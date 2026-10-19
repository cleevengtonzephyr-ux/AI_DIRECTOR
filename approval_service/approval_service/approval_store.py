"""Mock-only durable store for G2 WebAuthn approval requests.

One SQLite file from the standard library holds the approval requests with
their single immutable statement, the enrolled credentials, an
administrator-attested registry of principals, approvers and GitHub
accounts, and a minimal append-only journal. The store exposes only
``initialize``, ``create_request``, ``approve``, ``expire_request`` and
``revoke_credential``.

Each request persists the signed ``run_actor_id`` (a numeric GitHub account
ID, never the ``actor`` login) and the two principals compared when it was
created; creation and approval both re-check that account separation. That
separation is only attested by the administrator: it does not prove that two
different people are involved. The store never consumes an approval, never
talks to the Gate or a provider, and enrolls or revokes no registry entry.
An ``APPROVED`` request authorizes nothing: G1 D-5 is unresolved and no
future consumption may be built on this state until it is.

The database must stay on a local file system and be opened only through
``sqlite3``: WAL needs shared memory and working locks, and on POSIX closing
any other descriptor of the file drops this process's SQLite locks.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import sqlite3
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from fido2.webauthn import AttestedCredentialData

from approval_service.account_separation import (
    AccountBinding,
    AccountSeparationChecker,
    AccountSeparationError,
    AdminAttestedAccountSeparation,
    ApproverBinding,
    PrincipalRecord,
)
from approval_service.approval_statement import ApprovalStatement
from approval_service.webauthn_verifier import (
    RegisteredCredential,
    VerifiedApprovalAssertion,
    WebAuthnPolicy,
    WebAuthnVerificationError,
    WebAuthnVerifier,
)

SCHEMA_VERSION = 2  # no migration: any other version is refused
APPLICATION_ID = 0x41444732  # "ADG2"
# SQLITE_BUSY: wait at most this long for another writer before refusing.
DEFAULT_BUSY_TIMEOUT_SECONDS = 5.0
MAX_BUSY_TIMEOUT_SECONDS = 30.0
_MIN_SQLITE_VERSION = (3, 37, 0)  # STRICT tables
_MIN_CREDENTIAL_ID_BYTES = 16
_MAX_CREDENTIAL_ID_BYTES = 1023
_SEPARATION_REFUSED = "account separation between the run and the approver is not established"

# Registry IDs follow the approval statement's format; GitHub account IDs the
# OIDC `actor_id` assumption (positive decimal string, no leading zero).
_REGISTRY_ID_CHECK = "{0} GLOB '[A-Za-z0-9]*' AND {0} NOT GLOB '*[^A-Za-z0-9_.:-]*' AND length({0}) <= 128"
_ACCOUNT_ID_CHECK = "{0} GLOB '[1-9]*' AND {0} NOT GLOB '*[^0-9]*'"
_REVOCABLE = """state TEXT NOT NULL CHECK (state IN ('ACTIVE', 'REVOKED')),
        revoked_at_ms INTEGER,
        CHECK ((state = 'REVOKED') = (revoked_at_ms IS NOT NULL))"""


def _never_replaced(table: str, condition: str) -> str:
    # INSERT OR REPLACE deletes the conflicting row without firing DELETE
    # triggers (recursive_triggers is off): refuse any insert that would.
    # ``condition`` names every declared unique key; the rowid is unique in
    # every table too, even when not its PRIMARY KEY (-1 when not given).
    return (
        f"CREATE TRIGGER {table}_never_replaced BEFORE INSERT ON {table}"
        f" WHEN EXISTS (SELECT 1 FROM {table} WHERE rowid = NEW.rowid OR {condition})"
        f" BEGIN SELECT RAISE(ABORT, 'existing {table} rows are never replaced'); END"
    )


def _rowid_immutable(table: str) -> str:
    # UPDATE OR REPLACE moving a row onto another rowid deletes that row the
    # same way. Declared keys are already immutable; the hidden rowid is not.
    return (
        f"CREATE TRIGGER {table}_rowid_immutable BEFORE UPDATE ON {table} WHEN NEW.rowid IS NOT OLD.rowid"
        f" BEGIN SELECT RAISE(ABORT, 'the rowid of {table} rows never changes'); END"
    )


def _registry_triggers(table: str, identity_columns: str) -> tuple[str, ...]:
    return (
        f"CREATE TRIGGER {table}_permanent BEFORE DELETE ON {table}"
        f" BEGIN SELECT RAISE(ABORT, '{table} rows are never deleted'); END",
        f"CREATE TRIGGER {table}_identity_immutable BEFORE UPDATE OF {identity_columns} ON {table}"
        f" BEGIN SELECT RAISE(ABORT, '{table} identity and binding are immutable'); END",
        f"CREATE TRIGGER {table}_revocation_final BEFORE UPDATE ON {table} WHEN OLD.state = 'REVOKED'"
        f" BEGIN SELECT RAISE(ABORT, 'a revoked {table} row never changes'); END",
    )


_SCHEMA = (
    """CREATE TABLE store_meta (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        last_observed_ms INTEGER NOT NULL CHECK (last_observed_ms >= 0)
    ) STRICT""",
    f"""CREATE TABLE principals (
        principal_id TEXT PRIMARY KEY CHECK ({_REGISTRY_ID_CHECK.format("principal_id")}),
        {_REVOCABLE}
    ) STRICT""",
    f"""CREATE TABLE approvers (
        approver_id TEXT PRIMARY KEY CHECK ({_REGISTRY_ID_CHECK.format("approver_id")}),
        principal_id TEXT NOT NULL REFERENCES principals (principal_id),
        {_REVOCABLE}
    ) STRICT""",
    f"""CREATE TABLE github_accounts (
        account_id TEXT PRIMARY KEY CHECK ({_ACCOUNT_ID_CHECK.format("account_id")}),
        principal_id TEXT NOT NULL REFERENCES principals (principal_id),
        evidence TEXT NOT NULL CHECK (evidence = 'ADMIN_ATTESTED'),
        attested_at_ms INTEGER NOT NULL CHECK (attested_at_ms > 0),
        {_REVOCABLE}
    ) STRICT""",
    """CREATE TABLE credentials (
        credential_id BLOB PRIMARY KEY CHECK (length(credential_id) BETWEEN 16 AND 1023),
        credential_data BLOB NOT NULL,
        approver_id TEXT NOT NULL REFERENCES approvers (approver_id),
        user_handle BLOB NOT NULL CHECK (length(user_handle) BETWEEN 1 AND 64),
        backup_eligible INTEGER NOT NULL CHECK (backup_eligible IN (0, 1)),
        backup_state INTEGER NOT NULL CHECK (backup_state IN (0, 1) AND backup_state <= backup_eligible),
        sign_count INTEGER NOT NULL CHECK (sign_count BETWEEN 0 AND 4294967295),
        state TEXT NOT NULL CHECK (state IN ('ACTIVE', 'REVOKED')),
        revoked_at_ms INTEGER,
        CHECK ((state = 'REVOKED') = (revoked_at_ms IS NOT NULL))
    ) STRICT""",
    """CREATE TABLE approval_requests (
        approval_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL UNIQUE,
        authorization_id TEXT NOT NULL UNIQUE,
        nonce TEXT NOT NULL UNIQUE,
        run_id TEXT NOT NULL,
        run_attempt INTEGER NOT NULL,
        run_actor_id TEXT NOT NULL REFERENCES github_accounts (account_id),
        approver_id TEXT NOT NULL REFERENCES approvers (approver_id),
        actor_principal_id TEXT NOT NULL REFERENCES principals (principal_id),
        approver_principal_id TEXT NOT NULL REFERENCES principals (principal_id),
        separation_evidence TEXT NOT NULL CHECK (separation_evidence = 'ADMIN_ATTESTED_ACCOUNT_SEPARATION'),
        statement_json BLOB NOT NULL,
        statement_sha256 TEXT NOT NULL CHECK (length(statement_sha256) = 64),
        state TEXT NOT NULL CHECK (state IN ('PENDING', 'APPROVED', 'EXPIRED', 'REVOKED')),
        created_at_ms INTEGER NOT NULL,
        approved_at_ms INTEGER,
        approved_credential_id BLOB REFERENCES credentials (credential_id),
        closed_at_ms INTEGER,
        UNIQUE (run_id, run_attempt),
        CHECK (actor_principal_id <> approver_principal_id),
        CHECK ((approved_at_ms IS NULL) = (approved_credential_id IS NULL)),
        CHECK (
            (state = 'PENDING' AND approved_at_ms IS NULL AND closed_at_ms IS NULL)
            OR (state = 'APPROVED' AND approved_at_ms IS NOT NULL AND closed_at_ms IS NULL)
            OR (state = 'EXPIRED' AND approved_at_ms IS NULL AND closed_at_ms IS NOT NULL)
            OR (state = 'REVOKED' AND approved_at_ms IS NOT NULL AND closed_at_ms IS NOT NULL)
        )
    ) STRICT""",
    """CREATE INDEX approval_requests_by_credential ON approval_requests (approved_credential_id)""",
    """CREATE TABLE journal (
        sequence INTEGER PRIMARY KEY,
        at_ms INTEGER NOT NULL,
        event TEXT NOT NULL CHECK (event IN (
            'REQUEST_CREATED', 'REQUEST_APPROVED', 'REQUEST_EXPIRED',
            'APPROVAL_REVOKED', 'CREDENTIAL_REVOKED', 'COUNTER_SIGNAL'
        )),
        approval_id TEXT,
        credential_sha256 TEXT CHECK (credential_sha256 IS NULL OR length(credential_sha256) = 64),
        stored_sign_count INTEGER,
        presented_sign_count INTEGER,
        CHECK ((event = 'COUNTER_SIGNAL') = (
            approval_id IS NOT NULL AND credential_sha256 IS NOT NULL
            AND stored_sign_count IS NOT NULL AND presented_sign_count IS NOT NULL
        ))
    ) STRICT""",
    """CREATE UNIQUE INDEX journal_one_counter_signal
        ON journal (approval_id, credential_sha256) WHERE event = 'COUNTER_SIGNAL'""",
    *_registry_triggers("principals", "principal_id"),
    *_registry_triggers("approvers", "approver_id, principal_id"),
    *_registry_triggers("github_accounts", "account_id, principal_id, evidence, attested_at_ms"),
    _never_replaced("store_meta", "1"),
    _never_replaced("principals", "principal_id = NEW.principal_id"),
    _never_replaced("approvers", "approver_id = NEW.approver_id"),
    _never_replaced("github_accounts", "account_id = NEW.account_id"),
    _never_replaced("credentials", "credential_id = NEW.credential_id"),
    _never_replaced(
        "approval_requests",
        "approval_id = NEW.approval_id OR request_id = NEW.request_id OR authorization_id = NEW.authorization_id"
        " OR nonce = NEW.nonce OR (run_id = NEW.run_id AND run_attempt = NEW.run_attempt)",
    ),
    _never_replaced(
        "journal",
        "sequence = NEW.sequence OR (NEW.event = 'COUNTER_SIGNAL' AND event = 'COUNTER_SIGNAL'"
        " AND approval_id = NEW.approval_id AND credential_sha256 = NEW.credential_sha256)",
    ),
    # The rowid of store_meta and journal is their INTEGER PRIMARY KEY, which
    # the update triggers below already freeze.
    *(
        _rowid_immutable(table)
        for table in ("principals", "approvers", "github_accounts", "credentials", "approval_requests")
    ),
    """CREATE TRIGGER store_meta_permanent BEFORE DELETE ON store_meta
        BEGIN SELECT RAISE(ABORT, 'store metadata is permanent'); END""",
    """CREATE TRIGGER store_meta_clock_monotonic BEFORE UPDATE ON store_meta
        WHEN NEW.singleton <> OLD.singleton OR NEW.last_observed_ms < OLD.last_observed_ms
        BEGIN SELECT RAISE(ABORT, 'the observed clock never moves backwards'); END""",
    """CREATE TRIGGER credentials_permanent BEFORE DELETE ON credentials
        BEGIN SELECT RAISE(ABORT, 'credentials are never deleted'); END""",
    """CREATE TRIGGER credentials_identity_immutable
        BEFORE UPDATE OF credential_id, credential_data, approver_id, user_handle, backup_eligible ON credentials
        BEGIN SELECT RAISE(ABORT, 'credential identity and BE are immutable'); END""",
    """CREATE TRIGGER credentials_revocation_final BEFORE UPDATE ON credentials
        WHEN OLD.state = 'REVOKED'
        BEGIN SELECT RAISE(ABORT, 'a revoked credential never changes'); END""",
    """CREATE TRIGGER credentials_counter_advances BEFORE UPDATE OF sign_count ON credentials
        WHEN NEW.sign_count < OLD.sign_count OR (NEW.sign_count = OLD.sign_count AND OLD.sign_count <> 0)
        BEGIN SELECT RAISE(ABORT, 'the signature counter must advance'); END""",
    """CREATE TRIGGER approval_requests_created_pending BEFORE INSERT ON approval_requests
        WHEN NEW.state <> 'PENDING'
        BEGIN SELECT RAISE(ABORT, 'approval requests are created PENDING'); END""",
    """CREATE TRIGGER approval_requests_permanent BEFORE DELETE ON approval_requests
        BEGIN SELECT RAISE(ABORT, 'approval requests are never deleted'); END""",
    """CREATE TRIGGER approval_requests_statement_immutable
        BEFORE UPDATE OF approval_id, request_id, authorization_id, nonce, run_id, run_attempt,
            run_actor_id, approver_id, actor_principal_id, approver_principal_id, separation_evidence,
            statement_json, statement_sha256, created_at_ms ON approval_requests
        BEGIN SELECT RAISE(ABORT, 'the approval statement is immutable'); END""",
    """CREATE TRIGGER approval_requests_transitions BEFORE UPDATE ON approval_requests
        WHEN NOT (
            (OLD.state = 'PENDING' AND NEW.state IN ('APPROVED', 'EXPIRED'))
            OR (OLD.state = 'APPROVED' AND NEW.state = 'REVOKED'
                AND NEW.approved_at_ms IS OLD.approved_at_ms
                AND NEW.approved_credential_id IS OLD.approved_credential_id)
        )
        BEGIN SELECT RAISE(ABORT, 'approval request transition is not allowed'); END""",
    """CREATE TRIGGER journal_append_only_update BEFORE UPDATE ON journal
        BEGIN SELECT RAISE(ABORT, 'the journal is append-only'); END""",
    """CREATE TRIGGER journal_append_only_delete BEFORE DELETE ON journal
        BEGIN SELECT RAISE(ABORT, 'the journal is append-only'); END""",
)


class ApprovalStoreError(Exception):
    """Base of every refusal. Messages never include assertions or raw IDs."""


class ApprovalStoreUnavailableError(ApprovalStoreError):
    """The database is absent, invalid, inconsistent or failed; nothing changed."""


class ApprovalStoreBusyError(ApprovalStoreUnavailableError):
    """Another writer held the database beyond the bounded busy timeout."""


class ApprovalRefusedError(ApprovalStoreError):
    """The request, statement, clock or assertion does not allow the operation."""


@functools.cache
def _expected_schema() -> tuple[tuple[object, ...], ...]:
    connection = sqlite3.connect(":memory:", autocommit=True)
    try:
        for statement in _SCHEMA:
            connection.execute(statement)
        return _schema_snapshot(connection)
    finally:
        connection.close()


def _schema_snapshot(connection: sqlite3.Connection) -> tuple[tuple[object, ...], ...]:
    return tuple(connection.execute("SELECT type, name, tbl_name, sql FROM sqlite_schema ORDER BY type, name"))


def _check_sqlite_version() -> None:
    if sqlite3.sqlite_version_info < _MIN_SQLITE_VERSION:
        raise ApprovalStoreUnavailableError("SQLite 3.37 or later is required for STRICT tables")


def _checked_path(path: object) -> Path:
    if not isinstance(path, (str, os.PathLike)):
        raise TypeError("path must be a filesystem path")
    path = Path(path)
    if not path.is_absolute():
        raise ApprovalStoreUnavailableError("database path must be absolute")
    return path


def _checked_busy_timeout(seconds: object) -> float:
    if type(seconds) not in (int, float) or not math.isfinite(seconds):
        raise ValueError("busy_timeout_seconds must be a finite number")
    if not 0 < seconds <= MAX_BUSY_TIMEOUT_SECONDS:
        raise ValueError("busy_timeout_seconds must be within (0, 30] seconds")
    return float(seconds)


def _check_private(status: os.stat_result, what: str) -> None:
    if os.name == "nt":
        # Windows ACLs are not checked in this mock-only step.
        return
    if status.st_uid != os.geteuid() or status.st_mode & 0o077:
        raise ApprovalStoreUnavailableError(
            f"{what} must belong to the service account with no group or other permissions"
        )


def _check_parent(path: Path) -> None:
    try:
        status = os.lstat(path.parent)
    except OSError:
        raise ApprovalStoreUnavailableError("database directory cannot be inspected") from None
    if not stat.S_ISDIR(status.st_mode):
        raise ApprovalStoreUnavailableError("database directory must be a real directory")
    _check_private(status, "database directory")


def _check_files(path: Path) -> None:
    """Refuse an absent, linked, non-regular or non-private database.

    The check runs before each connection; a replacement between this check
    and SQLite's own open is not detected (Python exposes no O_NOFOLLOW).
    """

    try:
        status = os.lstat(path)
    except FileNotFoundError:
        raise ApprovalStoreUnavailableError(
            "database file is absent; only an explicit initialize() creates it"
        ) from None
    except OSError:
        raise ApprovalStoreUnavailableError("database file cannot be inspected") from None
    if stat.S_ISLNK(status.st_mode):
        raise ApprovalStoreUnavailableError("database path is a symbolic link")
    if not stat.S_ISREG(status.st_mode):
        raise ApprovalStoreUnavailableError("database path is not a regular file")
    _check_private(status, "database file")
    _check_parent(path)
    for suffix in ("-wal", "-shm"):
        try:
            side = os.lstat(f"{path}{suffix}")
        except FileNotFoundError:
            continue
        except OSError:
            raise ApprovalStoreUnavailableError(f"database {suffix} file cannot be inspected") from None
        if not stat.S_ISREG(side.st_mode):
            raise ApprovalStoreUnavailableError(f"database {suffix} file is not a regular file")
        _check_private(side, f"database {suffix} file")


def _connect(path: Path, busy_timeout: float) -> sqlite3.Connection:
    # mode=rw never creates a missing file; autocommit=True leaves every
    # transaction to the explicit BEGIN IMMEDIATE / COMMIT below.
    try:
        return sqlite3.connect(f"{path.as_uri()}?mode=rw", uri=True, autocommit=True, timeout=busy_timeout)
    except sqlite3.Error as error:
        raise _store_error(error, "database could not be opened", busy_timeout) from None


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
    if _schema_snapshot(connection) != _expected_schema():
        raise ApprovalStoreUnavailableError(f"database objects differ from schema version {SCHEMA_VERSION}")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ApprovalStoreUnavailableError("database contains foreign key violations")


def _store_error(error: sqlite3.Error, message: str, busy_timeout: float) -> ApprovalStoreUnavailableError:
    name = getattr(error, "sqlite_errorname", "") or type(error).__name__
    if name.startswith(("SQLITE_BUSY", "SQLITE_LOCKED")):
        return ApprovalStoreBusyError(f"{message}: the store stayed locked for more than {busy_timeout:g}s")
    return ApprovalStoreUnavailableError(f"{message} ({name})")


def _rollback(connection: sqlite3.Connection) -> None:
    if connection.in_transaction:
        try:
            connection.execute("ROLLBACK")
        except sqlite3.Error:
            # Closing the connection rolls the transaction back as well.
            pass


def _append_journal(
    connection: sqlite3.Connection,
    at_ms: int,
    event: str,
    *,
    approval_id: str | None = None,
    credential_id: bytes | None = None,
    stored_sign_count: int | None = None,
    presented_sign_count: int | None = None,
) -> None:
    """Append one entry; credentials appear only as SHA-256 digests.

    Only COUNTER_SIGNAL has a uniqueness rule (one per request and
    credential). A repeated signal is skipped here: the replacement guard
    fires before any ON CONFLICT clause and refuses it.
    """

    credential_sha256 = None if credential_id is None else hashlib.sha256(credential_id).hexdigest()
    if event == "COUNTER_SIGNAL" and connection.execute(
        "SELECT 1 FROM journal WHERE event = 'COUNTER_SIGNAL' AND approval_id = ? AND credential_sha256 = ?",
        (approval_id, credential_sha256),
    ).fetchone():
        return
    connection.execute(
        "INSERT INTO journal (at_ms, event, approval_id, credential_sha256, stored_sign_count, presented_sign_count)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (at_ms, event, approval_id, credential_sha256, stored_sign_count, presented_sign_count),
    )


def _expiry_instant(statement: ApprovalStatement) -> int:
    """First Unix millisecond at which ``statement`` can no longer be approved."""

    return min(statement.approval_deadline, statement.expires_at)


def _counter_advances(stored: int, presented: int) -> bool:
    """0 -> 0 means no counter; otherwise it must strictly increase.

    A non-advancing counter is a WebAuthn signal of a possible clone, not a
    proof: an authenticator reset or an older assertion arriving after a
    newer one look the same.
    """

    return (stored == 0 and presented == 0) or presented > stored


def _load_statement(connection: sqlite3.Connection, approval_id: str) -> tuple[ApprovalStatement, str]:
    """Rebuild the stored statement and refuse any integrity mismatch."""

    row = connection.execute(
        "SELECT statement_json, statement_sha256, state, request_id, authorization_id, nonce,"
        " run_id, run_attempt, run_actor_id, approver_id FROM approval_requests WHERE approval_id = ?",
        (approval_id,),
    ).fetchone()
    if row is None:
        raise ApprovalRefusedError("approval request is unknown")
    statement_json, statement_sha256, state, *columns = row
    try:
        fields = json.loads(statement_json)
        if type(fields) is not dict or fields.pop("statement_version", None) != ApprovalStatement.VERSION:
            raise ValueError("unexpected statement version")
        statement = ApprovalStatement(**fields)
    except (TypeError, ValueError, RecursionError):
        raise ApprovalStoreUnavailableError("approval statement failed its integrity check") from None
    if (
        statement.canonical_bytes() != statement_json
        or statement.sha256() != statement_sha256
        or [
            statement.request_id,
            statement.authorization_id,
            statement.nonce,
            statement.run_id,
            statement.run_attempt,
            statement.run_actor_id,
            statement.approver_id,
        ]
        != columns
        or statement.approval_id != approval_id
    ):
        raise ApprovalStoreUnavailableError("approval statement failed its integrity check")
    return statement, state


class _RegistryRows:
    """SeparationRegistry over the caller's open transaction (read-only)."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def _row(self, sql: str, key: str) -> tuple[object, ...]:
        row = self._connection.execute(sql, (key,)).fetchone()
        if row is None:
            raise KeyError("registry entry is not registered")
        return row

    def resolve_account(self, account_id: str) -> AccountBinding:
        found, principal_id, state = self._row(
            "SELECT account_id, principal_id, state FROM github_accounts WHERE account_id = ?", account_id
        )
        return AccountBinding(found, principal_id, revoked=state != "ACTIVE")

    def resolve_approver(self, approver_id: str) -> ApproverBinding:
        found, principal_id, state = self._row(
            "SELECT approver_id, principal_id, state FROM approvers WHERE approver_id = ?", approver_id
        )
        return ApproverBinding(found, principal_id, revoked=state != "ACTIVE")

    def resolve_principal(self, principal_id: str) -> PrincipalRecord:
        found, state = self._row("SELECT principal_id, state FROM principals WHERE principal_id = ?", principal_id)
        return PrincipalRecord(found, revoked=state != "ACTIVE")


def _check_separation(connection: sqlite3.Connection, statement: ApprovalStatement) -> AdminAttestedAccountSeparation:
    """Administrator-attested account separation of the run and the approver.

    Every refusal of the checker, SQLite errors included, becomes one generic
    refusal that names no account, approver or principal.
    """

    try:
        return AccountSeparationChecker(_RegistryRows(connection)).check(
            statement.run_actor_id, statement.approver_id
        )
    except AccountSeparationError:
        raise ApprovalRefusedError(_SEPARATION_REFUSED) from None


class _CredentialRows:
    """Resolve enrolled credentials inside the caller's open transaction."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def resolve(self, credential_id: bytes) -> RegisteredCredential:
        row = self._connection.execute(
            "SELECT credential_data, approver_id, user_handle, backup_eligible, state"
            " FROM credentials WHERE credential_id = ?",
            (credential_id,),
        ).fetchone()
        if row is None:
            raise KeyError("credential is not registered")
        credential_data, approver_id, user_handle, backup_eligible, state = row
        return RegisteredCredential(
            credential=AttestedCredentialData(credential_data),
            approver_id=approver_id,
            user_handle=user_handle,
            backup_eligible=bool(backup_eligible),
            revoked=state != "ACTIVE",
        )


class ApprovalStore:
    """Durable PENDING -> APPROVED state of WebAuthn approvals, without consumption.

    Each operation opens its own connection, re-checks the file and schema,
    and writes inside one ``BEGIN IMMEDIATE`` transaction. Only two writes
    are committed on their own after a refused approval: the ``EXPIRED``
    transition and a counter signal. The clock returns Unix milliseconds.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        clock: Callable[[], int],
        *,
        busy_timeout_seconds: float = DEFAULT_BUSY_TIMEOUT_SECONDS,
    ) -> None:
        if not callable(clock):
            raise TypeError("clock must return Unix time in milliseconds")
        self._path = _checked_path(path)
        self._busy_timeout = _checked_busy_timeout(busy_timeout_seconds)
        self._clock = clock
        self._policy = WebAuthnPolicy()
        with self._connection():
            pass

    @classmethod
    def initialize(
        cls,
        path: str | os.PathLike[str],
        clock: Callable[[], int],
        *,
        busy_timeout_seconds: float = DEFAULT_BUSY_TIMEOUT_SECONDS,
    ) -> ApprovalStore:
        """Create the current schema version in a new private file; never reuse a file."""

        _check_sqlite_version()
        path = _checked_path(path)
        busy_timeout = _checked_busy_timeout(busy_timeout_seconds)
        _check_parent(path)
        for suffix in ("-wal", "-shm"):
            if os.path.lexists(f"{path}{suffix}"):
                raise ApprovalStoreUnavailableError(f"a stale database {suffix} file already exists")
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except FileExistsError:
            raise ApprovalStoreUnavailableError("database file already exists; it is never re-initialized") from None
        except OSError:
            raise ApprovalStoreUnavailableError("database file could not be created") from None
        os.close(descriptor)

        connection = _connect(path, busy_timeout)
        try:
            # A failure leaves user_version 0: ordinary opens then refuse the
            # file and initialize() refuses to reuse it (human review).
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
                _rollback(connection)
                raise
            connection.execute("COMMIT")
        except sqlite3.Error as error:
            raise _store_error(error, "database could not be initialized", busy_timeout) from None
        finally:
            connection.close()
        return cls(path, clock, busy_timeout_seconds=busy_timeout)

    def create_request(self, statement: ApprovalStatement) -> None:
        """Record ``statement`` as the one immutable statement of a PENDING request.

        The account separation of its signed ``run_actor_id`` and approver is
        checked in the same transaction; any refusal leaves the store unchanged.
        """

        if type(statement) is not ApprovalStatement:
            raise ApprovalRefusedError("approval statement is missing or malformed")
        with self._write_transaction() as connection:
            now = self._observe_clock(connection)
            if now >= _expiry_instant(statement):
                raise ApprovalRefusedError("approval statement has already expired")
            separation = _check_separation(connection, statement)
            try:
                connection.execute(
                    "INSERT INTO approval_requests (approval_id, request_id, authorization_id, nonce, run_id,"
                    " run_attempt, run_actor_id, approver_id, actor_principal_id, approver_principal_id,"
                    " separation_evidence, statement_json, statement_sha256, state, created_at_ms)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)",
                    (
                        statement.approval_id,
                        statement.request_id,
                        statement.authorization_id,
                        statement.nonce,
                        statement.run_id,
                        statement.run_attempt,
                        statement.run_actor_id,
                        statement.approver_id,
                        separation.actor_principal_id,
                        separation.approver_principal_id,
                        separation.evidence,
                        statement.canonical_bytes(),
                        statement.sha256(),
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                raise ApprovalRefusedError(
                    "approval, request or authorization ID, nonce or run attempt is already recorded"
                ) from None
            _append_journal(connection, now, "REQUEST_CREATED", approval_id=statement.approval_id)

    def approve(self, approval_id: str, response: dict[str, object]) -> VerifiedApprovalAssertion:
        """Move one PENDING request to APPROVED with a verified assertion.

        Every refusal rolls the approval transaction back. Afterwards, an
        expired request is moved to EXPIRED and a non-advancing counter is
        recorded, each in its own committed transaction.

        The account separation is re-checked against the current registry and
        must yield the principals persisted at creation. A revocation committed
        after the approval does not undo it: no cascade exists here, so any
        future consumption must re-validate the separation first.
        """

        if type(approval_id) is not str or not approval_id:
            raise ApprovalRefusedError("approval ID is missing or malformed")
        expiry: int | None = None
        counter_signal: tuple[bytes, int, int] | None = None
        try:
            with self._write_transaction() as connection:
                now = self._observe_clock(connection)
                statement, state = _load_statement(connection, approval_id)
                if state != "PENDING":
                    raise ApprovalRefusedError("approval request is not pending")
                expiry = _expiry_instant(statement)
                if now >= expiry:
                    raise ApprovalRefusedError("approval request has expired")

                separation = _check_separation(connection, statement)
                persisted = connection.execute(
                    "SELECT actor_principal_id, approver_principal_id, separation_evidence"
                    " FROM approval_requests WHERE approval_id = ?",
                    (approval_id,),
                ).fetchone()
                if persisted != (
                    separation.actor_principal_id,
                    separation.approver_principal_id,
                    separation.evidence,
                ):
                    raise ApprovalStoreUnavailableError("account separation record failed its integrity check")

                verifier = WebAuthnVerifier(self._policy, _CredentialRows(connection), self._clock)
                try:
                    result = verifier.verify(statement, response)
                except WebAuthnVerificationError as error:
                    raise ApprovalRefusedError(f"WebAuthn assertion refused: {error}") from None
                if result.authorized_at < now:
                    raise ApprovalRefusedError("approval clock moved backwards")

                row = connection.execute(
                    "SELECT sign_count FROM credentials WHERE credential_id = ? AND state = 'ACTIVE'",
                    (result.credential_id,),
                ).fetchone()
                if row is None:
                    raise ApprovalRefusedError("WebAuthn credential is not active")
                stored_count = row[0]
                if not _counter_advances(stored_count, result.sign_count):
                    counter_signal = (result.credential_id, stored_count, result.sign_count)
                    raise ApprovalRefusedError(
                        "WebAuthn signature counter did not advance; recorded as a signal, not as proof of cloning"
                    )

                approved = connection.execute(
                    "UPDATE approval_requests SET state = 'APPROVED', approved_at_ms = ?,"
                    " approved_credential_id = ? WHERE approval_id = ? AND state = 'PENDING'",
                    (result.authorized_at, result.credential_id, approval_id),
                ).rowcount
                counted = connection.execute(
                    "UPDATE credentials SET sign_count = ?, backup_state = ?"
                    " WHERE credential_id = ? AND state = 'ACTIVE' AND sign_count = ?",
                    (result.sign_count, int(result.backup_state), result.credential_id, stored_count),
                ).rowcount
                if approved != 1 or counted != 1:
                    raise ApprovalStoreUnavailableError("approval request or credential changed during the transaction")
                connection.execute(
                    "UPDATE store_meta SET last_observed_ms = MAX(last_observed_ms, ?) WHERE singleton = 1",
                    (result.authorized_at,),
                )
                _append_journal(
                    connection,
                    result.authorized_at,
                    "REQUEST_APPROVED",
                    approval_id=approval_id,
                    credential_id=result.credential_id,
                )
        except ApprovalRefusedError as refusal:
            if counter_signal is not None:
                self._record_counter_signal(approval_id, *counter_signal, refusal=refusal)
            elif expiry is not None:
                self._expire_after_refusal(approval_id, expiry, refusal)
            raise
        return result

    def expire_request(self, approval_id: str) -> bool:
        """Move a due PENDING request to EXPIRED; ``False`` if nothing changed.

        APPROVED requests are left alone: their expiry matters only to a
        future consumption step.
        """

        if type(approval_id) is not str or not approval_id:
            raise ApprovalRefusedError("approval ID is missing or malformed")
        with self._write_transaction() as connection:
            now = self._observe_clock(connection)
            statement, state = _load_statement(connection, approval_id)
            if state != "PENDING" or now < _expiry_instant(statement):
                return False
            connection.execute(
                "UPDATE approval_requests SET state = 'EXPIRED', closed_at_ms = ?"
                " WHERE approval_id = ? AND state = 'PENDING'",
                (now, approval_id),
            )
            _append_journal(connection, now, "REQUEST_EXPIRED", approval_id=approval_id)
            return True

    def revoke_credential(self, credential_id: bytes) -> bool:
        """Revoke a credential for good, with its still-APPROVED requests.

        Returns ``False`` if it was already revoked. A clock moving backwards
        does not block a revocation, which then records the last observed
        instant; an unusable clock still refuses it.
        """

        if (
            type(credential_id) is not bytes
            or not _MIN_CREDENTIAL_ID_BYTES <= len(credential_id) <= _MAX_CREDENTIAL_ID_BYTES
        ):
            raise ApprovalRefusedError("credential ID is missing or malformed")
        with self._write_transaction() as connection:
            now = self._observe_clock(connection, allow_regression=True)
            row = connection.execute(
                "SELECT state FROM credentials WHERE credential_id = ?", (credential_id,)
            ).fetchone()
            if row is None:
                raise ApprovalRefusedError("credential is not registered")
            if row[0] == "REVOKED":
                return False
            connection.execute(
                "UPDATE credentials SET state = 'REVOKED', revoked_at_ms = ?"
                " WHERE credential_id = ? AND state = 'ACTIVE'",
                (now, credential_id),
            )
            approvals = [
                approval_id
                for (approval_id,) in connection.execute(
                    "SELECT approval_id FROM approval_requests"
                    " WHERE approved_credential_id = ? AND state = 'APPROVED' ORDER BY approval_id",
                    (credential_id,),
                )
            ]
            connection.execute(
                "UPDATE approval_requests SET state = 'REVOKED', closed_at_ms = ?"
                " WHERE approved_credential_id = ? AND state = 'APPROVED'",
                (now, credential_id),
            )
            _append_journal(connection, now, "CREDENTIAL_REVOKED", credential_id=credential_id)
            for approval_id in approvals:
                _append_journal(
                    connection, now, "APPROVAL_REVOKED", approval_id=approval_id, credential_id=credential_id
                )
            return True

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        _check_sqlite_version()
        _check_files(self._path)
        connection = _connect(self._path, self._busy_timeout)
        try:
            try:
                _verify_connection(connection, self._busy_timeout)
            except sqlite3.Error as error:
                raise _store_error(error, "database could not be verified", self._busy_timeout) from None
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _write_transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.Error as error:
                raise _store_error(error, "write transaction could not start", self._busy_timeout) from None
            try:
                yield connection
            except sqlite3.Error as error:
                _rollback(connection)
                raise _store_error(error, "transaction failed and was rolled back", self._busy_timeout) from None
            except BaseException:
                _rollback(connection)
                raise
            try:
                connection.execute("COMMIT")
            except sqlite3.Error as error:
                _rollback(connection)
                raise _store_error(
                    error, "commit failed; re-read the state before any retry", self._busy_timeout
                ) from None

    def _read_clock(self) -> int:
        try:
            now = self._clock()
        except Exception:
            raise ApprovalRefusedError("approval clock is unavailable") from None
        if type(now) is not int or now <= 0:
            raise ApprovalRefusedError("approval clock returned an invalid timestamp")
        return now

    def _observe_clock(self, connection: sqlite3.Connection, *, allow_regression: bool = False) -> int:
        """Read the clock and refuse any instant before the last one recorded."""

        now = self._read_clock()
        last_observed = connection.execute("SELECT last_observed_ms FROM store_meta WHERE singleton = 1").fetchone()
        if last_observed is None:
            raise ApprovalStoreUnavailableError("store metadata is missing")
        if now < last_observed[0]:
            if not allow_regression:
                raise ApprovalRefusedError("approval clock moved backwards")
            return last_observed[0]
        connection.execute("UPDATE store_meta SET last_observed_ms = ? WHERE singleton = 1", (now,))
        return now

    def _expire_after_refusal(self, approval_id: str, expiry: int, refusal: ApprovalRefusedError) -> None:
        # Runs only after the approval transaction has rolled back: the
        # EXPIRED transition is committed on its own, never undone with it.
        try:
            if self._read_clock() >= expiry:
                self.expire_request(approval_id)
        except ApprovalStoreError as error:
            refusal.add_note(f"the expiry could not be recorded ({type(error).__name__}); the request stays refused")

    def _record_counter_signal(
        self,
        approval_id: str,
        credential_id: bytes,
        stored_count: int,
        presented_count: int,
        *,
        refusal: ApprovalRefusedError,
    ) -> None:
        # Committed on its own after the rollback; no revocation or closure.
        try:
            with self._write_transaction() as connection:
                now = self._observe_clock(connection)
                _append_journal(
                    connection,
                    now,
                    "COUNTER_SIGNAL",
                    approval_id=approval_id,
                    credential_id=credential_id,
                    stored_sign_count=stored_count,
                    presented_sign_count=presented_count,
                )
        except ApprovalStoreError as error:
            refusal.add_note(f"the counter signal could not be recorded ({type(error).__name__})")
