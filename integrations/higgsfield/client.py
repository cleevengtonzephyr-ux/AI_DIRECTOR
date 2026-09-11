import json
import subprocess
from typing import Any


class HiggsfieldClient:
    """Safe interface between AI Director and Higgsfield CLI."""

    def __init__(self):
        self.command = r"C:\Users\omnia\AppData\Roaming\npm\higgsfield.cmd"

    def run(self, *args: str) -> Any:
        """Run a Higgsfield CLI command and return JSON when available."""
        command = [self.command, "--json", *args]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(
                f"Higgsfield CLI error:\n{error}"
            )

        output = result.stdout.strip()

        if not output:
            return None

        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return output

    def list_workflows(self) -> Any:
        """Return available Higgsfield workflows."""
        return self.run("workflow", "list")

    def get_workflow(self, workflow_name: str) -> Any:
        """Return parameters for a specific workflow."""
        return self.run("workflow", "get", workflow_name)

    def account_status(self) -> Any:
        """Return the current Higgsfield account status."""
        return self.run("account", "status")

    def estimate_cost(
        self,
        job_type: str,
        prompt: str,
        duration: int | None = None,
        resolution: str | None = None,
        aspect_ratio: str | None = None,
    ) -> Any:
        """Estimate Higgsfield credits without creating a generation job."""

        args = [
            "generate",
            "cost",
            job_type,
            "--prompt",
            prompt,
        ]

        if duration is not None:
            args.extend(["--duration", str(duration)])

        if resolution is not None:
            args.extend(["--resolution", resolution])

        if aspect_ratio is not None:
            args.extend(["--aspect-ratio", aspect_ratio])

        return self.run(*args)
if __name__ == "__main__":
    client = HiggsfieldClient()

    print("Higgsfield Client - TEST")
    print("-" * 40)

    print("ACCOUNT:")
    print(client.account_status())

    print("\nWORKFLOWS:")
    print(client.list_workflows())
