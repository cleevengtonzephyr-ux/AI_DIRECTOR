"""
Tests — VideoAgent (Phase K, MASTER PROMPT V2).

Le test d'assemblage de prompt utilise le vrai PromptAssemblySystem
sur les assets réels déjà présents dans assets/zephyr/prompts/
(video_005.md) — lecture de fichiers locaux uniquement, aucun appel
réseau ni CLI. Tous les scénarios de génération utilisent
exclusivement MockHiggsfieldProvider.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.final_report_service import FinalReportService, FinalReportStatus
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
)
from tests.authorization_content_helpers import bound_authorization
from agents.asset_preparation_system import AssetPreparationSystem
from agents.planner import VideoPlanner
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.video_agent import DEFAULT_JOB_TYPE, VideoAgent
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider


def _build_plan():
    planner = VideoPlanner(PROJECT_ROOT)
    return planner.create_zephyr_plan(
        video_id="005",
        title="Titre de test",
        hook="Hook de test",
        objective="Objectif de test",
        duration=40,
    )


def _build_plan_with_confirmed_duration():
    """
    Pour les tests d'intégration VideoAgent.run() (mécanique
    d'approbation/exécution, pas la durée elle-même) : utilise 5s,
    seule durée réellement confirmée pour seedance_2_0 (Phase P1.2,
    lecture seule) — 40s serait désormais rejeté par
    GenerationApprovalGate (Phase P1.3), y compris avec un Mock, car
    la table CONFIRMED_DURATIONS_BY_MODEL est indexée par job_type,
    pas par le schéma Mock local.
    """

    planner = VideoPlanner(PROJECT_ROOT)
    return planner.create_zephyr_plan(
        video_id="005",
        title="Titre de test",
        hook="Hook de test",
        objective="Objectif de test",
        duration=5,
    )


class TestVideoAgentBuildRequestWithExplicitPrompt(unittest.TestCase):

    def test_build_request_uses_explicit_prompt(self):
        agent = VideoAgent()
        plan = _build_plan()

        request = agent.build_request(plan, prompt="mon prompt explicite")

        self.assertEqual(request.prompt, "mon prompt explicite")
        self.assertEqual(request.request_id, "005")
        self.assertEqual(request.duration, 40)

    def test_build_request_defaults_job_type_to_seedance_2_0(self):
        agent = VideoAgent()
        plan = _build_plan()

        request = agent.build_request(plan, prompt="p")

        self.assertEqual(request.job_type, DEFAULT_JOB_TYPE)
        self.assertEqual(request.job_type, "seedance_2_0")

    def test_build_request_never_uses_plan_workflow_as_job_type(self):
        # plan.workflow == "cinematic_studio_video_4_0" (V1, WORKFLOW) ;
        # le job_type de la requête (modèle V2) doit rester indépendant.
        agent = VideoAgent()
        plan = _build_plan()
        self.assertEqual(plan.workflow, "cinematic_studio_video_4_0")

        request = agent.build_request(plan, prompt="p")

        self.assertNotEqual(request.job_type, plan.workflow)
        self.assertEqual(request.job_type, "seedance_2_0")

    def test_build_request_allows_overriding_job_type(self):
        agent = VideoAgent()
        plan = _build_plan()

        request = agent.build_request(plan, prompt="p", job_type="kling3_0")

        self.assertEqual(request.job_type, "kling3_0")

    def test_build_request_extracts_resolution_and_aspect_ratio_from_first_scene(self):
        agent = VideoAgent()
        plan = _build_plan()

        request = agent.build_request(plan, prompt="p")

        self.assertEqual(request.resolution, plan.scenes[0].resolution)
        self.assertEqual(request.aspect_ratio, plan.scenes[0].aspect_ratio)

    def test_build_request_defaults_approved_to_false(self):
        agent = VideoAgent()
        plan = _build_plan()

        request = agent.build_request(plan, prompt="p")

        self.assertFalse(request.approved)

    def test_build_request_raises_without_prompt_or_assembly_system(self):
        agent = VideoAgent()  # pas de PromptAssemblySystem configuré
        plan = _build_plan()

        with self.assertRaises(ValueError):
            agent.build_request(plan)


class TestVideoAgentPromptAssemblyIntegration(unittest.TestCase):
    """Intégration réelle avec PromptAssemblySystem (V1) — fichiers locaux uniquement."""

    def test_build_request_uses_prompt_assembly_system_when_no_prompt_given(self):
        prompt_assembly = PromptAssemblySystem(PROJECT_ROOT)
        agent = VideoAgent(prompt_assembly=prompt_assembly)
        plan = _build_plan()

        request = agent.build_request(plan)

        expected_prompt = prompt_assembly.assemble("005")
        self.assertEqual(request.prompt, expected_prompt)
        self.assertIn("ZEPHYR AI — MASTER PRODUCTION PROMPT", request.prompt)


class TestVideoAgentRun(unittest.TestCase):
    """run() délègue intégralement à FinalReportService (Phase J)."""

    def test_run_never_auto_approves(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)
        report_service = FinalReportService(provider, gate)
        agent = VideoAgent()
        plan = _build_plan_with_confirmed_duration()

        report = agent.run(plan, report_service, prompt="p")  # approved=False par défaut

        self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)
        self.assertEqual(
            report.approval_decision, GenerationApprovalDecision.NEEDS_APPROVAL
        )
        self.assertEqual(len(provider._jobs), 0)

    def test_run_with_explicit_approval_produces_executed_pass(self):
        provider = MockHiggsfieldProvider(
            cost_per_job=10.0, available_credits=100.0, succeed_after_polls=2
        )
        gate = GenerationApprovalGate(provider)
        report_service = FinalReportService(provider, gate)
        # Phase B : l'autorisation doit être liée au contenu exact
        # (prompt + avatar + référence visage) -- l'agent puise donc
        # les assets réels (lecture seule), et l'autorisation est liée
        # à la requête qu'il construira.
        agent = VideoAgent(asset_preparation=AssetPreparationSystem(PROJECT_ROOT))
        plan = _build_plan_with_confirmed_duration()
        authorization = bound_authorization(
            agent.build_request(plan, prompt="p", approved=True)
        )

        report = agent.run(
            plan,
            report_service,
            prompt="p",
            approved=True,
            # Phase P2.11 : deuxième verrou requis en plus d'`approved`.
            real_generation_authorization=authorization,
            interval_seconds=0,
        )

        self.assertEqual(report.status, FinalReportStatus.EXECUTED_PASS)
        self.assertTrue(report.job_created)

    def test_run_blocked_on_insufficient_budget(self):
        provider = MockHiggsfieldProvider(cost_per_job=50.0, available_credits=1.41)
        gate = GenerationApprovalGate(provider)
        report_service = FinalReportService(provider, gate)
        agent = VideoAgent()
        plan = _build_plan_with_confirmed_duration()

        report = agent.run(plan, report_service, prompt="p", approved=True)

        self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)
        self.assertEqual(report.approval_decision, GenerationApprovalDecision.BLOCKED)


class TestVideoAgentNoCliDependency(unittest.TestCase):

    def test_module_has_no_cli_or_network_dependency(self):
        import inspect

        import agents.video_agent as module

        imported_names = {
            name
            for name, value in vars(module).items()
            if inspect.ismodule(value) or inspect.isclass(value)
        }

        self.assertNotIn("HiggsfieldClient", imported_names)
        self.assertFalse(hasattr(module, "subprocess"))
        self.assertFalse(hasattr(module, "requests"))
        self.assertFalse(hasattr(module, "socket"))


if __name__ == "__main__":
    unittest.main()
