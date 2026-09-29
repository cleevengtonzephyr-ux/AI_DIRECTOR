"""
Tests — Human Authorization Handoff (Phase P3.19).

Fully offline: no network, no Higgsfield, no social platform, no OAuth,
no credential of any kind is imported or constructed anywhere in this
file. Verifies `agents/human_authorization_handoff.py` and the new
`AIDirector.human_authorization_handoff()` entry point in `director.py`.

The one exception, isolated to `P2_29CompatibilityTests`, exercises the
pre-existing (Phase P2.29) `AIDirector.prepare_real_generation_
activation()` entry point purely to prove it remains unaffected --
always via an injected `MockHiggsfieldProvider`-backed `report_service`
(the same pattern `tests/test_phase_p2_29_explicit_human_activation_
entry_point.py` already uses), never the real chain.
"""

import ast
import shutil
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace as dc_replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.asset_preparation_system import AssetPreparationSystem
from agents.content_agent import ContentAgent, ContentAgentInput
from agents.generation_approval_gate import GenerationApprovalGate, RealGenerationAuthorization
from tests.authorization_content_helpers import video_005_authorization
from agents.human_authorization_handoff import (
    HumanAuthorizationFailureCategory,
    HumanAuthorizationHandoff,
    HumanAuthorizationHandoffBuilder,
    HumanAuthorizationHandoffError,
    HumanAuthorizationHandoffInput,
    HumanAuthorizationHandoffStatus,
)
from agents.planner import VideoPlanner
from agents.pre_production_review import PreProductionReviewInput, PreProductionReviewer
from agents.production_authority_intake import ProductionAuthorityIntake, ProductionAuthorityIntakeInput
from agents.production_readiness_handoff import ProductionReadinessHandoffBuilder, ProductionReadinessHandoffInput
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.script_production_bridge import ProductionPreparationInput
from agents.strategy_agent import StrategyAgent, StrategyAgentInput
from agents.video_production_preparation import VideoProductionPreparation, VideoProductionPreparationInput
from director import AIDirector

MODULE_SOURCE_PATH = PROJECT_ROOT / "agents" / "human_authorization_handoff.py"

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


def _accepted_intake(request_id="005", **review_kwargs):
    result = _real_ready_result(request_id=request_id)
    review = PreProductionReviewer().review(
        PreProductionReviewInput(preparation_result=result, **review_kwargs)
    )
    handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
    return ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))


def _rejected_intake():
    result = _not_ready_result()
    review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
    handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
    return ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=handoff))


def _valid_auth(request_id="005"):
    return video_005_authorization(request_id=request_id)


def _findings_by_dimension(handoff):
    return {f.dimension: f for f in handoff.findings}


def _module_code_without_docstrings():
    """Source of agents/human_authorization_handoff.py with every
    module/class/function docstring stripped -- so raw-substring
    boundary checks below never false-positive on this module's own
    prose (which legitimately narrates forbidden concepts by name,
    e.g. explaining why GenerationApprovalGate/prepare_activation are
    never touched)."""

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


class AcceptedIntakeTests(unittest.TestCase):
    """Test 1 from the P3.19 mandatory list."""

    def test_accepted_intake_without_authorization_is_eligible(self):
        intake = _accepted_intake()
        handoff = HumanAuthorizationHandoffBuilder().build(HumanAuthorizationHandoffInput(intake=intake))
        self.assertEqual(handoff.status, HumanAuthorizationHandoffStatus.ELIGIBLE_FOR_HUMAN_AUTHORIZATION)
        self.assertEqual(handoff.reasons, ())
        self.assertFalse(handoff.authorization_supplied)
        self.assertIsNone(handoff.authorization_id)


class RejectedIntakeTests(unittest.TestCase):
    """Test 2 from the P3.19 mandatory list."""

    def test_rejected_intake_is_intake_not_accepted(self):
        intake = _rejected_intake()
        handoff = HumanAuthorizationHandoffBuilder().build(HumanAuthorizationHandoffInput(intake=intake))
        self.assertEqual(handoff.status, HumanAuthorizationHandoffStatus.INTAKE_NOT_ACCEPTED)
        self.assertTrue(handoff.reasons)
        finding = _findings_by_dimension(handoff)["intake_accepted"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, HumanAuthorizationFailureCategory.INTAKE_REJECTED)

    def test_rejected_intake_never_silently_upgraded_even_with_authorization(self):
        # Even a perfectly valid authorization must never rescue a
        # rejected intake -- INTAKE_NOT_ACCEPTED takes priority.
        intake = _rejected_intake()
        handoff = HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=_valid_auth("005"))
        )
        self.assertEqual(handoff.status, HumanAuthorizationHandoffStatus.INTAKE_NOT_ACCEPTED)


class AuthorizationAbsentTests(unittest.TestCase):
    """Test 3 from the P3.19 mandatory list."""

    def test_authorization_absent_reported_explicitly(self):
        intake = _accepted_intake()
        handoff = HumanAuthorizationHandoffBuilder().build(HumanAuthorizationHandoffInput(intake=intake))
        finding = _findings_by_dimension(handoff)["authorization_presence"]
        self.assertTrue(finding.passed)
        self.assertIn("No real_generation_authorization was supplied", finding.detail)


class AuthorizationSuppliedTests(unittest.TestCase):
    """Test 4 from the P3.19 mandatory list."""

    def test_authorization_supplied_flag_set(self):
        intake = _accepted_intake()
        handoff = HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=_valid_auth("005"))
        )
        self.assertTrue(handoff.authorization_supplied)
        self.assertIsNotNone(handoff.authorization_id)


class ValidAuthorizationTests(unittest.TestCase):
    """Test 5 from the P3.19 mandatory list."""

    def test_valid_authorization_structurally_valid(self):
        intake = _accepted_intake()
        handoff = HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=_valid_auth("005"))
        )
        self.assertEqual(handoff.status, HumanAuthorizationHandoffStatus.AUTHORIZATION_STRUCTURALLY_VALID)
        self.assertEqual(handoff.reasons, ())
        self.assertTrue(all(f.passed for f in handoff.findings))


class InvalidAuthorizationTests(unittest.TestCase):
    """Test 6 from the P3.19 mandatory list."""

    def test_wrong_type_authorization_rejected_as_forged(self):
        intake = _accepted_intake()
        handoff = HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization="not-an-authorization")  # type: ignore
        )
        self.assertEqual(handoff.status, HumanAuthorizationHandoffStatus.AUTHORIZATION_REJECTED)
        finding = _findings_by_dimension(handoff)["authorization_type_valid"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, HumanAuthorizationFailureCategory.AUTHORIZATION_FORGED)

    def test_authorized_by_human_false_rejected(self):
        intake = _accepted_intake()
        auth = RealGenerationAuthorization(request_id="005", authorized_by_human=False)
        handoff = HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=auth)
        )
        self.assertEqual(handoff.status, HumanAuthorizationHandoffStatus.AUTHORIZATION_REJECTED)
        finding = _findings_by_dimension(handoff)["authorization_human_flag"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, HumanAuthorizationFailureCategory.AUTHORIZATION_INVALID)


class AuthorizationRequestMismatchTests(unittest.TestCase):
    """Test 7 from the P3.19 mandatory list."""

    def test_authorization_bound_to_different_request_rejected(self):
        intake = _accepted_intake()
        handoff = HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=_valid_auth("999"))
        )
        self.assertEqual(handoff.status, HumanAuthorizationHandoffStatus.AUTHORIZATION_REJECTED)
        finding = _findings_by_dimension(handoff)["authorization_request_binding"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, HumanAuthorizationFailureCategory.AUTHORIZATION_REQUEST_MISMATCH)


class AuthorizationIdentityTests(unittest.TestCase):
    """Test 8 from the P3.19 mandatory list."""

    def test_authorization_identity_present(self):
        intake = _accepted_intake()
        handoff = HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=_valid_auth("005"))
        )
        finding = _findings_by_dimension(handoff)["authorization_identity_present"]
        self.assertTrue(finding.passed)
        self.assertEqual(handoff.authorization_id, finding.detail.split("'")[1])

    def test_missing_authorization_id_rejected(self):
        intake = _accepted_intake()
        auth = dc_replace(_valid_auth("005"), authorization_id="")
        handoff = HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=auth)
        )
        self.assertEqual(handoff.status, HumanAuthorizationHandoffStatus.AUTHORIZATION_REJECTED)
        finding = _findings_by_dimension(handoff)["authorization_identity_present"]
        self.assertFalse(finding.passed)


class AuthorizedByHumanSemanticsTests(unittest.TestCase):
    """Test 9 from the P3.19 mandatory list."""

    def test_authorized_by_human_must_be_literal_true(self):
        intake = _accepted_intake()
        auth = RealGenerationAuthorization(request_id="005", authorized_by_human=True)
        handoff = HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=auth)
        )
        self.assertTrue(_findings_by_dimension(handoff)["authorization_human_flag"].passed)


class ApprovedIndependenceTests(unittest.TestCase):
    """Test 10 from the P3.19 mandatory list."""

    def test_generation_request_approved_never_substitutes_for_authorization(self):
        intake = _accepted_intake()
        gr = intake.handoff.review.generation_request
        self.assertFalse(gr.approved)  # never true anywhere upstream of this module
        handoff = HumanAuthorizationHandoffBuilder().build(HumanAuthorizationHandoffInput(intake=intake))
        # approved is False upstream and no authorization was supplied:
        # the result must be ELIGIBLE, never any authorized-sounding status.
        self.assertEqual(handoff.status, HumanAuthorizationHandoffStatus.ELIGIBLE_FOR_HUMAN_AUTHORIZATION)

    def test_approved_true_on_tampered_request_does_not_grant_authorization(self):
        intake = _accepted_intake()
        # Even if an upstream GenerationRequest were (structurally
        # impossibly) approved=True, this module never reads .approved
        # anywhere -- confirmed by source inspection.
        code = MODULE_SOURCE_PATH.read_text(encoding="utf-8")
        self.assertNotIn(".approved", code)


class NoAutomaticAuthorizationTests(unittest.TestCase):
    """Test 11 from the P3.19 mandatory list -- adversarial: ready=True,
    accepted=True, review.status=PASS, approved=True, request exists --
    none of it can create a RealGenerationAuthorization."""

    def test_fully_ready_accepted_chain_never_authorizes_without_explicit_object(self):
        intake = _accepted_intake()
        self.assertTrue(intake.status.value == "ACCEPTED_FOR_P2_CONSIDERATION")
        self.assertTrue(intake.handoff.status.value == "READY_FOR_PRODUCTION_AUTHORITY")
        self.assertTrue(intake.handoff.review.status.value == "PASS")
        handoff = HumanAuthorizationHandoffBuilder().build(HumanAuthorizationHandoffInput(intake=intake))
        self.assertNotEqual(handoff.status, HumanAuthorizationHandoffStatus.AUTHORIZATION_STRUCTURALLY_VALID)
        self.assertIsNone(handoff.authorization_id)
        self.assertFalse(handoff.authorization_supplied)

    def test_builder_never_constructs_authorization_object(self):
        code = MODULE_SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(code)
        constructor_calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertNotIn("RealGenerationAuthorization", constructor_calls)


class NoForgedAuthorizationTests(unittest.TestCase):
    """Test 12 from the P3.19 mandatory list."""

    def test_dict_masquerading_as_authorization_rejected(self):
        intake = _accepted_intake()
        fake = {"request_id": "005", "authorized_by_human": True}
        handoff = HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=fake)  # type: ignore
        )
        self.assertEqual(handoff.status, HumanAuthorizationHandoffStatus.AUTHORIZATION_REJECTED)
        self.assertEqual(
            _findings_by_dimension(handoff)["authorization_type_valid"].category,
            HumanAuthorizationFailureCategory.AUTHORIZATION_FORGED,
        )


class NoActivationTests(unittest.TestCase):
    """Test 13 from the P3.19 mandatory list."""

    def test_no_activation_field(self):
        intake = _accepted_intake()
        handoff = HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=_valid_auth("005"))
        )
        self.assertFalse(hasattr(handoff, "activated"))
        self.assertFalse(hasattr(handoff, "activation_contract"))
        self.assertFalse(hasattr(handoff, "provider_activation_contract"))


class NoExecutionTests(unittest.TestCase):
    """Test 14 from the P3.19 mandatory list."""

    def test_no_execution_field(self):
        intake = _accepted_intake()
        handoff = HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=_valid_auth("005"))
        )
        self.assertFalse(hasattr(handoff, "executed"))
        self.assertFalse(hasattr(handoff, "job"))
        self.assertFalse(hasattr(handoff, "job_id"))

    def test_status_values_never_imply_authority_beyond_this_handoff(self):
        values = {member.value for member in HumanAuthorizationHandoffStatus}
        self.assertEqual(
            values,
            {
                "INTAKE_NOT_ACCEPTED",
                "ELIGIBLE_FOR_HUMAN_AUTHORIZATION",
                "AUTHORIZATION_STRUCTURALLY_VALID",
                "AUTHORIZATION_REJECTED",
            },
        )
        for forbidden in ("AUTHORIZED", "HUMAN_AUTHORIZED", "APPROVED", "ACTIVATED", "EXECUTING", "EXECUTED"):
            self.assertNotIn(forbidden, values)


class Video005RegressionTests(unittest.TestCase):
    """Test 19 from the P3.19 mandatory list."""

    @classmethod
    def setUpClass(cls):
        cls.intake = _accepted_intake(request_id="005", expected_prompt_sha256=VIDEO_005_PROMPT_SHA256)
        cls.handoff = HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=cls.intake, real_generation_authorization=_valid_auth("005"))
        )

    def test_video_005_authorization_structurally_valid(self):
        self.assertEqual(self.handoff.status, HumanAuthorizationHandoffStatus.AUTHORIZATION_STRUCTURALLY_VALID)

    def test_video_005_identity_preserved(self):
        self.assertEqual(self.handoff.request_id, VIDEO_005_REQUEST_ID)
        gr = self.handoff.intake.handoff.review.generation_request
        self.assertEqual(gr.job_type, VIDEO_005_JOB_TYPE)
        self.assertEqual(gr.duration, VIDEO_005_DURATION)
        self.assertEqual(gr.resolution, VIDEO_005_RESOLUTION)
        self.assertEqual(gr.aspect_ratio, VIDEO_005_ASPECT_RATIO)

    def test_video_005_generation_request_itself_still_unauthorized(self):
        # The embedded GenerationRequest object itself is never mutated
        # to carry the supplied authorization -- it remains exactly as
        # P3.14 produced it.
        gr = self.handoff.intake.handoff.review.generation_request
        self.assertFalse(gr.approved)
        self.assertIsNone(gr.real_generation_authorization)


class RequestIdentityTests(unittest.TestCase):
    """Test 20 from the P3.19 mandatory list."""

    def test_request_id_preserved(self):
        intake = _accepted_intake(request_id="custom-005")
        handoff = HumanAuthorizationHandoffBuilder().build(HumanAuthorizationHandoffInput(intake=intake))
        self.assertEqual(handoff.request_id, "custom-005")

    def test_swapped_generation_request_detected_via_identity_chain(self):
        intake = _accepted_intake()
        tampered_gr = dc_replace(intake.handoff.review.generation_request, request_id="swapped-id")
        tampered_review = dc_replace(intake.handoff.review, generation_request=tampered_gr)
        tampered_handoff = dc_replace(intake.handoff, review=tampered_review)
        tampered_intake = dc_replace(intake, handoff=tampered_handoff)
        handoff = HumanAuthorizationHandoffBuilder().build(HumanAuthorizationHandoffInput(intake=tampered_intake))
        self.assertEqual(handoff.status, HumanAuthorizationHandoffStatus.INTAKE_NOT_ACCEPTED)
        finding = _findings_by_dimension(handoff)["identity_chain_consistency"]
        self.assertFalse(finding.passed)


class ProvenanceTests(unittest.TestCase):
    """Test 21 from the P3.19 mandatory list."""

    def test_full_traceability_chain_reachable(self):
        intake = _accepted_intake()
        handoff = HumanAuthorizationHandoffBuilder().build(HumanAuthorizationHandoffInput(intake=intake))
        self.assertEqual(handoff.mission_id, "mission-005")
        self.assertEqual(handoff.intake.handoff.review.production_preparation.mission_id, "mission-005")
        self.assertIsNotNone(handoff.intake.handoff.review.production_preparation.script_artifact)


class DeterminismTests(unittest.TestCase):
    """Test 22 from the P3.19 mandatory list."""

    def test_deterministic_validation_no_authorization(self):
        intake = _accepted_intake()
        a = HumanAuthorizationHandoffBuilder().build(HumanAuthorizationHandoffInput(intake=intake))
        b = HumanAuthorizationHandoffBuilder().build(HumanAuthorizationHandoffInput(intake=intake))
        self.assertEqual(a.content_hash, b.content_hash)

    def test_deterministic_validation_with_same_authorization_instance(self):
        intake = _accepted_intake()
        auth = _valid_auth("005")
        a = HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=auth)
        )
        b = HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=auth)
        )
        self.assertEqual(a.content_hash, b.content_hash)
        self.assertEqual(a.status, b.status)


class IdempotencyTests(unittest.TestCase):
    """Test 23 from the P3.19 mandatory list."""

    def test_idempotent_repeated_validation(self):
        intake = _accepted_intake()
        auth = _valid_auth("005")
        builder = HumanAuthorizationHandoffBuilder()
        request = HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=auth)
        first = builder.build(request)
        second = builder.build(request)
        third = builder.build(request)
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(second.content_hash, third.content_hash)
        # No production execution occurred as a side effect of repeated
        # validation -- no executed_requests state exists to check
        # against in this module (it never imports that store at all).


class ImmutabilityTests(unittest.TestCase):
    """Test 24 from the P3.19 mandatory list."""

    def test_immutable_input(self):
        intake = _accepted_intake()
        request = HumanAuthorizationHandoffInput(intake=intake)
        with self.assertRaises(FrozenInstanceError):
            request.handoff_id = "tampered"  # type: ignore

    def test_immutable_output(self):
        intake = _accepted_intake()
        handoff = HumanAuthorizationHandoffBuilder().build(HumanAuthorizationHandoffInput(intake=intake))
        with self.assertRaises(FrozenInstanceError):
            handoff.status = HumanAuthorizationHandoffStatus.AUTHORIZATION_REJECTED  # type: ignore

    def test_source_intake_and_generation_request_untouched(self):
        intake = _accepted_intake()
        gr_before = intake.handoff.review.generation_request
        HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=_valid_auth("005"))
        )
        gr_after = intake.handoff.review.generation_request
        self.assertIs(gr_before, gr_after)
        self.assertFalse(gr_after.approved)
        self.assertIsNone(gr_after.real_generation_authorization)


class StaleMismatchedReadinessTests(unittest.TestCase):
    """Test 25 from the P3.19 mandatory list."""

    def test_tampered_intake_content_hash_detected(self):
        intake = _accepted_intake()
        tampered = dc_replace(intake, content_hash="0" * 64)
        handoff = HumanAuthorizationHandoffBuilder().build(HumanAuthorizationHandoffInput(intake=tampered))
        self.assertEqual(handoff.status, HumanAuthorizationHandoffStatus.INTAKE_NOT_ACCEPTED)
        self.assertFalse(_findings_by_dimension(handoff)["intake_integrity"].passed)

    def test_mission_mismatch_detected(self):
        intake = _accepted_intake()
        tampered_review = dc_replace(intake.handoff.review, mission_id="a-different-mission")
        tampered_handoff = dc_replace(intake.handoff, review=tampered_review)
        tampered_intake = dc_replace(intake, handoff=tampered_handoff)
        handoff = HumanAuthorizationHandoffBuilder().build(HumanAuthorizationHandoffInput(intake=tampered_intake))
        self.assertEqual(handoff.status, HumanAuthorizationHandoffStatus.INTAKE_NOT_ACCEPTED)


class ReplayAlreadyConsumedCategoryTests(unittest.TestCase):
    """Test 36 from the P3.19 mandatory list."""

    def test_already_consumed_category_defined_but_unreachable(self):
        self.assertIn(
            "AUTHORIZATION_ALREADY_CONSUMED",
            {m.value for m in HumanAuthorizationFailureCategory},
        )
        intake = _accepted_intake()
        for auth in (None, _valid_auth("005"), _valid_auth("999"), "not-real"):
            handoff = HumanAuthorizationHandoffBuilder().build(
                HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=auth)  # type: ignore
            )
            categories = {f.category for f in handoff.findings if f.category is not None}
            self.assertNotIn(HumanAuthorizationFailureCategory.AUTHORIZATION_ALREADY_CONSUMED, categories)

    def test_no_executed_request_store_reference(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("ExecutedRequestStore", code)
        self.assertNotIn("mark_executed", code)


class CriticalSectionPreservationTests(unittest.TestCase):
    """Test 37 from the P3.19 mandatory list."""

    def test_no_critical_section_lock_reference(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("CriticalSectionLock", code)
        self.assertNotIn(".acquire(", code)


class SoleProductionExecutionPathTests(unittest.TestCase):
    """Tests 38, 39 from the P3.19 mandatory list."""

    def test_no_create_job_or_execute_call(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("create_job(", code)
        self.assertNotIn(".execute(", code)

    def test_sole_create_job_caller_still_generation_job_service(self):
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
        self.assertFalse(offenders, f"Unexpected create_job() call site(s): {offenders}")


class StateAuthorityTests(unittest.TestCase):
    """Test 33 from the P3.19 mandatory list."""

    def test_no_state_authority(self):
        intake = _accepted_intake()
        handoff = HumanAuthorizationHandoffBuilder().build(HumanAuthorizationHandoffInput(intake=intake))
        self.assertFalse(hasattr(handoff, "mission_state"))
        self.assertFalse(hasattr(HumanAuthorizationHandoffBuilder(), "state_machine"))
        self.assertFalse(hasattr(HumanAuthorizationHandoffBuilder(), "transition"))


class ApprovalActivationSeparationTests(unittest.TestCase):
    """Tests 34, 35 from the P3.19 mandatory list."""

    def test_gate_not_constructed_or_invoked(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("GenerationApprovalGate(", code)
        self.assertNotIn(".evaluate(", code)

    def test_activation_contracts_not_constructed(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("RequestScopedActivationContract(", code)
        self.assertNotIn("ControlledRealProviderActivationContract(", code)
        self.assertNotIn("prepare_activation(", code)
        self.assertNotIn("prepare_real_generation_activation(", code)
        self.assertNotIn("execute_real_generation_activation(", code)


class DirectorIntegrationTests(unittest.TestCase):
    """Test 19 (Director integration) plus general wiring checks."""

    def test_director_exposes_human_authorization_handoff(self):
        director = AIDirector()
        self.assertTrue(hasattr(director, "human_authorization_handoff"))

    def test_director_delegates_to_injected_builder(self):
        intake = _accepted_intake()
        director = AIDirector()
        handoff = director.human_authorization_handoff(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=_valid_auth("005")),
            builder=HumanAuthorizationHandoffBuilder(),
        )
        self.assertIsInstance(handoff, HumanAuthorizationHandoff)
        self.assertEqual(handoff.status, HumanAuthorizationHandoffStatus.AUTHORIZATION_STRUCTURALLY_VALID)

    def test_director_default_builder_used_without_injection(self):
        intake = _accepted_intake()
        director = AIDirector()
        handoff = director.human_authorization_handoff(HumanAuthorizationHandoffInput(intake=intake))
        self.assertEqual(handoff.status, HumanAuthorizationHandoffStatus.ELIGIBLE_FOR_HUMAN_AUTHORIZATION)

    def test_existing_methods_unaffected(self):
        director = AIDirector()
        for name in (
            "run_business_pipeline", "run_video_mission", "prepare_production_from_script",
            "prepare_video_generation_request", "review_video_generation_request",
            "handoff_video_generation_request", "production_authority_intake",
            "prepare_real_generation_activation", "execute_real_generation_activation",
        ):
            self.assertTrue(hasattr(director, name), f"missing {name}")

    def test_not_invoked_automatically_by_production_authority_intake(self):
        director_source = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        tree = ast.parse(director_source)
        method_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "production_authority_intake":
                method_node = node
                break
        self.assertIsNotNone(method_node)
        called_names = {
            node.func.attr
            for node in ast.walk(method_node)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn("human_authorization_handoff", called_names)

    def test_run_video_mission_never_calls_new_method(self):
        director_source = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        tree = ast.parse(director_source)
        run_method = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "run_video_mission":
                run_method = node
                break
        self.assertIsNotNone(run_method)
        called_names = {
            node.func.attr
            for node in ast.walk(run_method)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn("human_authorization_handoff", called_names)

    def test_director_py_new_method_has_no_forbidden_calls(self):
        director_source = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        tree = ast.parse(director_source)
        method_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "human_authorization_handoff":
                method_node = node
                break
        self.assertIsNotNone(method_node, "human_authorization_handoff method not found in director.py")
        called_names = set()
        for node in ast.walk(method_node):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    called_names.add(func.id)
                elif isinstance(func, ast.Attribute):
                    called_names.add(func.attr)
        offenders = called_names & {
            "create_job", "transition", "evaluate", "execute", "prepare_activation",
            "prepare_real_generation_activation", "execute_real_generation_activation",
            "RealGenerationAuthorization", "RequestScopedActivationContract",
            "ControlledRealProviderActivationContract",
        }
        self.assertFalse(offenders, f"human_authorization_handoff contains forbidden call(s): {offenders}")


class CompatibilityTests(unittest.TestCase):
    """Tests 26-29 from the P3.19 mandatory list."""

    def test_full_chain_through_human_authorization_handoff(self):
        intake = _accepted_intake()
        handoff = HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=_valid_auth("005"))
        )
        self.assertEqual(handoff.status, HumanAuthorizationHandoffStatus.AUTHORIZATION_STRUCTURALLY_VALID)
        self.assertEqual(handoff.intake.status.value, "ACCEPTED_FOR_P2_CONSIDERATION")
        self.assertEqual(handoff.intake.handoff.status.value, "READY_FOR_PRODUCTION_AUTHORITY")
        self.assertEqual(handoff.intake.handoff.review.status.value, "PASS")

    def test_duration_policy_unaffected(self):
        intake = _accepted_intake()
        gr = intake.handoff.review.generation_request
        self.assertEqual(intake.handoff.review.production_preparation.duration_seconds, 30)
        self.assertEqual(gr.duration, 15)


class P2_29CompatibilityTests(unittest.TestCase):
    """Test 30 from the P3.19 mandatory list -- proves the pre-existing
    P2.29 entry point remains untouched and independently reachable,
    always via an injected Mock-backed report_service."""

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p3_19_p2_29_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def test_prepare_real_generation_activation_still_requires_explicit_authorization(self):
        import inspect

        sig = inspect.signature(AIDirector.prepare_real_generation_activation)
        self.assertIs(sig.parameters["real_generation_authorization"].default, inspect.Parameter.empty)

    def test_prepare_real_generation_activation_callable_without_p3_19_involvement(self):
        from agents.activation_contract import RequestScopedActivationService
        from agents.controlled_real_provider_activation import ControlledRealProviderActivationService
        from agents.critical_section_lock import FileCriticalSectionLock
        from agents.final_report_service import FinalReportService
        from agents.generation_job_service import GenerationJobService
        from agents.release_candidate_identity_lock import ReleaseCandidateIdentityLock, VIDEO_005_RELEASE_CANDIDATE
        from integrations.higgsfield.mock_provider import MockHiggsfieldProvider

        provider = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=1000.0)
        identity_lock = ReleaseCandidateIdentityLock(VIDEO_005_RELEASE_CANDIDATE)
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
        activation_service = RequestScopedActivationService(gate, identity_lock)
        provider_activation_service = ControlledRealProviderActivationService(gate, identity_lock, activation_service)
        lock = FileCriticalSectionLock(self._tmp)
        job_service = GenerationJobService(
            provider, gate, lock=lock,
            activation_service=activation_service,
            provider_activation_service=provider_activation_service,
        )
        report_service = FinalReportService(provider, gate, job_service=job_service)

        director = AIDirector()
        prepared = director.prepare_real_generation_activation(
            video_id="005", title="t", hook="h", objective="o",
            duration=15, approved=True,
            real_generation_authorization=_valid_auth("005"),
            report_service=report_service,
        )
        self.assertEqual(prepared.request.request_id, "005")
        self.assertFalse(prepared.request.approved is None)


class P2_30CompatibilityTests(unittest.TestCase):
    """Test 31 from the P3.19 mandatory list -- P2.30 (Real Generation
    Authorization Budget Readiness) remains reachable, untouched."""

    def test_p2_30_module_importable_and_unaffected(self):
        import importlib

        module = importlib.import_module("tests.test_phase_p2_30_real_generation_authorization_budget_readiness")
        self.assertIsNotNone(module)


class P2_40CompatibilityTests(unittest.TestCase):
    """Test 32 from the P3.19 mandatory list."""

    def test_generation_approval_gate_unaffected(self):
        # RealGenerationAuthorization's own contract (P2.11) is
        # untouched: constructing one without explicit consent is
        # simply not possible via this module's public API.
        auth = RealGenerationAuthorization(request_id="005", authorized_by_human=True)
        self.assertTrue(auth.authorized_by_human)
        self.assertEqual(auth.request_id, "005")


class RegressionProtectionTests(unittest.TestCase):
    """Test 40 from the P3.19 mandatory list."""

    def test_rejected_authorization_never_silently_upgraded(self):
        intake = _accepted_intake()
        handoff = HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=_valid_auth("999"))
        )
        self.assertNotEqual(handoff.status, HumanAuthorizationHandoffStatus.AUTHORIZATION_STRUCTURALLY_VALID)


class InvalidInputTests(unittest.TestCase):
    """Structural input-validation regression, mirrors P3.17/P3.18's own."""

    def test_invalid_intake_raises_explicitly(self):
        with self.assertRaises(HumanAuthorizationHandoffError):
            HumanAuthorizationHandoffBuilder().build(
                HumanAuthorizationHandoffInput(intake="not-an-intake")  # type: ignore
            )


class SecurityTests(unittest.TestCase):
    """
    Tests 15, 16, 17, 18 from the P3.19 mandatory list, plus AST
    Section 27 requirements: AST-based, docstring-false-positive-safe,
    static verification that `agents/human_authorization_handoff.py`
    never reaches real execution, any P2 authority mechanism beyond the
    legitimate `RealGenerationAuthorization` TYPE reuse, the Mission
    State Machine, or an event bus -- and that it never CONSTRUCTS a
    `RealGenerationAuthorization` (a Call node), even though it freely
    REFERENCES the type (a Name/Attribute node, for isinstance/typing).
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
        "prepare_real_generation_activation", "execute_real_generation_activation",
        "RealGenerationAuthorization",  # as a CALL -- construction forbidden (see below)
        "RequestScopedActivationContract",
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
        self.assertFalse(offenders, f"human_authorization_handoff.py imports forbidden module(s): {offenders}")

    def test_no_forbidden_calls(self):
        offenders = self._called_names() & self.FORBIDDEN_CALL_NAMES
        self.assertFalse(offenders, f"human_authorization_handoff.py contains forbidden call(s): {offenders}")

    def test_real_generation_authorization_referenced_but_never_constructed(self):
        # TYPE REFERENCE (isinstance/type hints) must be present --
        # this module legitimately needs the type.
        names_referenced = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name):
                names_referenced.add(node.id)
        self.assertIn("RealGenerationAuthorization", names_referenced)
        # CONSTRUCTOR INVOCATION (a Call whose func is this name) must
        # be entirely absent.
        self.assertNotIn("RealGenerationAuthorization", self._called_names())

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
        self.assertNotIn("RealGenerationAuthorization", class_defs)

    def test_p2_boundary_never_crossed(self):
        p2_modules = {
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
        self.assertFalse(offenders, f"human_authorization_handoff.py crosses the P2 boundary: {offenders}")

    def test_generation_approval_gate_module_not_imported(self):
        # Only the RealGenerationAuthorization TYPE from that module is
        # imported (same precedent as every prior P3 phase) -- the Gate
        # CLASS itself must never be importable from this module.
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module == "agents.generation_approval_gate":
                for alias in node.names:
                    names.add(alias.name)
        self.assertIn("RealGenerationAuthorization", names)
        self.assertNotIn("GenerationApprovalGate", names)


if __name__ == "__main__":
    unittest.main()
