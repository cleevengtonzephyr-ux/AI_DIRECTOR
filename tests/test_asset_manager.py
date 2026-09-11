"""
Tests de non-régression — AssetManager v0.2 (registre canonique).

Vérifie la nouvelle couche ASSET MANAGEMENT introduite par la
consolidation : build_registry() / get_asset() / is_production_ready().

Important : le scan d'AssetPreparationSystem (avec calcul SHA-256)
n'est effectué QU'UNE SEULE FOIS dans setUp() et son résultat est
réutilisé pour tous les tests, afin de ne jamais recalculer de hash
en double (voir agents/asset_manager.py::build_registry).

Aucun appel Higgsfield. Aucune génération.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.asset_manager import AssetManager
from agents.asset_preparation_system import AssetPreparationSystem


class TestAssetManagerRegistry(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Un seul scan (donc un seul calcul de hash) partagé par tous les tests.
        preparation = AssetPreparationSystem(PROJECT_ROOT)
        cls.prepared_assets = preparation.scan()

        cls.manager = AssetManager(PROJECT_ROOT)
        cls.registry = cls.manager.build_registry(cls.prepared_assets)

    def test_registry_contains_required_roles(self):
        for role in (
            "master_avatar",
            "face_reference",
            "main_voice",
            "production_prompts",
        ):
            with self.subTest(role=role):
                self.assertIn(role, self.registry)
                self.assertGreater(len(self.registry[role]), 0)

    def test_get_asset_returns_ready_asset(self):
        avatar = self.manager.get_asset("master_avatar", self.registry)

        self.assertIsNotNone(avatar)
        self.assertEqual(avatar.status, "READY")
        self.assertEqual(avatar.role, "master_avatar")

    def test_get_asset_returns_none_for_unknown_role(self):
        result = self.manager.get_asset("unknown_role", self.registry)
        self.assertIsNone(result)

    def test_is_production_ready_true_with_current_assets(self):
        self.assertTrue(
            self.manager.is_production_ready(self.registry)
        )

    def test_is_production_ready_false_when_required_role_missing(self):
        incomplete_registry = {
            role: assets
            for role, assets in self.registry.items()
            if role != "master_avatar"
        }

        self.assertFalse(
            self.manager.is_production_ready(incomplete_registry)
        )

    def test_build_registry_does_not_recompute_hash_when_assets_supplied(self):
        # En passant explicitement prepared_assets, build_registry() ne doit
        # déclencher aucun nouveau scan/hash (pas d'appel à preparation.scan()).
        calls = {"count": 0}
        original_scan = self.manager.preparation.scan

        def tracked_scan():
            calls["count"] += 1
            return original_scan()

        self.manager.preparation.scan = tracked_scan
        try:
            self.manager.build_registry(self.prepared_assets)
        finally:
            self.manager.preparation.scan = original_scan

        self.assertEqual(calls["count"], 0)


if __name__ == "__main__":
    unittest.main()
