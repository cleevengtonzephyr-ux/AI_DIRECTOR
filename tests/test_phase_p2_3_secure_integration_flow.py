"""
Tests — Phase P2.3, verrou 9 : flux d'intégration sécurisé de bout en
bout, VideoPlan -> VideoAgent -> GenerationApprovalGate ->
GenerationCostService -> GenerationJobService, avec PRODUCTION_MODEL,
duration=15 et le VRAI Master Prompt 005 (multi-lignes, assemblé par
PromptAssemblySystem — aucune reconstruction ni simplification).

Ce test verrouille que TOUTES les couches reçoivent exactement les
mêmes paramètres (modèle, durée, resolution, aspect_ratio, prompt
intégral) et que :
- un budget insuffisant produit BLOCKED (jamais d'approbation
  silencieuse) ;
- un coût connu avec budget suffisant, sans approbation explicite,
  reste NEEDS_APPROVAL ;
- dans les deux cas, AUCUN job n'est créé, AUCUNE génération réelle
  n'a lieu.

Un faux Provider (implémentant BaseHiggsfieldProvider, jamais le
HiggsfieldProvider réel ni MockHiggsfieldProvider) capture chaque appel
pour permettre des assertions fines sur les paramètres reçus par
chaque couche. Aucun CLI réel, aucun réseau, aucun crédit consommé.
"""

import sys
import unittest
from pathlib import Path
from typing import Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
)
from agents.generation_job_service import (
    GenerationJobExecutionError,
    GenerationJobService,
)
from agents.planner import VideoPlanner
from agents.production_model import PRODUCTION_MODEL
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.video_agent import VideoAgent
from integrations.higgsfield.provider import BaseHiggsfieldProvider
from integrations.higgsfield.types import CostEstimate, Job, JobStatus, ModelParam, ModelSchema, VideoResult


class _RecordingProvider(BaseHiggsfieldProvider):
    """Capture chaque paramètre reçu à chaque étage, sans jamais y toucher."""

    def __init__(self, cost: float, balance: float):
        self._cost = cost
        self._balance = balance
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
        return CostEstimate(job_type=job_type, credits=self._cost)

    def get_account_balance(self) -> Optional[float]:
        return self._balance

    def create_job(self, job_type: str, prompt: str, **params: Any) -> Job:
        self.create_job_calls.append({"job_type": job_type, "prompt": prompt, **params})
        return Job(job_id="should-not-happen", job_type=job_type, status=JobStatus.QUEUED)

    def get_job(self, job_id: str) -> Job:
        raise AssertionError("get_job ne doit jamais être appelé dans ces tests.")

    def wait_for_job(self, job_id, timeout_seconds=600, interval_seconds=3) -> VideoResult:
        raise AssertionError("wait_for_job ne doit jamais être appelé dans ces tests.")


def _build_real_005_request(provider_cost: float, provider_balance: float):
    """Construit une GenerationRequest via la VRAIE chaîne V1 de
    préparation (VideoPlanner + PromptAssemblySystem), traduite par
    VideoAgent — comme le fait réellement director.run_video_mission()."""

    planner = VideoPlanner(PROJECT_ROOT)
    plan = planner.create_zephyr_plan(
        video_id="005",
        title="Pourquoi la discipline vaut plus que le talent.",
        hook="Le talent impressionne. La discipline construit des empires.",
        objective="Créer une vidéo courte et motivante.",
    )

    prompt_assembly = PromptAssemblySystem(PROJECT_ROOT)
    real_master_prompt = prompt_assembly.assemble("005")

    agent = VideoAgent(prompt_assembly=prompt_assembly)
    request = agent.build_request(plan, approved=False)

    provider = _RecordingProvider(cost=provider_cost, balance=provider_balance)
    gate = GenerationApprovalGate(provider)
    job_service = GenerationJobService(provider, gate)

    return request, real_master_prompt, provider, gate, job_service, plan


class TestSecureEndToEndIntegrationFlow(unittest.TestCase):

    def test_the_real_master_prompt_is_multiline_and_duration_is_fifteen(self):
        request, real_master_prompt, *_ = _build_real_005_request(
            provider_cost=67.5, provider_balance=1.41
        )

        self.assertGreater(real_master_prompt.count("\n"), 50)
        self.assertEqual(request.prompt, real_master_prompt)
        self.assertEqual(request.duration, 15)
        self.assertEqual(request.job_type, PRODUCTION_MODEL)

    def test_insufficient_budget_blocks_without_silent_approval(self):
        request, real_master_prompt, provider, gate, job_service, _ = _build_real_005_request(
            provider_cost=67.5, provider_balance=1.41,
        )

        with self.assertRaises(GenerationJobExecutionError) as ctx:
            job_service.execute(request)

        self.assertEqual(ctx.exception.approval.decision, GenerationApprovalDecision.BLOCKED)
        self.assertEqual(provider.create_job_calls, [])

        # Toutes les couches ont bien reçu les MÊMES paramètres.
        self.assertEqual(len(provider.estimate_cost_calls), 1)
        call = provider.estimate_cost_calls[0]
        self.assertEqual(call["job_type"], PRODUCTION_MODEL)
        self.assertEqual(call["prompt"], real_master_prompt)
        self.assertEqual(call["duration"], 15)

    def test_sufficient_budget_without_explicit_approval_needs_approval_not_executed(self):
        request, real_master_prompt, provider, gate, job_service, _ = _build_real_005_request(
            provider_cost=10.0, provider_balance=1000.0,
        )

        with self.assertRaises(GenerationJobExecutionError) as ctx:
            job_service.execute(request)

        self.assertEqual(
            ctx.exception.approval.decision, GenerationApprovalDecision.NEEDS_APPROVAL
        )
        self.assertEqual(provider.create_job_calls, [])
        self.assertEqual(
            provider.estimate_cost_calls[0]["prompt"], real_master_prompt
        )

    def test_no_real_generation_occurs_in_either_scenario(self):
        for cost, balance in ((67.5, 1.41), (10.0, 1000.0)):
            with self.subTest(cost=cost, balance=balance):
                request, _, provider, _, job_service, _ = _build_real_005_request(
                    provider_cost=cost, provider_balance=balance,
                )
                with self.assertRaises(GenerationJobExecutionError):
                    job_service.execute(request)
                self.assertEqual(provider.create_job_calls, [])


if __name__ == "__main__":
    unittest.main()
