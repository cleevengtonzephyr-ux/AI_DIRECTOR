"""
Tests — Phase P3.106 : version Python supportée déclarée (F8-1).

Avant P3.106, aucune version Python n'était déclarée (ni pyproject, ni
requirements, ni `.python-version`, ni CI). La seule version réellement
validée par la suite complète est CPython 3.14 (Windows) ; c'est elle que
`.python-version` déclare et que le README documente.

Ces tests protègent la déclaration :
- `.python-version` contient une version `MAJEUR.MINEUR` unique ;
- le README annonce exactement cette version ;
- le README ne déclare jamais Python 3.11, 3.12 ou 3.13 supporté : ce ne
  sont que des versions non validées au-dessus du plancher technique ;
- le README précise que `.python-version` n'installe pas Python ;
- l'interpréteur qui exécute la suite EST la version déclarée : une suite
  verte ne vaut validation que pour elle. Changer d'interpréteur impose de
  relancer la suite complète puis de mettre à jour la déclaration, jamais
  de supposer la compatibilité.
"""

import re
import sys
import unicodedata
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


_UNVALIDATED_VERSION = re.compile(r"\b3\.1[123]\b")
# Formulations de support comparées sans accents ni casse : « support… »,
# « pris(e)(s) en charge ».
_SUPPORT_WORDING = re.compile(r"support|\bpris(?:es?|)\s+en\s+charge\b")
_NEGATION = re.compile(r"\bpas\b|\bnot\b")


def _fold(text):
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _unvalidated_support_claims(text):
    """Phrases qui déclarent supporté Python 3.11, 3.12 ou 3.13 sans le nier."""
    claims = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        folded = _fold(sentence)
        if (
            _UNVALIDATED_VERSION.search(folded)
            and _SUPPORT_WORDING.search(folded)
            and not _NEGATION.search(folded)
        ):
            claims.append(sentence)
    return claims


class TestDeclaredPythonVersion(unittest.TestCase):
    def test_declaration_is_a_single_major_minor_version(self):
        self.assertEqual(_declared_version(), (3, 14))

    def test_readme_documents_the_declared_version(self):
        major, minor = _declared_version()
        text = README.read_text(encoding="utf-8")
        self.assertIn("## Environnement Python", text)
        self.assertIn(f"Version supportée : **Python {major}.{minor}**", text)
        self.assertIn("`.python-version`", text)

    def test_readme_never_declares_unvalidated_versions_supported(self):
        text = README.read_text(encoding="utf-8")
        for line in text.splitlines():
            if re.search(r"Versions? supportées? :", line):
                self.assertEqual(re.findall(r"\b3\.\d+\b", line), ["3.14"], line)
        self.assertIsNone(re.search(r"(>=|≥)\s*3\.1[123]\b|\b3\.1[123]\s*\+", text))
        self.assertEqual(_unvalidated_support_claims(text), [])
        self.assertIn("les versions 3.11 à 3.13 n'ont jamais été validées et ne sont **pas** déclarées supportées", text)

    def test_readme_states_python_version_file_installs_nothing(self):
        text = README.read_text(encoding="utf-8")
        self.assertIn("il n'installe pas Python et n'en gère pas l'installation", text)

    def test_running_interpreter_is_the_declared_version(self):
        self.assertEqual(
            sys.version_info[:2],
            _declared_version(),
            f"Suite run with Python {sys.version.split()[0]}, but .python-version "
            f"declares {'.'.join(map(str, _declared_version()))}: validate the full "
            f"suite on this version, then update the declaration.",
        )


class TestUnvalidatedSupportClaimDetection(unittest.TestCase):
    """La détection elle-même, sur des phrases ciblées (hors README)."""

    def test_support_claims_are_detected(self):
        claims = [
            "Python 3.12 est prise en charge.",
            "Python 3.13 est pris en charge.",
            "Les versions 3.11 et 3.12 sont prises en charge.",
            "PYTHON 3.12 EST PRISE EN CHARGE.",
            "Python 3.13 est Pris En Charge.",
            "Python 3.12 est désormais prise en charge.",
            "Python 3.13 est prisé en chargé.",
            "Python 3.11 est supportée.",
            "Python 3.11 est supportee.",
            "Python 3.13 is supported.",
        ]
        for sentence in claims:
            with self.subTest(sentence=sentence):
                self.assertEqual(_unvalidated_support_claims(sentence), [sentence])

    def test_negated_support_is_not_a_claim(self):
        negations = [
            "Python 3.12 n'est pas prise en charge.",
            "Python 3.13 n'est PAS pris en charge.",
            "Les versions 3.11 à 3.13 ne sont pas prises en charge.",
            "Python 3.12 n'est pas supportée.",
            "Python 3.13 is not supported.",
        ]
        for sentence in negations:
            with self.subTest(sentence=sentence):
                self.assertEqual(_unvalidated_support_claims(sentence), [])

    def test_unrelated_sentences_are_not_claims(self):
        for sentence in [
            "Python 3.14 est prise en charge.",
            "La Phase P3.12 est prise en charge par les tests.",
            "Python 3.12 a été retiré.",
        ]:
            with self.subTest(sentence=sentence):
                self.assertEqual(_unvalidated_support_claims(sentence), [])


if __name__ == "__main__":
    unittest.main()
