"""
Tests — Phase P2.3, verrou 5 : aucune valeur par défaut ni modification
future ne peut transformer silencieusement une tâche nécessitant une
approbation en tâche automatiquement approuvée.

RISQUE VERROUILLÉ : un futur changement de code pourrait, par erreur,
faire de `approved=True` le défaut d'un paramètre quelque part dans la
chaîne (VideoAgent, TaskManager, AIDirector), ou faire en sorte qu'un
coût CONNU et un budget suffisant suffisent seuls à approuver une
génération sans validation humaine explicite. Ce fichier verrouille
les deux angles :
- INSPECTION DE SIGNATURE : chaque paramètre nommé `approved` dans la
  chaîne réelle a pour défaut `False` (jamais `True`).
- COMPORTEMENT : un coût connu + un budget suffisant, SANS approbation
  explicite, reste `NEEDS_APPROVAL` — jamais `APPROVED` — et
  `GenerationJobService` ne crée jamais de job dans ce cas.

Conformément aux contraintes de cette phase, `approved=True` est utilisé
ci-dessous UNIQUEMENT comme donnée de test légitime dans un scénario qui
DOIT rester bloqué pour une autre raison (budget insuffisant) — jamais
pour masquer ou contourner un problème de sécurité.

Aucun appel CLI réel, aucune génération, aucun crédit consommé.
"""

import inspect
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
    GenerationRequest,
)
from agents.generation_job_service import (
    GenerationJobExecutionError,
    GenerationJobService,
)
from agents.production_model import PRODUCTION_MODEL
from agents.task_manager import TaskManager
from agents.video_agent import VideoAgent
from director import AIDirector
from integrations.higgsfield.provider import BaseHiggsfieldProvider
from integrations.higgsfield.types import CostEstimate, Job, JobStatus, ModelParam, ModelSchema, VideoResult


class _KnownCostSufficientBudgetProvider(BaseHiggsfieldProvider):
    """Coût CONNU, budget SUFFISANT — le seul facteur qui doit rester
    bloquant, en l'absence d'approbation explicite, est l'ABSENCE
    d'approbation elle-même."""

    def __init__(self):
        self.create_job_call_count = 0

    def list_models(self, video: bool = True) -> List[ModelSchema]:
        return [self._schema()]

    def _schema(self) -> ModelSchema:
        return ModelSchema(
            job_type=PRODUCTION_MODEL,
            display_name="Seedance 2.0",
            params=(
                ModelParam(name="prompt", type="string", required=True),
                ModelParam(name="duration", type="integer", required=False, default=5),
            ),
        )

    def get_model(self, job_type: str) -> ModelSchema:
        return self._schema()

    def estimate_cost(self, job_type, prompt, duration=None, resolution=None, aspect_ratio=None):
        return CostEstimate(job_type=job_type, credits=10.0)

    def get_account_balance(self) -> Optional[float]:
        return 1000.0  # largement suffisant pour couvrir les 10.0 crédits

    def create_job(self, job_type: str, prompt: str, **params: Any) -> Job:
        self.create_job_call_count += 1
        raise AssertionError(
            "create_job ne doit JAMAIS être appelé sans approbation explicite."
        )

    def get_job(self, job_id: str) -> Job:
        raise AssertionError("get_job ne doit jamais être appelé dans ces tests.")

    def wait_for_job(self, job_id, timeout_seconds=600, interval_seconds=3) -> VideoResult:
        raise AssertionError("wait_for_job ne doit jamais être appelé dans ces tests.")


def _known_cost_request(approved: bool) -> GenerationRequest:
    return GenerationRequest(
        request_id="005",
        job_type=PRODUCTION_MODEL,
        prompt="Un prompt de test.",
        duration=5,
        resolution="720p",
        aspect_ratio="9:16",
        approved=approved,
    )


class TestNoCallableDefaultsApprovedToTrue(unittest.TestCase):
    """Inspection de signature : aucun défaut dangereux `approved=True`."""

    def _assert_default_is_false(self, callable_obj, label):
        signature = inspect.signature(callable_obj)
        param = signature.parameters.get("approved")
        self.assertIsNotNone(param, f"{label} devrait exposer un paramètre 'approved'.")
        if param.default is not inspect._empty:
            self.assertIs(
                param.default,
                False,
                f"{label}.approved a un défaut dangereux : {param.default!r}",
            )

    def test_generation_request_dataclass_default(self):
        self._assert_default_is_false(GenerationRequest, "GenerationRequest")

    def test_video_agent_build_request_default(self):
        self._assert_default_is_false(VideoAgent.build_request, "VideoAgent.build_request")

    def test_video_agent_run_default(self):
        self._assert_default_is_false(VideoAgent.run, "VideoAgent.run")

    def test_director_run_video_mission_default(self):
        self._assert_default_is_false(
            AIDirector.run_video_mission, "AIDirector.run_video_mission"
        )

    def test_task_manager_process_default(self):
        self._assert_default_is_false(TaskManager.process, "TaskManager.process")

    def test_task_manager_process_next_pending_default(self):
        self._assert_default_is_false(
            TaskManager.process_next_pending, "TaskManager.process_next_pending"
        )


class TestKnownCostSufficientBudgetStillRequiresExplicitApproval(unittest.TestCase):
    """Comportement : coût connu + budget suffisant + pas d'approbation
    explicite => NEEDS_APPROVAL, jamais APPROVED, jamais de job créé."""

    def test_gate_returns_needs_approval_not_approved(self):
        provider = _KnownCostSufficientBudgetProvider()
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_known_cost_request(approved=False))

        self.assertEqual(result.decision, GenerationApprovalDecision.NEEDS_APPROVAL)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)

    def test_job_service_never_creates_a_job_without_explicit_approval(self):
        provider = _KnownCostSufficientBudgetProvider()
        gate = GenerationApprovalGate(provider)
        job_service = GenerationJobService(provider, gate)

        with self.assertRaises(GenerationJobExecutionError) as ctx:
            job_service.execute(_known_cost_request(approved=False))

        self.assertEqual(
            ctx.exception.approval.decision, GenerationApprovalDecision.NEEDS_APPROVAL
        )
        self.assertEqual(provider.create_job_call_count, 0)

    def test_explicit_approval_alone_does_not_bypass_a_real_budget_block(self):
        # Utilisation légitime de approved=True : ce scénario DOIT rester
        # bloqué pour une raison INDÉPENDANTE (budget insuffisant), donc
        # approved=True ne masque ici aucun problème de sécurité — il
        # prouve au contraire que l'approbation seule ne suffit jamais.
        class _InsufficientBudgetProvider(_KnownCostSufficientBudgetProvider):
            def get_account_balance(self):
                return 0.0

        provider = _InsufficientBudgetProvider()
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_known_cost_request(approved=True))

        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)
        self.assertEqual(provider.create_job_call_count, 0)


if __name__ == "__main__":
    unittest.main()
