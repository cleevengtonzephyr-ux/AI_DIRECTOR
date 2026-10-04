# Phase F — Chemin de production REST Higgsfield (fermé)

- **Date :** 2026-10-02
- **Référence :** branche `phase-e2-final-content-verification` à `8c2f45c8bf7dbd385933eb6bad16d455a021bb0d` (Phase E2, non fusionnée ; `origin/main` à `8ad12f60465eb16edd36c7216ba04caa9c59ec8b`)
- **Statut :** implémentation fermée. Elle n'autorise rien et n'ouvre aucun verrou.

**NO-GO en vigueur. Provider = CLOSED.** La décision de [`phase_a_real_generation_decision.md`](phase_a_real_generation_decision.md) est inchangée. Ce document décrit le chemin de production réel prévu pour une future génération Higgsfield depuis GitHub Actions : ce qui est construit, ce qui reste fermé, et ce qui bloque un premier lancement. Pendant cette phase, aucun endpoint Higgsfield n'a été appelé, aucun secret n'a été lu ni créé, et aucun crédit n'a été consommé.

## 1. Contradictions constatées avec l'existant

| Constat | Conséquence pour ce chemin |
|---|---|
| Le chemin réel existant passe par le **CLI** (`HiggsfieldClient.run()`, `subprocess`). Les verrous 3 et 4 ne couvrent que ce CLI, et le détecteur de dérive ne compte que les appels `create_job(` et `.run(... "create" ...)` | Un client REST non verrouillé aurait été un chemin parallèle invisible pour ces gardes. Le client REST porte donc ses propres verrous (F-1 à F-4). Il n'est câblé à rien, et un test vérifie qu'aucun module de production ne l'importe |
| L'estimation actuelle (`generate cost`, P3.85) **exclut les médias**, alors que la génération les inclut | L'estimation n'a pas les mêmes paramètres que la génération. Le client REST construit les deux à partir du même corps (`request_body()`), mais aucun endpoint REST d'estimation n'est connu |
| Le registre anti-rejeu (`state/`) vaut pour **une machine et un dossier d'état** (A2-d). Les runners GitHub Actions sont **éphémères** | Sur GitHub Actions, l'anti-rejeu local repart de zéro à chaque exécution. Le script refuse donc toute reprise (`run_attempt` différent de 1) tant qu'aucun état durable n'existe |
| L'autorisation actuelle ne porte pas les paramètres vidéo (A2-b) | Le manifeste les inclut. L'approbation porte sur l'empreinte du manifeste complet |

## 2. Ce qui est construit

| Élément | Fichier | Rôle |
|---|---|---|
| Manifeste | `integrations/higgsfield/manifest.py` | Énoncé exact de la génération : modèle, paramètres, empreinte du prompt et des médias. Sérialisation déterministe, `manifest_sha256`. Les médias sont lus une seule fois, et leur type est reconnu par signature binaire, jamais par l'extension. Le prompt et les chemins locaux n'apparaissent pas dans la forme canonique |
| Comparaison | `verify_manifest()` | Le manifeste recalculé doit être identique à l'empreinte approuvée. Sinon : `ManifestMismatchError`, arrêt avant tout envoi |
| Idempotence | `derive_idempotency_key()` | Clé dérivée de (manifeste, identifiant d'approbation), sans aléa. Elle est identique pour toute reprise de la même approbation, et nouvelle pour toute nouvelle approbation |
| Client REST | `integrations/higgsfield/rest_api.py` | Requêtes REST explicites, sans SDK, avec en-tête `Idempotency-Key` visible. Classification fermée des réponses de soumission, de statut et d'annulation. Plan de reprise pur. Faits d'API marqués par niveau de confirmation |
| Transport HTTPS | `integrations/higgsfield/https_transport.py` | Seul module qui ouvrirait une connexion : hôte fixe, TLS vérifié par défaut, délai obligatoire, aucune redirection suivie, identifiants injectés et masqués. Chaque opération est liée à un gabarit fermé méthode + chemin + corps (`OPERATION_ROUTES`, aujourd'hui `status` seul : `GET /requests/<id>/status`, sans corps) ; toute requête qui ne correspond pas exactement est refusée avant connexion, quelle que soit son étiquette |
| Journal d'audit | `agents/production_audit_journal.py` | JSON Lines chaîné (option J-b), écrit par ajout, avec un fichier de tête (`<journal>.head`) qui fixe la fin de la chaîne. Détecte : modification, suppression ou insertion au début ou au milieu, suppression des dernières entrées, suppression du seul journal ou de la seule tête. Ne détecte pas : suppression conjointe du journal et de la tête, réécriture complète et cohérente (aucune clé, aucune ancre externe). Journal absent : état explicite refusé, jamais lu comme un journal vide ; seule une initialisation explicite en crée un. Il refuse tout détail qui ressemble à un secret, à un jeton, à un en-tête d'authentification, à une URL ou à un prompt. Chaîne rompue ou absente : aucune écriture |
| Script du workflow | `scripts/higgsfield_production_run.py` | `prepare` (manifeste Video 005, comparé à la Release Candidate verrouillée) et `verify-and-execute` (recalcul, comparaison, puis arrêt sur Provider = CLOSED, code 4). Un journal absent est refusé (code 6) sauf avec `--new-journal`. Il ne lit aucune variable d'environnement et n'instancie aucun client |
| Workflow | `.github/workflows/higgsfield-production.yml` | Déclenchement manuel seulement, `permissions: {}`, groupe de concurrence sans annulation. Le job `prepare` n'a ni secret ni environnement. Le job `execute` dépend de `prepare`, est limité à `main` et est rattaché à l'environnement `higgsfield-production`. **Aucun secret n'est référencé** tant que le Provider est fermé |
| Tests | `tests/test_phase_f_production_path.py` | Mock uniquement : toute connexion HTTPS est remplacée par un objet qui fait échouer le test |

## 3. Protections conservées et ajoutées

Les quatre verrous de la Phase A sont **inchangés** : aucun des fichiers qui les portent n'a été modifié.

Verrous ajoutés, indépendants les uns des autres :

- **F-1, F-2, F-3** : `HiggsfieldRestClient.submit_generation()`, `cancel_generation()` et `upload_media()` sont chacune une instruction `raise HiggsfieldRealGenerationDisabledError` unique, vérifiée par AST.
- **F-4** : `HttpsTransport.send()` refuse toute opération hors de `READ_ONLY_REST_OPERATIONS` (`status`, `estimate`) avant toute connexion.
- **Gabarits de route** : après F-4 et les faits, `HttpsTransport.send()` refuse toute requête dont la méthode, le chemin entier ou la présence d'un corps diffère du gabarit fermé de son opération. Une étiquette `status` ne peut donc pas porter un `POST /{model_id}`. `estimate` n'a pas de gabarit (aucun endpoint connu) : il est refusé même si ses faits étaient confirmés.
- **Faits non confirmés** : une opération dont un fait d'API requis n'est pas `CONFIRMED` est refusée avant toute connexion. Aucun fait ne l'est aujourd'hui : le transport réel refuse donc tout, y compris la lecture du statut.
- **Aucun câblage** : ni `director.py`, ni `HiggsfieldProvider`, ni `GenerationJobService`, ni le script n'importent le client REST ou le transport.

Point d'intégration futur, sur décision seulement : derrière `HiggsfieldProvider.create_job()` (verrou 2), après toute la chaîne P2 existante (Gate, contrats, consommation de l'autorisation, marqueur « en vol »). Jamais à côté.

## 4. Gestion fermée des issues

| Issue | Classification | Suite |
|---|---|---|
| 2xx avec `request_id` valide | `ACCEPTED` | Enregistrer l'identifiant avant toute autre action |
| 2xx sans identifiant, 3xx, 408, 409, 425, 429, 5xx, coupure après envoi | `AMBIGUOUS` | Reprise avec **la même clé** seulement si l'`Idempotency-Key` est confirmée ; sinon état inconnu, rapprochement humain, aucun nouvel envoi |
| Connexion jamais établie | `NOT_SENT` | Reprise possible dans la limite fixée par l'appelant |
| 402, ou 4xx mentionnant des crédits insuffisants | `INSUFFICIENT_CREDITS` | **Nouvelle approbation requise** avant tout nouvel envoi |
| 401, 403 | `AUTH_FAILED` | Nouvelle approbation requise |
| Autre 4xx | `REJECTED` | Nouvelle approbation requise |
| Statut non reconnu, « succès » sans résultat | `UNKNOWN` | Jamais présenté comme un succès |

Les URL de résultat ne sont jamais publiées : seul leur nombre l'est.

## 5. Inconnues qui bloquent le premier lancement réel

Aucun montant de plafond n'est fixé ni proposé ici. **L'estimation n'est pas un plafond garanti** : Higgsfield ne l'a pas confirmé. Aucune borne de dépense n'est donc garantie.

| Inconnue | Statut | Source actuelle |
|---|---|---|
| Prise en charge de l'en-tête `Idempotency-Key` | Non confirmée | Aucune |
| Signal d'un refus pour crédits insuffisants | Non confirmé | Aucune |
| L'estimation borne-t-elle la facturation ? | Non confirmé | Aucune |
| Endpoint REST d'estimation | Inconnu | Aucune |
| Procédure d'envoi des médias (upload, URL signée) | Inconnue | Aucune |
| Schéma du corps de soumission et `model_id` REST de `seedance_2_0` | Non confirmés | Aucune |
| Valeurs de statut | Non confirmées | Résumé de recherche |
| URL de base, schéma `Authorization: Key <id>:<secret>`, `POST /{model_id}`, `GET /requests/{id}/status`, `POST /requests/{id}/cancel` | Source secondaire | Résumés de recherche de docs.higgsfield.ai, non lus directement |
| Effet d'une annulation sur la facturation | Inconnu | Aucune |

Conditions de la Phase A toujours ouvertes : 1 (identité ; l'environnement GitHub avec relecteurs requis correspond à l'option D de la Phase C, qui reste à décider), 3 (plafond), 5 (révocation persistante ; le journal ne couvre qu'une partie), 7 (arrêt et refermeture). Condition 2 : toujours partiellement traitée.

Autres points bloquants :

- **État durable sur GitHub Actions** : registre anti-rejeu et journal à conserver hors du runner (options possibles : branche d'état, stockage externe, artefacts). Aucune n'est choisie. **Aujourd'hui, le journal du job `execute` est écrit dans `RUNNER_TEMP` : il est éphémère, disparaît avec le runner et n'est publié nulle part.** Il ne fournit donc ni trace d'audit conservée, ni anti-rejeu entre exécutions. Le seul garde-fou implémenté est le refus d'une relance (`run_attempt` différent de 1) ; un nouveau `workflow_dispatch` avec la même empreinte obtient un nouveau `run_id`, donc un nouvel `approval_id` et une nouvelle clé d'idempotence, et rien ne l'empêcherait.
- **Liaison approbation-autorisation** : transformer l'approbation de l'environnement GitHub en `RealGenerationAuthorization` liée au manifeste. Non implémenté : construire cette autorisation automatiquement serait une autorisation fabriquée par du code.
- **Portée réelle de l'approbation GitHub** : l'approbation d'un relecteur de l'environnement porte sur le *déploiement* d'une exécution, **pas cryptographiquement sur l'empreinte du manifeste**. `approved_manifest_sha256` est saisi par la personne qui lance le workflow ; le job `execute` vérifie seulement que le manifeste recalculé lui correspond. Aucune signature ni aucun enregistrement de l'approbateur n'est lié à cette empreinte.
- **`approval_id` non vérifié** : `approval_id` vaut `gh-<run_id>`. Ce n'est ni l'identité d'un approbateur, ni la preuve qu'une revue humaine a eu lieu, et le script ne le vérifie auprès d'aucune source : il accepte toute chaîne bien formée. Il n'est lié à aucune autorisation humaine.
- **Ancre externe du journal** (option J-c) : non mise en œuvre.

## 6. Actions du propriétaire, dans l'ordre, sur décision seulement

1. Obtenir de Higgsfield, par écrit, les faits de la section 5. Les consigner, puis passer chacun à `CONFIRMED` dans `HIGGSFIELD_REST_FACTS`, avec sa source.
2. Fixer le plafond par requête (condition 3), et choisir l'état durable et la liaison approbation-autorisation.
3. Créer l'environnement `higgsfield-production` : relecteurs requis, auto-approbation interdite, branche limitée à `main`. Sinon, GitHub le crée sans protection à la première exécution.
4. Placer les identifiants comme secrets **de l'environnement**, jamais du dépôt, puis les référencer dans la seule étape du job `execute`.
5. Prendre une nouvelle décision écrite, distincte de la Phase A, qui constate les sept conditions et ouvre les verrous de façon explicite.

## 7. Ce que cette phase ne fait pas

- Aucun appel à un endpoint Higgsfield (estimation, upload, soumission, statut, annulation) ; aucun appel à `create_job()`.
- Aucun compte, aucune clé, aucun secret, aucun paramètre GitHub ni aucune protection d'environnement créé ; aucun secret lu.
- Aucun des quatre verrous ouvert ni contourné ; aucun montant fixé.
- Aucune modification de `director.py`, de `HiggsfieldClient`, de `HiggsfieldProvider`, de `GenerationJobService` ni de la Gate.

**Provider = CLOSED · Real generation = 0 · Credits = 0**
