"""
AI DIRECTOR — MockHiggsfieldProvider (Phase B/C/E, MASTER PROMPT V2)

Implémentation 100% simulée du contrat BaseHiggsfieldProvider, destinée
exclusivement aux tests et au développement hors-ligne.

Aucun appel réseau, aucun appel au CLI Higgsfield, AUCUN crédit
consommé : toutes les données (modèles, coûts, jobs) sont générées et
suivies en mémoire (self._jobs), chaque job étant isolé par son
job_id — deux jobs créés sur la même instance ne partagent jamais
d'état.

Les valeurs par défaut (modèle seedance_2_0, coût de 22.5 crédits)
reflètent les données réelles observées lors de l'audit read-only du
CLI (workflow list / model list / model get / generate cost), afin que
les tests restent représentatifs sans jamais toucher au réseau.

Vocabulaire des statuts (Phase E) :
Le MASTER PROMPT V2 décrit le cycle global
NEEDS_APPROVAL -> APPROVED -> RUNNING -> WAITING -> COMPLETED. Les états
NEEDS_APPROVAL/APPROVED sont des décisions MÉTIER prises en amont de la
création du job (futur Approval Gate, Priorité 2 de la roadmap) : un
job Higgsfield n'existe pas encore à ce stade, donc ce Provider — qui
représente uniquement le CYCLE DE VIE D'UN JOB DÉJÀ CRÉÉ — ne les
modélise pas. Introduire ces états dans JobStatus (types.py, partagé
avec le HiggsfieldProvider réel) reviendrait à inventer une forme de
réponse CLI non vérifiée, ce qui est explicitement interdit. Le cycle
RUNNING -> WAITING -> COMPLETED du MASTER PROMPT V2 est donc simulé ici
avec le vocabulaire déjà défini et vérifié : QUEUED (= WAITING avant
démarrage) -> RUNNING -> SUCCEEDED (= COMPLETED) ou FAILED.
"""

import itertools
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from integrations.higgsfield.errors import HiggsfieldInvalidResponseError

if TYPE_CHECKING:
    # Phase P2.32 — type-checking-only import, mirrors provider.py:
    # avoids a real (runtime) circular import with agents.controlled_
    # real_provider_activation, which itself imports from
    # integrations.higgsfield.provider.
    from agents.controlled_real_provider_activation import (
        ControlledRealProviderActivationContract,
    )
from integrations.higgsfield.provider import BaseHiggsfieldProvider
from integrations.higgsfield.types import (
    CostEstimate,
    Job,
    JobStatus,
    ModelParam,
    ModelSchema,
    VideoResult,
)


DEFAULT_MOCK_MODELS: List[ModelSchema] = [
    ModelSchema(
        job_type="seedance_2_0",
        display_name="Seedance 2.0",
        params=(
            ModelParam(name="prompt", type="string", required=True),
            ModelParam(
                name="aspect_ratio",
                type="string",
                required=False,
                default="16:9",
                enum=("auto", "16:9", "9:16", "4:3", "3:4", "1:1", "21:9"),
            ),
            ModelParam(
                name="resolution",
                type="string",
                required=False,
                default="720p",
                enum=("480p", "720p", "1080p", "4k"),
            ),
            ModelParam(
                name="duration",
                type="integer",
                required=False,
                default=5,
            ),
            # start_image/image_references (Phase P2.7) : ajoutés pour
            # refléter le VRAI schéma seedance_2_0 (confirmé en lecture
            # seule, `model get seedance_2_0`), qui les déclare tous les
            # deux — cf. REAL_SEEDANCE_SCHEMA dans
            # tests/test_phase_p1_readiness.py, qui reproduisait déjà
            # cette réalité localement. Sans cette déclaration,
            # GenerationApprovalGate rejette (INVALID_REQUEST) toute
            # requête portant des références média dès que
            # AIDirector.run_video_mission() les attache réellement
            # (Phase P2.7), y compris avec ce Mock.
            ModelParam(
                name="start_image",
                type="object|null",
                required=False,
                default=None,
            ),
            ModelParam(
                name="image_references",
                type="array",
                required=False,
                default=None,
            ),
        ),
        raw={"display_name": "Seedance 2.0", "job_type": "seedance_2_0"},
    ),
]


class MockHiggsfieldProvider(BaseHiggsfieldProvider):
    """
    Double de test pour BaseHiggsfieldProvider.

    - create_job() simule réellement la création d'un job (id
      déterministe et prévisible : "mock-job-1", "mock-job-2", ...)
      mais n'effectue AUCUN appel réseau/CLI.
    - get_job() fait progresser l'état simulé à chaque appel
      (QUEUED -> RUNNING -> SUCCEEDED/FAILED après `succeed_after_polls`
      appels), pour permettre de tester le polling sans sleep réel.
      Chaque job garde son propre compteur d'appels et son propre
      résultat cible (`outcome`) : deux jobs créés sur la même
      instance progressent indépendamment.
    - wait_for_job() boucle sur get_job() en mémoire jusqu'à un état
      terminal ou l'expiration du timeout simulé. L'horloge (`clock`)
      et le sleep (`sleep`) sont injectables pour permettre des tests
      de timeout totalement déterministes, sans dépendre du temps réel
      écoulé.
    """

    def __init__(
        self,
        models: Optional[List[ModelSchema]] = None,
        cost_per_job: Optional[float] = 22.5,
        available_credits: Optional[float] = 100.0,
        succeed_after_polls: int = 2,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        cost_error: Optional[Exception] = None,
        balance_error: Optional[Exception] = None,
    ):
        self._models = list(models) if models is not None else list(DEFAULT_MOCK_MODELS)
        self._cost_per_job = cost_per_job
        self._available_credits = available_credits
        self._succeed_after_polls = succeed_after_polls
        self._job_ids = itertools.count(1)
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._clock = clock
        self._sleep = sleep
        self._cost_error = cost_error
        self._balance_error = balance_error

    def list_models(self, video: bool = True) -> List[ModelSchema]:
        return list(self._models)

    def get_model(self, job_type: str) -> ModelSchema:
        for model in self._models:
            if model.job_type == job_type:
                return model

        raise HiggsfieldInvalidResponseError(
            f"[mock] Unknown model job_type: {job_type}"
        )

    def estimate_cost(
        self,
        job_type: str,
        prompt: str,
        duration: Optional[int] = None,
        resolution: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
    ) -> CostEstimate:

        if self._cost_error is not None:
            raise self._cost_error

        return CostEstimate(
            job_type=job_type,
            credits=self._cost_per_job,
            raw={"credits": self._cost_per_job, "mock": True},
        )

    def get_account_balance(self) -> Optional[float]:
        """Simule le solde de compte, configurable via `available_credits`
        au constructeur, ou une erreur via `balance_error` (jamais de
        valeur inventée ni d'appel réseau)."""

        if self._balance_error is not None:
            raise self._balance_error

        return self._available_credits

    def create_job(
        self,
        job_type: str,
        prompt: str,
        provider_activation_contract: Optional["ControlledRealProviderActivationContract"] = None,
        request_id: Optional[str] = None,
        avatar_sha256: Optional[str] = None,
        face_reference_sha256: Optional[str] = None,
        **params: Any,
    ) -> Job:
        """
        Crée un faux job en mémoire. Signature strictement identique à
        HiggsfieldProvider.create_job() (même contrat, Phases P2.32 et
        P2.35 incluses) : les options propres au Mock sont passées via
        **params et retirées avant d'être stockées comme "params" du
        job.

        `provider_activation_contract`/`request_id`/`avatar_sha256`/
        `face_reference_sha256` (Phases P2.32/P2.35, optionnels) : ce
        Mock ne les utilise JAMAIS pour décider quoi que ce soit (il
        crée toujours le job simulé, avec ou sans eux, exactement
        comme avant P2.35 -- aucune validation structurelle n'est
        introduite ici, contrairement au vrai Provider) -- ils sont
        seulement conservés tels quels dans l'état du job simulé
        (`raw[...]`) à des fins PUREMENT OBSERVABLES, pour qu'un test
        puisse vérifier que ces paramètres ont bien été transmis par
        `GenerationJobService.execute()` jusqu'à cette frontière, sans
        jamais impliquer que le VRAI Provider les honorerait de la
        même façon.

        `outcome` ("succeeded" ou "failed", défaut "succeeded") et
        `succeed_after_polls` (nombre d'appels à get_job() avant
        l'état terminal, défaut = valeur de l'instance) sont
        configurables PAR JOB, afin de pouvoir tester plusieurs jobs
        aux comportements différents sur une même instance de Mock
        sans qu'ils ne se mélangent.
        """

        params = dict(params)
        outcome = params.pop("outcome", "succeeded")
        succeed_after_polls = params.pop("succeed_after_polls", None)

        if outcome not in ("succeeded", "failed"):
            raise ValueError(f"Invalid mock outcome: {outcome!r}")

        job_id = f"mock-job-{next(self._job_ids)}"

        self._jobs[job_id] = {
            "id": job_id,
            "job_type": job_type,
            "prompt": prompt,
            "params": params,
            "provider_activation_contract": provider_activation_contract,
            "request_id": request_id,
            "avatar_sha256": avatar_sha256,
            "face_reference_sha256": face_reference_sha256,
            "polls": 0,
            "status": JobStatus.QUEUED,
            "outcome": outcome,
            "succeed_after_polls": (
                succeed_after_polls
                if succeed_after_polls is not None
                else self._succeed_after_polls
            ),
        }

        return Job(
            job_id=job_id,
            job_type=job_type,
            status=JobStatus.QUEUED,
            raw=dict(self._jobs[job_id]),
        )

    def get_job(self, job_id: str) -> Job:
        state = self._jobs.get(job_id)

        if state is None:
            raise HiggsfieldInvalidResponseError(f"[mock] Unknown job_id: {job_id}")

        state["polls"] += 1

        if state["status"] == JobStatus.QUEUED:
            state["status"] = JobStatus.RUNNING
        elif (
            state["status"] == JobStatus.RUNNING
            and state["polls"] >= state["succeed_after_polls"]
        ):
            state["status"] = (
                JobStatus.SUCCEEDED
                if state["outcome"] == "succeeded"
                else JobStatus.FAILED
            )

        return Job(
            job_id=job_id,
            job_type=state["job_type"],
            status=state["status"],
            raw=dict(state),
        )

    def wait_for_job(
        self,
        job_id: str,
        timeout_seconds: float = 600,
        interval_seconds: float = 0,
    ) -> VideoResult:

        deadline = self._clock() + timeout_seconds

        while True:
            job = self.get_job(job_id)

            if job.status.is_terminal:
                output_urls = (
                    (f"mock://output/{job_id}.mp4",)
                    if job.status == JobStatus.SUCCEEDED
                    else tuple()
                )
                return VideoResult(
                    job_id=job_id,
                    status=job.status,
                    output_urls=output_urls,
                    raw=job.raw,
                )

            if self._clock() >= deadline:
                return VideoResult(
                    job_id=job_id,
                    status=job.status,
                    output_urls=tuple(),
                    raw=job.raw,
                )

            if interval_seconds:
                self._sleep(interval_seconds)
