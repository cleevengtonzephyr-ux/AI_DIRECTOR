"""
AI DIRECTOR — Pre-Production Review (Phase P3.15)

REVIEW BOUNDARY ONLY, built directly against the REAL contracts re-read
from disk before writing a line of this module: `agents/
video_production_preparation.py` (P3.14, `VideoProductionPreparation.
prepare()` -> `VideoProductionPreparationResult`), `agents/
script_production_bridge.py` (P3.13, `ProductionPreparationRequest`),
`agents/generation_approval_gate.py` (`GenerationRequest`'s real field
shape -- imported here ONLY as a type, exactly as `agents/video_agent.py`
and `agents/video_production_preparation.py` already do; `Generation
ApprovalGate`, `GenerationJobService`, `HiggsfieldProvider`, and
`HiggsfieldClient` are never imported), and `agents/content_agent.py`
(`ScriptArtifact`, `SCRIPT_ARTIFACT_TYPE`).

RESPONSIBILITY (P3.15 Section 4): given a P3.14
`VideoProductionPreparationResult` -- the real, already-existing bundle
that carries a prepared `GenerationRequest` together with its full
provenance chain (`ScriptArtifact`, prompt source, asset references,
mission_id) -- determine whether it is STRUCTURALLY READY for the next
authorization boundary, and STOP. This module never authorizes, never
activates a provider, and never executes anything.

WHY THE INPUT IS `VideoProductionPreparationResult`, NOT A BARE
`GenerationRequest`: `GenerationRequest` (agents/generation_approval_
gate.py) has no `mission_id` field and carries no reference back to the
`ScriptArtifact`/prompt-source/asset-provenance chain that produced it.
Reviewing prompt/asset PROVENANCE (P3.15 Section 9/10) is impossible
from a bare `GenerationRequest` alone. `VideoProductionPreparationResult`
already IS the real "prepared production request" the module docstring's
diagram refers to (P3.15 Section 3: reusing an existing contract instead
of inventing a conflicting one) -- it carries the `GenerationRequest`
(`.generation_request`) AND the `ProductionPreparationRequest`
(`.production_preparation`) that produced it, verbatim, never rewritten.

NO EXECUTION / NO ACTIVATION / NO AUTHORIZATION (P3.15 Section 0/13):
this module never imports `agents.generation_approval_gate.
GenerationApprovalGate`, `agents.generation_job_service.
GenerationJobService`, `integrations.higgsfield.provider.
HiggsfieldProvider`, `integrations.higgsfield.client.HiggsfieldClient`,
`agents.mission_state_machine`, or any activation/authorization
contract, and never calls `create_job`, `.evaluate(`, `.execute(`, or
`.transition(`. A `PASS` result means only "the technical preparation
satisfies this review's structural criteria" -- NEVER "authorized".
There is deliberately no `approved`/`authorized` field anywhere on
`PreProductionReview`: only `status` (`PASS`/`FAIL`), to make the two
concepts impossible to confuse by attribute name alone.

FAILURE SEMANTICS (Section 17): each `ReadinessFinding` that fails
carries one of `ReadinessFailureCategory` -- `INVALID_INPUT`,
`INTEGRITY_FAILURE`, `MISSING_PROVENANCE`, `CONTRACT_MISMATCH`,
`INCOMPLETE_PRODUCTION_REQUEST`, `INTERNAL_REVIEW_FAILURE`. There is
deliberately NO `UNKNOWN` category here: per Section 17's own
instruction, "P3.15 itself must not create an UNKNOWN execution state
merely because a review failed -- UNKNOWN belongs to actual execution
uncertainty", which this module, reading only already-computed
immutable dataclasses, never touches.

IMMUTABILITY / DETERMINISM / IDEMPOTENCY (Section 18/19/20): this
module never imports `dataclasses.replace` and never assigns to any
attribute of `VideoProductionPreparationResult`, `ProductionPreparation
Request`, `ScriptArtifact`, or `GenerationRequest` -- all frozen anyway.
`review()` is a pure function of its input: identical immutable input
(same `VideoProductionPreparationResult`, same optional expected-hash
arguments) always yields findings/status/`content_hash` that are equal
by value (the only fields excluded from `content_hash`, mirroring P3.13/
P3.14's own hash discipline, are `review_id`/`created_at` -- technical/
temporal, never fed into the hash).

COST (Section 12): `GenerationRequest`/`VideoProductionPreparationResult`
expose no cost field anywhere in the real P3/P2 contracts audited for
this phase -- `GenerationCostService`/`CostEngine` both require a real
`BaseHiggsfieldProvider` to produce a cost, which this review boundary
must never call (Section 0). This module therefore has no cost
dimension at all: there is nothing to honestly inspect, and Section 12
forbids inventing one.

STATE MACHINE (Section 14): this module never imports `agents.
mission_state_machine` and never calls `.transition()`. Whether a
`PASS` review here should ever be reflected as a Mission State
transition remains exclusively a Director/Orchestrator decision, never
exercised by this module.

DURATION POLICY (Phase P3.16 Section 7) -- OPTION D SELECTED, JUSTIFIED
BY REPOSITORY EVIDENCE, NOT CONVENIENCE: `ScriptArtifact.
total_duration_target` (content-planning stage, P3.6) and
`GenerationRequest.duration` (technical-production stage, Phase K) are
two INTENTIONALLY DIFFERENT concepts, never required to be equal.
Evidence, independently re-verified on disk before this statement was
written:

1. `ScriptArtifact.total_duration_target` is, by `agents/content_agent.
   py`'s OWN documentation, a non-binding scaffold absent an explicit
   caller override: when `ContentAgentInput.duration_target_seconds` is
   `None`, `ContentAgent.run()` falls back to
   `DEFAULT_TOTAL_DURATION_TARGET_SECONDS = 30` and appends the warning
   "no duration_target_seconds provided; using a non-binding scaffold
   default ... -- this is NOT a user-specified requirement." It was
   never designed to be a binding production constraint.

2. The only real caller of that override, `agents/director_pipeline.py`
   (`BusinessMissionRequest.content_duration_target_seconds` ->
   `ContentAgentInput.duration_target_seconds`), belongs exclusively to
   the P3.11 BUSINESS pipeline (Strategy -> Content -> Quality ->
   Publishing-preparation -> Analytics -> Optimization) -- a chain
   `agents/mission_state_machine.py`'s own P3.12 audit already
   documented as "deliberately left unintegrated" from the P2/
   VideoAgent real-generation chain. No real code path connects a
   business-pipeline duration target to a `VideoPlan` or a
   `GenerationRequest` today.

3. `GenerationRequest.duration` (`agents/video_agent.py`,
   `build_request()`: `duration=getattr(plan, "duration", None)`) comes
   exclusively from `VideoPlan.duration`, which for the real Video 005
   fixture (`VideoPlanner.create_zephyr_plan()`) is a fixed default of
   15s, documented in `agents/planner.py` itself as "plafond reel
   confirme en lecture seule pour seedance_2_0 (Phase P1.2-bis,
   `generate cost` reel : 5/10/15 acceptes, >15 rejete par l'API)" --
   i.e. grounded in a REAL, previously-verified Higgsfield provider
   constraint for this exact model, not an estimate.

4. `ScriptProductionBridge.prepare()` (P3.13) reads
   `script_artifact.total_duration_target` into `ProductionPreparation
   Request.duration_seconds` verbatim (never recomputed), but
   `ScriptProductionBridge.build_video_agent_kwargs()` -- the ONLY
   handoff point into `VideoAgent.build_request()` -- returns exactly
   `{"prompt": ..., "job_type": ...}`. `duration_seconds` is carried for
   traceability only; no real code path ever feeds it into a
   `GenerationRequest`.

CONCLUSION: `ScriptArtifact.total_duration_target` is CONTENT/EDITORIAL
planning metadata (a non-binding creative-duration estimate). `VideoPlan.
duration` / `GenerationRequest.duration` is TECHNICAL PRODUCTION
metadata (a real provider-constrained value). Neither is a stale copy of
the other; there is no single "canonical duration" spanning both
pipelines today, and none is invented here. `duration_validation`
therefore stays purely structural (`generation_request.duration` must be
a positive integer) and never compares the two values for equality --
but, per P3.16 Section 8's "no silent overwriting" instruction, the
finding's `detail` text below DOES surface both values (and explains the
distinction) whenever `production_preparation.duration_seconds` differs
from `generation_request.duration`, so the divergence is always visible
to a reader of the review, never hidden.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, Optional, Tuple

from agents.content_agent import SCRIPT_ARTIFACT_TYPE, ScriptArtifact
from agents.generation_approval_gate import GenerationRequest
from agents.script_production_bridge import (
    BRIDGE_CONTRACT_VERSION,
    ProductionPreparationRequest,
    ProductionPreparationStatus,
)
from agents.video_production_preparation import (
    CONTRACT_VERSION as PREPARATION_CONTRACT_VERSION,
    VideoProductionPreparationResult,
)
from integrations.higgsfield.types import MediaReference

REVIEW_CONTRACT_VERSION = 1
REVIEW_ARTIFACT_TYPE = "PreProductionReview"
PRODUCER_AGENT = "pre-production-review"
PRODUCER_VERSION = "1.0"

SUPPORTED_BRIDGE_CONTRACT_VERSIONS = frozenset({BRIDGE_CONTRACT_VERSION})
SUPPORTED_PREPARATION_CONTRACT_VERSIONS = frozenset({PREPARATION_CONTRACT_VERSION})

# Same asset roles VideoAgent/ScriptProductionBridge already treat as
# identity-relevant -- restated here, not imported, to avoid a new
# cross-module coupling for two literal strings.
START_IMAGE_ROLE = "master_avatar"
IMAGE_REFERENCE_ROLES = ("face_reference",)


class PreProductionReviewError(ValueError):
    """Raised for a structurally invalid `PreProductionReviewInput`
    (e.g. `preparation_result` is not a real
    `VideoProductionPreparationResult`) -- never a silent fallback."""


class PreProductionReviewStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ReadinessFailureCategory(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"
    INTEGRITY_FAILURE = "INTEGRITY_FAILURE"
    MISSING_PROVENANCE = "MISSING_PROVENANCE"
    CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
    INCOMPLETE_PRODUCTION_REQUEST = "INCOMPLETE_PRODUCTION_REQUEST"
    INTERNAL_REVIEW_FAILURE = "INTERNAL_REVIEW_FAILURE"


# ----------------------------------------------------------------------
# INPUT CONTRACT (Section 6)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class PreProductionReviewInput:
    preparation_result: VideoProductionPreparationResult

    # Optional caller-supplied canonical expected values (e.g. Video 005
    # regression, Section 8) -- NEVER fabricated internally. `None`
    # means "not checked against an external canonical value"; the
    # review still checks internal prompt/asset consistency regardless.
    expected_prompt_sha256: Optional[str] = None
    expected_asset_sha256_by_role: Optional[Dict[str, str]] = None

    review_id: Optional[str] = None
    clock: Optional[Callable[[], str]] = None


# ----------------------------------------------------------------------
# OUTPUT CONTRACT (Section 6/19/20) -- immutable.
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ReadinessFinding:
    dimension: str
    passed: bool
    detail: str
    category: Optional[ReadinessFailureCategory] = None  # None iff passed


@dataclass(frozen=True)
class PreProductionReview:
    review_id: str
    artifact_type: str
    created_at: str
    contract_version: int

    request_id: Optional[str]
    mission_id: str

    status: PreProductionReviewStatus
    findings: Tuple[ReadinessFinding, ...]
    reasons: Tuple[str, ...]  # detail of every failing finding, in order

    production_preparation: Optional[ProductionPreparationRequest]  # verbatim
    generation_request: Optional[GenerationRequest]  # verbatim, never rewritten

    producer_agent: str
    producer_version: str

    content_hash: str


def _default_clock() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_review_hash(
    request_id: Optional[str],
    mission_id: str,
    status: str,
    findings: Tuple[ReadinessFinding, ...],
    production_preparation_content_hash: Optional[str],
    contract_version: int,
) -> str:
    canonical = {
        "request_id": request_id,
        "mission_id": mission_id,
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
        "production_preparation_content_hash": production_preparation_content_hash,
        "contract_version": contract_version,
    }
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# READINESS DIMENSIONS (Section 7) -- each a pure function of the real
# input, returning exactly one ReadinessFinding. Never reaches outside
# the immutable objects it was given (no scanning, no I/O, no provider).
# ----------------------------------------------------------------------


def _find_media_reference(
    references: Tuple[MediaReference, ...], role: str, sha256: Optional[str]
) -> bool:
    return any(ref.role == role and ref.sha256 == sha256 for ref in references)


def _check_request_identity(gr: Optional[GenerationRequest]) -> ReadinessFinding:
    if gr is None:
        return ReadinessFinding(
            "request_identity", False,
            "No GenerationRequest is present (production preparation did not reach READY).",
            ReadinessFailureCategory.INCOMPLETE_PRODUCTION_REQUEST,
        )
    if not isinstance(gr.request_id, str) or not gr.request_id.strip():
        return ReadinessFinding(
            "request_identity", False,
            f"generation_request.request_id is missing or empty ({gr.request_id!r}).",
            ReadinessFailureCategory.INVALID_INPUT,
        )
    return ReadinessFinding("request_identity", True, f"request_id='{gr.request_id}'.")


def _check_mission_identity(
    result: VideoProductionPreparationResult, prepared: Optional[ProductionPreparationRequest]
) -> ReadinessFinding:
    if not isinstance(result.mission_id, str) or not result.mission_id.strip():
        return ReadinessFinding(
            "mission_identity", False, "mission_id is missing or empty.",
            ReadinessFailureCategory.INVALID_INPUT,
        )
    if prepared is not None and prepared.mission_id != result.mission_id:
        return ReadinessFinding(
            "mission_identity", False,
            f"preparation_result.mission_id '{result.mission_id}' does not match "
            f"production_preparation.mission_id '{prepared.mission_id}'.",
            ReadinessFailureCategory.CONTRACT_MISMATCH,
        )
    return ReadinessFinding("mission_identity", True, f"mission_id='{result.mission_id}'.")


def _check_script_artifact_provenance(prepared: Optional[ProductionPreparationRequest]) -> ReadinessFinding:
    if prepared is None:
        return ReadinessFinding(
            "script_artifact_provenance", False, "No production_preparation is present.",
            ReadinessFailureCategory.MISSING_PROVENANCE,
        )
    script = prepared.script_artifact
    if not isinstance(script, ScriptArtifact):
        return ReadinessFinding(
            "script_artifact_provenance", False,
            "production_preparation.script_artifact is not a real ScriptArtifact.",
            ReadinessFailureCategory.MISSING_PROVENANCE,
        )
    if script.artifact_type != SCRIPT_ARTIFACT_TYPE:
        return ReadinessFinding(
            "script_artifact_provenance", False,
            f"script_artifact.artifact_type '{script.artifact_type}' is not '{SCRIPT_ARTIFACT_TYPE}'.",
            ReadinessFailureCategory.CONTRACT_MISMATCH,
        )
    if not script.artifact_id or not script.content_hash:
        return ReadinessFinding(
            "script_artifact_provenance", False,
            "script_artifact is missing artifact_id or content_hash.",
            ReadinessFailureCategory.MISSING_PROVENANCE,
        )
    return ReadinessFinding(
        "script_artifact_provenance", True,
        f"script_artifact_id='{script.artifact_id}', content_hash='{script.content_hash}'.",
    )


def _check_source_artifact_integrity(prepared: Optional[ProductionPreparationRequest]) -> ReadinessFinding:
    if prepared is None or not isinstance(prepared.script_artifact, ScriptArtifact):
        return ReadinessFinding(
            "source_artifact_integrity", False, "No valid script_artifact to verify.",
            ReadinessFailureCategory.MISSING_PROVENANCE,
        )
    script = prepared.script_artifact
    if script.status != "FINAL":
        return ReadinessFinding(
            "source_artifact_integrity", False,
            f"script_artifact.status '{script.status}' is not 'FINAL'.",
            ReadinessFailureCategory.INTEGRITY_FAILURE,
        )
    if not script.scenes:
        return ReadinessFinding(
            "source_artifact_integrity", False, "script_artifact.scenes is empty.",
            ReadinessFailureCategory.INTEGRITY_FAILURE,
        )
    if not isinstance(script.total_duration_target, int) or script.total_duration_target <= 0:
        return ReadinessFinding(
            "source_artifact_integrity", False,
            f"script_artifact.total_duration_target ({script.total_duration_target!r}) is not positive.",
            ReadinessFailureCategory.INTEGRITY_FAILURE,
        )
    return ReadinessFinding("source_artifact_integrity", True, "script_artifact is structurally intact.")


def _check_prompt_provenance(prepared: Optional[ProductionPreparationRequest]) -> ReadinessFinding:
    if prepared is None:
        return ReadinessFinding(
            "prompt_provenance", False, "No production_preparation is present.",
            ReadinessFailureCategory.MISSING_PROVENANCE,
        )
    if not prepared.prompt_source:
        return ReadinessFinding(
            "prompt_provenance", False,
            "production_preparation.prompt_source is missing -- prompt origin is not traceable.",
            ReadinessFailureCategory.MISSING_PROVENANCE,
        )
    return ReadinessFinding("prompt_provenance", True, f"prompt_source='{prepared.prompt_source}'.")


def _check_prompt_integrity(
    gr: Optional[GenerationRequest],
    prepared: Optional[ProductionPreparationRequest],
    expected_prompt_sha256: Optional[str],
) -> ReadinessFinding:
    if gr is None or not isinstance(gr.prompt, str) or not gr.prompt.strip():
        return ReadinessFinding(
            "prompt_integrity", False, "generation_request.prompt is missing, empty, or blank.",
            ReadinessFailureCategory.INCOMPLETE_PRODUCTION_REQUEST,
        )
    if prepared is not None and prepared.prompt is not None and gr.prompt != prepared.prompt:
        return ReadinessFinding(
            "prompt_integrity", False,
            "generation_request.prompt does not match production_preparation.prompt verbatim "
            "-- possible unexpected rewrite.",
            ReadinessFailureCategory.INTEGRITY_FAILURE,
        )
    if expected_prompt_sha256:
        actual = hashlib.sha256(gr.prompt.encode("utf-8")).hexdigest()
        if actual != expected_prompt_sha256:
            return ReadinessFinding(
                "prompt_integrity", False,
                f"prompt sha256 '{actual}' does not match expected canonical value "
                f"'{expected_prompt_sha256}'.",
                ReadinessFailureCategory.INTEGRITY_FAILURE,
            )
    return ReadinessFinding("prompt_integrity", True, "prompt is present and matches expected provenance.")


def _used_media_references(gr: Optional[GenerationRequest]) -> Tuple[MediaReference, ...]:
    if gr is None:
        return ()
    refs = []
    if gr.start_image is not None:
        refs.append(gr.start_image)
    refs.extend(gr.image_references)
    return tuple(refs)


def _check_asset_provenance(
    gr: Optional[GenerationRequest], prepared: Optional[ProductionPreparationRequest]
) -> ReadinessFinding:
    used = _used_media_references(gr)
    if not used:
        return ReadinessFinding(
            "asset_provenance", True, "No visual asset references are attached; nothing to trace.",
        )
    known = prepared.asset_references if prepared is not None else ()
    for ref in used:
        if not _find_media_reference(known, ref.role, ref.sha256):
            return ReadinessFinding(
                "asset_provenance", False,
                f"generation_request reference role='{ref.role}' sha256='{ref.sha256}' does not "
                "trace back to production_preparation.asset_references.",
                ReadinessFailureCategory.MISSING_PROVENANCE,
            )
    return ReadinessFinding("asset_provenance", True, f"{len(used)} reference(s) trace to production_preparation.")


def _check_asset_integrity(
    gr: Optional[GenerationRequest], expected_asset_sha256_by_role: Optional[Dict[str, str]]
) -> ReadinessFinding:
    used = _used_media_references(gr)
    for ref in used:
        if not ref.sha256:
            return ReadinessFinding(
                "asset_integrity", False,
                f"reference role='{ref.role}' has no sha256 -- cannot verify integrity.",
                ReadinessFailureCategory.INTEGRITY_FAILURE,
            )
    if expected_asset_sha256_by_role:
        for role, expected_sha256 in expected_asset_sha256_by_role.items():
            matching = [ref for ref in used if ref.role == role]
            if not matching:
                return ReadinessFinding(
                    "asset_integrity", False,
                    f"expected reference role='{role}' is not present in generation_request.",
                    ReadinessFailureCategory.MISSING_PROVENANCE,
                )
            if matching[0].sha256 != expected_sha256:
                return ReadinessFinding(
                    "asset_integrity", False,
                    f"reference role='{role}' sha256='{matching[0].sha256}' does not match "
                    f"expected canonical value '{expected_sha256}'.",
                    ReadinessFailureCategory.INTEGRITY_FAILURE,
                )
    return ReadinessFinding("asset_integrity", True, "all attached references carry a verifiable sha256.")


def _check_model_job_type_consistency(
    gr: Optional[GenerationRequest], prepared: Optional[ProductionPreparationRequest]
) -> ReadinessFinding:
    if gr is None or not gr.job_type:
        return ReadinessFinding(
            "model_job_type_consistency", False, "generation_request.job_type is missing.",
            ReadinessFailureCategory.INCOMPLETE_PRODUCTION_REQUEST,
        )
    if prepared is not None and prepared.job_type is not None and gr.job_type != prepared.job_type:
        return ReadinessFinding(
            "model_job_type_consistency", False,
            f"generation_request.job_type '{gr.job_type}' does not match "
            f"production_preparation.job_type '{prepared.job_type}'.",
            ReadinessFailureCategory.CONTRACT_MISMATCH,
        )
    return ReadinessFinding("model_job_type_consistency", True, f"job_type='{gr.job_type}'.")


def _check_duration(
    gr: Optional[GenerationRequest], prepared: Optional[ProductionPreparationRequest]
) -> ReadinessFinding:
    # NOT cross-checked against production_preparation.duration_seconds
    # (script_artifact.total_duration_target, P3.13) for PASS/FAIL --
    # module docstring's "DURATION POLICY (P3.16 Section 7, Option D)":
    # the two are intentionally different concepts (content-planning
    # target vs. real technical production duration), never required to
    # be equal, and asserting equality would fabricate a readiness
    # criterion the actual architecture does not support. This dimension
    # is therefore structurally gated on `generation_request.duration`
    # alone (must be a positive integer) -- but per Section 8's "no
    # silent overwriting" instruction, `detail` always surfaces BOTH
    # values (and the reason they may differ) when a script-derived
    # duration_seconds is present, so the divergence stays visible
    # rather than silently dropped.
    if gr is None or not isinstance(gr.duration, int) or gr.duration <= 0:
        duration = gr.duration if gr is not None else None
        return ReadinessFinding(
            "duration_validation", False,
            f"generation_request.duration ({duration!r}) is not a positive integer.",
            ReadinessFailureCategory.INCOMPLETE_PRODUCTION_REQUEST,
        )
    script_duration = prepared.duration_seconds if prepared is not None else None
    if script_duration is not None and script_duration != gr.duration:
        return ReadinessFinding(
            "duration_validation", True,
            f"generation_request.duration={gr.duration} (technical production duration, "
            f"sourced from VideoPlan.duration) differs from "
            f"production_preparation.duration_seconds={script_duration} (content-planning "
            "target, sourced from ScriptArtifact.total_duration_target) -- intentional, "
            "per P3.16 duration policy: these are two distinct concepts, not required to "
            "match.",
        )
    return ReadinessFinding("duration_validation", True, f"duration={gr.duration}.")


def _check_resolution(gr: Optional[GenerationRequest]) -> ReadinessFinding:
    if gr is None or not gr.resolution or not str(gr.resolution).strip():
        return ReadinessFinding(
            "resolution_validation", False, "generation_request.resolution is missing or empty.",
            ReadinessFailureCategory.INCOMPLETE_PRODUCTION_REQUEST,
        )
    return ReadinessFinding("resolution_validation", True, f"resolution='{gr.resolution}'.")


def _check_aspect_ratio(gr: Optional[GenerationRequest]) -> ReadinessFinding:
    if gr is None or not gr.aspect_ratio or not str(gr.aspect_ratio).strip():
        return ReadinessFinding(
            "aspect_ratio_validation", False, "generation_request.aspect_ratio is missing or empty.",
            ReadinessFailureCategory.INCOMPLETE_PRODUCTION_REQUEST,
        )
    return ReadinessFinding("aspect_ratio_validation", True, f"aspect_ratio='{gr.aspect_ratio}'.")


def _check_reference_requirements(
    gr: Optional[GenerationRequest], prepared: Optional[ProductionPreparationRequest]
) -> ReadinessFinding:
    if prepared is None:
        return ReadinessFinding(
            "reference_requirements", True, "No production_preparation to require references from.",
        )
    known_roles = {ref.role for ref in prepared.asset_references}
    if START_IMAGE_ROLE in known_roles:
        if gr is None or gr.start_image is None:
            return ReadinessFinding(
                "reference_requirements", False,
                f"production_preparation resolved a '{START_IMAGE_ROLE}' asset, but "
                "generation_request.start_image is missing.",
                ReadinessFailureCategory.INCOMPLETE_PRODUCTION_REQUEST,
            )
    for role in IMAGE_REFERENCE_ROLES:
        if role in known_roles:
            present = gr is not None and any(ref.role == role for ref in gr.image_references)
            if not present:
                return ReadinessFinding(
                    "reference_requirements", False,
                    f"production_preparation resolved a '{role}' asset, but generation_request "
                    "does not carry it in image_references.",
                    ReadinessFailureCategory.INCOMPLETE_PRODUCTION_REQUEST,
                )
    return ReadinessFinding("reference_requirements", True, "all resolved reference roles are carried through.")


def _check_generation_request_structural_validity(gr: Optional[GenerationRequest]) -> ReadinessFinding:
    if gr is None:
        return ReadinessFinding(
            "generation_request_structural_validity", False, "generation_request is missing.",
            ReadinessFailureCategory.INCOMPLETE_PRODUCTION_REQUEST,
        )
    if not isinstance(gr, GenerationRequest):
        return ReadinessFinding(
            "generation_request_structural_validity", False,
            "generation_request is not a real GenerationRequest instance.",
            ReadinessFailureCategory.INVALID_INPUT,
        )
    if gr.approved is not False or gr.real_generation_authorization is not None:
        # Defensive, should be structurally impossible via P3.14's own
        # hardcoding -- a real contract violation if it ever happens,
        # never silently accepted (Section 15, authority separation).
        return ReadinessFinding(
            "generation_request_structural_validity", False,
            "generation_request is already approved/authorized before review -- "
            "this violates the technical/authorization boundary and must never happen.",
            ReadinessFailureCategory.INTERNAL_REVIEW_FAILURE,
        )
    return ReadinessFinding("generation_request_structural_validity", True, "generation_request is structurally valid and unauthorized.")


def _check_metadata_completeness(gr: Optional[GenerationRequest]) -> ReadinessFinding:
    if gr is None:
        return ReadinessFinding(
            "metadata_completeness", False, "generation_request is missing.",
            ReadinessFailureCategory.INCOMPLETE_PRODUCTION_REQUEST,
        )
    missing = [
        name
        for name, value in (
            ("job_type", gr.job_type),
            ("prompt", gr.prompt),
            ("duration", gr.duration),
            ("resolution", gr.resolution),
            ("aspect_ratio", gr.aspect_ratio),
        )
        if not value
    ]
    if missing:
        return ReadinessFinding(
            "metadata_completeness", False, f"generation_request is missing: {missing}.",
            ReadinessFailureCategory.INCOMPLETE_PRODUCTION_REQUEST,
        )
    return ReadinessFinding("metadata_completeness", True, "all production metadata fields are present.")


def _check_contract_version(
    result: VideoProductionPreparationResult, prepared: Optional[ProductionPreparationRequest]
) -> ReadinessFinding:
    if result.contract_version not in SUPPORTED_PREPARATION_CONTRACT_VERSIONS:
        return ReadinessFinding(
            "contract_version_compatibility", False,
            f"preparation_result.contract_version {result.contract_version} is not supported "
            f"(supported: {sorted(SUPPORTED_PREPARATION_CONTRACT_VERSIONS)}).",
            ReadinessFailureCategory.CONTRACT_MISMATCH,
        )
    if prepared is not None and prepared.contract_version not in SUPPORTED_BRIDGE_CONTRACT_VERSIONS:
        return ReadinessFinding(
            "contract_version_compatibility", False,
            f"production_preparation.contract_version {prepared.contract_version} is not supported "
            f"(supported: {sorted(SUPPORTED_BRIDGE_CONTRACT_VERSIONS)}).",
            ReadinessFailureCategory.CONTRACT_MISMATCH,
        )
    return ReadinessFinding("contract_version_compatibility", True, "all contract versions are supported.")


def _check_production_preparation_status(result: VideoProductionPreparationResult) -> ReadinessFinding:
    if result.status != ProductionPreparationStatus.READY:
        return ReadinessFinding(
            "production_preparation_status", False,
            f"production preparation status is '{result.status.value}', not READY "
            f"(reasons: {list(result.reasons)}).",
            ReadinessFailureCategory.INCOMPLETE_PRODUCTION_REQUEST,
        )
    return ReadinessFinding("production_preparation_status", True, "production preparation status is READY.")


# ----------------------------------------------------------------------
# REVIEWER (Section 4/13) -- single responsibility: review. Never
# orchestrates agents, never becomes the State Machine, never a
# production executor.
# ----------------------------------------------------------------------


class PreProductionReviewer:
    """
    AI DIRECTOR — Pre-Production Reviewer (P3.15)

    Stateless: holds no injected collaborator, no provider, no lock, no
    state machine reference. `review()` is a pure function of its
    `PreProductionReviewInput`.
    """

    def review(self, request: PreProductionReviewInput) -> PreProductionReview:
        if not isinstance(request.preparation_result, VideoProductionPreparationResult):
            raise PreProductionReviewError(
                "preparation_result is not a valid VideoProductionPreparationResult instance; "
                "this module never fabricates one."
            )

        result = request.preparation_result
        prepared = result.production_preparation
        gr = result.generation_request

        findings: list = [
            _check_production_preparation_status(result),
            _check_request_identity(gr),
            _check_mission_identity(result, prepared),
            _check_script_artifact_provenance(prepared),
            _check_source_artifact_integrity(prepared),
            _check_prompt_provenance(prepared),
            _check_prompt_integrity(gr, prepared, request.expected_prompt_sha256),
            _check_asset_provenance(gr, prepared),
            _check_asset_integrity(gr, request.expected_asset_sha256_by_role),
            _check_model_job_type_consistency(gr, prepared),
            _check_duration(gr, prepared),
            _check_resolution(gr),
            _check_aspect_ratio(gr),
            _check_reference_requirements(gr, prepared),
            _check_generation_request_structural_validity(gr),
            _check_metadata_completeness(gr),
            _check_contract_version(result, prepared),
        ]
        findings_t = tuple(findings)

        reasons = tuple(f.detail for f in findings_t if not f.passed)
        status = PreProductionReviewStatus.FAIL if reasons else PreProductionReviewStatus.PASS

        clock = request.clock or _default_clock
        review_id = request.review_id or uuid.uuid4().hex
        created_at = clock()

        content_hash = compute_review_hash(
            request_id=(gr.request_id if gr is not None else None),
            mission_id=result.mission_id,
            status=status.value,
            findings=findings_t,
            production_preparation_content_hash=(prepared.content_hash if prepared is not None else None),
            contract_version=REVIEW_CONTRACT_VERSION,
        )

        return PreProductionReview(
            review_id=review_id,
            artifact_type=REVIEW_ARTIFACT_TYPE,
            created_at=created_at,
            contract_version=REVIEW_CONTRACT_VERSION,
            request_id=(gr.request_id if gr is not None else None),
            mission_id=result.mission_id,
            status=status,
            findings=findings_t,
            reasons=reasons,
            production_preparation=prepared,
            generation_request=gr,
            producer_agent=PRODUCER_AGENT,
            producer_version=PRODUCER_VERSION,
            content_hash=content_hash,
        )
