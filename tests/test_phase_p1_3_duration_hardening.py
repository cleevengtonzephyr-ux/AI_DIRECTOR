"""
Tests — Phase P1.3 : durcissement de la validation de durée dans
GenerationApprovalGate, à partir des durées réellement confirmées pour
seedance_2_0 (Phase P1.2, lecture seule : 5/10/15s acceptés, >15s
rejeté par l'API réelle).

Aucun test de ce fichier n'appelle le CLI réel ni ne consomme de
crédit : MockHiggsfieldProvider uniquement. Son catalogue par défaut
déclare déjà "seedance_2_0" avec un paramètre "duration" — suffisant
pour ces tests, puisque la table CONFIRMED_DURATIONS_BY_MODEL du Gate
n'exige que la PRÉSENCE du paramètre dans le schéma, pas une valeur
par défaut particulière.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.generation_approval_gate import (
    CONFIRMED_DURATIONS_BY_MODEL,
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
)
from agents.production_model import PRODUCTION_MODEL
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider


def _request(duration: int, **overrides) -> GenerationRequest:
    defaults = dict(
        request_id=f"req-{duration}s",
        job_type="seedance_2_0",
        prompt="prompt de test",
        duration=duration,
        resolution="720p",
        aspect_ratio="9:16",
        approved=False,
    )
    defaults.update(overrides)
    return GenerationRequest(**defaults)


class TestConfirmedDurationsTable(unittest.TestCase):

    def test_seedance_2_0_confirmed_set_matches_phase_p1_2_audit(self):
        self.assertEqual(CONFIRMED_DURATIONS_BY_MODEL[PRODUCTION_MODEL], (5, 10, 15))


class TestConfirmedDurationsAreAccepted(unittest.TestCase):
    """duration=5 / 10 / 15 -> valides (ne bloquent pas sur INVALID_REQUEST)."""

    def test_duration_5_is_valid(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(5))

        self.assertNotEqual(result.decision, GenerationApprovalDecision.INVALID_REQUEST)

    def test_duration_10_is_valid(self):
        provider = MockHiggsfieldProvider(cost_per_job=45.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(10))

        self.assertNotEqual(result.decision, GenerationApprovalDecision.INVALID_REQUEST)

    def test_duration_15_is_valid(self):
        provider = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(15))

        self.assertNotEqual(result.decision, GenerationApprovalDecision.INVALID_REQUEST)

    def test_confirmed_durations_reach_needs_approval_with_sufficient_budget(self):
        # Budget suffisant + duree confirmee + PAS d'approbation
        # explicite -> NEEDS_APPROVAL (jamais APPROVED automatiquement).
        for duration in (5, 10, 15):
            with self.subTest(duration=duration):
                provider = MockHiggsfieldProvider(
                    cost_per_job=10.0, available_credits=1000.0
                )
                gate = GenerationApprovalGate(provider)

                result = gate.evaluate(_request(duration, approved=False))

                self.assertEqual(
                    result.decision, GenerationApprovalDecision.NEEDS_APPROVAL
                )


class TestUnconfirmedDurationsAreRejected(unittest.TestCase):
    """duration=20 / 40 (et toute valeur hors {5,10,15}) -> INVALID_REQUEST."""

    def test_duration_20_is_rejected(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(20))

        self.assertEqual(result.decision, GenerationApprovalDecision.INVALID_REQUEST)
        self.assertTrue(any("UNVERIFIED" in reason for reason in result.reasons))

    def test_duration_40_is_rejected(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(40))

        self.assertEqual(result.decision, GenerationApprovalDecision.INVALID_REQUEST)

    def test_rejection_happens_even_with_approval_and_huge_budget(self):
        # Ne jamais considerer une duree valide juste parce qu'elle
        # existe dans un VideoPlan approuve avec un budget confortable.
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100000.0)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(40, approved=True))

        self.assertEqual(result.decision, GenerationApprovalDecision.INVALID_REQUEST)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)

    def test_rejected_duration_never_reaches_cost_estimation(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(40))

        self.assertIsNone(result.cost_result)


class TestBudgetGateWithRealObservedNumbers(unittest.TestCase):
    """cost > available_balance -> BLOCKED (exemple reel : 22.5 > 1.41)."""

    def test_real_observed_numbers_block_generation(self):
        provider = MockHiggsfieldProvider(cost_per_job=22.5, available_credits=1.41)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(5, approved=True))

        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)
        self.assertIn("Insufficient credits", result.reasons[0])

    def test_sufficient_budget_still_requires_explicit_approval(self):
        provider = MockHiggsfieldProvider(cost_per_job=22.5, available_credits=1000.0)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(5, approved=False))

        self.assertEqual(result.decision, GenerationApprovalDecision.NEEDS_APPROVAL)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestNoRealGenerationAcrossAllScenarios(unittest.TestCase):
    """create_job() jamais appele, quel que soit le scenario de duree/budget."""

    def test_create_job_never_called_for_any_duration_scenario(self):
        for duration in (5, 10, 15, 20, 40):
            for approved in (True, False):
                with self.subTest(duration=duration, approved=approved):
                    provider = MockHiggsfieldProvider(
                        cost_per_job=22.5, available_credits=1.41
                    )
                    gate = GenerationApprovalGate(provider)

                    gate.evaluate(_request(duration, approved=approved))

                    self.assertEqual(len(provider._jobs), 0)


if __name__ == "__main__":
    unittest.main()
