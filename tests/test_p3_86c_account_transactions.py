"""
Tests -- read-only `account transactions` capability (Phase P3.86-C, strategy B1).

The P3.86 transaction-access audit showed that adding `("account",
"transactions")` to `_READ_ONLY_CLI_VERBS` ALONE (strategy B0) would relay
injected arguments such as `account transactions generate create ...` or
`--purchase 1` to the CLI. B1 adds the verb AND a canonical-form check
(`build_cli_argv()`):

    account transactions [--size <1..100>] [--cursor <opaque token>]

no positional argument, no other option, each option at most once, fixed
order, no `--x=v` form -- plus the narrow typed API
`HiggsfieldClient.get_account_transactions(size=None, cursor=None)`.

Provider = CLOSED: even a canonical form is never executed. The argv is
checked with the pure `build_argv()`; `run()` validates the same way then
always refuses. Every test runs under `no_egress()`: no real CLI, no
process, no network, no credits.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import integrations.higgsfield.client as client_mod
from integrations.higgsfield.client import HiggsfieldClient
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.provider import HiggsfieldProvider
from tests.provider_closure_helpers import NoEgressTestCase

PROVIDER_CLOSED = "provider_closed_no_cli_process"


# Fixture hermétique : un npm layout temporaire remplace le CLI Higgsfield
# installé sur la machine. Tout `HiggsfieldClient()` du module résout ce
# shim puis l'invocation Node directe (P3.92-R1), utilisée seulement pour
# construire l'argv : rien n'est lancé.
_FAKE_NPM_SHIM = (
    '@ECHO off\n'
    'endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  '
    '"%dp0%\\node_modules\\@higgsfield\\cli\\bin\\higgsfield.js"  %*\n'
)
_FIXTURE_NODE_EXE = None
_FIXTURE_SCRIPT = None


def setUpModule():
    global _FIXTURE_NODE_EXE, _FIXTURE_SCRIPT
    tmp = tempfile.TemporaryDirectory()
    unittest.addModuleCleanup(tmp.cleanup)
    root = Path(tmp.name)
    bin_dir = root / "node_modules" / "@higgsfield" / "cli" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "higgsfield.js").write_text("// fake entry\n", encoding="utf-8")
    (root / "node.exe").write_text("", encoding="utf-8")
    shim = root / "higgsfield.cmd"
    shim.write_text(_FAKE_NPM_SHIM, encoding="utf-8")
    env = mock.patch.dict(os.environ, {client_mod.HIGGSFIELD_CLI_ENV_VAR: str(shim), "APPDATA": str(root)})
    env.start()
    unittest.addModuleCleanup(env.stop)
    _FIXTURE_NODE_EXE = root / "node.exe"
    _FIXTURE_SCRIPT = bin_dir / "higgsfield.js"


class _TxCase(NoEgressTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.client = HiggsfieldClient()

    def argv(self, *args):
        """Validated argv after `--json` (pure: no process)."""

        argv = self.client.build_argv(*args)
        return tuple(argv[argv.index("--json") + 1:])

    def forwarded(self, call):
        """Arguments the typed API hands to `run()` (replaced: nothing runs)."""

        forwarded = []
        with mock.patch.object(HiggsfieldClient, "run", lambda self, *args, **kwargs: forwarded.append(args)):
            call()
        return forwarded

    def assertClosed(self, call):
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as context:
            call()
        self.assertEqual(context.exception.reasons, [PROVIDER_CLOSED])
        self.assertEqual(self.egress, [])

    def assertRefusedBeforeProcess(self, *args):
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as context:
            self.client.build_argv(*args)
        self.assertNotEqual(context.exception.reasons, [PROVIDER_CLOSED])
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            self.client.run(*args)
        self.assertEqual(self.egress, [], f"refused form reached a process: {args}")


class TestAllowedReadOnlyForms(_TxCase):
    CANONICAL = [
        ({}, ("account", "transactions")),
        ({"size": 50}, ("account", "transactions", "--size", "50")),
        ({"size": 1}, ("account", "transactions", "--size", "1")),
        ({"size": 100}, ("account", "transactions", "--size", "100")),
        ({"cursor": "eyJvZmZzZXQiOjUwfQ=="}, ("account", "transactions", "--cursor", "eyJvZmZzZXQiOjUwfQ==")),
        ({"size": 100, "cursor": "abc_DEF-123.x:y/z+"}, ("account", "transactions", "--size", "100", "--cursor", "abc_DEF-123.x:y/z+")),
    ]

    def test_typed_api_builds_the_exact_canonical_command(self):
        for kwargs, expected in self.CANONICAL:
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.forwarded(lambda: self.client.get_account_transactions(**kwargs)), [expected])
                self.assertEqual(self.argv(*expected), expected)

    def test_canonical_forms_validate_but_are_never_executed(self):
        for kwargs, expected in self.CANONICAL:
            with self.subTest(kwargs=kwargs):
                self.assertClosed(lambda: self.client.get_account_transactions(**kwargs))
                self.assertClosed(lambda: self.client.run(*expected))
        self.assertEqual(
            self.client.build_argv("account", "transactions", "--size", "50", "--cursor", "c1"),
            [str(_FIXTURE_NODE_EXE), str(_FIXTURE_SCRIPT), "--json", "account", "transactions", "--size", "50", "--cursor", "c1"],
        )

    def test_nothing_built_ever_contains_a_generation_verb(self):
        calls = self.forwarded(lambda: (self.client.get_account_transactions(),
                                        self.client.get_account_transactions(size=10, cursor="next")))
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertEqual(self.argv(*call)[:2], ("account", "transactions"))
            self.assertFalse({"generate", "create", "submit", "confirm", "purchase"} & set(call))


class TestB0IsReproducedAndB1BlocksIt(_TxCase):
    B0_INJECTIONS = [
        ("account", "transactions", "generate", "create", "seedance_2_0"),
        ("account", "transactions", "--size", "50", "create"),
        ("account", "transactions", "--purchase", "1"),
    ]

    def test_b0_verb_only_allowlist_would_relay_the_injections(self):
        # Reproduction of the audit's B0 finding: with the canonical-form check
        # neutralised, the verb allowlist alone validates every injection --
        # only the Provider = CLOSED refusal of `run()` would remain.
        with mock.patch.object(client_mod, "_account_transactions_violations", return_value=[]):
            for args in self.B0_INJECTIONS:
                with self.subTest(args=args):
                    self.assertEqual(self.argv(*args), args)
                    self.assertClosed(lambda: self.client.run(*args))

    def test_b1_blocks_every_b0_injection(self):
        for args in self.B0_INJECTIONS:
            with self.subTest(args=args):
                self.assertRefusedBeforeProcess(*args)


class TestRefusedForms(_TxCase):
    def test_injections_and_arbitrary_arguments_are_refused(self):
        cases = {
            "generate injection": ("account", "transactions", "generate"),
            "create injection": ("account", "transactions", "create"),
            "submit / confirm / purchase / billing": ("account", "transactions", "submit", "confirm", "purchase", "billing"),
            "arbitrary extra argument": ("account", "transactions", "./anything"),
            "injection after a valid option": ("account", "transactions", "--cursor", "c1", "generate", "create"),
        }
        for label, args in cases.items():
            with self.subTest(case=label):
                self.assertRefusedBeforeProcess(*args)

    def test_unknown_and_generation_like_options_are_refused(self):
        for option in ("--purchase", "--page", "--limit", "--workspace", "--prompt", "--image", "--duration", "--wait", "--json", "-s"):
            with self.subTest(option=option):
                self.assertRefusedBeforeProcess("account", "transactions", option, "1")

    def test_mutative_or_other_commands_are_refused(self):
        cases = [
            ("generate", "create", "seedance_2_0", "--prompt", "P"),
            ("account", "purchase"),
            ("account", "confirm"),
            ("account", "topup"),
            ("billing", "purchase"),
            ("workspace", "set", "ws-1"),
            ("account", "transaction"),
            ("Account", "Transactions"),
        ]
        for args in cases:
            with self.subTest(args=args):
                self.assertRefusedBeforeProcess(*args)

    def test_empty_partial_and_reordered_commands_are_refused(self):
        for args in [(), ("account",), ("transactions",), ("transactions", "account"),
                     ("account", "transactions", "--cursor", "c1", "--size", "50")]:
            with self.subTest(args=args):
                self.assertRefusedBeforeProcess(*args)

    def test_malformed_option_syntax_is_refused(self):
        for args in [("account", "transactions", "--size=50"),
                     ("account", "transactions", "--size", "50", "--size", "10"),
                     ("account", "transactions", "--cursor", "a", "--cursor", "b"),
                     ("account", "transactions", "--size"),
                     ("account", "transactions", "--cursor")]:
            with self.subTest(args=args):
                self.assertRefusedBeforeProcess(*args)

    def test_out_of_domain_values_are_refused(self):
        for size in ("0", "101", "-1", "50.0", "050", "abc", "", "1e2", " 50"):
            with self.subTest(size=size):
                self.assertRefusedBeforeProcess("account", "transactions", "--size", size)
        for cursor in ("-x", "--size", "has space", "", "a;b", "x" * 513, "é"):
            with self.subTest(cursor=cursor):
                self.assertRefusedBeforeProcess("account", "transactions", "--cursor", cursor)

    def test_typed_api_rejects_bad_parameters_before_building_anything(self):
        for kwargs in ({"size": True}, {"size": "50"}, {"size": 0}, {"size": 101}, {"size": 50.0}, {"cursor": 123}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.client.get_account_transactions(**kwargs)
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as context:
            self.client.get_account_transactions(cursor="--image")
        self.assertNotEqual(context.exception.reasons, [PROVIDER_CLOSED])
        self.assertEqual(self.egress, [])


class TestLocksAndSeparationStayIntact(_TxCase):
    def test_create_paths_stay_refused(self):
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            self.client.create_job("seedance_2_0", "P", duration=15)
        self.assertRefusedBeforeProcess("generate", "create", "seedance_2_0", "--prompt", "P")
        self.assertRefusedBeforeProcess("generate", "cost", "seedance_2_0", "--image", "./x.png")

    def test_provider_does_not_expose_or_use_transactions(self):
        self.assertFalse(any("transaction" in name for name in dir(HiggsfieldProvider)))
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            HiggsfieldProvider(client=self.client).create_job(job_type="seedance_2_0", prompt="P", duration=15)
        self.assertEqual(self.egress, [])


class TestHermeticCliFixture(unittest.TestCase):
    def test_default_client_resolves_the_temporary_node_exe(self):
        invocation = HiggsfieldClient()._direct_invocation
        self.assertIsNotNone(invocation)
        self.assertEqual(Path(invocation[0]), _FIXTURE_NODE_EXE)


if __name__ == "__main__":
    unittest.main()
