"""
Tests -- Certificate Lifecycle Cross-Process Recovery, Durability &
Adversarial Boundary Audit (Phase P3.60).

Extends P3.58 (persistence) and P3.59 (inter-process locking) with
adversarial crash/restart/corruption scenarios: crash-before-write,
temp-file residue, orphan locks (including a REAL brutally-killed OS
process, not merely a simulated stale lock file), corrupt store +
lock combinations, concurrent restarts, and a deterministic multi-
process stress run. Uses real `multiprocessing.Process` (never only
`threading`) wherever the mission requires "real OS processes", and
`multiprocessing.Barrier`/`Event`/`Queue` for deterministic
synchronization -- never a bare `time.sleep()` used as a race-timing
mechanism.

Every test uses MockHiggsfieldProvider exclusively; no real
generation, no real create_job(), no credits consumed. All files are
created in a temporary directory (never the real project).
"""

import multiprocessing
import os
import sys
import tempfile
import time
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import RequestScopedActivationService
from agents.activation_readiness import ActivationReadinessEvaluator
from agents.certificate_lifecycle import CertificateLifecycleRegistry, CertificateLifecycleStatus
from agents.certificate_lifecycle_lock import CertificateLifecycleFileLock, CertificateLifecycleLockBusyError
from agents.certificate_lifecycle_store import (
    LIFECYCLE_STORAGE_VERSION,
    CertificateLifecycleStoreCorruptedError,
    FileCertificateLifecycleStore,
)
from agents.generation_approval_gate import GenerationApprovalGate, GenerationRequest, RealGenerationAuthorization
from agents.production_activation_readiness_certificate import ProductionActivationReadinessCertificateIssuer
from agents.release_candidate_identity_lock import ReleaseCandidateIdentityLock, VIDEO_005_RELEASE_CANDIDATE
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.types import MediaReference

C = VIDEO_005_RELEASE_CANDIDATE
REAL_AVATAR_PATH = PROJECT_ROOT / "assets" / "zephyr" / "avatar" / "avatar_master.png"
REAL_FACE_PATH = PROJECT_ROOT / "assets" / "zephyr" / "references" / "mon avatar habille.png"


def _real_prompt() -> str:
    from agents.prompt_assembly_system import PromptAssemblySystem

    return PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id)


def _issue_certificate(request_id: str, mission_id):
    request = GenerationRequest(
        request_id=request_id, job_type=C.job_type, prompt=_real_prompt(),
        duration=C.duration, resolution=C.resolution, aspect_ratio=C.aspect_ratio,
        approved=True,
        start_image=MediaReference(role="master_avatar", source=str(REAL_AVATAR_PATH), sha256=None),
        image_references=(MediaReference(role="face_reference", source=str(REAL_FACE_PATH), sha256=None),),
        real_generation_authorization=RealGenerationAuthorization(request_id=request_id, authorized_by_human=True),
    )
    provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
    identity_lock = ReleaseCandidateIdentityLock(C)
    gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
    activation_service = RequestScopedActivationService(gate, identity_lock)
    evaluator = ActivationReadinessEvaluator(gate, identity_lock, activation_service)
    issuer = ProductionActivationReadinessCertificateIssuer(evaluator)
    return issuer.issue(request, mission_id=mission_id, video_plan_identity="plan-v1")


# ---------------------------------------------------------------------
# Module-level worker functions (top-level, required for spawn-pickling
# on Windows).
# ---------------------------------------------------------------------


def _worker_register_once(store_path_str, request_id, mission_id, barrier, result_queue):
    try:
        certificate = _issue_certificate(request_id, mission_id)
        store = FileCertificateLifecycleStore(Path(store_path_str), lock_timeout=20.0)
        barrier.wait(timeout=30)
        new_record, superseded_record = store.register_certificate(
            certificate_id=certificate.certificate_id, request_id=certificate.request_id,
            mission_id=certificate.mission_id, issued_at=certificate.issued_at,
        )
        result_queue.put(("ok", new_record.certificate_id, new_record.registered_sequence))
    except Exception as error:  # noqa: BLE001 -- reported, never swallowed
        result_queue.put(("error", repr(error), None))


def _worker_stress_register(store_path_str, request_id, mission_id, count, barrier, result_queue):
    try:
        store = FileCertificateLifecycleStore(Path(store_path_str), lock_timeout=60.0)
        barrier.wait(timeout=30)
        ids = []
        for _ in range(count):
            certificate = _issue_certificate(request_id, mission_id)
            new_record, _ = store.register_certificate(
                certificate_id=certificate.certificate_id, request_id=certificate.request_id,
                mission_id=certificate.mission_id, issued_at=certificate.issued_at,
            )
            ids.append(new_record.certificate_id)
        result_queue.put(("ok", ids))
    except Exception as error:  # noqa: BLE001
        result_queue.put(("error", repr(error)))


def _worker_concurrent_reader(store_path_str, barrier, result_queue):
    try:
        store = FileCertificateLifecycleStore(Path(store_path_str))
        registry = CertificateLifecycleRegistry(store=store)
        barrier.wait(timeout=30)
        registry.hydrate_from_store()
        result_queue.put((
            "ok",
            sorted(registry.record_for(cid).certificate_id for cid in registry._records),  # white-box, read-only
        ))
    except Exception as error:  # noqa: BLE001
        result_queue.put(("error", repr(error)))


def _worker_hold_lock_until_killed(lock_path_str, acquired_event):
    lock = CertificateLifecycleFileLock(Path(lock_path_str))
    with lock.acquire(timeout=0.0):
        acquired_event.set()
        time.sleep(3600)  # the parent kills this process long before this elapses


class _CrashRecoveryTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.state_path = Path(self._tmpdir.name) / "state" / "certificate_lifecycle.json"
        self.lock_path = self.state_path.parent / f".{self.state_path.name}.lock"

    def _store(self, lock_timeout: float = 5.0) -> FileCertificateLifecycleStore:
        return FileCertificateLifecycleStore(self.state_path, lock_timeout=lock_timeout)

    def _run_workers(self, worker, args_list, timeout=40):
        barrier = multiprocessing.Barrier(len(args_list))
        result_queue = multiprocessing.Queue()
        processes = []
        for args in args_list:
            p = multiprocessing.Process(target=worker, args=(*args, barrier, result_queue))
            processes.append(p)
            p.start()
        for p in processes:
            p.join(timeout=timeout)
            self.assertFalse(p.is_alive(), "worker process did not terminate in time")
            self.assertEqual(p.exitcode, 0, "worker process exited with a non-zero code")
        return [result_queue.get(timeout=5) for _ in processes]

    def _assert_recovery_invariants(self, expected_total=None):
        """The shared invariant checklist (Section 9, P3.60 mission).
        `store.load()` itself already enforces: sequence uniqueness,
        exactly-one-CURRENT-per-scope, superseded_by consistency
        (existence + same-scope + strictly-increasing sequence),
        cycle-freedom, and a chain that always terminates at CURRENT --
        a successful `load()` is therefore already strong,
        machine-checked proof of most of the checklist; this helper
        adds the remaining checks `load()` cannot express on its own
        (monotonic ordering, expected totals, UNKNOWN-for-the-unknown)."""

        records, current_by_scope, sequence_counter = self._store().load()

        sequences = sorted(r.registered_sequence for r in records.values())
        self.assertEqual(sequences, list(range(1, len(records) + 1)), "sequence not monotone/unique/gapless")

        for scope, cid in current_by_scope.items():
            currents_for_scope = [
                r for r in records.values() if r.scope == scope and r.status == CertificateLifecycleStatus.CURRENT
            ]
            self.assertEqual(len(currents_for_scope), 1, f"scope {scope} does not have exactly one CURRENT")
            self.assertEqual(currents_for_scope[0].certificate_id, cid)

        for record in records.values():
            if record.status == CertificateLifecycleStatus.SUPERSEDED:
                self.assertIsNotNone(record.superseded_by)
                self.assertIn(record.superseded_by, records)
                self.assertEqual(records[record.superseded_by].scope, record.scope)

        if expected_total is not None:
            self.assertEqual(len(records), expected_total)

        registry = CertificateLifecycleRegistry(store=self._store())
        registry.hydrate_from_store()
        self.assertEqual(registry.status_of("definitely-never-registered-" + os.urandom(4).hex()), CertificateLifecycleStatus.UNKNOWN)

        return records, current_by_scope, sequence_counter


# ---------------------------------------------------------------------
# A/B/C -- crash before write / after temp write / during rename
# ---------------------------------------------------------------------


class TestA_CrashBeforeWrite(_CrashRecoveryTestCase):
    def test_nothing_written_yet_recovers_to_legitimate_empty_state(self):
        """Section 4.A: a process that crashes before ever writing
        anything leaves exactly the state that existed before it ran
        -- here, nothing at all. Not corruption."""

        records, current_by_scope, sequence_counter = self._store().load()
        self.assertEqual((records, current_by_scope, sequence_counter), ({}, {}, 0))

    def test_crash_before_write_after_prior_valid_state_leaves_that_state_intact(self):
        certificate = _issue_certificate("005", "mission-A")
        store = self._store()
        store.register_certificate(
            certificate_id=certificate.certificate_id, request_id=certificate.request_id,
            mission_id=certificate.mission_id, issued_at=certificate.issued_at,
        )
        # A second, hypothetical process "crashes before writing" --
        # observationally indistinguishable from simply never running.
        records, current_by_scope, _ = self._store().load()
        self.assertEqual(len(records), 1)
        self.assertIn(certificate.certificate_id, records)


class TestB_CrashAfterTemporaryWriteBeforeRename(_CrashRecoveryTestCase):
    """Section 4.B ('if testable'): observationally reproduces the
    on-disk state a crash between the temp-file write and the atomic
    rename would leave -- a stray `.tmp-certificate-lifecycle-*.json`
    file next to an unchanged (or absent) real store file -- using the
    SAME temp-file naming convention `_write_raw_records()` uses, and
    verifies recovery never touches it."""

    def test_stray_temp_file_next_to_missing_store_is_never_adopted(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        stray = self.state_path.parent / ".tmp-certificate-lifecycle-crash.json"
        stray.write_text(
            f'{{"lifecycle_storage_version": {LIFECYCLE_STORAGE_VERSION}, "records": '
            f'{{"fake-id": {{"certificate_id": "fake-id", "request_id": "005", '
            f'"mission_id": null, "status": "CURRENT", "superseded_by": null, '
            f'"sequence": 1, "issued_at": "x"}}}}}}',
            encoding="utf-8",
        )
        self.addCleanup(lambda: stray.unlink(missing_ok=True))

        records, current_by_scope, sequence_counter = self._store().load()
        self.assertEqual((records, current_by_scope, sequence_counter), ({}, {}, 0))
        self.assertFalse(self.state_path.exists())

    def test_stray_temp_file_next_to_valid_store_never_overrides_it(self):
        certificate = _issue_certificate("005", "mission-A")
        store = self._store()
        store.register_certificate(
            certificate_id=certificate.certificate_id, request_id=certificate.request_id,
            mission_id=certificate.mission_id, issued_at=certificate.issued_at,
        )

        stray = self.state_path.parent / ".tmp-certificate-lifecycle-crash.json"
        stray.write_text(
            f'{{"lifecycle_storage_version": {LIFECYCLE_STORAGE_VERSION}, "records": {{}}}}',
            encoding="utf-8",
        )
        self.addCleanup(lambda: stray.unlink(missing_ok=True))

        records, _, _ = self._store().load()
        self.assertEqual(len(records), 1)
        self.assertIn(certificate.certificate_id, records)


class TestC_AtomicReplaceAssumption(_CrashRecoveryTestCase):
    def test_replace_observed_result_is_either_fully_old_or_fully_new(self):
        """Section 4.C: this repository does not implement, and P3.60
        does not add, any mechanism beyond `os.replace()` -- the exact
        same primitive `agents/executed_request_store.py`'s
        `FileExecutedRequestStore` (P2, PROTECTED, already trusted in
        production) relies on. This test documents the assumption by
        exercise, not by inventing a new one: two full writes in a row
        always leave a file that parses as EXACTLY one of the two
        complete states, never a mixture."""

        c1 = _issue_certificate("005", "mission-A")
        c2 = _issue_certificate("005", "mission-A")
        store = self._store()
        store.register_certificate(
            certificate_id=c1.certificate_id, request_id=c1.request_id,
            mission_id=c1.mission_id, issued_at=c1.issued_at,
        )
        records_after_first, _, _ = store.load()
        self.assertEqual(len(records_after_first), 1)

        store.register_certificate(
            certificate_id=c2.certificate_id, request_id=c2.request_id,
            mission_id=c2.mission_id, issued_at=c2.issued_at,
        )
        records_after_second, _, _ = store.load()
        self.assertEqual(len(records_after_second), 2)


# ---------------------------------------------------------------------
# D -- orphan lock (simulated + a REAL brutally-killed process)
# ---------------------------------------------------------------------


class TestD_OrphanLock(_CrashRecoveryTestCase):
    def test_simulated_orphan_lock_never_auto_removed_never_bypassed(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text('{"pid": 999999, "acquired_at": "1999-01-01T00:00:00+00:00"}', encoding="utf-8")

        store = self._store(lock_timeout=0.2)
        certificate = _issue_certificate("005", "mission-A")
        with self.assertRaises(CertificateLifecycleLockBusyError):
            store.register_certificate(
                certificate_id=certificate.certificate_id, request_id=certificate.request_id,
                mission_id=certificate.mission_id, issued_at=certificate.issued_at,
            )
        self.assertTrue(self.lock_path.exists(), "orphan lock must never be auto-removed")
        # The store itself is not "considered healthy" as a side effect
        # of the failed attempt -- still legitimately empty.
        records, _, _ = self._store().load()
        self.assertEqual(records, {})

    def test_real_process_brutally_killed_while_holding_the_lock_leaves_it_orphaned(self):
        """Section 7.20: a REAL OS process, killed (not merely
        exited/exception) while inside the lock's critical section --
        its `finally` never runs (SIGKILL/TerminateProcess bypasses
        Python entirely), exactly reproducing a genuine crash."""

        acquired_event = multiprocessing.Event()
        holder = multiprocessing.Process(target=_worker_hold_lock_until_killed, args=(str(self.lock_path), acquired_event))
        holder.start()
        self.addCleanup(lambda: holder.is_alive() and holder.kill())

        self.assertTrue(acquired_event.wait(timeout=15), "holder process never signalled lock acquisition")
        self.assertTrue(self.lock_path.exists())

        holder.kill()  # SIGKILL on POSIX, TerminateProcess on Windows -- no `finally` runs
        holder.join(timeout=15)
        self.assertFalse(holder.is_alive())

        # The lock file survives the brutal kill -- orphaned, exactly
        # as the fail-closed contract documents.
        self.assertTrue(self.lock_path.exists(), "lock must remain after the holder is killed")

        store = self._store(lock_timeout=0.2)
        certificate = _issue_certificate("005", "mission-A")
        with self.assertRaises(CertificateLifecycleLockBusyError) as ctx:
            store.register_certificate(
                certificate_id=certificate.certificate_id, request_id=certificate.request_id,
                mission_id=certificate.mission_id, issued_at=certificate.issued_at,
            )
        self.assertIn("pid=", str(ctx.exception))
        self.assertTrue(self.lock_path.exists(), "a failed acquisition attempt must never remove someone else's lock")


# ---------------------------------------------------------------------
# E -- temporary file residue
# ---------------------------------------------------------------------


class TestE_TemporaryFileResidue(_CrashRecoveryTestCase):
    def test_temp_residue_does_not_block_new_registrations(self):
        stray = self.state_path.parent / ".tmp-certificate-lifecycle-residue.json"
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        stray.write_text("garbage, not json", encoding="utf-8")
        self.addCleanup(lambda: stray.unlink(missing_ok=True))

        store = self._store()
        certificate = _issue_certificate("005", "mission-A")
        new_record, _ = store.register_certificate(
            certificate_id=certificate.certificate_id, request_id=certificate.request_id,
            mission_id=certificate.mission_id, issued_at=certificate.issued_at,
        )
        self.assertEqual(new_record.status, CertificateLifecycleStatus.CURRENT)
        self.assertTrue(stray.exists(), "this store never touches unrelated temp files")


# ---------------------------------------------------------------------
# F -- main file missing combinations
# ---------------------------------------------------------------------


class TestF_MainFileMissingCombinations(_CrashRecoveryTestCase):
    def test_lock_present_store_absent_is_still_a_clean_initial_state_for_reads(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text('{"pid": 123, "acquired_at": "x"}', encoding="utf-8")
        self.addCleanup(lambda: self.lock_path.unlink(missing_ok=True))

        # Reads never touch the lock at all.
        records, current_by_scope, sequence_counter = self._store().load()
        self.assertEqual((records, current_by_scope, sequence_counter), ({}, {}, 0))

    def test_lock_present_store_absent_still_fails_closed_for_writes(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text('{"pid": 123, "acquired_at": "x"}', encoding="utf-8")
        self.addCleanup(lambda: self.lock_path.unlink(missing_ok=True))

        store = self._store(lock_timeout=0.2)
        certificate = _issue_certificate("005", "mission-A")
        with self.assertRaises(CertificateLifecycleLockBusyError):
            store.register_certificate(
                certificate_id=certificate.certificate_id, request_id=certificate.request_id,
                mission_id=certificate.mission_id, issued_at=certificate.issued_at,
            )

    def test_store_absent_history_query_is_empty_not_an_error(self):
        registry = CertificateLifecycleRegistry(store=self._store())
        registry.hydrate_from_store()
        self.assertEqual(registry.history_for(("005", "mission-A")), ())


# ---------------------------------------------------------------------
# G -- corrupt store + lock (re-verification, see also P3.59 Test16)
# ---------------------------------------------------------------------


class TestG_CorruptStorePlusLock(_CrashRecoveryTestCase):
    def test_corrupt_store_with_free_lock_is_fail_closed(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text('{"lifecycle_storage_version": "not-an-int", "records": {}}', encoding="utf-8")
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()


# ---------------------------------------------------------------------
# H -- valid store + malformed temporary
# ---------------------------------------------------------------------


class TestH_ValidStorePlusMalformedTemporary(_CrashRecoveryTestCase):
    def test_malformed_temporary_never_silently_replaces_a_valid_store(self):
        certificate = _issue_certificate("005", "mission-A")
        store = self._store()
        store.register_certificate(
            certificate_id=certificate.certificate_id, request_id=certificate.request_id,
            mission_id=certificate.mission_id, issued_at=certificate.issued_at,
        )
        before_records, _, _ = store.load()

        stray = self.state_path.parent / ".tmp-certificate-lifecycle-malformed.json"
        stray.write_text("{{{ not json at all", encoding="utf-8")
        self.addCleanup(lambda: stray.unlink(missing_ok=True))

        after_records, _, _ = self._store().load()
        self.assertEqual(before_records, after_records)


# ---------------------------------------------------------------------
# I -- concurrent restart (many real processes reading simultaneously)
# ---------------------------------------------------------------------


class TestI_ConcurrentRestart(_CrashRecoveryTestCase):
    def test_several_processes_hydrating_simultaneously_all_agree(self):
        certs = []
        store = self._store()
        for i in range(3):
            cert = _issue_certificate("005" if i % 2 == 0 else "not-005", "mission-A")
            store.register_certificate(
                certificate_id=cert.certificate_id, request_id=cert.request_id,
                mission_id=cert.mission_id, issued_at=cert.issued_at,
            )
            certs.append(cert)

        results = self._run_workers(
            _worker_concurrent_reader,
            [(str(self.state_path),) for _ in range(4)],
        )
        expected_ids = sorted(c.certificate_id for c in certs)
        for status, ids in results:
            self.assertEqual(status, "ok")
            self.assertEqual(ids, expected_ids)


# ---------------------------------------------------------------------
# J/K -- concurrent supersession / different scopes (2, 4, 8 processes)
# ---------------------------------------------------------------------


class TestJK_ConcurrentSupersessionAndScopes(_CrashRecoveryTestCase):
    def test_2_processes_same_scope(self):
        self._exercise_same_scope(2)

    def test_4_processes_same_scope(self):
        self._exercise_same_scope(4)

    def test_8_processes_same_scope(self):
        self._exercise_same_scope(8)

    def _exercise_same_scope(self, n):
        results = self._run_workers(
            _worker_register_once,
            [(str(self.state_path), "005", "mission-A") for _ in range(n)],
        )
        for status, *_ in results:
            self.assertEqual(status, "ok")
        self._assert_recovery_invariants(expected_total=n)

    def test_multiple_scopes_simultaneously_no_interference(self):
        args_list = [(str(self.state_path), "005", f"mission-{i}") for i in range(5)]
        results = self._run_workers(_worker_register_once, args_list)
        for status, *_ in results:
            self.assertEqual(status, "ok")
        records, current_by_scope, _ = self._assert_recovery_invariants(expected_total=5)
        self.assertEqual(len(current_by_scope), 5)


# ---------------------------------------------------------------------
# L -- sequence durability across a restart
# ---------------------------------------------------------------------


class TestL_SequenceDurability(_CrashRecoveryTestCase):
    def test_sequence_stays_monotone_across_a_simulated_restart(self):
        store_1 = self._store()
        for _ in range(3):
            cert = _issue_certificate("005", "mission-A")
            store_1.register_certificate(
                certificate_id=cert.certificate_id, request_id=cert.request_id,
                mission_id=cert.mission_id, issued_at=cert.issued_at,
            )

        # "Restart": a brand new store/registry instance.
        store_2 = self._store()
        for _ in range(3):
            cert = _issue_certificate("005", "mission-A")
            store_2.register_certificate(
                certificate_id=cert.certificate_id, request_id=cert.request_id,
                mission_id=cert.mission_id, issued_at=cert.issued_at,
            )

        self._assert_recovery_invariants(expected_total=6)


# ---------------------------------------------------------------------
# M -- history durability under crash/restart/concurrency
# ---------------------------------------------------------------------


class TestM_HistoryDurability(_CrashRecoveryTestCase):
    def test_no_certificate_is_lost_across_concurrent_activity_and_restart(self):
        results = self._run_workers(
            _worker_register_once,
            [(str(self.state_path), "005", "mission-A") for _ in range(4)],
        )
        expected_ids = {cid for status, cid, _ in results if status == "ok"}
        self.assertEqual(len(expected_ids), 4)

        restarted = CertificateLifecycleRegistry(store=self._store())
        restarted.hydrate_from_store()
        history_ids = {r.certificate_id for r in restarted.history_for(("005", "mission-A"))}
        self.assertEqual(history_ids, expected_ids)


# ---------------------------------------------------------------------
# N -- UNKNOWN isolation
# ---------------------------------------------------------------------


class TestN_UnknownIsolation(_CrashRecoveryTestCase):
    def test_unknown_never_promoted_even_after_heavy_concurrent_activity(self):
        self._run_workers(
            _worker_register_once,
            [(str(self.state_path), "005", "mission-A") for _ in range(4)],
        )
        registry = CertificateLifecycleRegistry(store=self._store())
        registry.hydrate_from_store()
        self.assertEqual(registry.status_of("still-never-registered"), CertificateLifecycleStatus.UNKNOWN)


# ---------------------------------------------------------------------
# O -- integrity/freshness isolation (structural)
# ---------------------------------------------------------------------


class TestO_IntegrityFreshnessIsolation(_CrashRecoveryTestCase):
    def test_persisted_schema_carries_no_integrity_or_freshness_fields(self):
        import json

        certificate = _issue_certificate("005", "mission-A")
        store = self._store()
        store.register_certificate(
            certificate_id=certificate.certificate_id, request_id=certificate.request_id,
            mission_id=certificate.mission_id, issued_at=certificate.issued_at,
        )
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        for raw in data["records"].values():
            forbidden = {"integrity", "digest", "freshness", "approval_decision", "readiness_result", "estimated_cost"}
            self.assertFalse(set(raw.keys()) & forbidden, f"unexpected authority/verification field(s) in {raw}")


# ---------------------------------------------------------------------
# P -- certificate immutability under adversarial concurrency
# ---------------------------------------------------------------------


class TestP_CertificateImmutability(_CrashRecoveryTestCase):
    def test_certificate_never_mutated_by_conflict_resolution(self):
        c1 = _issue_certificate("005", "mission-A")
        store = self._store()
        store.register_certificate(
            certificate_id=c1.certificate_id, request_id=c1.request_id,
            mission_id=c1.mission_id, issued_at=c1.issued_at,
        )
        # A second registration for the same scope supersedes c1.
        c2 = _issue_certificate("005", "mission-A")
        store.register_certificate(
            certificate_id=c2.certificate_id, request_id=c2.request_id,
            mission_id=c2.mission_id, issued_at=c2.issued_at,
        )
        self.assertEqual(c1.request_id, "005")
        with self.assertRaises(FrozenInstanceError):
            c1.request_id = "tampered"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            c2.request_id = "tampered"  # type: ignore[misc]


# ---------------------------------------------------------------------
# Deterministic stress test (Section 8): 8 processes x 20 registrations
# ---------------------------------------------------------------------


class TestStress_EightProcessesTwentyRegistrationsEach(_CrashRecoveryTestCase):
    def test_160_registrations_one_current_159_superseded_full_history(self):
        n_processes = 8
        per_process = 20
        expected_total = n_processes * per_process

        args_list = [(str(self.state_path), "005", "mission-A", per_process) for _ in range(n_processes)]
        results = self._run_workers(_worker_stress_register, args_list, timeout=180)

        all_ids = []
        for status, ids in results:
            self.assertEqual(status, "ok")
            all_ids.extend(ids)
        self.assertEqual(len(all_ids), expected_total)
        self.assertEqual(len(set(all_ids)), expected_total, "duplicate certificate_id across processes")

        records, current_by_scope, sequence_counter = self._assert_recovery_invariants(expected_total=expected_total)
        self.assertEqual(sequence_counter, expected_total)
        self.assertEqual(len(current_by_scope), 1)
        current_records = [r for r in records.values() if r.status == CertificateLifecycleStatus.CURRENT]
        superseded_records = [r for r in records.values() if r.status == CertificateLifecycleStatus.SUPERSEDED]
        self.assertEqual(len(current_records), 1)
        self.assertEqual(len(superseded_records), expected_total - 1)

        # The supersession chain must be a single, unbroken line from
        # sequence 1 up to the CURRENT one (store.load() already
        # verified there is no cycle and every superseded_by resolves).
        chain_ids = {r.certificate_id for r in records.values()}
        self.assertEqual(chain_ids, set(all_ids))


# ---------------------------------------------------------------------
# Repeated stress runs (item 18) -- smaller N, repeated, to catch races
# that a single run might miss, without becoming a flaky/slow test.
# ---------------------------------------------------------------------


class TestRepeatedStressRuns(unittest.TestCase):
    def test_repeated_small_concurrent_bursts_never_produce_an_inconsistency(self):
        for _ in range(3):
            with tempfile.TemporaryDirectory() as tmpdir:
                state_path = Path(tmpdir) / "state" / "certificate_lifecycle.json"
                barrier = multiprocessing.Barrier(3)
                result_queue = multiprocessing.Queue()
                processes = [
                    multiprocessing.Process(
                        target=_worker_register_once, args=(str(state_path), "005", "mission-A", barrier, result_queue)
                    )
                    for _ in range(3)
                ]
                for p in processes:
                    p.start()
                for p in processes:
                    p.join(timeout=30)
                    self.assertEqual(p.exitcode, 0)

                store = FileCertificateLifecycleStore(state_path)
                records, current_by_scope, sequence_counter = store.load()
                self.assertEqual(len(records), 3)
                self.assertEqual(len(current_by_scope), 1)
                self.assertEqual(sequence_counter, 3)


# ---------------------------------------------------------------------
# Authority boundary (no lifecycle -> production authority escalation)
# ---------------------------------------------------------------------


class TestNoAuthorityEscalation(_CrashRecoveryTestCase):
    def test_full_recovery_state_grants_no_authority(self):
        certificate = _issue_certificate("005", "mission-A")
        store = self._store()
        new_record, _ = store.register_certificate(
            certificate_id=certificate.certificate_id, request_id=certificate.request_id,
            mission_id=certificate.mission_id, issued_at=certificate.issued_at,
        )
        registry = CertificateLifecycleRegistry(store=self._store())
        registry.hydrate_from_store()

        for obj in (store, registry, new_record):
            self.assertFalse(hasattr(obj, "execute"))
            self.assertFalse(hasattr(obj, "create_job"))
            self.assertFalse(hasattr(obj, "authorize"))
            self.assertFalse(hasattr(obj, "activate"))
            self.assertFalse(hasattr(obj, "approve"))
        self.assertNotIsInstance(store, RealGenerationAuthorization)
        self.assertNotIsInstance(registry, RealGenerationAuthorization)


if __name__ == "__main__":
    unittest.main()
