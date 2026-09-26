"""
AI DIRECTOR — Business Pipeline Orchestrator (Phase P3.11)

The FIRST real integration of the six P3 business agents
(`StrategyAgent`, `ContentAgent`, `QualityAgent`, `PublishingAgent`,
`AnalyticsAgent`, `OptimizationAgent`) into a single orchestration flow
owned by the Director. Built directly against the REAL contracts of all
six agents (re-read from disk in full, along with `director.py`,
`agents/planner.py`, `agents/task_manager.py`, and every corresponding
test file, before writing a single line of this module) -- no
conceptual P3.1-P3.4 type (`DirectorMission`, `AgentContract`,
`AgentContext`, a real Mission State Machine) is assumed to exist,
because none of them do: those phases produced architecture documents
only, never runnable code. This module does not retroactively implement
them; it defines the smallest new, honestly-named types this
integration actually needs (`BusinessMissionRequest`,
`DirectorPipelineContext`, `StageOutcome`), never claiming to be the
P3.1 `DirectorMission`.

RELATIONSHIP TO `director.py` / THE REAL P2 GENERATION CHAIN -- READ
THIS FIRST:
This module is entirely SEPARATE from, and never calls into,
`AIDirector.run_video_mission()`, `GenerationApprovalGate`,
`GenerationJobService`, `HiggsfieldProvider`, or any other P2
mechanism. `director.py` gains exactly one new, additive method
(`AIDirector.run_business_pipeline()`) that constructs a
`BusinessPipelineOrchestrator` (default: all real, deterministic
agents) and delegates to it -- nothing about the existing P2
orchestration path is touched, reordered, or reused. The two
orchestration paths (P2 real-generation, P3 business-agent pipeline)
remain structurally independent; see `tests/test_director_orchestration.
py::SecurityTests` for the AST proof that this module never reaches
`create_job`, `HiggsfieldProvider`, `RealGenerationAuthorization`, or
any activation contract.

PROMPT/ASSET/VIDEO AGENT INTEGRATION -- DELIBERATELY NOT DONE (Section
23 of this phase's brief): `PromptAssemblySystem`, `AssetPreparationSystem`,
`VideoAgent`, and `agents/planner.py::VideoPlanner` remain part of the
SEPARATE, existing P2 real-generation chain. Bridging a P3.6
`ScriptArtifact` into a P2 `GenerationRequest` would require either (a)
touching the P2 generation boundary (forbidden without an explicit STOP,
which this phase's audit found no genuine need to cross), or (b)
building a translation layer whose correctness this phase has not
scoped or tested. Documented here as explicit future work (Section 41
of the final report), never forced.

ORCHESTRATION PRINCIPLE (Section 3/4): the Director is the SOLE
orchestration authority. Every agent is called directly, synchronously,
by `BusinessPipelineOrchestrator` -- no agent ever calls another agent.
Confirmed structurally: none of `agents/strategy_agent.py`,
`agents/content_agent.py`, `agents/quality_agent.py`,
`agents/publishing_agent.py`, `agents/analytics_agent.py`,
`agents/optimization_agent.py` import each other for orchestration
purposes (they import each other's ARTIFACT TYPES and hash functions
only, to consume/validate contracts -- never to call `.run()` on one
another; re-confirmed by grep across all six files as part of this
phase's audit).

STAGE CONTINUATION RULE (Section 7/8/17/18), the central design
decision of this module, stated once, precisely: after each stage, the
orchestrator checks whether the agent's returned status is a member of
that stage's small, explicit, documented "CONTINUE" set (e.g. Quality's
is `{PASS, PASS_WITH_WARNINGS}` -- exactly the same two values
`PublishingAgent` itself already uses as its own quality gate, P3.8).
Any other status -- a recognized-but-not-good outcome (`FAIL`,
`REJECTED`, `VALIDATION_ERROR`, `INTEGRITY_FAILURE`, `QUALITY_REJECTED`,
...) OR a genuinely unrecognized/anomalous value -- means the
orchestrator does NOT continue "as if all is well" (Section 18's exact
words). The two cases are still recorded distinctly in `StageOutcome`
(`FAILURE` vs `UNKNOWN`) for observability, but neither one silently
advances the pipeline. This is a THIN rule -- a coarse enum-membership
check -- and never reimplements any agent's actual business logic
(score thresholds, dimension checks, hash recomputation, etc.), per
Section 11's explicit instruction not to reproduce agent rules in the
Director.

DEPENDENCY GRAPH ACTUALLY USED (derived from the REAL required-field
contracts, not invented):
    Strategy --(required)--> Content --(required)--> Quality --(required)--> Publishing
    Publishing's outcome does NOT gate Analytics (AnalyticsAgent's only
    REQUIRED input is its own observations -- a PublicationArtifact is
    merely an optional cross-reference, confirmed in P3.10). Analytics
    IS a hard prerequisite for Optimization (its only REQUIRED input,
    confirmed in P3.9).

NO FABRICATED ANALYTICS (Section 13), enforced structurally: the
Analytics stage is only ATTEMPTED if the caller's
`BusinessMissionRequest` explicitly supplies BOTH `analytics_platform`
and `analytics_period` -- `AnalyticsAgentInput.period` is a required,
non-optional field with no safe default this module is willing to
invent (a fabricated time window would itself be fabricated data, not
merely a fabricated metric). If neither is supplied, the stage is
recorded as `NOT_ATTEMPTED` -- never silently skipped without a trace,
never satisfied by inventing a period. `analytics_observations`
defaults to an empty tuple when the caller has no real data yet -- this
is handed to the REAL `AnalyticsAgent` exactly as given, which then
honestly returns its own `REJECTED` (Section 7 of P3.10: "observations
is missing or empty") -- the orchestrator never pre-empts or hides that
outcome.

NO AUTOMATIC AUTHORITY (Section 25/26/29): this module never
constructs a `RealGenerationAuthorization`, a `RequestScopedActivationContract`,
a `ControlledRealProviderActivationContract`, or applies an
`OptimizationRecommendation` (which always remains `PROPOSED`, exactly
as `OptimizationAgent` itself guarantees, P3.9). `QualityArtifact.
quality_status == PASS` is read ONLY to decide whether to attempt the
next pipeline stage -- never as evidence of any human or production
authorization, which remain, as always, explicitly external to this
entire pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Optional, Tuple

from agents.analytics_agent import (
    AnalyticsAgent,
    AnalyticsAgentInput,
    AnalyticsAgentStatus,
    AnalyticsCollectionProfile,
    AnalyticsObservation,
)
from agents.content_agent import (
    ContentAgent,
    ContentAgentInput,
    ContentAgentStatus,
    ContentArtifact,
    ScriptArtifact,
)
from agents.mission_state_machine import MissionState, MissionStateMachine
from agents.optimization_agent import (
    AnalyticsArtifact,
    AnalyticsPeriod,
    OptimizationAgent,
    OptimizationAgentInput,
    OptimizationAgentStatus,
    OptimizationArtifact,
    OptimizationProfile,
)
from agents.publishing_agent import (
    PublicationArtifact,
    PublicationProfile,
    PublishingAgent,
    PublishingAgentInput,
    PublishingAgentStatus,
)
from agents.quality_agent import (
    QualityAgent,
    QualityAgentInput,
    QualityAgentStatus,
    QualityArtifact,
    QualityProfile,
)
from agents.strategy_agent import StrategyAgent, StrategyAgentInput, StrategyAgentStatus, StrategyArtifact

# ----------------------------------------------------------------------
# STAGE OUTCOME CLASSIFICATION (Section 17/18/31) -- the ONLY new
# vocabulary this module introduces for pipeline-level bookkeeping.
# Never confused with any agent's own status enum.
# ----------------------------------------------------------------------


class StageClassification(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNKNOWN = "UNKNOWN"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"


# Per-stage CONTINUE sets -- the ONLY place this module encodes any
# opinion about an agent's status vocabulary, and only as a coarse
# "good enough to proceed" membership check, never a re-derivation of
# how that status was reached.
STRATEGY_CONTINUE = frozenset({StrategyAgentStatus.READY})
CONTENT_CONTINUE = frozenset({ContentAgentStatus.READY})
QUALITY_CONTINUE = frozenset({QualityAgentStatus.PASS, QualityAgentStatus.PASS_WITH_WARNINGS})
PUBLISHING_CONTINUE = frozenset(
    {PublishingAgentStatus.PREPARED, PublishingAgentStatus.PREPARATION_WARNING}
)
ANALYTICS_CONTINUE = frozenset({AnalyticsAgentStatus.COLLECTED, AnalyticsAgentStatus.PARTIAL})
OPTIMIZATION_CONTINUE = frozenset(
    {
        OptimizationAgentStatus.READY,
        OptimizationAgentStatus.WARNING,
        OptimizationAgentStatus.INSUFFICIENT_DATA,
    }
)

def _classify(status, continue_set: frozenset, status_enum_type) -> StageClassification:
    """
    UNKNOWN if `status` is not even a real member of the agent's own
    status enum (a malformed/anomalous return -- e.g. from a
    misbehaving fake agent in a test). SUCCESS if it is a member of the
    stage's small, explicit CONTINUE set. FAILURE for every other real,
    recognized enum member (including each agent's own reserved-but-
    never-actually-returned values, e.g. `StrategyAgentStatus.
    NOT_EVALUATED` -- seeing one for real is a genuine, documented
    failure to classify optimistically, never silently promoted to
    SUCCESS). Neither FAILURE nor UNKNOWN ever allows the pipeline to
    continue (Section 18) -- they are recorded distinctly in
    `StageOutcome` purely for observability.
    """

    if not isinstance(status, status_enum_type):
        return StageClassification.UNKNOWN
    if status in continue_set:
        return StageClassification.SUCCESS
    return StageClassification.FAILURE


# ----------------------------------------------------------------------
# STAGE OUTCOME (Section 31 -- observability)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class StageOutcome:
    stage: str
    agent_name: str
    classification: StageClassification
    raw_status: Optional[str]
    input_artifact_ids: Tuple[str, ...]
    output_artifact_id: Optional[str]
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    errors: Tuple[str, ...] = field(default_factory=tuple)


# ----------------------------------------------------------------------
# MISSION REQUEST (Section 15) -- the caller-supplied, fully explicit
# starting point. Every optional field defaults to "not provided",
# never to a fabricated value.
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class BusinessMissionRequest:
    mission_id: str
    objective: str
    platforms: Tuple[str, ...]
    topic: Optional[str] = None
    audience: Optional[str] = None
    language: Optional[str] = None
    priority: Optional[str] = None
    strategy_constraints: Tuple[str, ...] = field(default_factory=tuple)

    content_language_override: Optional[str] = None
    content_tone: Optional[str] = None
    content_format: Optional[str] = None
    content_platform_override: Optional[Tuple[str, ...]] = None
    content_duration_target_seconds: Optional[int] = None
    content_constraints: Tuple[str, ...] = field(default_factory=tuple)

    quality_profile: Optional[QualityProfile] = None

    publication_profile: Optional[PublicationProfile] = None
    publication_platform_override: Optional[Tuple[str, ...]] = None
    scheduled_at: Optional[str] = None
    timezone: Optional[str] = None

    # Analytics stage is only attempted if BOTH of these are supplied
    # (Section 13 -- never fabricated). `analytics_observations`
    # defaults to empty -- handed to AnalyticsAgent exactly as given.
    analytics_platform: Optional[str] = None
    analytics_period: Optional[AnalyticsPeriod] = None
    analytics_observations: Tuple[AnalyticsObservation, ...] = field(default_factory=tuple)
    analytics_collection_profile: Optional[AnalyticsCollectionProfile] = None

    optimization_profile: Optional[OptimizationProfile] = None


# ----------------------------------------------------------------------
# PIPELINE CONTEXT (Section 15/16) -- an ARTIFACT REGISTRY, never a
# persistence system: in-memory only, never written to `state/`. Frozen
# -- each stage produces a NEW context via `dataclasses.replace()`,
# never an in-place mutation, so no artifact and no prior context is
# ever altered after the fact (Section 21).
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class DirectorPipelineContext:
    mission_id: str
    strategy_artifact: Optional[StrategyArtifact] = None
    content_artifact: Optional[ContentArtifact] = None
    script_artifact: Optional[ScriptArtifact] = None
    quality_artifact: Optional[QualityArtifact] = None
    publication_artifact: Optional[PublicationArtifact] = None
    analytics_artifact: Optional[AnalyticsArtifact] = None
    optimization_artifact: Optional[OptimizationArtifact] = None
    stage_history: Tuple[StageOutcome, ...] = field(default_factory=tuple)
    halted: bool = False
    halted_at_stage: Optional[str] = None
    # P3.12 -- the REAL MissionStateMachine instance for this mission
    # (agents/mission_state_machine.py). The SAME mutable object flows
    # through every `replace()`-produced context (it is itself the
    # append-only authority for state history, Section 15 of P3.12) --
    # `DirectorPipelineContext` never duplicates or re-derives its state.
    state_machine: Optional[MissionStateMachine] = None

    def _append(self, outcome: StageOutcome, **artifact_updates) -> "DirectorPipelineContext":
        return replace(
            self,
            stage_history=self.stage_history + (outcome,),
            **artifact_updates,
        )


# ----------------------------------------------------------------------
# ORCHESTRATOR (Section 3/4/5/6)
# ----------------------------------------------------------------------


class BusinessPipelineOrchestrator:
    """
    AI DIRECTOR — Business Pipeline Orchestrator (P3.11)

    SOLE orchestration authority for the six P3 business agents. Every
    agent is injectable (constructor parameter, defaulting to a real,
    deterministic instance) -- no hidden instantiation, no global
    singleton, no shared mutable state (Section 5/6). Calling `.run()`
    twice with equivalent input and equivalent injected agents produces
    an equivalent logical sequence of artifacts (Section 32) --
    `artifact_id`/`created_at` on each artifact are the only fields that
    legitimately vary, exactly as every agent's own determinism
    guarantee already promises.
    """

    def __init__(
        self,
        strategy_agent: Optional[StrategyAgent] = None,
        content_agent: Optional[ContentAgent] = None,
        quality_agent: Optional[QualityAgent] = None,
        publishing_agent: Optional[PublishingAgent] = None,
        analytics_agent: Optional[AnalyticsAgent] = None,
        optimization_agent: Optional[OptimizationAgent] = None,
        state_machine_factory: Optional[Callable[[str], MissionStateMachine]] = None,
    ):
        self.strategy_agent = strategy_agent or StrategyAgent()
        self.content_agent = content_agent or ContentAgent()
        self.quality_agent = quality_agent or QualityAgent()
        self.publishing_agent = publishing_agent or PublishingAgent()
        self.analytics_agent = analytics_agent or AnalyticsAgent()
        self.optimization_agent = optimization_agent or OptimizationAgent()
        # P3.12 -- injectable so tests can supply a MissionStateMachine
        # built with a deterministic clock, or a pre-seeded state, without
        # this orchestrator ever constructing one with hidden defaults
        # tests cannot control (Section 17).
        self._state_machine_factory = state_machine_factory or (
            lambda mission_id: MissionStateMachine(mission_id=mission_id)
        )

    def run(self, request: BusinessMissionRequest) -> DirectorPipelineContext:
        state_machine = self._state_machine_factory(request.mission_id)
        context = DirectorPipelineContext(mission_id=request.mission_id, state_machine=state_machine)

        context = self._run_strategy(context, request)
        if context.halted:
            return context
        # STATE != AUTHORITY (P3.12 Section 7/8): this transition records
        # ONLY that StrategyAgent produced a real StrategyArtifact -- it
        # never creates, checks, or implies any human/production
        # authority. FAILURE/UNKNOWN classifications never reach here
        # (they set `context.halted = True` and return above) -- per
        # Section 22, the state machine simply stays in its current
        # state rather than a FAILED state that does not exist in the
        # canonical set.
        state_machine.transition(
            MissionState.PLANNED, reason="strategy completed", expected_from=MissionState.IDEA
        )

        context = self._run_content(context, request)
        if context.halted:
            return context
        state_machine.transition(
            MissionState.SCRIPT_READY, reason="content and script completed", expected_from=MissionState.PLANNED
        )

        context = self._run_quality(context, request)
        if context.halted:
            return context
        # The one documented adaptation to real code (module docstring,
        # agents/mission_state_machine.py): QUALITY_CHECK is reached
        # directly from SCRIPT_READY because this pipeline's QualityAgent
        # evaluates content/script quality, never a generated video's
        # quality -- there is no real PROMPT_READY/ASSETS_READY/
        # VIDEO_READY_FOR_REVIEW/TECHNICAL_APPROVAL/HUMAN_AUTHORIZATION/
        # PRODUCTION_AUTHORIZATION/EXECUTION evidence in this pipeline
        # today.
        state_machine.transition(
            MissionState.QUALITY_CHECK, reason="quality evaluation completed", expected_from=MissionState.SCRIPT_READY
        )

        # Publishing's outcome never halts the pipeline (Analytics does
        # not hard-depend on it) -- but it IS recorded faithfully, and
        # `context.publication_artifact` stays None if it did not
        # succeed, passed through as such to later stages.
        #
        # P3.12 Section 23, enforced here by ABSENCE of code, not by
        # convention: no matter what PublishingAgent returns, this
        # orchestrator NEVER calls
        # `state_machine.transition(MissionState.PUBLISHED, ...)` --
        # no real publication authority exists to justify that state,
        # so the mission state machine, driven only by this real
        # integration, provably cannot advance past QUALITY_CHECK
        # (see agents/mission_state_machine.py's module docstring).
        context = self._run_publishing(context, request)

        if request.analytics_platform is None or request.analytics_period is None:
            context = context._append(
                StageOutcome(
                    stage="analytics",
                    agent_name=type(self.analytics_agent).__name__,
                    classification=StageClassification.NOT_ATTEMPTED,
                    raw_status=None,
                    input_artifact_ids=(),
                    output_artifact_id=None,
                )
            )
            context = context._append(
                StageOutcome(
                    stage="optimization",
                    agent_name=type(self.optimization_agent).__name__,
                    classification=StageClassification.NOT_ATTEMPTED,
                    raw_status=None,
                    input_artifact_ids=(),
                    output_artifact_id=None,
                )
            )
            return context

        context = self._run_analytics(context, request)
        if context.halted:
            return context

        context = self._run_optimization(context, request)
        return context

    # ------------------------------------------------------------------
    # STAGE 1 — STRATEGY (Section 9)
    # ------------------------------------------------------------------

    def _run_strategy(self, context: DirectorPipelineContext, request: BusinessMissionRequest) -> DirectorPipelineContext:
        agent_input = StrategyAgentInput(
            mission_id=request.mission_id,
            objective=request.objective,
            platforms=request.platforms,
            topic=request.topic,
            audience=request.audience,
            **({"language": request.language} if request.language is not None else {}),
            **({"priority": request.priority} if request.priority is not None else {}),
            constraints=request.strategy_constraints,
        )
        output = self.strategy_agent.run(agent_input)

        classification = _classify(output.status, STRATEGY_CONTINUE, StrategyAgentStatus)
        outcome = StageOutcome(
            stage="strategy",
            agent_name=type(self.strategy_agent).__name__,
            classification=classification,
            raw_status=getattr(output.status, "value", str(output.status)),
            input_artifact_ids=(),
            output_artifact_id=(output.strategy_artifact.artifact_id if output.strategy_artifact else None),
            warnings=output.warnings,
            errors=output.errors,
        )

        if classification != StageClassification.SUCCESS or output.strategy_artifact is None:
            return context._append(outcome, halted=True, halted_at_stage="strategy")

        return context._append(outcome, strategy_artifact=output.strategy_artifact)

    # ------------------------------------------------------------------
    # STAGE 2 — CONTENT (Section 10)
    # ------------------------------------------------------------------

    def _run_content(self, context: DirectorPipelineContext, request: BusinessMissionRequest) -> DirectorPipelineContext:
        agent_input = ContentAgentInput(
            mission_id=request.mission_id,
            strategy_artifact=context.strategy_artifact,
            language_override=request.content_language_override,
            tone=request.content_tone,
            content_format=request.content_format,
            platform_override=request.content_platform_override,
            duration_target_seconds=request.content_duration_target_seconds,
            constraints=request.content_constraints,
        )
        output = self.content_agent.run(agent_input)

        classification = _classify(output.status, CONTENT_CONTINUE, ContentAgentStatus)
        outcome = StageOutcome(
            stage="content",
            agent_name=type(self.content_agent).__name__,
            classification=classification,
            raw_status=getattr(output.status, "value", str(output.status)),
            input_artifact_ids=(context.strategy_artifact.artifact_id,),
            output_artifact_id=(output.content_artifact.artifact_id if output.content_artifact else None),
            warnings=output.warnings,
            errors=output.errors,
        )

        if classification != StageClassification.SUCCESS or output.content_artifact is None or output.script_artifact is None:
            return context._append(outcome, halted=True, halted_at_stage="content")

        return context._append(
            outcome, content_artifact=output.content_artifact, script_artifact=output.script_artifact
        )

    # ------------------------------------------------------------------
    # STAGE 3 — QUALITY (Section 11)
    # ------------------------------------------------------------------

    def _run_quality(self, context: DirectorPipelineContext, request: BusinessMissionRequest) -> DirectorPipelineContext:
        agent_input = QualityAgentInput(
            mission_id=request.mission_id,
            content_artifact=context.content_artifact,
            script_artifact=context.script_artifact,
            quality_profile=request.quality_profile,
        )
        output = self.quality_agent.run(agent_input)

        classification = _classify(output.status, QUALITY_CONTINUE, QualityAgentStatus)
        outcome = StageOutcome(
            stage="quality",
            agent_name=type(self.quality_agent).__name__,
            classification=classification,
            raw_status=getattr(output.status, "value", str(output.status)),
            input_artifact_ids=(context.content_artifact.artifact_id, context.script_artifact.artifact_id),
            output_artifact_id=(output.quality_artifact.artifact_id if output.quality_artifact else None),
            warnings=output.warnings,
            errors=output.errors,
        )

        if classification != StageClassification.SUCCESS or output.quality_artifact is None:
            return context._append(outcome, halted=True, halted_at_stage="quality")

        return context._append(outcome, quality_artifact=output.quality_artifact)

    # ------------------------------------------------------------------
    # STAGE 4 — PUBLISHING PREPARATION (Section 12) — PREPARATION ONLY.
    # Does not halt the pipeline: Analytics does not hard-depend on it.
    # ------------------------------------------------------------------

    def _run_publishing(self, context: DirectorPipelineContext, request: BusinessMissionRequest) -> DirectorPipelineContext:
        agent_input = PublishingAgentInput(
            mission_id=request.mission_id,
            content_artifact=context.content_artifact,
            script_artifact=context.script_artifact,
            quality_artifact=context.quality_artifact,
            publication_profile=request.publication_profile,
            platform_override=request.publication_platform_override,
            scheduled_at=request.scheduled_at,
            timezone=request.timezone,
        )
        output = self.publishing_agent.run(agent_input)

        classification = _classify(output.status, PUBLISHING_CONTINUE, PublishingAgentStatus)
        outcome = StageOutcome(
            stage="publishing_preparation",
            agent_name=type(self.publishing_agent).__name__,
            classification=classification,
            raw_status=getattr(output.status, "value", str(output.status)),
            input_artifact_ids=(
                context.content_artifact.artifact_id,
                context.script_artifact.artifact_id,
                context.quality_artifact.artifact_id,
            ),
            output_artifact_id=(output.publication_artifact.artifact_id if output.publication_artifact else None),
            warnings=output.warnings,
            errors=output.errors,
        )

        publication_artifact = output.publication_artifact if classification == StageClassification.SUCCESS else None
        return context._append(outcome, publication_artifact=publication_artifact)

    # ------------------------------------------------------------------
    # STAGE 5 — ANALYTICS (Section 13) — only reached if the caller
    # supplied `analytics_platform`/`analytics_period` (checked by
    # `.run()` before calling this method).
    # ------------------------------------------------------------------

    def _run_analytics(self, context: DirectorPipelineContext, request: BusinessMissionRequest) -> DirectorPipelineContext:
        agent_input = AnalyticsAgentInput(
            mission_id=request.mission_id,
            platform=request.analytics_platform,
            period=request.analytics_period,
            observations=request.analytics_observations,
            content_artifact=context.content_artifact,
            quality_artifact=context.quality_artifact,
            publication_artifact=context.publication_artifact,
            collection_profile=request.analytics_collection_profile,
        )
        output = self.analytics_agent.run(agent_input)

        classification = _classify(output.status, ANALYTICS_CONTINUE, AnalyticsAgentStatus)
        input_ids = tuple(
            artifact.artifact_id
            for artifact in (context.content_artifact, context.quality_artifact, context.publication_artifact)
            if artifact is not None
        )
        outcome = StageOutcome(
            stage="analytics",
            agent_name=type(self.analytics_agent).__name__,
            classification=classification,
            raw_status=getattr(output.status, "value", str(output.status)),
            input_artifact_ids=input_ids,
            output_artifact_id=(output.analytics_artifact.artifact_id if output.analytics_artifact else None),
            warnings=output.warnings,
            errors=output.errors,
        )

        if classification != StageClassification.SUCCESS or output.analytics_artifact is None:
            return context._append(outcome, halted=True, halted_at_stage="analytics")

        return context._append(outcome, analytics_artifact=output.analytics_artifact)

    # ------------------------------------------------------------------
    # STAGE 6 — OPTIMIZATION (Section 14) — recommendations only, always
    # PROPOSED, never applied.
    # ------------------------------------------------------------------

    def _run_optimization(self, context: DirectorPipelineContext, request: BusinessMissionRequest) -> DirectorPipelineContext:
        agent_input = OptimizationAgentInput(
            mission_id=request.mission_id,
            analytics_artifact=context.analytics_artifact,
            quality_artifact=context.quality_artifact,
            content_artifact=context.content_artifact,
            publication_artifact=context.publication_artifact,
            optimization_profile=request.optimization_profile,
        )
        output = self.optimization_agent.run(agent_input)

        classification = _classify(output.status, OPTIMIZATION_CONTINUE, OptimizationAgentStatus)
        input_ids = tuple(
            artifact.artifact_id
            for artifact in (context.analytics_artifact, context.content_artifact, context.quality_artifact, context.publication_artifact)
            if artifact is not None
        )
        outcome = StageOutcome(
            stage="optimization",
            agent_name=type(self.optimization_agent).__name__,
            classification=classification,
            raw_status=getattr(output.status, "value", str(output.status)),
            input_artifact_ids=input_ids,
            output_artifact_id=(output.optimization_artifact.artifact_id if output.optimization_artifact else None),
            warnings=output.warnings,
            errors=output.errors,
        )

        halted = classification != StageClassification.SUCCESS or output.optimization_artifact is None
        return context._append(
            outcome,
            optimization_artifact=output.optimization_artifact,
            halted=halted,
            halted_at_stage=("optimization" if halted else context.halted_at_stage),
        )
