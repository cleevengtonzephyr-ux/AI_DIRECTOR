"""
AI DIRECTOR — Final Report Service v0.1 (Phase J, MASTER PROMPT V2)

Dernier maillon du pipeline :

    ... -> COST ESTIMATION -> NEEDS_APPROVAL -> APPROVAL
        -> REAL HIGGSFIELD JOB -> WAIT/POLL -> RESULT
        -> QUALITY EVALUATOR -> FINAL REPORT

Ce service N'EXÉCUTE RIEN lui-même : il délègue intégralement à
GenerationJobService (Phase H, qui interroge lui-même
GenerationApprovalGate, Phase G) et à QualityEvaluator (Phase I), puis
AGRÈGE leurs résultats en un rapport typé unique destiné à
l'utilisateur final.

RÈGLE ABSOLUE (Phase J) — NE JAMAIS SIMULER UN SUCCÈS :
Si GenerationApprovalGate n'a pas rendu une décision APPROVED (coût
inconnu non approuvé, budget insuffisant, requête invalide, requête
déjà exécutée), AUCUN job n'est créé et le rapport a
`status=NOT_EXECUTED`, `job_created=False`, et tous les champs liés à
un job (job_id, job_status, output_urls, quality_decision) restent
None/vides — jamais une valeur inventée ou déduite. Il est impossible
de confondre un rapport NOT_EXECUTED avec un succès : ces deux familles
d'état ne partagent aucune valeur de `status` (voir FinalReportStatus).

SÉCURITÉ :
- Ce module n'appelle jamais provider.create_job() directement : cet
  appel reste exclusivement dans GenerationJobService (Phase H), dont
  la protection réelle (HiggsfieldRealGenerationDisabledError,
  Phase C/D) n'est ni modifiée ni interceptée/masquée ici — si elle
  est levée (ex. usage accidentel avec le vrai HiggsfieldProvider),
  elle se propage telle quelle hors de generate(). Décision DÉLIBÉRÉE,
  RECONFIRMÉE en Phase P2.23 (cf. `tests/test_final_report_service.py
  ::test_real_provider_protection_propagates_uncaught`, non modifié) :
  ne JAMAIS transformer cette levée en un rapport NOT_EXECUTED "propre"
  -- l'absence totale de rapport, plutôt qu'un champ qu'un lecteur
  pressé pourrait manquer, reste la garantie la PLUS forte qu'aucun
  rapport ne puisse jamais prétendre EXECUTED_PASS dans ce cas
  (rapport P2.23, Cas 3). Faire autrement affaiblirait un signal
  d'alarme volontairement bruyant en un simple champ silencieux.
- N'importe ni HiggsfieldClient, ni subprocess.

FINAL REPORT TRUTHFULNESS (Phase P2.23) :
`approval_decision` (déjà existant, réutilisé tel quel -- c'est la
TECHNICAL_GATE_DECISION du rapport P2.23, jamais renommé pour ne pas
casser les nombreux tests existants) ne dit JAMAIS, à lui seul, si une
génération a eu lieu : `APPROVED` signifie seulement que le Gate
technique a validé la requête à cet instant, pas qu'un job a été créé
ni qu'une activation a été accordée. Trois champs supplémentaires
rendent cette distinction EXPLICITE plutôt que déductible :

- `activation_decision` (`ActivationDecision`) : `NOT_EVALUATED` si
  aucun `activation_contract` n'a été fourni à `generate()`, OU si le
  Gate a refusé AVANT même d'atteindre la vérification du contrat
  (Cas 1 du rapport P2.23) ; `REJECTED` si un contrat a été fourni et
  que `RequestScopedActivationService.validate_activation()` l'a
  refusé (Cas 2) ; `APPROVED` si un contrat a été fourni et validé
  (seul cas où un job a pu être créé).
- `activation_reasons` : raisons complètes du rejet d'activation
  (vide sauf `REJECTED`).
- `real_provider_called` : CORRIGÉ (audit post-P2.27) -- signifie
  littéralement "le VRAI `HiggsfieldProvider` (jamais
  `MockHiggsfieldProvider`, ni aucun autre double de test) a été le
  provider effectivement utilisé pour cette exécution", jamais "un
  job a été créé". AVANT cette correction, ce champ valait `True`
  INCONDITIONNELLEMENT dans le bloc de succès -- y compris avec
  `MockHiggsfieldProvider`, ce qui était factuellement faux :
  `job_created=True` ne prouve JAMAIS, à lui seul, qu'il s'agit du
  vrai Provider. Déterminé par identité de méthode sur le provider
  RÉELLEMENT utilisé par `GenerationJobService`
  (`self.job_service.provider`), jamais déduit du résultat du job --
  cf. `_is_real_provider()`. Conséquence architecturale : puisque
  `HiggsfieldProvider.create_job()` reste inconditionnellement
  désactivé (Phase C/D, INCHANGÉ), ce champ vaut TOUJOURS `False`
  pour tout rapport que le code peut réellement produire aujourd'hui
  -- comportement honnête attendu, qui resterait correct sans
  modification si un Provider réel fonctionnel était un jour activé.
- `execution_state` (propriété calculée, jamais un champ stocké
  séparément -- aucune deuxième source de vérité qui pourrait dériver) :
  `"EXECUTION_STATE_UNKNOWN"` si `approval_decision` vaut
  `EXECUTION_STATE_UNKNOWN` (Phase P2.20 : un job précédent a peut-être
  existé, jamais confondu avec un NOT_EXECUTED ordinaire) ; sinon
  `"EXECUTED"` si `job_created` ; sinon `"NOT_EXECUTED"`.

Phase P2.27 — TROISIÈME axe, tout aussi indépendant : `provider_
activation_decision`/`provider_activation_reasons` (réutilisent le
MÊME `ActivationDecision`, jamais un enum dupliqué) représentent ce
que `ControlledRealProviderActivationService.validate()` (Phase
P2.26/P2.27) a décidé pour cette tentative précise -- `NOT_EVALUATED`
si aucun `provider_activation_contract` n'a été fourni OU si un rejet
antérieur (Gate ou activation P2.21) a empêché de l'atteindre ;
`REJECTED` si fourni et rejeté (systématiquement le cas contre le
Provider réel, cf. Cas 3 déjà documenté ci-dessus) ; `APPROVED`
uniquement dans le cas où un job a pu être créé. `approval_decision ==
APPROVED` et même `activation_decision == APPROVED` ne permettent
donc TOUJOURS PAS, à eux seuls, de conclure qu'une génération a eu
lieu : `job_created`/`real_provider_called` restent la seule preuve.

MISSION_ID -- OBSERVABILITY METADATA ONLY (Phase P3.34, additive):
`mission_id` (optional, default `None`) is a pure passthrough value,
never read, inspected, or branched on anywhere in this module. It is
NOT request_id, NOT an authorization proof, and NOT used to compute
`approval_decision`/`activation_decision`/`provider_activation_
decision`/`real_provider_called`/`execution_state` -- every one of
those is still computed exactly as before P3.34, from `request`/
`outcome`/`error` alone. `generate()` forwards whatever caller-
supplied `mission_id` it receives (or `None`) verbatim onto the
returned `FinalReport`, on both the success and the NOT_EXECUTED
paths, and nowhere else. Closes the P3.33 F1 gap (mission_id did not
survive past the Domain B/C bridge) without touching
`GenerationApprovalGate`, `GenerationJobService`,
`RequestScopedActivationService`, `ControlledRealProviderActivation
Service`, or any other P2-protected file: this module was never on
that protected list, and no P2 file's signature changes.
"""

import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
)
from agents.generation_cost_service import CostEstimationStatus
from agents.generation_job_service import (
    GenerationJobActivationRejectedError,
    GenerationJobExecutionError,
    GenerationJobProviderActivationRejectedError,
    GenerationJobService,
)
from agents.quality_evaluator import QualityDecision, QualityEvaluator
from integrations.higgsfield.provider import BaseHiggsfieldProvider, HiggsfieldProvider
from integrations.higgsfield.types import JobStatus


class FinalReportStatus(str, Enum):
    """
    NOT_EXECUTED est structurellement disjoint des statuts EXECUTED_* :
    aucune confusion possible entre "rien ne s'est passé" et un résultat
    d'exécution, quel qu'il soit (succès, échec, ou retry recommandé).
    """

    NOT_EXECUTED = "NOT_EXECUTED"
    EXECUTED_PASS = "EXECUTED_PASS"
    EXECUTED_FAIL = "EXECUTED_FAIL"
    EXECUTED_RETRY_RECOMMENDED = "EXECUTED_RETRY_RECOMMENDED"


class ActivationDecision(str, Enum):
    """
    Phase P2.23 — axe INDÉPENDANT de `approval_decision` (Gate
    technique) : représente ce que le mécanisme d'activation (Phase
    P2.21/P2.22) a décidé pour CETTE tentative précise, jamais déduit
    du Gate seul.
    """

    NOT_EVALUATED = "NOT_EVALUATED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class FinalReport:
    """
    Rapport de synthèse fidèle à l'état réel du pipeline pour une
    requête donnée. Aucun champ n'est jamais inventé : un champ lié à
    un job absent reste None/vide, il n'est jamais déduit ou supposé.

    Phase P2.23 : `approval_decision` (Gate technique) et
    `activation_decision` (contrat d'activation) sont deux axes
    STRICTEMENT INDÉPENDANTS -- `approval_decision == APPROVED` ne
    permet JAMAIS, à lui seul, de conclure qu'une génération a eu
    lieu ni qu'une activation a été accordée. `job_created` et
    `real_provider_called` restent la seule preuve qu'un job a
    réellement été créé.
    """

    request_id: str
    job_type: str
    status: FinalReportStatus
    job_created: bool
    approval_decision: GenerationApprovalDecision
    approval_reasons: List[str] = field(default_factory=list)

    activation_decision: ActivationDecision = ActivationDecision.NOT_EVALUATED
    activation_reasons: List[str] = field(default_factory=list)

    provider_activation_decision: ActivationDecision = ActivationDecision.NOT_EVALUATED
    provider_activation_reasons: List[str] = field(default_factory=list)

    real_provider_called: bool = False

    cost_status: Optional[CostEstimationStatus] = None
    estimated_credits: Optional[float] = None

    job_id: Optional[str] = None
    job_status: Optional[JobStatus] = None
    output_urls: Tuple[str, ...] = field(default_factory=tuple)

    quality_decision: Optional[QualityDecision] = None
    quality_reasons: List[str] = field(default_factory=list)

    summary: str = ""

    # Phase P3.34 -- OBSERVABILITY METADATA ONLY, never authority
    # evidence. See module docstring "MISSION_ID -- OBSERVABILITY
    # METADATA ONLY". Appended last (not near request_id) so that any
    # pre-P3.34 positional construction of FinalReport remains valid.
    mission_id: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.status == FinalReportStatus.EXECUTED_PASS

    @property
    def execution_state(self) -> str:
        """
        Phase P2.23 — lecture unique et fidèle de "qu'est-il RÉELLEMENT
        arrivé", calculée à partir des champs déjà authoritatifs
        ci-dessus (jamais stockée séparément, donc jamais susceptible
        de diverger d'eux) : `"EXECUTION_STATE_UNKNOWN"` (un job
        antérieur a peut-être existé, cf. Phase P2.20 -- jamais
        confondu avec un NOT_EXECUTED ordinaire), sinon `"EXECUTED"`
        si `job_created`, sinon `"NOT_EXECUTED"`.
        """

        if self.approval_decision == GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN:
            return "EXECUTION_STATE_UNKNOWN"
        if self.job_created:
            return "EXECUTED"
        return "NOT_EXECUTED"


class FinalReportService:
    """
    AI DIRECTOR — Final Report Service v0.1 (Phase J)

    Ne connaît aucun détail du CLI (toute communication passe par un
    BaseHiggsfieldProvider injecté, via GenerationJobService).
    """

    def __init__(
        self,
        provider: BaseHiggsfieldProvider,
        gate: GenerationApprovalGate,
        job_service: Optional[GenerationJobService] = None,
        quality_evaluator: Optional[QualityEvaluator] = None,
    ):
        self.provider = provider
        self.gate = gate
        self.job_service = job_service or GenerationJobService(provider, gate)
        self.quality_evaluator = quality_evaluator or QualityEvaluator()

    def generate(
        self,
        request: GenerationRequest,
        timeout_seconds: float = 600,
        interval_seconds: float = 3,
        activation_contract=None,
        provider_activation_contract=None,
        mission_id: Optional[str] = None,
    ) -> FinalReport:
        """
        Exécute la requête via GenerationJobService (qui ré-interroge
        lui-même GenerationApprovalGate) et produit un FinalReport
        fidèle. N'appelle jamais create_job() directement : toute
        création de job passe exclusivement par GenerationJobService.

        `mission_id` (Phase P3.34, optionnel, `None` par défaut) :
        OBSERVABILITY METADATA ONLY -- voir la docstring du module.
        Jamais transmis à `self.job_service.execute()` ni à
        `self.gate.evaluate()` ni à aucun composant P2 : ce paramètre
        est stampé tel quel sur le `FinalReport` retourné, et sur rien
        d'autre. `None` par défaut : comportement strictement
        identique à avant P3.34 pour tout appelant existant.

        `activation_contract` (Phase P2.22, optionnel) : simple relais
        explicite vers `GenerationJobService.execute()` -- jamais créé
        ici. `None` par défaut : comportement STRICTEMENT identique à
        avant P2.22, et `activation_decision=NOT_EVALUATED` sur le
        rapport résultant.

        `provider_activation_contract` (Phase P2.27, optionnel) : même
        principe -- simple relais explicite, jamais créé ici, `None`
        par défaut.

        Phase P2.23/P2.27 : un rejet de contrat
        (`GenerationJobActivationRejectedError` ou
        `GenerationJobProviderActivationRejectedError`, toutes deux
        sous-classes de `GenerationJobExecutionError`) est toujours
        capturé par le même `except` ci-dessous (NOT_EXECUTED, comme
        tout autre refus -- jamais un chemin séparé qui pourrait
        diverger), mais `activation_decision`/`provider_activation_
        decision` distinguent désormais EXPLICITEMENT à quel niveau le
        refus a eu lieu (Gate seul / activation P2.21 / activation
        P2.26) : chaque niveau n'est `REJECTED` que si l'exception
        correspond exactement à ce niveau ; `NOT_EVALUATED` sinon, y
        compris quand un contrat était fourni mais qu'un niveau
        antérieur a refusé avant même de l'atteindre.
        """

        try:
            outcome = self.job_service.execute(
                request,
                timeout_seconds=timeout_seconds,
                interval_seconds=interval_seconds,
                activation_contract=activation_contract,
                provider_activation_contract=provider_activation_contract,
            )
        except GenerationJobExecutionError as error:
            approval = error.approval or self.gate.evaluate(request)

            cost_status, estimated_credits = self._extract_cost_info(approval)

            is_provider_activation_rejection = isinstance(
                error, GenerationJobProviderActivationRejectedError
            )
            is_activation_rejection = isinstance(
                error, GenerationJobActivationRejectedError
            )

            # Une rejection P2.26 implique nécessairement que
            # l'activation P2.21 a été évaluée et acceptée (sinon
            # GenerationJobProviderActivationRejectedError ne serait
            # jamais levée -- cf. agents/generation_job_service.py).
            if is_provider_activation_rejection:
                activation_decision = ActivationDecision.APPROVED
            elif is_activation_rejection:
                activation_decision = ActivationDecision.REJECTED
            else:
                activation_decision = ActivationDecision.NOT_EVALUATED

            activation_reasons = (
                list(error.activation_rejection.reasons)
                if is_activation_rejection and error.activation_rejection is not None
                else []
            )

            provider_activation_decision = (
                ActivationDecision.REJECTED
                if is_provider_activation_rejection
                else ActivationDecision.NOT_EVALUATED
            )
            provider_activation_reasons = (
                list(error.provider_activation_rejection.reasons)
                if is_provider_activation_rejection
                and error.provider_activation_rejection is not None
                else []
            )

            if is_provider_activation_rejection:
                summary = (
                    f"Generation NOT executed for request "
                    f"'{request.request_id}': Gate {approval.decision.value}, "
                    f"activation APPROVED, but provider activation "
                    f"REJECTED. {error}"
                )
            elif is_activation_rejection:
                summary = (
                    f"Generation NOT executed for request "
                    f"'{request.request_id}': Gate {approval.decision.value} "
                    f"but activation REJECTED. {error}"
                )
            else:
                summary = (
                    f"Generation NOT executed for request "
                    f"'{request.request_id}': {approval.decision.value}. "
                    f"{error}"
                )

            return FinalReport(
                request_id=request.request_id,
                job_type=request.job_type,
                status=FinalReportStatus.NOT_EXECUTED,
                job_created=False,
                approval_decision=approval.decision,
                approval_reasons=list(approval.reasons),
                activation_decision=activation_decision,
                activation_reasons=activation_reasons,
                provider_activation_decision=provider_activation_decision,
                provider_activation_reasons=provider_activation_reasons,
                real_provider_called=False,
                cost_status=cost_status,
                estimated_credits=estimated_credits,
                summary=summary,
                mission_id=mission_id,
            )

        quality = self.quality_evaluator.evaluate(outcome)

        status_by_quality = {
            QualityDecision.PASS: FinalReportStatus.EXECUTED_PASS,
            QualityDecision.FAIL: FinalReportStatus.EXECUTED_FAIL,
            QualityDecision.RETRY_RECOMMENDED: (
                FinalReportStatus.EXECUTED_RETRY_RECOMMENDED
            ),
        }

        cost_status, estimated_credits = self._extract_cost_info(outcome.approval)

        return FinalReport(
            request_id=request.request_id,
            job_type=request.job_type,
            status=status_by_quality[quality.decision],
            job_created=True,
            approval_decision=outcome.approval.decision,
            approval_reasons=list(outcome.approval.reasons),
            activation_decision=(
                ActivationDecision.APPROVED
                if activation_contract is not None
                else ActivationDecision.NOT_EVALUATED
            ),
            provider_activation_decision=(
                ActivationDecision.APPROVED
                if provider_activation_contract is not None
                else ActivationDecision.NOT_EVALUATED
            ),
            real_provider_called=self._is_real_provider(),
            cost_status=cost_status,
            estimated_credits=estimated_credits,
            job_id=outcome.job.job_id,
            job_status=outcome.result.status,
            output_urls=outcome.result.output_urls,
            quality_decision=quality.decision,
            quality_reasons=list(quality.reasons),
            summary=(
                f"Generation executed for request '{request.request_id}': "
                f"job '{outcome.job.job_id}' ended with status "
                f"'{outcome.result.status.value}', quality="
                f"{quality.decision.value}."
            ),
            mission_id=mission_id,
        )

    @staticmethod
    def _extract_cost_info(approval) -> Tuple[Optional[CostEstimationStatus], Optional[float]]:
        cost_result = approval.cost_result

        if cost_result is None:
            return None, None

        credits = (
            cost_result.estimate.credits
            if cost_result.estimate is not None
            else None
        )

        return cost_result.status, credits

    def _is_real_provider(self) -> bool:
        """
        Correction P2.27 (audit truthfulness) : `real_provider_called`
        DOIT signifier littéralement "le VRAI HiggsfieldProvider a été
        utilisé", jamais "un provider quelconque a réussi à créer un
        job". Avant cette correction, le bloc de succès de generate()
        renvoyait `real_provider_called=True` INCONDITIONNELLEMENT --
        y compris pour `MockHiggsfieldProvider`, ce qui était
        factuellement faux.

        Déterminé par IDENTITÉ DE MÉTHODE contre le PROVIDER
        RÉELLEMENT UTILISÉ par `GenerationJobService`
        (`self.job_service.provider` -- jamais `self.provider` seul,
        qui pourrait en théorie diverger d'une construction erronée)
        -- exactement le même mécanisme, jamais dupliqué autrement,
        que `agents/activation_readiness.py::_check_provider()` et
        `agents/controlled_real_provider_activation.py::
        _fresh_violations()`. Ne dépend JAMAIS du résultat du job
        (`job_created`) : la preuve porte sur QUEL provider a été
        engagé, pas sur si l'appel a réussi.

        Note de cohérence architecturale (non un raccourci) :
        `HiggsfieldProvider.create_job()` (integrations/higgsfield/
        provider.py, INCHANGÉ par cette correction) lève
        inconditionnellement `HiggsfieldRealGenerationDisabledError`
        et ne renvoie donc jamais de `Job` -- ce bloc de succès ne
        peut donc, dans l'état actuel du code, jamais être atteint
        avec le vrai Provider. Cette méthode renverra par conséquent
        TOUJOURS `False` aujourd'hui pour tout rapport réellement
        produit -- ce qui est exactement le comportement honnête
        attendu, et reste correct sans modification si une phase
        future venait à activer un Provider réel fonctionnel.
        """

        provider = self.job_service.provider
        return type(provider).create_job is HiggsfieldProvider.create_job
