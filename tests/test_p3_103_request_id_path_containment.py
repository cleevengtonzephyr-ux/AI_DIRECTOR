"""
Tests — Phase P3.103 : validation du `request_id` et confinement des
chemins (F7).

Défaut démontré en P3.103 (audit) : `request_id` / `video_id` était
interpolé tel quel dans un nom de fichier --
`FileCriticalSectionLock` (`<lock_dir>/<request_id>.lock`) et
`PromptAssemblySystem` (`<prompt_root>/video_<video_id>.md`). Des
valeurs comme `../escape`, `C:\\temp\\escape` ou `\\\\server\\share`
sortaient de ces répertoires.

Correction : `agents/request_id_validation.py` -- allowlist
`^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` + noms réservés Windows, appliquée
AVANT toute construction de chemin, puis contrôle de confinement
indépendant du chemin résolu.

Tout se déroule dans des répertoires temporaires (ou en lecture seule
sur les prompts réels pour `005`). Aucun provider, aucun réseau, aucun
`create_job()`, aucun crédit consommé.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents import critical_section_lock as lock_module
from agents import prompt_assembly_system as prompt_module
from agents.critical_section_lock import CriticalSectionBusyError, FileCriticalSectionLock
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.request_id_validation import (
    REQUEST_ID_MAX_LENGTH,
    InvalidRequestIdError,
    PathContainmentError,
    contained_child_path,
    validate_request_id,
)

VALID_IDS = (
    "005",
    "abc123",
    "A-B_C-123",
    "a",
    "0",
    "a" * REQUEST_ID_MAX_LENGTH,
    "CONSOLE",
    "COM10",
    "nul1",
)

# Matrice F7 de l'audit + formes Windows dangereuses.
INVALID_IDS = (
    "../escape",
    "..\\escape",
    "../../escape",
    "..\\..\\escape",
    "foo/bar",
    "foo\\bar",
    "C:\\temp\\escape",
    "C:escape",
    "\\\\server\\share",
    "/abs",
    ".",
    "..",
    "",
    " ",
    "../",
    "..\\",
    # `.` hors contrat (le contrat proposé l'exclut) -- refusé, jamais
    # normalisé.
    "A-B_C.123",
    "abc.",
    "abc ",
    " abc",
    "abc:stream",
    "abc\n",
    "abc\x00",
    "-abc",
    "_abc",
    "é005",
    "005\u2215x",
    "a" * (REQUEST_ID_MAX_LENGTH + 1),
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "LPT1",
    "con",
    "Nul",
    "com9",
    "lpt0",
)

NON_STR_IDS = (None, 5, b"005", Path("005"))


def _all_files(root: Path):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


class RequestIdValidatorTests(unittest.TestCase):
    def test_valid_ids_are_returned_unchanged(self):
        for request_id in VALID_IDS:
            with self.subTest(request_id=request_id):
                self.assertIs(validate_request_id(request_id), request_id)

    def test_005_is_valid(self):
        self.assertEqual(validate_request_id("005"), "005")

    def test_max_length_boundary(self):
        self.assertEqual(REQUEST_ID_MAX_LENGTH, 64)
        validate_request_id("x" * 64)
        with self.assertRaises(InvalidRequestIdError):
            validate_request_id("x" * 65)

    def test_invalid_ids_are_refused(self):
        for request_id in INVALID_IDS:
            with self.subTest(request_id=request_id):
                with self.assertRaises(InvalidRequestIdError):
                    validate_request_id(request_id)

    def test_non_str_ids_are_refused(self):
        for request_id in NON_STR_IDS:
            with self.subTest(request_id=request_id):
                with self.assertRaises(InvalidRequestIdError):
                    validate_request_id(request_id)

    def test_error_is_a_value_error(self):
        self.assertTrue(issubclass(InvalidRequestIdError, ValueError))
        self.assertTrue(issubclass(PathContainmentError, ValueError))


class ContainmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="p3_103_"))
        self.root = self.tmp / "root"
        self.root.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_direct_child_is_contained(self):
        path = contained_child_path(self.root, "005.lock")
        self.assertEqual(path, self.root / "005.lock")

    def test_containment_holds_for_missing_root(self):
        missing = self.tmp / "not" / "yet"
        self.assertEqual(contained_child_path(missing, "005.lock"), missing / "005.lock")

    def test_containment_is_lexical_and_never_resolves(self):
        # `Path.resolve()` retourne sous Windows, de façon non
        # déterministe pendant une création concurrente du répertoire, un
        # préfixe de chemin étendu -- des verrous légitimes étaient
        # refusés (régression observée sur P3.91 à 8 processus).
        with mock.patch.object(Path, "resolve", side_effect=AssertionError("resolve")):
            self.assertEqual(contained_child_path(self.root, "005.lock"), self.root / "005.lock")

    def test_escaping_names_are_refused(self):
        names = [
            "../escape.lock",
            "..\\escape.lock",
            "sub/child.lock",
            "sub\\child.lock",
            "..",
            ".",
            "",
            str(self.tmp / "outside.lock"),
            "\\\\server\\share\\x.lock",
        ]
        if os.name == "nt":
            names += ["C:\\temp\\escape.lock", "C:escape.lock"]
        for name in names:
            with self.subTest(name=name):
                with self.assertRaises(PathContainmentError):
                    contained_child_path(self.root, name)


class FileCriticalSectionLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="p3_103_lock_"))
        self.lock_dir = self.tmp / "state" / "locks"
        self.lock = FileCriticalSectionLock(self.lock_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_005_acquires_and_releases(self):
        with self.lock.acquire("005"):
            self.assertTrue((self.lock_dir / "005.lock").exists())
        self.assertFalse((self.lock_dir / "005.lock").exists())

    def test_valid_ids_acquire_inside_lock_dir(self):
        for request_id in VALID_IDS:
            with self.subTest(request_id=request_id):
                with self.lock.acquire(request_id):
                    self.assertEqual(
                        [p.name for p in self.lock_dir.iterdir()], [f"{request_id}.lock"]
                    )
                self.assertEqual(list(self.lock_dir.iterdir()), [])

    def test_005_busy_contract_unchanged(self):
        with self.lock.acquire("005"):
            with self.assertRaises(CriticalSectionBusyError):
                with self.lock.acquire("005"):
                    self.fail("second acquisition must not enter")

    def test_invalid_ids_refused_fail_closed_without_filesystem_effect(self):
        for request_id in INVALID_IDS + NON_STR_IDS:
            with self.subTest(request_id=request_id):
                entered = False
                with self.assertRaises(CriticalSectionBusyError) as ctx:
                    with self.lock.acquire(request_id):
                        entered = True
                self.assertFalse(entered)
                self.assertIsInstance(ctx.exception.__cause__, InvalidRequestIdError)
                self.assertEqual(_all_files(self.tmp), [])

    def test_validation_happens_before_path_construction(self):
        calls = []
        real_validate = lock_module.validate_request_id
        real_contain = lock_module.contained_child_path

        def spy_validate(request_id):
            calls.append("validate")
            return real_validate(request_id)

        def spy_contain(root, name):
            calls.append("contain")
            return real_contain(root, name)

        with mock.patch.object(lock_module, "validate_request_id", spy_validate), \
                mock.patch.object(lock_module, "contained_child_path", spy_contain), \
                mock.patch.object(lock_module.os, "open", wraps=os.open) as spy_open:
            with self.assertRaises(CriticalSectionBusyError):
                with self.lock.acquire("../escape"):
                    pass
            self.assertEqual(calls, ["validate"])
            spy_open.assert_not_called()

            calls.clear()
            with self.lock.acquire("005"):
                pass
            self.assertEqual(calls, ["validate", "contain"])
            spy_open.assert_called_once()

    def test_containment_is_an_independent_layer(self):
        # Allowlist neutralisée : le confinement refuse encore seul.
        outside = self.tmp / "state" / "escape.lock"
        with mock.patch.object(lock_module, "validate_request_id", lambda request_id: request_id):
            for request_id in ("../escape", "..\\escape", "sub/x"):
                with self.subTest(request_id=request_id):
                    with self.assertRaises(CriticalSectionBusyError) as ctx:
                        with self.lock.acquire(request_id):
                            self.fail("must not enter")
                    self.assertIsInstance(ctx.exception.__cause__, PathContainmentError)
                    self.assertFalse(outside.exists())
                    self.assertEqual(_all_files(self.tmp), [])

    def test_case_variants_never_escape_and_collide_only_on_case_insensitive_fs(self):
        probe = self.tmp / "CaseProbe"
        probe.write_text("x", encoding="utf-8")
        case_insensitive = (self.tmp / "caseprobe").exists()
        probe.unlink()

        with self.lock.acquire("abc"):
            if case_insensitive:
                with self.assertRaises(CriticalSectionBusyError):
                    with self.lock.acquire("ABC"):
                        self.fail("case variant shares the same lock file")
            else:
                with self.lock.acquire("ABC"):
                    self.assertEqual(len(list(self.lock_dir.iterdir())), 2)
        self.assertEqual(list(self.lock_dir.iterdir()), [])


class PromptAssemblySystemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="p3_103_prompt_"))
        self.prompt_root = self.tmp / "assets" / "zephyr" / "prompts"
        self.prompt_root.mkdir(parents=True)
        (self.prompt_root / "character_identity.md").write_text("IDENTITY", encoding="utf-8")
        (self.prompt_root / "visual_style.md").write_text("STYLE", encoding="utf-8")
        (self.prompt_root / "video_005.md").write_text("DIRECTION 005", encoding="utf-8")
        # Cible d'une traversée : lisible si le chemin n'était pas contrôlé.
        (self.tmp / "assets" / "zephyr" / "secret.md").write_text("SECRET", encoding="utf-8")
        self.system = PromptAssemblySystem(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_real_005_still_assembles(self):
        system = PromptAssemblySystem(PROJECT_ROOT)
        self.assertEqual(system.validate("005"), {"status": "READY", "errors": []})
        prompt = system.assemble("005")
        self.assertIn("VIDEO ID\n--------\n005", prompt)
        self.assertIn(
            (PROJECT_ROOT / "assets" / "zephyr" / "prompts" / "video_005.md")
            .read_text(encoding="utf-8").strip(),
            prompt,
        )

    def test_temp_005_assembles(self):
        self.assertEqual(self.system.validate("005")["status"], "READY")
        self.assertIn("DIRECTION 005", self.system.assemble("005"))

    def test_traversal_to_planted_file_is_refused(self):
        video_id = "x/../../secret"
        self.assertEqual(self.system.validate(video_id)["status"], "BLOCKED")
        with self.assertRaises(InvalidRequestIdError):
            self.system.assemble(video_id)

    def test_invalid_ids_refused_by_assemble_and_validate(self):
        for video_id in INVALID_IDS + NON_STR_IDS:
            with self.subTest(video_id=video_id):
                with mock.patch.object(Path, "read_text", side_effect=AssertionError("read")):
                    with self.assertRaises(InvalidRequestIdError):
                        self.system.assemble(video_id)
                    result = self.system.validate(video_id)
                self.assertEqual(result["status"], "BLOCKED")
                self.assertEqual(len(result["errors"]), 1)
                self.assertTrue(result["errors"][0].startswith("Invalid video_id:"))

    def test_run_refuses_invalid_id(self):
        with mock.patch("builtins.print"):
            with self.assertRaises(RuntimeError):
                self.system.run("../escape")

    def test_validation_happens_before_path_construction(self):
        with mock.patch.object(prompt_module, "contained_child_path") as spy_contain:
            with self.assertRaises(InvalidRequestIdError):
                self.system.assemble("../escape")
            self.system.validate("../escape")
            spy_contain.assert_not_called()

    def test_containment_is_an_independent_layer(self):
        with mock.patch.object(prompt_module, "validate_request_id", lambda video_id: video_id):
            with self.assertRaises(PathContainmentError):
                self.system.assemble("x/../../secret")
            result = self.system.validate("x/../../secret")
        self.assertEqual(result["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
