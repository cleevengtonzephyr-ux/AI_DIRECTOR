import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = PROJECT_ROOT / "assets" / "zephyr"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.asset_catalog import ASSET_CATALOG


@dataclass
class AssetRecord:
    category: str
    filename: str
    path: str
    extension: str
    size_bytes: int
    required: bool


class AssetIntakeManager:
    """
    AI DIRECTOR — Asset Intake Manager v0.1

    Mission :
    - Scanner les assets ZEPHYR.
    - Classer les fichiers.
    - Détecter les fichiers manquants.
    - Détecter les doublons.
    - Générer un inventaire JSON.
    - Ne lancer aucune génération.
    """

    # Règles de catégorie déléguées au catalogue unique (agents/asset_catalog.py)
    # afin d'éviter la duplication avec AssetPreparationSystem/AssetManager.
    CATEGORIES = ASSET_CATALOG

    def __init__(self, asset_root: Path):
        self.asset_root = asset_root

    def scan_category(
        self,
        category: str,
        configuration: Dict,
    ) -> List[AssetRecord]:

        category_path = self.asset_root / category

        category_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        records = []

        for file_path in sorted(category_path.iterdir()):

            if not file_path.is_file():
                continue

            records.append(
                AssetRecord(
                    category=category,
                    filename=file_path.name,
                    path=str(file_path),
                    extension=file_path.suffix.lower(),
                    size_bytes=file_path.stat().st_size,
                    required=configuration["required"],
                )
            )

        return records

    def scan(self) -> List[AssetRecord]:

        records = []

        for category, configuration in self.CATEGORIES.items():

            records.extend(
                self.scan_category(
                    category,
                    configuration,
                )
            )

        return records

    def validate(
        self,
        records: List[AssetRecord],
    ) -> Dict:

        errors = []
        warnings = []

        for category, configuration in self.CATEGORIES.items():

            category_records = [
                record
                for record in records
                if record.category == category
            ]

            if configuration["required"] and not category_records:
                errors.append(
                    f"Required category '{category}' is empty."
                )

            if len(category_records) > 1:
                warnings.append(
                    f"Category '{category}' contains "
                    f"{len(category_records)} files."
                )

            allowed = configuration["extensions"]

            for record in category_records:

                if record.extension not in allowed:

                    errors.append(
                        f"Invalid extension in '{category}': "
                        f"{record.filename}"
                    )

                if record.size_bytes == 0:

                    errors.append(
                        f"Empty file detected: "
                        f"{record.filename}"
                    )

        status = "READY" if not errors else "BLOCKED"

        return {
            "status": status,
            "errors": errors,
            "warnings": warnings,
        }

    def create_inventory(
        self,
        records: List[AssetRecord],
        validation: Dict,
    ) -> Path:

        inventory_path = (
            self.asset_root
            / "asset_inventory.json"
        )

        payload = {
            "project": "ZEPHYR AI",
            "asset_root": str(self.asset_root),
            "status": validation["status"],
            "assets": [
                asdict(record)
                for record in records
            ],
            "errors": validation["errors"],
            "warnings": validation["warnings"],
        }

        inventory_path.write_text(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return inventory_path

    def display(
        self,
        records: List[AssetRecord],
        validation: Dict,
        inventory_path: Path,
    ) -> None:

        print()
        print("=" * 70)
        print("AI DIRECTOR — ASSET INTAKE MANAGER v0.1")
        print("=" * 70)

        print(f"Asset root : {self.asset_root}")
        print(f"Assets     : {len(records)}")
        print()

        print("CATEGORY INVENTORY")
        print("-" * 70)

        for category, configuration in self.CATEGORIES.items():

            category_records = [
                record
                for record in records
                if record.category == category
            ]

            required_text = (
                "REQUIRED"
                if configuration["required"]
                else "OPTIONAL"
            )

            status = (
                "FOUND"
                if category_records
                else "MISSING"
            )

            print(
                f"{category:<15} "
                f"{required_text:<10} "
                f"{status:<10} "
                f"{len(category_records)} file(s)"
            )

        print()
        print("VALIDATION")
        print("-" * 70)

        print(
            f"Status : {validation['status']}"
        )

        if validation["errors"]:

            print()
            print("ERRORS")

            for index, error in enumerate(
                validation["errors"],
                start=1,
            ):
                print(f"{index}. {error}")

        if validation["warnings"]:

            print()
            print("WARNINGS")

            for index, warning in enumerate(
                validation["warnings"],
                start=1,
            ):
                print(f"{index}. {warning}")

        print()
        print(f"Inventory : {inventory_path}")

        print("=" * 70)
        print("HIGGSFIELD CALL : DISABLED")
        print("VIDEO GENERATION: DISABLED")
        print("CREDITS SPENT   : 0")
        print("=" * 70)


def main():

    manager = AssetIntakeManager(
        ASSET_ROOT
    )

    records = manager.scan()

    validation = manager.validate(
        records
    )

    inventory_path = manager.create_inventory(
        records,
        validation,
    )

    manager.display(
        records,
        validation,
        inventory_path,
    )


if __name__ == "__main__":
    main()
