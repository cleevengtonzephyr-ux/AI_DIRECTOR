import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.production_gate import ProductionGate


@dataclass
class ExecutionRequest:
    workflow: str
    prompt: str
    duration: int
    resolution: str
    aspect_ratio: str
    mode: str


class HiggsfieldExecutor:
    """
    AI DIRECTOR — Higgsfield Execution Layer v0.1

    Prépare une requête Higgsfield.
    
    IMPORTANT :
    - Aucun job n'est créé.
    - Aucun appel de génération n'est effectué.
    - Aucun crédit n'est dépensé.
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root

    def build_request(self, plan: Any) -> Dict[str, Any]:

        scenes = getattr(plan, "scenes", [])

        prompt_parts = []

        for index, scene in enumerate(scenes, start=1):

            visual = getattr(scene, "visual", "")
            narration = getattr(scene, "narration", "")

            prompt_parts.append(
                f"SCENE {index}\n"
                f"Visual: {visual}\n"
                f"Narration: {narration}"
            )

        prompt = "\n\n".join(prompt_parts)

        duration = getattr(plan, "duration", 40)

        resolution = "720p"
        aspect_ratio = "9:16"

        if scenes:
            resolution = getattr(
                scenes[0],
                "resolution",
                "720p"
            )

            aspect_ratio = getattr(
                scenes[0],
                "aspect_ratio",
                "9:16"
            )

        return {
            "workflow": getattr(
                plan,
                "workflow",
                "cinematic_studio_video_4_0"
            ),
            "prompt": prompt,
            "duration": duration,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "mode": "t2v",
        }

    def dry_run(self, request: Dict[str, Any]) -> None:

        print()
        print("=" * 70)
        print("AI DIRECTOR — HIGGSFIELD EXECUTION LAYER v0.1")
        print("=" * 70)

        print("EXECUTION MODE : DRY-RUN")
        print("HIGGSFIELD CALL : DISABLED")
        print()

        print("REQUEST")
        print("-" * 70)

        print(f"Workflow     : {request['workflow']}")
        print(f"Duration     : {request['duration']}s")
        print(f"Resolution   : {request['resolution']}")
        print(f"Aspect ratio : {request['aspect_ratio']}")
        print(f"Mode         : {request['mode']}")

        print()
        print("PROMPT")
        print("-" * 70)
        print(request["prompt"])

        print()
        print("=" * 70)
        print("EXECUTION STATUS")
        print("=" * 70)
        print("Request prepared : TRUE")
        print("Job created      : FALSE")
        print("Higgsfield called: FALSE")
        print("Credits spent    : 0")
        print("=" * 70)


def main():

    from agents.planner import VideoPlanner

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

    gate = ProductionGate(PROJECT_ROOT)
    decision = gate.evaluate(plan)

    print("=" * 70)
    print("AI DIRECTOR — EXECUTION AUTHORIZATION")
    print("=" * 70)

    print(f"Video ID       : {plan.video_id}")
    print(f"Decision       : {decision.decision}")
    print(
        f"Production ready: "
        f"{decision.production_ready}"
    )

    if not decision.production_ready:

        print()
        print("🛑 EXECUTION REFUSED")
        print("Production Gate is BLOCKED.")
        print("Higgsfield will NOT be called.")

        for number, reason in enumerate(
            decision.reasons,
            start=1
        ):
            print(f"{number}. {reason}")

        print()
        print("NO CREDITS SPENT")
        return

    executor = HiggsfieldExecutor(PROJECT_ROOT)

    request = executor.build_request(plan)

    executor.dry_run(request)


if __name__ == "__main__":
    main()
