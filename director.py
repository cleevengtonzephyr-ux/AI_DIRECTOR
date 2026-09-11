from pathlib import Path
from integrations.higgsfield.client import HiggsfieldClient


class AIDirector:
    """Core controller for the AI automation system."""

    def __init__(self):
        self.root = Path(__file__).resolve().parent
        self.name = "AI DIRECTOR"
        self.version = "0.2.0"
        self.higgsfield = HiggsfieldClient()

    def check_higgsfield(self):
        """Check that the Higgsfield connector is operational."""
        try:
            workflows = self.higgsfield.list_workflows()

            video_workflows = [
                workflow
                for workflow in workflows
                if workflow.get("type") == "video"
            ]

            cinema_40 = any(
                workflow.get("job_type") == "cinematic_studio_video_4_0"
                for workflow in video_workflows
            )

            return {
                "connected": True,
                "video_workflows": len(video_workflows),
                "cinema_4_available": cinema_40,
            }

        except Exception as error:
            return {
                "connected": False,
                "error": str(error),
            }

    def status(self):
        print("=" * 60)
        print(f"{self.name} v{self.version}")
        print("=" * 60)

        print(f"Project root : {self.root}")
        print("Status       : ONLINE")

        result = self.check_higgsfield()

        if result["connected"]:
            print("Higgsfield   : CONNECTED")
            print(f"Video models : {result['video_workflows']}")
            print(
                "Cinema 4.0   : "
                + ("AVAILABLE" if result["cinema_4_available"] else "NOT FOUND")
            )
        else:
            print("Higgsfield   : ERROR")
            print(f"Error        : {result['error']}")

        print("Claude       : READY FOR INTEGRATION")
        print("=" * 60)


def main():
    director = AIDirector()
    director.status()


if __name__ == "__main__":
    main()