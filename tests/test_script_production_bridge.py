"""
Tests — Script -> Production Bridge (Phase P3.13).

Fully offline: no network, no Higgsfield, no social platform, no OAuth,
no credential of any kind is imported or constructed anywhere in this
file.
"""

import ast
import sys
import unittest
from dataclasses import replace as dc_replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.content_agent import ContentAgent, ContentAgentInput, Scene as ContentScene, ScriptArtifact
from agents.production_model import PRODUCTION_MODEL
from agents.script_production_bridge import (
    ProductionPreparationInput,
    ProductionPreparationNotReadyError,
    ProductionPreparationRequest,
    ProductionPreparationStatus,
    ScriptProductionBridge,
    compute_preparation_hash,
)
from agents.strategy_agent import StrategyAgent, StrategyAgentInput
from director import AIDirector

BRIDGE_SOURCE_PATH = PROJECT_ROOT / "agents" / "script_production_bridge.py"


def _real_script_artifact(mission_id: str = "mission-001", **overrides) -> ScriptArtifact:
    strategy = StrategyAgent().run(
        StrategyAgentInput(
            mission_id=mission_id,
            objective="Explain why discipline beats talent over time.",
            platforms=("tiktok", "youtube"),
            topic="discipline vs talent",
            audience="young adults",
        )
    )
    content = ContentAgent().run(
        ContentAgentInput(mission_id=mission_id, strategy_artifact=strategy.strategy_artifact)
    )
    script = content.script_artifact
    if overrides:
        script = dc_replace(script, **overrides)
    return script


class _FakePromptAssembly:
    def __init__(self, prompts=None, error=None):
        self._prompts = prompts or {}
        self._error = error
        self.calls = []

    def assemble(self, video_id):
        self.calls.append(video_id)
        if self._error is not None:
            raise self._error
        return self._prompts.get(video_id, f"assembled-prompt-for-{video_id}")


class _FakeAsset:
    def __init__(self, role, path, sha256, status="READY"):
        self.role = role
        self.path = path
        self.sha256 = sha256
        self.status = status


class _FakeAssetPreparation:
    def __init__(self, assets):
        self._assets = assets
        self.scan_calls = 0

    def scan(self):
        self.scan_calls += 1
        return list(self._assets)


class BridgeHappyPathTests(unittest.TestCase):
    """Tests 1-9 from the P3.13 mandatory list."""

    def test_valid_script_artifact_produces_incomplete_without_prompt(self):
        script = _real_script_artifact()
        bridge = ScriptProductionBridge()
        prepared = bridge.prepare(ProductionPreparationInput(mission_id="mission-001", script_artifact=script))
        self.assertEqual(prepared.status, ProductionPreparationStatus.INCOMPLETE)
        self.assertEqual(prepared.reasons, ())

    def test_mission_id_propagation(self):
        script = _real_script_artifact(mission_id="mission-xyz")
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(mission_id="mission-xyz", script_artifact=script, prompt="p")
        )
        self.assertEqual(prepared.mission_id, "mission-xyz")

    def test_script_artifact_identity_preserved(self):
        script = _real_script_artifact()
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=script, prompt="p")
        )
        self.assertIs(prepared.script_artifact, script)
        self.assertEqual(prepared.script_artifact.artifact_id, script.artifact_id)

    def test_script_hash_preserved_not_recomputed(self):
        script = _real_script_artifact()
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=script, prompt="p")
        )
        self.assertEqual(prepared.script_artifact.content_hash, script.content_hash)

    def test_metadata_propagation(self):
        script = _real_script_artifact()
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(
                mission_id="mission-001", script_artifact=script, prompt="p",
                job_type="custom_model", resolution="1080p", aspect_ratio="16:9",
            )
        )
        self.assertEqual(prepared.job_type, "custom_model")
        self.assertEqual(prepared.resolution, "1080p")
        self.assertEqual(prepared.aspect_ratio, "16:9")
        self.assertEqual(prepared.duration_seconds, script.total_duration_target)

    def test_default_job_type_reuses_production_model_constant(self):
        script = _real_script_artifact()
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=script, prompt="p")
        )
        self.assertEqual(prepared.job_type, PRODUCTION_MODEL)

    def test_prompt_provenance_explicit(self):
        script = _real_script_artifact()
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(
                mission_id="mission-001", script_artifact=script,
                prompt="explicit prompt text", prompt_source="unit-test",
            )
        )
        self.assertEqual(prepared.prompt, "explicit prompt text")
        self.assertEqual(prepared.prompt_source, "unit-test")

    def test_prompt_provenance_via_delegation(self):
        script = _real_script_artifact()
        fake_prompt_assembly = _FakePromptAssembly(prompts={"005": "delegated master prompt"})
        bridge = ScriptProductionBridge(prompt_assembly=fake_prompt_assembly)
        prepared = bridge.prepare(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=script, video_id="005")
        )
        self.assertEqual(prepared.prompt, "delegated master prompt")
        self.assertEqual(prepared.prompt_source, "PromptAssemblySystem:005")
        self.assertEqual(fake_prompt_assembly.calls, ["005"])
        self.assertEqual(prepared.status, ProductionPreparationStatus.READY)

    def test_explicit_prompt_wins_over_delegation(self):
        script = _real_script_artifact()
        fake_prompt_assembly = _FakePromptAssembly(prompts={"005": "delegated"})
        bridge = ScriptProductionBridge(prompt_assembly=fake_prompt_assembly)
        prepared = bridge.prepare(
            ProductionPreparationInput(
                mission_id="mission-001", script_artifact=script,
                video_id="005", prompt="explicit wins",
            )
        )
        self.assertEqual(prepared.prompt, "explicit wins")
        self.assertEqual(fake_prompt_assembly.calls, [])

    def test_asset_provenance(self):
        script = _real_script_artifact()
        assets = [
            _FakeAsset("master_avatar", "/assets/avatar.png", "sha-avatar"),
            _FakeAsset("face_reference", "/assets/face.png", "sha-face"),
            _FakeAsset("background_music", "/assets/music.mp3", "sha-music"),  # not transmitted
            _FakeAsset("master_avatar", "/assets/bad.png", "sha-bad", status="INVALID_EXTENSION"),
        ]
        bridge = ScriptProductionBridge(asset_preparation=_FakeAssetPreparation(assets))
        prepared = bridge.prepare(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=script, prompt="p")
        )
        roles = {ref.role for ref in prepared.asset_references}
        self.assertEqual(roles, {"master_avatar", "face_reference"})
        self.assertEqual(len(prepared.asset_references), 2)

    def test_asset_hash_preservation(self):
        script = _real_script_artifact()
        assets = [_FakeAsset("master_avatar", "/assets/avatar.png", "sha-avatar-exact")]
        bridge = ScriptProductionBridge(asset_preparation=_FakeAssetPreparation(assets))
        prepared = bridge.prepare(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=script, prompt="p")
        )
        self.assertEqual(prepared.asset_references[0].sha256, "sha-avatar-exact")

    def test_video_agent_input_construction(self):
        script = _real_script_artifact()
        bridge = ScriptProductionBridge()
        prepared = bridge.prepare(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=script, prompt="hello", job_type="m1")
        )
        kwargs = bridge.build_video_agent_kwargs(prepared)
        self.assertEqual(kwargs, {"prompt": "hello", "job_type": "m1"})


class BridgeDeterminismTests(unittest.TestCase):
    """Tests 10-11 from the P3.13 mandatory list."""

    def test_deterministic_translation(self):
        script = _real_script_artifact()
        clock = iter(["t1", "t2"])
        bridge = ScriptProductionBridge()
        req = ProductionPreparationInput(
            mission_id="mission-001", script_artifact=script, prompt="p", clock=lambda: next(clock)
        )
        first = bridge.prepare(req)
        second = bridge.prepare(req)
        self.assertEqual(first.content_hash, second.content_hash)
        # preparation_id/created_at are technical/temporal -- allowed to vary.
        self.assertNotEqual(first.preparation_id, second.preparation_id)
        self.assertEqual(first.created_at, "t1")
        self.assertEqual(second.created_at, "t2")

    def test_immutability(self):
        script = _real_script_artifact()
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=script, prompt="p")
        )
        from dataclasses import FrozenInstanceError

        with self.assertRaises(FrozenInstanceError):
            prepared.prompt = "tampered"  # type: ignore


class BridgeFailureHandlingTests(unittest.TestCase):
    """Tests 12-17 from the P3.13 mandatory list."""

    def test_invalid_script_missing(self):
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=None)  # type: ignore
        )
        self.assertEqual(prepared.status, ProductionPreparationStatus.BLOCKED)
        self.assertTrue(any("missing" in r for r in prepared.reasons))
        self.assertIsNone(prepared.script_artifact)

    def test_invalid_script_wrong_mission(self):
        script = _real_script_artifact(mission_id="mission-A")
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(mission_id="mission-B", script_artifact=script)
        )
        self.assertEqual(prepared.status, ProductionPreparationStatus.BLOCKED)
        self.assertTrue(any("does not match" in r for r in prepared.reasons))

    def test_invalid_script_wrong_status(self):
        script = _real_script_artifact(status="DRAFT")
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=script)
        )
        self.assertEqual(prepared.status, ProductionPreparationStatus.BLOCKED)
        self.assertTrue(any("'FINAL'" in r for r in prepared.reasons))

    def test_invalid_script_empty_scenes(self):
        script = _real_script_artifact(scenes=())
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=script)
        )
        self.assertEqual(prepared.status, ProductionPreparationStatus.BLOCKED)
        self.assertTrue(any("scenes is empty" in r for r in prepared.reasons))

    def test_missing_mission_id(self):
        script = _real_script_artifact()
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(mission_id="", script_artifact=script)
        )
        self.assertEqual(prepared.status, ProductionPreparationStatus.BLOCKED)
        self.assertTrue(any("mission_id is missing" in r for r in prepared.reasons))

    def test_missing_prompt_yields_incomplete_not_blocked(self):
        script = _real_script_artifact()
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=script)
        )
        self.assertEqual(prepared.status, ProductionPreparationStatus.INCOMPLETE)
        self.assertEqual(prepared.reasons, ())
        self.assertTrue(prepared.missing_requirements)

    def test_invalid_prompt_input_blank(self):
        script = _real_script_artifact()
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=script, prompt="   ")
        )
        self.assertEqual(prepared.status, ProductionPreparationStatus.INCOMPLETE)
        self.assertIsNone(prepared.prompt)

    def test_prompt_delegation_failure_is_explicit(self):
        script = _real_script_artifact()
        fake_prompt_assembly = _FakePromptAssembly(error=FileNotFoundError("prompt file missing"))
        bridge = ScriptProductionBridge(prompt_assembly=fake_prompt_assembly)
        prepared = bridge.prepare(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=script, video_id="999")
        )
        self.assertEqual(prepared.status, ProductionPreparationStatus.INCOMPLETE)
        self.assertTrue(any("delegation failed" in m for m in prepared.missing_requirements))

    def test_invalid_video_agent_input_raises_explicitly(self):
        script = _real_script_artifact()
        bridge = ScriptProductionBridge()
        prepared = bridge.prepare(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=script)  # no prompt -> INCOMPLETE
        )
        with self.assertRaises(ProductionPreparationNotReadyError):
            bridge.build_video_agent_kwargs(prepared)


class BridgeNoFabricationTests(unittest.TestCase):
    """Test 18 from the P3.13 mandatory list."""

    def test_no_fallback_fabrication_for_resolution_aspect_ratio(self):
        script = _real_script_artifact()
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=script, prompt="p")
        )
        self.assertIsNone(prepared.resolution)
        self.assertIsNone(prepared.aspect_ratio)

    def test_no_assets_supplied_means_empty_not_fabricated(self):
        script = _real_script_artifact()
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=script, prompt="p")
        )
        self.assertEqual(prepared.asset_references, ())


class BridgeAuthorityTests(unittest.TestCase):
    """Tests 19-21 from the P3.13 mandatory list."""

    def test_no_state_authority(self):
        script = _real_script_artifact()
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=script, prompt="p")
        )
        self.assertFalse(hasattr(prepared, "mission_state"))
        self.assertFalse(hasattr(ScriptProductionBridge(), "transition"))
        self.assertFalse(hasattr(ScriptProductionBridge(), "state_machine"))

    def test_no_human_authorization(self):
        script = _real_script_artifact()
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=script, prompt="p")
        )
        self.assertFalse(hasattr(prepared, "real_generation_authorization"))
        self.assertFalse(hasattr(prepared, "human_authorization"))

    def test_no_activation_contract(self):
        script = _real_script_artifact()
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=script, prompt="p")
        )
        self.assertFalse(hasattr(prepared, "activation_contract"))
        self.assertFalse(hasattr(prepared, "provider_activation_contract"))


class BridgeTraceabilityTests(unittest.TestCase):
    """Test 28 from the P3.13 mandatory list."""

    def test_traceability_fields_present(self):
        script = _real_script_artifact()
        assets = [_FakeAsset("master_avatar", "/assets/avatar.png", "sha-avatar")]
        bridge = ScriptProductionBridge(asset_preparation=_FakeAssetPreparation(assets))
        prepared = bridge.prepare(
            ProductionPreparationInput(
                mission_id="mission-001", script_artifact=script, prompt="p",
                prompt_source="unit-test", job_type="m1",
            )
        )
        self.assertEqual(prepared.mission_id, "mission-001")
        self.assertEqual(prepared.script_artifact.artifact_id, script.artifact_id)
        self.assertEqual(prepared.script_artifact.version, script.version)
        self.assertEqual(len(prepared.asset_references), 1)
        self.assertEqual(prepared.prompt_source, "unit-test")
        self.assertEqual(prepared.job_type, "m1")
        self.assertTrue(prepared.duration_seconds)
        self.assertTrue(prepared.content_hash)


class BridgeIdempotencyTests(unittest.TestCase):
    """Test 29 from the P3.13 mandatory list."""

    def test_idempotency_hash_stable_for_same_inputs(self):
        script = _real_script_artifact()
        h1 = compute_preparation_hash(
            mission_id="m1", script_artifact_id="a1", script_content_hash="c1",
            status="READY", reasons=(), missing_requirements=(),
            job_type="jt", duration_seconds=30, resolution=None, aspect_ratio=None,
            prompt="p", prompt_source="src", asset_sha256s=(), contract_version=1,
        )
        h2 = compute_preparation_hash(
            mission_id="m1", script_artifact_id="a1", script_content_hash="c1",
            status="READY", reasons=(), missing_requirements=(),
            job_type="jt", duration_seconds=30, resolution=None, aspect_ratio=None,
            prompt="p", prompt_source="src", asset_sha256s=(), contract_version=1,
        )
        self.assertEqual(h1, h2)

    def test_idempotency_hash_changes_with_different_content(self):
        h1 = compute_preparation_hash(
            mission_id="m1", script_artifact_id="a1", script_content_hash="c1",
            status="READY", reasons=(), missing_requirements=(),
            job_type="jt", duration_seconds=30, resolution=None, aspect_ratio=None,
            prompt="p", prompt_source="src", asset_sha256s=(), contract_version=1,
        )
        h2 = compute_preparation_hash(
            mission_id="m1", script_artifact_id="a1", script_content_hash="c1",
            status="READY", reasons=(), missing_requirements=(),
            job_type="jt", duration_seconds=30, resolution=None, aspect_ratio=None,
            prompt="different prompt", prompt_source="src", asset_sha256s=(), contract_version=1,
        )
        self.assertNotEqual(h1, h2)


class BridgeDependencyInjectionTests(unittest.TestCase):
    """Test 27 from the P3.13 mandatory list."""

    def test_prompt_assembly_and_asset_preparation_are_injectable(self):
        fake_prompt_assembly = _FakePromptAssembly()
        fake_assets = _FakeAssetPreparation([])
        bridge = ScriptProductionBridge(prompt_assembly=fake_prompt_assembly, asset_preparation=fake_assets)
        self.assertIs(bridge.prompt_assembly, fake_prompt_assembly)
        self.assertIs(bridge.asset_preparation, fake_assets)

    def test_bridge_without_injection_still_translates_identity(self):
        script = _real_script_artifact()
        bridge = ScriptProductionBridge()
        prepared = bridge.prepare(ProductionPreparationInput(mission_id="mission-001", script_artifact=script))
        self.assertIsNotNone(prepared.script_artifact)


class DirectorIntegrationTests(unittest.TestCase):
    """Test 30 from the P3.13 mandatory list -- Director ownership,
    P3.13 Section 15: the bridge itself never orchestrates agents."""

    def test_director_exposes_prepare_production_from_script(self):
        director = AIDirector()
        self.assertTrue(hasattr(director, "prepare_production_from_script"))

    def test_director_delegates_to_injected_bridge(self):
        script = _real_script_artifact()
        fake_prompt_assembly = _FakePromptAssembly(prompts={"005": "director-delegated-prompt"})
        bridge = ScriptProductionBridge(prompt_assembly=fake_prompt_assembly)
        director = AIDirector()
        prepared = director.prepare_production_from_script(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=script, video_id="005"),
            bridge=bridge,
        )
        self.assertIsInstance(prepared, ProductionPreparationRequest)
        self.assertEqual(prepared.prompt, "director-delegated-prompt")

    def test_director_default_bridge_used_without_injection(self):
        script = _real_script_artifact()
        director = AIDirector()
        prepared = director.prepare_production_from_script(
            ProductionPreparationInput(mission_id="mission-001", script_artifact=script, prompt="explicit")
        )
        self.assertEqual(prepared.status, ProductionPreparationStatus.READY)

    def test_existing_methods_unaffected(self):
        director = AIDirector()
        self.assertTrue(hasattr(director, "run_business_pipeline"))
        self.assertTrue(hasattr(director, "run_video_mission"))


class BridgeSecurityTests(unittest.TestCase):
    """
    Tests 22-26 from the P3.13 mandatory list: AST-based, docstring-
    false-positive-safe (P3.5-P3.12 lesson), static verification that
    `agents/script_production_bridge.py` cannot reach Higgsfield, any P2
    authority mechanism, the Mission State Machine, or an event bus.
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
        "agents.mission_state_machine",
        "director",
        "subprocess",
        "socket",
        "urllib",
        "http",
        "requests",
        "aiohttp",
        "httpx",
        "os",
        "oauthlib",
    }

    FORBIDDEN_CALL_NAMES = {
        "create_job", "system", "popen", "Popen", "transition",
        "RealGenerationAuthorization", "RequestScopedActivationContract",
        "ControlledRealProviderActivationContract",
    }

    @classmethod
    def setUpClass(cls):
        cls.source = BRIDGE_SOURCE_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

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
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                texts.append(node.name)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) not in docstring_nodes:
                    texts.append(node.value)
        return texts

    def test_no_forbidden_module_imports(self):
        offenders = self._imported_modules() & self.FORBIDDEN_MODULES
        self.assertFalse(offenders, f"script_production_bridge.py imports forbidden module(s): {offenders}")

    def test_no_forbidden_calls(self):
        offenders = self._called_names() & self.FORBIDDEN_CALL_NAMES
        self.assertFalse(offenders, f"script_production_bridge.py contains forbidden call(s): {offenders}")

    def test_no_create_job_call(self):
        self.assertNotIn("create_job", self._called_names())

    def test_no_provider_dependency_outside_docstrings(self):
        texts = self._non_docstring_identifiers_and_literals()
        self.assertNotIn("HiggsfieldProvider", texts)
        self.assertNotIn("HiggsfieldClient", texts)

    def test_no_network_related_substrings(self):
        for banned_substring in ("requests.", "urllib.", "socket.", "http.client", "subprocess.", "os.system", "aiohttp.", "httpx."):
            self.assertNotIn(banned_substring, self.source)

    def test_no_credential_oauth_tokens(self):
        lowered = self.source.lower()
        for token in ("api_key", "apikey", "oauth", "credential", "access_token", "bearer", "password"):
            self.assertNotIn(token, lowered)

    def test_no_event_bus(self):
        suspicious = {name for name in self._called_names() if "emit" in name.lower() or "subscribe" in name.lower()}
        self.assertFalse(suspicious)
        self.assertNotIn("EventBus", self._non_docstring_identifiers_and_literals())

    def test_no_state_machine_transition_call(self):
        # P3.12 Section 14/30 restated: the bridge never calls .transition().
        self.assertNotIn("transition", self._called_names())

    def test_no_dataclasses_replace_on_script(self):
        # Section 8 -- the bridge never rewrites ScriptArtifact via
        # dataclasses.replace(). It should never even import `replace`.
        offenders = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module == "dataclasses":
                for alias in node.names:
                    if alias.name == "replace":
                        offenders.add("replace")
        self.assertFalse(offenders, "script_production_bridge.py must never import dataclasses.replace")

    def test_p2_boundary_never_crossed(self):
        texts = self._non_docstring_identifiers_and_literals()
        for forbidden in ("GenerationApprovalGate", "GenerationJobService", "HiggsfieldProvider", "HiggsfieldClient"):
            self.assertNotIn(forbidden, texts, f"'{forbidden}' found as a real (non-docstring) identifier/literal")

    def test_director_py_new_method_has_no_forbidden_calls(self):
        director_source = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        tree = ast.parse(director_source)
        method_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "prepare_production_from_script":
                method_node = node
                break
        self.assertIsNotNone(method_node, "prepare_production_from_script method not found in director.py")

        called_names = set()
        for node in ast.walk(method_node):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    called_names.add(func.id)
                elif isinstance(func, ast.Attribute):
                    called_names.add(func.attr)

        offenders = called_names & {
            "create_job", "transition", "RealGenerationAuthorization",
            "RequestScopedActivationContract", "ControlledRealProviderActivationContract",
        }
        self.assertFalse(offenders, f"prepare_production_from_script contains forbidden call(s): {offenders}")


if __name__ == "__main__":
    unittest.main()
