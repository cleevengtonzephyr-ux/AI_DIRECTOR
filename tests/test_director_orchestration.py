"""
Tests — Business Pipeline Orchestration (Phase P3.11).

Fully offline: no network, no Higgsfield, no social platform, no OAuth,
no credential of any kind is imported or constructed anywhere in this
file. Covers `agents/director_pipeline.py` and the new
`AIDirector.run_business_pipeline()` entry point in `director.py`.
"""

import ast
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.analytics_agent import (
    AnalyticsAgentOutput,
    AnalyticsAgentStatus,
    AnalyticsObservation,
    AnalyticsSourceTrust,
)
from agents.content_agent import ContentAgentOutput, ContentAgentStatus
from agents.director_pipeline import (
    BusinessMissionRequest,
    BusinessPipelineOrchestrator,
    DirectorPipelineContext,
    StageClassification,
)
from agents.mission_state_machine import MissionState, MissionStateMachine
from agents.optimization_agent import AnalyticsPeriod, OptimizationAgentOutput, OptimizationAgentStatus
from agents.publishing_agent import PublishingAgentOutput, PublishingAgentStatus
from agents.quality_agent import QualityAgentOutput, QualityAgentStatus
from agents.strategy_agent import StrategyAgentOutput, StrategyAgentStatus
from director import AIDirector

DIRECTOR_PIPELINE_SOURCE_PATH = PROJECT_ROOT / "agents" / "director_pipeline.py"

AGENT_SOURCE_PATHS = {
    "strategy_agent": PROJECT_ROOT / "agents" / "strategy_agent.py",
    "content_agent": PROJECT_ROOT / "agents" / "content_agent.py",
    "quality_agent": PROJECT_ROOT / "agents" / "quality_agent.py",
    "publishing_agent": PROJECT_ROOT / "agents" / "publishing_agent.py",
    "analytics_agent": PROJECT_ROOT / "agents" / "analytics_agent.py",
    "optimization_agent": PROJECT_ROOT / "agents" / "optimization_agent.py",
}
AGENT_CLASS_NAMES = {
    "StrategyAgent",
    "ContentAgent",
    "QualityAgent",
    "PublishingAgent",
    "AnalyticsAgent",
    "OptimizationAgent",
}


# ----------------------------------------------------------------------
# FAKE AGENTS (Section 33) -- controlled, offline, never call a real
# provider. Each records the input it received and returns a
# pre-configured output.
# ----------------------------------------------------------------------


class _RecordingFakeAgent:
    def __init__(self, output):
        self._output = output
        self.calls = []

    def run(self, agent_input):
        self.calls.append(agent_input)
        return self._output


def _valid_request(**overrides):
    defaults = dict(
        mission_id="mission-001",
        objective="Explain why discipline beats talent over time.",
        platforms=("tiktok", "youtube"),
        topic="discipline vs talent",
        audience="young adults pursuing self-improvement",
    )
    defaults.update(overrides)
    return BusinessMissionRequest(**defaults)


def _analytics_request(**overrides):
    defaults = dict(
        analytics_platform="tiktok",
        analytics_period=AnalyticsPeriod(start="2026-01-01T00:00:00", end="2026-01-07T00:00:00", timezone="UTC"),
        analytics_observations=(
            AnalyticsObservation(
                metric="views", value=500.0, unit="count", platform="tiktok",
                source=AnalyticsSourceTrust.EXPLICIT_INPUT.value, source_reference="manual-1",
            ),
        ),
    )
    defaults.update(overrides)
    return _valid_request(**defaults)


class OrchestrationHappyPathTests(unittest.TestCase):
    """Tests 1, 8-11 from the P3.11 mandatory list."""

    def test_valid_mission_runs_full_pipeline(self):
        context = BusinessPipelineOrchestrator().run(_analytics_request())
        self.assertFalse(context.halted)
        self.assertIsNotNone(context.strategy_artifact)
        self.assertIsNotNone(context.content_artifact)
        self.assertIsNotNone(context.script_artifact)
        self.assertIsNotNone(context.quality_artifact)
        self.assertIsNotNone(context.publication_artifact)
        self.assertIsNotNone(context.analytics_artifact)
        self.assertIsNotNone(context.optimization_artifact)

    def test_artifact_propagation(self):
        context = BusinessPipelineOrchestrator().run(_analytics_request())
        self.assertEqual(context.content_artifact.source_strategy_artifact_id, context.strategy_artifact.artifact_id)
        self.assertEqual(context.script_artifact.source_content_artifact_id, context.content_artifact.artifact_id)
        self.assertTrue(
            any(ref.artifact_id == context.content_artifact.artifact_id for ref in context.quality_artifact.evaluated_artifacts)
        )

    def test_mission_id_propagation(self):
        context = BusinessPipelineOrchestrator().run(_analytics_request(mission_id="mission-xyz"))
        self.assertEqual(context.mission_id, "mission-xyz")
        self.assertEqual(context.strategy_artifact.mission_id, "mission-xyz")
        self.assertEqual(context.content_artifact.mission_id, "mission-xyz")
        self.assertEqual(context.quality_artifact.mission_id, "mission-xyz")
        self.assertEqual(context.publication_artifact.mission_id, "mission-xyz")
        self.assertEqual(context.analytics_artifact.mission_id, "mission-xyz")
        self.assertEqual(context.optimization_artifact.mission_id, "mission-xyz")

    def test_correct_stage_ordering(self):
        context = BusinessPipelineOrchestrator().run(_analytics_request())
        self.assertEqual(
            [outcome.stage for outcome in context.stage_history],
            ["strategy", "content", "quality", "publishing_preparation", "analytics", "optimization"],
        )

    def test_deterministic_orchestration(self):
        orchestrator = BusinessPipelineOrchestrator()
        request = _analytics_request()
        first = orchestrator.run(request)
        second = orchestrator.run(request)
        self.assertEqual(first.strategy_artifact.content_hash, second.strategy_artifact.content_hash)
        self.assertEqual(first.content_artifact.content_hash, second.content_artifact.content_hash)
        # QualityArtifact.content_hash intentionally binds to upstream
        # EvaluatedArtifactReference.artifact_id (P3.7 Section 16
        # traceability -- "which exact instance was evaluated"), so it
        # is NOT expected to match bit-for-bit across two independently
        # regenerated pipeline runs (each mints fresh upstream
        # artifact_ids) even though the LOGICAL evaluation outcome is
        # identical -- a real architectural finding surfaced by this
        # integration test, documented in the P3.11 report's
        # Determinism/Risks sections. Verified via logical fields instead.
        self.assertEqual(first.quality_artifact.quality_status, second.quality_artifact.quality_status)
        self.assertEqual(first.quality_artifact.score, second.quality_artifact.score)
        self.assertEqual(
            [(f.code, f.severity) for f in first.quality_artifact.findings],
            [(f.code, f.severity) for f in second.quality_artifact.findings],
        )
        self.assertEqual(first.analytics_artifact.content_hash, second.analytics_artifact.content_hash)
        self.assertEqual(
            [o.classification for o in first.stage_history], [o.classification for o in second.stage_history]
        )


class OrchestrationInputPropagationTests(unittest.TestCase):
    """Tests 2-7 from the P3.11 mandatory list."""

    def test_strategy_called(self):
        fake_strategy = _RecordingFakeAgent(
            StrategyAgentOutput(mission_id="mission-001", status=StrategyAgentStatus.VALIDATION_ERROR, errors=("stop",))
        )
        orchestrator = BusinessPipelineOrchestrator(strategy_agent=fake_strategy)
        orchestrator.run(_valid_request())
        self.assertEqual(len(fake_strategy.calls), 1)
        self.assertEqual(fake_strategy.calls[0].mission_id, "mission-001")

    def test_content_receives_strategy_artifact(self):
        real_context_probe = BusinessPipelineOrchestrator().run(_valid_request())
        strategy_artifact = real_context_probe.strategy_artifact

        fake_strategy = _RecordingFakeAgent(
            StrategyAgentOutput(mission_id="mission-001", status=StrategyAgentStatus.READY, strategy_artifact=strategy_artifact)
        )
        fake_content = _RecordingFakeAgent(
            ContentAgentOutput(mission_id="mission-001", status=ContentAgentStatus.VALIDATION_ERROR, errors=("stop",))
        )
        orchestrator = BusinessPipelineOrchestrator(strategy_agent=fake_strategy, content_agent=fake_content)
        orchestrator.run(_valid_request())

        self.assertEqual(len(fake_content.calls), 1)
        self.assertIs(fake_content.calls[0].strategy_artifact, strategy_artifact)

    def test_quality_receives_content_and_script_artifacts(self):
        context = BusinessPipelineOrchestrator().run(_valid_request())
        content_artifact, script_artifact = context.content_artifact, context.script_artifact

        fake_content = _RecordingFakeAgent(
            ContentAgentOutput(mission_id="mission-001", status=ContentAgentStatus.READY, content_artifact=content_artifact, script_artifact=script_artifact)
        )
        fake_quality = _RecordingFakeAgent(
            QualityAgentOutput(mission_id="mission-001", status=QualityAgentStatus.VALIDATION_ERROR, errors=("stop",))
        )
        orchestrator = BusinessPipelineOrchestrator(content_agent=fake_content, quality_agent=fake_quality)
        orchestrator.run(_valid_request())

        self.assertEqual(len(fake_quality.calls), 1)
        self.assertIs(fake_quality.calls[0].content_artifact, content_artifact)
        self.assertIs(fake_quality.calls[0].script_artifact, script_artifact)

    def test_publishing_receives_quality_artifact(self):
        context = BusinessPipelineOrchestrator().run(_valid_request())
        quality_artifact = context.quality_artifact

        fake_quality = _RecordingFakeAgent(
            QualityAgentOutput(
                mission_id="mission-001", status=QualityAgentStatus.PASS,
                quality_artifact=quality_artifact,
            )
        )
        fake_publishing = _RecordingFakeAgent(
            PublishingAgentOutput(mission_id="mission-001", status=PublishingAgentStatus.VALIDATION_ERROR, errors=("stop",))
        )
        orchestrator = BusinessPipelineOrchestrator(quality_agent=fake_quality, publishing_agent=fake_publishing)
        orchestrator.run(_valid_request())

        self.assertEqual(len(fake_publishing.calls), 1)
        self.assertIs(fake_publishing.calls[0].quality_artifact, quality_artifact)

    def test_analytics_receives_explicit_analytics_input(self):
        request = _analytics_request()
        fake_analytics = _RecordingFakeAgent(
            AnalyticsAgentOutput(mission_id="mission-001", status=AnalyticsAgentStatus.VALIDATION_ERROR, errors=("stop",))
        )
        orchestrator = BusinessPipelineOrchestrator(analytics_agent=fake_analytics)
        orchestrator.run(request)

        self.assertEqual(len(fake_analytics.calls), 1)
        self.assertEqual(fake_analytics.calls[0].platform, "tiktok")
        self.assertEqual(fake_analytics.calls[0].observations, request.analytics_observations)

    def test_optimization_receives_analytics_artifact(self):
        context = BusinessPipelineOrchestrator().run(_analytics_request())
        analytics_artifact = context.analytics_artifact

        fake_analytics = _RecordingFakeAgent(
            AnalyticsAgentOutput(mission_id="mission-001", status=AnalyticsAgentStatus.COLLECTED, analytics_artifact=analytics_artifact)
        )
        fake_optimization = _RecordingFakeAgent(
            OptimizationAgentOutput(mission_id="mission-001", status=OptimizationAgentStatus.VALIDATION_ERROR, errors=("stop",))
        )
        orchestrator = BusinessPipelineOrchestrator(analytics_agent=fake_analytics, optimization_agent=fake_optimization)
        orchestrator.run(_analytics_request())

        self.assertEqual(len(fake_optimization.calls), 1)
        self.assertIs(fake_optimization.calls[0].analytics_artifact, analytics_artifact)


class OrchestrationFailureHandlingTests(unittest.TestCase):
    """Tests 12-18 from the P3.11 mandatory list."""

    def test_strategy_failure_halts_before_content(self):
        fake_strategy = _RecordingFakeAgent(
            StrategyAgentOutput(mission_id="mission-001", status=StrategyAgentStatus.VALIDATION_ERROR, errors=("bad input",))
        )
        fake_content = _RecordingFakeAgent(None)
        orchestrator = BusinessPipelineOrchestrator(strategy_agent=fake_strategy, content_agent=fake_content)
        context = orchestrator.run(_valid_request())

        self.assertTrue(context.halted)
        self.assertEqual(context.halted_at_stage, "strategy")
        self.assertEqual(len(fake_content.calls), 0)

    def test_content_failure_halts_before_quality(self):
        fake_content = _RecordingFakeAgent(
            ContentAgentOutput(mission_id="mission-001", status=ContentAgentStatus.REJECTED, errors=("bad strategy",))
        )
        fake_quality = _RecordingFakeAgent(None)
        orchestrator = BusinessPipelineOrchestrator(content_agent=fake_content, quality_agent=fake_quality)
        context = orchestrator.run(_valid_request())

        self.assertTrue(context.halted)
        self.assertEqual(context.halted_at_stage, "content")
        self.assertEqual(len(fake_quality.calls), 0)

    def test_quality_failure_halts_before_publishing(self):
        fake_quality = _RecordingFakeAgent(
            QualityAgentOutput(mission_id="mission-001", status=QualityAgentStatus.FAIL)
        )
        fake_publishing = _RecordingFakeAgent(None)
        orchestrator = BusinessPipelineOrchestrator(quality_agent=fake_quality, publishing_agent=fake_publishing)
        context = orchestrator.run(_valid_request())

        self.assertTrue(context.halted)
        self.assertEqual(context.halted_at_stage, "quality")
        self.assertEqual(len(fake_publishing.calls), 0)

    def test_publishing_preparation_failure_does_not_halt(self):
        fake_publishing = _RecordingFakeAgent(
            PublishingAgentOutput(mission_id="mission-001", status=PublishingAgentStatus.QUALITY_REJECTED, errors=("rejected",))
        )
        fake_analytics = _RecordingFakeAgent(
            AnalyticsAgentOutput(mission_id="mission-001", status=AnalyticsAgentStatus.REJECTED, errors=("stop",))
        )
        orchestrator = BusinessPipelineOrchestrator(publishing_agent=fake_publishing, analytics_agent=fake_analytics)
        context = orchestrator.run(_analytics_request())

        self.assertIsNone(context.publication_artifact)
        # Pipeline did NOT halt at publishing -- analytics was still attempted.
        self.assertEqual(len(fake_analytics.calls), 1)
        publishing_outcome = next(o for o in context.stage_history if o.stage == "publishing_preparation")
        self.assertEqual(publishing_outcome.classification, StageClassification.FAILURE)

    def test_analytics_failure_halts_before_optimization(self):
        fake_analytics = _RecordingFakeAgent(
            AnalyticsAgentOutput(mission_id="mission-001", status=AnalyticsAgentStatus.VALIDATION_ERROR, errors=("bad period",))
        )
        fake_optimization = _RecordingFakeAgent(None)
        orchestrator = BusinessPipelineOrchestrator(analytics_agent=fake_analytics, optimization_agent=fake_optimization)
        context = orchestrator.run(_analytics_request())

        self.assertTrue(context.halted)
        self.assertEqual(context.halted_at_stage, "analytics")
        self.assertEqual(len(fake_optimization.calls), 0)

    def test_optimization_failure_is_recorded(self):
        fake_optimization = _RecordingFakeAgent(
            OptimizationAgentOutput(mission_id="mission-001", status=OptimizationAgentStatus.REJECTED, errors=("bad analytics",))
        )
        orchestrator = BusinessPipelineOrchestrator(optimization_agent=fake_optimization)
        context = orchestrator.run(_analytics_request())

        self.assertTrue(context.halted)
        self.assertEqual(context.halted_at_stage, "optimization")

    def test_unknown_state_preservation(self):
        class _WeirdStatus:
            value = "TOTALLY_UNRECOGNIZED"

        fake_quality = _RecordingFakeAgent(
            QualityAgentOutput(mission_id="mission-001", status=_WeirdStatus())  # type: ignore
        )
        fake_publishing = _RecordingFakeAgent(None)
        orchestrator = BusinessPipelineOrchestrator(quality_agent=fake_quality, publishing_agent=fake_publishing)
        context = orchestrator.run(_valid_request())

        quality_outcome = next(o for o in context.stage_history if o.stage == "quality")
        self.assertEqual(quality_outcome.classification, StageClassification.UNKNOWN)
        self.assertTrue(context.halted)
        # Never continued "as if all is well".
        self.assertEqual(len(fake_publishing.calls), 0)


class OrchestrationAnalyticsFabricationTests(unittest.TestCase):
    """Test 19 from the P3.11 mandatory list."""

    def test_no_fabricated_analytics_when_not_supplied(self):
        fake_analytics = _RecordingFakeAgent(None)
        fake_optimization = _RecordingFakeAgent(None)
        orchestrator = BusinessPipelineOrchestrator(analytics_agent=fake_analytics, optimization_agent=fake_optimization)
        context = orchestrator.run(_valid_request())  # no analytics_platform/period supplied

        self.assertEqual(len(fake_analytics.calls), 0)
        self.assertEqual(len(fake_optimization.calls), 0)
        analytics_outcome = next(o for o in context.stage_history if o.stage == "analytics")
        optimization_outcome = next(o for o in context.stage_history if o.stage == "optimization")
        self.assertEqual(analytics_outcome.classification, StageClassification.NOT_ATTEMPTED)
        self.assertEqual(optimization_outcome.classification, StageClassification.NOT_ATTEMPTED)


class OrchestrationImmutabilityTests(unittest.TestCase):
    """Test 20 from the P3.11 mandatory list."""

    def test_immutable_artifacts_across_pipeline(self):
        from dataclasses import replace as dc_replace

        context = BusinessPipelineOrchestrator().run(_analytics_request())
        strategy_before = dc_replace(context.strategy_artifact)
        content_before = dc_replace(context.content_artifact)

        # Re-running a DIFFERENT mission must never affect the first context's artifacts.
        BusinessPipelineOrchestrator().run(_analytics_request(mission_id="mission-002"))

        self.assertEqual(context.strategy_artifact, strategy_before)
        self.assertEqual(context.content_artifact, content_before)


class OrchestrationTestDoubleTests(unittest.TestCase):
    """Tests 21-23 from the P3.11 mandatory list."""

    def test_fake_agents_full_pipeline(self):
        strategy_out = StrategyAgentOutput(mission_id="mission-001", status=StrategyAgentStatus.VALIDATION_ERROR, errors=("x",))
        fakes = {
            "strategy_agent": _RecordingFakeAgent(strategy_out),
            "content_agent": _RecordingFakeAgent(None),
            "quality_agent": _RecordingFakeAgent(None),
            "publishing_agent": _RecordingFakeAgent(None),
            "analytics_agent": _RecordingFakeAgent(None),
            "optimization_agent": _RecordingFakeAgent(None),
        }
        orchestrator = BusinessPipelineOrchestrator(**fakes)
        context = orchestrator.run(_valid_request())
        self.assertTrue(context.halted)
        self.assertEqual(context.halted_at_stage, "strategy")

    def test_dependency_injection(self):
        fake_strategy = _RecordingFakeAgent(
            StrategyAgentOutput(mission_id="mission-001", status=StrategyAgentStatus.VALIDATION_ERROR, errors=("x",))
        )
        orchestrator = BusinessPipelineOrchestrator(strategy_agent=fake_strategy)
        self.assertIs(orchestrator.strategy_agent, fake_strategy)
        orchestrator.run(_valid_request())
        self.assertEqual(len(fake_strategy.calls), 1)

    def test_no_global_state_between_runs(self):
        orchestrator = BusinessPipelineOrchestrator()
        context_a = orchestrator.run(_analytics_request(mission_id="mission-A"))
        context_b = orchestrator.run(_analytics_request(mission_id="mission-B"))
        self.assertEqual(context_a.mission_id, "mission-A")
        self.assertEqual(context_b.mission_id, "mission-B")
        self.assertNotEqual(context_a.strategy_artifact.artifact_id, context_b.strategy_artifact.artifact_id)


class OrchestrationOptimizationSafetyTests(unittest.TestCase):
    """Test 32 from the P3.11 mandatory list."""

    def test_no_automatic_optimization_application(self):
        from agents.optimization_agent import OptimizationRecommendationStatus

        context = BusinessPipelineOrchestrator().run(_analytics_request())
        for recommendation in context.optimization_artifact.recommendations:
            self.assertEqual(recommendation.status, OptimizationRecommendationStatus.PROPOSED)


class OrchestrationStateMachineTests(unittest.TestCase):
    """
    P3.12 integration tests -- the REAL `MissionStateMachine`
    (agents/mission_state_machine.py) driven by `BusinessPipelineOrchestrator.
    run()`. Only exercises transitions actually justified by real
    artifacts produced during this pipeline run (P3.12 Section 29):
    IDEA -> PLANNED -> SCRIPT_READY -> QUALITY_CHECK. Never PUBLISHED
    (P3.12 Section 23 -- no real publication authority exists on this
    path).
    """

    def test_context_carries_a_real_state_machine(self):
        context = BusinessPipelineOrchestrator().run(_valid_request())
        self.assertIsInstance(context.state_machine, MissionStateMachine)

    def test_successful_progression_reaches_quality_check(self):
        context = BusinessPipelineOrchestrator().run(_analytics_request())
        self.assertFalse(context.halted)
        self.assertEqual(context.state_machine.current_state, MissionState.QUALITY_CHECK)

    def test_state_history_matches_real_stage_progression(self):
        context = BusinessPipelineOrchestrator().run(_analytics_request())
        self.assertEqual(
            [t.to_state for t in context.state_machine.history],
            [MissionState.PLANNED, MissionState.SCRIPT_READY, MissionState.QUALITY_CHECK],
        )
        self.assertEqual(context.state_machine.transition_count, 3)

    def test_mission_id_propagated_into_state_machine(self):
        context = BusinessPipelineOrchestrator().run(_analytics_request(mission_id="mission-xyz"))
        self.assertEqual(context.state_machine.mission_id, "mission-xyz")
        for record in context.state_machine.history:
            self.assertEqual(record.mission_id, "mission-xyz")

    def test_strategy_failure_leaves_state_machine_at_idea(self):
        fake_strategy = _RecordingFakeAgent(
            StrategyAgentOutput(mission_id="mission-001", status=StrategyAgentStatus.VALIDATION_ERROR, errors=("bad input",))
        )
        orchestrator = BusinessPipelineOrchestrator(strategy_agent=fake_strategy)
        context = orchestrator.run(_valid_request())

        self.assertTrue(context.halted)
        self.assertEqual(context.state_machine.current_state, MissionState.IDEA)
        self.assertEqual(context.state_machine.transition_count, 0)

    def test_content_failure_leaves_state_machine_at_planned(self):
        fake_content = _RecordingFakeAgent(
            ContentAgentOutput(mission_id="mission-001", status=ContentAgentStatus.REJECTED, errors=("bad strategy",))
        )
        orchestrator = BusinessPipelineOrchestrator(content_agent=fake_content)
        context = orchestrator.run(_valid_request())

        self.assertTrue(context.halted)
        self.assertEqual(context.state_machine.current_state, MissionState.PLANNED)
        self.assertEqual([t.to_state for t in context.state_machine.history], [MissionState.PLANNED])

    def test_quality_failure_leaves_state_machine_at_script_ready(self):
        fake_quality = _RecordingFakeAgent(
            QualityAgentOutput(mission_id="mission-001", status=QualityAgentStatus.FAIL)
        )
        orchestrator = BusinessPipelineOrchestrator(quality_agent=fake_quality)
        context = orchestrator.run(_valid_request())

        self.assertTrue(context.halted)
        self.assertEqual(context.state_machine.current_state, MissionState.SCRIPT_READY)
        self.assertEqual(
            [t.to_state for t in context.state_machine.history],
            [MissionState.PLANNED, MissionState.SCRIPT_READY],
        )

    def test_unknown_quality_classification_leaves_state_machine_unchanged(self):
        class _WeirdStatus:
            value = "TOTALLY_UNRECOGNIZED"

        fake_quality = _RecordingFakeAgent(
            QualityAgentOutput(mission_id="mission-001", status=_WeirdStatus())  # type: ignore
        )
        orchestrator = BusinessPipelineOrchestrator(quality_agent=fake_quality)
        context = orchestrator.run(_valid_request())

        self.assertTrue(context.halted)
        # No FAILED/UNKNOWN state invented -- machine simply stays where
        # real evidence last put it (P3.12 Section 22).
        self.assertEqual(context.state_machine.current_state, MissionState.SCRIPT_READY)

    def test_publishing_preparation_never_transitions_state_machine(self):
        # P3.12 Section 23: no real publication authority exists on this
        # path -- the state machine must never reach PUBLISHED, even
        # when PublishingAgent itself reports success and even when
        # every later stage (Analytics/Optimization) also succeeds.
        context = BusinessPipelineOrchestrator().run(_analytics_request())
        self.assertIsNotNone(context.publication_artifact)
        self.assertIsNotNone(context.optimization_artifact)
        self.assertEqual(context.state_machine.current_state, MissionState.QUALITY_CHECK)
        self.assertNotIn(MissionState.PUBLISHED, [t.to_state for t in context.state_machine.history])

    def test_state_machine_history_is_immutable(self):
        context = BusinessPipelineOrchestrator().run(_valid_request())
        history = context.state_machine.history
        self.assertIsInstance(history, tuple)
        with self.assertRaises(AttributeError):
            history.append(MissionState.SCRIPT_READY)

    def test_two_runs_never_share_a_state_machine(self):
        orchestrator = BusinessPipelineOrchestrator()
        context_a = orchestrator.run(_analytics_request(mission_id="mission-A"))
        context_b = orchestrator.run(_analytics_request(mission_id="mission-B"))
        self.assertIsNot(context_a.state_machine, context_b.state_machine)
        self.assertEqual(context_a.state_machine.mission_id, "mission-A")
        self.assertEqual(context_b.state_machine.mission_id, "mission-B")

    def test_injected_state_machine_factory_is_used(self):
        ticks = iter(["t1", "t2", "t3"])
        built = {}

        def factory(mission_id):
            machine = MissionStateMachine(mission_id=mission_id, clock=lambda: next(ticks))
            built["machine"] = machine
            return machine

        orchestrator = BusinessPipelineOrchestrator(state_machine_factory=factory)
        context = orchestrator.run(_valid_request())

        self.assertIs(context.state_machine, built["machine"])
        self.assertEqual(context.state_machine.history[0].timestamp, "t1")

    def test_state_conflict_detected_on_stale_expected_from(self):
        from agents.mission_state_machine import StateConflictError

        machine = MissionStateMachine(mission_id="mission-001")
        machine.transition(MissionState.PLANNED, reason="external", expected_from=MissionState.IDEA)
        with self.assertRaises(StateConflictError):
            machine.transition(MissionState.SCRIPT_READY, reason="stale caller", expected_from=MissionState.IDEA)


class OrchestrationBoundaryTests(unittest.TestCase):
    """Tests 33, 35-36 from the P3.11 mandatory list."""

    def test_no_mission_mutation_by_agents(self):
        # No agent module imports another agent's CLASS (only artifact
        # types/hash functions) -- confirmed structurally: agents cannot
        # call one another because they never even reference each
        # other's class.
        for name, path in AGENT_SOURCE_PATHS.items():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported_names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        imported_names.add(alias.asname or alias.name)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        imported_names.add(alias.asname or alias.name)
            own_class_name = "".join(part.capitalize() for part in name.split("_"))
            other_agent_classes = AGENT_CLASS_NAMES - {own_class_name}
            offenders = imported_names & other_agent_classes
            self.assertFalse(offenders, f"{name}.py imports another agent's class: {offenders}")

    def test_agents_never_call_state_machine_transition(self):
        # P3.12 Section 14/30: agents return outputs only -- ONLY
        # BusinessPipelineOrchestrator may call
        # MissionStateMachine.transition()/can_transition(). Checked
        # structurally: no business agent even imports
        # agents.mission_state_machine, so it cannot call either method.
        for name, path in AGENT_SOURCE_PATHS.items():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported_modules = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    imported_modules.add(node.module)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        imported_modules.add(alias.name)
            self.assertNotIn(
                "agents.mission_state_machine", imported_modules,
                f"{name}.py must never import agents.mission_state_machine",
            )
            called_attrs = {
                node.func.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            }
            self.assertNotIn("transition", called_attrs, f"{name}.py must never call .transition()")

    def test_agents_do_not_call_each_other(self):
        # Same guarantee, restated via the orchestrator's own exclusivity:
        # BusinessPipelineOrchestrator is the only caller of every
        # agent's `.run()` among the source files in this repository's
        # agents/ package (re-uses the class-import check above, which
        # is the stronger, sufficient guarantee: an agent cannot call
        # `.run()` on a class it has not even imported).
        self.test_no_mission_mutation_by_agents()

    def test_p2_generation_boundary_preserved(self):
        source = DIRECTOR_PIPELINE_SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)

        docstring_nodes = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if (
                    node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)
                ):
                    docstring_nodes.add(id(node.body[0].value))

        texts = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                texts.append(node.id)
            elif isinstance(node, ast.Attribute):
                texts.append(node.attr)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                texts.append(node.name)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) not in docstring_nodes:
                    texts.append(node.value)

        for forbidden in ("GenerationApprovalGate", "GenerationJobService", "HiggsfieldProvider", "HiggsfieldClient"):
            self.assertNotIn(forbidden, texts, f"'{forbidden}' found as a real (non-docstring) identifier/literal")


class DirectorIntegrationTests(unittest.TestCase):
    """Test 34 from the P3.11 mandatory list -- Director owns orchestration."""

    def test_director_exposes_run_business_pipeline(self):
        director = AIDirector()
        self.assertTrue(hasattr(director, "run_business_pipeline"))

    def test_director_delegates_to_injected_orchestrator(self):
        fake_strategy = _RecordingFakeAgent(
            StrategyAgentOutput(mission_id="mission-001", status=StrategyAgentStatus.VALIDATION_ERROR, errors=("x",))
        )
        orchestrator = BusinessPipelineOrchestrator(strategy_agent=fake_strategy)
        director = AIDirector()
        context = director.run_business_pipeline(_valid_request(), orchestrator=orchestrator)
        self.assertIsInstance(context, DirectorPipelineContext)
        self.assertEqual(len(fake_strategy.calls), 1)

    def test_director_default_orchestrator_uses_real_agents(self):
        director = AIDirector()
        context = director.run_business_pipeline(_analytics_request())
        self.assertFalse(context.halted)
        self.assertIsNotNone(context.optimization_artifact)

    def test_existing_p2_methods_unaffected(self):
        director = AIDirector()
        self.assertTrue(hasattr(director, "run_video_mission"))
        self.assertTrue(hasattr(director, "check_higgsfield"))
        self.assertEqual(director.version, "0.2.0")


class OrchestrationSecurityTests(unittest.TestCase):
    """
    Tests 24-31 from the P3.11 mandatory list: static (AST) verification
    that agents/director_pipeline.py cannot reach Higgsfield, any P2
    authority mechanism, any network/social API, or an event bus --
    applying the docstring/identifier false-positive lesson from
    P3.5/P3.8/P3.9/P3.10 from the start. The Director may freely IMPORT
    declarative types/contracts needed for orchestration -- only actual
    calls/constructions are checked.
    """

    FORBIDDEN_MODULES = {
        "integrations.higgsfield.client",
        "integrations.higgsfield.provider",
        "integrations.higgsfield.mock_provider",
        "agents.generation_approval_gate",
        "agents.generation_job_service",
        "agents.activation_contract",
        "agents.controlled_real_provider_activation",
        "agents.real_provider_execution_gate",
        "agents.real_provider_activation_preflight",
        "agents.critical_section_lock",
        "agents.executed_request_store",
        "agents.video_agent",
        "agents.final_report_service",
        "agents.planner",
        "subprocess",
        "socket",
        "urllib",
        "http",
        "http.client",
        "requests",
        "aiohttp",
        "httpx",
        "os",
        "webbrowser",
        "oauthlib",
    }

    FORBIDDEN_CALL_NAMES = {
        "create_job",
        "system",
        "popen",
        "Popen",
        "post",
        "upload",
        "connect",
        "RealGenerationAuthorization",
        "RequestScopedActivationContract",
        "ControlledRealProviderActivationContract",
    }

    @classmethod
    def setUpClass(cls):
        cls.source = DIRECTOR_PIPELINE_SOURCE_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def _called_names(self):
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    names.add(func.id)
                elif isinstance(func, ast.Attribute):
                    names.add(func.attr)
        return names

    def _imported_modules(self):
        modules = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.add(node.module)
        return modules

    def _attribute_call_names(self):
        """Only `.something(...)` method calls on an EXTERNAL/unknown
        receiver -- e.g. a hypothetical `client.publish(...)` -- never a
        plain constructor call like `PublishingAgent(...)` (legitimate
        declarative orchestration), and never a call to this module's
        OWN methods (e.g. `self._run_publishing(...)`, pure internal
        control flow, not an external action)."""

        locally_defined_method_names = {
            node.name
            for node in ast.walk(self.tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
        return names - locally_defined_method_names

    def _non_docstring_identifiers_and_literals(self):
        docstring_nodes = set()
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if (
                    node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)
                ):
                    docstring_nodes.add(id(node.body[0].value))
        texts = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name):
                texts.append(node.id)
            elif isinstance(node, ast.Attribute):
                texts.append(node.attr)
            elif isinstance(node, ast.arg):
                texts.append(node.arg)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                texts.append(node.name)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) not in docstring_nodes:
                    texts.append(node.value)
        return texts

    def test_no_forbidden_module_imports(self):
        offenders = self._imported_modules() & self.FORBIDDEN_MODULES
        self.assertFalse(offenders, f"agents/director_pipeline.py imports forbidden module(s): {offenders}")

    def test_no_forbidden_calls_or_constructions(self):
        offenders = self._called_names() & self.FORBIDDEN_CALL_NAMES
        self.assertFalse(offenders, f"agents/director_pipeline.py contains forbidden call(s): {offenders}")

    def test_no_create_job_call(self):
        self.assertNotIn("create_job", self._called_names())

    def test_no_provider_dependency(self):
        texts = self._non_docstring_identifiers_and_literals()
        self.assertNotIn("HiggsfieldProvider", texts)
        self.assertNotIn("HiggsfieldClient", texts)

    def test_no_network_related_substrings_at_all(self):
        for banned_substring in ("requests.", "urllib.", "socket.", "http.client", "subprocess.", "os.system", "aiohttp.", "httpx."):
            self.assertNotIn(banned_substring, self.source)

    def test_no_event_bus_implementation(self):
        # Only real METHOD calls (`.emit(`/`.subscribe(`) are suspicious
        # -- a constructor call to an imported class is not.
        suspicious = {name for name in self._attribute_call_names() if "emit" in name.lower() or "subscribe" in name.lower()}
        self.assertFalse(suspicious, f"Suspicious event-bus-like method call(s): {suspicious}")
        self.assertNotIn("EventBus", self._non_docstring_identifiers_and_literals())

    def test_no_publish_execution(self):
        # Only real METHOD calls (e.g. a hypothetical `client.publish(...)`)
        # are suspicious -- constructing `PublishingAgent(...)` (an
        # imported class from agents.publishing_agent, already verified
        # network-free by that module's own AST security tests) is
        # legitimate declarative orchestration, not an execution call.
        suspicious_calls = {name for name in self._attribute_call_names() if "publish" in name.lower()}
        self.assertFalse(suspicious_calls, f"Suspicious publish-like method call(s): {suspicious_calls}")

    def test_no_credential_oauth_tokens(self):
        lowered = self.source.lower()
        # Scan only outside docstrings would be ideal, but this module's
        # docstrings never mention these terms at all -- a plain
        # substring check is therefore already zero-false-positive here.
        for token in ("api_key", "apikey", "oauth", "credential", "access_token", "bearer", "password"):
            self.assertNotIn(token, lowered)

    def test_director_py_new_method_has_no_forbidden_calls(self):
        director_source = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        tree = ast.parse(director_source)
        method_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "run_business_pipeline":
                method_node = node
                break
        self.assertIsNotNone(method_node, "run_business_pipeline method not found in director.py")

        called_names = set()
        for node in ast.walk(method_node):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    called_names.add(func.id)
                elif isinstance(func, ast.Attribute):
                    called_names.add(func.attr)

        offenders = called_names & {"create_job", "RealGenerationAuthorization", "RequestScopedActivationContract", "ControlledRealProviderActivationContract"}
        self.assertFalse(offenders, f"run_business_pipeline contains forbidden call(s): {offenders}")


if __name__ == "__main__":
    unittest.main()
