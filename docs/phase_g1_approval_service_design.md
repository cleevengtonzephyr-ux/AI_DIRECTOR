# Phase G1 — Conception du service d'approbation humaine

- **Date :** 2026-10-07
- **Référence :** `main` à `f687973568d787e2b2e0051a4632cbbe962de94b` (fusion de la PR #6, Phase F)
- **Statut :** document de conception, corrigé après une revue de sécurité en lecture seule. D-1 reprend une instruction explicite du propriétaire ; D-2 à D-5 sont choisies sous sa délégation explicite du 2026-10-07. Les autres décisions ouvertes restent à trancher. Ce document n'implémente rien, n'autorise rien et ne déploie rien.

**NO-GO en vigueur. Provider = CLOSED.** La décision de [`phase_a_real_generation_decision.md`](phase_a_real_generation_decision.md) est inchangée. Ce document prolonge la conception de l'identité ([`phase_c_authorizer_identity_design.md`](phase_c_authorizer_identity_design.md)), celle des limites de l'autorisation, du plafond, de la révocation et de l'arrêt ([`phase_e_authorization_limits_ceiling_revocation_shutdown_design.md`](phase_e_authorization_limits_ceiling_revocation_shutdown_design.md)) et le chemin de production fermé ([`phase_f_production_path_design.md`](phase_f_production_path_design.md)). Il ne résout aucune des sept conditions de la Phase A. Aucun des quatre verrous d'exécution ni des verrous F-1 à F-4 n'est modifié.

Pendant cette phase : aucun code, workflow, test, verrou, paramètre serveur, réglage GitHub ou enregistrement DNS n'a été modifié ; aucun secret ni aucune clé n'a été créé ou lu ; aucun logiciel n'a été installé ; aucun port n'a été ouvert ; rien n'a été déployé ; Higgsfield n'a pas été contacté ; aucun workflow n'a été lancé.

## 1. Rôle prévu du serveur

### 1.1 Architecture retenue pour la conception (D-1)

Le choix de conception est l'option **E-2, courtier** : le serveur Scaleway à Paris hébergerait un **service d'approbation humaine**, joignable sous `zephyr-approval.fr`. Si une clé API dédiée à ce chemin est créée ultérieurement, le serveur en serait le seul détenteur ; il conserverait aussi l'état durable anti-rejeu sur son volume persistant. Cette décision ne prétend pas contrôler les autres accès au compte Higgsfield (section 4.10). Le service :

1. reçoit d'un run GitHub Actions une **demande d'approbation** authentifiée par un jeton OIDC GitHub, portant l'empreinte du manifeste calculé par le job `prepare` (Phase F) ;
2. présente à un humain l'**énoncé canonique** de cette demande (dépôt, commit, workflow, run, manifeste, paramètres, plafond) ;
3. recueille l'**approbation** de cet humain par une assertion **WebAuthn** dont le défi est dérivé de cet énoncé ;
4. conserve dans un **stockage durable transactionnel** l'état de chaque demande, les nonces, les consommations, les révocations, l'interrupteur global et le journal ;
5. ne délivre une autorisation qu'**une seule fois**, à ce même run, dans sa fenêtre de validité.

Le service ne décide jamais d'ouvrir le Provider. Tant que la décision de la Phase A est en vigueur, aucune issue d'un run ne soumet quoi que ce soit. L'issue nominale du script de Phase F est l'arrêt sur Provider = CLOSED (code 4). Ses autres codes sont aussi des refus : 2 (entrée ou manifeste invalide), 3 (manifeste divergent), 5 (reprise refusée), 6 (journal corrompu ou impossible à écrire) (`scripts/higgsfield_production_run.py`, docstring et constantes `EXIT_*`).

### 1.2 Décisions prises, faits et décisions ouvertes

| Catégorie | Contenu | Source |
|---|---|---|
| **Décision prise par le propriétaire** | Hébergement chez **Scaleway**, région **Paris** | Instruction du propriétaire |
| **Décision prise par le propriétaire** | Domaine stable **`zephyr-approval.fr`** | Instruction du propriétaire |
| **Décision prise par le propriétaire** | **Objectif budgétaire maximal de 50 € par mois, taxes comprises**, pour l'ensemble des coûts récurrents. C'est un objectif : le coût réel TTC n'est ni constaté ni garanti (section 8) | Instruction du propriétaire |
| **Décision prise par le propriétaire** | Le serveur est préparé, mais aucune application web n'y est déployée | Instruction du propriétaire |
| **Vérifié dans le dépôt** | Phase F fusionnée : `main` = `origin/main` = `f687973` | Git local, après `git fetch` |
| **Vérifié dans le dépôt** | Aucun code de **serveur** HTTP, ni OIDC, ni WebAuthn, ni base de données. Le seul code HTTP est le transport **client** fermé de la Phase F (`integrations/higgsfield/https_transport.py`, `import http.client`), câblé à rien | Recherche dans le code |
| **Vérifié dans le dépôt** | Bibliothèque standard uniquement ; `cryptography`, `jwt` et `nacl` ne sont pas déclarés | README, Phase C §1 |
| **Vérifié dans le dépôt** | Seule plateforme validée : CPython 3.14 sous Windows | `.python-version`, `tests/test_p3_106_python_version.py`, README |
| **Vérifié dans le dépôt** | Le workflow de Phase F s'exécute sur `windows-2025`, sans `id-token: write` et sans référence à un secret | `.github/workflows/higgsfield-production.yml` |
| **Déclaré par le propriétaire, non vérifié par cette phase** | CI de la PR #6 verte : tests unitaires et audit `NO_DRIFT` | Instruction du propriétaire |
| **Déclaré par le propriétaire, non vérifié par cette phase** | Configuration actuelle du serveur | Section 6 |
| **Décision prise par le propriétaire** | D-1 : option E-2 (courtier) ; toute clé API dédiée à ce chemin serait détenue uniquement par le serveur, qui conserve l'état durable anti-rejeu sur son volume persistant. Choix de conception seulement : rien n'est implémenté et aucune clé n'a été créée | Instruction explicite du propriétaire, 2026-10-07 |
| **Ouvert** | Moteur de stockage, sauvegardes, rétention, ancre externe | Section 3, décisions D-6 et D-7 |
| **Décision prise sous délégation explicite du propriétaire** | D-2 : WebAuthn est le seul facteur normal d'approbation ; la vérification locale de l'utilisateur est obligatoire ; l'inscription est réservée à une invitation à usage unique créée par SSH d'administration | Section 4.4, décision D-2 |
| **Décision prise sous délégation explicite du propriétaire** | D-3 : deux identifiants WebAuthn distincts sur deux authentificateurs séparés ; fermeture immédiate et révocation en cas de perte ; remplacement seulement par la procédure SSH d'administration | Section 4.4, décision D-3 |
| **Décision prise sous délégation explicite du propriétaire** | D-4 : passkeys de plateforme et clés de sécurité acceptées ; une passkey synchronisable peut servir d'identifiant courant, mais le secours doit être un identifiant distinct non synchronisable (`BE=0`) | Section 4.4, décision D-4 |
| **Décision prise sous délégation explicite du propriétaire** | D-5 : une approbation WebAuthn par une personne autorisée distincte de l'acteur GitHub qui a lancé le run ; aucun auto-approuveur et aucun quorum supplémentaire | Section 4.4, décision D-5 |
| **Ouvert** | Forme de la réponse du service et sa vérification par le Director | Section 4.11, décision D-18 |
| **Ouvert** | Réapprobation d'un même manifeste | Section 4.6, décision D-17 |
| **Ouvert** | Exposition web : ports, TLS, reverse proxy | Section 7, décision D-12 |
| **Ouvert** | Plafonds de dépense (aucun montant) | Décision D-14 |
| **Ouvert** | Coût mensuel total réel, TTC | Section 8 |

## 2. Contradictions et contraintes héritées

| Constat | Conséquence pour G |
|---|---|
| La Phase F constate que les runners GitHub sont éphémères et que son journal, écrit dans `RUNNER_TEMP`, disparaît : aucun anti-rejeu entre exécutions | Selon D-1, le serveur et son volume persistant sont l'emplacement retenu en conception pour l'état durable. La base et les mécanismes restent à choisir (D-6 et D-7) |
| `approval_id` vaut `gh-<run_id>` et n'est vérifié par rien (Phase F §5) | L'identifiant d'approbation doit être choisi par le service, jamais par le run (exigence L5 de la Phase C) |
| L'approbation d'un environnement GitHub porte sur un déploiement, pas sur l'empreinte du manifeste (Phase F §5) | L'assertion WebAuthn doit porter cryptographiquement sur l'énoncé qui contient `manifest_sha256` |
| Le dépôt n'utilise que la bibliothèque standard | Elle ne fournit aucune API de vérification de signature RS256 (jeton OIDC) ou ECDSA/Ed25519 (WebAuthn). Il faudrait une dépendance tierce : c'est une décision du propriétaire (D-13). Une implémentation cryptographique maison est écartée |
| Le code n'est validé que sous Windows. Deux familles de tests ne s'exécutent que sous Windows (`skipUnless(os.name == "nt")`) : **tests de verrou** P3.97, P3.98 et P3.102 ; **tests du CLI** propres à `cmd.exe` et aux shims `.cmd`, P2.1, P2.3 (transport multiligne) et P3.92 (R1, R2) | Le comportement des verrous sous Ubuntu est à démontrer (section 9). Les tests CLI concernent l'invocation Windows du CLI Higgsfield, pas le service |
| Les écritures atomiques (`tempfile` + `fsync` + `os.replace`) ne synchronisent pas le répertoire parent (aucun `O_DIRECTORY` dans `agents/`) | Sous Linux, un renommage peut ne pas être durable après une coupure de courant. À prouver ou à corriger avant tout usage serveur (section 9) |
| Les verrous `O_CREAT | O_EXCL` laissent un fichier orphelin après un crash (limite documentée de `agents/critical_section_lock.py`) | Un service long ne peut pas reposer sur ces fichiers sans procédure de reprise. Un moteur transactionnel ne présente pas cette limite **pour ses propres verrous**, à condition que rien n'ouvre ni ne manipule le fichier de base en dehors du moteur |

## 3. Stockage durable transactionnel

### 3.1 Besoins

Le stockage doit garantir, sur un serveur unique :

- **Atomicité** : une transition d'état (par exemple `APPROVED` vers `CONSUMED`), l'enregistrement du nonce consommé et l'entrée de journal sont écrits ensemble ou pas du tout. **Portée par rapport à la limite A2-f de la Phase E** : A2-f concerne le Director (`consumed_authorizations.json` et le marqueur « en vol » de `GenerationJobService`). Une transaction du service ne la ferme côté service que si la consommation et le marqueur « en vol » y sont écrits ensemble, ce qui n'est envisageable qu'en option E-2 (section 4.10). En option E-1, A2-f subsiste dans le runner ;
- **Unicité** : contraintes d'unicité sur le nonce, l'identifiant d'approbation, le couple (`run_id`, `run_attempt`) et la clé d'idempotence ;
- **Concurrence** : plusieurs processus ou threads du service ne peuvent pas consommer deux fois la même approbation. Une mise à jour conditionnelle (`… WHERE state = 'APPROVED'`, avec contrôle du nombre de lignes modifiées) dans une transaction sérialisée suffit à l'exprimer ;
- **Durabilité** : une transaction confirmée au client survit à un arrêt brutal du processus et du système invité, dans les limites de la section 3.3 sur le stockage hébergé ;
- **Sauvegarde et restauration** sans rouvrir de rejeu non détecté (section 3.4) ;
- **Échec fermé** : base absente, corrompue, verrouillée, en lecture seule ou mal configurée entraîne un refus, jamais `APPROVED`.

### 3.2 Comparaison des options

Aucune option n'est choisie ici. Les versions disponibles sur Ubuntu 26.04.1 et les prix sont à vérifier.

| Critère | **S-1. SQLite** sur le volume ext4 | **S-2. PostgreSQL local** | **S-3. Base managée** (par exemple PostgreSQL managé chez Scaleway) | **S-4. Fichiers JSON actuels** (`os.replace`) |
|---|---|---|---|---|
| Atomicité | Transactions ACID ; plusieurs tables modifiées dans une même transaction | Transactions ACID complètes | Transactions ACID complètes | Une écriture atomique par fichier ; aucune transaction entre fichiers |
| Concurrence inter-processus | Un seul écrivain à la fois, lecteurs concurrents en mode WAL. `BEGIN IMMEDIATE` prend le verrou d'écriture dès le début et évite les échecs d'escalade. Fonctionne entre processus d'une même machine sur un système de fichiers local, pas sur un partage réseau. Les verrous POSIX de SQLite peuvent être perdus si le même processus ouvre puis ferme le fichier de base par un autre moyen | MVCC, nombreux écrivains, niveau `SERIALIZABLE` disponible | Comme S-2 | Verrous `O_EXCL` maison ; fichiers orphelins après crash |
| Durabilité après panne | Avec `journal_mode=WAL` et `synchronous=FULL`, le WAL est synchronisé à chaque validation. Avec `synchronous=NORMAL` en WAL, les dernières transactions peuvent être perdues après une coupure de courant : réglage à proscrire ici. `journal_mode` est persistant dans le fichier, mais `synchronous` est un réglage **par connexion** | `fsync=on`, `synchronous_commit=on`, `full_page_writes=on` (valeurs par défaut à vérifier) | Gérée par l'hébergeur, selon son offre ; à vérifier | Répertoire parent non synchronisé (section 2) |
| Dépendance d'exécution | Module `sqlite3` de la bibliothèque standard : **aucune dépendance Python tierce** | Pilote tiers (par exemple `psycopg`) et paquet serveur | Pilote tiers ; accès réseau ; identifiants de base sur le serveur | Aucune |
| Sauvegarde et restauration | Sauvegarde en ligne cohérente par `Connection.backup()` ou `VACUUM INTO`. Ne jamais copier le fichier principal seul pendant le fonctionnement en WAL. Restauration : service arrêté ; fichiers `-wal` et `-shm` de l'ancienne base supprimés ou traités explicitement, jamais laissés à côté de la base restaurée ; remplacement du fichier ; `PRAGMA integrity_check` | `pg_dump` (logique) ou sauvegarde de base + archivage WAL (restauration à un instant donné) | Sauvegardes et restauration gérées, selon l'offre | Copie de fichiers |
| Maintenance | Faible : un fichier ; réglages à poser **et à relire** à chaque connexion (`synchronous`, `foreign_keys`, `busy_timeout`) ; surveiller la taille du WAL et les checkpoints | Moyenne : mises à jour majeures (`pg_upgrade`), configuration de l'authentification, supervision. Écoute possible sur socket Unix seulement, sans port réseau | Faible côté serveur ; dépend de la console et des API de l'hébergeur | Faible, mais logique de verrou et de reprise à maintenir soi-même |
| Empreinte sur 2 vCPU / 4 Go | Négligeable | Modeste, à mesurer | Aucune sur le serveur | Négligeable |
| Coût récurrent supplémentaire | Aucun pour le moteur ; stockage de sauvegarde à compter | Aucun pour le moteur ; stockage de sauvegarde à compter | **Abonnement supplémentaire**, à intégrer à l'objectif budgétaire de 50 € par mois TTC avant tout choix | Aucun |
| Limites principales | Un seul écrivain ; pas d'accès depuis plusieurs machines | Surface et maintenance plus grandes pour un service à faible volume | Coût ; dépendance au réseau et au plan de contrôle de l'hébergeur ; un secret de base de données de plus | Pas de transaction ; ne répond pas aux besoins de la section 3.1 |

### 3.3 Recommandation conditionnelle

Elle ne vaut pas décision : le choix appartient au propriétaire (D-6).

- **Si** le service reste sur un seul serveur, avec un faible volume d'écritures, un seul processus écrivain ou des écritures sérialisées par `BEGIN IMMEDIATE`, et que le propriétaire veut éviter toute dépendance et tout coût supplémentaire, **alors S-1 (SQLite)** paraît proportionné. Configuration à démontrer : `journal_mode=WAL` ; `synchronous=FULL` posé à chaque connexion puis **relu**, avec refus de servir si la valeur relue diffère ; `foreign_keys=ON` ; `busy_timeout` borné ; transactions explicites (attribut `autocommit` du module `sqlite3`, disponible depuis Python 3.12) ; fichier sous `/srv/ai-director-data` appartenant à `aidirector` et illisible par les autres comptes.
- **Si** plusieurs processus écrivains indépendants ou une évolution vers plusieurs machines sont prévus, **alors S-2** est plus adapté, au prix d'une dépendance tierce et d'une maintenance accrue.
- **S-3** n'est envisageable que si son coût réel TTC, ajouté aux autres postes, reste dans l'objectif de 50 € par mois, preuve à l'appui (section 8).
- **S-4** ne répond pas aux besoins transactionnels de la section 3.1.

**Preuves nécessaires avant tout choix définitif :**

1. Version de SQLite (ou de PostgreSQL) réellement fournie par Ubuntu 26.04.1, et version de Python disponible sur le serveur.
2. Le volume ext4 est monté sans option désactivant les barrières d'écriture, et un arrêt brutal du processus puis du système invité ne perd aucune transaction confirmée (section 9, exigence X4).
3. Sauvegarde puis restauration complètes, réalisées et consignées, y compris les scénarios de la section 3.4.
4. Pour S-3 : devis ou tarif courant, montant TTC constaté, et mode de connexion (réseau privé ou point d'accès public avec TLS).

**Limite non démontrable par ces essais :** une réinitialisation brutale de la machine virtuelle prouve la tenue après un crash du système invité. Elle ne prouve pas la tenue du stockage de l'hébergeur en cas de défaillance côté hôte (cache, alimentation, réplication). Cette durabilité reste une **hypothèse de confiance** envers Scaleway et ses engagements de service, à consigner comme telle.

### 3.4 Restauration et rejeu

Restaurer une sauvegarde prise à l'instant T **fait réapparaître comme non consommés** les nonces et approbations consommés après T. C'est la limite A2-e de la Phase E, appliquée à la base.

**Les risques ne sont pas tous les mêmes :**

- une approbation `APPROVED` ressuscitée est déjà bornée par son expiration (au plus 300 s après la signature, section 4.5), tant que l'horloge du serveur ne recule pas (limite A2-g) ;
- le risque principal est la **perte d'un état `IN_FLIGHT`** ou `AMBIGUOUS` postérieur à T. Le service croirait qu'aucun envoi n'a eu lieu, et une nouvelle approbation du même manifeste pourrait conduire à une **double soumission**, donc à une double dépense, le jour où un Provider serait ouvert. Le rapprochement par lecture seule de l'historique du fournisseur n'est pas démontré : l'endpoint de statut REST et ses valeurs ne sont pas confirmés (Phase F §5).

**Mesures à concevoir et à tester, aucune n'étant choisie (D-7) :**

- **Témoin de restauration hors de l'ensemble sauvegardé.** Une époque de restauration et la dernière tête de journal connue ne peuvent pas vivre **uniquement** dans la base : restaurées avec elle, elles reviendraient à leur ancienne valeur. Elles doivent être conservées ailleurs, au minimum dans un fichier séparé exclu des sauvegardes de la base et, pour être utiles, dans une ancre externe. Au démarrage, le service refuse de servir si la base et le témoin divergent ;
- **Interrupteur fermé d'office** dès qu'une divergence ou une restauration est constatée. La réouverture suit D-9 ;
- **Rapprochement obligatoire** de tout état `IN_FLIGHT` ou `AMBIGUOUS` possiblement perdu, avant toute nouvelle demande. Faute d'un moyen de rapprochement démontré, le service reste fermé ;
- **Ancre externe** de la tête du journal (option J-c de la Phase E).

**Limites sans ancre externe :**

- un témoin local reste supprimable par le compte (limite A2-e) ;
- une restauration de l'**ensemble du volume** (par exemple par instantané de l'hébergeur) restaure aussi le témoin local, et n'est alors **pas détectée** ;
- une restauration faite hors procédure, sans signalement, n'est détectée que par une ancre externe.

Sans ancre externe, ces cas doivent être consignés comme **limites non détectées**, et non comme couverts.

## 4. Architecture d'approbation proposée

Toute cette section est une **proposition**. Les éléments qui dépendent d'une décision ouverte le signalent.

### 4.1 Vue d'ensemble

```
GitHub Actions (main)                       Serveur zephyr-approval.fr                  Humain
──────────────────────                      ──────────────────────────                  ──────
job prepare : calcule manifest_sha256
job request (id-token: write, audience A)
  ── jeton OIDC + manifeste canonique ─────► vérifie le jeton (§4.2)
                                             vérifie le commit autorisé (§4.3)
                                             crée la demande PENDING :
                                             approval_id, nonce, échéances
  ◄── approval_id ───────────────────────────
                                             page d'approbation ◄──────────────────── se connecte
                                             affiche l'énoncé canonique ─────────────► lit
                                             défi = H(énoncé, nonce)
                                             vérifie l'assertion WebAuthn ◄────────── approuve (§4.4)
                                             PENDING → APPROVED (+ journal)
job execute (environnement protégé, audience B)
  ── jeton OIDC (même run) + approval_id ──► vérifie, puis APPROVED → CONSUMED
                                             en une transaction (§4.6)
  ◄── réponse unique (forme : §4.11, D-18) ──
script Phase F : recalcul, comparaison,
arrêt sur Provider = CLOSED (code 4)
```

Ce schéma ne modifie pas le workflow de Phase F, qui ne demande aujourd'hui aucun jeton OIDC.

### 4.2 Identité du run : OIDC GitHub

Le job qui sollicite le service demanderait un jeton OIDC (permission `id-token: write`, limitée à ce seul job). Pour empêcher qu'un jeton destiné à une interface soit présenté à une autre, chaque interface du service aurait sa **propre audience** : l'une pour la demande, l'autre pour la consommation. Le service vérifierait, sous réserve de confirmation des noms et formats exacts :

- la signature, avec les clés publiées par l'émetteur `https://token.actions.githubusercontent.com`, en n'acceptant que l'algorithme attendu ; `alg=none`, un algorithme symétrique ou un `kid` inconnu sont refusés ;
- `iss`, `aud` (l'audience propre à l'interface appelée), `exp`, `iat` et `nbf`, avec une tolérance d'horloge bornée ;
- `repository_id` et `repository_owner_id` : identifiants numériques, stables même en cas de renommage, préférés aux noms ;
- `ref` = `refs/heads/main`, `event_name` = `workflow_dispatch` ;
- `workflow_ref` et `job_workflow_ref` : chemin exact du workflow sur `refs/heads/main` ;
- `runner_environment` = `github-hosted`, pour refuser un runner auto-hébergé ;
- `sha` : présent dans la liste des commits autorisés (section 4.3) ;
- `environment` : environnement protégé attendu, si le propriétaire l'impose ;
- `run_id` et `run_attempt` (refus de toute valeur différente de 1, cohérent avec le script de Phase F) ;
- l'unicité du jeton, si un identifiant de jeton (`jti`) est présent.

**Ces claims ne sont pas tenus pour confirmés.** Leur présence, leurs noms et leurs formats sont à vérifier sur la documentation de GitHub et sur un jeton réel de test. Un tel essai exige une **autorisation explicite et distincte du propriétaire** (section 11, étape 3).

**Vol de jeton.** Le jeton est porteur. Un jeton du job `request` présenté à l'interface de consommation est refusé par l'audience. Un jeton de consommation volé pendant sa validité permettrait de consommer l'approbation avant le job légitime :
- en E-1, c'est un refus de service, l'échec restant fermé ;
- en E-2, cela déclencherait la soumission du manifeste approuvé.

D'où l'exigence de journaux sans jeton et d'actions épinglées.

### 4.3 Commits autorisés et contenu montré à l'approbateur

Le service n'accepte qu'un `sha` explicitement autorisé. Options, sans choix (D-10) :

- (i) tout commit atteignable depuis `main`, protégé par les règles de branche du dépôt ;
- (ii) liste explicite de commits, chacun inscrit par une action humaine authentifiée par WebAuthn sur le service ;
- (iii) étiquettes signées. Leur vérification sur le serveur suppose un outil de vérification de signature, donc une dépendance (D-13).

(ii) est la seule option qui lie l'inscription à la personne qui approuve ; (i) délègue cette confiance aux protections GitHub.

Le service ne peut pas recalculer lui-même le manifeste sans disposer des fichiers sources (prompt, avatar, référence visage). Options (D-11) :

- (a) faire confiance au manifeste transmis par un run dont le commit est autorisé. Le service peut recalculer `manifest_sha256` à partir de la forme canonique reçue, mais pas à partir des fichiers ;
- (b) conserver sur le serveur une copie figée des assets Video 005 et recalculer.

**Hypothèses de (a).** Le code exécuté par le job est celui du commit autorisé, y compris les actions épinglées. L'image du runner et les binaires téléchargés à l'exécution (par exemple l'interpréteur installé par `setup-python`) sont eux aussi intègres.

**Ce que voit l'approbateur.** La forme canonique du manifeste de Phase F contient le modèle, les paramètres et les empreintes des médias, mais pas le prompt ni les images. Avec (a), l'approbateur consent à des **empreintes**, pas à un contenu qu'il a vu. Avec (b), le service pourrait afficher le contenu, au prix d'une copie à maintenir et d'un contenu stocké sur le serveur.

### 4.4 Approbation humaine : WebAuthn

- **Relying Party** : identifiant `zephyr-approval.fr`, origine `https://zephyr-approval.fr`. WebAuthn exige un contexte sécurisé : HTTPS obligatoire en production (`localhost` est toléré pour les essais locaux).
- **Inscription (D-2 décidée)** : fermée par défaut ; elle n'est possible qu'au moyen d'une invitation d'inscription à usage unique et de courte durée, créée par l'administrateur depuis une session SSH. Cette invitation est la racine de confiance de l'inscription ; le premier drapeau UV d'un nouvel identifiant n'est pas traité comme une preuve d'identité ni comme le facteur qui autorise sa propre inscription. La vérification locale de l'utilisateur est demandée pendant l'inscription et vérifiée lorsqu'elle est signalée.
- **Récupération (D-3 décidée)** : avant toute activation future, l'approbateur doit avoir deux identifiants WebAuthn distincts liés à deux authentificateurs séparés ; l'un est le secours et reste conservé séparément. Plusieurs copies synchronisées du même identifiant ne comptent que comme un seul identifiant. Cette exigence suit la recommandation NIST de conserver au moins deux moyens d'authentification séparés ([SP 800-63B-4, §4.1.2.1](https://pages.nist.gov/800-63-4/sp800-63b.html)).
  - Perte, vol ou suspicion de compromission : traiter l'identifiant concerné comme compromis, fermer immédiatement l'interrupteur global, le révoquer et journaliser l'événement. Remplacement uniquement par une nouvelle invitation à usage unique créée depuis SSH, puis inscription et vérification de deux identifiants distincts. NIST recommande de suspendre ou révoquer rapidement un authentificateur compromis.
  - Si tous les identifiants WebAuthn sont perdus, aucune récupération autonome par courriel, SMS, code de récupération ou support tiers : seul l'administrateur via SSH peut lancer une nouvelle inscription ; tous les anciens identifiants sont révoqués. L'interrupteur reste fermé jusqu'à une réouverture conforme à D-9. Si la clé SSH d'administration ou l'intégrité du serveur est compromise, le service reste fermé et la confiance d'administration doit être rétablie (D-15).
- **Défi** : `SHA-256` d'une chaîne de séparation de domaine, de l'énoncé canonique (section 4.5) et du nonce choisi par le service. Le défi est à usage unique et expire avec la demande (`approval_deadline`).
- **Vérifications** :
  - signature avec la clé publique enregistrée ;
  - égalité exacte du défi ;
  - `rpIdHash`, origine, `type` = `webauthn.get`, `crossOrigin` absent ou faux ;
  - drapeau de présence (UP) ;
  - drapeau de vérification de l'utilisateur (UV), exigé pour chaque approbation ; si le client ou l'authentificateur ne peut pas effectuer cette vérification, la cérémonie échoue ;
  - identifiant de l'authentificateur (credential ID) connu et non révoqué ;
  - politique du compteur de signatures (souvent nul pour les passkeys synchronisées, donc inutilisable pour détecter un clonage) ;
  - drapeaux de sauvegarde (BE, BS) selon la politique D-4.
- **Politique D-4 des authentificateurs** : passkeys de plateforme et clés de sécurité sont acceptées si UV est disponible. Une passkey synchronisable (`BE=1`) est acceptée comme identifiant courant, mais ne satisfait pas l'exigence de secours de D-3. Le secours doit être un identifiant différent, conservé sur un authentificateur séparé, avec `BE=0` et `BS=0`. Le service enregistre `BE` à l'inscription, refuse qu'il change ensuite, et vérifie que `BS=1` n'apparaît jamais avec `BE=0` ; pour `BE=1`, `BS` peut évoluer avec l'état de sauvegarde. Aucune attestation AAGUID n'est exigée : le service se fonde sur les indicateurs WebAuthn et garde comme hypothèse que l'authentificateur les déclare correctement. Référence : [W3C WebAuthn Level 3, §6.1.3 et §7.2](https://www.w3.org/TR/webauthn-3/).
- **Portée de la vérification locale** : UV signifie que l'authentificateur a effectué une vérification locale, par exemple PIN, mot de passe de l'appareil ou biométrie. Cela ne donne pas au service une identité civile ; D-4 fixe une classe d'identifiants mais ne vérifie pas la personne qui les contrôle. Référence : [W3C WebAuthn Level 3](https://www.w3.org/TR/webauthn-3/), sections « User Verification » et « User Verification Requirement ».
- **Politique D-5 des approbateurs** : une seule approbation WebAuthn valide suffit ; aucun quorum de plusieurs approbateurs n'est exigé. L'approbateur doit être un compte autorisé distinct de l'acteur GitHub ayant lancé le run. L'auto-approbation est refusée ; si le service ne peut pas établir cette séparation de façon fiable, il refuse la demande. La procédure qui lie un compte d'approbateur à une personne, ainsi que les protections des comptes GitHub, restent soumises à D-15 ; WebAuthn UV ne prouve pas à lui seul l'identité civile.
- **Refus** de toute assertion valide sur un autre défi, d'un identifiant révoqué ou d'une demande qui n'est plus `PENDING`.

### 4.5 Énoncé canonique et fenêtre de validité

Il prolonge l'exigence L1 de la Phase C. Il est sérialisé en JSON à clés triées, UTF-8, empreintes en hexadécimal minuscule, et versionné. Contenu minimal :

- version de l'énoncé et identifiant de la Relying Party ;
- `repository_id`, `repository`, `sha`, `workflow_ref`, `run_id`, `run_attempt` (issus du jeton vérifié) ;
- `manifest_sha256` (modèle, paramètres vidéo et empreintes des médias, Phase F) ;
- `approval_id` et nonce, choisis par le service. `approval_id` doit respecter le format accepté par le script de Phase F (`[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`) ;
- `requested_at` (création de la demande), `approval_deadline` (délai d'attente de l'humain, D-8) et `validity_seconds` (au plus 300) ;
- plafond de crédits par requête : **aucun montant n'est fixé ici**. Tant que le propriétaire n'en a pas fixé, ce champ est vide et toute demande est refusée (condition 3).

**Fenêtre de validité (proposition).** L'instant d'autorisation (`authorized_at`) est l'instant où le service vérifie l'assertion WebAuthn, et non la création de la demande. L'autorisation expire à `authorized_at` + `validity_seconds`, soit 300 s au plus, conformément à la condition 2 et au contrôle existant de la Gate (`MAX_AUTHORIZATION_AGE_SECONDS = 300.0`, `_authorization_freshness_reasons()` dans `agents/generation_approval_gate.py`). Le délai d'attente de l'humain s'ajoute **avant** cet instant, sans jamais prolonger la fenêtre de 300 s.

**Relation avec la limite A2-b.** Le manifeste contient les paramètres vidéo, mais cela ne couvre A2-b qu'au niveau du service. A2-b porte sur `RealGenerationAuthorization` et sur le Provider, qui ne reçoit pas l'autorisation. Elle ne serait couverte dans le Director que si la Gate et le Provider vérifiaient l'empreinte de l'énoncé (exigences L2 et L7 de la Phase C). Ce point est à concevoir (section 4.11).

L'énoncé affiché à l'humain doit être exactement celui dont l'empreinte entre dans le défi.

### 4.6 Nonce, usage unique, clé d'idempotence et réapprobation

- Nonce de 256 bits tiré par le service (`secrets`), unique en base.
- La consommation est **une seule transaction** : transition `APPROVED` → `CONSUMED` conditionnelle, enregistrement du couple (`run_id`, `run_attempt`), entrée de journal, lecture de l'interrupteur global. Zéro ligne modifiée signifie un refus.
- Une demande consommée, expirée, refusée ou révoquée n'est jamais rétablie.
- La clé d'idempotence de la Phase F (`derive_idempotency_key(manifest_sha256, approval_id)`, `integrations/higgsfield/manifest.py`) recevrait l'`approval_id` choisi par le service, et non plus `gh-<run_id>`.
- **Réapprobation d'un même manifeste.** La Phase F §5 constate qu'un nouveau `workflow_dispatch` avec la même empreinte obtient un nouveau run, donc une nouvelle approbation et une nouvelle clé d'idempotence. Rien ne l'empêcherait. Décision ouverte D-17 :
  - un manifeste peut-il être approuvé plusieurs fois, et à quelles conditions ;
  - une seule demande active à la fois est-elle imposée, tous manifestes confondus ?

### 4.7 États

| État | Signification | Transitions permises |
|---|---|---|
| `PENDING` | Demande reçue d'un run vérifié | `APPROVED`, `DENIED`, `EXPIRED`, `REVOKED` |
| `APPROVED` | Assertion WebAuthn valide sur l'énoncé | `CONSUMED`, `EXPIRED`, `REVOKED` |
| `DENIED` | Refus explicite de l'humain | Terminal |
| `EXPIRED` | Échéance dépassée (`approval_deadline` ou fenêtre de validité) | Terminal |
| `REVOKED` | Révocation humaine authentifiée | Terminal |
| `CONSUMED` | Délivrée une fois au run | **Terminal tant que Provider = CLOSED.** `IN_FLIGHT` ne deviendrait possible qu'après une décision distincte de réouverture |
| `IN_FLIGHT` | Envoi au fournisseur commencé (inatteignable aujourd'hui) | `ACCEPTED`, `REFUSED`, `NOT_SENT`, `AMBIGUOUS` |
| `ACCEPTED` | Classification `ACCEPTED` de la Phase F §4 (identifiant de requête reçu) | Terminal pour l'approbation ; le suivi du job relève d'une conception ultérieure |
| `REFUSED` | Classifications `REJECTED`, `AUTH_FAILED` ou `INSUFFICIENT_CREDITS` de la Phase F §4 | Terminal ; toute nouvelle tentative exige une nouvelle approbation |
| `NOT_SENT` | Classification `NOT_SENT` de la Phase F §4 (connexion jamais établie) | À trancher avec D-17 : reprise avec la même approbation pendant sa fenêtre de validité, ou nouvelle approbation |
| `AMBIGUOUS` | Issue inconnue (classification `AMBIGUOUS` ou `UNKNOWN` de la Phase F) | Uniquement par rapprochement humain consigné. **Bloque toute nouvelle demande** tant qu'il n'est pas résolu, comme `EXECUTION_STATE_UNKNOWN` |

Le traitement de `NOT_SENT` (reprise possible selon la Phase F, ou nouvelle approbation) est à trancher avec D-17.

### 4.8 Révocation et interrupteur global

Proposition, sous réserve de D-9.

- **Révocation** : par demande, par identifiant WebAuthn ou par commit autorisé ; persistante et journalisée. Elle correspond à l'option R-a de la Phase E, dans la base plutôt que dans un fichier. Le mode d'authentification de la révocation (WebAuthn, SSH, les deux) relève de D-9.
- **Interrupteur global** (options S-b et R-d de la Phase E) : **fermé par défaut**. Interrupteur absent, illisible ou corrompu signifie fermé. Il est lu dans la transaction de consommation.
  - **Fermeture** : elle doit rester possible sans dépendre de l'interface web ni de WebAuthn, par une session SSH d'administration ou par la console de l'hébergeur (à vérifier, section 6).
  - **Réouverture** : ses modalités relèvent de D-9.
- **Portée de l'arrêt.** En E-1, une autorisation déjà délivrée au run reste utilisable jusqu'à son expiration, au plus 300 s, sauf si le Director revérifie auprès du service juste avant l'envoi (à concevoir, section 4.11). En E-2, la fermeture s'applique à toute soumission non encore commencée.
- L'interrupteur ne remplace aucun verrou : les quatre verrous de la Phase A et F-1 à F-4 restent fermés dans le code.

### 4.9 Journal

- Table chaînée par empreinte (option J-b), écrite **dans la même transaction** que chaque changement d'état. Un échec d'écriture du journal annule la transition.
- **L'ajout seul est une convention**, renforcée si possible par des déclencheurs qui refusent `UPDATE` et `DELETE`. Elle n'est pas inviolable pour qui peut écrire le fichier ou administrer la base.
- Un refus portant sur une demande authentifiée est journalisé au même titre qu'une approbation. Les requêtes **non authentifiées** (jeton invalide, assertion invalide) sont comptées ou agrégées de façon bornée, sans une entrée par requête, pour ne pas permettre de saturer le disque ou le journal.
- Aucun secret, jeton OIDC, assertion brute, clé ni URL de résultat : seulement des identifiants, des empreintes, des décisions et des dates (exigence L6).
- Ancre externe de la tête (J-c) : option ouverte (D-7). C'est la seule capable de détecter une réécriture complète ou une restauration non signalée (section 3.4).
- Le journal trace ; il ne vaut jamais autorisation.

### 4.10 Point d'application : qui détient l'identifiant du fournisseur

C'est la décision D-1, prise le 2026-10-07 : **E-2 est retenue pour la conception**. Ce choix n'implémente pas le courtier et ne constitue pas une décision d'ouverture du Provider.

| Option | Description | Ce que l'approbation garantit réellement | Compromis |
|---|---|---|---|
| **E-1. Le run détient l'identifiant** (secret d'environnement GitHub) | Le service délivre l'autorisation ; le run la vérifie (section 4.11) puis appelle le fournisseur | Le code du commit autorisé refuse d'agir sans approbation. Un code modifié qui détient le secret peut s'en passer, comme toute étape du job qui y a accès | Le service n'a aucun secret fournisseur. La garantie repose sur la protection de `main`, de l'environnement et des actions épinglées |
| **E-2. RETENUE : le service est le seul détenteur de cet identifiant** (courtier) | Le run ne reçoit jamais l'identifiant ; seul le service soumet, après consommation | Aucune soumission **par ce chemin** sans approbation consommée, même avec un run compromis, **sous l'hypothèse d'un serveur intègre** | Secret fournisseur sur un serveur exposé à Internet ; surface plus grande ; le service doit implémenter les verrous et la classification de la Phase F |

**Accès fournisseur indépendants, hors de portée des deux options :** l'interface web du compte Higgsfield, le CLI Higgsfield authentifié sur un poste (Phase A, verrous 3 et 4), toute autre clé d'API, et tout connecteur ou intégration tierce autorisé sur ce compte. Ni E-1 ni E-2 ne les contrôle. Leur inventaire, leur protection et leur révocation relèvent de D-15.

L'option E-2 est un choix d'architecture seulement : elle n'est pas mise en œuvre et aucun identifiant fournisseur n'a été créé ou placé sur le serveur. L'ouverture effective du Provider exige toujours une nouvelle décision écrite distincte de la Phase A. Les accès fournisseur indépendants listés ci-dessus restent hors de portée.

### 4.11 Réponse du service et vérification par le Director

Le schéma de la section 4.1 ne fixe pas ce que le run reçoit lors de la consommation, ni comment le Director vérifie que cette réponse vient bien du service. Options, sans choix (D-18) :

| Option | Description | Compromis |
|---|---|---|
| **R-1. Attestation signée par le service** (signature asymétrique) | Le service signe l'énoncé et l'état `CONSUMED` ; le Director vérifie avec une clé publique épinglée | Exige une clé privée sur le serveur, sa rotation et une dépendance (D-13). La clé publique n'est pas un secret. Aucune clé n'est créée par cette phase |
| **R-2. TLS seul** | Le Director fait confiance à la réponse reçue sur `https://zephyr-approval.fr` | Repose sur le DNS, l'autorité de certification et l'intégrité du runner ; aucune preuve conservable |
| **R-3. Secret partagé (HMAC)** | Le service et le runner partagent une clé | Écartée par la limite 1 de la Phase C §3 : qui vérifie peut aussi signer |

**Couverture des exigences L1 à L8 de la Phase C par cette conception**

| Exigence | Couverture par G1 | Reste à faire |
|---|---|---|
| L1 — énoncé canonique | Section 4.5 | Validation du format en G2 |
| L2 — vérification à la Gate | **Non couverte** | Dépend de D-18 ; la Gate devrait vérifier l'attestation contre la requête évaluée |
| L3 — contrats P2.21 et P2.26 | **Non couverte** | Les contrats devraient porter l'empreinte de l'énoncé |
| L4 — paramètres vidéo et coût | Partielle : paramètres dans le manifeste ; plafond vide, donc refus | Coût `UNKNOWN` toujours bloquant côté Gate (condition 4) ; plafond à décider (D-14) |
| L5 — usage unique, identifiant choisi par l'émetteur | Côté service (section 4.6) | Le registre local du Director reste limité à une machine (A2-d) |
| L6 — aucun secret persisté | Section 4.9 | En E-2 ou R-1, des secrets vivraient sur le serveur : hors du dépôt, de `state/` et des journaux, mais à protéger |
| L7 — frontière Provider | **Non couverte** | Le Provider devrait recevoir l'empreinte de l'énoncé |
| L8 — testabilité mock-only | Section 11, étape 4 | — |

## 5. Ce que prouvent OIDC et WebAuthn

| | **OIDC GitHub** | **WebAuthn** |
|---|---|---|
| **Prouve** | GitHub a émis ce jeton, pendant sa courte validité, pour un job d'un dépôt, d'un workflow, d'une référence, d'un commit et d'un run donnés | Le détenteur d'un identifiant enregistré a signé ce défi précis, pour cette origine, avec présence et, si UV est exigé, vérification locale de l'utilisateur (biométrie ou code de l'appareil) |
| **Ne prouve pas** | Qu'un humain a consenti à l'énoncé. Le compte GitHub qui a lancé le run (claim `actor`, à confirmer) n'est pas une preuve de consentement. Que les étapes du job n'ont pas été modifiées au-delà de ce que contient le commit. Que le manifeste transmis a été calculé honnêtement | L'identité civile de la personne. Qu'elle a lu ou compris l'énoncé : le serveur choisit ce qu'il affiche, et l'authentificateur signe le défi, pas le texte affiché. Avec l'option (a) de D-11, qu'elle a vu le contenu : elle consent à des empreintes |
| **Hypothèses de confiance** | GitHub (émetteur, publication des clés, TLS) ; protection de la branche `main` et du compte GitHub du propriétaire ; épinglage des actions (toute étape du job peut demander un jeton si la permission est accordée) ; intégrité de l'image du runner et des binaires téléchargés ; runner hébergé par GitHub ; aucun accès aux jetons depuis des forks | Intégrité du serveur et du code qui affiche l'énoncé ; intégrité du poste et du navigateur de l'approbateur ; contrôle exclusif de l'authentificateur ; pour une passkey synchronisée, sécurité du compte du fournisseur de synchronisation ; intégrité de l'inscription (section 4.4) |
| **Limites** | Le jeton est porteur : quiconque le détient pendant sa validité peut le présenter (section 4.2). Le service doit atteindre les clés publiques de GitHub ; s'il ne le peut pas, il refuse | Un serveur compromis, ou un script injecté dans la page, peut afficher un énoncé et en faire signer un autre. Une passkey synchronisée se copie sur tous les appareils du compte. Le compteur de signatures ne détecte pas toujours un clonage |

**Rattachement aux conditions de la Phase A.**

- **OIDC lie la demande à un run.** Il fournit les champs de dépôt, de commit et de run de l'énoncé L1, mais **ne relève pas de la condition 1**. L'option D de la Phase C §5 vise l'identité de l'autorisateur humain, alors que le jeton OIDC du run identifie un job, pas une personne.
- **WebAuthn est le mécanisme qui se rapproche de la condition 1**, au plus près de l'option B de la Phase C (confirmation hors bande d'un énoncé précis). Le vérificateur est sur le serveur, hors du processus Director. Cela répond à la limite 1 de la Phase C §3, sous l'hypothèse d'un serveur intègre.
- **La condition 1 reste ouverte** : D-2 fixe le protocole WebAuthn mais ne prouve pas l'identité civile ; D-3 fixe la récupération, D-4 les types d'identifiants et D-5 la séparation des rôles, sans établir l'identité civile. La liaison entre comptes et personnes reste à définir sous D-15, et les preuves de validation des sections 9 et 11 restent nécessaires.
- Les conditions 2, 3, 5 et 7 restent dans leur état décrit par la Phase A.

**Racines de confiance hors du modèle :**

- le compte Scaleway. Sa console donne probablement un accès au serveur sans SSH (console série, mode secours, instantanés), **fonctions à vérifier sur l'offre Scaleway** ;
- le compte GitHub du propriétaire ;
- la ou les clés SSH d'administration, racine de confiance de l'inscription et de la récupération (D-2, D-3) ;
- le registrar et la zone DNS de `zephyr-approval.fr` ;
- l'autorité qui délivrerait le certificat TLS ;
- le compte Higgsfield lui-même (section 4.10).

La compromission de l'une d'elles contourne le service.

## 6. Configuration du serveur déjà effectuée

**Déclarée par le propriétaire, non vérifiée par cette phase.** Aucune adresse IP, aucun identifiant d'instance, aucune empreinte de clé ni aucune donnée de connexion n'est consignée ici, volontairement.

| Élément | État déclaré |
|---|---|
| Hébergement | Scaleway, région Paris (décision du propriétaire) |
| Système | Ubuntu 26.04.1 |
| Ressources | 2 vCPU, 4 Go de RAM |
| Stockage | Volume de données ext4 monté durablement sous `/srv/ai-director-data` |
| Pare-feu | UFW actif ; seul SSH (port 22) autorisé ; ports 80 et 443 fermés |
| SSH | Authentification par mot de passe désactivée ; connexion directe de `root` interdite ; authentification par clé |
| Administration | Compte `directoradmin` opérationnel |
| Compte de service | Compte système `aidirector`, sans connexion interactive ; propriétaire de `/srv/ai-director-data/app` |
| DNS | `zephyr-approval.fr` résout vers le serveur |
| Services web | Aucune application web déployée |
| Base de données et anti-rejeu | Aucun moteur ni mécanisme **choisi** (déclaré). La présence de paquets de base de données sur le système n'est pas vérifiée |

Non connu à ce jour, à constater plus tard :
- version de Python disponible ;
- synchronisation horaire (NTP) ;
- mises à jour de sécurité automatiques ;
- options de montage du volume ;
- politique de sauvegarde ou d'instantanés de l'hébergeur ;
- fonctions d'accès console et de mode secours de l'offre Scaleway.

## 7. Exposition web (non effectuée)

WebAuthn impose HTTPS, et le run GitHub doit pouvoir joindre le service depuis Internet. Les adresses des runners hébergés couvrent de larges plages : un filtrage par adresse n'est pas une protection réaliste pour l'interface OIDC. Décisions ouvertes (D-12) :

- ouverture du port 443. Le port 80 n'est nécessaire que pour un défi ACME HTTP-01 ; les défis DNS-01 et TLS-ALPN-01 n'en ont pas besoin ;
- terminaison TLS : reverse proxy (dépendance système) ou serveur Python ;
- limitation de débit, taille maximale des requêtes, interface d'administration non exposée (SSH seulement) ;
- séparation éventuelle de l'interface humaine et de l'interface OIDC.

**Sécurité de la page d'approbation**, exigences à valider. Un script injecté dans l'origine `https://zephyr-approval.fr` pourrait mener une cérémonie WebAuthn devant un affichage falsifié. D'où :
- une politique de sécurité du contenu (CSP) stricte ;
- aucun script ni ressource tierce ;
- HSTS ;
- une protection contre la falsification de requêtes (CSRF) ;
- des sessions courtes, liées à la demande, invalidées après usage ;
- aucune donnée de l'énoncé injectée sans échappement.

Rien n'est ouvert par cette phase.

## 8. Budget

**Objectif budgétaire maximal fixé par le propriétaire : 50 € par mois, taxes comprises, pour l'ensemble des coûts récurrents.** Le coût total réel TTC **n'est pas constaté**, et ce document ne garantit pas qu'il respecte cet objectif.

**Taxes.** Les tarifs publiés par les fournisseurs peuvent être exprimés hors taxes. Le montant TTC dépend du statut de facturation du compte. Il doit être constaté sur devis ou facture Scaleway, **sans être déduit d'une facture antérieure**, notamment celle du domaine.

**Coûts récurrents à additionner sur les tarifs en vigueur :**

- instance ;
- volume de données ;
- adresse IP publique, si facturée séparément ;
- instantanés et sauvegardes (et stockage objet, si utilisé) ;
- trafic sortant, si facturé ;
- domaine (renouvellement annuel, ramené au mois) et DNS ;
- base managée (S-3), le cas échéant ;
- plan GitHub, si les protections d'environnement requises (relecteurs obligatoires) ne sont pas disponibles pour la visibilité du dépôt et le plan actuels : à vérifier ;
- minutes GitHub Actions consommées par un job qui attend l'approbation, selon le plan et la visibilité du dépôt.

**Coûts ponctuels, hors de l'objectif mensuel :** authentificateurs matériels, le cas échéant.

Le certificat TLS peut être gratuit (autorité ACME), selon l'option retenue. Une alerte de facturation chez l'hébergeur est recommandée ; sa mise en place est une décision du propriétaire (D-15).

## 9. Constats Linux et exigences de validation

Les éléments ci-dessous sont des **exigences de validation futures**. **Aucun de ces essais n'a été exécuté.**

Règles communes :
- chaque exigence devient un test automatisé ou un procès-verbal consigné ;
- l'issue attendue en cas de refus est toujours la même : **refus, aucune transition d'état, entrée de journal** (ou compteur borné pour les requêtes non authentifiées, section 4.9) ;
- tous les essais se font **sans réseau vers le fournisseur, sans secret réel, Provider = CLOSED**, dans un dossier d'état temporaire ou dédié ;
- les clés OIDC et WebAuthn sont générées par les tests eux-mêmes.

**Portabilité et fichiers existants**

- **V-1. Version.** Exécuter la suite complète sous Ubuntu avec la version de Python retenue. Mettre à jour la déclaration de `.python-version` et du README seulement si cette version est validée (P3.106).
- **V-2. Verrous.** Démontrer sous Linux le comportement des verrous existants (`O_CREAT | O_EXCL`) et l'équivalent des tests de verrou réservés à Windows (P3.97, P3.98, P3.102). Sous POSIX, supprimer un fichier ouvert est permis : leurs hypothèses ne s'y transposent pas telles quelles.
- **V-3. Durabilité des fichiers.** Prouver ou corriger l'absence de synchronisation du répertoire parent après `os.replace`, pour tout fichier d'état qui serait encore utilisé sur le serveur.

**Exigences X1 à X8**

- **X1. OIDC.** Refus pour chacun des cas suivants :
  - signature invalide ; `alg=none` ; confusion d'algorithme (algorithme symétrique utilisant la clé publique) ; `kid` inconnu ;
  - clés publiques de GitHub injoignables ; rotation des clés (nouvelle clé acceptée, clé retirée refusée) ;
  - `iss`, `aud` (dont l'audience de l'autre interface), `ref`, `repository_id`, `repository_owner_id`, `workflow_ref`, `job_workflow_ref`, `event_name` ou `runner_environment` erronés ;
  - `sha` non autorisé ; `exp` dépassé ; `nbf` futur ; valeurs juste à l'intérieur et juste à l'extérieur de la tolérance d'horloge ;
  - `run_attempt` égal à 2 ; même jeton présenté deux fois ; jeton du job `request` présenté au job `execute`.
- **X2. WebAuthn.** Refus pour chacun des cas suivants :
  - origine ou `rpIdHash` erronés ; `type` différent de `webauthn.get` ; `crossOrigin` vrai ;
  - UP ou UV à 0 ; identifiant révoqué ; régression du compteur, selon la politique retenue ;
  - assertion rejouée ; assertion de la demande A présentée pour la demande B ; défi expiré ;
  - drapeaux BE/BS non conformes à D-4.
- **X3. Concurrence.** N processus **et** N threads, démarrés ensemble par une barrière, répétés au moins 1 000 fois. N et le nombre de répétitions sont fixés et consignés avant l'essai. Résultats attendus :
  - exactement une consommation ;
  - courses consommation/révocation, consommation/expiration et consommation/fermeture de l'interrupteur : aucune consommation après une révocation ou une fermeture confirmée ;
  - journal cohérent.
- **X4. Coupure.**
  - un observateur **externe au serveur** enregistre chaque identifiant dont la transaction a été confirmée ;
  - arrêt brutal du processus (`SIGKILL`), puis réinitialisation brutale de la machine ;
  - comparaison : aucun identifiant confirmé ne manque, aucune transaction partielle n'est visible, `integrity_check` est sain.
  - Limite : la durabilité du stockage hébergé côté hôte reste une hypothèse (section 3.3).
- **X5. Restauration.**
  - **annoncée** : sauvegarde, consommation, restauration ; l'approbation consommée n'est pas réutilisable, l'interrupteur est fermé, la divergence avec le témoin est signalée ;
  - **non annoncée**, y compris par restauration du volume entier : résultat attendu selon l'option D-7 retenue. Sans ancre externe, la limite est consignée comme **non détectée** (section 3.4) ;
  - traitement des fichiers `-wal` et `-shm` vérifié.
- **X6. Refus fermé.** Refus pour chacun des cas suivants : interrupteur absent ou corrompu ; version de schéma inattendue ; chaîne de journal rompue ; échec d'écriture du journal (aucune transition, la transaction étant atomique) ; `synchronous` relu différent de `FULL` ; base absente, corrompue ou en lecture seule ; disque plein ; verrou tenu au-delà du délai.
- **X7. Horloge.** Le dernier instant observé est conservé. Tout recul de l'horloge est refusé, sans prolongation de fenêtre (A2-g). Si l'option est retenue, refus quand la synchronisation NTP n'est pas établie.
- **X8. Secrets et droits.**
  - des valeurs sentinelles (jeton, assertion, secret) sont injectées puis recherchées dans tous les journaux du service et du système : aucune occurrence ;
  - base, témoin et journal ne sont lisibles que par `aidirector`.

## 10. Décisions qui restent au propriétaire

| # | Décision | Options principales |
|---|---|---|
| D-1 | **Décidée le 2026-10-07 — courtier E-2** | Toute clé API dédiée à ce chemin serait détenue uniquement par le service ; état anti-rejeu durable sur le serveur. Autres accès au compte hors périmètre. Choix de conception seulement, sans implémentation ni ouverture du Provider |
| D-2 | **Décidée par délégation le 2026-10-07 — WebAuthn avec vérification locale obligatoire** | WebAuthn est le seul facteur normal pour approuver une demande. L'option `userVerification=required` est demandée et le drapeau UV doit être vérifié pour chaque approbation ; aucun repli d'approbation par mot de passe de compte, courriel ou SMS. L'inscription reste fermée par défaut et requiert une invitation à usage unique créée depuis une session SSH d'administration. Le premier drapeau UV d'un nouvel identifiant n'autorise pas sa propre inscription. Choix de conception seulement ; la politique des types et des passkeys synchronisées est précisée par D-4 |
| D-3 | **Décidée par délégation le 2026-10-07 — deux identifiants séparés, récupération SSH** | Deux identifiants WebAuthn distincts liés à deux authentificateurs séparés sont requis avant toute activation ; l'un est conservé comme secours. Une perte entraîne fermeture immédiate, révocation et journalisation. Le remplacement exige une invitation à usage unique créée depuis SSH ; si tous les identifiants sont perdus, les anciens sont tous révoqués et l'interrupteur reste fermé jusqu'à une réouverture conforme à D-9. Aucun repli par courriel, SMS, code de récupération ou support tiers. La racine SSH et la confiance dans le serveur restent des hypothèses de D-15. Les types acceptés sont fixés en D-4 |
| D-4 | **Décidée par délégation le 2026-10-07 — plateforme et clé de sécurité, secours non synchronisable** | Passkeys de plateforme et clés de sécurité acceptées avec UV. Une passkey synchronisable (`BE=1`) peut être l'identifiant courant, pas l'identifiant de secours. Le secours doit être un identifiant distinct sur un authentificateur séparé avec `BE=0`, `BS=0`. `BE` est fixé à l'inscription et ne peut changer ; `BS=1` est refusé si `BE=0`, mais peut évoluer si `BE=1`. Aucune attestation AAGUID exigée ; le service fait confiance aux drapeaux signés et déclarés par l'authentificateur. Décision de conception seulement, sans inscription ni matériel acheté |
| D-5 | **Décidée par délégation le 2026-10-07 — un approbateur, séparation obligatoire** | Une seule approbation WebAuthn suffit, sans quorum supplémentaire. L'approbateur autorisé doit être distinct de l'acteur GitHub qui lance le run ; auto-approbation refusée. Si cette séparation ne peut pas être vérifiée, refus fermé. L'identification des comptes et la protection des comptes relèvent aussi de D-15. Choix de conception seulement, sans implémentation |
| D-6 | Base de données | S-1, S-2 ou S-3 (section 3), après les preuves de la section 3.3 |
| D-7 | Sauvegardes, rétention, témoin et ancre externe | Fréquence, emplacement hors du serveur, durée de conservation, chiffrement, exercice de restauration, emplacement du témoin de restauration, ancre J-c |
| D-8 | Délais | Délai d'attente de l'humain (`approval_deadline`), fenêtre de validité (au plus 300 s), durée maximale du job en attente |
| D-9 | Interrupteur et révocation | Qui ferme, qui rouvre, par quel geste et quel acte écrit ; authentification de la révocation ; révocation annulable ou non |
| D-10 | Commits autorisés | Options (i), (ii) ou (iii) de la section 4.3 |
| D-11 | Manifeste et contenu montré | Option (a) ou (b) de la section 4.3 |
| D-12 | Exposition web | Ports, TLS, reverse proxy, limitation de débit, sécurité de la page (section 7) |
| D-13 | Dépendances | Abandon de la règle « bibliothèque standard uniquement » pour la vérification OIDC et WebAuthn (et R-1 ou (iii) le cas échéant) ; bibliothèques choisies, épinglage, mise à jour |
| D-14 | Plafonds de dépense | Montant par requête et existence d'un plafond par période (condition 3). **Aucun montant n'est fixé par ce document** |
| D-15 | Protection des comptes Scaleway, GitHub, DNS et Higgsfield | Authentification forte, accès console, clés d'API, alertes de facturation, verrou du domaine chez le registrar, règles de protection de `main` et de l'environnement, inventaire et révocation des accès fournisseur indépendants (section 4.10) |
| D-16 | Plateforme Python | Version retenue sur le serveur et maintien ou non de la validation Windows |
| D-17 | Réapprobation et demandes simultanées | Un même manifeste peut-il être approuvé plusieurs fois, et à quelles conditions ; une seule demande active à la fois ou non ; traitement de `NOT_SENT` |
| D-18 | Réponse du service et vérification par le Director | R-1, R-2 (R-3 écartée), section 4.11 ; couverture de L2, L3 et L7 |

## 11. Séquence de preuves et de revues avant tout déploiement

Chaque étape est une condition de la suivante. Aucune n'ouvre le Provider.

1. **Revue de ce document G1** par le propriétaire, puis fusion éventuelle par PR.
2. **Décisions écrites** D-6 à D-18, ou décision explicite de reporter celles qui ne bloquent pas la suite. D-1 à D-5 sont décidées pour la conception ; elles ne constituent pas une autorisation d'implémenter ou d'ouvrir le Provider.
3. **Vérifications documentaires** : offres, tarifs TTC et fonctions de console de Scaleway ; plan GitHub ; versions des paquets Ubuntu.
   - L'essai avec un **jeton OIDC réel** exige une **autorisation explicite et distincte du propriétaire**.
   - Il passerait par un workflow dédié qui n'affiche jamais le jeton brut, seulement des claims décodés non sensibles, et n'appelle aucun service.
4. **Phase G2, implémentation mock-only** sur le poste de développement :
   - contenu : énoncé canonique, vérificateurs OIDC et WebAuthn testés avec des clés générées par les tests, machine à états, stockage, témoin, journal, interrupteur, réponse du service selon D-18 ;
   - aucun réseau, aucun secret réel ;
   - des **gardes documentaires**, sur le modèle de `tests/test_phase_e1_documentary_invariants.py`, protègent G1 : NO-GO, Provider = CLOSED, absence de montant, liens valides ;
   - les quatre verrous, F-1 à F-4, les cardinalités et `NO_DRIFT` restent verts.
5. **Campagne Linux** de la section 9 (V-1 à V-3, X1 à X8), avec procès-verbal consigné. Déployer du code, même de test, sur le serveur exige une **autorisation explicite et distincte du propriétaire**, sans ouverture de port.
6. **Revue de sécurité** du code (`/security-review` et relecture humaine) et **revue du modèle de menace** serveur : comptes, droits, journaux système, mises à jour, racines de confiance de la section 5.
7. **Exercice de sauvegarde et de restauration** de bout en bout, consigné, y compris les scénarios de la section 3.4.
8. **Décision d'exposition web** (D-12), puis ouverture des seuls ports retenus, et contrôle externe de la configuration TLS et de la sécurité de la page.
9. **Essai de bout en bout, Provider = CLOSED**, sur autorisation explicite du propriétaire :
   - run réel sur `main`, demande, approbation WebAuthn, consommation unique, puis arrêt attendu sur le code 4 ;
   - rejeu, relance, expiration, révocation et réapprobation (selon D-17) testés et refusés ;
   - aucun crédit consommé.
10. **Procédure d'arrêt et de refermeture** (condition 7) déroulée et consignée.
11. Seule une **nouvelle décision écrite**, distincte de celle de la Phase A, pourrait ensuite constater que les sept conditions sont remplies. Ce document ne la prépare pas et ne la promet pas.

## 12. Ce que cette phase ne fait pas

- Aucune modification de code, de workflow, de test, de verrou, de configuration serveur, de réglage GitHub ou de DNS.
- Aucun secret ni aucune clé créé ou lu ; aucun logiciel installé ; aucun port ouvert ; aucun déploiement.
- Aucun appel à Higgsfield ; aucun workflow lancé ; aucun appel à `create_job()`.
- Aucune option choisie à la place du propriétaire ; aucun montant de plafond fixé ; aucun essai de la section 9 exécuté.
- Les conditions 1, 3, 5 et 7 de la Phase A restent **ouvertes**, la condition 2 reste **partiellement traitée**, et le **NO-GO** reste en vigueur.

**Provider = CLOSED · Real generation = 0 · Credits = 0**
