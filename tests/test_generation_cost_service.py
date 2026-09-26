"""
Tests — GenerationCostService (Phase F, MASTER PROMPT V2).

Aucun de ces tests n'appelle le CLI Higgsfield ni le réseau. La
logique de génération (MockHiggsfieldProvider) est utilisée pour les
scénarios réalistes de bout en bout ; un provider factice
(MagicMock(spec=BaseHiggsfieldProvider)) est utilisé pour vérifier
précisément la délégation des paramètres et la propagation des
erreurs — sans jamais toucher au réseau non plus.
"""

import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.generation_cost_service import (
    CostEstimationStatus,
    GenerationCostResult,
    GenerationCostService,
)
from integrations.higgsfield.errors import (
    HiggsfieldCommandError,
    HiggsfieldTimeoutError,
)
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import BaseHiggsfieldProvider
from integrations.higgsfield.types import CostEstimate


class TestGenerationCostServiceKnownCost(unittest.TestCase):
    """1 & 2. Estimation de coût connue, coût retourné correctement."""

    def test_known_cost_with_mock_provider(self):
        provider = MockHiggsfieldProvider(cost_per_job=22.5)
        service = GenerationCostService(provider)

        result = service.estimate(
            job_type="seedance_2_0",
            prompt="prompt de test",
            duration=5,
            resolution="720p",
            aspect_ratio="9:16",
        )

        self.assertEqual(result.status, CostEstimationStatus.KNOWN)
        self.assertTrue(result.known)
        self.assertIsInstance(result.estimate, CostEstimate)
        self.assertEqual(result.estimate.credits, 22.5)
        self.assertIsNone(result.error)

    def test_known_cost_of_zero_is_not_treated_as_unknown(self):
        # Un coût explicitement gratuit (0.0) reste un coût CONNU,
        # distinct d'une absence de valeur (None -> UNKNOWN).
        provider = MockHiggsfieldProvider(cost_per_job=0.0)
        service = GenerationCostService(provider)

        result = service.estimate(job_type="seedance_2_0", prompt="p")

        self.assertEqual(result.status, CostEstimationStatus.KNOWN)
        self.assertEqual(result.estimate.credits, 0.0)


class TestGenerationCostServiceUnknownCost(unittest.TestCase):
    """3. Coût inconnu — jamais de valeur inventée."""

    def test_unknown_cost_when_provider_returns_none(self):
        provider = MockHiggsfieldProvider(cost_per_job=None)
        service = GenerationCostService(provider)

        result = service.estimate(job_type="seedance_2_0", prompt="prompt")

        self.assertEqual(result.status, CostEstimationStatus.UNKNOWN)
        self.assertFalse(result.known)
        self.assertIsNone(result.error)
        # Le coût n'est jamais inventé : credits reste None, pas 0.
        self.assertIsNone(result.estimate.credits)

    def test_unknown_cost_does_not_raise(self):
        provider = MockHiggsfieldProvider(cost_per_job=None)
        service = GenerationCostService(provider)

        try:
            service.estimate(job_type="seedance_2_0", prompt="prompt")
        except Exception as error:  # pragma: no cover - ne doit jamais arriver
            self.fail(f"UNKNOWN cost should not raise, got: {error}")


class TestGenerationCostServiceParameterPassthrough(unittest.TestCase):
    """4. Les paramètres de génération sont transmis correctement au Provider."""

    def test_parameters_are_forwarded_to_provider_estimate_cost(self):
        fake_provider = MagicMock(spec=BaseHiggsfieldProvider)
        fake_provider.estimate_cost.return_value = CostEstimate(
            job_type="seedance_2_0", credits=22.5, raw={"credits": 22.5}
        )
        service = GenerationCostService(fake_provider)

        service.estimate(
            job_type="seedance_2_0",
            prompt="mon prompt",
            duration=8,
            resolution="1080p",
            aspect_ratio="16:9",
        )

        fake_provider.estimate_cost.assert_called_once_with(
            job_type="seedance_2_0",
            prompt="mon prompt",
            duration=8,
            resolution="1080p",
            aspect_ratio="16:9",
        )


class TestGenerationCostServiceErrorPropagation(unittest.TestCase):
    """5. Erreur Provider correctement propagée/traduite (jamais d'exception non gérée)."""

    def test_timeout_error_is_translated_to_error_status(self):
        fake_provider = MagicMock(spec=BaseHiggsfieldProvider)
        fake_provider.estimate_cost.side_effect = HiggsfieldTimeoutError(
            "Higgsfield CLI command timed out"
        )
        service = GenerationCostService(fake_provider)

        result = service.estimate(job_type="seedance_2_0", prompt="prompt")

        self.assertEqual(result.status, CostEstimationStatus.ERROR)
        self.assertIsNone(result.estimate)
        self.assertIn("timed out", result.error)

    def test_command_error_is_translated_to_error_status(self):
        fake_provider = MagicMock(spec=BaseHiggsfieldProvider)
        fake_provider.estimate_cost.side_effect = HiggsfieldCommandError(
            "Higgsfield CLI command failed", exit_code=1, stderr="boom"
        )
        service = GenerationCostService(fake_provider)

        result = service.estimate(job_type="seedance_2_0", prompt="prompt")

        self.assertEqual(result.status, CostEstimationStatus.ERROR)

    def test_missing_prompt_is_an_error_without_calling_provider(self):
        fake_provider = MagicMock(spec=BaseHiggsfieldProvider)
        service = GenerationCostService(fake_provider)

        result = service.estimate(job_type="seedance_2_0", prompt="   ")

        self.assertEqual(result.status, CostEstimationStatus.ERROR)
        fake_provider.estimate_cost.assert_not_called()

    def test_missing_job_type_is_an_error_without_calling_provider(self):
        fake_provider = MagicMock(spec=BaseHiggsfieldProvider)
        service = GenerationCostService(fake_provider)

        result = service.estimate(job_type="", prompt="prompt")

        self.assertEqual(result.status, CostEstimationStatus.ERROR)
        fake_provider.estimate_cost.assert_not_called()


class TestGenerationCostServiceNeverCreatesJob(unittest.TestCase):
    """6, 7, 8. Aucun appel à createJob, au CLI réel, ni à une génération réelle."""

    def test_estimate_never_calls_create_job_on_success(self):
        fake_provider = MagicMock(spec=BaseHiggsfieldProvider)
        fake_provider.estimate_cost.return_value = CostEstimate(
            job_type="seedance_2_0", credits=22.5
        )
        service = GenerationCostService(fake_provider)

        service.estimate(job_type="seedance_2_0", prompt="prompt")

        fake_provider.create_job.assert_not_called()

    def test_estimate_never_calls_create_job_on_error(self):
        fake_provider = MagicMock(spec=BaseHiggsfieldProvider)
        fake_provider.estimate_cost.side_effect = HiggsfieldTimeoutError("timeout")
        service = GenerationCostService(fake_provider)

        service.estimate(job_type="seedance_2_0", prompt="prompt")

        fake_provider.create_job.assert_not_called()

    def test_module_has_no_cli_or_network_dependency(self):
        # Vérifie les IMPORTS réels du module (pas le texte des
        # docstrings, qui mentionnent volontairement HiggsfieldClient
        # en prose pour expliquer qu'il n'est PAS utilisé ici).
        import agents.generation_cost_service as module

        imported_names = {
            name
            for name, value in vars(module).items()
            if inspect.ismodule(value) or inspect.isclass(value)
        }

        self.assertNotIn("HiggsfieldClient", imported_names)
        self.assertFalse(hasattr(module, "subprocess"))
        self.assertFalse(hasattr(module, "requests"))
        self.assertFalse(hasattr(module, "socket"))
        self.assertFalse(hasattr(module, "urllib"))

    def test_full_flow_with_real_mock_provider_never_touches_cli(self):
        # Bout en bout réaliste avec MockHiggsfieldProvider : aucune
        # dépendance CLI, aucun crédit, aucun job créé.
        provider = MockHiggsfieldProvider(cost_per_job=22.5)
        service = GenerationCostService(provider)

        result = service.estimate(job_type="seedance_2_0", prompt="prompt")

        self.assertTrue(result.known)
        self.assertEqual(len(provider._jobs), 0)


class TestGenerationCostServiceTypeCompatibility(unittest.TestCase):
    """9. Compatibilité avec les types existants (Phase B)."""

    def test_result_is_generation_cost_result(self):
        provider = MockHiggsfieldProvider()
        service = GenerationCostService(provider)

        result = service.estimate(job_type="seedance_2_0", prompt="prompt")

        self.assertIsInstance(result, GenerationCostResult)
        self.assertIsInstance(result.status, CostEstimationStatus)
        self.assertIsInstance(result.estimate, CostEstimate)

    def test_service_accepts_any_base_higgsfield_provider(self):
        # Le service ne doit être couplé ni à Mock ni au réel : tout
        # objet respectant BaseHiggsfieldProvider doit fonctionner.
        provider = MockHiggsfieldProvider()
        self.assertIsInstance(provider, BaseHiggsfieldProvider)
        GenerationCostService(provider)  # ne doit pas lever


class TestCostEngineNonRegression(unittest.TestCase):
    """10. Non-régression de agents/cost_engine.py (V1, non modifié)."""

    def test_cost_engine_still_importable_and_untouched(self):
        from agents.cost_engine import CostEngine
        from agents.cost_engine import CostEstimate as V1CostEstimate

        # CostEngine reste instantiable hors-ligne (ne contacte le CLI
        # qu'au moment d'un appel de méthode, pas à la construction).
        engine = CostEngine()
        self.assertTrue(hasattr(engine, "evaluate_plan"))
        self.assertTrue(hasattr(engine, "get_verified_cost"))
        self.assertTrue(hasattr(engine, "get_available_credits"))

        # Le type V1 (business, budget) reste distinct du type Provider
        # (Phase B) : aucune duplication, aucune fusion accidentelle.
        self.assertIsNot(V1CostEstimate, CostEstimate)


if __name__ == "__main__":
    unittest.main()
