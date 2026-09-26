"""
Tests -- Certificate Lifecycle lock under Windows file-deletion contention
(Phase P3.97, D1/D2).

P3.97-STEP-1 measured, with real OS processes contending on
`CertificateLifecycleFileLock`:
- D1: a waiter reading the lock file (`_diagnostic_summary()`) made the
  holder's release `unlink()` fail with PermissionError, which was
  swallowed -- a lock released cleanly stayed on disk (5/5 trials).
- D2: `os.open(O_CREAT | O_EXCL)` raised PermissionError while a
  concurrent holder's lock file was being deleted; only FileExistsError
  was treated as "busy", so the PermissionError escaped (test_160).

Every worker function is module-level (required for pickling under
Windows' 'spawn' start method). No provider, no generation, no credits:
only the lock primitive is exercised, in a temporary directory.
"""

import multiprocessing
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.certificate_lifecycle_lock import CertificateLifecycleFileLock, CertificateLifecycleLockBusyError


def _worker_contend(lock_path_str, iterations, result_queue):
    counts = {"acquired": 0, "busy": 0, "other": []}
    for _ in range(iterations):
        try:
            with CertificateLifecycleFileLock(Path(lock_path_str)).acquire(timeout=0.0):
                counts["acquired"] += 1
        except CertificateLifecycleLockBusyError:
            counts["busy"] += 1
        except Exception as error:  # noqa: BLE001 -- reported, never swallowed
            counts["other"].append(repr(error))
    result_queue.put(counts)


class _LockTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.lock_path = Path(self._tmpdir.name) / "state" / ".certificate_lifecycle.json.lock"


class TestD1_ReleaseWhileLockFileIsBrieflyOpen(_LockTestCase):
    def test_release_still_removes_the_lock_file_once_the_reader_closes_it(self):
        lock = CertificateLifecycleFileLock(self.lock_path)
        with lock.acquire(timeout=0.0):
            # Same kind of handle `_diagnostic_summary()` opens (read_text).
            reader = open(self.lock_path, "rb")
            closer = threading.Timer(0.2, reader.close)
            closer.start()
        closer.join()
        reader.close()
        self.assertFalse(self.lock_path.exists(), "a cleanly released lock was left on disk")
        with CertificateLifecycleFileLock(self.lock_path).acquire(timeout=0.0):
            pass

    @unittest.skipUnless(os.name == "nt", "the delete only fails while open on Windows")
    def test_release_retry_is_bounded_and_fails_closed(self):
        lock = CertificateLifecycleFileLock(self.lock_path)
        reader = None
        try:
            with lock.acquire(timeout=0.0):
                reader = open(self.lock_path, "rb")  # held past the retry window
        finally:
            self.assertTrue(self.lock_path.exists())
            reader.close()
        # Left in place, never removed automatically: still busy, fail-closed.
        with self.assertRaises(CertificateLifecycleLockBusyError):
            with CertificateLifecycleFileLock(self.lock_path).acquire(timeout=0.0):
                pass


class TestD2_PermissionErrorOnCreateIsBusy(_LockTestCase):
    def test_transient_permission_error_is_polled_like_a_held_lock(self):
        real_open = os.open
        failures = {"left": 2}

        def flaky_open(path, flags, *args):
            if path == str(self.lock_path) and failures["left"]:
                failures["left"] -= 1
                raise PermissionError(13, "Permission denied", path)
            return real_open(path, flags, *args)

        with mock.patch("agents.certificate_lifecycle_lock.os.open", side_effect=flaky_open):
            with CertificateLifecycleFileLock(self.lock_path).acquire(timeout=5.0, poll_interval=0.01):
                self.assertTrue(self.lock_path.exists())
        self.assertEqual(failures["left"], 0)
        self.assertFalse(self.lock_path.exists())

    def test_persistent_permission_error_fails_closed_as_busy(self):
        denied = PermissionError(13, "Permission denied", str(self.lock_path))
        with mock.patch("agents.certificate_lifecycle_lock.os.open", side_effect=denied):
            with self.assertRaises(CertificateLifecycleLockBusyError) as raised:
                with CertificateLifecycleFileLock(self.lock_path).acquire(timeout=0.0):
                    self.fail("the lock must never be granted")
        self.assertIs(raised.exception.__cause__, denied)


class TestD1D2_RealTwoProcessContention(_LockTestCase):
    def test_contention_never_leaks_permission_error_nor_orphans_the_lock(self):
        result_queue = multiprocessing.Queue()
        processes = [
            multiprocessing.Process(target=_worker_contend, args=(str(self.lock_path), 2000, result_queue))
            for _ in range(2)
        ]
        for p in processes:
            p.start()
        for p in processes:
            p.join(timeout=240)
            self.assertFalse(p.is_alive(), "worker process did not terminate in time")
            self.assertEqual(p.exitcode, 0)
        results = [result_queue.get(timeout=5) for _ in processes]

        self.assertEqual([r["other"] for r in results], [[], []])
        self.assertEqual(sum(r["acquired"] + r["busy"] for r in results), 4000)
        self.assertGreater(sum(r["acquired"] for r in results), 0)
        self.assertFalse(self.lock_path.exists(), "a cleanly released lock was left on disk")


if __name__ == "__main__":
    unittest.main()
