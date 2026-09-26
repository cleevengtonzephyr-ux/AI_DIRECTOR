"""
AI DIRECTOR — Certificate Lifecycle File Lock (Phase P3.59)

P3.58 documented, as a known and accepted limitation, that two
independent OS PROCESSES writing to the same Certificate Lifecycle
store file could race: each decides its next `sequence`/CURRENT status
from its OWN process-local in-memory view, then does an independent
read-modify-write against the file -- a classic lost-update / duplicate-
CURRENT / sequence-collision hazard whenever both processes' writes
interleave. This module provides the minimal locking primitive needed
to close that gap; `agents/certificate_lifecycle_store.py` uses it to
make the FULL decide-then-write sequence atomic across processes (see
that module's `register_certificate()`).

AUDIT FINDING -- WHY NOT REUSE `FileCriticalSectionLock`
(agents/critical_section_lock.py, Phase P2.20):
Its actual MECHANISM (`os.open(path, O_CREAT | O_EXCL | O_RDWR)`,
non-blocking, released in `finally`) is genuinely generic -- nothing in
its CODE references `create_job()`, `GenerationJobService`, or any P2
symbol. It was still NOT reused, for two independent, concrete
reasons, not just narrative caution:
1. It is a `PROTECTED_P2_FILES` entry (agents/canonical_architecture_
   contract.py) -- P2.20's own docstring frames it as the lock for
   EXACTLY the `check-not-executed -> approval -> create_job() ->
   mark_executed()` critical section, and the mission for this phase
   explicitly warns against coupling a documentary registry to that
   boundary "simply because it exists".
2. MECHANICALLY confirmed, not just asserted: `agents.canonical_
   architecture_contract.CONSTRUCTOR_ALLOWLIST["FileCriticalSectionLock"]`
   is `frozenset({"director.py"})` -- `agents.architecture_drift_
   detector.ArchitectureDriftDetector._check_no_unauthorized_authority_
   construction()` would flag ANY construction of
   `FileCriticalSectionLock(...)` outside `director.py` as a CRITICAL
   `AUTHORITY_CONSTRUCTOR_OUTSIDE_ALLOWLIST` finding. Reusing it here
   would either break `NO_DRIFT` or require widening a P2-authority
   construction allowlist for a non-P2, purely documentary module --
   exactly the kind of production-authority-boundary change Section 20
   of the mission requires a STOP before making. A new, independent,
   Certificate-Lifecycle-scoped lock avoids both problems entirely.

WHAT THIS LOCK IS NOT AND NEVER DOES:
- Never imports, constructs, or references anything from
  `agents/critical_section_lock.py`, `agents/generation_job_service.py`,
  `agents/generation_approval_gate.py`, or any other P2 execution
  module -- this file has zero imports beyond the Python standard
  library.
- Never calls Provider/`execute()`/`create_job()`, never constructs a
  `RealGenerationAuthorization`/activation/approval object.
- Grants no authority of any kind -- holding this lock proves nothing
  more than "no other process is, right now, in the middle of writing
  to this exact Certificate Lifecycle file".

STALE LOCK POLICY (Section 4/5, P3.59 mission) -- FAIL-CLOSED, exactly
like `FileCriticalSectionLock`'s own documented stance: a process that
crashes while holding this lock leaves an orphaned lock file. This
module writes diagnostic content into the lock file (`pid`,
`acquired_at`) purely as FORENSIC information surfaced in the busy
error message -- it is NEVER read back to make an automatic staleness
decision. Cross-platform PID-liveness detection (would a `kill(pid, 0)`-
style check even be meaningful on Windows without a third-party
dependency like `psutil`, which this codebase does not use anywhere)
is deliberately NOT attempted: an unverifiable guess is worse than an
honest, fail-closed refusal requiring a human to look at the lock
file's diagnostic content and decide.

TIMEOUT (Section 4): default `timeout=0.0` reproduces
`FileCriticalSectionLock`'s exact non-blocking behavior. A caller may
pass a small positive `timeout` to poll briefly for a lock held by a
fast, legitimate concurrent registration (this store's writes are
small, synchronous JSON writes -- milliseconds, not the
potentially-long-running `create_job()` P2.20 deliberately never waits
for) -- still bounded, still fails closed with
`CertificateLifecycleLockBusyError` if the deadline is reached.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class CertificateLifecycleLockBusyError(RuntimeError):
    """
    Raised when the Certificate Lifecycle lock cannot be acquired
    within `timeout` -- another process (or another un-exited `with`
    block in this same process) currently holds it, or a previous
    holder crashed without releasing it. FAIL CLOSED: never retried
    beyond the caller's own `timeout`, never auto-resolved.
    """


class CertificateLifecycleFileLock:
    """
    Minimal, dedicated, file-based mutual-exclusion lock scoped
    EXCLUSIVELY to one Certificate Lifecycle store file. See module
    docstring for why this is independent from
    `agents/critical_section_lock.py`.
    """

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = Path(lock_path)

    @contextmanager
    def acquire(self, timeout: float = 0.0, poll_interval: float = 0.02):
        """
        Non-blocking by default (`timeout=0.0`), exactly like
        `FileCriticalSectionLock.acquire()`. With `timeout > 0`, polls
        every `poll_interval` seconds until acquired or the deadline
        passes -- still bounded, still fail-closed at the end. Always
        released in `finally`, even on an exception raised inside the
        `with` block.
        """

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + max(timeout, 0.0)

        fd = None
        while fd is None:
            try:
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            except FileExistsError as error:
                if time.monotonic() >= deadline:
                    raise CertificateLifecycleLockBusyError(
                        f"Certificate lifecycle lock '{self.lock_path}' is already held "
                        f"-- refusing to proceed (fail-closed, no automatic staleness "
                        f"recovery). {self._diagnostic_summary()}"
                    ) from error
                time.sleep(poll_interval)

        try:
            self._write_diagnostics(fd)
            yield
        finally:
            try:
                os.close(fd)
            finally:
                try:
                    self.lock_path.unlink()
                except OSError:
                    # Already gone (e.g. removed manually while held) --
                    # nothing more to do; never masks an exception raised
                    # inside the `with` block, which propagates normally.
                    pass

    @staticmethod
    def _write_diagnostics(fd: int) -> None:
        """Best-effort only (Section 4): a failure here never prevents
        the lock itself from working -- the mutual exclusion is the
        actual guarantee; this payload is forensic sugar for a human
        investigating a busy/stale lock."""

        try:
            payload = json.dumps(
                {"pid": os.getpid(), "acquired_at": datetime.now(timezone.utc).isoformat()}
            ).encode("utf-8")
            os.write(fd, payload)
        except OSError:
            pass

    def _diagnostic_summary(self) -> str:
        """Best-effort, NEVER raises, NEVER used to make an automatic
        decision -- purely to enrich the busy-error message for a human
        (malformed lock content is explicitly tolerated, never itself
        an additional failure)."""

        try:
            raw = self.lock_path.read_text(encoding="utf-8")
        except OSError:
            return "Lock file could not be read for diagnostics."
        if not raw:
            return "Lock file is present but empty (no diagnostic content)."
        try:
            data = json.loads(raw)
        except ValueError:
            return "Lock file content is not valid diagnostic JSON (possibly malformed)."
        if not isinstance(data, dict):
            return "Lock file content has an unexpected shape."
        return f"Lock appears held by pid={data.get('pid', 'unknown')!r}, acquired_at={data.get('acquired_at', 'unknown')!r}."
