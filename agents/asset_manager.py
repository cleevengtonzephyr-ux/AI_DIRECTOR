import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Asset:
    name: str
    asset_type: str
    path: Path
    required: bool = True


class AssetManager:
    """
    AI DIRECTOR — Asset Manager v0.1

    Responsabilités :
    - Organiser les assets d'un projet.
    - Vérifier les dossiers nécessaires.
    - Identifier les assets disponibles/manquants.
    - Préparer les références pour la génération.
    - Ne lance aucune génération.
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
