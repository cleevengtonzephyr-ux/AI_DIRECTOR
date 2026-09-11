import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class QAResult:
    video_id: str
    file_path: str
    status: str
    checks_passed: int
    checks_failed: int
    reasons: List[str]
    retry_recommended: bool


class QAEngine:
    """
    AI DIRECTOR — QA Engine v0.1

    Contrôle qualité après génération.

    Vérifications :
    - présence du fichier
    - extension vidéo
    - taille du fichier
    - durée
    - ratio
    - résolution
    - intégrité simulée

    Cette version fonctionne en simulation.
    Elle ne modifie aucun fichier.
    Elle ne contacte pas Higgsfield.
    """

    SUPPORTED_EXTENSIONS = {
        ".mp4",
        ".mov",
        ".webm",
        ".mkv",
    }

    def __init__(self):
        self.required_checks = [
            "file_exists",
            "extension",
            "file_size",
            "duration",
            "aspect_ratio",
            "resolution",
            "integrity",
        ]

    def check_file_exists(self, file_path: Path) -> bool:
        return file_path.exists()

    def check_extension(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def check_file_size(self, file_path: Path) -> bool:
        if not file_path.exists():
            return False

        return file_path.stat().st_size > 0

    def check_duration(
        self,
        actual_duration: float,
        expected_duration: float,
        tolerance: float = 1.0,
    ) -> bool:
        return abs(actual_duration - expected_duration) <= tolerance

    def check_aspect_ratio(
        self,
        actual_ratio: str,
        expected_ratio: str,
    ) -> bool:
        return actual_ratio == expected_ratio

    def check_resolution(
        self,
        actual_resolution: str,
        expected_resolution: str,
    ) -> bool:
        return actual_resolution == expected_resolution

    def check_integrity(
        self,
        integrity_ok: bool,
    ) -> bool:
        return integrity_ok

    def evaluate(
        self,
        video_id: str,
        file_path: str,
        expected_duration: float,
        actual_duration: float,
        expected_ratio: str,
        actual_ratio: str,
        expected_resolution: str,
        actual_resolution: str,
        integrity_ok: bool,
    ) -> QAResult:

        path = Path(file_path)

        reasons = []
        passed = 0
        failed = 0

        checks = {
            "File exists": self.check_file_exists(path),
            "Extension": self.check_extension(path),
            "File size": self.check_file_size(path),
            "Duration": self.check_duration(
                actual_duration,
                expected_duration,
            ),
            "Aspect ratio": self.check_aspect_ratio(
                actual_ratio,
                expected_ratio,
            ),
            "Resolution": self.check_resolution(
                actual_resolution,
                expected_resolution,
            ),
            "Integrity": self.check_integrity(
                integrity_ok,
            ),
        }

        for name, result in checks.items():

            if result:
                passed += 1
            else:
                failed += 1
                reasons.append(f"{name} check failed.")

        if failed == 0:
            status = "PASS"
            retry_recommended = False
        else:
            status = "FAIL"
            retry_recommended = True

        return QAResult(
            video_id=video_id,
            file_path=str(path),
            status=status,
            checks_passed=passed,
            checks_failed=failed,
            reasons=reasons,
            retry_recommended=retry_recommended,
        )

    def display(self, result: QAResult) -> None:

        print()
        print("=" * 70)
        print("AI DIRECTOR — QA ENGINE")
        print("=" * 70)

        print(f"Video ID          : {result.video_id}")
        print(f"File              : {result.file_path}")
        print(f"QA Status         : {result.status}")
        print(f"Checks passed     : {result.checks_passed}")
        print(f"Checks failed     : {result.checks_failed}")
        print(f"Retry recommended: {result.retry_recommended}")

        if result.reasons:

            print()
            print("QA ISSUES")

            for index, reason in enumerate(
                result.reasons,
                start=1,
            ):
                print(f"{index}. {reason}")

        print("=" * 70)


def create_simulated_file(path: Path) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_bytes(
        b"SIMULATED_VIDEO_DATA"
    )


def simulate_pass(engine: QAEngine) -> None:

    print()
    print("=" * 70)
    print("SCENARIO 1 — VALID VIDEO")
    print("=" * 70)

    file_path = (
        PROJECT_ROOT
        / "outputs"
        / "simulation_valid.mp4"
    )

    create_simulated_file(file_path)

    result = engine.evaluate(
        video_id="SIM-QA-001",
        file_path=str(file_path),
        expected_duration=40,
        actual_duration=40,
        expected_ratio="9:16",
        actual_ratio="9:16",
        expected_resolution="720p",
        actual_resolution="720p",
        integrity_ok=True,
    )

    engine.display(result)


def simulate_fail(engine: QAEngine) -> None:

    print()
    print("=" * 70)
    print("SCENARIO 2 — INVALID VIDEO")
    print("=" * 70)

    file_path = (
        PROJECT_ROOT
        / "outputs"
        / "simulation_invalid.mp4"
    )

    create_simulated_file(file_path)

    result = engine.evaluate(
        video_id="SIM-QA-002",
        file_path=str(file_path),
        expected_duration=40,
        actual_duration=32,
        expected_ratio="9:16",
        actual_ratio="16:9",
        expected_resolution="720p",
        actual_resolution="480p",
        integrity_ok=False,
    )

    engine.display(result)


def simulate_missing_file(engine: QAEngine) -> None:

    print()
    print("=" * 70)
    print("SCENARIO 3 — MISSING VIDEO")
    print("=" * 70)

    file_path = (
        PROJECT_ROOT
        / "outputs"
        / "simulation_missing.mp4"
    )

    if file_path.exists():
        file_path.unlink()

    result = engine.evaluate(
        video_id="SIM-QA-003",
        file_path=str(file_path),
        expected_duration=40,
        actual_duration=40,
        expected_ratio="9:16",
        actual_ratio="9:16",
        expected_resolution="720p",
        actual_resolution="720p",
        integrity_ok=True,
    )

    engine.display(result)


def main():

    engine = QAEngine()

    print()
    print("=" * 70)
    print("AI DIRECTOR — QA ENGINE v0.1")
    print("=" * 70)
    print("MODE              : SIMULATION")
    print("HIGGSFIELD CALL   : DISABLED")
    print("VIDEO GENERATION  : DISABLED")
    print("CREDITS SPENT     : 0")
    print("=" * 70)

    simulate_pass(engine)
    simulate_fail(engine)
    simulate_missing_file(engine)

    print()
    print("=" * 70)
    print("QA ENGINE TEST COMPLETE")
    print("=" * 70)
    print("NO HIGGSFIELD GENERATION")
    print("NO CREDITS SPENT")
    print("=" * 70)


if __name__ == "__main__":
    main()
