"""Synthetic-key tests for the mock-only GitHub Actions OIDC verifier."""

import sys
import time
import unittest
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPROVAL_SERVICE_ROOT = PROJECT_ROOT / "approval_service"
if str(APPROVAL_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(APPROVAL_SERVICE_ROOT))

from approval_service.oidc_verifier import (
    OidcPolicy,
    OidcVerificationError,
    OidcVerifier,
)


class _KeyResolver:
    def __init__(self, keys):
        self._keys = keys

    def resolve(self, kid):
        try:
            return self._keys[kid]
        except KeyError:
            raise KeyError("unknown synthetic key") from None


class OidcVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.policy = OidcPolicy(
            audience="https://api.zephyr-approval.fr/request",
            repository_id="123456789",
            repository_owner_id="987654321",
            repository="cleevengtonzephyr-ux/AI_DIRECTOR",
            workflow_ref=(
                "cleevengtonzephyr-ux/AI_DIRECTOR/"
                ".github/workflows/higgsfield-production.yml@refs/heads/main"
            ),
            job_workflow_ref=(
                "cleevengtonzephyr-ux/AI_DIRECTOR/"
                ".github/workflows/higgsfield-production.yml@refs/heads/main"
            ),
            authorized_shas=frozenset({"a" * 40}),
        )
        cls.verifier = OidcVerifier(
            cls.policy,
            _KeyResolver({"synthetic-key-1": cls.private_key.public_key()}),
        )

    def _claims(self, **overrides):
        now = int(time.time())
        claims = {
            "iss": "https://token.actions.githubusercontent.com",
            "aud": self.policy.audience,
            "iat": now,
            "nbf": now,
            "exp": now + 120,
            "repository_id": self.policy.repository_id,
            "repository_owner_id": self.policy.repository_owner_id,
            "repository": self.policy.repository,
            "ref": "refs/heads/main",
            "event_name": "workflow_dispatch",
            "workflow_ref": self.policy.workflow_ref,
            "job_workflow_ref": self.policy.job_workflow_ref,
            "runner_environment": "github-hosted",
            "sha": "a" * 40,
            "run_id": "1234567890",
            "run_attempt": 1,
            "actor": "synthetic-actor",
            "actor_id": "12",
            "jti": "synthetic-token-id",
        }
        claims.update(overrides)
        return claims

    def _token(self, claims=None, *, key=None, kid="synthetic-key-1", algorithm="RS256"):
        signing_key = self.private_key if key is None else key
        headers = {"kid": kid, "alg": algorithm}
        return jwt.encode(self._claims() if claims is None else claims, signing_key, algorithm=algorithm, headers=headers)

    def test_accepts_a_signature_valid_exact_first_attempt(self):
        identity = self.verifier.verify(self._token())

        self.assertEqual(identity.repository_id, "123456789")
        self.assertEqual(identity.repository_owner_id, "987654321")
        self.assertEqual(identity.sha, "a" * 40)
        self.assertEqual(identity.run_id, "1234567890")
        self.assertEqual(identity.run_attempt, 1)
        self.assertEqual(identity.actor, "synthetic-actor")
        self.assertEqual(identity.actor_id, "12")
        self.assertEqual(identity.token_id, "synthetic-token-id")

    def test_issuer_and_allowed_signing_algorithm_are_fixed(self):
        invalid = (
            self._token(self._claims(iss="https://attacker.example")),
            self._token(key=self.other_private_key),
            self._token(algorithm="HS256", key="synthetic-secret"),
            self._token(algorithm="none", key=""),
        )
        for token in invalid:
            with self.subTest(token_kind=token.split(".")[0]), self.assertRaises(OidcVerificationError):
                self.verifier.verify(token)

    def test_rejects_unknown_key_id_and_malformed_token(self):
        unknown_kid = self._token(kid="unknown-key")
        missing_expiration = self._claims()
        missing_expiration.pop("exp")

        for token in (
            unknown_kid,
            "not-a-jwt",
            "",
            self._token(missing_expiration),
        ):
            with self.subTest(token=token[:12]), self.assertRaises(OidcVerificationError):
                self.verifier.verify(token)

    def test_rejects_wrong_audience_even_if_jwt_library_accepts_audience_list(self):
        cases = (
            {"aud": "https://api.zephyr-approval.fr/execute"},
            {"aud": [self.policy.audience, "https://api.zephyr-approval.fr/execute"]},
        )
        for change in cases:
            with self.subTest(audience=change["aud"]), self.assertRaises(OidcVerificationError):
                self.verifier.verify(self._token(self._claims(**change)))

    def test_rejects_claims_that_do_not_match_the_exact_run_policy(self):
        invalid_claims = (
            {"repository_id": "987654321"},
            {"repository_owner_id": "123456789"},
            {"repository": "fork/AI_DIRECTOR"},
            {"ref": "refs/heads/feature"},
            {"event_name": "push"},
            {"workflow_ref": "other/workflow.yml@refs/heads/main"},
            {"job_workflow_ref": "other/workflow.yml@refs/heads/main"},
            {"runner_environment": "self-hosted"},
        )
        for change in invalid_claims:
            with self.subTest(change=change), self.assertRaises(OidcVerificationError):
                self.verifier.verify(self._token(self._claims(**change)))

    def test_rejects_unlisted_or_noncanonical_commit_sha(self):
        invalid = (
            {"sha": "b" * 40},
            {"sha": "a" * 39},
            {"sha": "A" * 40},
            {"sha": "refs/heads/main"},
        )
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(OidcVerificationError):
                self.verifier.verify(self._token(self._claims(**change)))

    def test_rejects_noninitial_attempt_and_malformed_run_id(self):
        for change in ({"run_attempt": 2}, {"run_attempt": True}, {"run_id": "0"}, {"run_id": 123}):
            with self.subTest(change=change), self.assertRaises(OidcVerificationError):
                self.verifier.verify(self._token(self._claims(**change)))

    def test_rejects_expired_and_future_not_before_tokens(self):
        now = int(time.time())
        cases = (
            {"iat": now - 120, "nbf": now - 120, "exp": now - 31},
            {"iat": now + 31, "nbf": now + 31, "exp": now + 120},
        )
        for change in cases:
            with self.subTest(change=change), self.assertRaises(OidcVerificationError):
                self.verifier.verify(self._token(self._claims(**change)))

    def test_requires_an_optional_protected_environment_when_policy_sets_one(self):
        policy = OidcPolicy(
            audience=self.policy.audience,
            repository_id=self.policy.repository_id,
            repository_owner_id=self.policy.repository_owner_id,
            repository=self.policy.repository,
            workflow_ref=self.policy.workflow_ref,
            job_workflow_ref=self.policy.job_workflow_ref,
            authorized_shas=self.policy.authorized_shas,
            expected_environment="production-approval",
        )
        verifier = OidcVerifier(policy, _KeyResolver({"synthetic-key-1": self.private_key.public_key()}))

        self.assertTrue(verifier.verify(self._token(self._claims(environment="production-approval"))))
        with self.assertRaises(OidcVerificationError):
            verifier.verify(self._token())

    def test_actor_and_jti_remain_optional_but_actor_id_is_required(self):
        claims = self._claims()
        del claims["actor"]
        del claims["jti"]

        identity = self.verifier.verify(self._token(claims))

        self.assertIsNone(identity.actor)
        self.assertEqual(identity.actor_id, "12")
        self.assertIsNone(identity.token_id)

    def test_actor_id_is_kept_as_a_decimal_string(self):
        for actor_id in ("1", "12", "9876543210", "123456789012345678901234567890"):
            with self.subTest(actor_id=actor_id):
                identity = self.verifier.verify(self._token(self._claims(actor_id=actor_id)))
                self.assertEqual(identity.actor_id, actor_id)

    def test_absent_actor_id_is_rejected(self):
        claims = self._claims()
        del claims["actor_id"]

        with self.assertRaisesRegex(OidcVerificationError, "OIDC token verification failed"):
            self.verifier.verify(self._token(claims))

    def test_rejects_malformed_actor_id_without_echoing_it(self):
        invalid = (
            None,
            12,
            12.0,
            True,
            ["12"],
            {"id": "12"},
            "",
            "0",
            "012",
            "-12",
            "+12",
            "1 2",
            " 12",
            "12 ",
            "12\n",
            "12a",
            "0x1f",
            "1e3",
            "１２",
            "synthetic-actor",
        )
        for actor_id in invalid:
            with self.subTest(actor_id=actor_id):
                with self.assertRaises(OidcVerificationError) as context:
                    self.verifier.verify(self._token(self._claims(actor_id=actor_id)))
                if isinstance(actor_id, str) and actor_id.strip():
                    self.assertNotIn(actor_id.strip(), str(context.exception))

    def test_actor_login_never_stands_in_for_the_actor_identity(self):
        renamed = self.verifier.verify(self._token(self._claims(actor="renamed-login")))
        original = self.verifier.verify(self._token())
        self.assertEqual(renamed.actor_id, original.actor_id)
        self.assertNotEqual(renamed.actor, original.actor)

        claims = self._claims(actor="12")
        del claims["actor_id"]
        with self.assertRaises(OidcVerificationError):
            self.verifier.verify(self._token(claims))

        claims = self._claims()
        del claims["actor"]
        without_login = self.verifier.verify(self._token(claims))
        self.assertIsNone(without_login.actor)
        self.assertEqual(without_login.actor_id, "12")

        with self.assertRaisesRegex(OidcVerificationError, "actor ID is malformed"):
            self.verifier.verify(self._token(self._claims(actor="12", actor_id="synthetic-actor")))

    def test_token_is_never_echoed_in_rejection_message(self):
        token = self._token(self._claims(aud="wrong-audience"))

        with self.assertRaises(OidcVerificationError) as context:
            self.verifier.verify(token)
        self.assertNotIn(token, str(context.exception))


if __name__ == "__main__":
    unittest.main()
