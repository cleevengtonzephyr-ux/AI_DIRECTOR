"""
AI DIRECTOR — Production Readiness Handoff (Phase P3.17)

HANDOFF BOUNDARY ONLY, built directly against the REAL contract
re-read from disk before writing a line of this module: `agents/
pre_production_review.py` (P3.15, `PreProductionReviewer.review()` ->
`PreProductionReview`, carrying `production_preparation`
(`ProductionPreparationRequest`, P3.13) and `generation_request`
(`GenerationRequest` -- imported here ONLY as a type, exactly as
`agents/pre_production_review.py` itself already does; `Generation
ApprovalGate`, `GenerationJobService`, `HiggsfieldProvider`, and
`HiggsfieldClient` are never imported, directly or transitively).

RESPONSIBILITY (P3.17 Section 3/6): given a P3.15 `PreProductionReview`
-- the real, already-existing verdict that carries a technically
reviewed `GenerationRequest` together with its full provenance chain
(`ScriptArtifact`, `ProductionPreparationRequest`, `mission_id`) --
produce a `ProductionReadinessHandoff`: a formal, inspectable record
that this prepared request has COMPLETED THE P3 TECHNICAL REVIEW
PROCESS and is ready to be CONSIDERED by the separate, pre-existing P2
production authority boundary (`agents/generation_approval_gate.py`,
`agents/activation_contract.py`, `agents/controlled_real_provider_
activation.py`, `agents/generation_job_service.py`). This module never
invokes that boundary, never authorizes, never activates, and never
executes anything. It only formalizes a STOP point.

WHY THE INPUT IS `PreProductionReview`, NOT A BARE `GenerationRequest`:
identical reasoning to why P3.15 itself required a
`VideoProductionPreparationResult` rather than a bare
`GenerationRequest` (`agents/pre_production_review.py` module
docstring) -- reviewing PROVENANCE requires the full chain, not just
the reviewed request. `PreProductionReview` already IS the real
"completed P3 technical review" object; this module never rebuilds or
re-derives any of P3.13/P3.14/P3.15's own findings (script/prompt/
asset/model/duration/resolution/aspect_ratio/reference checks all stay
EXCLUSIVELY inside `agents/pre_production_review.py`, never duplicated
here -- P3.17 Section 5's "if an existing contract already provides
the correct handoff logic, REUSE IT, do not create duplicate authority
concepts").

EXISTING CONTRACT AUDIT (P3.17 Section 5), DONE BEFORE WRITING THIS
MODULE: the repository already has several "readiness"/"authorization"/
"activation" concepts (`agents/activation_readiness.py` Phase P2.24,
`agents/production_activation_boundary.py` Phase P2.25, `agents/
activation_contract.py` Phase P2.21, `agents/controlled_real_provider_
activation.py` Phase P2.26, `agents/real_provider_execution_gate.py`
Phase P2.36) -- ALL of them operate on a bare `GenerationRequest` and
belong exclusively to the P2 REAL-GENERATION authority chain (gated
behind `HiggsfieldProvider`/`GenerationApprovalGate`). None of them
accepts or is aware of a P3.15 `PreProductionReview` (the P3 TECHNICAL
review chain, deliberately unintegrated with P2 -- cf. `agents/
mission_state_machine.py`'s own P3.12 audit). No existing contract
already bridges "P3 review completed" to "P2 authority boundary
exists" -- this module fills exactly that one gap, and only that gap.
It does NOT reimplement, wrap, or re-expose any P2 readiness/
authorization/activation mechanism: `ProductionReadinessHandoff`
carries no field and no method that could invoke, construct, or stand
in for any of them.

NO EXECUTION / NO ACTIVATION / NO AUTHORIZATION (Section 0/8/9/10):
this module never imports `agents.generation_approval_gate.
GenerationApprovalGate`, `agents.generation_job_service.
GenerationJobService`, `agents.activation_contract`, `agents.
controlled_real_provider_activation`, `agents.real_provider_execution_
gate`, `agents.real_provider_activation_preflight`, `agents.critical_
section_lock`, `agents.executed_request_store`, `integrations.
higgsfield.provider.HiggsfieldProvider`, `integrations.higgsfield.
client.HiggsfieldClient`, or `agents.mission_state_machine`, and never
calls `create_job`, `.evaluate(`, `.execute(`, `.transition(`, or
constructs `RealGenerationAuthorization`, `RequestScopedActivation
Contract`, or `ControlledRealProviderActivationContract`. A
`READY_FOR_PRODUCTION_AUTHORITY` status means only "the P3 technical
review process completed successfully and this handoff record is
internally consistent" -- NEVER "authorized", "activated", or
"executing". There is deliberately no `approved`/`authorized`/
`activated` field anywhere on `ProductionReadinessHandoff`, exactly
mirroring `PreProductionReview`'s own P3.15 discipline (Section 4 of
that phase): only `status`, restricted to the two values described
above, to make the concepts impossible to confuse by attribute name
alone.

SCOPE BOUNDARY -- WHAT THIS MODULE DOES AND DOES NOT RE-VERIFY
(Section 5/14, stated once, precisely, because it bounds what this
module can honestly do): `PreProductionReview.content_hash` already
canonically covers `request_id`, `mission_id`, `status`, every
`ReadinessFinding` (whose `detail` text embeds the reviewed request's
job_type/duration/resolution/aspect_ratio/request_id -- see `agents/
pre_production_review.py::compute_review_hash`), and `production_
preparation.content_hash`. This module reuses that EXACT hash function
(`agents.pre_production_review.compute_review_hash`, never
reimplemented) to detect whether a `PreProductionReview` instance has
been tampered with relative to its own recorded `content_hash` --
this is the `review_integrity` dimension below, and it is the primary
integrity boundary this module relies on, per Section 14's "use
existing hashes/contracts where available; do not duplicate hashing
systems unnecessarily". It additionally checks two IDENTIFIER
consistency dimensions that the review's hash does NOT cover for every
possible tamper vector (a hand-crafted `PreProductionReview` built via
`dataclasses.replace` that swaps `generation_request` or `production_
preparation` for a different object without touching `content_hash`):
`request_identity_consistency` (review.request_id must equal review.
generation_request.request_id) and `mission_identity_consistency`
(review.mission_id must equal review.production_preparation.
mission_id). It does NOT re-verify prompt/asset/model/duration/
resolution/aspect_ratio equality a second time -- that is P3.15's
exclusive, already-tested responsibility, and duplicating it here
would violate Section 5's "reuse, don't duplicate" instruction while
adding no real protection beyond what `review_integrity` already
gives for the fields that ARE hashed.

FAILURE SEMANTICS (Section 19): each `HandoffFinding` that fails
carries one of `HandoffFailureCategory` -- `INVALID_INPUT`,
`REVIEW_NOT_PASS`, `STALE_OR_MISMATCHED_REVIEW`, `INTEGRITY_FAILURE`,
`CONTRACT_MISMATCH`, `INTERNAL_HANDOFF_FAILURE`. A review that FAILED
its P3.15 review can never produce a `READY_FOR_PRODUCTION_AUTHORITY`
handoff (Section 7): `review_status_readiness` fails closed whenever
`review.status != PASS`, carrying the review's own `reasons` forward
verbatim so the original failure is never hidden behind a new handoff-
level message.

IMMUTABILITY / DETERMINISM / IDEMPOTENCY (Section 14/15/16/17): this
module never imports `dataclasses.replace` and never assigns to any
attribute of `PreProductionReview`, `ProductionPreparationRequest`,
`ScriptArtifact`, or `GenerationRequest` -- all frozen anyway. `build()`
is a pure function of its input: identical immutable input (same
`PreProductionReview`, same optional `expected_review_id`/
`expected_request_id`) always yields findings/status/`content_hash`
that are equal by value (the only fields excluded from `content_hash`,
mirroring P3.15/P3.13's own hash discipline, are `handoff_id`/
`created_at` -- technical/temporal, never fed into the hash).

STATE MACHINE (Section 12): this module never imports `agents.
mission_state_machine` and never calls `.transition()`. Whether a
`READY_FOR_PRODUCTION_AUTHORITY` handoff here should ever be reflected
as a Mission State transition remains exclusively a Director/
Orchestrator decision, never exercised by this module.

STALENESS (Section 20): the real architecture carries no version/
expiry field on `PreProductionReview` or its ancestors, and this
module does not invent one -- no clock-based expiry is introduced here.
"Staleness" is instead expressed structurally: an optional caller-
supplied `expected_review_id`/`expected_request_id` (mirroring `Pre
ProductionReviewInput`'s `expected_prompt_sha256` pattern, Section 6 of
P3.15) lets a caller pin down which exact review/request it expects to
be handing off; a mismatch is reported as `STALE_OR_MISMATCHED_REVIEW`,
never silently accepted. `None` (the default) means "no external pin
supplied" -- the handoff is still built and still checked against its
own internal identifier consistency (see the scope boundary above).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional, Tuple

from agents.pre_production_review import (
    REVIEW_ARTIFACT_TYPE,
    REVIEW_CONTRACT_VERSION,
    PreProductionReview,
    PreProductionReviewStatus,
    compute_review_hash,
)

HANDOFF_CONTRACT_VERSION = 1
HANDOFF_ARTIFACT_TYPE = "ProductionReadinessHandoff"
PRODUCER_AGENT = "production-readiness-handoff"
PRODUCER_VERSION = "1.0"

SUPPORTED_REVIEW_CONTRACT_VERSIONS = frozenset({REVIEW_CONTRACT_VERSION})


class ProductionReadinessHandoffError(ValueError):
    """Raised for a structurally invalid `ProductionReadinessHandoffInput`
    (e.g. `review` is not a real `PreProductionReview`) -- never a
    silent fallback."""


class ProductionReadinessHandoffStatus(str, Enum):
    """
    Exactly two values, deliberately never `AUTHORIZED`, `ACTIVATED`,
    or `EXECUTING` (P3.17 Section 4/8/9) -- a handoff can only ever
    say whether the P3 technical review process completed and this
    record is internally consistent, never anything about production
    authority.
    """

    READY_FOR_PRODUCTION_AUTHORITY = "READY_FOR_PRODUCTION_AUTHORITY"
    NOT_READY = "NOT_READY"


class HandoffFailureCategory(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"
    REVIEW_NOT_PASS = "REVIEW_NOT_PASS"
    STALE_OR_MISMATCHED_REVIEW = "STALE_OR_MISMATCHED_REVIEW"
    INTEGRITY_FAILURE = "INTEGRITY_FAILURE"
    CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
    INTERNAL_HANDOFF_FAILURE = "INTERNAL_HANDOFF_FAILURE"


# ----------------------------------------------------------------------
# INPUT CONTRACT (Section 6)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ProductionReadinessHandoffInput:
    review: PreProductionReview

    # Optional caller-supplied canonical expected values (Section 20,
    # "staleness expressed structurally") -- NEVER fabricated
    # internally. `None` means "not pinned"; the handoff still checks
    # internal review/request/mission identifier consistency
    # regardless (see module docstring's scope boundary).
    expected_review_id: Optional[str] = None
    expected_request_id: Optional[str] = None

    handoff_id: Optional[str] = None
    clock: Optional[Callable[[], str]] = None


# ----------------------------------------------------------------------
# OUTPUT CONTRACT (Section 6/16/17) -- immutable.
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class HandoffFinding:
    dimension: str
    passed: bool
    detail: str
    category: Optional[HandoffFailureCategory] = None  # None iff passed


@dataclass(frozen=True)
class ProductionReadinessHandoff:
    handoff_id: str
    artifact_type: str
    created_at: str
    contract_version: int

    request_id: Optional[str]
    mission_id: str
    review_id: str

    status: ProductionReadinessHandoffStatus
    findings: Tuple[HandoffFinding, ...]
    reasons: Tuple[str, ...]  # detail of every failing finding, in order

    review: PreProductionReview  # verbatim, never rewritten -- full
    # traceability chain (mission_id -> script_artifact -> production_
    # preparation -> generation_request -> review) is reachable through
    # this single field, never re-copied onto this dataclass (Section 13:
    # "reuse existing artifact IDs and request IDs", never invent new ones).

    producer_agent: str
    producer_version: str

    content_hash: str


def _default_clock() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_handoff_hash(
    request_id: Optional[str],
    mission_id: str,
    review_id: str,
    status: str,
    findings: Tuple[HandoffFinding, ...],
    review_content_hash: str,
    contract_version: int,
) -> str:
    canonical = {
        "request_id": request_id,
        "mission_id": mission_id,
        "review_id": review_id,
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
        "review_content_hash": review_content_hash,
        "contract_version": contract_version,
    }
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# HANDOFF DIMENSIONS (Section 6/14/19) -- each a pure function of the
# real input, returning exactly one HandoffFinding. Never reaches
# outside the immutable objects it was given (no scanning, no I/O, no
# provider), and never re-derives a P3.15 business rule.
# ----------------------------------------------------------------------


def _check_review_structural_validity(review: PreProductionReview) -> HandoffFinding:
    if review.artifact_type != REVIEW_ARTIFACT_TYPE:
        return HandoffFinding(
            "review_structural_validity", False,
            f"review.artifact_type '{review.artifact_type}' is not '{REVIEW_ARTIFACT_TYPE}'.",
            HandoffFailureCategory.INVALID_INPUT,
        )
    if not isinstance(review.review_id, str) or not review.review_id.strip():
        return HandoffFinding(
            "review_structural_validity", False,
            f"review.review_id is missing or empty ({review.review_id!r}).",
            HandoffFailureCategory.INVALID_INPUT,
        )
    return HandoffFinding("review_structural_validity", True, f"review_id='{review.review_id}'.")


def _check_review_contract_version(review: PreProductionReview) -> HandoffFinding:
    if review.contract_version not in SUPPORTED_REVIEW_CONTRACT_VERSIONS:
        return HandoffFinding(
            "review_contract_version_compatibility", False,
            f"review.contract_version {review.contract_version} is not supported "
            f"(supported: {sorted(SUPPORTED_REVIEW_CONTRACT_VERSIONS)}).",
            HandoffFailureCategory.CONTRACT_MISMATCH,
        )
    return HandoffFinding(
        "review_contract_version_compatibility", True,
        f"review.contract_version={review.contract_version}.",
    )


def _check_review_integrity(review: PreProductionReview) -> HandoffFinding:
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
        return HandoffFinding(
            "review_integrity", False,
            "review.content_hash does not match its own recomputed hash -- "
            "the review may have been tampered with or is otherwise corrupted; "
            "refusing to hand off an inconsistent review.",
            HandoffFailureCategory.INTEGRITY_FAILURE,
        )
    return HandoffFinding("review_integrity", True, "review.content_hash matches recomputed hash.")


def _check_review_status_pass(review: PreProductionReview) -> HandoffFinding:
    if review.status != PreProductionReviewStatus.PASS:
        return HandoffFinding(
            "review_status_readiness", False,
            f"review.status is '{review.status.value}', not PASS; a FAILED "
            f"P3.15 review can never produce a READY_FOR_PRODUCTION_AUTHORITY "
            f"handoff. Underlying review reasons: {list(review.reasons)}.",
            HandoffFailureCategory.REVIEW_NOT_PASS,
        )
    return HandoffFinding("review_status_readiness", True, "review.status is PASS.")


def _check_request_identity_consistency(review: PreProductionReview) -> HandoffFinding:
    gr = review.generation_request
    if gr is None:
        if review.request_id is not None:
            return HandoffFinding(
                "request_identity_consistency", False,
                "review.request_id is present but review.generation_request is "
                "None -- structurally inconsistent review.",
                HandoffFailureCategory.INTERNAL_HANDOFF_FAILURE,
            )
        return HandoffFinding(
            "request_identity_consistency", True,
            "No generation_request present; nothing to cross-check.",
        )
    if review.request_id != gr.request_id:
        return HandoffFinding(
            "request_identity_consistency", False,
            f"review.request_id '{review.request_id}' does not match "
            f"review.generation_request.request_id '{gr.request_id}'.",
            HandoffFailureCategory.CONTRACT_MISMATCH,
        )
    return HandoffFinding("request_identity_consistency", True, f"request_id='{review.request_id}'.")


def _check_mission_identity_consistency(review: PreProductionReview) -> HandoffFinding:
    if not isinstance(review.mission_id, str) or not review.mission_id.strip():
        return HandoffFinding(
            "mission_identity_consistency", False, "review.mission_id is missing or empty.",
            HandoffFailureCategory.INVALID_INPUT,
        )
    prepared = review.production_preparation
    if prepared is not None and prepared.mission_id != review.mission_id:
        return HandoffFinding(
            "mission_identity_consistency", False,
            f"review.mission_id '{review.mission_id}' does not match "
            f"review.production_preparation.mission_id '{prepared.mission_id}'.",
            HandoffFailureCategory.CONTRACT_MISMATCH,
        )
    return HandoffFinding("mission_identity_consistency", True, f"mission_id='{review.mission_id}'.")


def _check_not_already_authorized(review: PreProductionReview) -> HandoffFinding:
    gr = review.generation_request
    if gr is not None and (gr.approved is not False or gr.real_generation_authorization is not None):
        # Defensive, should be structurally impossible via P3.14/P3.15's
        # own hardcoding -- a real contract violation if it ever
        # happens, never silently accepted (Section 8/9, authority
        # separation).
        return HandoffFinding(
            "not_already_authorized", False,
            "review.generation_request is already approved/authorized -- a "
            "handoff must never be created from an already-authorized "
            "generation_request; this would violate the authority boundary.",
            HandoffFailureCategory.INTERNAL_HANDOFF_FAILURE,
        )
    return HandoffFinding("not_already_authorized", True, "generation_request carries no authorization.")


def _check_production_readiness_prerequisites(review: PreProductionReview) -> HandoffFinding:
    if review.status == PreProductionReviewStatus.PASS:
        if review.generation_request is None or review.production_preparation is None:
            return HandoffFinding(
                "production_readiness_prerequisites", False,
                "review.status is PASS but generation_request or "
                "production_preparation is missing -- structurally "
                "impossible per PreProductionReviewer's own guarantees; "
                "refusing to hand off regardless.",
                HandoffFailureCategory.INTERNAL_HANDOFF_FAILURE,
            )
    return HandoffFinding(
        "production_readiness_prerequisites", True,
        "generation_request/production_preparation presence is consistent with review.status.",
    )


def _check_expected_review_id(review: PreProductionReview, expected_review_id: Optional[str]) -> HandoffFinding:
    if expected_review_id is None:
        return HandoffFinding(
            "expected_review_id_pin", True, "No expected_review_id was pinned by the caller.",
        )
    if review.review_id != expected_review_id:
        return HandoffFinding(
            "expected_review_id_pin", False,
            f"review.review_id '{review.review_id}' does not match the caller-"
            f"pinned expected_review_id '{expected_review_id}' -- stale or "
            f"mismatched review.",
            HandoffFailureCategory.STALE_OR_MISMATCHED_REVIEW,
        )
    return HandoffFinding("expected_review_id_pin", True, f"review_id='{review.review_id}' matches pin.")


def _check_expected_request_id(review: PreProductionReview, expected_request_id: Optional[str]) -> HandoffFinding:
    if expected_request_id is None:
        return HandoffFinding(
            "expected_request_id_pin", True, "No expected_request_id was pinned by the caller.",
        )
    if review.request_id != expected_request_id:
        return HandoffFinding(
            "expected_request_id_pin", False,
            f"review.request_id '{review.request_id}' does not match the "
            f"caller-pinned expected_request_id '{expected_request_id}' -- "
            f"stale or mismatched review.",
            HandoffFailureCategory.STALE_OR_MISMATCHED_REVIEW,
        )
    return HandoffFinding("expected_request_id_pin", True, f"request_id='{review.request_id}' matches pin.")


# ----------------------------------------------------------------------
# BUILDER (Section 4/11) -- single responsibility: formalize the STOP
# point between PreProductionReview and the P2 authority boundary.
# Never orchestrates agents, never becomes the State Machine, never a
# production executor, never invokes the P2 boundary it references.
# ----------------------------------------------------------------------


class ProductionReadinessHandoffBuilder:
    """
    AI DIRECTOR — Production Readiness Handoff Builder (P3.17)

    Stateless: holds no injected collaborator, no provider, no lock, no
    state machine reference. `build()` is a pure function of its
    `ProductionReadinessHandoffInput`.
    """

    def build(self, request: ProductionReadinessHandoffInput) -> ProductionReadinessHandoff:
        if not isinstance(request.review, PreProductionReview):
            raise ProductionReadinessHandoffError(
                "review is not a valid PreProductionReview instance; this "
                "module never fabricates one."
            )

        review = request.review

        findings: list = [
            _check_review_structural_validity(review),
            _check_review_contract_version(review),
            _check_review_integrity(review),
            _check_review_status_pass(review),
            _check_request_identity_consistency(review),
            _check_mission_identity_consistency(review),
            _check_not_already_authorized(review),
            _check_production_readiness_prerequisites(review),
            _check_expected_review_id(review, request.expected_review_id),
            _check_expected_request_id(review, request.expected_request_id),
        ]
        findings_t = tuple(findings)

        reasons = tuple(f.detail for f in findings_t if not f.passed)
        status = (
            ProductionReadinessHandoffStatus.NOT_READY
            if reasons
            else ProductionReadinessHandoffStatus.READY_FOR_PRODUCTION_AUTHORITY
        )

        clock = request.clock or _default_clock
        handoff_id = request.handoff_id or uuid.uuid4().hex
        created_at = clock()

        content_hash = compute_handoff_hash(
            request_id=review.request_id,
            mission_id=review.mission_id,
            review_id=review.review_id,
            status=status.value,
            findings=findings_t,
            review_content_hash=review.content_hash,
            contract_version=HANDOFF_CONTRACT_VERSION,
        )

        return ProductionReadinessHandoff(
            handoff_id=handoff_id,
            artifact_type=HANDOFF_ARTIFACT_TYPE,
            created_at=created_at,
            contract_version=HANDOFF_CONTRACT_VERSION,
            request_id=review.request_id,
            mission_id=review.mission_id,
            review_id=review.review_id,
            status=status,
            findings=findings_t,
            reasons=reasons,
            review=review,
            producer_agent=PRODUCER_AGENT,
            producer_version=PRODUCER_VERSION,
            content_hash=content_hash,
        )
