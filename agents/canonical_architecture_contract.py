"""
AI DIRECTOR — Canonical Architecture Contract (Phase P3.31, MASTER PROMPT V2)

Formalise, en UN SEUL endroit immuable et testable, la cartographie
architecturale établie et vérifiée par les audits P3.28/P3.29/P3.30 :

    DOMAIN A -- BUSINESS_EDITORIAL
        Strategy -> Content -> Quality -> Publishing -> Analytics ->
        Optimization, orchestrés par DirectorPipeline/MissionStateMachine.
        Ne possède AUCUNE autorité de production réelle.

    DOMAIN B -- PRODUCTION_MODELING
        ScriptProductionBridge -> VideoProductionPreparation ->
        PreProductionReview -> ProductionReadinessHandoff ->
        ProductionAuthorityIntake -> HumanAuthorizationHandoff ->
        ActivationEligibility -> ProductionActivationHandoff.
        Prépare/modélise la production, ne possède aucune autorité
        propre -- inspecte uniquement des objets déjà fournis.

    BRIDGE -- ControlledActivationComposition (Phase P3.23)
        Seul point qui relie Domain B au Domain C, en délégant, sans
        jamais la dupliquer, à AIDirector.prepare_real_generation_
        activation() (Phase P2.29, pré-existant, protégé).

    DOMAIN C -- P2_AUTHORITY_CORE
        GenerationApprovalGate -> ReleaseCandidateIdentityLock ->
        RequestScopedActivationContract -> ControlledRealProvider
        ActivationContract -> CriticalSectionLock -> ExecutedRequestStore
        -> GenerationJobService -> HiggsfieldProvider -> create_job().
        Seul domaine possédant une autorité réelle d'exécution.

    DISPATCH -- TaskManager
        Wrapper/queue dispatcher vers AIDirector.run_video_mission() --
        n'est pas une quatrième architecture (cf. rapport P3.30 Section 7).

CE MODULE NE FAIT RIEN -- il ne contient aucune méthode qui déciderait,
activerait ou exécuterait quoi que ce soit, et n'importe aucun mécanisme
P2 (GenerationApprovalGate, CriticalSectionLock, ExecutedRequestStore,
GenerationJobService, HiggsfieldProvider, etc.) : le contrat DÉCRIT ces
frontières pour que `agents/architecture_drift_detector.py` puisse les
comparer à l'état réel du repository, il ne les remplace ni ne les
duplique jamais. Aucun secret, credential, token, ni chemin absolu
propre à une machine n'est stocké ici -- uniquement des chemins relatifs
au repository et des noms de symboles Python.

IMMUTABILITÉ / DÉTERMINISME (Section 6, rapport P3.31) : toutes les
collections exposées sont des `frozenset`/`tuple`, le contrat lui-même
est un `@dataclass(frozen=True)` construit une seule fois au niveau
module (`CANONICAL_ARCHITECTURE_CONTRACT`). Aucune méthode de ce module
n'a d'effet de bord ; deux appels quelconques de ce module renvoient
toujours exactement les mêmes valeurs.

VERSIONING (comme `agents/mission_state_machine.py::STATE_MACHINE_
VERSION`) : `CONTRACT_VERSION` doit être incrémenté si la cartographie
canonique elle-même change (nouveau domaine, nouveau composant protégé,
nouvelle règle non-négociable) -- jamais pour un simple ajout de
composant à un domaine existant sans changement de règle.

CONTRACT_VERSION 2 (Phase P3.63, "Certificate Consumer Architecture
Guardrail & Drift Enforcement") : ajoute une règle non-négociable
supplémentaire -- NO CERTIFICATE -> AUTHORITY EDGE. P3.62 a démontré,
par un audit AST manuel, que zéro fichier de la P2 Authority Core / de
la Production Modeling / du point d'entrée n'importe un symbole du
sous-système certificate (P3.54-P3.60), et que ce sous-système
n'importe/n'appelle jamais rien du côté autorité. P3.63 rend cette
propriété PERMANENTE : `agents/architecture_drift_detector.py` la
vérifie désormais à chaque `analyze()`, au lieu de dépendre d'un audit
manuel réexécuté à chaque phase. Aucun domaine n'est ajouté/retiré, et
aucune règle existante (P3.28-P3.31) n'est modifiée -- uniquement une
nouvelle catégorie de fichiers (le sous-système certificate) et une
nouvelle vérification d'edge, purement additive.
"""

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import FrozenSet, Mapping, Tuple


CONTRACT_VERSION = 2


class Domain(str, Enum):
    """Les domaines architecturaux canoniques (rapport P3.29/P3.30)."""

    BUSINESS_EDITORIAL = "BUSINESS_EDITORIAL"
    PRODUCTION_MODELING = "PRODUCTION_MODELING"
    BRIDGE = "BRIDGE"
    P2_AUTHORITY_CORE = "P2_AUTHORITY_CORE"
    DISPATCH = "DISPATCH"
    ENTRY_POINT = "ENTRY_POINT"
    TEST = "TEST"
    SCRIPT = "SCRIPT"
    UNCLASSIFIED_LEGACY = "UNCLASSIFIED_LEGACY"


# ----------------------------------------------------------------------
# DOMAIN A -- BUSINESS / EDITORIAL (rapport P3.29 Section C, P3.30 Section 3)
# ----------------------------------------------------------------------

BUSINESS_EDITORIAL_FILES: FrozenSet[str] = frozenset(
    {
        "agents/strategy_agent.py",
        "agents/content_agent.py",
        "agents/quality_agent.py",
        "agents/publishing_agent.py",
        "agents/analytics_agent.py",
        "agents/optimization_agent.py",
        "agents/director_pipeline.py",
        "agents/mission_state_machine.py",
    }
)

# ----------------------------------------------------------------------
# DOMAIN B -- PRODUCTION / MODELING (rapport P3.29 Section D, P3.30 Section 4)
# ----------------------------------------------------------------------

PRODUCTION_MODELING_FILES: FrozenSet[str] = frozenset(
    {
        "agents/script_production_bridge.py",
        "agents/video_production_preparation.py",
        "agents/pre_production_review.py",
        "agents/production_readiness_handoff.py",
        "agents/production_authority_intake.py",
        "agents/human_authorization_handoff.py",
        "agents/activation_eligibility.py",
        "agents/production_activation_handoff.py",
    }
)

# ----------------------------------------------------------------------
# BRIDGE -- Phase P3.23 (rapport P3.29 Section E, P3.30 Section 6)
# ----------------------------------------------------------------------

BRIDGE_FILES: FrozenSet[str] = frozenset({"agents/controlled_activation_composition.py"})

BRIDGE_ENTRY_METHOD = "compose_controlled_activation"
BRIDGE_DELEGATE_METHOD = "prepare_real_generation_activation"

# ----------------------------------------------------------------------
# DOMAIN C -- P2 PRODUCTION AUTHORITY / EXECUTION CORE
# (rapport P3.29 Section D/M, P3.30 Section 5)
# ----------------------------------------------------------------------

P2_AUTHORITY_CORE_FILES: FrozenSet[str] = frozenset(
    {
        "agents/generation_approval_gate.py",
        "agents/release_candidate_identity_lock.py",
        "agents/activation_contract.py",
        "agents/controlled_real_provider_activation.py",
        "agents/critical_section_lock.py",
        "agents/executed_request_store.py",
        "agents/generation_job_service.py",
        "agents/real_provider_execution_gate.py",
        "agents/real_provider_activation_preflight.py",
        "agents/production_activation_boundary.py",
        "agents/activation_readiness.py",
        "agents/production_activation_readiness_certificate.py",
        "agents/final_report_service.py",
        "agents/generation_cost_service.py",
        "agents/production_model.py",
        "agents/quality_evaluator.py",
        "integrations/higgsfield/provider.py",
        "integrations/higgsfield/client.py",
        "integrations/higgsfield/mock_provider.py",
        "integrations/higgsfield/types.py",
        "integrations/higgsfield/errors.py",
    }
)

# Sous-ensemble de P2_AUTHORITY_CORE_FILES (+ director.py, l'entry point
# de composition) : fichiers qu'aucune phase future ne doit modifier
# sans STOP explicite et justification démontrée (rapport P3.30 Section
# 11/17, mission P3.31 Section 15). `PROTECTED_P2_FILES <=
# P2_AUTHORITY_CORE_FILES | {"director.py"}` est une invariante vérifiée
# par tests/test_canonical_architecture_contract.py.
PROTECTED_P2_FILES: FrozenSet[str] = frozenset(
    {
        "agents/generation_approval_gate.py",
        "agents/critical_section_lock.py",
        "agents/executed_request_store.py",
        "agents/activation_contract.py",
        "agents/controlled_real_provider_activation.py",
        "agents/real_provider_execution_gate.py",
        "agents/real_provider_activation_preflight.py",
        "agents/production_activation_boundary.py",
        "agents/release_candidate_identity_lock.py",
        "agents/generation_job_service.py",
        "agents/final_report_service.py",
        "agents/activation_readiness.py",
        "agents/production_activation_readiness_certificate.py",
        "integrations/higgsfield/provider.py",
        "integrations/higgsfield/client.py",
        "integrations/higgsfield/mock_provider.py",
        "director.py",
    }
)

# ----------------------------------------------------------------------
# DISPATCH -- TaskManager (rapport P3.30 Section 7)
# ----------------------------------------------------------------------

DISPATCH_FILES: FrozenSet[str] = frozenset({"agents/task_manager.py"})

# ----------------------------------------------------------------------
# ENTRY POINT -- director.py (racine de composition, wiring layer)
# ----------------------------------------------------------------------

ENTRY_POINT_FILES: FrozenSet[str] = frozenset({"director.py"})


@dataclass(frozen=True)
class CanonicalComponent:
    """Un composant nommé de l'architecture canonique -- fichier +
    domaine, jamais plus (aucune méthode, aucun comportement)."""

    name: str
    file: str
    domain: Domain


CANONICAL_COMPONENTS: Tuple[CanonicalComponent, ...] = (
    CanonicalComponent("StrategyAgent", "agents/strategy_agent.py", Domain.BUSINESS_EDITORIAL),
    CanonicalComponent("ContentAgent", "agents/content_agent.py", Domain.BUSINESS_EDITORIAL),
    CanonicalComponent("QualityAgent", "agents/quality_agent.py", Domain.BUSINESS_EDITORIAL),
    CanonicalComponent("PublishingAgent", "agents/publishing_agent.py", Domain.BUSINESS_EDITORIAL),
    CanonicalComponent("AnalyticsAgent", "agents/analytics_agent.py", Domain.BUSINESS_EDITORIAL),
    CanonicalComponent("OptimizationAgent", "agents/optimization_agent.py", Domain.BUSINESS_EDITORIAL),
    CanonicalComponent("BusinessPipelineOrchestrator", "agents/director_pipeline.py", Domain.BUSINESS_EDITORIAL),
    CanonicalComponent("MissionStateMachine", "agents/mission_state_machine.py", Domain.BUSINESS_EDITORIAL),
    CanonicalComponent("ScriptProductionBridge", "agents/script_production_bridge.py", Domain.PRODUCTION_MODELING),
    CanonicalComponent("VideoProductionPreparation", "agents/video_production_preparation.py", Domain.PRODUCTION_MODELING),
    CanonicalComponent("PreProductionReviewer", "agents/pre_production_review.py", Domain.PRODUCTION_MODELING),
    CanonicalComponent("ProductionReadinessHandoffBuilder", "agents/production_readiness_handoff.py", Domain.PRODUCTION_MODELING),
    CanonicalComponent("ProductionAuthorityIntake", "agents/production_authority_intake.py", Domain.PRODUCTION_MODELING),
    CanonicalComponent("HumanAuthorizationHandoffBuilder", "agents/human_authorization_handoff.py", Domain.PRODUCTION_MODELING),
    CanonicalComponent("ActivationEligibilityChecker", "agents/activation_eligibility.py", Domain.PRODUCTION_MODELING),
    CanonicalComponent("ProductionActivationHandoffBuilder", "agents/production_activation_handoff.py", Domain.PRODUCTION_MODELING),
    CanonicalComponent("ControlledActivationComposition", "agents/controlled_activation_composition.py", Domain.BRIDGE),
    CanonicalComponent("GenerationApprovalGate", "agents/generation_approval_gate.py", Domain.P2_AUTHORITY_CORE),
    CanonicalComponent("ReleaseCandidateIdentityLock", "agents/release_candidate_identity_lock.py", Domain.P2_AUTHORITY_CORE),
    CanonicalComponent("RequestScopedActivationService", "agents/activation_contract.py", Domain.P2_AUTHORITY_CORE),
    CanonicalComponent("ControlledRealProviderActivationService", "agents/controlled_real_provider_activation.py", Domain.P2_AUTHORITY_CORE),
    CanonicalComponent("FileCriticalSectionLock", "agents/critical_section_lock.py", Domain.P2_AUTHORITY_CORE),
    CanonicalComponent("FileExecutedRequestStore", "agents/executed_request_store.py", Domain.P2_AUTHORITY_CORE),
    CanonicalComponent("GenerationJobService", "agents/generation_job_service.py", Domain.P2_AUTHORITY_CORE),
    CanonicalComponent("HiggsfieldProvider", "integrations/higgsfield/provider.py", Domain.P2_AUTHORITY_CORE),
    CanonicalComponent("HiggsfieldClient", "integrations/higgsfield/client.py", Domain.P2_AUTHORITY_CORE),
    CanonicalComponent("TaskManager", "agents/task_manager.py", Domain.DISPATCH),
    CanonicalComponent("AIDirector", "director.py", Domain.ENTRY_POINT),
)


# ----------------------------------------------------------------------
# DÉPENDANCES INTERDITES (rapport P3.31 Section 7 A/B/C)
# ----------------------------------------------------------------------

# Domain A ne doit importer AUCUN de ces modules (préfixe de module
# Python tel qu'il apparaîtrait dans `from X import ...` / `import X`).
FORBIDDEN_IMPORT_PREFIXES_FOR_BUSINESS_EDITORIAL: FrozenSet[str] = frozenset(
    {
        "integrations.higgsfield",
        "agents.generation_job_service",
        "agents.generation_approval_gate",
        "agents.activation_contract",
        "agents.controlled_real_provider_activation",
        "agents.critical_section_lock",
        "agents.executed_request_store",
        "agents.real_provider_execution_gate",
        "agents.real_provider_activation_preflight",
        "agents.activation_readiness",
        "agents.final_report_service",
    }
)

# Domain B (+ le Bridge) peuvent importer certains TYPES P2 (déjà
# vérifié P3.28/P3.30 : RealGenerationAuthorization/GenerationRequest/
# RequestScopedActivationContract/ControlledRealProviderActivationContract
# comme références de type pour isinstance -- jamais pour construire).
# Aucun import de MODULE n'est cependant permis pour les mécanismes
# d'EXÉCUTION eux-mêmes : un import de ces préfixes signale un
# affaiblissement potentiel de la frontière P3.23.
FORBIDDEN_IMPORT_PREFIXES_FOR_PRODUCTION_MODELING: FrozenSet[str] = frozenset(
    {
        "agents.generation_job_service",
        "agents.critical_section_lock",
        "agents.executed_request_store",
        "agents.real_provider_execution_gate",
        "agents.real_provider_activation_preflight",
        "agents.activation_readiness",
        "agents.final_report_service",
        "integrations.higgsfield.provider",
        "integrations.higgsfield.client",
        "integrations.higgsfield.mock_provider",
    }
)


# ----------------------------------------------------------------------
# CONSTRUCTEURS/SYMBOLES PORTEURS D'AUTORITÉ -- surveillés par appel
# (ast.Call), jamais par simple import (rapport P3.31 Section 7 E/F/H).
# ----------------------------------------------------------------------

AUTHORITY_BEARING_SYMBOLS: FrozenSet[str] = frozenset(
    {
        "RealGenerationAuthorization",
        "RequestScopedActivationContract",
        "ControlledRealProviderActivationContract",
        "RequestScopedActivationService",
        "ControlledRealProviderActivationService",
        "GenerationApprovalGate",
        "GenerationJobService",
        "FileCriticalSectionLock",
        "FileExecutedRequestStore",
        "HiggsfieldProvider",
        "HiggsfieldClient",
    }
)

# Pour chaque symbole porteur d'autorité, l'ensemble EXHAUSTIF des
# fichiers dans lesquels une CONSTRUCTION (appel du constructeur) est
# légitime en production. Un appel trouvé n'importe où ailleurs, hors
# domaine TEST/SCRIPT, est un DRIFT. `RealGenerationAuthorization` n'a
# aucune entrée : elle ne doit JAMAIS être construite automatiquement
# nulle part en production (rapport P3.28-P3.30, confirmé de façon
# répétée) -- seul un humain, via un test ou `scripts/demo_test.py`
# (domaine SCRIPT, hors périmètre de ce contrôle), peut en construire une.
CONSTRUCTOR_ALLOWLIST: Mapping[str, FrozenSet[str]] = MappingProxyType({
    "RealGenerationAuthorization": frozenset(),
    "RequestScopedActivationContract": frozenset({"agents/activation_contract.py"}),
    "ControlledRealProviderActivationContract": frozenset(
        {"agents/controlled_real_provider_activation.py"}
    ),
    "RequestScopedActivationService": frozenset(
        {"agents/activation_contract.py", "director.py"}
    ),
    "ControlledRealProviderActivationService": frozenset(
        {"agents/controlled_real_provider_activation.py", "director.py"}
    ),
    "GenerationApprovalGate": frozenset({"director.py"}),
    "GenerationJobService": frozenset({"director.py", "agents/final_report_service.py"}),
    "FileCriticalSectionLock": frozenset({"director.py"}),
    "FileExecutedRequestStore": frozenset({"director.py"}),
    "HiggsfieldProvider": frozenset({"director.py", "integrations/higgsfield/provider.py"}),
    "HiggsfieldClient": frozenset(
        {
            "director.py",
            "integrations/higgsfield/provider.py",
            "integrations/higgsfield/client.py",
            "agents/cost_engine.py",
            "agents/planner.py",
        }
    ),
})

# Modules dont la présence, au sein d'un MÊME fichier NON classifié
# (Domain UNCLASSIFIED_LEGACY uniquement -- jamais A/B/Bridge, déjà
# couverts par leurs propres règles dédiées), constituerait le signal
# d'un second noyau d'autorité en formation (rapport P3.31 Section 7 G).
SECOND_AUTHORITY_CORE_SIGNAL_MODULES: FrozenSet[str] = frozenset(
    {
        "agents.generation_approval_gate",
        "agents.activation_contract",
        "agents.controlled_real_provider_activation",
        "agents.critical_section_lock",
        "agents.executed_request_store",
        "agents.generation_job_service",
    }
)
SECOND_AUTHORITY_CORE_SIGNAL_THRESHOLD = 2

# ----------------------------------------------------------------------
# CARDINALITÉ ATTENDUE DU POINT D'EXÉCUTION (rapport P3.31 Section 7 D/H)
# ----------------------------------------------------------------------

EXPECTED_CREATE_JOB_PRODUCTION_CALL_SITE_COUNT = 1
EXPECTED_CREATE_JOB_PRODUCTION_FILE = "agents/generation_job_service.py"

# Un fichier n'est considéré pour le décompte des call-sites `create_job`
# QUE s'il a un lien plausible avec le contrat Higgsfield réel (importe
# l'un de ces modules) OU appartient déjà à P2_AUTHORITY_CORE_FILES --
# ceci exclut correctement les homonymes sans rapport (ex.
# `agents/job_monitor.py::JobMonitor.create_job`, qui n'importe rien de
# Higgsfield) sans jamais les ignorer silencieusement : le détecteur les
# consigne séparément comme "hors périmètre, sans lien Higgsfield
# démontré" plutôt que de les compter ou de prétendre qu'ils n'existent
# pas.
CREATE_JOB_RELEVANCE_IMPORT_PREFIXES: FrozenSet[str] = frozenset(
    {
        "integrations.higgsfield.provider",
        "integrations.higgsfield.client",
        "integrations.higgsfield.mock_provider",
    }
)

# P3.77-R1 (G2, option B) : `HiggsfieldClient.create_job()` n'est qu'un
# enrobage de `run("generate", "create", ...)`. Tout `.run(...)` portant
# l'argument positionnel littéral "create" est donc un call-site de
# création au même titre que `create_job()` -- SAUF dans ce fichier, qui
# DÉFINIT ce verbe CLI : son `run(... "create" ...)` est le corps même de
# `HiggsfieldClient.create_job()`, déjà gouverné par la cardinalité de ses
# propres appelants (le compter en plus décompterait deux fois le même
# chemin). Aucune autre exception n'existe.
CLI_CREATE_VERB = "create"
CLI_CREATE_VERB_OWNER_FILE = "integrations/higgsfield/client.py"

# P3.78-R1 (G4-a/d) : méthodes d'autorité qui ne doivent JAMAIS quitter
# leur position d'appel (stockées, transmises, retournées, enregistrées,
# enveloppées dans `partial`...) -- seules formes non-appel tolérées : la
# comparaison d'identité `is`/`is not` (P3.68) et l'annotation. Liste
# FERMÉE (P3.68 + P3.78), jamais généralisée à toutes les méthodes.
AUTHORITY_CAPABILITY_METHOD_NAMES: FrozenSet[str] = frozenset(
    {
        "execute",
        "create_job",
        "run",
        "mark_executed",
        "mark_unknown",
        # P3.91 : write-ahead anti-rejeu (context manager pouvant
        # annuler son propre marqueur) -- jamais transmissible.
        "in_flight",
        "consume",
        "prepare_activation",
        "validate_activation",
    }
)


# ----------------------------------------------------------------------
# CERTIFICATE SUBSYSTEM <-> AUTHORITY SURFACE (rapport P3.62/P3.63) --
# built from the modules actually present on disk under this name
# pattern (verified, never assumed), not a newly invented catalogue.
# ----------------------------------------------------------------------

# CERTIFICATE POLICY (P3.75, "STRICT"): information is allowed by
# LOCATION, never by intent. On the authority surface
# (CERTIFICATE_GUARDRAIL_AUTHORITY_SURFACE_FILES) NO certificate use is
# allowed, even a log/audit/display -- an import, a verdict call or a
# verdict attribute read is a finding. Outside it, informational use
# (UI, audit, logging, report, serialization, tests) is free, provided
# the module does not ALSO reach the authority surface
# (CERTIFICATE_AUTHORITY_BRIDGE_MODULE). Static checks recognize
# imports and certificate vocabulary only; duck-typed or data-only
# (dict/str) flows are backstopped at runtime -- `execute()` and the
# Gate never accept a certificate.
CERTIFICATE_SUBSYSTEM_FILES: FrozenSet[str] = frozenset(
    {
        "agents/certificate_verification.py",
        "agents/certificate_integrity.py",
        "agents/certificate_lifecycle.py",
        "agents/certificate_lifecycle_store.py",
        "agents/certificate_lifecycle_lock.py",
        "agents/production_activation_readiness_certificate.py",
    }
)

# The purely-informational sub-layer (Phases P3.55-P3.60): verification,
# integrity, and lifecycle bookkeeping over an ALREADY-ISSUED
# certificate. Deliberately EXCLUDES
# agents/production_activation_readiness_certificate.py (the P3.54
# Issuer): that file's coupling to the P2 Authority Core (it composes
# `ActivationReadinessEvaluator`) is pre-existing, sanctioned
# architecture, already governed by `PROTECTED_P2_FILES`/
# `P2_AUTHORITY_CORE_FILES` since Phase P3.31/P3.54 -- folding it into
# THIS narrower guardrail (built for the P3.55-P3.60 layer that has, by
# design, zero legitimate reason to import any authority module) would
# produce a false positive on that legitimate, already-audited
# composition (rapport P3.63 Section 7/11, False Positive Analysis).
CERTIFICATE_INFORMATIONAL_LAYER_FILES: FrozenSet[str] = frozenset(
    {
        "agents/certificate_verification.py",
        "agents/certificate_integrity.py",
        "agents/certificate_lifecycle.py",
        "agents/certificate_lifecycle_store.py",
        "agents/certificate_lifecycle_lock.py",
    }
)

# The authority surface a certificate must never reach (rapport P3.62
# Section 4/6-15, P3.63 Section 4) -- composed EXCLUSIVELY from
# pre-existing canonical domain sets already defined above (never a
# newly invented file list): every P2 Authority Core file, every
# Production Modeling file (the human-authorization/production-
# activation boundary chain P3.62 audited, even though Domain B holds
# no authority of its own per this contract's own module docstring),
# and the entry point.
CERTIFICATE_GUARDRAIL_AUTHORITY_SURFACE_FILES: FrozenSet[str] = (
    P2_AUTHORITY_CORE_FILES | PRODUCTION_MODELING_FILES | ENTRY_POINT_FILES
)


def _dotted(file_path: str) -> str:
    return file_path[:-3].replace("/", ".")


# Direction 1 (Section 5, "authority must never import a certificate"):
# every dotted module the certificate subsystem exposes.
CERTIFICATE_SUBSYSTEM_IMPORT_PREFIXES: FrozenSet[str] = frozenset(
    _dotted(f) for f in CERTIFICATE_SUBSYSTEM_FILES
)

# Direction 2 (Section 5, "the informational layer must never import
# authority"): the full authority surface MINUS the certificate
# subsystem's own files -- the P3.54 Issuer's certificate type is
# legitimate vocabulary for this layer, never "authority" being guarded
# against (see CERTIFICATE_INFORMATIONAL_LAYER_FILES docstring above).
CERTIFICATE_OUTBOUND_FORBIDDEN_IMPORT_PREFIXES: FrozenSet[str] = frozenset(
    _dotted(f) for f in (CERTIFICATE_GUARDRAIL_AUTHORITY_SURFACE_FILES - CERTIFICATE_SUBSYSTEM_FILES)
)

# Method/function names that, called FROM the certificate subsystem's
# purely informational layer, would mean that layer reached into the P2
# execution/authority boundary (rapport P3.62 Section 10 -- the same
# denylist that phase's ad-hoc test already used, now enforced
# permanently by the detector itself).
CERTIFICATE_FORBIDDEN_AUTHORITY_CALL_NAMES: FrozenSet[str] = frozenset(
    {"execute", "create_job", "mark_executed", "prepare_activation", "validate_activation"}
)

# Consumer side (rapport P3.70, "Authority interpretation isolation"):
# the import-edge checks above miss an authority-surface file that
# INTERPRETS a certificate verdict on a duck-typed object it never
# imports (`if certificate.is_ready(): return APPROVED`). These call
# names are certificate-verdict vocabulary -- each one is defined only
# by the certificate subsystem, and none is called anywhere on the
# authority surface (verified in P3.70, never assumed). Deliberately
# excludes generic names (`is_valid`, `decision`, `result`) that
# authority code legitimately uses for its own verdicts.
CERTIFICATE_VERDICT_CALL_NAMES: FrozenSet[str] = frozenset(
    {
        "is_ready",
        "is_trustworthy_and_current",
        "certificate_still_matches",
        "verify_certificate",
        "verify_certificate_provenance_and_integrity",
        "verify_integrity",
        "verify_provenance",
        "status_of",
        "current_record_for",
        # P3.73: same id/scope-keyed lifecycle lookups as `status_of`,
        # spelled differently -- `registry.record_for(cid).status` evaded
        # the rule (`.status` is deliberately generic, see below).
        "record_for",
        "history_for",
    }
)

# Attribute-read counterpart of the call vocabulary above (rapport
# P3.71): `certificate.is_ready` / `.readiness_result` /
# `.readiness_report` read WITHOUT a call evaded the P3.70 rule --
# `if certificate.is_ready:` is even always true (a bound method).
# Every name is a field/method owned by the certificate subsystem and
# none is read anywhere on the authority surface (verified in P3.71).
# Generic names shared with authority code (`status`, `decision`,
# `approval_decision`, `unknown_state`) are deliberately excluded.
CERTIFICATE_VERDICT_ATTRIBUTE_NAMES: FrozenSet[str] = frozenset(
    {
        "is_ready",
        "is_trustworthy_and_current",
        "readiness_result",
        "readiness_report",
        "blocking_reasons",
        "certificate_id",
        "superseded_by",
        "provenance_result",
        "integrity_result",
        "freshness_result",
    }
)

# The files that MAKE or ENFORCE the approval/activation/execution
# decision (rapport P3.70, Fixture B). They must never import a
# readiness-verdict module: `ActivationReadinessReport` -- the very
# report a certificate embeds -- is observation, never authorization
# (Phase P2.24). The two sanctioned readiness consumers
# (`real_provider_execution_gate.py`, `director.py`) always evaluate a
# FRESH report themselves and are deliberately not in this set.
READINESS_VERDICT_FORBIDDEN_CONSUMER_FILES: FrozenSet[str] = frozenset(
    {
        "agents/generation_approval_gate.py",
        "agents/generation_job_service.py",
        "agents/activation_contract.py",
        "agents/controlled_real_provider_activation.py",
        "integrations/higgsfield/provider.py",
    }
)
READINESS_VERDICT_MODULE_PREFIXES: FrozenSet[str] = frozenset(
    {"agents.activation_readiness", "agents.real_provider_execution_gate"}
)


@dataclass(frozen=True)
class CanonicalArchitectureContract:
    """
    Snapshot IMMUABLE et PUREMENT DOCUMENTAIRE/COMPARATIF de
    l'architecture canonique validée en P3.28/P3.29/P3.30. Ne contient
    aucune méthode qui déciderait, activerait ou exécuterait quoi que ce
    soit -- uniquement des données que `architecture_drift_detector.py`
    compare à la réalité du code.
    """

    version: int = CONTRACT_VERSION
    business_editorial_files: FrozenSet[str] = field(default_factory=lambda: BUSINESS_EDITORIAL_FILES)
    production_modeling_files: FrozenSet[str] = field(default_factory=lambda: PRODUCTION_MODELING_FILES)
    bridge_files: FrozenSet[str] = field(default_factory=lambda: BRIDGE_FILES)
    p2_authority_core_files: FrozenSet[str] = field(default_factory=lambda: P2_AUTHORITY_CORE_FILES)
    protected_p2_files: FrozenSet[str] = field(default_factory=lambda: PROTECTED_P2_FILES)
    dispatch_files: FrozenSet[str] = field(default_factory=lambda: DISPATCH_FILES)
    entry_point_files: FrozenSet[str] = field(default_factory=lambda: ENTRY_POINT_FILES)
    canonical_components: Tuple[CanonicalComponent, ...] = field(default_factory=lambda: CANONICAL_COMPONENTS)
    forbidden_import_prefixes_for_business_editorial: FrozenSet[str] = field(
        default_factory=lambda: FORBIDDEN_IMPORT_PREFIXES_FOR_BUSINESS_EDITORIAL
    )
    forbidden_import_prefixes_for_production_modeling: FrozenSet[str] = field(
        default_factory=lambda: FORBIDDEN_IMPORT_PREFIXES_FOR_PRODUCTION_MODELING
    )
    authority_bearing_symbols: FrozenSet[str] = field(default_factory=lambda: AUTHORITY_BEARING_SYMBOLS)
    constructor_allowlist: Mapping[str, FrozenSet[str]] = field(default_factory=lambda: CONSTRUCTOR_ALLOWLIST)
    second_authority_core_signal_modules: FrozenSet[str] = field(
        default_factory=lambda: SECOND_AUTHORITY_CORE_SIGNAL_MODULES
    )
    second_authority_core_signal_threshold: int = SECOND_AUTHORITY_CORE_SIGNAL_THRESHOLD
    expected_create_job_production_call_site_count: int = EXPECTED_CREATE_JOB_PRODUCTION_CALL_SITE_COUNT
    expected_create_job_production_file: str = EXPECTED_CREATE_JOB_PRODUCTION_FILE
    create_job_relevance_import_prefixes: FrozenSet[str] = field(
        default_factory=lambda: CREATE_JOB_RELEVANCE_IMPORT_PREFIXES
    )
    cli_create_verb: str = CLI_CREATE_VERB
    cli_create_verb_owner_file: str = CLI_CREATE_VERB_OWNER_FILE
    authority_capability_method_names: FrozenSet[str] = field(
        default_factory=lambda: AUTHORITY_CAPABILITY_METHOD_NAMES
    )
    bridge_entry_method: str = BRIDGE_ENTRY_METHOD
    bridge_delegate_method: str = BRIDGE_DELEGATE_METHOD
    certificate_subsystem_files: FrozenSet[str] = field(default_factory=lambda: CERTIFICATE_SUBSYSTEM_FILES)
    certificate_informational_layer_files: FrozenSet[str] = field(
        default_factory=lambda: CERTIFICATE_INFORMATIONAL_LAYER_FILES
    )
    certificate_guardrail_authority_surface_files: FrozenSet[str] = field(
        default_factory=lambda: CERTIFICATE_GUARDRAIL_AUTHORITY_SURFACE_FILES
    )
    certificate_subsystem_import_prefixes: FrozenSet[str] = field(
        default_factory=lambda: CERTIFICATE_SUBSYSTEM_IMPORT_PREFIXES
    )
    certificate_outbound_forbidden_import_prefixes: FrozenSet[str] = field(
        default_factory=lambda: CERTIFICATE_OUTBOUND_FORBIDDEN_IMPORT_PREFIXES
    )
    certificate_forbidden_authority_call_names: FrozenSet[str] = field(
        default_factory=lambda: CERTIFICATE_FORBIDDEN_AUTHORITY_CALL_NAMES
    )
    certificate_verdict_call_names: FrozenSet[str] = field(
        default_factory=lambda: CERTIFICATE_VERDICT_CALL_NAMES
    )
    certificate_verdict_attribute_names: FrozenSet[str] = field(
        default_factory=lambda: CERTIFICATE_VERDICT_ATTRIBUTE_NAMES
    )
    readiness_verdict_forbidden_consumer_files: FrozenSet[str] = field(
        default_factory=lambda: READINESS_VERDICT_FORBIDDEN_CONSUMER_FILES
    )
    readiness_verdict_module_prefixes: FrozenSet[str] = field(
        default_factory=lambda: READINESS_VERDICT_MODULE_PREFIXES
    )

    def domain_of(self, relative_path: str) -> Domain:
        """
        Classifie un chemin de fichier (relatif à la racine du
        repository, séparateurs `/`) selon l'architecture canonique.
        PURE, aucun accès disque : ne fait que comparer `relative_path`
        aux ensembles ci-dessus. `tests/` et `scripts/` sont reconnus
        par préfixe de chemin (pas de liste exhaustive nécessaire, ces
        répertoires n'appartiennent structurellement à aucun domaine
        d'autorité) ; tout le reste, hors domaines nommés, est
        UNCLASSIFIED_LEGACY -- jamais fusionné avec un domaine réel par
        défaut.
        """

        normalized = relative_path.replace("\\", "/")

        if normalized.startswith("tests/"):
            return Domain.TEST
        if normalized.startswith("scripts/"):
            return Domain.SCRIPT
        if normalized in self.business_editorial_files:
            return Domain.BUSINESS_EDITORIAL
        if normalized in self.production_modeling_files:
            return Domain.PRODUCTION_MODELING
        if normalized in self.bridge_files:
            return Domain.BRIDGE
        if normalized in self.p2_authority_core_files:
            return Domain.P2_AUTHORITY_CORE
        if normalized in self.dispatch_files:
            return Domain.DISPATCH
        if normalized in self.entry_point_files:
            return Domain.ENTRY_POINT

        return Domain.UNCLASSIFIED_LEGACY


CANONICAL_ARCHITECTURE_CONTRACT = CanonicalArchitectureContract()
