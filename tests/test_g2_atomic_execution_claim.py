"""
Tests — Phase G2 : réservation atomique d'exécution par `request_id`
(course P2.16).

Couvre `InMemoryExecutionClaimRegistry` / `FileExecutionClaimRegistry`
(agents/executed_request_store.py), `GenerationApprovalGate.
claim_execution()` et son usage par `GenerationJobService.execute()` :
- un seul détenteur (même processus, threads, processus distincts),
  refus immédiat, jamais d'attente ;
- refus fermé : identifiant invalide, fichier de réservation inutilisable
  ou remplacé, store sans registre de réservations ; état persistant
  corrompu -> BLOCKED sous la réservation ;
- parcours de décision : réservation prise dans le verrou, avant
  `evaluate()` ; une exécution refusée n'appelle jamais le Provider ;
- arrêt du détenteur : le système libère le verrou, et les registres
  durables empêchent tout rejeu (« ARRÊT APRÈS LA RÉSERVATION ») ;
- fichier STABLE : jamais supprimé, il reste un verrou vide, et chaque
  détenteur successif verrouille le même inode ; passage de main entre
  trois processus selon un calendrier fixe, sans jamais deux blocs
  `claim()` actifs en même temps.

La course à N processus « un seul gagnant » est dans
tests/test_phase_p2_16_concurrency_audit.py.

Mock-only : MockHiggsfieldProvider, répertoires temporaires, aucun
réseau, aucun CLI, aucun crédit. Les processus enfants exécutent ce
fichier (`WORKER_FLAG`).
"""

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import agents.executed_request_store as store_module
from agents.executed_request_store import (
    EXECUTION_CLAIM_SUFFIX,
    ExecutedRequestStoreCorruptedError,
    ExecutionClaimBusyError,
    ExecutionClaimRefusedError,
    FileExecutedRequestStore,
    FileExecutionClaimRegistry,
    InMemoryAuthorizationConsumptionRegistry,
    InMemoryExecutedRequestStore,
    InMemoryExecutionClaimRegistry,
)
from agents.generation_approval_gate import (
    GenerationApprovalDecision as D,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from agents.generation_job_service import GenerationJobExecutionError, GenerationJobService
from director import AIDirector
from tests.authorization_content_helpers import bind_request, content_media
from tests.real_provider_path_fixtures import counting_mock_provider, install_create_job_probe

RID = "005"
WORKER_FLAG = "--g2-claim-worker"
_PROVIDER_READS = ("list_models", "get_model", "estimate_cost", "get_account_balance", "get_job", "wait_for_job")


def _request(request_id=RID, authorized=True) -> GenerationRequest:
    return bind_request(GenerationRequest(
        **content_media(),
        request_id=request_id,
        job_type="seedance_2_0",
        prompt="Un prompt de test suffisamment explicite.",
        duration=5,
        approved=True,
        real_generation_authorization=(
            RealGenerationAuthorization(request_id=request_id, authorized_by_human=True)
            if authorized
            else None
        ),
    ))


def _observed_provider(calls, on_first_call=None, **kwargs):
    """Mock RECONNU (`create_job` jamais remplacé, compté par
    `install_create_job_probe()`) dont chaque autre appel est consigné
    dans `calls`."""

    provider = counting_mock_provider(cost_per_job=10.0, available_credits=100.0, succeed_after_polls=1, **kwargs)
    for name in _PROVIDER_READS:
        original = getattr(provider, name)

        def observed(*args, _name=name, _original=original, **kw):
            calls.append(_name)
            if on_first_call is not None and len(calls) == 1:
                on_first_call()
            return _original(*args, **kw)

        setattr(provider, name, observed)
    return provider


def _chain(state_path=None, calls=None, on_first_call=None, on_create=None):
    calls = [] if calls is None else calls
    provider = _observed_provider(calls, on_first_call=on_first_call, on_create=on_create)
    store = InMemoryExecutedRequestStore() if state_path is None else FileExecutedRequestStore(state_path)
    gate = install_create_job_probe(GenerationApprovalGate(provider, executed_request_store=store), provider)
    return provider, store, gate, GenerationJobService(provider, gate)


def _single_holder_outcomes(registry, count=8):
    """`count` threads tentent la même réservation ; le détenteur la garde
    jusqu'au refus de tous les autres (issue indépendante de
    l'ordonnancement)."""

    barrier = threading.Barrier(count)
    refused = threading.Semaphore(0)
    outcomes, guard = [], threading.Lock()

    def contender():
        barrier.wait(timeout=30)
        try:
            with registry.claim(RID):
                waited = all(refused.acquire(timeout=30) for _ in range(count - 1))
                outcome = "CLAIMED" if waited else "TIMEOUT"
        except ExecutionClaimBusyError:
            outcome = "BUSY"
            refused.release()
        except BaseException as error:  # noqa: B902 -- rapporté au test
            outcome = repr(error)
        with guard:
            outcomes.append(outcome)

    threads = [threading.Thread(target=contender) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return sorted(outcomes)


# ----------------------------------------------------------------------
# Processus enfants (jamais exécutés par unittest)
# ----------------------------------------------------------------------


def _wait_for(condition, what, timeout=60):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"timeout waiting for {what}")
        time.sleep(0.002)


def _handoff(sandbox: Path, wid, count, rounds):
    """Manche r : le processus r % count détient la réservation ; chacun des
    autres la tente pendant que le détenteur est dans son bloc. Rapporte
    les manches détenues/refusées, l'inode verrouillé et toute violation."""

    wid, count, rounds = int(wid), int(count), int(rounds)
    registry = FileExecutionClaimRegistry(sandbox / "state")
    claim_path = registry.claim_dir / f"{RID}{EXECUTION_CLAIM_SUFFIX}"
    signals, inside = sandbox / "handoff", sandbox / "inside"
    report = {"held": [], "refused": [], "inodes": [], "violations": []}

    def enter_block(r):
        # Témoin indépendant : création exclusive, impossible si un autre
        # bloc `claim()` est actif.
        try:
            os.close(os.open(str(inside), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:
            report["violations"].append(f"round {r}: process {wid} entered while another claim() block was active")
            return False
        report["inodes"].append(claim_path.stat().st_ino)
        return True

    (signals / f"ready-{wid}").write_text("1", encoding="utf-8")
    for r in range(rounds):
        holder = r % count
        others_done = lambda r=r: len(list(signals.glob(f"done-{r}-*"))) == count - 1
        if wid == holder:
            _wait_for((signals / f"start-{r}").exists, f"start-{r}")
            try:
                with registry.claim(RID):
                    entered = enter_block(r)
                    report["held"].append(r)
                    (signals / f"held-{r}").write_text("1", encoding="utf-8")
                    # Ne sort qu'après la tentative de tous les autres.
                    _wait_for(others_done, f"the other attempts of round {r}")
                    if entered:
                        inside.unlink()
            except ExecutionClaimBusyError:
                report["violations"].append(f"round {r}: the claim was not handed over to process {wid}")
                (signals / f"held-{r}").write_text("1", encoding="utf-8")
                _wait_for(others_done, f"the other attempts of round {r}")
            # Le bloc est entièrement sorti (réservation rendue) : manche suivante.
            (signals / f"start-{r + 1}").write_text("1", encoding="utf-8")
        else:
            _wait_for((signals / f"held-{r}").exists, f"held-{r}")
            try:
                with registry.claim(RID):
                    report["violations"].append(f"round {r}: process {wid} got the claim while {holder} held it")
                    if enter_block(r):
                        inside.unlink()
            except ExecutionClaimBusyError:
                report["refused"].append(r)
            (signals / f"done-{r}-{wid}").write_text("1", encoding="utf-8")
    print(json.dumps(report))


def _worker(mode, sandbox, *args):
    sandbox = Path(sandbox)
    state_path = sandbox / "state" / "executed_requests.json"
    held = sandbox / "held"

    if mode == "handoff":
        _handoff(sandbox, *args)
        return

    def _stop_here(*_):
        held.write_text("1", encoding="utf-8")
        time.sleep(120)

    if mode == "hold":
        with FileExecutedRequestStore(state_path).execution_claims.claim(RID):
            _stop_here()
    elif mode == "stop_while_deciding":
        # Premier appel Provider (dans evaluate) : réservation détenue,
        # rien consommé ni écrit.
        _chain(state_path, on_first_call=_stop_here)[3].execute(_request(), interval_seconds=0)
    elif mode == "stop_inside_create_job":
        # Instant de l'appel create_job() : marqueur « en vol » durable.
        _chain(state_path, on_create=_stop_here)[3].execute(_request(), interval_seconds=0)
    sys.exit(1)


class _Sandbox(unittest.TestCase):
    def setUp(self):
        self.sandbox = Path(tempfile.mkdtemp(prefix="g2_claim_"))
        self.addCleanup(shutil.rmtree, self.sandbox, ignore_errors=True)
        self.state_path = self.sandbox / "state" / "executed_requests.json"
        self.claim_path = self.state_path.parent / f"{RID}{EXECUTION_CLAIM_SUFFIX}"

    def assertReleasedLockFile(self, claim_path, inode=None):
        """Après libération : le fichier reste en place, vide (même inode
        si `inode` est fourni), et la réservation est de nouveau
        disponible sans attente."""

        self.assertTrue(claim_path.is_file(), "the claim lock file must stay in place")
        self.assertEqual(claim_path.stat().st_size, 0, "the claim lock file stays empty")
        if inode is not None:
            self.assertEqual(claim_path.stat().st_ino, inode, "the claim lock file was replaced")
        with FileExecutionClaimRegistry(claim_path.parent).claim(claim_path.name[: -len(EXECUTION_CLAIM_SUFFIX)]):
            pass

    def _stop_holder(self, mode):
        """Lance un enfant, attend qu'il détienne la réservation, vérifie
        qu'elle est refusée ici tant qu'il vit, puis le tue (arrêt dur).
        Renvoie l'inode du fichier de réservation qu'il détenait."""

        proc = subprocess.Popen(
            [sys.executable, "-B", __file__, WORKER_FLAG, mode, str(self.sandbox)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            deadline = time.monotonic() + 120
            while not (self.sandbox / "held").exists():
                if proc.poll() is not None:
                    self.fail(f"worker exited before holding the claim: {proc.communicate()[1][-800:]}")
                self.assertLess(time.monotonic(), deadline, "worker never held the claim")
                time.sleep(0.01)
            with self.assertRaises(ExecutionClaimBusyError):
                with FileExecutedRequestStore(self.state_path).execution_claims.claim(RID):
                    self.fail("the claim of a live holder must never be granted")
            return self.claim_path.stat().st_ino
        finally:
            proc.kill()
            proc.communicate(timeout=60)

    def _claim_once_released(self):
        """Réservation obtenue après l'arrêt du détenteur. Attente bornée :
        seule la libération par le système, après la fin du processus, est
        attendue -- la réservation elle-même ne patiente jamais."""

        registry = FileExecutedRequestStore(self.state_path).execution_claims
        deadline = time.monotonic() + 10
        while True:
            try:
                with registry.claim(RID):
                    return
            except ExecutionClaimBusyError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)


# ----------------------------------------------------------------------
# Registres de réservations
# ----------------------------------------------------------------------


class TestFileClaimRegistry(_Sandbox):
    def setUp(self):
        super().setUp()
        self.registry = FileExecutionClaimRegistry(self.state_path.parent)

    def test_a_held_claim_refuses_a_second_one_immediately(self):
        with self.registry.claim(RID):
            started = time.monotonic()
            with self.assertRaises(ExecutionClaimBusyError):
                with self.registry.claim(RID):
                    self.fail("a held claim must never be granted twice")
            self.assertLess(time.monotonic() - started, 0.5)
            with self.registry.claim("006"):
                pass  # un autre request_id est indépendant

    def test_release_keeps_the_same_empty_lock_file_even_on_exception(self):
        with self.registry.claim(RID):
            self.assertTrue(self.claim_path.is_file())
            inode = self.claim_path.stat().st_ino
        self.assertReleasedLockFile(self.claim_path, inode)

        with self.assertRaises(RuntimeError):
            with self.registry.claim(RID):
                self.assertEqual(self.claim_path.stat().st_ino, inode)
                raise RuntimeError("[test] failure inside the claim")
        self.assertReleasedLockFile(self.claim_path, inode)

    def test_threads_never_share_a_claim(self):
        self.assertEqual(_single_holder_outcomes(self.registry), ["BUSY"] * 7 + ["CLAIMED"])
        self.assertReleasedLockFile(self.claim_path)

    def test_invalid_request_ids_are_refused_without_filesystem_effect(self):
        for bad in ("", "../escape", "a/b", "a\\b", "C:x", "CON", "x" * 65, " 005", 5, None):
            with self.subTest(bad=bad):
                with self.assertRaises(ExecutionClaimRefusedError) as refused:
                    with self.registry.claim(bad):
                        self.fail("an invalid request_id must never be claimed")
                self.assertNotIsInstance(refused.exception, ExecutionClaimBusyError)
        self.assertFalse(self.state_path.parent.exists())

    def test_unusable_claim_file_is_refused(self):
        self.claim_path.mkdir(parents=True)  # un répertoire à la place du fichier
        with self.assertRaises(ExecutionClaimRefusedError):
            with self.registry.claim(RID):
                self.fail("an unusable claim file must never be granted")
        self.assertTrue(self.claim_path.is_dir())

    def test_claim_file_replaced_during_acquisition_is_refused_and_unlocked(self):
        with mock.patch.object(store_module, "_is_claimed_file", return_value=False):
            with self.assertRaises(ExecutionClaimBusyError):
                with self.registry.claim(RID):
                    self.fail("a replaced claim file must never be granted")
        with self.registry.claim(RID):
            pass  # le verrou n'est pas resté pris

    def test_identity_check_compares_the_open_file_with_the_path(self):
        self.claim_path.parent.mkdir(parents=True)
        other = self.claim_path.with_name(f"006{EXECUTION_CLAIM_SUFFIX}")
        self.claim_path.write_bytes(b"")
        other.write_bytes(b"")
        fd = os.open(str(other), os.O_RDONLY)
        try:
            self.assertTrue(store_module._is_claimed_file(fd, other))
            self.assertFalse(store_module._is_claimed_file(fd, self.claim_path))
            self.assertFalse(store_module._is_claimed_file(fd, self.claim_path.with_name("missing")))
        finally:
            os.close(fd)


class TestInMemoryClaimRegistry(unittest.TestCase):
    def test_a_held_claim_is_busy_then_released(self):
        registry = InMemoryExecutionClaimRegistry()
        with registry.claim(RID):
            with self.assertRaises(ExecutionClaimBusyError):
                with registry.claim(RID):
                    self.fail("a held claim must never be granted twice")
        with registry.claim(RID):
            pass

    def test_threads_never_share_a_claim(self):
        self.assertEqual(_single_holder_outcomes(InMemoryExecutionClaimRegistry()), ["BUSY"] * 7 + ["CLAIMED"])


# ----------------------------------------------------------------------
# Parcours de décision (GenerationJobService.execute)
# ----------------------------------------------------------------------


class TestDecisionPathUsesTheClaim(_Sandbox):
    def test_a_held_claim_refuses_execute_before_any_provider_call(self):
        for label in ("file", "memory"):
            with self.subTest(store=label):
                state_path = self.sandbox / label / "executed_requests.json"
                calls = []
                provider, _, gate, service = _chain(None if label == "memory" else state_path, calls=calls)
                request = _request()
                with gate.claim_execution(RID), mock.patch.object(gate, "evaluate", wraps=gate.evaluate) as evaluate:
                    with self.assertRaises(ExecutionClaimBusyError):
                        service.execute(request, interval_seconds=0)
                evaluate.assert_not_called()
                self.assertEqual(calls, [])
                self.assertEqual(provider.create_calls, 0)
                self.assertFalse(gate.is_authorization_consumed(request.real_generation_authorization.authorization_id))
                self.assertFalse(state_path.exists())

                # Réservation rendue : l'exécution suivante passe, une fois.
                self.assertTrue(service.execute(request, interval_seconds=0).succeeded)
                self.assertEqual(provider.create_calls, 1)

    def test_the_claim_is_released_after_success_refusal_and_failure(self):
        def create_job_fails(params):
            raise ConnectionError("[test] create_job() failure")

        scenarios = (
            ("success", None, True, None),
            ("gate refusal", None, False, GenerationJobExecutionError),
            ("create_job failure", create_job_fails, True, ConnectionError),
        )
        for label, on_create, authorized, expected in scenarios:
            with self.subTest(scenario=label):
                state_path = self.sandbox / label.replace(" ", "_") / "executed_requests.json"
                _, _, gate, service = _chain(state_path, on_create=on_create)
                if expected is None:
                    service.execute(_request(authorized=authorized), interval_seconds=0)
                else:
                    with self.assertRaises(expected):
                        service.execute(_request(authorized=authorized), interval_seconds=0)
                self.assertReleasedLockFile(state_path.parent / f"{RID}{EXECUTION_CLAIM_SUFFIX}")
                with gate.claim_execution(RID):
                    pass

    def test_corrupted_persistent_state_blocks_under_the_claim(self):
        self.state_path.parent.mkdir(parents=True)
        self.state_path.write_text("{not valid json", encoding="utf-8")
        provider, _, gate, service = _chain(self.state_path)
        request = _request()
        with self.assertRaises(GenerationJobExecutionError) as refused:
            service.execute(request, interval_seconds=0)
        self.assertEqual(refused.exception.approval.decision, D.BLOCKED)
        self.assertEqual(provider.create_calls, 0)
        self.assertFalse(gate.is_authorization_consumed(request.real_generation_authorization.authorization_id))
        self.assertEqual(self.state_path.read_text(encoding="utf-8"), "{not valid json")
        self.assertReleasedLockFile(self.claim_path)

    def test_store_without_claim_registry_fails_closed_before_any_provider_call(self):
        class _StoreWithoutClaims:
            authorization_registry = InMemoryAuthorizationConsumptionRegistry()

            def is_executed(self, request_id):
                return False

            def is_unknown(self, request_id):
                return False

            def in_flight(self, request_id):
                raise AssertionError("must never be reached")

        calls = []
        provider = _observed_provider(calls)
        gate = install_create_job_probe(
            GenerationApprovalGate(provider, executed_request_store=_StoreWithoutClaims()), provider
        )
        with self.assertRaises(ExecutedRequestStoreCorruptedError):
            GenerationJobService(provider, gate).execute(_request(), interval_seconds=0)
        self.assertEqual(calls, [])
        self.assertEqual(provider.create_calls, 0)


class TestClaimPositionInExecute(unittest.TestCase):
    """Statique (AST) : lit le source du service, ne l'exécute pas."""

    def setUp(self):
        tree = ast.parse((PROJECT_ROOT / "agents" / "generation_job_service.py").read_text(encoding="utf-8-sig"))
        service = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GenerationJobService")
        self.execute = next(n for n in service.body if isinstance(n, ast.FunctionDef) and n.name == "execute")
        self.lock_block = next(
            stmt for stmt in self.execute.body
            if isinstance(stmt, ast.With)
            and ast.unparse(stmt.items[0].context_expr) == "self.lock.acquire(request.request_id)"
        )

    @staticmethod
    def _called(node):
        return [ast.unparse(n.func) for n in ast.walk(node) if isinstance(n, ast.Call)]

    def test_the_claim_wraps_the_whole_decision_inside_the_lock(self):
        self.assertEqual(len(self.lock_block.body), 1, "nothing may run in the lock outside the claim")
        claim_block = self.lock_block.body[0]
        self.assertIsInstance(claim_block, ast.With)
        self.assertEqual(
            [ast.unparse(item.context_expr) for item in claim_block.items],
            ["self.gate.claim_execution(request.request_id)"],
        )
        inside = self._called(claim_block)
        for name in (
            "self.gate.evaluate",
            "self.gate.consume_authorization",
            "self.gate.in_flight",
            "self.provider.create_job",
            "self.gate.mark_executed",
            "self.gate.mark_unknown",
        ):
            with self.subTest(call=name):
                self.assertIn(name, inside)
        self.assertEqual(self._called(self.execute).count("self.gate.claim_execution"), 1)
        self.assertNotIn("self.provider.wait_for_job", inside)


class TestProductionWiring(unittest.TestCase):
    def test_director_chain_claims_in_its_state_directory(self):
        director = AIDirector()
        claims = director._build_default_chain().gate.executed_request_store.execution_claims
        self.assertIsInstance(claims, FileExecutionClaimRegistry)
        self.assertEqual(claims.claim_dir, director.root / "state")


# ----------------------------------------------------------------------
# Arrêt du détenteur après la réservation (vrais processus, arrêt dur)
# ----------------------------------------------------------------------


class TestStopAfterClaim(_Sandbox):
    def test_a_stopped_holder_releases_the_claim(self):
        inode = self._stop_holder("hold")
        self._claim_once_released()
        # Le fichier laissé par l'arrêt est le même verrou vide, repris tel quel.
        self.assertReleasedLockFile(self.claim_path, inode)

    def test_stop_before_any_consumption_leaves_no_trace_and_the_next_run_executes_once(self):
        inode = self._stop_holder("stop_while_deciding")
        self._claim_once_released()
        self.assertReleasedLockFile(self.claim_path, inode)
        self.assertFalse(self.state_path.exists(), "no in-flight marker: create_job() was never reached")
        self.assertFalse((self.state_path.parent / "consumed_authorizations.json").exists())

        provider, store, _, service = _chain(self.state_path)
        self.assertTrue(service.execute(_request(), interval_seconds=0).succeeded)
        self.assertEqual(provider.create_calls, 1)
        self.assertTrue(store.is_executed(RID))
        with self.assertRaises(GenerationJobExecutionError) as replay:
            service.execute(_request(), interval_seconds=0)
        self.assertEqual(replay.exception.approval.decision, D.ALREADY_EXECUTED)
        self.assertEqual(provider.create_calls, 1)

    def test_stop_after_the_in_flight_marker_is_never_replayed(self):
        inode = self._stop_holder("stop_inside_create_job")
        self._claim_once_released()

        provider, store, _, service = _chain(self.state_path)
        self.assertTrue(store.is_unknown(RID))
        with self.assertRaises(GenerationJobExecutionError) as refused:
            service.execute(_request(), interval_seconds=0)
        self.assertEqual(refused.exception.approval.decision, D.EXECUTION_STATE_UNKNOWN)
        self.assertEqual(provider.create_calls, 0)
        self.assertFalse(store.is_executed(RID))
        self.assertTrue(store.is_unknown(RID))
        self.assertReleasedLockFile(self.claim_path, inode)


# ----------------------------------------------------------------------
# Passage de main entre détenteurs (vrais processus, calendrier fixe)
# ----------------------------------------------------------------------


class TestClaimHandoffBetweenProcesses(_Sandbox):
    """
    Trois VRAIS processus se passent la réservation selon un calendrier
    fixe : à la manche r, le processus r % 3 la détient. Chacun des deux
    autres la tente PENDANT que le détenteur est dans son bloc (signal
    `held-r`), et le détenteur ne sort qu'après ces deux tentatives. Le
    détenteur suivant ne commence qu'une fois le bloc précédent entièrement
    sorti (signal `start-r+1`). Un marqueur à création exclusive, posé à
    l'entrée de chaque bloc et retiré à sa sortie, témoigne qu'aucun second
    bloc `claim()` n'a jamais été actif. Aucune issue ne dépend de
    l'ordonnancement : chaque tentative a lieu soit pendant un bloc actif
    (refus exigé), soit après sa sortie complète (succès exigé).
    """

    PROCESSES = 3
    ROUNDS = 6

    def test_handoff_never_overlaps_two_claim_blocks_and_keeps_one_inode(self):
        signals = self.sandbox / "handoff"
        signals.mkdir()
        procs = [
            subprocess.Popen(
                [sys.executable, "-B", __file__, WORKER_FLAG, "handoff", str(self.sandbox),
                 str(wid), str(self.PROCESSES), str(self.ROUNDS)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            for wid in range(self.PROCESSES)
        ]
        try:
            deadline = time.monotonic() + 120
            while len(list(signals.glob("ready-*"))) < self.PROCESSES:
                self.assertLess(time.monotonic(), deadline, "workers never reached the start barrier")
                time.sleep(0.01)
            (signals / "start-0").write_text("1", encoding="utf-8")
            reports = []
            for proc in procs:
                out, err = proc.communicate(timeout=240)
                lines = [line for line in out.splitlines() if line.startswith("{")]
                self.assertTrue(lines, err[-800:])
                reports.append(json.loads(lines[-1]))
        finally:
            for proc in procs:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()

        for wid, report in enumerate(reports):
            with self.subTest(process=wid):
                self.assertEqual(report["violations"], [])
                self.assertEqual(report["held"], [r for r in range(self.ROUNDS) if r % self.PROCESSES == wid])
                self.assertEqual(report["refused"], [r for r in range(self.ROUNDS) if r % self.PROCESSES != wid])
        inodes = {inode for report in reports for inode in report["inodes"]}
        self.assertEqual(len(inodes), 1, f"every holder must lock the same inode: {inodes}")
        self.assertFalse((self.sandbox / "inside").exists())
        self.assertReleasedLockFile(self.claim_path, inodes.pop())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == WORKER_FLAG:
        _worker(*sys.argv[2:])
    else:
        unittest.main()
