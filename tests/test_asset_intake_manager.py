"""
Tests de non-régression — AssetIntakeManager (consolidation assets).

Vérifie que la découverte des assets ZEPHYR réels reste correcte après
la délégation de CATEGORIES vers le catalogue unique (asset_catalog.py).

Utilise les assets réels déjà présents dans assets/zephyr/. Aucune
écriture n'est vérifiée ici au-delà de l'inventaire JSON déjà produit
par le système lui-même. Aucun appel Higgsfield.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.asset_intake_manager import AssetIntakeManager, ASSET_ROOT


class TestAssetIntakeManager(unittest.TestCase):

    def setUp(self):
        self.manager = AssetIntakeManager(ASSET_ROOT)
        self.records = self.manager.scan()
        self.validation = self.manager.validate(self.records)

    def test_categories_use_shared_catalog(self):
        from agents.asset_catalog import ASSET_CATALOG

        self.assertIs(AssetIntakeManager.CATEGORIES, ASSET_CATALOG)

    def test_required_assets_detected(self):
        categories_found = {record.category for record in self.records}

        for required_category in ("avatar", "references", "audio", "prompts"):
            with self.subTest(category=required_category):
                self.assertIn(required_category, categories_found)

    def test_validation_status_ready(self):
        self.assertEqual(self.validation["status"], "READY")
        self.assertEqual(self.validation["errors"], [])


if __name__ == "__main__":
    unittest.main()
