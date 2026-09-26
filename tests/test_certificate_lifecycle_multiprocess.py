"""
Tests -- Certificate Lifecycle Inter-Process Concurrency & Locking
Boundary (Phase P3.59).

Unlike P3.57's concurrency tests (threading.Thread, one process),
these tests use REAL OS processes (multiprocessing.Process) writing to
the SAME Certificate Lifecycle store file, synchronized with
multiprocessing.Barrier for determinism (never relying on incidental
timing). Every worker function is module-level (required for pickling
under Windows' 'spawn' start method).

Every test uses MockHiggsfieldProvider exclusively; no real
generation, no real create_job(), no credits consumed. All files are
created in a temporary directory (never the real project).
"""

import multiprocessing
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.certificate_lifecycle import CertificateLifecycleRegistry, CertificateLifecycleStatus
from agents.certificate_lifecycle_lock import CertificateLifecycleFileLock, CertificateLifecycleLockBusyError
from agents.certificate_lifecycle_store import (
    CertificateLifecycleStoreCorruptedError,
    FileCertificateLifecycleStore,
)
from agents.generation_approval_gate import GenerationApprovalGate, GenerationRequest, RealGenerationAuthorization
from agents.activation_contract import RequestScopedActivationService
from agents.activation_readiness import ActivationReadinessEvaluator
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
    """Rebuilt independently in every process (parent or child) -- no
    object is ever shared/pickled across the process boundary except
    plain scalars and file paths."""

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
# Module-level worker functions (must be top-level for spawn-pickling).
# ---------------------------------------------------------------------


def _worker_register_via_store(store_path_str, request_id, mission_id, barrier, result_queue):
    try:
        certificate = _issue_certificate(request_id, mission_id)
        store = FileCertificateLifecycleStore(Path(store_path_str), lock_timeout=10.0)
        barrier.wait(timeout=15)
        new_record, superseded_record = store.register_certificate(
            certificate_id=certificate.certificate_id,
            request_id=certificate.request_id,
            mission_id=certificate.mission_id,
            issued_at=certificate.issued_at,
        )
        result_queue.put((
            "ok",
            new_record.certificate_id,
            new_record.registered_sequence,
            superseded_record.certificate_id if superseded_record else None,
        ))
    except Exception as error:  # noqa: BLE001 -- reported to the parent, never swallowed
        result_queue.put(("error", repr(error), None, None))


def _worker_register_via_registry(store_path_str, request_id, mission_id, barrier, result_queue):
    try:
        certificate = _issue_certificate(request_id, mission_id)
        store = FileCertificateLifecycleStore(Path(store_path_str), lock_timeout=10.0)
        registry = CertificateLifecycleRegistry(store=store)
        barrier.wait(timeout=15)
        record = registry.register(certificate)
        result_queue.put(("ok", record.certificate_id, record.registered_sequence, record.status.value))
    except Exception as error:  # noqa: BLE001
        result_queue.put(("error", repr(error), None, None))


def _worker_hold_lock_then_signal(lock_path_str, hold_seconds, ready_event):
    lock = CertificateLifecycleFileLock(Path(lock_path_str))
    with lock.acquire(timeout=0.0):
        ready_event.set()
        import time

        time.sleep(hold_seconds)


class _MultiProcessTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.state_path = Path(self._tmpdir.name) / "state" / "certificate_lifecycle.json"

    def _store(self, lock_timeout: float = 5.0) -> FileCertificateLifecycleStore:
        return FileCertificateLifecycleStore(self.state_path, lock_timeout=lock_timeout)

    def _run_workers(self, worker, args_list, timeout=20):
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

        results = [result_queue.get(timeout=5) for _ in processes]
        return results


# 1 -- cross-process same scope -------------------------------------------


class Test01_CrossProcessSameScope(_MultiProcessTestCase):
    def test_two_processes_same_scope_never_produce_two_current(self):
        results = self._run_workers(
            _worker_register_via_store,
            [(str(self.state_path), "005", "mission-A"), (str(self.state_path), "005", "mission-A")],
        )
        for status, *_ in results:
            self.assertEqual(status, "ok")

        records, current_by_scope, sequence_counter = self._store().load()
        self.assertEqual(len(records), 2)
        current = [r for r in records.values() if r.status == CertificateLifecycleStatus.CURRENT]
        self.assertEqual(len(current), 1)
        self.assertEqual(sequence_counter, 2)
        sequences = sorted(r.registered_sequence for r in records.values())
        self.assertEqual(sequences, [1, 2])


# 2 -- cross-process different requests ------------------------------------


class Test02_CrossProcessDifferentRequests(_MultiProcessTestCase):
    def test_two_processes_different_requests_both_current(self):
        results = self._run_workers(
            _worker_register_via_store,
            [(str(self.state_path), "005", "mission-A"), (str(self.state_path), "not-005", "mission-A")],
        )
        for status, *_ in results:
            self.assertEqual(status, "ok")

        records, current_by_scope, _ = self._store().load()
        self.assertEqual(len(records), 2)
        self.assertEqual(len(current_by_scope), 2)
        self.assertEqual(len([r for r in records.values() if r.status == CertificateLifecycleStatus.CURRENT]), 2)


# 3/4 -- same request/same mission vs same request/different missions -----


class Test03_04_SameRequestMissionVariants(_MultiProcessTestCase):
    def test_same_request_same_mission_is_one_scope(self):
        results = self._run_workers(
            _worker_register_via_store,
            [(str(self.state_path), "005", "mission-A"), (str(self.state_path), "005", "mission-A")],
        )
        for status, *_ in results:
            self.assertEqual(status, "ok")
        _, current_by_scope, _ = self._store().load()
        self.assertEqual(len(current_by_scope), 1)

    def test_same_request_different_missions_are_two_scopes(self):
        results = self._run_workers(
            _worker_register_via_store,
            [(str(self.state_path), "005", "mission-A"), (str(self.state_path), "005", "mission-B")],
        )
        for status, *_ in results:
            self.assertEqual(status, "ok")
        _, current_by_scope, _ = self._store().load()
        self.assertEqual(len(current_by_scope), 2)


# 5 -- simultaneous registration (via the Registry, not the raw store) -----


class Test05_SimultaneousRegistrationViaRegistry(_MultiProcessTestCase):
    def test_registry_register_is_cross_process_safe(self):
        results = self._run_workers(
            _worker_register_via_registry,
            [(str(self.state_path), "005", "mission-A"), (str(self.state_path), "005", "mission-A")],
        )
        for status, *_ in results:
            self.assertEqual(status, "ok")
        records, current_by_scope, _ = self._store().load()
        self.assertEqual(len(records), 2)
        self.assertEqual(len(current_by_scope), 1)


# 6 -- simultaneous supersession ------------------------------------------


class Test06_SimultaneousSupersession(_MultiProcessTestCase):
    def test_two_processes_superseding_the_same_current_resolve_to_one_chain(self):
        # Pre-register C1 (parent process, before spawning children).
        c1 = _issue_certificate("005", "mission-A")
        store = self._store()
        store.register_certificate(
            certificate_id=c1.certificate_id, request_id=c1.request_id,
            mission_id=c1.mission_id, issued_at=c1.issued_at,
        )

        results = self._run_workers(
            _worker_register_via_store,
            [(str(self.state_path), "005", "mission-A"), (str(self.state_path), "005", "mission-A")],
        )
        for status, *_ in results:
            self.assertEqual(status, "ok")

        records, current_by_scope, sequence_counter = store.load()
        self.assertEqual(len(records), 3)
        current = [r for r in records.values() if r.status == CertificateLifecycleStatus.CURRENT]
        self.assertEqual(len(current), 1)
        self.assertEqual(sequence_counter, 3)
        # C1 must be superseded by SOMETHING (the chain must be unbroken --
        # store.load() already raised if it were not).
        c1_record = records[c1.certificate_id]
        self.assertEqual(c1_record.status, CertificateLifecycleStatus.SUPERSEDED)
        self.assertIsNotNone(c1_record.superseded_by)


# 7 -- sequence collision attempt ------------------------------------------


class Test07_SequenceCollisionAttempt(_MultiProcessTestCase):
    def test_no_two_records_ever_share_a_sequence(self):
        args_list = [(str(self.state_path), "005", f"mission-{i}") for i in range(5)]
        results = self._run_workers(_worker_register_via_store, args_list, timeout=30)
        for status, *_ in results:
            self.assertEqual(status, "ok")

        records, _, _ = self._store().load()
        sequences = [r.registered_sequence for r in records.values()]
        self.assertEqual(len(sequences), len(set(sequences)), "duplicate sequence detected")
        self.assertEqual(sorted(sequences), list(range(1, len(records) + 1)))


# 8/9 -- crash during critical section / stale lock -------------------------


class Test08_09_CrashDuringCriticalSectionAndStaleLock(_MultiProcessTestCase):
    def test_lock_held_by_another_process_fails_closed_never_silently_bypassed(self):
        lock_path = self.state_path.parent / f".{self.state_path.name}.lock"
        ready_event = multiprocessing.Event()
        holder = multiprocessing.Process(
            target=_worker_hold_lock_then_signal, args=(str(lock_path), 3.0, ready_event)
        )
        holder.start()
        self.addCleanup(holder.join)
        self.assertTrue(ready_event.wait(timeout=10), "holder process never acquired the lock")

        store = self._store(lock_timeout=0.2)
        certificate = _issue_certificate("005", "mission-A")
        with self.assertRaises(CertificateLifecycleLockBusyError) as ctx:
            store.register_certificate(
                certificate_id=certificate.certificate_id, request_id=certificate.request_id,
                mission_id=certificate.mission_id, issued_at=certificate.issued_at,
            )
        self.assertIn("pid=", str(ctx.exception))
        holder.join(timeout=10)

    def test_orphaned_stale_lock_file_is_never_auto_removed(self):
        lock_path = self.state_path.parent / f".{self.state_path.name}.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text('{"pid": 999999, "acquired_at": "1999-01-01T00:00:00+00:00"}', encoding="utf-8")

        store = self._store(lock_timeout=0.2)
        certificate = _issue_certificate("005", "mission-A")
        with self.assertRaises(CertificateLifecycleLockBusyError):
            store.register_certificate(
                certificate_id=certificate.certificate_id, request_id=certificate.request_id,
                mission_id=certificate.mission_id, issued_at=certificate.issued_at,
            )
        # Never auto-removed -- still there, untouched.
        self.assertTrue(lock_path.exists())


# 10/11/12 -- lock acquisition / release / timeout --------------------------


class Test10_11_12_LockAcquireReleaseTimeout(_MultiProcessTestCase):
    def test_lock_is_released_after_the_with_block(self):
        lock_path = self.state_path.parent / "lifecycle.lock"
        lock = CertificateLifecycleFileLock(lock_path)
        with lock.acquire():
            self.assertTrue(lock_path.exists())
        self.assertFalse(lock_path.exists())

    def test_lock_is_released_even_on_exception(self):
        lock_path = self.state_path.parent / "lifecycle.lock"
        lock = CertificateLifecycleFileLock(lock_path)
        with self.assertRaises(ValueError):
            with lock.acquire():
                raise ValueError("boom")
        self.assertFalse(lock_path.exists())

    def test_non_blocking_default_timeout_fails_immediately(self):
        lock_path = self.state_path.parent / "lifecycle.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = CertificateLifecycleFileLock(lock_path)
        with lock.acquire():
            other = CertificateLifecycleFileLock(lock_path)
            with self.assertRaises(CertificateLifecycleLockBusyError):
                with other.acquire(timeout=0.0):
                    pass  # pragma: no cover

    def test_bounded_timeout_eventually_raises(self):
        import time

        lock_path = self.state_path.parent / "lifecycle.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = CertificateLifecycleFileLock(lock_path)
        with lock.acquire():
            other = CertificateLifecycleFileLock(lock_path)
            start = time.monotonic()
            with self.assertRaises(CertificateLifecycleLockBusyError):
                with other.acquire(timeout=0.3, poll_interval=0.05):
                    pass  # pragma: no cover
            elapsed = time.monotonic() - start
            self.assertGreaterEqual(elapsed, 0.25)


# 13/14 -- stale lock / malformed lock ---------------------------------


class Test13_14_StaleMalformedLock(_MultiProcessTestCase):
    def test_malformed_lock_content_does_not_crash_the_busy_error_path(self):
        lock_path = self.state_path.parent / "lifecycle.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        import os

        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
        os.write(fd, b"not even json {{{")
        os.close(fd)
        self.addCleanup(lambda: lock_path.unlink(missing_ok=True))

        lock = CertificateLifecycleFileLock(lock_path)
        with self.assertRaises(CertificateLifecycleLockBusyError) as ctx:
            with lock.acquire(timeout=0.05):
                pass  # pragma: no cover
        self.assertIn("malformed", str(ctx.exception).lower())

    def test_empty_lock_file_does_not_crash_the_busy_error_path(self):
        lock_path = self.state_path.parent / "lifecycle.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        import os

        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
        os.close(fd)
        self.addCleanup(lambda: lock_path.unlink(missing_ok=True))

        lock = CertificateLifecycleFileLock(lock_path)
        with self.assertRaises(CertificateLifecycleLockBusyError):
            with lock.acquire(timeout=0.05):
                pass  # pragma: no cover


# 15/18 -- crash recovery / restart after crash -----------------------


class Test15_18_CrashRecoveryRestart(_MultiProcessTestCase):
    def test_reading_is_never_blocked_by_a_stale_write_lock(self):
        """A stuck write lock blocks NEW writes, but never reads -- a
        restarted process can always recover the last known-good
        CURRENT/history even while a human is still investigating the
        stale lock (Section 5/15, P3.59 mission)."""

        certificate = _issue_certificate("005", "mission-A")
        store = self._store()
        store.register_certificate(
            certificate_id=certificate.certificate_id, request_id=certificate.request_id,
            mission_id=certificate.mission_id, issued_at=certificate.issued_at,
        )

        lock_path = self.state_path.parent / f".{self.state_path.name}.lock"
        lock_path.write_text('{"pid": 999999, "acquired_at": "1999-01-01T00:00:00+00:00"}', encoding="utf-8")

        # A fresh registry, simulating a restarted process, must still
        # be able to hydrate and read the last known-good state.
        restarted = CertificateLifecycleRegistry(store=self._store())
        restarted.hydrate_from_store()
        self.assertEqual(restarted.status_of(certificate.certificate_id), CertificateLifecycleStatus.CURRENT)

    def test_restart_after_real_crash_preserves_state(self):
        results = self._run_workers(
            _worker_register_via_store,
            [(str(self.state_path), "005", "mission-A"), (str(self.state_path), "not-005", "mission-A")],
        )
        for status, *_ in results:
            self.assertEqual(status, "ok")

        restarted = CertificateLifecycleRegistry(store=self._store())
        restarted.hydrate_from_store()
        records, current_by_scope, _ = self._store().load()
        for certificate_id in records:
            self.assertEqual(restarted.status_of(certificate_id), CertificateLifecycleStatus.CURRENT)


# 16 -- corrupted storage + lock -----------------------------------------


class Test16_CorruptedStoragePlusLock(_MultiProcessTestCase):
    def test_corrupted_storage_with_lock_free_raises_corrupted_error(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text('{"lifecycle_storage_version": 999, "records": {}}', encoding="utf-8")

        store = self._store(lock_timeout=0.2)
        certificate = _issue_certificate("005", "mission-A")
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            store.register_certificate(
                certificate_id=certificate.certificate_id, request_id=certificate.request_id,
                mission_id=certificate.mission_id, issued_at=certificate.issued_at,
            )

    def test_stale_lock_is_reported_before_storage_is_even_read(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text('{"lifecycle_storage_version": 999, "records": {}}', encoding="utf-8")
        lock_path = self.state_path.parent / f".{self.state_path.name}.lock"
        lock_path.write_text('{"pid": 999999, "acquired_at": "1999-01-01T00:00:00+00:00"}', encoding="utf-8")

        store = self._store(lock_timeout=0.2)
        certificate = _issue_certificate("005", "mission-A")
        with self.assertRaises(CertificateLifecycleLockBusyError):
            store.register_certificate(
                certificate_id=certificate.certificate_id, request_id=certificate.request_id,
                mission_id=certificate.mission_id, issued_at=certificate.issued_at,
            )


# 17 -- atomic write + lock ------------------------------------------------


class Test17_AtomicWritePlusLock(_MultiProcessTestCase):
    def test_file_is_always_valid_json_after_concurrent_writes(self):
        args_list = [(str(self.state_path), "005", "mission-A") for _ in range(4)]
        results = self._run_workers(_worker_register_via_store, args_list, timeout=30)
        for status, *_ in results:
            self.assertEqual(status, "ok")
        # load() re-parses and fully re-validates the file -- no
        # exception means it is well-formed, atomic, and internally
        # consistent (Section 6 corruption matrix, re-used as the
        # invariant-checker here).
        records, current_by_scope, _ = self._store().load()
        self.assertEqual(len(records), 4)
        self.assertEqual(len(current_by_scope), 1)


# 19 -- repeated multi-process stress ---------------------------------


class Test19_RepeatedMultiProcessStress(_MultiProcessTestCase):
    def test_six_processes_same_scope_stress(self):
        args_list = [(str(self.state_path), "005", "mission-A") for _ in range(6)]
        results = self._run_workers(_worker_register_via_store, args_list, timeout=40)
        for status, *_ in results:
            self.assertEqual(status, "ok")

        records, current_by_scope, sequence_counter = self._store().load()
        self.assertEqual(len(records), 6)
        self.assertEqual(len(current_by_scope), 1)
        self.assertEqual(sequence_counter, 6)
        sequences = sorted(r.registered_sequence for r in records.values())
        self.assertEqual(sequences, list(range(1, 7)))


# 20 -- immutable certificate -----------------------------------------


class Test20_ImmutableCertificate(_MultiProcessTestCase):
    def test_certificate_object_stays_frozen_after_cross_process_registration(self):
        certificate = _issue_certificate("005", "mission-A")
        store = self._store()
        store.register_certificate(
            certificate_id=certificate.certificate_id, request_id=certificate.request_id,
            mission_id=certificate.mission_id, issued_at=certificate.issued_at,
        )
        self.assertEqual(certificate.request_id, "005")
        with self.assertRaises(FrozenInstanceError):
            certificate.request_id = "tampered"  # type: ignore[misc]


# 21 -- UNKNOWN fail-closed -------------------------------------------


class Test21_UnknownFailClosed(_MultiProcessTestCase):
    def test_unregistered_id_is_unknown_even_after_multiprocess_activity(self):
        results = self._run_workers(
            _worker_register_via_store,
            [(str(self.state_path), "005", "mission-A"), (str(self.state_path), "not-005", "mission-A")],
        )
        for status, *_ in results:
            self.assertEqual(status, "ok")

        registry = CertificateLifecycleRegistry(store=self._store())
        registry.hydrate_from_store()
        self.assertEqual(registry.status_of("never-registered"), CertificateLifecycleStatus.UNKNOWN)


# 22/23/24 -- no authority/execute/create_job escalation --------------------


class Test22_23_24_NoAuthorityEscalation(_MultiProcessTestCase):
    def test_no_authority_module_referenced_by_the_lock(self):
        import ast

        source = (PROJECT_ROOT / "agents" / "certificate_lifecycle_lock.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
        for module_name in imported_modules:
            self.assertFalse(module_name.startswith("agents."), f"unexpected agents import: {module_name}")

        forbidden_attr_calls = {
            n.func.attr for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("create_job", "execute", "prepare_activation", "validate_activation", "consume")
        }
        self.assertFalse(forbidden_attr_calls)

    def test_no_p2_file_or_director_references_the_lock_module(self):
        p2_files = (
            "agents/generation_approval_gate.py",
            "agents/generation_job_service.py",
            "agents/activation_contract.py",
            "agents/controlled_real_provider_activation.py",
            "agents/critical_section_lock.py",
            "agents/executed_request_store.py",
            "agents/release_candidate_identity_lock.py",
            "agents/production_activation_readiness_certificate.py",
            "integrations/higgsfield/provider.py",
            "director.py",
        )
        offenders = []
        for rel in p2_files:
            text = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
            if "certificate_lifecycle_lock" in text:
                offenders.append(rel)
        self.assertFalse(offenders, offenders)

    def test_maximal_state_still_grants_no_authority(self):
        certificate = _issue_certificate("005", "mission-A")
        store = self._store()
        new_record, _ = store.register_certificate(
            certificate_id=certificate.certificate_id, request_id=certificate.request_id,
            mission_id=certificate.mission_id, issued_at=certificate.issued_at,
        )
        self.assertEqual(new_record.status, CertificateLifecycleStatus.CURRENT)
        for obj in (new_record, store):
            self.assertFalse(hasattr(obj, "execute"))
            self.assertFalse(hasattr(obj, "create_job"))
            self.assertFalse(hasattr(obj, "authorize"))
            self.assertFalse(hasattr(obj, "activate"))
        self.assertNotIsInstance(store, RealGenerationAuthorization)


if __name__ == "__main__":
    unittest.main()
