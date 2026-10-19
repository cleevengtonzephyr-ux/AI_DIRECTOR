"""
Tests — Phase P2.3, verrou 3 : transport fidèle d'un prompt multi-lignes
au CLI Higgsfield (régression du bug Windows corrigé en P2.1).

RISQUE VERROUILLÉ : sous Windows, `subprocess.run([".../higgsfield.cmd",
...], shell=False)` passe par cmd.exe (comportement du chargeur de
processus Windows), dont le parseur orienté-ligne tronque tout argument
`--prompt` contenant un retour à la ligne littéral à sa première ligne —
décalant/perdant les arguments suivants (`--duration 15` notamment)
SANS lever d'erreur, et faisant retomber le coût sur la durée par
défaut du modèle (5s) au lieu de la durée demandée. Le correctif
(`HiggsfieldClient._resolve_direct_invocation`) contourne le shim
.cmd/cmd.exe en invoquant directement Node.js sur le script .js relayé.

Provider = CLOSED : `run()` ne lance plus aucun processus. Ce fichier
verrouille que (a) la détection du contournement reste active et (b) la
LISTE d'arguments construite par la fonction pure `build_argv()` (celle
que `run()` valide avant de refuser) ne perd, ne scinde, ni ne réordonne
jamais le prompt ou les paramètres qui le suivent — quelle que soit la
forme du prompt — et (c) que `run()` refuse sans processus. Chaque test
tourne sous `no_egress()`. Aucun appel réseau, aucun CLI réel, aucune
génération, aucun crédit consommé.
"""

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from integrations.higgsfield.client import HiggsfieldClient
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from agents.production_model import PRODUCTION_MODEL
from tests.provider_closure_helpers import NoEgressTestCase

PROVIDER_CLOSED = "provider_closed_no_cli_process"

# Test C : >= 200 lignes, espaces, caractères spéciaux raisonnables.
MULTILINE_PROMPT_200_LINES = "\n".join(
    f"  Scene {i:03d} — cinematic shot, café, naïve — élan; (beat) [{i}] "
    for i in range(1, 201)
)

LONG_SINGLE_LINE_PROMPT = "cinematic shot of a character " * 230  # ~6900 car.

SHORT_PROMPT = "read-only cost check"


_FAKE_NPM_SHIM = (
    "@ECHO off\n"
    "GOTO start\n"
    ":find_dp0\n"
    "SET dp0=%~dp0\n"
    "EXIT /b\n"
    ":start\n"
    "SETLOCAL\n"
    "CALL :find_dp0\n"
    'endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  '
    '"%dp0%\\node_modules\\@higgsfield\\cli\\bin\\higgsfield.js"  %*\n'
)


def _build_fake_npm_client(tmp_path: Path) -> HiggsfieldClient:
    """Fabrique un HiggsfieldClient pointant sur un faux shim npm (disposition
    réelle), sans jamais exécuter quoi que ce soit. Le fichier node.exe n'a
    besoin que d'exister (jamais lancé)."""

    bin_dir = tmp_path / "node_modules" / "@higgsfield" / "cli" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "higgsfield.js").write_text("// fake entry\n", encoding="utf-8")
    (tmp_path / "node.exe").write_text("", encoding="utf-8")

    shim_path = tmp_path / "higgsfield.cmd"
    shim_path.write_text(_FAKE_NPM_SHIM, encoding="utf-8")

    return HiggsfieldClient(command=str(shim_path))


@unittest.skipUnless(
    __import__("os").name == "nt",
    "Le contournement testé est spécifique à l'invocation .cmd sous Windows.",
)
class TestMultilinePromptTransportIsNeverCorrupted(NoEgressTestCase, unittest.TestCase):
    """Verrou 3 : Test A/B/C — le prompt et les paramètres qui le suivent
    (duration, job_type, resolution, aspect_ratio) restent intacts et
    correctement ordonnés, quelle que soit la forme du prompt."""

    def setUp(self):
        super().setUp()
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.client = _build_fake_npm_client(Path(self._tmp.name))

    @staticmethod
    def _cost_args(prompt: str):
        return (
            "generate",
            "cost",
            PRODUCTION_MODEL,
            "--prompt",
            prompt,
            "--duration",
            "15",
            "--resolution",
            "720p",
            "--aspect-ratio",
            "9:16",
        )

    def _run_and_capture_argv(self, prompt: str):
        """argv validé par la fonction pure ; `run()` refuse ensuite sans processus."""

        argv = self.client.build_argv(*self._cost_args(prompt))
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
            self.client.run(*self._cost_args(prompt))
        self.assertEqual(ctx.exception.reasons, [PROVIDER_CLOSED])
        self.assertEqual(self.egress, [])
        return argv

    def _assert_argv_is_intact(self, argv, prompt):
        # Le contournement du shim .cmd doit rester actif : l'argv ne doit
        # JAMAIS cibler directement le .cmd.
        self.assertTrue(argv[0].endswith("node.exe"))
        self.assertTrue(argv[1].endswith("higgsfield.js"))

        self.assertEqual(
            argv[2:],
            [
                "--json",
                "generate",
                "cost",
                PRODUCTION_MODEL,
                "--prompt",
                prompt,
                "--duration",
                "15",
                "--resolution",
                "720p",
                "--aspect-ratio",
                "9:16",
            ],
        )

        # Régression historique explicitement empêchée : --duration ne
        # doit jamais disparaître ni être absorbé dans le prompt, ce qui
        # ferait implicitement retomber le modèle sur sa durée par
        # défaut (5s).
        self.assertIn("--duration", argv)
        self.assertEqual(argv[argv.index("--duration") + 1], "15")
        self.assertNotEqual(argv[argv.index("--duration") + 1], "5")

    def test_A_short_single_line_prompt(self):
        argv = self._run_and_capture_argv(SHORT_PROMPT)
        self._assert_argv_is_intact(argv, SHORT_PROMPT)

    def test_B_long_single_line_prompt(self):
        self.assertGreater(len(LONG_SINGLE_LINE_PROMPT), 6000)
        argv = self._run_and_capture_argv(LONG_SINGLE_LINE_PROMPT)
        self._assert_argv_is_intact(argv, LONG_SINGLE_LINE_PROMPT)

    def test_C_multiline_prompt_with_spaces_and_special_characters(self):
        self.assertGreaterEqual(MULTILINE_PROMPT_200_LINES.count("\n"), 199)
        argv = self._run_and_capture_argv(MULTILINE_PROMPT_200_LINES)
        self._assert_argv_is_intact(argv, MULTILINE_PROMPT_200_LINES)

        # Le prompt reste un unique élément de liste, jamais scindé en
        # plusieurs arguments par ses retours à la ligne internes.
        prompt_index = argv.index("--prompt") + 1
        self.assertEqual(argv[prompt_index], MULTILINE_PROMPT_200_LINES)
        self.assertEqual(argv.count(MULTILINE_PROMPT_200_LINES), 1)

    def test_bypass_activation_does_not_depend_on_prompt_shape(self):
        # La détection du contournement (fichier .cmd + disposition npm)
        # est indépendante du contenu du prompt : elle doit s'activer de
        # façon identique pour les 3 formes testées.
        for prompt in (SHORT_PROMPT, LONG_SINGLE_LINE_PROMPT, MULTILINE_PROMPT_200_LINES):
            with self.subTest(prompt_kind=len(prompt)):
                argv = self._run_and_capture_argv(prompt)
                self.assertTrue(argv[0].endswith("node.exe"))


if __name__ == "__main__":
    unittest.main()
