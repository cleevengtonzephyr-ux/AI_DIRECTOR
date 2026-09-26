"""
AI DIRECTOR — Certificate Lifecycle & Supersession Boundary (Phase P3.57)

P3.54 answers "was a certificate issued?". P3.55 answers "does it still
match current state?" (freshness). P3.56 answers "is its content
unaltered, and who claims to have issued it?" (integrity/provenance).
None of them answer a question that only arises once MULTIPLE
certificates exist for the same request: "which one, among several
historically valid certificates, is THE one that represents the latest
preflight for this scope?" This module answers that -- and only that.

DEFINITIONS (Section 1, P3.57 mission) -- never merged:

    ISSUED      -- a certificate freshly returned by
                   `ProductionActivationReadinessCertificateIssuer.issue()`
                   (P3.54, untouched by this phase).
    CURRENT     -- the certificate this registry considers to represent
                   the latest known preflight for its scope.
    SUPERSEDED  -- a historically valid certificate that has been
                   replaced, for the SAME scope, by a later CURRENT one.
    STALE       -- P3.55's concept (content no longer matches presented
                   state) -- NOT redefined here, NOT a lifecycle value.
    INVALID     -- P3.56's concept (integrity/provenance/structure
                   failure) -- NOT redefined here, NOT a lifecycle value.
    UNKNOWN     -- lifecycle cannot be reliably determined (never
                   certificate this registry has seen, or an internal
                   inconsistency was detected) -- fail-closed, never
                   guessed.
    AUTHORITY   -- a wholly separate permission held exclusively by the
                   existing P2 production mechanisms. Nothing here
                   grants, checks, or substitutes for it.

CURRENT NEVER MEANS APPROVED/AUTHORIZED/ACTIVATED/EXECUTABLE. A
`CURRENT` lifecycle status is a documentary bookkeeping fact about
WHICH certificate is the latest for its scope -- nothing more.

AUDIT FINDING (repository-wide, before this module was written):
- No existing versioning/lifecycle mechanism tracks MULTIPLE
  certificates over time. `agents/mission_state_machine.py` versions
  MISSION states (a different concept: state TRANSITIONS of one
  mission, guarded by `InvalidMissionTransitionError`/
  `StateConflictError`/`DuplicateTransitionError`) -- its
  `STATE_MACHINE_VERSION = 1` convention is followed here
  (`LIFECYCLE_VERSION = 1`), its transition machinery is not reused
  (different problem: supersession among independent proof objects,
  not state transitions of one mission).
- `agents/executed_request_store.py` (P2, PROTECTED) offers exactly the
  architectural SHAPE this phase needs -- an `InMemoryExecutedRequestStore`
  (dict/set-based, lost on restart, the GenerationApprovalGate default)
  alongside a `FileExecutedRequestStore` (JSON, atomic-write, survives
  restart) -- but it is NEVER imported or reused directly: it is a P2
  replay guard for REAL EXECUTION, a different domain (Section 2,
  P3.31 architecture doctrine) with different failure semantics
  (`ExecutedRequestStoreCorruptedError`, `EXECUTION_STATE_UNKNOWN`).
  This module mirrors its SHAPE (in-memory by default, one class, a
  deterministic sequence counter in place of wall-clock time) without
  depending on it.
- No `threading.Lock` (or any `threading` import) exists anywhere in
  `agents/*.py`; the ONLY concurrency-safety mechanism in the
  repository is `agents/critical_section_lock.py`'s
  `FileCriticalSectionLock` (P2, PROTECTED, file-based, guards
  cross-PROCESS mutual exclusion around `create_job()`). Reusing it
  here would pull a purely documentary, in-memory registry into the P2
  execution boundary for no reason (Section 7/14 of the mission
  explicitly forbid inventing a *second* critical-section mechanism
  only when an existing one is a genuine fit -- it is not: this
  registry has no file, no cross-process concern, and no relationship
  to `create_job()`). A single `threading.Lock` guarding this
  registry's own in-memory dict is the smallest sufficient mechanism
  for the only concurrency this phase's scope actually has:
  same-process, multiple threads.

PERSISTENCE (Section 8, P3.57 mission -- documented, not implemented):
This registry is IN-MEMORY ONLY, lost on process restart, matching
`InMemoryExecutedRequestStore`'s own precedent and the certificate
Issuer itself (P3.54's `issue()` never persists anything). A
file-backed variant analogous to `FileExecutedRequestStore` is a
plausible FUTURE phase, structurally anticipated by keeping this
registry's public surface small and swappable -- but is NOT built here:
no disk format has been reviewed, no atomicity/corruption story
designed, and inventing one un-requested would be exactly the kind of
unjustified complexity Section 14 forbids. `tests/test_certificate_
lifecycle.py` tests the CURRENT, honest behavior instead: a fresh
registry (simulating a restart) has no memory of anything registered
in a previous one -- `UNKNOWN`/`None`, fail-closed, never fabricated.

WHAT THIS MODULE IS NOT AND NEVER DOES (same posture as P3.54/55/56):
- Never constructs a Gate/Evaluator/Issuer/Provider/Authorization/
  Activation object; never imports a P2 execution module; never calls
  `create_job()`, `.execute()`, `prepare_activation()`,
  `validate_activation()`, or `consume()`.
- Never mutates a `ProductionActivationReadinessCertificate` -- lifecycle
  status lives in a SEPARATE `CertificateLifecycleRecord`, itself
  frozen, never rewritten in place (Section 5): "superseding" a
  certificate replaces its RECORD in the registry's dict with a new,
  separate frozen record; the certificate object itself, and every
  earlier record, is never touched.
- Never deletes a record. Supersession is additive bookkeeping, never
  history loss (Section 3: "Ne jamais supprimer automatiquement C1").
- `CURRENT`/`SUPERSEDED`/`UNKNOWN` here says NOTHING about integrity,
  provenance, or freshness (Section 9) -- combine with
  `agents.certificate_verification`/`agents.certificate_integrity`
  independently; this module never imports either, and never will
  need to, to answer its one question.
- Never wired into `director.py` or any existing entry point.

PERSISTENCE (Phase P3.58, `agents/certificate_lifecycle_store.py`):
`CertificateLifecycleRegistry` optionally accepts a `store` implementing
`CertificateLifecycleStoreProtocol` below (default `None` -- pure
in-memory, byte-for-byte the P3.57 behavior, zero regression for every
existing caller/test that constructs `CertificateLifecycleRegistry()`
with no argument). This module never imports
`agents/certificate_lifecycle_store.py` itself (that would invert the
dependency direction for no reason -- the store depends on this
module's types, not the other way around); the `Protocol` below is the
full, minimal interface contract instead.
"""

from __future__ import annotations

import dataclasses
import sys
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Protocol, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.production_activation_readiness_certificate import ProductionActivationReadinessCertificate

LIFECYCLE_VERSION = 1

# Scope identity (Section 2, P3.57 mission): request_id + mission_id,
# always both -- P3.55's own freshness verifier already treats any
# mission_id difference as a MISMATCH (agents/certificate_verification.py),
# confirming mission_id is already load-bearing identity in this
# codebase. No new scope concept is invented; `None` is simply a valid,
# comparable `mission_id` value (exactly as P3.54's own
# `test_mission_id_optional` already established).
CertificateScope = Tuple[str, Optional[str]]


def certificate_scope(certificate: ProductionActivationReadinessCertificate) -> CertificateScope:
    """Never mutates `certificate`. Raises `TypeError` for anything
    that is not a real certificate -- fail-closed, never guesses a
    scope for an unrelated object."""

    if not isinstance(certificate, ProductionActivationReadinessCertificate):
        raise TypeError(
            "certificate_scope() requires a ProductionActivationReadinessCertificate instance."
        )
    return (certificate.request_id, certificate.mission_id)


class CertificateLifecycleStatus(str, Enum):
    """Only the three values this module actually needs to add --
    STALE/INVALID already belong to P3.55/P3.56 and are never
    redefined here (Section 9)."""

    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CertificateLifecycleRecord:
    """
    Immutable. Represents ONE certificate's lifecycle bookkeeping at a
    point in time -- never the certificate itself (Section 5:
    `request_id`/`mission_id`/prompt/asset/VideoPlan/cost/`issued_at`/
    issuer/integrity digest all remain exclusively on the certificate,
    untouched). Superseding a certificate produces a NEW record (via
    `dataclasses.replace()`), never mutates this one.
    """

    certificate_id: str
    scope: CertificateScope
    status: CertificateLifecycleStatus
    superseded_by: Optional[str]
    registered_sequence: int
    issued_at: str


class CertificateLifecycleStoreProtocol(Protocol):
    """
    The full, minimal interface a P3.58/P3.59 persistence store must
    offer -- this module depends only on this shape, never on a
    concrete store class (see PERSISTENCE note in the module
    docstring). `register_certificate` (P3.59) is used, when the
    injected store implements it, for CROSS-PROCESS-safe registration
    (agents/certificate_lifecycle_store.py); `register()` below falls
    back to `append_registration` (P3.58) for any store that does not.
    """

    def load(self) -> Tuple[Dict[str, CertificateLifecycleRecord], Dict[CertificateScope, str], int]:
        ...

    def append_registration(
        self,
        new_record: CertificateLifecycleRecord,
        superseded_record: Optional[CertificateLifecycleRecord],
    ) -> None:
        ...

    def register_certificate(
        self,
        certificate_id: str,
        request_id: str,
        mission_id: Optional[str],
        issued_at: str,
    ) -> Tuple[CertificateLifecycleRecord, Optional[CertificateLifecycleRecord]]:
        ...


class CertificateLifecycleRegistry:
    """
    In-memory, process-local, thread-safe (Section 7) bookkeeping of
    which certificate is CURRENT for a given scope, and which earlier
    certificates it SUPERSEDED. Deliberately holds no reference to any
    Gate/Evaluator/Issuer/Provider -- `register()` accepts an
    ALREADY-ISSUED certificate, exactly like P3.55's/P3.56's verifiers
    accept already-issued certificates. See module docstring for what
    this is not and does not do.

    "Current" is decided by REGISTRATION ORDER (a monotonic in-process
    counter under the same lock as the mutation it orders), never by
    comparing `issued_at` wall-clock strings (Section 6: "ne pas
    utiliser uniquement l'heure système si cela crée des ambiguïtés") --
    this makes concurrent registration for the same scope from
    multiple threads unambiguous: exactly one of the two calls
    physically completes second, and it deterministically wins.
    """

    def __init__(self, store: Optional[CertificateLifecycleStoreProtocol] = None) -> None:
        self._lock = threading.Lock()
        self._records: Dict[str, CertificateLifecycleRecord] = {}
        self._current_by_scope: Dict[CertificateScope, str] = {}
        self._sequence_counter = 0
        self._store = store

    def register(self, certificate: ProductionActivationReadinessCertificate) -> CertificateLifecycleRecord:
        """
        Registers `certificate` as CURRENT for its scope. If another
        certificate was already CURRENT for that exact scope, its
        record is replaced (never mutated in place, via
        `dataclasses.replace()`) with a SUPERSEDED copy pointing at
        `certificate.certificate_id` -- the superseded certificate
        itself, and its record's other fields, are otherwise
        unchanged. Re-registering the SAME `certificate_id` is
        idempotent: returns the existing record unchanged, never
        re-supersedes anything, never creates a second entry.

        If a `store` was supplied at construction that implements
        `register_certificate` (P3.59, agents/certificate_lifecycle_
        store.py::FileCertificateLifecycleStore), sequence/supersession
        are decided by the STORE from a FRESH read taken under its own
        cross-process lock -- never from this process's own, possibly
        stale, in-memory counter (this is what makes `register()`
        cross-process safe: see that module's docstring for the race
        P3.58 left open and how P3.59 closes it). A store that only
        implements the older `append_registration` (P3.58) still works
        exactly as before -- single-process-safe only, as documented at
        the time. Either way, persistence happens BEFORE the in-memory
        state is updated -- a persistence failure therefore leaves this
        registry's in-memory state completely untouched (never a
        partial commit, memory and disk never diverge) and propagates
        to the caller.

        Never calls Provider/`execute()`/`create_job()`, never
        constructs a `RealGenerationAuthorization`/activation/approval
        object -- pure bookkeeping.
        """

        if not isinstance(certificate, ProductionActivationReadinessCertificate):
            raise TypeError(
                "register() requires a ProductionActivationReadinessCertificate instance."
            )
        if not certificate.certificate_id:
            raise ValueError("register() requires a certificate with a non-empty certificate_id.")

        scope = certificate_scope(certificate)

        with self._lock:
            existing = self._records.get(certificate.certificate_id)
            if existing is not None:
                return existing

            superseded_record: Optional[CertificateLifecycleRecord]

            if self._store is not None and hasattr(self._store, "register_certificate"):
                new_record, superseded_record = self._store.register_certificate(
                    certificate_id=certificate.certificate_id,
                    request_id=scope[0],
                    mission_id=scope[1],
                    issued_at=certificate.issued_at,
                )
            else:
                sequence = self._sequence_counter + 1
                previous_current_id = self._current_by_scope.get(scope)
                superseded_record = None
                if previous_current_id is not None:
                    superseded_record = dataclasses.replace(
                        self._records[previous_current_id],
                        status=CertificateLifecycleStatus.SUPERSEDED,
                        superseded_by=certificate.certificate_id,
                    )

                new_record = CertificateLifecycleRecord(
                    certificate_id=certificate.certificate_id,
                    scope=scope,
                    status=CertificateLifecycleStatus.CURRENT,
                    superseded_by=None,
                    registered_sequence=sequence,
                    issued_at=certificate.issued_at,
                )

                if self._store is not None:
                    self._store.append_registration(new_record, superseded_record)

            self._sequence_counter = max(self._sequence_counter, new_record.registered_sequence)
            if superseded_record is not None:
                self._records[superseded_record.certificate_id] = superseded_record
            self._records[certificate.certificate_id] = new_record
            self._current_by_scope[scope] = certificate.certificate_id
            return new_record

    def hydrate_from_store(self) -> None:
        """
        Explicit, opt-in reload of this registry's in-memory state from
        `store` (Section 5, P3.58 mission: never automatic, never
        silent -- there is no call to this method anywhere except a
        caller's own explicit choice, and none of this module's own
        code calls it). Raises whatever `store.load()` raises on
        corruption (e.g. `CertificateLifecycleStoreCorruptedError`,
        agents/certificate_lifecycle_store.py) -- fail-closed,
        propagated to the caller exactly like
        `ExecutedRequestStoreCorruptedError` propagates out of
        `FileExecutedRequestStore` for `GenerationApprovalGate` to
        handle. Only safe to call before any `register()` call on this
        instance -- raises `RuntimeError` otherwise, to avoid silently
        discarding already-registered in-memory records.
        """

        if self._store is None:
            raise ValueError("hydrate_from_store() requires a store to have been supplied at construction.")

        with self._lock:
            if self._records:
                raise RuntimeError(
                    "hydrate_from_store() must be called before any register() call on "
                    "this registry instance -- it would otherwise silently discard "
                    "already-registered in-memory records."
                )
            records, current_by_scope, sequence_counter = self._store.load()
            self._records = dict(records)
            self._current_by_scope = dict(current_by_scope)
            self._sequence_counter = sequence_counter

    def record_for(self, certificate_id: str) -> Optional[CertificateLifecycleRecord]:
        """`None` if this exact `certificate_id` was never registered
        with THIS registry instance -- fail-closed, never guessed."""

        with self._lock:
            return self._records.get(certificate_id)

    def status_of(self, certificate_id: str) -> CertificateLifecycleStatus:
        """Keyed by `certificate_id` ONLY (P3.73): answers for the scope
        recorded at registration, never for a scope the caller presents.
        A caller holding a certificate object must also compare
        `record_for(id).scope` with `certificate_scope(certificate)` and
        check integrity -- this status alone never binds a mission."""

        record = self.record_for(certificate_id)
        return CertificateLifecycleStatus.UNKNOWN if record is None else record.status

    def current_record_for(self, scope: CertificateScope) -> Optional[CertificateLifecycleRecord]:
        """
        `None` if no certificate is currently registered as CURRENT
        for `scope` ("missing current certificate", Section 10) --
        including the defensive case where the internal pointer names
        a certificate_id whose own record does not (or no longer)
        say CURRENT ("corrupted lifecycle metadata", Section 10/11):
        this is NEVER repaired or guessed at, only reported as absent.
        """

        with self._lock:
            certificate_id = self._current_by_scope.get(scope)
            if certificate_id is None:
                return None
            record = self._records.get(certificate_id)
            if record is None or record.status != CertificateLifecycleStatus.CURRENT:
                return None
            return record

    def history_for(self, scope: CertificateScope) -> Tuple[CertificateLifecycleRecord, ...]:
        """Every record ever registered for `scope`, in registration
        order -- oldest first, nothing ever removed (Section 3)."""

        with self._lock:
            records = [record for record in self._records.values() if record.scope == scope]
        return tuple(sorted(records, key=lambda record: record.registered_sequence))
