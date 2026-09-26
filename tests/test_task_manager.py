"""
Tests — TaskManager (Phase M, MASTER PROMPT V2).

Tous les scénarios de génération utilisent EXCLUSIVEMENT un
report_service injecté (MockHiggsfieldProvider) via AIDirector. Un
test dédié vérifie que la protection réelle (Phase C/D) n'est jamais
avalée par TaskManager.process() : elle doit marquer la tâche en
ERROR puis se propager, jamais être convertie en simple échec routinier.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.final_report_service import FinalReportService, FinalReportStatus
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    RealGenerationAuthorization,
)
from agents.task_manager import TaskManager, TaskStatus
from director import AIDirector
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider

# Seule durée réellement confirmée pour seedance_2_0 (Phase P1.2,
# lecture seule) : la table CONFIRMED_DURATIONS_BY_MODEL du Gate
# (Phase P1.3) est indexée par job_type, pas par un schéma Mock local
# — un plan à 40s (TaskRecord.duration par défaut) serait désormais
# rejeté (INVALID_REQUEST), y compris avec un Mock personnalisé. Ces
# tests portent sur la mécanique de dispatch, pas sur la durée : on
# utilise donc explicitement 5s.
CONFIRMED_DURATION = 5


def _mock_report_service(**mock_kwargs) -> FinalReportService:
    provider = MockHiggsfieldProvider(**mock_kwargs)
    gate = GenerationApprovalGate(provider)
    return FinalReportService(provider, gate)


class TestTaskManagerSubmission(unittest.TestCase):

    def test_submit_creates_pending_task_with_predictable_id(self):
        manager = TaskManager()

        task1 = manager.submit(video_id="005", title="t1", hook="h1", objective="o1")
        task2 = manager.submit(video_id="005", title="t2", hook="h2", objective="o2")

        self.assertEqual(task1.task_id, "task-1")
        self.assertEqual(task2.task_id, "task-2")
        self.assertEqual(task1.status, TaskStatus.PENDING)
        self.assertIsNone(task1.report)

    def test_submit_duplicate_task_id_raises(self):
        manager = TaskManager()
        manager.submit(video_id="005", title="t", hook="h", objective="o", task_id="fixed")

        with self.assertRaises(ValueError):
            manager.submit(
                video_id="005", title="t", hook="h", objective="o", task_id="fixed"
            )

    def test_get_task_unknown_raises(self):
        manager = TaskManager()

        with self.assertRaises(KeyError):
            manager.get_task("does-not-exist")

    def test_list_tasks_reflects_all_submitted_tasks(self):
        manager = TaskManager()
        manager.submit(video_id="005", title="t1", hook="h", objective="o")
        manager.submit(video_id="005", title="t2", hook="h", objective="o")

        self.assertEqual(len(manager.list_tasks()), 2)

    def test_submit_never_estimates_or_executes_anything(self):
        # submit() est une opération purement locale — aucune
        # génération, aucune estimation.
        manager = TaskManager()
        task = manager.submit(video_id="005", title="t", hook="h", objective="o")

        self.assertEqual(task.status, TaskStatus.PENDING)
        self.assertIsNone(task.report)


class TestTaskManagerProcessNeverAutoApproves(unittest.TestCase):

    def test_process_without_approval_yields_not_executed_but_processed_status(self):
        manager = TaskManager()
        task = manager.submit(
            video_id="005", title="t", hook="h", objective="o",
            duration=CONFIRMED_DURATION,
        )
        director = AIDirector()
        report_service = _mock_report_service(cost_per_job=10.0, available_credits=100.0)

        report = manager.process(task.task_id, director, report_service=report_service)

        self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)
        self.assertEqual(
            report.approval_decision, GenerationApprovalDecision.NEEDS_APPROVAL
        )
        # La FILE considère la tâche "traitée" (un rapport existe),
        # même si le pipeline lui-même n'a rien exécuté.
        self.assertEqual(task.status, TaskStatus.PROCESSED)
        self.assertIs(task.report, report)


class TestTaskManagerProcessExecutedOutcomes(unittest.TestCase):

    def test_process_with_explicit_approval_succeeds(self):
        manager = TaskManager()
        task = manager.submit(
            video_id="005", title="t", hook="h", objective="o",
            duration=CONFIRMED_DURATION,
        )
        director = AIDirector()
        report_service = _mock_report_service(
            cost_per_job=10.0, available_credits=100.0, succeed_after_polls=2
        )

        report = manager.process(
            task.task_id,
            director,
            approved=True,
            # Phase P2.11 : deuxième verrou requis en plus d'`approved`.
            real_generation_authorization=RealGenerationAuthorization(
                request_id=task.video_id,
                authorized_by_human=True,
            ),
            report_service=report_service,
            interval_seconds=0,
        )

        self.assertEqual(report.status, FinalReportStatus.EXECUTED_PASS)
        self.assertEqual(task.status, TaskStatus.PROCESSED)

    def test_process_blocked_on_insufficient_budget(self):
        manager = TaskManager()
        task = manager.submit(
            video_id="005", title="t", hook="h", objective="o",
            duration=CONFIRMED_DURATION,
        )
        director = AIDirector()
        report_service = _mock_report_service(cost_per_job=50.0, available_credits=1.41)

        report = manager.process(
            task.task_id, director, approved=True, report_service=report_service
        )

        self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)
        self.assertEqual(report.approval_decision, GenerationApprovalDecision.BLOCKED)
        self.assertEqual(task.status, TaskStatus.PROCESSED)


class TestTaskManagerProcessNextPending(unittest.TestCase):

    def test_process_next_pending_processes_oldest_first_and_skips_processed(self):
        manager = TaskManager()
        task1 = manager.submit(video_id="005", title="t1", hook="h", objective="o")
        task2 = manager.submit(video_id="005", title="t2", hook="h", objective="o")
        director = AIDirector()
        report_service = _mock_report_service(cost_per_job=10.0, available_credits=100.0)

        first_report = manager.process_next_pending(director, report_service=report_service)
        self.assertIs(task1.report, first_report)
        self.assertEqual(task1.status, TaskStatus.PROCESSED)
        self.assertEqual(task2.status, TaskStatus.PENDING)

        second_report = manager.process_next_pending(director, report_service=report_service)
        self.assertIs(task2.report, second_report)

        # Plus aucune tâche PENDING.
        self.assertIsNone(manager.process_next_pending(director, report_service=report_service))


class TestTaskManagerNeverSwallowsRealProtection(unittest.TestCase):
    """
    La protection réelle (Phase C/D) doit se propager : process()
    marque la tâche en ERROR mais RE-LÈVE l'exception — jamais
    convertie silencieusement en un simple rapport d'échec.
    """

    def test_real_provider_protection_marks_error_and_reraises(self):
        fake_client = MagicMock()
        fake_client.estimate_cost.return_value = {"credits": 10.0}
        fake_client.account_status.return_value = {"credits": 100.0}
        fake_client.get_model.return_value = {
            "job_type": "seedance_2_0",
            "display_name": "d",
            "params": [
                {"name": "prompt", "type": "string", "required": True},
                {"name": "duration", "type": "integer", "required": False, "default": 5},
                # start_image/image_references (Phase P2.7) : le VRAI
                # schéma seedance_2_0 les déclare (cf. REAL_SEEDANCE_SCHEMA,
                # tests/test_phase_p1_readiness.py). AIDirector attache
                # désormais réellement ces références (Phase P2.7) ; sans
                # elles ici, GenerationApprovalGate rejetterait la requête
                # en INVALID_REQUEST avant même d'atteindre le vrai
                # create_job(), ce que ce test ne veut PAS vérifier — il
                # vérifie spécifiquement le garde-fou
                # HiggsfieldRealGenerationDisabledError.
                {"name": "start_image", "type": "object|null", "required": False, "default": None},
                {"name": "image_references", "type": "array", "required": False, "default": None},
            ],
        }

        real_provider = HiggsfieldProvider(client=fake_client)
        gate = GenerationApprovalGate(real_provider)
        report_service = FinalReportService(real_provider, gate)

        manager = TaskManager()
        task = manager.submit(
            video_id="005", title="t", hook="h", objective="o",
            duration=CONFIRMED_DURATION,
        )
        director = AIDirector()

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            manager.process(
                task.task_id,
                director,
                approved=True,
                # Phase P2.11 : sans ce second verrou, le Gate
                # renverrait NEEDS_APPROVAL avant même d'atteindre le
                # vrai create_job() — ce que ce test ne veut PAS
                # vérifier ; il vérifie spécifiquement que même
                # APPROVED (budget + approved + autorisation humaine)
                # n'atteint jamais une génération réelle.
                real_generation_authorization=RealGenerationAuthorization(
                    request_id=task.video_id,
                    authorized_by_human=True,
                ),
                report_service=report_service,
            )

        self.assertEqual(task.status, TaskStatus.ERROR)
        self.assertIsNone(task.report)
        fake_client.create_job.assert_not_called()


class TestTaskManagerNoCliDependency(unittest.TestCase):

    def test_module_has_no_cli_or_network_dependency(self):
        import inspect

        import agents.task_manager as module

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
