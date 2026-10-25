"""Mock-only G2 approval store schema v5: pending enrollments, confirmed apart.

This is a fresh-file schema. It does not migrate or modify schema v3 or v4:
both stores keep rejecting a v5 database, ``initialize`` never reuses an
existing file, and opening accepts only a file whose objects are exactly
those of schema v5. The inherited approval-request operations use the same
immutable v3 contract plus three enrollment tables.

Consuming an invitation only records a PENDING enrollment: no principal,
approver, GitHub account or credential row exists before a separate
confirmation, which inserts them all ACTIVE in one transaction and leaves a
confirmation trace distinct from the ``ADMIN_ATTESTED`` registry evidence.
A pending enrollment has no expiry: its lifetime is not decided here.

This module is storage machinery only. Its primitives are unauthenticated
and reserved for isolated tests: they authenticate no administrator and do
not verify that the owner confirmed anything over SSH; they must not be
exposed through any interface or endpoint, nor connected to a Provider. They
run no OAuth exchange and verify no WebAuthn registration: the caller
supplies the GitHub account ID and the credential. That account ID is the
REST user ID that the future GitHub App flow would read with ``GET /user``;
whether it equals an OIDC ``actor_id`` (H1) is not established. No person's
identity is proved, and G1 D-5 stays unresolved.
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
from typing import Callable, Iterator

from fido2.webauthn import AttestedCredentialData

from approval_service import approval_store as _v3
from approval_service.approval_store import (
    ApprovalRefusedError,
    ApprovalStore,
    ApprovalStoreBusyError,
    ApprovalStoreError,
    ApprovalStoreUnavailableError,
)

SCHEMA_VERSION = 5
APPLICATION_ID = _v3.APPLICATION_ID
DEFAULT_BUSY_TIMEOUT_SECONDS = _v3.DEFAULT_BUSY_TIMEOUT_SECONDS
MAX_BUSY_TIMEOUT_SECONDS = _v3.MAX_BUSY_TIMEOUT_SECONDS
# Proof kind of a pending enrollment: the caller states that the GitHub user
# ID it read matched the expected ID of the invitation. Not ADMIN_ATTESTED.
ACCOUNT_PROOF = "EXPECTED_GITHUB_USER_ID_MATCHED"
# Trace of a confirmation. The primitive authenticates nobody, and says so.
CONFIRMATION_EVIDENCE = "UNAUTHENTICATED_MOCK_CONFIRMATION"
_MAX_SQLITE_INTEGER = (1 << 63) - 1
_MAX_SIGN_COUNT = 4294967295
_MAX_USER_HANDLE_BYTES = 64
_INVITATION_ID = re.compile(r"^[0-9a-f]{32}$")
_SECRET = re.compile(r"^[A-Za-z0-9_-]{43}$")
_INVITATION_UNAVAILABLE = "invitation is invalid or unavailable"
_ENROLLMENT_UNAVAILABLE = "enrollment is unknown or not pending"

_ENROLLMENT_SCHEMA = (
    f"""CREATE TABLE enrollment_invitations (
        invitation_id TEXT PRIMARY KEY
            CHECK (length(invitation_id) = 32 AND invitation_id NOT GLOB '*[^0-9a-f]*'),
        secret_sha256 TEXT NOT NULL UNIQUE
            CHECK (length(secret_sha256) = 64 AND secret_sha256 NOT GLOB '*[^0-9a-f]*'),
        approver_id TEXT NOT NULL CHECK ({_v3._REGISTRY_ID_CHECK.format("approver_id")}),
        principal_id TEXT NOT NULL CHECK ({_v3._REGISTRY_ID_CHECK.format("principal_id")}),
        expected_account_id TEXT NOT NULL CHECK ({_v3._ACCOUNT_ID_CHECK.format("expected_account_id")}),
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
    """CREATE UNIQUE INDEX enrollment_one_open_per_account
        ON enrollment_invitations (expected_account_id) WHERE state = 'ISSUED'""",
    """CREATE TRIGGER enrollment_insert_issued BEFORE INSERT ON enrollment_invitations
        WHEN NEW.state <> 'ISSUED'
        BEGIN SELECT RAISE(ABORT, 'invitations are created ISSUED'); END""",
    """CREATE TRIGGER enrollment_permanent BEFORE DELETE ON enrollment_invitations
        BEGIN SELECT RAISE(ABORT, 'invitations are never deleted'); END""",
    """CREATE TRIGGER enrollment_identity_immutable
        BEFORE UPDATE OF invitation_id, secret_sha256, approver_id, principal_id, expected_account_id,
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
                    AND (approver_id = NEW.approver_id OR principal_id = NEW.principal_id
                        OR expected_account_id = NEW.expected_account_id))
        )
        BEGIN SELECT RAISE(ABORT, 'existing invitation rows are never replaced'); END""",
    # One pending enrollment per consumed invitation. It holds the credential
    # until confirmation; nothing here is read by the v3 approval operations.
    """CREATE TABLE pending_enrollments (
        invitation_id TEXT PRIMARY KEY REFERENCES enrollment_invitations (invitation_id),
        account_proof TEXT NOT NULL CHECK (account_proof = 'EXPECTED_GITHUB_USER_ID_MATCHED'),
        credential_id BLOB NOT NULL UNIQUE CHECK (length(credential_id) BETWEEN 16 AND 1023),
        credential_data BLOB NOT NULL,
        user_handle BLOB NOT NULL CHECK (length(user_handle) BETWEEN 1 AND 64),
        backup_eligible INTEGER NOT NULL CHECK (backup_eligible IN (0, 1)),
        backup_state INTEGER NOT NULL CHECK (backup_state IN (0, 1) AND backup_state <= backup_eligible),
        sign_count INTEGER NOT NULL CHECK (sign_count BETWEEN 0 AND 4294967295),
        created_at_ms INTEGER NOT NULL CHECK (created_at_ms > 0),
        state TEXT NOT NULL CHECK (state IN ('PENDING', 'CONFIRMED', 'REJECTED')),
        closed_at_ms INTEGER,
        CHECK ((state = 'PENDING') = (closed_at_ms IS NULL)),
        CHECK (closed_at_ms IS NULL OR closed_at_ms >= created_at_ms)
    ) STRICT""",
    """CREATE TRIGGER pending_enrollments_created_pending BEFORE INSERT ON pending_enrollments
        WHEN NEW.state <> 'PENDING' OR NOT EXISTS (
            SELECT 1 FROM enrollment_invitations
            WHERE invitation_id = NEW.invitation_id AND state = 'CONSUMED'
        )
        BEGIN SELECT RAISE(ABORT, 'enrollments are created PENDING from a consumed invitation'); END""",
    """CREATE TRIGGER pending_enrollments_permanent BEFORE DELETE ON pending_enrollments
        BEGIN SELECT RAISE(ABORT, 'enrollments are never deleted'); END""",
    """CREATE TRIGGER pending_enrollments_identity_immutable
        BEFORE UPDATE OF invitation_id, account_proof, credential_id, credential_data, user_handle,
            backup_eligible, backup_state, sign_count, created_at_ms ON pending_enrollments
        BEGIN SELECT RAISE(ABORT, 'enrollment content is immutable'); END""",
    """CREATE TRIGGER pending_enrollments_transitions BEFORE UPDATE ON pending_enrollments
        WHEN NOT (
            OLD.state = 'PENDING'
            AND NEW.state IN ('CONFIRMED', 'REJECTED')
            AND NEW.closed_at_ms IS NOT NULL
        )
        BEGIN SELECT RAISE(ABORT, 'enrollment transition is not allowed'); END""",
    """CREATE TRIGGER pending_enrollments_rowid_immutable BEFORE UPDATE ON pending_enrollments
        WHEN NEW.rowid IS NOT OLD.rowid
        BEGIN SELECT RAISE(ABORT, 'the rowid of enrollments never changes'); END""",
    _v3._never_replaced(
        "pending_enrollments", "invitation_id = NEW.invitation_id OR credential_id = NEW.credential_id"
    ),
    # Append-only confirmation trace, separate from ADMIN_ATTESTED.
    """CREATE TABLE enrollment_confirmations (
        invitation_id TEXT PRIMARY KEY REFERENCES pending_enrollments (invitation_id),
        evidence TEXT NOT NULL CHECK (evidence = 'UNAUTHENTICATED_MOCK_CONFIRMATION'),
        confirmed_at_ms INTEGER NOT NULL CHECK (confirmed_at_ms > 0)
    ) STRICT""",
    """CREATE TRIGGER enrollment_confirmations_of_pending BEFORE INSERT ON enrollment_confirmations
        WHEN NOT EXISTS (
            SELECT 1 FROM pending_enrollments WHERE invitation_id = NEW.invitation_id AND state = 'PENDING'
        )
        BEGIN SELECT RAISE(ABORT, 'only a pending enrollment can be confirmed'); END""",
    """CREATE TRIGGER enrollment_confirmations_append_only_update BEFORE UPDATE ON enrollment_confirmations
        BEGIN SELECT RAISE(ABORT, 'confirmations are append-only'); END""",
    """CREATE TRIGGER enrollment_confirmations_append_only_delete BEFORE DELETE ON enrollment_confirmations
        BEGIN SELECT RAISE(ABORT, 'confirmations are append-only'); END""",
    _v3._never_replaced("enrollment_confirmations", "invitation_id = NEW.invitation_id"),
    # CONFIRMED requires the confirmation trace and the activated rows, which
    # the confirmation inserts first, in the same transaction.
    """CREATE TRIGGER pending_enrollments_confirmed_activated BEFORE UPDATE ON pending_enrollments
        WHEN NEW.state = 'CONFIRMED' AND NOT (
            EXISTS (SELECT 1 FROM enrollment_confirmations WHERE invitation_id = NEW.invitation_id)
            AND EXISTS (
                SELECT 1 FROM credentials
                JOIN approvers USING (approver_id)
                JOIN enrollment_invitations AS invitation
                    ON invitation.approver_id = approvers.approver_id
                    AND invitation.principal_id = approvers.principal_id
                JOIN github_accounts AS account
                    ON account.account_id = invitation.expected_account_id
                    AND account.principal_id = invitation.principal_id
                WHERE credentials.credential_id = NEW.credential_id
                    AND invitation.invitation_id = NEW.invitation_id
                    AND credentials.state = 'ACTIVE' AND approvers.state = 'ACTIVE' AND account.state = 'ACTIVE'
            )
        )
        BEGIN SELECT RAISE(ABORT, 'a confirmed enrollment requires its trace and activated rows'); END""",
)

_SCHEMA = _v3._SCHEMA + _ENROLLMENT_SCHEMA


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
class EnrollmentCredential:
    """WebAuthn credential fields supplied by the caller, not verified here.

    No registration ceremony (challenge, origin, RP ID, UV, attestation,
    D-3/D-4 rules) is checked by this store; ``credential_data`` must only
    parse as fido2 ``AttestedCredentialData``.
    """

    credential_data: bytes
    user_handle: bytes
    backup_eligible: bool
    backup_state: bool
    sign_count: int


@dataclass(frozen=True, slots=True)
class PendingEnrollment:
    """An enrollment recorded PENDING; nothing is active yet."""

    invitation_id: str
    approver_id: str
    principal_id: str
    account_id: str


@dataclass(frozen=True, slots=True)
class ConfirmedEnrollment:
    """Registry and credential rows activated by one confirmation."""

    invitation_id: str
    approver_id: str
    principal_id: str
    account_id: str
    credential_id: bytes


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


def _require_account_id(value: object, what: str) -> str:
    if type(value) is not str or _v3._ACCOUNT_ID.fullmatch(value) is None:
        raise ApprovalRefusedError(f"{what} is missing or malformed")
    return value


def _require_timestamp(value: object, name: str) -> int:
    if type(value) is not int or not 0 < value <= _MAX_SQLITE_INTEGER:
        raise ApprovalRefusedError(f"{name} is malformed")
    return value


def _require_invitation_id(value: object) -> str:
    if type(value) is not str or _INVITATION_ID.fullmatch(value) is None:
        raise ApprovalRefusedError("invitation ID is missing or malformed")
    return value


def _checked_credential(credential: object) -> tuple[bytes, EnrollmentCredential]:
    """Return the credential ID of well-formed caller-supplied fields."""

    if not isinstance(credential, EnrollmentCredential):
        raise ApprovalRefusedError("enrollment credential is missing or malformed")
    if (
        type(credential.credential_data) is not bytes
        or type(credential.user_handle) is not bytes
        or not 1 <= len(credential.user_handle) <= _MAX_USER_HANDLE_BYTES
        or type(credential.backup_eligible) is not bool
        or type(credential.backup_state) is not bool
        or (credential.backup_state and not credential.backup_eligible)
        or type(credential.sign_count) is not int
        or not 0 <= credential.sign_count <= _MAX_SIGN_COUNT
    ):
        raise ApprovalRefusedError("enrollment credential is missing or malformed")
    try:
        credential_id = AttestedCredentialData(credential.credential_data).credential_id
    except Exception:
        raise ApprovalRefusedError("enrollment credential is missing or malformed") from None
    if not _v3._MIN_CREDENTIAL_ID_BYTES <= len(credential_id) <= _v3._MAX_CREDENTIAL_ID_BYTES:
        raise ApprovalRefusedError("enrollment credential is missing or malformed")
    return credential_id, credential


class ApprovalStoreV5(ApprovalStore):
    """Fresh-file schema v5 store with mock-only pending enrollments.

    All inherited v3 request and revocation operations remain available and
    see only confirmed enrollments. Every enrollment primitive below is
    unauthenticated and reserved for isolated tests.
    """

    @classmethod
    def initialize(
        cls,
        path: str | os.PathLike[str],
        clock: Callable[[], int],
        *,
        busy_timeout_seconds: float = DEFAULT_BUSY_TIMEOUT_SECONDS,
    ) -> ApprovalStoreV5:
        """Create schema v5 in a brand-new file; never migrate or reuse a file."""

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
        expected_account_id: str,
        *,
        expires_at_ms: int,
    ) -> IssuedInvitation:
        """Create an invitation bound to an expected GitHub user ID.

        Return its 256-bit secret exactly once. The expected ID is the one the
        owner receives from B over a separate channel. This method does not
        authenticate its caller; its use is restricted to isolated tests.
        """

        approver_id = _require_registry_id(approver_id)
        principal_id = _require_registry_id(principal_id)
        expected_account_id = _require_account_id(expected_account_id, "expected GitHub account ID")
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
                " SELECT 1 FROM approvers WHERE approver_id = ? UNION ALL"
                " SELECT 1 FROM github_accounts WHERE account_id = ? LIMIT 1",
                (principal_id, approver_id, expected_account_id),
            ).fetchone() is not None:
                raise ApprovalRefusedError("invitation binding is already registered")
            if connection.execute(
                "SELECT 1 FROM pending_enrollments JOIN enrollment_invitations USING (invitation_id)"
                " WHERE pending_enrollments.state = 'PENDING'"
                " AND (approver_id = ? OR principal_id = ? OR expected_account_id = ?) LIMIT 1",
                (approver_id, principal_id, expected_account_id),
            ).fetchone() is not None:
                raise ApprovalRefusedError("an enrollment is already pending for this binding")
            # Close expired invitations for this binding before checking the
            # one-open-invitation constraint, in the same write transaction.
            connection.execute(
                "UPDATE enrollment_invitations SET state = 'EXPIRED', closed_at_ms = ?"
                " WHERE state = 'ISSUED' AND expires_at_ms <= ?"
                " AND (approver_id = ? OR principal_id = ? OR expected_account_id = ?)",
                (now, now, approver_id, principal_id, expected_account_id),
            )
            # The partial unique indexes and the never-replaced trigger would
            # also abort this insert, but as a store failure, not a refusal.
            if connection.execute(
                "SELECT 1 FROM enrollment_invitations WHERE state = 'ISSUED'"
                " AND (approver_id = ? OR principal_id = ? OR expected_account_id = ?) LIMIT 1",
                (approver_id, principal_id, expected_account_id),
            ).fetchone() is not None:
                raise ApprovalRefusedError("an invitation is already open for this binding")
            connection.execute(
                "INSERT INTO enrollment_invitations"
                " (invitation_id, secret_sha256, approver_id, principal_id, expected_account_id,"
                " created_at_ms, expires_at_ms, state, closed_at_ms)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'ISSUED', NULL)",
                (invitation_id, secret_hash, approver_id, principal_id, expected_account_id, now, expires_at_ms),
            )
        return IssuedInvitation(invitation_id, secret, expires_at_ms)

    def consume_invitation(
        self,
        secret: str,
        *,
        account_id: str,
        credential: EnrollmentCredential,
    ) -> PendingEnrollment:
        """Consume once and record a PENDING enrollment; activate nothing.

        ``account_id`` is the GitHub user ID the caller read; it must equal
        the invitation's expected ID, otherwise nothing is written and the
        invitation stays open. Neither the ID nor the credential is verified
        against GitHub or a WebAuthn ceremony here. Unauthenticated; reserved
        for isolated tests.
        """

        if type(secret) is not str or _SECRET.fullmatch(secret) is None:
            raise ApprovalRefusedError(_INVITATION_UNAVAILABLE)
        account_id = _require_account_id(account_id, "GitHub account ID")
        credential_id, credential = _checked_credential(credential)
        secret_hash = hashlib.sha256(secret.encode("ascii")).hexdigest()
        expired = False
        pending: PendingEnrollment | None = None

        with self._write_transaction() as connection:
            now = self._observe_clock(connection)
            row = connection.execute(
                "SELECT invitation_id, approver_id, principal_id, expected_account_id, expires_at_ms, state"
                " FROM enrollment_invitations WHERE secret_sha256 = ?",
                (secret_hash,),
            ).fetchone()
            if row is None or row[5] != "ISSUED":
                raise ApprovalRefusedError(_INVITATION_UNAVAILABLE)
            invitation_id, approver_id, principal_id, expected_account_id, expires_at_ms, _state = row
            if now >= expires_at_ms:
                connection.execute(
                    "UPDATE enrollment_invitations SET state = 'EXPIRED', closed_at_ms = ?"
                    " WHERE invitation_id = ?",
                    (now, invitation_id),
                )
                expired = True
            else:
                if not secrets.compare_digest(account_id, expected_account_id):
                    raise ApprovalRefusedError("GitHub account does not match the invitation")
                if connection.execute(
                    "SELECT 1 FROM credentials WHERE credential_id = ? UNION ALL"
                    " SELECT 1 FROM pending_enrollments WHERE credential_id = ? LIMIT 1",
                    (credential_id, credential_id),
                ).fetchone() is not None:
                    raise ApprovalRefusedError("enrollment credential is already registered")
                try:
                    connection.execute(
                        "UPDATE enrollment_invitations SET state = 'CONSUMED', closed_at_ms = ?"
                        " WHERE invitation_id = ?",
                        (now, invitation_id),
                    )
                    connection.execute(
                        "INSERT INTO pending_enrollments (invitation_id, account_proof, credential_id,"
                        " credential_data, user_handle, backup_eligible, backup_state, sign_count,"
                        " created_at_ms, state, closed_at_ms)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', NULL)",
                        (
                            invitation_id,
                            ACCOUNT_PROOF,
                            credential_id,
                            credential.credential_data,
                            credential.user_handle,
                            int(credential.backup_eligible),
                            int(credential.backup_state),
                            credential.sign_count,
                            now,
                        ),
                    )
                except sqlite3.IntegrityError:
                    # Rolled back with the CONSUMED transition: the invitation stays open.
                    raise ApprovalRefusedError("enrollment cannot be recorded") from None
                pending = PendingEnrollment(invitation_id, approver_id, principal_id, expected_account_id)

        if expired or pending is None:
            raise ApprovalRefusedError(_INVITATION_UNAVAILABLE)
        return pending

    def confirm_enrollment(self, invitation_id: str) -> ConfirmedEnrollment:
        """Activate a PENDING enrollment and all its rows in one transaction.

        One ``BEGIN IMMEDIATE`` transaction records the confirmation trace
        (``UNAUTHENTICATED_MOCK_CONFIRMATION``), inserts the principal, the
        approver, the GitHub account and the credential ACTIVE, then marks the
        enrollment CONFIRMED. Any failure rolls all of it back. The registry
        column ``github_accounts.evidence`` only accepts ``ADMIN_ATTESTED``;
        the account proof and the confirmation stay recorded apart from it.

        This method does not authenticate its caller and does not prove that
        the owner confirmed over SSH; it is reserved for isolated tests and
        must not be exposed through any interface or endpoint.
        """

        invitation_id = _require_invitation_id(invitation_id)
        with self._write_transaction() as connection:
            now = self._observe_clock(connection)
            row = connection.execute(
                "SELECT approver_id, principal_id, expected_account_id, credential_id, credential_data,"
                " user_handle, backup_eligible, backup_state, sign_count, pending_enrollments.state"
                " FROM pending_enrollments JOIN enrollment_invitations USING (invitation_id)"
                " WHERE invitation_id = ?",
                (invitation_id,),
            ).fetchone()
            if row is None or row[9] != "PENDING":
                raise ApprovalRefusedError(_ENROLLMENT_UNAVAILABLE)
            (
                approver_id, principal_id, account_id, credential_id, credential_data,
                user_handle, backup_eligible, backup_state, sign_count, _state,
            ) = row
            try:
                connection.execute(
                    "INSERT INTO enrollment_confirmations (invitation_id, evidence, confirmed_at_ms)"
                    " VALUES (?, ?, ?)",
                    (invitation_id, CONFIRMATION_EVIDENCE, now),
                )
                connection.execute(
                    "INSERT INTO principals (principal_id, state, revoked_at_ms) VALUES (?, 'ACTIVE', NULL)",
                    (principal_id,),
                )
                connection.execute(
                    "INSERT INTO approvers (approver_id, principal_id, state, revoked_at_ms)"
                    " VALUES (?, ?, 'ACTIVE', NULL)",
                    (approver_id, principal_id),
                )
                connection.execute(
                    "INSERT INTO github_accounts (account_id, principal_id, evidence, attested_at_ms,"
                    " state, revoked_at_ms) VALUES (?, ?, 'ADMIN_ATTESTED', ?, 'ACTIVE', NULL)",
                    (account_id, principal_id, now),
                )
                connection.execute(
                    "INSERT INTO credentials (credential_id, credential_data, approver_id, user_handle,"
                    " backup_eligible, backup_state, sign_count, state, revoked_at_ms)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE', NULL)",
                    (credential_id, credential_data, approver_id, user_handle, backup_eligible, backup_state,
                     sign_count),
                )
                connection.execute(
                    "UPDATE pending_enrollments SET state = 'CONFIRMED', closed_at_ms = ? WHERE invitation_id = ?",
                    (now, invitation_id),
                )
            except sqlite3.IntegrityError:
                # The context manager rolls the whole transaction back,
                # including every insert that succeeded before the failure.
                raise ApprovalRefusedError("enrollment cannot be activated") from None
        return ConfirmedEnrollment(invitation_id, approver_id, principal_id, account_id, credential_id)

    def reject_enrollment(self, invitation_id: str) -> bool:
        """Close a PENDING enrollment as REJECTED without activating anything.

        ``False`` means it was not pending and nothing was written. This is
        an unauthenticated storage primitive, reserved for isolated tests.
        """

        invitation_id = _require_invitation_id(invitation_id)
        with self._write_transaction() as connection:
            row = connection.execute(
                "SELECT state FROM pending_enrollments WHERE invitation_id = ?", (invitation_id,)
            ).fetchone()
            if row is None or row[0] != "PENDING":
                return False
            now = self._observe_clock(connection)
            connection.execute(
                "UPDATE pending_enrollments SET state = 'REJECTED', closed_at_ms = ? WHERE invitation_id = ?",
                (now, invitation_id),
            )
            return True

    def revoke_invitation(self, invitation_id: str) -> bool:
        """Revoke an issued invitation by its non-secret identifier.

        This is an unauthenticated storage primitive, not an admin interface.
        """

        invitation_id = _require_invitation_id(invitation_id)
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
        """Mark all currently expired issued invitations as terminal.

        Pending enrollments are not touched: they have no expiry.
        """

        with self._write_transaction() as connection:
            now = self._observe_clock(connection)
            cursor = connection.execute(
                "UPDATE enrollment_invitations SET state = 'EXPIRED', closed_at_ms = ?"
                " WHERE state = 'ISSUED' AND expires_at_ms <= ?",
                (now, now),
            )
            return cursor.rowcount


__all__ = [
    "ACCOUNT_PROOF",
    "APPLICATION_ID",
    "CONFIRMATION_EVIDENCE",
    "SCHEMA_VERSION",
    "ApprovalStoreV5",
    "ConfirmedEnrollment",
    "EnrollmentCredential",
    "IssuedInvitation",
    "PendingEnrollment",
    "ApprovalRefusedError",
    "ApprovalStoreBusyError",
    "ApprovalStoreError",
    "ApprovalStoreUnavailableError",
]
