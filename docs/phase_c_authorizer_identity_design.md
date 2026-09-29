# Phase C — Conception de l'identité de l'autorisateur

- **Date :** 2026-09-29
- **Référence :** `main` à `f333cec7a4ad3e4d8fa5e007b8248b7527daab43` (fusion de la PR #1, CI verte : tests + `NO_DRIFT`)
- **Statut :** document de conception. Il n'implémente rien, n'autorise rien et ne choisit aucune solution.

Ce document traite la condition 1 de [`phase_a_real_generation_decision.md`](phase_a_real_generation_decision.md) (« identité authentifiée de l'autorisateur »). Cette condition **reste ouverte** et reste à elle seule un motif de **NO-GO**. Rien ici ne rend la génération réelle possible : **Provider = CLOSED**, et les quatre verrous d'exécution décrits dans la décision de Phase A sont inchangés.

## 1. État actuel vérifié

Constaté dans le code à la référence ci-dessus :

- **Aucun mécanisme d'identité.** `agents/`, `integrations/`, `scripts/` et `director.py` ne contiennent ni authentification d'utilisateur, ni signature, ni HMAC, ni clé, ni identifiant d'opérateur. La seule authentification présente est celle du CLI Higgsfield (`integrations/higgsfield/client.py`), qui concerne le compte fournisseur et non la personne qui autorise. `agents/certificate_integrity.py` déclare explicitement n'utiliser ni clé ni secret HMAC.
- **Ce qui tient lieu d'autorité humaine.** `RealGenerationAuthorization` (`agents/generation_approval_gate.py`) est une dataclass figée constructible par tout code du processus :
  - `authorized_by_human` est un booléen fourni par l'appelant. Il n'a pas de valeur par défaut et la Gate exige qu'il soit littéralement `True` ;
  - `note` est un texte libre que la Gate ne lit jamais : ce n'est pas une preuve d'identité ;
  - `authorization_id` et `authorized_at` sont générés par défaut à la construction, ou fournis par l'appelant.
- **Création.** Aucun module de `agents/`, `integrations/` ni `director.py` ne construit d'autorisation. Hors des tests, seul `scripts/demo_test.py` en construit une, pour une démonstration limitée à `MockHiggsfieldProvider`. Ailleurs, l'autorisation est fournie par l'appelant à `AIDirector.run_video_mission()`, `prepare_real_generation_activation()` ou `compose_controlled_activation()`.
- **Vérification bloquante (Gate).** Sont vérifiés : le type, `authorized_by_human is True`, le `request_id` exact, la fraîcheur (300 s, d'après `authorized_at`), les empreintes du prompt, de l'avatar et de la référence visage, et la non-consommation. Les contrats P2.21 et P2.26 exigent de plus le même `authorization_id`.
- **Consommation.** `GenerationJobService.execute()` appelle `gate.consume_authorization()` avant le marqueur « en vol » et `create_job()`. Le registre local ne contient que `sha256(authorization_id)`.
- **Dépendances disponibles.** Le dépôt ne déclare aucune dépendance (ni `requirements`, ni `pyproject`). Côté Python 3.14, la bibliothèque standard fournit `hmac` et `secrets`. `cryptography`, `nacl`, `jwt`, `keyring` et `pyotp` ne sont pas installés.

Conséquence : l'autorisation prouve la **cohérence** de ce qui serait exécuté (requête, contenu, contrats, fraîcheur, usage unique), jamais **qui** a consenti.

## 2. Acteurs, actifs et frontières de confiance

**Acteurs**

| Acteur | Rôle | Capacités actuelles |
|---|---|---|
| Propriétaire du projet | Décide de toute ouverture et fixe le plafond de crédits | Tous les droits sur le dépôt et le poste |
| Opérateur autorisateur | Humain qui consent à une génération précise | Aujourd'hui indiscernable du code qui l'appelle |
| Code du dépôt | Director, agents, scripts | Peut construire une autorisation valide (tout objet est constructible en mémoire) |
| Automatisation sous le même compte système | Scripts, CI locale, assistant IA exécutant des commandes | Mêmes droits que l'opérateur sur les fichiers, `state/`, les variables d'environnement et l'entrée standard |
| Code tiers chargé dans le processus | Bibliothèques importées | Même mémoire que le Director |
| Fournisseur Higgsfield | Facture via le CLI authentifié | Hors du périmètre de confiance du projet ; `create_job` est fermé côté client et Provider |
| Attaquant local | Accès au poste ou au compte | Peut lire et modifier le dépôt, `state/` et les clés lisibles par le compte |

**Actifs** : crédits Higgsfield ; contenu approuvé (prompt, avatar, référence visage) ; enregistrement du consentement ; registre de consommation ; futurs secrets d'identité.

**Frontières de confiance**

1. **Processus Python.** Tout ce qui s'y exécute partage la même mémoire : un objet ou une valeur vérifiable par la Gate peut aussi être produit par un autre code du même processus.
2. **Compte système du poste.** Tous les processus du compte lisent les mêmes fichiers (`state/`, dépôt, clés éventuelles), les mêmes variables d'environnement et le même terminal.
3. **Dépôt Git et CI.** Le code et la documentation sont versionnés. La CI exécute les tests et l'audit, sans aucun secret d'identité.
4. **Compte Higgsfield.** C'est une identité de facturation, pas une identité d'autorisateur.
5. **Canal humain hors bande** (appareil, application, service séparé). **Il n'existe pas aujourd'hui dans le projet.**

**Menaces principales (STRIDE)**

| Type | Scénario | Protection actuelle |
|---|---|---|
| Usurpation | Du code ou une automatisation construit `RealGenerationAuthorization(authorized_by_human=True)` avec les empreintes calculées par `authorization_content_digests()` | Aucune : c'est l'objet de la condition 1 |
| Altération | `authorized_at` fourni par l'appelant (fraîcheur auto-déclarée) ; suppression manuelle du registre de consommation | Fraîcheur et usage unique vérifiés, mais sur des données contrôlées par l'appelant ou le compte |
| Répudiation | Impossible d'établir qui a consenti ; `note` n'est ni vérifiée ni persistée | Aucune (voir aussi la condition 5, journal durable) |
| Déni de service | Consommer d'avance l'`authorization_id` d'autrui, puisque cet identifiant est choisi par l'appelant | Échec fermé : aucune exécution, mais l'autorisation est perdue |
| Élévation | Contourner la chaîne P2 par le client ou le Provider | Quatre verrous fermés (P3.83, identité de méthode, `raise` inconditionnels) |

## 3. Limites d'un mécanisme exécuté dans le même processus

1. **Tout ce que le vérificateur peut lire, le code voisin peut le lire.** Une clé, un jeton ou un fichier accessible au processus qui vérifie est aussi accessible au code qui voudrait fabriquer l'autorisation. Une vérification symétrique (HMAC) faite dans le processus ne sépare donc pas celui qui signe de celui qui vérifie.
2. **Une saisie interactive ne prouve pas la présence d'un humain.** `input()` ou une invite dans le terminal peut être satisfaite par une entrée redirigée, un script ou un agent qui pilote le terminal.
3. **Le compte système identifie un compte, pas une personne.** Toute automatisation lancée sous ce compte obtient le même résultat.
4. **La frontière Provider est elle aussi dans le processus.** `HiggsfieldProvider` s'exécute dans le même processus que le Director : il ne constitue pas une frontière de confiance indépendante.
5. **Une garantie forte suppose une ancre externe.** Il faut un secret ou un appareil hors de portée de l'automatisation du compte, et un énoncé signé ou confirmé hors du processus. À défaut, un mécanisme interne ne fait que relever le niveau d'effort et améliorer la traçabilité. Il ne satisfait pas la condition 1.

## 4. Exigences de liaison

Toute solution future devra respecter les exigences suivantes. La vérification échoue fermée à chaque étape.

- **L1 — Énoncé canonique signé ou confirmé.** L'identité atteste un énoncé unique, versionné et sérialisé de façon déterministe : JSON à clés triées, UTF-8, empreintes en hexadécimal minuscule. Il contient au minimum :
  - l'identifiant du sujet authentifié et le mécanisme utilisé ;
  - `authorization_id` et `request_id` ;
  - `prompt_sha256`, `avatar_sha256` et `face_reference_sha256`, calculés comme dans `authorization_content_digests()` ;
  - `job_type`, `duration`, `resolution` et `aspect_ratio` ;
  - le plafond de crédits par requête, fixé par le propriétaire (aucun montant n'est fixé ici) et au moins égal au coût attendu ;
  - `issued_at` et `expires_at` (au plus 300 s), plus un nonce à usage unique.
- **L2 — Vérification à la Gate.** La Gate vérifie l'attestation contre la requête réellement évaluée : champs de L1 et empreintes recalculées. Attestation absente, mal formée, expirée, déjà consommée ou non concordante : jamais `APPROVED`.
- **L3 — Contrats.** P2.21 et P2.26 portent l'empreinte de l'énoncé attesté, et refusent un contrat dont l'énoncé diffère de celui de la requête, en plus de la comparaison d'`authorization_id` déjà en place.
- **L4 — Paramètres vidéo et coût.** Toute divergence de `job_type`, `duration`, `resolution`, `aspect_ratio`, ou tout coût attendu supérieur au plafond attesté, bloque. Un coût `UNKNOWN` bloque dans tous les cas (condition 4).
- **L5 — Usage unique et rejeu.** Le nonce et `authorization_id` sont consommés de façon atomique avant tout appel d'exécution. Une attestation rejouée, même valide, est refusée. L'émetteur choisit l'identifiant, jamais l'appelant.
- **L6 — Aucun secret persisté.** Ni le dépôt, ni `state/`, ni les journaux, ni les rapports ne contiennent de clé, de jeton ou de secret. Le journal (condition 5) ne garde que des identifiants et des empreintes.
- **L7 — Frontière.** Le Provider reçoit l'empreinte de l'énoncé attesté et la compare aux valeurs réellement transmises. Cela ne lève aucun des quatre verrous : seule une décision distincte de réouverture pourrait le faire.
- **L8 — Testabilité.** Tout est vérifiable par des tests mock-only, sans réseau, sans génération réelle et sans secret réel dans le dépôt.

## 5. Comparaison des options

Aucune de ces options n'est disponible ni validée dans le projet aujourd'hui. Le tableau décrit ce que chacune prouverait si ses hypothèses étaient établies.

| Option | Hypothèses | Ce qu'elle prouve | Ce qu'elle ne prouve pas | Preuves de disponibilité à obtenir |
|---|---|---|---|---|
| **A. Compte système** (utilisateur Windows courant, SID) | Le projet tourne sous un compte connu | Que le processus s'exécute sous tel compte | Ni la personne, ni sa présence, ni son intention. Toute automatisation du même compte passe (limites 1 à 3) | Liste des comptes qui exécutent le projet, et assurance qu'aucune automatisation (CI locale, assistant) n'utilise le même compte. Disponible techniquement via la bibliothèque standard, mais ne satisfait pas la condition 1 à lui seul |
| **B. Confirmation hors bande** (code dérivé de l'énoncé L1, confirmé sur un appareil ou canal séparé) | Canal contrôlé par l'opérateur seul, inaccessible à l'automatisation du compte ; l'énoncé affiché est exactement celui qui est lié | Qu'un détenteur du canal a confirmé cet énoncé précis | L'identité au-delà de la possession du canal. Si le secret de vérification (par exemple la graine TOTP) est lisible par le processus, on retombe dans la limite 1 | Canal existant et contrôlé ; méthode de vérification hors du processus, ou secret hors du compte. Aucune bibliothèque OTP n'est installée (`pyotp` absent) et aucun service n'est configuré |
| **C. HMAC avec clé hors dépôt** (`hmac` de la bibliothèque standard) | Clé générée et stockée hors du dépôt et de `state/` ; signature faite dans un contexte séparé (autre compte ou appareil) | Qu'un détenteur de la clé a signé l'énoncé L1 | Si le vérificateur (la Gate) détient la même clé, il peut aussi signer : HMAC ne sépare pas signataire et vérificateur (limite 1). Ne prouve pas la présence humaine | `hmac` et `secrets` sont disponibles. Le stockage séparé de la clé (coffre système, autre compte, appareil) n'est pas démontré. Une signature asymétrique (par exemple Ed25519), qui séparerait signataire et vérificateur, demanderait une bibliothèque non installée (`cryptography` et `nacl` absents) |
| **D. Fournisseur d'identité externe** (OIDC/OAuth, SSO, identité GitHub) | Fournisseur configuré, application enregistrée, validation des jetons (signature, audience, expiration, horloge), accès réseau | Que le fournisseur a authentifié un principal à un instant donné, avec les facteurs qu'il impose | Que ce principal a approuvé l'énoncé L1, sauf si le jeton ou l'approbation porte sur cet énoncé. Dépend de la disponibilité du réseau et du fournisseur | Aucun fournisseur configuré, aucune dépendance (`jwt` absent), aucun code d'authentification réseau. L'authentification du CLI Higgsfield ne s'applique pas à l'autorisateur. `gh` n'est pas installé sur le poste de développement |

Observations factuelles :

- Seules les options où le secret ou l'appareil de signature est **hors de portée du compte et du processus** (B avec vérification externe, C avec signature séparée, D) peuvent répondre à l'usurpation décrite en section 2.
- L'option A et les variantes « dans le processus » de B et C améliorent la traçabilité, mais ne satisfont pas la condition 1.
- Toutes les options exigent L1 à L8. Aucune ne dispense des conditions 3 (plafond), 4 (`UNKNOWN` bloquant) et 5 (révocation et journal).

## 6. Critères de décision

Le choix appartient au **propriétaire du projet**. Ce document ne recommande aucune option de façon contraignante. Critères proposés, par ordre de priorité :

1. **Résistance à l'usurpation.** L'option empêche-t-elle du code ou une automatisation du même compte de produire une attestation valide ?
2. **Complétude de la liaison.** Couvre-t-elle L1 à L7, dont les paramètres vidéo et le plafond de coût ?
3. **Échec fermé.** Toute indisponibilité (réseau, appareil, clé, horloge) bloque-t-elle sans jamais produire `APPROVED` ?
4. **Disponibilité démontrée.** Les preuves de la section 5 existent-elles, versionnables sans secret ?
5. **Aucun secret dans le dépôt, `state/` ou les journaux** (L6).
6. **Testabilité mock-only** (L8), sans réseau ni crédit.
7. **Coût opérationnel et réversibilité.** Faut-il des appareils, des comptes ou des procédures de perte ou de rotation de clé ?
8. **Indépendance vis-à-vis de Higgsfield.** L'identité de facturation n'est pas une identité d'autorisateur.

## 7. Ce que cette phase ne fait pas

- Aucune modification de `agents/`, `integrations/`, `director.py` ni `scripts/`.
- Aucune solution d'identité introduite ou activée ; aucune dépendance ajoutée.
- Aucun verrou desserré ; aucune génération réelle ; aucun crédit consommé.
- La condition 1 reste **ouverte** et le **NO-GO** reste en vigueur.
- Des gardes de non-régression (`tests/test_phase_c_identity_nogo_invariants.py`) vérifient que le code ne prétend pas authentifier d'identité, que `note` n'est pas une preuve d'identité, que la condition 1 reste un motif de NO-GO et que les quatre verrous restent fermés.

## 8. Suite possible, sur décision seulement

1. Le propriétaire choisit une option, avec ses preuves de disponibilité (section 5), et fixe le plafond de crédits (condition 3).
2. Une phase d'implémentation distincte réalise L1 à L8, en échec fermé et avec des tests mock-only. Le Provider reste fermé.
3. Seule une nouvelle décision écrite, distincte de la décision de Phase A, pourrait constater que les sept conditions sont remplies.

**Provider = CLOSED · Real generation = 0 · Credits = 0**
