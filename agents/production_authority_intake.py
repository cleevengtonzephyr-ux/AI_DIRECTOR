"""
AI DIRECTOR — Production Authority Intake (Phase P3.18)

INTAKE BOUNDARY ONLY, built directly against the REAL contracts re-read
from disk before writing a line of this module: `agents/production_
readiness_handoff.py` (P3.17, `ProductionReadinessHandoffBuilder.
build()` -> `ProductionReadinessHandoff`, carrying `review`
(`PreProductionReview`, P3.15) verbatim), and the full existing P2
authority chain re-audited from disk this phase: `agents/generation_
approval_gate.py` (Phase G/P2.11+), `agents/activation_contract.py`
(Phase P2.21), `agents/controlled_real_provider_activation.py` (Phase
P2.26), `agents/generation_job_service.py` (Phase H/P2.20/22/27),
`agents/activation_readiness.py` (Phase P2.24), `agents/real_provider_
execution_gate.py` (Phase P2.36), `integrations/higgsfield/provider.py`
and `integrations/higgsfield/client.py`.

RESPONSIBILITY (P3.18 Section 5): given a P3.17 `ProductionReadiness
Handoff`, determine whether it is STRUCTURALLY ACCEPTABLE for the P2
production authority chain to CONSIDER -- and STOP. This module never
authorizes, never activates, never executes, and, critically, NEVER
INVOKES the P2 chain itself (see "WHY THIS MODULE NEVER TOUCHES THE
GATE" below). A `ProductionReadinessHandoff` is NEVER treated as human
authorization anywhere in this module.

WHY THIS MODULE NEVER TOUCHES THE GATE, THE PROVIDER, OR ANY P2
OBJECT (Section 0/7 -- stated once, precisely, because it is the
single most important design decision of this phase): P3.18 Section 7
says "if the existing P2 architecture already has an appropriate
validation/intake contract, REUSE IT" -- and one already exists,
`agents/activation_readiness.py::ActivationReadinessEvaluator`
(Phase P2.24), a real, tested, purely-informational, ten-dimension
readiness snapshot for a bare `GenerationRequest`. It was audited this
phase and found UNSAFE to call unconditionally from here: its
`_check_budget()` dimension calls `gate.provider.get_account_balance()`
and `gate.cost_service.estimate()`, which on the REAL production chain
(`AIDirector._build_default_chain()`, `integrations/higgsfield/
provider.py::HiggsfieldProvider.get_account_balance()`/`estimate_cost()`)
delegate to `HiggsfieldClient.account_status()`/`estimate_cost()`
(`integrations/higgsfield/client.py`), both of which invoke
`subprocess.run()` against the REAL Higgsfield CLI -- an absolute,
non-negotiable violation of Section 0 ("MUST NOT ... call Higgsfield
CLI ... make network requests") if this module called it, or called
anything that transitively could, without the caller's own explicit,
scoped decision to do so. `GenerationApprovalGate.evaluate()` has the
exact same transitive risk (it calls the same cost/balance path).
Per Section 7's "implement only the smallest additive adapter" and
Section 12 ("the existing GenerationApprovalGate remains authoritative
... according to its real contract" -- never reinterpreted, never
pre-empted, never silently invoked on a caller's behalf by a new
module), this module therefore performs ONLY the checks that require
no I/O whatsoever: pure, offline, read-only inspection of the already
-computed, already-immutable `ProductionReadinessHandoff` and its
embedded `PreProductionReview`/`GenerationRequest`. Whether and how to
additionally consult the live Gate/Provider chain (via the already-
existing, unmodified `AIDirector.check_activation_readiness()`, `check_
real_provider_execution_gate()`, `check_activation_preflight()`, or
`prepare_real_generation_activation()`) remains ENTIRELY the caller's
own, separate, explicit decision -- never automatically chained from
this module, never duplicated by it.

NO EXECUTION / NO ACTIVATION / NO AUTHORIZATION (Section 0/11/12/13/14):
this module never imports `agents.generation_approval_gate.
GenerationApprovalGate`, `agents.generation_job_service.
GenerationJobService`, `agents.activation_contract`, `agents.
controlled_real_provider_activation`, `agents.activation_readiness`,
`agents.production_activation_boundary`, `agents.real_provider_
execution_gate`, `agents.real_provider_activation_preflight`, `agents.
critical_section_lock`, `agents.executed_request_store`, `integrations.
higgsfield.provider.HiggsfieldProvider`, `integrations.higgsfield.
client.HiggsfieldClient`, or `agents.mission_state_machine`, and never
calls `create_job`, `.evaluate(`, `.execute(`, `.transition(`,
`prepare_activation`, or constructs `RealGenerationAuthorization`,
`RequestScopedActivationContract`, or `ControlledRealProviderActivation
Contract`. `ProductionAuthorityIntakeStatus` has exactly two values,
`ACCEPTED_FOR_P2_CONSIDERATION` and `REJECTED` -- deliberately never
`APPROVED`, `AUTHORIZED`, `ACTIVATED`, `EXECUTING`, or `EXECUTED`
(Section 6's "do not collapse these states").

SCOPE BOUNDARY -- WHAT THIS MODULE DOES AND DOES NOT VERIFY (Section
8/9, mirrors P3.17's own documented scope boundary): this module
re-verifies, at ITS OWN layer, exactly what Section 8 lists --
handoff readiness status, malformed/stale handoff, request/mission/
review/artifact identity, integrity, and contract version -- by
recomputing BOTH `agents.production_readiness_handoff.
compute_handoff_hash` (for the handoff itself) AND `agents.
pre_production_review.compute_review_hash` (for the embedded review)
against their own recorded `content_hash` fields, reusing both
functions verbatim, never reimplementing either. Re-checking the
review's own hash here (P3.17 already did this once) is DELIBERATE
defense-in-depth, the same "each layer independently re-verifies the
one below it, never trusts it blindly" idiom already established by
`agents/controlled_real_provider_activation.py` re-inspecting `agents/
activation_contract.py`'s work. This module does NOT re-verify prompt/
asset/model/duration/resolution/aspect_ratio equality a second time --
those stay exclusively inside P3.15/P3.17, per the same "reuse, don't
duplicate" instruction carried forward from P3.17 Section 5.

BUDGET (Section 15): this module carries NO budget/cost dimension at
all -- not "always passes", not "informational" -- it is simply ABSENT,
because inspecting it honestly would require the live Gate/Provider
chain this module deliberately never touches (see above). Nothing here
ever approves production because of budget data, and nothing here
fabricates budget data by omission either: the absence of a budget
dimension is itself the honest answer to "does this module know
anything about budget" (no).

STATE MACHINE (Section 16/18): this module never imports `agents.
mission_state_machine` and never calls `.transition()`. Whether an
`ACCEPTED_FOR_P2_CONSIDERATION` intake result here should ever be
reflected as a Mission State transition remains exclusively a
Director/Orchestrator decision, never exercised by this module.

CONCURRENCY / REPLAY / CRITICAL SECTION (Section 17/18/19): this
module makes zero calls to `create_job`, `execute`, `mark_executed`,
`activation.consume`, or any critical-section lock -- there is
therefore exactly one production execution path in the repository
(`GenerationJobService.execute()`, unmodified, unreachable from here)
before and after this phase. `ExecutedRequestStore` is never imported,
inspected, or written to: accepting a handoff here is explicitly NOT
an execution record and never touches replay state.

IMMUTABILITY / DETERMINISM / IDEMPOTENCY (Section 20/21/22): this
module never imports `dataclasses.replace` and never assigns to any
attribute of `ProductionReadinessHandoff`, `PreProductionReview`,
`ProductionPreparationRequest`, `ScriptArtifact`, or `GenerationRequest`
-- all frozen anyway. `intake()` is a pure function of its input:
identical immutable input always yields findings/status/`content_hash`
that are equal by value (the only fields excluded from `content_hash`,
mirroring P3.15/P3.17's own hash discipline, are `intake_id`/
`created_at` -- technical/temporal, never fed into the hash).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional, Tuple

from agents.pre_production_review import compute_review_hash
from agents.production_readiness_handoff import (
    HANDOFF_ARTIFACT_TYPE,
    HANDOFF_CONTRACT_VERSION,
    ProductionReadinessHandoff,
    ProductionReadinessHandoffStatus,
    compute_handoff_hash,
)

INTAKE_CONTRACT_VERSION = 1
INTAKE_ARTIFACT_TYPE = "ProductionAuthorityIntakeReport"
PRODUCER_AGENT = "production-authority-intake"
PRODUCER_VERSION = "1.0"

SUPPORTED_HANDOFF_CONTRACT_VERSIONS = frozenset({HANDOFF_CONTRACT_VERSION})


class ProductionAuthorityIntakeError(ValueError):
    """Raised for a structurally invalid `ProductionAuthorityIntakeInput`
    (e.g. `handoff` is not a real `ProductionReadinessHandoff`) -- never
    a silent fallback."""


class ProductionAuthorityIntakeStatus(str, Enum):
    """
    Exactly two values, deliberately never `APPROVED`, `AUTHORIZED`,
    `ACTIVATED`, `EXECUTING`, or `EXECUTED` (Section 6/12/13/14) -- an
    intake result can only ever say whether this handoff is
    structurally acceptable for the P2 chain to CONSIDER, never
    anything about production authority itself.
    """

    ACCEPTED_FOR_P2_CONSIDERATION = "ACCEPTED_FOR_P2_CONSIDERATION"
    REJECTED = "REJECTED"


class IntakeFailureCategory(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"
    HANDOFF_NOT_READY = "HANDOFF_NOT_READY"
    STALE_OR_MISMATCHED_HANDOFF = "STALE_OR_MISMATCHED_HANDOFF"
    INTEGRITY_FAILURE = "INTEGRITY_FAILURE"
    CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
    INTERNAL_INTAKE_FAILURE = "INTERNAL_INTAKE_FAILURE"


# ----------------------------------------------------------------------
# INPUT CONTRACT (Section 5/8)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ProductionAuthorityIntakeInput:
    handoff: ProductionReadinessHandoff

    # Optional caller-supplied canonical expected values (mirrors
    # ProductionReadinessHandoffInput's expected_review_id/
    # expected_request_id pattern, P3.17 Section 20) -- NEVER
    # fabricated internally. `None` means "not pinned"; the intake
    # still checks internal identity consistency regardless.
    expected_handoff_id: Optional[str] = None
    expected_review_id: Optional[str] = None
    expected_request_id: Optional[str] = None

    intake_id: Optional[str] = None
    clock: Optional[Callable[[], str]] = None


# ----------------------------------------------------------------------
# OUTPUT CONTRACT -- immutable.
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class IntakeFinding:
    dimension: str
    passed: bool
    detail: str
    category: Optional[IntakeFailureCategory] = None  # None iff passed


@dataclass(frozen=True)
class ProductionAuthorityIntakeReport:
    intake_id: str
    artifact_type: str
    created_at: str
    contract_version: int

    request_id: Optional[str]
    mission_id: str
    review_id: str
    handoff_id: str

    status: ProductionAuthorityIntakeStatus
    findings: Tuple[IntakeFinding, ...]
    reasons: Tuple[str, ...]  # detail of every failing finding, in order

    handoff: ProductionReadinessHandoff  # verbatim, never rewritten --
    # full chain (mission_id -> script_artifact -> production_
    # preparation -> generation_request -> review -> handoff) is
    # reachable through this single field, never re-copied onto this
    # dataclass (same "reuse existing artifact/request IDs" discipline
    # as P3.17 Section 13).

    producer_agent: str
    producer_version: str

    content_hash: str


def _default_clock() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_intake_hash(
    request_id: Optional[str],
    mission_id: str,
    review_id: str,
    handoff_id: str,
    status: str,
    findings: Tuple[IntakeFinding, ...],
    handoff_content_hash: str,
    contract_version: int,
) -> str:
    canonical = {
        "request_id": request_id,
        "mission_id": mission_id,
        "review_id": review_id,
        "handoff_id": handoff_id,
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
        "handoff_content_hash": handoff_content_hash,
        "contract_version": contract_version,
    }
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# INTAKE DIMENSIONS (Section 8/9) -- each a pure function of the real
# input, returning exactly one IntakeFinding. Never reaches outside the
# immutable objects it was given (no I/O, no provider, no Gate).
# ----------------------------------------------------------------------


def _check_handoff_structural_validity(handoff: ProductionReadinessHandoff) -> IntakeFinding:
    if handoff.artifact_type != HANDOFF_ARTIFACT_TYPE:
        return IntakeFinding(
            "handoff_structural_validity", False,
            f"handoff.artifact_type '{handoff.artifact_type}' is not '{HANDOFF_ARTIFACT_TYPE}'.",
            IntakeFailureCategory.INVALID_INPUT,
        )
    if not isinstance(handoff.handoff_id, str) or not handoff.handoff_id.strip():
        return IntakeFinding(
            "handoff_structural_validity", False,
            f"handoff.handoff_id is missing or empty ({handoff.handoff_id!r}).",
            IntakeFailureCategory.INVALID_INPUT,
        )
    return IntakeFinding("handoff_structural_validity", True, f"handoff_id='{handoff.handoff_id}'.")


def _check_handoff_contract_version(handoff: ProductionReadinessHandoff) -> IntakeFinding:
    if handoff.contract_version not in SUPPORTED_HANDOFF_CONTRACT_VERSIONS:
        return IntakeFinding(
            "handoff_contract_version_compatibility", False,
            f"handoff.contract_version {handoff.contract_version} is not supported "
            f"(supported: {sorted(SUPPORTED_HANDOFF_CONTRACT_VERSIONS)}).",
            IntakeFailureCategory.CONTRACT_MISMATCH,
        )
    return IntakeFinding(
        "handoff_contract_version_compatibility", True,
        f"handoff.contract_version={handoff.contract_version}.",
    )


def _check_handoff_integrity(handoff: ProductionReadinessHandoff) -> IntakeFinding:
    recomputed = compute_handoff_hash(
        request_id=handoff.request_id,
        mission_id=handoff.mission_id,
        review_id=handoff.review_id,
        status=handoff.status.value,
        findings=handoff.findings,
        review_content_hash=handoff.review.content_hash,
        contract_version=handoff.contract_version,
    )
    if recomputed != handoff.content_hash:
        return IntakeFinding(
            "handoff_integrity", False,
            "handoff.content_hash does not match its own recomputed hash -- "
            "the handoff may have been tampered with or is otherwise "
            "corrupted; refusing to accept an inconsistent handoff.",
            IntakeFailureCategory.INTEGRITY_FAILURE,
        )
    return IntakeFinding("handoff_integrity", True, "handoff.content_hash matches recomputed hash.")


def _check_review_integrity(handoff: ProductionReadinessHandoff) -> IntakeFinding:
    review = handoff.review
    recomputed = compute_review_hash(
        request_id=review.request_id,
        mission_id=review.mission_id,
        status=review.status.value,
        findings=review.findings,
        production_preparation_content_hash=(
            review.production_preparation.content_hash
            if review.production_preparation is not None
            else None
        ),
        contract_version=review.contract_version,
    )
    if recomputed != review.content_hash:
        return IntakeFinding(
            "embedded_review_integrity", False,
            "handoff.review.content_hash does not match its own "
            "recomputed hash -- the embedded review may have been "
            "tampered with; refusing to accept an inconsistent handoff.",
            IntakeFailureCategory.INTEGRITY_FAILURE,
        )
    return IntakeFinding("embedded_review_integrity", True, "handoff.review.content_hash matches recomputed hash.")


def _check_handoff_status_ready(handoff: ProductionReadinessHandoff) -> IntakeFinding:
    if handoff.status != ProductionReadinessHandoffStatus.READY_FOR_PRODUCTION_AUTHORITY:
        return IntakeFinding(
            "handoff_status_ready", False,
            f"handoff.status is '{handoff.status.value}', not "
            f"READY_FOR_PRODUCTION_AUTHORITY; a NOT_READY handoff can "
            f"never be accepted for P2 consideration. Underlying handoff "
            f"reasons: {list(handoff.reasons)}.",
            IntakeFailureCategory.HANDOFF_NOT_READY,
        )
    return IntakeFinding("handoff_status_ready", True, "handoff.status is READY_FOR_PRODUCTION_AUTHORITY.")


def _check_identity_chain_consistency(handoff: ProductionReadinessHandoff) -> IntakeFinding:
    review = handoff.review

    if handoff.review_id != review.review_id:
        return IntakeFinding(
            "identity_chain_consistency", False,
            f"handoff.review_id '{handoff.review_id}' does not match "
            f"handoff.review.review_id '{review.review_id}'.",
            IntakeFailureCategory.CONTRACT_MISMATCH,
        )
    if handoff.mission_id != review.mission_id:
        return IntakeFinding(
            "identity_chain_consistency", False,
            f"handoff.mission_id '{handoff.mission_id}' does not match "
            f"handoff.review.mission_id '{review.mission_id}'.",
            IntakeFailureCategory.CONTRACT_MISMATCH,
        )
    if handoff.request_id != review.request_id:
        return IntakeFinding(
            "identity_chain_consistency", False,
            f"handoff.request_id '{handoff.request_id}' does not match "
            f"handoff.review.request_id '{review.request_id}'.",
            IntakeFailureCategory.CONTRACT_MISMATCH,
        )
    gr = review.generation_request
    if gr is not None and review.request_id != gr.request_id:
        return IntakeFinding(
            "identity_chain_consistency", False,
            f"handoff.review.request_id '{review.request_id}' does not "
            f"match handoff.review.generation_request.request_id "
            f"'{gr.request_id}'.",
            IntakeFailureCategory.CONTRACT_MISMATCH,
        )
    return IntakeFinding(
        "identity_chain_consistency", True,
        f"handoff_id/review_id/mission_id/request_id are consistent across "
        f"the full chain (request_id='{handoff.request_id}').",
    )


def _check_not_already_authorized(handoff: ProductionReadinessHandoff) -> IntakeFinding:
    gr = handoff.review.generation_request
    if gr is not None and (gr.approved is not False or gr.real_generation_authorization is not None):
        # Defensive, should be structurally impossible via P3.14/P3.15/
        # P3.17's own hardcoding -- a real contract violation if it ever
        # happens, never silently accepted (Section 11/12).
        return IntakeFinding(
            "not_already_authorized", False,
            "handoff.review.generation_request is already "
            "approved/authorized -- an intake must never accept a "
            "handoff whose underlying generation_request already carries "
            "authorization; this would violate the authority boundary.",
            IntakeFailureCategory.INTERNAL_INTAKE_FAILURE,
        )
    return IntakeFinding("not_already_authorized", True, "generation_request carries no authorization.")


def _check_expected_handoff_id(handoff: ProductionReadinessHandoff, expected_handoff_id: Optional[str]) -> IntakeFinding:
    if expected_handoff_id is None:
        return IntakeFinding("expected_handoff_id_pin", True, "No expected_handoff_id was pinned by the caller.")
    if handoff.handoff_id != expected_handoff_id:
        return IntakeFinding(
            "expected_handoff_id_pin", False,
            f"handoff.handoff_id '{handoff.handoff_id}' does not match the "
            f"caller-pinned expected_handoff_id '{expected_handoff_id}' -- "
            f"stale or mismatched handoff.",
            IntakeFailureCategory.STALE_OR_MISMATCHED_HANDOFF,
        )
    return IntakeFinding("expected_handoff_id_pin", True, f"handoff_id='{handoff.handoff_id}' matches pin.")


def _check_expected_review_id(handoff: ProductionReadinessHandoff, expected_review_id: Optional[str]) -> IntakeFinding:
    if expected_review_id is None:
        return IntakeFinding("expected_review_id_pin", True, "No expected_review_id was pinned by the caller.")
    if handoff.review_id != expected_review_id:
        return IntakeFinding(
            "expected_review_id_pin", False,
            f"handoff.review_id '{handoff.review_id}' does not match the "
            f"caller-pinned expected_review_id '{expected_review_id}' -- "
            f"stale or mismatched handoff.",
            IntakeFailureCategory.STALE_OR_MISMATCHED_HANDOFF,
        )
    return IntakeFinding("expected_review_id_pin", True, f"review_id='{handoff.review_id}' matches pin.")


def _check_expected_request_id(handoff: ProductionReadinessHandoff, expected_request_id: Optional[str]) -> IntakeFinding:
    if expected_request_id is None:
        return IntakeFinding("expected_request_id_pin", True, "No expected_request_id was pinned by the caller.")
    if handoff.request_id != expected_request_id:
        return IntakeFinding(
            "expected_request_id_pin", False,
            f"handoff.request_id '{handoff.request_id}' does not match "
            f"the caller-pinned expected_request_id '{expected_request_id}' "
            f"-- stale or mismatched handoff.",
            IntakeFailureCategory.STALE_OR_MISMATCHED_HANDOFF,
        )
    return IntakeFinding("expected_request_id_pin", True, f"request_id='{handoff.request_id}' matches pin.")


# ----------------------------------------------------------------------
# INTAKE (Section 5/7) -- single responsibility: formalize the second
# STOP point between ProductionReadinessHandoff and the P2 authority
# chain. Never orchestrates agents, never becomes the State Machine,
# never a production executor, never invokes the P2 boundary it
# references.
# ----------------------------------------------------------------------


class ProductionAuthorityIntake:
    """
    AI DIRECTOR — Production Authority Intake (P3.18)

    Stateless: holds no injected collaborator, no provider, no gate, no
    lock, no state machine reference. `intake()` is a pure function of
    its `ProductionAuthorityIntakeInput`.
    """

    def intake(self, request: ProductionAuthorityIntakeInput) -> ProductionAuthorityIntakeReport:
        if not isinstance(request.handoff, ProductionReadinessHandoff):
            raise ProductionAuthorityIntakeError(
                "handoff is not a valid ProductionReadinessHandoff instance; "
                "this module never fabricates one."
            )

        handoff = request.handoff

        findings: list = [
            _check_handoff_structural_validity(handoff),
            _check_handoff_contract_version(handoff),
            _check_handoff_integrity(handoff),
            _check_review_integrity(handoff),
            _check_handoff_status_ready(handoff),
            _check_identity_chain_consistency(handoff),
            _check_not_already_authorized(handoff),
            _check_expected_handoff_id(handoff, request.expected_handoff_id),
            _check_expected_review_id(handoff, request.expected_review_id),
            _check_expected_request_id(handoff, request.expected_request_id),
        ]
        findings_t = tuple(findings)

        reasons = tuple(f.detail for f in findings_t if not f.passed)
        status = (
            ProductionAuthorityIntakeStatus.REJECTED
            if reasons
            else ProductionAuthorityIntakeStatus.ACCEPTED_FOR_P2_CONSIDERATION
        )

        clock = request.clock or _default_clock
        intake_id = request.intake_id or uuid.uuid4().hex
        created_at = clock()

        content_hash = compute_intake_hash(
            request_id=handoff.request_id,
            mission_id=handoff.mission_id,
            review_id=handoff.review_id,
            handoff_id=handoff.handoff_id,
            status=status.value,
            findings=findings_t,
            handoff_content_hash=handoff.content_hash,
            contract_version=INTAKE_CONTRACT_VERSION,
        )

        return ProductionAuthorityIntakeReport(
            intake_id=intake_id,
            artifact_type=INTAKE_ARTIFACT_TYPE,
            created_at=created_at,
            contract_version=INTAKE_CONTRACT_VERSION,
            request_id=handoff.request_id,
            mission_id=handoff.mission_id,
            review_id=handoff.review_id,
            handoff_id=handoff.handoff_id,
            status=status,
            findings=findings_t,
            reasons=reasons,
            handoff=handoff,
            producer_agent=PRODUCER_AGENT,
            producer_version=PRODUCER_VERSION,
            content_hash=content_hash,
        )
