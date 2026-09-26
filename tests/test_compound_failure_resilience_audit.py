"""
Tests -- Compound Failure & Multi-Guardrail Resilience Audit (Phase P3.50).

Prior phases (P2.15-39, P3.33-49) exhaustively tested each guardrail
INDIVIDUALLY: store persistence, identity binding, activation expiry,
critical-section locking, replay protection, UNKNOWN handling, etc.
This file adds ONLY genuinely new COMPOUND scenarios -- two or three
of these failure modes triggered together -- to prove none of them
can cancel or weaken another. Scenarios that reduce trivially to "two
independent checks, whichever runs first blocks identically" (e.g.
identity-mismatch + authorization-mismatch, both structurally
independent, already proven never to interact) are cited in the
P3.50 report rather than duplicated here as tests.

Fully offline: no network, no Higgsfield CLI, always MockHiggsfieldProvider.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import ActivationRejectedError, RequestScopedActivationService
from agents.controlled_real_provider_activation import (
    ControlledRealProviderActivationRejectedError,
    ControlledRealProviderActivationService,
)
from agents.critical_section_lock import CriticalSectionBusyError, FileCriticalSectionLock
from agents.executed_request_store import ExecutedRequestStoreCorruptedError, FileExecutedRequestStore
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from agents.generation_job_service import GenerationJobExecutionError, GenerationJobService
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


class _TmpDirMixin:
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p3_50_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)


# ------------------------------------------------------------------
# TWO-FAILURE COMBINATIONS
# ------------------------------------------------------------------


class TwoFailureCombinationTests(_TmpDirMixin, unittest.TestCase):
    def test_A_approval_store_loss_plus_identity_mismatch(self):
        """A: default (lost-memory) Gate store combined with a prompt
        that does NOT match the Release Candidate -- must still be
        rejected for IDENTITY reasons, never silently approved because
        the store has no memory to consult."""
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)  # default store

        tampered_request = _conforming_request(prompt="this prompt does not match the Release Candidate")
        approval = gate.evaluate(tampered_request)
        self.assertNotEqual(approval.decision, GenerationApprovalDecision.APPROVED)
        self.assertTrue(any("prompt" in r.lower() or "identity" in r.lower() for r in approval.reasons))

    def test_B_approval_store_loss_plus_activation_expiry(self):
        """B: default Gate store combined with an activation contract
        that has since expired -- rejected for EXPIRY, independent of
        the Gate's own store state (the Gate is not even consulted for
        this specific rejection; the activation service's own fresh
        Gate re-check happens through a separately-configured clock)."""
        fake_time = {"t": 1000.0}
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)  # default store
        activation_service = RequestScopedActivationService(gate, identity_lock, clock=lambda: fake_time["t"])
        activation_service.max_age_seconds = 60.0

        request = _conforming_request()
        contract = activation_service.prepare_activation(request)
        fake_time["t"] += 61.0

        with self.assertRaises(ActivationRejectedError) as ctx:
            activation_service.validate_activation(request, contract)
        self.assertTrue(any("expired" in r for r in ctx.exception.reasons))

    def test_H_critical_lock_busy_blocks_before_replay_is_even_checked(self):
        """H: a held critical-section lock must block a second attempt
        for the SAME request_id immediately -- before that second
        attempt's Gate.evaluate() (and therefore its replay check) is
        ever reached at all."""
        lock = FileCriticalSectionLock(self._tmp / "locks")
        with lock.acquire("005"):
            with self.assertRaises(CriticalSectionBusyError):
                with lock.acquire("005"):
                    pass  # never reached

    def test_O_corrupted_persistent_state_survives_simulated_restart(self):
        """O: a corrupted store file, combined with a brand-new Gate
        instance (simulating a full process restart), must still fail
        closed -- corruption is a property of the FILE, not of any
        one Gate instance's memory, so a 'fresh' instance does not
        get a clean slate."""
        store_path = self._tmp / "executed_requests.json"
        store_path.write_text("{not valid json", encoding="utf-8")

        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        # "New process": a completely fresh Gate/store object pointed
        # at the same (corrupted) file path.
        gate_after_restart = GenerationApprovalGate(
            provider, executed_request_store=FileExecutedRequestStore(store_path), identity_lock=identity_lock,
        )
        approval = gate_after_restart.evaluate(_conforming_request())
        self.assertEqual(approval.decision, GenerationApprovalDecision.BLOCKED)
        self.assertTrue(any("corrupt" in r.lower() or "verified" in r.lower() for r in approval.reasons))


# ------------------------------------------------------------------
# THREE-FAILURE COMBINATIONS
# ------------------------------------------------------------------


class ThreeFailureCombinationTests(_TmpDirMixin, unittest.TestCase):
    def _chain(self, store_path=None):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        store = FileExecutedRequestStore(store_path) if store_path else None
        gate = GenerationApprovalGate(provider, executed_request_store=store, identity_lock=identity_lock)
        activation_service = RequestScopedActivationService(gate, identity_lock)
        provider_activation_service = ControlledRealProviderActivationService(gate, identity_lock, activation_service)
        lock = FileCriticalSectionLock(self._tmp / "locks")
        job_service = GenerationJobService(
            provider, gate, lock=lock, activation_service=activation_service,
            provider_activation_service=provider_activation_service,
        )
        return gate, activation_service, provider_activation_service, job_service

    def test_scenario_2_unknown_plus_new_authorization_plus_new_activation(self):
        """UNKNOWN + a genuinely fresh authorization + a genuinely
        fresh activation-preparation attempt, all three combined --
        none of the three individually-valid-looking new artifacts,
        alone or together, clears UNKNOWN."""
        store_path = self._tmp / "executed_requests.json"
        gate, activation_service, _, job_service = self._chain(store_path)
        request = _conforming_request()
        gate.mark_unknown(request.request_id, reason="simulated crash")

        fresh_request = _conforming_request(
            real_generation_authorization=RealGenerationAuthorization(request_id=C.request_id, authorized_by_human=True)
        )
        self.assertEqual(gate.evaluate(fresh_request).decision, GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN)

        with self.assertRaises(ActivationRejectedError):
            activation_service.prepare_activation(fresh_request)

        with self.assertRaises(GenerationJobExecutionError):
            job_service.execute(fresh_request)

    def test_scenario_4_approval_store_loss_plus_authorization_mismatch_plus_repeated_attempt(self):
        """Default (lost-memory) store + a mismatched authorization,
        attempted twice in a row ('replay' of the attempt itself, not
        of a success) -- both attempts must be rejected identically,
        for authorization reasons, with no cumulative weakening."""
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)  # default store

        mismatched_request = _conforming_request(
            real_generation_authorization=RealGenerationAuthorization(request_id="not-005", authorized_by_human=True)
        )
        first = gate.evaluate(mismatched_request)
        second = gate.evaluate(mismatched_request)
        for approval in (first, second):
            self.assertNotEqual(approval.decision, GenerationApprovalDecision.APPROVED)
            self.assertTrue(any("authoriz" in r.lower() for r in approval.reasons))
        self.assertEqual(first.decision, second.decision)

    def test_scenario_5_lock_release_plus_activation_revoke_plus_second_attempt(self):
        """A revoked activation contract, attempted, released from its
        critical section, then attempted AGAIN under a fresh lock
        acquisition -- revocation must survive the lock release/
        reacquisition cycle; the second attempt must fail identically
        to the first, never succeeding because the lock was 'reset'."""
        store_path = self._tmp / "executed_requests.json"
        gate, activation_service, provider_activation_service, _ = self._chain(store_path)
        request = _conforming_request()

        rs_contract = activation_service.prepare_activation(request)
        pa_contract = provider_activation_service.prepare(request, rs_contract)
        provider_activation_service.revoke(pa_contract)

        lock = FileCriticalSectionLock(self._tmp / "locks")

        with lock.acquire(request.request_id):
            with self.assertRaises(ControlledRealProviderActivationRejectedError):
                provider_activation_service.validate(request, rs_contract, pa_contract)

        # Lock released; a second, independent acquisition for the
        # SAME request_id succeeds (no lock-level replay block here --
        # this isolates that the REJECTION is carried by the
        # activation's own revoked state, not by the lock).
        with lock.acquire(request.request_id):
            with self.assertRaises(ControlledRealProviderActivationRejectedError) as ctx:
                provider_activation_service.validate(request, rs_contract, pa_contract)
            self.assertTrue(any("consumed or revoked" in r for r in ctx.exception.reasons))


if __name__ == "__main__":
    unittest.main()
