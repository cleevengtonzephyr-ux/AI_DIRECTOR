import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.cost_engine import CostEngine
from agents.asset_resolver import AssetResolver


@dataclass
class GateDecision:
    video_id: str
    project: str
    workflow: str
    decision: str
    reasons: List[str]
    production_ready: bool


class ProductionGate:
    """
    AI DIRECTOR — Production Gate v0.3

    Verrou central avant toute production.

    Conditions :
    1. Le plan doit être valide.
    2. Le Master Prompt doit être présent.
    3. Le coût réel Higgsfield doit être vérifié.
    4. Le budget doit être suffisant.
    5. Les assets obligatoires doivent être présents.

    Cette version ne lance aucune génération.
    """

    VERSION = "0.3"

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.cost_engine = CostEngine()
        self.asset_resolver = AssetResolver(project_root)

    def evaluate(
        self,
        plan: Any,
        prompt: Optional[str] = None,
    ) -> GateDecision:

        reasons = []

        # ---------------------------------------------------------
        # 1. PLAN VALIDATION
        # ---------------------------------------------------------

        if plan is None:

            reasons.append("Video plan is missing.")

        else:

            scenes = getattr(
                plan,
                "scenes",
                [],
            )

            if not scenes:
                reasons.append(
                    "Video plan contains no scenes."
                )

        # ---------------------------------------------------------
        # 2. MASTER PROMPT VALIDATION
        # ---------------------------------------------------------

        if not isinstance(prompt, str) or not prompt.strip():

            reasons.append(
                "Master Prompt is missing or empty."
            )

        # ---------------------------------------------------------
        # 3. COST VALIDATION
        # ---------------------------------------------------------

        if plan is not None and prompt:

            cost_estimate = self.cost_engine.evaluate_plan(
                plan,
                prompt=prompt,
            )

            if cost_estimate.status != "APPROVED":

                reasons.append(
                    f"Budget: {cost_estimate.message}"
                )

        # ---------------------------------------------------------
        # 4. ASSET VALIDATION
        # ---------------------------------------------------------

        assets = self.asset_resolver.resolve()

        required_missing = [
            asset.name
            for asset in assets
            if asset.required and not asset.found
        ]

        if required_missing:

            reasons.append(
                "Missing required assets: "
                + ", ".join(required_missing)
            )

        # ---------------------------------------------------------
        # 5. FINAL DECISION
        # ---------------------------------------------------------

        ready = len(reasons) == 0

        decision = (
            "READY"
            if ready
            else "BLOCKED"
        )

        return GateDecision(
            video_id=getattr(
                plan,
                "video_id",
                "UNKNOWN",
            ),
            project=getattr(
                plan,
                "project",
                "UNKNOWN",
            ),
            workflow=getattr(
                plan,
                "workflow",
                "UNKNOWN",
            ),
            decision=decision,
            reasons=reasons,
            production_ready=ready,
        )

    def display(
        self,
        decision: GateDecision,
    ) -> None:

        print()
        print("=" * 70)
        print("AI DIRECTOR — PRODUCTION GATE v0.3")
        print("=" * 70)

        print(
            f"Project          : "
            f"{decision.project}"
        )

        print(
            f"Video ID         : "
            f"{decision.video_id}"
        )

        print(
            f"Workflow         : "
            f"{decision.workflow}"
        )

        print(
            f"Final decision   : "
            f"{decision.decision}"
        )

        print(
            f"Production ready : "
            f"{decision.production_ready}"
        )

        print()

        if decision.reasons:

            print("BLOCKING REASONS")
            print("-" * 70)

            for number, reason in enumerate(
                decision.reasons,
                start=1,
            ):
                print(
                    f"{number}. {reason}"
                )

        else:

            print(
                "NO BLOCKING REASONS"
            )

        print()
        print("=" * 70)

        if decision.production_ready:

            print(
                "READY FOR PRODUCTION"
            )

            print(
                "Higgsfield execution "
                "remains disabled."
            )

        else:

            print(
                "PRODUCTION BLOCKED"
            )

            print(
                "Higgsfield generation "
                "will NOT be executed."
            )

        print("=" * 70)
        print("DRY-RUN ONLY")
        print("NO VIDEO GENERATION")
        print("NO CREDITS SPENT")
        print("=" * 70)


def main():

    from agents.planner import VideoPlanner
    from agents.prompt_assembly_system import (
        PromptAssemblySystem
    )

    planner = VideoPlanner(
        PROJECT_ROOT
    )

    plan = planner.create_zephyr_plan(
        video_id="005",
        title=(
            "Pourquoi la discipline "
            "vaut plus que le talent."
        ),
        hook=(
            "Le talent impressionne. "
            "La discipline construit "
            "des empires."
        ),
        objective=(
            "Créer une vidéo courte, "
            "cinématique et motivante "
            "expliquant pourquoi la "
            "discipline répétée produit "
            "des résultats supérieurs "
            "au talent seul."
        ),
        duration=40,
    )

    assembler = PromptAssemblySystem(
        PROJECT_ROOT
    )

    master_prompt = assembler.assemble(
        video_id="005"
    )

    gate = ProductionGate(
        PROJECT_ROOT
    )

    print("=" * 70)
    print(
        "AI DIRECTOR — CENTRAL PRODUCTION CHECK"
    )
    print("=" * 70)

    decision = gate.evaluate(
        plan,
        prompt=master_prompt,
    )

    gate.display(
        decision
    )


if __name__ == "__main__":
    main()