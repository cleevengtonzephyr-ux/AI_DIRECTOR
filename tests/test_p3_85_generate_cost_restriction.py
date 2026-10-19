"""
Tests -- `generate cost` option restriction (Phase P3.85).

P3.84: after the read-only `("generate", "cost")` verb, `HiggsfieldClient.run()`
passed ANY option through. The installed CLI documents media flags
(`--image`, `--video-references` ...) that "accept a UUID (upload id or job
id) or a local file path" -- a local path is uploaded, a backend write whose
harmlessness cannot be proven offline (NOT PROVEN). P3.85 restricts
`generate cost` to the exact estimation form `estimate_cost()` emits:

    generate cost <job_type> [--prompt v] [--duration v] [--resolution v] [--aspect-ratio v]

Everything else is refused before any command is built. Provider = CLOSED:
even an accepted form is never executed -- `run()` validates with the pure
`build_argv()` then refuses. Every test runs under `no_egress()`.
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
from integrations.higgsfield.errors import HiggsfieldError, HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.provider import HiggsfieldProvider
from agents.generation_cost_service import CostEstimationStatus, GenerationCostService
from tests.provider_closure_helpers import NoEgressTestCase

PROVIDER_CLOSED = "provider_closed_no_cli_process"

MEDIA_FLAGS = ("--image", "--image-url", "--image-references", "--start-image", "--end-image", "--video",
               "--video-input", "--video-references", "--audio", "--audio-references", "--media", "--avatar",
               "--product", "--from-file")
OTHER_UNNEEDED_FLAGS = ("--count", "--wait", "--wait-timeout", "--wait-interval", "--json", "--prefix", "--start", "--foo")


# Fixture hermétique : un npm layout temporaire remplace le CLI Higgsfield
# installé sur la machine. Tout `HiggsfieldClient()` du module résout ce
# shim puis l'invocation Node directe (P3.92-R1) ; sans elle, `run()`
# refuse le shim .cmd avant tout processus.
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


class _CostCase(NoEgressTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.client = HiggsfieldClient()

    def argv(self, *args):
        """Validated argv after `--json` (pure: no process)."""

        argv = self.client.build_argv(*args)
        return tuple(argv[argv.index("--json") + 1:])

    def assertRefusedBeforeProcess(self, *args):
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as context:
            self.client.build_argv(*args)
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            self.client.run(*args)
        self.assertEqual(self.egress, [])
        return context.exception

    def assertClosed(self, call):
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as context:
            call()
        self.assertEqual(context.exception.reasons, [PROVIDER_CLOSED])
        self.assertEqual(self.egress, [])


class TestAllowedEstimationForms(_CostCase):
    def _forwarded(self, call):
        forwarded = []
        with mock.patch.object(HiggsfieldClient, "run", lambda self, *args, **kwargs: forwarded.append(args)):
            call()
        return forwarded

    def test_estimate_cost_builds_the_exact_estimation_request(self):
        cases = [
            ({}, ("generate", "cost", "seedance_2_0", "--prompt", "P")),
            ({"duration": 15}, ("generate", "cost", "seedance_2_0", "--prompt", "P", "--duration", "15")),
            ({"duration": 15, "resolution": "720p", "aspect_ratio": "9:16"},
             ("generate", "cost", "seedance_2_0", "--prompt", "P", "--duration", "15", "--resolution", "720p", "--aspect-ratio", "9:16")),
        ]
        for kwargs, expected in cases:
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self._forwarded(lambda: self.client.estimate_cost("seedance_2_0", "P", **kwargs)), [expected])
                self.assertEqual(self.argv(*expected), expected)
                self.assertClosed(lambda: self.client.estimate_cost("seedance_2_0", "P", **kwargs))

    def test_prompt_values_are_opaque_text(self):
        for prompt in ("- scene one", "--image ./x.png", "generate create", "multi\nline"):
            with self.subTest(prompt=prompt):
                expected = ("generate", "cost", "seedance_2_0", "--prompt", prompt, "--duration", "15")
                self.assertEqual(self._forwarded(lambda: self.client.estimate_cost("seedance_2_0", prompt, duration=15)), [expected])
                self.assertEqual(self.argv(*expected), expected)

    def test_bare_estimate_without_prompt_stays_a_valid_form_but_is_closed(self):
        self.assertEqual(self.argv("generate", "cost", "seedance_2_0"), ("generate", "cost", "seedance_2_0"))
        self.assertClosed(lambda: self.client.run("generate", "cost", "seedance_2_0"))


class TestRefusedEstimationForms(_CostCase):
    def test_media_options_are_refused(self):
        for flag in MEDIA_FLAGS:
            for value in ("./first.png", "3f2c9a1e-upload-id"):
                with self.subTest(flag=flag, value=value):
                    self.assertRefusedBeforeProcess("generate", "cost", "seedance_2_0", "--prompt", "P", flag, value)

    def test_unneeded_or_unknown_options_are_refused(self):
        for flag in OTHER_UNNEEDED_FLAGS:
            with self.subTest(flag=flag):
                self.assertRefusedBeforeProcess("generate", "cost", "seedance_2_0", "--prompt", "P", flag, "5")

    def test_ambiguous_syntax_is_refused(self):
        cases = {
            "equals form of a media flag": ("generate", "cost", "seedance_2_0", "--image=./x.png"),
            "equals form of an allowed flag": ("generate", "cost", "seedance_2_0", "--prompt=P"),
            "repeated option": ("generate", "cost", "seedance_2_0", "--duration", "5", "--duration", "15"),
            "option without value": ("generate", "cost", "seedance_2_0", "--prompt", "P", "--duration"),
            "extra positional": ("generate", "cost", "seedance_2_0", "--prompt", "P", "./first.png"),
            "short flag": ("generate", "cost", "seedance_2_0", "-i", "./x.png"),
        }
        for label, args in cases.items():
            with self.subTest(case=label):
                self.assertRefusedBeforeProcess(*args)

    def test_subcommands_and_non_identifier_job_types_are_refused(self):
        cases = {
            "workflow subcommand": ("generate", "cost", "workflow", "reframe", "--duration", "7.1", "--resolution", "1080p"),
            "create as job_type": ("generate", "cost", "create", "--prompt", "P"),
            "flag as job_type": ("generate", "cost", "--image", "./x.png"),
            "empty job_type": ("generate", "cost", ""),
            "path as job_type": ("generate", "cost", "./first.png"),
            "missing job_type": ("generate", "cost"),
        }
        for label, args in cases.items():
            with self.subTest(case=label):
                self.assertRefusedBeforeProcess(*args)


class TestFailClosedThroughTheP2CostPath(NoEgressTestCase, unittest.TestCase):
    def test_closed_estimation_surfaces_as_cost_error_never_as_a_cost(self):
        client = HiggsfieldClient()
        self.assertIsInstance(HiggsfieldRealGenerationDisabledError("x"), HiggsfieldError)
        for estimate in (
            lambda *a, **k: client.run("generate", "cost", "seedance_2_0", "--image", "./first.png"),
            client.estimate_cost,
        ):
            with self.subTest(estimate=estimate):
                client.estimate_cost = estimate
                result = GenerationCostService(HiggsfieldProvider(client=client)).estimate(
                    job_type="seedance_2_0", prompt="P", duration=15
                )
                self.assertEqual(result.status, CostEstimationStatus.ERROR)
        self.assertEqual(self.egress, [])


class TestLockDStillIntact(_CostCase):
    def test_create_paths_stay_refused(self):
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            self.client.create_job("seedance_2_0", "P", duration=15)
        self.assertRefusedBeforeProcess("generate", "create", "seedance_2_0", "--prompt", "P")


class TestHermeticCliFixture(unittest.TestCase):
    def test_default_client_resolves_the_temporary_node_exe(self):
        invocation = HiggsfieldClient()._direct_invocation
        self.assertIsNotNone(invocation)
        self.assertEqual(Path(invocation[0]), _FIXTURE_NODE_EXE)


if __name__ == "__main__":
    unittest.main()
