"""
Tests — Video Production Preparation (Phase P3.14).

Fully offline: no network, no Higgsfield, no social platform, no OAuth,
no credential of any kind is imported or constructed anywhere in this
file. Verifies `agents/video_production_preparation.py` and the new
`AIDirector.prepare_video_generation_request()` entry point in
`director.py`.
"""

import ast
import hashlib
import sys
import unittest
from dataclasses import replace as dc_replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.asset_preparation_system import AssetPreparationSystem
from agents.content_agent import ContentAgent, ContentAgentInput
from agents.generation_approval_gate import GenerationRequest
from agents.planner import Scene as PlannerScene, VideoPlan, VideoPlanner
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.script_production_bridge import ProductionPreparationInput, ProductionPreparationStatus
from agents.strategy_agent import StrategyAgent, StrategyAgentInput
from agents.video_agent import VideoAgent
from agents.video_production_preparation import (
    VideoProductionPreparation,
    VideoProductionPreparationError,
    VideoProductionPreparationInput,
    VideoProductionPreparationResult,
)
from director import AIDirector

MODULE_SOURCE_PATH = PROJECT_ROOT / "agents" / "video_production_preparation.py"
PROJECT_ROOT_FOR_ASSETS = PROJECT_ROOT

# Canonical Video 005 fixture values (P3.14 Section 9/10), independently
# verified in this phase's audit against the real files on disk before
# being asserted here -- never trusted blindly from the phase brief.
VIDEO_005_REQUEST_ID = "005"
VIDEO_005_JOB_TYPE = "seedance_2_0"
VIDEO_005_DURATION = 15
VIDEO_005_RESOLUTION = "720p"
VIDEO_005_ASPECT_RATIO = "9:16"
VIDEO_005_PROMPT_SHA256 = "1c498617adb4603bcf2fc114a9cb9e8fe2219f09285adbff4d1e6c7a10a669e1"
VIDEO_005_AVATAR_SHA256 = "d293e41a63f66fd43afbebee3f7f9f1bd29143b465fa57a18ab4e1df5faf7280"
VIDEO_005_FACE_SHA256 = "df83a97b71cff9a90191c19d15ff989228b9fef2e57c96cf7c76c68652e3a343"


def _real_video_005_plan() -> VideoPlan:
    planner = VideoPlanner(PROJECT_ROOT_FOR_ASSETS)
    return planner.create_zephyr_plan(
        video_id="005",
        title="Pourquoi la discipline vaut plus que le talent.",
        hook="Le talent impressionne. La discipline construit des empires.",
        objective="Créer une vidéo courte, cinématique et motivante.",
    )


def _real_script_artifact(mission_id: str = "mission-005", **overrides):
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


class _FakeBridgePrepared:
    """Minimal stand-in for a ProductionPreparationRequest, used only to
    build a fake ScriptProductionBridge test double."""


class _FakeVideoAgent:
    def __init__(self, response=None, error=None):
        self.calls = []
        self._response = response
        self._error = error

    def build_request(self, plan, **kwargs):
        self.calls.append((plan, kwargs))
        if self._error is not None:
            raise self._error
        return self._response


class VideoProductionPreparationHappyPathTests(unittest.TestCase):
    """Tests 1-4 from the P3.14 mandatory list."""

    def test_valid_script_artifact_end_to_end(self):
        script = _real_script_artifact()
        plan = _real_video_005_plan()
        pa = PromptAssemblySystem(PROJECT_ROOT_FOR_ASSETS)
        assets = AssetPreparationSystem(PROJECT_ROOT_FOR_ASSETS)
        integration = VideoProductionPreparation(prompt_assembly=pa, asset_preparation=assets)

        result = integration.prepare(
            VideoProductionPreparationInput(
                production_input=ProductionPreparationInput(
                    mission_id="mission-005", script_artifact=script, video_id="005"
                ),
                video_plan=plan,
                request_id="005",
            )
        )
        self.assertEqual(result.status, ProductionPreparationStatus.READY)
        self.assertIsInstance(result.generation_request, GenerationRequest)

    def test_bridge_feeds_video_agent(self):
        fake_video_agent = _FakeVideoAgent(response="SENTINEL")
        pa = PromptAssemblySystem(PROJECT_ROOT_FOR_ASSETS)
        integration = VideoProductionPreparation(prompt_assembly=pa, video_agent=fake_video_agent)
        script = _real_script_artifact()
        plan = _real_video_005_plan()

        result = integration.prepare(
            VideoProductionPreparationInput(
                production_input=ProductionPreparationInput(
                    mission_id="mission-005", script_artifact=script, video_id="005"
                ),
                video_plan=plan,
            )
        )
        self.assertEqual(len(fake_video_agent.calls), 1)
        self.assertEqual(result.generation_request, "SENTINEL")

    def test_video_agent_receives_correct_input(self):
        fake_video_agent = _FakeVideoAgent(response="SENTINEL")
        pa = PromptAssemblySystem(PROJECT_ROOT_FOR_ASSETS)
        integration = VideoProductionPreparation(prompt_assembly=pa, video_agent=fake_video_agent)
        script = _real_script_artifact()
        plan = _real_video_005_plan()

        integration.prepare(
            VideoProductionPreparationInput(
                production_input=ProductionPreparationInput(
                    mission_id="mission-005", script_artifact=script, video_id="005"
                ),
                video_plan=plan,
                request_id="custom-id",
            )
        )
        called_plan, kwargs = fake_video_agent.calls[0]
        self.assertIs(called_plan, plan)
        self.assertEqual(kwargs["job_type"], "seedance_2_0")
        self.assertTrue(kwargs["prompt"])
        self.assertEqual(kwargs["approved"], False)
        self.assertEqual(kwargs["request_id"], "custom-id")
        self.assertIsNone(kwargs["real_generation_authorization"])

    def test_generation_request_produced(self):
        script = _real_script_artifact()
        plan = _real_video_005_plan()
        pa = PromptAssemblySystem(PROJECT_ROOT_FOR_ASSETS)
        assets = AssetPreparationSystem(PROJECT_ROOT_FOR_ASSETS)
        integration = VideoProductionPreparation(prompt_assembly=pa, asset_preparation=assets)
        result = integration.prepare(
            VideoProductionPreparationInput(
                production_input=ProductionPreparationInput(
                    mission_id="mission-005", script_artifact=script, video_id="005"
                ),
                video_plan=plan,
            )
        )
        self.assertIsNotNone(result.generation_request)


class Video005RegressionTests(unittest.TestCase):
    """Tests 5-14, 38 from the P3.14 mandatory list -- Video 005 fixture,
    independently verified against real files (not asserted blindly)."""

    @classmethod
    def setUpClass(cls):
        script = _real_script_artifact()
        plan = _real_video_005_plan()
        pa = PromptAssemblySystem(PROJECT_ROOT_FOR_ASSETS)
        assets = AssetPreparationSystem(PROJECT_ROOT_FOR_ASSETS)
        integration = VideoProductionPreparation(prompt_assembly=pa, asset_preparation=assets)
        cls.result = integration.prepare(
            VideoProductionPreparationInput(
                production_input=ProductionPreparationInput(
                    mission_id="mission-005", script_artifact=script, video_id="005"
                ),
                video_plan=plan,
                request_id="005",
            )
        )
        cls.request = cls.result.generation_request

    def test_status_ready(self):
        self.assertEqual(self.result.status, ProductionPreparationStatus.READY)

    def test_request_id_preserved(self):
        self.assertEqual(self.request.request_id, VIDEO_005_REQUEST_ID)

    def test_model_job_type_preserved(self):
        self.assertEqual(self.request.job_type, VIDEO_005_JOB_TYPE)

    def test_duration_preserved(self):
        self.assertEqual(self.request.duration, VIDEO_005_DURATION)

    def test_resolution_preserved(self):
        self.assertEqual(self.request.resolution, VIDEO_005_RESOLUTION)

    def test_aspect_ratio_preserved(self):
        self.assertEqual(self.request.aspect_ratio, VIDEO_005_ASPECT_RATIO)

    def test_prompt_preserved_and_non_empty(self):
        self.assertTrue(self.request.prompt)

    def test_prompt_hash_matches_canonical_value(self):
        actual_hash = hashlib.sha256(self.request.prompt.encode("utf-8")).hexdigest()
        self.assertEqual(actual_hash, VIDEO_005_PROMPT_SHA256)

    def test_prompt_provenance_via_bridge_delegation(self):
        self.assertEqual(self.result.production_preparation.prompt_source, "PromptAssemblySystem:005")

    def test_master_avatar_preserved(self):
        self.assertIsNotNone(self.request.start_image)
        self.assertEqual(self.request.start_image.role, "master_avatar")

    def test_face_reference_preserved(self):
        self.assertEqual(len(self.request.image_references), 1)
        self.assertEqual(self.request.image_references[0].role, "face_reference")

    def test_asset_hashes_preserved(self):
        self.assertEqual(self.request.start_image.sha256, VIDEO_005_AVATAR_SHA256)
        self.assertEqual(self.request.image_references[0].sha256, VIDEO_005_FACE_SHA256)

    def test_never_approved_never_authorized(self):
        self.assertFalse(self.request.approved)
        self.assertIsNone(self.request.real_generation_authorization)

    def test_full_video_005_regression(self):
        self.assertEqual(self.request.request_id, VIDEO_005_REQUEST_ID)
        self.assertEqual(self.request.job_type, VIDEO_005_JOB_TYPE)
        self.assertEqual(self.request.duration, VIDEO_005_DURATION)
        self.assertEqual(self.request.resolution, VIDEO_005_RESOLUTION)
        self.assertEqual(self.request.aspect_ratio, VIDEO_005_ASPECT_RATIO)
        self.assertEqual(
            hashlib.sha256(self.request.prompt.encode("utf-8")).hexdigest(), VIDEO_005_PROMPT_SHA256
        )
        self.assertEqual(self.request.start_image.sha256, VIDEO_005_AVATAR_SHA256)
        self.assertEqual(self.request.image_references[0].sha256, VIDEO_005_FACE_SHA256)
        self.assertFalse(self.request.approved)
        self.assertIsNone(self.request.real_generation_authorization)


class VideoProductionPreparationDeterminismTests(unittest.TestCase):
    """Tests 15-16 from the P3.14 mandatory list."""

    def test_deterministic_preparation(self):
        script = _real_script_artifact()
        plan = _real_video_005_plan()
        pa = PromptAssemblySystem(PROJECT_ROOT_FOR_ASSETS)
        assets = AssetPreparationSystem(PROJECT_ROOT_FOR_ASSETS)

        def run_once():
            integration = VideoProductionPreparation(prompt_assembly=pa, asset_preparation=assets)
            return integration.prepare(
                VideoProductionPreparationInput(
                    production_input=ProductionPreparationInput(
                        mission_id="mission-005", script_artifact=script, video_id="005"
                    ),
                    video_plan=plan,
                    request_id="005",
                )
            )

        first = run_once()
        second = run_once()
        self.assertEqual(first.generation_request.prompt, second.generation_request.prompt)
        self.assertEqual(first.generation_request.job_type, second.generation_request.job_type)
        self.assertEqual(first.generation_request.duration, second.generation_request.duration)
        self.assertEqual(
            first.production_preparation.content_hash, second.production_preparation.content_hash
        )

    def test_immutable_inputs(self):
        from dataclasses import FrozenInstanceError

        script = _real_script_artifact()
        plan = _real_video_005_plan()
        request_input = VideoProductionPreparationInput(
            production_input=ProductionPreparationInput(mission_id="mission-005", script_artifact=script),
            video_plan=plan,
        )
        with self.assertRaises(FrozenInstanceError):
            request_input.request_id = "tampered"  # type: ignore


class VideoProductionPreparationFailureTests(unittest.TestCase):
    """Tests 17-22 from the P3.14 mandatory list."""

    def test_invalid_script_artifact_blocks(self):
        plan = _real_video_005_plan()
        integration = VideoProductionPreparation()
        result = integration.prepare(
            VideoProductionPreparationInput(
                production_input=ProductionPreparationInput(mission_id="mission-005", script_artifact=None),
                video_plan=plan,
            )
        )
        self.assertEqual(result.status, ProductionPreparationStatus.BLOCKED)
        self.assertIsNone(result.generation_request)

    def test_invalid_production_metadata_wrong_mission_blocks(self):
        script = _real_script_artifact(mission_id="mission-A")
        plan = _real_video_005_plan()
        integration = VideoProductionPreparation()
        result = integration.prepare(
            VideoProductionPreparationInput(
                production_input=ProductionPreparationInput(mission_id="mission-B", script_artifact=script),
                video_plan=plan,
            )
        )
        self.assertEqual(result.status, ProductionPreparationStatus.BLOCKED)
        self.assertIsNone(result.generation_request)

    def test_missing_asset_reference_does_not_crash(self):
        script = _real_script_artifact()
        plan = _real_video_005_plan()
        pa = PromptAssemblySystem(PROJECT_ROOT_FOR_ASSETS)
        integration = VideoProductionPreparation(prompt_assembly=pa, asset_preparation=None)
        result = integration.prepare(
            VideoProductionPreparationInput(
                production_input=ProductionPreparationInput(
                    mission_id="mission-005", script_artifact=script, video_id="005"
                ),
                video_plan=plan,
            )
        )
        self.assertEqual(result.status, ProductionPreparationStatus.READY)
        self.assertIsNone(result.generation_request.start_image)
        self.assertEqual(result.generation_request.image_references, ())

    def test_malformed_prompt_input_yields_incomplete(self):
        script = _real_script_artifact()
        plan = _real_video_005_plan()
        integration = VideoProductionPreparation()
        result = integration.prepare(
            VideoProductionPreparationInput(
                production_input=ProductionPreparationInput(
                    mission_id="mission-005", script_artifact=script, prompt="   "
                ),
                video_plan=plan,
            )
        )
        self.assertEqual(result.status, ProductionPreparationStatus.INCOMPLETE)
        self.assertIsNone(result.generation_request)

    def test_invalid_video_agent_input_raises_explicitly(self):
        script = _real_script_artifact()
        integration = VideoProductionPreparation()
        with self.assertRaises(VideoProductionPreparationError):
            integration.prepare(
                VideoProductionPreparationInput(
                    production_input=ProductionPreparationInput(mission_id="mission-005", script_artifact=script),
                    video_plan="not-a-video-plan",  # type: ignore
                )
            )

    def test_failure_propagation_from_video_agent(self):
        fake_video_agent = _FakeVideoAgent(error=ValueError("boom"))
        pa = PromptAssemblySystem(PROJECT_ROOT_FOR_ASSETS)
        integration = VideoProductionPreparation(prompt_assembly=pa, video_agent=fake_video_agent)
        script = _real_script_artifact()
        plan = _real_video_005_plan()
        with self.assertRaises(ValueError):
            integration.prepare(
                VideoProductionPreparationInput(
                    production_input=ProductionPreparationInput(
                        mission_id="mission-005", script_artifact=script, video_id="005"
                    ),
                    video_plan=plan,
                )
            )


class VideoProductionPreparationUnknownTests(unittest.TestCase):
    """Test 23 from the P3.14 mandatory list."""

    def test_unknown_classification_never_upgraded_to_ready(self):
        script = _real_script_artifact()
        plan = _real_video_005_plan()
        # No prompt, no video_id/prompt_assembly delegation -> bridge
        # cannot resolve a prompt -> INCOMPLETE, never silently promoted.
        integration = VideoProductionPreparation()
        result = integration.prepare(
            VideoProductionPreparationInput(
                production_input=ProductionPreparationInput(mission_id="mission-005", script_artifact=script),
                video_plan=plan,
            )
        )
        self.assertNotEqual(result.status, ProductionPreparationStatus.READY)
        self.assertIsNone(result.generation_request)


class NoPromptOrAssetRewriteTests(unittest.TestCase):
    """Tests 39-40 from the P3.14 mandatory list."""

    def test_no_prompt_rewrite(self):
        pa = PromptAssemblySystem(PROJECT_ROOT_FOR_ASSETS)
        expected_prompt = pa.assemble("005")
        script = _real_script_artifact()
        plan = _real_video_005_plan()
        assets = AssetPreparationSystem(PROJECT_ROOT_FOR_ASSETS)
        integration = VideoProductionPreparation(prompt_assembly=pa, asset_preparation=assets)
        result = integration.prepare(
            VideoProductionPreparationInput(
                production_input=ProductionPreparationInput(
                    mission_id="mission-005", script_artifact=script, video_id="005"
                ),
                video_plan=plan,
            )
        )
        self.assertEqual(result.generation_request.prompt, expected_prompt)

    def test_no_asset_rewrite(self):
        script = _real_script_artifact()
        plan = _real_video_005_plan()
        pa = PromptAssemblySystem(PROJECT_ROOT_FOR_ASSETS)
        assets = AssetPreparationSystem(PROJECT_ROOT_FOR_ASSETS)
        expected_assets = {a.role: a.sha256 for a in assets.scan() if a.status == "READY"}
        integration = VideoProductionPreparation(prompt_assembly=pa, asset_preparation=assets)
        result = integration.prepare(
            VideoProductionPreparationInput(
                production_input=ProductionPreparationInput(
                    mission_id="mission-005", script_artifact=script, video_id="005"
                ),
                video_plan=plan,
            )
        )
        self.assertEqual(result.generation_request.start_image.sha256, expected_assets["master_avatar"])
        self.assertEqual(
            result.generation_request.image_references[0].sha256, expected_assets["face_reference"]
        )


class TraceabilityTests(unittest.TestCase):
    """Test 12 (traceability) from the P3.14 mandatory list."""

    def test_traceability_chain(self):
        script = _real_script_artifact()
        plan = _real_video_005_plan()
        pa = PromptAssemblySystem(PROJECT_ROOT_FOR_ASSETS)
        assets = AssetPreparationSystem(PROJECT_ROOT_FOR_ASSETS)
        integration = VideoProductionPreparation(prompt_assembly=pa, asset_preparation=assets)
        result = integration.prepare(
            VideoProductionPreparationInput(
                production_input=ProductionPreparationInput(
                    mission_id="mission-005", script_artifact=script, video_id="005"
                ),
                video_plan=plan,
            )
        )
        self.assertEqual(result.mission_id, "mission-005")
        self.assertEqual(result.production_preparation.script_artifact.artifact_id, script.artifact_id)
        self.assertEqual(result.production_preparation.mission_id, "mission-005")


class MissionIdPropagationTests(unittest.TestCase):
    """Test 35 from the P3.14 mandatory list."""

    def test_mission_id_propagation(self):
        script = _real_script_artifact(mission_id="mission-xyz")
        plan = _real_video_005_plan()
        integration = VideoProductionPreparation()
        result = integration.prepare(
            VideoProductionPreparationInput(
                production_input=ProductionPreparationInput(
                    mission_id="mission-xyz", script_artifact=script, prompt="p"
                ),
                video_plan=plan,
            )
        )
        self.assertEqual(result.mission_id, "mission-xyz")


class DirectorIntegrationTests(unittest.TestCase):
    """Test 34 from the P3.14 mandatory list."""

    def test_director_exposes_prepare_video_generation_request(self):
        director = AIDirector()
        self.assertTrue(hasattr(director, "prepare_video_generation_request"))

    def test_director_delegates_to_injected_preparation(self):
        fake_video_agent = _FakeVideoAgent(response="SENTINEL")
        pa = PromptAssemblySystem(PROJECT_ROOT_FOR_ASSETS)
        preparation = VideoProductionPreparation(prompt_assembly=pa, video_agent=fake_video_agent)
        script = _real_script_artifact()
        plan = _real_video_005_plan()
        director = AIDirector()
        result = director.prepare_video_generation_request(
            VideoProductionPreparationInput(
                production_input=ProductionPreparationInput(
                    mission_id="mission-005", script_artifact=script, video_id="005"
                ),
                video_plan=plan,
            ),
            preparation=preparation,
        )
        self.assertIsInstance(result, VideoProductionPreparationResult)
        self.assertEqual(len(fake_video_agent.calls), 1)

    def test_director_default_preparation_used_without_injection(self):
        script = _real_script_artifact()
        plan = _real_video_005_plan()
        director = AIDirector()
        result = director.prepare_video_generation_request(
            VideoProductionPreparationInput(
                production_input=ProductionPreparationInput(
                    mission_id="mission-005", script_artifact=script, prompt="explicit prompt"
                ),
                video_plan=plan,
            )
        )
        self.assertEqual(result.status, ProductionPreparationStatus.READY)

    def test_existing_methods_unaffected(self):
        director = AIDirector()
        self.assertTrue(hasattr(director, "run_business_pipeline"))
        self.assertTrue(hasattr(director, "run_video_mission"))
        self.assertTrue(hasattr(director, "prepare_production_from_script"))


class StateBoundaryTests(unittest.TestCase):
    """Test 36 from the P3.14 mandatory list."""

    def test_no_state_authority_on_result_or_integration(self):
        script = _real_script_artifact()
        plan = _real_video_005_plan()
        integration = VideoProductionPreparation()
        result = integration.prepare(
            VideoProductionPreparationInput(
                production_input=ProductionPreparationInput(
                    mission_id="mission-005", script_artifact=script, prompt="p"
                ),
                video_plan=plan,
            )
        )
        self.assertFalse(hasattr(result, "mission_state"))
        self.assertFalse(hasattr(integration, "state_machine"))
        self.assertFalse(hasattr(integration, "transition"))


class SecurityTests(unittest.TestCase):
    """
    Tests 24-33, 37 from the P3.14 mandatory list: AST-based,
    docstring-false-positive-safe (P3.5-P3.13 lesson), static
    verification that `agents/video_production_preparation.py` never
    reaches real execution, any P2 authority mechanism beyond the
    legitimate `GenerationRequest` TYPE import (exactly the same
    precedent already set by `agents/video_agent.py`), the Mission
    State Machine, or an event bus.
    """

    FORBIDDEN_MODULES = {
        "integrations.higgsfield.client",
        "integrations.higgsfield.provider",
        "integrations.higgsfield.mock_provider",
        "agents.generation_job_service",
        "agents.activation_contract",
        "agents.controlled_real_provider_activation",
        "agents.real_provider_execution_gate",
        "agents.real_provider_activation_preflight",
        "agents.critical_section_lock",
        "agents.executed_request_store",
        "agents.final_report_service",
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
        "create_job", "system", "popen", "Popen", "transition", "evaluate", "execute",
        "RealGenerationAuthorization", "RequestScopedActivationContract",
        "ControlledRealProviderActivationContract", "GenerationApprovalGate",
        "GenerationJobService", "HiggsfieldProvider", "HiggsfieldClient",
    }

    @classmethod
    def setUpClass(cls):
        cls.source = MODULE_SOURCE_PATH.read_text(encoding="utf-8")
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

    def _imported_names_from(self, module_name):
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module == module_name:
                for alias in node.names:
                    names.add(alias.name)
        return names

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

    def _docstring_nodes(self):
        docstring_nodes = set()
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if (
                    node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)
                ):
                    docstring_nodes.add(node.body[0].value)
        return docstring_nodes

    def _non_docstring_identifiers_and_literals(self):
        docstring_nodes = {id(n) for n in self._docstring_nodes()}
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

    def _source_without_docstrings(self):
        # Every module/class/function docstring is real prose that may
        # legitimately discuss forbidden-looking substrings (e.g. "this
        # module never requests." -- a sentence ending in "requests.",
        # not the `requests` library) -- P3.12's own lesson, reapplied
        # here rather than reworded away in the docstring.
        lines = self.source.splitlines(keepends=True)
        doc_nodes = sorted(self._docstring_nodes(), key=lambda n: n.lineno, reverse=True)
        for doc_node in doc_nodes:
            start = doc_node.lineno - 1
            end = doc_node.end_lineno
            lines = lines[:start] + lines[end:]
        return "".join(lines)

    def test_no_forbidden_module_imports(self):
        offenders = self._imported_modules() & self.FORBIDDEN_MODULES
        self.assertFalse(offenders, f"video_production_preparation.py imports forbidden module(s): {offenders}")

    def test_generation_approval_gate_imported_for_type_only(self):
        # Legitimate precedent: agents/video_agent.py already imports
        # GenerationRequest/RealGenerationAuthorization from this exact
        # module as types, never calling GenerationApprovalGate itself.
        names = self._imported_names_from("agents.generation_approval_gate")
        self.assertTrue(names)
        self.assertNotIn("GenerationApprovalGate", names)

    def test_no_forbidden_calls(self):
        offenders = self._called_names() & self.FORBIDDEN_CALL_NAMES
        self.assertFalse(offenders, f"video_production_preparation.py contains forbidden call(s): {offenders}")

    def test_no_create_job_call(self):
        self.assertNotIn("create_job", self._called_names())

    def test_no_network_related_substrings(self):
        code = self._source_without_docstrings()
        for banned_substring in ("requests.", "urllib.", "socket.", "http.client", "subprocess.", "os.system", "aiohttp.", "httpx."):
            self.assertNotIn(banned_substring, code)

    def test_no_credential_oauth_tokens(self):
        lowered = self._source_without_docstrings().lower()
        for token in ("api_key", "apikey", "oauth", "credential", "access_token", "bearer", "password"):
            self.assertNotIn(token, lowered)

    def test_no_event_bus(self):
        suspicious = {name for name in self._called_names() if "emit" in name.lower() or "subscribe" in name.lower()}
        self.assertFalse(suspicious)
        self.assertNotIn("EventBus", self._non_docstring_identifiers_and_literals())

    def test_no_publish_execution(self):
        suspicious = {name for name in self._called_names() if "publish" in name.lower()}
        self.assertFalse(suspicious)

    def test_no_state_machine_transition_call(self):
        self.assertNotIn("transition", self._called_names())

    def test_approved_hardcoded_false_and_authorization_hardcoded_none(self):
        # Structural check on the actual build_request(...) call: the
        # `approved` keyword must be the literal False, and
        # `real_generation_authorization` the literal None -- never a
        # variable sourced from the caller.
        call_node = None
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "build_request":
                call_node = node
                break
        self.assertIsNotNone(call_node, "build_request(...) call not found")
        keywords = {kw.arg: kw.value for kw in call_node.keywords}
        self.assertIn("approved", keywords)
        self.assertIsInstance(keywords["approved"], ast.Constant)
        self.assertEqual(keywords["approved"].value, False)
        self.assertIn("real_generation_authorization", keywords)
        self.assertIsInstance(keywords["real_generation_authorization"], ast.Constant)
        self.assertIsNone(keywords["real_generation_authorization"].value)

    def test_agent_boundary_bridge_and_video_agent_not_reimplemented(self):
        # ScriptProductionBridge/VideoAgent classes are imported and
        # used, never redefined locally in this module.
        class_defs = {node.name for node in ast.walk(self.tree) if isinstance(node, ast.ClassDef)}
        self.assertNotIn("ScriptProductionBridge", class_defs)
        self.assertNotIn("VideoAgent", class_defs)

    def test_director_py_new_method_has_no_forbidden_calls(self):
        director_source = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        tree = ast.parse(director_source)
        method_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "prepare_video_generation_request":
                method_node = node
                break
        self.assertIsNotNone(method_node, "prepare_video_generation_request method not found in director.py")

        called_names = set()
        for node in ast.walk(method_node):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    called_names.add(func.id)
                elif isinstance(func, ast.Attribute):
                    called_names.add(func.attr)

        offenders = called_names & {
            "create_job", "transition", "evaluate", "execute",
            "RealGenerationAuthorization", "RequestScopedActivationContract",
            "ControlledRealProviderActivationContract",
        }
        self.assertFalse(offenders, f"prepare_video_generation_request contains forbidden call(s): {offenders}")


if __name__ == "__main__":
    unittest.main()
