"""
Tests -- Phase P3.92-R2 : fermeture de F-1bis (interpréteur `node.cmd`).

La validation P3.92 sur l'état R1 a démontré que `shutil.which("node")`
suit PATHEXT : un `node.cmd`/`node.bat` placé plus tôt sur le PATH devient
l'interpréteur de l'invocation « directe » (`_direct_invocation[0]`). Le
verrou R1 ne portait que sur le cas `_direct_invocation is None` : cmd.exe
était donc lancé quand même et un argument d'un verbe autorisé (`model get
<job_type>`, atteint par `GenerationApprovalGate.evaluate()`) pouvait
enchaîner une seconde commande.

Méthode : disposition npm factice et faux `node.cmd` dans un répertoire
temporaire placé en tête du PATH ; `subprocess.run` mocké ou espionné ; le
seul processus qui pourrait être lancé en cas de régression est un `echo`
inoffensif. Aucune installation réelle de Node/Higgsfield n'est utilisée.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.executed_request_store import FileExecutedRequestStore
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
)
from agents.release_candidate_identity_lock import (
    VIDEO_005_RELEASE_CANDIDATE,
    ReleaseCandidateIdentityLock,
)
from integrations.higgsfield.client import HiggsfieldClient, _is_node_exe
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.provider import HiggsfieldProvider

_FAKE_NPM_SHIM = (
    '@ECHO off\n'
    '"%_prog%"  "%dp0%\\node_modules\\@higgsfield\\cli\\bin\\higgsfield.js" %*\n'
)

_READ_ONLY_CALLS = (
    lambda c: c.account_status(),
    lambda c: c.list_workflows(),
    lambda c: c.get_workflow("reframe"),
    lambda c: c.list_models(),
    lambda c: c.get_model("seedance_2_0"),
    lambda c: c.estimate_cost("seedance_2_0", "p", duration=5),
    lambda c: c.get_account_transactions(size=10),
    lambda c: c.get_job("job-1"),
    lambda c: c.list_jobs(),
    lambda c: c.wait_for_job("job-1", timeout_seconds=1, interval_seconds=1),
)


class _Completed:
    returncode = 0
    stdout = "{}"
    stderr = ""


def _payload(marker: Path) -> str:
    # En production réelle, `echo ...` serait `higgsfield generate create ...`.
    return f'x" & echo INJECTED>{marker} & rem '


@unittest.skipUnless(os.name == "nt", "PATHEXT / cmd.exe n'existent que sous Windows.")
class TestNodeWrapperOnPathIsRefused(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        npm = self.tmp / "npm"
        bin_dir = npm / "node_modules" / "@higgsfield" / "cli" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "higgsfield.js").write_text("// fake entry\n", encoding="utf-8")
        self.shim = npm / "higgsfield.cmd"  # pas de node.exe fourni : shutil.which est utilisé
        self.shim.write_text(_FAKE_NPM_SHIM, encoding="utf-8")
        self.path_dir = self.tmp / "pathbin"
        self.path_dir.mkdir()

    def _client_with_node(self, filename: str) -> HiggsfieldClient:
        (self.path_dir / filename).write_text("@echo FAKE-NODE %*\r\n", encoding="ascii")
        with patch.dict(os.environ, {"PATH": str(self.path_dir) + os.pathsep + os.environ.get("PATH", "")}):
            return HiggsfieldClient(command=str(self.shim))

    def test_node_resolves_to_a_wrapper(self):
        for filename in ("node.cmd", "node.bat"):
            with self.subTest(filename=filename):
                client = self._client_with_node(filename)
                self.assertIsNotNone(client._direct_invocation)
                self.assertEqual(Path(client._direct_invocation[0]).name.lower(), filename)

    def test_every_call_is_refused_before_any_subprocess(self):
        for filename in ("node.cmd", "node.bat"):
            client = self._client_with_node(filename)
            for call in _READ_ONLY_CALLS:
                with self.subTest(filename=filename), patch("subprocess.run") as mock_run:
                    with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
                        call(client)
                    mock_run.assert_not_called()
                    self.assertTrue(
                        ctx.exception.reasons[0].startswith("direct_invocation_interpreter_refused")
                    )

    def test_generative_attempts_stay_refused(self):
        client = self._client_with_node("node.cmd")
        with patch("subprocess.run") as mock_run:
            with self.assertRaises(HiggsfieldRealGenerationDisabledError):
                client.run("generate", "create", "seedance_2_0", "--prompt", "x")
            with self.assertRaises(HiggsfieldRealGenerationDisabledError):
                client.run("model", "get", _payload(self.tmp / "m.txt"))
            with self.assertRaises(HiggsfieldRealGenerationDisabledError):
                client.create_job("seedance_2_0", "x", duration=5)
            mock_run.assert_not_called()

    def test_injection_payload_is_never_executed(self):
        """Sans mock : en cas de régression, cmd.exe exécuterait l'`echo`
        injecté et créerait le marqueur (reproduction P3.92)."""

        marker = self.tmp / "injected.txt"
        client = self._client_with_node("node.cmd")
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            client.run("model", "get", _payload(marker))
        self.assertFalse(marker.exists())

    def test_injection_through_the_real_gate_path_spawns_nothing(self):
        marker = self.tmp / "injected_gate.txt"
        client = self._client_with_node("node.cmd")
        gate = GenerationApprovalGate(
            HiggsfieldProvider(client=client),
            executed_request_store=FileExecutedRequestStore(self.tmp / "state" / "executed_requests.json"),
            identity_lock=ReleaseCandidateIdentityLock(VIDEO_005_RELEASE_CANDIDATE),
        )
        request = GenerationRequest(request_id="005", job_type=_payload(marker), prompt="p")
        with patch("subprocess.run", wraps=subprocess.run) as spy:
            decision = gate.evaluate(request).decision
        spy.assert_not_called()
        self.assertFalse(marker.exists())
        self.assertNotEqual(decision, GenerationApprovalDecision.APPROVED)

    def test_real_node_exe_on_path_keeps_read_only_calls_working(self):
        client = self._client_with_node("node.exe")
        self.assertEqual(Path(client._direct_invocation[0]).name.lower(), "node.exe")
        for call in _READ_ONLY_CALLS:
            with self.subTest(), patch("subprocess.run", return_value=_Completed()) as mock_run:
                call(client)
                self.assertEqual(mock_run.call_args.args[0][:2], client._direct_invocation)
                self.assertIs(mock_run.call_args.kwargs["shell"], False)

    def test_f1_cmd_fallback_stays_closed(self):
        foreign = self.tmp / "foreign.cmd"
        foreign.write_text("@echo FAKE %*\r\n", encoding="ascii")
        client = HiggsfieldClient(command=str(foreign))
        self.assertIsNone(client._direct_invocation)
        with patch("subprocess.run") as mock_run:
            with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
                client.account_status()
            mock_run.assert_not_called()
        self.assertTrue(ctx.exception.reasons[0].startswith("cmd_exe_fallback_refused"))


class TestNodeExeAllowlist(unittest.TestCase):
    def test_only_node_exe_is_accepted(self):
        for executable in ("node.exe", "NODE.EXE", "C:/x y/node.exe", "C:\\n\\node.exe.", "node.exe "):
            self.assertTrue(_is_node_exe(executable), executable)
        for executable in ("node.cmd", "node.bat", "node.CMD", "node.com", "node", "cmd.exe",
                           "powershell.exe", "node.js", "node.exe.cmd", "notnode.exe", ""):
            self.assertFalse(_is_node_exe(executable), executable)


if __name__ == "__main__":
    unittest.main()
