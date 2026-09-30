# Phase E — Conception : limites de l'autorisation, plafond, révocation et arrêt

- **Date :** 2026-09-30
- **Référence :** `main` à `2b10c40bc28b318d3be75f66a029bc2e914f05cc` (fusion de la PR #3, Phase D)
- **Statut :** document de conception (Phase E1). Il n'implémente rien, n'autorise rien et ne choisit aucune option.
- **Mise à jour après la Phase E2 :** 2026-09-30, à `main` `8ad12f60465eb16edd36c7216ba04caa9c59ec8b`. La Phase E2 est une phase d'implémentation distincte de cette conception : sur instruction du propriétaire, elle a mis en œuvre l'option (i) de la limite A2-c. Seules la ligne A2-c de la section 3 et la preuve A2-c correspondante ont été mises à jour pour le décrire. Tout le reste du document est la conception initiale de la Phase E1, constatée à la référence ci-dessus : aucune autre option n'est mise en œuvre, aucune condition n'est résolue et aucun statut ne change.

Ce document traite les conditions 1, 2, 3, 5 et 7 de [`phase_a_real_generation_decision.md`](phase_a_real_generation_decision.md). Il décrit les limites restantes, des options, leurs compromis, les décisions qui appartiennent au propriétaire du projet et les preuves à produire. Il ne résout aucune de ces conditions. Rien ici ne rend la génération réelle possible : le **NO-GO** reste en vigueur, **Provider = CLOSED**, et les quatre verrous d'exécution décrits dans la décision de Phase A sont inchangés.

## État des conditions traitées ici

| Condition | Statut | Où elle est traitée |
|---|---|---|
| 1. Identité authentifiée | **Ouverte** | [`phase_c_authorizer_identity_design.md`](phase_c_authorizer_identity_design.md) ; section 2 ci-dessous |
| 2. Autorisation explicite, liée, courte et à usage unique | **Partiellement traitée** | Expiration, usage unique et liaison au contenu sont présentes ; les limites restantes sont en section 3 |
| 3. Plafond de crédits | **Ouverte** | Section 4 |
| 5. Révocation et audit | **Ouverte** | Section 5 |
| 7. Arrêt et refermeture | **Ouverte** | Section 6 |

Les conditions 4 (`UNKNOWN` toujours bloquant) et 6 (périmètre Video 005) ne sont pas l'objet de ce document : leur état est décrit dans la décision de Phase A.

## 1. État actuel vérifié

Constaté dans le code à la référence ci-dessus :

- **Autorisation.** `RealGenerationAuthorization` (`agents/generation_approval_gate.py`) est liée au `request_id` et aux empreintes du prompt, de l'avatar et de la référence visage. Elle expire après 300 s (`_authorization_freshness_reasons()`) et n'est utilisable qu'une fois, via `FileAuthorizationConsumptionRegistry` (`agents/executed_request_store.py`), dans un seul dossier d'état.
- **Plafond.** `GenerationApprovalGate` accepte un plafond par requête facultatif (`max_cost_credits_per_request`). Pour tout Provider qui n'est pas un mock de test reconnu, son absence donne `BLOCKED` (`_real_provider_configuration_reasons()`). Aucun code de production ne le configure, et `director.py` ne le mentionne pas. Aucun plafond par période n'existe.
- **Révocation.** `ControlledRealProviderActivationService.revoke()` ajoute l'identifiant du contrat P2.26 à un ensemble en mémoire. Rien n'est persisté. Il n'existe pas de révocation d'une autorisation ni du contrat de requête P2.21.
- **Journal.** Les registres persistants (`executed_requests.json`, `consumed_authorizations.json`) enregistrent les exécutions et les consommations. Aucun journal durable et append-only ne trace les autorisations, préparations, refus et tentatives.
- **Arrêt.** Les quatre verrous sont fermés dans le code : il n'y a donc rien à refermer aujourd'hui. Aucune procédure de refermeture n'est documentée ni testée. Le client n'autorise aucun verbe d'annulation (`_READ_ONLY_CLI_VERBS`, `integrations/higgsfield/client.py`).
- **Frontière d'exécution (Phase D).** Dans `GenerationJobService.execute()`, la garde `may_reach_create_job()` lève `GenerationJobProviderNotAllowedError` pour tout Provider autre que le Mock reconnu ou le vrai `HiggsfieldProvider` exact (dont `create_job()` lève toujours). `GenerationJobService.execute()` est le seul site d'appel de `create_job()` en production, ce que vérifient les cardinalités. La garde ne couvre que ce chemin : un appel direct à `provider.create_job()` ne passe pas par elle. Un tel appel n'existe pas en production tant que les cardinalités tiennent, et le vrai Provider refuse de toute façon par ses propres verrous. Limite : une modification de la classe elle-même à l'exécution (monkeypatch dans le processus) reste hors du modèle de menace. Rien de cela n'ouvre quoi que ce soit : le NO-GO et les quatre verrous sont inchangés. Voir « Contrôles déjà présents » dans la décision de Phase A.
- **Dossier d'état.** `state/` est ignoré par Git : son contenu n'est ni versionné ni sauvegardé par le dépôt.

## 2. Condition 1 — identité authentifiée (renvoi)

La condition 1 est traitée par [`phase_c_authorizer_identity_design.md`](phase_c_authorizer_identity_design.md). Elle reste **ouverte** : aucune option d'identité n'y est choisie, et rien n'est implémenté.

Plusieurs limites ci-dessous dépendent d'elle. Tant qu'un code du même processus peut construire une autorisation valide, l'usage unique, la fraîcheur, le plafond attesté et la révocation par l'émetteur ne protègent que contre l'erreur et la réutilisation, pas contre une autorisation fabriquée. Les sections suivantes signalent chaque dépendance par « dépend de la condition 1 ».

## 3. Condition 2 — limites restantes de l'autorisation

Ce qui est présent : expiration, usage unique local et liaison au contenu. Les limites ci-dessous restent ouvertes. Elles reprennent celles de la décision de Phase A (« Lacunes à combler », condition 2).

| Limite | Options | Compromis |
|---|---|---|
| **A2-a. Cohérence, pas consentement.** Les empreintes prouvent que l'autorisation correspond au contenu, pas qu'une personne a consenti | Aucune option propre à cette phase : dépend de la condition 1 (Phase C, exigences L1 et L2) | Sans identité, toute amélioration de la liaison reste contournable par du code du même processus |
| **A2-b. Paramètres hors empreintes.** Durée, résolution, format et modèle ne font pas partie des empreintes de l'autorisation, et le Provider ne reçoit pas l'autorisation | (i) Étendre les empreintes de l'autorisation aux paramètres vidéo. (ii) Transmettre au Provider l'empreinte d'un énoncé complet (Phase C, L7). (iii) Conserver l'état actuel : ces paramètres restent vérifiés par l'Identity Lock et les contrats | (i) change le format de l'autorisation et tous ses constructeurs. (ii) dépend de la condition 1. (iii) ne coûte rien, mais laisse l'autorisation muette sur ces paramètres |
| **A2-c. Fenêtre entre vérification et transmission.** Avant la Phase E2, un fichier avatar ou référence visage remplacé entre la vérification de la Gate et le recalcul par `GenerationJobService` créait un décalage. La Phase E2 a mis en œuvre (i), sur instruction du propriétaire : dernier contrôle après la Gate et l'inspection du contrat P2.21, avant toute consommation, puis transmission de ces valeurs exactes à `create_job()`, sans relecture. Avec un contrat P2.26, sa validation suit ce contrôle (elle consomme ce contrat dans le même appel), relit les fichiers et ne peut que refuser. **Reste ouvert :** un remplacement après ce dernier contrôle (ou après la validation P2.26) n'est pas détecté, et `create_job()` reçoit des empreintes, jamais le contenu des fichiers | (i) Refuser si les empreintes recalculées avant transmission diffèrent de celles de l'autorisation. (ii) Lire chaque fichier une seule fois et réutiliser le même contenu. (iii) Copier les fichiers dans un emplacement figé avant la vérification. (iv) Rendre le contrat P2.26 obligatoire, puisqu'il refuse déjà ce décalage | (i), en place depuis la Phase E2, est local et simple, mais laisse une fenêtre résiduelle entre le dernier contrôle et toute lecture ultérieure des fichiers par un Provider. (ii) supprime la fenêtre côté Director, pas côté Provider si celui-ci relit le fichier. (iii) ajoute une gestion de copies et de nettoyage. (iv) change le chemin d'exécution pour tous les appelants |
| **A2-d. Une seule machine, un seul dossier d'état** | (i) Déclarer l'exécution mono-machine comme contrainte d'exploitation, vérifiée par une procédure. (ii) Registre partagé externe | (i) n'empêche rien techniquement : c'est une règle, pas un contrôle. (ii) exige réseau, service et dépendances, absents aujourd'hui |
| **A2-e. Suppression manuelle du registre.** Supprimer `consumed_authorizations.json` ou `state/` rend réutilisables les autorisations consommées | (i) Recouper avec un journal durable (section 5). (ii) Faire choisir l'identifiant et le nonce par l'émetteur, qui garde sa propre trace (dépend de la condition 1). (iii) Traiter un registre absent comme bloquant après une première initialisation explicite. (iv) Accepter le risque, borné par l'expiration | (i) n'aide que si le journal n'est pas supprimable par le même geste. (iii) exige un marqueur d'initialisation, lui-même supprimable s'il vit dans `state/`. (iv) laisse une réutilisation possible pendant la fenêtre de validité |
| **A2-f. Consommation sans transaction commune avec le marqueur « en vol ».** Un arrêt entre les deux brûle l'autorisation sans exécution | (i) Conserver : l'échec est fermé. (ii) Écrire consommation et marqueur dans une seule écriture atomique | (i) coûte une nouvelle autorisation après un arrêt. (ii) réunit deux registres aujourd'hui séparés à dessein (P3.89 : aucune donnée d'autorisation dans `executed_requests.json`) |
| **A2-g. Horloge murale.** Un recul de l'horloge système prolonge la fenêtre d'expiration | (i) Mémoriser le dernier instant observé dans l'état persistant et refuser tout recul. (ii) Horodatage fourni par l'émetteur (dépend de la condition 1). (iii) Accepter le risque | (i) ajoute un état persistant, supprimable comme le registre (A2-e), et peut bloquer après une correction d'horloge légitime. (iii) laisse la fenêtre sous le contrôle de qui règle l'horloge |
| **A2-h. `authorized_at` rempli par défaut.** L'instant d'autorisation peut être celui de la construction de l'objet | (i) Exiger une valeur explicite. (ii) Valeur fournie par l'émetteur (dépend de la condition 1) | (i) casse les constructeurs existants sans empêcher l'appelant de fournir l'instant courant |
| **A2-i. Registre jamais purgé** | (i) Purger les entrées plus anciennes que la fenêtre d'expiration. (ii) Archiver par rotation. (iii) Laisser grandir | (i) rouvre un rejeu si l'horloge recule (A2-g). (ii) ajoute une procédure. (iii) est sans risque de sécurité, avec une croissance d'une entrée par tentative |
| **A2-j. Stores en mémoire.** Ils ne survivent pas à un redémarrage | (i) Les réserver aux tests, avec une garde qui refuse un store en mémoire hors du Mock reconnu. (ii) Conserver l'état actuel | (i) ajoute un contrôle de configuration. (ii) laisse la distinction à la charge de l'appelant |

**Décisions du propriétaire**

- Pour chaque limite, laquelle doit être fermée avant toute nouvelle décision, et laquelle peut rester un risque accepté et documenté.
- L'exécution est-elle déclarée mono-machine (A2-d) ?
- Les paramètres vidéo entrent-ils dans l'autorisation (A2-b) ?
- Le contrat P2.26 devient-il obligatoire sur tout chemin réel (A2-c) ?

**Preuves et tests requis (selon les options retenues plus tard)**

- A2-b : une autorisation valide pour un contenu, présentée avec une durée, une résolution, un format ou un modèle différent, n'est jamais `APPROVED`.
- A2-c : un fichier remplacé entre la vérification et le dernier contrôle n'atteint jamais `create_job()` (Mock), et rien n'est consommé à tort : couvert depuis la Phase E2 par `tests/test_phase_e2_final_content_verification.py`, qui documente aussi la limite restante (un remplacement après le dernier contrôle n'est pas détecté). Pour (ii), (iii) ou (iv) : preuves à définir avec l'option.
- A2-e : registre supprimé puis autorisation rejouée, avec le résultat attendu par l'option retenue.
- A2-f : arrêt simulé entre consommation et marqueur, sans exécution ni état `APPROVED` au redémarrage.
- A2-g : horloge reculée, sans prolongation de la fenêtre.
- A2-i : purge, puis rejeu d'un identifiant purgé.
- Dans tous les cas : tests mock-only, dossier d'état temporaire, aucun accès au `state/` réel.

## 4. Condition 3 — plafond de crédits

**Aucun montant n'est fixé par ce document.** Aucun montant n'est proposé, suggéré ni déduit d'un coût observé. Le montant du plafond, par requête comme par période, appartient au propriétaire du projet.

**État actuel**

- Un plafond par requête est appliqué par la Gate et par P2.26 s'il est configuré. Aucun code de production n'en configure : la chaîne réelle de `director.py` est `BLOCKED` par construction.
- Les plafonds des tests sont des fixtures fictives (`tests/real_provider_path_fixtures.py`), qu'aucun code de production n'importe.
- Aucun plafond par période n'existe.

**Questions ouvertes et options**

| Question | Options | Compromis |
|---|---|---|
| **P-a. Source du plafond par requête** | (i) Paramètre explicite fourni par l'appelant à chaque exécution. (ii) Fichier de configuration hors du dépôt. (iii) Valeur portée par l'énoncé attesté (Phase C, exigence L1 ; dépend de la condition 1) | (i) laisse le montant au code appelant, donc à toute automatisation. (ii) sort le montant du dépôt, mais reste lisible et modifiable par le compte. (iii) est la seule option qui lie le montant à la personne qui autorise, et elle n'existe pas sans identité |
| **P-b. Plafond par période : définition de la période** | (i) Fenêtre glissante. (ii) Période calendaire. (iii) Compteur cumulé sans remise à zéro, relevé seulement par décision écrite | (i) et (ii) reposent sur l'horloge murale (limite A2-g). (iii) ne dépend d'aucune horloge, mais demande une décision à chaque relèvement |
| **P-c. Plafond par période : source du cumul** | (i) Compteur local persistant dans le dossier d'état. (ii) Historique du compte fournisseur, lu en lecture seule. (iii) Les deux, avec blocage en cas d'écart | (i) est supprimable à la main, comme le registre de consommation (A2-e). (ii) dépend du réseau et de la fidélité de l'historique, à démontrer. (iii) est le plus strict et bloque au moindre écart |
| **P-d. Moment du décompte** | (i) Réserver le coût attendu avant `create_job()`. (ii) Compter après confirmation du job | (i) échoue fermé, et une tentative avortée consomme du plafond. (ii) laisse une fenêtre où deux exécutions dépassent ensemble le plafond |
| **P-e. État d'exécution inconnu** | (i) Compter le coût attendu comme dépensé. (ii) Bloquer tout décompte jusqu'à revue humaine | (i) peut surestimer la dépense. (ii) bloque toute exécution suivante, ce qui est cohérent avec `EXECUTION_STATE_UNKNOWN` |

**Décisions du propriétaire**

- Le montant du plafond par requête.
- L'existence, la définition et le montant d'un plafond par période.
- La source du plafond (P-a) et celle du cumul (P-c).
- Qui peut modifier un plafond, et par quel acte écrit.

**Preuves et tests requis (selon les options retenues plus tard)**

- Un coût supérieur au plafond par requête n'est jamais `APPROVED` (déjà couvert par `tests/test_phase_d_cost_fail_closed.py` avec des valeurs fictives).
- Plafond par période : un cumul qui dépasserait le plafond bloque avant `create_job()` ; compteur absent, corrompu ou illisible bloque ; deux exécutions concurrentes ne dépassent pas ensemble le plafond.
- Aucun montant réel dans le dépôt, les tests ou les journaux, sauf décision écrite du propriétaire.
- Tests mock-only, sans réseau, sans accès au `state/` réel.

## 5. Condition 5 — révocation persistante et journal d'audit

**Révocation : options**

| Option | Ce qu'elle apporte | Compromis |
|---|---|---|
| **R-a. Registre de révocation persistant** dans le dossier d'état, sur le modèle du registre de consommation (écriture atomique, verrou, échec fermé) | Une autorisation ou un contrat révoqué le reste après un redémarrage | Supprimable à la main comme `consumed_authorizations.json` (A2-e). Garantie limitée à une machine |
| **R-b. Révocation par consommation anticipée** : révoquer une autorisation revient à la consommer dans le registre existant | Aucun nouveau registre | Confond « utilisée » et « révoquée » dans les traces. Ne couvre pas les contrats P2.21 et P2.26, qui vivent en mémoire |
| **R-c. Révocation par l'émetteur** (dépend de la condition 1) | La révocation est décidée hors du processus | N'existe pas sans identité. Exige de consulter l'émetteur à chaque exécution, avec blocage s'il est indisponible |
| **R-d. Révocation globale** : un état « tout est révoqué » consulté avant toute exécution | Un seul geste arrête tout | Recouvre la condition 7 (section 6) : à concevoir ensemble |

**Journal d'audit : options**

| Option | Ce qu'elle apporte | Compromis |
|---|---|---|
| **J-a. Fichier local append-only** dans le dossier d'état, une entrée par événement | Trace durable des autorisations, préparations, refus et tentatives | Modifiable et supprimable par le compte : l'append-only est une convention, pas une garantie |
| **J-b. Fichier local chaîné** : chaque entrée porte l'empreinte de la précédente | Une altération partielle devient détectable | Une réécriture complète de la chaîne reste possible sans ancre externe. Aucun mécanisme de clé n'existe actuellement dans le code (Phase C, section 1) |
| **J-c. Ancre externe** : l'empreinte de tête est recopiée hors du poste | Détecte une réécriture complète | Exige un canal et une procédure hors du processus, absents aujourd'hui |
| **J-d. Service de journalisation externe** | Durabilité indépendante du poste | Réseau, dépendance et compte supplémentaires, absents aujourd'hui |

**Exigences communes, quelle que soit l'option**

- Le journal ne contient jamais de secret ni de token : seulement des identifiants, des empreintes, des décisions et des dates.
- Une écriture de journal impossible avant `create_job()` bloque l'exécution.
- Les refus sont journalisés au même titre que les tentatives.
- Le journal ne devient jamais une source d'autorisation : il trace, il ne décide pas.

**Décisions du propriétaire**

- Ce qui doit être révocable : autorisation, contrat P2.21, contrat P2.26, ou tout à la fois.
- Qui peut révoquer, et si une révocation peut être annulée.
- L'emplacement du journal, sa durée de conservation et sa sauvegarde, `state/` n'étant pas versionné.
- Le niveau de résistance attendu : erreur et accident, ou attaquant local.

**Preuves et tests requis (selon les options retenues plus tard)**

- Une autorisation ou un contrat révoqué puis présenté après un redémarrage simulé n'est jamais `APPROVED` et n'atteint jamais `create_job()`.
- Registre de révocation absent, corrompu ou verrouillé : blocage.
- Chaque chemin (autorisation, préparation, refus, tentative) produit une entrée de journal ; aucune entrée ne contient de secret ni de token.
- Écriture de journal en échec : aucune exécution.
- Tests mock-only, dossier d'état temporaire.

## 6. Condition 7 — arrêt et refermeture

Les quatre verrous étant fermés, il n'y a rien à arrêter aujourd'hui. La condition demande une procédure documentée et testée **avant** toute ouverture, pour qu'elle existe le jour où elle servirait.

| Option | Ce qu'elle apporte | Compromis |
|---|---|---|
| **S-a. Refermeture par le code** : annuler le changement qui aurait ouvert un verrou, puis repasser les tests et l'audit `NO_DRIFT` | S'appuie sur les verrous et les gardes existants (P3.83, cardinalités) | Lente : elle n'arrête pas un processus déjà lancé |
| **S-b. Interrupteur persistant** consulté avant `create_job()`, fermé par défaut : seule une ouverture explicite et valide laisse passer | Arrêt immédiat des nouvelles exécutions, sans modifier le code | Modifiable par le compte. Ajoute un état dont l'absence ou la corruption doit bloquer |
| **S-c. Arrêt au niveau du compte fournisseur** : retirer l'authentification du CLI | Hors du processus : aucun code local ne peut passer outre | Dépend du fournisseur. Pourrait aussi couper les lectures (coût, solde) : conséquence à vérifier, non démontrée |
| **S-d. Jobs déjà lancés** : annulation côté fournisseur | Limite la dépense d'un job en cours | Disponibilité non démontrée : le client n'autorise aucun verbe d'annulation, et l'effet sur la facturation est inconnu |

Ces options ne s'excluent pas. S-b recouvre la révocation globale (R-d).

**Décisions du propriétaire**

- Qui peut déclencher l'arrêt, et par quel geste.
- Ce que « immédiat » signifie : nouvelles exécutions seulement, ou aussi les jobs en cours.
- Qui peut rouvrir après un arrêt, et par quelle décision écrite.
- Si la procédure doit fonctionner sans réseau.

**Preuves et tests requis (selon les options retenues plus tard)**

- Après l'arrêt, tous les chemins (`run_video_mission()`, préparation, composition, `GenerationJobService.execute()`) sont bloqués avant `create_job()`.
- État d'arrêt absent, illisible ou corrompu : blocage.
- L'arrêt survit à un redémarrage.
- La procédure écrite a été déroulée de bout en bout sur le Mock, et ce déroulé est consigné.
- Les quatre verrous, les cardinalités et `NO_DRIFT` restent verts après la refermeture.

## 7. Dépendances entre conditions

- La condition 1 conditionne les options A2-a, A2-b (ii), A2-e (ii), A2-g (ii), A2-h (ii), P-a (iii) et R-c.
- Le journal (condition 5) conditionne A2-e (i).
- La révocation globale (R-d) et l'interrupteur (S-b) décrivent le même mécanisme vu de deux conditions.
- Tout état persistant local (registre, compteur, journal, interrupteur) partage la limite A2-e : il est supprimable par le compte.

## 8. Ce que cette phase ne fait pas

- Aucune modification de `agents/`, `integrations/`, `director.py` ni `scripts/`.
- Aucun changement de comportement, aucune dépendance ajoutée, aucun mécanisme cryptographique, réseau ou sous-processus introduit.
- Aucun montant de plafond fixé ou proposé.
- Aucune option n'est choisie : chaque choix appartient au propriétaire du projet.
- Aucun verrou desserré ; aucune génération réelle ; aucun crédit consommé.
- Les conditions 1, 3, 5 et 7 restent **ouvertes**, la condition 2 reste **partiellement traitée**, et le **NO-GO** reste en vigueur.
- Des gardes documentaires (`tests/test_phase_e1_documentary_invariants.py`) vérifient que ces statuts, le NO-GO, Provider = CLOSED et l'absence de montant restent explicites.

## 9. Suite possible, sur décision seulement

1. Le propriétaire prend les décisions listées dans les sections 3 à 6, par écrit.
2. Des phases d'implémentation distinctes réalisent les options retenues, en échec fermé et avec des tests mock-only. Le Provider reste fermé.
3. Seule une nouvelle décision écrite, distincte de la décision de Phase A, pourrait constater que les sept conditions sont remplies.

**Provider = CLOSED · Real generation = 0 · Credits = 0**
