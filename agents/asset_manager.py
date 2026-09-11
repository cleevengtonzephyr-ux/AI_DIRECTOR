import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.asset_catalog import ASSET_CATALOG
from agents.asset_preparation_system import (
    AssetPreparationSystem,
    PreparedAsset,
)


@dataclass
class Asset:
    name: str
    asset_type: str
    path: Path
    required: bool = True


class AssetManager:
    """
    AI DIRECTOR — Asset Manager v0.2

    Couche ASSET MANAGEMENT de l'architecture cible (audit consolidation
    assets) : stockage, référencement et cycle de vie des assets déjà
    validés/préparés.

    Responsabilités :
    - Organiser les assets d'un projet (structure de dossiers, y compris
      "exports").
    - Vérifier les dossiers nécessaires.
    - Construire le REGISTRE CANONIQUE des assets prêts, par rôle
      sémantique, à partir des résultats d'AssetPreparationSystem
      (aucun recalcul de hash ici — AssetPreparationSystem reste la
      référence pour la préparation/validation).
    - Exposer une API de référencement (get_asset) et de disponibilité
      (is_production_ready) pour les futurs consommateurs
      (PipelineOrchestrator, ProductionGate).
    - Ne lance aucune génération.

    Note (héritage) :
    `scan()` / `Asset` / `get_summary()` proviennent de la v0.1 et
    effectuent un scan de structure superficiel (sans extension/hash).
    Ils sont conservés tels quels pour compatibilité descendante mais
    sont supersédés par `build_registry()` pour tout besoin de
    validation réelle. Candidats à une suppression future une fois
    qu'aucune référence externe n'y sera plus nécessaire.
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.assets_root = project_root / "assets"
        self.project_assets = self.assets_root / "zephyr"

        self.directories = {
            "avatar": self.project_assets / "avatar",
            "references": self.project_assets / "references",
            "audio": self.project_assets / "audio",
            "music": self.project_assets / "music",
            "logo": self.project_assets / "logo",
            "prompts": self.project_assets / "prompts",
            "exports": self.project_assets / "exports",
        }

        self.preparation = AssetPreparationSystem(project_root)

    def initialize(self) -> None:
        """Create the standard ZEPHYR asset structure."""

        for directory in self.directories.values():
            directory.mkdir(parents=True, exist_ok=True)

    def scan(self) -> List[Asset]:
        """Scan available files in the ZEPHYR asset directories."""

        assets = []

        for asset_type, directory in self.directories.items():

            if not directory.exists():
                continue

            for file_path in directory.iterdir():

                if file_path.is_file():
                    assets.append(
                        Asset(
                            name=file_path.name,
                            asset_type=asset_type,
                            path=file_path,
                        )
                    )

        return assets

    def validate_required_structure(self) -> bool:
        """Verify that the complete asset structure exists."""

        return all(
            directory.exists()
            for directory in self.directories.values()
        )

    def get_summary(self) -> dict:

        assets = self.scan()

        summary = {
            "total_assets": len(assets),
            "by_type": {},
        }

        for asset in assets:
            summary["by_type"].setdefault(
                asset.asset_type,
                0
            )
            summary["by_type"][asset.asset_type] += 1

        return summary

    # ============================================================
    # REGISTRE CANONIQUE (couche ASSET MANAGEMENT)
    # ============================================================

    def build_registry(
        self,
        prepared_assets: Optional[List[PreparedAsset]] = None,
    ) -> Dict[str, List[PreparedAsset]]:
        """
        Construit le registre canonique {role: [PreparedAsset READY...]}.

        N'effectue AUCUN calcul de hash : consomme directement la sortie
        d'AssetPreparationSystem.scan() (source de vérité). Un appelant
        qui a déjà un résultat de scan (ex. PipelineOrchestrator) peut le
        passer via `prepared_assets` pour éviter un second scan.
        """

        if prepared_assets is None:
            prepared_assets = self.preparation.scan()

        registry: Dict[str, List[PreparedAsset]] = {}

        for asset in prepared_assets:

            if asset.status != "READY":
                continue

            registry.setdefault(asset.role, []).append(asset)

        return registry

    def get_asset(
        self,
        role: str,
        registry: Optional[Dict[str, List[PreparedAsset]]] = None,
    ) -> Optional[PreparedAsset]:
        """Retourne le premier asset prêt correspondant à un rôle donné."""

        if registry is None:
            registry = self.build_registry()

        candidates = registry.get(role, [])

        return candidates[0] if candidates else None

    def is_production_ready(
        self,
        registry: Optional[Dict[str, List[PreparedAsset]]] = None,
    ) -> bool:
        """
        Vérifie, via le catalogue canonique (ASSET_CATALOG), que chaque
        catégorie obligatoire dispose d'au moins un asset prêt dans le
        registre.
        """

        if registry is None:
            registry = self.build_registry()

        for rule in ASSET_CATALOG.values():

            if not rule["required"]:
                continue

            if not registry.get(rule["role"]):
                return False

        return True

    def display(self) -> None:

        self.initialize()

        assets = self.scan()
        summary = self.get_summary()

        print("=" * 70)
        print("AI DIRECTOR — ASSET MANAGER v0.1")
        print("=" * 70)

        print(f"Project root : {self.project_root}")
        print(f"Asset root   : {self.project_assets}")

        print()
        print("DIRECTORY STRUCTURE")
        print("-" * 70)

        for asset_type, directory in self.directories.items():
            print(f"{asset_type:<12}: {directory}")

        print()
        print("ASSET INVENTORY")
        print("-" * 70)

        if not assets:
            print("No assets found yet.")
        else:
            for asset in assets:
                print(
                    f"{asset.asset_type:<12} "
                    f"{asset.name}"
                )

        print()
        print("SUMMARY")
        print("-" * 70)

        print(f"Total assets : {summary['total_assets']}")

        if summary["by_type"]:
            for asset_type, count in summary["by_type"].items():
                print(f"{asset_type:<12}: {count}")
        else:
            print("No assets registered.")

        print()
        print("STRUCTURE VALID :", self.validate_required_structure())

        print("=" * 70)
        print("DRY-RUN ONLY")
        print("NO HIGGSFIELD CALL")
        print("NO VIDEO GENERATION")
        print("NO CREDITS SPENT")
        print("=" * 70)


def main():

    manager = AssetManager(PROJECT_ROOT)
    manager.display()


if __name__ == "__main__":
    main()
