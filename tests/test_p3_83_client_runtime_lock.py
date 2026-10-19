"""
Tests -- Higgsfield Client Runtime Lock (Phase P3.83, verrou D spécifié en P3.82).

Before P3.83 only `HiggsfieldProvider.create_job()` was closed: any holder of
the Client (`AIDirector.higgsfield`, `<P2 object>.provider.client`, a direct
instance) reached a billable `generate create` with no P2 layer involved
(8 paths reproduced in P3.82). P3.83 closed the Client itself:

- `create_job()` raises `HiggsfieldRealGenerationDisabledError` first thing
  (no argv built, `run()` never reached);
- only the closed allowlist of read-only verbs `_READ_ONLY_CLI_VERBS`
  passes validation; everything else is refused BEFORE any command is built.

Provider = CLOSED now goes further: `run()` starts no process at all, not even
for a read-only verb. It validates the command with the pure
`build_cli_argv()` and then always raises. The authorized P2 path with the
real client is blocked by the Gate before any provider call.

The lock is stateless: no caller inspection, no global flag, no `approved`
boolean can reopen it; reopening is a separate written decision and step.
Every test runs under `no_egress()`: any process launch or connection would
be recorded and refused, and the record must stay empty.
"""

import ast
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import integrations.higgsfield.client as client_mod
from integrations.higgsfield.client import HiggsfieldClient, build_create_job_args
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from tests.real_provider_path_fixtures import FIXTURE_MAX_COST_CREDITS_PER_REQUEST, fixture_identity_lock_for
from tests.authorization_content_helpers import bind_request, content_media
from tests.provider_closure_helpers import NoEgressTestCase
from agents.generation_job_service import GenerationJobExecutionError, GenerationJobService

PROVIDER_CLOSED = "provider_closed_no_cli_process"

# Fixture hermétique : un npm layout temporaire remplace le CLI Higgsfield
# installé sur la machine. Tout `HiggsfieldClient()` du module (direct, via
# AIDirector ou le Provider) résout ce shim puis l'invocation Node directe
# (P3.92-R1), utilisée seulement pour construire l'argv : rien n'est lancé.
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


class _LockedClientCase(NoEgressTestCase, unittest.TestCase):
    def assertRefused(self, fn):
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as context:
            fn()
        return context.exception


class TestWithoutActivationEverythingBillableIsRefused(_LockedClientCase):
    def test_the_eight_p3_82_paths_are_refused_before_any_process(self):
        from director import AIDirector

        director = AIDirector()
        chain = director._build_default_chain()
        paths = {
            "AIDirector().higgsfield.create_job": lambda: AIDirector().higgsfield.create_job("seedance_2_0", "P", duration=15),
            "AIDirector().higgsfield.run(generate create)": lambda: AIDirector().higgsfield.run("generate", "create", "seedance_2_0", "--prompt", "P"),
            "gate.provider.client.create_job": lambda: chain.gate.provider.client.create_job("seedance_2_0", "P"),
            "job_service.provider.client.create_job": lambda: chain.job_service.provider.client.create_job("seedance_2_0", "P"),
            "alias = director.higgsfield": lambda: (lambda alias: alias.create_job("seedance_2_0", "P"))(director.higgsfield),
            "client = provider.client": lambda: (lambda client: client.create_job("seedance_2_0", "P"))(chain.provider.client),
            "HiggsfieldClient().create_job": lambda: HiggsfieldClient().create_job("seedance_2_0", "P"),
            "HiggsfieldClient().run(generate create)": lambda: HiggsfieldClient().run("generate", "create", "seedance_2_0", "--prompt", "P"),
        }
        for label, fn in paths.items():
            with self.subTest(path=label):
                self.assertRefused(fn)
        self.assertEqual(self.egress, [], "a refused call must never reach a process")

    def test_create_job_never_reaches_run_even_if_run_is_replaced(self):
        client = HiggsfieldClient.__new__(HiggsfieldClient)
        reached = []
        client.run = lambda *a, **k: reached.append(a)
        self.assertRefused(lambda: client.create_job("seedance_2_0", "P", duration=15))
        self.assertEqual(reached, [])

    def test_every_non_read_only_verb_is_refused(self):
        client = HiggsfieldClient()
        cases = [
            ("generate", "create", "seedance_2_0"),
            ("GENERATE", "CREATE"),
            ("generate", "Create"),
            ("generate", "upscale"),
            ("video", "create"),
            ("--flag", "generate", "create"),
            ("generate",),
            (),
            ("auth", "login"),
        ]
        for args in cases:
            with self.subTest(args=args):
                error = self.assertRefused(lambda: client.run(*args))
                self.assertEqual(error.reasons, [f"cli_verb_not_read_only: {tuple(args[:2])!r}"])
                self.assertRefused(lambda: client.build_argv(*args))
        self.assertRefused(lambda: client.run("generate", "create", "m", timeout=1))
        self.assertEqual(self.egress, [])

    def test_no_attribute_flag_or_boolean_reopens_the_lock(self):
        client = HiggsfieldClient()
        client.approved = True
        client.authorized = True
        client.real_generation_authorization = RealGenerationAuthorization(authorized_by_human=True, request_id="005")
        with mock.patch.object(client_mod, "REAL_GENERATION_ENABLED", True, create=True), \
                mock.patch.object(client_mod, "PROVIDER_CLOSED", False, create=True):
            self.assertRefused(lambda: client.create_job("seedance_2_0", "P"))
            self.assertRefused(lambda: client.run("generate", "create", "seedance_2_0"))
            self.assertEqual(self.assertRefused(lambda: client.run("account", "status")).reasons, [PROVIDER_CLOSED])
        self.assertEqual(self.egress, [])

    def test_concurrent_attempts_are_all_refused(self):
        client = HiggsfieldClient()
        outcomes, barrier = [], threading.Barrier(16)

        def attempt(i):
            barrier.wait()
            try:
                client.create_job("seedance_2_0", "P") if i % 2 else client.run("generate", "create", "seedance_2_0")
                outcomes.append("SENT")
            except HiggsfieldRealGenerationDisabledError:
                outcomes.append("REFUSED")

        threads = [threading.Thread(target=attempt, args=(i,)) for i in range(16)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(outcomes.count("REFUSED"), 16)
        self.assertEqual(self.egress, [])

    def test_documented_create_arguments_remain_pinned_without_execution(self):
        self.assertEqual(
            build_create_job_args("seedance_2_0", "P", duration=15, resolution="720p", aspect_ratio="9:16", seed=None),
            ["generate", "create", "seedance_2_0", "--prompt", "P", "--duration", "15", "--resolution", "720p", "--aspect-ratio", "9:16"],
        )
        self.assertEqual(self.egress, [])


class TestReadOperationsAreClosed(_LockedClientCase):
    READS = {
        "list_workflows": ((), ("workflow", "list")),
        "get_workflow": (("cinematic_studio_video_4_0",), ("workflow", "get", "cinematic_studio_video_4_0")),
        "account_status": ((), ("account", "status")),
        "estimate_cost": (
            ("seedance_2_0", "P", 15, "720p", "9:16"),
            ("generate", "cost", "seedance_2_0", "--prompt", "P", "--duration", "15", "--resolution", "720p",
             "--aspect-ratio", "9:16"),
        ),
        "list_models": ((), ("model", "list", "--video")),
        "get_model": (("seedance_2_0",), ("model", "get", "seedance_2_0")),
        "get_job": (("job-1",), ("generate", "get", "job-1")),
        "list_jobs": ((), ("generate", "list")),
        "wait_for_job": (("job-1", 5, 1), ("generate", "wait", "job-1", "--timeout", "5s", "--interval", "1s")),
    }

    def test_every_read_method_is_refused_without_starting_a_process(self):
        client = HiggsfieldClient()
        for method, (args, _) in self.READS.items():
            with self.subTest(method=method):
                self.assertEqual(self.assertRefused(lambda: getattr(client, method)(*args)).reasons, [PROVIDER_CLOSED])
        self.assertEqual(self.egress, [])

    def test_read_methods_still_build_their_exact_validated_argv(self):
        client = HiggsfieldClient()
        forwarded = []
        with mock.patch.object(HiggsfieldClient, "run", lambda self, *args, **kwargs: forwarded.append(args)):
            for method, (args, _) in self.READS.items():
                getattr(client, method)(*args)
        self.assertEqual(forwarded, [cli_args for _, cli_args in self.READS.values()])
        for cli_args in forwarded:
            with self.subTest(argv=cli_args):
                self.assertEqual(client.build_argv(*cli_args), [str(_FIXTURE_NODE_EXE), str(_FIXTURE_SCRIPT), "--json", *cli_args])
        self.assertEqual(self.egress, [])

    def test_allowlist_is_exactly_the_read_only_contract(self):
        self.assertEqual(
            client_mod._READ_ONLY_CLI_VERBS,
            # P3.86-C (authorized): + ("account", "transactions"), read-only, canonical form enforced in run().
            frozenset({("workflow", "list"), ("workflow", "get"), ("account", "status"), ("account", "transactions"),
                       ("model", "list"), ("model", "get"), ("generate", "cost"), ("generate", "get"),
                       ("generate", "list"), ("generate", "wait")}),
        )


class TestAuthorizedP2PathUnderTheLock(_LockedClientCase):
    """Mock/fixture only. With the real Client, even the fully authorized P2
    path is blocked by the Gate before any provider call (Provider = CLOSED)."""

    def _authorized_request(self, request_id="p383-authorized"):
        return bind_request(GenerationRequest(
            **content_media(),
            request_id=request_id, job_type="seedance_2_0", prompt="P", duration=15, resolution="720p",
            aspect_ratio="9:16", approved=True,
            real_generation_authorization=RealGenerationAuthorization(authorized_by_human=True, request_id=request_id),
        ))

    def _spied_provider(self):
        provider = HiggsfieldProvider(client=HiggsfieldClient())
        # Reads only: an instance-level create_job would make the provider an
        # unrecognized one, refused by GenerationJobService before the Gate.
        spies = {
            name: mock.patch.object(provider, name, side_effect=AssertionError(f"provider.{name} reached"))
            for name in ("get_model", "estimate_cost", "get_account_balance", "list_models", "get_job", "wait_for_job")
        }
        for name, spy in spies.items():
            spies[name] = spy.start()
            self.addCleanup(spy.stop)
        return provider, spies

    def test_authorized_request_with_the_real_client_is_blocked_before_any_provider_call(self):
        provider, spies = self._spied_provider()
        request = self._authorized_request()
        # Even with the Phase D fixtures (ceiling + Identity Lock), the real
        # Client path is closed before validation.
        gate = GenerationApprovalGate(
            provider,
            identity_lock=fixture_identity_lock_for(request),
            max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST,
        )

        result = gate.evaluate(request)
        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)
        self.assertTrue(any("Provider = CLOSED" in reason for reason in result.reasons), result.reasons)
        with self.assertRaises(GenerationJobExecutionError):
            GenerationJobService(provider, gate).execute(request)

        for name, spy in spies.items():
            with self.subTest(method=name):
                spy.assert_not_called()
        self.assertEqual(self.egress, [])
        self.assertFalse(gate.is_already_executed(request.request_id), "no job created -> never marked executed")

    def test_unauthorized_request_never_reaches_creation(self):
        provider, spies = self._spied_provider()
        request = GenerationRequest(**content_media(), request_id="p383-no-auth", job_type="seedance_2_0", prompt="P", duration=15,
                                    resolution="720p", aspect_ratio="9:16", approved=True)
        gate = GenerationApprovalGate(
            provider,
            identity_lock=fixture_identity_lock_for(request),
            max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST,
        )
        self.assertEqual(gate.evaluate(request).decision, GenerationApprovalDecision.BLOCKED)
        for spy in spies.values():
            spy.assert_not_called()
        self.assertEqual(self.egress, [])

    def test_authorized_chain_still_executes_end_to_end_with_the_mock_provider(self):
        provider = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=100.0, sleep=lambda s: None)
        gate = GenerationApprovalGate(provider)
        outcome = GenerationJobService(provider, gate).execute(self._authorized_request("p383-mock"))
        self.assertTrue(outcome.succeeded)
        self.assertTrue(gate.is_already_executed("p383-mock"))
        self.assertEqual(self.egress, [], "the mock path never touches the real client")

    def test_real_provider_create_job_still_closed_and_never_touches_the_client(self):
        client = HiggsfieldClient()
        with mock.patch.object(HiggsfieldClient, "create_job", side_effect=AssertionError("client reached")) as spy:
            with self.assertRaises(HiggsfieldRealGenerationDisabledError):
                HiggsfieldProvider(client=client).create_job(job_type="seedance_2_0", prompt="P", duration=15)
            spy.assert_not_called()
        self.assertEqual(self.egress, [])


class TestLockStructureCannotBeBypassedByANewMethod(unittest.TestCase):
    """P3.84: a new client method launching the CLI through `subprocess`
    directly (bypassing `run()` and its allowlist) passed the whole suite
    (mutation reproduced). Provider = CLOSED goes further: the client module
    contains no process launch at all, its validation starts with the
    allowlist guard, and `run()` always ends by refusing."""

    LAUNCHERS = ("subprocess.", "os.system", "os.popen", "os.spawn", "os.exec", "os.startfile",
                 "asyncio.create_subprocess", "pty.spawn")
    PROCESS_MODULES = ("subprocess", "multiprocessing", "pty", "asyncio")

    def setUp(self):
        self.tree = ast.parse(Path(client_mod.__file__).read_text(encoding="utf-8-sig"))
        self.cls = next(n for n in self.tree.body if isinstance(n, ast.ClassDef) and n.name == "HiggsfieldClient")

    def _method(self, name):
        return next(f for f in self.cls.body if isinstance(f, ast.FunctionDef) and f.name == name)

    @staticmethod
    def _statements(function):
        return [s for s in function.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]

    def test_the_client_module_contains_no_process_launch(self):
        launches = [
            (n.lineno, ast.unparse(n.func))
            for n in ast.walk(self.tree)
            if isinstance(n, ast.Call) and ast.unparse(n.func).startswith(self.LAUNCHERS)
        ]
        self.assertEqual(launches, [])
        imported = {alias.name.split(".")[0] for n in ast.walk(self.tree) if isinstance(n, ast.Import) for alias in n.names}
        imported |= {n.module.split(".")[0] for n in ast.walk(self.tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertFalse(imported & set(self.PROCESS_MODULES), imported)
        self.assertFalse(hasattr(client_mod, "subprocess"))

    def test_allowlist_guard_comes_first_and_run_always_refuses(self):
        build = next(n for n in self.tree.body if isinstance(n, ast.FunctionDef) and n.name == "build_cli_argv")
        statements = self._statements(build)
        guard = next(
            (s for s in statements if isinstance(s, ast.If) and "_READ_ONLY_CLI_VERBS" in ast.unparse(s.test)), None
        )
        self.assertIsNotNone(guard, "build_cli_argv() must test _READ_ONLY_CLI_VERBS")
        self.assertIsInstance(guard.body[0], ast.Raise)
        self.assertLessEqual(statements.index(guard), 2, "the guard must be the first check, unconditional")

        run = self._statements(self._method("run"))
        self.assertEqual([ast.unparse(s) for s in run[:-1]], ["self.build_argv(*args)"])
        self.assertIsInstance(run[-1], ast.Raise)
        self.assertIn("provider_closed_no_cli_process", ast.unparse(run[-1]))
        self.assertFalse([n for n in ast.walk(self._method("run")) if isinstance(n, (ast.Return, ast.Try))])

    def test_create_job_is_a_single_raise(self):
        statements = self._statements(self._method("create_job"))
        self.assertEqual([type(s).__name__ for s in statements], ["Raise"])


class TestFailClosedOnTheRealPath(NoEgressTestCase, unittest.TestCase):
    def test_real_provider_gate_is_blocked_and_never_creates(self):
        provider = HiggsfieldProvider(client=HiggsfieldClient())
        gate = GenerationApprovalGate(provider)
        request = GenerationRequest(
            request_id="p383-cli-down", job_type="seedance_2_0", prompt="P", duration=15, resolution="720p",
            aspect_ratio="9:16", approved=True,
            real_generation_authorization=RealGenerationAuthorization(authorized_by_human=True, request_id="p383-cli-down"),
        )
        with mock.patch.object(HiggsfieldClient, "create_job", side_effect=AssertionError("client reached")) as spy:
            self.assertEqual(gate.evaluate(request).decision, GenerationApprovalDecision.BLOCKED)
            spy.assert_not_called()
        self.assertEqual(self.egress, [])


class TestHermeticCliFixture(unittest.TestCase):
    def test_default_client_resolves_the_temporary_node_exe(self):
        invocation = HiggsfieldClient()._direct_invocation
        self.assertIsNotNone(invocation)
        self.assertEqual(Path(invocation[0]), _FIXTURE_NODE_EXE)


if __name__ == "__main__":
    unittest.main()
