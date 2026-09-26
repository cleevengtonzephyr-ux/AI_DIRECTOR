"""
Tests -- Provenance Integrity & Trace Consistency Audit (Phase P3.36).

Central question: "Can data from Mission A be accidentally used as if
it came from Mission B, without the system being able to detect it?"

This file adds ONLY the genuinely new integration-level angles P3.33/
P3.34/P3.35 did not already cover with dedicated tests:

1. A full TWO-MISSION parallel chain (Mission A / Mission B, both on
   the only real Release-Candidate-eligible request_id "005") with
   cross-substitution at the PRODUCTION PREPARATION boundary, going
   further than the existing unit-level
   tests/test_script_production_bridge.py::test_invalid_script_wrong_mission
   by exercising the real ScriptProductionBridge->...->
   ProductionActivationHandoff integration path.
2. Reuse of a REAL authorization minted for one full chain against a
   DIFFERENT full chain's handoff (not merely a freshly-constructed,
   unrelated RealGenerationAuthorization, which P3.34/P3.35 already
   covered).
3. A targeted identity-hash-substitution test directly against
   ControlledActivationComposition.verify_generation_request_
   consistency() -- the seam P3.33/P3.34 identified as the single most
   load-bearing traceability check in the whole architecture.
4. Artifact-level immutability for ScriptArtifact specifically (the
   object that actually crosses the Domain A/B boundary).

Everything else this phase's required test list (Section 18) asks for
already has dedicated, passing coverage elsewhere in this suite -- the
P3.36 report cites those directly by file:line rather than duplicating
them here (prompt/asset mutation: test_phase_p2_22/25/26/38/39;
cross-mission at the bridge: test_script_production_bridge.py;
mission/request grid: test_mission_traceability_integration_audit.py;
FinalReport provenance across SUCCESS/NOT_EXECUTED/UNKNOWN/replay:
test_mission_identity_contract.py; deterministic trace:
test_mission_traceability_integration_audit.py; hash tamper detection:
test_production_readiness_handoff.py and siblings).

Fully offline: no network, no Higgsfield CLI, always a
MockHiggsfieldProvider-backed report_service.
"""

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
from agents.controlled_activation_composition import (
    ControlledActivationCompositionError,
    verify_generation_request_consistency,
)
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
from agents.script_production_bridge import ProductionPreparationInput, ScriptProductionBridge
from agents.strategy_agent import StrategyAgent, StrategyAgentInput
from agents.video_production_preparation import VideoProductionPreparation, VideoProductionPreparationInput
from director import AIDirector
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider

TITLE = "Pourquoi la discipline vaut plus que le talent."
HOOK = "Le talent impressionne. La discipline construit des empires."
OBJECTIVE = "Créer une vidéo courte, cinématique et motivante."


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
    return RealGenerationAuthorization(request_id=request_id, authorized_by_human=True)


def _full_chain(mission_id: str, request_id="005"):
    script = _real_script_artifact(mission_id)
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
    auth = _valid_auth(request_id)
    auth_handoff = HumanAuthorizationHandoffBuilder().build(
        HumanAuthorizationHandoffInput(intake=intake, real_generation_authorization=auth)
    )
    eligibility = ActivationEligibilityChecker().check_eligibility(
        ActivationEligibilityInput(human_authorization_handoff=auth_handoff)
    )
    activation_handoff = ProductionActivationHandoffBuilder().build(
        ProductionActivationHandoffInput(eligibility=eligibility)
    )
    return {
        "script_artifact": script,
        "activation_handoff": activation_handoff,
        "auth": auth,
    }


class _MockChainMixin:
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p3_36_"))
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
        return FinalReportService(provider, gate, job_service=job_service), gate


# ------------------------------------------------------------------
# 1. TWO-MISSION PARALLEL CHAIN -- integration-level cross-substitution
#    at the ScriptProductionBridge boundary (beyond the existing
#    unit-level test_invalid_script_wrong_mission).
# ------------------------------------------------------------------


class TwoMissionParallelChainTests(unittest.TestCase):
    """Builds Mission A's and Mission B's ScriptArtifact independently,
    then attempts every cross-combination against ScriptProductionBridge
    directly -- the earliest point in the real chain a Mission-B object
    could be mistaken for Mission A's, or vice versa."""

    @classmethod
    def setUpClass(cls):
        cls.script_a = _real_script_artifact("mission-A")
        cls.script_b = _real_script_artifact("mission-B")

    def test_A_artifact_A_preparation_valid(self):
        # No prompt_assembly/asset_preparation injected here (this
        # class only exercises ScriptProductionBridge in isolation),
        # so full READY (which needs prompt/asset resolution, cf.
        # VideoProductionPreparation) is not expected -- what matters
        # for this test is that mission_id MATCHES, so the script is
        # accepted and carried through rather than rejected/dropped.
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(mission_id="mission-A", script_artifact=self.script_a, video_id="005")
        )
        self.assertIsNotNone(prepared.script_artifact)
        self.assertFalse(any("does not match" in r for r in prepared.reasons))

    def test_B_artifact_B_preparation_valid(self):
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(mission_id="mission-B", script_artifact=self.script_b, video_id="005")
        )
        self.assertIsNotNone(prepared.script_artifact)
        self.assertFalse(any("does not match" in r for r in prepared.reasons))

    def test_A_artifact_B_preparation_rejected(self):
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(mission_id="mission-B", script_artifact=self.script_a, video_id="005")
        )
        self.assertEqual(prepared.status.value, "BLOCKED")
        self.assertTrue(any("does not match" in r for r in prepared.reasons))
        self.assertIsNone(prepared.script_artifact)

    def test_B_artifact_A_preparation_rejected(self):
        prepared = ScriptProductionBridge().prepare(
            ProductionPreparationInput(mission_id="mission-A", script_artifact=self.script_b, video_id="005")
        )
        self.assertEqual(prepared.status.value, "BLOCKED")
        self.assertTrue(any("does not match" in r for r in prepared.reasons))
        self.assertIsNone(prepared.script_artifact)


# ------------------------------------------------------------------
# 2. AUTHORIZATION PROVENANCE -- a REAL authorization from one full
#    chain reused against a DIFFERENT full chain's handoff (not just a
#    freshly-constructed unrelated authorization, cf. P3.34/P3.35).
# ------------------------------------------------------------------


class CrossChainAuthorizationReuseTests(_MockChainMixin, unittest.TestCase):
    def test_chain_A_authorization_rejected_against_chain_B_handoff(self):
        chain_a = _full_chain(mission_id="mission-A")
        chain_b = _full_chain(mission_id="mission-B")
        report_service, _ = self._mock_report_service()
        director = AIDirector()

        with self.assertRaises(ControlledActivationCompositionError) as ctx:
            director.compose_controlled_activation(
                handoff=chain_b["activation_handoff"],
                real_generation_authorization=chain_a["auth"],  # wrong chain's auth
                title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True,
                report_service=report_service,
            )
        self.assertIn("does not match", str(ctx.exception))

    def test_chain_B_authorization_rejected_against_chain_A_handoff(self):
        chain_a = _full_chain(mission_id="mission-A")
        chain_b = _full_chain(mission_id="mission-B")
        report_service, _ = self._mock_report_service()
        director = AIDirector()

        with self.assertRaises(ControlledActivationCompositionError) as ctx:
            director.compose_controlled_activation(
                handoff=chain_a["activation_handoff"],
                real_generation_authorization=chain_b["auth"],  # wrong chain's auth
                title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True,
                report_service=report_service,
            )
        self.assertIn("does not match", str(ctx.exception))

    def test_chain_A_authorization_accepted_against_chain_A_handoff(self):
        """Positive control -- proves the rejections above are due to
        the mismatch, not to some unrelated failure in the fixtures."""
        chain_a = _full_chain(mission_id="mission-A")
        report_service, _ = self._mock_report_service()
        director = AIDirector()
        prepared = director.compose_controlled_activation(
            handoff=chain_a["activation_handoff"], real_generation_authorization=chain_a["auth"],
            title=TITLE, hook=HOOK, objective=OBJECTIVE, approved=True,
            report_service=report_service,
        )
        self.assertEqual(prepared.mission_id, "mission-A")


# ------------------------------------------------------------------
# 3. IDENTITY HASH SUBSTITUTION -- direct test of
#    verify_generation_request_consistency(), the seam P3.33/P3.34
#    identified as the single most load-bearing traceability check.
# ------------------------------------------------------------------


class IdentityHashSubstitutionTests(_MockChainMixin, unittest.TestCase):
    def _prepared_and_reviewed(self):
        chain = _full_chain(mission_id="mission-hash-audit")
        report_service, _ = self._mock_report_service()
        director = AIDirector()
        prepared = director.prepare_real_generation_activation(
            video_id="005", title=TITLE, hook=HOOK, objective=OBJECTIVE,
            real_generation_authorization=chain["auth"],
            approved=True, report_service=report_service,
        )
        reviewed = (
            chain["activation_handoff"].eligibility.human_authorization_handoff
            .intake.handoff.review.generation_request
        )
        return prepared.request, reviewed

    def test_matching_request_passes(self):
        freshly_built, reviewed = self._prepared_and_reviewed()
        verify_generation_request_consistency(freshly_built, reviewed)  # no raise

    def test_prompt_substitution_detected(self):
        freshly_built, reviewed = self._prepared_and_reviewed()
        tampered = dc_replace(reviewed, prompt="a completely different, substituted prompt")
        with self.assertRaises(ControlledActivationCompositionError) as ctx:
            verify_generation_request_consistency(freshly_built, tampered)
        self.assertIn("prompt", str(ctx.exception))

    def test_request_id_substitution_detected(self):
        freshly_built, reviewed = self._prepared_and_reviewed()
        tampered = dc_replace(reviewed, request_id="not-005")
        with self.assertRaises(ControlledActivationCompositionError) as ctx:
            verify_generation_request_consistency(freshly_built, tampered)
        self.assertIn("request_id", str(ctx.exception))

    def test_duration_substitution_detected(self):
        freshly_built, reviewed = self._prepared_and_reviewed()
        tampered = dc_replace(reviewed, duration=freshly_built.duration + 1)
        with self.assertRaises(ControlledActivationCompositionError) as ctx:
            verify_generation_request_consistency(freshly_built, tampered)
        self.assertIn("duration", str(ctx.exception))


# ------------------------------------------------------------------
# 4. ARTIFACT-LEVEL IMMUTABILITY (ScriptArtifact -- the object that
#    actually crosses the Domain A/B boundary).
# ------------------------------------------------------------------


class ArtifactImmutabilityTests(unittest.TestCase):
    def test_script_artifact_cannot_be_mutated_directly(self):
        script = _real_script_artifact("mission-immutable")
        with self.assertRaises(FrozenInstanceError):
            script.mission_id = "tampered"  # type: ignore[misc]

    def test_replace_produces_new_object_original_unchanged(self):
        script = _real_script_artifact("mission-immutable-2")
        original_mission_id = script.mission_id
        _ = dc_replace(script, mission_id="different-mission")
        self.assertEqual(script.mission_id, original_mission_id)


if __name__ == "__main__":
    unittest.main()
