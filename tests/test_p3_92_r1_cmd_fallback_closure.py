"""
Tests -- Phase P3.92-R1 : fermeture de F-1 (repli cmd.exe).

P3.92 a démontré que, lorsque `HiggsfieldClient` ne résout pas
l'invocation directe Node.js (`_direct_invocation is None`) et que
`command` est un shim .cmd/.bat, `run()` lançait ce shim -- donc cmd.exe,
qui ré-interprète la ligne de commande. Un argument d'un verbe autorisé
(`model get <job_type>`, atteint par `GenerationApprovalGate.evaluate()`
même après un rejet de l'Identity Lock) pouvait alors enchaîner une
seconde commande (`& higgsfield generate create ...`), hors allowlist.

Méthode : faux shims dans un répertoire temporaire, `subprocess.run`
mocké ou gardé ; le seul processus réellement lancé (test de non-
exécution) serait un `echo` inoffensif. Aucun CLI Higgsfield, aucun
réseau, aucun crédit.
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
from integrations.higgsfield.client import HiggsfieldClient, _runs_through_cmd_exe
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.provider import HiggsfieldProvider

_FAKE_NPM_SHIM = (
    '@ECHO off\n'
    'endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  '
    '"%dp0%\\node_modules\\@higgsfield\\cli\\bin\\higgsfield.js"  %*\n'
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


@unittest.skipUnless(os.name == "nt", "cmd.exe n'existe que sous Windows.")
class TestCmdExeFallbackIsClosed(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.foreign_cmd = self.tmp / "foreign_shim.cmd"
        self.foreign_cmd.write_text("@echo FAKE %*\r\n", encoding="ascii")

    def _variants(self):
        (self.tmp / "foreign_shim.bat").write_text("@echo FAKE %*\r\n", encoding="ascii")
        base = str(self.foreign_cmd)
        return [base, base + ".", base + " ", base[:-4] + ".CMD", str(self.tmp / "foreign_shim.bat")]

    def test_fallback_path_is_detected(self):
        for command in self._variants():
            with self.subTest(command=command):
                client = HiggsfieldClient(command=command)
                self.assertIsNone(client._direct_invocation)
                self.assertTrue(_runs_through_cmd_exe(command))

    def test_every_read_only_call_is_refused_before_any_subprocess(self):
        for command in self._variants():
            client = HiggsfieldClient(command=command)
            for call in _READ_ONLY_CALLS:
                with self.subTest(command=command), patch("subprocess.run") as mock_run:
                    with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
                        call(client)
                    mock_run.assert_not_called()
                    self.assertTrue(ctx.exception.reasons[0].startswith("cmd_exe_fallback_refused"))

    def test_generative_verbs_stay_refused_by_the_runtime_lock_first(self):
        client = HiggsfieldClient(command=str(self.foreign_cmd))
        with patch("subprocess.run") as mock_run:
            with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
                client.run("generate", "create", "seedance_2_0", "--prompt", "x")
            self.assertTrue(ctx.exception.reasons[0].startswith("cli_verb_not_read_only"))
            with self.assertRaises(HiggsfieldRealGenerationDisabledError):
                client.create_job("seedance_2_0", "x", duration=5)
            mock_run.assert_not_called()

    def test_injection_payload_is_never_executed_by_cmd_exe(self):
        """Sans mock : si le repli était encore ouvert, cmd.exe exécuterait
        le `echo` injecté et créerait le marqueur (reproduction P3.92)."""

        marker = self.tmp / "injected.txt"
        client = HiggsfieldClient(command=str(self.foreign_cmd))
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            client.run("model", "get", _payload(marker))
        self.assertFalse(marker.exists())

    def test_injection_through_the_real_gate_path_spawns_nothing(self):
        marker = self.tmp / "injected_gate.txt"
        client = HiggsfieldClient(command=str(self.foreign_cmd))
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


@unittest.skipUnless(os.name == "nt", "Invocation directe spécifique à Windows.")
class TestReadOnlyOperationsStayFunctional(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        bin_dir = root / "node_modules" / "@higgsfield" / "cli" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "higgsfield.js").write_text("// fake entry\n", encoding="utf-8")
        (root / "node.exe").write_text("", encoding="utf-8")
        shim = root / "higgsfield.cmd"
        shim.write_text(_FAKE_NPM_SHIM, encoding="utf-8")
        self.client = HiggsfieldClient(command=str(shim))

    def test_npm_layout_executes_read_only_calls_via_node_never_cmd(self):
        self.assertIsNotNone(self.client._direct_invocation)
        for call in _READ_ONLY_CALLS:
            with self.subTest(), patch("subprocess.run", return_value=_Completed()) as mock_run:
                call(self.client)
                argv = mock_run.call_args.args[0]
                self.assertEqual(argv[:2], self.client._direct_invocation)
                self.assertTrue(argv[0].endswith("node.exe"))
                self.assertIs(mock_run.call_args.kwargs["shell"], False)

    def test_runtime_lock_unchanged_with_direct_invocation(self):
        with patch("subprocess.run") as mock_run:
            with self.assertRaises(HiggsfieldRealGenerationDisabledError):
                self.client.run("generate", "create", "seedance_2_0", "--prompt", "x")
            with self.assertRaises(HiggsfieldRealGenerationDisabledError):
                self.client.run("generate", "cost", "workflow", "reframe")
            with self.assertRaises(HiggsfieldRealGenerationDisabledError):
                self.client.create_job("seedance_2_0", "x")
            mock_run.assert_not_called()


class TestNonShimCommandsUnaffected(unittest.TestCase):
    def test_plain_executable_command_still_runs(self):
        client = HiggsfieldClient(command="fake-higgsfield-cli")
        with patch("subprocess.run", return_value=_Completed()) as mock_run:
            client.account_status()
        self.assertEqual(mock_run.call_args.args[0][0], "fake-higgsfield-cli")

    def test_cmd_suffix_is_not_special_off_windows(self):
        with patch("integrations.higgsfield.client.os.name", "posix"):
            self.assertFalse(_runs_through_cmd_exe("/opt/higgsfield.cmd"))
            client = HiggsfieldClient(command="/opt/higgsfield.cmd")
            with patch("subprocess.run", return_value=_Completed()) as mock_run:
                client.account_status()
            mock_run.assert_called_once()

    def test_detection_helper(self):
        with patch("integrations.higgsfield.client.os.name", "nt"):
            for command in ("a.cmd", "a.CMD", "a.bat", "a.Bat", "a.cmd.", "a.cmd ", "a.cmd. .", "C:/x y/h.cmd"):
                self.assertTrue(_runs_through_cmd_exe(command), command)
            for command in ("a.exe", "node", "a.cmdx", "a.js", "cmd"):
                self.assertFalse(_runs_through_cmd_exe(command), command)


if __name__ == "__main__":
    unittest.main()
