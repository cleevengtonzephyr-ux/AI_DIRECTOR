"""
Tests — GenerationApprovalGate (Phase G, MASTER PROMPT V2).

Tous les tests utilisent EXCLUSIVEMENT MockHiggsfieldProvider (aucun
CLI réel, aucun réseau, aucun crédit consommé). Chaque scénario du
cahier des charges de la Phase G a sa propre méthode de test nommée
explicitement.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from integrations.higgsfield.errors import HiggsfieldTimeoutError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider


def _request(**overrides) -> GenerationRequest:
    """
    Phase P2.11 : sauf override explicite de
    `real_generation_authorization` (y compris `None`), une
    autorisation humaine VALIDE et liée au `request_id` effectif est
    fournie par défaut — ces tests portent sur le comportement du Gate
    au regard du budget/`approved`/replay, pas sur le verrou
    d'autorisation humaine lui-même (couvert par
    tests/test_phase_p2_11_human_authorization_guard.py). `approved`
    reste le signal qui détermine réellement APPROVED vs
    NEEDS_APPROVAL dans ces scénarios.
    """

    defaults = dict(
        request_id="req-1",
        job_type="seedance_2_0",
        prompt="prompt de test",
        duration=5,
        resolution="720p",
        aspect_ratio="9:16",
        approved=False,
    )
    defaults.update(overrides)

    if "real_generation_authorization" not in overrides:
        defaults["real_generation_authorization"] = RealGenerationAuthorization(
            request_id=defaults["request_id"],
            authorized_by_human=True,
        )

    return GenerationRequest(**defaults)


class TestKnownCostSufficientBudget(unittest.TestCase):
    """Cas 1 : coût connu, budget suffisant, pas d'approbation -> NEEDS_APPROVAL."""

    def test_needs_approval_when_not_yet_approved(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(approved=False))

        self.assertEqual(result.decision, GenerationApprovalDecision.NEEDS_APPROVAL)
        self.assertFalse(result.approved)

    def test_approved_when_explicitly_approved(self):
        """Cas 4 : approbation explicite valide -> APPROVED, sans créer de job."""
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(approved=True))

        self.assertEqual(result.decision, GenerationApprovalDecision.APPROVED)
        self.assertTrue(result.approved)
        self.assertEqual(len(provider._jobs), 0)


class TestKnownCostInsufficientBudget(unittest.TestCase):
    """Cas 2 : coût connu, budget insuffisant -> BLOCKED (même si approuvé)."""

    def test_blocked_when_budget_insufficient_and_not_approved(self):
        provider = MockHiggsfieldProvider(cost_per_job=50.0, available_credits=1.41)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(approved=False))

        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)
        self.assertIn("Insufficient credits", result.reasons[0])

    def test_blocked_even_if_approved_when_budget_insufficient(self):
        # L'approbation humaine ne crée pas de crédits : le budget
        # insuffisant bloque inconditionnellement.
        provider = MockHiggsfieldProvider(cost_per_job=50.0, available_credits=1.41)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(approved=True))

        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)


class TestUnknownCost(unittest.TestCase):
    """Cas 3 : coût UNKNOWN -> jamais d'autorisation silencieuse."""

    def test_unknown_cost_needs_approval_when_not_approved(self):
        provider = MockHiggsfieldProvider(cost_per_job=None)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(approved=False))

        self.assertEqual(result.decision, GenerationApprovalDecision.NEEDS_APPROVAL)

    def test_unknown_cost_approved_when_explicit_approval_given(self):
        provider = MockHiggsfieldProvider(cost_per_job=None)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(approved=True))

        self.assertEqual(result.decision, GenerationApprovalDecision.APPROVED)

    def test_unknown_cost_never_auto_approves_without_explicit_flag(self):
        # Répéter plusieurs fois : jamais d'APPROVED implicite.
        provider = MockHiggsfieldProvider(cost_per_job=None)
        gate = GenerationApprovalGate(provider)

        for _ in range(3):
            result = gate.evaluate(_request(approved=False))
            self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestMissingOrInvalidApproval(unittest.TestCase):
    """Absence d'approbation / approbation invalide."""

    def test_missing_approval_defaults_to_needs_approval(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request())  # approved=False par défaut

        self.assertEqual(result.decision, GenerationApprovalDecision.NEEDS_APPROVAL)

    def test_invalid_request_is_rejected_before_any_cost_estimation(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(prompt="   "))

        self.assertEqual(result.decision, GenerationApprovalDecision.INVALID_REQUEST)
        self.assertIsNone(result.cost_result)

    def test_invalid_request_missing_job_type(self):
        provider = MockHiggsfieldProvider()
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(job_type=""))

        self.assertEqual(result.decision, GenerationApprovalDecision.INVALID_REQUEST)

    def test_invalid_request_missing_request_id(self):
        provider = MockHiggsfieldProvider()
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(request_id=""))

        self.assertEqual(result.decision, GenerationApprovalDecision.INVALID_REQUEST)

    def test_invalid_request_bad_duration(self):
        provider = MockHiggsfieldProvider()
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(duration=-5))

        self.assertEqual(result.decision, GenerationApprovalDecision.INVALID_REQUEST)


class TestAlreadyExecuted(unittest.TestCase):
    """Cas 5 : demande déjà exécutée -> ALREADY_EXECUTED."""

    def test_already_executed_after_mark_executed(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        first = gate.evaluate(_request(approved=True))
        self.assertEqual(first.decision, GenerationApprovalDecision.APPROVED)

        gate.mark_executed("req-1")

        second = gate.evaluate(_request(approved=True))
        self.assertEqual(second.decision, GenerationApprovalDecision.ALREADY_EXECUTED)

    def test_already_executed_short_circuits_before_cost_estimation(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)
        gate.mark_executed("req-1")

        result = gate.evaluate(_request())

        self.assertEqual(result.decision, GenerationApprovalDecision.ALREADY_EXECUTED)
        self.assertIsNone(result.cost_result)

    def test_different_request_ids_are_independent(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)
        gate.mark_executed("req-1")

        result = gate.evaluate(_request(request_id="req-2", approved=True))

        self.assertEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestProviderErrors(unittest.TestCase):
    """Erreur du Provider (ex. lors de la vérification du solde) -> décision sûre."""

    def test_balance_error_results_in_blocked(self):
        provider = MockHiggsfieldProvider(
            cost_per_job=10.0,
            balance_error=HiggsfieldTimeoutError("account status timed out"),
        )
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(approved=True))

        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)
        self.assertIn("account status timed out", result.reasons[0])

    def test_balance_none_results_in_blocked(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=None)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(approved=True))

        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)


class TestCostServiceErrors(unittest.TestCase):
    """Cas 6 : erreur du Cost Service -> décision sûre, jamais APPROVED."""

    def test_cost_service_error_results_in_blocked_not_approved(self):
        provider = MockHiggsfieldProvider(
            cost_error=HiggsfieldTimeoutError("generate cost timed out"),
        )
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(approved=True))

        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)
        self.assertIn("Cost estimation error", result.reasons[0])


class TestNeverCallsCreateJobOrRealCli(unittest.TestCase):
    """Vérifications de sécurité transverses (obligatoires, Phase G)."""

    def test_create_job_is_never_called_across_all_decisions(self):
        scenarios = [
            MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0),  # -> NEEDS_APPROVAL/APPROVED
            MockHiggsfieldProvider(cost_per_job=50.0, available_credits=1.41),   # -> BLOCKED
            MockHiggsfieldProvider(cost_per_job=None),                          # -> UNKNOWN path
        ]

        for provider in scenarios:
            gate = GenerationApprovalGate(provider)
            gate.evaluate(_request(approved=True))
            gate.evaluate(_request(approved=False))

            self.assertEqual(len(provider._jobs), 0)

    def test_module_has_no_cli_or_network_dependency(self):
        import inspect

        import agents.generation_approval_gate as module

        imported_names = {
            name
            for name, value in vars(module).items()
            if inspect.ismodule(value) or inspect.isclass(value)
        }

        self.assertNotIn("HiggsfieldClient", imported_names)
        self.assertFalse(hasattr(module, "subprocess"))
        self.assertFalse(hasattr(module, "requests"))
        self.assertFalse(hasattr(module, "socket"))

    def test_no_credits_consumed_across_full_scenario_matrix(self):
        # Aucune de ces évaluations ne doit jamais faire progresser
        # le registre de jobs simulés (create_job n'est jamais appelé).
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        for approved in (True, False):
            for request_id in ("a", "b", "c"):
                gate.evaluate(_request(request_id=request_id, approved=approved))

        self.assertEqual(len(provider._jobs), 0)


if __name__ == "__main__":
    unittest.main()
