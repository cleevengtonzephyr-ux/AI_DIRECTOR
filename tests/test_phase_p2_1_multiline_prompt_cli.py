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
shim .cmd/cmd.exe en invoquant directement le vrai interpréteur Node.js
sur le script .js qu'il relaie, quand la disposition npm standard est
détectée. Ces tests utilisent un VRAI sous-processus (aucun mock de
subprocess.run) avec un faux shim + un faux "node" (l'interpréteur
Python courant, qui exécute n'importe quel fichier texte qu'on lui
donne, quelle que soit son extension) pour observer l'argv EXACT reçu
par le "CLI" — sans jamais toucher au vrai CLI Higgsfield, au réseau,
ni consommer le moindre crédit.

Spécifique à Windows (os.name == "nt") : c'est précisément la
plateforme où le bug existe. Ignoré ailleurs.
"""

import json
import os
import shutil
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

_FAKE_ENTRY_SCRIPT = (
    "import sys, json\n"
    "print(json.dumps({'argv': sys.argv[1:]}))\n"
)


@unittest.skipUnless(
    os.name == "nt",
    "Le bug contourné est spécifique à l'invocation .cmd sous Windows.",
)
class TestWindowsCmdShimMultilinePromptBypass(unittest.TestCase):
    """
    Fabrique un faux shim npm .cmd + un faux 'node' (l'interpréteur
    Python courant) reproduisant exactement la disposition réelle
    (node_modules/@higgsfield/cli/bin/higgsfield.js), pour observer via
    un VRAI sous-processus l'argv effectivement reçu.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

        root = Path(self._tmp.name)

        bin_dir = root / "node_modules" / "@higgsfield" / "cli" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "higgsfield.js").write_text(_FAKE_ENTRY_SCRIPT, encoding="utf-8")

        shutil.copy2(sys.executable, root / "node.exe")

        self.shim_path = root / "higgsfield.cmd"
        self.shim_path.write_text(_FAKE_NPM_SHIM_TEMPLATE, encoding="utf-8")

        self.client = HiggsfieldClient(command=str(self.shim_path))

    def test_bypass_is_detected_for_the_fake_npm_shim(self):
        self.assertIsNotNone(self.client._direct_invocation)
        self.assertTrue(self.client._direct_invocation[0].endswith("node.exe"))
        self.assertTrue(self.client._direct_invocation[1].endswith("higgsfield.js"))

    def test_short_prompt_arguments_are_correct(self):
        result = self.client.run(
            "generate", "cost", "seedance_2_0", "--prompt", "read-only cost check",
        )
        self.assertEqual(
            result["argv"],
            ["--json", "generate", "cost", "seedance_2_0", "--prompt", "read-only cost check"],
        )

    def test_long_single_line_prompt_arguments_are_correct(self):
        long_single_line = "cinematic shot of a character " * 230
        result = self.client.run(
            "generate", "cost", "seedance_2_0", "--prompt", long_single_line,
        )
        self.assertEqual(result["argv"][-1], long_single_line)

    def test_multiline_prompt_and_duration_stay_distinct_and_correct(self):
        result = self.client.run(
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
            result["argv"],
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
        self.assertIn("\n", result["argv"][5])
        self.assertEqual(result["argv"][5], REALISTIC_MULTILINE_PROMPT)

        # --duration doit rester une paire (flag, valeur) distincte,
        # jamais absorbée dans le prompt ni perdue.
        self.assertIn("--duration", result["argv"])
        duration_index = result["argv"].index("--duration")
        self.assertEqual(result["argv"][duration_index + 1], "15")

    def test_estimate_cost_via_client_uses_same_correct_argv(self):
        with patch.object(HiggsfieldClient, "run", wraps=self.client.run) as spy:
            self.client.estimate_cost(
                job_type="seedance_2_0",
                prompt=REALISTIC_MULTILINE_PROMPT,
                duration=15,
                resolution="720p",
                aspect_ratio="9:16",
            )

        call_args = spy.call_args.args
        self.assertIn(REALISTIC_MULTILINE_PROMPT, call_args)
        self.assertIn("--duration", call_args)
        self.assertIn("15", call_args)

    def test_account_status_not_regressed_by_the_bypass(self):
        result = self.client.account_status()
        self.assertEqual(result["argv"], ["--json", "account", "status"])

    def test_get_model_not_regressed_by_the_bypass(self):
        result = self.client.get_model("seedance_2_0")
        self.assertEqual(result["argv"], ["--json", "model", "get", "seedance_2_0"])


@unittest.skipUnless(os.name == "nt", "Comportement de repli spécifique à Windows.")
class TestWindowsCmdShimBypassSafeFallback(unittest.TestCase):
    """Le contournement ne doit JAMAIS s'activer hors de la disposition npm connue."""

    def test_unrelated_cmd_file_falls_back_to_original_behaviour(self):
        with TemporaryDirectory() as tmp:
            foreign_cmd = Path(tmp) / "something_else.cmd"
            foreign_cmd.write_text("@ECHO off\necho not higgsfield\n", encoding="utf-8")

            client = HiggsfieldClient(command=str(foreign_cmd))

            self.assertIsNone(client._direct_invocation)

            # Phase P3.92-R1 (F-1) : l'ancien repli exécutait ce .cmd via
            # cmd.exe (injection possible) -- il est désormais refusé,
            # avant tout subprocess.
            with patch("subprocess.run") as mock_run:
                with self.assertRaises(HiggsfieldRealGenerationDisabledError):
                    client.run("account", "status")

                mock_run.assert_not_called()

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
