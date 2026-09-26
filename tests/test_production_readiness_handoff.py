"""
Tests — Production Readiness Handoff (Phase P3.17).

Fully offline: no network, no Higgsfield, no social platform, no OAuth,
no credential of any kind is imported or constructed anywhere in this
file. Verifies `agents/production_readiness_handoff.py` and the new
`AIDirector.handoff_video_generation_request()` entry point in
`director.py`.
"""

import ast
import sys
import unittest
from dataclasses import FrozenInstanceError, replace as dc_replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.asset_preparation_system import AssetPreparationSystem
from agents.content_agent import ContentAgent, ContentAgentInput
from agents.planner import VideoPlanner
from agents.pre_production_review import (
    PreProductionReview,
    PreProductionReviewInput,
    PreProductionReviewer,
    PreProductionReviewStatus,
)
from agents.production_readiness_handoff import (
    HandoffFailureCategory,
    ProductionReadinessHandoff,
    ProductionReadinessHandoffBuilder,
    ProductionReadinessHandoffError,
    ProductionReadinessHandoffInput,
    ProductionReadinessHandoffStatus,
)
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.script_production_bridge import ProductionPreparationInput, ScriptProductionBridge
from agents.strategy_agent import StrategyAgent, StrategyAgentInput
from agents.video_production_preparation import VideoProductionPreparation, VideoProductionPreparationInput
from director import AIDirector
from integrations.higgsfield.types import MediaReference

MODULE_SOURCE_PATH = PROJECT_ROOT / "agents" / "production_readiness_handoff.py"

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


def _pass_review(request_id="005", **review_kwargs):
    result = _real_ready_result(request_id=request_id)
    return PreProductionReviewer().review(
        PreProductionReviewInput(preparation_result=result, **review_kwargs)
    )


def _fail_review():
    result = _not_ready_result()
    return PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))


def _findings_by_dimension(handoff):
    return {f.dimension: f for f in handoff.findings}


class ValidPassReviewTests(unittest.TestCase):
    """Test 1 from the P3.17 mandatory list."""

    def test_pass_review_yields_ready_handoff(self):
        review = _pass_review()
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        self.assertEqual(handoff.status, ProductionReadinessHandoffStatus.READY_FOR_PRODUCTION_AUTHORITY)
        self.assertEqual(handoff.reasons, ())
        self.assertTrue(all(f.passed for f in handoff.findings))


class FailReviewTests(unittest.TestCase):
    """Test 2 from the P3.17 mandatory list."""

    def test_fail_review_yields_not_ready_handoff(self):
        review = _fail_review()
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        self.assertEqual(handoff.status, ProductionReadinessHandoffStatus.NOT_READY)
        self.assertTrue(handoff.reasons)
        finding = _findings_by_dimension(handoff)["review_status_readiness"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, HandoffFailureCategory.REVIEW_NOT_PASS)

    def test_fail_review_never_silently_upgraded(self):
        review = _fail_review()
        self.assertEqual(review.status, PreProductionReviewStatus.FAIL)
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        self.assertNotEqual(handoff.status, ProductionReadinessHandoffStatus.READY_FOR_PRODUCTION_AUTHORITY)


class HandoffCreationTests(unittest.TestCase):
    """Test 3 from the P3.17 mandatory list."""

    def test_handoff_fields_populated(self):
        review = _pass_review()
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        self.assertTrue(handoff.handoff_id)
        self.assertEqual(handoff.artifact_type, "ProductionReadinessHandoff")
        self.assertTrue(handoff.created_at)
        self.assertEqual(handoff.contract_version, 1)
        self.assertEqual(handoff.producer_agent, "production-readiness-handoff")
        self.assertTrue(handoff.content_hash)

    def test_custom_handoff_id_honored(self):
        review = _pass_review()
        handoff = ProductionReadinessHandoffBuilder().build(
            ProductionReadinessHandoffInput(review=review, handoff_id="custom-handoff-1")
        )
        self.assertEqual(handoff.handoff_id, "custom-handoff-1")


class HandoffIdentityTests(unittest.TestCase):
    """Test 4 from the P3.17 mandatory list."""

    def test_expected_review_id_match_passes(self):
        review = _pass_review()
        handoff = ProductionReadinessHandoffBuilder().build(
            ProductionReadinessHandoffInput(review=review, expected_review_id=review.review_id)
        )
        self.assertEqual(handoff.status, ProductionReadinessHandoffStatus.READY_FOR_PRODUCTION_AUTHORITY)

    def test_expected_review_id_mismatch_fails(self):
        review = _pass_review()
        handoff = ProductionReadinessHandoffBuilder().build(
            ProductionReadinessHandoffInput(review=review, expected_review_id="not-the-real-review-id")
        )
        self.assertEqual(handoff.status, ProductionReadinessHandoffStatus.NOT_READY)
        finding = _findings_by_dimension(handoff)["expected_review_id_pin"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, HandoffFailureCategory.STALE_OR_MISMATCHED_REVIEW)


class RequestIdentityTests(unittest.TestCase):
    """Tests 5, 7 from the P3.17 mandatory list."""

    def test_request_id_preserved(self):
        review = _pass_review(request_id="custom-005")
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        self.assertEqual(handoff.request_id, "custom-005")

    def test_expected_request_id_mismatch_fails(self):
        review = _pass_review()
        handoff = ProductionReadinessHandoffBuilder().build(
            ProductionReadinessHandoffInput(review=review, expected_request_id="not-the-real-request-id")
        )
        self.assertEqual(handoff.status, ProductionReadinessHandoffStatus.NOT_READY)
        finding = _findings_by_dimension(handoff)["expected_request_id_pin"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, HandoffFailureCategory.STALE_OR_MISMATCHED_REVIEW)

    def test_request_identity_consistency_detects_swapped_generation_request(self):
        review = _pass_review()
        tampered_gr = dc_replace(review.generation_request, request_id="swapped-id")
        tampered_review = dc_replace(review, generation_request=tampered_gr)
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=tampered_review))
        self.assertEqual(handoff.status, ProductionReadinessHandoffStatus.NOT_READY)
        finding = _findings_by_dimension(handoff)["request_identity_consistency"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, HandoffFailureCategory.CONTRACT_MISMATCH)


class ArtifactMutationDetectionTests(unittest.TestCase):
    """Tests 6, 14 from the P3.17 mandatory list."""

    def test_mission_identity_consistency_detects_swapped_production_preparation(self):
        review = _pass_review()
        tampered_prepared = dc_replace(review.production_preparation, mission_id="a-different-mission")
        tampered_review = dc_replace(review, production_preparation=tampered_prepared)
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=tampered_review))
        self.assertEqual(handoff.status, ProductionReadinessHandoffStatus.NOT_READY)
        finding = _findings_by_dimension(handoff)["mission_identity_consistency"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, HandoffFailureCategory.CONTRACT_MISMATCH)


class PromptAssetModelMetadataPropagationTests(unittest.TestCase):
    """Tests 8, 9, 10, 11 from the P3.17 mandatory list -- verifies
    handoff PROPAGATES P3.15's own findings rather than re-deriving
    them (Section 5 reuse instruction)."""

    def test_prompt_integrity_visible_through_embedded_review(self):
        review = _pass_review()
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        review_findings = {f.dimension: f for f in handoff.review.findings}
        self.assertTrue(review_findings["prompt_integrity"].passed)

    def test_asset_integrity_visible_through_embedded_review(self):
        review = _pass_review()
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        review_findings = {f.dimension: f for f in handoff.review.findings}
        self.assertTrue(review_findings["asset_integrity"].passed)

    def test_model_consistency_visible_through_embedded_review(self):
        review = _pass_review()
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        review_findings = {f.dimension: f for f in handoff.review.findings}
        self.assertTrue(review_findings["model_job_type_consistency"].passed)

    def test_metadata_completeness_visible_through_embedded_review(self):
        review = _pass_review()
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        review_findings = {f.dimension: f for f in handoff.review.findings}
        self.assertTrue(review_findings["metadata_completeness"].passed)

    def test_review_fail_from_asset_mismatch_propagates_to_handoff(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(
            PreProductionReviewInput(
                preparation_result=result,
                expected_asset_sha256_by_role={"master_avatar": "0" * 64},
            )
        )
        self.assertEqual(review.status, PreProductionReviewStatus.FAIL)
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        self.assertEqual(handoff.status, ProductionReadinessHandoffStatus.NOT_READY)


class ProvenanceTests(unittest.TestCase):
    """Test 12 from the P3.17 mandatory list."""

    def test_full_traceability_chain_reachable(self):
        review = _pass_review()
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        self.assertEqual(handoff.mission_id, "mission-005")
        self.assertEqual(handoff.review.production_preparation.mission_id, "mission-005")
        self.assertIsNotNone(handoff.review.production_preparation.script_artifact)
        self.assertEqual(handoff.review.production_preparation.script_artifact.mission_id, "mission-005")
        self.assertEqual(handoff.review.generation_request.request_id, handoff.request_id)
        self.assertEqual(handoff.review_id, handoff.review.review_id)


class StaleReviewTests(unittest.TestCase):
    """Test 15 from the P3.17 mandatory list."""

    def test_stale_review_via_review_id_pin_never_silently_ready(self):
        review = _pass_review()
        handoff = ProductionReadinessHandoffBuilder().build(
            ProductionReadinessHandoffInput(review=review, expected_review_id="stale-review-id")
        )
        self.assertEqual(handoff.status, ProductionReadinessHandoffStatus.NOT_READY)


class RequestMismatchTests(unittest.TestCase):
    """Test 16 from the P3.17 mandatory list."""

    def test_request_mismatch_via_request_id_pin_never_silently_ready(self):
        review = _pass_review()
        handoff = ProductionReadinessHandoffBuilder().build(
            ProductionReadinessHandoffInput(review=review, expected_request_id="some-other-request")
        )
        self.assertEqual(handoff.status, ProductionReadinessHandoffStatus.NOT_READY)


class IntegrityMismatchTests(unittest.TestCase):
    """Test 17 from the P3.17 mandatory list."""

    def test_tampered_content_hash_detected(self):
        review = _pass_review()
        tampered_review = dc_replace(review, content_hash="0" * 64)
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=tampered_review))
        self.assertEqual(handoff.status, ProductionReadinessHandoffStatus.NOT_READY)
        finding = _findings_by_dimension(handoff)["review_integrity"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, HandoffFailureCategory.INTEGRITY_FAILURE)


class ContractMismatchTests(unittest.TestCase):
    """Test 18 from the P3.17 mandatory list."""

    def test_unsupported_review_contract_version_fails(self):
        review = _pass_review()
        tampered_review = dc_replace(review, contract_version=999)
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=tampered_review))
        self.assertEqual(handoff.status, ProductionReadinessHandoffStatus.NOT_READY)
        finding = _findings_by_dimension(handoff)["review_contract_version_compatibility"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, HandoffFailureCategory.CONTRACT_MISMATCH)


class DeterminismIdempotencyTests(unittest.TestCase):
    """Tests 19, 20 from the P3.17 mandatory list."""

    def test_deterministic_handoff(self):
        review = _pass_review()
        handoff_a = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        handoff_b = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        self.assertEqual(handoff_a.status, handoff_b.status)
        self.assertEqual(handoff_a.findings, handoff_b.findings)
        self.assertEqual(handoff_a.content_hash, handoff_b.content_hash)

    def test_idempotent_repeated_build(self):
        review = _pass_review()
        builder = ProductionReadinessHandoffBuilder()
        request = ProductionReadinessHandoffInput(review=review)
        first = builder.build(request)
        second = builder.build(request)
        third = builder.build(request)
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(second.content_hash, third.content_hash)


class ImmutableInputTests(unittest.TestCase):
    """Test 21 from the P3.17 mandatory list."""

    def test_immutable_handoff_input(self):
        review = _pass_review()
        request = ProductionReadinessHandoffInput(review=review)
        with self.assertRaises(FrozenInstanceError):
            request.handoff_id = "tampered"  # type: ignore

    def test_immutable_handoff_output(self):
        review = _pass_review()
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        with self.assertRaises(FrozenInstanceError):
            handoff.status = ProductionReadinessHandoffStatus.NOT_READY  # type: ignore

    def test_source_review_untouched(self):
        review = _pass_review()
        review_id_before = review.review_id
        content_hash_before = review.content_hash
        ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        self.assertEqual(review.review_id, review_id_before)
        self.assertEqual(review.content_hash, content_hash_before)


class NoAuthorizationTests(unittest.TestCase):
    """Test 22 from the P3.17 mandatory list."""

    def test_no_authorization_field(self):
        review = _pass_review()
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        self.assertFalse(hasattr(handoff, "approved"))
        self.assertFalse(hasattr(handoff, "authorized"))
        self.assertFalse(hasattr(handoff, "authorization"))

    def test_handoff_never_created_from_already_authorized_request(self):
        review = _pass_review()
        from agents.generation_approval_gate import RealGenerationAuthorization

        auth = RealGenerationAuthorization(request_id=review.generation_request.request_id, authorized_by_human=True)
        tampered_gr = dc_replace(review.generation_request, approved=True, real_generation_authorization=auth)
        tampered_review = dc_replace(review, generation_request=tampered_gr)
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=tampered_review))
        self.assertEqual(handoff.status, ProductionReadinessHandoffStatus.NOT_READY)
        finding = _findings_by_dimension(handoff)["not_already_authorized"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, HandoffFailureCategory.INTERNAL_HANDOFF_FAILURE)


class NoActivationTests(unittest.TestCase):
    """Test 23 from the P3.17 mandatory list."""

    def test_no_activation_field(self):
        review = _pass_review()
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        self.assertFalse(hasattr(handoff, "activated"))
        self.assertFalse(hasattr(handoff, "activation_contract"))
        self.assertFalse(hasattr(handoff, "provider_activation_contract"))


class AuthoritySeparationTests(unittest.TestCase):
    """Test 33 from the P3.17 mandatory list."""

    def test_status_values_never_imply_authority_beyond_readiness(self):
        values = {member.value for member in ProductionReadinessHandoffStatus}
        self.assertEqual(values, {"READY_FOR_PRODUCTION_AUTHORITY", "NOT_READY"})
        for forbidden in ("AUTHORIZED", "ACTIVATED", "EXECUTING", "EXECUTED"):
            self.assertNotIn(forbidden, values)

    def test_no_executing_field(self):
        review = _pass_review()
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        self.assertFalse(hasattr(handoff, "executing"))
        self.assertFalse(hasattr(handoff, "executed"))
        self.assertFalse(hasattr(handoff, "job"))
        self.assertFalse(hasattr(handoff, "job_id"))


class StateBoundaryTests(unittest.TestCase):
    """Test 32 from the P3.17 mandatory list."""

    def test_no_state_authority(self):
        review = _pass_review()
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        self.assertFalse(hasattr(handoff, "mission_state"))
        self.assertFalse(hasattr(ProductionReadinessHandoffBuilder(), "state_machine"))
        self.assertFalse(hasattr(ProductionReadinessHandoffBuilder(), "transition"))


class InvalidInputTests(unittest.TestCase):
    """Structural input-validation regression, mirrors P3.15's own."""

    def test_invalid_review_raises_explicitly(self):
        with self.assertRaises(ProductionReadinessHandoffError):
            ProductionReadinessHandoffBuilder().build(
                ProductionReadinessHandoffInput(review="not-a-review")  # type: ignore
            )


class DirectorIntegrationTests(unittest.TestCase):
    """Test 31 from the P3.17 mandatory list."""

    def test_director_exposes_handoff_video_generation_request(self):
        director = AIDirector()
        self.assertTrue(hasattr(director, "handoff_video_generation_request"))

    def test_director_delegates_to_injected_builder(self):
        review = _pass_review()
        director = AIDirector()
        handoff = director.handoff_video_generation_request(
            ProductionReadinessHandoffInput(review=review), builder=ProductionReadinessHandoffBuilder()
        )
        self.assertIsInstance(handoff, ProductionReadinessHandoff)
        self.assertEqual(handoff.status, ProductionReadinessHandoffStatus.READY_FOR_PRODUCTION_AUTHORITY)

    def test_director_default_builder_used_without_injection(self):
        review = _pass_review()
        director = AIDirector()
        handoff = director.handoff_video_generation_request(ProductionReadinessHandoffInput(review=review))
        self.assertEqual(handoff.status, ProductionReadinessHandoffStatus.READY_FOR_PRODUCTION_AUTHORITY)

    def test_existing_methods_unaffected(self):
        director = AIDirector()
        self.assertTrue(hasattr(director, "run_business_pipeline"))
        self.assertTrue(hasattr(director, "run_video_mission"))
        self.assertTrue(hasattr(director, "prepare_production_from_script"))
        self.assertTrue(hasattr(director, "prepare_video_generation_request"))
        self.assertTrue(hasattr(director, "review_video_generation_request"))

    def test_not_invoked_automatically_by_review(self):
        director_source = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        tree = ast.parse(director_source)
        review_method = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "review_video_generation_request":
                review_method = node
                break
        self.assertIsNotNone(review_method)
        called_names = set()
        for node in ast.walk(review_method):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    called_names.add(func.attr)
        self.assertNotIn("handoff_video_generation_request", called_names)

    def test_not_invoked_automatically_by_prepare(self):
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
        self.assertNotIn("handoff_video_generation_request", called_names)

    def test_director_py_new_method_has_no_forbidden_calls(self):
        director_source = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        tree = ast.parse(director_source)
        method_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "handoff_video_generation_request":
                method_node = node
                break
        self.assertIsNotNone(method_node, "handoff_video_generation_request method not found in director.py")

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
        self.assertFalse(offenders, f"handoff_video_generation_request contains forbidden call(s): {offenders}")


class CompatibilityTests(unittest.TestCase):
    """Tests 34-37, 40 from the P3.17 mandatory list -- P3.13/14/15/16
    regression protection: the full real chain still composes end to
    end through the new handoff layer."""

    def test_full_chain_script_bridge_through_handoff(self):
        script = _real_script_artifact()
        plan = _real_video_005_plan()
        pa = PromptAssemblySystem(PROJECT_ROOT)
        assets = AssetPreparationSystem(PROJECT_ROOT)

        bridge = ScriptProductionBridge(prompt_assembly=pa, asset_preparation=assets)
        prepared = bridge.prepare(
            ProductionPreparationInput(mission_id="mission-005", script_artifact=script, video_id="005")
        )
        self.assertEqual(prepared.status.value, "READY")

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

        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        self.assertEqual(review.status, PreProductionReviewStatus.PASS)

        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        self.assertEqual(handoff.status, ProductionReadinessHandoffStatus.READY_FOR_PRODUCTION_AUTHORITY)
        self.assertEqual(handoff.mission_id, "mission-005")
        self.assertEqual(handoff.request_id, "005")

    def test_duration_policy_p3_16_unaffected(self):
        # P3.16's Option D duration policy must remain untouched: script
        # planning target (30s) and technical production duration (15s)
        # for Video 005 stay intentionally different, never forced equal.
        review = _pass_review()
        self.assertEqual(review.production_preparation.duration_seconds, 30)
        self.assertEqual(review.generation_request.duration, 15)
        handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        self.assertEqual(handoff.status, ProductionReadinessHandoffStatus.READY_FOR_PRODUCTION_AUTHORITY)


class Video005RegressionTests(unittest.TestCase):
    """Test 38 from the P3.17 mandatory list."""

    @classmethod
    def setUpClass(cls):
        cls.review = _pass_review(
            request_id="005",
            expected_prompt_sha256=VIDEO_005_PROMPT_SHA256,
            expected_asset_sha256_by_role={
                "master_avatar": VIDEO_005_AVATAR_SHA256,
                "face_reference": VIDEO_005_FACE_SHA256,
            },
        )
        cls.handoff = ProductionReadinessHandoffBuilder().build(
            ProductionReadinessHandoffInput(review=cls.review)
        )

    def test_video_005_handoff_ready(self):
        self.assertEqual(self.handoff.status, ProductionReadinessHandoffStatus.READY_FOR_PRODUCTION_AUTHORITY)

    def test_video_005_identity_preserved(self):
        self.assertEqual(self.handoff.request_id, VIDEO_005_REQUEST_ID)
        self.assertEqual(self.handoff.review.generation_request.job_type, VIDEO_005_JOB_TYPE)
        self.assertEqual(self.handoff.review.generation_request.duration, VIDEO_005_DURATION)
        self.assertEqual(self.handoff.review.generation_request.resolution, VIDEO_005_RESOLUTION)
        self.assertEqual(self.handoff.review.generation_request.aspect_ratio, VIDEO_005_ASPECT_RATIO)

    def test_video_005_still_not_authorized(self):
        self.assertFalse(self.handoff.review.generation_request.approved)
        self.assertIsNone(self.handoff.review.generation_request.real_generation_authorization)


class SecurityTests(unittest.TestCase):
    """
    Tests 24-30, 39 from the P3.17 mandatory list: AST-based,
    docstring-false-positive-safe, static verification that
    `agents/production_readiness_handoff.py` never reaches real
    execution, any P2 authority mechanism beyond the legitimate
    `PreProductionReview` reuse, the Mission State Machine, or an
    event bus.
    """

    FORBIDDEN_MODULES = {
        "integrations.higgsfield.client",
        "integrations.higgsfield.provider",
        "integrations.higgsfield.mock_provider",
        "agents.generation_approval_gate",
        "agents.generation_job_service",
        "agents.generation_cost_service",
        "agents.cost_engine",
        "agents.activation_contract",
        "agents.controlled_real_provider_activation",
        "agents.real_provider_execution_gate",
        "agents.real_provider_activation_preflight",
        "agents.activation_readiness",
        "agents.production_activation_boundary",
        "agents.critical_section_lock",
        "agents.executed_request_store",
        "agents.final_report_service",
        "agents.mission_state_machine",
        "agents.publishing_agent",
        "agents.analytics_agent",
        "agents.video_agent",
        "agents.video_production_preparation",
        "agents.script_production_bridge",
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
        self.assertFalse(offenders, f"production_readiness_handoff.py imports forbidden module(s): {offenders}")

    def test_no_forbidden_calls(self):
        offenders = self._called_names() & self.FORBIDDEN_CALL_NAMES
        self.assertFalse(offenders, f"production_readiness_handoff.py contains forbidden call(s): {offenders}")

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

    def test_no_publish_or_analytics_execution(self):
        suspicious = {
            name for name in self._called_names()
            if "publish" in name.lower() or "analytic" in name.lower()
        }
        self.assertFalse(suspicious)

    def test_no_state_machine_transition_call(self):
        self.assertNotIn("transition", self._called_names())

    def test_no_dataclasses_replace_used_in_module(self):
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module == "dataclasses":
                for alias in node.names:
                    names.add(alias.name)
        self.assertNotIn("replace", names)

    def test_pre_production_reviewer_not_reimplemented(self):
        class_defs = {node.name for node in ast.walk(self.tree) if isinstance(node, ast.ClassDef)}
        self.assertNotIn("PreProductionReviewer", class_defs)
        self.assertNotIn("ScriptProductionBridge", class_defs)
        self.assertNotIn("VideoAgent", class_defs)
        self.assertNotIn("VideoProductionPreparation", class_defs)

    def test_p2_boundary_never_crossed(self):
        # Test 39 from the P3.17 mandatory list.
        p2_modules = {
            "agents.generation_approval_gate",
            "agents.generation_job_service",
            "agents.activation_contract",
            "agents.controlled_real_provider_activation",
            "agents.critical_section_lock",
            "agents.executed_request_store",
            "integrations.higgsfield.provider",
            "integrations.higgsfield.client",
        }
        offenders = self._imported_modules() & p2_modules
        self.assertFalse(offenders, f"production_readiness_handoff.py crosses the P2 boundary: {offenders}")


if __name__ == "__main__":
    unittest.main()
