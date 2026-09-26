"""
Tests — Phase P1 / P1.1 : préparation de la première génération réelle
supervisée, correction des références visuelles et recalcul du coût.

Aucun test de ce fichier n'appelle le CLI réel ni ne consomme de
crédit : tout repose sur MockHiggsfieldProvider ou un HiggsfieldClient
factice (MagicMock, zéro subprocess) reproduisant les valeurs réelles
observées (coût=22.5 pour une durée confirmée de 5s, solde=1.41).

Deux variantes du scénario Zephyr AI sont utilisées :
- `_build_p1_request()`            : duration=40 (le VideoPlan Zephyr
  réel) — NON confirmée par le schéma réel de seedance_2_0.
- `_build_p1_request_confirmed()`  : duration=5 (le seul défaut
  réellement confirmé par l'API) — utilisée pour isoler les tests de
  budget/approbation de la question de la durée.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.asset_preparation_system import AssetPreparationSystem
from agents.final_report_service import FinalReportService, FinalReportStatus
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
)
from agents.planner import VideoPlanner
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.task_manager import TaskManager
from agents.video_agent import VideoAgent
from director import AIDirector
from integrations.higgsfield.provider import HiggsfieldProvider

# Schéma factice reproduisant le VRAI seedance_2_0 (Phase P1.1,
# `model get seedance_2_0` réel) : duration confirmée = 5 uniquement,
# start_image/image_references déclarés supportés.
REAL_SEEDANCE_SCHEMA = {
    "job_type": "seedance_2_0",
    "display_name": "Seedance 2.0",
    "params": [
        {"name": "prompt", "type": "string", "required": True, "default": None},
        {"name": "duration", "type": "integer", "required": False, "default": 5},
        {"name": "start_image", "type": "object|null", "required": False, "default": None},
        {"name": "image_references", "type": "array", "required": False, "default": None},
    ],
}

# Schéma factice d'un modèle plus limité, sans support média — utilisé
# pour prouver qu'une capacité non déclarée est bien refusée.
MINIMAL_SCHEMA_NO_MEDIA = {
    "job_type": "seedance_2_0",
    "display_name": "Seedance 2.0 (minimal)",
    "params": [
        {"name": "prompt", "type": "string", "required": True, "default": None},
        {"name": "duration", "type": "integer", "required": False, "default": 5},
    ],
}


def _build_plan(duration: int):
    planner = VideoPlanner(PROJECT_ROOT)
    return planner.create_zephyr_plan(
        video_id="005",
        title="Zephyr AI - Premiere generation supervisee (P1)",
        hook="Le talent impressionne. La discipline construit des empires.",
        objective="Video courte, cinematique, motivante.",
        duration=duration,
    )


def _build_p1_request(asset_preparation=None):
    """Scénario réel Zephyr : duration=40, NON confirmée."""

    plan = _build_plan(duration=40)
    prompt_assembly = PromptAssemblySystem(PROJECT_ROOT)
    agent = VideoAgent(
        prompt_assembly=prompt_assembly,
        asset_preparation=asset_preparation,
    )
    return plan, agent.build_request(plan)


def _build_p1_request_confirmed(asset_preparation=None):
    """Même scénario, avec la durée réellement confirmée (5s)."""

    plan = _build_plan(duration=5)
    prompt_assembly = PromptAssemblySystem(PROJECT_ROOT)
    agent = VideoAgent(
        prompt_assembly=prompt_assembly,
        asset_preparation=asset_preparation,
    )
    return plan, agent.build_request(plan)


def _fake_provider(schema: dict, cost: float, balance: float):
    fake_client = MagicMock()
    fake_client.estimate_cost.return_value = {"credits": cost}
    fake_client.account_status.return_value = {"credits": balance}
    fake_client.get_model.return_value = schema
    return HiggsfieldProvider(client=fake_client), fake_client


class TestPhaseP1PayloadIsWellFormed(unittest.TestCase):

    def test_p1_request_matches_the_validated_scenario(self):
        _, request = _build_p1_request()

        self.assertEqual(request.request_id, "005")
        self.assertEqual(request.job_type, "seedance_2_0")
        self.assertEqual(request.resolution, "720p")
        self.assertEqual(request.aspect_ratio, "9:16")
        self.assertEqual(request.duration, 40)
        self.assertFalse(request.approved)
        self.assertGreater(len(request.prompt), 0)


class TestPhaseP1MediaReferencesArePropagated(unittest.TestCase):
    """1 & 2 : les assets READY sont propagés jusqu'au request, sans perte."""

    def test_ready_assets_are_propagated_to_the_request(self):
        asset_preparation = AssetPreparationSystem(PROJECT_ROOT)
        _, request = _build_p1_request_confirmed(asset_preparation=asset_preparation)

        self.assertIsNotNone(request.start_image)
        self.assertEqual(request.start_image.role, "master_avatar")
        self.assertTrue(request.start_image.source.endswith("avatar_master.png"))
        self.assertIsNotNone(request.start_image.sha256)

        self.assertEqual(len(request.image_references), 1)
        self.assertEqual(request.image_references[0].role, "face_reference")
        self.assertTrue(
            request.image_references[0].source.endswith("mon avatar habille.png")
        )

    def test_references_survive_from_asset_preparation_to_gate_evaluation(self):
        # Les références ne sont PAS perdues entre AssetPreparation et
        # le Provider : un modèle qui les supporte laisse passer la
        # validation (le blocage éventuel vient alors du budget, pas
        # d'une perte de référence).
        asset_preparation = AssetPreparationSystem(PROJECT_ROOT)
        _, request = _build_p1_request_confirmed(asset_preparation=asset_preparation)

        provider, fake_client = _fake_provider(
            REAL_SEEDANCE_SCHEMA, cost=22.5, balance=1000.0
        )
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(request)

        self.assertNotEqual(result.decision, GenerationApprovalDecision.INVALID_REQUEST)
        fake_client.create_job.assert_not_called()

    def test_audio_asset_is_never_included(self):
        asset_preparation = AssetPreparationSystem(PROJECT_ROOT)
        _, request = _build_p1_request_confirmed(asset_preparation=asset_preparation)

        all_sources = [request.start_image.source] + [
            ref.source for ref in request.image_references
        ]
        self.assertFalse(any("voice_main" in source for source in all_sources))

    def test_no_asset_preparation_configured_means_no_media_references(self):
        _, request = _build_p1_request_confirmed(asset_preparation=None)

        self.assertIsNone(request.start_image)
        self.assertEqual(request.image_references, tuple())


class TestPhaseP1RejectsUnsupportedCapabilities(unittest.TestCase):
    """3 & 4 : références/capacités non supportées par le modèle -> refusées."""

    def test_start_image_rejected_when_model_does_not_support_it(self):
        asset_preparation = AssetPreparationSystem(PROJECT_ROOT)
        _, request = _build_p1_request_confirmed(asset_preparation=asset_preparation)

        provider, fake_client = _fake_provider(
            MINIMAL_SCHEMA_NO_MEDIA, cost=22.5, balance=1000.0
        )
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(request)

        self.assertEqual(result.decision, GenerationApprovalDecision.INVALID_REQUEST)
        self.assertTrue(
            any("does not support start_image" in reason for reason in result.reasons)
        )
        fake_client.create_job.assert_not_called()

    def test_image_references_rejected_when_model_does_not_support_them(self):
        asset_preparation = AssetPreparationSystem(PROJECT_ROOT)
        _, request = _build_p1_request_confirmed(asset_preparation=asset_preparation)

        provider, fake_client = _fake_provider(
            MINIMAL_SCHEMA_NO_MEDIA, cost=22.5, balance=1000.0
        )
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(request)

        self.assertTrue(
            any(
                "does not support image_references" in reason
                for reason in result.reasons
            )
        )
        fake_client.create_job.assert_not_called()


class TestPhaseP1UnverifiedDurationIsInvalid(unittest.TestCase):
    """5 : une durée non confirmée n'est jamais considérée comme valide."""

    def test_duration_40_is_invalid_against_the_real_schema(self):
        _, request = _build_p1_request()  # duration=40

        provider, fake_client = _fake_provider(
            REAL_SEEDANCE_SCHEMA, cost=22.5, balance=1000.0
        )
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(request)

        self.assertEqual(result.decision, GenerationApprovalDecision.INVALID_REQUEST)
        self.assertTrue(any("UNVERIFIED" in reason for reason in result.reasons))
        fake_client.create_job.assert_not_called()
        fake_client.estimate_cost.assert_not_called()  # court-circuit avant le cout

    def test_duration_5_matches_the_confirmed_default(self):
        _, request = _build_p1_request_confirmed()  # duration=5

        provider, fake_client = _fake_provider(
            REAL_SEEDANCE_SCHEMA, cost=22.5, balance=1000.0
        )
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(request)

        self.assertNotEqual(result.decision, GenerationApprovalDecision.INVALID_REQUEST)


class TestPhaseP1CostCalculatedBeforeGeneration(unittest.TestCase):
    """6 : le coût est calculé avant toute génération — jamais si la requête est invalide."""

    def test_cost_is_estimated_when_request_is_valid(self):
        _, request = _build_p1_request_confirmed()

        provider, fake_client = _fake_provider(
            REAL_SEEDANCE_SCHEMA, cost=22.5, balance=1000.0
        )
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(request)

        fake_client.estimate_cost.assert_called_once()
        self.assertIsNotNone(result.cost_result)
        self.assertEqual(result.cost_result.estimate.credits, 22.5)

    def test_cost_is_never_estimated_when_duration_is_unverified(self):
        _, request = _build_p1_request()  # duration=40, non confirmee

        provider, fake_client = _fake_provider(
            REAL_SEEDANCE_SCHEMA, cost=22.5, balance=1000.0
        )
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(request)

        fake_client.estimate_cost.assert_not_called()
        self.assertIsNone(result.cost_result)


class TestPhaseP1NeverReachesCreateJobWithRealBalance(unittest.TestCase):
    """
    Reproduit les valeurs réelles observées en Phase P1 (coût=22.5,
    solde=1.41) avec une durée CONFIRMÉE (5s) afin d'isoler le
    blocage budgétaire de la question de la durée.
    """

    def setUp(self):
        self.provider, self.fake_client = _fake_provider(
            REAL_SEEDANCE_SCHEMA, cost=22.5, balance=1.41
        )
        self.gate = GenerationApprovalGate(self.provider)
        self.report_service = FinalReportService(self.provider, self.gate)
        self.director = AIDirector()
        self.task_manager = TaskManager()

    def test_scenario_is_blocked_on_real_observed_balance(self):
        _, request = _build_p1_request_confirmed()

        report = self.report_service.generate(request)

        self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)
        self.assertEqual(report.approval_decision, GenerationApprovalDecision.BLOCKED)
        self.assertIn("Insufficient credits", report.approval_reasons[0])
        self.assertFalse(report.job_created)

    def test_create_job_never_called_even_with_approved_true(self):
        _, request = _build_p1_request_confirmed()
        approved_request = type(request)(**{**request.__dict__, "approved": True})

        report = self.report_service.generate(approved_request)

        self.assertEqual(report.approval_decision, GenerationApprovalDecision.BLOCKED)
        self.fake_client.create_job.assert_not_called()

    def test_task_manager_path_also_never_calls_create_job(self):
        task = self.task_manager.submit(
            video_id="005",
            title="Zephyr AI - Premiere generation supervisee (P1)",
            hook="Le talent impressionne. La discipline construit des empires.",
            objective="Video courte, cinematique, motivante.",
            duration=5,
        )

        report = self.task_manager.process(
            task.task_id,
            self.director,
            approved=False,
            report_service=self.report_service,
        )

        self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)
        self.fake_client.create_job.assert_not_called()


class TestPhaseP1RequiresExplicitApprovalEvenWithSufficientBudget(unittest.TestCase):
    """
    Avec un solde HYPOTHETIQUEMENT suffisant (simulé) et une durée
    confirmée, seul le défaut d'approbation explicite bloque encore
    la génération.
    """

    def setUp(self):
        self.provider, self.fake_client = _fake_provider(
            REAL_SEEDANCE_SCHEMA, cost=22.5, balance=1000.0
        )
        self.gate = GenerationApprovalGate(self.provider)
        self.report_service = FinalReportService(self.provider, self.gate)

    def test_needs_approval_without_explicit_approval(self):
        _, request = _build_p1_request_confirmed()

        report = self.report_service.generate(request)

        self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)
        self.assertEqual(
            report.approval_decision, GenerationApprovalDecision.NEEDS_APPROVAL
        )
        self.fake_client.create_job.assert_not_called()


if __name__ == "__main__":
    unittest.main()
