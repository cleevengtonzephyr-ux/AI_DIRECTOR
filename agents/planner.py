import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any

# Add project root to Python path
PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from integrations.higgsfield.client import HiggsfieldClient


@dataclass
class Scene:
    number: int
    duration: int
    narration: str
    visual_prompt: str
    camera: str
    aspect_ratio: str = "9:16"
    resolution: str = "720p"


@dataclass
class VideoPlan:
    project: str
    video_id: str
    title: str
    hook: str
    objective: str
    duration: int
    workflow: str
    scenes: List[Scene] = field(default_factory=list)


class VideoPlanner:
    """Production planner connected to Higgsfield."""

    def __init__(self, root: Path):
        self.root = root
        self.higgsfield = HiggsfieldClient()

    def get_higgsfield_workflow(self) -> Dict[str, Any]:
        """Read Higgsfield workflow configuration."""
        return self.higgsfield.get_workflow(
            "cinematic_studio_video_4_0"
        )

    def create_zephyr_plan(
        self,
        video_id: str,
        title: str,
        hook: str,
        objective: str,
        duration: int = 40,
    ) -> VideoPlan:

        scenes = [
            Scene(
                number=1,
                duration=5,
                narration=hook,
                visual_prompt=(
                    "Cinematic futuristic scene, recurring Zephyr AI avatar, "
                    "identical face and identity, dark modern environment, "
                    "premium Hollywood cinematography, realistic lighting."
                ),
                camera="Slow cinematic push-in",
            ),

            Scene(
                number=2,
                duration=7,
                narration="Le talent impressionne. Mais il ne suffit pas.",
                visual_prompt=(
                    "Same Zephyr AI avatar and identical face, walking through "
                    "a futuristic city at night, massive architecture, "
                    "cinematic depth, realistic film lighting."
                ),
                camera="Smooth tracking shot",
            ),

            Scene(
                number=3,
                duration=8,
                narration=(
                    "Ce qui crée réellement la différence, c'est ce que "
                    "tu répètes lorsque personne ne regarde."
                ),
                visual_prompt=(
                    "Same character identity, close cinematic portrait, "
                    "focused expression, dramatic lighting, dark background, "
                    "intense psychological atmosphere."
                ),
                camera="Slow orbital camera movement",
            ),

            Scene(
                number=4,
                duration=8,
                narration=(
                    "La discipline transforme une petite action répétée "
                    "en résultat extraordinaire."
                ),
                visual_prompt=(
                    "Same Zephyr avatar working alone in a futuristic studio, "
                    "holographic interfaces, focused work session, cinematic "
                    "realism, premium futuristic atmosphere."
                ),
                camera="Slow lateral dolly",
            ),

            Scene(
                number=5,
                duration=7,
                narration=(
                    "Le talent peut ouvrir une porte. La discipline te "
                    "fait rester dans la pièce."
                ),
                visual_prompt=(
                    "Same avatar walking toward a gigantic illuminated "
                    "futuristic doorway, powerful backlight, atmospheric fog, "
                    "cinematic scale."
                ),
                camera="Low-angle forward tracking shot",
            ),

            Scene(
                number=6,
                duration=5,
                narration=(
                    "Le futur appartient à ceux qui continuent. "
                    "Transmission ZEPHYR."
                ),
                visual_prompt=(
                    "Same Zephyr avatar facing camera, dark premium "
                    "background, subtle futuristic light accents, confident "
                    "expression, minimal cinematic composition."
                ),
                camera="Static cinematic hero shot",
            ),
        ]

        return VideoPlan(
            project="ZEPHYR AI",
            video_id=video_id,
            title=title,
            hook=hook,
            objective=objective,
            duration=duration,
            workflow="cinematic_studio_video_4_0",
            scenes=scenes,
        )

    def validate_plan(self, plan: VideoPlan) -> Dict[str, Any]:
        """Validate the plan against the real Higgsfield schema."""

        workflow = self.get_higgsfield_workflow()

        # Higgsfield stores generation parameters in "params".
        workflow_params = workflow.get("params", [])

        available_parameters = {
            parameter.get("name")
            for parameter in workflow_params
            if isinstance(parameter, dict)
        }

        required_parameters = {
            parameter.get("name")
            for parameter in workflow_params
            if isinstance(parameter, dict)
            and parameter.get("required") is True
        }

        missing_required = required_parameters - available_parameters

        total_scene_duration = sum(
            scene.duration for scene in plan.scenes
        )

        # Verify the settings selected by our planner.
        aspect_ratio_supported = any(
            parameter.get("name") == "aspect_ratio"
            and "9:16" in parameter.get("enum", [])
            for parameter in workflow_params
            if isinstance(parameter, dict)
        )

        resolution_supported = any(
            parameter.get("name") == "resolution"
            and "720p" in parameter.get("enum", [])
            for parameter in workflow_params
            if isinstance(parameter, dict)
        )

        duration_supported = "duration" in available_parameters
        prompt_supported = "prompt" in available_parameters

        valid = all([
            len(plan.scenes) > 0,
            total_scene_duration == plan.duration,
            not missing_required,
            aspect_ratio_supported,
            resolution_supported,
            duration_supported,
            prompt_supported,
        ])

        return {
            "valid": valid,
            "workflow": plan.workflow,
            "scenes": len(plan.scenes),
            "planned_duration": total_scene_duration,
            "requested_duration": plan.duration,
            "required_parameters": sorted(required_parameters),
            "available_parameters": sorted(available_parameters),
            "missing_required": sorted(missing_required),
            "aspect_ratio_9_16": aspect_ratio_supported,
            "resolution_720p": resolution_supported,
            "duration_supported": duration_supported,
            "prompt_supported": prompt_supported,
        }

    def export_plan(self, plan: VideoPlan) -> str:

        lines = [
            "=" * 70,
            "AI DIRECTOR — VIDEO PRODUCTION PLAN",
            "=" * 70,
            f"Project    : {plan.project}",
            f"Video ID   : {plan.video_id}",
            f"Title      : {plan.title}",
            f"Duration   : {plan.duration}s",
            f"Workflow   : {plan.workflow}",
            "",
            "SCENES",
            "-" * 70,
        ]

        for scene in plan.scenes:
            lines.extend([
                "",
                f"[SCENE {scene.number}] — {scene.duration}s",
                f"Narration : {scene.narration}",
                f"Camera    : {scene.camera}",
                f"Format    : {scene.aspect_ratio}",
                f"Resolution: {scene.resolution}",
                f"Visual    : {scene.visual_prompt}",
            ])

        lines.extend([
            "",
            "=" * 70,
            "DRY-RUN ONLY",
            "NO VIDEO GENERATION",
            "NO CREDITS SPENT",
            "=" * 70,
        ])

        return "\n".join(lines)


def main():

    root = Path(__file__).resolve().parents[1]

    planner = VideoPlanner(root)

    print("=" * 70)
    print("AI DIRECTOR — PLANNER TEST")
    print("=" * 70)

    print("\n[1] Reading Higgsfield workflow...")

    workflow = planner.get_higgsfield_workflow()

    print("Workflow : cinematic_studio_video_4_0")
    print("Status   : READ SUCCESSFULLY")

    plan = planner.create_zephyr_plan(
        video_id="005",
        title="Pourquoi la discipline vaut plus que le talent.",
        hook="Le talent impressionne. La discipline construit des empires.",
        objective=(
            "Créer une vidéo courte, cinématique et motivante expliquant "
            "pourquoi la discipline répétée produit des résultats "
            "supérieurs au talent seul."
        ),
        duration=40,
    )

    print("\n[2] Validating production plan...")

    validation = planner.validate_plan(plan)

    print(f"Valid              : {validation['valid']}")
    print(f"Scenes             : {validation['scenes']}")
    print(f"Duration           : {validation['planned_duration']}s")
    print(f"Prompt supported   : {validation['prompt_supported']}")
    print(f"9:16 supported     : {validation['aspect_ratio_9_16']}")
    print(f"720p supported     : {validation['resolution_720p']}")
    print(f"Duration supported : {validation['duration_supported']}")
    print(f"Missing required   : {validation['missing_required']}")

    print("\n[3] Production plan")

    print(planner.export_plan(plan))


if __name__ == "__main__":
    main()