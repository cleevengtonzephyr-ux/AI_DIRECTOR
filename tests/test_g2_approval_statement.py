"""Synthetic-data tests for the G2 canonical approval-statement schema."""

import hashlib
import sys
import unittest
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPROVAL_SERVICE_ROOT = PROJECT_ROOT / "approval_service"
if str(APPROVAL_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(APPROVAL_SERVICE_ROOT))

from approval_service.approval_statement import ApprovalStatement


def _statement(**overrides) -> ApprovalStatement:
    requested_at = 1_800_000_000_000
    values = dict(
        relying_party_id="zephyr-approval.fr",
        approver_id="approver-pseudonym-1",
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
        requested_at=requested_at,
        approval_deadline=requested_at + 600_000,
        issued_at=requested_at + 1_000,
        expires_at=requested_at + 301_000,
        max_cost_credits_per_request=None,
    )
    values.update(overrides)
    return ApprovalStatement(**values)


class ApprovalStatementTests(unittest.TestCase):
    def test_schema_is_versioned_and_keeps_unset_credit_ceiling_empty(self):
        statement = _statement()

        self.assertEqual(ApprovalStatement.VERSION, 2)
        self.assertEqual(statement.to_dict()["statement_version"], 2)
        self.assertIsNone(statement.to_dict()["max_cost_credits_per_request"])

    def test_serialization_and_statement_digest_are_stable(self):
        statement = _statement()

        self.assertEqual(statement.canonical_bytes(), _statement().canonical_bytes())
        self.assertEqual(statement.sha256(), _statement().sha256())
        self.assertEqual(len(statement.sha256()), 64)

    def test_challenge_is_32_bytes_and_bound_to_statement(self):
        original = _statement()
        changed_manifest = _statement(manifest_sha256="f" * 64)

        self.assertEqual(len(original.webauthn_challenge()), 32)
        self.assertNotEqual(original.webauthn_challenge(), changed_manifest.webauthn_challenge())

    def test_statement_is_immutable(self):
        statement = _statement()

        with self.assertRaises(FrozenInstanceError):
            statement.sha = "b" * 40

    def test_rejects_noncanonical_or_incomplete_identity_and_hashes(self):
        invalid = (
            {"relying_party_id": "other.example"},
            {"auth_method": "password"},
            {"sha": "a" * 39},
            {"manifest_sha256": "A" * 64},
            {"nonce": "not-a-random-256-bit-hex-value"},
            {"run_attempt": 2},
        )
        for overrides in invalid:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                _statement(**overrides)

    def test_rejects_duplicate_service_ids(self):
        for overrides in (
            {"authorization_id": "request-1"},
            {"approval_id": "5" * 64},
        ):
            with self.subTest(overrides=overrides), self.assertRaisesRegex(ValueError, "must be distinct"):
                _statement(**overrides)

    def test_rejects_invalid_time_windows(self):
        base = 1_800_000_000_000
        invalid = (
            {"approval_deadline": base + 599_999},
            {"issued_at": base - 1},
            {"expires_at": base + 301_001},
        )
        for overrides in invalid:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                _statement(**overrides)

    def test_rejects_numeric_credit_ceiling_until_g1_decision_changes(self):
        with self.assertRaisesRegex(ValueError, "not authorized by G1 D-14"):
            _statement(max_cost_credits_per_request=1)

    def test_run_actor_id_is_signed_into_the_bytes_digest_and_challenge(self):
        original = _statement()
        other_actor = _statement(run_actor_id="13")

        self.assertEqual(original.to_dict()["run_actor_id"], "12")
        self.assertIn(b'"run_actor_id":"12"', original.canonical_bytes())
        self.assertNotEqual(original.canonical_bytes(), other_actor.canonical_bytes())
        self.assertNotEqual(original.sha256(), other_actor.sha256())
        self.assertNotEqual(original.webauthn_challenge(), other_actor.webauthn_challenge())

    def test_challenge_uses_the_version_2_domain(self):
        statement = _statement()
        signed = statement.canonical_bytes() + b"\x00" + bytes.fromhex(statement.nonce)

        self.assertEqual(
            statement.webauthn_challenge(),
            hashlib.sha256(b"AI_DIRECTOR_APPROVAL_WEBAUTHN_V2\x00" + signed).digest(),
        )
        self.assertNotEqual(
            statement.webauthn_challenge(),
            hashlib.sha256(b"AI_DIRECTOR_APPROVAL_WEBAUTHN_V1\x00" + signed).digest(),
        )

    def test_rejects_absent_or_malformed_run_actor_id(self):
        with self.assertRaises(TypeError):
            values = _statement().to_dict()
            del values["statement_version"], values["run_actor_id"]
            ApprovalStatement(**values)

        fullwidth_twelve = chr(0xFF11) + chr(0xFF12)
        invalid = (
            None, 12, 12.0, True, b"12", "", "0", "012", "-12", "+12", " 12", "12 ",
            "12\n", "1 2", "12a", "1e3", "1.0", fullwidth_twelve, "octocat",
        )
        for run_actor_id in invalid:
            with self.subTest(run_actor_id=run_actor_id), self.assertRaises(ValueError):
                _statement(run_actor_id=run_actor_id)

    def test_version_1_statements_are_rejected(self):
        # A v1 statement had no run_actor_id: its field set no longer builds a statement.
        values = _statement().to_dict()
        self.assertEqual(values.pop("statement_version"), 2)
        values.pop("run_actor_id")
        with self.assertRaises(TypeError):
            ApprovalStatement(**values)
        # The version is fixed by the class and cannot be supplied by a caller.
        with self.assertRaises(TypeError):
            ApprovalStatement(**{**_statement().to_dict(), "statement_version": 1})

    def test_the_actor_login_is_never_part_of_the_statement(self):
        names = [field.name for field in fields(ApprovalStatement)]
        self.assertEqual([name for name in names if "actor" in name], ["run_actor_id"])
        self.assertNotIn("actor", _statement().to_dict())
        with self.assertRaises(TypeError):
            _statement(actor="octocat")


if __name__ == "__main__":
    unittest.main()
