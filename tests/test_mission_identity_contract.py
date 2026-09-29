"""
Tests -- Mission Identity Contract (Phase P3.34).

Proves that `mission_id`, threaded additively through
`PreparedRealGenerationActivation` (director.py) and `FinalReport`
(agents/final_report_service.py) since P3.34, is PURE OBSERVABILITY
METADATA: it never influences GenerationApprovalGate, cost, budget,
human authorization, activation eligibility, activation consumption,
Identity Lock, CriticalSectionLock, replay protection, provider
activation, create_job, or the execution result. `request_id` remains
the sole P2 execution identity.

Fully offline: no network, no Higgsfield CLI, always a
MockHiggsfieldProvider-backed report_service, exactly the same
discipline as tests/test_controlled_activation_composition.py (which
this file borrows its fixture-building helpers' shape from).
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

from agents.activation_contract import RequestScopedActivationService
from agents.activation_eligibility import ActivationEligibilityChecker, ActivationEligibilityInput
from agents.asset_preparation_system import AssetPreparationSystem
from agents.content_agent import ContentAgent, ContentAgentInput
from agents.controlled_real_provider_activation import ControlledRealProviderActivationService
from agents.critical_section_lock import FileCriticalSectionLock
from agents.final_report_service import FinalReport, FinalReportService
from agents.generation_approval_gate import GenerationApprovalGate, RealGenerationAuthorization
from tests.authorization_content_helpers import video_005_authorization
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
from director import AIDirector, PreparedRealGenerationActivation
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider

TITLE = "Pourquoi la discipline vaut plus que le talent."
HOOK = "Le talent impressionne. La discipline construit des empires."
OBJECTIVE = "Créer une vidéo courte, cinématique et motivante."

P2_PROTECTED_FILES = (
    "agents/generation_approval_gate.py",
    "agents/generation_job_service.py",
    "agents/activation_contract.py",
    "agents/controlled_real_provider_activation.py",
    "agents/critical_section_lock.py",
    "agents/executed_request_store.py",
    "agents/release_candidate_identity_lock.py",
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
    return content.script_artifact


def _valid_auth(request_id="005"):
    return video_005_authorization(request_id=request_id)


def _ready_handoff(mission_id: str, request_id="005", auth=None):
    script = _real_script_artifact(mission_id)
    plan = _real_video_005_plan()
    pa = PromptAssemblySystem(PROJECT_ROOT)
    assets = AssetPreparationSystem(PROJECT_ROOT)
    integration = VideoProductionPreparation(prompt_assembly=pa, asset_preparation=assets)
    result = integration.prepare(
        VideoProductionPreparationInput(
            production_input=ProductionPreparationInput(
                mission_id=mission_id, script_artifact=script, video_id="005"
            ),
            video_plan=plan,
            request_id=request_id,
        )
    )
    review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=result))
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


class _MockChainMixin:
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p3_34_"))
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

    def _simple_request(self, request_id="005", report_service=None):
        # Reuses the exact real Video 005 request-building path
        # (VideoAgent.build_request(), via the unmodified P2.29 entry
        # point) so the Identity Lock and Gate accept it -- never a
        # fabricated GenerationRequest, and never the merely-reviewed
        # one embedded in the P3 handoff chain (which is a separate
        # object, cf. verify_generation_request_consistency()).
        director = AIDirector()
        prepared = director.prepare_real_generation_activation(
            video_id=request_id, title=TITLE, hook=HOOK, objective=OBJECTIVE,
            real_generation_authorization=_valid_auth(request_id),
            approved=True, report_service=report_service or self._mock_report_service()[0],
        )
        return prepared.request


# ------------------------------------------------------------------
# 1. END-TO-END PROPAGATION
# ------------------------------------------------------------------


class EndToEndPropagationTests(_MockChainMixin, unittest.TestCase):
    def test_mission_id_survives_composition_to_prepared_bundle(self):
        handoff, auth = _ready_handoff(mission_id="mission-alpha")
        report_service, _ = self._mock_report_service()
        director = AIDirector()
        prepared = director.compose_controlled_activation(
            handoff=handoff, real_generation_authorization=auth,
            title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True,
            report_service=report_service,
        )
        self.assertEqual(prepared.mission_id, "mission-alpha")
        self.assertEqual(prepared.request.request_id, "005")
        self.assertNotEqual(prepared.mission_id, prepared.request.request_id)

    def test_mission_id_survives_into_final_report(self):
        handoff, auth = _ready_handoff(mission_id="mission-beta")
        report_service, _ = self._mock_report_service()
        director = AIDirector()
        prepared = director.compose_controlled_activation(
            handoff=handoff, real_generation_authorization=auth,
            title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True,
            report_service=report_service,
        )
        report = director.execute_real_generation_activation(prepared, report_service=report_service)
        self.assertEqual(report.mission_id, "mission-beta")
        self.assertEqual(report.request_id, "005")

    def test_prepare_real_generation_activation_direct_call_leaves_mission_id_none(self):
        """The unmodified P2.29 entry point never sets mission_id --
        only compose_controlled_activation() (P3.23/P3.34) stamps it,
        post-hoc, via dataclasses.replace()."""
        report_service, _ = self._mock_report_service()
        director = AIDirector()
        prepared = director.prepare_real_generation_activation(
            video_id="005", title=TITLE, hook=HOOK, objective=OBJECTIVE,
            real_generation_authorization=_valid_auth("005"),
            approved=True, report_service=report_service,
        )
        self.assertIsInstance(prepared, PreparedRealGenerationActivation)
        self.assertIsNone(prepared.mission_id)

    def test_unknown_execution_state_preserves_mission_id(self):
        """A request already marked UNKNOWN by a prior crash (Phase
        P2.20) must still yield a FinalReport carrying mission_id --
        observability must not vanish exactly when it matters most.
        (A crash DURING the current attempt deliberately propagates an
        uncaught GenerationJobUnknownStateError instead of producing
        any FinalReport at all -- confirmed separately below; that is
        pre-existing, unmodified P2 behaviour, not something P3.34
        changes.)"""
        report_service, gate = self._mock_report_service()
        request = self._simple_request("005", report_service=report_service)
        gate.executed_request_store.mark_unknown(request.request_id, "prior simulated crash")

        report = report_service.generate(request, mission_id="mission-crash")
        self.assertEqual(report.execution_state, "EXECUTION_STATE_UNKNOWN")
        self.assertFalse(report.job_created)
        self.assertEqual(report.mission_id, "mission-crash")

    def test_crash_during_mark_executed_propagates_uncaught_no_final_report(self):
        """Pre-existing P2 behaviour (P2.20/P2.23, unmodified by
        P3.34): if create_job() succeeds but mark_executed() AND
        mark_unknown() both fail, GenerationJobUnknownStateError-family
        exceptions propagate uncaught -- no FinalReport, no mission_id
        field, no silent 'clean' report is ever produced. Confirms
        P3.34 did not weaken this guarantee."""
        report_service, gate = self._mock_report_service()

        from agents.executed_request_store import InMemoryAuthorizationConsumptionRegistry

        class _BrokenStore:
            # Phase B : registre de consommation requis par le Gate
            # (sans lui : BLOCKED, fail closed) -- en mémoire ici.
            authorization_registry = InMemoryAuthorizationConsumptionRegistry()

            def is_executed(self, request_id):
                return False

            def is_unknown(self, request_id):
                return False

            def mark_executed(self, request_id, job_id=None):
                raise RuntimeError("simulated crash before persistence")

            def mark_unknown(self, request_id, reason, job_id=None):
                raise RuntimeError("mark_unknown also fails")

        gate.executed_request_store = _BrokenStore()
        request = self._simple_request("005", report_service=report_service)

        with self.assertRaises(Exception):
            report_service.generate(request, mission_id="mission-double-crash")

    def test_not_executed_failure_path_preserves_mission_id(self):
        report_service, _ = self._mock_report_service(available_credits=0.0)
        request = self._simple_request("005")
        report = report_service.generate(request, mission_id="mission-budget-blocked")
        self.assertEqual(report.status.value, "NOT_EXECUTED")
        self.assertEqual(report.mission_id, "mission-budget-blocked")

    def test_replay_preserves_mission_id(self):
        report_service, _ = self._mock_report_service()
        request = self._simple_request("005")
        first = report_service.generate(request, mission_id="mission-replay")
        self.assertTrue(first.job_created)
        second = report_service.generate(request, mission_id="mission-replay")
        self.assertFalse(second.job_created)
        self.assertIn("already been executed", " ".join(second.approval_reasons).lower())
        self.assertEqual(second.mission_id, "mission-replay")


# ------------------------------------------------------------------
# 2. AUTHORITY ISOLATION (differential tests: mission_id=A vs B)
# ------------------------------------------------------------------


class AuthorityIsolationTests(_MockChainMixin, unittest.TestCase):
    def test_differential_mission_id_never_changes_authority_outcome(self):
        """Same request, only mission_id differs (A vs B) -- every
        authority-relevant field on the FinalReport must be identical;
        only `mission_id` and (trivially) nothing else may diverge."""
        report_service_a, _ = self._mock_report_service()
        report_service_b, _ = self._mock_report_service()
        request = self._simple_request("005")

        report_a = report_service_a.generate(request, mission_id="mission-A")
        report_b = report_service_b.generate(request, mission_id="mission-B")

        self.assertNotEqual(report_a.mission_id, report_b.mission_id)
        for field_name in (
            "request_id", "job_type", "status", "job_created",
            "approval_decision", "approval_reasons",
            "activation_decision", "activation_reasons",
            "provider_activation_decision", "provider_activation_reasons",
            "real_provider_called", "cost_status", "estimated_credits",
            "job_status", "quality_decision", "quality_reasons",
        ):
            self.assertEqual(
                getattr(report_a, field_name), getattr(report_b, field_name),
                f"field '{field_name}' diverged between mission_id=A and mission_id=B",
            )

    def test_mission_id_does_not_change_approval_gate_decision(self):
        report_service, gate = self._mock_report_service(available_credits=0.0)
        request = self._simple_request("005")

        decision_no_mission = gate.evaluate(request).decision
        decision_with_mission_a = gate.evaluate(request).decision
        decision_with_mission_b = gate.evaluate(request).decision
        # mission_id is never a parameter of evaluate() at all -- the
        # Gate has no way to see it. This test documents that fact by
        # construction, not by inspecting a parameter that doesn't
        # exist.
        self.assertEqual(decision_no_mission, decision_with_mission_a)
        self.assertEqual(decision_with_mission_a, decision_with_mission_b)

    def test_mismatched_mission_id_cannot_paper_over_authorization_mismatch(self):
        """mission_id must never become a substitute security check:
        an authorization for a DIFFERENT request_id is still rejected
        regardless of which mission_id the caller claims."""
        handoff, _ = _ready_handoff(mission_id="mission-real")
        wrong_auth = RealGenerationAuthorization(request_id="not-005", authorized_by_human=True)
        report_service, _ = self._mock_report_service()
        director = AIDirector()
        from agents.controlled_activation_composition import ControlledActivationCompositionError

        with self.assertRaises(ControlledActivationCompositionError):
            director.compose_controlled_activation(
                handoff=handoff, real_generation_authorization=wrong_auth,
                title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True,
                report_service=report_service,
            )


# ------------------------------------------------------------------
# 3. IMMUTABILITY / EQUALITY / VALIDATION
# ------------------------------------------------------------------


class ImmutabilityTests(_MockChainMixin, unittest.TestCase):
    def test_final_report_mission_id_is_immutable(self):
        report_service, _ = self._mock_report_service()
        request = self._simple_request("005")
        report = report_service.generate(request, mission_id="mission-frozen")
        with self.assertRaises(FrozenInstanceError):
            report.mission_id = "tampered"  # type: ignore[misc]

    def test_prepared_activation_mission_id_is_immutable(self):
        handoff, auth = _ready_handoff(mission_id="mission-frozen-2")
        report_service, _ = self._mock_report_service()
        director = AIDirector()
        prepared = director.compose_controlled_activation(
            handoff=handoff, real_generation_authorization=auth,
            title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True,
            report_service=report_service,
        )
        with self.assertRaises(FrozenInstanceError):
            prepared.mission_id = "tampered"  # type: ignore[misc]

    def test_equality_deterministic_for_identical_mission_id(self):
        report_service, _ = self._mock_report_service()
        request = self._simple_request("005")
        report = report_service.generate(request, mission_id="mission-eq")
        same_fields_copy = dc_replace(report)
        self.assertEqual(report, same_fields_copy)

    def test_empty_string_mission_id_is_preserved_verbatim_not_coerced_to_none(self):
        report_service, _ = self._mock_report_service()
        request = self._simple_request("005")
        report = report_service.generate(request, mission_id="")
        self.assertEqual(report.mission_id, "")
        self.assertIsNotNone(report.mission_id)

    def test_none_mission_id_backward_compatible_default(self):
        report_service, _ = self._mock_report_service()
        request = self._simple_request("005")
        report = report_service.generate(request)
        self.assertIsNone(report.mission_id)


# ------------------------------------------------------------------
# 4. P2 ISOLATION (static, AST-based)
# ------------------------------------------------------------------


class P2IsolationTests(unittest.TestCase):
    def test_no_p2_protected_file_references_mission_id(self):
        offenders = {}
        for relative_path in P2_PROTECTED_FILES:
            source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
            if "mission_id" in source:
                offenders[relative_path] = source.count("mission_id")
        self.assertFalse(offenders, f"P2-protected file(s) reference mission_id: {offenders}")

    def test_prepare_real_generation_activation_body_never_reads_mission_id(self):
        director_source = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        tree = ast.parse(director_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "prepare_real_generation_activation":
                body_source = ast.get_source_segment(director_source, node) or ""
                # Strip the docstring (which legitimately narrates
                # mission_id in prose) before the substring check.
                if isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
                    doc = node.body[0].value.value
                    body_source = body_source.replace(doc, "", 1)
                self.assertNotIn("mission_id", body_source)
                return
        raise AssertionError("prepare_real_generation_activation not found in director.py")

    def test_generation_request_dataclass_has_no_mission_id_field(self):
        from agents.generation_approval_gate import GenerationRequest

        self.assertNotIn("mission_id", GenerationRequest.__dataclass_fields__)


if __name__ == "__main__":
    unittest.main()
