"""
Tests — Controlled Activation Composition (Phase P3.23).

Fully offline: no network, no Higgsfield, no social platform, no OAuth,
no credential of any kind is imported or constructed anywhere in this
file. Every test that exercises `AIDirector.compose_controlled_
activation()` (which delegates to the real, unmodified `prepare_real_
generation_activation()`, Phase P2.29) always injects a `Mock
HiggsfieldProvider`-backed `report_service` -- the same pattern
`tests/test_phase_p2_29_explicit_human_activation_entry_point.py`
already uses -- never the real chain.
"""

import ast
import io
import shutil
import sys
import tempfile
import tokenize as _tokenize
import unittest
from dataclasses import FrozenInstanceError, replace as dc_replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import ActivationRejectedError, RequestScopedActivationService
from agents.activation_eligibility import ActivationEligibilityChecker, ActivationEligibilityInput
from agents.asset_preparation_system import AssetPreparationSystem
from agents.content_agent import ContentAgent, ContentAgentInput
from agents.controlled_activation_composition import (
    ControlledActivationCompositionError,
    ExtractedProductionParameters,
    extract_production_parameters,
    verify_authorization_binding,
    verify_generation_request_consistency,
    verify_handoff_ready,
)
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
    ProductionActivationHandoffBuilder,
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
from director import AIDirector, PreparedRealGenerationActivation
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider

MODULE_SOURCE_PATH = PROJECT_ROOT / "agents" / "controlled_activation_composition.py"

VIDEO_005_REQUEST_ID = "005"
VIDEO_005_JOB_TYPE = "seedance_2_0"
VIDEO_005_DURATION = 15
VIDEO_005_RESOLUTION = "720p"
VIDEO_005_ASPECT_RATIO = "9:16"
VIDEO_005_PROMPT_SHA256 = "1c498617adb4603bcf2fc114a9cb9e8fe2219f09285adbff4d1e6c7a10a669e1"

TITLE = "Pourquoi la discipline vaut plus que le talent."
HOOK = "Le talent impressionne. La discipline construit des empires."
OBJECTIVE = "Créer une vidéo courte, cinématique et motivante."


def _module_code_stripped():
    """Source of agents/controlled_activation_composition.py with every
    docstring AND `#` comment stripped -- so raw-substring boundary
    checks below never false-positive on this module's own prose
    (which legitimately narrates forbidden concepts by name)."""

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

    out_lines = without_docstrings.splitlines(keepends=True)
    for tok in _tokenize.generate_tokens(io.StringIO(without_docstrings).readline):
        if tok.type == _tokenize.COMMENT:
            row = tok.start[0] - 1
            col_start = tok.start[1]
            col_end = tok.end[1]
            line = out_lines[row]
            out_lines[row] = line[:col_start] + line[col_end:]
    return "".join(out_lines)


def _director_method_source(name):
    director_source = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
    tree = ast.parse(director_source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return tree, node
    raise AssertionError(f"{name} not found in director.py")


def _real_video_005_plan():
    planner = VideoPlanner(PROJECT_ROOT)
    return planner.create_zephyr_plan(video_id="005", title=TITLE, hook=HOOK, objective=OBJECTIVE)


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


def _ready_handoff(request_id="005", auth=None, **review_kwargs):
    result = _real_ready_result(request_id=request_id)
    review = PreProductionReviewer().review(
        PreProductionReviewInput(preparation_result=result, **review_kwargs)
    )
    prod_handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
    intake = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=prod_handoff))
    used_auth = auth or _valid_auth(request_id)
    auth_handoff = HumanAuthorizationHandoffBuilder().build(
        HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=used_auth)
    )
    eligibility = ActivationEligibilityChecker().check_eligibility(
        ActivationEligibilityInput(human_authorization_handoff=auth_handoff)
    )
    handoff = ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))
    return handoff, used_auth


def _not_ready_handoff():
    result = _not_ready_result()
    review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
    prod_handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
    intake = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=prod_handoff))
    auth_handoff = HumanAuthorizationHandoffBuilder().build(HumanAuthorizationHandoffInput(intake=intake))
    eligibility = ActivationEligibilityChecker().check_eligibility(
        ActivationEligibilityInput(human_authorization_handoff=auth_handoff)
    )
    return ProductionActivationHandoffBuilder().build(ProductionActivationHandoffInput(eligibility=eligibility))


class _MockChainMixin:
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p3_23_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def _mock_report_service(self, cost_per_job=67.5, available_credits=1000.0, provider=None):
        provider = provider or MockHiggsfieldProvider(cost_per_job=cost_per_job, available_credits=available_credits)
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
        return FinalReportService(provider, gate, job_service=job_service), gate


# ------------------------------------------------------------------
# HANDOFF (tests 1-4)
# ------------------------------------------------------------------


class ValidHandoffAcceptedTests(_MockChainMixin, unittest.TestCase):
    def test_valid_handoff_composes(self):
        handoff, auth = _ready_handoff()
        report_service, _ = self._mock_report_service()
        director = AIDirector()
        prepared = director.compose_controlled_activation(
            handoff=handoff, real_generation_authorization=auth,
            title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True,
            report_service=report_service,
        )
        self.assertIsInstance(prepared, PreparedRealGenerationActivation)
        self.assertEqual(prepared.request.request_id, "005")


class NonReadyHandoffRejectedTests(unittest.TestCase):
    def test_not_ready_handoff_rejected(self):
        handoff = _not_ready_handoff()
        self.assertEqual(handoff.status, ProductionActivationHandoffStatus.NOT_ELIGIBLE_FOR_HANDOFF)
        with self.assertRaises(ControlledActivationCompositionError):
            verify_handoff_ready(handoff)


class MalformedHandoffRejectedTests(unittest.TestCase):
    def test_non_handoff_object_rejected(self):
        with self.assertRaises(ControlledActivationCompositionError):
            verify_handoff_ready("not-a-handoff")  # type: ignore

    def test_tampered_content_hash_rejected(self):
        handoff, _ = _ready_handoff()
        tampered = dc_replace(handoff, content_hash="0" * 64)
        with self.assertRaises(ControlledActivationCompositionError):
            verify_handoff_ready(tampered)


class RequestIdentityPreservedTests(_MockChainMixin, unittest.TestCase):
    def test_request_identity_preserved(self):
        handoff, auth = _ready_handoff(request_id="005")
        report_service, _ = self._mock_report_service()
        director = AIDirector()
        prepared = director.compose_controlled_activation(
            handoff=handoff, real_generation_authorization=auth,
            title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True,
            report_service=report_service,
        )
        self.assertEqual(prepared.request.request_id, handoff.request_id)


# ------------------------------------------------------------------
# AUTHORIZATION (tests 5-12)
# ------------------------------------------------------------------


class ExplicitAuthorizationRequiredTests(unittest.TestCase):
    def test_authorization_is_a_required_parameter(self):
        import inspect

        sig = inspect.signature(AIDirector.compose_controlled_activation)
        self.assertIs(sig.parameters["real_generation_authorization"].default, inspect.Parameter.empty)


class NoAutomaticAuthorizationConstructionTests(unittest.TestCase):
    def test_module_never_constructs_authorization(self):
        code = MODULE_SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(code)
        constructor_calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertNotIn("RealGenerationAuthorization", constructor_calls)

    def test_director_method_never_constructs_authorization(self):
        tree, node = _director_method_source("compose_controlled_activation")
        constructor_calls = {
            n.func.id
            for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        self.assertNotIn("RealGenerationAuthorization", constructor_calls)


class MatchingAuthorizationIdAcceptedTests(unittest.TestCase):
    def test_matching_authorization_id_accepted(self):
        handoff, auth = _ready_handoff()
        verify_authorization_binding(handoff, auth)  # no raise


class MismatchedAuthorizationIdRejectedTests(unittest.TestCase):
    def test_different_authorization_object_rejected(self):
        handoff, _ = _ready_handoff()
        other_auth = RealGenerationAuthorization(request_id="005", authorized_by_human=True)
        with self.assertRaises(ControlledActivationCompositionError):
            verify_authorization_binding(handoff, other_auth)


class MissingAuthorizationRejectedTests(unittest.TestCase):
    def test_none_authorization_rejected(self):
        handoff, _ = _ready_handoff()
        with self.assertRaises(ControlledActivationCompositionError):
            verify_authorization_binding(handoff, None)

    def test_wrong_type_authorization_rejected(self):
        handoff, _ = _ready_handoff()
        with self.assertRaises(ControlledActivationCompositionError):
            verify_authorization_binding(handoff, {"request_id": "005"})


class ExpiredAuthorizationTests(unittest.TestCase):
    """RealGenerationAuthorization carries no expiry field -- confirmed
    structurally; expiration is not applicable at this layer (see
    module docstring 'SCOPE BOUNDARY'). Downstream contract expiry
    (P2.21/P2.26) is exercised, untouched, inside the delegated call."""

    def test_real_generation_authorization_has_no_expiry_field(self):
        auth = _valid_auth("005")
        self.assertFalse(hasattr(auth, "expires_at"))
        self.assertFalse(hasattr(auth, "expiry"))
        self.assertFalse(hasattr(auth, "max_age_seconds"))


class RevokedAuthorizationTests(unittest.TestCase):
    """RealGenerationAuthorization carries no revoke mechanism --
    confirmed structurally; revocation is not applicable at this layer.
    Downstream contract revocation (P2.26) is exercised, untouched,
    inside the delegated call."""

    def test_real_generation_authorization_has_no_revoke_method(self):
        auth = _valid_auth("005")
        self.assertFalse(hasattr(auth, "revoke"))
        self.assertFalse(hasattr(auth, "revoked"))


class AlreadyConsumedAuthorizationTests(_MockChainMixin, unittest.TestCase):
    """Interpreted as: the underlying request was already marked
    executed. P2's own fresh Gate check rejects this via
    ActivationRejectedError, propagated unmodified -- never
    reinterpreted by this module."""

    def test_already_executed_request_rejected_by_delegated_p2_call(self):
        handoff, auth = _ready_handoff("005")
        report_service, gate = self._mock_report_service()
        gate.mark_executed("005")

        director = AIDirector()
        with self.assertRaises(ActivationRejectedError):
            director.compose_controlled_activation(
                handoff=handoff, real_generation_authorization=auth,
                title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True,
                report_service=report_service,
            )


# ------------------------------------------------------------------
# IDENTITY (tests 13-17)
# ------------------------------------------------------------------


class RequestIdMismatchRejectedTests(unittest.TestCase):
    def test_request_id_mismatch_between_authorization_and_handoff(self):
        handoff, _ = _ready_handoff("005")
        wrong_request_auth = RealGenerationAuthorization(
            request_id="999", authorized_by_human=True, authorization_id=handoff.authorization_id
        )
        with self.assertRaises(ControlledActivationCompositionError):
            verify_authorization_binding(handoff, wrong_request_auth)


class MissionIdMismatchTests(unittest.TestCase):
    """mission_id is not a GenerationRequest field and is not accepted
    by prepare_real_generation_activation() -- consistency is verified
    one layer down (P3.21's own identity_chain_consistency), re-checked
    here defensively via the handoff's own integrity hash."""

    def test_tampered_mission_id_detected_via_handoff_integrity(self):
        handoff, _ = _ready_handoff()
        tampered_review = dc_replace(
            handoff.eligibility.human_authorization_handoff.intake.handoff.review, mission_id="a-different-mission"
        )
        tampered_prod_handoff = dc_replace(
            handoff.eligibility.human_authorization_handoff.intake.handoff, review=tampered_review
        )
        tampered_intake = dc_replace(
            handoff.eligibility.human_authorization_handoff.intake, handoff=tampered_prod_handoff
        )
        tampered_auth_handoff = dc_replace(handoff.eligibility.human_authorization_handoff, intake=tampered_intake)
        tampered_eligibility = dc_replace(handoff.eligibility, human_authorization_handoff=tampered_auth_handoff)
        tampered_handoff = dc_replace(handoff, eligibility=tampered_eligibility)
        with self.assertRaises(ControlledActivationCompositionError):
            verify_handoff_ready(tampered_handoff)


class GenerationRequestMismatchRejectedTests(_MockChainMixin, unittest.TestCase):
    def test_tampered_job_type_in_handoff_detected_post_delegation(self):
        handoff, auth = _ready_handoff("005")
        reviewed = handoff.eligibility.human_authorization_handoff.intake.handoff.review.generation_request
        tampered = dc_replace(reviewed, job_type="a_different_model")
        with self.assertRaises(ControlledActivationCompositionError):
            verify_generation_request_consistency(tampered, reviewed)


class PromptIdentityMismatchRejectedTests(unittest.TestCase):
    def test_prompt_mismatch_rejected(self):
        handoff, _ = _ready_handoff()
        reviewed = handoff.eligibility.human_authorization_handoff.intake.handoff.review.generation_request
        freshly_built = dc_replace(reviewed, prompt="a completely different prompt")
        with self.assertRaises(ControlledActivationCompositionError):
            verify_generation_request_consistency(freshly_built, reviewed)


class AssetIdentityMismatchRejectedTests(unittest.TestCase):
    def test_start_image_sha_mismatch_rejected(self):
        from integrations.higgsfield.types import MediaReference

        handoff, _ = _ready_handoff()
        reviewed = handoff.eligibility.human_authorization_handoff.intake.handoff.review.generation_request
        foreign_ref = MediaReference(role="master_avatar", source="nowhere.png", sha256="f" * 64)
        freshly_built = dc_replace(reviewed, start_image=foreign_ref)
        with self.assertRaises(ControlledActivationCompositionError):
            verify_generation_request_consistency(freshly_built, reviewed)

    def test_matching_generation_request_passes(self):
        handoff, _ = _ready_handoff()
        reviewed = handoff.eligibility.human_authorization_handoff.intake.handoff.review.generation_request
        verify_generation_request_consistency(reviewed, reviewed)  # identical object, no raise


# ------------------------------------------------------------------
# PRODUCTION PARAMETERS (tests 18-24)
# ------------------------------------------------------------------


class ProductionParameterExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.handoff, _ = _ready_handoff("005", expected_prompt_sha256=VIDEO_005_PROMPT_SHA256)
        cls.params = extract_production_parameters(cls.handoff)

    def test_model_preserved(self):
        self.assertEqual(self.params.job_type, VIDEO_005_JOB_TYPE)

    def test_duration_preserved(self):
        self.assertEqual(self.params.duration, VIDEO_005_DURATION)

    def test_resolution_preserved_via_cross_check(self):
        # resolution is NOT a call argument to prepare_real_generation_
        # activation() -- it is verified post-hoc instead (see module
        # docstring). Confirmed reachable and correct on the reviewed
        # request itself.
        reviewed = self.handoff.eligibility.human_authorization_handoff.intake.handoff.review.generation_request
        self.assertEqual(reviewed.resolution, VIDEO_005_RESOLUTION)

    def test_aspect_ratio_preserved_via_cross_check(self):
        reviewed = self.handoff.eligibility.human_authorization_handoff.intake.handoff.review.generation_request
        self.assertEqual(reviewed.aspect_ratio, VIDEO_005_ASPECT_RATIO)

    def test_prompt_preserved_via_cross_check(self):
        reviewed = self.handoff.eligibility.human_authorization_handoff.intake.handoff.review.generation_request
        import hashlib

        self.assertEqual(hashlib.sha256(reviewed.prompt.encode("utf-8")).hexdigest(), VIDEO_005_PROMPT_SHA256)

    def test_assets_preserved(self):
        reviewed = self.handoff.eligibility.human_authorization_handoff.intake.handoff.review.generation_request
        self.assertIsNotNone(reviewed.start_image)
        self.assertTrue(any(ref.role == "face_reference" for ref in reviewed.image_references))

    def test_asset_hashes_preserved(self):
        reviewed = self.handoff.eligibility.human_authorization_handoff.intake.handoff.review.generation_request
        self.assertIsNotNone(reviewed.start_image.sha256)

    def test_extracted_parameters_shape(self):
        self.assertIsInstance(self.params, ExtractedProductionParameters)
        self.assertEqual(self.params.request_id, "005")


# ------------------------------------------------------------------
# DELEGATION (tests 25-28)
# ------------------------------------------------------------------


class DelegationTests(_MockChainMixin, unittest.TestCase):
    def test_prepare_real_generation_activation_called_exactly_once(self):
        handoff, auth = _ready_handoff()
        report_service, _ = self._mock_report_service()
        director = AIDirector()

        call_count = {"n": 0}
        original = AIDirector.prepare_real_generation_activation

        def counting_wrapper(self, *args, **kwargs):
            call_count["n"] += 1
            return original(self, *args, **kwargs)

        director.prepare_real_generation_activation = counting_wrapper.__get__(director, AIDirector)
        director.compose_controlled_activation(
            handoff=handoff, real_generation_authorization=auth,
            title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True,
            report_service=report_service,
        )
        self.assertEqual(call_count["n"], 1)

    def test_correct_parameters_delegated(self):
        handoff, auth = _ready_handoff()
        report_service, _ = self._mock_report_service()
        director = AIDirector()
        prepared = director.compose_controlled_activation(
            handoff=handoff, real_generation_authorization=auth,
            title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True,
            report_service=report_service,
        )
        self.assertEqual(prepared.request.job_type, VIDEO_005_JOB_TYPE)
        self.assertEqual(prepared.request.duration, VIDEO_005_DURATION)

    def test_no_v2_service_created(self):
        code = MODULE_SOURCE_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "ActivationContractV2", "ControlledActivationServiceV2", "ProviderActivationV2",
            "GenerationJobServiceV2", "HumanAuthorizationV2", "class GenerationApprovalGate",
            "class RequestScopedActivationService", "class ControlledRealProviderActivationService",
            "class GenerationJobService",
        ):
            self.assertNotIn(forbidden, code)

    def test_no_p2_contract_bypass_activation_service_not_imported(self):
        source = MODULE_SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        forbidden = {
            "agents.activation_contract", "agents.controlled_real_provider_activation",
            "agents.generation_job_service", "agents.generation_approval_gate.GenerationApprovalGate",
            "agents.critical_section_lock", "agents.executed_request_store",
            "agents.release_candidate_identity_lock",
        }
        offenders = imports & forbidden
        self.assertFalse(offenders, f"unexpected import(s): {offenders}")
        self.assertIn("agents.generation_approval_gate", imports)  # type-only, verified elsewhere


# ------------------------------------------------------------------
# EXECUTION BOUNDARY (tests 29-35)
# ------------------------------------------------------------------


class ExecutionBoundaryTests(unittest.TestCase):
    def test_execute_real_generation_activation_not_called(self):
        code = _module_code_stripped()
        self.assertNotIn("execute_real_generation_activation(", code)

    def test_generation_job_service_execute_not_called(self):
        code = _module_code_stripped()
        self.assertNotIn("GenerationJobService", code)
        self.assertNotIn(".execute(", code)

    def test_create_job_not_called(self):
        code = _module_code_stripped()
        self.assertNotIn("create_job(", code)

    def test_provider_not_referenced(self):
        code = _module_code_stripped()
        self.assertNotIn("HiggsfieldProvider", code)

    def test_client_not_referenced(self):
        code = _module_code_stripped()
        self.assertNotIn("HiggsfieldClient", code)

    def test_no_cli_reference(self):
        code = _module_code_stripped()
        self.assertNotIn("subprocess", code)

    def test_no_network_reference(self):
        code = _module_code_stripped()
        for banned in ("requests.", "urllib.", "socket.", "aiohttp.", "httpx."):
            self.assertNotIn(banned, code)

    def test_director_method_never_calls_execute_or_create_job(self):
        tree, node = _director_method_source("compose_controlled_activation")
        called_names = {
            n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
            for n in ast.walk(node)
            if isinstance(n, ast.Call)
        }
        offenders = called_names & {"execute", "execute_real_generation_activation", "create_job"}
        self.assertFalse(offenders, f"forbidden call(s) in compose_controlled_activation: {offenders}")


# ------------------------------------------------------------------
# SAFETY (tests 36-40)
# ------------------------------------------------------------------


class SafetyTests(unittest.TestCase):
    def test_no_replay_store_reference(self):
        code = _module_code_stripped()
        self.assertNotIn("ExecutedRequestStore", code)
        self.assertNotIn("mark_executed", code)

    def test_no_execution_mark(self):
        code = _module_code_stripped()
        self.assertNotIn("mark_executed(", code)
        self.assertNotIn("mark_unknown(", code)

    def test_no_critical_section_bypass(self):
        code = _module_code_stripped()
        self.assertNotIn("CriticalSectionLock", code)
        self.assertNotIn(".acquire(", code)

    def test_no_automatic_activation(self):
        code = _module_code_stripped()
        self.assertNotIn("prepare_activation(", code)
        self.assertNotIn(".consume(", code)

    def test_no_automatic_human_authorization(self):
        code = _module_code_stripped()
        self.assertNotIn("RealGenerationAuthorization(", code)


# ------------------------------------------------------------------
# DIRECTOR (tests 41-43)
# ------------------------------------------------------------------


class DirectorIntegrationTests(_MockChainMixin, unittest.TestCase):
    def test_additive_director_entry_point_works(self):
        director = AIDirector()
        self.assertTrue(hasattr(director, "compose_controlled_activation"))

    def test_invalid_input_rejected(self):
        director = AIDirector()
        with self.assertRaises(ControlledActivationCompositionError):
            director.compose_controlled_activation(
                handoff="not-a-handoff",  # type: ignore
                real_generation_authorization=_valid_auth("005"),
                title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True,
            )

    def test_valid_composition_returns_existing_p2_preparation_object(self):
        handoff, auth = _ready_handoff()
        report_service, _ = self._mock_report_service()
        director = AIDirector()
        prepared = director.compose_controlled_activation(
            handoff=handoff, real_generation_authorization=auth,
            title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True,
            report_service=report_service,
        )
        self.assertIs(type(prepared), PreparedRealGenerationActivation)

    def test_existing_methods_unaffected(self):
        director = AIDirector()
        for name in (
            "run_business_pipeline", "run_video_mission", "prepare_video_generation_request",
            "review_video_generation_request", "handoff_video_generation_request",
            "production_authority_intake", "human_authorization_handoff", "activation_eligibility",
            "production_activation_handoff", "prepare_real_generation_activation",
            "execute_real_generation_activation",
        ):
            self.assertTrue(hasattr(director, name), f"missing {name}")

    def test_not_invoked_automatically_by_production_activation_handoff(self):
        tree, node = _director_method_source("production_activation_handoff")
        called_names = {
            n.func.attr for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        self.assertNotIn("compose_controlled_activation", called_names)

    def test_run_video_mission_never_calls_new_method(self):
        tree, node = _director_method_source("run_video_mission")
        called_names = {
            n.func.attr for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        self.assertNotIn("compose_controlled_activation", called_names)


# ------------------------------------------------------------------
# DETERMINISM / INTEGRITY (tests 44-48)
# ------------------------------------------------------------------


class DeterminismIntegrityTests(_MockChainMixin, unittest.TestCase):
    def test_deterministic_result_fields(self):
        handoff, auth = _ready_handoff()
        report_service_a, _ = self._mock_report_service()
        report_service_b, _ = self._mock_report_service()
        director = AIDirector()
        prepared_a = director.compose_controlled_activation(
            handoff=handoff, real_generation_authorization=auth,
            title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True, report_service=report_service_a,
        )
        prepared_b = director.compose_controlled_activation(
            handoff=handoff, real_generation_authorization=auth,
            title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True, report_service=report_service_b,
        )
        self.assertEqual(prepared_a.request.prompt, prepared_b.request.prompt)
        self.assertEqual(prepared_a.request.job_type, prepared_b.request.job_type)

    def test_repeated_composition_does_not_consume_activation(self):
        # Each call prepares a FRESH P2.21/P2.26 contract pair (never
        # reused/cached) -- repeated composition against separate Mock
        # chains must succeed each time, proving no shared consumed
        # state leaks between calls.
        handoff, auth = _ready_handoff()
        director = AIDirector()
        for _ in range(3):
            report_service, _ = self._mock_report_service()
            prepared = director.compose_controlled_activation(
                handoff=handoff, real_generation_authorization=auth,
                title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True, report_service=report_service,
            )
            self.assertIsNotNone(prepared.activation_contract)

    def test_result_preserves_provenance(self):
        handoff, auth = _ready_handoff()
        report_service, _ = self._mock_report_service()
        director = AIDirector()
        prepared = director.compose_controlled_activation(
            handoff=handoff, real_generation_authorization=auth,
            title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True, report_service=report_service,
        )
        self.assertEqual(prepared.activation_contract.request_id, handoff.request_id)
        self.assertEqual(prepared.activation_contract.authorization_id, handoff.authorization_id)

    def test_result_remains_request_scoped(self):
        handoff, auth = _ready_handoff()
        report_service, _ = self._mock_report_service()
        director = AIDirector()
        prepared = director.compose_controlled_activation(
            handoff=handoff, real_generation_authorization=auth,
            title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True, report_service=report_service,
        )
        self.assertEqual(prepared.provider_activation_contract.request_id, handoff.request_id)

    def test_result_cannot_itself_execute(self):
        handoff, auth = _ready_handoff()
        report_service, _ = self._mock_report_service()
        director = AIDirector()
        prepared = director.compose_controlled_activation(
            handoff=handoff, real_generation_authorization=auth,
            title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True, report_service=report_service,
        )
        self.assertFalse(hasattr(prepared, "execute"))
        self.assertFalse(hasattr(prepared, "run"))


# ------------------------------------------------------------------
# COMPATIBILITY (tests 49-51)
# ------------------------------------------------------------------


class CompatibilityTests(unittest.TestCase):
    def test_p3_20_suite_still_green(self):
        import subprocess

        result = subprocess.run(
            [sys.executable, "-m", "unittest", "tests.test_activation_eligibility", "-q"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_p3_21_suite_still_green(self):
        import subprocess

        result = subprocess.run(
            [sys.executable, "-m", "unittest", "tests.test_production_activation_handoff", "-q"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class Video005EndToEndTests(_MockChainMixin, unittest.TestCase):
    def test_full_chain_composition_ready(self):
        handoff, auth = _ready_handoff("005", expected_prompt_sha256=VIDEO_005_PROMPT_SHA256)
        self.assertEqual(handoff.status, ProductionActivationHandoffStatus.ACTIVATION_HANDOFF_READY)
        report_service, _ = self._mock_report_service()
        director = AIDirector()
        prepared = director.compose_controlled_activation(
            handoff=handoff, real_generation_authorization=auth,
            title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True, report_service=report_service,
        )
        self.assertEqual(prepared.request.request_id, VIDEO_005_REQUEST_ID)
        self.assertEqual(prepared.request.job_type, VIDEO_005_JOB_TYPE)
        self.assertEqual(prepared.request.duration, VIDEO_005_DURATION)
        self.assertEqual(prepared.request.resolution, VIDEO_005_RESOLUTION)
        self.assertEqual(prepared.request.aspect_ratio, VIDEO_005_ASPECT_RATIO)
        # approved=True was explicitly passed by this test (technical/
        # budget consent); it is a SEPARATE axis from human authorization
        # -- both were supplied here, both are preserved independently.
        self.assertTrue(prepared.request.approved)
        self.assertIs(prepared.request.real_generation_authorization, auth)


# ------------------------------------------------------------------
# IMMUTABILITY
# ------------------------------------------------------------------


class ImmutabilityTests(unittest.TestCase):
    def test_extracted_parameters_immutable(self):
        handoff, _ = _ready_handoff()
        params = extract_production_parameters(handoff)
        with self.assertRaises(FrozenInstanceError):
            params.job_type = "tampered"  # type: ignore

    def test_source_handoff_untouched(self):
        handoff, _ = _ready_handoff()
        hash_before = handoff.content_hash
        verify_handoff_ready(handoff)
        self.assertEqual(handoff.content_hash, hash_before)


class SecurityTests(unittest.TestCase):
    """
    AST-based, docstring/comment-false-positive-safe, static
    verification that `agents/controlled_activation_composition.py`
    never reaches real execution, any P2 authority mechanism beyond
    the legitimate TYPE reuse, the Mission State Machine, or an event
    bus.
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

    def test_no_forbidden_module_imports(self):
        offenders = self._imported_modules() & self.FORBIDDEN_MODULES
        self.assertFalse(offenders, f"controlled_activation_composition.py imports forbidden module(s): {offenders}")

    def test_no_forbidden_calls(self):
        offenders = self._called_names() & self.FORBIDDEN_CALL_NAMES
        self.assertFalse(offenders, f"controlled_activation_composition.py contains forbidden call(s): {offenders}")

    def test_real_generation_authorization_referenced_but_never_constructed(self):
        names_referenced = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name):
                names_referenced.add(node.id)
        self.assertIn("RealGenerationAuthorization", names_referenced)
        self.assertNotIn("RealGenerationAuthorization", self._called_names())

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
        self.assertNotIn("ProductionActivationHandoffBuilder", class_defs)

    def test_p2_boundary_never_crossed(self):
        p2_modules = {
            "agents.generation_approval_gate.GenerationApprovalGate",
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
        self.assertFalse(offenders, f"controlled_activation_composition.py crosses the P2 boundary: {offenders}")


if __name__ == "__main__":
    unittest.main()
