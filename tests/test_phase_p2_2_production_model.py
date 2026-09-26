"""
Tests — Phase P2.2 : source unique de vérité pour le modèle de
production Higgsfield ("seedance_2_0").

CONTEXTE (Phase P2, audit) : avant P2.2, `CostEngine.evaluate_plan()`
interrogeait `plan.workflow` ("cinematic_studio_video_4_0", un WORKFLOW
V1, agents/planner.py) comme s'il s'agissait du modèle réel de
production, alors que la chaîne V2 (VideoAgent, GenerationApprovalGate)
utilise "seedance_2_0". Deux moteurs de coût concurrents et divergents
en résultaient. `agents/production_model.py` (PRODUCTION_MODEL) est
désormais l'unique source, importée par VideoAgent,
GenerationApprovalGate et CostEngine.

Aucun test de ce fichier n'appelle le CLI Higgsfield réel : CostEngine
est testé avec un faux client (`_FakeHiggsfieldClient`) capturant
exactement les arguments reçus. Aucun réseau, aucune génération, aucun
crédit consommé.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.cost_engine import CostEngine
from agents.generation_approval_gate import CONFIRMED_DURATIONS_BY_MODEL
from agents.planner import VideoPlanner
from agents.production_model import PRODUCTION_MODEL
from agents.video_agent import DEFAULT_JOB_TYPE
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider

WORKFLOW_V1_IDENTIFIER = "cinematic_studio_video_4_0"


class _FakeHiggsfieldClient:
    """Capture les arguments réels transmis par CostEngine, sans CLI/réseau."""

    def __init__(self, cost_response=None, balance=1.41):
        self.cost_response = cost_response or {"credits": 67.5}
        self.balance = balance
        self.estimate_cost_calls = []

    def estimate_cost(self, job_type, prompt, duration, resolution, aspect_ratio):
        self.estimate_cost_calls.append(
            {
                "job_type": job_type,
                "prompt": prompt,
                "duration": duration,
                "resolution": resolution,
                "aspect_ratio": aspect_ratio,
            }
        )
        return self.cost_response

    def account_status(self):
        return {"credits": self.balance}


def _build_zephyr_005_plan():
    planner = VideoPlanner(PROJECT_ROOT)
    return planner.create_zephyr_plan(
        video_id="005",
        title="Pourquoi la discipline vaut plus que le talent.",
        hook="Le talent impressionne. La discipline construit des empires.",
        objective="Test.",
    )


class TestSingleSourceOfTruthForProductionModel(unittest.TestCase):
    """1 & 2. Une même VideoPlan / VideoAgent / GenerationApprovalGate
    utilisent tous exactement la même source de vérité."""

    def test_production_model_constant_is_seedance_2_0(self):
        self.assertEqual(PRODUCTION_MODEL, "seedance_2_0")

    def test_video_agent_default_job_type_is_the_shared_constant(self):
        self.assertEqual(DEFAULT_JOB_TYPE, PRODUCTION_MODEL)

    def test_generation_approval_gate_duration_table_is_keyed_by_shared_constant(self):
        self.assertIn(PRODUCTION_MODEL, CONFIRMED_DURATIONS_BY_MODEL)
        self.assertEqual(CONFIRMED_DURATIONS_BY_MODEL[PRODUCTION_MODEL], (5, 10, 15))

    def test_video_plan_workflow_is_not_used_as_the_production_model(self):
        # VideoPlan.workflow reste un identifiant V1 légitime (schéma
        # d'assets/workflow), mais ne doit JAMAIS être confondu avec le
        # modèle réel de production.
        plan = _build_zephyr_005_plan()
        self.assertEqual(plan.workflow, WORKFLOW_V1_IDENTIFIER)
        self.assertNotEqual(plan.workflow, PRODUCTION_MODEL)


class TestCostEngineNoLongerUsesTheWorkflowIdentifier(unittest.TestCase):
    """3 & 4. Aucun appel réel de coût ne reçoit cinematic_studio_video_4_0 ;
    CostEngine/ProductionGate ne le présentent plus comme modèle réel."""

    def test_evaluate_plan_queries_production_model_not_the_workflow(self):
        plan = _build_zephyr_005_plan()
        engine = CostEngine()
        engine.higgsfield = _FakeHiggsfieldClient()

        result = engine.evaluate_plan(plan, prompt="Un Master Prompt non vide.")

        self.assertEqual(len(engine.higgsfield.estimate_cost_calls), 1)
        call = engine.higgsfield.estimate_cost_calls[0]

        self.assertEqual(call["job_type"], PRODUCTION_MODEL)
        self.assertNotEqual(call["job_type"], WORKFLOW_V1_IDENTIFIER)

    def test_cost_estimate_target_is_production_model(self):
        plan = _build_zephyr_005_plan()
        engine = CostEngine()
        engine.higgsfield = _FakeHiggsfieldClient()

        result = engine.evaluate_plan(plan, prompt="Un Master Prompt non vide.")

        self.assertEqual(result.target, PRODUCTION_MODEL)
        self.assertNotEqual(result.target, WORKFLOW_V1_IDENTIFIER)

    def test_missing_prompt_still_reports_production_model_as_target(self):
        # Même sur le chemin d'échec précoce (prompt manquant), le
        # target rapporté ne doit jamais être le workflow V1.
        plan = _build_zephyr_005_plan()
        engine = CostEngine()
        engine.higgsfield = _FakeHiggsfieldClient()

        result = engine.evaluate_plan(plan, prompt=None)

        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.target, PRODUCTION_MODEL)


class TestApprovalGateDurationTableUnaffected(unittest.TestCase):
    """5. GenerationApprovalGate continue à valider 5/10/15 secondes."""

    def test_confirmed_durations_unchanged(self):
        self.assertEqual(
            CONFIRMED_DURATIONS_BY_MODEL[PRODUCTION_MODEL],
            (5, 10, 15),
        )


class TestRealGenerationGuardStillActive(unittest.TestCase):
    """6. HiggsfieldProvider.create_job() réel lève toujours le garde-fou,
    y compris pour une requête ciblant explicitement PRODUCTION_MODEL."""

    def test_real_provider_create_job_raises_for_production_model(self):
        provider = HiggsfieldProvider()

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            provider.create_job(job_type=PRODUCTION_MODEL, prompt="test")

    def test_mock_provider_unaffected_by_this_phase(self):
        # Non-régression : le Mock (utilisé par tous les tests de
        # génération) continue de fonctionner normalement.
        provider = MockHiggsfieldProvider()
        job = provider.create_job(job_type=PRODUCTION_MODEL, prompt="test")
        self.assertIsNotNone(job.job_id)


if __name__ == "__main__":
    unittest.main()
