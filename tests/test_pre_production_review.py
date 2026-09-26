"""
Tests — Pre-Production Review (Phase P3.15).

Fully offline: no network, no Higgsfield, no social platform, no OAuth,
no credential of any kind is imported or constructed anywhere in this
file. Verifies `agents/pre_production_review.py` and the new
`AIDirector.review_video_generation_request()` entry point in
`director.py`.
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
from agents.content_agent import ContentAgent, ContentAgentInput
from agents.generation_approval_gate import GenerationRequest
from agents.planner import VideoPlanner
from agents.pre_production_review import (
    PreProductionReview,
    PreProductionReviewError,
    PreProductionReviewInput,
    PreProductionReviewStatus,
    PreProductionReviewer,
    ReadinessFailureCategory,
)
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.script_production_bridge import ProductionPreparationInput, ScriptProductionBridge
from agents.strategy_agent import StrategyAgent, StrategyAgentInput
from agents.video_production_preparation import VideoProductionPreparation, VideoProductionPreparationInput
from director import AIDirector
from integrations.higgsfield.types import MediaReference

MODULE_SOURCE_PATH = PROJECT_ROOT / "agents" / "pre_production_review.py"

VIDEO_005_REQUEST_ID = "005"
VIDEO_005_JOB_TYPE = "seedance_2_0"
VIDEO_005_DURATION = 15
VIDEO_005_RESOLUTION = "720p"
VIDEO_005_ASPECT_RATIO = "9:16"
VIDEO_005_PROMPT_SHA256 = "1c498617adb4603bcf2fc114a9cb9e8fe2219f09285adbff4d1e6c7a10a669e1"
VIDEO_005_AVATAR_SHA256 = "d293e41a63f66fd43afbebee3f7f9f1bd29143b465fa57a18ab4e1df5faf7280"
VIDEO_005_FACE_SHA256 = "df83a97b71cff9a90191c19d15ff989228b9fef2e57c96cf7c76c68652e3a343"


def _real_video_005_plan():
    planner = VideoPlanner(PROJECT_ROOT)
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


def _real_ready_result(request_id="005"):
    script = _real_script_artifact()
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


def _not_ready_result():
    """A BLOCKED production preparation (invalid script) -- generation_request stays None."""
    plan = _real_video_005_plan()
    integration = VideoProductionPreparation()
    return integration.prepare(
        VideoProductionPreparationInput(
            production_input=ProductionPreparationInput(mission_id="mission-005", script_artifact=None),
            video_plan=plan,
        )
    )


def _findings_by_dimension(review):
    return {f.dimension: f for f in review.findings}


class ValidGenerationRequestTests(unittest.TestCase):
    """Tests 1, 20 from the P3.15 mandatory list."""

    def test_valid_generation_request_passes(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertEqual(review.status, PreProductionReviewStatus.PASS)
        self.assertEqual(review.reasons, ())

    def test_readiness_pass(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertEqual(review.status, PreProductionReviewStatus.PASS)
        self.assertTrue(all(f.passed for f in review.findings))


class InvalidGenerationRequestTests(unittest.TestCase):
    """Tests 2, 21 from the P3.15 mandatory list."""

    def test_invalid_generation_request_fails(self):
        result = _real_ready_result()
        tampered_request = dc_replace(result.generation_request, request_id="")
        tampered_result = dc_replace(result, generation_request=tampered_request)
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=tampered_result))
        self.assertEqual(review.status, PreProductionReviewStatus.FAIL)
        self.assertFalse(_findings_by_dimension(review)["request_identity"].passed)

    def test_readiness_fail_when_preparation_not_ready(self):
        result = _not_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertEqual(review.status, PreProductionReviewStatus.FAIL)
        self.assertIsNone(review.generation_request)


class IdentityPreservationTests(unittest.TestCase):
    """Tests 3, 4 from the P3.15 mandatory list."""

    def test_request_id_preservation(self):
        result = _real_ready_result(request_id="custom-005")
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertEqual(review.request_id, "custom-005")

    def test_mission_id_preservation(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertEqual(review.mission_id, "mission-005")


class PromptIntegrityTests(unittest.TestCase):
    """Tests 5, 6, 7, 39 from the P3.15 mandatory list."""

    def test_prompt_integrity_passes_for_real_prompt(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertTrue(_findings_by_dimension(review)["prompt_integrity"].passed)

    def test_prompt_hash_mismatch_fails(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(
            PreProductionReviewInput(preparation_result=result, expected_prompt_sha256="0" * 64)
        )
        self.assertEqual(review.status, PreProductionReviewStatus.FAIL)
        finding = _findings_by_dimension(review)["prompt_integrity"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, ReadinessFailureCategory.INTEGRITY_FAILURE)

    def test_prompt_hash_matches_canonical_video_005_value(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(
            PreProductionReviewInput(preparation_result=result, expected_prompt_sha256=VIDEO_005_PROMPT_SHA256)
        )
        self.assertTrue(_findings_by_dimension(review)["prompt_integrity"].passed)

    def test_prompt_provenance(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        finding = _findings_by_dimension(review)["prompt_provenance"]
        self.assertTrue(finding.passed)
        self.assertIn("PromptAssemblySystem:005", finding.detail)

    def test_no_prompt_rewrite(self):
        result = _real_ready_result()
        original_prompt = result.generation_request.prompt
        PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertEqual(result.generation_request.prompt, original_prompt)


class AssetIntegrityTests(unittest.TestCase):
    """Tests 8, 9, 10, 40, 44 from the P3.15 mandatory list."""

    def test_asset_integrity_passes(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertTrue(_findings_by_dimension(review)["asset_integrity"].passed)

    def test_asset_hash_mismatch_fails(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(
            PreProductionReviewInput(
                preparation_result=result,
                expected_asset_sha256_by_role={"master_avatar": "0" * 64},
            )
        )
        self.assertEqual(review.status, PreProductionReviewStatus.FAIL)
        finding = _findings_by_dimension(review)["asset_integrity"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, ReadinessFailureCategory.INTEGRITY_FAILURE)

    def test_asset_provenance_passes(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertTrue(_findings_by_dimension(review)["asset_provenance"].passed)

    def test_asset_provenance_mismatch_fails(self):
        result = _real_ready_result()
        foreign_ref = MediaReference(role="master_avatar", source="nowhere.png", sha256="f" * 64)
        tampered_request = dc_replace(result.generation_request, start_image=foreign_ref)
        tampered_result = dc_replace(result, generation_request=tampered_request)
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=tampered_result))
        self.assertEqual(review.status, PreProductionReviewStatus.FAIL)
        finding = _findings_by_dimension(review)["asset_provenance"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, ReadinessFailureCategory.MISSING_PROVENANCE)

    def test_no_asset_rewrite(self):
        result = _real_ready_result()
        original_start_image = result.generation_request.start_image
        original_refs = result.generation_request.image_references
        PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertEqual(result.generation_request.start_image, original_start_image)
        self.assertEqual(result.generation_request.image_references, original_refs)


class ModelDurationResolutionTests(unittest.TestCase):
    """Tests 11, 12, 13, 14, 15 from the P3.15 mandatory list."""

    def test_model_job_type_consistency_passes(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertTrue(_findings_by_dimension(review)["model_job_type_consistency"].passed)

    def test_model_job_type_mismatch_fails(self):
        result = _real_ready_result()
        tampered_prepared = dc_replace(result.production_preparation, job_type="a_different_model")
        tampered_result = dc_replace(result, production_preparation=tampered_prepared)
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=tampered_result))
        finding = _findings_by_dimension(review)["model_job_type_consistency"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, ReadinessFailureCategory.CONTRACT_MISMATCH)

    def test_duration_validation_passes(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertTrue(_findings_by_dimension(review)["duration_validation"].passed)

    def test_duration_validation_fails_on_non_positive_duration(self):
        result = _real_ready_result()
        tampered_request = dc_replace(result.generation_request, duration=0)
        tampered_result = dc_replace(result, generation_request=tampered_request)
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=tampered_result))
        self.assertFalse(_findings_by_dimension(review)["duration_validation"].passed)

    def test_resolution_validation_passes(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertTrue(_findings_by_dimension(review)["resolution_validation"].passed)

    def test_resolution_validation_fails_when_missing(self):
        result = _real_ready_result()
        tampered_request = dc_replace(result.generation_request, resolution=None)
        tampered_result = dc_replace(result, generation_request=tampered_request)
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=tampered_result))
        self.assertFalse(_findings_by_dimension(review)["resolution_validation"].passed)

    def test_aspect_ratio_validation_passes(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertTrue(_findings_by_dimension(review)["aspect_ratio_validation"].passed)

    def test_aspect_ratio_validation_fails_when_missing(self):
        result = _real_ready_result()
        tampered_request = dc_replace(result.generation_request, aspect_ratio="")
        tampered_result = dc_replace(result, generation_request=tampered_request)
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=tampered_result))
        self.assertFalse(_findings_by_dimension(review)["aspect_ratio_validation"].passed)

    def test_reference_requirements_pass(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertTrue(_findings_by_dimension(review)["reference_requirements"].passed)

    def test_reference_requirements_fail_when_start_image_dropped(self):
        result = _real_ready_result()
        tampered_request = dc_replace(result.generation_request, start_image=None)
        tampered_result = dc_replace(result, generation_request=tampered_request)
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=tampered_result))
        self.assertFalse(_findings_by_dimension(review)["reference_requirements"].passed)


class MetadataAndContractTests(unittest.TestCase):
    """Tests 16, 17, 45 from the P3.15 mandatory list."""

    def test_metadata_completeness_passes(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertTrue(_findings_by_dimension(review)["metadata_completeness"].passed)

    def test_metadata_completeness_fails_when_prompt_missing(self):
        result = _real_ready_result()
        tampered_request = dc_replace(result.generation_request, prompt="")
        tampered_result = dc_replace(result, generation_request=tampered_request)
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=tampered_result))
        self.assertFalse(_findings_by_dimension(review)["metadata_completeness"].passed)

    def test_contract_version_passes(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertTrue(_findings_by_dimension(review)["contract_version_compatibility"].passed)

    def test_contract_version_mismatch_fails(self):
        result = _real_ready_result()
        tampered_prepared = dc_replace(result.production_preparation, contract_version=999)
        tampered_result = dc_replace(result, production_preparation=tampered_prepared)
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=tampered_result))
        self.assertEqual(review.status, PreProductionReviewStatus.FAIL)
        finding = _findings_by_dimension(review)["contract_version_compatibility"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, ReadinessFailureCategory.CONTRACT_MISMATCH)


class ScriptProvenanceTests(unittest.TestCase):
    """Tests 18, 19 from the P3.15 mandatory list."""

    def test_script_artifact_provenance_passes(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertTrue(_findings_by_dimension(review)["script_artifact_provenance"].passed)

    def test_script_artifact_provenance_fails_when_missing(self):
        result = _not_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        finding = _findings_by_dimension(review)["script_artifact_provenance"]
        self.assertFalse(finding.passed)

    def test_source_artifact_integrity_passes(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertTrue(_findings_by_dimension(review)["source_artifact_integrity"].passed)

    def test_source_artifact_integrity_fails_on_non_final_status(self):
        script = _real_script_artifact()
        tampered_script = dc_replace(script, status="DRAFT")
        pa = PromptAssemblySystem(PROJECT_ROOT)
        assets = AssetPreparationSystem(PROJECT_ROOT)
        bridge = ScriptProductionBridge(prompt_assembly=pa, asset_preparation=assets)
        prepared = bridge.prepare(
            ProductionPreparationInput(mission_id="mission-005", script_artifact=tampered_script, video_id="005")
        )
        # BLOCKED at the bridge level (status != FINAL) -- construct a
        # VideoProductionPreparationResult shape directly to exercise
        # this review dimension in isolation.
        from agents.video_production_preparation import VideoProductionPreparationResult

        fake_result = VideoProductionPreparationResult(
            mission_id="mission-005",
            status=prepared.status,
            reasons=prepared.reasons,
            production_preparation=prepared,
            generation_request=None,
        )
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=fake_result))
        finding = _findings_by_dimension(review)["source_artifact_integrity"]
        self.assertFalse(finding.passed)


class DeterminismIdempotencyTests(unittest.TestCase):
    """Tests 22, 23 from the P3.15 mandatory list."""

    def test_deterministic_review(self):
        result = _real_ready_result()
        review_a = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        review_b = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertEqual(review_a.status, review_b.status)
        self.assertEqual(review_a.findings, review_b.findings)
        self.assertEqual(review_a.content_hash, review_b.content_hash)

    def test_idempotent_repeated_review(self):
        result = _real_ready_result()
        reviewer = PreProductionReviewer()
        request = PreProductionReviewInput(preparation_result=result)
        first = reviewer.review(request)
        second = reviewer.review(request)
        third = reviewer.review(request)
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(second.content_hash, third.content_hash)


class ImmutabilityTests(unittest.TestCase):
    """Tests 24, 25 from the P3.15 mandatory list."""

    def test_immutable_review_input(self):
        result = _real_ready_result()
        request = PreProductionReviewInput(preparation_result=result)
        with self.assertRaises(FrozenInstanceError):
            request.review_id = "tampered"  # type: ignore

    def test_immutable_source_artifact_untouched(self):
        result = _real_ready_result()
        script_before = result.production_preparation.script_artifact
        PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        script_after = result.production_preparation.script_artifact
        self.assertIs(script_before, script_after)
        self.assertEqual(script_before.content_hash, script_after.content_hash)


class AuthoritySeparationTests(unittest.TestCase):
    """Tests 26, 27, 41, 42, 43 from the P3.15 mandatory list."""

    def test_no_state_authority(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertFalse(hasattr(review, "mission_state"))
        self.assertFalse(hasattr(PreProductionReviewer(), "state_machine"))
        self.assertFalse(hasattr(PreProductionReviewer(), "transition"))

    def test_no_authorization_field(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertFalse(hasattr(review, "approved"))
        self.assertFalse(hasattr(review, "authorized"))

    def test_cost_does_not_authorize_no_cost_field(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertFalse(hasattr(review, "cost"))
        self.assertFalse(hasattr(review, "cost_result"))
        self.assertFalse(hasattr(review, "budget"))

    def test_review_pass_does_not_authorize_generation_request(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertEqual(review.status, PreProductionReviewStatus.PASS)
        self.assertFalse(review.generation_request.approved)
        self.assertIsNone(review.generation_request.real_generation_authorization)

    def test_review_fail_semantics_reasons_populated(self):
        result = _not_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertEqual(review.status, PreProductionReviewStatus.FAIL)
        self.assertTrue(review.reasons)
        self.assertTrue(all(isinstance(r, str) and r for r in review.reasons))


class Video005RegressionTests(unittest.TestCase):
    """Test 38 from the P3.15 mandatory list."""

    @classmethod
    def setUpClass(cls):
        cls.result = _real_ready_result(request_id="005")
        cls.review = PreProductionReviewer().review(
            PreProductionReviewInput(
                preparation_result=cls.result,
                expected_prompt_sha256=VIDEO_005_PROMPT_SHA256,
                expected_asset_sha256_by_role={
                    "master_avatar": VIDEO_005_AVATAR_SHA256,
                    "face_reference": VIDEO_005_FACE_SHA256,
                },
            )
        )

    def test_video_005_review_passes(self):
        self.assertEqual(self.review.status, PreProductionReviewStatus.PASS)

    def test_video_005_identity_preserved(self):
        self.assertEqual(self.review.request_id, VIDEO_005_REQUEST_ID)
        self.assertEqual(self.review.generation_request.job_type, VIDEO_005_JOB_TYPE)
        self.assertEqual(self.review.generation_request.duration, VIDEO_005_DURATION)
        self.assertEqual(self.review.generation_request.resolution, VIDEO_005_RESOLUTION)
        self.assertEqual(self.review.generation_request.aspect_ratio, VIDEO_005_ASPECT_RATIO)

    def test_video_005_still_not_authorized(self):
        self.assertFalse(self.review.generation_request.approved)
        self.assertIsNone(self.review.generation_request.real_generation_authorization)


class MissionIdPropagationTests(unittest.TestCase):
    """Additional traceability regression, mirrors P3.14 test 35."""

    def test_mission_id_propagation(self):
        result = _real_ready_result()
        result = dc_replace(result, mission_id="mission-xyz-should-mismatch")
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        finding = _findings_by_dimension(review)["mission_identity"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, ReadinessFailureCategory.CONTRACT_MISMATCH)


class InvalidInputTests(unittest.TestCase):
    """Structural input-validation regression."""

    def test_invalid_preparation_result_raises_explicitly(self):
        with self.assertRaises(PreProductionReviewError):
            PreProductionReviewer().review(
                PreProductionReviewInput(preparation_result="not-a-preparation-result")  # type: ignore
            )


class DirectorIntegrationTests(unittest.TestCase):
    """Test 35 from the P3.15 mandatory list."""

    def test_director_exposes_review_video_generation_request(self):
        director = AIDirector()
        self.assertTrue(hasattr(director, "review_video_generation_request"))

    def test_director_delegates_to_injected_reviewer(self):
        result = _real_ready_result()
        director = AIDirector()
        review = director.review_video_generation_request(
            PreProductionReviewInput(preparation_result=result), reviewer=PreProductionReviewer()
        )
        self.assertIsInstance(review, PreProductionReview)
        self.assertEqual(review.status, PreProductionReviewStatus.PASS)

    def test_director_default_reviewer_used_without_injection(self):
        result = _real_ready_result()
        director = AIDirector()
        review = director.review_video_generation_request(PreProductionReviewInput(preparation_result=result))
        self.assertEqual(review.status, PreProductionReviewStatus.PASS)

    def test_existing_methods_unaffected(self):
        director = AIDirector()
        self.assertTrue(hasattr(director, "run_business_pipeline"))
        self.assertTrue(hasattr(director, "run_video_mission"))
        self.assertTrue(hasattr(director, "prepare_production_from_script"))
        self.assertTrue(hasattr(director, "prepare_video_generation_request"))

    def test_not_invoked_automatically_by_prepare(self):
        # review_video_generation_request must never be called as a side
        # effect of prepare_video_generation_request -- the P3.14 method's
        # own source is unaffected.
        director_source = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        tree = ast.parse(director_source)
        prepare_method = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "prepare_video_generation_request":
                prepare_method = node
                break
        self.assertIsNotNone(prepare_method)
        called_names = set()
        for node in ast.walk(prepare_method):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    called_names.add(func.attr)
        self.assertNotIn("review_video_generation_request", called_names)


class StateBoundaryTests(unittest.TestCase):
    """Test 36 from the P3.15 mandatory list."""

    def test_no_state_authority_on_result_or_reviewer(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertFalse(hasattr(review, "mission_state"))
        self.assertFalse(hasattr(PreProductionReviewer(), "state_machine"))
        self.assertFalse(hasattr(PreProductionReviewer(), "transition"))


class SecurityTests(unittest.TestCase):
    """
    Tests 28-33, 37 from the P3.15 mandatory list: AST-based,
    docstring-false-positive-safe (P3.5-P3.14 lesson), static
    verification that `agents/pre_production_review.py` never reaches
    real execution, any P2 authority mechanism beyond the legitimate
    `GenerationRequest` TYPE import (same precedent as `agents/
    video_agent.py`/`agents/video_production_preparation.py`), the
    Mission State Machine, or an event bus.
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

    def test_generation_approval_gate_imported_for_type_only(self):
        names = self._imported_names_from("agents.generation_approval_gate")
        self.assertTrue(names)
        self.assertNotIn("GenerationApprovalGate", names)
        self.assertNotIn("RealGenerationAuthorization", names)

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

    def test_no_event_bus(self):
        suspicious = {name for name in self._called_names() if "emit" in name.lower() or "subscribe" in name.lower()}
        self.assertFalse(suspicious)

    def test_no_publish_execution(self):
        suspicious = {name for name in self._called_names() if "publish" in name.lower()}
        self.assertFalse(suspicious)

    def test_no_state_machine_transition_call(self):
        self.assertNotIn("transition", self._called_names())

    def test_no_dataclasses_replace_used_in_module(self):
        # This module never mutates/reconstructs the immutable objects it
        # reviews -- unlike this TEST file, which legitimately uses
        # dataclasses.replace only to build tampered fixtures.
        names = self._imported_names_from("dataclasses")
        self.assertNotIn("replace", names)

    def test_reviewer_and_bridge_video_agent_not_reimplemented(self):
        class_defs = {node.name for node in ast.walk(self.tree) if isinstance(node, ast.ClassDef)}
        self.assertNotIn("ScriptProductionBridge", class_defs)
        self.assertNotIn("VideoAgent", class_defs)
        self.assertNotIn("VideoProductionPreparation", class_defs)

    def test_director_py_new_method_has_no_forbidden_calls(self):
        director_source = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        tree = ast.parse(director_source)
        method_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "review_video_generation_request":
                method_node = node
                break
        self.assertIsNotNone(method_node, "review_video_generation_request method not found in director.py")

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
        self.assertFalse(offenders, f"review_video_generation_request contains forbidden call(s): {offenders}")


if __name__ == "__main__":
    unittest.main()
