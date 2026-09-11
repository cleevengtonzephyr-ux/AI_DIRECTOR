from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict
import json
import hashlib


@dataclass
class PreparedAsset:
    category: str
    filename: str
    path: str
    extension: str
    size_bytes: int
    sha256: str
    status: str
    role: str


class AssetPreparationSystem:
    """
    AI DIRECTOR — Asset Preparation System v0.1

    Mission:
    - Inspecter les assets ZEPHYR.
    - Identifier les fichiers utilisables.
    - Détecter les doublons.
    - Vérifier les extensions.
    - Préparer un registre propre.
    - Ne jamais appeler Higgsfield.
    - Ne jamais générer de média.
    """

    RULES = {
        "avatar": {
            "required": True,
            "extensions": [".png", ".jpg", ".jpeg", ".webp"],
            "role": "master_avatar",
        },
        "references": {
            "required": True,
            "extensions": [".png", ".jpg", ".jpeg", ".webp"],
            "role": "face_reference",
        },
        "audio": {
            "required": True,
            "extensions": [".wav", ".mp3", ".m4a", ".aac"],
            "role": "main_voice",
        },
        "prompts": {
            "required": True,
            "extensions": [".txt", ".md", ".json"],
            "role": "production_prompts",
        },
        "music": {
            "required": False,
            "extensions": [".wav", ".mp3", ".m4a", ".aac"],
            "role": "background_music",
        },
        "logo": {
            "required": False,
            "extensions": [
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
                ".svg",
            ],
            "role": "brand_logo",
        },
    }

    def __init__(self, project_root: Path):

        self.project_root = Path(project_root)
        self.asset_root = (
            self.project_root
            / "assets"
            / "zephyr"
        )

        self.inventory_path = (
            self.asset_root
            / "prepared_assets.json"
        )

        self.asset_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        for category in self.RULES:
            (
                self.asset_root / category
            ).mkdir(
                parents=True,
                exist_ok=True,
            )

    def calculate_hash(
        self,
        path: Path,
    ) -> str:

        sha256 = hashlib.sha256()

        with path.open(
            "rb"
        ) as file:

            for chunk in iter(
                lambda: file.read(1024 * 1024),
                b"",
            ):
                sha256.update(chunk)

        return sha256.hexdigest()

    def scan(self) -> List[PreparedAsset]:

        assets = []

        for category, rule in self.RULES.items():

            folder = (
                self.asset_root / category
            )

            for path in sorted(
                folder.iterdir()
            ):

                if not path.is_file():
                    continue

                extension = (
                    path.suffix.lower()
                )

                size = path.stat().st_size

                if (
                    extension
                    not in rule["extensions"]
                ):
                    status = "INVALID_EXTENSION"

                elif size == 0:
                    status = "EMPTY"

                else:
                    status = "READY"

                file_hash = ""

                if status == "READY":
                    file_hash = self.calculate_hash(
                        path
                    )

                assets.append(
                    PreparedAsset(
                        category=category,
                        filename=path.name,
                        path=str(path),
                        extension=extension,
                        size_bytes=size,
                        sha256=file_hash,
                        status=status,
                        role=rule["role"],
                    )
                )

        return assets

    def detect_duplicates(
        self,
        assets: List[PreparedAsset],
    ) -> List[str]:

        hashes: Dict[str, str] = {}
        duplicates = []

        for asset in assets:

            if not asset.sha256:
                continue

            if asset.sha256 in hashes:

                duplicates.append(
                    f"{asset.filename} "
                    f"is identical to "
                    f"{hashes[asset.sha256]}"
                )

            else:

                hashes[
                    asset.sha256
                ] = asset.filename

        return duplicates

    def validate(
        self,
        assets: List[PreparedAsset],
    ):

        errors = []
        warnings = []

        for category, rule in self.RULES.items():

            category_assets = [
                asset
                for asset in assets
                if asset.category == category
            ]

            valid_assets = [
                asset
                for asset in category_assets
                if asset.status == "READY"
            ]

            if (
                rule["required"]
                and not valid_assets
            ):

                errors.append(
                    f"Required asset "
                    f"'{category}' "
                    f"is missing or invalid."
                )

            if len(valid_assets) > 1:

                warnings.append(
                    f"Multiple valid files "
                    f"found in '{category}'. "
                    f"Primary selection required."
                )

        duplicates = self.detect_duplicates(
            assets
        )

        warnings.extend(
            [
                f"Duplicate: {item}"
                for item in duplicates
            ]
        )

        return {
            "status": (
                "READY"
                if not errors
                else "BLOCKED"
            ),
            "errors": errors,
            "warnings": warnings,
        }

    def save_inventory(
        self,
        assets: List[PreparedAsset],
        validation: dict,
    ):

        data = {
            "system": (
                "AI DIRECTOR — "
                "Asset Preparation System"
            ),
            "version": "0.1",
            "project": "ZEPHYR AI",
            "status": validation["status"],
            "assets": [
                asdict(asset)
                for asset in assets
            ],
            "validation": validation,
            "higgsfield_called": False,
            "generation_performed": False,
            "credits_spent": 0,
        }

        with self.inventory_path.open(
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                data,
                file,
                indent=2,
                ensure_ascii=False,
            )

    def run(self):

        print()
        print("=" * 70)
        print(
            "AI DIRECTOR — "
            "ASSET PREPARATION SYSTEM v0.1"
        )
        print("=" * 70)

        print(
            f"Asset root : {self.asset_root}"
        )

        assets = self.scan()

        print(
            f"Assets found : {len(assets)}"
        )

        print()
        print("ASSET ANALYSIS")
        print("-" * 70)

        for category, rule in self.RULES.items():

            category_assets = [
                asset
                for asset in assets
                if asset.category == category
            ]

            valid = [
                asset
                for asset in category_assets
                if asset.status == "READY"
            ]

            invalid = [
                asset
                for asset in category_assets
                if asset.status != "READY"
            ]

            required_label = (
                "REQUIRED"
                if rule["required"]
                else "OPTIONAL"
            )

            print(
                f"{category:<15}"
                f"{required_label:<11}"
                f"READY={len(valid):<5}"
                f"INVALID={len(invalid)}"
            )

        validation = self.validate(
            assets
        )

        self.save_inventory(
            assets,
            validation,
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
                print(
                    f"{index}. {error}"
                )

        if validation["warnings"]:

            print()
            print("WARNINGS")

            for index, warning in enumerate(
                validation["warnings"],
                start=1,
            ):
                print(
                    f"{index}. {warning}"
                )

        print()
        print(
            f"Inventory : {self.inventory_path}"
        )

        print()
        print(
            "HIGGSFIELD CALL : DISABLED"
        )

        print(
            "VIDEO GENERATION: DISABLED"
        )

        print(
            "CREDITS SPENT   : 0"
        )

        print("=" * 70)

        return validation


if __name__ == "__main__":

    project_root = (
        Path(__file__).resolve().parents[1]
    )

    system = AssetPreparationSystem(
        project_root
    )

    system.run()
