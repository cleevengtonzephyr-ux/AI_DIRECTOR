"""
AI DIRECTOR — Critical Section Lock (Phase P2.20, MASTER PROMPT V2)

Ferme le risque TOCTOU démontré empiriquement en P2.16 (deux vrais
processus OS pouvaient tous deux lire "non exécuté" avant que l'un des
deux n'appelle `mark_executed()`). Fournit une exclusion mutuelle
LÉGÈRE, request-scoped, autour de la séquence critique complète :

    check-not-executed -> approbation finale (fraîche) -> create_job()
    -> mark_executed()

(cf. `agents/generation_job_service.py::GenerationJobService.execute()`,
qui exécute désormais TOUTE cette séquence à l'intérieur du verrou.)

MÉCANISME :
Création EXCLUSIVE d'un fichier de verrou (`os.O_CREAT | os.O_EXCL`),
un fichier par `request_id`. Cette primitive est atomique au niveau du
système de fichiers, aussi bien sur Windows que POSIX — c'est
exactement la même garantie que celle déjà exploitée par
`FileExecutedRequestStore` pour son écriture atomique
(fichier temporaire + `os.replace`), pas une nouvelle hypothèse. Aucun
service externe, aucune dépendance, pas de SQLite : un mécanisme
disproportionné pour un outil CLI mono-opérateur (cf. rapport P2.19,
section CONCURRENCY).

COMPORTEMENT :
- Non-bloquant : si le fichier de verrou existe déjà, l'acquisition
  ÉCHOUE IMMÉDIATEMENT (`CriticalSectionBusyError`) plutôt que
  d'attendre — FAIL CLOSED explicite, jamais une file d'attente
  silencieuse qui pourrait masquer un blocage.
- Le verrou est TOUJOURS libéré à la sortie du bloc `with`, y compris
  en cas d'exception (`try/finally`).
- PORTÉE HONNÊTE : cette primitive protège contre deux processus
  s'exécutant sur LA MÊME MACHINE et partageant LE MÊME répertoire de
  verrous (donc, dans ce projet, le même `self.root / "state" /
  "locks"`). Elle NE prétend PAS résoudre une exécution distribuée
  multi-machine — aucune tentative n'est faite dans ce sens.
- LIMITE CONNUE, NON MASQUÉE : un crash du processus PENDANT qu'il
  détient le verrou (avant que le `finally` ne s'exécute) laisse un
  fichier de verrou orphelin. Ce module ne tente PAS de détecter ou
  d'expirer automatiquement un verrou orphelin (pas de TTL inventé) :
  un tel crash correspond de toute façon à une situation qui nécessite
  déjà une revue humaine (cf. `agents/generation_job_service.py`,
  état `EXECUTION_STATE_UNKNOWN`), donc exiger un nettoyage manuel du
  fichier de verrou après une telle revue est un choix DÉLIBÉRÉMENT
  fail-closed plutôt qu'une fausse commodité.

`NoOpCriticalSectionLock` est le verrou par défaut de
`GenerationJobService` (Phase P2.20) : AUCUNE exclusion mutuelle,
comportement STRICTEMENT identique à avant cette phase pour tout code
qui construit `GenerationJobService(provider, gate)` sans argument
supplémentaire. Le chemin de production réel (director.py) injecte
explicitement un `FileCriticalSectionLock`.
"""

import os
import time
from contextlib import contextmanager
from pathlib import Path

from agents.request_id_validation import contained_child_path, validate_request_id

# Phase P3.98 (D4b) : nouvel essai borné de la suppression du verrou à la
# libération (cf. `FileCriticalSectionLock.acquire()`).
_RELEASE_RETRY_SECONDS = 1.0
_RELEASE_RETRY_INTERVAL_SECONDS = 0.005


class CriticalSectionBusyError(RuntimeError):
    """
    Levée quand le verrou de section critique ne peut pas être acquis
    pour un `request_id` donné -- une autre exécution (autre processus,
    ou bloc `with` non encore sorti dans ce même processus) le détient
    déjà. FAIL CLOSED : ne déclenche jamais d'attente ni de retry
    automatique ; l'appelant (GenerationJobService.execute()) laisse
    cette exception se propager sans jamais tenter `create_job()`.
    """


class NoOpCriticalSectionLock:
    """
    Verrou par défaut : AUCUNE exclusion mutuelle. Préserve exactement
    le comportement d'avant P2.20 pour tout test/code existant qui ne
    fournit pas de verrou explicite à `GenerationJobService`.
    """

    @contextmanager
    def acquire(self, request_id: str):
        yield


class FileCriticalSectionLock:
    """
    Verrou request-scoped basé sur la création exclusive d'un fichier.
    Un fichier de verrou par `request_id`, sous `lock_dir`.
    """

    def __init__(self, lock_dir: Path):
        self.lock_dir = Path(lock_dir)

    @contextmanager
    def acquire(self, request_id: str):
        # Phase P3.103 (F7) : `request_id` validé AVANT toute construction
        # de chemin, puis chemin confiné à `lock_dir` -- refus immédiat,
        # avant toute écriture disque et tout create_job() (fail closed).
        try:
            validate_request_id(request_id)
            lock_path = contained_child_path(self.lock_dir, f"{request_id}.lock")
        except ValueError as error:
            raise CriticalSectionBusyError(
                f"Critical section for request {request_id!r} refused: "
                f"{error} -- refusing to proceed (fail-closed)."
            ) from error

        self.lock_dir.mkdir(parents=True, exist_ok=True)

        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
        except FileExistsError as error:
            raise CriticalSectionBusyError(
                f"Critical section for request '{request_id}' is already "
                f"locked (lock file '{lock_path}' exists) -- refusing to "
                f"proceed (fail-closed). Another execution may currently "
                f"be in progress for this exact request."
            ) from error
        except PermissionError as error:
            # Phase P3.98 (D4a) : sous Windows, la création exclusive est
            # refusée pendant la suppression du verrou d'un détenteur
            # concurrent. Même issue que ci-dessus -- refus immédiat, sans
            # attente, avant toute évaluation et tout create_job() ; une
            # vraie erreur d'ACL est refusée de la même façon (fail closed),
            # la cause d'origine restant chaînée.
            raise CriticalSectionBusyError(
                f"Critical section for request '{request_id}' could not be "
                f"acquired (lock file '{lock_path}' refused: {error}) -- "
                f"refusing to proceed (fail-closed)."
            ) from error

        try:
            yield
        finally:
            try:
                os.close(fd)
            finally:
                release_deadline = time.monotonic() + _RELEASE_RETRY_SECONDS
                while True:
                    try:
                        lock_path.unlink()
                    except PermissionError:
                        # Phase P3.98 (D4b) : sous Windows, un handle
                        # externe ouvert sur le verrou fait échouer la
                        # suppression ; abandonner aussitôt laissait
                        # orphelin un verrou libéré proprement. Nouvel
                        # essai, borné -- ensuite comportement inchangé.
                        if time.monotonic() < release_deadline:
                            time.sleep(_RELEASE_RETRY_INTERVAL_SECONDS)
                            continue
                    except OSError:
                        # Le verrou est déjà "perdu" (ex. supprimé
                        # manuellement pendant qu'il était détenu) --
                        # rien de plus à faire ici ; ne masque jamais une
                        # exception survenue DANS le bloc `with` (celle-ci
                        # se propage normalement via ce `finally`).
                        pass
                    break
