"""
AI DIRECTOR — Request-Scoped Activation Contract (Phase P2.21, MASTER PROMPT V2)

Formalise, comme CODE DE PRODUCTION cette fois (et non plus une
simulation locale à un fichier de test, cf.
`tests/test_phase_p2_19_activation_contract_design.py::_SimulatedActivationContract`),
ce qu'une future génération réelle extrêmement contrôlée devra exiger
avant même d'envisager `create_job()`.

STOP -- PORTÉE ABSOLUE DE CE MODULE :
Ce module ne crée JAMAIS de job, n'appelle JAMAIS create_job(),
n'importe ni HiggsfieldClient ni subprocess. MIS À JOUR Phase P2.22 :
`GenerationJobService.execute()` accepte désormais explicitement un
`activation_contract` (cf. agents/generation_job_service.py) et
appelle `validate_activation()` lui-même DANS le verrou critique --
mais ce câblage reste STRUCTUREL, jamais AUTOMATIQUE : rien dans
`director.py::run_video_mission()` ne construit ni ne fournit de
contrat aujourd'hui (cf. section ACTIVATION AUTHORITY BOUNDARY
ci-dessous, Phase P2.23, et `tests/test_phase_p2_22_activation_wiring.py`
/ `tests/test_phase_p2_23_final_report_authority.py`, qui le
vérifient structurellement). Un contrat produit par ce module ne peut,
à lui seul, ni aujourd'hui ni par construction, déclencher quoi que ce
soit : il ne fait que répondre à la question « cette requête précise
serait-elle éligible à une future activation, SOUS RÉSERVE d'une
re-vérification totalement fraîche au moment exact de l'utiliser ? »
-- jamais « vas-y ».

ACTIVATION AUTHORITY BOUNDARY (Phase P2.23) :
Trois rôles STRICTEMENT distincts, jamais fusionnés :

    Director / Planner (director.py, agents/planner.py)
         |  produit une GenerationRequest -- SANS AUCUNE autorité
         |  d'activation : `real_generation_authorization` reste
         |  `None` par défaut, jamais dérivé de `approved`, jamais
         |  construit automatiquement par ce code.
         v
    Human / Explicit Activation Authority (appelant EXTERNE)
         |  construit une RealGenerationAuthorization explicite,
         |  liée à CE request_id exact -- SEUL mécanisme qui existe
         |  pour produire cette autorité (cf. agents/
         |  generation_approval_gate.py::RealGenerationAuthorization).
         v
    RequestScopedActivationService.prepare_activation(request)
         |  vérifie CETTE autorité EN PREMIER (avant même le Gate/
         |  Identity Lock, cf. docstring de la méthode) -- jamais
         |  appelée automatiquement par le Director/Planner ci-dessus.
         v
    RequestScopedActivationContract
         v
    GenerationJobService.execute(request, activation_contract)

Aucun raccourci n'existe entre la première étape et la troisième :
`Gate = APPROVED` seul ne fait et ne fera jamais appeler
`prepare_activation()` automatiquement (vérifié structurellement --
aucun appel à `prepare_activation` n'existe dans `director.py`,
`agents/planner.py`, `agents/video_agent.py` ou `agents/task_manager.py`).

ARCHITECTURE (Étape 11 du rapport P2.21) :

    prepare_activation(request)
         v   (re-vérifie TOUT depuis zéro : identité, coût/budget,
         v    replay, double consentement -- rien n'est mis en cache
         v    à des fins de DÉCISION, seulement pour traçabilité)
    RequestScopedActivationContract  (éphémère, lié à CE request_id,
         v                            à usage UNIQUE, en mémoire only)
    validate_activation(request, contract)
         v   (re-vérifie À NOUVEAU tout depuis zéro, + vérifie que le
         v    contrat correspond exactement à cette requête, n'a pas
         v    expiré, n'a pas déjà été consommé -- puis le consomme)
    "cette requête est ACTUELLEMENT éligible à une activation"
         v
    (HORS PÉRIMÈTRE DE P2.21) execute_real_generation(request, contract)
         -- N'EXISTE PAS dans ce module. Une phase future pourrait
            câbler validate_activation() À L'INTÉRIEUR du verrou de
            section critique (agents/critical_section_lock.py,
            Phase P2.20), juste avant create_job(), sans jamais
            déplacer wait_for_job() dans cette section -- mais cette
            phase (P2.21) n'effectue PAS ce câblage, délibérément.

DOUBLE CONSENTEMENT (Étape 4) :
`_fresh_check()` exige `gate.evaluate(request).decision == APPROVED`,
qui EST DÉJÀ, par construction de `GenerationApprovalGate` (Phase G,
P2.11), la preuve que les DEUX consentements existent
indépendamment : `request.approved is True` (technique/budgétaire) ET
`request.real_generation_authorization` valide, lié EXACTEMENT à ce
`request_id`, avec `authorized_by_human is True` (humain, Phase P2.11)
-- ce module ne duplique jamais cette logique, il la RÉUTILISE.
Aucune autorisation humaine n'est jamais créée, déduite ou complétée
ici.

NE PERSISTE JAMAIS `RealGenerationAuthorization` (règle absolue
P2.21) : le contrat ne porte que `authorization_id` (identifiant
opaque généré par `RealGenerationAuthorization.authorization_id`, pas
un secret ; Phase B : comparé à l'autorisation de la requête à chaque
validation, cf. `_activation_violations()`) -- jamais l'objet
d'autorisation lui-même, jamais `authorized_by_human`, jamais de note
libre.

IDENTITY LOCK OBLIGATOIRE (Étape 5) :
`identity_lock` est un paramètre REQUIS (non optionnel) du
constructeur de `RequestScopedActivationService` -- contrairement à
`GenerationApprovalGate`, où il reste optionnel pour ne pas casser les
356+ tests antérieurs à P2.18. Impossible de construire ce service
sans une identité réelle à vérifier : fail-closed PAR CONSTRUCTION,
pas seulement par vérification au runtime. `identity_lock.violations()`
est appelé directement par ce service (recalcul réel depuis le prompt
et les fichiers d'assets tels qu'ils apparaissent RÉELLEMENT dans la
requête évaluée, jamais une valeur déclarée) -- EN PLUS de la
vérification déjà effectuée par le Gate si celui-ci porte lui-même un
`identity_lock` (défense en profondeur intentionnelle, redondante par
design, comme l'exige l'Objectif 7 de P2.18).

FRESHNESS (Étape 6) :
`prepare_activation()` ET `validate_activation()` appellent CHACUNE
`gate.evaluate(request)` (qui relit lui-même le coût/solde RÉELS à cet
instant précis, cf. P2.19 TestH/TestI) et `identity_lock.violations()`
(qui relit les fichiers RÉELS sur disque à cet instant précis). AUCUNE
valeur de coût/solde/identité n'est jamais mise en cache à des fins de
décision : seule `prompt_sha256` est conservée sur le contrat, et
UNIQUEMENT pour une vérification de cohérence en PLUS (jamais À LA
PLACE) de la re-vérification complète par l'Identity Lock.

LIFETIME (Étape 7) :
- Contrat en mémoire UNIQUEMENT (aucune écriture disque) : ni
  persistant au-delà du processus, ni partagé entre deux instances de
  `RequestScopedActivationService` (un contrat produit par une
  instance A est explicitement REFUSÉ par une instance B -- ce
  service ne fait jamais confiance à un contrat qu'il n'a pas
  lui-même émis).
- Usage UNIQUE : `validate_activation()` marque le contrat consommé
  (`_consumed_activation_ids`) ; une seconde validation du MÊME
  contrat est refusée.
- Expire après `max_age_seconds` (5 minutes par défaut) : un contrat
  trop ancien doit être régénéré, jamais réutilisé indéfiniment. Cette
  expiration est un FILET DE SÉCURITÉ SUPPLÉMENTAIRE, jamais un
  substitut aux re-vérifications fraîches ci-dessus.

REPLAY (Étape 8) :
`gate.evaluate()` renvoie `ALREADY_EXECUTED` ou
`EXECUTION_STATE_UNKNOWN` (Phase P2.15/P2.20) exactement comme pour
tout appelant -- ce module ne les intercepte ni ne les contourne
JAMAIS : un décision non-APPROVED du Gate, quelle qu'elle soit, est
systématiquement une raison de refus de `prepare_activation()` et de
`validate_activation()`.

FAIL CLOSED (Étape 12) :
Toute ambiguïté (contrat absent, mauvais request_id, expiré, déjà
consommé, non émis par cette instance, Gate non-APPROVED, violation
d'identité) lève `ActivationRejectedError` avec la liste complète des
raisons -- jamais une approbation par défaut, jamais un fallback
permissif.
"""

import hashlib
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Set

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from agents.release_candidate_identity_lock import ReleaseCandidateIdentityLock


class ActivationRejectedError(RuntimeError):
    """
    Levée par `prepare_activation()` ou `validate_activation()` dès
    qu'AU MOINS UNE condition n'est pas réunie. `reasons` porte la
    liste complète (jamais tronquée à la première raison trouvée) pour
    permettre une revue humaine exhaustive en un seul passage.
    """

    def __init__(self, message: str, reasons: List[str]):
        super().__init__(message)
        self.reasons = list(reasons)


@dataclass(frozen=True)
class RequestScopedActivationContract:
    """
    Snapshot éphémère, à usage unique, PRODUIT UNIQUEMENT par
    `RequestScopedActivationService.prepare_activation()`. Ne contient
    aucune information permettant à elle seule de déclencher une
    génération : ni credentials, ni objet `RealGenerationAuthorization`,
    ni décision d'approbation figée (celle-ci est toujours
    RE-vérifiée, jamais relue depuis ce contrat).

    `authorization_id` est l'identifiant opaque (UUID) porté par
    `RealGenerationAuthorization.authorization_id` -- pas un secret.
    Phase B : il LIE le contrat à cette autorisation précise ;
    `validate_activation()`/`inspect_activation()` refusent le contrat
    si la requête porte une autre autorisation (même valide pour le
    même request_id). `prompt_sha256` sert de vérification de cohérence
    supplémentaire (Étape 6), jamais de source de vérité (l'Identity
    Lock reste seul juge de la conformité réelle du prompt).
    """

    activation_id: str
    request_id: str
    job_type: str
    duration: Optional[int]
    resolution: Optional[str]
    aspect_ratio: Optional[str]
    prompt_sha256: str
    authorization_id: str
    created_at: str


class RequestScopedActivationService:
    """
    AI DIRECTOR — Request-Scoped Activation Contract Service (Phase P2.21)

    N'appelle JAMAIS `provider.create_job()`. N'importe ni
    `HiggsfieldClient`, ni `subprocess`. Ne connaît rien du verrou de
    section critique (Phase P2.20) ni de `GenerationJobService` : une
    intégration future pourrait entourer un appel à
    `validate_activation()` avec `FileCriticalSectionLock.acquire()`,
    mais ce module ne le fait pas et ne le suppose pas.
    """

    def __init__(
        self,
        gate: GenerationApprovalGate,
        identity_lock: ReleaseCandidateIdentityLock,
        max_age_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        if identity_lock is None:
            raise ValueError(
                "RequestScopedActivationService requires an explicit "
                "ReleaseCandidateIdentityLock: Identity Lock is "
                "mandatory for this service (Phase P2.21, Étape 5), "
                "unlike GenerationApprovalGate where it stays optional "
                "for backward compatibility. Refusing to construct a "
                "service that could ever skip identity verification."
            )

        self.gate = gate
        self.identity_lock = identity_lock
        self.max_age_seconds = max_age_seconds
        self._clock = clock
        self._consumed_activation_ids: Set[str] = set()
        # activation_id -> horodatage (self._clock()) de création,
        # EN MÉMOIRE UNIQUEMENT. Sert à la fois de preuve "émis par
        # cette instance" (Lifetime) et de base pour l'expiration.
        self._issued_at: dict = {}

    # ------------------------------------------------------------------
    # PRÉPARATION -- crée un contrat éphémère SI ET SEULEMENT SI toutes
    # les conditions actuelles sont réunies.
    # ------------------------------------------------------------------

    def prepare_activation(
        self, request: GenerationRequest
    ) -> RequestScopedActivationContract:
        """
        ACTIVATION AUTHORITY BOUNDARY (Phase P2.23) : la toute première
        chose vérifiée ici, AVANT même le Gate/l'Identity Lock, est la
        présence d'une `RealGenerationAuthorization` explicite liée à
        CE `request_id` exact -- jamais déduite d'un `gate.evaluate()
        == APPROVED`, même si le Gate l'exige déjà lui-même en
        interne. Cette redondance est DÉLIBÉRÉE (défense en
        profondeur, même logique que P2.18 pour les hashs déclarés vs
        réels) : `prepare_activation()` ne doit JAMAIS pouvoir devenir
        accessible uniquement parce qu'un Gate, aujourd'hui ou dans une
        refonte future, se met à renvoyer APPROVED sans cette
        autorisation -- l'autorité d'activation est vérifiée par CE
        service lui-même, indépendamment de ce que le Gate décide.

        Qui peut appeler cette méthode : jamais `AIDirector`,
        `VideoPlanner`, ni aucun code de planification -- ceux-ci ne
        produisent qu'une `GenerationRequest`, sans jamais construire
        ni fournir de `RealGenerationAuthorization` (cf.
        `director.py::run_video_mission()`, paramètre `real_generation_
        authorization` par défaut `None`, jamais dérivé de `approved`).
        Seul un appelant EXTERNE à la planification, en possession
        d'une autorisation humaine explicite pour CETTE requête
        précise, peut légitimement appeler `prepare_activation()` --
        aucun mécanisme de ce module ne peut jamais construire cette
        autorisation à sa place.
        """

        auth = request.real_generation_authorization
        if (
            auth is None
            or not isinstance(auth, RealGenerationAuthorization)
            or auth.request_id != request.request_id
        ):
            # Phase P2.38 audit finding: `not isinstance(...)` added --
            # previously, a malformed (non-None, non-RealGeneration
            # Authorization) `real_generation_authorization` reached
            # `auth.request_id` directly and raised an unhandled
            # `AttributeError` instead of the intended, cleanly typed
            # `ActivationRejectedError`. This was never a safety gap
            # (both outcomes already failed closed -- no path ever
            # approved anything), but the inconsistent exception type
            # broke the "fail closed with a typed, catchable rejection"
            # guarantee every other check in this module already
            # provides. Mirrors the isinstance check already performed
            # by `GenerationApprovalGate._human_authorization_reasons()`.
            raise ActivationRejectedError(
                f"Cannot prepare activation contract for request "
                f"'{request.request_id}': no explicit Activation "
                f"Authority (RealGenerationAuthorization) bound to "
                f"this exact request -- prepare_activation() never "
                f"infers authority from a Gate decision alone, "
                f"regardless of what gate.evaluate() would return.",
                [
                    "real_generation_authorization is missing or not "
                    "bound to this exact request_id."
                ],
            )

        reasons = self._fresh_violations(request)

        if reasons:
            raise ActivationRejectedError(
                f"Cannot prepare activation contract for request "
                f"'{request.request_id}': not currently eligible.",
                reasons,
            )

        contract = RequestScopedActivationContract(
            activation_id=uuid.uuid4().hex,
            request_id=request.request_id,
            job_type=request.job_type,
            duration=request.duration,
            resolution=request.resolution,
            aspect_ratio=request.aspect_ratio,
            prompt_sha256=hashlib.sha256(request.prompt.encode("utf-8")).hexdigest(),
            authorization_id=auth.authorization_id,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        self._issued_at[contract.activation_id] = self._clock()

        return contract

    # ------------------------------------------------------------------
    # VALIDATION -- immédiatement avant une éventuelle future
    # activation réelle : re-vérifie TOUT depuis zéro, plus la santé du
    # contrat lui-même, puis le consomme (usage unique).
    # ------------------------------------------------------------------

    def validate_activation(
        self,
        request: GenerationRequest,
        contract: RequestScopedActivationContract,
    ) -> RequestScopedActivationContract:
        reasons = self._activation_violations(request, contract)

        if reasons:
            raise ActivationRejectedError(
                f"Cannot validate activation contract "
                f"'{contract.activation_id}' for request "
                f"'{request.request_id}'.",
                reasons,
            )

        self._consumed_activation_ids.add(contract.activation_id)

        return contract

    def consume(self, contract: RequestScopedActivationContract) -> None:
        """
        Phase P2.27 — marque `contract` consommé SANS re-vérifier quoi
        que ce soit : réservé aux appelants (ex.
        `GenerationJobService.execute()`, lorsqu'une couche
        supplémentaire -- Phase P2.26 -- doit encore inspecter ce même
        contrat P2.21 APRÈS que sa validité a déjà été confirmée par
        `inspect_activation()`, mais AVANT que la consommation
        définitive n'ait lieu) qui ont DÉJÀ obtenu une confirmation de
        validité fraîche (via `inspect_activation()`) dans le MÊME
        appel, et qui ne veulent consommer qu'une fois toutes les
        couches suivantes également validées. N'est JAMAIS un raccourci
        pour consommer un contrat qui n'a pas été vérifié : tout
        appelant public de ce module doit continuer à passer par
        `inspect_activation()`/`validate_activation()` pour la
        vérification elle-même.
        """

        self._consumed_activation_ids.add(contract.activation_id)

    def inspect_activation(
        self,
        request: GenerationRequest,
        contract: RequestScopedActivationContract,
    ) -> List[str]:
        """
        Phase P2.24 — variante NON MUTANTE de `validate_activation()` :
        renvoie EXACTEMENT les mêmes raisons de refus (liste vide ==
        le contrat validerait actuellement), SANS jamais consommer le
        contrat ni lever d'exception. Réservée aux lectures de type
        "readiness" (cf. agents/activation_readiness.py) : un contrat
        réel à usage unique ne doit JAMAIS être brûlé par une simple
        inspection. N'est JAMAIS un substitut à `validate_activation()`
        immédiatement avant une future activation réelle -- celle-ci
        DOIT continuer à consommer le contrat.
        """

        return self._activation_violations(request, contract)

    def _activation_violations(
        self,
        request: GenerationRequest,
        contract: RequestScopedActivationContract,
    ) -> List[str]:
        """Logique de vérification partagée, PURE (aucun effet de
        bord) entre `validate_activation()` (qui consomme ensuite le
        contrat si cette liste est vide) et `inspect_activation()`
        (qui ne consomme jamais rien, cf. Phase P2.24)."""

        reasons: List[str] = []

        if contract.request_id != request.request_id:
            reasons.append(
                f"Activation contract is bound to request "
                f"'{contract.request_id}', not to this request "
                f"'{request.request_id}'."
            )

        issued_at = self._issued_at.get(contract.activation_id)

        if issued_at is None:
            reasons.append(
                f"Activation contract '{contract.activation_id}' was "
                f"not issued by this RequestScopedActivationService "
                f"instance (or was already consumed and forgotten) -- "
                f"refusing to trust a contract this instance cannot "
                f"vouch for."
            )
        elif contract.activation_id in self._consumed_activation_ids:
            reasons.append(
                f"Activation contract '{contract.activation_id}' has "
                f"already been consumed -- activation contracts are "
                f"single-use and are never reusable."
            )
        elif self._clock() - issued_at > self.max_age_seconds:
            reasons.append(
                f"Activation contract '{contract.activation_id}' has "
                f"expired ({self.max_age_seconds}s max age) -- call "
                f"prepare_activation() again for a fresh contract."
            )

        # Phase B : le contrat n'est valable que pour l'autorisation
        # EXACTE dont il a été préparé -- jamais transférable à une
        # autre autorisation, même valide pour le même request_id.
        auth = request.real_generation_authorization
        request_authorization_id = (
            auth.authorization_id
            if isinstance(auth, RealGenerationAuthorization)
            else None
        )
        if request_authorization_id is None or contract.authorization_id != request_authorization_id:
            reasons.append(
                f"Activation contract is bound to authorization "
                f"'{contract.authorization_id}', not to this request's "
                f"authorization {request_authorization_id!r} -- not "
                f"transferable between authorizations."
            )

        actual_prompt_sha256 = hashlib.sha256(
            request.prompt.encode("utf-8") if isinstance(request.prompt, str) else b""
        ).hexdigest()
        if actual_prompt_sha256 != contract.prompt_sha256:
            reasons.append(
                f"Activation contract prompt sha256 "
                f"'{contract.prompt_sha256}' does not match this "
                f"request's current prompt sha256 "
                f"'{actual_prompt_sha256}' -- the request changed since "
                f"the contract was prepared."
            )

        reasons.extend(self._fresh_violations(request))

        return reasons

    # ------------------------------------------------------------------
    # VÉRIFICATIONS FRAÎCHES -- partagées par prepare_activation() et
    # validate_activation(), jamais mises en cache entre les deux.
    # ------------------------------------------------------------------

    def _fresh_violations(self, request: GenerationRequest) -> List[str]:
        reasons: List[str] = []

        # Identity Lock -- recalcul RÉEL depuis le prompt/les fichiers
        # d'assets tels qu'ils apparaissent DANS CETTE requête, jamais
        # une valeur déclarée (Étape 5). Vérifié EN PREMIER, comme
        # dans GenerationApprovalGate._validate() (Identity -> Replay
        # -> Cost -> Balance -> ...).
        reasons.extend(self.identity_lock.violations(request))

        # Double consentement + replay + coût/budget -- entièrement
        # délégués à GenerationApprovalGate.evaluate(), qui relit lui
        # -même le coût/solde réels à cet instant et applique
        # ALREADY_EXECUTED / EXECUTION_STATE_UNKNOWN sans exception
        # (Étape 4 et Étape 8) : jamais dupliqué ici.
        approval = self.gate.evaluate(request)

        if approval.decision != GenerationApprovalDecision.APPROVED:
            reasons.append(
                f"GenerationApprovalGate decision is "
                f"{approval.decision.value}, not APPROVED. Reasons: "
                f"{'; '.join(approval.reasons) or 'none provided'}"
            )

        return reasons
