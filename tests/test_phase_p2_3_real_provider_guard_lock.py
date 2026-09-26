"""
Tests — Phase P2.3, verrou 6 : HiggsfieldProvider.create_job() (réel)
reste bloqué par HiggsfieldRealGenerationDisabledError, levée AVANT
tout appel au client Higgsfield sous-jacent — jamais contournable.

RISQUE VERROUILLÉ : un futur refactor pourrait accidentellement
appeler `self.client.create_job(...)` (ou toute autre méthode du
client) avant de lever l'erreur, ou déplacer la levée après une
tentative d'appel réseau/CLI, ouvrant la voie à une génération réelle
facturable. Ce fichier verrouille que :
- l'erreur est bien HiggsfieldRealGenerationDisabledError ;
- le client injecté n'est JAMAIS appelé, sous aucune forme (aucune
  méthode, aucun attribut) — vérifié avec un espion strict qui lève
  immédiatement si on le sollicite ;
- ceci reste vrai quel que soit le job_type demandé (y compris
  PRODUCTION_MODEL, le modèle réel de production).

Ce fichier ne modifie ni ne contourne jamais ce garde-fou.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.production_model import PRODUCTION_MODEL
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.provider import HiggsfieldProvider


class _NeverCalledClient:
    """Espion strict : toute utilisation (attribut ou appel) échoue le test."""

    def __getattr__(self, name):
        raise AssertionError(
            f"HiggsfieldClient.{name} a été sollicité alors que le garde-fou "
            f"doit lever AVANT tout accès au client réel."
        )


class TestRealProviderCreateJobHardGuard(unittest.TestCase):

    def setUp(self):
        self.spy_client = _NeverCalledClient()
        self.provider = HiggsfieldProvider(client=self.spy_client)

    def test_create_job_raises_the_typed_disabled_error(self):
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            self.provider.create_job(job_type=PRODUCTION_MODEL, prompt="test")

    def test_create_job_never_touches_the_underlying_client(self):
        # Si create_job() appelait ne serait-ce qu'un seul attribut du
        # client avant de lever, _NeverCalledClient.__getattr__ lèverait
        # une AssertionError au lieu de HiggsfieldRealGenerationDisabledError.
        try:
            self.provider.create_job(job_type=PRODUCTION_MODEL, prompt="test")
            self.fail("create_job() aurait dû lever une exception.")
        except HiggsfieldRealGenerationDisabledError:
            pass  # attendu : le garde-fou a levé sans toucher au client.
        except AssertionError:
            raise  # le client a été sollicité : régression du garde-fou.

    def test_guard_holds_regardless_of_job_type(self):
        for job_type in (PRODUCTION_MODEL, "cinematic_studio_video_4_0", "anything_else"):
            with self.subTest(job_type=job_type):
                with self.assertRaises(HiggsfieldRealGenerationDisabledError):
                    self.provider.create_job(job_type=job_type, prompt="test")

    def test_guard_holds_regardless_of_extra_params(self):
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            self.provider.create_job(
                job_type=PRODUCTION_MODEL,
                prompt="test",
                duration=15,
                resolution="720p",
                aspect_ratio="9:16",
                approved=True,
            )

    def test_default_client_construction_is_never_reached_either(self):
        # Sans client injecté, HiggsfieldProvider() en construit un réel en
        # interne (integrations/higgsfield/client.py) — mais create_job()
        # doit lever avant même d'y toucher : on le vérifie avec un Mock
        # espion posé après construction.
        provider = HiggsfieldProvider()
        provider.client = MagicMock()

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            provider.create_job(job_type=PRODUCTION_MODEL, prompt="test")

        provider.client.assert_not_called()
        self.assertEqual(provider.client.method_calls, [])


if __name__ == "__main__":
    unittest.main()
