"""
Tests — GenerationJobService (Phase H, MASTER PROMPT V2).

Tous les scénarios de génération utilisent EXCLUSIVEMENT
MockHiggsfieldProvider (aucun CLI réel, aucun réseau, aucun crédit
consommé). Un test dédié vérifie explicitement que la protection
réelle (HiggsfieldRealGenerationDisabledError, Phase C/D) reste
intacte et n'est jamais contournée par ce nouveau service — en
utilisant le vrai HiggsfieldProvider avec un faux HiggsfieldClient
(aucun subprocess, comme dans test_higgsfield_provider.py).
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from agents.generation_job_service import (
    GenerationJobExecutionError,
    GenerationJobOutcome,
    GenerationJobService,
)
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider
from integrations.higgsfield.types import JobStatus, VideoResult


def _request(**overrides) -> GenerationRequest:
    """
    Phase P2.11 : sauf override explicite (y compris `None`), une
    autorisation humaine valide liée au `request_id` effectif est
    fournie par défaut — ces tests portent sur GenerationJobService
    (exécution/idempotence/timeout/protection réelle), pas sur le
    verrou d'autorisation humaine lui-même.
    """

    defaults = dict(
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

    return GenerationRequest(**defaults)


class TestGenerationJobServiceHappyPath(unittest.TestCase):

    def setUp(self):
        self.provider = MockHiggsfieldProvider(
            cost_per_job=10.0,
            available_credits=100.0,
            succeed_after_polls=2,
        )
        self.gate = GenerationApprovalGate(self.provider)
        self.service = GenerationJobService(self.provider, self.gate)

    def test_execute_returns_generation_job_outcome_on_success(self):
        outcome = self.service.execute(_request(), interval_seconds=0)

        self.assertIsInstance(outcome, GenerationJobOutcome)
        self.assertTrue(outcome.succeeded)
        self.assertEqual(outcome.result.status, JobStatus.SUCCEEDED)
        self.assertEqual(outcome.approval.decision, GenerationApprovalDecision.APPROVED)

    def test_execute_marks_request_as_executed(self):
        self.assertFalse(self.gate.is_already_executed("req-1"))

        self.service.execute(_request(), interval_seconds=0)

        self.assertTrue(self.gate.is_already_executed("req-1"))

    def test_execute_creates_exactly_one_job(self):
        self.service.execute(_request(), interval_seconds=0)

        self.assertEqual(len(self.provider._jobs), 1)


class TestGenerationJobServiceRefusesWithoutApproval(unittest.TestCase):

    def test_execute_refuses_when_not_approved(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)
        service = GenerationJobService(provider, gate)

        with self.assertRaises(GenerationJobExecutionError):
            service.execute(_request(approved=False))

        # Aucun job ne doit avoir été créé.
        self.assertEqual(len(provider._jobs), 0)

    def test_execute_refuses_when_budget_insufficient(self):
        provider = MockHiggsfieldProvider(cost_per_job=50.0, available_credits=1.41)
        gate = GenerationApprovalGate(provider)
        service = GenerationJobService(provider, gate)

        with self.assertRaises(GenerationJobExecutionError):
            service.execute(_request(approved=True))

        self.assertEqual(len(provider._jobs), 0)

    def test_execute_refuses_invalid_request_without_calling_provider(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)
        service = GenerationJobService(provider, gate)

        with self.assertRaises(GenerationJobExecutionError):
            service.execute(_request(prompt="   "))

        self.assertEqual(len(provider._jobs), 0)

    def test_execute_refuses_unknown_cost_without_approval(self):
        provider = MockHiggsfieldProvider(cost_per_job=None)
        gate = GenerationApprovalGate(provider)
        service = GenerationJobService(provider, gate)

        with self.assertRaises(GenerationJobExecutionError):
            service.execute(_request(approved=False))

        self.assertEqual(len(provider._jobs), 0)


class TestGenerationJobServiceIdempotence(unittest.TestCase):
    """Protection anti double-génération — bouclée avec le Gate (Phase G)."""

    def setUp(self):
        self.provider = MockHiggsfieldProvider(
            cost_per_job=10.0, available_credits=100.0, succeed_after_polls=1
        )
        self.gate = GenerationApprovalGate(self.provider)
        self.service = GenerationJobService(self.provider, self.gate)

    def test_second_execution_of_same_request_is_refused(self):
        self.service.execute(_request(), interval_seconds=0)

        with self.assertRaises(GenerationJobExecutionError) as ctx:
            self.service.execute(_request(), interval_seconds=0)

        self.assertIn("ALREADY_EXECUTED", str(ctx.exception))
        # Un seul job doit exister malgré la 2e tentative.
        self.assertEqual(len(self.provider._jobs), 1)

    def test_different_request_ids_can_both_execute(self):
        outcome_a = self.service.execute(_request(request_id="req-a"), interval_seconds=0)
        outcome_b = self.service.execute(_request(request_id="req-b"), interval_seconds=0)

        self.assertTrue(outcome_a.succeeded)
        self.assertTrue(outcome_b.succeeded)
        self.assertEqual(len(self.provider._jobs), 2)


class TestGenerationJobServiceFailureAndTimeout(unittest.TestCase):

    def test_execute_returns_outcome_object_even_with_tight_timeout(self):
        # Le service ne transmet à create_job() que
        # duration/resolution/aspect_ratio : il n'y a pas de moyen de
        # forcer un "outcome=failed" depuis GenerationRequest. Ce test
        # vérifie simplement qu'un timeout de polling très court ne
        # lève jamais d'exception : execute() retourne toujours un
        # GenerationJobOutcome, y compris quand le job n'a pas encore
        # atteint un état terminal.
        provider = MockHiggsfieldProvider(
            cost_per_job=10.0, available_credits=100.0, succeed_after_polls=1
        )
        gate = GenerationApprovalGate(provider)
        service = GenerationJobService(provider, gate)

        outcome = service.execute(_request(), timeout_seconds=0, interval_seconds=0)

        self.assertIsInstance(outcome, GenerationJobOutcome)
        self.assertIsInstance(outcome.result, VideoResult)
        self.assertIn(
            outcome.result.status,
            (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.SUCCEEDED),
        )

    def test_execute_never_raises_on_wait_timeout_it_returns_outcome(self):
        provider = MockHiggsfieldProvider(
            cost_per_job=10.0,
            available_credits=100.0,
            succeed_after_polls=1_000_000,
        )
        gate = GenerationApprovalGate(provider)
        service = GenerationJobService(provider, gate)

        outcome = service.execute(_request(), timeout_seconds=0, interval_seconds=0)

        self.assertFalse(outcome.succeeded)
        self.assertFalse(outcome.result.status.is_terminal)


class TestGenerationJobServiceNeverBypassesRealProtection(unittest.TestCase):
    """
    Vérifie que ce nouveau service N'AFFAIBLIT PAS la protection
    existante (Phase C/D) : avec le VRAI HiggsfieldProvider (client
    factice, zéro subprocess), une décision APPROVED simulée via un
    Mock-Gate qui approuverait quand même ne doit JAMAIS aboutir à une
    création de job réelle — create_job() du Provider réel lève
    systématiquement HiggsfieldRealGenerationDisabledError.
    """

    def test_real_provider_create_job_still_disabled_even_via_job_service(self):
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

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            service.execute(_request(approved=True))

        # Le CLI réel n'a jamais été sollicité pour créer un job.
        fake_client.create_job.assert_not_called()

    def test_module_has_no_cli_or_network_dependency(self):
        import inspect

        import agents.generation_job_service as module

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
