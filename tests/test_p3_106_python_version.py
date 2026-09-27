"""
Tests — Phase P3.106 : version Python supportée déclarée (F8-1).

Avant P3.106, aucune version Python n'était déclarée (ni pyproject, ni
requirements, ni `.python-version`, ni CI). La seule version réellement
validée par la suite complète est CPython 3.14 (Windows) ; c'est elle que
`.python-version` déclare et que le README documente.

Ces tests protègent la déclaration :
- `.python-version` contient une version `MAJEUR.MINEUR` unique ;
- le README annonce exactement cette version ;
- l'interpréteur qui exécute la suite EST la version déclarée : une suite
  verte ne vaut validation que pour elle. Changer d'interpréteur impose de
  relancer la suite complète puis de mettre à jour la déclaration, jamais
  de supposer la compatibilité.
"""

import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_VERSION_FILE = PROJECT_ROOT / ".python-version"
README = PROJECT_ROOT / "README.md"


def _declared_version():
    content = PYTHON_VERSION_FILE.read_text(encoding="utf-8").strip()
    match = re.fullmatch(r"(\d+)\.(\d+)", content)
    if match is None:
        raise AssertionError(f".python-version must hold a single MAJOR.MINOR version, got {content!r}")
    return int(match.group(1)), int(match.group(2))


class TestDeclaredPythonVersion(unittest.TestCase):
    def test_declaration_is_a_single_major_minor_version(self):
        self.assertEqual(_declared_version(), (3, 14))

    def test_readme_documents_the_declared_version(self):
        major, minor = _declared_version()
        text = README.read_text(encoding="utf-8")
        self.assertIn("## Environnement Python", text)
        self.assertIn(f"Version supportée : **Python {major}.{minor}**", text)
        self.assertIn("`.python-version`", text)

    def test_running_interpreter_is_the_declared_version(self):
        self.assertEqual(
            sys.version_info[:2],
            _declared_version(),
            f"Suite run with Python {sys.version.split()[0]}, but .python-version "
            f"declares {'.'.join(map(str, _declared_version()))}: validate the full "
            f"suite on this version, then update the declaration.",
        )


if __name__ == "__main__":
    unittest.main()
