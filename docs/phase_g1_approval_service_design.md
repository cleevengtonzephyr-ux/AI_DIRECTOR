# Phase G1 — Conception du service d'approbation humaine

- **Date :** 2026-10-08
- **Référence :** `main` à `f687973568d787e2b2e0051a4632cbbe962de94b` (fusion de la PR #6, Phase F)
- **Statut :** document de conception, corrigé après des revues de sécurité en lecture seule. D-1 reprend une instruction explicite du propriétaire ; D-2 à D-13 sont choisies sous sa délégation explicite des 2026-10-07 et 2026-10-08 ; D-14 est explicitement reportée sans fixer de montant. Les autres décisions ouvertes restent à trancher. Ce document n'implémente rien, n'autorise rien et ne déploie rien.

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
| **Ouvert** | Forme de la réponse du service et sa vérification par le Director | Section 4.11, décision D-18 |
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

- version de l'énoncé et identifiant de la Relying Party ;
- `repository_id`, `repository`, `sha`, `workflow_ref`, `run_id`, `run_attempt` (issus du jeton vérifié) ;
- `manifest_sha256` (modèle, paramètres vidéo et empreintes des médias, Phase F) ;
- `approval_id` et nonce, choisis par le service. `approval_id` doit respecter le format accepté par le script de Phase F (`[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`) ;
- `requested_at` (création de la demande), `approval_deadline` (= `requested_at` + 600 secondes) et `validity_seconds` (= 300 secondes, D-8) ;
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

**Exigences X1 à X8**

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
| D-13 | **Choix de conception conditionnel sous délégation le 2026-10-08 — PyJWT et python-fido2** | PyJWT avec l'extra `[crypto]` est retenu pour signature JWT/JWKS OIDC ; `python-fido2` est retenu pour la vérification WebAuthn côté serveur. Pas d'implémentation cryptographique maison ni d'extra PC/SC. Les versions directes et transitives exactes, empreintes de verrouillage, compatibilité Python, licences/avis de sécurité et procédure de mise à jour doivent être établies et revues en G2. Le paquetage n'est ni installé ni créé par cette décision ; R-1 ou l'option (iii) de D-18 peut nécessiter une dépendance de signature distincte |
| D-14 | **Report explicite sous délégation le 2026-10-08 — aucun montant ni dépense de génération autorisés** | Aucun plafond de crédits par requête ou par période n'est fixé. L'objectif budgétaire de 50 €/mois TTC porte sur les coûts récurrents d'infrastructure et ne constitue pas un plafond Higgsfield. Tant que le plafond par requête reste absent ou que le coût vaut `UNKNOWN`, toute demande est refusée, aucun crédit ne peut être consommé, et Provider reste CLOSED. La condition 3 de la Phase A demeure non satisfaite ; une éventuelle réévaluation du NO-GO exigera une décision ultérieure distincte fixant des limites numériques et leur périmètre. Ce report ne fixe aucun montant |
| D-15 | **Choix de conception conditionnel sous délégation le 2026-10-08 — protection des comptes et des accès** | MFA résistante à l'hameçonnage lorsque disponible, récupération protégée, comptes nominatifs et moindre privilège ; règles GitHub `main` avec PR, CI, blocage des force-push/suppressions et contournement administrateur désactivé lorsque possible ; Actions épinglées à des SHA complets ; MFA/IAM et alertes Scaleway (alertes non assimilées à un plafond) ; MFA, verrou et récupération DNS à vérifier ; inventaire puis révocation des voies Higgsfield de génération hors courtier avant tout usage réel. État actuel non vérifié ; aucune configuration ni clé modifiée ou consultée |
| D-16 | **Choix de conception conditionnel sous délégation le 2026-10-09 — CPython 3.14.4 comme cible Linux G2 ; CI Windows 3.14.5 maintenue** | Pas de mise à niveau du serveur dans cette décision. La compatibilité des dépendances verrouillées avec 3.14.4 doit être établie en G2 ; si elle échoue, D-16 est réexaminée. La validation Linux complète et l'audit d'architecture restent obligatoires avant toute mise en service. Version rapportée, non vérifiée indépendamment |
| D-17 | **Choix de conception conditionnel sous délégation le 2026-10-09 — exécution sérialisée et nouvelle approbation à chaque essai** | Un seul emplacement global d'exécution, occupé tant qu'une demande est active ou qu'une issue fournisseur n'est pas résolue. Un même manifeste peut être soumis de nouveau seulement après résolution définitive, avec nouvelle demande/assertion, nouvel `approval_id` et nouvelle clé d'idempotence ; `ACCEPTED` ne libère pas l'emplacement avant résolution du job, `AMBIGUOUS` bloque. `NOT_SENT` est terminal et toute reprise exige une nouvelle approbation. Le statut fournisseur n'est pas supposé vérifiable automatiquement |
| D-18 | Réponse du service et vérification par le Director | R-1, R-2 (R-3 écartée), section 4.11 ; couverture de L2, L3 et L7 |

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
5. **Campagne Linux** de la section 9 (V-1 à V-3, X1 à X8), avec procès-verbal consigné. Déployer du code, même de test, sur le serveur exige une **autorisation explicite et distincte du propriétaire**, sans ouverture de port.
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

- Aucune modification de code, de workflow, de test, de verrou, de configuration serveur, de réglage GitHub ou de DNS.
- Aucun secret ni aucune clé créé ou lu ; aucun logiciel installé ; aucun port ouvert ; aucun déploiement.
- Aucun appel à Higgsfield ; aucun workflow lancé ; aucun appel à `create_job()`.
- Aucune option choisie sans instruction ou délégation explicite du propriétaire ; aucun montant de plafond fixé ; aucun essai de la section 9 exécuté.
- Les conditions 1, 3, 5 et 7 de la Phase A restent **ouvertes**, la condition 2 reste **partiellement traitée**, et le **NO-GO** reste en vigueur.

**Provider = CLOSED · Real generation = 0 · Credits = 0**
