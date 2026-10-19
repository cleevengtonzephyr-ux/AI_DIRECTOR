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
Tous les contrôles P3.92 restent appliqués par la validation pure
(`build_argv()`) ; un interpréteur de commandes (cmd.exe, PowerShell)
désigné comme CLI est refusé.

Provider = CLOSED : même une CLI valide n'est jamais lancée -- `run()`
valide puis refuse toujours. Les anciens tests de normalisation des erreurs
de lancement (OSError, timeout, code de sortie) n'ont plus d'objet : ils sont
remplacés par la vérification qu'aucun lancement n'est tenté et que le refus
de fermeture n'est jamais converti en erreur de commande.

Chaque test tourne sous `no_egress()`, qui enregistre et refuse tout
lancement de processus ou toute connexion (l'enregistrement doit rester
vide) : aucun CLI Higgsfield, aucun réseau, aucun `create_job()`, aucun
crédit.
"""

import os
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
    HiggsfieldCLINotFoundError,
    HiggsfieldCommandError,
    HiggsfieldRealGenerationDisabledError,
)
from integrations.higgsfield.provider import HiggsfieldProvider
from tests.provider_closure_helpers import NoEgressTestCase

PROVIDER_CLOSED = "provider_closed_no_cli_process"

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


def _env(**values):
    """Environnement contrôlé : ni HIGGSFIELD_CLI_PATH ni APPDATA hérités."""

    env = {k: v for k, v in os.environ.items() if k not in (HIGGSFIELD_CLI_ENV_VAR, "APPDATA")}
    env.update({k: v for k, v in values.items() if v is not None})
    return patch.dict(os.environ, env, clear=True)


class _TmpCase(NoEgressTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
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
            with self.subTest(command=client.command):
                with self.assertRaises(error_type) as ctx:
                    call(client)
                if reason_prefix is not None:
                    self.assertTrue(ctx.exception.reasons[0].startswith(reason_prefix), ctx.exception.reasons)
        with self.assertRaises(error_type):
            client.build_argv("account", "status")
        self.assertEqual(self.egress, [])

    def assert_closed_after_valid_argv(self, client, expected_prefix):
        """Configuration valide : argv construit (pur), puis `run()` refuse sans processus."""

        self.assertEqual(client.build_argv("account", "status")[:len(expected_prefix)], expected_prefix)
        for call in _READ_ONLY_CALLS:
            with self.subTest(command=client.command):
                with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
                    call(client)
                self.assertEqual(ctx.exception.reasons, [PROVIDER_CLOSED])
        self.assertEqual(self.egress, [])


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
    def test_explicit_valid_command_builds_its_argv_and_is_closed(self):
        client = HiggsfieldClient(command=str(self.plain_cli))
        self.assert_closed_after_valid_argv(client, [str(self.plain_cli), "--json"])

    def test_environment_valid_plain_executable_builds_its_argv_and_is_closed(self):
        with _env(**{HIGGSFIELD_CLI_ENV_VAR: str(self.plain_cli)}):
            client = HiggsfieldClient()
        self.assert_closed_after_valid_argv(client, [str(self.plain_cli), "--json"])

    def test_environment_npm_shim_targets_direct_node_invocation_never_cmd(self):
        shim = self._npm_layout(self.tmp / "npm")
        with _env(**{HIGGSFIELD_CLI_ENV_VAR: str(shim)}):
            client = HiggsfieldClient()
        self.assertIsNotNone(client._direct_invocation)
        argv = client.build_argv("account", "status")
        self.assertTrue(argv[0].endswith("node.exe"))
        self.assertTrue(argv[1].endswith("higgsfield.js"))
        self.assert_closed_after_valid_argv(client, [*client._direct_invocation, "--json"])

    def test_default_npm_shim_under_appdata_uses_direct_node_invocation(self):
        self._npm_layout(self.tmp / "npm")
        with _env(APPDATA=str(self.tmp)):
            client = HiggsfieldClient()
        self.assertEqual(client.command_source, "default")
        self.assertIsNotNone(client._direct_invocation)

    def test_construction_never_launches_a_process(self):
        HiggsfieldClient()
        with _env(**{HIGGSFIELD_CLI_ENV_VAR: str(self.plain_cli)}):
            HiggsfieldClient()
        self.assertEqual(self.egress, [])


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
            with self.subTest(command=client.command):
                with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
                    client.run("generate", "create", "seedance_2_0", "--prompt", "x")
                self.assertTrue(ctx.exception.reasons[0].startswith("cli_verb_not_read_only"))
                with self.assertRaises(HiggsfieldRealGenerationDisabledError):
                    client.create_job("seedance_2_0", "x", duration=5)
        self.assertEqual(self.egress, [])


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
                self.assert_closed_after_valid_argv(client, [value, "--json"])
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
        decision = gate.evaluate(_request()).decision
        self.assertEqual(self.egress, [])
        self.assertNotEqual(decision, GenerationApprovalDecision.APPROVED)


class TestNoLaunchIsAttemptedForAValidCli(_TmpCase):
    """Remplace la normalisation P3.105-STEP-3 des OSError de lancement :
    Provider = CLOSED, aucun lancement n'est tenté, donc aucune erreur de
    lancement ne peut survenir ni être normalisée."""

    def setUp(self):
        super().setUp()
        self.client = HiggsfieldClient(command=str(self.plain_cli))

    def test_valid_cli_read_is_closed_never_a_command_or_not_found_error(self):
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
            self.client.account_status()
        self.assertEqual(ctx.exception.reasons, [PROVIDER_CLOSED])
        self.assertNotIsInstance(ctx.exception, (HiggsfieldCommandError, HiggsfieldCLINotFoundError))
        self.assertIsNone(ctx.exception.__cause__)
        self.assertEqual(self.egress, [])

    def test_a_launch_failure_would_be_unreachable(self):
        # Si un lancement était encore tenté, ce Popen piégé serait appelé et
        # sa OSError apparaîtrait (normalisée ou non) : rien de tel.
        with patch("subprocess.Popen", side_effect=OSError(22, "bad exe format", None, 193)) as popen:
            with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
                self.client.account_status()
        popen.assert_not_called()
        self.assertEqual(ctx.exception.reasons, [PROVIDER_CLOSED])

    def test_runtime_lock_refusal_is_never_normalized(self):
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
            self.client.run("generate", "create", "seedance_2_0", "--prompt", "x")
        self.assertTrue(ctx.exception.reasons[0].startswith("cli_verb_not_read_only"))
        self.assertEqual(self.egress, [])

    def test_valid_cli_through_real_gate_is_blocked_before_any_provider_call(self):
        provider = HiggsfieldProvider(client=self.client)
        gate = GenerationApprovalGate(provider)
        with patch.object(provider, "get_model", side_effect=AssertionError("get_model reached")) as get_model:
            result = gate.evaluate(_request())
        get_model.assert_not_called()
        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)
        self.assertTrue(any("Provider = CLOSED" in reason for reason in result.reasons), result.reasons)
        self.assertEqual(self.egress, [])


if __name__ == "__main__":
    unittest.main()
