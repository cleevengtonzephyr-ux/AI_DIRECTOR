"""
Tests -- Recovery & Reconciliation Boundary Audit (Phase P3.38).

The large majority of the crash/UNKNOWN/restart matrix this phase
asks for is already exhaustively covered elsewhere in this suite (see
the P3.38 report's Section 14 for the full citation list --
tests/test_phase_p2_16_concurrency_audit.py,
tests/test_phase_p2_20_crash_recovery_lock.py,
tests/test_phase_p2_21_activation_contract.py,
tests/test_mission_identity_contract.py). This file adds ONLY the
genuinely new angles those did not already cover:

1. Cross-request UNKNOWN isolation -- marking request A UNKNOWN must
   not affect request B's evaluation in any way.
2. Cross-mission UNKNOWN -- mission_id is structurally irrelevant to
   UNKNOWN determination (proven, not merely asserted).
3. UNKNOWN + authorization/activation expiry interaction (P3.38
   Section 11's central temporal question).
4. Reconciliation-capability absence, proven executably: ExecutedRequestStore
   has no request_id -> job_id mapping and no method to programmatically
   clear an UNKNOWN entry (only is_executed/mark_executed/is_unknown/
   mark_unknown exist) -- UNKNOWN can only ever be cleared by a human
   editing the persisted store directly, never by any in-band code path.
5. Reconciliation vs retry distinction: repeated evaluate() calls after
   UNKNOWN always return EXECUTION_STATE_UNKNOWN, never APPROVED, no
   matter how many times retried -- retry alone can never resolve
   UNKNOWN, confirming reconciliation (external evidence) and retry
   (a new attempt) are not interchangeable in this codebase.

Fully offline: no network, no Higgsfield CLI, always MockHiggsfieldProvider.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.executed_request_store import FileExecutedRequestStore
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from agents.release_candidate_identity_lock import ReleaseCandidateIdentityLock, VIDEO_005_RELEASE_CANDIDATE
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.types import MediaReference

C = VIDEO_005_RELEASE_CANDIDATE

REAL_AVATAR_PATH = PROJECT_ROOT / "assets" / "zephyr" / "avatar" / "avatar_master.png"
REAL_FACE_PATH = PROJECT_ROOT / "assets" / "zephyr" / "references" / "mon avatar habille.png"


def _real_prompt() -> str:
    from agents.prompt_assembly_system import PromptAssemblySystem

    return PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id)


def _conforming_request(**overrides) -> GenerationRequest:
    defaults = dict(
        request_id=C.request_id, job_type=C.job_type, prompt=_real_prompt(),
        duration=C.duration, resolution=C.resolution, aspect_ratio=C.aspect_ratio,
        approved=True,
        start_image=MediaReference(role="master_avatar", source=str(REAL_AVATAR_PATH), sha256=None),
        image_references=(MediaReference(role="face_reference", source=str(REAL_FACE_PATH), sha256=None),),
        real_generation_authorization=RealGenerationAuthorization(request_id=C.request_id, authorized_by_human=True),
    )
    defaults.update(overrides)
    return GenerationRequest(**defaults)


class _StoreMixin:
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p3_38_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.store = FileExecutedRequestStore(self._tmp / "executed_requests.json")

    def _gate(self, available_credits=1000.0):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=available_credits)
        identity_lock = ReleaseCandidateIdentityLock(C)
        return GenerationApprovalGate(provider, executed_request_store=self.store, identity_lock=identity_lock)


# ------------------------------------------------------------------
# 1. CROSS-REQUEST UNKNOWN ISOLATION
# ------------------------------------------------------------------


class CrossRequestUnknownIsolationTests(_StoreMixin, unittest.TestCase):
    """Isolation is tested directly at the store layer -- the actual
    boundary where cross-request contamination would have to occur.
    (Testing this via Gate.evaluate() with a second, non-canonical
    request_id is not meaningful on its own: Video 005's Release
    Candidate Identity Lock rejects any non-"005" request_id as
    INVALID_REQUEST before the replay/UNKNOWN check is ever reached --
    confirmed directly by test_gate_level_rejection_order_independent_
    of_unrelated_unknown_entries below -- so only the store's own
    per-key isolation is the meaningful thing to prove here.)"""

    def test_request_A_marked_unknown_does_not_make_request_B_unknown(self):
        self.store.mark_unknown("request-A", reason="simulated crash for A")
        self.assertTrue(self.store.is_unknown("request-A"))
        self.assertFalse(self.store.is_unknown("request-B"))
        self.assertFalse(self.store.is_executed("request-B"))

    def test_request_A_executed_does_not_make_request_B_executed(self):
        self.store.mark_executed("request-A")
        self.assertTrue(self.store.is_executed("request-A"))
        self.assertFalse(self.store.is_executed("request-B"))
        self.assertFalse(self.store.is_unknown("request-B"))

    def test_gate_level_rejection_order_independent_of_unrelated_unknown_entries(self):
        """An unrelated request_id being UNKNOWN in the same store must
        never surface in, or alter, a different (here: invalid,
        non-canonical) request's own rejection reasons."""
        self.store.mark_unknown("request-A", reason="simulated crash for A")
        gate = self._gate()
        request_b = _conforming_request(request_id="request-B")
        approval_b = gate.evaluate(request_b)
        self.assertNotEqual(approval_b.decision, GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN)
        self.assertFalse(any("request-A" in r for r in approval_b.reasons))


# ------------------------------------------------------------------
# 2. CROSS-MISSION UNKNOWN -- mission_id is structurally irrelevant
# ------------------------------------------------------------------


class CrossMissionUnknownTests(_StoreMixin, unittest.TestCase):
    def test_unknown_determination_is_identical_regardless_of_mission_id(self):
        """UNKNOWN is a property of request_id alone -- Gate.evaluate()
        has no mission_id parameter to even accept (re-confirmed
        directly here, not assumed from a prior phase)."""
        import inspect

        self.assertNotIn("mission_id", inspect.signature(GenerationApprovalGate.evaluate).parameters)

        self.store.mark_unknown(C.request_id, reason="simulated crash")
        gate = self._gate()
        request = _conforming_request()  # no mission_id field exists on GenerationRequest at all
        approval = gate.evaluate(request)
        self.assertEqual(approval.decision, GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN)


# ------------------------------------------------------------------
# 3. UNKNOWN + AUTHORIZATION/ACTIVATION EXPIRY INTERACTION (Section 11)
# ------------------------------------------------------------------


class UnknownPlusExpiryInteractionTests(_StoreMixin, unittest.TestCase):
    def test_unknown_blocks_even_with_a_freshly_reauthorized_request(self):
        """Central question of Section 11: once UNKNOWN, does a brand
        new (still-valid, not-expired) authorization/activation change
        anything? Answer, proven here: NO -- UNKNOWN is checked before
        authorization is even considered, so nothing downstream of it
        (fresh or expired) can ever un-block it."""
        self.store.mark_unknown(C.request_id, reason="simulated crash")
        gate = self._gate()

        fresh_request = _conforming_request(
            real_generation_authorization=RealGenerationAuthorization(
                request_id=C.request_id, authorized_by_human=True,
            )
        )
        approval = gate.evaluate(fresh_request)
        self.assertEqual(approval.decision, GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN)
        # A second, independently fresh authorization object changes nothing.
        another_fresh_request = _conforming_request(
            real_generation_authorization=RealGenerationAuthorization(
                request_id=C.request_id, authorized_by_human=True,
            )
        )
        approval_2 = gate.evaluate(another_fresh_request)
        self.assertEqual(approval_2.decision, GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN)

    def test_retry_alone_never_clears_unknown_no_matter_how_many_attempts(self):
        """Distinguishes RETRY (a new attempt) from RECONCILIATION
        (external evidence establishing the truth) -- Section 9. Ten
        repeated evaluate() calls must all return UNKNOWN identically;
        nothing about repetition itself resolves it."""
        self.store.mark_unknown(C.request_id, reason="simulated crash")
        gate = self._gate()
        request = _conforming_request()
        decisions = {gate.evaluate(request).decision for _ in range(10)}
        self.assertEqual(decisions, {GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN})


# ------------------------------------------------------------------
# 4. RECONCILIATION CAPABILITY ABSENCE (Section 7/9, proven executably)
# ------------------------------------------------------------------


class ReconciliationCapabilityAbsenceTests(_StoreMixin, unittest.TestCase):
    def test_executed_request_store_job_id_mapping_is_trace_only(self):
        """Phase P3.89 (GAP #1 closed): mark_executed()/mark_unknown()
        now persist the job_id and recorded_job_id() reads it back --
        but it is a trace only: recording or reading it never clears
        or resolves an UNKNOWN entry (P3.38 finding unchanged)."""
        import inspect

        self.assertIn("job_id", inspect.signature(self.store.mark_executed).parameters)
        self.assertIn("job_id", inspect.signature(self.store.mark_unknown).parameters)
        self.store.mark_unknown("005", reason="r", job_id="job-1")
        self.assertEqual(self.store.recorded_job_id("005"), "job-1")
        self.assertTrue(self.store.is_unknown("005"))

    def test_executed_request_store_has_no_programmatic_clear_method(self):
        """Only is_executed/mark_executed/is_unknown/mark_unknown exist
        (plus, since P3.89, the read-only recorded_job_id) -- no
        clear/resolve/acknowledge/remove/delete method of any kind. An
        UNKNOWN entry can only be cleared by a human editing the
        persisted JSON file directly, never in-band."""
        public_methods = {
            name for name in dir(self.store)
            if not name.startswith("_") and callable(getattr(self.store, name))
        }
        # P3.91 : `in_flight` (write-ahead) refuse toute requête déjà
        # enregistrée et ne peut annuler que son propre marqueur -- il
        # ne retire jamais un UNKNOWN existant (prouvé par
        # tests/test_p3_91_execution_safety_hardening.py).
        self.assertEqual(
            public_methods,
            {"is_executed", "mark_executed", "is_unknown", "mark_unknown", "recorded_job_id",
             "in_flight"},
        )

    def test_no_reconciliation_or_recovery_module_exists(self):
        for name in ("reconciliation", "recovery", "reconcile"):
            self.assertFalse(
                list((PROJECT_ROOT / "agents").glob(f"*{name}*.py")),
                f"unexpected module matching '*{name}*.py' -- no such mechanism should exist yet",
            )


if __name__ == "__main__":
    unittest.main()
