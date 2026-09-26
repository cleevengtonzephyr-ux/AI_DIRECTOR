"""
Tests — Phase P2.11 : EXPLICIT HUMAN AUTHORIZATION GUARD.

Deuxième verrou de sécurité, structurellement distinct du premier
(`GenerationRequest.approved`) : `RealGenerationAuthorization`
(agents/generation_approval_gate.py). Objectif verrouillé par cette
suite : ni le budget, ni `approved=True` seul, ni un dry-run, ni un
ancien run/cache ne peuvent jamais produire une autorisation humaine
valide — seule une construction EXPLICITE de `RealGenerationAuthorization`,
liée au `request_id` exact, le peut.

Tous les scénarios Mock utilisent EXCLUSIVEMENT MockHiggsfieldProvider
(aucun réseau, aucun CLI réel, aucun crédit consommé). Le scénario
Provider réel (Test G) et le scénario pipeline Video 005 (Test H)
n'effectuent QUE des opérations read-only (estimate_cost,
get_account_balance, get_model) ou vérifient que create_job() reste
bloqué SANS jamais toucher au réseau (client factice/isolé) — aucune
génération réelle n'est jamais tentée.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.asset_preparation_system import AssetPreparationSystem
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from agents.generation_job_service import GenerationJobExecutionError, GenerationJobService
from agents.planner import VideoPlanner
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.video_agent import VideoAgent
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider


def _request(**overrides) -> GenerationRequest:
    defaults = dict(
        request_id="005",
        job_type="seedance_2_0",
        prompt="prompt de test",
        duration=5,
        resolution="720p",
        aspect_ratio="9:16",
        approved=True,
    )
    defaults.update(overrides)
    return GenerationRequest(**defaults)


class TestA_NoConsentBlocksEvenWithBudgetAndApproved(unittest.TestCase):
    """Test A — budget suffisant + approved=True mais AUCUNE autorisation humaine."""

    def test_no_authorization_never_yields_approved(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(real_generation_authorization=None))

        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)
        self.assertEqual(result.decision, GenerationApprovalDecision.NEEDS_APPROVAL)

    def test_no_authorization_means_create_job_never_called(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)
        service = GenerationJobService(provider, gate)

        with self.assertRaises(GenerationJobExecutionError):
            service.execute(_request(real_generation_authorization=None))

        self.assertEqual(len(provider._jobs), 0)


class TestB_ValidAuthorizationYieldsApproved(unittest.TestCase):
    """Test B — budget suffisant + approved=True + autorisation humaine valide -> APPROVED."""

    def test_valid_authorization_yields_approved(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        request = _request(
            real_generation_authorization=RealGenerationAuthorization(
                request_id="005",
                authorized_by_human=True,
            )
        )
        result = gate.evaluate(request)

        self.assertEqual(result.decision, GenerationApprovalDecision.APPROVED)
        # Toujours MockHiggsfieldProvider : evaluate() seul ne crée jamais de job.
        self.assertEqual(len(provider._jobs), 0)

    def test_valid_authorization_allows_mock_job_execution(self):
        provider = MockHiggsfieldProvider(
            cost_per_job=10.0, available_credits=100.0, succeed_after_polls=1
        )
        gate = GenerationApprovalGate(provider)
        service = GenerationJobService(provider, gate)

        request = _request(
            real_generation_authorization=RealGenerationAuthorization(
                request_id="005",
                authorized_by_human=True,
            )
        )
        outcome = service.execute(request, interval_seconds=0)

        self.assertTrue(outcome.succeeded)
        self.assertEqual(len(provider._jobs), 1)


class TestC_AuthorizationBoundToAnotherRequestNeverApproves(unittest.TestCase):
    """Test C — autorisation valide mais liée à un AUTRE request_id -> NOT APPROVED."""

    def test_mismatched_request_id_never_yields_approved(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        request = _request(
            request_id="005",
            real_generation_authorization=RealGenerationAuthorization(
                request_id="OTHER-REQUEST-ID",
                authorized_by_human=True,
            ),
        )
        result = gate.evaluate(request)

        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)
        self.assertEqual(result.decision, GenerationApprovalDecision.NEEDS_APPROVAL)
        self.assertTrue(
            any("bound to request" in reason for reason in result.reasons)
        )


class TestD_NewRequestHasNoAuthorizationByDefault(unittest.TestCase):
    """Test D — une GenerationRequest nouvellement construite n'est jamais autorisée."""

    def test_default_is_none(self):
        request = GenerationRequest(
            request_id="005",
            job_type="seedance_2_0",
            prompt="prompt de test",
        )

        self.assertIsNone(request.real_generation_authorization)

    def test_setting_approved_alone_does_not_populate_authorization(self):
        request = GenerationRequest(
            request_id="005",
            job_type="seedance_2_0",
            prompt="prompt de test",
            approved=True,
        )

        self.assertIsNone(request.real_generation_authorization)


class TestE_InsufficientBudgetBlocksEvenWithValidAuthorization(unittest.TestCase):
    """Test E — l'autorisation humaine ne contourne JAMAIS un budget insuffisant."""

    def test_blocked_despite_valid_authorization(self):
        provider = MockHiggsfieldProvider(cost_per_job=50.0, available_credits=1.41)
        gate = GenerationApprovalGate(provider)

        request = _request(
            real_generation_authorization=RealGenerationAuthorization(
                request_id="005",
                authorized_by_human=True,
            )
        )
        result = gate.evaluate(request)

        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestF_ReplayProtectionSurvivesAuthorization(unittest.TestCase):
    """Test F — une génération déjà exécutée ne peut pas être réautorisée."""

    def test_already_executed_even_with_fresh_valid_authorization(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        auth = RealGenerationAuthorization(request_id="005", authorized_by_human=True)

        first = gate.evaluate(_request(real_generation_authorization=auth))
        self.assertEqual(first.decision, GenerationApprovalDecision.APPROVED)

        gate.mark_executed("005")

        # Nouvelle autorisation "fraîche", toujours valide et toujours
        # liée à "005" -- ne doit JAMAIS repasser le replay guard.
        fresh_auth = RealGenerationAuthorization(request_id="005", authorized_by_human=True)
        second = gate.evaluate(_request(real_generation_authorization=fresh_auth))

        self.assertEqual(second.decision, GenerationApprovalDecision.ALREADY_EXECUTED)
        self.assertNotEqual(second.decision, GenerationApprovalDecision.APPROVED)


class TestG_RealProviderStillDisabledRegardlessOfAuthorization(unittest.TestCase):
    """
    Test G — HiggsfieldProvider.create_job() (réel) continue de lever
    HiggsfieldRealGenerationDisabledError, MÊME avec budget suffisant +
    approved=True + autorisation humaine valide. Aucun appel réseau
    réel : client factice (MagicMock), comme dans
    tests/test_generation_job_service.py.
    """

    def test_real_create_job_still_disabled_with_full_authorization(self):
        fake_client = MagicMock()
        fake_client.estimate_cost.return_value = {"credits": 10.0}
        fake_client.account_status.return_value = {"credits": 100.0}
        fake_client.get_model.return_value = {
            "job_type": "seedance_2_0",
            "display_name": "d",
            "params": [
                {"name": "prompt", "type": "string", "required": True},
                {"name": "duration", "type": "integer", "required": False, "default": 5},
            ],
        }

        real_provider = HiggsfieldProvider(client=fake_client)
        gate = GenerationApprovalGate(real_provider)
        service = GenerationJobService(real_provider, gate)

        request = _request(
            real_generation_authorization=RealGenerationAuthorization(
                request_id="005",
                authorized_by_human=True,
            )
        )

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            service.execute(request)

        fake_client.create_job.assert_not_called()

    def test_isolated_create_job_call_still_disabled(self):
        # Le garde-fou du Provider réel est inconditionnel : même un
        # appel DIRECT (hors Gate) doit lever l'erreur, sans jamais
        # toucher au client sous-jacent.
        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(job_type="seedance_2_0", prompt="prompt de test")

        fake_client.create_job.assert_not_called()


class TestH_Video005PipelineNonRegression(unittest.TestCase):
    """
    Test H — reconstruit Video 005 via le chemin réel après P2.11 et
    vérifie que le Master Prompt et les assets restent STRICTEMENT
    identiques au gel P2.9/P2.10. Opérations Provider réelles limitées
    au read-only (estimate_cost, get_account_balance) ; aucun
    create_job(), aucune génération réelle.
    """

    EXPECTED_PROMPT_CHARS = 7284
    EXPECTED_PROMPT_LINES = 265
    EXPECTED_PROMPT_SHA256 = (
        "1c498617adb4603bcf2fc114a9cb9e8fe2219f09285adbff4d1e6c7a10a669e1"
    )
    EXPECTED_AVATAR_SHA256 = (
        "d293e41a63f66fd43afbebee3f7f9f1bd29143b465fa57a18ab4e1df5faf7280"
    )
    EXPECTED_FACE_SHA256 = (
        "df83a97b71cff9a90191c19d15ff989228b9fef2e57c96cf7c76c68652e3a343"
    )

    def test_master_prompt_and_assets_unchanged(self):
        import hashlib

        pa = PromptAssemblySystem(PROJECT_ROOT)
        assembled = pa.assemble("005")

        self.assertEqual(len(assembled), self.EXPECTED_PROMPT_CHARS)
        self.assertEqual(len(assembled.splitlines()), self.EXPECTED_PROMPT_LINES)
        self.assertEqual(
            hashlib.sha256(assembled.encode("utf-8")).hexdigest(),
            self.EXPECTED_PROMPT_SHA256,
        )

        aps = AssetPreparationSystem(PROJECT_ROOT)
        assets = {a.role: a for a in aps.scan() if a.status == "READY"}

        self.assertEqual(assets["master_avatar"].sha256, self.EXPECTED_AVATAR_SHA256)
        self.assertEqual(assets["face_reference"].sha256, self.EXPECTED_FACE_SHA256)

    def test_request_built_by_real_chain_has_no_authorization_by_default(self):
        planner = VideoPlanner(PROJECT_ROOT)
        plan = planner.create_zephyr_plan(
            video_id="005", title="t", hook="h", objective="o"
        )
        pa = PromptAssemblySystem(PROJECT_ROOT)
        aps = AssetPreparationSystem(PROJECT_ROOT)
        agent = VideoAgent(prompt_assembly=pa, asset_preparation=aps)

        request = agent.build_request(plan, approved=True)

        # `approved=True` seul, sans autorisation humaine explicite :
        # le champ doit rester None, exactement comme pour n'importe
        # quel autre appelant.
        self.assertIsNone(request.real_generation_authorization)
        self.assertEqual(request.job_type, "seedance_2_0")
        self.assertEqual(request.duration, 15)
        self.assertEqual(request.resolution, "720p")
        self.assertEqual(request.aspect_ratio, "9:16")

    def test_real_chain_request_stays_unapproved_without_authorization_offline(self):
        # Reproduit le comportement du Gate SANS toucher au CLI réel :
        # ce fichier reste, comme tout le reste de la suite, 100%
        # MockHiggsfieldProvider (cf. README : "Tous les tests touchant
        # à la génération vidéo utilisent exclusivement
        # MockHiggsfieldProvider"). La vérification READ-ONLY contre le
        # vrai HiggsfieldProvider (estimate_cost/get_account_balance,
        # jamais create_job) a été effectuée séparément, hors suite
        # automatisée, en Phase P2.9/P2.10.
        planner = VideoPlanner(PROJECT_ROOT)
        plan = planner.create_zephyr_plan(
            video_id="005", title="t", hook="h", objective="o"
        )
        pa = PromptAssemblySystem(PROJECT_ROOT)
        aps = AssetPreparationSystem(PROJECT_ROOT)
        agent = VideoAgent(prompt_assembly=pa, asset_preparation=aps)
        request = agent.build_request(plan, approved=True)

        provider = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=1.41)
        gate = GenerationApprovalGate(provider)
        result = gate.evaluate(request)

        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)
        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)


if __name__ == "__main__":
    unittest.main()
