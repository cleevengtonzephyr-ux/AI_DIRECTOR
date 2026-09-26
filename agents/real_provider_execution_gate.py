"""
AI DIRECTOR — Real Provider Execution Gate (Phase P2.36, MASTER PROMPT V2)

Répond, de façon déterministe et PUREMENT EN LECTURE, à UNE question,
plus étroite et plus tardive que celle de `agents/activation_
readiness.py` (Phase P2.24) :

    « Si une exécution réelle était tentée MAINTENANT, avec CE
      `provider_activation_contract` (Phase P2.26) précis, la chaîne
      d'autorité complète -- readiness technique ET activation
      contrôlée du Provider -- est-elle actuellement cohérente ? »

STOP -- CE QUE CE MODULE N'EST PAS :
Une décision `APPROVED` de ce Gate NE SIGNIFIE JAMAIS « génère
maintenant ». Exactement comme `ActivationReadinessEvaluator` (Phase
P2.24) dont il se compose : ce module
- N'APPELLE JAMAIS `provider.create_job()` ni `client.create_job()`.
- NE CONSTRUIT JAMAIS de `RealGenerationAuthorization`,
  `RequestScopedActivationContract`, ni
  `ControlledRealProviderActivationContract`.
- NE CONSOMME JAMAIS un contrat (utilise exclusivement les variantes
  NON MUTANTES `inspect_activation()` (P2.21) et `inspect()` (P2.26,
  Phase P2.36) -- jamais `validate_activation()`/`validate()`).
- N'importe ni HiggsfieldClient, ni subprocess.

POURQUOI UN MODULE SÉPARÉ, PLUTÔT QU'UNE MODIFICATION DE
`ActivationReadinessEvaluator` (Étape 1/2, rapport P2.36) :
`ActivationReadinessEvaluator` est déjà validé par des dizaines de
tests (P2.24, P2.28, P2.30) qui ne fournissent JAMAIS de
`provider_activation_contract` -- lui ajouter une onzième dimension
obligatoire y aurait introduit un risque de régression réel pour un
composant déjà figé. Ce module RÉUTILISE `ActivationReadinessEvaluator`
tel quel, par COMPOSITION (jamais dupliqué), et n'ajoute qu'UNE seule
dimension supplémentaire, spécifique à la frontière Provider (P2.26) :
`provider_activation_ready`. Zéro ligne de
`agents/activation_readiness.py` n'est modifiée par cette phase.

ONZE DIMENSIONS AU TOTAL (les dix de `ActivationReadinessReport`, plus
une) -- toutes indépendantes, jamais fusionnées :

    technical_ready, request_identity_ready, prompt_ready, asset_ready,
    budget_ready, authorization_ready, activation_ready, replay_safe,
    crash_safe, provider_ready         (héritées de P2.24, inchangées)
    provider_activation_ready          (NOUVELLE, Phase P2.36)

RÈGLE ABSOLUE : `decision == APPROVED` n'est vrai QUE si LES ONZE
dimensions le sont simultanément -- et même alors, ne représente
jamais une autorisation, une activation, ni une exécution. La
transition finale vers `HiggsfieldProvider.create_job()` reste fermée
(Phase P2.35) indépendamment de ce que ce Gate renvoie.
"""

import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import (
    RequestScopedActivationContract,
    RequestScopedActivationService,
)
from agents.activation_readiness import ActivationReadinessEvaluator, ActivationReadinessReport
from agents.controlled_real_provider_activation import (
    ControlledRealProviderActivationContract,
    ControlledRealProviderActivationService,
)
from agents.generation_approval_gate import GenerationApprovalGate, GenerationRequest
from agents.generation_job_service import GenerationJobService
from agents.release_candidate_identity_lock import ReleaseCandidateIdentityLock


class RealProviderExecutionDecision(str, Enum):
    """Décision du Gate -- délibérément distincte du vocabulaire
    READY/NOT_READY de P2.24 (une notion différente, plus tardive et
    plus étroite : readiness technique + activation Provider, jamais
    une autorisation)."""

    APPROVED = "APPROVED"
    NOT_APPROVED = "NOT_APPROVED"


@dataclass(frozen=True)
class RealProviderExecutionGateReport:
    """
    Photographie du Gate pour UNE requête, à UN instant précis. Rien
    n'est mis en cache au-delà de cet objet : un nouvel appel à
    `RealProviderExecutionGate.evaluate()` relit tout depuis zéro,
    y compris `readiness` (P2.24, elle-même déjà non-caching).
    """

    request_id: str
    readiness: ActivationReadinessReport

    provider_activation_ready: bool = False
    provider_activation_reasons: List[str] = field(default_factory=list)

    @property
    def decision(self) -> RealProviderExecutionDecision:
        """`APPROVED` UNIQUEMENT si les ONZE dimensions (dix de
        `readiness` + `provider_activation_ready`) sont vraies
        simultanément -- jamais une autorisation, cf. docstring de
        module."""

        if (
            self.readiness.decision == "READY"
            and self.provider_activation_ready
        ):
            return RealProviderExecutionDecision.APPROVED

        return RealProviderExecutionDecision.NOT_APPROVED

    @property
    def all_reasons(self) -> List[str]:
        """Concatène toutes les raisons de refus, readiness d'abord,
        puis la dimension Provider-activation propre à ce Gate."""

        return list(self.readiness.all_reasons) + list(self.provider_activation_reasons)


class RealProviderExecutionGate:
    """
    AI DIRECTOR — Real Provider Execution Gate (Phase P2.36)

    Compose EXCLUSIVEMENT des mécanismes déjà existants et validés
    (`ActivationReadinessEvaluator`, Phase P2.24 ;
    `ControlledRealProviderActivationService.inspect()`, Phase P2.36 --
    variante non mutante ajoutée à `agents/controlled_real_provider_
    activation.py` en même temps que ce module, mirroir exact de
    `RequestScopedActivationService.inspect_activation()`, Phase
    P2.24) -- aucune logique de décision métier n'est dupliquée ici,
    seulement de la lecture et de l'agrégation.
    """

    def __init__(
        self,
        gate: GenerationApprovalGate,
        identity_lock: ReleaseCandidateIdentityLock,
        activation_service: RequestScopedActivationService,
        provider_activation_service: ControlledRealProviderActivationService,
        job_service: Optional[GenerationJobService] = None,
    ):
        if provider_activation_service is None:
            raise ValueError(
                "RealProviderExecutionGate requires an explicit "
                "ControlledRealProviderActivationService -- mandatory, "
                "never optional here, exactly as identity_lock is "
                "mandatory for RequestScopedActivationService (Phase "
                "P2.21) and ControlledRealProviderActivationService "
                "(Phase P2.26). Refusing to construct a gate that could "
                "ever skip the provider-activation dimension."
            )

        self.readiness_evaluator = ActivationReadinessEvaluator(
            gate, identity_lock, activation_service, job_service=job_service
        )
        self.provider_activation_service = provider_activation_service

    def evaluate(
        self,
        request: GenerationRequest,
        activation_contract: Optional[RequestScopedActivationContract] = None,
        provider_activation_contract: Optional[ControlledRealProviderActivationContract] = None,
    ) -> RealProviderExecutionGateReport:
        """
        Évalue les onze dimensions pour `request` à cet instant précis.
        N'appelle jamais `create_job()`, ne construit jamais de
        `RealGenerationAuthorization` ni ne consomme un contrat
        quelconque -- une inspection pure, deux fois non mutante
        (P2.21 `inspect_activation()` + P2.26 `inspect()`).
        """

        readiness = self.readiness_evaluator.evaluate(
            request, activation_contract=activation_contract
        )

        provider_activation_ready, provider_activation_reasons = (
            self._check_provider_activation(
                request, activation_contract, provider_activation_contract
            )
        )

        return RealProviderExecutionGateReport(
            request_id=request.request_id,
            readiness=readiness,
            provider_activation_ready=provider_activation_ready,
            provider_activation_reasons=provider_activation_reasons,
        )

    # ------------------------------------------------------------------
    # 11. PROVIDER_ACTIVATION_READINESS -- INSPECTION SEULE (jamais
    # prepare()/validate()).
    # ------------------------------------------------------------------

    def _check_provider_activation(
        self,
        request: GenerationRequest,
        activation_contract: Optional[RequestScopedActivationContract],
        provider_activation_contract: Optional[ControlledRealProviderActivationContract],
    ):
        if activation_contract is None or provider_activation_contract is None:
            return False, [
                "No provider_activation_contract (and/or its underlying "
                "P2.21 activation_contract) was supplied -- this gate "
                "never calls prepare()/prepare_activation() "
                "automatically, and a provider activation contract can "
                "never be inspected without the request-scoped contract "
                "it is bound to."
            ]

        reasons = self.provider_activation_service.inspect(
            request, activation_contract, provider_activation_contract
        )
        return (len(reasons) == 0, reasons)
