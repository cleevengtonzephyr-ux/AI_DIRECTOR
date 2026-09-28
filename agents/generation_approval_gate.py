"""
AI DIRECTOR — Generation Approval Gate v0.1 (Phase G, MASTER PROMPT V2)

Service responsable de BLOQUER toute génération facturable tant qu'une
approbation explicite n'a pas été obtenue, en s'appuyant exclusivement
sur les abstractions déjà construites (Phase B-F) : jamais de contact
direct avec HiggsfieldClient ni avec le CLI.

Architecture (MASTER PROMPT V2) :

    Video request (GenerationRequest)
         v
    GenerationCostService.estimate()      (Phase F, réutilisé tel quel)
         v
    CostEstimate / GenerationCostResult
         v
    GenerationApprovalGate.evaluate()
         v
    APPROVED | NEEDS_APPROVAL | BLOCKED | ALREADY_EXECUTED | INVALID_REQUEST
         v
    (future) createJob() — jamais appelé depuis ce module

IMPORTANT — séparation stricte des responsabilités :
- L'ESTIMATION du coût reste entièrement dans GenerationCostService
  (Phase F), qui délègue lui-même à HiggsfieldProvider.estimate_cost().
- La VÉRIFICATION DU BUDGET utilise HiggsfieldProvider.get_account_
  balance() (nouvelle méthode Provider, Phase G — additive, cf.
  provider.py/mock_provider.py), jamais agents/cost_engine.py
  directement : cost_engine.py instancie un HiggsfieldClient réel en
  dur dans son constructeur et n'est donc pas injectable avec un Mock,
  ce qui rendrait ce Gate impossible à tester hors-ligne (violerait la
  règle "tous les tests utilisent MockHiggsfieldProvider"). CostEngine
  (V1) n'est pas modifié et reste la référence utilisée par
  ProductionGate pour son propre flux.
- L'APPROBATION TECHNIQUE/BUDGÉTAIRE est un booléen explicite porté
  par la requête (`GenerationRequest.approved`) — ce Gate ne l'obtient
  pas lui-même (pas d'UI, pas de prompt interactif) ; il applique
  uniquement la règle métier sur sa présence/absence.
- L'AUTORISATION HUMAINE (Phase P2.11, `RealGenerationAuthorization`)
  est un DEUXIÈME verrou, structurellement distinct de `approved` :
  APPROVED n'est désormais jamais renvoyé sans une autorisation
  explicite, valide, et liée au `request_id` exact — ni le budget, ni
  `approved=True` seul, ni un dry-run, ni un cache ne peuvent la
  produire (cf. `_human_authorization_reasons()`).
- La CRÉATION RÉELLE DU JOB n'est JAMAIS effectuée ici. Ce module
  n'importe ni HiggsfieldClient, ni subprocess, et n'appelle jamais
  `create_job()`.

Idempotence / anti-double-génération :
Un registre (`executed_request_store`, Phase P2.15 — voir
agents/executed_request_store.py) retient les `request_id` déjà
marqués exécutés via `mark_executed()`, appelé par GenerationJobService
après une création de job réussie. Une seconde évaluation pour le même
`request_id` renvoie ALREADY_EXECUTED plutôt que de re-proposer une
approbation. Ce registre est en mémoire par défaut (comportement
identique à la Phase G d'origine) ; le chemin de production réel
(director.py) injecte un store persistant sur disque, afin que ce
fait survive un redémarrage du processus — ce projet n'ayant aucun
processus long-vivant, la persistance est nécessaire pour que la
protection anti-rejeu protège quoi que ce soit entre deux invocations
réelles. Une lecture d'état corrompue échoue TOUJOURS fermée
(BLOCKED), jamais vers APPROVED ni vers un silencieux "non exécuté".
"""

import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.executed_request_store import (
    ExecutedRequestStoreCorruptedError,
    InMemoryExecutedRequestStore,
)
from agents.generation_cost_service import (
    CostEstimationStatus,
    GenerationCostResult,
    GenerationCostService,
)
from agents.production_model import PRODUCTION_MODEL
from agents.release_candidate_identity_lock import ReleaseCandidateIdentityLock
from integrations.higgsfield.errors import HiggsfieldError
from integrations.higgsfield.provider import BaseHiggsfieldProvider
from integrations.higgsfield.types import MediaReference

# Durées EMPIRIQUEMENT confirmées par lecture seule (Phase P1.2,
# `generate cost`, jamais `generate create`) — le schéma statique
# (`model get`) ne déclare AUCUNE borne de durée, ces valeurs ne
# viennent donc que de tests read-only réels, pas d'une supposition.
#
# seedance_2_0 : tarif observé 4.5 crédits/seconde ; 5/10/15s acceptés
# par l'API réelle ; >15s explicitement rejeté par le serveur
# ("duration: Input should be less than or equal to 15"). Le
# comportement de l'API a déjà changé une fois au cours de ce projet
# (Phase O/P1 vs Phase P1.2) — à RE-VÉRIFIER en lecture seule avant
# toute Phase P2 future plutôt que de faire confiance indéfiniment à
# cette table.
#
# Clé indexée sur PRODUCTION_MODEL (agents/production_model.py, Phase
# P2.2) — source unique de vérité, jamais une chaîne recopiée ici.
CONFIRMED_DURATIONS_BY_MODEL: dict = {
    PRODUCTION_MODEL: (5, 10, 15),
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class GenerationApprovalDecision(str, Enum):
    """États retournés par le Gate — noms imposés par le MASTER PROMPT V2."""

    APPROVED = "APPROVED"
    NEEDS_APPROVAL = "NEEDS_APPROVAL"
    BLOCKED = "BLOCKED"
    ALREADY_EXECUTED = "ALREADY_EXECUTED"
    INVALID_REQUEST = "INVALID_REQUEST"
    # Phase P2.20 — un create_job() a peut-être réussi mais son
    # enregistrement (mark_executed) a échoué juste après : l'état
    # réel est ambigu. FAIL CLOSED, jamais rejouable automatiquement,
    # structurellement distinct d'ALREADY_EXECUTED (qui signifie une
    # exécution CONFIRMÉE, pas une exécution AMBIGUË).
    EXECUTION_STATE_UNKNOWN = "EXECUTION_STATE_UNKNOWN"


@dataclass(frozen=True)
class RealGenerationAuthorization:
    """
    Autorisation HUMAINE explicite de lancer UNE génération réelle
    précise (Phase P2.11) — deuxième verrou, structurellement distinct
    du premier (`GenerationRequest.approved`).

    Distincte, et ne pouvant JAMAIS être déduite, de :
    - `approved` (approbation technique/budgétaire : peut être vraie
      sans qu'aucun humain n'ait consciemment autorisé CETTE
      génération réelle précise) ;
    - du budget disponible ou de l'estimation de coût (aucun des deux
      ne crée jamais cette autorisation, cf.
      GenerationApprovalGate.evaluate()) ;
    - d'un dry-run, d'un ancien run, d'une configuration ou d'un cache
      (rien de tout cela ne peut produire une instance valide — seule
      une construction explicite de cette classe, par un appelant
      conscient, le peut).

    Liée à une requête précise via `request_id` : le Gate
    (GenerationApprovalGate._human_authorization_reasons) rejette
    toute autorisation dont le `request_id` ne correspond pas
    exactement à la GenerationRequest évaluée — une autorisation
    donnée pour une génération n'est jamais valable pour une autre.

    `authorized_by_human` n'a pas de valeur par défaut : il doit être
    explicitement fourni à `True` par l'appelant (jamais implicite),
    et le Gate vérifie littéralement `is True`, pas une simple valeur
    "truthy".

    Le projet ne possède pas de système d'identité utilisateur : `note`
    reste un champ texte libre, optionnel, jamais rempli
    automatiquement — à l'appelant humain d'y consigner un contexte
    réel (qui a autorisé, par quel canal) s'il le souhaite. Aucune
    identité n'est inventée ici.
    """

    request_id: str
    authorized_by_human: bool
    authorization_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    authorized_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    note: str = ""


@dataclass(frozen=True)
class GenerationRequest:
    """
    La "Video request" du diagramme MASTER PROMPT V2.

    `start_image`/`image_references` (Phase P1.1) portent les
    références visuelles validées par AssetPreparationSystem,
    traçables jusqu'au fichier local d'origine — jamais uploadées ni
    transformées ici. Un modèle qui ne déclare pas ces paramètres dans
    son schéma réel les refusera (GenerationApprovalGate._validate).

    `real_generation_authorization` (Phase P2.11) est ABSENT par
    défaut (`None`) : une GenerationRequest nouvellement construite
    n'est donc jamais autorisée à produire une génération réelle, quel
    que soit `approved`. Seule une construction explicite d'un objet
    `RealGenerationAuthorization` valide, lié à ce `request_id`, permet
    au Gate de renvoyer APPROVED (cf.
    GenerationApprovalGate.evaluate()).
    """

    request_id: str
    job_type: str
    prompt: str
    duration: Optional[int] = None
    resolution: Optional[str] = None
    aspect_ratio: Optional[str] = None
    approved: bool = False
    start_image: Optional[MediaReference] = None
    image_references: Tuple[MediaReference, ...] = field(default_factory=tuple)
    real_generation_authorization: Optional[RealGenerationAuthorization] = None


@dataclass(frozen=True)
class GenerationApprovalResult:
    """Décision typée du Gate — ne contient aucune information inventée."""

    decision: GenerationApprovalDecision
    request_id: str
    job_type: str
    reasons: List[str] = field(default_factory=list)
    cost_result: Optional[GenerationCostResult] = None
    available_credits: Optional[float] = None

    @property
    def approved(self) -> bool:
        return self.decision == GenerationApprovalDecision.APPROVED


class GenerationApprovalGate:
    """
    AI DIRECTOR — Generation Approval Gate v0.1 (Phase G)

    N'appelle JAMAIS create_job(). Ne connaît aucun détail du CLI
    (toute communication passe par un BaseHiggsfieldProvider injecté).
    """

    # Phase B (docs/phase_a_real_generation_decision.md, condition 2) :
    # une RealGenerationAuthorization expire au plus tard 300 secondes
    # après `authorized_at`. Âge == 300 s accepté, > 300 s refusé.
    MAX_AUTHORIZATION_AGE_SECONDS = 300.0

    def __init__(
        self,
        provider: BaseHiggsfieldProvider,
        cost_service: Optional[GenerationCostService] = None,
        executed_request_store=None,
        identity_lock: Optional[ReleaseCandidateIdentityLock] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        """
        `executed_request_store` (Phase P2.15) : persiste le replay
        guard au-delà de la durée de vie de ce Gate. Par défaut
        (`None`), un `InMemoryExecutedRequestStore` est utilisé —
        comportement STRICTEMENT identique à l'ancien `_executed_
        request_ids: Set[str]` (Phase G), pour ne rien changer au
        code/tests existants qui construisent `GenerationApprovalGate
        (provider)` sans argument supplémentaire. Le chemin de
        production réel (director.py) injecte explicitement un
        `FileExecutedRequestStore` (agents/executed_request_store.py).

        `identity_lock` (Phase P2.18) : verrou optionnel d'identité de
        Release Candidate (agents/release_candidate_identity_lock.py).
        Par défaut (`None`), AUCUNE vérification d'identité prompt/
        assets n'est effectuée — comportement STRICTEMENT identique à
        avant P2.18, pour ne rien changer aux 356 tests existants qui
        construisent `GenerationApprovalGate(provider)` sans cet
        argument. Le chemin de production réel (director.py) injecte
        explicitement un `ReleaseCandidateIdentityLock` lié à la
        Release Candidate actuellement validée (Video 005).

        `clock` (Phase B) : horloge UTC utilisée pour vérifier
        l'expiration de `RealGenerationAuthorization.authorized_at`.
        Par défaut, l'heure réelle ; injectable pour des tests
        déterministes.
        """

        self.provider = provider
        self.cost_service = cost_service or GenerationCostService(provider)
        self.executed_request_store = executed_request_store or InMemoryExecutedRequestStore()
        self.identity_lock = identity_lock
        self._clock = clock or _utc_now

    # ------------------------------------------------------------------
    # DÉCISION PRINCIPALE
    # ------------------------------------------------------------------

    def evaluate(self, request: GenerationRequest) -> GenerationApprovalResult:
        """
        Évalue une demande de génération et retourne une décision
        typée. Ne crée et n'appelle JAMAIS de job.
        """

        validation_errors = self._validate(request)

        if validation_errors:
            return GenerationApprovalResult(
                decision=GenerationApprovalDecision.INVALID_REQUEST,
                request_id=request.request_id,
                job_type=request.job_type,
                reasons=validation_errors,
            )

        try:
            already_executed = self.executed_request_store.is_executed(
                request.request_id
            )
            is_unknown_state = self.executed_request_store.is_unknown(
                request.request_id
            )
        except ExecutedRequestStoreCorruptedError as error:
            # FAIL CLOSED (Phase P2.15) : un état de replay guard
            # illisible/corrompu ne doit JAMAIS être interprété comme
            # "non exécuté" (ce qui autoriserait un rejeu) ni comme
            # "exécuté" par défaut — il bloque, point final.
            return GenerationApprovalResult(
                decision=GenerationApprovalDecision.BLOCKED,
                request_id=request.request_id,
                job_type=request.job_type,
                reasons=[
                    f"Replay guard state could not be verified; failing "
                    f"closed rather than risking a replay or a false "
                    f"approval: {error}"
                ],
            )

        if is_unknown_state:
            # Phase P2.20 : un create_job() antérieur a peut-être
            # réussi mais n'a pas pu être enregistré de façon fiable.
            # Vérifié AVANT already_executed : un état ambigu doit
            # rester ambigu (jamais silencieusement traité comme "pas
            # encore exécuté", ce qui autoriserait un rejeu automatique
            # dangereux).
            return GenerationApprovalResult(
                decision=GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN,
                request_id=request.request_id,
                job_type=request.job_type,
                reasons=[
                    f"Request '{request.request_id}' is in an UNKNOWN "
                    f"execution state: a prior create_job() attempt may "
                    f"have succeeded but was not reliably recorded. "
                    f"Automatic retry is refused; this requires explicit "
                    f"human review before any further action."
                ],
            )

        if already_executed:
            return GenerationApprovalResult(
                decision=GenerationApprovalDecision.ALREADY_EXECUTED,
                request_id=request.request_id,
                job_type=request.job_type,
                reasons=[
                    f"Request '{request.request_id}' has already been executed."
                ],
            )

        cost_result = self.cost_service.estimate(
            job_type=request.job_type,
            prompt=request.prompt,
            duration=request.duration,
            resolution=request.resolution,
            aspect_ratio=request.aspect_ratio,
        )

        # Erreur du Cost Service : décision sûre, jamais APPROVED.
        if cost_result.status == CostEstimationStatus.ERROR:
            return GenerationApprovalResult(
                decision=GenerationApprovalDecision.BLOCKED,
                request_id=request.request_id,
                job_type=request.job_type,
                reasons=[f"Cost estimation error: {cost_result.error}"],
                cost_result=cost_result,
            )

        # Coût inconnu : jamais d'autorisation silencieuse.
        if cost_result.status == CostEstimationStatus.UNKNOWN:
            reasons = []

            if not request.approved:
                reasons.append(
                    "Cost is unknown; explicit approval is required "
                    "before proceeding."
                )

            reasons.extend(self._human_authorization_reasons(request))

            if reasons:
                return GenerationApprovalResult(
                    decision=GenerationApprovalDecision.NEEDS_APPROVAL,
                    request_id=request.request_id,
                    job_type=request.job_type,
                    reasons=reasons,
                    cost_result=cost_result,
                )

            return GenerationApprovalResult(
                decision=GenerationApprovalDecision.APPROVED,
                request_id=request.request_id,
                job_type=request.job_type,
                reasons=[
                    "Cost is unknown but explicit approval and explicit "
                    "human authorization for real generation were both "
                    "given."
                ],
                cost_result=cost_result,
            )

        # Coût CONNU : vérification du budget via le Provider.
        try:
            available = self.provider.get_account_balance()
        except HiggsfieldError as error:
            return GenerationApprovalResult(
                decision=GenerationApprovalDecision.BLOCKED,
                request_id=request.request_id,
                job_type=request.job_type,
                reasons=[f"Unable to verify account balance: {error}"],
                cost_result=cost_result,
            )

        if available is None:
            return GenerationApprovalResult(
                decision=GenerationApprovalDecision.BLOCKED,
                request_id=request.request_id,
                job_type=request.job_type,
                reasons=[
                    "Account balance could not be determined; budget "
                    "cannot be verified."
                ],
                cost_result=cost_result,
            )

        required = cost_result.estimate.credits

        if required > available:
            return GenerationApprovalResult(
                decision=GenerationApprovalDecision.BLOCKED,
                request_id=request.request_id,
                job_type=request.job_type,
                reasons=[
                    f"Insufficient credits: {available} available < "
                    f"{required} required."
                ],
                cost_result=cost_result,
                available_credits=available,
            )

        reasons = []

        if not request.approved:
            reasons.append(
                "Cost known and budget sufficient; explicit "
                "approval is required before proceeding."
            )

        reasons.extend(self._human_authorization_reasons(request))

        if reasons:
            return GenerationApprovalResult(
                decision=GenerationApprovalDecision.NEEDS_APPROVAL,
                request_id=request.request_id,
                job_type=request.job_type,
                reasons=reasons,
                cost_result=cost_result,
                available_credits=available,
            )

        return GenerationApprovalResult(
            decision=GenerationApprovalDecision.APPROVED,
            request_id=request.request_id,
            job_type=request.job_type,
            reasons=[
                "Cost known, budget sufficient, explicit approval given, "
                "and explicit human authorization for real generation "
                "provided."
            ],
            cost_result=cost_result,
            available_credits=available,
        )

    # ------------------------------------------------------------------
    # IDEMPOTENCE
    # ------------------------------------------------------------------

    def mark_executed(self, request_id: str, job_id: Optional[str] = None) -> None:
        """
        À appeler par GenerationJobService APRÈS la création réussie
        d'un job réel. Ce Gate lui-même n'appelle jamais cette méthode
        automatiquement : une décision APPROVED n'implique pas qu'une
        exécution a eu lieu.

        Délègue au store injecté (Phase P2.15) : persiste au-delà de
        la durée de vie de ce Gate si un `FileExecutedRequestStore` a
        été injecté (chemin de production réel), reste en mémoire
        uniquement sinon (comportement identique à avant P2.15).

        Phase P3.89 : `job_id` (trace, jamais une autorisation) est
        persisté dans le même enregistrement ; `evaluate()` ne le lit
        jamais.
        """

        self.executed_request_store.mark_executed(request_id, job_id=job_id)

    def is_already_executed(self, request_id: str) -> bool:
        return self.executed_request_store.is_executed(request_id)

    def mark_unknown(self, request_id: str, reason: str = "", job_id: Optional[str] = None) -> None:
        """
        Phase P2.20 — à appeler par GenerationJobService quand
        `create_job()` a réussi mais que `mark_executed()` a échoué
        juste après : consigne l'ambiguïté plutôt que de la laisser
        silencieuse. Délègue au store injecté, comme `mark_executed`.
        Phase P3.89 : `job_id` persisté comme champ structuré.
        """

        self.executed_request_store.mark_unknown(request_id, reason=reason, job_id=job_id)

    def in_flight(self, request_id: str):
        """
        Phase P3.91 — context manager à utiliser par
        GenerationJobService, DANS la section critique, AUTOUR de
        `create_job()` : écriture anticipée (write-ahead) d'un marqueur
        lu comme UNKNOWN par `evaluate()` tant que `mark_executed()` ne
        l'a pas remplacé. Un crash entre `create_job()` et
        `mark_executed()` laisse donc une trace bloquante, jamais une
        absence de trace. Ne crée aucune autorité : ce marqueur ne peut
        que BLOQUER (cf. store pour l'unique retour arrière autorisé).
        """

        return self.executed_request_store.in_flight(request_id)

    def is_unknown(self, request_id: str) -> bool:
        return self.executed_request_store.is_unknown(request_id)

    # ------------------------------------------------------------------
    # AUTORISATION HUMAINE (Phase P2.11) — second verrou, indépendant
    # de `approved` et du budget.
    # ------------------------------------------------------------------

    def _human_authorization_reasons(self, request: GenerationRequest) -> List[str]:
        """
        Renvoie la liste des raisons pour lesquelles
        `request.real_generation_authorization` N'AUTORISE PAS une
        génération réelle. Liste vide == autorisation valide pour
        CETTE requête précise.

        Ne fait JAMAIS de fallback vers `approved`, le budget, un
        cache ou une configuration : seule une instance de
        RealGenerationAuthorization explicitement construite, avec
        `authorized_by_human is True`, `request_id` correspondant
        exactement à cette requête et `authorized_at` frais (Phase B :
        au plus MAX_AUTHORIZATION_AGE_SECONDS, jamais dans le futur),
        est acceptée.
        """

        auth = request.real_generation_authorization

        if auth is None:
            return [
                "No explicit human authorization for real generation "
                "was provided (real_generation_authorization is None)."
            ]

        if not isinstance(auth, RealGenerationAuthorization):
            return [
                "real_generation_authorization is not a valid "
                "RealGenerationAuthorization instance."
            ]

        if auth.authorized_by_human is not True:
            return [
                "real_generation_authorization.authorized_by_human is "
                "not explicitly True."
            ]

        if auth.request_id != request.request_id:
            return [
                f"real_generation_authorization is bound to request "
                f"'{auth.request_id}', not to this request "
                f"'{request.request_id}'."
            ]

        return self._authorization_freshness_reasons(auth)

    def _authorization_freshness_reasons(self, auth: RealGenerationAuthorization) -> List[str]:
        """Phase B : refuse un `authorized_at` absent, invalide, sans
        fuseau, futur ou plus vieux que MAX_AUTHORIZATION_AGE_SECONDS."""

        raw = auth.authorized_at
        if not isinstance(raw, str) or not raw.strip():
            return ["real_generation_authorization.authorized_at is missing."]
        try:
            issued_at = datetime.fromisoformat(raw)
        except ValueError:
            return [
                f"real_generation_authorization.authorized_at {raw!r} is "
                f"not a valid ISO-8601 timestamp."
            ]
        if issued_at.utcoffset() is None:
            return [
                f"real_generation_authorization.authorized_at {raw!r} has "
                f"no timezone -- ambiguous, refused."
            ]
        try:
            age_seconds = (self._clock() - issued_at).total_seconds()
        except TypeError:
            return ["Gate clock is not timezone-aware -- authorization freshness cannot be verified."]
        if age_seconds < 0:
            return [
                f"real_generation_authorization.authorized_at {raw!r} is in "
                f"the future."
            ]
        if age_seconds > self.MAX_AUTHORIZATION_AGE_SECONDS:
            return [
                f"real_generation_authorization expired: issued "
                f"{age_seconds:.0f}s ago, max {self.MAX_AUTHORIZATION_AGE_SECONDS:.0f}s."
            ]
        return []

    # ------------------------------------------------------------------
    # VALIDATION
    # ------------------------------------------------------------------

    def _validate(self, request: GenerationRequest) -> List[str]:
        errors = []

        # Identity Lock (Phase P2.18) — vérifié EN PREMIER, avant même
        # le replay guard/coût/budget (hiérarchie explicitement requise :
        # Identity Integrity -> Replay -> Cost -> Balance -> ...). Aucun
        # effet si `identity_lock` n'a pas été injecté (défaut `None`).
        if self.identity_lock is not None:
            errors.extend(self.identity_lock.violations(request))

        if not request.request_id:
            errors.append("request_id is missing.")

        if not request.job_type:
            errors.append("job_type is missing.")

        if not isinstance(request.prompt, str) or not request.prompt.strip():
            errors.append("prompt is missing or empty.")

        if request.duration is not None and (
            not isinstance(request.duration, int) or request.duration <= 0
        ):
            errors.append("duration must be a positive integer when provided.")

        if request.job_type:
            errors.extend(self._validate_model_compatibility(request))

        return errors

    def _validate_model_compatibility(
        self,
        request: GenerationRequest,
    ) -> List[str]:
        """
        Vérifie, à partir du VRAI schéma du modèle (Provider.get_model,
        Phase P1.1), que les capacités demandées sont réellement
        supportées. RIEN n'est supposé : tout ce qui n'est pas
        explicitement confirmé par le schéma est refusé.

        - start_image/image_references : refusés si le modèle ne
          déclare pas ces paramètres.
        - duration : le schéma ne confirme que sa valeur par défaut
          (aucun maximum n'est déclaré par l'API pour la plupart des
          modèles) — toute valeur différente du défaut est donc
          UNVERIFIED et traitée comme invalide tant qu'elle n'a pas été
          confirmée par une génération réelle (hors périmètre de ces
          phases).
        """

        errors: List[str] = []

        try:
            schema = self.provider.get_model(request.job_type)
        except HiggsfieldError as error:
            errors.append(
                f"Unable to verify model capabilities for "
                f"'{request.job_type}': {error}"
            )
            return errors

        if request.start_image is not None and schema.param("start_image") is None:
            errors.append(
                f"Model '{request.job_type}' does not support start_image."
            )

        if request.image_references and schema.param("image_references") is None:
            errors.append(
                f"Model '{request.job_type}' does not support "
                f"image_references."
            )

        if request.duration is not None:
            duration_param = schema.param("duration")

            if duration_param is None:
                errors.append(
                    f"Model '{request.job_type}' does not declare a "
                    f"'duration' parameter; duration cannot be confirmed."
                )
            else:
                confirmed_durations = CONFIRMED_DURATIONS_BY_MODEL.get(
                    request.job_type
                )

                if confirmed_durations is not None:
                    # Modèle spécifiquement audité en lecture seule
                    # (Phase P1.2) : seules les valeurs de cette table
                    # sont acceptées, jamais une durée simplement
                    # "présente dans un VideoPlan".
                    if request.duration not in confirmed_durations:
                        errors.append(
                            f"Duration {request.duration}s is UNVERIFIED "
                            f"for model '{request.job_type}': only "
                            f"{confirmed_durations}s are confirmed by "
                            f"real read-only cost checks (Phase P1.2). "
                            f"Not treated as valid until re-confirmed."
                        )
                elif (
                    duration_param.default is not None
                    and request.duration != duration_param.default
                ):
                    # Aucun profil empirique pour ce modèle : seul le
                    # défaut déclaré par le schéma reste confirmé.
                    errors.append(
                        f"Duration {request.duration}s is UNVERIFIED for "
                        f"model '{request.job_type}': the API schema only "
                        f"confirms the default of {duration_param.default}s "
                        f"(no maximum is declared, and no empirical "
                        f"confirmation is registered for this model). Not "
                        f"treated as valid until confirmed."
                    )

        return errors
