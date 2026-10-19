"""
Tests — Phase P2.1 : transmission fidèle d'un prompt multi-lignes au CLI
Higgsfield sous Windows (HiggsfieldClient).

CONTEXTE (Phase P2, audit) : `higgsfield.cmd` (shim npm) invoqué via
`subprocess.run([...], shell=False)` passe, sous Windows, par cmd.exe
(comportement du chargeur de processus Windows lui-même pour tout
.cmd/.bat, indépendant de Python). Le parseur de cmd.exe est orienté
ligne : un argument contenant un retour à la ligne littéral (le Master
Prompt réel en contient toujours) était tronqué à sa première ligne,
perdant/décalant les arguments suivants (ex. --duration) SANS jamais
lever d'erreur — confirmé en lecture seule : un même prompt donnait
67.5 crédits sur une seule ligne et 22.5 crédits (prix par défaut du
modèle) réparti sur plusieurs lignes, à durée demandée identique (15s).

Le correctif (HiggsfieldClient._resolve_direct_invocation) contourne le
shim .cmd/cmd.exe en ciblant directement le vrai interpréteur Node.js
sur le script .js qu'il relaie, quand la disposition npm standard est
détectée.

Provider = CLOSED : `run()` ne lance plus aucun processus, pas même une
lecture. Ces tests ne lancent donc plus de vrai sous-processus : ils
vérifient l'argv EXACT avec la fonction pure `build_argv()` (une liste
d'arguments séparés, le prompt multi-lignes restant UN seul élément), puis
que `run()` et chaque lecture refusent. Chaque test tourne sous
`no_egress()`, qui enregistre et refuse tout lancement de processus ou toute
connexion (l'enregistrement doit rester vide) — sans jamais toucher au vrai
CLI Higgsfield, au réseau, ni consommer le moindre crédit.

Spécifique à Windows (os.name == "nt") : c'est précisément la
plateforme où le bug existe. Ignoré ailleurs.
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

from integrations.higgsfield.client import HiggsfieldClient
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from tests.provider_closure_helpers import NoEgressTestCase

PROVIDER_CLOSED = "provider_closed_no_cli_process"

# Reproduit fidèlement le Master Prompt 005 réel : plusieurs dizaines de
# lignes, sections multiples, exactement le type de contenu qui
# déclenchait la troncature (Phase P2 audit).
REALISTIC_MULTILINE_PROMPT = "\n".join(
    [
        "ZEPHYR AI — MASTER PRODUCTION PROMPT",
        "====================================",
        "",
        "VIDEO ID",
        "--------",
        "005",
        "",
        "1. CHARACTER IDENTITY",
        "Keep the face and identity visually consistent across every scene.",
        "Do not redesign, replace, beautify, age, de-age, or reinterpret the face.",
        "",
        "2. VISUAL STYLE",
        "Premium cinematic AI / future / mindset content.",
        "Dark, sophisticated, futuristic, mysterious, intelligent.",
        "",
        "3. VIDEO-SPECIFIC DIRECTION",
        "Format: Duration 40 seconds. Aspect ratio: 9:16.",
        "Scene 01 — 5s: Le talent impressionne. La discipline construit des empires.",
        "Scene 02 — 7s: Le talent impressionne. Mais il ne suffit pas.",
        "",
        "END MASTER PROMPT",
        "====================================",
    ]
)


_FAKE_NPM_SHIM_TEMPLATE = (
    "@ECHO off\n"
    "GOTO start\n"
    ":find_dp0\n"
    "SET dp0=%~dp0\n"
    "EXIT /b\n"
    ":start\n"
    "SETLOCAL\n"
    "CALL :find_dp0\n"
    'IF EXIST "%dp0%\\node.exe" (\n'
    '  SET "_prog=%dp0%\\node.exe"\n'
    ") ELSE (\n"
    "  SET _prog=node\n"
    ")\n"
    'endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  '
    '"%dp0%\\node_modules\\@higgsfield\\cli\\bin\\higgsfield.js"  %*\n'
)

@unittest.skipUnless(
    os.name == "nt",
    "Le bug contourné est spécifique à l'invocation .cmd sous Windows.",
)
class TestWindowsCmdShimMultilinePromptBypass(NoEgressTestCase, unittest.TestCase):
    """
    Fabrique un faux shim npm .cmd + un faux node.exe (fichier vide, jamais
    lancé) reproduisant exactement la disposition réelle
    (node_modules/@higgsfield/cli/bin/higgsfield.js), pour vérifier l'argv
    construit par la fonction pure `build_argv()`.
    """

    def setUp(self):
        super().setUp()
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

        root = Path(self._tmp.name)

        bin_dir = root / "node_modules" / "@higgsfield" / "cli" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "higgsfield.js").write_text("// fake entry\n", encoding="utf-8")
        (root / "node.exe").write_text("", encoding="utf-8")

        self.shim_path = root / "higgsfield.cmd"
        self.shim_path.write_text(_FAKE_NPM_SHIM_TEMPLATE, encoding="utf-8")

        self.client = HiggsfieldClient(command=str(self.shim_path))

    def test_bypass_is_detected_for_the_fake_npm_shim(self):
        self.assertIsNotNone(self.client._direct_invocation)
        self.assertTrue(self.client._direct_invocation[0].endswith("node.exe"))
        self.assertTrue(self.client._direct_invocation[1].endswith("higgsfield.js"))

    def _cli_args(self, *args):
        """argv validé (pur) après l'invocation Node directe ; rien n'est lancé."""

        argv = self.client.build_argv(*args)
        self.assertEqual(argv[:2], self.client._direct_invocation)
        return argv[2:]

    def _forwarded(self, call):
        """Arguments qu'une lecture transmet à `run()` (remplacé : rien ne tourne)."""

        forwarded = []
        with patch.object(HiggsfieldClient, "run", lambda self, *args, **kwargs: forwarded.append(args)):
            call()
        self.assertEqual(len(forwarded), 1)
        return forwarded[0]

    def test_short_prompt_arguments_are_correct(self):
        self.assertEqual(
            self._cli_args("generate", "cost", "seedance_2_0", "--prompt", "read-only cost check"),
            ["--json", "generate", "cost", "seedance_2_0", "--prompt", "read-only cost check"],
        )

    def test_long_single_line_prompt_arguments_are_correct(self):
        long_single_line = "cinematic shot of a character " * 230
        argv = self._cli_args("generate", "cost", "seedance_2_0", "--prompt", long_single_line)
        self.assertEqual(argv[-1], long_single_line)

    def test_multiline_prompt_and_duration_stay_distinct_and_correct(self):
        argv = self._cli_args(
            "generate",
            "cost",
            "seedance_2_0",
            "--prompt",
            REALISTIC_MULTILINE_PROMPT,
            "--duration",
            "15",
            "--resolution",
            "720p",
            "--aspect-ratio",
            "9:16",
        )

        self.assertEqual(
            argv,
            [
                "--json",
                "generate",
                "cost",
                "seedance_2_0",
                "--prompt",
                REALISTIC_MULTILINE_PROMPT,
                "--duration",
                "15",
                "--resolution",
                "720p",
                "--aspect-ratio",
                "9:16",
            ],
        )

        # Le point de rupture historique : le prompt ne doit JAMAIS être
        # tronqué à sa première ligne.
        self.assertIn("\n", argv[5])
        self.assertEqual(argv[5], REALISTIC_MULTILINE_PROMPT)

        # --duration doit rester une paire (flag, valeur) distincte,
        # jamais absorbée dans le prompt ni perdue.
        duration_index = argv.index("--duration")
        self.assertEqual(argv[duration_index + 1], "15")

    def test_estimate_cost_via_client_uses_same_correct_argv(self):
        call_args = self._forwarded(lambda: self.client.estimate_cost(
            job_type="seedance_2_0",
            prompt=REALISTIC_MULTILINE_PROMPT,
            duration=15,
            resolution="720p",
            aspect_ratio="9:16",
        ))

        self.assertIn(REALISTIC_MULTILINE_PROMPT, call_args)
        self.assertIn("--duration", call_args)
        self.assertIn("15", call_args)
        self.assertEqual(self._cli_args(*call_args)[1:], list(call_args))

    def test_account_status_not_regressed_by_the_bypass(self):
        call_args = self._forwarded(self.client.account_status)
        self.assertEqual(self._cli_args(*call_args), ["--json", "account", "status"])

    def test_get_model_not_regressed_by_the_bypass(self):
        call_args = self._forwarded(lambda: self.client.get_model("seedance_2_0"))
        self.assertEqual(self._cli_args(*call_args), ["--json", "model", "get", "seedance_2_0"])

    def test_run_and_reads_refuse_without_any_process(self):
        calls = {
            "run multiline cost": lambda: self.client.run(
                "generate", "cost", "seedance_2_0", "--prompt", REALISTIC_MULTILINE_PROMPT, "--duration", "15",
            ),
            "estimate_cost": lambda: self.client.estimate_cost(
                job_type="seedance_2_0", prompt=REALISTIC_MULTILINE_PROMPT, duration=15,
            ),
            "account_status": self.client.account_status,
            "get_model": lambda: self.client.get_model("seedance_2_0"),
        }
        for label, call in calls.items():
            with self.subTest(call=label):
                with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
                    call()
                self.assertEqual(ctx.exception.reasons, [PROVIDER_CLOSED])
        self.assertEqual(self.egress, [])


@unittest.skipUnless(os.name == "nt", "Comportement de repli spécifique à Windows.")
class TestWindowsCmdShimBypassSafeFallback(NoEgressTestCase, unittest.TestCase):
    """Le contournement ne doit JAMAIS s'activer hors de la disposition npm connue."""

    def test_unrelated_cmd_file_falls_back_to_original_behaviour(self):
        with TemporaryDirectory() as tmp:
            foreign_cmd = Path(tmp) / "something_else.cmd"
            foreign_cmd.write_text("@ECHO off\necho not higgsfield\n", encoding="utf-8")

            client = HiggsfieldClient(command=str(foreign_cmd))

            self.assertIsNone(client._direct_invocation)

            # Phase P3.92-R1 (F-1) : l'ancien repli exécutait ce .cmd via
            # cmd.exe (injection possible) -- il est désormais refusé dès
            # la validation, avant tout processus.
            with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
                client.run("account", "status")
            self.assertTrue(ctx.exception.reasons[0].startswith("cmd_exe_fallback_refused"))

            self.assertEqual(self.egress, [])

    def test_bypass_never_triggers_off_windows(self):
        with patch("integrations.higgsfield.client.os.name", "posix"):
            client = HiggsfieldClient(command=str(self._shim_path()))
            self.assertIsNone(client._direct_invocation)

    def _shim_path(self):
        # Un vrai shim valide n'a pas besoin d'exister sur disque : le
        # test vérifie que la vérification de plateforme coupe court
        # avant toute lecture de fichier.
        return Path("C:/does/not/need/to/exist/higgsfield.cmd")


if __name__ == "__main__":
    unittest.main()
