"""
AI DIRECTOR — Client API REST Higgsfield, côté serveur (Phase F)

Chemin de production prévu pour une exécution depuis GitHub Actions. Les
appels sont des requêtes REST EXPLICITES (méthode, chemin, en-têtes, corps),
construites ici et envoyées par un transport injecté
(`integrations/higgsfield/https_transport.py`). Aucun SDK : l'en-tête
`Idempotency-Key` et la politique de reprise restent visibles et testables,
au lieu de dépendre d'un comportement de SDK non documenté.

ÉTAT : FERMÉ. Provider = CLOSED, décision NO-GO de la Phase A en vigueur.
- `submit_generation()`, `cancel_generation()` et `upload_media()` lèvent
  TOUJOURS `HiggsfieldRealGenerationDisabledError`, en instruction unique,
  sans rien construire ni transmettre (verrous F-1, F-2 et F-3, vérifiés
  par AST dans tests/test_phase_f_production_path.py). Ils s'ajoutent aux
  quatre verrous de la Phase A sans en remplacer ni en modifier aucun.
- Ce client n'est câblé à aucun chemin de production : ni `director.py`,
  ni `HiggsfieldProvider`, ni `GenerationJobService` ne l'importent. Son
  point d'intégration futur est DERRIÈRE `HiggsfieldProvider.create_job()`
  (verrou 2), jamais à côté.
- Chaque fait d'API utilisé porte son niveau de confirmation
  (`HIGGSFIELD_REST_FACTS`). Aucun n'est `CONFIRMED` : le transport réel
  refuse donc toute opération, y compris en lecture.

Ce module ne fait aucun appel réseau lui-même et n'importe aucun module
réseau.
"""

import json
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from integrations.higgsfield.errors import HiggsfieldError, HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.manifest import GenerationManifest
from integrations.higgsfield.types import JobStatus


API_HOST = "platform.higgsfield.ai"


class FactStatus(str, Enum):
    # Confirmé par écrit par Higgsfield ou par la documentation primaire,
    # constaté et consigné par le propriétaire du projet.
    CONFIRMED = "confirmed"
    # Vu dans des résumés de recherche de la documentation publique, sans
    # lecture vérifiée de la source : jamais suffisant pour envoyer.
    SECONDARY_SOURCE = "secondary_source"
    UNCONFIRMED = "unconfirmed"


@dataclass(frozen=True)
class ApiFact:
    value: str
    status: FactStatus
    note: str = ""


# Constaté le 2026-10-02 par recherche web (résumés de docs.higgsfield.ai,
# sans appel à l'API ni lecture directe de la documentation). Toute
# promotion en CONFIRMED est une décision du propriétaire, avec sa source.
HIGGSFIELD_REST_FACTS: Mapping[str, ApiFact] = {
    "base_url": ApiFact(f"https://{API_HOST}", FactStatus.SECONDARY_SOURCE),
    "auth_scheme": ApiFact(
        "Authorization: Key <key_id>:<key_secret>",
        FactStatus.SECONDARY_SOURCE,
        "clé et secret créés dans Higgsfield Cloud ; usage serveur uniquement",
    ),
    "submit_endpoint": ApiFact("POST /{model_id}", FactStatus.SECONDARY_SOURCE, "file d'attente asynchrone"),
    "submit_model_id": ApiFact(
        "identifiant REST du modèle (seedance_2_0 côté CLI)",
        FactStatus.UNCONFIRMED,
        "la correspondance entre le job_type du CLI et le model_id REST n'est pas établie",
    ),
    "submit_body_schema": ApiFact(
        "champs JSON du prompt, de la durée, de la résolution, du format et des médias",
        FactStatus.UNCONFIRMED,
        "le corps construit par `request_body()` est provisoire",
    ),
    "submit_response_request_id": ApiFact("champ `request_id` de la réponse", FactStatus.SECONDARY_SOURCE),
    "status_endpoint": ApiFact("GET /requests/{request_id}/status", FactStatus.SECONDARY_SOURCE),
    "status_values": ApiFact(
        "queued, in_progress, completed, failed, nsfw, canceled",
        FactStatus.UNCONFIRMED,
        "toute valeur non reconnue est lue comme UNKNOWN, jamais comme un succès",
    ),
    "cancel_endpoint": ApiFact(
        "POST /requests/{request_id}/cancel -> 202",
        FactStatus.SECONDARY_SOURCE,
        "annule seulement une requête pas encore démarrée ; effet sur la facturation inconnu",
    ),
    "estimate_endpoint": ApiFact("aucun endpoint REST d'estimation connu", FactStatus.UNCONFIRMED),
    "estimate_is_binding_ceiling": ApiFact(
        "l'estimation borne-t-elle la facturation réelle ?",
        FactStatus.UNCONFIRMED,
        "l'estimation n'est JAMAIS présentée comme un plafond garanti",
    ),
    "media_upload": ApiFact("procédure d'envoi des médias (upload, URL signée)", FactStatus.UNCONFIRMED),
    "idempotency_key_header": ApiFact(
        "en-tête Idempotency-Key honoré par la soumission",
        FactStatus.UNCONFIRMED,
        "sans confirmation, une réponse ambiguë n'est jamais renvoyée",
    ),
    "insufficient_credits_signal": ApiFact(
        "statut HTTP ou code d'erreur d'un refus pour crédits insuffisants",
        FactStatus.UNCONFIRMED,
        "402 ou message explicite traités comme tels ; tout autre refus exige aussi une nouvelle approbation",
    ),
}

# Faits dont dépend chaque opération : tous doivent être CONFIRMED pour
# qu'un transport accepte de l'envoyer.
OPERATION_REQUIRED_FACTS: Mapping[str, Tuple[str, ...]] = {
    "submit": (
        "base_url", "auth_scheme", "submit_endpoint", "submit_model_id", "submit_body_schema",
        "submit_response_request_id", "media_upload", "idempotency_key_header",
        "insufficient_credits_signal",
    ),
    "status": ("base_url", "auth_scheme", "status_endpoint", "status_values"),
    "cancel": ("base_url", "auth_scheme", "cancel_endpoint"),
    "estimate": ("base_url", "auth_scheme", "estimate_endpoint", "submit_body_schema", "media_upload"),
    "upload": ("base_url", "auth_scheme", "media_upload"),
}

# Seules opérations qu'un transport peut envoyer, une fois leurs faits
# confirmés. Liste fermée : soumission, annulation et upload n'y figurent
# pas, et aucune variable ne l'élargit.
READ_ONLY_REST_OPERATIONS = frozenset({"status", "estimate"})


class HiggsfieldApiSpecUnconfirmedError(HiggsfieldError):
    """Un fait d'API requis par l'opération n'est pas confirmé : rien n'est envoyé."""

    def __init__(self, message: str, unconfirmed: List[str]):
        super().__init__(message)
        self.unconfirmed = list(unconfirmed)


class TransportNotSentError(HiggsfieldError):
    """La connexion n'a jamais été établie : aucun octet de la requête n'est parti."""


class TransportAmbiguousError(HiggsfieldError):
    """Délai dépassé ou coupure APRÈS le début de l'envoi : la requête a peut-être été reçue."""


def operation_blockers(operation: str, facts: Mapping[str, ApiFact] = HIGGSFIELD_REST_FACTS) -> List[str]:
    """Faits requis par `operation` qui ne sont pas CONFIRMED. Opération inconnue : bloquée."""

    required = OPERATION_REQUIRED_FACTS.get(operation)
    if required is None:
        return [f"unknown operation {operation!r}"]
    return [
        name for name in required
        if not isinstance(facts.get(name), ApiFact) or facts[name].status is not FactStatus.CONFIRMED
    ]


def launch_blockers(facts: Mapping[str, ApiFact] = HIGGSFIELD_REST_FACTS) -> List[str]:
    """Tous les faits non confirmés dont dépendrait un premier lancement réel."""

    names = sorted({name for required in OPERATION_REQUIRED_FACTS.values() for name in required})
    names.append("estimate_is_binding_ceiling")
    return [name for name in names if facts[name].status is not FactStatus.CONFIRMED]


@dataclass(frozen=True)
class HttpRequest:
    """
    Requête REST explicite. Ne porte JAMAIS d'identifiant d'authentification :
    l'en-tête `Authorization` est ajouté par le transport au moment de
    l'envoi. `body` peut contenir le prompt : il n'apparaît pas dans `repr`.
    """

    operation: str
    method: str
    path: str
    headers: Tuple[Tuple[str, str], ...] = ()
    body: bytes = field(default=b"", repr=False)

    def header(self, name: str) -> Optional[str]:
        return next((value for key, value in self.headers if key.lower() == name.lower()), None)

    def public_summary(self) -> Dict[str, Any]:
        """Forme publiable dans un journal : jamais de corps, de secret ni d'URL complète."""

        return {"operation": self.operation, "method": self.method, "body_bytes": len(self.body)}


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes = field(default=b"", repr=False)


_PROVIDER_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")


def _validated_provider_request_id(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and _PROVIDER_REQUEST_ID.fullmatch(value) else None


def _json_object(body: bytes) -> Optional[Dict[str, Any]]:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


# ============================================================
# Classification des réponses -- fermée : tout ce qui n'est pas
# explicitement reconnu est AMBIGUOUS (soumission) ou UNKNOWN (statut).
# ============================================================

class SubmitOutcomeKind(str, Enum):
    ACCEPTED = "accepted"
    NOT_SENT = "not_sent"
    AMBIGUOUS = "ambiguous"
    INSUFFICIENT_CREDITS = "insufficient_credits"
    REJECTED = "rejected"
    AUTH_FAILED = "auth_failed"


@dataclass(frozen=True)
class SubmitOutcome:
    kind: SubmitOutcomeKind
    http_status: Optional[int] = None
    provider_request_id: Optional[str] = None
    reason: str = ""

    @property
    def requires_new_approval(self) -> bool:
        """
        Refus définitif : l'approbation en cours est épuisée. Tout nouvel
        envoi exige une nouvelle approbation (donc un nouveau manifeste
        approuvé et une nouvelle clé d'idempotence), y compris après un
        refus pour crédits insuffisants.
        """

        return self.kind in (
            SubmitOutcomeKind.INSUFFICIENT_CREDITS,
            SubmitOutcomeKind.REJECTED,
            SubmitOutcomeKind.AUTH_FAILED,
        )


def _mentions_insufficient_credits(body: bytes) -> bool:
    text = body.decode("utf-8", errors="replace").lower()
    return "insufficient" in text and ("credit" in text or "balance" in text)


def classify_submit_response(response: HttpResponse) -> SubmitOutcome:
    status = response.status
    if status in (200, 201, 202):
        payload = _json_object(response.body)
        provider_request_id = _validated_provider_request_id((payload or {}).get("request_id"))
        if provider_request_id is None:
            return SubmitOutcome(
                SubmitOutcomeKind.AMBIGUOUS, status,
                reason="success status without a valid request_id: a job may exist",
            )
        return SubmitOutcome(SubmitOutcomeKind.ACCEPTED, status, provider_request_id)
    if status == 402 or (400 <= status < 500 and _mentions_insufficient_credits(response.body)):
        return SubmitOutcome(
            SubmitOutcomeKind.INSUFFICIENT_CREDITS, status,
            reason="refused for insufficient credits: a new approval is required before any new send",
        )
    if status in (401, 403):
        return SubmitOutcome(SubmitOutcomeKind.AUTH_FAILED, status, reason="authentication refused")
    if status in (408, 409, 425, 429) or status >= 500:
        return SubmitOutcome(
            SubmitOutcomeKind.AMBIGUOUS, status,
            reason="the request may or may not have been processed",
        )
    if 400 <= status < 500:
        return SubmitOutcome(SubmitOutcomeKind.REJECTED, status, reason="request rejected")
    return SubmitOutcome(SubmitOutcomeKind.AMBIGUOUS, status, reason="unexpected status")


def classify_submit_transport_error(error: Exception) -> SubmitOutcome:
    if isinstance(error, TransportNotSentError):
        return SubmitOutcome(SubmitOutcomeKind.NOT_SENT, reason="connection never established")
    return SubmitOutcome(
        SubmitOutcomeKind.AMBIGUOUS,
        reason=f"transport failure after the send may have started ({type(error).__name__})",
    )


class RetryDecision(str, Enum):
    RETRY_SAME_KEY = "retry_same_key"
    STOP_ACCEPTED = "stop_accepted"
    STOP_STATE_UNKNOWN = "stop_state_unknown"
    STOP_NEW_APPROVAL_REQUIRED = "stop_new_approval_required"


@dataclass(frozen=True)
class SubmitRetryPolicy:
    """`max_attempts` est fourni explicitement par l'appelant ; 1 = aucune reprise."""

    max_attempts: int = 1

    def __post_init__(self):
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int) or self.max_attempts < 1:
            raise ValueError("max_attempts must be an int >= 1")


def plan_next_submit_attempt(
    outcome: SubmitOutcome,
    attempt: int,
    policy: SubmitRetryPolicy,
    idempotency_confirmed: bool,
) -> RetryDecision:
    """
    Décision PURE après la tentative numéro `attempt` (à partir de 1).
    Une reprise réutilise toujours la même requête et la même clé.
    - NOT_SENT : rien n'est parti, reprise possible dans la limite.
    - AMBIGUOUS : reprise seulement si la prise en charge de
      l'Idempotency-Key est CONFIRMÉE ; sinon, ou une fois la limite
      atteinte, état inconnu : rapprochement humain obligatoire, jamais un
      nouvel envoi.
    - Refus définitif : nouvelle approbation requise.
    """

    if outcome.kind is SubmitOutcomeKind.ACCEPTED:
        return RetryDecision.STOP_ACCEPTED
    if outcome.requires_new_approval:
        return RetryDecision.STOP_NEW_APPROVAL_REQUIRED
    can_retry = attempt < policy.max_attempts
    if outcome.kind is SubmitOutcomeKind.NOT_SENT:
        return RetryDecision.RETRY_SAME_KEY if can_retry else RetryDecision.STOP_NEW_APPROVAL_REQUIRED
    if outcome.kind is SubmitOutcomeKind.AMBIGUOUS and idempotency_confirmed is True and can_retry:
        return RetryDecision.RETRY_SAME_KEY
    return RetryDecision.STOP_STATE_UNKNOWN


_STATUS_VALUES = {
    "queued": JobStatus.QUEUED,
    "in_progress": JobStatus.RUNNING,
    "completed": JobStatus.SUCCEEDED,
    "failed": JobStatus.FAILED,
    "nsfw": JobStatus.FAILED,
    "canceled": JobStatus.CANCELED,
    "cancelled": JobStatus.CANCELED,
}


@dataclass(frozen=True)
class StatusObservation:
    """`output_urls` ne sont jamais publiées : seul leur nombre l'est."""

    provider_request_id: str
    status: JobStatus
    http_status: int
    output_urls: Tuple[str, ...] = field(default=(), repr=False)

    def public_summary(self) -> Dict[str, Any]:
        return {"status": self.status.value, "http_status": self.http_status, "output_count": len(self.output_urls)}


def classify_status_response(provider_request_id: str, response: HttpResponse) -> StatusObservation:
    payload = _json_object(response.body) if response.status == 200 else None
    status = JobStatus.UNKNOWN
    urls: Tuple[str, ...] = ()
    if payload is not None:
        status = _STATUS_VALUES.get(str(payload.get("status", "")).lower(), JobStatus.UNKNOWN)
        if status is JobStatus.SUCCEEDED:
            candidates = []
            for key in ("video", "images", "outputs"):
                value = payload.get(key)
                items = value if isinstance(value, list) else [value]
                for item in items:
                    url = item.get("url") if isinstance(item, dict) else None
                    if isinstance(url, str) and url.startswith("https://"):
                        candidates.append(url)
            urls = tuple(candidates)
            # Un « succès » sans aucun résultat exploitable n'est pas un succès.
            if not urls:
                status = JobStatus.UNKNOWN
    return StatusObservation(provider_request_id, status, response.status, urls)


class CancelOutcomeKind(str, Enum):
    ACCEPTED = "accepted"
    REFUSED = "refused"
    AMBIGUOUS = "ambiguous"


def classify_cancel_response(response: HttpResponse) -> CancelOutcomeKind:
    if response.status == 202:
        return CancelOutcomeKind.ACCEPTED
    if 400 <= response.status < 500 and response.status not in (408, 425, 429):
        return CancelOutcomeKind.REFUSED
    return CancelOutcomeKind.AMBIGUOUS


# ============================================================
# Transport par défaut et client
# ============================================================

class ClosedTransport:
    """Transport par défaut : refuse tout, n'ouvre jamais de connexion."""

    def send(self, request: HttpRequest) -> HttpResponse:
        raise HiggsfieldRealGenerationDisabledError(
            "ClosedTransport never sends anything (Provider = CLOSED).",
            reasons=[f"closed_transport: {request.operation}"],
        )


class HiggsfieldRestClient:
    """
    Construit les requêtes REST et classe les réponses. Les opérations
    mutantes sont fermées sans condition ; `get_status()` passe par le
    transport, qui refuse tant que ses faits ne sont pas confirmés.
    """

    def __init__(self, transport: Optional[Any] = None):
        self.transport = transport if transport is not None else ClosedTransport()

    @staticmethod
    def request_body(manifest: GenerationManifest, media_inputs: Mapping[str, str]) -> bytes:
        """
        Corps UNIQUE de l'estimation et de la soumission : les deux reçoivent
        exactement les mêmes paramètres, par construction. Schéma provisoire
        (`submit_body_schema` non confirmé). `media_inputs` associe chaque
        rôle du manifeste à la référence renvoyée par l'upload (non
        confirmé) ; un rôle manquant ou en trop est refusé.
        """

        roles = [item.role for item in manifest.media]
        if sorted(media_inputs) != sorted(roles):
            raise ValueError(f"media_inputs roles {sorted(media_inputs)} do not match manifest roles {sorted(roles)}")
        body = {
            "prompt": manifest.prompt,
            **dict(manifest.parameters),
            "media": [{"role": role, "input": media_inputs[role]} for role in roles],
        }
        return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def build_estimate_request(self, manifest: GenerationManifest, media_inputs: Mapping[str, str]) -> HttpRequest:
        """
        Aucun endpoint REST d'estimation n'est connu. Quand il le sera, son
        corps sera `request_body()`, le même que la soumission. La seule
        estimation existante reste `generate cost` (CLI), qui EXCLUT les
        médias (P3.85) : elle n'a pas les mêmes paramètres que la génération.
        """

        raise HiggsfieldApiSpecUnconfirmedError(
            "No REST estimate endpoint is confirmed: the REST estimate cannot be built.",
            operation_blockers("estimate"),
        )

    def build_submit_request(
        self, manifest: GenerationManifest, media_inputs: Mapping[str, str], idempotency_key: str
    ) -> HttpRequest:
        if not isinstance(idempotency_key, str) or not re.fullmatch(r"aidir1-[0-9a-f]{64}", idempotency_key):
            raise ValueError("idempotency_key must come from manifest.derive_idempotency_key()")
        return HttpRequest(
            operation="submit",
            method="POST",
            path=f"/{manifest.model_id}",
            headers=(
                ("Content-Type", "application/json"),
                ("Accept", "application/json"),
                ("Idempotency-Key", idempotency_key),
            ),
            body=self.request_body(manifest, media_inputs),
        )

    @staticmethod
    def _request_path(provider_request_id: str, suffix: str) -> str:
        if _validated_provider_request_id(provider_request_id) is None:
            raise ValueError(f"provider request id {provider_request_id!r} is not a plain identifier")
        return f"/requests/{provider_request_id}/{suffix}"

    def build_status_request(self, provider_request_id: str) -> HttpRequest:
        return HttpRequest("status", "GET", self._request_path(provider_request_id, "status"), (("Accept", "application/json"),))

    def build_cancel_request(self, provider_request_id: str) -> HttpRequest:
        return HttpRequest("cancel", "POST", self._request_path(provider_request_id, "cancel"), (("Accept", "application/json"),))

    def get_status(self, provider_request_id: str) -> StatusObservation:
        request = self.build_status_request(provider_request_id)
        try:
            response = self.transport.send(request)
        except (TransportNotSentError, TransportAmbiguousError):
            return StatusObservation(provider_request_id, JobStatus.UNKNOWN, 0)
        return classify_status_response(provider_request_id, response)

    # ========================================================
    # OPÉRATIONS MUTANTES -- fermées sans condition (verrous F-1 à F-3)
    # ========================================================

    def submit_generation(self, *args: Any, **kwargs: Any) -> SubmitOutcome:
        """Soumission facturable : FERMÉE. Rouvrir exige une décision distincte de la Phase A."""
        raise HiggsfieldRealGenerationDisabledError("HiggsfieldRestClient.submit_generation() is closed (Phase F lock F-1, Provider = CLOSED).", reasons=["rest_submit_unconditionally_closed"])

    def cancel_generation(self, *args: Any, **kwargs: Any) -> CancelOutcomeKind:
        """Annulation avant démarrage : FERMÉE tant que le Provider l'est (rien à annuler)."""
        raise HiggsfieldRealGenerationDisabledError("HiggsfieldRestClient.cancel_generation() is closed (Phase F lock F-2, Provider = CLOSED).", reasons=["rest_cancel_unconditionally_closed"])

    def upload_media(self, *args: Any, **kwargs: Any) -> Dict[str, str]:
        """Envoi des médias : FERMÉ (procédure non confirmée, Provider = CLOSED)."""
        raise HiggsfieldRealGenerationDisabledError("HiggsfieldRestClient.upload_media() is closed (Phase F lock F-3, Provider = CLOSED).", reasons=["rest_upload_unconditionally_closed"])
