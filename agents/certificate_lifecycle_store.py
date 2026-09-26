"""
AI DIRECTOR — Certificate Lifecycle Persistence & Restart Recovery
(Phase P3.58)

P3.57's `CertificateLifecycleRegistry` (agents/certificate_lifecycle.py)
is in-memory only, by explicit, documented design at the time -- lost
on process restart. This module closes that gap with a file-backed
store the registry can optionally use (`CertificateLifecycleRegistry
(store=...)`), following exactly the same OPTIONAL-injection shape
`GenerationApprovalGate(provider, executed_request_store=...)` already
uses: default `None` means pure in-memory, zero behavior change for
every existing caller.

AUDIT FINDING (before this module was written):
- `agents/executed_request_store.py::FileExecutedRequestStore` (P2,
  PROTECTED) is the ONLY existing file-persistence mechanism in the
  repository, and the ONLY atomic-write implementation
  (`tempfile.mkstemp` in the same directory + `flush()` + `fsync()` +
  `os.replace()`, with temp-file cleanup on any exception). This
  module independently REPLICATES that exact atomic-write shape --
  never imports `agents/executed_request_store.py` itself, which is a
  P2 replay guard for REAL EXECUTION (a different domain, different
  failure semantics, `PROTECTED_P2_FILES`) with no relationship to a
  purely documentary certificate lifecycle. No other reusable
  persistence/atomic-write utility exists anywhere in `agents/*.py`
  (verified by repository-wide search before writing this module).
- No `threading` import exists anywhere outside
  `agents/certificate_lifecycle.py` (P3.57) itself. Per Section 9 of
  the P3.58 mission, cross-thread write safety is achieved by having
  `CertificateLifecycleRegistry.register()` call
  `store.append_registration()` FROM INSIDE the SAME `threading.Lock`
  it already holds for its in-memory mutation (P3.57, unchanged) --
  this module adds NO lock of its own, and `FileCriticalSectionLock`
  (P2, PROTECTED, guards `create_job()`) is deliberately NOT reused
  here, per the mission's explicit instruction not to couple this
  documentary registry to the execution boundary.

UPDATE -- PHASE P3.59, CERTIFICATE LIFECYCLE INTER-PROCESS CONCURRENCY:
P3.58 left true CROSS-PROCESS concurrent writers as a KNOWN, ACCEPTED,
documented limitation (the paragraph above described the gap). P3.59
demonstrated the gap was real and exploitable (two processes racing
`register()` could both decide the same `sequence` and both believe
they alone were CURRENT, per their own stale in-memory view) and closed
it with `register_certificate()` below, which acquires
`agents/certificate_lifecycle_lock.py::CertificateLifecycleFileLock` (a
NEW, independent, Certificate-Lifecycle-scoped lock -- see that
module's docstring for the audit finding on why
`FileCriticalSectionLock` was not reused) and decides
`sequence`/supersession from a FRESH read taken under that lock, never
from a caller-supplied or previously-cached value. `append_registration()`
remains as a lower-level, NOT cross-process-safe primitive (see its own
docstring) -- kept for the P3.58 tests that exercise the raw write path
directly, and for any future caller that has already established, by
some other means, that it is the only writer.

WHAT IS PERSISTED -- deliberately minimal (Section 2, P3.58 mission):
`certificate_id`, `request_id`, `mission_id`, `status`, `superseded_by`,
`sequence`, `issued_at`. NEVER the certificate's own content (prompt/
asset/VideoPlan identity, cost, integrity digest, ...) -- that content
already belongs exclusively to the certificate object itself (P3.54)
and its own integrity digest (P3.56); duplicating it here would be
exactly the redundant, driftable copy Section 2 forbids. NEVER a
secret, credential, token, or `RealGenerationAuthorization`.

CANONICAL STORAGE FORMAT (Section 3):
    {
      "lifecycle_storage_version": 1,
      "records": {
        "<certificate_id>": {
          "certificate_id": "<certificate_id>",
          "request_id": "...", "mission_id": "..." | null,
          "status": "CURRENT" | "SUPERSEDED",
          "superseded_by": "<certificate_id>" | null,
          "sequence": <int >= 1>,
          "issued_at": "<iso8601>"
        }, ...
      }
    }
Written with `json.dump(..., sort_keys=True, ensure_ascii=True)` --
deterministic byte-for-byte for the same logical state, exactly the
canonical-serialization discipline P3.56 already established for the
certificate itself. `current_by_scope` is intentionally NEVER stored
as a separate structure: it is always RE-DERIVED from `records` on
load (the single source of truth), which is what lets `load()` detect
"duplicate CURRENT for one scope" as the structural impossibility it
is, rather than trusting a second, independently-corruptible pointer.

LOAD / RECOVERY (Section 5) -- exactly three outcomes, never a fourth:
    MISSING file    -> empty initial state (`{}, {}, 0`) -- legitimate,
                        NOT corruption (mirrors
                        `FileExecutedRequestStore.is_executed()`'s own
                        "absence is not corruption" rule).
    VALID file       -> the persisted state, byte-exact.
    ANYTHING ELSE    -> `CertificateLifecycleStoreCorruptedError`,
                        raised, never swallowed, never repaired, never
                        used to silently pick an arbitrary CURRENT.

CORRUPTION MATRIX (Section 6) -- every one of these raises
`CertificateLifecycleStoreCorruptedError` from `load()`, never returns
a guessed value: empty file; malformed JSON; duplicate JSON keys
(`object_pairs_hook`); unknown/missing schema version (NO automatic
migration -- Section 10); a record missing a required field, with the
wrong type, or carrying an unexpected extra field; a record's own key
not matching its `certificate_id`; an invalid `status` value; two
records CURRENT for the same scope; `superseded_by` naming a
certificate_id absent from `records`; `superseded_by` crossing scopes
(cross-request/cross-mission supersession); a CURRENT record with
`superseded_by` set (or a SUPERSEDED one without it); a supersession
cycle; two records sharing one `sequence`; a successor with a
`sequence` not strictly greater than what it superseded.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.certificate_lifecycle import (
    CertificateLifecycleRecord,
    CertificateLifecycleStatus,
    CertificateScope,
)
from agents.certificate_lifecycle_lock import CertificateLifecycleFileLock

LIFECYCLE_STORAGE_VERSION = 1

# Default bounded wait for the cross-process lock used by
# `register_certificate()` (Section 4, P3.59 mission): this store's
# writes are small, synchronous JSON read-modify-writes -- milliseconds,
# never a long-running operation -- so a short bounded poll absorbs a
# benign overlap between two legitimate, fast registrations rather than
# failing on it, while still failing closed once the deadline passes.
DEFAULT_LOCK_TIMEOUT_SECONDS = 2.0

_REQUIRED_RECORD_FIELDS = (
    "certificate_id", "request_id", "mission_id", "status", "superseded_by", "sequence", "issued_at",
)


class CertificateLifecycleStoreCorruptedError(RuntimeError):
    """
    Raised whenever persisted lifecycle state exists but cannot be
    reliably interpreted -- NEVER means "no certificates exist yet"
    (that is the legitimate, non-error "missing file" case). The
    caller must treat this as UNKNOWN/fail-closed, exactly like
    `agents.executed_request_store.ExecutedRequestStoreCorruptedError`
    is treated by `GenerationApprovalGate.evaluate()`.
    """


def _reject_duplicate_keys(pairs):
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key '{key}'")
        result[key] = value
    return result


class FileCertificateLifecycleStore:
    """
    JSON, atomic-write, file-backed persistence for
    `CertificateLifecycleRegistry`. See module docstring for the
    canonical format, load semantics, and corruption matrix. Holds no
    in-memory cache of its own -- every method reads `self.path` fresh.

    Two ways to write, deliberately kept distinct:
    - `append_registration()` (P3.58): a LOW-LEVEL primitive -- writes
      caller-supplied, already-decided records. NOT cross-process safe
      by itself (no lock) -- the caller must already know the correct
      `sequence`/supersession, which is only safe when nothing else can
      be concurrently writing (e.g. tests exercising the raw format).
    - `register_certificate()` (P3.59): the CROSS-PROCESS-SAFE
      operation -- acquires this store's dedicated
      `CertificateLifecycleFileLock`, reads the CURRENT file fresh,
      decides `sequence`/supersession from THAT read (never from any
      caller-supplied or in-memory value), writes atomically, then
      releases. `agents.certificate_lifecycle.CertificateLifecycleRegistry
      .register()` uses this method whenever a store is configured
      (P3.57's registry itself gained no new lock of its own -- Section
      15, reuse the minimum necessary).
    """

    def __init__(self, path: Path, lock_timeout: float = DEFAULT_LOCK_TIMEOUT_SECONDS) -> None:
        self.path = Path(path)
        self.lock_timeout = lock_timeout
        self._lock = CertificateLifecycleFileLock(self.path.parent / f".{self.path.name}.lock")

    def load(self) -> Tuple[Dict[str, CertificateLifecycleRecord], Dict[CertificateScope, str], int]:
        """
        Section 5. `(records, current_by_scope, sequence_counter)`.
        Missing file -> `({}, {}, 0)`, not an error. Present-but-broken
        -> `CertificateLifecycleStoreCorruptedError`, never guessed.
        Read-only -- never takes the write lock (Section 9: a reader
        must never block, or be blocked by, a concurrent writer's
        atomic rename; `os.replace()` guarantees a reader only ever
        sees a fully-formed old or new file, never a torn one).
        """

        if not self.path.exists():
            return {}, {}, 0

        raw_records = self._read_and_validate()
        records = {
            certificate_id: self._raw_to_record(raw) for certificate_id, raw in raw_records.items()
        }
        current_by_scope: Dict[CertificateScope, str] = {
            record.scope: record.certificate_id
            for record in records.values()
            if record.status == CertificateLifecycleStatus.CURRENT
        }
        sequence_counter = max((record.registered_sequence for record in records.values()), default=0)
        return records, current_by_scope, sequence_counter

    def append_registration(
        self,
        new_record: CertificateLifecycleRecord,
        superseded_record: Optional[CertificateLifecycleRecord],
    ) -> None:
        """
        LOW-LEVEL, NOT cross-process safe (see class docstring) --
        read-modify-write, atomic (`tempfile.mkstemp` + `fsync` +
        `os.replace`, independently mirroring
        `FileExecutedRequestStore._write_full()`'s own pattern). Never
        touches any certificate object -- only ever writes the minimal
        lifecycle fields (Section 2/12). Prefer `register_certificate()`
        for any caller that must be safe under concurrent processes.
        """

        self._reject_unpersistable(new_record)
        if superseded_record is not None:
            self._reject_unpersistable(superseded_record)

        raw_records = self._read_raw_records_or_empty()
        raw_records[new_record.certificate_id] = self._record_to_raw(new_record)
        if superseded_record is not None:
            raw_records[superseded_record.certificate_id] = self._record_to_raw(superseded_record)
        self._write_raw_records(raw_records)

    def register_certificate(
        self,
        certificate_id: str,
        request_id: str,
        mission_id: Optional[str],
        issued_at: str,
    ) -> Tuple[CertificateLifecycleRecord, Optional[CertificateLifecycleRecord]]:
        """
        CROSS-PROCESS-SAFE registration (Section 2/6/8, P3.59 mission).
        Accepts plain scalars, not a certificate object -- this module
        has no dependency on
        `agents/production_activation_readiness_certificate.py` and
        this method introduces none (Section 2: persist only what the
        lifecycle needs).

        Order, and why (Section 6): acquire lock -> read+validate the
        CURRENT file (never a caller-supplied or previously-cached
        sequence/current -- Section 8: the only way to guarantee a
        globally unique `sequence` across processes) -> decide
        idempotency/sequence/supersession from that fresh read ->
        atomic write -> release lock. Deciding BEFORE re-reading, or
        writing before deciding, would reopen exactly the race this
        method exists to close.

        Idempotent: if `certificate_id` already exists in the file
        (registered by this process or another one), returns
        `(existing_record, None)` unchanged -- never re-supersedes,
        never duplicates, never re-derives a different sequence for an
        id that already has one.
        """

        with self._lock.acquire(timeout=self.lock_timeout):
            raw_records = self._read_raw_records_or_empty()

            existing_raw = raw_records.get(certificate_id)
            if existing_raw is not None:
                return self._raw_to_record(existing_raw), None

            scope = (request_id, mission_id)
            sequence = 1 + max((raw["sequence"] for raw in raw_records.values()), default=0)

            previous_current_key = next(
                (
                    key
                    for key, raw in raw_records.items()
                    if raw["status"] == CertificateLifecycleStatus.CURRENT.value
                    and (raw["request_id"], raw["mission_id"]) == scope
                ),
                None,
            )

            superseded_record: Optional[CertificateLifecycleRecord] = None
            if previous_current_key is not None:
                superseded_raw = dict(raw_records[previous_current_key])
                superseded_raw["status"] = CertificateLifecycleStatus.SUPERSEDED.value
                superseded_raw["superseded_by"] = certificate_id
                raw_records[previous_current_key] = superseded_raw
                superseded_record = self._raw_to_record(superseded_raw)

            new_record = CertificateLifecycleRecord(
                certificate_id=certificate_id,
                scope=scope,
                status=CertificateLifecycleStatus.CURRENT,
                superseded_by=None,
                registered_sequence=sequence,
                issued_at=issued_at,
            )
            self._reject_unpersistable(new_record)
            raw_records[certificate_id] = self._record_to_raw(new_record)

            self._write_raw_records(raw_records)
            return new_record, superseded_record

    @staticmethod
    def _raw_to_record(raw: Dict[str, Any]) -> CertificateLifecycleRecord:
        return CertificateLifecycleRecord(
            certificate_id=raw["certificate_id"],
            scope=(raw["request_id"], raw["mission_id"]),
            status=CertificateLifecycleStatus(raw["status"]),
            superseded_by=raw["superseded_by"],
            registered_sequence=raw["sequence"],
            issued_at=raw["issued_at"],
        )

    # ------------------------------------------------------------------
    # Internal: read + validate (Section 6 corruption matrix)
    # ------------------------------------------------------------------

    def _read_raw_records_or_empty(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {}
        return self._read_and_validate()

    def _read_and_validate(self) -> Dict[str, Any]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as error:
            raise CertificateLifecycleStoreCorruptedError(
                f"lifecycle storage at '{self.path}' could not be read: {error}"
            ) from error

        try:
            data = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
        except (ValueError, json.JSONDecodeError) as error:
            raise CertificateLifecycleStoreCorruptedError(
                f"lifecycle storage at '{self.path}' is not valid JSON: {error}"
            ) from error

        if not isinstance(data, dict):
            raise CertificateLifecycleStoreCorruptedError(
                f"lifecycle storage at '{self.path}' has an unexpected top-level shape "
                f"(expected a JSON object)."
            )

        version = data.get("lifecycle_storage_version")
        if version != LIFECYCLE_STORAGE_VERSION:
            raise CertificateLifecycleStoreCorruptedError(
                f"lifecycle storage at '{self.path}' has schema version {version!r}, "
                f"expected exactly {LIFECYCLE_STORAGE_VERSION} -- no automatic migration "
                f"is performed (Section 10, P3.58 mission)."
            )

        raw_records = data.get("records")
        if not isinstance(raw_records, dict):
            raise CertificateLifecycleStoreCorruptedError(
                f"lifecycle storage at '{self.path}' is missing a 'records' object."
            )

        self._validate_records_shape(raw_records)
        self._validate_semantic_consistency(raw_records)
        return raw_records

    def _validate_records_shape(self, raw_records: Dict[str, Any]) -> None:
        for key, raw in raw_records.items():
            if not isinstance(raw, dict):
                raise CertificateLifecycleStoreCorruptedError(
                    f"lifecycle storage record '{key}' is not a JSON object."
                )

            missing = [field for field in _REQUIRED_RECORD_FIELDS if field not in raw]
            if missing:
                raise CertificateLifecycleStoreCorruptedError(
                    f"lifecycle storage record '{key}' is missing required field(s): {missing}."
                )
            extra = sorted(set(raw.keys()) - set(_REQUIRED_RECORD_FIELDS))
            if extra:
                raise CertificateLifecycleStoreCorruptedError(
                    f"lifecycle storage record '{key}' has unexpected field(s): {extra}."
                )

            if not isinstance(raw["certificate_id"], str) or not raw["certificate_id"]:
                raise CertificateLifecycleStoreCorruptedError(
                    f"lifecycle storage record '{key}' has an invalid 'certificate_id'."
                )
            if raw["certificate_id"] != key:
                raise CertificateLifecycleStoreCorruptedError(
                    f"lifecycle storage record key '{key}' does not match its own "
                    f"certificate_id '{raw['certificate_id']}'."
                )
            if not isinstance(raw["request_id"], str) or not raw["request_id"]:
                raise CertificateLifecycleStoreCorruptedError(
                    f"lifecycle storage record '{key}' has an invalid 'request_id'."
                )
            if raw["mission_id"] is not None and not isinstance(raw["mission_id"], str):
                raise CertificateLifecycleStoreCorruptedError(
                    f"lifecycle storage record '{key}' has an invalid 'mission_id'."
                )
            if raw["status"] not in (
                CertificateLifecycleStatus.CURRENT.value,
                CertificateLifecycleStatus.SUPERSEDED.value,
            ):
                raise CertificateLifecycleStoreCorruptedError(
                    f"lifecycle storage record '{key}' has an invalid status {raw['status']!r}."
                )
            if raw["superseded_by"] is not None and (
                not isinstance(raw["superseded_by"], str) or not raw["superseded_by"]
            ):
                raise CertificateLifecycleStoreCorruptedError(
                    f"lifecycle storage record '{key}' has an invalid 'superseded_by'."
                )
            if isinstance(raw["sequence"], bool) or not isinstance(raw["sequence"], int) or raw["sequence"] < 1:
                raise CertificateLifecycleStoreCorruptedError(
                    f"lifecycle storage record '{key}' has an invalid 'sequence' "
                    f"(expected a positive integer)."
                )
            if not isinstance(raw["issued_at"], str) or not raw["issued_at"]:
                raise CertificateLifecycleStoreCorruptedError(
                    f"lifecycle storage record '{key}' has an invalid 'issued_at'."
                )

    def _validate_semantic_consistency(self, raw_records: Dict[str, Any]) -> None:
        # CURRENT must never carry a superseded_by; SUPERSEDED always must.
        for key, raw in raw_records.items():
            if raw["status"] == CertificateLifecycleStatus.CURRENT.value and raw["superseded_by"] is not None:
                raise CertificateLifecycleStoreCorruptedError(
                    f"lifecycle storage record '{key}' is CURRENT but names a 'superseded_by' "
                    f"-- a CURRENT record can never have been superseded."
                )
            if raw["status"] == CertificateLifecycleStatus.SUPERSEDED.value and raw["superseded_by"] is None:
                raise CertificateLifecycleStoreCorruptedError(
                    f"lifecycle storage record '{key}' is SUPERSEDED but names no "
                    f"'superseded_by' successor."
                )
            if raw["superseded_by"] == key:
                raise CertificateLifecycleStoreCorruptedError(
                    f"lifecycle storage record '{key}' names itself as its own 'superseded_by' "
                    f"(supersession cycle)."
                )

        # At most one CURRENT per (request_id, mission_id) scope.
        current_scopes: Dict[CertificateScope, str] = {}
        for key, raw in raw_records.items():
            if raw["status"] != CertificateLifecycleStatus.CURRENT.value:
                continue
            scope = (raw["request_id"], raw["mission_id"])
            if scope in current_scopes:
                raise CertificateLifecycleStoreCorruptedError(
                    f"lifecycle storage has two CURRENT records for the same scope {scope}: "
                    f"'{current_scopes[scope]}' and '{key}'."
                )
            current_scopes[scope] = key

        # No two records share one sequence number.
        sequences_seen: Dict[int, str] = {}
        for key, raw in raw_records.items():
            sequence = raw["sequence"]
            if sequence in sequences_seen:
                raise CertificateLifecycleStoreCorruptedError(
                    f"lifecycle storage has two records sharing sequence {sequence}: "
                    f"'{sequences_seen[sequence]}' and '{key}'."
                )
            sequences_seen[sequence] = key

        # superseded_by must name a real record, in the SAME scope, with
        # a strictly later sequence -- and following the chain from any
        # record must terminate at a CURRENT one within a bounded number
        # of hops (never an unbroken/cyclic chain among SUPERSEDED-only
        # records).
        for key, raw in raw_records.items():
            successor_id = raw["superseded_by"]
            if successor_id is None:
                continue
            successor = raw_records.get(successor_id)
            if successor is None:
                raise CertificateLifecycleStoreCorruptedError(
                    f"lifecycle storage record '{key}' has 'superseded_by' pointing to "
                    f"'{successor_id}', which does not exist."
                )
            this_scope = (raw["request_id"], raw["mission_id"])
            successor_scope = (successor["request_id"], successor["mission_id"])
            if this_scope != successor_scope:
                raise CertificateLifecycleStoreCorruptedError(
                    f"lifecycle storage record '{key}' (scope {this_scope}) is superseded_by "
                    f"'{successor_id}' (scope {successor_scope}) -- cross-scope supersession."
                )
            if successor["sequence"] <= raw["sequence"]:
                raise CertificateLifecycleStoreCorruptedError(
                    f"lifecycle storage record '{key}' (sequence {raw['sequence']}) is "
                    f"superseded_by '{successor_id}' (sequence {successor['sequence']}) -- a "
                    f"successor must have a strictly greater sequence."
                )

            visited = {key}
            cursor = successor_id
            for _ in range(len(raw_records) + 1):
                if cursor in visited:
                    raise CertificateLifecycleStoreCorruptedError(
                        f"lifecycle storage has a supersession cycle reachable from '{key}'."
                    )
                visited.add(cursor)
                cursor_raw = raw_records[cursor]
                if cursor_raw["status"] == CertificateLifecycleStatus.CURRENT.value:
                    break
                cursor = cursor_raw["superseded_by"]
                if cursor is None:
                    raise CertificateLifecycleStoreCorruptedError(
                        f"lifecycle storage has a broken supersession chain reachable from '{key}'."
                    )
            else:
                raise CertificateLifecycleStoreCorruptedError(
                    f"lifecycle storage has a supersession chain reachable from '{key}' that "
                    f"never terminates at a CURRENT record."
                )

    # ------------------------------------------------------------------
    # Internal: write (Section 4, atomic)
    # ------------------------------------------------------------------

    def _reject_unpersistable(self, record: CertificateLifecycleRecord) -> None:
        """P3.72: the writer enforces EXACTLY the reader's own shape rules
        (`_validate_records_shape`) BEFORE anything is written. A record
        the reader would reject (e.g. request_id None/'' or a non-str
        mission_id) would otherwise poison the whole file: every later
        load/register would fail as corrupted. Raises `TypeError` for a
        wrongly-typed scope (the refusal P3.68 already pins for non-str
        scopes), `ValueError` otherwise -- never
        `CertificateLifecycleStoreCorruptedError`: nothing on disk is
        corrupted, the caller's input is refused."""

        raw = self._record_to_raw(record)
        try:
            self._validate_records_shape({raw["certificate_id"]: raw})
        except CertificateLifecycleStoreCorruptedError as error:
            wrong_scope_type = not isinstance(raw["request_id"], str) or not (
                raw["mission_id"] is None or isinstance(raw["mission_id"], str)
            )
            refusal = TypeError if wrong_scope_type else ValueError
            raise refusal(f"refusing to persist an invalid lifecycle record: {error}") from None

    @staticmethod
    def _record_to_raw(record: CertificateLifecycleRecord) -> Dict[str, Any]:
        return {
            "certificate_id": record.certificate_id,
            "request_id": record.scope[0],
            "mission_id": record.scope[1],
            "status": record.status.value,
            "superseded_by": record.superseded_by,
            "sequence": record.registered_sequence,
            "issued_at": record.issued_at,
        }

    def _write_raw_records(self, raw_records: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        data = {"lifecycle_storage_version": LIFECYCLE_STORAGE_VERSION, "records": raw_records}

        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.path.parent),
            prefix=".tmp-certificate-lifecycle-",
            suffix=".json",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True, ensure_ascii=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
