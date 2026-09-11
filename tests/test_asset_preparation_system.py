"""
Tests de non-régression — AssetPreparationSystem (consolidation assets).

Vérifie que, après délégation de RULES vers le catalogue unique
(asset_catalog.py), les SHA-256 calculés sur les assets réels restent
strictement identiques à ceux déjà enregistrés dans
assets/zephyr/prepared_assets.json (golden snapshot committé en
baseline). Aucun appel Higgsfield.
"""

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.asset_preparation_system import AssetPreparationSystem


GOLDEN_INVENTORY = PROJECT_ROOT / "assets" / "zephyr" / "prepared_assets.json"


class TestAssetPreparationSystem(unittest.TestCase):

    def setUp(self):
        self.system = AssetPreparationSystem(PROJECT_ROOT)
        self.assets = self.system.scan()
        self.validation = self.system.validate(self.assets)

        with GOLDEN_INVENTORY.open(encoding="utf-8") as handle:
            golden = json.load(handle)

        self.golden_by_filename = {
            entry["filename"]: entry for entry in golden["assets"]
        }

    def test_rules_use_shared_catalog(self):
        from agents.asset_catalog import ASSET_CATALOG

        self.assertIs(AssetPreparationSystem.RULES, ASSET_CATALOG)

    def test_validation_status_ready(self):
        self.assertEqual(self.validation["status"], "READY")
        self.assertEqual(self.validation["errors"], [])

    def test_sha256_matches_golden_snapshot(self):
        for asset in self.assets:
            if asset.status != "READY":
                continue

            with self.subTest(filename=asset.filename):
                golden_entry = self.golden_by_filename.get(asset.filename)
                self.assertIsNotNone(
                    golden_entry,
                    f"{asset.filename} absent du golden snapshot",
                )
                self.assertEqual(asset.sha256, golden_entry["sha256"])
                self.assertEqual(asset.role, golden_entry["role"])


if __name__ == "__main__":
    unittest.main()
