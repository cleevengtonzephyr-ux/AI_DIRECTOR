"""
Tests — HiggsfieldClient (Phase C, MASTER PROMPT V2), Provider = CLOSED.

Provider = CLOSED : `run()` ne lance plus aucun processus, pas même une
commande en lecture seule. Les anciens tests de gestion d'erreurs du
processus (timeout, authentification, code de sortie, JSON invalide) n'ont
plus d'objet : ce chemin n'existe plus. Ils sont remplacés par :
- la construction d'argv, vérifiée avec la fonction pure `build_argv()` /
  `build_cli_argv()` (liste d'arguments séparés, jamais une chaîne shell) ;
- le refus typé de `run()` et de chaque lecture, sans aucun processus ;
- le refus typé d'une CLI non configurée, sans aucun processus.

Tous les tests tournent sous `no_egress()` : tout lancement de processus ou
toute connexion serait enregistré et refusé, et l'enregistrement doit rester
vide. AUCUN appel réseau, AUCUN appel au CLI, AUCUN crédit consommé.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from integrations.higgsfield.client import HiggsfieldClient, build_cli_argv
from integrations.higgsfield.errors import (
    HiggsfieldAuthenticationError,
    HiggsfieldCLINotFoundError,
    HiggsfieldCommandError,
    HiggsfieldInvalidResponseError,
    HiggsfieldRealGenerationDisabledError,
    HiggsfieldTimeoutError,
)
from tests.provider_closure_helpers import NoEgressTestCase

PROVIDER_CLOSED = "provider_closed_no_cli_process"


class TestHiggsfieldClientRun(NoEgressTestCase, unittest.TestCase):

    def setUp(self):
        super().setUp()
        self.client = HiggsfieldClient(command="fake-higgsfield-cli")

    def test_argv_is_an_argument_list_never_a_shell_string(self):
        argv = self.client.build_argv("model", "get", "seedance_2_0 & higgsfield generate create")

        self.assertIsInstance(argv, list)
        self.assertTrue(all(isinstance(arg, str) for arg in argv))
        self.assertEqual(
            argv,
            ["fake-higgsfield-cli", "--json", "model", "get", "seedance_2_0 & higgsfield generate create"],
        )

    def test_build_cli_argv_is_pure_and_matches_the_client(self):
        argv = build_cli_argv(
            ("generate", "cost", "seedance_2_0"),
            command="fake-higgsfield-cli",
            command_source="explicit",
            command_error=None,
            direct_invocation=None,
        )

        self.assertEqual(argv, ["fake-higgsfield-cli", "--json", "generate", "cost", "seedance_2_0"])
        self.assertEqual(argv, self.client.build_argv("generate", "cost", "seedance_2_0"))
        self.assertEqual(self.egress, [])

    def test_run_refuses_a_valid_read_without_starting_a_process(self):
        for args in (("account", "status"), ("generate", "cost", "seedance_2_0"), ("workflow", "list")):
            with self.subTest(args=args):
                with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
                    self.client.run(*args, timeout=5)
                self.assertEqual(ctx.exception.reasons, [PROVIDER_CLOSED])
        self.assertEqual(self.egress, [])

    def test_run_keeps_the_validation_refusals_before_the_closure(self):
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
            self.client.run("generate", "create", "seedance_2_0")
        self.assertEqual(ctx.exception.reasons, ["cli_verb_not_read_only: ('generate', 'create')"])
        self.assertEqual(self.egress, [])

    def test_unconfigured_cli_raises_typed_error_without_any_process(self):
        client = HiggsfieldClient(command="   ")

        self.assertIsNone(client.command)
        for call in (lambda: client.build_argv("account", "status"), lambda: client.run("account", "status")):
            with self.subTest(call=call):
                with self.assertRaises(HiggsfieldCLINotFoundError):
                    call()
        self.assertEqual(self.egress, [])

    def test_typed_errors_are_runtimeerror_subclasses_for_v1_compat(self):
        # Le code V1 (agents/cost_engine.py) capture `except Exception`
        # génériquement : toute erreur typée doit donc rester attrapable de
        # la même façon, sans aucune modification de V1.
        for error_cls in (
            HiggsfieldCLINotFoundError,
            HiggsfieldTimeoutError,
            HiggsfieldAuthenticationError,
            HiggsfieldCommandError,
            HiggsfieldInvalidResponseError,
            HiggsfieldRealGenerationDisabledError,
        ):
            with self.subTest(error_cls=error_cls):
                self.assertTrue(issubclass(error_cls, RuntimeError))


class TestHiggsfieldClientReadOnlyMethods(NoEgressTestCase, unittest.TestCase):
    """Les lectures construisent les bons arguments CLI, puis sont refusées."""

    def setUp(self):
        super().setUp()
        self.client = HiggsfieldClient(command="fake-higgsfield-cli")

    def _built_argv(self, call):
        """argv validé que la lecture aurait lancé (`run()` remplacé : rien ne tourne)."""

        forwarded = []
        with patch.object(HiggsfieldClient, "run", lambda self, *args, **kwargs: forwarded.append(args)):
            call()
        self.assertEqual(len(forwarded), 1)
        return self.client.build_argv(*forwarded[0])

    def test_list_models_video_flag(self):
        self.assertIn("--video", self._built_argv(lambda: self.client.list_models(video=True)))

    def test_get_model_builds_expected_command(self):
        args = self._built_argv(lambda: self.client.get_model("seedance_2_0"))
        self.assertEqual(args[-3:], ["model", "get", "seedance_2_0"])

    def test_get_job_builds_expected_command(self):
        args = self._built_argv(lambda: self.client.get_job("job-123"))
        self.assertEqual(args[-3:], ["generate", "get", "job-123"])

    def test_wait_for_job_never_calls_generate_create(self):
        args = self._built_argv(
            lambda: self.client.wait_for_job("job-123", timeout_seconds=5, interval_seconds=1)
        )
        self.assertIn("wait", args)
        self.assertNotIn("create", args)

    def test_every_read_method_is_refused_without_a_process(self):
        reads = {
            "list_models": lambda: self.client.list_models(video=True),
            "get_model": lambda: self.client.get_model("seedance_2_0"),
            "get_job": lambda: self.client.get_job("job-123"),
            "list_jobs": lambda: self.client.list_jobs(),
            "wait_for_job": lambda: self.client.wait_for_job("job-123", timeout_seconds=5, interval_seconds=1),
        }
        for name, call in reads.items():
            with self.subTest(method=name):
                with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
                    call()
                self.assertEqual(ctx.exception.reasons, [PROVIDER_CLOSED])
        self.assertEqual(self.egress, [])


if __name__ == "__main__":
    unittest.main()
