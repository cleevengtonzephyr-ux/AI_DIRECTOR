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
USER_HANDLE = b"synthetic-approver-handle-1"
FAST_BUSY_TIMEOUT = 0.2


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

    def _rows(self, sql, params=()):
        connection = sqlite3.connect(self.db_path)
        try:
            return connection.execute(sql, params).fetchall()
        finally:
            connection.close()

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
    def test_initialize_creates_a_private_wal_schema_version_1(self):
        connection = sqlite3.connect(self.db_path)
        try:
            pragmas = {
                name: connection.execute(f"PRAGMA {name}").fetchone()[0]
                for name in ("application_id", "user_version", "journal_mode")
            }
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")}
        finally:
            connection.close()
        self.assertEqual(
            pragmas, {"application_id": APPLICATION_ID, "user_version": SCHEMA_VERSION, "journal_mode": "wal"}
        )
        self.assertEqual(tables, {"store_meta", "credentials", "approval_requests", "journal"})
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
            "user_version": ["PRAGMA user_version = 2"],
            "journal_mode": ["PRAGMA journal_mode = DELETE"],
            "objects": ["DROP TRIGGER approval_requests_transitions"],
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
# Scope boundaries
# ----------------------------------------------------------------------


class TestScopeBoundaries(_StoreTestCase):
    SOURCE = Path(store_module.__file__).read_text(encoding="utf-8")

    def test_the_store_exposes_only_the_operations_of_this_step(self):
        public = {name for name in dir(ApprovalStore) if not name.startswith("_")}
        self.assertEqual(
            public, {"initialize", "create_request", "approve", "expire_request", "revoke_credential"}
        )

    def test_the_store_module_has_no_credential_enrollment_path(self):
        self.assertIsNone(re.search(r"(?i)insert\s+(or\s+\w+\s+)?into\s+credentials", self.SOURCE))
        names = {
            node.name
            for node in ast.walk(ast.parse(self.SOURCE))
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        }
        for name in names:
            self.assertIsNone(re.search(r"(?i)enrol|regist|add_cred|insert", name), name)

    def test_no_github_actor_is_recorded_while_d5_is_unresolved(self):
        schema = " ".join(sql for (sql,) in self._rows("SELECT sql FROM sqlite_schema WHERE sql IS NOT NULL"))
        self.assertNotIn("actor", schema.lower())
        self.assertNotIn("consume", schema.lower())

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
        ):
            self.assertNotIn(secret_like, stored)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == WORKER_FLAG:
        _worker(*sys.argv[2:])
    else:
        unittest.main()
