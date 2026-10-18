"""Mock-only verification of GitHub Actions OIDC run tokens.

This module never fetches JWKS or stores tokens. A trusted key resolver is
injected by the caller; production JWKS retrieval and durable replay detection
remain separate service responsibilities.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

import jwt
from jwt import InvalidTokenError

_SHA = re.compile(r"^[0-9a-f]{40}$")
_DECIMAL = re.compile(r"^[1-9][0-9]*$")
_KID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_REQUIRED_CLAIMS = (
    "iss",
    "aud",
    "exp",
    "iat",
    "nbf",
    "repository_id",
    "repository_owner_id",
    "repository",
    "ref",
    "event_name",
    "workflow_ref",
    "job_workflow_ref",
    "runner_environment",
    "sha",
    "run_id",
    "run_attempt",
)
_ALLOWED_ALGORITHMS = ("RS256",)
_CLOCK_SKEW_SECONDS = 30


class OidcVerificationError(ValueError):
    """Safe, token-free error raised for every rejected OIDC token."""


class SigningKeyResolver(Protocol):
    """Resolve a trusted RSA verification key by an untrusted key ID."""

    def resolve(self, kid: str) -> object:
        """Return a previously trusted public key or raise ``KeyError``."""


@dataclass(frozen=True, slots=True)
class OidcPolicy:
    """Exact run identity expected by one service interface."""

    audience: str
    repository_id: str
    repository_owner_id: str
    repository: str
    workflow_ref: str
    job_workflow_ref: str
    authorized_shas: frozenset[str]
    expected_environment: str | None = None
    issuer: str = "https://token.actions.githubusercontent.com"

    def __post_init__(self) -> None:
        for name in (
            "audience",
            "repository_id",
            "repository_owner_id",
            "repository",
            "workflow_ref",
            "job_workflow_ref",
            "issuer",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value or value.strip() != value:
                raise ValueError(f"{name} must be a non-empty, trimmed string")
        for name in ("repository_id", "repository_owner_id"):
            if _DECIMAL.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must be a positive decimal identifier")
        if type(self.authorized_shas) is not frozenset or not self.authorized_shas:
            raise ValueError("authorized_shas must be a non-empty frozenset")
        if any(type(sha) is not str or _SHA.fullmatch(sha) is None for sha in self.authorized_shas):
            raise ValueError("authorized_shas must contain only full lowercase Git SHAs")
        if self.expected_environment is not None and (
            type(self.expected_environment) is not str
            or not self.expected_environment
            or self.expected_environment.strip() != self.expected_environment
        ):
            raise ValueError("expected_environment must be None or a trimmed string")
        if self.issuer != "https://token.actions.githubusercontent.com":
            raise ValueError("issuer must be the fixed GitHub Actions OIDC issuer")


@dataclass(frozen=True, slots=True)
class VerifiedRunIdentity:
    """Minimal, verified claims safe to pass to the request layer.

    ``actor_id`` is the stable account ID of the run initiator when the token
    carries it; ``actor`` is a renamable login kept for display only and never
    used as an identity. Neither links the run to a WebAuthn approver, and G1
    D-5 remains unresolved.
    """

    repository_id: str
    repository_owner_id: str
    repository: str
    sha: str
    workflow_ref: str
    job_workflow_ref: str
    run_id: str
    run_attempt: int
    actor: str | None
    actor_id: str | None
    token_id: str | None


class OidcVerifier:
    """Verify GitHub Actions JWTs without network, secrets, or side effects."""

    def __init__(self, policy: OidcPolicy, key_resolver: SigningKeyResolver) -> None:
        if not callable(getattr(key_resolver, "resolve", None)):
            raise TypeError("key_resolver must provide resolve(kid)")
        self._policy = policy
        self._key_resolver = key_resolver

    def verify(self, token: str) -> VerifiedRunIdentity:
        """Verify signature, time bounds, audience and exact run claims.

        Errors deliberately omit the token and claim values so callers can
        safely report the exception without leaking bearer credentials.
        """

        if type(token) is not str or not token or token.strip() != token:
            raise OidcVerificationError("OIDC token is missing or malformed")
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256":
                raise OidcVerificationError("OIDC algorithm is not allowed")
            kid = header.get("kid")
            if type(kid) is not str or _KID.fullmatch(kid) is None:
                raise OidcVerificationError("OIDC key identifier is missing or malformed")
            key = self._key_resolver.resolve(kid)
            claims = jwt.decode(
                token,
                key=key,
                algorithms=list(_ALLOWED_ALGORITHMS),
                issuer=self._policy.issuer,
                audience=self._policy.audience,
                leeway=_CLOCK_SKEW_SECONDS,
                options={"require": list(_REQUIRED_CLAIMS)},
            )
        except OidcVerificationError:
            raise
        except (InvalidTokenError, KeyError, TypeError, ValueError):
            raise OidcVerificationError("OIDC token verification failed") from None
        except Exception:
            # Resolver implementations must fail closed and must not let
            # third-party errors escape as an approval-capable result.
            raise OidcVerificationError("OIDC signing key could not be resolved") from None

        if type(claims) is not dict:
            raise OidcVerificationError("OIDC token claims must be a JSON object")
        if claims.get("aud") != self._policy.audience:
            raise OidcVerificationError("OIDC audience must match this interface exactly")
        if claims.get("repository_id") != self._policy.repository_id:
            raise OidcVerificationError("OIDC repository identity does not match policy")
        if claims.get("repository_owner_id") != self._policy.repository_owner_id:
            raise OidcVerificationError("OIDC repository owner does not match policy")
        if claims.get("repository") != self._policy.repository:
            raise OidcVerificationError("OIDC repository name does not match policy")
        if claims.get("ref") != "refs/heads/main":
            raise OidcVerificationError("OIDC ref is not the protected main branch")
        if claims.get("event_name") != "workflow_dispatch":
            raise OidcVerificationError("OIDC event is not an allowed manual dispatch")
        if claims.get("workflow_ref") != self._policy.workflow_ref:
            raise OidcVerificationError("OIDC workflow ref does not match policy")
        if claims.get("job_workflow_ref") != self._policy.job_workflow_ref:
            raise OidcVerificationError("OIDC job workflow ref does not match policy")
        if claims.get("runner_environment") != "github-hosted":
            raise OidcVerificationError("OIDC runner is not GitHub-hosted")
        if self._policy.expected_environment is not None:
            if claims.get("environment") != self._policy.expected_environment:
                raise OidcVerificationError("OIDC environment does not match policy")

        sha = claims.get("sha")
        if type(sha) is not str or _SHA.fullmatch(sha) is None:
            raise OidcVerificationError("OIDC SHA must be a full lowercase Git SHA")
        if sha not in self._policy.authorized_shas:
            raise OidcVerificationError("OIDC SHA is not explicitly authorized")

        run_id = claims.get("run_id")
        if type(run_id) is not str or _DECIMAL.fullmatch(run_id) is None:
            raise OidcVerificationError("OIDC run ID is malformed")
        run_attempt = claims.get("run_attempt")
        if type(run_attempt) is not int or run_attempt != 1:
            raise OidcVerificationError("OIDC run attempt is not the first attempt")
        # The design document marks `actor` as a claim to confirm against a
        # real, explicitly authorized token. Preserve it when present without
        # making an unverified claim name a prerequisite for this mock-only
        # verifier. It is a display value only: no identity decision uses it.
        actor = claims.get("actor")
        if actor is not None and (
            type(actor) is not str or not actor or actor.strip() != actor
        ):
            raise OidcVerificationError("OIDC actor is malformed")
        # GitHub documents `actor_id` as the ID of the personal account that
        # initiated the run; its official example is a string such as "12".
        # Accepting only a positive decimal string without a leading zero is
        # this module's assumption. Neither that representation nor the
        # claim's presence in a real token is confirmed, so it stays optional;
        # once present, any other value (null included) is refused.
        actor_id = None
        if "actor_id" in claims:
            actor_id = claims["actor_id"]
            if type(actor_id) is not str or _DECIMAL.fullmatch(actor_id) is None:
                raise OidcVerificationError("OIDC actor ID is malformed")
        token_id = claims.get("jti")
        if token_id is not None and (type(token_id) is not str or not token_id or token_id.strip() != token_id):
            raise OidcVerificationError("OIDC token identifier is malformed")

        return VerifiedRunIdentity(
            repository_id=self._policy.repository_id,
            repository_owner_id=self._policy.repository_owner_id,
            repository=self._policy.repository,
            sha=sha,
            workflow_ref=self._policy.workflow_ref,
            job_workflow_ref=self._policy.job_workflow_ref,
            run_id=run_id,
            run_attempt=run_attempt,
            actor=actor,
            actor_id=actor_id,
            token_id=token_id,
        )
