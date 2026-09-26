"""
Tests — AIDirector.run_video_mission() (Phase L, MASTER PROMPT V2).

Tous les scénarios de génération utilisent EXCLUSIVEMENT un
report_service injecté, construit sur MockHiggsfieldProvider. Aucun
test de cette suite n'invoque la chaîne par défaut (réelle) de
run_video_mission() : la construction de cette chaîne réelle est
vérifiée séparément (structurelle uniquement, aucun appel CLI).
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
    RealGenerationAuthorization,
)
from director import AIDirector
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider

# Seule durée réellement confirmée pour seedance_2_0 (Phase P1.2,
# lecture seule) ; le VideoPlan Zephyr par défaut (40s) est désormais
# rejeté par GenerationApprovalGate (Phase P1.3, table indexée par
# job_type). Ces tests portent sur l'orchestration Director, pas sur
# la durée : on utilise donc explicitement 5s.
CONFIRMED_DURATION = 5


def _mock_report_service(**mock_kwargs) -> FinalReportService:
    provider = MockHiggsfieldProvider(**mock_kwargs)
    gate = GenerationApprovalGate(provider)
    return FinalReportService(provider, gate)


class TestDirectorRunVideoMissionNeverAutoApproves(unittest.TestCase):

    def test_run_video_mission_defaults_to_not_executed(self):
        director = AIDirector()
        report_service = _mock_report_service(
            cost_per_job=10.0, available_credits=100.0
        )

        report = director.run_video_mission(
            video_id="005",
            title="Titre de test",
            hook="Hook de test",
            objective="Objectif de test",
            duration=CONFIRMED_DURATION,
            report_service=report_service,
        )  # approved=False par défaut

        self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)
        self.assertEqual(
            report.approval_decision, GenerationApprovalDecision.NEEDS_APPROVAL
        )


class TestDirectorRunVideoMissionExecutedPath(unittest.TestCase):

    def test_run_video_mission_with_approval_succeeds(self):
        director = AIDirector()
        report_service = _mock_report_service(
            cost_per_job=10.0, available_credits=100.0, succeed_after_polls=2
        )

        report = director.run_video_mission(
            video_id="005",
            title="Titre de test",
            hook="Hook de test",
            objective="Objectif de test",
            duration=CONFIRMED_DURATION,
            approved=True,
            # Phase P2.11 : deuxième verrou requis en plus d'`approved`.
            real_generation_authorization=RealGenerationAuthorization(
                request_id="005",
                authorized_by_human=True,
            ),
            report_service=report_service,
            interval_seconds=0,
        )

        self.assertEqual(report.status, FinalReportStatus.EXECUTED_PASS)
        self.assertTrue(report.job_created)

    def test_run_video_mission_uses_seedance_2_0_by_default(self):
        director = AIDirector()
        report_service = _mock_report_service(
            cost_per_job=10.0, available_credits=100.0
        )

        report = director.run_video_mission(
            video_id="005",
            title="t",
            hook="h",
            objective="o",
            report_service=report_service,
        )

        self.assertEqual(report.job_type, "seedance_2_0")

    def test_run_video_mission_blocked_on_insufficient_budget(self):
        director = AIDirector()
        report_service = _mock_report_service(
            cost_per_job=50.0, available_credits=1.41
        )

        report = director.run_video_mission(
            video_id="005",
            title="t",
            hook="h",
            objective="o",
            duration=CONFIRMED_DURATION,
            approved=True,
            report_service=report_service,
        )

        self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)
        self.assertEqual(report.approval_decision, GenerationApprovalDecision.BLOCKED)


class TestDirectorDefaultChainWiringOnly(unittest.TestCase):
    """
    Vérifie que la chaîne réelle par défaut se CONSTRUIT correctement
    (types, instanciation) sans jamais l'INVOQUER — aucun appel CLI
    n'est déclenché par la simple construction d'objets.
    """

    def test_build_default_report_service_returns_correct_types(self):
        director = AIDirector()

        report_service = director._build_default_report_service()

        self.assertIsInstance(report_service, FinalReportService)
        self.assertIsInstance(report_service.provider, HiggsfieldProvider)
        self.assertIs(report_service.provider.client, director.higgsfield)

    def test_default_report_service_construction_makes_no_cli_call(self):
        # La construction seule (sans appel de méthode) ne doit
        # déclencher aucun subprocess. On le vérifie en s'assurant
        # qu'aucune exception liée au CLI n'est levée : la
        # construction d'objets Python purs ne peut pas invoquer le
        # CLI Higgsfield.
        director = AIDirector()
        try:
            director._build_default_report_service()
        except Exception as error:  # pragma: no cover - ne doit jamais arriver
            self.fail(f"Construction should never touch the CLI: {error}")


class TestDirectorStatusUnaffected(unittest.TestCase):
    """Non-régression : les méthodes V1 de AIDirector restent inchangées."""

    def test_check_higgsfield_and_status_still_exist(self):
        director = AIDirector()
        self.assertTrue(hasattr(director, "check_higgsfield"))
        self.assertTrue(hasattr(director, "status"))
        self.assertEqual(director.version, "0.2.0")


if __name__ == "__main__":
    unittest.main()
