import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class AssetRequirement:
    name: str
    asset_type: str
    required: bool
    found: bool
    path: Path | None


class AssetResolver:
    """
    AI DIRECTOR — Asset Resolver v0.1

    Vérifie les assets nécessaires avant production.
    Aucun appel Higgsfield.
    Aucun crédit consommé.
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.assets_root = project_root / "assets" / "zephyr"

    def find_first_file(self, directory: Path):
        if not directory.exists():
            return None

        files = [
            file
            for file in directory.iterdir()
            if file.is_file()
        ]

        return files[0] if files else None

    def resolve(self) -> List[AssetRequirement]:

        requirements = [
            ("Avatar maître", "avatar", True),
            ("Référence visage", "references", True),
            ("Voix principale", "audio", True),
            ("Prompts", "prompts", True),
            ("Musique", "music", False),
            ("Logo", "logo", False),
        ]

        resolved = []

        for name, asset_type, required in requirements:

            directory = self.assets_root / asset_type
            path = self.find_first_file(directory)

            resolved.append(
                AssetRequirement(
                    name=name,
                    asset_type=asset_type,
                    required=required,
                    found=path is not None,
                    path=path,
                )
            )

        return resolved

    def is_ready(self, requirements):

        return all(
            requirement.found
            for requirement in requirements
            if requirement.required
        )

    def display(self):

        requirements = self.resolve()
        ready = self.is_ready(requirements)

        print("=" * 70)
        print("AI DIRECTOR — ASSET RESOLVER v0.1")
        print("=" * 70)

        print(f"Asset root : {self.assets_root}")
        print()

        print("REQUIRED ASSETS")
        print("-" * 70)

        for requirement in requirements:

            status = "FOUND" if requirement.found else "MISSING"

            required_label = (
                "REQUIRED"
                if requirement.required
                else "OPTIONAL"
            )

            print(
                f"{requirement.name:<22} "
                f"{required_label:<9} "
                f"{status}"
            )

            if requirement.path:
                print(
                    f"  → {requirement.path}"
                )

        print()
        print("=" * 70)

        if ready:
            print("ASSET STATUS : READY")
            print("All required assets are available.")
        else:
            print("ASSET STATUS : BLOCKED")
            print("One or more required assets are missing.")

        print("=" * 70)
        print("DRY-RUN ONLY")
        print("NO HIGGSFIELD CALL")
        print("NO VIDEO GENERATION")
        print("NO CREDITS SPENT")
        print("=" * 70)


def main():

    resolver = AssetResolver(PROJECT_ROOT)
    resolver.display()


if __name__ == "__main__":
    main()
