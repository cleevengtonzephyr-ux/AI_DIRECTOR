"""
Tests — MockHiggsfieldProvider (Phase B/C/E, MASTER PROMPT V2).

Aucun de ces tests n'appelle le CLI Higgsfield ni le réseau : le Mock
est 100% en mémoire. C'est la SEULE implémentation de Provider
autorisée à simuler réellement create_job()/get_job()/wait_for_job()
dans ce projet.

Déterminisme strict (Phase E) : le scénario de timeout n'utilise
AUCUN sleep réel ni AUCUNE dépendance au temps réel écoulé — une
horloge factice (_FakeClock) est injectée dans MockHiggsfieldProvider
pour que le franchissement du délai soit un fait de calcul, pas un
fait de timing.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from integrations.higgsfield.errors import HiggsfieldInvalidResponseError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import BaseHiggsfieldProvider
from integrations.higgsfield.types import (
    CostEstimate,
    Job,
    JobStatus,
    ModelSchema,
    VideoResult,
)


class _FakeClock:
    """Horloge déterministe : chaque appel avance le temps d'un pas fixe."""

    def __init__(self, step: float = 1.0):
        self._now = 0.0
        self._step = step

    def __call__(self) -> float:
        value = self._now
        self._now += self._step
        return value


def _no_sleep(_seconds: float) -> None:
    """Remplace time.sleep dans les tests : ne dort jamais réellement."""


class TestMockHiggsfieldProviderContract(unittest.TestCase):
    """1. Le Mock respecte le contrat du Provider."""

    def test_mock_is_a_base_higgsfield_provider(self):
        provider = MockHiggsfieldProvider()
        self.assertIsInstance(provider, BaseHiggsfieldProvider)

    def test_mock_implements_every_abstract_method(self):
        # ABC lève TypeError à l'instanciation si une méthode abstraite
        # manque : le simple fait d'instancier sans erreur EST la preuve.
        try:
            MockHiggsfieldProvider()
        except TypeError as error:
            self.fail(f"MockHiggsfieldProvider n'implémente pas le contrat: {error}")


class TestMockHiggsfieldProviderEstimateCost(unittest.TestCase):
    """2. estimateCost fonctionne (déterministe, contrôlable par le test)."""

    def test_estimate_cost_returns_configured_value(self):
        provider = MockHiggsfieldProvider(cost_per_job=99.0)

        estimate = provider.estimate_cost("seedance_2_0", "un prompt")

        self.assertIsInstance(estimate, CostEstimate)
        self.assertEqual(estimate.credits, 99.0)
        self.assertEqual(estimate.job_type, "seedance_2_0")

    def test_estimate_cost_is_deterministic_across_calls(self):
        provider = MockHiggsfieldProvider(cost_per_job=22.5)

        first = provider.estimate_cost("seedance_2_0", "prompt A")
        second = provider.estimate_cost("seedance_2_0", "prompt B")

        self.assertEqual(first.credits, second.credits)


class TestMockHiggsfieldProviderCreateJob(unittest.TestCase):
    """3. createJob ne contacte aucun système externe."""

    def test_create_job_generates_predictable_id(self):
        provider = MockHiggsfieldProvider()

        job_1 = provider.create_job("seedance_2_0", "prompt 1")
        job_2 = provider.create_job("seedance_2_0", "prompt 2")

        self.assertEqual(job_1.job_id, "mock-job-1")
        self.assertEqual(job_2.job_id, "mock-job-2")

    def test_create_job_returns_queued_job_instance(self):
        provider = MockHiggsfieldProvider()

        job = provider.create_job("seedance_2_0", "prompt")

        self.assertIsInstance(job, Job)
        self.assertEqual(job.status, JobStatus.QUEUED)

    def test_create_job_uses_no_network_module(self):
        # Vérification structurelle : mock_provider.py ne doit importer
        # ni subprocess, ni HiggsfieldClient, ni requests/urllib.
        import inspect

        import integrations.higgsfield.mock_provider as module

        source = inspect.getsource(module)
        for forbidden in ("subprocess", "HiggsfieldClient", "requests", "urllib", "socket"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


class TestMockHiggsfieldProviderGetJob(unittest.TestCase):
    """4. getJob fonctionne."""

    def test_get_job_returns_job_instance_with_matching_id(self):
        provider = MockHiggsfieldProvider()
        created = provider.create_job("seedance_2_0", "prompt")

        fetched = provider.get_job(created.job_id)

        self.assertIsInstance(fetched, Job)
        self.assertEqual(fetched.job_id, created.job_id)

    def test_get_job_unknown_id_raises(self):
        provider = MockHiggsfieldProvider()

        with self.assertRaises(HiggsfieldInvalidResponseError):
            provider.get_job("unknown-job-id")


class TestMockHiggsfieldProviderProgression(unittest.TestCase):
    """5. waitForJob simule correctement la progression."""

    def test_job_progresses_queued_then_running_then_terminal(self):
        provider = MockHiggsfieldProvider(succeed_after_polls=2)
        job = provider.create_job("seedance_2_0", "prompt")

        self.assertEqual(job.status, JobStatus.QUEUED)

        job = provider.get_job(job.job_id)
        self.assertEqual(job.status, JobStatus.RUNNING)

        job = provider.get_job(job.job_id)
        self.assertEqual(job.status, JobStatus.SUCCEEDED)


class TestMockHiggsfieldProviderCompleted(unittest.TestCase):
    """6. Un job peut terminer en COMPLETED (= JobStatus.SUCCEEDED)."""

    def test_wait_for_job_completes_successfully(self):
        provider = MockHiggsfieldProvider(succeed_after_polls=2)
        job = provider.create_job("seedance_2_0", "prompt", outcome="succeeded")

        result = provider.wait_for_job(job.job_id, timeout_seconds=5, interval_seconds=0)

        self.assertIsInstance(result, VideoResult)
        self.assertEqual(result.status, JobStatus.SUCCEEDED)
        self.assertTrue(result.succeeded)
        self.assertEqual(result.output_urls, (f"mock://output/{job.job_id}.mp4",))


class TestMockHiggsfieldProviderFailed(unittest.TestCase):
    """7. Un job peut terminer en FAILED."""

    def test_job_can_be_forced_to_fail(self):
        provider = MockHiggsfieldProvider(succeed_after_polls=2)
        job = provider.create_job("seedance_2_0", "prompt", outcome="failed")

        result = provider.wait_for_job(job.job_id, timeout_seconds=5, interval_seconds=0)

        self.assertEqual(result.status, JobStatus.FAILED)
        self.assertFalse(result.succeeded)
        self.assertEqual(result.output_urls, tuple())

    def test_get_job_reflects_failed_status_directly(self):
        provider = MockHiggsfieldProvider(succeed_after_polls=1)
        job = provider.create_job("seedance_2_0", "prompt", outcome="failed")

        job = provider.get_job(job.job_id)  # -> RUNNING
        job = provider.get_job(job.job_id)  # -> FAILED (1 poll suffisant)

        self.assertEqual(job.status, JobStatus.FAILED)


class TestMockHiggsfieldProviderTimeout(unittest.TestCase):
    """8. Un timeout est correctement simulé — de façon 100% déterministe."""

    def test_wait_for_job_times_out_without_real_sleep(self):
        # succeed_after_polls très élevé : le job ne termine jamais.
        # L'horloge factice avance de 1.0 à chaque appel ; avec un
        # timeout de 2.5, le budget est dépassé après 3 appels — sans
        # dépendre du temps réel écoulé.
        fake_clock = _FakeClock(step=1.0)
        provider = MockHiggsfieldProvider(
            succeed_after_polls=1_000_000,
            clock=fake_clock,
            sleep=_no_sleep,
        )
        job = provider.create_job("seedance_2_0", "prompt")

        result = provider.wait_for_job(job.job_id, timeout_seconds=2.5, interval_seconds=1)

        self.assertFalse(result.succeeded)
        self.assertIn(result.status, (JobStatus.QUEUED, JobStatus.RUNNING))
        self.assertEqual(result.output_urls, tuple())

    def test_timeout_never_loops_forever(self):
        # Garde-fou du test lui-même : si wait_for_job bouclait à
        # l'infini, ce test ne se terminerait jamais (le harness de
        # test le ferait échouer par timeout global, jamais en boucle
        # silencieuse). L'horloge factice garantit une sortie après un
        # nombre fini et connu d'itérations.
        fake_clock = _FakeClock(step=1.0)
        provider = MockHiggsfieldProvider(
            succeed_after_polls=1_000_000,
            clock=fake_clock,
            sleep=_no_sleep,
        )
        job = provider.create_job("seedance_2_0", "prompt")

        result = provider.wait_for_job(job.job_id, timeout_seconds=1000, interval_seconds=1)

        self.assertFalse(result.succeeded)


class TestMockHiggsfieldProviderListModels(unittest.TestCase):
    """9. listModels fonctionne."""

    def test_list_models_includes_seedance_2_0_by_default(self):
        provider = MockHiggsfieldProvider()

        models = provider.list_models()

        self.assertTrue(all(isinstance(m, ModelSchema) for m in models))
        self.assertIn("seedance_2_0", [m.job_type for m in models])

    def test_list_models_uses_injected_catalog_without_any_cli_call(self):
        custom_models = [
            ModelSchema(job_type="kling3_0", display_name="Kling v3.0"),
        ]
        provider = MockHiggsfieldProvider(models=custom_models)

        models = provider.list_models()

        self.assertEqual([m.job_type for m in models], ["kling3_0"])

    def test_get_model_unknown_raises(self):
        provider = MockHiggsfieldProvider()

        with self.assertRaises(HiggsfieldInvalidResponseError):
            provider.get_model("does_not_exist")


class TestMockHiggsfieldProviderIsolation(unittest.TestCase):
    """10. Deux jobs distincts ne se mélangent pas."""

    def test_two_jobs_progress_independently(self):
        provider = MockHiggsfieldProvider()

        job_a = provider.create_job(
            "seedance_2_0", "prompt A", outcome="succeeded", succeed_after_polls=1
        )
        job_b = provider.create_job(
            "seedance_2_0", "prompt B", outcome="failed", succeed_after_polls=3
        )

        # On ne fait progresser QUE job_a jusqu'au bout.
        provider.get_job(job_a.job_id)  # RUNNING
        result_a = provider.get_job(job_a.job_id)  # SUCCEEDED (1 poll)

        # job_b n'a reçu aucun appel : il doit rester QUEUED.
        self.assertEqual(result_a.status, JobStatus.SUCCEEDED)

        raw_b_state = provider._jobs[job_b.job_id]  # inspection directe, test uniquement
        self.assertEqual(raw_b_state["status"], JobStatus.QUEUED)
        self.assertEqual(raw_b_state["polls"], 0)

        # On fait maintenant progresser job_b jusqu'à FAILED : job_a ne
        # doit pas être affecté.
        provider.get_job(job_b.job_id)  # RUNNING
        provider.get_job(job_b.job_id)  # RUNNING (poll 2 < 3)
        result_b = provider.get_job(job_b.job_id)  # FAILED (poll 3)

        self.assertEqual(result_b.status, JobStatus.FAILED)
        self.assertEqual(provider.get_job(job_a.job_id).status, JobStatus.SUCCEEDED)
        self.assertNotEqual(job_a.job_id, job_b.job_id)

    def test_ids_are_never_reused(self):
        provider = MockHiggsfieldProvider()

        ids = {provider.create_job("seedance_2_0", f"prompt {i}").job_id for i in range(5)}

        self.assertEqual(len(ids), 5)


class TestMockHiggsfieldProviderTypes(unittest.TestCase):
    """11. Les résultats correspondent aux types définis (Phase B)."""

    def test_all_return_types_match_defined_interfaces(self):
        provider = MockHiggsfieldProvider(succeed_after_polls=1)

        self.assertTrue(all(isinstance(m, ModelSchema) for m in provider.list_models()))
        self.assertIsInstance(provider.get_model("seedance_2_0"), ModelSchema)
        self.assertIsInstance(
            provider.estimate_cost("seedance_2_0", "prompt"), CostEstimate
        )

        job = provider.create_job("seedance_2_0", "prompt")
        self.assertIsInstance(job, Job)
        self.assertIsInstance(provider.get_job(job.job_id), Job)

        job2 = provider.create_job("seedance_2_0", "prompt")
        result = provider.wait_for_job(job2.job_id, timeout_seconds=5, interval_seconds=0)
        self.assertIsInstance(result, VideoResult)


class TestMockHiggsfieldProviderNoRealDependency(unittest.TestCase):
    """12. Aucune dépendance au CLI réel n'est nécessaire."""

    def test_mock_provider_module_does_not_import_client(self):
        import inspect

        import integrations.higgsfield.mock_provider as module

        source = inspect.getsource(module)
        self.assertNotIn("HiggsfieldClient", source)
        self.assertNotIn("import subprocess", source)

    def test_full_lifecycle_without_any_cli_or_network(self):
        # Séquence complète (list -> cost -> create -> poll -> wait)
        # entièrement fonctionnelle sans CLI, sans réseau, sans crédit.
        provider = MockHiggsfieldProvider(succeed_after_polls=2)

        self.assertTrue(provider.list_models())
        self.assertGreater(provider.estimate_cost("seedance_2_0", "p").credits, 0)

        job = provider.create_job("seedance_2_0", "p")
        result = provider.wait_for_job(job.job_id, timeout_seconds=5, interval_seconds=0)

        self.assertTrue(result.succeeded)


if __name__ == "__main__":
    unittest.main()
