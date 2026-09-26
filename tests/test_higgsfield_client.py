"""
Tests — HiggsfieldClient (Phase C, MASTER PROMPT V2).

Tous les tests de ce fichier mockent `subprocess.run` : AUCUN appel
réseau, AUCUN appel réel au CLI Higgsfield, AUCUNE génération, AUCUN
crédit consommé. Objectif : vérifier la gestion des erreurs (CLI
introuvable, timeout, échec d'authentification, échec de commande,
sortie invalide) ainsi que la robustesse contre l'injection shell.
"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from integrations.higgsfield.client import HiggsfieldClient
from integrations.higgsfield.errors import (
    HiggsfieldAuthenticationError,
    HiggsfieldCLINotFoundError,
    HiggsfieldCommandError,
    HiggsfieldInvalidResponseError,
    HiggsfieldTimeoutError,
)


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestHiggsfieldClientRun(unittest.TestCase):

    def setUp(self):
        self.client = HiggsfieldClient(command="fake-higgsfield-cli")

    def test_run_uses_argument_list_never_shell(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _FakeCompletedProcess(stdout='{"ok": true}')

            self.client.run("account", "status")

            args, kwargs = mock_run.call_args
            self.assertIsInstance(args[0], list)
            self.assertFalse(kwargs.get("shell", False))

    def test_run_returns_parsed_json_on_success(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _FakeCompletedProcess(
                stdout='{"credits": 22.5}'
            )

            result = self.client.run("generate", "cost", "seedance_2_0")

            self.assertEqual(result, {"credits": 22.5})

    def test_run_returns_none_on_empty_stdout(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _FakeCompletedProcess(stdout="")

            result = self.client.run("workflow", "list")

            self.assertIsNone(result)

    def test_cli_not_found_raises_typed_error(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            with self.assertRaises(HiggsfieldCLINotFoundError):
                self.client.run("account", "status")

    def test_timeout_raises_typed_error(self):
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="higgsfield", timeout=120),
        ):
            with self.assertRaises(HiggsfieldTimeoutError):
                self.client.run("account", "status")

    def test_authentication_failure_raises_typed_error(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _FakeCompletedProcess(
                returncode=1,
                stderr="Error: not authenticated. Please run 'higgsfield auth login'.",
            )

            with self.assertRaises(HiggsfieldAuthenticationError):
                self.client.run("account", "status")

    def test_generic_command_failure_raises_typed_error(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _FakeCompletedProcess(
                returncode=2,
                stderr="unknown flag: --bogus",
            )

            with self.assertRaises(HiggsfieldCommandError) as ctx:
                self.client.run("workflow", "list", "--bogus")

            self.assertEqual(ctx.exception.exit_code, 2)

    def test_invalid_json_output_raises_typed_error(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _FakeCompletedProcess(
                stdout="not-json-at-all"
            )

            with self.assertRaises(HiggsfieldInvalidResponseError):
                self.client.run("account", "status")

    def test_typed_errors_are_runtimeerror_subclasses_for_v1_compat(self):
        # Le code V1 (agents/cost_engine.py) capture `except Exception`
        # génériquement : toute nouvelle erreur typée doit donc rester
        # attrapable de la même façon, sans aucune modification de V1.
        for error_cls in (
            HiggsfieldCLINotFoundError,
            HiggsfieldTimeoutError,
            HiggsfieldAuthenticationError,
            HiggsfieldCommandError,
            HiggsfieldInvalidResponseError,
        ):
            with self.subTest(error_cls=error_cls):
                self.assertTrue(issubclass(error_cls, RuntimeError))


class TestHiggsfieldClientReadOnlyMethods(unittest.TestCase):
    """Vérifie que les nouvelles méthodes construisent les bons arguments CLI."""

    def setUp(self):
        self.client = HiggsfieldClient(command="fake-higgsfield-cli")

    def _last_args(self, mock_run):
        return mock_run.call_args.args[0]

    def test_list_models_video_flag(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _FakeCompletedProcess(stdout="[]")
            self.client.list_models(video=True)
            self.assertIn("--video", self._last_args(mock_run))

    def test_get_model_builds_expected_command(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _FakeCompletedProcess(stdout="{}")
            self.client.get_model("seedance_2_0")
            args = self._last_args(mock_run)
            self.assertIn("model", args)
            self.assertIn("get", args)
            self.assertIn("seedance_2_0", args)

    def test_get_job_builds_expected_command(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _FakeCompletedProcess(stdout="{}")
            self.client.get_job("job-123")
            args = self._last_args(mock_run)
            self.assertEqual(args[-3:], ["generate", "get", "job-123"])

    def test_wait_for_job_never_calls_generate_create(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _FakeCompletedProcess(stdout="{}")
            self.client.wait_for_job("job-123", timeout_seconds=5, interval_seconds=1)
            args = self._last_args(mock_run)
            self.assertIn("wait", args)
            self.assertNotIn("create", args)

if __name__ == "__main__":
    unittest.main()
