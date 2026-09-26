"""
AI DIRECTOR — Video Production Preparation (Phase P3.14)

INTEGRATION LAYER ONLY, built directly against the REAL contracts
re-read from disk before writing a line of this module:
`agents/script_production_bridge.py` (P3.13, re-audited independently
this phase -- confirmed unchanged and correct: `ScriptProductionBridge.
prepare()`/`build_video_agent_kwargs()` behave exactly as documented,
48/48 of P3.13's own tests re-run and pass), `agents/video_agent.py`
(`VideoAgent.build_request(plan, prompt=None, job_type=DEFAULT_JOB_TYPE,
approved=False, request_id=None, real_generation_authorization=None) ->
GenerationRequest`), `agents/planner.py` (`VideoPlan`), and
`agents/generation_approval_gate.py` (`GenerationRequest`'s real field
shape -- imported here ONLY as a type, exactly as `agents/video_agent.py`
itself already does; `GenerationApprovalGate`, `GenerationJobService`,
`HiggsfieldProvider`, and `HiggsfieldClient` are never imported).

REAL GAP CARRIED FORWARD FROM P3.13, NOT REPAIRED HERE: `ScriptArtifact.
Scene` has no `camera` field and `agents/planner.py::Scene.camera` has
no default -- there is still no honest way to derive a `VideoPlan` from
a `ScriptArtifact` without fabricating camera direction. This module
therefore does NOT construct a `VideoPlan` either; the caller supplies
one explicitly (e.g. via the existing, unmodified
`VideoPlanner.create_zephyr_plan()` for Video 005, or a fake in tests).
This is consistent with P3.13's own documented boundary and with this
phase's Section 5 ("the bridge must not duplicate VideoAgent logic" --
extended here to "this integration module must not duplicate VideoPlan
construction either").

RESPONSIBILITY (P3.14 Section 4/5/6): compose exactly two existing,
unmodified building blocks in sequence --
`ScriptProductionBridge.prepare()` (resolves prompt/job_type from a
real `ScriptArtifact`, P3.13) then `VideoAgent.build_request()`
(resolves duration/resolution/aspect_ratio/asset references from the
caller-supplied `VideoPlan` and produces the real `GenerationRequest`,
Phase K) -- and STOP. Neither building block's own logic is
reimplemented or duplicated here; this module only sequences two already
-tested calls and fails closed if the first does not report `READY`.

NO EXECUTION (P3.14 Section 7): this module never imports
`agents.generation_approval_gate.GenerationApprovalGate`,
`agents.generation_job_service.GenerationJobService`,
`integrations.higgsfield.provider.HiggsfieldProvider`, or
`integrations.higgsfield.client.HiggsfieldClient`, and never calls
`create_job`, `.evaluate(`, or `.execute(`. Its output is a PREPARED
`GenerationRequest` with `approved=False` and
`real_generation_authorization=None` -- always, never overridable by
this module -- exactly as `GenerationRequest` itself already guarantees
nothing executes without a Gate decision this module never requests.

AUTHORITY (Section 15): a `GenerationRequest` returned here is not an
approved request, not an authorized generation, and not an activated
provider. This module never constructs `RealGenerationAuthorization`,
`RequestScopedActivationContract`, or
`ControlledRealProviderActivationContract`.

STATE MACHINE (Section 16): this module never imports
`agents.mission_state_machine` and never calls `.transition()` --
whether a successful preparation here should ever be reflected as
`VIDEO_READY_FOR_REVIEW` (or any other Mission State) in the real state
machine remains exclusively a Director/Orchestrator decision, not
exercised automatically by this module (P3.14 Section 17/18 caution:
"do not equate VideoAgent success -> TECHNICAL_APPROVAL unless the
State Machine contract explicitly defines that transition" -- this
module does not make that call at all).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from agents.asset_preparation_system import AssetPreparationSystem
from agents.generation_approval_gate import GenerationRequest
from agents.planner import VideoPlan
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.script_production_bridge import (
    ProductionPreparationInput,
    ProductionPreparationRequest,
    ProductionPreparationStatus,
    ScriptProductionBridge,
)
from agents.video_agent import VideoAgent

CONTRACT_VERSION = 1


class VideoProductionPreparationError(ValueError):
    """Raised for a structurally invalid `VideoProductionPreparationInput`
    (e.g. a `video_plan` that is not a real `VideoPlan`) -- never a
    silent fallback."""


# ----------------------------------------------------------------------
# INPUT CONTRACT
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class VideoProductionPreparationInput:
    production_input: ProductionPreparationInput  # feeds ScriptProductionBridge (P3.13)
    video_plan: VideoPlan  # caller-supplied -- never constructed here (camera gap)
    request_id: Optional[str] = None


# ----------------------------------------------------------------------
# OUTPUT CONTRACT -- immutable. `generation_request` is `None` unless
# `status == READY` (Section 8/24 -- never a partial/fabricated request).
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class VideoProductionPreparationResult:
    mission_id: str
    status: ProductionPreparationStatus
    reasons: Tuple[str, ...]
    production_preparation: ProductionPreparationRequest
    generation_request: Optional[GenerationRequest]
    contract_version: int = CONTRACT_VERSION


# ----------------------------------------------------------------------
# INTEGRATION (Section 4/5/6) -- sequences ScriptProductionBridge then
# VideoAgent; owns neither's internal logic.
# ----------------------------------------------------------------------


class VideoProductionPreparation:
    """
    AI DIRECTOR — Video Production Preparation (P3.14)

    `prompt_assembly`/`asset_preparation` are injectable and, when
    given, are wired into BOTH the internally constructed
    `ScriptProductionBridge` and `VideoAgent` (same instances -- a
    single, consistent source for prompt/asset resolution across this
    integration, never two independently-configured copies). `bridge`/
    `video_agent` may instead be injected directly (e.g. test doubles),
    which takes priority over `prompt_assembly`/`asset_preparation`.
    """

    def __init__(
        self,
        prompt_assembly: Optional[PromptAssemblySystem] = None,
        asset_preparation: Optional[AssetPreparationSystem] = None,
        bridge: Optional[ScriptProductionBridge] = None,
        video_agent: Optional[VideoAgent] = None,
    ):
        self.bridge = bridge or ScriptProductionBridge(
            prompt_assembly=prompt_assembly, asset_preparation=asset_preparation
        )
        self.video_agent = video_agent or VideoAgent(
            prompt_assembly=prompt_assembly, asset_preparation=asset_preparation
        )

    def prepare(self, request: VideoProductionPreparationInput) -> VideoProductionPreparationResult:
        """
        1. `ScriptProductionBridge.prepare()` (P3.13, unmodified) --
           resolves/validates the `ScriptArtifact` and its prompt/
           job_type. Not `READY` -> STOP here; `generation_request`
           stays `None`, `status`/`reasons` mirror the bridge's own
           (Section 22/23 -- failure/incomplete propagated verbatim,
           never reinterpreted or upgraded).
        2. Only when `READY`: `VideoAgent.build_request()` (Phase K,
           unmodified) -- builds the real `GenerationRequest` from the
           caller-supplied `VideoPlan` plus the bridge-resolved
           prompt/job_type. `approved` is hardcoded `False` and
           `real_generation_authorization` hardcoded `None` -- never
           taken from the caller, never inferred (Section 15).
        """

        if not isinstance(request.video_plan, VideoPlan):
            raise VideoProductionPreparationError(
                "video_plan is not a valid VideoPlan instance; this module "
                "never fabricates one (see module docstring's camera-data gap)."
            )

        prepared = self.bridge.prepare(request.production_input)

        if prepared.status != ProductionPreparationStatus.READY:
            return VideoProductionPreparationResult(
                mission_id=prepared.mission_id,
                status=prepared.status,
                reasons=prepared.reasons or prepared.missing_requirements,
                production_preparation=prepared,
                generation_request=None,
            )

        kwargs = self.bridge.build_video_agent_kwargs(prepared)

        generation_request = self.video_agent.build_request(
            request.video_plan,
            prompt=kwargs["prompt"],
            job_type=kwargs["job_type"],
            approved=False,
            request_id=request.request_id,
            real_generation_authorization=None,
        )

        return VideoProductionPreparationResult(
            mission_id=prepared.mission_id,
            status=ProductionPreparationStatus.READY,
            reasons=(),
            production_preparation=prepared,
            generation_request=generation_request,
        )
