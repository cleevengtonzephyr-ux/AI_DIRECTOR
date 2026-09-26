"""
Tests — Phase P2.3, verrou 7 : GenerationJobService réévalue TOUJOURS le
Gate au moment de l'exécution — une décision antérieure (même
APPROVED) ne suffit jamais à contourner une réévaluation fraîche.

RISQUE VERROUILLÉ (TOCTOU) : si GenerationJobService réutilisait une
décision d'approbation calculée plus tôt (par exemple transmise par
l'appelant) au lieu de rappeler `gate.evaluate(request)` juste avant
`create_job()`, une condition qui se dégrade entre-temps (budget
consommé ailleurs, coût recalculé différemment) pourrait laisser
passer une création de job qui ne serait plus autorisée au moment réel
de l'exécution.

Scénario : le solde du compte (simulé) est SUFFISANT au premier appel
à evaluate() puis CHUTE avant l'exécution — GenerationJobService doit
recalculer et bloquer, jamais se fier à la première décision.

`approved=True` est utilisé ici comme donnée de test légitime,
nécessaire pour atteindre la branche APPROVED lors du premier appel et
ainsi démontrer que ce n'est PAS suffisant pour garantir l'exécution —
il ne masque aucun problème de sécurité, il le met précisément en
évidence si la réévaluation venait à disparaître.

Aucun appel CLI réel, aucune génération, aucun crédit consommé.
"""

import dataclasses
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
    RealGenerationAuthorization,
)
from agents.generation_job_service import (
    GenerationJobExecutionError,
    GenerationJobService,
)
from agents.production_model import PRODUCTION_MODEL
from integrations.higgsfield.provider import BaseHiggsfieldProvider
from integrations.higgsfield.types import CostEstimate, Job, JobStatus, ModelParam, ModelSchema, VideoResult


class _ConditionsDegradeBetweenCallsProvider(BaseHiggsfieldProvider):
    """
    Simule des conditions qui SE DÉGRADENT entre deux appels : le solde
    est suffisant lors du premier evaluate() (étape 1 du scénario), puis
    tombe à zéro pour tout appel suivant (étape 2 : les conditions
    changent avant l'exécution réelle).
    """

    def __init__(self, cost: float = 10.0):
        self._cost = cost
        self._balance_calls = 0
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
        return CostEstimate(job_type=job_type, credits=self._cost)

    def get_account_balance(self) -> Optional[float]:
        self._balance_calls += 1
        if self._balance_calls == 1:
            return 1000.0  # Étape 1 : suffisant.
        return 0.0  # Étape 2+ : les conditions se sont dégradées.

    def create_job(self, job_type: str, prompt: str, **params: Any) -> Job:
        self.create_job_call_count += 1
        raise AssertionError(
            "create_job ne doit JAMAIS être appelé : la réévaluation "
            "au moment de l'exécution doit bloquer avant d'y arriver."
        )

    def get_job(self, job_id: str) -> Job:
        raise AssertionError("get_job ne doit jamais être appelé dans ces tests.")

    def wait_for_job(self, job_id, timeout_seconds=600, interval_seconds=3) -> VideoResult:
        raise AssertionError("wait_for_job ne doit jamais être appelé dans ces tests.")


def _request(approved: bool) -> GenerationRequest:
    """
    Phase P2.11 : inclut une autorisation humaine valide liée à
    "005" par défaut — ces tests portent sur la réévaluation fraîche
    du Gate au moment de l'exécution (TOCTOU budget), pas sur le
    verrou d'autorisation humaine lui-même. `dataclasses.replace(...,
    request_id="006")`, utilisé plus bas pour simuler une DEUXIÈME
    requête indépendante, laisse alors volontairement cette
    autorisation "orpheline" (liée à "005", pas "006") — sans
    incidence ici puisque le budget dégradé bloque déjà AVANT que le
    Gate n'examine l'autorisation.
    """

    return GenerationRequest(
        request_id="005",
        job_type=PRODUCTION_MODEL,
        prompt="Un prompt de test.",
        duration=5,
        resolution="720p",
        aspect_ratio="9:16",
        approved=approved,
        real_generation_authorization=RealGenerationAuthorization(
            request_id="005",
            authorized_by_human=True,
        ),
    )


class TestGenerationJobServiceReevaluatesAtExecutionTime(unittest.TestCase):

    def test_initial_decision_is_approved_but_conditions_then_degrade(self):
        # Étape 1 : un premier evaluate() isolé obtient APPROVED (budget
        # encore suffisant à cet instant).
        provider = _ConditionsDegradeBetweenCallsProvider()
        gate = GenerationApprovalGate(provider)

        first_decision = gate.evaluate(_request(approved=True))
        self.assertEqual(first_decision.decision, GenerationApprovalDecision.APPROVED)

    def test_execute_reevaluates_fresh_and_blocks_when_conditions_degraded(self):
        # Étape 2 : les conditions changent (solde chute) avant toute
        # tentative d'exécution. GenerationJobService.execute() ne doit
        # PAS se fier à la première décision APPROVED : il réévalue.
        provider = _ConditionsDegradeBetweenCallsProvider()
        gate = GenerationApprovalGate(provider)
        job_service = GenerationJobService(provider, gate)

        # Simule le premier evaluate() "obtenu plus tôt" (étape 1).
        stale_decision = gate.evaluate(_request(approved=True))
        self.assertEqual(stale_decision.decision, GenerationApprovalDecision.APPROVED)

        # Étape 3/4 : execute() réévalue lui-même le Gate — la décision
        # fraîche doit être BLOCKED (solde tombé à 0 entre-temps), et
        # AUCUN job ne doit être créé, quelle que soit la décision
        # "ancienne" obtenue à l'étape 1.
        with self.assertRaises(GenerationJobExecutionError) as ctx:
            job_service.execute(_request(approved=True))

        self.assertEqual(
            ctx.exception.approval.decision, GenerationApprovalDecision.BLOCKED
        )
        self.assertEqual(provider.create_job_call_count, 0)

    def test_the_stale_approved_result_is_never_reused_by_execute(self):
        # Démontre explicitement que GenerationJobService ne prend PAS
        # en paramètre une décision précalculée : il appelle
        # gate.evaluate(request) lui-même, à chaque execute().
        provider = _ConditionsDegradeBetweenCallsProvider()
        gate = GenerationApprovalGate(provider)
        job_service = GenerationJobService(provider, gate)

        import inspect

        signature = inspect.signature(GenerationJobService.execute)
        self.assertNotIn(
            "approval",
            signature.parameters,
            "execute() ne doit jamais accepter une décision d'approbation "
            "précalculée en paramètre — il doit toujours la recalculer.",
        )

        # Consomme le 1er appel evaluate() (solde encore suffisant),
        # simulant une décision "obtenue plus tôt" ailleurs dans le code
        # — execute() ne doit PAS pouvoir la réutiliser.
        gate.evaluate(_request(approved=True))

        with self.assertRaises(GenerationJobExecutionError):
            job_service.execute(_request(approved=True))

    def test_two_consecutive_execute_calls_each_trigger_their_own_evaluation(self):
        # Un provider dont le solde ne se dégrade qu'une fois : le 1er
        # execute() (evaluate() interne = son 1er appel réel) doit
        # réussir jusqu'à create_job (bloqué séparément par le garde-fou
        # réel testé ailleurs) ; le 2e doit être bloqué par le solde
        # dégradé, prouvant que chaque execute() déclenche BIEN sa
        # propre évaluation indépendante plutôt que de réutiliser un
        # résultat mis en cache.
        class _SucceedsOnceThenDegrades(_ConditionsDegradeBetweenCallsProvider):
            def create_job(self, job_type, prompt, **params):
                self.create_job_call_count += 1
                return Job(job_id="job-1", job_type=job_type, status=JobStatus.QUEUED)

            def get_job(self, job_id):
                return Job(job_id=job_id, job_type=PRODUCTION_MODEL, status=JobStatus.SUCCEEDED)

            def wait_for_job(self, job_id, timeout_seconds=600, interval_seconds=3):
                return VideoResult(job_id=job_id, status=JobStatus.SUCCEEDED, output_urls=("mock://x",))

        provider = _SucceedsOnceThenDegrades()
        gate = GenerationApprovalGate(provider)
        job_service = GenerationJobService(provider, gate)

        # 1er execute() : premier appel evaluate() -> solde suffisant -> APPROVED -> job créé.
        outcome = job_service.execute(_request(approved=True))
        self.assertEqual(provider.create_job_call_count, 1)

        # 2e execute() avec une NOUVELLE requête (sinon ALREADY_EXECUTED
        # masquerait le vrai signal recherché ici) : solde désormais
        # dégradé -> réévaluation fraîche -> BLOCKED -> pas de job créé.
        second_request = dataclasses.replace(_request(approved=True), request_id="006")

        with self.assertRaises(GenerationJobExecutionError) as ctx:
            job_service.execute(second_request)

        self.assertEqual(
            ctx.exception.approval.decision, GenerationApprovalDecision.BLOCKED
        )
        self.assertEqual(provider.create_job_call_count, 1)  # Toujours 1, pas 2.


if __name__ == "__main__":
    unittest.main()
