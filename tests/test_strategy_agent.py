"""
Tests — StrategyAgent v1.0 (Phase P3.5).

Fully offline: no network, no Higgsfield, no provider of any kind is
imported or constructed anywhere in this file.
"""

import ast
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.strategy_agent import (
    AGENT_VERSION,
    ARTIFACT_TYPE,
    CONTRACT_VERSION,
    DeterministicStrategyEngine,
    StrategyAgent,
    StrategyAgentInput,
    StrategyAgentOutput,
    StrategyAgentStatus,
    StrategyArtifact,
    StrategyContent,
    StrategyEngine,
    compute_content_hash,
    compute_strategy_idempotency_key,
)

STRATEGY_AGENT_SOURCE_PATH = PROJECT_ROOT / "agents" / "strategy_agent.py"


def _valid_input(**overrides) -> StrategyAgentInput:
    defaults = dict(
        mission_id="mission-001",
        objective="Explain why discipline beats talent over time.",
        platforms=("tiktok", "youtube"),
        topic="discipline vs talent",
        audience="young adults pursuing self-improvement",
    )
    defaults.update(overrides)
    return StrategyAgentInput(**defaults)


class StrategyAgentBehaviorTests(unittest.TestCase):
    """Tests 1-6, 9-11 from the P3.5 mandatory list."""

    def test_valid_input_produces_ready_output(self):
        output = StrategyAgent().run(_valid_input())
        self.assertEqual(output.status, StrategyAgentStatus.READY)
        self.assertIsNotNone(output.strategy_artifact)
        self.assertEqual(output.errors, ())

    def test_missing_mission_id_is_validation_error(self):
        output = StrategyAgent().run(_valid_input(mission_id=""))
        self.assertEqual(output.status, StrategyAgentStatus.VALIDATION_ERROR)
        self.assertIsNone(output.strategy_artifact)
        self.assertTrue(any("mission_id" in reason for reason in output.errors))

    def test_missing_objective_is_validation_error(self):
        output = StrategyAgent().run(_valid_input(objective=""))
        self.assertEqual(output.status, StrategyAgentStatus.VALIDATION_ERROR)
        self.assertTrue(any("objective" in reason for reason in output.errors))

    def test_whitespace_only_objective_is_validation_error(self):
        output = StrategyAgent().run(_valid_input(objective="   "))
        self.assertEqual(output.status, StrategyAgentStatus.VALIDATION_ERROR)
        self.assertTrue(any("objective" in reason for reason in output.errors))

    def test_invalid_platform_is_validation_error(self):
        output = StrategyAgent().run(_valid_input(platforms=("myspace",)))
        self.assertEqual(output.status, StrategyAgentStatus.VALIDATION_ERROR)
        self.assertTrue(any("platform" in reason for reason in output.errors))

    def test_invalid_priority_is_validation_error(self):
        output = StrategyAgent().run(_valid_input(priority="ASAP"))
        self.assertEqual(output.status, StrategyAgentStatus.VALIDATION_ERROR)
        self.assertTrue(any("priority" in reason for reason in output.errors))

    def test_invalid_language_is_validation_error(self):
        output = StrategyAgent().run(_valid_input(language="klingon"))
        self.assertEqual(output.status, StrategyAgentStatus.VALIDATION_ERROR)
        self.assertTrue(any("language" in reason for reason in output.errors))

    def test_empty_platforms_is_validation_error(self):
        output = StrategyAgent().run(_valid_input(platforms=()))
        self.assertEqual(output.status, StrategyAgentStatus.VALIDATION_ERROR)
        self.assertTrue(any("platforms" in reason for reason in output.errors))

    def test_missing_audience_produces_warning_never_invented(self):
        output = StrategyAgent().run(_valid_input(audience=None))
        self.assertEqual(output.status, StrategyAgentStatus.READY)
        self.assertIsNone(output.strategy_artifact.audience)
        self.assertTrue(any("audience" in warning for warning in output.warnings))

    def test_correct_mission_id_propagation(self):
        output = StrategyAgent().run(_valid_input(mission_id="mission-xyz"))
        self.assertEqual(output.mission_id, "mission-xyz")
        self.assertEqual(output.strategy_artifact.mission_id, "mission-xyz")

    def test_correct_producer_metadata(self):
        output = StrategyAgent().run(_valid_input())
        self.assertEqual(output.producer_agent, "strategy-agent")
        self.assertEqual(output.producer_version, AGENT_VERSION)
        self.assertEqual(output.strategy_artifact.producer_agent, "strategy-agent")
        self.assertEqual(output.strategy_artifact.producer_version, AGENT_VERSION)

    def test_correct_contract_version(self):
        output = StrategyAgent().run(_valid_input())
        self.assertEqual(output.contract_version, CONTRACT_VERSION)
        self.assertEqual(output.strategy_artifact.contract_version, CONTRACT_VERSION)
        self.assertEqual(output.strategy_artifact.artifact_type, ARTIFACT_TYPE)


class StrategyAgentDeterminismTests(unittest.TestCase):
    """Tests 7, 18, 19 from the P3.5 mandatory list."""

    def test_deterministic_output_same_input_same_content(self):
        agent = StrategyAgent()
        first = agent.run(_valid_input())
        second = agent.run(_valid_input())

        # created_at and artifact_id are technical/temporal and may
        # legitimately differ between calls -- everything else,
        # including the content hash, must be identical.
        self.assertEqual(
            first.strategy_artifact.content_hash,
            second.strategy_artifact.content_hash,
        )
        self.assertEqual(
            first.strategy_artifact.content_goals,
            second.strategy_artifact.content_goals,
        )
        self.assertEqual(
            first.strategy_artifact.strategic_angles,
            second.strategy_artifact.strategic_angles,
        )
        self.assertEqual(
            first.strategy_artifact.priorities,
            second.strategy_artifact.priorities,
        )

    def test_artifact_immutability(self):
        output = StrategyAgent().run(_valid_input())
        with self.assertRaises(FrozenInstanceError):
            output.strategy_artifact.objective = "tampered"

    def test_hash_determinism_same_input_same_hash(self):
        h1 = compute_content_hash(
            mission_id="m1",
            objective="obj",
            audience="a",
            platforms=("tiktok",),
            content_goals=("g1",),
            strategic_angles=("s1",),
            priorities=("p1",),
            constraints=(),
            contract_version=1,
        )
        h2 = compute_content_hash(
            mission_id="m1",
            objective="obj",
            audience="a",
            platforms=("tiktok",),
            content_goals=("g1",),
            strategic_angles=("s1",),
            priorities=("p1",),
            constraints=(),
            contract_version=1,
        )
        self.assertEqual(h1, h2)

    def test_hash_changes_with_different_input(self):
        base = dict(
            mission_id="m1",
            objective="obj",
            audience="a",
            platforms=("tiktok",),
            content_goals=("g1",),
            strategic_angles=("s1",),
            priorities=("p1",),
            constraints=(),
            contract_version=1,
        )
        h1 = compute_content_hash(**base)
        changed = dict(base, objective="different objective")
        h2 = compute_content_hash(**changed)
        self.assertNotEqual(h1, h2)

    def test_idempotency_key_same_input_same_key(self):
        k1 = compute_strategy_idempotency_key(_valid_input())
        k2 = compute_strategy_idempotency_key(_valid_input())
        self.assertEqual(k1, k2)

    def test_idempotency_key_changes_with_different_input(self):
        k1 = compute_strategy_idempotency_key(_valid_input())
        k2 = compute_strategy_idempotency_key(_valid_input(objective="a different objective entirely"))
        self.assertNotEqual(k1, k2)


class StrategyAgentAuthorityBoundaryTests(unittest.TestCase):
    """Tests 15, 16, 17 from the P3.5 mandatory list."""

    def test_no_authorization_object_created(self):
        output = StrategyAgent().run(_valid_input())
        # The only public surface of this whole module is
        # StrategyAgentOutput/StrategyArtifact -- neither carries any
        # authorization-shaped field, and no other object is returned.
        self.assertFalse(hasattr(output, "real_generation_authorization"))
        self.assertFalse(hasattr(output.strategy_artifact, "real_generation_authorization"))
        self.assertFalse(hasattr(output.strategy_artifact, "activation_id"))

    def test_no_mission_state_field_exists_on_output(self):
        output = StrategyAgent().run(_valid_input())
        self.assertFalse(hasattr(output, "current_state"))
        self.assertFalse(hasattr(output.strategy_artifact, "current_state"))

    def test_no_event_bus_attribute_on_agent(self):
        agent = StrategyAgent()
        self.assertFalse(hasattr(agent, "event_bus"))
        self.assertFalse(hasattr(agent, "emit"))


class FakeStrategyEngine(StrategyEngine):
    """Test-only engine proving the StrategyEngine contract is
    substitutable (mandatory test 20)."""

    def build_content(self, agent_input: StrategyAgentInput) -> StrategyContent:
        return StrategyContent(
            content_goals=("fake goal",),
            strategic_angles=("fake angle",),
            priorities=("fake priority",),
            warnings=("fake engine used",),
        )


class StrategyAgentFakeEngineTests(unittest.TestCase):
    def test_fake_engine_compatibility(self):
        agent = StrategyAgent(engine=FakeStrategyEngine())
        output = agent.run(_valid_input())

        self.assertEqual(output.status, StrategyAgentStatus.READY)
        self.assertEqual(output.strategy_artifact.content_goals, ("fake goal",))
        self.assertEqual(output.strategy_artifact.strategic_angles, ("fake angle",))
        self.assertEqual(output.strategy_artifact.priorities, ("fake priority",))
        self.assertIn("fake engine used", output.warnings)
        # Even with a substituted engine, StrategyAgent (not the
        # engine) still stamps identity/versioning -- the engine never
        # gains authority over producer metadata.
        self.assertEqual(output.strategy_artifact.producer_agent, "strategy-agent")
        self.assertEqual(output.strategy_artifact.producer_version, AGENT_VERSION)

    def test_default_engine_is_deterministic_engine(self):
        agent = StrategyAgent()
        self.assertIsInstance(agent.engine, DeterministicStrategyEngine)


class StrategyAgentSecurityTests(unittest.TestCase):
    """
    Tests 12-14 and Section 21 of P3.5: static (AST) verification that
    agents/strategy_agent.py cannot reach Higgsfield, any P2 authority
    mechanism, subprocess, or networking -- checked structurally rather
    than by a naive substring scan, to avoid false positives (e.g. the
    word "provider" appearing only in a comment/docstring must not fail
    this test; an actual `import` statement is what is checked).
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
        "requests",
    }

    FORBIDDEN_CALL_NAMES = {"create_job", "system", "popen", "Popen"}

    @classmethod
    def setUpClass(cls):
        cls.source = STRATEGY_AGENT_SOURCE_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

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
            f"agents/strategy_agent.py imports forbidden module(s): {offenders}",
        )

    def test_no_forbidden_calls(self):
        call_names = set()

        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    call_names.add(func.id)
                elif isinstance(func, ast.Attribute):
                    call_names.add(func.attr)

        offenders = call_names & self.FORBIDDEN_CALL_NAMES
        self.assertFalse(
            offenders,
            f"agents/strategy_agent.py contains forbidden call(s): {offenders}",
        )

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

    def test_no_realgenerationauthorization_construction(self):
        # Checks actual CALL expressions (e.g. `RealGenerationAuthorization(...)`),
        # never a naive substring scan -- the module's own docstring
        # legitimately names this class in prose to document that it is
        # never constructed, which a substring check would misfire on.
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
        # Broader net than the import check above: catches an attempt
        # to reach the network via a dynamically-imported/aliased name.
        for banned_substring in ("requests.", "urllib.", "socket.", "http.client"):
            self.assertNotIn(banned_substring, self.source)


if __name__ == "__main__":
    unittest.main()
