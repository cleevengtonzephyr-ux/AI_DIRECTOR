# G2 D-5 — proposition de parcours d’inscription (brouillon)

> **Statut : frontière des rôles confirmée par le propriétaire le 23 octobre 2026 ; parcours technique encore à examiner.** Ce document ne crée aucun compte, aucune invitation, aucun credential ni aucune preuve de séparation. Il n’autorise ni consommation d’approbation, ni Provider, ni déploiement.

## But

Préparer l’inscription de l’approbatrice B désignée le 23 octobre 2026, en respectant les décisions D-2 à D-5 et D-9 à D-15. La désignation de B est une décision humaine ; elle ne lie encore aucun compte GitHub ou authentificateur WebAuthn à cette personne.

## Parcours proposé

1. **Frontière des rôles décidée.** Le propriétaire administre seul le registre par le mécanisme SSH d’administration prévu par D-2. B est approbatrice uniquement : elle ne crée ni ne révoque de comptes, d’approbateurs, de credentials ou d’invitations. Aucun endpoint web d’administration n’est exposé. La configuration effective du compte SSH autorisé, son contrôle d’accès et sa journalisation restent à concevoir et à vérifier.
2. **Invitation à usage unique.** L’invitation est liée à un identifiant d’approbateur et à un principal prédéfinis. Elle contient un secret aléatoire, n’est utilisable qu’une fois et expire rapidement. La base ne conserve que son empreinte ; le secret n’est montré qu’à sa création et remis à B par un canal choisi à part. La durée exacte et le canal restent à décider.
3. **Preuve de contrôle du compte GitHub (option à confirmer).** Une piste est que B lance elle-même un workflow dédié et que le vérificateur contrôle un jeton OIDC limité au dépôt et au workflow choisis, puis récupère l’identifiant numérique signé du compte (`actor_id`). Cela prouverait au mieux le contrôle de ce compte pendant ce run ; pas l’identité civile de B ni, à lui seul, la séparation de deux personnes. Le dépôt AI_DIRECTOR est public : B peut lire et examiner le code sans invitation ni droit d’écriture. La revue du dépôt ne vaut pas liaison de son compte à son identité d’approbatrice. Si la preuve P-1 exige que B lance un workflow, les permissions GitHub nécessaires restent à établir séparément ; aucun droit d’écriture ne lui est attribué par la présente décision. Le workflow, ses permissions et les protections du dépôt restent à spécifier selon D-15.
4. **Inscription WebAuthn.** B utilise l’invitation pour inscrire un premier identifiant avec vérification locale (UV). Une cérémonie séparée inscrit un second identifiant sur un authentificateur distinct, destiné au secours. Les règles D-3 et D-4 (BE/BS, UV, RP ID et origine exacts) sont appliquées. La première UV ne remplace pas l’invitation et ne sert pas à autoriser sa propre inscription.
5. **Liaison du compte et séparation au moment d’une demande.** L’inscription par invitation n’établit aucune liaison avec un compte GitHub et ne compare pas B à l’acteur d’un run. Une preuve de contrôle du compte, sa liaison au principal par l’administrateur et la trace de cette attestation restent à décider. Lors d’une future demande, le service devra comparer le `actor_id` vérifié au compte lié à l’approbateur et refuser si les deux appartiennent au même principal. Cette comparaison ne prouve pas à elle seule que deux personnes distinctes interviennent.
6. **Maintien du refus fermé.** Tant que les contrôles précédents, la preuve de séparation humaine et la vérification des protections GitHub ne sont pas établis, aucune approbation ne peut être consommée et Provider = CLOSED, NO-GO restent inchangés.

## Contrat de stockage v4 (mock-only)

- Le stockage actuel de G2 est strictement validé en version 3 : toute table supplémentaire ou toute version différente est refusée, et aucune migration n’existe. Ajouter les invitations au même registre nécessite donc un schéma version 4, créé uniquement dans un nouveau fichier ; une base existante ne sera ni modifiée ni migrée automatiquement.
- Une invitation doit être créée avec un secret cryptographiquement aléatoire d’au moins 256 bits, lié à un `approver_id` et un `principal_id` immuables. La primitive retourne le secret au processus appelant une seule fois ; le registre ne conserve que son empreinte SHA-256. La remise à B par un administrateur authentifié relève d’une étape distincte.
- L’enregistrement conserve les instants de création et d’expiration, ainsi qu’un état terminal (`CONSUMED`, `EXPIRED` ou `REVOKED`). Les identifiants d’approbateur et de principal restent des identifiants de registre ; cette étape n’y lie encore aucun compte GitHub, aucune personne vérifiée ni credential WebAuthn.
- La consommation doit utiliser une transaction d’écriture (`BEGIN IMMEDIATE`) et refuser de façon indiscernable un secret inconnu, expiré, révoqué ou déjà consommé. La consommation et l’activation des lignes de registre doivent être atomiques dans la même transaction ; aucun appel séparé ne doit pouvoir brûler le jeton avant une inscription réussie.
- La durée exacte de validité, le canal de remise à B, l’authentification de l’administrateur SSH et la preuve de liaison de B restent ouverts. L’incrément ne doit pas les inventer ni exposer une interface d’administration.
- Aucun jeton réel, compte réel, credential WebAuthn réel, endpoint, service déployé ou appel Provider n’est créé par cet incrément. Les primitives de stockage seules ne constituent pas une frontière d’administration : l’accès reste limité au code mock-only jusqu’à une étape distincte qui authentifie l’administrateur.

## État du dépôt vérifié en lecture seule (23 octobre 2026)

- GitHub indique que AI_DIRECTOR est public, appartient au compte personnel cleevengtonzephyr-ux et utilise main comme branche par défaut. B peut donc lire le code avec le lien public ; aucune invitation ni permission Write n’est nécessaire pour cette consultation.
- Le ruleset actif Protect main cible refs/heads/main. Il exige une pull request, la résolution des fils de revue, le contrôle tests et CodeQL (seuil d’alerte élevé ; erreurs de scan bloquantes), et interdit suppression et réécriture non fast-forward. Aucun acteur de contournement n’est configuré.
- Le ruleset exige zéro approbation humaine (required_approving_review_count = 0). Cette règle protège la fusion contre les changements directs et les contrôles manquants, mais n’impose pas une validation par B.
- Le contrôle du ruleset était en lecture seule. Aucun réglage GitHub n’a été modifié et aucune invitation n’a été envoyée.

## Décisions et points restant à établir avant l’inscription

- **Décidé :** le propriétaire tient seul le rôle d’administrateur SSH ; B est approbatrice uniquement et n’administre pas le registre.
- **Décidé par le propriétaire le 24 octobre 2026 :** `actor_id` reste obligatoire dans le vérificateur OIDC et son absence entraîne un refus fermé. Sa présence et sa représentation dans un jeton réel restent non vérifiées ; cette décision n’autorise pas l’utilisation d’un jeton réel.
- Définir et vérifier comment le compte SSH du propriétaire est autorisé à gérer le registre, et comment ces opérations sont journalisées.
- La lecture et la revue du code public ne nécessitent aucun accès collaborateur. Si le workflow de preuve P-1 doit être lancé par B, déterminer séparément les permissions GitHub requises ; la présente décision ne lui attribue aucun droit d’écriture.
- Quelle durée courte pour l’invitation, et par quel canal séparé le secret sera-t-il remis à B ?
- Quelle action exacte de B confirme la liaison de son compte, et quelle trace l’administrateur conserve-t-il sans prétendre prouver une identité civile ?
- Comment la possession d’un second authentificateur séparé sera-t-elle vérifiée et son usage de secours protégé ?
- La présence et la forme de actor_id dans un vrai jeton OIDC restent à vérifier séparément ; aucun jeton réel n’est autorisé par la désignation actuelle.

## Premier incrément de code — prototype mock-only (24 octobre 2026)

Le module `approval_service/approval_service/approval_store_v4.py` ajoute une variante fraîche du stockage en schéma 4. Le stockage v3 reste inchangé et refuse les bases v4. Le nouveau module n’effectue aucune migration : `initialize` refuse tout fichier existant, et l’ouverture n’accepte qu’un fichier dont les objets sont exactement ceux du schéma 4 ; une base v3 est donc refusée. Il permet de créer une invitation liée à un `approver_id` et un `principal_id`, d’en consommer le secret une seule fois pour activer ces deux lignes dans la même transaction, de la révoquer ou de marquer les invitations expirées. Seule l’empreinte SHA-256 du secret est conservée. L’appelant fournit l’instant absolu d’expiration ; aucune durée n’est choisie ici.

Ce prototype n’est pas encore une frontière d’administration : ses méthodes ne vérifient pas que leur appelant est le propriétaire et ne doivent pas être exposées à un service ou à une interface. Il n’inscrit aucun compte GitHub, aucune personne vérifiée et aucun credential WebAuthn. L’étape ne résout donc pas D-5. La preuve P-1, les protections GitHub et l’authentification SSH restent à établir ; Provider = CLOSED et NO-GO restent en vigueur.

**Validation locale après les dernières corrections (24 octobre 2026).** `tests/test_g2_approval_store_v4.py` ajoute 32 tests synthétiques. Ils utilisent uniquement des bases temporaires et des secrets générés par le module testé. Ils vérifient :

- un schéma 4 créé seulement dans un nouveau fichier : les fichiers existants (v4, v3 ou vide) restent identiques octet pour octet, et les fichiers `-wal` ou `-shm` résiduels sont refusés ;
- le schéma 3 inchangé : le schéma 4 n’ajoute que la table des invitations, et v3 et v4 se refusent mutuellement ;
- un secret de 256 bits dont seule l’empreinte SHA-256 est stockée : le secret ne figure dans aucune ligne, dans aucun fichier de la base, ni dans la représentation `repr` de l’objet retourné ;
- l’expiration à l’instant exact, la révocation définitive et un refus identique pour un secret inconnu, expiré, révoqué, déjà consommé ou mal formé ;
- la consommation unique, avec activation du principal et de l’approbateur dans la même transaction `BEGIN IMMEDIATE` ;
- un retour arrière complet lorsque l’activation échoue, et l’absence de tout effet après l’arrêt brutal d’un processus juste avant `COMMIT` ;
- le refus de `INSERT OR REPLACE`, `REPLACE` et `UPDATE OR REPLACE`, ainsi que de toute suppression, modification ou réouverture par SQL direct ;
- la concurrence entre 2 et 8 fils d’exécution, puis entre 4 processus, sur le même secret.

Sept mutations temporaires, appliquées à une copie hors du dépôt, ont toutes été détectées : réutilisation d’une invitation consommée, borne d’expiration décalée, message de refus révélateur, déclencheur anti-remplacement neutralisé, jeton brûlé dans une transaction séparée, secret en clair écrit dans la base, secret présent dans `repr`.

Ces tests ont conduit à deux corrections du prototype :

- le secret est exclu de `repr(IssuedInvitation)` ;
- une invitation déjà ouverte pour le même approbateur ou principal est refusée explicitement (`ApprovalRefusedError`), au lieu d’apparaître comme une défaillance du stockage.

Une invitation expirée pour la même liaison est maintenant marquée `EXPIRED` dans la transaction qui crée l’invitation suivante. Un conflit avec une ligne de registre déjà ajoutée produit un refus générique (`ApprovalRefusedError`) ; la transaction est entièrement annulée, y compris si l’insertion du principal avait réussi avant l’échec de l’approbateur.

Résultats sous Windows, Python 3.14.5, avec les dépendances verrouillées de `approval_service/` installées dans un environnement temporaire hors du dépôt. Les résultats ci-dessous sont ceux obtenus après mise à jour du test de contrat CI pour inclure la suite v4 :

- tests ciblés : 32 tests OK ;
- tests G2 : 197 tests OK (2 ignorés) ;
- suite complète : 3189 tests OK (2 ignorés) ;
- tests `test_phase_f_production_path.py` : 63 tests OK ;
- audit d’architecture : `NO_DRIFT`.

Le job `posix-approval-store` lance maintenant les suites v3 et v4 sous Ubuntu, tout en conservant son nom de contrôle GitHub antérieur. La validation Windows ne vérifie pas le comportement Linux (verrous `fcntl`, mémoire partagée WAL et permissions POSIX) ; celui-ci ne sera confirmé qu’après le prochain passage de ce job CI. Ce prototype reste local et mock-only ; il n’est ni fusionné ni utilisable comme frontière d’administration.

## Limites

Ce brouillon n’affirme pas que D-5 est satisfait. Il n’autorise aucune inscription réelle ni l’utilisation du compte, du jeton OIDC ou des authentificateurs de B.
