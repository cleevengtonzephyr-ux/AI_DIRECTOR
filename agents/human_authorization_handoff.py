"""
AI DIRECTOR — Human Authorization Handoff (Phase P3.19)

HANDOFF BOUNDARY ONLY, built directly against the REAL contracts
re-read from disk before writing a line of this module: `agents/
production_authority_intake.py` (P3.18, `ProductionAuthorityIntake.
intake()` -> `ProductionAuthorityIntakeReport`, carrying `handoff`
(`ProductionReadinessHandoff`, P3.17) verbatim), and the full existing
P2 human-authorization chain re-audited from disk this phase: `agents/
generation_approval_gate.py` (`RealGenerationAuthorization`, Phase
P2.11 -- imported here ONLY as a type, exactly as every other P3
module already does; `GenerationApprovalGate` itself is never
imported), `agents/activation_contract.py` (Phase P2.21,
`RequestScopedActivationService.prepare_activation()`'s own
authorization check), and `director.py` (`AIDirector.prepare_real_
generation_activation()`, Phase P2.29 -- the pre-existing real human
entry point, never duplicated here).

RESPONSIBILITY (P3.19 Section 5): given a P3.18 `ProductionAuthority
IntakeReport`, and an OPTIONAL caller-supplied `RealGenerationAuthorization`
(never constructed by this module), determine whether this request is
merely ELIGIBLE to receive explicit human authorization, or whether an
already-supplied authorization is STRUCTURALLY VALID and correctly
bound to it -- and STOP. This module never authorizes on its own
initiative, never activates, never executes, and never calls the P2
chain (`GenerationApprovalGate`, `RequestScopedActivationService`,
`ControlledRealProviderActivationService`, `GenerationJobService`) --
same "never touch the Gate/Provider, even read-only" lesson P3.18
already established (see that module's own docstring: `gate.evaluate()`
transitively reaches `HiggsfieldClient` via `get_account_balance()`/
`estimate_cost()`, a real CLI subprocess call). A `ProductionReadiness
Handoff`/`ProductionAuthorityIntakeReport` is NEVER treated as human
authorization anywhere in this module, and neither is `approved=True`,
`ready=True`, or `accepted=True` on any upstream object.

WHY THIS MODULE NEVER CONSTRUCTS `RealGenerationAuthorization` (Section
0/8 -- the single most important rule of this phase): the ONLY
mechanism in this entire repository that may legitimately construct a
`RealGenerationAuthorization` is an external, human caller of `agents.
generation_approval_gate.RealGenerationAuthorization(...)` itself,
outside of any automatic pipeline (established at Phase P2.11,
re-confirmed unchanged at Phase P2.29 -- `director.py::AIDirector.
prepare_real_generation_activation()` requires it as a parameter with
NO default, and its own docstring states "ce Director ne construit, ne
devine ni ne dérive JAMAIS cet objet lui-même"). This module inherits
that same absolute rule: `HumanAuthorizationHandoffInput.real_
generation_authorization` is `Optional[RealGenerationAuthorization] =
None`, and every code path in `HumanAuthorizationHandoffBuilder.build()`
either receives that object AS SUPPLIED by the caller or reports that
none was supplied -- there is no third path.

WHY THIS MODULE NEVER CALLS `prepare_real_generation_activation()` OR
`execute_real_generation_activation()` (Section 14): both already
exist, unmodified, at Phase P2.29, and both remain the caller's own,
separate, explicit responsibility. `prepare_real_generation_activation()`
itself calls `RequestScopedActivationService.prepare_activation()`,
which calls `gate.evaluate(request)` internally (`agents/activation_
contract.py::_fresh_violations()`) -- the exact real-CLI-subprocess
risk P3.18 already identified and refused to touch. This module
performs ONLY structural, offline, zero-I/O checks: the same
`isinstance`/`authorized_by_human is True`/`request_id` equality
checks ALREADY duplicated, by design, in two independent places in
this codebase (`GenerationApprovalGate._human_authorization_reasons()`
and `RequestScopedActivationService.prepare_activation()`'s own inline
check -- see that module's own docstring: "Cette redondance est
DÉLIBÉRÉE ... l'autorité d'activation est vérifiée par CE service
lui-même, indépendamment de ce que le Gate décide"). Adding a THIRD,
equally inert, equally side-effect-free copy of that same three-line
structural check is the same established idiom, not a new authority:
it produces no decision beyond "this object is shaped like a valid,
correctly-bound authorization" -- never "approved", never "activated".

NO EXECUTION / NO ACTIVATION / NO AUTOMATIC AUTHORIZATION (Section 0/
11/13/14/15): this module never imports `agents.generation_approval_
gate.GenerationApprovalGate`, `agents.generation_job_service.
GenerationJobService`, `agents.activation_contract.
RequestScopedActivationService`, `agents.controlled_real_provider_
activation.ControlledRealProviderActivationService`, `agents.
critical_section_lock`, `agents.executed_request_store`, `integrations.
higgsfield.provider.HiggsfieldProvider`, `integrations.higgsfield.
client.HiggsfieldClient`, or `agents.mission_state_machine`, and never
calls `create_job`, `.evaluate(`, `.execute(`, `.transition(`,
`prepare_activation`, `validate_activation`, or `.consume(`.
`RealGenerationAuthorization` is imported ONLY as a type (for
`isinstance` checks and type hints) -- this module contains exactly
ZERO constructor invocations of it (`RealGenerationAuthorization(`
never appears as executable code, only as prose in this docstring and
as a bare type reference elsewhere -- verified by a dedicated AST test
that distinguishes a `Call` node from a `Name`/attribute reference).
`HumanAuthorizationHandoffStatus` has exactly four values --
`INTAKE_NOT_ACCEPTED`, `ELIGIBLE_FOR_HUMAN_AUTHORIZATION`,
`AUTHORIZATION_STRUCTURALLY_VALID`, `AUTHORIZATION_REJECTED` --
deliberately never `AUTHORIZED`, `HUMAN_AUTHORIZED`, `APPROVED`,
`ACTIVATED`, `EXECUTING`, or `EXECUTED` (Section 6's "do not collapse
these states"). Even when a genuinely valid, correctly-bound
authorization is supplied, this module reports only
`AUTHORIZATION_STRUCTURALLY_VALID` -- never `HUMAN_AUTHORIZED` -- because
that stronger claim would require the live Gate's budget/replay/UNKNOWN
re-verification this module deliberately never performs (Section 16).

SCOPE BOUNDARY (mirrors P3.17/P3.18's own documented scope boundaries):
this module re-verifies, at its own layer, the P3.18 intake's own
structural validity (artifact type, contract version, recomputed
`compute_intake_hash`, `ACCEPTED_FOR_P2_CONSIDERATION` status,
identity-chain consistency down to the embedded `GenerationRequest`) --
the same "each layer independently re-verifies the one below it,
never trusts it blindly" idiom already established by `agents/
controlled_real_provider_activation.py` re-inspecting `agents/
activation_contract.py`'s work. It does NOT re-verify prompt/asset/
model/duration/resolution/aspect_ratio equality a second time -- those
stay exclusively inside P3.15/P3.17/P3.18, never duplicated here.

REPLAY / SINGLE-USE (Section 21): this module holds no state, tracks
no "consumed" registry, and never imports `agents.executed_request_
store`. `HumanAuthorizationFailureCategory.AUTHORIZATION_ALREADY_
CONSUMED` is DEFINED (Section 22 names it explicitly as a failure
semantics category this module's vocabulary must distinguish from
`EXECUTION_UNKNOWN`) but structurally UNREACHABLE by any check in this
module -- single-use/consumption tracking remains exclusively
`RequestScopedActivationService`'s responsibility (Phase P2.21), never
simulated or duplicated here. A dedicated test asserts this category
is never assigned by any finding.

BUDGET (Section 16): this module carries no budget/cost dimension, for
the same reason P3.18 carries none -- inspecting it honestly would
require the live Gate/Provider chain this module deliberately never
touches.

STATE MACHINE (Section 13/17): this module never imports `agents.
mission_state_machine` and never calls `.transition()`. Whether an
`ELIGIBLE_FOR_HUMAN_AUTHORIZATION` or `AUTHORIZATION_STRUCTURALLY_VALID`
result here should ever be reflected as a Mission State transition
remains exclusively a Director/Orchestrator decision, never exercised
by this module.

IMMUTABILITY / DETERMINISM / IDEMPOTENCY (Section 18/16/17... i.e.
P3.19 Sections 25/23/24): this module never imports `dataclasses.
replace` and never assigns to any attribute of `ProductionAuthority
IntakeReport`, `ProductionReadinessHandoff`, `PreProductionReview`,
`GenerationRequest`, or `RealGenerationAuthorization` -- all frozen
anyway. `build()` is a pure function of its input: identical immutable
input (same intake, same optional authorization object) always yields
findings/status/`content_hash` that are equal by value. No wall-clock
value is ever fed into the hash (only `handoff_id`/`created_at` are
excluded, mirroring every prior P3 phase's own hash discipline) --
this module never reads `RealGenerationAuthorization.authorized_at`
into anything hashed or compared, exactly per Section 23's "do not
include current time in hashes ... unless the existing authorization
contract requires it" (it does not).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional, Tuple

from agents.generation_approval_gate import RealGenerationAuthorization
from agents.production_authority_intake import (
    INTAKE_ARTIFACT_TYPE,
    INTAKE_CONTRACT_VERSION,
    ProductionAuthorityIntakeReport,
    ProductionAuthorityIntakeStatus,
    compute_intake_hash,
)

HANDOFF_CONTRACT_VERSION = 1
HANDOFF_ARTIFACT_TYPE = "HumanAuthorizationHandoff"
PRODUCER_AGENT = "human-authorization-handoff"
PRODUCER_VERSION = "1.0"

SUPPORTED_INTAKE_CONTRACT_VERSIONS = frozenset({INTAKE_CONTRACT_VERSION})


class HumanAuthorizationHandoffError(ValueError):
    """Raised for a structurally invalid `HumanAuthorizationHandoffInput`
    (e.g. `intake` is not a real `ProductionAuthorityIntakeReport`) --
    never a silent fallback."""


class HumanAuthorizationHandoffStatus(str, Enum):
    """
    Exactly four values, deliberately never `AUTHORIZED`, `HUMAN_
    AUTHORIZED`, `APPROVED`, `ACTIVATED`, `EXECUTING`, or `EXECUTED`
    (Section 6/12/13/14) -- this handoff can only ever say whether the
    intake was accepted, whether human authorization is still needed,
    or whether an already-supplied authorization is structurally valid
    -- never anything about production authority itself.
    """

    INTAKE_NOT_ACCEPTED = "INTAKE_NOT_ACCEPTED"
    ELIGIBLE_FOR_HUMAN_AUTHORIZATION = "ELIGIBLE_FOR_HUMAN_AUTHORIZATION"
    AUTHORIZATION_STRUCTURALLY_VALID = "AUTHORIZATION_STRUCTURALLY_VALID"
    AUTHORIZATION_REJECTED = "AUTHORIZATION_REJECTED"


class HumanAuthorizationFailureCategory(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"
    INTAKE_REJECTED = "INTAKE_REJECTED"
    CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
    AUTHORIZATION_MISSING = "AUTHORIZATION_MISSING"
    AUTHORIZATION_FORGED = "AUTHORIZATION_FORGED"
    AUTHORIZATION_INVALID = "AUTHORIZATION_INVALID"
    AUTHORIZATION_REQUEST_MISMATCH = "AUTHORIZATION_REQUEST_MISMATCH"
    # Defined per Section 22's explicit failure-semantics vocabulary --
    # structurally UNREACHABLE by this stateless module (see module
    # docstring "REPLAY / SINGLE-USE"). Single-use/consumption tracking
    # remains exclusively agents.activation_contract's responsibility.
    AUTHORIZATION_ALREADY_CONSUMED = "AUTHORIZATION_ALREADY_CONSUMED"
    INTERNAL_HANDOFF_FAILURE = "INTERNAL_HANDOFF_FAILURE"


# ----------------------------------------------------------------------
# INPUT CONTRACT (Section 5/8/9)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class HumanAuthorizationHandoffInput:
    intake: ProductionAuthorityIntakeReport

    # NEVER constructed internally -- see module docstring "WHY THIS
    # MODULE NEVER CONSTRUCTS RealGenerationAuthorization". `None`
    # (the default) means "no explicit human action has happened yet".
    real_generation_authorization: Optional[RealGenerationAuthorization] = None

    handoff_id: Optional[str] = None
    clock: Optional[Callable[[], str]] = None


# ----------------------------------------------------------------------
# OUTPUT CONTRACT -- immutable.
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class HumanAuthorizationFinding:
    dimension: str
    passed: bool
    detail: str
    category: Optional[HumanAuthorizationFailureCategory] = None  # None iff passed


@dataclass(frozen=True)
class HumanAuthorizationHandoff:
    handoff_id: str
    artifact_type: str
    created_at: str
    contract_version: int

    request_id: Optional[str]
    mission_id: str
    review_id: str
    intake_id: str

    status: HumanAuthorizationHandoffStatus
    findings: Tuple[HumanAuthorizationFinding, ...]
    reasons: Tuple[str, ...]  # detail of every failing finding, in order

    intake: ProductionAuthorityIntakeReport  # verbatim, never rewritten
    # -- full chain (mission_id -> script_artifact -> production_
    # preparation -> generation_request -> review -> handoff -> intake)
    # is reachable through this single field, never re-copied onto
    # this dataclass.

    authorization_supplied: bool
    authorization_id: Optional[str]  # opaque UUID only (mirrors P2.21's
    # own "never persist the object itself, only authorization_id"
    # discipline) -- never `authorized_by_human`, never `note`, never
    # `authorized_at`.

    producer_agent: str
    producer_version: str

    content_hash: str


def _default_clock() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_human_authorization_handoff_hash(
    request_id: Optional[str],
    mission_id: str,
    review_id: str,
    intake_id: str,
    status: str,
    findings: Tuple[HumanAuthorizationFinding, ...],
    intake_content_hash: str,
    authorization_id: Optional[str],
    contract_version: int,
) -> str:
    canonical = {
        "request_id": request_id,
        "mission_id": mission_id,
        "review_id": review_id,
        "intake_id": intake_id,
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
        "intake_content_hash": intake_content_hash,
        "authorization_id": authorization_id,
        "contract_version": contract_version,
    }
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# INTAKE-LEVEL DIMENSIONS (Section 5/9/10) -- re-verify the P3.18
# intake's own structural validity at this layer, never re-deriving
# P3.15/P3.17/P3.18's own business logic.
# ----------------------------------------------------------------------


def _check_intake_structural_validity(intake: ProductionAuthorityIntakeReport) -> HumanAuthorizationFinding:
    if intake.artifact_type != INTAKE_ARTIFACT_TYPE:
        return HumanAuthorizationFinding(
            "intake_structural_validity", False,
            f"intake.artifact_type '{intake.artifact_type}' is not '{INTAKE_ARTIFACT_TYPE}'.",
            HumanAuthorizationFailureCategory.INVALID_INPUT,
        )
    if not isinstance(intake.intake_id, str) or not intake.intake_id.strip():
        return HumanAuthorizationFinding(
            "intake_structural_validity", False,
            f"intake.intake_id is missing or empty ({intake.intake_id!r}).",
            HumanAuthorizationFailureCategory.INVALID_INPUT,
        )
    return HumanAuthorizationFinding("intake_structural_validity", True, f"intake_id='{intake.intake_id}'.")


def _check_intake_contract_version(intake: ProductionAuthorityIntakeReport) -> HumanAuthorizationFinding:
    if intake.contract_version not in SUPPORTED_INTAKE_CONTRACT_VERSIONS:
        return HumanAuthorizationFinding(
            "intake_contract_version_compatibility", False,
            f"intake.contract_version {intake.contract_version} is not supported "
            f"(supported: {sorted(SUPPORTED_INTAKE_CONTRACT_VERSIONS)}).",
            HumanAuthorizationFailureCategory.CONTRACT_MISMATCH,
        )
    return HumanAuthorizationFinding(
        "intake_contract_version_compatibility", True,
        f"intake.contract_version={intake.contract_version}.",
    )


def _check_intake_integrity(intake: ProductionAuthorityIntakeReport) -> HumanAuthorizationFinding:
    recomputed = compute_intake_hash(
        request_id=intake.request_id,
        mission_id=intake.mission_id,
        review_id=intake.review_id,
        handoff_id=intake.handoff_id,
        status=intake.status.value,
        findings=intake.findings,
        handoff_content_hash=intake.handoff.content_hash,
        contract_version=intake.contract_version,
    )
    if recomputed != intake.content_hash:
        return HumanAuthorizationFinding(
            "intake_integrity", False,
            "intake.content_hash does not match its own recomputed hash -- "
            "the intake may have been tampered with or is otherwise "
            "corrupted; refusing to consider human authorization for an "
            "inconsistent intake.",
            HumanAuthorizationFailureCategory.INVALID_INPUT,
        )
    return HumanAuthorizationFinding("intake_integrity", True, "intake.content_hash matches recomputed hash.")


def _check_intake_accepted(intake: ProductionAuthorityIntakeReport) -> HumanAuthorizationFinding:
    if intake.status != ProductionAuthorityIntakeStatus.ACCEPTED_FOR_P2_CONSIDERATION:
        return HumanAuthorizationFinding(
            "intake_accepted", False,
            f"intake.status is '{intake.status.value}', not "
            f"ACCEPTED_FOR_P2_CONSIDERATION; a rejected intake can never "
            f"become eligible for human authorization. Underlying intake "
            f"reasons: {list(intake.reasons)}.",
            HumanAuthorizationFailureCategory.INTAKE_REJECTED,
        )
    return HumanAuthorizationFinding("intake_accepted", True, "intake.status is ACCEPTED_FOR_P2_CONSIDERATION.")


def _check_identity_chain_consistency(intake: ProductionAuthorityIntakeReport) -> HumanAuthorizationFinding:
    handoff = intake.handoff
    review = handoff.review

    if intake.handoff_id != handoff.handoff_id:
        return HumanAuthorizationFinding(
            "identity_chain_consistency", False,
            f"intake.handoff_id '{intake.handoff_id}' does not match "
            f"intake.handoff.handoff_id '{handoff.handoff_id}'.",
            HumanAuthorizationFailureCategory.CONTRACT_MISMATCH,
        )
    if intake.review_id != review.review_id:
        return HumanAuthorizationFinding(
            "identity_chain_consistency", False,
            f"intake.review_id '{intake.review_id}' does not match "
            f"intake.handoff.review.review_id '{review.review_id}'.",
            HumanAuthorizationFailureCategory.CONTRACT_MISMATCH,
        )
    if intake.mission_id != review.mission_id:
        return HumanAuthorizationFinding(
            "identity_chain_consistency", False,
            f"intake.mission_id '{intake.mission_id}' does not match "
            f"intake.handoff.review.mission_id '{review.mission_id}'.",
            HumanAuthorizationFailureCategory.CONTRACT_MISMATCH,
        )
    if intake.request_id != review.request_id:
        return HumanAuthorizationFinding(
            "identity_chain_consistency", False,
            f"intake.request_id '{intake.request_id}' does not match "
            f"intake.handoff.review.request_id '{review.request_id}'.",
            HumanAuthorizationFailureCategory.CONTRACT_MISMATCH,
        )
    gr = review.generation_request
    if gr is not None and review.request_id != gr.request_id:
        return HumanAuthorizationFinding(
            "identity_chain_consistency", False,
            f"intake.handoff.review.request_id '{review.request_id}' does "
            f"not match intake.handoff.review.generation_request.request_id "
            f"'{gr.request_id}'.",
            HumanAuthorizationFailureCategory.CONTRACT_MISMATCH,
        )
    return HumanAuthorizationFinding(
        "identity_chain_consistency", True,
        f"intake_id/handoff_id/review_id/mission_id/request_id are "
        f"consistent across the full chain (request_id='{intake.request_id}').",
    )


# ----------------------------------------------------------------------
# AUTHORIZATION-LEVEL DIMENSIONS (Section 8/9/10/11) -- pure, defensive
# re-checks of an EXTERNALLY-SUPPLIED RealGenerationAuthorization.
# Never constructs one; `getattr(..., default=None)` is used
# deliberately so a wrong-type object never raises here, it only ever
# produces a typed, explicit rejection finding.
# ----------------------------------------------------------------------


def _check_authorization_type(auth: object) -> HumanAuthorizationFinding:
    if not isinstance(auth, RealGenerationAuthorization):
        return HumanAuthorizationFinding(
            "authorization_type_valid", False,
            f"real_generation_authorization is not a valid "
            f"RealGenerationAuthorization instance (got "
            f"{type(auth).__name__}) -- refusing to trust an object of "
            f"the wrong type as human authorization.",
            HumanAuthorizationFailureCategory.AUTHORIZATION_FORGED,
        )
    return HumanAuthorizationFinding("authorization_type_valid", True, "real_generation_authorization is a valid RealGenerationAuthorization instance.")


def _check_authorization_human_flag(auth: object) -> HumanAuthorizationFinding:
    flag = getattr(auth, "authorized_by_human", None)
    if flag is not True:
        return HumanAuthorizationFinding(
            "authorization_human_flag", False,
            f"real_generation_authorization.authorized_by_human is not "
            f"explicitly True (got {flag!r}).",
            HumanAuthorizationFailureCategory.AUTHORIZATION_INVALID,
        )
    return HumanAuthorizationFinding("authorization_human_flag", True, "authorized_by_human is explicitly True.")


def _check_authorization_identity_present(auth: object) -> HumanAuthorizationFinding:
    authorization_id = getattr(auth, "authorization_id", None)
    if not isinstance(authorization_id, str) or not authorization_id.strip():
        return HumanAuthorizationFinding(
            "authorization_identity_present", False,
            f"real_generation_authorization.authorization_id is missing "
            f"or empty ({authorization_id!r}).",
            HumanAuthorizationFailureCategory.AUTHORIZATION_INVALID,
        )
    return HumanAuthorizationFinding(
        "authorization_identity_present", True, f"authorization_id='{authorization_id}'.",
    )


def _check_authorization_request_binding(auth: object, expected_request_id: Optional[str]) -> HumanAuthorizationFinding:
    bound_request_id = getattr(auth, "request_id", None)
    if bound_request_id != expected_request_id:
        return HumanAuthorizationFinding(
            "authorization_request_binding", False,
            f"real_generation_authorization is bound to request "
            f"{bound_request_id!r}, not to the reviewed request "
            f"{expected_request_id!r}.",
            HumanAuthorizationFailureCategory.AUTHORIZATION_REQUEST_MISMATCH,
        )
    return HumanAuthorizationFinding(
        "authorization_request_binding", True, f"request_id='{bound_request_id}' matches the reviewed request.",
    )


# ----------------------------------------------------------------------
# BUILDER (Section 5/7) -- single responsibility: formalize the third
# STOP point, between ProductionAuthorityIntake and explicit human
# authorization. Never orchestrates agents, never becomes the State
# Machine, never a production executor, never constructs or infers
# human consent.
# ----------------------------------------------------------------------


class HumanAuthorizationHandoffBuilder:
    """
    AI DIRECTOR — Human Authorization Handoff Builder (P3.19)

    Stateless: holds no injected collaborator, no provider, no gate, no
    lock, no state machine reference. `build()` is a pure function of
    its `HumanAuthorizationHandoffInput`.
    """

    def build(self, request: HumanAuthorizationHandoffInput) -> HumanAuthorizationHandoff:
        if not isinstance(request.intake, ProductionAuthorityIntakeReport):
            raise HumanAuthorizationHandoffError(
                "intake is not a valid ProductionAuthorityIntakeReport "
                "instance; this module never fabricates one."
            )

        intake = request.intake

        intake_findings: list = [
            _check_intake_structural_validity(intake),
            _check_intake_contract_version(intake),
            _check_intake_integrity(intake),
            _check_intake_accepted(intake),
            _check_identity_chain_consistency(intake),
        ]
        intake_reasons = tuple(f.detail for f in intake_findings if not f.passed)

        auth = request.real_generation_authorization
        authorization_supplied = auth is not None

        if intake_reasons:
            status = HumanAuthorizationHandoffStatus.INTAKE_NOT_ACCEPTED
            auth_findings: tuple = ()
            reasons = intake_reasons
            authorization_id: Optional[str] = None
        elif not authorization_supplied:
            status = HumanAuthorizationHandoffStatus.ELIGIBLE_FOR_HUMAN_AUTHORIZATION
            auth_findings = (
                HumanAuthorizationFinding(
                    "authorization_presence", True,
                    "No real_generation_authorization was supplied -- this "
                    "request is structurally eligible to receive explicit "
                    "human authorization, but none has been provided yet. "
                    "This module never constructs one automatically.",
                ),
            )
            reasons = ()
            authorization_id = None
        else:
            auth_findings = (
                _check_authorization_type(auth),
                _check_authorization_human_flag(auth),
                _check_authorization_identity_present(auth),
                _check_authorization_request_binding(auth, intake.request_id),
            )
            auth_reasons = tuple(f.detail for f in auth_findings if not f.passed)
            authorization_id = getattr(auth, "authorization_id", None) if isinstance(auth, RealGenerationAuthorization) else None
            if auth_reasons:
                status = HumanAuthorizationHandoffStatus.AUTHORIZATION_REJECTED
                reasons = auth_reasons
            else:
                status = HumanAuthorizationHandoffStatus.AUTHORIZATION_STRUCTURALLY_VALID
                reasons = ()

        findings_t = tuple(intake_findings) + tuple(auth_findings)

        clock = request.clock or _default_clock
        handoff_id = request.handoff_id or uuid.uuid4().hex
        created_at = clock()

        content_hash = compute_human_authorization_handoff_hash(
            request_id=intake.request_id,
            mission_id=intake.mission_id,
            review_id=intake.review_id,
            intake_id=intake.intake_id,
            status=status.value,
            findings=findings_t,
            intake_content_hash=intake.content_hash,
            authorization_id=authorization_id,
            contract_version=HANDOFF_CONTRACT_VERSION,
        )

        return HumanAuthorizationHandoff(
            handoff_id=handoff_id,
            artifact_type=HANDOFF_ARTIFACT_TYPE,
            created_at=created_at,
            contract_version=HANDOFF_CONTRACT_VERSION,
            request_id=intake.request_id,
            mission_id=intake.mission_id,
            review_id=intake.review_id,
            intake_id=intake.intake_id,
            status=status,
            findings=findings_t,
            reasons=reasons,
            intake=intake,
            authorization_supplied=authorization_supplied,
            authorization_id=authorization_id,
            producer_agent=PRODUCER_AGENT,
            producer_version=PRODUCER_VERSION,
            content_hash=content_hash,
        )
