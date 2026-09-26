"""
AI DIRECTOR — Production Activation Boundary Contract (Phase P2.25,
MASTER PROMPT V2)

Formalise, en UN SEUL endroit inspectable et testable, la frontière
exacte entre "le système est techniquement prêt" (Phase P2.24) et "un
job Higgsfield réel pourrait être créé". Ce module N'ACTIVE RIEN,
NE CRÉE RIEN, ET N'APPELLE JAMAIS `create_job()` -- il documente
uniquement, sous une forme que les tests peuvent vérifier
automatiquement (jamais de la prose qui pourrait dériver de la
réalité sans que rien ne le remarque).

LA FRONTIÈRE ELLE-MÊME, AUJOURD'HUI :

    PRODUCTION ACTIVATION BOUNDARY
             |
             v
    HiggsfieldProvider.create_job()
             |
             v
    HiggsfieldRealGenerationDisabledError   (Phase C/D, inchangé)

Cette barrière reste, à ce jour, la SEULE chose qui empêche une
génération réelle une fois toutes les autres conditions réunies —
elle n'est ni modifiée ni affaiblie par ce module.

TROIS NIVEAUX D'AUTORITÉ (Étape 4 du rapport P2.25) -- jamais
fusionnés, jamais convertibles implicitement l'un dans l'autre :

    Niveau 1 -- TECHNICAL_READINESS
        Produit par `ActivationReadinessEvaluator` (Phase P2.24).
        Répond uniquement : "le système satisfait-il les
        préconditions techniques connues ?" Ne donne AUCUNE autorité
        de génération.

    Niveau 2 -- HUMAN_AUTHORIZATION
        Représenté par `RealGenerationAuthorization` (Phase P2.11).
        Explicite, lié à un `request_id`, jamais dérivé de
        `GenerationRequest.approved`, jamais créé par un composant
        automatique (Director/Planner/VideoAgent/TaskManager/
        ActivationReadinessEvaluator).

    Niveau 3 -- REQUEST_SCOPED_ACTIVATION
        Représenté par `RequestScopedActivationContract` (Phase
        P2.21). Request-scoped, param-scoped, single-use, expirant,
        lié à l'autorisation, vérifié fraîchement, protégé par
        Identity Lock.

    Niveau 4 -- EXECUTION
        `GenerationJobService.execute()` (Phase H/P2.20/P2.22) --
        SEUL point qui appelle réellement `provider.create_job()`,
        et UNIQUEMENT après ré-vérification fraîche de TOUT ce qui
        précède, DANS le verrou de section critique.

RÈGLE FONDAMENTALE (Étape 5) :

    READINESS != AUTHORIZATION
    AUTHORIZATION != ACTIVATION
    ACTIVATION != EXECUTION
    EXECUTION != QUALITY SUCCESS

Aucune conversion implicite entre ces niveaux n'existe dans ce
module ni ailleurs dans le pipeline -- vérifié structurellement par
`tests/test_phase_p2_25_production_activation_boundary.py`.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Tuple


class AuthorityLevel(str, Enum):
    """Les quatre niveaux d'autorité STRICTEMENT distincts (Étape 4)."""

    TECHNICAL_READINESS = "TECHNICAL_READINESS"
    HUMAN_AUTHORIZATION = "HUMAN_AUTHORIZATION"
    REQUEST_SCOPED_ACTIVATION = "REQUEST_SCOPED_ACTIVATION"
    EXECUTION = "EXECUTION"


# Étape 12 du rapport P2.25 -- les 20 vérifications qu'une FUTURE
# exécution réelle devra TOUTES refaire, fraîchement, immédiatement
# avant tout appel à create_job() : aucune décision antérieure
# (readiness, authorization, activation) ne peut en dispenser une
# seule. Un item par requirement, jamais fusionné.
FRESH_CHECK_REQUIREMENTS: Tuple[str, ...] = (
    "request_identity",
    "model",
    "duration",
    "resolution",
    "aspect_ratio",
    "prompt_sha256",
    "asset_sha256",
    "cost",
    "live_balance",
    "technical_approval",
    "human_authorization",
    "authorization_request_binding",
    "activation_contract",
    "activation_expiry",
    "activation_single_use_state",
    "replay_state",
    "unknown_state",
    "identity_lock",
    "critical_section",
    "provider_activation_state",
)


# Fait le lien entre chaque exigence de la checklist ci-dessus et le
# mécanisme RÉEL qui l'implémente déjà aujourd'hui dans ce projet --
# jamais une simple affirmation textuelle : `tests/test_phase_p2_25_
# production_activation_boundary.py` vérifie que CHAQUE référence
# pointe vers un attribut/méthode qui existe RÉELLEMENT dans le code,
# afin que cette documentation ne puisse jamais dériver de la réalité
# sans qu'un test ne le détecte.
FRESH_CHECK_IMPLEMENTED_BY: Dict[str, str] = {
    "request_identity": "agents.release_candidate_identity_lock.ReleaseCandidateIdentityLock.violations",
    "model": "agents.release_candidate_identity_lock.ReleaseCandidateIdentityLock.violations",
    "duration": "agents.release_candidate_identity_lock.ReleaseCandidateIdentityLock.violations",
    "resolution": "agents.release_candidate_identity_lock.ReleaseCandidateIdentityLock.violations",
    "aspect_ratio": "agents.release_candidate_identity_lock.ReleaseCandidateIdentityLock.violations",
    "prompt_sha256": "agents.release_candidate_identity_lock.ReleaseCandidateIdentityLock.violations",
    "asset_sha256": "agents.release_candidate_identity_lock.ReleaseCandidateIdentityLock.violations",
    "cost": "agents.generation_cost_service.GenerationCostService.estimate",
    "live_balance": "integrations.higgsfield.provider.BaseHiggsfieldProvider.get_account_balance",
    "technical_approval": "agents.generation_approval_gate.GenerationApprovalGate.evaluate",
    "human_authorization": "agents.generation_approval_gate.GenerationApprovalGate._human_authorization_reasons",
    "authorization_request_binding": "agents.generation_approval_gate.GenerationApprovalGate._human_authorization_reasons",
    "activation_contract": "agents.activation_contract.RequestScopedActivationService.validate_activation",
    "activation_expiry": "agents.activation_contract.RequestScopedActivationService._activation_violations",
    "activation_single_use_state": "agents.activation_contract.RequestScopedActivationService._activation_violations",
    "replay_state": "agents.generation_approval_gate.GenerationApprovalGate.evaluate",
    "unknown_state": "agents.generation_approval_gate.GenerationApprovalGate.evaluate",
    "identity_lock": "agents.release_candidate_identity_lock.ReleaseCandidateIdentityLock.violations",
    "critical_section": "agents.critical_section_lock.FileCriticalSectionLock.acquire",
    "provider_activation_state": "integrations.higgsfield.provider.HiggsfieldProvider.create_job",
}


# Étape 14 -- motifs qui constitueraient une "autorité globale"
# illégitime s'ils apparaissaient dans le code de production. Cette
# liste EST le contrat négatif : aucun de ces motifs ne doit jamais
# exister dans agents/, integrations/ ou director.py (cf. le test
# dédié, qui grep le repository réel plutôt que de faire confiance à
# cette liste seule).
FORBIDDEN_GLOBAL_AUTHORITY_TOKENS: Tuple[str, ...] = (
    "REAL_GENERATION_ENABLED",
    "HIGGSFIELD_ENABLED",
    "PRODUCTION_MODE",
    "FORCE_GENERATION",
    "enabled=True",
    "real_generation_enabled",
    "force_generate",
    "skip_gate",
    "bypass",
    "auto_authorize",
    "auto_activation",
    "generate_now",
    "direct_provider",
)


@dataclass(frozen=True)
class ProductionActivationBoundaryContract:
    """
    Snapshot IMMUABLE et PUREMENT DOCUMENTAIRE de la frontière
    d'activation. Ne contient aucune méthode qui déciderait, activerait
    ou exécuterait quoi que ce soit -- uniquement des données que les
    tests peuvent comparer à la réalité du code.
    """

    authority_levels: Tuple[AuthorityLevel, ...] = (
        AuthorityLevel.TECHNICAL_READINESS,
        AuthorityLevel.HUMAN_AUTHORIZATION,
        AuthorityLevel.REQUEST_SCOPED_ACTIVATION,
        AuthorityLevel.EXECUTION,
    )
    fresh_check_requirements: Tuple[str, ...] = FRESH_CHECK_REQUIREMENTS
    forbidden_global_authority_tokens: Tuple[str, ...] = FORBIDDEN_GLOBAL_AUTHORITY_TOKENS

    # Vérité actuelle, non modifiable par ce contrat : le Provider
    # réel reste désactivé. `True` ici documente un FAIT du code
    # (integrations/higgsfield/provider.py), jamais une décision prise
    # par ce module.
    real_provider_currently_disabled: bool = True


PRODUCTION_ACTIVATION_BOUNDARY = ProductionActivationBoundaryContract()
