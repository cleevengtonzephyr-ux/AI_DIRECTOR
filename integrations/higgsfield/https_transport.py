"""
AI DIRECTOR — Transport HTTPS réel pour l'API REST Higgsfield (Phase F)

Seul module du chemin REST qui ouvre une connexion réseau. Avant toute
connexion, `send()` refuse, dans cet ordre :
1. toute opération hors de `READ_ONLY_REST_OPERATIONS` (soumission,
   annulation, upload : verrou F-4, indépendant des verrous F-1 à F-3 du
   client) ;
2. toute opération dont un fait d'API requis n'est pas CONFIRMED
   (`operation_blockers`) -- aujourd'hui, toutes ;
3. toute requête dont la méthode, le chemin ou la présence d'un corps ne
   correspond pas EXACTEMENT au gabarit de son opération
   (`OPERATION_ROUTES`) : l'étiquette `operation` ne suffit jamais à
   choisir ce qui est envoyé. Une opération sans gabarit (`estimate`,
   dont aucun endpoint n'est connu) est refusée ;
4. tout en-tête mal formé ou réservé.

Hôte fixe (`platform.higgsfield.ai`), HTTPS avec vérification TLS par
défaut (contexte de la bibliothèque standard), délai obligatoire, aucune redirection suivie, aucun proxy lu dans
l'environnement. Les identifiants sont injectés (`HiggsfieldApiCredentials`)
et n'apparaissent que dans l'en-tête ajouté au moment de l'envoi : jamais
dans `HttpRequest`, un `repr`, un message d'erreur ou un journal.
"""

import http.client
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.rest_api import (
    API_HOST,
    HIGGSFIELD_REST_FACTS,
    READ_ONLY_REST_OPERATIONS,
    ApiFact,
    HiggsfieldApiSpecUnconfirmedError,
    HttpRequest,
    HttpResponse,
    TransportAmbiguousError,
    TransportNotSentError,
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
_MAX_RESPONSE_BYTES = 1024 * 1024


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
        self._credentials = credentials
        self._timeout = float(timeout_seconds)
        self._facts = facts

    def send(self, request: HttpRequest) -> HttpResponse:
        if not isinstance(request, HttpRequest) or request.operation not in READ_ONLY_REST_OPERATIONS:
            raise HiggsfieldRealGenerationDisabledError(
                "HttpsTransport only sends read-only operations (Phase F lock F-4): "
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
        headers = {}
        for name, value in request.headers:
            if name.lower() == "authorization" or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", name) or not _SAFE_HEADER_VALUE.fullmatch(value):
                raise ValueError("request header is malformed or reserved")
            headers[name] = value
        headers["Authorization"] = self._credentials.authorization_header()
        return self._exchange(request, headers)

    def _exchange(self, request: HttpRequest, headers: dict) -> HttpResponse:
        # Sans `context` explicite, `HTTPSConnection` applique le contexte TLS
        # par défaut de la bibliothèque standard : certificat et nom d'hôte
        # vérifiés. `ssl` n'est pas importé ici (garde de la Phase C).
        connection = http.client.HTTPSConnection(API_HOST, timeout=self._timeout)
        try:
            try:
                connection.connect()
            except (OSError, http.client.HTTPException) as error:
                raise TransportNotSentError(
                    f"connection to the Higgsfield API was not established ({type(error).__name__})"
                ) from None
            try:
                connection.request(request.method, request.path, body=request.body or None, headers=headers)
                response = connection.getresponse()
                body = response.read(_MAX_RESPONSE_BYTES + 1)
            except (OSError, http.client.HTTPException) as error:
                # `from None` : la cause d'origine pourrait citer des en-têtes.
                raise TransportAmbiguousError(
                    f"transport failure after the request may have been sent ({type(error).__name__})"
                ) from None
            if len(body) > _MAX_RESPONSE_BYTES:
                raise TransportAmbiguousError("response body exceeds the accepted size")
            # Une redirection n'est jamais suivie : son statut est rendu tel quel.
            return HttpResponse(status=response.status, body=body)
        finally:
            connection.close()
