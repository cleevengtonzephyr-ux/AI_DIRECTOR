"""Synthetic-data tests for the G2 canonical approval-statement schema."""

import sys
import unittest
from dataclasses import FrozenInstanceError
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

        self.assertEqual(statement.to_dict()["statement_version"], 1)
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


if __name__ == "__main__":
    unittest.main()
