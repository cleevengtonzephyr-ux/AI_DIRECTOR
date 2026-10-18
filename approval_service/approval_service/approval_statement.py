"""Validated G2 approval statement and its WebAuthn challenge binding.

This module is local-only. It does not validate OIDC tokens or WebAuthn
assertions, persist state, make approval decisions, or contact a provider.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import ClassVar

from approval_service.canonical_json import canonical_json_bytes, canonical_json_sha256

_LOWER_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LOWER_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_APPROVAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]*$")
# Same assumption as the OIDC verifier's `actor_id`: a positive ASCII decimal
# string without a leading zero (GitHub's official example is "12").
_GITHUB_ACCOUNT_ID = re.compile(r"^[1-9][0-9]*$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_WORKFLOW_REF = re.compile(r"^.+/\.github/workflows/[^@]+@refs/heads/main$")
_JOB_TYPE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

_APPROVAL_WINDOW_MS = 600_000
_AUTHORIZATION_WINDOW_MS = 300_000
_CHALLENGE_DOMAIN = b"AI_DIRECTOR_APPROVAL_WEBAUTHN_V2\x00"


def _require_text(name: str, value: object, pattern: re.Pattern[str] | None = None) -> None:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{name} must be a non-empty, trimmed string")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ValueError(f"{name} must not contain control characters")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise ValueError(f"{name} has an invalid format")


def _require_timestamp_ms(name: str, value: object) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive Unix timestamp in milliseconds")


@dataclass(frozen=True, slots=True)
class ApprovalStatement:
    """Immutable, schema-validated statement bound to a synthetic/mock request.

    Timestamp values are integer Unix milliseconds. The credit ceiling is
    deliberately fixed to ``None`` because G1 D-14 has not authorized a
    numeric generation budget; consumers must refuse a request with no cap.

    Version 2 adds ``run_actor_id``, the numeric GitHub account ID that
    initiated the run, taken from a verified OIDC ``actor_id``; the approver
    signs it. The renamable ``actor`` login is never part of the statement.
    Signing this ID does not resolve G1 D-5. Version 1 is not supported.
    """

    relying_party_id: str
    approver_id: str
    auth_method: str
    repository_id: str
    repository: str
    sha: str
    workflow_ref: str
    run_id: str
    run_attempt: int
    run_actor_id: str
    manifest_sha256: str
    prompt_sha256: str
    avatar_sha256: str
    face_reference_sha256: str
    job_type: str
    duration: int
    resolution: str
    aspect_ratio: str
    request_id: str
    authorization_id: str
    approval_id: str
    nonce: str
    requested_at: int
    approval_deadline: int
    issued_at: int
    expires_at: int
    max_cost_credits_per_request: None = None

    VERSION: ClassVar[int] = 2
    RELYING_PARTY_ID: ClassVar[str] = "zephyr-approval.fr"
    AUTH_METHOD: ClassVar[str] = "webauthn"

    def __post_init__(self) -> None:
        _require_text("relying_party_id", self.relying_party_id)
        if self.relying_party_id != self.RELYING_PARTY_ID:
            raise ValueError("relying_party_id does not match the configured RP ID")

        _require_text("approver_id", self.approver_id, _SAFE_ID)
        if self.auth_method != self.AUTH_METHOD:
            raise ValueError("auth_method must be 'webauthn'")

        _require_text("repository_id", self.repository_id, _REPOSITORY_ID)
        _require_text("repository", self.repository, _REPOSITORY)
        _require_text("sha", self.sha, _LOWER_GIT_SHA)
        _require_text("workflow_ref", self.workflow_ref, _WORKFLOW_REF)
        _require_text("run_id", self.run_id, _REPOSITORY_ID)
        if type(self.run_attempt) is not int or self.run_attempt != 1:
            raise ValueError("run_attempt must be the first attempt")
        _require_text("run_actor_id", self.run_actor_id, _GITHUB_ACCOUNT_ID)

        for name in (
            "manifest_sha256",
            "prompt_sha256",
            "avatar_sha256",
            "face_reference_sha256",
        ):
            _require_text(name, getattr(self, name), _LOWER_SHA256)

        _require_text("job_type", self.job_type, _JOB_TYPE)
        if type(self.duration) is not int or self.duration <= 0:
            raise ValueError("duration must be a positive integer number of seconds")
        _require_text("resolution", self.resolution)
        _require_text("aspect_ratio", self.aspect_ratio)

        for name in ("request_id", "authorization_id"):
            _require_text(name, getattr(self, name), _SAFE_ID)
        _require_text("approval_id", self.approval_id, _APPROVAL_ID)
        _require_text("nonce", self.nonce, _LOWER_SHA256)
        if len({self.request_id, self.authorization_id, self.approval_id, self.nonce}) != 4:
            raise ValueError("request, authorization, approval IDs, and nonce must be distinct")

        for name in ("requested_at", "approval_deadline", "issued_at", "expires_at"):
            _require_timestamp_ms(name, getattr(self, name))
        if self.approval_deadline != self.requested_at + _APPROVAL_WINDOW_MS:
            raise ValueError("approval_deadline must be requested_at plus 600 seconds")
        if not self.requested_at <= self.issued_at < self.approval_deadline:
            raise ValueError("issued_at must fall within the approval window")
        if not self.issued_at < self.expires_at <= self.issued_at + _AUTHORIZATION_WINDOW_MS:
            raise ValueError("expires_at must be after issued_at and within 300 seconds")
        if self.max_cost_credits_per_request is not None:
            raise ValueError("a numeric credit ceiling is not authorized by G1 D-14")

    def to_dict(self) -> dict[str, object]:
        """Return the exact versioned JSON schema used for display and hashing."""

        return {"statement_version": self.VERSION, **asdict(self)}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return canonical_json_sha256(self.to_dict())

    def webauthn_challenge(self) -> bytes:
        """Derive a 32-byte, domain-separated challenge bound to this statement."""

        nonce_bytes = bytes.fromhex(self.nonce)
        return hashlib.sha256(
            _CHALLENGE_DOMAIN + self.canonical_bytes() + b"\x00" + nonce_bytes
        ).digest()
