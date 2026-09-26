"""
AI DIRECTOR — Activation Eligibility (Phase P3.20)

ELIGIBILITY BOUNDARY ONLY, built directly against the REAL contracts
re-read from disk before writing a line of this module: `agents/
human_authorization_handoff.py` (P3.19, `HumanAuthorizationHandoffBuilder.
build()` -> `HumanAuthorizationHandoff`, carrying `intake`
(`ProductionAuthorityIntakeReport`, P3.18) verbatim), and the full
existing P2 activation chain re-audited from disk this phase: `agents/
activation_contract.py` (Phase P2.21, `RequestScopedActivationContract`/
`RequestScopedActivationService`), `agents/controlled_real_provider_
activation.py` (Phase P2.26, `ControlledRealProviderActivationContract`/
`ControlledRealProviderActivationService`), `agents/real_provider_
execution_gate.py` (Phase P2.36 -- composes P2.24+P2.26 by pure,
non-mutating inspection, never `prepare()`/`validate()`), `agents/
critical_section_lock.py` (Phase P2.20), `agents/executed_request_
store.py` (Phase P2.15), and `director.py` (`AIDirector.prepare_real_
generation_activation()`, Phase P2.29 -- the pre-existing explicit
human/caller entry point that actually calls `prepare_activation()`,
never duplicated or invoked here).

RESPONSIBILITY (P3.20 Section 5): given a P3.19 `HumanAuthorization
Handoff`, and OPTIONAL caller-supplied, ALREADY-PREPARED activation
snapshots (`RequestScopedActivationContract` from Phase P2.21,
`ControlledRealProviderActivationContract` from Phase P2.26 -- NEITHER
ever constructed by this module), determine whether this request is
ELIGIBLE for the caller to proceed to the existing P2 activation
boundary, or whether an already-supplied activation snapshot is
STRUCTURALLY VALID and correctly bound -- and STOP. This module never
activates on its own initiative, never calls `prepare_activation()`/
`.prepare()` (which would construct a real ephemeral contract), never
calls `validate_activation()`/`.validate()` (which would CONSUME one),
and never calls the P2 chain at all (`GenerationApprovalGate`,
`RequestScopedActivationService`, `ControlledRealProviderActivation
Service`, `GenerationJobService`) -- same "never touch the Gate/
Provider, even read-only" lesson P3.18/P3.19 already established (see
those modules' own docstrings: `gate.evaluate()`, reached transitively
by `RequestScopedActivationService.prepare_activation()`/`inspect_
activation()` alike via `_fresh_violations()`, calls `HiggsfieldClient.
get_account_balance()`/`estimate_cost()` -- real CLI subprocess calls).
A `HumanAuthorizationHandoff`/`RealGenerationAuthorization` is NEVER
treated as activation on its own, and neither is `review.status==PASS`,
`handoff.status==READY_FOR_PRODUCTION_AUTHORITY`,
`intake.status==ACCEPTED_FOR_P2_CONSIDERATION`, or
`authorized_by_human==True`.

WHY THIS MODULE NEVER CALLS `prepare_activation()`/`.prepare()` OR
`validate_activation()`/`.validate()` (Section 0/8/9/14 -- the single
most important rule of this phase): both already exist, unmodified, at
Phase P2.21/P2.26, and remain the caller's own, separate, explicit
responsibility (that caller is `director.py::AIDirector.prepare_real_
generation_activation()`, Phase P2.29, re-audited unchanged this
phase). `prepare_activation()` calls `gate.evaluate(request)`
internally -- the exact real-CLI-subprocess risk P3.18 already
identified and refused to touch, carried forward unchanged.
`validate_activation()`/`.validate()` additionally CONSUME the
contract (Section 14: "authorization validation != activation
consumption") -- an irreversible, single-use side effect this
read-only eligibility layer must never trigger merely by inspecting a
contract. Per Section 8's "if the existing P2 contract requires an
explicit caller to prepare activation: preserve that requirement" and
Section 7's "reuse, don't create a second activation authority", this
module performs ONLY structural, offline, zero-I/O checks: the same
`isinstance`/field-equality/`prompt_sha256`-recomputation pattern
ALREADY established, independently, in THREE places in this codebase
(`agents/activation_contract.py::_activation_violations()`, `agents/
controlled_real_provider_activation.py::_violations()`, `integrations/
higgsfield/provider.py::_provider_activation_violations()` -- the
latter explicitly documented as "PUREMENT LOCALE" and based only on
`contract.created_at`). Adding a FOURTH, equally inert, equally
side-effect-free copy of that same structural pattern is the same
established idiom, not a new authority.

NO EXECUTION / NO ACTIVATION / NO AUTOMATIC AUTHORIZATION (Section 0/
9/13/14/16): this module never imports `agents.generation_approval_
gate.GenerationApprovalGate`, `agents.generation_job_service.
GenerationJobService`, `agents.activation_contract.
RequestScopedActivationService`, `agents.controlled_real_provider_
activation.ControlledRealProviderActivationService`, `agents.
activation_readiness`, `agents.real_provider_execution_gate`, `agents.
real_provider_activation_preflight`, `agents.critical_section_lock`,
`agents.executed_request_store`, `integrations.higgsfield.provider.
HiggsfieldProvider`, `integrations.higgsfield.client.HiggsfieldClient`,
or `agents.mission_state_machine`, and never calls `create_job`,
`.evaluate(`, `.execute(`, `.transition(`, `prepare_activation`,
`validate_activation`, `.consume(`, `.prepare(`, `.validate(`,
`prepare_real_generation_activation`, or `execute_real_generation_
activation`. `RequestScopedActivationContract`/`ControlledRealProvider
ActivationContract` are imported ONLY as types (for `isinstance` checks
and type hints, and to read their already-computed public fields) --
this module contains exactly ZERO constructor invocations of either
(verified by a dedicated AST test distinguishing a `Call` node from a
`Name`/attribute reference, same discipline as P3.19's own `Real
GenerationAuthorization` test). `ActivationEligibilityStatus` has
exactly four values -- `HUMAN_AUTHORIZATION_NOT_VALID`, `ELIGIBLE_FOR_
ACTIVATION`, `ACTIVATION_CONTRACT_STRUCTURALLY_VALID`, `NOT_ELIGIBLE_
FOR_ACTIVATION` -- deliberately never `ACTIVATED`, `EXECUTING`, or
`EXECUTED` (Section 6's "do not collapse these states"). Even when a
genuinely valid, correctly-bound activation snapshot is supplied, this
module reports only `ACTIVATION_CONTRACT_STRUCTURALLY_VALID` -- never
`ACTIVATED` -- because that stronger claim would require the live
service's fresh Gate/Identity-Lock/replay re-verification and single-
use consumption this module deliberately never performs.

SCOPE BOUNDARY -- STALENESS/REVOCATION/SINGLE-USE (Section 13/14/15,
mirrors P3.19's own documented "structurally unreachable" pattern):
`RequestScopedActivationContract`/`ControlledRealProviderActivation
Contract` carry a public `created_at` field but NO public "revoked"/
"consumed" field -- that state lives exclusively inside the issuing
`RequestScopedActivationService`/`ControlledRealProviderActivation
Service` instance's private, in-memory bookkeeping (`_issued_at`,
`_consumed_activation_ids`), never exposed on the contract dataclass
itself and never duplicated by a second bookkeeping system here
(Section 7). This module therefore performs a PURELY LOCAL staleness
SANITY check from `contract.created_at` alone -- the exact same
pattern, deliberately mirrored, as `integrations/higgsfield/provider.
py::_provider_activation_violations()`'s own "purement locale au
Provider" freshness check, using the SAME default `max_age_seconds`
(300.0, Phase P2.21's own default, never a new invented value) and an
injectable `now` clock (never a second uninjectable clock). This is
NOT the authoritative expiry/consumption/revocation check -- that
remains exclusively `RequestScopedActivationService.inspect_
activation()`'s job, never performed here. `EligibilityFailureCategory.
AUTHORIZATION_REVOKED` and `.ACTIVATION_ALREADY_CONSUMED` are DEFINED
(Section 17/25 name them explicitly) but structurally UNREACHABLE by
any check in this module -- dedicated tests assert this.

BUDGET (Section 21): this module carries no budget/cost dimension, for
the same reason P3.18/P3.19 carry none -- inspecting it honestly would
require the live Gate/Provider chain this module deliberately never
touches. `expected_cost_credits` (a field already present, verbatim,
on a caller-supplied `ControlledRealProviderActivationContract`) is
read back ONLY for traceability in a finding's `detail` text, NEVER
compared, approved, or fabricated.

STATE MACHINE (Section 19): this module never imports `agents.
mission_state_machine` and never calls `.transition()`. Whether an
`ELIGIBLE_FOR_ACTIVATION` or `ACTIVATION_CONTRACT_STRUCTURALLY_VALID`
result here should ever be reflected as a Mission State transition
remains exclusively a Director/Orchestrator decision, never exercised
by this module.

IMMUTABILITY / DETERMINISM / IDEMPOTENCY (Section 22/23/24): this
module never imports `dataclasses.replace` and never assigns to any
attribute of `HumanAuthorizationHandoff`, `ProductionAuthorityIntake
Report`, `ProductionReadinessHandoff`, `PreProductionReview`,
`GenerationRequest`, `RealGenerationAuthorization`, `RequestScoped
ActivationContract`, or `ControlledRealProviderActivationContract` --
all frozen anyway. `check_eligibility()` is a pure function of its
input, including the injected `now`/`clock` callables: identical
immutable input (same handoff, same optional contracts, same frozen
`now`) always yields findings/status/`content_hash` that are equal by
value. No production side effect of any kind occurs, ever, regardless
of how many times the same input is checked.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional, Tuple

from agents.activation_contract import RequestScopedActivationContract
from agents.controlled_real_provider_activation import ControlledRealProviderActivationContract
from agents.human_authorization_handoff import (
    HANDOFF_ARTIFACT_TYPE as HUMAN_AUTHORIZATION_HANDOFF_ARTIFACT_TYPE,
    HANDOFF_CONTRACT_VERSION as HUMAN_AUTHORIZATION_HANDOFF_CONTRACT_VERSION,
    HumanAuthorizationHandoff,
    HumanAuthorizationHandoffStatus,
    compute_human_authorization_handoff_hash,
)

ELIGIBILITY_CONTRACT_VERSION = 1
ELIGIBILITY_ARTIFACT_TYPE = "ActivationEligibilityResult"
PRODUCER_AGENT = "activation-eligibility"
PRODUCER_VERSION = "1.0"

# Phase P2.21's own default (agents/activation_contract.py::
# RequestScopedActivationService.__init__) -- never a new invented
# value, reused verbatim as this module's own default too.
DEFAULT_MAX_AGE_SECONDS = 300.0

SUPPORTED_HUMAN_AUTHORIZATION_HANDOFF_CONTRACT_VERSIONS = frozenset(
    {HUMAN_AUTHORIZATION_HANDOFF_CONTRACT_VERSION}
)


class ActivationEligibilityError(ValueError):
    """Raised for a structurally invalid `ActivationEligibilityInput`
    (e.g. `human_authorization_handoff` is not a real `Human
    AuthorizationHandoff`) -- never a silent fallback."""


class ActivationEligibilityStatus(str, Enum):
    """
    Exactly four values, deliberately never `ACTIVATED`, `EXECUTING`,
    or `EXECUTED` (Section 6/9/13/14) -- this result can only ever say
    whether the underlying human authorization is valid, whether this
    request is merely eligible to proceed to the existing P2 activation
    boundary, or whether an already-supplied activation snapshot is
    structurally valid -- never anything about activation itself.
    """

    HUMAN_AUTHORIZATION_NOT_VALID = "HUMAN_AUTHORIZATION_NOT_VALID"
    ELIGIBLE_FOR_ACTIVATION = "ELIGIBLE_FOR_ACTIVATION"
    ACTIVATION_CONTRACT_STRUCTURALLY_VALID = "ACTIVATION_CONTRACT_STRUCTURALLY_VALID"
    NOT_ELIGIBLE_FOR_ACTIVATION = "NOT_ELIGIBLE_FOR_ACTIVATION"


class EligibilityFailureCategory(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"
    HANDOFF_INTEGRITY_FAILURE = "HANDOFF_INTEGRITY_FAILURE"
    CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
    AUTHORIZATION_MISSING = "AUTHORIZATION_MISSING"
    AUTHORIZATION_INVALID = "AUTHORIZATION_INVALID"
    AUTHORIZATION_REQUEST_MISMATCH = "AUTHORIZATION_REQUEST_MISMATCH"
    # Defined per Section 17/25's explicit failure-semantics vocabulary
    # -- structurally UNREACHABLE by this stateless module (see module
    # docstring "SCOPE BOUNDARY"). Revocation/consumption tracking
    # remains exclusively agents.activation_contract's/agents.
    # controlled_real_provider_activation's responsibility.
    AUTHORIZATION_REVOKED = "AUTHORIZATION_REVOKED"
    ACTIVATION_ALREADY_CONSUMED = "ACTIVATION_ALREADY_CONSUMED"
    # A LOCAL staleness sanity check only (contract.created_at-based,
    # mirrors integrations/higgsfield/provider.py's own freshness
    # check) -- never the authoritative P2.21 expiry.
    AUTHORIZATION_EXPIRED = "AUTHORIZATION_EXPIRED"
    ACTIVATION_CONTRACT_INVALID = "ACTIVATION_CONTRACT_INVALID"
    ACTIVATION_CONTRACT_MISMATCH = "ACTIVATION_CONTRACT_MISMATCH"
    ACTIVATION_ELIGIBILITY_FAILED = "ACTIVATION_ELIGIBILITY_FAILED"
    INTERNAL_ELIGIBILITY_FAILURE = "INTERNAL_ELIGIBILITY_FAILURE"


# ----------------------------------------------------------------------
# INPUT CONTRACT (Section 5/8/11)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ActivationEligibilityInput:
    human_authorization_handoff: HumanAuthorizationHandoff

    # NEVER constructed internally -- both are externally-prepared
    # snapshots a caller obtained from the real, unmodified P2.21/P2.26
    # services (via those services' own preparation methods, called by
    # the CALLER, never by this module). `None` (the default) means
    # "no activation snapshot has been prepared yet".
    activation_contract: Optional[RequestScopedActivationContract] = None
    provider_activation_contract: Optional[ControlledRealProviderActivationContract] = None

    # Local staleness SANITY check parameters only -- mirrors Phase
    # P2.21's own default and integrations/higgsfield/provider.py's own
    # injectable-clock discipline. Never the authoritative expiry.
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS
    now: Optional[Callable[[], datetime]] = None

    eligibility_id: Optional[str] = None
    clock: Optional[Callable[[], str]] = None


# ----------------------------------------------------------------------
# OUTPUT CONTRACT -- immutable.
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class EligibilityFinding:
    dimension: str
    passed: bool
    detail: str
    category: Optional[EligibilityFailureCategory] = None  # None iff passed


@dataclass(frozen=True)
class ActivationEligibilityResult:
    eligibility_id: str
    artifact_type: str
    created_at: str
    contract_version: int

    request_id: Optional[str]
    mission_id: str
    review_id: str
    intake_id: str
    handoff_id: str  # HumanAuthorizationHandoff.handoff_id

    status: ActivationEligibilityStatus
    findings: Tuple[EligibilityFinding, ...]
    reasons: Tuple[str, ...]  # detail of every failing finding, in order

    human_authorization_handoff: HumanAuthorizationHandoff  # verbatim,
    # never rewritten -- full chain (mission_id -> script_artifact ->
    # production_preparation -> generation_request -> review -> handoff
    # -> intake -> human_authorization_handoff) is reachable through
    # this single field.

    activation_contract: Optional[RequestScopedActivationContract]  # verbatim pass-through
    provider_activation_contract: Optional[ControlledRealProviderActivationContract]  # verbatim pass-through

    producer_agent: str
    producer_version: str

    content_hash: str


def _default_clock() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_now() -> datetime:
    return datetime.now(timezone.utc)


def compute_activation_eligibility_hash(
    request_id: Optional[str],
    mission_id: str,
    review_id: str,
    intake_id: str,
    handoff_id: str,
    status: str,
    findings: Tuple[EligibilityFinding, ...],
    handoff_content_hash: str,
    activation_contract_id: Optional[str],
    provider_activation_contract_id: Optional[str],
    contract_version: int,
) -> str:
    canonical = {
        "request_id": request_id,
        "mission_id": mission_id,
        "review_id": review_id,
        "intake_id": intake_id,
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
        "activation_contract_id": activation_contract_id,
        "provider_activation_contract_id": provider_activation_contract_id,
        "contract_version": contract_version,
    }
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# HANDOFF-LEVEL DIMENSIONS (Section 9/11) -- re-verify the P3.19
# handoff's own structural validity at this layer, never re-deriving
# P3.15/P3.17/P3.18/P3.19's own business logic.
# ----------------------------------------------------------------------


def _check_handoff_structural_validity(handoff: HumanAuthorizationHandoff) -> EligibilityFinding:
    if handoff.artifact_type != HUMAN_AUTHORIZATION_HANDOFF_ARTIFACT_TYPE:
        return EligibilityFinding(
            "handoff_structural_validity", False,
            f"human_authorization_handoff.artifact_type "
            f"'{handoff.artifact_type}' is not "
            f"'{HUMAN_AUTHORIZATION_HANDOFF_ARTIFACT_TYPE}'.",
            EligibilityFailureCategory.INVALID_INPUT,
        )
    if not isinstance(handoff.handoff_id, str) or not handoff.handoff_id.strip():
        return EligibilityFinding(
            "handoff_structural_validity", False,
            f"human_authorization_handoff.handoff_id is missing or "
            f"empty ({handoff.handoff_id!r}).",
            EligibilityFailureCategory.INVALID_INPUT,
        )
    return EligibilityFinding("handoff_structural_validity", True, f"handoff_id='{handoff.handoff_id}'.")


def _check_handoff_contract_version(handoff: HumanAuthorizationHandoff) -> EligibilityFinding:
    if handoff.contract_version not in SUPPORTED_HUMAN_AUTHORIZATION_HANDOFF_CONTRACT_VERSIONS:
        return EligibilityFinding(
            "handoff_contract_version_compatibility", False,
            f"human_authorization_handoff.contract_version "
            f"{handoff.contract_version} is not supported (supported: "
            f"{sorted(SUPPORTED_HUMAN_AUTHORIZATION_HANDOFF_CONTRACT_VERSIONS)}).",
            EligibilityFailureCategory.CONTRACT_MISMATCH,
        )
    return EligibilityFinding(
        "handoff_contract_version_compatibility", True,
        f"human_authorization_handoff.contract_version={handoff.contract_version}.",
    )


def _check_handoff_integrity(handoff: HumanAuthorizationHandoff) -> EligibilityFinding:
    recomputed = compute_human_authorization_handoff_hash(
        request_id=handoff.request_id,
        mission_id=handoff.mission_id,
        review_id=handoff.review_id,
        intake_id=handoff.intake_id,
        status=handoff.status.value,
        findings=handoff.findings,
        intake_content_hash=handoff.intake.content_hash,
        authorization_id=handoff.authorization_id,
        contract_version=handoff.contract_version,
    )
    if recomputed != handoff.content_hash:
        return EligibilityFinding(
            "handoff_integrity", False,
            "human_authorization_handoff.content_hash does not match its "
            "own recomputed hash -- the handoff may have been tampered "
            "with or is otherwise corrupted; refusing to consider "
            "activation eligibility for an inconsistent handoff.",
            EligibilityFailureCategory.HANDOFF_INTEGRITY_FAILURE,
        )
    return EligibilityFinding("handoff_integrity", True, "human_authorization_handoff.content_hash matches recomputed hash.")


def _check_identity_chain_consistency(handoff: HumanAuthorizationHandoff) -> EligibilityFinding:
    intake = handoff.intake
    review = intake.handoff.review

    if handoff.intake_id != intake.intake_id:
        return EligibilityFinding(
            "identity_chain_consistency", False,
            f"human_authorization_handoff.intake_id '{handoff.intake_id}' "
            f"does not match human_authorization_handoff.intake.intake_id "
            f"'{intake.intake_id}'.",
            EligibilityFailureCategory.CONTRACT_MISMATCH,
        )
    if handoff.review_id != review.review_id:
        return EligibilityFinding(
            "identity_chain_consistency", False,
            f"human_authorization_handoff.review_id '{handoff.review_id}' "
            f"does not match the reviewed request's review_id "
            f"'{review.review_id}'.",
            EligibilityFailureCategory.CONTRACT_MISMATCH,
        )
    if handoff.mission_id != review.mission_id:
        return EligibilityFinding(
            "identity_chain_consistency", False,
            f"human_authorization_handoff.mission_id '{handoff.mission_id}' "
            f"does not match the reviewed request's mission_id "
            f"'{review.mission_id}'.",
            EligibilityFailureCategory.CONTRACT_MISMATCH,
        )
    if handoff.request_id != review.request_id:
        return EligibilityFinding(
            "identity_chain_consistency", False,
            f"human_authorization_handoff.request_id '{handoff.request_id}' "
            f"does not match the reviewed request's request_id "
            f"'{review.request_id}'.",
            EligibilityFailureCategory.CONTRACT_MISMATCH,
        )
    return EligibilityFinding(
        "identity_chain_consistency", True,
        f"eligibility_id/handoff_id/intake_id/review_id/mission_id/"
        f"request_id are consistent across the full chain "
        f"(request_id='{handoff.request_id}').",
    )


def _check_human_authorization_valid(handoff: HumanAuthorizationHandoff) -> EligibilityFinding:
    if handoff.status == HumanAuthorizationHandoffStatus.AUTHORIZATION_STRUCTURALLY_VALID:
        return EligibilityFinding(
            "human_authorization_valid", True,
            f"human_authorization_handoff.status is "
            f"AUTHORIZATION_STRUCTURALLY_VALID (authorization_id="
            f"{handoff.authorization_id!r}).",
        )
    if handoff.status == HumanAuthorizationHandoffStatus.ELIGIBLE_FOR_HUMAN_AUTHORIZATION:
        return EligibilityFinding(
            "human_authorization_valid", False,
            "human_authorization_handoff.status is "
            "ELIGIBLE_FOR_HUMAN_AUTHORIZATION -- no explicit human "
            "authorization has been supplied upstream yet; activation "
            "eligibility can never be reached without one.",
            EligibilityFailureCategory.AUTHORIZATION_MISSING,
        )
    return EligibilityFinding(
        "human_authorization_valid", False,
        f"human_authorization_handoff.status is '{handoff.status.value}', "
        f"not AUTHORIZATION_STRUCTURALLY_VALID. Underlying handoff "
        f"reasons: {list(handoff.reasons)}.",
        EligibilityFailureCategory.AUTHORIZATION_INVALID,
    )


# ----------------------------------------------------------------------
# ACTIVATION-CONTRACT-LEVEL DIMENSIONS (Section 8/11/13) -- pure,
# defensive re-checks of EXTERNALLY-SUPPLIED, already-prepared
# activation snapshots. Never constructs one; never calls a live
# service method. `getattr(..., default=None)` is used deliberately so
# a wrong-type object never raises here, it only ever produces a typed,
# explicit rejection finding.
# ----------------------------------------------------------------------


def _generation_request_media_sha256(generation_request, role: str) -> Optional[str]:
    if generation_request.start_image is not None and generation_request.start_image.role == role:
        return generation_request.start_image.sha256
    for ref in generation_request.image_references:
        if ref.role == role:
            return ref.sha256
    return None


def _check_activation_contract_type(contract: object) -> EligibilityFinding:
    if not isinstance(contract, RequestScopedActivationContract):
        return EligibilityFinding(
            "activation_contract_type_valid", False,
            f"activation_contract is not a valid "
            f"RequestScopedActivationContract instance (got "
            f"{type(contract).__name__}).",
            EligibilityFailureCategory.ACTIVATION_CONTRACT_INVALID,
        )
    return EligibilityFinding("activation_contract_type_valid", True, "activation_contract is a valid RequestScopedActivationContract instance.")


def _check_activation_contract_binding(
    contract: object, expected_request_id: Optional[str], expected_authorization_id: Optional[str]
) -> EligibilityFinding:
    bound_request_id = getattr(contract, "request_id", None)
    if bound_request_id != expected_request_id:
        return EligibilityFinding(
            "activation_contract_request_binding", False,
            f"activation_contract is bound to request "
            f"{bound_request_id!r}, not to the authorized request "
            f"{expected_request_id!r}.",
            EligibilityFailureCategory.AUTHORIZATION_REQUEST_MISMATCH,
        )
    bound_authorization_id = getattr(contract, "authorization_id", None)
    if bound_authorization_id != expected_authorization_id:
        return EligibilityFinding(
            "activation_contract_request_binding", False,
            f"activation_contract.authorization_id {bound_authorization_id!r} "
            f"does not match the supplied authorization's authorization_id "
            f"{expected_authorization_id!r} -- this contract was not "
            f"prepared from the exact authorization being handed off.",
            EligibilityFailureCategory.ACTIVATION_CONTRACT_MISMATCH,
        )
    return EligibilityFinding(
        "activation_contract_request_binding", True,
        f"activation_contract bound to request_id={bound_request_id!r}, "
        f"authorization_id={bound_authorization_id!r}.",
    )


def _check_activation_contract_field_consistency(contract: object, generation_request) -> EligibilityFinding:
    mismatches = []
    for field_name in ("job_type", "duration", "resolution", "aspect_ratio"):
        contract_value = getattr(contract, field_name, None)
        request_value = getattr(generation_request, field_name, None)
        if contract_value != request_value:
            mismatches.append(f"{field_name}: contract={contract_value!r} request={request_value!r}")
    if mismatches:
        return EligibilityFinding(
            "activation_contract_field_consistency", False,
            f"activation_contract fields diverge from the reviewed "
            f"generation_request: {'; '.join(mismatches)}.",
            EligibilityFailureCategory.ACTIVATION_CONTRACT_MISMATCH,
        )
    return EligibilityFinding("activation_contract_field_consistency", True, "job_type/duration/resolution/aspect_ratio match the reviewed request.")


def _check_activation_contract_prompt_sha256(contract: object, generation_request) -> EligibilityFinding:
    prompt = generation_request.prompt if isinstance(generation_request.prompt, str) else ""
    actual = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    contract_value = getattr(contract, "prompt_sha256", None)
    if contract_value != actual:
        return EligibilityFinding(
            "activation_contract_prompt_integrity", False,
            f"activation_contract.prompt_sha256 {contract_value!r} does "
            f"not match the reviewed request's prompt sha256 {actual!r}.",
            EligibilityFailureCategory.ACTIVATION_CONTRACT_MISMATCH,
        )
    return EligibilityFinding("activation_contract_prompt_integrity", True, f"prompt_sha256='{actual}' matches.")


def _check_activation_contract_staleness(
    contract: object, now: datetime, max_age_seconds: float
) -> EligibilityFinding:
    created_at_raw = getattr(contract, "created_at", None)
    try:
        created_at = datetime.fromisoformat(created_at_raw)
    except (TypeError, ValueError):
        return EligibilityFinding(
            "activation_contract_staleness_sanity", False,
            f"activation_contract.created_at {created_at_raw!r} is not a "
            f"valid ISO-8601 timestamp -- cannot verify local freshness.",
            EligibilityFailureCategory.AUTHORIZATION_EXPIRED,
        )
    elapsed = (now - created_at).total_seconds()
    if elapsed > max_age_seconds or elapsed < 0:
        return EligibilityFinding(
            "activation_contract_staleness_sanity", False,
            f"activation_contract age ({elapsed:.1f}s) exceeds this "
            f"module's local freshness sanity threshold "
            f"({max_age_seconds}s), or is negative (clock inconsistency) "
            f"-- a purely local sanity check, never a substitute for the "
            f"authoritative RequestScopedActivationService expiry.",
            EligibilityFailureCategory.AUTHORIZATION_EXPIRED,
        )
    return EligibilityFinding("activation_contract_staleness_sanity", True, f"activation_contract age ({elapsed:.1f}s) is within the local sanity threshold.")


def _check_provider_activation_contract_type(contract: object) -> EligibilityFinding:
    if not isinstance(contract, ControlledRealProviderActivationContract):
        return EligibilityFinding(
            "provider_activation_contract_type_valid", False,
            f"provider_activation_contract is not a valid "
            f"ControlledRealProviderActivationContract instance (got "
            f"{type(contract).__name__}).",
            EligibilityFailureCategory.ACTIVATION_CONTRACT_INVALID,
        )
    return EligibilityFinding("provider_activation_contract_type_valid", True, "provider_activation_contract is a valid ControlledRealProviderActivationContract instance.")


def _check_provider_activation_contract_binding(
    provider_contract: object, activation_contract: object, expected_request_id: Optional[str]
) -> EligibilityFinding:
    bound_request_id = getattr(provider_contract, "request_id", None)
    if bound_request_id != expected_request_id:
        return EligibilityFinding(
            "provider_activation_contract_binding", False,
            f"provider_activation_contract is bound to request "
            f"{bound_request_id!r}, not to the authorized request "
            f"{expected_request_id!r}.",
            EligibilityFailureCategory.AUTHORIZATION_REQUEST_MISMATCH,
        )
    bound_scoped_id = getattr(provider_contract, "request_scoped_activation_id", None)
    activation_id = getattr(activation_contract, "activation_id", None)
    if bound_scoped_id != activation_id:
        return EligibilityFinding(
            "provider_activation_contract_binding", False,
            f"provider_activation_contract.request_scoped_activation_id "
            f"{bound_scoped_id!r} does not match the supplied "
            f"activation_contract.activation_id {activation_id!r} -- not "
            f"transferable between activations.",
            EligibilityFailureCategory.ACTIVATION_ELIGIBILITY_FAILED,
        )
    return EligibilityFinding(
        "provider_activation_contract_binding", True,
        f"provider_activation_contract bound to request_id={bound_request_id!r}, "
        f"request_scoped_activation_id={bound_scoped_id!r}.",
    )


def _check_provider_activation_contract_field_consistency(contract: object, generation_request) -> EligibilityFinding:
    mismatches = []
    for field_name in ("job_type", "duration", "resolution", "aspect_ratio"):
        contract_value = getattr(contract, field_name, None)
        request_value = getattr(generation_request, field_name, None)
        if contract_value != request_value:
            mismatches.append(f"{field_name}: contract={contract_value!r} request={request_value!r}")
    prompt = generation_request.prompt if isinstance(generation_request.prompt, str) else ""
    actual_prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if getattr(contract, "prompt_sha256", None) != actual_prompt_sha256:
        mismatches.append("prompt_sha256 mismatch")
    if getattr(contract, "avatar_sha256", None) != _generation_request_media_sha256(generation_request, "master_avatar"):
        mismatches.append("avatar_sha256 mismatch")
    if getattr(contract, "face_reference_sha256", None) != _generation_request_media_sha256(generation_request, "face_reference"):
        mismatches.append("face_reference_sha256 mismatch")
    if mismatches:
        return EligibilityFinding(
            "provider_activation_contract_field_consistency", False,
            f"provider_activation_contract fields diverge from the "
            f"reviewed generation_request: {'; '.join(mismatches)}.",
            EligibilityFailureCategory.ACTIVATION_CONTRACT_MISMATCH,
        )
    return EligibilityFinding("provider_activation_contract_field_consistency", True, "job_type/duration/resolution/aspect_ratio/prompt/avatar/face-reference match the reviewed request.")


def _check_provider_activation_contract_staleness(
    contract: object, now: datetime, max_age_seconds: float
) -> EligibilityFinding:
    created_at_raw = getattr(contract, "created_at", None)
    try:
        created_at = datetime.fromisoformat(created_at_raw)
    except (TypeError, ValueError):
        return EligibilityFinding(
            "provider_activation_contract_staleness_sanity", False,
            f"provider_activation_contract.created_at {created_at_raw!r} "
            f"is not a valid ISO-8601 timestamp -- cannot verify local "
            f"freshness.",
            EligibilityFailureCategory.AUTHORIZATION_EXPIRED,
        )
    elapsed = (now - created_at).total_seconds()
    if elapsed > max_age_seconds or elapsed < 0:
        return EligibilityFinding(
            "provider_activation_contract_staleness_sanity", False,
            f"provider_activation_contract age ({elapsed:.1f}s) exceeds "
            f"this module's local freshness sanity threshold "
            f"({max_age_seconds}s), or is negative -- a purely local "
            f"sanity check, never a substitute for the authoritative "
            f"ControlledRealProviderActivationService expiry.",
            EligibilityFailureCategory.AUTHORIZATION_EXPIRED,
        )
    return EligibilityFinding("provider_activation_contract_staleness_sanity", True, f"provider_activation_contract age ({elapsed:.1f}s) is within the local sanity threshold.")


# ----------------------------------------------------------------------
# CHECKER (Section 5/7) -- single responsibility: formalize the fourth
# STOP point, between HumanAuthorizationHandoff and the existing P2
# activation boundary. Never orchestrates agents, never becomes the
# State Machine, never a production executor, never prepares,
# validates, or consumes an activation contract.
# ----------------------------------------------------------------------


class ActivationEligibilityChecker:
    """
    AI DIRECTOR — Activation Eligibility Checker (P3.20)

    Stateless: holds no injected collaborator, no provider, no gate, no
    service, no lock, no state machine reference. `check_eligibility()`
    is a pure function of its `ActivationEligibilityInput` (including
    the injected `now`/`clock` callables).
    """

    def check_eligibility(self, request: ActivationEligibilityInput) -> ActivationEligibilityResult:
        if not isinstance(request.human_authorization_handoff, HumanAuthorizationHandoff):
            raise ActivationEligibilityError(
                "human_authorization_handoff is not a valid "
                "HumanAuthorizationHandoff instance; this module never "
                "fabricates one."
            )

        handoff = request.human_authorization_handoff

        handoff_findings: list = [
            _check_handoff_structural_validity(handoff),
            _check_handoff_contract_version(handoff),
            _check_handoff_integrity(handoff),
            _check_identity_chain_consistency(handoff),
        ]
        handoff_reasons = tuple(f.detail for f in handoff_findings if not f.passed)

        auth_finding = _check_human_authorization_valid(handoff)

        activation_contract = request.activation_contract
        provider_activation_contract = request.provider_activation_contract
        now = (request.now or _default_now)()

        activation_findings: tuple = ()

        if handoff_reasons:
            status = ActivationEligibilityStatus.NOT_ELIGIBLE_FOR_ACTIVATION
            reasons = handoff_reasons
        elif not auth_finding.passed:
            status = ActivationEligibilityStatus.HUMAN_AUTHORIZATION_NOT_VALID
            reasons = (auth_finding.detail,)
        elif activation_contract is None:
            status = ActivationEligibilityStatus.ELIGIBLE_FOR_ACTIVATION
            activation_findings = (
                EligibilityFinding(
                    "activation_contract_presence", True,
                    "No activation_contract was supplied -- this request "
                    "is structurally eligible for a caller to separately "
                    "obtain one via the existing, unmodified "
                    "RequestScopedActivationService's own activation-"
                    "preparation method. This module never does so "
                    "automatically.",
                ),
            )
            reasons = ()
        else:
            generation_request = handoff.intake.handoff.review.generation_request
            contract_type_finding = _check_activation_contract_type(activation_contract)

            if not contract_type_finding.passed:
                activation_findings = (contract_type_finding,)
            else:
                activation_findings = (
                    contract_type_finding,
                    _check_activation_contract_binding(
                        activation_contract, handoff.request_id, handoff.authorization_id
                    ),
                    _check_activation_contract_field_consistency(activation_contract, generation_request),
                    _check_activation_contract_prompt_sha256(activation_contract, generation_request),
                    _check_activation_contract_staleness(activation_contract, now, request.max_age_seconds),
                )

                if provider_activation_contract is not None:
                    provider_type_finding = _check_provider_activation_contract_type(provider_activation_contract)
                    if not provider_type_finding.passed:
                        activation_findings = activation_findings + (provider_type_finding,)
                    else:
                        activation_findings = activation_findings + (
                            provider_type_finding,
                            _check_provider_activation_contract_binding(
                                provider_activation_contract, activation_contract, handoff.request_id
                            ),
                            _check_provider_activation_contract_field_consistency(
                                provider_activation_contract, generation_request
                            ),
                            _check_provider_activation_contract_staleness(
                                provider_activation_contract, now, request.max_age_seconds
                            ),
                        )

            activation_reasons = tuple(f.detail for f in activation_findings if not f.passed)
            if activation_reasons:
                status = ActivationEligibilityStatus.NOT_ELIGIBLE_FOR_ACTIVATION
                reasons = activation_reasons
            else:
                status = ActivationEligibilityStatus.ACTIVATION_CONTRACT_STRUCTURALLY_VALID
                reasons = ()

        findings_t = tuple(handoff_findings) + (auth_finding,) + tuple(activation_findings)

        clock = request.clock or _default_clock
        eligibility_id = request.eligibility_id or uuid.uuid4().hex
        created_at = clock()

        content_hash = compute_activation_eligibility_hash(
            request_id=handoff.request_id,
            mission_id=handoff.mission_id,
            review_id=handoff.review_id,
            intake_id=handoff.intake_id,
            handoff_id=handoff.handoff_id,
            status=status.value,
            findings=findings_t,
            handoff_content_hash=handoff.content_hash,
            activation_contract_id=getattr(activation_contract, "activation_id", None),
            provider_activation_contract_id=getattr(provider_activation_contract, "activation_id", None),
            contract_version=ELIGIBILITY_CONTRACT_VERSION,
        )

        return ActivationEligibilityResult(
            eligibility_id=eligibility_id,
            artifact_type=ELIGIBILITY_ARTIFACT_TYPE,
            created_at=created_at,
            contract_version=ELIGIBILITY_CONTRACT_VERSION,
            request_id=handoff.request_id,
            mission_id=handoff.mission_id,
            review_id=handoff.review_id,
            intake_id=handoff.intake_id,
            handoff_id=handoff.handoff_id,
            status=status,
            findings=findings_t,
            reasons=reasons,
            human_authorization_handoff=handoff,
            activation_contract=activation_contract,
            provider_activation_contract=provider_activation_contract,
            producer_agent=PRODUCER_AGENT,
            producer_version=PRODUCER_VERSION,
            content_hash=content_hash,
        )
