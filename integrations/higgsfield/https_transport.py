"""
AI DIRECTOR — Transport HTTPS de l'API REST Higgsfield (Phase F) -- FERMÉ.

Provider = CLOSED : ce module n'ouvre AUCUNE connexion, pas même pour une
requête en lecture seule (`status`), et n'importe aucun module réseau.
`send()` valide la requête puis lève toujours
`HiggsfieldRealGenerationDisabledError` ; aucune autre méthode ne mène à
un échange HTTP. Aucune variable, option ni configuration (pas même des
faits d'API injectés comme CONFIRMED) ne rouvre l'envoi : une réouverture
exige une décision écrite et une étape distinctes
(docs/phase_a_real_generation_decision.md), qui réintroduirait l'échange.

Avant ce refus final, `send()` refuse, dans cet ordre :
1. toute opération hors de `READ_ONLY_REST_OPERATIONS` (soumission,
   annulation, upload : verrou F-4, indépendant des verrous F-1 à F-3 du
   client) ;
2. toute opération dont un fait d'API requis n'est pas CONFIRMED
   (`operation_blockers`) -- aujourd'hui, toutes ;
3. toute requête dont la méthode, le chemin ou la présence d'un corps ne
   correspond pas EXACTEMENT au gabarit de son opération
   (`OPERATION_ROUTES`) : l'étiquette `operation` ne suffit jamais à
   choisir ce qui serait envoyé. Une opération sans gabarit (`estimate`,
   dont aucun endpoint n'est connu) est refusée ;
4. tout en-tête mal formé ou réservé.

Les identifiants sont injectés (`HiggsfieldApiCredentials`) et validés ;
ils ne sont jamais affichés, comparés, sérialisés ni utilisés tant que le
transport est fermé.
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, NoReturn

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.rest_api import (
    HIGGSFIELD_REST_FACTS,
    READ_ONLY_REST_OPERATIONS,
    ApiFact,
    HiggsfieldApiSpecUnconfirmedError,
    HttpRequest,
    operation_blockers,
)

API_KEY_ID_ENV_VAR = "HIGGSFIELD_API_KEY_ID"
API_KEY_SECRET_ENV_VAR = "HIGGSFIELD_API_KEY_SECRET"

_PROVIDER_REQUEST_ID = r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}"


@dataclass(frozen=True)
class RouteTemplate:
    method: str
    path: "re.Pattern[str]"
    body_allowed: bool


# Gabarits fermés, par opération : seule une requête qui correspond
# exactement (méthode, chemin entier, corps) à celui de son opération peut
# partir. Aucune variable ne l'élargit ; les opérations mutantes n'y
# figurent pas, et `estimate` non plus tant qu'aucun endpoint n'est connu.
OPERATION_ROUTES: Mapping[str, RouteTemplate] = MappingProxyType({
    "status": RouteTemplate("GET", re.compile(rf"/requests/{_PROVIDER_REQUEST_ID}/status"), body_allowed=False),
})

_SAFE_HEADER_VALUE = re.compile(r"[\x20-\x7e]{0,512}")


class HiggsfieldApiCredentials:
    """Identifiants de l'API. Jamais affichés, comparés ni sérialisés."""

    __slots__ = ("_key_id", "_key_secret")

    def __init__(self, key_id: str, key_secret: str):
        for label, value in (("key_id", key_id), ("key_secret", key_secret)):
            if not isinstance(value, str) or not value or not _SAFE_HEADER_VALUE.fullmatch(value) or ":" in value:
                raise ValueError(f"Higgsfield API {label} is missing or malformed")
        self._key_id = key_id
        self._key_secret = key_secret

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> "HiggsfieldApiCredentials":
        """À n'appeler que dans le job autorisé ; absent ou vide -> erreur (aucun repli)."""

        return cls(environ.get(API_KEY_ID_ENV_VAR, ""), environ.get(API_KEY_SECRET_ENV_VAR, ""))

    def authorization_header(self) -> str:
        return f"Key {self._key_id}:{self._key_secret}"

    def __repr__(self) -> str:
        return "HiggsfieldApiCredentials(<redacted>)"

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError("HiggsfieldApiCredentials cannot be serialized")


class HttpsTransport:
    def __init__(
        self,
        credentials: HiggsfieldApiCredentials,
        timeout_seconds: float,
        facts: Mapping[str, ApiFact] = HIGGSFIELD_REST_FACTS,
    ):
        if not isinstance(credentials, HiggsfieldApiCredentials):
            raise TypeError("credentials must be HiggsfieldApiCredentials")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 0 < timeout_seconds <= 300:
            raise ValueError("timeout_seconds must be a number in (0, 300]")
        # Identifiants et délai sont validés mais jamais conservés : fermé, le
        # transport n'en a aucun usage.
        self._facts = facts

    def send(self, request: HttpRequest) -> NoReturn:
        if not isinstance(request, HttpRequest) or request.operation not in READ_ONLY_REST_OPERATIONS:
            raise HiggsfieldRealGenerationDisabledError(
                "HttpsTransport only accepts read-only operations (Phase F lock F-4): "
                "submission, cancellation and upload are refused before any connection.",
                reasons=[f"rest_operation_not_read_only: {getattr(request, 'operation', None)!r}"],
            )
        blockers = operation_blockers(request.operation, self._facts)
        if blockers:
            raise HiggsfieldApiSpecUnconfirmedError(
                f"Operation {request.operation!r} depends on unconfirmed API facts: nothing is sent.",
                blockers,
            )
        route = OPERATION_ROUTES.get(request.operation)
        if (
            route is None
            or request.method != route.method
            or not isinstance(request.path, str)
            or not route.path.fullmatch(request.path)
            or (request.body and not route.body_allowed)
        ):
            raise HiggsfieldRealGenerationDisabledError(
                f"Request does not match the closed route template of operation {request.operation!r}: nothing is sent.",
                reasons=[f"rest_route_not_allowed: {request.operation!r}"],
            )
        for name, value in request.headers:
            if name.lower() == "authorization" or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", name) or not _SAFE_HEADER_VALUE.fullmatch(value):
                raise ValueError("request header is malformed or reserved")
        # Provider = CLOSED : aucune connexion, même pour une requête en
        # lecture seule valide. Aucun échange HTTP n'existe dans ce module.
        raise HiggsfieldRealGenerationDisabledError(
            "HttpsTransport.send() opens no connection while Provider = CLOSED: "
            "not even a read-only request is sent. Reopening requires a separate "
            "written decision and step (docs/phase_a_real_generation_decision.md).",
            reasons=[f"provider_closed_no_https_connection: {request.operation!r}"],
        )
