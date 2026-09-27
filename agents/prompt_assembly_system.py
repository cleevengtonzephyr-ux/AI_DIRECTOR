from pathlib import Path
from typing import Dict

from agents.request_id_validation import (
    contained_child_path,
    validate_request_id,
)


class PromptAssemblySystem:
    """
    AI DIRECTOR — Prompt Assembly System v0.1

    Mission:
    - Charger les composants de prompt ZEPHYR.
    - Respecter une structure déterministe.
    - Assembler identité + style + vidéo.
    - Produire un master prompt.
    - Ne jamais appeler Higgsfield.
    - Ne jamais générer de média.
    """

    VERSION = "0.1.0"

    REQUIRED_PROMPTS = {
        "character_identity": "character_identity.md",
        "visual_style": "visual_style.md",
    }

    def __init__(self, project_root: Path):

        self.project_root = Path(project_root)

        self.prompt_root = (
            self.project_root
            / "assets"
            / "zephyr"
            / "prompts"
        )

    def load_prompt(self, filename: str) -> str:

        path = self.prompt_root / filename

        if not path.exists():
            raise FileNotFoundError(
                f"Prompt not found: {path}"
            )

        if not path.is_file():
            raise ValueError(
                f"Prompt path is not a file: {path}"
            )

        content = path.read_text(
            encoding="utf-8"
        ).strip()

        if not content:
            raise ValueError(
                f"Prompt is empty: {path}"
            )

        return content

    def assemble(
        self,
        video_id: str,
    ) -> str:

        # P3.103 (F7) : video_id validé AVANT toute construction de
        # chemin, puis chemin confiné à prompt_root.
        validate_request_id(video_id)

        video_path = contained_child_path(
            self.prompt_root,
            f"video_{video_id}.md",
        )

        character_identity = self.load_prompt(
            self.REQUIRED_PROMPTS[
                "character_identity"
            ]
        )

        visual_style = self.load_prompt(
            self.REQUIRED_PROMPTS[
                "visual_style"
            ]
        )

        video_prompt = self.load_prompt(
            video_path.name
        )

        master_prompt = f"""
ZEPHYR AI — MASTER PRODUCTION PROMPT
====================================

VIDEO ID
--------
{video_id}

====================================
1. CHARACTER IDENTITY
====================================

{character_identity}

====================================
2. VISUAL STYLE
====================================

{visual_style}

====================================
3. VIDEO-SPECIFIC DIRECTION
====================================

{video_prompt}

====================================
4. GLOBAL PRODUCTION RULES
====================================

- Preserve the exact identity of the ZEPHYR avatar.
- Do not alter the avatar's face.
- Maintain visual continuity between scenes.
- Respect the established ZEPHYR visual language.
- Maintain cinematic composition and professional lighting.
- Maintain vertical 9:16 framing.
- Avoid random stylistic changes between scenes.
- Follow the video-specific direction exactly.
- Do not introduce unrelated characters or visual elements.
- The final result must feel like one coherent production.

====================================
END MASTER PROMPT
====================================
""".strip()

        return master_prompt

    def validate(
        self,
        video_id: str,
    ) -> Dict:

        errors = []

        # P3.103 (F7) : refus avant toute construction de chemin.
        try:
            validate_request_id(video_id)
            contained_child_path(
                self.prompt_root,
                f"video_{video_id}.md",
            )
        except ValueError as error:
            return {
                "status": "BLOCKED",
                "errors": [
                    f"Invalid video_id: {error}"
                ],
            }

        required_files = [
            self.REQUIRED_PROMPTS[
                "character_identity"
            ],
            self.REQUIRED_PROMPTS[
                "visual_style"
            ],
            f"video_{video_id}.md",
        ]

        for filename in required_files:

            path = self.prompt_root / filename

            if not path.exists():
                errors.append(
                    f"Missing prompt: {filename}"
                )
                continue

            if not path.is_file():
                errors.append(
                    f"Prompt is not a file: {filename}"
                )
                continue

            if not path.read_text(
                encoding="utf-8"
            ).strip():
                errors.append(
                    f"Prompt is empty: {filename}"
                )

        return {
            "status": (
                "READY"
                if not errors
                else "BLOCKED"
            ),
            "errors": errors,
        }

    def run(
        self,
        video_id: str,
    ) -> str:

        print()
        print("=" * 70)
        print(
            "AI DIRECTOR — "
            "PROMPT ASSEMBLY SYSTEM v0.1"
        )
        print("=" * 70)

        print(
            f"Video ID    : {video_id}"
        )

        validation = self.validate(
            video_id
        )

        print(
            f"Validation  : "
            f"{validation['status']}"
        )

        if validation["status"] != "READY":

            print()
            print("ERRORS")

            for index, error in enumerate(
                validation["errors"],
                start=1,
            ):
                print(
                    f"{index}. {error}"
                )

            raise RuntimeError(
                "Prompt assembly blocked."
            )

        master_prompt = self.assemble(
            video_id
        )

        print(
            "Components  : 3"
        )

        print(
            "Assembly    : READY"
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

        return master_prompt


if __name__ == "__main__":

    project_root = (
        Path(__file__).resolve().parents[1]
    )

    system = PromptAssemblySystem(
        project_root
    )

    prompt = system.run(
        video_id="005"
    )

    print()
    print("MASTER PROMPT")
    print("-" * 70)
    print(prompt)