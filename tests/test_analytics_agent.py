"""
Tests — AnalyticsAgent v1.0 (Phase P3.10).

Fully offline: no network, no social platform, no OAuth, no credential
of any kind is imported or constructed anywhere in this file.
"""

import ast
import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.analytics_agent import (
    AGENT_VERSION,
    ALLOWED_UNITS,
    AnalyticsAgent,
    AnalyticsAgentInput,
    AnalyticsAgentOutput,
    AnalyticsAgentStatus,
    AnalyticsCollectionContext,
    AnalyticsCollectionProfile,
    AnalyticsCollectionResult,
    AnalyticsEngine,
    AnalyticsObservation,
    AnalyticsSourceTrust,
    CONTRACT_VERSION,
    DeterministicAnalyticsEngine,
    compute_analytics_idempotency_key,
    compute_observations_hash,
)
from agents.content_agent import ContentAgent, ContentAgentInput
from agents.optimization_agent import ANALYTICS_ARTIFACT_TYPE, ANALYTICS_CONTRACT_VERSION, AnalyticsPeriod, MetricValue
from agents.publishing_agent import PublishingAgent, PublishingAgentInput
from agents.quality_agent import QualityAgent, QualityAgentInput, QualityAgentStatus
from agents.strategy_agent import StrategyAgent, StrategyAgentInput

ANALYTICS_AGENT_SOURCE_PATH = PROJECT_ROOT / "agents" / "analytics_agent.py"


def _period(start="2026-01-01T00:00:00", end="2026-01-07T00:00:00", tz="UTC") -> AnalyticsPeriod:
    return AnalyticsPeriod(start=start, end=end, timezone=tz)


def _obs(metric, value, unit="count", platform="tiktok", source=None, source_reference="manual-entry-1", **overrides):
    source = source or AnalyticsSourceTrust.EXPLICIT_INPUT.value
    defaults = dict(metric=metric, value=value, unit=unit, platform=platform, source=source, source_reference=source_reference)
    defaults.update(overrides)
    return AnalyticsObservation(**defaults)


def _valid_input(**overrides):
    defaults = dict(
        mission_id="mission-001",
        platform="tiktok",
        period=_period(),
        observations=(
            _obs("views", 500.0, unit="count"),
            _obs("completion_rate", 0.45, unit="ratio"),
        ),
    )
    defaults.update(overrides)
    return AnalyticsAgentInput(**defaults)


def _valid_content_triplet(mission_id="mission-001"):
    strategy_output = StrategyAgent().run(
        StrategyAgentInput(
            mission_id=mission_id, objective="Explain why discipline beats talent over time.",
            platforms=("tiktok", "youtube"), topic="discipline vs talent",
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


class AnalyticsAgentBehaviorTests(unittest.TestCase):
    """Tests 1-3 from the P3.10 mandatory list."""

    def test_valid_input(self):
        output = AnalyticsAgent().run(_valid_input())
        self.assertEqual(output.status, AnalyticsAgentStatus.COLLECTED)
        self.assertIsNotNone(output.analytics_artifact)
        self.assertEqual(output.analytics_artifact.artifact_type, ANALYTICS_ARTIFACT_TYPE)

    def test_missing_observations_is_rejected(self):
        output = AnalyticsAgent().run(_valid_input(observations=()))
        self.assertEqual(output.status, AnalyticsAgentStatus.REJECTED)
        self.assertIsNone(output.analytics_artifact)

    def test_valid_observation_fields(self):
        output = AnalyticsAgent().run(_valid_input())
        obs = output.analytics_artifact.observations
        self.assertTrue(any(o.metric == "views" for o in obs))
        self.assertTrue(all(o.source_reference for o in obs))


class AnalyticsAgentMetricValidationTests(unittest.TestCase):
    """Tests 4-11 from the P3.10 mandatory list."""

    def test_missing_metric_value_is_rejected_at_construction(self):
        with self.assertRaises(TypeError):
            AnalyticsObservation(metric="views")  # type: ignore

    def test_zero_metric_is_valid(self):
        output = AnalyticsAgent().run(_valid_input(observations=(_obs("views", 0.0),)))
        self.assertEqual(output.status, AnalyticsAgentStatus.COLLECTED)
        self.assertEqual(output.analytics_artifact.metrics[0].value, 0.0)

    def test_negative_count_is_validation_error(self):
        output = AnalyticsAgent().run(_valid_input(observations=(_obs("views", -5.0),)))
        self.assertEqual(output.status, AnalyticsAgentStatus.VALIDATION_ERROR)

    def test_invalid_percentage_is_validation_error(self):
        output = AnalyticsAgent().run(
            _valid_input(observations=(_obs("completion_rate", 150.0, unit="percentage"),))
        )
        self.assertEqual(output.status, AnalyticsAgentStatus.VALIDATION_ERROR)

    def test_invalid_ratio_is_validation_error(self):
        output = AnalyticsAgent().run(_valid_input(observations=(_obs("completion_rate", 1.5, unit="ratio"),)))
        self.assertEqual(output.status, AnalyticsAgentStatus.VALIDATION_ERROR)

    def test_invalid_duration_is_validation_error(self):
        output = AnalyticsAgent().run(_valid_input(observations=(_obs("watch_time", -10.0, unit="seconds"),)))
        self.assertEqual(output.status, AnalyticsAgentStatus.VALIDATION_ERROR)

    def test_unknown_metric_is_validation_error(self):
        output = AnalyticsAgent().run(_valid_input(observations=(_obs("some_unknown_metric", 1.0),)))
        self.assertEqual(output.status, AnalyticsAgentStatus.VALIDATION_ERROR)

    def test_unit_mismatch_is_validation_error(self):
        output = AnalyticsAgent().run(_valid_input(observations=(_obs("views", 5.0, unit="ratio"),)))
        self.assertEqual(output.status, AnalyticsAgentStatus.VALIDATION_ERROR)


class AnalyticsAgentPeriodTests(unittest.TestCase):
    """Tests 10-11 from the P3.10 mandatory list."""

    def test_invalid_period_is_validation_error(self):
        bad_period = _period(start="2026-01-10T00:00:00", end="2026-01-01T00:00:00")
        output = AnalyticsAgent().run(_valid_input(period=bad_period))
        self.assertEqual(output.status, AnalyticsAgentStatus.VALIDATION_ERROR)

    def test_invalid_timezone_is_validation_error(self):
        bad_period = _period(tz="Mars/OlympusMons")
        output = AnalyticsAgent().run(_valid_input(period=bad_period))
        self.assertEqual(output.status, AnalyticsAgentStatus.VALIDATION_ERROR)


class AnalyticsAgentPlatformTests(unittest.TestCase):
    """Test 12, 29 from the P3.10 mandatory list."""

    def test_invalid_platform_is_validation_error(self):
        output = AnalyticsAgent().run(_valid_input(platform="myspace"))
        self.assertEqual(output.status, AnalyticsAgentStatus.VALIDATION_ERROR)

    def test_platform_preservation(self):
        output = AnalyticsAgent().run(_valid_input(platform="youtube", observations=(_obs("views", 10.0, platform="youtube"),)))
        self.assertEqual(output.analytics_artifact.platform, "youtube")

    def test_observation_platform_mismatch_is_validation_error(self):
        output = AnalyticsAgent().run(_valid_input(platform="tiktok", observations=(_obs("views", 10.0, platform="youtube"),)))
        self.assertEqual(output.status, AnalyticsAgentStatus.VALIDATION_ERROR)


class AnalyticsAgentDeterminismTests(unittest.TestCase):
    """Tests 13-15 from the P3.10 mandatory list."""

    def test_deterministic_normalization(self):
        agent = AnalyticsAgent()
        obs = (_obs("completion_rate", 45.0, unit="percentage"),)
        first = agent.run(_valid_input(observations=obs))
        second = agent.run(_valid_input(observations=obs))
        self.assertEqual(first.analytics_artifact.metrics, second.analytics_artifact.metrics)
        self.assertAlmostEqual(first.analytics_artifact.metrics[0].value, 0.45)

    def test_deterministic_artifact(self):
        agent = AnalyticsAgent()
        first = agent.run(_valid_input())
        second = agent.run(_valid_input())
        self.assertEqual(first.status, second.status)
        self.assertEqual(first.analytics_artifact.metrics, second.analytics_artifact.metrics)

    def test_deterministic_hash(self):
        agent = AnalyticsAgent()
        first = agent.run(_valid_input())
        second = agent.run(_valid_input())
        self.assertEqual(first.analytics_artifact.content_hash, second.analytics_artifact.content_hash)
        self.assertEqual(first.analytics_artifact.observations_hash, second.analytics_artifact.observations_hash)


class AnalyticsAgentRawDerivedTests(unittest.TestCase):
    """Tests 16-19 from the P3.10 mandatory list."""

    def test_raw_metric(self):
        output = AnalyticsAgent().run(_valid_input())
        raw_obs = [o for o in output.analytics_artifact.observations if not o.is_derived]
        self.assertTrue(raw_obs)

    def test_derived_metric_computed_when_available(self):
        observations = (
            _obs("likes", 10.0), _obs("comments", 5.0), _obs("shares", 2.0), _obs("impressions", 100.0),
        )
        output = AnalyticsAgent().run(_valid_input(observations=observations))
        derived = [o for o in output.analytics_artifact.observations if o.is_derived]
        self.assertEqual(len(derived), 1)
        self.assertEqual(derived[0].metric, "engagement_rate")
        self.assertAlmostEqual(derived[0].value, (10.0 + 5.0 + 2.0) / 100.0)
        # NEVER injected into canonical metrics (Section 20).
        self.assertFalse(any(m.name == "engagement_rate" for m in output.analytics_artifact.metrics))

    def test_derived_metric_provenance(self):
        observations = (
            _obs("likes", 10.0), _obs("comments", 5.0), _obs("shares", 2.0), _obs("impressions", 100.0),
        )
        output = AnalyticsAgent().run(_valid_input(observations=observations))
        derived = next(o for o in output.analytics_artifact.observations if o.is_derived)
        self.assertEqual(set(derived.derived_from), {"likes", "comments", "shares", "impressions"})
        self.assertEqual(derived.source, AnalyticsSourceTrust.DERIVED.value)

    def test_division_by_zero_never_computed(self):
        observations = (
            _obs("likes", 10.0), _obs("comments", 5.0), _obs("shares", 2.0), _obs("impressions", 0.0),
        )
        output = AnalyticsAgent().run(_valid_input(observations=observations))
        self.assertFalse(any(o.is_derived for o in output.analytics_artifact.observations))

    def test_absent_denominator_never_computed(self):
        observations = (_obs("likes", 10.0), _obs("comments", 5.0), _obs("shares", 2.0))
        output = AnalyticsAgent().run(_valid_input(observations=observations))
        self.assertFalse(any(o.is_derived for o in output.analytics_artifact.observations))


class AnalyticsAgentPartialInvalidTests(unittest.TestCase):
    """Tests 20-23 from the P3.10 mandatory list."""

    def test_partial_data(self):
        observations = (
            _obs("views", 100.0, source_reference="ref-a"),
            _obs("views", 200.0, source_reference="ref-b"),
            _obs("completion_rate", 0.5, unit="ratio", source_reference="ref-c"),
        )
        output = AnalyticsAgent().run(_valid_input(observations=observations))
        self.assertEqual(output.status, AnalyticsAgentStatus.PARTIAL)
        self.assertFalse(any(m.name == "views" for m in output.analytics_artifact.metrics))
        self.assertTrue(any(m.name == "completion_rate" for m in output.analytics_artifact.metrics))

    def test_invalid_data_is_validation_error(self):
        output = AnalyticsAgent().run(_valid_input(observations=(_obs("views", -1.0),)))
        self.assertEqual(output.status, AnalyticsAgentStatus.VALIDATION_ERROR)

    def test_no_fabricated_data(self):
        output = AnalyticsAgent().run(_valid_input(observations=(_obs("views", 500.0),)))
        names = {m.name for m in output.analytics_artifact.metrics}
        self.assertEqual(names, {"views"})  # completion_rate never fabricated as absent-but-present

    def test_zero_vs_absent(self):
        with_zero = AnalyticsAgent().run(_valid_input(observations=(_obs("views", 0.0),)))
        without = AnalyticsAgent().run(_valid_input(observations=(_obs("completion_rate", 0.4, unit="ratio"),)))
        self.assertTrue(any(m.name == "views" and m.value == 0.0 for m in with_zero.analytics_artifact.metrics))
        self.assertFalse(any(m.name == "views" for m in without.analytics_artifact.metrics))


class AnalyticsAgentProvenanceTests(unittest.TestCase):
    """Tests 24-27 from the P3.10 mandatory list."""

    def test_source_provenance(self):
        output = AnalyticsAgent().run(_valid_input())
        self.assertTrue(output.analytics_artifact.source_references)
        for obs in output.analytics_artifact.observations:
            self.assertIn(obs.source_reference, output.analytics_artifact.source_references)

    def test_explicit_input_source(self):
        output = AnalyticsAgent().run(_valid_input())
        for obs in output.analytics_artifact.observations:
            if not obs.is_derived:
                self.assertEqual(obs.source, AnalyticsSourceTrust.EXPLICIT_INPUT.value)

    def test_observed_at_preservation(self):
        observations = (_obs("views", 500.0, observed_at="2026-01-03T12:00:00+00:00"),)
        output = AnalyticsAgent().run(_valid_input(observations=observations))
        obs = next(o for o in output.analytics_artifact.observations if o.metric == "views")
        self.assertEqual(obs.observed_at, "2026-01-03T12:00:00+00:00")

    def test_period_preservation(self):
        period = _period(start="2026-02-01T00:00:00", end="2026-02-07T00:00:00")
        output = AnalyticsAgent().run(_valid_input(period=period))
        self.assertEqual(output.analytics_artifact.period, period)


class AnalyticsAgentCurrencyTests(unittest.TestCase):
    """Tests 30-31 from the P3.10 mandatory list."""

    def test_currency_handling(self):
        observations = (_obs("revenue", 42.5, unit="currency", currency="USD"),)
        output = AnalyticsAgent().run(_valid_input(observations=observations))
        self.assertEqual(output.status, AnalyticsAgentStatus.COLLECTED)
        revenue_obs = next(o for o in output.analytics_artifact.observations if o.metric == "revenue")
        self.assertEqual(revenue_obs.currency, "USD")
        # NEVER included in canonical numeric metrics (no currency slot there).
        self.assertFalse(any(m.name == "revenue" for m in output.analytics_artifact.metrics))

    def test_missing_currency_is_validation_error(self):
        output = AnalyticsAgent().run(_valid_input(observations=(_obs("revenue", 42.5, unit="currency"),)))
        self.assertEqual(output.status, AnalyticsAgentStatus.VALIDATION_ERROR)

    def test_no_currency_conversion(self):
        observations = (_obs("revenue", 100.0, unit="currency", currency="EUR"),)
        output = AnalyticsAgent().run(_valid_input(observations=observations))
        revenue_obs = next(o for o in output.analytics_artifact.observations if o.metric == "revenue")
        self.assertEqual(revenue_obs.value, 100.0)
        self.assertEqual(revenue_obs.currency, "EUR")


class AnalyticsAgentImmutabilityTests(unittest.TestCase):
    """Tests 32-33 from the P3.10 mandatory list."""

    def test_immutable_input(self):
        agent_input = _valid_input()
        before_observations = agent_input.observations
        AnalyticsAgent().run(agent_input)
        self.assertEqual(agent_input.observations, before_observations)

    def test_immutable_output(self):
        output = AnalyticsAgent().run(_valid_input())
        with self.assertRaises(FrozenInstanceError):
            output.analytics_artifact.platform = "tampered"
        with self.assertRaises(FrozenInstanceError):
            output.analytics_artifact.observations[0].value = 999.0


class AnalyticsAgentMetadataTests(unittest.TestCase):
    """Tests 34-36 from the P3.10 mandatory list."""

    def test_version_metadata(self):
        output = AnalyticsAgent().run(_valid_input())
        self.assertEqual(output.analytics_artifact.version, 1)
        self.assertEqual(output.analytics_artifact.artifact_type, ANALYTICS_ARTIFACT_TYPE)

    def test_producer_metadata(self):
        output = AnalyticsAgent().run(_valid_input())
        self.assertEqual(output.producer_agent, "analytics-agent")
        self.assertEqual(output.producer_version, AGENT_VERSION)
        self.assertEqual(output.analytics_artifact.producer_agent, "analytics-agent")

    def test_contract_version(self):
        output = AnalyticsAgent().run(_valid_input())
        self.assertEqual(output.contract_version, CONTRACT_VERSION)
        self.assertEqual(output.analytics_artifact.contract_version, ANALYTICS_CONTRACT_VERSION)


class AnalyticsAgentIdempotencyTests(unittest.TestCase):
    """Tests 37-38 from the P3.10 mandatory list."""

    def test_idempotency_same_input(self):
        k1 = compute_analytics_idempotency_key(_valid_input())
        k2 = compute_analytics_idempotency_key(_valid_input())
        self.assertEqual(k1, k2)

    def test_idempotency_changed_input(self):
        k1 = compute_analytics_idempotency_key(_valid_input(observations=(_obs("views", 100.0),)))
        k2 = compute_analytics_idempotency_key(_valid_input(observations=(_obs("views", 999.0),)))
        self.assertNotEqual(k1, k2)


class AnalyticsAgentCrossReferenceTests(unittest.TestCase):
    """Tests 39-43 from the P3.10 mandatory list."""

    def test_mission_validation(self):
        content_a, script_a, quality_a = _valid_content_triplet("mission-A")
        output = AnalyticsAgent().run(
            _valid_input(mission_id="mission-B", content_artifact=content_a)
        )
        self.assertEqual(output.status, AnalyticsAgentStatus.REJECTED)

    def test_content_reference(self):
        content_artifact, script_artifact, quality_artifact = _valid_content_triplet("mission-001")
        output = AnalyticsAgent().run(_valid_input(content_artifact=content_artifact))
        self.assertEqual(output.status, AnalyticsAgentStatus.COLLECTED)

    def test_quality_reference(self):
        content_artifact, script_artifact, quality_artifact = _valid_content_triplet("mission-001")
        output = AnalyticsAgent().run(_valid_input(quality_artifact=quality_artifact))
        self.assertEqual(output.status, AnalyticsAgentStatus.COLLECTED)

    def test_publication_reference(self):
        content_artifact, script_artifact, quality_artifact = _valid_content_triplet("mission-001")
        publishing_output = PublishingAgent().run(
            PublishingAgentInput(mission_id="mission-001", content_artifact=content_artifact, script_artifact=script_artifact, quality_artifact=quality_artifact)
        )
        output = AnalyticsAgent().run(_valid_input(publication_artifact=publishing_output.publication_artifact))
        self.assertEqual(output.status, AnalyticsAgentStatus.COLLECTED)

    def test_publication_prepared_not_published(self):
        content_artifact, script_artifact, quality_artifact = _valid_content_triplet("mission-001")
        publishing_output = PublishingAgent().run(
            PublishingAgentInput(mission_id="mission-001", content_artifact=content_artifact, script_artifact=script_artifact, quality_artifact=quality_artifact)
        )
        self.assertIn(publishing_output.publication_artifact.publication_status.value, ("PREPARED", "PREPARATION_WARNING"))
        output = AnalyticsAgent().run(_valid_input(publication_artifact=publishing_output.publication_artifact))
        # AnalyticsAgent never surfaces a "published" claim anywhere.
        self.assertFalse(hasattr(output, "published"))
        self.assertFalse(hasattr(output.analytics_artifact, "published"))


class FakeAnalyticsEngine(AnalyticsEngine):
    """Test-only engine proving the AnalyticsEngine contract is
    substitutable (mandatory tests 44/45)."""

    def collect(self, context: AnalyticsCollectionContext) -> AnalyticsCollectionResult:
        return AnalyticsCollectionResult(metrics=(MetricValue(name="views", value=1.0),), warnings=("fake engine used",))


class AnalyticsAgentEngineTests(unittest.TestCase):
    def test_fake_engine_compatibility(self):
        agent = AnalyticsAgent(engine=FakeAnalyticsEngine())
        output = agent.run(_valid_input())
        self.assertEqual(output.status, AnalyticsAgentStatus.PARTIAL)
        self.assertEqual(output.analytics_artifact.metrics[0].value, 1.0)

    def test_default_engine_is_deterministic_engine(self):
        agent = AnalyticsAgent()
        self.assertIsInstance(agent.engine, DeterministicAnalyticsEngine)


class AnalyticsAgentAuthorityBoundaryTests(unittest.TestCase):
    """Test 46 from the P3.10 mandatory list."""

    def test_mission_state_unchanged(self):
        output = AnalyticsAgent().run(_valid_input())
        self.assertFalse(hasattr(output, "current_state"))
        self.assertFalse(hasattr(output.analytics_artifact, "current_state"))

    def test_no_event_bus(self):
        agent = AnalyticsAgent()
        self.assertFalse(hasattr(agent, "event_bus"))
        self.assertFalse(hasattr(agent, "emit"))
        self.assertFalse(hasattr(agent, "publish"))
        self.assertFalse(hasattr(agent, "subscribe"))


class AnalyticsAgentNoSideEffectTests(unittest.TestCase):
    """Test 58 from the P3.10 mandatory list."""

    def test_no_filesystem_state_mutation(self):
        state_dir = PROJECT_ROOT / "state"
        locks_dir = state_dir / "locks"
        executed_requests = state_dir / "executed_requests.json"

        locks_before = sorted(locks_dir.glob("*")) if locks_dir.exists() else []
        existed_before = executed_requests.exists()

        AnalyticsAgent().run(_valid_input())

        locks_after = sorted(locks_dir.glob("*")) if locks_dir.exists() else []
        self.assertEqual(locks_before, locks_after)
        self.assertEqual(existed_before, executed_requests.exists())


class AnalyticsAgentSecurityTests(unittest.TestCase):
    """
    Tests 47-57 from the P3.10 mandatory list: static (AST) verification
    that agents/analytics_agent.py cannot reach any social/platform SDK,
    HTTP client, subprocess, credential, Higgsfield, or P2 authority
    mechanism -- applying the docstring/identifier false-positive lesson
    from P3.5/P3.8/P3.9 from the start.
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
        "google",
        "tiktok",
        "instagram",
        "facebook",
        "linkedin",
        "twitter",
        "tweepy",
    }

    FORBIDDEN_CALL_NAMES = {"create_job", "system", "popen", "Popen", "post", "get", "upload", "connect"}

    @classmethod
    def setUpClass(cls):
        cls.source = ANALYTICS_AGENT_SOURCE_PATH.read_text(encoding="utf-8")
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
        self.assertFalse(offenders, f"agents/analytics_agent.py imports forbidden module(s): {offenders}")

    def test_no_forbidden_calls(self):
        offenders = self._called_names() & self.FORBIDDEN_CALL_NAMES
        self.assertFalse(offenders, f"agents/analytics_agent.py contains forbidden call(s): {offenders}")

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
        for token in ("api_key", "apikey", "password", "secret", "oauth", "credential", "access_token", "bearer", "session_cookie"):
            offenders = [t for t in texts if token in t.lower()]
            self.assertFalse(offenders, f"Found credential/OAuth-like identifier or non-docstring literal containing '{token}': {offenders}")

    def test_no_network_related_substrings_at_all(self):
        for banned_substring in ("requests.", "urllib.", "socket.", "http.client", "subprocess.", "os.system", "aiohttp.", "httpx."):
            self.assertNotIn(banned_substring, self.source)

    def test_no_event_bus_calls(self):
        locally_defined_names = {
            node.name for node in ast.walk(self.tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        suspicious = {name for name in self._called_names() if "emit" in name.lower() or "subscribe" in name.lower()}
        self.assertFalse(suspicious - locally_defined_names)

    def test_publish_word_usage_is_documentary_only(self):
        locally_defined_names = {
            node.name for node in ast.walk(self.tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        suspicious_calls = {name for name in self._called_names() if "publish" in name.lower()}
        undefined_elsewhere = suspicious_calls - locally_defined_names
        self.assertFalse(undefined_elsewhere, f"Call(s) to a 'publish'-related name not defined in this module: {undefined_elsewhere}")

    def test_no_published_literal_ever_constructed(self):
        # "PUBLISHED" may legitimately appear in a docstring explaining
        # the prohibition -- it must never appear as a non-docstring
        # string literal (i.e. an actual constructed value).
        texts = self._non_docstring_identifiers_and_literals()
        offenders = [t for t in texts if t == "PUBLISHED"]
        self.assertFalse(offenders, "Found 'PUBLISHED' as an actual (non-docstring) literal value in agents/analytics_agent.py")

    def test_no_platform_sdk_names(self):
        for sdk_name in ("youtube_dl", "tiktok_api", "instagram_private_api", "facebook_business", "linkedin_api", "tweepy"):
            self.assertNotIn(sdk_name, self.source.lower())


if __name__ == "__main__":
    unittest.main()
