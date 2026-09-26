"""
AI DIRECTOR — Controlled Activation Composition (Phase P3.23)

COMPOSITION ONLY, built directly against the REAL contracts re-read
from disk before writing a line of this module: `agents/production_
activation_handoff.py` (P3.21, `ProductionActivationHandoff`),
`agents/generation_approval_gate.py` (`GenerationRequest`,
`RealGenerationAuthorization` -- imported here ONLY as types, exactly
as every other P3 module already does), and `director.py`
(`AIDirector.prepare_real_generation_activation()`, Phase P2.29 -- the
pre-existing, UNMODIFIED entry point this module delegates to, never
duplicates).

RESPONSIBILITY (P3.23 Section 1/5): given a P3.21 `ProductionActivation
Handoff` and an EXTERNALLY-SUPPLIED `RealGenerationAuthorization`
(never constructed here), translate the handoff's already-reviewed
production parameters into the exact call `AIDirector.prepare_real_
generation_activation()` already expects, delegate to it UNMODIFIED,
and cross-check its result against the handoff before returning it
verbatim. This module produces NO new result type: it returns the
existing `director.PreparedRealGenerationActivation` (Phase P2.29)
as-is (Section 19: "ne pas inventer un troisième objet si un objet P2
existant convient"). `COMPOSED` here means exactly what P2.29 already
means by "prepared" -- never `ACTIVATED`, never `EXECUTING`, never
`EXECUTED`.

WHY `title`/`hook`/`objective` ARE REQUIRED, EXPLICIT, CALLER-SUPPLIED
PARAMETERS -- NEVER EXTRACTED FROM THE HANDOFF (Section 10's "si un
champ n'est pas présent dans le contrat réel: NOT AVAILABLE, ne pas
l'inventer", verified this phase by direct inspection of `agents/
planner.py::VideoPlan` and `agents/video_production_preparation.py::
VideoProductionPreparationResult`): `VideoPlan` (the object `title`/
`hook`/`objective` are stored on, produced by `VideoPlanner.
create_zephyr_plan()`) is NEVER embedded anywhere in the P3.13-P3.21
object chain -- `VideoProductionPreparationResult` carries only
`production_preparation`/`generation_request`, never the `VideoPlan`
used to build the latter. `title`/`hook`/`objective` are therefore
STRUCTURALLY NOT AVAILABLE from any `ProductionActivationHandoff`, at
any depth -- confirmed, not assumed. `AIDirector.prepare_real_
generation_activation()` itself requires all three as its own
positional/required parameters (no default): this module's Director
entry point mirrors that exact requirement rather than inventing a
placeholder value, which would violate Section 10 outright.

WHY THIS MODULE NEVER CALLS `GenerationApprovalGate`, `RequestScoped
ActivationService`, `ControlledRealProviderActivationService`, or
`ReleaseCandidateIdentityLock` DIRECTLY (Section 9/12): all of these
are exercised, fresh, EXACTLY ONCE, entirely INSIDE the delegated
`prepare_real_generation_activation()` call (Phase P2.29, unmodified)
-- re-implementing any part of that chain here would violate Section
12's "elle ne doit pas réimplémenter... identity lock... budget
gate... ces mécanismes restent P2" outright, and would risk a second,
divergent copy of logic that must never drift from the original. This
module's own pre-checks (`verify_handoff_ready()`, `verify_
authorization_binding()`) are STRUCTURAL ONLY -- they inspect already-
computed, immutable fields on the handoff/authorization objects
themselves, never call a live P2 service, never touch the Provider,
Client, CLI, or network (same "never touch the Gate/Provider, even
read-only, at THIS layer" discipline established at every P3.18-P3.22
layer). The one and only place this module reaches a live P2
mechanism is the single delegated call to `prepare_real_generation_
activation()` -- and that call is the SAME call `director.py` already
exposes today, not a new one.

FRESH-GENERATION-REQUEST CROSS-CHECK (Section 11 -- a genuine, non-
duplicate verification this module adds): `prepare_real_generation_
activation()` REBUILDS a `GenerationRequest` from scratch, every call,
via `VideoPlanner.create_zephyr_plan()` + `PromptAssemblySystem` +
`AssetPreparationSystem` -- it NEVER reuses the exact `GenerationRequest`
object embedded, several layers deep, inside the P3.15-P3.21 chain that
was actually reviewed and authorized. For Video 005 today both are
content-identical (same real files on disk), but nothing in the
existing architecture enforces this by construction. `verify_
generation_request_consistency()` therefore compares the FRESHLY-BUILT
request that `prepare_real_generation_activation()` just returned
against the REVIEWED one embedded in the handoff -- `request_id`,
`job_type`, `duration`, `resolution`, `aspect_ratio`, `prompt`, and
both media reference SHA-256 values -- and raises
`ControlledActivationCompositionError` on ANY divergence. This is NOT
the Release Candidate Identity Lock (which compares against a
hardcoded canonical Video 005 contract, never against a specific
previously-reviewed request) and does not replace it -- both checks
run, independently, for different reasons: the Identity Lock (inside
the delegated call) verifies "this matches the locked Release
Candidate"; this module's cross-check verifies "this matches what was
actually reviewed and handed off". `PromptAssemblySystem`/`Asset
PreparationSystem` file reads happen exclusively INSIDE the delegated
`prepare_real_generation_activation()` call (as they already did
before this phase) -- this module's own cross-check reads only
already-in-memory dataclass fields, no I/O of its own.

NO EXECUTION / NO ACTIVATION / NO AUTOMATIC AUTHORIZATION (Section 0/
7/13/14): this module never imports `agents.generation_job_service.
GenerationJobService`, `agents.activation_contract.
RequestScopedActivationService`, `agents.controlled_real_provider_
activation.ControlledRealProviderActivationService`, `agents.
critical_section_lock`, `agents.executed_request_store`, `agents.
release_candidate_identity_lock`, `integrations.higgsfield.provider.
HiggsfieldProvider`, `integrations.higgsfield.client.HiggsfieldClient`,
or `agents.mission_state_machine`, and never calls `create_job`,
`.execute(`, `.consume(`, `execute_real_generation_activation`, or
`prepare_activation`/`.prepare(` directly (those remain exclusively
internal to the delegated P2.29 call). `RealGenerationAuthorization`
is imported ONLY as a type (for `isinstance` checks) -- this module
contains exactly ZERO constructor invocations of it, verified by a
dedicated AST test distinguishing a `Call` node from a `Name`/
attribute reference, same discipline as P3.19-P3.21.

SCOPE BOUNDARY -- EXPIRY/REVOKE/CONSUMPTION (Section 16/17, mirrors
the "structurally unreachable" pattern already established at P3.19/
P3.20): `RealGenerationAuthorization` (Phase P2.11) carries NO expiry
field and NO revoke mechanism of its own -- confirmed by direct
inspection of `agents/generation_approval_gate.py`. Expiry, revocation,
and single-use consumption are properties of the DOWNSTREAM
`RequestScopedActivationContract`/`ControlledRealProviderActivation
Contract` (Phase P2.21/P2.26), constructed and consumed EXCLUSIVELY
inside the delegated `prepare_real_generation_activation()`/(a future,
separate, never-called-here) `execute_real_generation_activation()`
call -- this module never constructs, inspects, or references either
contract type directly. "Already executed" (replay) is exercised
naturally: if the underlying `request_id` was already marked executed,
the delegated call's own fresh `GenerationApprovalGate.evaluate()`
returns non-`APPROVED`, and `ActivationRejectedError` propagates
UNMODIFIED from `prepare_real_generation_activation()` -- never caught,
never reinterpreted, never converted into a different exception type
by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from agents.generation_approval_gate import GenerationRequest, RealGenerationAuthorization
from agents.pre_production_review import compute_review_hash
from agents.production_activation_handoff import (
    HANDOFF_ARTIFACT_TYPE,
    HANDOFF_CONTRACT_VERSION,
    ProductionActivationHandoff,
    ProductionActivationHandoffStatus,
    compute_production_activation_handoff_hash,
)

SUPPORTED_HANDOFF_CONTRACT_VERSIONS = frozenset({HANDOFF_CONTRACT_VERSION})

# Fields structurally available on a reviewed GenerationRequest and
# therefore safe to cross-check verbatim -- never re-derived, never
# guessed. `resolution`/`aspect_ratio` are included here even though
# prepare_real_generation_activation() does not accept them as
# parameters (VideoAgent.build_request() derives them internally from
# scene defaults) -- precisely why they must be verified AFTER the
# fact rather than trusted by construction.
_COMPARABLE_SCALAR_FIELDS = ("request_id", "job_type", "duration", "resolution", "aspect_ratio", "prompt")


class ControlledActivationCompositionError(ValueError):
    """
    Raised for this module's OWN pre-checks: a structurally invalid or
    not-ready handoff, a mismatched authorization binding, or a
    divergence between the freshly-built GenerationRequest and the one
    actually reviewed. NEVER raised in place of a P2 rejection --
    `ActivationRejectedError` (Phase P2.21) and `ControlledRealProvider
    ActivationRejectedError` (Phase P2.26), raised by the delegated
    `prepare_real_generation_activation()` call itself, always
    propagate unmodified, never caught or reinterpreted here.
    """


def verify_handoff_ready(handoff: ProductionActivationHandoff) -> None:
    """
    Structural, offline, zero-I/O pre-check (Section 6). Raises
    `ControlledActivationCompositionError` unless `handoff` is a real,
    internally-consistent `ProductionActivationHandoff` whose status is
    exactly `ACTIVATION_HANDOFF_READY`. Never mutates `handoff`.
    """

    if not isinstance(handoff, ProductionActivationHandoff):
        raise ControlledActivationCompositionError(
            "handoff is not a valid ProductionActivationHandoff instance; "
            "this module never fabricates one."
        )

    if handoff.artifact_type != HANDOFF_ARTIFACT_TYPE:
        raise ControlledActivationCompositionError(
            f"handoff.artifact_type '{handoff.artifact_type}' is not "
            f"'{HANDOFF_ARTIFACT_TYPE}'."
        )

    if handoff.contract_version not in SUPPORTED_HANDOFF_CONTRACT_VERSIONS:
        raise ControlledActivationCompositionError(
            f"handoff.contract_version {handoff.contract_version} is not "
            f"supported (supported: "
            f"{sorted(SUPPORTED_HANDOFF_CONTRACT_VERSIONS)})."
        )

    recomputed = compute_production_activation_handoff_hash(
        request_id=handoff.request_id,
        mission_id=handoff.mission_id,
        review_id=handoff.review_id,
        intake_id=handoff.intake_id,
        human_authorization_handoff_id=handoff.human_authorization_handoff_id,
        eligibility_id=handoff.eligibility_id,
        status=handoff.status.value,
        findings=handoff.findings,
        eligibility_content_hash=handoff.eligibility.content_hash,
        authorization_id=handoff.authorization_id,
        identity_lock_violations=handoff.identity_lock_violations,
        contract_version=handoff.contract_version,
    )
    if recomputed != handoff.content_hash:
        raise ControlledActivationCompositionError(
            "handoff.content_hash does not match its own recomputed hash "
            "-- the handoff may have been tampered with or is otherwise "
            "corrupted; refusing to compose an activation from an "
            "inconsistent handoff."
        )

    # Deep re-verification (mirrors P3.18's own `_check_review_integrity`,
    # reused via the SAME `compute_review_hash` function, never a second
    # hashing scheme): `handoff.content_hash` alone only covers the
    # IMMEDIATE `eligibility.content_hash` string -- a deeply nested
    # field could be swapped (e.g. via `dataclasses.replace` on the
    # embedded review) without changing any hash ABOVE that exact
    # layer. Recomputing the deepest, most content-rich review hash
    # here closes that gap, exactly as P3.18 already does at its own
    # layer -- never a new integrity mechanism, the same one reused
    # one hop further down.
    review = handoff.eligibility.human_authorization_handoff.intake.handoff.review
    recomputed_review_hash = compute_review_hash(
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
    if recomputed_review_hash != review.content_hash:
        raise ControlledActivationCompositionError(
            "The reviewed request embedded deep in the handoff has a "
            "content_hash that does not match its own recomputed hash -- "
            "a nested field (e.g. mission_id, request_id, or a finding) "
            "may have been tampered with; refusing to compose an "
            "activation from an inconsistent handoff."
        )

    if handoff.status != ProductionActivationHandoffStatus.ACTIVATION_HANDOFF_READY:
        raise ControlledActivationCompositionError(
            f"handoff.status is '{handoff.status.value}', not "
            f"ACTIVATION_HANDOFF_READY -- a handoff that is not ready can "
            f"never be composed into an activation. Underlying handoff "
            f"reasons: {list(handoff.reasons)}."
        )


def verify_authorization_binding(
    handoff: ProductionActivationHandoff, real_generation_authorization: object
) -> None:
    """
    Structural, offline, zero-I/O pre-check (Section 7/8). Raises
    `ControlledActivationCompositionError` unless `real_generation_
    authorization` is a real, correctly-bound `RealGenerationAuthorization`
    for EXACTLY the request/authorization this handoff was built from.
    Never constructs a `RealGenerationAuthorization`; only inspects one
    already supplied by the caller.
    """

    if not isinstance(real_generation_authorization, RealGenerationAuthorization):
        raise ControlledActivationCompositionError(
            f"real_generation_authorization is not a valid "
            f"RealGenerationAuthorization instance (got "
            f"{type(real_generation_authorization).__name__})."
        )

    if real_generation_authorization.authorization_id != handoff.authorization_id:
        raise ControlledActivationCompositionError(
            f"real_generation_authorization.authorization_id "
            f"'{real_generation_authorization.authorization_id}' does not "
            f"match handoff.authorization_id '{handoff.authorization_id}' "
            f"-- this authorization was not the one this handoff was "
            f"reviewed and built from."
        )

    if real_generation_authorization.request_id != handoff.request_id:
        raise ControlledActivationCompositionError(
            f"real_generation_authorization.request_id "
            f"'{real_generation_authorization.request_id}' does not match "
            f"handoff.request_id '{handoff.request_id}'."
        )

    if real_generation_authorization.authorized_by_human is not True:
        raise ControlledActivationCompositionError(
            "real_generation_authorization.authorized_by_human is not "
            "explicitly True."
        )


@dataclass(frozen=True)
class ExtractedProductionParameters:
    """
    Only the fields `AIDirector.prepare_real_generation_activation()`
    actually accepts as call arguments (Section 10) -- `resolution`/
    `aspect_ratio`/`prompt`/asset hashes are NOT extracted here (that
    method has no parameter for them); they are instead verified
    AFTER the delegated call via `verify_generation_request_
    consistency()`, never passed in.
    """

    request_id: str
    job_type: str
    duration: int


def extract_production_parameters(handoff: ProductionActivationHandoff) -> ExtractedProductionParameters:
    """
    Extracts `request_id`/`job_type`/`duration` from the handoff's own
    embedded, already-reviewed `GenerationRequest` -- never re-derived,
    never guessed. Raises `ControlledActivationCompositionError` if the
    chain does not actually carry a `GenerationRequest` (structurally
    impossible for an `ACTIVATION_HANDOFF_READY` handoff per every
    upstream P3.15-P3.20 guarantee, but never assumed here).
    """

    generation_request = handoff.eligibility.human_authorization_handoff.intake.handoff.review.generation_request
    if generation_request is None:
        raise ControlledActivationCompositionError(
            "handoff carries no generation_request -- structurally "
            "impossible for an ACTIVATION_HANDOFF_READY handoff, but "
            "never assumed here."
        )

    return ExtractedProductionParameters(
        request_id=handoff.request_id,
        job_type=generation_request.job_type,
        duration=generation_request.duration,
    )


def verify_generation_request_consistency(
    freshly_built: GenerationRequest, reviewed: GenerationRequest
) -> None:
    """
    Section 11's mandatory cross-check. Compares the `GenerationRequest`
    `prepare_real_generation_activation()` just rebuilt from scratch
    against the one actually reviewed and embedded in the handoff.
    Raises `ControlledActivationCompositionError` on ANY divergence --
    never corrected silently, never partially accepted.
    """

    mismatches = []

    for field_name in _COMPARABLE_SCALAR_FIELDS:
        if getattr(freshly_built, field_name) != getattr(reviewed, field_name):
            mismatches.append(field_name)

    freshly_avatar = freshly_built.start_image.sha256 if freshly_built.start_image is not None else None
    reviewed_avatar = reviewed.start_image.sha256 if reviewed.start_image is not None else None
    if freshly_avatar != reviewed_avatar:
        mismatches.append("start_image.sha256")

    freshly_refs = {ref.role: ref.sha256 for ref in freshly_built.image_references}
    reviewed_refs = {ref.role: ref.sha256 for ref in reviewed.image_references}
    if freshly_refs != reviewed_refs:
        mismatches.append("image_references")

    if mismatches:
        raise ControlledActivationCompositionError(
            f"Freshly-built GenerationRequest diverges from the reviewed "
            f"one embedded in the handoff: {', '.join(mismatches)}. "
            f"Refusing to proceed -- a divergence must never be silently "
            f"accepted."
        )
