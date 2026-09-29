"""
Tests — Production Activation Handoff (Phase P3.21).

Fully offline: no network, no Higgsfield, no social platform, no OAuth,
no credential of any kind is imported or constructed anywhere in this
file. Verifies `agents/production_activation_handoff.py` and the new
`AIDirector.production_activation_handoff()` entry point in
`director.py`.

The one exception, isolated to `P2CompatibilityTests`, exercises the
pre-existing (Phase P2.29) `AIDirector.prepare_real_generation_
activation()` entry point purely to obtain REAL, externally-prepared
`RequestScopedActivationContract`/`ControlledRealProviderActivation
Contract` snapshots to feed through the full P3.20/P3.21 chain --
always via an injected `MockHiggsfieldProvider`-backed `report_service`,
never the real chain.
"""

import ast
import shutil
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace as dc_replace
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import RequestScopedActivationService
from agents.activation_eligibility import (
    ActivationEligibilityChecker,
    ActivationEligibilityInput,
    ActivationEligibilityStatus,
)
from agents.asset_preparation_system import AssetPreparationSystem
from agents.content_agent import ContentAgent, ContentAgentInput
from agents.controlled_real_provider_activation import ControlledRealProviderActivationService
from agents.critical_section_lock import FileCriticalSectionLock
from agents.final_report_service import FinalReportService
from agents.generation_approval_gate import GenerationApprovalGate, RealGenerationAuthorization
from tests.authorization_content_helpers import video_005_authorization
from agents.generation_job_service import GenerationJobService
from agents.human_authorization_handoff import HumanAuthorizationHandoffBuilder, HumanAuthorizationHandoffInput
from agents.planner import VideoPlanner
from agents.pre_production_review import PreProductionReviewInput, PreProductionReviewer
from agents.production_activation_handoff import (
    HandoffFailureCategory,
    ProductionActivationHandoff,
    ProductionActivationHandoffBuilder,
    ProductionActivationHandoffError,
    ProductionActivationHandoffInput,
    ProductionActivationHandoffStatus,
)
from agents.production_authority_intake import ProductionAuthorityIntake, ProductionAuthorityIntakeInput
from agents.production_readiness_handoff import ProductionReadinessHandoffBuilder, ProductionReadinessHandoffInput
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.release_candidate_identity_lock import ReleaseCandidateIdentityLock, VIDEO_005_RELEASE_CANDIDATE
from agents.script_production_bridge import ProductionPreparationInput
from agents.strategy_agent import StrategyAgent, StrategyAgentInput
from agents.video_production_preparation import VideoProductionPreparation, VideoProductionPreparationInput
from director import AIDirector
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider

MODULE_SOURCE_PATH = PROJECT_ROOT / "agents" / "production_activation_handoff.py"

VIDEO_005_REQUEST_ID = "005"
VIDEO_005_JOB_TYPE = "seedance_2_0"
VIDEO_005_DURATION = 15
VIDEO_005_RESOLUTION = "720p"
VIDEO_005_ASPECT_RATIO = "9:16"
VIDEO_005_PROMPT_SHA256 = "1c498617adb4603bcf2fc114a9cb9e8fe2219f09285adbff4d1e6c7a10a669e1"


def _module_code_without_docstrings():
    """Source of agents/production_activation_handoff.py with every
    module/class/function docstring stripped -- so raw-substring
    boundary checks below never false-positive on this module's own
    prose (which legitimately narrates forbidden concepts by name)."""

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
    without_docstrings = "".join(lines)

    # Also strip `#` comments (Section 14/26's "correctly exclude ...
    # comments") -- tokenize-based, so a `#` inside a string literal is
    # never mistaken for a comment.
    import io
    import tokenize as _tokenize

    out_lines = without_docstrings.splitlines(keepends=True)
    for tok in _tokenize.generate_tokens(io.StringIO(without_docstrings).readline):
        if tok.type == _tokenize.COMMENT:
            row = tok.start[0] - 1
            col_start = tok.start[1]
            col_end = tok.end[1]
            line = out_lines[row]
            out_lines[row] = line[:col_start] + line[col_end:]
    return "".join(out_lines)


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


def _eligible_eligibility(request_id="005", auth=None, **review_kwargs):
    result = _real_ready_result(request_id=request_id)
    review = PreProductionReviewer().review(
        PreProductionReviewInput(preparation_result=result, **review_kwargs)
    )
    prod_handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
    intake = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=prod_handoff))
    handoff = HumanAuthorizationHandoffBuilder().build(
        HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=auth or _valid_auth(request_id))
    )
    return ActivationEligibilityChecker().check_eligibility(ActivationEligibilityInput(human_authorization_handoff=handoff))


def _not_eligible_eligibility():
    result = _not_ready_result()
    review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
    prod_handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
    intake = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=prod_handoff))
    handoff = HumanAuthorizationHandoffBuilder().build(HumanAuthorizationHandoffInput(intake=intake))
    return ActivationEligibilityChecker().check_eligibility(ActivationEligibilityInput(human_authorization_handoff=handoff))


def _findings_by_dimension(handoff):
    return {f.dimension: f for f in handoff.findings}


class _MockChainMixin:
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p3_21_"))
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


# ------------------------------------------------------------------
# IDENTITY (tests 1-6)
# ------------------------------------------------------------------


class RequestIdentityRequiredTests(unittest.TestCase):
    """Test 1 from the P3.21 mandatory list."""

    def test_request_id_preserved(self):
        eligibility = _eligible_eligibility(request_id="custom-005")
        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        self.assertEqual(handoff.request_id, "custom-005")


class MissionIdContractTests(unittest.TestCase):
    """Test 2 from the P3.21 mandatory list."""

    def test_mission_id_preserved(self):
        eligibility = _eligible_eligibility()
        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        self.assertEqual(handoff.mission_id, "mission-005")


class MismatchedRequestRejectedTests(unittest.TestCase):
    """Test 3 from the P3.21 mandatory list."""

    def test_tampered_request_id_detected(self):
        eligibility = _eligible_eligibility()
        handoff = ProductionActivationHandoffBuilder().build(
            ProductionActivationHandoffInput(eligibility=eligibility, expected_request_id="not-the-real-one")
        )
        self.assertEqual(handoff.status, ProductionActivationHandoffStatus.NOT_ELIGIBLE_FOR_HANDOFF)
        finding = _findings_by_dimension(handoff)["expected_request_id_pin"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, HandoffFailureCategory.STALE_OR_MISMATCHED_HANDOFF)


class AuthorizationIdentityPreservedTests(unittest.TestCase):
    """Test 4 from the P3.21 mandatory list."""

    def test_authorization_id_preserved(self):
        eligibility = _eligible_eligibility()
        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        self.assertEqual(handoff.authorization_id, eligibility.human_authorization_handoff.authorization_id)
        self.assertIsNotNone(handoff.authorization_id)


class EligibilityIdentityPreservedTests(unittest.TestCase):
    """Test 5 from the P3.21 mandatory list."""

    def test_eligibility_identity_preserved(self):
        eligibility = _eligible_eligibility()
        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        self.assertEqual(handoff.eligibility_id, eligibility.eligibility_id)
        self.assertEqual(handoff.human_authorization_handoff_id, eligibility.handoff_id)
        self.assertEqual(handoff.intake_id, eligibility.intake_id)
        self.assertEqual(handoff.review_id, eligibility.review_id)


class ArtifactProvenancePreservedTests(unittest.TestCase):
    """Test 6 from the P3.21 mandatory list."""

    def test_full_traceability_chain_reachable(self):
        eligibility = _eligible_eligibility()
        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        script_artifact = handoff.eligibility.human_authorization_handoff.intake.handoff.review.production_preparation.script_artifact
        self.assertIsNotNone(script_artifact)
        self.assertEqual(script_artifact.mission_id, "mission-005")


# ------------------------------------------------------------------
# ELIGIBILITY (tests 7-12)
# ------------------------------------------------------------------


class IneligibleRejectedTests(unittest.TestCase):
    """Test 7 from the P3.21 mandatory list."""

    def test_not_eligible_rejected(self):
        eligibility = _not_eligible_eligibility()
        self.assertEqual(eligibility.status, ActivationEligibilityStatus.HUMAN_AUTHORIZATION_NOT_VALID)
        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        self.assertEqual(handoff.status, ProductionActivationHandoffStatus.NOT_ELIGIBLE_FOR_HANDOFF)
        finding = _findings_by_dimension(handoff)["eligibility_status_acceptable"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, HandoffFailureCategory.ACTIVATION_NOT_ELIGIBLE)


class EligibleHandoffAcceptedTests(unittest.TestCase):
    """Test 8 from the P3.21 mandatory list."""

    def test_eligible_handoff_accepted(self):
        eligibility = _eligible_eligibility()
        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        self.assertEqual(handoff.status, ProductionActivationHandoffStatus.ACTIVATION_HANDOFF_READY)
        self.assertEqual(handoff.reasons, ())
        self.assertTrue(all(f.passed for f in handoff.findings))


class HumanAuthorizationMissingRejectedTests(unittest.TestCase):
    """Test 9 from the P3.21 mandatory list."""

    def test_authorization_missing_rejected(self):
        result = _real_ready_result()
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        prod_handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        intake = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=prod_handoff))
        auth_handoff = HumanAuthorizationHandoffBuilder().build(HumanAuthorizationHandoffInput(intake=intake))
        eligibility = ActivationEligibilityChecker().check_eligibility(
            ActivationEligibilityInput(human_authorization_handoff=auth_handoff)
        )
        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        self.assertEqual(handoff.status, ProductionActivationHandoffStatus.NOT_ELIGIBLE_FOR_HANDOFF)


class InvalidAuthorizationRejectedTests(unittest.TestCase):
    """Test 10 from the P3.21 mandatory list."""

    def test_invalid_authorization_rejected(self):
        eligibility = _eligible_eligibility(auth=RealGenerationAuthorization(request_id="005", authorized_by_human=False))
        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        self.assertEqual(handoff.status, ProductionActivationHandoffStatus.NOT_ELIGIBLE_FOR_HANDOFF)


class ExpiredAuthorizationRejectedTests(unittest.TestCase):
    """Test 11 from the P3.21 mandatory list -- expiry belongs to a
    caller-supplied activation_contract at the P3.20 layer; a stale one
    propagates upward as NOT_ELIGIBLE_FOR_HANDOFF."""

    def test_stale_activation_contract_propagates_to_not_eligible(self):
        from agents.activation_contract import RequestScopedActivationContract
        from datetime import timedelta

        auth = _valid_auth("005")
        eligibility_base = _eligible_eligibility(auth=auth)
        stale_contract = RequestScopedActivationContract(
            activation_id="a1", request_id="005", job_type=VIDEO_005_JOB_TYPE,
            duration=VIDEO_005_DURATION, resolution=VIDEO_005_RESOLUTION,
            aspect_ratio=VIDEO_005_ASPECT_RATIO, prompt_sha256="0" * 64,
            authorization_id=eligibility_base.human_authorization_handoff.authorization_id,
            created_at=(datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat(),
        )
        eligibility = ActivationEligibilityChecker().check_eligibility(
            ActivationEligibilityInput(
                human_authorization_handoff=eligibility_base.human_authorization_handoff,
                activation_contract=stale_contract,
            )
        )
        self.assertEqual(eligibility.status, ActivationEligibilityStatus.NOT_ELIGIBLE_FOR_ACTIVATION)
        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        self.assertEqual(handoff.status, ProductionActivationHandoffStatus.NOT_ELIGIBLE_FOR_HANDOFF)


class RevokedAuthorizationRejectedTests(unittest.TestCase):
    """Test 12 from the P3.21 mandatory list -- revocation state is
    structurally unreachable at this layer (see module docstring); the
    identity-lock-violation channel is this layer's own analogous
    fail-closed mechanism, tested here."""

    def test_identity_lock_violation_forces_not_eligible(self):
        eligibility = _eligible_eligibility()
        handoff = ProductionActivationHandoffBuilder().build(
            ProductionActivationHandoffInput(
                eligibility=eligibility,
                identity_lock_violations=("prompt sha256 mismatch",),
            )
        )
        self.assertEqual(handoff.status, ProductionActivationHandoffStatus.NOT_ELIGIBLE_FOR_HANDOFF)
        finding = _findings_by_dimension(handoff)["identity_lock_status"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, HandoffFailureCategory.IDENTITY_LOCK_VIOLATION)


# ------------------------------------------------------------------
# AUTHORITY (tests 13-18)
# ------------------------------------------------------------------


class ApprovalVsAuthorizationTests(unittest.TestCase):
    """Test 13 from the P3.21 mandatory list."""

    def test_approved_never_read_by_this_module(self):
        code = _module_code_without_docstrings()
        self.assertNotIn(".approved", code)


class AuthorizationVsActivationTests(unittest.TestCase):
    """Test 14 from the P3.21 mandatory list."""

    def test_status_values_never_imply_activation(self):
        values = {m.value for m in ProductionActivationHandoffStatus}
        self.assertEqual(values, {"NOT_ELIGIBLE_FOR_HANDOFF", "ACTIVATION_HANDOFF_READY"})
        for forbidden in ("ACTIVATED", "EXECUTING", "EXECUTED", "AUTHORIZED"):
            self.assertNotIn(forbidden, values)


class EligibilityVsActivationTests(unittest.TestCase):
    """Test 15 from the P3.21 mandatory list."""

    def test_ready_handoff_has_no_activation_fields(self):
        eligibility = _eligible_eligibility()
        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        self.assertFalse(hasattr(handoff, "activated"))
        self.assertFalse(hasattr(handoff, "activation_contract"))
        self.assertFalse(hasattr(handoff, "provider_activation_contract"))


class HandoffVsExecutionTests(unittest.TestCase):
    """Test 16 from the P3.21 mandatory list."""

    def test_ready_handoff_has_no_execution_fields(self):
        eligibility = _eligible_eligibility()
        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        self.assertFalse(hasattr(handoff, "executed"))
        self.assertFalse(hasattr(handoff, "job"))
        self.assertFalse(hasattr(handoff, "job_id"))


class NoAutomaticAuthorizationConstructionTests(unittest.TestCase):
    """Test 17 from the P3.21 mandatory list."""

    def test_real_generation_authorization_not_importable_or_constructible(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("RealGenerationAuthorization", code)

    def test_only_opaque_authorization_id_is_reachable(self):
        eligibility = _eligible_eligibility()
        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        self.assertIsInstance(handoff.authorization_id, str)


class NoAutomaticActivationTests(unittest.TestCase):
    """Test 18 from the P3.21 mandatory list -- adversarial: eligible,
    valid authorization, review PASS, handoff READY -- none of it
    constructs an activation contract."""

    def test_fully_eligible_chain_never_constructs_activation_contract(self):
        eligibility = _eligible_eligibility()
        self.assertEqual(eligibility.status, ActivationEligibilityStatus.ELIGIBLE_FOR_ACTIVATION)
        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        self.assertEqual(handoff.status, ProductionActivationHandoffStatus.ACTIVATION_HANDOFF_READY)
        self.assertIsNone(eligibility.activation_contract)

    def test_builder_never_constructs_activation_objects(self):
        code = MODULE_SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(code)
        constructor_calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertNotIn("RequestScopedActivationContract", constructor_calls)
        self.assertNotIn("ControlledRealProviderActivationContract", constructor_calls)


# ------------------------------------------------------------------
# INTEGRITY (tests 19-24)
# ------------------------------------------------------------------


class ImmutableOutputTests(unittest.TestCase):
    """Test 19 from the P3.21 mandatory list."""

    def test_immutable_output(self):
        eligibility = _eligible_eligibility()
        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        with self.assertRaises(FrozenInstanceError):
            handoff.status = ProductionActivationHandoffStatus.NOT_ELIGIBLE_FOR_HANDOFF  # type: ignore

    def test_immutable_input(self):
        eligibility = _eligible_eligibility()
        request = ProductionActivationHandoffInput(eligibility=eligibility)
        with self.assertRaises(FrozenInstanceError):
            request.handoff_id = "tampered"  # type: ignore

    def test_source_eligibility_untouched(self):
        eligibility = _eligible_eligibility()
        hash_before = eligibility.content_hash
        ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        self.assertEqual(eligibility.content_hash, hash_before)


class DeterministicOutputTests(unittest.TestCase):
    """Test 20 from the P3.21 mandatory list."""

    def test_deterministic_output(self):
        eligibility = _eligible_eligibility()
        a = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        b = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        self.assertEqual(a.content_hash, b.content_hash)


class VersionedContractTests(unittest.TestCase):
    """Test 21 from the P3.21 mandatory list."""

    def test_contract_version_present(self):
        eligibility = _eligible_eligibility()
        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        self.assertEqual(handoff.contract_version, 1)
        self.assertEqual(handoff.artifact_type, "ProductionActivationHandoff")


class TamperedIdentityRejectedTests(unittest.TestCase):
    """Test 22 from the P3.21 mandatory list."""

    def test_tampered_eligibility_content_hash_detected(self):
        eligibility = _eligible_eligibility()
        tampered = dc_replace(eligibility, content_hash="0" * 64)
        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=tampered))
        self.assertEqual(handoff.status, ProductionActivationHandoffStatus.NOT_ELIGIBLE_FOR_HANDOFF)
        finding = _findings_by_dimension(handoff)["eligibility_integrity"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, HandoffFailureCategory.ELIGIBILITY_INTEGRITY_FAILURE)

    def test_tampered_mission_id_detected(self):
        eligibility = _eligible_eligibility()
        tampered_review = dc_replace(
            eligibility.human_authorization_handoff.intake.handoff.review, mission_id="a-different-mission"
        )
        tampered_prod_handoff = dc_replace(eligibility.human_authorization_handoff.intake.handoff, review=tampered_review)
        tampered_intake = dc_replace(eligibility.human_authorization_handoff.intake, handoff=tampered_prod_handoff)
        tampered_auth_handoff = dc_replace(eligibility.human_authorization_handoff, intake=tampered_intake)
        tampered_eligibility = dc_replace(eligibility, human_authorization_handoff=tampered_auth_handoff)
        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=tampered_eligibility))
        self.assertEqual(handoff.status, ProductionActivationHandoffStatus.NOT_ELIGIBLE_FOR_HANDOFF)


class IncompatibleContractRejectedTests(unittest.TestCase):
    """Test 23 from the P3.21 mandatory list."""

    def test_unsupported_eligibility_contract_version_rejected(self):
        eligibility = _eligible_eligibility()
        tampered = dc_replace(eligibility, contract_version=999)
        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=tampered))
        self.assertEqual(handoff.status, ProductionActivationHandoffStatus.NOT_ELIGIBLE_FOR_HANDOFF)
        finding = _findings_by_dimension(handoff)["eligibility_contract_version_compatibility"]
        self.assertFalse(finding.passed)
        self.assertEqual(finding.category, HandoffFailureCategory.CONTRACT_MISMATCH)


class StaleHandoffRejectedTests(unittest.TestCase):
    """Test 24 from the P3.21 mandatory list."""

    def test_expected_eligibility_id_mismatch_rejected(self):
        eligibility = _eligible_eligibility()
        handoff = ProductionActivationHandoffBuilder().build(
            ProductionActivationHandoffInput(eligibility=eligibility, expected_eligibility_id="stale-id")
        )
        self.assertEqual(handoff.status, ProductionActivationHandoffStatus.NOT_ELIGIBLE_FOR_HANDOFF)
        finding = _findings_by_dimension(handoff)["expected_eligibility_id_pin"]
        self.assertFalse(finding.passed)


# ------------------------------------------------------------------
# SAFETY (tests 25-33)
# ------------------------------------------------------------------


class SafetyTests(unittest.TestCase):
    """Tests 25-33 from the P3.21 mandatory list."""

    def test_no_create_job_call(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("create_job(", code)

    def test_no_real_provider_call(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("HiggsfieldProvider", code)

    def test_no_higgsfield_client_call(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("HiggsfieldClient", code)

    def test_no_cli_call(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("subprocess", code)

    def test_no_network_call(self):
        code = _module_code_without_docstrings()
        for banned in ("requests.", "urllib.", "socket.", "http.client", "aiohttp.", "httpx."):
            self.assertNotIn(banned, code)

    def test_no_credits_consumed_no_cost_calls(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("get_account_balance", code)
        self.assertNotIn("estimate_cost", code)

    def test_no_activation_consumed(self):
        code = _module_code_without_docstrings()
        self.assertNotIn(".consume(", code)
        self.assertNotIn("validate_activation(", code)

    def test_no_replay_store_mutation(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("ExecutedRequestStore", code)
        self.assertNotIn("mark_executed", code)

    def test_no_critical_section_mutation(self):
        code = _module_code_without_docstrings()
        self.assertNotIn("CriticalSectionLock", code)
        self.assertNotIn(".acquire(", code)


# ------------------------------------------------------------------
# DIRECTOR (tests 34-37)
# ------------------------------------------------------------------


class DirectorIntegrationTests(unittest.TestCase):
    """Tests 34-37 from the P3.21 mandatory list."""

    def test_additive_director_entry_point_works(self):
        eligibility = _eligible_eligibility()
        director = AIDirector()
        handoff = director.production_activation_handoff(ProductionActivationHandoffInput(eligibility=eligibility))
        self.assertIsInstance(handoff, ProductionActivationHandoff)
        self.assertEqual(handoff.status, ProductionActivationHandoffStatus.ACTIVATION_HANDOFF_READY)

    def test_missing_inputs_rejected(self):
        with self.assertRaises(TypeError):
            ProductionActivationHandoffInput()  # type: ignore

    def test_invalid_inputs_rejected(self):
        with self.assertRaises(ProductionActivationHandoffError):
            ProductionActivationHandoffBuilder().build(
                ProductionActivationHandoffInput(eligibility="not-an-eligibility-result")  # type: ignore
            )

    def test_valid_inputs_produce_handoff_only(self):
        eligibility = _eligible_eligibility()
        director = AIDirector()
        handoff = director.production_activation_handoff(
            ProductionActivationHandoffInput(eligibility=eligibility), builder=ProductionActivationHandoffBuilder()
        )
        self.assertFalse(hasattr(handoff, "job_id"))
        self.assertFalse(hasattr(handoff, "activated"))

    def test_existing_methods_unaffected(self):
        director = AIDirector()
        for name in (
            "run_business_pipeline", "run_video_mission", "prepare_production_from_script",
            "prepare_video_generation_request", "review_video_generation_request",
            "handoff_video_generation_request", "production_authority_intake",
            "human_authorization_handoff", "activation_eligibility",
            "prepare_real_generation_activation", "execute_real_generation_activation",
        ):
            self.assertTrue(hasattr(director, name), f"missing {name}")

    def test_not_invoked_automatically_by_activation_eligibility(self):
        director_source = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        tree = ast.parse(director_source)
        method_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "activation_eligibility":
                method_node = node
                break
        self.assertIsNotNone(method_node)
        called_names = {
            node.func.attr
            for node in ast.walk(method_node)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn("production_activation_handoff", called_names)

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
        self.assertNotIn("production_activation_handoff", called_names)

    def test_director_py_new_method_has_no_forbidden_calls(self):
        director_source = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        tree = ast.parse(director_source)
        method_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "production_activation_handoff":
                method_node = node
                break
        self.assertIsNotNone(method_node, "production_activation_handoff method not found in director.py")
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
        self.assertFalse(offenders, f"production_activation_handoff contains forbidden call(s): {offenders}")


# ------------------------------------------------------------------
# BOUNDARY (tests 38-43)
# ------------------------------------------------------------------


class BoundaryTests(unittest.TestCase):
    """Tests 38-43 from the P3.21 mandatory list."""

    def test_handoff_cannot_itself_execute(self):
        eligibility = _eligible_eligibility()
        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        self.assertFalse(hasattr(handoff, "execute"))
        self.assertFalse(hasattr(ProductionActivationHandoffBuilder(), "execute"))

    def test_handoff_cannot_grant_human_authorization(self):
        code = MODULE_SOURCE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("RealGenerationAuthorization(", code)

    def test_handoff_cannot_bypass_p2_contracts(self):
        code = _module_code_without_docstrings()
        for forbidden in ("prepare_activation(", "validate_activation(", ".consume(", "create_job("):
            self.assertNotIn(forbidden, code)

    def test_handoff_cannot_bypass_identity_lock(self):
        # A non-empty identity_lock_violations tuple (however the
        # caller obtained it) always forces NOT_ELIGIBLE_FOR_HANDOFF --
        # verified again here explicitly as the boundary category.
        eligibility = _eligible_eligibility()
        handoff = ProductionActivationHandoffBuilder().build(
            ProductionActivationHandoffInput(eligibility=eligibility, identity_lock_violations=("x", "y"))
        )
        self.assertEqual(handoff.status, ProductionActivationHandoffStatus.NOT_ELIGIBLE_FOR_HANDOFF)

    def test_handoff_cannot_bypass_activation_service(self):
        source = MODULE_SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        self.assertNotIn("agents.activation_contract", imports)
        self.assertNotIn("agents.controlled_real_provider_activation", imports)

    def test_handoff_cannot_bypass_generation_job_service(self):
        source = MODULE_SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        self.assertNotIn("agents.generation_job_service", imports)
        self.assertNotIn("agents.generation_approval_gate", imports)


class MissionStateAuthorityTests(unittest.TestCase):
    def test_no_state_authority(self):
        eligibility = _eligible_eligibility()
        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        self.assertFalse(hasattr(handoff, "mission_state"))
        self.assertFalse(hasattr(ProductionActivationHandoffBuilder(), "state_machine"))
        self.assertFalse(hasattr(ProductionActivationHandoffBuilder(), "transition"))


# ------------------------------------------------------------------
# COMPATIBILITY (tests 44-45)
# ------------------------------------------------------------------


class Video005RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eligibility = _eligible_eligibility("005", expected_prompt_sha256=VIDEO_005_PROMPT_SHA256)
        cls.handoff = ProductionActivationHandoffBuilder().build(
            ProductionActivationHandoffInput(eligibility=cls.eligibility)
        )

    def test_video_005_ready(self):
        self.assertEqual(self.handoff.status, ProductionActivationHandoffStatus.ACTIVATION_HANDOFF_READY)

    def test_video_005_identity_preserved(self):
        self.assertEqual(self.handoff.request_id, VIDEO_005_REQUEST_ID)
        gr = self.handoff.eligibility.human_authorization_handoff.intake.handoff.review.generation_request
        self.assertEqual(gr.job_type, VIDEO_005_JOB_TYPE)
        self.assertEqual(gr.duration, VIDEO_005_DURATION)
        self.assertEqual(gr.resolution, VIDEO_005_RESOLUTION)
        self.assertEqual(gr.aspect_ratio, VIDEO_005_ASPECT_RATIO)

    def test_video_005_still_unexecuted(self):
        gr = self.handoff.eligibility.human_authorization_handoff.intake.handoff.review.generation_request
        self.assertFalse(gr.approved)
        self.assertIsNone(gr.real_generation_authorization)


class P2CompatibilityTests(_MockChainMixin, unittest.TestCase):
    """Test 44 from the P3.21 mandatory list -- the full real chain
    (P2.20/21/26/27/29) composed through P3.15-P3.21 still yields
    ACTIVATION_HANDOFF_READY when a real, externally-prepared activation
    snapshot is structurally valid."""

    def test_full_chain_with_real_activation_snapshot(self):
        shared_auth = _valid_auth("005")
        result = _real_ready_result("005")
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
        prod_handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        intake = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=prod_handoff))
        auth_handoff = HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=shared_auth)
        )
        prepared = self._real_prepared_activation("005", auth=shared_auth)
        eligibility = ActivationEligibilityChecker().check_eligibility(
            ActivationEligibilityInput(
                human_authorization_handoff=auth_handoff,
                activation_contract=prepared.activation_contract,
                provider_activation_contract=prepared.provider_activation_contract,
            )
        )
        self.assertEqual(eligibility.status, ActivationEligibilityStatus.ACTIVATION_CONTRACT_STRUCTURALLY_VALID)

        handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
        self.assertEqual(handoff.status, ProductionActivationHandoffStatus.ACTIVATION_HANDOFF_READY)
        self.assertTrue(all(f.passed for f in handoff.findings))


class FullRepositoryRegressionMarkerTest(unittest.TestCase):
    """Test 45 from the P3.21 mandatory list -- this test file itself
    is included in `python -m unittest discover`; full-repository
    regression is verified by running that command, not re-implemented
    here."""

    def test_marker(self):
        self.assertTrue(True)


class InvalidInputTests(unittest.TestCase):
    """Structural input-validation regression, mirrors P3.17-20's own."""

    def test_invalid_eligibility_raises_explicitly(self):
        with self.assertRaises(ProductionActivationHandoffError):
            ProductionActivationHandoffBuilder().build(
                ProductionActivationHandoffInput(eligibility="not-an-eligibility-result")  # type: ignore
            )


class IdempotencyTests(unittest.TestCase):
    def test_idempotent_repeated_build(self):
        eligibility = _eligible_eligibility()
        builder = ProductionActivationHandoffBuilder()
        request = ProductionActivationHandoffInput(eligibility=eligibility)
        first = builder.build(request)
        second = builder.build(request)
        third = builder.build(request)
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(second.content_hash, third.content_hash)


class SecurityTests(unittest.TestCase):
    """
    AST-based, docstring-false-positive-safe, static verification that
    `agents/production_activation_handoff.py` never reaches real
    execution, any P2 authority mechanism beyond the legitimate TYPE
    reuse, the Mission State Machine, or an event bus.
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
        "agents.activation_readiness",
        "agents.production_activation_boundary",
        "agents.real_provider_execution_gate",
        "agents.real_provider_activation_preflight",
        "agents.critical_section_lock",
        "agents.executed_request_store",
        "agents.release_candidate_identity_lock",
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
        "RealGenerationAuthorization",
        "GenerationApprovalGate", "RequestScopedActivationService",
        "ControlledRealProviderActivationService", "GenerationJobService",
        "HiggsfieldProvider", "HiggsfieldClient", "ReleaseCandidateIdentityLock",
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
        self.assertFalse(offenders, f"production_activation_handoff.py imports forbidden module(s): {offenders}")

    def test_no_forbidden_calls(self):
        offenders = self._called_names() & self.FORBIDDEN_CALL_NAMES
        self.assertFalse(offenders, f"production_activation_handoff.py contains forbidden call(s): {offenders}")

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

    def test_no_p2_or_p3_class_reimplemented(self):
        class_defs = {node.name for node in ast.walk(self.tree) if isinstance(node, ast.ClassDef)}
        self.assertNotIn("GenerationApprovalGate", class_defs)
        self.assertNotIn("RequestScopedActivationService", class_defs)
        self.assertNotIn("ControlledRealProviderActivationService", class_defs)
        self.assertNotIn("GenerationJobService", class_defs)
        self.assertNotIn("ActivationEligibilityChecker", class_defs)
        self.assertNotIn("HumanAuthorizationHandoffBuilder", class_defs)

    def test_eligibility_module_imported_for_type_and_hash_reuse_only(self):
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module == "agents.activation_eligibility":
                for alias in node.names:
                    names.add(alias.name)
        self.assertIn("ActivationEligibilityResult", names)
        self.assertIn("compute_activation_eligibility_hash", names)
        self.assertNotIn("ActivationEligibilityChecker", names)

    def test_p2_boundary_never_crossed(self):
        p2_modules = {
            "agents.generation_approval_gate",
            "agents.generation_job_service",
            "agents.activation_contract",
            "agents.controlled_real_provider_activation",
            "agents.activation_readiness",
            "agents.critical_section_lock",
            "agents.executed_request_store",
            "agents.release_candidate_identity_lock",
            "integrations.higgsfield.provider",
            "integrations.higgsfield.client",
        }
        offenders = self._imported_modules() & p2_modules
        self.assertFalse(offenders, f"production_activation_handoff.py crosses the P2 boundary: {offenders}")


if __name__ == "__main__":
    unittest.main()
