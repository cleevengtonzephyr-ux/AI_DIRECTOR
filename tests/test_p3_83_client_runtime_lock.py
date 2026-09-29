"""
Tests -- Higgsfield Client Runtime Lock (Phase P3.83, verrou D spécifié en P3.82).

Before P3.83 only `HiggsfieldProvider.create_job()` was closed: any holder of
the Client (`AIDirector.higgsfield`, `<P2 object>.provider.client`, a direct
instance) reached a billable `generate create` with no P2 layer involved
(8 paths reproduced in P3.82). P3.83 closes the Client itself:

- `create_job()` raises `HiggsfieldRealGenerationDisabledError` first thing
  (no argv built, `run()` never reached);
- `run()` executes only the closed allowlist of read-only verbs
  `_READ_ONLY_CLI_VERBS`; everything else is refused BEFORE any command is
  built or any process started.

The lock is stateless: no caller inspection, no global flag, no `approved`
boolean can reopen it. It is NOT a new authority; the future reopening (a
capability minted by `GenerationJobService.execute()` after the whole P2
chain) is a separate, dedicated phase. Under this phase the authorized P2
path therefore reaches the Client for READS only; creation stops at the
(already closed) Provider.

Every test replaces the client module's `subprocess` with a recording fake:
no process can start, no network, no credits.
"""

import json
import os
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import integrations.higgsfield.client as client_mod
from integrations.higgsfield.client import HiggsfieldClient, build_create_job_args
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import DEFAULT_MOCK_MODELS, MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from tests.authorization_content_helpers import bind_request, content_media
from agents.generation_job_service import GenerationJobService


def _model_json(job_type):
    schema = next(m for m in DEFAULT_MOCK_MODELS if m.job_type == job_type)
    return {
        "job_type": schema.job_type,
        "display_name": schema.display_name,
        "params": [
            {"name": p.name, "type": p.type, "required": p.required, "default": p.default, "enum": list(p.enum)}
            for p in schema.params
        ],
    }


# Fixture hermétique : un npm layout temporaire remplace le CLI Higgsfield
# installé sur la machine. Tout `HiggsfieldClient()` du module (direct, via
# AIDirector ou le Provider) résout ce shim puis l'invocation Node directe
# (P3.92-R1) ; sans elle, `run()` refuse le shim .cmd avant tout processus.
_FAKE_NPM_SHIM = (
    '@ECHO off\n'
    'endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  '
    '"%dp0%\\node_modules\\@higgsfield\\cli\\bin\\higgsfield.js"  %*\n'
)
_FIXTURE_NODE_EXE = None


def setUpModule():
    global _FIXTURE_NODE_EXE
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


class _FakeSubprocess(types.ModuleType):
    """Stands in for `subprocess` inside the client module: records the CLI
    arguments it would have received and answers read verbs with JSON."""

    TimeoutExpired = client_mod.subprocess.TimeoutExpired

    def __init__(self, fail_with=None):
        super().__init__("fake_subprocess")
        self.calls = []
        self._fail_with = fail_with

    def run(self, command, **kwargs):
        args = list(command[command.index("--json") + 1:])
        self.calls.append(tuple(args))
        if self._fail_with is not None:
            raise self._fail_with
        verb = tuple(args[:2])
        if verb == ("model", "get"):
            body = _model_json(args[2])
        elif verb == ("generate", "cost"):
            body = {"credits": 67.5}
        elif verb == ("account", "status"):
            body = {"credits": 100.0}
        else:
            body = {"ok": True, "status": "completed", "id": "job-1"}
        return SimpleNamespace(returncode=0, stdout=json.dumps(body), stderr="")


class _LockedClientCase(unittest.TestCase):
    def setUp(self):
        self.fake = _FakeSubprocess()
        patcher = mock.patch.object(client_mod, "subprocess", self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def assertRefused(self, fn):
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            fn()


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
        self.assertEqual(self.fake.calls, [], "a refused call must never reach subprocess")

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
                self.assertRefused(lambda: client.run(*args))
        self.assertRefused(lambda: client.run("generate", "create", "m", timeout=1))
        self.assertEqual(self.fake.calls, [])

    def test_no_attribute_flag_or_boolean_reopens_the_lock(self):
        client = HiggsfieldClient()
        client.approved = True
        client.authorized = True
        client.real_generation_authorization = RealGenerationAuthorization(authorized_by_human=True, request_id="005")
        with mock.patch.object(client_mod, "REAL_GENERATION_ENABLED", True, create=True):
            self.assertRefused(lambda: client.create_job("seedance_2_0", "P"))
            self.assertRefused(lambda: client.run("generate", "create", "seedance_2_0"))
        self.assertEqual(self.fake.calls, [])

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
        self.assertEqual(self.fake.calls, [])

    def test_documented_create_arguments_remain_pinned_without_execution(self):
        self.assertEqual(
            build_create_job_args("seedance_2_0", "P", duration=15, resolution="720p", aspect_ratio="9:16", seed=None),
            ["generate", "create", "seedance_2_0", "--prompt", "P", "--duration", "15", "--resolution", "720p", "--aspect-ratio", "9:16"],
        )
        self.assertEqual(self.fake.calls, [])


class TestReadOnlyOperationsStillWork(_LockedClientCase):
    def test_reads_status_and_polling_reach_the_cli(self):
        client = HiggsfieldClient()
        client.list_workflows()
        client.get_workflow("cinematic_studio_video_4_0")
        client.account_status()
        client.estimate_cost("seedance_2_0", "P", duration=15, resolution="720p", aspect_ratio="9:16")
        client.list_models()
        client.get_model("seedance_2_0")
        client.get_job("job-1")
        client.list_jobs()
        client.wait_for_job("job-1", timeout_seconds=5, interval_seconds=1)
        self.assertEqual(
            [c[:2] for c in self.fake.calls],
            [("workflow", "list"), ("workflow", "get"), ("account", "status"), ("generate", "cost"),
             ("model", "list"), ("model", "get"), ("generate", "get"), ("generate", "list"), ("generate", "wait")],
        )

    def test_allowlist_is_exactly_the_read_only_contract(self):
        self.assertEqual(
            client_mod._READ_ONLY_CLI_VERBS,
            # P3.86-C (authorized): + ("account", "transactions"), read-only, canonical form enforced in run().
            frozenset({("workflow", "list"), ("workflow", "get"), ("account", "status"), ("account", "transactions"),
                       ("model", "list"), ("model", "get"), ("generate", "cost"), ("generate", "get"),
                       ("generate", "list"), ("generate", "wait")}),
        )


class TestAuthorizedP2PathUnderTheLock(_LockedClientCase):
    """Mock/fixture only. Under this phase the fully authorized P2 path
    reaches the real Client for its READS; creation stops at the Provider."""

    def _authorized_request(self, request_id="p383-authorized"):
        return bind_request(GenerationRequest(
            **content_media(),
            request_id=request_id, job_type="seedance_2_0", prompt="P", duration=15, resolution="720p",
            aspect_ratio="9:16", approved=True,
            real_generation_authorization=RealGenerationAuthorization(authorized_by_human=True, request_id=request_id),
        ))

    def test_authorized_request_reads_through_the_real_client_and_creation_stays_closed(self):
        provider = HiggsfieldProvider(client=HiggsfieldClient())
        gate = GenerationApprovalGate(provider)
        request = self._authorized_request()

        self.assertEqual(gate.evaluate(request).decision, GenerationApprovalDecision.APPROVED)
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            GenerationJobService(provider, gate).execute(request)

        verbs = {c[:2] for c in self.fake.calls}
        self.assertTrue({("model", "get"), ("generate", "cost"), ("account", "status")} <= verbs)
        self.assertNotIn(("generate", "create"), verbs)
        self.assertFalse(gate.is_already_executed(request.request_id), "no job created -> never marked executed")

    def test_unauthorized_request_never_reaches_creation(self):
        provider = HiggsfieldProvider(client=HiggsfieldClient())
        gate = GenerationApprovalGate(provider)
        request = GenerationRequest(request_id="p383-no-auth", job_type="seedance_2_0", prompt="P", duration=15,
                                    resolution="720p", aspect_ratio="9:16", approved=True)
        self.assertEqual(gate.evaluate(request).decision, GenerationApprovalDecision.NEEDS_APPROVAL)
        self.assertNotIn(("generate", "create"), {c[:2] for c in self.fake.calls})

    def test_authorized_chain_still_executes_end_to_end_with_the_mock_provider(self):
        provider = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=100.0, sleep=lambda s: None)
        gate = GenerationApprovalGate(provider)
        outcome = GenerationJobService(provider, gate).execute(self._authorized_request("p383-mock"))
        self.assertTrue(outcome.succeeded)
        self.assertTrue(gate.is_already_executed("p383-mock"))
        self.assertEqual(self.fake.calls, [], "the mock path never touches the real client")

    def test_real_provider_create_job_still_closed_and_never_touches_the_client(self):
        client = HiggsfieldClient()
        with mock.patch.object(HiggsfieldClient, "create_job", side_effect=AssertionError("client reached")) as spy:
            with self.assertRaises(HiggsfieldRealGenerationDisabledError):
                HiggsfieldProvider(client=client).create_job(job_type="seedance_2_0", prompt="P", duration=15)
            spy.assert_not_called()
        self.assertEqual(self.fake.calls, [])


class TestLockStructureCannotBeBypassedByANewMethod(unittest.TestCase):
    """P3.84: a new client method launching the CLI through `subprocess`
    directly (bypassing `run()` and its allowlist) passed the whole suite
    (mutation reproduced). The runtime lock only holds if `run()` stays the
    ONE process-launch point and its allowlist guard runs before it."""

    LAUNCHERS = ("subprocess.", "os.system", "os.popen", "os.spawn", "os.exec", "os.startfile",
                 "asyncio.create_subprocess", "pty.spawn")

    def setUp(self):
        import ast
        self.ast = ast
        self.tree = ast.parse(Path(client_mod.__file__).read_text(encoding="utf-8-sig"))
        self.cls = next(n for n in self.tree.body if isinstance(n, ast.ClassDef) and n.name == "HiggsfieldClient")

    def _method(self, name):
        return next(f for f in self.cls.body if isinstance(f, self.ast.FunctionDef) and f.name == name)

    def test_run_is_the_only_process_launch_point(self):
        ast = self.ast
        run = self._method("run")
        inside_run = {id(n) for n in ast.walk(run)}
        launches = [
            (n.lineno, ast.unparse(n.func), id(n) in inside_run)
            for n in ast.walk(self.tree)
            if isinstance(n, ast.Call) and ast.unparse(n.func).startswith(self.LAUNCHERS)
        ]
        self.assertEqual(len(launches), 1, f"exactly one process launch expected: {launches}")
        self.assertTrue(launches[0][2], f"the only process launch must live in HiggsfieldClient.run: {launches}")

    def test_allowlist_guard_precedes_the_launch_in_run(self):
        ast = self.ast
        run = self._method("run")
        statements = [s for s in run.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
        guard = next(
            (s for s in statements if isinstance(s, ast.If) and "_READ_ONLY_CLI_VERBS" in ast.unparse(s.test)), None
        )
        self.assertIsNotNone(guard, "run() must test _READ_ONLY_CLI_VERBS")
        self.assertIsInstance(guard.body[0], ast.Raise)
        self.assertLessEqual(statements.index(guard), 1, "the guard must be run()'s first check, unconditional")
        launch_line = next(n.lineno for n in ast.walk(run) if isinstance(n, ast.Call) and ast.unparse(n.func).startswith(self.LAUNCHERS))
        self.assertLess(guard.lineno, launch_line)

    def test_create_job_is_a_single_raise(self):
        ast = self.ast
        statements = [s for s in self._method("create_job").body
                      if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
        self.assertEqual([type(s).__name__ for s in statements], ["Raise"])


class TestFailClosedOnCliFailure(unittest.TestCase):
    def test_read_failure_blocks_and_never_creates(self):
        fake = _FakeSubprocess(fail_with=FileNotFoundError("no cli"))
        with mock.patch.object(client_mod, "subprocess", fake):
            provider = HiggsfieldProvider(client=HiggsfieldClient())
            gate = GenerationApprovalGate(provider)
            request = GenerationRequest(
                request_id="p383-cli-down", job_type="seedance_2_0", prompt="P", duration=15, resolution="720p",
                aspect_ratio="9:16", approved=True,
                real_generation_authorization=RealGenerationAuthorization(authorized_by_human=True, request_id="p383-cli-down"),
            )
            self.assertNotEqual(gate.evaluate(request).decision, GenerationApprovalDecision.APPROVED)
        self.assertNotIn(("generate", "create"), {c[:2] for c in fake.calls})


class TestHermeticCliFixture(unittest.TestCase):
    def test_default_client_resolves_the_temporary_node_exe(self):
        invocation = HiggsfieldClient()._direct_invocation
        self.assertIsNotNone(invocation)
        self.assertEqual(Path(invocation[0]), _FIXTURE_NODE_EXE)


if __name__ == "__main__":
    unittest.main()
