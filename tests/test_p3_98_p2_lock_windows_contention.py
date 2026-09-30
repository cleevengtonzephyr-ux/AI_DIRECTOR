"""
Tests — Phase P3.98 : verrous du P2 authority core sous contention de
suppression Windows (D3 / D4).

Défauts démontrés en P3.97-STEP-1 / P3.98 (audit), avec de vrais
processus OS :
- D3 (`FileExecutedRequestStore._locked`) : un lecteur du verrou
  (`_lock_holder()` d'un autre processus) faisait échouer la suppression
  à la libération -- `PermissionError` avalée, verrou orphelin après une
  libération PROPRE (5/5 essais à timeout 0). Conséquence : tout le store
  en timeout -> BLOCKED ; placé entre `in_flight` et `mark_executed`, le
  `job_id` n'était plus persisté.
- D4a (`FileCriticalSectionLock.acquire`) : `PermissionError` à la
  création exclusive (verrou d'un détenteur concurrent en cours de
  suppression) non interceptée -- exception brute hors de `execute()`
  (108 / 10 000 tentatives).
- D4b (même fonction, libération) : un handle externe ouvert sur le
  verrou laissait un verrou orphelin pour ce `request_id`.

Invariants re-vérifiés ici : fail closed (jamais d'autorisation sur une
erreur de verrou), un verrou orphelin n'est jamais supprimé
automatiquement, write-ahead `in_flight` avant `create_job()`, UNKNOWN
jamais retiré, aucun rejeu, aucun `create_job()` sur refus de verrou.

Toutes les créations de job utilisent exclusivement MockHiggsfield
Provider, dans des répertoires temporaires. Aucun appel réseau, aucun
CLI réel, aucun crédit consommé. Les workers multiprocessing sont des
fonctions de module (pickling sous 'spawn', Windows).
"""

import json
import multiprocessing
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.critical_section_lock import CriticalSectionBusyError, FileCriticalSectionLock
from agents.executed_request_store import FileExecutedRequestStore, ExecutedRequestStoreLockTimeoutError
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from tests.real_provider_path_fixtures import (
    counting_mock_provider,
    fixture_real_path_gate_kwargs,
    install_create_job_probe,
)
from tests.authorization_content_helpers import bind_request, content_media
from agents.generation_job_service import (
    CriticalStateUnknownAndUnrecordedError,
    GenerationJobExecutionError,
    GenerationJobService,
)
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider

RID = "005"


def _request(request_id=RID) -> GenerationRequest:
    return bind_request(GenerationRequest(
        **content_media(),
        request_id=request_id,
        job_type="seedance_2_0",
        prompt="Un prompt de test suffisamment explicite.",
        duration=5,
        approved=True,
        real_generation_authorization=RealGenerationAuthorization(
            request_id=request_id, authorized_by_human=True
        ),
    ))


def _HookedProvider(**kwargs):
    """Mock RECONNU dont un crochet de test s'exécute juste après la
    création du job (simule un événement disque concurrent). Phase D : le
    crochet `after_create_job` est exécuté par `install_create_job_probe()`
    au retour de `create_job()`, avant `mark_executed()` -- jamais par un
    `create_job()` redéfini."""

    return counting_mock_provider(**kwargs)


def _worker_store_contend(state_path_str, iterations, result_queue):
    store = FileExecutedRequestStore(Path(state_path_str), lock_timeout_seconds=0.0)
    counts = {"acquired": 0, "timeout": 0, "other": []}
    for _ in range(iterations):
        try:
            with store._locked(context="p3.98 contention", write=True):
                counts["acquired"] += 1
        except ExecutedRequestStoreLockTimeoutError:
            counts["timeout"] += 1
        except Exception as error:  # noqa: BLE001 -- rapporté, jamais avalé
            counts["other"].append(repr(error))
    result_queue.put(counts)


def _worker_critical_section_contend(lock_dir_str, iterations, result_queue):
    lock = FileCriticalSectionLock(Path(lock_dir_str))
    counts = {"acquired": 0, "busy": 0, "other": []}
    for _ in range(iterations):
        try:
            with lock.acquire(RID):
                counts["acquired"] += 1
        except CriticalSectionBusyError:
            counts["busy"] += 1
        except Exception as error:  # noqa: BLE001 -- rapporté, jamais avalé
            counts["other"].append(repr(error))
    result_queue.put(counts)


def _run_two_processes(target, args):
    result_queue = multiprocessing.Queue()
    processes = [multiprocessing.Process(target=target, args=(*args, result_queue)) for _ in range(2)]
    for p in processes:
        p.start()
    for p in processes:
        p.join(timeout=240)
    results = [result_queue.get(timeout=10) for _ in processes]
    return processes, results


class _SandboxCase(unittest.TestCase):
    def setUp(self):
        self.sandbox = Path(tempfile.mkdtemp(prefix="p3_98_"))
        self.addCleanup(shutil.rmtree, self.sandbox, ignore_errors=True)
        self.state_path = self.sandbox / "state" / "executed_requests.json"
        self.lock_dir = self.sandbox / "state" / "locks"

    def _chain(self, lock_timeout=10.0):
        provider = _HookedProvider(cost_per_job=10.0, available_credits=1000.0)
        store = FileExecutedRequestStore(self.state_path, lock_timeout_seconds=lock_timeout)
        # Phase D : _HookedProvider (non reconnu comme mock) -> fixtures
        # EXPLICITES : plafond + Identity Lock lié au contenu exact.
        gate = install_create_job_probe(
            GenerationApprovalGate(provider, executed_request_store=store, **fixture_real_path_gate_kwargs(_request())),
            provider,
        )
        service = GenerationJobService(provider, gate, lock=FileCriticalSectionLock(self.lock_dir))
        return provider, store, gate, service

    def _execute(self, service):
        return service.execute(_request(), timeout_seconds=5, interval_seconds=0)


# ---------------------------------------------------------------------
# D3 -- FileExecutedRequestStore._locked
# ---------------------------------------------------------------------


class TestD3_StoreLockRelease(_SandboxCase):
    def test_release_removes_the_lock_once_a_brief_reader_closes_it(self):
        store = FileExecutedRequestStore(self.state_path)
        with store._locked(context="p3.98", write=True):
            # Même type de handle que `_lock_holder()` (read_text).
            reader = open(store.lock_path, "rb")
            closer = threading.Timer(0.2, reader.close)
            closer.start()
        closer.join()
        reader.close()
        self.assertFalse(store.lock_path.exists(), "a cleanly released store lock was left on disk")
        self.assertFalse(FileExecutedRequestStore(self.state_path, lock_timeout_seconds=0.0).is_executed(RID))

    @unittest.skipUnless(os.name == "nt", "the delete only fails while open on Windows")
    def test_release_retry_is_bounded_then_fails_closed_and_is_never_auto_removed(self):
        provider, store, gate, _ = self._chain(lock_timeout=0.2)
        reader = None
        try:
            with store._locked(context="p3.98", write=True):
                reader = open(store.lock_path, "rb")  # tenu au-delà de la fenêtre
        finally:
            self.assertTrue(store.lock_path.exists())
            reader.close()
        self.assertTrue(store.lock_path.exists(), "an orphaned lock must never be removed automatically")
        decision = gate.evaluate(_request()).decision
        self.assertEqual(decision, GenerationApprovalDecision.BLOCKED)
        self.assertEqual(len(provider._jobs), 0)

    def test_two_process_contention_never_orphans_the_store_lock(self):
        self.state_path.parent.mkdir(parents=True)
        processes, results = _run_two_processes(_worker_store_contend, (str(self.state_path), 2000))
        for p in processes:
            self.assertFalse(p.is_alive(), "worker process did not terminate in time")
            self.assertEqual(p.exitcode, 0)
        self.assertEqual([r["other"] for r in results], [[], []])
        self.assertGreater(sum(r["acquired"] for r in results), 0)
        self.assertFalse(
            self.state_path.with_name(self.state_path.name + ".lock").exists(),
            "a cleanly released store lock was left on disk",
        )


class TestD3_OrphanAfterCreateJobNeverAllowsReplay(_SandboxCase):
    """Pire placement de D3 : verrou du store présent juste après un
    `create_job()` réussi, avant `mark_executed()`."""

    def test_in_flight_marker_blocks_every_replay_and_the_orphan_is_left_for_review(self):
        provider, store, _, service = self._chain(lock_timeout=0.2)

        def orphan_the_store_lock():
            store.lock_path.write_text(json.dumps({"pid": -1, "acquired_at": "p3.98 test"}))

        provider.after_create_job = orphan_the_store_lock
        with self.assertRaises(CriticalStateUnknownAndUnrecordedError):
            self._execute(service)
        self.assertEqual(len(provider._jobs), 1)
        provider.after_create_job = None

        with self.assertRaises(GenerationJobExecutionError) as blocked:
            self._execute(service)
        self.assertEqual(blocked.exception.approval.decision, GenerationApprovalDecision.BLOCKED)
        self.assertTrue(store.lock_path.exists(), "an orphaned lock must never be removed automatically")
        self.assertEqual(len(provider._jobs), 1)

        store.lock_path.unlink()  # revue humaine
        record = json.loads(self.state_path.read_text(encoding="utf-8"))["unknown_requests"][RID]
        self.assertIs(record.get("in_flight"), True)
        with self.assertRaises(GenerationJobExecutionError) as unknown:
            self._execute(service)
        self.assertEqual(
            unknown.exception.approval.decision, GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN
        )
        self.assertEqual(len(provider._jobs), 1)


class TestD3_NominalWriteAheadOrderPreserved(_SandboxCase):
    def test_in_flight_is_persisted_before_create_job_and_replaced_by_executed(self):
        provider, store, _, service = self._chain()
        seen = {}

        def observe_store_during_create_job():
            seen["unknown_during_create_job"] = store.is_unknown(RID)
            seen["executed_during_create_job"] = store.is_executed(RID)

        provider.after_create_job = observe_store_during_create_job
        outcome = self._execute(service)
        self.assertTrue(outcome.succeeded)
        self.assertEqual(seen, {"unknown_during_create_job": True, "executed_during_create_job": False})
        self.assertTrue(store.is_executed(RID))
        self.assertFalse(store.is_unknown(RID))
        self.assertEqual(store.recorded_job_id(RID), outcome.job.job_id)
        self.assertFalse(store.lock_path.exists())
        self.assertEqual(list(self.lock_dir.glob("*.lock")), [])

        with self.assertRaises(GenerationJobExecutionError) as replay:
            self._execute(service)
        self.assertEqual(replay.exception.approval.decision, GenerationApprovalDecision.ALREADY_EXECUTED)
        self.assertEqual(len(provider._jobs), 1)


# ---------------------------------------------------------------------
# D4 -- FileCriticalSectionLock.acquire
# ---------------------------------------------------------------------


class TestD4a_PermissionErrorOnCreateIsBusy(_SandboxCase):
    def _deny_lock_file_creation(self):
        real_open = os.open
        lock_file = str(self.lock_dir / f"{RID}.lock")

        def denied(path, flags, *args):
            if str(path) == lock_file:
                raise PermissionError(13, "Permission denied", path)
            return real_open(path, flags, *args)

        return mock.patch("agents.critical_section_lock.os.open", side_effect=denied)

    def test_permission_error_is_busy_and_never_reaches_evaluate_nor_create_job(self):
        provider, store, gate, service = self._chain()
        with self._deny_lock_file_creation(), mock.patch.object(gate, "evaluate", wraps=gate.evaluate) as evaluate:
            with self.assertRaises(CriticalSectionBusyError) as busy:
                self._execute(service)
        self.assertIsInstance(busy.exception.__cause__, PermissionError)
        evaluate.assert_not_called()
        self.assertEqual(len(provider._jobs), 0)
        self.assertFalse(self.state_path.exists(), "no store write may happen before the lock")
        self.assertEqual(list(self.lock_dir.glob("*.lock")), [])

    def test_refusal_is_immediate_never_a_wait(self):
        lock = FileCriticalSectionLock(self.lock_dir)
        with self._deny_lock_file_creation():
            started = time.monotonic()
            with self.assertRaises(CriticalSectionBusyError):
                with lock.acquire(RID):
                    self.fail("the critical section must never be granted")
            self.assertLess(time.monotonic() - started, 0.5)


class TestD4b_CriticalSectionRelease(_SandboxCase):
    def test_release_removes_the_lock_once_a_brief_external_handle_closes(self):
        lock = FileCriticalSectionLock(self.lock_dir)
        lock_file = self.lock_dir / f"{RID}.lock"
        with lock.acquire(RID):
            reader = open(lock_file, "rb")
            closer = threading.Timer(0.2, reader.close)
            closer.start()
        closer.join()
        reader.close()
        self.assertFalse(lock_file.exists(), "a cleanly released critical-section lock was left on disk")
        with lock.acquire(RID):
            pass

    @unittest.skipUnless(os.name == "nt", "the delete only fails while open on Windows")
    def test_release_retry_is_bounded_then_fails_closed_without_replay(self):
        provider, _, _, service = self._chain()
        lock_file = self.lock_dir / f"{RID}.lock"
        handles = []
        provider.after_create_job = lambda: handles.append(open(lock_file, "rb"))
        try:
            self.assertTrue(self._execute(service).succeeded)
        finally:
            provider.after_create_job = None
            for handle in handles:
                handle.close()
        self.assertTrue(lock_file.exists(), "an orphaned lock must never be removed automatically")
        with self.assertRaises(CriticalSectionBusyError):
            self._execute(service)
        self.assertEqual(len(provider._jobs), 1)

    def test_two_process_contention_never_leaks_permission_error_nor_orphans(self):
        processes, results = _run_two_processes(_worker_critical_section_contend, (str(self.lock_dir), 3000))
        for p in processes:
            self.assertFalse(p.is_alive(), "worker process did not terminate in time")
            self.assertEqual(p.exitcode, 0)
        self.assertEqual([r["other"] for r in results], [[], []])
        self.assertEqual(sum(r["acquired"] + r["busy"] for r in results), 6000)
        self.assertGreater(sum(r["acquired"] for r in results), 0)
        self.assertFalse((self.lock_dir / f"{RID}.lock").exists(), "a cleanly released lock was left on disk")


if __name__ == "__main__":
    unittest.main()
