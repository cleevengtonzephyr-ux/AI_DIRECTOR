"""
Tests — Phase B : expiration de l'autorisation humaine
(docs/phase_a_real_generation_decision.md, condition 2).

`GenerationApprovalGate` refuse une `RealGenerationAuthorization` dont
`authorized_at` est absent, invalide, sans fuseau, futur ou plus vieux
que 300 secondes (âge == 300 s accepté). Horloge injectée : aucun test
ne dépend de l'heure réelle, sauf le contrôle du défaut. Uniquement
`MockHiggsfieldProvider` : aucun appel Higgsfield, aucun create_job réel.
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from agents.generation_job_service import GenerationJobExecutionError, GenerationJobService
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider

NOW = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)


def _auth(authorized_at, request_id="005"):
    return RealGenerationAuthorization(
        request_id=request_id, authorized_by_human=True, authorized_at=authorized_at
    )


def _issued(seconds_ago):
    return (NOW - timedelta(seconds=seconds_ago)).isoformat()


def _request(auth, approved=True, request_id="005"):
    return GenerationRequest(
        request_id=request_id,
        job_type="seedance_2_0",
        prompt="prompt de test",
        duration=5,
        resolution="720p",
        aspect_ratio="9:16",
        approved=approved,
        real_generation_authorization=auth,
    )


def _gate(provider=None):
    provider = provider or MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
    return GenerationApprovalGate(provider, clock=lambda: NOW)


class TestFreshAuthorizationIsAccepted(unittest.TestCase):
    def test_the_limit_is_300_seconds(self):
        self.assertEqual(GenerationApprovalGate.MAX_AUTHORIZATION_AGE_SECONDS, 300.0)

    def test_fresh_authorization_is_approved(self):
        for seconds_ago in (0, 1, 60, 299):
            with self.subTest(seconds_ago=seconds_ago):
                result = _gate().evaluate(_request(_auth(_issued(seconds_ago))))
                self.assertEqual(result.decision, GenerationApprovalDecision.APPROVED)

    def test_exactly_300_seconds_is_still_accepted(self):
        result = _gate().evaluate(_request(_auth(_issued(300))))
        self.assertEqual(result.decision, GenerationApprovalDecision.APPROVED)

    def test_non_utc_offset_is_accepted_when_fresh(self):
        issued = (NOW - timedelta(seconds=30)).astimezone(timezone(timedelta(hours=-3)))
        result = _gate().evaluate(_request(_auth(issued.isoformat())))
        self.assertEqual(result.decision, GenerationApprovalDecision.APPROVED)

    def test_default_clock_accepts_a_just_created_authorization(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        auth = RealGenerationAuthorization(request_id="005", authorized_by_human=True)
        result = GenerationApprovalGate(provider).evaluate(_request(auth))
        self.assertEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestRefusedAuthorizationNeverApproves(unittest.TestCase):
    CASES = {
        "one microsecond past the limit": (NOW - timedelta(seconds=300, microseconds=1)).isoformat(),
        "301 seconds old": _issued(301),
        "one hour old": _issued(3600),
        "one second in the future": _issued(-1),
        "one hour in the future": _issued(-3600),
        "not a timestamp": "not-a-timestamp",
        "empty string": "",
        "blank string": "   ",
        "missing (None)": None,
        "naive timestamp (no timezone)": NOW.replace(tzinfo=None).isoformat(),
    }

    def test_known_cost_path_never_approves(self):
        for label, authorized_at in self.CASES.items():
            with self.subTest(case=label):
                result = _gate().evaluate(_request(_auth(authorized_at)))
                self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)
                self.assertTrue(any("authorized_at" in r or "expired" in r for r in result.reasons), result.reasons)

    def test_unknown_cost_path_never_approves(self):
        for label, authorized_at in self.CASES.items():
            with self.subTest(case=label):
                result = _gate(MockHiggsfieldProvider(cost_per_job=None)).evaluate(_request(_auth(authorized_at)))
                self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)

    def test_expired_reason_is_explicit(self):
        result = _gate().evaluate(_request(_auth(_issued(301))))
        self.assertTrue(any("expired" in r for r in result.reasons), result.reasons)

    def test_expired_authorization_never_reaches_create_job(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = _gate(provider)
        with self.assertRaises(GenerationJobExecutionError):
            GenerationJobService(provider, gate).execute(_request(_auth(_issued(301))))
        self.assertEqual(len(provider._jobs), 0)
        self.assertFalse(gate.is_already_executed("005"))

    def test_naive_gate_clock_is_refused_not_crashed(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider, clock=lambda: NOW.replace(tzinfo=None))
        result = gate.evaluate(_request(_auth(_issued(10))))
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestOtherRequirementsStillApplyToAFreshAuthorization(unittest.TestCase):
    def test_explicit_approval_is_still_required(self):
        result = _gate().evaluate(_request(_auth(_issued(10)), approved=False))
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)

    def test_authorization_stays_bound_to_the_exact_request(self):
        result = _gate().evaluate(_request(_auth(_issued(10), request_id="other"), request_id="005"))
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)

    def test_authorized_by_human_must_be_true(self):
        auth = RealGenerationAuthorization(request_id="005", authorized_by_human=False, authorized_at=_issued(10))
        result = _gate().evaluate(_request(auth))
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


if __name__ == "__main__":
    unittest.main()
