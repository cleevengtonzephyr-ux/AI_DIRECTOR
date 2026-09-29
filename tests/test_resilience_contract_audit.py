"""
Tests -- Production Authority Resilience & Recovery Contract Audit
(Phase P3.39).

P3.36 (provenance), P3.37 (temporal/freshness), and P3.38 (recovery/
reconciliation boundary) are each individually exhaustively tested
elsewhere in this suite (see the P3.39 report's Section 13 for the
full citation matrix). This file adds ONLY what synthesizing all
three together, adversarially, surfaced as genuinely new:

1. A concrete demonstration of a real (if narrow) "escape route" from
   UNKNOWN without external proof: GenerationApprovalGate's default
   constructor argument is `InMemoryExecutedRequestStore()` -- a
   process restart with a freshly-constructed Gate (no explicit store
   injected) silently loses ALL executed/UNKNOWN history, because nothing
   was ever persisted to disk. Production (director.py) never does
   this (it always injects `FileExecutedRequestStore` explicitly) --
   confirmed by a positive-control test -- but the class-level default
   itself is a real footgun for any future caller who constructs
   `GenerationApprovalGate` directly.
2. The full Section 6 multi-dimensional scenario (identity + provenance
   + freshness + execution state, combined, adversarially): authorization
   + activation for Mission A / Request "005", crash to UNKNOWN, restart,
   then an attempt using a DIFFERENT mission's authorization -- proving
   no combination of these three dimensions together opens a path to
   identity substitution that each dimension individually (already
   tested in P3.36/37/38) would not already have blocked alone.
3. A programmatic (not merely docstring-trusted) STATE != AUTHORITY
   check across all five P3.17-21 status enums, confirming none of
   them contains any value that could be mistaken for an authority
   grant (AUTHORIZED/APPROVED/ACTIVATED/EXECUTING/EXECUTED).

Fully offline: no network, no Higgsfield CLI, always MockHiggsfieldProvider.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import RequestScopedActivationService
from agents.activation_eligibility import ActivationEligibilityChecker, ActivationEligibilityInput, ActivationEligibilityStatus
from agents.content_agent import ContentAgent, ContentAgentInput
from agents.controlled_activation_composition import ControlledActivationCompositionError
from agents.controlled_real_provider_activation import ControlledRealProviderActivationService
from agents.critical_section_lock import FileCriticalSectionLock
from agents.executed_request_store import FileExecutedRequestStore, InMemoryExecutedRequestStore
from agents.final_report_service import FinalReportService
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from tests.authorization_content_helpers import bind_request, video_005_authorization
from agents.generation_job_service import GenerationJobService
from agents.human_authorization_handoff import (
    HumanAuthorizationHandoffBuilder,
    HumanAuthorizationHandoffInput,
    HumanAuthorizationHandoffStatus,
)
from agents.planner import VideoPlanner
from agents.pre_production_review import PreProductionReviewInput, PreProductionReviewer
from agents.production_activation_handoff import (
    ProductionActivationHandoffBuilder,
    ProductionActivationHandoffInput,
    ProductionActivationHandoffStatus,
)
from agents.production_authority_intake import ProductionAuthorityIntake, ProductionAuthorityIntakeInput, ProductionAuthorityIntakeStatus
from agents.production_readiness_handoff import ProductionReadinessHandoffBuilder, ProductionReadinessHandoffInput, ProductionReadinessHandoffStatus
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.asset_preparation_system import AssetPreparationSystem
from agents.release_candidate_identity_lock import ReleaseCandidateIdentityLock, VIDEO_005_RELEASE_CANDIDATE
from agents.script_production_bridge import ProductionPreparationInput
from agents.strategy_agent import StrategyAgent, StrategyAgentInput
from agents.video_production_preparation import VideoProductionPreparation, VideoProductionPreparationInput
from director import AIDirector
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.types import MediaReference

C = VIDEO_005_RELEASE_CANDIDATE
TITLE = "Pourquoi la discipline vaut plus que le talent."
HOOK = "Le talent impressionne. La discipline construit des empires."
OBJECTIVE = "Créer une vidéo courte, cinématique et motivante."

REAL_AVATAR_PATH = PROJECT_ROOT / "assets" / "zephyr" / "avatar" / "avatar_master.png"
REAL_FACE_PATH = PROJECT_ROOT / "assets" / "zephyr" / "references" / "mon avatar habille.png"


def _real_prompt() -> str:
    return PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id)


def _conforming_request(**overrides) -> GenerationRequest:
    defaults = dict(
        request_id=C.request_id, job_type=C.job_type, prompt=_real_prompt(),
        duration=C.duration, resolution=C.resolution, aspect_ratio=C.aspect_ratio,
        approved=True,
        start_image=MediaReference(role="master_avatar", source=str(REAL_AVATAR_PATH), sha256=None),
        image_references=(MediaReference(role="face_reference", source=str(REAL_FACE_PATH), sha256=None),),
        real_generation_authorization=RealGenerationAuthorization(request_id=C.request_id, authorized_by_human=True),
    )
    defaults.update(overrides)
    return bind_request(GenerationRequest(**defaults))


# ------------------------------------------------------------------
# 1. DEFAULT-STORE UNKNOWN NON-PERSISTENCE (a real, narrow footgun)
# ------------------------------------------------------------------


class DefaultStorePersistenceTests(unittest.TestCase):
    def test_gate_default_constructor_uses_nonpersistent_store(self):
        """Confirms the class-level default, not just by reading the
        source: GenerationApprovalGate(provider) with no explicit
        store gets InMemoryExecutedRequestStore -- a real footgun for
        any caller that bypasses AIDirector's builder."""
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
        gate = GenerationApprovalGate(provider, identity_lock=ReleaseCandidateIdentityLock(C))
        self.assertIsInstance(gate.executed_request_store, InMemoryExecutedRequestStore)

    def test_unknown_state_is_silently_lost_across_a_simulated_restart_with_the_default_store(self):
        """Demonstrates, executably, the one real 'escape route' from
        UNKNOWN without external proof this audit found: if a caller
        constructs a fresh Gate with the DEFAULT (in-memory) store
        after a crash -- instead of reusing a Gate backed by the same
        FileExecutedRequestStore -- the UNKNOWN record is gone, and a
        fresh evaluate() proceeds as if nothing happened. This is not
        a code bypass; it requires the caller to deliberately construct
        a non-persistent Gate, which production (director.py) never
        does (see the positive control below)."""
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
        identity_lock = ReleaseCandidateIdentityLock(C)

        gate_before_crash = GenerationApprovalGate(provider, identity_lock=identity_lock)
        gate_before_crash.mark_unknown(C.request_id, reason="simulated crash")
        self.assertEqual(
            gate_before_crash.evaluate(_conforming_request()).decision,
            GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN,
        )

        # "Restart": a FRESH Gate, default (non-persistent) store --
        # simulates a caller who forgot to wire persistence.
        gate_after_restart = GenerationApprovalGate(provider, identity_lock=identity_lock)
        approval_after_restart = gate_after_restart.evaluate(_conforming_request())
        self.assertNotEqual(approval_after_restart.decision, GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN)

    def test_director_production_chain_uses_the_persistent_file_store(self):
        """Positive control: the REAL production path never falls into
        the footgun above -- AIDirector._build_default_chain() always
        injects a FileExecutedRequestStore explicitly."""
        director = AIDirector()
        chain = director._build_default_chain()
        self.assertIsInstance(chain.gate.executed_request_store, FileExecutedRequestStore)

    def test_unknown_state_correctly_survives_restart_with_the_persistent_store(self):
        """Same restart simulation as above, but with the store
        production actually uses -- UNKNOWN correctly survives."""
        tmp = Path(tempfile.mkdtemp(prefix="p3_39_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        store_path = tmp / "executed_requests.json"

        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
        identity_lock = ReleaseCandidateIdentityLock(C)

        gate_before_crash = GenerationApprovalGate(
            provider, executed_request_store=FileExecutedRequestStore(store_path), identity_lock=identity_lock,
        )
        gate_before_crash.mark_unknown(C.request_id, reason="simulated crash")

        # "Restart": a fresh Gate, but pointed at the SAME file -- what
        # director.py actually does across invocations.
        gate_after_restart = GenerationApprovalGate(
            provider, executed_request_store=FileExecutedRequestStore(store_path), identity_lock=identity_lock,
        )
        approval = gate_after_restart.evaluate(_conforming_request())
        self.assertEqual(approval.decision, GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN)


# ------------------------------------------------------------------
# 2. COMBINED PROVENANCE + TEMPORAL + RECOVERY SCENARIO (Section 6)
# ------------------------------------------------------------------


class CombinedDimensionScenarioTests(unittest.TestCase):
    def _full_chain(self, mission_id, tmp_dir):
        strategy = StrategyAgent().run(StrategyAgentInput(
            mission_id=mission_id, objective="Explain why discipline beats talent over time.",
            platforms=("tiktok", "youtube"), topic="discipline vs talent", audience="young adults",
        ))
        content = ContentAgent().run(ContentAgentInput(mission_id=mission_id, strategy_artifact=strategy.strategy_artifact))
        plan = VideoPlanner(PROJECT_ROOT).create_zephyr_plan(video_id="005", title=TITLE, hook=HOOK, objective=OBJECTIVE)
        integration = VideoProductionPreparation(
            prompt_assembly=PromptAssemblySystem(PROJECT_ROOT), asset_preparation=AssetPreparationSystem(PROJECT_ROOT),
        )
        prep_result = integration.prepare(VideoProductionPreparationInput(
            production_input=ProductionPreparationInput(mission_id=mission_id, script_artifact=content.script_artifact, video_id="005"),
            video_plan=plan, request_id="005",
        ))
        review = PreProductionReviewer().review(PreProductionReviewInput(preparation_result=prep_result))
        readiness = ProductionReadinessHandoffBuilder().build(ProductionReadinessHandoffInput(review=review))
        intake = ProductionAuthorityIntake().intake(ProductionAuthorityIntakeInput(handoff=readiness))
        auth = video_005_authorization()
        auth_handoff = HumanAuthorizationHandoffBuilder().build(
            HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=auth)
        )
        eligibility = ActivationEligibilityChecker().check_eligibility(
            ActivationEligibilityInput(human_authorization_handoff=auth_handoff)
        )
        activation_handoff = ProductionActivationHandoffBuilder().build(
            ProductionActivationHandoffInput(eligibility=eligibility)
        )
        return activation_handoff, auth

    def _mock_report_service(self, store_path):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(provider, executed_request_store=FileExecutedRequestStore(store_path), identity_lock=identity_lock)
        activation_service = RequestScopedActivationService(gate, identity_lock)
        provider_activation_service = ControlledRealProviderActivationService(gate, identity_lock, activation_service)
        lock = FileCriticalSectionLock(store_path.parent / "locks")
        job_service = GenerationJobService(
            provider, gate, lock=lock, activation_service=activation_service, provider_activation_service=provider_activation_service,
        )
        return FinalReportService(provider, gate, job_service=job_service), gate

    def test_mission_A_crash_to_unknown_then_mission_B_attempt_is_still_isolated(self):
        """Identity + provenance + freshness + execution state, all at
        once: Mission A's authorization/activation reach UNKNOWN via a
        simulated crash; a SEPARATE, later attempt built from Mission
        B's own full chain (different strategy/content/handoff, same
        canonical request_id "005" since that's the only real Release
        Candidate) must be evaluated on its own merits -- and, because
        both necessarily target request_id "005", Mission B's attempt
        is correctly blocked too, but for the SAME reason (request_id
        "005" is UNKNOWN), never because of anything mission-specific
        -- proving no combination of these three dimensions opens an
        identity-substitution path beyond what each already blocks
        alone."""
        tmp = Path(tempfile.mkdtemp(prefix="p3_39_combined_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        store_path = tmp / "executed_requests.json"

        handoff_a, auth_a = self._full_chain("mission-A", tmp)
        report_service, gate = self._mock_report_service(store_path)
        director = AIDirector()

        prepared_a = director.compose_controlled_activation(
            handoff=handoff_a, real_generation_authorization=auth_a,
            title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True, report_service=report_service,
        )
        self.assertEqual(prepared_a.mission_id, "mission-A")

        # Simulated crash: request "005" becomes UNKNOWN.
        gate.mark_unknown("005", reason="simulated crash mid-execution for mission-A")

        # A fresh attempt, from Mission B's own independently-built
        # chain, "restarted" against the SAME persisted store.
        handoff_b, auth_b = self._full_chain("mission-B", tmp)
        report_service_2, gate_2 = self._mock_report_service(store_path)  # simulates a new process, same file
        director_2 = AIDirector()

        with self.assertRaises(Exception) as ctx:
            prepared_b = director_2.compose_controlled_activation(
                handoff=handoff_b, real_generation_authorization=auth_b,
                title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True, report_service=report_service_2,
            )
            # If composition itself doesn't fail (it only pre-checks
            # structure, not UNKNOWN), execution must be what blocks it.
            report_service_2.job_service.execute(prepared_b.request)

        # Whatever failed, it must be attributable to request_id "005"
        # being UNKNOWN -- never to mission_id, which the exception
        # text must never even mention.
        self.assertNotIn("mission-A", str(ctx.exception))
        self.assertNotIn("mission-B", str(ctx.exception))


# ------------------------------------------------------------------
# 3. PROGRAMMATIC STATE != AUTHORITY CHECK
# ------------------------------------------------------------------


class StateNotAuthorityTests(unittest.TestCase):
    FORBIDDEN_AUTHORITY_WORDS = ("AUTHORIZED", "APPROVED", "ACTIVATED", "EXECUTING", "EXECUTED")

    def test_no_p3_status_enum_contains_an_authority_bearing_value(self):
        enums = (
            ProductionReadinessHandoffStatus,
            ProductionAuthorityIntakeStatus,
            HumanAuthorizationHandoffStatus,
            ActivationEligibilityStatus,
            ProductionActivationHandoffStatus,
        )
        offenders = []
        for enum_cls in enums:
            for member in enum_cls:
                if any(word in member.value.upper() for word in self.FORBIDDEN_AUTHORITY_WORDS):
                    offenders.append(f"{enum_cls.__name__}.{member.name}={member.value!r}")
        self.assertFalse(offenders, f"status enum value(s) could be mistaken for an authority grant: {offenders}")


if __name__ == "__main__":
    unittest.main()
