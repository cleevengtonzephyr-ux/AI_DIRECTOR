"""
Tests — HiggsfieldProvider (implémentation réelle, Phase B/C/D).

Ces tests injectent un FAUX HiggsfieldClient (aucun subprocess, aucun
CLI réel) pour vérifier :
- la délégation correcte de chaque méthode au Client ;
- la traduction JSON brut -> types internes (Job/VideoResult/
  CostEstimate/ModelSchema) ;
- la propagation des erreurs typées levées par le Client (timeout,
  authentification, etc.) sans les avaler ni les masquer ;
- la détection explicite des réponses invalides (forme inattendue) ;
- le garde-fou de create_job(), qui n'atteint JAMAIS le Client.

Le seul test qui touche VRAIMENT le garde-fou de sécurité
(test_create_job_is_disabled...) vérifie qu'AUCUN appel CLI n'est
fait, même indirectement, en s'assurant que le faux client n'est
jamais sollicité pour create_job().
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from integrations.higgsfield.errors import (
    HiggsfieldInvalidResponseError,
    HiggsfieldRealGenerationDisabledError,
    HiggsfieldTimeoutError,
)
from integrations.higgsfield.provider import HiggsfieldProvider
from integrations.higgsfield.types import JobStatus


class TestHiggsfieldProvider(unittest.TestCase):

    def setUp(self):
        self.fake_client = MagicMock()
        self.provider = HiggsfieldProvider(client=self.fake_client)

    def test_list_models_parses_raw_json(self):
        self.fake_client.list_models.return_value = [
            {
                "job_type": "seedance_2_0",
                "display_name": "Seedance 2.0",
                "params": [
                    {"name": "prompt", "type": "string", "required": True},
                    {
                        "name": "resolution",
                        "type": "string",
                        "required": False,
                        "default": "720p",
                        "enum": ["480p", "720p", "1080p"],
                    },
                ],
            }
        ]

        models = self.provider.list_models(video=True)

        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].job_type, "seedance_2_0")
        self.assertEqual(models[0].param("prompt").required, True)
        self.assertIn("720p", models[0].param("resolution").enum)
        self.fake_client.list_models.assert_called_once_with(video=True)

    def test_get_model_parses_raw_json(self):
        self.fake_client.get_model.return_value = {
            "job_type": "seedance_2_0",
            "display_name": "Seedance 2.0",
            "params": [],
        }

        model = self.provider.get_model("seedance_2_0")

        self.assertEqual(model.display_name, "Seedance 2.0")
        self.fake_client.get_model.assert_called_once_with("seedance_2_0")

    def test_estimate_cost_parses_raw_json(self):
        self.fake_client.estimate_cost.return_value = {"credits": 22.5}

        estimate = self.provider.estimate_cost(
            job_type="seedance_2_0",
            prompt="test",
            duration=5,
            resolution="720p",
            aspect_ratio="9:16",
        )

        self.assertEqual(estimate.credits, 22.5)
        self.assertEqual(estimate.job_type, "seedance_2_0")
        self.fake_client.estimate_cost.assert_called_once_with(
            job_type="seedance_2_0",
            prompt="test",
            duration=5,
            resolution="720p",
            aspect_ratio="9:16",
        )

    def test_get_job_parses_raw_json(self):
        self.fake_client.get_job.return_value = {
            "id": "job-123",
            "job_type": "seedance_2_0",
            "status": "running",
        }

        job = self.provider.get_job("job-123")

        self.assertEqual(job.job_id, "job-123")
        self.assertEqual(job.status, JobStatus.RUNNING)

    def test_wait_for_job_parses_video_result(self):
        self.fake_client.wait_for_job.return_value = {
            "id": "job-123",
            "status": "succeeded",
            "outputs": [{"url": "https://example.invalid/video.mp4"}],
        }

        result = self.provider.wait_for_job("job-123", timeout_seconds=5)

        self.assertTrue(result.succeeded)
        self.assertEqual(result.output_urls, ("https://example.invalid/video.mp4",))

    def test_create_job_is_disabled_and_never_touches_the_client(self):
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            self.provider.create_job("seedance_2_0", "prompt de test")

        # Garantie de sécurité centrale de cette phase : le garde-fou
        # intervient AVANT tout appel au client CLI sous-jacent.
        self.fake_client.create_job.assert_not_called()

    def test_create_job_disabled_regardless_of_model(self):
        # Le garde-fou n'est pas spécifique à seedance_2_0 : il bloque
        # toute génération réelle, quel que soit le job_type demandé.
        for job_type in ("seedance_2_0", "kling3_0", "veo3_1"):
            with self.subTest(job_type=job_type):
                with self.assertRaises(HiggsfieldRealGenerationDisabledError):
                    self.provider.create_job(job_type, "prompt de test")

        self.fake_client.create_job.assert_not_called()

    def test_list_models_is_not_coupled_to_any_specific_model(self):
        # Le Provider doit rester agnostique du modèle : ici on simule
        # un catalogue ne contenant PAS seedance_2_0, et tout doit
        # fonctionner normalement (aucune hypothèse codée en dur).
        self.fake_client.list_models.return_value = [
            {"job_type": "kling3_0", "display_name": "Kling v3.0", "params": []},
        ]

        models = self.provider.list_models(video=True)

        self.assertEqual([m.job_type for m in models], ["kling3_0"])

    # --------------------------------------------------------------
    # Propagation d'erreurs (le Provider ne doit ni avaler ni masquer
    # les erreurs typées levées par le Client)
    # --------------------------------------------------------------

    def test_get_job_propagates_client_timeout(self):
        self.fake_client.get_job.side_effect = HiggsfieldTimeoutError("timed out")

        with self.assertRaises(HiggsfieldTimeoutError):
            self.provider.get_job("job-123")

    def test_wait_for_job_propagates_client_timeout(self):
        self.fake_client.wait_for_job.side_effect = HiggsfieldTimeoutError("timed out")

        with self.assertRaises(HiggsfieldTimeoutError):
            self.provider.wait_for_job("job-123", timeout_seconds=1)

    def test_estimate_cost_propagates_client_errors(self):
        self.fake_client.estimate_cost.side_effect = HiggsfieldTimeoutError("timed out")

        with self.assertRaises(HiggsfieldTimeoutError):
            self.provider.estimate_cost(job_type="seedance_2_0", prompt="test")

    # --------------------------------------------------------------
    # Réponses invalides (forme JSON inattendue)
    # --------------------------------------------------------------

    def test_get_job_raises_on_non_dict_response(self):
        self.fake_client.get_job.return_value = ["not", "a", "dict"]

        with self.assertRaises(HiggsfieldInvalidResponseError):
            self.provider.get_job("job-123")

    def test_wait_for_job_raises_on_non_dict_response(self):
        self.fake_client.wait_for_job.return_value = "unexpected-string"

        with self.assertRaises(HiggsfieldInvalidResponseError):
            self.provider.wait_for_job("job-123", timeout_seconds=1)

    def test_list_models_raises_on_non_list_response(self):
        self.fake_client.list_models.return_value = {"not": "a list"}

        with self.assertRaises(HiggsfieldInvalidResponseError):
            self.provider.list_models()

    def test_list_models_raises_on_non_dict_entry(self):
        self.fake_client.list_models.return_value = ["not-a-dict-entry"]

        with self.assertRaises(HiggsfieldInvalidResponseError):
            self.provider.list_models()

    def test_get_model_raises_on_non_dict_response(self):
        self.fake_client.get_model.return_value = None

        # Le client peut renvoyer None (stdout vide) -> le Provider le
        # normalise en {} avant validation ; ici on force explicitement
        # une forme invalide (liste) pour vérifier la détection.
        self.fake_client.get_model.return_value = ["invalid"]

        with self.assertRaises(HiggsfieldInvalidResponseError):
            self.provider.get_model("seedance_2_0")

    def test_estimate_cost_raises_on_non_dict_response(self):
        self.fake_client.estimate_cost.return_value = [1, 2, 3]

        with self.assertRaises(HiggsfieldInvalidResponseError):
            self.provider.estimate_cost(job_type="seedance_2_0", prompt="test")


if __name__ == "__main__":
    unittest.main()
