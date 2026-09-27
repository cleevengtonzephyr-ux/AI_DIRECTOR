# AI DIRECTOR

Système d'agents IA destiné à orchestrer la production vidéo via Higgsfield, construit selon le **MASTER PROMPT V2**.

## État du projet

Toutes les phases du pipeline MASTER PROMPT V2 sont implémentées et testées (Phases B à N). Le projet reste en **mode sécurisé par défaut** : aucune génération Higgsfield réelle n'est jamais déclenchée automatiquement, et un `HiggsfieldRealGenerationDisabledError` explicite bloque toute tentative de création de job réel via le `HiggsfieldProvider` réel, indépendamment de toute autre logique.

## Architecture (pipeline MASTER PROMPT V2)

```
USER
  -> AIDirector            (director.py)
  -> VideoPlanner          (agents/planner.py — V1)
  -> TaskManager           (agents/task_manager.py)
  -> VideoAgent            (agents/video_agent.py)
  -> HiggsfieldProvider    (integrations/higgsfield/provider.py)
  -> GenerationCostService (agents/generation_cost_service.py)
  -> GenerationApprovalGate(agents/generation_approval_gate.py)  -> APPROVED / NEEDS_APPROVAL / BLOCKED / ALREADY_EXECUTED / INVALID_REQUEST
  -> GenerationJobService  (agents/generation_job_service.py)     -> createJob() / wait_for_job()
  -> QualityEvaluator      (agents/quality_evaluator.py)
  -> FinalReportService    (agents/final_report_service.py)
  -> USER
```

- **HiggsfieldClient** (`integrations/higgsfield/client.py`) est le seul point de contact avec le CLI Higgsfield installé localement (arguments toujours passés en liste, `shell=False`, jamais d'injection shell possible).
- **HiggsfieldProvider** masque le CLI derrière un contrat stable (`BaseHiggsfieldProvider`), implémenté aussi par **MockHiggsfieldProvider** (100 % en mémoire, utilisé par tous les tests de génération).
- **GenerationApprovalGate** est le verrou central : aucune génération n'est jamais approuvée automatiquement, un coût inconnu ne débloque jamais silencieusement l'exécution, et une requête déjà exécutée est rejetée (`ALREADY_EXECUTED`).
- Le modèle vidéo par défaut est **`seedance_2_0`**, mais reste un paramètre explicite partout (`VideoAgent`, `TaskManager`) — jamais déduit implicitement d'un ancien identifiant de workflow V1.

### Composants V1 — état réel (vérifié P3.42, graphe d'import réel, jamais supposé)

Certains modules historiques restent réellement utilisés par le chemin de production ; d'autres sont des orphelins V1 totalement déconnectés — les deux catégories étaient auparavant listées ensemble ici, ce qui était trompeur. État exact, reconstruit depuis le graphe d'import réel de `director.py` (`tests/test_v1_orphan_isolation.py` protège cette distinction en permanence) :

- **Réellement utilisés en production** : `agents/asset_preparation_system.py`, `agents/asset_catalog.py` (données de catalogue consommées par `asset_preparation_system.py`), `agents/prompt_assembly_system.py`. Ces trois modules sont importés, directement ou indirectement, par `director.py`.
- **Orphelins V1 confirmés (Phase P3.42)** : `agents/asset_intake_manager.py`, `agents/asset_manager.py`, `agents/cost_engine.py`, `agents/production_gate.py`, `agents/pipeline_orchestrator.py`, ainsi que `agents/production_controller.py`, `agents/asset_resolver.py`, `agents/higgsfield_executor.py`, `agents/job_monitor.py`, `agents/qa_engine.py`. Aucun de ces dix modules n'est atteignable depuis `director.py` — ils ne participent à AUCUNE décision budgétaire, d'identité ou d'autorisation réelle aujourd'hui, malgré des noms proches de composants réels (`production_gate.py` ≠ `generation_approval_gate.py`, le vrai Gate P2 ; `cost_engine.py` ≠ `generation_cost_service.py`, le vrai service de coût P2). Conservés comme dette technique, non supprimés automatiquement.

Le nouveau pipeline (Phases B-N, P2, P3) est la seule chaîne d'autorité réelle ; il ne délègue aucune décision aux modules orphelins ci-dessus.

## Scripts

- **`python scripts/higgsfield_check.py`** — vérification de connectivité Higgsfield en lecture seule (compte, workflows). Ne crée aucun job, ne consomme aucun crédit.
- **`python scripts/demo_test.py`** — démonstration de bout en bout du pipeline complet via `MockHiggsfieldProvider` (aucun réseau, aucun CLI réel, aucun crédit). Illustre 3 scénarios : sans approbation (`NEEDS_APPROVAL`), approuvé (`EXECUTED_PASS`), budget insuffisant (`BLOCKED`).
- **`python scripts/architecture_audit.py`** — audit ponctuel, en lecture seule, de la cartographie architecturale canonique (`agents/canonical_architecture_contract.py`) contre l'état réel du repository, via le Architecture Drift Detector (`agents/architecture_drift_detector.py`). Code de sortie `0` = `NO_DRIFT`, `1` = `DRIFT_DETECTED`, `2` = `ANALYSIS_INCOMPLETE`. Ce même contrôle s'exécute déjà automatiquement à chaque lancement de la suite de tests (`tests/test_architecture_drift_detector.py`, `tests/test_architecture_contract_integration.py`) ; ce script sert uniquement à l'invoquer isolément.

## Environnement Python

Version supportée : **Python 3.14** (CPython, Windows), déclarée dans `.python-version`. Ce fichier se contente de déclarer la version : il n'installe pas Python et n'en gère pas l'installation, l'interpréteur doit être installé séparément. C'est la seule version sur laquelle la suite complète a été exécutée et validée (Phase P3.106). Bibliothèque standard uniquement : aucune dépendance tierce.

Le code exige au minimum Python 3.11 (`BaseException.add_note()`, `agents/executed_request_store.py`), mais les versions 3.11 à 3.13 n'ont jamais été validées et ne sont **pas** déclarées supportées. Certains garde-fous dépendent de comportements précis de la bibliothèque standard sous Windows (résolution de chemins, lancement de processus). Changer de version impose donc de relancer la suite complète, puis de mettre à jour cette déclaration. `tests/test_p3_106_python_version.py` échoue tant que l'interpréteur utilisé diffère de la version déclarée.

## Tests

```
python -m unittest discover -s tests -t . -v
```

Tous les tests touchant à la génération vidéo utilisent exclusivement `MockHiggsfieldProvider` — aucun appel réseau, aucun crédit consommé. Vérification de compilation :

```
python -m compileall agents integrations scripts .
```

## Sécurité

- `HiggsfieldProvider.create_job()` (réel) lève systématiquement `HiggsfieldRealGenerationDisabledError` — ce garde-fou est indépendant de toute autre logique (Approval Gate, budget) et n'a jamais été désactivé au cours du développement.
- Aucune approbation n'est jamais déduite automatiquement (`approved=False` par défaut à chaque étage : `GenerationRequest`, `VideoAgent`, `TaskManager`, `AIDirector`).
- Un coût inconnu ne débloque jamais silencieusement l'exécution (`NEEDS_APPROVAL` explicite).
- Aucun résultat n'est jamais présenté comme un succès s'il n'a pas été réellement exécuté (`FinalReportStatus.NOT_EXECUTED` structurellement disjoint des statuts `EXECUTED_*`).
