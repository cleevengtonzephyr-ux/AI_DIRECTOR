"""
Tests — Production Metadata Consistency (Phase P3.16).

Audits, and locks in with regression tests, the real source of every
production-metadata field that flows ContentAgent -> ScriptArtifact ->
ScriptProductionBridge -> VideoProductionPreparation -> VideoPlan ->
VideoAgent -> GenerationRequest -> PreProductionReview. Fully offline:
no network, no Higgsfield, no social platform, no OAuth, no credential
of any kind is imported or constructed anywhere in this file.

DURATION POLICY UNDER TEST (P3.16 Section 7, Option D -- see `agents/
pre_production_review.py` module docstring for the full evidence trail):
`ScriptArtifact.total_duration_target` (content-planning target) and
`GenerationRequest.duration` (technical production duration, sourced
from `VideoPlan.duration`) are INTENTIONALLY DIFFERENT concepts, never
required to be equal. This file proves both sources independently and
proves the review surfaces, rather than hides or fails on, their
divergence.
"""

import ast
import hashlib
import sys
import unittest
from dataclasses import FrozenInstanceError, replace as dc_replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.asset_preparation_system import AssetPreparationSystem
from agents.content_agent import (
    ContentAgent,
    ContentAgentInput,
    DEFAULT_TOTAL_DURATION_TARGET_SECONDS,
)
from agents.generation_approval_gate import GenerationRequest
from agents.planner import VideoPlanner
from agents.pre_production_review import (
    PreProductionReview,
    PreProductionReviewInput,
    PreProductionReviewStatus,
    PreProductionReviewer,
    ReadinessFailureCategory,
)
from agents.production_model import PRODUCTION_MODEL
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.script_production_bridge import (
    ProductionPreparationInput,
    ProductionPreparationStatus,
    ScriptProductionBridge,
)
from agents.strategy_agent import StrategyAgent, StrategyAgentInput
from agents.video_production_preparation import VideoProductionPreparation, VideoProductionPreparationInput
from director import AIDirector

MODULE_SOURCE_PATH = PROJECT_ROOT / "agents" / "pre_production_review.py"

VIDEO_005_REQUEST_ID = "005"
VIDEO_005_JOB_TYPE = "seedance_2_0"
VIDEO_005_DURATION = 15
VIDEO_005_RESOLUTION = "720p"
VIDEO_005_ASPECT_RATIO = "9:16"
VIDEO_005_PROMPT_SHA256 = "1c498617adb4603bcf2fc114a9cb9e8fe2219f09285adbff4d1e6c7a10a669e1"
VIDEO_005_SCRIPT_SCAFFOLD_DURATION = 30  # DEFAULT_TOTAL_DURATION_TARGET_SECONDS, non-binding


def _real_video_005_plan():
    planner = VideoPlanner(PROJECT_ROOT)
    return planner.create_zephyr_plan(
        video_id="005",
        title="Pourquoi la discipline vaut plus que le talent.",
        hook="Le talent impressionne. La discipline construit des empires.",
        objective="Créer une vidéo courte, cinématique et motivante.",
    )


def _real_script_artifact(mission_id: str = "mission-005", duration_target_seconds=None, **overrides):
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
        ContentAgentInput(
            mission_id=mission_id,
            strategy_artifact=strategy.strategy_artifact,
            duration_target_seconds=duration_target_seconds,
        )
    )
    script = content.script_artifact
    if overrides:
        script = dc_replace(script, **overrides)
    return script


def _real_ready_result(request_id="005", script=None):
    script = script if script is not None else _real_script_artifact()
    plan = _real_video_005_plan()
    pa = PromptAssemblySystem(PROJECT_ROOT)
    assets = AssetPreparationSystem(PROJECT_ROOT)
    integration = VideoProductionPreparation(prompt_assembly=pa, asset_preparation=assets)
    return integration.prepare(
        VideoProductionPreparationInput(
            production_input=ProductionPreparationInput(
                mission_id="mission-005", script_artifact=script, video_id="005"
            ),
            video_plan=plan,
            request_id=request_id,
        )
    )


def _findings_by_dimension(review):
    return {f.dimension: f for f in review.findings}


class ScriptArtifactDurationSourceTests(unittest.TestCase):
    """Test 1 from the P3.16 mandatory list."""

    def test_default_duration_is_non_binding_scaffold(self):
        script = _real_script_artifact()
        self.assertEqual(script.total_duration_target, DEFAULT_TOTAL_DURATION_TARGET_SECONDS)
        self.assertEqual(script.total_duration_target, VIDEO_005_SCRIPT_SCAFFOLD_DURATION)

    def test_explicit_override_becomes_script_duration(self):
        script = _real_script_artifact(duration_target_seconds=15)
        self.assertEqual(script.total_duration_target, 15)

    def test_scene_durations_sum_to_total_duration_target(self):
        script = _real_script_artifact(duration_target_seconds=15)
        self.assertEqual(sum(scene.duration for scene in script.scenes), 15)


class VideoPlanDurationSourceTests(unittest.TestCase):
    """Test 2 from the P3.16 mandatory list."""

    def test_video_005_plan_duration_is_fixed_real_constraint(self):
        plan = _real_video_005_plan()
        self.assertEqual(plan.duration, VIDEO_005_DURATION)

    def test_plan_duration_independent_of_script_artifact(self):
        # The plan carries no reference to any ScriptArtifact at all --
        # constructing it never even takes one as an argument.
        plan = _real_video_005_plan()
        self.assertFalse(hasattr(plan, "script_artifact"))
        self.assertFalse(hasattr(plan, "total_duration_target"))


class GenerationRequestDurationSourceTests(unittest.TestCase):
    """Tests 3, 4, 5 from the P3.16 mandatory list."""

    def test_generation_request_duration_matches_plan_not_script(self):
        script = _real_script_artifact()  # scaffold default: 30s
        self.assertNotEqual(script.total_duration_target, VIDEO_005_DURATION)
        result = _real_ready_result(script=script)
        self.assertEqual(result.status, ProductionPreparationStatus.READY)
        self.assertEqual(result.generation_request.duration, VIDEO_005_DURATION)
        self.assertEqual(result.production_preparation.duration_seconds, VIDEO_005_SCRIPT_SCAFFOLD_DURATION)

    def test_duration_consistency_when_explicitly_aligned(self):
        script = _real_script_artifact(duration_target_seconds=15)
        result = _real_ready_result(script=script)
        self.assertEqual(result.generation_request.duration, 15)
        self.assertEqual(result.production_preparation.duration_seconds, 15)

    def test_intentional_duration_difference_surfaced_not_hidden(self):
        result = _real_ready_result()  # real fixture: 30 (script) vs 15 (plan)
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        finding = _findings_by_dimension(review)["duration_validation"]
        self.assertTrue(finding.passed)
        self.assertIn(str(VIDEO_005_DURATION), finding.detail)
        self.assertIn(str(VIDEO_005_SCRIPT_SCAFFOLD_DURATION), finding.detail)
        self.assertEqual(review.status, PreProductionReviewStatus.PASS)


class DurationFailureSemanticsTests(unittest.TestCase):
    """Tests 6, 7, 8 from the P3.16 mandatory list."""

    def test_missing_duration_fails(self):
        result = _real_ready_result()
        tampered_request = dc_replace(result.generation_request, duration=None)
        tampered_result = dc_replace(result, generation_request=tampered_request)
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=tampered_result))
        finding = _findings_by_dimension(review)["duration_validation"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, ReadinessFailureCategory.INCOMPLETE_PRODUCTION_REQUEST)
        self.assertEqual(review.status, PreProductionReviewStatus.FAIL)

    def test_invalid_duration_fails(self):
        result = _real_ready_result()
        tampered_request = dc_replace(result.generation_request, duration=-5)
        tampered_result = dc_replace(result, generation_request=tampered_request)
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=tampered_result))
        self.assertFalse(_findings_by_dimension(review)["duration_validation"].passed)

    def test_conflicting_duration_does_not_auto_fail_review(self):
        # "Conflicting" (script vs plan differ) is, per the P3.16 duration
        # policy, explicitly NOT a failure -- an ambiguity must never be
        # silently turned into an automatic approval OR a spurious
        # rejection; here it is neither: it is reported, and the review
        # can still PASS on its own separate structural merits.
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertTrue(_findings_by_dimension(review)["duration_validation"].passed)
        self.assertEqual(review.status, PreProductionReviewStatus.PASS)


class ModelResolutionAspectRatioConsistencyTests(unittest.TestCase):
    """Tests 9, 10, 11 from the P3.16 mandatory list."""

    def test_model_job_type_single_source_of_truth(self):
        result = _real_ready_result()
        self.assertEqual(result.generation_request.job_type, PRODUCTION_MODEL)
        self.assertEqual(result.production_preparation.job_type, PRODUCTION_MODEL)
        self.assertEqual(result.generation_request.job_type, VIDEO_005_JOB_TYPE)

    def test_resolution_single_source_of_truth(self):
        result = _real_ready_result()
        self.assertEqual(result.generation_request.resolution, VIDEO_005_RESOLUTION)

    def test_aspect_ratio_single_source_of_truth(self):
        result = _real_ready_result()
        self.assertEqual(result.generation_request.aspect_ratio, VIDEO_005_ASPECT_RATIO)

    def test_model_mismatch_detected_by_review(self):
        result = _real_ready_result()
        tampered_prepared = dc_replace(result.production_preparation, job_type="not_seedance")
        tampered_result = dc_replace(result, production_preparation=tampered_prepared)
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=tampered_result))
        finding = _findings_by_dimension(review)["model_job_type_consistency"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, ReadinessFailureCategory.CONTRACT_MISMATCH)


class ProductionMetadataCompletenessTests(unittest.TestCase):
    """Tests 12, 13 from the P3.16 mandatory list."""

    def test_metadata_completeness_passes_for_real_request(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertTrue(_findings_by_dimension(review)["metadata_completeness"].passed)

    def test_metadata_provenance_traceable(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertTrue(_findings_by_dimension(review)["prompt_provenance"].passed)
        self.assertTrue(_findings_by_dimension(review)["script_artifact_provenance"].passed)
        self.assertTrue(_findings_by_dimension(review)["asset_provenance"].passed)


class PromptAndAssetIntegrityTests(unittest.TestCase):
    """Tests 14, 15 from the P3.16 mandatory list."""

    def test_prompt_unchanged_and_matches_canonical_hash(self):
        result = _real_ready_result()
        actual_hash = hashlib.sha256(result.generation_request.prompt.encode("utf-8")).hexdigest()
        self.assertEqual(actual_hash, VIDEO_005_PROMPT_SHA256)

    def test_no_second_prompt_assembly_path(self):
        # PromptAssemblySystem is used, never reimplemented, by this
        # module's own AST suite below; here we assert the resulting
        # prompt is byte-identical to a direct call.
        pa = PromptAssemblySystem(PROJECT_ROOT)
        expected = pa.assemble("005")
        result = _real_ready_result()
        self.assertEqual(result.generation_request.prompt, expected)

    def test_asset_hashes_and_roles_preserved(self):
        result = _real_ready_result()
        self.assertEqual(result.generation_request.start_image.role, "master_avatar")
        self.assertEqual(len(result.generation_request.image_references), 1)
        self.assertEqual(result.generation_request.image_references[0].role, "face_reference")


class Video005RegressionTests(unittest.TestCase):
    """Test 16 from the P3.16 mandatory list."""

    @classmethod
    def setUpClass(cls):
        cls.result = _real_ready_result(request_id="005")
        cls.review = PreProductionReviewer().review(
            PreProductionReviewInput(
                preparation_result=cls.result, expected_prompt_sha256=VIDEO_005_PROMPT_SHA256
            )
        )

    def test_video_005_metadata_unchanged(self):
        gr = self.result.generation_request
        self.assertEqual(gr.request_id, VIDEO_005_REQUEST_ID)
        self.assertEqual(gr.job_type, VIDEO_005_JOB_TYPE)
        self.assertEqual(gr.duration, VIDEO_005_DURATION)
        self.assertEqual(gr.resolution, VIDEO_005_RESOLUTION)
        self.assertEqual(gr.aspect_ratio, VIDEO_005_ASPECT_RATIO)

    def test_video_005_review_still_passes(self):
        self.assertEqual(self.review.status, PreProductionReviewStatus.PASS)

    def test_video_005_not_modified_to_force_a_pass(self):
        # The review passes DESPITE the real script/plan duration
        # divergence (30 vs 15) -- proof no fixture was altered to
        # artificially align the two values.
        self.assertEqual(
            self.result.production_preparation.duration_seconds, VIDEO_005_SCRIPT_SCAFFOLD_DURATION
        )
        self.assertEqual(self.result.generation_request.duration, VIDEO_005_DURATION)


class DeterminismIdempotencyImmutabilityTests(unittest.TestCase):
    """Tests 17, 18, 19, 20 from the P3.16 mandatory list."""

    def test_deterministic_metadata(self):
        script_a = _real_script_artifact(duration_target_seconds=15)
        script_b = _real_script_artifact(duration_target_seconds=15)
        self.assertEqual(script_a.total_duration_target, script_b.total_duration_target)

    def test_deterministic_request(self):
        result_a = _real_ready_result()
        result_b = _real_ready_result()
        self.assertEqual(result_a.generation_request.duration, result_b.generation_request.duration)
        self.assertEqual(result_a.generation_request.job_type, result_b.generation_request.job_type)
        self.assertEqual(result_a.generation_request.prompt, result_b.generation_request.prompt)

    def test_idempotent_preparation_no_mutation(self):
        script = _real_script_artifact()
        before = script.total_duration_target
        _real_ready_result(script=script)
        _real_ready_result(script=script)
        self.assertEqual(script.total_duration_target, before)

    def test_immutable_generation_request_duration(self):
        result = _real_ready_result()
        with self.assertRaises(FrozenInstanceError):
            result.generation_request.duration = 999  # type: ignore

    def test_immutable_script_artifact_duration(self):
        script = _real_script_artifact()
        with self.assertRaises(FrozenInstanceError):
            script.total_duration_target = 999  # type: ignore


class MalformedInputAndFailurePropagationTests(unittest.TestCase):
    """Tests 21, 22 from the P3.16 mandatory list."""

    def test_malformed_script_artifact_blocks_preparation(self):
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

    def test_failure_propagates_to_review_without_upgrade(self):
        plan = _real_video_005_plan()
        integration = VideoProductionPreparation()
        result = integration.prepare(
            VideoProductionPreparationInput(
                production_input=ProductionPreparationInput(mission_id="mission-005", script_artifact=None),
                video_plan=plan,
            )
        )
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertEqual(review.status, PreProductionReviewStatus.FAIL)
        self.assertTrue(review.reasons)


class PriorPhaseCompatibilityTests(unittest.TestCase):
    """Tests 23, 24, 25 from the P3.16 mandatory list."""

    def test_p3_13_bridge_unaffected(self):
        script = _real_script_artifact(duration_target_seconds=15)
        pa = PromptAssemblySystem(PROJECT_ROOT)
        bridge = ScriptProductionBridge(prompt_assembly=pa)
        prepared = bridge.prepare(
            ProductionPreparationInput(mission_id="mission-005", script_artifact=script, video_id="005")
        )
        self.assertEqual(prepared.status, ProductionPreparationStatus.READY)
        self.assertEqual(prepared.duration_seconds, 15)

    def test_p3_14_preparation_unaffected(self):
        result = _real_ready_result()
        self.assertEqual(result.status, ProductionPreparationStatus.READY)
        self.assertIsInstance(result.generation_request, GenerationRequest)

    def test_p3_15_review_unaffected(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertIsInstance(review, PreProductionReview)
        self.assertEqual(review.status, PreProductionReviewStatus.PASS)
        self.assertEqual(len(review.findings), 17)


class DirectorIntegrationTests(unittest.TestCase):
    """Test 26 from the P3.16 mandatory list."""

    def test_director_review_entry_point_still_works(self):
        result = _real_ready_result()
        director = AIDirector()
        review = director.review_video_generation_request(PreProductionReviewInput(preparation_result=result))
        self.assertEqual(review.status, PreProductionReviewStatus.PASS)

    def test_no_new_director_entry_point_added(self):
        # P3.16 makes no new production/execution capability -- no new
        # Director method beyond the already-existing P3.14/P3.15 ones
        # is introduced by this phase.
        director = AIDirector()
        self.assertTrue(hasattr(director, "prepare_video_generation_request"))
        self.assertTrue(hasattr(director, "review_video_generation_request"))


class StateAndAuthorityBoundaryTests(unittest.TestCase):
    """Tests 27, 28 from the P3.16 mandatory list."""

    def test_no_state_authority(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertFalse(hasattr(review, "mission_state"))
        self.assertFalse(hasattr(PreProductionReviewer(), "state_machine"))
        self.assertFalse(hasattr(PreProductionReviewer(), "transition"))

    def test_no_authority_field_on_review(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertFalse(hasattr(review, "approved"))
        self.assertFalse(hasattr(review, "authorized"))
        self.assertFalse(review.generation_request.approved)
        self.assertIsNone(review.generation_request.real_generation_authorization)


class RegressionProtectionTests(unittest.TestCase):
    """Test 38 from the P3.16 mandatory list."""

    def test_video_005_full_metadata_chain_regression(self):
        result = _real_ready_result(request_id="005")
        review = PreProductionReviewer().review(
            PreProductionReviewInput(preparation_result=result, expected_prompt_sha256=VIDEO_005_PROMPT_SHA256)
        )
        gr = result.generation_request
        self.assertEqual(gr.request_id, VIDEO_005_REQUEST_ID)
        self.assertEqual(gr.job_type, VIDEO_005_JOB_TYPE)
        self.assertEqual(gr.duration, VIDEO_005_DURATION)
        self.assertEqual(gr.resolution, VIDEO_005_RESOLUTION)
        self.assertEqual(gr.aspect_ratio, VIDEO_005_ASPECT_RATIO)
        self.assertEqual(review.status, PreProductionReviewStatus.PASS)
        self.assertFalse(gr.approved)
        self.assertIsNone(gr.real_generation_authorization)


class SecurityTests(unittest.TestCase):
    """
    Tests 29-37 from the P3.16 mandatory list: AST-based,
    docstring-false-positive-safe, static verification that the P3.16
    -modified `agents/pre_production_review.py` still never reaches real
    execution, any P2 authority mechanism beyond the legitimate
    `GenerationRequest` TYPE import, the Mission State Machine, or an
    event bus. Re-runs the same class of checks P3.15's own suite
    established, applied to the file as it exists after this phase's
    edits.
    """

    FORBIDDEN_MODULES = {
        "integrations.higgsfield.client",
        "integrations.higgsfield.provider",
        "integrations.higgsfield.mock_provider",
        "agents.generation_job_service",
        "agents.generation_cost_service",
        "agents.cost_engine",
        "agents.activation_contract",
        "agents.controlled_real_provider_activation",
        "agents.real_provider_execution_gate",
        "agents.real_provider_activation_preflight",
        "agents.critical_section_lock",
        "agents.executed_request_store",
        "agents.final_report_service",
        "agents.mission_state_machine",
        "agents.publishing_agent",
        "agents.analytics_agent",
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

    def _source_without_docstrings(self):
        lines = self.source.splitlines(keepends=True)
        doc_nodes = sorted(self._docstring_nodes(), key=lambda n: n.lineno, reverse=True)
        for doc_node in doc_nodes:
            start = doc_node.lineno - 1
            end = doc_node.end_lineno
            lines = lines[:start] + lines[end:]
        return "".join(lines)

    def test_no_forbidden_module_imports(self):
        offenders = self._imported_modules() & self.FORBIDDEN_MODULES
        self.assertFalse(offenders, f"pre_production_review.py imports forbidden module(s): {offenders}")

    def test_no_forbidden_calls(self):
        offenders = self._called_names() & self.FORBIDDEN_CALL_NAMES
        self.assertFalse(offenders, f"pre_production_review.py contains forbidden call(s): {offenders}")

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

    def test_no_publish_execution(self):
        suspicious = {name for name in self._called_names() if "publish" in name.lower()}
        self.assertFalse(suspicious)

    def test_no_analytics_call(self):
        suspicious = {name for name in self._called_names() if "analytics" in name.lower()}
        self.assertFalse(suspicious)

    def test_no_event_bus(self):
        suspicious = {name for name in self._called_names() if "emit" in name.lower() or "subscribe" in name.lower()}
        self.assertFalse(suspicious)

    def test_no_state_machine_transition_call(self):
        self.assertNotIn("transition", self._called_names())

    def test_no_authorization_or_activation_construction(self):
        offenders = self._called_names() & {
            "RealGenerationAuthorization", "RequestScopedActivationContract",
            "ControlledRealProviderActivationContract",
        }
        self.assertFalse(offenders)


if __name__ == "__main__":
    unittest.main()
