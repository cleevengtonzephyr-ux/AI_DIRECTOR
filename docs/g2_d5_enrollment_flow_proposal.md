# G2 D-5 — proposition de parcours d’inscription (brouillon)

> **Statut : frontière des rôles confirmée par le propriétaire le 23 octobre 2026 ; choix de conception de la preuve de compte GitHub acceptés le 24 octobre 2026 ; parcours technique encore à concevoir.** Ce document ne crée aucun compte, aucune invitation, aucun credential, aucune GitHub App ni aucune preuve de séparation. Il n’autorise ni consommation d’approbation, ni Provider, ni déploiement.

## But

Préparer l’inscription de l’approbatrice B désignée le 23 octobre 2026, en respectant les décisions D-2 à D-5 et D-9 à D-15. La désignation de B est une décision humaine ; elle ne lie encore aucun compte GitHub ou authentificateur WebAuthn à cette personne.

## Parcours proposé

1. **Frontière des rôles décidée.** Le propriétaire administre seul le registre par le mécanisme SSH d’administration prévu par D-2. B est approbatrice uniquement : elle ne crée ni ne révoque de comptes, d’approbateurs, de credentials ou d’invitations. Aucun endpoint web d’administration n’est exposé. La configuration effective du compte SSH autorisé, son contrôle d’accès et sa journalisation restent à concevoir et à vérifier.
2. **Invitation à usage unique.** L’invitation est liée à un identifiant d’approbateur et à un principal prédéfinis. Elle contient un secret aléatoire, n’est utilisable qu’une fois et expire rapidement. La base ne conserve que son empreinte ; le secret n’est montré qu’à sa création et remis à B par un canal choisi à part. La durée exacte et le canal restent à décider.
3. **Preuve de contrôle du compte GitHub (choix de conception du 24 octobre 2026).** B autorise, avec son propre compte, une GitHub App sans permission et non installée, par le flux Web. L’ID obtenu avec `GET /user` doit être égal à l’ID attendu, communiqué par un canal séparé (voir la section « Décision du propriétaire (24 octobre 2026) »). B ne lance aucun workflow et n’obtient aucun droit d’écriture. Cela prouve au mieux le contrôle de ce compte à un instant donné ; pas l’identité civile de B ni la séparation de deux personnes. Le dépôt AI_DIRECTOR est public : B peut lire et examiner le code sans invitation ni droit d’écriture. La revue du dépôt ne vaut pas liaison de son compte à son identité d’approbatrice.
4. **Inscription WebAuthn.** B utilise l’invitation pour inscrire un premier identifiant avec vérification locale (UV). Une cérémonie séparée inscrit un second identifiant sur un authentificateur distinct, destiné au secours. Les règles D-3 et D-4 (BE/BS, UV, RP ID et origine exacts) sont appliquées. La première UV ne remplace pas l’invitation et ne sert pas à autoriser sa propre inscription.
5. **Liaison du compte et séparation au moment d’une demande.** L’inscription par invitation du prototype v4 n’établit aucune liaison avec un compte GitHub et ne compare pas B à l’acteur d’un run. La preuve de contrôle du compte suit le parcours décidé le 24 octobre 2026 ; l’état d’attente, la confirmation par l’administrateur et la trace distincte de la preuve restent à concevoir. Lors d’une future demande, le service devra comparer le `actor_id` vérifié au compte lié à l’approbateur et refuser si les deux appartiennent au même principal. Cette comparaison ne prouve pas à elle seule que deux personnes distinctes interviennent.
6. **Maintien du refus fermé.** Tant que les contrôles précédents, la preuve de séparation humaine et la vérification des protections GitHub ne sont pas établis, aucune approbation ne peut être consommée et Provider = CLOSED, NO-GO restent inchangés.

## Décision du propriétaire (24 octobre 2026) : preuve de contrôle du compte GitHub de B

Le propriétaire a accepté le 24 octobre 2026 les choix de conception ci-dessous. Ce sont des choix de conception seulement : aucune GitHub App, aucun secret, aucun jeton ni aucun compte n’est créé, et rien n’est déployé. D-5 reste non résolu ; Provider = CLOSED et NO-GO restent en vigueur.

**Choix retenus**

- **GitHub App sans permission, non installée, flux Web seulement.** L’application ne demande aucune permission et n’est installée sur aucun compte ni dépôt ; elle sert uniquement à ce que B l’autorise avec son propre compte GitHub. Le flux Web utilise PKCE `S256`, un `state` aléatoire lié à la session d’inscription et une URI de callback exacte, sans correspondance générique. Le Device Flow est désactivé. B n’obtient aucun accès Write et ne lance aucun workflow dans le dépôt : la piste d’un workflow lancé par B, envisagée jusqu’ici pour cette preuve, n’est pas retenue.
- **ID attendu communiqué à part.** L’ID numérique du compte GitHub de B est communiqué au propriétaire par un canal séparé, avant l’inscription. L’ID obtenu avec `GET /user`, au moyen du jeton issu de cet échange, doit lui être égal ; sinon l’inscription est refusée. Le login n’intervient jamais dans cette comparaison.
- **Inscription en attente.** L’inscription reste en attente jusqu’à la confirmation du propriétaire par SSH. Aucune ligne n’est active avant cette confirmation.
- **Preuve distincte de `ADMIN_ATTESTED`.** La preuve de contrôle du compte GitHub est enregistrée séparément de l’attestation administrative `ADMIN_ATTESTED` ; l’une ne remplace pas l’autre.
- **Aucun login ni jeton conservé.** Ni le login ni aucun jeton OAuth (jeton d’accès ou de rafraîchissement) n’est conservé. Le grant de B est révoqué dès que l’ID est lu.
- **Secret client.** La GitHub App possède un secret client. Il reste à protéger et à gérer selon une décision D-15 encore ouverte.

**Parcours visé (non implémenté)**

1. Le propriétaire crée par SSH une invitation et y associe l’ID attendu de B, reçu par un canal séparé.
2. B ouvre le service et présente le secret de l’invitation. Le service ouvre une session d’inscription sans consommer l’invitation.
3. Le service redirige B vers GitHub avec le `state` et le défi PKCE `S256` ; B se connecte avec son compte et autorise l’application.
4. Au retour sur l’URI de callback exacte, le service vérifie le `state`, échange le code avec le vérificateur PKCE et lit l’ID avec `GET /user`.
5. Le service compare cet ID à l’ID attendu, révoque le grant et ne conserve pas le jeton.
6. B inscrit son identifiant WebAuthn avec UV, selon D-2 à D-4. L’invitation est consommée et l’inscription est enregistrée en attente.
7. Le propriétaire confirme l’inscription par SSH ; elle ne devient active qu’à ce moment.

**Écart avec le stockage v4 actuel.** Le prototype v4 active le principal et l’approbateur dès la consommation de l’invitation, dans la même transaction, et ne crée aucune liaison de compte GitHub ; la colonne `github_accounts.evidence` n’accepte aujourd’hui que `ADMIN_ATTESTED`. Avant toute implémentation de ce parcours, il faudra concevoir un état d’attente jusqu’à la confirmation SSH, ainsi que l’enregistrement distinct de la preuve de compte GitHub. Cette décision ne modifiait pas le code du stockage. Le deuxième incrément de code (schéma v5, section « Deuxième incrément de code » ci-dessous) ajoute ensuite cet état d’attente dans un prototype mock-only, sans modifier v4.

**Points qui restent ouverts**

- **H1.** L’équivalence entre l’ID REST renvoyé par `GET /user` et le claim `actor_id` du jeton OIDC n’est pas prouvée. La documentation GitHub décrit les deux comme l’identifiant du compte, sans les déclarer identiques. Aucun essai avec un jeton OIDC réel n’est autorisé.
- **D-12.** L’URI de callback est une interface publique : aucun callback public ne doit être déployé avant une décision séparée.
- **Secret client (D-15).** Son stockage et sa rotation restent à décider.
- **Portée de la preuve.** Ce mécanisme prouve le contrôle d’un compte GitHub à un instant donné. Il ne prouve ni l’identité civile de B ni la séparation de deux personnes.
- **À vérifier avant l’enregistrement de l’application :** que B peut autoriser l’application selon la visibilité choisie, et que la révocation du grant invalide aussi le jeton de rafraîchissement. Le comportement en cas d’échec de la révocation reste à spécifier.
- **Non tranchés :** la liaison du compte GitHub du propriétaire à son principal, la conduite à tenir si le compte de B change ou est compromis, et la protection du compte GitHub de B, que ce mécanisme ne permet pas de vérifier.

**Références (documentation officielle GitHub, consultée le 24 octobre 2026)**

- [Generating a user access token for a GitHub App](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app) : flux Web, `state`, PKCE `S256`, expiration des jetons.
- [Authorizing OAuth apps](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps) : URI de callback exacte, risque de la correspondance générique, Device Flow.
- [Authenticating with a GitHub App on behalf of a user](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-with-a-github-app-on-behalf-of-a-user) : autorisation possible sans installation.
- [Choosing permissions for a GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app) et [Endpoints available for GitHub App user access tokens](https://docs.github.com/en/rest/authentication/endpoints-available-for-github-app-user-access-tokens) : aucune permission par défaut ; `GET /user` disponible.
- [Best practices for creating a GitHub App](https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/best-practices-for-creating-a-github-app) : identifier l’utilisateur par son `id`, Device Flow réservé aux environnements contraints, révocation des jetons.
- [REST API endpoints for OAuth authorizations](https://docs.github.com/en/rest/apps/oauth-applications?apiVersion=2022-11-28) : révocation d’un grant.
- [OpenID Connect reference](https://docs.github.com/en/actions/reference/security/oidc) : définition de `actor_id`.

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
- **Décidé par le propriétaire le 24 octobre 2026 :** la preuve de contrôle du compte GitHub de B passe par une GitHub App sans permission, non installée, et par le flux Web (voir la section dédiée). B n’a besoin d’aucun accès collaborateur ni droit d’écriture et ne lance aucun workflow. La lecture et la revue du code public ne nécessitent pas non plus d’accès collaborateur.
- Quelle durée courte pour l’invitation, et par quel canal séparé le secret sera-t-il remis à B ?
- Combien de temps une inscription peut-elle rester en attente de la confirmation SSH ? Le prototype v5 ne fixe aucune expiration.
- L’action de B est l’autorisation de la GitHub App, suivie de la confirmation SSH du propriétaire (décision du 24 octobre 2026). La forme exacte de la trace de la preuve et de cette confirmation reste à concevoir, sans prétendre prouver une identité civile.
- Comment la possession d’un second authentificateur séparé sera-t-elle vérifiée et son usage de secours protégé ?
- La présence et la forme de actor_id dans un vrai jeton OIDC restent à vérifier séparément ; aucun jeton réel n’est autorisé par la désignation actuelle.

## Premier incrément de code — prototype mock-only (24 octobre 2026)

Le module `approval_service/approval_service/approval_store_v4.py` ajoute une variante fraîche du stockage en schéma 4. Le stockage v3 reste inchangé et refuse les bases v4. Le nouveau module n’effectue aucune migration : `initialize` refuse tout fichier existant, et l’ouverture n’accepte qu’un fichier dont les objets sont exactement ceux du schéma 4 ; une base v3 est donc refusée. Il permet de créer une invitation liée à un `approver_id` et un `principal_id`, d’en consommer le secret une seule fois pour activer ces deux lignes dans la même transaction, de la révoquer ou de marquer les invitations expirées. Seule l’empreinte SHA-256 du secret est conservée. L’appelant fournit l’instant absolu d’expiration ; aucune durée n’est choisie ici.

Ce prototype n’est pas encore une frontière d’administration : ses méthodes ne vérifient pas que leur appelant est le propriétaire et ne doivent pas être exposées à un service ou à une interface. Il n’inscrit aucun compte GitHub, aucune personne vérifiée et aucun credential WebAuthn. L’étape ne résout donc pas D-5. La preuve de contrôle du compte GitHub de B (choix de conception du 24 octobre 2026, non implémentée), les protections GitHub et l’authentification SSH restent à établir ; Provider = CLOSED et NO-GO restent en vigueur.

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

## Deuxième incrément de code — inscription en attente, schéma v5 mock-only (24 octobre 2026)

Le module `approval_service/approval_service/approval_store_v5.py` ajoute un schéma 5 frais. Il reprend le schéma 3 à l’identique et lui ajoute deux tables : `enrollment_invitations` et `pending_enrollments`. Le schéma 4 et son module ne sont pas modifiés. Aucune migration n’existe : `initialize` refuse tout fichier existant (v3, v4, v5 ou vide) sans le modifier, et chacune des trois versions refuse d’ouvrir les fichiers des deux autres.

**Fonctionnement**

- **Invitation.** `create_invitation` lie l’invitation à un `approver_id`, à un `principal_id` et à l’ID numérique attendu du compte GitHub de B (`expected_account_id`). Elle est refusée si l’une de ces valeurs est déjà enregistrée, déjà invitée ou déjà en attente. Comme en v4, seule l’empreinte SHA-256 du secret est stockée.
- **Consommation.** `consume_invitation` reçoit le secret, un ID de compte fourni par l’appelant et les champs du credential WebAuthn. Si l’ID diffère de l’ID attendu, rien n’est écrit et l’invitation reste ouverte. Sinon, dans une seule transaction `BEGIN IMMEDIATE`, l’invitation passe à `CONSUMED` et une inscription `PENDING` est créée avec le credential et le contrôle `MOCK_UNVERIFIED_ACCOUNT_ID_MATCH`.
- **Aucune activation.** Aucune frontière SSH authentifiée n’existe ; le schéma v5 n’a donc ni primitive de confirmation ni état `CONFIRMED`. Une inscription ne peut que rester `PENDING` ou être clôturée `REJECTED` par `reject_enrollment`, sans rien activer ; `REJECTED` est définitif. Le module n’écrit jamais de ligne de principal, d’approbateur, de compte GitHub ou de credential : les opérations héritées de v3 ne voient aucune inscription.
- **Aucune expiration.** Une inscription en attente n’a pas de délai d’expiration et `expire_invitations` ne la modifie pas. Sa durée reste à décider.

**Ni preuve GitHub, ni attestation.** `MOCK_UNVERIFIED_ACCOUNT_ID_MATCH` enregistre seulement que deux identifiants fournis par l’appelant étaient égaux. Ce n’est ni une preuve de contrôle du compte GitHub, ni une attestation administrative `ADMIN_ATTESTED`. Des contraintes SQLite refusent tout autre libellé, l’état `CONFIRMED` et toute réouverture d’une inscription rejetée, y compris par SQL direct.

**Correction avant fusion (24 octobre 2026).** La première version de ce schéma, poussée sur la branche du PR #62 sans être fusionnée, contenait une primitive `confirm_enrollment`. Celle-ci activait le principal, l’approbateur, le compte GitHub et le credential, et marquait le compte `ADMIN_ATTESTED`, alors qu’elle n’authentifiait aucun administrateur. Le contrôle s’appelait en outre `EXPECTED_GITHUB_USER_ID_MATCHED`, ce qui pouvait passer pour une preuve GitHub réelle. Cette primitive, sa table de traces et l’état `CONFIRMED` sont retirés, et le contrôle est renommé. La conception de l’activation est reportée à l’étape qui établira la frontière SSH authentifiée.

**Limites**

- **Non authentifié.** Ces primitives n’authentifient aucun appelant. Elles sont réservées aux tests isolés et ne sont exposées par aucune interface ni aucun endpoint.
- **Rien n’est vérifié en amont.** Le module n’exécute aucun échange OAuth et ne vérifie aucune cérémonie d’inscription WebAuthn (défi, origine, RP ID, UV, attestation, règles D-3 et D-4). L’appelant fournit l’ID de compte et le credential ; ce dernier doit seulement pouvoir être lu comme `AttestedCredentialData`.
- **H1 reste ouverte.** L’ID fourni représente l’ID REST que lirait le futur flux de la GitHub App avec `GET /user`. Son équivalence avec le claim `actor_id` OIDC n’est pas établie. Aucun jeton OIDC réel n’est autorisé.
- **Activation à concevoir.** La confirmation par le propriétaire, la représentation de la preuve de compte GitHub distincte de `ADMIN_ATTESTED` dans le registre (la table v3 `github_accounts` n’accepte que cette valeur) et la trace de confirmation restent à concevoir avec la frontière SSH authentifiée.
- **Hors périmètre.** Une inscription porte un seul credential ; le second authentificateur, destiné au secours (D-3), relève d’une cérémonie séparée qui n’est pas conçue ici. Le module n’ajoute ni OAuth, ni callback public (D-12), ni authentification SSH, ni compte réel, ni jeton, ni secret, ni Provider.

**Validation locale (24 octobre 2026).** `tests/test_g2_approval_store_v5.py` contient 27 tests synthétiques. Ils utilisent des bases temporaires, des ID de compte fictifs et des credentials construits à partir de clés EC générées localement. Ils vérifient :

- un schéma 5 créé seulement dans un nouveau fichier ; les fichiers v3, v4, v5 ou vides existants restent identiques octet pour octet, et les trois versions se refusent mutuellement ;
- la consommation vers l’état `PENDING`, sans aucune ligne de registre ou de credential, et le refus sans écriture d’un ID de compte différent ou d’un credential mal formé, déjà inscrit ou déjà en attente ;
- un retour arrière complet si l’écriture de l’inscription échoue après le passage de l’invitation à `CONSUMED` ;
- l’absence de toute primitive ou de tout état de confirmation, et l’absence de toute ligne `github_accounts`, `ADMIN_ATTESTED` ou non, après consommation, rejet, révocation et expiration ;
- le caractère définitif du rejet et le refus des transitions répétées ou invalides ;
- le refus, par SQL direct, de confirmer, de réétiqueter le contrôle en `ADMIN_ATTESTED` ou en preuve GitHub, de réécrire ou de supprimer une inscription ;
- l’absence d’expiration d’une inscription en attente ;
- la concurrence entre six fils d’exécution sur la consommation d’une même invitation.

Huit mutations temporaires, appliquées à une copie hors du dépôt, ont toutes été détectées : activation dès la consommation, comparaison de l’ID supprimée, contrôle réétiqueté en preuve GitHub, état `CONFIRMED` admis, expiration des inscriptions en attente, déclencheur de création neutralisé, primitive de confirmation rétablie avec une ligne `ADMIN_ATTESTED`, et échec d’écriture ignoré après le passage à `CONSUMED`.

Résultats sous Windows, Python 3.14.5, avec les dépendances verrouillées installées dans un dossier temporaire hors du dépôt :

- tests ciblés : 27 tests OK ;
- tests G2 : 224 tests OK (2 ignorés) ;
- suite complète : 3216 tests OK (2 ignorés) ;
- audit d’architecture : `NO_DRIFT`.

Le job `posix-approval-store` lance aussi la suite v5 sous Ubuntu. Le comportement Linux de cette version corrigée ne sera confirmé qu’après le prochain passage de ce job. D-5 reste non résolu ; Provider = CLOSED et NO-GO restent en vigueur.

## Limites

Ce brouillon n’affirme pas que D-5 est satisfait. Il n’autorise aucune inscription réelle ni l’utilisation du compte, du jeton OIDC ou des authentificateurs de B.
