"""
Tests -- Provider = CLOSED: no entry point reaches Higgsfield (egress closure).

While Provider = CLOSED (docs/phase_a_real_generation_decision.md), no entry
point of the repository may launch the Higgsfield CLI or open a connection to
Higgsfield, not even for a "read-only" request. These tests pin that over ALL
application code -- director.py, agents/, integrations/, scripts/ and
approval_service/, i.e. everything but tests/:

1. Egress inventory: no application file imports a process, network or
   dynamic-import primitive (`subprocess` and `http.client` included: the
   Higgsfield client and HTTPS transport no longer import them).
2. Closure: HiggsfieldClient.run() and HttpsTransport.send() validate, then
   always end with an unconditional refusal; no second method (such as the
   former HttpsTransport._exchange()) exists.
3. Direct calls: run(), send(), every method of the real Provider and
   AIDirector.run_video_mission() with the default chain have no external
   effect; the Gate blocks the real Provider before get_model().
4. Entry points: a module with a `__main__` block whose import closure
   reaches either Higgsfield module must be listed in CLOSED_ENTRY_POINTS,
   and each of those runs below under sentinels that fail on any CLI,
   process, HTTP(S) or socket use.
5. Workflows only run an allowlisted set of Python entry points and never a
   bare `higgsfield` command.

The sentinels (`no_egress()`) replace every egress point before anything
runs: no test here starts a process or opens a connection. Static limits:
calls hidden behind duck typing, containers or getattr() with a computed name
are not followed; the runtime sentinels cover what the scan cannot.
"""

import ast
import contextlib
import importlib.util
import io
import re
import socket
import subprocess
import sys
import tempfile
import unittest
import http.client
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import integrations.higgsfield.client as client_mod
import integrations.higgsfield.https_transport as transport_mod
from agents.generation_approval_gate import GenerationApprovalDecision, GenerationApprovalGate, GenerationRequest
from agents.release_candidate_identity_lock import VIDEO_005_RELEASE_CANDIDATE as C
from integrations.higgsfield.errors import HiggsfieldError, HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider, provider_closed_reasons
from integrations.higgsfield.rest_api import (
    HIGGSFIELD_REST_FACTS,
    ApiFact,
    ClosedTransport,
    FactStatus,
    HiggsfieldRestClient,
)
from tests.authorization_content_helpers import bind_request, content_media, video_005_authorization
from tests.provider_closure_helpers import EgressAttempt, no_egress
from tests.strict_workflow_yaml import parse_workflow_yaml
from tests.test_phase_b_authorization_single_use import isolated_director_state

CLIENT = "integrations/higgsfield/client.py"
TRANSPORT = "integrations/higgsfield/https_transport.py"
HIGGSFIELD_MODULE_NAMES = frozenset({"integrations.higgsfield.client", "integrations.higgsfield.https_transport"})
PROVIDER_CLOSED = "provider_closed_no_cli_process"
CONFIRMED_FACTS = {name: ApiFact(fact.value, FactStatus.CONFIRMED) for name, fact in HIGGSFIELD_REST_FACTS.items()}

# Never imported by application code, submodules included.
FORBIDDEN_MODULES = (
    "subprocess", "multiprocessing", "concurrent", "asyncio", "pty", "pexpect", "runpy", "code",
    "socket", "socketserver", "ssl", "http", "urllib", "requests", "httpx", "aiohttp",
    "websocket", "websockets", "ftplib", "smtplib", "poplib", "imaplib", "nntplib", "telnetlib",
    "xmlrpc", "webbrowser", "importlib", "ctypes",
)
FORBIDDEN_OS_CALLS = frozenset({"system", "popen", "startfile", "fork", "forkpty", "posix_spawn", "posix_spawnp"})
FORBIDDEN_OS_PREFIXES = ("exec", "spawn")
FORBIDDEN_BUILTINS = frozenset({"__import__", "exec", "eval", "compile"})
# PyJWT fetches JWKS over the network through these.
FORBIDDEN_NAMES = frozenset({"PyJWKClient", "jwks_client"})

# Entry points whose import closure reaches a Higgsfield module; each is run
# under sentinels by TestEntryPointsRunUnderSentinels.
CLOSED_ENTRY_POINTS = frozenset({"director.py", "scripts/higgsfield_check.py", "scripts/demo_test.py"})
# Modules whose `__main__` block used to launch the real CLI (read-only).
FORMER_CLI_ENTRY_POINTS = (
    CLIENT,
    "agents/planner.py",
    "agents/cost_engine.py",
    "agents/production_controller.py",
    "agents/production_gate.py",
    "agents/higgsfield_executor.py",
    "agents/pipeline_orchestrator.py",
)
# The only Python invocations a workflow `run:` block may contain.
WORKFLOW_PYTHON_TARGETS = frozenset({
    "-m pip", "-m unittest", "scripts/architecture_audit.py", "scripts/higgsfield_production_run.py",
})

_EXCLUDED_PARTS = frozenset({"tests", ".git", "__pycache__", "venv", ".venv", "env", "node_modules", "site-packages"})


def _application_files():
    return [
        path for path in sorted(PROJECT_ROOT.rglob("*.py"))
        if not _EXCLUDED_PARTS.intersection(path.relative_to(PROJECT_ROOT).parts)
    ]


def _rel(path):
    return path.relative_to(PROJECT_ROOT).as_posix()


def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _module_name(rel):
    parts = Path(rel).with_suffix("").parts
    if parts[:2] == ("approval_service", "approval_service"):
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _import_names(node):
    """Names an import statement can bind; `from a import b` yields both a and a.b."""

    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    module = "." * node.level + (node.module or "")
    return [module, *(f"{module}.{alias.name}" for alias in node.names)]


def _imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node.lineno, _import_names(node)


def _matches(name, prefix):
    return name == prefix or name.startswith(prefix + ".")


def _method(rel, class_name, method):
    cls = next(n for n in _tree(PROJECT_ROOT / rel).body if isinstance(n, ast.ClassDef) and n.name == class_name)
    return next(f for f in cls.body if isinstance(f, ast.FunctionDef) and f.name == method)


def _has_main_block(tree):
    for node in tree.body:
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and len(node.test.ops) == 1:
            sides = [node.test.left, *node.test.comparators]
            names = {side.id for side in sides if isinstance(side, ast.Name)}
            values = {side.value for side in sides if isinstance(side, ast.Constant)}
            if isinstance(node.test.ops[0], ast.Eq) and names == {"__name__"} and values == {"__main__"}:
                return True
    return False


class TestEgressInventory(unittest.TestCase):
    """No application file may import a process or network primitive."""

    def test_the_scan_covers_every_application_root(self):
        files = {_rel(path) for path in _application_files()}
        for root in ("director.py", "agents/", "integrations/", "scripts/", "approval_service/approval_service/"):
            with self.subTest(root=root):
                self.assertTrue(any(rel == root or rel.startswith(root) for rel in files), root)
        self.assertIn(CLIENT, files)
        self.assertIn(TRANSPORT, files)
        self.assertFalse(any(rel.startswith("tests/") for rel in files))

    def test_process_and_network_modules_are_imported_nowhere(self):
        offenders = []
        for path in _application_files():
            rel = _rel(path)
            for lineno, names in _imports(_tree(path)):
                for name in names:
                    if name.startswith("."):
                        offenders.append(f"{rel}:{lineno} relative import {name} (closure not followed)")
                    elif any(_matches(name, module) for module in FORBIDDEN_MODULES):
                        offenders.append(f"{rel}:{lineno} imports {name}")
        self.assertEqual(offenders, [])

    def test_no_os_process_call_dynamic_import_or_jwks_fetch_is_used(self):
        offenders = []
        for path in _application_files():
            rel = _rel(path)
            tree = _tree(path)
            for lineno, names in _imports(tree):
                for name in names:
                    leaf = name.rsplit(".", 1)[-1]
                    if _matches(name, "os") and name != "os" and (
                        leaf in FORBIDDEN_OS_CALLS or leaf.startswith(FORBIDDEN_OS_PREFIXES)
                    ):
                        offenders.append(f"{rel}:{lineno} imports {name}")
                    if leaf in FORBIDDEN_NAMES:
                        offenders.append(f"{rel}:{lineno} imports {name}")
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os" and (
                    node.attr in FORBIDDEN_OS_CALLS or node.attr.startswith(FORBIDDEN_OS_PREFIXES)
                ):
                    offenders.append(f"{rel}:{node.lineno} uses os.{node.attr}")
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in FORBIDDEN_BUILTINS
                ):
                    offenders.append(f"{rel}:{node.lineno} calls {node.func.id}()")
                if (isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES) or (
                    isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES
                ):
                    offenders.append(f"{rel}:{node.lineno} uses {getattr(node, 'id', None) or node.attr}")
        self.assertEqual(offenders, [])


class TestHiggsfieldModulesAreClosed(unittest.TestCase):
    """The client and the HTTPS transport hold no egress code and always refuse."""

    def test_neither_module_holds_a_process_or_network_module(self):
        self.assertFalse(hasattr(client_mod, "subprocess"))
        self.assertFalse(hasattr(transport_mod, "http"))
        self.assertFalse(hasattr(transport_mod.HttpsTransport, "_exchange"))

    def test_run_and_send_validate_then_always_refuse(self):
        for rel, class_name, method, reason in (
            (CLIENT, "HiggsfieldClient", "run", "provider_closed_no_cli_process"),
            (TRANSPORT, "HttpsTransport", "send", "provider_closed_no_https_connection"),
        ):
            with self.subTest(method=f"{class_name}.{method}"):
                function = _method(rel, class_name, method)
                last = function.body[-1]
                self.assertIsInstance(last, ast.Raise)
                self.assertEqual(last.exc.func.id, "HiggsfieldRealGenerationDisabledError")
                self.assertIn(reason, ast.unparse(last))
                self.assertFalse([n for n in ast.walk(function) if isinstance(n, (ast.Return, ast.Try, ast.Yield))])

    def test_the_rest_client_defaults_to_a_transport_that_never_sends(self):
        self.assertIs(type(HiggsfieldRestClient().transport), ClosedTransport)


class TestDirectCallsHaveNoExternalEffect(unittest.TestCase):
    """Called directly, every Higgsfield entry is refused with no process and no connection."""

    def setUp(self):
        context = no_egress()
        self.egress = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.client = client_mod.HiggsfieldClient(command="fake-higgsfield-cli")

    def assertClosed(self, call, reasons=(PROVIDER_CLOSED,)):
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as context:
            call()
        if reasons is not None:
            self.assertEqual(context.exception.reasons, list(reasons))
        return context.exception

    def test_client_run_and_every_read_are_refused(self):
        calls = {
            "run(account status)": lambda: self.client.run("account", "status"),
            "run(generate cost)": lambda: self.client.run("generate", "cost", "seedance_2_0", "--prompt", "P"),
            "list_workflows": self.client.list_workflows,
            "get_workflow": lambda: self.client.get_workflow("reframe"),
            "account_status": self.client.account_status,
            "get_account_transactions": lambda: self.client.get_account_transactions(size=10),
            "estimate_cost": lambda: self.client.estimate_cost("seedance_2_0", "P", duration=15),
            "list_models": self.client.list_models,
            "get_model": lambda: self.client.get_model("seedance_2_0"),
            "get_job": lambda: self.client.get_job("job-1"),
            "list_jobs": self.client.list_jobs,
            "wait_for_job": lambda: self.client.wait_for_job("job-1", timeout_seconds=1, interval_seconds=1),
        }
        for label, call in calls.items():
            with self.subTest(call=label):
                self.assertClosed(call)
        with self.subTest(call="create_job"):
            self.assertClosed(lambda: self.client.create_job("seedance_2_0", "P"), reasons=None)
        self.assertEqual(self.egress, [])

    def test_https_send_is_refused_even_for_a_confirmed_status_request(self):
        transport = transport_mod.HttpsTransport(
            transport_mod.HiggsfieldApiCredentials("kid", "ksecret"), 30, facts=CONFIRMED_FACTS
        )
        request = HiggsfieldRestClient().build_status_request("r-1")
        error = self.assertClosed(lambda: transport.send(request), reasons=["provider_closed_no_https_connection: 'status'"])
        self.assertNotIn("ksecret", str(error))
        self.assertClosed(lambda: HiggsfieldRestClient(transport).get_status("r-1"), reasons=None)
        self.assertEqual(self.egress, [])

    def test_every_real_provider_method_is_refused(self):
        provider = HiggsfieldProvider(client=self.client)
        calls = {
            "list_models": provider.list_models,
            "get_model": lambda: provider.get_model("seedance_2_0"),
            "estimate_cost": lambda: provider.estimate_cost("seedance_2_0", "P", duration=15),
            "get_account_balance": provider.get_account_balance,
            "get_job": lambda: provider.get_job("job-1"),
            "wait_for_job": lambda: provider.wait_for_job("job-1", timeout_seconds=1, interval_seconds=1),
            "create_job": lambda: provider.create_job("seedance_2_0", "P", duration=15),
        }
        for label, call in calls.items():
            with self.subTest(method=label):
                with self.assertRaises(HiggsfieldError):
                    call()
        self.assertEqual(self.egress, [])

    def test_provider_closed_reasons_recognize_the_real_client_only(self):
        self.assertTrue(provider_closed_reasons(HiggsfieldProvider(client=self.client)))

        class SubClient(client_mod.HiggsfieldClient):
            pass

        self.assertTrue(provider_closed_reasons(HiggsfieldProvider(client=SubClient(command="fake-higgsfield-cli"))))
        self.assertEqual(provider_closed_reasons(MockHiggsfieldProvider()), [])
        self.assertEqual(provider_closed_reasons(mock.Mock(client=mock.Mock())), [])
        self.assertEqual(self.egress, [])

    def test_gate_blocks_the_real_provider_before_get_model(self):
        provider = HiggsfieldProvider(client=self.client)
        request = bind_request(GenerationRequest(
            **content_media(),
            request_id="egress-gate", job_type="seedance_2_0", prompt="P", duration=15, resolution="720p",
            aspect_ratio="9:16", approved=True,
            real_generation_authorization=video_005_authorization("egress-gate"),
        ))
        reached = []
        with mock.patch.object(client_mod.HiggsfieldClient, "run", lambda self, *a, **k: reached.append(a)), \
                mock.patch.object(provider, "get_model", side_effect=AssertionError("get_model reached")) as get_model:
            result = GenerationApprovalGate(provider).evaluate(request)
        get_model.assert_not_called()
        self.assertEqual(reached, [], "the Gate must not reach the client at all")
        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)
        self.assertTrue(any("Provider = CLOSED" in reason for reason in result.reasons), result.reasons)
        self.assertEqual(self.egress, [])

    def test_run_video_mission_with_the_default_chain_has_no_external_effect(self):
        import director

        aidirector = director.AIDirector()
        aidirector.higgsfield = self.client
        reached = []
        with tempfile.TemporaryDirectory() as tmp, isolated_director_state(tmp) as state, \
                mock.patch.object(client_mod.HiggsfieldClient, "run", lambda self, *a, **k: reached.append(a)), \
                mock.patch.object(HiggsfieldProvider, "get_model", side_effect=AssertionError("get_model reached")) as get_model:
            report = aidirector.run_video_mission(
                video_id=C.request_id, title="t", hook="h", objective="o", duration=C.duration, approved=True,
                real_generation_authorization=video_005_authorization(), interval_seconds=0,
            )
            created = sorted(path.name for path in state.rglob("*")) if state.exists() else []
        get_model.assert_not_called()
        self.assertEqual(reached, [], "run_video_mission() must not reach the client")
        self.assertEqual(report.approval_decision, GenerationApprovalDecision.BLOCKED)
        self.assertFalse(report.job_created)
        self.assertTrue(any("Provider = CLOSED" in reason for reason in report.approval_reasons), report.approval_reasons)
        self.assertNotIn("executed_requests.json", created)
        self.assertNotIn("consumed_authorizations.json", created)
        self.assertEqual(self.egress, [])


class TestEntryPoints(unittest.TestCase):
    """No module run as a script may reach a Higgsfield module, except the closed ones below."""

    def _modules(self):
        return {_module_name(_rel(path)): path for path in _application_files()}

    def _closure(self, start, modules, trees):
        seen, pending = {start}, [start]
        while pending:
            for _, names in _imports(trees[pending.pop()]):
                for name in names:
                    for candidate in modules:
                        if (name == candidate or name.startswith(candidate + ".")) and candidate not in seen:
                            seen.add(candidate)
                            pending.append(candidate)
        return seen

    def test_only_closed_entry_points_have_a_main_block_reaching_higgsfield(self):
        modules = self._modules()
        trees = {name: _tree(path) for name, path in modules.items()}
        reaching = {
            _rel(modules[name])
            for name, tree in trees.items()
            if _has_main_block(tree) and HIGGSFIELD_MODULE_NAMES & self._closure(name, modules, trees)
        }
        self.assertEqual(reaching, CLOSED_ENTRY_POINTS)

    def test_the_closure_follows_indirect_imports(self):
        modules = self._modules()
        trees = {name: _tree(path) for name, path in modules.items()}
        # agents.production_gate reaches the client only through agents.cost_engine.
        closure = self._closure("agents.production_gate", modules, trees)
        self.assertIn("agents.cost_engine", closure)
        self.assertIn("integrations.higgsfield.client", closure)
        self.assertNotIn("integrations.higgsfield.client", self._closure("scripts.architecture_audit", modules, trees))

    def test_former_cli_entry_points_have_no_main_block(self):
        for rel in FORMER_CLI_ENTRY_POINTS:
            with self.subTest(module=rel):
                self.assertFalse(_has_main_block(_tree(PROJECT_ROOT / rel)))


class TestEntryPointsRunUnderSentinels(unittest.TestCase):
    """Each closed entry point runs with every egress point replaced by a sentinel."""

    @contextlib.contextmanager
    def _sentinels(self):
        def refuse(attempts, label):
            def refused(*args, **kwargs):
                attempts.append(label)
                raise EgressAttempt(label)
            return refused

        with no_egress() as attempts, contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(client_mod.HiggsfieldClient, "run", refuse(attempts, "HiggsfieldClient.run"))
            )
            stack.enter_context(
                mock.patch.object(transport_mod.HttpsTransport, "send", refuse(attempts, "HttpsTransport.send"))
            )
            yield attempts

    @staticmethod
    def _load(rel):
        spec = importlib.util.spec_from_file_location(f"egress_closure_{Path(rel).stem}", PROJECT_ROOT / rel)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_sentinels_catch_every_egress_point(self):
        def raw_socket():
            with socket.socket() as raw:
                raw.connect(("192.0.2.1", 9))

        with self._sentinels() as attempts:
            calls = {
                "client read": lambda: client_mod.HiggsfieldClient(command="unused-cli").list_workflows(),
                "subprocess": lambda: subprocess.run(["unused-cli"]),
                "transport": lambda: transport_mod.HttpsTransport(
                    transport_mod.HiggsfieldApiCredentials("kid", "ksecret"), 30
                ).send(None),
                "https": lambda: http.client.HTTPSConnection("example.invalid"),
                "socket": lambda: socket.create_connection(("192.0.2.1", 9)),
                "raw socket": raw_socket,
            }
            for name, call in calls.items():
                with self.subTest(egress=name), self.assertRaises(EgressAttempt):
                    call()
        self.assertEqual(len(attempts), len(calls))

    def test_director_main_reports_the_provider_closed_without_any_egress(self):
        import director

        output = io.StringIO()
        with self._sentinels() as attempts, contextlib.redirect_stdout(output):
            director.main()
            result = director.AIDirector().check_higgsfield()
        self.assertEqual(attempts, [])
        self.assertIn("Higgsfield   : CLOSED", output.getvalue())
        self.assertEqual(result["provider"], "CLOSED")
        self.assertIs(result["connected"], False)

    def test_higgsfield_check_script_reports_the_provider_closed_without_any_egress(self):
        output = io.StringIO()
        with self._sentinels() as attempts, contextlib.redirect_stdout(output):
            result = self._load("scripts/higgsfield_check.py").main()
        self.assertEqual(attempts, [])
        self.assertEqual(result["provider"], "CLOSED")
        self.assertIn("Higgsfield   : CLOSED", output.getvalue())

    def test_demo_script_runs_without_any_egress(self):
        output = io.StringIO()
        with self._sentinels() as attempts, contextlib.redirect_stdout(output):
            results = self._load("scripts/demo_test.py").run_demo()
        self.assertEqual(attempts, [])
        self.assertTrue(results)


class TestWorkflowEntryPoints(unittest.TestCase):
    """Workflows run only allowlisted Python entry points and never the Higgsfield CLI."""

    @staticmethod
    def _run_blocks():
        for path in sorted((PROJECT_ROOT / ".github" / "workflows").glob("*.yml")):
            pending = [((), parse_workflow_yaml(path.read_text(encoding="utf-8")))]
            while pending:
                key, node = pending.pop()
                if isinstance(node, dict):
                    pending.extend(((*key, k), v) for k, v in node.items())
                elif isinstance(node, list):
                    pending.extend(((*key, i), v) for i, v in enumerate(node))
                elif isinstance(node, str) and key and key[-1] == "run":
                    yield path.name, node

    def test_run_blocks_only_invoke_allowlisted_python_targets_and_no_higgsfield_command(self):
        blocks = list(self._run_blocks())
        self.assertTrue(blocks)
        seen = set()
        for workflow, block in blocks:
            for match in re.finditer(r"\bpython(?:3)?(?:\.exe)?\s+(-m\s+\S+|\S+)", block):
                target = re.sub(r"\s+", " ", match.group(1))
                seen.add(target)
                self.assertIn(target, WORKFLOW_PYTHON_TARGETS, f"{workflow}: python {target}")
            self.assertIsNone(
                re.search(r"(?<![\w./-])higgsfield(?:\.cmd|\.ps1|\.exe)?(?![\w.-])", block),
                f"{workflow} runs the Higgsfield CLI",
            )
        self.assertEqual(seen, WORKFLOW_PYTHON_TARGETS)


if __name__ == "__main__":
    unittest.main()
