"""Mock-only verification of WebAuthn approval assertions.

One assertion is checked against an existing ``ApprovalStatement`` and the
challenge it derives. Enrolled credentials and the clock are injected by the
caller. This module performs no registration, persistence, network access or
approval state transition, and it does not establish anyone's civil identity.
"""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from typing import Callable, Protocol

from cryptography.hazmat.primitives.asymmetric import rsa
from fido2.cose import ES256, RS256, CoseKey, EdDSA
from fido2.server import Fido2Server
from fido2.utils import bytes2int
from fido2.webauthn import (
    AttestedCredentialData,
    AuthenticationResponse,
    CollectedClientData,
    PublicKeyCredentialRpEntity,
    UserVerificationRequirement,
)

from approval_service.approval_statement import ApprovalStatement

_ALLOWED_COSE_ALGORITHMS = frozenset({ES256.ALGORITHM, EdDSA.ALGORITHM, RS256.ALGORITHM})
_MIN_RSA_MODULUS_BITS = 2048
_MIN_CREDENTIAL_ID_BYTES = 16
_MAX_CREDENTIAL_ID_BYTES = 1023
_MAX_USER_HANDLE_BYTES = 64


class WebAuthnVerificationError(ValueError):
    """Safe, assertion-free error raised for every rejected assertion."""


def _rsa_modulus_bits(public_key: CoseKey) -> int | None:
    """Return the RS256 modulus size in bits, or ``None`` if it is undeterminable.

    fido2 2.2.1 exposes no key-size accessor: ``RS256.verify()`` rebuilds the
    key from COSE labels -1 (n) and -2 (e). The same rebuild is used here, and
    ``cryptography`` reports the size of the key it accepted.
    """

    modulus = public_key.get(-1)
    exponent = public_key.get(-2)
    if type(modulus) is not bytes or type(exponent) is not bytes:
        return None
    try:
        return rsa.RSAPublicNumbers(bytes2int(exponent), bytes2int(modulus)).public_key().key_size
    except Exception:
        return None


@dataclass(frozen=True, slots=True)
class RegisteredCredential:
    """Enrolled credential record returned by a trusted resolver.

    ``backup_eligible`` is the BE flag recorded at registration (G1 D-4) and
    must not change afterwards. ``revoked`` has no default: a resolver must
    state it explicitly.
    """

    credential: AttestedCredentialData
    approver_id: str
    user_handle: bytes
    backup_eligible: bool
    revoked: bool

    def __post_init__(self) -> None:
        if not isinstance(self.credential, AttestedCredentialData):
            raise ValueError("credential must be fido2 AttestedCredentialData")
        if (
            type(self.approver_id) is not str
            or not self.approver_id
            or self.approver_id.strip() != self.approver_id
        ):
            raise ValueError("approver_id must be a non-empty, trimmed string")
        if type(self.user_handle) is not bytes or not 1 <= len(self.user_handle) <= _MAX_USER_HANDLE_BYTES:
            raise ValueError("user_handle must be 1 to 64 bytes")
        if type(self.backup_eligible) is not bool or type(self.revoked) is not bool:
            raise ValueError("backup_eligible and revoked must be booleans")


class CredentialResolver(Protocol):
    """Resolve an enrolled credential by an untrusted credential ID."""

    def resolve(self, credential_id: bytes) -> RegisteredCredential:
        """Return the enrolled credential record or raise ``KeyError``."""


@dataclass(frozen=True, slots=True)
class WebAuthnPolicy:
    """Relying Party identity expected by the approval interface."""

    rp_id: str = ApprovalStatement.RELYING_PARTY_ID
    origin: str = f"https://{ApprovalStatement.RELYING_PARTY_ID}"

    def __post_init__(self) -> None:
        if self.rp_id != ApprovalStatement.RELYING_PARTY_ID:
            raise ValueError("rp_id must be the approval statement RP ID")
        if self.origin != f"https://{self.rp_id}":
            raise ValueError("origin must be the exact HTTPS origin of the RP ID")


@dataclass(frozen=True, slots=True)
class VerifiedApprovalAssertion:
    """Minimal outcome of one verified assertion.

    It shows that the holder of an enrolled, non-revoked credential signed
    this statement's challenge with UP and UV. It does not identify a person,
    consume the approval or record anything. ``sign_count`` and
    ``backup_state`` are returned for a future credential store; beyond the
    BE/BS rules they are not evaluated here.
    """

    approval_id: str
    statement_sha256: str
    approver_id: str
    credential_id: bytes
    authorized_at: int
    expires_at: int
    sign_count: int
    backup_state: bool


class WebAuthnVerifier:
    """Verify approval assertions without network, persistence, or side effects."""

    def __init__(
        self,
        policy: WebAuthnPolicy,
        credential_resolver: CredentialResolver,
        clock: Callable[[], int],
    ) -> None:
        if type(policy) is not WebAuthnPolicy:
            raise TypeError("policy must be a WebAuthnPolicy")
        if not callable(getattr(credential_resolver, "resolve", None)):
            raise TypeError("credential_resolver must provide resolve(credential_id)")
        if not callable(clock):
            raise TypeError("clock must return Unix time in milliseconds")
        self._policy = policy
        self._credential_resolver = credential_resolver
        self._clock = clock
        self._rp = PublicKeyCredentialRpEntity(name="AI_DIRECTOR approval", id=policy.rp_id)
        # fido2's default origin check also accepts subdomains and
        # http://localhost; the approval interface accepts one exact origin.
        self._server = Fido2Server(self._rp, verify_origin=lambda origin: origin == policy.origin)

    def verify(self, statement: ApprovalStatement, response: dict[str, object]) -> VerifiedApprovalAssertion:
        """Verify one ``AuthenticationResponseJSON`` against ``statement``.

        Errors deliberately omit assertion and statement values. Single use,
        the ``PENDING`` state and the D-5 separation from the GitHub actor
        belong to the future transactional store and are not enforced here.
        """

        if type(statement) is not ApprovalStatement:
            raise WebAuthnVerificationError("approval statement is missing or malformed")
        if statement.relying_party_id != self._policy.rp_id:
            raise WebAuthnVerificationError("approval statement RP ID does not match policy")
        if type(response) is not dict or response.get("type") != "public-key":
            raise WebAuthnVerificationError("WebAuthn response is missing or malformed")
        try:
            authentication = AuthenticationResponse.from_dict(response)
            assertion = authentication.response
            client_data = assertion.client_data
            auth_data = assertion.authenticator_data
            client_data_fields = json.loads(client_data)
        except Exception:
            raise WebAuthnVerificationError("WebAuthn response is missing or malformed") from None
        credential_id = authentication.raw_id
        if not _MIN_CREDENTIAL_ID_BYTES <= len(credential_id) <= _MAX_CREDENTIAL_ID_BYTES:
            raise WebAuthnVerificationError("WebAuthn credential ID is malformed")

        record = self._resolve(credential_id)
        if record.revoked:
            raise WebAuthnVerificationError("WebAuthn credential is revoked")
        if record.approver_id != statement.approver_id:
            raise WebAuthnVerificationError("WebAuthn credential does not belong to the expected approver")
        if assertion.user_handle is not None and not hmac.compare_digest(
            assertion.user_handle, record.user_handle
        ):
            raise WebAuthnVerificationError("WebAuthn user handle does not match the expected approver")
        if type(record.credential.public_key).ALGORITHM not in _ALLOWED_COSE_ALGORITHMS:
            raise WebAuthnVerificationError("WebAuthn credential algorithm is not allowed")
        if type(record.credential.public_key).ALGORITHM == RS256.ALGORITHM:
            modulus_bits = _rsa_modulus_bits(record.credential.public_key)
            if modulus_bits is None or modulus_bits < _MIN_RSA_MODULUS_BITS:
                raise WebAuthnVerificationError("WebAuthn RS256 key size is unknown or below 2048 bits")

        challenge = statement.webauthn_challenge()
        if client_data.type != CollectedClientData.TYPE.GET:
            raise WebAuthnVerificationError("WebAuthn client data type must be webauthn.get")
        if client_data.origin != self._policy.origin:
            raise WebAuthnVerificationError("WebAuthn origin does not match policy")
        if client_data.cross_origin is not False or "topOrigin" in client_data_fields:
            raise WebAuthnVerificationError("WebAuthn cross-origin assertions are not allowed")
        if not hmac.compare_digest(client_data.challenge, challenge):
            raise WebAuthnVerificationError("WebAuthn challenge does not match the approval statement")
        if not hmac.compare_digest(auth_data.rp_id_hash, self._rp.id_hash):
            raise WebAuthnVerificationError("WebAuthn RP ID hash does not match policy")
        if not auth_data.is_user_present():
            raise WebAuthnVerificationError("WebAuthn user presence (UP) is required")
        if not auth_data.is_user_verified():
            raise WebAuthnVerificationError("WebAuthn user verification (UV) is required")
        if auth_data.is_backup_eligible() != record.backup_eligible:
            raise WebAuthnVerificationError("WebAuthn backup eligibility (BE) differs from registration")
        if auth_data.is_backed_up() and not auth_data.is_backup_eligible():
            raise WebAuthnVerificationError("WebAuthn backup state (BS) is set without backup eligibility (BE)")

        try:
            _, state = self._server.authenticate_begin(
                [record.credential],
                user_verification=UserVerificationRequirement.REQUIRED,
                challenge=challenge,
            )
            self._server.authenticate_complete(state, [record.credential], authentication)
        except Exception:
            # Every check fido2 repeats before the signature has passed above,
            # so a failure here is the signature itself.
            raise WebAuthnVerificationError("WebAuthn signature verification failed") from None

        authorized_at = self._now()
        if authorized_at < statement.issued_at:
            raise WebAuthnVerificationError("approval statement is not yet valid")
        if authorized_at >= statement.approval_deadline:
            raise WebAuthnVerificationError("approval deadline has passed")
        if authorized_at >= statement.expires_at:
            raise WebAuthnVerificationError("approval statement has expired")

        # issued_at <= authorized_at, so the statement's expires_at already
        # falls within authorized_at + 300 seconds (G1 D-8).
        return VerifiedApprovalAssertion(
            approval_id=statement.approval_id,
            statement_sha256=statement.sha256(),
            approver_id=record.approver_id,
            credential_id=credential_id,
            authorized_at=authorized_at,
            expires_at=statement.expires_at,
            sign_count=auth_data.counter,
            backup_state=auth_data.is_backed_up(),
        )

    def _resolve(self, credential_id: bytes) -> RegisteredCredential:
        try:
            record = self._credential_resolver.resolve(credential_id)
        except KeyError:
            raise WebAuthnVerificationError("WebAuthn credential is not registered") from None
        except Exception:
            # Resolver implementations must fail closed and must not let
            # storage errors escape as an approval-capable result.
            raise WebAuthnVerificationError("WebAuthn credential could not be resolved") from None
        if type(record) is not RegisteredCredential or record.credential.credential_id != credential_id:
            raise WebAuthnVerificationError("WebAuthn credential could not be resolved")
        return record

    def _now(self) -> int:
        try:
            now = self._clock()
        except Exception:
            raise WebAuthnVerificationError("approval clock is unavailable") from None
        if type(now) is not int or now <= 0:
            raise WebAuthnVerificationError("approval clock returned an invalid timestamp")
        return now
