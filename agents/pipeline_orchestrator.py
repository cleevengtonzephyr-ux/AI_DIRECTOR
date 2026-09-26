import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, List
import json
from datetime import datetime


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.planner import VideoPlanner
from agents.asset_intake_manager import AssetIntakeManager
from agents.asset_preparation_system import AssetPreparationSystem
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.production_gate import ProductionGate


@dataclass
class PipelineResult:
    video_id: str
    status: str
    stage: str
    messages: List[str] = field(default_factory=list)


class PipelineOrchestrator:
    """
    AI DIRECTOR — Pipeline Orchestrator v0.4

    Secure production architecture:

    PLAN
      ↓
    VALIDATION
      ↓
    ASSET INTAKE
      ↓
    ASSET PREPARATION
      ↓
    PROMPT ASSEMBLY
      ↓
    PRODUCTION GATE
      ↓
    EXECUTION AUTHORIZATION
      ↓
    JOB MONITOR
      ↓
    QA
      ↓
    FINAL VIDEO

    IMPORTANT:
    v0.4 remains DRY-RUN.
    No Higgsfield generation.
    No credits spent.
    """

    VERSION = "0.4.0"

    def __init__(self, project_root: Path):

        self.project_root = Path(project_root)

        self.asset_root = (
            self.project_root
            / "assets"
            / "zephyr"
        )

        self.logs_root = (
            self.project_root
            / "logs"
        )

        self.logs_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.asset_intake = AssetIntakeManager(
            self.asset_root
        )

        self.asset_preparation = AssetPreparationSystem(
            self.project_root
        )

        self.prompt_assembly = PromptAssemblySystem(
            self.project_root
        )

        self.production_gate = ProductionGate(
            self.project_root
        )

        self.events = []

        self.master_prompt = None

    # ============================================================
    # LOGGING
    # ============================================================

    def log_event(
        self,
        stage: str,
        status: str,
        message: str,
    ):

        event = {
            "timestamp": datetime.now().isoformat(),
            "stage": stage,
            "status": status,
            "message": message,
        }

        self.events.append(event)

    def save_log(
        self,
        video_id: str,
    ):

        log_path = (
            self.logs_root
            / f"pipeline_{video_id}.json"
        )

        data = {
            "system": "AI DIRECTOR",
            "version": self.VERSION,
            "video_id": video_id,
            "mode": "DRY-RUN",
            "higgsfield_called": False,
            "generation_performed": False,
            "credits_spent": 0,
            "master_prompt_assembled": self.master_prompt is not None,
            "events": self.events,
        }

        with log_path.open(
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                data,
                file,
                indent=2,
                ensure_ascii=False,
            )

        return log_path

    # ============================================================
    # BLOCK
    # ============================================================

    def block(
        self,
        video_id: str,
        stage: str,
        reasons: List[str],
    ) -> PipelineResult:

        self.log_event(
            stage,
            "BLOCKED",
            "; ".join(reasons),
        )

        print()
        print("=" * 70)
        print("🛑 PIPELINE BLOCKED")
        print("=" * 70)

        print(
            f"Stage : {stage}"
        )

        for index, reason in enumerate(
            reasons,
            start=1,
        ):

            print(
                f"{index}. {reason}"
            )

        print()
        print(
            "HIGGSFIELD : NOT CALLED"
        )

        print(
            "CREDITS SPENT : 0"
        )

        print("=" * 70)

        result = PipelineResult(
            video_id=video_id,
            status="BLOCKED",
            stage=stage,
            messages=reasons,
        )

        self.save_log(
            video_id
        )

        return result

    # ============================================================
    # MAIN PIPELINE
    # ============================================================

    def run(
        self,
        plan: Any,
    ) -> PipelineResult:

        video_id = getattr(
            plan,
            "video_id",
            "UNKNOWN",
        )

        project = getattr(
            plan,
            "project",
            "UNKNOWN",
        )

        print()
        print("=" * 70)
        print(
            "AI DIRECTOR — "
            "PIPELINE ORCHESTRATOR v0.4"
        )
        print("=" * 70)

        print(
            f"Video ID : {video_id}"
        )

        print(
            f"Project  : {project}"
        )

        print(
            "Mode     : DRY-RUN"
        )

        # ========================================================
        # 1 — PLAN VALIDATION
        # ========================================================

        print()
        print("[1/6] PLAN VALIDATION")

        if plan is None:

            return self.block(
                video_id,
                "PLAN_VALIDATION",
                ["Video plan is missing."],
            )

        scenes = getattr(
            plan,
            "scenes",
            [],
        )

        if not scenes:

            return self.block(
                video_id,
                "PLAN_VALIDATION",
                ["Video plan contains no scenes."],
            )

        print(
            f"✅ Plan valid — {len(scenes)} scenes"
        )

        self.log_event(
            "PLAN_VALIDATION",
            "PASS",
            f"{len(scenes)} scenes validated.",
        )

        # ========================================================
        # 2 — ASSET INTAKE
        # ========================================================

        print()
        print("[2/6] ASSET INTAKE")

        records = self.asset_intake.scan()

        validation = self.asset_intake.validate(
            records
        )

        print(
            f"Assets detected : {len(records)}"
        )

        print(
            f"Status          : {validation['status']}"
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

        if validation["status"] != "READY":

            return self.block(
                video_id,
                "ASSET_INTAKE",
                validation["errors"],
            )

        print(
            "✅ Asset Intake passed."
        )

        self.log_event(
            "ASSET_INTAKE",
            "PASS",
            f"{len(records)} assets detected.",
        )

        # ========================================================
        # 3 — ASSET PREPARATION
        # ========================================================

        print()
        print("[3/6] ASSET PREPARATION")

        prepared_assets = (
            self.asset_preparation.scan()
        )

        preparation_validation = (
            self.asset_preparation.validate(
                prepared_assets
            )
        )

        print(
            f"Prepared assets : "
            f"{len(prepared_assets)}"
        )

        print(
            f"Status          : "
            f"{preparation_validation['status']}"
        )

        if preparation_validation["errors"]:

            print()
            print("ERRORS")

            for index, error in enumerate(
                preparation_validation["errors"],
                start=1,
            ):

                print(
                    f"{index}. {error}"
                )

        if preparation_validation["warnings"]:

            print()
            print("WARNINGS"

            )

            for index, warning in enumerate(
                preparation_validation["warnings"],
                start=1,
            ):

                print(
                    f"{index}. {warning}"
                )

        if (
            preparation_validation["status"]
            != "READY"
        ):

            return self.block(
                video_id,
                "ASSET_PREPARATION",
                preparation_validation["errors"],
            )

        print(
            "✅ Asset Preparation passed."
        )

        self.log_event(
            "ASSET_PREPARATION",
            "PASS",
            f"{len(prepared_assets)} assets prepared.",
        )

        # ========================================================
        # 4 — PROMPT ASSEMBLY
        # ========================================================

        print()
        print("[4/6] PROMPT ASSEMBLY")

        try:

            prompt_validation = (
                self.prompt_assembly.validate(
                    video_id
                )
            )

            print(
                f"Validation : "
                f"{prompt_validation['status']}"
            )

            if prompt_validation["errors"]:

                print()
                print("ERRORS")

                for index, error in enumerate(
                    prompt_validation["errors"],
                    start=1,
                ):

                    print(
                        f"{index}. {error}"
                    )

                return self.block(
                    video_id,
                    "PROMPT_ASSEMBLY",
                    prompt_validation["errors"],
                )

            self.master_prompt = (
                self.prompt_assembly.assemble(
                    video_id
                )
            )

            print(
                "Components : 3"
            )

            print(
                "Assembly   : READY"
            )

            print(
                "Master Prompt : READY"
            )

            print(
                "Higgsfield : DISABLED"
            )

            print(
                "Credits    : 0"
            )

            self.log_event(
                "PROMPT_ASSEMBLY",
                "PASS",
                "Master Prompt assembled from character identity, visual style and video-specific direction.",
            )

        except Exception as error:

            return self.block(
                video_id,
                "PROMPT_ASSEMBLY",
                [str(error)],
            )

        # ========================================================
        # 5 — PRODUCTION GATE
        # ========================================================

        print()
        print("[5/6] PRODUCTION GATE")

        gate = self.production_gate.evaluate(
            plan,
            prompt=self.master_prompt,
        )

        print(
            f"Decision : {gate.decision}"
        )

        if gate.reasons:

            print()

            for index, reason in enumerate(
                gate.reasons,
                start=1,
            ):

                print(
                    f"{index}. {reason}"
                )

        if not gate.production_ready:

            return self.block(
                video_id,
                "PRODUCTION_GATE",
                gate.reasons,
            )

        print(
            "✅ Production Gate passed."
        )

        self.log_event(
            "PRODUCTION_GATE",
            "PASS",
            "Production authorization granted.",
        )

        # ========================================================
        # 6 — EXECUTION AUTHORIZATION
        # ========================================================

        print()
        print("[6/6] EXECUTION AUTHORIZATION")

        print(
            "⚠️ DRY-RUN MODE"
        )

        print(
            "Real Higgsfield execution is disabled."
        )

        self.log_event(
            "EXECUTION",
            "DRY-RUN",
            "Higgsfield execution intentionally disabled.",
        )

        result = PipelineResult(
            video_id=video_id,
            status="DRY-RUN",
            stage="EXECUTION",
            messages=[
                "Plan validated.",
                "Assets validated.",
                "Assets prepared.",
                "Master Prompt assembled.",
                "Production Gate passed.",
                "Real generation disabled.",
            ],
        )

        log_path = self.save_log(
            video_id
        )

        print()
        print("=" * 70)
        print("PIPELINE RESULT")
        print("=" * 70)

        print(
            "Status : DRY-RUN"
        )

        print(
            "Stage  : EXECUTION"
        )

        print(
            f"Log    : {log_path}"
        )

        print(
            "Higgsfield : NOT CALLED"
        )

        print(
            "Credits    : 0"
        )

        print("=" * 70)

        return result

    # ============================================================
    # FINAL STATUS
    # ============================================================

    def display_result(
        self,
        result: PipelineResult,
    ):

        print()
        print("=" * 70)
        print(
            "AI DIRECTOR — FINAL PIPELINE STATUS"
        )
        print("=" * 70)

        print(
            f"Video ID : {result.video_id}"
        )

        print(
            f"Status   : {result.status}"
        )

        print(
            f"Stage    : {result.stage}"
        )

        print()
        print("Messages:")

        for message in result.messages:

            print(
                f"- {message}"
            )

        print()
        print(
            "HIGGSFIELD GENERATION : DISABLED"
        )

        print(
            "CREDITS SPENT         : 0"
        )

        print("=" * 70)


def main():

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
            "La discipline construit des empires."
        ),
        objective=(
            "Créer une vidéo courte, cinématique "
            "et motivante expliquant pourquoi "
            "la discipline répétée produit des "
            "résultats supérieurs au talent seul."
        ),
    )

    orchestrator = PipelineOrchestrator(
        PROJECT_ROOT
    )

    result = orchestrator.run(
        plan
    )

    orchestrator.display_result(
        result
    )


if __name__ == "__main__":

    # Correctif encodage console (Windows/PowerShell, codepages non-UTF-8) :
    # les messages du pipeline contiennent des caractères Unicode (✅, 🛑, ⚠️)
    # que certains codepages (ex. cp1252) ne peuvent pas encoder, ce qui fait
    # planter print() avec UnicodeEncodeError. On force stdout/stderr en UTF-8
    # uniquement lors d'une exécution directe du script.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    main()