"""
Tests -- Phase P3.91 : P2 EXECUTION SAFETY HARDENING.

Ferme les deux risques démontrés par l'audit P3.90 :

- RISK #1 : un crash (dur : processus tué ; ou "doux" : KeyboardInterrupt,
  exception de create_job() après acceptation côté backend) entre
  `create_job()` et `mark_executed()` ne laissait aucune trace : le Gate
  renvoyait APPROVED et un second job était créé. Fermé par le
  write-ahead `in_flight()` (agents/executed_request_store.py).
- RISK #2 : `FileExecutedRequestStore` faisait READ -> MODIFY -> WRITE
  sans verrou global : des écritures concurrentes sur des request_id
  DIFFÉRENTS s'écrasaient (pertes silencieuses, puis rejeu approuvé).
  Fermé par le verrou global du fichier.

Méthode : VRAIS processus OS (`os._exit` / `Popen.kill()` = aucun
`finally`), store temporaire, MockHiggsfieldProvider uniquement, et un
"ledger backend" factice qui compte les jobs réellement acceptés. Aucun
appel réseau, aucun CLI, aucun crédit ; le state/ réel n'est jamais
touché.
"""

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.critical_section_lock import CriticalSectionBusyError, FileCriticalSectionLock
from agents.executed_request_store import (
    ExecutedRequestStoreConflictError,
    ExecutedRequestStoreCorruptedError,
    ExecutedRequestStoreLockTimeoutError,
    FileExecutedRequestStore,
    InMemoryExecutedRequestStore,
)
from agents.generation_approval_gate import (
    GenerationApprovalDecision as D,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from tests.real_provider_path_fixtures import (
    FIXTURE_MAX_COST_CREDITS_PER_REQUEST,
    fixture_identity_lock_for,
    install_create_job_probe,
)
from tests.real_provider_path_fixtures import fixture_real_path_gate_kwargs
from tests.authorization_content_helpers import bind_request, content_media
from agents.generation_job_service import GenerationJobExecutionError, GenerationJobService
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider

WORKER_FLAG = "--p391-worker"
RID = "p391-req"


def _request(request_id=RID) -> GenerationRequest:
    return bind_request(GenerationRequest(
        **content_media(),
        request_id=request_id,
        job_type="seedance_2_0",
        prompt="Un prompt de test suffisamment explicite.",
        duration=5,
        approved=True,
        real_generation_authorization=RealGenerationAuthorization(
            request_id=request_id, authorized_by_human=True
        ),
    ))


def _paths(sandbox: Path):
    return sandbox / "state" / "executed_requests.json", sandbox / "state" / "locks"


def _chain(sandbox: Path, scenario: str = "none", lock_timeout: float = 10.0, request_ids=(RID,)):
    """Chaîne réelle Gate + Service + FileCriticalSectionLock +
    FileExecutedRequestStore, sur un store temporaire, avec un Provider
    mock dont chaque job accepté est consigné dans un ledger factice."""

    state_path, lock_dir = _paths(sandbox)
    ledger = sandbox / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)

    # Phase D : Mock RECONNU (un Provider qui redéfinit create_job()
    # n'atteint plus la frontière). Les crochets de crash sont portés par
    # `install_create_job_probe()` sur `gate.in_flight()` -- à l'instant de
    # l'appel (C1), puis juste après le retour de create_job(), avant
    # `mark_executed()` (ledger, C2) -- et par `wait_for_job` remplacé sur
    # l'instance, hors frontière `create_job` (C5).
    provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)

    def _at_create_job(params):
        if scenario == "C1_hard":
            os._exit(91)  # avant tout effet côté backend

    def _after_create_job():
        job_id, job = list(provider._jobs.items())[-1]
        (ledger / f"{job['request_id']}-{os.getpid()}-{time.perf_counter_ns()}").write_text(job_id)
        if scenario == "C2_hard":
            os._exit(92)  # backend a accepté, réponse perdue
        if scenario == "C2_soft":
            raise TimeoutError("[p3.91] response lost after the backend accepted the job")

    def _wait_for_job(job_id, **kwargs):
        if scenario == "C5_hard":
            os._exit(95)
        return MockHiggsfieldProvider.wait_for_job(provider, job_id, **kwargs)

    provider.on_create = _at_create_job
    provider.after_create_job = _after_create_job
    provider.wait_for_job = _wait_for_job
    store = FileExecutedRequestStore(state_path, lock_timeout_seconds=lock_timeout)
    # Phase D : fixtures EXPLICITES conservées (sans effet sur le Mock
    # reconnu) : plafond + Identity Lock lié aux `request_ids` évalués.
    gate = install_create_job_probe(
        GenerationApprovalGate(
            provider,
            executed_request_store=store,
            **fixture_real_path_gate_kwargs(*(_request(request_id) for request_id in request_ids)),
        ),
        provider,
    )

    if scenario == "pre_write_ahead_hard":
        original_begin = store._begin_in_flight

        def _dying_begin(request_id):
            os.replace = lambda src, dst: os._exit(90)  # tmp écrit, jamais renommé
            return original_begin(request_id)

        store._begin_in_flight = _dying_begin

    original_mark = gate.mark_executed

    def _mark_executed(request_id, job_id=None):
        if scenario == "C3_hard":
            os._exit(93)
        if scenario == "C3_soft":
            raise KeyboardInterrupt("[p3.91] Ctrl+C right before mark_executed()")
        if scenario in ("C4_hard", "C4_soft"):
            def _dying_replace(src, dst):
                if scenario == "C4_hard":
                    os._exit(94)
                raise KeyboardInterrupt("[p3.91] Ctrl+C inside os.replace()")

            os.replace = _dying_replace
        return original_mark(request_id, job_id=job_id)

    gate.mark_executed = _mark_executed
    service = GenerationJobService(provider, gate, lock=FileCriticalSectionLock(lock_dir))
    return store, gate, service


def _ledger_count(sandbox: Path, request_id=RID) -> int:
    return len(list((sandbox / "ledger").glob(f"{request_id}-*")))


# ----------------------------------------------------------------------
# Worker entry point (vrais processus, jamais exécuté par unittest)
# ----------------------------------------------------------------------


def _wait_for_go(sandbox: Path, wid: str):
    (sandbox / f"ready-{wid}").write_text("1")
    while not (sandbox / "go").exists():
        time.sleep(0.001)


def _worker(mode, sandbox, *args):
    sandbox = Path(sandbox)
    if mode == "execute":
        scenario, request_id, wid = args
        _, _, service = _chain(sandbox, scenario, request_ids=(request_id,))
        if wid != "-":
            _wait_for_go(sandbox, wid)
        try:
            outcome = service.execute(_request(request_id), timeout_seconds=5, interval_seconds=0)
            print(json.dumps({"result": "EXECUTED", "job_id": outcome.job.job_id}))
        except BaseException as error:  # noqa: B902 -- rapport, puis sortie non nulle
            print(json.dumps({"result": type(error).__name__}))
            sys.exit(1)
    elif mode == "store":
        wid, ids_csv, prefix, use_lock, forever = args
        state_path, lock_dir = _paths(sandbox)
        store = FileExecutedRequestStore(state_path)
        lock = FileCriticalSectionLock(lock_dir)
        _wait_for_go(sandbox, wid)
        ok, errors, busy = [], {}, 0
        while True:
            for request_id in ids_csv.split(","):
                try:
                    if use_lock == "1":
                        with lock.acquire(request_id):
                            store.mark_executed(request_id, job_id=f"{prefix}-{request_id}")
                    else:
                        store.mark_executed(request_id, job_id=f"{prefix}-{request_id}")
                    ok.append(request_id)
                    if forever == "1":
                        # P3.97 : marqueur atomique -- un `write_text()` direct
                        # tué entre création et écriture laissait un `ok-*`
                        # vide, lu comme id '' par l'oracle de test_c6.
                        tmp = sandbox / f".tmp-ok-{wid}-{len(ok)}"
                        tmp.write_text(request_id)
                        os.replace(tmp, sandbox / f"ok-{wid}-{len(ok)}")
                except CriticalSectionBusyError:
                    busy += 1
                except Exception as error:
                    errors[type(error).__name__] = errors.get(type(error).__name__, 0) + 1
            if forever != "1":
                break
            ids_csv = ",".join(f"{wid}-{len(ok)}-{i}" for i in range(5))
        print(json.dumps({"ok": ok, "errors": errors, "busy": busy, "prefix": prefix}))
    elif mode == "hold_store_lock":
        state_path, _ = _paths(sandbox)
        with FileExecutedRequestStore(state_path)._locked(context="p3.91 holder", write=True):
            (sandbox / "held").write_text("1")
            time.sleep(120)
    elif mode == "hold_cs_lock":
        _, lock_dir = _paths(sandbox)
        with FileCriticalSectionLock(lock_dir).acquire(RID):
            (sandbox / "held").write_text("1")
            time.sleep(120)


def _run_worker(*args, timeout=120):
    completed = subprocess.run(
        [sys.executable, "-B", __file__, WORKER_FLAG, *map(str, args)],
        capture_output=True, text=True, timeout=timeout,
    )
    lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
    return completed.returncode, (json.loads(lines[-1]) if lines else {"stderr": completed.stderr[-500:]})


def _spawn_worker(*args):
    return subprocess.Popen(
        [sys.executable, "-B", __file__, WORKER_FLAG, *map(str, args)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def _release_barrier(sandbox: Path, count: int, timeout=120):
    deadline = time.monotonic() + timeout
    while len(list(sandbox.glob("ready-*"))) < count:
        if time.monotonic() > deadline:
            raise AssertionError("workers never reached the start barrier")
        time.sleep(0.01)
    (sandbox / "go").write_text("1")


def _wait_for_file(path: Path, timeout=60):
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() > deadline:
            raise AssertionError(f"{path.name} never appeared")
        time.sleep(0.01)


class _SandboxCase(unittest.TestCase):
    def setUp(self):
        self.sandbox = Path(tempfile.mkdtemp(prefix="p3_91_"))
        self.addCleanup(shutil.rmtree, self.sandbox, ignore_errors=True)
        self.state_path, self.lock_dir = _paths(self.sandbox)

    def _state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _restart(self, lock_timeout=10.0, request_ids=(RID,)):
        store, gate, service = _chain(self.sandbox, lock_timeout=lock_timeout, request_ids=request_ids)
        return store, gate, service

    def _operator_removes_orphan_locks(self):
        """Revue humaine : retire les verrous orphelins (section
        critique ET store) -- jamais fait automatiquement."""

        candidates = list(self.lock_dir.glob("*.lock")) if self.lock_dir.exists() else []
        candidates += list(self.state_path.parent.glob("*.json.lock"))
        for path in candidates:
            path.unlink()
        return sorted(p.name for p in candidates)


# ----------------------------------------------------------------------
# RISK #1 -- crash matrix (P3.90 A1..A6), vrais processus
# ----------------------------------------------------------------------


class TestRisk1CrashMatrix(_SandboxCase):
    """Pour chaque point de crash : état du store, UNKNOWN, restart,
    recovery (suppression manuelle du verrou orphelin, procédure
    documentée par agents/critical_section_lock.py), puis rejeu. Le
    ledger backend ne doit JAMAIS dépasser 1 job."""

    def _crash_then_recover(self, scenario):
        rc, crash = _run_worker("execute", self.sandbox, scenario, RID, "-")
        self.assertNotEqual(rc, 0, crash)
        jobs_after_crash = _ledger_count(self.sandbox)

        # Restart : nouveau processus (celui-ci), nouvelles instances.
        _, gate, _ = self._restart(lock_timeout=0.5)
        decision_after_restart = gate.evaluate(_request()).decision

        # Recovery : l'opérateur retire les verrous orphelins.
        removed = self._operator_removes_orphan_locks()
        _, gate, _ = self._restart()
        decision_after_recovery = gate.evaluate(_request()).decision

        # Replay après recovery, dans un nouveau processus normal.
        replay_rc, replay = _run_worker("execute", self.sandbox, "none", RID, "-")
        return {
            "jobs_after_crash": jobs_after_crash,
            "decision_after_restart": decision_after_restart,
            "decision_after_recovery": decision_after_recovery,
            "orphan_locks": removed,
            "replay": replay.get("result"),
            "jobs_total": _ledger_count(self.sandbox),
            "tmp_files": sorted(p.name for p in self.state_path.parent.glob(".tmp-*")),
        }

    def _assert_blocked_forever(self, r, jobs, after_restart=D.EXECUTION_STATE_UNKNOWN):
        self.assertEqual(r["jobs_after_crash"], jobs)
        self.assertEqual(r["decision_after_restart"], after_restart)
        self.assertEqual(r["decision_after_recovery"], D.EXECUTION_STATE_UNKNOWN)
        self.assertEqual(r["replay"], "GenerationJobExecutionError")
        self.assertEqual(r["jobs_total"], jobs, "double execution after recovery")
        store, gate, _ = self._restart()
        self.assertTrue(store.is_unknown(RID))
        self.assertFalse(store.is_executed(RID))
        self.assertEqual(gate.evaluate(_request()).decision, D.EXECUTION_STATE_UNKNOWN)

    def test_crash_while_writing_the_write_ahead_never_reaches_create_job(self):
        r = self._crash_then_recover("pre_write_ahead_hard")
        # Le marqueur n'a jamais été rendu durable : create_job() n'a
        # donc structurellement jamais pu être appelé -> l'absence de
        # trace est ici une preuve, et la reprise exécute UNE fois.
        # Crash DANS la section protégée du store : verrou du store
        # orphelin -> BLOCKED (fail closed) jusqu'à la revue humaine.
        self.assertEqual(r["jobs_after_crash"], 0)
        self.assertEqual(r["decision_after_restart"], D.BLOCKED)
        self.assertEqual(r["orphan_locks"], ["executed_requests.json.lock", f"{RID}.lock"])
        self.assertEqual(r["decision_after_recovery"], D.APPROVED)
        self.assertEqual(r["replay"], "EXECUTED")
        self.assertEqual(r["jobs_total"], 1)

    def test_c1_crash_just_before_create_job(self):
        r = self._crash_then_recover("C1_hard")
        self.assertEqual(r["orphan_locks"], [f"{RID}.lock"])
        # Conservateur : aucun job n'existe, mais l'état local ne peut
        # pas le prouver -> UNKNOWN (revue humaine), jamais APPROVED.
        self._assert_blocked_forever(r, jobs=0)
        self.assertTrue(self._state()["unknown_requests"][RID]["in_flight"])

    def test_c2_hard_crash_while_create_job_returns(self):
        r = self._crash_then_recover("C2_hard")
        self.assertEqual(r["orphan_locks"], [f"{RID}.lock"])
        self._assert_blocked_forever(r, jobs=1)

    def test_c2_soft_create_job_raises_after_backend_accepted(self):
        r = self._crash_then_recover("C2_soft")
        self.assertEqual(r["orphan_locks"], [])  # verrou libéré normalement
        self._assert_blocked_forever(r, jobs=1)

    def test_c3_hard_crash_after_job_id_before_mark_executed(self):
        r = self._crash_then_recover("C3_hard")
        self.assertEqual(r["orphan_locks"], [f"{RID}.lock"])
        self._assert_blocked_forever(r, jobs=1)

    def test_c3_soft_keyboard_interrupt_before_mark_executed(self):
        r = self._crash_then_recover("C3_soft")
        self.assertEqual(r["orphan_locks"], [])
        self._assert_blocked_forever(r, jobs=1)

    def test_c4_hard_crash_inside_mark_executed_before_replace(self):
        r = self._crash_then_recover("C4_hard")
        self.assertEqual(r["orphan_locks"], ["executed_requests.json.lock", f"{RID}.lock"])
        self._assert_blocked_forever(r, jobs=1, after_restart=D.BLOCKED)
        # Écriture atomique : l'ancien fichier (marqueur) reste lisible.
        self.assertTrue(self._state()["unknown_requests"][RID]["in_flight"])

    def test_c4_soft_interrupt_inside_mark_executed_cleans_tmp_file(self):
        r = self._crash_then_recover("C4_soft")
        self._assert_blocked_forever(r, jobs=1)
        self.assertEqual(r["tmp_files"], [])

    def test_c5_crash_after_complete_persistence(self):
        r = self._crash_then_recover("C5_hard")
        self.assertEqual(r["jobs_after_crash"], 1)
        self.assertEqual(r["decision_after_restart"], D.ALREADY_EXECUTED)
        self.assertEqual(r["orphan_locks"], [])
        self.assertEqual(r["replay"], "GenerationJobExecutionError")
        self.assertEqual(r["jobs_total"], 1)
        store, _, _ = self._restart()
        self.assertFalse(store.is_unknown(RID))  # marqueur retiré atomiquement
        self.assertEqual(store.recorded_job_id(RID), self._state()["executed_requests"][RID]["job_id"])


# ----------------------------------------------------------------------
# RISK #2 -- concurrence du store, vrais processus
# ----------------------------------------------------------------------


class TestRisk2StoreConcurrency(_SandboxCase):
    def _run(self, plan, use_lock=False):
        procs = [
            _spawn_worker("store", self.sandbox, str(i), ",".join(ids), prefix, "1" if use_lock else "0", "0")
            for i, (ids, prefix) in enumerate(plan)
        ]
        _release_barrier(self.sandbox, len(procs))
        outputs = []
        for proc in procs:
            out, err = proc.communicate(timeout=240)
            lines = [line for line in out.splitlines() if line.startswith("{")]
            self.assertTrue(lines, err[-500:])
            outputs.append(json.loads(lines[-1]))
        records = self._state()["executed_requests"]
        return outputs, records

    def _assert_no_loss(self, plan, outputs, records):
        for output in outputs:
            self.assertEqual(output["errors"], {}, output)
        expected = {rid for ids, _ in plan for rid in ids}
        self.assertEqual(set(records), expected)
        for output in outputs:
            for rid in output["ok"]:
                self.assertIn(rid, records)
        self.assertEqual(list(self.state_path.parent.glob(".tmp-*")), [])
        self.assertFalse(FileExecutedRequestStore(self.state_path).lock_path.exists())

    def test_c1_two_processes_two_request_ids(self):
        plan = [(["a"], "J0"), (["b"], "J1")]
        outputs, records = self._run(plan)
        self._assert_no_loss(plan, outputs, records)
        self.assertEqual(records["a"]["job_id"], "J0-a")
        self.assertEqual(records["b"]["job_id"], "J1-b")

    def test_c2_eight_processes_distinct_request_ids(self):
        plan = [([f"r{i}"], f"J{i}") for i in range(8)]
        outputs, records = self._run(plan)
        self._assert_no_loss(plan, outputs, records)
        for i in range(8):
            self.assertEqual(records[f"r{i}"]["job_id"], f"J{i}-r{i}")

    def test_c3_eight_processes_times_many_writes(self):
        plan = [([f"r{i}-{j}" for j in range(15)], f"J{i}") for i in range(8)]
        outputs, records = self._run(plan)
        self._assert_no_loss(plan, outputs, records)
        self.assertEqual(len(records), 120)
        for rid, record in records.items():
            self.assertEqual(record["job_id"], f"J{rid.split('-')[0][1:]}-{rid}")

    def test_c4_same_request_id_concurrently_never_overwrites_job_id(self):
        plan = [(["same"], f"J{i}") for i in range(8)]
        outputs, records = self._run(plan)
        winners = [o for o in outputs if o["ok"]]
        conflicts = sum(o["errors"].get("ExecutedRequestStoreConflictError", 0) for o in outputs)
        self.assertEqual(len(winners), 1, outputs)
        self.assertEqual(conflicts, 7, outputs)
        self.assertEqual(records["same"]["job_id"], f"{winners[0]['prefix']}-same")

    def test_c5_mixed_same_and_distinct_request_ids_via_critical_section(self):
        plan = [(["shared"] + [f"m{i}-{j}" for j in range(8)], f"J{i}") for i in range(8)]
        outputs, records = self._run(plan, use_lock=True)
        expected = {"shared"} | {f"m{i}-{j}" for i in range(8) for j in range(8)}
        self.assertEqual(set(records), expected)
        shared_winners = [o["prefix"] for o in outputs if "shared" in o["ok"]]
        self.assertEqual(len(shared_winners), 1, outputs)
        self.assertEqual(records["shared"]["job_id"], f"{shared_winners[0]}-shared")
        for output in outputs:
            self.assertEqual(set(output["errors"]) - {"ExecutedRequestStoreConflictError"}, set(), output)
            for rid in output["ok"]:
                self.assertIn(rid, records)

    def test_c6_processes_killed_during_protected_sequence(self):
        procs = [_spawn_worker("store", self.sandbox, str(i), f"k{i}-0", f"J{i}", "0", "1") for i in range(8)]
        _release_barrier(self.sandbox, len(procs))
        time.sleep(1.0)
        for proc in procs:
            proc.kill()  # TerminateProcess / SIGKILL : aucun finally
        for proc in procs:
            proc.communicate(timeout=60)

        store = FileExecutedRequestStore(self.state_path, lock_timeout_seconds=1.0)
        if store.lock_path.exists():
            # Un processus tué DANS la section protégée : verrou orphelin
            # -> fail closed, jamais supprimé automatiquement.
            with self.assertRaises(ExecutedRequestStoreLockTimeoutError):
                store.is_executed("anything")
            self.assertTrue(store.lock_path.exists())
            store.lock_path.unlink()  # revue humaine
        # Aucune corruption, et chaque écriture confirmée est présente.
        records = self._state()["executed_requests"]
        confirmed = {p.read_text() for p in self.sandbox.glob("ok-*")}
        self.assertTrue(confirmed)
        self.assertEqual(confirmed - set(records), set())

    def test_end_to_end_eight_processes_distinct_requests_no_double_execution(self):
        request_ids = [f"vid-{i}" for i in range(8)]
        procs = [_spawn_worker("execute", self.sandbox, "none", rid, str(i)) for i, rid in enumerate(request_ids)]
        _release_barrier(self.sandbox, len(procs))
        for proc in procs:
            out, err = proc.communicate(timeout=240)
            self.assertIn('"EXECUTED"', out, err[-500:])
        store, gate, service = self._restart(request_ids=request_ids)
        for rid in request_ids:
            self.assertEqual(gate.evaluate(_request(rid)).decision, D.ALREADY_EXECUTED)
            self.assertFalse(store.is_unknown(rid))
            with self.assertRaises(GenerationJobExecutionError):
                service.execute(_request(rid), interval_seconds=0)
            self.assertEqual(_ledger_count(self.sandbox, rid), 1)


# ----------------------------------------------------------------------
# Verrous orphelins (Part D) et persistence / restart (Part E)
# ----------------------------------------------------------------------


class TestLockHolderCrash(_SandboxCase):
    def _kill_holder(self, mode):
        proc = _spawn_worker(mode, self.sandbox)
        _wait_for_file(self.sandbox / "held")
        proc.kill()
        proc.communicate(timeout=60)

    def test_store_lock_holder_killed_fails_closed_and_is_never_auto_removed(self):
        FileExecutedRequestStore(self.state_path).mark_executed("done", job_id="job-done")
        self._kill_holder("hold_store_lock")
        store, gate, service = self._restart(lock_timeout=0.5)
        self.assertTrue(store.lock_path.exists())
        self.assertIn('"pid"', store.lock_path.read_text(encoding="utf-8"))
        # Lecture et écriture : fail closed, jamais une réponse devinée.
        with self.assertRaises(ExecutedRequestStoreLockTimeoutError):
            store.is_executed("done")
        with self.assertRaises(ExecutedRequestStoreLockTimeoutError):
            store.mark_executed("other")
        self.assertIsInstance(ExecutedRequestStoreLockTimeoutError("x"), ExecutedRequestStoreCorruptedError)
        # Gate : BLOCKED, jamais APPROVED ; create_job() jamais atteint.
        self.assertEqual(gate.evaluate(_request()).decision, D.BLOCKED)
        with self.assertRaises(GenerationJobExecutionError):
            service.execute(_request(), interval_seconds=0)
        self.assertEqual(_ledger_count(self.sandbox), 0)
        self.assertTrue(store.lock_path.exists(), "stale lock must never be auto-removed")
        # Revue humaine : suppression explicite -> état intact.
        store.lock_path.unlink()
        self.assertTrue(store.is_executed("done"))
        self.assertEqual(store.recorded_job_id("done"), "job-done")

    def test_critical_section_holder_killed_fails_closed(self):
        self._kill_holder("hold_cs_lock")
        _, _, service = self._restart()
        with self.assertRaises(CriticalSectionBusyError):
            service.execute(_request(), interval_seconds=0)
        self.assertEqual(_ledger_count(self.sandbox), 0)
        self.assertTrue((self.lock_dir / f"{RID}.lock").exists())


class TestPersistenceAndRestart(_SandboxCase):
    def test_valid_store_survives_restart_with_history(self):
        _, _, service = self._restart(request_ids=("h1", "h2"))
        first = service.execute(_request("h1"), interval_seconds=0)
        second = service.execute(_request("h2"), interval_seconds=0)
        store, gate, _ = self._restart(request_ids=("h1", "h2"))
        self.assertEqual(store.recorded_job_id("h1"), first.job.job_id)
        self.assertEqual(store.recorded_job_id("h2"), second.job.job_id)
        self.assertEqual(self._state()["unknown_requests"], {})
        for rid in ("h1", "h2"):
            self.assertEqual(gate.evaluate(_request(rid)).decision, D.ALREADY_EXECUTED)

    def test_corruption_blocks(self):
        self.state_path.parent.mkdir(parents=True)
        self.state_path.write_text("{not json", encoding="utf-8")
        _, gate, service = self._restart()
        self.assertEqual(gate.evaluate(_request()).decision, D.BLOCKED)
        with self.assertRaises(GenerationJobExecutionError):
            service.execute(_request(), interval_seconds=0)
        self.assertEqual(_ledger_count(self.sandbox), 0)

    def test_residual_tmp_file_is_ignored(self):
        self.state_path.parent.mkdir(parents=True)
        (self.state_path.parent / ".tmp-executed-requests-orphan.json").write_text("{partial")
        _, _, service = self._restart()
        service.execute(_request(), interval_seconds=0)
        store, gate, _ = self._restart()
        self.assertEqual(gate.evaluate(_request()).decision, D.ALREADY_EXECUTED)

    def test_legacy_file_without_unknown_registry_still_works(self):
        self.state_path.parent.mkdir(parents=True)
        self.state_path.write_text(json.dumps({"executed_requests": {"old": {"executed_at": "x"}}}))
        _, gate, service = self._restart(request_ids=("old", "new"))
        self.assertEqual(gate.evaluate(_request("old")).decision, D.ALREADY_EXECUTED)
        service.execute(_request("new"), interval_seconds=0)
        self.assertEqual(set(self._state()["executed_requests"]), {"old", "new"})

    def test_reads_never_create_state_directory(self):
        store = FileExecutedRequestStore(self.sandbox / "absent" / "executed_requests.json")
        self.assertFalse(store.is_executed(RID))
        self.assertFalse(store.is_unknown(RID))
        self.assertIsNone(store.recorded_job_id(RID))
        self.assertFalse((self.sandbox / "absent").exists())


# ----------------------------------------------------------------------
# UNKNOWN / anti-replay / in_flight (Part A2/A3, Part F)
# ----------------------------------------------------------------------


class TestInFlightBoundary(_SandboxCase):
    def _stores(self):
        return [InMemoryExecutedRequestStore(), FileExecutedRequestStore(self.state_path)]

    def test_in_flight_reads_as_unknown_and_mark_executed_replaces_it(self):
        for store in self._stores():
            with store.in_flight(RID):
                self.assertTrue(store.is_unknown(RID))
            self.assertTrue(store.is_unknown(RID))  # sortie normale : marqueur conservé
            store.mark_executed(RID, job_id="job-1")
            self.assertFalse(store.is_unknown(RID))
            self.assertTrue(store.is_executed(RID))

    def test_in_flight_can_never_clear_an_existing_record(self):
        for store in self._stores():
            store.mark_unknown("u", reason="prior ambiguity")
            store.mark_executed("e", job_id="job-e")
            for rid in ("u", "e"):
                with self.assertRaises(ExecutedRequestStoreConflictError):
                    with store.in_flight(rid):
                        raise HiggsfieldRealGenerationDisabledError("refused")
            self.assertTrue(store.is_unknown("u"))
            self.assertTrue(store.is_executed("e"))

    def test_marker_of_a_crashed_attempt_can_never_be_rolled_back(self):
        for store in self._stores():
            with store.in_flight(RID):
                pass  # tentative "crashée" : marqueur laissé
            with self.assertRaises(ExecutedRequestStoreConflictError):
                with store.in_flight(RID):
                    raise HiggsfieldRealGenerationDisabledError("refused")
            self.assertTrue(store.is_unknown(RID))

    def test_only_disabled_refusal_rolls_back_its_own_marker(self):
        for store in self._stores():
            with self.assertRaises(HiggsfieldRealGenerationDisabledError):
                with store.in_flight("refused"):
                    raise HiggsfieldRealGenerationDisabledError("refused before any client call")
            self.assertFalse(store.is_unknown("refused"))
            for error in (ConnectionError("x"), TimeoutError("x"), KeyboardInterrupt(), RuntimeError("x")):
                rid = f"kept-{type(error).__name__}"
                with self.assertRaises(type(error)):
                    with store.in_flight(rid):
                        raise error
                self.assertTrue(store.is_unknown(rid), rid)

    def test_marker_converted_by_mark_unknown_is_never_rolled_back(self):
        for store in self._stores():
            with self.assertRaises(HiggsfieldRealGenerationDisabledError) as caught:
                with store.in_flight(RID):
                    store.mark_unknown(RID, reason="converted")
                    raise HiggsfieldRealGenerationDisabledError("refused")
            self.assertTrue(store.is_unknown(RID))
            if isinstance(store, FileExecutedRequestStore):
                self.assertIn("remains EXECUTION_STATE_UNKNOWN", "".join(caught.exception.__notes__))

    def test_rollback_restores_absence_of_store_file(self):
        store = FileExecutedRequestStore(self.state_path)
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            with store.in_flight(RID):
                self.assertTrue(self.state_path.exists())
                raise HiggsfieldRealGenerationDisabledError("refused")
        self.assertFalse(self.state_path.exists())
        self.assertFalse(store.lock_path.exists())

    def test_real_provider_refusal_leaves_no_trace_and_never_creates(self):
        from unittest.mock import MagicMock

        client = MagicMock()  # lectures seulement (coût, solde, modèle)
        client.estimate_cost.return_value = {"credits": 10.0}
        client.account_status.return_value = {"credits": 1000.0}
        client.get_model.return_value = {
            "job_type": "seedance_2_0",
            "display_name": "d",
            "params": [
                {"name": "prompt", "type": "string", "required": True},
                {"name": "duration", "type": "integer", "required": False, "default": 5},
                {"name": "start_image", "type": "object|null", "required": False},
                {"name": "image_references", "type": "array", "required": False},
            ],
        }
        provider = HiggsfieldProvider(client=client)
        store = FileExecutedRequestStore(self.state_path)
        # Phase D : fixtures de TEST explicites (plafond + Identity Lock) ;
        # sans elles, la Gate bloque le chemin réel avant create_job().
        gate = GenerationApprovalGate(
            provider,
            executed_request_store=store,
            identity_lock=fixture_identity_lock_for(_request()),
            max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST,
        )
        service = GenerationJobService(provider, gate, lock=FileCriticalSectionLock(self.lock_dir))
        self.assertEqual(gate.evaluate(_request()).decision, D.APPROVED)
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            service.execute(_request(), interval_seconds=0)
        client.create_job.assert_not_called()
        self.assertNotIn("create", [a for c in client.run.call_args_list for a in c.args])
        # Aucune trace : identique à avant P3.91, rejeu non bloqué.
        self.assertFalse(self.state_path.exists())
        self.assertFalse(store.lock_path.exists())
        self.assertEqual(list(self.lock_dir.glob("*")), [])
        self.assertEqual(gate.evaluate(_request()).decision, D.APPROVED)

    def test_unknown_or_in_flight_of_one_request_never_blocks_another(self):
        _, gate, service = self._restart(request_ids=("a", "b", "c"))
        store = gate.executed_request_store
        with store.in_flight("a"):
            pass
        store.mark_unknown("b", reason="ambiguous")
        self.assertEqual(gate.evaluate(_request("a")).decision, D.EXECUTION_STATE_UNKNOWN)
        self.assertEqual(gate.evaluate(_request("b")).decision, D.EXECUTION_STATE_UNKNOWN)
        outcome = service.execute(_request("c"), interval_seconds=0)
        self.assertEqual(store.recorded_job_id("c"), outcome.job.job_id)
        self.assertIsNone(store.recorded_job_id("a"))
        self.assertEqual(gate.evaluate(_request("c")).decision, D.ALREADY_EXECUTED)

    def test_execution_identity_is_never_transferred_across_requests(self):
        _, gate, service = self._restart(request_ids=("a", "b"))
        a = service.execute(_request("a"), interval_seconds=0)
        b = service.execute(_request("b"), interval_seconds=0)
        store = gate.executed_request_store
        self.assertNotEqual(a.job.job_id, b.job.job_id)
        self.assertEqual(store.recorded_job_id("a"), a.job.job_id)
        self.assertEqual(store.recorded_job_id("b"), b.job.job_id)
        with self.assertRaises(ExecutedRequestStoreConflictError):
            store.mark_executed("a", job_id=b.job.job_id)
        self.assertEqual(store.recorded_job_id("a"), a.job.job_id)


# ----------------------------------------------------------------------
# Critical section ordering (Part G) -- AST, jamais une supposition
# ----------------------------------------------------------------------


def _calls_in(node):
    return [
        (n.lineno, n.func.attr)
        for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    ]


class TestCriticalSectionOrdering(unittest.TestCase):
    def setUp(self):
        source = (PROJECT_ROOT / "agents" / "generation_job_service.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        execute = next(
            n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "execute"
        )
        self.lock_with = next(
            n for n in ast.walk(execute)
            if isinstance(n, ast.With)
            and any(
                isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Attribute)
                and item.context_expr.func.attr == "acquire"
                for item in n.items
            )
        )
        self.in_flight_with = next(
            n for n in ast.walk(self.lock_with)
            if isinstance(n, ast.With)
            and any(
                isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Attribute)
                and item.context_expr.func.attr == "in_flight"
                for item in n.items
            )
        )

    def test_order_evaluate_then_write_ahead_then_create_job_then_record(self):
        calls = _calls_in(self.lock_with)
        first = {}
        for lineno, name in calls:
            first.setdefault(name, lineno)
        self.assertLess(first["evaluate"], first["in_flight"])
        self.assertLess(first["consume"], first["in_flight"])
        self.assertLess(first["in_flight"], first["create_job"])
        self.assertLess(first["create_job"], first["mark_executed"])

    def test_create_job_is_only_ever_called_inside_the_write_ahead_block(self):
        inside = [name for _, name in _calls_in(self.in_flight_with)]
        self.assertEqual(inside.count("create_job"), 1)
        whole = [name for _, name in _calls_in(self.lock_with)]
        self.assertEqual(whole.count("create_job"), 1)

    def test_in_flight_is_used_only_by_generation_job_service_in_production(self):
        users = set()
        for directory in ("agents", "integrations", "scripts"):
            for path in (PROJECT_ROOT / directory).rglob("*.py"):
                if "__pycache__" in path.parts:
                    continue
                tree = ast.parse(path.read_text(encoding="utf-8-sig"))
                if any(name == "in_flight" for _, name in _calls_in(tree)):
                    users.add(path.relative_to(PROJECT_ROOT).as_posix())
        self.assertEqual(
            users,
            {"agents/generation_job_service.py", "agents/generation_approval_gate.py"},
        )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == WORKER_FLAG:
        _worker(*sys.argv[2:])
    else:
        unittest.main()
