"""
Tests — ContentAgent v1.0 (Phase P3.6).

Fully offline: no network, no Higgsfield, no provider of any kind is
imported or constructed anywhere in this file.
"""

import ast
import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.content_agent import (
    AGENT_VERSION,
    CONTENT_ARTIFACT_TYPE,
    CONTRACT_VERSION,
    SCRIPT_ARTIFACT_TYPE,
    ContentAgent,
    ContentAgentInput,
    ContentAgentOutput,
    ContentAgentStatus,
    ContentEngine,
    ContentGenerationContext,
    ContentGenerationResult,
    DeterministicContentEngine,
    SceneDraft,
    compute_content_artifact_hash,
    compute_content_idempotency_key,
    compute_script_artifact_hash,
)
from agents.strategy_agent import StrategyAgent, StrategyAgentInput

CONTENT_AGENT_SOURCE_PATH = PROJECT_ROOT / "agents" / "content_agent.py"


def _valid_strategy_artifact(mission_id="mission-001"):
    output = StrategyAgent().run(
        StrategyAgentInput(
            mission_id=mission_id,
            objective="Explain why discipline beats talent over time.",
            platforms=("tiktok", "youtube"),
            topic="discipline vs talent",
            audience="young adults pursuing self-improvement",
        )
    )
    assert output.status.value == "READY"
    return output.strategy_artifact


def _valid_input(**overrides):
    defaults = dict(
        mission_id="mission-001",
        strategy_artifact=_valid_strategy_artifact("mission-001"),
    )
    defaults.update(overrides)
    return ContentAgentInput(**defaults)


class ContentAgentBehaviorTests(unittest.TestCase):
    """Tests 1, 3, 4, 7, 8, 9, 10 from the P3.6 mandatory list."""

    def test_valid_strategy_artifact_produces_ready_output(self):
        output = ContentAgent().run(_valid_input())
        self.assertEqual(output.status, ContentAgentStatus.READY)
        self.assertIsNotNone(output.content_artifact)
        self.assertIsNotNone(output.script_artifact)
        self.assertEqual(output.errors, ())

    def test_missing_strategy_artifact_is_rejected(self):
        output = ContentAgent().run(_valid_input(strategy_artifact=None))
        self.assertEqual(output.status, ContentAgentStatus.REJECTED)
        self.assertIsNone(output.content_artifact)
        self.assertTrue(any("strategy_artifact is missing" in reason for reason in output.errors))

    def test_wrong_mission_id_is_rejected(self):
        wrong_mission_strategy = _valid_strategy_artifact("mission-OTHER")
        output = ContentAgent().run(
            _valid_input(mission_id="mission-001", strategy_artifact=wrong_mission_strategy)
        )
        self.assertEqual(output.status, ContentAgentStatus.REJECTED)
        self.assertTrue(any("does not match" in reason for reason in output.errors))

    def test_invalid_artifact_type_is_rejected(self):
        artifact = _valid_strategy_artifact("mission-001")
        tampered = replace(artifact, artifact_type="NotAStrategyArtifact")
        output = ContentAgent().run(_valid_input(strategy_artifact=tampered))
        self.assertEqual(output.status, ContentAgentStatus.REJECTED)
        self.assertTrue(any("artifact_type" in reason for reason in output.errors))

    def test_tampered_content_hash_is_rejected(self):
        artifact = _valid_strategy_artifact("mission-001")
        tampered = replace(artifact, objective="a different objective never validated")
        output = ContentAgent().run(_valid_input(strategy_artifact=tampered))
        self.assertEqual(output.status, ContentAgentStatus.REJECTED)
        self.assertTrue(any("content_hash" in reason for reason in output.errors))

    def test_unsupported_strategy_contract_version_is_rejected(self):
        artifact = _valid_strategy_artifact("mission-001")
        tampered = replace(artifact, contract_version=999)
        output = ContentAgent().run(_valid_input(strategy_artifact=tampered))
        self.assertEqual(output.status, ContentAgentStatus.REJECTED)
        self.assertTrue(any("contract_version" in reason for reason in output.errors))

    def test_content_artifact_fields(self):
        output = ContentAgent().run(_valid_input())
        artifact = output.content_artifact
        self.assertEqual(artifact.artifact_type, CONTENT_ARTIFACT_TYPE)
        self.assertEqual(artifact.mission_id, "mission-001")
        self.assertTrue(artifact.concept)
        self.assertTrue(artifact.angle)
        self.assertTrue(artifact.hook)
        self.assertTrue(artifact.title)
        self.assertTrue(artifact.cta)
        self.assertEqual(artifact.target_platforms, ("tiktok", "youtube"))

    def test_script_artifact_fields(self):
        output = ContentAgent().run(_valid_input())
        script = output.script_artifact
        self.assertEqual(script.artifact_type, SCRIPT_ARTIFACT_TYPE)
        self.assertEqual(len(script.scenes), 3)
        self.assertEqual([scene.order for scene in script.scenes], [1, 2, 3])
        self.assertEqual(
            sum(scene.duration for scene in script.scenes),
            script.total_duration_target,
        )

    def test_correct_producer_metadata(self):
        output = ContentAgent().run(_valid_input())
        self.assertEqual(output.producer_agent, "content-agent")
        self.assertEqual(output.producer_version, AGENT_VERSION)
        self.assertEqual(output.content_artifact.producer_agent, "content-agent")
        self.assertEqual(output.script_artifact.producer_agent, "content-agent")

    def test_correct_contract_version(self):
        output = ContentAgent().run(_valid_input())
        self.assertEqual(output.contract_version, CONTRACT_VERSION)
        self.assertEqual(output.content_artifact.contract_version, CONTRACT_VERSION)
        self.assertEqual(output.script_artifact.contract_version, CONTRACT_VERSION)


class ContentAgentDeterminismTests(unittest.TestCase):
    """Tests 5, 6, 11, 12 from the P3.6 mandatory list."""

    def test_deterministic_content(self):
        agent = ContentAgent()
        strategy_artifact = _valid_strategy_artifact("mission-001")
        first = agent.run(_valid_input(strategy_artifact=strategy_artifact))
        second = agent.run(_valid_input(strategy_artifact=strategy_artifact))

        self.assertEqual(
            first.content_artifact.content_hash, second.content_artifact.content_hash
        )
        self.assertEqual(first.content_artifact.hook, second.content_artifact.hook)
        self.assertEqual(first.content_artifact.title, second.content_artifact.title)

    def test_deterministic_scenes(self):
        agent = ContentAgent()
        strategy_artifact = _valid_strategy_artifact("mission-001")
        first = agent.run(_valid_input(strategy_artifact=strategy_artifact))
        second = agent.run(_valid_input(strategy_artifact=strategy_artifact))

        self.assertEqual(
            [
                (scene.order, scene.duration, scene.narration, scene.transition)
                for scene in first.script_artifact.scenes
            ],
            [
                (scene.order, scene.duration, scene.narration, scene.transition)
                for scene in second.script_artifact.scenes
            ],
        )
        self.assertEqual(
            first.script_artifact.content_hash, second.script_artifact.content_hash
        )

    def test_content_hash_determinism(self):
        kwargs = dict(
            mission_id="m1",
            concept="c",
            angle="a",
            hook="h",
            title="t",
            cta="cta",
            target_platforms=("tiktok",),
            language="en",
            tone="conversational",
            content_format="short_video",
            constraints=(),
            contract_version=1,
            source_strategy_content_hash="deadbeef",
        )
        self.assertEqual(
            compute_content_artifact_hash(**kwargs),
            compute_content_artifact_hash(**kwargs),
        )
        changed = dict(kwargs, hook="different hook")
        self.assertNotEqual(
            compute_content_artifact_hash(**kwargs),
            compute_content_artifact_hash(**changed),
        )

    def test_script_hash_determinism(self):
        output = ContentAgent().run(_valid_input())
        script = output.script_artifact
        recomputed = compute_script_artifact_hash(
            mission_id=script.mission_id,
            scenes=script.scenes,
            total_duration_target=script.total_duration_target,
            language=script.language,
            contract_version=script.contract_version,
            source_content_content_hash=output.content_artifact.content_hash,
        )
        self.assertEqual(recomputed, script.content_hash)


class ContentAgentImmutabilityTests(unittest.TestCase):
    """Test 13 from the P3.6 mandatory list."""

    def test_immutability(self):
        output = ContentAgent().run(_valid_input())
        with self.assertRaises(FrozenInstanceError):
            output.content_artifact.hook = "tampered"
        with self.assertRaises(FrozenInstanceError):
            output.script_artifact.scenes[0].narration = "tampered"


class ContentAgentValidationTests(unittest.TestCase):
    """Tests 14-19 from the P3.6 mandatory list."""

    def test_invalid_language_override_is_validation_error(self):
        output = ContentAgent().run(_valid_input(language_override="klingon"))
        self.assertEqual(output.status, ContentAgentStatus.VALIDATION_ERROR)
        self.assertTrue(any("language_override" in reason for reason in output.errors))

    def test_valid_language_override_is_used(self):
        output = ContentAgent().run(_valid_input(language_override="fr"))
        self.assertEqual(output.status, ContentAgentStatus.READY)
        self.assertEqual(output.content_artifact.language, "fr")
        self.assertEqual(output.script_artifact.language, "fr")
        # No "defaulting content language" warning when an override IS given.
        self.assertFalse(any("defaulting content language" in w for w in output.warnings))

    def test_missing_language_override_defaults_with_warning(self):
        output = ContentAgent().run(_valid_input())
        self.assertEqual(output.status, ContentAgentStatus.READY)
        self.assertEqual(output.content_artifact.language, "en")
        self.assertTrue(any("defaulting content language" in w for w in output.warnings))

    def test_invalid_tone_is_validation_error(self):
        output = ContentAgent().run(_valid_input(tone="sarcastic"))
        self.assertEqual(output.status, ContentAgentStatus.VALIDATION_ERROR)
        self.assertTrue(any("tone" in reason for reason in output.errors))

    def test_invalid_format_is_validation_error(self):
        output = ContentAgent().run(_valid_input(content_format="feature_film"))
        self.assertEqual(output.status, ContentAgentStatus.VALIDATION_ERROR)
        self.assertTrue(any("content_format" in reason for reason in output.errors))

    def test_platform_preservation_without_override(self):
        strategy_artifact = _valid_strategy_artifact("mission-001")
        output = ContentAgent().run(
            _valid_input(strategy_artifact=strategy_artifact)
        )
        self.assertEqual(
            output.content_artifact.target_platforms, strategy_artifact.platforms
        )

    def test_no_silent_platform_invention(self):
        # Strategy only asked for tiktok/youtube -- output must never
        # contain a platform the strategy never mentioned, with no override.
        output = ContentAgent().run(_valid_input())
        for platform in output.content_artifact.target_platforms:
            self.assertIn(platform, ("tiktok", "youtube"))

    def test_platform_override_is_validated_and_traced(self):
        output = ContentAgent().run(_valid_input(platform_override=("instagram",)))
        self.assertEqual(output.status, ContentAgentStatus.READY)
        self.assertEqual(output.content_artifact.target_platforms, ("instagram",))
        self.assertTrue(any("diverges from strategy_artifact.platforms" in w for w in output.warnings))

    def test_invalid_platform_override_is_validation_error(self):
        output = ContentAgent().run(_valid_input(platform_override=("myspace",)))
        self.assertEqual(output.status, ContentAgentStatus.VALIDATION_ERROR)
        self.assertTrue(any("platform_override" in reason for reason in output.errors))


class ContentAgentDurationTests(unittest.TestCase):
    """Test 20 from the P3.6 mandatory list."""

    def test_missing_duration_uses_default_with_warning(self):
        output = ContentAgent().run(_valid_input())
        self.assertEqual(output.script_artifact.total_duration_target, 30)
        self.assertTrue(any("scaffold default" in w for w in output.warnings))

    def test_explicit_duration_is_respected_without_default_warning(self):
        output = ContentAgent().run(_valid_input(duration_target_seconds=60))
        self.assertEqual(output.script_artifact.total_duration_target, 60)
        self.assertFalse(any("scaffold default" in w for w in output.warnings))
        self.assertEqual(
            sum(scene.duration for scene in output.script_artifact.scenes), 60
        )

    def test_invalid_duration_is_validation_error(self):
        output = ContentAgent().run(_valid_input(duration_target_seconds=-5))
        self.assertEqual(output.status, ContentAgentStatus.VALIDATION_ERROR)
        self.assertTrue(any("duration_target_seconds" in reason for reason in output.errors))


class ContentAgentIdempotencyTests(unittest.TestCase):
    """Test 21 from the P3.6 mandatory list."""

    def test_idempotency_key_same_input_same_key(self):
        strategy_artifact = _valid_strategy_artifact("mission-001")
        k1 = compute_content_idempotency_key(_valid_input(strategy_artifact=strategy_artifact))
        k2 = compute_content_idempotency_key(_valid_input(strategy_artifact=strategy_artifact))
        self.assertEqual(k1, k2)

    def test_idempotency_key_changes_with_different_strategy_content(self):
        # Built via a fresh StrategyAgent run (not `replace()`) so that
        # content_hash is genuinely, correctly recomputed for the new
        # objective -- the idempotency key is deliberately bound to
        # content_hash, not to raw fields, so a stale/unrecomputed hash
        # would defeat this test's purpose.
        strategy_a = _valid_strategy_artifact("mission-001")
        strategy_b_output = StrategyAgent().run(
            StrategyAgentInput(
                mission_id="mission-001",
                objective="A completely different objective about something else.",
                platforms=("tiktok", "youtube"),
            )
        )
        strategy_b = strategy_b_output.strategy_artifact
        self.assertNotEqual(strategy_a.content_hash, strategy_b.content_hash)

        k1 = compute_content_idempotency_key(_valid_input(strategy_artifact=strategy_a))
        k2 = compute_content_idempotency_key(_valid_input(strategy_artifact=strategy_b))
        self.assertNotEqual(k1, k2)


class FakeContentEngine(ContentEngine):
    """Test-only engine proving the ContentEngine contract is
    substitutable (mandatory test 22)."""

    def build_content(self, context: ContentGenerationContext) -> ContentGenerationResult:
        return ContentGenerationResult(
            concept="fake concept",
            angle="fake angle",
            hook="fake hook",
            title="fake title",
            cta="fake cta",
            scene_drafts=(
                SceneDraft("fake narration 1", "fake visual 1", "cut", "", 0.5),
                SceneDraft("fake narration 2", "fake visual 2", None, "", 0.5),
            ),
            warnings=("fake engine used",),
        )


class ContentAgentFakeEngineTests(unittest.TestCase):
    def test_fake_engine_compatibility(self):
        agent = ContentAgent(engine=FakeContentEngine())
        output = agent.run(_valid_input())

        self.assertEqual(output.status, ContentAgentStatus.READY)
        self.assertEqual(output.content_artifact.concept, "fake concept")
        self.assertEqual(len(output.script_artifact.scenes), 2)
        self.assertIn("fake engine used", output.warnings)
        self.assertEqual(output.content_artifact.producer_agent, "content-agent")

    def test_default_engine_is_deterministic_engine(self):
        agent = ContentAgent()
        self.assertIsInstance(agent.engine, DeterministicContentEngine)


class ContentAgentAuthorityBoundaryTests(unittest.TestCase):
    """Tests 23, 24 from the P3.6 mandatory list."""

    def test_no_mission_state_field_exists_on_output(self):
        output = ContentAgent().run(_valid_input())
        self.assertFalse(hasattr(output, "current_state"))
        self.assertFalse(hasattr(output.content_artifact, "current_state"))
        self.assertFalse(hasattr(output.script_artifact, "current_state"))

    def test_no_event_bus_attribute_on_agent(self):
        agent = ContentAgent()
        self.assertFalse(hasattr(agent, "event_bus"))
        self.assertFalse(hasattr(agent, "emit"))

    def test_no_authorization_object_created(self):
        output = ContentAgent().run(_valid_input())
        self.assertFalse(hasattr(output, "real_generation_authorization"))
        self.assertFalse(hasattr(output.content_artifact, "activation_id"))
        self.assertFalse(hasattr(output.script_artifact, "activation_id"))


class ContentAgentSecurityTests(unittest.TestCase):
    """
    Tests 25-30 from the P3.6 mandatory list: static (AST) verification
    that agents/content_agent.py cannot reach Higgsfield, any P2
    authority mechanism, subprocess, or networking -- checked
    structurally, never a naive substring scan (P3.5's own security
    tests hit and fixed exactly this false-positive class; the same
    AST-call-target approach is reused here).
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
        "agents.publishing_agent",
        "subprocess",
        "socket",
        "urllib",
        "http",
        "requests",
    }

    FORBIDDEN_CALL_NAMES = {"create_job", "system", "popen", "Popen"}

    @classmethod
    def setUpClass(cls):
        cls.source = CONTENT_AGENT_SOURCE_PATH.read_text(encoding="utf-8")
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

    def test_no_forbidden_module_imports(self):
        imported_modules = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module)

        offenders = imported_modules & self.FORBIDDEN_MODULES
        self.assertFalse(
            offenders,
            f"agents/content_agent.py imports forbidden module(s): {offenders}",
        )

    def test_no_forbidden_calls(self):
        offenders = self._called_names() & self.FORBIDDEN_CALL_NAMES
        self.assertFalse(
            offenders,
            f"agents/content_agent.py contains forbidden call(s): {offenders}",
        )

    def test_no_realgenerationauthorization_construction(self):
        self.assertNotIn("RealGenerationAuthorization", self._called_names())

    def test_no_activation_contract_construction(self):
        called = self._called_names()
        self.assertFalse(
            {n for n in called if "ActivationContract" in n or "ControlledRealProviderActivation" in n}
        )

    def test_no_credential_or_secret_like_tokens(self):
        lowered = self.source.lower()
        for token in ("api_key", "apikey", "password", "secret", "token=", "credential"):
            self.assertNotIn(token, lowered)

    def test_module_has_no_network_related_names_at_all(self):
        for banned_substring in ("requests.", "urllib.", "socket.", "http.client"):
            self.assertNotIn(banned_substring, self.source)


if __name__ == "__main__":
    unittest.main()
