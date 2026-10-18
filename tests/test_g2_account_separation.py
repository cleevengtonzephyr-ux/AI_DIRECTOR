"""Synthetic tests for the administrator-attested account separation check."""

import ast
import inspect
import sys
import unittest
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPROVAL_SERVICE_ROOT = PROJECT_ROOT / "approval_service"
if str(APPROVAL_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(APPROVAL_SERVICE_ROOT))

import approval_service.account_separation as separation_module
from approval_service.account_separation import (
    AccountBinding,
    AccountSeparationChecker,
    AccountSeparationError,
    AdminAttestedAccountSeparation,
    ApproverBinding,
    PrincipalRecord,
)

ACTOR_ID = "12"
APPROVER_ID = "approver-pseudonym-1"
ACTOR_PRINCIPAL = "principal-dispatcher"
APPROVER_PRINCIPAL = "principal-approver"


class _Registry:
    """In-memory closed-world registry; `overrides` replace a lookup's outcome."""

    def __init__(self, accounts=(), approvers=(), principals=(), **overrides):
        self.accounts = {entry.account_id: entry for entry in accounts}
        self.approvers = {entry.approver_id: entry for entry in approvers}
        self.principals = {entry.principal_id: entry for entry in principals}
        self.overrides = overrides
        self.calls = []

    def _answer(self, method, table, key):
        self.calls.append((method, key))
        override = self.overrides.get(method)
        if override is not None:
            if isinstance(override, BaseException):
                raise override
            return override(key)
        try:
            return table[key]
        except KeyError:
            raise KeyError("synthetic entry is not registered") from None

    def resolve_account(self, account_id):
        return self._answer("resolve_account", self.accounts, account_id)

    def resolve_approver(self, approver_id):
        return self._answer("resolve_approver", self.approvers, approver_id)

    def resolve_principal(self, principal_id):
        return self._answer("resolve_principal", self.principals, principal_id)


def _registry(**overrides):
    return _Registry(
        accounts=(
            AccountBinding(ACTOR_ID, ACTOR_PRINCIPAL, revoked=False),
            AccountBinding("13", APPROVER_PRINCIPAL, revoked=False),
            AccountBinding("14", APPROVER_PRINCIPAL, revoked=False),
            AccountBinding("15", "principal-departed", revoked=False),
            AccountBinding("16", ACTOR_PRINCIPAL, revoked=True),
        ),
        approvers=(
            ApproverBinding(APPROVER_ID, APPROVER_PRINCIPAL, revoked=False),
            ApproverBinding("approver-pseudonym-2", ACTOR_PRINCIPAL, revoked=False),
            ApproverBinding("approver-pseudonym-3", "principal-other", revoked=True),
            ApproverBinding("approver-pseudonym-4", "principal-departed", revoked=False),
        ),
        principals=(
            PrincipalRecord(ACTOR_PRINCIPAL, revoked=False),
            PrincipalRecord(APPROVER_PRINCIPAL, revoked=False),
            PrincipalRecord("principal-other", revoked=False),
            PrincipalRecord("principal-departed", revoked=True),
        ),
        **overrides,
    )


class AccountSeparationTests(unittest.TestCase):
    def _check(self, actor_id=ACTOR_ID, approver_id=APPROVER_ID, registry=None):
        return AccountSeparationChecker(_registry() if registry is None else registry).check(actor_id, approver_id)

    def assertRefused(self, message, **kwargs):
        with self.assertRaisesRegex(AccountSeparationError, message) as context:
            self._check(**kwargs)
        return context.exception

    def test_distinct_active_principals_give_an_admin_attested_separation(self):
        registry = _registry()

        result = AccountSeparationChecker(registry).check(ACTOR_ID, APPROVER_ID)

        self.assertIsInstance(result, AdminAttestedAccountSeparation)
        self.assertEqual(
            (result.actor_principal_id, result.approver_principal_id), (ACTOR_PRINCIPAL, APPROVER_PRINCIPAL)
        )
        self.assertEqual(result.evidence, "ADMIN_ATTESTED_ACCOUNT_SEPARATION")
        self.assertEqual(
            registry.calls,
            [
                ("resolve_account", ACTOR_ID),
                ("resolve_approver", APPROVER_ID),
                ("resolve_principal", ACTOR_PRINCIPAL),
                ("resolve_principal", APPROVER_PRINCIPAL),
            ],
        )
        with self.assertRaises(FrozenInstanceError):
            result.evidence = "D5_RESOLVED"

    def test_the_result_never_claims_more_than_an_administrator_attestation(self):
        self.assertEqual(
            [field.name for field in fields(AdminAttestedAccountSeparation)],
            ["actor_principal_id", "approver_principal_id", "evidence"],
        )
        self.assertNotRegex(AdminAttestedAccountSeparation.__name__, "(?i)d5|resolved|human|person")
        doc = " ".join(inspect.getdoc(AdminAttestedAccountSeparation).split())
        self.assertIn("does not prove that two different people are involved", doc)
        self.assertIn("does not resolve G1 D-5", doc)
        for invalid in (
            {"evidence": "D5_RESOLVED"},
            {"approver_principal_id": ACTOR_PRINCIPAL},
            {"actor_principal_id": ""},
        ):
            values = {"actor_principal_id": ACTOR_PRINCIPAL, "approver_principal_id": APPROVER_PRINCIPAL, **invalid}
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                AdminAttestedAccountSeparation(**values)

    def test_missing_or_malformed_actor_ids_are_refused_before_any_lookup(self):
        fullwidth_twelve = chr(0xFF11) + chr(0xFF12)
        invalid = (None, "", "0", "012", "-12", "+12", " 12", "12 ", "12\n", "12a", fullwidth_twelve, 12, True, "octocat")
        for actor_id in invalid:
            registry = _registry()
            with self.subTest(actor_id=actor_id):
                with self.assertRaisesRegex(AccountSeparationError, "run actor ID is missing or malformed"):
                    AccountSeparationChecker(registry).check(actor_id, APPROVER_ID)
                self.assertEqual(registry.calls, [])

    def test_missing_or_malformed_approver_ids_are_refused_before_any_lookup(self):
        for approver_id in (None, "", " approver", "approver 1", "-approver", "a" * 129, 1):
            registry = _registry()
            with self.subTest(approver_id=approver_id):
                with self.assertRaisesRegex(AccountSeparationError, "approver ID is missing or malformed"):
                    AccountSeparationChecker(registry).check(ACTOR_ID, approver_id)
                self.assertEqual(registry.calls, [])

    def test_unknown_accounts_and_approvers_are_refused_in_a_closed_world(self):
        # An unregistered ID covers bots, apps and any undeclared second account.
        self.assertRefused("run account is not registered", actor_id="41898282")
        self.assertRefused("approver is not registered", approver_id="approver-pseudonym-9")

    def test_revoked_accounts_approvers_and_principals_are_refused(self):
        self.assertRefused("run account is revoked", actor_id="16")
        self.assertRefused("approver is revoked", approver_id="approver-pseudonym-3")
        self.assertRefused("run account principal is revoked", actor_id="15")
        self.assertRefused("approver principal is revoked", approver_id="approver-pseudonym-4")

    def test_actor_and_approver_of_the_same_principal_are_refused(self):
        # Direct self-approval, then a second account of the approver's principal.
        self.assertRefused("same principal", approver_id="approver-pseudonym-2")
        self.assertRefused("same principal", actor_id="13")
        self.assertRefused("same principal", actor_id="14")

    def test_inconsistent_registry_entries_are_refused(self):
        cases = {
            "account for another ID": {
                "resolve_account": lambda key: AccountBinding("99", ACTOR_PRINCIPAL, revoked=False)
            },
            "approver for another ID": {
                "resolve_approver": lambda key: ApproverBinding("approver-other", APPROVER_PRINCIPAL, revoked=False)
            },
            "principal for another ID": {
                "resolve_principal": lambda key: PrincipalRecord("principal-x", revoked=False)
            },
            "binding to an unknown principal": {"resolve_principal": KeyError("synthetic unknown principal")},
            "account of the wrong type": {
                "resolve_account": lambda key: {"account_id": key, "principal_id": ACTOR_PRINCIPAL}
            },
            "approver of the wrong type": {"resolve_approver": lambda key: None},
            "principal of the wrong type": {
                "resolve_principal": lambda key: ApproverBinding(APPROVER_ID, key, revoked=False)
            },
        }
        for name, overrides in cases.items():
            with self.subTest(case=name):
                self.assertRefused("registry entry is inconsistent", registry=_registry(**overrides))

    def test_registry_errors_fail_closed_without_chaining(self):
        failures = (
            RuntimeError("synthetic failure 12"),
            OSError("synthetic I/O"),
            ValueError("bad row"),
            TypeError("x"),
        )
        for method in ("resolve_account", "resolve_approver", "resolve_principal"):
            for failure in failures:
                with self.subTest(method=method, failure=type(failure).__name__):
                    error = self.assertRefused("registry could not be read", registry=_registry(**{method: failure}))
                    self.assertIsNone(error.__cause__)
                    self.assertTrue(error.__suppress_context__)

    def test_refusals_never_disclose_account_approver_or_principal_ids(self):
        refusals = (
            {"actor_id": "41898282"},
            {"actor_id": "16"},
            {"actor_id": "13"},
            {"approver_id": "approver-pseudonym-9"},
            {"approver_id": "approver-pseudonym-2"},
            {"registry": _registry(resolve_principal=RuntimeError(f"row {APPROVER_PRINCIPAL} unreadable"))},
        )
        identifiers = (ACTOR_ID, "13", "16", "41898282", APPROVER_ID, "pseudonym", ACTOR_PRINCIPAL, APPROVER_PRINCIPAL)
        for kwargs in refusals:
            with self.subTest(kwargs=kwargs):
                message = str(self.assertRefused(".", **kwargs))
                for identifier in identifiers:
                    self.assertNotIn(identifier, message)

    def test_registry_entries_validate_their_own_fields(self):
        invalid = (
            lambda: AccountBinding("octocat", ACTOR_PRINCIPAL, revoked=False),
            lambda: AccountBinding("012", ACTOR_PRINCIPAL, revoked=False),
            lambda: AccountBinding(ACTOR_ID, "", revoked=False),
            lambda: AccountBinding(ACTOR_ID, ACTOR_PRINCIPAL, revoked=0),
            lambda: ApproverBinding(" approver", APPROVER_PRINCIPAL, revoked=False),
            lambda: ApproverBinding(APPROVER_ID, APPROVER_PRINCIPAL, revoked=None),
            lambda: PrincipalRecord("principal x", revoked=False),
            lambda: PrincipalRecord(ACTOR_PRINCIPAL, revoked="no"),
        )
        for factory in invalid:
            with self.subTest(factory=factory), self.assertRaises(ValueError):
                factory()
        with self.assertRaises(TypeError):
            AccountBinding(ACTOR_ID, ACTOR_PRINCIPAL)

    def test_checker_requires_a_complete_registry(self):
        class _Partial:
            def resolve_account(self, account_id):
                raise KeyError(account_id)

            def resolve_approver(self, approver_id):
                raise KeyError(approver_id)

        for registry in (None, object(), _Partial()):
            with self.subTest(registry=type(registry).__name__), self.assertRaises(TypeError):
                AccountSeparationChecker(registry)


class AccountSeparationBoundaryTests(unittest.TestCase):
    SOURCE = Path(separation_module.__file__).read_text(encoding="utf-8")

    def test_only_the_actor_id_takes_part_in_the_decision(self):
        parameters = list(inspect.signature(AccountSeparationChecker.check).parameters)
        self.assertEqual(parameters, ["self", "actor_id", "approver_id"])
        tree = ast.parse(self.SOURCE)
        names = (
            {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
            | {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
            | {node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)}
        )
        self.assertNotIn("actor", names)
        # A login is refused even when an account with that "ID" could exist.
        registry = _registry()
        registry.accounts["octocat"] = registry.accounts[ACTOR_ID]
        with self.assertRaisesRegex(AccountSeparationError, "malformed"):
            AccountSeparationChecker(registry).check("octocat", APPROVER_ID)

    def test_module_stays_independent_of_storage_gate_agents_and_network(self):
        imported = set()
        for node in ast.walk(ast.parse(self.SOURCE)):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported, {"__future__", "re", "dataclasses", "typing"})


if __name__ == "__main__":
    unittest.main()
