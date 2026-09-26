"""
AI DIRECTOR — Production Activation Handoff (Phase P3.21)

HANDOFF BOUNDARY ONLY, built directly against the REAL contracts
re-read from disk before writing a line of this module: `agents/
activation_eligibility.py` (P3.20, `ActivationEligibilityChecker.
check_eligibility()` -> `ActivationEligibilityResult`, carrying
`human_authorization_handoff` (`HumanAuthorizationHandoff`, P3.19)
verbatim), and the full existing P2 activation/execution chain
re-audited from disk this phase: `agents/activation_contract.py`
(Phase P2.21), `agents/controlled_real_provider_activation.py` (Phase
P2.26), `agents/real_provider_execution_gate.py` (Phase P2.36),
`agents/real_provider_activation_preflight.py` (Phase P2.37), `agents/
generation_job_service.py` (Phase H/P2.20/22/27), `agents/generation_
approval_gate.py` (Phase G/P2.11), `agents/critical_section_lock.py`
(Phase P2.20), `agents/executed_request_store.py` (Phase P2.15),
`integrations/higgsfield/provider.py`/`client.py`, and `director.py`
(`AIDirector.prepare_real_generation_activation()`/`execute_real_
generation_activation()`, Phase P2.29 -- the pre-existing entry points
that actually construct/consume activation contracts and execute,
never duplicated or invoked here).

RESPONSIBILITY (Section 4/5): given a P3.20 `ActivationEligibility
Result`, and OPTIONAL caller-supplied identity-lock traceability data
(never computed by this module), package a single, immutable, fully
traceable `ProductionActivationHandoff` record -- the LAST handoff
object before a future, separately-authorized "Controlled Activation /
Execution" phase -- and STOP. This module never activates, never
executes, never constructs or consumes any P2 activation contract, and
never calls the P2 chain at all (`GenerationApprovalGate`,
`RequestScopedActivationService`, `ControlledRealProviderActivation
Service`, `GenerationJobService`) -- same "never touch the Gate/
Provider, even read-only" lesson P3.18/P3.19/P3.20 already established.
`ProductionActivationHandoffStatus` has exactly two values --
`NOT_ELIGIBLE_FOR_HANDOFF`, `ACTIVATION_HANDOFF_READY` -- deliberately
never `ACTIVATED`, `EXECUTING`, or `EXECUTED` (Section 9's "do not
collapse these states"; Section 4's full state chain: HUMAN_
AUTHORIZATION_VALID -> ACTIVATION_ELIGIBLE -> ACTIVATION_HANDOFF_READY
-> ACTIVATED -> EXECUTING -> EXECUTED -- this module produces ONLY the
third state, never any later one).

NAMING DECISION (Section 5's "avoid a collision with existing
contracts", audited this phase): a repository-wide search for every
`class \\w*(Activation|Handoff|Production)\\w*` definition found no
existing `ProductionActivationHandoff` (nor any V2/duplicate-authority
name) -- `agents/production_activation_boundary.py` (Phase P2.25)
defines a DIFFERENT, static, non-per-request `ProductionActivation
BoundaryContract` (four `AuthorityLevel`s: TECHNICAL_READINESS,
HUMAN_AUTHORIZATION, REQUEST_SCOPED_ACTIVATION, EXECUTION -- a
documentation/test-verification contract, never a per-request handoff
object) that this module does not duplicate or modify. Section 9's own
diagram names the positive state `ACTIVATION_HANDOFF_READY` (used
verbatim here as the enum value) while Section 4 also uses the phrase
"ACTIVATION_AUTHORITY_GRANTED" informally -- this module treats
`ACTIVATION_HANDOFF_READY` as authoritative (it is the literal state-
chain vocabulary in Section 9, and "authority granted" would risk
being misread as an actual grant of activation authority, which this
module never performs). The Director entry point is named `production_
activation_handoff()`, matching the established naming convention of
every sibling entry point this phase builds on (`human_authorization_
handoff()`, `production_authority_intake()`, `activation_eligibility()`
-- all noun-phrase names, deliberately NOT prefixed `prepare_`, to
avoid any naming collision or reader confusion with the real, side-
effecting `AIDirector.prepare_real_generation_activation()`, Phase
P2.29, which this module never calls).

WHY THIS MODULE NEVER CALLS ANY P2 METHOD, MUTATING OR NOT (Section 0/
7/8 -- the single most important rule of this phase, carried forward
unchanged from P3.18/P3.19/P3.20): every P2 read method this module
could theoretically call (`GenerationApprovalGate.evaluate()`,
`RequestScopedActivationService.inspect_activation()`, `Controlled
RealProviderActivationService.inspect()`, `ActivationReadinessEvaluator.
evaluate()`, `RealProviderExecutionGate.evaluate()`) transitively
reaches `HiggsfieldClient.get_account_balance()`/`estimate_cost()` --
real CLI subprocess calls -- via `_fresh_violations()`/`gate.evaluate()`
internally. Per Section 8's "STRUCTURAL / FROZEN DATA ONLY, comme
P3.18" and Section 7's explicit list of forbidden calls
(`prepare_real_generation_activation()` if it mutates state,
`execute_real_generation_activation()`, `.consume()`, `create_job()`,
`GenerationJobService.execute()`, the real provider, the real client),
this module performs ONLY structural, offline, zero-I/O checks on
ALREADY-COMPUTED, immutable P3.15-P3.20 objects -- the same pattern
established, independently, at every P3.17-P3.20 layer. `identity_
lock_violations` (Section 5's "identity-lock status", Section 10's
"Les Identity Locks P2 restent autoritatifs") is therefore accepted
ONLY as an OPTIONAL, externally-supplied, already-computed snapshot
(`Optional[Tuple[str, ...]]`, `None` meaning "not checked by the
caller") -- this module NEVER constructs or calls a `ReleaseCandidate
IdentityLock` itself (that would require real file I/O against the
Release Candidate's actual asset files, a live P2.18 check this module
never re-executes, only records for traceability if the caller already
ran it). A non-empty tuple (violations present) always forces
`NOT_ELIGIBLE_FOR_HANDOFF`, never silently ignored.

CORRELATION/CAUSATION (Section 5's "si déjà supportée"): audited this
phase -- no existing P2 or P3 contract in this repository defines a
correlation_id/causation_id concept anywhere. Per Section 3's "ne pas
inventer une architecture V2" (and the same discipline applied
throughout every P3.15-P3.20 module docstring: never invent a new
identity/versioning concept the real architecture does not already
have), this module does NOT introduce one. The full causal chain
remains reachable, in order, through the embedded `eligibility ->
human_authorization_handoff -> intake -> handoff -> review ->
production_preparation -> script_artifact` object graph itself -- the
existing, real provenance mechanism, never duplicated by a new
identifier scheme.

NO EXECUTION / NO ACTIVATION / NO AUTOMATIC AUTHORIZATION (Section 0/
6/7): this module never imports `agents.generation_approval_gate.
GenerationApprovalGate`, `agents.generation_job_service.
GenerationJobService`, `agents.activation_contract.
RequestScopedActivationService`, `agents.controlled_real_provider_
activation.ControlledRealProviderActivationService`, `agents.
activation_readiness`, `agents.real_provider_execution_gate`, `agents.
real_provider_activation_preflight`, `agents.critical_section_lock`,
`agents.executed_request_store`, `agents.release_candidate_identity_
lock`, `integrations.higgsfield.provider.HiggsfieldProvider`,
`integrations.higgsfield.client.HiggsfieldClient`, or `agents.mission_
state_machine`, and never calls `create_job`, `.evaluate(`, `.execute(`,
`.transition(`, `prepare_activation`, `validate_activation`,
`.consume(`, `.prepare(`, `.validate(`, `prepare_real_generation_
activation`, or `execute_real_generation_activation`. `RealGeneration
Authorization` is not even importable from this module's own dependency
chain: `HumanAuthorizationHandoff` (P3.19) already exposes only the
opaque `authorization_id` string, never the authorization object itself
-- this module therefore has no field, and no possible code path, that
could ever reconstruct or reference one, let alone construct one
automatically from `approved=True`/a valid handoff/eligibility/READY
state (Section 6's absolute rule).

IMMUTABILITY / DETERMINISM / IDEMPOTENCY (Section 5/13, mirrors every
P3.17-P3.20 module's own discipline): this module never imports
`dataclasses.replace` and never assigns to any attribute of
`ActivationEligibilityResult`, `HumanAuthorizationHandoff`,
`ProductionAuthorityIntakeReport`, `ProductionReadinessHandoff`,
`PreProductionReview`, `GenerationRequest`, `RequestScopedActivation
Contract`, or `ControlledRealProviderActivationContract` -- all frozen
anyway. `build()` is a pure function of its input: identical immutable
input always yields findings/status/`content_hash` that are equal by
value. No production side effect of any kind occurs, ever, regardless
of how many times the same input is handed off.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional, Tuple

from agents.activation_eligibility import (
    ELIGIBILITY_ARTIFACT_TYPE,
    ELIGIBILITY_CONTRACT_VERSION,
    ActivationEligibilityResult,
    ActivationEligibilityStatus,
    compute_activation_eligibility_hash,
)

HANDOFF_CONTRACT_VERSION = 1
HANDOFF_ARTIFACT_TYPE = "ProductionActivationHandoff"
PRODUCER_AGENT = "production-activation-handoff"
PRODUCER_VERSION = "1.0"

SUPPORTED_ELIGIBILITY_CONTRACT_VERSIONS = frozenset({ELIGIBILITY_CONTRACT_VERSION})

# Eligibility statuses (Phase P3.20) that may legitimately proceed to a
# production activation handoff -- both represent "human authorization
# valid" outcomes, distinguished only by whether an activation snapshot
# was already supplied at that layer. Neither means activated/executed.
_ELIGIBLE_UPSTREAM_STATUSES = frozenset(
    {
        ActivationEligibilityStatus.ELIGIBLE_FOR_ACTIVATION,
        ActivationEligibilityStatus.ACTIVATION_CONTRACT_STRUCTURALLY_VALID,
    }
)


class ProductionActivationHandoffError(ValueError):
    """Raised for a structurally invalid `ProductionActivationHandoff
    Input` (e.g. `eligibility` is not a real `ActivationEligibility
    Result`) -- never a silent fallback."""


class ProductionActivationHandoffStatus(str, Enum):
    """
    Exactly two values, deliberately never `ACTIVATED`, `EXECUTING`, or
    `EXECUTED` (Section 4/9) -- this handoff can only ever say whether
    it is structurally complete and traceable, or not -- never anything
    about activation or execution itself.
    """

    NOT_ELIGIBLE_FOR_HANDOFF = "NOT_ELIGIBLE_FOR_HANDOFF"
    ACTIVATION_HANDOFF_READY = "ACTIVATION_HANDOFF_READY"


class HandoffFailureCategory(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"
    ELIGIBILITY_INTEGRITY_FAILURE = "ELIGIBILITY_INTEGRITY_FAILURE"
    CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
    ACTIVATION_NOT_ELIGIBLE = "ACTIVATION_NOT_ELIGIBLE"
    IDENTITY_LOCK_VIOLATION = "IDENTITY_LOCK_VIOLATION"
    STALE_OR_MISMATCHED_HANDOFF = "STALE_OR_MISMATCHED_HANDOFF"
    INTERNAL_HANDOFF_FAILURE = "INTERNAL_HANDOFF_FAILURE"


# ----------------------------------------------------------------------
# INPUT CONTRACT (Section 5/10)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ProductionActivationHandoffInput:
    eligibility: ActivationEligibilityResult

    # OPTIONAL, externally-computed identity-lock snapshot (Section 5's
    # "identity-lock status") -- NEVER computed by this module (see
    # module docstring). `None` means "not checked by the caller";
    # `()` means "checked, zero violations"; a non-empty tuple always
    # forces NOT_ELIGIBLE_FOR_HANDOFF.
    identity_lock_violations: Optional[Tuple[str, ...]] = None

    # Optional caller-supplied canonical expected values (mirrors the
    # expected_*_id pattern established at every P3.17-P3.20 layer) --
    # NEVER fabricated internally.
    expected_eligibility_id: Optional[str] = None
    expected_request_id: Optional[str] = None

    handoff_id: Optional[str] = None
    clock: Optional[Callable[[], str]] = None


# ----------------------------------------------------------------------
# OUTPUT CONTRACT -- immutable.
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class HandoffFinding:
    dimension: str
    passed: bool
    detail: str
    category: Optional[HandoffFailureCategory] = None  # None iff passed


@dataclass(frozen=True)
class ProductionActivationHandoff:
    handoff_id: str
    artifact_type: str
    created_at: str
    contract_version: int

    request_id: Optional[str]
    mission_id: str
    review_id: str
    intake_id: str
    human_authorization_handoff_id: str
    eligibility_id: str

    status: ProductionActivationHandoffStatus
    findings: Tuple[HandoffFinding, ...]
    reasons: Tuple[str, ...]  # detail of every failing finding, in order

    eligibility: ActivationEligibilityResult  # verbatim, never rewritten
    # -- full chain (mission_id -> script_artifact -> production_
    # preparation -> generation_request -> review -> handoff -> intake
    # -> human_authorization_handoff -> eligibility) is reachable
    # through this single field.

    authorization_id: Optional[str]  # opaque UUID only, mirrored
    # verbatim from human_authorization_handoff.authorization_id --
    # never the RealGenerationAuthorization object itself (which this
    # module has no way to reach at all, see module docstring).

    identity_lock_checked: bool
    identity_lock_violations: Tuple[str, ...]  # empty iff no violations
    # were supplied, or the caller supplied an empty tuple; NEVER
    # computed here.

    producer_agent: str
    producer_version: str

    content_hash: str


def _default_clock() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_production_activation_handoff_hash(
    request_id: Optional[str],
    mission_id: str,
    review_id: str,
    intake_id: str,
    human_authorization_handoff_id: str,
    eligibility_id: str,
    status: str,
    findings: Tuple[HandoffFinding, ...],
    eligibility_content_hash: str,
    authorization_id: Optional[str],
    identity_lock_violations: Tuple[str, ...],
    contract_version: int,
) -> str:
    canonical = {
        "request_id": request_id,
        "mission_id": mission_id,
        "review_id": review_id,
        "intake_id": intake_id,
        "human_authorization_handoff_id": human_authorization_handoff_id,
        "eligibility_id": eligibility_id,
        "status": status,
        "findings": [
            {
                "dimension": f.dimension,
                "passed": f.passed,
                "detail": f.detail,
                "category": f.category.value if f.category is not None else None,
            }
            for f in findings
        ],
        "eligibility_content_hash": eligibility_content_hash,
        "authorization_id": authorization_id,
        "identity_lock_violations": list(identity_lock_violations),
        "contract_version": contract_version,
    }
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# ELIGIBILITY-LEVEL DIMENSIONS (Section 10) -- re-verify the P3.20
# eligibility result's own structural validity at this layer, never
# re-deriving P3.15-P3.20's own business logic.
# ----------------------------------------------------------------------


def _check_eligibility_structural_validity(eligibility: ActivationEligibilityResult) -> HandoffFinding:
    if eligibility.artifact_type != ELIGIBILITY_ARTIFACT_TYPE:
        return HandoffFinding(
            "eligibility_structural_validity", False,
            f"eligibility.artifact_type '{eligibility.artifact_type}' is "
            f"not '{ELIGIBILITY_ARTIFACT_TYPE}'.",
            HandoffFailureCategory.INVALID_INPUT,
        )
    if not isinstance(eligibility.eligibility_id, str) or not eligibility.eligibility_id.strip():
        return HandoffFinding(
            "eligibility_structural_validity", False,
            f"eligibility.eligibility_id is missing or empty "
            f"({eligibility.eligibility_id!r}).",
            HandoffFailureCategory.INVALID_INPUT,
        )
    return HandoffFinding("eligibility_structural_validity", True, f"eligibility_id='{eligibility.eligibility_id}'.")


def _check_eligibility_contract_version(eligibility: ActivationEligibilityResult) -> HandoffFinding:
    if eligibility.contract_version not in SUPPORTED_ELIGIBILITY_CONTRACT_VERSIONS:
        return HandoffFinding(
            "eligibility_contract_version_compatibility", False,
            f"eligibility.contract_version {eligibility.contract_version} "
            f"is not supported (supported: "
            f"{sorted(SUPPORTED_ELIGIBILITY_CONTRACT_VERSIONS)}).",
            HandoffFailureCategory.CONTRACT_MISMATCH,
        )
    return HandoffFinding(
        "eligibility_contract_version_compatibility", True,
        f"eligibility.contract_version={eligibility.contract_version}.",
    )


def _check_eligibility_integrity(eligibility: ActivationEligibilityResult) -> HandoffFinding:
    recomputed = compute_activation_eligibility_hash(
        request_id=eligibility.request_id,
        mission_id=eligibility.mission_id,
        review_id=eligibility.review_id,
        intake_id=eligibility.intake_id,
        handoff_id=eligibility.handoff_id,
        status=eligibility.status.value,
        findings=eligibility.findings,
        handoff_content_hash=eligibility.human_authorization_handoff.content_hash,
        activation_contract_id=(
            eligibility.activation_contract.activation_id if eligibility.activation_contract is not None else None
        ),
        provider_activation_contract_id=(
            eligibility.provider_activation_contract.activation_id
            if eligibility.provider_activation_contract is not None
            else None
        ),
        contract_version=eligibility.contract_version,
    )
    if recomputed != eligibility.content_hash:
        return HandoffFinding(
            "eligibility_integrity", False,
            "eligibility.content_hash does not match its own recomputed "
            "hash -- the eligibility result may have been tampered with "
            "or is otherwise corrupted; refusing to hand off an "
            "inconsistent eligibility result.",
            HandoffFailureCategory.ELIGIBILITY_INTEGRITY_FAILURE,
        )
    return HandoffFinding("eligibility_integrity", True, "eligibility.content_hash matches recomputed hash.")


def _check_eligibility_status_acceptable(eligibility: ActivationEligibilityResult) -> HandoffFinding:
    if eligibility.status not in _ELIGIBLE_UPSTREAM_STATUSES:
        return HandoffFinding(
            "eligibility_status_acceptable", False,
            f"eligibility.status is '{eligibility.status.value}', not "
            f"ELIGIBLE_FOR_ACTIVATION or "
            f"ACTIVATION_CONTRACT_STRUCTURALLY_VALID; a request that is "
            f"not eligible for activation can never receive a production "
            f"activation handoff. Underlying eligibility reasons: "
            f"{list(eligibility.reasons)}.",
            HandoffFailureCategory.ACTIVATION_NOT_ELIGIBLE,
        )
    return HandoffFinding("eligibility_status_acceptable", True, f"eligibility.status is '{eligibility.status.value}'.")


def _check_identity_chain_consistency(eligibility: ActivationEligibilityResult) -> HandoffFinding:
    handoff = eligibility.human_authorization_handoff
    intake = handoff.intake
    review = intake.handoff.review

    if eligibility.handoff_id != handoff.handoff_id:
        return HandoffFinding(
            "identity_chain_consistency", False,
            f"eligibility.handoff_id '{eligibility.handoff_id}' does not "
            f"match eligibility.human_authorization_handoff.handoff_id "
            f"'{handoff.handoff_id}'.",
            HandoffFailureCategory.CONTRACT_MISMATCH,
        )
    if eligibility.intake_id != intake.intake_id:
        return HandoffFinding(
            "identity_chain_consistency", False,
            f"eligibility.intake_id '{eligibility.intake_id}' does not "
            f"match the underlying intake_id '{intake.intake_id}'.",
            HandoffFailureCategory.CONTRACT_MISMATCH,
        )
    if eligibility.review_id != review.review_id:
        return HandoffFinding(
            "identity_chain_consistency", False,
            f"eligibility.review_id '{eligibility.review_id}' does not "
            f"match the reviewed request's review_id '{review.review_id}'.",
            HandoffFailureCategory.CONTRACT_MISMATCH,
        )
    if eligibility.mission_id != review.mission_id:
        return HandoffFinding(
            "identity_chain_consistency", False,
            f"eligibility.mission_id '{eligibility.mission_id}' does not "
            f"match the reviewed request's mission_id '{review.mission_id}'.",
            HandoffFailureCategory.CONTRACT_MISMATCH,
        )
    if eligibility.request_id != review.request_id:
        return HandoffFinding(
            "identity_chain_consistency", False,
            f"eligibility.request_id '{eligibility.request_id}' does not "
            f"match the reviewed request's request_id "
            f"'{review.request_id}'.",
            HandoffFailureCategory.CONTRACT_MISMATCH,
        )
    return HandoffFinding(
        "identity_chain_consistency", True,
        f"handoff_id/intake_id/review_id/mission_id/request_id are "
        f"consistent across the full chain "
        f"(request_id='{eligibility.request_id}').",
    )


def _check_identity_lock_status(identity_lock_violations: Optional[Tuple[str, ...]]) -> HandoffFinding:
    if identity_lock_violations is None:
        return HandoffFinding(
            "identity_lock_status", True,
            "No identity_lock_violations were supplied by the caller -- "
            "this module never computes its own; the P2.18 Release "
            "Candidate Identity Lock remains the sole live authority for "
            "this check.",
        )
    if identity_lock_violations:
        return HandoffFinding(
            "identity_lock_status", False,
            f"Caller-supplied identity_lock_violations is non-empty "
            f"({len(identity_lock_violations)} violation(s)) -- a "
            f"production activation handoff must never be READY while "
            f"the Release Candidate Identity Lock reports violations: "
            f"{list(identity_lock_violations)}.",
            HandoffFailureCategory.IDENTITY_LOCK_VIOLATION,
        )
    return HandoffFinding("identity_lock_status", True, "Caller-supplied identity_lock_violations is empty -- no violations reported.")


def _check_expected_eligibility_id(eligibility: ActivationEligibilityResult, expected: Optional[str]) -> HandoffFinding:
    if expected is None:
        return HandoffFinding("expected_eligibility_id_pin", True, "No expected_eligibility_id was pinned by the caller.")
    if eligibility.eligibility_id != expected:
        return HandoffFinding(
            "expected_eligibility_id_pin", False,
            f"eligibility.eligibility_id '{eligibility.eligibility_id}' "
            f"does not match the caller-pinned expected_eligibility_id "
            f"'{expected}' -- stale or mismatched eligibility result.",
            HandoffFailureCategory.STALE_OR_MISMATCHED_HANDOFF,
        )
    return HandoffFinding("expected_eligibility_id_pin", True, f"eligibility_id='{eligibility.eligibility_id}' matches pin.")


def _check_expected_request_id(eligibility: ActivationEligibilityResult, expected: Optional[str]) -> HandoffFinding:
    if expected is None:
        return HandoffFinding("expected_request_id_pin", True, "No expected_request_id was pinned by the caller.")
    if eligibility.request_id != expected:
        return HandoffFinding(
            "expected_request_id_pin", False,
            f"eligibility.request_id '{eligibility.request_id}' does not "
            f"match the caller-pinned expected_request_id '{expected}' "
            f"-- stale or mismatched eligibility result.",
            HandoffFailureCategory.STALE_OR_MISMATCHED_HANDOFF,
        )
    return HandoffFinding("expected_request_id_pin", True, f"request_id='{eligibility.request_id}' matches pin.")


# ----------------------------------------------------------------------
# BUILDER (Section 4/5) -- single responsibility: formalize the fifth
# and final P3-side STOP point, between ActivationEligibilityResult and
# a future, separately-authorized "Controlled Activation / Execution"
# phase. Never orchestrates agents, never becomes the State Machine,
# never a production executor, never prepares/validates/consumes an
# activation contract.
# ----------------------------------------------------------------------


class ProductionActivationHandoffBuilder:
    """
    AI DIRECTOR — Production Activation Handoff Builder (P3.21)

    Stateless: holds no injected collaborator, no provider, no gate, no
    service, no lock, no state machine reference. `build()` is a pure
    function of its `ProductionActivationHandoffInput`.
    """

    def build(self, request: ProductionActivationHandoffInput) -> ProductionActivationHandoff:
        if not isinstance(request.eligibility, ActivationEligibilityResult):
            raise ProductionActivationHandoffError(
                "eligibility is not a valid ActivationEligibilityResult "
                "instance; this module never fabricates one."
            )

        eligibility = request.eligibility
        handoff = eligibility.human_authorization_handoff

        findings: list = [
            _check_eligibility_structural_validity(eligibility),
            _check_eligibility_contract_version(eligibility),
            _check_eligibility_integrity(eligibility),
            _check_identity_chain_consistency(eligibility),
            _check_eligibility_status_acceptable(eligibility),
            _check_identity_lock_status(request.identity_lock_violations),
            _check_expected_eligibility_id(eligibility, request.expected_eligibility_id),
            _check_expected_request_id(eligibility, request.expected_request_id),
        ]
        findings_t = tuple(findings)

        reasons = tuple(f.detail for f in findings_t if not f.passed)
        status = (
            ProductionActivationHandoffStatus.NOT_ELIGIBLE_FOR_HANDOFF
            if reasons
            else ProductionActivationHandoffStatus.ACTIVATION_HANDOFF_READY
        )

        clock = request.clock or _default_clock
        handoff_id = request.handoff_id or uuid.uuid4().hex
        created_at = clock()

        identity_lock_checked = request.identity_lock_violations is not None
        identity_lock_violations = tuple(request.identity_lock_violations or ())

        content_hash = compute_production_activation_handoff_hash(
            request_id=eligibility.request_id,
            mission_id=eligibility.mission_id,
            review_id=eligibility.review_id,
            intake_id=eligibility.intake_id,
            human_authorization_handoff_id=eligibility.handoff_id,
            eligibility_id=eligibility.eligibility_id,
            status=status.value,
            findings=findings_t,
            eligibility_content_hash=eligibility.content_hash,
            authorization_id=handoff.authorization_id,
            identity_lock_violations=identity_lock_violations,
            contract_version=HANDOFF_CONTRACT_VERSION,
        )

        return ProductionActivationHandoff(
            handoff_id=handoff_id,
            artifact_type=HANDOFF_ARTIFACT_TYPE,
            created_at=created_at,
            contract_version=HANDOFF_CONTRACT_VERSION,
            request_id=eligibility.request_id,
            mission_id=eligibility.mission_id,
            review_id=eligibility.review_id,
            intake_id=eligibility.intake_id,
            human_authorization_handoff_id=eligibility.handoff_id,
            eligibility_id=eligibility.eligibility_id,
            status=status,
            findings=findings_t,
            reasons=reasons,
            eligibility=eligibility,
            authorization_id=handoff.authorization_id,
            identity_lock_checked=identity_lock_checked,
            identity_lock_violations=identity_lock_violations,
            producer_agent=PRODUCER_AGENT,
            producer_version=PRODUCER_VERSION,
            content_hash=content_hash,
        )
