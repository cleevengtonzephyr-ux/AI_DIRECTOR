"""
Tests -- `generate cost` option restriction (Phase P3.85).

P3.84: after the read-only `("generate", "cost")` verb, `HiggsfieldClient.run()`
passed ANY option through. The installed CLI documents media flags
(`--image`, `--video-references` ...) that "accept a UUID (upload id or job
id) or a local file path" -- a local path is uploaded, a backend write whose
harmlessness cannot be proven offline (NOT PROVEN). P3.85 restricts
`generate cost` to the exact estimation form `estimate_cost()` emits:

    generate cost <job_type> [--prompt v] [--duration v] [--resolution v] [--aspect-ratio v]

Everything else is refused BEFORE any process starts. Every test replaces the
client module's `subprocess` with a recording fake: no network, no credits.
"""

import json
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import integrations.higgsfield.client as client_mod
from integrations.higgsfield.client import HiggsfieldClient
from integrations.higgsfield.errors import HiggsfieldError, HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.provider import HiggsfieldProvider
from agents.generation_cost_service import CostEstimationStatus, GenerationCostService

MEDIA_FLAGS = ("--image", "--image-url", "--image-references", "--start-image", "--end-image", "--video",
               "--video-input", "--video-references", "--audio", "--audio-references", "--media", "--avatar",
               "--product", "--from-file")
OTHER_UNNEEDED_FLAGS = ("--count", "--wait", "--wait-timeout", "--wait-interval", "--json", "--prefix", "--start", "--foo")


class _FakeSubprocess(types.ModuleType):
    TimeoutExpired = client_mod.subprocess.TimeoutExpired

    def __init__(self):
        super().__init__("fake_subprocess")
        self.calls = []

    def run(self, command, **kwargs):
        self.calls.append(tuple(command[command.index("--json") + 1:]))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"credits": 67.5}), stderr="")


class _CostCase(unittest.TestCase):
    def setUp(self):
        self.fake = _FakeSubprocess()
        patcher = mock.patch.object(client_mod, "subprocess", self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = HiggsfieldClient()

    def assertRefusedBeforeProcess(self, *args):
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            self.client.run(*args)
        self.assertEqual(self.fake.calls, [])


class TestAllowedEstimationForms(_CostCase):
    def test_estimate_cost_builds_the_exact_estimation_request(self):
        cases = [
            ({}, ("generate", "cost", "seedance_2_0", "--prompt", "P")),
            ({"duration": 15}, ("generate", "cost", "seedance_2_0", "--prompt", "P", "--duration", "15")),
            ({"duration": 15, "resolution": "720p", "aspect_ratio": "9:16"},
             ("generate", "cost", "seedance_2_0", "--prompt", "P", "--duration", "15", "--resolution", "720p", "--aspect-ratio", "9:16")),
        ]
        for kwargs, expected in cases:
            with self.subTest(kwargs=kwargs):
                self.fake.calls.clear()
                self.assertEqual(self.client.estimate_cost("seedance_2_0", "P", **kwargs), {"credits": 67.5})
                self.assertEqual(self.fake.calls, [expected])

    def test_prompt_values_are_opaque_text(self):
        for prompt in ("- scene one", "--image ./x.png", "generate create", "multi\nline"):
            with self.subTest(prompt=prompt):
                self.fake.calls.clear()
                self.client.estimate_cost("seedance_2_0", prompt, duration=15)
                self.assertEqual(self.fake.calls, [("generate", "cost", "seedance_2_0", "--prompt", prompt, "--duration", "15")])

    def test_bare_estimate_without_prompt_stays_allowed(self):
        self.assertEqual(self.client.run("generate", "cost", "seedance_2_0"), {"credits": 67.5})

    def test_every_accepted_form_is_still_an_estimation(self):
        self.client.estimate_cost("seedance_2_0", "P", duration=15, resolution="720p", aspect_ratio="9:16")
        self.client.run("generate", "cost", "seedance_2_0")
        self.assertTrue(self.fake.calls)
        self.assertTrue(all(call[:2] == ("generate", "cost") for call in self.fake.calls))


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


class TestFailClosedThroughTheP2CostPath(unittest.TestCase):
    def test_refused_estimation_surfaces_as_cost_error_never_as_a_cost(self):
        fake = _FakeSubprocess()
        with mock.patch.object(client_mod, "subprocess", fake):
            client = HiggsfieldClient()
            original = client.estimate_cost
            client.estimate_cost = lambda *a, **k: client.run("generate", "cost", "seedance_2_0", "--image", "./first.png")
            result = GenerationCostService(HiggsfieldProvider(client=client)).estimate(job_type="seedance_2_0", prompt="P", duration=15)
            self.assertIsInstance(HiggsfieldRealGenerationDisabledError("x"), HiggsfieldError)
            self.assertEqual(result.status, CostEstimationStatus.ERROR)
            client.estimate_cost = original
            self.assertEqual(
                GenerationCostService(HiggsfieldProvider(client=client)).estimate(job_type="seedance_2_0", prompt="P", duration=15).status,
                CostEstimationStatus.KNOWN,
            )
        self.assertEqual(fake.calls, [("generate", "cost", "seedance_2_0", "--prompt", "P", "--duration", "15")])


class TestLockDStillIntact(_CostCase):
    def test_create_paths_stay_refused(self):
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            self.client.create_job("seedance_2_0", "P", duration=15)
        self.assertRefusedBeforeProcess("generate", "create", "seedance_2_0", "--prompt", "P")


if __name__ == "__main__":
    unittest.main()
