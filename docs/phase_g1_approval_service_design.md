# Phase G1 — Conception du service d'approbation humaine

- **Date :** 2026-10-08
- **Référence :** `main` à `f687973568d787e2b2e0051a4632cbbe962de94b` (fusion de la PR #6, Phase F)
- **Statut :** document de conception, corrigé après des revues de sécurité en lecture seule. D-1 reprend une instruction explicite du propriétaire ; D-2 à D-18 sont choisies ou explicitement reportées sous sa délégation des 2026-10-07 au 2026-10-09. D-14 demeure reportée sans montant ; les preuves opérationnelles, coûts réels et vérifications d'accès restent ouverts. Ce document n'implémente rien, n'autorise rien et ne déploie rien.

**NO-GO en vigueur. Provider = CLOSED.** La décision de [`phase_a_real_generation_decision.md`](phase_a_real_generation_decision.md) est inchangée. Ce document prolonge la conception de l'identité ([`phase_c_authorizer_identity_design.md`](phase_c_authorizer_identity_design.md)), celle des limites de l'autorisation, du plafond, de la révocation et de l'arrêt ([`phase_e_authorization_limits_ceiling_revocation_shutdown_design.md`](phase_e_authorization_limits_ceiling_revocation_shutdown_design.md)) et le chemin de production fermé ([`phase_f_production_path_design.md`](phase_f_production_path_design.md)). Il ne résout aucune des sept conditions de la Phase A. Aucun des quatre verrous d'exécution ni des verrous F-1 à F-4 n'est modifié.

Pendant la phase initiale de conception : aucun code, workflow, test, verrou, paramètre serveur, réglage GitHub ou enregistrement DNS n'a été modifié ; aucun secret ni aucune clé n'a été créé ou lu par Codex ; aucun logiciel n'a été installé ; aucun port n'a été ouvert ; rien n'a été déployé. Codex n'a lancé aucun appel API Higgsfield ni aucun workflow de génération. Les commandes locales exécutées ultérieurement par le propriétaire sont rapportées dans les compléments datés ci-dessous. Les contrôles GitHub Actions déclenchés automatiquement par les pull requests documentaires ont été exécutés et ont réussi.

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
| **Vérifié dans le dépôt** | La Phase F a été fusionnée dans `main` au commit historique `f687973` | Historique Git |
| **Vérifié dans le dépôt** | Aucun code de **serveur** HTTP, ni OIDC, ni WebAuthn, ni base de données. Le seul code HTTP est le transport **client** fermé de la Phase F (`integrations/higgsfield/https_transport.py`, `import http.client`), câblé à rien | Recherche dans le code |
| **Vérifié dans le dépôt** | Bibliothèque standard uniquement ; `cryptography`, `jwt` et `nacl` ne sont pas déclarés | README, Phase C §1 |
| **Vérifié dans le dépôt** | Seule plateforme validée : CPython 3.14 sous Windows | `.python-version`, `tests/test_p3_106_python_version.py`, README |
| **Décision de conception conditionnelle sous délégation explicite** | D-16 : prendre CPython 3.14.4, version déclarée sur le serveur Ubuntu 26.04.1, comme cible Linux de G2 sans mise à niveau du serveur ; conserver la CI Windows CPython 3.14.5 et ajouter une validation Linux sous 3.14.4 avant toute mise en service. La version serveur vient d'une sortie communiquée par le propriétaire et n'a pas été vérifiée indépendamment. Si les dépendances verrouillées ne prennent pas en charge 3.14.4, réexaminer D-16 avant G2 | Sortie SSH rapportée le 2026-10-08 ; `.python-version`, CI |
| **Vérifié dans le dépôt** | Le workflow de Phase F s'exécute sur `windows-2025`, sans `id-token: write` et sans référence à un secret | `.github/workflows/higgsfield-production.yml` |
| **Déclaré par le propriétaire, non vérifié par cette phase** | CI de la PR #6 verte : tests unitaires et audit `NO_DRIFT` | Instruction du propriétaire |
| **Déclaré par le propriétaire, non vérifié par cette phase** | Configuration actuelle du serveur | Section 6 |
| **Décision prise par le propriétaire** | D-1 : option E-2 (courtier) ; toute clé API dédiée à ce chemin serait détenue uniquement par le serveur, qui conserve l'état durable anti-rejeu sur son volume persistant. Choix de conception seulement : rien n'est implémenté et aucune clé n'a été créée | Instruction explicite du propriétaire, 2026-10-07 |
| **Décision de conception conditionnelle sous délégation explicite** | D-6 : SQLite retenu comme cible de conception pour G2, sous réserve des preuves de durabilité et de restauration ; aucune base n'est créée ni déployée | Section 3, décision D-6 |
| **Décision de conception conditionnelle sous délégation explicite** | D-7 : sauvegarde chiffrée quotidienne hors serveur, rétention de 30 jours, restauration d'essai mensuelle et ancre externe append-only ; fournisseur et coût restent à vérifier | Section 3.4, décision D-7 |
| **Ouvert** | Validation de SQLite avant tout usage serveur ; fournisseur et compte des sauvegardes/ancre ; chiffrement et coût TTC ; versions exactes et empreintes des dépendances, examen des avis de sécurité et procédure de mise à jour | Sections 3.3, 3.4, 8 et 10 ; décisions D-6, D-7, D-13 et D-15 |
| **Décision prise sous délégation explicite du propriétaire** | D-2 : WebAuthn est le seul facteur normal d'approbation ; la vérification locale de l'utilisateur est obligatoire ; l'inscription est réservée à une invitation à usage unique créée par SSH d'administration | Section 4.4, décision D-2 |
| **Décision prise sous délégation explicite du propriétaire** | D-3 : deux identifiants WebAuthn distincts sur deux authentificateurs séparés ; fermeture immédiate et révocation en cas de perte ; remplacement seulement par la procédure SSH d'administration | Section 4.4, décision D-3 |
| **Décision prise sous délégation explicite du propriétaire** | D-4 : passkeys de plateforme et clés de sécurité acceptées ; une passkey synchronisable peut servir d'identifiant courant, mais le secours doit être un identifiant distinct non synchronisable (`BE=0`) | Section 4.4, décision D-4 |
| **Décision prise sous délégation explicite du propriétaire** | D-5 : une approbation WebAuthn par une personne autorisée distincte de l'acteur GitHub qui a lancé le run ; aucun auto-approuveur et aucun quorum supplémentaire | Section 4.4, décision D-5 |
| **Décision prise sous délégation explicite du propriétaire** | D-8 : 10 minutes pour approuver depuis `requested_at`, validité de 300 secondes depuis `authorized_at`, et attente totale du job plafonnée à 15 minutes ; la première échéance atteinte bloque, sans prolongation ni réutilisation | Sections 4.5 et 10, décision D-8 |
| **Décision prise sous délégation explicite du propriétaire** | D-9 : interrupteur fermé par défaut ; fermeture d'urgence depuis SSH sans WebAuthn ; réouverture manuelle depuis SSH avec confirmation WebAuthn fraîche et journalisation ; révocations définitives | Sections 4.8 et 10, décision D-9 |
| **Décision prise sous délégation explicite du propriétaire** | D-10 : liste persistante de SHA complets autorisés explicitement par WebAuthn après fusion dans `main` ; tout SHA absent, différent ou révoqué est refusé | Sections 4.3 et 10, décision D-10 |
| **Décision prise sous délégation explicite du propriétaire** | D-11 : copie figée des seuls assets verrouillés de Video 005 ; le service recalcule le manifeste et montre le contenu réel à l'approbateur | Sections 4.3 et 10, décision D-11 |
| **Décision prise sous délégation explicite du propriétaire** | D-12 : Caddy en reverse proxy HTTPS ; ports publics 80/443, backend limité à localhost, SSH sur 22 ; interfaces WebAuthn et OIDC séparées ; aucune exposition avant autorisation distincte | Sections 7 et 10, décision D-12 |
| **Décision de conception conditionnelle sous délégation explicite** | D-13 : PyJWT avec l'extra cryptographique pour les JWT OIDC, et `python-fido2` pour la vérification WebAuthn côté serveur ; versions, empreintes du verrou, examen des licences/avis de sécurité et procédure de mise à jour à établir en G2 ; rien n'est installé | Section 10, décision D-13 |
| **Décision de conception conditionnelle sous délégation explicite** | D-18 : R-1, attestation asymétriquement signée par le service, liée à l'énoncé canonique et à l'état `CONSUMED` ; la Gate du Director vérifie la signature, l'audience, l'échéance, l'usage unique et la concordance exacte des identifiants et empreintes. Toute réponse absente, rejouée ou discordante échoue fermée. Aucune clé ni dépendance n'est créée ici | Sections 4.11 et 10, décision D-18 |
| **Décision de conception conditionnelle sous délégation explicite** | D-17 : un seul emplacement global d'exécution est disponible ; il reste occupé tant qu'une demande est active ou qu'une issue fournisseur n'est pas définitivement résolue. Tout nouvel essai, y compris après `NOT_SENT`, exige une nouvelle demande, une nouvelle approbation WebAuthn, un nouvel `approval_id` et une nouvelle clé d'idempotence | Sections 4.6–4.7 et 10, décision D-17 |
| **Décision de report sous délégation explicite** | D-14 : aucun plafond numérique par requête ou période n'est fixé ; plafond vide et coût `UNKNOWN` bloquent toute demande. La condition 3 de la Phase A reste non satisfaite et le NO-GO demeure | Section 10, décision D-14 |
| **Décision de conception conditionnelle sous délégation explicite** | D-15 : MFA résistante à l'hameçonnage lorsque disponible, récupération préparée, accès au moindre privilège, protections GitHub vérifiables, domaine protégé et inventaire des accès Higgsfield ; réglages réels non vérifiés et inchangés | Section 4.12 et décision D-15 |
| **Ouvert** | Preuves de l'état réel des comptes, moyens de récupération, règles de `main`, verrou et alertes DNS, IAM Scaleway, inventaire et révocation des accès Higgsfield ; aucune capture ne doit exposer un secret | Section 11, étape 3, et décision D-15 |
| **Ouvert** | Coût mensuel total réel, TTC | Section 8 |

## 2. Contradictions et contraintes héritées

| Constat | Conséquence pour G |
|---|---|
| La Phase F constate que les runners GitHub sont éphémères et que son journal, écrit dans `RUNNER_TEMP`, disparaît : aucun anti-rejeu entre exécutions | Selon D-1, le serveur et son volume persistant sont l'emplacement retenu en conception pour l'état durable. SQLite est la cible conditionnelle de D-6 ; D-7 fixe une politique de sauvegarde, dont le fournisseur reste à choisir |
| `approval_id` vaut `gh-<run_id>` et n'est vérifié par rien (Phase F §5) | L'identifiant d'approbation doit être choisi par le service, jamais par le run (exigence L5 de la Phase C) |
| L'approbation d'un environnement GitHub porte sur un déploiement, pas sur l'empreinte du manifeste (Phase F §5) | L'assertion WebAuthn doit porter cryptographiquement sur l'énoncé qui contient `manifest_sha256` |
| Le dépôt n'utilise que la bibliothèque standard | Elle ne fournit aucune API de vérification de signature RS256 (jeton OIDC) ou ECDSA/Ed25519 (WebAuthn). D-13 choisit des bibliothèques tierces pour G2. Une implémentation cryptographique maison est écartée |
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

Les sorties de commandes en lecture seule, communiquées par le propriétaire le 2026-10-08, indiquent Python 3.14.4, SQLite 3.46.1 et `/dev/sdb` monté en ext4 avec `rw,relatime,stripe=1024`. `findmnt` n'affiche pas l'option `nobarrier`. Ces sorties ne démontrent ni la durabilité après coupure, ni la restauration, ni le comportement du stockage côté hôte.

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

### 3.3 Choix de conception conditionnel (D-6)

Sous la délégation explicite du propriétaire, **S-1 (SQLite) est retenu comme cible de conception pour G2**, car le service vise un seul serveur et un faible volume d'écritures ; Python fournit déjà le module `sqlite3`, sans serveur de base séparé, dépendance tierce ni abonnement supplémentaire. Ce choix ne vaut pas autorisation de créer une base, d'installer un logiciel, de déployer du code ou d'utiliser le service. Il ne devient définitif pour un usage serveur qu'après réussite et consignation des preuves ci-dessous. Si ces preuves échouent, D-6 devra être réexaminée avant toute suite.

- **Configuration SQLite à démontrer avant tout usage** : `journal_mode=WAL` ; `synchronous=FULL` posé à chaque connexion puis **relu**, avec refus de servir si la valeur relue diffère ; `foreign_keys=ON` ; `busy_timeout` borné ; transactions explicites (attribut `autocommit` du module `sqlite3`, disponible depuis Python 3.12) ; fichier sous `/srv/ai-director-data` appartenant à `aidirector` et illisible par les autres comptes.
- **Si** plusieurs processus écrivains indépendants ou une évolution vers plusieurs machines sont prévus, **alors S-2** est plus adapté, au prix d'une dépendance tierce et d'une maintenance accrue.
- **S-3** n'est envisageable que si son coût réel TTC, ajouté aux autres postes, reste dans l'objectif de 50 € par mois, preuve à l'appui (section 8).
- **S-4** ne répond pas aux besoins transactionnels de la section 3.1.

**Preuves nécessaires avant toute décision définitive de mise en service :**

1. **Reçue en sortie de session SSH le 2026-10-08** : Python 3.14.4, SQLite 3.46.1 ; `/dev/sdb`, ext4, options `rw,relatime,stripe=1024` (aucun `nobarrier` affiché). Cette preuve vient de la sortie fournie par le propriétaire et n'a pas été vérifiée indépendamment.
2. Le volume ext4 est confirmé sans option désactivant les barrières d'écriture, et un arrêt brutal du processus puis du système invité ne perd aucune transaction confirmée (section 9, exigence X4). **Non démontré à ce stade.**
3. Sauvegarde puis restauration complètes, réalisées et consignées, y compris les scénarios de la section 3.4. **Non démontré à ce stade.**
4. Pour S-3 : devis ou tarif courant, montant TTC constaté, et mode de connexion (réseau privé ou point d'accès public avec TLS).

**Limite non démontrable par ces essais :** une réinitialisation brutale de la machine virtuelle prouve la tenue après un crash du système invité. Elle ne prouve pas la tenue du stockage de l'hébergeur en cas de défaillance côté hôte (cache, alimentation, réplication). Cette durabilité reste une **hypothèse de confiance** envers Scaleway et ses engagements de service, à consigner comme telle.

### 3.4 Restauration et rejeu

Restaurer une sauvegarde prise à l'instant T **fait réapparaître comme non consommés** les nonces et approbations consommés après T. C'est la limite A2-e de la Phase E, appliquée à la base.

**Les risques ne sont pas tous les mêmes :**

- une approbation `APPROVED` ressuscitée est déjà bornée par son expiration (au plus 300 s après la signature, section 4.5), tant que l'horloge du serveur ne recule pas (limite A2-g) ;
- le risque principal est la **perte d'un état `IN_FLIGHT`** ou `AMBIGUOUS` postérieur à T. Le service croirait qu'aucun envoi n'a eu lieu, et une nouvelle approbation du même manifeste pourrait conduire à une **double soumission**, donc à une double dépense, le jour où un Provider serait ouvert. Le rapprochement par lecture seule de l'historique du fournisseur n'est pas démontré : l'endpoint de statut REST et ses valeurs ne sont pas confirmés (Phase F §5).

**Décision de conception conditionnelle D-7, sous délégation du propriétaire (2026-10-08) :**

- **Sauvegardes** : une sauvegarde SQLite cohérente par jour, chiffrée avant de quitter le serveur, vers un stockage hors serveur et dans un compte et domaine de panne distincts. Conserver les 30 dernières sauvegardes quotidiennes. La clé privée de déchiffrement reste hors du serveur, sous contrôle de l'administrateur ; le serveur ne reçoit au plus que le matériel public nécessaire au chiffrement. La méthode et le fournisseur ne sont pas choisis (D-7, D-15), aucun coût n'est engagé, et le total récurrent TTC doit d'abord être vérifié par rapport à l'objectif budgétaire (section 8) ;
- **Test de restauration** : un exercice mensuel dans un environnement isolé, sans réseau fournisseur et avec l'interrupteur fermé. Vérifier `integrity_check`, le traitement WAL, le journal et le comportement anti-rejeu. Ce test n'est pas encore réalisé ;
- **Témoin local** : l'époque de restauration et la dernière tête connue sont conservées dans un fichier distinct de la base, exclu des sauvegardes. Il aide à détecter une restauration partielle, mais ne constitue pas la source d'autorité ;
- **Ancre externe J-c** : enregistrer hors serveur, en ajout seul et dans un compte et domaine de panne distincts, le numéro séquentiel et l'empreinte de chaque nouvelle tête du journal, sans donnée métier, secret ou jeton. Le compte de service peut ajouter, pas remplacer ni supprimer les entrées. Au démarrage et avant de délivrer une autorisation, la base, le témoin local et l'ancre doivent concorder. Si l'ancre est indisponible, absente ou divergente, le service reste fermé ; aucun résultat n'est confirmé avant vérification de l'ancre ;
- **Restauration** : toute restauration maintient l'interrupteur fermé jusqu'à vérification de l'ancre et rapprochement de l'état. Si une entrée `IN_FLIGHT` ou `AMBIGUOUS` a pu être perdue, aucune reprise n'est permise sans rapprochement fiable ; faute de preuve, le service reste fermé. Les modalités de réouverture relèvent de D-9.

Avec cette conception, une restauration ancienne ou non annoncée doit diverger de l'ancre externe et provoquer un refus fermé. La résistance réelle de l'ancre dépendra toutefois du fournisseur, des droits et de l'immutabilité retenus ; ils restent à vérifier avant implémentation ou achat. Sans ancre opérationnelle, ces cas demeurent **non détectés** et le service ne peut pas être mis en service.

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

- la signature, avec les clés publiées par l'émetteur `https://token.actions.githubusercontent.com`, en n'acceptant que `RS256` ; `alg=none`, un algorithme symétrique ou un `kid` inconnu sont refusés ;
- `iss`, `aud` (l'audience propre à l'interface appelée), `exp`, `iat` et `nbf`, avec une tolérance d'horloge bornée ;
- `repository_id` et `repository_owner_id` : identifiants numériques, stables même en cas de renommage, préférés aux noms ;
- `ref` = `refs/heads/main`, `event_name` = `workflow_dispatch` ;
- `workflow_ref` et `job_workflow_ref` : chemin exact du workflow sur `refs/heads/main` ;
- `runner_environment` = `github-hosted`, pour refuser un runner auto-hébergé ;
- `sha` : présent dans la liste des commits autorisés (section 4.3) ;
- `environment` : environnement protégé attendu, si le propriétaire l'impose ;
- `run_id` et `run_attempt` (refus de toute valeur différente de 1, cohérent avec le script de Phase F) ;
- l'unicité du jeton, si un identifiant de jeton (`jti`) est présent.

**Bibliothèque D-13 :** PyJWT avec l'extra `[crypto]` est retenu pour vérifier la signature JWT et exploiter les clés JWKS. Ce n'est pas un client OIDC complet : l'application reste responsable de l'émetteur, de l'audience propre à chaque interface, des claims requis et de toutes les règles ci-dessus. L'algorithme accepté est explicitement `RS256`, transmis comme liste d'autorisation au vérificateur ; il n'est jamais déduit de l'en-tête du jeton. La récupération JWKS reste limitée à l'URL GitHub fixée par la conception, et toute clé inconnue, récupération impossible ou erreur de validation bloque la demande. Référence : [documentation PyJWT](https://pyjwt.readthedocs.io/en/stable/).

**Ces claims ne sont pas tenus pour confirmés.** Leur présence, leurs noms et leurs formats sont à vérifier sur la documentation de GitHub et sur un jeton réel de test. Un tel essai exige une **autorisation explicite et distincte du propriétaire** (section 11, étape 3).

**Vol de jeton.** Le jeton est porteur. Un jeton du job `request` présenté à l'interface de consommation est refusé par l'audience. Un jeton de consommation volé pendant sa validité permettrait de consommer l'approbation avant le job légitime :
- en E-1, c'est un refus de service, l'échec restant fermé ;
- en E-2, cela déclencherait la soumission du manifeste approuvé.

D'où l'exigence de journaux sans jeton et d'actions épinglées.

### 4.3 Commits autorisés et contenu montré à l'approbateur

**Décision D-10, sous délégation explicite du propriétaire : option (ii), liste explicite de commits.** Le service n'accepte qu'un SHA complet (40 caractères hexadécimaux) inscrit individuellement dans une liste persistante par une action humaine authentifiée par WebAuthn. L'inscription n'est permise qu'après la fusion du commit dans `main` et la réussite de ses contrôles CI ; l'action d'inscription lie le SHA exact à l'identité de l'approbateur et est journalisée. Le SHA présenté par le jeton OIDC du run doit être identique caractère pour caractère à une entrée active de cette liste. Un SHA abrégé, inconnu, différent ou révoqué, un nom de branche ou une étiquette ne constitue jamais une autorisation. Une révocation est définitive conformément à D-9 ; une nouvelle version nécessite une nouvelle inscription WebAuthn après fusion et contrôles.

La liste explicite lie l'autorisation à une action humaine et à un commit immuable. La condition de fusion dans `main` et de CI verte doit être vérifiée avant l'inscription ; la protection effective de `main` et la preuve de cette vérification restent liées aux décisions de sécurité GitHub de D-15. Cette décision ne choisit ni n'implémente le mécanisme de vérification GitHub du service.

**Décision D-11, sous délégation explicite du propriétaire : option (b).** Le service garde une copie figée des seuls fichiers de la Release Candidate Video 005 (prompt, avatar et référence visage), liée aux empreintes verrouillées de cette version, et recalcule lui-même le manifeste. Il n'accepte aucun asset arbitraire téléversé par un run. Avant toute approbation, il vérifie que le manifeste canonique transmis correspond exactement à celui recalculé depuis le jeu d'assets verrouillé ; un asset manquant, supplémentaire ou modifié, ou toute divergence de paramètres ou d'empreintes, bloque la demande. La page d'approbation présente le contenu réel et les paramètres, pas seulement les empreintes.

Cette décision de conception évite de demander à l'approbateur de consentir à des empreintes seules, mais elle entraîne le stockage de contenu sensible sur le serveur. Avant toute mise en service, l'accès doit être limité à `aidirector`, les fichiers exclus des journaux, protégés au repos et couverts par une politique de sauvegarde, de rétention et de suppression cohérente avec D-7 et D-15. Les détails de chiffrement et de cycle de vie restent à vérifier ; aucun asset n'est copié sur le serveur par cette décision.

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

**Bibliothèque D-13 :** `python-fido2` (`fido2.server.Fido2Server`) est retenue pour les opérations de vérification WebAuthn côté Relying Party. Elle n'est pas considérée comme suffisante à elle seule : l'application doit encore imposer explicitement les décisions D-2 à D-5 et les contrôles du défi, de l'origine, du RP ID, de UP/UV, de BE/BS, de la révocation et de la consommation unique. Le service ne communique pas directement avec un authentificateur USB/NFC ; l'extra optionnel `pcsc` n'est donc pas retenu. Le projet indique prendre en charge Python 3.10+ et dépendre de `cryptography` ; la compatibilité effective avec les versions retenues reste à valider en G2. Référence : [documentation officielle Yubico python-fido2](https://developers.yubico.com/python-fido2/).

### 4.5 Énoncé canonique et fenêtre de validité

Il prolonge l'exigence L1 de la Phase C. Il est sérialisé en JSON à clés triées, UTF-8, empreintes en hexadécimal minuscule, et versionné. Contenu minimal :

- version de l'énoncé, identifiant de la Relying Party, `approver_id` pseudonyme relié à un identifiant WebAuthn actif et `auth_method=webauthn` ;
- `repository_id`, `repository`, `sha`, `workflow_ref`, `run_id`, `run_attempt` (issus du jeton vérifié) ;
- `manifest_sha256` et les champs vidéo liés : empreintes du prompt, de l'avatar et de la référence visage, `job_type`, `duration`, `resolution` et `aspect_ratio`, issus du manifeste recalculé ;
- `request_id`, `authorization_id`, `approval_id` et nonce, tous choisis par le service et distincts. `approval_id` doit respecter le format accepté par le script de Phase F (`[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`) ;
- `requested_at` (création de la demande) et `approval_deadline` (= `requested_at` + 600 secondes), qui bornent l'attente humaine ;
- pour l'énoncé d'autorisation signé par WebAuthn : `issued_at` et `expires_at` (écart maximal de 300 secondes, D-8), calculés avant le défi. `authorized_at` est horodaté par le service lorsqu'il vérifie l'assertion ; la consommation est refusée dès la première échéance entre `expires_at` et `authorized_at` + 300 secondes. L'énoncé complet est créé et affiché au début de l'approbation, puis signé ; il ne peut être réutilisé après échéance ;
- plafond de crédits par requête : **aucun montant n'est fixé ici**. Tant que le propriétaire n'en a pas fixé, ce champ est vide et toute demande est refusée (condition 3).

**Délais retenus (D-8).** `approval_deadline` est fixé à `requested_at` + 600 secondes. Une assertion reçue à l'échéance ou après (`now >= approval_deadline`) est refusée ; elle ne peut ni prolonger ni renouveler la demande. `authorized_at` est l'instant où le service vérifie l'assertion WebAuthn. L'autorisation expire à `authorized_at` + 300 secondes, et toute consommation à l'échéance ou après est refusée, conformément à la condition 2 et au contrôle existant de la Gate (`MAX_AUTHORIZATION_AGE_SECONDS = 300.0`, `_authorization_freshness_reasons()` dans `agents/generation_approval_gate.py`). Le job GitHub ne peut attendre plus de 15 minutes au total à partir de son démarrage ; aucune reconnexion, interrogation répétée ou relance ne remet ce délai à zéro. La première échéance atteinte — échéance d'approbation, expiration de l'autorisation ou plafond total du job — provoque un refus fermé. Il faut alors une nouvelle demande et une nouvelle assertion WebAuthn.

**Relation avec la limite A2-b.** Le manifeste contient les paramètres vidéo, mais cela ne couvre A2-b qu'au niveau du service. A2-b porte sur `RealGenerationAuthorization` et sur le Provider, qui ne reçoit pas l'autorisation. Elle ne serait couverte dans le Director que si la Gate et le Provider vérifiaient l'empreinte de l'énoncé (exigences L2 et L7 de la Phase C). Ce point est à concevoir (section 4.11).

L'énoncé affiché à l'humain doit être exactement celui dont l'empreinte entre dans le défi.

### 4.6 Nonce, usage unique, clé d'idempotence et réapprobation

- Nonce de 256 bits tiré par le service (`secrets`), unique en base.
- La consommation est **une seule transaction** : transition `APPROVED` → `CONSUMED` conditionnelle, enregistrement du couple (`run_id`, `run_attempt`), entrée de journal, lecture de l'interrupteur global. Zéro ligne modifiée signifie un refus.
- Une demande consommée, expirée, refusée ou révoquée n'est jamais rétablie.
- La clé d'idempotence de la Phase F (`derive_idempotency_key(manifest_sha256, approval_id)`, `integrations/higgsfield/manifest.py`) recevrait l'`approval_id` choisi par le service, et non plus `gh-<run_id>`.
- **Décision de conception conditionnelle D-17, sous délégation explicite du propriétaire (2026-10-09).** Un seul emplacement global d'exécution est disponible : il reste occupé tant qu'une approbation est active ou qu'une issue fournisseur n'est pas définitivement résolue, tous manifestes confondus. Cela sérialise le chemin à faible volume et évite les courses entre demandes et jobs. Un même manifeste pourra faire l'objet d'une nouvelle génération uniquement après résolution définitive de toute issue fournisseur antérieure et avec une nouvelle demande, une nouvelle assertion WebAuthn, un nouvel `approval_id` et une nouvelle clé d'idempotence ; l'approbation ou la clé précédentes ne sont jamais réutilisées. Un résultat `ACCEPTED` ne libère pas l'emplacement : le job fournisseur doit être déclaré terminé ou rapproché par une preuve faisant autorité et consignée. L'état de suivi du job reste à concevoir avant toute ouverture du Provider ; `ACCEPTED` ne doit jamais être assimilé à une génération terminée. `AMBIGUOUS` bloque les demandes suivantes jusqu'au rapprochement humain. L'endpoint de statut de la Phase F n'étant pas confirmé, aucune consultation automatique n'est présumée possible.
- **`NOT_SENT`.** Malgré la reprise éventuellement permise par la Phase F §4, cette conception impose une nouvelle demande et une nouvelle approbation WebAuthn pour tout nouvel essai. L'approbation consommée reste terminale ; aucun `run_id`, `approval_id` ou clé d'idempotence n'est réutilisé. La nouvelle tentative n'est possible qu'après clôture de la demande précédente et respecte toujours la règle d'un seul emplacement global d'exécution.

### 4.7 États

| État | Signification | Transitions permises |
|---|---|---|
| `PENDING` | Demande reçue d'un run vérifié | `APPROVED`, `DENIED`, `EXPIRED`, `REVOKED` |
| `APPROVED` | Assertion WebAuthn valide sur l'énoncé | `CONSUMED`, `EXPIRED`, `REVOKED` |
| `DENIED` | Refus explicite de l'humain | Terminal |
| `EXPIRED` | Échéance dépassée (`approval_deadline`, fenêtre de validité ou plafond du job) | Terminal ; aucune prolongation, une nouvelle demande est requise |
| `REVOKED` | Révocation humaine authentifiée | Terminal |
| `CONSUMED` | Délivrée une fois au run | **Terminal tant que Provider = CLOSED.** `IN_FLIGHT` ne deviendrait possible qu'après une décision distincte de réouverture |
| `IN_FLIGHT` | Envoi au fournisseur commencé (inatteignable aujourd'hui) | `ACCEPTED`, `REFUSED`, `NOT_SENT`, `AMBIGUOUS` |
| `ACCEPTED` | Classification `ACCEPTED` de la Phase F §4 (identifiant de requête reçu) | Terminal pour l'approbation ; le suivi du job relève d'une conception ultérieure |
| `REFUSED` | Classifications `REJECTED`, `AUTH_FAILED` ou `INSUFFICIENT_CREDITS` de la Phase F §4 | Terminal ; toute nouvelle tentative exige une nouvelle approbation |
| `NOT_SENT` | Classification `NOT_SENT` de la Phase F §4 (connexion jamais établie) | Terminal ; tout nouvel essai exige une nouvelle demande et une nouvelle approbation WebAuthn (D-17) |
| `AMBIGUOUS` | Issue inconnue (classification `AMBIGUOUS` ou `UNKNOWN` de la Phase F) | Uniquement par rapprochement humain consigné. **Bloque toute nouvelle demande** tant qu'il n'est pas résolu, comme `EXECUTION_STATE_UNKNOWN` |

La Phase F permet une reprise de `NOT_SENT` sous certaines conditions ; D-17 choisit une politique plus stricte pour le futur service : une nouvelle demande et une nouvelle approbation WebAuthn sont toujours requises.

### 4.8 Révocation et interrupteur global

**Décision D-9, sous délégation explicite du propriétaire.** Cette politique est un choix de conception uniquement ; aucun interrupteur, mécanisme de révocation ou accès serveur n'est configuré par cette décision.

- **Interrupteur global** (options S-b et R-d de la Phase E) : **fermé par défaut**. Interrupteur absent, illisible ou corrompu, état de stockage incertain, restauration non rapprochée, journal rompu ou ancre externe indisponible signifie fermé. Il est vérifié dans la même transaction que la consommation ; état inconnu = refus.
- **Fermeture d'urgence** : un administrateur authentifié par SSH peut fermer l'interrupteur sans WebAuthn, sans accès web et sans dépendre de GitHub. La fermeture est prioritaire, persistante et inscrite au journal dans la même transaction ; si l'écriture ou sa confirmation échoue, le service reste indisponible et fermé par défaut. Les conditions de récupération de l'accès SSH restent à vérifier (section 6).
- **Réouverture** : uniquement par une action manuelle depuis SSH d'administration, accompagnée d'une assertion WebAuthn fraîche avec vérification locale obligatoire, par un approbateur autorisé distinct de l'acteur GitHub du run concerné. L'action indique un motif, est journalisée atomiquement et n'est acceptée que si l'état de la base, du journal, du témoin et de l'ancre externe a été rapproché. Aucun redémarrage, restauration ou expiration ne rouvre l'interrupteur automatiquement. Si une condition n'est pas démontrée, il reste fermé.
- **Révocations** : une demande ou approbation, un identifiant WebAuthn ou un commit autorisé révoqué ne peut pas être réactivé ni annulé. Toute reprise exige une nouvelle demande et une nouvelle approbation ; le remplacement d'un identifiant révoqué passe par une nouvelle invitation à usage unique créée par SSH, conformément à D-2 et D-3. Toute révocation est persistante et journalisée atomiquement.
- **Portée de l'arrêt** : en E-1, une autorisation déjà délivrée au run reste utilisable jusqu'à son expiration (300 s au plus), sauf nouvelle vérification auprès du service juste avant l'envoi (à concevoir, section 4.11). En E-2, la fermeture bloque toute soumission non commencée. Cette limite doit être prise en compte avant tout choix E-1/E-2 définitif.
- L'interrupteur ne remplace aucun verrou : les quatre verrous de la Phase A et F-1 à F-4 restent fermés dans le code. Sa réouverture ne constitue jamais une ouverture du Provider et ne modifie pas le NO-GO.

### 4.9 Journal

- Table chaînée par empreinte (option J-b), écrite **dans la même transaction** que chaque changement d'état. Un échec d'écriture du journal annule la transition.
- **L'ajout seul est une convention**, renforcée si possible par des déclencheurs qui refusent `UPDATE` et `DELETE`. Elle n'est pas inviolable pour qui peut écrire le fichier ou administrer la base.
- Un refus portant sur une demande authentifiée est journalisé au même titre qu'une approbation. Les requêtes **non authentifiées** (jeton invalide, assertion invalide) sont comptées ou agrégées de façon bornée, sans une entrée par requête, pour ne pas permettre de saturer le disque ou le journal.
- Aucun secret, jeton OIDC, assertion brute, clé ni URL de résultat : seulement des identifiants, des empreintes, des décisions et des dates (exigence L6).
- Ancre externe de la tête (J-c) : principe retenu conditionnellement par D-7. C'est la seule capable de détecter une réécriture complète ou une restauration non signalée ; son fournisseur, ses droits append-only et sa disponibilité restent à démontrer (section 3.4).
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

**Décision de conception conditionnelle D-18, sous délégation explicite du propriétaire (2026-10-09) : R-1 est retenue.** Le service remet une attestation asymétriquement signée ; le Director ne fait confiance qu'à une clé publique épinglée par configuration de confiance, jamais fournie dans la réponse. Le format canonique, l'algorithme fixe, la gestion/rotation/révocation des clés et la compatibilité des bibliothèques seront spécifiés et testés en G2. Aucune clé ou dépendance n'est créée ici.

L'attestation est un reçu de consommation, pas une preuve que le fournisseur a terminé un job ni une autorisation d'ouvrir le Provider. Elle lie au minimum la version du protocole, l'audience exacte du Director, un identifiant de reçu à usage unique, `request_id`, `authorization_id`, `approval_id`, `approver_id`, `run_id`, `run_attempt`, le SHA complet du commit autorisé, `manifest_sha256`, les champs vidéo L1, l'empreinte de l'énoncé canonique, `state=CONSUMED`, `issued_at`, `authorized_at` et `expires_at` (au plus 300 secondes après `issued_at` et sans dépasser la limite de validité calculée depuis `authorized_at`). La signature porte sur la sérialisation canonique entière. Le service vérifie que `issued_at <= authorized_at`, que `expires_at <= issued_at + 300 secondes` et que l'autorisation n'a pas expiré à la consommation. Il prépare la signature dans la transaction de consommation et ne remet le reçu qu'après validation de la transaction ; si la signature ou l'écriture échoue, la consommation est annulée. Si la transaction est validée mais que la réponse se perd, l'approbation reste consommée et ne peut être réutilisée.

La Gate du Director vérifie une liste d'algorithmes fixe et le `key_id` attendu, la signature avec une clé publique épinglée, l'audience, la fraîcheur, le statut, l'identifiant de reçu jamais consommé, puis l'égalité exacte de chaque identifiant et empreinte L1 avec la demande et le manifeste recalculé. Aucune valeur de clé ou d'algorithme déclarée par le reçu ne peut élargir la confiance. Réponse absente, mal formée, expirée, rejouée, signature invalide, clé inconnue/révoquée ou champ discordant : refus fermé, aucune approbation côté Gate, aucun envoi fournisseur par le run. L'approbation déjà consommée n'est pas restaurée ; un nouvel essai exige une nouvelle demande conformément à D-17.

Dans l'architecture E-2, le run ne détient aucun identifiant fournisseur. La signature du reçu ne remplace pas les vérifications côté courtier : avant toute soumission, le service doit lui-même lier la consommation, l'état global et le corps envoyé au même manifeste. Cette frontière reste à implémenter et à vérifier ; elle n'est pas couverte par le reçu seul.

| Option | Description | Compromis |
|---|---|---|
| **R-1. RETENUE : attestation signée par le service** (signature asymétrique) | Reçu canonique de consommation vérifié par la Gate avec une clé publique épinglée | Clé privée côté service, clé publique de confiance côté Director ; algorithme, stockage, rotation et dépendance à valider en G2. Aucune clé n'est créée par cette phase |
| **R-2. TLS seul — écartée** | Confiance dans la réponse reçue sur `https://zephyr-approval.fr` | Lie la réponse à la connexion mais ne donne pas de reçu vérifiable indépendant après coup ; confiance trop dépendante du DNS, de l'autorité de certification et du runner |
| **R-3. Secret partagé (HMAC) — écartée** | Le service et le Director partageraient une clé | Écartée par la limite 1 de la Phase C §3 : qui vérifie peut aussi signer |

**Couverture des exigences L1 à L8 de la Phase C par cette conception**

| Exigence | Couverture par G1 | Reste à faire |
|---|---|---|
| L1 — énoncé canonique | Section 4.5 | Validation du format en G2 |
| L2 — vérification à la Gate | D-18 définit R-1 et la concordance exacte avec la demande recalculée | À implémenter et tester en G2 ; réponse incorrecte ou non vérifiée ne peut approuver |
| L3 — contrats P2.21 et P2.26 | D-18 impose de lier le reçu aux identifiants, au statut et à l'empreinte de l'énoncé | Porter et vérifier ces champs dans les contrats, puis protéger leurs cardinalités en G2 |
| L4 — paramètres vidéo et coût | Partielle : paramètres dans le manifeste ; plafond vide, donc refus | Coût `UNKNOWN` toujours bloquant côté Gate (condition 4) ; plafond à décider (D-14) |
| L5 — usage unique, identifiant choisi par l'émetteur | Côté service (section 4.6) | Le registre local du Director reste limité à une machine (A2-d) |
| L6 — aucun secret persisté | Section 4.9 | En E-2 ou R-1, des secrets vivraient sur le serveur : hors du dépôt, de `state/` et des journaux, mais à protéger |
| L7 — frontière Provider | D-1/E-2 et D-18 exigent que le courtier lie la consommation et le corps de soumission au même `manifest_sha256` | Non implémentée : vérifier cette liaison dans le courtier avant tout envoi ; le reçu seul ne protège pas cette frontière |
| L8 — testabilité mock-only | Section 11, étape 4 | — |

### 4.12 Protection des comptes et des accès (D-15)

**Choix de conception conditionnel sous délégation (2026-10-08) :** protéger les comptes qui peuvent modifier le code, le DNS, le serveur ou le compte fournisseur par une authentification multifacteur résistante à l'hameçonnage lorsqu'elle est prise en charge ; garder des comptes nominatifs et des mots de passe uniques ; conserver les moyens de récupération séparément et hors du dépôt. Si un fournisseur ne permet pas le moyen préféré, la méthode disponible et son risque doivent être documentés avant tout usage. Deux personnes ou deux comptes contrôlés par la même personne ne satisfont pas à la séparation humaine de D-5. Si une personne distincte ne peut pas être authentifiée, toute demande reste bloquée.

- **Scaleway :** activer MFA pour le compte Owner et tout membre IAM ; préférer une passkey quand l'offre la rend disponible, conserver les codes de secours hors ligne et vérifier la procédure de récupération. N'accorder au futur service que des permissions IAM indispensables ; toute clé éventuelle doit être dédiée, limitée et révocable, sans être créée par cette phase. Une alerte de facturation est une notification de suivi, pas un plafond garanti ni un coupe-circuit. Références : [MFA Scaleway](https://www.scaleway.com/en/docs/account/login-credentials/use-2fa/), [IAM Scaleway](https://www.scaleway.com/en/docs/iam/) et [alertes de facturation](https://www.scaleway.com/en/docs/billing/how-to/use-billing-alerts/).
- **GitHub :** activer MFA et préparer les méthodes de récupération ; protéger `main` par PR et réussite du contrôle CI qui comprend les tests unitaires et l'audit `NO_DRIFT`, bloquer force-push et suppression, et désactiver le contournement administrateur lorsque le réglage du dépôt le permet. Ne pas exiger ici un nombre de revues qui empêcherait le propriétaire unique de poursuivre ; cette règle ne remplace jamais l'approbateur humain distinct prévu en D-5. Garder les permissions des workflows au minimum, épingler les Actions à des SHA complets revus, et ne placer aucune clé Higgsfield dans GitHub puisque D-1 retient le courtier E-2. État réel des règles et du plan GitHub à vérifier ; rien n'est changé ici. Références : [2FA et récupération GitHub](https://docs.github.com/en/authentication/securing-your-account-with-two-factor-authentication-2fa), [branches protégées](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches) et [sécurité des Actions](https://docs.github.com/en/code-security/tutorials/secure-your-organization/protect-against-threats).
- **Registrar et DNS :** activer MFA, verrouiller le domaine contre le transfert non autorisé, protéger les moyens de récupération et activer les notifications de connexion et de changement de serveurs DNS quand le fournisseur les offre. Le registrar et ses capacités ne sont pas vérifiés dans cette phase ; aucune donnée DNS n'est changée.
- **Higgsfield :** inventorier avant tout usage futur les sessions, identifiants de connexion, clés API, CLI authentifiés, intégrations et connecteurs autorisés qui peuvent soumettre une génération. Selon E-2, le service serait seul détenteur de l'identifiant dédié à ce chemin. Avant toute génération réelle, révoquer ou désactiver les autres accès capables de générer ; si un accès indépendant reste actif, le service ne peut garantir que les générations passent par son approbation et le NO-GO demeure. Aucun identifiant n'est lu, créé, tourné ou révoqué ici.
- **Compromission suspectée :** fermer l'interrupteur global conformément à D-9, révoquer les sessions, clés et tokens touchés, puis rétablir la confiance et rapprocher le journal avant toute réouverture. Aucun secret, code de récupération, token, QR ou valeur d'authentification ne doit être copié dans GitHub, le dépôt, les journaux, une capture partagée ou cette conversation.

**Limite de preuve :** cette politique est une décision de conception, pas un audit des comptes. MFA, récupération, permissions IAM, protections de branche, domaine, alertes et accès Higgsfield restent **non vérifiés**. La vérification et tout changement effectif exigent une étape distincte, une revue de leurs conséquences et une autorisation explicite du propriétaire ; aucun réglage de compte n'est modifié par la présente décision.

## 5. Ce que prouvent OIDC et WebAuthn

| | **OIDC GitHub** | **WebAuthn** |
|---|---|---|
| **Prouve** | GitHub a émis ce jeton, pendant sa courte validité, pour un job d'un dépôt, d'un workflow, d'une référence, d'un commit et d'un run donnés | Le détenteur d'un identifiant enregistré a signé ce défi précis, pour cette origine, avec présence et, si UV est exigé, vérification locale de l'utilisateur (biométrie ou code de l'appareil) |
| **Ne prouve pas** | Qu'un humain a consenti à l'énoncé. Le compte GitHub qui a lancé le run (claim `actor`, à confirmer) n'est pas une preuve de consentement. Que les étapes du job n'ont pas été modifiées au-delà de ce que contient le commit. Que le manifeste transmis a été calculé honnêtement | L'identité civile de la personne. Qu'elle a lu ou compris l'énoncé : l'authentificateur signe le défi, pas le texte affiché. D-11 exige que l'affichage corresponde au manifeste recalculé, mais WebAuthn ne prouve pas que l'humain a effectivement regardé le contenu |
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

## 7. Exposition web (D-12 décidée ; non effectuée)

**Décision D-12, sous délégation explicite du propriétaire.** Si une exposition est autorisée dans une étape ultérieure, Caddy sert de reverse proxy et termine TLS pour `zephyr-approval.fr`. Le service applicatif écoute seulement sur loopback ou socket Unix ; aucun port applicatif ou d'administration n'est directement exposé. La documentation officielle de Caddy décrit l'HTTPS automatique et demande une accessibilité publique sur 80/443 pour la configuration standard ([HTTPS quick-start](https://caddyserver.com/docs/quick-starts/https), [reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)).

- **Ports entrants prévus, conditionnels à une autorisation distincte avant tout changement serveur** : TCP 22 pour SSH d'administration ; TCP 80 pour le défi ACME et redirection vers HTTPS uniquement ; TCP 443 pour l'interface. Le port 80 ne sert aucune page ni donnée sensible. Aucun autre port entrant n'est autorisé. La politique SSH reste clé uniquement ; la restriction de son adresse source dépend de la vérification d'une adresse d'administration stable (D-15). Cette décision ne change aucune règle UFW existante.
- **Séparation des interfaces** : interface humaine sur `zephyr-approval.fr` ; API des jobs sur `api.zephyr-approval.fr`, avec audiences OIDC distinctes. L'API n'utilise ni ne reçoit de cookie de session WebAuthn. Le sous-domaine API n'est publié qu'après vérification DNS et du pare-feu IPv4/IPv6 ; aucun enregistrement AAAA n'est publié tant que le filtrage IPv6 n'est pas vérifié.
- **Limites applicatives** : limitation de débit bornée, tailles et délais de requête bornés, endpoints d'administration accessibles par SSH uniquement. La protection ne dépend pas d'un filtrage par IP des runners GitHub, dont les plages sont trop larges.
- **Sécurité de la page WebAuthn** : CSP stricte, aucune ressource ni aucun script tiers, protection CSRF, sessions courtes liées à la demande avec cookies `Secure`, `HttpOnly` et `SameSite`, échappement des données de l'énoncé ; HSTS uniquement après vérification complète de HTTPS. Le proxy administratif de Caddy reste accessible en local seulement.

**Limite de cette décision :** elle fixe une cible de conception, pas un déploiement. Aucun logiciel n'est installé, aucun port n'est ouvert, aucun DNS n'est modifié et aucune application n'est exposée par cette phase. Avant tout changement, il faudra une autorisation distincte, la vérification de la configuration DNS, du pare-feu et de TLS, puis une revue de sécurité de l'interface.

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

Le certificat TLS peut être gratuit (autorité ACME), selon l'option retenue. Selon D-15, une alerte de facturation Scaleway est prévue comme notification de suivi, pas comme plafond de dépense ; son état et ses seuils devront être vérifiés lors de l'étape 3 de la section 11. Elle n'est pas configurée par cette décision.

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

**Exigences X1 à X9**

- **X1. OIDC.** Refus pour chacun des cas suivants, y compris lorsque PyJWT reçoit une entrée mal formée ou une erreur de JWKS :
  - signature invalide ; `alg=none` ; confusion d'algorithme (algorithme symétrique utilisant la clé publique) ; `kid` inconnu ;
  - clés publiques de GitHub injoignables ; rotation des clés (nouvelle clé acceptée, clé retirée refusée) ;
  - `iss`, `aud` (dont l'audience de l'autre interface), `ref`, `repository_id`, `repository_owner_id`, `workflow_ref`, `job_workflow_ref`, `event_name` ou `runner_environment` erronés ;
  - `sha` non autorisé, abrégé, révoqué ou différent de l'entrée WebAuthn autorisée ; un nom de branche ou une étiquette fourni à la place du SHA est refusé ; `exp` dépassé ; `nbf` futur ; valeurs juste à l'intérieur et juste à l'extérieur de la tolérance d'horloge ;
  - `run_attempt` égal à 2 ; même jeton présenté deux fois ; jeton du job `request` présenté au job `execute`.
- **X2. WebAuthn.** Refus pour chacun des cas suivants, y compris les erreurs de vérification de `python-fido2` ; aucun défaut ou exception de la bibliothèque ne doit produire une approbation :
  - origine ou `rpIdHash` erronés ; `type` différent de `webauthn.get` ; `crossOrigin` vrai ;
  - UP ou UV à 0 ; identifiant révoqué ; régression du compteur, selon la politique retenue ;
  - assertion rejouée ; assertion de la demande A présentée pour la demande B ; défi expiré ;
  - drapeaux BE/BS non conformes à D-4.
  - **D-11** : asset attendu absent, asset supplémentaire ou modifié, paramètres divergents, ou manifeste du run différent du manifeste recalculé ; aucune approbation n'est délivrée et le contenu sensible n'est pas écrit dans les journaux. Vérifier que le contenu affiché correspond exactement au manifeste recalculé.
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
  - **annoncée** : sauvegarde, consommation, restauration ; l'approbation consommée n'est pas réutilisable, l'interrupteur est fermé, et toute divergence base/témoin/ancre bloque le service ;
  - **non annoncée**, y compris par restauration du volume entier : l'ancre externe indépendante doit détecter le recul et provoquer un refus fermé ; l'indisponibilité ou l'absence de l'ancre bloque aussi le service (section 3.4) ;
  - traitement des fichiers `-wal` et `-shm` vérifié.
- **X6. Refus fermé et D-9.** Refus pour chacun des cas suivants : interrupteur absent ou corrompu ; version de schéma inattendue ; chaîne de journal rompue ; échec d'écriture du journal (aucune transition, la transaction étant atomique) ; `synchronous` relu différent de `FULL` ; base absente, corrompue ou en lecture seule ; disque plein ; verrou tenu au-delà du délai. Vérifier aussi qu'une fermeture SSH rend immédiatement toute consommation impossible, qu'aucun redémarrage ou restauration ne rouvre l'interrupteur, qu'une réouverture sans assertion WebAuthn fraîche ou avec état/ancre non rapproché est refusée, et qu'aucune révocation ne peut être annulée.
- **X7. Horloge et échéances.** Le dernier instant observé est conservé. Tout recul de l'horloge est refusé, sans prolongation de fenêtre (A2-g). Tester les bornes `now < approval_deadline`/`now >= approval_deadline` et `now < authorized_at + 300 s`/`now >= authorized_at + 300 s` ; assertion tardive, consommation expirée et plafond total du job atteint doivent tous être refusés. Vérifier qu'aucune reconnexion, interrogation répétée ou relance ne réinitialise les délais. Si l'option est retenue, refus quand la synchronisation NTP n'est pas établie.
- **X8. Secrets et droits.**
  - des valeurs sentinelles (jeton, assertion, secret) sont injectées puis recherchées dans tous les journaux du service et du système : aucune occurrence ;
  - base, témoin et journal ne sont lisibles que par `aidirector` ;
  - **D-12** : backend non joignable directement depuis Internet ; HTTP ne sert que le défi ACME/la redirection sans donnée sensible ; UI et API ont des audiences OIDC distinctes et aucune session WebAuthn n'est transmise à l'API ; politique CSP, CSRF et cookies de session sont vérifiés ; aucune entrée DNS IPv6 avant contrôle du pare-feu IPv6.
- **X9. Attestation de service (D-18).** Avec des clés éphémères générées par les tests : un reçu valide, exact et non expiré est accepté une seule fois ; un second usage est refusé. Rejeter et journaliser, sans approbation Gate ni appel fournisseur, une signature invalide, un algorithme non autorisé, une clé inconnue/révoquée, une mauvaise audience, un statut différent de `CONSUMED`, un reçu expiré ou futur, une altération de chaque champ lié à L1 (identité pseudonyme/méthode, demande, autorisation, approbation, run, SHA, hashes vidéo, plafond, `manifest_sha256`, `issued_at`, `expires_at`, nonce et empreinte canonique), ou un reçu d'une autre demande. Simuler une erreur de signature ou d'écriture avant validation de la transaction : aucune consommation ne doit être validée et aucun reçu ne doit être remis. Une réponse perdue après commit laisse l'autorisation consommée et non réutilisable. Tester le roulement des clés avec la configuration publique épinglée ; aucune clé publique fournie par le reçu ne devient fiable.

## 10. Décisions qui restent au propriétaire

| # | Décision | Options principales |
|---|---|---|
| D-1 | **Décidée le 2026-10-07 — courtier E-2** | Toute clé API dédiée à ce chemin serait détenue uniquement par le service ; état anti-rejeu durable sur le serveur. Autres accès au compte hors périmètre. Choix de conception seulement, sans implémentation ni ouverture du Provider |
| D-2 | **Décidée par délégation le 2026-10-07 — WebAuthn avec vérification locale obligatoire** | WebAuthn est le seul facteur normal pour approuver une demande. L'option `userVerification=required` est demandée et le drapeau UV doit être vérifié pour chaque approbation ; aucun repli d'approbation par mot de passe de compte, courriel ou SMS. L'inscription reste fermée par défaut et requiert une invitation à usage unique créée depuis une session SSH d'administration. Le premier drapeau UV d'un nouvel identifiant n'autorise pas sa propre inscription. Choix de conception seulement ; la politique des types et des passkeys synchronisées est précisée par D-4 |
| D-3 | **Décidée par délégation le 2026-10-07 — deux identifiants séparés, récupération SSH** | Deux identifiants WebAuthn distincts liés à deux authentificateurs séparés sont requis avant toute activation ; l'un est conservé comme secours. Une perte entraîne fermeture immédiate, révocation et journalisation. Le remplacement exige une invitation à usage unique créée depuis SSH ; si tous les identifiants sont perdus, les anciens sont tous révoqués et l'interrupteur reste fermé jusqu'à une réouverture conforme à D-9. Aucun repli par courriel, SMS, code de récupération ou support tiers. La racine SSH et la confiance dans le serveur restent des hypothèses de D-15. Les types acceptés sont fixés en D-4 |
| D-4 | **Décidée par délégation le 2026-10-07 — plateforme et clé de sécurité, secours non synchronisable** | Passkeys de plateforme et clés de sécurité acceptées avec UV. Une passkey synchronisable (`BE=1`) peut être l'identifiant courant, pas l'identifiant de secours. Le secours doit être un identifiant distinct sur un authentificateur séparé avec `BE=0`, `BS=0`. `BE` est fixé à l'inscription et ne peut changer ; `BS=1` est refusé si `BE=0`, mais peut évoluer si `BE=1`. Aucune attestation AAGUID exigée ; le service fait confiance aux drapeaux signés et déclarés par l'authentificateur. Décision de conception seulement, sans inscription ni matériel acheté |
| D-5 | **Décidée par délégation le 2026-10-07 — un approbateur, séparation obligatoire** | Une seule approbation WebAuthn suffit, sans quorum supplémentaire. L'approbateur autorisé doit être distinct de l'acteur GitHub qui lance le run ; auto-approbation refusée. Si cette séparation ne peut pas être vérifiée, refus fermé. L'identification des comptes et la protection des comptes relèvent aussi de D-15. Choix de conception seulement, sans implémentation |
| D-6 | **Choix de conception conditionnel sous délégation le 2026-10-08 — S-1 SQLite** | SQLite est la cible de conception G2. Avant toute mise en service, réussir et consigner les preuves 2 et 3 de la section 3.3 ; si elles échouent, réexaminer S-2 ou S-3. Aucune base n'est créée ni déployée |
| D-7 | **Choix de conception conditionnel sous délégation le 2026-10-08 — sauvegardes et ancre J-c** | Sauvegarde quotidienne chiffrée hors serveur, 30 jours de rétention, exercice mensuel de restauration isolé, témoin local hors sauvegarde et ancre externe append-only par tête de journal ; en cas d'indisponibilité ou de divergence, refus fermé. Le fournisseur, le compte, la méthode de chiffrement et le coût restent ouverts (D-15, section 8). Aucune sauvegarde ni aucun ancrage n'est configuré |
| D-8 | **Décidée par délégation le 2026-10-08 — délais** | Approbation dans les 10 minutes suivant `requested_at` ; assertion refusée à `approval_deadline` ou après. Autorisation valable 300 secondes depuis `authorized_at`, consommation refusée à l'échéance ou après. Attente totale du job limitée à 15 minutes depuis son démarrage ; la première échéance atteinte bloque. Aucun délai n'est prolongé ou remis à zéro et aucune approbation expirée n'est réutilisable ; nouvelle demande et nouvelle assertion requises. Décision de conception uniquement, sans implémentation |
| D-9 | **Décidée par délégation le 2026-10-08 — interrupteur et révocation** | Fermé par défaut ; SSH d'administration suffit pour la fermeture d'urgence. Réouverture manuelle par SSH avec assertion WebAuthn fraîche, vérification locale et journalisation atomique, après rapprochement de la base, du journal, du témoin et de l'ancre ; sinon refus fermé. Les révocations de demandes, identifiants et commits sont définitives ; un nouvel identifiant nécessite une nouvelle invitation SSH. Aucun redémarrage ni restauration ne rouvre le service. Choix de conception seulement : Provider = CLOSED et NO-GO inchangés |
| D-10 | **Décidée par délégation le 2026-10-08 — inscription explicite des commits** | Option (ii) : inscrire individuellement par WebAuthn le SHA complet d'un commit seulement après sa fusion dans `main` et la réussite de CI. À chaque demande, le SHA OIDC doit correspondre exactement à une entrée active. SHA abrégé, inconnu, différent ou révoqué refusé ; révocation définitive. Les protections de `main` et la manière de vérifier l'éligibilité restent à préciser avec D-15. Décision de conception seulement, sans implémentation |
| D-11 | **Décidée par délégation le 2026-10-08 — recomposition et présentation du manifeste** | Option (b) : copie figée limitée aux assets verrouillés de Video 005 ; recalcul du manifeste côté service et comparaison exacte avec le manifeste du run ; affichage du prompt, des paramètres et des médias réels avant approbation. Aucun asset arbitraire accepté. Accès, chiffrement, sauvegarde, rétention et suppression doivent être démontrés avant mise en service. Aucun fichier n'est copié ou déployé à cette étape |
| D-12 | **Décidée par délégation le 2026-10-08 — exposition web conditionnelle** | Caddy reverse proxy avec HTTPS automatique ; TCP 80 limité à ACME/redirection, TCP 443 pour l'interface, TCP 22 pour SSH d'administration ; application sur loopback/socket Unix ; UI `zephyr-approval.fr` séparée de l'API OIDC `api.zephyr-approval.fr` et audiences distinctes. Limites de débit/taille/délai, CSP, absence de ressources tierces, CSRF, sessions sécurisées ; pas d'AAAA avant validation IPv6. Rien n'est ouvert ou installé : exposition et changement UFW nécessiteront une autorisation distincte et une revue de sécurité |
| D-13 | **Choix de conception conditionnel sous délégation le 2026-10-08 — PyJWT et python-fido2** | PyJWT avec l'extra `[crypto]` est retenu pour signature JWT/JWKS OIDC ; `python-fido2` est retenu pour la vérification WebAuthn côté serveur. Pas d'implémentation cryptographique maison ni d'extra PC/SC. Les versions directes et transitives exactes, empreintes de verrouillage, compatibilité Python, licences/avis de sécurité et procédure de mise à jour doivent être établies et revues en G2. Il reste à démontrer que les dépendances retenues couvrent la signature asymétrique de D-18 ; si une dépendance supplémentaire est nécessaire, elle doit être évaluée et verrouillée en G2. Rien n'est installé par cette décision |
| D-14 | **Report explicite sous délégation le 2026-10-08 — aucun montant ni dépense de génération autorisés** | Aucun plafond de crédits par requête ou par période n'est fixé. L'objectif budgétaire de 50 €/mois TTC porte sur les coûts récurrents d'infrastructure et ne constitue pas un plafond Higgsfield. Tant que le plafond par requête reste absent ou que le coût vaut `UNKNOWN`, toute demande est refusée, aucun crédit ne peut être consommé, et Provider reste CLOSED. La condition 3 de la Phase A demeure non satisfaite ; une éventuelle réévaluation du NO-GO exigera une décision ultérieure distincte fixant des limites numériques et leur périmètre. Ce report ne fixe aucun montant |
| D-15 | **Choix de conception conditionnel sous délégation le 2026-10-08 — protection des comptes et des accès** | MFA résistante à l'hameçonnage lorsque disponible, récupération protégée, comptes nominatifs et moindre privilège ; règles GitHub `main` avec PR, CI, blocage des force-push/suppressions et contournement administrateur désactivé lorsque possible ; Actions épinglées à des SHA complets ; MFA/IAM et alertes Scaleway (alertes non assimilées à un plafond) ; MFA, verrou et récupération DNS à vérifier ; inventaire puis révocation des voies Higgsfield de génération hors courtier avant tout usage réel. État actuel non vérifié ; aucune configuration ni clé modifiée ou consultée |
| D-16 | **Choix de conception conditionnel sous délégation le 2026-10-09 — CPython 3.14.4 comme cible Linux G2 ; CI Windows 3.14.5 maintenue** | Pas de mise à niveau du serveur dans cette décision. La compatibilité des dépendances verrouillées avec 3.14.4 doit être établie en G2 ; si elle échoue, D-16 est réexaminée. La validation Linux complète et l'audit d'architecture restent obligatoires avant toute mise en service. Version rapportée, non vérifiée indépendamment |
| D-17 | **Choix de conception conditionnel sous délégation le 2026-10-09 — exécution sérialisée et nouvelle approbation à chaque essai** | Un seul emplacement global d'exécution, occupé tant qu'une demande est active ou qu'une issue fournisseur n'est pas résolue. Un même manifeste peut être soumis de nouveau seulement après résolution définitive, avec nouvelle demande/assertion, nouvel `approval_id` et nouvelle clé d'idempotence ; `ACCEPTED` ne libère pas l'emplacement avant résolution du job, `AMBIGUOUS` bloque. `NOT_SENT` est terminal et toute reprise exige une nouvelle approbation. Le statut fournisseur n'est pas supposé vérifiable automatiquement |
| D-18 | **Choix de conception conditionnel sous délégation le 2026-10-09 — R-1, reçu asymétriquement signé** | Reçu canonique de consommation, vérifié par la Gate avec une clé publique épinglée, audience dédiée, validité maximale de 300 secondes, anti-rejeu et concordance exacte ; R-2 (TLS seul) et R-3 (HMAC) écartées. L'algorithme, la dépendance, la gestion des clés et le câblage Gate/contrats/courtier restent à concevoir et tester en G2. Aucune clé ni dépendance créée |

## 11. Séquence de preuves et de revues avant tout déploiement

Chaque étape est une condition de la suivante. Aucune n'ouvre le Provider.

1. **Revue de ce document G1** par le propriétaire, puis fusion éventuelle par PR.
2. **Décisions écrites** D-16 à D-18, ou décision explicite de reporter celles qui ne bloquent pas la suite. D-14 est reportée sans plafond : elle ne satisfait pas la condition 3 et n'autorise aucune dépense. D-1 à D-15 fixent des choix ou reports de conception ; ils ne constituent pas une autorisation d'implémenter, d'installer des dépendances, d'acheter un stockage, de modifier UFW/DNS, d'exposer l'interface, de déployer, de modifier des comptes ou d'ouvrir le Provider. Pour D-6, D-7, D-11, D-13 et D-15, les preuves de durabilité, de chiffrement, de sauvegarde, de restauration, de rétention et de suppression, le verrouillage reproductible des versions, l'examen de sécurité des dépendances et des comptes ainsi que la vérification des coûts restent préalables à toute mise en service.
3. **Vérifications documentaires et d'accès**, sans modifier les comptes : offres et tarifs TTC de Scaleway ; plan GitHub ; MFA et récupération des comptes ; droits IAM et clés déclarés ; règles actives de `main` et des Actions ; protections et récupération du registrar/DNS ; inventaire des accès de génération Higgsfield. Consigner seulement des résultats expurgés, jamais des secrets ni codes de récupération. Tout changement réel de réglage, de clé, de DNS ou de facturation demande une autorisation explicite distincte.
   - L'essai avec un **jeton OIDC réel** exige une **autorisation explicite et distincte du propriétaire**.
   - Il passerait par un workflow dédié qui n'affiche jamais le jeton brut, seulement des claims décodés non sensibles, et n'appelle aucun service.
4. **Phase G2, implémentation mock-only** sur le poste de développement :
   - contenu : énoncé canonique, vérificateurs OIDC et WebAuthn testés avec des clés générées par les tests, machine à états, stockage, témoin, journal, interrupteur, réponse du service selon D-18, recalcul et présentation du manifeste D-11 ;
    - avant toute exécution G2, fixer des versions directes et transitives exactes, générer un verrou avec empreintes, vérifier les avis de sécurité et licences, puis valider l'installation reproductible sur les Python Windows et Ubuntu retenus ; aucune dépendance n'est installée sur le serveur dans cette étape ;
   - aucun réseau, aucun secret réel, aucun asset réel de Video 005 (fixtures synthétiques uniquement) ;
   - des **gardes documentaires**, sur le modèle de `tests/test_phase_e1_documentary_invariants.py`, protègent G1 : NO-GO, Provider = CLOSED, absence de montant, liens valides ;
   - les quatre verrous, F-1 à F-4, les cardinalités et `NO_DRIFT` restent verts.
5. **Campagne Linux** de la section 9 (V-1 à V-3, X1 à X9), avec procès-verbal consigné. Déployer du code, même de test, sur le serveur exige une **autorisation explicite et distincte du propriétaire**, sans ouverture de port.
6. **Revue de sécurité** du code (`/security-review` et relecture humaine) et **revue du modèle de menace** serveur : comptes, droits, journaux système, mises à jour, racines de confiance de la section 5.
7. **Exercice de sauvegarde et de restauration** de bout en bout, consigné, y compris les scénarios de la section 3.4.
8. **Exposition web** : elle exige une **autorisation explicite et distincte du propriétaire** avant tout changement UFW, DNS, installation ou déploiement. Après les prérequis D-12, seuls les ports retenus sont ouverts, puis la configuration TLS et la sécurité de la page sont contrôlées depuis l'extérieur.
9. **Essai de bout en bout, Provider = CLOSED**, sur autorisation explicite du propriétaire :
   - run réel sur `main`, demande, approbation WebAuthn, consommation unique, puis arrêt attendu sur le code 4 ;
   - rejeu, relance, expiration, révocation et réapprobation (selon D-17) testés et refusés ;
   - aucun crédit consommé.
10. **Procédure d'arrêt et de refermeture** (condition 7) déroulée et consignée.
11. Seule une **nouvelle décision écrite**, distincte de celle de la Phase A, pourrait ensuite constater que les sept conditions sont remplies. Ce document ne la prépare pas et ne la promet pas.

## 12. Ce que cette phase ne fait pas
- Dans le périmètre initial de cette phase, aucune modification du code, des workflows, des tests, du verrou applicatif, de la configuration serveur, des réglages GitHub ou du DNS n’était prévue. Un audit ultérieur a activé la règle GitHub « Protect main » ; voir l’addendum ci-dessous.
### Addendum — Protection GitHub de main (10 octobre 2026)
Le ruleset « Protect main » est actif et cible uniquement la branche `main`. La liste d’exceptions est vide.

Les fusions dans `main` exigent une pull request et la réussite du contrôle GitHub Actions `tests`. Les suppressions et les force pushes sont bloqués. Aucune approbation humaine n’est exigée ; la mise à jour de la branche avec la dernière version de `main` n’est pas obligatoire.

Ce changement concerne les réglages GitHub. Aucun code, workflow ou test n’a été modifié ; aucun secret n’a été créé ou lu ; aucun appel au fournisseur n’a été lancé. Le contrôle GitHub Actions `tests`, déclenché automatiquement pour la pull request documentaire, a réussi. `Provider = CLOSED` et `NO-GO` restent en vigueur.
- Aucun secret ni aucune clé créée ou lue ; aucun logiciel installé ; aucun nouveau port ouvert ; SSH 22/tcp reste autorisé et à l’écoute ; aucun déploiement.
- Aucun appel à Higgsfield ; aucun workflow lancé manuellement ; le contrôle GitHub Actions déclenché automatiquement par la pull request documentaire a réussi ; aucun appel à `create_job()`.
- Aucune option choisie sans instruction ou délégation explicite du propriétaire ; aucun montant de plafond fixé ; aucun essai de la section 9 exécuté.
- Les conditions 1, 3, 5 et 7 de la Phase A restent **ouvertes**, la condition 2 reste **partiellement traitée**, et le **NO-GO** reste en vigueur.

**Provider = CLOSED · Real generation = 0 · API balance = UNKNOWN**


### GitHub Actions — Permissions (11 octobre 2026)

La politique GitHub Actions est restreinte à « cleevengtonzephyr-ux » et aux Actions externes explicitement autorisées. Les Actions créées par GitHub et celles de créateurs vérifiés du Marketplace ne sont pas autorisées globalement.

Les seules Actions externes inscrites dans la liste sont `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` et `actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97`. L’obligation d’épingler les Actions sur un SHA complet est activée. Les workflows examinés utilisent ces deux Actions, épinglées sur ces SHA.

Ce changement concerne les réglages GitHub Actions. Aucun code, workflow ou test n’a été modifié ; aucun secret n’a été créé ou lu ; aucun appel au fournisseur n’a été lancé. Le contrôle GitHub Actions `tests`, déclenché automatiquement pour la PR #29, a réussi. `Provider = CLOSED` et `NO-GO` restent en vigueur.

### Vérification de la facturation Scaleway (12 octobre 2026)

La liste des factures passées affiche une facture d’octobre 2026, type « Purchase », statut « Paid », total final de 5,98 € TTC (TVA : 0 %). Cost Manager affiche séparément 13,44 € HT de consommation courante. Ces chiffres ne sont pas réconciliés comme un total unique ; vérifier la facture de consommation après la clôture d’octobre.

### Audit des accès Scaleway, DNS et Higgsfield (14 octobre 2026)

Constats consignés à partir des captures fournies par le propriétaire et des commandes de lecture seule qu’il a exécutées. Les éléments qui ne sont pas confirmés ci-dessous restent ouverts.

**Scaleway, IAM et serveur**
- L’organisation montre un membre actif, propriétaire, avec MFA configurée sur son compte. L’application indique cependant que l’obligation MFA à l’échelle de l’organisation n’est pas appliquée. Aucune clé API Scaleway n’est affichée. L’organisation comporte 5 groupes et 3 politiques ; les trois politiques de groupes personnalisés sont décrites dans le complément IAM ci-dessous. Les droits directs et la vue exhaustive des permissions effectives restent à confirmer.
- Le domaine `zephyr-approval.fr` est actif, verrouillé contre le transfert et le renouvellement automatique est activé ; l’expiration affichée est le 5 octobre 2027. Le propriétaire confirme que les contacts sont accessibles et à jour. DNSSEC est désactivé. La zone comporte deux NS et un enregistrement A vers `78.232.45.139`, adresse que le propriétaire confirme comme celle de l’instance AI_DIRECTOR.
- L’instance est affichée « Running », avec facturation active, en zone PAR1. Le groupe de sécurité affiche les politiques par défaut entrantes et sortantes sur Accept et aucune règle personnalisée entrante ou sortante ; des règles fixes bloquent toutefois SMTP sortant.
- Sur Ubuntu, UFW est actif, journalisation faible, politique entrante `deny` et sortante `allow`. La seule règle entrante affichée est SSH 22/tcp depuis toutes les adresses, en IPv4 et IPv6. La configuration SSH effective interdit root et l’authentification par mot de passe, et autorise les clés publiques. La liste des sockets montre SSH 22 comme seul port TCP écoutant sur toutes les interfaces ; aucun service Web n’écoute actuellement sur 80 ou 443.
- L’administration se fait depuis un partage de connexion mobile Wizzee. Le caractère fixe ou changeant de l’adresse publique n’est pas connu ; aucune restriction SSH par adresse source n’a donc été vérifiée ou configurée. Le filtrage cloud par groupe de sécurité ne limite pas actuellement les connexions entrantes.
- Le tableau de facturation montre un champ de budget mensuel sans montant et une alerte par courriel à 90 %. Cette alerte est une notification, pas une limite de dépense. Les 5,98 € TTC de la facture d’octobre et les 13,44 € HT affichés par Cost Manager restent à rapprocher après clôture de la période.

**GitHub**
- Le propriétaire confirme le 15 octobre 2026 que la double authentification et les moyens de récupération de son compte GitHub sont activés et à jour. Cette confirmation n’a pas été vérifiée indépendamment ; aucun code de récupération ni secret n’a été demandé ou communiqué.

**Higgsfield**
- Selon les captures et les vérifications rapportées par le propriétaire, la console API n’affiche aucune clé, le solde API est nul et Analytics affiche 0 requête sur les 30 derniers jours.
- Sur le compte Web, la capture « 7 derniers jours » affiche 0 coût, 0 crédit dépensé et 0 génération totale ; le rechargement automatique est désactivé. Elle montre aussi trois lignes « Mode Auto Libre », « Épuisé », chacune à 0 crédit, datées du 10 octobre 2026 vers 07 h 03–07 h 04. Le propriétaire ne reconnaît pas ces événements. Ces écrans ne montrent aucune génération achevée ni dépense de crédits, mais ne permettent pas d’identifier qui a déclenché les événements ni d’exclure un accès non autorisé.
- Le propriétaire confirme le 14 octobre 2026 avoir effectué la démarche recommandée : changer le mot de passe (ou sécuriser le compte du fournisseur de connexion, selon la méthode utilisée) et contacter Higgsfield pour fermer les sessions actives. La fermeture effective n’a pas été vérifiée indépendamment. La procédure officielle Higgsfield décrit cette récupération ([source](https://higgsfield.ai/creator-hub/help-center/account/how-do-i-recover-access-to-my-account)). Le propriétaire a depuis confirmé deux connexions connues — ChatGPT et Claude — décrites dans le complément du 15 octobre ci-dessous. Les autres voies d’accès pouvant lancer une génération restent à inventorier. Les trois événements inexpliqués empêchent de considérer l’inventaire comme terminé.

### Complément — Groupes et politiques IAM Scaleway (15 octobre 2026)

Constats tirés des captures de la console IAM fournies par le propriétaire. Les noms et identifiants personnels ne sont pas reproduits.

- La liste montre cinq groupes : `Administrators`, `Billing Administrators`, `Editors`, ainsi que les groupes intégrés `All Applications` et `All Users`. La colonne des politiques associe les trois premiers groupes à une politique du même nom ; aucune politique n'est affichée pour les deux groupes intégrés dans cette capture.
- Les pages de détail présentées pour `Administrators`, `Billing Administrators` et `Editors` ne montrent aucun utilisateur ni aucune application membre. Aucun bénéficiaire par ces trois groupes n'est donc visible dans les captures. Le compte Owner conserve ses propres droits indépendamment de ces appartenances. Les attributions directes à des utilisateurs et les autres voies d'accès n'étant pas exhaustivement examinées, cet élément ne clôt pas l'inventaire IAM.
- La politique `Administrators` comprend `OrganizationManager` au niveau de l'organisation, sans condition, et `AllProductsFullAccess` sur tous les projets, sans condition. Cette combinaison permet la gestion de l'organisation et des ressources de tous les projets ; Scaleway indique aussi que `OrganizationManager` permet de créer des politiques donnant accès à d'autres actions et ressources ([ensembles de permissions](https://www.scaleway.com/en/docs/iam/policies-permissions/permission-sets/)).
- La politique `Billing Administrators` comprend `BillingManager` et `OrganizationReadOnly` au niveau de l'organisation, sans condition. Elle correspond au rôle de gestion de facturation décrit par Scaleway ([rôles IAM](https://www.scaleway.com/en/docs/iam/policies-permissions/reproduce-roles-project-api-keys/)).
- La politique `Editors` comprend au niveau de l'organisation, sans condition, `AuditTrailFullAccess`, `OrganizationReadOnly`, `ProjectManager` et `SupportTicketReadOnly`, ainsi que `AllProductsFullAccess` sur tous les projets, sans condition. `AuditTrailFullAccess` est un ensemble de permissions supplémentaire par rapport au rôle Editor standard décrit par Scaleway ([rôles IAM](https://www.scaleway.com/en/docs/iam/policies-permissions/reproduce-roles-project-api-keys/)).
- Ces politiques sont très étendues si un utilisateur ou une application leur est associé ultérieurement. Aucun groupe, membre, application ou politique n'a été modifié pendant cet audit.

Aucun secret ni aucune clé n’a été lu ou copié dans le dépôt ; aucune clé, aucun réglage de compte, aucune règle réseau ou DNS n’a été modifié. Codex n’a lancé aucun appel API Higgsfield ni aucune génération pour ces contrôles documentaires. Les commandes CLI saisies par le propriétaire sont décrites dans le complément dédié ; leurs résultats et éventuels effets réseau ne sont pas tous vérifiables depuis l’historique. Ces constats ne lèvent pas le NO-GO : Provider = CLOSED, plafond de dépense Higgsfield non fixé et génération réelle toujours non autorisée.

### Complément — Connexions Higgsfield aux agents IA (15 octobre 2026)

Constats issus d’une capture des paramètres du plugin ChatGPT et des confirmations du propriétaire. Les identifiants et adresses de compte ne sont pas reproduits.

- Dans ChatGPT, le plugin Higgsfield est installé. La page de gestion affiche un compte connecté nommé « Primary » ; le propriétaire confirme qu’il s’agit de son compte Higgsfield. L’adresse affichée sur la capture est expurgée. Cette connexion est donc reconnue par le propriétaire, mais la capture ne démontre pas que le plugin a été utilisé.
- Le propriétaire déclare avoir configuré Higgsfield dans Claude et confirme que le connecteur y apparaît connecté. Ce statut n’a pas été inspecté indépendamment.
- Higgsfield indique que les connecteurs d’agents peuvent fonctionner sans clé API et que les générations faites par ces connecteurs consomment des crédits ([guide officiel des intégrations Higgsfield](https://higgsfield.ai/creator-hub/help-center/integrations/how-do-i-connect-higgsfield-to-ai-agent)). La présence des deux connexions établit des voies d’accès possibles, pas une activité ni une dépense. Les captures d’usage précédentes montraient 0 requête API sur 30 jours et 0 génération/crédit dépensé sur les 7 derniers jours ; elles n’identifient pas l’auteur des trois événements « Mode Auto Libre / Épuisé » du 10 octobre.
- Pour vérifier les connexions ChatGPT et Claude, Codex n’a lancé aucun appel de génération et aucune connexion n’a été déconnectée. Le CLI PowerShell est examiné dans le complément suivant ; l’inventaire reste incomplet pour Cursor et tout autre client ou agent non examiné. La revue de ces accès et l’application de D-15 avant tout usage réel restent ouvertes ; Provider = CLOSED et NO-GO demeurent en vigueur.

### Complément — Audit du CLI Higgsfield sous PowerShell (15 octobre 2026)

Constats issus des commandes locales et des résultats expurgés transmis par le propriétaire. Aucun jeton, contenu du fichier d’identifiants, prompt ou argument de commande n’est reproduit.

- **Commande disponible et connexion reconnue.** Get-Command higgsfield affiche un script PowerShell externe (higgsfield.ps1). higgsfield auth --help expose login, logout et token. Le propriétaire confirme avoir utilisé auth login avec son propre compte. La présence du fichier ~/.config/higgsfield/credentials.json a été vérifiée par son existence uniquement, sans en lire le contenu ; ce chemin est indiqué par la [documentation officielle des skills Higgsfield](https://github.com/higgsfield-ai/skills/blob/main/CLAUDE.md). Cela établit une voie CLI reconnue et des identifiants locaux présents, pas leur validité actuelle ni une utilisation réussie.
- **Historique PowerShell.** L’historique consulté contient 47 entrées commençant par higgsfield : 4 auth login, 12 commandes de la famille generate, 10 commandes account ou workspace, et 0 commande upload. Le propriétaire n’a transmis que les totaux et catégories, pas les lignes ou arguments.
- **Détail des commandes de génération.** Les 12 entrées se répartissent en 5 generate cost, 3 demandes d’aide generate cost, 2 generate --help, 1 generate workflow --help et 1 generate workflow avec un nom de workflow mais sans option. Aucune entrée generate create n’a été relevée. La documentation distingue l’estimation de coût de la création d’un job et montre que les workflows demandent des entrées comme une vidéo, un prompt ou des paramètres ([CLI officiel](https://github.com/higgsfield-ai/cli)). L’entrée avec un nom seul paraît incomplète, mais l’historique ne conserve pas sa sortie ni son code de retour ; il ne permet donc pas de prouver qu’elle a échoué ou qu’aucun job n’a été créé.
- **Autres commandes.** Les 10 entrées account/workspace n’ont pas été détaillées par sous-commande ; leur résultat et un éventuel accès réseau ne sont pas établis. Les totaux ne démontrent ni génération réussie ni dépense. Les captures d’usage déjà consignées affichent 0 génération et 0 crédit dépensé sur leur période, mais les trois événements Mode Auto Libre / Épuisé du 10 octobre restent non reconnus et sans attribution.
- **Limites et statut.** Cette vérification couvre l’historique PowerShell consulté seulement ; elle ne couvre pas les historiques supprimés, d’autres terminaux, appareils ou agents. Aucun paramètre de compte ni identifiant local n’a été modifié ou révoqué. La voie CLI est maintenant reconnue ; les autres clients non examinés restent à inventorier. Provider = CLOSED et NO-GO restent en vigueur, et la décision D-15 demeure ouverte avant tout usage réel.

### Complément — Usage Higgsfield via Claude Code et suivi du relevé (16 octobre 2026)

Constats complémentaires transmis par le propriétaire. Aucun secret, prompt ou identifiant de requête n’est reproduit.

- **Usage reconnu.** Le propriétaire confirme avoir déjà généré des vidéos avec Claude Code via Higgsfield, principalement pour sa chaîne YouTube Zephyr AI. Cet usage est reconnu comme sien. Il ne permet pas, à lui seul, d’attribuer les trois événements du 10 octobre à ces vidéos.
- **Claude Code et autres agents.** Dans PowerShell, `claude` est présent ; `openclaw`, `hermes` et `cursor-agent` sont absents, et l’application Cursor n’apparaît pas dans la recherche du menu Démarrer. Ces vérifications ponctuelles n’excluent pas d’autres installations ou clients non examinés. `claude mcp list` affiche un serveur Higgsfield avec le statut « Needs authentication ». Le propriétaire ne se rappelle pas avoir ajouté cette configuration. Cela décrit son état au moment du contrôle, sans établir son origine ni son historique d’authentification. Le propriétaire a par ailleurs utilisé le CLI Higgsfield avec son compte ; le chemin précis employé pour ses vidéos Claude Code n’est pas démontré par ces sorties.
- **Espace de facturation.** L’historique PowerShell contient une commande `workspace set` avec un argument masqué. Le résultat de cette invocation n’est pas disponible. `higgsfield workspace status` affiche actuellement le contexte privé et le forfait Plus. Le relevé ne prouve donc ni qu’un espace d’équipe a été sélectionné avec succès, ni qu’il l’est actuellement.
- **Trois événements du 10 octobre.** La capture du relevé détaillé montre trois lignes « Free Auto mode », statut « Spent », à 07:03, 07:03 et 07:04, chacune à 0 crédit. Aucun modèle, identifiant de requête/job, source ou résultat n’est visible. Le propriétaire ne retrouve pas de vidéo correspondante dans Assets. Le Centre d’aide publié ne définit pas ces libellés ; zéro crédit indique qu’aucun crédit n’a été déduit, sans permettre de conclure si une génération a été exécutée ou si un résultat a été créé.
- **Suivi support.** Le propriétaire indique avoir envoyé un courriel au support Higgsfield avec la capture et une demande d’explication sur le sens des événements, les résultats éventuels, la source et les identifiants de requête. Deux réponses sont arrivées le 16 octobre : elles expliquent la catégorie des événements, mais les détails techniques par entrée annoncés restent en attente (complément ci-dessous).

Ces éléments reconnaissent une activité antérieure voulue via Claude Code, mais ne résolvent pas l’attribution des trois événements du 10 octobre. Jusqu’à reconnaissance de la conversation et clôture des autres contrôles D-15, **Provider = CLOSED** et **NO-GO** restent en vigueur. Codex n’a lancé aucun appel Higgsfield, génération, téléversement ou déploiement.

### Complément — Réponses du support Higgsfield et sécurisation du compte (16 octobre 2026)

Constats issus de deux courriels du support Higgsfield transmis par le propriétaire. Le ticket est référencé par le support comme `#333346`. Ces messages sont consignés comme déclarations du fournisseur, sans vérification indépendante du contenu du compte.

- **Nature des trois événements.** Le support confirme que les trois lignes « Free Auto mode » du 10 octobre, à 0 crédit, correspondent à des messages et réponses textuels dans une conversation Supercomputer en Auto mode. Ces interactions sont gratuites et ne créent pas à elles seules de photo, vidéo ou audio ; aucun job ni média correspondant n’est donc attendu dans Assets.
- **Historique à consulter.** Le support indique que la conversation correspondante devrait être retrouvée dans l’historique Supercomputer du 10 octobre. Le propriétaire n’a pas encore confirmé reconnaître ces messages. Cette explication établit leur catégorie et l’absence de génération média/job, mais n’identifie pas l’auteur ni l’appareil à l’origine des interactions.
- **Suivi technique.** Le premier courriel indique que la demande de détails par entrée (source et détails de requête) a été transmise à l’équipe de développement, avec un suivi annoncé sous 24 heures. Le second courriel confirme la catégorie des interactions, mais ne fournit pas les identifiants individuels, l’appareil ni l’auteur. Le suivi technique reste donc ouvert.
- **Mesures de compte.** Le support recommande, si l’activité n’est pas reconnue, de changer le mot de passe et de fermer les sessions Higgsfield sur tous les appareils. Le propriétaire indique le 16 octobre avoir déjà effectué ces mesures. Leur effet et la fermeture effective de toutes les sessions n’ont pas été vérifiés indépendamment. Cette déclaration concerne Higgsfield, pas les sessions Scaleway examinées séparément.
- **Conséquence pour l’audit.** Les trois entrées ne témoignent pas d’une dépense de crédits ni d’une génération média selon le support. L’attribution personnelle des messages et l’inventaire complet des voies d’accès restent à établir ; la réponse technique par entrée est encore attendue.

Aucun appel API, message Supercomputer, génération, téléversement ou déploiement Higgsfield n’a été lancé par Codex pour cette vérification. `Provider = CLOSED` et `NO-GO` restent en vigueur.

### Confirmation des sessions de console Scaleway (16 octobre 2026)

La capture de l’onglet des identifiants du compte Owner affiche cinq sessions de console, toutes indiquées comme Chrome sur Windows 10 : une datée du 5 octobre 2026 et quatre du 16 octobre 2026. Le propriétaire confirme le 16 octobre reconnaître les cinq sessions comme les siennes. Les adresses IP ne sont pas reproduites. Aucune session n’a été révoquée ou modifiée pendant cette vérification.

Cette confirmation est une déclaration du propriétaire à partir des informations affichées ; elle ne constitue pas une vérification technique indépendante de l’appareil ou des adresses IP. Elle concerne les sessions Scaleway et ne change pas l’analyse distincte des accès Higgsfield. Aucun identifiant, paramètre de compte ou secret n’a été consulté ou modifié. `Provider = CLOSED` et `NO-GO` restent en vigueur.

### Pré-vérification des dépendances G2 — avis PyJWT à clarifier (16 octobre 2026)

Revue documentaire des métadonnées publiques et avis de sécurité, sans installation de dépendance ni modification de code.

- **Candidats déclarés par D-13.** PyPI publie PyJWT 2.15.1 (licence MIT) et `fido2` 2.2.1 (Python `>=3.10,<4`, licences déclarées Apache/BSD/MPL-2.0). La fiche GitHub de `python-fido2` ne montre aucun avis de sécurité publié au moment de cette revue. Ces éléments de catalogue ne remplacent pas l’examen de la licence des dépendances transitives ni la validation des versions exactes.
- **Avis PyJWT corrigés dans une version publiée.** Les avis GHSA-42vr-xj54-vc7v et GHSA-x33g-cr3x-6449 indiquent PyJWT 2.15.0 comme première version corrigée. Ils ne bloquent donc pas, à eux seuls, l’examen de 2.15.1.
- **Avis PyJWT sans version corrigée déclarée.** GHSA-gvp8-978c-rx2q indique `Patched versions: None`, pour une mutation d’un dictionnaire `options` réutilisé entre appels de vérification. Sa plage publiée s’arrête à 2.13.0 ; elle ne classe pas 2.15.1 comme vulnérable, mais l’absence de version corrigée et d’explication de la frontière laisse son statut de correction indéterminé. L’avis décrit un correctif préparé, sans indiquer qu’une version publiée le contient. Avant de verrouiller PyJWT, il faut obtenir une confirmation du mainteneur, vérifier un avis mis à jour et le correctif dans l’artefact publié, ou évaluer une autre bibliothèque prise en charge. L’application ne devra jamais réutiliser un dictionnaire mutable `options` entre modes de vérification.
- **Verrou non établi.** Les versions exactes et empreintes transitives, notamment celles de `cryptography`, la compatibilité de l’ensemble avec CPython 3.14.5 Windows et la cible Linux rapportée CPython 3.14.4, les licences et tous les avis restent à contrôler. Aucun fichier de verrou n’a été créé et aucune dépendance n’a été installée.
- **Décision d’étape.** Cette pré-vérification n’autorise pas encore le verrouillage final ni l’implémentation des vérificateurs G2. D-13 et la précondition de verrouillage de l’étape 4 restent ouvertes jusqu’à résolution du point PyJWT et à l’examen reproductible de l’arbre complet des dépendances. Aucun test, workflow, appel réseau applicatif, accès fournisseur ou déploiement n’a été lancé. `Provider = CLOSED` et `NO-GO` restent en vigueur.

Sources consultées le 16 octobre 2026 : [PyJWT sur PyPI](https://pypi.org/project/PyJWT/), [fido2 sur PyPI](https://pypi.org/project/fido2/), [avis GHSA-42vr-xj54-vc7v](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-42vr-xj54-vc7v), [avis GHSA-x33g-cr3x-6449](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-x33g-cr3x-6449), [avis GHSA-gvp8-978c-rx2q](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-gvp8-978c-rx2q), [avis de sécurité publiés de python-fido2](https://github.com/Yubico/python-fido2/security/advisories).

### G2 — verrou candidat et installation Windows (16 octobre 2026)

Suite à la pré-vérification, création d’un manifeste séparé pour les dépendances futures du service (`approval_service/pyproject.toml`) et d’un verrou uv universel (`approval_service/uv.lock`). Cela ne modifie pas les dépendances du Director historique et n’implémente aucun service.

- **Versions directes et transitives verrouillées.** PyJWT 2.15.1 avec l’extra `crypto`, `fido2` 2.2.1, `cryptography` 50.0.2, `cffi` 2.1.1 et `pycparser` 3.11. Le verrou consigne les empreintes SHA-256 des distributions et roues disponibles par plateforme. Aucun extra PC/SC n’est demandé. Les exigences Python sont `>=3.14.4,<3.15`, correspondant aux cibles de conception Windows 3.14.5 et Linux 3.14.4.
- **Point GHSA-gvp8-978c-rx2q.** La fiche GitHub affiche toujours `Patched versions: None` et ne classe comme affectées que les versions jusqu’à 2.13.0. Pour lever le doute sur l’artefact retenu, l’installation Windows a été faite depuis la roue PyPI PyJWT 2.15.1 ; le fichier `jwt/api_jwt.py` installé contient la copie défensive `dict(options)` avant mutation. Le SHA-256 de la roue correspond à celui publié par PyPI. Cela constitue une vérification directe du correctif dans l’artefact, tandis que le statut textuel de l’avis reste non actualisé. L’application conservera l’invariant de ne pas réutiliser un dictionnaire mutable `options` entre modes de vérification.
- **Avis connus.** Un audit de l’environnement verrouillé par `pip-audit` a indiqué « No known vulnerabilities found » à la date du contrôle. Ce résultat est borné à la base d’avis consultée par l’outil et ne remplace pas le suivi des avis éditeurs ni la revue avant chaque mise en service. PyJWT 2.14.0 corrige les avis antérieurs portant notamment sur les JWK/JWKS, les clés HMAC vides, les redirections JWKS et les entrées profondément imbriquées ; 2.15.1 est ultérieur. La version `cryptography` retenue est postérieure aux seuils de correction publiés pour les avis examinés.
- **Licences relevées dans les métadonnées PyPI.** PyJWT : MIT ; `fido2` : Apache-2.0, BSD et MPL-2.0 ; `cryptography` : Apache-2.0 OU BSD-3-Clause ; `cffi` : MIT-0 ; `pycparser` : BSD-3-Clause. Cette revue de métadonnées ne remplace pas une validation juridique des obligations de redistribution.
- **Installation reproductible Windows.** `uv sync --locked --no-dev` a installé les cinq distributions sur CPython 3.14.5 Windows depuis ce verrou, dans un environnement temporaire isolé. Aucune suite de tests n’a été exécutée.
- **Limite et suite bloquante.** Aucune distribution Linux/WSL n’est disponible sur le poste. Bien que le verrou contienne des artefacts Linux compatibles déclarés, l’installation effective sous CPython 3.14.4 Ubuntu reste à réaliser avant de considérer la précondition G2 complète. Le verrou est donc un candidat documenté, pas une autorisation de commencer l’implémentation G2. Aucun paquet n’a été installé sur le serveur ; aucun réseau applicatif, secret réel, asset réel, appel fournisseur ou déploiement n’a été utilisé. `Provider = CLOSED` et `NO-GO` restent en vigueur.

Sources consultées le 16 octobre 2026 : [PyJWT 2.15.1 sur PyPI — licence et empreinte publiée](https://pypi.org/project/PyJWT/2.15.1/), [source PyJWT 2.15.1](https://github.com/jpadilla/pyjwt/blob/2.15.1/jwt/api_jwt.py), [avis GHSA-gvp8-978c-rx2q](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-gvp8-978c-rx2q), [changelog PyJWT 2.14.0](https://github.com/jpadilla/pyjwt/blob/2.14.0/CHANGELOG.rst), [fido2 2.2.1 sur PyPI](https://pypi.org/project/fido2/2.2.1/), [cryptography 50.0.2 sur PyPI](https://pypi.org/project/cryptography/50.0.2/), [cffi sur PyPI](https://pypi.org/project/cffi/), [pycparser sur PyPI](https://pypi.org/project/pycparser/), [avis cryptography](https://github.com/pyca/cryptography/security/advisories).

### G2 — validation du verrou sur Ubuntu via CI (17 octobre 2026)

Le poste de développement ne dispose pas d’une distribution WSL ni de Docker/Podman ; l’installation effective sur Ubuntu ne peut donc pas être réalisée localement. Pour ne pas prétendre qu’une compatibilité Linux est prouvée par la seule résolution universelle du verrou, le workflow CI ajoute un contrôle d’installation isolé ciblant Ubuntu 24.04 avec CPython 3.14.4, ainsi que Windows 2025 avec CPython 3.14.5.

- Le job installe uniquement les dépendances verrouillées du sous-projet `approval_service` avec `uv sync --locked --no-dev`. Il n’exécute pas le service, n’utilise aucun secret, n’appelle aucun fournisseur et ne déploie rien.
- La version de uv utilisée pour ce contrôle est fixée à 0.13.1. Les actions de checkout et de configuration Python réutilisent les révisions déjà épinglées par la CI.
- **Résultat obtenu sur la PR #41 fusionnée.** GitHub Actions a validé l’installation verrouillée sur Windows 2025 / CPython 3.14.5 et Ubuntu 24.04 / CPython 3.14.4. Après correction du test de pins d’actions (compteur fixe de 6 devenu inutile après l’ajout du job matriciel), la suite complète et l’audit d’architecture ont également réussi ; la PR affiche trois contrôles réussis. Cela satisfait le prérequis d’installation reproductible pour commencer l’implémentation G2 mock-only, sans constituer une preuve de disponibilité ou de durabilité sur le serveur.
- Le job ne change ni le périmètre d’exécution G2, ni les verrous de production : `Provider = CLOSED` et `NO-GO` restent en vigueur. L’implémentation G2 est commencée dans l’addendum ci-dessous.

Référence d’action : [documentation officielle de setup-python](https://github.com/actions/setup-python/blob/main/docs/advanced-usage.md).

### G2 — première primitive d’énoncé canonique (17 octobre 2026)

Début de l’implémentation mock-only dans `approval_service/approval_service/canonical_json.py` : sérialisation JSON compacte à clés triées, encodée en UTF-8, et calcul SHA-256 en hexadécimal minuscule. Les floats, clés non textuelles, types Python non JSON et chaînes non encodables en UTF-8 sont refusés pour éviter une empreinte ambiguë entre runtimes. Cette primitive ne définit pas encore le schéma métier de l’énoncé et n’effectue aucune vérification OIDC/WebAuthn.

- Sept tests locaux couvrent la stabilité d’ordre, les octets UTF-8, l’absence de mutation et les refus de types ambigus ; ils réussissent. `git diff --check` et l’audit `python scripts/architecture_audit.py` réussissent (`NO_DRIFT`).
- Aucun serveur HTTP, stockage, appel réseau, secret, asset réel, fournisseur ou génération n’est utilisé. La suite G2 reste incomplète ; `Provider = CLOSED` et `NO-GO` restent en vigueur.

### G2 — schéma versionné de l’énoncé d’approbation (17 octobre 2026)

Ajout d’un modèle immuable et strict (`approval_service/approval_service/approval_statement.py`) aligné sur les champs de la section 4.5. Le modèle lie le RP, l’approbateur pseudonyme et la méthode WebAuthn, les identifiants stables du dépôt/run/workflow, le SHA complet, les empreintes du manifeste et des médias, les paramètres vidéo et les identifiants générés par le service. Les horodatages sont des entiers Unix en millisecondes ; `approval_deadline` doit valoir `requested_at + 600 s`, et la validité de l’autorisation ne dépasse pas 300 s. Cette unité est une convention de représentation de l’implémentation, sans modifier les délais D-8.

- Le nonce est vérifié comme 256 bits en hexadécimal minuscule et distinct des trois identifiants de service. L’empreinte de l’énoncé utilise les octets canoniques ; le défi WebAuthn est une empreinte SHA-256 de ces octets, du nonce brut et d’un préfixe de séparation de domaine.
- `max_cost_credits_per_request` reste obligatoirement `null` conformément à D-14. Ce modèle ne prend aucune décision et n’autorise aucune génération ; la demande demeure bloquante tant qu’un plafond n’est pas défini séparément.
- Huit tests sur le schéma et le défi, ainsi que les sept tests JSON canoniques, réussissent localement. Aucun vrai jeton OIDC, identifiant WebAuthn, secret, réseau, stockage, asset ou fournisseur n’est utilisé. Vérificateurs, registre transactionnel et serveur restent à implémenter ; `Provider = CLOSED` et `NO-GO` restent en vigueur.

### G2 — vérificateur OIDC GitHub mock-only (17 octobre 2026)

Ajout de `approval_service/approval_service/oidc_verifier.py`. Le vérificateur n’accepte que RS256 avec une clé publique fournie par une interface de résolution injectée ; il exige l’émetteur GitHub Actions fixe, une audience exacte propre à l’interface, les claims temporels et d’identité requis, le dépôt et le workflow configurés, `refs/heads/main`, `workflow_dispatch`, un runner `github-hosted`, un SHA complet inscrit explicitement et la première tentative du run. Une tolérance d’horloge de 30 secondes est appliquée. L’environnement protégé peut être exigé par configuration. Les erreurs restent génériques et n’incluent pas le jeton.

- Les clés synthétiques RSA et les JWT des tests sont générés localement. Le module ne récupère pas de JWKS, n’utilise aucun jeton réel et n’a pas d’accès réseau. Le claim `actor` et `jti` restent optionnels dans la sortie jusqu’à confirmation de leur contrat sur un jeton réel autorisé ; si `jti` est présent, son unicité durable reste à faire respecter par le futur stockage transactionnel.
- Cette brique ne crée pas de demande et ne décide pas d’une approbation. L’approvisionnement JWKS GitHub borné à l’URL prévue, sa politique de cache/rotation, la détection persistante des replays, WebAuthn, le stockage et le serveur restent hors périmètre. Aucun workflow ni permission `id-token: write` n’est modifié ; `Provider = CLOSED` et `NO-GO` restent en vigueur.

### G2 — réservation atomique d’exécution (17 octobre 2026)

Correction de la course P2.16 : deux processus pouvaient constater ensemble qu’une même demande n’avait pas encore été exécutée. Avec le verrou par défaut (`NoOpCriticalSectionLock`), tous deux obtenaient `APPROVED` et interrogeaient le fournisseur ; seul le marqueur « en vol » arrêtait le second avant `create_job()`, après la consommation de sa propre autorisation.

- **Mécanisme.** Chaque store expose `execution_claims`. `GenerationJobService.execute()` prend `gate.claim_execution(request_id)` comme première instruction dans le verrou de section critique, avant `evaluate()`, et la garde jusqu’après `mark_executed()`. Côté fichier, la réservation est un fichier `<request_id>.execution-claim` du dossier d’état, verrouillé sans attente par `msvcrt.locking` (Windows) ou `fcntl.flock` (Linux). Ce fichier est stable : la libération ferme seulement le descripteur et le laisse en place, vide ; le détenteur suivant verrouille le même inode. Le supprimer à la libération aurait ouvert une course sous Linux : un nouveau venu aurait pu recréer le chemin et verrouiller un nouvel inode pendant que l’ancien détenteur tenait encore l’ancien. C’est un verrou vide, ni bail actif ni marqueur d’exécution : sa présence ne dit pas qu’une exécution est en cours ou a eu lieu. Un concurrent reçoit `ExecutionClaimBusyError` sans évaluation, consommation, écriture ni appel fournisseur. L’exception n’est pas convertie en rapport, car `FinalReportService` réévaluerait alors la demande. Un identifiant invalide, un fichier inutilisable ou remplacé pendant l’acquisition, ou un store sans registre de réservations entraînent un refus fermé.
- **État persistant corrompu.** La réservation n’autorise rien : `evaluate()` relit le registre sous elle. Un registre illisible, mal formé ou verrouillé donne `BLOCKED` ; rien n’est consommé, écrit ou créé, et le fichier n’est jamais réparé automatiquement.
- **Arrêt d’un processus.** Le système libère le verrou à la fin du processus : aucune réservation ne reste détenue. Le blocage éventuel vient des registres durables, jamais du verrou :

| Arrêt du détenteur | Trace durable | Essai suivant |
|---|---|---|
| Avant la consommation de l’autorisation | Aucune | Évaluation normale. Aucun `create_job()` n’a pu avoir lieu (le marqueur « en vol » le précède toujours) : ce n’est pas un rejeu |
| Après la consommation, avant le marqueur « en vol » | Autorisation consommée | `NEEDS_APPROVAL` : une nouvelle autorisation humaine est requise |
| Pendant l’écriture du marqueur | Aucun marqueur (écriture atomique) ; verrou du store orphelin | `BLOCKED` jusqu’à la revue humaine |
| Marqueur écrit, pendant ou après `create_job()`, avant `mark_executed()` | `EXECUTION_STATE_UNKNOWN` | Refus ; revue humaine, aucun rejeu automatique |
| Après `mark_executed()` | Exécution enregistrée | `ALREADY_EXECUTED` |

  Le fichier de réservation laissé par un arrêt est le même verrou vide qu’après une libération normale : la réservation suivante verrouille ce même inode. Il ne doit être ni supprimé ni remplacé à la main pendant qu’un processus peut tourner. Sous Linux, cela permettrait un second détenteur sur un nouvel inode ; le marqueur « en vol », vérifié sous le verrou du store, resterait alors la seule garde contre un second `create_job()`. Sur le chemin réel, `director.py` conserve aussi `FileCriticalSectionLock`, pris avant la réservation : son fichier `<request_id>.lock` reste orphelin après un arrêt et bloque jusqu’à la revue humaine (P2.20, inchangé).
- **Preuves.** Dans `tests/test_phase_p2_16_concurrency_audit.py`, deux tests à quatre vrais processus vérifient un seul gagnant, au niveau du store puis dans `execute()`. Les processus refusés n’appellent jamais le fournisseur. Le détenteur garde la réservation jusqu’au refus de tous les autres : le résultat ne dépend pas de l’ordonnancement. L’expérience historique de l’Objectif 4 est conservée telle quelle. `tests/test_g2_atomic_execution_claim.py` (19 tests) couvre les threads, les refus fermés, la position dans `execute()`, le câblage de `director.py` et trois arrêts durs de processus. Il comprend aussi un passage de main entre trois vrais processus selon un calendrier fixe : chaque concurrent tente la réservation pendant que le détenteur est dans son bloc, et le détenteur suivant ne commence qu’après la sortie complète du précédent. Un marqueur à création exclusive témoigne qu’aucun second bloc n’a été actif, et tous les détenteurs verrouillent le même inode. Des mutations temporaires font échouer ces tests : verrou neutralisé, réservation retirée d’`execute()`, et retour à la suppression du fichier à la libération (6 inodes distincts en 6 manches).
- **Limites.** Le poste n’a ni WSL ni Docker : la branche Linux (`fcntl.flock`) n’a pas été exécutée localement. La CI ajoute un job `posix-execution-claim` (Ubuntu 24.04, CPython 3.14.4), qui lance `tests.test_g2_atomic_execution_claim`, à côté des jobs Windows inchangés ; son résultat fera foi pour l’exigence V-2 (section 9) sur ce mécanisme. La portée est d’une machine et d’un dossier d’état local ; `flock` n’est pas fiable sur un système de fichiers réseau. Les verrous `O_CREAT | O_EXCL` du registre et de `FileCriticalSectionLock` ne changent pas.

Aucun appel réel Higgsfield, jeton réel, secret, génération ou déploiement n’a été utilisé. `Provider = CLOSED` et `NO-GO` restent en vigueur.

### G2 — vérificateur d’assertions WebAuthn mock-only (18 octobre 2026)

Ajout de `approval_service/approval_service/webauthn_verifier.py`. `WebAuthnVerifier.verify()` vérifie une seule assertion (`AuthenticationResponseJSON`, sous forme de dictionnaire) contre un `ApprovalStatement` existant ; le défi attendu est celui que calcule `ApprovalStatement.webauthn_challenge()`. Les identifiants enregistrés et l’horloge (Unix, en millisecondes) sont injectés. Aucune dépendance n’est ajoutée : `pyproject.toml` et `uv.lock` sont inchangés, et le module utilise l’API de `fido2` 2.2.1 verrouillée.

- **Identifiants (D-3).** Le résolveur renvoie un `RegisteredCredential` : `AttestedCredentialData` de `fido2`, `approver_id`, user handle, BE relevé à l’inscription et révocation explicite, sans valeur par défaut. Le refus est la règle : identifiant inconnu, révoqué ou rattaché à un autre approbateur que `approver_id` de l’énoncé, user handle discordant lorsqu’il est présent, erreur du résolveur ou enregistrement d’un autre identifiant. Seuls les algorithmes COSE ES256, EdDSA et RS256 sont acceptés ; RS1 (SHA-1) et les autres sont refusés. Pour RS256, une limite est appliquée : toute clé dont le module RSA fait moins de 2 048 bits est refusée, de même que toute clé dont la taille ne peut pas être déterminée (module ou exposant absent ou non binaire, ou nombres refusés par `cryptography`). `fido2` 2.2.1 n’offre pas d’accesseur de taille : `RS256.verify()` reconstruit la clé à partir des labels COSE -1 (n) et -2 (e) avec `rsa.RSAPublicNumbers(...).public_key()`. Le vérificateur fait la même reconstruction et lit `key_size` dans `cryptography`, déjà présent dans le verrou. Cette liste d’algorithmes reste provisoire : elle a été choisie pour cette brique et doit être confirmée avant toute inscription réelle.
- **Contrôles explicites (section 4.4).** Type d’identifiant `public-key`, `type = webauthn.get`, origine strictement égale à `https://zephyr-approval.fr`, `crossOrigin` absent ou `false` et `topOrigin` absent, défi égal à celui de l’énoncé (comparaison en temps constant), `rpIdHash` du RP ID configuré, UP et UV. Pour D-4, BE doit être identique à celui de l’inscription et BS=1 est refusé lorsque BE=0. La configuration n’accepte que le RP ID de l’énoncé et son origine HTTPS exacte. Le contrôle d’origine par défaut de `fido2` accepterait aussi les sous-domaines et `http://localhost` ; il est remplacé par une égalité stricte.
- **Signature.** Elle est vérifiée par `Fido2Server.authenticate_begin()` puis `authenticate_complete()`, avec `user_verification=required` et le défi de l’énoncé ; `fido2` délègue la vérification à `cryptography`. Aucune cryptographie n’est implémentée dans le dépôt. `fido2` refait aussi les contrôles de type, d’origine, de défi, de RP ID, de UP et de UV, mais pas ceux de `crossOrigin` ni de BE/BS : ces derniers ne reposent que sur les contrôles explicites ci-dessus.
- **Délais (D-8).** L’horloge est lue après la vérification cryptographique. L’assertion est refusée si l’instant est antérieur à `issued_at`, atteint ou dépasse `approval_deadline`, ou atteint ou dépasse `expires_at`. Une horloge en erreur ou une valeur non entière positive entraînent aussi un refus.
- **Résultat.** `VerifiedApprovalAssertion` est figé et limité à `approval_id`, `statement_sha256`, `approver_id`, `credential_id`, `authorized_at`, `expires_at`, `sign_count` et `backup_state`. `expires_at` est celui de l’énoncé ; comme `issued_at <= authorized_at`, il ne dépasse jamais `authorized_at + 300 s`. `sign_count` et `backup_state` ne sont renvoyés que pour le futur stockage et ne sont pas évalués au-delà des règles BE/BS. Les messages d’erreur sont fixes et ne reprennent ni l’assertion ni l’énoncé. Le résultat atteste qu’un détenteur d’identifiant enregistré a signé ce défi avec UP et UV ; il n’établit pas l’identité civile de l’approbateur et ne vaut ni consommation ni autorisation.

**Ce que prouvent les tests.** `tests/test_g2_webauthn_verifier.py` comprend 23 tests. Les clés P-256, Ed25519 et RSA 2048 sont générées localement. Le test joue le rôle de l’authentificateur : il signe `authenticatorData || SHA-256(clientDataJSON)` avec `cryptography`, construit la réponse avec les classes de `fido2`, puis la fait passer par JSON.

- Cas acceptés : ES256, EdDSA et RS256 ; `crossOrigin` absent ; absence de user handle ; BE/BS valant (0,0), (1,0) et (1,1).
- **Signature :** autre clé, données d’authentificateur ou données client modifiées après signature, signature tronquée ou vide. La même signature est d’abord acceptée sans modification, ce qui sert de témoin positif.
- **Défi :** défi d’un autre énoncé, défi aléatoire ou tronqué. La même assertion reste acceptée pour l’énoncé qu’elle signe.
- **Origine et RP ID :** autre domaine, sous-domaine, `http`, port explicite, barre oblique finale, `localhost` ou valeur nulle ; quatre RP ID étrangers ; configuration d’un autre RP ID ou d’une autre origine.
- **Type :** cinq valeurs de `type` autres que `webauthn.get` ; type d’identifiant absent, nul ou différent de `public-key`.
- **`crossOrigin` :** `true`, `"false"`, `0`, `null`, ou présence de `topOrigin`.
- **UP/UV :** UP absent, UV absent, aucun des deux.
- **Identifiant :** inconnu, révoqué, rattaché à un autre approbateur, user handle discordant, résolveur en erreur, sans résultat ou renvoyant un autre identifiant ; algorithme RS1.
- **Taille des clés RS256 :** clés de 1 024 et 2 047 bits, pourtant valides et signant correctement, refusées ; une clé de 2 048 bits est acceptée avec la même assertion. Quatre clés de taille indéterminable sont refusées : module absent, exposant absent, module encodé en texte, exposant refusé par `cryptography`.
- **BE/BS :** quatre changements de BE par rapport à l’inscription, et BS sans BE.
- **Expiration :** avant `issued_at`, à `expires_at` ou après, à `approval_deadline` ou après ; le dernier instant valide est accepté. Six horloges invalides ou en erreur sont refusées.
- **Données mal formées :** onze formes de réponse mal formée, ainsi qu’un énoncé absent ou passé sous forme de dictionnaire.

Chaque refus est identifié par son propre message : un test ne réussit pas parce qu’un autre contrôle aurait refusé avant. Vingt-quatre mutations temporaires font échouer le module de tests. Elles neutralisent chacun des contrôles ci-dessus, sautent la vérification de signature ou rétablissent le contrôle d’origine par défaut de `fido2`. Pour RS256, elles suppriment la limite, acceptent une taille indéterminable ou refusent aussi 2 048 bits. Après ces essais, le fichier a été restauré à l’identique, octet pour octet. Un dernier test vérifie que deux vérifications de la même assertion donnent le même résultat : le module ne détecte pas le rejeu.

**Vérifications exécutées.** Elles ont été lancées avec le CPython 3.14.5 Windows du poste. Les dépendances verrouillées ont été installées hors du dépôt, dans un dossier temporaire, par `uv export --locked` (uv 0.13.1) puis `pip install --require-hashes --no-deps --target`, comme dans le job CI ; rien n’a été installé dans le Python système. Résultats : les quatre modules G2 de `approval_service` (49 tests) réussissent ; la suite complète `python -m unittest discover -s tests -t .` réussit (3 041 tests, aucun échec ni test ignoré) ; `python scripts/architecture_audit.py` donne `NO_DRIFT`. Aucun workflow n’est modifié : le job `tests` installe déjà les dépendances verrouillées dans le Python système et découvre `tests/`.

**Limites restantes.**

- Aucun authentificateur ni navigateur réel n’a été utilisé, et aucune inscription n’est implémentée. L’invitation SSH (D-2), l’exigence de deux identifiants dont un secours `BE=0` (D-3) et l’enregistrement de BE relèvent de l’inscription. Le résolveur est un double de test et ne constitue pas un stockage.
- L’usage unique, l’état `PENDING`, la consommation, la journalisation, la mise à jour de BS et la politique du compteur de signatures, qui n’est pas décidée, relèvent du futur stockage transactionnel. Ce module accepte deux fois la même assertion.
- La séparation D-5 entre l’approbateur et l’acteur GitHub du run n’est pas établie : rien ne relie `approver_id` à un compte GitHub. Ce contrôle reste à faire dans la couche de demande, avec l’identité vérifiée par OIDC.
- UV, BE et BS sont déclarés par l’authentificateur ; aucune attestation AAGUID n’est exigée, conformément à D-4. WebAuthn ne prouve ni l’identité civile, ni que l’humain a lu l’énoncé (section 5).
- RP ID et origine sont fixés sur `zephyr-approval.fr` : aucun essai `localhost` n’est possible avec cette configuration.
- La liste ES256, EdDSA et RS256, avec la limite RS256 de 2 048 bits, reste provisoire. Elle doit être confirmée avant l’inscription réelle, en même temps que les paramètres `pubKeyCredParams` qui seront proposés aux authentificateurs.
- Comme les tests OIDC, ce module n’est exécuté en CI que sous Windows. Le job Ubuntu se limite à l’installation verrouillée et aux tests de réservation ; la validation Linux complète exigée par D-16 reste ouverte.

Aucun serveur HTTP, stockage durable, récupération JWKS, jeton OIDC réel, réseau applicatif, secret, compte Higgsfield, génération ou déploiement n’a été utilisé. `Provider = CLOSED` et `NO-GO` restent en vigueur.

### G2 — registre durable des approbations WebAuthn (18 octobre 2026)

Ajout de `approval_service/approval_service/approval_store.py`, un registre SQLite de la bibliothèque standard. Aucune dépendance n’est ajoutée : `pyproject.toml` et `uv.lock` sont inchangés. Le registre expose seulement `initialize`, `create_request`, `approve`, `expire_request` et `revoke_credential`. Il ne consomme aucune approbation, n’est pas relié au Gate, n’inscrit aucun identifiant et n’appelle aucun fournisseur.

- **Initialisation et ouverture.** `initialize()` crée un fichier neuf (création exclusive, mode 0600), le passe en WAL et pose le schéma version 1 (`application_id`, `user_version`). Les tables sont STRICT : métadonnées (dernier instant observé), identifiants, demandes et journal. Un fichier existant est refusé. Chaque opération ouvre sa propre connexion en `mode=rw`, qui ne crée jamais de fichier. Elle refuse auparavant un chemin relatif, une base absente, un lien symbolique, un fichier non régulier et, sous POSIX, un fichier, un `-wal`, un `-shm` ou un répertoire qui ne sont pas privés au compte (aucun droit pour le groupe ni les autres). Elle vérifie ensuite `application_id`, `user_version`, `journal_mode=wal`, `synchronous=FULL` et `foreign_keys=ON` (posés puis relus), le délai d’attente, l’absence de violation de clé étrangère et l’égalité exacte des tables, index et déclencheurs avec le schéma version 1. SQLite 3.37 au moins est exigé pour les tables STRICT.
- **`SQLITE_BUSY`.** Le délai d’attente est borné : 5 secondes par défaut, réglable au-dessus de 0 et jusqu’à 30 secondes. Toute écriture commence par `BEGIN IMMEDIATE` : un concurrent attend le détenteur au lieu d’échouer sur un instantané périmé. Au-delà du délai, `ApprovalStoreBusyError` est levée sans aucune modification. Un `COMMIT` en échec est signalé comme une issue à relire avant tout nouvel essai.
- **Demande et énoncé.** `create_request()` enregistre un seul énoncé immuable par demande, sous forme d’octets canoniques avec leur empreinte. `approval_id`, `request_id`, `authorization_id`, le nonce et le couple (`run_id`, `run_attempt`) sont uniques. Aucune réémission n’est possible, et un énoncé déjà expiré est refusé.
- **Approbation.** Dans une transaction `BEGIN IMMEDIATE`, `approve()` relit l’énoncé stocké, le reconstruit et vérifie ses octets canoniques, son empreinte et les colonnes associées. Elle contrôle ensuite l’état `PENDING`, l’échéance E = min(`approval_deadline`, `expires_at`) et l’horloge, puis l’assertion avec le vérificateur WebAuthn existant. Celui-ci lit les identifiants dans la même transaction et exige un identifiant actif de l’approbateur attendu. En cas de succès, la même transaction écrit l’état `APPROVED`, le compteur, BS, le dernier instant observé et l’entrée de journal. Toute erreur annule l’ensemble.
- **Expiration.** Dès l’instant E, aucune approbation n’est possible. L’état `EXPIRED` est écrit dans une transaction distincte, validée après le rollback de l’approbation, et jamais annulée par lui. Si cette écriture échoue, le refus demeure : la demande reste `PENDING` en base, mais ne peut toujours pas être approuvée. `expire_request()` fait la même transition sur demande et ne touche pas aux demandes `APPROVED`.
- **Compteurs.** La valeur 0 suivie de 0 est acceptée. Si l’une des deux valeurs est non nulle et que la nouvelle est inférieure ou égale à l’ancienne, l’approbation est refusée et la demande reste `PENDING`. C’est un signal, pas une preuve de clonage : une réinitialisation, un défaut de l’authentificateur ou une assertion plus ancienne validée après une plus récente produisent le même écart. L’ordre retenu est celui des validations. Le signal est consigné au plus une fois par couple demande/identifiant, dans une transaction distincte, avec l’empreinte SHA-256 de l’identifiant et les deux valeurs, sans assertion. Il n’entraîne ni révocation ni fermeture automatique.
- **BE/BS et révocation.** BE est immuable ; BS suit la dernière assertion acceptée. `revoke_credential()` est définitive et fait passer dans la même transaction les demandes encore `APPROVED` par cet identifiant à `REVOKED`. Un recul d’horloge ne bloque pas une révocation, qui enregistre alors le dernier instant observé.
- **Horloge.** Le dernier instant observé est conservé. Un recul est refusé sans écriture, y compris pendant la vérification de l’assertion.
- **Protections du schéma.** Des déclencheurs refusent les transitions non prévues, toute suppression, la modification de l’énoncé, de l’identité d’un identifiant ou de BE, le recul ou la répétition d’un compteur non nul, la réactivation d’un identifiant et toute réécriture du journal. Ce sont des conventions renforcées : un processus qui peut écrire le fichier peut les contourner (§4.9).
- **Identifiants de test.** Aucune méthode, commande ni voie d’inscription n’existe. Les tests insèrent leurs identifiants synthétiques directement dans leurs bases temporaires.
- **D-5 non résolu.** Aucun acteur GitHub n’est enregistré ni vérifié. Un état `APPROVED` n’autorise rien, et aucune future consommation n’est autorisée tant que D-5 n’est pas résolu par un contrat d’identité confirmé.

**Ce que prouvent les tests.** `tests/test_g2_approval_store.py` comprend 46 tests. Les clés P-256 sont générées localement et les assertions construites avec les classes de `fido2`.

- **Approbation et rejeu :** approbation nominale ; rejeu de la même assertion refusé, même avec un compteur à 0 ; assertion d’une autre demande ; signature invalide ; identifiants d’approbation inconnus ou mal formés ; doublons d’énoncé.
- **Intégrité de l’énoncé :** énoncé altéré, empreinte altérée, colonne divergente, contenu non JSON. Une réécriture cohérente de l’énoncé, empreinte comprise, ne permet pas de réutiliser l’assertion signée.
- **Compteurs :** 0 suivi de 0, progression, valeurs égales, inférieures ou nulles, assertion arrivée dans le désordre puis nouvelle assertion acceptée, signal unique par demande et identifiant.
- **Expiration :** échéance de l’énoncé et échéance d’approbation ; expiration détectée par le vérificateur puis validée séparément ; échec de l’écriture d’expiration ; `expire_request()`.
- **Révocation et transitions :** révocation définitive avec cascade ; quinze transitions ou modifications refusées par le schéma.
- **Horloge :** recul avant et pendant la vérification ; horloges invalides.
- **Ouverture :** base absente (jamais recréée), fichier existant, chemin relatif, lien symbolique, permissions POSIX, identifiant d’application, version, mode de journal, objets du schéma, fichier non SQLite, violation de clé étrangère, version de SQLite.
- **Échecs SQLite :** `SQLITE_BUSY` borné sans modification ; échec du journal qui annule toute l’approbation ; base en lecture seule.
- **Contention :** quatre processus et huit threads, avec une seule approbation retenue. Avec les threads, chaque perdant reçoit le refus « non `PENDING` ».
- **Arrêt brutal :** processus tué avant le `COMMIT` (la demande reste `PENDING`, `integrity_check` est sain et l’approbation reste possible) ou après (l’approbation est conservée et le rejeu refusé).
- **Périmètre :** seules les cinq opérations sont publiques ; le module ne contient aucune insertion d’identifiant ; le schéma ne contient aucun acteur ; le journal ne contient ni identifiant brut ni élément d’assertion.

Vingt-deux mutations temporaires ont neutralisé tour à tour chacune de ces règles. Vingt et une ont fait échouer le module dès le premier essai. La vingt-deuxième remplaçait `BEGIN IMMEDIATE` par un `BEGIN` différé ; le test des threads exige depuis que chaque perdant reçoive le refus « non `PENDING` », et cette mutation échoue désormais à chaque essai (trois sur trois). Le fichier a été restauré à l’identique, octet pour octet.

**CI.** Un nouveau job `posix-approval-store` s’exécute sur Ubuntu 24.04 avec CPython 3.14.4, les actions épinglées et `persist-credentials: false`. Il installe uv 0.13.1, exporte le verrou par `uv export --locked`, installe les dépendances par `pip install --require-hashes --no-deps` dans le Python système, puis lance `python -m unittest tests.test_g2_approval_store -v`. Les jobs `posix-execution-claim` et `tests` sont inchangés. `tests/test_phase_f_production_path.py` vérifie la structure exacte de ce job et la liste des jobs. Les deux tests propres à POSIX (lien symbolique et permissions) ne s’exécutent que dans ce job.

**Vérifications exécutées.** Elles ont été lancées avec le CPython 3.14.5 Windows du poste, avec les dépendances verrouillées installées dans un dossier temporaire hors du dépôt.

- Registre : 46 tests réussis, dont deux ignorés sous Windows (lien symbolique sans privilège, permissions POSIX).
- Avec les autres modules G2 et les tests de structure CI : 158 tests réussis.
- Suite complète (`python -m unittest discover -s tests -t .`) : 3 088 tests réussis, dont deux ignorés (les deux tests propres à POSIX).
- Audit d’architecture : `NO_DRIFT`.
- `git diff --check` : propre.

Le job Ubuntu n’a pas pu être exécuté localement, faute de WSL et de Docker : son résultat sur GitHub Actions fera foi.

**Limites restantes.**

- **Durabilité :** `synchronous=FULL` ne couvre pas le stockage de l’hébergeur. Aucune coupure de machine n’a été testée (X4). La synchronisation du répertoire à la création reste à vérifier sous Linux (V-3).
- **Restauration :** sans ancre externe J-c, une restauration ancienne n’est pas détectée (§3.4).
- **Fichier :**
  - système de fichiers local uniquement ; NFS, SMB et dossiers synchronisés ne sont ni pris en charge ni détectés ;
  - la base, son `-wal` et son `-shm` ne doivent jamais être ouverts, copiés ou supprimés hors de `sqlite3` pendant le fonctionnement ;
  - un remplacement du fichier entre le contrôle du lien symbolique et l’ouverture par SQLite n’est pas couvert ;
  - les permissions Windows ne sont pas contrôlées ;
  - le chemin de production `/srv/ai-director-data` n’est pas créé.
- **Schéma :** aucune migration n’existe et toute autre version est refusée. Une future version exigera une étape explicite, précédée d’une sauvegarde.
- **Journal :** il n’est ni chaîné ni ancré. Seuls l’expiration et le signal de compteur sont consignés parmi les refus.
- **Hors périmètre :** consommation `APPROVED → CONSUMED`, interrupteur D-9, emplacement D-17, reçu D-18, intégration au Gate, inscription réelle (D-2, D-3) et serveur HTTP.
- **D-5 :** non résolu, comme indiqué plus haut.

Aucun secret, authentificateur réel, jeton, appel Higgsfield, génération ou déploiement n’a été utilisé. `Provider = CLOSED` et `NO-GO` restent en vigueur.
