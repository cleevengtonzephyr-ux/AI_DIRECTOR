"""
Tests -- Mission Traceability Integration Audit (Phase P3.35).

Confirms, with executable evidence rather than re-assertion, that the
mission_id mechanism introduced in P3.34 (tests/test_mission_identity_
contract.py) is correctly integrated end-to-end across the REAL chain:

    Strategy -> Content (ScriptArtifact) -> ScriptProductionBridge
    -> VideoProductionPreparation -> PreProductionReview
    -> ProductionReadinessHandoff -> ProductionAuthorityIntake
    -> HumanAuthorizationHandoff -> ActivationEligibility
    -> ProductionActivationHandoff -> ControlledActivationComposition
    -> GenerationRequest -> FinalReport

Fully offline: no network, no Higgsfield CLI, always a
MockHiggsfieldProvider-backed report_service -- same discipline as
tests/test_mission_identity_contract.py and tests/test_controlled_
activation_composition.py, whose fixture-building helpers this file's
own helpers mirror.
"""

import ast
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import RequestScopedActivationService
from agents.activation_eligibility import ActivationEligibilityChecker, ActivationEligibilityInput
from agents.asset_preparation_system import AssetPreparationSystem
from agents.content_agent import ContentAgent, ContentAgentInput
from agents.controlled_activation_composition import ControlledActivationCompositionError
from agents.controlled_real_provider_activation import ControlledRealProviderActivationService
from agents.critical_section_lock import FileCriticalSectionLock
from agents.final_report_service import FinalReportService
from agents.generation_approval_gate import GenerationApprovalGate, RealGenerationAuthorization
from agents.generation_job_service import GenerationJobService
from agents.human_authorization_handoff import HumanAuthorizationHandoffBuilder, HumanAuthorizationHandoffInput
from agents.planner import VideoPlanner
from agents.pre_production_review import PreProductionReviewInput, PreProductionReviewer
from agents.production_activation_handoff import ProductionActivationHandoffBuilder, ProductionActivationHandoffInput
from agents.production_authority_intake import ProductionAuthorityIntake, ProductionAuthorityIntakeInput
from agents.production_readiness_handoff import ProductionReadinessHandoffBuilder, ProductionReadinessHandoffInput
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.release_candidate_identity_lock import ReleaseCandidateIdentityLock, VIDEO_005_RELEASE_CANDIDATE
from agents.script_production_bridge import ProductionPreparationInput
from agents.strategy_agent import StrategyAgent, StrategyAgentInput
from agents.video_production_preparation import VideoProductionPreparation, VideoProductionPreparationInput
from director import AIDirector
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider

TITLE = "Pourquoi la discipline vaut plus que le talent."
HOOK = "Le talent impressionne. La discipline construit des empires."
OBJECTIVE = "Créer une vidéo courte, cinématique et motivante."

# Phase P3.35 Section 9's exact component list, plus HiggsfieldProvider
# (§9 names it explicitly, unlike P3.34's own narrower check).
P2_AUTHORITY_CORE_FILES = (
    "agents/generation_approval_gate.py",        # GenerationApprovalGate
    "agents/generation_job_service.py",          # GenerationJobService
    "agents/activation_contract.py",             # RequestScopedActivationService
    "agents/controlled_real_provider_activation.py",  # ControlledRealProviderActivationService
    "integrations/higgsfield/provider.py",       # HiggsfieldProvider
    "agents/critical_section_lock.py",           # CriticalSectionLock
    "agents/executed_request_store.py",          # ExecutedRequestStore
    "agents/release_candidate_identity_lock.py",  # Identity Lock
)


def _real_video_005_plan():
    planner = VideoPlanner(PROJECT_ROOT)
    return planner.create_zephyr_plan(video_id="005", title=TITLE, hook=HOOK, objective=OBJECTIVE)


def _real_script_artifact(mission_id: str):
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
    return strategy, content.script_artifact


def _valid_auth(request_id="005"):
    return RealGenerationAuthorization(request_id=request_id, authorized_by_human=True)


def _full_chain(mission_id: str, request_id="005", auth=None):
    """Builds every intermediate object of the real chain (Section 3)
    and returns them all, never just the final handoff -- so tests can
    assert mission_id/request_id at EVERY hop, not just the endpoints."""

    strategy, script = _real_script_artifact(mission_id)
    plan = _real_video_005_plan()
    pa = PromptAssemblySystem(PROJECT_ROOT)
    assets = AssetPreparationSystem(PROJECT_ROOT)
    integration = VideoProductionPreparation(prompt_assembly=pa, asset_preparation=assets)
    prep_result = integration.prepare(
        VideoProductionPreparationInput(
            production_input=ProductionPreparationInput(
                mission_id=mission_id, script_artifact=script, video_id="005"
            ),
            video_plan=plan,
            request_id=request_id,
        )
    )
    review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=prep_result))
    readiness_handoff = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
    intake = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=readiness_handoff))
    used_auth = auth or _valid_auth(request_id)
    auth_handoff = HumanAuthorizationHandoffBuilder().build(
        HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=used_auth)
    )
    eligibility = ActivationEligibilityChecker().check_eligibility(
        ActivationEligibilityInput(human_authorization_handoff=auth_handoff)
    )
    activation_handoff = ProductionActivationHandoffBuilder().build(
        ProductionActivationHandoffInput(eligibility=eligibility)
    )
    return {
        "strategy_artifact": strategy.strategy_artifact,
        "script_artifact": script,
        "prep_result": prep_result,
        "review": review,
        "readiness_handoff": readiness_handoff,
        "intake": intake,
        "auth_handoff": auth_handoff,
        "eligibility": eligibility,
        "activation_handoff": activation_handoff,
        "auth": used_auth,
    }


class _MockChainMixin:
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p3_35_"))
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
# 1. FULL MISSION TRACE -- mission_id asserted at EVERY hop
# ------------------------------------------------------------------


class FullMissionTraceTests(_MockChainMixin, unittest.TestCase):
    def test_mission_id_identical_at_every_hop_of_the_real_chain(self):
        chain = _full_chain(mission_id="mission-trace-005")

        self.assertEqual(chain["strategy_artifact"].mission_id, "mission-trace-005")
        self.assertEqual(chain["script_artifact"].mission_id, "mission-trace-005")
        self.assertEqual(chain["prep_result"].mission_id, "mission-trace-005")
        self.assertEqual(chain["prep_result"].production_preparation.mission_id, "mission-trace-005")
        self.assertEqual(
            chain["prep_result"].production_preparation.script_artifact.mission_id, "mission-trace-005"
        )
        self.assertEqual(chain["review"].mission_id, "mission-trace-005")
        self.assertEqual(chain["review"].production_preparation.mission_id, "mission-trace-005")
        self.assertEqual(chain["readiness_handoff"].mission_id, "mission-trace-005")
        self.assertEqual(chain["intake"].mission_id, "mission-trace-005")
        self.assertEqual(chain["auth_handoff"].mission_id, "mission-trace-005")
        self.assertEqual(chain["eligibility"].mission_id, "mission-trace-005")
        self.assertEqual(chain["activation_handoff"].mission_id, "mission-trace-005")

        report_service, _ = self._mock_report_service()
        director = AIDirector()
        prepared = director.compose_controlled_activation(
            handoff=chain["activation_handoff"], real_generation_authorization=chain["auth"],
            title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True,
            report_service=report_service,
        )
        self.assertEqual(prepared.mission_id, "mission-trace-005")
        report = director.execute_real_generation_activation(prepared, report_service=report_service)
        self.assertEqual(report.mission_id, "mission-trace-005")

        # request_id trace, same chain, in parallel (Section 7 report
        # requirement): identical at every hop that carries it, and
        # ALWAYS distinct from mission_id.
        self.assertEqual(chain["review"].request_id, "005")
        self.assertEqual(chain["readiness_handoff"].request_id, "005")
        self.assertEqual(chain["intake"].request_id, "005")
        self.assertEqual(chain["auth_handoff"].request_id, "005")
        self.assertEqual(chain["eligibility"].request_id, "005")
        self.assertEqual(chain["activation_handoff"].request_id, "005")
        self.assertEqual(prepared.request.request_id, "005")
        self.assertEqual(report.request_id, "005")
        self.assertNotEqual(report.mission_id, report.request_id)

    def test_trace_is_deterministic_across_two_independent_runs(self):
        """Same mission_id/request_id in, same mission_id/request_id
        out -- rebuilding the chain twice from scratch must not
        introduce drift or randomness anywhere in the trace."""
        chain_1 = _full_chain(mission_id="mission-deterministic")
        chain_2 = _full_chain(mission_id="mission-deterministic")
        for key in ("review", "readiness_handoff", "intake", "auth_handoff", "eligibility", "activation_handoff"):
            self.assertEqual(chain_1[key].mission_id, chain_2[key].mission_id)
            self.assertEqual(chain_1[key].request_id, chain_2[key].request_id)


# ------------------------------------------------------------------
# 2. AUTHORITY ISOLATION -- P3.35's own component list (Section 9),
#    including HiggsfieldProvider (not explicitly named in P3.34's).
# ------------------------------------------------------------------


class AuthorityIsolationTests(unittest.TestCase):
    def test_no_p2_authority_core_file_references_mission_id(self):
        """Every reference found here would need to be classified
        ALLOWED OBSERVABILITY or FORBIDDEN AUTHORITY USE per Section 9
        -- there are none to classify."""
        offenders = {}
        for relative_path in P2_AUTHORITY_CORE_FILES:
            source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
            if "mission_id" in source:
                offenders[relative_path] = source.count("mission_id")
        self.assertFalse(offenders, f"P2 Authority Core file(s) reference mission_id: {offenders}")

    def test_generation_approval_gate_evaluate_signature_has_no_mission_id_parameter(self):
        import inspect

        from agents.generation_approval_gate import GenerationApprovalGate

        sig = inspect.signature(GenerationApprovalGate.evaluate)
        self.assertNotIn("mission_id", sig.parameters)

    def test_generation_job_service_execute_signature_has_no_mission_id_parameter(self):
        import inspect

        from agents.generation_job_service import GenerationJobService

        sig = inspect.signature(GenerationJobService.execute)
        self.assertNotIn("mission_id", sig.parameters)


# ------------------------------------------------------------------
# 3. CROSS-REQUEST / CROSS-MISSION GRID (Section 10: A+A, A+B, B+A, B+B)
# ------------------------------------------------------------------


class CrossRequestCrossMissionGridTests(_MockChainMixin, unittest.TestCase):
    """
    'Mission' varies freely (mission_id is non-authoritative -- Section
    10's explicit warning against turning it into a P2 security
    mechanism). 'Request' identity here is the (request_id,
    authorization) pair actually checked by the real chain -- "Request
    B" means an authorization that does NOT match the handoff's own
    request_id, which verify_authorization_binding() rejects
    regardless of mission_id. Video 005's Release Candidate Identity
    Lock scopes any SUCCESSFUL real path to request_id "005" -- so a
    genuinely different, successfully-authorized request_id is not
    constructible against the real chain today; the meaningful,
    real-chain-testable distinction is authorized (matching) vs
    unauthorized (mismatched) request identity, independent of
    mission_id.
    """

    def _compose_valid(self, mission_id):
        """'Request A' == the authorization the handoff was actually
        built/reviewed from (the ONLY authorization that can ever bind
        -- authorization_id itself is freshly minted per-handoff, so a
        'matching request' necessarily means reusing that exact
        object, never reconstructing an equivalent one)."""
        chain = _full_chain(mission_id=mission_id, request_id="005", auth=None)
        report_service, _ = self._mock_report_service()
        director = AIDirector()
        return director.compose_controlled_activation(
            handoff=chain["activation_handoff"], real_generation_authorization=chain["auth"],
            title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True,
            report_service=report_service,
        )

    def _compose_mismatched(self, mission_id):
        """'Request B' == an authorization that does NOT match the
        handoff's own authorization_id/request_id -- a fresh, unrelated
        RealGenerationAuthorization object, exactly what an attacker or
        a mixed-up caller would present."""
        chain = _full_chain(mission_id=mission_id, request_id="005", auth=None)
        report_service, _ = self._mock_report_service()
        director = AIDirector()
        wrong_auth = _valid_auth("005")  # correct request_id, WRONG (freshly minted) authorization_id
        return director.compose_controlled_activation(
            handoff=chain["activation_handoff"], real_generation_authorization=wrong_auth,
            title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True,
            report_service=report_service,
        )

    def test_mission_A_request_A_accepted(self):
        prepared = self._compose_valid("mission-A")
        self.assertEqual(prepared.mission_id, "mission-A")
        self.assertEqual(prepared.request.request_id, "005")

    def test_mission_A_request_B_rejected(self):
        with self.assertRaises(ControlledActivationCompositionError):
            self._compose_mismatched("mission-A")

    def test_mission_B_request_A_accepted(self):
        """The critical isolation proof: changing ONLY mission_id
        (A -> B) while keeping the same authorized request_id still
        succeeds, identically -- mission_id has no veto power."""
        prepared = self._compose_valid("mission-B")
        self.assertEqual(prepared.mission_id, "mission-B")
        self.assertEqual(prepared.request.request_id, "005")

    def test_mission_B_request_B_rejected(self):
        """Rejection is driven by request/authorization identity alone
        -- changing mission_id does not rescue an otherwise-invalid
        request, and does not introduce a second way to fail."""
        with self.assertRaises(ControlledActivationCompositionError):
            self._compose_mismatched("mission-B")


# ------------------------------------------------------------------
# 4. FINAL REPORT -- observability-only confirmation (Section 8)
# ------------------------------------------------------------------


class FinalReportObservabilityTests(_MockChainMixin, unittest.TestCase):
    def test_final_report_mission_id_not_used_for_replay_decision(self):
        """A second call with a DIFFERENT mission_id against the SAME
        request_id must still be rejected as ALREADY_EXECUTED -- replay
        protection keys on request_id alone, confirming mission_id
        plays no role in it, per Section 8."""
        report_service, _ = self._mock_report_service()
        director = AIDirector()
        prepared = director.prepare_real_generation_activation(
            video_id="005", title=TITLE, hook=HOOK, objective=OBJECTIVE,
            real_generation_authorization=_valid_auth("005"),
            approved=True, report_service=report_service,
        )
        first = report_service.generate(prepared.request, mission_id="mission-first")
        self.assertTrue(first.job_created)

        second = report_service.generate(prepared.request, mission_id="mission-second-entirely-different")
        self.assertFalse(second.job_created)
        self.assertIn("already been executed", " ".join(second.approval_reasons).lower())


if __name__ == "__main__":
    unittest.main()
