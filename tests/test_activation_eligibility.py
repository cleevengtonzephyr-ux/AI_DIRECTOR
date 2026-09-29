"""
Tests — Activation Eligibility (Phase P3.20).

Fully offline: no network, no Higgsfield, no social platform, no OAuth,
no credential of any kind is imported or constructed anywhere in this
file. Verifies `agents/activation_eligibility.py` and the new
`AIDirector.activation_eligibility()` entry point in `director.py`.

The one exception, isolated to `P2_29CompatibilityTests`, exercises the
pre-existing (Phase P2.29) `AIDirector.prepare_real_generation_
activation()` entry point purely to obtain REAL, externally-prepared
`RequestScopedActivationContract`/`ControlledRealProviderActivation
Contract` snapshots to feed into this phase's eligibility checker --
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import RequestScopedActivationContract, RequestScopedActivationService
from agents.activation_eligibility import (
    ActivationEligibilityChecker,
    ActivationEligibilityError,
    ActivationEligibilityInput,
    ActivationEligibilityResult,
    ActivationEligibilityStatus,
    EligibilityFailureCategory,
)
from agents.asset_preparation_system import AssetPreparationSystem
from agents.content_agent import ContentAgent, ContentAgentInput
from agents.controlled_real_provider_activation import (
    ControlledRealProviderActivationContract,
    ControlledRealProviderActivationService,
)
from agents.critical_section_lock import FileCriticalSectionLock
from agents.final_report_service import FinalReportService
from agents.generation_approval_gate import GenerationApprovalGate, RealGenerationAuthorization
from tests.authorization_content_helpers import video_005_authorization
from agents.generation_job_service import GenerationJobService
from agents.human_authorization_handoff import HumanAuthorizationHandoffBuilder, HumanAuthorizationHandoffInput
from agents.planner import VideoPlanner
from agents.pre_production_review import PreProductionReviewInput, PreProductionReviewer
from agents.production_authority_intake import ProductionAuthorityIntake, ProductionAuthorityIntakeInput
from agents.production_readiness_handoff import ProductionReadinessHandoffBuilder, ProductionReadinessHandoffInput
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.release_candidate_identity_lock import ReleaseCandidateIdentityLock, VIDEO_005_RELEASE_CANDIDATE
from agents.script_production_bridge import ProductionPreparationInput
from agents.strategy_agent import StrategyAgent, StrategyAgentInput
from agents.video_production_preparation import VideoProductionPreparation, VideoProductionPreparationInput
from director import AIDirector
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider

MODULE_SOURCE_PATH = PROJECT_ROOT / "agents" / "activation_eligibility.py"

VIDEO_005_REQUEST_ID = "005"
VIDEO_005_JOB_TYPE = "seedance_2_0"
VIDEO_005_DURATION = 15
VIDEO_005_RESOLUTION = "720p"
VIDEO_005_ASPECT_RATIO = "9:16"
VIDEO_005_PROMPT_SHA256 = "1c498617adb4603bcf2fc114a9cb9e8fe2219f09285adbff4d1e6c7a10a669e1"


def _module_code_without_docstrings():
    """Source of agents/activation_eligibility.py with every module/
    class/function docstring stripped -- so raw-substring boundary
    checks below never false-positive on this module's own prose
    (which legitimately narrates forbidden concepts by name, e.g.
    explaining why prepare_activation()/validate_activation() are
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


def _valid_auth(request_id="005"):
    return video_005_authorization(request_id=request_id)


def _structurally_valid_handoff(request_id="005", auth=None, **review_kwargs):
    result = _real_ready_result(request_id=request_id)
    review = PreProductionReviewer().review(
        PreProductionReviewInput(preparation_result=result, **review_kwargs)
    )
    prod_handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
    intake = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=prod_handoff))
    return HumanAuthorizationHandoffBuilder().build(
        HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=auth or _valid_auth(request_id))
    )


def _eligible_handoff_no_authorization(request_id="005"):
    result = _real_ready_result(request_id=request_id)
    review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
    prod_handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
    intake = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=prod_handoff))
    return HumanAuthorizationHandoffBuilder().build(HumanAuthorizationHandoffInput(intake=intake))


def _not_accepted_handoff():
    result = _not_ready_result()
    review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
    prod_handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
    intake = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=prod_handoff))
    return HumanAuthorizationHandoffBuilder().build(HumanAuthorizationHandoffInput(intake=intake))


def _findings_by_dimension(result):
    return {f.dimension: f for f in result.findings}


class _MockChainMixin:
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p3_20_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def _mock_report_service(self, cost_per_job=67.5, available_credits=1000.0):
        provider = MockHiggsfieldProvider(cost_per_job=cost_per_job, available_credits=available_credits)
        identity_lock = ReleaseCandidateIdentityLock(VIDEO_005_RELEASE_CANDIDATE)
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
        activation_service = RequestScopedActivationService(gate, identity_lock)
        provider_activation_service = ControlledRealProviderActivationService(
            gate, identity_lock, activation_service
        )
        lock = FileCriticalSectionLock(self._tmp)
        job_service = GenerationJobService(
            provider, gate, lock=lock,
            activation_service=activation_service,
            provider_activation_service=provider_activation_service,
        )
        return FinalReportService(provider, gate, job_service=job_service)

    def _real_prepared_activation(self, request_id="005", auth=None):
        director = AIDirector()
        report_service = self._mock_report_service()
        return director.prepare_real_generation_activation(
            video_id="005", title="t", hook="h", objective="o",
            duration=15, approved=True,
            real_generation_authorization=auth or _valid_auth(request_id),
            report_service=report_service,
        )


class ValidAuthorizationTests(unittest.TestCase):
    """Test 1 from the P3.20 mandatory list."""

    def test_valid_authorization_eligible_for_activation(self):
        handoff = _structurally_valid_handoff()
        result = ActivationEligibilityChecker().check_eligibility(ActivationEligibilityInput(human_authorization_handoff=handoff))
        self.assertEqual(result.status, ActivationEligibilityStatus.ELIGIBLE_FOR_ACTIVATION)
        self.assertEqual(result.reasons, ())


class MissingAuthorizationTests(unittest.TestCase):
    """Test 2 from the P3.20 mandatory list."""

    def test_missing_authorization_not_valid(self):
        handoff = _eligible_handoff_no_authorization()
        result = ActivationEligibilityChecker().check_eligibility(ActivationEligibilityInput(human_authorization_handoff=handoff))
        self.assertEqual(result.status, ActivationEligibilityStatus.HUMAN_AUTHORIZATION_NOT_VALID)
        finding = _findings_by_dimension(result)["human_authorization_valid"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, EligibilityFailureCategory.AUTHORIZATION_MISSING)


class InvalidAuthorizationTests(unittest.TestCase):
    """Test 3 from the P3.20 mandatory list."""

    def test_rejected_authorization_not_valid(self):
        result_prep = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result_prep))
        prod_handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        intake = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=prod_handoff))
        handoff = HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=_valid_auth("999"))
        )
        result = ActivationEligibilityChecker().check_eligibility(ActivationEligibilityInput(human_authorization_handoff=handoff))
        self.assertEqual(result.status, ActivationEligibilityStatus.HUMAN_AUTHORIZATION_NOT_VALID)
        finding = _findings_by_dimension(result)["human_authorization_valid"]
        self.assertEqual(finding.category, EligibilityFailureCategory.AUTHORIZATION_INVALID)


class RequestMismatchTests(unittest.TestCase):
    """Test 4 from the P3.20 mandatory list."""

    def test_activation_contract_request_mismatch_rejected(self):
        handoff = _structurally_valid_handoff("005")
        foreign_contract = RequestScopedActivationContract(
            activation_id="fake-activation-id",
            request_id="999",
            job_type=VIDEO_005_JOB_TYPE,
            duration=VIDEO_005_DURATION,
            resolution=VIDEO_005_RESOLUTION,
            aspect_ratio=VIDEO_005_ASPECT_RATIO,
            prompt_sha256="0" * 64,
            authorization_id=handoff.authorization_id,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        result = ActivationEligibilityChecker().check_eligibility(
            ActivationEligibilityInput(human_authorization_handoff=handoff, activation_contract=foreign_contract)
        )
        self.assertEqual(result.status, ActivationEligibilityStatus.NOT_ELIGIBLE_FOR_ACTIVATION)
        finding = _findings_by_dimension(result)["activation_contract_request_binding"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, EligibilityFailureCategory.AUTHORIZATION_REQUEST_MISMATCH)


class ReadinessMismatchTests(unittest.TestCase):
    """Test 5 from the P3.20 mandatory list."""

    def test_tampered_readiness_chain_detected_via_identity_consistency(self):
        handoff = _structurally_valid_handoff()
        tampered_review = dc_replace(handoff.intake.handoff.review, mission_id="a-different-mission")
        tampered_prod_handoff = dc_replace(handoff.intake.handoff, review=tampered_review)
        tampered_intake = dc_replace(handoff.intake, handoff=tampered_prod_handoff)
        tampered_handoff = dc_replace(handoff, intake=tampered_intake)
        result = ActivationEligibilityChecker().check_eligibility(
            ActivationEligibilityInput(human_authorization_handoff=tampered_handoff)
        )
        self.assertEqual(result.status, ActivationEligibilityStatus.NOT_ELIGIBLE_FOR_ACTIVATION)


class IntakeMismatchTests(unittest.TestCase):
    """Test 6 from the P3.20 mandatory list."""

    def test_tampered_intake_id_detected(self):
        handoff = _structurally_valid_handoff()
        tampered_handoff = dc_replace(handoff, intake_id="not-the-real-intake-id")
        result = ActivationEligibilityChecker().check_eligibility(
            ActivationEligibilityInput(human_authorization_handoff=tampered_handoff)
        )
        self.assertEqual(result.status, ActivationEligibilityStatus.NOT_ELIGIBLE_FOR_ACTIVATION)
        finding = _findings_by_dimension(result)["identity_chain_consistency"]
        self.assertFalse(finding.passed)


class ExpiredAuthorizationTests(unittest.TestCase):
    """Test 7 from the P3.20 mandatory list -- local staleness sanity
    check on a supplied activation_contract's created_at."""

    def test_stale_activation_contract_rejected(self):
        handoff = _structurally_valid_handoff()
        stale_created_at = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
        contract = RequestScopedActivationContract(
            activation_id="a1",
            request_id="005",
            job_type=VIDEO_005_JOB_TYPE,
            duration=VIDEO_005_DURATION,
            resolution=VIDEO_005_RESOLUTION,
            aspect_ratio=VIDEO_005_ASPECT_RATIO,
            prompt_sha256="0" * 64,
            authorization_id=handoff.authorization_id,
            created_at=stale_created_at,
        )
        result = ActivationEligibilityChecker().check_eligibility(
            ActivationEligibilityInput(human_authorization_handoff=handoff, activation_contract=contract)
        )
        self.assertEqual(result.status, ActivationEligibilityStatus.NOT_ELIGIBLE_FOR_ACTIVATION)
        finding = _findings_by_dimension(result)["activation_contract_staleness_sanity"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, EligibilityFailureCategory.AUTHORIZATION_EXPIRED)

    def test_fresh_activation_contract_passes_staleness_with_injected_now(self):
        handoff = _structurally_valid_handoff()
        fixed_created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        contract = RequestScopedActivationContract(
            activation_id="a1",
            request_id="005",
            job_type=VIDEO_005_JOB_TYPE,
            duration=VIDEO_005_DURATION,
            resolution=VIDEO_005_RESOLUTION,
            aspect_ratio=VIDEO_005_ASPECT_RATIO,
            prompt_sha256=handoff.intake.handoff.review.generation_request and __import__("hashlib").sha256(
                handoff.intake.handoff.review.generation_request.prompt.encode("utf-8")
            ).hexdigest(),
            authorization_id=handoff.authorization_id,
            created_at=fixed_created_at.isoformat(),
        )
        result = ActivationEligibilityChecker().check_eligibility(
            ActivationEligibilityInput(
                human_authorization_handoff=handoff,
                activation_contract=contract,
                now=lambda: fixed_created_at + timedelta(seconds=10),
            )
        )
        self.assertTrue(_findings_by_dimension(result)["activation_contract_staleness_sanity"].passed)


class RevokedAuthorizationTests(unittest.TestCase):
    """Test 8 from the P3.20 mandatory list."""

    def test_already_consumed_and_revoked_categories_defined_but_unreachable(self):
        categories = {m.value for m in EligibilityFailureCategory}
        self.assertIn("AUTHORIZATION_REVOKED", categories)
        self.assertIn("ACTIVATION_ALREADY_CONSUMED", categories)

        handoff = _structurally_valid_handoff()
        result = ActivationEligibilityChecker().check_eligibility(ActivationEligibilityInput(human_authorization_handoff=handoff))
        used = {f.category for f in result.findings if f.category is not None}
        self.assertNotIn(EligibilityFailureCategory.AUTHORIZATION_REVOKED, used)
        self.assertNotIn(EligibilityFailureCategory.ACTIVATION_ALREADY_CONSUMED, used)


class AuthorizationIdentityTests(unittest.TestCase):
    """Test 9 from the P3.20 mandatory list."""

    def test_activation_contract_must_bind_to_same_authorization_id(self):
        handoff = _structurally_valid_handoff()
        contract = RequestScopedActivationContract(
            activation_id="a1",
            request_id="005",
            job_type=VIDEO_005_JOB_TYPE,
            duration=VIDEO_005_DURATION,
            resolution=VIDEO_005_RESOLUTION,
            aspect_ratio=VIDEO_005_ASPECT_RATIO,
            prompt_sha256="0" * 64,
            authorization_id="some-other-authorization-id",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        result = ActivationEligibilityChecker().check_eligibility(
            ActivationEligibilityInput(human_authorization_handoff=handoff, activation_contract=contract)
        )
        finding = _findings_by_dimension(result)["activation_contract_request_binding"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, EligibilityFailureCategory.ACTIVATION_CONTRACT_MISMATCH)


class AuthorizedByHumanSemanticsTests(unittest.TestCase):
    """Test 10 from the P3.20 mandatory list."""

    def test_authorized_by_human_false_never_reaches_eligible(self):
        result_prep = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result_prep))
        prod_handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        intake = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=prod_handoff))
        auth = RealGenerationAuthorization(request_id="005", authorized_by_human=False)
        handoff = HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=auth)
        )
        result = ActivationEligibilityChecker().check_eligibility(ActivationEligibilityInput(human_authorization_handoff=handoff))
        self.assertEqual(result.status, ActivationEligibilityStatus.HUMAN_AUTHORIZATION_NOT_VALID)


class ActivationEligibilityPassTests(unittest.TestCase):
    """Test 11 from the P3.20 mandatory list."""

    def test_eligible_for_activation_pass(self):
        handoff = _structurally_valid_handoff()
        result = ActivationEligibilityChecker().check_eligibility(ActivationEligibilityInput(human_authorization_handoff=handoff))
        self.assertEqual(result.status, ActivationEligibilityStatus.ELIGIBLE_FOR_ACTIVATION)
        self.assertTrue(all(f.passed for f in result.findings))


class ActivationEligibilityFailTests(unittest.TestCase):
    """Test 12 from the P3.20 mandatory list."""

    def test_not_eligible_for_activation_fail(self):
        handoff = _not_accepted_handoff()
        result = ActivationEligibilityChecker().check_eligibility(ActivationEligibilityInput(human_authorization_handoff=handoff))
        self.assertEqual(result.status, ActivationEligibilityStatus.HUMAN_AUTHORIZATION_NOT_VALID)
        self.assertTrue(result.reasons)


class NoAutomaticActivationTests(unittest.TestCase):
    """Test 13 from the P3.20 mandatory list -- adversarial: review
    PASS, handoff READY, intake ACCEPTED, authorized_by_human=True --
    none of it can create an activation contract."""

    def test_fully_authorized_chain_never_constructs_activation_contract(self):
        handoff = _structurally_valid_handoff()
        self.assertEqual(handoff.intake.handoff.review.status.value, "PASS")
        self.assertEqual(handoff.intake.handoff.status.value, "READY_FOR_PRODUCTION_AUTHORITY")
        self.assertEqual(handoff.intake.status.value, "ACCEPTED_FOR_P2_CONSIDERATION")
        self.assertEqual(handoff.status.value, "AUTHORIZATION_STRUCTURALLY_VALID")
        result = ActivationEligibilityChecker().check_eligibility(ActivationEligibilityInput(human_authorization_handoff=handoff))
        self.assertEqual(result.status, ActivationEligibilityStatus.ELIGIBLE_FOR_ACTIVATION)
        self.assertIsNone(result.activation_contract)
        self.assertIsNone(result.provider_activation_contract)

    def test_checker_never_constructs_activation_contract_objects(self):
        code = MODULE_SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(code)
        constructor_calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertNotIn("RequestScopedActivationContract", constructor_calls)
        self.assertNotIn("ControlledRealProviderActivationContract", constructor_calls)


class NoActivationConstructionWhenProhibitedTests(unittest.TestCase):
    """Test 14 from the P3.20 mandatory list."""

    def test_no_prepare_or_validate_calls_anywhere(self):
        code = _module_code_without_docstrings()
        self.assertNotIn(".prepare(", code)
        self.assertNotIn(".validate(", code)
        self.assertNotIn("prepare_activation(", code)
        self.assertNotIn("validate_activation(", code)


class NoExecutionTests(unittest.TestCase):
    """Test 15 from the P3.20 mandatory list."""

    def test_no_create_job_or_execute(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("create_job(", code)
        self.assertNotIn(".execute(", code)

    def test_status_values_never_imply_activation_or_execution(self):
        values = {m.value for m in ActivationEligibilityStatus}
        self.assertEqual(
            values,
            {
                "HUMAN_AUTHORIZATION_NOT_VALID",
                "ELIGIBLE_FOR_ACTIVATION",
                "ACTIVATION_CONTRACT_STRUCTURALLY_VALID",
                "NOT_ELIGIBLE_FOR_ACTIVATION",
            },
        )
        for forbidden in ("ACTIVATED", "EXECUTING", "EXECUTED"):
            self.assertNotIn(forbidden, values)


class NoProviderNetworkCLICreditsTests(unittest.TestCase):
    """Tests 16, 17, 18, 19 from the P3.20 mandatory list."""

    def test_no_provider_or_client_imports(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("HiggsfieldProvider", code)
        self.assertNotIn("HiggsfieldClient", code)

    def test_no_network_or_cli_substrings(self):
        code = _module_code_without_docstrings()
        for banned in ("requests.", "urllib.", "socket.", "subprocess.", "os.system"):
            self.assertNotIn(banned, code)

    def test_no_credit_or_balance_calls(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("get_account_balance", code)
        self.assertNotIn("estimate_cost", code)


class Video005RegressionTests(unittest.TestCase):
    """Test 20 from the P3.20 mandatory list."""

    @classmethod
    def setUpClass(cls):
        cls.handoff = _structurally_valid_handoff("005", expected_prompt_sha256=VIDEO_005_PROMPT_SHA256)
        cls.result = ActivationEligibilityChecker().check_eligibility(
            ActivationEligibilityInput(human_authorization_handoff=cls.handoff)
        )

    def test_video_005_eligible(self):
        self.assertEqual(self.result.status, ActivationEligibilityStatus.ELIGIBLE_FOR_ACTIVATION)

    def test_video_005_identity_preserved(self):
        self.assertEqual(self.result.request_id, VIDEO_005_REQUEST_ID)
        gr = self.result.human_authorization_handoff.intake.handoff.review.generation_request
        self.assertEqual(gr.job_type, VIDEO_005_JOB_TYPE)
        self.assertEqual(gr.duration, VIDEO_005_DURATION)
        self.assertEqual(gr.resolution, VIDEO_005_RESOLUTION)
        self.assertEqual(gr.aspect_ratio, VIDEO_005_ASPECT_RATIO)

    def test_video_005_still_unexecuted(self):
        gr = self.result.human_authorization_handoff.intake.handoff.review.generation_request
        self.assertFalse(gr.approved)
        self.assertIsNone(gr.real_generation_authorization)


class IdentityConsistencyTests(unittest.TestCase):
    """Test 21 from the P3.20 mandatory list."""

    def test_full_identity_chain_preserved(self):
        handoff = _structurally_valid_handoff()
        result = ActivationEligibilityChecker().check_eligibility(ActivationEligibilityInput(human_authorization_handoff=handoff))
        self.assertEqual(result.request_id, handoff.request_id)
        self.assertEqual(result.mission_id, handoff.mission_id)
        self.assertEqual(result.review_id, handoff.review_id)
        self.assertEqual(result.intake_id, handoff.intake_id)
        self.assertEqual(result.handoff_id, handoff.handoff_id)


class ProvenanceTests(unittest.TestCase):
    """Test 22 from the P3.20 mandatory list."""

    def test_full_traceability_chain_reachable(self):
        handoff = _structurally_valid_handoff()
        result = ActivationEligibilityChecker().check_eligibility(ActivationEligibilityInput(human_authorization_handoff=handoff))
        self.assertIsNotNone(result.human_authorization_handoff.intake.handoff.review.production_preparation.script_artifact)
        self.assertEqual(result.mission_id, "mission-005")


class DeterminismTests(unittest.TestCase):
    """Test 23 from the P3.20 mandatory list."""

    def test_deterministic_eligibility_no_contract(self):
        handoff = _structurally_valid_handoff()
        a = ActivationEligibilityChecker().check_eligibility(ActivationEligibilityInput(human_authorization_handoff=handoff))
        b = ActivationEligibilityChecker().check_eligibility(ActivationEligibilityInput(human_authorization_handoff=handoff))
        self.assertEqual(a.content_hash, b.content_hash)

    def test_deterministic_eligibility_with_fixed_now_and_contract(self):
        handoff = _structurally_valid_handoff()
        fixed_now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        contract = RequestScopedActivationContract(
            activation_id="a1", request_id="005", job_type=VIDEO_005_JOB_TYPE,
            duration=VIDEO_005_DURATION, resolution=VIDEO_005_RESOLUTION,
            aspect_ratio=VIDEO_005_ASPECT_RATIO,
            prompt_sha256=__import__("hashlib").sha256(
                handoff.intake.handoff.review.generation_request.prompt.encode("utf-8")
            ).hexdigest(),
            authorization_id=handoff.authorization_id, created_at=fixed_now.isoformat(),
        )
        a = ActivationEligibilityChecker().check_eligibility(
            ActivationEligibilityInput(human_authorization_handoff=handoff, activation_contract=contract, now=lambda: fixed_now)
        )
        b = ActivationEligibilityChecker().check_eligibility(
            ActivationEligibilityInput(human_authorization_handoff=handoff, activation_contract=contract, now=lambda: fixed_now)
        )
        self.assertEqual(a.content_hash, b.content_hash)
        self.assertEqual(a.status, ActivationEligibilityStatus.ACTIVATION_CONTRACT_STRUCTURALLY_VALID)


class IdempotencyTests(unittest.TestCase):
    """Test 24 from the P3.20 mandatory list."""

    def test_idempotent_repeated_eligibility_check(self):
        handoff = _structurally_valid_handoff()
        checker = ActivationEligibilityChecker()
        request = ActivationEligibilityInput(human_authorization_handoff=handoff)
        first = checker.check_eligibility(request)
        second = checker.check_eligibility(request)
        third = checker.check_eligibility(request)
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(second.content_hash, third.content_hash)


class ImmutableInputsTests(unittest.TestCase):
    """Test 25 from the P3.20 mandatory list."""

    def test_immutable_input(self):
        handoff = _structurally_valid_handoff()
        request = ActivationEligibilityInput(human_authorization_handoff=handoff)
        with self.assertRaises(FrozenInstanceError):
            request.eligibility_id = "tampered"  # type: ignore

    def test_immutable_output(self):
        handoff = _structurally_valid_handoff()
        result = ActivationEligibilityChecker().check_eligibility(ActivationEligibilityInput(human_authorization_handoff=handoff))
        with self.assertRaises(FrozenInstanceError):
            result.status = ActivationEligibilityStatus.NOT_ELIGIBLE_FOR_ACTIVATION  # type: ignore

    def test_source_handoff_and_generation_request_untouched(self):
        handoff = _structurally_valid_handoff()
        gr_before = handoff.intake.handoff.review.generation_request
        ActivationEligibilityChecker().check_eligibility(ActivationEligibilityInput(human_authorization_handoff=handoff))
        gr_after = handoff.intake.handoff.review.generation_request
        self.assertIs(gr_before, gr_after)
        self.assertFalse(gr_after.approved)
        self.assertIsNone(gr_after.real_generation_authorization)


class ReplayProtectionTests(unittest.TestCase):
    """Test 34 from the P3.20 mandatory list."""

    def test_no_executed_request_store_reference(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("ExecutedRequestStore", code)
        self.assertNotIn("mark_executed", code)


class CriticalSectionPreservationTests(unittest.TestCase):
    """Test 38 from the P3.20 mandatory list."""

    def test_no_critical_section_lock_reference(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("CriticalSectionLock", code)
        self.assertNotIn(".acquire(", code)


class SoleExecutionPathTests(unittest.TestCase):
    """Tests 40, 41 from the P3.20 mandatory list."""

    def test_no_create_job_in_module(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("create_job(", code)

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


class MissionStateAuthorityTests(unittest.TestCase):
    """Test 39 from the P3.20 mandatory list."""

    def test_no_state_authority(self):
        handoff = _structurally_valid_handoff()
        result = ActivationEligibilityChecker().check_eligibility(ActivationEligibilityInput(human_authorization_handoff=handoff))
        self.assertFalse(hasattr(result, "mission_state"))
        self.assertFalse(hasattr(ActivationEligibilityChecker(), "state_machine"))
        self.assertFalse(hasattr(ActivationEligibilityChecker(), "transition"))


class P2BoundaryTests(unittest.TestCase):
    """Test 43 from the P3.20 mandatory list."""

    def test_gate_and_services_never_constructed(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("GenerationApprovalGate(", code)
        self.assertNotIn("RequestScopedActivationService(", code)
        self.assertNotIn("ControlledRealProviderActivationService(", code)
        self.assertNotIn(".evaluate(", code)

    def test_p2_module_boundary_never_crossed(self):
        source = MODULE_SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        forbidden = {
            "agents.generation_approval_gate",
            "agents.generation_job_service",
            "agents.activation_readiness",
            "agents.real_provider_execution_gate",
            "agents.real_provider_activation_preflight",
            "agents.critical_section_lock",
            "agents.executed_request_store",
            "integrations.higgsfield.provider",
            "integrations.higgsfield.client",
            "agents.mission_state_machine",
        }
        offenders = imports & forbidden
        self.assertFalse(offenders, f"activation_eligibility.py crosses the P2 boundary: {offenders}")


class DirectorIntegrationTests(unittest.TestCase):
    """Test 42 from the P3.20 mandatory list."""

    def test_director_exposes_activation_eligibility(self):
        director = AIDirector()
        self.assertTrue(hasattr(director, "activation_eligibility"))

    def test_director_delegates_to_injected_checker(self):
        handoff = _structurally_valid_handoff()
        director = AIDirector()
        result = director.activation_eligibility(
            ActivationEligibilityInput(human_authorization_handoff=handoff), checker=ActivationEligibilityChecker()
        )
        self.assertIsInstance(result, ActivationEligibilityResult)
        self.assertEqual(result.status, ActivationEligibilityStatus.ELIGIBLE_FOR_ACTIVATION)

    def test_director_default_checker_used_without_injection(self):
        handoff = _structurally_valid_handoff()
        director = AIDirector()
        result = director.activation_eligibility(ActivationEligibilityInput(human_authorization_handoff=handoff))
        self.assertEqual(result.status, ActivationEligibilityStatus.ELIGIBLE_FOR_ACTIVATION)

    def test_existing_methods_unaffected(self):
        director = AIDirector()
        for name in (
            "run_business_pipeline", "run_video_mission", "prepare_production_from_script",
            "prepare_video_generation_request", "review_video_generation_request",
            "handoff_video_generation_request", "production_authority_intake",
            "human_authorization_handoff", "prepare_real_generation_activation",
            "execute_real_generation_activation",
        ):
            self.assertTrue(hasattr(director, name), f"missing {name}")

    def test_not_invoked_automatically_by_human_authorization_handoff(self):
        director_source = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        tree = ast.parse(director_source)
        method_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "human_authorization_handoff":
                method_node = node
                break
        self.assertIsNotNone(method_node)
        called_names = {
            node.func.attr
            for node in ast.walk(method_node)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn("activation_eligibility", called_names)

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
        self.assertNotIn("activation_eligibility", called_names)

    def test_director_py_new_method_has_no_forbidden_calls(self):
        director_source = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        tree = ast.parse(director_source)
        method_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "activation_eligibility":
                method_node = node
                break
        self.assertIsNotNone(method_node, "activation_eligibility method not found in director.py")
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
            "validate_activation", "prepare_real_generation_activation",
            "execute_real_generation_activation", "RequestScopedActivationContract",
            "ControlledRealProviderActivationContract",
        }
        self.assertFalse(offenders, f"activation_eligibility contains forbidden call(s): {offenders}")


class InvalidInputTests(unittest.TestCase):
    """Structural input-validation regression, mirrors P3.17/18/19's own."""

    def test_invalid_handoff_raises_explicitly(self):
        with self.assertRaises(ActivationEligibilityError):
            ActivationEligibilityChecker().check_eligibility(
                ActivationEligibilityInput(human_authorization_handoff="not-a-handoff")  # type: ignore
            )


class RegressionProtectionTests(unittest.TestCase):
    """Test 44 from the P3.20 mandatory list."""

    def test_rejected_never_silently_upgraded(self):
        handoff = _not_accepted_handoff()
        result = ActivationEligibilityChecker().check_eligibility(ActivationEligibilityInput(human_authorization_handoff=handoff))
        self.assertNotIn(
            result.status,
            (ActivationEligibilityStatus.ELIGIBLE_FOR_ACTIVATION, ActivationEligibilityStatus.ACTIVATION_CONTRACT_STRUCTURALLY_VALID),
        )


class P2_29CompatibilityTests(_MockChainMixin, unittest.TestCase):
    """Tests 26, 27, 28, 29, 30 from the P3.20 mandatory list --
    real, externally-prepared P2.21/P2.26 snapshots (obtained only via
    the pre-existing, unmodified P2.29 entry point over a Mock chain)
    are structurally valid according to this phase's checker, proving
    P2.20/P2.21/P2.26/P2.27/P2.29 all remain compatible and untouched."""

    def test_real_activation_contract_structurally_valid(self):
        shared_auth = _valid_auth("005")
        prepared = self._real_prepared_activation("005", auth=shared_auth)
        handoff = _structurally_valid_handoff("005", auth=shared_auth)
        result = ActivationEligibilityChecker().check_eligibility(
            ActivationEligibilityInput(
                human_authorization_handoff=handoff,
                activation_contract=prepared.activation_contract,
                provider_activation_contract=prepared.provider_activation_contract,
            )
        )
        self.assertEqual(result.status, ActivationEligibilityStatus.ACTIVATION_CONTRACT_STRUCTURALLY_VALID)
        self.assertTrue(all(f.passed for f in result.findings))

    def test_prepare_real_generation_activation_still_requires_explicit_authorization(self):
        import inspect

        sig = inspect.signature(AIDirector.prepare_real_generation_activation)
        self.assertIs(sig.parameters["real_generation_authorization"].default, inspect.Parameter.empty)

    def test_p2_20_critical_section_lock_still_used_by_real_chain(self):
        # Confirms P2.20's FileCriticalSectionLock remains the real
        # chain's own serialization mechanism -- this phase never
        # substitutes or duplicates it.
        prepared = self._real_prepared_activation("005")
        self.assertTrue(prepared.activation_contract.activation_id)

    def test_p2_26_provider_activation_contract_bound_to_p2_21_contract(self):
        prepared = self._real_prepared_activation("005")
        self.assertEqual(
            prepared.provider_activation_contract.request_scoped_activation_id,
            prepared.activation_contract.activation_id,
        )


class SecurityTests(unittest.TestCase):
    """
    AST-based, docstring-false-positive-safe, static verification that
    `agents/activation_eligibility.py` never reaches real execution,
    any P2 authority mechanism beyond the legitimate TYPE reuse, the
    Mission State Machine, or an event bus -- and that it never
    CONSTRUCTS `RequestScopedActivationContract`/`ControlledReal
    ProviderActivationContract` (a Call node), even though it freely
    REFERENCES the types (a Name/Attribute node, for isinstance/typing/
    field reads).
    """

    FORBIDDEN_MODULES = {
        "integrations.higgsfield.client",
        "integrations.higgsfield.provider",
        "integrations.higgsfield.mock_provider",
        "agents.generation_approval_gate",
        "agents.generation_job_service",
        "agents.generation_cost_service",
        "agents.cost_engine",
        "agents.activation_readiness",
        "agents.production_activation_boundary",
        "agents.real_provider_execution_gate",
        "agents.real_provider_activation_preflight",
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
        "prepare_activation", "validate_activation", "consume", "prepare", "validate",
        "prepare_real_generation_activation", "execute_real_generation_activation",
        "RequestScopedActivationContract", "ControlledRealProviderActivationContract",
        "GenerationApprovalGate", "RequestScopedActivationService",
        "ControlledRealProviderActivationService", "GenerationJobService",
        "HiggsfieldProvider", "HiggsfieldClient",
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
        self.assertFalse(offenders, f"activation_eligibility.py imports forbidden module(s): {offenders}")

    def test_no_forbidden_calls(self):
        # "prepare"/"validate" here means bare method names -- this
        # module defines neither, and calls neither on any object; the
        # only "check_eligibility"/"_check_*" names it defines are
        # distinct identifiers, never colliding with these.
        offenders = self._called_names() & self.FORBIDDEN_CALL_NAMES
        self.assertFalse(offenders, f"activation_eligibility.py contains forbidden call(s): {offenders}")

    def test_activation_contract_types_referenced_but_never_constructed(self):
        names_referenced = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name):
                names_referenced.add(node.id)
        self.assertIn("RequestScopedActivationContract", names_referenced)
        self.assertIn("ControlledRealProviderActivationContract", names_referenced)
        self.assertNotIn("RequestScopedActivationContract", self._called_names())
        self.assertNotIn("ControlledRealProviderActivationContract", self._called_names())

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
        self.assertNotIn("RequestScopedActivationContract", class_defs)
        self.assertNotIn("ControlledRealProviderActivationContract", class_defs)

    def test_activation_contract_modules_imported_for_type_only(self):
        names_from_activation_contract = set()
        names_from_provider_activation = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module == "agents.activation_contract":
                for alias in node.names:
                    names_from_activation_contract.add(alias.name)
            if isinstance(node, ast.ImportFrom) and node.module == "agents.controlled_real_provider_activation":
                for alias in node.names:
                    names_from_provider_activation.add(alias.name)
        self.assertIn("RequestScopedActivationContract", names_from_activation_contract)
        self.assertNotIn("RequestScopedActivationService", names_from_activation_contract)
        self.assertIn("ControlledRealProviderActivationContract", names_from_provider_activation)
        self.assertNotIn("ControlledRealProviderActivationService", names_from_provider_activation)


if __name__ == "__main__":
    unittest.main()
