"""
AI DIRECTOR — COST ENGINE v0.6

Responsibility:
- Verify Higgsfield account balance.
- Verify the real Higgsfield generation cost.
- Use the official Master Prompt.
- Block production when budget is insufficient.
- NEVER create a generation job.
- NEVER spend credits.
"""

import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Optional


# ============================================================
# PROJECT PATH
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# HIGGSFIELD CLIENT
# ============================================================

from integrations.higgsfield.client import HiggsfieldClient


# ============================================================
# COST ESTIMATE
# ============================================================

@dataclass
class CostEstimate:
    target: str
    duration: int
    resolution: str
    aspect_ratio: str
    estimated_cost: Optional[float]
    available_credits: Optional[float]
    status: str
    message: str


# ============================================================
# COST ENGINE
# ============================================================

class CostEngine:

    VERSION = "0.6"

    def __init__(self):
        self.higgsfield = HiggsfieldClient()

    # ========================================================
    # ACCOUNT BALANCE
    # ========================================================

    def get_available_credits(self) -> Optional[float]:
        """
        Retrieve the current Higgsfield account balance.

        This operation does NOT create a generation job.
        """

        try:
            result = self.higgsfield.account_status()

            if not isinstance(result, dict):
                return None

            credits = result.get("credits")

            if credits is None:
                return None

            return float(credits)

        except Exception:
            return None

    # ========================================================
    # VERIFIED COST
    # ========================================================

    def get_verified_cost(
        self,
        target: str,
        prompt: str,
        duration: int,
        resolution: str,
        aspect_ratio: str,
    ) -> Optional[float]:
        """
        Ask Higgsfield for the real cost of the requested
        configuration.

        This does NOT create a generation job.
        """

        try:
            result = self.higgsfield.estimate_cost(
                job_type=target,
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
            )

            if not isinstance(result, dict):
                return None

            credits = result.get("credits")

            if credits is None:
                return None

            return float(credits)

        except Exception:
            return None

    # ========================================================
    # ESTIMATE
    # ========================================================

    def estimate(
        self,
        target: str,
        prompt: str,
        duration: int,
        resolution: str,
        aspect_ratio: str,
    ) -> CostEstimate:
        """
        Complete cost verification.

        No generation is performed.
        """

        # ----------------------------------------------------
        # PROMPT VALIDATION
        # ----------------------------------------------------

        if not isinstance(prompt, str) or not prompt.strip():

            return CostEstimate(
                target=target,
                duration=duration,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                estimated_cost=None,
                available_credits=None,
                status="BLOCKED",
                message="Master Prompt is missing or empty.",
            )

        # ----------------------------------------------------
        # TARGET VALIDATION
        # ----------------------------------------------------

        if not target:

            return CostEstimate(
                target=target,
                duration=duration,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                estimated_cost=None,
                available_credits=None,
                status="BLOCKED",
                message="Higgsfield target is missing.",
            )

        # ----------------------------------------------------
        # COST VERIFICATION
        # ----------------------------------------------------

        cost = self.get_verified_cost(
            target=target,
            prompt=prompt,
            duration=duration,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
        )

        if cost is None:

            return CostEstimate(
                target=target,
                duration=duration,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                estimated_cost=None,
                available_credits=None,
                status="BLOCKED",
                message="Unable to verify Higgsfield generation cost.",
            )

        # ----------------------------------------------------
        # BALANCE
        # ----------------------------------------------------

        available = self.get_available_credits()

        if available is None:

            return CostEstimate(
                target=target,
                duration=duration,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                estimated_cost=cost,
                available_credits=None,
                status="BLOCKED",
                message="Unable to verify account balance.",
            )

        # ----------------------------------------------------
        # BUDGET
        # ----------------------------------------------------

        if cost > available:

            return CostEstimate(
                target=target,
                duration=duration,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                estimated_cost=cost,
                available_credits=available,
                status="BLOCKED",
                message=(
                    f"Insufficient credits: "
                    f"{available} available "
                    f"< {cost} required."
                ),
            )

        # ----------------------------------------------------
        # APPROVED
        # ----------------------------------------------------

        return CostEstimate(
            target=target,
            duration=duration,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
            estimated_cost=cost,
            available_credits=available,
            status="APPROVED",
            message=(
                "Higgsfield cost verified "
                "and budget sufficient."
            ),
        )

    # ========================================================
    # PLAN EVALUATION
    # ========================================================

    def evaluate_plan(
        self,
        plan: Any,
        prompt: Optional[str] = None,
    ) -> CostEstimate:
        """
        Evaluate a VideoPlan using the official Master Prompt.

        The prompt MUST come from PromptAssemblySystem.
        """

        duration = int(
            getattr(
                plan,
                "duration",
                0,
            )
        )

        workflow = getattr(
            plan,
            "workflow",
            "",
        )

        scenes = getattr(
            plan,
            "scenes",
            [],
        )

        resolution = "720p"
        aspect_ratio = "9:16"

        if scenes:

            resolution = getattr(
                scenes[0],
                "resolution",
                "720p",
            )

            aspect_ratio = getattr(
                scenes[0],
                "aspect_ratio",
                "9:16",
            )

        # ----------------------------------------------------
        # MASTER PROMPT REQUIRED
        # ----------------------------------------------------

        if prompt is None or not prompt.strip():

            return CostEstimate(
                target=workflow,
                duration=duration,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                estimated_cost=None,
                available_credits=None,
                status="BLOCKED",
                message=(
                    "Master Prompt is required "
                    "for cost verification."
                ),
            )

        # ----------------------------------------------------
        # FINAL COST CHECK
        # ----------------------------------------------------

        return self.estimate(
            target=workflow,
            prompt=prompt,
            duration=duration,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
        )

# ============================================================
# TEST / STANDALONE EXECUTION
# ============================================================

def main():

    print()
    print("=" * 70)
    print("AI DIRECTOR — COST ENGINE v0.6")
    print("=" * 70)
    print()
    print("Mode : COST VERIFICATION ONLY")
    print("HIGGSFIELD GENERATION : DISABLED")
    print("CREDITS SPENT         : 0")
    print()

    try:

        from agents.planner import VideoPlanner
        from agents.prompt_assembly_system import PromptAssemblySystem

        planner = VideoPlanner(PROJECT_ROOT)

        plan = planner.create_zephyr_plan(
            video_id="005",
            title="Pourquoi la discipline vaut plus que le talent.",
            hook="Le talent impressionne. La discipline construit des empires.",
            objective=(
                "Montrer que la discipline répétée produit des résultats "
                "supérieurs au talent seul."
            ),
            duration=40,
        )

        assembler = PromptAssemblySystem(PROJECT_ROOT)

        master_prompt = assembler.assemble(
            video_id="005",
        )

        engine = CostEngine()

        result = engine.evaluate_plan(
            plan,
            prompt=master_prompt,
        )

        print("COST VERIFICATION")
        print("-" * 70)
        print(f"Target            : {result.target}")
        print(f"Duration          : {result.duration}s")
        print(f"Resolution        : {result.resolution}")
        print(f"Aspect Ratio      : {result.aspect_ratio}")
        print(f"Estimated Cost    : {result.estimated_cost}")
        print(f"Available Credits : {result.available_credits}")
        print(f"Status            : {result.status}")
        print(f"Message           : {result.message}")
        print()
        print("HIGGSFIELD GENERATION : DISABLED")
        print("CREDITS SPENT         : 0")
        print("=" * 70)

    except Exception as error:

        print()
        print("COST ENGINE TEST FAILED")
        print(f"Error: {error}")
        print()


if __name__ == "__main__":
    main()
