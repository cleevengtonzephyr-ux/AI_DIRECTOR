"""Mock-only G2 approval store schema v4 with one-time enrollment invitations.

This is a fresh-file schema. It does not migrate or modify schema v3: the v3
store continues to reject a v4 database, ``initialize`` never reuses an
existing file, and opening accepts only a file whose objects are exactly
those of schema v4. The inherited approval-request operations use the same
immutable v3 contract plus the invitation table.

This module is storage machinery only. It authenticates no administrator,
creates no real account or WebAuthn credential, proves no person's identity,
and must not be exposed as an administration interface or connected to a
Provider. The caller supplies an explicit absolute expiry timestamp; no
lifetime is chosen here.
"""

from __future__ import annotations

import functools
import hashlib
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from approval_service import approval_store as _v3
from approval_service.approval_store import (
    ApprovalRefusedError,
    ApprovalStore,
    ApprovalStoreBusyError,
    ApprovalStoreError,
    ApprovalStoreUnavailableError,
)

SCHEMA_VERSION = 4
APPLICATION_ID = _v3.APPLICATION_ID
DEFAULT_BUSY_TIMEOUT_SECONDS = _v3.DEFAULT_BUSY_TIMEOUT_SECONDS
MAX_BUSY_TIMEOUT_SECONDS = _v3.MAX_BUSY_TIMEOUT_SECONDS
_MAX_SQLITE_INTEGER = (1 << 63) - 1
_INVITATION_ID = re.compile(r"^[0-9a-f]{32}$")
_SECRET = re.compile(r"^[A-Za-z0-9_-]{43}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_INVITATION_UNAVAILABLE = "invitation is invalid or unavailable"

_INVITATION_SCHEMA = (
    """CREATE TABLE enrollment_invitations (
        invitation_id TEXT PRIMARY KEY
            CHECK (length(invitation_id) = 32 AND invitation_id NOT GLOB '*[^0-9a-f]*'),
        secret_sha256 TEXT NOT NULL UNIQUE
            CHECK (length(secret_sha256) = 64 AND secret_sha256 NOT GLOB '*[^0-9a-f]*'),
        approver_id TEXT NOT NULL
            CHECK (approver_id GLOB '[A-Za-z0-9]*'
                AND approver_id NOT GLOB '*[^A-Za-z0-9_.:-]*'
                AND length(approver_id) <= 128),
        principal_id TEXT NOT NULL
            CHECK (principal_id GLOB '[A-Za-z0-9]*'
                AND principal_id NOT GLOB '*[^A-Za-z0-9_.:-]*'
                AND length(principal_id) <= 128),
        created_at_ms INTEGER NOT NULL CHECK (created_at_ms > 0),
        expires_at_ms INTEGER NOT NULL CHECK (expires_at_ms > created_at_ms),
        state TEXT NOT NULL CHECK (state IN ('ISSUED', 'CONSUMED', 'EXPIRED', 'REVOKED')),
        closed_at_ms INTEGER,
        CHECK ((state = 'ISSUED') = (closed_at_ms IS NULL)),
        CHECK (closed_at_ms IS NULL OR closed_at_ms >= created_at_ms)
    ) STRICT""",
    """CREATE UNIQUE INDEX enrollment_one_open_per_approver
        ON enrollment_invitations (approver_id) WHERE state = 'ISSUED'""",
    """CREATE UNIQUE INDEX enrollment_one_open_per_principal
        ON enrollment_invitations (principal_id) WHERE state = 'ISSUED'""",
    """CREATE TRIGGER enrollment_insert_issued BEFORE INSERT ON enrollment_invitations
        WHEN NEW.state <> 'ISSUED'
        BEGIN SELECT RAISE(ABORT, 'invitations are created ISSUED'); END""",
    """CREATE TRIGGER enrollment_permanent BEFORE DELETE ON enrollment_invitations
        BEGIN SELECT RAISE(ABORT, 'invitations are never deleted'); END""",
    """CREATE TRIGGER enrollment_identity_immutable
        BEFORE UPDATE OF invitation_id, secret_sha256, approver_id, principal_id,
            created_at_ms, expires_at_ms ON enrollment_invitations
        BEGIN SELECT RAISE(ABORT, 'invitation identity and binding are immutable'); END""",
    """CREATE TRIGGER enrollment_transitions BEFORE UPDATE ON enrollment_invitations
        WHEN NOT (
            OLD.state = 'ISSUED'
            AND NEW.state IN ('CONSUMED', 'EXPIRED', 'REVOKED')
            AND NEW.closed_at_ms IS NOT NULL
        )
        BEGIN SELECT RAISE(ABORT, 'invitation transition is not allowed'); END""",
    """CREATE TRIGGER enrollment_rowid_immutable BEFORE UPDATE ON enrollment_invitations
        WHEN NEW.rowid IS NOT OLD.rowid
        BEGIN SELECT RAISE(ABORT, 'the rowid of invitations never changes'); END""",
    """CREATE TRIGGER enrollment_never_replaced BEFORE INSERT ON enrollment_invitations
        WHEN EXISTS (
            SELECT 1 FROM enrollment_invitations
            WHERE rowid = NEW.rowid
                OR invitation_id = NEW.invitation_id
                OR secret_sha256 = NEW.secret_sha256
                OR (NEW.state = 'ISSUED' AND state = 'ISSUED'
                    AND (approver_id = NEW.approver_id OR principal_id = NEW.principal_id))
        )
        BEGIN SELECT RAISE(ABORT, 'existing invitation rows are never replaced'); END""",
)

_SCHEMA = _v3._SCHEMA + _INVITATION_SCHEMA


@dataclass(frozen=True, slots=True)
class IssuedInvitation:
    """One-time return value; the plaintext secret is never stored in SQLite.

    The secret is left out of ``repr`` so that logs and tracebacks never
    carry it.
    """

    invitation_id: str
    secret: str = field(repr=False)
    expires_at_ms: int


@dataclass(frozen=True, slots=True)
class ActivatedApprover:
    """Registry rows activated atomically when an invitation is consumed."""

    invitation_id: str
    approver_id: str
    principal_id: str


@functools.cache
def _expected_schema() -> tuple[tuple[object, ...], ...]:
    connection = sqlite3.connect(":memory:", autocommit=True)
    try:
        for statement in _SCHEMA:
            connection.execute(statement)
        return _v3._schema_snapshot(connection)
    finally:
        connection.close()


def _verify_connection(connection: sqlite3.Connection, busy_timeout: float) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA synchronous = FULL")
    expected = {
        "application_id": APPLICATION_ID,
        "user_version": SCHEMA_VERSION,
        "journal_mode": "wal",
        "synchronous": 2,
        "foreign_keys": 1,
        "busy_timeout": int(busy_timeout * 1000),
    }
    for pragma, value in expected.items():
        if connection.execute(f"PRAGMA {pragma}").fetchone()[0] != value:
            raise ApprovalStoreUnavailableError(
                f"database {pragma} is not the value of schema version {SCHEMA_VERSION}"
            )
    if _v3._schema_snapshot(connection) != _expected_schema():
        raise ApprovalStoreUnavailableError(f"database objects differ from schema version {SCHEMA_VERSION}")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ApprovalStoreUnavailableError("database contains foreign key violations")


def _require_registry_id(value: object) -> str:
    if type(value) is not str or _v3._REGISTRY_ID.fullmatch(value) is None:
        raise ApprovalRefusedError("invitation binding is missing or malformed")
    return value


def _require_timestamp(value: object, name: str) -> int:
    if type(value) is not int or not 0 < value <= _MAX_SQLITE_INTEGER:
        raise ApprovalRefusedError(f"{name} is malformed")
    return value


class ApprovalStoreV4(ApprovalStore):
    """Fresh-file schema v4 store with mock-only invitation primitives.

    All inherited v3 request and revocation operations remain available.
    Invitation consumption inserts the bound principal and approver in the
    same BEGIN IMMEDIATE transaction that marks the invitation CONSUMED.
    """

    @classmethod
    def initialize(
        cls,
        path: str | os.PathLike[str],
        clock: Callable[[], int],
        *,
        busy_timeout_seconds: float = DEFAULT_BUSY_TIMEOUT_SECONDS,
    ) -> ApprovalStoreV4:
        """Create schema v4 in a brand-new file; never migrate or reuse a file."""

        _v3._check_sqlite_version()
        path = _v3._checked_path(path)
        busy_timeout = _v3._checked_busy_timeout(busy_timeout_seconds)
        _v3._check_parent(path)
        for suffix in ("-wal", "-shm"):
            if os.path.lexists(f"{path}{suffix}"):
                raise ApprovalStoreUnavailableError(f"a stale database {suffix} file already exists")
        try:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except FileExistsError:
            raise ApprovalStoreUnavailableError("database file already exists; it is never re-initialized") from None
        except OSError:
            raise ApprovalStoreUnavailableError("database file could not be created") from None
        os.close(descriptor)

        connection = _v3._connect(path, busy_timeout)
        try:
            if connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] != "wal":
                raise ApprovalStoreUnavailableError("database could not switch to WAL mode")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            try:
                for statement in _SCHEMA:
                    connection.execute(statement)
                connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                connection.execute("INSERT INTO store_meta (singleton, last_observed_ms) VALUES (1, 0)")
            except BaseException:
                _v3._rollback(connection)
                raise
            connection.execute("COMMIT")
        except sqlite3.Error as error:
            raise _v3._store_error(error, "database could not be initialized", busy_timeout) from None
        finally:
            connection.close()
        return cls(path, clock, busy_timeout_seconds=busy_timeout)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        _v3._check_sqlite_version()
        _v3._check_files(self._path)
        connection = _v3._connect(self._path, self._busy_timeout)
        try:
            try:
                _verify_connection(connection, self._busy_timeout)
            except sqlite3.Error as error:
                raise _v3._store_error(error, "database could not be verified", self._busy_timeout) from None
            yield connection
        finally:
            connection.close()

    def create_invitation(
        self,
        approver_id: str,
        principal_id: str,
        *,
        expires_at_ms: int,
    ) -> IssuedInvitation:
        """Create an invitation; return its 256-bit secret exactly once.

        This method does not authenticate its caller. Its use is restricted to
        isolated tests until a separate SSH administration boundary exists.
        """

        approver_id = _require_registry_id(approver_id)
        principal_id = _require_registry_id(principal_id)
        expires_at_ms = _require_timestamp(expires_at_ms, "invitation expiry")
        secret = secrets.token_urlsafe(32)
        invitation_id = secrets.token_hex(16)
        if _SECRET.fullmatch(secret) is None or _INVITATION_ID.fullmatch(invitation_id) is None:
            raise ApprovalStoreUnavailableError("secure invitation material could not be generated")
        secret_hash = hashlib.sha256(secret.encode("ascii")).hexdigest()

        with self._write_transaction() as connection:
            now = self._observe_clock(connection)
            if expires_at_ms <= now:
                raise ApprovalRefusedError("invitation expiry must be in the future")
            if connection.execute(
                "SELECT 1 FROM principals WHERE principal_id = ? UNION ALL"
                " SELECT 1 FROM approvers WHERE approver_id = ? LIMIT 1",
                (principal_id, approver_id),
            ).fetchone() is not None:
                raise ApprovalRefusedError("invitation binding is already registered")
            # Close expired invitations for this binding before checking the
            # one-open-invitation constraint, in the same write transaction.
            connection.execute(
                "UPDATE enrollment_invitations SET state = 'EXPIRED', closed_at_ms = ?"
                " WHERE state = 'ISSUED' AND expires_at_ms <= ?"
                " AND (approver_id = ? OR principal_id = ?)",
                (now, now, approver_id, principal_id),
            )
            # The partial unique indexes and the never-replaced trigger would
            # also abort this insert, but as a store failure, not a refusal.
            if connection.execute(
                "SELECT 1 FROM enrollment_invitations"
                " WHERE state = 'ISSUED' AND (approver_id = ? OR principal_id = ?) LIMIT 1",
                (approver_id, principal_id),
            ).fetchone() is not None:
                raise ApprovalRefusedError("an invitation is already open for this binding")
            connection.execute(
                "INSERT INTO enrollment_invitations"
                " (invitation_id, secret_sha256, approver_id, principal_id, created_at_ms,"
                " expires_at_ms, state, closed_at_ms)"
                " VALUES (?, ?, ?, ?, ?, ?, 'ISSUED', NULL)",
                (invitation_id, secret_hash, approver_id, principal_id, now, expires_at_ms),
            )
        return IssuedInvitation(invitation_id, secret, expires_at_ms)

    def consume_invitation(self, secret: str) -> ActivatedApprover:
        """Consume once and activate the bound principal and approver atomically."""

        if type(secret) is not str or _SECRET.fullmatch(secret) is None:
            raise ApprovalRefusedError(_INVITATION_UNAVAILABLE)
        secret_hash = hashlib.sha256(secret.encode("ascii")).hexdigest()
        expired = False
        activated: ActivatedApprover | None = None

        with self._write_transaction() as connection:
            now = self._observe_clock(connection)
            row = connection.execute(
                "SELECT invitation_id, approver_id, principal_id, expires_at_ms, state"
                " FROM enrollment_invitations WHERE secret_sha256 = ?",
                (secret_hash,),
            ).fetchone()
            if row is None or row[4] != "ISSUED":
                raise ApprovalRefusedError(_INVITATION_UNAVAILABLE)
            invitation_id, approver_id, principal_id, expires_at_ms, _state = row
            if now >= expires_at_ms:
                connection.execute(
                    "UPDATE enrollment_invitations SET state = 'EXPIRED', closed_at_ms = ?"
                    " WHERE invitation_id = ?",
                    (now, invitation_id),
                )
                expired = True
            else:
                try:
                    connection.execute(
                        "INSERT INTO principals (principal_id, state, revoked_at_ms)"
                        " VALUES (?, 'ACTIVE', NULL)",
                        (principal_id,),
                    )
                    connection.execute(
                        "INSERT INTO approvers (approver_id, principal_id, state, revoked_at_ms)"
                        " VALUES (?, ?, 'ACTIVE', NULL)",
                        (approver_id, principal_id),
                    )
                except sqlite3.IntegrityError:
                    # The context manager rolls the transaction back, including
                    # the principal insert if only the approver insert failed.
                    raise ApprovalRefusedError("invitation cannot be activated") from None
                connection.execute(
                    "UPDATE enrollment_invitations SET state = 'CONSUMED', closed_at_ms = ?"
                    " WHERE invitation_id = ?",
                    (now, invitation_id),
                )
                activated = ActivatedApprover(invitation_id, approver_id, principal_id)

        if expired or activated is None:
            raise ApprovalRefusedError(_INVITATION_UNAVAILABLE)
        return activated

    def revoke_invitation(self, invitation_id: str) -> bool:
        """Revoke an issued invitation by its non-secret identifier.

        This is an unauthenticated storage primitive, not an admin interface.
        """

        if type(invitation_id) is not str or _INVITATION_ID.fullmatch(invitation_id) is None:
            raise ApprovalRefusedError("invitation ID is missing or malformed")
        with self._write_transaction() as connection:
            now = self._observe_clock(connection)
            row = connection.execute(
                "SELECT state, expires_at_ms FROM enrollment_invitations WHERE invitation_id = ?",
                (invitation_id,),
            ).fetchone()
            if row is None or row[0] != "ISSUED":
                return False
            state = "EXPIRED" if now >= row[1] else "REVOKED"
            connection.execute(
                "UPDATE enrollment_invitations SET state = ?, closed_at_ms = ? WHERE invitation_id = ?",
                (state, now, invitation_id),
            )
            return state == "REVOKED"

    def expire_invitations(self) -> int:
        """Mark all currently expired issued invitations as terminal."""

        with self._write_transaction() as connection:
            now = self._observe_clock(connection)
            cursor = connection.execute(
                "UPDATE enrollment_invitations SET state = 'EXPIRED', closed_at_ms = ?"
                " WHERE state = 'ISSUED' AND expires_at_ms <= ?",
                (now, now),
            )
            return cursor.rowcount


__all__ = [
    "APPLICATION_ID",
    "SCHEMA_VERSION",
    "ActivatedApprover",
    "ApprovalStoreV4",
    "IssuedInvitation",
    "ApprovalRefusedError",
    "ApprovalStoreBusyError",
    "ApprovalStoreError",
    "ApprovalStoreUnavailableError",
]
