"""
Tests — OptimizationAgent v1.0 (Phase P3.9).

Fully offline: no network, no Higgsfield, no social platform, no OAuth,
no credential of any kind is imported or constructed anywhere in this
file.
"""

import ast
import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.content_agent import ContentAgent, ContentAgentInput
from agents.optimization_agent import (
    AGENT_VERSION,
    ANALYTICS_ARTIFACT_TYPE,
    CONTRACT_VERSION,
    OPTIMIZATION_ARTIFACT_TYPE,
    AnalyticsArtifact,
    AnalyticsPeriod,
    DeterministicOptimizationEngine,
    MetricValue,
    OptimizationAgent,
    OptimizationAgentInput,
    OptimizationAgentOutput,
    OptimizationAgentStatus,
    OptimizationEngine,
    OptimizationEvaluationContext,
    OptimizationEvaluationResult,
    OptimizationProfile,
    OptimizationRecommendation,
    OptimizationRecommendationStatus,
    OptimizationThresholds,
    compute_analytics_artifact_hash,
    compute_optimization_idempotency_key,
)
from agents.quality_agent import QualityAgent, QualityAgentInput, QualityAgentStatus
from agents.strategy_agent import StrategyAgent, StrategyAgentInput

OPTIMIZATION_AGENT_SOURCE_PATH = PROJECT_ROOT / "agents" / "optimization_agent.py"


def _period(start="2026-01-01T00:00:00", end="2026-01-07T00:00:00", tz="UTC") -> AnalyticsPeriod:
    return AnalyticsPeriod(start=start, end=end, timezone=tz)


def _build_analytics(
    mission_id="mission-001",
    platform="tiktok",
    metrics=(("views", 500.0), ("completion_rate", 0.45), ("click_through_rate", 0.03)),
    period=None,
) -> AnalyticsArtifact:
    period = period or _period()
    metric_values = tuple(MetricValue(name=name, value=value) for name, value in metrics)
    content_hash = compute_analytics_artifact_hash(
        mission_id=mission_id, platform=platform, period=period, metrics=metric_values, contract_version=1
    )
    return AnalyticsArtifact(
        artifact_id="analytics-" + mission_id,
        artifact_type=ANALYTICS_ARTIFACT_TYPE,
        mission_id=mission_id,
        created_at="2026-01-08T00:00:00+00:00",
        version=1,
        status="FINAL",
        platform=platform,
        period=period,
        metrics=metric_values,
        producer_agent="analytics-agent",
        producer_version="0.0",
        contract_version=1,
        content_hash=content_hash,
    )


def _valid_content_triplet(mission_id="mission-001"):
    strategy_output = StrategyAgent().run(
        StrategyAgentInput(
            mission_id=mission_id,
            objective="Explain why discipline beats talent over time.",
            platforms=("tiktok", "youtube"),
            topic="discipline vs talent",
            audience="young adults pursuing self-improvement",
        )
    )
    content_output = ContentAgent().run(
        ContentAgentInput(mission_id=mission_id, strategy_artifact=strategy_output.strategy_artifact, language_override="en")
    )
    quality_output = QualityAgent().run(
        QualityAgentInput(mission_id=mission_id, content_artifact=content_output.content_artifact, script_artifact=content_output.script_artifact)
    )
    assert quality_output.status == QualityAgentStatus.PASS
    return content_output.content_artifact, content_output.script_artifact, quality_output.quality_artifact


def _valid_input(**overrides):
    analytics = _build_analytics("mission-001")
    defaults = dict(mission_id="mission-001", analytics_artifact=analytics)
    defaults.update(overrides)
    return OptimizationAgentInput(**defaults)


class OptimizationAgentBehaviorTests(unittest.TestCase):
    """Tests 1-4 from the P3.9 mandatory list."""

    def test_valid_analytics_input(self):
        output = OptimizationAgent().run(_valid_input())
        self.assertIn(output.status, (OptimizationAgentStatus.READY, OptimizationAgentStatus.WARNING))
        self.assertIsNotNone(output.optimization_artifact)

    def test_missing_analytics_is_rejected(self):
        output = OptimizationAgent().run(_valid_input(analytics_artifact=None))
        self.assertEqual(output.status, OptimizationAgentStatus.REJECTED)
        self.assertIsNone(output.optimization_artifact)

    def test_wrong_mission_is_rejected(self):
        analytics_other = _build_analytics("mission-OTHER")
        output = OptimizationAgent().run(
            OptimizationAgentInput(mission_id="mission-001", analytics_artifact=analytics_other)
        )
        self.assertEqual(output.status, OptimizationAgentStatus.REJECTED)

    def test_wrong_artifact_type_is_rejected(self):
        analytics = _build_analytics("mission-001")
        tampered = replace(analytics, artifact_type="NotAnalytics")
        output = OptimizationAgent().run(_valid_input(analytics_artifact=tampered))
        self.assertEqual(output.status, OptimizationAgentStatus.REJECTED)


class OptimizationAgentIntegrityTests(unittest.TestCase):
    """Tests 5-6 from the P3.9 mandatory list."""

    def test_analytics_integrity_valid(self):
        output = OptimizationAgent().run(_valid_input())
        self.assertNotEqual(output.status, OptimizationAgentStatus.INTEGRITY_FAILURE)

    def test_analytics_integrity_failure(self):
        analytics = _build_analytics("mission-001")
        tampered = replace(analytics, platform="youtube")  # hash left stale
        output = OptimizationAgent().run(_valid_input(analytics_artifact=tampered))
        self.assertEqual(output.status, OptimizationAgentStatus.INTEGRITY_FAILURE)
        self.assertIsNotNone(output.optimization_artifact)
        self.assertEqual(output.optimization_artifact.recommendations, ())


class OptimizationAgentMetricTests(unittest.TestCase):
    """Tests 7-11 from the P3.9 mandatory list."""

    def test_absent_metric_is_not_zero(self):
        analytics = _build_analytics("mission-001", metrics=(("views", 500.0),))
        output = OptimizationAgent().run(_valid_input(analytics_artifact=analytics))
        # completion_rate/click_through_rate are ABSENT, not 0 -- no
        # threshold recommendation should fire for either.
        for rec in (output.optimization_artifact.recommendations if output.optimization_artifact else ()):
            self.assertNotEqual(rec.target, "hook_and_early_pacing")
            self.assertNotEqual(rec.target, "call_to_action")

    def test_zero_metric_is_distinct_from_absent(self):
        analytics = _build_analytics(
            "mission-001", metrics=(("views", 500.0), ("completion_rate", 0.0))
        )
        output = OptimizationAgent().run(_valid_input(analytics_artifact=analytics))
        self.assertIn(output.status, (OptimizationAgentStatus.READY, OptimizationAgentStatus.WARNING))
        # completion_rate=0.0 IS below threshold -> a recommendation SHOULD fire.
        self.assertTrue(
            any(rec.target == "hook_and_early_pacing" for rec in output.optimization_artifact.recommendations)
        )

    def test_invalid_metric_type_is_validation_error(self):
        analytics = _build_analytics("mission-001")
        bad_metric = MetricValue(name="views", value="not-a-number")  # type: ignore
        tampered = replace(analytics, metrics=(bad_metric,))
        rehashed = replace(
            tampered,
            content_hash=compute_analytics_artifact_hash(
                mission_id=tampered.mission_id, platform=tampered.platform, period=tampered.period,
                metrics=tampered.metrics, contract_version=tampered.contract_version,
            ),
        )
        output = OptimizationAgent().run(_valid_input(analytics_artifact=rehashed))
        self.assertEqual(output.status, OptimizationAgentStatus.VALIDATION_ERROR)

    def test_negative_metric_is_validation_error(self):
        analytics = _build_analytics("mission-001", metrics=(("views", -10.0),))
        output = OptimizationAgent().run(_valid_input(analytics_artifact=analytics))
        self.assertEqual(output.status, OptimizationAgentStatus.VALIDATION_ERROR)

    def test_invalid_percentage_is_validation_error(self):
        analytics = _build_analytics("mission-001", metrics=(("completion_rate", 1.5),))
        output = OptimizationAgent().run(_valid_input(analytics_artifact=analytics))
        self.assertEqual(output.status, OptimizationAgentStatus.VALIDATION_ERROR)


class OptimizationAgentPeriodTests(unittest.TestCase):
    """Test 12 from the P3.9 mandatory list."""

    def test_invalid_period_is_validation_error(self):
        bad_period = _period(start="2026-01-10T00:00:00", end="2026-01-01T00:00:00")
        analytics = _build_analytics("mission-001", period=bad_period)
        output = OptimizationAgent().run(_valid_input(analytics_artifact=analytics))
        self.assertEqual(output.status, OptimizationAgentStatus.VALIDATION_ERROR)


class OptimizationAgentDeterminismTests(unittest.TestCase):
    """Tests 13-15 from the P3.9 mandatory list."""

    def test_deterministic_evaluation(self):
        analytics = _build_analytics("mission-001")
        agent = OptimizationAgent()
        first = agent.run(_valid_input(analytics_artifact=analytics))
        second = agent.run(_valid_input(analytics_artifact=analytics))
        self.assertEqual(first.status, second.status)

    def test_deterministic_recommendations(self):
        analytics = _build_analytics("mission-001", metrics=(("completion_rate", 0.1),))
        agent = OptimizationAgent()
        first = agent.run(_valid_input(analytics_artifact=analytics))
        second = agent.run(_valid_input(analytics_artifact=analytics))
        self.assertEqual(
            [(r.recommendation_id, r.category, r.confidence) for r in first.optimization_artifact.recommendations],
            [(r.recommendation_id, r.category, r.confidence) for r in second.optimization_artifact.recommendations],
        )

    def test_deterministic_hash(self):
        analytics = _build_analytics("mission-001")
        agent = OptimizationAgent()
        first = agent.run(_valid_input(analytics_artifact=analytics))
        second = agent.run(_valid_input(analytics_artifact=analytics))
        self.assertEqual(first.optimization_artifact.content_hash, second.optimization_artifact.content_hash)


class OptimizationAgentProfileTests(unittest.TestCase):
    """Tests 16-17 from the P3.9 mandatory list."""

    def test_optimization_profile(self):
        output = OptimizationAgent().run(_valid_input(optimization_profile=OptimizationProfile(name="engagement")))
        self.assertEqual(output.optimization_artifact.profile.name, "engagement")

    def test_invalid_profile_is_validation_error(self):
        output = OptimizationAgent().run(_valid_input(optimization_profile=OptimizationProfile(name="not-a-real-profile")))
        self.assertEqual(output.status, OptimizationAgentStatus.VALIDATION_ERROR)

    def test_thresholds_are_configurable(self):
        analytics = _build_analytics("mission-001", metrics=(("completion_rate", 0.35),))
        # Default threshold is 0.30 -- 0.35 does not trigger. A custom,
        # higher threshold SHOULD trigger it.
        default_output = OptimizationAgent().run(_valid_input(analytics_artifact=analytics))
        self.assertFalse(
            any(r.target == "hook_and_early_pacing" for r in default_output.optimization_artifact.recommendations)
        )

        custom_profile = OptimizationProfile(thresholds=OptimizationThresholds(low_completion_rate=0.5))
        custom_output = OptimizationAgent().run(_valid_input(analytics_artifact=analytics, optimization_profile=custom_profile))
        self.assertTrue(
            any(r.target == "hook_and_early_pacing" for r in custom_output.optimization_artifact.recommendations)
        )


class OptimizationAgentDataTests(unittest.TestCase):
    """Tests 18-21 from the P3.9 mandatory list."""

    def test_insufficient_data(self):
        analytics = _build_analytics("mission-001", metrics=(("comments", 5.0),))
        output = OptimizationAgent().run(_valid_input(analytics_artifact=analytics))
        self.assertEqual(output.status, OptimizationAgentStatus.INSUFFICIENT_DATA)
        self.assertEqual(output.optimization_artifact.recommendations, ())

    def test_no_fabricated_data(self):
        # No previous_analytics_artifact supplied -> no comparison-based
        # recommendation should EVER be produced, since no baseline exists.
        analytics = _build_analytics("mission-001", metrics=(("completion_rate", 0.1),))
        output = OptimizationAgent().run(_valid_input(analytics_artifact=analytics))
        self.assertFalse(any(r.category == "performance_decline" for r in output.optimization_artifact.recommendations))
        for rec in output.optimization_artifact.recommendations:
            for evidence in rec.evidence:
                self.assertIsNone(evidence.comparison_value)

    def test_provenance(self):
        analytics = _build_analytics("mission-001", metrics=(("completion_rate", 0.1),))
        output = OptimizationAgent().run(_valid_input(analytics_artifact=analytics))
        refs = {ref.artifact_id: ref for ref in output.optimization_artifact.source_artifacts}
        self.assertIn(analytics.artifact_id, refs)
        self.assertEqual(refs[analytics.artifact_id].content_hash, analytics.content_hash)

    def test_evidence_structure(self):
        analytics = _build_analytics("mission-001", metrics=(("completion_rate", 0.1),))
        output = OptimizationAgent().run(_valid_input(analytics_artifact=analytics))
        rec = output.optimization_artifact.recommendations[0]
        self.assertTrue(rec.evidence)
        evidence = rec.evidence[0]
        self.assertEqual(evidence.metric, "completion_rate")
        self.assertEqual(evidence.source_artifact_id, analytics.artifact_id)
        self.assertEqual(evidence.source_artifact_hash, analytics.content_hash)


class OptimizationAgentRecommendationStructureTests(unittest.TestCase):
    """Tests 22-26 from the P3.9 mandatory list."""

    def test_recommendation_structure(self):
        analytics = _build_analytics("mission-001", metrics=(("completion_rate", 0.1),))
        output = OptimizationAgent().run(_valid_input(analytics_artifact=analytics))
        rec = output.optimization_artifact.recommendations[0]
        for field_name in ("recommendation_id", "category", "priority", "target", "action", "rationale", "evidence", "expected_effect", "confidence", "status"):
            self.assertTrue(hasattr(rec, field_name))

    def test_recommendation_priority(self):
        analytics = _build_analytics("mission-001", metrics=(("completion_rate", 0.1),))
        output = OptimizationAgent().run(_valid_input(analytics_artifact=analytics))
        rec = output.optimization_artifact.recommendations[0]
        self.assertIn(rec.priority.value, ("LOW", "MEDIUM", "HIGH"))

    def test_recommendation_status_always_proposed(self):
        analytics = _build_analytics("mission-001", metrics=(("completion_rate", 0.1), ("click_through_rate", 0.001)))
        output = OptimizationAgent().run(_valid_input(analytics_artifact=analytics))
        self.assertTrue(output.optimization_artifact.recommendations)
        for rec in output.optimization_artifact.recommendations:
            self.assertEqual(rec.status, OptimizationRecommendationStatus.PROPOSED)

    def test_no_accepted_status_ever_produced(self):
        source = OPTIMIZATION_AGENT_SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "OptimizationRecommendation":
                for keyword in node.keywords:
                    if keyword.arg == "status":
                        # The only status ever passed to a construction
                        # call is the PROPOSED enum member.
                        self.assertTrue(
                            isinstance(keyword.value, ast.Attribute) and keyword.value.attr == "PROPOSED"
                        )

    def test_no_applied_status_ever_produced(self):
        analytics = _build_analytics("mission-001", metrics=(("completion_rate", 0.1),))
        output = OptimizationAgent().run(_valid_input(analytics_artifact=analytics))
        for rec in output.optimization_artifact.recommendations:
            self.assertNotEqual(rec.status, OptimizationRecommendationStatus.APPLIED)
            self.assertNotEqual(rec.status, OptimizationRecommendationStatus.ACCEPTED)


class OptimizationAgentNoMutationTests(unittest.TestCase):
    """Test 27 from the P3.9 mandatory list."""

    def test_no_automatic_mutation_of_source_artifacts(self):
        content_artifact, script_artifact, quality_artifact = _valid_content_triplet("mission-001")
        analytics = _build_analytics("mission-001")

        content_before = replace(content_artifact)
        quality_before = replace(quality_artifact)

        OptimizationAgent().run(
            OptimizationAgentInput(
                mission_id="mission-001",
                analytics_artifact=analytics,
                quality_artifact=quality_artifact,
                content_artifact=content_artifact,
            )
        )

        self.assertEqual(content_artifact, content_before)
        self.assertEqual(quality_artifact, quality_before)


class OptimizationAgentReferenceTests(unittest.TestCase):
    """Tests 28-30 from the P3.9 mandatory list."""

    def test_content_reference(self):
        content_artifact, script_artifact, quality_artifact = _valid_content_triplet("mission-001")
        analytics = _build_analytics("mission-001")
        output = OptimizationAgent().run(
            OptimizationAgentInput(mission_id="mission-001", analytics_artifact=analytics, content_artifact=content_artifact)
        )
        refs = {ref.artifact_id for ref in output.optimization_artifact.source_artifacts}
        self.assertIn(content_artifact.artifact_id, refs)

    def test_quality_reference(self):
        content_artifact, script_artifact, quality_artifact = _valid_content_triplet("mission-001")
        analytics = _build_analytics("mission-001")
        output = OptimizationAgent().run(
            OptimizationAgentInput(mission_id="mission-001", analytics_artifact=analytics, quality_artifact=quality_artifact)
        )
        refs = {ref.artifact_id for ref in output.optimization_artifact.source_artifacts}
        self.assertIn(quality_artifact.artifact_id, refs)

    def test_publication_reference(self):
        from agents.publishing_agent import PublishingAgent, PublishingAgentInput

        content_artifact, script_artifact, quality_artifact = _valid_content_triplet("mission-001")
        publishing_output = PublishingAgent().run(
            PublishingAgentInput(
                mission_id="mission-001", content_artifact=content_artifact, script_artifact=script_artifact, quality_artifact=quality_artifact,
            )
        )
        analytics = _build_analytics("mission-001")
        output = OptimizationAgent().run(
            OptimizationAgentInput(
                mission_id="mission-001", analytics_artifact=analytics, publication_artifact=publishing_output.publication_artifact,
            )
        )
        refs = {ref.artifact_id for ref in output.optimization_artifact.source_artifacts}
        self.assertIn(publishing_output.publication_artifact.artifact_id, refs)


class OptimizationAgentPlatformTests(unittest.TestCase):
    """Test 31 from the P3.9 mandatory list."""

    def test_platform_preservation(self):
        analytics = _build_analytics("mission-001", platform="youtube")
        output = OptimizationAgent().run(_valid_input(analytics_artifact=analytics))
        self.assertEqual(output.optimization_artifact.platform, "youtube")


class OptimizationAgentComparisonTests(unittest.TestCase):
    """Tests 32-33 from the P3.9 mandatory list."""

    def test_previous_current_comparison(self):
        previous = _build_analytics("mission-001", metrics=(("completion_rate", 0.5),))
        current = _build_analytics("mission-001", metrics=(("completion_rate", 0.4), ("views", 500.0)))
        output = OptimizationAgent().run(
            _valid_input(analytics_artifact=current, previous_analytics_artifact=previous)
        )
        self.assertTrue(
            any(r.category == "performance_decline" for r in output.optimization_artifact.recommendations)
        )
        decline = next(r for r in output.optimization_artifact.recommendations if r.category == "performance_decline")
        self.assertEqual(decline.evidence[0].comparison_value, 0.5)

    def test_no_baseline_behavior(self):
        current = _build_analytics("mission-001", metrics=(("completion_rate", 0.4),))
        output = OptimizationAgent().run(_valid_input(analytics_artifact=current))
        self.assertFalse(any(r.category == "performance_decline" for r in output.optimization_artifact.recommendations))


class OptimizationAgentConfidenceTests(unittest.TestCase):
    """Test 34 from the P3.9 mandatory list."""

    def test_confidence_behavior(self):
        analytics = _build_analytics("mission-001", metrics=(("completion_rate", 0.1),))
        output = OptimizationAgent().run(_valid_input(analytics_artifact=analytics))
        rec = output.optimization_artifact.recommendations[0]
        self.assertGreaterEqual(rec.confidence, 0.1)
        self.assertLessEqual(rec.confidence, 0.9)
        self.assertNotEqual(rec.confidence, 1.0)

    def test_low_sample_size_reduces_confidence(self):
        analytics_low_sample = _build_analytics("mission-001", metrics=(("completion_rate", 0.1), ("views", 10.0)))
        analytics_high_sample = _build_analytics("mission-001", metrics=(("completion_rate", 0.1), ("views", 1000.0)))
        low_output = OptimizationAgent().run(_valid_input(analytics_artifact=analytics_low_sample))
        high_output = OptimizationAgent().run(_valid_input(analytics_artifact=analytics_high_sample))
        low_conf = low_output.optimization_artifact.recommendations[0].confidence
        high_conf = high_output.optimization_artifact.recommendations[0].confidence
        self.assertLess(low_conf, high_conf)


class OptimizationAgentCausalitySafetyTests(unittest.TestCase):
    """Test 35 from the P3.9 mandatory list."""

    def test_causal_language_safety(self):
        analytics = _build_analytics("mission-001", metrics=(("completion_rate", 0.1),))
        output = OptimizationAgent().run(_valid_input(analytics_artifact=analytics))
        for rec in output.optimization_artifact.recommendations:
            lowered = rec.rationale.lower()
            self.assertIn("observation:", lowered)
            self.assertIn("interpretation:", lowered)
            self.assertIn("recommendation:", lowered)
            for banned in ("caused", "resulted in", "because of", " due to "):
                self.assertNotIn(banned, lowered)


class OptimizationAgentImmutabilityTests(unittest.TestCase):
    """Tests 36-37 from the P3.9 mandatory list."""

    def test_immutable_input(self):
        analytics = _build_analytics("mission-001")
        before = replace(analytics)
        OptimizationAgent().run(_valid_input(analytics_artifact=analytics))
        self.assertEqual(analytics, before)

    def test_immutable_output(self):
        analytics = _build_analytics("mission-001", metrics=(("completion_rate", 0.1),))
        output = OptimizationAgent().run(_valid_input(analytics_artifact=analytics))
        with self.assertRaises(FrozenInstanceError):
            output.optimization_artifact.platform = "tampered"
        with self.assertRaises(FrozenInstanceError):
            output.optimization_artifact.recommendations[0].confidence = 1.0


class OptimizationAgentMetadataTests(unittest.TestCase):
    """Tests 38-40 from the P3.9 mandatory list."""

    def test_version_metadata(self):
        output = OptimizationAgent().run(_valid_input())
        self.assertEqual(output.optimization_artifact.artifact_type, OPTIMIZATION_ARTIFACT_TYPE)
        self.assertEqual(output.optimization_artifact.version, 1)

    def test_producer_metadata(self):
        output = OptimizationAgent().run(_valid_input())
        self.assertEqual(output.producer_agent, "optimization-agent")
        self.assertEqual(output.producer_version, AGENT_VERSION)

    def test_contract_version(self):
        output = OptimizationAgent().run(_valid_input())
        self.assertEqual(output.contract_version, CONTRACT_VERSION)
        self.assertEqual(output.optimization_artifact.contract_version, CONTRACT_VERSION)


class OptimizationAgentIdempotencyTests(unittest.TestCase):
    """Tests 41-42 from the P3.9 mandatory list."""

    def test_idempotency_same_input(self):
        analytics = _build_analytics("mission-001")
        k1 = compute_optimization_idempotency_key(_valid_input(analytics_artifact=analytics))
        k2 = compute_optimization_idempotency_key(_valid_input(analytics_artifact=analytics))
        self.assertEqual(k1, k2)

    def test_idempotency_changed_input(self):
        analytics_a = _build_analytics("mission-001", metrics=(("views", 500.0),))
        analytics_b = _build_analytics("mission-001", metrics=(("views", 999.0),))
        k1 = compute_optimization_idempotency_key(_valid_input(analytics_artifact=analytics_a))
        k2 = compute_optimization_idempotency_key(_valid_input(analytics_artifact=analytics_b))
        self.assertNotEqual(k1, k2)


class FakeOptimizationEngine(OptimizationEngine):
    """Test-only engine proving the OptimizationEngine contract is
    substitutable (mandatory tests 43/44)."""

    def evaluate(self, context: OptimizationEvaluationContext) -> OptimizationEvaluationResult:
        from agents.optimization_agent import OptimizationEvidence, OptimizationRecommendationPriority

        return OptimizationEvaluationResult(
            recommendations=(
                OptimizationRecommendation(
                    recommendation_id="recommendation-001",
                    category="content",
                    priority=OptimizationRecommendationPriority.LOW,
                    target="fake_target",
                    action="fake action",
                    rationale="OBSERVATION: fake. INTERPRETATION: fake. RECOMMENDATION: fake.",
                    evidence=(
                        OptimizationEvidence(
                            metric="views",
                            observed_value=1.0,
                            source_artifact_id=context.analytics_artifact.artifact_id,
                            source_artifact_type=ANALYTICS_ARTIFACT_TYPE,
                            source_artifact_hash=context.analytics_artifact.content_hash,
                        ),
                    ),
                    expected_effect="fake effect",
                    confidence=0.5,
                    status=OptimizationRecommendationStatus.PROPOSED,
                ),
            )
        )


class OptimizationAgentEngineTests(unittest.TestCase):
    def test_fake_engine_compatibility(self):
        agent = OptimizationAgent(engine=FakeOptimizationEngine())
        output = agent.run(_valid_input())
        self.assertEqual(len(output.optimization_artifact.recommendations), 1)
        self.assertEqual(output.optimization_artifact.recommendations[0].target, "fake_target")

    def test_default_engine_is_deterministic_engine(self):
        agent = OptimizationAgent()
        self.assertIsInstance(agent.engine, DeterministicOptimizationEngine)


class OptimizationAgentAuthorityBoundaryTests(unittest.TestCase):
    """Test 45 from the P3.9 mandatory list."""

    def test_mission_state_unchanged(self):
        output = OptimizationAgent().run(_valid_input())
        self.assertFalse(hasattr(output, "current_state"))
        self.assertFalse(hasattr(output.optimization_artifact, "current_state"))

    def test_no_event_bus(self):
        agent = OptimizationAgent()
        self.assertFalse(hasattr(agent, "event_bus"))
        self.assertFalse(hasattr(agent, "emit"))
        self.assertFalse(hasattr(agent, "publish"))
        self.assertFalse(hasattr(agent, "subscribe"))


class OptimizationAgentSecurityTests(unittest.TestCase):
    """
    Tests 46-56 from the P3.9 mandatory list: static (AST) verification
    that agents/optimization_agent.py cannot reach any social platform,
    HTTP client, subprocess, credential, Higgsfield, or P2 authority
    mechanism -- checked structurally, applying the docstring/identifier
    false-positive lesson from P3.5/P3.8 from the start.
    """

    FORBIDDEN_MODULES = {
        "integrations.higgsfield.client",
        "integrations.higgsfield.provider",
        "integrations.higgsfield.mock_provider",
        "director",
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

    FORBIDDEN_CALL_NAMES = {"create_job", "system", "popen", "Popen", "post", "upload", "connect"}

    @classmethod
    def setUpClass(cls):
        cls.source = OPTIMIZATION_AGENT_SOURCE_PATH.read_text(encoding="utf-8")
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
        self.assertFalse(offenders, f"agents/optimization_agent.py imports forbidden module(s): {offenders}")

    def test_no_forbidden_calls(self):
        offenders = self._called_names() & self.FORBIDDEN_CALL_NAMES
        self.assertFalse(offenders, f"agents/optimization_agent.py contains forbidden call(s): {offenders}")

    def test_no_create_job_call(self):
        self.assertNotIn("create_job", self._called_names())

    def test_no_authorization_construction(self):
        self.assertNotIn("RealGenerationAuthorization", self._called_names())

    def test_no_activation_construction(self):
        called = self._called_names()
        self.assertFalse({n for n in called if "ActivationContract" in n or "ControlledRealProviderActivation" in n})

    def test_no_provider_dependency(self):
        self.assertNotIn("HiggsfieldProvider", self.source)
        self.assertNotIn("HiggsfieldClient", self.source)

    def test_no_credential_oauth_or_token_handling(self):
        texts = self._non_docstring_identifiers_and_literals()
        for token in ("api_key", "apikey", "password", "secret", "oauth", "credential", "access_token", "bearer"):
            offenders = [t for t in texts if token in t.lower()]
            self.assertFalse(offenders, f"Found credential/OAuth-like identifier or non-docstring literal containing '{token}': {offenders}")

    def test_no_network_related_substrings_at_all(self):
        for banned_substring in ("requests.", "urllib.", "socket.", "http.client", "subprocess.", "os.system", "aiohttp.", "httpx."):
            self.assertNotIn(banned_substring, self.source)

    def test_no_event_bus_calls(self):
        locally_defined_names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                locally_defined_names.add(node.name)
        suspicious = {name for name in self._called_names() if "emit" in name.lower() or "subscribe" in name.lower()}
        self.assertFalse(suspicious - locally_defined_names)

    def test_publish_word_usage_is_documentary_only(self):
        locally_defined_names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                locally_defined_names.add(node.name)
        suspicious_calls = {name for name in self._called_names() if "publish" in name.lower()}
        undefined_elsewhere = suspicious_calls - locally_defined_names
        self.assertFalse(undefined_elsewhere, f"Call(s) to a 'publish'-related name not defined in this module: {undefined_elsewhere}")

    def test_no_publication_execution(self):
        # No call anywhere in this file targets anything resembling
        # "send"/"deliver"/"execute" a publication -- this agent only
        # ever CONSTRUCTS in-memory OptimizationArtifact/recommendation
        # objects.
        for banned in ("send_publication", "execute_publication", "deliver", "trigger_publish"):
            self.assertNotIn(banned, self.source)


if __name__ == "__main__":
    unittest.main()
