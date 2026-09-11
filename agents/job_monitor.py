import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class JobState(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    RETRYING = "RETRYING"
    FAILED = "FAILED"


@dataclass
class JobStatus:
    job_id: str
    state: JobState
    attempt: int = 1
    max_retries: int = 2
    progress: int = 0
    result: Optional[str] = None
    error: Optional[str] = None


class JobMonitor:
    """
    AI DIRECTOR — Job Monitor v0.1

    Responsabilités :
    - Suivre l'état d'un job de génération.
    - Détecter SUCCESS / ERROR.
    - Gérer les retries.
    - Ne jamais lancer lui-même une génération.
    - Cette version fonctionne uniquement en simulation.
    """

    def __init__(self, max_retries: int = 2):
        self.max_retries = max_retries

    def create_job(self, job_id: str) -> JobStatus:
        return JobStatus(
            job_id=job_id,
            state=JobState.CREATED,
            max_retries=self.max_retries,
        )

    def transition(
        self,
        job: JobStatus,
        state: JobState,
        progress: int = 0,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> JobStatus:

        job.state = state
        job.progress = progress
        job.result = result
        job.error = error

        return job

    def retry(self, job: JobStatus) -> JobStatus:

        if job.attempt >= job.max_retries + 1:
            return self.transition(
                job,
                JobState.FAILED,
                progress=0,
                error="Maximum retry attempts reached.",
            )

        job.attempt += 1

        return self.transition(
            job,
            JobState.RETRYING,
            progress=0,
            error=None,
        )

    def display(self, job: JobStatus) -> None:

        print()
        print("=" * 70)
        print("AI DIRECTOR — JOB MONITOR")
        print("=" * 70)

        print(f"Job ID        : {job.job_id}")
        print(f"State         : {job.state.value}")
        print(f"Attempt       : {job.attempt}/{job.max_retries + 1}")
        print(f"Progress      : {job.progress}%")

        if job.result:
            print(f"Result        : {job.result}")

        if job.error:
            print(f"Error         : {job.error}")

        print("=" * 70)


def simulate_success(monitor: JobMonitor) -> None:

    print()
    print("=" * 70)
    print("SCENARIO 1 — SUCCESS")
    print("=" * 70)

    job = monitor.create_job("SIM-001")
    monitor.display(job)

    monitor.transition(job, JobState.QUEUED)
    monitor.display(job)

    monitor.transition(job, JobState.RUNNING, progress=25)
    monitor.display(job)

    monitor.transition(job, JobState.RUNNING, progress=60)
    monitor.display(job)

    monitor.transition(
        job,
        JobState.SUCCESS,
        progress=100,
        result="simulation_video_001.mp4",
    )
    monitor.display(job)


def simulate_error_and_retry(monitor: JobMonitor) -> None:

    print()
    print("=" * 70)
    print("SCENARIO 2 — ERROR → RETRY → SUCCESS")
    print("=" * 70)

    job = monitor.create_job("SIM-002")

    monitor.transition(job, JobState.QUEUED)
    monitor.transition(job, JobState.RUNNING, progress=35)

    monitor.transition(
        job,
        JobState.ERROR,
        progress=35,
        error="Simulated generation timeout.",
    )

    monitor.display(job)

    monitor.retry(job)
    monitor.display(job)

    monitor.transition(job, JobState.RUNNING, progress=50)
    monitor.display(job)

    monitor.transition(
        job,
        JobState.SUCCESS,
        progress=100,
        result="simulation_video_002.mp4",
    )
    monitor.display(job)


def simulate_max_retries(monitor: JobMonitor) -> None:

    print()
    print("=" * 70)
    print("SCENARIO 3 — ERROR → RETRIES → FAILED")
    print("=" * 70)

    job = monitor.create_job("SIM-003")

    monitor.transition(job, JobState.RUNNING, progress=20)

    monitor.transition(
        job,
        JobState.ERROR,
        progress=20,
        error="Simulated provider error.",
    )
    monitor.display(job)

    while job.state != JobState.FAILED:

        monitor.retry(job)
        monitor.display(job)

        if job.state == JobState.FAILED:
            break

        monitor.transition(
            job,
            JobState.ERROR,
            progress=20,
            error="Simulated repeated provider error.",
        )
        monitor.display(job)


def main():

    monitor = JobMonitor(max_retries=2)

    print()
    print("=" * 70)
    print("AI DIRECTOR — JOB MONITOR v0.1")
    print("=" * 70)
    print("MODE : SIMULATION")
    print("HIGGSFIELD CALL : DISABLED")
    print("CREDITS SPENT   : 0")
    print("=" * 70)

    simulate_success(monitor)
    simulate_error_and_retry(monitor)
    simulate_max_retries(monitor)

    print()
    print("=" * 70)
    print("JOB MONITOR TEST COMPLETE")
    print("=" * 70)
    print("NO HIGGSFIELD GENERATION")
    print("NO CREDITS SPENT")
    print("=" * 70)


if __name__ == "__main__":
    main()
