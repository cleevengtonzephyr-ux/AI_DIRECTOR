"""
Tests — QualityAgent v1.0 (Phase P3.7).

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

from agents.content_agent import ContentAgent, ContentAgentInput
from agents.quality_agent import (
    AGENT_VERSION,
    CONTRACT_VERSION,
    QUALITY_ARTIFACT_TYPE,
    DeterministicQualityEngine,
    QualityAgent,
    QualityAgentInput,
    QualityAgentOutput,
    QualityAgentStatus,
    QualityEngine,
    QualityEvaluationContext,
    QualityEvaluationResult,
    QualityFindingSeverity,
    QualityProfile,
    compute_quality_artifact_hash,
    compute_quality_idempotency_key,
)
from agents.strategy_agent import StrategyAgent, StrategyAgentInput

QUALITY_AGENT_SOURCE_PATH = PROJECT_ROOT / "agents" / "quality_agent.py"


def _valid_content_and_script(mission_id="mission-001"):
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
        ContentAgentInput(
            mission_id=mission_id,
            strategy_artifact=strategy_output.strategy_artifact,
            language_override="en",
        )
    )
    assert content_output.status.value == "READY"
    return content_output.content_artifact, content_output.script_artifact


def _valid_input(**overrides):
    content_artifact, script_artifact = _valid_content_and_script("mission-001")
    defaults = dict(
        mission_id="mission-001",
        content_artifact=content_artifact,
        script_artifact=script_artifact,
    )
    defaults.update(overrides)
    return QualityAgentInput(**defaults)


class QualityAgentBehaviorTests(unittest.TestCase):
    """Tests 1-6, 19 from the P3.7 mandatory list."""

    def test_valid_input_produces_evaluated_output(self):
        output = QualityAgent().run(_valid_input())
        self.assertIn(
            output.status,
            (QualityAgentStatus.PASS, QualityAgentStatus.PASS_WITH_WARNINGS),
        )
        self.assertIsNotNone(output.quality_artifact)

    def test_missing_content_artifact_is_rejected(self):
        output = QualityAgent().run(_valid_input(content_artifact=None))
        self.assertEqual(output.status, QualityAgentStatus.REJECTED)
        self.assertIsNone(output.quality_artifact)
        self.assertTrue(any("content_artifact is missing" in reason for reason in output.errors))

    def test_missing_script_artifact_is_rejected(self):
        output = QualityAgent().run(_valid_input(script_artifact=None))
        self.assertEqual(output.status, QualityAgentStatus.REJECTED)
        self.assertTrue(any("script_artifact is missing" in reason for reason in output.errors))

    def test_wrong_mission_content_is_rejected(self):
        content_a, _ = _valid_content_and_script("mission-A")
        _, script_b = _valid_content_and_script("mission-B")
        output = QualityAgent().run(
            QualityAgentInput(mission_id="mission-B", content_artifact=content_a, script_artifact=script_b)
        )
        self.assertEqual(output.status, QualityAgentStatus.REJECTED)
        self.assertTrue(any("content_artifact.mission_id" in reason for reason in output.errors))

    def test_wrong_mission_script_is_rejected(self):
        content_a, script_a = _valid_content_and_script("mission-A")
        output = QualityAgent().run(
            QualityAgentInput(mission_id="mission-A", content_artifact=content_a, script_artifact=script_a)
        )
        # sanity: same-mission pair is fine
        self.assertNotEqual(output.status, QualityAgentStatus.REJECTED)

        _, script_other = _valid_content_and_script("mission-OTHER")
        output2 = QualityAgent().run(
            QualityAgentInput(mission_id="mission-A", content_artifact=content_a, script_artifact=script_other)
        )
        self.assertEqual(output2.status, QualityAgentStatus.REJECTED)
        self.assertTrue(any("script_artifact.mission_id" in reason for reason in output2.errors))

    def test_wrong_artifact_type_is_rejected(self):
        content_artifact, script_artifact = _valid_content_and_script("mission-001")
        tampered = replace(content_artifact, artifact_type="NotAContentArtifact")
        output = QualityAgent().run(
            _valid_input(content_artifact=tampered, script_artifact=script_artifact)
        )
        self.assertEqual(output.status, QualityAgentStatus.REJECTED)
        self.assertTrue(any("artifact_type" in reason for reason in output.errors))

    def test_rejected_input_produces_no_artifact(self):
        output = QualityAgent().run(_valid_input(content_artifact=None))
        self.assertIsNone(output.quality_artifact)


class QualityAgentIntegrityTests(unittest.TestCase):
    """Tests 7-10, 18 from the P3.7 mandatory list."""

    def test_content_integrity_valid(self):
        output = QualityAgent().run(_valid_input())
        self.assertNotEqual(output.status, QualityAgentStatus.INTEGRITY_FAILURE)

    def test_content_integrity_failure(self):
        content_artifact, script_artifact = _valid_content_and_script("mission-001")
        tampered = replace(content_artifact, hook="a tampered hook never validated")
        output = QualityAgent().run(
            _valid_input(content_artifact=tampered, script_artifact=script_artifact)
        )
        self.assertEqual(output.status, QualityAgentStatus.INTEGRITY_FAILURE)
        self.assertIsNotNone(output.quality_artifact)
        self.assertIsNone(output.quality_artifact.score)
        self.assertTrue(
            any(f.code == "CONTENT_ARTIFACT_HASH_MISMATCH" for f in output.quality_artifact.findings)
        )

    def test_script_integrity_valid(self):
        output = QualityAgent().run(_valid_input())
        self.assertNotEqual(output.status, QualityAgentStatus.INTEGRITY_FAILURE)

    def test_script_integrity_failure(self):
        content_artifact, script_artifact = _valid_content_and_script("mission-001")
        tampered = replace(script_artifact, total_duration_target=999999)
        output = QualityAgent().run(
            _valid_input(content_artifact=content_artifact, script_artifact=tampered)
        )
        self.assertEqual(output.status, QualityAgentStatus.INTEGRITY_FAILURE)
        self.assertTrue(
            any(f.code == "SCRIPT_ARTIFACT_HASH_MISMATCH" for f in output.quality_artifact.findings)
        )

    def test_integrity_failure_status(self):
        content_artifact, script_artifact = _valid_content_and_script("mission-001")
        tampered = replace(content_artifact, title="tampered title")
        output = QualityAgent().run(
            _valid_input(content_artifact=tampered, script_artifact=script_artifact)
        )
        self.assertEqual(output.quality_artifact.quality_status, QualityAgentStatus.INTEGRITY_FAILURE)


class QualityAgentDeterminismTests(unittest.TestCase):
    """Tests 11-14 from the P3.7 mandatory list."""

    def test_deterministic_evaluation(self):
        content_artifact, script_artifact = _valid_content_and_script("mission-001")
        agent = QualityAgent()
        first = agent.run(_valid_input(content_artifact=content_artifact, script_artifact=script_artifact))
        second = agent.run(_valid_input(content_artifact=content_artifact, script_artifact=script_artifact))
        self.assertEqual(first.status, second.status)
        self.assertEqual(first.quality_artifact.score, second.quality_artifact.score)

    def test_deterministic_findings(self):
        content_artifact, script_artifact = _valid_content_and_script("mission-001")
        agent = QualityAgent()
        first = agent.run(_valid_input(content_artifact=content_artifact, script_artifact=script_artifact))
        second = agent.run(_valid_input(content_artifact=content_artifact, script_artifact=script_artifact))
        self.assertEqual(
            [(f.finding_id, f.code) for f in first.quality_artifact.findings],
            [(f.finding_id, f.code) for f in second.quality_artifact.findings],
        )

    def test_deterministic_score(self):
        content_artifact, script_artifact = _valid_content_and_script("mission-001")
        agent = QualityAgent()
        first = agent.run(_valid_input(content_artifact=content_artifact, script_artifact=script_artifact))
        second = agent.run(_valid_input(content_artifact=content_artifact, script_artifact=script_artifact))
        self.assertEqual(first.quality_artifact.score, second.quality_artifact.score)

    def test_deterministic_quality_artifact_hash(self):
        content_artifact, script_artifact = _valid_content_and_script("mission-001")
        agent = QualityAgent()
        first = agent.run(_valid_input(content_artifact=content_artifact, script_artifact=script_artifact))
        second = agent.run(_valid_input(content_artifact=content_artifact, script_artifact=script_artifact))
        self.assertEqual(first.quality_artifact.content_hash, second.quality_artifact.content_hash)


class QualityAgentStatusTests(unittest.TestCase):
    """Tests 15-17 from the P3.7 mandatory list."""

    def test_quality_status_pass(self):
        output = QualityAgent().run(_valid_input())
        # The DeterministicContentEngine's default output should be fully
        # complete/coherent -- a clean PASS with zero non-INFO findings.
        self.assertEqual(output.status, QualityAgentStatus.PASS)
        self.assertEqual(output.quality_artifact.score, 100)

    def test_pass_with_warnings(self):
        content_artifact, script_artifact = _valid_content_and_script("mission-001")
        # Force exactly one WARNING-severity finding: an unrecognized tone.
        # Tampering content_artifact changes its content_hash, which in turn
        # invalidates script_artifact's binding to it (source_content_
        # content_hash) -- both hashes must be rebuilt for this to reach
        # DeterministicQualityEngine rather than being caught (correctly)
        # as an INTEGRITY_FAILURE first.
        from agents.content_agent import compute_content_artifact_hash, compute_script_artifact_hash

        tampered_content = replace(content_artifact, tone="sarcastic_unlisted_tone")
        new_content_hash = compute_content_artifact_hash(
            mission_id=tampered_content.mission_id,
            concept=tampered_content.concept,
            angle=tampered_content.angle,
            hook=tampered_content.hook,
            title=tampered_content.title,
            cta=tampered_content.cta,
            target_platforms=tampered_content.target_platforms,
            language=tampered_content.language,
            tone=tampered_content.tone,
            content_format=tampered_content.content_format,
            constraints=tampered_content.constraints,
            contract_version=tampered_content.contract_version,
            source_strategy_content_hash=tampered_content.source_strategy_content_hash,
        )
        tampered_content = replace(tampered_content, content_hash=new_content_hash)

        new_script_hash = compute_script_artifact_hash(
            mission_id=script_artifact.mission_id,
            scenes=script_artifact.scenes,
            total_duration_target=script_artifact.total_duration_target,
            language=script_artifact.language,
            contract_version=script_artifact.contract_version,
            source_content_content_hash=tampered_content.content_hash,
        )
        rebound_script = replace(script_artifact, content_hash=new_script_hash)

        output = QualityAgent().run(
            _valid_input(content_artifact=tampered_content, script_artifact=rebound_script)
        )
        self.assertEqual(output.status, QualityAgentStatus.PASS_WITH_WARNINGS)
        self.assertTrue(any(f.code == "INVALID_CONTENT_TONE" for f in output.quality_artifact.findings))

    def test_fail_status_on_critical_finding(self):
        content_artifact, script_artifact = _valid_content_and_script("mission-001")
        empty_script = replace(script_artifact, scenes=())
        from agents.content_agent import compute_script_artifact_hash

        new_hash = compute_script_artifact_hash(
            mission_id=empty_script.mission_id,
            scenes=(),
            total_duration_target=empty_script.total_duration_target,
            language=empty_script.language,
            contract_version=empty_script.contract_version,
            source_content_content_hash=content_artifact.content_hash,
        )
        empty_script = replace(empty_script, content_hash=new_hash)

        output = QualityAgent().run(
            _valid_input(content_artifact=content_artifact, script_artifact=empty_script)
        )
        self.assertEqual(output.status, QualityAgentStatus.FAIL)
        self.assertTrue(any(f.code == "EMPTY_SCRIPT" for f in output.quality_artifact.findings))


class QualityAgentValidationTests(unittest.TestCase):
    """Tests 20-25 from the P3.7 mandatory list."""

    def test_content_completeness(self):
        content_artifact, script_artifact = _valid_content_and_script("mission-001")
        from agents.content_agent import compute_content_artifact_hash, compute_script_artifact_hash

        tampered = replace(content_artifact, title="")
        new_content_hash = compute_content_artifact_hash(
            mission_id=tampered.mission_id,
            concept=tampered.concept,
            angle=tampered.angle,
            hook=tampered.hook,
            title=tampered.title,
            cta=tampered.cta,
            target_platforms=tampered.target_platforms,
            language=tampered.language,
            tone=tampered.tone,
            content_format=tampered.content_format,
            constraints=tampered.constraints,
            contract_version=tampered.contract_version,
            source_strategy_content_hash=tampered.source_strategy_content_hash,
        )
        tampered = replace(tampered, content_hash=new_content_hash)

        new_script_hash = compute_script_artifact_hash(
            mission_id=script_artifact.mission_id,
            scenes=script_artifact.scenes,
            total_duration_target=script_artifact.total_duration_target,
            language=script_artifact.language,
            contract_version=script_artifact.contract_version,
            source_content_content_hash=tampered.content_hash,
        )
        rebound_script = replace(script_artifact, content_hash=new_script_hash)

        output = QualityAgent().run(
            _valid_input(content_artifact=tampered, script_artifact=rebound_script)
        )
        self.assertTrue(any(f.code == "MISSING_TITLE" for f in output.quality_artifact.findings))

    def test_script_structure_valid(self):
        output = QualityAgent().run(_valid_input())
        structure_findings = [f for f in output.quality_artifact.findings if f.category == "structure"]
        self.assertEqual(structure_findings, [])

    def test_scene_order_valid(self):
        _, script_artifact = _valid_content_and_script("mission-001")
        self.assertEqual([s.order for s in script_artifact.scenes], [1, 2, 3])

    def test_duration_validation(self):
        output = QualityAgent().run(_valid_input(quality_profile=QualityProfile(max_duration_variance_seconds=0)))
        duration_findings = [
            f for f in output.quality_artifact.findings if f.code == "DURATION_SUM_MISMATCH"
        ]
        self.assertEqual(duration_findings, [])

    def test_language_consistency(self):
        content_artifact, script_artifact = _valid_content_and_script("mission-001")
        self.assertEqual(content_artifact.language, script_artifact.language)
        output = QualityAgent().run(_valid_input(content_artifact=content_artifact, script_artifact=script_artifact))
        self.assertFalse(any(f.code == "LANGUAGE_MISMATCH" for f in output.quality_artifact.findings))

    def test_platform_alignment(self):
        output = QualityAgent().run(_valid_input())
        self.assertFalse(any(f.code == "UNSUPPORTED_PLATFORM" for f in output.quality_artifact.findings))

    def test_content_script_coherence(self):
        output = QualityAgent().run(_valid_input())
        self.assertFalse(any(f.code == "HOOK_SCENE_MISMATCH" for f in output.quality_artifact.findings))
        self.assertFalse(any(f.code == "CTA_SCENE_MISMATCH" for f in output.quality_artifact.findings))


class FakeQualityEngine(QualityEngine):
    """Test-only engine proving the QualityEngine contract is
    substitutable (mandatory tests 27/28)."""

    def evaluate(self, context: QualityEvaluationContext) -> QualityEvaluationResult:
        from agents.quality_agent import Finding

        return QualityEvaluationResult(
            findings=(
                Finding(
                    finding_id="finding-001",
                    severity=QualityFindingSeverity.INFO,
                    category="completeness",
                    code="FAKE_FINDING",
                    message="fake engine used",
                    artifact_reference=context.content_artifact.artifact_id,
                ),
            )
        )


class QualityAgentEngineTests(unittest.TestCase):
    """Tests 27, 28 from the P3.7 mandatory list."""

    def test_fake_engine_compatibility(self):
        agent = QualityAgent(engine=FakeQualityEngine())
        output = agent.run(_valid_input())
        self.assertEqual(output.status, QualityAgentStatus.PASS)
        self.assertEqual(len(output.quality_artifact.findings), 1)
        self.assertEqual(output.quality_artifact.findings[0].code, "FAKE_FINDING")

    def test_default_engine_is_deterministic_engine(self):
        agent = QualityAgent()
        self.assertIsInstance(agent.engine, DeterministicQualityEngine)


class QualityAgentImmutabilityTests(unittest.TestCase):
    """Tests 29-31 (partially), 18 from the P3.7 mandatory list."""

    def test_immutable_inputs_not_mutated(self):
        content_artifact, script_artifact = _valid_content_and_script("mission-001")
        content_before = replace(content_artifact)
        script_before = replace(script_artifact)

        QualityAgent().run(
            _valid_input(content_artifact=content_artifact, script_artifact=script_artifact)
        )

        self.assertEqual(content_artifact, content_before)
        self.assertEqual(script_artifact, script_before)

    def test_immutable_output(self):
        output = QualityAgent().run(_valid_input())
        with self.assertRaises(FrozenInstanceError):
            output.quality_artifact.score = 0
        with self.assertRaises(FrozenInstanceError):
            output.quality_artifact.findings[0].message = "tampered" if output.quality_artifact.findings else None


class QualityAgentMetadataTests(unittest.TestCase):
    """Tests 31-33 from the P3.7 mandatory list."""

    def test_version_metadata(self):
        output = QualityAgent().run(_valid_input())
        self.assertEqual(output.quality_artifact.artifact_type, QUALITY_ARTIFACT_TYPE)
        self.assertEqual(output.quality_artifact.version, 1)

    def test_producer_metadata(self):
        output = QualityAgent().run(_valid_input())
        self.assertEqual(output.producer_agent, "quality-agent")
        self.assertEqual(output.producer_version, AGENT_VERSION)
        self.assertEqual(output.quality_artifact.producer_agent, "quality-agent")

    def test_contract_version(self):
        output = QualityAgent().run(_valid_input())
        self.assertEqual(output.contract_version, CONTRACT_VERSION)
        self.assertEqual(output.quality_artifact.contract_version, CONTRACT_VERSION)


class QualityAgentIdempotencyTests(unittest.TestCase):
    """Tests 34, 35 from the P3.7 mandatory list."""

    def test_idempotency_same_input(self):
        content_artifact, script_artifact = _valid_content_and_script("mission-001")
        k1 = compute_quality_idempotency_key(
            _valid_input(content_artifact=content_artifact, script_artifact=script_artifact)
        )
        k2 = compute_quality_idempotency_key(
            _valid_input(content_artifact=content_artifact, script_artifact=script_artifact)
        )
        self.assertEqual(k1, k2)

    def test_idempotency_changed_input(self):
        content_a, script_a = _valid_content_and_script("mission-001")
        strategy_output_b = StrategyAgent().run(
            StrategyAgentInput(
                mission_id="mission-001",
                objective="A completely different objective entirely.",
                platforms=("tiktok", "youtube"),
            )
        )
        content_output_b = ContentAgent().run(
            ContentAgentInput(mission_id="mission-001", strategy_artifact=strategy_output_b.strategy_artifact)
        )
        k1 = compute_quality_idempotency_key(
            _valid_input(content_artifact=content_a, script_artifact=script_a)
        )
        k2 = compute_quality_idempotency_key(
            _valid_input(
                content_artifact=content_output_b.content_artifact,
                script_artifact=content_output_b.script_artifact,
            )
        )
        self.assertNotEqual(k1, k2)


class QualityAgentAuthorityBoundaryTests(unittest.TestCase):
    """Tests 36, 37 from the P3.7 mandatory list."""

    def test_mission_state_unchanged(self):
        output = QualityAgent().run(_valid_input())
        self.assertFalse(hasattr(output, "current_state"))
        self.assertFalse(hasattr(output.quality_artifact, "current_state"))

    def test_no_event_bus(self):
        agent = QualityAgent()
        self.assertFalse(hasattr(agent, "event_bus"))
        self.assertFalse(hasattr(agent, "emit"))
        self.assertFalse(hasattr(agent, "publish"))
        self.assertFalse(hasattr(agent, "subscribe"))


class QualityAgentSecurityTests(unittest.TestCase):
    """
    Tests 38-43 from the P3.7 mandatory list: static (AST) verification
    that agents/quality_agent.py cannot reach Higgsfield, any P2
    authority mechanism, subprocess, os.system, or networking -- checked
    structurally, never a naive substring scan.
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
        "os",
    }

    FORBIDDEN_CALL_NAMES = {"create_job", "system", "popen", "Popen"}

    @classmethod
    def setUpClass(cls):
        cls.source = QUALITY_AGENT_SOURCE_PATH.read_text(encoding="utf-8")
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
            f"agents/quality_agent.py imports forbidden module(s): {offenders}",
        )

    def test_no_create_job_call(self):
        self.assertNotIn("create_job", self._called_names())

    def test_no_forbidden_calls(self):
        offenders = self._called_names() & self.FORBIDDEN_CALL_NAMES
        self.assertFalse(
            offenders,
            f"agents/quality_agent.py contains forbidden call(s): {offenders}",
        )

    def test_no_authorization_construction(self):
        self.assertNotIn("RealGenerationAuthorization", self._called_names())

    def test_no_activation_construction(self):
        called = self._called_names()
        self.assertFalse(
            {n for n in called if "ActivationContract" in n or "ControlledRealProviderActivation" in n}
        )

    def test_no_network_or_subprocess(self):
        for banned_substring in ("requests.", "urllib.", "socket.", "http.client", "subprocess.", "os.system"):
            self.assertNotIn(banned_substring, self.source)

    def test_no_provider_dependency(self):
        self.assertNotIn("HiggsfieldProvider", self.source)
        self.assertNotIn("HiggsfieldClient", self.source)


if __name__ == "__main__":
    unittest.main()
