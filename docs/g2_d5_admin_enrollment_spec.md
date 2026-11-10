# G2 D-5 — Spécification de conception : administration des inscriptions v5 en attente (option A-1)

> **Statut : brouillon de spécification, non implémenté.** Ce document s’appuie sur une analyse en lecture seule de la frontière SSH (24 octobre 2026), qui n’est pas archivée dans le dépôt. **Le propriétaire a adopté le 25 octobre 2026 l’option A-1 comme orientation de conception** pour confirmer les inscriptions D-5 `PENDING`, dans la portée exacte décrite au §3 et au §4. **Le même jour, il a tranché T-3, puis l’a complété** : `root` possède et contrôle en écriture tout ce qui peut changer l’application ou son autorisation (CLI d’administration, stockage, vérifications V0/V1/E, chemin d’approbation et de consommation, dépendances d’exécution, configuration et lancement du service, fichier de confiance). `aidirector` peut les lire et les exécuter, sans pouvoir les modifier ni les remplacer ; les fichiers SQLite restent au compte de service (§3, §9.2). Les détails de mise en œuvre restent ouverts. **Il a aussi tranché T-1** : le propriétaire, unique administrateur, peut rouvrir l’interrupteur D-9 par SSH avec une assertion WebAuthn fraîche et UV de son credential d’administration ; B reste approbatrice uniquement ; cette action n’autorise jamais le propriétaire à approuver une demande de génération (§3, §3.1, §7.1). Cette décision modifie la règle historique de G1 §4.8. **L’alignement de G1 est commité dans `73737dd` et fusionné dans `main` par le PR #62 (`6313648`)** (§3.1). **Il a enfin retenu l’option O-3 pour le RP ID d’administration** : RP ID `ai-director-admin.invalid`, origine déclarée par le client CTAP local `https://ai-director-admin.invalid`, fixes pendant toute la vie des credentials d’administration. La compatibilité réelle avec Windows, CTAP et le modèle de clé reste à vérifier, et aucun essai avec une vraie clé n’est autorisé (§5.1). **Il a aussi tranché l’orientation générale des credentials d’administration** : deux clés matérielles distinctes, principale et secours ; UV obligatoire ; `BE=0` requis ; une seule clé suffisant aux opérations courantes. Il a ensuite fixé les **règles de la cérémonie de genèse initiale** : une seule fois, hors du service web, système fermé ; réponses d’inscription validées ; installation `root` refusée si un fichier existe déjà ; échec fermé (§5.2.2). Il a retenu enfin, pour le cycle de vie des défis, C-1 (défis en mémoire d’une seule invocation `root`, sans reprise) et O-a (aucun orphelin approuvé) (§5.2.5). Il a retenu enfin, comme orientation d’attestation, une attestation vérifiable contre une racine approuvée et une liste fermée d’AAGUID, le refus de `none` sans déclassement silencieux, la preuve de possession séparée et l’absence d’attestation `enterprise` à ce stade (§5.2.6). **Le 26 octobre 2026, il a tranché neuf orientations sur le cycle de vie de cette attestation** (§5.2.7, M) :
> - ancres de confiance selon R-c, ou R-b après approbation hors bande ;
> - métadonnées selon M-2, documentées comme une adaptation de MDS §3.2 dont la conformité stricte n’est pas établie, sans accès réseau du serveur ;
> - refus de `x5u` ;
> - liste fermée AAGUID–ancre–format ;
> - contrôles de fraîcheur et de révocation à la genèse et à chaque import ;
> - suspension après la genèse ;
> - deux modèles différents recommandés ;
> - validation X.509 éprouvée ;
> - journalisation et ancrage.
>
> **Le 26 octobre 2026 également, il a fixé la liaison des énoncés signés à la reprise de suspension et le champ qui la porte** (§5.3, §5.5.1, §11.2 ; §14, point 21) :
> - pour les opérations ordinaires qui ouvrent (opérations 1 à 4 du §11.2), l’énoncé signé contient toujours le champ `effective_resume_entry_hash` : l’`entry_hash` de la dernière reprise de suspension effective et ancrée, en 64 caractères hexadécimaux minuscules, ou `null` explicite avant toute reprise effective, sans séquence supplémentaire ; ce champ appartient aux octets canoniques, et le défi le couvre ;
> - V0 compare cette valeur à la reprise effective courante au moment de l’`apply` ;
> - V1 et E vérifient la signature de l’énoncé sans comparer son identifiant à une reprise ultérieure ; E applique toujours la politique et la suspension courantes.
>
> La création d’une invitation devra suivre la même règle lorsque son protocole signé sera conçu. Seuls ces points sont décidés. Le reste de V0, V1 et E demeure une recommandation [R], hormis les règles déjà consignées sur le sort du nonce (§14, point 21), sur le contrôle de la politique d’attestation (§5.2.7, M.6), sur le compteur d’administration, sur les statuts des clés et sur la liaison à l’autorisation effective de la clé signataire (ci-dessous).
>
> **Le même jour, il a retenu l’option (b), signal seulement, pour le compteur `signCount` des credentials d’administration** (§5.5.4 ; §14, point 8) :
> - `0` suivi de `0` : aucune anomalie ; si l’une des deux valeurs est non nulle et que la nouvelle est inférieure ou égale à la précédente : signal borné, sans refus pour ce seul motif ;
> - la nouvelle valeur est enregistrée à chaque opération acceptée, y compris après un signal ;
> - le signal ne fait pas passer le nonce à `FAILED` et ne bloque pas l’effet si les autres contrôles réussissent ;
> - il n’est pas une preuve de clonage, ne change pas automatiquement le statut du credential et ne suspend pas le service.
>
> Les détails du signal borné et la valeur initiale du compteur après la genèse restent ouverts [O].
>
> **Le même jour, il a fixé les statuts des clés d’administration** (§5.5.3 ; §14, point 9) :
> - `ACTIVE` : autorisé en V0 et vérifiable en V1 ;
> - `RETIRED` : refusé en V0 ; les confirmations antérieures au retrait, selon l’ordre des entrées de journal ancrées, restent vérifiables en V1 ;
> - `COMPROMISED` : refusé en V0 et en V1 ; aucune de ses confirmations n’est utilisable, quelle que soit sa date ;
> - une anomalie `signCount` ne change jamais un statut ; tout changement de statut est explicite, authentifié, journalisé et ancré ;
> - une fois une clé marquée `COMPROMISED`, aucune opération qui ouvre signée par elle ne peut fonder une autorisation future ; ses effets futurs sont refusés ou recalculés comme inactifs, sans modification rétroactive ; les opérations qui ferment restent applicables ; sans clé `ACTIVE` permettant d’établir un état valide, le système reste fermé ;
> - un marquage survenu avant l’ancrage d’une entrée que la clé a signée ne mène pas à S4 à lui seul : l’entrée peut être ancrée pour l’audit, sans effet futur, l’ordre étant établi par le journal ;
> - une clé ajoutée par une clé ultérieurement `COMPROMISED` garde son enregistrement et son statut, mais n’autorise aucune opération future tant qu’une clé `ACTIVE` ne l’a pas réautorisée ;
> - cette réautorisation est explicite, authentifiée, journalisée et ancrée ; elle ne prend effet qu’après l’ancrage requis, pour les opérations futures seulement, sans rendre utilisable ce qui a été signé avant elle ; sans chemin sûr, le système reste fermé.
>
> La procédure de récupération, de perte et de remplacement des clés, la sortie d’un blocage, la désignation de l’entrée de retrait, les mécanismes d’application de la portée de `COMPROMISED` aux opérations autres que la confirmation d’inscription, la distinction sûre des cas lorsque l’opération et le marquage attendent dans la même queue, et le format de la réautorisation d’une clé ajoutée restent ouverts [O].
>
> **Le même jour, il a lié chaque signature administrative à l’autorisation effective de la clé signataire** (§5.3, §5.5.1, §5.5.2, §5.5.3 ; §14, point 9) :
> - chaque énoncé signé lie la signature à l’entrée qui autorise effectivement la clé signataire : genèse initiale, ajout ou réautorisation ;
> - pour une opération qui ouvre, V0 vérifie cette liaison à l’`apply`, d’après la chaîne concordante avec l’ancre relue ; V1 vérifie, pour une confirmation enregistrée, que l’autorisation liée est cohérente avec l’entrée de l’opération et reste valable ;
> - une assertion préparée avant une nouvelle autorisation ne peut pas être appliquée après celle-ci ;
> - une clé dont la chaîne d’ajout dépend d’une clé `COMPROMISED` ne signe plus d’opérations futures tant qu’une réautorisation valide n’a pas été ancrée ;
> - pour une opération signée qui ferme, V0 vérifie le statut `ACTIVE` et compare l’identifiant d’autorisation à l’entrée effective conservée dans le fichier de confiance protégé par `root`, sans relire J-c ni exiger une queue vide. En cas de manque ou d’incohérence, l’opération signée est refusée, et la voie d’urgence D-9 du §7.0 reste disponible dans sa portée décidée (formulation propre à ce refus, qui ne décide pas de sa disponibilité pendant le gel, §5.5.1, cas 3). Validée, la fermeture prend effet au `COMMIT` local, et un échec d’ancrage ultérieur ne la rouvre pas. Le 27 octobre 2026, il a précisé que le statut `ACTIVE` ne suffit pas (ci-dessous).
>
> C’est la valeur signée qui fait preuve, non l’ordre du journal ni une date SQLite. Restent ouverts [O] : le nom du champ, son encodage, la représentation de l’autorisation initiale de genèse et le format des opérations d’ajout et de réautorisation ; pour les fermetures, la représentation de l’entrée d’autorisation dans le fichier de confiance, la preuve qu’elle était déjà effective, sa cohérence avec J-b et J-c et la conduite en cas de divergence ou d’impossibilité d’écrire le journal ; le reflet d’une autorisation invalidée relève de la représentation de la chaîne d’autorisation (ci-dessous).
>
> **Le 27 octobre 2026, il a fixé la validité de la chaîne d’autorisation des opérations signées qui ferment** (§5.5.1, étape 5 ; §5.5.3 ; §7.0 ; §9.2 ; §11.2 ; §14, point 9) :
> - une opération signée qui ferme ne peut être acceptée que si le credential signataire est autorisé et si sa chaîne d’autorisation n’a pas été invalidée ;
> - le statut `ACTIVE` dans le fichier de confiance ne suffit pas à lui seul ;
> - si V0 ne peut pas établir cette validité, il refuse l’opération ;
> - la fermeture acceptée reste effective au `COMMIT` local, sans relecture de J-c ni attente de l’ancrage ;
> - la voie d’urgence D-9 reste distincte et limitée à sa portée déjà décidée ; cette décision ne l’étend pas aux autres opérations qui ferment.
>
> Les autres règles décidées sont inchangées, notamment l’absence de changement automatique des statuts. Restent ouverts [O] : la représentation de la chaîne d’autorisation dans la politique protégée par `root`, la preuve de sa validité, sa cohérence avec le journal et la conduite en cas de divergence.
>
> **Analyse du 27 octobre 2026** (§5.5.5, A à I et K ; §14, point 23). Elle porte sur la représentation et la preuve de cette chaîne, avec une piste [R] de manifeste d’autorisation protégé par `root`. Elle distingue une invalidation connue seulement en base, sans garantie face à un compte de service compromis, d’une invalidation inscrite dans la politique `root`, et elle compare les ordres d’écriture possibles.
>
> **Le même jour, il a pris sept décisions de portée sur l’invalidation des chaînes** (§5.5.5, J ; §14, point 23). Elles précisent cette analyse sans modifier les décisions antérieures sur `RETIRED`, `COMPROMISED`, les nonces ou la portée de D-9 :
> - le `COMMIT` local rend effectives les fermetures ordinaires dans le service intact. Le marquage `COMPROMISED`, transition spéciale de la politique d’autorisation, ne prend effet qu’à l’installation de la nouvelle politique `root` ;
> - une invalidation compte lorsqu’elle est inscrite dans la politique `root`. Un marqueur SQLite peut seulement faire refuser, et la limite d’un marqueur effaçable par un compte de service compromis est acceptée ;
> - le marquage exige une opération `root` contrôlée et une assertion WebAuthn fraîche, avec UV, d’un autre credential d’administration valide dans la politique courante et indépendant du credential visé. SSH ou `sudo` seuls ne suffisent pas. Sans autre credential valide, la récupération relève du §5.8. D-9 n’est pas étendue ;
> - l’événement signé est conservé durablement par `root` avant la mise à jour de la politique. Le service l’inscrit ensuite dans J-b, de façon idempotente, puis il est ancré. `root` n’écrit jamais dans SQLite ;
> - `root` prend une barrière exclusive qui attend la fin des transactions du service, et le service tient cette barrière de la lecture de la politique jusqu’au `COMMIT`. La première transaction visée consigne le marquage avant toute autre entrée signée. Cette coordination n’est pas atomique avec SQLite ;
> - l’ordre n’est garanti que pour des processus qui respectent le protocole. Le refus en V1 des opérations signées par une clé `COMPROMISED`, quelle que soit leur date, est préservé ;
> - seuls les échecs propres à la barrière γ1, survenus avant la vérification de l’assertion, laissent le nonce `ISSUED`. Une impossibilité temporaire d’obtenir la barrière, de lire la politique ou de consigner le marquage est un refus de précondition γ1. Une divergence d’intégrité détectée par cette barrière maintient S4 jusqu’à la résolution, sans écriture de `FAILED`. Le refus 1b pour politique d’attestation suspendue garde sa règle `FAILED`, et les autres étapes de V0 gardent leur sort de nonce déjà décidé.
>
> **Réserve décidée le 29 octobre 2026 [D]** (ci-dessous ; §5.5.5, L.8, point 8) : l’inscription dans J-b, l’ancrage et la consignation prévus ci-dessus ne s’appliquent pas à une génération visible mais non déclarée effective. Le service reste alors fermé et ne l’utilise pas : aucune opération signée, aucune consignation de `c` ni aucun ancrage pour cette génération avant sa déclaration d’effectivité.
>
> **Le même jour, il a fixé la conduite de la barrière** (§5.5.5, L.5 ; §14, point 23) :
> - en temps normal, `root` attend la barrière exclusive. Après un délai borné, il arrête tous les processus du service et empêche leur redémarrage pendant l’installation ;
> - ordre de prise : le service prend G puis B en partagé, relâche G, puis exécute `BEGIN IMMEDIATE`, et garde B jusqu’au `COMMIT` ou au rollback. `root` prend G puis B en exclusif. Entre processus qui respectent le protocole, cet ordre évite les cycles d’attente ;
> - nonce : en cas de refus 1b ou d’échec des étapes 2 à 8, V0 revient à un `SAVEPOINT` pris après `BEGIN IMMEDIATE`. Il passe ensuite le nonce de `ISSUED` à `FAILED` dans la même transaction, sous B, avant le `COMMIT`. Un second `apply` ne peut plus décider sur ce nonce encore `ISSUED`. En cas d’erreur SQLite, l’effet de l’opération est annulé dès que le retour au `SAVEPOINT` a réussi, et seul le sort du nonce reste alors ouvert. Aucun `COMMIT` ne suit un échec de ce retour, et l’absence d’effet n’y est affirmée qu’une fois l’annulation établie, ou déduite sans s’appuyer sur `in_transaction` seul (formulation précisée le 27 octobre 2026, §5.5.1) ;
> - la nouvelle génération n’est déclarée effective qu’après l’obtention de la barrière exclusive et l’installation durable de la politique. Si l’arrêt du service ou l’obtention de B échoue avant R6, aucune nouvelle génération de politique n’est installée et le système reste fermé ;
> - la barrière couvre le contrôle de politique d’E jusqu’à l’enregistrement local de sa décision. La lecture réseau de J-c reste hors barrière. Sous la barrière, E revérifie la génération et refuse en cas de course. Il refuse aussi tant que l’entrée qui consigne la génération courante, initiale comprise, n’est pas incluse dans la tête J-c qu’il vient de relire ;
> - la voie d’urgence D-9 reste hors barrière et limitée à l’interrupteur. Elle peut être temporairement indisponible pendant l’arrêt forcé, durant lequel le service est en échec fermé et rien n’autorise. Elle redevient disponible au redémarrage, même si `c` attend l’ancrage. Ni sa portée ni les conditions d’effectivité des opérations qui ouvrent ne changent.
>
> Cet arrêt forcé n’est pas une atomicité entre SQLite et la politique. La limite face à un compte de service compromis qui contourne le protocole demeure.
>
> Les mécanismes (barrière, arrêt et interdiction de redémarrage, zone d’événements, énoncé de marquage) restent ouverts [O].
>
> **Le même jour, sur instruction du propriétaire, le chemin d’échec SQLite de V0 a été précisé** (§5.5.1, « Erreurs SQLite dans la transaction de V0 » ; §10.3 ; §5.5.5, L ; §14, points 21 et 24). L’option (a) est inchangée : transition conditionnelle vers `FAILED` dans la transaction externe, sans réécriture dans une transaction séparée.
> - après un retour au `SAVEPOINT` réussi, l’effet de l’opération, `c` comprise, est annulé. Si la transition ou le `COMMIT` échoue ensuite, seul le sort du nonce est incertain ;
> - si le retour au `SAVEPOINT` ou l’annulation complète échoue, aucun `COMMIT` ne suit. Le refus est fermé, et l’absence d’effet n’est affirmée qu’une fois l’annulation établie, ou déduite sans s’appuyer sur `in_transaction` seul ;
> - une erreur du `COMMIT` du chemin de succès n’est pas un refus et ne déclenche aucune nouvelle tentative automatique. L’opération n’est tenue pour effective que si son `COMMIT` est établi, et l’état est constaté avant toute nouvelle tentative. B n’est relâchée qu’une fois la transaction résolue, et ni `show` ni une relecture n’établit à lui seul la durabilité ;
> - `SQLITE_BUSY` est distingué des erreurs d’E/S, de mémoire ou de disque plein, qui peuvent annuler la transaction.
>
> Les règles 1a et 1b, γ1, S4, la barrière et D-9 sont inchangées. La récupération et le constat restent des recommandations [R]. Ce qui n’est pas établi par les sources vérifiées est marqué [O] ou [H], notamment la version de SQLite liée sur le serveur, qui reste inconnue.
>
> **Le même jour, il a décidé un gel après une issue indéterminée** (§5.5.1, cas 3 ; §10.3 ; §11.2 ; §11.3 ; §5.5.5, L.7 et L.8 ; §14, point 24) :
> - après une erreur de `COMMIT` dont l’issue est indéterminée, le service refuse les opérations d’approbation jusqu’à une récupération et une vérification explicites ;
> - pendant l’incertitude, aucune nouvelle autorisation d’approbation n’est délivrée et aucune opération qui ouvre n’est acceptée ;
> - la lecture seule à des fins de constat reste possible ;
> - D-9 reste dans sa portée, mais elle écrit dans la même base et n’est donc pas une solution garantie à sa panne.
>
> L’option (a), les règles de nonce, γ1, S4, la barrière B et la portée de D-9 sont inchangées. L’incertitude ne peut pas être enregistrée de façon fiable dans une base SQLite en erreur. Restent ouverts [O] l’enregistrement durable du gel, son maintien après un redémarrage, les critères de récupération et la vérification qui le lève, ainsi que le sort d’une nouvelle tentative après la levée.
>
> **Le même jour, il a étendu ce gel au `COMMIT` d’E** (§5.5.1, cas 3 ; §11.2 ; §10.3 ; §11.3 ; §5.5.5, L.2, L.7 et L.8 ; §14, point 24) :
> - si le `COMMIT` par lequel E enregistre une autorisation a une issue indéterminée, E ne délivre aucune nouvelle autorisation, et le même gel s’applique jusqu’à une récupération et une vérification explicites ;
> - un échec dont le non-`COMMIT` est établi par un `ROLLBACK` réussi ne déclenche pas ce gel, sauf si une règle déjà décidée l’exige ;
> - les règles déjà décidées du gel sont conservées : aucune opération qui ouvre n’est acceptée, et la lecture seule à des fins de constat reste possible.
>
> Le mécanisme qui arme et maintient le gel pour E restait alors à concevoir [O], sans marqueur retenu ; il a été fixé le 28 octobre 2026 (ci-dessous). Restent ouverts, sans changement, les points sur D-9, les opérations signées qui ferment pendant le gel, la validation avant ancrage, l’ancrage, la levée du gel et le sort des nouvelles tentatives après la récupération.
>
> **Le même jour, il a fixé les transactions couvertes par ce gel** (§5.5.1, cas 3, « Transactions couvertes » ; mêmes renvois) :
> - toute transaction V0, qu’elle consigne une opération qui ouvre ou une opération signée qui ferme ;
> - la transaction d’E qui enregistre une autorisation (extension ci-dessus).
>
> Le gel ne vise que l’issue indéterminée d’un `COMMIT` ; un non-`COMMIT` établi par un `ROLLBACK` réussi ne le déclenche pas, sauf si une règle déjà décidée l’exige. Au point a de la résolution, le `ROLLBACK` réussi établit le non-`COMMIT`, et le gel n’y est pas déclenché ; aux points b et c, l’issue est indéterminée et le gel s’applique. Cette décision fixe les catégories couvertes, pas le mécanisme qui arme ou conserve le gel [O]. Restent ouverts [O] : la validation avant ancrage, l’ancrage, la disponibilité de D-9 pendant le gel, le sort des fermetures pendant le gel et la levée du gel.
>
> **Le même jour, il a accepté un gel conservateur** (§5.5.1, cas 3, « Gel conservateur » ; §10.3 ; §11.2 ; §11.3 ; §5.5.5, L.7 et L.8 ; §14, point 24) :
> - tout marqueur encore présent après l’arrêt d’un processus ou une issue non résolue maintient le gel, y compris après un redémarrage ;
> - cela comprend un arrêt avant le `COMMIT`, pendant le `COMMIT`, ou après un `COMMIT` réussi mais avant le retrait du marqueur ;
> - aucun nettoyage automatique ne retire un marqueur, ni au démarrage, ni après un délai, ni d’après la seule visibilité de l’état SQLite ou une simple déduction sur l’issue ;
> - le gel ne prend fin qu’après une récupération, une vérification et une levée explicites.
>
> Règle préservée : un `ROLLBACK` complet réussi et établi, suivi du retrait normal du marqueur, ne déclenche pas le gel ; si le processus s’arrête avant ce retrait, le gel conservateur s’applique. « Marqueur » désigne l’indice que laisse le mécanisme qui arme le gel, fixé le 28 octobre 2026 (ci-dessous). Les détails de ce mécanisme et la procédure de récupération restent ouverts [O], de même que la portée de la remise E7, la disponibilité de D-9 pendant le gel, la validation avant ancrage, l’ancrage et les fermetures pendant le gel.
>
> **Le 28 octobre 2026, il a fixé le mécanisme du marqueur du gel** (§5.5.1, cas 1 et 3, « Mécanisme du marqueur » ; §5.5.5, L.1, L.2, L.7 et L.8 ; §9.2 ; §10.3 ; §11.2 ; §11.3 ; §12 ; §14, point 24) :
> - le gel utilise un marqueur distinct par transaction couverte, sous forme de fichier persistant hors de SQLite ;
> - le marqueur est créé avant les écritures de la transaction ; le service ne le retire qu’après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi ;
> - un `ROLLBACK TO SAVEPOINT` seul ne permet jamais de retirer le marqueur ;
> - un marqueur restant après un arrêt ou une issue indéterminée maintient le gel, sans nettoyage automatique au démarrage ;
> - `root` ne retire un marqueur résiduel qu’après une récupération et une vérification explicites ;
> - la limite déjà établie s’applique : ce mécanisme protège contre les erreurs de processus et de stockage, pas contre un compte de service compromis.
>
> Le gel conservateur et les décisions antérieures sur V0, E, les nonces, γ1, S4, la barrière B et L.5 sont inchangés. Restent à concevoir [O] : l’emplacement, le nommage et le contenu des marqueurs, leurs propriétaires et modes de permission, les moyens de leur persistance, le moment de leur création par rapport à G, B et `BEGIN IMMEDIATE` (fixé ensuite le même jour, ci-dessous), la conduite si leur création ou leur retrait échoue, leur consultation par les autres processus (fixée ensuite sous W, ci-dessous) et la distinction d’un marqueur résiduel, l’opération `root` qui retire un marqueur résiduel et la procédure détaillée de récupération. Rien, dans ce document, n’établit que le système de fichiers empêche un processus du compte de service de supprimer le marqueur d’un autre processus. Restent ouverts, sans être tranchés : la disponibilité de D-9 pendant le gel, la portée de la remise E7, les fermetures pendant le gel, la validation avant ancrage, l’ancrage et les critères détaillés de levée.
>
> **Le même jour, il a adopté le verrou W et l’ordre de prise des transactions couvertes** (§5.5.1, précondition γ1 et cas 3, « Mécanisme du marqueur » ; §5.5.5, L.1, L.2, L.4, L.7 et L.8 ; §9.2 ; §10.3 ; §11.2 ; §11.3 ; §12 ; §14, point 24) :
> - W est un verrou exclusif qui sérialise les transactions couvertes, V0 et E ; elles le prennent avant G ;
> - sous W, elles examinent les marqueurs existants. Pour E et les opérations qui ouvrent, un marqueur résiduel entraîne un refus sans écriture ; la qualification du refus et le sort du nonce restent ouverts [O] ;
> - après cette vérification, l’ordre existant reste intact : G en partagé, B en partagé, relâchement de G, puis `BEGIN IMMEDIATE` ;
> - V0 prend ensuite le `SAVEPOINT`, puis crée son marqueur avant toute écriture de la transaction, donc avant les étapes S4 et S5 de L.2 et toute consignation de `c`. E crée le sien après `BEGIN IMMEDIATE` et avant toute écriture, donc avant E3 à E6 ;
> - W est gardé pendant la transaction, jusqu’à sa résolution sur la connexion. Après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi, le service peut tenter de retirer son marqueur avant de relâcher les verrous, jamais après le seul retour au `SAVEPOINT` ;
> - une fois la transaction résolue, le service relâche B, puis W. Si le retrait échoue et que le marqueur reste présent, ou s’il n’est pas tenté, le marqueur résiduel maintient le gel. Une suppression visible dont seule la synchronisation du répertoire échoue ou reste incertaine ne maintient pas, à elle seule, le gel pendant que le système tourne (les autres marqueurs résiduels, s’il y en a, continuent de le maintenir et de provoquer les refus prévus) ; le marqueur peut réapparaître après une coupure ou un redémarrage. Si l’issue du `COMMIT` est indéterminée, le service ne tente pas le retrait ; le marqueur reste en place et maintient le gel jusqu’à une levée explicite par `root`.
>
> La libération de W à la fin du processus est une hypothèse à vérifier [H]. W ne protège pas contre un compte de service compromis, et rien n’établit que le système de fichiers empêche ce compte de supprimer les marqueurs d’autres processus. Restent ouverts [O] : le mécanisme et l’équité de W, les délais, l’emplacement et les permissions des fichiers, la durabilité effective, l’échec de création, les détails techniques du retrait, le code du refus, la procédure de récupération et l’identification des marqueurs résiduels. Ne sont pas tranchés : la conduite des fermetures signées pendant le gel, y compris en présence d’un marqueur résiduel, la disponibilité de D-9, la validation avant ancrage, l’ancrage, la remise E7 et le protocole de récupération par `root`.
>
> **Le même jour, il a précisé le rôle de W et la fin d’une transaction couverte** (§5.5.1, cas 1 à 3 et « Mécanisme du marqueur » ; §5.5.5, L.2, L.7 et L.8 ; §11.2 ; §14, point 24) :
> - W est un verrou de sérialisation, pas le support persistant du gel : le marqueur restant porte le gel ;
> - après que la transaction SQLite est résolue sur la connexion, le service relâche B puis W, même si le marqueur n’a pas pu être retiré ;
> - si le `COMMIT` est confirmé ou si un `ROLLBACK` complet réussit, le service peut tenter de retirer son propre marqueur. Si ce retrait échoue, il ne prétend pas que le gel est levé et ne retire aucun autre marqueur ; tout marqueur résiduel maintient le gel, sans nettoyage automatique ;
> - si l’issue du `COMMIT` est indéterminée, le service ne tente pas de retirer le marqueur. Une fois la transaction inactive sur la connexion, il relâche B puis W et laisse le marqueur en place jusqu’à la récupération et à la levée explicites par `root` ;
> - si la transaction reste non résolue, la conduite fail-stop déjà décrite est conservée : le processus se termine sans autre instruction, et la libération de B et de W à la fin du processus reste une hypothèse [H].
>
> Restent inchangés : un `ROLLBACK TO SAVEPOINT` seul n’autorise pas le retrait ; seul `root` retire un marqueur résiduel, après une récupération et une vérification explicites ; E et les opérations qui ouvrent refusent sous W lorsqu’un marqueur résiduel est présent. Restent ouverts [O] : la conduite si l’état ou la présence du marqueur ne peut pas être établi, le code et le comptage du refus, les détails techniques du retrait et de sa durabilité, et la procédure de récupération. Les points déjà ouverts sur D-9, les fermetures pendant le gel, la validation avant ancrage, l’ancrage et la remise E7 ne sont pas tranchés.
>
> **Le même jour, il a fixé le support de W, la catégorie d’emplacement des marqueurs et un principe sur la restauration** (§5.5.1, cas 3, « Mécanisme du marqueur » ; §5.5.5, L.1 et L.8 ; §9.2 ; §12 ; §14, point 24) :
> - W est un fichier stable détenu par `root`, jamais supprimé ni remplacé, que le service peut ouvrir et prendre en verrou exclusif sans pouvoir le modifier. Cela reprend la décision existante sur le rôle exclusif de W ;
> - les marqueurs sont placés dans un sous-répertoire persistant du compte de service, dans l’arborescence des données, hors des arborescences `root` et du code. Un système de fichiers local est une exigence de conception ; le système de fichiers réellement utilisé sur le serveur reste à vérifier [H] ;
> - une restauration n’est jamais, à elle seule, une levée explicite du gel. La façon d’appliquer cette règle après une restauration reste ouverte [O].
>
> La portée de W reste limitée à V0 et E, et L.4 est inchangé : cette décision ne fait pas prendre W par `root` pour la récupération. La prise de W ne garantit pas la cohérence d’une sauvegarde : d’autres écrivains, dont D-9 et la validation avant ancrage, écrivent dans la base sans W. Restent ouverts [O] : la méthode de sauvegarde, la procédure de restauration, l’emplacement et les modes exacts des fichiers, la synchronisation détaillée, la récupération et la levée du gel.
>
> **Le même jour, il a fixé la conduite après un retrait visible mais non durable, et après un échec de synchronisation à la création** (§5.5.1, cas 3, « Mécanisme du marqueur » ; §5.5.5, L.2, L.7 et L.8 ; §10.3 ; §14, point 24) :
> - après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi, si la suppression du marqueur est visible mais que la synchronisation du répertoire échoue ou a une issue incertaine : l’issue SQLite reste établie ; l’absence visible du marqueur fait que le contrôle sous W peut laisser poursuivre les transactions couvertes pendant que le système reste en marche, sauf si d’autres marqueurs résiduels sont présents : ceux-ci continuent de maintenir le gel et de provoquer les refus prévus, cette suppression ne le maintenant pas à elle seule ; le service signale que la durabilité du retrait n’est pas établie et ne présente pas ce constat comme une levée explicite par `root` ; après une coupure ou un redémarrage, le marqueur peut réapparaître et provoquer un gel conservateur ; ce cas ne crée pas, à lui seul, un nouveau déclencheur de gel pendant que le système tourne ;
> - si la synchronisation du marqueur ou de son répertoire échoue avant toute écriture SQLite, la transaction n’exécute aucune écriture de base. Elle suit la conduite de refus déjà prévue et ne supprime aucun marqueur appartenant à une autre transaction. Son propre marqueur relève de la règle de retrait déjà décidée : après un `ROLLBACK` complet réussi, le service peut tenter de le retirer. **Précisé le 28 octobre 2026 [D] :** la transaction se termine alors par un `ROLLBACK` complet avant de poursuivre. Si ce `ROLLBACK` échoue ou si son issue ne peut pas être établie, aucun `COMMIT` ne suit et le service applique la règle fail-stop propre à ce cas, plus stricte que la règle générale du §5.5.1, cas 2, point 2 : tout échec de ce `ROLLBACK`, même si `in_transaction` est faux et que l’annulation pourrait être déduite selon cette règle générale, met fin au processus sans autre instruction, comme au cas 2, point 3. Le marqueur est laissé en place s’il est présent, et la règle générale du point 2 reste applicable aux autres erreurs.
>
> La règle applicable à un `COMMIT` d’issue indéterminée, la levée explicite des marqueurs résiduels par `root` et la portée de W sont inchangées. Le sort du nonce et la qualification du refus en cas d’échec de synchronisation restent ouverts [O].
>
> **Le même jour, il a fixé la fin de la transaction après un échec de synchronisation du marqueur** (§5.5.1, cas 3, « Mécanisme du marqueur » ; §5.5.5, L.2, L.7 et L.8 ; §10.3 ; §14, point 24) : si la synchronisation du marqueur ou de son répertoire échoue avant toute écriture SQLite, le service termine la transaction SQLite par un `ROLLBACK` complet avant de poursuivre. Après un `ROLLBACK` complet réussi, il peut tenter de retirer son propre marqueur selon la règle déjà décidée ; il ne retire jamais le marqueur d’une autre transaction. Si le `ROLLBACK` échoue ou si son issue ne peut pas être établie, aucun `COMMIT` ne suit et le service applique la règle fail-stop propre à ce cas, plus stricte que la règle générale du §5.5.1, cas 2, point 2 : tout échec de ce `ROLLBACK`, même si `in_transaction` est faux et que l’annulation pourrait être déduite selon cette règle générale, met fin au processus sans autre instruction, comme au cas 2, point 3. Le marqueur est laissé en place s’il est présent, et la règle générale du point 2 reste applicable aux autres erreurs. Le refus et le sort du nonce dans ce cas ont été fixés ensuite le même jour (ci-dessous).
>
> **Le même jour, il a fixé le refus et le sort du nonce après un échec de synchronisation du marqueur** (§5.5.1, « Sort du nonce selon l’issue » et cas 3, « Mécanisme du marqueur » ; §5.5.5, L.2, L.7 et L.8 ; §10.3 ; §14, point 24). Pour toute transaction couverte, V0 comme E, si la synchronisation du marqueur ou de son répertoire échoue avant toute écriture SQLite :
> - l’opération est refusée comme échec technique fermé ; aucun effet ni aucune écriture SQLite ne sont produits ;
> - pour V0, le nonce n’est ni consommé, ni passé à `FAILED`, ni renouvelé. S’il est encore `ISSUED`, il le reste jusqu’à son expiration normale ;
> - ce refus n’incrémente ni le compteur des tentatives d’autorisation, ni le compteur borné par opération et par classe de refus du §10.3 (ci-dessous) ;
> - après un `ROLLBACK` complet réussi, le service peut tenter de retirer son propre marqueur, selon la règle déjà décidée ; il ne retire jamais le marqueur d’une autre transaction ;
> - si ce `ROLLBACK` échoue ou si son issue ne peut être établie, aucun `COMMIT` ne suit et le fail-stop spécial déjà décidé s’applique, même si `in_transaction` est faux ; le marqueur est laissé en place s’il existe ;
> - aucune nouvelle tentative automatique n’est lancée. Après récupération du stockage, une nouvelle présentation repasse les contrôles normaux et n’est possible avec le même énoncé signé que si le nonce est encore valide ;
> - cet échec, à lui seul, ne crée pas de nouveau déclencheur de gel général ; les règles déjà décidées sur les marqueurs résiduels et le gel conservateur restent applicables.
>
> Restent ouverts [O] : le code technique distinct du refus, sa qualification détaillée au-delà de l’« échec technique fermé », et l’articulation de ce refus avec le compteur borné par opération et par classe de refus (§10.3), fixée ensuite le même jour (ci-dessous).
>
> **Le même jour, il a précisé que cet échec n’incrémente pas le compteur borné par opération et par classe de refus du §10.3** (§5.5.1, cas 3, « Mécanisme du marqueur » ; §5.5.5, L.2, L.7 et L.8 ; §10.3 ; §14, point 24). Les autres catégories de refus et leurs compteurs sont inchangés. Les décisions déjà prises pour ce cas restent applicables : refus technique fermé, sans effet ni écriture SQLite ; nonce inchangé ; aucune nouvelle tentative automatique ; `ROLLBACK` complet obligatoire, avec le fail-stop spécial s’il échoue ou si son issue ne peut être établie ; nouvelle présentation soumise aux contrôles normaux et possible seulement si le nonce est encore valide. Une télémétrie diagnostique éventuelle reste facultative et hors du protocole d’autorisation ; elle ne doit retarder ni le `ROLLBACK` ni le fail-stop, et son mécanisme n’est pas conçu ici. Le code technique distinct et la qualification détaillée du refus restent ouverts [O] ; la nature de ce code est fixée ensuite le même jour (ci-dessous).
>
> **Le même jour, il a fixé la nature du code de ce refus** (§5.5.1, cas 3, « Mécanisme du marqueur » ; §5.5.5, L.2, L.7 et L.8 ; §6.3 ; §10.2 ; §10.3 ; §14, point 24) :
> - le refus reçoit un code technique fixe, défini par les garanties qu’il donne à l’appelant et commun à V0 et E : aucun effet ni écriture SQLite, nonce V0 inchangé, aucun incrément des compteurs décidés, aucune nouvelle tentative automatique. Il n’est émis qu’après un `ROLLBACK` complet réussi ;
> - ce code est distinct des codes de rejet signés du §6.3 : il n’est ni signé, ni écrit en base, ni inscrit dans J-b ;
> - il est accompagné d’un qualificatif secondaire fixe sur le retrait du marqueur. Ce qualificatif indique seulement le sort du marqueur de cette transaction ; aucune valeur ne signifie que le gel global est levé ;
> - en cas de fail-stop, aucun code de refus n’est émis, conformément à la règle existante : le processus se termine sans autre instruction ;
> - toute télémétrie diagnostique reste facultative, hors du protocole d’autorisation, et ne retarde ni le `ROLLBACK` ni le fail-stop.
>
> Restent ouverts [O] : le nom exact du code, sa place dans une liste distincte de réponses techniques, les valeurs fermées du qualificatif (fixées ensuite le même jour, ci-dessous, hors leurs noms) et ce que l’opérateur observe en cas de fail-stop (signalement fixé ensuite le même jour, ci-dessous, hors la valeur et la transmission du statut). La liste des codes de rejet signés du §6.3 est inchangée.
>
> **Le même jour, il a fixé les valeurs du qualificatif sur le retrait du marqueur** (option Q-A, lecture (b) ; §5.5.1, cas 3, « Mécanisme du marqueur » ; §5.5.5, L.2, L.7 et L.8 ; §10.2 ; §14, point 24). Le qualificatif a trois valeurs fermées, qui décrivent seulement l’état observable du marqueur de cette transaction :
> - **retrait visible, durabilité non établie :** le fichier a été supprimé du répertoire visible. Le retrait n’est jamais déclaré durable dans ce cas, même si une synchronisation ultérieure réussit ; la valeur signifie que la durabilité n’est pas établie, et non que la suppression est certainement non durable ;
> - **marqueur confirmé présent :** retrait non tenté, ou retrait échoué dont la présence est confirmée ;
> - **état du marqueur non établi :** notamment identité différente, fichier absent avant la tentative, répertoire illisible, ou impossibilité de vérifier l’état. Dans ces cas, rien n’est supprimé.
>
> Il n’existe donc pas de valeur « retrait durable » pour ce cas. Aucune valeur n’est nommée ni décrite comme « gel levé », « système ouvert » ou équivalent : le qualificatif ne prouve pas l’absence d’autres marqueurs et ne constitue jamais une levée du gel global. Le code technique défini par ses garanties, la règle du nonce et des compteurs, l’émission seulement après un `ROLLBACK` complet réussi et l’absence de code en fail-stop sont inchangés. Restent ouverts [O] : les noms exacts des trois valeurs et leur place dans la liste des réponses techniques, la tentative systématique ou non du retrait, la conduite lorsque l’état n’est pas établi, et le signalement du fail-stop (fixé ensuite le même jour, ci-dessous).
>
> **Le même jour, il a fixé le signalement des fail-stop (option F2)** (§5.5.1, cas 2, point 3 et point 5, cas 3 et « Signalement du fail-stop » ; §5.5.5, L.2, L.7 et L.8 ; §10.2 ; §14, point 24) :
> - en fail-stop — §5.5.1, cas 2, point 3 ; cas 3, point b ; fail-stop spécial après échec de synchronisation du marqueur — le processus n’émet aucun code de refus ni message de réponse du protocole. Il se termine avec un statut de sortie dédié, unique et commun à ces chemins, distinct des statuts de succès et de refus ;
> - ce statut signifie uniquement que le processus s’est arrêté en fail-stop et que l’issue n’est pas établie. Il ne prétend rien sur l’effet ni sur l’état du nonce ;
> - ce statut de sortie n’est pas un code de réponse technique du §10.2. Les codes [R] prévus au cas 2, point 5, et au cas 3 ne s’appliquent qu’aux chemins où le processus continue, jamais aux chemins en fail-stop ;
> - un marqueur résiduel, lorsqu’il est présent, maintient le gel selon les règles décidées. Dans le fail-stop spécial après échec de synchronisation du marqueur, l’absence observée du marqueur n’est présentée ni comme une preuve de retrait durable ni comme une levée du gel.
>
> Restent ouverts [O] : la valeur exacte du statut (son nom symbolique est fixé ensuite le même jour, ci-dessous), sa transmission par la CLI, SSH ou le superviseur, et la conduite de récupération lorsque le marqueur est absent ou que sa présence ne peut être établie. Les autres décisions sur le gel, les marqueurs, le nonce, les compteurs et le retrait sont inchangées.
>
> **Le même jour, il a fixé le nom symbolique de ce statut : `EXIT_FAIL_STOP`** (§5.5.1, « Signalement du fail-stop » ; §5.5.5, L.2, L.7 et L.8 ; §10.2 ; §14, point 24) :
> - `EXIT_FAIL_STOP` est le statut de sortie symbolique unique, commun à tous les chemins qui se terminent en fail-stop ;
> - il indique seulement que le processus s’est terminé en fail-stop et que l’issue n’est pas établie. Il ne dit rien sur l’effet ni sur l’état du nonce ;
> - il n’est ni un code de refus ni un code de réponse du protocole. En fail-stop, aucun code de refus ni message de réponse n’est émis.
>
> Restent ouverts [O] : sa valeur numérique, sa transmission par la CLI, SSH ou le superviseur, et la politique de redémarrage du processus par le superviseur. F2, la règle spéciale après échec de synchronisation du marqueur, les codes des chemins qui continuent et les règles sur l’effet et le nonce sont inchangés.
>
> **Le même jour, il a fixé le seul signal d’un fail-stop au titre du protocole (option T1, « statut de sortie seul », sans lien avec la tension T-1, §3.1 et §7.1)** (§5.5.1, « Signalement du fail-stop » ; §5.5.5, L.2, L.7 et L.8 ; §10.2 ; §14, point 24) :
> - en fail-stop — §5.5.1, cas 2, point 3 ; cas 3, point b ; fail-stop spécial après échec de synchronisation du marqueur — aucun code de réponse ni message du protocole n’est émis ;
> - le seul signal produit par le processus au titre du protocole est le statut symbolique dédié `EXIT_FAIL_STOP`, déjà décidé. Ce statut signifie seulement que le processus s’est arrêté en fail-stop et que l’issue n’est pas établie ; il n’affirme rien sur l’effet ni sur le nonce ;
> - aucun message applicatif n’est écrit sur stdout ni sur stderr lors du fail-stop. Une télémétrie diagnostique facultative, hors protocole et sans retard du fail-stop, reste soumise aux règles déjà établies ;
> - le marqueur n’est pas décrit comme l’unique signal qui fait toujours foi : après un échec de synchronisation du marqueur, son absence visible ne prouve ni que son retrait est durable ni que le gel est levé. Un marqueur résiduel présent maintient le gel selon les décisions existantes ;
> - aucun code n’est émis sur un chemin qui se termine en fail-stop ; les codes prévus au cas 2, point 5, et au cas 3 ne s’appliquent qu’aux chemins où le processus continue.
>
> Restent ouverts [O] : la valeur numérique de `EXIT_FAIL_STOP`, sa transmission par la CLI, sudo, SSH ou le superviseur, la conduite face à un statut inconnu ou au statut 255, la politique de redémarrage du processus par le superviseur et l’observation côté E. F2, le nom `EXIT_FAIL_STOP`, la règle spéciale après échec de synchronisation du marqueur et les règles sur le gel, les marqueurs, l’effet, le nonce et les compteurs sont inchangés.
>
> **Le même jour, il a décidé de ne pas fixer maintenant la valeur numérique de `EXIT_FAIL_STOP`** (§5.5.1, « Signalement du fail-stop » ; §10.2 ; §14, point 24) :
> - le nom symbolique `EXIT_FAIL_STOP` reste fixé ;
> - sa valeur numérique n’est pas fixée à ce stade ;
> - le choix numérique sera repris après la définition de la liste des statuts de sortie de la CLI et l’examen des chaînes concernées (CLI, sudo, SSH et superviseur) ;
> - aucune plage numérique n’est adoptée comme décision.
>
> Restent ouverts [O] : la valeur numérique de `EXIT_FAIL_STOP` ; la liste des statuts de sortie de la CLI ; la transmission du statut par la CLI, sudo, SSH ou le superviseur, et la vérification de ces chaînes sur le serveur ; la conduite face à un statut inconnu ou au statut 255 ; l’observation côté E ; la politique de redémarrage du processus par le superviseur, que le choix du numéro ne tranche pas. F2, l’option T1, le nom `EXIT_FAIL_STOP` et sa signification sont inchangés.
>
> **Le même jour, il a fixé le cadre symbolique des catégories de sortie de la future commande `apply`, sans valeurs numériques** (§10.2, « Catégories de sortie de `apply` » ; §5.5.1, cas 1 à 3 ; §5.5.5, L.7 ; §14, point 24) :
> - les catégories décrivent seulement ce qui est établi sur l’effet métier, le `COMMIT` et l’état du nonce. Elles n’affirment ni l’effectivité, ni la possibilité de réessayer, ni l’état du gel ou du marqueur ;
> - le comptage éventuel des refus est hors de leurs garanties : son emplacement et sa transaction restent [O] ;
> - `EXIT_OK` : `COMMIT` confirmé ; effet et `CONSUMED` enregistrés ensemble. La catégorie n’affirme pas l’effectivité : une opération qui ouvre n’est effective qu’après V1, l’ancrage et E ; une fermeture ordinaire prend effet au `COMMIT` local dans le service intact ;
> - `EXIT_REFUSED_RECORDED` : effet métier annulé ; refus enregistré ; le nonce visé n’est pas `ISSUED` à l’issue ;
> - `EXIT_REFUSED_UNRECORDED` : aucun effet métier ni changement du nonce n’est validé par cette tentative ; cela ne dit rien des écritures éventuelles de comptage ;
> - `EXIT_REFUSED_NONCE_UNESTABLISHED` : effet annulé au `SAVEPOINT` ; `COMMIT` final en erreur ; nonce ni établi comme `FAILED` ni comme intact (cas 1, points a et c) ;
> - `EXIT_OUTCOME_TO_ESTABLISH` : `COMMIT` du chemin de succès en erreur ; ni succès ni refus, et le processus continue (cas 3, points a et c) ;
> - `EXIT_FAIL_STOP` : définition déjà décidée, inchangée.
>
> `EXIT_REFUSED_EFFECT_UNASSERTED` (cas 2, points 1 et 2) reste une recommandation [R], conditionnelle à la confirmation du code de réponse du cas 2. Restent ouverts [O] : le classement des chemins non définis, notamment le refus pour marqueur résiduel, l’échec de `BEGIN IMMEDIATE`, le délai de W, la transition sans changement de ligne après une lecture `ISSUED` et les autres commandes ; la concordance entre catégories et codes de réponse, et le canal de ces codes ; toutes les valeurs numériques, le report de celle de `EXIT_FAIL_STOP` étant inchangé. Le même jour, les renvois des codes du cas 2, point 5, et du cas 3, « Réponse », ont été corrigés vers le §10.2, sans trancher leur rattachement ; dans L.7, la ligne du cas 1, « échec de la transition », renvoie désormais au cas 2, point 3, lorsque l’annulation n’est ni établie ni déduite.
>
> **Le 29 octobre 2026, il a précisé la portée de ces catégories face aux déductions sous C2** (§10.2, « Catégories de sortie de `apply` » ; §5.5.1, « Conditions de toute garantie », cas 1 et cas 2, points 1 et 2 ; §5.5.5, L.7 ; §14, point 24) :
> - une catégorie n’affirme pas comme établi un état qui repose seulement sur une déduction sous C2 ;
> - au cas 2, point 1, le nonce non modifié par cette tentative peut être indiqué comme établi après le `ROLLBACK` réussi ;
> - au cas 2, point 2, la catégorie n’affirme pas que le nonce est inchangé : cette conclusion dépend de C2 et reste une déduction [R], non une garantie de la catégorie ;
> - la même réserve s’applique à tout rattachement de `EXIT_REFUSED_UNRECORDED` qui dépend de `in_transaction` faux et de C2, notamment au cas 1 ;
> - `EXIT_REFUSED_EFFECT_UNASSERTED` peut affirmer « aucun `COMMIT` exécuté » et « absence d’effet non affirmée », mais ne garantit pas l’état du nonce au point 2.
>
> `EXIT_REFUSED_EFFECT_UNASSERTED` reste une recommandation [R], conditionnelle à la confirmation du code de réponse du cas 2, et les rattachements proposés restent [R]. Restent ouverts [O] : la démonstration de C2 dans la mise en œuvre ; la question, distincte, d’un nouvel essai de `ROLLBACK`. Les règles de transaction, les autres catégories et les autres décisions sont inchangées.
>
> **Le même jour, il a fixé la conduite face à une génération visible mais non déclarée effective** (§5.5.5, I.4, J.4, L.7 et L.8, point 8 ; §14, point 23) :
> - après un arrêt brutal de `root`, ou une coupure d’alimentation au même stade (extension décidée le même jour [D]), survenu entre le renommage de P′ et la synchronisation durable du répertoire, lorsque g+1 est visible sans avoir été déclarée effective, le service n’utilise pas g+1 tant qu’elle n’est pas déclarée effective ;
> - le service reste fermé : aucune opération signée, aucun ancrage et aucune consignation de `c` pour cette génération avant sa déclaration d’effectivité ;
> - `root` doit achever ou résoudre l’installation avant la reprise du service ;
> - cette exception s’applique aux formulations de I.4 et J.4 selon lesquelles la mise à jour de la politique fait entrer l’invalidation en vigueur.
>
> Restent ouverts [O] : le mécanisme concret qui établit la durabilité de l’installation ou déclare g+1 effective, et la conduite de `root` pour achever ou résoudre l’installation. Le principe O1-B a été adopté sous condition le 1er novembre 2026 [D] (ci-dessous ; §5.5.5, L.8, point 8) ; sa condition reste [H].
>
> **Le même jour, il a fixé la conduite après un échec de synchronisation du répertoire, `root` restant actif** (§5.5.5, L.3, R6 ; L.5 ; L.7 ; L.8, point 8 ; §14, point 23) :
> - après le renommage de P′ en P, si la synchronisation du répertoire échoue alors que `root` est encore actif, `root` garde B et G pendant une période bornée pour achever ou résoudre l’installation ;
> - s’il n’y parvient pas dans cette période, il arrête le service, maintient l’interdiction de redémarrage et libère les verrous après l’arrêt complet. Le service reste arrêté jusqu’à l’achèvement ou la résolution de l’installation ;
> - g+1 n’est déclarée effective que lorsque les conditions déjà décidées sont remplies (L.3, R6). D’ici là, la règle précédente s’applique : le service n’utilise pas g+1.
>
> Restent ouverts [O] : la valeur du délai borné ; les modalités et le nombre des tentatives, la méthode technique d’achèvement après un échec de `fsync` restant à vérifier [H] ; la persistance de l’interdiction de redémarrage si `root` s’arrête brutalement ; les conditions précises de reprise ; les mécanismes d’intervention si l’installation ne peut pas être résolue. Cette décision ne modifie pas les règles de D-9 (§5.5.5, L.5).
>
> **Le même jour, il a fixé la portée de la « révocation défavorable connue » de M.6** (§5.2.7, M.6 et K.7 ; §5.5.3 ; §14, point 22) :
> - l’énumération est normative et fermée : seuls relèvent de cette notion un statut de sécurité applicable, le statut `REVOKED`, une AC intermédiaire révoquée et une ancre retirée, connus par un import ;
> - toute extension exige une décision distincte.
>
> L’applicabilité d’un statut de sécurité selon `authenticatorVersion` reste ouverte [O], et son refus à la genèse reste une recommandation [R] (§5.2.7, G et K.6). Les autres règles de M.6 et de vérification sont inchangées.
>
> **Le 1er novembre 2026, le propriétaire a adopté sous condition le principe O1-B pour la déclaration d’effectivité [D]** (§5.5.5, L.2, L.3, L.7 et L.8, point 8 ; §14, point 23, décision 15) :
> - après R6 et avant R7, tout en tenant B, `root` écrit une déclaration D qui désigne g+1 et l’empreinte de P, puis établit sa durabilité ;
> - toujours sous B et avant R7, `root` écrit une confirmation, uniquement après avoir établi cette durabilité ;
> - le service et E n’utilisent g+1, n’acceptent aucune opération signée pour cette génération, ne consignent pas `c` et n’ancrent pas tant qu’ils n’ont pas lu sous B une déclaration confirmée qui concorde avec P (contrôle de l’état courant de D à chaque opération concernée : §5.5.5, L.8, point 8, « Portée ») ;
> - si D est absente, non confirmée, illisible ou discordante, le système reste fermé pour cette génération ;
> - **condition :** la représentation retenue doit garantir que la perte de la confirmation ne peut pas altérer la déclaration déjà durable. Cette garantie n’est pas encore démontrée [H]. Si elle ne peut pas être garantie, aucune mise en œuvre d’O1-B ne doit en être déduite.
>
> Seul ce principe abstrait est décidé, et aucun mécanisme concret n’est choisi. Restent ouverts [O] : le format et le stockage de D ; ses permissions et son inscription à l’inventaire T-3 ; la méthode d’écriture ; la conduite de `root` en cas d’échec ; les états de refus et le sort du nonce ; l’écriture initiale de D à la genèse ; la reprise par `root` ; la disponibilité de D-9. Les deux décisions du 29 octobre 2026 sur l’installation interrompue (§14, point 23, décisions 13 et 14), L.5 et M.6 sont inchangées.
>
> **Le 1er novembre 2026, le propriétaire a retenu l’option 2 pour l’ancrage externe [D]** (§5.5.5, L.6, L.7 et L.8, point 7 ; §11.3 ; §14, point 23, décision 16) :
> - la règle d’ancrage vise la génération et l’état de D contrôlés sous B lors de la validation de la queue ;
> - l’ajout externe à J-c, qui suit le `COMMIT` et a lieu hors barrière selon le protocole actuel, publie la queue déjà validée ; il n’est pas une nouvelle validation sous la génération qui pourrait être installée après le `COMMIT` ;
> - une queue validée sous g demeure classée sous g, même si son ajout à J-c survient après l’installation de g+1. Cet ajout peut donc précéder `c` de g+1, et les entrées de g restent antérieures à `c` dans l’ordre du journal ;
> - cette publication ne constitue ni l’utilisation de g+1, ni un ancrage d’opération de g+1 ;
> - avant toute validation ultérieure sous g+1, le service vérifie sous B que D est actuellement confirmée et concorde avec P ; `c` de g+1 est consignée avant toute validation ou tout ancrage ultérieur sous g+1.
>
> L’option 1, tenir B pendant l’ajout, n’est pas retenue. La barrière, O1-B, dont la condition reste [H], et M.6 sont inchangés. Restent ouverts [O] : le processus qui effectue l’ajout à J-c ; ses tentatives et ses issues inconnues ; le traitement d’une queue en attente après un redémarrage, cette décision ne fixant pas, à elle seule, comment une queue dont la validation précédente a eu lieu sous g est traitée si la validation est rejouée après l’installation de g+1 ; le sort d’un ajout en attente si g devient fermée selon O1-B, pendant S4 ou pendant le gel.
>
> **Le 2 novembre 2026, le propriétaire a fixé le critère d’évaluation de la condition d’O1-B [D]** (§5.5.5, L.8, point 8 ; §14, point 23, décision 17) :
> - la condition est évaluée selon une garantie conditionnelle, fondée sur des hypothèses explicites et vérifiées pour l’environnement cible, avec fermeture en cas d’anomalie ;
> - cette décision ne constate pas que la condition est satisfaite, ne choisit aucune représentation de D et n’autorise ni relevé de l’environnement, ni essai, ni mise en œuvre ;
> - la condition reste [H] jusqu’à une décision distincte constatant que les preuves requises sont suffisantes.
>
> La liste des hypothèses et des preuves requises reste à fixer [O]. Le principe de la décision 15, les décisions 13, 14 et 16, L.5 et M.6 sont inchangés.
>
> **Le 2 novembre 2026, le propriétaire a fixé le traitement des hypothèses relevant de l’hébergeur [D]** (§5.5.5, L.8, point 8 ; §14, point 23, décision 18) :
> - seules les hypothèses intrinsèquement invérifiables depuis le système invité et relevant de l’hébergeur peuvent être acceptées comme limites de confiance explicites ; elles ne sont jamais présentées comme vérifiées ;
> - cette acceptation exige que le type de volume et les engagements applicables de l’hébergeur soient identifiés et examinés, puis que le propriétaire accepte explicitement chaque hypothèse concernée ;
> - si ces éléments sont absents ou ambigus, l’hypothèse reste non établie, et O1-B demeure [H] et bloquée.
>
> **Articulation [D].** Cette décision complète la décision 17 : toute autre hypothèse reste à vérifier pour l’environnement cible, et le texte de la décision 17 est inchangé. Elle ne constate pas que la condition est satisfaite, ne désigne aucune hypothèse, ne choisit aucune représentation de D et n’autorise ni relevé, ni contact avec l’hébergeur, ni essai, ni prototype, ni accès au serveur, ni mise en œuvre.
>
> Fabricant, modèles, ancres, licence, canal et durées restent à choisir. Les détails de mise en œuvre de la genèse, la gestion et la perte des clés restent ouverts (§5.2). Toutes les autres propositions de ce document restent des recommandations [R] ou des points ouverts [O]. Ces décisions n’autorisent ni implémentation, ni création de compte, de clé ou de credential, ni modification du serveur, ni déploiement. Le document ne crée aucun compte, credential, secret, RP ID, enregistrement DNS, GitHub App, callback, inscription ni activation, et n’apporte aucune modification au code ni aux tests du dépôt. D-5 reste non résolu ; Provider = CLOSED et NO-GO restent en vigueur.

**Légende**

- **[F]** fait vérifié, soit dans le dépôt à `c41146b` (fichier et ligne), soit dans une source externe citée : spécifications WebAuthn et MDS, bibliothèques, documentation SQLite et Python (§5.2.7, A ; §5.5.1, « Sources officielles consultées le 27 octobre 2026 »). Une citation de code à `73737dd` désigne les mêmes lignes : ce commit ne modifie qu’un document de G1. Une citation de code à `6313648` décrit `main` après `e431cea` ;
- **[D]** décision déjà prise, avec sa source ;
- **[R]** recommandation nouvelle de cette spécification, non décidée ;
- **[H]** hypothèse à vérifier, non établie par les sources vérifiées ;
- **[O]** point qui exige une décision explicite (récapitulés au §14).

**Sources citées.** « G1 » désigne [`docs/phase_g1_approval_service_design.md`](phase_g1_approval_service_design.md), et « D-5 l. » renvoie aux lignes de [`docs/g2_d5_enrollment_flow_proposal.md`](g2_d5_enrollment_flow_proposal.md). Employé seul, « D-5 » désigne la décision D-5 de G1.

Aucune durée n’est fixée. Chaque délai est désigné par un nom (`T_nonce`, `T_invitation`, `T_attente`) sans valeur.

## 1. Périmètre

La spécification couvre la manière dont le propriétaire, seul administrateur, confirme ou rejette une inscription `PENDING`, et ce qui entoure cette opération : credentials d’administration, énoncé signé, voie d’urgence, preuve GitHub, comptes système, journal, secrets et menaces.

Elle consigne qui peut rouvrir l’interrupteur D-9 (T-1, §7.1) et comment cette réouverture s’inscrit dans A-1. Elle ne couvre pas : la conception de l’interrupteur lui-même, qui n’existe pas encore, le flux OAuth lui-même, la cérémonie WebAuthn de B côté web, ni la consommation d’une approbation.

## 2. Faits du dépôt [F]

### 2.1 Stockage v5

- Une invitation lie `approver_id`, `principal_id` et `expected_account_id` ; seule l’empreinte SHA-256 du secret est stockée (`approval_store_v5.py:68-80`).
- `pending_enrollments` porte **un seul credential** par invitation, l’état `PENDING` ou `REJECTED`, et le contrôle `MOCK_UNVERIFIED_ACCOUNT_ID_MATCH` (`:122-135`). Il n’existe pas d’état `CONFIRMED`.
- `reject_enrollment` n’enregistre ni motif, ni auteur, ni entrée de journal (`:453-475` à `6313648`). Aucune primitive v5 n’écrit au journal.
- Toutes les primitives v5 sont non authentifiées et réservées aux tests.

### 2.2 Registre v3

- `github_accounts.evidence` n’accepte que `ADMIN_ATTESTED` (`approval_store.py:138`) ; `separation_evidence` n’accepte que `ADMIN_ATTESTED_ACCOUNT_SEPARATION` (`:165`).
- Le journal a une liste d’événements fermée et ne contient que des empreintes. Il n’est ni chaîné ni ancré et n’a aucune colonne d’auteur (`:184-211` ; G1 l. 1087, 1118).
- L’ouverture est refusée si la base, son `-wal`, son `-shm` ou son répertoire n’appartiennent pas à l’utilisateur effectif ou donnent un droit au groupe ou aux autres (`:332-336`). Tout processus qui ouvre la base doit donc tourner sous le compte propriétaire du fichier.
- Les déclencheurs sont des conventions renforcées : un processus qui peut écrire le fichier peut les contourner (G1 l. 289, 778).

### 2.3 Vérificateur WebAuthn : non réutilisable tel quel

- `WebAuthnPolicy` refuse tout RP ID autre que `ApprovalStatement.RELYING_PARTY_ID` (`zephyr-approval.fr`) et toute origine autre que `https://zephyr-approval.fr` (`webauthn_verifier.py:97-107` ; `approval_statement.py:90`).
- `verify()` n’accepte qu’un `ApprovalStatement` (`webauthn_verifier.py:154`). Le défi est dérivé avec la séparation de domaine `AI_DIRECTOR_APPROVAL_WEBAUTHN_V2\0` (`approval_statement.py:30, 154-159`).
- Les échéances appliquées sont celles de D-8 (`approval_deadline`, `expires_at`) (`webauthn_verifier.py:231`).
- Le résolveur rattache le credential à l’`approver_id` de l’énoncé.
- Le vérificateur ne détecte pas le rejeu (G1 l. 750, 757).

Sont réutilisables : `fido2` 2.2.1 déjà verrouillé, la liste d’algorithmes et la limite RSA (provisoires, G1 l. 729, 761), et `canonical_json`.

### 2.4 Interdiction des primitives réseau et processus

`tests/test_provider_egress_closure.py:77-87, 181-191` : aucun fichier applicatif, `approval_service/` compris, ne peut importer `socket`, `socketserver`, `ssl`, `http`, `urllib`, `subprocess`, `multiprocessing`, `asyncio`, `importlib`, `ctypes`, etc., ni appeler `os.system`, `fork`, `exec*` ou `spawn*`. La règle ne prévoit aucune exception par fichier.

Conséquence : ni serveur web, ni client OAuth, ni canal local entre processus, ni envoi vers une ancre externe ne peut être écrit dans le code applicatif sans modifier cette règle.

### 2.5 Absence d’administration

Il n’existe ni CLI, ni lecture de l’utilisateur appelant, ni règle `sudo`, ni module d’administration dans `approval_service/`. Seules des docstrings en parlent.

### 2.6 Serveur — déclaré par le propriétaire, non vérifié (G1 §6, l. 380-392)

`directoradmin` est le compte d’administration ; `aidirector` est un compte de service sans connexion interactive, **propriétaire de `/srv/ai-director-data/app`** ; SSH par clé seulement ; `root` sans connexion directe ; UFW n’autorise que SSH.

## 3. Décisions déjà prises [D]

| Réf. | Contenu | Source |
|---|---|---|
| D-2 | Inscription fermée par défaut ; invitation à usage unique créée depuis une session SSH d’administration ; la première UV n’autorise pas sa propre inscription | G1 l. 45, 209, 491 |
| D-3 | Deux credentials distincts sur deux authentificateurs séparés **avant toute activation** ; perte → fermeture, révocation, journal ; remplacement par invitation SSH ; aucun repli par courriel, SMS ou code | G1 l. 46, 210-212, 492 |
| D-4 | Secours `BE=0`, `BS=0` ; BE figé à l’inscription ; `BS=1` refusé si `BE=0` ; aucune attestation AAGUID | G1 l. 47, 223, 493 |
| D-7 | Ancre externe J-c en ajout seul ; indisponible ou divergente → fermé ; aucun résultat confirmé avant vérification de l’ancre | G1 l. 135, 496 |
| D-9 | Fermeture d’urgence par SSH sans WebAuthn ; réouverture par SSH avec assertion WebAuthn fraîche et UV **par un approbateur autorisé** (texte historique, modifié le 25 octobre par T-1, voir plus bas) ; révocations définitives | G1 l. 280-282, 498 à `c41146b` |
| D-12 | Application sur loopback ou socket Unix ; aucune exposition avant autorisation distincte | G1 l. 501 |
| D-13 | `python-fido2` pour WebAuthn ; aucune cryptographie maison | G1 l. 502 |
| D-15 | Clés SSH d’administration et serveur sont des racines de confiance ; leur compromission laisse le service fermé | G1 l. 212, 369, 504 |
| G1 §4.9 | Journal chaîné J-b écrit dans la même transaction ; refus non authentifiés agrégés de façon bornée ; ni secret, ni jeton, ni assertion brute, ni clé | G1 l. 288-293 |
| 19 oct. | Aucun principal fictif, aucun mode à une personne | G1 l. 1125 |
| 23 oct. | Le propriétaire est seul administrateur, par SSH ; B est approbatrice uniquement ; le propriétaire n’est pas approbateur | G1 l. 1136-1142 |
| 24 oct. | GitHub App sans permission, flux Web ; inscription en attente jusqu’à la confirmation SSH ; preuve distincte de `ADMIN_ATTESTED` ; ni login ni jeton conservé ; grant révoqué | D-5 l. 22-29 |
| 24 oct. | v4 retiré ; v5 est le seul prototype d’inscription | D-5 l. 175-182 |
| G1 | Une preuve WebAuthn d’administration et la confirmation WebAuthn des opérations d’administration restent à concevoir | G1 l. 1073, 1127 |
| 25 oct. | **Orientation A-1 adoptée** pour confirmer les inscriptions D-5 `PENDING`. SSH reste le transport et le contrôle d’accès système ; l’autorisation de confirmation requiert une assertion WebAuthn du propriétaire avec UV, liée à l’énoncé exact de l’opération ; les credentials d’administration sont distincts de ceux de B ; le propriétaire reste administrateur, pas approbateur. La décision ne tranche pas qui peut rouvrir l’interrupteur D-9 (tranché ensuite le même jour par T-1, voir plus bas). RP ID, origine, genèse et nombre des credentials d’administration restent ouverts. La limite du client CTAP local est maintenue : son origine est déclarée par le client, pas attestée par un navigateur | Décision du propriétaire, 25 octobre 2026 |
| 25 oct. | **T-3 tranché.** Le code d’administration et le fichier de confiance contenant les clés publiques épinglées appartiennent à `root`. `aidirector` peut les lire, mais ne peut ni les modifier ni les remplacer. Les fichiers de base de données restent détenus et utilisés par le compte de service, conformément aux contrôles existants (`approval_store.py:332-336`). L’installation et la mise à jour du code et du fichier de confiance relèvent d’une opération administrative `root` contrôlée. La compromission de `root` ou du serveur reste hors de la protection offerte par A-1 et maintient le système fermé selon D-15 | Décision du propriétaire, 25 octobre 2026 |
| 25 oct. | **T-3 complété.** `root` possède et contrôle en écriture l’ensemble des éléments qui peuvent changer l’application ou son autorisation : CLI d’administration, stockage, vérifications V0/V1/E, chemin d’approbation et de consommation, dépendances d’exécution, configuration et lancement du service. `aidirector` peut lire et exécuter ces éléments, mais ne peut ni les modifier ni les remplacer. Les fichiers SQLite restent au compte de service selon les contrôles d’accès existants. Toute mise à jour de ces éléments passe par une opération administrative `root` contrôlée. Aucune modification effective du serveur n’est autorisée par cette décision | Décision du propriétaire, 25 octobre 2026 |
| 25 oct. | **T-1 tranché.** Le propriétaire, en qualité d’unique administrateur, peut rouvrir l’interrupteur D-9 par SSH, avec une assertion WebAuthn fraîche et UV de son credential d’administration. B reste approbatrice uniquement, sans accès SSH ni rôle d’administration. Cette action n’autorise jamais le propriétaire à approuver une demande de génération. La décision modifie la règle historique de G1/D-9, qui attribuait la réouverture à un approbateur autorisé. La règle « distinct de l’acteur GitHub du run » s’applique aux approbations associées à un run, pas à la réouverture administrative, qui n’a pas d’acteur de run à comparer. **Alignement de G1 commité dans `73737dd` et fusionné dans `main` par le PR #62 (`6313648`)** (§3.1) | Décision du propriétaire, 25 octobre 2026 |
| 25 oct. | **RP ID d’administration : option O-3 retenue.** RP ID exact `ai-director-admin.invalid` ; origine exacte déclarée par le client CTAP local `https://ai-director-admin.invalid`. Cette valeur est fixe pendant toute la vie des credentials d’administration ; la changer exigera une nouvelle genèse. Aucun endpoint web d’administration ni aucune page publique ne doit utiliser cette origine. L’origine est fournie par le client local et n’est pas attestée par un navigateur ; la séparation de RP ID n’empêche pas un poste compromis de tromper son propriétaire. La compatibilité réelle avec Windows, CTAP et le modèle de clé retenu reste un point ouvert ; aucun essai avec une vraie clé n’est autorisé par cette décision. En cas d’échec de compatibilité, O-1 n’est qu’une solution de repli, à soumettre à une décision séparée | Décision de conception du propriétaire, 25 octobre 2026 |
| 25 oct. | **Credentials d’administration : orientation générale.** Deux credentials d’administration sur deux clés matérielles distinctes, principale et secours ; UV obligatoire à chaque signature ; `BE=0` requis, `BS=0` en découlant selon WebAuthn ; une seule des deux clés suffit aux opérations courantes. Restent ouverts : la cérémonie de genèse et l’installation initiale du fichier de confiance, la procédure de séparation physique (contrôle humain), la règle d’ajout, de remplacement ou de révocation, la perte des deux clés, les opérations qui pourraient exiger les deux clés, l’attestation, le partage éventuel d’une clé avec SSH et la compatibilité réelle avec Windows et CTAP. Aucune création de clé ou de credential ni aucun essai matériel n’est autorisé | Décision du propriétaire, 25 octobre 2026, sur sa consigne de suivre les choix recommandés |
| 25 oct. | **Règles de la cérémonie de genèse initiale du fichier de confiance.** La genèse a lieu une seule fois, hors du service web, système fermé et Provider CLOSED. Le client CTAP local crée séparément les deux credentials décidés (UV, RP ID et origine décidés, `BE=0`) ; les clés privées ne quittent jamais leurs authentificateurs. Les réponses d’inscription sont validées avant l’installation, et non remplacées par un fichier de clés publiques assorti d’un booléen « vérifié ». La séparation physique reste un contrôle humain de procédure. L’installation passe par l’opération `root` contrôlée (T-3), n’est permise que si aucun fichier de confiance n’existe, installe les deux entrées ensemble et refuse toute écriture partielle et tout remplacement. Après installation, les règles T-3 s’appliquent. Toute erreur laisse le système fermé ; la genèse n’active pas Provider et n’autorise aucun déploiement (§5.2.2) | Décision de conception du propriétaire, 25 octobre 2026 |
| 25 oct. | **Cycle de vie des défis de genèse.** C-1 : défis conservés uniquement en mémoire pendant une seule invocation `root`, sans reprise après une interruption. O-a : un credential orphelin d’une cérémonie échouée n’est jamais approuvé ni installé ; la confiance vient uniquement des deux entrées validées installées. Aucun défi ne vient du client local. Toute interruption ou erreur laisse le système fermé ; une nouvelle cérémonie utilise des défis frais et doit produire deux entrées validées ensemble. Aucune durée ni aucun nombre de tentatives n’est fixé tant que le client local et le transfert ne sont pas définis. Restent ouverts la procédure physique de reprise sur une clé portant un orphelin et les hypothèses sur les credentials découvrables, le stockage et le PIN. C-1 sera réexaminé si le transfert ne permet pas de terminer les deux inscriptions et les deux preuves de possession dans une seule invocation `root` (§5.2.5) | Décision de conception du propriétaire, 25 octobre 2026, sur sa consigne de suivre les recommandations |
| 25 oct. | **Orientation d’attestation de la genèse.** Attestation vérifiable contre une racine explicitement approuvée et une liste fermée d’AAGUID autorisés. Refus des attestations `none`, inconnues ou non vérifiables, et des chaînes non conformes ; aucun déclassement silencieux. Preuve de possession séparée maintenue, par assertion avec un défi frais. Pas d’attestation `enterprise` ni d’identifiant unique par appareil à ce stade. Si l’attestation requise ne peut pas être vérifiée, le système reste fermé. Portée : une attestation validée lie cryptographiquement les éléments couverts par sa signature et permet une décision de confiance selon la racine et les métadonnées admises ; elle ne garantit pas le comportement réel de l’appareil, ne prouve pas que la clé est celle que le propriétaire croyait utiliser, ni que deux credentials sont sur deux appareils distincts. Restent ouverts : le modèle et ses AAGUID, les racines, les métadonnées, les contrôles de validité et de révocation, l’attestation disponible par Windows et CTAP, et la procédure si la politique ne peut pas être satisfaite (§5.2.6) | Orientation de conception du propriétaire, 25 octobre 2026, sur sa consigne de suivre les choix recommandés |
| 26 oct. | **Cycle de vie de l’attestation AT-2.** Le propriétaire tranche neuf orientations (§5.2.7, M) :<br>– **M.1** ancres R-c si une source indépendante concorde avec MDS, sinon R-b après approbation hors bande de l’ancre de signature MDS ; divergence → refus fermé ;<br>– **M.2** métadonnées M-2, récupérées hors serveur et importées par l’opération `root` contrôlée, sans accès réseau du serveur ; adaptation de MDS §3.2 dont la conformité stricte n’est pas établie ;<br>– **M.3** refus de tout BLOB qui contient `x5u`, sans repli ;<br>– **M.4** liste fermée AAGUID–ancre–format ; modèle absent ou correspondance non démontrée → refus ; statuts inconnus ignorés, sans dispense d’admission ;<br>– **M.5** refus d’un `nextUpdate` dépassé, d’un `no` non croissant ou d’informations de révocation manquantes, à la genèse et à chaque import ; informations de statut vérifiées pour les AC intermédiaires ;<br>– **M.6** après la genèse, suspension des opérations qui ouvrent si `nextUpdate` est dépassé ou si un import échoue ; révocation connue → fermeture et revue ; aucun changement automatique de statut ; reprise par décision administrative authentifiée et politique valide, journalisée et ancrée ;<br>– **M.7** deux modèles d’AAGUID différents recommandés ;<br>– **M.8** validation X.509 éprouvée et horloge `root`, refus fermé si dates ou révocation sont invérifiables, `cryptography` 50.0.2 non présenté comme validé ;<br>– **M.9** journalisation et ancrage des éléments d’audit, aucune opération qui ouvre effective avant l’ancrage requis.<br>Restent ouverts : fabricant, modèles, ancres, licence, canaux, durées et détails techniques (§14, point 22) | Orientations de conception du propriétaire, 26 octobre 2026 |
| 26 oct. | **Liaison des énoncés signés à la reprise de suspension.** Pour les opérations 1 à 4 du §11.2, l’énoncé signé contient toujours le champ `effective_resume_entry_hash` : l’`entry_hash` de la dernière reprise de suspension effective et ancrée au moment du `prepare` (SHA-256, 32 octets), en 64 caractères hexadécimaux minuscules, ou `null` explicite avant toute reprise effective. Aucune séquence n’est ajoutée : l’empreinte identifie l’entrée. Ce champ appartient aux octets canoniques, et le défi le couvre. V0 reconstruit la reprise effective courante à partir de la chaîne concordante avec l’ancre relue et la compare à la valeur signée au moment de l’`apply` ; toute différence entraîne un refus, et le nonce passe à `FAILED`. Ni une valeur SQLite seule ni `prepared_at_ms` ne peuvent établir cette liaison. **Comparaison réservée à V0** : V1 et E vérifient la signature de l’énoncé sans comparer son identifiant à une reprise ultérieure, qui ne rend donc pas inutilisables les confirmations déjà enregistrées ; E applique toujours la politique et la suspension courantes. La création d’une invitation, dont le protocole signé n’est pas défini, devra suivre la même règle lorsque ce protocole sera conçu. Le reste de V0, V1 et E reste une recommandation (§5.3, §5.5.1, §11.2 ; §14, point 21) | Décisions du propriétaire, 26 octobre 2026 |
| 26 oct. | **Compteur `signCount` des credentials d’administration : option (b), signal seulement.** Si l’ancienne et la nouvelle valeur valent toutes deux 0, il n’y a pas d’anomalie. Si l’une des deux est non nulle et que la nouvelle est inférieure ou égale à la précédente, un signal borné est consigné ; l’opération n’est pas refusée pour ce seul motif. La nouvelle valeur est enregistrée à chaque opération acceptée, y compris après un signal. Le signal n’est ni une preuve de clonage ni une raison de changer automatiquement le statut du credential ou de suspendre le service. Il ne fait pas passer le nonce à `FAILED` et ne bloque pas l’effet de l’opération si les autres contrôles réussissent. Restent ouverts : les détails du signal borné et la valeur initiale du compteur après la genèse (§5.5.4 ; §14, point 8) | Décision du propriétaire, 26 octobre 2026 |
| 26 oct. | **Statuts des clés d’administration.** `ACTIVE` : autorisé en V0 et vérifiable en V1. `RETIRED` : refusé pour toute nouvelle opération V0 ; les confirmations antérieures au retrait restent vérifiables en V1, l’antériorité étant définie par l’ordre des entrées de journal ancrées et jamais par une date en base. `COMPROMISED` : refusé en V0 et en V1 ; aucune confirmation signée par cette clé ne peut être utilisée, quelle que soit sa date, puisqu’aucune borne de compromission suffisamment fiable n’est établie. Une anomalie `signCount` reste un signal seulement et ne change jamais automatiquement le statut d’une clé. Les changements de statut restent explicites, authentifiés, journalisés et ancrés selon les règles générales. **Portée de `COMPROMISED` :** une fois la clé marquée, aucune opération qui ouvre signée par elle (confirmation d’inscription, création d’invitation, ajout d’une clé, réouverture, reprise de suspension) ne peut fonder une autorisation future ; ses effets futurs sont refusés ou recalculés comme inactifs selon le chemin, sans modification rétroactive ; les opérations qui ferment restent applicables ; si aucune clé `ACTIVE` ne permet d’établir un état valide, le système reste fermé. Un marquage `COMPROMISED` survenu après la signature d’une opération qui ouvre, mais avant son ancrage, ne mène pas à S4 à lui seul : l’entrée peut être ancrée pour l’audit, sans effet futur, l’ordre étant établi par le journal. Une clé ajoutée par une clé ultérieurement `COMPROMISED` conserve son enregistrement et son statut, mais n’autorise aucune opération future tant qu’une clé `ACTIVE` ne l’a pas réautorisée. Cette réautorisation est explicite, authentifiée, journalisée et ancrée. Elle ne prend effet qu’après l’ancrage requis, pour les opérations futures seulement, sans rendre utilisable ce qui a été signé avant elle, y compris une assertion antérieure appliquée après elle. L’ordre des entrées du journal ancré ne prouve pas, à lui seul, le moment de la signature ; la détection repose sur la liaison à l’autorisation effective de la clé signataire (ligne suivante). Sans chemin sûr de réautorisation, le système reste fermé. Restent ouverts : la procédure de récupération, de perte et de remplacement des clés, la sortie d’un blocage, la désignation fiable de l’entrée de retrait et de celle du marquage, les mécanismes d’application aux opérations 2 à 5, la distinction sûre des cas dans une même queue non ancrée et le format de la réautorisation (§5.5.3, §5.7, §5.8 ; §14, point 9) | Décision du propriétaire, 26 octobre 2026 |
| 26 oct. | **Liaison d’une signature administrative à l’autorisation effective de la clé signataire.** Chaque énoncé signé pour une opération administrative lie la signature à l’entrée qui autorise effectivement la clé signataire : genèse initiale, ajout ou réautorisation. Pour une opération qui ouvre, V0 vérifie cette liaison à l’`apply`, d’après la chaîne concordante avec l’ancre relue. V1 vérifie, pour une confirmation enregistrée, que l’entrée d’autorisation liée est cohérente avec l’entrée de l’opération et reste valable. Une assertion préparée avant une nouvelle autorisation ne peut pas être appliquée après celle-ci. Si l’autorisation d’une clé est invalidée parce que sa chaîne d’ajout dépend d’une clé `COMPROMISED`, cette clé ne signe plus d’opérations futures tant qu’une réautorisation valide n’a pas été ancrée. C’est la valeur signée qui rattache l’assertion à l’autorisation, non l’ordre du journal ni une date SQLite. Restent ouverts : le nom du champ, son encodage, la représentation de l’autorisation initiale de genèse, le format des opérations d’ajout et de réautorisation, la désignation de la clé signataire dans l’énoncé et, pour les opérations qui ferment, les détails de mise en œuvre (ligne suivante) (§5.3, §5.5.1, §5.5.2, §5.5.3 ; §14, point 9) | Décision du propriétaire, 26 octobre 2026 |
| 26 oct. | **Opérations administratives signées qui ferment.** V0 vérifie que le credential signataire est `ACTIVE` et compare l’identifiant d’autorisation inclus dans l’énoncé signé à l’entrée d’autorisation effective conservée dans le fichier de confiance protégé par `root`. Cette vérification ne relit pas J-c et n’exige pas une queue vide. Si le fichier, l’entrée ou la correspondance manque, est invalide ou incohérente, l’opération signée est refusée ; la voie d’urgence de fermeture du §7.0 reste disponible dans sa portée décidée (D-9 ; formulation propre à ce refus, qui ne décide pas de sa disponibilité pendant le gel, §5.5.1, cas 3). Validée, la fermeture prend effet au `COMMIT` local ; un échec d’ancrage ultérieur ne la rouvre pas, et son entrée reste à ancrer selon la chaîne normale. Les décisions sur les opérations qui ouvrent sont inchangées. Restent ouverts : la représentation de l’entrée d’autorisation dans le fichier de confiance, la preuve qu’elle était déjà effective, sa cohérence avec J-b et J-c et la conduite en cas de divergence ou d’impossibilité d’écrire le journal. **Complété le 27 octobre 2026** (ligne suivante) : le statut `ACTIVE` ne suffit pas à lui seul, et le reflet d’une autorisation invalidée relève de la représentation de la chaîne d’autorisation (§5.5.1, §7.0, §9.2, §11.2 ; §14, point 9) | Décision du propriétaire, 26 octobre 2026 |
| 27 oct. | **Validité de la chaîne d’autorisation des opérations signées qui ferment.** Une opération administrative signée qui ferme ne peut être acceptée que si le credential signataire est autorisé et si sa chaîne d’autorisation n’a pas été invalidée, par exemple parce que sa chaîne d’ajout dépend d’une clé `COMPROMISED` sans réautorisation effective (§5.5.3). Le statut `ACTIVE` dans le fichier de confiance ne suffit pas à lui seul. Si V0 ne peut pas établir cette validité, il refuse l’opération. La fermeture acceptée reste effective au `COMMIT` local, sans relecture de J-c ni attente de l’ancrage. La voie d’urgence D-9 reste distincte et limitée à sa portée déjà décidée, la fermeture de l’interrupteur ; cette décision ne l’étend pas aux autres opérations qui ferment. Les autres règles décidées sont inchangées, notamment l’absence de changement automatique des statuts. Restent ouverts : la représentation de la chaîne d’autorisation dans la politique protégée par `root`, la preuve de sa validité, sa cohérence avec le journal (J-b et J-c) et la conduite en cas de divergence (§5.5.1, §5.5.3, §7.0, §9.2, §11.2 ; §14, point 9) | Décision de conception du propriétaire, 27 octobre 2026 |

Les décisions prises à partir du 27 octobre 2026, au-delà de la dernière ligne du tableau, sont consignées dans l’en-tête et récapitulées au §14, notamment aux points 23 et 24. C’est le cas du principe O1-B, adopté sous condition le 1er novembre 2026 [D] (§5.5.5, L.8, point 8 ; §14, point 23, décision 15), et de l’option 2 pour l’ancrage externe, retenue le même jour [D] (§5.5.5, L.6 ; §14, point 23, décision 16).

### 3.1 Tensions entre décisions [O]

- **T-1 — D-9 et le rôle du propriétaire : tranché le 25 octobre 2026 [D].** Le texte historique de G1 §4.8 (l. 281 à `c41146b`) confiait la réouverture à « un approbateur autorisé distinct de l’acteur GitHub du run concerné ». Le propriétaire n’est pas approbateur depuis le 23 octobre. La décision d’adopter A-1 laissait ce point ouvert ; une décision distincte du même jour l’a tranché :
  - le propriétaire, en qualité d’unique administrateur, peut rouvrir l’interrupteur par SSH, avec une assertion WebAuthn fraîche et UV de son **credential d’administration** ;
  - B reste approbatrice uniquement, sans accès SSH ni rôle d’administration ;
  - cette action n’autorise jamais le propriétaire à approuver une demande de génération.

  - **[D] Clause de séparation (précisée le 25 octobre 2026).** La règle « distinct de l’acteur GitHub du run » s’applique aux approbations associées à un run. Elle ne s’applique pas à la réouverture administrative, qui n’a pas d’acteur de run à comparer.

  **Alignement de la documentation de référence : commité dans `73737dd` et fusionné dans `main` par le PR #62 (`6313648`).** G1 a été aligné : G1 §4.8 (règle de réouverture), tableau de G1 §1.2 (l. 50), ligne D-9 de G1 §10, exigence X6 de G1 §9, et un addendum daté du 25 octobre 2026 en fin de document. La version de G1 sur `main` porte désormais cette attribution.
- **T-2 — D-12 et l’interdiction des sockets.** D-12 prévoit une application sur loopback ou socket Unix, alors que le code interdit `socket`. Toute mise en œuvre de D-12 exigera une exception décidée (§9.3).
- **T-3 — Propriété du code, de ses dépendances, de sa configuration et du fichier de confiance : tranché et complété le 25 octobre 2026 [D].** Tout ce qui peut changer l’application ou son autorisation appartient à `root`. `aidirector` peut le lire et l’exécuter, sans pouvoir le modifier ni le remplacer. Les fichiers SQLite restent au compte de service (§3, §9.2). La conformité du serveur à cette décision n’est pas établie. Toute vérification ou mise en conformité éventuelle relève d’une étape autorisée séparément.

## 4. Option A-1 : orientation adoptée [D], modalités recommandées [R]

### 4.0 Ce qui est décidé et ce qui ne l’est pas

**Décidé par le propriétaire le 25 octobre 2026 [D]**, comme orientation de conception pour confirmer les inscriptions D-5 `PENDING` :

- SSH reste le transport et le contrôle d’accès système ;
- l’autorisation d’une confirmation requiert une assertion WebAuthn du propriétaire, avec UV, liée à l’énoncé exact de l’opération ;
- les credentials d’administration sont distincts de ceux de B ;
- le propriétaire reste administrateur ; il n’est pas approbateur.

**Explicitement non tranché par cette décision [O]** :

- qui peut rouvrir l’interrupteur D-9 (T-1) : **tranché ensuite par une décision distincte du même jour** (§3.1, §7.1). La portée d’A-1 reste la confirmation des inscriptions `PENDING` ; la réouverture relève de la décision T-1, qui emploie le même credential d’administration ;
- RP ID et origine d’administration (§5.1) : **tranchés ensuite par une décision distincte du même jour** (O-3, `ai-director-admin.invalid`). Leur compatibilité réelle reste ouverte ;
- genèse et nombre des credentials d’administration (§5.2). Une décision distincte du même jour a tranché l’orientation générale (§5.2.1) : deux clés matérielles, UV obligatoire, `BE=0` requis, une seule clé suffisant aux opérations courantes. Les règles de la cérémonie de genèse initiale sont aussi fixées (§5.2.2). Restent ouverts les détails de mise en œuvre de cette genèse, la gestion et la perte des clés, et les autres points du §5.2.3.

**Limite reconnue par la décision.** Le client CTAP local déclare lui-même l’origine ; elle n’est pas attestée par un navigateur (§5.1).

**Décidé par le propriétaire le 26 octobre 2026 [D]**, sur la seule liaison des énoncés signés à la reprise de suspension (§5.3, §5.5.1, §11.2 ; §14, point 21) :

- pour les opérations 1 à 4 du §11.2, l’énoncé signé contient toujours le champ `effective_resume_entry_hash` : l’`entry_hash` de la dernière reprise de suspension effective et ancrée, en 64 caractères hexadécimaux minuscules, ou `null` explicite avant toute reprise effective, sans séquence supplémentaire ; le défi le couvre ;
- V0 compare cette valeur à la reprise effective courante au moment de l’`apply` ;
- V1 et E vérifient la signature de l’énoncé sans comparer son identifiant à une reprise ultérieure ; E applique toujours la politique et la suspension courantes.

La création d’une invitation devra suivre la même règle lorsque son protocole signé sera conçu.

**Décidé par le propriétaire le 26 octobre 2026 [D] : compteur des credentials d’administration**, option (b), signal seulement (§5.5.4 ; §14, point 8). Un compteur non croissant, hors le cas `0` suivi de `0`, produit un signal borné et jamais un refus : il ne fait pas passer le nonce à `FAILED` et ne bloque pas l’effet si les autres contrôles réussissent. La nouvelle valeur est enregistrée à chaque opération acceptée. Le signal ne prouve pas un clonage, ne change pas automatiquement le statut du credential et ne suspend pas le service. Les détails du signal borné restent ouverts [O].

**Décidé par le propriétaire le 26 octobre 2026 [D] : statuts des clés d’administration** (§5.5.3 ; §14, point 9). `ACTIVE` est autorisé en V0 et vérifiable en V1. `RETIRED` est refusé en V0 ; ses confirmations antérieures au retrait, selon l’ordre des entrées de journal ancrées, restent vérifiables en V1. `COMPROMISED` est refusé en V0 et en V1, et aucune de ses confirmations n’est utilisable, quelle que soit sa date. Une anomalie `signCount` ne change jamais un statut, et tout changement de statut est explicite, authentifié, journalisé et ancré. Une fois une clé marquée `COMPROMISED`, aucune opération qui ouvre signée par elle ne peut fonder une autorisation future : ses effets futurs sont refusés ou recalculés comme inactifs, sans modification rétroactive, et les opérations qui ferment restent applicables. Sans clé `ACTIVE` permettant d’établir un état valide, le système reste fermé. Un marquage survenu avant l’ancrage d’une entrée que la clé a signée ne mène pas à S4 à lui seul, et une clé ajoutée par la clé compromise n’autorise rien tant qu’une clé `ACTIVE` ne l’a pas réautorisée. Cette réautorisation, explicite, authentifiée, journalisée et ancrée, ne prend effet qu’après l’ancrage requis et pour les opérations futures seulement ; sans chemin sûr, le système reste fermé. La procédure de récupération, de perte et de remplacement des clés, la sortie d’un blocage, les mécanismes d’application aux opérations autres que la confirmation d’inscription, la distinction sûre des cas dans une même queue non ancrée et le format de la réautorisation restent ouverts [O].

**Décidé par le propriétaire le 26 octobre 2026 [D] : liaison à l’autorisation effective de la clé signataire** (§5.3, §5.5.1, §5.5.2, §5.5.3 ; §14, point 9). Chaque énoncé signé pour une opération administrative lie la signature à l’entrée qui autorise effectivement la clé signataire : genèse initiale, ajout ou réautorisation. Pour une opération qui ouvre, V0 vérifie cette liaison à l’`apply`, d’après la chaîne concordante avec l’ancre relue. V1 vérifie qu’elle est cohérente avec l’entrée de l’opération et reste valable. Une assertion préparée avant une nouvelle autorisation ne peut pas être appliquée après celle-ci, et une clé dont la chaîne d’ajout dépend d’une clé `COMPROMISED` ne signe plus rien tant qu’une réautorisation valide n’a pas été ancrée. Pour une opération signée qui ferme, V0 vérifie la liaison contre le fichier de confiance protégé par `root`, sans relire J-c ni exiger une queue vide. **Précisé le 27 octobre 2026 [D] :** il n’accepte l’opération que si le credential signataire est autorisé et si sa chaîne d’autorisation n’a pas été invalidée, le statut `ACTIVE` ne suffisant pas à lui seul ; s’il ne peut pas établir cette validité, il la refuse. La voie d’urgence D-9 reste distincte et limitée à sa portée décidée. Acceptée, la fermeture prend effet au `COMMIT` local, sans attente de l’ancrage. Restent ouverts [O] : le nom du champ, son encodage, la représentation de la genèse et le format de l’ajout et de la réautorisation ; pour les fermetures, la représentation de l’entrée et de la chaîne d’autorisation dans la politique protégée par `root`, la preuve que l’entrée était déjà effective et que la chaîne n’a pas été invalidée, leur cohérence avec le journal (J-b et J-c) et la conduite en cas de divergence ou d’impossibilité d’écrire le journal.

**Décidé par le propriétaire le 27 octobre 2026 [D] : portée de l’invalidation des chaînes d’autorisation** (§5.5.5, J ; §14, point 23).
- Les fermetures ordinaires restent effectives au `COMMIT` local. Le marquage `COMPROMISED`, transition spéciale de la politique d’autorisation, ne prend effet qu’à l’installation de la nouvelle politique protégée par `root`.
- Seule cette politique fait autorité. Un marqueur SQLite ne peut que faire refuser, et sa limite est acceptée.
- Le marquage exige une assertion WebAuthn fraîche avec UV d’un autre credential d’administration valide, sans extension de D-9.
- L’événement est conservé par `root` avant la mise à jour, puis consigné par le service sous la barrière γ1. `root` n’écrit jamais dans SQLite.
- L’ordre n’est garanti que pour des processus qui respectent le protocole. Les refus γ1 suivent J.7.
- Barrière bloquée : après un délai borné, `root` arrête le service et empêche son redémarrage. Si l’arrêt ou l’obtention de la barrière échoue, rien n’est installé et le système reste fermé. La barrière couvre le contrôle de politique d’E. E refuse tant que l’entrée qui consigne la génération courante, initiale comprise, n’est pas incluse dans la tête J-c relue. D-9 reste hors barrière ; elle peut être temporairement indisponible pendant l’arrêt forcé, puis redevient disponible dans sa portée (§5.5.5, L.2, L.5). Ordre de prise décidé : côté service, G puis B en partagé, puis `BEGIN IMMEDIATE` ; côté `root`, G puis B en exclusif (§5.5.5, L.2 à L.4).

Les mécanismes restent ouverts [O].

**Décisions ultérieures.** Les décisions [D] prises par le propriétaire après celles ci-dessus ne sont pas reprises ici : elles sont consignées dans l’en-tête du document et récapitulées au §14, notamment aux points 23 et 24.

**Restent des recommandations [R]**, non décidées, sans requalifier les décisions [D] consignées dans l’en-tête et récapitulées au §14 : le protocole `prepare` / signature / `apply` (§4.2), le vérificateur distinct (§4.3), la forme de l’énoncé et du nonce (§5.3, §5.4 ; sauf le champ `effective_resume_entry_hash` et la liaison à l’autorisation effective de la clé signataire, décidés ci-dessus), V0, V1 et le contrôle d’effectivité (§5.5, §11.2 ; sauf les points décidés ci-dessus, le sort du nonce lors d’un refus à la précondition de V0, déjà consigné au §14, point 21, et le contrôle de la politique d’attestation, déjà décidé au §5.2.7, M.6, ainsi que la politique du compteur d’administration, les statuts des clés et la liaison à l’autorisation effective de la clé signataire, décidés ci-dessus), le contenu et la genèse du fichier de confiance (§5.2 ; sa propriété par `root` est tranchée par T-3, et les statuts des clés ci-dessus, §5.5.3), la règle `sudo` et les détails de mise en œuvre de T-3 (§9.2), la voie d’urgence étendue (§7.0), le manifeste d’autorisation et les mécanismes d’application des invalidations, hors les décisions de portée du 27 octobre ci-dessus (§5.5.5), les modalités de la réouverture (§7.1), le schéma v6 (§8.2) et l’ancrage (§11).

Cette orientation n’autorise ni implémentation, ni création de credential, ni déploiement.

### 4.1 Principe

Trois couches ; seule la troisième autorise.

1. **SSH** (`directoradmin`, clé seulement) : transport et contrôle d’accès système [D, 25 octobre]. Le service n’en voit rien.
2. **Compte système** [R] : la CLI d’administration tourne sous le compte propriétaire de la base (imposé par §2.2), par une règle `sudo` limitée à une commande exacte. Cela prouve seulement « un processus de ce compte ».
3. **Assertion WebAuthn d’un credential d’administration du propriétaire**, avec UV, liée à l’énoncé exact de l’opération [D, 25 octobre]. Modalités [R] : le **stockage** la vérifie entièrement une seule fois, dans la transaction qui applique l’opération (V0). Il revérifie ensuite son intégrité cryptographique en lecture seule (V1), sans la traiter comme une nouvelle authentification, avant d’ancrer l’entrée qui la consigne puis à chaque usage. Une confirmation n’est effective qu’après relecture de l’ancre qui la couvre (contrôle d’effectivité E, §5.5, §11.2).

**Pourquoi A-1 plutôt que A-2 (signature SSH).** A-1 suit le schéma de D-9 et de G1 l. 1127. Il s’appuie sur `python-fido2`, déjà verrouillé (D-13), au lieu d’un parseur de signatures SSH à écrire, et UV et BE/BS y sont déjà encadrés. La décision du 25 octobre retient A-1 ; revenir à A-2 exigerait une nouvelle décision.

### 4.2 Déroulement

1. **`prepare`** (serveur, session SSH) : `admin prepare <opération> <cible>` lit l’état, construit l’énoncé (§5.3), tire et enregistre un nonce `ISSUED`, puis affiche l’énoncé canonique encodé et un résumé. Pour les opérations ordinaires qui ouvrent (opérations 1 à 4 du §11.2), l’énoncé contient l’identifiant de la dernière reprise de suspension effective et ancrée ; `prepare` l’inscrit, mais seul V0 le contrôle (§5.3 ; §5.5.1, étape 4).
2. **Signature** (poste du propriétaire, hors serveur) : un client local reçoit les octets canoniques. Il les décode et les affiche **lui-même**, **recalcule lui-même** le défi (il n’accepte jamais un défi fourni par le serveur), puis demande l’assertion à l’authentificateur par CTAP, avec le RP ID d’administration `ai-director-admin.invalid`, l’origine `https://ai-director-admin.invalid` (§5.1) et UV obligatoire. Avant de toucher la clé, le propriétaire compare l’ID de compte affiché à celui reçu de B par le canal séparé.
3. **`apply`** (serveur, session SSH) : `admin apply` lit l’énoncé et l’assertion **sur l’entrée standard**. Dans une seule transaction `BEGIN IMMEDIATE`, il effectue la vérification initiale V0 (qui comprend, pour les opérations 1 à 4, la reconstruction de l’identifiant de reprise et sa comparaison à la valeur signée) puis, si elle réussit, écrit l’effet, la trace de confirmation, le compteur, le journal et la consommation du nonce. L’ordre exact et le sort du nonce dans chaque cas d’échec sont décrits au §5.5.
4. **Validation pré-ancrage puis ancrage** (après le `COMMIT`) : V1 est exécutée sur la confirmation, puis l’entrée de journal est ancrée hors serveur et relue. Pour une confirmation, le `COMMIT` ne fait qu’**enregistrer** l’opération. Elle ne devient **effective** qu’au moment d’un usage, si le contrôle d’effectivité E réussit : V1, relecture de l’ancre à ce moment, couverture de l’entrée (§11.2).

Le transport passe par la session SSH (copier-coller ou tube). **La frontière d’administration n’exige aucun socket dans le code applicatif.**

### 4.3 Nouveau vérificateur

Il faut un module distinct, par exemple `admin_webauthn_verifier`, avec :

- sa propre politique : RP ID `ai-director-admin.invalid` et origine `https://ai-director-admin.invalid` (décidés, §5.1), comparés par égalité stricte ; refus du RP ID et de l’origine de l’approbation ;
- son propre type d’énoncé ;
- sa propre séparation de domaine, proposée : `AI_DIRECTOR_ADMIN_WEBAUTHN_V1\0` ;
- son propre résolveur, limité aux credentials d’administration actifs et épinglés ;
- ses propres échéances (`T_nonce`, non fixée) ;
- le refus du rejeu par l’état du nonce, pas par le vérificateur seul.

Les contrôles de bas niveau communs (algorithmes, taille RSA, type, `crossOrigin`, UP/UV, BE/BS) peuvent être factorisés dans une modification séparée et revue. Elle ne doit pas changer le comportement du vérificateur d’approbation : ses 23 tests et ses mutations doivent rester inchangés.

## 5. Limites propres à A-1

### 5.1 RP ID et origine dédiés

**Décidé le 25 octobre 2026 (option O-3) [D] :**

- RP ID exact : `ai-director-admin.invalid` ;
- origine exacte déclarée par le client CTAP local : `https://ai-director-admin.invalid`, sans port ni barre oblique finale ;
- cette valeur est fixe pendant toute la vie des credentials d’administration. La changer exigera une nouvelle genèse (§5.2). Ce serait une réinitialisation ultérieure, distincte de la genèse initiale, qui refuse tout fichier existant ; sa procédure reste ouverte (§5.2.2). Elle impliquerait notamment : tous les credentials d’administration seraient recréés, le fichier de confiance remplacé par une opération administrative `root` contrôlée (T-3), et les anciennes clés passées à `RETIRED` (§5.5.3) ;
- aucun endpoint web d’administration ni aucune page publique ne doit utiliser cette origine ;
- l’origine est fournie par le client local et n’est pas attestée par un navigateur. La séparation de RP ID n’empêche pas un poste compromis de tromper son propriétaire ;
- aucun essai avec une vraie clé n’est autorisé par cette décision.

**Faits sur lesquels repose ce choix [F] :**

- RFC 6761 §6.4 : les résolveurs et serveurs DNS doivent répondre NXDOMAIN pour les noms sous `.invalid`, et les registrars « MUST NOT grant requests to register "invalid" names ».
- WebAuthn niveau 3 (W3C), WebAuthn §6.1 : l’authentificateur cloisonne les credentials par `rpIdHash`, l’empreinte SHA-256 du RP ID. Le client n’envoie à l’authentificateur que l’empreinte des données client (WebAuthn §6) : l’authentificateur ne voit jamais l’origine.
- Dans un navigateur, un RP ID n’est accepté que s’il est égal au domaine de l’origine appelante ou s’il en est un domaine parent (WebAuthn §5.1.3 étape 8, WebAuthn §5.1.4 étape 7). Les plateformes non web peuvent définir d’autres règles.
- `python-fido2` 2.2.1 (code lu) : `DefaultClientDataCollector` recopie dans `clientDataJSON` l’origine fournie par le programme. Son contrôle par défaut `verify_rp_id` accepte un RP ID égal à l’hôte d’une origine `https`.

**Ce que la séparation de RP ID protège :**

- un credential d’administration ne peut pas servir sur le RP d’approbation `zephyr-approval.fr`, ni l’inverse ;
- le vérificateur d’approbation refuse une assertion d’administration (§2.3) ;
- un `clientDataJSON` d’approbation ne peut pas être rejoué comme `clientDataJSON` d’administration ;
- aucune page du web public ne peut servir cette origine pour solliciter le credential, puisque le nom ne peut pas être enregistré.

**Ce qu’elle ne protège pas :**

- un programme malveillant sur le poste du propriétaire peut solliciter la clé avec ce RP ID, n’importe quel défi et n’importe quelle origine. Seuls le geste UP/UV et l’attention du propriétaire s’y opposent (§12) ;
- un attaquant qui contrôle le poste (fichier `hosts`, autorité de certification locale de confiance) pourrait servir ce nom localement dans un navigateur. Cela suppose un poste déjà compromis.

**Hypothèses et points ouverts [O] :**

- **Compatibilité réelle, non vérifiée :** le chemin CTAP du poste (probablement `WindowsClient`, qui passe par l’API WebAuthn de Windows) accepte-t-il ce RP ID et cette origine, ou applique-t-il ses propres contrôles ? La clé de sécurité retenue accepte-t-elle ce RP ID ? Un essai avec une vraie clé exigera une autorisation distincte.
- **Certificats :** que les autorités de certification publiques ne délivrent pas de certificat pour un nom interne comme `.invalid` est une hypothèse, non vérifiée ici.
- **Repli :** si la compatibilité échoue, O-1 (sous-domaine non publié de `zephyr-approval.fr`, sans enregistrement DNS générique, sans certificat générique, sans hôte Caddy, avec surveillance Certificate Transparency) n’est qu’une solution de repli. Elle n’est pas adoptée et devra faire l’objet d’une décision séparée.

### 5.2 Enrôlement des credentials du propriétaire (genèse)

**Problème.** Aucun credential d’administration n’existe pour autoriser le premier, et B, sans rôle d’administration, ne peut pas le confirmer (décision du 23 octobre).

> **Statut de cette section.** L’orientation générale du §5.2.1 est une **décision du propriétaire du 25 octobre 2026 [D]**, prise sur sa consigne de suivre les choix recommandés. Elle couvre uniquement : deux credentials sur deux clés matérielles distinctes (principale et secours), UV obligatoire à chaque signature, `BE=0` requis (`BS=0` en découlant selon WebAuthn), et une seule clé suffisant aux opérations courantes. Une seconde décision de conception du même jour fixe les **règles de la cérémonie de genèse initiale** (§5.2.2, règles 1 à 7). Tout le reste de la section (détails de mise en œuvre de la genèse, forme du contrôle de séparation physique, gestion et perte des clés, etc.) reste ouvert [O] ou au stade de piste [R] (§5.2.3). Cette décision n’autorise ni création de clé ou de credential, ni essai matériel, ni modification du dépôt, ni déploiement.

#### 5.2.1 Nombre, rôles et propriétés des credentials

**Décidé le 25 octobre 2026 [D] :**

- **Deux credentials WebAuthn d’administration, sur deux clés matérielles distinctes :**
  - une clé **principale** ;
  - une clé **de secours**.

  Le lieu et les modalités de conservation séparée de la clé de secours ne sont pas fixés.
- **UV obligatoire à chaque signature.**
- **`BE=0` requis.** Un credential d’administration qui déclare `BE=1` est refusé.
- **Une seule des deux clés suffit aux opérations courantes.** Ainsi, la perte d’une clé ne bloque pas immédiatement le système.

**Déjà décidé par ailleurs [D] :**

- les credentials d’administration sont distincts de ceux de B (décision A-1 du 25 octobre, §4.0) ;
- RP ID et origine d’administration : `ai-director-admin.invalid` et `https://ai-director-admin.invalid` (décision du 25 octobre, §5.1).

**Précisions et limites :**

- **UV**, en pratique : à la création, à chaque opération signée (V0, étape 6, §5.5.1) et pour toute preuve de possession.
- **Relation avec la clé SSH.** Un credential WebAuthn d’administration n’est jamais la clé SSH d’administration. Le partage éventuel d’une même clé physique entre les deux reste ouvert (§5.2.3).
- **`BE=0` :**
  - **Règle WebAuthn sur `BS` [F].** Selon WebAuthn §6.1 et WebAuthn §6.1.3, `BS` ne vaut 1 que pour un credential éligible à la sauvegarde (`BE=1`) et actuellement sauvegardé. La combinaison `BE=0`, `BS=1` « is not allowed ». Si `BE=0`, `BS=0` découle donc de cette règle ; le vérificateur d’administration refuserait `BS=1` avec `BE=0`, comme le fait déjà le vérificateur d’approbation (G1 l. 730). De plus, BE est fixé à la création et « MUST NOT change » (WebAuthn §6.1.3).
  - **Portée de BE/BS.** Ces drapeaux décrivent la sauvegarde du credential : un credential `BE=0` est un *single-device credential*. Ils **ne prouvent pas** que deux credentials se trouvent sur deux appareils physiques distincts.
  - **Limite.** Ces drapeaux sont déclarés par l’authentificateur ; sans attestation, rien ne les prouve (même limite que D-4).
- **Une seule clé suffit :**
  - **Contrepartie :** la compromission d’une seule clé, avec son UV, suffit à signer. La protection de la clé de secours (lieu de conservation, PIN distinct) compte donc autant que celle de la clé principale.
  - **[O]** Les opérations qui pourraient exiger les deux clés, par exemple la modification des clés de confiance, restent ouvertes (§5.2.3, §5.7).

#### 5.2.2 Cérémonie de genèse initiale du fichier de confiance

**Règles décidées par le propriétaire le 25 octobre 2026 [D] (décision de conception) :**

1. **Unicité et contexte.** La genèse initiale a lieu une seule fois, hors du service web, alors que le système reste fermé et que Provider demeure CLOSED.
2. **Création des credentials.** Le client CTAP local crée **séparément** les deux credentials décidés au §5.2.1 :
   - UV obligatoire ;
   - RP ID `ai-director-admin.invalid` et origine `https://ai-director-admin.invalid` (§5.1) ;
   - `BE=0`.

   Les clés privées restent dans leurs authentificateurs et ne sont jamais exportées.
3. **Validation des réponses d’inscription avant l’installation.** Les réponses d’inscription elles-mêmes doivent être validées. Il ne faut pas se fier à un simple fichier de clés publiques accompagné d’un booléen « vérifié ».
4. **Séparation physique.** La vérification que les deux credentials proviennent de deux clés physiques distinctes est un **contrôle humain de procédure**, pas une garantie cryptographique WebAuthn.
5. **Installation initiale.** Elle passe par l’opération administrative `root` contrôlée exigée par T-3, et :
   - n’est autorisée que si **aucun fichier de confiance n’existe déjà** ;
   - installe **les deux entrées ensemble** ;
   - refuse toute écriture partielle et tout remplacement.
6. **Protection après installation (règles T-3).** `root` peut modifier le fichier par l’opération contrôlée ; `aidirector` peut le lire et l’utiliser sans le modifier.
7. **Échec fermé.** Toute erreur laisse le système fermé. La genèse n’active pas Provider et ne constitue pas une autorisation de déploiement.

Cette décision ne crée aucune clé, aucun credential ni aucun fichier, n’autorise aucun essai matériel et ne touche à aucun serveur. **Aucun des mécanismes ci-dessous n’existe aujourd’hui.**

**Détails laissés ouverts [O] :**

- **Client local concret :** programme, emplacement (dans le dépôt ou non), dépendances, poste utilisé (§4.2).
- **Forme du transfert** des réponses d’inscription du poste vers le serveur.
- **Format du paquet d’inscription :** contenu exact (par exemple réponses d’inscription complètes, défi utilisé, rôle principal ou secours) et format du fichier de confiance qui en résulte, y compris un éventuel `store_id`.
- **Outil et procédure `root`** qui valident puis installent le fichier. On ne sait pas encore notamment si la base garde une copie ou une empreinte du fichier.
- **Vérification exacte des réponses.** Une proposition technique de contrat minimal figure au §5.2.4 ; elle n’est pas décidée. Pistes, non décidées :
  - `type = webauthn.create` ;
  - défi attendu ;
  - origine et `rpIdHash` exacts ;
  - UP, UV, `BE=0`, `BS=0` ;
  - algorithme autorisé ;
  - identifiants et clés publiques distincts entre les deux credentials ;
  - preuve de possession par une assertion avec UV.

  Format d’attestation accepté : lié au point ouvert sur l’attestation (§5.2.3).
- **Journalisation et ancrage J-b et J-c** de la genèse, par exemple de l’empreinte du fichier installé (§11).
- **Traitement d’un échec** en cours de cérémonie : C-1, O-a et l’échec fermé suivi d’une nouvelle cérémonie complète sont décidés (§5.2.5, H). La procédure physique de reprise sur une clé qui porte un orphelin reste ouverte, comme toute **réinitialisation ultérieure**. La règle « aucun fichier existant, aucun remplacement » vise la genèse initiale ; une nouvelle genèse imposée par un changement de RP ID (§5.1) ou par la perte des deux clés (§5.8) exigerait une procédure distincte, non décidée.
- **Forme concrète du contrôle humain de séparation physique.** Pistes :
  - une seule clé branchée à la fois ;
  - clés identifiées et étiquetées ;
  - vérification que chaque clé, seule, ne signe que pour son propre credential ;
  - consignation.

**Pourquoi la séparation physique n’est pas prouvée.** Ni deux identifiants de credential différents, ni les drapeaux BE/BS ne prouvent que les clés physiques sont distinctes : une même clé peut porter plusieurs credentials pour un même RP ID. WebAuthn ne fournit aucune preuve cryptographique de séparation physique. Le contrôle repose sur l’attention du propriétaire et sur l’intégrité du poste.

Ancien déroulement envisagé, conservé comme piste pour les détails ouverts ; il n’est pas décidé au-delà des règles 1 à 7 ci-dessus :

1. **Création, sur le poste du propriétaire, hors serveur**, une clé à la fois.
2. **Contrôle humain de séparation physique.** Voir les pistes ci-dessus.

   **`excludeCredentials` n’est qu’une aide.** Créer le credential de secours en excluant l’identifiant du premier peut aider à détecter un credential déjà connu de l’authentificateur : l’authentificateur ne renvoie l’erreur que s’il reconnaît un credential de la liste qui lui est lié, après consentement de l’utilisateur (WebAuthn §5.1.3, étape 22). Ce n’est **pas une preuve suffisante de séparation physique**. Le résultat dépend :
   - du client, qui peut ignorer une entrée de la liste selon les indications de transport ; la spécification signale que des indications inexactes peuvent conduire à enregistrer plusieurs credentials sur le même authentificateur (WebAuthn §5.1.3, étape 9) ;
   - des indications de transport fournies ;
   - du comportement déclaré de l’authentificateur.

   Ce comportement n’est pas vérifié sur le chemin CTAP retenu, et aucun essai matériel n’est autorisé.
3. **Preuve de possession** : chaque credential produit une assertion avec UV sur un défi de genèse (piste).
4. **Installation** par l’opération `root` contrôlée, selon les règles 5 et 6. Contenu envisagé : identifiants, clés publiques COSE, rôle, BE, algorithme et `store_id`. Pistes non décidées : la base garderait une copie et une empreinte du fichier, et le stockage refuserait toute opération signée si le fichier et la base divergent.
5. **Trace** : journalisation et ancrage de l’empreinte du fichier (§11), point ouvert.

**Limites.** La genèse repose sur la confiance dans `root` et dans la session SSH qui l’installe (D-15). Elle n’est vérifiable après coup que si l’empreinte du fichier est ancrée (§11). Un poste compromis pendant la cérémonie pourrait faire enregistrer une autre clé publique que celle de la clé du propriétaire (§12).

#### 5.2.3 Points laissés explicitement ouverts [O]

Les décisions du 25 octobre (§5.2.1, et règles de genèse du §5.2.2) ne tranchent aucun des points suivants :

- **les détails de la cérémonie de genèse initiale** : client local concret, forme du transfert, format du paquet d’inscription, outil et procédure `root`, vérification exacte des réponses (proposition au §5.2.4, non décidée), journalisation et ancrage, durée des défis, nombre de tentatives et procédure physique de reprise sur une clé portant un orphelin (§5.2.5, H ; C-1 et O-a y sont décidés), et toute réinitialisation ultérieure (§5.2.2) ;
- **la forme concrète du contrôle humain de séparation physique des deux clés**. Ni BE/BS ni `excludeCredentials` n’en apportent la preuve (§5.2.2) ;
- **la règle d’ajout, de remplacement ou de révocation d’une clé de confiance** (§5.7) ;
- **la procédure en cas de perte des deux clés** (§5.8) ;
- **les opérations qui pourraient exiger les deux clés** (§5.2.1) ;
- **la mise en œuvre de l’attestation.** Son orientation est décidée (§5.2.6, D) : racine approuvée, liste fermée d’AAGUID, refus de `none` sans déclassement silencieux, pas d’attestation `enterprise`. Restent ouverts : le modèle et ses AAGUID, les racines, la source et les mises à jour des métadonnées, les contrôles de validité et de révocation, l’attestation disponible par Windows et CTAP, et la procédure si la politique ne peut pas être satisfaite. L’analyse de leur cycle de vie figure au §5.2.7. Les orientations décidées le 26 octobre 2026 sont au point M ; ce qui exige encore un fabricant, un modèle, une ancre, une licence, un canal ou une durée reste ouvert ;
- **le partage éventuel d’une clé physique avec la clé SSH d’administration** du propriétaire. Les credentials sont distincts, mais avec la même clé physique, une perte ou un vol toucherait les deux couches ;
- **la compatibilité réelle avec Windows, CTAP et le modèle de clé retenu**, y compris le comportement de `excludeCredentials` (§5.1). Un essai matériel exigera une autorisation distincte.

#### 5.2.4 Contrat minimal de validation des réponses de genèse : proposition technique [R]

> **Statut : proposition technique, non décidée.** Elle précise ce que pourrait recouvrir la règle 3 décidée (§5.2.2 : valider les réponses d’inscription avant l’installation). Ni le client CTAP local, ni le vérificateur, ni l’opération `root` n’existent. Cette proposition ne ferme aucun point ouvert du §5.2.3, en particulier la vérification exacte des réponses, et ne modifie aucune décision prise. L’orientation d’attestation décidée ensuite figure au §5.2.6 ; les points B.10, D et F ci-dessous en tiennent compte.

**Acteur supposé.** Un **vérificateur de genèse**, exécuté dans l’opération administrative `root` contrôlée (T-3). Sa forme concrète reste ouverte. Le service web n’y participe pas.

##### A. Défis de genèse

- Chaque défi est tiré par le vérificateur de genèse, qui est la source de confiance : 256 bits aléatoires (`secrets`), comme le nonce du §5.4.
- Un défi distinct par usage :
  - inscription de la clé principale ;
  - inscription de la clé de secours ;
  - preuve de possession de chacune (point D).
- Chaque défi est associé à cette genèse : identifiant de cérémonie, rôle (principal ou secours) et usage (inscription ou possession). Le vérificateur l’enregistre avant de le remettre au client local ; la forme du transfert reste ouverte.
- Le vérificateur compare **exactement**, octet pour octet et en temps constant, le défi retourné dans `clientDataJSON` à celui qu’il a émis pour ce rôle et cet usage.
- Chaque défi sert une seule fois. Une cérémonie échouée ou abandonnée invalide tous ses défis : une nouvelle tentative exige de nouveaux défis. Leur durée de validité n’est pas fixée.

##### B. Contrôles sur chaque réponse d’inscription (WebAuthn §7.1)

1. `clientDataJSON.type` vaut `webauthn.create` (étape 7).
2. Le défi est celui émis pour ce rôle (étape 8, point A).
3. L’origine est exactement `https://ai-director-admin.invalid`, sans port ni barre oblique finale (étape 9, §5.1). `crossOrigin` est absent ou faux, `topOrigin` absent, comme pour le vérificateur d’approbation.
4. `rpIdHash` est l’empreinte SHA-256 de `ai-director-admin.invalid` (étape 14).
5. UP présent (étape 15) ; UV présent, UV étant obligatoire (étape 16, §5.2.1).
6. `BE=0`, exigé par la décision du §5.2.1 ; `BS=0` (étape 17, qui interdit BS sans BE).
7. Données de credential attestées présentes. Identifiant de credential de 16 à 1023 octets : la borne haute vient de l’étape 25, la borne basse est celle du registre v3 (`approval_store.py:143`).
8. Clé publique COSE lisible. Algorithme parmi ceux proposés à la création (étape 20) et dans la liste autorisée (ES256, EdDSA, RS256 d’au moins 2048 bits, provisoire, G1 l. 729 et 761). Pour l’administration, le choix de cette liste reste ouvert.
9. Aucune sortie d’extension non demandée.
10. Déclaration d’attestation : vérifiée selon l’orientation du §5.2.6 [D]. Elle doit être vérifiable contre une racine approuvée, avec un AAGUID de la liste fermée. `none`, un format inconnu, une attestation non vérifiable ou une chaîne non conforme sont refusés, sans déclassement silencieux. Le détail des contrôles de chaîne reste ouvert. Le §5.2.7 distingue deux étapes : la **validation cryptographique** de la signature et de la chaîne (§5.2.7, E.1), puis la **décision de confiance** dans le modèle (§5.2.7, E.2). Il montre aussi que les valeurs par défaut de `python-fido2` ne suffisent à aucune des deux (§5.2.7, D).

**Ce que `python-fido2` ne fait pas [F].** `Fido2Server.register_complete` (2.2.1, code lu) vérifie le type, l’origine par la fonction fournie, le défi, `rpIdHash`, UP, et UV s’il est exigé. Il **ignore l’attestation** dans trois cas :
- la préférence de transmission vaut `none` ;
- aucune fonction `verify_attestation` n’a été fournie, même avec `attestation="direct"`. La fonction par défaut ne fait rien (`server.py:119-122, 155`) ;
- la préférence est absente ou n’est pas une valeur reconnue. Une chaîne inconnue devient `None` (`webauthn.py:344-362` ; `server.py:148, 266-268`).

Il ne contrôle ni BE/BS, ni la liste d’algorithmes, ni la longueur de l’identifiant, ni les doublons, ni `crossOrigin`. Ces contrôles doivent donc être explicites, comme dans le vérificateur d’approbation.

##### C. Contrôles sur l’ensemble de la cérémonie

- Exactement deux inscriptions, un rôle principal et un rôle de secours, chacun une seule fois.
- Identifiants de credential distincts et clés publiques distinctes.
- Aucun identifiant déjà connu du système (étape 26) : aucun ne correspond à un credential d’approbation ni à une inscription en attente.
- Tous les défis appartiennent à cette genèse et ne servent qu’une fois.
- Tout champ manquant, en trop, mal encodé ou incohérent, et tout doublon, fait refuser **toute** la cérémonie. Rien n’est installé, conformément à la règle 5 (ni écriture partielle, ni remplacement).

##### D. Preuve de possession

- **Pourquoi.** Avec l’attestation `none`, la réponse d’inscription ne contient aucune signature faite avec la clé privée du credential. Selon la note de WebAuthn §7.1, étape 26, seule l’auto-attestation contient une telle auto-signature. Rien ne montre alors que la clé publique enregistrée correspond à une clé privée utilisable.
- **Proposition.** Chaque nouvelle clé produit séparément une assertion sur un **défi frais** (point A), distinct de son défi d’inscription :
  - `type = webauthn.get` ;
  - origine exacte et `rpIdHash` attendu ;
  - UP, UV, `BE=0`, `BS=0` ;
  - liste de credentials autorisés réduite à ce seul credential, et identifiant retourné identique ;
  - signature vérifiée avec la clé publique issue de l’inscription.
- **Décidé [D] (§5.2.6) :** la preuve de possession séparée, par assertion avec un défi frais, est maintenue. Une attestation vérifiable contre une racine (Basic ou AttCA) est signée par la clé d’attestation, pas par celle du credential : elle n’apporte pas cette preuve. L’auto-attestation, qui la prouverait, ne satisfait pas la politique retenue, faute de chaîne vers une racine approuvée.
- La valeur du compteur observée pourrait servir de valeur initiale [O]. La politique du compteur est décidée : signal seulement (§5.5.4).

##### E. Du résultat validé à l’installation

- Les entrées du fichier de confiance sont **dérivées par le vérificateur** des réponses validées : identifiant, clé publique COSE, algorithme, rôle, `BE=0`. Elles ne sont jamais reprises d’un résumé fourni par le client, ni d’un booléen « vérifié » (règle 3).
- L’installation suit les règles 5 et 6 : opération `root` contrôlée, seulement si aucun fichier n’existe, les deux entrées ensemble. Tout échec laisse le système fermé et rien d’installé (règle 7).
- La conservation des réponses brutes pour audit, le format du fichier, la journalisation et l’ancrage restent ouverts (§5.2.2).

##### F. Limites

- **Origine déclarée.** L’origine est fournie par le client local, pas attestée par un navigateur (§5.1). Le contrôle d’origine sépare les domaines ; il n’authentifie pas le client.
- **Attestation.** `none` n’apporte aucune provenance d’authentificateur : un authentificateur logiciel, ou un poste compromis, pourrait produire des réponses conformes à tous les contrôles structurels ci-dessus. L’orientation du §5.2.6 refuse donc `none` et exige une attestation vérifiable contre une racine approuvée. Même validée, une attestation ne garantit pas le comportement réel de l’appareil, ne prouve pas que la clé est celle que le propriétaire croyait utiliser, et ne prouve pas la séparation physique (§5.2.6, D).
- **Statut des certificats.** Une chaîne d’attestation dont les signatures sont valides n’est pas, pour autant, conforme à WebAuthn. WebAuthn exige aussi l’accès aux informations de statut des AC intermédiaires (§5.2.7, B.2).
- **Séparation physique.** Ces validations ne prouvent pas cryptographiquement que les deux clés sont physiquement distinctes. Cette séparation reste un contrôle humain de procédure (règle 4, §5.2.2).
- **Confiance dans `root`.** Le vérificateur s’exécute dans l’opération `root` ; sa compromission sort de la protection d’A-1 (T-3, D-15).

##### G. Compatibilité avec les décisions prises

- **T-3 :** le vérificateur fait partie du code d’administration appartenant à `root`. Il s’exécute dans l’opération `root` contrôlée ; `aidirector` ne peut ni le modifier ni écrire le fichier de confiance.
- **RP ID et origine :** contrôles B.3 et B.4 avec `ai-director-admin.invalid` et `https://ai-director-admin.invalid` exactement (§5.1).
- **Système fermé :** la vérification se fait sur le serveur sans accès réseau, avec `python-fido2` et `cryptography` déjà verrouillés. Elle n’exige aucun socket ni service web, et n’ouvre ni l’interrupteur ni Provider. Le transfert entre le poste et le serveur reste ouvert.
  - **Réserve.** La vérification hors ligne n’est complète et conforme que si les ancres de confiance et les informations de statut nécessaires ont été **importées et vérifiées au préalable** (§5.2.7, F et K). Sans ces informations, elle n’est pas conforme à WebAuthn, et le projet ne doit pas la présenter comme telle (§5.2.7, B.2).
- **Décisions inchangées :** deux clés, UV, `BE=0`, une seule clé suffisante (§5.2.1) ; règles 1 à 7 de la genèse (§5.2.2).

#### 5.2.5 Cycle de vie des défis et des tentatives de genèse

> **Statut.** Le propriétaire a retenu le 25 octobre 2026 une partie de cette analyse comme **décision de conception [D]**, sur sa consigne de suivre les recommandations : C-1, O-a, aucun défi venant du client local, et un échec fermé suivi d’une nouvelle cérémonie complète. Le détail figure au point H. Les garanties d’installation (deux entrées ensemble, aucune écriture partielle, aucun remplacement) sont décidées par la règle 5 du §5.2.2 ; seule la technique qui les réalisera reste ouverte. Les autres éléments restent une analyse ou des recommandations [R], ou des points ouverts [O]. La proposition du §5.2.4 n’est pas modifiée. Aucune durée ni aucun nombre de tentatives n’est fixé. Le client CTAP local, le transfert et l’opération `root` ne sont pas spécifiés et n’existent pas.

##### A. Un credential créé n’est jamais approuvé par sa seule création

- La création a lieu sur l’authentificateur, **avant** toute validation par le vérificateur de genèse. Le serveur ne peut ni l’empêcher, ni l’effacer à distance.
- La confiance ne vient que de la présence du credential dans le fichier de confiance installé par l’opération `root` contrôlée (T-3), au terme d’une cérémonie entièrement validée (règles 3, 5 et 7, §5.2.2 ; §5.2.4).
- Ni la création, ni une preuve de possession réussie, ni une validation partielle ne rend un credential digne de confiance.
- Un credential issu d’une cérémonie échouée (credential **orphelin**) peut encore produire des assertions valides pour `ai-director-admin.invalid`. Toute opération signée les refuse, puisqu’il n’est dans aucun fichier de confiance (V0, étape 5, §5.5.1).

##### B. États proposés

**Défi :**
- `ISSUED`, puis `USED` (réponse reçue et validée), `FAILED`, `EXPIRED` ou `ABANDONED` ;
- tous ces états d’arrivée sont terminaux, et un défi est accepté au plus une fois (§5.2.4, A).

**Cérémonie :**
- `OPEN`, puis `INSTALLED`, `FAILED` ou `ABANDONED`, tous terminaux ;
- tout échec d’un défi, d’une validation ou de l’installation fait passer la cérémonie entière à `FAILED`, et tous ses défis encore ouverts à `ABANDONED` ;
- **aucune reprise** d’une cérémonie terminée.

##### C. Où vivent les défis : options

- **C-1. En mémoire d’une seule invocation de l’opération `root`. Retenue le 25 octobre 2026 [D].**
  - Fonctionnement : l’opération tire les défis, les remet au client local, attend les réponses dans la même session, valide puis installe. Si elle s’arrête (interruption, déconnexion SSH, erreur), les défis disparaissent et la cérémonie est abandonnée.
  - Avantages : aucun état persistant à protéger ; aucun défi ressuscité par une restauration ; aucun nettoyage.
  - Inconvénients : les quatre gestes (deux inscriptions, deux preuves de possession) doivent tenir dans une seule session ; la trace d’un échec dépend de la journalisation, qui reste ouverte.
- **C-2. Dans un état persistant appartenant à `root`, distinct du fichier de confiance. Non retenue**, sauf réexamen de C-1 (point H).
  - Fonctionnement : permettrait de reprendre après une interruption.
  - Inconvénients : un état de plus à protéger ; une restauration pourrait faire réapparaître des défis `ISSUED` ; une durée d’expiration devient indispensable ; c’est plus complexe.
- **C-3. Défis tirés par le client local. Écartée par la décision du 25 octobre [D] :** aucun défi ne vient du client local, sinon le vérificateur ne pourrait plus comparer le défi à celui qu’il a émis (§5.2.4, A).

##### D. Expiration

- Aucune durée n’est fixée. Une valeur dépend du client CTAP et de la forme du transfert, qui ne sont pas spécifiés.
- Avec C-1, la borne naturelle est la durée de vie de l’invocation `root`, mesurée par une horloge monotone dans le processus. Une borne maximale `T_genèse` serait à fixer une fois le client et le transfert spécifiés.
- Un défi échu ne peut pas être prolongé ni réémis ; la cérémonie est alors `FAILED`.

##### E. Échec, interruption et reprise

| Situation | État | Conduite proposée |
|---|---|---|
| Validation d’une réponse refusée (§5.2.4, B à D) | Cérémonie `FAILED` | Rien n’est installé. Nouvelle tentative = nouvelle cérémonie, nouveaux défis, nouvelles inscriptions |
| Clé principale validée, clé de secours en échec | Cérémonie `FAILED` | Rien n’est installé : les deux entrées s’installent ensemble (règle 5). La clé principale est **réinscrite** lors de la nouvelle cérémonie ; aucun résultat validé n’est reporté |
| Interruption (déconnexion SSH, arrêt) | `ABANDONED` avec C-1 | Comme un échec : nouvelle cérémonie complète |
| Échec de l’installation après validation | `FAILED` | Rien n’est installé ; nouvelle cérémonie. Les garanties sont **décidées** (règle 5, §5.2.2) : les deux entrées ensemble, aucune écriture partielle, aucun remplacement d’un fichier existant. La technique qui les assure (par exemple une écriture atomique en création exclusive) est un détail d’implémentation **ouvert** |
| Issue d’installation incertaine (arrêt pendant l’écriture) et fichier présent | Bloqué | La genèse initiale est refusée, puisqu’un fichier existe (règle 5). Si ce fichier ne peut pas être validé, le système reste fermé. La résolution relève de la procédure de réinitialisation ultérieure, **ouverte** (§5.2.2) |

Dans tous les cas, le système reste fermé et Provider CLOSED (règles 1 et 7). Aucun échec n’ouvre l’interrupteur ni n’autorise un déploiement.

##### F. Conséquences d’une nouvelle tentative sur la même clé

Analyse. La procédure physique de reprise et les hypothèses ci-dessous restent ouvertes (point H).

- **Credential supplémentaire.** Une nouvelle inscription crée un **nouveau** credential, avec un nouvel identifiant et une nouvelle clé publique. L’ancien reste orphelin et jamais approuvé (point A). Sa réponse d’inscription ne peut pas être rejouée dans la nouvelle cérémonie : son défi est terminal (§5.2.4, A).
- **Credentials découvrables.** S’ils sont demandés, chaque tentative peut occuper un emplacement de stockage sur la clé. [R] Demander des credentials non découvrables (`residentKey = discouraged`, option disponible dans `python-fido2` 2.2.1) : le fichier de confiance fournit de toute façon la liste des credentials autorisés. Hypothèse non vérifiée : certains authentificateurs écrasent un credential découvrable existant pour le même RP ID et le même identifiant d’utilisateur ; ce comportement dépend du modèle.
- **`excludeCredentials` et orphelins.** Si la nouvelle tentative excluait aussi les identifiants orphelins de la même clé, cette clé **refuserait** la création (WebAuthn §5.1.3, étape 22). [R] N’exclure que le credential principal de la cérémonie **en cours** lors de l’inscription de la clé de secours, jamais les orphelins. `excludeCredentials` reste une aide, non une preuve (§5.2.2).
- **Blocage du PIN.** Chaque tentative demande une vérification de l’utilisateur. Les échecs répétés du PIN consomment le compteur d’essais de la clé (`ClientPin.get_pin_retries`, `python-fido2`) et peuvent la bloquer. [R] Limiter le nombre de tentatives par cérémonie et ne jamais relancer automatiquement en boucle. La borne reste à fixer.
- **Compteur de signatures.** Il peut avancer sur la clé à chaque tentative. Sans effet sous la politique décidée (signal seulement, §5.5.4) : une valeur qui augmente ne produit aucun signal, et aucun signal ne refuse.
- **Contrôle humain de séparation physique.** Il est refait intégralement à chaque nouvelle cérémonie (règle 4).
- **Aucun mélange entre cérémonies.** Les deux entrées installées proviennent de la **même** cérémonie réussie. Combiner le credential d’une cérémonie avec celui d’une autre est refusé.

##### G. Options pour les orphelins

- **O-a. Les ignorer. Retenue le 25 octobre 2026 [D].** Un orphelin n’est jamais approuvé ni installé. La confiance ne vient que des deux entrées validées installées dans le fichier de confiance, et une inscription n’est valable qu’avec un défi frais.
- **O-b. Les consigner dans une liste de refus** appartenant à `root`, consultée pour toute installation ultérieure (genèse, ajout ou réinitialisation). Défense en profondeur et aide à l’audit, au prix d’un état de plus. **Non retenue.**
- **O-c. Récupérer un orphelin par une simple nouvelle preuve de possession, sans réinscription. Écartée :** cela accepterait un credential dont le défi d’inscription est terminal, contre §5.2.4 A.

##### H. Décision du 25 octobre 2026, recommandations restantes et points ouverts

**Décidé [D]** (décision de conception du propriétaire, sur sa consigne de suivre les recommandations) :

- **C-1 :** les défis de genèse sont conservés uniquement en mémoire, pendant une seule invocation `root`. Aucune reprise après une interruption.
- **O-a :** un credential laissé orphelin par une cérémonie échouée n’est jamais approuvé ni installé. La confiance vient uniquement des deux entrées validées installées dans le fichier de confiance.
- **Aucun défi ne vient du client local.** Celui-ci ne fait que présenter les réponses au vérificateur de confiance.
- **Échec fermé et cérémonie complète.** Toute interruption ou erreur laisse le système fermé. Une nouvelle cérémonie utilise des défis frais et doit produire deux entrées validées ensemble.
- **Aucune durée ni aucun nombre de tentatives n’est fixé** tant que le client local et le transfert ne sont pas définis.
- **Réexamen de C-1.** C-1 devra être réexaminé si le transfert ne permet pas de terminer les deux inscriptions et les deux preuves de possession dans une seule invocation `root`.

**Rappel : garanties d’installation déjà décidées [D] (règle 5, §5.2.2).** Les deux entrées sont installées ensemble, sans écriture partielle et sans remplacement d’un fichier existant. Ce ne sont pas des recommandations. Seule la technique qui réalisera ces garanties (par exemple une écriture atomique en création exclusive) reste un détail d’implémentation ouvert (ci-dessous).

**Recommandations encore non décidées [R] :**

- consignation des identifiants orphelins dans la trace de la cérémonie, si la journalisation retenue le permet ;
- credentials non découvrables, exclusion limitée au credential principal de la cérémonie en cours, nombre de tentatives borné (point F).

**Restent ouverts [O] :**

- la **procédure physique de reprise** sur une clé qui porte déjà un credential orphelin ;
- les **hypothèses** sur les credentials découvrables (écrasement éventuel selon le modèle), les **limites de stockage** de la clé et les **tentatives de PIN** (compteur et risque de blocage) (point F) ;
- `T_genèse` et la borne du nombre de tentatives, à fixer une fois le client local et le transfert définis ;
- la **technique d’installation** qui réalisera les garanties décidées de la règle 5 (par exemple écriture atomique en création exclusive), détail d’implémentation ;
- la sortie d’un blocage par un fichier présent après une issue incertaine, qui relève de la procédure de réinitialisation ultérieure (§5.2.2).

##### I. Cohérence vérifiée

- **§5.2.2 :** C-1 et O-a respectent les règles décidées :
  - genèse unique et hors du service web (règle 1) ;
  - création par le client local, qui ne fournit aucun défi (règle 2) ;
  - réponses validées par le vérificateur (règle 3) ;
  - installation des deux entrées ensemble, sans remplacement (règle 5) ;
  - échec fermé (règle 7).
- **§5.2.3 :** les points qu’il laisse ouverts le restent : attestation, gestion et perte des clés, réinitialisation ultérieure.
- **§5.2.4 :** inchangé ; il reste une proposition technique. C-1 précise seulement où vivent les défis : en mémoire de l’invocation `root` qui les a émis. Usage unique, invalidation en cas d’échec (A) et entrées dérivées des seules réponses validées (E) y sont cohérents.
- **T-3 :** les défis et la cérémonie restent dans le processus `root` (aucune liste de refus, O-b n’étant pas retenue) ; `aidirector` n’y participe pas et ne peut pas écrire le fichier de confiance.
- **Règle 5 (installation initiale sans remplacement) :** respectée. L’analyse identifie le blocage possible par un fichier présent après une issue incertaine, et le renvoie à la procédure de réinitialisation, ouverte.
- **Système fermé :** tout échec, toute interruption et tout blocage laissent le système fermé et Provider CLOSED.

#### 5.2.6 Politique d’attestation de la genèse

> **Statut.** Le propriétaire a retenu le 25 octobre 2026 une **orientation de conception [D]**, sur sa consigne de suivre les choix recommandés (point D) : attestation vérifiable contre une racine explicitement approuvée et une liste fermée d’AAGUID ; refus de `none`, des attestations inconnues ou non vérifiables et des chaînes non conformes, sans aucun déclassement silencieux ; preuve de possession séparée maintenue ; pas d’attestation `enterprise` à ce stade. Les éléments de mise en œuvre restent ouverts (point D). Aucune clé, aucun essai, aucune racine de confiance ni aucune liste d’AAGUID n’est créé ou installé. Aucune compatibilité n’est présumée.

##### A. Faits

**WebAuthn niveau 3 (Recommandation W3C du 25 août 2026, `REC-webauthn-3-20260825`) :**
- Types d’attestation (WebAuthn §6.5.3) :
  - **Basic** et **AttCA** : une clé d’attestation certifiée signe l’inscription ;
  - **Self** : l’authentificateur « uses the credential private key to create the attestation signature » ;
  - **None** : « no attestation information is available ».
- À l’inscription, l’étape 24 de WebAuthn §7.1 note que, faute d’attestation vérifiable, la RP admet qu’il n’existe « no cryptographic proof that the public key credential has been generated by a particular authenticator model ». La note de l’étape 26 indique que seuls les types autres que l’auto-attestation ne contiennent pas d’auto-signature prouvant la possession.
- Préférences de transmission (WebAuthn §5.4.7) :
  - `none` : le client remplace toute déclaration qui n’est pas une auto-attestation par une déclaration `none`. C’est la valeur par défaut, et les valeurs inconnues se comportent comme elle ;
  - `indirect` : le client peut passer par une autorité d’anonymisation ;
  - `direct` : déclaration transmise telle que l’authentificateur l’a produite ;
  - `enterprise` : attestation pouvant identifier l’authentificateur de façon unique, seulement si la configuration l’autorise pour ce RP ID.
- L’AAGUID « is not provably authentic without attestation » (WebAuthn §6).
- La RP « MUST have access to certificate status information for the intermediate CA certificates » (paragraphe qui suit les étapes de WebAuthn §7.1). Les conséquences pour une vérification hors ligne sont au §5.2.7 (B.2 et F).

**`python-fido2` 2.2.1 (code lu dans le wheel dont l’empreinte SHA-256 est celle de `uv.lock:127` ; détail et lignes au §5.2.7, D) :**
- Formats pris en charge : `none`, `packed` (Basic avec `x5c`, Self sans), `fido-u2f`, `tpm`, `android-key`, `android-safetynet`, `apple`.
- Le format `packed` compare l’extension AAGUID du certificat à l’AAGUID des données d’authentificateur **seulement si l’extension est présente**. Si elle est absente, ce contrôle est sauté (`packed.py:78-79`). Seul le premier certificat de `x5c` reçoit les contrôles de profil (version 3, `CA=false`, champs du sujet).
- `AttestationVerifier` refuse l’attestation (`UntrustedAttestation`) si `ca_lookup` ne fournit pas de racine. En revanche, si une `ca_lookup` renvoie une racine pour un résultat Self ou None (chemin de confiance vide), l’attestation est **acceptée** : la vérification de chaîne porte alors sur un seul certificat et ne contrôle rien (`base.py:105-137, 249-258`). Par défaut, le format `none` n’est pas pris en charge et lève `UnsupportedType`. Le commentaire du code invite toutefois l’appelant à « allow the registration » (`base.py:198-203, 240-247`).
- **`verify_x509_chain` ne vérifie que les signatures** de chaque maillon par le suivant. Elle ne contrôle ni dates de validité, ni révocation, ni contraintes d’AC (BasicConstraints, longueur de chemin, KeyUsage).
- `Fido2Server.register_complete` **ignore l’attestation** si la préférence vaut `none`, si elle est absente ou inconnue, ou si aucune fonction de vérification n’est fournie (§5.2.4, B).
- `mds3` :
  - `parse_blob(blob, trust_root)` vérifie la signature et la chaîne `x5c` du BLOB, avec la même limite que `verify_x509_chain`. Il ne lit ni `nextUpdate`, ni `no`, ni aucune CRL, et ne télécharge rien. Avec `trust_root=None`, il **ne vérifie rien** et se contente d’un avertissement dans le journal ;
  - `MdsAttestationVerifier` n’écarte par défaut que les entrées dont un rapport vaut `REVOKED`. Son filtre `ATTESTATION_KEY_COMPROMISE` ne compare que le champ `certificate` au chemin `x5c` (§5.2.7, D).
- **`Fido2Client`**, qui parle directement à la clé par CTAP, renvoie la déclaration d’attestation de l’authentificateur **telle quelle**, quelle que soit la préférence demandée (hors cas `enterprise`). **`WindowsClient`** transmet la préférence à l’API WebAuthn de Windows, qui décide. Si aucune préférence n’est donnée, il demande `none` (`client/windows.py:197-199`).

**Hypothèses non vérifiées :**
- le comportement de l’API Windows pour une attestation `direct` avec le RP ID `ai-director-admin.invalid` ;
- le type d’attestation produit par le modèle de clé retenu ;
- la taille réelle des lots de certificats d’attestation Basic du modèle retenu. WebAuthn §14.4.1 cite comme repère l’exigence de [UAFProtocol] : au moins 100 000 appareils par certificat d’attestation ;
- la disponibilité d’une attestation `enterprise` pour ce RP ID.

##### B. Options

| | **AT-0 : `none`** | **AT-1 : auto-attestation (`packed` sans `x5c`)** | **AT-2 : attestation vérifiable par une racine de confiance (Basic ou AttCA)** | **AT-3 : attestation `enterprise`** |
|---|---|---|---|---|
| Ce qu’elle prouve | Aucune provenance d’authentificateur. La réponse reste vérifiable structurellement : type, défi, origine, `rpIdHash`, drapeaux déclarés, format de l’identifiant et de la clé (§5.2.4, B). Aucune signature du credential à l’inscription : la possession doit être vérifiée séparément | Que l’inscription est signée par la clé privée du credential (possession) ; cohérence interne de la réponse | Une fois validée, la signature lie cryptographiquement les données qu’elle couvre (données d’authentificateur, dont l’AAGUID, la clé publique et les drapeaux, et l’empreinte des données client) à une clé d’attestation chaînée jusqu’à une racine admise. Elle permet une décision de confiance, selon cette racine et les métadonnées admises, sur le modèle de l’authentificateur | Comme AT-2, avec un identifiant éventuellement propre à l’appareil |
| Ce qu’elle ne prouve pas | Modèle, authenticité de l’AAGUID, véracité des drapeaux | Provenance et modèle ; un logiciel peut produire une auto-attestation valide avec des drapeaux mensongers | Le comportement réel de chaque appareil (honnêteté des drapeaux, absence de défaut : hypothèse de confiance dans le fabricant) ; que la clé est **celle que le propriétaire croyait utiliser** (un attaquant pourrait utiliser sa propre clé authentique du même modèle) ; que deux credentials sont sur deux appareils physiques distincts (un même certificat de lot peut couvrir de nombreuses clés) ; la possession de la clé privée du credential (signature faite par la clé d’attestation) | La disponibilité pour ce RP ID ; elle ne remplace pas le contrôle humain |
| Données exposées | AAGUID éventuel, non authentifié | Idem | Modèle (AAGUID authentifié), certificat de lot | Identifiant unique possible |
| Confiance à configurer | Aucune | Aucune | Ancres de confiance approuvées et épinglées. Selon Metadata Statement §4, une ancre peut être une racine, une AC intermédiaire ou le certificat d’attestation lui-même. S’y ajoutent les informations de statut des AC intermédiaires (WebAuthn §7.1) et, si elles sont retenues, des métadonnées obtenues hors serveur et vérifiées (§5.2.7) | Configuration d’entreprise chez le fabricant ou sur la plateforme |
| Chemin CTAP local | `Fido2Client` renvoie l’attestation brute : le vérificateur doit ignorer la déclaration. `WindowsClient` peut la remplacer | Possible seulement si le modèle produit de l’auto-attestation : on ne peut pas l’imposer | `Fido2Client` la transmet ; `WindowsClient` dépend de l’API Windows (non vérifié) | Peu probable pour un RP ID `.invalid` (hypothèse) |
| Coût et risque | Nul | Faible ; dépend du modèle | Gestion des ancres et des artefacts sous T-3. Dates, statut et contraintes d’AC à contrôler en plus de `verify_x509_chain`. Valeurs par défaut de `python-fido2` à neutraliser explicitement. Métadonnées à mettre à jour selon une procédure contrôlée. Une révocation ultérieure peut toucher les deux clés si elles sont du même modèle. Échec fermé si l’attestation est absente (§5.2.7) | Élevé ; hors de portée probable |

##### C. Analyse au regard du projet

- **Menace principale à la genèse :** un poste compromis qui substitue une clé logicielle aux clés du propriétaire (§12).
  - AT-0 et AT-1 ne s’y opposent pas.
  - AT-2 oblige l’attaquant à disposer d’un authentificateur matériel authentique du modèle autorisé. La menace est réduite, pas supprimée.
- **Drapeaux décidés** (UV, `BE=0`, §5.2.1) : seul AT-2 les fait garantir par un authentificateur certifié. Avec AT-0 et AT-1, ils restent déclaratifs.
- **Possession :** seule AT-1 la prouve à l’inscription. Avec AT-0 et AT-2, la preuve de possession séparée du §5.2.4 (point D) reste nécessaire.
- **Confidentialité :** les clés sont celles du propriétaire, pour un RP unique et non public. Exposer le modèle n’est pas un enjeu ici.
- **Séparation physique : aucune option ne la prouve.** Deux clés du même modèle partagent l’AAGUID et souvent le certificat de lot. Même AT-3 dépendrait d’une configuration improbable. Elle reste un **contrôle humain** (règle 4, §5.2.2).

##### D. Orientation décidée le 25 octobre 2026, portée et points ouverts

**Orientation de conception décidée [D]** (sur la consigne du propriétaire de suivre les choix recommandés) :

- **Attestation vérifiable** contre une **racine explicitement approuvée**, et **liste fermée d’AAGUID autorisés** (option AT-2).
- **Refus** des attestations `none`, des formats inconnus, des attestations non vérifiables et de toute chaîne qui ne respecte pas la politique. **Aucun déclassement silencieux** vers une politique plus faible.
- **Preuve de possession séparée maintenue :** une assertion par nouvelle clé, avec un défi frais (§5.2.4, D). Une attestation Basic n’apporte pas cette preuve.
- **Pas d’attestation `enterprise`** ni d’identifiant unique par appareil à ce stade (AT-3 non exigée).
- **Échec fermé :** si l’attestation requise ne peut pas être vérifiée, la cérémonie échoue et le système reste fermé (règle 7, §5.2.2).

Conséquence : l’auto-attestation (AT-1), qui n’a pas de chaîne vers une racine approuvée, ne satisfait pas cette politique.

**Portée exacte d’une attestation validée.** Il faut distinguer trois niveaux :

1. **Données signées (fait cryptographique).** La signature d’attestation, une fois vérifiée, lie cryptographiquement les éléments qu’elle couvre :
   - les données d’authentificateur : `rpIdHash`, drapeaux UP, UV, BE et BS, compteur, AAGUID, identifiant et clé publique du credential ;
   - l’empreinte des données client.

   Elle les lie à une clé d’attestation dont la chaîne aboutit à une ancre de confiance admise : racine, AC intermédiaire ou certificat d’attestation (Metadata Statement §4). Rien de ce qui n’est pas couvert par cette signature n’est prouvé. La validité de la chaîne au-delà des signatures (dates, contraintes, statut) n’est pas établie par `python-fido2` (§5.2.7, D et E.1).
2. **Identité de modèle (établie par la politique).** Le rattachement à un modèle précis découle de la politique : ancre approuvée, liste fermée d’AAGUID, cohérence entre l’AAGUID et le certificat, et métadonnées admises le cas échéant. Pour la cohérence AAGUID–certificat, `python-fido2` ne compare l’extension AAGUID du certificat, pour `packed`, que si elle est présente (§5.2.7, D.2). C’est une décision de confiance, valable dans les limites de cette politique.
3. **Hypothèses de confiance dans le fabricant.** Que l’appareil se comporte réellement comme déclaré (UV effectif, `BE=0` véridique, clé privée non exportable, absence de défaut), et que la clé d’attestation n’a pas été compromise. Ces points ne sont pas prouvés par l’attestation : ils reposent sur la confiance accordée au fabricant et aux métadonnées.

Une attestation validée **ne garantit pas** le comportement réel de tout appareil. Elle **ne prouve pas** que la clé est celle que le propriétaire croyait utiliser. Elle **ne prouve pas** que deux credentials sont sur deux appareils physiques distincts : ce point reste un contrôle humain (règle 4, §5.2.2).

**Éléments de mise en œuvre, non décidés [R] :**
- préférence de transmission `direct` ;
- racine et liste d’AAGUID dans un fichier de configuration appartenant à `root`, en lecture seule pour `aidirector`, modifiable seulement par l’opération `root` contrôlée (T-3) ;
- contrôles complémentaires de la chaîne, puisque `verify_x509_chain` ne vérifie que les signatures ;
- cycle de vie des ancres, de la liste d’AAGUID, des métadonnées et des informations de statut. Les orientations sont décidées le 26 octobre 2026 (§5.2.7, M) ; leur mise en œuvre détaillée reste [R] (§5.2.7, K).

**Restent ouverts [O]** (analyse au §5.2.7, récapitulatif au §14, point 22) :
- le modèle de clé exact et ses AAGUID. M.7 recommande deux modèles différents ;
- les ancres de confiance concrètes. Leur source d’approbation est décidée (M.1), mais la source indépendante et le canal hors bande restent ouverts ;
- le poste, le canal et la cadence de récupération des métadonnées. Le mode M-2 et l’import `root` sont décidés (M.2) ;
- la forme des informations de validité et de révocation. Leur exigence est décidée (M.5, M.8), en distinguant la chaîne du BLOB MDS et les AC intermédiaires de l’attestation (§5.2.7, F) ;
- l’attestation réellement disponible par le chemin Windows et CTAP. Aucune compatibilité n’est présumée et aucun essai matériel n’est autorisé ;
- la procédure si la politique ne peut pas être satisfaite. Tout changement vers une politique plus faible exigerait une décision séparée ; jusque-là, le système reste fermé ;
- les détails de la conduite si une ancre, une AC intermédiaire ou un modèle est révoqué après la genèse. Le principe est décidé (M.6 : fermeture des opérations qui ouvrent, revue, aucun changement automatique de statut) ; la forme de la reprise reste ouverte.

##### E. Rappel

L’attestation, quelle qu’elle soit, **ne prouve pas à elle seule** que deux clés physiques distinctes sont présentes. Elle ne prouve pas non plus que la clé est celle que le propriétaire croyait utiliser. Elle ne change ni les décisions des §5.2.1 et §5.2.2, ni le statut fermé du système.

#### 5.2.7 Cycle de vie de l’attestation AT-2 : analyse, décisions du 26 octobre 2026 [D] et recommandations restantes [R]

> **Statut.** Le propriétaire a tranché le **26 octobre 2026** neuf orientations de conception sur ce cycle de vie. Elles sont inscrites au point M comme décisions [D] et rappelées là où elles s’appliquent (C, F, G, J, K, L). Tout ce qui n’est pas repris au point M reste une analyse, une recommandation [R] ou un point ouvert [O]. En particulier, rien n’est fixé sur ce qui exige encore un fabricant, un modèle, une ancre précise, une licence, un canal, une durée ou un détail technique non établi. Cette section précise la mise en œuvre de l’orientation décidée au §5.2.6 (D). Elle couvre :
> - l’approbation des ancres de confiance ;
> - la liste d’AAGUID ;
> - la source et la mise à jour des métadonnées ;
> - la vérification hors ligne ;
> - la révocation après la genèse ;
> - le comportement si les métadonnées sont absentes, périmées ou indisponibles.
>
> Elle ne choisit ni fabricant, ni modèle, ni ancre, ni fournisseur de métadonnées, ni durée, ni cadence. **Seules les orientations du point M sont des décisions du propriétaire ; les autres recommandations ne le sont pas.** Ni ces décisions ni cette section ne créent d’artefact, ni n’autorisent essai matériel, accès réseau du serveur ou modification du serveur. Les décisions prises et celles qui restent à prendre sont récapitulées au §14, point 22. D-5 reste non résolu ; Provider = CLOSED et NO-GO restent en vigueur.

##### A. Sources vérifiées le 26 octobre 2026

- **WebAuthn niveau 3**, Recommandation W3C du 25 août 2026 (`https://www.w3.org/TR/2026/REC-webauthn-3-20260825/`), désignée ci-dessous « WebAuthn ».
- **FIDO Metadata Service v3.1**, Proposed Standard du 21 mai 2025 (`fido-metadata-service-v3.1-ps-20250521`), désigné « MDS ». Les mots clés en majuscules s’y lisent selon RFC 2119 (MDS §1.1). Les formulations en minuscules (« should », « must ») ne sont pas des exigences au sens de RFC 2119.
- **FIDO Metadata Statement v3.1**, Proposed Standard du 21 mai 2025 (`fido-metadata-statement-v3.1-ps-20250521`), désigné « MS ». Le texte lu n’énonce pas de convention de mots clés ; ses formulations sont donc citées telles quelles.
- **FIDO Technical Glossary v2.1** (Proposed Standard du 23 mai 2022), auquel MDS §1 renvoie pour ses définitions.
- **`python-fido2` 2.2.1.** Code lu dans le wheel publié sur PyPI. Son empreinte SHA-256 (`ed397da9…749f`) est celle de `approval_service/uv.lock:127`, et son contenu est identique à celui du cache `uv` local. Les numéros de ligne renvoient à ce wheel.
- **`cryptography` 50.0.2** (`uv.lock:57`). Seules les signatures de type (`hazmat/bindings/_rust/x509.pyi`) ont été lues. Aucun comportement n’a été exécuté ni testé.
- La page d’information de la FIDO Alliance sur le service de métadonnées n’a pas pu être lue directement. Rien de ce qu’elle contient n’est repris ici comme fait.

##### B. Faits normatifs WebAuthn [F]

1. **Ancres de confiance (WebAuthn §7.1, étapes 23 et 24).**
   - La RP obtient la liste des ancres acceptables « from a trusted source or from policy ». MDS n’y est cité qu’à titre d’exemple.
   - La chaîne doit aboutir à un certificat racine acceptable, « or is itself an acceptable certificate ».
   - Une attestation non jugée digne de confiance SHOULD faire échouer la cérémonie. La note de l’étape 24 permet (MAY) de l’enregistrer comme une auto-attestation, ce que l’orientation du §5.2.6 exclut.
2. **Informations de statut des AC intermédiaires** (paragraphe qui suit les étapes de WebAuthn §7.1).
   - Texte : « if certificates are being used, the Relying Party MUST have access to certificate status information for the intermediate CA certificates ». La RP MUST aussi pouvoir construire la chaîne si le client ne l’a pas fournie.
   - Ce texte ne prescrit ni mécanisme (CRL, OCSP, métadonnées), ni accès réseau au moment de la vérification.
   - **Lecture retenue ici, qui est une interprétation et non un texte :** l’exigence peut être satisfaite hors ligne par des informations de statut **importées et vérifiées avant** la vérification. Elle **n’est pas satisfaite** en leur absence. Une vérification hors ligne sans ces informations ne doit pas être présentée comme conforme.
3. **AC intermédiaire révoquée (WebAuthn §13.4.5).** La recommandation est conditionnelle : elle s’applique si la validation échoue à cause d’une AC intermédiaire révoquée **et** si la politique de la RP exige alors un refus.
   - Il est RECOMMENDED de désinscrire les credentials inscrits **après la date de compromission** avec une chaîne qui aboutit à cette AC, ou de leur donner un niveau de confiance équivalent à l’auto-attestation.
   - Il est RECOMMENDED de conserver les certificats d’AC intermédiaire vus à l’inscription.
4. **Compromission d’une AC (WebAuthn §13.3.2).**
   - Les paires de clés d’attestation restent sûres, mais leurs certificats ne sont plus dignes de confiance.
   - Si l’AC racine change, les RP MUST mettre à jour leurs racines de confiance.
   - Un certificat d’attestation dont la clé privée est compromise MUST être révoqué par l’AC émettrice.
5. **Hiérarchie et AAGUID (WebAuthn §13.3.1, §8.2, §8.2.1).**
   - Une hiérarchie à trois niveaux est RECOMMENDED, avec une AC émettrice par modèle.
   - Si la racine d’attestation n’est pas dédiée à un seul modèle, l’AAGUID SHOULD figurer dans le certificat d’attestation (WebAuthn §13.3.1, considérations pour les authentificateurs, tous formats).
   - Pour le seul format `packed`, les exigences de certificat de WebAuthn §8.2.1 vont plus loin : l’extension `id-fido-gen-ce-aaguid` (1.3.6.1.4.1.45724.1.1.4) MUST être présente si la racine sert à plusieurs modèles. Il s’agit d’une exigence sur le certificat émis, pas d’un contrôle imposé à la RP.
   - Du côté de la RP, la procédure de vérification de WebAuthn §8.2 compare l’extension à l’AAGUID **si elle est présente**. WebAuthn §8.2.1 « suggère » (sans mot clé normatif) de rechercher l’extension.
   - Les extensions AIA/OCSP et le point de distribution de CRL sont OPTIONAL dans le certificat d’attestation, « as the status of many attestation certificates is available through authenticator metadata services ».
6. **Limites (WebAuthn §13.4.4, non normatif).** L’attestation ne permet pas de vérifier que l’objet vient de l’authentificateur voulu. Au mieux, elle oblige l’attaquant à utiliser un authentificateur authentique du même modèle.
7. **Aucune revérification.** L’attestation n’est vérifiée qu’à l’inscription (WebAuthn §7.1) ; une assertion (WebAuthn §7.2) n’en contient pas. Un changement ultérieur du statut d’un modèle ou d’une AC n’a donc aucun effet sur les assertions sans une politique explicite.

##### C. Faits normatifs MDS et MS [F], et ce qu’ils ne garantissent pas

| Élément | Ce que disent les spécifications | Ce qu’elles ne garantissent pas |
|---|---|---|
| Recours à MDS | Facultatif : la RP « could also obtain metadata directly from authenticator vendors or other trusted sources » (MDS §3). Un environnement à haute sécurité peut se limiter à une source propriétaire (MDS §4, non normatif) | Que le modèle retenu figure dans le BLOB |
| Téléchargement par le serveur | « The FIDO Server MUST be able to download the latest metadata BLOB object from the well-known URL when appropriate ». Le serveur télécharge et met en cache l’ancre de signature et dispose des CRL (MDS §3.2). Le glossaire FIDO définit le « FIDO Server » comme « server software typically deployed in the relying party’s infrastructure ». La RP décide si elle utilise le service (MDS §3) | Les sources ne disent pas si un poste de récupération distinct, suivi d’un import sur le serveur, fait partie du rôle de « FIDO Server ». **Décidé (M.2) :** le projet traite son architecture comme une adaptation, dont la conformité stricte à MDS §3.2 n’est pas établie (K.1) |
| Signature du BLOB | Le serveur vérifie la signature et SHOULD ignorer un BLOB dont la signature est invalide (MDS §2.2, §3.2). Chaîne de signature : celle de `x5u` (même origine web, vérification selon RFC 5280 et contrôle de révocation de tous les maillons, MUST) ; à défaut celle de `x5c` ; à défaut l’ancre elle-même (MDS §3.2) | L’exactitude du contenu des déclarations, fourni par les fabricants (MDS §4) |
| Révocation de la chaîne du BLOB | Pour les certificats de la signature, « the certificate revocation information MUST be available in the form of CRLs » (MDS §3.2). Ces exigences « are only applicable to the MDS BLOB payload certificates » | Le statut des AC des fabricants : le contrôle des CRL pour les certificats des déclarations est laissé « up to the server vendors » (MDS §3.2) |
| `no` | Numéro de série que l’éditeur MUST incrémenter, consécutif et strictement monotone (MDS §3.1.6). Le serveur SHOULD ignorer un BLOB dont `no` est inférieur ou égal à celui du dernier BLOB en cache (MDS §3.2) | Aucune protection contre un BLOB ancien si aucun `no` n’a été conservé. Aucune garantie de fraîcheur |
| `nextUpdate` | Date à laquelle la prochaine mise à jour sera fournie au plus tard (MDS §3.1.6) ; date à laquelle le téléchargement SHOULD avoir lieu au plus tard (MDS §3.2). Un BLOB est publié à cette date même sans changement (MDS §4) | Aucune règle d’invalidité : la spécification ne déclare pas inutilisable un BLOB dont `nextUpdate` est dépassé. Le refus et la suspension pour ce motif sont des **règles propres au projet** (M.5, M.6), pas des exigences MDS |
| Mise à jour | La RP décide de la fréquence (MDS §2.2). Le guide d’implémentation (MDS §4, non normatif) conseille une vérification quotidienne pour des applications typiques | Aucune cadence n’est retenue ici. La suspension décidée en M.6 dépend du `nextUpdate` publié, pas d’une cadence propre au projet |
| Statuts | Le dernier `StatusReport` MUST refléter le statut courant (MDS §3.1.3). `REVOKED` : les RP SHOULD refuser toute nouvelle inscription du modèle (MDS §3.1.4.1). `ATTESTATION_KEY_COMPROMISE` : la RP SHOULD examiner le champ `certificate` pour identifier le lot ; si ni `batchCertificate` ni `certificate` n’est renseigné, elle « should » (minuscule) refuser toute nouvelle inscription (MDS §3.1.4.2). Pour les autres statuts, la conduite relève de la RP (MDS §3.2). Les valeurs inconnues MUST être ignorées silencieusement (MDS §3.1.4.3) | Qu’un modèle `FIDO_CERTIFIED*` se comporte comme déclaré ; que la certification couvre les clés multi-appareils (MDS §3.1.3) ; un statut propre à un appareil |
| `authenticatorVersion` | Version de micrologiciel à laquelle se rapporte un rapport (MDS §3.1.3). La version courante peut figurer dans l’extension `id-fido-gen-ce-fw-version` du certificat d’attestation, qui est facultative (MDS §3.1.3 ; WebAuthn §8.2.1) | La version réelle d’un appareil en l’absence de cette extension attestée |
| AAGUID | Identique pour tous les appareils sensiblement identiques d’un fabricant, différent de celui des autres modèles (MS §3.1) | L’identité d’un appareil ; son authenticité sans attestation (WebAuthn §6) |
| `attestationRootCertificates` | Ancres de confiance de la chaîne de lot (MS §4) :<br>– chacune peut être une racine, une **AC intermédiaire** ou **le certificat d’attestation lui-même** ;<br>– elles ne forment pas une chaîne ;<br>– chacune MUST être dédiée à l’attestation.<br>Ancre couvrant plusieurs modèles :<br>– MS §4 : « it must be possible to uniquely derive the authenticator model from the Attestation Certificate », par l’extension AAGUID pour un authentificateur qui a un AAGUID ;<br>– WebAuthn §13.3.1 : l’AAGUID **SHOULD** figurer dans le certificat d’attestation ;<br>– WebAuthn §8.2.1 : pour `packed` seulement, l’extension MUST être présente (exigence sur le certificat, B.5).<br>Aucune de ces règles n’oblige la RP à refuser un certificat sans extension. La règle locale plus stricte est **décidée** (M.4) : une correspondance AAGUID–certificat non démontrée entraîne un refus. Le moyen de la démontrer reste [R] ou [O] (G) | Qu’une ancre soit une AC racine X.509 auto-signée ; qu’elle soit propre à un seul modèle ; que l’extension AAGUID soit présente |

##### D. Faits `python-fido2` 2.2.1 et `cryptography` 50.0.2 [F]

**Validation cryptographique : ce que fait la bibliothèque.**

| # | Fait | Emplacement |
|---|---|---|
| D.1 | `verify_x509_chain` vérifie seulement que chaque maillon est signé par le suivant. Elle ne contrôle ni dates, ni révocation, ni BasicConstraints, longueur de chemin ou KeyUsage des AC. Avec une chaîne d’un seul élément, elle réussit sans rien vérifier | `attestation/base.py:105-137` |
| D.2 | `packed` avec `x5c` : contrôles de profil sur le premier certificat seulement (version 3, `CA=false`, champs C, O, OU et CN). L’extension AAGUID n’est comparée que si elle est présente. Résultat BASIC. Sans `x5c` : résultat SELF, avec un chemin de confiance vide | `attestation/packed.py:48-105` |
| D.3 | `fido-u2f` renvoie BASIC sans contrôle de profil du certificat | `attestation/u2f.py:44-61` |
| D.4 | Les formats par défaut excluent `none`, qui lève `UnsupportedType`. `verify_attestation` ne renvoie rien : le type d’attestation n’est visible que de `ca_lookup`. Si `ca_lookup` renvoie une ancre pour un résultat SELF ou NONE, l’attestation est acceptée (voir D.1) | `attestation/base.py:198-258` |
| D.5 | **Ancre égale au certificat d’attestation (permis par MS §4).** Ce n’est pas le cas de la chaîne isolée de D.1. `verify_attestation` vérifie `trust_path + [ancre]` (`base.py:256`), et le chemin d’un `packed` Basic est `x5c` (`packed.py:105`). Le certificat d’attestation apparaît donc deux fois.<br>– Si `x5c` ne contient que lui, la boucle vérifie sa signature avec sa propre clé : succès s’il est auto-signé, `InvalidSignature` puis `UntrustedAttestation` sinon.<br>– Si `x5c` contient aussi une AC, la boucle vérifie la signature de cette AC avec la clé du certificat d’attestation, ce qui échoue normalement.<br>– Avec `MdsAttestationVerifier`, une telle ancre n’est retenue que si son sujet est égal à l’émetteur du dernier certificat de `x5c` (D.11).<br>Aucun de ces chemins n’est la comparaison binaire que décrit MS §4 (note : « a binary comparison is sufficient »). L’accepter exigerait un traitement explicite, hors de `verify_x509_chain` ; ce point reste ouvert (G). Constat tiré de la lecture du code, sans exécution | `attestation/base.py:105-137, 249-258` ; `attestation/packed.py:103-105` ; `mds3.py:463-473` |
| D.6 | `Fido2Server` ignore l’attestation si la préférence est `none`, absente ou inconnue, ou si aucune fonction de vérification n’est fournie | `server.py:119-122, 148, 155, 266-268` ; `webauthn.py:344-362` |
| D.7 | `Fido2Client` renvoie la déclaration brute de l’authentificateur. `WindowsClient` demande `none` si aucune préférence n’est donnée | `client/__init__.py:915-917` ; `client/windows.py:197-199` |

**Décision de confiance : ce que propose la bibliothèque (`mds3`, facultatif).**

| # | Fait | Emplacement |
|---|---|---|
| D.8 | `parse_blob` vérifie la chaîne `x5c` (limite D.1) et la signature si une ancre est fournie. Il ne lit ni `nextUpdate`, ni `no`, ni aucune CRL, et ne contrôle aucune date. Avec `trust_root=None`, il ne vérifie rien et émet seulement un avertissement | `mds3.py:495-528` |
| D.8 bis | **`x5u` n’est pas traité.** Le module ne contient aucune occurrence de `x5u` ; la chaîne est lue uniquement dans `header.get("x5c", [])`.<br>– Si `x5u` et `x5c` sont tous deux présents, la chaîne `x5c` est utilisée et `x5u` est ignoré. Or MDS §3.2 donne la priorité à `x5u`.<br>– Si seul `x5u` est présent, la signature est vérifiée avec la clé de l’ancre fournie.<br>Dans les deux cas, ni le contrôle d’origine web, ni la vérification RFC 5280, ni le contrôle de révocation exigés pour `x5u` n’ont lieu. D’où le refus décidé en M.3 | `mds3.py:509-520` |
| D.9 | Filtre d’entrées par défaut (`filter_revoked`) : une entrée est exclue si **un** rapport de son historique vaut `REVOKED`. Aucun autre statut n’est pris en compte, et `effectiveDate` comme `authenticatorVersion` sont ignorés | `mds3.py:332-340, 389-411` |
| D.10 | Filtre d’attestation par défaut : il refuse seulement si le champ `certificate` d’un rapport `ATTESTATION_KEY_COMPROMISE` figure dans `x5c`. Il ignore `batchCertificate` et accepte lorsque aucun des deux champs n’est renseigné. Une ancre absente de `x5c` n’est pas comparée | `mds3.py:343-355` |
| D.11 | `ca_lookup` cherche l’entrée par AAGUID, ou par identifiant de clé si l’AAGUID est nul. Elle choisit l’ancre par égalité entre son sujet et l’émetteur du dernier certificat de `x5c`, puis applique D.1. Avec un résultat SELF et une entrée trouvée, l’accès à `trust_path[-1]` lève `IndexError` (exception d’un autre type qu’`InvalidAttestation`) | `mds3.py:438-475` |
| D.12 | Une valeur de statut inconnue est lue comme `None`, et aucun filtre n’en tient compte, ce qui est cohérent avec MDS §3.1.4.3 | `utils.py:228-262` ; `webauthn.py:344-362` |
| D.13 | Aucune horloge n’intervient dans `attestation/` ni dans `mds3` | modules cités |

**`cryptography` 50.0.2 (signatures de type seulement).**

- **D.14.** `PolicyBuilder` expose `time()`, `store()`, `max_chain_depth()`, `extension_policies(ca_policy, ee_policy)` et `build_client_verifier()`. `ExtensionPolicy` propose `permit_all()` et les politiques par défaut WebPKI.
- Une CRL peut être lue (`load_der_x509_crl`) et sa signature vérifiée (`is_signature_valid`).
- Les signatures lues ne montrent aucune option de révocation dans `PolicyBuilder`.
- Ce sont des primitives existantes. Leur compatibilité avec le profil des certificats d’attestation n’est pas établie (H-4). Conformément à M.8, `cryptography` 50.0.2 n’est pas présenté comme validé pour ce profil tant que des tests ultérieurs ne l’ont pas montré.

##### E. Deux étapes à ne pas confondre

1. **Validation cryptographique.** Elle comprend :
   - la signature d’attestation, faite par la clé du certificat d’attestation ;
   - la chaîne jusqu’à une ancre approuvée ;
   - la validation du chemin à un instant donné : dates, contraintes d’AC, longueur, usages de clé ;
   - le statut des AC intermédiaires.

   `python-fido2` couvre la signature d’attestation et la signature de chaque maillon (D.1 à D.3), **rien de plus**. `cryptography` 50.0.2 offre une validation de chemin (D.14), dont l’adéquation reste à établir. Le statut doit venir d’informations importées (F).
2. **Décision de confiance dans un modèle.** Elle comprend :
   - un AAGUID présent dans la liste fermée ;
   - une ancre approuvée pour cet AAGUID ;
   - un format et un type d’attestation (BASIC ou AttCA) autorisés ;
   - le rattachement de l’AAGUID au certificat, par l’extension ou par une ancre établie comme dédiée au modèle ;
   - un statut de métadonnées admis, si des métadonnées sont retenues.

   C’est une **politique du projet**, dont les règles principales sont décidées (M.1, M.4, M.5). `python-fido2` n’en fournit qu’une partie facultative (D.8 à D.11), avec des valeurs par défaut plus faibles que l’orientation du §5.2.6.

Ni l’une ni l’autre ne prouve le comportement réel de l’appareil (§5.2.6, D, niveau 3).

##### F. Deux familles d’informations de révocation

| | **F.1 — Chaîne de signature du BLOB MDS** | **F.2 — AC intermédiaires de l’attestation de l’authentificateur** |
|---|---|---|
| Ce qui est signé | Le BLOB de métadonnées | La déclaration d’attestation de chaque credential |
| Exigence | MDS §3.2 : CRL disponibles (MUST) ; avec `x5u`, contrôle de révocation de tous les maillons (MUST) | WebAuthn §7.1 : accès aux informations de statut des AC intermédiaires (MUST) |
| Sources possibles | CRL publiées pour les certificats de signature du BLOB | CRL ou OCSP désignés par les certificats, s’ils existent (facultatifs, WebAuthn §8.2.1) ; rapports de statut des métadonnées ; publications du fabricant |
| Hors ligne | Possible si les CRL ont été obtenues hors serveur, importées, puis vérifiées (signature de l’émetteur, période de validité selon RFC 5280, non détaillée ici) avant la vérification du BLOB | Possible si les informations pertinentes ont été importées et vérifiées avant la genèse |
| En leur absence | Vérification non conforme à MDS §3.2 → refus de l’import ou de la genèse (M.5) | Vérification non conforme à WebAuthn §7.1 → refus de la genèse (M.5) |
| `python-fido2` | Ne traite rien (D.8) ; `x5u` est ignoré (D.8 bis) | Ne traite rien (D.1) |

Une famille ne remplace pas l’autre. Un BLOB vérifié ne donne pas, à lui seul, le statut des AC intermédiaires d’un fabricant. Les rapports de statut des métadonnées peuvent en porter une partie, par leurs champs `certificate` et `batchCertificate`.

**Décidé (M.5) :** pour les AC intermédiaires de l’attestation, des **informations de statut vérifiées** sont exigées. Un rapport MDS n’est retenu à ce titre que s’il **identifie effectivement** les certificats concernés. Il n’est jamais présenté comme suffisant dans le cas contraire. Toute information requise manquante entraîne un refus.

**[O]** Restent ouverts :
- la forme des informations admises pour F.2 (CRL, réponse OCSP obtenue à l’avance, ou autre) ;
- le critère exact d’identification d’un certificat par un rapport MDS ;
- la vérification de ces informations, avec la limite de D.14.

##### G. Règles normatives et règles plus strictes propres au projet

| Sujet | Normatif (WebAuthn, MDS, MS) | Projet : décidé [D] ou proposé [R] |
|---|---|---|
| `none` et auto-attestation | Acceptables si la politique de la RP les admet (WebAuthn §7.1, étape 24) | [D] Refusées (§5.2.6) |
| Attestation non digne de confiance | SHOULD faire échouer ; MAY être enregistrée comme auto-attestation (étape 24) | [D] Échec, sans déclassement (§5.2.6) |
| Modèles admis | Aucune liste exigée | [D] Liste fermée d’AAGUID (§5.2.6) |
| Valeurs de statut inconnues | MUST être ignorées silencieusement (MDS §3.1.4.3) | [D] (M.4) Ignorées, comme l’exige MDS : elles ne bloquent pas et ne dispensent jamais de l’admission explicite du modèle. La rigueur supplémentaire vient de la liste fermée : un modèle ou un AAGUID absent de la liste d’autorisation est refusé, quel que soit son statut |
| Téléchargement du BLOB | Le « FIDO Server » MUST pouvoir télécharger le BLOB (MDS §3.2) | [D] (M.2) Récupération hors serveur et import par l’opération `root` contrôlée, sans accès réseau du serveur. C’est une **adaptation** reconnue, dont la conformité stricte à MDS §3.2 n’est pas établie ni revendiquée |
| Sources des ancres | La RP obtient les ancres « from a trusted source or from policy » (WebAuthn §7.1, étape 23) | [D] (M.1) R-c si une source indépendante du fabricant concorde avec MDS ; sinon R-b après approbation hors bande de l’ancre de signature MDS. Toute divergence entraîne un refus fermé |
| `REVOKED` | SHOULD refuser les nouvelles inscriptions (MDS §3.1.4.1) | [R] Refus à la genèse |
| Statuts de sécurité (`USER_VERIFICATION_BYPASS`, `USER_KEY_REMOTE_COMPROMISE`, `USER_KEY_PHYSICAL_COMPROMISE`, `ATTESTATION_KEY_COMPROMISE`) | Conduite laissée à la RP. Pour `ATTESTATION_KEY_COMPROMISE`, la RP SHOULD examiner `certificate` (MDS §3.1.4.2, §3.2) | [R] Refus à la genèse si un rapport de sécurité s’applique, ou ne peut pas être écarté, pour l’appareil présenté. Ces statuts contredisent « UV obligatoire » et une clé privée non exportable (§5.2.1). [O] La portée de `authenticatorVersion` et l’effet d’un `UPDATE_AVAILABLE` postérieur restent à décider |
| `nextUpdate` dépassé | Aucune règle d’invalidité ; téléchargement SHOULD avant cette date (MDS §3.2) | [D] (M.5, M.6) Règle propre au projet, qui ne fixe aucune durée et n’emploie que la date publiée :<br>– à la genèse et à chaque import : refus ;<br>– après la genèse : suspension des opérations qui ouvrent dès que le `nextUpdate` du fichier en place est dépassé |
| `no` | SHOULD ignorer un BLOB dont le `no` n’est pas supérieur à celui du cache (MDS §3.2) | [D] (M.5) Refus à la genèse et à chaque import d’un `no` inférieur ou égal au dernier accepté. **[R]** Conserver ce `no` dans un artefact appartenant à `root`, journalisé et ancré (M.9) |
| Extension AAGUID | AAGUID SHOULD dans le certificat si la racine n’est pas dédiée à un modèle (WebAuthn §13.3.1). MUST pour les certificats `packed` dans ce cas (WebAuthn §8.2.1). Contrôle par la RP seulement si l’extension est présente (WebAuthn §8.2). MS §4 : le modèle « must » pouvoir se déduire du certificat (B.5, C) | [D] (M.4) Règle plus stricte : une correspondance AAGUID–certificat non démontrée entraîne un refus. **[R]** La démontrer par l’extension, ou par la preuve d’une ancre dédiée au modèle, dont la source reste à décider [O] |
| Ancre égale au certificat d’attestation | Permise (MS §4, avec comparaison binaire ; WebAuthn §7.1, étape 24) | [O] À accepter seulement si le vérificateur la traite explicitement, par comparaison binaire. Sans ce traitement, le résultat de `python-fido2` dépend de l’auto-signature du certificat et du contenu de `x5c` (D.5), ce qui ne correspond pas à la règle de MS §4 |
| `x5u` dans l’en-tête du BLOB | Prioritaire sur `x5c` ; même origine web, chaîne RFC 5280 et révocation de tous les maillons : MUST (MDS §3.2) | [D] (M.3) Refus de tout BLOB dont l’en-tête contient `x5u`, puisque `python-fido2` ne le traite pas (D.8 bis). Pas de repli sur `x5c` ni sur l’ancre seule, ce qui serait un déclassement silencieux. Cette règle tient jusqu’à une décision et un traitement dédiés [O] |
| Statut des AC intermédiaires de l’attestation | Accès aux informations de statut : MUST (WebAuthn §7.1) | [D] (M.5) Des informations de statut vérifiées sont exigées. Un rapport MDS ne compte que s’il identifie effectivement les certificats concernés (F). Absence → refus |
| Révocation après l’inscription | WebAuthn §13.4.5 : RECOMMENDED, sous condition (B.3) | [D] (M.6) Fermeture des opérations qui ouvrent et revue par le propriétaire, sans changement automatique des statuts des credentials (K.7). Reprise par décision administrative authentifiée et politique valide, journalisée et ancrée |
| Fraîcheur après la genèse | Aucune règle (MDS §3.2 fixe seulement la date limite de téléchargement) | [D] (M.6) Suspension des opérations qui ouvrent si `nextUpdate` est dépassé ou si un import échoue. Reprise comme ci-dessus |
| Modèles des deux clés | Aucune règle | [D] (M.7) Deux modèles d’AAGUID différents recommandés pour la clé principale et la clé de secours. Fabricant, modèles et ancres restent à choisir [O] |

##### H. Hypothèses [H], non vérifiées

- **H-1.** Le modèle retenu produit `packed` en mode Basic avec `x5c` et porte l’extension AAGUID. On ne sait pas si son ancre est dédiée au modèle.
- **H-2.** Le modèle figure dans le BLOB MDS avec une déclaration et des ancres. Le fabricant publie aussi ses ancres par un canal indépendant.
- **H-3.** L’API Windows transmet l’attestation `direct` pour `ai-director-admin.invalid` (§5.2.6, A).
- **H-4.** Le vérificateur client de `cryptography` 50.0.2 accepte le profil des certificats d’attestation (usage étendu de clé attendu, extensions), au besoin avec des politiques d’extensions adaptées. Ce point peut être évalué sur des certificats d’exemple publics, sans matériel ; aucun essai n’est autorisé par cette section.
- **H-5.** Des informations de statut existent pour les AC intermédiaires du fabricant et pour la chaîne du BLOB, et elles peuvent être transportées hors ligne.
- **H-6.** Les conditions d’utilisation du BLOB MDS couvrent l’usage du projet. Elles n’ont pas été lues.
- **H-7.** L’horloge du serveur, contrôlée par `root` (T-3, D-15), est assez fiable pour juger des dates de validité à la genèse.

##### I. Risques

- **I-1. Déclassement silencieux par les valeurs par défaut** (D.4, D.6, D.11). Une intégration naïve accepterait une auto-attestation, ou ignorerait toute l’attestation, contre le §5.2.6 D.
- **I-2. Chaîne acceptée hors politique** (D.1). Une AC expirée, révoquée ou qui n’est pas une AC passerait, quelle que soit la longueur du chemin.
- **I-3. Statut contraire aux décisions** (D.9). `USER_VERIFICATION_BYPASS` et `USER_KEY_*_COMPROMISE` passent les filtres par défaut.
- **I-4. BLOB ancien ou périmé** (D.8). Il reste correctement signé. Sans `no` conservé, un BLOB plus ancien serait accepté. Conserver `no` exige un artefact persistant appartenant à `root`. Cela ne contredit pas C-1, qui ne concerne que les défis de genèse (§5.2.5).
- **I-5. Vérification hors ligne non conforme** (B.2, F). Elle l’est si les informations de statut manquent.
- **I-6. Révocation commune aux deux clés.** Si les deux clés sont du même modèle, une révocation du modèle ou de son AC les touche toutes les deux (§5.8). M.7 recommande deux modèles d’AAGUID différents. Cela ne protège pas contre une AC ou une ancre commune à deux modèles du même fabricant (hypothèse à vérifier une fois les modèles choisis).
- **I-7. Aucun effet automatique** (B.7). Une révocation postérieure à la genèse ne change rien tant qu’un import n’a pas eu lieu et qu’aucune règle n’a été appliquée.
- **I-8. Provenance des ancres.** Une ancre obtenue sur un poste compromis, ou par le même canal que les métadonnées qu’elle doit vérifier, n’apporte aucune indépendance.
- **I-9. Dépendance réseau.** La récupération des artefacts exige un réseau hors serveur. Le serveur ne doit jamais aller les chercher lui-même (§2.4, M.2).
- **I-10. Suspension prolongée.** Avec M.6, un import en échec ou un `nextUpdate` dépassé suspend les opérations qui ouvrent. Une source de métadonnées indisponible, ou une suite d’imports refusés, peut donc bloquer durablement les confirmations, les invitations et la réouverture. C’est un échec fermé voulu. Seule l’opération `root` contrôlée peut lancer un import (T-3).

##### J. Options par étape du cycle de vie

1. **Approbation des ancres.**
   - **R-a.** Ancre publiée par le fabricant, épinglée par l’empreinte SHA-256 de son encodage DER, comparée par le propriétaire sur deux canaux indépendants.
   - **R-b.** Ancre tirée de l’entrée MDS de l’AAGUID, dans un BLOB vérifié contre une ancre MDS elle-même épinglée.
   - **R-c.** R-a et R-b doivent concorder.

   **Décidé (M.1) :** R-c lorsqu’une source indépendante du fabricant existe et concorde avec MDS. Sinon, R-b seulement après approbation hors bande de l’ancre de signature MDS. Toute divergence entraîne un refus fermé. La source indépendante et le canal hors bande restent ouverts [O].

   Contenu enregistré envisagé [R] : empreinte, sujet, émetteur, validité, nature de l’ancre (racine, AC intermédiaire ou certificat d’attestation, MS §4), source, date d’approbation et AAGUID liés.
2. **Liste d’AAGUID — décidé (M.4).** Une liste fermée de **couples** AAGUID–ancre–format, et non deux listes indépendantes. Un modèle absent de la liste, ou dont la correspondance AAGUID–certificat n’est pas démontrée, est refusé. **[R]** La démonstration passe par l’extension AAGUID, ou par la preuve que l’ancre est dédiée au modèle ; la source de cette preuve reste ouverte (G).
3. **Source et mise à jour des métadonnées.**
   - **M-0.** Aucune métadonnée MDS : aucun statut n’est disponible, la surveillance est manuelle, et F.2 doit être satisfaite autrement.
   - **M-1.** Instantané récupéré hors serveur, importé et vérifié par l’opération `root` contrôlée.
   - **M-2.** Comme M-1, avec des imports ultérieurs par la même procédure.

   **Décidé (M.2) : M-2.** Le parcours est une adaptation reconnue de MDS §3.2, dont la conformité stricte n’est pas établie (K.1). Aucune cadence ni aucun fournisseur n’est retenu. M-0 et M-1 ne sont pas retenus.
4. **Vérification hors ligne à la genèse.** Les contrôles sont décidés quant à leur principe par M.1, M.3, M.4, M.5 et M.8 ; leurs détails techniques restent [R] :
   - chaîne et signature du BLOB, avec ses informations de révocation (F.1) ;
   - `nextUpdate` et `no` (G) ;
   - statut courant de l’entrée (G) ;
   - attestation : validation cryptographique (E.1), puis décision de confiance (E.2) ;
   - statut des AC intermédiaires d’après les informations importées (F.2).
5. **Révocation après la genèse.**
   - **P-a.** Événement journalisé et revue par le propriétaire.
   - **P-b.** Comme P-a, plus un changement de statut des clés (§5.5.3) et une nouvelle genèse.
   - **P-c.** Fermeture des opérations qui ouvrent ; seules celles qui ferment restent possibles (§11.2).

   **Décidé (M.6) :** P-c avec la revue de P-a. P-b n’est jamais automatique et exige une décision distincte. La reprise exige une décision administrative authentifiée et une politique valide, journalisée et ancrée.

   Le traitement dépend du statut. `ATTESTATION_KEY_COMPROMISE` et la révocation d’une AC intermédiaire mettent en cause les inscriptions postérieures à la date de compromission (B.3) ; il faut donc une date de genèse ancrée (§11). `USER_KEY_*_COMPROMISE` et `USER_VERIFICATION_BYPASS` mettent en cause les credentials déjà inscrits.
6. **Métadonnées absentes, périmées ou indisponibles.**
   - **À la genèse — décidé (M.5).** Les cas suivants entraînent un refus fermé : métadonnées absentes ou non vérifiables ; `nextUpdate` dépassé ; `no` non supérieur au dernier accepté ; informations de révocation requises manquantes.
   - `parse_blob` sans ancre n’est jamais admis (D.8). Un BLOB avec `x5u` est refusé jusqu’à une décision et un traitement dédiés (M.3).
   - **Après la genèse — décidé (M.6).** Un `nextUpdate` dépassé sans nouvel import valide, ou un import en échec, n’invalide pas les clés existantes, et le fichier précédent reste en place (K.3). En revanche, les opérations qui ouvrent sont **suspendues** jusqu’à la reprise prévue par M.6. Une indisponibilité des artefacts se traduit en pratique par l’un de ces deux cas. Elle empêche aussi de détecter une révocation nouvelle (I-7).
   - Ce cas se distingue d’une révocation défavorable **connue**, qui ferme les opérations qui ouvrent et déclenche une revue (K.7).
   - **Décidé (M.6, complément) :** le contrôle s’applique à V0, avant toute opération administrative qui ouvre, et à E, avant toute autorisation du chemin d’approbation (§11.2). Toute suspension exige une reprise authentifiée, journalisée et ancrée. Aucune durée n’est fixée.

##### K. Mise en œuvre : décisions du 26 octobre [D] et recommandations restantes [R]

Chaque point indique ce qui est décidé (renvoi au point M) et ce qui reste une recommandation.

1. **Artefacts récupérés hors serveur — décidé (M.2).** Ancres, BLOB, CRL et autres informations de statut sont obtenus sur un poste, hors du serveur. Ils restent des données non fiables jusqu’à leur vérification sur le serveur. Le serveur n’accède jamais au réseau (§2.4).
   - **Statut au regard de MDS §3.2 — décidé (M.2).** MDS §3.2 exige que le « FIDO Server » puisse télécharger le BLOB, mettre en cache l’ancre de signature et disposer des CRL. Les sources lues (MDS §3.2, glossaire FIDO) ne disent pas si un poste de récupération distinct, suivi d’un import `root`, remplit ce rôle. Le propriétaire a retenu la lecture prudente : l’architecture est une **adaptation** de MDS §3.2, et sa **conformité stricte n’est pas établie** ni revendiquée. La lecture (a), selon laquelle poste et import formeraient ensemble la fonction « FIDO Server », n’est pas adoptée.
   - **[O]** Le poste, le canal et les conditions d’utilisation du BLOB (H-6) restent à décider.
2. **Import par l’opération `root` contrôlée (T-3) — décidé (M.2).** L’opération vérifie avant d’installer :
   - **signature et chaîne.** Un BLOB dont l’en-tête contient `x5u` est refusé, sans repli sur `x5c` ni sur l’ancre seule, jusqu’à une décision et un traitement dédiés (**M.3**, D.8 bis) ;
   - **validation du chemin** à l’instant de l’import (M.8) ;
   - **informations de révocation** requises, F.1 et F.2. Leur absence entraîne un refus (**M.5**) ;
   - **fraîcheur :** `nextUpdate` non dépassé, et `no` strictement supérieur au dernier accepté (**M.5**) ;
   - **ancres**, selon M.1 : concordance R-c, ou R-b après approbation hors bande de l’ancre de signature MDS. Toute divergence entraîne un refus.

   Elle installe ensuite, d’un seul tenant, un **fichier de politique d’attestation** appartenant à `root` et lisible par `aidirector`. Contenu : ancres approuvées, couples AAGUID–ancre–format (M.4), instantané des métadonnées et informations de statut. Les éléments de M.9 sont journalisés et ancrés.
   - **[R]** Le format exact du fichier et l’installation atomique.
   - **[O]** Le canal de comparaison des empreintes hors bande.
3. **Mise à jour ultérieure — décidé (M.2, M.6).** Elle passe par la même procédure contrôlée. Un import refusé laisse en place le fichier précédent et **suspend** les opérations qui ouvrent. Il en va de même lorsque le `nextUpdate` du fichier en place est dépassé. La reprise suit M.6. Aucune cadence n’est fixée [O]. Seule l’opération `root` contrôlée peut lancer un import (T-3).
4. **Vérification de genèse sans aucune valeur par défaut de `python-fido2` [R]** (la validation X.509 relève de M.8).
   - Formats limités à ceux du modèle retenu.
   - Une `ca_lookup` qui ne renvoie une ancre que dans les cas suivants : type BASIC ou AttCA, chemin non vide, AAGUID listé, ancre liée à cet AAGUID.
   - Toute exception traitée comme un refus (D.11).
   - Validation de chemin complémentaire, éprouvée et à règles explicites (E.1, M.8).
   - Statut des AC intermédiaires établi d’après des informations de statut vérifiées (F.2, M.5).
   - Couple AAGUID–ancre–format présent dans la liste fermée, et correspondance AAGUID–certificat démontrée (M.4).
   - Ne jamais s’en remettre au seul paramètre `attestation` de `Fido2Server` (D.6), ni à `parse_blob` sans ancre (D.8) ou pour un BLOB qui contient `x5u` (D.8 bis, M.3).
   - Ne pas accepter une ancre égale au certificat d’attestation sans un traitement explicite, qui reste ouvert (D.5, G).
5. **Journalisation et ancrage — décidé (M.9).** Sont journalisés et ancrés (J-b, J-c) :
   - le BLOB, son `no` et son `nextUpdate` ;
   - les informations de révocation ;
   - la chaîne `x5c` de l’attestation ;
   - l’empreinte du fichier de politique.

   Aucune opération qui ouvre ne devient effective avant l’ancrage requis. Cela permet d’appliquer B.3 et de dater la genèse par rapport à une `effectiveDate`.
   - **[R]** Ajouter à l’enregistrement de genèse `fmt`, l’AAGUID et l’ancre utilisée.
   - **[O]** Le moment de l’ancrage d’une genèse faite système fermé (§11.4).
6. **Refus fermé lorsqu’une genèse ne peut pas satisfaire la politique — décidé pour les motifs de M.1, M.3, M.4 et M.5.** La règle vaut pour la genèse initiale comme pour une réinitialisation ultérieure. Motifs décidés :
   - divergence des ancres ;
   - présence de `x5u` ;
   - modèle hors liste ou correspondance AAGUID–certificat non démontrée ;
   - `nextUpdate` dépassé ou `no` non supérieur au dernier accepté ;
   - informations de révocation requises manquantes ;
   - dates ou révocation invérifiables (M.8).

   **[R]** Le refus pour un statut bloquant (G) n’est pas décidé. Aucun déclassement : tout assouplissement exige une décision séparée.
7. **Révocation défavorable connue après la genèse — décidé (M.6) ; portée fermée décidée le 29 octobre 2026 [D].** Elle couvre exactement quatre cas, connus par un import : un statut de sécurité applicable, le statut `REVOKED`, une AC intermédiaire révoquée ou une ancre retirée. Aucun autre cas n’en relève sans décision distincte. L’applicabilité d’un statut de sécurité selon `authenticatorVersion` reste ouverte [O] (G).
   - **Conduite :** les opérations qui ouvrent sont fermées (§11.2) et le propriétaire procède à une revue. Les opérations qui ferment restent possibles.
   - **Statuts des credentials :** ceux qui sont déjà inscrits (§5.5.3) **ne sont jamais modifiés automatiquement**. Un passage à `RETIRED` ou `COMPROMISED`, ou une nouvelle genèse, exige une décision distincte (§5.7, §5.8).
   - **Reprise :** décision administrative authentifiée, journalisée et ancrée, précédée d’une revue qui établit que la politique est de nouveau satisfaite. À défaut, le système reste suspendu (M.6, complément).
   - **Limite :** la détection dépend des imports (I-7).
   - **[O]** Le nom et le format exact de l’opération « reprise de suspension » (opération 5 du §11.2).

##### L. Cohérence avec les décisions prises

- **§5.2.6 D :** l’orientation est inchangée. Les décisions du 26 octobre 2026 (M) la précisent sans la modifier. Le reste de cette section n’ajoute que des recommandations et des points ouverts.
- **C-1 (§5.2.5) :** C-1 ne concerne que les défis de genèse. Le fichier de politique et les artefacts importés sont des fichiers `root` distincts, comme le fichier de confiance.
- **T-3 :** fichier de politique et artefacts appartiennent à `root` et sont en lecture seule pour `aidirector`. Ils sont à inscrire à l’inventaire du §9.2.
- **§2.4 :** aucune primitive réseau n’est ajoutée au code applicatif ; la récupération a lieu hors serveur (M.2).
- **MDS §3.2 :** l’architecture est une adaptation reconnue, dont la conformité stricte n’est pas établie (M.2). Aucune autre partie du document ne doit revendiquer cette conformité.
- **`x5u` :** tout BLOB qui le contient est refusé, sans repli, jusqu’à une décision et un traitement dédiés (M.3, D.8 bis). Le refus vaut à la genèse comme à chaque import ; à l’import, il entraîne donc aussi la suspension de M.6.
- **Deux familles d’informations de révocation :** la chaîne du BLOB (F.1) et les AC intermédiaires de l’attestation (F.2) sont exigées séparément (M.5). L’une ne remplace pas l’autre.
- **Système fermé.** Il faut distinguer trois situations (décisions M.5 et M.6) :
  - **à la genèse,** un `nextUpdate` dépassé, un `no` inférieur ou égal au dernier accepté, l’absence des informations de révocation requises (F.1, F.2) ou leur échec de vérification entraîne le refus fermé de la genèse (M.5). Il en va de même d’un BLOB qui contient `x5u` (M.3), d’une divergence d’ancres (M.1) et de dates ou d’une révocation invérifiables (M.8) ;
  - **après la genèse,** un `nextUpdate` dépassé ou un import en échec laisse en place le fichier précédent et **suspend** les opérations qui ouvrent (M.6) ;
  - **après la genèse,** une révocation défavorable **connue** ferme ces opérations et déclenche une revue par le propriétaire (M.6).

  Dans les deux derniers cas, la reprise exige une décision administrative authentifiée et une politique valide, journalisée et ancrée. Aucune de ces situations n’ouvre l’interrupteur, ne modifie automatiquement le statut d’un credential ni n’active Provider, qui reste CLOSED.

##### M. Orientations décidées par le propriétaire le 26 octobre 2026 [D]

**Décidé [D]** (orientations de conception du propriétaire, 26 octobre 2026) :

1. **M.1 — Ancres de confiance.**
   - **R-c** lorsqu’une source indépendante du fabricant existe et concorde avec MDS.
   - Sinon, **R-b** seulement, et uniquement après **approbation hors bande de l’ancre de signature MDS**.
   - Toute divergence entre les sources entraîne un **refus fermé**.
2. **M.2 — Métadonnées.**
   - Option **M-2** : récupération hors serveur, puis import par l’opération `root` contrôlée (T-3), pour la genèse comme pour les mises à jour ultérieures.
   - **Aucun accès réseau n’est ajouté au serveur** (§2.4).
   - **Adaptation reconnue.** MDS §3.2 exige que le « FIDO Server » puisse télécharger le BLOB lui-même. Ici, le serveur applicatif ne le télécharge pas : l’architecture est une **adaptation** de MDS §3.2, et sa **conformité stricte à MDS §3.2 n’est pas établie**. Le projet ne la revendique pas. Cette décision tranche la question de K.1 en faveur de la lecture (b).
3. **M.3 — `x5u`.** Tout BLOB dont l’en-tête contient `x5u` est **refusé**, sans repli sur `x5c` ni sur l’ancre seule, jusqu’à une décision et un traitement dédiés (D.8 bis).
4. **M.4 — Liste fermée.**
   - Une liste fermée de couples **AAGUID–ancre–format** est maintenue.
   - Sont refusés : un modèle absent de cette liste, et une correspondance AAGUID–certificat **non démontrée**.
   - Les statuts MDS inconnus sont ignorés, comme l’exige MDS §3.1.4.3. Ils ne dispensent jamais de l’admission explicite du modèle.
5. **M.5 — Contrôles à la genèse et à chaque import.** Sont refusés :
   - un `nextUpdate` dépassé ;
   - un `no` inférieur ou égal au dernier accepté ;
   - l’absence des informations de révocation requises, pour la chaîne du BLOB (F.1) comme pour les AC intermédiaires de l’attestation (F.2).

   Pour les AC intermédiaires de l’attestation, des **informations de statut vérifiées** sont exigées. Les rapports MDS ne sont pas présentés comme suffisants s’ils n’identifient pas effectivement les certificats concernés (F).
6. **M.6 — Après la genèse.**
   - **Suspension.** Les opérations qui ouvrent (§11.2) sont suspendues si les métadonnées dépassent leur `nextUpdate` ou si un import échoue.
   - **Révocation connue.** Une révocation défavorable connue ferme aussi ces opérations et déclenche une revue par le propriétaire. **Portée décidée le 29 octobre 2026 [D] :** seuls quatre cas en relèvent, connus par un import : un statut de sécurité applicable, le statut `REVOKED`, une AC intermédiaire révoquée et une ancre retirée (K.7). Cette énumération est fermée : toute extension exige une décision distincte. L’applicabilité d’un statut de sécurité selon `authenticatorVersion` reste ouverte [O], et son refus à la genèse reste une recommandation [R] (G ; K.6).
   - **Credentials.** Leurs statuts ne changent jamais automatiquement (§5.5.3).
   - **Reprise.** Elle exige une **décision administrative authentifiée** et une **politique valide**, journalisée et ancrée.
   - **Complément décidé le 26 octobre 2026 — portée de la reprise.**
     - **Toute suspension** exige une décision administrative authentifiée de reprise, quelle qu’en soit la cause : métadonnées périmées, import en échec ou révocation défavorable connue. Un import valide ultérieur ne lève pas la suspension à lui seul.
     - La reprise est **journalisée et ancrée**. Avant l’envoi à l’ancre, elle passe la validation pré-ancrage par une branche dédiée (§11.3, étape 3). Comme toute opération qui ouvre, elle n’est effective qu’après l’ancrage et la relecture requis (M.9, §11.2), et seulement si la politique est encore valide à ce moment (complément « légitimité de l’entrée et effet de la reprise » ci-dessous).
     - **Après une révocation connue,** la reprise exige en outre une **revue** qui établit que la politique est de nouveau satisfaite.
     - Aucun credential ne change d’état automatiquement.
     - Si ces conditions ne peuvent pas être établies, le système **reste suspendu**. C’est notamment le cas si la seule clé disponible relève du modèle ou de l’ancre révoqués et que la revue ne peut pas établir que la politique est satisfaite.
   - **Complément décidé le 26 octobre 2026 — application de la suspension.** La politique d’attestation locale, protégée par `root` (fichier de politique, §9.2), est vérifiée à deux endroits :
     - **à V0,** avant toute opération administrative ordinaire qui ouvre, soit les opérations 1 à 4 du §11.2 (§5.5.1, étape 1) ;
     - **à E,** avant toute autorisation délivrée par le chemin d’approbation (§11.2).

     Les deux chemins **refusent** si la politique est périmée (`nextUpdate` dépassé), si un import est en échec ou si une révocation défavorable est connue, tant qu’aucune reprise effective n’est intervenue. L’état de suspension se lit dans cette politique protégée par `root`. Une valeur en base ou en cache, modifiable par le compte de service, ne peut servir qu’à refuser plus vite, jamais à lever une suspension (§11.2).
     - **La reprise elle-même**, « reprise de suspension » (opération 5 du §11.2), est la seule opération qui ouvre admise pendant une suspension. Elle ne permet aucune autre opération qui ouvre : les opérations 1 à 4 restent refusées tant qu’elle n’est pas effective, et les opérations qui ferment restent permises. Elle ne change le statut d’aucun credential. Son V0 vérifie, à la place de l’absence de suspension, que la politique est de nouveau valide (`nextUpdate` non dépassé, dernier import réussi) et, après une révocation connue, que la revue est consignée.
     - Cette décision **ne tranche pas** la fréquence de relecture de l’ancre, qui reste un point séparé (§11.2 ; §14, point 18).
   - **Complément décidé le 26 octobre 2026 — légitimité de l’entrée et effet de la reprise.**
     - **Légitimité.** La branche pré-ancrage (§11.3, étape 3) vérifie la légitimité de l’énoncé signé et de l’assertion **au moment de l’opération** : assertion valide, et conditions liées à l’énoncé conformes, à cet instant, à la politique protégée par `root` et au journal.
     - **Effet.** La reprise ne lève la suspension qu’**après l’ancrage et la relecture requis**, et seulement **si la politique est encore valide à ce moment**.
     - **Cause survenue entre l’opération et l’ancrage.** Il peut s’agir d’un `nextUpdate` qui expire, d’un import en échec ou d’une révocation défavorable connue. L’entrée de reprise peut alors rester journalisée et ancrée pour l’audit, mais elle est **sans effet** : la suspension demeure. Une **nouvelle reprise authentifiée** est requise après rétablissement d’une politique valide. La reprise devenue sans effet ne peut pas reprendre effet plus tard.
     - **Pas de S4 pour une simple péremption.** Une péremption de politique, un import en échec ou une révocation connue ne constituent pas une divergence S4. S4 reste réservé aux échecs d’intégrité et aux divergences définis par le protocole (§11.2, §11.3).
     - **Formulation opérationnelle [R].** À V0, pour les opérations 1 à 4, comme à E, une suspension n’est considérée comme levée que s’il existe une entrée de reprise `R` qui remplit trois conditions :
       - `R` est couverte par l’ancre relue lors de ce contrôle ;
       - aucune cause de suspension n’est survenue depuis l’instant de l’opération `R` : ni péremption d’une politique en vigueur depuis `R`, ni import en échec, ni révocation défavorable connue, d’après le journal et la politique protégée par `root` ;
       - la politique est valide au moment du contrôle.

       Une cause survenue après `R` rend `R` définitivement sans effet. Une valeur modifiable par le compte de service ne peut servir qu’à refuser, jamais à lever une suspension. **[O]** La manière exacte d’établir ces instants (horloge du stockage, §5.5.1 ; entrées de journal) relève du format de l’opération, qui reste ouvert.
7. **M.7 — Modèles des deux clés.**
   - Deux modèles d’**AAGUID différents** sont recommandés pour la clé principale et la clé de secours (I-6, §5.8).
   - Le fabricant, les modèles et les ancres **restent à choisir**.
8. **M.8 — Validation X.509.**
   - Une validation X.509 **éprouvée, avec des règles explicites**, est recommandée, ainsi qu’une **horloge contrôlée par `root`** (H-7).
   - Refus fermé si les dates ou la révocation ne peuvent pas être vérifiées.
   - `cryptography` 50.0.2 **n’est pas présenté comme validé** pour ce profil ; des tests ultérieurs sont nécessaires (H-4, D.14).
9. **M.9 — Journalisation et ancrage.** Sont journalisés et ancrés les éléments nécessaires à l’audit :
   - le BLOB, son `no` et son `nextUpdate` ;
   - les informations de révocation ;
   - la chaîne `x5c` de l’attestation ;
   - l’empreinte du fichier de politique.

   **Aucune opération qui ouvre ne devient effective avant l’ancrage requis** (§11.2).

**Portée.** Ces décisions :
- précisent l’orientation du §5.2.6 sans la modifier ;
- n’autorisent ni implémentation, ni création de compte, de jeton, de secret, de clé ou de credential ;
- n’autorisent ni essai matériel, ni accès réseau du serveur, ni modification du serveur, ni déploiement.

D-5 reste non résolu ; Provider = CLOSED et NO-GO restent en vigueur.

**Restent ouverts [O]** (récapitulés au §14, point 22) :
- le fabricant, les modèles, leurs AAGUID et les ancres concrètes (M.7) ;
- la source indépendante utilisable pour R-c ;
- le canal et la procédure d’approbation hors bande de l’ancre de signature MDS (M.1) ;
- le poste et le canal de récupération ; les conditions d’utilisation du BLOB (H-6) ;
- la cadence des imports. Aucune durée n’est fixée ;
- le traitement dédié éventuel de `x5u` (M.3) ;
- la manière de démontrer la correspondance AAGUID–certificat lorsque l’extension AAGUID est absente (preuve d’une ancre dédiée au modèle) ; l’acceptation d’une ancre égale au certificat d’attestation (D.5) ;
- les statuts bloquants à la genèse (`REVOKED`, statuts de sécurité, portée de `authenticatorVersion`, effet d’un `UPDATE_AVAILABLE`), qui restent [R] en G ;
- la forme des informations de statut vérifiées pour les AC intermédiaires (CRL, OCSP pré-obtenu ou autre), et le critère selon lequel un rapport MDS « identifie effectivement » un certificat (F) ;
- l’outil de validation X.509, ses règles et ses tests (M.8, H-4) ; la source et le contrôle de l’horloge `root` ;
- le nom et le format exact de l’opération « reprise de suspension » (opération 5 du §11.2) ; une piste [R] est de s’inspirer de `SWITCH_REOPEN` (§7.1). Sa portée et son point d’application sont décidés (M.6) ;
- la fréquence de relecture de l’ancre, que M.6 ne tranche pas (§11.2 ; §14, point 18) ;
- le protocole signé de la création d’une invitation, que le §6.2 ne décrit pas. Le contrôle de M.6 s’applique en tout cas avant elle (§11.2) ;
- le moment de l’ancrage de la genèse, qui a lieu système fermé, et le fournisseur de l’ancre (§11.4).

### 5.3 Construction de l’énoncé signé

[R] Énoncé canonique (`canonical_json` : JSON à clés triées, UTF-8, hexadécimal minuscule), version 1 :

- `statement_kind = "AI_DIRECTOR_ADMIN_STATEMENT"`, `statement_version`, `admin_rp_id` ;
- `operation`, dans une liste fermée (§6.2, §5.7, §5.8, §7.1) ;
- `store_id`, identifiant aléatoire de 256 bits créé à l’initialisation du futur schéma (v5 n’en a pas [F]), et `schema_version` ;
- la cible : `invitation_id`, `approver_id`, `principal_id`, `expected_account_id` ;
- `account_proof_sha256` (§8) ;
- pour chaque credential de B : rôle (`PRIMARY` ou `BACKUP`), empreintes SHA-256 du credential ID et de la clé publique COSE, algorithme, BE, BS ;
- `enrollment_sha256`, empreinte canonique de toute la ligne d’inscription, `credential_data` compris ;
- `reason_code` pour un rejet ;
- pour les opérations ordinaires qui ouvrent (opérations 1 à 4 du §11.2), **`effective_resume_entry_hash`** — décidé par le propriétaire le 26 octobre 2026 [D] (§5.5.1, étape 4 ; §14, point 21). Ce champ est une exigence de sécurité, non facultative, et il est **toujours présent** dans l’énoncé canonique de ces opérations. Sa valeur est l’`entry_hash` de l’entrée de journal de la **dernière reprise de suspension effective et ancrée au moment du `prepare`** (SHA-256, 32 octets, §11.1, J-b), encodé en 64 caractères hexadécimaux minuscules. Avant toute reprise effective, il vaut `null` explicite. Aucune séquence n’est ajoutée : l’empreinte identifie l’entrée ;
- pour **toute opération administrative signée**, la **liaison à l’autorisation effective de la clé signataire** — décidé par le propriétaire le 26 octobre 2026 [D] (§5.5.1, étape 5 ; §5.5.2, contrôle 7 ; §5.5.3 ; §14, point 9) : l’identifiant de l’entrée qui autorise effectivement cette clé, qu’il s’agisse de la genèse initiale, d’un ajout ou d’une réautorisation. Pour une opération qui ferme, V0 compare cette valeur à l’entrée d’autorisation effective conservée dans le fichier de confiance protégé par `root`, sans relire J-c, et exige en outre que la chaîne d’autorisation de la clé n’ait pas été invalidée, le statut `ACTIVE` ne suffisant pas (décidé le 27 octobre 2026 [D] ; §5.5.1, étape 5). **[O]** Restent ouverts le nom du champ, son encodage, la représentation de l’autorisation initiale de genèse et le format des opérations d’ajout et de réautorisation. Reste aussi ouverte la manière dont l’énoncé désigne la clé signataire : la liste actuelle ne la contient pas, et `prepare` ne sait pas aujourd’hui quelle clé signera ;
- `nonce` (256 bits, `secrets`), `prepared_at_ms`, `expires_at_ms` (= `prepared_at_ms` + `T_nonce`).

Défi = SHA-256(séparation de domaine ‖ octets canoniques ‖ `0x00` ‖ nonce), la même construction que pour l’énoncé d’approbation avec un autre domaine. Le résumé affiché est dérivé des octets canoniques par le client local, pas par le serveur.

**Liaison à la reprise effective** (opérations 1 à 4 ; §5.5.1, étape 4 ; §14, point 21).
- **Signée et couverte par le défi.** `effective_resume_entry_hash` appartient aux octets canoniques signés, y compris lorsqu’il vaut `null`, comme tout autre champ de l’énoncé. Le défi, dérivé de ces octets, le couvre donc aussi ; le client local le recalcule lui-même (§4.2, étape 2). Une assertion ne vaut que pour la valeur qu’elle signe.
- **Contrôlée par V0, pas par `prepare`.** La valeur inscrite par `prepare` provient d’un processus du compte de service ; elle n’est pas digne de confiance en soi, et le propriétaire n’est pas tenu de la vérifier avant de signer. V0 reconstruit cet identifiant à partir de la chaîne locale concordante avec l’ancre relue, sans queue en attente (§5.5.1, étapes 1 et 4), et le compare à la valeur signée. Toute différence entraîne un refus, et le nonce passe à `FAILED`.
- **Ce qui ne peut pas l’établir.** Ni une valeur SQLite seule (colonne, cache, témoin local), ni `prepared_at_ms` : tous deux sont fixés ou modifiables par le compte de service (§5.5.1, « Sort du nonce selon l’issue »).
- **Comparaison réservée à V0 — décidé par le propriétaire le 26 octobre 2026 [D]** (§14, point 21).
  - V0 compare le champ signé à la reprise effective courante au moment de l’`apply` (§5.5.1, étape 4).
  - V1 et E vérifient ce champ uniquement comme partie de l’énoncé signé : octets canoniques, défi et signature (§5.5.2). Ils ne le comparent pas à la reprise effective courante.
  - Une reprise ultérieure ne rend donc pas inutilisables les confirmations déjà enregistrées.
  - E continue d’appliquer le contrôle de la politique et de la suspension courantes (§11.2, étape 4).
- **Création d’une invitation.** Son protocole signé n’est pas encore défini (§6.2). **Contrainte à intégrer lors de sa conception :** son énoncé signé devra suivre la même règle (champ `effective_resume_entry_hash` toujours présent, même valeur ou `null` explicite), couvert par son défi, reconstruit par son V0 à partir de la chaîne concordante avec l’ancre relue et comparé à la valeur signée.

**Liaison à l’autorisation effective de la clé signataire** (toute opération administrative signée ; §5.5.1, étape 5 ; §5.5.2, contrôle 7 ; §14, point 9).
- **Signée et couverte par le défi**, comme tout champ de l’énoncé. C’est cette valeur signée, et non l’ordre du journal ni une date SQLite, qui rattache l’assertion à une autorisation existante : l’ordre des entrées J-b date l’enregistrement, pas la signature.
- **Contrôlée par V0 et par V1, pas par `prepare`.** Contrairement à `effective_resume_entry_hash`, dont la comparaison est réservée à V0, V1 vérifie aussi que l’autorisation liée reste valable. Pour une opération qui ferme, V0 la vérifie contre le fichier de confiance protégé par `root`, sans relire J-c ni exiger une queue vide, et refuse l’opération s’il ne peut pas établir que la chaîne d’autorisation de la clé n’a pas été invalidée (§5.5.1, étape 5) ; le brouillon ne prévoit pas de V1 pour une fermeture.
- **[R] Condition pour que la liaison prouve quelque chose :** l’identifiant doit être imprévisible avant l’écriture de l’entrée d’autorisation, comme l’empreinte d’une entrée, et non sa séquence. Le choix de l’encodage reste ouvert [O].

**Limite.** L’authentificateur n’a pas d’écran : il signe ce que le client lui donne (§12).

[O] Lier aussi la tête du journal au moment du `prepare`. La protection contre un changement d’état entre `prepare` et `apply` serait plus forte, mais toute écriture concurrente invaliderait l’énoncé. Cette option est distincte de la liaison à la reprise effective, qui est exigée : l’identifiant de reprise ne change que lorsqu’une nouvelle reprise devient effective, et une écriture concurrente ordinaire ne l’invalide pas.

### 5.4 Nonce à usage unique

- [R] Table `admin_nonces` : nonce unique, opération, `statement_sha256`, `prepared_at_ms`, `expires_at_ms`, état `ISSUED` → `CONSUMED` | `EXPIRED` | `FAILED`. Les états sont terminaux ; une ligne n’est jamais supprimée ni rouverte (déclencheurs, comme en v5).
- Un seul nonce ouvert par cible et par opération.
- Le nonce passe à `CONSUMED` dans la transaction qui écrit l’effet, et seulement dans celle-ci : il est consommé si et seulement si l’effet est validé. Le passage à `FAILED` et le cas d’un arrêt du processus sont décrits au §5.5.
- `statement_sha256` porte sur l’énoncé entier, donc aussi, pour les opérations 1 à 4 du §11.2, sur l’identifiant de reprise (§5.3). La liaison n’ajoute aucune règle de nonce : un écart détecté à l’étape 4 de V0 fait passer le nonce à `FAILED`, comme les autres refus des étapes 2 à 8 ; les règles des étapes 1a et 1b restent inchangées (§5.5.1 ; §14, point 21).
- [O] `T_nonce`.

### 5.5 Assertion : vérification initiale, revérifications et compteur

Trois contrôles distincts s’appliquent à une confirmation. Ils ne doivent pas être confondus.

| | **V0 — vérification initiale** | **V1 — revérification d’intégrité** | **E — contrôle d’effectivité** |
|---|---|---|---|
| Quand | Une seule fois, pendant `apply`, avant le `COMMIT` | Avant d’ancrer l’entrée qui consigne la confirmation (validation pré-ancrage), et dans chaque contrôle E | À chaque usage par le chemin d’approbation (§11.2) |
| Question posée | Le propriétaire autorise-t-il maintenant cette opération ? | La confirmation stockée est-elle authentique et inchangée ? | La confirmation est-elle authentique **et** couverte par l’ancre relue maintenant ? |
| Dépend de l’ancre | Seulement pour la précondition d’environnement (étape 1) | **Non** | **Oui** : relecture au moment de l’usage |
| Fraîcheur | Exigée | Sans objet | Sans objet |
| Nonce | Doit être `ISSUED` ; passe à `CONSUMED` | Doit être `CONSUMED` et désigner cette confirmation ; jamais modifié | Comme V1 |
| Compteur | Comparé pour signal seulement, jamais motif de refus, puis enregistré (§5.5.4) | Jamais comparé | Jamais comparé |
| Écritures | Effet, confirmation, compteur, journal, nonce | Aucune | Aucune |

V1 ne dépend pas de l’ancre : elle peut donc précéder l’ancrage. E = V1 + relecture de l’ancre + couverture de l’entrée ; elle seule rend une confirmation utilisable.

#### 5.5.1 V0, pendant `apply`

**Précondition γ1 — décidée le 27 octobre 2026 [D] (§5.5.5, J.5 et J.7).** Avant les étapes ci-dessous, et donc avant toute vérification de l’assertion, V0 tient la barrière γ1 et lit la politique `root`. Le cas échéant, il consigne la génération non consignée dans la même transaction. **Réserve (§5.5.5, L.8, point 8, décidé le 29 octobre 2026 [D]) :** cette consignation ne s’applique pas à une génération visible mais non déclarée effective ; le service reste alors fermé et ne l’utilise pas : aucune opération signée, aucune consignation de `c` ni aucun ancrage pour cette génération avant sa déclaration d’effectivité. **Point de sauvegarde — décidé le 27 octobre 2026 [D] (§14, point 24) :** juste après `BEGIN IMMEDIATE`, avant toute écriture de l’opération et donc avant la consignation éventuelle de `c`, V0 crée un `SAVEPOINT`. Un échec propre à cette précondition laisse le nonce `ISSUED` : impossibilité d’obtenir la barrière, politique `root` inaccessible, consignation de `c` impossible, ou divergence d’intégrité qu’elle détecte. Cette règle ne s’étend pas aux étapes ci-dessous. Le refus 1b garde sa règle `FAILED`, et chaque autre étape son sort de nonce déjà décidé (« Sort du nonce selon l’issue », ci-dessous). Si la précondition γ1 échoue, les étapes suivantes ne sont pas évaluées lors de cette tentative. L’ordre de prise est décidé (§5.5.5, L.2) [D] : W en exclusif, avec l’examen des marqueurs sous W [D, 28 octobre 2026], puis G, puis B en partagé, relâchement de G, puis `BEGIN IMMEDIATE`. B est gardée jusqu’au `COMMIT` ou au rollback.

**Verrou W et marqueur — décidés le 28 octobre 2026 [D]** (§5.5.5, L.2 ; cas 3, « Mécanisme du marqueur », ci-dessous). Avant G, V0 prend W, verrou exclusif qui sérialise les transactions couvertes, et examine sous W les marqueurs existants. Pour une opération qui ouvre, un marqueur résiduel entraîne un refus sans écriture ; la qualification de ce refus et le sort du nonce restent ouverts [O], comme la conduite d’une opération signée qui ferme dans ce cas [O]. L’ordre de prise ci-dessus suit sans changement. Après le `SAVEPOINT`, V0 crée son marqueur avant toute écriture de la transaction, donc avant la lecture de la politique (S4), la comparaison des générations (S5) et toute consignation de `c`. Il garde W jusqu’à la résolution de la transaction sur la connexion. Après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi, il peut tenter de retirer son marqueur. Une fois la transaction résolue, il relâche B, puis W, même si le retrait a échoué ou n’a pas été tenté ; un marqueur laissé en place maintient le gel (précisé le même jour : cas 3, « Mécanisme du marqueur », ci-dessous).

Dans la transaction `BEGIN IMMEDIATE`, dans cet ordre :

1. **Préconditions d’environnement**, avant toute vérification de l’assertion, pour les opérations qui ouvrent seulement (§11.2) : l’ancre J-c est **relue à ce moment** (jamais le témoin local ni une valeur en cache), elle concorde avec la chaîne locale, et la tête locale est égale à la tête relue, sans queue en attente. Ce contrôle porte sur l’état **antérieur** à l’opération ; il ne rend pas effective la confirmation à venir, qui devra encore réussir E après son propre ancrage. Les opérations qui ferment ne dépendent pas de l’ancre. Cette étape comprend deux contrôles, dont le sort du nonce diffère. Règle consignée le 26 octobre 2026 sur instruction du propriétaire [D] (§14, point 21) :
   - **1a. Ancre et queue.** Ancre indisponible, absente ou divergente, ou queue en attente d’ancrage. Si V0 refuse **uniquement** pour l’une de ces raisons, le refus ne compte pas comme une tentative : le nonce reste `ISSUED`. Une nouvelle tentative reste possible tant que le nonce n’a pas expiré (`expires_at_ms`), à condition de reprendre le **même énoncé signé**.
   - **1b. Politique d’attestation suspendue** (§5.2.7, M.6 ; §11.2). Elle s’applique aux opérations ordinaires qui ouvrent (opérations 1 à 4 du §11.2), qu’il y ait ou non en même temps un motif 1a. Le refus fait passer le nonce à `FAILED`. Cette mise à jour est distincte des écritures de l’opération, mais a lieu dans la même transaction `BEGIN IMMEDIATE`, après un retour au `SAVEPOINT` (formulation modifiée le 27 octobre 2026 ; §14, point 24). L’opération n’est pas enregistrée. Après la reprise effective, il faudra un **nouveau nonce et une nouvelle assertion**. Cette règle est garantie par la liaison de l’étape 4.
     - Le nonce visé est celui que désigne l’énoncé présenté, s’il existe et est `ISSUED`.
     - Pour la création d’une invitation, dont le protocole signé n’est pas décrit (§6.2), la même règle s’appliquera à son nonce s’il en a un.
     - La reprise de suspension (opération 5) n’est pas concernée : son V0 suit ses propres conditions (§11.2).
2. **Nonce** : la ligne existe, est `ISSUED`, et son `statement_sha256` est celui de l’énoncé présenté.
3. **Fraîcheur** : l’horloge du stockage, lue dans la transaction et qui ne peut pas reculer (règle v3), est strictement inférieure à `expires_at_ms`. « Fraîche » signifie ici : produite pour ce nonce (le défi le contient) et présentée pendant qu’il est `ISSUED` et non échu. [O] `T_nonce`.
4. **Énoncé** : reconstruit depuis l’état courant de la base et identique, octet pour octet, à l’énoncé présenté. Pour les opérations 1 à 4, le champ de reprise de l’énoncé reconstruit ne provient pas de la base seule : il est établi comme indiqué ci-dessous.
   - **Liaison à la reprise effective — exigence de sécurité, non facultative** (opérations 1 à 4 ; §14, point 21). Elle garantit la règle décidée : après une reprise effective, une ancienne assertion ne peut pas être réutilisée, et il faut un nouveau nonce et une nouvelle assertion.
   - **Contenu de la liaison — décidé par le propriétaire le 26 octobre 2026 [D].** Le champ `effective_resume_entry_hash` (§5.3), toujours présent, contient l’`entry_hash` de l’entrée de journal de la **dernière reprise de suspension effective et ancrée** au moment du `prepare`, en 64 caractères hexadécimaux minuscules. Aucune séquence n’est ajoutée : l’empreinte identifie l’entrée. Avant toute reprise effective, il vaut `null` explicite.
   - **Reconstruction et comparaison.** V0 reconstruit la valeur attendue (l’`entry_hash` de la reprise effective **courante**, au sens du §5.2.7, M.6, ou `null` avant toute reprise effective) à partir de la chaîne locale dont l’étape 1 a vérifié la concordance avec l’ancre relue, sans queue en attente. Il le compare à la valeur signée. Celle-ci appartient aux octets canoniques (§5.3) ; le défi vérifié à l’étape 6 la couvre donc aussi.
   - **Comparaison réservée à V0 — décidé par le propriétaire le 26 octobre 2026 [D]** (§5.3 ; §14, point 21). Cette comparaison à la reprise effective courante a lieu une seule fois, ici, au moment de l’`apply`. V1 et E ne la refont pas (§11.2) : une reprise ultérieure ne rend pas inutilisables les confirmations déjà enregistrées.
   - **Ce qui ne peut pas établir la liaison.** Ni une valeur SQLite seule (colonne, cache, témoin local), ni `prepared_at_ms` (voir « Sort du nonce selon l’issue », ci-dessous).
   - **Refus.** Toute différence entraîne un refus, et le nonce passe à `FAILED` comme pour les autres échecs des étapes 2 à 8.
   - **Création d’une invitation.** Son protocole signé n’est pas encore défini (§6.2) ; il devra suivre la même règle lorsqu’il sera conçu (§5.3).
5. **Credential d’administration** : présent dans le fichier de confiance avec le statut `ACTIVE` et actif en base. `RETIRED` et `COMPROMISED` sont refusés pour toute nouvelle opération (§5.5.3, décidé le 26 octobre 2026 [D]). Une clé ajoutée par une clé ultérieurement `COMPROMISED` est aussi refusée tant que sa réautorisation par une clé `ACTIVE` n’est pas effective. Ensuite, elle n’est acceptée que pour les opérations autorisées après l’entrée effective de cette réautorisation (§5.5.3 [D] ; mécanisme [O]).
   - **Liaison à l’autorisation effective de la clé signataire — décidé par le propriétaire le 26 octobre 2026 [D]** (§5.3 ; §14, point 9). L’énoncé signé lie l’entrée qui autorise effectivement la clé signataire : genèse initiale, ajout ou réautorisation. Pour une opération qui ouvre, V0 vérifie, à l’`apply`, que cette entrée est l’autorisation effective courante du credential utilisé, d’après la chaîne concordante avec l’ancre relue. Pour une opération qui ferme, la vérification suit la puce suivante. Toute différence entraîne un refus, et le nonce passe à `FAILED`, comme pour les autres refus des étapes 2 à 8.
   - **Opérations signées qui ferment — décidé par le propriétaire le 26 octobre 2026, précisé le 27 octobre 2026 [D]** (§11.2 ; §14, point 9) :
     - V0 n’accepte l’opération que si le credential signataire est autorisé **et** si sa chaîne d’autorisation n’a pas été invalidée, par exemple parce que sa chaîne d’ajout dépend d’une clé `COMPROMISED` sans réautorisation effective (§5.5.3). Le statut `ACTIVE` dans le fichier de confiance est exigé, mais **ne suffit pas à lui seul** (27 octobre) ;
     - V0 compare l’identifiant d’autorisation inclus dans l’énoncé signé à l’entrée d’autorisation effective conservée, pour ce credential, dans le fichier de confiance protégé par `root` (§9.2) (26 octobre) ;
     - cette vérification ne relit pas J-c et n’exige pas une queue vide : l’étape 1 ne s’applique toujours pas aux opérations qui ferment ;
     - si V0 ne peut pas établir cette validité (fichier, entrée, chaîne ou correspondance manquante, invalide ou incohérente), l’opération signée est refusée, et le nonce passe à `FAILED` comme pour les autres refus des étapes 2 à 8 ;
     - la voie d’urgence D-9 reste distincte (§7.0) et limitée à sa portée déjà décidée, la fermeture de l’interrupteur. Cette décision ne l’étend pas aux autres opérations qui ferment ; leur extension reste une recommandation [R] (§7.0 ; §14, point 12) ;
     - acceptée, la fermeture prend effet au `COMMIT` local, sans relecture de J-c ni attente de l’ancrage. Un échec d’ancrage ultérieur ne la rouvre pas ; son entrée reste à ancrer selon la chaîne normale (§11.2) ;
     - **conséquence, et non règle nouvelle :** tant que la représentation de la chaîne d’autorisation et la preuve de sa validité restent ouvertes (ci-dessous), V0 ne peut pas établir cette validité, et toute opération signée qui ferme serait refusée. Hors de la portée D-9, aucune voie de repli n’est alors décidée. Les options de mise en œuvre sont analysées au §5.5.5.
   - **Assertion préparée avant une nouvelle autorisation — décidé [D].** Elle ne peut pas être appliquée après celle-ci : elle lie l’ancienne entrée d’autorisation, ou aucune, et V0 la refuse. Cela vaut notamment pour une assertion préparée ou signée avant une réautorisation (§5.5.3). La garantie repose sur la valeur signée. Elle ne repose ni sur l’ordre des entrées J-b, qui date l’enregistrement et non la création de l’assertion WebAuthn, ni sur `prepared_at_ms`, l’instant de vérification ou une autre date SQLite, qui ne sont pas une preuve fiable (§5.3).
   - **Ouverts [O] :**
     - le nom du champ, son encodage, la représentation de l’autorisation initiale de genèse et le format des opérations d’ajout et de réautorisation (§5.3) ;
     - la désignation de la clé signataire dans l’énoncé, que `prepare` ne connaît pas aujourd’hui (§5.3) ;
     - **opérations qui ferment :** la représentation de l’entrée et de la chaîne d’autorisation dans la politique protégée par `root` (fichier de confiance, §9.2), y compris le reflet d’une invalidation par une chaîne d’ajout dépendant d’une clé `COMPROMISED` ; la preuve que l’entrée était déjà effective et que la chaîne n’a pas été invalidée ; leur cohérence avec le journal (J-b et J-c) ; la conduite en cas de divergence ou d’impossibilité d’écrire le journal. Le risque relevé auparavant, celui d’un credential dont l’autorisation est invalidée mais dont le statut reste `ACTIVE` faute de changement automatique, est écarté par la décision du 27 octobre : faute de pouvoir établir la validité de la chaîne, V0 refuse (§5.5.3). Analyse, recommandation [R] et décisions de portée du 27 octobre 2026 [D] : §5.5.5 ; §14, point 23 ;
     - l’ancrage de l’entrée de genèse, dont le moment reste ouvert (§11.4) ;
     - le sort d’une assertion préparée entre l’écriture d’une entrée d’autorisation et le moment où elle devient effective.
6. **Assertion** : `type = webauthn.get` ; défi recalculé par le stockage à partir de l’énoncé et du nonce ; origine et `rpIdHash` d’administration ; UP et UV ; règles BE/BS ; signature valide avec la clé publique épinglée.
7. **Compteur** — option (b), signal seulement, décidée par le propriétaire le 26 octobre 2026 [D] (§5.5.4 ; §14, point 8) : la valeur `signCount` de l’assertion est comparée à la dernière valeur acceptée pour ce credential, uniquement pour détecter une anomalie. Cette étape **ne refuse jamais** : un signal ne fait pas passer le nonce à `FAILED` et ne bloque pas l’effet si les autres contrôles réussissent.
8. **Préconditions métier** de l’opération (§6.2 pour `CONFIRM`).
9. **Écritures** : effet ; ligne `admin_confirmations` (énoncé canonique, `authenticatorData`, `clientDataJSON`, signature, credential utilisé, valeur du compteur acceptée, instant de vérification) ; nouvelle valeur du compteur du credential, enregistrée y compris après un signal (§5.5.4) ; entrée de journal J-b ; nonce `ISSUED` → `CONSUMED`, avec la référence de la confirmation.
10. `COMMIT`.

**Sort du nonce selon l’issue**

- **Succès** : le nonce est `CONSUMED` dans la même transaction que l’effet. Toute nouvelle présentation de la même assertion est refusée à l’étape 2.
- **Refus à l’étape 1a seulement** (ancre ou queue) : rollback, et le nonce reste `ISSUED`. Une nouvelle tentative est possible avec le même énoncé signé avant `expires_at_ms` (§14, point 21).
- **Échec propre à la barrière γ1, avant la vérification de l’assertion — décidé le 27 octobre 2026 [D] (§5.5.5, J.7).** Seuls les cas ci-dessous laissent le nonce `ISSUED`. Ils ne couvrent pas le refus 1b, qui garde sa règle `FAILED` (ci-dessous).
  - **Échec de la barrière, politique `root` inaccessible ou échec de l’écriture de `c` :** rollback complet, refus fermé, nonce `ISSUED`. Après la résolution, le même énoncé signé peut être retenté avant `expires_at_ms`.
  - **Divergence d’intégrité entre la politique `root` et l’événement conservé, détectée par la barrière :** refus fermé, et S4 maintenu jusqu’à la résolution (§11.3). Aucune écriture séparée de `FAILED` n’est tentée. Le nonce reste `ISSUED`, mais aucune opération signée n’est admise pendant S4. Après la résolution, V0 revérifie entièrement l’énoncé et le nonce, qui doit encore être valide.
  - **Barrière obtenue, échec ensuite :** chaque étape garde son sort de nonce déjà décidé. L’étape 1a laisse le nonce `ISSUED` (ci-dessus). L’étape 1b et les étapes 2 à 8 le font passer à `FAILED` (ci-dessous).
- **Refus à l’étape 1b** (politique d’attestation suspendue, opérations 1 à 4). Le service revient au `SAVEPOINT`, ce qui annule les écritures de l’opération. Dans la même transaction, il effectue la transition conditionnelle `ISSUED` → `FAILED`, puis le `COMMIT`, et relâche B, puis W [D, 28 octobre 2026]. L’opération n’est pas enregistrée. Après la reprise effective, un nouveau nonce et une nouvelle assertion sont nécessaires (§14, point 21). **Formulation modifiée le 27 octobre 2026 [D]** (§14, point 24) : la mise à jour du nonce n’a plus lieu « dans une transaction distincte ». Elle reste distincte des écritures de l’opération grâce au `SAVEPOINT`, mais se fait dans la même transaction. Pour les erreurs SQLite, voir « Course entre un échec de V0 et l’écriture de `FAILED` », ci-dessous.
  - **Garantie de la règle dans ce cas : liaison à la reprise effective (étape 4).** Une assertion antérieure à une reprise effective ne peut pas être réutilisée, même si son nonce est resté `ISSUED`. Cette garantie repose sur l’exigence de l’étape 4, **et non sur `prepared_at_ms`**, qui ne suffit pas :
    - `prepared_at_ms` est bien couvert par la signature, car il fait partie des octets canoniques (§5.3) ;
    - mais sa valeur est fixée au `prepare` par un processus du compte de service, à partir de l’horloge et d’un compteur conservé en base (`store_meta.last_observed_ms`, `approval_store.py:238-240, 1020-1032` à `6313648`) ;
    - un processus qui peut écrire la base peut contourner ce compteur (§2.2), et le propriétaire n’est pas tenu de vérifier cette valeur avant de signer ;
    - `prepared_at_ms` ne prouve donc pas que l’énoncé a été préparé avant ou après une reprise.
- **Échec des étapes 2 à 8.** Même séquence, décidée le 27 octobre 2026 [D] (§14, point 24) : retour au `SAVEPOINT`, transition conditionnelle `ISSUED` → `FAILED` dans la même transaction, `COMMIT`, puis libération de B, puis de W [D, 28 octobre 2026]. C’est la règle « une tentative par nonce » (§10.3), hors erreurs SQLite (ci-dessous).
- **Échec de l’écriture de `FAILED`, dans tous les cas — décidé le 27 octobre 2026 [D] (§5.5.5, J.7).** Il ne permet jamais un effet : l’opération reste refusée. Ce que l’on peut alors établir dépend de la réussite du retour au `SAVEPOINT` (« Erreurs SQLite dans la transaction de V0 », ci-dessous).
- **Arrêt du processus avant le `COMMIT`** : rien n’est écrit et le nonce reste `ISSUED`. La même assertion peut être présentée de nouveau avant `expires_at_ms` : ce n’est pas un rejeu, puisqu’aucun effet n’a été validé. L’usage unique est garanti par le `COMMIT`, qui consomme le nonce en même temps que l’effet. Si le marqueur du gel était déjà présent, le gel conservateur s’applique [D] : pour une opération qui ouvre, cette nouvelle présentation n’est acceptée qu’après la levée (« Erreurs SQLite dans la transaction de V0 », cas 3, « Gel conservateur »).
- **Échec de synchronisation du marqueur avant toute écriture — décidé le 28 octobre 2026 [D]** (cas 3, « Mécanisme du marqueur », « Refus et nonce après échec de synchronisation »). Le refus est un échec technique fermé, sans effet ni écriture SQLite. Le nonce n’est ni consommé, ni passé à `FAILED`, ni renouvelé ; s’il est encore `ISSUED`, il le reste jusqu’à son expiration normale. Le refus n’incrémente ni le compteur des tentatives d’autorisation, ni le compteur borné par opération et par classe de refus du §10.3 (précisé le même jour). Aucune nouvelle tentative automatique n’est lancée ; après récupération du stockage, une nouvelle présentation du même énoncé signé repasse les contrôles normaux et n’est possible que si le nonce est encore valide.
- **Arrêt après le `COMMIT`**, avant la réponse au propriétaire : l’opération est enregistrée et le nonce `CONSUMED`. `show` le fait apparaître ; une nouvelle présentation est refusée. Si l’arrêt précède le retrait du marqueur, le gel conservateur s’applique [D] (même renvoi).
- **Erreur du `COMMIT` de l’étape 10 — consigné le 27 octobre 2026 sur instruction du propriétaire [D].** Ce n’est ni un succès ni un refus, et aucune nouvelle tentative automatique n’est lancée. L’état est constaté avant toute nouvelle tentative (« Erreurs SQLite dans la transaction de V0 », cas 3, ci-dessous). Si l’issue reste indéterminée, le gel décidé le même jour s’applique [D] (même renvoi).
- **Deux `apply` concurrents** sur le même nonce : `BEGIN IMMEDIATE` les sérialise ; le second trouve le nonce `CONSUMED` et il est refusé.
- **Course entre un échec de V0 et l’écriture de `FAILED` — fermée par décision du 27 octobre 2026 [D] (§14, point 24).**
  - **Constat.** Avec un `ROLLBACK` complet suivi d’une transaction distincte, un second `apply` pouvait, entre les deux, prendre B, exécuter `BEGIN IMMEDIATE` et lire le nonce encore `ISSUED`. Garder B n’y aurait rien changé, puisque B est partagée entre les transactions du service.
  - **Protocole décidé [D].**
    1. `BEGIN IMMEDIATE`, puis `SAVEPOINT` avant toute écriture de l’opération, y compris la consignation éventuelle de `c`.
    2. Si V0 doit refuser et faire échouer le nonce (1b ou étapes 2 à 8) : retour au `SAVEPOINT`. Les écritures de l’opération sont annulées, `c` comprise. La transaction SQLite et son verrou d’écriture sont conservés.
    3. Dans cette même transaction : transition conditionnelle `ISSUED` → `FAILED`, seulement si le nonce est encore `ISSUED`. Un état terminal, tel que `CONSUMED`, n’est jamais remplacé.
    4. `COMMIT` de la transaction externe, puis libération de B, puis de W [D, 28 octobre 2026]. B n’est jamais relâchée après le seul retour au `SAVEPOINT`.
  - **Pourquoi la course est fermée.**
    - De l’échec jusqu’au `COMMIT`, la transaction garde le verrou d’écriture SQLite.
    - Un second `apply` attend ce verrou à son `BEGIN IMMEDIATE`. Quand il l’obtient, le nonce est déjà `FAILED`, et l’étape 2 le refuse.
    - Entre processus qui respectent le protocole, aucun entrelacement ne lui permet donc de décider sur un nonce `ISSUED` entre l’annulation des effets et `FAILED`.
    - Une simple lecture hors transaction d’écriture, par exemple un affichage, peut voir `ISSUED` dans cet intervalle. Elle ne décide rien, puisque V0 décide toujours sous `BEGIN IMMEDIATE`.
  - **Ordre des verrous.** Il est inchangé : G, puis B, relâchement de G, puis `BEGIN IMMEDIATE`. W est pris avant G, et les marqueurs sont examinés sous W [D, 28 octobre 2026]. B est relâchée après le `COMMIT` ou le `ROLLBACK` complet de la transaction externe, puis W. La transition se fait sous le verrou SQLite déjà tenu, sans demander G ni B : il n’y a pas de cycle (§5.5.5, L.4).
  - **Cas non concernés.**
    - Les refus 1a et les refus propres à γ1 gardent leur règle décidée : rollback complet, nonce `ISSUED` (J.7).
    - Les erreurs d’assertion ou de V0 survenues après la barrière gardent les classifications déjà décidées.
    - Ce protocole n’oppose rien à un compte de service compromis qui écrit directement la base (J.6).
  - **Erreurs SQLite — formulation précisée le 27 octobre 2026 sur instruction du propriétaire.** La formulation antérieure, « Dans tous ces cas, aucun effet de l’opération ne subsiste », est remplacée. Elle confondait l’effet de l’opération, annulé au `SAVEPOINT` lorsque ce retour réussit, avec une annulation qui n’est pas toujours établie. L’ancienne piste d’une écriture de `FAILED` dans une nouvelle transaction est écartée par l’option (a) [D]. Voir « Erreurs SQLite dans la transaction de V0 », ci-dessous.
    - **Retour au `SAVEPOINT` réussi, puis échec de la transition ou du `COMMIT` :** l’effet de l’opération, `c` comprise, est annulé. Seul le sort du nonce peut être incertain (cas 1).
    - **Échec du retour au `SAVEPOINT` ou de l’annulation complète :** la transaction externe n’est jamais validée [D], et aucun `COMMIT` ne suit. L’absence d’effet n’est affirmée comme établie qu’une fois l’annulation établie (cas 2, point 1). Lorsque l’annulation est seulement déduite sous C2 (cas 2, point 2), l’absence d’effet reste une déduction [R], non un état établi. Ni le code fixe du refus (cas 2, point 5) ni la catégorie de sortie recommandée (§10.2) ne l’affirment, dans aucun de ces deux cas [R]. Refus fermé et récupération : cas 2.
    - **Erreur du `COMMIT` du chemin de succès :** cas 3.
    - **`SQLITE_BUSY` et autres erreurs :** cas 4.

**Erreurs SQLite dans la transaction de V0 : analyse [R], précisions consignées le 27 octobre 2026 sur instruction du propriétaire [D] et points ouverts [O]**

**Portée.** Ce paragraphe précise le chemin d’échec de l’option (a) (§14, point 24) et le `COMMIT` du chemin de succès (étape 10). Il ne modifie pas l’option (a) : retour au `SAVEPOINT`, puis transition conditionnelle `ISSUED` → `FAILED` dans la transaction externe, sans réécriture de `FAILED` dans une transaction séparée. Il ne modifie pas non plus les règles 1a et 1b, γ1 (J.7), S4, la barrière (§5.5.5, L) ni D-9. On distingue ici les faits documentés [F], avec leur source, les déductions [R], les hypothèses [H] et les points ouverts [O].

**Sources officielles consultées le 27 octobre 2026.**
- (savepoint) https://www.sqlite.org/lang_savepoint.html
- (transaction) https://www.sqlite.org/lang_transaction.html
- (autocommit) https://www.sqlite.org/c3ref/get_autocommit.html
- (close) https://www.sqlite.org/c3ref/close.html
- (rescode) https://www.sqlite.org/rescode.html
- (conflict) https://www.sqlite.org/lang_conflict.html
- (wal) https://www.sqlite.org/wal.html
- (pragma) https://www.sqlite.org/pragma.html#pragma_synchronous
- (corrupt) https://www.sqlite.org/howtocorrupt.html
- (atomic) https://www.sqlite.org/atomiccommit.html, qui ne traite explicitement que le mode rollback
- (python) https://docs.python.org/3.14/library/sqlite3.html

**Pilote et configuration.**
- [F] Dépôt à `73737dd` :
  - Python `>=3.14.4,<3.15` (`approval_service/pyproject.toml:5`) ;
  - module `sqlite3` de la bibliothèque standard, ouvert avec `autocommit=True` et un délai d’occupation `timeout` (`approval_store.py:385-389`) ;
  - mode de journal WAL, `synchronous = FULL`, `foreign_keys` et `busy_timeout` contrôlés à chaque connexion (`approval_store.py:394-407`) ;
  - SQLite 3.37.0 au moins (`approval_store.py:73`) ;
  - déclencheurs en `RAISE(ABORT, …)`, et aucun `SAVEPOINT` encore dans le dépôt ;
  - à `c41146b`, la v5 redéfinissait `initialize` et `_connection` (`approval_store_v5.py:297-361`), qui appelaient les fonctions de connexion d’`approval_store.py`, dont `_check_sqlite_version` et `_connect`. Après `e431cea`, elle hérite ces deux méthodes d’`ApprovalStore`, qui appellent ces mêmes fonctions (`approval_store_v5.py:288` ; `approval_store.py:680-728, 974-986` à `6313648`). Aux deux états, elle garde sa propre `_verify_connection` (`approval_store_v5.py:217-236`).
- Le code d’administration V0 n’existe pas. Qu’il réutilise ces fonctions est une hypothèse [H].
- **Version de SQLite réellement liée sur le serveur : inconnue [O].** Le serveur n’a pas été consulté. Les versions relevées le 27 octobre 2026 sur le poste du propriétaire, qui n’est pas l’environnement d’exécution, ne valent pas pour le serveur.
- [F] (python) Avec `autocommit=True`, `commit()` et `rollback()` sont sans effet. `close()` n’exécute alors aucun contrôle implicite de transaction.

**Portée des moyens d’observation : ce qu’ils établissent, et ce qu’ils n’établissent pas.**
- **`in_transaction`.**
  - [F] (python) Il correspond au mode autocommit de bas niveau de SQLite, et il est vrai si une transaction est active.
  - [F] (autocommit) Le mode autocommit est réactivé par un `COMMIT` ou par un `ROLLBACK`. Après une erreur sur une instruction d’une transaction, `sqlite3_get_autocommit()` est le seul moyen de savoir si SQLite a annulé automatiquement la transaction.
  - **`in_transaction` faux signifie seulement qu’aucune transaction n’est active sur cette connexion.** À lui seul, il ne prouve pas que la transaction a été annulée plutôt que validée [R].
  - **Erreur avant le `COMMIT`** : une instruction de l’opération, `ROLLBACK TO` ou la transition. Si `in_transaction` est faux, et si aucun `COMMIT` n’a été exécuté sur cette connexion depuis `BEGIN IMMEDIATE`, la seule fin restante est une annulation. C’est une déduction [R] sous C2, qui suppose qu’aucune instruction n’a été exécutée après l’erreur.
  - **Erreur pendant le `COMMIT`.**
    - `in_transaction` faux est compatible avec une validation comme avec une annulation : l’issue est indéterminée [O].
    - `in_transaction` vrai indique que SQLite tient la transaction pour encore active.
    - Qu’aucune écriture de ce `COMMIT` en erreur ne soit devenue persistante n’est documenté que pour le `SQLITE_BUSY` dû à un lecteur (cas 4). Dans les autres cas, ce point reste ouvert [O].
  - [R] `in_transaction` ne dit rien de ce qui a été rendu durable, ni de ce que voient les autres connexions.
- **`close()`.**
  - [F] (python, close) Avec `autocommit=True`, Python n’exécute aucun contrôle de transaction à la fermeture. C’est SQLite qui annule une transaction ouverte lorsque la connexion est détruite.
  - [F] (close) Avec `sqlite3_close_v2()`, des instructions non finalisées retardent cette destruction : la connexion devient un « zombie ».
  - [H] Il n’est pas vérifié que CPython 3.14 appelle `sqlite3_close_v2()` ni qu’il finalise ses instructions avant.
  - `close()` n’est donc pas une preuve d’annulation immédiate.
- **Relecture.**
  - [F] (wal) Une transaction de lecture voit la base telle qu’elle était au dernier enregistrement de validation valide, relevé à son début.
  - Elle établit donc l’**état visible** à cet instant, et non l’issue durable d’un `COMMIT` qui a renvoyé une erreur [O].
- **Arrêt du processus.**
  - [F] (wal) En WAL, une validation consiste à ajouter un enregistrement de validation au WAL.
  - [F] (corrupt) Une transaction partiellement écrite est annulée au prochain accès.
  - [F] (pragma) Les transactions validées sont durables face à un arrêt de l’application, quel que soit `synchronous`.
  - [R] Une transaction pour laquelle aucun `COMMIT` n’a été exécuté ne devient donc pas visible, sous la condition C2.

**Conditions de toute garantie ci-dessous [R].**
- **C1 [D].** Le `SAVEPOINT` est pris avant toute écriture de l’opération, `c` comprise.
- **C2.** Après une erreur SQLite dans cette transaction, la connexion n’exécute plus aucune instruction autre que `ROLLBACK`.
  - Raison [F] (transaction, autocommit) : une erreur peut annuler toute la transaction et ramener la connexion au mode autocommit. Une écriture exécutée ensuite serait alors validée seule.
  - Non démontré tant que le code n’existe pas [O].
- **C3.** Configuration contrôlée à chaque connexion : WAL et `synchronous = FULL` [F, dépôt]. Système de fichiers local, une seule copie de SQLite dans le processus, aucun accès direct au fichier de base ni au WAL (wal, corrupt) [H, serveur non vérifié].
- **C4.** Les périphériques respectent la synchronisation demandée (atomic, corrupt) [H].

**Cas 1 : chemin d’échec après un retour au `SAVEPOINT` réussi (refus 1b ou étapes 2 à 8).**
- **Effet de l’opération.**
  - [F] (savepoint) Un `ROLLBACK TO` réussi ramène la base à l’état qui suivait le `SAVEPOINT`, sans annuler la transaction.
  - Les écritures de l’opération, `c` comprise, sont donc annulées à ce point.
  - **[R] L’effet de l’opération est annulé à ce point, quelle que soit la suite**, sous C1 et C2. Un `COMMIT` ultérieur ne peut valider que les écritures faites après ce retour : la transition, et le comptage borné si son écriture a lieu dans cette transaction (emplacement [O]).
  - **Marqueur du gel — décidé le 28 octobre 2026 [D].** Ce retour au `SAVEPOINT` ne permet jamais, à lui seul, de retirer le marqueur, même s’il annule l’effet de l’opération. Le retrait attend le `COMMIT` confirmé de la transition vers `FAILED`, ou un `ROLLBACK` complet réussi (cas 3, « Mécanisme du marqueur »).
- **Verrou d’écriture.**
  - La page des points de sauvegarde ne dit pas que le verrou est maintenu après `ROLLBACK TO`.
  - [R] On le déduit de la garantie de `BEGIN IMMEDIATE` (rescode : « if it succeeds, then SQLite guarantees that no subsequent operations on the same database through the next COMMIT will return SQLITE_BUSY ») [H, à confirmer].
  - La fermeture de la course (§14, point 24) repose sur ce maintien.
- **Échec de la transition conditionnelle.**
  - [F] (conflict) Un refus par un déclencheur `RAISE(ABORT)` n’annule que l’instruction : la transaction reste active.
  - [F] (transaction) Une erreur `SQLITE_FULL`, `SQLITE_IOERR`, `SQLITE_NOMEM` ou `SQLITE_INTERRUPT` peut annuler la seule instruction, ou toute la transaction.
  - Conduite inchangée [D] : aucun `COMMIT`, puis annulation complète.
  - L’effet reste annulé (ci-dessus).
  - Cette tentative ne valide rien. Le nonce reste donc dans son état antérieur, `ISSUED` lorsque l’étape 2 l’a lu ainsi, dans deux cas :
    - le `ROLLBACK` réussit [F] (transaction) ;
    - le `ROLLBACK` échoue alors que `in_transaction` est faux. Aucun `COMMIT` n’ayant été exécuté, la transaction a été annulée automatiquement (transaction : « the ROLLBACK command will fail with an error, but no harm is caused »). C’est une déduction [R], sous C2 et sous cette prémisse, et non une conséquence de `in_transaction` seul. Cette déduction ne permet pas de retirer le marqueur du gel : le gel conservateur s’applique [D] (cas 3, « Gel conservateur »). La transaction n’étant plus active, le service relâche ensuite B puis W et laisse le marqueur en place [D, 28 octobre 2026].
  - Si le `ROLLBACK` échoue et que `in_transaction` reste vrai, l’annulation n’est pas établie : récupération du cas 2.
- **Transition qui ne modifie aucune ligne.**
  - C’est le résultat attendu si l’étape 2 a trouvé le nonce dans un état terminal.
  - Si l’étape 2 l’a lu `ISSUED` sous le même verrou, ce résultat n’est pas attendu entre processus qui respectent le protocole.
  - La conduite et un éventuel rattachement au §11.3 restent ouverts [O].
- **Échec du `COMMIT` final.**
  - L’effet de l’opération reste annulé (ci-dessus), quelle que soit l’issue du `COMMIT`.
  - **Le sort du nonce est incertain** : `FAILED` ou `ISSUED`. La documentation ne fixe pas l’état persistant après un `COMMIT` en erreur, hors du cas `SQLITE_BUSY` décrit au cas 4 [O]. Seule exception : si un `ROLLBACK` explicite réussit (cas 3, a), on en déduit `ISSUED` [R], mais sa durabilité n’est pas établie [O].
  - **Résolution de la transaction et barrière B :** mêmes règles qu’au cas 3, « Résolution de la transaction et barrière B », points a à c. Aux points b et c, le gel décidé s’applique aussi, même si l’effet de l’opération est annulé. Au point a, il ne s’applique pas, sauf si une règle déjà décidée l’exige (cas 3, « Gel après une issue indéterminée ») [D].
  - L’appelant ne présente ce cas ni comme « nonce échoué », ni comme « nonce intact ».
  - Aucune réécriture de `FAILED` dans une transaction séparée (option (a) [D]). Aucune nouvelle tentative automatique.
  - **Au point a**, une tentative ultérieure relit le nonce sous `BEGIN IMMEDIATE` et suit les règles normales du nonce, qui sont inchangées. `FAILED` : refus à l’étape 2. `ISSUED` : V0 complet. Cela suppose le retrait normal du marqueur ; si le processus s’est arrêté avant, le gel conservateur s’applique [D] (cas 3, « Gel conservateur »).
  - **Aux points b et c**, aucune opération qui ouvre n’est acceptée tant que le gel n’est pas levé [D]. Le sort d’une nouvelle tentative après la levée n’est pas tranché [O].
  - La règle « une tentative par nonce » n’est alors pas garantie [O].

**Cas 2 : échec du retour au `SAVEPOINT` ou de l’annulation complète.**
- [D] (inchangé) La transaction externe n’est jamais validée. **Aucun `COMMIT` ne suit un échec du retour au `SAVEPOINT`.**
- Les écritures de l’opération peuvent encore figurer dans la transaction. **On n’affirme pas comme établi qu’aucun effet n’a subsisté tant que l’annulation n’est pas établie.** Au point 1, l’annulation est établie, et l’absence d’effet peut l’être aussi. Au point 2, l’annulation est seulement déduite sous C2 : l’absence d’effet n’est affirmée que comme déduction [R], non comme état établi. Au point 3, elle n’est pas affirmée. Aux points 1 et 2, le code fixe du refus ne l’affirme pas (point 5).
- **Refus fermé et récupération [R].**
  1. Exécuter `ROLLBACK`. S’il réussit, l’annulation est établie [F] (transaction).
  2. S’il échoue alors que `in_transaction` est faux, aucune transaction n’est plus active. Aucun `COMMIT` n’ayant été exécuté (règle ci-dessus), on en déduit l’annulation [R], sous C2 (transaction, autocommit). `in_transaction` seul ne l’établirait pas. Cette déduction ne permet pas de retirer le marqueur du gel : le gel conservateur s’applique [D] (cas 3, « Gel conservateur »). Le service relâche ensuite B puis W et laisse le marqueur en place [D, 28 octobre 2026] (point 4). Cette règle générale ne vise pas l’échec du `ROLLBACK` qui suit un échec de synchronisation du marqueur : ce cas suit une règle fail-stop plus stricte (cas 3, « Mécanisme du marqueur »).
  3. S’il échoue alors que `in_transaction` reste vrai, ou si cet état ne peut pas être lu, l’annulation **n’est pas établie**.
     - Le processus ferme la connexion et se termine, sans exécuter d’autre instruction. Le marqueur du gel reste présent : le gel conservateur s’applique [D] (cas 3, « Gel conservateur »). Cette conduite fail-stop est conservée par la décision du 28 octobre 2026 [D] ; B et W ne sont libérés qu’à la fin du processus [H]. Le processus n’émet aucun code de réponse ni message du protocole et se termine avec, pour seul signal, le statut de sortie dédié au fail-stop (`EXIT_FAIL_STOP`) (« Signalement du fail-stop », ci-dessous) [D, 28 octobre 2026].
     - L’annulation repose alors sur la destruction de la connexion (close), ou sur l’absence d’enregistrement de validation après l’arrêt (wal, corrupt).
     - C’est une déduction sous C2, avec une hypothèse [H] sur `sqlite3_close_v2()` dans CPython.
  4. B n’est relâchée qu’après une annulation établie (point 1) ou déduite (point 2), puis `close()`. Dans le cas du point 3, elle n’est libérée que par la fin du processus [H : libération par le noyau, §5.5.5, L.1]. **Précisé le 28 octobre 2026 [D] :** dans les deux premiers cas, W est relâché après B. Au point 1, le service peut d’abord tenter de retirer son marqueur, et relâche B puis W même si ce retrait échoue. Au point 2, il ne le retire pas. Au point 3, W n’est libéré, comme B, qu’à la fin du processus [H].
  5. Le refus est signalé par un code fixe, distinct d’un refus ordinaire, qui n’affirme pas l’absence d’effet [R ; codes : §10.2]. Ce code ne vaut que pour les points 1 et 2, où le processus continue. Au point 3, aucun code n’est émis : le processus se termine avec le statut de sortie dédié au fail-stop (`EXIT_FAIL_STOP`) [D, 28 octobre 2026] (« Signalement du fail-stop », ci-dessous).
  6. Avant toute nouvelle tentative sur ce nonce, l’état est constaté (ci-dessous). Si le constat montre une écriture de l’opération, c’est une incohérence. Elle relève des contrôles existants (V1, validation avant ancrage, §11.3), et son classement reste ouvert [O].
- **Sort du nonce.** Point 1 : `ISSUED`, établi après le `ROLLBACK` réussi [F] (transaction). Point 2 : `ISSUED` seulement déduit, sous C2 et sous la prémisse qu’aucun `COMMIT` n’a été exécuté [R] ; cet état n’est donc pas garanti par une catégorie de sortie (§10.2, « Déductions sous C2 », décidé le 29 octobre 2026 [D]). Non établi dans le cas du point 3 [O].

**Cas 3 : erreur du `COMMIT` sur le chemin de succès (étape 10). Les deux premières règles sont consignées le 27 octobre 2026 sur instruction du propriétaire [D].**
- **[D]** Ce n’est **pas un refus**.
- **[D]** Aucune nouvelle tentative automatique n’est lancée : ni du `COMMIT`, ni de l’`apply`.
- **Issue de la transaction.**
  - Elle peut être inconnue de l’appelant. L’atomicité garantit le tout ou rien, et non le moment où l’issue devient définitive. Après un `COMMIT` en erreur, la documentation ne dit ni quand ni si cette issue devient durable [O] (« Portée du constat », ci-dessous).
  - [F] (atomic, pragma) La transaction est atomique. L’effet, la confirmation, le compteur, l’entrée J-b, `c` le cas échéant, et `CONSUMED` sont validés ensemble ou pas du tout.
  - WAL avec `FULL` est ACID pour un `COMMIT` qui a réussi (pragma).
- **Règle rappelée, distincte de ce que sait l’appelant.**
  - L’opération n’est tenue pour effective que si son `COMMIT` est établi : le nonce est consommé si et seulement si l’effet est validé (§5.4). Après un `COMMIT` en erreur, aucun moyen décrit ne l’établit : ni `in_transaction`, ni `show`, ni une relecture. Le critère reste ouvert [O]. Pendant l’incertitude, le gel décidé s’applique (ci-dessous).
  - Une opération qui ouvre n’est de toute façon utilisable qu’après V1, son ancrage et E (§11.2).
  - Une fermeture prend effet au `COMMIT` local.
    - Le constat montre seulement si elle est visible. Après un `COMMIT` en erreur, il n’établit pas qu’elle est durable.
    - La conduite si une fermeture visible disparaît après une récupération reste ouverte [O].
- **Réponse.** Un code fixe « issue à constater », distinct du succès et du refus [R ; §10.2]. Il ne vaut que pour les chemins où le processus continue (points a et c ci-dessous). Au point b, qui se termine en fail-stop, aucun code n’est émis [D, 28 octobre 2026] (« Signalement du fail-stop », ci-dessous).
- **Résolution de la transaction et barrière B [R].**
  - Ces règles valent aussi pour l’échec du `COMMIT` final du cas 1.
  - **B n’est jamais relâchée tant que la transaction n’est pas résolue sur la connexion.** C’est l’application de la règle décidée : B est gardée jusqu’au `COMMIT` ou au `ROLLBACK` complet (§5.5.5, L.2 [D]).
  - **a) `in_transaction` reste vrai, et un `ROLLBACK` explicite réussit.**
    - La transaction est résolue par ce `ROLLBACK` [F] (transaction).
    - On en déduit que le `COMMIT` n’a pas validé la transaction sur cette connexion [R].
    - Qu’aucune écriture du `COMMIT` en erreur ne soit devenue persistante n’est documenté que pour le `SQLITE_BUSY` dû à un lecteur (cas 4). Dans les autres cas, ce point reste ouvert [O].
    - **Gel : non déclenché [D].** Au sens de la décision sur les transactions couvertes, ce `ROLLBACK` réussi établit le non-`COMMIT`. Le gel ne s’applique donc pas, sauf si une règle déjà décidée l’exige (« Issues visées », ci-dessous). La limite documentaire du point précédent reste signalée [O], sans déclencher le gel.
    - **Marqueur [D, 28 octobre 2026].** Le `ROLLBACK` complet ayant réussi, le service peut tenter de retirer son propre marqueur (« Mécanisme du marqueur », ci-dessous). La tentative précède la libération de B, puis celle de W, qui ont lieu même si le retrait échoue. Si le marqueur reste présent, il est résiduel et maintient le gel ; si sa suppression est visible mais non durable, cette suppression ne maintient pas, à elle seule, le gel pendant que le système tourne (les autres marqueurs résiduels, s’il y en a, continuent de le maintenir et de provoquer les refus prévus), et le marqueur peut réapparaître après une coupure ou un redémarrage (« Mécanisme du marqueur », ci-dessous). L’ordre de la tentative par rapport à `close()` reste ouvert [O].
    - Ensuite, `close()`, puis libération de B.
  - **b) `in_transaction` reste vrai, et le `ROLLBACK` échoue, ou bien l’état de la connexion ne peut pas être lu.**
    - La transaction n’est pas résolue, et B n’est pas relâchée.
    - Le processus ferme la connexion et se termine, sans exécuter d’autre instruction. Il ne retire pas le marqueur, qui maintient le gel jusqu’à son retrait par `root` [D] (« Mécanisme du marqueur », ci-dessous). Cette conduite fail-stop est conservée par la décision du 28 octobre 2026 [D]. Le processus n’émet aucun code de réponse ni message du protocole et se termine avec, pour seul signal, le statut de sortie dédié au fail-stop (`EXIT_FAIL_STOP`) (« Signalement du fail-stop », ci-dessous) [D, 28 octobre 2026].
    - B n’est libérée que par la fin du processus [H : libération par le noyau, §5.5.5, L.1]. Il en va de même pour W, dont la libération à la fin du processus reste une hypothèse à vérifier [H].
    - La résolution repose alors sur la destruction de la connexion ou sur la récupération (close, wal, corrupt) [H].
  - **c) `in_transaction` est faux juste après le `COMMIT` en erreur.**
    - Aucune transaction n’est plus active, mais elle a pu être validée comme annulée : **l’issue est indéterminée** [O].
    - Un `ROLLBACK` est alors sans objet.
    - Ensuite, `close()`, puis libération de B. Cette libération n’établit pas la condition 3 du §5.5.5, L.4 (ci-dessous).
    - **Marqueur [D, 28 octobre 2026].** Ni `COMMIT` confirmé ni `ROLLBACK` complet réussi : le service ne retire pas le marqueur, qui maintient le gel jusqu’à son retrait par `root` (« Mécanisme du marqueur », ci-dessous). **Précisé le 28 octobre 2026 [D] :** le service ne tente pas de retirer le marqueur. La transaction étant inactive sur la connexion, il relâche B puis W et laisse le marqueur en place jusqu’à la récupération et à la levée explicites par `root`.
  - Dans les trois cas, aucune nouvelle tentative automatique n’est lancée [D]. Aux points a et c, où le processus continue, le code fixe reste « issue à constater » ; au point b, qui se termine en fail-stop, aucun code n’est émis et seul le statut de sortie dédié (`EXIT_FAIL_STOP`) est produit [D, 28 octobre 2026]. Aux points b et c, le gel décidé s’applique. Au point a, il ne s’applique pas, sauf si une règle déjà décidée l’exige [D] (« Gel après une issue indéterminée », ci-dessous).
- **Barrière.** La condition 3 du §5.5.5, L.4, n’est pas établie dans les cas b et c. Dans le cas a, elle ne l’est que sous la réserve de durabilité indiquée [O].
- **Gel après une issue indéterminée — décidé par le propriétaire le 27 octobre 2026 [D].**
  - **Décision [D].** Après une erreur de `COMMIT` dont l’issue est indéterminée, le service refuse les opérations d’approbation jusqu’à une récupération et une vérification explicites.
  - **Portée décidée [D].** Pendant l’incertitude :
    - aucune nouvelle autorisation d’approbation n’est délivrée : E refuse (§11.2) ;
    - aucune opération qui ouvre n’est acceptée, qu’il s’agisse des opérations 1 à 5 du §11.2, y compris la réouverture de l’interrupteur et la reprise de suspension ;
    - la lecture seule à des fins de constat reste possible (« Constat de l’état », ci-dessous).
  - **Issues visées.**
    - Après une erreur de `COMMIT`, trois situations se distinguent, pour V0 comme pour E. Ce sont les points a à c de la résolution, ci-dessus. Elles valent au cas 3 comme pour l’échec du `COMMIT` final du cas 1.
      - **`ROLLBACK` réussi, non-`COMMIT` établi (point a).** La transaction était encore active, et le `ROLLBACK` la résout [F]. Le gel n’est pas déclenché [D], sauf si une règle déjà décidée l’exige. Il faut pour cela que le retrait normal du marqueur suive ; sinon, le gel conservateur s’applique [D] (« Gel conservateur », ci-dessous). La limite documentaire sur l’état persistant reste signalée [O], sans déclencher le gel.
      - **`ROLLBACK` échoué, ou état de la connexion illisible : transaction non résolue (point b).** L’issue est indéterminée, et le gel s’applique [D].
      - **Transaction inactive juste après l’erreur de `COMMIT` (point c).** L’issue est indéterminée, et le gel s’applique [D].
    - Au sens de ce paragraphe, l’issue est donc indéterminée aux points b et c seulement.
    - Un arrêt brutal pendant le `COMMIT` ne renvoie pas d’erreur à l’appelant. Il relève du gel conservateur [D] (« Gel conservateur », ci-dessous), et son issue reste à constater [O].
    - L’application du gel à une erreur du `COMMIT` de la validation avant ancrage ou de D-9 reste à préciser [O].
  - **Transactions couvertes — décidé par le propriétaire le 27 octobre 2026 [D].**
    - Le gel couvre **toute transaction V0**, qu’elle consigne une opération qui ouvre (opérations 1 à 5 du §11.2) ou une opération signée qui ferme (« Fermeture signée dont le `COMMIT` a une issue indéterminée », ci-dessous).
    - Il couvre aussi **la transaction d’E qui enregistre une autorisation** (« Extension au `COMMIT` d’E », ci-dessous).
    - Il ne vise que l’issue indéterminée d’un `COMMIT` (« Issues visées », ci-dessus). Un échec dont le non-`COMMIT` est établi par un `ROLLBACK` réussi ne le déclenche pas, sauf si une règle déjà décidée l’exige. Le gel conservateur, décidé ensuite, est une telle règle : il s’y ajoute pour tout marqueur resté présent (« Gel conservateur », ci-dessous).
    - Cette décision fixe les catégories de transactions couvertes, et non le mécanisme qui arme ou conserve le gel. Ce mécanisme a été fixé le 28 octobre 2026 [D] (« Mécanisme du marqueur », ci-dessous) ; ses détails restent ouverts [O].
  - **Extension au `COMMIT` d’E — décidée par le propriétaire le 27 octobre 2026 [D]** (§11.2 ; §5.5.5, L.2, étape E6).
    - E enregistre localement sa décision d’autorisation, puis exécute son `COMMIT` (E6). Si ce `COMMIT` a une issue indéterminée, E ne délivre aucune nouvelle autorisation, et le même gel s’applique jusqu’à une récupération et une vérification explicites [D].
    - Les règles déjà décidées du gel s’appliquent sans changement : aucune opération qui ouvre n’est acceptée, et la lecture seule à des fins de constat reste possible [D].
    - Un échec dont le non-`COMMIT` est établi par un `ROLLBACK` réussi ne déclenche pas ce gel, sauf si une règle déjà décidée l’exige [D].
    - [R] E suit le même ordre de prise que le service (§5.5.5, L.2 et L.8, point 2 [D]). Les critères de résolution des points a à c ci-dessus se transposent à sa transaction : les points b et c correspondent à l’issue indéterminée. Un `ROLLBACK` réussi établit le non-`COMMIT`, qu’aucun `COMMIT` n’ait été exécuté ou que le `ROLLBACK` suive un `COMMIT` en erreur alors que la transaction était encore active (point a). Dans les deux cas, le gel n’est pas déclenché [D], comme pour V0 (« Issues visées », ci-dessus).
    - [R] La remise du résultat suit le `COMMIT` (E7). La décision dont le `COMMIT` est en erreur n’est donc pas remise comme une autorisation.
    - Un arrêt brutal pendant le `COMMIT` d’E relève du gel conservateur [D], comme pour V0 (« Gel conservateur », ci-dessous).
    - Ce que la décision enregistrée gouverne localement, et sa revalidation avant usage, restent ouverts [O] (§5.5.5, L.8, point 5).
    - **Mécanisme pour E — fixé le 28 octobre 2026 [D]** (« Mécanisme du marqueur », ci-dessous). La transaction d’E a son propre marqueur. Il est créé avant ses écritures, donc avant l’enregistrement de la décision (E6), et le service ne le retire qu’après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi.
      - [R] Un mécanisme armé seulement par V0 n’aurait pas couvert E : un processus qui suit E en erreur n’aurait vu aucun gel. Le marqueur propre à la transaction d’E répond à ce point.
      - **Moment de sa création — décidé le 28 octobre 2026 [D]** (§5.5.5, L.2) : après `BEGIN IMMEDIATE`, avant toute écriture de la transaction, donc avant E3 à E6. E prend auparavant W, avant G, et examine sous W les marqueurs existants.
      - Restent ouverts [O] : les détails communs à tous les marqueurs (« Mécanisme du marqueur », ci-dessous).
  - **Gel conservateur — décidé par le propriétaire le 27 octobre 2026 [D].** Il vaut pour toute transaction couverte (« Transactions couvertes », ci-dessus). Ici, « marqueur » désigne le marqueur du gel : un fichier persistant hors de SQLite, propre à chaque transaction couverte, fixé le 28 octobre 2026 (« Mécanisme du marqueur », ci-dessous). Il est distinct du marqueur de refus en base du §5.5.5 (option 3 ; I.5).
    - Tout marqueur encore présent après l’arrêt d’un processus, ou après une issue non résolue, maintient le gel, y compris après un redémarrage.
    - Cela comprend un arrêt avant le `COMMIT`, un arrêt pendant le `COMMIT`, et un arrêt après un `COMMIT` réussi mais avant le retrait du marqueur.
    - Aucun nettoyage automatique ne retire un marqueur : ni au démarrage, ni après un délai, ni d’après la seule visibilité de l’état SQLite, ni d’après une simple déduction sur l’issue.
    - Le gel ne prend fin qu’après une récupération, une vérification et une levée explicites.
    - **Règle préservée [D].** Un `ROLLBACK` complet réussi et établi, suivi du retrait normal du marqueur, ne déclenche pas le gel. Si le processus s’arrête avant ce retrait, le gel conservateur s’applique.
    - **Conséquences dans ce document**, sans changement des autres décisions :
      - au point a, le `ROLLBACK` réussi n’évite le gel que si le retrait normal suit (« Issues visées », ci-dessus) ;
      - une annulation seulement déduite, après un `ROLLBACK` en échec alors que `in_transaction` est faux, ne permet pas le retrait. Cela vise le cas 1 (« Échec de la transition conditionnelle ») et le cas 2, point 2. Le gel conservateur s’applique, et les règles du nonce sont inchangées ;
      - au cas 2, point 3, le processus se termine sans retrait : le gel conservateur s’applique ;
      - un arrêt brutal pendant le `COMMIT`, de V0 comme d’E, relève de ce gel. Son issue reste à constater [O] ;
      - pour une opération qui ouvre, une nouvelle présentation du même énoncé après un arrêt n’est acceptée qu’après la levée. Les règles du nonce sont inchangées, et le sort de cette tentative après la levée reste ouvert [O] ;
      - une transaction couverte interrompue par l’arrêt forcé de `root` (§5.5.5, L.5) laisse ce gel si son marqueur était présent, et la relance du service ne le lève pas. L’articulation avec la disponibilité de D-9 au redémarrage (L.5 [D]) et avec sa disponibilité pendant le gel ([O], « D-9 », ci-dessous) reste à préciser [O].
    - Pour que cette règle ait un objet, le marqueur est créé avant les écritures de la transaction [D] (« Mécanisme du marqueur », ci-dessous). Un arrêt survenu avant sa création ne laisse aucun marqueur ; la transaction n’a alors rien écrit. Le moment de la création a été fixé le 28 octobre 2026 [D] : après le `SAVEPOINT` pour V0, après `BEGIN IMMEDIATE` pour E, et dans les deux cas avant toute écriture (« Mécanisme du marqueur », ci-dessous).
    - **Restent ouverts [O] :**
      - les détails du mécanisme (« Mécanisme du marqueur », ci-dessous) ;
      - la procédure détaillée de récupération, la vérification, et les critères détaillés de la levée, y compris ce qu’elle exige au-delà du retrait des marqueurs résiduels par `root` ;
      - la portée de la remise par E (E7) d’une décision enregistrée avant l’incertitude.
    - La protection contre un compte de service compromis, qui peut effacer ou ignorer un marqueur qu’il peut écrire, n’est plus un point ouvert : c’est une limite décidée (« Mécanisme du marqueur », ci-dessous).
  - **Mécanisme du marqueur — décidé par le propriétaire le 28 octobre 2026 [D].** Il met en œuvre le gel conservateur pour toute transaction couverte (« Transactions couvertes », ci-dessus), sans en changer les règles.
    - **Un marqueur par transaction.** Chaque transaction couverte, V0 comme E, a son propre marqueur, distinct de celui de toute autre transaction, sous forme de fichier persistant hors de SQLite.
    - **Création.** Le marqueur est créé avant les écritures de la transaction.
    - **Verrou W et ordre de prise — décidés par le propriétaire le 28 octobre 2026 [D]** (§5.5.5, L.2) :
      - W est un verrou exclusif qui sérialise les transactions couvertes, V0 et E. Elles le prennent avant G ;
      - sous W, elles examinent les marqueurs existants. Pour E et les opérations qui ouvrent, un marqueur résiduel entraîne un refus sans écriture. La qualification du refus et le sort du nonce restent ouverts [O]. La conduite d’une opération signée qui ferme dans ce cas relève des fermetures pendant le gel, non tranchées [O] ;
      - après cette vérification, l’ordre existant reste intact : G en partagé, B en partagé, relâchement de G, puis `BEGIN IMMEDIATE` ;
      - V0 prend ensuite le `SAVEPOINT`, puis crée son marqueur avant toute écriture de la transaction, donc avant les étapes S4 et S5 de L.2 et toute consignation de `c`. E crée le sien après `BEGIN IMMEDIATE`, avant toute écriture, donc avant E3 à E6 ;
      - W est gardé pendant la transaction, jusqu’à sa résolution sur la connexion. Après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi, le service peut tenter de retirer son marqueur avant de relâcher les verrous ;
      - une fois la transaction résolue, le service relâche B, puis W. Si le retrait échoue et que le marqueur reste présent, ou s’il n’est pas tenté, le marqueur résiduel maintient le gel. Une suppression visible dont seule la synchronisation du répertoire échoue ou reste incertaine ne maintient pas, à elle seule, le gel pendant que le système tourne (les autres marqueurs résiduels, s’il y en a, continuent de le maintenir et de provoquer les refus prévus) ; le marqueur peut réapparaître après une coupure ou un redémarrage. Si l’issue du `COMMIT` est indéterminée, le service ne tente pas le retrait ; le marqueur reste en place et maintient le gel jusqu’à une levée explicite par `root` (« Rôle de W et fin de la transaction », ci-dessous).
    - **Rôle de W et fin de la transaction — décidés par le propriétaire le 28 octobre 2026 [D] :**
      - W est un verrou de sérialisation, pas le support persistant du gel : le marqueur restant porte le gel ;
      - après que la transaction SQLite est résolue sur la connexion, le service relâche B puis W, même si le marqueur n’a pas pu être retiré ;
      - après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi, le service peut tenter de retirer son propre marqueur. Si ce retrait échoue, il ne prétend pas que le gel est levé et ne retire aucun autre marqueur ; tout marqueur résiduel maintient le gel, sans nettoyage automatique ;
      - si l’issue du `COMMIT` est indéterminée, le service ne tente pas le retrait. Une fois la transaction inactive sur la connexion, il relâche B puis W et laisse le marqueur en place jusqu’à la récupération et à la levée explicites par `root` ;
      - si la transaction reste non résolue, la conduite fail-stop déjà décrite est conservée : le processus se termine sans autre instruction (cas 2, point 3 ; cas 3, point b), sans code ni message du protocole, avec pour seul signal `EXIT_FAIL_STOP` (« Signalement du fail-stop », ci-dessous). La libération de B et de W à la fin du processus reste une hypothèse [H] ;
      - restent inchangés : un `ROLLBACK TO SAVEPOINT` seul n’autorise pas le retrait ; seul `root` retire un marqueur résiduel, après une récupération et une vérification explicites ; E et les opérations qui ouvrent refusent sous W en présence d’un marqueur résiduel.
    - **Support de W, emplacement des marqueurs et restauration — décidés par le propriétaire le 28 octobre 2026 [D] :**
      - W est un fichier stable détenu par `root`, jamais supprimé ni remplacé, que le service peut ouvrir et prendre en verrou exclusif sans pouvoir le modifier. Cela reprend le rôle exclusif de W décidé ci-dessus ;
      - les marqueurs sont placés dans un sous-répertoire persistant du compte de service, dans l’arborescence des données, hors des arborescences `root` et du code. Un système de fichiers local est une exigence de conception ; le système de fichiers réellement utilisé sur le serveur reste à vérifier [H] ;
      - une restauration n’est jamais, à elle seule, une levée explicite du gel. La façon d’appliquer cette règle après une restauration reste ouverte [O] ;
      - restent inchangés : la portée de W, limitée à V0 et E, et L.4, selon lequel `root` ne prend pas W. La prise de W ne garantit pas la cohérence d’une sauvegarde : d’autres écrivains, dont D-9 et la validation avant ancrage, écrivent dans la base sans W.
    - **Retrait visible non durable et échec de synchronisation à la création — décidés par le propriétaire le 28 octobre 2026 [D] :**
      - après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi, si la suppression du marqueur est visible mais que la synchronisation du répertoire échoue ou a une issue incertaine : l’issue SQLite reste établie ; l’absence visible du marqueur fait que le contrôle sous W peut laisser poursuivre les transactions couvertes pendant que le système reste en marche, sauf si d’autres marqueurs résiduels sont présents : ceux-ci continuent de maintenir le gel et de provoquer les refus prévus, cette suppression ne le maintenant pas à elle seule ; le service signale que la durabilité du retrait n’est pas établie et ne présente pas ce constat comme une levée explicite par `root` ; après une coupure ou un redémarrage, le marqueur peut réapparaître et provoquer un gel conservateur ; ce cas ne crée pas, à lui seul, un nouveau déclencheur de gel pendant que le système tourne ;
      - si la synchronisation du marqueur ou de son répertoire échoue avant toute écriture SQLite, la transaction n’exécute aucune écriture de base. Elle suit la conduite de refus déjà prévue et ne supprime aucun marqueur appartenant à une autre transaction. Son propre marqueur relève de la règle de retrait déjà décidée : après un `ROLLBACK` complet réussi, le service peut tenter de le retirer. **Précisé le 28 octobre 2026 [D] :** la transaction se termine alors par un `ROLLBACK` complet avant de poursuivre. Si ce `ROLLBACK` échoue ou si son issue ne peut pas être établie, aucun `COMMIT` ne suit et le service applique la règle fail-stop propre à ce cas, plus stricte que la règle générale du §5.5.1, cas 2, point 2 : tout échec de ce `ROLLBACK`, même si `in_transaction` est faux et que l’annulation pourrait être déduite selon cette règle générale, met fin au processus sans autre instruction, comme au cas 2, point 3. Le marqueur est laissé en place s’il est présent, et la règle générale du point 2 reste applicable aux autres erreurs. Le refus et le sort du nonce sont fixés au sous-bloc suivant [D] ;
      - restent inchangés : la règle applicable à un `COMMIT` d’issue indéterminée, et la levée explicite des marqueurs résiduels par `root`.
    - **Refus et nonce après échec de synchronisation — décidés par le propriétaire le 28 octobre 2026 [D].** Pour toute transaction couverte, V0 comme E, si la synchronisation du marqueur ou de son répertoire échoue avant toute écriture SQLite :
      - l’opération est refusée comme échec technique fermé ; aucun effet ni aucune écriture SQLite ne sont produits ;
      - pour V0, le nonce n’est ni consommé, ni passé à `FAILED`, ni renouvelé. S’il est encore `ISSUED`, il le reste jusqu’à son expiration normale (« Sort du nonce selon l’issue », ci-dessus) ;
      - ce refus n’incrémente pas le compteur des tentatives d’autorisation. **Précisé le même jour [D] :** il n’incrémente pas non plus le compteur borné par opération et par classe de refus du §10.3 ; les autres catégories de refus et leurs compteurs sont inchangés ;
      - une télémétrie diagnostique éventuelle reste facultative et hors du protocole d’autorisation ; elle ne doit retarder ni le `ROLLBACK` ni le fail-stop spécial, et son mécanisme n’est pas conçu ici ;
      - la fin par `ROLLBACK` complet, le retrait possible de son propre marqueur et le fail-stop spécial suivent le sous-bloc précédent ; aucun marqueur d’une autre transaction n’est retiré ;
      - aucune nouvelle tentative automatique n’est lancée. Après récupération du stockage, une nouvelle présentation repasse les contrôles normaux et n’est possible avec le même énoncé signé que si le nonce est encore valide ;
      - cet échec, à lui seul, ne crée pas de nouveau déclencheur de gel général ; les règles sur les marqueurs résiduels et le gel conservateur restent applicables ;
      - **code du refus — décidé le même jour [D] :** un code technique fixe, défini par les garanties ci-dessus et commun à V0 et E, émis seulement après un `ROLLBACK` complet réussi. Il est distinct des codes de rejet signés du §6.3 et n’est ni signé, ni écrit en base, ni inscrit dans J-b. Il est accompagné d’un qualificatif secondaire fixe qui indique seulement le sort du marqueur de cette transaction ; aucune valeur ne signifie que le gel global est levé. En cas de fail-stop, aucun code de refus ou de réponse ni message du protocole n’est émis : le processus se termine sans autre instruction, avec pour seul signal le statut de sortie dédié au fail-stop (`EXIT_FAIL_STOP`) (§10.2 ; « Signalement du fail-stop », ci-dessous) ; l’absence observée du marqueur n’est alors présentée ni comme une preuve de retrait durable ni comme une levée du gel ;
      - **valeurs du qualificatif — décidées le même jour [D] (option Q-A, lecture (b)) :** trois valeurs fermées, qui décrivent seulement l’état observable du marqueur de cette transaction. (1) **Retrait visible, durabilité non établie :** le fichier a été supprimé du répertoire visible ; le retrait n’est jamais déclaré durable dans ce cas, même si une synchronisation ultérieure réussit, et la valeur ne prétend pas que la suppression est certainement non durable. (2) **Marqueur confirmé présent :** retrait non tenté, ou retrait échoué dont la présence est confirmée. (3) **État du marqueur non établi :** notamment identité différente, fichier absent avant la tentative, répertoire illisible, ou impossibilité de vérifier l’état ; rien n’est alors supprimé. Il n’existe pas de valeur « retrait durable » pour ce cas. Aucune valeur n’est nommée ni décrite comme « gel levé », « système ouvert » ou équivalent ; le qualificatif ne prouve pas l’absence d’autres marqueurs et ne constitue jamais une levée du gel global ;
      - restent ouverts [O] : le nom exact du code, sa place dans une liste distincte de réponses techniques (§10.2), les noms exacts des trois valeurs du qualificatif, la tentative systématique ou non du retrait, la conduite lorsque l’état du marqueur n’est pas établi, la valeur numérique de `EXIT_FAIL_STOP`, non fixée à ce stade [D], la liste complète des statuts de sortie de la CLI au-delà du cadre symbolique de `apply` (§10.2), le classement des chemins de `apply` non encore définis, la transmission du statut et la vérification des chaînes sur le serveur, la conduite face à un statut inconnu ou au statut 255, la politique de redémarrage du processus par le superviseur, que le choix du numéro ne tranche pas, et l’observation côté E (« Signalement du fail-stop », ci-dessous), la conduite de récupération lorsque le marqueur est absent ou que sa présence ne peut être établie, et la qualification détaillée au-delà de l’« échec technique fermé ». L’articulation avec le compteur borné est fixée (ci-dessus).
    - **Hypothèse à vérifier [H].** La libération de W à la fin du processus, y compris à sa mort, comme pour B et G (§5.5.5, L.1). Lorsque le processus se termine sans relâcher W (cas 2, point 3 ; cas 3, point b), W n’est libéré que de cette façon.
    - **Propriété attendue [R], entre processus qui respectent le protocole.** Aucune transaction couverte ne s’intercale entre l’examen des marqueurs par une autre et la création du marqueur de celle-ci. Aucune ne voit sous W le marqueur d’une transaction couverte en cours, puisque celle-ci tient W jusqu’à la résolution de sa transaction et, le cas échéant, jusqu’à la tentative de retrait. Un marqueur laissé en place au relâchement de W, faute de retrait autorisé ou réussi, maintient le gel [D]. Cette propriété dépend du mécanisme de W et de l’hypothèse ci-dessus. Elle ne vaut ni pour les transactions non couvertes, ni face à un compte de service compromis, qui peut retenir ou ignorer W. L’identification des marqueurs résiduels, notamment hors W et par la procédure de récupération, reste ouverte [O].
    - **Retrait par le service.** Le service ne retire le marqueur qu’après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi.
    - **Retour au `SAVEPOINT`.** Un `ROLLBACK TO SAVEPOINT` seul ne permet jamais de retirer le marqueur (cas 1).
    - **Marqueur restant.** Un marqueur restant après un arrêt ou une issue indéterminée maintient le gel. Aucun nettoyage automatique ne le retire au démarrage (« Gel conservateur », ci-dessus).
    - **Marqueur résiduel.** `root` ne le retire qu’après une récupération et une vérification explicites.
    - **Limite [D].** La limite déjà établie s’applique (§5.5.5, J.6 ; L.4, « Limites ») : ce mécanisme protège contre les erreurs de processus et de stockage, pas contre un compte de service compromis, qui peut omettre, effacer ou ignorer un marqueur.
    - **Ce que le système de fichiers ne garantit pas.** Le caractère distinct des marqueurs est une règle du protocole, que respectent les processus intègres. Rien, dans ce document, n’établit que le système de fichiers empêche un processus du compte de service de supprimer le marqueur d’un autre processus, et la protection décrite ne s’appuie sur aucune garantie de ce type [R]. W n’y change rien : il ordonne les processus qui le respectent, sans empêcher un processus du compte de service de supprimer un marqueur.
    - **Conséquences dans ce document [R]**, tirées des règles ci-dessus sans les étendre :
      - cas 1 : après un retour au `SAVEPOINT` réussi, le marqueur reste présent jusqu’au `COMMIT` confirmé de la transition vers `FAILED`, ou jusqu’à un `ROLLBACK` complet réussi ;
      - cas 1, « Échec de la transition conditionnelle », et cas 2, point 2 : une annulation seulement déduite n’est pas un `ROLLBACK` complet réussi ; le marqueur reste, et le gel conservateur s’applique (ci-dessus). La transaction n’étant plus active, B puis W sont relâchés [D, 28 octobre 2026]. Cela ne vaut pas pour l’échec du `ROLLBACK` qui suit un échec de synchronisation du marqueur, régi par un fail-stop plus strict (ci-dessus) ;
      - cas 2, point 1, et cas 3, point a : le `ROLLBACK` complet réussi permet au service de retirer le marqueur ;
      - cas 2, point 3, et cas 3, points b et c : ni `COMMIT` confirmé ni `ROLLBACK` complet réussi ; le marqueur reste, et le gel est maintenu jusqu’à son retrait par `root`. Au point c, B puis W sont relâchés ; aux deux autres, le processus se termine [D ; H sur la libération] ;
      - un `COMMIT` en erreur n’est pas un `COMMIT` confirmé, même si le constat montre ensuite l’état validé : la seule visibilité de l’état SQLite ne permet pas le retrait (« Gel conservateur », ci-dessus) ;
      - une suppression visible dont la synchronisation du répertoire échoue ou reste incertaine ne laisse plus ce marqueur dans le système en marche et ne maintient pas, à elle seule, le gel : le contrôle sous W peut laisser poursuivre, sauf si d’autres marqueurs résiduels sont présents, qui continuent de maintenir le gel et de provoquer les refus prévus ; le service signale que la durabilité du retrait n’est pas établie, et le marqueur peut réapparaître après une coupure ou un redémarrage, ce qui provoque alors un gel conservateur [D, 28 octobre 2026] ;
      - un échec du retrait qui laisse le marqueur présent : le service relâche B puis W, ne prétend pas que le gel est levé et ne retire aucun autre marqueur ; le marqueur résiduel maintient le gel jusqu’à la levée par `root` [D, 28 octobre 2026] ;
      - un arrêt avant la création du marqueur n’en laisse aucun ; la transaction n’a alors rien écrit ;
      - la levée du gel suppose le retrait de tout marqueur résiduel par `root`. Ce qu’elle exige au-delà reste ouvert [O].
    - **Restent à concevoir [O]**, sans être fixés ici :
      - l’emplacement exact des marqueurs, leur catégorie étant fixée [D] ; leur nommage et leur contenu, notamment l’identification de la transaction ;
      - leurs modes exacts de permission, leur groupe éventuel, et leur compatibilité avec T-3 et la disposition des répertoires (§9.2) ;
      - la méthode de sauvegarde et la procédure de restauration, y compris l’application du principe selon lequel une restauration ne vaut pas levée du gel ;
      - les moyens de leur persistance effective, notamment la synchronisation du fichier et de son répertoire [H] ;
      - le mécanisme de W, son équité, ses délais, l’emplacement et les modes exacts de son fichier ; son support (fichier stable détenu par `root`), le moment de la création et l’examen sous W étant fixés depuis le 28 octobre 2026 [D] ;
      - la conduite si la création échoue. Par la règle de création, la transaction n’écrit rien sans son marqueur, et un échec de synchronisation du marqueur ou de son répertoire interdit toute écriture de base [D, 28 octobre 2026] ; la transaction se termine alors par un `ROLLBACK` complet, et un échec ou une issue non établie de ce `ROLLBACK` mène au fail-stop propre à ce cas, même si `in_transaction` est faux, plus strict que la règle générale du cas 2, point 2 [D, 28 octobre 2026] ; le refus, qualifié d’échec technique fermé, et le sort du nonce sont fixés depuis le même jour [D] ; la nature de son code est fixée [D] ; les trois valeurs de son qualificatif sont fixées [D] ; son nom exact et les noms de ces valeurs restent ouverts ;
      - les détails techniques du retrait et de sa durabilité. La conduite après un échec du retrait, le cas d’une suppression visible non durable, et le relâchement de W lorsque le marqueur ne peut pas être retiré, sont fixés depuis le 28 octobre 2026 [D] ;
      - la conduite si l’état ou la présence du marqueur ne peut pas être établi, par exemple si l’issue de son retrait est inconnue, hors le cas d’une suppression visible dont seule la synchronisation du répertoire échoue ou reste incertaine, réglé depuis le 28 octobre 2026 [D] ;
      - le code et le comptage du refus pour marqueur résiduel ;
      - l’ordre du retrait par rapport à `close()`, celui par rapport à B et W étant fixé ;
      - l’identification des marqueurs résiduels, hors W et par la procédure de récupération ;
      - l’opération `root` qui retire un marqueur résiduel, son protocole, sa coordination avec W et tout éventuel assistant ;
      - la procédure détaillée de récupération et de vérification, et les critères détaillés de la levée ;
      - l’usage d’un marqueur pour les transactions de la validation avant ancrage et de D-9, auxquelles l’application du gel reste à préciser (« Issues visées », ci-dessus).
  - **Ce que le gel ne change pas [D].** Restent inchangés :
    - l’option (a), sans réécriture de `FAILED` dans une transaction séparée ;
    - les règles de nonce : 1a, 1b, étapes 2 à 8, échecs propres à γ1 ;
    - S4, dont la définition et la conduite restent celles du §11.3 ;
    - la barrière B et l’ordre de prise ;
    - la portée de D-9.

    Le mécanisme du marqueur et le verrou W, décidés le 28 octobre 2026, ne modifient aucun de ces points, ni les décisions de L.5 (§5.5.5). W s’ajoute avant G, sans changer l’ordre G, B, `BEGIN IMMEDIATE`.
  - **Points non tranchés par la décision [O].**
    - Le sort, pendant le gel, des opérations signées qui ferment, de la validation avant ancrage et de l’ancrage.
    - La disponibilité de D-9 pendant le gel, sa portée restant inchangée (« D-9 », ci-dessous).
    - La qualification et le code du refus d’une opération qui ouvre pour cause de gel, et le sort du nonce qu’elle vise. [R] Ce refus n’écrit rien, puisque c’est la base qui est en cause. Pour un marqueur résiduel constaté sous W, le refus est sans écriture [D, 28 octobre 2026].
    - Le sort d’une nouvelle tentative sur le même nonce ou le même énoncé après la levée du gel. Les règles du nonce ne sont pas modifiées.
  - **D-9.**
    - **Portée : inchangée [D].** Le gel ne modifie pas la portée décidée de D-9, limitée à la fermeture de l’interrupteur (§7.0).
    - **Disponibilité pendant le gel : non décidée [O].** Rien ne fixe si D-9 reste utilisable pendant le gel qui suit un `COMMIT` d’issue indéterminée. Les précisions décidées sur sa disponibilité visent d’autres situations :
      - l’arrêt forcé par la procédure `root` (§5.5.5, L.5) ;
      - le refus par V0 d’une opération signée qui ferme (en-tête ; §3, ligne du 26 octobre ; §7.0) ;
      - l’impossibilité ou la divergence détectée par la barrière γ1 (§5.5.5, I, J et K.3).

      Ces formulations disent que D-9 « reste disponible » dans ces situations. Elles ne décident pas de sa disponibilité pendant le gel.
    - Elle écrit dans la même base. La panne à l’origine de l’incertitude peut donc aussi la faire échouer, et D-9 n’est pas une solution garantie à cette panne [R].
    - Une erreur de son propre `COMMIT` relèverait de la même incertitude [O].
  - **Fermeture signée dont le `COMMIT` a une issue indéterminée.** Sa transaction V0 est couverte par le gel (« Transactions couvertes », ci-dessus) [D].
    - Pendant le gel, aucune autorisation ni aucune opération qui ouvre ne peut s’appuyer sur l’absence de cette fermeture, tant que le gel est effectivement tenu (ci-dessous).
    - Après la levée du gel, l’état de la fermeture est celui que montre le constat, sans preuve de durabilité [O].
  - **Mise en œuvre : mécanisme fixé le 28 octobre 2026 [D], détails non établis [O].**
    - Le processus qui reçoit l’erreur en a connaissance.
    - Il ne peut pas enregistrer cette incertitude de façon fiable dans SQLite : c’est précisément la base qui est en erreur, et une écriture du gel aurait elle-même une issue incertaine [R]. Le marqueur, fichier hors de SQLite créé avant les écritures, porte le gel sans écriture dans la base en erreur [D] (« Mécanisme du marqueur », ci-dessus).
    - Au point b, ce processus se termine. Sa connaissance de l’incertitude disparaît avec lui, mais son marqueur reste et maintient le gel [D].
    - Restent ouverts [O] :
      - la persistance effective du marqueur ;
      - l’identification des marqueurs résiduels. Leur examen par les autres transactions couvertes, sous W, a été fixé le 28 octobre 2026 [D] ;
      - son maintien effectif après un redémarrage, que le gel conservateur exige [D], selon les moyens de persistance retenus ;
      - les critères de récupération ;
      - la vérification qui permet de lever le gel. Le retrait d’un marqueur résiduel revient à `root` [D].
    - Tant que ces détails ne sont pas établis, le brouillon ne sait pas encore démontrer que la règle décidée tient hors du processus qui a constaté l’erreur [R].
    - Le rôle de `root` décidé se limite au retrait d’un marqueur résiduel, après récupération et vérification [D]. Aucun autre mécanisme `root` n’est retenu pour le gel.
    - Le constat de l’état ne lève pas, à lui seul, le gel, et ne permet pas le retrait d’un marqueur.
- **Arrêt brutal pendant le `COMMIT`.** L’issue est à constater de la même façon (§5.5.5, L.7). Le gel conservateur s’applique [D] (« Gel conservateur », ci-dessus).

**Signalement du fail-stop — décidé par le propriétaire le 28 octobre 2026 [D] (option F2), précisé le même jour (option T1, « statut de sortie seul »).**
- **Chemins visés :** cas 2, point 3 ; cas 3, point b ; fail-stop spécial après échec de synchronisation du marqueur (cas 3, « Mécanisme du marqueur »).
- Sur ces chemins, le processus n’émet aucun code de refus ni message de réponse du protocole. Il se termine avec un statut de sortie dédié, unique et commun à ces chemins, distinct des statuts de succès et de refus.
- Ce statut signifie uniquement que le processus s’est arrêté en fail-stop et que l’issue n’est pas établie. Il ne prétend rien sur l’effet ni sur l’état du nonce.
- **Nom symbolique — décidé le même jour [D] :** ce statut est `EXIT_FAIL_STOP`, statut de sortie symbolique unique, commun à tous les chemins qui se terminent en fail-stop. Il indique seulement que le processus s’est terminé en fail-stop et que l’issue n’est pas établie ; il ne dit rien sur l’effet ni sur l’état du nonce.
- **Valeur numérique — non fixée, décidé le même jour [D] :** le nom symbolique `EXIT_FAIL_STOP` reste fixé ; sa valeur numérique n’est pas fixée à ce stade. Le choix numérique sera repris après la définition de la liste des statuts de sortie de la CLI et l’examen des chaînes concernées (CLI, sudo, SSH et superviseur). Aucune plage numérique n’est adoptée comme décision.
- Ce statut de sortie n’est pas un code de réponse technique du §10.2, ni un code de refus. Les codes [R] prévus au cas 2, point 5, et au cas 3 (« issue à constater ») ne s’appliquent qu’aux chemins où le processus continue.
- **Seul signal du protocole — décidé le même jour [D] (option T1) :** sur ces chemins, aucun code de réponse ni message du protocole n’est émis ; le seul signal produit par le processus au titre du protocole est `EXIT_FAIL_STOP`. Aucun message applicatif n’est écrit sur stdout ni sur stderr lors du fail-stop. Une télémétrie diagnostique facultative, hors protocole et sans retard du fail-stop, reste soumise aux règles déjà établies (« Mécanisme du marqueur », ci-dessus ; §10.2).
- Un marqueur résiduel, lorsqu’il est présent, maintient le gel selon les règles décidées. Dans le fail-stop spécial, l’absence observée du marqueur n’est présentée ni comme une preuve de retrait durable ni comme une levée du gel. **Précisé le même jour [D] (option T1) :** le marqueur n’est pas l’unique signal qui fait toujours foi ; après un échec de synchronisation du marqueur, son absence visible ne prouve ni que son retrait est durable ni que le gel est levé.
- **Restent ouverts [O] :** la valeur numérique de `EXIT_FAIL_STOP` ; la liste complète des statuts de sortie de la CLI au-delà du cadre symbolique de `apply` (§10.2) ; le classement des chemins de `apply` non encore définis ; la transmission du statut par la CLI, sudo, SSH ou le superviseur, et la vérification de ces chaînes sur le serveur ; la conduite face à un statut inconnu ou au statut 255 ; la politique de redémarrage du processus par le superviseur, que le choix du numéro ne tranche pas ; l’observation côté E ; la conduite de récupération lorsque le marqueur est absent ou que sa présence ne peut être établie.

**Constat de l’état avant toute nouvelle tentative (cas 1 à 3) [R].**
1. Ouvrir une nouvelle connexion, après la fermeture de la connexion en erreur ou la fin du processus, avec les contrôles de configuration habituels.
2. Dans une seule transaction de lecture, lire l’état du nonce, la confirmation qu’il désigne, l’entrée J-b correspondante et l’effet. `show` restitue le résultat. Ni `show` ni la relecture n’établit à lui seul la durabilité (point 4).
3. Interpréter :
   - `CONSUMED`, avec une confirmation et une entrée concordantes : la validation est visible ;
   - `FAILED`, sans confirmation : le refus est visible ;
   - `ISSUED`, sans confirmation : aucune écriture de cette tentative n’est visible ;
   - tout autre état : incohérence, qui relève des contrôles existants (V1, §11.3) ; son classement reste ouvert [O].
4. **Portée du constat.**
   - [F] (wal) Il établit l’état visible au début de la lecture, et non l’issue durable d’un `COMMIT` en erreur.
   - [F] (corrupt) « A sync failure during a COMMIT might result in loss of durability but not in a corrupt database file. »
   - La documentation ne dit pas si un état invisible peut réapparaître après une récupération, ni si un état visible peut disparaître après une coupure lorsque la synchronisation a échoué [O].
5. **Au point a**, la nouvelle tentative, décidée par le propriétaire, suit les règles normales du nonce, qui sont inchangées. `CONSUMED` ou `FAILED` : refus à l’étape 2. `ISSUED` : V0 complet, sous γ1. Cela suppose le retrait normal du marqueur ; sinon, le gel conservateur s’applique [D] (cas 3, « Gel conservateur »).
6. **Aux points b et c**, le constat est la lecture seule que le gel permet. Il ne lève pas le gel à lui seul, et ne permet pas de retirer le marqueur (cas 3, « Mécanisme du marqueur »). Aucune opération qui ouvre n’est acceptée tant que le gel n’est pas levé [D]. Les critères de récupération, la vérification qui lève le gel et le sort d’une nouvelle tentative après la levée restent ouverts [O].

**Cas 4 : `SQLITE_BUSY`, distinct des autres erreurs.**
- **Au `BEGIN IMMEDIATE`.**
  - [F] (transaction) Il peut renvoyer `SQLITE_BUSY` si une autre connexion a une transaction d’écriture active.
  - [F] (rescode, wal) En WAL, il peut aussi le renvoyer pendant la récupération (`SQLITE_BUSY_RECOVERY`), ou pendant le nettoyage par la dernière connexion qui se ferme.
  - Aucune instruction de l’opération n’a alors été exécutée, et le nonce reste `ISSUED`. La qualification du refus reste ouverte [O] (§5.5.5, L.8, point 9).
- **Après un `BEGIN IMMEDIATE` réussi.**
  - [F] (rescode) Aucune opération sur la base, jusqu’au `COMMIT` suivant inclus, ne renvoie `SQLITE_BUSY`.
  - [F] (transaction) En WAL, `IMMEDIATE` et `EXCLUSIVE` sont identiques.
  - [F] (wal) Les lecteurs ne bloquent pas l’écrivain. La page ajoute que c’est « mostly true ».
- **Deux `SQLITE_BUSY` décrits au `COMMIT`** [F] (transaction) :
  - une instruction d’écriture encore en cours sur la connexion ;
  - un lecteur ouvert sur une autre connexion. Pour ce cas seulement, la page indique : « the transaction remains active and the COMMIT can be retried ».
  - [R] Le second cas est exclu par la garantie de rescode. Le premier révélerait une instruction non terminée sur la même connexion, donc un défaut de mise en œuvre.
- **Conduite [R].**
  - Un `SQLITE_BUSY` au `COMMIT` reste une erreur de `COMMIT`, traitée aux cas 1 et 3.
  - Si `in_transaction` reste vrai, la documentation établit seulement, pour le cas du lecteur, que la transaction reste active et que le `COMMIT` peut être retenté. On en déduit que rien n’a été validé [R]. La résolution suit le cas 3, a ou b.
  - [F] (autocommit) `SQLITE_BUSY` figure parmi les erreurs qui peuvent annuler la transaction.
  - Aucun nouveau `COMMIT` n’est exécuté automatiquement. L’admissibilité d’un second `COMMIT` dans la même transaction n’est pas décidée [O].
- **Autres erreurs.**
  - [F] (transaction, autocommit) `SQLITE_FULL`, `SQLITE_IOERR`, `SQLITE_NOMEM` et `SQLITE_INTERRUPT` peuvent annuler la seule instruction, ou toute la transaction. Pour une erreur survenue avant le `COMMIT`, `in_transaction` indique laquelle de ces deux voies SQLite a suivie (transaction). Pour une erreur du `COMMIT`, il ne distingue pas une validation d’une annulation (« Portée des moyens d’observation »).
  - Au `COMMIT`, l’état persistant après ces erreurs n’est pas documenté [O].
  - [F] (conflict) Un `SQLITE_CONSTRAINT` levé par un déclencheur `RAISE(ABORT)` n’annule que l’instruction.
  - [F] (wal) Un point de contrôle automatique peut être lancé par le `COMMIT`. L’effet de son échec sur le code renvoyé n’est pas documenté [O].

**Points restés ouverts [O].**
- La version de SQLite liée sur le serveur et la configuration effective (C3).
- La démonstration de C2 dans la mise en œuvre.
- Lorsque le cas 2 suit un échec de l’annulation complète, la question de savoir si un nouvel essai de `ROLLBACK` est admis (cas 2).
- Le maintien du verrou d’écriture après `ROLLBACK TO`, déduit [H]. L’appel de `sqlite3_close_v2()` et la finalisation des instructions dans CPython 3.14 [H].
- L’état persistant après un `COMMIT` en erreur, et la portée d’une relecture.
- L’acceptation de la perte de la règle « une tentative par nonce » lorsque le nonce reste `ISSUED` après ces erreurs. L’option (a) exclut d’y remédier par une réécriture dans une transaction séparée.
- La portée de la règle « ne permet jamais un effet » (J.7) pour une tentative ultérieure.
- La transition qui ne modifie aucune ligne après une lecture `ISSUED`, et l’emplacement du comptage borné.
- Les codes fixes. L’admissibilité d’un second `COMMIT` dans la même transaction après le `SQLITE_BUSY` documenté.
- La condition 3 du §5.5.5, L.4, après un `COMMIT` en erreur.
- Pour le gel décidé (toute transaction V0, qu’elle ouvre ou qu’elle ferme, et transaction d’E [D]), dont le mécanisme du marqueur est fixé depuis le 28 octobre 2026 [D] :
  - les détails du marqueur : emplacement, nommage et contenu, propriétaires et modes, persistance effective, échecs de création ou de retrait, hors l’échec de synchronisation à la création et la suppression visible non durable réglés le 28 octobre 2026 [D], identification des marqueurs résiduels, opération `root` de retrait (cas 3, « Mécanisme du marqueur »). Le moment de création et l’examen sous W sont fixés depuis le 28 octobre 2026 [D] ;
  - le mécanisme, l’équité et les délais de W, ainsi que l’emplacement et les modes exacts de son fichier, son relâchement et son support étant fixés depuis le 28 octobre 2026 [D] ;
  - la méthode de sauvegarde et la procédure de restauration, y compris l’application du principe selon lequel une restauration ne vaut pas levée du gel ;
  - la conduite si l’état ou la présence du marqueur ne peut pas être établi ; le code et le comptage du refus ; les détails techniques du retrait et de sa durabilité ;
  - les critères de récupération, la vérification qui le lève et les critères détaillés de la levée ;
  - son application aux erreurs du `COMMIT` de la validation avant ancrage ou de D-9 ;
  - la portée de la remise par E (E7) d’une décision enregistrée avant l’incertitude ;
  - l’articulation entre le gel conservateur, l’arrêt forcé de `root` (§5.5.5, L.5) et la disponibilité de D-9 au redémarrage ;
  - le sort, pendant le gel, des opérations signées qui ferment, de la validation avant ancrage et de l’ancrage ;
  - la disponibilité de D-9 pendant le gel, sa portée restant inchangée ;
  - la qualification du refus et le sort du nonce visé ;
  - le sort d’une nouvelle tentative après la levée.

#### 5.5.2 V1, revérification d’intégrité (avant l’ancrage et dans chaque contrôle E)

V1 est une vérification **en lecture seule** de l’intégrité de la confirmation stockée. Ce n’est pas une nouvelle authentification : elle ne demande ni fraîcheur, ni nonce ouvert, ni comparaison du compteur. Elle ne lit pas l’ancre ; la couverture par l’ancre relève de E (§11.2).

Contrôles :

1. l’énoncé stocké se resérialise à l’identique et son empreinte est celle qui est enregistrée ;
2. le défi recalculé à partir de l’énoncé et du nonce qu’il contient est celui de `clientDataJSON` ;
3. `type`, origine et `rpIdHash` d’administration ; UP et UV présents dans `authenticatorData` ;
4. la signature sur `authenticatorData ‖ SHA-256(clientDataJSON)` est valide avec la clé publique du credential, lue dans le fichier de confiance (et non dans la base), avec un statut qui permet la revérification (§5.5.3 [D]) : `ACTIVE`, ou `RETIRED` pour une confirmation antérieure au retrait selon l’ordre du journal ; jamais `COMPROMISED`, ni une clé ajoutée par une clé ultérieurement `COMPROMISED`, sauf pour une opération autorisée après l’entrée effective de sa réautorisation (§5.5.3 [D]). Une entrée de confirmation postérieure à la réautorisation ne suffit pas à l’établir ; voir ci-dessous « Réautorisation et moment de la signature » ;
5. le nonce est `CONSUMED` et désigne cette confirmation ;
6. les lignes utilisées (approbateur, principal, compte, credentials, preuve) correspondent exactement aux champs de l’énoncé signé.
7. **liaison à l’autorisation effective de la clé signataire** — décidé par le propriétaire le 26 octobre 2026 [D] (§5.3 ; §14, point 9). L’entrée d’autorisation liée par l’énoncé signé est cohérente avec l’entrée de l’opération : elle autorise le credential utilisé, et elle la précède dans la chaîne. Elle reste valable : elle n’a pas été invalidée, sous réserve des statuts décidés (§5.5.3 : `RETIRED` pour les confirmations antérieures au retrait, jamais `COMPROMISED`). Une autorisation est notamment invalidée lorsque la chaîne d’ajout de la clé dépend d’une clé `COMPROMISED`, tant qu’une réautorisation valide n’a pas été ancrée. L’entrée d’autorisation précède celle de l’opération : dans E, sa couverture par l’ancre relue découle donc de celle de l’opération (§11.2, étapes 2 et 3). La représentation de la liaison reste ouverte [O].

**Réautorisation et moment de la signature** (§5.5.3). Pour une confirmation signée par une clé dont l’autorisation a été invalidée puis rétablie par réautorisation :
- une entrée qui **précède** celle de la réautorisation suffit à refuser : l’assertion a nécessairement été créée avant ;
- une entrée qui la **suit** ne suffit pas à accepter. Elle date l’enregistrement, pas la création de l’assertion. Quelqu’un qui peut écrire la base pourrait insérer, après la réautorisation, une assertion signée avant elle (voir « Limite : énoncé signé non appliqué », ci-dessous). Les dates SQLite ne sont pas une preuve fiable ;
- **c’est la liaison signée qui décide — décidé le 26 octobre 2026 [D] (contrôle 7).** La confirmation n’est acceptée que si son énoncé signé lie la réautorisation elle-même. Une assertion signée avant la réautorisation lie l’ancienne entrée d’autorisation, invalidée, et échoue. Cette garantie suppose un identifiant imprévisible avant l’écriture de l’entrée (§5.3). Tant que le champ n’est pas défini [O], aucune confirmation de cette clé ne peut être acceptée sur le seul ordre du journal.

**Pourquoi V1 ne compare pas le compteur.** Le compteur a été évalué une fois, pendant V0, et sa valeur a été enregistrée. Le comparer de nouveau à la valeur stockée ferait rejeter la même assertion, dont le compteur vaut déjà cette valeur. V1 vérifie que l’assertion est authentique et rattachée à l’énoncé, pas qu’elle est récente.

**Pourquoi V1 ne contrôle pas `expires_at_ms`.** L’échéance est forcément dépassée lors des usages ultérieurs. La fraîcheur est une propriété établie une seule fois par V0 et consignée par la transaction qui a consommé le nonce.

**Ce que V1 protège.** Une ligne de registre forgée par écriture directe dans la base, sans assertion valide du propriétaire sur un énoncé qui la décrit exactement, échoue en V1. Elle n’est donc jamais ancrée par le service (§11.3) et échoue aussi en E.

**Limite : énoncé signé non appliqué.** Si le propriétaire a signé un énoncé dont l’`apply` n’a pas été validé (précondition non remplie, abandon, refus ultérieur), l’assertion existe hors de la base : sur le poste, dans la session SSH, en mémoire. Quelqu’un qui peut écrire la base pourrait insérer cette confirmation avec une entrée de journal correctement chaînée. Le calcul de la chaîne ne demande aucun secret. V1 l’accepterait, et le service l’ancrerait **lui-même** lors de la validation pré-ancrage : il n’est pas nécessaire de détenir le droit d’ajout à l’ancre. L’effet reste limité à l’opération exacte que le propriétaire a signée pour cette inscription précise. [O] Mesures possibles :
- refuser d’ancrer une entrée qui ouvre si l’instant d’ancrage dépasse le `expires_at_ms` de son énoncé, ou exiger un horodatage du fournisseur de l’ancre antérieur à cette échéance. Contrepartie : une confirmation légitime dont l’ancrage a été retardé (panne, arrêt) devrait être refaite ;
- faire primer un rejet ancré de la même inscription sur une confirmation postérieure.

#### 5.5.3 Statut des clés dans le fichier de confiance

V1 doit encore pouvoir vérifier une confirmation ancienne après la rotation de la clé qui l’a signée. Le fichier de confiance conserve donc chaque clé avec un statut.

**Statuts et portée — décidés par le propriétaire le 26 octobre 2026 [D]** (§14, point 9) :
- `ACTIVE` : autorisé en V0 et vérifiable en V1 ;
- `RETIRED` : retirée sans suspicion. Refusée pour toute nouvelle opération V0 ; les confirmations **antérieures au retrait** restent vérifiables en V1 ;
- `COMPROMISED` : refusée en V0 et en V1. Aucune confirmation signée par cette clé ne peut être utilisée, quelle que soit sa date, puisqu’aucune borne de compromission suffisamment fiable n’est établie. Les lignes qu’elle a confirmées deviennent inutilisables : l’échec reste fermé ;
- une anomalie `signCount` reste un signal seulement (§5.5.4) et ne change jamais automatiquement le statut d’une clé ;
- tout changement de statut est explicite, authentifié, journalisé (J-b) et ancré (J-c) selon les règles générales (§11.1).

**« Antérieure au retrait » : définie par l’ordre du journal, jamais par une date.** Les dates conservées en base (`prepared_at_ms`, instant de vérification de `admin_confirmations`) sont fixées ou modifiables par le compte de service (§2.2 ; §5.5.1, « Sort du nonce selon l’issue ») : elles ne peuvent pas établir l’antériorité. Une confirmation est antérieure au retrait si et seulement si l’entrée de journal qui la consigne précède, dans la chaîne, l’entrée qui consigne le retrait de la clé :
- en V1, l’ordre est lu sur la chaîne locale recalculée. V1 seule ne rend aucune confirmation utilisable (§5.5) ;
- dans E, les deux entrées doivent être couvertes par l’ancre relue, dans la chaîne concordante avec elle (§11.2, étapes 2 et 3). Une confirmation insérée en base après le retrait se place après l’entrée de retrait et échoue, même si elle porte une assertion signée avant le retrait (§5.5.2, « Limite : énoncé signé non appliqué ») ;
- si l’ordre ne peut pas être établi ainsi (entrée de retrait introuvable, pas encore ancrée, ou chaîne divergente), la confirmation est refusée : l’échec reste fermé.

**Portée de `COMPROMISED` sur les opérations qui ouvrent — décidé par le propriétaire le 26 octobre 2026 [D]** (§14, point 9) :
- une fois une clé marquée `COMPROMISED`, aucune opération qui ouvre signée par elle ne peut fonder une autorisation future : confirmation d’inscription, création d’invitation, ajout d’une clé, réouverture de l’interrupteur ou reprise de suspension (opérations 1 à 5 du §11.2) ;
- les effets futurs de ces opérations sont refusés, ou recalculés comme inactifs, selon le chemin concerné. Les opérations déjà exécutées ne sont pas modifiées rétroactivement : leurs entrées de journal restent telles quelles, et rien n’est supprimé ni réécrit ;
- les opérations qui ferment restent applicables. Celles que cette clé a déjà signées gardent leur effet, puisqu’elles ne font que réduire les capacités. De nouvelles opérations qui ferment restent possibles avec une clé `ACTIVE` dont la chaîne d’autorisation n’a pas été invalidée (§5.5.1, étape 5 ; précisé le 27 octobre 2026), ou par la voie d’urgence dans sa portée décidée (§7.0) ; la clé `COMPROMISED` elle-même reste refusée en V0 pour toute nouvelle opération ;
- aucun statut de clé ne change automatiquement : ni celui de l’autre clé, ni celui d’une clé ajoutée par une opération que la clé `COMPROMISED` a signée ;
- si aucune clé `ACTIVE` ne permet d’établir un état valide, le système reste fermé. La procédure de récupération et de remplacement reste ouverte (§5.7, §5.8).

**Application selon le chemin : ce que décrit le brouillon et ce qui reste à concevoir.** La règle ci-dessus est décidée. Son mécanisme n’existe que là où le brouillon décrit déjà un chemin de revérification ; ailleurs, il reste ouvert [O].
- **Confirmation d’inscription (opération 1) : mécanisme existant.** E exécute V1 à chaque usage, avec le statut de la clé lu dans le fichier de confiance (§5.5.2, contrôle 4 ; §11.2). Une confirmation signée par une clé `COMPROMISED` échoue en V1, donc en E : elle est recalculée comme inactive.
- **Reprise de suspension (opération 5) : recalcul existant, contrôle de la clé à concevoir.** Son effet est recalculé à chaque V0 des opérations 1 à 4 et à chaque E, selon la formulation opérationnelle de M.6 (§5.2.7, M.6 [R] ; §11.2). Cette formulation ne vérifie pas la clé qui a signé la reprise. La règle impose qu’une reprise signée par une clé `COMPROMISED` ne lève aucune suspension ; la manière de l’intégrer à ce recalcul reste ouverte [O].
- **Création d’invitation (opération 2) : mécanisme à concevoir.** Son protocole signé n’est pas défini (§6.2). La règle s’appliquera à ses effets futurs, par exemple à la confirmation d’une inscription faite sur cette invitation [O].
- **Ajout d’une clé (opération 3) : règle décidée, mécanisme à concevoir.** La règle d’ajout reste ouverte (§5.7). Pour la clé ajoutée par la clé `COMPROMISED`, voir ci-dessous « Clé ajoutée par une clé ultérieurement `COMPROMISED` ».
- **Réouverture de l’interrupteur (opération 4) : mécanisme à concevoir.** L’interrupteur n’est pas encore conçu (§7.1), et aucun contrôle de son état au moment de l’usage n’est décrit. Une réouverture signée par la clé `COMPROMISED` ne peut pas maintenir l’interrupteur ouvert pour une autorisation future [O].
- **Validation pré-ancrage : classement décidé, distinction sûre limitée.** Elle exécute V1 avec le statut de la clé (§11.3, étapes 2 et 3). Le classement d’un échec dû au seul marquage est décidé ci-dessous (« Marquage `COMPROMISED` survenu avant l’ancrage »).

**Marquage `COMPROMISED` survenu avant l’ancrage — décidé par le propriétaire le 26 octobre 2026 [D]** (§11.3 ; §14, point 9).
- Si une clé est marquée `COMPROMISED` après avoir signé une opération qui ouvre, mais avant l’ancrage de l’entrée qui la consigne, l’entrée peut être ancrée pour l’audit. Elle n’a aucun effet futur.
- Ce changement de statut ne mène pas à S4 à lui seul. S4 reste réservé aux divergences et aux échecs d’intégrité, notamment une signature invalide ou une opération enregistrée alors que la clé était déjà `COMPROMISED`.
- **L’ordre est établi par le journal, jamais par une date SQLite.** On compare la position de l’entrée `n` qui consigne l’opération à celle de l’entrée `c` qui consigne le marquage (tout changement de statut est journalisé et ancré, ci-dessus) :
  - `n` précède `c` : opération enregistrée avant le marquage. Ancrage pour l’audit possible, sans effet futur, sans S4 ;
  - `n` suit `c` : opération enregistrée après le marquage. V0 refuse toute nouvelle opération d’une clé `COMPROMISED` (§5.5.1, étape 5) ; l’entrée suppose donc un contournement de V0, et mène à S4.

**Ce que le protocole permet de distinguer sûrement, et ce qu’il ne permet pas.**
- **Sûr : `c` déjà ancrée et relue** (`c ≤ H`, §11.2). Toute entrée de la queue suit alors `c`. Une entrée de la queue signée par cette clé est donc postérieure au marquage, et mène à S4.
- **Sûr : `n` déjà ancrée avant `c`.** Elle ne repasse pas par la validation pré-ancrage ; seul son effet futur est refusé (V1, E).
- **Limite : `n` et `c` dans la même queue non ancrée.** C’est un cas légitime possible : une opération qui ouvre est enregistrée, l’ancre est indisponible, puis le marquage allonge la queue, comme toute opération qui ferme (§11.3). L’ordre de `n` et de `c` n’est alors attesté que par la chaîne locale, que le compte de service peut réécrire, puisque le calcul de la chaîne ne demande aucun secret (§5.5.2). Le protocole ne permet donc pas de distinguer sûrement une entrée légitime antérieure au marquage d’une entrée placée avant `c` par quelqu’un qui peut écrire la base et détient la clé compromise. Un tel contournement pourrait échapper à S4. Il n’obtiendrait aucun effet, puisque l’entrée n’a aucun effet futur dans les deux cas. [R] V0 exige qu’aucune queue ne soit en attente pour une opération qui ouvre (§5.5.1, étape 1a) : seule la première entrée d’une queue peut être une opération qui ouvre légitime. Cela réduit le cas sans l’éliminer, car l’entrée de tête peut elle-même avoir été remplacée.
- **[O] Conditions dont dépend la distinction :**
  - la désignation fiable de l’entrée `c`, comme celle de l’entrée de retrait ;
  - le moment où `c` est écrite. Elle ne doit pas être journalisée avant que V0 refuse effectivement la clé : sinon une opération légitime enregistrée entre les deux suivrait `c` et serait classée à tort en S4. À l’inverse, un retard de `c` élargit la fenêtre de la limite ci-dessus. Pour le marquage `COMPROMISED`, ce moment est décidé le 27 octobre 2026 : `c` est consignée par la première transaction visée après l’installation de la nouvelle politique, sous barrière (§5.5.5, J.5) [D]. Pour les autres changements de statut, il reste ouvert ;
  - la conduite si `c` est introuvable ou si la chaîne ne permet pas d’établir l’ordre. Dans tous les cas, l’entrée n’a aucun effet futur : seul son classement, S4 ou audit, reste à trancher.

**Clé ajoutée par une clé ultérieurement `COMPROMISED` — décidé par le propriétaire le 26 octobre 2026 [D]** (§5.7 ; §14, point 9).
- Elle conserve son enregistrement dans le fichier de confiance et son statut déclaré. Aucun statut ne change automatiquement.
- Elle ne peut toutefois autoriser **aucune opération future** tant qu’une clé `ACTIVE` ne l’a pas explicitement réautorisée. V0 la refuse pour toute nouvelle opération (§5.5.1, étape 5) ; V1 ne l’accepte pour aucune confirmation (§5.5.2, contrôle 4), donc E non plus.
- Une clé elle-même soumise à cette règle ne peut réautoriser aucune clé, puisqu’elle ne peut autoriser aucune opération.
- **Chaîne d’ajout — décidé par le propriétaire le 26 octobre 2026 [D]** (§14, point 9). La règle vaut pour toute clé dont la chaîne d’ajout dépend d’une clé `COMPROMISED`, directement ou par une clé elle-même ajoutée. Son autorisation est invalidée : elle ne signe plus d’opérations futures tant qu’une réautorisation valide n’a pas été ancrée et n’est pas devenue effective. V0 et V1 l’appliquent par la liaison à l’autorisation effective de la clé signataire (§5.5.1, étape 5 ; §5.5.2, contrôle 7). Pour une opération qui ferme, V0 s’appuie sur le fichier de confiance (§5.5.1, étape 5). **Décidé le 27 octobre 2026 [D] :** le statut `ACTIVE`, qui ne change pas automatiquement, ne suffit pas ; V0 n’accepte la fermeture que s’il établit que la chaîne d’autorisation de la clé n’a pas été invalidée, et la refuse sinon. Restent ouvertes [O] la représentation de cette chaîne dans la politique protégée par `root`, la preuve de sa validité, sa cohérence avec le journal et la conduite en cas de divergence (analyse au §5.5.5).
- **Portée temporelle de la réautorisation — décidé par le propriétaire le 26 octobre 2026 [D]** (§14, point 9) :
  - la réautorisation par une clé `ACTIVE` est une opération explicite, authentifiée, journalisée et ancrée ;
  - elle ne prend effet qu’après l’ancrage requis : son entrée doit avoir été ancrée et relue, comme celle d’une opération qui ouvre (§11.2) ;
  - elle autorise la clé réautorisée pour les opérations futures seulement ;
  - elle ne rend pas rétroactivement utilisables les confirmations ni les opérations signées avant elle ;
  - l’ordre est établi par le journal ancré, jamais par une date SQLite (`prepared_at_ms`, instant de vérification). Une confirmation dont l’entrée précède celle de la réautorisation a nécessairement été signée avant elle : elle reste inutilisable. L’inverse n’est pas vrai : une entrée postérieure ne prouve pas que l’assertion l’est aussi (§5.5.1, étape 5 ; §5.5.2) ;
  - la clé reste inutilisable tant que la réautorisation n’est pas effective. Si aucun chemin sûr ne permet de réautoriser, le système reste fermé.
- **[O] Mécanismes dont dépend cette garantie :**
  - l’ajout de clé n’est pas conçu (§5.7), et le brouillon ne décrit aucun chemin par lequel une clé serait ajoutée par une opération signée. La garantie devra faire partie de sa conception : V0 et V1 devront pouvoir établir quelle clé a signé l’ajout, sans s’appuyer sur une valeur SQLite seule ;
  - **la réautorisation elle-même :** son nom, son format, son énoncé signé et son classement parmi les opérations du §11.2, qui ne la mentionne pas. Restent aussi ouverts la désignation fiable de son entrée de journal, sa validation pré-ancrage (le §11.3 ne prévoit de branche que pour les opérations 1 à 5) et la manière dont V0 et E établissent qu’elle est effective ;
  - **V0 : assertion préparée ou signée avant la réautorisation.** La règle est désormais tenue par la liaison à l’autorisation effective de la clé signataire, décidée le 26 octobre 2026 [D] (§5.3 ; §5.5.1, étape 5), et non par l’ordre du journal, qui date l’enregistrement et pas la signature. Restent ouverts le nom du champ, son encodage, la représentation de la genèse et le format de l’ajout et de la réautorisation ;
  - **V1 : confirmations antérieures.** La règle est fixée : une confirmation dont l’entrée précède celle de la réautorisation reste inutilisable. Pour une confirmation enregistrée après, l’ordre ne suffit pas : V1 exige que l’énoncé signé lie la réautorisation elle-même (§5.5.2, contrôle 7 [D]). La représentation de cette liaison reste ouverte ;
  - le sort d’une réautorisation signée par une clé elle-même marquée ensuite `COMPROMISED` : la portée décidée ci-dessus ne nomme pas cette opération.

**Restent ouverts [O] :**
- la manière de désigner de façon fiable l’entrée de retrait, par exemple par son `entry_hash` inscrit dans le fichier de confiance protégé par `root`. Elle relève de la procédure de changement de statut (§5.7) ;
- la procédure de perte et de remplacement des clés, et la manière de sortir d’un blocage, par exemple si les deux clés sont perdues ou `COMPROMISED` (§5.7, §5.8) ;
- les mécanismes qui appliquent la portée de `COMPROMISED` aux opérations 2 à 5, la désignation fiable et le moment d’écriture de l’entrée de marquage (décidé pour `COMPROMISED` le 27 octobre 2026, §5.5.5, J.5), la distinction sûre des cas lorsque l’opération et le marquage attendent dans la même queue, le format de l’ajout et de la réautorisation, et la représentation de la liaison à l’autorisation effective de la clé signataire (ci-dessus ; §5.3).

**Révocation d’attestation après la genèse — décidé le 26 octobre 2026 [D] (§5.2.7, M.6) ; portée fermée décidée le 29 octobre 2026 [D].** Une révocation défavorable peut être connue après la genèse. Seuls quatre cas en relèvent, connus par un import : statut de sécurité applicable du modèle, `REVOKED`, AC intermédiaire révoquée ou ancre retirée (§5.2.7, K.7). Toute extension exige une décision distincte ; l’applicabilité d’un statut de sécurité selon `authenticatorVersion` reste ouverte [O] (§5.2.7, G).
- Elle ferme les opérations qui ouvrent et déclenche une revue par le propriétaire.
- Elle **ne modifie jamais automatiquement** le statut d’une clé dans le fichier de confiance.
- Tout passage à `RETIRED` ou `COMPROMISED` exige une décision distincte.
- La reprise exige une décision administrative authentifiée et une politique valide, journalisée et ancrée.

#### 5.5.4 Compteur : ce qui est fixé et ce qui reste ouvert

- **Fixé par cette spécification :** le compteur n’est lu et enregistré qu’en V0, dans la même transaction que l’effet. Il n’est jamais comparé en V1 ni en E.
- **Fait du dépôt :** le prototype v3 applique aux approbateurs une règle (0 suivi de 0 accepté ; sinon, valeur strictement supérieure exigée, refus et signal unique dans le cas contraire), mais G1 indique que la politique du compteur n’est pas décidée (G1 l. 757, 775). Cette règle du prototype vise les approbateurs ; elle ne s’applique pas aux credentials d’administration, dont la politique est fixée ci-dessous.
- **Politique des credentials d’administration : option (b), signal seulement — décidée par le propriétaire le 26 octobre 2026 [D]** (§14, point 8). Soit `ancien` la dernière valeur `signCount` acceptée pour ce credential et `nouveau` celle de l’assertion présentée :
  - `ancien = 0` et `nouveau = 0` : aucune anomalie ;
  - l’une des deux valeurs est non nulle et `nouveau ≤ ancien` : un **signal borné** est consigné ; l’opération n’est pas refusée pour ce seul motif ;
  - `nouveau > ancien` : aucune anomalie ;
  - la nouvelle valeur est enregistrée à chaque opération acceptée, y compris après un signal (§5.5.1, étape 9) ;
  - un signal de compteur ne fait pas passer le nonce à `FAILED` et ne bloque pas l’effet de l’opération si les autres contrôles réussissent. Les autres règles de nonce et d’effectivité restent celles des §5.5.1 et §11.2 ;
  - le signal **n’est pas une preuve de clonage** : une réinitialisation de l’authentificateur produit le même écart (G1 l. 775). Il ne change jamais automatiquement le statut du credential dans le fichier de confiance (§5.5.3) et ne suspend pas le service. Tout changement de statut exige une décision distincte (§5.5.3).
- **[O] Restent ouverts :**
  - les détails du signal borné : support et contenu de l’entrée (J-b prévoit un événement « signal de compteur », §11.1), bornes et fenêtre (§10.3, qui propose « au plus une fois par credential et par nonce »), sort du signal lorsqu’une étape ultérieure de V0 refuse l’opération ;
  - la valeur initiale du compteur après la genèse (§5.2.4, D).

#### 5.5.5 Représentation et preuve de la chaîne d’autorisation : analyse [R], décisions de portée du 27 octobre 2026 [D] et points ouverts [O]

Cette sous-section examine le point laissé ouvert par la décision du 27 octobre 2026 (§5.5.1, étape 5). **Jusqu’en I, elle ne contient aucune décision nouvelle ; J consigne les décisions de portée du 27 octobre 2026 [D].** Ce qui suit est une analyse, une piste ou une recommandation [R], ou une question ouverte [O]. Les décisions rappelées en A restent inchangées. **Révisée le 27 octobre 2026.** La version précédente présentait l’option 3 comme compatible et immédiate sans réserve, et l’écriture du manifeste en premier comme sans intervalle. Ces deux affirmations sont corrigées en E, F et H. **Complétée le même jour** par une recommandation [R], qui n’était pas alors une décision du propriétaire (I) : l’invalidation n’y serait autoritative qu’une fois inscrite dans la politique `root`, et prendrait donc effet à cette inscription, non au seul `COMMIT` SQLite. Ses incompatibilités avec les décisions actuelles et les décisions de portée qu’elle suppose sont relevées en J. K analyse ensuite l’ordre des écritures de I.4 et la chronologie du journal, sans rien décider. Elle compare trois ordres : J-b d’abord, politique `root` d’abord, et barrière de consignation. Elle corrige une affirmation de F et de I.4. À la suite de cette analyse, I.4 a intégré la barrière de consignation γ1. **Le propriétaire a ensuite pris, le 27 octobre 2026, sept décisions de portée, consignées en J [D].** Elles précisent la recommandation I et la barrière γ1, qu’elles complètent par une barrière exclusive prise par `root`. Elles ne modifient aucune décision antérieure. L analyse le protocole de coordination de cette barrière, sans rien décider. Elle relève qu’un processus du service peut retenir la barrière (L.5). Le propriétaire a tranché le même jour : option (d), couverture d’E, et D-9 hors barrière (L.5, L.8) [D]. Il a ensuite précisé le sens de la couverture par l’ancre, la règle de la genèse pour E et le sort de D-9 pendant l’arrêt forcé (L.2, L.5, L.8) [D].

##### A. Ce que le brouillon fixe déjà

- **Règle à tenir [D, 27 octobre 2026].** Une opération signée qui ferme n’est acceptée que si le credential signataire est autorisé et si sa chaîne d’autorisation n’a pas été invalidée. Le statut `ACTIVE` ne suffit pas à lui seul. Si V0 ne peut pas établir cette validité, il refuse (§5.5.1, étape 5).
- **Effet au `COMMIT` local [D, 26 et 27 octobre 2026]**, sans relecture de J-c ni attente de l’ancrage (§11.2).
- **Cause d’invalidation [D, 26 octobre 2026].** La seule cause décidée est une chaîne d’ajout qui dépend d’une clé `COMPROMISED`, directement ou par une clé elle-même ajoutée. Seule une réautorisation par une clé `ACTIVE` la lève, après ancrage et relecture, pour les opérations futures (§5.5.3).
- **Statuts [D].** Aucun statut ne change automatiquement ; tout changement est explicite, authentifié, journalisé (J-b) et ancré (J-c) (§5.5.3).
- **T-3 [D].** Le fichier de confiance appartient à `root`. `aidirector` le lit sans pouvoir le modifier, et toute mise à jour passe par l’opération `root` contrôlée (§9.2). La base SQLite, J-b compris, appartient au compte de service.
- **Emplacement du statut.** Le brouillon conserve le statut de chaque clé dans le fichier de confiance (§5.5.3), où V1 le lit (§5.5.2, contrôle 4). Si cette disposition est retenue, un marquage `COMPROMISED` définitif passe nécessairement par l’opération `root` (T-3). Une invalidation connue seulement en base n’en est alors qu’une anticipation.
- **Limite déjà admise par le brouillon.** Un processus qui peut écrire la base peut effacer une révocation enregistrée en base, et seul l’ancrage le révèle. Le changement de statut dans le fichier de confiance par `root` est la seule révocation qui ne dépend pas de la base (§5.7, « Limite » ; §12). Un compte de service compromis peut donc annuler tout effet de fermeture conservé en base, et même contourner V0 en écrivant directement la base.
- **Principe déjà posé par le brouillon [R].** Une valeur que le compte de service peut modifier peut servir à **refuser** plus vite, jamais à **accepter** (§11.2).
- **Non décidé [O].** Qui exécute le marquage `COMPROMISED`, par quel chemin et avec quelle authentification. La règle d’ajout, de remplacement et de révocation (§5.7). Le moment d’écriture de l’entrée de marquage (§5.5.3).
- **Tranché depuis, le 27 octobre 2026 (J) [D] :** le chemin et l’authentification du marquage `COMPROMISED` (J.3), et le moment d’écriture de son entrée (J.5). La règle générale d’ajout, de remplacement et de révocation reste ouverte (§5.7).

##### B. La tension

Quatre exigences se rencontrent :

1. le service doit refuser toute opération signée par une clé dont la chaîne d’autorisation est invalidée ;
2. le compte de service ne peut pas modifier la politique protégée par `root` (T-3) ;
3. une opération qui ferme ne relit pas J-c ;
4. une fermeture acceptée prend effet au `COMMIT` local.

Ce qui en découle :

- **Une ligne SQLite ne prouve ni l’invalidation ni son absence.** Le compte de service peut insérer une fausse indication, effacer ou réécrire une vraie, ou restaurer une base antérieure. Un effacement n’est détecté que par l’ancre (§11.4), que les fermetures ne relisent pas (exigence 3).
- **Le manifeste `root` peut être en retard.** Si le marquage d’une clé est d’abord enregistré en base, par exemple par une opération signée qui ferme, effective au `COMMIT` (exigence 4), le compte de service ne peut pas le reporter dans le fichier protégé (exigence 2). Tant que `root` ne l’a pas fait, ce fichier atteste encore une validité périmée.
- **Risque concret.** Une clé `K’` ajoutée au moyen d’une clé ensuite marquée `COMPROMISED` peut être aux mains de l’attaquant. Si ses fermetures signées sont encore acceptées, elle peut rejeter des inscriptions, révoquer des credentials de B ou tenter de révoquer la clé légitime du propriétaire. Les révocations sont définitives (D-9). Le dommage est une destruction ou un déni de service, jamais une ouverture.
- **Asymétrie.** La règle exige une preuve pour **accepter**, pas pour **refuser**. Une invalidation doit donc s’appliquer dès qu’elle est connue. Une autorisation ou une réautorisation ne doit être acceptée que sur une source protégée par `root`. Un retard du manifeste est sans danger pour une réautorisation : la clé reste refusée, et l’échec reste fermé. Pour une invalidation, le même retard est dangereux.

##### C. Piste [R] : manifeste d’autorisation canonique protégé par `root`

Forme envisagée, non décidée : un fichier canonique (`canonical_json`, comme l’énoncé, §5.3), propriété de `root` et lisible par `aidirector` (T-3). Il pourrait être joint au fichier de confiance ou inclus dans celui-ci [O].

En tête :
- `store_id` et version du format ;
- une **génération** strictement croissante et l’empreinte du manifeste précédent ;
- l’`entry_hash` de la dernière entrée J-b prise en compte par `root` lors de l’écriture. Le manifeste ne peut pas contenir l’empreinte de l’entrée J-b qui le consigne s’il est écrit avant elle : c’est cette entrée qui référence l’empreinte du manifeste (F, option 1a).

Pour chaque credential d’administration :
- les empreintes SHA-256 du credential ID et de la clé publique COSE, le rôle et le statut (§5.5.3) ;
- l’**événement d’autorisation effectif** : l’`entry_hash` de l’entrée J-b de genèse, d’ajout ou de réautorisation qui l’autorise actuellement. C’est la valeur que lie l’énoncé signé (§5.3) ;
- l’**événement autorisant** : l’empreinte du credential qui a signé cet ajout ou cette réautorisation, ou la mention de la genèse ;
- les **invalidations applicables** : les références des marquages `COMPROMISED` d’une clé de sa chaîne, non levés par une réautorisation effective ;
- la **génération** qui a introduit chaque élément ;
- pour un ajout ou une réautorisation, qui ne sont effectifs qu’après ancrage, une référence à la relecture de l’ancre constatée par `root` [O].

Avec chaque génération, `root` conserve aussi, dans un fichier qu’il protège, l’énoncé signé et l’assertion qui l’ont fondée. Sans eux, l’entrée J-b ne pourrait pas être reconstituée après une panne (F, option 1a). La recommandation I.4 propose de les conserver **avant** la mise à jour de la politique [R].

Avec cette forme, V0 peut établir à partir du seul manifeste qu’une chaîne n’est pas invalidée **selon la génération qu’il lit**. Il remonte les événements autorisants jusqu’à la genèse et vérifie qu’aucune invalidation applicable n’est inscrite. **Cela ne suffit pas.** Le manifeste ne contient que ce que `root` y a écrit, au moment où il l’a écrit. La piste ne devient une solution qu’avec une réponse aux questions de D et aux décisions de portée de H.

##### D. Deux questions à résoudre

1. **Application immédiate.** Entre le moment où une invalidation est connue et celui où `root` l’inscrit, quelle source fait refuser V0, et avec quelle garantie ?
2. **Reprise après panne.** Le manifeste et J-b sont deux supports distincts, sans transaction commune. Si l’écriture s’interrompt entre les deux, comment l’état est-il reconnu et réparé, sans jamais accepter une chaîne invalidée ?

##### E. Invalidation connue en base, invalidation inscrite dans la politique `root`

| | Invalidation connue seulement en base | Invalidation inscrite dans la politique `root` |
|---|---|---|
| Qui peut l’écrire | Le compte de service : opération signée appliquée par le service, ou toute écriture directe | `root`, par l’opération contrôlée (T-3) |
| Processus et marqueur intègres | V0 refuse dès le `COMMIT` du marqueur | V0 refuse dès le renommage du fichier |
| Compte de service compromis | **Aucune garantie** : le marqueur peut être omis, effacé, réécrit ou supprimé par restauration | Le compte ne peut pas la modifier. Le code de V0, propriété de `root`, la respecte. Le compte peut toutefois contourner V0 pour les effets conservés en base (A) |
| Panne | Atomique avec la transaction SQLite | Indépendante de SQLite ; écart possible avec J-b (F, 1a) |
| Valeur de preuve | Aucune, ni pour la présence ni pour l’absence | Celle que donne T-3, hors compromission de `root` (D-15) |
| Rôle possible | Refuser seulement | Refuser, et fonder l’acceptation |

**Conséquence.** Face à un compte de service compromis, la règle du 27 octobre n’est tenue que pour les invalidations inscrites dans la politique `root`. Pour une invalidation connue seulement en base, elle n’est tenue que si les processus restent intègres.

##### F. Options

**Option 1a — marquage par l’opération `root` contrôlée, lancée par le propriétaire par SSH.** L’invalidation est inscrite dans la politique `root`. Les points ci-dessous sont des pistes [R] : aucun n’est démontré.

- **Qui authentifie le marquage.** SSH et `sudo` donnent l’accès système, pas l’autorisation d’administration (A-1). Piste [R] : une assertion WebAuthn fraîche, avec UV, d’un credential d’administration dont la chaîne est valide selon la génération courante du manifeste. Elle porte sur un énoncé canonique de marquage qui :
  - désigne la clé visée par ses empreintes ;
  - lie l’autorisation effective du signataire (règle du 26 octobre, §5.3) ;
  - désigne la génération du manifeste à laquelle il s’applique.

  Un marquage par SSH et `sudo` seuls, sans WebAuthn, reviendrait à étendre la voie d’urgence à la révocation d’un credential d’administration. Cette extension est seulement recommandée au §7.0 et n’est pas décidée (§14, point 12) ; cette analyse ne la retient pas.
- **Comment `root` vérifie l’événement et son autorisation.** Piste [R] :
  - l’opération `root` engendre le défi en mémoire, pendant une seule invocation, comme pour la genèse (C-1, §5.2.5). Elle n’utilise ni nonce ni ligne de la base pour accepter ;
  - elle vérifie l’assertion avec la clé épinglée lue dans le manifeste, puis, toujours d’après le manifeste, la chaîne du signataire, l’autorisation effective liée par l’énoncé et la génération ;
  - elle refuse si la génération a changé depuis la préparation de l’énoncé ;
  - la base ne peut fournir que des motifs de refus ;
  - le code qui vérifie appartient à `root` (T-3).
- **Comment J-b est alimenté.** Un processus `root` qui ouvre la base risque de créer des fichiers `-wal` ou `-shm` appartenant à `root`, que le contrôle existant refuse (`approval_store.py:332-347`). Deux pistes [R], à vérifier :
  - après le renommage, l’opération écrit l’entrée J-b dans un processus enfant qui a pris l’identité du compte de service (utilisateur, groupe, environnement propre). Piste non retenue : selon J.4, le service inscrit lui-même l’événement ;
  - ou le service écrit lui-même l’entrée lorsqu’il constate une génération non consignée (ci-dessous). C’est la piste retenue par la décision du 27 octobre 2026 (J.4) [D].

  Dans les deux cas, l’entrée est dérivée de la génération inscrite : numéro, empreinte du manifeste, et empreintes de l’énoncé et de l’assertion conservés avec elle (C). Elle peut donc être recalculée et comparée.
- **Ordre, et absence d’atomicité.** Le renommage d’un fichier n’est pas atomique avec une transaction SQLite, et aucun ordre ne le rend tel.
  - **Écrire le manifeste en premier** ne supprime pas l’intervalle : il le déplace de l’application de l’invalidation vers le journal. Pendant cet intervalle, le changement de statut est en vigueur dans la politique `root` sans être ni journalisé ni ancré.
  - **Écrire J-b en premier** fait l’inverse : l’invalidation est d’abord connue seulement en base (E), sans garantie face à un compte de service compromis.
- **Panne entre la mise à jour de la politique et l’écriture du journal.** Pistes [R] :
  - **avant le renommage :** rien n’a changé. Le propriétaire recommence avec un défi frais, sans reprise (comme C-1) ;
  - **après le renommage, avant l’entrée J-b :** la génération g+1 est en vigueur sans être consignée. Elle est reconnue en comparant la génération du manifeste à la dernière génération consignée dans J-b, puis consignée par l’entrée dérivée ci-dessus, de façon idempotente. Cela suppose que l’énoncé et l’assertion aient été conservés avec la génération (C) ; sinon, l’entrée ne peut consigner que l’empreinte du manifeste ;
  - **tant que g+1 n’est pas consignée :** les invalidations qu’elle inscrit s’appliquent, mais aucun élément qu’elle ajoute (ajout, réautorisation) ne sert à accepter. Les opérations qui ouvrent ne restent refusées que si une queue est en attente (§5.5.1, étape 1a). Avant la consignation, ce n’est pas le cas si la queue était vide et ancrée au moment du renommage (**correction** ; K.2) ;
  - **après l’entrée J-b, avant l’ancrage :** file d’attente ordinaire (S1, §11.3) ;
  - **entrée J-b effacée par un compte de service compromis :** la génération redevient non consignée. Aucune invalidation n’est levée ; seul un déni de service en résulte.
- **Non démontré [O] :**
  - la durabilité du renommage (synchronisation du fichier et de son répertoire) ;
  - l’identité exacte du processus qui écrit J-b ;
  - le transfert de l’énoncé et de l’assertion entre le poste et l’opération `root` ;
  - la conduite si la consignation échoue durablement.
- **Compatibilité.** Le marquage ne passe plus par un `COMMIT` SQLite : son effet est l’inscription dans la politique `root`. Les décisions ne disent pas si « effective au `COMMIT` local » vise un tel changement, ni si la journalisation d’un changement de statut peut suivre son effet (H, décisions de portée 1 et 4 ; tranchées le 27 octobre 2026 en J.1 et J.4).

**Option 1b — mise à jour privilégiée déclenchée par le service**, par exemple par un utilitaire `root` appelable par `aidirector` pendant l’opération signée qui ferme.
- **Processus intègres.** L’invalidation peut s’appliquer dès l’écriture du manifeste. Celle-ci n’est pas atomique avec le `COMMIT` : si le `COMMIT` échoue ensuite, le manifeste porte une invalidation sans entrée J-b, qu’il faut reconnaître et réparer.
- **Compte de service compromis.** Le compte décide d’appeler ou non l’utilitaire. Il peut donc empêcher l’inscription : aucune garantie de plus que l’option 3.
- **T-3.** Ce chemin d’écriture `root` est atteignable depuis le compte de service. `root` analyserait des entrées à la demande d’un compte non fiable. Si l’utilitaire ne vérifie pas lui-même l’assertion, des invalidations forgées deviennent possibles, ce qui ouvre un déni de service. T-3 exige une opération administrative `root` *contrôlée*, et un déclenchement par le compte de service ne paraît pas compatible avec cette exigence sans décision explicite.

**Option 2 — changer le moment où la fermeture devient effective.** La fermeture qui invalide, ou toutes les fermetures, attendraient l’ancrage ou l’inscription au manifeste.
- **Incompatible avec les décisions des 26 et 27 octobre 2026** sur les opérations signées qui ferment : effet au `COMMIT` local, sans relecture de J-c ni attente de l’ancrage. L’adopter exigerait une nouvelle décision du propriétaire.
- Les fermetures dépendraient alors de l’ancre ou de `root`. Une panne de l’ancre empêcherait de fermer, ce qui inverse la propriété recherchée : les opérations qui ferment restent possibles quand l’ancre est indisponible (§11.3).
- **Variante.** Si le marquage `COMPROMISED` est une opération `root` et non une opération signée appliquée par le service, son effet suit l’inscription. Cette variante revient à l’option 1a et dépend des mêmes décisions de portée (H).

**Option 3 — refuser d’après la base, accepter seulement d’après le manifeste.** C’est le principe du §11.2 appliqué à la chaîne. V0 n’accepte une opération signée qui ferme que si **les deux** conditions suivantes sont remplies :
- le manifeste `root` établit que le credential est autorisé et que sa chaîne n’est pas invalidée (piste C) ;
- la base ne contient **aucune** indication d’invalidation pour une clé de cette chaîne, par exemple un marquage enregistré en base et pas encore inscrit au manifeste, que cette indication soit authentique ou non. L’ascendance est lue dans le manifeste, jamais dans la base.

Une indication en base peut seulement ajouter un refus. Elle ne peut jamais remplacer le manifeste pour accepter.
- **Si le processus et le marqueur restent intègres.** Le marqueur s’applique dès son `COMMIT` : toute V0 dont la transaction commence ensuite le lit et refuse, `BEGIN IMMEDIATE` sérialisant les transactions (§5.5.1). Une panne le laisse entier ou absent, puisque la transaction SQLite est atomique. Le report au manifeste vient ensuite par l’opération `root`, rejouable.
- **Face à un compte de service compromis : aucune garantie** pour une invalidation connue seulement en base. Le compte peut ne pas écrire le marqueur, l’effacer, le réécrire pour qu’il désigne une autre clé, ou restaurer une base antérieure. V0 lit alors un manifeste qui atteste une validité périmée, et il accepte. L’effacement n’est détecté qu’après coup, par l’ancre, et seulement si l’entrée avait été ancrée (§11.3, S4). Le V0 des fermetures ne relit pas J-c.
- **Ce qui borne le dommage, sans constituer une garantie [R].** Un compte de service compromis obtient déjà, sans signature, tout effet de fermeture conservé en base (A). Une fermeture acceptée à tort n’ajoute donc quelque chose qu’à deux endroits :
  - la trace d’audit, qui attribue à une opération authentifiée une fermeture signée par une chaîne invalidée ;
  - tout chemin qui se fierait à la base pour accepter une modification de la politique `root`. Ce chemin est exclu si cette politique n’est modifiée que par l’opération `root` lancée par le propriétaire, et si cette opération ne se fie jamais à la base pour accepter (1a).
- **Réautorisation.** Seul le manifeste la lève. D’ici là, les fermetures signées par la clé réautorisée sont refusées : l’échec reste fermé.
- **Compatibilité.** Avec des processus intègres, l’option respecte les décisions. Face à un compte de service compromis, elle ne tient pas la règle du 27 octobre pour une invalidation connue seulement en base. **Seule, elle n’est donc pas une solution.** Son usage comme motif de refus supplémentaire reste possible avec toute autre option.

##### G. Comparaison

| | Processus intègres | Compte de service compromis | Panne | Compatibilité avec les décisions |
|---|---|---|---|---|
| 1a, manifeste d’abord | Invalidation appliquée au renommage | Invalidation hors de portée du compte ; effets en base toujours exposés (A) | Non atomique : génération en vigueur, non consignée, à reconnaître et consigner | Décisions de portée 1, 3 et 4 tranchées le 27 octobre 2026 (J) |
| 1a, J-b d’abord | Comme l’option 3 jusqu’au report | Comme l’option 3 jusqu’au report | Report rejouable | Comme l’option 3 |
| 1b | Invalidation appliquée à l’écriture du manifeste | Aucune garantie : le compte décide de l’appel | Invalidation sans entrée J-b si le `COMMIT` échoue | **Tension avec T-3** |
| 2 | La fermeture attend | — | Simple | **Non** (décisions des 26 et 27 octobre), sauf la variante, qui revient à 1a |
| 3 | Invalidation appliquée au `COMMIT` | **Aucune garantie** pour une invalidation connue seulement en base | Atomique côté SQLite | Oui pour des processus intègres ; non face à un compte de service compromis |

##### H. Incompatibilités et décisions de portée nécessaires [O]

**Constat.** Sous la lecture la plus stricte des décisions actuelles, aucune option ne les satisfait toutes à la fois :
- si le marquage est une opération signée appliquée par le service, effective au `COMMIT` local, l’invalidation est d’abord connue seulement en base. La règle du 27 octobre n’est alors pas tenue face à un compte de service compromis (options 3 et 1b, et 1a « J-b d’abord » jusqu’au report) ;
- si le marquage est d’abord inscrit par `root` (1a), la règle est tenue par tout processus qui lit la politique. En revanche, l’effet ne survient pas à un `COMMIT` local, et le changement de statut est en vigueur avant d’être journalisé et ancré ;
- retarder l’effet des fermetures (option 2) contredit les décisions des 26 et 27 octobre.

**Décisions de portée nécessaires, à trancher par le propriétaire.** Ce document n’en prend aucune.
1. **Sens d’« effet immédiat au `COMMIT` local ».** Vise-t-il seulement les effets de fermeture conservés en base (rejet, révocation en base, clôture de nonces), ou aussi les changements de la politique `root`, dont le marquage `COMPROMISED` ? Est-ce une garantie pour des processus intègres seulement, comme le brouillon l’admet déjà pour toute révocation conservée en base (§5.7, « Limite ») ?
2. **Moment où une invalidation compte pour la règle du 27 octobre.** À son enregistrement en base, ou à son inscription dans la politique `root` ? Dans le second cas, une indication en base reste un motif de refus supplémentaire, jamais une condition d’acceptation.
3. **Chemin et authentification du marquage `COMPROMISED`.** Les choix possibles sont :
   - opération `root` avec assertion WebAuthn (1a) ;
   - opération signée appliquée par le service ;
   - les deux, en deux temps.

   Un marquage par SSH et `sudo` seuls relèverait de l’extension de la voie d’urgence (§7.0 ; §14, point 12).
4. **Journalisation d’un changement de statut.** Doit-elle précéder l’effet ou lui être atomique, ou peut-elle le suivre avec une reprise idempotente ? Avec deux supports distincts, l’atomicité n’est pas disponible.
5. **Limite résiduelle.** Si une invalidation peut rester connue seulement en base, faut-il accepter qu’un compte de service compromis l’efface avant son inscription par `root` ?

**Ces questions ont été tranchées par le propriétaire le 27 octobre 2026 (J) [D].** Deux points s’y ajoutent : l’ordre et la barrière γ1 (J.5), et le traitement des refus γ1 et du nonce (J.7).

**Autres questions ouvertes [O] :**
- **réautorisation et ajout : preuve qu’ils sont effectifs.** Les fermetures ne relisent pas J-c. Seul `root`, en mettant à jour le manifeste, peut donc établir qu’un ajout ou une réautorisation a été ancré et relu. Il doit pour cela pouvoir relire l’ancre, alors que le processus qui la relit reste ouvert (§11.4 ; §14, point 17) ;
- **cohérence du manifeste avec J-b et J-c, et conduite en cas de divergence.** Pistes [R], à trancher :
  - un marquage présent en base mais pas encore inscrit au manifeste entraîne le refus pour la chaîne concernée, un signal et une inscription par `root`. Ce n’est pas S4 à lui seul ;
  - une génération du manifeste non consignée dans J-b : ses invalidations s’appliquent, et ses autres éléments ne servent pas à accepter (F, 1a) ;
  - un élément du manifeste dont l’entrée J-b est absente ou différente, alors que sa génération est consignée, entraîne le refus pour la clé concernée et un incident d’intégrité. Son classement en S4 reste à trancher ;
  - une génération du manifeste inférieure à la dernière consignée dans J-b indique un retour arrière du fichier, et entraîne le refus de toute opération signée. La compromission de `root` reste hors de la protection d’A-1 (D-15) ;
  - les fermetures contrôlent ces points par rapport à la chaîne locale seulement. Les opérations qui ouvrent les contrôlent par rapport à la chaîne concordante avec l’ancre relue (§5.5.1, étapes 1 et 5) ;
- **impossibilité d’écrire le journal.** Une opération signée qui ferme écrit J-b dans sa transaction (§5.5.1, étape 9) : sans cette écriture, il n’y a pas de `COMMIT`, donc pas d’effet. Il ne reste que la voie d’urgence, dans sa seule portée décidée : l’interrupteur (§7.0). Pour les autres fermetures, aucune voie de repli n’est décidée ;
- **genèse.** Le manifeste initial devrait être installé avec les deux entrées de genèse, dans la même opération `root` (§5.2.2, règle 5). Comme `root` ne doit pas créer de fichiers SQLite qui lui appartiennent, la consignation de la genèse dans J-b pose la même question qu’en F (1a). Son ancrage reste ouvert (§11.4).

##### I. Recommandation du 27 octobre 2026 [R], précisée par les décisions de portée du même jour [D]

**Statut.** Rédigée comme recommandation [R], elle a été précisée et retenue, sur les points de portée, par les décisions du propriétaire du 27 octobre 2026, consignées en J [D]. Ces points sont signalés [D] ci-dessous. Les modalités, formats et mécanismes restent [R] ou [O]. Rien n’est démontré, mis en œuvre ni validé. Elle remplace la recommandation antérieure de cette sous-section. Elle en garde l’orientation (option 1a pour le marquage, option 3 comme seul motif de refus supplémentaire) et précise la source autoritative de l’invalidation, l’authentification du marquage et l’ordre des écritures.

**I.1 Portée du `COMMIT` local [R].** Le `COMMIT` local rend immédiatement effectif, dans le service, l’effet d’une opération qui ferme, lorsque le processus du service et son code restent intègres. Il ne garantit pas à lui seul une invalidation fiable face à un compte de service compromis (E ; §5.7, « Limite »). **Décidé le 27 octobre 2026 (J.1) [D]**, avec une précision : cette règle vaut pour les fermetures ordinaires ; le marquage `COMPROMISED`, transition spéciale de la politique d’autorisation, ne prend effet qu’à l’installation de la nouvelle politique `root`.

**I.2 Source autoritative de l’invalidation [R].** Une invalidation de chaîne n’est autoritative qu’une fois inscrite dans la politique protégée par `root` (piste C). Un marqueur SQLite peut entraîner un refus supplémentaire (option 3), mais ne peut jamais justifier une acceptation. **Décidé le 27 octobre 2026 (J.2) [D].**

**I.3 Marquage `COMPROMISED` par une opération `root` contrôlée [R].** Il passerait par l’opération `root` contrôlée (T-3), authentifiée par **un autre credential d’administration encore valide** :
- le signataire n’est pas la clé visée. Une clé ne se marque pas elle-même par cette voie ;
- « encore valide » s’entendrait ainsi : statut `ACTIVE` et chaîne non invalidée selon la génération courante de la politique `root`, chaîne qui ne dépend pas de la clé visée [R] ;
- les modalités restent celles de l’option 1a, toutes [R] (F) : assertion WebAuthn fraîche avec UV sur un énoncé canonique de marquage ; défi engendré en mémoire par une seule invocation `root` ; vérification d’après la seule politique `root`, la base ne fournissant que des motifs de refus ;
- SSH et `sudo` seuls ne suffisent pas. Cette recommandation n’étend pas la voie d’urgence (§7.0 ; §14, point 12) ;
- **conséquence :** si aucun autre credential valide n’existe (autre clé perdue, `COMPROMISED` ou de chaîne invalidée), le marquage est impossible par cette voie. La situation relève alors de la perte des clés, dont la procédure reste ouverte (§5.8) [O]. Jusque-là, la clé suspecte n’est pas invalidée dans la politique `root`. Seul un marqueur en base peut alors la faire refuser, avec la garantie limitée de I.5.

**Décidé le 27 octobre 2026 (J.3) [D] :** un autre credential d’administration, dont le statut et la chaîne sont valides dans la politique `root` courante et ne dépendent pas du credential visé ; une assertion WebAuthn fraîche avec UV ; ni SSH ni `sudo` seuls ; sans autre credential valide, aucun marquage par cette voie, la récupération relevant du §5.8 ; D-9 non étendue. Restent [R] : l’énoncé canonique de marquage et la production du défi en mémoire.

**I.4 Ordre des écritures et reprise après panne, sans écriture de SQLite par `root`.** Ordre, conservation, reprise et barrière : décidés le 27 octobre 2026 (J.4, J.5, J.7) [D]. Formats et mécanismes : [R] ou [O].
1. L’opération `root` vérifie l’assertion (I.3).
2. Elle conserve **d’abord** l’événement signé, c’est-à-dire l’énoncé canonique de marquage et l’assertion, dans une zone protégée par `root` et lisible par `aidirector` (T-3), par une écriture synchronisée.
3. Elle met **ensuite** à jour la politique `root` : la génération g+1 référence l’empreinte de cet événement et est installée par renommage d’un fichier synchronisé. **Cette mise à jour fait entrer l’invalidation en vigueur.** **Exception décidée le 29 octobre 2026 [D] :** après un arrêt brutal de `root` ou une coupure d’alimentation entre le renommage et la synchronisation durable du répertoire, g+1 n’est pas utilisée tant qu’elle n’est pas déclarée effective (L.8, point 8).
4. Le service reporte **enfin** l’événement dans J-b, sous son propre compte, de façon idempotente, selon la barrière γ1 décrite ci-dessous. Il constate une génération non consignée, relit l’événement qu’elle référence, vérifie que son empreinte concorde avec celle inscrite dans la politique, puis écrit l’entrée dérivée : numéro de génération, empreinte du manifeste, empreintes de l’énoncé et de l’assertion. **Réserve (L.8, point 8, décidé le 29 octobre 2026 [D]) :** aucun report pour une génération visible mais non déclarée effective ; le service reste alors fermé et ne l’utilise pas : aucune opération signée, aucune consignation de `c` ni aucun ancrage pour cette génération avant sa déclaration d’effectivité. Si une entrée existe déjà pour cette génération, il n’écrit rien quand elle concorde ; sinon, il signale un incident d’intégrité et refuse pour les clés concernées.

`root` n’ouvre jamais la base, et aucun fichier SQLite ne lui appartient. Parmi les deux pistes de F (« Comment J-b est alimenté »), cette recommandation retient donc l’écriture par le service. La piste du processus enfant n’est pas retenue.

**Barrière de consignation γ1 — décidée le 27 octobre 2026 (J.5 à J.7) [D] ; mise en œuvre [O].** Elle ne modifie ni les règles antérieures ni la portée de D-9.
- **Barrière [D].** Avant d’installer la nouvelle politique, `root` obtient une barrière exclusive qui attend la fin des transactions du service. Le service tient la barrière correspondante depuis la lecture de la politique jusqu’au `COMMIT` SQLite. Aucune transaction vérifiée sous l’ancienne génération ne peut donc se terminer après le changement de politique. L’ordre de prise est décidé (L.2, L.3) [D]. Restent ouverts [O] : le mécanisme de la barrière, les délais d’attente, l’équité envers `root` et la libération après l’arrêt brutal d’un processus. Protocole analysé en L ; la contradiction relevée en L.5 a été tranchée par l’option (d) [D].
- **Consignation [D].**
  - Toute transaction du service qui écrit dans J-b l’entrée d’une opération signée, ou qui valide ou ancre une queue, lit la politique protégée par `root` sous la barrière.
  - Après un changement de politique, la première de ces transactions écrit d’abord `c`, dérivée de l’événement conservé dans la zone `root` (étape 4), **dans la même transaction SQLite**, avant toute autre entrée signée et avant toute validation ou tout ancrage de queue. Elle poursuit ensuite l’opération ou l’ancrage. **Réserve (L.8, point 8, décidé le 29 octobre 2026 [D]) :** cette règle ne s’applique pas à une génération visible mais non déclarée effective ; le service reste alors fermé et ne l’utilise pas : aucune opération signée, aucune consignation de `c` ni aucun ancrage pour cette génération avant sa déclaration d’effectivité.
  - Si plusieurs générations ne sont pas consignées, elles le sont dans l’ordre, chacune par sa propre entrée [R].
- **Ce qui est atomique, et ce qui ne l’est pas.**
  - **L’atomicité ne vaut qu’entre les écritures SQLite d’une même transaction :** `c` et l’entrée de l’opération, ou `c` et les écritures de la validation avant ancrage. Elle repose sur la sémantique transactionnelle de SQLite, sous réserve de sa configuration, que ce document ne vérifie pas.
  - **La lecture de la politique et de la zone `root` reste une opération distincte**, extérieure à la transaction et non atomique avec elle.
  - **La barrière est une coordination extérieure à SQLite**, non atomique avec la transaction. Elle ordonne l’installation de la politique par rapport aux transactions du service ; elle ne rend pas le renommage et le `COMMIT` indivisibles.
  - L’ajout à l’ancre J-c est une écriture externe, qui n’appartient à aucune transaction SQLite.
- **Chronologie, processus qui respectent le protocole [D].**
  - `c` précède toute entrée vérifiée sous la nouvelle génération et suit celles vérifiées sous l’ancienne. L’ordre du journal correspond donc à la génération utilisée.
  - Les autres entrées J-b (voie d’urgence, signaux) ne sont pas soumises à γ1. Elles peuvent précéder `c`, sans effet sur le classement des clés. Leur éventuelle couverture reste ouverte [O].
- **Échecs [D] (J.7).**
  - Si la barrière ou la consignation échoue, l’opération échoue fermée. Pour l’opération `root`, cela signifie qu’aucune génération n’est installée et que le système reste fermé (L.5, décision du 27 octobre 2026).
  - Seuls les échecs propres à la barrière γ1, survenus avant la vérification de l’assertion, laissent le nonce `ISSUED`. Le refus 1b pour politique d’attestation suspendue garde sa règle `FAILED`, et les autres étapes de V0 gardent leur sort de nonce déjà décidé.
  - Un échec de la barrière, une politique inaccessible ou un échec de l’écriture de `c` est un **refus de précondition γ1**. La transaction est annulée et le nonce reste `ISSUED`. Une nouvelle tentative est possible avec le même énoncé avant `expires_at_ms`, et le refus est compté de façon bornée.
  - Une divergence d’intégrité entre la politique et l’événement `root`, détectée par la barrière, est un **incident d’intégrité**, avec refus fermé et S4 maintenu jusqu’à la résolution. Aucune écriture de `FAILED` n’est tentée, et le nonce reste `ISSUED`, sans qu’aucune opération signée soit admise pendant S4 (J.7).
  - Une fois la barrière obtenue, un échec de V0 suit les règles du §5.5.1. Un échec de l’écriture de `FAILED` ne permet jamais un effet.
  - Tant que dure l’impossibilité ou la divergence, les opérations signées et l’ancrage sont refusés, fermetures signées comprises. La voie d’urgence D-9 reste disponible uniquement pour l’interrupteur.
- **`root` n’écrit jamais dans SQLite [D].** Le service exécute γ1 entièrement, sous son propre compte.
- **Ancrage [D].** `c` entre dans la queue avant toute entrée vérifiée sous la nouvelle génération. L’ancrage attend que la génération soit consignée. **Précisé le 1er novembre 2026 [D] (L.6) :** cette règle vise la génération et l’état de D contrôlés sous B lors de la validation de la queue ; l’ajout externe à J-c publie la queue déjà validée. Les fermetures n’attendent pas l’ancre (§11.2).
- **Limite [D] (J.6).**
  - γ1 et la barrière garantissent l’ordre seulement lorsque les processus respectent le protocole.
  - Un compte de service compromis peut contourner la barrière ou réécrire la base avant l’ancrage. Ni la chronologie ni le classement S4 ne sont alors garantis (K.2, K.4).
  - Le refus en V1 des opérations signées par une clé `COMPROMISED`, quelle que soit leur date, est préservé (§5.5.3).

Reprise, selon le point d’interruption :
- **avant l’étape 2 :** rien n’a changé. Le propriétaire recommence avec un défi frais (comme C-1) ;
- **entre les étapes 2 et 3 :** un événement conservé sans génération qui le référence n’a aucun effet. Ce cas couvre aussi l’échec de la barrière exclusive de `root` (J.5). Il n’est jamais reporté dans J-b. Son sort reste ouvert [O] : abandon et nouvelle assertion, ce vers quoi oriente C-1, ou achèvement par une nouvelle invocation `root` qui revérifie l’événement contre une génération inchangée ;
- **entre les étapes 3 et 4 :** g+1 est en vigueur sans être consignée. Ses invalidations valent pour toute lecture de la politique postérieure au renommage, et aucun élément qu’elle ajoute ne sert à accepter ; si g+1 n’a pas été déclarée effective à la suite d’un arrêt brutal de `root` ou d’une coupure d’alimentation avant la synchronisation durable, le service ne l’utilise pas et reste fermé (décidé le 29 octobre 2026 [D] ; L.8, point 8). Avec γ1 et la barrière (J.5), la première transaction visée qui lit g+1 écrit `c` avant toute autre entrée signée et toute validation ou tout ancrage. Une panne dans cet intervalle ne lève pas l’invalidation : l’événement conservé par `root` permet de reprendre la consignation (J.4). Sans γ1, c’est-à-dire avec β seule, les opérations qui ouvrent ne seraient pas refusées si la queue était vide et ancrée au moment du renommage. Une entrée écrite dans l’intervalle précéderait alors `c`, alors qu’elle suit l’entrée en vigueur (**correction** ; conséquences pour V1, `COMPROMISED`, `RETIRED` et S4 en K.2) ;
- **après l’étape 4 :** file d’attente ordinaire jusqu’à l’ancrage (S1, §11.3). L’événement reste conservé dans la zone `root` au moins jusqu’à l’ancrage de son entrée J-b (J.4) ;
- **entrée J-b effacée par un compte de service compromis :** la génération redevient non consignée. L’événement reste dans la zone `root` et peut être reporté de nouveau. Aucune invalidation n’est levée.

**I.5 Marqueur présent seulement en base [R].** Un compte de service compromis peut l’omettre, l’effacer, le réécrire ou le supprimer par restauration. Il ne garantit donc ni la présence ni l’absence d’une invalidation (E). Il sert seulement à refuser plus tôt (option 3). Son origine (opération signée appliquée par le service, ou autre) reste ouverte [O]. **Limite acceptée le 27 octobre 2026 (J.2) [D]**, et maintenue visible.

**Conséquence explicite — décidée le 27 octobre 2026 (J.1, J.4) [D].** L’invalidation de la chaîne prend effet **à la mise à jour de la politique `root`** (I.4, étape 3), **et non au seul `COMMIT` SQLite**. Exception décidée le 29 octobre 2026 [D] : une génération visible mais non déclarée effective, après un arrêt brutal de `root` ou une coupure d’alimentation entre le renommage et la synchronisation durable, n’est pas utilisée (L.8, point 8). Entre la connaissance d’une compromission et cette mise à jour, seul un marqueur en base peut faire refuser, et seulement si les processus restent intègres. La journalisation dans J-b suit l’effet, et l’ancrage vient après. Avec γ1 (J.5), elle intervient au plus tard dans la première transaction visée qui lit la nouvelle génération.

**Éléments maintenus [R] :**
- l’option 3 sert seulement de motif de refus supplémentaire. Elle n’est présentée ni comme une garantie face à un compte de service compromis, ni comme un moyen d’accepter ;
- ne pas retenir l’option 2, ni l’option 1b sans décision explicite sur T-3.

**Non démontré [O],** en plus des points de F (« Non démontré ») :
- le format, l’emplacement, les droits et la durabilité de la zone d’événements ;
- les transactions à couvrir par γ1 au-delà de celles qu’elle nomme (E, voie d’urgence, signaux, démarrage du service), et la résolution d’un écart avec la zone `root` ;
- la lecture fiable de l’état SQLite par `root`, dont la piste α aurait besoin et que γ1 évite sans la résoudre (K.3) ;
- la vérification que le service applique à l’événement avant de le reporter ;
- la conservation des éléments bruts (énoncé, assertion) au-delà de l’ancrage de l’entrée J-b (J.4) ;
- le mécanisme de la barrière : fichier de verrou ou autre, délais, équité envers `root`, libération après un arrêt brutal (J.5). L’ordre de prise est décidé (L.2) ;
- le sort d’un événement conservé sans génération ;
- l’usage éventuel de la même séquence pour consigner la genèse (H, « genèse »).

**Rappel.** Tant que le format du manifeste et la preuve de validité ne sont pas définis, V0 ne peut rien établir et refuse toute opération signée qui ferme (§5.5.1, étape 5). La voie d’urgence D-9 reste distincte et limitée à l’interrupteur ; cette recommandation ne l’étend pas.

##### J. Décisions de portée du 27 octobre 2026 [D] et points restés ouverts [O]

**Décidé par le propriétaire le 27 octobre 2026 [D].** Ces décisions de portée tranchent les questions de H. Elles précisent la recommandation I, y compris la barrière γ1 (I.4). Elles ne modifient aucune décision antérieure : ni la règle des autres fermetures, ni les décisions sur `RETIRED` et `COMPROMISED`, ni les règles de nonce du §14, point 21, ni la portée de D-9. Les détails de mise en œuvre marqués [O] restent ouverts.

1. **Portée du `COMMIT` local [D].**
   - Le `COMMIT` local rend effectives les fermetures ordinaires dans le service intact.
   - Le marquage `COMPROMISED` est une **transition spéciale de la politique d’autorisation**. Il ne prend effet qu’à l’installation de la nouvelle politique protégée par `root`, et non au seul `COMMIT` SQLite.
   - **Cette exception ne change pas la règle des autres fermetures.** Rejet, révocation en base, clôture de nonces et opérations d’urgence restent effectifs au `COMMIT` local (décisions des 26 et 27 octobre 2026 ; §11.2).
   - Répond à H, décision 1, et à la qualification du marquage.
2. **Source faisant autorité [D].**
   - Une invalidation de chaîne compte lorsqu’elle est inscrite dans la politique `root`.
   - Un marqueur SQLite peut provoquer un refus supplémentaire. Il ne peut établir ni une autorisation, ni une invalidation faisant autorité.
   - **Limite acceptée, qui doit rester visible :** un marqueur présent seulement en base peut être effacé par un compte de service compromis (E ; I.5 ; §5.7, « Limite »).
   - Répond à H, décisions 2 et 5.
3. **Authentification du marquage [D].**
   - L’opération `root` contrôlée exige une assertion WebAuthn fraîche, avec UV, signée par un **autre** credential d’administration. Le statut et la chaîne de ce credential doivent être valides dans la politique `root` courante et ne pas dépendre du credential visé.
   - SSH ou `sudo` seuls ne suffisent pas.
   - S’il n’existe aucun autre credential valide, cette voie ne permet pas le marquage. La récupération reste soumise à la procédure distincte du §5.8, encore ouverte.
   - D-9 n’est pas étendue : la voie d’urgence ne permet pas ce marquage (§7.0).
   - Restent [R] ou [O] : l’énoncé canonique de marquage, la production du défi (en mémoire d’une seule invocation `root`, F) et le transfert de l’assertion (F, « Non démontré »).
   - Répond à H, décision 3.
4. **Journalisation et reprise [D].**
   - L’événement signé est conservé durablement dans la zone `root` **avant** la mise à jour de la politique.
   - La politique `root` mise à jour rend l’invalidation effective.
   - Le service inscrit ensuite l’événement dans J-b, sous son propre compte, de façon idempotente. L’ancrage suit.
   - Une panne après la mise à jour ne lève pas l’invalidation : l’événement conservé par `root` permet de reprendre la consignation.
   - **Exception décidée le 29 octobre 2026 [D] :** après un arrêt brutal de `root` ou une coupure d’alimentation entre le renommage et la synchronisation durable du répertoire, la génération visible mais non déclarée effective n’est pas utilisée par le service, qui reste fermé jusqu’à sa déclaration d’effectivité (L.8, point 8).
   - `root` n’écrit jamais dans SQLite.
   - L’événement signé reste conservé au moins jusqu’à l’ancrage de son entrée J-b. La conservation ultérieure des éléments bruts reste ouverte [O].
   - Répond à H, décision 4 : la journalisation suit l’effet, avec une reprise idempotente.
5. **Ordre et barrière γ1 [D].**
   - Pour empêcher qu’une transaction vérifiée sous l’ancienne génération se termine après le changement de politique, `root` obtient une **barrière exclusive** qui attend la fin des transactions du service.
   - Le service tient la barrière correspondante depuis la lecture de la politique jusqu’au `COMMIT` SQLite.
   - Après le changement, la première transaction visée consigne `c` dans la même transaction SQLite, avant toute autre entrée signée et avant toute validation ou tout ancrage de queue. **Réserve (L.8, point 8, décidé le 29 octobre 2026 [D]) :** cette règle ne s’applique pas à une génération visible mais non déclarée effective ; le service reste alors fermé et ne l’utilise pas : aucune opération signée, aucune consignation de `c` ni aucun ancrage pour cette génération avant sa déclaration d’effectivité. **Précisé le 1er novembre 2026 [D] (L.6) :** l’ajout externe à J-c d’une queue validée sous l’ancienne génération publie cette queue déjà validée ; il peut précéder `c` de la nouvelle génération, sans constituer ni l’utilisation de celle-ci, ni un ancrage de ses opérations.
   - Si la barrière ou la consignation échoue, l’opération échoue fermée. Pour l’opération `root`, cela signifie qu’aucune génération n’est installée et que le système reste fermé (L.5, décision du 27 octobre 2026).
   - **La coordination n’est pas atomique avec SQLite.** La barrière est extérieure à SQLite, et la lecture de la politique reste distincte de la transaction. Seules les écritures SQLite d’une même transaction sont atomiques entre elles, sous réserve de la configuration de SQLite, non vérifiée ici.
   - **Mise en œuvre [O] (analyse en L) :** mécanisme de la barrière (fichier de verrou ou autre, propriétaire et droits compatibles avec T-3), délais d’attente, équité envers `root`, libération après l’arrêt brutal d’un processus. L’ordre de prise a été décidé ensuite (L.2, L.3) [D].
   - Répond à K.5, points 1 et 2. Pour des processus qui respectent le protocole, le marquage prend rang dans le journal à `c`, et l’ordre du journal correspond à la génération utilisée.
6. **Limite face à un compte compromis [D].**
   - γ1 et la barrière garantissent l’ordre seulement lorsque les processus respectent le protocole.
   - Un compte de service compromis peut contourner la barrière ou réécrire la base avant l’ancrage. **Ni la chronologie ni le classement S4 ne sont alors garantis.**
   - Le refus en V1 des opérations signées par une clé `COMPROMISED`, quelle que soit leur date, est préservé (§5.5.2, contrôle 4 ; §5.5.3). La limite touche l’ordre et le classement, pas l’acceptation de ces opérations.
   - Les repères qui réduiraient cette limite (K.5, points 3 et 4) restent des options ouvertes, non décidées [O].
7. **Refus γ1 et nonce [D].** **Portée de la règle, précisée le 27 octobre 2026 :** seuls les **échecs propres à la barrière γ1**, survenus avant la vérification de l’assertion, laissent le nonce `ISSUED`. Il s’agit de l’impossibilité d’obtenir la barrière, d’une politique `root` inaccessible, d’une consignation de `c` impossible, ou d’une divergence d’intégrité détectée par cette barrière.
   - **Ce n’est pas une règle générale sur tout refus antérieur à la vérification de l’assertion.** Le refus 1b pour politique d’attestation suspendue survient lui aussi avant cette vérification, mais garde sa règle existante : `FAILED` (§5.5.1 ; §14, point 21). Cette mise à jour est écrite dans la même transaction, après un retour au `SAVEPOINT` (formulation modifiée le 27 octobre 2026, §14, point 24). Les autres étapes de V0 gardent leur sort de nonce déjà décidé.
   - La précondition γ1 est évaluée avant l’étape 1. Si elle échoue, les étapes suivantes ne sont pas évaluées lors de cette tentative. Une nouvelle tentative les évalue chacune avec sa propre règle.
   - **Échec de la barrière, politique `root` inaccessible ou échec de l’écriture de `c`, avant la vérification de l’assertion.**
     - Rollback complet et refus fermé. Le nonce reste `ISSUED`.
     - Après la résolution, le même énoncé signé peut être retenté tant que le nonce n’a pas expiré.
     - Comme le refus 1a, ce refus ne fait pas échouer le nonce. Il est compté de façon bornée (§10.3 ; bornes ouvertes, §14, point 16).
     - L’impossibilité d’obtenir la barrière est un échec propre à la barrière, et relève de cette règle.
   - **Divergence d’intégrité entre la politique `root` et l’événement conservé, détectée par la barrière** : empreinte discordante, événement absent ou différent de celui que la génération référence, ou entrée `c` existante et discordante.
     - Refus fermé, et S4 maintenu jusqu’à la résolution (§11.3).
     - **Aucune écriture séparée de `FAILED` n’est tentée pendant l’incident.** Le nonce reste `ISSUED`, mais aucune opération signée n’est admise pendant S4.
     - Après la résolution, V0 revérifie entièrement l’énoncé et le nonce, qui doit encore être `ISSUED` et non échu. Sinon, il faut un nouveau nonce et une nouvelle assertion.
   - **Barrière obtenue, puis échec de la vérification de l’assertion ou d’une étape normale de V0.** La règle existante s’applique sans changement : rollback, puis sort du nonce selon le §5.5.1. L’étape 1a laisse le nonce `ISSUED`. L’étape 1b et les étapes 2 à 8 le font passer à `FAILED`, par une transition conditionnelle effectuée dans la même transaction après un retour au `SAVEPOINT` (formulation modifiée le 27 octobre 2026, §14, point 24). Le reste de J.7, dont la règle des refus propres à γ1, est inchangé.
   - **Échec de la transaction qui écrit `FAILED`.** Il ne permet jamais un effet : l’opération reste refusée.
   - **Compatibilité.** Ces règles ne modifient ni celles du §14, point 21 (1a, 1b, étapes 2 à 8, arrêts du processus), ni la définition et la conduite de S4 (§11.3), ni la portée de D-9. La précision antérieure, qui faisait passer le nonce à `FAILED` lors d’un incident d’intégrité, est remplacée. La formulation « règle générale », trop large puisqu’elle semblait couvrir le refus 1b, est elle aussi remplacée.
   - Ces refus s’appliquent aussi aux fermetures signées. La voie d’urgence D-9 reste disponible uniquement pour l’interrupteur.
   - **Restent ouverts [O] :**
     - les bornes du comptage ;
     - les modalités techniques de résolution d’un incident d’intégrité γ1 et de sortie de S4 : rapprochement entre la politique, la zone `root` et J-b, au-delà de la conduite S4 existante ;
     - la distinction sûre entre une impossibilité temporaire et une divergence, par exemple une zone `root` partiellement lisible.

**Points restés ouverts [O]**, hors des décisions ci-dessus :
- la zone d’événements `root` : format, emplacement, droits et synchronisation (§9.2), et le sort d’un événement conservé sans génération (I.4) ;
- la couverture par γ1 des autres entrées J-b : E, voie d’urgence, signaux ;
- la lecture fiable de l’état SQLite par `root`, que la décision J.4 évite sans la résoudre ;
- les repères qui réduiraient la limite face à un compte compromis (K.5, points 3 et 4) ;
- le chemin du retrait `RETIRED`, dont dépend l’analyse `RETIRED` de K.2. Les décisions sur `RETIRED` restent inchangées (§5.5.3, §5.7) ;
- la forme du manifeste d’autorisation (C), la relecture de l’ancre par `root` (§14, point 17), la cohérence du manifeste avec J-b et J-c, et la consignation de la genèse (H) ;
- les recommandations [R] du §7.0 (extension de la voie d’urgence) et du §5.7 (pistes de révocation), désormais alignées sur J.3 pour le seul marquage `COMPROMISED`.

##### K. Ordre des écritures de I.4 et chronologie du journal : analyse [R] et points ouverts [O]

**Portée.** Cette analyse a précédé les décisions de portée du 27 octobre 2026, consignées en J. Elle-même ne décide rien et ne modifie aucune règle décidée ; là où une décision l’a suivie, un renvoi l’indique. **Aucune option ci-dessous n’est atomique avec SQLite.** Le renommage d’un fichier `root` et une transaction SQLite restent deux écritures distinctes (F). Seules des entrées J-b écrites dans **une même** transaction SQLite sont atomiques entre elles, par la sémantique transactionnelle de SQLite, sous réserve de sa configuration, que ce document ne vérifie pas.

###### K.1 Règles décidées en jeu [D], rappelées sans changement

- **V1** lit le statut de la clé dans le fichier de confiance au moment où il vérifie (§5.5.2, contrôle 4) :
  - `COMPROMISED` est refusé quelle que soit la date ;
  - `RETIRED` reste vérifiable pour une confirmation antérieure au retrait, au sens de l’ordre du journal. Dans E, les deux entrées doivent être couvertes par l’ancre relue (§5.5.3).
- **Marquage avant l’ancrage.** On compare l’entrée `n` de l’opération à l’entrée `c` du marquage :
  - si `n` précède `c` : ancrage pour l’audit possible, sans effet futur et sans S4 ;
  - si `n` suit `c` : S4.

  L’ordre vient du journal, jamais d’une date SQLite (§5.5.3 ; §11.3).
- **Limite déjà admise.** Si `n` et `c` attendent dans la même queue non ancrée, aucune distinction n’est sûre (§5.5.3). Le moment d’écriture de `c` est déjà un point ouvert du §5.5.3 : `c` ne doit pas être écrite avant que V0 refuse effectivement la clé, et un retard élargit la limite.

###### K.2 Le cas posé : une entrée écrite entre la mise à jour `root` et le report dans J-b

Avec I.4, les écritures se suivent ainsi : zone `root` (étape 2), renommage qui met g+1 en vigueur (étape 3), report de `c` dans J-b (étape 4). Une entrée `n` écrite entre les étapes 3 et 4 précède `c` dans J-b, alors qu’elle a été enregistrée après l’entrée en vigueur.

- **Qui peut écrire `n`.**
  - **Processus intègre.** V0 lit g+1 et refuse toute nouvelle opération de la clé visée `K`, ou d’une clé dont la chaîne dépend de `K`, à une condition [R] : il lit la politique **après** avoir pris le verrou `BEGIN IMMEDIATE`. Sinon, une transaction qui a lu g avant le renommage peut enregistrer une opération de `K` après lui. Une transaction qui a lu g sous le verrou et valide après le renommage a été vérifiée sous g, et sa place avant `c` est cohérente. La barrière décidée le 27 octobre 2026 (J.5) exclut désormais ce cas : `root` attend la fin des transactions du service avant d’installer la politique. Un processus intègre peut aussi enregistrer, dans l’intervalle, des opérations signées par d’autres clés valides ; leur place ne change pas le classement de `K`.
  - **Compte de service compromis.** N’importe quelle entrée : une opération signée par `K` s’il détient `K`, ou une assertion signée et jamais appliquée (§5.5.2, « Limite »).
- **`COMPROMISED` et V1 : aucune acceptation.** V1 lit le statut courant, si bien que `n` échoue en V1 et en E quelle que soit sa place. **Seul le classement est faussé.** `n` précède `c` : elle est classée « enregistrée avant le marquage », donc audit sans S4, alors qu’elle suppose un contournement de V0. Un contournement échappe ainsi à S4.
- **Validation pré-ancrage pendant l’intervalle.**
  - Les entrées de `K` échouent en V1, mais `c` est introuvable. Le classement ne peut pas être établi, cas laissé ouvert au §5.5.3.
  - Si la queue est ancrée sans `c`, ses entrées deviennent « ancrées avant `c` ». Leur classement pour l’audit, sans S4, devient alors définitif (§5.5.3, « Sûr : `n` déjà ancrée avant `c` »).
- **`RETIRED` : l’ordre décide de l’acceptation**, si le retrait suit le même chemin, ce qui n’est pas décidé (§5.7).
  - Une confirmation insérée entre le renommage et l’entrée de retrait `r` précède `r`. Elle est donc « antérieure au retrait » : V1 l’accepte, et E aussi une fois les deux entrées ancrées, ancrage que le service fait lui-même (§5.5.2, « Limite »).
  - Seul un compte de service compromis peut l’insérer, et seulement avec une assertion du propriétaire jamais appliquée, puisque la clé retirée n’est pas réputée compromise.
  - Le §5.5.3 affirme qu’une confirmation insérée après le retrait se place après `r` et échoue. Cette propriété suppose que `r` existe déjà dans J-b, et y soit ancrée, au moment de l’insertion. Avec I.4, `r` n’existe pas avant l’étape 4.
  - Le risque est de la même classe que la limite admise (énoncé signé non appliqué). Sa fenêtre s’ouvre au renommage au lieu de l’écriture de `r`.
- **Opérations qui ouvrent pendant l’intervalle : correction.** F et I.4 affirmaient qu’elles restent refusées parce que la queue n’est ni vide ni ancrée. **C’est inexact avant l’étape 4.** Si la queue était vide et ancrée au moment du renommage, rien ne la remplit avant `c`. Une opération qui ouvre, signée par une autre clé valide, peut alors être acceptée sous g+1 et précéder `c`.
  - Elle ne s’appuie sur aucun élément ajouté par g+1, et son classement n’est pas en cause.
  - La correction porte sur l’affirmation de F et de I.4. Ce n’est pas un nouveau défaut d’acceptation.
- **Opérations qui ferment signées par `K` pendant l’intervalle.** Un V0 intègre les refuse. Une entrée de contournement n’a qu’un effet de fermeture, qu’un compte de service compromis obtient déjà sans signature (A). La validation pré-ancrage n’examine que les opérations qui ouvrent (§11.3, étape 2), et le classement d’une telle entrée n’est pas défini [O].

###### K.3 Ordres possibles

**Option α — J-b d’abord, vérification par `root`, puis politique.**
1. Le service applique le marquage comme une opération signée. V0 vérifie l’assertion de l’autre credential, puis écrit `c` et le marqueur de refus (option 3) dans **une même** transaction SQLite. Ces deux écritures sont atomiques entre elles, mais pas avec la politique.
2. Une copie de `c` (énoncé, assertion, contenu de l’entrée) est déposée là où `root` peut la lire : soit le service la dépose, soit le propriétaire la transmet dans sa session [O].
3. `root` traite cette copie comme une entrée non fiable :
   - il vérifie l’assertion contre la génération g et la génération liée par l’énoncé ;
   - il recalcule l’`entry_hash` de `c` à partir du contenu fourni ;
   - il n’ouvre pas la base [R]. Une lecture d’une base en mode WAL peut exiger d’écrire le fichier `-shm`, ce qui n’est pas vérifié [O].
4. `root` installe g+1, qui référence l’`entry_hash` de `c`. La désignation de `c` devient fiable, ce qui répond à un point ouvert du §5.5.3. La position de `c` reste attestée par la seule chaîne locale tant qu’elle n’est pas ancrée.

Analyse de l’option α :
- **Chronologie, processus intègres.** Le marqueur fait refuser `K` par toute transaction qui suit le `COMMIT` de `c`, du fait de `BEGIN IMMEDIATE`. Aucune entrée légitime de `K` ne suit donc `c`. L’ordre du journal coïncide avec le **refus local**, sans faux S4. Le risque noté au §5.5.3 (`c` écrite avant que V0 refuse) disparaît, puisque `c` porte elle-même le refus.
- **Pannes.**
  - Avant l’étape 1 : rien.
  - Entre les étapes 1 et 4 : `c` est consignée et le refus local est actif. L’invalidation n’est pas autoritative : `K` reste valide dans la politique. Une nouvelle invocation `root` peut achever le marquage en revérifiant `c`, tant que la génération est encore g [R]. Le sort d’une copie arrivée après un changement de génération reste ouvert [O].
  - **Tension avec C-1.** Le défi provient du nonce du service, et non de la mémoire d’une invocation `root`. La fraîcheur repose donc sur la base, et la liaison à la génération ne suffit qu’à empêcher une application dans une autre génération [O].
- **Ancrage.** `c` peut être ancrée avant même l’entrée en vigueur autoritative. Une fois `c` ancrée et relue, toute entrée ultérieure est classée sûrement (§5.5.3, « Sûr »). C’est l’ordre qui ouvre la fenêtre la plus courte.
- **Compte de service compromis.**
  - Il peut ne pas écrire `c`, l’effacer avant le dépôt, ou ne pas la déposer. `root` n’a alors rien à inscrire : **l’invalidation autoritative dépend de la coopération du compte de service**, faiblesse de l’option 1b que I.2 cherche à éviter.
  - Il ne peut pas forger `c`, puisque `root` vérifie l’assertion d’un autre credential valide.
  - Il peut rejouer un marquage signé et non appliqué. L’effet est une fermeture, bornée par la liaison à la génération.
  - Après le renommage, s’il efface `c`, la politique désigne une entrée absente : la divergence est détectable (S4, « entrée … disparue », §11.3).
  - Il peut réordonner la queue tant que `c` n’est pas ancrée.
- **Variante α′.** Si `c` n’est pas déposée, `root` inscrit quand même l’invalidation à partir de l’assertion du propriétaire qu’il détient. C’est un retour à β, réservé au cas où le service ne coopère pas. Aucun délai n’est fixé [O]. Si le service est simplement arrêté, aucune entrée n’est écrite pendant l’arrêt, et au redémarrage la barrière de γ consigne d’abord.
- **Compatibilité.** C’est l’ordre le plus proche des décisions actuelles : l’effet local survient au `COMMIT` et la journalisation est atomique avec lui. Il n’atteint pas l’objectif de I.2 sans α′.

**Option β — politique `root` d’abord (I.4 actuelle).**
- **Pannes :** celles de I.4.
- **Écriture de SQLite par `root` :** aucune.
- **Chronologie, processus intègres : non garantie sans règle supplémentaire.** Les écarts de K.2 subsistent :
  - validation pré-ancrage sans `c` ;
  - queue ancrée sans `c` ;
  - opérations qui ouvrent acceptées avant `c` ;
  - rang de `c` indéfini (« prochaine vérification »).
- **Ancrage :** `c` n’est ancrable qu’après l’étape 4. La fenêtre de K.2 s’allonge de l’intervalle entre les étapes 3 et 4.
- **Compte de service compromis.**
  - Il ne peut ni empêcher ni effacer l’invalidation autoritative, puisque la zone `root` et la politique lui échappent. C’est l’avantage de β.
  - Il peut retarder `c` indéfiniment, écrire des entrées avant `c`, ancrer une queue sans `c`, ou effacer `c`. Un nouveau report depuis la zone `root` reste possible.
  - Le classement S4 n’est pas fiable, et la fenêtre `RETIRED` de K.2 reste ouverte.

**Option γ — β avec une barrière de consignation.** Règle envisagée [R] : toute transaction du service qui écrit dans J-b l’entrée d’une opération signée, ou qui valide ou ancre une queue, lit la politique `root` après avoir pris le verrou. Si la génération en vigueur n’est pas consignée :
- **γ1 :** elle écrit d’abord `c` dans la même transaction, d’après la zone `root` (I.4, étape 4), puis poursuit ;
- **γ2 :** elle refuse, et une étape dédiée consigne `c`.

**γ1, complétée par une barrière exclusive prise par `root`, a été retenue par le propriétaire le 27 octobre 2026 (J.5 à J.7) [D].** L’analyse ci-dessous a précédé cette décision. γ2 reste une variante examinée, non retenue : elle bloque plus longtemps sans meilleure garantie.

Analyse de l’option γ :
- **Chronologie, processus intègres.**
  - `c` précède toute entrée vérifiée sous g+1, et suit toute entrée vérifiée sous g. L’ordre du journal coïncide alors avec la génération sous laquelle chaque entrée a été vérifiée.
  - Il n’y a ni faux S4, ni queue ancrée sans `c`, ni opération qui ouvre placée avant `c`. Pour la queue ancrée, cela vaut à l’instant de la validation : son ajout externe à J-c peut précéder `c` (L.6, décidé le 1er novembre 2026 [D]).
  - Des entrées non signées (urgence, signaux) peuvent précéder `c`, sans effet sur le classement des clés.
- **Pannes.**
  - Si la consignation échoue, la transaction est annulée et l’opération refusée : l’échec reste fermé.
  - Si la zone `root` est illisible, ou si son empreinte ne concorde pas, toute opération signée et tout ancrage sont refusés, fermetures signées comprises, tant que l’écart dure. C’est un déni de service ; la voie d’urgence D-9 reste disponible pour l’interrupteur.
  - Avec γ2, le blocage dure en outre jusqu’à l’étape dédiée.
- **Écriture de SQLite par `root` :** aucune.
- **Ancrage :** `c` entre dans la queue avant toute entrée vérifiée sous g+1. L’ancrage attend que g+1 soit consignée. Les fermetures n’attendent pas l’ancre, et ne sont donc pas ralenties.
- **Compte de service compromis.** La barrière fait partie du code, qui appartient à `root` (T-3), mais une écriture directe en base la contourne. Le compte a donc les mêmes capacités qu’avec β : γ ne protège la chronologie que pour des processus intègres.
- **Compatibilité.** γ ajoute un motif de refus des fermetures signées, l’échec de la consignation, alors que leur validité pourrait être établie d’après la seule politique. Ce motif a été tranché le 27 octobre 2026 (J.7) [D] : refus de précondition γ1 en cas d’impossibilité temporaire, incident d’intégrité en cas de divergence.

| | Chronologie, processus intègres | Compte de service compromis | Pannes | `root` et SQLite | Ancrage |
|---|---|---|---|---|---|
| α | Préservée par rapport au refus local | Peut **empêcher** l’invalidation autoritative ; ne peut pas forger `c` ; peut réordonner la queue non ancrée | `c` sans politique : refus local, achèvement par `root` | `root` n’écrit pas ; lecture par copie non fiable | `c` ancrable au plus tôt |
| α′ | Comme α | Comme β en l’absence de coopération | Comme α, puis comme β | Idem | Comme α, sinon comme β |
| β | **Non garantie** (K.2) | Ne peut pas empêcher l’invalidation ; peut placer des entrées avant `c`, ancrer sans `c` | Celles de I.4 | `root` n’écrit pas | `c` ancrable seulement après report |
| γ1 avec barrière (décidée le 27 octobre 2026, J.5 à J.7) | Préservée pour des processus qui respectent le protocole : aucune transaction vérifiée sous l’ancienne génération ne se termine après le changement. Atomicité limitée aux écritures SQLite d’une même transaction ; barrière et lecture de la politique restent distinctes | Comme β : ni chronologie ni S4 garantis avant l’ancrage (J.6) ; refus en V1 de `COMPROMISED` préservé | Échec fermé. Échec propre à la barrière avant la vérification de l’assertion : nonce `ISSUED`. Refus 1b : règle existante `FAILED`, écrit dans la même transaction après un retour au `SAVEPOINT` (§14, point 24). Autres étapes de V0 : sort de nonce déjà décidé. Impossibilité temporaire : rollback, nonce `ISSUED`. Divergence : S4 jusqu’à la résolution, nonce `ISSUED`, aucune opération signée. D-9 limitée à l’interrupteur | `root` n’écrit pas | `c` avant toute entrée de la nouvelle génération ; ancrage après consignation ; fermetures sans attente de l’ancre |
| γ2 (non retenue) | Comme γ1 | Comme β | Comme γ1, et blocage jusqu’à l’étape dédiée | `root` n’écrit pas | Comme γ1 |

###### K.4 Ce qu’aucun ordre ne donne

- **Aucune atomicité** entre le renommage et une transaction SQLite, quel que soit l’ordre.
- **Face à un compte de service compromis, aucun ordre ne préserve la chronologie avant l’ancrage.** Le compte écrit la chaîne, et son calcul ne demande aucun secret (§5.5.2). Il peut donc placer une entrée avant `c` ou `r` tant que celle-ci n’est pas ancrée. Les options se distinguent seulement par la largeur de la fenêtre :
  - α la raccourcit, puisque `c` est ancrable avant l’entrée en vigueur ;
  - β l’allonge ;
  - γ ne la change pas face à un compte compromis, barrière décidée comprise (J.6).
- **Une valeur signée peut prouver qu’une signature est postérieure à un événement, jamais qu’elle lui est antérieure.** Il suffit pour la première preuve de lier une valeur imprévisible avant l’événement, comme le fait déjà la liaison à l’autorisation effective (§5.3). Seule une ancre externe, ou un repère tiré d’une ancre relue, peut établir l’antériorité. De plus, le détenteur de `K` ne lierait pas volontairement une valeur qui le désigne.

###### K.5 Règles ou repères pour préserver la chronologie : décidés [D] et ouverts [O]

Les points 1 et 2 ont été tranchés le 27 octobre 2026 (J.5) [D]. Les points 3 et 4 restent ouverts [O]. J.6 constate la limite du point 5.
1. **Rang d’un changement de statut inscrit par `root`.** Il faudrait décider que, pour l’ordre du journal (S4, antériorité au retrait), le changement prend rang à l’entrée `c` qui le consigne, et non au renommage. **Avec une barrière érigée en règle**, ce rang donne la chronologie exigée pour des processus intègres. **Tranché le 27 octobre 2026 (J.5) [D] :** γ1, complétée par une barrière exclusive prise par `root`. Le marquage prend rang à `c`. Sans barrière, ce rang n’est pas cohérent, même pour des processus intègres (K.2).
2. **Lecture de la politique sous le verrou [R], condition du point 1.** V0 et la validation pré-ancrage lisent la politique `root` après avoir pris le verrou `BEGIN IMMEDIATE`, jamais avant. Cette exigence fait partie de γ1. **Décidé le 27 octobre 2026 sous une forme plus forte (J.5) [D] :** le service tient la barrière de la lecture de la politique jusqu’au `COMMIT` SQLite.
3. **Repère inscrit par `root` d’après une ancre qu’il relit lui-même. Non décidé [O].** `root` inscrirait dans g+1 la tête `H_root` lue dans J-c. Toute entrée couverte par `H_root` serait sûrement antérieure, même face à un compte de service compromis. Cela suppose que l’opération `root` relise l’ancre (§14, point 17), sous les contraintes de T-2 sur l’accès réseau (§14, point 15). Il faudrait aussi une règle pour les entrées situées entre `H_root` et `c` :
   - **`COMPROMISED` :** elles n’ont d’effet dans aucun cas. Reste à choisir leur classement : S4, audit, ou une classe distincte ;
   - **`RETIRED` :** les refuser **modifierait la règle décidée**, selon laquelle les confirmations antérieures au retrait, au sens de l’ordre du journal, restent vérifiables. Il faudrait une décision du propriétaire. Les accepter revient à accepter la limite.
4. **Repère signé de postériorité, facultatif. Non décidé [O].** L’énoncé lierait la génération de la politique, ou l’empreinte du manifeste, au moment du `prepare`, et V0 refuserait toute discordance.
   - Une entrée de `K` qui lie g+1 ou une génération ultérieure relèverait sûrement de S4.
   - Ce repère ne prouve aucune antériorité et ne gêne pas le détenteur de `K`, qui lierait l’ancienne génération.
   - Il impose un nouveau nonce à chaque changement de génération.
   - Ce champ n’est pas décidé (§5.3).
5. **Limite, constatée par la décision J.6 [D] sans choix entre les points 3 et 4 :** la chronologie n’est alors préservée que pour des processus intègres, et pour les entrées dont `c` ou `r` est déjà ancrée, comme le §5.5.3 l’admet déjà pour une même queue. Avec β ou γ, la fenêtre s’ouvre au renommage.

Le chemin du retrait (`RETIRED`) n’est pas décidé. L’analyse `RETIRED` de K.2 ne vaut que s’il suit le même ordre (§5.7) [O].

###### K.6 Bilan

- **β seule ne préserve pas la chronologie, même avec des processus intègres** (analyse [R]).
- **Décidé le 27 octobre 2026 (J.4 à J.7) [D] :** l’ordre β, complété par γ1 et par une barrière exclusive prise par `root`.
  - Pour des processus qui respectent le protocole, aucune transaction vérifiée sous l’ancienne génération ne se termine après le changement, et l’ordre du journal correspond à la génération utilisée.
  - `root` n’écrit pas dans SQLite, et l’invalidation ne dépend pas de la consignation par le service. **Correction :** un processus du service qui retient la barrière peut retarder l’installation de la politique. Depuis la décision du 27 octobre 2026 (option d, L.5), ce retard est borné : après le délai, `root` arrête le service. Si l’arrêt échoue, rien n’est installé et le système reste fermé.
- **Atomicité.** Elle ne vaut qu’entre les écritures SQLite d’une même transaction. La barrière et la lecture de la politique `root` restent des opérations distinctes, non atomiques avec SQLite.
- **Prix.** Les opérations signées et l’ancrage sont refusés tant que la politique ne peut pas être lue ou que `c` ne peut pas être consignée (refus de précondition γ1, nonce `ISSUED`), ou en cas de divergence (S4 maintenu jusqu’à la résolution, sans écriture de `FAILED`). D-9 reste limitée à l’interrupteur.
- **α** préserve la chronologie pour des processus intègres et raccourcit la fenêtre d’ancrage, mais fait dépendre l’invalidation autoritative du compte de service. Elle est écartée par J.4 : l’événement est conservé par `root` et la politique mise à jour avant l’inscription dans J-b.
- **Face à un compte de service compromis, aucun ordre ne suffit avant l’ancrage, barrière comprise (J.6).** Le refus en V1 des opérations signées par une clé `COMPROMISED`, quelle que soit leur date, est préservé. Les repères 3 et 4 de K.5 restent ouverts.

##### L. Protocole de coordination de la barrière γ1 : analyse [R] et points ouverts [O]

**Portée.** Cette sous-section analyse la mise en œuvre de J.5 et J.7. Les décisions prises ensuite par le propriétaire, le 27 octobre 2026, y sont signalées [D] (L.2, L.3, L.4, L.5, L.8). Le reste est une analyse [R], des hypothèses [H] ou des points ouverts [O]. L’ensemble ne modifie aucune règle décidée antérieurement : ni le `COMMIT` local des fermetures ordinaires, ni les règles de nonce (§5.5.1 ; §14, point 21 ; J.7), ni S4, ni la portée de D-9. **La barrière ordonne les écritures ; elle ne rend pas atomiques le renommage de la politique et une transaction SQLite** (J.5). Les mécanismes système cités (`flock`, `fsync`, récupération SQLite) sont des hypothèses [H], non vérifiées sur le serveur.

###### L.1 Objets en jeu

- **P**, la politique protégée par `root`. Elle est remplacée par renommage : chaque génération est un nouveau fichier.
- **Z**, la zone d’événements protégée par `root` (J.4).
- **B**, le fichier de barrière. Il appartient à `root`, est lisible par `aidirector` et n’est jamais remplacé [R]. **La barrière ne doit pas porter sur P lui-même :** le renommage remplace le fichier, et un verrou pris sur l’ancien ne protégerait rien.
- **G**, un fichier de porte. Il appartient à `root` et est lisible par `aidirector` [R]. Il empêche que des transactions du service, en se succédant sans interruption, privent `root` de la barrière exclusive (famine).
- **M**, un verrou réservé à `root` [R]. Il sérialise deux opérations `root` concurrentes.
- **W**, un verrou exclusif qui sérialise les transactions couvertes du service, V0 et E, pris avant G (décidé le 28 octobre 2026 [D] ; L.2). Son support est un fichier stable détenu par `root`, jamais supprimé ni remplacé, que le service peut ouvrir et prendre en verrou exclusif sans pouvoir le modifier (décidé le même jour [D]). Son mécanisme, son équité, ses délais, l’emplacement et les modes exacts de son fichier restent ouverts [O]. Sa libération à la fin du processus est une hypothèse à vérifier [H], comme pour B et G (ci-dessous).
- **La base SQLite**, avec le verrou d’écriture pris par `BEGIN IMMEDIATE`.
- **Les marqueurs du gel**, un fichier persistant hors de SQLite par transaction couverte (décidé le 28 octobre 2026 [D] ; §5.5.1, cas 3, « Mécanisme du marqueur »). Leur place dans L.2 a été fixée le même jour [D]. Ils sont placés dans un sous-répertoire persistant du compte de service, dans l’arborescence des données, hors des arborescences `root` et du code (décidé le même jour [D]) ; leur emplacement et leurs modes exacts restent ouverts [O].

Hypothèse de mécanisme [H] : des verrous consultatifs `flock`, partagés ou exclusifs. Le noyau les libère à la fermeture du dernier descripteur, y compris à la mort du processus. Les descripteurs ne sont pas hérités par les processus enfants (`O_CLOEXEC`), et les fichiers résident sur un système de fichiers local. Ces points restent à vérifier [O].

###### L.2 Séquence d’une transaction du service visée par γ1 : ordre de prise décidé [D], détails [R]

L’assertion est déjà en main avant S1. Entre S2 et S8, aucune interaction humaine ni aucune entrée-sortie réseau n’a lieu.

**Avant S1, pour une transaction couverte — décidé le 28 octobre 2026 [D].** Prendre W, puis examiner sous W les marqueurs existants (« Verrou W et marqueur du gel », ci-dessous). Pour une opération qui ouvre, un marqueur résiduel entraîne un refus sans écriture. La numérotation S1 à S8 est inchangée.

1. **S1.** Prendre G en partagé, avec le délai `T_barrière_service`. En cas d’échec : refus de précondition γ1, nonce `ISSUED` (J.7).
2. **S2.** Prendre B en partagé, avec le même délai, puis relâcher G.
3. **S3.** `BEGIN IMMEDIATE`, avec le délai d’occupation SQLite, puis `SAVEPOINT` avant toute écriture de l’opération [D] (§14, point 24). En cas d’échec, rien n’est écrit et aucune étape de V0 n’a été évaluée : le nonce reste `ISSUED`. La qualification de ce refus reste ouverte [O]. **Pour une transaction couverte — décidé le 28 octobre 2026 [D] :** après le `SAVEPOINT`, créer le marqueur, avant S4. Si la synchronisation du marqueur ou de son répertoire échoue avant toute écriture SQLite, la transaction n’exécute aucune écriture de base et suit la conduite de refus prévue (précisé le même jour [D]). Elle ne retire aucun marqueur d’une autre transaction. Pour son propre marqueur, la règle de retrait décidée s’applique : après un `ROLLBACK` complet réussi, le service peut tenter de le retirer. **Précisé le même jour [D] :** la transaction se termine par un `ROLLBACK` complet avant de poursuivre ; si ce `ROLLBACK` échoue ou si son issue ne peut pas être établie, aucun `COMMIT` ne suit et le service applique la règle fail-stop propre à ce cas, plus stricte que la règle générale du §5.5.1, cas 2, point 2 : tout échec de ce `ROLLBACK`, même si `in_transaction` est faux et que l’annulation pourrait être déduite selon cette règle générale, met fin au processus sans autre instruction, comme au cas 2, point 3. Le marqueur est laissé en place s’il est présent, et la règle générale du point 2 reste applicable aux autres erreurs. Refus et nonce : échec technique fermé, nonce inchangé, sans incrément du compteur des tentatives ni du compteur borné du §10.3, ni nouvelle tentative automatique (décidé le même jour [D] ; §5.5.1, cas 3, « Mécanisme du marqueur »). Après le `ROLLBACK` complet réussi, le refus porte le code technique de ce cas et son qualificatif sur le retrait du marqueur, à trois valeurs (§5.5.1, cas 3, « Mécanisme du marqueur » ; §10.2) ; en cas de fail-stop, aucun code ni message du protocole n’est émis et le processus se termine avec, pour seul signal, le statut de sortie dédié au fail-stop (`EXIT_FAIL_STOP`) (§5.5.1, « Signalement du fail-stop »). Si `BEGIN IMMEDIATE` échoue, aucun marqueur n’existe encore.
4. **S4.** Lire P. En cas d’échec : refus de précondition γ1, `ROLLBACK`, nonce `ISSUED`. **Principe O1-B — décidé le 1er novembre 2026 [D], sous condition [H] (L.8, point 8) :** pour chaque opération concernée, le service vérifie sous B l’état courant de D, et il n’utilise g+1 que si D est alors confirmée et concorde avec P. Une lecture antérieure ne suffit pas : si D est ensuite absente, non confirmée, illisible ou discordante, le système reste fermé pour cette génération. États de refus et sort du nonce [O].
5. **S5.** Comparer la génération de P à la dernière génération consignée dans J-b :
   - **égale :** contrôler que l’entrée `c` correspondante concorde avec P [R] ;
   - **supérieure :** pour chaque génération non consignée, dans l’ordre, lire l’événement dans Z, vérifier son empreinte et écrire `c`. **Réserve (L.8, point 8, décidé le 29 octobre 2026 [D]) :** pas pour une génération visible mais non déclarée effective ; le service reste alors fermé et ne l’utilise pas : aucune opération signée, aucune consignation de `c` ni aucun ancrage pour cette génération avant sa déclaration d’effectivité. Une lecture impossible est un refus de précondition γ1. Une discordance mène à l’état S4 (§11.3, « Divergence γ1 »), sans écriture de `FAILED` (J.7) ;
   - **inférieure :** la politique est revenue en arrière. C’est un incident d’intégrité ; son rattachement à J.7 et à l’état S4 reste ouvert [O].
6. **S6.** V0, étapes 1 à 8, ou validation avant ancrage. En cas d’échec, le sort du nonce suit le §5.5.1 :
   - **étape 1a :** `ROLLBACK` complet, qui annule aussi `c`. Le nonce reste `ISSUED` ;
   - **étape 1b et étapes 2 à 8 :** retour au `SAVEPOINT`, qui annule les écritures de l’opération, `c` comprise. Puis, dans la même transaction et sous B, transition conditionnelle `ISSUED` → `FAILED` et `COMMIT` [D] (§14, point 24) ;
   - si la transition ou le `COMMIT` échoue après un retour au `SAVEPOINT` réussi, l’effet de l’opération, `c` comprise, est annulé, et seul le sort du nonce est incertain [O]. Si le retour au `SAVEPOINT` ou l’annulation complète échoue, aucun `COMMIT` ne suit [D], et l’absence d’effet n’est affirmée qu’une fois l’annulation établie, ou déduite sous les conditions du §5.5.1 (« Erreurs SQLite dans la transaction de V0 », cas 1 et 2).
7. **S7.** Écritures de l’étape 9, puis `COMMIT` (étape 10). Une erreur de ce `COMMIT` n’est pas un refus. L’issue est à constater, sans nouvelle tentative automatique [D]. B reste tenue jusqu’à la résolution de la transaction sur la connexion (§5.5.1, cas 3, points a à c).
8. **S8.** Relâcher B après le `COMMIT` ou le `ROLLBACK` complet de la transaction externe, jamais après le seul retour au `SAVEPOINT` [D]. Le descripteur est fermé [R]. Si l’annulation n’est ni établie ni déduite, B n’est libérée que par la fin du processus [R ; H] (§5.5.1, cas 2). **Pour une transaction couverte — décidé le 28 octobre 2026 [D] :** après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi, le service peut tenter de retirer son propre marqueur, puis il relâche B, puis W, même si ce retrait a échoué. Si l’issue du `COMMIT` est indéterminée, il ne tente pas le retrait ; une fois la transaction inactive sur la connexion, il relâche B puis W et laisse le marqueur en place. Si la transaction reste non résolue, le processus se termine sans autre instruction ; la libération de B et de W à sa fin reste une hypothèse [H].

**Ordre de prise — décidé le 27 octobre 2026 [D].**
- Le service prend G en partagé, puis B en partagé, relâche G, puis exécute `BEGIN IMMEDIATE`.
- Il lit la politique `root` après l’obtention de B. Dans cette séquence, la lecture a lieu après `BEGIN IMMEDIATE`, ce qui respecte aussi K.5, point 2.
- Il garde B jusqu’au `COMMIT` ou au `ROLLBACK`, puis la relâche. Il s’agit du `COMMIT` ou du `ROLLBACK` complet de la transaction externe, jamais du seul retour au `SAVEPOINT` (précisé le 27 octobre 2026, §14, point 24).
- La barrière est donc toujours prise avant SQLite, jamais l’inverse.
- **Complété le 28 octobre 2026 [D] :** les transactions couvertes, V0 et E, prennent W avant G et le gardent jusqu’à la résolution de la transaction et, le cas échéant, jusqu’à la tentative de retrait de leur marqueur (précisé le même jour). L’ordre ci-dessus suit sans changement (« Verrou W et marqueur du gel », ci-dessous).

Les délais d’attente restent ouverts [O].

**Verrou W et marqueur du gel — décidés le 28 octobre 2026 [D]** (§5.5.1, cas 3, « Mécanisme du marqueur »).
- **W.** Verrou exclusif qui sérialise les transactions couvertes, V0 et E. Elles le prennent avant G.
- **Examen des marqueurs.** Sous W, la transaction examine les marqueurs existants. Pour E et les opérations qui ouvrent, un marqueur résiduel entraîne un refus sans écriture ; la qualification du refus et le sort du nonce restent ouverts [O]. La conduite d’une opération signée qui ferme dans ce cas n’est pas tranchée [O].
- **Ordre ensuite.** Inchangé : G en partagé, B en partagé, relâchement de G, puis `BEGIN IMMEDIATE` (S1 à S3 ; E2).
- **Création du marqueur.** Chaque transaction couverte a son propre marqueur. Pour V0, il est créé après le `SAVEPOINT` de S3, avant toute écriture de la transaction, donc avant S4 et S5 et toute consignation de `c`. Pour E, il est créé après le `BEGIN IMMEDIATE` de E2, avant toute écriture, donc avant E3 à E6.
- **Durée de W.** W est gardé pendant la transaction, jusqu’à sa résolution sur la connexion et, le cas échéant, jusqu’à la tentative de retrait du marqueur (précisé le même jour). Le service ne tente ce retrait qu’après le `COMMIT` confirmé ou le `ROLLBACK` complet réussi de la transaction externe, jamais après le seul retour au `SAVEPOINT` (S6).
- **Rôle de W — précisé le même jour [D].** W est un verrou de sérialisation, pas le support persistant du gel : le marqueur restant porte le gel.
- **Fin — précisée le même jour [D].** Une fois la transaction résolue sur la connexion, le service relâche B, puis W, même si le marqueur n’a pas pu être retiré. Si le retrait tenté échoue et que le marqueur reste présent, il ne prétend pas que le gel est levé et ne retire aucun autre marqueur ; le marqueur résiduel maintient le gel, sans nettoyage automatique. Si la suppression est visible mais que la synchronisation du répertoire échoue ou reste incertaine, l’issue SQLite reste établie : le service signale que la durabilité du retrait n’est pas établie, sans la présenter comme une levée explicite par `root`. Cette suppression ne maintient pas, à elle seule, le gel pendant que le système tourne (les autres marqueurs résiduels, s’il y en a, continuent de le maintenir et de provoquer les refus prévus), mais le marqueur peut réapparaître après une coupure ou un redémarrage (précisé le même jour, §5.5.1, cas 3, « Mécanisme du marqueur »). Si l’issue du `COMMIT` est indéterminée, il ne tente pas le retrait ; une fois la transaction inactive, il relâche B puis W et laisse le marqueur en place jusqu’à la récupération et à la levée explicites par `root`. Si la transaction reste non résolue, le processus se termine sans autre instruction (fail-stop), sans code ni message du protocole, avec pour seul signal le statut de sortie dédié `EXIT_FAIL_STOP` (§5.5.1, « Signalement du fail-stop »). Contrairement à B, le marqueur n’est donc pas retiré au point c du §5.5.1, cas 3.
- **Hypothèse à vérifier [H] :** la libération de W à la fin du processus (L.1).
- **Limite.** W ne protège pas contre un compte de service compromis, qui peut le retenir ou l’ignorer (L.4, « Limites » ; J.6). Il n’empêche pas un processus du compte de service de supprimer le marqueur d’un autre.
- **Restent ouverts [O] :** le mécanisme et l’équité de W ; ses délais ; l’échec de création, hors l’échec de synchronisation réglé le 28 octobre 2026 [D] ; les détails techniques du retrait et de sa durabilité, hors le cas d’une suppression visible non durable réglé le même jour [D] ; la conduite si l’état ou la présence du marqueur ne peut pas être établi ; l’ordre de la tentative de retrait par rapport à `close()` ; la participation éventuelle à W de la validation avant ancrage et de D-9, dont l’application du gel reste à préciser.

**Séquence du contrôle E.** La couverture et les refus ont été décidés le 27 octobre 2026 [D]. L’ordre détaillé des étapes reste [R].
1. **E1.** Hors barrière, relire l’ancre J-c, ce qui est une lecture réseau [D]. Lire P et relever la génération vérifiée, g_v [R].
2. **E2.** Prendre G puis B en partagé, relâcher G, puis `BEGIN IMMEDIATE`, dans le même ordre que le service [D]. **Complété le 28 octobre 2026 [D] :** auparavant, prendre W et examiner sous W les marqueurs existants ; un marqueur résiduel entraîne un refus sans écriture. Après `BEGIN IMMEDIATE`, créer le marqueur d’E, avant E3. Si sa synchronisation ou celle de son répertoire échoue avant toute écriture SQLite, E n’exécute aucune écriture de base et refuse (précisé le même jour [D]). Il ne retire aucun marqueur d’une autre transaction ; pour son propre marqueur, la même règle de retrait s’applique. **Précisé le même jour [D] :** E termine alors la transaction par un `ROLLBACK` complet ; si ce `ROLLBACK` échoue ou si son issue ne peut pas être établie, aucun `COMMIT` ne suit et la règle fail-stop propre à ce cas s’applique, plus stricte que la règle générale du §5.5.1, cas 2, point 2 : même si `in_transaction` est faux, le processus se termine sans autre instruction, le marqueur restant en place s’il est présent. Le refus est un échec technique fermé, sans incrément du compteur des tentatives ni du compteur borné du §10.3, ni nouvelle tentative automatique ; E ne modifie pas le nonce (décidé le même jour [D] ; §5.5.1, cas 3, « Mécanisme du marqueur »). Le même code technique, commun à V0 et E, est émis après le `ROLLBACK` complet réussi, avec son qualificatif à trois valeurs ; en cas de fail-stop, aucun code ni message du protocole n’est émis et le processus se termine avec, pour seul signal, le statut de sortie dédié au fail-stop (`EXIT_FAIL_STOP`) (§10.2 ; §5.5.1, « Signalement du fail-stop »).
3. **E3.** Sous B, revérifier la génération `root` en relisant P : c’est la génération courante, g_c [D]. **Principe O1-B — décidé le 1er novembre 2026 [D], sous condition [H] (L.8, point 8) :** pour chaque opération concernée, E vérifie sous B l’état courant de D, et il n’utilise g+1 que si D est alors confirmée et concorde avec P. Une lecture antérieure ne suffit pas : si D est ensuite absente, non confirmée, illisible ou discordante, le système reste fermé pour cette génération. États de refus [O].
4. **E4.** Refuser si g_c diffère de g_v, ou si l’ancre relue ne couvre pas la génération courante [D]. **Sens précisé le 27 octobre 2026 [D] :** l’entrée `c` qui consigne la génération courante est incluse dans la tête J-c qu’E vient de relire. E refuse si ce n’est pas le cas. La règle vaut aussi pour la génération initiale : aucune autorisation E avant que son entrée soit consignée et ancrée.
5. **E5.** Exécuter sous g_c les contrôles existants d’E : V1, politique d’attestation, suspension (§11.2).
6. **E6.** Enregistrer localement la décision d’autorisation, puis `COMMIT`. La barrière couvre E jusqu’à cet enregistrement [D].
   - **Erreur de ce `COMMIT` — décidé le 27 octobre 2026 [D].** Si son issue est indéterminée, E ne délivre aucune nouvelle autorisation, et le gel du §5.5.1 (cas 3, « Extension au `COMMIT` d’E ») s’applique jusqu’à une récupération et une vérification explicites. Un non-`COMMIT` établi par un `ROLLBACK` réussi ne le déclenche pas, sauf si une règle déjà décidée l’exige.
   - [R] B reste tenue jusqu’à la résolution de la transaction, selon les points a à c du §5.5.1, cas 3. Le gel pour E est porté par le marqueur propre à sa transaction, fixé le 28 octobre 2026 [D] ; ses détails restent ouverts [O].
7. **E7.** Relâcher B. La remise du résultat suit. **Complété le 28 octobre 2026 [D], puis précisé le même jour :** après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi, le service peut tenter de retirer le marqueur d’E, puis il relâche B, puis W, même si ce retrait a échoué. Si l’issue est indéterminée, il ne tente pas le retrait ; une fois la transaction inactive, il relâche B puis W et laisse le marqueur en place. Si la transaction reste non résolue, le processus se termine sans autre instruction [H sur la libération de B et de W], sans code ni message du protocole, avec pour seul signal le statut de sortie dédié au fail-stop (`EXIT_FAIL_STOP`) (§5.5.1, « Signalement du fail-stop »). La place de la remise par rapport au retrait et à W, comme sa portée, reste ouverte [O].

**Traitement d’une course [D].**
- **Cas visés :** la génération a changé entre E1 et E3, ou l’ancre relue ne couvre pas la génération courante.
- **Refus :** E refuse. C’est un refus fermé du chemin d’approbation. Aucune décision n’est enregistrée, ni la confirmation ni le nonce ne sont modifiés, et le refus est compté de façon bornée (§10.3).
- **Nouvelle tentative :** elle recommence à E1, avec une nouvelle relecture de l’ancre. Le nombre de tentatives reste ouvert [O].
- **Garantie :** sous B, la génération ne peut pas changer avant E6. Aucune autorisation n’est donc enregistrée sous une génération antérieure à celle en vigueur.
- **Conséquence [D] :** après l’installation d’une nouvelle génération, E refuse tant que son entrée `c` n’est pas consignée et incluse dans la tête J-c relue. Il en va de même pour la génération initiale. Les détails techniques de la consignation et de l’ancrage de la genèse restent ouverts [O].

**D-9 [D].** La voie d’urgence ne prend pas la barrière et reste limitée à l’interrupteur. **Précisé le 27 octobre 2026 :** elle peut être temporairement indisponible tant que le service est arrêté par la procédure `root` (L.5). Après le redémarrage, elle est de nouveau disponible dans sa portée décidée, même si `c` attend encore l’ancrage.

###### L.3 Séquence de l’opération `root` : ordre décidé [D], détails [R]

1. **R0.** Prendre M. Engendrer le défi en mémoire et recevoir l’assertion (J.3 ; F). Cette étape se déroule hors barrière.
2. **R1.** Lire P, de génération g. Vérifier l’assertion, le statut et la chaîne du signataire d’après g, ainsi que l’indépendance du signataire à l’égard du credential visé (J.3).
3. **R2.** Écrire l’événement dans Z : fichier temporaire, `fsync`, renommage, `fsync` du répertoire. L’événement est ainsi durable avant la mise à jour de la politique (J.4) [H].
4. **R3.** Préparer P′, de génération g+1, qui référence l’empreinte de l’événement : fichier temporaire, puis `fsync`. Rien n’est encore visible.
5. **R4.** Prendre G en exclusif, ce qui bloque les nouvelles transactions du service. Prendre ensuite B en exclusif, ce qui attend la fin des transactions en cours. Le délai est borné : `T_barrière_root`. **Décidé (L.5, option d) [D] :** si B est encore retenue à l’expiration du délai, `root` arrête tous les processus du service, empêche leur redémarrage, puis prend B. Si l’arrêt ou la prise de B échoue, aucune génération n’est installée et le système reste fermé.
6. **R5.** Sous B, relire P. Si sa génération n’est plus g, abandonner : l’assertion ne vaut que pour g [R].
7. **R6.** Renommer P′ en P, puis `fsync` du répertoire, en tenant toujours B. **Décidé [D] :** g+1 n’est déclarée effective qu’après l’obtention de la barrière exclusive et l’installation durable de la politique, c’est-à-dire après le renommage et la synchronisation du répertoire [H]. **Échec de la synchronisation, `root` restant actif — décidé le 29 octobre 2026 [D] :** `root` garde B et G pendant une période bornée pour achever ou résoudre l’installation, puis, à défaut, arrête le service selon L.8, point 8 ; g+1 n’est pas déclarée effective. **Déclaration D — principe O1-B décidé le 1er novembre 2026 [D], sous condition [H] (L.8, point 8) :** l’obtention de la barrière et l’installation durable de P sont des préalables, mais ne suffisent pas à déclarer g+1 effective. Après R6 et avant R7, toujours sous B, `root` écrit D, établit sa durabilité, puis écrit la confirmation ; la déclaration d’effectivité de g+1 intervient après la déclaration D durable et cette confirmation. Mécanisme concret et conduite en cas d’échec [O].
8. **R7.** Relâcher B, puis G, puis M. Si le service a été arrêté, lever l’interdiction de redémarrage et le relancer ; les conditions de la relance restent ouvertes [O]. Rapporter le succès.

**Ordre — décidé le 27 octobre 2026 [D].**
1. Préparer et vérifier l’événement hors barrière (R1 à R3).
2. Prendre G en exclusif, puis B en exclusif (R4). G bloque l’arrivée de nouveaux utilisateurs de B pendant que `root` attend la fin des transactions déjà en cours.
3. Vérifier de nouveau la génération (R5).
4. Installer durablement la politique (R6).
5. Relâcher les verrous (R7).

Le dépassement du délai suit la procédure déjà décidée (L.5). Restent [R] : l’abandon lorsque la génération a changé, le verrou M et l’ordre de libération.

G et B ne sont tenus qu’entre R4 et R7, jamais pendant l’interaction avec le propriétaire.

###### L.4 Propriété vérifiée, et ses conditions

**Propriété.** Aucune transaction visée ne peut être validée sous la génération g après que g+1 est devenue effective.

**Raisonnement.**
- `root` renomme P à un instant `t_r`, compris dans l’intervalle où il tient B en exclusif.
- Une transaction visée tient B en partagé sur un intervalle qui contient sa lecture de P et son `COMMIT`.
- Un verrou exclusif et un verrou partagé sur B ne se chevauchent pas.
- Donc soit la transaction a relâché B avant que `root` le prenne, auquel cas elle a lu g et validé avant `t_r` ; soit elle l’a pris après que `root` l’a relâché, auquel cas elle lit g+1.

**Conditions** [R ; H] :
1. toutes les transactions visées suivent L.2 ;
2. B est un fichier stable, distinct de P ;
3. le point de validation SQLite se situe avant S8. Il dépend du mode de journal et du réglage `synchronous`, non vérifiés sur le serveur [O]. Le dépôt exige WAL et `synchronous = FULL` à chaque connexion (§5.5.1, « Erreurs SQLite dans la transaction de V0 »). **Cette condition n’est pas établie lorsque le `COMMIT` a renvoyé une erreur**, car l’état persistant n’est alors pas documenté (même paragraphe, cas 3) [O]. Le refus en V1 des opérations signées par une clé `COMPROMISED` reste acquis (J.6), mais la chronologie et le classement S4 ne sont alors pas garantis [R] ;
4. aucune lecture de P n’a lieu avant S2 ;
5. `root` ne renomme P que sous B.

**Absence de cycle d’attente. Ordre décidé le 27 octobre 2026 [D] ; vérification [R].**

Les ressources sont G, B, le verrou d’écriture SQLite et M, que seul `root` prend. Les ordres de prise décidés sont les suivants :
- **service et E :** G partagé, puis B partagé, puis relâchement de G, puis SQLite ;
- **`root` :** M, puis G exclusif, puis B exclusif, et jamais SQLite.

Voici les attentes possibles entre processus qui respectent le protocole, et pourquoi chacune se termine.
- **Un service attend G en partagé.** Seul `root` peut tenir G en exclusif. En le tenant, `root` attend au plus B. Les détenteurs de B ont déjà relâché G : ils n’attendent plus que SQLite, ou leur propre fin.
- **Un service attend B en partagé en tenant G en partagé.** `root` ne peut tenir B en exclusif que s’il tient déjà G en exclusif, ce qui est impossible tant que ce service tient G. Aucun processus qui respecte le protocole ne bloque donc cette attente.
- **Un service attend le verrou SQLite.** Son détenteur tient déjà B, a relâché G et n’attend ni G ni B : il progresse jusqu’à son `COMMIT` ou son `ROLLBACK`. La transition vers `FAILED` a lieu dans la même transaction, sous B et sous le verrou SQLite déjà tenus, sans demander G ni B (§14, point 24). D-9 prend SQLite sans G ni B, et n’attend pas G ni B non plus.
- **`root` attend G en exclusif.** Les détenteurs de G n’attendent que B, que `root` ne tient pas encore. Ils la prennent, puis relâchent G.
- **`root` attend B en exclusif.** Les détenteurs de B attendent au plus SQLite, tenu par un processus qui n’attend ni G ni B.
- **M** n’est demandé par aucun processus du service.

Aucun détenteur du verrou SQLite n’attend G ou B ; le graphe des attentes n’a donc pas de cycle.

**Avec W, décidé le 28 octobre 2026 [D] : vérification [R].** Les transactions couvertes prennent W avant G ; `root` ne prend pas W. Les attentes ajoutées se terminent :
- **une transaction attend W :** son détenteur attend au plus G, B ou SQLite, et ces attentes se terminent comme ci-dessus ;
- **le détenteur de W attend G :** `root` tient G en exclusif et attend au plus B. Les détenteurs de B n’attendent pas W : une transaction couverte qui tient B tient déjà W, et les autres ne le demandent pas ;
- **le détenteur de W attend SQLite :** le détenteur de SQLite n’attend pas W.

**Condition [R], à vérifier dans la mise en œuvre [O] :** aucun processus ne demande W en tenant G, B ou une transaction SQLite.

**Limite.** Un processus bloqué qui retient W bloque toutes les transactions couvertes. S’il ne tient pas B, il ne retarde pas `root`, qui n’attend pas W ; s’il tient aussi B, la procédure de L.5 s’applique. Un compte de service compromis peut retenir W indéfiniment : c’est un refus de service, que ce raisonnement ne prévient pas (J.6). L’équité de W n’est pas garantie [O].

**Condition [R], à vérifier dans la mise en œuvre [O] :** un processus ne demande jamais G ni B alors qu’il tient une transaction SQLite ouverte, y compris sur une autre connexion.

**Contre-exemple de l’ordre inverse (SQLite, puis barrière).** T1 tient SQLite et attend G, que `root` tient. `root` attend B, que tient T2. T2 attend SQLite, que tient T1. C’est un interblocage.

**Limites.**
- **L’absence d’interblocage n’est pas l’équité.** Avec `flock` [H], une demande exclusive n’a aucune priorité garantie : des transactions qui se succèdent sur G peuvent retarder `root`. La garantie d’équité reste ouverte [O]. Le délai borné et l’arrêt forcé décidés (L.5) en limitent l’effet.
- **Compte compromis.** Un compte de service compromis peut retenir G ou B, ou les ignorer. Ce raisonnement ne lui oppose aucune garantie (J.6), au-delà de la procédure d’arrêt forcé (L.5).

**Ce que la propriété ne couvre pas.**
- **Le chemin E, couvert depuis la décision du 27 octobre 2026 [D]** (séquence E de L.2).
  - Sans cette couverture, E pourrait décider sous g et produire son effet après `t_r`.
  - La relecture réseau de J-c reste hors barrière. La course qui en résulte est traitée par la revérification sous B.
  - Une décision enregistrée sous g puis remise après la libération de B a été prise avant la déclaration de g+1. Sa revalidation éventuelle avant usage reste ouverte [O].
- **Toute autre lecture de P hors barrière.** Elle peut voir g+1 avant sa durabilité. Elle n’en tire que des refus supplémentaires, sauf retour arrière après une coupure (L.7).
- **Un compte de service compromis**, qui peut ignorer B et écrire directement la base (J.6).

###### L.5 Barrière retenue par un processus du service : constat, puis décision du 27 octobre 2026 [D]

**Constat (analyse).**
- `root` attend la fin des transactions du service (J.5). Tout processus qui tient B en partagé, ou G, retarde donc `root`. C’est le cas d’un processus bloqué, mais aussi d’un compte de service compromis, qui peut le faire indéfiniment. Avec `flock` [H], un descripteur ouvert en lecture seule permet même de prendre un verrou exclusif.
- Pour l’opération `root`, un échec de la barrière signifiait ne pas installer g+1, et laissait donc la clé visée utilisable par un service en marche.
- Aucun protocole fondé seulement sur une barrière que `root` attend ne tient à la fois ces trois exigences :
  1. aucune transaction validée sous g après g+1 ;
  2. une installation que le service ne peut pas empêcher ;
  3. un échec qui ferme.

  Quatre options ont été examinées : (a) accepter la limite ; (b) installer de force, ce qui modifierait J.5 ; (c) arrêter les processus du service ; (d) barrière en temps normal, puis (c) après un délai.

**Décidé par le propriétaire le 27 octobre 2026 [D] : option (d).**
- En fonctionnement normal, `root` attend la barrière exclusive.
- Après un délai borné, si le service la retient encore, `root` arrête tous les processus du service et empêche leur redémarrage pendant l’installation de la nouvelle politique.
- `root` ne déclare la nouvelle génération effective qu’après avoir obtenu la barrière exclusive et installé durablement la politique (L.3, R6).
- Si l’arrêt ou l’obtention de la barrière échoue, aucune nouvelle génération n’est installée, et le système reste fermé.
- La valeur du délai et les détails du mécanisme restent ouverts [O].

**Ce que la décision donne, et ce qu’elle ne donne pas.**
- **Exigence 1.** Elle est tenue pour les transactions qui suivent le protocole. Soit elles se terminent avant que `root` prenne B, soit elles sont interrompues avant leur `COMMIT`, et SQLite les annule à la récupération [H]. Aucune ne valide donc sous g après la déclaration de g+1. Une transaction validée juste avant l’arrêt reste validée sous g, avant cette déclaration.
- **Exigence 2.** Un processus qui retient la barrière ne peut plus que retarder l’installation, jusqu’au délai borné. Il ne l’empêche que si l’arrêt ou l’obtention de la barrière échoue ; le système reste alors fermé.
- **Exigence 3.** L’échec ferme le système, au lieu de laisser la clé visée utilisable par un service en marche. Cette clé reste valide dans la politique g, mais aucun processus du service ne doit alors fonctionner.
- **Pas d’atomicité.** L’arrêt forcé n’est pas une atomicité entre SQLite et la politique `root`. Il interrompt des transactions, que SQLite annule à la récupération [H]. Il ne rend pas indivisibles un `COMMIT` et un renommage.
- **Limite maintenue (J.6).** La décision n’arrête pas un compte de service compromis qui contourne directement le protocole, par une écriture directe dans la base ou par un processus relancé d’une manière que l’interdiction de redémarrage ne couvre pas. La chronologie et le classement S4 ne sont alors pas garantis.
- **Fermeture en cas d’échec de l’arrêt.** Des processus du service peuvent encore fonctionner. La manière de garantir que le système reste fermé relève du mécanisme [O] : ne pas relancer le service, désactiver son lancement, ou autre.
- **D-9 [D].** La voie d’urgence reste hors de la barrière et limitée à l’interrupteur. **Précisé le 27 octobre 2026 [D] :**
  - D-9 peut être temporairement indisponible tant que le service est arrêté par la procédure `root` ;
  - le service arrêté est en échec fermé, et aucune voie ne doit autoriser pendant cet arrêt ;
  - après le redémarrage, D-9 est de nouveau disponible dans sa portée décidée, même si `c` attend encore l’ancrage, puisqu’elle ne fait que fermer l’interrupteur ;
  - ni la portée de D-9 ni les conditions d’effectivité des opérations qui ouvrent ne changent.

**Échec de la synchronisation du répertoire, `root` restant actif — décidé le 29 octobre 2026 [D]** (L.8, point 8). `root` garde B et G pendant une période bornée pour achever ou résoudre l’installation. S’il n’y parvient pas, il arrête le service, maintient l’interdiction de redémarrage et libère les verrous après l’arrêt complet ; le service reste arrêté jusqu’à l’achèvement ou la résolution. g+1 n’est déclarée effective que lorsque les conditions de L.3, R6, sont remplies. Les règles de D-9 ci-dessus sont inchangées.

**Détails restés ouverts [O] :**
- la valeur du délai ;
- le mécanisme d’arrêt, qui doit viser tous les processus du compte de service, y compris ceux lancés hors du gestionnaire de services ;
- le mécanisme qui empêche le redémarrage, et sa persistance si `root` s’arrête brutalement ;
- le moment et les conditions de la relance ;
- pour l’échec de synchronisation décidé ci-dessus : la valeur du délai borné, les modalités et le nombre des tentatives (méthode d’achèvement après un échec de `fsync` à vérifier [H]), les conditions précises de reprise et les mécanismes d’intervention si l’installation ne peut pas être résolue ;
- la conduite pour les autres échecs de l’installation durable après l’obtention de B.

###### L.6 Ancrage externe et barrière : décision du 1er novembre 2026 [D], détails [O]

La transaction de validation avant ancrage consigne `c` et valide la queue sous B (S5, S6). **Réserve (L.8, point 8, décidé le 29 octobre 2026 [D]) :** pas pour une génération visible mais non déclarée effective ; le service reste alors fermé et ne l’utilise pas : aucune opération signée, aucune consignation de `c` ni aucun ancrage pour cette génération avant sa déclaration d’effectivité. L’ajout à l’ancre J-c est une écriture externe qui suit son `COMMIT` (I.4). Si `root` installe g+1 entre ce `COMMIT` et l’ajout, la queue ancrée ne contient pas l’entrée `c` de g+1. **L’ordre reste correct :** toutes les entrées ancrées ont été vérifiées sous g et précèdent cette entrée `c`. En revanche, la règle selon laquelle « l’ancrage attend que la génération soit consignée » (I.4, J.5) n’est tenue qu’à l’instant de la validation. **Principe O1-B (L.8, point 8, décidé le 1er novembre 2026 [D], sous condition [H]) :** à lui seul, il ne tranche pas si « chaque ancrage » (§11.3) inclut l’ajout externe à J-c. Selon le protocole actuel, cet ajout suit le `COMMIT`, après lequel le service relâche B (L.2, S8).

Options examinées :
- **option 1, non retenue : tenir B pendant l’ajout à l’ancre.** `root` attendrait alors la latence de l’ancre, dans la limite de `T_barrière_root`, et une entrée-sortie réseau aurait lieu sous la barrière, contrairement à L.2 ;
- **option 2, retenue : lire la règle comme visant la génération et l’état de D contrôlés sous B lors de la validation de la queue.**

**Décidé par le propriétaire le 1er novembre 2026 [D] : option 2** (§14, point 23, décision 16). La règle d’ancrage vise la génération et l’état de D contrôlés sous B lors de la validation de la queue. L’ajout externe à J-c, qui suit le `COMMIT` et a lieu hors barrière selon le protocole actuel, publie la queue déjà validée ; il n’est pas une nouvelle validation sous la génération qui pourrait être installée après le `COMMIT`.
- Une queue validée sous g demeure classée sous g, même si son ajout à J-c survient après l’installation de g+1.
- Cet ajout peut donc précéder `c` de g+1. Les entrées de g restent antérieures à `c` dans l’ordre du journal.
- Cette publication de la queue validée sous g ne constitue ni l’utilisation de g+1, ni un ancrage d’opération de g+1.
- Avant toute validation ultérieure sous g+1, le service vérifie sous B que D est actuellement confirmée et concorde avec P. `c` de g+1 est consignée avant toute validation ou tout ancrage ultérieur sous g+1.

Cette décision précise la portée de la règle d’ancrage (I.4, J.5) et de « chaque ancrage » (§11.3). Elle ne modifie ni la barrière (J.5 ; L.2, S8), ni O1-B, dont la condition reste [H], ni M.6.

**Restent ouverts [O] :**
- le processus qui effectue l’ajout à J-c (§11.4 ; §14, point 17) ;
- les tentatives et les issues inconnues de cet ajout (§11.3) ;
- le traitement d’une queue en attente après un redémarrage. La validation pré-ancrage y est rejouée (§11.3), mais cette décision ne fixe pas, à elle seule, comment une queue dont la validation précédente a eu lieu sous g est traitée si la validation est rejouée après l’installation de g+1 ;
- le sort d’un ajout en attente si g devient fermée selon O1-B, pendant S4 ou pendant le gel.

###### L.7 Matrice des interruptions [R]

« Politique » désigne la génération qui fait autorité après l’interruption.

| Interruption | Opération refusée ? | Politique | Nonce | Reprise |
|---|---|---|---|---|
| Service ou E, W non obtenu (délai) ou arrêt avant G [D, 28 octobre 2026] | Oui. Rien n’est écrit ; aucun marqueur n’est créé | Inchangée | Inchangé ; qualification du refus [O] | Même énoncé, avant expiration ; délai de W [O] |
| Service ou E, marqueur résiduel constaté sous W [D, 28 octobre 2026] | E et opérations qui ouvrent : oui, refus sans écriture [D]. Opération signée qui ferme : [O] | Inchangée | Inchangé ; qualification du refus et sort du nonce [O] | Après la levée explicite par `root` [D] ; sort d’une nouvelle tentative [O] |
| Service, avant la prise de la barrière (S1, S2) : délai dépassé ou arrêt brutal | Oui. Refus de précondition γ1 ; en cas d’arrêt, rien n’est écrit ; aucun marqueur n’existe encore [D] | Inchangée (g ou g+1) | `ISSUED` | Même énoncé, avant expiration |
| Service, barrière prise, `BEGIN IMMEDIATE` en échec (S3) | Oui. Rien n’est écrit ; aucun marqueur n’existe encore, sa création suivant le `SAVEPOINT` [D] | Inchangée | `ISSUED` ; qualification [O] | Même énoncé, avant expiration |
| Service, arrêt brutal après la création du marqueur, avant S4 [D, 28 octobre 2026] | Oui. Rien n’est écrit | Inchangée ; barrière et W libérés par le noyau [H] | `ISSUED` | Gel conservateur [D] jusqu’au retrait du marqueur par `root` et à la levée (§5.5.1, cas 3, « Gel conservateur ») |
| Service, pendant la transaction : P ou Z illisible, ou écriture de `c` impossible (S4, S5) | Oui. `ROLLBACK`, qui annule aussi `c`. Le marqueur, créé avant S4, n’est retiré qu’après le `ROLLBACK` complet réussi [D] | Inchangée | `ISSUED` (J.7) | Même énoncé, après résolution |
| Service, pendant la transaction : divergence détectée (S5) | Oui. État S4 (§11.3, « Divergence γ1 ») | Celle de `root`, mais aucune opération signée n’est admise pendant S4 | `ISSUED`, sans écriture de `FAILED` (J.7) | Résolution de S4 [O], puis V0 complet |
| Service, pendant la transaction : échec d’une étape de V0 (S6) | Oui. Étape 1a : `ROLLBACK` complet. Étape 1b et étapes 2 à 8 : retour au `SAVEPOINT` | Inchangée | 1a : `ISSUED`. 1b et étapes 2 à 8 : `FAILED`, par transition conditionnelle dans la même transaction (§14, point 24) | Règles du §5.5.1 |
| Service, retour au `SAVEPOINT` réussi, puis échec de la transition | Oui. Aucun `COMMIT`, annulation complète. L’effet de l’opération, `c` comprise, est annulé au `SAVEPOINT` | Inchangée | `ROLLBACK` réussi : `ISSUED`, établi [F]. `ROLLBACK` en échec avec `in_transaction` faux : `ISSUED` seulement déduit sous C2 [R], non garanti par une catégorie de sortie (§10.2, « Déductions sous C2 »). Sinon, ligne du cas 2, point 3 | Constat de l’état, puis règles du §5.5.1 (cas 1) |
| Service, échec du retour au `SAVEPOINT` ou de l’annulation complète, puis `ROLLBACK` réussi, ou en échec avec `in_transaction` faux (§5.5.1, cas 2, points 1 et 2) | Oui. Aucun `COMMIT` [D]. Point 1 : annulation établie par le `ROLLBACK` [F]. Point 2 : annulation déduite sous C2, aucun `COMMIT` n’ayant été exécuté [R]. Ce n’est pas un fail-stop : le processus continue et ne produit pas le statut de sortie dédié au fail-stop (`EXIT_FAIL_STOP`). Le refus est signalé par le code fixe du cas 2, point 5 [R] | Inchangée | Point 1 : `ISSUED`, établi par le `ROLLBACK` réussi [F]. Point 2 : `ISSUED` seulement déduit sous C2 [R], non garanti par une catégorie de sortie (§10.2, « Déductions sous C2 ») | Constat avant toute nouvelle tentative (§5.5.1, cas 2). Point 1 : tentative de retrait possible, puis B et W relâchés. Point 2 : marqueur laissé en place, puis B et W relâchés [D, 28 octobre 2026]. Exception : après un échec de synchronisation du marqueur, tout échec du `ROLLBACK`, même si `in_transaction` est faux, mène au fail-stop spécial, plus strict que la règle générale du point 2 (ligne dédiée) |
| Service, échec du retour au `SAVEPOINT` ou de l’annulation complète, puis `ROLLBACK` en échec avec `in_transaction` vrai ou illisible (§5.5.1, cas 2, point 3) | Oui. Aucun `COMMIT` [D]. Annulation non établie : l’absence d’effet n’est pas affirmée. Fail-stop : le processus se termine sans autre instruction, sans code ni message du protocole, avec pour seul signal le statut de sortie dédié au fail-stop (`EXIT_FAIL_STOP`) [D] ; B et W sont libérés par le noyau [H] | Inchangée | Non établi [O] | Constat avant toute nouvelle tentative (§5.5.1, cas 2). Marqueur laissé en place : gel conservateur [D] jusqu’à son retrait par `root` et la levée (§5.5.1, cas 3, « Gel conservateur » ; « Signalement du fail-stop ») |
| Service, retour au `SAVEPOINT` réussi, puis échec du `COMMIT` final | Oui. L’effet est annulé au `SAVEPOINT`. B est gardée jusqu’à la résolution de la transaction (§5.5.1, cas 3, points a à c) | Inchangée | **Incertain** : `FAILED` ou `ISSUED` [O]. Après un `ROLLBACK` explicite réussi, `ISSUED` est déduit, sans que sa durabilité soit établie [O] | Constat, sans réécriture dans une transaction séparée ni nouvelle tentative automatique (§5.5.1, cas 1). Au point a (`ROLLBACK` réussi, non-`COMMIT` établi) : pas de gel, sauf règle déjà décidée [D], le service retirant le marqueur. Aux points b et c : gel [D], pour toute transaction V0, qu’elle ouvre ou qu’elle ferme, soit aucune autorisation E ni opération qui ouvre jusqu’à une récupération et une vérification explicites ; le marqueur reste, et seul `root` le retire [D]. Au point c, B puis W sont relâchés sans tentative de retrait ; au point b, fin du processus sans code ni message du protocole, avec pour seul signal le statut de sortie dédié au fail-stop (`EXIT_FAIL_STOP`) [D ; H] ; détails [O] |
| Service, arrêt brutal entre le retour au `SAVEPOINT` et le `COMMIT` | Oui. Rien n’est validé, faute d’enregistrement de validation (wal) | Inchangée ; barrière libérée par le noyau [H] | `ISSUED` ; « une tentative par nonce » n’est pas tenue [O] | Constat, puis règles du §5.5.1. Le marqueur, créé avant les écritures et non retiré par le retour au `SAVEPOINT`, est présent : gel conservateur [D] jusqu’à son retrait par `root` et la levée (§5.5.1, cas 3, « Gel conservateur » et « Mécanisme du marqueur ») |
| Service, erreur du `COMMIT` du chemin de succès (étape 10) | Ni succès ni refus : issue à constater [D]. B est gardée jusqu’à la résolution de la transaction (§5.5.1, cas 3, points a à c) | Inchangée ; L.4, condition 3, non établie [O] | `CONSUMED` avec l’effet, ou `ISSUED` sans lui (atomicité) ; inconnu de l’appelant | Constat ; aucune nouvelle tentative automatique [D] (§5.5.1, cas 3). Au point a (`ROLLBACK` réussi, non-`COMMIT` établi) : pas de gel, sauf règle déjà décidée [D], le service retirant le marqueur. Aux points b et c : gel [D], pour toute transaction V0, qu’elle ouvre ou qu’elle ferme, soit aucune autorisation E ni opération qui ouvre jusqu’à une récupération et une vérification explicites ; le marqueur reste, et seul `root` le retire [D]. Au point c, B puis W sont relâchés sans tentative de retrait ; au point b, fin du processus sans code ni message du protocole, avec pour seul signal le statut de sortie dédié au fail-stop (`EXIT_FAIL_STOP`) [D ; H] ; détails [O] |
| Service, arrêt brutal avant le `COMMIT`, `c` éventuellement écrite | Oui. Rien n’est validé ; SQLite annule à la récupération [H] | Inchangée ; barrière libérée par le noyau [H] | `ISSUED` (arrêt avant le `COMMIT`) | `c` est reconsignée par la transaction suivante (idempotent). Marqueur présent, puisqu’il est créé avant S4 [D, 28 octobre 2026] : gel conservateur [D] jusqu’à son retrait par `root` et la levée (§5.5.1, cas 3, « Gel conservateur » et « Mécanisme du marqueur ») |
| Service, arrêt pendant ou juste après le `COMMIT`, avant de relâcher B | Selon le point de validation SQLite [H] : transaction validée sous g, avant tout renommage, ou annulée | Inchangée | `CONSUMED` si la transaction est validée, sinon `ISSUED` | Règles existantes. Arrêt pendant le `COMMIT`, ou après lui avant le retrait du marqueur : gel conservateur [D] jusqu’à son retrait par `root` et la levée ; issue à constater [O] (§5.5.1, cas 3, « Gel conservateur » et « Mécanisme du marqueur ») |
| Service ou E, échec du retrait du marqueur, resté présent, après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi [D, 28 octobre 2026] | L’issue de la transaction est établie ; le service ne prétend pas que le gel est levé | Inchangée | Selon l’issue établie | B puis W sont relâchés. Le marqueur résiduel maintient le gel jusqu’à la récupération et à la levée explicites par `root` ; aucun autre marqueur n’est retiré. Détails techniques du retrait et conduite si l’état du marqueur ne peut pas être établi [O] |
| Service ou E, suppression du marqueur visible, synchronisation du répertoire en échec ou incertaine, après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi [D, 28 octobre 2026] | L’issue SQLite reste établie | Inchangée | Selon l’issue établie | B puis W sont relâchés. Le service signale que la durabilité du retrait n’est pas établie, sans la présenter comme une levée explicite. Sous W, l’absence visible du marqueur laisse poursuivre les transactions couvertes pendant que le système tourne, sauf si d’autres marqueurs résiduels sont présents, qui continuent de maintenir le gel ; cette suppression ne le maintient pas à elle seule ; après une coupure ou un redémarrage, le marqueur peut réapparaître et provoquer un gel conservateur [D] |
| Service ou E, échec de la synchronisation du marqueur ou de son répertoire avant toute écriture [D, 28 octobre 2026] | Oui. Aucune écriture de base | Inchangée | Inchangé : ni consommé, ni passé à `FAILED`, ni renouvelé ; reste `ISSUED` jusqu’à son expiration normale s’il l’est encore [D] | Conduite de refus prévue ; aucun marqueur d’une autre transaction n’est supprimé ; après un `ROLLBACK` complet réussi, le service peut tenter de retirer son propre marqueur (règle décidée). La transaction se termine par un `ROLLBACK` complet ; s’il échoue ou si son issue ne peut pas être établie, aucun `COMMIT` ne suit : fail-stop propre à ce cas, même si `in_transaction` est faux, plus strict que la règle générale du cas 2, point 2 ; marqueur laissé en place s’il est présent [D, 28 octobre 2026] ; échec technique fermé, sans incrément du compteur des tentatives ni du compteur borné du §10.3, ni nouvelle tentative automatique [D] ; code technique commun à V0 et E, avec qualificatif sur le retrait à trois valeurs (retrait visible sans durabilité établie, marqueur confirmé présent, état non établi), émis seulement après le `ROLLBACK` complet réussi, jamais en cas de fail-stop, qui ne produit que le statut de sortie dédié `EXIT_FAIL_STOP` [D] ; noms du code et des valeurs, valeur numérique de `EXIT_FAIL_STOP` [O] (§10.2 ; §5.5.1, « Signalement du fail-stop ») |
| `root`, préparation inachevée (R0, R1) | Aucune opération du service n’est refusée | g | — | Nouveau défi (C-1) |
| `root`, après la préparation : événement écrit (R2, R3) | Aucune opération du service n’est refusée | g ; l’événement, sans génération, n’a aucun effet | — | Sort de l’événement [O] (I.4) |
| `root`, en attente de la barrière (R4), délai non encore dépassé | Les transactions retenues par G peuvent dépasser leur propre délai : refus de précondition γ1 | g | `ISSUED` pour les transactions retenues | Même énoncé, après l’installation |
| `root`, délai dépassé : arrêt forcé du service (L.5, option d) [D] | Les transactions en cours sont interrompues avant leur `COMMIT`, et SQLite les annule [H]. Arrêt forcé ≠ atomicité | g, jusqu’à l’installation durable | `ISSUED` (arrêt avant le `COMMIT`) | Relance du service après l’installation [O] ; même énoncé, avant expiration. Transaction couverte interrompue avec son marqueur présent : gel conservateur [D], que la relance ne lève pas ; seul `root` retire ce marqueur, après récupération et vérification [D] ; articulation avec D-9 au redémarrage [O] (§5.5.1, cas 3, « Gel conservateur ») |
| `root`, échec de l’arrêt ou de la prise de B [D] | Aucune nouvelle génération n’est installée | g dans la politique, mais **le système reste fermé** | `ISSUED` pour les transactions interrompues | Intervention du propriétaire ; mécanisme de fermeture [O] |
| D-9 pendant l’arrêt forcé du service [D] | D-9 peut être temporairement indisponible. Le service arrêté est en échec fermé : aucune voie n’autorise | Inchangée jusqu’à l’installation | — | Après le redémarrage, D-9 est de nouveau disponible dans sa portée, même si `c` attend l’ancrage |
| `root`, arrêt brutal pendant l’arrêt forcé | Le service est arrêté | g | `ISSUED` | Si l’interdiction de redémarrage ne persiste pas, le service repartirait sous g : persistance requise [O]. Nouvelle opération `root` |
| `root`, sous B, avant le renommage (R5) : génération changée ou arrêt | Opération `root` abandonnée | g | — | Comme la ligne « événement écrit » |
| `root`, après le renommage, avant la synchronisation du répertoire : arrêt brutal de `root` | Oui : le service n’utilise pas g+1 et reste fermé, sans opération signée, ancrage ni consignation de `c` pour cette génération [D, 29 octobre 2026] | g+1 visible, **non déclarée effective** (L.5) [D] ; barrière libérée [H]. Un service arrêté reste arrêté si l’interdiction persiste [O] | — | `root` achève ou résout l’installation avant la reprise du service [D, 29 octobre 2026]. Mécanisme concret qui établit la durabilité ou déclare g+1 effective, et conduite de `root` [O] ; principe O1-B décidé sous condition [D ; H] (L.8, point 8) |
| `root`, après le renommage : échec de la synchronisation du répertoire, `root` restant actif [D, 29 octobre 2026] | Oui. Pendant la période bornée, B et G restent tenues : refus de précondition γ1. Ensuite, si l’installation n’est pas achevée ou résolue, le service est arrêté | g+1 visible, **non déclarée effective** (L.3, R6) [D] | `ISSUED` pour les transactions retenues ou interrompues avant leur `COMMIT` | Achèvement ou résolution par `root` pendant la période bornée ; à défaut, arrêt du service, interdiction de redémarrage maintenue et verrous libérés après l’arrêt complet ; service arrêté jusqu’à l’achèvement ou la résolution [D]. Délai, tentatives, persistance de l’interdiction, conditions de reprise et intervention [O] (L.8, point 8) |
| Coupure d’alimentation au même point | Si g+1 est visible sans avoir été déclarée effective : oui, le service n’utilise pas g+1 et reste fermé, sans opération signée, consignation de `c` ni ancrage pour cette génération [D, 29 octobre 2026] | g ou g+1, selon ce qui a été persisté [H]. Si c’est g, l’installation n’a pas eu lieu. Si c’est g+1, elle n’est pas déclarée effective (L.8, point 8) [D]. Si `c` de g+1 a été consignée puis que P revient à g : incident d’intégrité (L.2, S5). La conduite décidée excluant la consignation de `c` avant la déclaration d’effectivité, ce cas suppose un écart à ce protocole ou une persistance qui ne respecte pas la synchronisation déclarée [H] | — | Si g+1 est visible sans avoir été déclarée effective : `root` achève ou résout l’installation avant la reprise du service [D, 29 octobre 2026] ; mécanisme concret de déclaration et conduite de `root` [O] ; principe O1-B décidé sous condition [D ; H] (L.8, point 8). Constat par le propriétaire, nouvelle opération ou résolution [O] |
| Après l’installation durable de la politique, avant la consignation de `c` | **Voie normale (L.8, point 8, décidé le 1er novembre 2026 [D], sous condition [H]) :** la première transaction visée ne consigne `c` et ne poursuit qu’après avoir vérifié, sous B, que D est actuellement confirmée et concorde avec P. Si cette vérification échoue, le système reste fermé pour cette génération, sans opération signée, consignation de `c` ni ancrage ; états de refus et sort du nonce [O]. Si elle réussit, la consignation suit la voie normale et les contrôles habituels de l’opération continuent ; un échec ou une divergence de consignation entraîne le refus prévu : refus de précondition γ1 en cas d’échec, état S4 en cas de divergence (§11.3, « Divergence γ1 »). Les autres préconditions et motifs de refus restent applicables | g+1 installée durablement. Si la vérification sous B établit que D est actuellement confirmée et concorde avec P : g+1 déclarée effective, invalidation effective (J.1, J.4). Sinon : g+1 non utilisée, système fermé pour cette génération (L.8, point 8, décidé le 1er novembre 2026 [D], sous condition [H]) | Selon le cas | Si la vérification sous B établit que D est actuellement confirmée et concorde avec P : première transaction visée ; E refuse jusqu’à l’ancrage de `c` (L.2). Sinon : le système reste fermé pour cette génération tant que cette vérification échoue ; reprise par `root` [O] (L.8, point 8). Dans les deux cas, l’événement reste dans Z au moins jusqu’à l’ancrage de son entrée J-b (J.4) |
| Validation avant ancrage validée sous g, puis renommage, puis ajout à J-c | Non | g+1 n’est déclarée effective et l’invalidation n’est effective que si la vérification sous B établit que D est actuellement confirmée et concorde avec P ; sinon, g+1 n’est pas utilisée et le système reste fermé pour cette génération (O1-B, L.8, point 8, décidé le 1er novembre 2026 [D], sous condition [H]) | — | Option 2 décidée le 1er novembre 2026 [D] (L.6) : l’ajout publie la queue validée sous g, qui demeure classée sous g et peut précéder `c` de g+1. Avant toute validation ultérieure sous g+1, le service vérifie sous B que D est actuellement confirmée et concorde avec P ; `c` de g+1 est consignée avant toute validation ou tout ancrage ultérieur sous g+1. Processus de l’ajout, tentatives, issues inconnues et traitement après un redémarrage [O] (L.6 ; §11.3) |
| E : génération changée entre E1 et E3 [D] | Oui : refus fermé du chemin d’approbation, aucune décision enregistrée | Nouvelle génération | Inchangé (E ne modifie pas le nonce, §10.3) | Nouvelle tentative depuis E1, avec une nouvelle relecture de l’ancre ; nombre de tentatives [O] |
| E : l’ancre relue ne couvre pas la génération courante [D] | Oui : refus fermé | Génération courante, pas encore consignée ou ancrée | Inchangé | Après consignation et ancrage de `c`, nouvelle relecture de l’ancre |
| E : barrière indisponible | Oui : refus fermé, aucune décision enregistrée | Inchangée | Inchangé | Nouvelle tentative |
| E : arrêt brutal ou arrêt forcé avant le `COMMIT` d’E6 | Oui : refus fermé, aucune décision enregistrée (arrêt avant le `COMMIT`, §5.5.1 ; SQLite annule à la récupération [H]) | Inchangée | Inchangé | Nouvelle tentative. Marqueur présent s’il a été créé, après `BEGIN IMMEDIATE` (L.2) [D] : gel conservateur [D], nouvelle tentative seulement après son retrait par `root` et la levée (§5.5.1, cas 3, « Gel conservateur » et « Mécanisme du marqueur ») |
| E : arrêt brutal ou arrêt forcé pendant le `COMMIT` d’E6 | Non établi : ni refus ni succès établi. La décision a pu être validée ou non [O] | Inchangée | Inchangé (E ne modifie pas le nonce, §10.3) | Constat de l’état [R]. Issue non établie [O]. Gel conservateur [D] jusqu’au retrait du marqueur par `root` et à la levée (§5.5.1, cas 3, « Gel conservateur » et « Mécanisme du marqueur ») |
| E : erreur du `COMMIT` de la décision (E6) | Aucune autorisation n’est remise [R]. Issue indéterminée (points b et c, §5.5.1, cas 3) : gel [D]. Non-`COMMIT` établi par un `ROLLBACK` réussi (point a, ou aucun `COMMIT` exécuté) : pas de gel, sauf règle déjà décidée [D] | Inchangée | Inchangé (E ne modifie pas le nonce, §10.3) | En cas de gel : aucune autorisation E ni opération qui ouvre jusqu’à une récupération et une vérification explicites ; lecture seule pour le constat [D]. Gel porté par le marqueur de la transaction d’E, que seul `root` retire alors [D, 28 octobre 2026]. Détails du marqueur, levée et sort d’une nouvelle tentative après la levée [O] |

###### L.8 Points décidés [D] et points à décider [O]

1. **[O]** Le mécanisme de verrou (`flock` ou autre), les fichiers B, G et M, ainsi que le mécanisme, l’équité et l’emplacement exact de W, son support étant fixé le 28 octobre 2026 (point 16), leurs propriétaires et modes, leur compatibilité avec T-3 (§9.2), et le refus de verrouiller P lui-même.
2. **Ordre de prise — décidé le 27 octobre 2026 [D]** (L.2, L.3, L.4).
   - **Service :** G partagé, puis B partagé, relâchement de G, puis `BEGIN IMMEDIATE`. La politique est lue après B, et B est gardée jusqu’au `COMMIT` ou au `ROLLBACK`.
   - **E :** le même ordre.
   - **Verrou W — décidé le 28 octobre 2026 [D] :** les transactions couvertes, V0 et E, prennent W avant G, examinent sous W les marqueurs existants, puis suivent l’ordre ci-dessus. W est un verrou de sérialisation, pas le support persistant du gel. Il est gardé jusqu’à la résolution de la transaction sur la connexion ; après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi, le service peut tenter de retirer son marqueur avant de relâcher les verrous. Une fois la transaction résolue, B puis W sont relâchés ; si le retrait échoue et que le marqueur reste présent, ou s’il n’est pas tenté, le marqueur résiduel maintient le gel. Une suppression visible dont seule la synchronisation du répertoire échoue ou reste incertaine ne maintient pas, à elle seule, le gel pendant que le système tourne (les autres marqueurs résiduels, s’il y en a, continuent de le maintenir et de provoquer les refus prévus) ; le marqueur peut réapparaître après une coupure ou un redémarrage. Si la transaction reste non résolue, le processus se termine (fail-stop), sans code ni message du protocole, avec pour seul signal le statut de sortie dédié `EXIT_FAIL_STOP` (§5.5.1, « Signalement du fail-stop »). La libération de W à la fin du processus est une hypothèse à vérifier [H] (L.2).
   - **`root` :** G exclusif, puis B exclusif.
   - **Reste ouverte [O] :** la vérification, dans la mise en œuvre, qu’aucun processus ne demande G ni B en tenant une transaction SQLite ouverte, ni W en tenant G, B ou une transaction SQLite (L.4).
3. **Porte G — retenue le 27 octobre 2026 [D].** Elle bloque l’arrivée de nouveaux utilisateurs de B pendant que `root` attend. **Reste ouverte [O] :** la garantie d’équité, que `flock` ne fournit pas à lui seul [H].
4. **[O]** Les délais : `T_barrière_service`, le délai d’occupation SQLite, et la valeur de `T_barrière_root`, borné dans son principe (point 6).
5. **Couverture de la barrière — décidé le 27 octobre 2026 [D].**
   - E est couvert jusqu’à l’enregistrement local de la décision d’autorisation. La lecture réseau de J-c reste hors barrière. Sous la barrière, E revérifie la génération et refuse en cas de course (L.2).
   - D-9 reste hors barrière et limitée à l’interrupteur.
   - **Restent ouverts [O] :**
     - les autres transactions éventuelles qui liraient la politique ;
     - le nombre de nouvelles tentatives de E ;
     - la revalidation d’une décision enregistrée mais pas encore utilisée.
   - **Précisé le 27 octobre 2026 [D] :**
     - l’entrée `c` qui consigne la génération courante est incluse dans la tête J-c qu’E vient de relire, et la règle vaut pour la génération initiale ;
     - D-9 peut être temporairement indisponible pendant l’arrêt forcé, durant lequel le service est en échec fermé ;
     - D-9 redevient disponible au redémarrage, dans sa portée, même si `c` attend l’ancrage.
6. **Barrière bloquée — décidé le 27 octobre 2026 [D] : option (d)** (L.5).
   - **Restent ouverts [O] :**
     - les mécanismes d’arrêt, d’interdiction de redémarrage et de relance ;
     - la persistance de l’interdiction si `root` s’arrête brutalement ;
     - la garantie que le système reste fermé si l’arrêt échoue.
7. **Ancrage externe — option 2 décidée le 1er novembre 2026 [D]** (L.6). La règle d’ancrage vise la génération et l’état de D contrôlés sous B lors de la validation de la queue ; l’ajout externe à J-c publie la queue déjà validée. **Restent ouverts [O] :** le processus qui effectue l’ajout, ses tentatives et ses issues inconnues, le traitement d’une queue en attente après un redémarrage, y compris une validation rejouée après l’installation de g+1, et le sort d’un ajout en attente si g devient fermée selon O1-B, pendant S4 ou pendant le gel.
8. **Durabilité — décidé le 27 octobre 2026 [D].** g+1 n’est déclarée effective qu’après l’obtention de la barrière exclusive et l’installation durable de la politique. **Selon le principe O1-B, décidé le 1er novembre 2026 [D], sous condition [H] (ci-dessous) :** ces deux étapes sont des préalables, mais ne suffisent pas à déclarer g+1 effective ; cette déclaration intervient après la déclaration D durable et la confirmation.
   - **Génération visible mais non déclarée effective — décidé le 29 octobre 2026 [D].** Après un arrêt brutal de `root`, ou une coupure d’alimentation au même stade (extension décidée le même jour [D] ; L.7), survenu entre le renommage et la synchronisation durable du répertoire, lorsque g+1 est visible sans avoir été déclarée effective, le service n’utilise pas g+1 tant qu’elle n’est pas déclarée effective. Il reste fermé : aucune opération signée, aucun ancrage et aucune consignation de `c` pour cette génération avant sa déclaration d’effectivité. `root` doit achever ou résoudre l’installation avant la reprise du service. Cette exception s’applique aux formulations de I.4 et J.4 selon lesquelles la mise à jour de la politique fait entrer l’invalidation en vigueur.
   - **Échec de la synchronisation du répertoire, `root` restant actif — décidé le 29 octobre 2026 [D].** Après le renommage de P′ en P, si la synchronisation du répertoire échoue alors que `root` est encore actif, `root` garde B et G pendant une période bornée pour achever ou résoudre l’installation. S’il n’y parvient pas dans cette période, il arrête le service, maintient l’interdiction de redémarrage et libère les verrous après l’arrêt complet ; le service reste arrêté jusqu’à l’achèvement ou la résolution de l’installation. g+1 n’est déclarée effective que lorsque les conditions de L.3, R6, sont remplies ; d’ici là, la règle précédente s’applique : le service n’utilise pas g+1.
   - **Principe O1-B pour la déclaration d’effectivité — décidé par le propriétaire le 1er novembre 2026 [D], sous condition (analyse du 30 octobre 2026).** Il porte sur le mécanisme resté ouvert ci-dessous. Seul le principe abstrait est décidé : sa condition reste [H], et ses détails de mise en œuvre restent [O]. Il ne rouvre ni les deux décisions du 29 octobre 2026 ci-dessus, ni L.5, ni M.6.
     - **Constat.** Dans le cas normal de l’option (d), le service n’est pas arrêté pendant l’installation. Si `root` s’arrête brutalement entre le renommage et la synchronisation durable, la barrière est libérée [H] et le service relit P sous B. Un contrôle au seul démarrage du service ne couvre donc pas ce cas : le service doit pouvoir constater, à chaque lecture de P, si la génération lue est déclarée effective.
     - **Principe décidé [D].**
       1. Après R6 et avant R7, en tenant toujours B, `root` écrit une déclaration D qui désigne g+1 et l’empreinte de P, puis établit la durabilité de cette déclaration.
       2. Toujours sous B et avant R7, il écrit ensuite une confirmation de cette durabilité, seulement après l’avoir établie. La conduite de `root` si cette durabilité ne peut pas être établie reste ouverte [O].
       3. Le service et E n’utilisent g+1, n’acceptent aucune opération signée pour cette génération, ne consignent pas `c` et n’ancrent pas tant qu’ils n’ont pas lu sous B une déclaration confirmée qui concorde avec P. Si D est absente, non confirmée, illisible ou discordante, le système reste fermé pour cette génération.
     - **Portée.** La règle du point 3 s’applique à chaque opération concernée : le service et E vérifient sous B l’état courant de D, y compris après l’installation durable de P (L.2, E3, L.7 et §11.3). Une lecture antérieure ne suffit pas : si D est ensuite absente, non confirmée, illisible ou discordante, le système reste fermé pour cette génération. Les réserves et exceptions du 29 octobre 2026 (§5.5.1, I.4, J.4, J.5, L.2, L.6 et §11.3) restent inchangées et se lisent avec cette règle.
     - **Condition.** Si la confirmation devient visible avant d’être durable, le service peut agir sur g+1, puis la confirmation peut être perdue après une coupure. Cette perte n’est sûre que si elle ramène à une déclaration durable non confirmée, donc à une fermeture cohérente avec une entrée `c` déjà consignée. La représentation de D doit donc garantir que la perte de la confirmation ne peut pas altérer la déclaration déjà durable. **Cette garantie n’est pas encore démontrée [H].** Par exemple, une réécriture en place du support de la déclaration pourrait l’altérer en cas de coupure [H]. Aucun format ni mécanisme concret n’est choisi : ni un fichier dédié, ni le contenu de B, ni la zone Z ne sont retenus.
     - **Si cette propriété ne peut pas être garantie,** O1-B ne résout pas le problème, et aucune mise en œuvre ne doit en être déduite.
     - **Critère d’évaluation de la condition — décidé le 2 novembre 2026 [D].** La condition est évaluée selon une garantie conditionnelle, fondée sur des hypothèses explicites et vérifiées pour l’environnement cible, avec fermeture en cas d’anomalie. Cette décision ne constate pas que la condition est satisfaite, ne choisit aucune représentation de D et n’autorise ni relevé de l’environnement, ni essai, ni mise en œuvre. La condition reste [H] jusqu’à une décision distincte constatant que les preuves requises sont suffisantes. La liste des hypothèses et des preuves requises reste à fixer [O].
     - **Limites de confiance envers l’hébergeur — décidé le 2 novembre 2026 [D].** Seules les hypothèses intrinsèquement invérifiables depuis le système invité et relevant de l’hébergeur peuvent être acceptées comme limites de confiance explicites ; elles ne sont jamais présentées comme vérifiées. Cette acceptation exige que le type de volume et les engagements applicables de l’hébergeur soient identifiés et examinés, puis que le propriétaire accepte explicitement chaque hypothèse concernée. Si ces éléments sont absents ou ambigus, l’hypothèse reste non établie, et O1-B demeure [H] et bloquée.
     - **Articulation [D].** Cette décision complète la décision 17 : toute autre hypothèse reste à vérifier pour l’environnement cible, et le texte de la décision 17 est inchangé. Elle ne constate pas que la condition est satisfaite, ne désigne aucune hypothèse, ne choisit aucune représentation de D et n’autorise ni relevé, ni contact avec l’hébergeur, ni essai, ni prototype, ni accès au serveur, ni mise en œuvre.
     - **Hypothèses [H], non vérifiées :** durabilité d’une écriture après la synchronisation confirmée du fichier et de son répertoire ; comportement d’un `fsync` relancé après un échec ; lecture de l’ancien ou du nouveau contenu de D, jamais d’un mélange ; état persisté après une coupure égal à l’un des états écrits ; atomicité d’une réécriture en place ou d’un renommage en cas de panne ; libération des verrous à la mort d’un processus.
     - **Restent ouverts [O] :** le format et le stockage de D ; ses permissions et son inscription à l’inventaire T-3 (§9.2) ; la méthode d’écriture ; la conduite de `root` en cas d’échec ; les états de refus et le sort du nonce pour chaque état de D ; l’écriture initiale de D à la genèse ; la reprise par `root` ; la disponibilité de D-9 dans cet état. D-9 est hors barrière (L.4), mais cela ne suffit pas à établir sa disponibilité.
     - **Proposition [R], non adoptée.** Une matrice des hypothèses et des preuves, ainsi qu’un critère de constat, figurent au L.9. Ils ne fixent pas la liste des hypothèses et des preuves requises, qui reste à fixer [O].
   - **Restent ouverts [O] :**
     - le mécanisme concret qui établit la durabilité de l’installation ou déclare g+1 effective, et la conduite de `root` pour achever ou résoudre l’installation, hors le cadre décidé ci-dessus pour l’échec de synchronisation et hors le principe O1-B décidé ci-dessus sous condition ;
     - pour l’échec de synchronisation : la valeur du délai borné, les modalités et le nombre des tentatives (méthode d’achèvement après un échec de `fsync` à vérifier [H]), la persistance de l’interdiction de redémarrage si `root` s’arrête brutalement, les conditions précises de reprise et les mécanismes d’intervention si l’installation ne peut pas être résolue ;
     - la conduite pour les autres échecs de l’installation durable après la prise de B.
9. **[O]** La qualification du refus lorsque `BEGIN IMMEDIATE` échoue. Le nonce reste alors `ISSUED`, aucune étape de V0 n’ayant été évaluée (L.2, étape S3 ; §5.5.1, cas 4). Les cas de `SQLITE_BUSY` documentés sont rappelés au §5.5.1 (« Erreurs SQLite dans la transaction de V0 », cas 4).
10. **[O]** Le retour arrière de la politique (génération inférieure à la dernière consignée), et son rattachement à J.7 et à S4.
11. **[O]** Le verrou M, et l’abandon lorsque la génération a changé.
12. **Passage à `FAILED` — décidé le 27 octobre 2026 [D]** (§14, point 24). Il a lieu dans la même transaction, sous B, après un retour au `SAVEPOINT`. La transaction distincte sans barrière n’est plus retenue.
13. **E et genèse — décidé le 27 octobre 2026 [D].** Aucune autorisation E n’est possible avant que l’entrée qui consigne la génération initiale soit consignée et incluse dans la tête J-c relue. **Restent ouverts [O] :** les détails techniques de la consignation et de l’ancrage de la genèse (H, « genèse » ; §11.4).
14. **Portée inchangée — décidé le 27 octobre 2026 [D].** Ces précisions ne changent ni la portée de D-9, ni les conditions d’effectivité des opérations qui ouvrent.
15. **Course sur le nonce — fermée le 27 octobre 2026 [D]** (§5.5.1 ; §14, point 24). Séquence : retour au `SAVEPOINT`, transition conditionnelle `ISSUED` → `FAILED` dans la même transaction, `COMMIT`, puis libération de B, puis de W [D, 28 octobre 2026]. **Chemin d’échec précisé le 27 octobre 2026 sur instruction du propriétaire** (§5.5.1, « Erreurs SQLite dans la transaction de V0 »). Après un retour au `SAVEPOINT` réussi, l’effet est annulé, et seul le sort du nonce peut être incertain. Après un échec de ce retour ou de l’annulation complète, aucun `COMMIT` ne suit, et l’absence d’effet n’est affirmée qu’une fois l’annulation établie, ou déduite sous les conditions du §5.5.1. Après une erreur de `COMMIT`, B n’est relâchée qu’une fois la transaction résolue sur la connexion. **Restent ouverts [O] :** le sort du nonce lorsque le `COMMIT` final échoue ; l’annulation lorsqu’elle n’est ni établie ni déduite ; la portée du constat de l’état. Le maintien du verrou d’écriture après `ROLLBACK TO` est déduit de la garantie de `BEGIN IMMEDIATE`, sans être énoncé par la documentation [H].
16. **Gel après une issue indéterminée — décidé le 27 octobre 2026 [D]** (§5.5.1, cas 3).
    - Après une erreur de `COMMIT` dont l’issue est indéterminée, aucune nouvelle autorisation E n’est délivrée et aucune opération qui ouvre n’est acceptée, jusqu’à une récupération et une vérification explicites. La lecture seule pour le constat reste possible.
    - Le gel ne change ni la barrière B, ni l’ordre de prise, ni la portée de D-9. D-9 écrit dans la même base et n’est pas une solution garantie à sa panne [R].
    - **Transactions couvertes — décidé le 27 octobre 2026 [D]** (§5.5.1, cas 3, « Transactions couvertes »). Toute transaction V0, qu’elle consigne une opération qui ouvre ou une opération signée qui ferme, et la transaction d’E (puce suivante). Le mécanisme a été fixé le 28 octobre 2026 (puce « Mécanisme du marqueur », ci-dessous).
    - **Extension au `COMMIT` d’E — décidée le 27 octobre 2026 [D]** (L.2, E6 ; §5.5.1, cas 3). Si le `COMMIT` par lequel E enregistre une autorisation a une issue indéterminée, E ne délivre aucune nouvelle autorisation, et le même gel s’applique jusqu’à une récupération et une vérification explicites. Un non-`COMMIT` établi par un `ROLLBACK` réussi ne le déclenche pas, sauf si une règle déjà décidée l’exige. [R] Un mécanisme armé par V0 seul n’aurait pas couvert E ; le marqueur propre à la transaction d’E y répond [D].
    - **Gel conservateur — décidé le 27 octobre 2026 [D]** (§5.5.1, cas 3, « Gel conservateur »). Tout marqueur encore présent après l’arrêt d’un processus ou une issue non résolue maintient le gel, y compris après un redémarrage et après l’arrêt forcé de L.5, que la relance ne lève pas. Aucun nettoyage automatique ne le retire, et seule une levée explicite, après récupération et vérification, y met fin. Un `ROLLBACK` complet réussi et établi, suivi du retrait normal, ne le déclenche pas.
    - **Mécanisme du marqueur — décidé le 28 octobre 2026 [D]** (§5.5.1, cas 3, « Mécanisme du marqueur » ; L.2). Un marqueur distinct par transaction couverte, V0 comme E, sous forme de fichier persistant hors de SQLite. Il est créé avant les écritures de la transaction. Le service ne le retire qu’après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi, jamais après un `ROLLBACK TO SAVEPOINT` seul. Un marqueur restant après un arrêt ou une issue indéterminée maintient le gel, sans nettoyage automatique au démarrage. `root` ne retire un marqueur résiduel qu’après une récupération et une vérification explicites. Limite déjà établie (J.6) : le mécanisme protège contre les erreurs de processus et de stockage, pas contre un compte de service compromis. Rien n’établit que le système de fichiers empêche un processus du compte de service de supprimer le marqueur d’un autre processus.
    - **Verrou W et ordre de prise — décidés le 28 octobre 2026 [D]** (L.2 ; point 2). Les transactions couvertes, V0 et E, prennent W avant G et examinent sous W les marqueurs existants ; pour E et les opérations qui ouvrent, un marqueur résiduel entraîne un refus sans écriture. L’ordre G, B, relâchement de G, `BEGIN IMMEDIATE` est inchangé. V0 crée son marqueur après le `SAVEPOINT`, avant l’étape S4 ; E après `BEGIN IMMEDIATE`, avant E3. W est gardé jusqu’à la résolution de la transaction ; après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi, le service peut tenter de retirer son marqueur avant de relâcher B, puis W. Si l’issue est indéterminée, il ne tente pas le retrait et le marqueur reste en place. W ne protège pas contre un compte de service compromis.
    - **Rôle de W et fin de la transaction — décidés le 28 octobre 2026 [D]** (L.2 ; §5.5.1, cas 3, « Mécanisme du marqueur »). W est un verrou de sérialisation, pas le support persistant du gel : le marqueur restant porte le gel. Une fois la transaction résolue sur la connexion, B puis W sont relâchés, même si le marqueur n’a pas pu être retiré. Après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi, le service peut tenter de retirer son propre marqueur ; en cas d’échec, il ne prétend pas que le gel est levé et ne retire aucun autre marqueur. Si l’issue est indéterminée, il ne tente pas le retrait et laisse le marqueur en place jusqu’à la levée explicite par `root`. Si la transaction reste non résolue : fail-stop, sans code ni message du protocole, avec pour seul signal `EXIT_FAIL_STOP` (§5.5.1, « Signalement du fail-stop »), la libération de B et de W à la fin du processus restant une hypothèse [H].
    - **Support de W, emplacement des marqueurs et restauration — décidés le 28 octobre 2026 [D]** (§5.5.1, cas 3, « Mécanisme du marqueur »). W est un fichier stable détenu par `root`, jamais supprimé ni remplacé, que le service peut ouvrir et prendre en verrou exclusif sans pouvoir le modifier. Les marqueurs sont placés dans un sous-répertoire persistant du compte de service, dans l’arborescence des données, hors des arborescences `root` et du code ; un système de fichiers local est une exigence de conception, et le système réellement utilisé sur le serveur reste à vérifier [H]. Une restauration n’est jamais, à elle seule, une levée explicite du gel ; son application après une restauration reste ouverte [O]. La portée de W, limitée à V0 et E, et L.4 sont inchangés ; la prise de W ne garantit pas la cohérence d’une sauvegarde.
    - **Retrait visible non durable et échec de synchronisation à la création — décidés le 28 octobre 2026 [D]** (§5.5.1, cas 3, « Mécanisme du marqueur » ; L.7). Après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi, une suppression visible dont la synchronisation du répertoire échoue ou reste incertaine laisse l’issue SQLite établie. Elle ne maintient pas, à elle seule, le gel pendant que le système tourne (les autres marqueurs résiduels, s’il y en a, continuent de le maintenir et de provoquer les refus prévus), mais le marqueur peut réapparaître après une coupure ou un redémarrage ; le service signale que la durabilité du retrait n’est pas établie, sans levée explicite. Un échec de synchronisation du marqueur ou de son répertoire avant toute écriture SQLite interdit toute écriture de base ; la transaction suit la conduite de refus prévue et ne retire aucun marqueur d’une autre transaction. Pour son propre marqueur, la règle de retrait décidée s’applique après un `ROLLBACK` complet réussi. La transaction se termine alors par un `ROLLBACK` complet ; s’il échoue ou si son issue ne peut pas être établie, aucun `COMMIT` ne suit et la règle fail-stop propre à ce cas s’applique, plus stricte que la règle générale du §5.5.1, cas 2, point 2 : même si `in_transaction` est faux, le processus se termine sans autre instruction, le marqueur restant en place s’il est présent (précisé le même jour [D]). Le refus est un échec technique fermé ; pour V0, le nonce est inchangé ; il n’y a ni incrément du compteur des tentatives ou du compteur borné du §10.3, ni nouvelle tentative automatique (décidé le même jour [D] ; §5.5.1, cas 3, « Mécanisme du marqueur ») ; le code technique de réponse, commun à V0 et E et accompagné d’un qualificatif sur le retrait, n’est émis qu’après le `ROLLBACK` complet réussi, jamais en cas de fail-stop, qui ne produit que le statut de sortie dédié `EXIT_FAIL_STOP` (§5.5.1, « Signalement du fail-stop ») ; le qualificatif a trois valeurs (retrait visible sans durabilité établie, marqueur confirmé présent, état non établi), sans valeur « retrait durable » ; les noms exacts du code et des valeurs restent ouverts [O] (§10.2). La règle d’un `COMMIT` d’issue indéterminée et la levée par `root` sont inchangées.
    - **Restent ouverts [O] :** la méthode de sauvegarde et la procédure de restauration ; les détails du marqueur (emplacement exact, nommage et contenu, propriétaires et modes, persistance effective, échec de création hors l’échec de synchronisation réglé [D], détails techniques du retrait et de sa durabilité hors la suppression visible non durable réglée [D], conduite si l’état ou la présence du marqueur ne peut pas être établi, identification des marqueurs résiduels, opération `root` de retrait et sa coordination avec W) ; le mécanisme, l’équité et les délais de W ; la qualification, le code et le comptage du refus pour marqueur résiduel, et le sort du nonce ; la conduite des fermetures signées en présence d’un marqueur résiduel ; l’articulation entre le gel conservateur, l’arrêt forcé et la disponibilité de D-9 au redémarrage (L.5) ; les critères de récupération, la vérification qui lève le gel et les critères détaillés de la levée ; l’ancrage pendant le gel.

###### L.9 Hypothèses et preuves pour la condition d’O1-B : proposition [R], non adoptée

**Portée.** Cette sous-section est une recommandation [R]. Elle ne fixe pas la liste prévue au L.8, point 8, qui reste à fixer [O]. Elle ne constate pas que la condition d’O1-B est satisfaite, ne choisit aucune représentation de D et n’autorise ni relevé de l’environnement, ni contact avec l’hébergeur, ni essai, ni prototype, ni accès au serveur, ni mise en œuvre. La condition reste [H].

**Types de preuve.** DOC : documentation. REL : relevé en lecture seule de l’environnement cible. ISO : essai dans un environnement isolé. RÉEL : essai touchant le serveur réel, jamais requis par défaut. Chacun, hors documentation publique, exige une autorisation distincte.

**Propriétés du protocole ou du futur logiciel.** Elles décrivent le comportement attendu du logiciel et découlent de décisions existantes, qui restent décidées à leur source. Ce ne sont pas des hypothèses techniques : seule leur vérification est proposée. Une vérification sur prototype devra être reprise sur tout code mis en œuvre.

| N° | Propriété à vérifier | Exigence d’origine | Vérification possible | Ce qu’elle établirait | Ce qu’elle ne prouverait pas |
|---|---|---|---|---|---|
| Prop-1 | Toujours sous B et avant R7, `root` n’écrit la confirmation qu’après avoir établi la durabilité de D | Décision 15 ; méthode et conduite en cas d’échec [O] | DOC : revue du protocole. ISO : trace d’un prototype | L’ordre d’exécution du code testé | La durabilité de D ; qu’un signal de réussite vaille durabilité ; le code futur |
| Prop-2 | Le logiciel ferme pour tout état absent, non confirmé, illisible ou discordant, et refuse un contenu partiel ou mélangé comme illisible ou discordant | Décision 15 | ISO : matrice d’états et contrôle d’intégrité | Aucun cas ouvert parmi les états énumérés | Les états non énumérés ; un compte de service compromis (J.6) |
| Prop-3 | Seul `root` écrit D et sa confirmation | T-3 ; permissions de D et inscription à l’inventaire [O] | DOC : T-3. REL : droits qui permettent d’écrire D et sa confirmation, une fois la représentation et l’emplacement choisis ; pour une représentation fondée sur des fichiers, tout attribut qui en accorde l’écriture, notamment propriétaires et modes, pour ces fichiers et pour chaque répertoire de leur chemin ; pour une autre représentation, droits équivalents à définir [O] | Les droits à la date du relevé | Une dérive ultérieure ; `root` compromis |
| Prop-4 | Un échec de synchronisation signalé n’est jamais tenu pour une durabilité établie | Décision 15 ; conduite de `root` en cas d’échec [O] | ISO : injection d’échecs d’écriture | La conduite du code face aux erreurs injectées | Toutes les formes d’erreur réelles |
| Prop-5 | Le service et E vérifient sous B l’état courant de D à chaque opération concernée | Décision 15, « Portée » | ISO : trace d’un prototype | Le contrôle dans le code testé | Le code futur ; un compte de service compromis (J.6) |

**Hypothèses techniques à vérifier [H].** La colonne « Origine » renvoie au L.8, point 8. La colonne « Dépend de » signale un choix qui n’a pas été fait : l’hypothèse n’est évaluable qu’après ce choix. La colonne « Renvoi » désigne l’hypothèse relevant de l’hébergeur qui porte la part hors de portée du système invité ; elle ne permet pas d’accepter la ligne elle-même.

| N° | Hypothèse | Origine | Dépend de | Preuve possible | Ce qu’elle établirait | Ce qu’elle ne prouverait pas | Renvoi |
|---|---|---|---|---|---|---|---|
| Hyp-1 | Les verrous B, G, M et W sont libérés à la mort du processus qui les tient | L.8, point 8 | Mécanisme de verrouillage [O] | DOC : documentation système, par déduction. ISO : arrêt brutal. RÉEL : seulement sur autorisation distincte | La libération sur le noyau testé, pour le mécanisme testé | Un processus bloqué non tué ; un descripteur hérité | Aucun |
| Hyp-2 | Une lecture restitue l’ancien ou le nouveau contenu de D, jamais un mélange | L.8, point 8 | Représentation de D | DOC : atomicité de visibilité seulement. ISO : lecteurs concurrents | Ce comportement du système pour la représentation testée | La tenue en cas de panne | Aucun |
| Hyp-3 | Si la représentation retenue emploie une réécriture en place ou un renommage, chaque opération de ce type est atomique en cas de panne. Si elle n’en emploie ni l’un ni l’autre, cette absence doit elle-même être établie par une revue documentée de la représentation retenue et du code qui la met en œuvre ; sans cette preuve, la ligne reste `non établie` et bloque le constat (critère 3) | L.8, point 8 | Représentation de D | DOC : journal du système de fichiers ; revue de la représentation et du code, pour établir l’absence de ces opérations. ISO : rejeu de coupures | Ce résultat pour l’opération testée, au niveau du système de fichiers, dans ce modèle ; ou l’absence de ces opérations dans ce qui a été revu | Une garantie générale ; la couche physique | Hyp-13, Hyp-14 |
| Hyp-4 | Après une panne, l’état persisté de D et de sa confirmation est l’un des états écrits | L.8, point 8 | Représentation de D | DOC : journal du système de fichiers. ISO : rejeu de coupures | Ce résultat au niveau du système de fichiers, dans ce modèle | La couche physique | Hyp-13, Hyp-14 |
| Hyp-5 | Un échec de synchronisation est signalé à `root` | Proposée | Aucun choix | DOC : documentation du noyau. ISO : injection d’échecs d’écriture | Le signalement des erreurs injectées | Une perte silencieuse | Hyp-15 |
| Hyp-6 | Le comportement d’une synchronisation relancée après un échec est établi | L.8, point 8 | Aucun choix | DOC : documentation du noyau. ISO : injection d’échecs d’écriture | Le comportement sur le noyau testé | Qu’une relance réussie vaille durabilité | Aucun |
| Hyp-7 | Une méthode d’achèvement après un échec de synchronisation est établie | L.8, point 8, points ouverts | Méthode d’achèvement [O] | DOC : documentation du noyau. ISO : injection d’échecs d’écriture | Le comportement de la méthode testée | Son efficacité en panne réelle | Aucun |
| Hyp-8 | Pour une représentation fondée sur des fichiers, une écriture dont la synchronisation du fichier et du répertoire est confirmée est durable. Pour toute autre représentation, l’hypothèse équivalente et sa preuve restent à définir [O] ; tant qu’elles ne sont pas définies et vérifiées, cette ligne reste `non établie` et bloque le constat (critère 3) | L.8, point 8 | Représentation de D | DOC : documentation système. ISO : rejeu de coupures. RÉEL : réinitialisation brutale, seulement sur autorisation distincte | La tenue du système invité si le périphérique respecte les vidages | La tenue chez l’hébergeur | Hyp-13 |
| Hyp-9 | Écrire ou perdre la confirmation n’altère pas une D déjà durable | Condition d’O1-B | Représentation de D | DOC : journal du système de fichiers. ISO : rejeu à chaque point, avec comparaison octet par octet | La non-interférence au niveau du système de fichiers, dans ce modèle | Les secteurs déchirés et la couche physique | Hyp-14 |
| Hyp-10 | Le système invité transmet bien les vidages | Proposée | Aucun choix | DOC : documentation du noyau. REL : cache d’écriture vu par le noyau | Ce que le noyau croit du périphérique | L’état réel du périphérique | Hyp-13 |
| Hyp-11 | Le système de fichiers portant P et D présente un profil à définir [O] | Proposée | Emplacement de D | REL | L’état à la date du relevé | Tout comportement en panne | Aucun |
| Hyp-12 | À la date du constat, l’environnement, volume tel que présenté au système invité compris, correspond au profil consigné dans le dossier de preuves pour Env-1 à Env-5 ; Env-6 relève de la décision 18 (critère 4) | Proposée | Emplacement de D | REL | L’état observable à la date du relevé | Que cet état restera inchangé ; la nature et le comportement des couches cachées par l’hébergeur | Hyp-13 à Hyp-16 |

**Profil d’environnement proposé [R].** Ce profil propose le contenu prévu par Hyp-11 et la référence de Hyp-12. Il énumère les caractéristiques à consigner ; il n’en fixe aucune valeur, ne choisit aucun emplacement de D et n’autorise aucun relevé. Le profil consigné regroupe Env-1 à Env-6 ; la part propre au système de fichiers portant P et D, visée par Hyp-11, est formée d’Env-2 et d’Env-3.

| N° | Caractéristique à consigner | Hypothèses concernées | Preuve possible | Observable depuis le système invité | Ce que la valeur consignée ne prouverait pas |
|---|---|---|---|---|---|
| Env-1 | Noyau en cours d’exécution | Hyp-1 à Hyp-10 | REL ; DOC pour son comportement | Oui | Son comportement en panne |
| Env-2 | Type du système de fichiers portant P et D | Hyp-2 à Hyp-4, Hyp-8, Hyp-9 | REL ; DOC | Oui, une fois l’emplacement de D choisi | Son comportement en panne |
| Env-3 | Options de montage de ce système de fichiers, dont celles qui déterminent la journalisation et les vidages | Hyp-3, Hyp-4, Hyp-8, Hyp-9 | REL ; DOC | Oui, une fois l’emplacement de D choisi | Leur effet réel sur le périphérique |
| Env-4 | Volume tel qu’il est présenté au système invité : périphérique présenté et propriétés que le noyau en expose, hors cache d’écriture (Env-5) | Hyp-8, Hyp-10, Hyp-12 | REL | Oui, pour ce qui est présenté seulement ; les couches de stockage de l’hébergeur ne le sont pas | La nature et le comportement des couches cachées par l’hébergeur ; la correspondance avec le type de volume examiné pour Env-6 (Hyp-13 à Hyp-16) |
| Env-5 | État du cache d’écriture du périphérique tel que vu par le noyau | Hyp-8, Hyp-10 | REL | Oui, comme ce que le noyau en croit | L’état réel du périphérique (Hyp-13) |
| Env-6 | Type de volume et engagements applicables de l’hébergeur | Hyp-13 à Hyp-16 | DOC : examen selon la décision 18 | Non | Leur exécution effective |

Règles proposées [R] :

- chaque valeur est consignée datée, avec ses empreintes, dans le dossier de preuves (critère 2) ;
- une valeur observable depuis le système invité n’est consignée que si elle a été relevée ; une simple ressemblance d’offre ou de configuration ne suffit pas (critère 7) ; une caractéristique qui ne peut pas être relevée laisse `non établie` l’hypothèse concernée (critère 10) ;
- Env-6 relève de la décision 18 : il n’est jamais présenté comme vérifié ;
- la colonne « Hypothèses concernées » est une base proposée pour les caractéristiques pertinentes du critère 7 ;
- le profil ne prétend pas être complet : une caractéristique dont l’influence sur une hypothèse viendrait à être établie y est ajoutée, et les preuves concernées sont réexaminées.

Restent [O] : l’adoption de cette liste et sa complétude ; son application au système de fichiers qui portera D, qui dépend de l’emplacement de D ; les valeurs, qui exigent un relevé autorisé séparément ; les caractéristiques pertinentes du critère 7 pour chaque hypothèse.

**Contrôle des changements ultérieurs [O].** Aucune preuve ponctuelle ne démontre que l’environnement restera inchangé (G1 l. 397). Ce point n’est donc pas une hypothèse à vérifier par un relevé. La méthode de ce contrôle, sa fréquence et ses événements déclencheurs restent à décider [O]. Tant qu’ils ne sont pas décidés, le constat de suffisance ne peut pas être prononcé (critère 10).

**Générations pendant une période sans preuves valides [R].** Cette proposition précise, pour le critère 10, le sort des générations lorsque les preuves requises pour O1-B expirent, sont invalidées ou restent non établies. Elle ne modifie pas les décisions 15, 17 et 18, ne constate pas que la condition d’O1-B est satisfaite, qui reste [H], et ne choisit aucun mécanisme.

- **Qualification.** L’expiration ou l’invalidation d’une preuve requise est tenue pour une anomalie au sens de la décision 17, aux seules fins de déclencher la fermeture de la génération concernée. Elle ne signifie pas que D est altérée et ne fait pas entrer le système en S4. Cette fermeture s’ajoute aux cas de fermeture de la décision 15, qui restent inchangés.
- **Déclaration d’effectivité et preuves valides.** Avant le premier constat de suffisance, aucune génération n’est déclarée effective sous O1-B : la condition reste [H]. Après ce constat, tant que chaque élément requis conserve son statut du critère 3, `vérifiée` pour Prop-1 à Prop-5 et Hyp-1 à Hyp-12, `limite de confiance acceptée` selon la décision 18 pour Hyp-13 à Hyp-16, aucune nouvelle décision de suffisance n’est requise pour chaque génération ; la déclaration d’effectivité reste soumise aux conditions de la décision 15.
- **Génération déjà effective.** Si un élément requis expire ou est invalidé après la déclaration d’effectivité d’une génération, le système reste fermé pour cette génération au moins jusqu’au renouvellement des éléments de preuve concernés et à une décision distincte constatant de nouveau la suffisance de l’ensemble des preuves pour l’environnement en vigueur, chaque élément ayant de nouveau son statut du critère 3. Il n’y a ni retour automatique à la génération précédente, ni réouverture automatique.
- **Expiration à la date prévue.** La date d’expiration est connue d’avance. La fermeture prend effet à cette date si les preuves n’ont pas été renouvelées et leur suffisance constatée de nouveau auparavant.
- **Changement connu.** Les preuves concernées sont invalidées par le changement (critère 10). La fermeture prend effet au plus tard au moment du changement.
- **Invalidation découverte après coup.** Les preuves sont invalidées à compter de la date du changement ; si elle est inconnue, à compter du dernier relevé conforme pour un changement d’environnement ou de droits, et, pour un changement de représentation, d’emplacement ou de code, selon la sous-puce « Prise d’effet » du critère 10. Lorsqu’il est établi après coup qu’un outil de preuve est affecté d’un défaut, que la configuration isolée présente un écart ou un défaut, ou qu’une caractéristique isolée non désignée peut influer sur un résultat, le point de départ de l’invalidation est celui que fixe la sous-puce « Défaut ou écart établi après coup » du critère 10. Lorsqu’une incertitude sur la catégorie d’un élément apparaît après le constat sans résulter d’un changement, le point de départ de l’invalidation est l’apparition de cette incertitude, selon la sous-puce « Catégorie incertaine » du critère 10 ; si est établi ensuite l’un des cas que vise la sous-puce « Défaut ou écart établi après coup », à savoir un défaut d’un outil de preuve ou de sa configuration, un écart entre la configuration isolée désignée et celle effectivement testée ou un défaut de cette configuration, ou le fait qu’une caractéristique non désignée de l’environnement isolé peut influer sur le résultat d’un essai, il produit une invalidation distincte, dont le point de départ est celui que fixe cette sous-puce, aucune des deux dates ne remplaçant l’autre. Dans les autres cas où l’invalidation ne résulte pas d’un changement, hors ceux que fixent les sous-puces « Catégorie incertaine », « Défaut ou écart établi après coup » et « Écart ou défaut soupçonné » du critère 10, ou lorsqu’elle résulte d’un changement de date inconnue d’un élément dont la catégorie n’est pas établie, le point de départ de l’invalidation n’est fixé ni par la date d’un changement ni par le dernier relevé conforme, et reste à décider (critère 10). La fermeture prend effet dès la découverte et ne peut pas être rétroactive. Les opérations acceptées entre la date d’effet de l’invalidation et sa découverte se sont appuyées sur des preuves déjà invalides.
- **Date d’effet de l’invalidation.** Pour l’invalidation des preuves, le point de départ et la date d’effet désignent la même date : celle à compter de laquelle les preuves concernées sont tenues pour invalidées, telle que la fixent ce bloc et le critère 10. Pour un changement de représentation, d’emplacement ou de code connu d’avance, cette date peut précéder le changement, les invalidations prenant effet au plus tard quand il prend effet (sous-puce « Prise d’effet » du critère 10). Cette équivalence ne vise pas la fermeture : sa prise d’effet reste régie séparément par les règles de ce bloc et du critère 10, et sa date peut différer de celle de l’invalidation, notamment lorsque l’invalidation est découverte après coup. Elle ne modifie pas le régime des acceptations de Hyp-13 à Hyp-16, qui relève de la décision 18.
- **Horodatage des constats.** Chaque constat, qu’il s’agisse du premier constat de suffisance ou d’une décision distincte constatant de nouveau la suffisance, est daté de façon à permettre d’établir son ordre par rapport à chacun des événements pertinents suivants : une question de qualification effectivement posée et la qualification d’un indice (sous-puce « Écart ou défaut soupçonné » du critère 10), l’apparition d’une incertitude de catégorie (sous-puce « Catégorie incertaine »), l’établissement d’un défaut ou d’un écart (sous-puce « Défaut ou écart établi après coup ») et la déclaration d’effectivité d’une génération. Cet ordre établit que l’événement précède le constat ou qu’il le suit ; aucune catégorie distincte de simultanéité n’est créée. Lorsqu’un événement pertinent qui entraîne une invalidation survient, mais que son ordre par rapport au constat ne peut pas être établi, cette invalidation ne prend pas effet avant un instant qui suit ce constat. Cette règle de datation ne rend pas régulier un constat qui aurait pu être bloqué, faute d’ordre établi entre lui et un événement qui l’aurait bloqué ou qui aurait mis fin à ce blocage, par une attente de qualification ouverte (sous-puce « Écart ou défaut soupçonné ») ou par une propriété ou une hypothèse `non établie` au sens du critère 3, notamment parce qu’une preuve ne pouvait pas fonder le statut `vérifiée`, qu’un soupçon n’était pas levé ou qu’une preuve était tenue pour invalidée ; elle ne permet d’écarter ni ces règles distinctes, ni celle selon laquelle aucune génération n’est déclarée effective sous O1-B avant le premier constat de suffisance. Elle ne fixe ni le point de départ de l’échéance d’une attente, ni les concours entre invalidations qui restent à décider, et ne vise pas la fermeture, dont la prise d’effet reste régie par les règles de ce bloc et du critère 10. Elle ne vise ni le relevé qui établit Hyp-12 à la date du constat (sous-puce « Relevés »), ni sa relation temporelle avec le constat, et ne tranche ni le délai ni la validité des relevés. Elle n’écarte aucun résultat négatif, qui reste bloquant au titre du critère 9, et ne modifie pas le régime des acceptations de Hyp-13 à Hyp-16, qui relève de la décision 18. Aucun format, aucune horloge, aucune précision absolue ni aucun mécanisme d’horodatage n’est choisi.
- **Preuve impossible à renouveler.** Une preuve qui ne peut pas être renouvelée, notamment faute de relevé possible ou autorisé, reste `non établie`, et la génération concernée reste fermée.

Restent [O] : le sort de `c` en attente ; la portée de D-9 pendant cette fermeture ; les détails des opérations qui ferment ; la procédure de récupération et les modalités de réouverture ; le traitement des opérations acceptées entre la date d’effet d’une invalidation et sa découverte ; le sort d’un constat déjà prononcé lorsque l’ordre ne peut pas être établi entre ce constat et l’ouverture ou la fin d’un blocage, qu’il s’agisse d’une attente de qualification ouverte ou d’une propriété ou d’une hypothèse `non établie` au sens du critère 3, ainsi que celui d’une déclaration d’effectivité dont l’ordre par rapport au constat ne peut pas être établi.

**Hypothèses relevant de l’hébergeur [H].** Leur désignation ci-dessous est proposée [R]. Elles relèvent de la décision 18 : elles peuvent seulement devenir des limites de confiance explicites et ne sont jamais vérifiées. L’examen d’un engagement n’établit pas son exécution.

| N° | Hypothèse | Origine | Élément à examiner | Ce qu’il permettrait | Ce qu’il ne prouverait pas |
|---|---|---|---|---|---|
| Hyp-13 | L’hôte ne confirme un vidage qu’une fois les données persistantes | Proposée | Type de volume et engagements applicables | Savoir à quoi l’hébergeur s’engage | Son exécution effective |
| Hyp-14 | Une écriture n’altère pas des blocs voisins sur l’hôte | Proposée | Type de volume et engagements applicables | Savoir à quoi l’hébergeur s’engage | Le comportement réel de la pile de stockage |
| Hyp-15 | L’hôte signale au système invité une écriture ou un vidage qu’il n’a pas pu honorer | Proposée | Type de volume et engagements applicables | Savoir à quoi l’hébergeur s’engage | L’absence de perte silencieuse |
| Hyp-16 | Le volume ne recule pas silencieusement | Proposée | Type de volume et engagements applicables | Savoir à quoi l’hébergeur s’engage | L’absence de recul |

**Limites des preuves.**

- Une réinitialisation brutale prouve la tenue après un crash du système invité, pas celle du stockage de l’hébergeur (G1 l. 119).
- Un essai isolé ne prouve pas le comportement du stockage de l’hébergeur : il montre le comportement du code et du système invité sous un périphérique modélisé.
- L’exigence X4 de G1 vise les transactions SQLite : sa réussite ne dit rien de D, et cette proposition ne la modifie pas.
- Un résultat positif montre seulement qu’aucun contre-exemple n’a été trouvé dans les cas couverts.

**Critère de constat proposé [R].** Une décision ultérieure pourrait constater que les preuves sont suffisantes si, et seulement si, tous ces points sont vérifiables :

1. **Choix préalables.** Une représentation de D, avec son emplacement, et un mécanisme de verrouillage ont été retenus par décisions distinctes.
2. **Environnement.** Le profil constaté à une date est identifié dans un dossier de preuves daté, conservé avec ses empreintes.
3. **Statuts distincts.** Chaque propriété de Prop-1 à Prop-5 et chaque hypothèse de Hyp-1 à Hyp-12 est `vérifiée`, avec une preuve référencée et datée. Cette vérification vaut pour sa date et ne démontre pas que l’environnement restera inchangé. Chaque hypothèse de Hyp-13 à Hyp-16 est `limite de confiance acceptée`, jamais `vérifiée`. Tout autre état est `non établie` et bloque le constat.
4. **Limites de confiance (décision 18).** Pour chaque hypothèse de Hyp-13 à Hyp-16, le type de volume et les engagements applicables de l’hébergeur sont identifiés et examinés, puis le propriétaire l’accepte explicitement. Si ces éléments sont absents ou ambigus, elle reste `non établie`, et O1-B demeure [H] et bloquée. Une hypothèse de Hyp-1 à Hyp-12 ne peut pas être acceptée ainsi.
5. **Rejeu.** En environnement isolé, à chaque point de vidage de la représentation retenue, une D dont la durabilité a été établie reste identique octet pour octet, et l’état relu est concordant ou fermant. Aucune exception n’est tolérée.
6. **Injection d’échecs.** En environnement isolé, à chaque synchronisation, un échec signalé n’entraîne jamais la confirmation.
7. **Sources de preuve.** Les essais sont proposés en environnement isolé. Un essai isolé établit le comportement du prototype et de la configuration effectivement testés ; il ne prouve pas à lui seul le comportement du serveur cible. Le rattachement de ce résultat à l’environnement cible exige un relevé en lecture seule, autorisé séparément, établissant la correspondance des caractéristiques pertinentes pour l’hypothèse et la représentation de D évaluées. Une simple ressemblance d’offre ou de configuration ne suffit pas à établir cette correspondance. Pour une hypothèse dont la vérification repose sur le rattachement d’un essai isolé à l’environnement cible, si la correspondance pertinente ne peut pas être établie, cette hypothèse reste `non établie` et O1-B demeure [H]. Les hypothèses intrinsèquement invérifiables depuis le système invité et relevant de l’hébergeur suivent le régime de la décision 18 : elles ne sont jamais présentées comme vérifiées et ne peuvent être acceptées que comme limites de confiance explicites, selon les conditions de cette décision. Aucun essai sur le serveur cible, notamment avec coupure ou arrêt brutal, n’est requis par défaut : un tel essai exigerait une décision et une autorisation distinctes, et toute action sur le serveur, lecture seule comprise, exige une autorisation distincte. Les caractéristiques pertinentes pour ce rattachement restent à fixer [O].
8. **Fermeture.** Prop-2 est vérifiée, y compris lorsque `c` de g+1 est consignée.
9. **Résultat négatif.** Une seule altération de D, ou une ouverture à tort, bloque le constat.
10. **Changements ultérieurs.** Le contrôle proposé combine des déclencheurs et une durée de validité des relevés ; il réduit le délai de détection d’un changement, mais ne démontre pas que l’environnement restera inchangé.
    - **Environnement et droits.** Un changement connu ou constaté de noyau, de système de fichiers, d’options de montage, de volume, d’offre d’hébergement ou des engagements applicables de l’hébergeur invalide les preuves et les acceptations concernées ; une preuve dont il n’est pas établi qu’elle n’est pas concernée est tenue pour invalidée. Un changement connu ou constaté des droits qui permettent d’écrire D ou sa confirmation invalide de même la preuve de Prop-3 ; le relevé de ces droits ne vaut lui aussi que pour une durée bornée, à l’expiration de laquelle Prop-3 redevient `non établie`.
    - **Représentation et emplacement.** Un changement de la représentation de D, qui suppose une nouvelle décision au titre du critère 1, invalide les preuves qui en dépendent explicitement : Hyp-2 à Hyp-4, Hyp-8 et Hyp-9, la vérification de Prop-3 et le rejeu du critère 5 obtenus pour la représentation précédente. Les renvois de ces lignes vers Hyp-13 à Hyp-16 sont alors à réexaminer, distinctement des acceptations elles-mêmes. Un changement de l’emplacement de D, qui suppose aussi une décision au titre du critère 1, y compris un déplacement sur le même système de fichiers, invalide Hyp-11, Hyp-12 et la vérification de Prop-3.
    - **Code évalué, outils de preuve et environnement.** Quatre catégories sont distinguées pour appliquer les sous-puces voisines ; leur délimitation reste à décider (« Restent à décider »).
      - **Code évalué.** Le code, prototype ou mis en œuvre, qui écrit, confirme, lit ou vérifie D ou sa confirmation et dont le comportement fait l’objet d’une preuve, avec les dépendances et la configuration qui en déterminent l’exécution. Le noyau, le système de fichiers, les options de montage, le volume et les droits de l’environnement cible n’en font pas partie : ils relèvent de la sous-puce « Environnement et droits ». Chaque preuve qui porte sur le comportement du code évalué, notamment celles qu’énumère la sous-puce « Code », désigne la version exacte évaluée, dépendances et configuration comprises, consignée dans le dossier de preuves daté visé au critère 2 ; cette identification est une exigence propre à L.9, le critère 2 ne visant que le profil de l’environnement cible, et aucun format, outil ni mécanisme d’identification n’est choisi. Une preuve qui ne la désigne pas ne peut pas fonder le statut `vérifiée` (critère 3). Une preuve ne vaut que pour la version qu’elle désigne : une vérification obtenue sur un prototype reste à reprendre sur le code mis en œuvre.
      - **Outils de preuve.** Les scripts, injecteurs, bancs d’essai, outils de relevé ou de comparaison et leur configuration, qui provoquent, observent, relèvent ou comparent le comportement du code évalué ou l’état de l’environnement. Ils ne font pas partie du code évalué, même lorsqu’ils lisent D pour la comparer.
      - **Environnement cible.** Les éléments que vise la sous-puce « Environnement et droits », dont le noyau et le système de fichiers cibles, qui restent dans cette catégorie.
      - **Environnement isolé.** Le noyau, le système de fichiers, le périphérique modélisé et les autres éléments de l’environnement dans lequel un essai isolé est exécuté. Il n’est ni l’environnement cible ni une partie du code évalué. Ses caractéristiques font partie de la configuration effectivement testée (critère 7). Chaque essai isolé désigne la configuration exacte testée, consignée dans le dossier de preuves daté visé au critère 2 ; cette identification est une exigence propre à L.9, le critère 2 ne visant que le profil de l’environnement cible, et aucun format, outil ni mécanisme d’identification n’est choisi. Un essai qui ne la désigne pas ne peut pas fonder le statut `vérifiée` (critère 3). Le résultat ne vaut que pour cette configuration et ne se rattache à l’environnement cible que selon le critère 7. Le périphérique modélisé ne représente pas les couches de stockage de l’hébergeur : aucun résultat obtenu avec lui n’établit Hyp-13 à Hyp-16, qui relèvent de la décision 18 (bloc « Limites des preuves »).
      - **Identification de la configuration isolée.** La configuration exacte que chaque essai isolé désigne (sous-puce « Environnement isolé ») est celle en vigueur pendant cet essai. Sa désignation comprend au moins : le noyau de l’environnement isolé, avec sa version exacte et ses paramètres ; le type de chaque système de fichiers qui porte la représentation évaluée de D ou sa confirmation, avec ses paramètres de création et ses options de montage ; le périphérique modélisé, avec le comportement qu’il simule, notamment pour les écritures non vidées, les vidages, les échecs signalés et les coupures, ainsi que son cache d’écriture, tel qu’il est simulé et tel que le noyau de l’environnement isolé le voit ; toute autre caractéristique de l’environnement isolé dont il est établi qu’elle peut influer sur le résultat de l’essai, que cela soit établi avant ou après l’essai. Elle permet de distinguer cette configuration de toute configuration qui en diffère par l’une de ces caractéristiques. Une désignation qui omet l’une d’elles est incomplète et ne désigne pas la configuration exacte : tant qu’elle l’est, l’essai ne peut pas fonder le statut `vérifiée`, et la propriété ou l’hypothèse concernée reste `non établie` et bloque le constat (critère 3) ; si l’incomplétude apparaît après le constat, notamment parce qu’il est établi après coup qu’une caractéristique non désignée peut influer sur le résultat, les preuves concernées sont tenues pour invalidées, avec les conséquences du bloc « Générations pendant une période sans preuves valides ». La désignation peut être complétée après l’essai : la valeur de chaque caractéristique omise en vigueur pendant l’essai doit être établie, une valeur constatée après l’essai ne suffisant pas s’il n’est pas établi qu’elle était déjà celle de l’essai, puis consignée, datée, dans le dossier de preuves, comme complément distinct de la désignation initiale. L’essai peut alors fonder le statut `vérifiée` pour la configuration ainsi complétée seulement, si les autres conditions requises par L.9 sont remplies, notamment celles des critères 3 et 7 et des autres sous-puces du critère 10 ; après le constat, le complément peut servir au renouvellement des éléments de preuve que prévoit le bloc « Générations pendant une période sans preuves valides », et la génération concernée reste fermée jusqu’à la décision distincte que ce bloc exige. L’omission d’une caractéristique n’est pas, à elle seule, un écart entre la configuration désignée et celle effectivement testée au sens de la sous-puce « Changement de l’environnement isolé » : elle relève de la présente sous-puce. Si l’établissement de la valeur omise révèle un tel écart, ou si un écart ou un défaut de la configuration est établi par ailleurs, la sous-puce « Changement de l’environnement isolé » s’applique en outre, et le complément ne vaut pas justification qu’une preuve n’en a pas été affectée. Cette désignation ne remplace ni celle de la version exacte du code évalué (sous-puce « Code évalué »), ni l’identification de l’outil employé, de sa version et de sa configuration, qui reste à décider, y compris pour un élément de l’environnement isolé qui joue aussi le rôle d’instrument (sous-puce « Rôles multiples »). Elle n’attribue de catégorie à aucun élément (sous-puce « Catégorie incertaine ») et n’établit pas la correspondance avec l’environnement cible, qui relève du critère 7 ; le critère 2 ne vise que le profil de l’environnement cible. Elle n’exige ni la conservation ni la reproductibilité de la configuration isolée. Aucun format, outil ni mécanisme d’identification n’est choisi.
      - **Changement de l’environnement isolé.** Un changement ultérieur de l’environnement isolé, notamment de son noyau, de son système de fichiers, de son périphérique modélisé ou d’une autre caractéristique testée, ne modifie pas ce qu’un essai antérieur établit pour la configuration qu’il désigne et n’invalide pas, à lui seul, cette preuve. Cette règle ne s’applique qu’à un élément dont l’appartenance à l’environnement isolé, et non au code évalué, est établie ; sinon, la sous-puce « Catégorie incertaine » s’applique. Si un écart entre la configuration désignée et celle effectivement testée, ou un défaut de la configuration antérieure, est établi, notamment à l’occasion du changement, les preuves concernées sont tenues pour invalidées, sauf s’il est établi, par une justification consignée dans le dossier de preuves, qu’elles n’ont pas été affectées. Un élément qui jouait aussi le rôle d’instrument relève en outre de la sous-puce « Changement et défaut d’outil ». Un résultat obtenu sur la configuration modifiée ne vaut que pour celle-ci. Un changement de l’environnement cible relève de la sous-puce « Environnement et droits » : il invalide les preuves concernées, y compris les résultats isolés dont le rattachement reposait sur la correspondance avec l’état antérieur de la cible (critère 7).
      - **Changement pendant un essai.** La configuration isolée change pendant un essai lorsqu’une caractéristique que sa désignation doit comprendre (sous-puce « Identification de la configuration isolée ») prend, au cours de l’essai, une valeur différente de celle qu’elle avait jusque-là. Un événement que la configuration désignée prévoit et dont elle décrit le comportement, notamment une coupure, un échec signalé ou une écriture non vidée simulés par le périphérique modélisé, ou la reprise qui suit une coupure lorsqu’elle rétablit les valeurs désignées, n’est pas un tel changement, pas plus que ses effets prévus par cette description ; une modification de ce comportement en est un. Les effets de ces événements sur D, sur sa confirmation et sur l’état relu sont des résultats de l’essai, soumis notamment aux critères 5, 6 et 9. Hors la règle sur les résultats négatifs, qui vaut quel que soit l’élément qui a changé, cette sous-puce ne s’applique qu’à un élément dont l’appartenance à l’environnement isolé est établie ; sinon, la sous-puce « Catégorie incertaine » s’applique, et un élément qui joue aussi le rôle d’instrument relève en outre des sous-puces « Rôles multiples » et « Changement et défaut d’outil ». La première phrase de la sous-puce « Changement de l’environnement isolé », qui vise un changement postérieur à l’essai, ne s’applique pas à un changement survenu pendant celui-ci. Un essai au cours duquel la configuration change ne peut fonder le statut `vérifiée` que par séquences, chacune obtenue sous une seule configuration, ou, pour un changement non désigné, par un résultat maintenu selon la règle d’écart ci-dessous. Ce découpage n’est admis que si la désignation initiale de l’essai distingue chaque séquence, en désigne la configuration selon la sous-puce « Identification de la configuration isolée », sous réserve du complément que celle-ci prévoit, et situe chaque changement par rapport aux résultats de l’essai. Chaque résultat est rattaché à la séquence pendant laquelle il a été obtenu : il ne vaut que pour la configuration de cette séquence, ne se rattache à l’environnement cible que selon le critère 7 et ne contribue aux critères 5 et 6 que pour cette configuration. Un résultat qui ne peut pas être rattaché à une seule séquence, notamment parce qu’il a été obtenu pendant un changement ou que sa position par rapport à un changement n’est pas établie, ne contribue à aucune couverture et ne peut pas fonder le statut `vérifiée`. Les couvertures obtenues sous des configurations différentes, dans un même essai ou dans des essais distincts, ne se cumulent pas tant que leur comparabilité et les conditions de ce cumul ne sont pas établies : jusque-là, le critère 5 n’est satisfait pour une configuration que si chaque point de vidage y est couvert, et le critère 6 que si chaque synchronisation y est couverte. Un changement survenu pendant l’essai que la désignation initiale ne désigne pas ou ne situe pas, qu’il porte sur une caractéristique désignée ou omise, est un écart entre la configuration désignée et celle effectivement testée : la sous-puce « Changement de l’environnement isolé » s’applique, et les résultats de l’essai sont tenus pour invalidés, sauf un résultat dont il est établi, par une justification consignée dans le dossier de preuves, qu’il n’a pas été affecté. Établir qu’un résultat a été obtenu avant ce changement peut fonder une telle justification. Un résultat ainsi maintenu ne vaut que pour la configuration désignée. Le complément prévu à la sous-puce « Identification de la configuration isolée » établit seulement la valeur d’une caractéristique omise, unique pendant l’essai ou, pour un essai découpé selon sa désignation initiale, pendant chaque séquence ; il n’ajoute ni changement, ni chronologie, ni séquence. Si l’établissement de cette valeur révèle qu’elle a changé pendant l’essai ou la séquence, la règle d’écart ci-dessus s’applique. Ni un complément ni un découpage ultérieur en séquences ne rattachent un résultat à la configuration modifiée ni ne tiennent lieu de la justification exigée. Un résultat négatif n’est écarté ni par le changement, ni par son absence de la désignation initiale, ni par l’impossibilité de rattacher ce résultat à une séquence, ni par l’invalidation des résultats de l’essai, ni par son attribution au changement : chacun des deux résultats négatifs du critère 9, une altération de D et une ouverture à tort, bloque le constat selon ce critère dès lors qu’il survient pendant l’essai, qu’il soit constaté pendant celui-ci ou après, et quelle que soit la configuration en vigueur. Cette conséquence découle du critère 9, qui ne prévoit aucune exception, et n’en crée aucune ; un contre-exemple aux critères 5 ou 6 n’est pas davantage écarté par ces circonstances. Si ce résultat conduit à établir un défaut de la configuration, la sous-puce « Changement de l’environnement isolé » s’applique en outre aux autres preuves obtenues sous celle-ci. Un changement pendant un essai qui n’est établi qu’après le constat est un écart établi après coup : les preuves concernées sont tenues pour invalidées, sauf justification consignée, avec les conséquences du bloc « Générations pendant une période sans preuves valides » ; l’invalidation résultant de cet écart, et non d’un changement de l’environnement cible, de la représentation, de l’emplacement ou du code, son point de départ est celui que fixe la sous-puce « Défaut ou écart établi après coup ». Un changement du code évalué ou d’un outil de preuve pendant un essai relève des sous-puces qui leur sont propres. Aucun format, outil ni mécanisme d’identification ou de datation n’est choisi.
      - **Rôles multiples.** La catégorie d’un élément s’apprécie selon son rôle dans chaque preuve : objet de la preuve, condition de son exécution, ou instrument qui la provoque, l’observe ou la compare. Un même élément peut jouer plusieurs rôles, dans une même preuve ou dans des preuves différentes ; les règles de chaque catégorie concernée s’appliquent alors cumulativement. Notamment, un élément de l’environnement isolé qui injecte des pannes, observe ou compare est aussi un outil de preuve ; un outil qui modifie l’exécution du code évalué pendant une preuve fait aussi partie, pour cette preuve, de la configuration qui détermine cette exécution, et la preuve ne vaut pas, à elle seule, pour une exécution sans cet outil ; un élément du code évalué employé pour vérifier ou comparer le résultat d’une preuve reste soumis à la sous-puce « Code ». Aucun rôle n’est attribué par défaut : un élément dont le rôle dans une preuve n’est pas établi relève de la sous-puce « Catégorie incertaine ».
      - **Catégorie incertaine.** Aucune catégorie n’est attribuée par défaut à un élément intervenu dans la production d’une preuve ou dans l’exécution évaluée. Tant que sa nature, son rôle et son effet sur une preuve ne sont pas établis, cette preuve ne peut pas fonder le statut `vérifiée` : la propriété ou l’hypothèse concernée reste `non établie` et bloque le constat (critère 3) ; si l’incertitude apparaît après le constat, la preuve est tenue pour invalidée, avec les conséquences du bloc « Générations pendant une période sans preuves valides ». Il en va de même après un changement d’un tel élément ; la sous-puce « Code » précise cette conséquence pour un changement de code dont le rapport avec D n’est pas établi. L’absence de justification ne permet jamais de maintenir une preuve valide. Lorsque l’incertitude apparaît après le constat sans résulter d’un changement, le point de départ de l’invalidation est l’apparition de cette incertitude ; il n’est fixé ni par la date d’un changement ni par le dernier relevé conforme. La fermeture prend effet dès la découverte, conformément au bloc « Générations pendant une période sans preuves valides », et ne peut pas être rétroactive. Si l’un des cas que vise la sous-puce « Défaut ou écart établi après coup » est établi ensuite, y compris le fait qu’une caractéristique non désignée de l’environnement isolé peut influer sur le résultat d’un essai, il produit une invalidation distincte, dont le point de départ est celui que fixe cette sous-puce : les deux invalidations se cumulent, chacune conservant sa propre date, et aucune ne remplace l’autre. Cette règle de cumul ne vise que cet ordre ; elle ne tranche ni le concours entre l’invalidation due à l’incertitude et celle que produit la qualification d’un indice ou l’échéance d’une attente (sous-puce « Écart ou défaut soupçonné »), ni celui avec l’un des cas que vise la sous-puce « Défaut ou écart établi après coup » lorsqu’il est établi avant l’apparition de l’incertitude ou en même temps qu’elle, qui restent à décider. Cette règle ne tranche pas le concours entre l’invalidation produite dès la qualification d’un indice après le constat (sous-puce « Écart ou défaut soupçonné ») et celle qui résulte de l’établissement ultérieur du défaut ou de l’écart, qui reste à décider. Restent également à décider, pour une incertitude de catégorie apparue après le constat sans résulter d’un changement, le seuil qui distingue une incertitude pertinente d’un risque seulement théorique, ainsi que la façon d’établir et de dater son apparition. Le traitement des opérations acceptées entre ce point de départ et la découverte relève des points [O] de ce bloc. Ce point de départ ne vise que les preuves qui fondent le statut `vérifiée` (critère 3) : il n’écarte aucun résultat négatif, qui reste bloquant au titre du critère 9, lequel ne prévoit aucune exception. Il ne vise pas une invalidation qui résulte d’un changement d’un tel élément. Cette règle ne modifie pas le régime des acceptations de Hyp-13 à Hyp-16, qui relève de la décision 18.
      - **Changement et défaut d’outil.** Un changement d’un outil de preuve ou de sa configuration n’est pas un changement du code évalué et n’invalide pas, à lui seul, les preuves déjà produites. Un défaut établi d’un outil de preuve ou de sa configuration invalide les preuves produites avec cet outil, sauf s’il est établi qu’elles n’ont pas été affectées, notamment parce qu’elles l’ont été avec une version et une configuration non affectées ; à défaut de cette justification, elles sont tenues pour invalidées. Il n’invalide pas les preuves produites sans cet outil. Une preuve requise ainsi invalidée rend `non établie` la propriété ou l’hypothèse qu’elle soutenait (critère 3), et un relevé ainsi invalidé ne peut pas servir de dernier relevé conforme (sous-puce « Relevés »). Un défaut d’outil seul n’invalide pas les acceptations de Hyp-13 à Hyp-16, qui relèvent de la décision 18.
      - **Défaut ou écart établi après coup.** La présente sous-puce vise, lorsqu’ils sont établis après le constat, un défaut d’un outil de preuve ou de sa configuration (sous-puce « Changement et défaut d’outil »), un écart entre la configuration isolée désignée et celle effectivement testée ou un défaut de cette configuration (sous-puces « Changement de l’environnement isolé » et « Changement pendant un essai »), et le fait qu’une caractéristique non désignée de l’environnement isolé peut influer sur le résultat d’un essai (sous-puce « Identification de la configuration isolée »). La fermeture prend effet dès la découverte, conformément au bloc « Générations pendant une période sans preuves valides », et ne peut pas être rétroactive. Le point de départ de l’invalidation des preuves concernées en est distinct : ces cas n’étant pas des changements, il n’est fixé ni par la date d’un changement ni par le dernier relevé conforme. Pour chaque preuve concernée sur laquelle un constat s’est appuyé, ce point de départ est fixé au premier constat qui s’est appuyé sur elle, qu’il s’agisse du premier constat de suffisance ou d’une décision distincte constatant de nouveau la suffisance (bloc « Générations pendant une période sans preuves valides »). Ce constat en est le plancher : le point de départ ne lui est pas antérieur, et une preuve réutilisée par plusieurs constats ne reçoit pas un point de départ plus tardif. Ce plancher est une règle de datation : il ne déclare pas la preuve valide avant ce constat et ne remet pas en cause ce constat, qui n’est pas invalidé rétroactivement. Ce point de départ est un instant qui suit ce constat ; le constat est daté selon la puce « Horodatage des constats » du bloc « Générations pendant une période sans preuves valides ». Si une preuve concernée a déjà été tenue pour invalidée à compter de l’échéance d’une attente de qualification (sous-puce « Écart ou défaut soupçonné »), cette invalidation conserve la date d’effet que lui attribue cette sous-puce ; le défaut ou l’écart établi ensuite y ajoute une invalidation distincte, dont le point de départ est celui que fixe la présente sous-puce, même s’il est antérieur à l’échéance. Les deux motifs se cumulent, chacune des deux invalidations conservant sa propre date : aucune ne remplace l’autre. Cette règle de cumul ne vaut que pour l’invalidation produite à l’échéance d’une attente et, selon la sous-puce « Catégorie incertaine », pour celle qui résulte d’une incertitude de catégorie apparue après le constat sans résulter d’un changement, lorsque le défaut ou l’écart est établi après l’apparition de cette incertitude ; s’il est établi avant cette apparition ou en même temps qu’elle, le concours reste à décider, comme le prévoit cette sous-puce ; le concours entre l’invalidation produite dès la qualification d’un indice après le constat (sous-puce « Écart ou défaut soupçonné ») et celle qui résulte de l’établissement ultérieur du défaut ou de l’écart reste à décider. Le traitement des opérations acceptées entre ce point de départ et la découverte, y compris pendant chacune des périodes d’invalidation ainsi cumulées, relève des points [O] du même bloc. Ce point de départ ne vise que les preuves qui fondent le statut `vérifiée` (critère 3) : il n’écarte aucun résultat négatif, qui reste bloquant au titre du critère 9, lequel ne prévoit aucune exception. La présente sous-puce ne modifie pas le régime des acceptations de Hyp-13 à Hyp-16, qui relèvent de la décision 18.
      - **Écart ou défaut soupçonné.** Un écart ou un défaut est soupçonné lorsqu’une information propre à une preuve, à un essai ou à un élément déterminés est qualifiée d’indice concret soit d’un écart entre la configuration isolée désignée et celle effectivement testée, ou d’un défaut de cette configuration (sous-puces « Changement de l’environnement isolé » et « Changement pendant un essai »), soit d’un défaut d’un outil de preuve ou de sa configuration (sous-puce « Changement et défaut d’outil »), sans que cet écart ou ce défaut soit établi. Le seul fait qu’une information se rapporte à une preuve, à un essai ou à un élément n’en fait pas un indice ; les critères de cette qualification restent à décider. La qualification d’une information n’est en attente que lorsqu’une question de qualification la concernant a effectivement été posée, et jusqu’à ce qu’une réponse y mette fin selon les règles ci-dessous ; ni la seule présence d’une information, ni son examen, ni le seul fait qu’elle se rapporte à une preuve, à un essai ou à un élément n’ouvrent cette attente. La question posée est consignée dans le dossier de preuves, avec les preuves, essais, éléments et rôles auxquels elle se rapporte, et la réponse qui y est donnée l’est de même ; la consignation de la question est une obligation, non une condition de l’ouverture de l’attente, qui commence dès que la question est posée, et ni la consignation d’une information ni celle de son examen ne valent question de qualification. La façon dont la question est posée, qui la pose et qui y répond, ainsi que la façon de consigner la question et sa réponse et de les rattacher aux preuves, essais, éléments et rôles concernés, restent à décider. L’attente ne vaut ni qualification ni levée : elle n’est pas un statut du critère 3 et, hors l’effet de son échéance prévu ci-dessous, ne modifie le statut d’aucune preuve et n’invalide aucune preuve. Tant qu’une qualification est en attente au titre de la présente sous-puce, le constat de suffisance ne peut pas être prononcé, qu’il s’agisse du premier constat ou d’une décision distincte constatant de nouveau la suffisance, que prévoit le bloc « Générations pendant une période sans preuves valides » ; ce blocage porte sur le prononcé du constat, non sur le statut des preuves, et constitue une condition propre à la présente proposition, qui n’est pas tirée de la décision 17. Après un constat déjà prononcé, l’attente n’est tenue ni pour une invalidation, ni pour une anomalie au sens de la puce « Qualification » de ce bloc, et, hors l’effet de son échéance prévu ci-dessous, ne ferme pas une génération déjà déclarée effective. Après un tel constat, chaque attente de qualification a une échéance, distincte de l’expiration d’un relevé ou d’une preuve ; sa durée, son point de départ, notamment lorsque la date de la question n’est pas établie, et la possibilité d’une prolongation restent à décider. À l’échéance de l’attente, si aucune réponse n’y a mis fin, les preuves concernées, c’est-à-dire chaque preuve à laquelle la question se rapporte au titre de cette attente ou produite sous la configuration ou avec l’outil qu’elle vise à ce titre, et chaque preuve dont il n’est pas établi qu’elle n’est pas concernée par cette question, sont tenues pour invalidées faute de réponse, à compter de l’échéance, avec les conséquences du bloc « Générations pendant une période sans preuves valides » : la propriété ou l’hypothèse qu’elles soutenaient devient `non établie` (critère 3). La fermeture qui en découle selon la puce « Qualification » de ce bloc prend effet à l’échéance si, celle-ci étant connue, il est établi à cette date que l’attente n’a pas pris fin ; si le dépassement n’est établi qu’après coup, elle prend effet dès sa découverte et ne peut pas être rétroactive, le traitement des opérations acceptées entre l’échéance et cette découverte relevant des points [O] de ce bloc. Cette invalidation est un choix propre à la présente proposition, qui n’est pas tiré de la décision 17. L’échéance n’est pas une qualification : elle ne qualifie pas l’information d’indice, n’ouvre aucun soupçon, n’est pas une levée et ne met pas fin à l’attente, qui continue jusqu’à l’une des réponses prévues ci-dessous, aucun nouveau constat ne pouvant être prononcé tant qu’elle reste ouverte. Une réponse concluant que l’information n’est pas un indice, consignée après l’échéance, met fin à l’attente mais ne rétablit pas les preuves invalidées : la suffisance ne peut être constatée de nouveau qu’après le renouvellement des éléments de preuve et la décision distincte que prévoit ce bloc. L’échéance de chaque attente, au titre de la configuration isolée, d’un outil de preuve ou de chacun des rôles d’un élément, ne vaut que pour cette attente et n’invalide que les preuves qu’elle concerne. Ni une qualification ultérieure de l’information, ni l’échéance d’une autre attente ne modifient la date d’effet d’une invalidation déjà produite par une échéance. Restent également à décider la possibilité de nouvelles déclarations d’effectivité pendant l’attente, que l’attente, à elle seule, ne suspend ni n’autorise, et le sort des opérations acceptées pendant celle-ci. Parmi les réponses qui ne qualifient pas l’information d’indice, seule une réponse concluant qu’elle n’en constitue pas un met fin à l’attente, et seulement une fois consignée ; cette réponse n’a pas d’autre effet et n’est pas une levée, aucun soupçon n’existant alors. Une réponse qui laisse la qualification indéterminée, notamment un examen resté sans conclusion, ne met pas fin à l’attente, même consignée. Une réponse concluant que l’information constitue un indice met fin à l’attente en la qualifiant : les effets prévus ci-dessous pour un indice courent à compter de cette qualification, et non du début de l’attente, même si sa consignation vient ensuite ; après le constat, la fermeture qui en résulte ne peut pas être rétroactive. Une attente au titre de la configuration isolée et une attente au titre d’un outil de preuve sont distinctes, même lorsqu’elles portent sur la même information : chacune prend fin séparément, et la réponse donnée au titre de l’une ne vaut pas pour l’autre. Pour un élément qui joue plusieurs rôles (sous-puce « Rôles multiples »), une question de qualification qui le concerne est en attente au titre de chacun de ses rôles, les effets de ces attentes se cumulent, et l’attente ne prend fin qu’une fois terminée au titre de chacun. L’attente ne suspend ni l’application de la sous-puce « Catégorie incertaine », ni les effets d’un soupçon déjà qualifié à partir d’une autre information. Un risque seulement théorique, qui vaut pour tout essai ou tout outil sans reposer sur une information propre à une preuve, à un essai ou à un élément déterminés, n’est pas un soupçon : il ne modifie aucun statut, relève du bloc « Limites des preuves » et de la complétude des caractéristiques à désigner (sous-puce « Identification de la configuration isolée »), et ne vaut pas justification qu’une preuve n’a pas été affectée. Un indice est consigné dans le dossier de preuves dès sa qualification ; cette consignation est une obligation, non une condition de l’effet de la présente règle, qui commence à la qualification. Chaque soupçon suit cette règle pour lui-même : un soupçon portant sur la configuration isolée et un soupçon portant sur un outil de preuve sont traités séparément, même lorsqu’ils procèdent de la même information, et la levée de l’un ne lève pas l’autre. Pour un élément qui joue plusieurs rôles (sous-puce « Rôles multiples »), la règle s’applique cumulativement au titre de chacun d’eux, et le soupçon n’est levé qu’une fois levé au titre de chacun ; un doute sur sa catégorie relève en outre de la sous-puce « Catégorie incertaine ». Dès qu’une information est qualifiée d’indice et tant que le soupçon n’est pas levé, chaque preuve concernée, c’est-à-dire chaque preuve produite sous la configuration ou avec l’outil visés, ou à laquelle l’indice se rapporte, et chaque preuve dont il n’est pas établi qu’elle n’est pas concernée, ne peut pas fonder le statut `vérifiée` : la propriété ou l’hypothèse concernée reste `non établie` et bloque le constat (critère 3), et un relevé produit avec un outil visé ne peut pas servir de dernier relevé conforme (sous-puce « Relevés »). Si une information est qualifiée d’indice après le constat, les preuves concernées sont tenues pour invalidées dès cette qualification, avec les conséquences du bloc « Générations pendant une période sans preuves valides » ; la fermeture prend effet dès la qualification, même si la consignation ou l’examen de l’indice viennent ensuite, et elle ne peut pas être rétroactive. Après le constat, la levée du soupçon peut servir au renouvellement des éléments de preuve que prévoit ce bloc, et la génération concernée reste fermée jusqu’à la décision distincte qu’il exige. Le soupçon n’est levé pour l’ensemble des preuves concernées que s’il est établi, par une justification consignée dans le dossier de preuves, que l’écart ou le défaut n’existe pas ; il n’est levé pour une preuve donnée que s’il est établi de même qu’elle n’en a pas été affectée. Ni l’écoulement du temps, ni l’absence de confirmation ou de nouvel indice, ni un examen resté sans conclusion, ni un complément de la désignation ne le lèvent. Si l’écart ou le défaut est établi, la sous-puce qui le régit s’applique ; s’il l’est après le constat, le point de départ de l’invalidation est celui que fixe la sous-puce « Défaut ou écart établi après coup ». Ni l’attente d’une qualification, ni son échéance, ni un soupçon, ni sa qualification, ni l’examen qui suit, ni l’établissement d’un écart ou d’un défaut, y compris d’un défaut d’outil, n’écartent un résultat négatif : une altération de D et une ouverture à tort restent chacune bloquantes au titre du critère 9, y compris lorsque l’indice ou le défaut porte sur la configuration ou sur l’outil sous lesquels elles ont été produites ou avec lesquels elles ont été observées. Cette conséquence découle du critère 9, qui ne prévoit aucune exception, et n’en crée aucune. Ni une attente de qualification, ni son échéance, ni un soupçon n’invalident, à eux seuls, les acceptations de Hyp-13 à Hyp-16, qui relèvent de la décision 18. Aucun seuil, outil, méthode ni procédure de qualification, de consignation, d’examen ou de levée n’est choisi.
    - **Code.** Un changement du code évalué (sous-puce « Code évalué »), c’est-à-dire du code qui écrit, confirme, lit ou vérifie D ou sa confirmation, de ses dépendances ou de la configuration qui en détermine l’exécution, ne concerne que les preuves qui portent sur le comportement de ce code : les vérifications de Prop-1, Prop-2, Prop-4, Prop-5, de Hyp-3 et de Hyp-7, les résultats d’essais isolés de Hyp-2, Hyp-4 et Hyp-9 et les résultats des critères 5 et 6, obtenus sur la version précédente. Chacune de ces preuves est tenue pour invalidée, sauf s’il est établi que la nature du changement ne la concerne pas ; les éléments DOC de Hyp-2, Hyp-4 et Hyp-9, qui portent sur le système de fichiers, ne sont pas visés. La preuve de Prop-3 n’est invalidée par un changement de code que s’il modifie l’acteur qui écrit D ou sa confirmation, leur chemin ou les droits d’accès, ou s’il n’est pas établi qu’il ne les modifie pas. Pour un changement de code autre qu’un changement d’outil de preuve : s’il est établi qu’il ne relève pas du code évalué (sous-puce « Code évalué »), c’est-à-dire qu’il n’écrit, ne confirme, ne lit ni ne vérifie D ou sa confirmation et ne modifie ni les dépendances ni la configuration qui en déterminent l’exécution, il n’invalide aucune de ces preuves ; tant que ce n’est pas établi, ces preuves sont traitées comme pour un changement du code évalué, sans que le changement soit classé dans cette catégorie (sous-puce « Catégorie incertaine »). Cette phrase ne préjuge pas des effets possibles d’un changement ou d’un défaut d’un outil de preuve sur une preuve, qui relèvent de la sous-puce « Changement et défaut d’outil ». Un changement de code seul n’invalide pas les acceptations de Hyp-13 à Hyp-16, qui relèvent de la décision 18.
    - **Prise d’effet.** Pour un changement dont la date est connue, les invalidations prévues pour la représentation, l’emplacement et le code prennent effet au plus tard quand le changement prend effet. Si un tel changement est découvert après coup, les preuves concernées sont invalidées à compter de sa date, comme pour les autres changements. Si cette date est inconnue, le dernier relevé conforme ne permet pas de la situer. Lorsqu’il est établi que l’élément changé appartient à la représentation de D, à son emplacement ou au code évalué (sous-puce « Code évalué »), le point de départ de l’invalidation est alors fixé, pour chaque preuve concernée sur laquelle un constat s’est appuyé, au premier constat qui s’est appuyé sur elle, qu’il s’agisse du premier constat de suffisance ou d’une décision distincte constatant de nouveau la suffisance (bloc « Générations pendant une période sans preuves valides »). Ce constat en est le plancher : le point de départ ne lui est pas antérieur, et une preuve réutilisée par plusieurs constats ne reçoit pas un point de départ plus tardif. Ce plancher est une règle de datation : il ne déclare pas la preuve valide avant ce constat et ne remet pas en cause ce constat, qui n’est pas invalidé rétroactivement. Ce point de départ est un instant qui suit ce constat ; le constat est daté selon la puce « Horodatage des constats » du bloc « Générations pendant une période sans preuves valides ». Ce point de départ ne vise que les preuves qui fondent le statut `vérifiée` (critère 3) : il n’écarte aucun résultat négatif, qui reste bloquant au titre du critère 9, lequel ne prévoit aucune exception. La règle du plancher ne s’applique pas lorsque cette appartenance n’est pas établie, notamment pour un changement de code traité comme un changement du code évalué sans être classé dans cette catégorie (sous-puces « Code » et « Catégorie incertaine ») : le point de départ reste alors à décider. Dans tous les cas de découverte après coup, la fermeture prend effet dès la découverte, comme le prévoit le bloc « Générations pendant une période sans preuves valides », et ne peut pas être rétroactive ; le traitement des opérations acceptées entre le point de départ de l’invalidation et la découverte relève des points [O] de ce bloc. La présente sous-puce ne modifie pas le régime des acceptations de Hyp-13 à Hyp-16, qui relève de la décision 18.
    - **Relevés.** Le dossier de preuves comporte un relevé établissant Hyp-12 à la date du constat, puis, après chaque changement connu, un nouveau relevé et, le cas échéant, de nouvelles preuves, avant que les preuves concernées soient de nouveau tenues pour valides. Chaque relevé ne vaut que pour une durée bornée ; à son expiration, Hyp-12 redevient `non établie` jusqu’à un nouveau relevé. Un relevé renouvelé peut révéler un écart au profil consigné, dans la mesure où cet écart porte sur une caractéristique relevée et observable depuis le système invité. Il ne détecte ni un changement survenu puis annulé entre deux relevés, ni un changement invisible depuis le système invité. Une caractéristique qui ne peut pas être relevée laisse `non établie` l’hypothèse concernée. Un changement d’environnement ou de droits constaté après coup invalide les preuves concernées à compter de sa date ou, si elle est inconnue, à compter du dernier relevé conforme. Pour un changement de représentation, d’emplacement ou de code découvert après coup, le point de départ est celui précisé dans la sous-puce « Prise d’effet ». Le risque d’un changement non détecté entre deux relevés n’est pas couvert ; lorsqu’il relève du système invité, il ne peut pas être accepté comme limite de confiance (critère 4).
    - Restent à décider [O] : la durée de validité des relevés ; les moyens de connaître les changements, mises à jour automatiques comprises (G1 l. 397) ; le traitement des générations installées pendant une période où les preuves concernées sont invalidées ou non établies ; l’autorisation de chaque relevé ; pour l’horodatage des constats (puce « Horodatage des constats » du bloc « Générations pendant une période sans preuves valides » ; sous-puces « Défaut ou écart établi après coup » et « Prise d’effet »), son format, sa précision et son mécanisme ; la délimitation du code évalué, de ses dépendances et de la configuration qui en détermine l’exécution, celle des outils de preuve et de leur configuration, et celle de l’environnement isolé, qui dépendent de l’architecture retenue ; la frontière entre les dépendances du code évalué et les éléments de l’environnement que ne vise pas la sous-puce « Environnement et droits », notamment les bibliothèques système et l’environnement d’exécution ; la façon d’identifier la version exacte évaluée ; la façon d’identifier la configuration de l’environnement isolé effectivement testé, dont le format, l’outil et le mécanisme d’identification, et la complétude des caractéristiques à désigner ; la façon d’établir et de consigner, dans la désignation initiale, chaque changement de la configuration isolée pendant un essai et la position de chaque résultat par rapport à lui, ainsi que l’antériorité d’un résultat à un changement non désigné ; la façon d’établir qu’une caractéristique isolée peut influer sur un résultat et, après coup, quelle était sa valeur pendant l’essai ; la façon d’établir un écart entre la configuration isolée désignée et celle effectivement testée, ou un défaut de la configuration antérieure, et qu’une preuve n’en a pas été affectée ; les critères de qualification d’un indice concret d’écart ou de défaut de la configuration isolée, notamment ce qui le distingue d’un risque seulement théorique, la façon dont une question de qualification portant sur la configuration isolée est posée, qui la pose et qui y répond, ainsi que la façon de consigner un indice, de déterminer les preuves qu’il concerne et d’établir sa levée ; la conservation ou la reproductibilité de la configuration isolée testée ; l’indépendance requise entre l’instrument et l’objet d’une preuve, notamment lorsqu’un élément du code évalué sert à vérifier ou comparer son résultat ; les conditions auxquelles une preuve obtenue sur une exécution instrumentée peut valoir pour une exécution sans cet instrument ; la façon d’établir qu’un changement de code est sans rapport avec D ou qu’une preuve n’est pas concernée par sa nature ; la façon d’établir la nature, le rôle et l’effet sur une preuve d’un élément dont la catégorie est incertaine ; les moyens de connaître les changements du code évalué, de ses dépendances et de sa configuration ; l’identification, pour chaque preuve, de l’outil employé, de sa version et de sa configuration ; le traitement des changements d’outils, notamment les conditions auxquelles une preuve produite avec un outil modifié peut renouveler ou compléter une preuve antérieure ; la comparabilité des preuves obtenues avec des outils, des versions ou des configurations différents, ou sur des versions différentes du code évalué, ou sous des configurations isolées différentes, et les conditions auxquelles leurs couvertures peuvent se cumuler au regard des critères 5 et 6 ; la façon d’établir qu’une preuve n’a pas été affectée par un défaut d’outil ; les critères de qualification d’un indice concret de défaut d’outil, notamment ce qui le distingue d’un risque seulement théorique, la façon dont une question de qualification portant sur un outil de preuve ou sa configuration est posée, qui la pose et qui y répond, ainsi que la façon de consigner un indice, de déterminer les preuves qu’il concerne et d’établir sa levée ; pour les questions de qualification portant sur la configuration isolée comme sur un outil de preuve, la façon de consigner la question posée et la réponse qui y est donnée et de les rattacher aux preuves, essais, éléments et rôles qu’elles concernent, y compris pour un élément qui joue plusieurs rôles, pour l’échéance de l’attente après le constat, sa durée, son point de départ, notamment lorsque la date de la question n’est pas établie, et la possibilité d’une prolongation, ainsi que la durée applicable à chaque attente, l’articulation des échéances de plusieurs attentes qui concernent une même preuve et ce que requiert le renouvellement d’une preuve tenue pour invalidée à l’échéance de l’attente, notamment l’usage d’une réponse donnée après cette échéance, la possibilité de nouvelles déclarations d’effectivité pendant l’attente et le sort des opérations acceptées pendant celle-ci ; les moyens de détecter les changements et les défauts d’outils ; le point de départ de l’invalidation lorsqu’elle ne résulte pas d’un changement, hors les cas que fixent les sous-puces « Catégorie incertaine », « Défaut ou écart établi après coup » et « Écart ou défaut soupçonné » ; le point de départ de l’invalidation lorsqu’elle résulte d’un changement de date inconnue d’un élément dont la catégorie n’est pas établie ; pour une incertitude de catégorie apparue après le constat sans résulter d’un changement (sous-puce « Catégorie incertaine »), le seuil qui distingue une incertitude pertinente d’un risque seulement théorique et la façon d’établir et de dater son apparition ; pour cette même incertitude, et distinctement du concours ouvert ci-après entre la qualification d’un indice et un défaut ou un écart établi ensuite, le concours entre l’invalidation qui en résulte et celle que produit la qualification d’un indice ou l’échéance d’une attente (sous-puce « Écart ou défaut soupçonné »), ainsi que le concours entre cette invalidation et celle qui résulte de l’un des cas que vise la sous-puce « Défaut ou écart établi après coup », lorsque ce cas est établi avant l’apparition de l’incertitude ou en même temps qu’elle ; pour un défaut ou un écart établi après coup (sous-puce « Défaut ou écart établi après coup »), le concours entre l’invalidation produite dès la qualification d’un indice après le constat et celle qui résulte de l’établissement ultérieur de l’écart ou du défaut ; l’examen des renvois vers Hyp-13 à Hyp-16 pour une nouvelle représentation. Tant qu’ils ne sont pas décidés, ce point bloque le constat.

### 5.6 Rejeu

Couverts :

- rejeu sur la même base : nonce `CONSUMED` ou `FAILED`, terminal (§5.5.1) ;
- rejeu sur une autre base (`store_id`) ;
- assertion d’approbation de B présentée comme assertion d’administration, ou l’inverse (RP ID et domaine différents) ;
- inscription modifiée entre `prepare` et `apply` (comparaison octet pour octet, `enrollment_sha256`) ;
- énoncé périmé (`expires_at_ms`, contrôlé en V0 seulement) ;
- confirmation stockée réutilisée pour autre chose : V1 exige que les lignes correspondent exactement à l’énoncé signé, et V1 n’écrit jamais rien.

Non couverts :

- une **restauration de sauvegarde** prise entre `prepare` et `apply` fait réapparaître le nonce `ISSUED`. Le risque est borné par `expires_at_ms` tant que l’horloge ne recule pas ; seul J-c le détecte (§11) ;
- l’énoncé signé non appliqué (§5.5.2).

### 5.7 Ajout, remplacement et révocation d’une clé de confiance [O]

**Règle laissée explicitement ouverte (§5.2.3).** Aucune règle d’ajout, de remplacement ou de révocation d’une clé de confiance n’est décidée ni recommandée ici.

**Contraintes déjà fixées ailleurs, que toute règle devra respecter :**

- toute modification du fichier de confiance passe par l’opération administrative `root` contrôlée (T-3 [D]) ;
- le RP ID d’administration reste fixe (§5.1 [D]) ;
- un credential n’est utilisable en V0 que s’il figure dans le fichier de confiance avec le statut `ACTIVE` (§5.5.1, étape 5 ; §5.5.3, [D]) ;
- pour une opération signée qui ferme, ce statut ne suffit pas : V0 exige aussi que la chaîne d’autorisation du credential n’ait pas été invalidée, et refuse s’il ne peut pas l’établir (§5.5.1, étape 5, [D], 27 octobre 2026). Une révocation signée devra respecter cette règle. Le chemin retenu pour le marquage `COMPROMISED` (opération signée appliquée par le service ou opération `root`) détermine comment l’appliquer sans délai, et avec quelle garantie (§5.5.5, E, F et H). **Décidé le 27 octobre 2026 (§5.5.5, J.1 à J.3) [D] :** le marquage passe par l’opération `root` contrôlée, authentifiée par un autre credential d’administration valide et indépendant du credential visé. Il ne prend effet qu’à l’installation de la nouvelle politique `root` ;
- V1 revérifie les confirmations d’une clé `RETIRED` antérieures à son retrait, au sens de l’ordre des entrées de journal ancrées, et refuse toutes celles d’une clé `COMPROMISED`, quelle que soit leur date (§5.5.3, [D]) ;
- tout changement de statut est explicite, authentifié, journalisé et ancré ; une anomalie `signCount` n’en provoque jamais (§5.5.3, [D]) ;
- une clé ajoutée par une opération signée par une clé ultérieurement `COMPROMISED` conserve son enregistrement et son statut déclaré, mais ne peut autoriser aucune opération future, ni en V0 ni en V1, tant qu’une clé `ACTIVE` ne l’a pas explicitement réautorisée (§5.5.3, [D]). Toute règle d’ajout devra donc permettre d’établir quelle clé a signé l’ajout. La réautorisation est une opération explicite, authentifiée, journalisée et ancrée. Elle ne prend effet qu’après l’ancrage requis, pour les opérations futures seulement, sans rendre utilisable ce qui a été signé avant elle (§5.5.3, [D]). Son mécanisme reste à concevoir [O] ;
- un ajout ou un remplacement de clé crée un nouveau credential, qui devrait satisfaire la même politique d’attestation que la genèse (§5.2.6, D ; §5.2.7). Ce point est [R] : la règle d’ajout reste ouverte.

**Déclencheur possible.** Une révocation d’attestation connue après la genèse (§5.2.7, J.5) peut conduire à remplacer une clé. Selon la décision du 26 octobre 2026 (§5.2.7, M.6) [D], elle ferme d’abord les opérations qui ouvrent et déclenche une revue. Le remplacement lui-même relève de la règle laissée ouverte ici [O].

**Pistes examinées, non retenues, à trancher :**

- révocation par une opération signée (par exemple `ADMIN_CREDENTIAL_REVOKE`) par n’importe quel credential actif, ou par la voie d’urgence (§7.0), puisqu’elle ne fait que fermer ;
- ajout ou remplacement par une opération signée (par exemple `ADMIN_CREDENTIAL_ADD`) du credential restant, **et** mise à jour du fichier de confiance par `root` ;
- exigence des deux clés pour toute modification des clés de confiance, avec le risque de blocage que cela entraîne si une clé est perdue.

Pour le seul marquage `COMPROMISED`, **décidé le 27 octobre 2026 (§5.5.5, J.3) [D]** : ni la voie d’urgence, ni SSH ou `sudo` seuls, ni l’assertion de la clé visée. Il faut un autre credential d’administration dont le statut et la chaîne sont valides et indépendants du credential visé. La règle générale d’ajout, de remplacement et de révocation, dont le retrait `RETIRED`, reste ouverte.

**Limite, quelle que soit la règle.** Un processus qui peut écrire la base peut effacer une révocation enregistrée en base ; seul l’ancrage le révèle. Le changement de statut dans le fichier de confiance par `root` est la seule révocation qui ne dépend pas de la base. Pour un marqueur d’invalidation présent seulement en base, cette limite est acceptée le 27 octobre 2026 et reste visible (§5.5.5, J.2) [D].

### 5.8 Perte d’une ou des deux clés [O]

- **Perte d’une seule clé.** Selon la décision du 25 octobre (§5.2.1), l’autre clé suffit aux opérations courantes : le système n’est pas bloqué immédiatement. La conduite à tenir (révocation, remplacement) dépend de la règle laissée ouverte au §5.7.
- **Perte des deux clés : procédure laissée explicitement ouverte (§5.2.3).** Fait certain : aucune opération signée n’est alors possible. Toute restauration de la confiance d’administration toucherait le fichier de confiance, donc l’opération `root` contrôlée (T-3). Piste examinée, non retenue : une nouvelle genèse par `root`, journalisée et ancrée, avec l’interrupteur maintenu fermé et tous les nonces ouverts clos. Elle ne pourrait pas suivre telle quelle la genèse initiale, qui refuse tout fichier de confiance existant et tout remplacement (§5.2.2, règle 5) : ce serait une réinitialisation ultérieure, dont la procédure reste ouverte.
- **Perte avec suspicion de compromission.** Piste [R] : marquer la clé `COMPROMISED` dans le fichier de confiance. **Décidé le 27 octobre 2026 (§5.5.5, J.3) [D] :** ce marquage passe par l’opération `root` contrôlée et exige un autre credential d’administration valide, indépendant du credential visé. Sans lui, il est impossible par cette voie, et la récupération relève de la procédure distincte de cette section, encore ouverte. **Portée de `COMPROMISED` décidée le 26 octobre 2026 [D] (§5.5.3)** : toutes les confirmations signées par cette clé deviennent inutilisables, quelle que soit leur date, faute de borne de compromission suffisamment fiable. La limitation aux confirmations postérieures à un point ancré vérifié n’est pas retenue. Cette portée s’étend à toutes les opérations qui ouvrent signées par cette clé, sans modification rétroactive ; si aucune clé `ACTIVE` ne permet d’établir un état valide, le système reste fermé (§5.5.3, [D]). Un marquage survenu avant l’ancrage d’une entrée que la clé a signée ne mène pas à S4 à lui seul, et une clé qu’elle a ajoutée doit être réautorisée par une clé `ACTIVE` avant toute opération. Cette réautorisation ne vaut que pour l’avenir, après son ancrage ; si aucun chemin sûr ne la permet, le système reste fermé (§5.5.3, [D]). La procédure de perte, le remplacement et la sortie d’un éventuel blocage restent ouverts [O].
- **Révocation commune aux deux clés.** Si les deux clés sont du même modèle, ou chaînent vers la même AC, une révocation défavorable connue après la genèse peut les toucher toutes les deux (§5.2.7, I-6). Selon la décision du 26 octobre 2026 (§5.2.7, M.6) [D], les opérations qui ouvrent restent alors fermées. La situation se rapproche de la perte des deux clés pour ces opérations, sans que leurs statuts changent automatiquement. Pour réduire ce risque, M.7 [D] recommande deux modèles d’AAGUID différents pour la clé principale et la clé de secours. Le fabricant, les modèles et les ancres restent à choisir [O]. Deux modèles différents ne protègent pas contre une AC commune (§5.2.7, I-6).
- **Aucune récupération par courriel, SMS, code ou support tiers** [R, par analogie avec D-3].

## 6. Inscriptions : deux credentials (D-3) et opérations sur `PENDING`

### 6.1 Deux credentials avant activation

- [F] v5 ne porte qu’un credential par inscription ; [D] D-3 en exige deux avant toute activation.
- [R] Dans le futur schéma, l’inscription porte exactement deux credentials, `PRIMARY` et `BACKUP`, enregistrés pendant la même session d’invitation. L’invitation n’est consommée qu’avec les deux : aucune inscription `PENDING` à un seul credential.
- Le stockage vérifie, à la consommation puis de nouveau à `CONFIRM` :
  - identifiants distincts et clés publiques distinctes ;
  - `BACKUP` avec `BE=0` et `BS=0`, et jamais `BS=1` avec `BE=0` ;
  - algorithmes autorisés ;
  - UV signalée à l’inscription ;
  - une **assertion de possession** de chaque credential sur un défi lié à la session, car une inscription avec attestation `none` ne prouve pas la possession de la clé privée.
- **Limite.** Sans attestation (D-4), rien ne prouve que les deux credentials sont sur deux authentificateurs physiques séparés : seuls les drapeaux déclarés sont contrôlés.
- [O] Les deux credentials dans la même session (recommandé) ou une seconde invitation pour le secours.

### 6.2 Opérations autorisées

| Opération | Autorité | Effet |
|---|---|---|
| `list --pending`, `show <invitation_id>` | Compte système seul (lecture) | Identifiants, ID attendu, empreintes, BE/BS, dates, état de la preuve. Jamais `credential_data` brut, secret ni assertion |
| `prepare confirm`, puis `apply` | Assertion d’administration | `PENDING` → `CONFIRMED` : enregistrement atomique (§8.2). Autorisation effective seulement après ancrage et relecture (§11.2) |
| `prepare reject --reason <code>`, puis `apply` | Assertion d’administration | `PENDING` → `REJECTED`, définitif |
| `emergency reject --reason <code>` | Compte système seul (§7.0) | `PENDING` → `REJECTED`, définitif |

**Interdit :** modifier une inscription, la rouvrir, prolonger une invitation ou une attente, confirmer sans deux credentials conformes, confirmer sur la base de `MOCK_UNVERIFIED_ACCOUNT_ID_MATCH`. Pour corriger une inscription, on la rejette et on crée une nouvelle invitation.

**États [R].** `PENDING` → `CONFIRMED` | `REJECTED`. Si `T_attente` est décidée, `PENDING` → `EXPIRED` s’y ajoute. Les trois états d’arrivée sont terminaux. `CONFIRMED` reste une trace historique ; la révocation porte ensuite sur les lignes du registre.

**`CONFIRMED` est un état enregistré, pas une autorisation.** Aucun état stocké en base ne vaut autorisation effective. L’effectivité est recalculée à chaque usage par le chemin d’approbation (contrôle E : V1, relecture de l’ancre et couverture de l’entrée, §11.2) ; elle n’est jamais une colonne qu’une écriture directe pourrait basculer.

**Préconditions de `CONFIRM`**, toutes vérifiées dans la transaction (ordre au §5.5.1). Elles conditionnent l’**enregistrement**, pas l’effectivité :

- J-b et J-c opérationnels : ancre relue pendant l’`apply`, concordante, sans queue locale en attente d’ancrage (§5.5.1, étape 1) ;
- inscription `PENDING` et invitation `CONSUMED` ;
- preuve GitHub valide, du type attendu, avec révocation du grant confirmée (§8) ;
- deux credentials conformes (§6.1) ;
- aucune ligne de registre déjà existante pour ces identifiants ;
- énoncé reconstruit identique ;
- assertion valide ;
- nonce `ISSUED`, non échu.

### 6.3 Codes de rejet

[R] Liste fermée proposée, sans aucun texte libre. Le code est une colonne contrainte par `CHECK (... IN (...))` ; il entre dans l’énoncé signé et dans le journal. [O] Liste définitive. Ces codes de rejet signés sont distincts des codes techniques de réponse du service, qui ne sont ni signés, ni écrits en base, ni inscrits dans J-b (§10.2, catégorie fixée le 28 octobre 2026).

| Code | Sens |
|---|---|
| `ACCOUNT_ID_OUT_OF_BAND_MISMATCH` | L’ID attendu ne concorde pas avec celui reçu de B par le canal séparé |
| `ACCOUNT_PROOF_INVALID` | Preuve absente ou d’un autre type, ou révocation du grant non confirmée |
| `CREDENTIAL_POLICY_NOT_MET` | D-3 ou D-4 non satisfaits : secours absent, BE/BS, clés identiques, algorithme |
| `POSSESSION_NOT_PROVEN` | Assertion de possession absente ou invalide |
| `APPROVER_DID_NOT_CONFIRM` | B ne confirme pas, par le canal séparé, être à l’origine de l’inscription |
| `CHANNEL_SUSPECTED` | Canal de remise du secret ou canal séparé suspect |
| `COMPROMISE_SUSPECTED` | Compromission suspectée du compte ou des appareils de B, du poste du propriétaire ou du serveur |
| `SUPERSEDED` | Remplacée par une nouvelle invitation |
| `DESIGNATION_WITHDRAWN` | Le propriétaire retire la désignation |
| `EMERGENCY` | Réservé à la voie d’urgence quand aucun autre code ne s’applique |

## 7. Interrupteur D-9 : voie d’urgence et réouverture

### 7.0 Voie d’urgence : opérations qui ferment

[D] D-9 prévoit une fermeture d’urgence par SSH sans WebAuthn, pour l’interrupteur seulement. [R] L’étendre aux autres opérations qui ferment ou révoquent :

- **Autorité :** compte système seul (SSH et `sudo`), sans WebAuthn.
- **Autorisé :**
  - fermer l’interrupteur, quand il existera ;
  - rejeter une inscription `PENDING` ;
  - révoquer une invitation ouverte ;
  - clore les nonces ouverts ;
  - révoquer un credential d’administration, si la règle laissée ouverte au §5.7 le retient ;
  - révoquer un credential, un approbateur, un compte ou un principal.
- **Jamais :** confirmer, activer, créer une invitation, ajouter un credential, rouvrir l’interrupteur, annuler une révocation, sortir d’un état terminal, modifier une inscription. La réouverture exige l’assertion d’administration décrite au §7.1 ; la voie d’urgence ne peut jamais y suppléer.
- **Mise en œuvre :**
  - un module séparé, dont la surface ne contient que des transitions vers des états terminaux de fermeture ;
  - les déclencheurs refusent déjà toute sortie de `REJECTED` ou `REVOKED` ;
  - un test de périmètre vérifie la liste exacte des opérations et qu’aucune n’écrit `CONFIRMED` ni `ACTIVE`.
- **Journal :** `emergency = 1`, opération, code, cible par empreinte. Une opération d’urgence n’est jamais confondue avec une opération signée.
- **Limite :** quiconque obtient ce compte système peut tout fermer, donc bloquer le service. C’est accepté : il le pourrait déjà en écrivant le fichier, et l’échec reste fermé.
- **Distincte des opérations signées qui ferment** — décidé le 26 octobre 2026, précisé le 27 octobre 2026 [D] (§5.5.1, étape 5). Une opération signée qui ferme est vérifiée par V0 contre le fichier de confiance protégé par `root`, sans relire J-c ni exiger une queue vide. Elle n’est acceptée que si le credential signataire est autorisé et si sa chaîne d’autorisation n’a pas été invalidée ; le statut `ACTIVE` ne suffit pas à lui seul. Si V0 ne peut pas établir cette validité, l’opération signée est refusée. La voie d’urgence reste alors disponible **dans sa seule portée décidée** : la fermeture de l’interrupteur (D-9, ci-dessus). Cette formulation vise ce refus ; elle ne décide pas de la disponibilité de D-9 pendant le gel après un `COMMIT` d’issue indéterminée, qui reste ouverte [O] (§5.5.1, cas 3). Ces décisions ne l’étendent pas aux autres opérations qui ferment : pour elles, un refus de V0 n’a pas de voie de repli tant que l’extension recommandée ci-dessus n’est pas décidée. Les deux chemins restent séparés : une opération d’urgence n’est jamais confondue avec une opération signée (« Journal », ci-dessus).
- [O] Confirmer cette extension au-delà de l’interrupteur.
- **[D, 27 octobre 2026]** Le marquage `COMPROMISED` d’un credential d’administration n’est pas possible par cette voie : il exige l’opération `root` contrôlée, authentifiée par un autre credential valide (§5.5.5, J.3). La portée décidée de D-9 n’est pas étendue. Dans l’extension recommandée ci-dessus [R], la ligne « révoquer un credential d’administration » ne peut donc pas viser ce marquage. Sa portée pour un retrait reste ouverte [O].
- **[D, 27 octobre 2026] Pendant l’arrêt forcé du service par la procédure `root`** (§5.5.5, L.5) :
  - D-9 peut être temporairement indisponible ;
  - le service arrêté est en échec fermé, et aucune voie n’autorise pendant cet arrêt ;
  - après le redémarrage, D-9 est de nouveau disponible dans sa portée décidée, même si l’entrée `c` attend encore l’ancrage, puisqu’elle ne fait que fermer l’interrupteur.

  Sa portée n’est pas modifiée. Les détails de l’arrêt et du redémarrage restent ouverts [O].

### 7.1 Réouverture de l’interrupteur (T-1)

**Décidé le 25 octobre 2026 [D] :**

- le propriétaire, en qualité d’unique administrateur, peut rouvrir l’interrupteur D-9 par SSH, avec une assertion WebAuthn fraîche et UV de son credential d’administration ;
- B reste approbatrice uniquement, sans accès SSH ni rôle d’administration ;
- cette action n’autorise jamais le propriétaire à approuver une demande de génération.

**Conditions de D-9 que cette décision ne modifie pas [D]** (G1 l. 281, 284, 498) :

- action manuelle ;
- motif indiqué et journalisation atomique ;
- acceptée seulement après rapprochement de la base, du journal, du témoin et de l’ancre externe ;
- aucun redémarrage, aucune restauration ni aucune expiration ne rouvre l’interrupteur automatiquement ;
- la réouverture ne constitue jamais une ouverture du Provider et ne modifie pas le NO-GO.

**Clause de séparation [D].** La règle « distinct de l’acteur GitHub du run » s’applique aux approbations associées à un run, pas à la réouverture, qui n’a pas d’acteur de run à comparer.

**Documentation de référence : alignement commité dans `73737dd` et fusionné dans `main` par le PR #62 (`6313648`).** G1 §4.8, G1 §1.2, G1 §9 (X6), G1 §10 (D-9) et un addendum daté sont alignés (§3.1). La version de G1 sur `main` est à jour.

**Modalités recommandées, non décidées [R] :**

- **Opération signée.** Une opération `SWITCH_REOPEN` est ajoutée à la liste fermée des opérations (§5.3). Elle suit le même protocole `prepare` / signature / `apply` et la même vérification V0 (§4.2, §5.5.1), avec un nonce à usage unique.
- **Énoncé.** Il lie le `store_id`, la tête du journal ancrée et relue au moment du `prepare`, et le code de motif.
- **Classement.** La réouverture est une opération qui ouvre (§11.2) : son étape 1 de V0 exige une ancre relue et concordante. Elle n’est effective qu’après l’ancrage et la relecture de l’entrée qui la consigne.
- **Jamais par la voie d’urgence** (§7.0).
- **Séparation des rôles :**
  - le credential d’administration n’est jamais inscrit dans les tables d’approbateurs ni de credentials d’approbation ;
  - le vérificateur d’approbation le refuse par son RP ID (§2.3, §5.1) ;
  - un test vérifie qu’une assertion d’administration est refusée par le chemin d’approbation, et qu’une assertion d’approbation est refusée par les opérations d’administration.

**Ouvert [O] :**

- la liste fermée des codes de motif de réouverture ;
- la conception de l’interrupteur lui-même, qui n’existe pas encore ;
- le mécanisme qui empêche une réouverture signée par une clé devenue `COMPROMISED` de maintenir l’interrupteur ouvert pour une autorisation future. La règle est décidée le 26 octobre 2026 (§5.5.3) ; son application dépend de la conception de l’interrupteur.

**Limite.** Un poste du propriétaire compromis peut lui faire signer une réouverture à la place d’une autre opération qu’il lance (§12). Les préconditions de rapprochement et d’ancrage restent toutefois exigées.

## 8. Preuve GitHub distincte de `ADMIN_ATTESTED`

### 8.1 Enregistrement de la preuve [R]

Table `account_proofs`, une ligne par invitation :

- `proof_kind`, contraint à la seule valeur `GITHUB_APP_WEB_FLOW_USER_ID` ;
- ID public de la GitHub App, ID observé, instant de l’observation ;
- `grant_revocation`, contraint à `CONFIRMED` ou `FAILED` ;
- empreinte canonique de la ligne.

Ne sont jamais enregistrés : login, code, `state`, vérificateur PKCE, jeton d’accès ou de rafraîchissement, secret client.

- La table n’est écrite que par le futur composant OAuth. Ce composant n’existe pas ; il exige `http` et `ssl` sortants, donc une exception au §2.4 [O], ainsi que D-12 et D-15.
- `CONFIRM` refuse `MOCK_UNVERIFIED_ACCOUNT_ID_MATCH`, une preuve absente, un ID observé différent de l’ID attendu, et `grant_revocation = FAILED`. [O] La conduite en cas d’échec de la révocation reste à spécifier (D-5 l. 49) ; la recommandation est le refus.

### 8.2 Activation : futur schéma v6, frais, sans migration [R]

- **`admin_confirmations`** (ajout seul) : opération, octets canoniques et empreinte de l’énoncé, credential d’administration utilisé, `authenticatorData`, `clientDataJSON`, signature, instant de vérification.
- **`github_accounts` v6** : au lieu de `evidence = 'ADMIN_ATTESTED'`, deux références obligatoires, `account_proof_id` (preuve GitHub) et `admin_confirmation_id` (confirmation signée du propriétaire). L’une ne remplace pas l’autre (décision du 24 octobre). La séparation (`separation_evidence`) suit le même principe.
- **Enregistrement atomique** : principal, approbateur, compte, deux credentials, confirmation, compteur, journal et consommation du nonce, dans une seule transaction (V0, §5.5.1). Ces lignes sont **enregistrées**, pas encore **effectives**.
- **Autorisation effective** : le chemin d’approbation n’utilise ces lignes que si le contrôle E réussit au moment de l’usage, c’est-à-dire si V1 réussit (§5.5.2) **et** si l’entrée de journal de la confirmation est couverte par une tête d’ancre relue à ce moment (§11.2). La revérification de l’énoncé stocké par v3 suit le même principe. Une ligne forgée par écriture SQL directe échoue en V1.

### 8.3 Limites

- La preuve reste une affirmation du service au moment de l’observation : le jeton est jeté, et rien n’est revérifiable ensuite auprès de GitHub.
- La signature du propriétaire couvre l’ID observé et sa comparaison hors bande, pas l’identité civile de B ni la séparation de deux personnes.
- H1 reste ouverte : l’ID REST n’est pas prouvé égal à `actor_id`.

## 9. Comptes système et accès au registre SQLite

### 9.1 Contraintes [F]

Seul le compte propriétaire du fichier peut ouvrir la base (§2.2). Aucun canal réseau ni local n’est permis au code applicatif (§2.4).

### 9.2 Frontière d’administration

**Exigence décidée le 25 octobre 2026 (T-3, décision initiale puis complément) [D] :**

- `root` possède et contrôle en écriture l’ensemble des éléments qui peuvent changer l’application ou son autorisation :
  - la CLI d’administration ;
  - le stockage ;
  - les vérifications V0, V1 et E ;
  - le chemin d’approbation et de consommation ;
  - les dépendances d’exécution ;
  - la configuration et le lancement du service ;
  - le fichier de confiance contenant les clés publiques épinglées ;
- `aidirector` peut lire et exécuter ces éléments, mais ne peut ni les modifier ni les remplacer ;
- les fichiers SQLite (base, `-wal`, `-shm` et leur répertoire) restent détenus et utilisés par le compte de service, selon les contrôles d’accès existants (`approval_store.py:332-347`) ;
- toute installation ou mise à jour de ces éléments passe par une opération administrative `root` contrôlée ;
- la compromission de `root` ou du serveur reste hors de la protection offerte par A-1 et maintient le système fermé selon D-15 ;
- aucune modification effective du serveur n’est autorisée par ces décisions.

Raison : si un processus compromis sous le compte de service pouvait modifier le code qui vérifie, ses dépendances, sa configuration ou les clés épinglées, A-1 ne protégerait plus rien.

**Détails de mise en œuvre, ouverts [O].** L’exigence ci-dessus est décidée ; la manière de la satisfaire ne l’est pas.

- **Méthode d’installation et de mise à jour** : forme de l’opération administrative `root` contrôlée, qui la lance, depuis quelle source (commit revu, archive signée ou autre), et comment une mise à jour est validée avant d’être utilisée.
- **Inventaire exact** des fichiers et dépendances couverts : code de l’application, interpréteur Python, paquets verrouillés, configuration, unité de lancement, fichier de confiance, ainsi que leurs répertoires parents. L’exigence « ne peut ni les remplacer » couvre aussi le remplacement par renommage dans un répertoire parent ; propriétaire, groupe, mode et attributs exacts restent à fixer. Points d’attention pour cet inventaire, à vérifier et non décidés :
  - les répertoires de cache de bytecode (`__pycache__`), que le compte de service ne doit pas pouvoir écrire ;
  - les répertoires `site-packages` propres à l’utilisateur et les fichiers `.pth` ;
  - les variables d’environnement qui influencent l’interpréteur (`PYTHONPATH` et autres) ;
  - les options de lancement de l’interpréteur ;
  - conformément à la décision du 26 octobre 2026 (§5.2.7, M.2 ; import par l’opération `root` contrôlée) : le **fichier de politique d’attestation** (ancres approuvées, couples AAGUID–ancres–formats) et les **artefacts importés** (instantané des métadonnées, informations de statut, dernier `no` importé). Ils relèvent de l’exigence T-3, puisqu’ils changent l’autorisation : propriété `root`, lecture seule pour `aidirector`, import et mise à jour par l’opération `root` contrôlée seulement.
  - conformément aux décisions des 26 et 27 octobre 2026 sur les opérations signées qui ferment (§5.5.1, étape 5) : le **fichier de confiance** conserve, pour chaque credential d’administration, l’entrée d’autorisation effective contre laquelle V0 vérifie ces opérations, sans relire J-c. Le statut `ACTIVE` ne suffisant pas, V0 doit aussi pouvoir établir que la chaîne d’autorisation du credential n’a pas été invalidée ; à défaut, il refuse. Restent ouvertes [O] la représentation de cette entrée et de cette chaîne dans la politique protégée par `root`, la preuve que l’entrée était déjà effective quand `root` l’y inscrit et que la chaîne n’a pas été invalidée, leur cohérence avec J-b et J-c, et la conduite en cas de divergence ou d’impossibilité d’écrire le journal. Une piste de manifeste d’autorisation canonique et les options d’application sont analysées au §5.5.5 [R].
  - conformément aux décisions de portée du 27 octobre 2026 (§5.5.5, J.4 et J.5) : la **zone d’événements** protégée par `root`, où l’événement signé de marquage est conservé durablement avant la mise à jour de la politique, et au moins jusqu’à l’ancrage de son entrée J-b ; et la **barrière** que `root` prend en exclusif et que le service tient de la lecture de la politique jusqu’au `COMMIT`. Elles relèvent de T-3 : `root` écrit la zone, et `aidirector` la lit sans pouvoir la modifier. `root` n’écrit jamais dans SQLite. Restent ouverts [O] : format, droits exacts, synchronisation de la zone, mécanisme de la barrière et compatibilité de son support avec T-3. L’arrêt des processus du service par `root` et l’interdiction de leur redémarrage (décision du 27 octobre 2026, §5.5.5, L.5) s’appuient sur le contrôle du lancement du service par `root` (T-3). Leur mécanisme reste ouvert [O].
  - conformément à la décision du 28 octobre 2026 (§5.5.1, cas 3, « Mécanisme du marqueur ») : les **marqueurs du gel**, fichiers persistants hors de SQLite, un par transaction couverte. Le service les crée et les retire ; `root` seul retire un marqueur résiduel, après une récupération et une vérification explicites, sans écrire dans SQLite. Ils sont placés dans un sous-répertoire persistant du compte de service, dans l’arborescence des données, hors des arborescences `root` et du code (décidé le même jour [D]). Restent ouverts [O] : leur emplacement exact, leurs modes, leur place précise dans la disposition des répertoires et leur compatibilité avec T-3. Rien, ici, n’établit que le système de fichiers empêche un processus du compte de service de supprimer le marqueur d’un autre processus. Le verrou W, décidé le même jour (§5.5.5, L.2), est réservé aux transactions couvertes du service. Son support est un fichier stable détenu par `root`, jamais supprimé ni remplacé, que le service peut ouvrir et prendre en verrou exclusif sans pouvoir le modifier (décidé le même jour [D]). Son mécanisme, l’emplacement et les modes exacts de son fichier et sa compatibilité avec T-3 restent ouverts [O].
- **Contrôles d’intégrité** : comment vérifier que les éléments installés correspondent à ce qui a été revu (empreintes, comparaison au commit, vérification au démarrage), et que faire en cas d’écart (refus fermé).
- **Journalisation** : trace de chaque installation ou mise à jour, sans secret ; lien avec J-b et l’ancrage J-c (par exemple, l’empreinte de l’inventaire et du fichier de confiance) ; conservation des journaux système.
- **Disposition des répertoires.** Le contrôle existant exige que le **répertoire** de la base appartienne lui aussi au compte de service (`approval_store.py:340-347`). Les fichiers SQLite doivent donc se trouver hors de toute arborescence `root` et le code hors de leur répertoire. L’emplacement exact reste à fixer.
- **Conformité du serveur.** Sa conformité à T-3 n’est pas établie. Toute vérification, mise en conformité éventuelle ou autre modification du serveur relève d’une étape autorisée séparément.

**Recommandations, non décidées [R] :**

- la CLI d’administration tourne sous le compte propriétaire de la base, par une règle `sudo` limitée au chemin exact de la commande ;
- les données sensibles transitent par l’entrée standard, jamais en argument : les arguments sont visibles dans la liste des processus et dans les journaux de `sudo` ;
- le module d’administration n’est jamais importé par un futur point d’entrée web : un test de fermeture des imports le vérifie, sur le modèle du test d’egress ;
- les primitives non authentifiées de v5 sont retirées ou rendues inaccessibles au code déployé. Les opérations signées vivent dans le stockage, pas dans la CLI : la CLI n’est pas de confiance ;
- cette frontière n’exige **aucune** exception à l’interdiction des sockets.

### 9.3 Isolation du futur processus web [O]

- **I-0 : web et stockage sous le même compte.** Le stockage n’a besoin d’aucune exception aux sockets. Un processus web compromis peut écrire le fichier, donc rejeter, révoquer, supprimer ou bloquer. Il ne peut pas forger une activation, grâce à la revérification, parce que le code qui l’exécute, ses dépendances, sa configuration et le fichier de confiance appartiennent à `root` (T-3, §9.2). Cela vaut une fois les détails de mise en œuvre satisfaits.
- **I-1 : web sous un compte sans droit sur la base**, stockage derrière un canal local (socket Unix). C’est plus robuste contre le blocage, mais **toute exception à l’interdiction actuelle de `socket` exige une décision explicite et des contrôles d’architecture** :
  - un seul module nommé ;
  - `AF_UNIX` uniquement, jamais `AF_INET` ;
  - vérification du pair (`SO_PEERCRED`) et permissions du fichier socket ;
  - protocole minimal, sans aucune opération d’administration ;
  - tests qui continuent d’interdire `socket` partout ailleurs ;
  - mise à jour revue de `tests/test_provider_egress_closure.py` et de l’audit d’architecture.
- La même exigence vaut pour le client OAuth (`http`, `ssl`) et pour l’envoi vers l’ancre J-c.

## 10. Secrets, clés, assertions, signatures et tentatives refusées

### 10.1 Où chaque élément peut exister

| Élément | Où il peut exister | Jamais |
|---|---|---|
| Secret d’invitation | Affiché une fois dans la session SSH ; empreinte SHA-256 en base | Argument de commande, journal, message d’erreur, historique du shell, fichier |
| Code OAuth, `state`, vérificateur PKCE, jetons | Mémoire du composant OAuth pendant l’échange | Base, journal, messages |
| Secret client de la GitHub App | Selon D-15, encore ouverte | Dépôt, base, journal |
| Clés privées d’administration | Authentificateurs du propriétaire | Serveur, disque du poste, dépôt |
| Clés SSH privées | Poste du propriétaire | Serveur, dépôt |
| Clés publiques d’administration | Fichier de confiance (`root`) et copie en base | — (publiques) |
| `credential_data` de B (clé publique) | Base | Journal (empreinte seulement), affichage brut |
| Assertions et signatures d’administration | `admin_confirmations`, pour la revérification | Journal, messages, sorties de commande |
| Nonces et énoncés canoniques | Base, session SSH, client local | Journal (empreinte de l’énoncé seulement) |
| Énoncé et assertion d’un marquage `COMPROMISED` | Zone d’événements protégée par `root`, lisible par `aidirector`, au moins jusqu’à l’ancrage de l’entrée J-b (décidé le 27 octobre 2026, §5.5.5, J.4) | Journal (empreintes seulement), messages, sorties de commande |

[O] La conservation des éléments bruts d’un marquage au-delà de l’ancrage de son entrée J-b reste ouverte (§5.5.5, J.4).

### 10.2 Messages

Les messages sont des codes fixes. Ils ne reprennent jamais un identifiant, un énoncé, une assertion ni un secret.

**Codes techniques de réponse — catégorie fixée le 28 octobre 2026 [D]** (§5.5.1, cas 3, « Mécanisme du marqueur »). Ils sont distincts des codes de rejet signés du §6.3 : un code technique de réponse n’est ni signé, ni écrit en base, ni inscrit dans J-b. Cette catégorie comprend le code du refus après échec de synchronisation du marqueur : défini par ses garanties, commun à V0 et E, émis seulement après un `ROLLBACK` complet réussi, et accompagné d’un qualificatif secondaire fixe sur le sort du marqueur de cette transaction, dont aucune valeur ne signifie que le gel global est levé. Ce qualificatif a trois valeurs fermées (décidées le même jour [D]) : retrait visible, durabilité non établie ; marqueur confirmé présent ; état du marqueur non établi. Il n’a pas de valeur « retrait durable » pour ce cas, et aucune valeur n’est nommée ni décrite comme « gel levé », « système ouvert » ou équivalent. En cas de fail-stop, aucun code de refus n’est émis. **Statut de sortie de fail-stop — décidé le même jour [D]** (§5.5.1, « Signalement du fail-stop ») : sur tout chemin qui se termine en fail-stop (cas 2, point 3 ; cas 3, point b ; fail-stop spécial), le processus se termine avec un statut de sortie dédié, unique et commun, distinct des statuts de succès et de refus. Ce statut n’est pas un code technique de réponse de cette catégorie ; il signifie seulement que le processus s’est arrêté en fail-stop et que l’issue n’est pas établie, sans rien prétendre sur l’effet ni sur l’état du nonce. Les codes fixes prévus au §5.5.1, cas 2, point 5, et cas 3 (« issue à constater ») ne valent que pour les chemins où le processus continue. **Nom symbolique — décidé le même jour [D] :** ce statut est `EXIT_FAIL_STOP`, unique et commun à tous les chemins qui se terminent en fail-stop ; il n’est ni un code de refus ni un code de réponse du protocole. **Valeur numérique — non fixée, décidé le même jour [D] :** le nom symbolique reste fixé ; la valeur numérique n’est pas fixée à ce stade et sera choisie après la définition de la liste des statuts de sortie de la CLI et l’examen des chaînes CLI, sudo, SSH et superviseur ; aucune plage numérique n’est adoptée comme décision. **Seul signal du protocole — décidé le même jour [D] (option T1) :** en fail-stop, aucun code de réponse ni message du protocole n’est émis ; `EXIT_FAIL_STOP` est le seul signal produit par le processus au titre du protocole, et aucun message applicatif n’est écrit sur stdout ni sur stderr. Après un échec de synchronisation du marqueur, l’absence visible du marqueur ne prouve ni que son retrait est durable ni que le gel est levé ; un marqueur résiduel présent maintient le gel. Toute télémétrie diagnostique reste facultative, hors du protocole d’autorisation, et ne retarde ni le `ROLLBACK` ni le fail-stop. Restent ouverts [O] : le nom exact de ce code, la liste des codes techniques de réponse, les noms exacts des trois valeurs du qualificatif, la tentative systématique ou non du retrait, la conduite lorsque l’état du marqueur n’est pas établi, la valeur numérique de `EXIT_FAIL_STOP`, la liste complète des statuts de sortie de la CLI au-delà du cadre symbolique de `apply` (ci-dessous), la transmission du statut par la CLI, sudo, SSH ou le superviseur, la vérification de ces chaînes sur le serveur, la conduite face à un statut inconnu ou au statut 255, la politique de redémarrage du processus par le superviseur, que le choix du numéro ne tranche pas, l’observation côté E, la conduite de récupération lorsque le marqueur est absent ou que sa présence ne peut être établie, et le rattachement éventuel à cette catégorie des autres codes fixes évoqués au §5.5.1 (« issue à constater », cas 2).

**Catégories de sortie de `apply` — cadre symbolique décidé par le propriétaire le 28 octobre 2026 [D], sans valeurs numériques** (§5.5.1, cas 1 à 3 ; §5.5.5, L.7 ; §14, point 24). Ce sont des statuts de sortie du processus, distincts des codes techniques de réponse ci-dessus et des codes de rejet signés du §6.3.

- **Portée des garanties.** Une catégorie décrit seulement ce qui est établi sur l’effet métier, le `COMMIT` et l’état du nonce. Elle n’affirme ni l’effectivité, ni la possibilité de réessayer, ni l’état du gel ou du marqueur.
- **Comptage des refus.** Le comptage éventuel des refus est hors des garanties des catégories : son emplacement et sa transaction restent [O] (§5.5.1, cas 1 ; §10.3).
- **Déductions sous C2 — décidé par le propriétaire le 29 octobre 2026 [D].** Une catégorie n’affirme pas comme établi un état qui repose seulement sur une déduction sous C2 (§5.5.1, « Conditions de toute garantie »). Au §5.5.1, cas 2, point 1, le nonce non modifié par cette tentative peut être indiqué comme établi après le `ROLLBACK` réussi. Au point 2, la catégorie n’affirme pas que le nonce est inchangé : cette conclusion dépend de C2 et reste une déduction [R], non une garantie de la catégorie. La même réserve s’applique à tout rattachement de `EXIT_REFUSED_UNRECORDED` qui dépend de `in_transaction` faux et de C2, notamment au cas 1, « Échec de la transition conditionnelle ». La démonstration de C2 dans la mise en œuvre reste [O] ; la question d’un nouvel essai de `ROLLBACK` est distincte et reste [O].
- `EXIT_OK` : `COMMIT` confirmé ; l’effet et `CONSUMED` sont enregistrés ensemble. La catégorie n’affirme pas l’effectivité : une opération qui ouvre n’est effective qu’après V1, l’ancrage et E (§6.2 ; §11.2) ; une fermeture ordinaire prend effet au `COMMIT` local dans le service intact (§5.5.1, étape 5).
- `EXIT_REFUSED_RECORDED` : effet métier annulé ; refus enregistré ; le nonce visé n’est pas `ISSUED` à l’issue.
- `EXIT_REFUSED_UNRECORDED` : aucun effet métier ni changement du nonce n’est validé par cette tentative ; cela ne dit rien des écritures éventuelles de comptage.
- `EXIT_REFUSED_NONCE_UNESTABLISHED` : effet annulé au `SAVEPOINT` ; `COMMIT` final en erreur ; nonce ni établi comme `FAILED` ni comme intact (§5.5.1, cas 1, « Échec du `COMMIT` final », points a et c).
- `EXIT_OUTCOME_TO_ESTABLISH` : `COMMIT` du chemin de succès en erreur ; ni succès ni refus, et le processus continue (§5.5.1, cas 3, points a et c).
- `EXIT_FAIL_STOP` : définition déjà décidée, inchangée (ci-dessus ; §5.5.1, « Signalement du fail-stop »).
- **Recommandation [R], non adoptée :** `EXIT_REFUSED_EFFECT_UNASSERTED`, pour le §5.5.1, cas 2, points 1 et 2 : aucun `COMMIT` exécuté ; absence d’effet non affirmée. **Précisé le 29 octobre 2026 [D], sans adopter la catégorie :** elle peut affirmer ces deux points, mais ne garantit pas l’état du nonce au point 2, qui reste une déduction [R] sous C2 (« Déductions sous C2 », ci-dessus) ; au point 1, le nonce non modifié par cette tentative peut être indiqué comme établi après le `ROLLBACK` réussi. Elle reste conditionnelle à la confirmation du code de réponse du cas 2.
- **Rattachement proposé [R], non décidé :** `EXIT_REFUSED_RECORDED` pour l’étape 1b et les étapes 2 à 8 menées jusqu’au `COMMIT` confirmé de la transition conditionnelle ; `EXIT_REFUSED_UNRECORDED` pour l’étape 1a et les échecs propres à γ1 terminés par un `ROLLBACK` complet réussi, pour l’échec de la transition du cas 1 suivi d’un `ROLLBACK` réussi ou de `in_transaction` faux, et pour l’échec de synchronisation du marqueur suivi d’un `ROLLBACK` complet réussi. Lorsque ce rattachement dépend de `in_transaction` faux et de C2, la réserve « Déductions sous C2 » s’applique [D, 29 octobre 2026] : l’absence d’effet métier et de changement du nonce validés par cette tentative y reste une déduction [R], non une garantie établie de la catégorie.
- **Restent ouverts [O] :** le classement du refus pour marqueur résiduel, de l’échec de `BEGIN IMMEDIATE`, du délai de W, de la transition sans changement de ligne après une lecture `ISSUED`, des erreurs d’invocation et des issues des autres commandes (`prepare`, `list`, `show`, `emergency reject`, réouverture de D-9) ; la concordance entre catégories et codes de réponse, et le canal de ces codes ; toutes les valeurs numériques, le report de celle de `EXIT_FAIL_STOP` étant inchangé ; la transmission par la CLI, sudo, SSH ou le superviseur, et la vérification de ces chaînes sur le serveur ; la conduite face à un statut inconnu ou au statut 255 ; la politique de redémarrage du processus par le superviseur.

### 10.3 Tentatives refusées

- Un `apply` refusé lors des étapes 2 à 8 de V0, y compris pour un écart de l’identifiant de reprise à l’étape 4, fait passer le nonce à `FAILED` par une transition conditionnelle, effectuée dans la même transaction `BEGIN IMMEDIATE` après un retour au `SAVEPOINT`. C’est la règle « une tentative par nonce », hors erreurs SQLite (§5.5.1 ; décidé le 27 octobre 2026, §14, point 24). Un refus dû **uniquement** à l’ancre (indisponible, absente ou divergente) ou à une queue en attente (étape 1a), ou un arrêt du processus avant le `COMMIT`, laisse le nonce `ISSUED` (§5.5.1). Une nouvelle tentative avec le même énoncé signé reste possible avant `expires_at_ms` (§14, point 21). Un compteur borné est tenu par opération et par classe de refus. L’échec de synchronisation du marqueur avant toute écriture ne l’incrémente pas (décidé le 28 octobre 2026 [D], ci-dessous). Aucune copie de l’énoncé ni de l’assertion refusés n’est gardée.
- **Course sur le nonce — fermée le 27 octobre 2026 [D]** (§5.5.1 ; §14, point 24). Le verrou d’écriture SQLite est gardé depuis l’échec jusqu’au `COMMIT` de la transition conditionnelle `ISSUED` → `FAILED`. Un second `apply` ne peut donc plus décider sur un nonce encore `ISSUED` entre les deux. Si la transition ou le `COMMIT` échoue après un retour au `SAVEPOINT` réussi, l’effet de l’opération est annulé, et seul le sort du nonce est incertain. Si le retour au `SAVEPOINT` ou l’annulation complète échoue, aucun `COMMIT` ne suit, et l’absence d’effet n’est affirmée qu’une fois l’annulation établie, ou déduite sous les conditions du §5.5.1. `in_transaction` seul n’y suffit pas. Une erreur du `COMMIT` du chemin de succès n’est pas un refus et ne déclenche aucune nouvelle tentative automatique [D]. Après une erreur de `COMMIT`, B n’est relâchée qu’une fois la transaction résolue sur la connexion. Ni `show` ni une relecture n’établit à lui seul la durabilité. Détails, constat de l’état et points ouverts [O] : §5.5.1, « Erreurs SQLite dans la transaction de V0 ».
- **Gel après une issue indéterminée — décidé le 27 octobre 2026 [D]** (§5.5.1, cas 3).
  - Après une erreur de `COMMIT` dont l’issue est indéterminée, le service refuse les opérations d’approbation jusqu’à une récupération et une vérification explicites.
  - Pendant l’incertitude, aucune nouvelle autorisation n’est délivrée et aucune opération qui ouvre n’est acceptée. La lecture seule à des fins de constat reste possible.
  - Ce refus ne modifie ni les règles de nonce ci-dessus, ni S4.
  - **Transactions couvertes — décidé le 27 octobre 2026 [D]** (§5.5.1, cas 3, « Transactions couvertes » ; §11.2). Toute transaction V0, qu’elle consigne une opération qui ouvre ou une opération signée qui ferme, et la transaction d’E qui enregistre une autorisation. Seule une issue indéterminée du `COMMIT` déclenche le gel ; un non-`COMMIT` établi par un `ROLLBACK` réussi ne le déclenche pas, sauf si une règle déjà décidée l’exige.
  - **Gel conservateur — décidé le 27 octobre 2026 [D]** (§5.5.1, cas 3, « Gel conservateur »). Tout marqueur encore présent après l’arrêt d’un processus ou une issue non résolue maintient le gel, y compris après un redémarrage : arrêt avant le `COMMIT`, pendant le `COMMIT` ou après un `COMMIT` réussi mais avant le retrait. Aucun nettoyage automatique ne le retire. Le gel ne prend fin qu’après une récupération, une vérification et une levée explicites. Un `ROLLBACK` complet réussi et établi, suivi du retrait normal, ne le déclenche pas.
  - **Mécanisme du marqueur — décidé le 28 octobre 2026 [D]** (§5.5.1, cas 3, « Mécanisme du marqueur »). Un marqueur distinct par transaction couverte, fichier persistant hors de SQLite, créé avant les écritures de la transaction. Le service ne le retire qu’après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi, jamais après un `ROLLBACK TO SAVEPOINT` seul. Un marqueur restant maintient le gel, sans nettoyage automatique au démarrage ; `root` ne retire un marqueur résiduel qu’après une récupération et une vérification explicites. Le mécanisme protège contre les erreurs de processus et de stockage, pas contre un compte de service compromis. Les règles de nonce ci-dessus sont inchangées.
  - **Verrou W — décidé le 28 octobre 2026 [D]** (§5.5.5, L.2). Les transactions couvertes prennent W avant G et examinent sous W les marqueurs existants. Pour E et les opérations qui ouvrent, un marqueur résiduel entraîne un refus sans écriture. Sa qualification, son éventuel comptage, qui doit rester compatible avec un refus sans écriture, et le sort du nonce restent ouverts [O].
  - **Échec de synchronisation du marqueur — décidé le 28 octobre 2026 [D]** (§5.5.1, cas 3, « Mécanisme du marqueur »). Si la synchronisation du marqueur ou de son répertoire échoue avant toute écriture SQLite, la transaction n’exécute aucune écriture de base et suit la conduite de refus prévue ; elle ne supprime aucun marqueur d’une autre transaction. Son propre marqueur relève de la règle de retrait déjà décidée : après un `ROLLBACK` complet réussi, le service peut tenter de le retirer. **Précisé le 28 octobre 2026 [D] :** la transaction se termine alors par un `ROLLBACK` complet avant de poursuivre. Si ce `ROLLBACK` échoue ou si son issue ne peut pas être établie, aucun `COMMIT` ne suit et le service applique la règle fail-stop propre à ce cas, plus stricte que la règle générale du §5.5.1, cas 2, point 2 : tout échec de ce `ROLLBACK`, même si `in_transaction` est faux et que l’annulation pourrait être déduite selon cette règle générale, met fin au processus sans autre instruction, comme au cas 2, point 3. Le marqueur est laissé en place s’il est présent, et la règle générale du point 2 reste applicable aux autres erreurs. **Refus et nonce — décidés le même jour [D]** (§5.5.1, cas 3, « Mécanisme du marqueur ») : ce refus est un échec technique fermé ; pour V0, le nonce n’est ni consommé, ni passé à `FAILED`, ni renouvelé, et reste `ISSUED` jusqu’à son expiration normale s’il l’est encore ; le refus n’incrémente pas le compteur des tentatives d’autorisation ; aucune nouvelle tentative automatique n’est lancée. **Précisé le même jour [D] :** ce refus n’incrémente pas non plus le compteur borné par opération et par classe de refus (ci-dessus) ; les autres catégories de refus et leurs compteurs sont inchangés. Une télémétrie diagnostique éventuelle reste facultative et hors du protocole d’autorisation ; elle ne doit retarder ni le `ROLLBACK` ni le fail-stop. Le refus porte le code technique de réponse décidé le même jour (§10.2), avec son qualificatif sur le retrait ; ce code n’est émis qu’après le `ROLLBACK` complet réussi, jamais en cas de fail-stop. Les trois valeurs du qualificatif sont fixées (§5.5.1, cas 3, « Mécanisme du marqueur » ; §10.2) ; son nom exact et les noms de ces valeurs restent ouverts [O].
  - Restent ouverts [O] : sa qualification et son comptage, le mécanisme et les délais de W, les détails du marqueur, y compris la conduite si sa création échoue et le sort du nonce dans ce cas, hors l’échec de synchronisation du marqueur ou de son répertoire, réglé [D] (ci-dessus), les critères de récupération, la vérification qui le lève et les critères détaillés de la levée.
- **Échec propre à la barrière γ1, avant la vérification de l’assertion — décidé le 27 octobre 2026 [D] (§5.5.5, J.7).** Seuls ces cas laissent le nonce `ISSUED`. Le refus 1b, ci-dessous, garde sa règle `FAILED`.
  - Échec de la barrière, politique `root` inaccessible ou échec de l’écriture de `c` : le nonce reste `ISSUED`, et le refus est compté de façon bornée.
  - Divergence d’intégrité détectée par la barrière : S4 est maintenu jusqu’à la résolution, sans écriture de `FAILED`. Le nonce reste `ISSUED`, mais aucune opération signée n’est admise pendant S4.
  - Un refus survenu après l’obtention de la barrière suit les règles déjà décidées : celles ci-dessus, et celle du refus 1b ci-dessous.
  - Un échec de l’écriture de `FAILED` ne permet jamais un effet.
- Un échec de E au moment d’un usage (V1, y compris un refus dû au statut de la clé selon le §5.5.3, relecture de l’ancre ou couverture) est un refus fermé du chemin d’approbation. Il est compté de façon bornée et ne modifie ni la confirmation, ni le nonce, ni le compteur. Une erreur du `COMMIT` par lequel E enregistre sa décision n’est pas un tel refus : elle relève du gel ci-dessus lorsque son issue est indéterminée [D].
- **Validation pré-ancrage (§11.3, « Issue de la validation »).**
  - **Mènent à S4,** et la queue n’est pas ancrée : uniquement les échecs d’intégrité et les divergences que le §11.3 définit.
  - **Ne mènent pas à S4 :** une péremption de politique, un import en échec ou une révocation défavorable **apparus après une opération légitime**. L’entrée peut être ancrée pour l’audit, mais elle reste sans effet, et la suspension demeure jusqu’à une reprise effective (§11.2 ; §5.2.7, M.6). Il ne s’agit ni d’un refus ni d’un échec de la validation.
- **Refus de V0 pour suspension.** Il est distinct du cas précédent. Lorsque la politique est **déjà** suspendue (politique périmée, import en échec ou révocation défavorable connue), la précondition de V0 refuse l’opération ordinaire qui ouvre (opérations 1 à 4 du §11.2), qui n’est donc pas enregistrée (§5.5.1, étape 1 ; §5.2.7, M.6).
  - Contrairement au refus pour ancre ou queue, ce refus (étape 1b) fait passer le nonce à `FAILED`, par une transition conditionnelle effectuée dans la même transaction après un retour au `SAVEPOINT` (§14, point 24). Après la reprise effective, un nouveau nonce et une nouvelle assertion seront nécessaires (§5.5.1 ; §14, point 21). Il est compté de façon bornée.
  - Si le passage à `FAILED` échoue, l’ancienne assertion reste inutilisable après la reprise. Cela tient à l’identifiant de reprise inscrit dans les octets canoniques signés et couvert par le défi (§5.3), que V0 reconstruit à partir de la chaîne concordante avec l’ancre relue et compare à la valeur signée (§5.5.1, étape 4). Ni une valeur SQLite seule ni `prepared_at_ms` ne garantissent cette règle.
  - Le même contrôle, à E, refuse l’autorisation (§11.2, étape 4).
- Les futures requêtes web non authentifiées sont comptées ou agrégées de façon bornée (G1 §4.9).
- Le signal de compteur d’administration (option (b), décidée le 26 octobre 2026, §5.5.4) n’est pas un refus : il ne fait pas passer le nonce à `FAILED` et ne bloque pas l’effet si les autres contrôles réussissent. Il est consigné au plus une fois par credential et par nonce [R] ; ses autres détails restent ouverts (§5.5.4).
- [O] Fenêtre et bornes des compteurs ; aucune valeur n’est fixée ici.

## 11. Journal chaîné et ancrage externe

### 11.1 Principes

- [F] Le journal v3 n’est ni chaîné ni ancré ; v5 n’écrit rien au journal.
- [D] J-b et J-c (G1 §4.9, D-7).
- [R] **Aucune activation réelle sans J-b et J-c opérationnels**, à deux moments distincts :
  - **avant l’enregistrement** : `CONFIRM` refuse si l’ancre, relue pendant l’`apply`, est indisponible, absente ou divergente, ou si une queue locale attend l’ancrage (§5.5.1, étape 1) ;
  - **avant tout usage** : la confirmation enregistrée n’est effective que si le contrôle E réussit, avec une relecture de l’ancre qui couvre son entrée (§11.2).
- [R] **J-b.** Chaque entrée porte `prev_hash` et `entry_hash` = SHA-256(séparation de domaine ‖ `prev_hash` ‖ entrée canonique) ; elle est écrite dans la transaction de l’effet. Liste fermée d’événements :
  - invitation créée, révoquée ou expirée ;
  - inscription créée, confirmée, ou rejetée (avec son code) ;
  - nonce clos `FAILED` ;
  - credential d’administration ajouté ou révoqué ;
  - credential d’administration réautorisé ;
  - genèse ou nouvelle genèse (empreinte du fichier de confiance et de l’enregistrement d’attestation, dont la chaîne `x5c`) ;
  - import ou mise à jour des artefacts d’attestation, accepté ou refusé (empreintes du BLOB, des informations de révocation et du fichier de politique ; `no` ; `nextUpdate`) ;
  - suspension des opérations qui ouvrent (`nextUpdate` dépassé, import en échec) ; révocation d’attestation défavorable détectée et fermeture qui en résulte ;
  - reprise de suspension, opération 5 qui ouvre (§11.2), avec la revue qui la précède après une révocation connue ;
  - opération d’urgence ;
  - signal de compteur et compteur de refus.

  Les éléments d’attestation de cette liste, y compris la suspension et la reprise de suspension, sont exigés par la décision du 26 octobre 2026 (§5.2.7, M.6 et M.9) [D]. La journalisation des changements de statut d’un credential d’administration, dont le retrait et le marquage `COMPROMISED`, et celle de sa réautorisation sont aussi exigées par les décisions du 26 octobre 2026 (§5.5.3 ; §14, point 9) [D] ; le format et le contenu de ces entrées, la désignation fiable de leur entrée de journal et le classement de la réautorisation parmi les opérations du §11.2 restent [R] ou [O] (§5.5.3). Le reste de la liste demeure [R]. Les entrées ne contiennent que des empreintes d’identifiants, des codes et des instants, jamais de secret.
- [R] **J-c.** Après le `COMMIT`, le triplet (`store_id`, séquence, `entry_hash`) est ajouté hors serveur. L’ajout est idempotent : présenter de nouveau le même triplet ne change rien, alors qu’une empreinte différente pour une même séquence est une divergence.

### 11.2 Enregistrement et autorisation effective : états d’une opération qui ouvre

[R] Les opérations se répartissent en deux classes :

- **Opérations qui ouvrent** :
  1. confirmation d’une inscription ;
  2. création d’une invitation ;
  3. ajout d’un credential d’administration ;
  4. réouverture de l’interrupteur (§7.1) ;
  5. **reprise de suspension**, soumise à une condition spéciale (ci-dessous). C’est la seule opération qui ouvre admise pendant une suspension (§5.2.7, M.6, décision du 26 octobre 2026 [D]).

  Les opérations 1 à 4 sont les **opérations ordinaires qui ouvrent**.
- **Opérations qui ferment** : rejet, révocation, clôture de nonces, opérations d’urgence.

Une opération qui **ferme** prend effet dès le `COMMIT` local, sans attendre l’ancre : elle ne fait que réduire les capacités, et l’échec reste fermé. Elle est ancrée ensuite avec le reste de la queue. Une opération qui **ouvre** n’est **effective** qu’après l’ancrage et la relecture de l’entrée qui la consigne.

**Opérations signées qui ferment — décidé le 26 octobre 2026, précisé le 27 octobre 2026 [D] (§5.5.1, étape 5).** Leur V0 vérifie la liaison à l’autorisation effective du credential contre le fichier de confiance protégé par `root`, sans relire J-c ni exiger une queue vide. Il n’accepte l’opération que si le credential signataire est autorisé et si sa chaîne d’autorisation n’a pas été invalidée ; le statut `ACTIVE` ne suffit pas à lui seul. Acceptée, la fermeture prend effet au `COMMIT` local, sans attendre l’ancrage. Un échec d’ancrage ultérieur ne la rouvre pas, et son entrée reste à ancrer avec la queue. Aucune opération qui ferme ne dépend donc d’une relecture de J-c pour prendre effet. Si V0 ne peut pas établir cette validité, l’opération signée est refusée ; la voie d’urgence du §7.0 reste distincte et limitée à sa portée décidée, la fermeture de l’interrupteur. La représentation et la preuve de cette validité restent ouvertes ; elles sont analysées au §5.5.5.

**Marquage `COMPROMISED` — décidé le 27 octobre 2026 [D] (§5.5.5, J.1 à J.7).** C’est une transition spéciale de la politique d’autorisation, et non une fermeture ordinaire. Il ne prend effet qu’à l’installation de la nouvelle politique protégée par `root`, et non au seul `COMMIT` SQLite. Son entrée J-b est consignée ensuite par le service, sous barrière, puis ancrée avec la queue. **Cette exception ne change pas la règle ci-dessus :** les autres fermetures restent effectives au `COMMIT` local. Une impossibilité temporaire de lire la politique ou de consigner cette entrée est un refus de précondition γ1 ; une divergence entre la politique et l’événement `root` est un incident d’intégrité qui maintient S4 jusqu’à la résolution. Dans ces deux cas, le nonce reste `ISSUED` (J.7).

**Réautorisation d’une clé ajoutée par une clé ultérieurement `COMPROMISED` — décidé le 26 octobre 2026 [D] (§5.5.3).** Elle ne prend effet qu’après l’ancrage et la relecture de son entrée, et pour les opérations futures seulement. Son classement dans la liste ci-dessus, son nom et son format restent ouverts [O].

**Contrôle de la politique d’attestation — décidé le 26 octobre 2026 [D] (§5.2.7, M.6, complément).** Avant **chacune des quatre opérations ordinaires qui ouvrent** (1 à 4 ci-dessus), le stockage vérifie la politique d’attestation locale, protégée par `root` (§9.2).

Le contrôle a lieu à la précondition de V0 (§5.5.1, étape 1), dans la transaction de l’opération. Pour la création d’une invitation, dont le protocole signé n’est pas encore décrit (§6.2), il précède de même la création, dans sa transaction. Son futur énoncé signé devra en outre contenir l’identifiant de la dernière reprise effective : c’est une contrainte à intégrer lors de sa conception (§5.3 ; §5.5.1, étape 4).

L’opération est refusée si :
- la politique est périmée (`nextUpdate` dépassé, selon l’horloge du stockage) ;
- le dernier import est en échec ;
- une révocation défavorable est connue,

tant qu’aucune reprise de suspension effective n’est intervenue. Les opérations 1 à 4 restent donc **bloquées pendant toute la suspension**, y compris lorsqu’une reprise est enregistrée mais que son entrée n’est pas encore ancrée et relue.

**Condition spéciale : reprise de suspension (opération 5).**
- **Conditions.** Elle exige :
  - une décision administrative authentifiée ;
  - une politique redevenue valide : `nextUpdate` non dépassé, dernier import réussi ;
  - après une révocation défavorable connue, une revue qui établit que la politique est de nouveau satisfaite.

  Son V0 vérifie ces conditions **à la place** de l’absence de suspension.
- **Légitimité et effet — décidé le 26 octobre 2026 [D] (§5.2.7, M.6).**
  - **Légitimité.** L’entrée est journalisée. Avant l’envoi à l’ancre, la validation pré-ancrage vérifie, par une branche dédiée, la légitimité de son énoncé signé et de son assertion au moment de l’opération (§11.3, étape 3).
  - **Effet.** La reprise ne lève la suspension qu’après l’ancrage et la relecture requis, et seulement si la politique est encore valide à ce moment (§5.2.7, M.6 et M.9).
  - **Cause intermédiaire.** Si une cause de suspension survient entre l’opération et l’ancrage (`nextUpdate` expiré, import en échec, révocation défavorable connue), l’entrée peut être ancrée pour l’audit. Elle reste toutefois **sans effet**, et la suspension demeure jusqu’à une nouvelle reprise authentifiée, faite après rétablissement d’une politique valide. Ce cas n’est **pas** une divergence S4.
- **Portée limitée.** Cette exception ne permet **aucune autre** opération qui ouvre : les opérations 1 à 4, comme E, restent refusées tant que la reprise n’est pas effective au sens ci-dessus. Une reprise légitime mais sans effet ne lève rien. La reprise ne change le statut d’aucun credential (§5.5.3).
- **Clé `COMPROMISED` — décidé le 26 octobre 2026 [D] (§5.5.3).** Une reprise signée par une clé marquée `COMPROMISED` ne lève aucune suspension pour l’avenir. La formulation opérationnelle de M.6 ne vérifie pas encore la clé signataire ; la manière de l’y intégrer reste ouverte [O].
- **Échec.** Si ses conditions ne peuvent pas être établies, la reprise est refusée et le système reste suspendu (§5.2.7, M.6).
- **[O]** Le nom et le format exact de l’opération de reprise restent ouverts. La fréquence de relecture de l’ancre reste aussi ouverte (ci-dessous ; §14, point 18).

**Opérations qui ferment.** Elles **restent permises pendant une suspension** et ne sont jamais soumises à ce contrôle.

Soit `n` la séquence de l’entrée de journal qui consigne une confirmation, et `H` la dernière tête relue et validée sur l’ancre.

| État | Situation | En base | Utilisable par le chemin d’approbation |
|---|---|---|---|
| **S0 — préparée** | Nonce `ISSUED` ; `apply` non validé, ou arrêté avant le `COMMIT` | Rien de l’effet | Non |
| **S1 — enregistrée, non ancrée** | `COMMIT` local fait ; aucun ajout à l’ancre n’a encore été tenté pour `n`. Le passage à S2 exige d’abord la validation pré-ancrage (V1 et chaîne, §11.3) | Inscription `CONFIRMED`, lignes du registre, confirmation, entrée `n`, nonce `CONSUMED` | **Non** |
| **S2 — ancrage en cours** | Validation pré-ancrage réussie ; ajout envoyé à l’ancre, sans relecture validée (réponse attendue, perdue ou expirée) | Identique à S1 | **Non** |
| **S3 — ancrée et relue** | Une relecture de l’ancre a montré une entrée (`store_id`, `m`, `h_m`) avec `m ≥ n` ; la chaîne locale recalculée jusqu’à `m` donne `h_m` ; les entrées déjà validées n’ont pas changé ; la séquence de l’ancre est continue | Identique à S1 | **Seulement si le contrôle E réussit au moment de l’usage**. S3 décrit le résultat d’une relecture passée ; E relit l’ancre à chaque usage (ci-dessous) |
| **S4 — bloquée** | Divergence entre la base, le témoin local et l’ancre | Inchangé, rien n’est supprimé | **Non**, ni pour cette confirmation ni pour aucune autre : le service reste fermé (D-7) |

**Contrôle d’effectivité E, au moment de l’usage.** Avant d’utiliser un approbateur ou un credential, le chemin d’approbation :

1. exécute V1 (§5.5.2) ;
2. relit l’ancre et vérifie sa concordance avec la base et le témoin local, comme D-7 l’exige avant de délivrer une autorisation ;
3. vérifie que l’entrée `n` de la confirmation est couverte par la tête relue (`n ≤ m`) ;
4. **vérifie la politique d’attestation locale, protégée par `root`** — décidé le 26 octobre 2026 [D] (§5.2.7, M.6, complément). Il refuse toute autorisation si la politique est périmée, si un import est en échec ou si une révocation défavorable est connue, tant qu’aucune reprise effective n’est intervenue. Une reprise n’est effective qu’ancrée et relue, et seulement si aucune cause de suspension n’est survenue depuis son opération (§5.2.7, M.6, complément « légitimité de l’entrée et effet de la reprise »). Ce refus vaut pour **toute** autorisation délivrée par le chemin d’approbation, y compris celles qui reposent sur des confirmations déjà effectives, et quel que soit l’état S3.

**Champ de reprise de l’énoncé signé dans E — décidé par le propriétaire le 26 octobre 2026 [D]** (§5.3 ; §5.5.1, étape 4 ; §14, point 21).
- À l’étape 1, V1 vérifie ce champ uniquement comme partie de l’énoncé signé : octets canoniques, défi et signature. Ni V1 ni E ne le comparent à la reprise effective courante ; cette comparaison est réservée à V0, au moment de l’`apply`.
- Une reprise ultérieure ne rend donc pas inutilisables les confirmations déjà enregistrées.
- La suspension reste traitée par l’étape 4, qui applique à chaque usage le contrôle de la politique et de la suspension **courantes**.

Le témoin local et toute valeur mise en cache (par exemple `H` enregistré en base ou dans un fichier) peuvent servir à **refuser** plus vite, jamais à **accepter** : ils sont modifiables par le compte de service. [O] Relecture de l’ancre à chaque usage ou une fois par demande d’approbation ; dans les deux cas, elle a lieu avant de délivrer l’autorisation. Cette fréquence reste ouverte : la décision M.6 ne la tranche pas (§14, point 18). Le contrôle de l’étape 4 a lieu, lui, avant chaque autorisation.

**Aucun drapeau stocké n’autorise.** Le passage de S1 à S3 n’écrit pas « effective » en base. L’effectivité est recalculée à chaque usage par E, à partir de V1 et de l’ancre relue. Une écriture directe dans la base ne peut donc pas faire passer une confirmation de S1 à S3.

**Trois contrôles à ne pas confondre.**
- **Précondition de V0** (§5.5.1, étape 1) : elle porte sur l’état antérieur à l’opération et conditionne l’enregistrement. Elle comprend le contrôle de la politique d’attestation (M.6).
- **Validation pré-ancrage** (chaîne, V1 et absence de suspension pour les opérations 1 à 4, branche dédiée pour la reprise de suspension, §11.3) : elle conditionne l’ancrage.
- **E** : il conditionne chaque usage. Il comprend le contrôle de la politique d’attestation (étape 4).

Aucun des deux premiers ne vaut autorisation effective.

**Contrôle E et barrière γ1 — décidé le 27 octobre 2026 [D] (§5.5.5, L.2 et L.5).**
- La barrière couvre le contrôle de politique d’E jusqu’à l’enregistrement local de la décision d’autorisation. La relecture réseau de J-c reste hors barrière.
- Après avoir pris la barrière, E revérifie la génération `root`. Il refuse si l’ancre relue ne couvre pas la génération courante, ou si celle-ci a changé depuis sa vérification.
- Une telle course entraîne un refus fermé, sans décision enregistrée. Une nouvelle tentative recommence par la relecture de l’ancre.
- Aucune autorisation n’est ainsi enregistrée sous une génération antérieure à celle en vigueur.
- **Précisé le 27 octobre 2026 [D] :** l’ancre couvre la génération courante si l’entrée `c` qui la consigne est incluse dans la tête J-c qu’E vient de relire. La règle vaut pour la génération initiale : aucune autorisation E avant que son entrée soit consignée et ancrée. Les détails techniques de l’ancrage de la genèse restent ouverts (§11.4) [O].
- Ces précisions ne changent pas les conditions d’effectivité des opérations qui ouvrent.
- L’ordre exact des étapes reste [R] (§5.5.5, L.2).

**Gel après une issue indéterminée — décidé le 27 octobre 2026 [D]** (§5.5.1, cas 3).
- Après une erreur de `COMMIT` dont l’issue est indéterminée, E ne délivre aucune nouvelle autorisation, et aucune opération qui ouvre (1 à 5 ci-dessus) n’est acceptée. Cela dure jusqu’à une récupération et une vérification explicites.
- La lecture seule à des fins de constat reste possible.
- Ce gel s’ajoute aux refus existants (D-7, suspension, S4) sans les modifier.
- **Transactions couvertes — décidé par le propriétaire le 27 octobre 2026 [D]** (§5.5.1, cas 3, « Transactions couvertes »). Toute transaction V0, qu’elle consigne une opération qui ouvre ou une opération signée qui ferme (§11.2, ci-dessus), et la transaction d’E qui enregistre une autorisation (puce suivante). Cette décision ne fixait pas le mécanisme qui arme ou conserve le gel ; il a été fixé le 28 octobre 2026 (ci-dessous).
- **Étendu au `COMMIT` d’E — décidé par le propriétaire le 27 octobre 2026 [D]** (§5.5.1, cas 3, « Extension au `COMMIT` d’E » ; §5.5.5, L.2, E6). Si le `COMMIT` par lequel E enregistre une autorisation a une issue indéterminée, E ne délivre aucune nouvelle autorisation, et le même gel s’applique jusqu’à une récupération et une vérification explicites. Un échec dont le non-`COMMIT` est établi par un `ROLLBACK` réussi ne le déclenche pas, sauf si une règle déjà décidée l’exige.
- **Gel conservateur — décidé par le propriétaire le 27 octobre 2026 [D]** (§5.5.1, cas 3, « Gel conservateur »). Tout marqueur encore présent après l’arrêt d’un processus ou une issue non résolue maintient le gel, y compris après un redémarrage, quel que soit le moment de l’arrêt : avant le `COMMIT`, pendant, ou après un `COMMIT` réussi mais avant le retrait. Aucun nettoyage automatique ne le retire, et le gel ne prend fin qu’après une récupération, une vérification et une levée explicites. Un `ROLLBACK` complet réussi et établi, suivi du retrait normal, ne le déclenche pas.
- **Mécanisme du marqueur — décidé par le propriétaire le 28 octobre 2026 [D]** (§5.5.1, cas 3, « Mécanisme du marqueur »). Chaque transaction couverte, y compris celle d’E, a son propre marqueur, fichier persistant hors de SQLite, créé avant ses écritures. Le service ne le retire qu’après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi, jamais après un `ROLLBACK TO SAVEPOINT` seul. Un marqueur restant après un arrêt ou une issue indéterminée maintient le gel, sans nettoyage automatique au démarrage ; `root` ne retire un marqueur résiduel qu’après une récupération et une vérification explicites. Limite déjà établie : protection contre les erreurs de processus et de stockage, pas contre un compte de service compromis.
- **Verrou W et ordre — décidés par le propriétaire le 28 octobre 2026 [D]** (§5.5.5, L.2). E, comme V0, prend W avant G et examine sous W les marqueurs existants ; un marqueur résiduel entraîne un refus sans écriture. E crée son marqueur après `BEGIN IMMEDIATE`, avant E3, et garde W jusqu’à la résolution de sa transaction. Après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi, il peut tenter de retirer son marqueur ; B puis W sont relâchés même si ce retrait a échoué. Si l’issue est indéterminée, le marqueur reste en place (précisé le même jour, §5.5.1, cas 3, « Mécanisme du marqueur »). La place de la remise E7 par rapport à ce retrait reste ouverte [O].
- Restent ouverts [O] : les détails du marqueur (§5.5.1, cas 3, « Mécanisme du marqueur »), le mécanisme et les délais de W, la portée de la remise E7, les critères de récupération, la vérification qui lève le gel et les critères détaillés de la levée.

### 11.3 Incidents

| Incident | État résultant | Conduite |
|---|---|---|
| Ancre indisponible au moment de l’ajout | S1 | Nouvel essai du même triplet (idempotent). La confirmation reste inutilisable ; tant que l’ancre est indisponible, le service ne délivre aucune autorisation (D-7). Les opérations qui ferment restent possibles et allongent la queue. Toute nouvelle opération qui ouvre est refusée tant que la queue n’est pas ancrée (§5.5.1, étape 1) |
| Issue de l’ajout inconnue (délai dépassé, réponse perdue) | S2 | Relecture. Entrée présente et concordante : S3. Absente : nouvel ajout du même triplet. Empreinte différente : S4 |
| Divergence : empreinte différente pour une séquence déjà écrite, tête de l’ancre au-delà de la tête locale (base plus ancienne, restauration), chaîne locale qui ne se recalcule pas, entrée déjà validée modifiée ou disparue | S4 | Service fermé, aucune ligne effective, y compris celles qui l’étaient. Rien n’est supprimé ni réécrit automatiquement. Rapprochement manuel, puis réouverture par le propriétaire selon D-9 et T-1 (§7.1) |
| Arrêt avant le `COMMIT` | S0 | Nonce `ISSUED` ; l’assertion peut être présentée de nouveau avant `expires_at_ms` (§5.5.1). Si le marqueur du gel était présent, ce qui est le cas dès sa création, après le `SAVEPOINT` pour V0 ou après `BEGIN IMMEDIATE` pour E [D, 28 octobre 2026] : gel conservateur [D], et nouvelle présentation d’une opération qui ouvre seulement après la levée (§5.5.1, cas 3, « Gel conservateur ») |
| Erreur du `COMMIT` d’une transaction V0, qu’elle ouvre ou qu’elle ferme, ou de la transaction d’E (E6), issue indéterminée (§5.5.1, cas 3, points b et c ; transactions couvertes décidées le 27 octobre 2026 [D]) | S0 ou S1, selon l’état visible ; durabilité non établie. Pour une fermeture signée, la fermeture est visible ou non, sans preuve de durabilité (§5.5.1, cas 3). Pour E, la confirmation garde son état : c’est la décision d’autorisation enregistrée qui est incertaine | **Gel décidé le 27 octobre 2026 [D]** : aucune nouvelle autorisation E et aucune opération qui ouvre, jusqu’à une récupération et une vérification explicites ; lecture seule pour le constat. Une entrée visible, ancrée puis disparue localement, relève de la ligne « Divergence » (S4). Disparue avant l’ancrage, aucun contrôle décrit ne le détecte [O]. Le marqueur de la transaction reste présent, et seul `root` le retire, après une récupération et une vérification explicites [D, 28 octobre 2026]. Restent ouverts [O] : l’ancrage pendant le gel, les détails du marqueur (§5.5.1, cas 3, « Mécanisme du marqueur »), les critères de récupération et la vérification qui lève le gel |
| Arrêt après le `COMMIT`, avant l’ajout | S1 | Au redémarrage, la tête locale dépasse `H` : la queue `H+1 … n` est en attente. Validation pré-ancrage (ci-dessous), puis ajout et relecture. Si l’arrêt a précédé le retrait du marqueur : gel conservateur [D] jusqu’à la levée ; le sort de la validation pré-ancrage et de l’ancrage pendant le gel reste ouvert [O] |
| Arrêt après l’ajout, avant la relecture | S2 | Au redémarrage : relecture, puis comme ci-dessus |
| Arrêt après la relecture, avant la mise à jour du témoin local | S3 | Le témoin est en retard ; la relecture suivante le remet à jour. Le témoin n’a pas autorité |

**Divergence γ1 — décidé le 27 octobre 2026 [D] (§5.5.5, J.7).** Une divergence d’intégrité entre la politique `root` et l’événement conservé dans la zone `root`, détectée par la barrière γ1, est traitée en S4, dont la définition et la conduite ci-dessus restent inchangées. S4 est maintenu jusqu’à la résolution. Aucune écriture séparée de `FAILED` n’est tentée pendant l’incident : un nonce en cours reste `ISSUED`, et aucune opération signée n’est admise pendant S4. Après la résolution, V0 revérifie l’énoncé et le nonce, qui doit encore être valide. Les modalités techniques de la résolution restent ouvertes [O].

**Validation pré-ancrage.** [R] Elle s’applique à **tout** ancrage, juste après un `COMMIT` comme au redémarrage. Avant de valider ou d’ancrer une queue, la transaction applique la barrière γ1 et consigne, le cas échéant, la génération `root` non consignée (§5.5.5, J.5) [D]. **Réserve (§5.5.5, L.8, point 8, décidé le 29 octobre 2026 [D]) :** ni validation, ni consignation, ni ancrage pour une génération visible mais non déclarée effective ; le service reste alors fermé et ne l’utilise pas : aucune opération signée, aucune consignation de `c` ni aucun ancrage pour cette génération avant sa déclaration d’effectivité. **Principe O1-B — décidé le 1er novembre 2026 [D], sous condition [H] (§5.5.5, L.8, point 8, « Portée ») :** chaque validation et chaque ancrage suivent la règle de contrôle de l’état courant de D sous B ; une lecture antérieure ne suffit pas. **Option 2 — décidée le 1er novembre 2026 [D] (§5.5.5, L.6 ; §14, point 23, décision 16) :** la règle d’ancrage vise la génération et l’état de D contrôlés sous B lors de la validation de la queue. L’ajout externe à J-c, qui suit le `COMMIT` et a lieu hors barrière selon le protocole actuel, publie la queue déjà validée ; il n’est pas une nouvelle validation sous la génération qui pourrait être installée après le `COMMIT`. Une queue validée sous g demeure classée sous g, même si son ajout survient après l’installation de g+1 ; cet ajout peut précéder `c` de g+1, et ne constitue ni l’utilisation de g+1, ni un ancrage d’opération de g+1. Avant toute validation ultérieure sous g+1, le service vérifie sous B que D est actuellement confirmée et concorde avec P, et `c` de g+1 est consignée avant toute validation ou tout ancrage ultérieur sous g+1. La validation est rejouée au redémarrage, mais cette décision ne fixe pas, à elle seule, comment une queue dont la validation précédente a eu lieu sous g est traitée si la validation est rejouée après l’installation de g+1 [O]. Le processus de l’ajout, ses tentatives et ses issues inconnues restent aussi ouverts [O]. Avant d’ancrer une queue locale, le service :

1. recalcule la chaîne depuis `H` ;
2. pour chaque entrée de la queue qui consigne une **opération ordinaire qui ouvre** (opérations 1 à 4 du §11.2 : confirmation d’inscription, création d’invitation, ajout de credential d’administration, réouverture de l’interrupteur) :
   - exécute V1 sur sa confirmation signée ;
   - vérifie qu’elle n’a pas été enregistrée pendant une suspension (§5.2.7, M.6), d’après le journal (événements de suspension et de reprise, §11.1) et la politique d’attestation protégée par `root`.

   Une entrée 1 à 4 qui suit une reprise de suspension non encore ancrée et relue est illégitime par construction : V0 exige, pour toute opération qui ouvre, qu’aucune queue ne soit en attente d’ancrage (§5.5.1, étape 1) ;
3. pour chaque entrée de la queue qui consigne une **reprise de suspension** (opération 5 du §11.2), applique une **branche dédiée**. Elle vérifie :
   - **l’assertion administrative,** selon la règle applicable : V1 sur l’énoncé signé et l’assertion (§5.5.2), avec le statut de la clé tiré du fichier de confiance (§5.5.3) ;
   - **la politique redevenue valide et le dernier import réussi :** l’empreinte du fichier de politique, son `nextUpdate` et la référence au dernier import réussi, liés à l’énoncé signé, correspondent à la politique protégée par `root` et aux entrées de journal de l’import. Le `nextUpdate` n’était pas dépassé à l’instant de la reprise ;
   - **après une révocation connue,** la revue qui établit que la politique est de nouveau satisfaite : elle est consignée, et son empreinte est liée à l’énoncé signé de la reprise.

   **Légitimité, pas effet** — décidé le 26 octobre 2026 [D] (§5.2.7, M.6). La branche vérifie la légitimité de l’énoncé signé et de l’assertion **au moment de l’opération**, et seulement elle. Elle ne dit pas si la reprise lèvera la suspension.

   Si une cause de suspension survient entre l’opération et l’ancrage, l’entrée reste légitime et peut être ancrée pour l’audit. Les causes visées sont un `nextUpdate` expiré, un import en échec ou une révocation défavorable connue. L’entrée est alors **sans effet** : la suspension demeure, et une nouvelle reprise authentifiée est requise après rétablissement d’une politique valide (§11.2).

Cette branche **n’est pas un contournement général**. Elle ne valide que des entrées de reprise de suspension et ne rend aucune entrée 1 à 4 admissible. Comme toute validation pré-ancrage, elle ne rend rien effectif. La reprise ne lève la suspension qu’après l’ancrage et la relecture requis, si la politique est encore valide à ce moment. D’ici là, V0, pour les opérations 1 à 4, et E continuent de refuser (§11.2 ; §5.2.7, M.6 et M.9). Le nom et le format exact de l’opération et de son énoncé, y compris la façon d’y lier la politique, l’import et la revue, restent ouverts (§14, point 22).

**Issue de la validation, dans l’une ou l’autre branche.**
- **Mènent à S4,** sans ancrer cette queue : les **échecs d’intégrité et les divergences** définis par le protocole. Ce sont :
  - une chaîne qui ne se recalcule pas ;
  - un V1 en échec, notamment pour une signature invalide, ou pour une entrée enregistrée alors que la clé était déjà `COMPROMISED` selon l’ordre du journal. Un échec dû **uniquement** au marquage `COMPROMISED` d’une clé, enregistré après l’entrée, n’y mène pas (ci-dessous ; §5.5.3) ;
  - des éléments liés à un énoncé signé qui ne correspondent pas à la politique protégée par `root` ou au journal ;
  - une entrée 1 à 4 enregistrée pendant une suspension ;
  - une entrée de reprise dont les conditions n’étaient pas réunies à l’instant de son opération. Ces deux derniers cas supposent un contournement de V0.
- **Ne mènent pas à S4 :** une péremption de politique, un import en échec ou une révocation connue **survenus après l’opération**. Les entrées concernées, qu’il s’agisse d’une reprise ou d’une opération 1 à 4 légitime à son instant, peuvent être ancrées. Leur usage reste refusé par V0 et par E tant que la suspension n’est pas levée par une reprise effective.
- **Ne mène pas non plus à S4 — décidé le 26 octobre 2026 [D] (§5.5.3) :** le marquage `COMPROMISED` d’une clé, enregistré dans le journal après une entrée qui ouvre qu’elle a signée. L’entrée peut être ancrée pour l’audit, sans effet futur. L’ordre est établi par le journal, jamais par une date SQLite. Il n’est sûr que si l’entrée de marquage, ou celle de l’opération, est déjà ancrée. Si les deux attendent dans la même queue, le protocole ne permet pas de distinguer sûrement une entrée légitime d’une entrée placée avant le marquage ; cette limite est décrite au §5.5.3 [O].

Ancrer prouve l’existence et l’ordre d’une entrée, pas sa légitimité : il ne faut pas ancrer des entrées qu’un tiers aurait écrites dans la base, que le service soit arrêté ou non. Cette validation ne rend rien effectif. L’effectivité d’une confirmation est établie par E, au moment de l’usage. La levée d’une suspension par une reprise est évaluée à chaque contrôle de V0, pour les opérations 1 à 4, et de E (§5.2.7, M.6). Elle ne couvre pas l’énoncé signé non appliqué (§5.5.2).

### 11.4 Limites et points ouverts

- **Limites.** J-b seul ne détecte pas une réécriture complète. J-c ne la détecte que si ses droits d’écriture ne permettent ni remplacement ni suppression. Un attaquant qui détient le droit d’ajout peut ajouter de fausses têtes, ce qui n’est détectable qu’après coup ; V1 continue alors de refuser toute confirmation sans assertion valide du propriétaire, sauf le cas de l’énoncé signé non appliqué (§5.5.2).
- Le contrôle au moment de l’usage exige que le chemin d’approbation lise l’ancre, donc un accès réseau : c’est une exception à l’interdiction actuelle (§2.4, §9.3).
- [O] Fournisseur, compte et coût de l’ancre (D-7) ; processus qui l’écrit et qui la relit (exception réseau, §9.3) ; calendrier par rapport à la première activation ; fréquence de relecture (§11.2) ; horodatage par le fournisseur de l’ancre (§5.5.2).
- **Ancrage de l’enregistrement de genèse et des imports d’attestation — décidé le 26 octobre 2026 [D] (§5.2.7, M.9).** Sont ancrés le BLOB, `no`, `nextUpdate`, les informations de révocation, la chaîne `x5c` de l’attestation et l’empreinte du fichier de politique. Aucune opération qui ouvre ne devient effective avant l’ancrage requis. Une date de genèse ancrée permet de situer la genèse par rapport à la date de compromission d’une AC ou d’une clé d’attestation (§5.2.7, B.3 et J.5). [O] Comme la genèse a lieu système fermé, le moment de cet ancrage reste à fixer, de même que le fournisseur de l’ancre (point précédent).

## 12. Modèle de menace

Actifs protégés : la capacité d’activer un approbateur, l’intégrité du registre, le secret d’invitation et la disponibilité du service.

| Compromission | Ce que l’attaquant peut faire | Ce qu’il ne peut pas faire | Ce qui reste |
|---|---|---|---|
| Poste du propriétaire | Faire signer un autre énoncé que celui affiché lors d’une opération que le propriétaire lance ; lire les secrets d’invitation affichés | Signer sans contact avec la clé et sans UV | Non atténué. [O] Poste dédié à l’administration |
| Compte SSH `directoradmin`, sans `sudo` complet | `prepare`, lectures, voie d’urgence (blocage) | Confirmer ou rouvrir l’interrupteur sans credential d’administration (§7.1) | Dépend de la règle `sudo` |
| Compte SSH avec `sudo` complet, `root` ou serveur | Tout : modifier le code, ses dépendances, sa configuration, son lancement et le fichier de confiance (qui appartiennent à `root`), ainsi que la base ; installer une mise à jour malveillante par l’opération administrative ; forger une preuve GitHub et des activations ; contourner B | Réécrire l’historique déjà ancré sans les droits de l’ancre | **Hors de la protection d’A-1 (décision T-3 du 25 octobre).** Système maintenu fermé (D-15) ; détection après coup par J-c seulement |
| Compte de service ou processus web | Écrire la base, qui lui appartient : rejeter, révoquer, supprimer, bloquer ; lire les inscriptions ; lire et exécuter le code ; omettre, effacer ou ignorer un marqueur du gel (limite décidée le 28 octobre 2026, §5.5.1, cas 3, « Mécanisme du marqueur ») ; retenir ou ignorer le verrou W (§5.5.5, L.2 et L.4) | Modifier ou remplacer la CLI, le stockage, les vérifications V0/V1/E, le chemin d’approbation et de consommation, les dépendances, la configuration, le lancement ou le fichier de confiance (T-3) ; donc forger une activation valide ou ajouter un credential d’administration | Refus de service ; restauration non détectée sans J-c ; énoncé signé non appliqué (§5.5.2). **Réserve :** cette protection n’existe qu’une fois les détails de mise en œuvre de T-3 satisfaits et vérifiés (inventaire complet, caches de bytecode, chemins d’import propres à l’utilisateur, environnement, répertoires parents ; §9.2) |
| Compte GitHub ou appareils de B | Passer la preuve GitHub et inscrire ses propres credentials | Être activé sans la confirmation du propriétaire | Repose sur la vérification hors bande avec B (`APPROVER_DID_NOT_CONFIRM`) |
| Canal de remise du secret | Consommer l’invitation à la place de B | Passer la preuve GitHub sans le compte de B | — |
| Sauvegarde restaurée | Faire réapparaître un nonce `ISSUED` ; effacer une révocation ; faire disparaître un marqueur du gel créé depuis l’état restauré | — | Détection par J-c seulement, pour ce qui a été ancré. Une restauration n’est jamais, à elle seule, une levée explicite du gel [D, 28 octobre 2026] ; son application reste ouverte [O] |
| Perte d’une clé d’administration | — | — | Selon la décision du 25 octobre, l’autre clé suffit aux opérations courantes (§5.2.1) ; la conduite à tenir est ouverte (§5.7) |
| Perte des deux clés d’administration | — | — | Plus aucune activation ni réouverture ; procédure de rétablissement ouverte (§5.8), passant nécessairement par l’opération `root` contrôlée (T-3) |
| Poste du propriétaire compromis pendant la genèse | Faire enregistrer dans le fichier de confiance une autre clé publique que celle de la clé du propriétaire | — | Non atténué par la séparation de RP ID (§5.2.2). Avec AT-2, l’attaquant doit disposer d’un authentificateur authentique d’un modèle autorisé (§5.2.6, C ; WebAuthn §13.4.4) |
| Poste ou canal de récupération des artefacts d’attestation | Fournir une ancre, des métadonnées ou des informations de statut falsifiées ou anciennes | Faire accepter (décisions M.1, M.3 et M.5) :<br>– un BLOB dont la signature ne remonte pas à l’ancre MDS approuvée hors bande ;<br>– un BLOB qui contient `x5u` ;<br>– un `no` non supérieur au dernier accepté ;<br>– un `nextUpdate` dépassé ;<br>– une ancre qui diverge entre sources | Bloquer les opérations qui ouvrent en fournissant des artefacts refusés ou en n’en fournissant pas (suspension, M.6 ; §5.2.7, I-10). Ancre obtenue par le même canal que les données qu’elle vérifie : aucune indépendance (§5.2.7, I-8). [O] Canal de comparaison des empreintes hors bande |
| Fabricant, clé d’attestation ou AC du fabricant compromis | Produire des attestations valides pour un modèle autorisé | — | Détecté seulement par un statut ou une révocation importés plus tard (§5.2.7, I-7). [D] Fermeture des opérations qui ouvrent et revue (§5.2.7, M.6) |
| Métadonnées absentes, périmées ou indisponibles | Empêcher une genèse ; masquer une révocation postérieure ; suspendre les opérations qui ouvrent | Faire passer une genèse sans les informations exigées (M.5) ; maintenir les opérations qui ouvrent après le `nextUpdate` (M.6) | Refus fermé à la genèse. Après la genèse : suspension des opérations qui ouvrent, sans détection d’une révocation nouvelle tant qu’aucun import valide n’a lieu (§5.2.7, J.6) |
| Console Scaleway, DNS, compte GitHub du propriétaire | Contournement total | — | Hors modèle (G1 §5) |

## 13. Ce que cette spécification n’établit pas

Elle ne prouve ni l’identité civile de B, ni la séparation de deux personnes, ni H1. Elle ne résout pas D-5. Elle n’autorise aucune implémentation, inscription réelle, activation, OAuth, compte, secret client, callback public, déploiement ni Provider.

## 14. Décisions explicites requises

1. **Tranché le 25 octobre 2026** : A-1 est adopté comme orientation de conception pour confirmer les inscriptions D-5 `PENDING`, dans la portée décrite au §4.0. Le point 3 a été tranché ensuite (sauf la compatibilité réelle) ; le point 4 l’a été en partie (orientation générale), le reste demeurant ouvert. Les autres modalités d’A-1 restent des recommandations.
2. **T-1 — tranché le 25 octobre 2026** par une décision distincte : le propriétaire, unique administrateur, peut rouvrir l’interrupteur D-9 par SSH avec une assertion WebAuthn fraîche et UV de son credential d’administration ; B reste approbatrice uniquement, sans accès SSH ni rôle d’administration ; cette action n’autorise jamais le propriétaire à approuver une demande de génération (§3.1, §7.1).
    - **Précisé le même jour :** la règle « distinct de l’acteur GitHub du run » ne s’applique pas à la réouverture administrative.
    - **Alignement de G1 :** commité dans `73737dd`, CI réussie ; fusionné dans `main` par le PR #62 (`6313648`).
    - **Restent ouverts :** la liste des codes de motif de réouverture ; la conception de l’interrupteur.
    - **Restent des recommandations :** l’opération signée `SWITCH_REOPEN`, son énoncé et son classement parmi les opérations qui ouvrent (§7.1).
3. **RP ID et origine d’administration — tranchés le 25 octobre 2026** par une décision de conception distincte : option O-3, RP ID `ai-director-admin.invalid`, origine `https://ai-director-admin.invalid`, fixes pendant toute la vie des credentials d’administration (§5.1).
    - **Restent ouverts :** la compatibilité réelle avec Windows, CTAP et le modèle de clé retenu ; un essai avec une vraie clé exigera une autorisation distincte.
    - **En cas d’échec :** décision séparée sur le repli O-1, qui n’est pas adopté.
4. **Credentials d’administration : orientation générale tranchée le 25 octobre 2026** (§5.2.1).
    - **Décidé :** deux credentials sur deux clés matérielles distinctes (principale et secours) ; UV obligatoire à chaque signature ; `BE=0` requis (`BS=0` en découle selon WebAuthn) ; une seule des deux clés suffit aux opérations courantes.
    - **Décidé aussi, règles de la genèse initiale (§5.2.2) :** une seule fois, hors du service web, système fermé et Provider CLOSED ; création séparée des deux credentials par le client CTAP local (UV, RP ID et origine décidés, `BE=0`), sans export des clés privées ; validation des réponses d’inscription avant l’installation ; séparation physique vérifiée par contrôle humain ; installation `root` contrôlée, uniquement sans fichier existant, des deux entrées ensemble, sans écriture partielle ni remplacement ; règles T-3 ensuite ; toute erreur laisse le système fermé.
    - **Décidé aussi, cycle de vie des défis (§5.2.5, H) :**
      - C-1 : défis uniquement en mémoire d’une seule invocation `root`, sans reprise ;
      - O-a : un orphelin n’est jamais approuvé ni installé ;
      - aucun défi ne vient du client local ;
      - toute interruption ou erreur laisse le système fermé, et une nouvelle cérémonie, avec des défis frais, doit produire deux entrées validées ensemble ;
      - aucune durée ni aucun nombre de tentatives n’est fixé ;
      - C-1 sera réexaminé si le transfert ne permet pas une seule invocation.
    - **Restent ouverts (§5.2.3) :** les détails de la genèse (client local concret, forme du transfert, format du paquet d’inscription et du fichier de confiance, outil et procédure `root`, vérification exacte des réponses, pour laquelle une proposition technique figure au §5.2.4, durée des défis, nombre de tentatives, procédure physique de reprise sur une clé portant un orphelin et hypothèses sur les credentials découvrables, le stockage et le PIN (§5.2.5), journalisation et ancrage, traitement d’un échec et de toute réinitialisation ultérieure) ; la forme concrète du contrôle humain de séparation physique ; la règle d’ajout, de remplacement ou de révocation d’une clé de confiance (§5.7 ; le marquage `COMPROMISED` est tranché au point 23) ; la perte des deux clés (§5.8) ; les opérations qui pourraient exiger les deux clés ; la mise en œuvre de l’attestation (orientation décidée au §5.2.6 ; restent ouverts le modèle et ses AAGUID, les ancres, les métadonnées, les contrôles de validité et de révocation, l’attestation disponible par Windows et CTAP, et la procédure si la politique ne peut pas être satisfaite ; analyse au §5.2.7 ; orientations du cycle de vie décidées le 26 octobre 2026 au §5.2.7, M ; décisions prises et restantes récapitulées au point 22) ; la technique d’installation qui réalisera les garanties décidées de la règle 5 ; le partage éventuel d’une clé physique avec la clé SSH d’administration ; la compatibilité réelle avec Windows et CTAP.
    - **Déjà tranché ailleurs :** la propriété du fichier de confiance par `root` (point 14).
5. Client de signature local : emplacement (dans le dépôt ou non), dépendances, poste dédié (§4.2, §12).
6. Durées `T_nonce`, `T_invitation` et `T_attente` ; aucune valeur n’est proposée ici.
7. Liaison de la tête du journal à l’énoncé (§5.3).
8. **Compteur des credentials d’administration — tranché le 26 octobre 2026** : option (b), signal seulement (§5.5.1, étape 7 ; §5.5.4 ; §10.3).
    - `0` suivi de `0` : aucune anomalie ;
    - l’une des deux valeurs non nulle et nouvelle valeur inférieure ou égale à la précédente : signal borné, sans refus pour ce seul motif ;
    - nouvelle valeur enregistrée à chaque opération acceptée, y compris après un signal ;
    - le signal n’est ni une preuve de clonage ni une raison de changer automatiquement le statut du credential ou de suspendre le service ;
    - il ne fait pas passer le nonce à `FAILED` et ne bloque pas l’effet si les autres contrôles réussissent ;
    - **restent ouverts :** les détails du signal borné et la valeur initiale du compteur après la genèse (§5.5.4).
9. **Statuts des clés d’administration — tranchés le 26 octobre 2026** (§5.5.3 ; §5.5.1, étape 5 ; §5.5.2, contrôle 4).
    - `ACTIVE` : autorisé en V0 et vérifiable en V1 ;
    - `RETIRED` : refusé pour toute nouvelle opération V0 ; les confirmations antérieures au retrait restent vérifiables en V1. L’antériorité se définit par l’ordre des entrées de journal ancrées, jamais par une date en base ;
    - `COMPROMISED` : refusé en V0 et en V1 ; aucune confirmation signée par cette clé ne peut être utilisée, quelle que soit sa date, puisqu’aucune borne de compromission suffisamment fiable n’est établie ;
    - une anomalie `signCount` reste un signal seulement et ne change jamais automatiquement le statut d’une clé (point 8) ;
    - les changements de statut restent explicites, authentifiés, journalisés et ancrés selon les règles générales ;
    - **portée de `COMPROMISED` sur les opérations qui ouvrent :** une fois la clé marquée, aucune opération qui ouvre signée par elle (confirmation d’inscription, création d’invitation, ajout d’une clé, réouverture, reprise de suspension) ne peut fonder une autorisation future. Ses effets futurs sont refusés ou recalculés comme inactifs selon le chemin, sans modification rétroactive des opérations exécutées. Les opérations qui ferment restent applicables. Aucun statut ne change automatiquement. Si aucune clé `ACTIVE` ne permet d’établir un état valide, le système reste fermé ;
    - **marquage avant l’ancrage :** une entrée signée par la clé avant son marquage `COMPROMISED`, mais pas encore ancrée, peut être ancrée pour l’audit, sans effet futur. Ce changement de statut ne mène pas à S4 à lui seul ; S4 reste réservé aux divergences et aux échecs d’intégrité, dont une signature invalide ou une opération enregistrée après le marquage. L’ordre est établi par le journal, jamais par une date SQLite ; il n’est sûr que si l’entrée de marquage, ou celle de l’opération, est déjà ancrée (§5.5.3, §11.3) ;
    - **clé ajoutée par une clé ultérieurement `COMPROMISED` :** enregistrement et statut déclaré conservés, sans changement automatique. Elle n’autorise aucune opération future, ni en V0 ni en V1, tant qu’une clé `ACTIVE` ne l’a pas explicitement réautorisée (§5.5.3, §5.7) ;
    - **liaison à l’autorisation effective de la clé signataire :** chaque énoncé signé pour une opération administrative lie la signature à l’entrée qui autorise effectivement la clé signataire (genèse initiale, ajout ou réautorisation). Pour une opération qui ouvre, V0 vérifie cette liaison à l’`apply`, d’après la chaîne concordante avec l’ancre relue. V1 vérifie, pour une confirmation enregistrée, que l’entrée d’autorisation liée est cohérente avec l’entrée de l’opération et reste valable. Une assertion préparée avant une nouvelle autorisation ne peut pas être appliquée après celle-ci. Une clé dont la chaîne d’ajout dépend d’une clé `COMPROMISED` ne signe plus d’opérations futures tant qu’une réautorisation valide n’a pas été ancrée. C’est la valeur signée qui fait preuve, non l’ordre du journal ni une date SQLite (§5.3 ; §5.5.1, étape 5 ; §5.5.2, contrôle 7 ; §5.5.3) ;
    - **opérations signées qui ferment :** V0 compare l’identifiant d’autorisation de l’énoncé signé à l’entrée d’autorisation effective conservée dans le fichier de confiance protégé par `root`. Cette vérification ne relit pas J-c et n’exige pas une queue vide. **Précisé le 27 octobre 2026 :** l’opération n’est acceptée que si le credential signataire est autorisé et si sa chaîne d’autorisation n’a pas été invalidée ; le statut `ACTIVE` dans le fichier de confiance ne suffit pas à lui seul. Si V0 ne peut pas établir cette validité, l’opération signée est refusée. La voie d’urgence D-9 reste distincte et limitée à sa portée déjà décidée, sans extension aux autres opérations qui ferment (point 12). Acceptée, la fermeture prend effet au `COMMIT` local, sans relecture de J-c ni attente de l’ancrage ; un échec d’ancrage ultérieur ne la rouvre pas, et son entrée reste à ancrer selon la chaîne normale (§5.5.1, étape 5 ; §5.5.3 ; §7.0 ; §9.2 ; §11.2) ;
    - **portée temporelle de la réautorisation :** opération explicite, authentifiée, journalisée et ancrée. Elle ne prend effet qu’après l’ancrage requis, pour les opérations futures seulement, et ne rend pas rétroactivement utilisables les confirmations ni les opérations signées avant elle. Une assertion préparée ou signée avant elle ne peut pas être appliquée après pour contourner la règle. L’ordre des entrées J-b est établi par le journal ancré, jamais par une date SQLite (`prepared_at_ms` comprise) ; il date l’enregistrement, pas la création de l’assertion, et ne suffit donc pas seul à prouver qu’une assertion est postérieure. La clé reste inutilisable tant que la réautorisation n’est pas effective ; si aucun chemin sûr ne permet de réautoriser, le système reste fermé (§5.5.3, §11.2) ;
    - **restent ouverts :** la désignation fiable de l’entrée de retrait ; la procédure de récupération, de perte et de remplacement des clés, et la sortie d’un blocage ; les mécanismes qui appliquent la portée de `COMPROMISED` aux opérations 2 à 5, seule la confirmation d’inscription disposant déjà d’un chemin (E) ; la désignation fiable et le moment d’écriture de l’entrée de marquage (moment tranché le 27 octobre 2026 pour le marquage par `root`, point 23), et la distinction sûre des cas lorsque l’opération et le marquage attendent dans la même queue ; le mécanisme de la réautorisation d’une clé ajoutée (opération, désignation de son entrée, validation pré-ancrage), pour la liaison à l’autorisation effective de la clé signataire : le nom du champ, son encodage, la représentation de l’autorisation initiale de genèse, la désignation de la clé signataire dans l’énoncé, pour les opérations qui ferment, la représentation de l’entrée et de la chaîne d’autorisation dans la politique protégée par `root`, la preuve que l’entrée était déjà effective et que la chaîne n’a pas été invalidée, leur cohérence avec le journal (J-b et J-c) et la conduite en cas de divergence ou d’impossibilité d’écrire le journal (point 23), et le sort d’une assertion préparée avant qu’une autorisation écrite soit effective ; le format des opérations d’ajout et de réautorisation, et la trace de la clé qui a signé un ajout (§5.5.3, §5.7, §5.8, §7.1, §11.2, §11.3).
10. Deux credentials de B dans une même session ou non (§6.1).
11. Liste définitive des codes de rejet (§6.3).
12. Extension de la voie d’urgence au-delà de l’interrupteur (§7.0). **Décidé le 27 octobre 2026 :** le marquage `COMPROMISED` d’un credential d’administration n’est pas possible par cette voie (point 23). L’extension elle-même reste ouverte.
13. Conduite si la révocation du grant échoue (§8.1).
14. **T-3 — tranché et complété le 25 octobre 2026.**
    - **Décidé :** `root` possède et contrôle en écriture tout ce qui peut changer l’application ou son autorisation (CLI d’administration, stockage, V0/V1/E, chemin d’approbation et de consommation, dépendances d’exécution, configuration et lancement du service, fichier de confiance). `aidirector` lit et exécute, sans modifier ni remplacer. Les fichiers SQLite restent au compte de service. Toute mise à jour passe par une opération administrative `root` contrôlée. La compromission de `root` ou du serveur reste hors de la protection d’A-1, système fermé selon D-15. Aucune modification effective du serveur n’est autorisée (§3, §9.2).
    - **Restent ouverts (§9.2) :** méthode d’installation et de mise à jour ; inventaire exact des fichiers et dépendances, avec propriétaire, groupe, mode et répertoires parents ; contrôles d’intégrité ; journalisation ; disposition des répertoires (code et base séparés) ; vérification de la conformité du serveur et mise en conformité éventuelle, qui relèvent d’une étape autorisée séparément.
    - **Restent des recommandations :** la règle `sudo` (§9.2).
15. **T-2** : I-0 ou I-1 ; toute exception à l’interdiction de `socket`, `http` ou `ssl` (OAuth, ancre), avec ses contrôles d’architecture (§9.3).
16. Bornes des compteurs de refus (§10.3).
17. Ancre J-c : fournisseur, droits, calendrier avant la première activation, processus qui l’écrit et la relit (§11.4).
18. Relecture de l’ancre à chaque usage ou une fois par demande d’approbation (§11.2).
19. Énoncé signé non appliqué : refus d’ancrer après `expires_at_ms` ou horodatage par le fournisseur de l’ancre (avec leur contrepartie), priorité d’un rejet ancré, ou acceptation de la limite (§5.5.2).
20. Confirmer la répartition entre opérations qui ouvrent (effectives après ancrage) et opérations qui ferment (effectives dès le `COMMIT` local) (§11.2). **Décidé le 27 octobre 2026 :** le marquage `COMPROMISED`, transition spéciale de la politique d’autorisation, ne prend effet qu’à l’installation de la nouvelle politique `root`. La règle des autres fermetures est inchangée (point 23).
21. **Sort du nonce lors d’un refus à la précondition de V0 — règle consignée le 26 octobre 2026 sur instruction du propriétaire** (§5.5.1, étapes 1a et 1b ; §10.3) :
    - **refus dû uniquement à l’ancre ou à la queue** (ancre indisponible, absente ou divergente, ou queue en attente d’ancrage) : le nonce reste `ISSUED`. Une nouvelle tentative reste possible tant qu’il n’a pas expiré et qu’elle reprend le même énoncé signé ;
    - **refus d’une opération ordinaire qui ouvre** (opérations 1 à 4 du §11.2) **parce que la politique d’attestation est suspendue** : le nonce passe à `FAILED`, même si un motif lié à l’ancre s’y ajoute. **Formulation modifiée le 27 octobre 2026 [D]** (point 24) : cette mise à jour se faisait « dans une transaction séparée ». Elle reste distincte des écritures de l’opération grâce à un retour au `SAVEPOINT`, mais a désormais lieu dans la même transaction `BEGIN IMMEDIATE`, par une transition conditionnelle `ISSUED` → `FAILED`. L’opération n’est pas enregistrée. Après la reprise effective, il faudra un nouveau nonce et une nouvelle assertion ;
    - **inchangées :** les règles des autres refus de V0 (étapes 2 à 8 : `FAILED`) et des arrêts du processus avant ou après le `COMMIT` (§5.5.1). Les erreurs SQLite de la transaction de V0 sont précisées au point 24 et au §5.5.1, sans modification de ces règles ;
    - **complément du 27 octobre 2026 [D], sans modification des règles ci-dessus** (§5.5.1 ; §5.5.5, J.7). Seuls les échecs propres à la barrière γ1, survenus avant la vérification de l’assertion, laissent le nonce `ISSUED`. Le refus 1b pour politique d’attestation suspendue garde la règle ci-dessus (`FAILED`), et les autres étapes de V0 gardent leur sort de nonce déjà décidé :
      - échec de la barrière, politique `root` inaccessible ou échec de l’écriture de `c` : rollback complet, refus fermé, nonce `ISSUED`. Le même énoncé peut être retenté avant expiration ;
      - divergence d’intégrité détectée par la barrière : S4 maintenu jusqu’à la résolution, sans écriture de `FAILED`. Le nonce reste `ISSUED`, mais aucune opération signée n’est admise pendant S4. Après la résolution, V0 revérifie l’énoncé et le nonce ;
      - après l’obtention de la barrière, les règles ci-dessus s’appliquent ;
      - un échec de l’écriture de `FAILED` ne permet jamais un effet. L’effet est annulé au `SAVEPOINT` lorsque ce retour a réussi ; sinon, il ne l’est qu’une fois l’annulation établie (point 24) ;
    - **exigence de sécurité, non facultative :**
      - l’énoncé signé des opérations 1 à 4 contient toujours le champ `effective_resume_entry_hash` (décidé par le propriétaire le 26 octobre 2026) : l’`entry_hash` de la dernière reprise de suspension effective et ancrée au moment du `prepare`, en 64 caractères hexadécimaux minuscules, ou `null` explicite avant toute reprise effective. Aucune séquence n’est ajoutée : l’empreinte identifie l’entrée ;
      - ce champ figure dans la liste de l’énoncé canonique (§5.3). Il appartient aux octets canoniques signés, et le défi dérivé de l’énoncé le couvre donc aussi ;
      - V0 reconstruit cet identifiant à partir de la chaîne concordante avec l’ancre relue et le compare à la valeur signée ;
      - toute différence entraîne un refus, et le nonce passe à `FAILED` (§5.5.1, étape 4) ;
      - cette liaison garantit la règle même si le passage à `FAILED` d’un refus 1b a échoué. Une valeur SQLite seule ne la garantit pas. `prepared_at_ms`, bien que signé, ne la garantit pas non plus, puisque sa valeur est fixée par un processus du compte de service ;
      - la création d’une invitation, dont le protocole signé n’est pas encore défini (§6.2), devra suivre la même règle lorsque ce protocole sera conçu (§5.3).
    - **comparaison réservée à V0 — décidé par le propriétaire le 26 octobre 2026** (§5.3 ; §5.5.1, étape 4 ; §11.2) :
      - V0 compare le champ signé à la reprise effective courante au moment de l’`apply` ;
      - V1 et E vérifient ce champ uniquement comme partie de l’énoncé signé (octets canoniques, défi et signature) ; ils ne le comparent pas à la reprise effective courante ;
      - une reprise ultérieure ne rend donc pas inutilisables les confirmations déjà enregistrées ;
      - E continue d’appliquer le contrôle de la politique et de la suspension courantes (§11.2, étape 4).
22. **Cycle de vie de l’attestation AT-2** (§5.2.7).
    - **Décidé le 26 octobre 2026** (orientations de conception du propriétaire, §5.2.7, M) :
      - **M.1, ancres :** R-c lorsqu’une source indépendante du fabricant existe et concorde avec MDS ; sinon R-b, uniquement après approbation hors bande de l’ancre de signature MDS. Toute divergence entraîne un refus fermé ;
      - **M.2, métadonnées :** M-2, avec récupération hors serveur et import par l’opération `root` contrôlée. Aucun accès réseau n’est ajouté au serveur. L’architecture est une **adaptation** de MDS §3.2, dont la conformité stricte n’est pas établie ; le serveur applicatif ne télécharge pas lui-même le BLOB ;
      - **M.3, `x5u` :** tout BLOB dont l’en-tête contient `x5u` est refusé, sans repli sur `x5c` ni sur l’ancre seule, jusqu’à une décision et un traitement dédiés ;
      - **M.4, liste fermée :** couples AAGUID–ancre–format. Un modèle absent de la liste ou une correspondance AAGUID–certificat non démontrée est refusé. Les statuts MDS inconnus sont ignorés, comme l’exige MDS, et ne dispensent jamais de l’admission explicite ;
      - **M.5, genèse et import :** refus d’un `nextUpdate` dépassé, d’un `no` inférieur ou égal au dernier accepté, et de l’absence des informations de révocation requises (F.1, F.2). Pour les AC intermédiaires de l’attestation, des informations de statut vérifiées sont exigées. Un rapport MDS ne compte que s’il identifie effectivement les certificats concernés ;
      - **M.6, après la genèse :** les opérations qui ouvrent sont suspendues si `nextUpdate` est dépassé ou si un import échoue. Une révocation défavorable connue les ferme et déclenche une revue par le propriétaire. **Portée décidée le 29 octobre 2026 [D] :** seuls en relèvent, connus par un import, un statut de sécurité applicable, le statut `REVOKED`, une AC intermédiaire révoquée et une ancre retirée (§5.2.7, K.7) ; toute extension exige une décision distincte ; l’applicabilité d’un statut de sécurité selon `authenticatorVersion` reste ouverte [O], et son refus à la genèse reste [R]. Aucun changement automatique du statut des credentials. La reprise exige une décision administrative authentifiée et une politique valide, journalisée et ancrée ;
      - **M.6, complément sur la portée de la reprise :**
        - toute suspension exige une décision administrative authentifiée de reprise, qu’elle vienne de métadonnées périmées, d’un import en échec ou d’une révocation connue ;
        - la reprise est journalisée et ancrée ;
        - après une révocation connue, elle exige en outre une revue qui établit que la politique est de nouveau satisfaite ;
        - aucun credential ne change d’état automatiquement ;
        - si ces conditions ne peuvent pas être établies, le système reste suspendu ;
      - **M.6, complément sur l’application de la suspension :**
        - la politique d’attestation locale, protégée par `root`, est vérifiée à V0, avant toute opération administrative ordinaire qui ouvre (opérations 1 à 4 du §11.2), et à E, avant toute autorisation du chemin d’approbation (§11.2, étape 4) ;
        - les deux chemins refusent si la politique est périmée, si un import est en échec ou si une révocation défavorable est connue ;
        - la **reprise de suspension** (opération 5 du §11.2) est la seule opération qui ouvre admise pendant une suspension. Elle exige une décision administrative authentifiée, une politique redevenue valide et, après une révocation connue, une revue. Elle est journalisée et ancrée, et n’est effective qu’après l’ancrage requis ;
        - elle ne permet aucune autre opération qui ouvre : les opérations 1 à 4 restent bloquées jusqu’à ce qu’elle soit effective. Aucun statut de credential ne change automatiquement ;
        - **alignement de la validation pré-ancrage (§11.3) [R] :**
          - la reprise de suspension y passe par une branche dédiée (étape 3). Celle-ci vérifie l’assertion administrative selon la règle applicable (V1, §5.5.3), la politique redevenue valide, le dernier import réussi et, après une révocation connue, la revue ;
          - pour les opérations 1 à 4, l’étape 2 vérifie en outre qu’elles n’ont pas été enregistrées pendant une suspension ;
          - la branche de reprise n’est pas un contournement général ;
          - comme l’ensemble de la validation pré-ancrage, cet alignement reste une recommandation [R], cohérente avec M.6 et M.9 ;
      - **M.6, complément sur la légitimité de l’entrée et l’effet de la reprise :**
        - la branche pré-ancrage vérifie la légitimité de l’énoncé signé et de l’assertion au moment de l’opération ;
        - la reprise ne lève la suspension qu’après l’ancrage et la relecture requis, si la politique est encore valide à ce moment ;
        - si `nextUpdate` expire, si un import échoue ou si une révocation défavorable est connue entre l’opération et l’ancrage, l’entrée peut être ancrée pour l’audit mais reste sans effet. La suspension demeure, et une nouvelle reprise authentifiée est requise après rétablissement d’une politique valide ;
        - une simple péremption n’est pas une divergence S4 ; S4 est réservé aux échecs d’intégrité et aux divergences définis par le protocole ;
        - V0, pour les opérations 1 à 4, et E refusent tant que la reprise n’est pas effective. La formulation opérationnelle reste [R] (§5.2.7, M.6) ;
        - les opérations qui ferment restent permises pendant une suspension ;
      - **M.7 :** deux modèles d’AAGUID différents sont recommandés pour la clé principale et la clé de secours ;
      - **M.8 :** une validation X.509 éprouvée, à règles explicites, est recommandée, avec une horloge contrôlée par `root`. Refus fermé si les dates ou la révocation ne peuvent pas être vérifiées. `cryptography` 50.0.2 n’est pas présenté comme validé sans tests ultérieurs ;
      - **M.9 :** journalisation et ancrage du BLOB, de `no`, de `nextUpdate`, des informations de révocation, de la chaîne `x5c` de l’attestation et de l’empreinte du fichier de politique. Aucune opération qui ouvre ne devient effective avant l’ancrage requis.
    - **Restent ouverts**, parce qu’ils exigent un fabricant, un modèle, une licence, un canal, une durée ou un détail technique non établi :
      - **choix concrets :** fabricant, modèles et AAGUID ; ancres concrètes ; contenu de la liste fermée (M.4, M.7) ;
      - **ancres :** source indépendante utilisable pour R-c ; canal et procédure d’approbation hors bande de l’ancre de signature MDS ; canal de comparaison des empreintes (M.1, K.2) ;
      - **récupération :** poste et canal ; conditions d’utilisation du BLOB (H-6) ; cadence des imports, aucune durée n’étant fixée (M.2, K.1, K.3) ;
      - **`x5u` :** traitement dédié éventuel, qui exigerait une décision distincte (M.3) ;
      - **correspondance AAGUID–certificat :** moyen de la démontrer lorsque l’extension AAGUID est absente (preuve d’une ancre dédiée au modèle) ; acceptation d’une ancre égale au certificat d’attestation et son traitement par comparaison binaire (§5.2.7, D.5, G) ;
      - **statuts bloquants à la genèse** (`REVOKED`, statuts de sécurité, portée de `authenticatorVersion`, effet d’un `UPDATE_AVAILABLE` postérieur). Ils restent [R] en G ;
      - **informations de statut des AC intermédiaires :** forme admise (CRL, réponse OCSP obtenue à l’avance ou autre) ; critère d’identification effective d’un certificat par un rapport MDS ; modalités de vérification (F) ;
      - **validation X.509 :** outil, règles et tests ; source et contrôle de l’horloge `root` (M.8, H-4, H-7) ;
      - **reprise de suspension :** nom et format exact de l’opération (opération 5 du §11.2) et de son énoncé, y compris la façon d’y lier la politique, l’import et la revue (§11.3, étape 3), et d’établir les instants qui décident de son effet (§5.2.7, M.6). Sa portée et son point d’application sont décidés, et sa validation pré-ancrage est alignée (§11.3) ;
      - **fréquence de relecture de l’ancre :** non tranchée par M.6, elle reste ouverte (point 18, §11.2) ;
      - **création d’une invitation :** protocole signé non décrit (§6.2). Le contrôle de M.6 la précède en tout cas (§11.2) ;
      - **ancrage :** moment de l’ancrage d’une genèse faite système fermé ; fournisseur de l’ancre (§11.4, point 17) ;
      - **changement de statut des clés** après une révocation : il exige une décision distincte (§5.5.3, §5.7, §5.8).
23. **Représentation et preuve de la chaîne d’autorisation des credentials d’administration** (§5.5.5). La règle du 27 octobre 2026 est décidée (point 9).
    - **Décisions de portée du 27 octobre 2026 [D]** (§5.5.5, J). Elles précisent la recommandation I et la barrière γ1 sans modifier les décisions antérieures sur `RETIRED`, `COMPROMISED`, les nonces ou la portée de D-9 :
      1. **`COMMIT` local :** les fermetures ordinaires sont effectives au `COMMIT` local dans le service intact. Le marquage `COMPROMISED`, transition spéciale de la politique d’autorisation, ne prend effet qu’à l’installation de la nouvelle politique `root`. Cette exception ne change pas la règle des autres fermetures (§5.5.5, J.1) ;
      2. **source faisant autorité :** l’inscription dans la politique `root`. Un marqueur SQLite peut seulement faire refuser. **Limite acceptée et visible :** un marqueur présent seulement en base peut être effacé par un compte de service compromis (§5.5.5, J.2) ;
      3. **authentification :**
         - opération `root` contrôlée ;
         - assertion WebAuthn fraîche avec UV, signée par un autre credential d’administration valide dans la politique courante et indépendant du credential visé ;
         - SSH ou `sudo` seuls ne suffisent pas ;
         - sans autre credential valide, aucun marquage par cette voie, et la récupération relève du §5.8 ;
         - D-9 n’est pas étendue (§5.5.5, J.3) ;
      4. **journalisation et reprise :**
         - l’événement est conservé durablement dans la zone `root` avant la mise à jour ;
         - la politique mise à jour rend l’invalidation effective ;
         - le service l’inscrit dans J-b sous son propre compte, de façon idempotente, puis il est ancré ;
         - une panne après la mise à jour ne lève pas l’invalidation ;
         - `root` n’écrit jamais dans SQLite ;
         - l’événement est conservé au moins jusqu’à l’ancrage de son entrée J-b (§5.5.5, J.4) ;
      5. **ordre et barrière γ1 :**
         - `root` prend une barrière exclusive qui attend la fin des transactions du service ;
         - le service tient la barrière de la lecture de la politique jusqu’au `COMMIT` ;
         - la première transaction visée consigne `c` dans la même transaction SQLite, avant toute autre entrée signée et toute validation ou tout ancrage. Réserve : cette règle ne vaut pas pour une génération visible mais non déclarée effective, pour laquelle le service reste fermé, sans opération signée, consignation de `c` ni ancrage avant sa déclaration d’effectivité (décision 13) ;
         - tout échec est fermé ;
         - la coordination n’est pas atomique avec SQLite (§5.5.5, J.5) ;
      6. **limite :** l’ordre n’est garanti que si les processus respectent le protocole. Face à un compte de service compromis, ni la chronologie ni le classement S4 ne sont garantis avant l’ancrage. Le refus en V1 des opérations signées par une clé `COMPROMISED`, quelle que soit leur date, est préservé (§5.5.5, J.6) ;
      7. **refus γ1 et nonce :** seuls les échecs propres à la barrière γ1, survenus avant la vérification de l’assertion, laissent le nonce `ISSUED`. Le refus 1b garde sa règle `FAILED`, et les autres étapes de V0 gardent leur sort de nonce déjà décidé (§5.5.5, J.7) :
         - échec de la barrière, politique `root` inaccessible ou échec de l’écriture de `c` : rollback complet, refus fermé, nonce `ISSUED`, nouvelle tentative possible avec le même énoncé avant expiration, comptage borné ;
         - divergence d’intégrité détectée par la barrière : refus fermé et S4 maintenu jusqu’à la résolution, sans écriture séparée de `FAILED`. Le nonce reste `ISSUED`, mais aucune opération signée n’est admise pendant S4. Après la résolution, V0 revérifie l’énoncé et le nonce ;
         - barrière obtenue, puis échec de l’assertion ou d’une étape normale de V0 : règles existantes du §5.5.1. Étape 1a : rollback complet. Étape 1b et étapes 2 à 8 : retour au `SAVEPOINT`, puis `FAILED` dans la même transaction (point 24) ;
         - un échec de l’écriture de `FAILED` ne permet jamais un effet.
    - **Décisions du 27 octobre 2026 sur la barrière [D]** (§5.5.5, L.5 et L.8) :
      8. **barrière bloquée, option (d) :**
         - en temps normal, `root` attend la barrière exclusive ;
         - après un délai borné, `root` arrête tous les processus du service et empêche leur redémarrage pendant l’installation ;
         - la nouvelle génération n’est déclarée effective qu’après l’obtention de la barrière exclusive et l’installation durable ;
         - si l’arrêt ou l’obtention de la barrière échoue, rien n’est installé et le système reste fermé ;
         - l’arrêt forcé n’est pas une atomicité entre SQLite et la politique ;
      9. **couverture d’E :**
         - la barrière couvre le contrôle de politique d’E jusqu’à l’enregistrement local de la décision ;
         - la lecture réseau de J-c reste hors barrière ;
         - sous la barrière, E revérifie la génération et refuse si l’ancre relue ne la couvre pas ou si elle a changé. Ce refus est fermé, sans décision enregistrée, et une nouvelle tentative repart de la relecture de l’ancre ;
         - **précisé :** l’entrée `c` qui consigne la génération courante est incluse dans la tête J-c qu’E vient de relire. La règle vaut pour la génération initiale : aucune autorisation E avant que son entrée soit consignée et ancrée ;
      10. **D-9 :** hors barrière, et limitée à l’interrupteur.
          - **Précisé :** D-9 peut être temporairement indisponible tant que le service est arrêté par la procédure `root`.
          - Le service arrêté est en échec fermé, et aucune voie n’autorise pendant cet arrêt.
          - Après le redémarrage, D-9 est de nouveau disponible dans sa portée, même si `c` attend encore l’ancrage ;
      11. **portée inchangée :** ces précisions ne changent ni la portée de D-9, ni les conditions d’effectivité des opérations qui ouvrent ;
      12. **ordre de prise des verrous** (§5.5.5, L.2 à L.4) :
          - **service :** prendre G en partagé, puis B en partagé, relâcher G, puis exécuter `BEGIN IMMEDIATE`. Lire la politique après l’obtention de B. Garder B jusqu’au `COMMIT` ou au rollback, puis la relâcher ;
          - **E :** le même ordre ;
          - **`root` :** préparer et vérifier l’événement hors barrière, puis prendre G en exclusif et B en exclusif. Vérifier de nouveau la génération, installer durablement la politique, puis relâcher les verrous ;
          - entre processus qui respectent le protocole, cet ordre évite les cycles d’attente entre SQLite, G et B, et empêche qu’une transaction commencée sous l’ancienne génération valide après le remplacement ;
          - aucune garantie n’est donnée contre un compte de service compromis qui contourne les verrous ;
          - le dépassement du délai suit la procédure décidée en 8.
    - **Décisions du 29 octobre 2026 [D]** (§5.5.5, I.4, J.4, L.3, L.5, L.7 et L.8, point 8) :
      13. **génération visible mais non déclarée effective :**
          - après un arrêt brutal de `root`, ou une coupure d’alimentation au même stade (extension décidée le même jour [D]), survenu entre le renommage et la synchronisation durable du répertoire, lorsque g+1 est visible sans avoir été déclarée effective, le service n’utilise pas g+1 tant qu’elle n’est pas déclarée effective ;
          - il reste fermé : aucune opération signée, aucun ancrage et aucune consignation de `c` pour cette génération avant sa déclaration d’effectivité ;
          - `root` doit achever ou résoudre l’installation avant la reprise du service ;
          - cette exception s’applique aux formulations de I.4 et J.4 sur l’effet de la mise à jour de la politique.
      14. **échec de la synchronisation du répertoire, `root` restant actif :**
          - après le renommage de P′ en P, `root` garde B et G pendant une période bornée pour achever ou résoudre l’installation ;
          - s’il n’y parvient pas, il arrête le service, maintient l’interdiction de redémarrage et libère les verrous après l’arrêt complet ; le service reste arrêté jusqu’à l’achèvement ou la résolution ;
          - g+1 n’est déclarée effective que lorsque les conditions décidées sont remplies ; d’ici là, la décision 13 s’applique.
    - **Décision du 1er novembre 2026 [D], sous condition** (§5.5.5, L.2, L.3, L.7 et L.8, point 8) :
      15. **principe O1-B pour la déclaration d’effectivité :**
          - après R6 et avant R7, tout en tenant B, `root` écrit une déclaration D qui désigne g+1 et l’empreinte de P, puis établit sa durabilité ;
          - toujours sous B et avant R7, `root` écrit une confirmation, uniquement après avoir établi cette durabilité ;
          - le service et E n’utilisent g+1, n’acceptent aucune opération signée pour cette génération, ne consignent pas `c` et n’ancrent pas tant qu’ils n’ont pas lu sous B une déclaration confirmée qui concorde avec P (contrôle de l’état courant de D à chaque opération concernée : §5.5.5, L.8, point 8, « Portée ») ;
          - si D est absente, non confirmée, illisible ou discordante, le système reste fermé pour cette génération ;
          - **condition :** la représentation retenue doit garantir que la perte de la confirmation ne peut pas altérer la déclaration déjà durable. Cette garantie n’est pas encore démontrée [H]. Si elle ne peut pas être garantie, aucune mise en œuvre d’O1-B ne doit en être déduite ;
          - seul ce principe abstrait est décidé, et aucun mécanisme concret n’est choisi. Les décisions 13 et 14, L.5 et M.6 sont inchangées.
    - **Décision du 1er novembre 2026 [D]** (§5.5.5, I.4, J.5, L.6, L.7 et L.8, point 7 ; §11.3) :
      16. **option 2 pour l’ancrage externe :**
          - la règle d’ancrage vise la génération et l’état de D contrôlés sous B lors de la validation de la queue ;
          - l’ajout externe à J-c, qui suit le `COMMIT` et a lieu hors barrière selon le protocole actuel, publie la queue déjà validée ; il n’est pas une nouvelle validation sous la génération qui pourrait être installée après le `COMMIT` ;
          - une queue validée sous g demeure classée sous g, même si son ajout à J-c survient après l’installation de g+1 ;
          - cet ajout peut donc précéder `c` de g+1 ; les entrées de g restent antérieures à `c` dans l’ordre du journal ;
          - cette publication de la queue validée sous g ne constitue ni l’utilisation de g+1, ni un ancrage d’opération de g+1 ;
          - avant toute validation ultérieure sous g+1, le service vérifie sous B que D est actuellement confirmée et concorde avec P ; `c` de g+1 est consignée avant toute validation ou tout ancrage ultérieur sous g+1 ;
          - l’option 1, tenir B pendant l’ajout, n’est pas retenue. La barrière, O1-B, dont la condition reste [H], et M.6 sont inchangés.
    - **Décision du 2 novembre 2026 [D]** (§5.5.5, L.8, point 8) :
      17. **critère d’évaluation de la condition d’O1-B :**
          - la condition est évaluée selon une garantie conditionnelle, fondée sur des hypothèses explicites et vérifiées pour l’environnement cible, avec fermeture en cas d’anomalie ;
          - cette décision ne constate pas que la condition est satisfaite, ne choisit aucune représentation de D et n’autorise ni relevé de l’environnement, ni essai, ni mise en œuvre ;
          - la condition reste [H] jusqu’à une décision distincte constatant que les preuves requises sont suffisantes ;
          - la liste des hypothèses et des preuves requises reste à fixer [O] ; le principe de la décision 15, les décisions 13, 14 et 16, L.5 et M.6 sont inchangés.
    - **Décision du 2 novembre 2026 [D]** (§5.5.5, L.8, point 8) :
      18. **limites de confiance envers l’hébergeur :**
          - seules les hypothèses intrinsèquement invérifiables depuis le système invité et relevant de l’hébergeur peuvent être acceptées comme limites de confiance explicites ; elles ne sont jamais présentées comme vérifiées ;
          - cette acceptation exige que le type de volume et les engagements applicables de l’hébergeur soient identifiés et examinés, puis que le propriétaire accepte explicitement chaque hypothèse concernée ;
          - si ces éléments sont absents ou ambigus, l’hypothèse reste non établie, et O1-B demeure [H] et bloquée.
    - **Articulation [D].** Cette décision complète la décision 17 : toute autre hypothèse reste à vérifier pour l’environnement cible, et le texte de la décision 17 est inchangé. Elle ne constate pas que la condition est satisfaite, ne désigne aucune hypothèse, ne choisit aucune représentation de D et n’autorise ni relevé, ni contact avec l’hébergeur, ni essai, ni prototype, ni accès au serveur, ni mise en œuvre.
    - **Restent ouverts [O] :**
      - la mise en œuvre de la barrière (§5.5.5, L.8) : valeur du délai borné ; mécanismes d’arrêt, d’interdiction de redémarrage, de persistance de cette interdiction et de relance ; garantie de fermeture si l’arrêt échoue ; détails techniques de la consignation et de l’ancrage de la genèse ; détails de l’arrêt et du redémarrage du service ; mécanisme concret qui établit la durabilité de l’installation ou déclare une génération effective, et conduite de `root` pour achever ou résoudre une installation interrompue (décision 13 ; principe O1-B adopté sous condition, décision 15, dont la condition reste [H]) ; pour D : format et stockage, permissions et inscription à l’inventaire T-3, méthode d’écriture, conduite de `root` en cas d’échec, états de refus et sort du nonce, écriture initiale à la genèse, reprise par `root` et disponibilité de D-9 (§5.5.5, L.8, point 8) ; pour l’échec de synchronisation (décision 14), valeur du délai borné, modalités et nombre des tentatives (méthode d’achèvement après un échec de `fsync` à vérifier [H]), conditions précises de reprise et mécanismes d’intervention si l’installation ne peut pas être résolue ; mécanisme concret des verrous, fichiers et permissions, délais, garantie d’équité envers `root`, libération après un arrêt brutal, et vérification qu’aucun processus ne demande G ni B en tenant une transaction SQLite ouverte ;
      - la zone d’événements `root` (format, droits, synchronisation), la conservation des éléments bruts après l’ancrage, et le sort d’un événement conservé sans génération ;
      - l’énoncé canonique de marquage, la production du défi et le transfert de l’assertion ;
      - la couverture par γ1 des autres entrées J-b (E, voie d’urgence, signaux) ;
      - la lecture fiable de l’état SQLite par `root` ;
      - les repères qui réduiraient la limite face à un compte compromis : ancre relue par `root`, repère signé de postériorité (§5.5.5, K.5) ;
      - les bornes du comptage (point 16), et les modalités techniques de résolution d’un incident d’intégrité γ1 et de sortie de S4 ;
      - le chemin du retrait `RETIRED`, dont dépend l’analyse du §5.5.5, K.2 (§5.7) ;
      - la forme du manifeste d’autorisation (§5.5.5, C), la relecture de l’ancre par `root` (point 17), la cohérence du manifeste avec J-b et J-c, et la consignation de la genèse ;
      - la liste des hypothèses et des preuves requises pour la condition d’O1-B et le critère de constat (décisions 17 et 18) ; une proposition [R], non adoptée, figure au §5.5.5, L.9 ;
      - pour l’ancrage externe (décision 16 ; §5.5.5, L.6 ; §11.3) : le processus qui effectue l’ajout à J-c ; ses tentatives et ses issues inconnues ; le traitement d’une queue en attente après un redémarrage, y compris le sort d’une queue dont la validation précédente a eu lieu sous g si la validation est rejouée après l’installation de g+1 ; le sort d’un ajout en attente si g devient fermée selon O1-B, pendant S4 ou pendant le gel.
    - **Protocole de la barrière : analyse (§5.5.5, L), tranchée en partie.**
      - L’analyse décrit les séquences du service, d’E et de `root`, l’ordre de prise, désormais décidé (décision 12), la porte G, et une matrice des interruptions.
      - **La contradiction relevée en L.5 est tranchée par l’option (d)** (décisions 8 à 10 ci-dessus). La limite face à un compte de service compromis qui contourne le protocole demeure (J.6).
      - **Restent à décider (L.8) :** les détails de l’ancrage externe (L.6 ; option 2 décidée, décision 16), le mécanisme concret qui établit la durabilité d’une génération et la conduite de `root` pour achever ou résoudre son installation (la conduite du service étant décidée, décision 13, et le principe O1-B adopté sous condition, décision 15), le retour arrière de la politique, et les autres points [O] de L.8.
    - **Analyse sans décision (§5.5.5, K) :**
      - les ordres α, β et γ sont comparés, et une affirmation de F et de I.4 est corrigée ;
      - il n’existe aucune atomicité entre la politique `root` et SQLite ;
      - une valeur signée prouve une postériorité, jamais une antériorité.

24. **Course sur le nonce entre un échec de V0 et l’écriture de `FAILED` — décidé le 27 octobre 2026 [D] : option (a)** (§5.5.1 ; §10.3 ; §5.5.5, L.2, L.4, L.7 et L.8).
    - **Protocole :**
      - `BEGIN IMMEDIATE`, puis `SAVEPOINT` avant les écritures de l’opération ;
      - si V0 doit refuser et faire échouer le nonce (1b ou étapes 2 à 8) : retour au `SAVEPOINT`. Il annule les écritures de l’opération, `c` comprise, en conservant la transaction et son verrou d’écriture ;
      - dans la même transaction, transition conditionnelle `ISSUED` → `FAILED`, seulement si le nonce est encore `ISSUED`, sans jamais remplacer un état terminal tel que `CONSUMED` ;
      - `COMMIT` de la transaction externe, puis libération de B, puis de W [D, 28 octobre 2026]. B n’est jamais relâchée après le seul retour au `SAVEPOINT`.
    - **Effet :** un second `apply` ne peut pas observer le nonce encore `ISSUED` entre l’annulation des effets et le passage à `FAILED`.
    - **Inchangé :** les refus 1a et les refus propres à γ1 (rollback complet, nonce `ISSUED`, J.7), les classifications des erreurs d’assertion ou de V0 après la barrière, S4 et D-9.
    - **Formulations modifiées, et signalées :** le point 21 (refus 1b), le §5.5.1, le §10.3 et J.7 prévoyaient une « transaction distincte » ou « séparée » pour `FAILED`. La mise à jour reste distincte des écritures de l’opération grâce au `SAVEPOINT`, mais a lieu dans la même transaction `BEGIN IMMEDIATE`.
    - **Erreurs SQLite — formulation précisée le 27 octobre 2026 sur instruction du propriétaire** (§5.5.1, « Erreurs SQLite dans la transaction de V0 »). La formulation antérieure, « la transaction externe est annulée en entier, et aucun effet de l’opération ne subsiste », est remplacée :
      - **retour au `SAVEPOINT` réussi, puis échec de la transition ou du `COMMIT` :** l’effet de l’opération, `c` comprise, est annulé. Après un échec de la transition, aucun `COMMIT` n’est exécuté et la transaction est annulée en entier. Après un échec du `COMMIT`, le sort du nonce est incertain, `FAILED` ou `ISSUED`. Après un `ROLLBACK` explicite réussi, `ISSUED` est déduit, sans que sa durabilité soit établie. B suit la règle de résolution énoncée ci-dessous ;
      - **échec du retour au `SAVEPOINT` ou de l’annulation complète :** aucun `COMMIT` ne suit [D]. Le refus est fermé, et l’absence d’effet n’est affirmée qu’une fois l’annulation établie, ou déduite sous les conditions du §5.5.1 ; `in_transaction` faux ne suffit pas à lui seul. Sinon, le processus se termine sans relâcher B avant sa fin, et l’état est constaté avant toute nouvelle tentative [R] ;
      - **erreur du `COMMIT` du chemin de succès [D] :** ce n’est pas un refus, et aucune nouvelle tentative automatique n’est lancée. L’opération n’est tenue pour effective que si son `COMMIT` est établi. L’état est constaté avant toute nouvelle tentative [R]. B n’est relâchée qu’une fois la transaction résolue sur la connexion : par un `ROLLBACK` explicite réussi, ou lorsque la transaction n’est plus active et que l’issue reste indéterminée [O]. Si la transaction reste active et que le `ROLLBACK` échoue, le processus se termine [R]. Ni `show` ni une relecture n’établit à lui seul la durabilité [O] ;
      - **`SQLITE_BUSY` :** après un `BEGIN IMMEDIATE` réussi, la documentation exclut `SQLITE_BUSY` jusqu’au `COMMIT`. Il est distingué des erreurs d’E/S, de mémoire ou de disque plein, qui peuvent annuler la seule instruction ou toute la transaction ;
      - **inchangé :** l’option (a), sans réécriture de `FAILED` dans une transaction séparée.
    - **Gel après une issue indéterminée — décidé par le propriétaire le 27 octobre 2026 [D]** (§5.5.1, cas 3 ; §10.3 ; §11.2 ; §11.3 ; §5.5.5, L.7 et L.8) :
      - après une erreur de `COMMIT` dont l’issue est indéterminée, le service refuse les opérations d’approbation jusqu’à une récupération et une vérification explicites ;
      - pendant l’incertitude, aucune nouvelle autorisation d’approbation n’est délivrée, et aucune opération qui ouvre n’est acceptée (opérations 1 à 5 du §11.2) ;
      - la lecture seule à des fins de constat reste possible ;
      - issues visées : points b et c de la résolution (§5.5.1, cas 3), au cas 3 comme pour l’échec du `COMMIT` final du cas 1 ;
      - **transactions couvertes — décidé par le propriétaire le 27 octobre 2026 [D]** (§5.5.1, cas 3, « Transactions couvertes ») : toute transaction V0, qu’elle consigne une opération qui ouvre ou une opération signée qui ferme, et la transaction d’E qui enregistre une autorisation (extension ci-dessous). Seule une issue indéterminée du `COMMIT` déclenche le gel ; un non-`COMMIT` établi par un `ROLLBACK` réussi ne le déclenche pas, sauf si une règle déjà décidée l’exige. Cette décision fixe les catégories couvertes, pas le mécanisme qui arme ou conserve le gel [O] ;
      - inchangés : l’option (a), les règles de nonce, γ1, S4, la barrière B et la portée de D-9. D-9 écrit dans la même base et n’est pas une solution garantie à sa panne [R] ;
      - l’incertitude ne peut pas être enregistrée de façon fiable dans une base SQLite en erreur. Le 28 octobre 2026, le propriétaire a retenu un marqueur hors de SQLite (ci-dessous) ; le rôle de `root` se limite au retrait d’un marqueur résiduel ;
      - au point a, le `ROLLBACK` réussi établit le non-`COMMIT` : le gel n’est pas déclenché, sauf si une règle déjà décidée l’exige, et les règles du nonce restent inchangées ;
      - **extension au `COMMIT` d’E — décidée par le propriétaire le 27 octobre 2026 [D]** (§5.5.1, cas 3, « Extension au `COMMIT` d’E » ; §5.5.5, L.2, E6) : si le `COMMIT` par lequel E enregistre une autorisation a une issue indéterminée, E ne délivre aucune nouvelle autorisation, et le même gel s’applique jusqu’à une récupération et une vérification explicites. Un échec dont le non-`COMMIT` est établi par un `ROLLBACK` réussi ne le déclenche pas, sauf si une règle déjà décidée l’exige. Les règles déjà décidées du gel sont conservées. Le gel pour E est porté par le marqueur propre à sa transaction, fixé le 28 octobre 2026 (ci-dessous) ; un mécanisme armé par V0 seul ne l’aurait pas couvert [R] ;
      - **gel conservateur — décidé par le propriétaire le 27 octobre 2026 [D]** (§5.5.1, cas 3, « Gel conservateur ») : tout marqueur encore présent après l’arrêt d’un processus ou une issue non résolue maintient le gel, y compris après un redémarrage. Cela vaut pour un arrêt avant le `COMMIT`, pendant le `COMMIT`, ou après un `COMMIT` réussi mais avant le retrait du marqueur. Aucun nettoyage automatique ne retire un marqueur : ni au démarrage, ni après un délai, ni d’après la seule visibilité de l’état SQLite, ni d’après une simple déduction sur l’issue. Le gel ne prend fin qu’après une récupération, une vérification et une levée explicites. Un `ROLLBACK` complet réussi et établi, suivi du retrait normal du marqueur, ne le déclenche pas ; un arrêt avant ce retrait laisse le gel conservateur. Le mécanisme du marqueur a été fixé le 28 octobre 2026 (puce suivante) ;
      - **mécanisme du marqueur — décidé par le propriétaire le 28 octobre 2026 [D]** (§5.5.1, cas 3, « Mécanisme du marqueur ») : le gel utilise un marqueur distinct par transaction couverte, sous forme de fichier persistant hors de SQLite. Le marqueur est créé avant les écritures de la transaction ; le service ne le retire qu’après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi. Un `ROLLBACK TO SAVEPOINT` seul ne permet jamais de le retirer. Un marqueur restant après un arrêt ou une issue indéterminée maintient le gel, sans nettoyage automatique au démarrage. `root` ne retire un marqueur résiduel qu’après une récupération et une vérification explicites. La limite déjà établie s’applique : ce mécanisme protège contre les erreurs de processus et de stockage, pas contre un compte de service compromis. Rien n’établit que le système de fichiers empêche un processus du compte de service de supprimer le marqueur d’un autre processus. Le gel conservateur et les décisions antérieures sur V0, E, les nonces, γ1, S4, B et L.5 sont inchangés ;
      - **verrou W et ordre de prise — décidés par le propriétaire le 28 octobre 2026 [D]** (§5.5.5, L.2 ; §5.5.1, cas 3, « Mécanisme du marqueur ») : W est un verrou exclusif qui sérialise les transactions couvertes, V0 et E, et que celles-ci prennent avant G. Sous W, elles examinent les marqueurs existants ; pour E et les opérations qui ouvrent, un marqueur résiduel entraîne un refus sans écriture, dont la qualification et le sort du nonce restent ouverts. Ensuite, l’ordre existant reste intact : G en partagé, B en partagé, relâchement de G, puis `BEGIN IMMEDIATE`. V0 prend le `SAVEPOINT`, puis crée son marqueur avant toute écriture, donc avant les étapes S4 et S5 de L.2 et toute consignation de `c` ; E crée le sien après `BEGIN IMMEDIATE`, avant E3 à E6. W est gardé jusqu’à la résolution de la transaction sur la connexion. Après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi, le service peut tenter de retirer son marqueur avant de relâcher les verrous, jamais après le seul retour au `SAVEPOINT`. Une fois la transaction résolue, B puis W sont relâchés ; si le retrait échoue et que le marqueur reste présent, ou s’il n’est pas tenté, le marqueur résiduel maintient le gel. Une suppression visible dont seule la synchronisation du répertoire échoue ou reste incertaine ne maintient pas, à elle seule, le gel pendant que le système tourne (les autres marqueurs résiduels, s’il y en a, continuent de le maintenir et de provoquer les refus prévus) ; le marqueur peut réapparaître après une coupure ou un redémarrage. Si l’issue est indéterminée, le service ne tente pas le retrait ; le marqueur reste en place et maintient le gel jusqu’à une levée explicite par `root`. La libération de W à la fin du processus est une hypothèse à vérifier [H]. W ne protège pas contre un compte de service compromis ;
      - **rôle de W et fin de la transaction — décidés par le propriétaire le 28 octobre 2026 [D]** (§5.5.1, cas 1 à 3 et « Mécanisme du marqueur » ; §5.5.5, L.2) : W est un verrou de sérialisation, pas le support persistant du gel ; le marqueur restant porte le gel. Après que la transaction SQLite est résolue sur la connexion, le service relâche B puis W, même si le marqueur n’a pas pu être retiré. Si le `COMMIT` est confirmé ou si un `ROLLBACK` complet réussit, il peut tenter de retirer son propre marqueur ; si ce retrait échoue, il ne prétend pas que le gel est levé et ne retire aucun autre marqueur, et tout marqueur résiduel maintient le gel, sans nettoyage automatique. Si l’issue du `COMMIT` est indéterminée, il ne tente pas le retrait ; une fois la transaction inactive sur la connexion, il relâche B puis W et laisse le marqueur en place jusqu’à la récupération et à la levée explicites par `root`. Si la transaction reste non résolue, la conduite fail-stop est conservée : le processus se termine sans autre instruction, et la libération de B et de W à sa fin reste une hypothèse [H]. Ce fail-stop ne produit aucun code de réponse ni message du protocole, seulement le statut de sortie dédié `EXIT_FAIL_STOP` (puce « signalement des fail-stop », ci-dessous). Restent inchangés : un `ROLLBACK TO SAVEPOINT` seul n’autorise pas le retrait ; seul `root` retire un marqueur résiduel, après récupération et vérification explicites ; E et les opérations qui ouvrent refusent sous W en présence d’un marqueur résiduel ;
      - **support de W, emplacement des marqueurs et restauration — décidés par le propriétaire le 28 octobre 2026 [D]** (§5.5.1, cas 3, « Mécanisme du marqueur ») : W est un fichier stable détenu par `root`, jamais supprimé ni remplacé, que le service peut ouvrir et prendre en verrou exclusif sans pouvoir le modifier ; cela reprend le rôle exclusif de W. Les marqueurs sont placés dans un sous-répertoire persistant du compte de service, dans l’arborescence des données, hors des arborescences `root` et du code ; un système de fichiers local est une exigence de conception, et le système réellement utilisé sur le serveur reste à vérifier [H]. Une restauration n’est jamais, à elle seule, une levée explicite du gel ; la façon d’appliquer cette règle reste ouverte [O]. La portée de W, limitée à V0 et E, et L.4 sont inchangés. La prise de W ne garantit pas la cohérence d’une sauvegarde : d’autres écrivains, dont D-9 et la validation avant ancrage, écrivent dans la base sans W ;
      - **retrait visible non durable et échec de synchronisation à la création — décidés par le propriétaire le 28 octobre 2026 [D]** (§5.5.1, cas 3, « Mécanisme du marqueur ») : après un `COMMIT` confirmé ou un `ROLLBACK` complet réussi, si la suppression du marqueur est visible mais que la synchronisation du répertoire échoue ou a une issue incertaine, l’issue SQLite reste établie. L’absence visible du marqueur fait que le contrôle sous W peut laisser poursuivre les transactions couvertes pendant que le système reste en marche, sauf si d’autres marqueurs résiduels sont présents : ceux-ci continuent de maintenir le gel et de provoquer les refus prévus, cette suppression ne le maintenant pas à elle seule. Le service signale que la durabilité du retrait n’est pas établie et ne présente pas ce constat comme une levée explicite par `root`. Après une coupure ou un redémarrage, le marqueur peut réapparaître et provoquer un gel conservateur. Ce cas ne crée pas, à lui seul, un nouveau déclencheur de gel pendant que le système tourne. Si la synchronisation du marqueur ou de son répertoire échoue avant toute écriture SQLite, la transaction n’exécute aucune écriture de base ; elle suit la conduite de refus prévue et ne supprime aucun marqueur d’une autre transaction. Son propre marqueur relève de la règle de retrait déjà décidée : après un `ROLLBACK` complet réussi, le service peut tenter de le retirer. **Précisé le 28 octobre 2026 [D] :** la transaction se termine alors par un `ROLLBACK` complet avant de poursuivre. Si ce `ROLLBACK` échoue ou si son issue ne peut pas être établie, aucun `COMMIT` ne suit et le service applique la règle fail-stop propre à ce cas, plus stricte que la règle générale du §5.5.1, cas 2, point 2 : tout échec de ce `ROLLBACK`, même si `in_transaction` est faux et que l’annulation pourrait être déduite selon cette règle générale, met fin au processus sans autre instruction, comme au cas 2, point 3. Le marqueur est laissé en place s’il est présent, et la règle générale du point 2 reste applicable aux autres erreurs. **Refus et nonce — décidés le même jour [D]** (§5.5.1, cas 3, « Mécanisme du marqueur ») : pour V0 comme pour E, ce refus est un échec technique fermé, sans effet ni écriture SQLite ; pour V0, le nonce n’est ni consommé, ni passé à `FAILED`, ni renouvelé, et reste `ISSUED` jusqu’à son expiration normale s’il l’est encore ; le refus n’incrémente ni le compteur des tentatives d’autorisation, ni le compteur borné par opération et par classe de refus du §10.3 (précisé le même jour), les autres catégories de refus et leurs compteurs restant inchangés ; une télémétrie diagnostique éventuelle reste facultative, hors du protocole d’autorisation, et ne doit retarder ni le `ROLLBACK` ni le fail-stop ; aucune nouvelle tentative automatique n’est lancée, et une nouvelle présentation, après récupération du stockage, repasse les contrôles normaux et n’est possible avec le même énoncé signé que si le nonce est encore valide ; cet échec, à lui seul, ne crée pas de nouveau déclencheur de gel général ; le refus porte un code technique de réponse défini par ses garanties, commun à V0 et E, distinct des codes signés du §6.3, ni signé ni écrit en base ni inscrit dans J-b, émis seulement après le `ROLLBACK` complet réussi avec un qualificatif à trois valeurs sur le sort du marqueur de cette transaction (retrait visible sans durabilité établie, marqueur confirmé présent, état non établi ; aucune valeur « retrait durable » ni « gel levé »), et jamais en cas de fail-stop, qui ne produit que le statut de sortie dédié `EXIT_FAIL_STOP` (§10.2). La règle d’un `COMMIT` d’issue indéterminée et la levée explicite des marqueurs résiduels par `root` sont inchangées ;
      - **signalement des fail-stop — décidé par le propriétaire le 28 octobre 2026 [D] (option F2)** (§5.5.1, « Signalement du fail-stop ») : sur tout chemin qui se termine en fail-stop (cas 2, point 3 ; cas 3, point b ; fail-stop spécial après échec de synchronisation du marqueur), le processus n’émet aucun code de refus ni message de réponse du protocole et se termine avec un statut de sortie dédié, unique et commun, distinct des statuts de succès et de refus. Ce statut signifie uniquement que le processus s’est arrêté en fail-stop et que l’issue n’est pas établie ; il ne prétend rien sur l’effet ni sur l’état du nonce, et n’est pas un code technique de réponse du §10.2. Les codes [R] du cas 2, point 5, et du cas 3 ne valent que pour les chemins où le processus continue. Un marqueur résiduel présent maintient le gel ; dans le fail-stop spécial, l’absence observée du marqueur n’est présentée ni comme une preuve de retrait durable ni comme une levée du gel. **Nom symbolique — décidé le même jour [D] :** ce statut est `EXIT_FAIL_STOP`, statut de sortie symbolique unique, commun à tous les chemins qui se terminent en fail-stop ; il indique seulement l’arrêt en fail-stop et une issue non établie, ne dit rien sur l’effet ni sur l’état du nonce, et n’est ni un code de refus ni un code de réponse du protocole. **Seul signal du protocole — décidé le même jour [D] (option T1) :** en fail-stop, aucun code de réponse ni message du protocole n’est émis ; `EXIT_FAIL_STOP` est le seul signal produit par le processus au titre du protocole ; aucun message applicatif n’est écrit sur stdout ni sur stderr lors du fail-stop ; une télémétrie diagnostique facultative, hors protocole et sans retard du fail-stop, reste soumise aux règles déjà établies ; le marqueur n’est pas l’unique signal qui fait toujours foi : après un échec de synchronisation du marqueur, son absence visible ne prouve ni que son retrait est durable ni que le gel est levé, et un marqueur résiduel présent maintient le gel. **Valeur numérique — non fixée, décidé le même jour [D] :** le nom symbolique `EXIT_FAIL_STOP` reste fixé ; sa valeur numérique n’est pas fixée à ce stade et sera choisie après la définition de la liste des statuts de sortie de la CLI et l’examen des chaînes CLI, sudo, SSH et superviseur ; aucune plage numérique n’est adoptée comme décision. Restent ouverts : la valeur numérique de `EXIT_FAIL_STOP`, la liste complète des statuts de sortie de la CLI au-delà du cadre symbolique de `apply` (puce suivante), la transmission du statut par la CLI, sudo, SSH ou le superviseur, la vérification de ces chaînes sur le serveur, la conduite face à un statut inconnu ou au statut 255, la politique de redémarrage du processus par le superviseur, que le choix du numéro ne tranche pas, l’observation côté E, et la conduite de récupération lorsque le marqueur est absent ou que sa présence ne peut être établie ;
      - **catégories de sortie de `apply` — cadre symbolique décidé par le propriétaire le 28 octobre 2026 [D], sans valeurs numériques** (§10.2, « Catégories de sortie de `apply` » ; §5.5.1, cas 1 à 3 ; §5.5.5, L.7) : les catégories décrivent seulement ce qui est établi sur l’effet métier, le `COMMIT` et l’état du nonce, sans affirmer l’effectivité, la possibilité de réessayer ni l’état du gel ou du marqueur ; le comptage éventuel des refus est hors de leurs garanties, son emplacement et sa transaction restant [O]. `EXIT_OK` : `COMMIT` confirmé, effet et `CONSUMED` enregistrés ensemble, sans affirmer l’effectivité (une opération qui ouvre n’est effective qu’après V1, l’ancrage et E ; une fermeture ordinaire prend effet au `COMMIT` local dans le service intact) ; `EXIT_REFUSED_RECORDED` : effet métier annulé, refus enregistré, nonce visé non `ISSUED` à l’issue ; `EXIT_REFUSED_UNRECORDED` : aucun effet métier ni changement du nonce validé par cette tentative, sans rien dire des écritures éventuelles de comptage ; `EXIT_REFUSED_NONCE_UNESTABLISHED` : effet annulé au `SAVEPOINT`, `COMMIT` final en erreur, nonce ni établi comme `FAILED` ni comme intact (cas 1, points a et c) ; `EXIT_OUTCOME_TO_ESTABLISH` : `COMMIT` du chemin de succès en erreur, ni succès ni refus, processus qui continue (cas 3, points a et c) ; `EXIT_FAIL_STOP` : inchangé. `EXIT_REFUSED_EFFECT_UNASSERTED` (cas 2, points 1 et 2) reste [R], conditionnelle à la confirmation du code de réponse du cas 2. Restent ouverts : le classement du refus pour marqueur résiduel, de l’échec de `BEGIN IMMEDIATE`, du délai de W, de la transition sans changement de ligne après une lecture `ISSUED` et des autres commandes ; la concordance entre catégories et codes, et le canal des codes ; toutes les valeurs numériques. Les renvois des codes du cas 2, point 5, et du cas 3, « Réponse », pointent vers le §10.2, sans trancher leur rattachement. **Précisé le 29 octobre 2026 [D]** (§10.2, « Déductions sous C2 ») : une catégorie n’affirme pas comme établi un état qui repose seulement sur une déduction sous C2 ; au cas 2, point 1, le nonce non modifié par cette tentative peut être indiqué comme établi après le `ROLLBACK` réussi ; au point 2, la catégorie n’affirme pas que le nonce est inchangé, cette conclusion dépendant de C2 et restant une déduction [R], non une garantie de la catégorie ; la même réserve s’applique à tout rattachement de `EXIT_REFUSED_UNRECORDED` qui dépend de `in_transaction` faux et de C2, notamment au cas 1 ; `EXIT_REFUSED_EFFECT_UNASSERTED`, toujours [R], peut affirmer « aucun `COMMIT` exécuté » et « absence d’effet non affirmée », mais ne garantit pas l’état du nonce au point 2. La démonstration de C2 dans la mise en œuvre reste ouverte [O] ; la question d’un nouvel essai de `ROLLBACK` est distincte et reste ouverte [O].
    - **Restent ouverts [O] :**
      - le sort du nonce lorsque le `COMMIT` final échoue, et l’acceptation de la perte de « une tentative par nonce » lorsque le nonce reste `ISSUED`. L’option (a) exclut d’y remédier par une réécriture dans une transaction séparée ;
      - la portée de « ne permet jamais un effet » pour une tentative ultérieure ;
      - l’annulation lorsqu’elle n’est ni établie ni déduite, la portée du constat de l’état et l’état persistant après un `COMMIT` en erreur ;
      - lorsque le cas 2 suit un échec de l’annulation complète, la question de savoir si un nouvel essai de `ROLLBACK` est admis ;
      - la démonstration de la condition C2 dans la mise en œuvre, et la version de SQLite liée sur le serveur, inconnue, ainsi que la configuration effective (C3) ;
      - le maintien du verrou d’écriture après `ROLLBACK TO`, déduit, et le comportement de `close()` dans CPython 3.14 [H] ;
      - l’admissibilité d’un second `COMMIT` dans la même transaction après le `SQLITE_BUSY` documenté ;
      - la condition 3 du §5.5.5, L.4, après un `COMMIT` en erreur ;
      - pour le gel : les détails du marqueur, c’est-à-dire son emplacement exact, sa catégorie étant fixée, son nommage et son contenu, ses modes exacts de permission, les moyens de sa persistance, la conduite si sa création échoue, hors l’échec de synchronisation réglé [D] (la fin par un `ROLLBACK` complet, le refus comme échec technique fermé et le sort du nonce après cet échec étant également réglés [D] ; l’absence d’incrément du compteur borné par classe de refus et la nature de son code étant aussi réglées [D] ; les trois valeurs du qualificatif étant réglées [D] ; son nom exact, la liste des codes techniques, les noms de ces valeurs, la tentative systématique ou non du retrait, la valeur numérique de `EXIT_FAIL_STOP`, non fixée à ce stade [D], sa transmission, la liste complète des statuts de sortie de la CLI au-delà du cadre symbolique de `apply`, le classement des chemins de `apply` non encore définis, la vérification des chaînes sur le serveur, la conduite face à un statut inconnu ou au statut 255, la politique de redémarrage du processus par le superviseur, que le choix du numéro ne tranche pas, l’observation côté E, et la conduite de récupération lorsque le marqueur est absent ou que sa présence ne peut être établie restant ouverts), les détails techniques du retrait et de sa durabilité, hors la suppression visible non durable réglée [D], la conduite si l’état ou la présence du marqueur ne peut pas être établi, l’identification des marqueurs résiduels, l’opération `root` qui le retire et sa coordination avec W ; le mécanisme, l’équité et les délais de W, et l’emplacement et les modes exacts de son fichier, son support étant fixé ; la méthode de sauvegarde et la procédure de restauration, y compris l’application du principe selon lequel une restauration ne vaut pas levée du gel ; la qualification du refus pour marqueur résiduel, son code, son comptage et le sort du nonce ; les critères de récupération, la vérification qui lève le gel et les critères détaillés de la levée ;
      - l’application du gel, et d’un marqueur, aux erreurs du `COMMIT` de la validation avant ancrage ou de D-9 ;
      - pour le gel conservateur : la procédure détaillée de récupération, et l’articulation avec l’arrêt forcé et la disponibilité de D-9 au redémarrage (L.5). La limite face à un compte de service compromis est décidée, et n’est plus un point ouvert ;
      - la portée de la remise par E (E7) d’une décision enregistrée avant l’incertitude ;
      - le sort, pendant le gel, des opérations signées qui ferment, y compris en présence d’un marqueur résiduel constaté sous W, de la validation avant ancrage et de l’ancrage, ainsi que la qualification du refus et le sort du nonce visé ;
      - la disponibilité de D-9 pendant le gel, sa portée restant inchangée ;
      - le sort d’une nouvelle tentative après la levée du gel.

Restent ouverts hors de ce périmètre : H1, D-12 (aucun callback public), D-15 (secret client) et D-14.

**D-5 reste non résolu. Provider = CLOSED et NO-GO restent en vigueur.**
