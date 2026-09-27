"""
Tests — Phase P3.105 : résolution configurable de l'exécutable Higgsfield
CLI (F8-2).

Avant P3.105, `HiggsfieldClient()` utilisait un chemin codé en dur propre à
un compte Windows (`C:\\Users\\<user>\\AppData\\Roaming\\npm\\higgsfield.cmd`),
non configurable sans modifier les appelants de production.

Priorité désormais :
  1. `HiggsfieldClient(command=...)` explicite (non None) ;
  2. `HIGGSFIELD_CLI_PATH` (chemin absolu d'un fichier existant) ;
  3. `%APPDATA%\\npm\\higgsfield.cmd` (Windows uniquement).
Une source présente mais invalide ne retombe jamais sur la suivante.
Tous les contrôles P3.92 de `run()` restent appliqués ; un interpréteur de
commandes (cmd.exe, PowerShell) désigné comme CLI est refusé.

`subprocess.run` est systématiquement remplacé : aucun lancement réel du
CLI Higgsfield, aucun réseau, aucun `create_job()`, aucun crédit.
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

from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from integrations.higgsfield import client as client_mod
from integrations.higgsfield.client import HIGGSFIELD_CLI_ENV_VAR, HiggsfieldClient
from integrations.higgsfield.errors import (
    HiggsfieldAuthenticationError,
    HiggsfieldCLINotFoundError,
    HiggsfieldCommandError,
    HiggsfieldInvalidResponseError,
    HiggsfieldRealGenerationDisabledError,
    HiggsfieldTimeoutError,
)
from integrations.higgsfield.provider import HiggsfieldProvider

_FAKE_NPM_SHIM = (
    '@ECHO off\n'
    'endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  '
    '"%dp0%\\node_modules\\@higgsfield\\cli\\bin\\higgsfield.js"  %*\n'
)

_READ_ONLY_CALLS = (
    lambda c: c.account_status(),
    lambda c: c.list_workflows(),
    lambda c: c.list_models(),
)


class _Completed:
    returncode = 0
    stdout = "{}"
    stderr = ""


def _env(**values):
    """Environnement contrôlé : ni HIGGSFIELD_CLI_PATH ni APPDATA hérités."""

    env = {k: v for k, v in os.environ.items() if k not in (HIGGSFIELD_CLI_ENV_VAR, "APPDATA")}
    env.update({k: v for k, v in values.items() if v is not None})
    return patch.dict(os.environ, env, clear=True)


class _TmpCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.plain_cli = self.tmp / "higgsfield-cli.exe"
        self.plain_cli.write_text("", encoding="utf-8")

    def _npm_layout(self, root: Path, with_node_exe=True) -> Path:
        bin_dir = root / "node_modules" / "@higgsfield" / "cli" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "higgsfield.js").write_text("// fake entry\n", encoding="utf-8")
        if with_node_exe:
            (root / "node.exe").write_text("", encoding="utf-8")
        shim = root / "higgsfield.cmd"
        shim.write_text(_FAKE_NPM_SHIM, encoding="utf-8")
        return shim

    def assert_refused_without_process(self, client, error_type, reason_prefix=None):
        for call in _READ_ONLY_CALLS:
            with self.subTest(command=client.command), patch("subprocess.run") as mock_run:
                with self.assertRaises(error_type) as ctx:
                    call(client)
                mock_run.assert_not_called()
                if reason_prefix is not None:
                    self.assertTrue(ctx.exception.reasons[0].startswith(reason_prefix), ctx.exception.reasons)


class TestPriority(_TmpCase):
    def test_explicit_command_wins_over_environment_and_default(self):
        with _env(**{HIGGSFIELD_CLI_ENV_VAR: str(self.plain_cli), "APPDATA": str(self.tmp)}):
            client = HiggsfieldClient(command="fake-higgsfield-cli")
        self.assertEqual((client.command, client.command_source), ("fake-higgsfield-cli", "explicit"))

    def test_environment_wins_over_default(self):
        with _env(**{HIGGSFIELD_CLI_ENV_VAR: str(self.plain_cli), "APPDATA": str(self.tmp)}):
            client = HiggsfieldClient()
        self.assertEqual((client.command, client.command_source), (str(self.plain_cli), "environment"))
        self.assertIsNone(client.command_error)

    def test_default_is_derived_from_appdata_on_windows(self):
        with _env(APPDATA=str(self.tmp)), patch.object(client_mod.os, "name", "nt"):
            client = HiggsfieldClient()
        self.assertEqual(client.command, str(self.tmp / "npm" / "higgsfield.cmd"))
        self.assertEqual(client.command_source, "default")

    def test_no_user_specific_path_is_hard_coded(self):
        source = Path(client_mod.__file__).read_text(encoding="utf-8-sig")
        self.assertNotIn("C:\\Users\\", source)
        self.assertNotIn("AppData\\Roaming", source)


class TestValidConfiguration(_TmpCase):
    def test_explicit_valid_command_runs_mocked_with_shell_false(self):
        client = HiggsfieldClient(command=str(self.plain_cli))
        with patch("subprocess.run", return_value=_Completed()) as mock_run:
            client.account_status()
        argv = mock_run.call_args.args[0]
        self.assertEqual(argv[0], str(self.plain_cli))
        self.assertIs(mock_run.call_args.kwargs["shell"], False)

    def test_environment_valid_plain_executable_runs_mocked(self):
        with _env(**{HIGGSFIELD_CLI_ENV_VAR: str(self.plain_cli)}):
            client = HiggsfieldClient()
        with patch("subprocess.run", return_value=_Completed()) as mock_run:
            client.account_status()
        self.assertEqual(mock_run.call_args.args[0][0], str(self.plain_cli))

    def test_environment_npm_shim_uses_direct_node_invocation_never_cmd(self):
        shim = self._npm_layout(self.tmp / "npm")
        with _env(**{HIGGSFIELD_CLI_ENV_VAR: str(shim)}):
            client = HiggsfieldClient()
        self.assertIsNotNone(client._direct_invocation)
        with patch("subprocess.run", return_value=_Completed()) as mock_run:
            client.account_status()
        argv = mock_run.call_args.args[0]
        self.assertTrue(argv[0].endswith("node.exe"))
        self.assertTrue(argv[1].endswith("higgsfield.js"))
        self.assertIs(mock_run.call_args.kwargs["shell"], False)

    def test_default_npm_shim_under_appdata_uses_direct_node_invocation(self):
        self._npm_layout(self.tmp / "npm")
        with _env(APPDATA=str(self.tmp)):
            client = HiggsfieldClient()
        self.assertEqual(client.command_source, "default")
        self.assertIsNotNone(client._direct_invocation)

    def test_construction_never_launches_a_process(self):
        with patch("subprocess.run") as mock_run, patch("subprocess.Popen") as mock_popen:
            HiggsfieldClient()
            with _env(**{HIGGSFIELD_CLI_ENV_VAR: str(self.plain_cli)}):
                HiggsfieldClient()
        mock_run.assert_not_called()
        mock_popen.assert_not_called()


class TestAbsentConfiguration(_TmpCase):
    def test_no_environment_no_appdata_is_unconfigured_and_refused(self):
        with _env(), patch.object(client_mod.os, "name", "nt"):
            client = HiggsfieldClient()
        self.assertIsNone(client.command)
        self.assertEqual(client.command_source, "default")
        self.assertIn(HIGGSFIELD_CLI_ENV_VAR, client.command_error)
        self.assert_refused_without_process(client, HiggsfieldCLINotFoundError)

    def test_relative_appdata_gives_no_default(self):
        with _env(APPDATA="relative\\dir"), patch.object(client_mod.os, "name", "nt"):
            client = HiggsfieldClient()
        self.assertIsNone(client.command)

    def test_no_default_outside_windows(self):
        with _env(APPDATA=str(self.tmp)), patch.object(client_mod.os, "name", "posix"):
            client = HiggsfieldClient()
        self.assertIsNone(client.command)
        self.assert_refused_without_process(client, HiggsfieldCLINotFoundError)


class TestInvalidConfigurationHasNoFallback(_TmpCase):
    def setUp(self):
        super().setUp()
        # Un défaut parfaitement valide existe : il ne doit JAMAIS servir de repli.
        self._npm_layout(self.tmp / "npm")

    def test_invalid_environment_values_never_fall_back_to_default(self):
        directory = self.tmp / "a_directory"
        directory.mkdir()
        values = ["", "   ", "higgsfield.cmd", "npm\\higgsfield.cmd",
                  str(self.tmp / "missing.exe"), str(directory)]
        for value in values:
            with self.subTest(value=value):
                with _env(**{HIGGSFIELD_CLI_ENV_VAR: value, "APPDATA": str(self.tmp)}):
                    client = HiggsfieldClient()
                self.assertIsNone(client.command)
                self.assertEqual(client.command_source, "environment")
                self.assertIsNone(client._direct_invocation)
                self.assert_refused_without_process(client, HiggsfieldCLINotFoundError)

    def test_invalid_explicit_values_never_fall_back(self):
        for value in ("", "   ", "higgs\x00field", 5):
            with self.subTest(value=value):
                with _env(**{HIGGSFIELD_CLI_ENV_VAR: str(self.plain_cli), "APPDATA": str(self.tmp)}):
                    client = HiggsfieldClient(command=value)
                self.assertIsNone(client.command)
                self.assertEqual(client.command_source, "explicit")
                self.assert_refused_without_process(client, HiggsfieldCLINotFoundError)

    def test_refused_interpreter_never_falls_back(self):
        with _env(**{HIGGSFIELD_CLI_ENV_VAR: str(self.plain_cli), "APPDATA": str(self.tmp)}):
            client = HiggsfieldClient(command="cmd.exe")
        self.assertEqual(client.command, "cmd.exe")
        self.assert_refused_without_process(
            client, HiggsfieldRealGenerationDisabledError, "shell_interpreter_refused"
        )


class TestInterpretersRefused(_TmpCase):
    def test_cmd_exe_and_equivalents_refused_explicitly(self):
        comspec = os.environ.get("ComSpec", r"C:\Windows\System32\cmd.exe")
        for command in ("cmd.exe", "CMD.EXE", "cmd", "cmd.exe.", "cmd.exe ", comspec,
                        "powershell.exe", "pwsh", r"C:\x\PowerShell.EXE"):
            with self.subTest(command=command):
                self.assert_refused_without_process(
                    HiggsfieldClient(command=command),
                    HiggsfieldRealGenerationDisabledError,
                    "shell_interpreter_refused",
                )

    def test_cmd_exe_refused_through_environment(self):
        fake_cmd = self.tmp / "cmd.exe"
        fake_cmd.write_text("", encoding="utf-8")
        with _env(**{HIGGSFIELD_CLI_ENV_VAR: str(fake_cmd)}):
            client = HiggsfieldClient()
        self.assertEqual(client.command_source, "environment")
        self.assert_refused_without_process(
            client, HiggsfieldRealGenerationDisabledError, "shell_interpreter_refused"
        )

    def test_node_cmd_refused_explicitly_and_through_environment(self):
        node_cmd = self.tmp / "node.cmd"
        node_cmd.write_text("@echo FAKE %*\r\n", encoding="ascii")
        explicit = HiggsfieldClient(command=str(node_cmd))
        with _env(**{HIGGSFIELD_CLI_ENV_VAR: str(node_cmd)}):
            configured = HiggsfieldClient()
        for client in (explicit, configured):
            self.assertIsNone(client._direct_invocation)
            self.assert_refused_without_process(
                client, HiggsfieldRealGenerationDisabledError, "cmd_exe_fallback_refused"
            )

    def test_node_cmd_on_path_refused_for_configured_shim(self):
        # P3.92-R2 : sans node.exe à côté du shim, `shutil.which` peut
        # renvoyer un node.cmd -- l'invocation directe est alors refusée.
        shim = self._npm_layout(self.tmp / "npm", with_node_exe=False)
        with _env(**{HIGGSFIELD_CLI_ENV_VAR: str(shim)}), \
                patch.object(client_mod.shutil, "which", return_value=str(self.tmp / "node.cmd")):
            client = HiggsfieldClient()
        self.assertIsNotNone(client._direct_invocation)
        self.assert_refused_without_process(
            client, HiggsfieldRealGenerationDisabledError, "direct_invocation_interpreter_refused"
        )

    def test_foreign_cmd_shim_through_environment_refused(self):
        foreign = self.tmp / "foreign_shim.cmd"
        foreign.write_text("@echo FAKE %*\r\n", encoding="ascii")
        with _env(**{HIGGSFIELD_CLI_ENV_VAR: str(foreign)}):
            client = HiggsfieldClient()
        self.assert_refused_without_process(
            client, HiggsfieldRealGenerationDisabledError, "cmd_exe_fallback_refused"
        )


class TestRuntimeLockUnchanged(_TmpCase):
    def test_runtime_lock_is_checked_first_whatever_the_configuration(self):
        with _env():
            unconfigured = HiggsfieldClient(command="")
        clients = (unconfigured, HiggsfieldClient(command="cmd.exe"), HiggsfieldClient(command=str(self.plain_cli)))
        for client in clients:
            with self.subTest(command=client.command), patch("subprocess.run") as mock_run:
                with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
                    client.run("generate", "create", "seedance_2_0", "--prompt", "x")
                self.assertTrue(ctx.exception.reasons[0].startswith("cli_verb_not_read_only"))
                with self.assertRaises(HiggsfieldRealGenerationDisabledError):
                    client.create_job("seedance_2_0", "x", duration=5)
                mock_run.assert_not_called()


# ----------------------------------------------------------------------
# P3.105-STEP-3 -- flux NTFS / préfixes de namespace, normalisation OSError
# ----------------------------------------------------------------------


def _request(request_id="p3105-step3"):
    return GenerationRequest(
        request_id=request_id, job_type="seedance_2_0", prompt="p", duration=5,
        resolution="720p", aspect_ratio="9:16", approved=True,
        real_generation_authorization=RealGenerationAuthorization(
            request_id=request_id, authorized_by_human=True
        ),
    )


class TestAlternateDataStreamPathsRefused(_TmpCase):
    def setUp(self):
        super().setUp()
        self._npm_layout(self.tmp / "npm")  # défaut valide : jamais un repli
        self.node_cmd = self.tmp / "node.cmd"
        self.node_cmd.write_text("@echo FAKE %*\r\n", encoding="ascii")
        self.comspec = os.environ.get("ComSpec", r"C:\Windows\System32\cmd.exe")

    def _ads_variants(self, target: Path):
        base = str(target)
        return [
            base + "::$DATA",
            base + "::$data",
            base + ":stream",
            base + ":stream:$DATA",
            base.replace("\\", "/") + "::$DATA",
            str(target.parent) + "::$INDEX_ALLOCATION\\" + target.name,
            "\\\\?\\" + base,
            "\\\\.\\" + base,
            "\\\\?\\" + base + "::$DATA",
        ]

    def test_precondition_ads_form_is_seen_as_an_existing_file(self):
        # Le résiduel P3.105 : cette forme passait `is_file()`.
        self.assertTrue(Path(str(self.plain_cli) + "::$DATA").is_file())

    def test_environment_ads_and_namespace_forms_refused_without_fallback(self):
        targets = (self.plain_cli, Path(self.comspec), self.node_cmd, self.tmp / "npm" / "higgsfield.cmd")
        for target in targets:
            for value in self._ads_variants(target):
                with self.subTest(value=value):
                    with _env(**{HIGGSFIELD_CLI_ENV_VAR: value, "APPDATA": str(self.tmp)}):
                        client = HiggsfieldClient()
                    self.assertIsNone(client.command)
                    self.assertEqual(client.command_source, "environment")
                    self.assertIn("not allowed", client.command_error)
                    self.assertIsNone(client._direct_invocation)
                    self.assert_refused_without_process(client, HiggsfieldCLINotFoundError)

    def test_explicit_ads_forms_refused_including_cmd_and_node_cmd(self):
        values = [
            self.comspec + "::$DATA",
            self.comspec.upper() + "::$DATA",
            "cmd.exe::$DATA",
            "CMD.EXE:x",
            str(self.node_cmd) + "::$DATA",
            str(self.node_cmd).upper() + "::$data",
            "node.cmd::$DATA",
            str(self.plain_cli) + ":stream",
            "\\\\?\\" + self.comspec,
        ]
        for value in values:
            with self.subTest(value=value):
                with _env(**{HIGGSFIELD_CLI_ENV_VAR: str(self.plain_cli), "APPDATA": str(self.tmp)}):
                    client = HiggsfieldClient(command=value)
                self.assertIsNone(client.command)
                self.assertEqual(client.command_source, "explicit")
                self.assert_refused_without_process(client, HiggsfieldCLINotFoundError)

    def test_default_under_ads_appdata_is_refused(self):
        with _env(APPDATA=str(self.tmp) + "::$DATA"), patch.object(client_mod.os, "name", "nt"):
            client = HiggsfieldClient()
        self.assertIsNone(client.command)
        self.assertEqual(client.command_source, "default")

    def test_normal_windows_paths_still_accepted(self):
        for value in (str(self.plain_cli), str(self.plain_cli).replace("\\", "/")):
            with self.subTest(value=value):
                with _env(**{HIGGSFIELD_CLI_ENV_VAR: value}):
                    client = HiggsfieldClient()
                self.assertEqual((client.command, client.command_source), (value, "environment"))
                with patch("subprocess.run", return_value=_Completed()) as mock_run:
                    client.account_status()
                self.assertEqual(mock_run.call_args.args[0][:2], [value, "--json"])
                self.assertIs(mock_run.call_args.kwargs["shell"], False)
        for value in ("fake-higgsfield-cli", "\\\\server\\share\\higgsfield.exe", str(self.plain_cli)):
            with self.subTest(value=value):
                self.assertEqual(HiggsfieldClient(command=value).command, value)

    def test_relative_environment_path_still_refused(self):
        with _env(**{HIGGSFIELD_CLI_ENV_VAR: "higgsfield-cli.exe", "APPDATA": str(self.tmp)}):
            client = HiggsfieldClient()
        self.assertIsNone(client.command)
        self.assertIn("absolute", client.command_error)

    def test_ads_env_through_real_gate_is_a_structured_refusal(self):
        # Avant STEP-3 : OSError brut levé par gate.evaluate().
        with _env(**{HIGGSFIELD_CLI_ENV_VAR: str(self.plain_cli) + "::$DATA"}):
            gate = GenerationApprovalGate(HiggsfieldProvider(client=HiggsfieldClient()))
        with patch("subprocess.run") as mock_run:
            decision = gate.evaluate(_request()).decision
        mock_run.assert_not_called()
        self.assertNotEqual(decision, GenerationApprovalDecision.APPROVED)


class TestLaunchOSErrorNormalization(_TmpCase):
    def setUp(self):
        super().setUp()
        self.client = HiggsfieldClient(command=str(self.plain_cli))

    def _run_with(self, side_effect=None, return_value=None):
        with patch("subprocess.run", side_effect=side_effect, return_value=return_value) as mock_run:
            try:
                self.client.account_status()
            finally:
                self.assertEqual(mock_run.call_count, 1)

    def test_missing_file_still_cli_not_found(self):
        original = FileNotFoundError(2, "not found")
        with self.assertRaises(HiggsfieldCLINotFoundError) as ctx:
            self._run_with(side_effect=original)
        self.assertIs(ctx.exception.__cause__, original)

    def test_launch_refusals_become_command_errors_not_not_found(self):
        refusals = [
            OSError(22, "bad exe format", None, 193),
            OSError(22, "invalid name", None, 123),
            PermissionError(13, "access denied"),
            IsADirectoryError(21, "is a directory"),
            OSError(5, "I/O error"),
        ]
        for original in refusals:
            with self.subTest(error=repr(original)):
                with self.assertRaises(HiggsfieldCommandError) as ctx:
                    self._run_with(side_effect=original)
                self.assertNotIsInstance(ctx.exception, HiggsfieldCLINotFoundError)
                self.assertIsNone(ctx.exception.exit_code)
                self.assertIs(ctx.exception.__cause__, original)
                self.assertIn(str(self.plain_cli), str(ctx.exception))

    def test_winerror_code_is_kept_in_the_message(self):
        with self.assertRaises(HiggsfieldCommandError) as ctx:
            self._run_with(side_effect=OSError(22, "bad exe format", None, 193))
        if os.name == "nt":
            self.assertIn("193", str(ctx.exception))

    def test_timeout_still_timeout_error(self):
        with self.assertRaises(HiggsfieldTimeoutError):
            self._run_with(side_effect=subprocess.TimeoutExpired(cmd="x", timeout=1))

    def test_exit_code_auth_and_json_errors_unchanged(self):
        class _Failed:
            returncode = 3
            stdout = ""
            stderr = "boom"

        class _Auth(_Failed):
            stderr = "Not authenticated, please run auth login"

        class _NotJson(_Completed):
            stdout = "not json"

        with self.assertRaises(HiggsfieldCommandError) as ctx:
            self._run_with(return_value=_Failed())
        self.assertEqual(ctx.exception.exit_code, 3)
        with self.assertRaises(HiggsfieldAuthenticationError):
            self._run_with(return_value=_Auth())
        with self.assertRaises(HiggsfieldInvalidResponseError):
            self._run_with(return_value=_NotJson())

    def test_runtime_lock_refusal_is_never_normalized(self):
        with patch("subprocess.run", side_effect=OSError(22, "x", None, 193)) as mock_run:
            with self.assertRaises(HiggsfieldRealGenerationDisabledError):
                self.client.run("generate", "create", "seedance_2_0", "--prompt", "x")
        mock_run.assert_not_called()

    def test_launch_refusal_through_real_gate_is_a_structured_refusal(self):
        gate = GenerationApprovalGate(HiggsfieldProvider(client=self.client))
        with patch("subprocess.run", side_effect=OSError(22, "bad exe format", None, 193)):
            decision = gate.evaluate(_request()).decision
        self.assertNotEqual(decision, GenerationApprovalDecision.APPROVED)


if __name__ == "__main__":
    unittest.main()
