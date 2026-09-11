"""
Tests de non-régression — Asset Catalog (consolidation assets).

Vérifie que le catalogue unique (agents/asset_catalog.py) expose bien,
pour chaque catégorie, les trois clés attendues par AssetIntakeManager,
AssetPreparationSystem et AssetManager : required, extensions, role.

Aucun appel Higgsfield. Aucune génération. Lecture seule.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.asset_catalog import ASSET_CATALOG


EXPECTED_CATEGORIES = {
    "avatar",
    "references",
    "audio",
    "prompts",
    "music",
    "logo",
}

EXPECTED_REQUIRED = {
    "avatar": True,
    "references": True,
    "audio": True,
    "prompts": True,
    "music": False,
    "logo": False,
}


class TestAssetCatalog(unittest.TestCase):

    def test_categories_match_expected_set(self):
        self.assertEqual(set(ASSET_CATALOG.keys()), EXPECTED_CATEGORIES)

    def test_each_category_has_required_extensions_role(self):
        for category, rule in ASSET_CATALOG.items():
            with self.subTest(category=category):
                self.assertIn("required", rule)
                self.assertIsInstance(rule["required"], bool)

                self.assertIn("extensions", rule)
                self.assertIsInstance(rule["extensions"], tuple)
                self.assertGreater(len(rule["extensions"]), 0)
                for extension in rule["extensions"]:
                    self.assertTrue(extension.startswith("."))

                self.assertIn("role", rule)
                self.assertIsInstance(rule["role"], str)
                self.assertTrue(rule["role"])

    def test_required_flags_match_expected(self):
        for category, expected in EXPECTED_REQUIRED.items():
            with self.subTest(category=category):
                self.assertEqual(
                    ASSET_CATALOG[category]["required"],
                    expected,
                )

    def test_roles_are_unique(self):
        roles = [rule["role"] for rule in ASSET_CATALOG.values()]
        self.assertEqual(len(roles), len(set(roles)))


if __name__ == "__main__":
    unittest.main()
