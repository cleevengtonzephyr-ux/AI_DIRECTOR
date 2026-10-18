"""Synthetic-credential tests for the mock-only WebAuthn approval verifier."""

import hashlib
import json
import sys
import unittest
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from fido2.cose import ES256, RS1, RS256, EdDSA
from fido2.utils import websafe_encode
from fido2.webauthn import (
    Aaguid,
    AttestedCredentialData,
    AuthenticationResponse,
    AuthenticatorAssertionResponse,
    AuthenticatorData,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPROVAL_SERVICE_ROOT = PROJECT_ROOT / "approval_service"
if str(APPROVAL_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(APPROVAL_SERVICE_ROOT))

from approval_service.approval_statement import ApprovalStatement
from approval_service.webauthn_verifier import (
    RegisteredCredential,
    VerifiedApprovalAssertion,
    WebAuthnPolicy,
    WebAuthnVerificationError,
    WebAuthnVerifier,
)

FLAG = AuthenticatorData.FLAG
REQUESTED_AT = 1_800_000_000_000
RP_ID = "zephyr-approval.fr"
ORIGIN = "https://zephyr-approval.fr"
APPROVER_ID = "approver-pseudonym-1"
CREDENTIAL_ID = bytes(range(32))
USER_HANDLE = b"synthetic-approver-handle-1"
_ABSENT = object()


def _statement(**overrides) -> ApprovalStatement:
    values = dict(
        relying_party_id=RP_ID,
        approver_id=APPROVER_ID,
        auth_method="webauthn",
        repository_id="123456789",
        repository="cleevengtonzephyr-ux/AI_DIRECTOR",
        sha="a" * 40,
        workflow_ref="cleevengtonzephyr-ux/AI_DIRECTOR/.github/workflows/higgsfield-production.yml@refs/heads/main",
        run_id="987654321",
        run_attempt=1,
        run_actor_id="12",
        manifest_sha256="1" * 64,
        prompt_sha256="2" * 64,
        avatar_sha256="3" * 64,
        face_reference_sha256="4" * 64,
        job_type="seedance_2_0",
        duration=5,
        resolution="720p",
        aspect_ratio="9:16",
        request_id="request-1",
        authorization_id="authorization-1",
        approval_id="approval-1",
        nonce="5" * 64,
        requested_at=REQUESTED_AT,
        approval_deadline=REQUESTED_AT + 600_000,
        issued_at=REQUESTED_AT + 1_000,
        expires_at=REQUESTED_AT + 301_000,
        max_cost_credits_per_request=None,
    )
    values.update(overrides)
    return ApprovalStatement(**values)


def _client_data(challenge, **overrides) -> bytes:
    """Return clientDataJSON bytes; an override of ``_ABSENT`` drops the member."""

    members = {
        "type": "webauthn.get",
        "challenge": websafe_encode(challenge),
        "origin": ORIGIN,
        "crossOrigin": False,
    }
    members.update(overrides)
    members = {key: value for key, value in members.items() if value is not _ABSENT}
    return json.dumps(members, separators=(",", ":")).encode()


def _es256_sign(private_key, message):
    return private_key.sign(message, ec.ECDSA(hashes.SHA256()))


def _record(credential, **overrides) -> RegisteredCredential:
    values = dict(
        credential=credential,
        approver_id=APPROVER_ID,
        user_handle=USER_HANDLE,
        backup_eligible=False,
        revoked=False,
    )
    values.update(overrides)
    return RegisteredCredential(**values)


class _CredentialResolver:
    def __init__(self, records):
        self._records = {record.credential.credential_id: record for record in records}
        self.calls = 0

    def resolve(self, credential_id):
        self.calls += 1
        try:
            return self._records[credential_id]
        except KeyError:
            raise KeyError("unknown synthetic credential") from None


class _FixedResolver:
    def __init__(self, result):
        self._result = result

    def resolve(self, credential_id):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class WebAuthnVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_key = ec.generate_private_key(ec.SECP256R1())
        cls.other_private_key = ec.generate_private_key(ec.SECP256R1())
        cls.credential = AttestedCredentialData.create(
            Aaguid.NONE, CREDENTIAL_ID, ES256.from_cryptography_key(cls.private_key.public_key())
        )
        cls.statement = _statement()
        cls.now = cls.statement.issued_at + 10_000

    def _verifier(self, *records, resolver=None, clock=None, policy=None):
        if resolver is None:
            resolver = _CredentialResolver(records or (_record(self.credential),))
        return WebAuthnVerifier(
            WebAuthnPolicy() if policy is None else policy,
            resolver,
            (lambda: self.now) if clock is None else clock,
        )

    def _response(
        self,
        *,
        statement=None,
        client_data=None,
        rp_id=RP_ID,
        flags=FLAG.UP | FLAG.UV,
        counter=7,
        credential_id=CREDENTIAL_ID,
        user_handle=USER_HANDLE,
        sign=None,
        signature=None,
    ):
        """Act as a synthetic authenticator and return AuthenticationResponseJSON."""

        statement = self.statement if statement is None else statement
        if client_data is None:
            client_data = _client_data(statement.webauthn_challenge())
        auth_data = AuthenticatorData.create(hashlib.sha256(rp_id.encode()).digest(), flags, counter)
        if signature is None:
            sign = sign or (lambda data: _es256_sign(self.private_key, data))
            signature = sign(auth_data + hashlib.sha256(client_data).digest())
        response = AuthenticationResponse(
            raw_id=credential_id,
            response=AuthenticatorAssertionResponse(
                client_data=client_data,
                authenticator_data=auth_data,
                signature=signature,
                user_handle=user_handle,
            ),
        )
        return json.loads(json.dumps(dict(response)))

    def test_accepts_a_valid_assertion_and_returns_a_minimal_immutable_result(self):
        result = self._verifier().verify(self.statement, self._response())

        self.assertIsInstance(result, VerifiedApprovalAssertion)
        self.assertEqual(
            [field.name for field in fields(result)],
            [
                "approval_id",
                "statement_sha256",
                "approver_id",
                "credential_id",
                "authorized_at",
                "expires_at",
                "sign_count",
                "backup_state",
            ],
        )
        self.assertEqual(result.approval_id, "approval-1")
        self.assertEqual(result.statement_sha256, self.statement.sha256())
        self.assertEqual(result.approver_id, APPROVER_ID)
        self.assertEqual(result.credential_id, CREDENTIAL_ID)
        self.assertEqual(result.authorized_at, self.now)
        self.assertEqual(result.expires_at, self.statement.expires_at)
        self.assertLessEqual(result.expires_at, result.authorized_at + 300_000)
        self.assertEqual(result.sign_count, 7)
        self.assertFalse(result.backup_state)
        with self.assertRaises(FrozenInstanceError):
            result.approver_id = "someone-else"

    def test_accepts_absent_cross_origin_and_missing_user_handle(self):
        client_data = _client_data(self.statement.webauthn_challenge(), crossOrigin=_ABSENT)

        result = self._verifier().verify(
            self.statement, self._response(client_data=client_data, user_handle=None)
        )

        self.assertEqual(result.approval_id, self.statement.approval_id)

    def test_accepts_other_allowed_credential_algorithms(self):
        ed_key = ed25519.Ed25519PrivateKey.generate()
        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cases = (
            ("EdDSA", EdDSA.from_cryptography_key(ed_key.public_key()), ed_key.sign),
            (
                "RS256",
                RS256.from_cryptography_key(rsa_key.public_key()),
                lambda data: rsa_key.sign(data, padding.PKCS1v15(), hashes.SHA256()),
            ),
        )
        for name, cose_key, sign in cases:
            with self.subTest(algorithm=name):
                credential = AttestedCredentialData.create(Aaguid.NONE, CREDENTIAL_ID, cose_key)
                verifier = self._verifier(_record(credential))

                result = verifier.verify(self.statement, self._response(sign=sign))

                self.assertEqual(result.credential_id, CREDENTIAL_ID)

    def test_rejects_invalid_signatures(self):
        challenge = self.statement.webauthn_challenge()
        auth_data = AuthenticatorData.create(hashlib.sha256(RP_ID.encode()).digest(), FLAG.UP | FLAG.UV, 7)
        signature = _es256_sign(
            self.private_key, auth_data + hashlib.sha256(_client_data(challenge)).digest()
        )
        verifier = self._verifier()
        # Control: this exact signature is accepted, so each case below
        # differs from a valid assertion by one signed element only.
        verifier.verify(self.statement, self._response(signature=signature))

        cases = {
            "other key": self._response(sign=lambda data: _es256_sign(self.other_private_key, data)),
            "authenticator data altered after signing": self._response(counter=8, signature=signature),
            "client data altered after signing": self._response(
                client_data=_client_data(challenge, extra="altered"), signature=signature
            ),
            "truncated signature": self._response(signature=signature[:-4]),
            "empty signature": self._response(signature=b""),
        }
        for name, response in cases.items():
            with self.subTest(case=name), self.assertRaisesRegex(WebAuthnVerificationError, "signature"):
                verifier.verify(self.statement, response)

    def test_rejects_a_challenge_not_derived_from_this_statement(self):
        other_statement = _statement(manifest_sha256="f" * 64)
        cases = {
            "other statement": self._response(statement=other_statement),
            "random challenge": self._response(client_data=_client_data(bytes(32))),
            "truncated challenge": self._response(
                client_data=_client_data(self.statement.webauthn_challenge()[:16])
            ),
        }
        verifier = self._verifier()
        for name, response in cases.items():
            with self.subTest(case=name), self.assertRaisesRegex(WebAuthnVerificationError, "challenge"):
                verifier.verify(self.statement, response)

        # The same signed assertion is valid only for the statement it binds.
        verifier.verify(other_statement, cases["other statement"])

    def test_rejects_any_origin_other_than_the_configured_one(self):
        challenge = self.statement.webauthn_challenge()
        verifier = self._verifier()
        for origin in (
            "https://evil.example",
            "https://sub.zephyr-approval.fr",
            "http://zephyr-approval.fr",
            "https://zephyr-approval.fr:443",
            "https://zephyr-approval.fr/",
            "http://localhost",
            None,
        ):
            response = self._response(client_data=_client_data(challenge, origin=origin))
            with self.subTest(origin=origin), self.assertRaisesRegex(WebAuthnVerificationError, "origin"):
                verifier.verify(self.statement, response)

    def test_rejects_an_rp_id_hash_for_another_relying_party(self):
        verifier = self._verifier()
        for rp_id in ("evil.example", "sub.zephyr-approval.fr", "approval.fr", "localhost"):
            with self.subTest(rp_id=rp_id), self.assertRaisesRegex(WebAuthnVerificationError, "RP ID"):
                verifier.verify(self.statement, self._response(rp_id=rp_id))

    def test_policy_accepts_only_the_configured_rp_id_and_https_origin(self):
        self.assertEqual(WebAuthnPolicy().rp_id, RP_ID)
        self.assertEqual(WebAuthnPolicy().origin, ORIGIN)
        invalid = (
            {"rp_id": "localhost"},
            {"rp_id": "sub.zephyr-approval.fr"},
            {"origin": "http://zephyr-approval.fr"},
            {"origin": "https://sub.zephyr-approval.fr"},
            {"origin": "https://zephyr-approval.fr/"},
        )
        for overrides in invalid:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                WebAuthnPolicy(**overrides)

    def test_rejects_client_data_type_other_than_webauthn_get(self):
        challenge = self.statement.webauthn_challenge()
        verifier = self._verifier()
        for client_type in ("webauthn.create", "WEBAUTHN.GET", "webauthn.get ", "", 1):
            response = self._response(client_data=_client_data(challenge, type=client_type))
            with self.subTest(type=client_type), self.assertRaisesRegex(WebAuthnVerificationError, "webauthn.get"):
                verifier.verify(self.statement, response)

    def test_rejects_a_credential_type_other_than_public_key(self):
        verifier = self._verifier()
        for credential_type in ("password", None, _ABSENT):
            response = self._response()
            if credential_type is _ABSENT:
                del response["type"]
            else:
                response["type"] = credential_type
            with self.subTest(type=credential_type), self.assertRaisesRegex(WebAuthnVerificationError, "malformed"):
                verifier.verify(self.statement, response)

    def test_rejects_cross_origin_assertions(self):
        challenge = self.statement.webauthn_challenge()
        cases = (
            {"crossOrigin": True},
            {"crossOrigin": "false"},
            {"crossOrigin": 0},
            {"crossOrigin": None},
            {"topOrigin": ORIGIN},
        )
        verifier = self._verifier()
        for overrides in cases:
            response = self._response(client_data=_client_data(challenge, **overrides))
            with self.subTest(overrides=overrides), self.assertRaisesRegex(WebAuthnVerificationError, "cross-origin"):
                verifier.verify(self.statement, response)

    def test_requires_user_presence_and_user_verification(self):
        verifier = self._verifier()
        for flags, reason in ((FLAG.UV, r"\(UP\)"), (FLAG.UP, r"\(UV\)"), (FLAG(0), r"\(UP\)")):
            with self.subTest(flags=flags), self.assertRaisesRegex(WebAuthnVerificationError, reason):
                verifier.verify(self.statement, self._response(flags=flags))

    def test_rejects_unknown_revoked_or_foreign_credentials(self):
        unknown_id = bytes(reversed(range(32)))
        unknown = AttestedCredentialData.create(
            Aaguid.NONE, unknown_id, ES256.from_cryptography_key(self.private_key.public_key())
        )
        cases = {
            "unknown": (self._verifier(), self._response(credential_id=unknown_id), "not registered"),
            "revoked": (self._verifier(_record(self.credential, revoked=True)), self._response(), "revoked"),
            "other approver": (
                self._verifier(_record(self.credential, approver_id="approver-pseudonym-2")),
                self._response(),
                "expected approver",
            ),
            "other user handle": (
                self._verifier(),
                self._response(user_handle=b"synthetic-approver-handle-2"),
                "user handle",
            ),
            "resolver failure": (
                self._verifier(resolver=_FixedResolver(RuntimeError("storage unavailable"))),
                self._response(),
                "could not be resolved",
            ),
            "resolver returns nothing": (
                self._verifier(resolver=_FixedResolver(None)),
                self._response(),
                "could not be resolved",
            ),
            "resolver returns another credential": (
                self._verifier(resolver=_FixedResolver(_record(unknown))),
                self._response(),
                "could not be resolved",
            ),
        }
        for name, (verifier, response, reason) in cases.items():
            with self.subTest(case=name), self.assertRaisesRegex(WebAuthnVerificationError, reason):
                verifier.verify(self.statement, response)

    def test_enforces_backup_eligibility_and_backup_state_rules(self):
        accepted = (
            (False, FLAG(0)),
            (True, FLAG.BE),
            (True, FLAG.BE | FLAG.BS),
        )
        for registered_be, backup_flags in accepted:
            with self.subTest(registered_be=registered_be, flags=backup_flags):
                verifier = self._verifier(_record(self.credential, backup_eligible=registered_be))
                result = verifier.verify(
                    self.statement, self._response(flags=FLAG.UP | FLAG.UV | backup_flags)
                )
                self.assertEqual(result.backup_state, bool(backup_flags & FLAG.BS))

        be_changed = r"\(BE\) differs from registration"
        rejected = (
            (False, FLAG.BE, be_changed),
            (False, FLAG.BE | FLAG.BS, be_changed),
            (True, FLAG(0), be_changed),
            (True, FLAG.BS, be_changed),
            (False, FLAG.BS, r"\(BS\) is set without backup eligibility"),
        )
        for registered_be, backup_flags, reason in rejected:
            with self.subTest(registered_be=registered_be, flags=backup_flags), self.assertRaisesRegex(
                WebAuthnVerificationError, reason
            ):
                verifier = self._verifier(_record(self.credential, backup_eligible=registered_be))
                verifier.verify(self.statement, self._response(flags=FLAG.UP | FLAG.UV | backup_flags))

    def test_rejects_a_credential_algorithm_outside_the_allowlist(self):
        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        credential = AttestedCredentialData.create(
            Aaguid.NONE, CREDENTIAL_ID, RS1.from_cryptography_key(rsa_key.public_key())
        )
        response = self._response(
            sign=lambda data: rsa_key.sign(data, padding.PKCS1v15(), hashes.SHA1())
        )

        with self.assertRaisesRegex(WebAuthnVerificationError, "algorithm"):
            self._verifier(_record(credential)).verify(self.statement, response)

    def test_rejects_rs256_keys_below_2048_bits_or_of_unknown_size(self):
        def rs256_signer(private_key):
            return lambda data: private_key.sign(data, padding.PKCS1v15(), hashes.SHA256())

        for bits in (1024, 2047):
            rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=bits)
            credential = AttestedCredentialData.create(
                Aaguid.NONE, CREDENTIAL_ID, RS256.from_cryptography_key(rsa_key.public_key())
            )
            response = self._response(sign=rs256_signer(rsa_key))
            with self.subTest(bits=bits), self.assertRaisesRegex(WebAuthnVerificationError, "RS256 key size"):
                self._verifier(_record(credential)).verify(self.statement, response)

        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        valid = RS256.from_cryptography_key(rsa_key.public_key())
        response = self._response(sign=rs256_signer(rsa_key))
        # Control: the same 2048-bit key and assertion are accepted.
        self._verifier(_record(AttestedCredentialData.create(Aaguid.NONE, CREDENTIAL_ID, valid))).verify(
            self.statement, response
        )

        undeterminable = {
            "missing modulus": {1: 3, 3: RS256.ALGORITHM, -2: valid[-2]},
            "missing exponent": {1: 3, 3: RS256.ALGORITHM, -1: valid[-1]},
            "text modulus": {1: 3, 3: RS256.ALGORITHM, -1: valid[-1].hex(), -2: valid[-2]},
            "exponent rejected by cryptography": {1: 3, 3: RS256.ALGORITHM, -1: valid[-1], -2: b"\x01"},
        }
        for name, cose in undeterminable.items():
            credential = AttestedCredentialData.create(Aaguid.NONE, CREDENTIAL_ID, RS256(cose))
            with self.subTest(case=name), self.assertRaisesRegex(WebAuthnVerificationError, "RS256 key size"):
                self._verifier(_record(credential)).verify(self.statement, response)

    def test_rejects_assertions_outside_the_statement_window(self):
        late_statement = _statement(
            issued_at=REQUESTED_AT + 500_000,
            expires_at=REQUESTED_AT + 750_000,
        )
        cases = (
            (self.statement, self.statement.issued_at - 1, "not yet valid"),
            (self.statement, self.statement.expires_at, "expired"),
            (self.statement, self.statement.expires_at + 1, "expired"),
            (late_statement, late_statement.approval_deadline, "deadline"),
            (late_statement, late_statement.approval_deadline + 1, "deadline"),
        )
        for statement, now, reason in cases:
            verifier = self._verifier(clock=lambda now=now: now)
            response = self._response(statement=statement)
            with self.subTest(now=now, reason=reason), self.assertRaisesRegex(WebAuthnVerificationError, reason):
                verifier.verify(statement, response)

        last_instant = self.statement.expires_at - 1
        result = self._verifier(clock=lambda: last_instant).verify(self.statement, self._response())
        self.assertEqual(result.authorized_at, last_instant)

    def test_rejects_invalid_or_unavailable_clock_values(self):
        def failing_clock():
            raise OSError("clock unavailable")

        for clock in (lambda: True, lambda: float(self.now), lambda: 0, lambda: -1, lambda: str(self.now), failing_clock):
            with self.subTest(clock=clock), self.assertRaisesRegex(WebAuthnVerificationError, "clock"):
                self._verifier(clock=clock).verify(self.statement, self._response())

    def test_rejects_malformed_inputs(self):
        def with_response_member(name, value):
            response = self._response()
            response["response"][name] = value
            return response

        def with_member(name, value):
            response = self._response()
            response[name] = value
            return response

        short_auth_data = websafe_encode(hashlib.sha256(RP_ID.encode()).digest())
        cases = {
            "not a dict": "not-a-webauthn-response",
            "list": [self._response()],
            "missing response": {key: value for key, value in self._response().items() if key != "response"},
            "missing raw id": {key: value for key, value in self._response().items() if key not in ("id", "rawId")},
            "id differs from raw id": with_member("id", websafe_encode(bytes(32))),
            "client data is not JSON": with_response_member("clientDataJSON", websafe_encode(b"not json")),
            "client data is a JSON array": with_response_member("clientDataJSON", websafe_encode(b"[]")),
            "client data without challenge": with_response_member(
                "clientDataJSON", websafe_encode(b'{"type":"webauthn.get","origin":"https://zephyr-approval.fr"}')
            ),
            "authenticator data too short": with_response_member("authenticatorData", short_auth_data),
            "response is not an object": with_member("response", "nope"),
            "credential ID too short": self._response(credential_id=b"short-id"),
        }
        verifier = self._verifier()
        for name, response in cases.items():
            with self.subTest(case=name), self.assertRaises(WebAuthnVerificationError):
                verifier.verify(self.statement, response)

        for statement in (None, self.statement.to_dict()):
            with self.subTest(statement=type(statement).__name__), self.assertRaisesRegex(
                WebAuthnVerificationError, "statement"
            ):
                verifier.verify(statement, self._response())

    def test_rejection_messages_do_not_echo_assertion_material(self):
        response = self._response(sign=lambda data: _es256_sign(self.other_private_key, data))

        with self.assertRaises(WebAuthnVerificationError) as context:
            self._verifier().verify(self.statement, response)

        message = str(context.exception)
        for value in (
            response["rawId"],
            response["response"]["clientDataJSON"],
            response["response"]["signature"],
            response["response"]["authenticatorData"],
            websafe_encode(self.statement.webauthn_challenge()),
        ):
            self.assertNotIn(value, message)

    def test_verifier_is_stateless_and_leaves_single_use_to_the_future_store(self):
        resolver = _CredentialResolver((_record(self.credential),))
        verifier = self._verifier(resolver=resolver)
        response = self._response()
        snapshot = json.dumps(response, sort_keys=True)

        first = verifier.verify(self.statement, response)
        second = verifier.verify(self.statement, response)

        self.assertEqual(first, second)
        self.assertEqual(resolver.calls, 2)
        self.assertEqual(json.dumps(response, sort_keys=True), snapshot)

    def test_constructor_requires_policy_resolver_and_clock(self):
        resolver = _CredentialResolver((_record(self.credential),))
        invalid = (
            (None, resolver, lambda: self.now),
            (WebAuthnPolicy(), object(), lambda: self.now),
            (WebAuthnPolicy(), resolver, self.now),
        )
        for policy, credential_resolver, clock in invalid:
            with self.subTest(policy=policy, resolver=credential_resolver, clock=clock), self.assertRaises(TypeError):
                WebAuthnVerifier(policy, credential_resolver, clock)

    def test_registered_credential_record_is_validated(self):
        with self.assertRaises(ValueError):
            _record(bytes(self.credential))
        invalid = (
            {"approver_id": ""},
            {"approver_id": " padded "},
            {"user_handle": b""},
            {"user_handle": b"x" * 65},
            {"user_handle": "text-handle"},
            {"backup_eligible": 0},
            {"revoked": None},
        )
        for overrides in invalid:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                _record(self.credential, **overrides)
        with self.assertRaises(TypeError):
            RegisteredCredential(
                credential=self.credential,
                approver_id=APPROVER_ID,
                user_handle=USER_HANDLE,
                backup_eligible=False,
            )


if __name__ == "__main__":
    unittest.main()
