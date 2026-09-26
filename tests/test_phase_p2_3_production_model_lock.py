"""
Tests — Phase P2.3, verrous 2 & 8 : source unique du modèle de
production et exclusion du modèle legacy des chemins réels.

RISQUE VERROUILLÉ : avant P2.2, `CostEngine.evaluate_plan()`
interrogeait silencieusement `plan.workflow` ("cinematic_studio_video_4_0",
un WORKFLOW V1) au lieu du vrai modèle de production
("seedance_2_0"), produisant un coût pour un modèle DIFFÉRENT de celui
réellement utilisé en génération. Ces tests verrouillent :
- qu'une seule constante (agents.production_model.PRODUCTION_MODEL)
  fait autorité dans toute la chaîne réelle (VideoAgent,
  GenerationApprovalGate, CostEngine) ;
- que "cinematic_studio_video_4_0" ne peut plus réapparaître comme
  job_type/target dans un appel réel de coût ou de job — sans
  interdire sa présence légitime ailleurs (agents/planner.py,
  documentation, tests de migration), qui reste un identifiant de
  WORKFLOW V1 valide pour ses propres usages.

Aucun test de ce fichier n'appelle le CLI Higgsfield réel : CostEngine
est testé avec un faux client capturant les arguments ;
GenerationApprovalGate/VideoAgent avec un faux Provider. Aucun réseau,
aucune génération, aucun crédit consommé.
"""

import sys
import unittest
from pathlib import Path
from typing import Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.cost_engine import CostEngine
from agents.generation_approval_gate import (
    CONFIRMED_DURATIONS_BY_MODEL,
    GenerationApprovalGate,
)
from agents.planner import VideoPlanner
from agents.production_model import PRODUCTION_MODEL
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.video_agent import DEFAULT_JOB_TYPE, VideoAgent
from integrations.higgsfield.provider import BaseHiggsfieldProvider
from integrations.higgsfield.types import CostEstimate, Job, JobStatus, ModelParam, ModelSchema, VideoResult

LEGACY_WORKFLOW_MODEL = "cinematic_studio_video_4_0"


def _build_zephyr_005_plan():
    planner = VideoPlanner(PROJECT_ROOT)
    return planner.create_zephyr_plan(
        video_id="005",
        title="Pourquoi la discipline vaut plus que le talent.",
        hook="Le talent impressionne. La discipline construit des empires.",
        objective="Test.",
    )


class _FakeHiggsfieldClientCapturingJobType:
    """Capture le job_type réellement envoyé, sans CLI/réseau."""

    def __init__(self):
        self.estimate_cost_calls: List[dict] = []

    def estimate_cost(self, job_type, prompt, duration, resolution, aspect_ratio):
        self.estimate_cost_calls.append({"job_type": job_type})
        return {"credits": 67.5}

    def account_status(self):
        return {"credits": 1.41}


class _SpyProvider(BaseHiggsfieldProvider):
    """Faux Provider capturant chaque job_type transmis à estimate_cost/create_job."""

    def __init__(self):
        self.estimate_cost_job_types: List[str] = []
        self.create_job_job_types: List[str] = []

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
        self.estimate_cost_job_types.append(job_type)
        return CostEstimate(job_type=job_type, credits=67.5)

    def get_account_balance(self) -> Optional[float]:
        return 1.41

    def create_job(self, job_type: str, prompt: str, **params: Any) -> Job:
        self.create_job_job_types.append(job_type)
        return Job(job_id="never-created", job_type=job_type, status=JobStatus.QUEUED)

    def get_job(self, job_id: str) -> Job:
        raise AssertionError("get_job ne doit jamais être appelé dans ces tests.")

    def wait_for_job(self, job_id, timeout_seconds=600, interval_seconds=3) -> VideoResult:
        raise AssertionError("wait_for_job ne doit jamais être appelé dans ces tests.")


class TestSingleSourceOfTruthAcrossTheRealChain(unittest.TestCase):
    """Verrou 2 : une seule source de vérité pour le modèle de production."""

    def test_production_model_is_seedance_2_0(self):
        self.assertEqual(PRODUCTION_MODEL, "seedance_2_0")

    def test_video_agent_default_job_type_matches(self):
        self.assertEqual(DEFAULT_JOB_TYPE, PRODUCTION_MODEL)

    def test_approval_gate_duration_table_keyed_by_the_same_constant(self):
        self.assertIn(PRODUCTION_MODEL, CONFIRMED_DURATIONS_BY_MODEL)
        self.assertEqual(CONFIRMED_DURATIONS_BY_MODEL[PRODUCTION_MODEL], (5, 10, 15))
        # Pas de doublon : une seule clé dans la table.
        self.assertEqual(len(CONFIRMED_DURATIONS_BY_MODEL), 1)

    def test_video_agent_build_request_uses_the_shared_constant_end_to_end(self):
        plan = _build_zephyr_005_plan()
        prompt_assembly = PromptAssemblySystem(PROJECT_ROOT)
        agent = VideoAgent(prompt_assembly=prompt_assembly)

        request = agent.build_request(plan)

        self.assertEqual(request.job_type, PRODUCTION_MODEL)

    def test_generation_approval_gate_receives_the_shared_constant(self):
        plan = _build_zephyr_005_plan()
        prompt_assembly = PromptAssemblySystem(PROJECT_ROOT)
        agent = VideoAgent(prompt_assembly=prompt_assembly)
        request = agent.build_request(plan)

        provider = _SpyProvider()
        gate = GenerationApprovalGate(provider)
        gate.evaluate(request)

        self.assertEqual(provider.estimate_cost_job_types, [PRODUCTION_MODEL])

    def test_cost_engine_queries_the_shared_constant_not_the_v1_workflow(self):
        plan = _build_zephyr_005_plan()
        engine = CostEngine()
        fake_client = _FakeHiggsfieldClientCapturingJobType()
        engine.higgsfield = fake_client

        result = engine.evaluate_plan(plan, prompt="Un Master Prompt non vide.")

        self.assertEqual(len(fake_client.estimate_cost_calls), 1)
        self.assertEqual(fake_client.estimate_cost_calls[0]["job_type"], PRODUCTION_MODEL)
        self.assertEqual(result.target, PRODUCTION_MODEL)


class TestLegacyModelNeverReachesARealCostOrJobCall(unittest.TestCase):
    """
    Verrou 8 : "cinematic_studio_video_4_0" ne doit plus jamais
    apparaître comme job_type dans un chemin réellement exécuté par la
    production (VideoAgent, GenerationApprovalGate, CostEngine, ou tout
    Provider). Ne vérifie PAS son absence du dépôt entier — sa présence
    dans agents/planner.py (VideoPlan.workflow, diagnostic V1) reste
    légitime et n'est pas concernée par ce verrou.
    """

    def test_video_plan_workflow_field_keeps_its_v1_identity_unused_as_model(self):
        plan = _build_zephyr_005_plan()
        # Le champ existe et vaut bien l'identifiant V1 (usage légitime
        # : schéma de workflow, diagnostic), mais n'est jamais lu comme
        # job_type par la chaîne réelle testée ci-dessous.
        self.assertEqual(plan.workflow, LEGACY_WORKFLOW_MODEL)

    def test_video_agent_never_forwards_the_legacy_workflow_as_job_type(self):
        plan = _build_zephyr_005_plan()
        prompt_assembly = PromptAssemblySystem(PROJECT_ROOT)
        agent = VideoAgent(prompt_assembly=prompt_assembly)

        request = agent.build_request(plan)

        self.assertNotEqual(request.job_type, LEGACY_WORKFLOW_MODEL)

    def test_generation_approval_gate_never_queries_the_legacy_workflow(self):
        plan = _build_zephyr_005_plan()
        prompt_assembly = PromptAssemblySystem(PROJECT_ROOT)
        agent = VideoAgent(prompt_assembly=prompt_assembly)
        request = agent.build_request(plan)

        provider = _SpyProvider()
        gate = GenerationApprovalGate(provider)
        gate.evaluate(request)

        self.assertNotIn(LEGACY_WORKFLOW_MODEL, provider.estimate_cost_job_types)
        self.assertNotIn(LEGACY_WORKFLOW_MODEL, provider.create_job_job_types)

    def test_cost_engine_never_queries_the_legacy_workflow(self):
        plan = _build_zephyr_005_plan()
        engine = CostEngine()
        fake_client = _FakeHiggsfieldClientCapturingJobType()
        engine.higgsfield = fake_client

        engine.evaluate_plan(plan, prompt="Un Master Prompt non vide.")

        queried_job_types = [c["job_type"] for c in fake_client.estimate_cost_calls]
        self.assertNotIn(LEGACY_WORKFLOW_MODEL, queried_job_types)

    def test_a_regression_reintroducing_the_legacy_model_would_be_caught(self):
        # Caractérisation explicite : si evaluate_plan() régressait vers
        # `target=plan.workflow`, ce test échouerait immédiatement.
        plan = _build_zephyr_005_plan()
        self.assertEqual(plan.workflow, LEGACY_WORKFLOW_MODEL)

        engine = CostEngine()
        fake_client = _FakeHiggsfieldClientCapturingJobType()
        engine.higgsfield = fake_client
        engine.evaluate_plan(plan, prompt="Un Master Prompt non vide.")

        actual = fake_client.estimate_cost_calls[0]["job_type"]
        self.assertNotEqual(actual, plan.workflow)
        self.assertEqual(actual, PRODUCTION_MODEL)


if __name__ == "__main__":
    unittest.main()
