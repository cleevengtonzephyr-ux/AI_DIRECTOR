import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.cost_engine import CostEngine


@dataclass
class ProductionDecision:
    video_id: str
    project: str
    workflow: str
    decision: str
    reason: str
    generation_allowed: bool


class ProductionController:
    """
    AI DIRECTOR — Production Controller v0.1

    Sécurité :
    - Analyse le plan avant toute génération.
    - Utilise le Cost Engine comme Production Gate.
    - BLOCKED = aucune génération autorisée.
    - APPROVED = génération théoriquement autorisable.
    - Cette version n'exécute AUCUNE génération Higgsfield.
    """

    def __init__(self):
        self.cost_engine = CostEngine()

    def evaluate(self, plan: Any) -> ProductionDecision:

        estimate = self.cost_engine.evaluate_plan(plan)

        video_id = getattr(plan, "video_id", "UNKNOWN")
        project = getattr(plan, "project", "UNKNOWN")
        workflow = getattr(plan, "workflow", "UNKNOWN")

        if estimate.status != "APPROVED":
            return ProductionDecision(
                video_id=video_id,
                project=project,
                workflow=workflow,
                decision="BLOCKED",
                reason=estimate.message,
                generation_allowed=False,
            )

        return ProductionDecision(
            video_id=video_id,
            project=project,
            workflow=workflow,
            decision="APPROVED",
            reason=estimate.message,
            generation_allowed=False,
        )

    def display(self, decision: ProductionDecision) -> None:

        print()
        print("=" * 70)
        print("AI DIRECTOR — PRODUCTION CONTROLLER")
        print("=" * 70)

        print(f"Project            : {decision.project}")
        print(f"Video ID           : {decision.video_id}")
        print(f"Workflow           : {decision.workflow}")
        print(f"Decision           : {decision.decision}")
        print(f"Reason             : {decision.reason}")
        print(
            f"Generation allowed: "
            f"{decision.generation_allowed}"
        )

        print("=" * 70)

        if decision.decision == "BLOCKED":
            print("🛑 PRODUCTION BLOCKED")
            print("Higgsfield generation will NOT be executed.")
        else:
            print("✅ PRODUCTION APPROVED")
            print("⚠️ Generation remains disabled in v0.1.")

        print("=" * 70)
        print("DRY-RUN ONLY")
        print("NO VIDEO GENERATION")
        print("NO CREDITS SPENT")
        print("=" * 70)


def main():

    from planner import VideoPlanner

    planner = VideoPlanner(PROJECT_ROOT)

    plan = planner.create_zephyr_plan(
        video_id="005",
        title="Pourquoi la discipline vaut plus que le talent.",
        hook="Le talent impressionne. La discipline construit des empires.",
        objective=(
            "Créer une vidéo courte, cinématique et motivante "
            "expliquant pourquoi la discipline répétée produit "
            "des résultats supérieurs au talent seul."
        ),
        duration=40,
    )

    controller = ProductionController()

    print("=" * 70)
    print("AI DIRECTOR — PRODUCTION DECISION")
    print("=" * 70)

    decision = controller.evaluate(plan)

    controller.display(decision)


if __name__ == "__main__":
    main()
