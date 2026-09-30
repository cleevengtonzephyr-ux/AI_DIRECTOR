"""
AI DIRECTOR — Activation Readiness Protocol (Phase P2.24, MASTER PROMPT V2)

Répond, de façon déterministe et PUREMENT EN LECTURE, à UNE question :

    « Le système est-il techniquement prêt à effectuer une génération
      réelle SI ET SEULEMENT SI une autorisation humaine explicite et
      une activation contrôlée sont fournies ? »

STOP -- CE QUE CE MODULE N'EST PAS :
Une réponse `READY` de ce module NE SIGNIFIE JAMAIS « génère
maintenant ». Elle signifie uniquement que les conditions structurelles
et métier observées à cet instant sont satisfaites -- ce module :
- N'APPELLE JAMAIS `provider.create_job()`.
- NE CONSTRUIT JAMAIS de `RealGenerationAuthorization` (Phase P2.11) :
  il se contente d'INSPECTER `request.real_generation_authorization`
  tel qu'il a été fourni par un appelant externe.
- N'APPELLE JAMAIS `prepare_activation()` (Phase P2.21) : il n'accepte
  qu'un `activation_contract` DÉJÀ obtenu par un appelant externe, et
  ne fait qu'une INSPECTION NON MUTANTE de sa validité actuelle via
  `RequestScopedActivationService.inspect_activation()` (Phase P2.24)
  -- jamais `validate_activation()`, qui consommerait le contrat pour
  rien.
- N'importe ni HiggsfieldClient, ni subprocess.

DIX DIMENSIONS INDÉPENDANTES (Étape 4-12 du rapport P2.24) -- chacune
un booléen + ses raisons, JAMAIS fusionnées entre elles :

    technical_ready         -- le pipeline logiciel est-il câblé ?
    request_identity_ready  -- request_id/model/duration/resolution/
                               aspect_ratio == Release Candidate ?
    prompt_ready            -- Master Prompt exact (longueur, lignes,
                               SHA-256) ?
    asset_ready             -- avatar/face reference exacts (SHA-256
                               recalculés depuis les fichiers réels) ?
    budget_ready            -- coût connu <= solde disponible, tous
                               deux relus EN DIRECT à cet instant ?
    authorization_ready     -- une RealGenerationAuthorization valide
                               est-elle DÉJÀ présente sur la requête ?
                               (jamais créée ici)
    activation_ready        -- un activation_contract DÉJÀ fourni
                               validerait-il actuellement ? (jamais
                               créé ni consommé ici)
    replay_safe             -- ni ALREADY_EXECUTED ni
                               EXECUTION_STATE_UNKNOWN pour ce
                               request_id ?
    crash_safe              -- le mécanisme de gestion UNKNOWN (Phase
                               P2.20) est-il structurellement présent ?
    provider_ready          -- le Provider EST-IL, par construction,
                               susceptible d'appeler réellement
                               Higgsfield (jamais vérifié en
                               l'appelant) ?

RÈGLE ABSOLUE (Étape 13) -- READINESS != AUTHORIZATION != ACTIVATION
!= EXECUTION != QUALITÉ : la décision globale (`decision` ==
`"READY"`) n'est vraie QUE si les DIX dimensions le sont
simultanément -- mais même alors, elle ne représente jamais une
autorisation, une activation, ni une exécution. `provider_ready` est
délibérément TOUJOURS `False` face au vrai `HiggsfieldProvider` (son
`create_job()` reste inconditionnellement désactivé par construction,
Phase C/D, jamais modifié) : la décision globale contre le chemin de
production réel ne peut donc jamais afficher `READY` tant que cette
phase n'a pas été explicitement révisée par un futur contrat dédié.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import (
    RequestScopedActivationContract,
    RequestScopedActivationService,
)
from agents.critical_section_lock import NoOpCriticalSectionLock
from agents.executed_request_store import (
    ExecutedRequestStoreCorruptedError,
    FileAuthorizationConsumptionRegistry,
    FileExecutedRequestStore,
    InvalidAuthorizationIdError,
)
from agents.generation_approval_gate import (
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
    is_exact_disabled_real_provider,
    is_recognized_test_mock_provider,
)
from agents.generation_cost_service import CostEstimationStatus
from agents.generation_job_service import GenerationJobService
from agents.release_candidate_identity_lock import ReleaseCandidateIdentityLock
from integrations.higgsfield.provider import HiggsfieldProvider


@dataclass(frozen=True)
class ActivationReadinessReport:
    """
    Photographie de readiness pour UNE requête, à UN instant précis.
    Rien n'est mis en cache au-delà de cet objet : un nouvel appel à
    `ActivationReadinessEvaluator.evaluate()` relit tout depuis zéro.
    """

    request_id: str

    technical_ready: bool
    technical_reasons: List[str] = field(default_factory=list)

    request_identity_ready: bool = False
    request_identity_reasons: List[str] = field(default_factory=list)

    prompt_ready: bool = False
    prompt_reasons: List[str] = field(default_factory=list)

    asset_ready: bool = False
    asset_reasons: List[str] = field(default_factory=list)

    budget_ready: bool = False
    budget_reasons: List[str] = field(default_factory=list)

    authorization_ready: bool = False
    authorization_reasons: List[str] = field(default_factory=list)

    activation_ready: bool = False
    activation_reasons: List[str] = field(default_factory=list)

    replay_safe: bool = False
    replay_reasons: List[str] = field(default_factory=list)

    crash_safe: bool = False
    crash_reasons: List[str] = field(default_factory=list)

    provider_ready: bool = False
    provider_reasons: List[str] = field(default_factory=list)

    @property
    def decision(self) -> str:
        """
        `"READY"` UNIQUEMENT si les DIX dimensions sont vraies
        simultanément -- jamais une autorisation, cf. docstring de
        module. `"NOT_READY"` sinon.
        """

        dimensions = (
            self.technical_ready,
            self.request_identity_ready,
            self.prompt_ready,
            self.asset_ready,
            self.budget_ready,
            self.authorization_ready,
            self.activation_ready,
            self.replay_safe,
            self.crash_safe,
            self.provider_ready,
        )
        return "READY" if all(dimensions) else "NOT_READY"

    @property
    def all_reasons(self) -> List[str]:
        """Concatène toutes les raisons de refus, dans l'ordre des dimensions, pour un affichage humain en une lecture."""

        return (
            list(self.technical_reasons)
            + list(self.request_identity_reasons)
            + list(self.prompt_reasons)
            + list(self.asset_reasons)
            + list(self.budget_reasons)
            + list(self.authorization_reasons)
            + list(self.activation_reasons)
            + list(self.replay_reasons)
            + list(self.crash_reasons)
            + list(self.provider_reasons)
        )


class ActivationReadinessEvaluator:
    """
    AI DIRECTOR — Activation Readiness Evaluator (Phase P2.24)

    Compose EXCLUSIVEMENT des mécanismes déjà existants et validés
    (GenerationApprovalGate, ReleaseCandidateIdentityLock,
    RequestScopedActivationService) -- aucune logique de décision
    métier n'est dupliquée ici, seulement de la lecture et de
    l'agrégation.
    """

    def __init__(
        self,
        gate: GenerationApprovalGate,
        identity_lock: ReleaseCandidateIdentityLock,
        activation_service: RequestScopedActivationService,
        job_service: Optional[GenerationJobService] = None,
    ):
        if identity_lock is None:
            raise ValueError(
                "ActivationReadinessEvaluator requires an explicit "
                "ReleaseCandidateIdentityLock -- Identity Lock is "
                "mandatory for readiness evaluation, exactly as for "
                "RequestScopedActivationService (Phase P2.21)."
            )

        self.gate = gate
        self.identity_lock = identity_lock
        self.activation_service = activation_service
        self.job_service = job_service

    def evaluate(
        self,
        request: GenerationRequest,
        activation_contract: Optional[RequestScopedActivationContract] = None,
    ) -> ActivationReadinessReport:
        """
        Évalue les dix dimensions de readiness pour `request` à cet
        instant précis. N'appelle jamais `create_job()`, ne construit
        jamais de `RealGenerationAuthorization` ni ne consomme un
        `activation_contract` -- une inspection pure.
        """

        technical_ready, technical_reasons = self._check_technical()

        (
            identity_ready,
            prompt_ready,
            asset_ready,
            identity_reasons,
            prompt_reasons,
            asset_reasons,
        ) = self._check_identity(request)

        budget_ready, budget_reasons = self._check_budget(request)
        authorization_ready, authorization_reasons = self._check_authorization(request)
        activation_ready, activation_reasons = self._check_activation(
            request, activation_contract
        )
        replay_safe, replay_reasons = self._check_replay(request)
        crash_safe, crash_reasons = self._check_crash_safety()
        provider_ready, provider_reasons = self._check_provider()

        return ActivationReadinessReport(
            request_id=request.request_id,
            technical_ready=technical_ready,
            technical_reasons=technical_reasons,
            request_identity_ready=identity_ready,
            request_identity_reasons=identity_reasons,
            prompt_ready=prompt_ready,
            prompt_reasons=prompt_reasons,
            asset_ready=asset_ready,
            asset_reasons=asset_reasons,
            budget_ready=budget_ready,
            budget_reasons=budget_reasons,
            authorization_ready=authorization_ready,
            authorization_reasons=authorization_reasons,
            activation_ready=activation_ready,
            activation_reasons=activation_reasons,
            replay_safe=replay_safe,
            replay_reasons=replay_reasons,
            crash_safe=crash_safe,
            crash_reasons=crash_reasons,
            provider_ready=provider_ready,
            provider_reasons=provider_reasons,
        )

    # ------------------------------------------------------------------
    # A. TECHNICAL_READINESS
    # ------------------------------------------------------------------

    def _check_technical(self):
        reasons: List[str] = []

        if not isinstance(self.gate, GenerationApprovalGate):
            reasons.append("gate is not a GenerationApprovalGate instance.")

        if not isinstance(self.identity_lock, ReleaseCandidateIdentityLock):
            reasons.append(
                "identity_lock is not a ReleaseCandidateIdentityLock instance."
            )

        if not isinstance(self.activation_service, RequestScopedActivationService):
            reasons.append(
                "activation_service is not a RequestScopedActivationService "
                "instance."
            )

        if self.job_service is not None:
            if not isinstance(self.job_service, GenerationJobService):
                reasons.append("job_service is not a GenerationJobService instance.")
            else:
                if isinstance(self.job_service.lock, NoOpCriticalSectionLock):
                    reasons.append(
                        "job_service.lock is a NoOpCriticalSectionLock -- no "
                        "real mutual exclusion is configured (technical "
                        "readiness requires a real FileCriticalSectionLock)."
                    )
                if self.job_service.activation_service is None:
                    reasons.append(
                        "job_service.activation_service is not configured."
                    )

        return (len(reasons) == 0, reasons)

    # ------------------------------------------------------------------
    # B/C/5. REQUEST_IDENTITY_READINESS / PROMPT_READINESS / ASSET_READINESS
    # ------------------------------------------------------------------

    def _check_identity(self, request: GenerationRequest):
        violations = self.identity_lock.violations(request)

        identity_reasons: List[str] = []
        prompt_reasons: List[str] = []
        asset_reasons: List[str] = []

        for violation in violations:
            lowered = violation.lower()
            if "prompt" in lowered:
                prompt_reasons.append(violation)
            elif "master_avatar" in lowered or "face_reference" in lowered:
                asset_reasons.append(violation)
            else:
                identity_reasons.append(violation)

        return (
            len(identity_reasons) == 0,
            len(prompt_reasons) == 0,
            len(asset_reasons) == 0,
            identity_reasons,
            prompt_reasons,
            asset_reasons,
        )

    # ------------------------------------------------------------------
    # 6. BUDGET_READINESS -- coût/solde relus EN DIRECT, jamais mis en cache.
    # ------------------------------------------------------------------

    def _check_budget(self, request: GenerationRequest):
        cost_result = self.gate.cost_service.estimate(
            job_type=request.job_type,
            prompt=request.prompt,
            duration=request.duration,
            resolution=request.resolution,
            aspect_ratio=request.aspect_ratio,
        )

        if cost_result.status == CostEstimationStatus.ERROR:
            return False, [f"Cost estimation error: {cost_result.error}"]

        if cost_result.status == CostEstimationStatus.UNKNOWN:
            return False, [
                "Cost is unknown -- budget readiness cannot be confirmed "
                "(never treated as ready by default)."
            ]

        try:
            available = self.gate.provider.get_account_balance()
        except Exception as error:  # noqa: BLE001 -- surfaced as a reason, never masked
            return False, [f"Unable to verify account balance: {error}"]

        if available is None:
            return False, ["Account balance could not be determined."]

        required = cost_result.estimate.credits if cost_result.estimate else None

        if required is None:
            return False, ["Cost estimate has no usable credits value."]

        if required > available:
            return False, [
                f"Insufficient credits: {available} available < "
                f"{required} required."
            ]

        return True, []

    # ------------------------------------------------------------------
    # 7. AUTHORIZATION_READINESS -- INSPECTION SEULE, jamais de création.
    # ------------------------------------------------------------------

    def _check_authorization(self, request: GenerationRequest):
        auth = request.real_generation_authorization

        if auth is None:
            return False, [
                "No RealGenerationAuthorization present on this request -- "
                "readiness never creates one automatically."
            ]

        if not isinstance(auth, RealGenerationAuthorization):
            return False, [
                "real_generation_authorization is not a valid "
                "RealGenerationAuthorization instance."
            ]

        if auth.authorized_by_human is not True:
            return False, [
                "real_generation_authorization.authorized_by_human is not "
                "explicitly True."
            ]

        if auth.request_id != request.request_id:
            return False, [
                f"real_generation_authorization is bound to request "
                f"'{auth.request_id}', not to this request "
                f"'{request.request_id}'."
            ]

        return True, []

    # ------------------------------------------------------------------
    # 8. ACTIVATION_READINESS -- INSPECTION SEULE (jamais prepare_activation()).
    # ------------------------------------------------------------------

    def _check_activation(
        self,
        request: GenerationRequest,
        activation_contract: Optional[RequestScopedActivationContract],
    ):
        if activation_contract is None:
            return False, [
                "No activation_contract supplied -- activation readiness "
                "was never evaluated. Readiness never calls "
                "prepare_activation() automatically."
            ]

        reasons = self.activation_service.inspect_activation(
            request, activation_contract
        )
        return (len(reasons) == 0, reasons)

    # ------------------------------------------------------------------
    # 9. REPLAY_READINESS
    # ------------------------------------------------------------------

    def _check_replay(self, request: GenerationRequest):
        if self.gate.is_unknown(request.request_id):
            return False, [
                f"Request '{request.request_id}' is in "
                f"EXECUTION_STATE_UNKNOWN -- blocked, never auto-cleared "
                f"by a new authorization or activation."
            ]

        if self.gate.is_already_executed(request.request_id):
            return False, [
                f"Request '{request.request_id}' has already been "
                f"executed -- replay is blocked."
            ]

        reasons: List[str] = []

        # Phase B : lecture seule -- la readiness ne consomme jamais.
        auth = request.real_generation_authorization
        if isinstance(auth, RealGenerationAuthorization):
            try:
                consumed = self.gate.is_authorization_consumed(auth.authorization_id)
            except (ExecutedRequestStoreCorruptedError, InvalidAuthorizationIdError) as error:
                reasons.append(
                    f"authorization single-use state could not be verified: {error}"
                )
            else:
                if consumed:
                    reasons.append(
                        f"real_generation_authorization '{auth.authorization_id}' "
                        f"has already been consumed -- a new explicit human "
                        f"authorization is required."
                    )

        store = self.gate.executed_request_store
        if not isinstance(store, FileExecutedRequestStore) or not isinstance(
            getattr(store, "authorization_registry", None), FileAuthorizationConsumptionRegistry
        ):
            reasons.append(
                "executed_request_store / authorization consumption registry "
                "is not persistent -- authorization single-use and replay "
                "protection would not survive a process restart; the durable "
                "guarantee is unavailable."
            )

        return (len(reasons) == 0, reasons)

    # ------------------------------------------------------------------
    # 10. CRASH_SAFETY -- vérifie que le mécanisme (Phase P2.20) est
    # bien câblé, sans jamais simuler un crash réel.
    # ------------------------------------------------------------------

    def _check_crash_safety(self):
        reasons: List[str] = []

        if not callable(getattr(self.gate, "mark_unknown", None)):
            reasons.append(
                "gate does not expose a callable mark_unknown() -- "
                "crash/UNKNOWN handling is not wired."
            )

        if not callable(getattr(self.gate, "is_unknown", None)):
            reasons.append(
                "gate does not expose a callable is_unknown() -- "
                "crash/UNKNOWN handling is not wired."
            )

        return (len(reasons) == 0, reasons)

    # ------------------------------------------------------------------
    # 12. PROVIDER_READINESS -- JAMAIS déterminé en appelant create_job().
    # ------------------------------------------------------------------

    def _check_provider(self):
        provider = self.gate.provider

        # Phase D : sous-classe du vrai Provider, wrapper ou Provider
        # inconnu -- jamais « prêt », comme à la frontière d'exécution.
        # Vérifié EN PREMIER : ne lève jamais, quel que soit l'objet.
        if not (
            is_recognized_test_mock_provider(provider)
            or is_exact_disabled_real_provider(provider)
        ):
            return False, [
                f"provider {type(provider).__name__} is neither the real "
                f"HiggsfieldProvider nor a recognized test mock -- a "
                f"subclass, wrapper or unknown provider is never ready."
            ]

        is_the_disabled_real_provider = (
            type(provider).create_job is HiggsfieldProvider.create_job
        )

        if is_the_disabled_real_provider:
            return False, [
                "provider is the real HiggsfieldProvider, whose "
                "create_job() unconditionally raises "
                "HiggsfieldRealGenerationDisabledError by design -- not "
                "ready for real generation in this phase (never probed "
                "by actually calling create_job())."
            ]

        return True, []
