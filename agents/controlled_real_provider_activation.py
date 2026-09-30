"""
AI DIRECTOR — Controlled Real-Provider Activation Contract (Phase P2.26,
MASTER PROMPT V2)

Conçoit la DERNIÈRE couche d'autorité, entre "cette requête est
activée" (Phase P2.21, `RequestScopedActivationContract`) et "le
Provider réel pourrait être appelé" -- sans jamais appeler
`create_job()`, ni modifier `HiggsfieldProvider.create_job()`, ni
câbler quoi que ce soit dans `GenerationJobService.execute()`.

STOP -- PORTÉE ABSOLUE DE CE MODULE (Phase P2.26) :
Ce module N'EST PAS câblé dans `GenerationJobService.execute()`.
Exactement comme `agents/activation_contract.py` existait, complet et
testé, PENDANT UNE PHASE ENTIÈRE (P2.21) avant d'être explicitement
câblé (P2.22) -- ce module suit le même schéma délibéré. Le câblage
réel, s'il a lieu, appartient à une phase ULTÉRIEURE, EXPLICITEMENT
autorisée (cf. Étape 17 du rapport P2.26 : "définir précisément ce qui
SERA nécessaire dans une phase ultérieure"). Aucun test de ce fichier
n'invoque `GenerationJobService.execute()` avec ce contrat -- il
n'existe simplement aucune API qui accepterait de le faire aujourd'hui.

FUTUR CHEMIN THÉORIQUE (documenté, JAMAIS activé ici) :

    GenerationJobService
         v
    Final Fresh Gate                              (existant, P2.11-20)
         v
    Validated Human Authorization                 (existant, P2.11)
         v
    Validated RequestScopedActivationContract      (existant, P2.21)
         v
    Validated ControlledRealProviderActivationContract   (CE MODULE)
         v
    Critical Section                              (existant, P2.20)
         v
    HiggsfieldProvider.create_job()                (reste DISABLED)

POURQUOI UNE COUCHE SUPPLÉMENTAIRE, DISTINCTE DE
`RequestScopedActivationContract` :
`RequestScopedActivationContract` répond à « cette requête précise
est-elle éligible à une activation ? ». Ce nouveau contrat répond à
une question DIFFÉRENTE et DÉLIBÉRÉMENT SÉPARÉE : « le PROVIDER
lui-même peut-il être engagé pour CETTE activation précise ? » --
jamais fusionnées (Étape 8, P2.26). Un `RequestScopedActivationContract`
valide ne suffit jamais, seul, à faire exister ce second contrat :
`prepare()` exige explicitement le premier, encore valide, en
paramètre.

PAS DE GLOBAL FLAG (Étape 7/18) : aucune variable booléenne de type
"activation globale" (nommée ou non) n'existe dans ce module. La
question « le provider est-il activable ? » est déterminée UNIQUEMENT
par identité de méthode (`type(provider).create_job is
HiggsfieldProvider.create_job`, jamais en l'appelant) -- exactement le
même mécanisme, jamais dupliqué différemment, que
`agents/activation_readiness.py::_check_provider()`. Contre le
Provider réel, ce contrat NE PEUT JAMAIS être validé avec succès
aujourd'hui -- ce fait est permanent tant qu'une phase future dédiée
ne révise pas explicitement `HiggsfieldProvider.create_job()`
lui-même (ce que ce module ne fait PAS).

RÉVOCATION (Étape 18) : `revoke()` permet de rendre un contrat encore
valide immédiatement inutilisable, sans attendre son expiration --
"refusé par défaut" au sens où l'ABSENCE d'un contrat valide (jamais
préparé, expiré, consommé, ou révoqué) est TOUJOURS l'état de départ,
jamais l'inverse.

OBSERVABILITÉ (Étape 24) : `ControlledRealProviderActivationContract`
et `ControlledRealProviderActivationRejectedError.reasons` exposent
request_id/activation_id/authorization_id/prompt_sha256/asset sha256/
coût attendu/décision -- JAMAIS un secret, un token, ni l'objet
`RealGenerationAuthorization` lui-même (seul `authorization_id`, un
UUID opaque, est conservé -- même règle que Phase P2.21).

MISE À JOUR (Phase B) : `authorization_id` n'est plus seulement une
donnée de traçabilité. `prepare()`/`validate()`/`inspect()` exigent
qu'il soit identique à celui de l'autorisation portée par la requête
ET à celui du contrat P2.21 apparié (cf.
`_authorization_binding_violations()`) ; la Gate exige par ailleurs que
cette autorisation porte les empreintes exactes du contenu.

MISE À JOUR (Phase P2.39) : `avatar_sha256`/`face_reference_sha256`
étaient auparavant qualifiés de "observabilité seulement" ici (jamais
comparés à rien) -- un audit (Phase P2.39) a montré que cela laissait
un contrat forgé (mais partageant un `activation_id` authentique)
passer `validate()`/`inspect()` sans que ces deux champs ne soient
jamais vérifiés contre les fichiers réels de la requête. `_violations()`
les recalcule désormais depuis le DISQUE (comme `prepare()` le fait
déjà) et les compare -- même niveau de garantie que `prompt_sha256`.
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

from agents.activation_contract import RequestScopedActivationContract, RequestScopedActivationService
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
    is_exact_disabled_real_provider,
    is_recognized_test_mock_provider,
)
from agents.generation_cost_service import CostEstimationStatus, is_usable_credit_amount
from agents.release_candidate_identity_lock import ReleaseCandidateIdentityLock
from integrations.higgsfield.provider import HiggsfieldProvider


class ControlledRealProviderActivationRejectedError(RuntimeError):
    """
    Levée par `prepare()` ou `validate()` dès qu'AU MOINS UNE
    condition n'est pas réunie. `reasons` porte la liste complète
    (Étape 19 : aucune situation ambiguë n'est résolue silencieusement).
    """

    def __init__(self, message: str, reasons: List[str]):
        super().__init__(message)
        self.reasons = list(reasons)


@dataclass(frozen=True)
class ControlledRealProviderActivationContract:
    """
    Snapshot éphémère, à usage unique, PRODUIT UNIQUEMENT par
    `ControlledRealProviderActivationService.prepare()`. Ne contient
    aucun secret, aucun token, aucun objet `RealGenerationAuthorization`.

    `request_scoped_activation_id` lie ce contrat à EXACTEMENT le
    `RequestScopedActivationContract` (Phase P2.21) à partir duquel il
    a été préparé -- non transférable à un autre.
    """

    activation_id: str
    request_id: str
    request_scoped_activation_id: str
    job_type: str
    duration: Optional[int]
    resolution: Optional[str]
    aspect_ratio: Optional[str]
    prompt_sha256: str
    avatar_sha256: Optional[str]
    face_reference_sha256: Optional[str]
    expected_cost_credits: Optional[float]
    authorization_id: str
    created_at: str


class ControlledRealProviderActivationService:
    """
    AI DIRECTOR — Controlled Real-Provider Activation Service (Phase P2.26)

    N'appelle JAMAIS `provider.create_job()`. N'importe ni
    `HiggsfieldClient`, ni `subprocess`. Ne connaît rien du verrou de
    section critique (Phase P2.20) : une intégration future pourrait
    entourer un appel à `validate()` avec
    `FileCriticalSectionLock.acquire()`, mais ce module ne le fait pas.
    """

    def __init__(
        self,
        gate: GenerationApprovalGate,
        identity_lock: ReleaseCandidateIdentityLock,
        request_scoped_activation_service: RequestScopedActivationService,
        max_age_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        if identity_lock is None:
            raise ValueError(
                "ControlledRealProviderActivationService requires an "
                "explicit ReleaseCandidateIdentityLock -- mandatory, "
                "never optional here, exactly as for "
                "RequestScopedActivationService (Phase P2.21)."
            )

        self.gate = gate
        self.identity_lock = identity_lock
        self.request_scoped_activation_service = request_scoped_activation_service
        self.max_age_seconds = max_age_seconds
        self._clock = clock
        self._consumed_activation_ids: Set[str] = set()
        self._issued_at: dict = {}

    # ------------------------------------------------------------------
    # PRÉPARATION
    # ------------------------------------------------------------------

    def prepare(
        self,
        request: GenerationRequest,
        request_scoped_contract: RequestScopedActivationContract,
    ) -> ControlledRealProviderActivationContract:
        """
        Crée le contrat SI ET SEULEMENT SI le `RequestScopedActivation
        Contract` fourni est ACTUELLEMENT valide (inspection NON
        MUTANTE -- Phase P2.24 -- il n'est jamais consommé ici) ET que
        toutes les vérifications fraîches passent.
        """

        reasons = self._fresh_violations(request, request_scoped_contract)

        # Phase B : ce contrat reprendra l'`authorization_id` de la
        # requête -- le contrat P2.21 fourni doit porter le même, sinon
        # la paire serait incohérente dès sa création.
        auth = request.real_generation_authorization
        if isinstance(auth, RealGenerationAuthorization):
            reasons.extend(
                _authorization_binding_violations(
                    request, request_scoped_contract, auth.authorization_id
                )
            )

        if reasons:
            raise ControlledRealProviderActivationRejectedError(
                f"Cannot prepare a controlled real-provider activation "
                f"contract for request '{request.request_id}': not "
                f"currently eligible.",
                reasons,
            )

        auth = request.real_generation_authorization
        if (
            auth is None
            or not isinstance(auth, RealGenerationAuthorization)
            or auth.request_id != request.request_id
        ):
            # Défense en profondeur : `_fresh_violations` l'exige déjà
            # via le Gate, mais on ne fait jamais confiance
            # implicitement à cette invariance (même logique que
            # Phase P2.23/P2.21). `not isinstance(...)` ajouté Phase
            # P2.38 (audit finding) -- même correction que
            # `agents/activation_contract.py::prepare_activation()` :
            # un objet malformé lève désormais un rejet proprement
            # typé plutôt qu'un `AttributeError` non intentionnel
            # (jamais un gap de sécurité -- les deux échouaient déjà
            # fermé -- mais une incohérence de type d'exception).
            raise ControlledRealProviderActivationRejectedError(
                f"Cannot prepare contract for request "
                f"'{request.request_id}': no valid human authorization "
                f"bound to this exact request.",
                ["real_generation_authorization is missing or not bound "
                 "to this exact request_id."],
            )

        cost_result = self.gate.cost_service.estimate(
            job_type=request.job_type,
            prompt=request.prompt,
            duration=request.duration,
            resolution=request.resolution,
            aspect_ratio=request.aspect_ratio,
        )
        expected_cost = (
            cost_result.estimate.credits
            if cost_result.estimate is not None
            else None
        )

        cost_reasons = self._expected_cost_violations(expected_cost)
        if cost_result.status != CostEstimationStatus.KNOWN:
            cost_reasons.append(
                f"Cost estimate status is {cost_result.status.value}, not "
                f"known -- a contract is never prepared for an unknown cost."
            )
        if cost_reasons:
            raise ControlledRealProviderActivationRejectedError(
                f"Cannot prepare contract for request "
                f"'{request.request_id}': expected cost is not authorized.",
                cost_reasons,
            )

        avatar_sha256 = _sha256_of_file_or_none(
            request.start_image.source if request.start_image else None
        )
        face_reference_sha256 = None
        for ref in request.image_references:
            if ref.role == "face_reference":
                face_reference_sha256 = _sha256_of_file_or_none(ref.source)
                break

        contract = ControlledRealProviderActivationContract(
            activation_id=uuid.uuid4().hex,
            request_id=request.request_id,
            request_scoped_activation_id=request_scoped_contract.activation_id,
            job_type=request.job_type,
            duration=request.duration,
            resolution=request.resolution,
            aspect_ratio=request.aspect_ratio,
            prompt_sha256=hashlib.sha256(request.prompt.encode("utf-8")).hexdigest(),
            avatar_sha256=avatar_sha256,
            face_reference_sha256=face_reference_sha256,
            expected_cost_credits=expected_cost,
            authorization_id=auth.authorization_id,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        self._issued_at[contract.activation_id] = self._clock()

        return contract

    # ------------------------------------------------------------------
    # VALIDATION -- immédiatement avant une future activation réelle.
    # ------------------------------------------------------------------

    def validate(
        self,
        request: GenerationRequest,
        request_scoped_contract: RequestScopedActivationContract,
        provider_contract: ControlledRealProviderActivationContract,
    ) -> ControlledRealProviderActivationContract:
        reasons = self._violations(request, request_scoped_contract, provider_contract)

        if reasons:
            raise ControlledRealProviderActivationRejectedError(
                f"Cannot validate controlled real-provider activation "
                f"contract '{provider_contract.activation_id}' for "
                f"request '{request.request_id}'.",
                reasons,
            )

        self._consumed_activation_ids.add(provider_contract.activation_id)

        return provider_contract

    def inspect(
        self,
        request: GenerationRequest,
        request_scoped_contract: RequestScopedActivationContract,
        provider_contract: ControlledRealProviderActivationContract,
    ) -> List[str]:
        """
        Phase P2.36 — variante NON MUTANTE de `validate()`, exactement
        le même principe que `RequestScopedActivationService.inspect_
        activation()` (Phase P2.24) pour le contrat P2.21 : renvoie
        EXACTEMENT les mêmes raisons de refus que `validate()`
        obtiendrait (liste vide == le contrat validerait actuellement),
        SANS jamais consommer `provider_contract` ni lever d'exception.
        Réservée aux lectures de type "readiness"/"execution gate" (cf.
        agents/real_provider_execution_gate.py) : un contrat réel à
        usage unique ne doit JAMAIS être brûlé par une simple
        inspection. N'est JAMAIS un substitut à `validate()`
        immédiatement avant une future activation réelle -- celle-ci
        DOIT continuer à consommer le contrat.
        """

        return self._violations(request, request_scoped_contract, provider_contract)

    def _violations(
        self,
        request: GenerationRequest,
        request_scoped_contract: RequestScopedActivationContract,
        provider_contract: ControlledRealProviderActivationContract,
    ) -> List[str]:
        """Logique de vérification partagée, PURE (aucun effet de bord)
        entre `validate()` (qui consomme ensuite le contrat si cette
        liste est vide) et `inspect()` (Phase P2.36, qui ne consomme
        jamais rien) -- même principe que `RequestScopedActivation
        Service._activation_violations()` (Phase P2.21/P2.24)."""

        reasons: List[str] = []

        if provider_contract.request_id != request.request_id:
            reasons.append(
                f"Controlled real-provider activation contract is bound "
                f"to request '{provider_contract.request_id}', not to "
                f"this request '{request.request_id}'."
            )

        reasons.extend(
            _authorization_binding_violations(
                request, request_scoped_contract, provider_contract.authorization_id
            )
        )

        if provider_contract.request_scoped_activation_id != request_scoped_contract.activation_id:
            reasons.append(
                f"Controlled real-provider activation contract is bound "
                f"to request-scoped activation "
                f"'{provider_contract.request_scoped_activation_id}', "
                f"not to the one supplied "
                f"('{request_scoped_contract.activation_id}') -- not "
                f"transferable between activations."
            )

        issued_at = self._issued_at.get(provider_contract.activation_id)

        if issued_at is None:
            reasons.append(
                f"Contract '{provider_contract.activation_id}' was not "
                f"issued by this service instance (or was already "
                f"consumed/revoked and forgotten) -- refusing to trust "
                f"a contract this instance cannot vouch for."
            )
        elif provider_contract.activation_id in self._consumed_activation_ids:
            reasons.append(
                f"Contract '{provider_contract.activation_id}' has "
                f"already been consumed or revoked -- single-use, never "
                f"reusable."
            )
        elif self._clock() - issued_at > self.max_age_seconds:
            reasons.append(
                f"Contract '{provider_contract.activation_id}' has "
                f"expired ({self.max_age_seconds}s max age)."
            )

        actual_prompt_sha256 = hashlib.sha256(
            request.prompt.encode("utf-8") if isinstance(request.prompt, str) else b""
        ).hexdigest()
        if actual_prompt_sha256 != provider_contract.prompt_sha256:
            reasons.append(
                f"Contract prompt sha256 '{provider_contract.prompt_sha256}' "
                f"does not match this request's current prompt sha256 "
                f"'{actual_prompt_sha256}' -- the request changed since "
                f"the contract was prepared."
            )

        # Phase P2.38 audit finding : AVANT cette phase, ni validate()
        # ni inspect() ne comparaient JAMAIS job_type/duration/
        # resolution/aspect_ratio du CONTRAT à la requête -- seul
        # prompt_sha256 l'était explicitement ici. Un contrat forgé à
        # la main (même activation_id qu'un contrat réellement émis
        # par cette instance -- donc capable de passer les vérifications
        # issued_at/consumed/expired ci-dessus -- mais avec un
        # job_type/duration/resolution/aspect_ratio différent) pouvait
        # donc valider à cette couche. Ce n'était PAS exploitable
        # jusqu'au vrai Provider (integrations/higgsfield/provider.py,
        # Phase P2.35, vérifie indépendamment ces mêmes champs contre
        # les valeurs live transmises à create_job() et aurait refusé
        # quand même), mais affaiblissait la défense en profondeur que
        # ce module prétend offrir. Corrigé ici pour que CETTE couche,
        # comme toutes les autres, ne fasse jamais confiance à un champ
        # du contrat sans le revérifier contre la requête réelle.
        if provider_contract.job_type != request.job_type:
            reasons.append(
                f"Contract job_type '{provider_contract.job_type}' does "
                f"not match this request's current job_type "
                f"'{request.job_type}'."
            )

        if provider_contract.duration != request.duration:
            reasons.append(
                f"Contract duration {provider_contract.duration!r} does "
                f"not match this request's current duration "
                f"{request.duration!r}."
            )

        if provider_contract.resolution != request.resolution:
            reasons.append(
                f"Contract resolution {provider_contract.resolution!r} "
                f"does not match this request's current resolution "
                f"{request.resolution!r}."
            )

        if provider_contract.aspect_ratio != request.aspect_ratio:
            reasons.append(
                f"Contract aspect_ratio {provider_contract.aspect_ratio!r} "
                f"does not match this request's current aspect_ratio "
                f"{request.aspect_ratio!r}."
            )

        # Phase P2.39 audit finding (même famille que le finding P2.38
        # ci-dessus) : `avatar_sha256`/`face_reference_sha256` étaient
        # documentés "OBSERVABILITÉ SEULEMENT" (Étape 24, docstring de
        # `ControlledRealProviderActivationContract`) au motif que
        # l'Identity Lock (via `_fresh_violations()` juste en dessous)
        # recalcule déjà le SHA-256 des fichiers RÉELS référencés par
        # la requête contre les valeurs CANONIQUES fixes -- mais cela
        # ne vérifie JAMAIS que les champs `avatar_sha256`/
        # `face_reference_sha256` PORTÉS PAR LE CONTRAT correspondent à
        # ces mêmes fichiers réels. Un contrat forgé à la main partageant
        # un `activation_id` authentique (donc capable de passer les
        # vérifications issued_at/consumed/expired) mais avec des champs
        # avatar/face divergents passait donc cette couche -- exactement
        # la même classe de lacune que job_type/duration/resolution/
        # aspect_ratio (Phase P2.38), non détectée à l'époque car ces
        # deux champs sont recalculés depuis le DISQUE plutôt que copiés
        # depuis la requête. Toujours non exploitable jusqu'au vrai
        # Provider (l'Identity Lock, appelé juste après, bloque déjà
        # toute requête dont les fichiers réels ne correspondent pas au
        # canon -- mais ne compare jamais le CONTRAT aux fichiers).
        # Corrigé ici pour une cohérence complète : ce contrat ne doit
        # plus jamais contenir un champ non vérifié contre la réalité.
        actual_avatar_sha256 = _sha256_of_file_or_none(
            request.start_image.source if request.start_image else None
        )
        if provider_contract.avatar_sha256 != actual_avatar_sha256:
            reasons.append(
                f"Contract avatar_sha256 {provider_contract.avatar_sha256!r} "
                f"does not match this request's current live avatar file "
                f"sha256 {actual_avatar_sha256!r}."
            )

        actual_face_reference_sha256 = None
        for ref in request.image_references:
            if ref.role == "face_reference":
                actual_face_reference_sha256 = _sha256_of_file_or_none(ref.source)
                break
        if provider_contract.face_reference_sha256 != actual_face_reference_sha256:
            reasons.append(
                f"Contract face_reference_sha256 "
                f"{provider_contract.face_reference_sha256!r} does not "
                f"match this request's current live face-reference file "
                f"sha256 {actual_face_reference_sha256!r}."
            )

        # Le RequestScopedActivationContract sous-jacent doit LUI AUSSI
        # être actuellement valide -- inspection NON MUTANTE (Phase
        # P2.24) : ce module ne consomme jamais le contrat P2.21 (sa
        # consommation réelle, si elle a lieu un jour, restera de la
        # responsabilité de GenerationJobService.execute(), Phase P2.22,
        # jamais dupliquée ici).
        reasons.extend(
            self.request_scoped_activation_service.inspect_activation(
                request, request_scoped_contract
            )
        )

        reasons.extend(self._fresh_violations(request, request_scoped_contract))

        # Phase D : `expected_cost_credits` n'est plus seulement observé.
        # Il doit rester sous le plafond configuré ET correspondre au coût
        # que la Gate évalue à cet instant -- sinon le coût a changé
        # depuis `prepare()` et le contrat ne couvre plus ce qui serait
        # exécuté.
        reasons.extend(self._expected_cost_violations(provider_contract.expected_cost_credits))
        fresh_cost = self.gate.cost_service.estimate(
            job_type=request.job_type,
            prompt=request.prompt,
            duration=request.duration,
            resolution=request.resolution,
            aspect_ratio=request.aspect_ratio,
        )
        fresh_credits = fresh_cost.estimate.credits if fresh_cost.estimate is not None else None
        if (
            fresh_cost.status != CostEstimationStatus.KNOWN
            or not is_usable_credit_amount(fresh_credits)
            or fresh_credits != provider_contract.expected_cost_credits
        ):
            reasons.append(
                f"Contract expected_cost_credits "
                f"{provider_contract.expected_cost_credits!r} does not match "
                f"the cost currently authorized by the Gate "
                f"({fresh_cost.status.value}, {fresh_credits!r})."
            )

        return reasons

    def _expected_cost_violations(self, expected_cost: Optional[float]) -> List[str]:
        """Phase D — le coût attendu doit être un montant exploitable et ne
        jamais dépasser le plafond par requête configuré sur la Gate.
        Pour tout Provider autre qu'un mock de test reconnu
        (`GenerationApprovalGate.requires_real_path_protections()`), un
        plafond absent ou inexploitable est lui-même un refus (jamais
        « sans limite ») ; pour un mock reconnu sans plafond, aucune
        limite n'est appliquée ici. Le Provider réel reste de toute façon refusé par
        l'identité de méthode de `_fresh_violations()` et par son
        `raise` inconditionnel."""

        reasons: List[str] = []
        ceiling = self.gate.max_cost_credits_per_request

        if ceiling is not None and not is_usable_credit_amount(ceiling):
            reasons.append(
                f"Configured per-request ceiling {ceiling!r} is not a "
                f"finite, non-negative number of credits."
            )
        elif ceiling is None and self.gate.requires_real_path_protections():
            reasons.append(
                "Real or unrecognized provider path: no explicitly configured "
                "per-request credit ceiling; expected cost cannot be "
                "authorized."
            )

        if not is_usable_credit_amount(expected_cost):
            reasons.append(
                f"Expected cost {expected_cost!r} is not a finite, "
                f"non-negative number of credits."
            )
        elif is_usable_credit_amount(ceiling) and expected_cost > ceiling:
            reasons.append(
                f"Expected cost {expected_cost} exceeds the configured "
                f"per-request ceiling of {ceiling} credits."
            )

        return reasons

    # ------------------------------------------------------------------
    # RÉVOCATION (Étape 18) -- rend un contrat encore valide
    # immédiatement inutilisable, sans attendre son expiration.
    # ------------------------------------------------------------------

    def revoke(self, contract: ControlledRealProviderActivationContract) -> None:
        self._consumed_activation_ids.add(contract.activation_id)

    # ------------------------------------------------------------------
    # VÉRIFICATIONS FRAÎCHES -- jamais mises en cache entre prepare()
    # et validate().
    # ------------------------------------------------------------------

    def _fresh_violations(
        self,
        request: GenerationRequest,
        request_scoped_contract: RequestScopedActivationContract,
    ) -> List[str]:
        reasons: List[str] = []

        # Identity Lock -- recalcul RÉEL, jamais une valeur déclarée.
        reasons.extend(self.identity_lock.violations(request))

        # Gate -- re-lit coût/solde/replay/UNKNOWN à cet instant précis.
        approval = self.gate.evaluate(request)
        if approval.decision != GenerationApprovalDecision.APPROVED:
            reasons.append(
                f"GenerationApprovalGate decision is "
                f"{approval.decision.value}, not APPROVED. Reasons: "
                f"{'; '.join(approval.reasons) or 'none provided'}"
            )

        # Provider Activation Boundary (Étape 5/17/18) -- JAMAIS un
        # booléen global : identité de méthode contre le VRAI Provider
        # désactivé, jamais déterminé en l'appelant.
        provider = self.gate.provider
        if not (
            is_recognized_test_mock_provider(provider)
            or is_exact_disabled_real_provider(provider)
        ):
            # Phase D : une sous-classe du vrai Provider (create_job
            # redéfini), un wrapper ou un Provider inconnu échapperait à
            # l'identité de méthode ci-dessous -- il ne peut pas pour
            # autant remplacer ce verrou. Vérifié EN PREMIER : ce test ne
            # lève jamais, même pour un objet sans `create_job` de classe.
            reasons.append(
                f"provider {type(provider).__name__} is neither the real "
                f"HiggsfieldProvider nor a recognized test mock -- a "
                f"subclass, wrapper or unknown provider can never "
                f"validate the provider activation boundary."
            )
        elif type(provider).create_job is HiggsfieldProvider.create_job:
            reasons.append(
                "provider is the real HiggsfieldProvider, whose "
                "create_job() unconditionally raises "
                "HiggsfieldRealGenerationDisabledError by design -- "
                "provider activation cannot be validated while this "
                "remains true (never probed by actually calling "
                "create_job())."
            )

        return reasons


def _authorization_binding_violations(
    request: GenerationRequest,
    request_scoped_contract: RequestScopedActivationContract,
    provider_authorization_id: Optional[str],
) -> List[str]:
    """Phase B — `provider_authorization_id` (contrat P2.26) doit être
    EXACTEMENT l'`authorization_id` de l'autorisation portée par la
    requête ET celui du contrat P2.21 apparié : ni transférable à une
    autre autorisation, ni combinable avec un contrat P2.21 préparé
    sous une autre autorisation."""

    reasons: List[str] = []
    auth = request.real_generation_authorization
    request_authorization_id = (
        auth.authorization_id if isinstance(auth, RealGenerationAuthorization) else None
    )

    if request_authorization_id is None or provider_authorization_id != request_authorization_id:
        reasons.append(
            f"Controlled real-provider activation contract is bound to "
            f"authorization {provider_authorization_id!r}, not to this "
            f"request's authorization {request_authorization_id!r} -- not "
            f"transferable between authorizations."
        )

    if request_scoped_contract.authorization_id != provider_authorization_id:
        reasons.append(
            f"Request-scoped activation contract authorization "
            f"'{request_scoped_contract.authorization_id}' and controlled "
            f"real-provider activation contract authorization "
            f"{provider_authorization_id!r} differ -- the contract pair was "
            f"not prepared under one single authorization."
        )

    return reasons


def _sha256_of_file_or_none(path: Optional[str]) -> Optional[str]:
    """Recalcule le SHA-256 depuis le FICHIER RÉEL, jamais une valeur
    déclarée. `None` si le fichier est absent/illisible ou si `path`
    est `None` -- jamais une exception, jamais une valeur inventée
    (même logique que `agents/release_candidate_identity_lock.py::
    _sha256_of_file`, délibérément dupliquée ici en 8 lignes pour ne
    pas coupler ce module à une fonction privée d'un autre module)."""

    if path is None:
        return None

    try:
        sha256 = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except OSError:
        return None
