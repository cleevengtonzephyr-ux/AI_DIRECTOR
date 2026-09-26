"""
AI DIRECTOR — Higgsfield Provider (Phase B/C/D, MASTER PROMPT V2)

Le Provider masque la complexité du CLI Higgsfield derrière un contrat
stable (BaseHiggsfieldProvider), afin que les futurs composants
(VideoAgent, GenerationJobService, etc. — priorités suivantes de la
roadmap) ne dépendent jamais directement de HiggsfieldClient ni de la
forme exacte des commandes CLI.

Deux implémentations partagent ce contrat :
- HiggsfieldProvider      : implémentation réelle, appuyée sur
                            HiggsfieldClient (integrations/higgsfield/client.py).
- MockHiggsfieldProvider  : implémentation 100% simulée, utilisée par
                            les tests (voir mock_provider.py).

SÉCURITÉ (Phase B/C/D) :
HiggsfieldProvider.create_job() est VOLONTAIREMENT désactivée dans
cette phase : elle lève HiggsfieldRealGenerationDisabledError au lieu
d'appeler le CLI, quelle que soit la manière dont elle est invoquée.
Aucun test, aucun script de cette phase ne peut donc déclencher une
génération réelle facturable via cette classe.

INTERFACE D'ACTIVATION (Phase P2.32) : `create_job()` accepte
désormais un paramètre optionnel `provider_activation_contract`
(par défaut `None`) afin qu'une future phase explicitement autorisée
puisse lui transmettre un `ControlledRealProviderActivationContract`
(Phase P2.26, agents/controlled_real_provider_activation.py) déjà
validé.

CONTROLLED REAL-PROVIDER ACTIVATION BOUNDARY (Phase P2.35) :
`create_job()` INSPECTE désormais réellement `provider_activation_
contract` -- ce n'était pas le cas avant P2.35, où ce paramètre
n'était accepté que pour exister dans la signature (P2.32) sans
jamais être lu. Le Provider vérifie maintenant, structurellement,
AVANT toute conclusion :
- que le contrat existe et est bien une instance de
  `ControlledRealProviderActivationContract` (import différé, cf.
  `_provider_activation_violations()` ci-dessous, pour éviter un
  import circulaire réel avec agents/controlled_real_provider_
  activation.py, qui importe déjà `HiggsfieldProvider` depuis ce
  module) ;
- que `request_id`/`job_type`/`duration`/`resolution`/`aspect_ratio`
  du contrat correspondent EXACTEMENT aux valeurs LIVE effectivement
  soumises à CET appel précis (jamais une valeur mise en cache) ;
- que le SHA-256 du prompt LIVE, recalculé ici, correspond au
  `prompt_sha256` du contrat ;
- que `avatar_sha256`/`face_reference_sha256` (nouveaux paramètres
  explicites, calculés par l'appelant -- `GenerationJobService` --
  depuis les fichiers RÉELS de la requête, jamais recalculés ici
  depuis un chemin de fichier que ce Provider n'a pas) correspondent
  à ceux du contrat ;
- que `authorization_id`/`request_scoped_activation_id` sont
  présents (traçabilité minimale, jamais une preuve d'autorité en
  eux-mêmes) ;
- une vérification de fraîcheur PUREMENT LOCALE AU PROVIDER, basée
  UNIQUEMENT sur `contract.created_at` et une horloge injectable
  (`clock`, par défaut `datetime.now(timezone.utc)`) comparée à
  `self.max_age_seconds` (300s par défaut, alignée mais
  INDÉPENDANTE du service P2.26).

CE QUE CETTE VÉRIFICATION N'EST PAS (Étape 3, P2.35 -- "le Provider
ne doit pas dupliquer l'autorité") : elle ne re-implémente NI ne
remplace l'enregistrement de consommation/révocation/expiration
AUTHORITATIF, qui reste EXCLUSIVEMENT la responsabilité de
`ControlledRealProviderActivationService.validate()`
(agents/controlled_real_provider_activation.py) -- déjà appelée par
`GenerationJobService.execute()` IMMÉDIATEMENT avant `create_job()`,
DANS le même verrou de section critique, sans aucun écart temporel.
Un état "consommé"/"révoqué" ne peut PAS être redétecté ici : ce
Provider ne détient (et ne doit jamais détenir, cf. Phase 3 du
rapport P2.35) aucune référence à ce service, et une bookkeeping
locale par instance serait de toute façon TROMPEUSE (elle ne
survivrait pas à la reconstruction du Provider) -- documenté
explicitement plutôt que simulé.

VERROU FINAL, INCONDITIONNEL (Étape 9, P2.35 -- "le point le plus
important") : que la liste de violations structurelles ci-dessus soit
VIDE ou non, `create_job()` lève TOUJOURS
`HiggsfieldRealGenerationDisabledError` et n'appelle JAMAIS
`self.client.create_job()` ni aucune autre méthode de `self.client`.
Une activation structurellement valide prouve seulement que la
CHAÎNE D'AUTORITÉ est cohérente jusqu'à cette frontière -- elle ne
prouve jamais, et ne doit jamais impliquer, qu'un appel réel est
autorisé. Cette dernière transition reste fermée par une phase
FUTURE, explicitement autorisée, qui devra modifier cette méthode
elle-même.

MODÈLE (Phase D) :
Aucune méthode de ce Provider n'est couplée à un job_type particulier
(ex. seedance_2_0) : `job_type` est toujours un paramètre d'appel. Le
choix du modèle par défaut appartient à une couche supérieure (future
VideoAgent/CostService), pas au Provider.

RÉPONSES INVALIDES (Phase D) :
Toute réponse CLI dont la forme ne correspond pas à ce qui est attendu
(objet vs liste, champ manquant) déclenche explicitement
HiggsfieldInvalidResponseError (réutilisée depuis la Phase B, aucune
nouvelle classe d'erreur créée) plutôt que de lever une exception
générique (AttributeError, KeyError) plus loin dans le code appelant.
"""

import hashlib
import sys
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from integrations.higgsfield.client import HiggsfieldClient

if TYPE_CHECKING:
    # Phase P2.32 — type-checking-only import: agents.controlled_real_
    # provider_activation already imports HiggsfieldProvider from this
    # module, so a real (runtime) import here would be circular. This
    # guarded import exists SOLELY so create_job()'s new optional
    # parameter (see below) can carry a real type hint instead of
    # `Any` — it has zero effect at runtime and is never evaluated.
    from agents.controlled_real_provider_activation import (
        ControlledRealProviderActivationContract,
    )
from integrations.higgsfield.errors import (
    HiggsfieldInvalidResponseError,
    HiggsfieldRealGenerationDisabledError,
)
from integrations.higgsfield.types import (
    CostEstimate,
    Job,
    JobStatus,
    ModelParam,
    ModelSchema,
    VideoResult,
)


class BaseHiggsfieldProvider(ABC):
    """Contrat commun à toute implémentation Higgsfield (réelle ou mock)."""

    @abstractmethod
    def list_models(self, video: bool = True) -> List[ModelSchema]:
        ...

    @abstractmethod
    def get_model(self, job_type: str) -> ModelSchema:
        ...

    @abstractmethod
    def estimate_cost(
        self,
        job_type: str,
        prompt: str,
        duration: Optional[int] = None,
        resolution: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
    ) -> CostEstimate:
        ...

    @abstractmethod
    def get_account_balance(self) -> Optional[float]:
        """
        Retourne le solde de crédits disponible, ou None si le Provider
        ne peut pas le déterminer (jamais une valeur inventée).
        Nécessaire à GenerationApprovalGate (Phase G) pour vérifier le
        budget sans jamais appeler HiggsfieldClient directement.
        """
        ...

    @abstractmethod
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
        `provider_activation_contract` (Phase P2.32, optional, default
        `None`) — the request-scoped, single-use, expiring Controlled
        Real-Provider Activation Contract (Phase P2.26,
        agents/controlled_real_provider_activation.py) a caller MAY
        supply so that a future authorized phase can thread the full
        authority chain (Human Authorization -> P2.21 -> P2.26) all
        the way to this exact boundary.

        `request_id`/`avatar_sha256`/`face_reference_sha256` (Phase
        P2.35, optional, default `None`) — LIVE ground-truth values for
        THIS exact call, computed by the caller (`GenerationJobService`)
        from the actual `GenerationRequest` being executed, never
        cached or reused across calls. A concrete implementation MAY
        compare these against the fields carried by
        `provider_activation_contract` as an additional, independent
        binding check -- this parameter set exists to make that
        comparison POSSIBLE without granting the Provider access to the
        original `GenerationRequest`, `RealGenerationAuthorization`, or
        any activation service instance (which it must never hold, cf.
        agents/controlled_real_provider_activation.py module docstring,
        "Ne connaît rien du verrou de section critique").

        This parameter set exists ONLY to define a safe, typed,
        request-scoped INTERFACE between that contract and the
        Provider -- it carries no enforcement duty by itself. Whether
        and how a concrete implementation honors it is entirely up to
        that implementation: `HiggsfieldProvider` (the real
        implementation, provider.py below) now performs real
        structural validation of these values (Phase P2.35) but still
        UNCONDITIONALLY refuses real generation regardless of the
        outcome -- see its own docstring/module docstring for why.
        """
        ...

    @abstractmethod
    def get_job(self, job_id: str) -> Job:
        ...

    @abstractmethod
    def wait_for_job(
        self,
        job_id: str,
        timeout_seconds: float = 600,
        interval_seconds: float = 3,
    ) -> VideoResult:
        ...


# ============================================================
# Parsing helpers — traduisent le JSON brut du CLI vers les types
# de integrations/higgsfield/types.py
#
# Chaque helper valide la FORME de la réponse avant de la parser : une
# réponse CLI qui ne serait pas un dict/list (JSON valide mais mal
# formé pour l'usage attendu — ex. un booléen, une chaîne, une liste
# là où un objet est attendu) déclenche explicitement
# HiggsfieldInvalidResponseError plutôt qu'un AttributeError non
# maîtrisé plus loin dans le code appelant.
# ============================================================

def _ensure_dict(raw: Any, context: str) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise HiggsfieldInvalidResponseError(
            f"Higgsfield CLI returned an unexpected response shape for "
            f"{context}: expected an object, got {type(raw).__name__}."
        )

    return raw


def _ensure_list(raw: Any, context: str) -> List[Any]:
    if not isinstance(raw, list):
        raise HiggsfieldInvalidResponseError(
            f"Higgsfield CLI returned an unexpected response shape for "
            f"{context}: expected a list, got {type(raw).__name__}."
        )

    return raw


def _parse_model_schema(job_type: str, raw: Dict[str, Any]) -> ModelSchema:
    params = tuple(
        ModelParam(
            name=item.get("name"),
            type=item.get("type", "string"),
            required=bool(item.get("required", False)),
            default=item.get("default"),
            enum=tuple(item.get("enum") or []),
        )
        for item in raw.get("params", [])
        if isinstance(item, dict)
    )

    return ModelSchema(
        job_type=raw.get("job_type", job_type),
        display_name=raw.get("display_name", job_type),
        params=params,
        raw=raw,
    )


def _parse_job_status(raw_status: Optional[str]) -> JobStatus:
    if not raw_status:
        return JobStatus.UNKNOWN

    try:
        return JobStatus(str(raw_status).lower())
    except ValueError:
        return JobStatus.UNKNOWN


def _parse_job(raw: Dict[str, Any]) -> Job:
    return Job(
        job_id=raw.get("id") or raw.get("job_id", ""),
        job_type=raw.get("job_type", ""),
        status=_parse_job_status(raw.get("status")),
        raw=raw,
    )


def _parse_video_result(raw: Dict[str, Any]) -> VideoResult:
    outputs = raw.get("outputs") or raw.get("results") or []

    urls = tuple(
        item.get("url")
        for item in outputs
        if isinstance(item, dict) and item.get("url")
    ) if isinstance(outputs, list) else tuple()

    return VideoResult(
        job_id=raw.get("id") or raw.get("job_id", ""),
        status=_parse_job_status(raw.get("status")),
        output_urls=urls,
        raw=raw,
    )


# ============================================================
# CONTROLLED REAL-PROVIDER ACTIVATION BOUNDARY (Phase P2.35)
#
# Fonction PURE (aucun effet de bord, aucun appel réseau/CLI) --
# structurellement identique dans l'esprit à `_activation_violations()`
# / `_fresh_violations()` déjà utilisées par
# agents/activation_contract.py et
# agents/controlled_real_provider_activation.py : une liste vide
# signifie "structurellement cohérent", jamais "autorisé à exécuter".
# ============================================================

def _provider_activation_violations(
    job_type: str,
    prompt: str,
    duration: Optional[Any],
    resolution: Optional[Any],
    aspect_ratio: Optional[Any],
    request_id: Optional[str],
    avatar_sha256: Optional[str],
    face_reference_sha256: Optional[str],
    provider_activation_contract: Optional[Any],
    max_age_seconds: float,
    now: datetime,
) -> List[str]:
    reasons: List[str] = []

    if provider_activation_contract is None:
        reasons.append(
            "no provider_activation_contract was supplied -- a request-"
            "scoped activation boundary requires an explicit contract, "
            "never inferred or defaulted."
        )
        return reasons

    # Import différé (jamais au niveau module) : agents/controlled_real_
    # provider_activation.py importe déjà HiggsfieldProvider depuis CE
    # module -- un import de niveau module ici créerait un import
    # circulaire réel. Au moment où create_job() peut effectivement être
    # appelée, les deux modules sont déjà entièrement chargés : cet
    # import différé est donc sûr et ne fait qu'exécuter un lookup dans
    # le cache d'imports de Python (sys.modules), jamais un rechargement.
    from agents.controlled_real_provider_activation import (
        ControlledRealProviderActivationContract,
    )

    if not isinstance(provider_activation_contract, ControlledRealProviderActivationContract):
        reasons.append(
            f"provider_activation_contract is not a "
            f"ControlledRealProviderActivationContract instance (got "
            f"{type(provider_activation_contract).__name__}) -- refusing "
            f"to trust an object of the wrong type as an activation "
            f"boundary."
        )
        return reasons

    contract = provider_activation_contract

    if not request_id:
        reasons.append(
            "no request_id was supplied to create_job() for this call -- "
            "a missing/empty request_id can never satisfy a request-"
            "scoped activation boundary (no wildcard is ever accepted)."
        )
    elif contract.request_id != request_id:
        reasons.append(
            f"provider_activation_contract is bound to request "
            f"'{contract.request_id}', not to this call's request_id "
            f"'{request_id}'."
        )

    if contract.job_type != job_type:
        reasons.append(
            f"provider_activation_contract job_type '{contract.job_type}' "
            f"does not match this call's job_type '{job_type}'."
        )

    if contract.duration != duration:
        reasons.append(
            f"provider_activation_contract duration {contract.duration!r} "
            f"does not match this call's live duration {duration!r}."
        )

    if contract.resolution != resolution:
        reasons.append(
            f"provider_activation_contract resolution "
            f"{contract.resolution!r} does not match this call's live "
            f"resolution {resolution!r}."
        )

    if contract.aspect_ratio != aspect_ratio:
        reasons.append(
            f"provider_activation_contract aspect_ratio "
            f"{contract.aspect_ratio!r} does not match this call's live "
            f"aspect_ratio {aspect_ratio!r}."
        )

    actual_prompt_sha256 = hashlib.sha256(
        prompt.encode("utf-8") if isinstance(prompt, str) else b""
    ).hexdigest()
    if actual_prompt_sha256 != contract.prompt_sha256:
        reasons.append(
            f"provider_activation_contract prompt sha256 "
            f"'{contract.prompt_sha256}' does not match this call's live "
            f"prompt sha256 '{actual_prompt_sha256}'."
        )

    if not avatar_sha256 or contract.avatar_sha256 != avatar_sha256:
        reasons.append(
            f"provider_activation_contract avatar_sha256 "
            f"{contract.avatar_sha256!r} does not match this call's live "
            f"avatar_sha256 {avatar_sha256!r}."
        )

    if not face_reference_sha256 or contract.face_reference_sha256 != face_reference_sha256:
        reasons.append(
            f"provider_activation_contract face_reference_sha256 "
            f"{contract.face_reference_sha256!r} does not match this "
            f"call's live face_reference_sha256 {face_reference_sha256!r}."
        )

    if not contract.authorization_id:
        reasons.append("provider_activation_contract.authorization_id is missing/empty.")

    if not contract.request_scoped_activation_id:
        reasons.append(
            "provider_activation_contract.request_scoped_activation_id "
            "is missing/empty."
        )

    # Vérification de fraîcheur PUREMENT LOCALE au Provider -- PAS
    # l'enregistrement authoritatif d'expiration/consommation/révocation
    # (qui reste exclusivement la responsabilité de
    # ControlledRealProviderActivationService.validate(), cf. docstring
    # de module ci-dessus). Basée UNIQUEMENT sur le champ `created_at`
    # déjà porté par le contrat, jamais sur un état mutable externe.
    try:
        created_at = datetime.fromisoformat(contract.created_at)
    except (TypeError, ValueError):
        reasons.append(
            f"provider_activation_contract.created_at "
            f"{contract.created_at!r} is not a valid ISO-8601 timestamp."
        )
    else:
        age_seconds = (now - created_at).total_seconds()
        if age_seconds > max_age_seconds or age_seconds < 0:
            reasons.append(
                f"provider_activation_contract age ({age_seconds:.1f}s) "
                f"exceeds this Provider's own freshness sanity threshold "
                f"({max_age_seconds}s), or is negative (clock "
                f"inconsistency) -- refusing to trust a stale contract."
            )

    return reasons


class HiggsfieldProvider(BaseHiggsfieldProvider):
    """Implémentation réelle du Provider, appuyée sur HiggsfieldClient."""

    def __init__(
        self,
        client: Optional[HiggsfieldClient] = None,
        max_age_seconds: float = 300.0,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        """
        `max_age_seconds`/`clock` (Phase P2.35, optional) : paramètres
        du garde-fou de fraîcheur PUREMENT LOCAL AU PROVIDER décrit dans
        le docstring de module -- `clock` est injectable pour permettre
        des tests totalement déterministes (jamais dépendant du temps
        réel écoulé), exactement le même principe que `agents/
        activation_contract.py::RequestScopedActivationService` et
        `agents/controlled_real_provider_activation.py::
        ControlledRealProviderActivationService`.
        """

        self.client = client or HiggsfieldClient()
        self.max_age_seconds = max_age_seconds
        self._clock = clock

    def list_models(self, video: bool = True) -> List[ModelSchema]:
        raw_models = _ensure_list(
            self.client.list_models(video=video) or [],
            context="model list",
        )

        models = []

        for item in raw_models:
            entry = _ensure_dict(item, context="model list entry")
            models.append(_parse_model_schema(entry.get("job_type", ""), entry))

        return models

    def get_model(self, job_type: str) -> ModelSchema:
        raw = _ensure_dict(
            self.client.get_model(job_type) or {},
            context=f"model get {job_type}",
        )
        return _parse_model_schema(job_type, raw)

    def estimate_cost(
        self,
        job_type: str,
        prompt: str,
        duration: Optional[int] = None,
        resolution: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
    ) -> CostEstimate:
        """
        Délègue intégralement au HiggsfieldClient (donc au CLI réel) pour
        le prix : aucun montant n'est jamais inventé ou codé en dur ici.
        Si le CLI ne renvoie aucune valeur "credits" exploitable,
        `CostEstimate.credits` vaut `None` (jamais 0.0 par défaut) —
        c'est au consommateur (ex. GenerationCostService, Phase F) de
        traiter ce cas comme un coût inconnu plutôt que gratuit.
        """

        raw = _ensure_dict(
            self.client.estimate_cost(
                job_type=job_type,
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
            ) or {},
            context=f"generate cost {job_type}",
        )

        credits_raw = raw.get("credits")
        credits = (
            float(credits_raw)
            if isinstance(credits_raw, (int, float)) and not isinstance(credits_raw, bool)
            else None
        )

        return CostEstimate(
            job_type=job_type,
            credits=credits,
            raw=raw,
        )

    def get_account_balance(self) -> Optional[float]:
        """
        Délègue à HiggsfieldClient.account_status(). Retourne None
        (jamais 0.0) si le CLI ne renvoie aucun solde exploitable.
        """

        raw = _ensure_dict(
            self.client.account_status() or {},
            context="account status",
        )

        credits_raw = raw.get("credits")

        if isinstance(credits_raw, (int, float)) and not isinstance(credits_raw, bool):
            return float(credits_raw)

        return None

    # SÉCURITÉ (Phase B/C, RÉVISÉE Phase P2.35) : cette méthode
    # n'appelle JAMAIS `self.client.create_job()` ni AUCUNE autre
    # méthode de `self.client` -- vérifié structurellement par
    # tests/test_phase_p2_29_explicit_human_activation_entry_point.py::
    # test_provider_py_unchanged_create_job_still_disabled (AST révisé
    # en P2.35 : zéro `ast.Return`, zéro référence à `self.client`
    # n'importe où dans le corps de cette méthode -- l'ancienne
    # invariante "corps = un seul statement" datait de P2.29/P2.32,
    # quand cette méthode n'effectuait encore AUCUNE validation
    # structurelle ; P2.35 introduit délibérément cette validation
    # -- cf. docstring de module -- tout en PRÉSERVANT une garantie au
    # moins aussi forte : aucun chemin de cette méthode ne peut jamais
    # renvoyer un `Job`, et aucun chemin ne touche jamais `self.client`).
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
        violations = _provider_activation_violations(
            job_type=job_type,
            prompt=prompt,
            duration=params.get("duration"),
            resolution=params.get("resolution"),
            aspect_ratio=params.get("aspect_ratio"),
            request_id=request_id,
            avatar_sha256=avatar_sha256,
            face_reference_sha256=face_reference_sha256,
            provider_activation_contract=provider_activation_contract,
            max_age_seconds=self.max_age_seconds,
            now=self._clock(),
        )

        if violations:
            raise HiggsfieldRealGenerationDisabledError(
                "Real Higgsfield generation is disabled for this phase of "
                "the project. In addition, this specific attempt failed "
                "the Provider's own request-scoped activation boundary "
                "(Phase P2.35) -- see .reasons for the exhaustive list of "
                "structural violations. Use MockHiggsfieldProvider to "
                "test create_job()/get_job()/wait_for_job().",
                reasons=violations,
            )

        # Every structural check above passed: provider_activation_
        # contract is a genuine ControlledRealProviderActivationContract,
        # exactly bound (request_id/job_type/duration/resolution/
        # aspect_ratio/prompt sha/avatar sha/face-reference sha) to THIS
        # call, carries a non-empty authorization_id and request_scoped_
        # activation_id, and is not stale by this Provider's own
        # freshness sanity check. This PROVES the authority chain is
        # structurally coherent up to this exact boundary -- it does
        # NOT, and must never be read to, prove that a real call is
        # authorized. Phase P2.35 (Étape 9, "le point le plus
        # important") requires this method to STILL refuse
        # unconditionally here: `self.client.create_job()` is never
        # reached, regardless of how thoroughly the activation validates.
        # Closing this final transition is explicitly reserved for a
        # future, separately authorized phase.
        raise HiggsfieldRealGenerationDisabledError(
            "Real Higgsfield generation is disabled for this phase of "
            "the project (Phase B/C — MASTER PROMPT V2: 'Construire la "
            "base du Provider Higgsfield sans aucune génération réelle "
            "et sans consommer de crédit'). Phase P2.35: this exact "
            "attempt's provider_activation_contract IS structurally "
            "valid and request-scoped (request_id/model/duration/"
            "resolution/aspect_ratio/prompt/avatar/face-reference all "
            "matched) -- but a structurally valid activation is NOT the "
            "same as an authorized real execution. The final transition "
            "to a live self.client.create_job() call remains "
            "intentionally, permanently closed in this phase and "
            "requires a distinct future phase with explicit human "
            "authorization and sufficient budget. Use "
            "MockHiggsfieldProvider to test create_job()/get_job()/"
            "wait_for_job().",
            reasons=[
                "activation_structurally_valid_but_real_execution_"
                "transition_intentionally_closed_in_this_phase",
            ],
        )

    def get_job(self, job_id: str) -> Job:
        raw = _ensure_dict(
            self.client.get_job(job_id) or {},
            context=f"generate get {job_id}",
        )
        return _parse_job(raw)

    def wait_for_job(
        self,
        job_id: str,
        timeout_seconds: float = 600,
        interval_seconds: float = 3,
    ) -> VideoResult:
        """
        Délègue au HiggsfieldClient, qui délègue lui-même au CLI
        `generate wait` (polling interne au CLI, pas de boucle Python
        ici — donc aucun risque de boucle infinie côté Provider). Le
        client applique un timeout subprocess légèrement supérieur au
        timeout CLI demandé, garantissant un retour même si le CLI ne
        respecte pas son propre délai (HiggsfieldTimeoutError est alors
        levée et se propage telle quelle jusqu'à l'appelant).

        États couverts par VideoResult/JobStatus :
        - succeeded : output_urls renseignées, VideoResult.succeeded True.
        - failed / canceled : état terminal, output_urls vide.
        - running / queued / unknown : état non terminal (timeout ou
          réponse ambiguë) — jamais interprété comme un succès.
        """

        raw = _ensure_dict(
            self.client.wait_for_job(
                job_id,
                timeout_seconds=timeout_seconds,
                interval_seconds=interval_seconds,
            ) or {},
            context=f"generate wait {job_id}",
        )

        return _parse_video_result(raw)
