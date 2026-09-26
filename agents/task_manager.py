"""
AI DIRECTOR — Task Manager v0.1 (Phase M, MASTER PROMPT V2)

Nœud "TASK MANAGER" du pipeline :

    USER -> AI DIRECTOR -> PLANNER -> TASK MANAGER -> VIDEO AGENT -> ...

Gère une file de missions vidéo (TaskRecord), chacune associée à un
statut de file (TaskStatus), et délègue leur exécution effective à
AIDirector.run_video_mission() (Phase L) — qui délègue lui-même à
VideoAgent (Phase K), FinalReportService (Phase J), etc. Ce module
n'exécute RIEN lui-même contre Higgsfield : il n'est qu'un
ordonnanceur/registre.

RELATION AVEC L'EXISTANT :
- Ne duplique ni VideoPlanner, ni VideoAgent, ni FinalReportService :
  process() ne fait qu'appeler AIDirector.run_video_mission(), qui
  reste l'unique point d'entrée du pipeline complet.
- Ne modifie AUCUN composant des Phases B-L.

SÉCURITÉ :
- submit() ne fait qu'enregistrer une mission (statut PENDING) —
  aucune estimation, approbation ou génération n'a lieu à cet instant.
- process()/process_next_pending() ne déduisent JAMAIS `approved`
  automatiquement d'un TaskRecord : c'est toujours un paramètre
  explicite du site d'appel, avec `False` par défaut (jamais
  d'approbation implicite).
- Une exception de sécurité (ex. HiggsfieldRealGenerationDisabledError,
  Phase C/D) n'est JAMAIS avalée : process() marque le TaskRecord en
  ERROR puis RE-LÈVE l'exception telle quelle — un incident de sécurité
  ne doit jamais être masqué en simple "tâche échouée" routinière.
- N'importe ni HiggsfieldClient, ni subprocess.
"""

import itertools
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.final_report_service import FinalReport, FinalReportService
from agents.generation_approval_gate import RealGenerationAuthorization
from agents.video_agent import DEFAULT_JOB_TYPE
from director import AIDirector


class TaskStatus(str, Enum):
    """Cycle de vie de la FILE, distinct du résultat pipeline (FinalReportStatus)."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PROCESSED = "PROCESSED"
    ERROR = "ERROR"


@dataclass
class TaskRecord:
    """Une mission vidéo en file, avec son statut et (une fois traitée) son rapport."""

    task_id: str
    video_id: str
    title: str
    hook: str
    objective: str
    duration: int = 40
    job_type: str = DEFAULT_JOB_TYPE
    status: TaskStatus = TaskStatus.PENDING
    report: Optional[FinalReport] = None


class TaskManager:
    """
    AI DIRECTOR — Task Manager v0.1 (Phase M)

    Registre en mémoire de TaskRecord. Ne connaît aucun détail du CLI
    Higgsfield ni du Provider : toute exécution passe par un
    AIDirector fourni par l'appelant.
    """

    def __init__(self):
        self._tasks: Dict[str, TaskRecord] = {}
        self._task_ids = itertools.count(1)

    def submit(
        self,
        video_id: str,
        title: str,
        hook: str,
        objective: str,
        duration: int = 40,
        job_type: str = DEFAULT_JOB_TYPE,
        task_id: Optional[str] = None,
    ) -> TaskRecord:
        """Enregistre une nouvelle mission en file, statut PENDING. N'exécute rien."""

        resolved_id = task_id or f"task-{next(self._task_ids)}"

        if resolved_id in self._tasks:
            raise ValueError(f"Task '{resolved_id}' already exists.")

        record = TaskRecord(
            task_id=resolved_id,
            video_id=video_id,
            title=title,
            hook=hook,
            objective=objective,
            duration=duration,
            job_type=job_type,
        )

        self._tasks[resolved_id] = record
        return record

    def get_task(self, task_id: str) -> TaskRecord:
        if task_id not in self._tasks:
            raise KeyError(f"Unknown task_id: {task_id}")
        return self._tasks[task_id]

    def list_tasks(self) -> List[TaskRecord]:
        return list(self._tasks.values())

    def process(
        self,
        task_id: str,
        director: AIDirector,
        approved: bool = False,
        real_generation_authorization: Optional[RealGenerationAuthorization] = None,
        report_service: Optional[FinalReportService] = None,
        timeout_seconds: float = 600,
        interval_seconds: float = 3,
    ) -> FinalReport:
        """
        Dispatche une tâche PENDING (ou déjà traitée, pour ré-essai)
        vers AIDirector.run_video_mission(). `approved` reste un choix
        explicite de l'appelant — jamais déduit du TaskRecord.

        `real_generation_authorization` (Phase P2.11) : simple relais
        explicite, `None` par défaut, jamais déduit du TaskRecord ni
        d'`approved`.
        """

        task = self.get_task(task_id)
        task.status = TaskStatus.RUNNING

        try:
            report = director.run_video_mission(
                video_id=task.video_id,
                title=task.title,
                hook=task.hook,
                objective=task.objective,
                duration=task.duration,
                job_type=task.job_type,
                approved=approved,
                real_generation_authorization=real_generation_authorization,
                report_service=report_service,
                timeout_seconds=timeout_seconds,
                interval_seconds=interval_seconds,
            )
        except Exception:
            # Ne jamais avaler une exception de sécurité : on marque
            # l'échec puis on la relève telle quelle.
            task.status = TaskStatus.ERROR
            raise

        task.status = TaskStatus.PROCESSED
        task.report = report
        return report

    def process_next_pending(
        self,
        director: AIDirector,
        approved: bool = False,
        real_generation_authorization: Optional[RealGenerationAuthorization] = None,
        report_service: Optional[FinalReportService] = None,
        timeout_seconds: float = 600,
        interval_seconds: float = 3,
    ) -> Optional[FinalReport]:
        """Traite la première tâche PENDING trouvée (ordre d'insertion). None si aucune."""

        for task in self._tasks.values():
            if task.status == TaskStatus.PENDING:
                return self.process(
                    task.task_id,
                    director,
                    approved=approved,
                    real_generation_authorization=real_generation_authorization,
                    report_service=report_service,
                    timeout_seconds=timeout_seconds,
                    interval_seconds=interval_seconds,
                )

        return None
