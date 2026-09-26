"""
AI DIRECTOR — Script -> Production Bridge (Phase P3.13)

TRANSLATION LAYER ONLY, built directly against the REAL contracts
re-read from disk before writing a line of this module:
`agents/content_agent.py` (ScriptArtifact/Scene, `SCRIPT_ARTIFACT_TYPE`,
`CONTRACT_VERSION`, `compute_script_artifact_hash`), `agents/
prompt_assembly_system.py`, `agents/asset_preparation_system.py`,
`agents/video_agent.py`, `agents/planner.py`, `agents/production_model.py`,
`agents/generation_approval_gate.py` (`GenerationRequest`'s real field
shape), `agents/mission_state_machine.py`, `agents/director_pipeline.py`,
and `director.py`.

RESPONSIBILITY (P3.13 Section 4): translate a real `ScriptArtifact`
(P3.6) plus already-known production metadata into a
`ProductionPreparationRequest` -- nothing more. This module never
generates a video, never calls a provider, never crosses the P2
boundary (`GenerationApprovalGate`, `GenerationJobService`,
`HiggsfieldProvider`) and never constructs any production authority
object.

TWO REAL ARCHITECTURAL GAPS FOUND DURING THE MANDATORY AUDIT (P3.13
Section 3), STATED ONCE, PRECISELY, BECAUSE THEY BOUND WHAT THIS MODULE
CAN HONESTLY DO:

1. `PromptAssemblySystem.assemble(video_id)` (V1) loads STATIC markdown
   files from `assets/zephyr/prompts/` keyed by `video_id` -- it has no
   parameter and no mechanism to consume a `ScriptArtifact`'s actual
   generated scene text. There is today no real link between a
   dynamically produced P3.6 `ScriptArtifact` and any on-disk prompt
   file. Per this phase's Section 9 instruction ("if PromptAssemblySystem
   does not yet accept ScriptArtifact, do NOT modify it automatically --
   document the gap"), this module does NOT modify
   `PromptAssemblySystem`, does NOT reconstruct its Identity/Visual
   Style/Video Prompt assembly logic itself (which would duplicate that
   system's sole responsibility), and does NOT silently assert that a
   given `video_id` corresponds to a given `ScriptArtifact`. Instead: a
   caller who has that mission context may EXPLICITLY supply
   `(video_id, prompt_assembly)` for real delegation to the existing
   system, or supply an already-resolved `prompt` string directly. If
   neither is supplied, `prompt` stays `None` and the resulting
   `ProductionPreparationRequest.status` is `INCOMPLETE` -- never a
   fabricated prompt.

2. `agents/planner.py::Scene` (V1, consumed by `VideoAgent.build_request()`
   via a `VideoPlan`) requires a `camera` field with NO default and no
   equivalent anywhere in P3.6's `ScriptArtifact.Scene` (which has
   `scene_id/order/duration/narration/visual_direction/transition/notes`
   -- no camera direction). This module therefore does NOT attempt to
   construct a `VideoPlan` or call `VideoAgent.build_request()` itself
   (constructing one would require fabricating a camera direction that
   does not exist anywhere in the real P3 pipeline -- forbidden by
   Section 25, "UNKNOWN stays UNKNOWN"). Per Section 11 ("the bridge MAY
   produce VideoAgent's expected input, but VideoAgent stays responsible
   for building its own technical request" -- "peut", not "doit"), this
   module instead hands back exactly the two fields of `VideoAgent.
   build_request(plan, prompt=..., job_type=...)` that it DOES own
   without fabrication (`prompt`, `job_type`) via
   `ScriptProductionBridge.build_video_agent_kwargs()`, called only when
   `status == READY`. Building an actual `VideoPlan` (camera direction
   per scene) remains a documented future gap, never forced here.

PRODUCTION METADATA (Section 17): `duration_seconds` is never invented
-- it is read verbatim from `script_artifact.total_duration_target`
(already computed by the real `ContentAgent`, P3.6). `job_type` defaults
to `agents.production_model.PRODUCTION_MODEL` (the repository's own
single source of truth for the real Higgsfield model, P2.2) only when
the caller does not override it -- never a new literal recopied here.
`resolution`/`aspect_ratio` have NO equivalent in any real P3 contract
and no P3-side canonical source exists (the only existing sources,
`agents/video_agent.py` and `agents/cost_engine.py`, both sit on the P2
side and the latter imports `HiggsfieldClient` directly) -- so this
module never defaults them; they are purely optional, caller-supplied
pass-through fields, exactly like the `Optional[str] = None` shape
`GenerationRequest` itself already gives them.

AUTHORITY (Section 13): a `READY` status means only "technical
preparation possible" -- never "production authorized". This module
never constructs `RealGenerationAuthorization`,
`RequestScopedActivationContract`, or
`ControlledRealProviderActivationContract`, never imports
`GenerationApprovalGate`/`GenerationJobService`/`HiggsfieldProvider`/
`HiggsfieldClient`, and never calls `create_job`.

STATE MACHINE (Section 14): this module never imports
`agents.mission_state_machine` and never calls `.transition()` --
representing `PROMPT_READY`/`ASSETS_READY`/`VIDEO_READY_FOR_REVIEW` in
the real Mission State Machine remains exclusively the Director/
Orchestrator's call (P3.12 Section 14/30), never this bridge's.

SCRIPT INTEGRITY (Section 7): `ScriptArtifact.content_hash` is
PRESERVED, never recomputed here -- its hash formula
(`compute_script_artifact_hash`) binds to `source_content_content_hash`,
a value that lives on the upstream `ContentArtifact`, not on
`ScriptArtifact` itself; verifying it would require accepting a
`ContentArtifact` this phase's input contract (Section 6) does not
call for, and Section 7 itself says not to re-derive an agent's own
business rules. This module instead validates STRUCTURAL contract
validity: real type, real `artifact_type`, matching `mission_id`,
`status == "FINAL"`, a supported `contract_version`, and non-empty,
positively-durationed scenes -- then preserves every identity field
(`artifact_id`, `version`, `content_hash`, `dependencies`) untouched.

NO SCRIPT REWRITE (Section 8): this module never imports
`dataclasses.replace` and never assigns to any `ScriptArtifact`
attribute -- it is frozen anyway, so mutation is not even possible in
Python, but no reconstruction via `replace()` happens either.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional, Tuple

from agents.asset_preparation_system import AssetPreparationSystem
from agents.content_agent import (
    CONTRACT_VERSION as SCRIPT_CONTRACT_VERSION,
    SCRIPT_ARTIFACT_TYPE,
    ScriptArtifact,
)
from agents.production_model import PRODUCTION_MODEL
from agents.prompt_assembly_system import PromptAssemblySystem
from integrations.higgsfield.types import MediaReference

# ----------------------------------------------------------------------
# VERSIONING -- explicit, no migration infrastructure (mirrors P3.12
# Section 18's discipline).
# ----------------------------------------------------------------------

BRIDGE_CONTRACT_VERSION = 1
PREPARATION_ARTIFACT_TYPE = "ProductionPreparationRequest"
PRODUCER_AGENT = "script-production-bridge"
PRODUCER_VERSION = "1.0"

SUPPORTED_SCRIPT_CONTRACT_VERSIONS = frozenset({SCRIPT_CONTRACT_VERSION})

# Same asset roles VideoAgent itself already treats as identity-relevant
# (agents/video_agent.py) -- restated here, not imported, to avoid this
# module ever importing agents.video_agent (which itself imports the P2
# GenerationRequest/RealGenerationAuthorization types purely as
# annotations -- this bridge stays structurally clear of that chain
# entirely, per Section 12's boundary).
START_IMAGE_ROLE = "master_avatar"
IMAGE_REFERENCE_ROLES = ("face_reference",)


class ProductionPreparationStatus(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    INCOMPLETE = "INCOMPLETE"


class ProductionPreparationNotReadyError(RuntimeError):
    """Raised by `build_video_agent_kwargs()` when asked to hand over
    VideoAgent inputs from a non-READY preparation -- never silently
    returns a partial/fabricated result."""

    def __init__(self, status: ProductionPreparationStatus, reasons: Tuple[str, ...]):
        super().__init__(
            f"ProductionPreparationRequest is not READY (status={status.value}); "
            f"reasons: {list(reasons)}"
        )
        self.status = status
        self.reasons = reasons


# ----------------------------------------------------------------------
# INPUT CONTRACT (Section 6)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ProductionPreparationInput:
    mission_id: str
    script_artifact: ScriptArtifact  # REQUIRED -- no default, same
    # discipline as ContentAgentInput.strategy_artifact (P3.6).

    # Caller-supplied production metadata -- never fabricated internally.
    job_type: Optional[str] = None
    resolution: Optional[str] = None
    aspect_ratio: Optional[str] = None

    # Prompt -- either an already-resolved string, or explicit delegation
    # to PromptAssemblySystem via video_id (Section 9). Never both
    # silently merged: an explicit `prompt` always wins over delegation.
    prompt: Optional[str] = None
    prompt_source: Optional[str] = None
    video_id: Optional[str] = None

    clock: Optional[Callable[[], str]] = None


# ----------------------------------------------------------------------
# OUTPUT CONTRACT (Section 5/20/21) -- immutable.
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ProductionPreparationRequest:
    preparation_id: str
    artifact_type: str
    mission_id: str
    created_at: str
    contract_version: int

    status: ProductionPreparationStatus
    reasons: Tuple[str, ...]
    missing_requirements: Tuple[str, ...]

    script_artifact: Optional[ScriptArtifact]  # verbatim, never rewritten

    job_type: Optional[str]
    duration_seconds: Optional[int]
    resolution: Optional[str]
    aspect_ratio: Optional[str]

    prompt: Optional[str]
    prompt_source: Optional[str]

    asset_references: Tuple[MediaReference, ...]

    producer_agent: str
    producer_version: str

    content_hash: str


def _default_clock() -> str:
    return datetime.now(timezone.utc).isoformat()


# ----------------------------------------------------------------------
# SCRIPT INTEGRITY (Section 7) -- structural validation only, never a
# re-derivation of ContentAgent's own business rules.
# ----------------------------------------------------------------------


def _validate_script(mission_id: str, script_artifact) -> Tuple[str, ...]:
    errors = []

    if script_artifact is None:
        return ("script_artifact is missing; the bridge cannot prepare production without it.",)

    if not isinstance(script_artifact, ScriptArtifact):
        return ("script_artifact is not a valid ScriptArtifact instance.",)

    if script_artifact.artifact_type != SCRIPT_ARTIFACT_TYPE:
        errors.append(
            f"script_artifact.artifact_type '{script_artifact.artifact_type}' "
            f"is not '{SCRIPT_ARTIFACT_TYPE}'."
        )

    if script_artifact.mission_id != mission_id:
        errors.append(
            f"script_artifact.mission_id '{script_artifact.mission_id}' does not "
            f"match this request's mission_id '{mission_id}' -- refusing to "
            f"bridge a ScriptArtifact belonging to a different mission."
        )

    if script_artifact.status != "FINAL":
        errors.append(f"script_artifact.status '{script_artifact.status}' is not 'FINAL'.")

    if script_artifact.contract_version not in SUPPORTED_SCRIPT_CONTRACT_VERSIONS:
        errors.append(
            f"script_artifact.contract_version {script_artifact.contract_version} "
            f"is not supported by this bridge (supported: "
            f"{sorted(SUPPORTED_SCRIPT_CONTRACT_VERSIONS)})."
        )

    if not script_artifact.scenes:
        errors.append("script_artifact.scenes is empty; nothing to prepare for production.")
    else:
        for scene in script_artifact.scenes:
            if not isinstance(scene.duration, int) or scene.duration <= 0:
                errors.append(
                    f"script_artifact scene '{scene.scene_id}' has a non-positive "
                    f"duration ({scene.duration!r})."
                )

    if not isinstance(script_artifact.total_duration_target, int) or script_artifact.total_duration_target <= 0:
        errors.append(
            f"script_artifact.total_duration_target "
            f"({script_artifact.total_duration_target!r}) is not a positive integer."
        )

    return tuple(errors)


# ----------------------------------------------------------------------
# HASH / DETERMINISM (Section 19/22/23) -- excludes preparation_id/
# created_at (technical/temporal), mirroring P3.6's own hash discipline.
# ----------------------------------------------------------------------


def compute_preparation_hash(
    mission_id: str,
    script_artifact_id: Optional[str],
    script_content_hash: Optional[str],
    status: str,
    reasons: Tuple[str, ...],
    missing_requirements: Tuple[str, ...],
    job_type: Optional[str],
    duration_seconds: Optional[int],
    resolution: Optional[str],
    aspect_ratio: Optional[str],
    prompt: Optional[str],
    prompt_source: Optional[str],
    asset_sha256s: Tuple[str, ...],
    contract_version: int,
) -> str:
    canonical = {
        "mission_id": mission_id,
        "script_artifact_id": script_artifact_id,
        "script_content_hash": script_content_hash,
        "status": status,
        "reasons": list(reasons),
        "missing_requirements": list(missing_requirements),
        "job_type": job_type,
        "duration_seconds": duration_seconds,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "prompt": prompt,
        "prompt_source": prompt_source,
        "asset_sha256s": list(asset_sha256s),
        "contract_version": contract_version,
    }
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# BRIDGE (Section 4/15) -- single responsibility: translate. Never
# orchestrates agents, never becomes the State Machine.
# ----------------------------------------------------------------------


class ScriptProductionBridge:
    """
    AI DIRECTOR — Script -> Production Bridge (P3.13)

    `prompt_assembly`/`asset_preparation` are injectable (constructor
    parameters, same shape as `VideoAgent.__init__`) -- no hidden
    instantiation. Both default to `None`: a bridge with neither
    configured can still translate script identity/metadata; it simply
    cannot resolve a prompt via delegation or asset references.
    """

    def __init__(
        self,
        prompt_assembly: Optional[PromptAssemblySystem] = None,
        asset_preparation: Optional[AssetPreparationSystem] = None,
    ):
        self.prompt_assembly = prompt_assembly
        self.asset_preparation = asset_preparation

    def _resolve_prompt(self, request: ProductionPreparationInput) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Returns (prompt, prompt_source, error). An explicit `prompt`
        always wins over delegation (Section 9) -- never silently
        merged. Delegation failures are surfaced as an explicit error,
        never swallowed into a fabricated prompt (Section 24)."""

        if request.prompt is not None:
            if not request.prompt.strip():
                return None, None, "prompt was supplied but is empty/blank."
            return request.prompt, (request.prompt_source or "caller_supplied"), None

        if request.video_id is not None and self.prompt_assembly is not None:
            try:
                assembled = self.prompt_assembly.assemble(request.video_id)
            except Exception as error:  # noqa: BLE001 -- surfaced, never masked
                return None, None, f"PromptAssemblySystem delegation failed: {error}"
            return assembled, f"PromptAssemblySystem:{request.video_id}", None

        return None, None, None

    def _resolve_asset_references(self) -> Tuple[MediaReference, ...]:
        """Transmits AssetPreparationSystem's existing READY references
        as-is (Section 10) -- never copies files, never recomputes a
        hash, never invents an asset."""

        if self.asset_preparation is None:
            return ()

        references = []
        for asset in self.asset_preparation.scan():
            if asset.status != "READY":
                continue
            if asset.role == START_IMAGE_ROLE or asset.role in IMAGE_REFERENCE_ROLES:
                references.append(
                    MediaReference(role=asset.role, source=asset.path, sha256=asset.sha256)
                )
        return tuple(references)

    def prepare(self, request: ProductionPreparationInput) -> ProductionPreparationRequest:
        clock = request.clock or _default_clock
        mission_id = request.mission_id if isinstance(request.mission_id, str) else ""

        script_errors = _validate_script(mission_id, request.script_artifact)
        script_artifact = request.script_artifact if not script_errors else None

        if not mission_id.strip():
            script_errors = script_errors + ("mission_id is missing or empty.",)

        job_type = request.job_type or PRODUCTION_MODEL
        duration_seconds = script_artifact.total_duration_target if script_artifact is not None else None

        asset_references = self._resolve_asset_references()

        if script_errors:
            # BLOCKED -- script integrity failure takes priority over
            # any metadata concern (Section 24, fail-closed).
            status = ProductionPreparationStatus.BLOCKED
            missing_requirements: Tuple[str, ...] = ()
            prompt, prompt_source = None, None
        else:
            prompt, prompt_source, prompt_error = self._resolve_prompt(request)
            missing_list = []
            if prompt is None:
                missing_list.append(
                    prompt_error
                    or "prompt not resolved: no prompt provided and no (video_id, "
                    "prompt_assembly) supplied for delegation to PromptAssemblySystem."
                )
            missing_requirements = tuple(missing_list)
            status = (
                ProductionPreparationStatus.READY
                if not missing_requirements
                else ProductionPreparationStatus.INCOMPLETE
            )

        preparation_id = uuid.uuid4().hex
        created_at = clock()

        content_hash = compute_preparation_hash(
            mission_id=mission_id,
            script_artifact_id=(script_artifact.artifact_id if script_artifact else None),
            script_content_hash=(script_artifact.content_hash if script_artifact else None),
            status=status.value,
            reasons=script_errors,
            missing_requirements=missing_requirements,
            job_type=job_type,
            duration_seconds=duration_seconds,
            resolution=request.resolution,
            aspect_ratio=request.aspect_ratio,
            prompt=prompt,
            prompt_source=prompt_source,
            asset_sha256s=tuple(ref.sha256 for ref in asset_references if ref.sha256),
            contract_version=BRIDGE_CONTRACT_VERSION,
        )

        return ProductionPreparationRequest(
            preparation_id=preparation_id,
            artifact_type=PREPARATION_ARTIFACT_TYPE,
            mission_id=mission_id,
            created_at=created_at,
            contract_version=BRIDGE_CONTRACT_VERSION,
            status=status,
            reasons=script_errors,
            missing_requirements=missing_requirements,
            script_artifact=script_artifact,
            job_type=job_type,
            duration_seconds=duration_seconds,
            resolution=request.resolution,
            aspect_ratio=request.aspect_ratio,
            prompt=prompt,
            prompt_source=prompt_source,
            asset_references=asset_references,
            producer_agent=PRODUCER_AGENT,
            producer_version=PRODUCER_VERSION,
            content_hash=content_hash,
        )

    def build_video_agent_kwargs(self, prepared: ProductionPreparationRequest) -> dict:
        """
        Hands over exactly the two `VideoAgent.build_request(plan,
        prompt=..., job_type=...)` keyword arguments this bridge
        legitimately owns without fabrication (Section 11) -- never a
        `VideoPlan` itself (camera direction has no source in
        `ScriptArtifact`, see module docstring). Only callable on a
        `READY` preparation (Section 24 -- explicit failure, never a
        silent partial result).
        """

        if prepared.status != ProductionPreparationStatus.READY:
            raise ProductionPreparationNotReadyError(prepared.status, prepared.reasons or prepared.missing_requirements)

        return {"prompt": prepared.prompt, "job_type": prepared.job_type}
