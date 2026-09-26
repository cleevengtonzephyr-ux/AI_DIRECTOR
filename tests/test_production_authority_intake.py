"""
Tests — Production Authority Intake (Phase P3.18).

Fully offline: no network, no Higgsfield, no social platform, no OAuth,
no credential of any kind is imported or constructed anywhere in this
file. Verifies `agents/production_authority_intake.py` and the new
`AIDirector.production_authority_intake()` entry point in `director.py`.
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
    PreProductionReviewInput,
    PreProductionReviewer,
    PreProductionReviewStatus,
)
from agents.production_authority_intake import (
    IntakeFailureCategory,
    ProductionAuthorityIntake,
    ProductionAuthorityIntakeError,
    ProductionAuthorityIntakeInput,
    ProductionAuthorityIntakeReport,
    ProductionAuthorityIntakeStatus,
)
from agents.production_readiness_handoff import (
    ProductionReadinessHandoffBuilder,
    ProductionReadinessHandoffInput,
    ProductionReadinessHandoffStatus,
)
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.script_production_bridge import ProductionPreparationInput
from agents.strategy_agent import StrategyAgent, StrategyAgentInput
from agents.video_production_preparation import VideoProductionPreparation, VideoProductionPreparationInput
from director import AIDirector

MODULE_SOURCE_PATH = PROJECT_ROOT / "agents" / "production_authority_intake.py"

VIDEO_005_REQUEST_ID = "005"
VIDEO_005_JOB_TYPE = "seedance_2_0"
VIDEO_005_DURATION = 15
VIDEO_005_RESOLUTION = "720p"
VIDEO_005_ASPECT_RATIO = "9:16"
VIDEO_005_PROMPT_SHA256 = "1c498617adb4603bcf2fc114a9cb9e8fe2219f09285adbff4d1e6c7a10a669e1"


def _real_video_005_plan():
    planner = VideoPlanner(PROJECT_ROOT)
    return planner.create_zephyr_plan(
        video_id="005",
        title="Pourquoi la discipline vaut plus que le talent.",
        hook="Le talent impressionne. La discipline construit des empires.",
        objective="Créer une vidéo courte, cinématique et motivante.",
    )


def _real_script_artifact(mission_id: str = "mission-005"):
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
    return content.script_artifact


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
    plan = _real_video_005_plan()
    integration = VideoProductionPreparation()
    return integration.prepare(
        VideoProductionPreparationInput(
            production_input=ProductionPreparationInput(mission_id="mission-005", script_artifact=None),
            video_plan=plan,
        )
    )


def _ready_handoff(request_id="005", **review_kwargs):
    result = _real_ready_result(request_id=request_id)
    review = PreProductionReviewer().review(
        PreProductionReviewInput(preparation_result=result, **review_kwargs)
    )
    return ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))


def _not_ready_handoff():
    result = _not_ready_result()
    review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
    return ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))


def _findings_by_dimension(report):
    return {f.dimension: f for f in report.findings}


def _module_code_without_docstrings():
    """Source of agents/production_authority_intake.py with every
    module/class/function docstring stripped -- so raw-substring
    boundary checks below never false-positive on this module's own
    prose (which legitimately narrates forbidden concepts by name,
    e.g. explaining why GenerationApprovalGate is never touched)."""

    source = MODULE_SOURCE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    docstring_nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                docstring_nodes.add(node.body[0].value)
    lines = source.splitlines(keepends=True)
    for doc_node in sorted(docstring_nodes, key=lambda n: n.lineno, reverse=True):
        start = doc_node.lineno - 1
        end = doc_node.end_lineno
        lines = lines[:start] + lines[end:]
    return "".join(lines)


class ValidReadyHandoffTests(unittest.TestCase):
    """Test 1 from the P3.18 mandatory list."""

    def test_ready_handoff_accepted(self):
        handoff = _ready_handoff()
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))
        self.assertEqual(report.status, ProductionAuthorityIntakeStatus.ACCEPTED_FOR_P2_CONSIDERATION)
        self.assertEqual(report.reasons, ())
        self.assertTrue(all(f.passed for f in report.findings))


class NotReadyHandoffTests(unittest.TestCase):
    """Test 2 from the P3.18 mandatory list."""

    def test_not_ready_handoff_rejected(self):
        handoff = _not_ready_handoff()
        self.assertEqual(handoff.status, ProductionReadinessHandoffStatus.NOT_READY)
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))
        self.assertEqual(report.status, ProductionAuthorityIntakeStatus.REJECTED)
        finding = _findings_by_dimension(report)["handoff_status_ready"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, IntakeFailureCategory.HANDOFF_NOT_READY)


class MalformedHandoffTests(unittest.TestCase):
    """Test 3 from the P3.18 mandatory list."""

    def test_non_handoff_input_raises_explicitly(self):
        with self.assertRaises(ProductionAuthorityIntakeError):
            ProductionAuthorityIntake().intake(
                ProductionAuthorityIntakeInput(handoff="not-a-handoff")  # type: ignore
            )

    def test_wrong_artifact_type_rejected(self):
        handoff = _ready_handoff()
        tampered = dc_replace(handoff, artifact_type="SomethingElse")
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=tampered))
        self.assertEqual(report.status, ProductionAuthorityIntakeStatus.REJECTED)
        finding = _findings_by_dimension(report)["handoff_structural_validity"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, IntakeFailureCategory.INVALID_INPUT)


class StaleHandoffTests(unittest.TestCase):
    """Test 4 from the P3.18 mandatory list."""

    def test_expected_handoff_id_mismatch_is_stale(self):
        handoff = _ready_handoff()
        report = ProductionAuthorityIntake().intake(
            ProductionAuthorityIntakeInput(handoff=handoff, expected_handoff_id="not-the-real-id")
        )
        self.assertEqual(report.status, ProductionAuthorityIntakeStatus.REJECTED)
        finding = _findings_by_dimension(report)["expected_handoff_id_pin"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, IntakeFailureCategory.STALE_OR_MISMATCHED_HANDOFF)


class RequestIdentityTests(unittest.TestCase):
    """Tests 5, 6 from the P3.18 mandatory list."""

    def test_request_identity_match_accepted(self):
        handoff = _ready_handoff(request_id="custom-005")
        report = ProductionAuthorityIntake().intake(
            ProductionAuthorityIntakeInput(handoff=handoff, expected_request_id="custom-005")
        )
        self.assertEqual(report.status, ProductionAuthorityIntakeStatus.ACCEPTED_FOR_P2_CONSIDERATION)
        self.assertEqual(report.request_id, "custom-005")

    def test_request_identity_mismatch_rejected(self):
        handoff = _ready_handoff()
        report = ProductionAuthorityIntake().intake(
            ProductionAuthorityIntakeInput(handoff=handoff, expected_request_id="some-other-request")
        )
        self.assertEqual(report.status, ProductionAuthorityIntakeStatus.REJECTED)
        finding = _findings_by_dimension(report)["expected_request_id_pin"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, IntakeFailureCategory.STALE_OR_MISMATCHED_HANDOFF)

    def test_swapped_generation_request_detected(self):
        handoff = _ready_handoff()
        tampered_gr = dc_replace(handoff.review.generation_request, request_id="swapped-id")
        tampered_review = dc_replace(handoff.review, generation_request=tampered_gr)
        tampered_handoff = dc_replace(handoff, review=tampered_review)
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=tampered_handoff))
        self.assertEqual(report.status, ProductionAuthorityIntakeStatus.REJECTED)
        finding = _findings_by_dimension(report)["identity_chain_consistency"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, IntakeFailureCategory.CONTRACT_MISMATCH)


class MissionIdentityTests(unittest.TestCase):
    """Test 7 from the P3.18 mandatory list."""

    def test_mission_identity_preserved(self):
        handoff = _ready_handoff()
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))
        self.assertEqual(report.mission_id, "mission-005")

    def test_mission_identity_mismatch_detected(self):
        handoff = _ready_handoff()
        tampered_review = dc_replace(handoff.review, mission_id="a-different-mission")
        tampered_handoff = dc_replace(handoff, review=tampered_review)
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=tampered_handoff))
        self.assertEqual(report.status, ProductionAuthorityIntakeStatus.REJECTED)
        finding = _findings_by_dimension(report)["identity_chain_consistency"]
        self.assertFalse(finding.passed)


class ReviewIdentityTests(unittest.TestCase):
    """Test 8 from the P3.18 mandatory list."""

    def test_review_identity_preserved(self):
        handoff = _ready_handoff()
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))
        self.assertEqual(report.review_id, handoff.review.review_id)

    def test_expected_review_id_mismatch_rejected(self):
        handoff = _ready_handoff()
        report = ProductionAuthorityIntake().intake(
            ProductionAuthorityIntakeInput(handoff=handoff, expected_review_id="not-the-real-review-id")
        )
        self.assertEqual(report.status, ProductionAuthorityIntakeStatus.REJECTED)
        finding = _findings_by_dimension(report)["expected_review_id_pin"]
        self.assertFalse(finding.passed)


class ArtifactIdentityTests(unittest.TestCase):
    """Test 9 from the P3.18 mandatory list."""

    def test_full_chain_reachable_through_handoff(self):
        handoff = _ready_handoff()
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))
        self.assertIsNotNone(report.handoff.review.production_preparation.script_artifact)
        self.assertEqual(
            report.handoff.review.production_preparation.script_artifact.mission_id, "mission-005"
        )


class PromptAssetMetadataIntegrityTests(unittest.TestCase):
    """Tests 10, 11, 12 from the P3.18 mandatory list -- propagated
    through the embedded handoff/review, never re-derived here."""

    def test_prompt_integrity_visible_through_chain(self):
        handoff = _ready_handoff()
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))
        review_findings = {f.dimension: f for f in report.handoff.review.findings}
        self.assertTrue(review_findings["prompt_integrity"].passed)

    def test_asset_integrity_visible_through_chain(self):
        handoff = _ready_handoff()
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))
        review_findings = {f.dimension: f for f in report.handoff.review.findings}
        self.assertTrue(review_findings["asset_integrity"].passed)

    def test_metadata_integrity_visible_through_chain(self):
        handoff = _ready_handoff()
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))
        review_findings = {f.dimension: f for f in report.handoff.review.findings}
        self.assertTrue(review_findings["metadata_completeness"].passed)


class ContractVersionTests(unittest.TestCase):
    """Test 13 from the P3.18 mandatory list."""

    def test_supported_contract_version_accepted(self):
        handoff = _ready_handoff()
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))
        self.assertTrue(_findings_by_dimension(report)["handoff_contract_version_compatibility"].passed)

    def test_unsupported_handoff_contract_version_rejected(self):
        handoff = _ready_handoff()
        tampered = dc_replace(handoff, contract_version=999)
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=tampered))
        self.assertEqual(report.status, ProductionAuthorityIntakeStatus.REJECTED)
        finding = _findings_by_dimension(report)["handoff_contract_version_compatibility"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, IntakeFailureCategory.CONTRACT_MISMATCH)


class IntegrityMismatchTests(unittest.TestCase):
    """Additional integrity coverage supporting tests 13/40."""

    def test_tampered_handoff_content_hash_detected(self):
        handoff = _ready_handoff()
        tampered = dc_replace(handoff, content_hash="0" * 64)
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=tampered))
        self.assertEqual(report.status, ProductionAuthorityIntakeStatus.REJECTED)
        finding = _findings_by_dimension(report)["handoff_integrity"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, IntakeFailureCategory.INTEGRITY_FAILURE)

    def test_tampered_embedded_review_content_hash_detected(self):
        handoff = _ready_handoff()
        tampered_review = dc_replace(handoff.review, content_hash="0" * 64)
        tampered_handoff = dc_replace(handoff, review=tampered_review)
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=tampered_handoff))
        self.assertEqual(report.status, ProductionAuthorityIntakeStatus.REJECTED)
        finding = _findings_by_dimension(report)["embedded_review_integrity"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, IntakeFailureCategory.INTEGRITY_FAILURE)


class Video005RegressionTests(unittest.TestCase):
    """Test 14 from the P3.18 mandatory list."""

    @classmethod
    def setUpClass(cls):
        cls.handoff = _ready_handoff(request_id="005", expected_prompt_sha256=VIDEO_005_PROMPT_SHA256)
        cls.report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=cls.handoff))

    def test_video_005_accepted(self):
        self.assertEqual(self.report.status, ProductionAuthorityIntakeStatus.ACCEPTED_FOR_P2_CONSIDERATION)

    def test_video_005_identity_preserved(self):
        self.assertEqual(self.report.request_id, VIDEO_005_REQUEST_ID)
        gr = self.report.handoff.review.generation_request
        self.assertEqual(gr.job_type, VIDEO_005_JOB_TYPE)
        self.assertEqual(gr.duration, VIDEO_005_DURATION)
        self.assertEqual(gr.resolution, VIDEO_005_RESOLUTION)
        self.assertEqual(gr.aspect_ratio, VIDEO_005_ASPECT_RATIO)

    def test_video_005_still_not_authorized(self):
        gr = self.report.handoff.review.generation_request
        self.assertFalse(gr.approved)
        self.assertIsNone(gr.real_generation_authorization)


class DeterminismIdempotencyTests(unittest.TestCase):
    """Tests 15, 16 from the P3.18 mandatory list."""

    def test_deterministic_intake(self):
        handoff = _ready_handoff()
        report_a = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))
        report_b = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))
        self.assertEqual(report_a.status, report_b.status)
        self.assertEqual(report_a.findings, report_b.findings)
        self.assertEqual(report_a.content_hash, report_b.content_hash)

    def test_idempotent_repeated_intake(self):
        handoff = _ready_handoff()
        intake = ProductionAuthorityIntake()
        request = ProductionAuthorityIntakeInput(handoff=handoff)
        first = intake.intake(request)
        second = intake.intake(request)
        third = intake.intake(request)
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(second.content_hash, third.content_hash)


class ImmutableHandoffTests(unittest.TestCase):
    """Test 17 from the P3.18 mandatory list."""

    def test_immutable_intake_input(self):
        handoff = _ready_handoff()
        request = ProductionAuthorityIntakeInput(handoff=handoff)
        with self.assertRaises(FrozenInstanceError):
            request.intake_id = "tampered"  # type: ignore

    def test_immutable_intake_output(self):
        handoff = _ready_handoff()
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))
        with self.assertRaises(FrozenInstanceError):
            report.status = ProductionAuthorityIntakeStatus.REJECTED  # type: ignore

    def test_source_handoff_untouched(self):
        handoff = _ready_handoff()
        handoff_id_before = handoff.handoff_id
        content_hash_before = handoff.content_hash
        ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))
        self.assertEqual(handoff.handoff_id, handoff_id_before)
        self.assertEqual(handoff.content_hash, content_hash_before)


class NoAuthorizationTests(unittest.TestCase):
    """Test 18 from the P3.18 mandatory list."""

    def test_no_authorization_field(self):
        handoff = _ready_handoff()
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))
        self.assertFalse(hasattr(report, "approved"))
        self.assertFalse(hasattr(report, "authorized"))
        self.assertFalse(hasattr(report, "authorization"))

    def test_intake_never_accepts_already_authorized_request(self):
        handoff = _ready_handoff()
        from agents.generation_approval_gate import RealGenerationAuthorization

        auth = RealGenerationAuthorization(
            request_id=handoff.review.generation_request.request_id, authorized_by_human=True
        )
        tampered_gr = dc_replace(handoff.review.generation_request, approved=True, real_generation_authorization=auth)
        tampered_review = dc_replace(handoff.review, generation_request=tampered_gr)
        tampered_handoff = dc_replace(handoff, review=tampered_review)
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=tampered_handoff))
        self.assertEqual(report.status, ProductionAuthorityIntakeStatus.REJECTED)
        finding = _findings_by_dimension(report)["not_already_authorized"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, IntakeFailureCategory.INTERNAL_INTAKE_FAILURE)


class NoActivationTests(unittest.TestCase):
    """Test 19 from the P3.18 mandatory list."""

    def test_no_activation_field(self):
        handoff = _ready_handoff()
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))
        self.assertFalse(hasattr(report, "activated"))
        self.assertFalse(hasattr(report, "activation_contract"))
        self.assertFalse(hasattr(report, "provider_activation_contract"))


class NoExecutionTests(unittest.TestCase):
    """Test 20 from the P3.18 mandatory list."""

    def test_no_execution_field(self):
        handoff = _ready_handoff()
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))
        self.assertFalse(hasattr(report, "executed"))
        self.assertFalse(hasattr(report, "executing"))
        self.assertFalse(hasattr(report, "job"))
        self.assertFalse(hasattr(report, "job_id"))

    def test_status_values_never_imply_authority_beyond_intake(self):
        values = {member.value for member in ProductionAuthorityIntakeStatus}
        self.assertEqual(values, {"ACCEPTED_FOR_P2_CONSIDERATION", "REJECTED"})
        for forbidden in ("APPROVED", "AUTHORIZED", "ACTIVATED", "EXECUTING", "EXECUTED"):
            self.assertNotIn(forbidden, values)


class P2ApprovalBoundaryTests(unittest.TestCase):
    """Test 27 from the P3.18 mandatory list."""

    def test_gate_not_constructed_or_invoked(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("GenerationApprovalGate(", code)
        self.assertNotIn(".evaluate(", code)


class P2ActivationBoundaryTests(unittest.TestCase):
    """Test 28 from the P3.18 mandatory list."""

    def test_activation_contracts_not_constructed(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("RequestScopedActivationContract(", code)
        self.assertNotIn("ControlledRealProviderActivationContract(", code)
        self.assertNotIn("prepare_activation(", code)


class P2ExecutionBoundaryTests(unittest.TestCase):
    """Test 29 from the P3.18 mandatory list."""

    def test_no_execute_or_create_job(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("create_job(", code)
        self.assertNotIn(".execute(", code)


class ReplayProtectionTests(unittest.TestCase):
    """Test 30 from the P3.18 mandatory list."""

    def test_no_executed_request_store_reference(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("ExecutedRequestStore", code)
        self.assertNotIn("mark_executed", code)

    def test_intake_not_treated_as_execution_record(self):
        handoff = _ready_handoff()
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))
        self.assertFalse(hasattr(report, "executed"))


class CriticalSectionPreservationTests(unittest.TestCase):
    """Test 31 from the P3.18 mandatory list."""

    def test_no_critical_section_lock_reference(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("CriticalSectionLock", code)
        self.assertNotIn(".acquire(", code)


class StateAuthorityTests(unittest.TestCase):
    """Test 32 from the P3.18 mandatory list."""

    def test_no_state_authority(self):
        handoff = _ready_handoff()
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))
        self.assertFalse(hasattr(report, "mission_state"))
        self.assertFalse(hasattr(ProductionAuthorityIntake(), "state_machine"))
        self.assertFalse(hasattr(ProductionAuthorityIntake(), "transition"))


class DirectorIntegrationTests(unittest.TestCase):
    """Test 33 from the P3.18 mandatory list."""

    def test_director_exposes_production_authority_intake(self):
        director = AIDirector()
        self.assertTrue(hasattr(director, "production_authority_intake"))

    def test_director_delegates_to_injected_intake(self):
        handoff = _ready_handoff()
        director = AIDirector()
        report = director.production_authority_intake(
            ProductionAuthorityIntakeInput(handoff=handoff), intake=ProductionAuthorityIntake()
        )
        self.assertIsInstance(report, ProductionAuthorityIntakeReport)
        self.assertEqual(report.status, ProductionAuthorityIntakeStatus.ACCEPTED_FOR_P2_CONSIDERATION)

    def test_director_default_intake_used_without_injection(self):
        handoff = _ready_handoff()
        director = AIDirector()
        report = director.production_authority_intake(ProductionAuthorityIntakeInput(handoff=handoff))
        self.assertEqual(report.status, ProductionAuthorityIntakeStatus.ACCEPTED_FOR_P2_CONSIDERATION)

    def test_existing_methods_unaffected(self):
        director = AIDirector()
        self.assertTrue(hasattr(director, "run_business_pipeline"))
        self.assertTrue(hasattr(director, "run_video_mission"))
        self.assertTrue(hasattr(director, "prepare_production_from_script"))
        self.assertTrue(hasattr(director, "prepare_video_generation_request"))
        self.assertTrue(hasattr(director, "review_video_generation_request"))
        self.assertTrue(hasattr(director, "handoff_video_generation_request"))

    def test_not_invoked_automatically_by_handoff_method(self):
        director_source = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        tree = ast.parse(director_source)
        handoff_method = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "handoff_video_generation_request":
                handoff_method = node
                break
        self.assertIsNotNone(handoff_method)
        called_names = set()
        for node in ast.walk(handoff_method):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    called_names.add(func.attr)
        self.assertNotIn("production_authority_intake", called_names)

    def test_run_video_mission_unmodified_no_intake_call(self):
        director_source = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        tree = ast.parse(director_source)
        run_method = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "run_video_mission":
                run_method = node
                break
        self.assertIsNotNone(run_method)
        called_names = set()
        for node in ast.walk(run_method):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    called_names.add(func.attr)
        self.assertNotIn("production_authority_intake", called_names)

    def test_director_py_new_method_has_no_forbidden_calls(self):
        director_source = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        tree = ast.parse(director_source)
        method_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "production_authority_intake":
                method_node = node
                break
        self.assertIsNotNone(method_node, "production_authority_intake method not found in director.py")

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
        self.assertFalse(offenders, f"production_authority_intake contains forbidden call(s): {offenders}")


class CompatibilityTests(unittest.TestCase):
    """Tests 34-37 from the P3.18 mandatory list."""

    def test_full_chain_through_intake(self):
        handoff = _ready_handoff()
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))
        self.assertEqual(report.status, ProductionAuthorityIntakeStatus.ACCEPTED_FOR_P2_CONSIDERATION)
        self.assertEqual(report.handoff.status, ProductionReadinessHandoffStatus.READY_FOR_PRODUCTION_AUTHORITY)
        self.assertEqual(report.handoff.review.status, PreProductionReviewStatus.PASS)

    def test_duration_policy_unaffected(self):
        # P3.16's Option D duration policy (script target 30s, technical
        # duration 15s for Video 005) must remain untouched through the
        # new intake layer.
        handoff = _ready_handoff()
        self.assertEqual(handoff.review.production_preparation.duration_seconds, 30)
        self.assertEqual(handoff.review.generation_request.duration, 15)
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))
        self.assertEqual(report.status, ProductionAuthorityIntakeStatus.ACCEPTED_FOR_P2_CONSIDERATION)


class SoleCreateJobCallSiteTests(unittest.TestCase):
    """Tests 38, 39 from the P3.18 mandatory list -- verifies exactly
    one production execution path exists in the repository."""

    def test_generation_job_service_is_sole_create_job_caller(self):
        # agents/job_monitor.py is unrelated pre-P2 legacy code that
        # defines its own unrelated `create_job(self, job_id)` method
        # (a local simulation, never BaseHiggsfieldProvider.create_job)
        # -- excluded by name match alone, not by real coupling to the
        # P2 authority chain audited by this phase.
        legacy_excluded = {"generation_job_service.py", "job_monitor.py"}
        offenders = []
        for path in (PROJECT_ROOT / "agents").glob("*.py"):
            if path.name in legacy_excluded:
                continue
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                    if name == "create_job":
                        offenders.append(str(path))
        self.assertFalse(offenders, f"Unexpected create_job() call site(s) outside GenerationJobService: {offenders}")

    def test_intake_module_has_no_create_job_call(self):
        source = MODULE_SOURCE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("create_job(", source)


class RegressionProtectionTests(unittest.TestCase):
    """Test 40 from the P3.18 mandatory list."""

    def test_rejected_intake_never_silently_upgraded(self):
        handoff = _not_ready_handoff()
        report = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))
        self.assertNotEqual(report.status, ProductionAuthorityIntakeStatus.ACCEPTED_FOR_P2_CONSIDERATION)


class SecurityTests(unittest.TestCase):
    """
    Tests 21-26 from the P3.18 mandatory list: AST-based, docstring-
    false-positive-safe, static verification that `agents/production_
    authority_intake.py` never reaches real execution, any P2 authority
    mechanism beyond the legitimate `ProductionReadinessHandoff`/
    `PreProductionReview` reuse, the Mission State Machine, or an event
    bus.
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
        "prepare_activation", "validate_activation", "consume",
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
        self.assertFalse(offenders, f"production_authority_intake.py imports forbidden module(s): {offenders}")

    def test_no_forbidden_calls(self):
        offenders = self._called_names() & self.FORBIDDEN_CALL_NAMES
        self.assertFalse(offenders, f"production_authority_intake.py contains forbidden call(s): {offenders}")

    def test_no_create_job_call(self):
        self.assertNotIn("create_job", self._called_names())

    def test_no_network_related_substrings(self):
        code = self._source_without_docstrings()
        for banned_substring in ("requests.", "urllib.", "socket.", "http.client", "subprocess.", "os.system", "aiohttp.", "httpx."):
            self.assertNotIn(banned_substring, code)

    def test_no_credential_oauth_tokens(self):
        lowered = self._source_without_docstrings().lower()
        for token in ("api_key", "apikey", "oauth", "access_token", "bearer", "password"):
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

    def test_no_p2_class_reimplemented(self):
        class_defs = {node.name for node in ast.walk(self.tree) if isinstance(node, ast.ClassDef)}
        self.assertNotIn("GenerationApprovalGate", class_defs)
        self.assertNotIn("RequestScopedActivationService", class_defs)
        self.assertNotIn("ControlledRealProviderActivationService", class_defs)
        self.assertNotIn("GenerationJobService", class_defs)
        self.assertNotIn("PreProductionReviewer", class_defs)
        self.assertNotIn("ProductionReadinessHandoffBuilder", class_defs)

    def test_p2_boundary_never_crossed(self):
        p2_modules = {
            "agents.generation_approval_gate",
            "agents.generation_job_service",
            "agents.activation_contract",
            "agents.controlled_real_provider_activation",
            "agents.activation_readiness",
            "agents.critical_section_lock",
            "agents.executed_request_store",
            "integrations.higgsfield.provider",
            "integrations.higgsfield.client",
        }
        offenders = self._imported_modules() & p2_modules
        self.assertFalse(offenders, f"production_authority_intake.py crosses the P2 boundary: {offenders}")


if __name__ == "__main__":
    unittest.main()
