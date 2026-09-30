"""
Tests — Phase P2.3, verrou 4 : les paramètres réels de coût
(model=seedance_2_0, duration=15, resolution, aspect_ratio, prompt)
traversent GenerationCostService -> BaseHiggsfieldProvider sans être
altérés, tronqués, ou remplacés par une valeur implicite.

RISQUE VERROUILLÉ : la combinaison des bugs P2.1 (transport CLI
multi-lignes) et P2.2 (mauvais job_type) pouvait faire parvenir au
Provider un job_type différent de celui demandé, une durée
silencieusement retombée à 5s, ou un prompt tronqué — sans jamais lever
d'erreur. ATTENTION : ce fichier teste la couche GenerationCostService
(Phase F) avec un faux Provider capturant les arguments EXACTS reçus —
il ne remplace pas les tests P2.1 (transport CLI réel) ni P2.2 (modèle
unique), il verrouille la fidélité de bout en bout au niveau métier.

Aucun test de ce fichier n'appelle le CLI Higgsfield réel, ni ne crée
de job. Aucun crédit consommé.
"""

import sys
import unittest
from pathlib import Path
from typing import Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.authorization_content_helpers import content_media
from tests.real_provider_path_fixtures import fixture_real_path_gate_kwargs
from agents.generation_approval_gate import GenerationApprovalGate, GenerationRequest
from agents.generation_cost_service import GenerationCostService
from agents.production_model import PRODUCTION_MODEL
from integrations.higgsfield.provider import BaseHiggsfieldProvider
from integrations.higgsfield.types import CostEstimate, Job, JobStatus, ModelParam, ModelSchema, VideoResult

REAL_MULTILINE_MASTER_PROMPT_005_LIKE = "\n".join(
    [
        "ZEPHYR AI — MASTER PRODUCTION PROMPT",
        "====================================",
        "VIDEO ID",
        "005",
        "1. CHARACTER IDENTITY",
        "Keep the face and identity visually consistent across every scene.",
        "2. VISUAL STYLE",
        "Premium cinematic AI / future / mindset content.",
        "3. VIDEO-SPECIFIC DIRECTION",
        "Format: Duration 40 seconds. Aspect ratio: 9:16.",
        "END MASTER PROMPT",
    ]
)


class _RecordingProvider(BaseHiggsfieldProvider):
    """Capture, sans jamais y toucher, les arguments exacts reçus."""

    def __init__(self):
        self.estimate_cost_calls: List[dict] = []
        self.create_job_calls: List[dict] = []

    def list_models(self, video: bool = True) -> List[ModelSchema]:
        return [self._schema()]

    def _schema(self) -> ModelSchema:
        return ModelSchema(
            job_type=PRODUCTION_MODEL,
            display_name="Seedance 2.0",
            params=(
                ModelParam(name="prompt", type="string", required=True),
                ModelParam(name="duration", type="integer", required=False, default=5),
                ModelParam(name="resolution", type="string", required=False, default="720p"),
                ModelParam(name="aspect_ratio", type="string", required=False, default="16:9"),
                ModelParam(name="start_image", type="object|null", required=False),
                ModelParam(name="image_references", type="array", required=False),
            ),
        )

    def get_model(self, job_type: str) -> ModelSchema:
        return self._schema()

    def estimate_cost(self, job_type, prompt, duration=None, resolution=None, aspect_ratio=None):
        self.estimate_cost_calls.append(
            {
                "job_type": job_type,
                "prompt": prompt,
                "duration": duration,
                "resolution": resolution,
                "aspect_ratio": aspect_ratio,
            }
        )
        return CostEstimate(job_type=job_type, credits=67.5)

    def get_account_balance(self) -> Optional[float]:
        return 1.41

    def create_job(self, job_type: str, prompt: str, **params: Any) -> Job:
        self.create_job_calls.append({"job_type": job_type, "prompt": prompt, **params})
        raise AssertionError("create_job ne doit jamais être appelé dans ces tests.")

    def get_job(self, job_id: str) -> Job:
        raise AssertionError("get_job ne doit jamais être appelé dans ces tests.")

    def wait_for_job(self, job_id, timeout_seconds=600, interval_seconds=3) -> VideoResult:
        raise AssertionError("wait_for_job ne doit jamais être appelé dans ces tests.")


class TestGenerationCostServiceForwardsExactParameters(unittest.TestCase):
    """Verrou 4 : GenerationCostService transmet exactement les paramètres reçus."""

    def setUp(self):
        self.provider = _RecordingProvider()
        self.cost_service = GenerationCostService(self.provider)

    def test_all_parameters_reach_the_provider_unmodified(self):
        self.cost_service.estimate(
            job_type=PRODUCTION_MODEL,
            prompt=REAL_MULTILINE_MASTER_PROMPT_005_LIKE,
            duration=15,
            resolution="720p",
            aspect_ratio="9:16",
        )

        self.assertEqual(len(self.provider.estimate_cost_calls), 1)
        call = self.provider.estimate_cost_calls[0]

        self.assertEqual(call["job_type"], PRODUCTION_MODEL)
        self.assertEqual(call["prompt"], REAL_MULTILINE_MASTER_PROMPT_005_LIKE)
        self.assertEqual(call["duration"], 15)
        self.assertEqual(call["resolution"], "720p")
        self.assertEqual(call["aspect_ratio"], "9:16")

    def test_duration_never_silently_becomes_five(self):
        self.cost_service.estimate(
            job_type=PRODUCTION_MODEL,
            prompt=REAL_MULTILINE_MASTER_PROMPT_005_LIKE,
            duration=15,
            resolution="720p",
            aspect_ratio="9:16",
        )

        received_duration = self.provider.estimate_cost_calls[0]["duration"]
        self.assertEqual(received_duration, 15)
        self.assertNotEqual(received_duration, 5)

    def test_model_never_silently_changes(self):
        self.cost_service.estimate(
            job_type=PRODUCTION_MODEL,
            prompt=REAL_MULTILINE_MASTER_PROMPT_005_LIKE,
            duration=15,
            resolution="720p",
            aspect_ratio="9:16",
        )

        received_job_type = self.provider.estimate_cost_calls[0]["job_type"]
        self.assertEqual(received_job_type, PRODUCTION_MODEL)
        self.assertNotEqual(received_job_type, "cinematic_studio_video_4_0")

    def test_prompt_is_never_truncated(self):
        self.cost_service.estimate(
            job_type=PRODUCTION_MODEL,
            prompt=REAL_MULTILINE_MASTER_PROMPT_005_LIKE,
            duration=15,
            resolution="720p",
            aspect_ratio="9:16",
        )

        received_prompt = self.provider.estimate_cost_calls[0]["prompt"]
        self.assertEqual(received_prompt, REAL_MULTILINE_MASTER_PROMPT_005_LIKE)
        self.assertEqual(
            received_prompt.count("\n"),
            REAL_MULTILINE_MASTER_PROMPT_005_LIKE.count("\n"),
        )
        # Le point de rupture historique : la première ligne seule ne
        # doit jamais suffire à représenter le prompt reçu.
        self.assertNotEqual(received_prompt, REAL_MULTILINE_MASTER_PROMPT_005_LIKE.split("\n")[0])


class TestApprovalGateEndToEndParameterFidelity(unittest.TestCase):
    """Même verrou, vérifié via GenerationApprovalGate.evaluate() (chemin réel)."""

    def test_full_request_parameters_reach_the_provider_unmodified(self):
        provider = _RecordingProvider()
        request = GenerationRequest(
            **content_media(),
            request_id="005",
            job_type=PRODUCTION_MODEL,
            prompt=REAL_MULTILINE_MASTER_PROMPT_005_LIKE,
            duration=15,
            resolution="720p",
            aspect_ratio="9:16",
            approved=False,
        )
        # Phase D : Provider instrumenté (non reconnu comme mock) -> fixtures
        # EXPLICITES : plafond + Identity Lock lié au contenu exact.
        gate = GenerationApprovalGate(provider, **fixture_real_path_gate_kwargs(request))

        gate.evaluate(request)

        self.assertEqual(len(provider.estimate_cost_calls), 1)
        call = provider.estimate_cost_calls[0]

        self.assertEqual(call["job_type"], PRODUCTION_MODEL)
        self.assertEqual(call["prompt"], REAL_MULTILINE_MASTER_PROMPT_005_LIKE)
        self.assertEqual(call["duration"], 15)
        self.assertEqual(call["resolution"], "720p")
        self.assertEqual(call["aspect_ratio"], "9:16")

        # Aucun job réel n'est créé lors d'une simple estimation.
        self.assertEqual(provider.create_job_calls, [])


if __name__ == "__main__":
    unittest.main()
