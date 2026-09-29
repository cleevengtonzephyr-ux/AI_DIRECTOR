"""
Tests — FinalReportService (Phase J, MASTER PROMPT V2).

Tous les scénarios de génération utilisent EXCLUSIVEMENT
MockHiggsfieldProvider. Une attention particulière est portée à la
règle absolue de la Phase J : un rapport ne doit JAMAIS représenter
une génération comme réussie si elle n'a pas été exécutée, et la
protection réelle (Phase C/D) ne doit jamais être contournée ni
masquée par ce nouveau composant.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.final_report_service import (
    FinalReport,
    FinalReportService,
    FinalReportStatus,
)
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from tests.authorization_content_helpers import bind_request, content_media
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider


def _request(**overrides) -> GenerationRequest:
    """
    Phase P2.11 : sauf override explicite (y compris `None`), une
    autorisation humaine valide liée au `request_id` effectif est
    fournie par défaut — ces tests portent sur FinalReportService, pas
    sur le verrou d'autorisation humaine lui-même.
    """

    defaults = dict(
        **content_media(),
        request_id="req-1",
        job_type="seedance_2_0",
        prompt="prompt de test",
        duration=5,
        resolution="720p",
        aspect_ratio="9:16",
        approved=True,
    )
    defaults.update(overrides)

    if "real_generation_authorization" not in overrides:
        defaults["real_generation_authorization"] = RealGenerationAuthorization(
            request_id=defaults["request_id"],
            authorized_by_human=True,
        )

    return bind_request(GenerationRequest(**defaults))


class TestFinalReportNeverFakesSuccess(unittest.TestCase):
    """Règle absolue de la Phase J : jamais de succès simulé."""

    def test_blocked_budget_produces_not_executed_report(self):
        provider = MockHiggsfieldProvider(cost_per_job=50.0, available_credits=1.41)
        service = FinalReportService(provider, GenerationApprovalGate(provider))

        report = service.generate(_request(approved=True))

        self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)
        self.assertFalse(report.job_created)
        self.assertFalse(report.succeeded)
        self.assertIsNone(report.job_id)
        self.assertEqual(report.output_urls, tuple())
        self.assertIsNone(report.quality_decision)
        self.assertEqual(report.approval_decision, GenerationApprovalDecision.BLOCKED)

    def test_needs_approval_produces_not_executed_report(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        service = FinalReportService(provider, GenerationApprovalGate(provider))

        report = service.generate(_request(approved=False))

        self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)
        self.assertFalse(report.job_created)
        self.assertEqual(
            report.approval_decision, GenerationApprovalDecision.NEEDS_APPROVAL
        )

    def test_invalid_request_produces_not_executed_report(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        service = FinalReportService(provider, GenerationApprovalGate(provider))

        report = service.generate(_request(prompt="   "))

        self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)
        self.assertEqual(
            report.approval_decision, GenerationApprovalDecision.INVALID_REQUEST
        )

    def test_already_executed_produces_not_executed_report_not_a_second_success(self):
        provider = MockHiggsfieldProvider(
            cost_per_job=10.0, available_credits=100.0, succeed_after_polls=1
        )
        gate = GenerationApprovalGate(provider)
        service = FinalReportService(provider, gate)

        first = service.generate(_request(), interval_seconds=0)
        self.assertEqual(first.status, FinalReportStatus.EXECUTED_PASS)

        second = service.generate(_request(), interval_seconds=0)

        self.assertEqual(second.status, FinalReportStatus.NOT_EXECUTED)
        self.assertFalse(second.job_created)
        self.assertEqual(
            second.approval_decision, GenerationApprovalDecision.ALREADY_EXECUTED
        )
        # Un seul job réel doit exister malgré les deux rapports générés.
        self.assertEqual(len(provider._jobs), 1)

    def test_not_executed_status_is_disjoint_from_executed_statuses(self):
        self.assertNotIn(
            FinalReportStatus.NOT_EXECUTED,
            (
                FinalReportStatus.EXECUTED_PASS,
                FinalReportStatus.EXECUTED_FAIL,
                FinalReportStatus.EXECUTED_RETRY_RECOMMENDED,
            ),
        )


class TestFinalReportExecutedOutcomes(unittest.TestCase):

    def test_successful_generation_produces_executed_pass_report(self):
        provider = MockHiggsfieldProvider(
            cost_per_job=10.0, available_credits=100.0, succeed_after_polls=2
        )
        service = FinalReportService(provider, GenerationApprovalGate(provider))

        report = service.generate(_request(), interval_seconds=0)

        self.assertIsInstance(report, FinalReport)
        self.assertEqual(report.status, FinalReportStatus.EXECUTED_PASS)
        self.assertTrue(report.job_created)
        self.assertTrue(report.succeeded)
        self.assertIsNotNone(report.job_id)
        self.assertEqual(len(report.output_urls), 1)
        self.assertEqual(report.estimated_credits, 10.0)

    def test_timeout_produces_executed_retry_recommended_report(self):
        provider = MockHiggsfieldProvider(
            cost_per_job=10.0,
            available_credits=100.0,
            succeed_after_polls=1_000_000,
        )
        service = FinalReportService(provider, GenerationApprovalGate(provider))

        report = service.generate(_request(), timeout_seconds=0, interval_seconds=0)

        self.assertEqual(report.status, FinalReportStatus.EXECUTED_RETRY_RECOMMENDED)
        self.assertTrue(report.job_created)
        self.assertFalse(report.succeeded)


class TestFinalReportNeverBypassesRealProtection(unittest.TestCase):
    """
    La protection réelle (Phase C/D) doit se propager telle quelle
    hors de generate() — jamais interceptée pour produire un faux
    rapport NOT_EXECUTED "propre" à la place.
    """

    def test_real_provider_protection_propagates_uncaught(self):
        fake_client = MagicMock()
        fake_client.estimate_cost.return_value = {"credits": 10.0}
        fake_client.account_status.return_value = {"credits": 100.0}
        fake_client.get_model.return_value = {
            "job_type": "seedance_2_0",
            "display_name": "d",
            "params": [
                {"name": "prompt", "type": "string", "required": True},
                {"name": "duration", "type": "integer", "required": False, "default": 5},
                {"name": "start_image", "type": "object|null", "required": False},
                {"name": "image_references", "type": "array", "required": False},
            ],
        }

        real_provider = HiggsfieldProvider(client=fake_client)
        service = FinalReportService(real_provider, GenerationApprovalGate(real_provider))

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            service.generate(_request(approved=True))

        fake_client.create_job.assert_not_called()

    def test_module_has_no_cli_or_network_dependency(self):
        import inspect

        import agents.final_report_service as module

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
