"""Synthetic tests for the mock-only G2 durable approval store (SQLite).

Credentials are generated locally and inserted straight into each temporary
database by `_seed_credential()`: the store itself has no enrollment path.
Child processes run this file (`WORKER_FLAG`) for contention and hard stops.
No network, real authenticator, token, secret or provider is used.
"""

import ast
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fido2.cose import ES256
from fido2.utils import websafe_encode
from fido2.webauthn import (
    Aaguid,
    AttestedCredentialData,
    AuthenticationResponse,
    AuthenticatorAssertionResponse,
    AuthenticatorData,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPROVAL_SERVICE_ROOT = PROJECT_ROOT / "approval_service"
if str(APPROVAL_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(APPROVAL_SERVICE_ROOT))

import approval_service.approval_store as store_module
from approval_service.account_separation import AccountBinding
from approval_service.approval_statement import ApprovalStatement
from approval_service.approval_store import (
    APPLICATION_ID,
    SCHEMA_VERSION,
    ApprovalRefusedError,
    ApprovalStore,
    ApprovalStoreBusyError,
    ApprovalStoreError,
    ApprovalStoreUnavailableError,
)

WORKER_FLAG = "--g2-approval-store-worker"
FLAG = AuthenticatorData.FLAG
RP_ID = "zephyr-approval.fr"
ORIGIN = "https://zephyr-approval.fr"
REQUESTED_AT = 1_800_000_000_000
ISSUED_AT = REQUESTED_AT + 1_000
EXPIRES_AT = REQUESTED_AT + 301_000
NOW = ISSUED_AT + 10_000
APPROVER_ID = "approver-pseudonym-1"
OTHER_APPROVER_ID = "approver-pseudonym-2"
ACTOR_ID = "12"
ACTOR_PRINCIPAL = "principal-dispatcher"
APPROVER_PRINCIPAL = "principal-approver"
OTHER_PRINCIPAL = "principal-other"
USER_HANDLE = b"synthetic-approver-handle-1"
FAST_BUSY_TIMEOUT = 0.2
SEPARATION_REFUSED = "account separation between the run and the approver is not established"


def _statement(n=1, **overrides) -> ApprovalStatement:
    values = dict(
        relying_party_id=RP_ID,
        approver_id=APPROVER_ID,
        auth_method="webauthn",
        repository_id="123456789",
        repository="cleevengtonzephyr-ux/AI_DIRECTOR",
        sha="a" * 40,
        workflow_ref="cleevengtonzephyr-ux/AI_DIRECTOR/.github/workflows/higgsfield-production.yml@refs/heads/main",
        run_id=str(987654320 + n),
        run_attempt=1,
        run_actor_id="12",
        manifest_sha256="1" * 64,
        prompt_sha256="2" * 64,
        avatar_sha256="3" * 64,
        face_reference_sha256="4" * 64,
        job_type="seedance_2_0",
        duration=5,
        resolution="720p",
        aspect_ratio="9:16",
        request_id=f"request-{n}",
        authorization_id=f"authorization-{n}",
        approval_id=f"approval-{n}",
        nonce=hashlib.sha256(f"synthetic-nonce-{n}".encode()).hexdigest(),
        requested_at=REQUESTED_AT,
        approval_deadline=REQUESTED_AT + 600_000,
        issued_at=ISSUED_AT,
        expires_at=EXPIRES_AT,
        max_cost_credits_per_request=None,
    )
    values.update(overrides)
    return ApprovalStatement(**values)


@dataclass(frozen=True)
class _Credential:
    credential_id: bytes
    private_key: ec.EllipticCurvePrivateKey
    data: AttestedCredentialData


def _new_credential(label: str) -> _Credential:
    private_key = ec.generate_private_key(ec.SECP256R1())
    credential_id = hashlib.sha256(label.encode()).digest()
    data = AttestedCredentialData.create(
        Aaguid.NONE, credential_id, ES256.from_cryptography_key(private_key.public_key())
    )
    return _Credential(credential_id, private_key, data)


def _seed_registry(db_path, *, principals=(), approvers=(), accounts=()):
    """Test-only administrator attestation: registry rows written directly.

    ``principals``: principal IDs; ``approvers``: (approver_id, principal_id);
    ``accounts``: (account_id, principal_id). Every row starts ACTIVE.
    """

    connection = sqlite3.connect(db_path)
    try:
        with connection:
            for principal_id in principals:
                connection.execute("INSERT INTO principals (principal_id, state) VALUES (?, 'ACTIVE')", (principal_id,))
            for approver_id, principal_id in approvers:
                connection.execute(
                    "INSERT INTO approvers (approver_id, principal_id, state) VALUES (?, ?, 'ACTIVE')",
                    (approver_id, principal_id),
                )
            for account_id, principal_id in accounts:
                connection.execute(
                    "INSERT INTO github_accounts (account_id, principal_id, evidence, attested_at_ms, state)"
                    " VALUES (?, ?, 'ADMIN_ATTESTED', ?, 'ACTIVE')",
                    (account_id, principal_id, REQUESTED_AT),
                )
    finally:
        connection.close()


def _seed_default_registry(db_path):
    _seed_registry(
        db_path,
        principals=(ACTOR_PRINCIPAL, APPROVER_PRINCIPAL, OTHER_PRINCIPAL),
        approvers=((APPROVER_ID, APPROVER_PRINCIPAL), (OTHER_APPROVER_ID, OTHER_PRINCIPAL)),
        accounts=((ACTOR_ID, ACTOR_PRINCIPAL),),
    )


def _revoke(db_path, table, key_column, key, at_ms=NOW):
    """Test-only revocation: the store itself has no revocation path for the registry."""

    connection = sqlite3.connect(db_path)
    try:
        with connection:
            connection.execute(
                f"UPDATE {table} SET state = 'REVOKED', revoked_at_ms = ? WHERE {key_column} = ?", (at_ms, key)
            )
    finally:
        connection.close()


def _seed_credential(
    db_path, credential, *, backup_eligible=False, backup_state=False, sign_count=0, approver_id=APPROVER_ID
):
    """Test-only enrollment: one synthetic credential row written directly."""

    connection = sqlite3.connect(db_path)
    try:
        with connection:
            connection.execute(
                "INSERT INTO credentials (credential_id, credential_data, approver_id, user_handle,"
                " backup_eligible, backup_state, sign_count, state) VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE')",
                (
                    credential.credential_id,
                    bytes(credential.data),
                    approver_id,
                    USER_HANDLE,
                    int(backup_eligible),
                    int(backup_state),
                    sign_count,
                ),
            )
    finally:
        connection.close()


def _response(statement, credential, *, sign_count=1, flags=FLAG.UP | FLAG.UV, signer=None):
    """Act as the synthetic authenticator; return AuthenticationResponseJSON."""

    client_data = json.dumps(
        {
            "type": "webauthn.get",
            "challenge": websafe_encode(statement.webauthn_challenge()),
            "origin": ORIGIN,
            "crossOrigin": False,
        },
        separators=(",", ":"),
    ).encode()
    auth_data = AuthenticatorData.create(hashlib.sha256(RP_ID.encode()).digest(), flags, sign_count)
    signer = signer or credential.private_key
    signature = signer.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
    response = AuthenticationResponse(
        raw_id=credential.credential_id,
        response=AuthenticatorAssertionResponse(
            client_data=client_data,
            authenticator_data=auth_data,
            signature=signature,
            user_handle=USER_HANDLE,
        ),
    )
    return json.loads(json.dumps(dict(response)))


class _Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


class _SequenceClock:
    """Return the given instants in order, then repeat the last one."""

    def __init__(self, *instants):
        self._instants = list(instants)

    def __call__(self):
        return self._instants.pop(0) if len(self._instants) > 1 else self._instants[0]


def _wait_for(condition, what, timeout=120):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"timeout waiting for {what}")
        time.sleep(0.005)


# ----------------------------------------------------------------------
# Child processes (never run by unittest)
# ----------------------------------------------------------------------


def _worker(mode, db_path, now, approval_id, response_path, sandbox):
    sandbox = Path(sandbox)
    store = ApprovalStore(db_path, lambda: int(now), busy_timeout_seconds=10.0)
    response = json.loads(Path(response_path).read_text(encoding="utf-8"))

    if mode == "contend":
        (sandbox / f"ready-{os.getpid()}").write_text("1", encoding="utf-8")
        _wait_for((sandbox / "go").exists, "the start signal")
        try:
            store.approve(approval_id, response)
            outcome = "APPROVED"
        except ApprovalStoreBusyError:
            outcome = "BUSY"
        except ApprovalRefusedError as error:
            outcome = f"REFUSED: {error}"
        except BaseException as error:  # noqa: B902 -- reported to the test
            outcome = f"ERROR: {error!r}"
        print(json.dumps({"outcome": outcome}))
        return

    def stop_here():
        (sandbox / "stopped").write_text("1", encoding="utf-8")
        time.sleep(120)

    if mode == "stop_before_commit":
        original = store_module._append_journal

        def pausing(connection, at_ms, event, **kwargs):
            original(connection, at_ms, event, **kwargs)
            if event == "REQUEST_APPROVED":
                # Every approval write is done; COMMIT has not run yet.
                stop_here()

        store_module._append_journal = pausing
        store.approve(approval_id, response)
    elif mode == "stop_after_commit":
        store.approve(approval_id, response)
        stop_here()
    sys.exit(1)


# ----------------------------------------------------------------------
# Test fixtures
# ----------------------------------------------------------------------


class _StoreTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.credential = _new_credential("synthetic-credential-1")
        cls.other_credential = _new_credential("synthetic-credential-2")

    def setUp(self):
        self.sandbox = Path(tempfile.mkdtemp(prefix="g2_store_"))
        self.addCleanup(shutil.rmtree, self.sandbox, ignore_errors=True)
        self.db_path = self.sandbox / "approvals.sqlite3"
        self.clock = _Clock()
        self.store = ApprovalStore.initialize(self.db_path, self.clock, busy_timeout_seconds=FAST_BUSY_TIMEOUT)
        _seed_default_registry(self.db_path)

    def _rows(self, sql, params=(), db_path=None):
        connection = sqlite3.connect(self.db_path if db_path is None else db_path)
        try:
            return connection.execute(sql, params).fetchall()
        finally:
            connection.close()

    def _tamper(self, approval_id, **columns):
        """Bypass the protecting triggers and restore them, as an attacker with file access could."""

        names = ("approval_requests_statement_immutable", "approval_requests_transitions")
        triggers = [self._rows("SELECT sql FROM sqlite_schema WHERE name = ?", (name,))[0][0] for name in names]
        assignments = ", ".join(f"{name} = ?" for name in columns)
        self._write(
            *((f"DROP TRIGGER {name}", ()) for name in names),
            (f"UPDATE approval_requests SET {assignments} WHERE approval_id = ?", (*columns.values(), approval_id)),
            *((sql, ()) for sql in triggers),
        )

    def _write(self, *statements):
        """Direct SQL in one all-or-nothing transaction, as a process with file access could do."""

        connection = sqlite3.connect(self.db_path, autocommit=False)
        try:
            with connection:
                for sql, params in statements:
                    connection.execute(sql, params)
        finally:
            connection.close()

    def _state(self, approval_id):
        rows = self._rows("SELECT state FROM approval_requests WHERE approval_id = ?", (approval_id,))
        return rows[0][0] if rows else None

    def _credential_row(self, credential):
        return self._rows(
            "SELECT sign_count, backup_state, state FROM credentials WHERE credential_id = ?",
            (credential.credential_id,),
        )[0]

    def _journal(self):
        return self._rows(
            "SELECT event, approval_id, credential_sha256, stored_sign_count, presented_sign_count"
            " FROM journal ORDER BY sequence"
        )

    def _last_observed(self):
        return self._rows("SELECT last_observed_ms FROM store_meta")[0][0]

    def _pending(self, n=1, credential=None, **seed):
        """Seed `credential` (if given) and create PENDING request `n`."""

        if credential is not None:
            _seed_credential(self.db_path, credential, **seed)
        statement = _statement(n)
        self.store.create_request(statement)
        return statement


# ----------------------------------------------------------------------
# Initialization and ordinary opening
# ----------------------------------------------------------------------


class TestInitializationAndOpening(_StoreTestCase):
    def test_initialize_creates_a_private_wal_schema_version_2(self):
        connection = sqlite3.connect(self.db_path)
        try:
            pragmas = {
                name: connection.execute(f"PRAGMA {name}").fetchone()[0]
                for name in ("application_id", "user_version", "journal_mode")
            }
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")}
        finally:
            connection.close()
        self.assertEqual(SCHEMA_VERSION, 2)
        self.assertEqual(
            pragmas, {"application_id": APPLICATION_ID, "user_version": SCHEMA_VERSION, "journal_mode": "wal"}
        )
        self.assertEqual(
            tables,
            {"store_meta", "principals", "approvers", "github_accounts", "credentials", "approval_requests", "journal"},
        )
        self.assertEqual(self._last_observed(), 0)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.db_path.stat().st_mode), 0o600)
        ApprovalStore(self.db_path, self.clock)

    def test_initialize_never_reuses_an_existing_file(self):
        with self.assertRaisesRegex(ApprovalStoreUnavailableError, "already exists"):
            ApprovalStore.initialize(self.db_path, self.clock)
        other = self.sandbox / "other.sqlite3"
        other.write_bytes(b"")
        with self.assertRaisesRegex(ApprovalStoreUnavailableError, "already exists"):
            ApprovalStore.initialize(other, self.clock)
        self.assertEqual(other.read_bytes(), b"")

    def test_ordinary_open_refuses_an_absent_database_without_creating_it(self):
        missing = self.sandbox / "missing.sqlite3"
        with self.assertRaisesRegex(ApprovalStoreUnavailableError, "absent"):
            ApprovalStore(missing, self.clock)
        self.assertFalse(missing.exists())
        with self.assertRaisesRegex(ApprovalStoreUnavailableError, "absolute"):
            ApprovalStore("relative.sqlite3", self.clock)

        self.db_path.unlink()
        with self.assertRaisesRegex(ApprovalStoreUnavailableError, "absent"):
            self.store.create_request(_statement())
        self.assertFalse(self.db_path.exists())

    def test_ordinary_open_refuses_a_symbolic_link(self):
        link = self.sandbox / "link.sqlite3"
        try:
            os.symlink(self.db_path, link)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symbolic links are not available here: {error}")
        with self.assertRaisesRegex(ApprovalStoreUnavailableError, "symbolic link"):
            ApprovalStore(link, self.clock)

    def test_ordinary_open_refuses_unexpected_identity_version_mode_or_objects(self):
        changes = {
            "application_id": ["PRAGMA application_id = 1"],
            "schema version 1": ["PRAGMA user_version = 1"],
            "schema version 3": ["PRAGMA user_version = 3"],
            "journal_mode": ["PRAGMA journal_mode = DELETE"],
            "objects": ["DROP TRIGGER approval_requests_transitions"],
            "registry table dropped": ["DROP TABLE github_accounts"],
            "replacement guard dropped": ["DROP TRIGGER github_accounts_never_replaced"],
            "extra table": ["CREATE TABLE extra (x INTEGER)"],
        }
        for name, statements in changes.items():
            with self.subTest(change=name):
                path = self.sandbox / f"{name.replace(' ', '_')}.sqlite3"
                ApprovalStore.initialize(path, self.clock)
                connection = sqlite3.connect(path, autocommit=True)
                try:
                    for sql in statements:
                        connection.execute(sql)
                finally:
                    connection.close()
                with self.assertRaises(ApprovalStoreUnavailableError):
                    ApprovalStore(path, self.clock)

    def test_ordinary_open_refuses_a_file_that_is_not_a_database(self):
        garbage = self.sandbox / "garbage.sqlite3"
        descriptor = os.open(garbage, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(descriptor, b"not a database " * 64)
        os.close(descriptor)
        with self.assertRaises(ApprovalStoreUnavailableError):
            ApprovalStore(garbage, self.clock)

    def test_ordinary_open_refuses_foreign_key_violations(self):
        self._pending(1)
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("PRAGMA foreign_keys = OFF")
            with connection:
                connection.execute(
                    "UPDATE approval_requests SET state = 'APPROVED', approved_at_ms = 1,"
                    " approved_credential_id = ? WHERE approval_id = 'approval-1'",
                    (b"x" * 32,),
                )
        finally:
            connection.close()
        with self.assertRaisesRegex(ApprovalStoreUnavailableError, "foreign key"):
            ApprovalStore(self.db_path, self.clock)

    @unittest.skipIf(os.name == "nt", "POSIX permissions only")
    def test_posix_permissions_must_be_private_to_the_owner(self):
        for target, mode in ((self.db_path, 0o644), (self.db_path, 0o660), (self.sandbox, 0o755)):
            original = stat.S_IMODE(target.stat().st_mode)
            with self.subTest(target=target.name, mode=oct(mode)):
                os.chmod(target, mode)
                try:
                    with self.assertRaisesRegex(ApprovalStoreUnavailableError, "no group or other permissions"):
                        ApprovalStore(self.db_path, self.clock)
                finally:
                    os.chmod(target, original)
        ApprovalStore(self.db_path, self.clock)

    def test_busy_timeout_must_be_bounded(self):
        for value in (0, -1, 30.5, float("nan"), float("inf"), "5", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ApprovalStore(self.db_path, self.clock, busy_timeout_seconds=value)

    def test_sqlite_without_strict_tables_is_refused(self):
        with mock.patch.object(store_module.sqlite3, "sqlite_version_info", (3, 36, 0)):
            with self.assertRaisesRegex(ApprovalStoreUnavailableError, "3.37"):
                ApprovalStore(self.db_path, self.clock)


# ----------------------------------------------------------------------
# Approval, replay and binding
# ----------------------------------------------------------------------


class TestApprovalAndReplay(_StoreTestCase):
    def test_nominal_approval_updates_request_counter_backup_state_and_journal(self):
        statement = self._pending(1, self.credential, backup_eligible=True, backup_state=False, sign_count=4)

        flags = FLAG.UP | FLAG.UV | FLAG.BE | FLAG.BS
        result = self.store.approve("approval-1", _response(statement, self.credential, sign_count=5, flags=flags))

        self.assertEqual((result.approval_id, result.authorized_at, result.sign_count), ("approval-1", NOW, 5))
        self.assertEqual(
            self._rows("SELECT state, approved_at_ms, approved_credential_id FROM approval_requests"),
            [("APPROVED", NOW, self.credential.credential_id)],
        )
        self.assertEqual(self._credential_row(self.credential), (5, 1, "ACTIVE"))
        credential_sha256 = hashlib.sha256(self.credential.credential_id).hexdigest()
        self.assertEqual(
            self._journal(),
            [
                ("REQUEST_CREATED", "approval-1", None, None, None),
                ("REQUEST_APPROVED", "approval-1", credential_sha256, None, None),
            ],
        )
        self.assertEqual(self._last_observed(), NOW)

    def test_replayed_assertion_is_refused_even_without_a_counter(self):
        statement = self._pending(1, self.credential, sign_count=0)
        response = _response(statement, self.credential, sign_count=0)
        self.store.approve("approval-1", response)
        journal = self._journal()

        with self.assertRaisesRegex(ApprovalRefusedError, "not pending"):
            self.store.approve("approval-1", response)

        self.assertEqual(self._state("approval-1"), "APPROVED")
        self.assertEqual(self._credential_row(self.credential), (0, 0, "ACTIVE"))
        self.assertEqual(self._journal(), journal)

    def test_assertion_bound_to_another_request_is_refused(self):
        first = self._pending(1, self.credential)
        self._pending(2)

        with self.assertRaisesRegex(ApprovalRefusedError, "challenge"):
            self.store.approve("approval-2", _response(first, self.credential, sign_count=1))

        self.assertEqual(self._state("approval-2"), "PENDING")
        self.assertEqual(self._credential_row(self.credential), (0, 0, "ACTIVE"))
        self.store.approve("approval-1", _response(first, self.credential, sign_count=1))

    def test_invalid_assertion_leaves_the_request_pending(self):
        statement = self._pending(1, self.credential)
        forged = _response(statement, self.credential, signer=self.other_credential.private_key)

        with self.assertRaisesRegex(ApprovalRefusedError, "signature"):
            self.store.approve("approval-1", forged)

        self.assertEqual(self._state("approval-1"), "PENDING")
        self.store.approve("approval-1", _response(statement, self.credential))

    def test_unknown_or_malformed_approval_ids_are_refused(self):
        statement = self._pending(1, self.credential)
        response = _response(statement, self.credential)
        for approval_id in ("approval-9", "", None, 1):
            with self.subTest(approval_id=approval_id), self.assertRaises(ApprovalRefusedError):
                self.store.approve(approval_id, response)
        self.assertEqual(self._state("approval-1"), "PENDING")

    def test_each_request_keeps_one_immutable_statement(self):
        self._pending(1)
        duplicates = {
            "same statement": _statement(1),
            "same request": _statement(2, request_id="request-1"),
            "same authorization": _statement(2, authorization_id="authorization-1"),
            "same nonce": _statement(2, nonce=_statement(1).nonce),
            "same run attempt": _statement(2, run_id=_statement(1).run_id),
        }
        for name, statement in duplicates.items():
            with self.subTest(case=name), self.assertRaisesRegex(ApprovalRefusedError, "already recorded"):
                self.store.create_request(statement)
        with self.assertRaisesRegex(ApprovalRefusedError, "malformed"):
            self.store.create_request(_statement(2).to_dict())
        self.clock.now = EXPIRES_AT
        with self.assertRaisesRegex(ApprovalRefusedError, "already expired"):
            self.store.create_request(_statement(3))
        self.assertEqual(self._rows("SELECT count(*) FROM approval_requests"), [(1,)])


# ----------------------------------------------------------------------
# Stored statement integrity
# ----------------------------------------------------------------------


class TestStatementIntegrity(_StoreTestCase):
    def test_altered_statement_or_digest_is_refused(self):
        statement = self._pending(1, self.credential)
        response = _response(statement, self.credential)
        altered = statement.canonical_bytes().replace(b'"duration":5', b'"duration":15')
        cases = {
            "statement altered": {"statement_json": altered},
            "digest altered": {"statement_sha256": "f" * 64},
            "column differs from statement": {"approver_id": "approver-pseudonym-2"},
            "not JSON": {"statement_json": b"\xff" * 8},
        }
        for name, columns in cases.items():
            with self.subTest(case=name):
                original = self._rows(
                    "SELECT statement_json, statement_sha256, approver_id FROM approval_requests"
                )[0]
                self._tamper("approval-1", **columns)
                try:
                    with self.assertRaisesRegex(ApprovalStoreUnavailableError, "integrity"):
                        self.store.approve("approval-1", response)
                    self.assertEqual(self._state("approval-1"), "PENDING")
                finally:
                    self._tamper(
                        "approval-1",
                        statement_json=original[0],
                        statement_sha256=original[1],
                        approver_id=original[2],
                    )
        self.store.approve("approval-1", response)

    def test_consistent_rewrite_cannot_reuse_the_signed_assertion(self):
        statement = self._pending(1, self.credential)
        response = _response(statement, self.credential)
        rewritten = _statement(1, manifest_sha256="f" * 64)
        self._tamper("approval-1", statement_json=rewritten.canonical_bytes(), statement_sha256=rewritten.sha256())

        with self.assertRaisesRegex(ApprovalRefusedError, "challenge"):
            self.store.approve("approval-1", response)
        self.assertEqual(self._state("approval-1"), "PENDING")


# ----------------------------------------------------------------------
# Signature counters
# ----------------------------------------------------------------------


class TestSignatureCounters(_StoreTestCase):
    def test_zero_to_zero_is_accepted(self):
        statement = self._pending(1, self.credential, sign_count=0)
        self.store.approve("approval-1", _response(statement, self.credential, sign_count=0))
        self.assertEqual(self._credential_row(self.credential), (0, 0, "ACTIVE"))

    def test_increasing_counters_are_accepted(self):
        first = self._pending(1, self.credential, sign_count=0)
        second = self._pending(2)
        self.store.approve("approval-1", _response(first, self.credential, sign_count=5))
        self.store.approve("approval-2", _response(second, self.credential, sign_count=6))
        self.assertEqual(self._credential_row(self.credential), (6, 0, "ACTIVE"))

    def test_non_advancing_counter_is_refused_as_a_signal_and_keeps_the_request_pending(self):
        _seed_credential(self.db_path, self.credential, sign_count=5)
        credential_sha256 = hashlib.sha256(self.credential.credential_id).hexdigest()
        for n, presented in ((1, 5), (2, 3), (3, 0)):
            statement = self._pending(n)
            response = _response(statement, self.credential, sign_count=presented)
            with self.subTest(presented=presented):
                for _attempt in range(2):
                    with self.assertRaisesRegex(ApprovalRefusedError, "signal, not as proof"):
                        self.store.approve(f"approval-{n}", response)
                self.assertEqual(self._state(f"approval-{n}"), "PENDING")
        self.assertEqual(self._credential_row(self.credential), (5, 0, "ACTIVE"))
        self.assertEqual(
            [row for row in self._journal() if row[0] == "COUNTER_SIGNAL"],
            [
                ("COUNTER_SIGNAL", "approval-1", credential_sha256, 5, 5),
                ("COUNTER_SIGNAL", "approval-2", credential_sha256, 5, 3),
                ("COUNTER_SIGNAL", "approval-3", credential_sha256, 5, 0),
            ],
        )

    def test_out_of_order_assertion_is_refused_and_a_fresh_one_succeeds(self):
        first = self._pending(1, self.credential, sign_count=0)
        second = self._pending(2)
        older = _response(first, self.credential, sign_count=5)
        newer = _response(second, self.credential, sign_count=6)

        self.store.approve("approval-2", newer)
        with self.assertRaisesRegex(ApprovalRefusedError, "signal"):
            self.store.approve("approval-1", older)
        self.assertEqual(self._state("approval-1"), "PENDING")

        self.store.approve("approval-1", _response(first, self.credential, sign_count=7))
        self.assertEqual(self._credential_row(self.credential), (7, 0, "ACTIVE"))

    def test_backup_eligibility_is_immutable_while_backup_state_follows_the_assertion(self):
        first = self._pending(1, self.credential, backup_eligible=True, backup_state=True, sign_count=0)
        second = self._pending(2)
        backup_eligible_only = FLAG.UP | FLAG.UV | FLAG.BE
        self.store.approve("approval-1", _response(first, self.credential, sign_count=0, flags=backup_eligible_only))
        self.assertEqual(self._credential_row(self.credential), (0, 0, "ACTIVE"))
        with self.assertRaisesRegex(ApprovalRefusedError, r"\(BE\)"):
            self.store.approve("approval-2", _response(second, self.credential, sign_count=0))
        with self.assertRaises(sqlite3.IntegrityError):
            self._write(("UPDATE credentials SET backup_eligible = 0", ()))


# ----------------------------------------------------------------------
# Expiry
# ----------------------------------------------------------------------


class TestExpiry(_StoreTestCase):
    def test_expired_request_is_marked_in_its_own_committed_transaction(self):
        statement = self._pending(1, self.credential)
        response = _response(statement, self.credential)
        self.clock.now = EXPIRES_AT

        with self.assertRaisesRegex(ApprovalRefusedError, "expired"):
            self.store.approve("approval-1", response)

        self.assertEqual(self._rows("SELECT state, closed_at_ms FROM approval_requests"), [("EXPIRED", EXPIRES_AT)])
        self.assertEqual(self._journal()[-1], ("REQUEST_EXPIRED", "approval-1", None, None, None))
        self.assertEqual(self._credential_row(self.credential), (0, 0, "ACTIVE"))
        self.clock.now = EXPIRES_AT + 60_000
        with self.assertRaisesRegex(ApprovalRefusedError, "not pending"):
            self.store.approve("approval-1", response)

    def test_approval_deadline_before_statement_expiry(self):
        _seed_credential(self.db_path, self.credential)
        late = _statement(1, issued_at=REQUESTED_AT + 500_000, expires_at=REQUESTED_AT + 750_000)
        self.clock.now = REQUESTED_AT + 510_000
        self.store.create_request(late)
        self.clock.now = late.approval_deadline

        with self.assertRaisesRegex(ApprovalRefusedError, "expired"):
            self.store.approve("approval-1", _response(late, self.credential))
        self.assertEqual(self._state("approval-1"), "EXPIRED")

    def test_expiry_seen_by_the_verifier_rolls_back_then_commits_the_expiry(self):
        statement = self._pending(1, self.credential)
        # Approval transaction start, verifier read after the signature, expiry.
        self.store._clock = _SequenceClock(NOW, EXPIRES_AT, EXPIRES_AT)

        with self.assertRaisesRegex(ApprovalRefusedError, "has expired"):
            self.store.approve("approval-1", _response(statement, self.credential))

        self.assertEqual(self._state("approval-1"), "EXPIRED")
        self.assertEqual(self._credential_row(self.credential), (0, 0, "ACTIVE"))
        self.assertNotIn("REQUEST_APPROVED", [row[0] for row in self._journal()])
        self.assertEqual(self._last_observed(), EXPIRES_AT)

    def test_failed_expiry_write_keeps_the_refusal_and_the_request_unapprovable(self):
        statement = self._pending(1, self.credential)
        response = _response(statement, self.credential)
        self.clock.now = EXPIRES_AT
        with mock.patch.object(self.store, "expire_request", side_effect=ApprovalStoreBusyError("synthetic busy")):
            with self.assertRaisesRegex(ApprovalRefusedError, "expired") as context:
                self.store.approve("approval-1", response)
        self.assertIn("could not be recorded", " ".join(context.exception.__notes__))
        self.assertEqual(self._state("approval-1"), "PENDING")

        with self.assertRaisesRegex(ApprovalRefusedError, "expired"):
            self.store.approve("approval-1", response)
        self.assertEqual(self._state("approval-1"), "EXPIRED")

    def test_expire_request_only_moves_due_pending_requests(self):
        first = self._pending(1, self.credential)
        self._pending(2)
        self.store.approve("approval-1", _response(first, self.credential))

        self.assertFalse(self.store.expire_request("approval-2"))
        self.assertEqual(self._state("approval-2"), "PENDING")
        self.clock.now = EXPIRES_AT
        self.assertTrue(self.store.expire_request("approval-2"))
        self.assertFalse(self.store.expire_request("approval-2"))
        self.assertFalse(self.store.expire_request("approval-1"))
        self.assertEqual((self._state("approval-1"), self._state("approval-2")), ("APPROVED", "EXPIRED"))
        with self.assertRaisesRegex(ApprovalRefusedError, "unknown"):
            self.store.expire_request("approval-9")


# ----------------------------------------------------------------------
# Revocation and forbidden transitions
# ----------------------------------------------------------------------


class TestRevocationAndTransitions(_StoreTestCase):
    def test_revocation_is_final_and_revokes_its_approvals_in_the_same_transaction(self):
        first = self._pending(1, self.credential)
        _seed_credential(self.db_path, self.other_credential)
        second = self._pending(2)
        third = self._pending(3)
        self.store.approve("approval-1", _response(first, self.credential, sign_count=1))
        self.store.approve("approval-2", _response(second, self.other_credential, sign_count=1))
        self.clock.now = NOW + 1_000

        self.assertTrue(self.store.revoke_credential(self.credential.credential_id))

        self.assertEqual(self._credential_row(self.credential), (1, 0, "REVOKED"))
        self.assertEqual(
            self._rows("SELECT approval_id, state, closed_at_ms FROM approval_requests ORDER BY approval_id"),
            [("approval-1", "REVOKED", NOW + 1_000), ("approval-2", "APPROVED", None), ("approval-3", "PENDING", None)],
        )
        credential_sha256 = hashlib.sha256(self.credential.credential_id).hexdigest()
        self.assertEqual(
            self._journal()[-2:],
            [
                ("CREDENTIAL_REVOKED", None, credential_sha256, None, None),
                ("APPROVAL_REVOKED", "approval-1", credential_sha256, None, None),
            ],
        )
        self.assertFalse(self.store.revoke_credential(self.credential.credential_id))
        with self.assertRaisesRegex(ApprovalRefusedError, "revoked"):
            self.store.approve("approval-3", _response(third, self.credential, sign_count=2))
        self.store.approve("approval-3", _response(third, self.other_credential, sign_count=2))

    def test_unknown_or_malformed_credentials_cannot_be_revoked(self):
        for credential_id in (b"x" * 32, b"short", "not-bytes", None):
            with self.subTest(credential_id=credential_id), self.assertRaises(ApprovalRefusedError):
                self.store.revoke_credential(credential_id)

    def test_a_clock_moving_backwards_does_not_block_a_revocation(self):
        statement = self._pending(1, self.credential)
        self.clock.now = NOW + 5_000
        self.store.approve("approval-1", _response(statement, self.credential))
        self.clock.now = NOW

        self.assertTrue(self.store.revoke_credential(self.credential.credential_id))
        self.assertEqual(
            self._rows("SELECT revoked_at_ms FROM credentials"), [(NOW + 5_000,)]
        )
        self.assertEqual(self._last_observed(), NOW + 5_000)

    def test_forbidden_transitions_and_deletions_are_aborted_by_the_schema(self):
        first = self._pending(1, self.credential, sign_count=3)
        self._pending(2)
        self._pending(3)
        self.store.approve("approval-1", _response(first, self.credential, sign_count=4))
        self.clock.now = EXPIRES_AT
        self.store.expire_request("approval-3")
        forbidden = {
            "APPROVED back to PENDING": "UPDATE approval_requests SET state = 'PENDING', approved_at_ms = NULL,"
            " approved_credential_id = NULL WHERE approval_id = 'approval-1'",
            "PENDING straight to REVOKED": "UPDATE approval_requests SET state = 'REVOKED', approved_at_ms = 1,"
            " approved_credential_id = NULL, closed_at_ms = 1 WHERE approval_id = 'approval-2'",
            "EXPIRED back to PENDING": "UPDATE approval_requests SET state = 'PENDING', closed_at_ms = NULL"
            " WHERE approval_id = 'approval-3'",
            "statement rewritten": "UPDATE approval_requests SET statement_json = x'00'"
            " WHERE approval_id = 'approval-2'",
            "request deleted": "DELETE FROM approval_requests WHERE approval_id = 'approval-2'",
            "request created APPROVED": "INSERT INTO approval_requests (approval_id, request_id, authorization_id,"
            " nonce, run_id, run_attempt, approver_id, statement_json, statement_sha256, state, created_at_ms)"
            " VALUES ('a', 'r', 'z', 'n', '1', 1, 'p', x'00', '" + "0" * 64 + "', 'APPROVED', 1)",
            "counter decreased": "UPDATE credentials SET sign_count = 2",
            "counter repeated": "UPDATE credentials SET sign_count = 4",
            "BE changed": "UPDATE credentials SET backup_eligible = 1",
            "credential deleted": "DELETE FROM credentials",
            "journal rewritten": "UPDATE journal SET event = 'REQUEST_CREATED'",
            "journal deleted": "DELETE FROM journal",
            "clock moved back": "UPDATE store_meta SET last_observed_ms = 1",
        }
        for name, sql in forbidden.items():
            with self.subTest(change=name), self.assertRaises(sqlite3.IntegrityError):
                self._write((sql, ()))
        self.store.revoke_credential(self.credential.credential_id)
        with self.assertRaises(sqlite3.IntegrityError):
            self._write(("UPDATE credentials SET state = 'ACTIVE', revoked_at_ms = NULL", ()))
        with self.assertRaises(sqlite3.IntegrityError):
            self._write((
                "UPDATE approval_requests SET state = 'APPROVED', closed_at_ms = NULL WHERE approval_id = 'approval-1'",
                (),
            ))


class TestRowsAreNeverReplaced(_StoreTestCase):
    def test_insert_or_replace_cannot_rewrite_existing_rows(self):
        # REPLACE deletes the conflicting row without firing DELETE triggers;
        # each permanent table refuses it with a BEFORE INSERT guard.
        statement = self._pending(1, self.credential)
        self.store.approve("approval-1", _response(statement, self.credential, sign_count=1))
        snapshot = {table: self._rows(f"SELECT * FROM {table} ORDER BY 1") for table in TestAccountSeparation.TABLES}
        forbidden = {
            "approval reset to PENDING": "INSERT OR REPLACE INTO approval_requests (approval_id, request_id,"
            " authorization_id, nonce, run_id, run_attempt, run_actor_id, approver_id, actor_principal_id,"
            " approver_principal_id, separation_evidence, statement_json, statement_sha256, state, created_at_ms)"
            " SELECT approval_id, request_id, authorization_id, nonce, run_id, run_attempt, run_actor_id,"
            " approver_id, actor_principal_id, approver_principal_id, separation_evidence, statement_json,"
            " statement_sha256, 'PENDING', created_at_ms FROM approval_requests WHERE approval_id = 'approval-1'",
            "request replaced through its nonce": "INSERT OR REPLACE INTO approval_requests (approval_id, request_id,"
            " authorization_id, nonce, run_id, run_attempt, run_actor_id, approver_id, actor_principal_id,"
            " approver_principal_id, separation_evidence, statement_json, statement_sha256, state, created_at_ms)"
            " SELECT 'approval-9', 'request-9', 'authorization-9', nonce, '9', 1, run_actor_id, approver_id,"
            " actor_principal_id, approver_principal_id, separation_evidence, statement_json, statement_sha256,"
            " 'PENDING', created_at_ms FROM approval_requests WHERE approval_id = 'approval-1'",
            "credential counter reset": "INSERT OR REPLACE INTO credentials SELECT credential_id, credential_data,"
            " approver_id, user_handle, backup_eligible, backup_state, 0, 'ACTIVE', NULL FROM credentials",
            "journal entry rewritten": "INSERT OR REPLACE INTO journal (sequence, at_ms, event, approval_id)"
            " VALUES (1, 1, 'REQUEST_CREATED', 'approval-x')",
            "observed clock reset": "INSERT OR REPLACE INTO store_meta (singleton, last_observed_ms) VALUES (1, 0)",
        }
        for name, sql in forbidden.items():
            with self.subTest(change=name), self.assertRaises(sqlite3.IntegrityError):
                self._write((sql, ()))
        self.assertEqual(
            {table: self._rows(f"SELECT * FROM {table} ORDER BY 1") for table in TestAccountSeparation.TABLES},
            snapshot,
        )

    def test_a_counter_signal_cannot_be_replaced_through_its_partial_unique_index(self):
        # journal_one_counter_signal keys COUNTER_SIGNAL on (approval_id,
        # credential_sha256): a REPLACE with a new sequence conflicts there only.
        statement = self._pending(1, self.credential, sign_count=5)
        response = _response(statement, self.credential, sign_count=5)
        with self.assertRaisesRegex(ApprovalRefusedError, "signal"):
            self.store.approve("approval-1", response)
        credential_sha256 = hashlib.sha256(self.credential.credential_id).hexdigest()
        journal = self._rows("SELECT * FROM journal ORDER BY sequence")
        self.assertEqual(
            [row[2:] for row in journal if row[2] == "COUNTER_SIGNAL"],
            [("COUNTER_SIGNAL", "approval-1", credential_sha256, 5, 5)],
        )
        columns = "at_ms, event, approval_id, credential_sha256, stored_sign_count, presented_sign_count"
        values = f"1, 'COUNTER_SIGNAL', 'approval-1', '{credential_sha256}', 0, 0"
        forbidden = {
            "new sequence": f"INSERT OR REPLACE INTO journal (sequence, {columns}) VALUES (1000, {values})",
            "sequence left to SQLite": f"REPLACE INTO journal ({columns}) VALUES ({values})",
        }
        for name, sql in forbidden.items():
            with self.subTest(change=name), self.assertRaises(sqlite3.IntegrityError):
                self._write((sql, ()))
        self.assertEqual(self._rows("SELECT * FROM journal ORDER BY sequence"), journal)

        # The store still records a repeated signal once, without a failure note.
        with self.assertRaisesRegex(ApprovalRefusedError, "signal") as context:
            self.store.approve("approval-1", response)
        self.assertEqual(getattr(context.exception, "__notes__", []), [])
        self.assertEqual(self._rows("SELECT * FROM journal ORDER BY sequence"), journal)

    def test_insert_or_replace_cannot_rewrite_rows_through_their_rowid(self):
        # Tables keyed on TEXT or BLOB keep a unique rowid: REPLACE with an
        # existing rowid and fresh keys would delete that row.
        statement = self._pending(1, self.credential)
        self.store.approve("approval-1", _response(statement, self.credential, sign_count=1))
        snapshot = {
            table: self._rows(f"SELECT rowid, * FROM {table} ORDER BY 1") for table in TestAccountSeparation.TABLES
        }
        forbidden = {
            "principal": "INSERT OR REPLACE INTO principals (rowid, principal_id, state)"
            " SELECT rowid, 'principal-new', 'ACTIVE' FROM principals WHERE principal_id = 'principal-other'",
            "approver": "INSERT OR REPLACE INTO approvers (rowid, approver_id, principal_id, state)"
            " SELECT rowid, 'approver-new', principal_id, 'ACTIVE' FROM approvers"
            " WHERE approver_id = 'approver-pseudonym-2'",
            "account": "INSERT OR REPLACE INTO github_accounts"
            " (rowid, account_id, principal_id, evidence, attested_at_ms, state)"
            " SELECT rowid, '99', principal_id, evidence, attested_at_ms, 'ACTIVE' FROM github_accounts",
            "credential": "INSERT OR REPLACE INTO credentials (rowid, credential_id, credential_data, approver_id,"
            " user_handle, backup_eligible, backup_state, sign_count, state) SELECT rowid, zeroblob(32),"
            " credential_data, approver_id, user_handle, backup_eligible, backup_state, 0, 'ACTIVE' FROM credentials",
            "approved request": "INSERT OR REPLACE INTO approval_requests (rowid, approval_id, request_id,"
            " authorization_id, nonce, run_id, run_attempt, run_actor_id, approver_id, actor_principal_id,"
            " approver_principal_id, separation_evidence, statement_json, statement_sha256, state, created_at_ms)"
            " SELECT rowid, 'approval-9', 'request-9', 'authorization-9', 'nonce-9', '9', 1, run_actor_id,"
            " approver_id, actor_principal_id, approver_principal_id, separation_evidence, statement_json,"
            " statement_sha256, 'PENDING', created_at_ms FROM approval_requests WHERE approval_id = 'approval-1'",
        }
        for name, sql in forbidden.items():
            with self.subTest(table=name), self.assertRaises(sqlite3.IntegrityError):
                self._write((sql, ()))
        self.assertEqual(
            {table: self._rows(f"SELECT rowid, * FROM {table} ORDER BY 1") for table in TestAccountSeparation.TABLES},
            snapshot,
        )

    def test_update_or_replace_cannot_move_rows_onto_another_rowid(self):
        # Moving a row onto an existing rowid deletes the row already there,
        # without DELETE triggers; each update is otherwise an allowed one.
        _seed_registry(self.db_path, accounts=(("13", OTHER_PRINCIPAL),))
        first = self._pending(1, self.credential)
        _seed_credential(self.db_path, self.other_credential)
        self._pending(2)
        self._pending(3)
        self.store.approve("approval-1", _response(first, self.credential, sign_count=1))
        snapshot = {
            table: self._rows(f"SELECT rowid, * FROM {table} ORDER BY 1") for table in TestAccountSeparation.TABLES
        }

        def onto(table, condition):
            return f"UPDATE OR REPLACE {table} SET rowid = (SELECT rowid FROM {table} WHERE {condition})"

        forbidden = {
            "principal": onto("principals", "principal_id = 'principal-dispatcher'")
            + " WHERE principal_id = 'principal-other'",
            "approver": onto("approvers", "approver_id = 'approver-pseudonym-1'")
            + " WHERE approver_id = 'approver-pseudonym-2'",
            "account": onto("github_accounts", "account_id = '12'") + " WHERE account_id = '13'",
            "credential": onto("credentials", f"credential_id = x'{self.credential.credential_id.hex()}'")
            + f" WHERE credential_id = x'{self.other_credential.credential_id.hex()}'",
            "pending request expired onto the APPROVED one": onto("approval_requests", "approval_id = 'approval-1'")
            + ", state = 'EXPIRED', closed_at_ms = 1 WHERE approval_id = 'approval-2'",
            "APPROVED request revoked onto a pending one": onto("approval_requests", "approval_id = 'approval-3'")
            + ", state = 'REVOKED', closed_at_ms = 1 WHERE approval_id = 'approval-1'",
        }
        for name, sql in forbidden.items():
            with self.subTest(change=name), self.assertRaises(sqlite3.IntegrityError):
                self._write((sql, ()))
        self.assertEqual(
            {table: self._rows(f"SELECT rowid, * FROM {table} ORDER BY 1") for table in TestAccountSeparation.TABLES},
            snapshot,
        )
        self.assertEqual(
            self._rows("SELECT approval_id, state FROM approval_requests ORDER BY approval_id"),
            [("approval-1", "APPROVED"), ("approval-2", "PENDING"), ("approval-3", "PENDING")],
        )


# ----------------------------------------------------------------------
# Clock
# ----------------------------------------------------------------------


class TestClock(_StoreTestCase):
    def test_a_clock_moving_backwards_is_refused_without_any_write(self):
        first = self._pending(1, self.credential)
        second = self._pending(2)
        self.clock.now = NOW + 5_000
        self.store.approve("approval-1", _response(first, self.credential, sign_count=1))
        journal = self._journal()
        self.clock.now = NOW + 4_999

        with self.assertRaisesRegex(ApprovalRefusedError, "backwards"):
            self.store.approve("approval-2", _response(second, self.credential, sign_count=2))
        with self.assertRaisesRegex(ApprovalRefusedError, "backwards"):
            self.store.create_request(_statement(3))

        self.assertEqual(self._state("approval-2"), "PENDING")
        self.assertEqual(self._journal(), journal)
        self.assertEqual(self._last_observed(), NOW + 5_000)

    def test_a_clock_moving_backwards_during_verification_is_refused(self):
        statement = self._pending(1, self.credential)
        self.store._clock = _SequenceClock(NOW, NOW - 1, NOW)
        with self.assertRaisesRegex(ApprovalRefusedError, "backwards|not yet valid"):
            self.store.approve("approval-1", _response(statement, self.credential))
        self.assertEqual(self._state("approval-1"), "PENDING")

    def test_invalid_or_unavailable_clocks_are_refused(self):
        def failing():
            raise OSError("synthetic clock failure")

        for clock in (lambda: True, lambda: float(NOW), lambda: 0, lambda: -1, lambda: str(NOW), failing):
            with self.subTest(clock=clock):
                self.store._clock = clock
                with self.assertRaisesRegex(ApprovalRefusedError, "clock"):
                    self.store.create_request(_statement())
        self.assertEqual(self._rows("SELECT count(*) FROM approval_requests"), [(0,)])


# ----------------------------------------------------------------------
# SQLite failures
# ----------------------------------------------------------------------


class TestSqliteFailures(_StoreTestCase):
    def test_busy_store_is_refused_after_the_bounded_timeout_without_change(self):
        statement = self._pending(1, self.credential)
        response = _response(statement, self.credential)
        blocker = sqlite3.connect(self.db_path, autocommit=True)
        try:
            blocker.execute("BEGIN IMMEDIATE")
            started = time.monotonic()
            with self.assertRaisesRegex(ApprovalStoreBusyError, "locked"):
                self.store.approve("approval-1", response)
            self.assertLess(time.monotonic() - started, 5)
            blocker.execute("ROLLBACK")
        finally:
            blocker.close()
        self.assertEqual(self._state("approval-1"), "PENDING")
        self.store.approve("approval-1", response)

    def test_journal_failure_rolls_back_the_whole_approval(self):
        statement = self._pending(1, self.credential)
        response = _response(statement, self.credential, sign_count=1)

        def failing_journal(*args, **kwargs):
            raise sqlite3.OperationalError("synthetic disk I/O error")

        with mock.patch.object(store_module, "_append_journal", failing_journal):
            with self.assertRaises(ApprovalStoreUnavailableError):
                self.store.approve("approval-1", response)

        self.assertEqual(self._state("approval-1"), "PENDING")
        self.assertEqual(self._credential_row(self.credential), (0, 0, "ACTIVE"))
        self.assertEqual(self._last_observed(), NOW)
        self.store.approve("approval-1", response)

    def test_read_only_database_is_refused_without_change(self):
        if os.name != "nt" and os.geteuid() == 0:
            self.skipTest("root ignores file permissions")
        statement = self._pending(1, self.credential)
        os.chmod(self.db_path, stat.S_IREAD)
        try:
            with self.assertRaises(ApprovalStoreError):
                self.store.approve("approval-1", _response(statement, self.credential))
        finally:
            # A refused open may leave -shm/-wal created with the read-only mode.
            for path in (self.db_path, Path(f"{self.db_path}-wal"), Path(f"{self.db_path}-shm")):
                if path.exists():
                    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        self.assertEqual(self._state("approval-1"), "PENDING")


# ----------------------------------------------------------------------
# Contention and hard stops
# ----------------------------------------------------------------------


class TestContention(_StoreTestCase):
    PROCESSES = 4
    THREADS = 8

    def _spawn(self, mode, approval_id, response):
        response_path = self.sandbox / f"response-{approval_id}.json"
        response_path.write_text(json.dumps(response), encoding="utf-8")
        return subprocess.Popen(
            [sys.executable, "-B", __file__, WORKER_FLAG, mode, str(self.db_path), str(NOW), approval_id,
             str(response_path), str(self.sandbox)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

    def test_only_one_process_wins_a_contended_approval(self):
        statement = self._pending(1, self.credential)
        response = _response(statement, self.credential, sign_count=1)
        workers = [self._spawn("contend", "approval-1", response) for _ in range(self.PROCESSES)]
        try:
            _wait_for(lambda: len(list(self.sandbox.glob("ready-*"))) == self.PROCESSES, "ready workers")
            (self.sandbox / "go").write_text("1", encoding="utf-8")
            outputs = [worker.communicate(timeout=120) for worker in workers]
        finally:
            for worker in workers:
                if worker.poll() is None:
                    worker.kill()
                    worker.communicate(timeout=60)
        outcomes = []
        for stdout, stderr in outputs:
            self.assertTrue(stdout.strip(), stderr[-800:])
            outcomes.append(json.loads(stdout.strip().splitlines()[-1])["outcome"])
        self.assertEqual(outcomes.count("APPROVED"), 1, outcomes)
        for outcome in outcomes:
            self.assertTrue(outcome in ("APPROVED", "BUSY") or "not pending" in outcome, outcome)
        self.assertEqual(self._state("approval-1"), "APPROVED")
        self.assertEqual([row[0] for row in self._journal()].count("REQUEST_APPROVED"), 1)

    def test_only_one_thread_wins_a_contended_approval(self):
        statement = self._pending(1, self.credential)
        response = _response(statement, self.credential, sign_count=1)
        barrier = threading.Barrier(self.THREADS)
        outcomes, guard = [], threading.Lock()

        def contender():
            store = ApprovalStore(self.db_path, self.clock, busy_timeout_seconds=10.0)
            barrier.wait(timeout=60)
            try:
                store.approve("approval-1", response)
                outcome = "APPROVED"
            except ApprovalStoreError as error:
                outcome = f"{type(error).__name__}: {error}"
            with guard:
                outcomes.append(outcome)

        threads = [threading.Thread(target=contender) for _ in range(self.THREADS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        self.assertEqual(len(outcomes), self.THREADS)
        self.assertEqual(outcomes.count("APPROVED"), 1, outcomes)
        # BEGIN IMMEDIATE makes every loser wait for the winner, then read
        # APPROVED; a deferred BEGIN would fail them with SQLITE_BUSY_SNAPSHOT.
        not_pending = "ApprovalRefusedError: approval request is not pending"
        for outcome in outcomes:
            self.assertTrue(outcome == "APPROVED" or outcome.startswith(not_pending), outcome)
        self.assertEqual([row[0] for row in self._journal()].count("REQUEST_APPROVED"), 1)

    def _stop(self, mode, approval_id, response):
        worker = self._spawn(mode, approval_id, response)
        try:
            deadline = time.monotonic() + 120
            while not (self.sandbox / "stopped").exists():
                if worker.poll() is not None:
                    self.fail(f"worker exited before its stop point: {worker.communicate()[1][-800:]}")
                self.assertLess(time.monotonic(), deadline, "worker never reached its stop point")
                time.sleep(0.01)
        finally:
            worker.kill()
            worker.communicate(timeout=60)

    def _integrity(self):
        return self._rows("PRAGMA integrity_check")

    def test_stop_before_commit_leaves_the_request_pending_and_approvable(self):
        statement = self._pending(1, self.credential, sign_count=4)
        response = _response(statement, self.credential, sign_count=5)

        self._stop("stop_before_commit", "approval-1", response)

        store = ApprovalStore(self.db_path, self.clock)
        self.assertEqual(self._integrity(), [("ok",)])
        self.assertEqual(self._state("approval-1"), "PENDING")
        self.assertEqual(self._credential_row(self.credential), (4, 0, "ACTIVE"))
        self.assertNotIn("REQUEST_APPROVED", [row[0] for row in self._journal()])
        # Never committed, so this is the first approval, not a replay.
        store.approve("approval-1", response)
        self.assertEqual(self._state("approval-1"), "APPROVED")

    def test_stop_after_commit_keeps_the_approval_and_refuses_a_replay(self):
        statement = self._pending(1, self.credential, sign_count=4)
        response = _response(statement, self.credential, sign_count=5)

        self._stop("stop_after_commit", "approval-1", response)

        store = ApprovalStore(self.db_path, self.clock)
        self.assertEqual(self._integrity(), [("ok",)])
        self.assertEqual(self._state("approval-1"), "APPROVED")
        self.assertEqual(self._credential_row(self.credential), (5, 0, "ACTIVE"))
        with self.assertRaisesRegex(ApprovalRefusedError, "not pending"):
            store.approve("approval-1", response)


# ----------------------------------------------------------------------
# Administrator-attested account separation (schema version 2)
# ----------------------------------------------------------------------


class TestAccountSeparation(_StoreTestCase):
    TABLES = ("store_meta", "principals", "approvers", "github_accounts", "credentials", "approval_requests", "journal")

    def _snapshot(self, db_path=None):
        return {table: self._rows(f"SELECT * FROM {table} ORDER BY 1", db_path=db_path) for table in self.TABLES}

    def assertSeparationRefused(self, call):
        with self.assertRaises(ApprovalRefusedError) as context:
            call()
        self.assertEqual(str(context.exception), SEPARATION_REFUSED)
        self.assertIsNone(context.exception.__cause__)
        return context.exception

    def test_creation_persists_the_signed_actor_and_distinct_principals(self):
        self._pending(1)

        self.assertEqual(
            self._rows(
                "SELECT run_actor_id, approver_id, actor_principal_id, approver_principal_id, separation_evidence"
                " FROM approval_requests"
            ),
            [(ACTOR_ID, APPROVER_ID, ACTOR_PRINCIPAL, APPROVER_PRINCIPAL, "ADMIN_ATTESTED_ACCOUNT_SEPARATION")],
        )
        stored = json.loads(self._rows("SELECT statement_json FROM approval_requests")[0][0])
        self.assertEqual(stored["run_actor_id"], ACTOR_ID)
        self.assertNotIn("actor", stored)
        self.assertEqual(self._journal(), [("REQUEST_CREATED", "approval-1", None, None, None)])

    def test_unknown_or_revoked_accounts_approvers_and_principals_refuse_creation_without_any_write(self):
        _seed_registry(
            self.db_path,
            principals=("principal-revoked-actor", "principal-revoked-approver"),
            approvers=(("approver-revoked", APPROVER_PRINCIPAL), ("approver-of-revoked", "principal-revoked-approver")),
            accounts=(("21", ACTOR_PRINCIPAL), ("22", "principal-revoked-actor")),
        )
        _revoke(self.db_path, "github_accounts", "account_id", "21")
        _revoke(self.db_path, "approvers", "approver_id", "approver-revoked")
        _revoke(self.db_path, "principals", "principal_id", "principal-revoked-actor")
        _revoke(self.db_path, "principals", "principal_id", "principal-revoked-approver")
        cases = {
            "unknown account (bot, app or undeclared)": {"run_actor_id": "41898282"},
            "revoked account": {"run_actor_id": "21"},
            "account of a revoked principal": {"run_actor_id": "22"},
            "unknown approver": {"approver_id": "approver-pseudonym-9"},
            "revoked approver": {"approver_id": "approver-revoked"},
            "approver of a revoked principal": {"approver_id": "approver-of-revoked"},
        }
        before = self._snapshot()
        for name, overrides in cases.items():
            with self.subTest(case=name):
                self.assertSeparationRefused(lambda: self.store.create_request(_statement(1, **overrides)))
                self.assertEqual(self._snapshot(), before)

    def test_the_same_principal_is_refused_including_through_a_second_account(self):
        _seed_registry(
            self.db_path, approvers=(("approver-self", ACTOR_PRINCIPAL),), accounts=(("13", APPROVER_PRINCIPAL),)
        )
        before = self._snapshot()
        cases = {
            "approver of the run account's principal": {"approver_id": "approver-self"},
            "second account of the approver's principal": {"run_actor_id": "13"},
        }
        for name, overrides in cases.items():
            with self.subTest(case=name):
                self.assertSeparationRefused(lambda: self.store.create_request(_statement(1, **overrides)))
                self.assertEqual(self._snapshot(), before)

    def test_an_inconsistent_or_unavailable_registry_refuses_without_writes_or_leaks(self):
        def unavailable(registry, account_id):
            raise sqlite3.OperationalError(f"disk I/O error reading {account_id} of {ACTOR_PRINCIPAL}")

        def another_account(registry, account_id):
            return AccountBinding("99", ACTOR_PRINCIPAL, revoked=False)

        def another_principal(registry, account_id):
            return AccountBinding(account_id, "principal-unknown", revoked=False)

        before = self._snapshot()
        cases = {"unavailable": unavailable, "another account": another_account, "unknown principal": another_principal}
        for name, replacement in cases.items():
            with self.subTest(case=name), mock.patch.object(store_module._RegistryRows, "resolve_account", replacement):
                error = self.assertSeparationRefused(lambda: self.store.create_request(_statement(1)))
                self.assertTrue(error.__suppress_context__)
                self.assertEqual(self._snapshot(), before)

    def test_a_revocation_between_creation_and_approval_is_refused_and_keeps_the_request_pending(self):
        cases = {
            "run account": ("github_accounts", "account_id", ACTOR_ID),
            "approver": ("approvers", "approver_id", APPROVER_ID),
            "run account principal": ("principals", "principal_id", ACTOR_PRINCIPAL),
            "approver principal": ("principals", "principal_id", APPROVER_PRINCIPAL),
        }
        for name, (table, column, key) in cases.items():
            with self.subTest(revoked=name):
                db_path = self.sandbox / f"revoked-{table}-{key}.sqlite3"
                store = ApprovalStore.initialize(db_path, self.clock, busy_timeout_seconds=FAST_BUSY_TIMEOUT)
                _seed_default_registry(db_path)
                _seed_credential(db_path, self.credential)
                statement = _statement(1)
                store.create_request(statement)
                _revoke(db_path, table, column, key)
                before = self._snapshot(db_path)

                self.assertSeparationRefused(lambda: store.approve("approval-1", _response(statement, self.credential)))

                self.assertEqual(self._snapshot(db_path), before)
                self.assertEqual(
                    self._rows("SELECT state FROM approval_requests", db_path=db_path), [("PENDING",)]
                )

    def test_a_revocation_after_approval_does_not_cascade_in_this_increment(self):
        statement = self._pending(1, self.credential)
        self.store.approve("approval-1", _response(statement, self.credential))
        _revoke(self.db_path, "github_accounts", "account_id", ACTOR_ID)

        # Documented limit: a future consumption must re-validate the separation.
        self.assertEqual(self._state("approval-1"), "APPROVED")
        self.assertSeparationRefused(lambda: self.store.create_request(_statement(2)))

    def test_persisted_separation_and_actor_must_match_the_statement_and_current_registry(self):
        _seed_registry(self.db_path, accounts=(("14", ACTOR_PRINCIPAL),))
        statement = self._pending(1, self.credential)
        response = _response(statement, self.credential)
        cases = {
            "actor principal": ({"actor_principal_id": OTHER_PRINCIPAL}, "account separation record"),
            "approver principal": ({"approver_principal_id": OTHER_PRINCIPAL}, "account separation record"),
            "run account": ({"run_actor_id": "14"}, "statement failed its integrity check"),
        }
        original = self._rows(
            "SELECT actor_principal_id, approver_principal_id, run_actor_id FROM approval_requests"
        )[0]
        for name, (columns, reason) in cases.items():
            with self.subTest(case=name):
                self._tamper("approval-1", **columns)
                try:
                    with self.assertRaisesRegex(ApprovalStoreUnavailableError, reason):
                        self.store.approve("approval-1", response)
                    self.assertEqual(self._state("approval-1"), "PENDING")
                finally:
                    self._tamper(
                        "approval-1",
                        actor_principal_id=original[0],
                        approver_principal_id=original[1],
                        run_actor_id=original[2],
                    )
        self.store.approve("approval-1", response)

    def test_registry_rows_are_permanent_immutable_never_reactivated_nor_replaced(self):
        _seed_registry(self.db_path, accounts=(("21", OTHER_PRINCIPAL),))
        _revoke(self.db_path, "github_accounts", "account_id", "21")
        _revoke(self.db_path, "approvers", "approver_id", OTHER_APPROVER_ID)
        _revoke(self.db_path, "principals", "principal_id", OTHER_PRINCIPAL)
        account = (
            "INSERT INTO github_accounts (account_id, principal_id, evidence, attested_at_ms, state) VALUES "
        )
        forbidden = {
            "principal deleted": "DELETE FROM principals WHERE principal_id = 'principal-dispatcher'",
            "principal renamed": "UPDATE principals SET principal_id = 'principal-x'"
            " WHERE principal_id = 'principal-dispatcher'",
            "principal reactivated": "UPDATE principals SET state = 'ACTIVE', revoked_at_ms = NULL"
            " WHERE principal_id = 'principal-other'",
            "principal replaced": "INSERT OR REPLACE INTO principals (principal_id, state)"
            " VALUES ('principal-other', 'ACTIVE')",
            "malformed principal ID": "INSERT INTO principals (principal_id, state) VALUES (' principal', 'ACTIVE')",
            "approver deleted": "DELETE FROM approvers WHERE approver_id = 'approver-pseudonym-1'",
            "approver rebound": "UPDATE approvers SET principal_id = 'principal-dispatcher'"
            " WHERE approver_id = 'approver-pseudonym-1'",
            "approver reactivated": "UPDATE approvers SET state = 'ACTIVE', revoked_at_ms = NULL"
            " WHERE approver_id = 'approver-pseudonym-2'",
            "approver replaced": "REPLACE INTO approvers (approver_id, principal_id, state)"
            " VALUES ('approver-pseudonym-1', 'principal-dispatcher', 'ACTIVE')",
            "account deleted": "DELETE FROM github_accounts WHERE account_id = '12'",
            "account rebound": "UPDATE github_accounts SET principal_id = 'principal-approver' WHERE account_id = '12'",
            "account evidence changed": "UPDATE github_accounts SET evidence = 'SELF_DECLARED' WHERE account_id = '12'",
            "account reactivated": "UPDATE github_accounts SET state = 'ACTIVE', revoked_at_ms = NULL"
            " WHERE account_id = '21'",
            "revoked account re-registered elsewhere": account
            + "('21', 'principal-approver', 'ADMIN_ATTESTED', 1, 'ACTIVE')",
            "revoked account replaced elsewhere": "INSERT OR REPLACE INTO github_accounts"
            " (account_id, principal_id, evidence, attested_at_ms, state)"
            " VALUES ('21', 'principal-approver', 'ADMIN_ATTESTED', 1, 'ACTIVE')",
            "active account replaced": "REPLACE INTO github_accounts"
            " (account_id, principal_id, evidence, attested_at_ms, state)"
            " VALUES ('12', 'principal-approver', 'ADMIN_ATTESTED', 1, 'ACTIVE')",
            "zero-padded account ID": account + "('012', 'principal-dispatcher', 'ADMIN_ATTESTED', 1, 'ACTIVE')",
            "login used as account ID": account + "('octocat', 'principal-dispatcher', 'ADMIN_ATTESTED', 1, 'ACTIVE')",
            "unattested account": account + "('31', 'principal-dispatcher', 'SELF_DECLARED', 1, 'ACTIVE')",
        }
        for name, sql in forbidden.items():
            with self.subTest(change=name), self.assertRaises(sqlite3.IntegrityError):
                self._write((sql, ()))
        self.assertEqual(
            self._rows("SELECT account_id, principal_id, state FROM github_accounts ORDER BY account_id"),
            [(ACTOR_ID, ACTOR_PRINCIPAL, "ACTIVE"), ("21", OTHER_PRINCIPAL, "REVOKED")],
        )

    def test_foreign_keys_bind_credentials_requests_and_registry_rows(self):
        stranger = _new_credential("synthetic-credential-stranger")
        request = (
            "INSERT INTO approval_requests (approval_id, request_id, authorization_id, nonce, run_id, run_attempt,"
            " run_actor_id, approver_id, actor_principal_id, approver_principal_id, separation_evidence,"
            " statement_json, statement_sha256, state, created_at_ms) VALUES ('a-x', 'r-x', 'z-x', 'n-x', '1', 1,"
            " ?, ?, 'principal-dispatcher', 'principal-approver', 'ADMIN_ATTESTED_ACCOUNT_SEPARATION', x'00', ?,"
            " 'PENDING', 1)"
        )
        cases = {
            "credential of an unknown approver": (
                "INSERT INTO credentials (credential_id, credential_data, approver_id, user_handle, backup_eligible,"
                " backup_state, sign_count, state) VALUES (?, ?, 'approver-unknown', ?, 0, 0, 0, 'ACTIVE')",
                (stranger.credential_id, bytes(stranger.data), USER_HANDLE),
            ),
            "request for an unknown approver": (request, (ACTOR_ID, "approver-unknown", "0" * 64)),
            "request from an unregistered account": (request, ("99", APPROVER_ID, "0" * 64)),
            "approver of an unknown principal": (
                "INSERT INTO approvers (approver_id, principal_id, state)"
                " VALUES ('approver-x', 'principal-unknown', 'ACTIVE')",
                (),
            ),
            "account of an unknown principal": (
                "INSERT INTO github_accounts (account_id, principal_id, evidence, attested_at_ms, state)"
                " VALUES ('31', 'principal-unknown', 'ADMIN_ATTESTED', 1, 'ACTIVE')",
                (),
            ),
        }
        for name, (sql, params) in cases.items():
            with self.subTest(case=name):
                connection = sqlite3.connect(self.db_path, autocommit=True)
                try:
                    connection.execute("PRAGMA foreign_keys = ON")
                    with self.assertRaises(sqlite3.IntegrityError):
                        connection.execute(sql, params)
                finally:
                    connection.close()

        # Written with foreign keys off, a dangling binding makes every open fail closed.
        self._write(cases["account of an unknown principal"])
        with self.assertRaisesRegex(ApprovalStoreUnavailableError, "foreign key"):
            ApprovalStore(self.db_path, self.clock)


# ----------------------------------------------------------------------
# Scope boundaries
# ----------------------------------------------------------------------


class TestScopeBoundaries(_StoreTestCase):
    SOURCE = Path(store_module.__file__).read_text(encoding="utf-8")

    def test_the_store_exposes_only_the_operations_of_this_step(self):
        public = {name for name in dir(ApprovalStore) if not name.startswith("_")}
        self.assertEqual(
            public, {"initialize", "create_request", "approve", "expire_request", "revoke_credential"}
        )

    def test_the_store_module_has_no_enrollment_or_registry_administration_path(self):
        registry_tables = r"(credentials|principals|approvers|github_accounts)\b"
        self.assertIsNone(re.search(r"(?i)insert\s+(or\s+\w+\s+)?into\s+" + registry_tables, self.SOURCE))
        administration = r"(?i)(update|delete\s+from)\s+(principals|approvers|github_accounts)\b"
        self.assertIsNone(re.search(administration, self.SOURCE))
        names = {
            node.name
            for node in ast.walk(ast.parse(self.SOURCE))
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        }
        administration_names = r"(?i)enrol|register|add_|insert|attest|revoke_(account|approver|principal)"
        for name in names:
            self.assertIsNone(re.search(administration_names, name), name)

    def test_the_signed_account_id_is_persisted_and_checked_without_any_login_while_d5_stays_unresolved(self):
        tables = [name for (name,) in self._rows("SELECT name FROM sqlite_schema WHERE type = 'table'")]
        columns = {table: [row[1] for row in self._rows(f"PRAGMA table_info({table})")] for table in tables}
        self.assertIn("run_actor_id", columns["approval_requests"])
        self.assertIn("account_id", columns["github_accounts"])
        for table, names in columns.items():
            for name in names:
                with self.subTest(table=table, column=name):
                    self.assertNotEqual(name, "actor")
                    self.assertNotIn("login", name)
        schema = " ".join(sql for (sql,) in self._rows("SELECT sql FROM sqlite_schema WHERE sql IS NOT NULL"))
        self.assertNotIn("consume", schema.lower())

        self._pending(1)
        self.assertEqual(self._rows("SELECT run_actor_id FROM approval_requests"), [(ACTOR_ID,)])
        with self.assertRaisesRegex(ApprovalRefusedError, SEPARATION_REFUSED):
            self.store.create_request(_statement(2, run_actor_id="41898282"))

        doc = " ".join((store_module.__doc__ or "").split())
        self.assertIn("G1 D-5 is unresolved", doc)
        self.assertIn("does not prove that two different people are involved", doc)

    def test_the_journal_never_holds_raw_credential_ids_or_assertion_material(self):
        statement = self._pending(1, self.credential, sign_count=2)
        second = self._pending(2)
        response = _response(statement, self.credential, sign_count=3)
        self.store.approve("approval-1", response)
        with self.assertRaises(ApprovalRefusedError):
            self.store.approve("approval-2", _response(second, self.credential, sign_count=3))
        self.store.revoke_credential(self.credential.credential_id)

        stored = json.dumps(self._rows("SELECT * FROM journal"))
        for secret_like in (
            self.credential.credential_id.hex(),
            response["rawId"],
            response["response"]["signature"],
            response["response"]["clientDataJSON"],
            response["response"]["authenticatorData"],
            ACTOR_PRINCIPAL,
            APPROVER_PRINCIPAL,
        ):
            self.assertNotIn(secret_like, stored)
        # No journal column can hold an account or principal ID.
        self.assertEqual(
            [row[1] for row in self._rows("PRAGMA table_info(journal)")],
            [
                "sequence", "at_ms", "event", "approval_id",
                "credential_sha256", "stored_sign_count", "presented_sign_count",
            ],
        )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == WORKER_FLAG:
        _worker(*sys.argv[2:])
    else:
        unittest.main()
