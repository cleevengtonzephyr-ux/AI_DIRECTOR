"""
Tests — Phase B : usage unique de `RealGenerationAuthorization`.

La consommation vit dans un registre SÉPARÉ (`consumed_authorizations
.json`, verrou propre), jamais dans `executed_requests.json` (invariant
P3.89). Elle est vérifiée puis inscrite atomiquement juste avant le
marqueur write-ahead et `create_job()` ; tout refus antérieur ne consomme
rien ; ensuite elle est définitive (refus du Provider, erreur, arrêt --
un arrêt entre la consommation et le marqueur brûle l'autorisation :
échec fermé). Une autorisation consommée ne mène jamais à APPROVED.
Portée : une machine, un dossier d'état partagé.

Uniquement `MockHiggsfieldProvider` (ou `HiggsfieldProvider` avec un
client MagicMock pour le refus réel) : aucun CLI, aucun réseau, aucun
crédit ; chaque test travaille dans un dossier temporaire, jamais dans
le `state/` réel.
"""

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.critical_section_lock import CriticalSectionBusyError, FileCriticalSectionLock
from agents.executed_request_store import (
    AuthorizationAlreadyConsumedError,
    AuthorizationRegistryCorruptedError,
    AuthorizationRegistryLockTimeoutError,
    ExecutedRequestStoreCorruptedError,
    FileAuthorizationConsumptionRegistry,
    FileExecutedRequestStore,
    InMemoryAuthorizationConsumptionRegistry,
    InMemoryExecutedRequestStore,
    InvalidAuthorizationIdError,
)
from agents.generation_approval_gate import (
    GenerationApprovalDecision as D,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from agents.generation_job_service import GenerationJobExecutionError, GenerationJobService
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider

@contextmanager
def isolated_director_state(tmp_root):
    """
    Redirige UNIQUEMENT les chemins persistants construits par
    `AIDirector._build_default_chain()` (store anti-rejeu, registre de
    consommation adjacent, verrou de section critique) vers
    `<tmp_root>/state`. Le Gate, les services et le HiggsfieldProvider
    réel (refus systématique) restent ceux que construit le Director :
    seul l'emplacement disque change, jamais le comportement. Aucun
    accès au vrai `state/` du dépôt.
    """

    import director as director_module

    state = Path(tmp_root) / "state"
    with patch.object(
        director_module, "FileExecutedRequestStore",
        lambda path, **kwargs: FileExecutedRequestStore(state / Path(path).name, **kwargs),
    ), patch.object(
        director_module, "FileCriticalSectionLock",
        lambda lock_dir: FileCriticalSectionLock(state / Path(lock_dir).name),
    ):
        yield state


WORKER_FLAG = "--phase-b-single-use-worker"
RID = "pb-req"
CONSUMED_REASON = "a new explicit human authorization is required"


def _auth(request_id=RID, authorization_id=None):
    kwargs = {} if authorization_id is None else {"authorization_id": authorization_id}
    return RealGenerationAuthorization(
        request_id=request_id, authorized_by_human=True, note="phase-b-note-marker", **kwargs
    )


def _request(auth=None, request_id=RID, approved=True):
    return GenerationRequest(
        request_id=request_id,
        job_type="seedance_2_0",
        prompt="Un prompt de test suffisamment explicite.",
        duration=5,
        approved=approved,
        real_generation_authorization=auth if auth is not None else _auth(request_id),
    )


def _digest(authorization_id):
    return hashlib.sha256(authorization_id.encode("utf-8")).hexdigest()


class _CountingProvider(MockHiggsfieldProvider):
    """Mock : compte chaque create_job(), peut refuser comme le vrai
    Provider, ou observer l'état au moment exact de l'appel."""

    def __init__(self, *args, refuse=False, on_create=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.create_calls = 0
        self.refuse = refuse
        self.on_create = on_create

    def create_job(self, job_type, prompt, **params):
        self.create_calls += 1
        if self.on_create is not None:
            self.on_create(params)
        if self.refuse:
            raise HiggsfieldRealGenerationDisabledError("mock refusal before any client call")
        return super().create_job(job_type, prompt, **params)


def _paths(sandbox: Path):
    state = sandbox / "state"
    return state / "executed_requests.json", state / "consumed_authorizations.json", state / "locks"


class _Sandbox(unittest.TestCase):
    def setUp(self):
        self.sandbox = Path(tempfile.mkdtemp(prefix="phase_b_single_use_"))
        self.addCleanup(shutil.rmtree, self.sandbox, ignore_errors=True)
        self.state_path, self.registry_path, self.lock_dir = _paths(self.sandbox)

    def _store(self, **kwargs):
        return FileExecutedRequestStore(self.state_path, **kwargs)

    def _chain(self, cost=10.0, store=None, **provider_kwargs):
        provider = _CountingProvider(cost_per_job=cost, available_credits=1000.0, **provider_kwargs)
        store = store or self._store()
        gate = GenerationApprovalGate(provider, executed_request_store=store)
        service = GenerationJobService(provider, gate, lock=FileCriticalSectionLock(self.lock_dir))
        return provider, store, gate, service

    def _registry(self):
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def _consumed_digests(self):
        return set(self._registry()["consumed_authorization_sha256"])


# ----------------------------------------------------------------------
# 1. Registre séparé : P3.89 préservé, contenu minimal
# ----------------------------------------------------------------------


class TestSeparateMinimalRegistry(_Sandbox):
    def test_executed_requests_never_contains_authorization_material(self):
        auth = _auth()
        _, _, _, service = self._chain()
        service.execute(_request(auth), interval_seconds=0)
        text = self.state_path.read_text(encoding="utf-8")
        for forbidden in ("authorization", "authorized_by_human", "prompt", "approved",
                          auth.authorization_id, _digest(auth.authorization_id)):
            self.assertNotIn(forbidden, text)

    def test_registry_holds_only_the_digest_and_minimal_metadata(self):
        auth = _auth()
        _, _, _, service = self._chain()
        service.execute(_request(auth), interval_seconds=0)
        registry = self._registry()
        self.assertEqual(set(registry), {"consumed_authorization_sha256"})
        self.assertEqual(self._consumed_digests(), {_digest(auth.authorization_id)})
        record = registry["consumed_authorization_sha256"][_digest(auth.authorization_id)]
        self.assertEqual(set(record), {"request_id", "consumed_at"})
        self.assertEqual(record["request_id"], RID)
        text = self.registry_path.read_text(encoding="utf-8")
        for forbidden in (auth.authorization_id, "phase-b-note-marker", "authorized_by_human",
                          "authorized_at", auth.authorized_at, "prompt", "Un prompt de test"):
            self.assertNotIn(forbidden, text)

    def test_registry_lives_next_to_the_store_with_its_own_lock(self):
        store = self._store()
        registry = store.authorization_registry
        self.assertIsInstance(registry, FileAuthorizationConsumptionRegistry)
        self.assertEqual(registry.path, self.registry_path)
        self.assertNotEqual(registry.lock_path, store.lock_path)
        self.assertIsInstance(InMemoryExecutedRequestStore().authorization_registry,
                              InMemoryAuthorizationConsumptionRegistry)


# ----------------------------------------------------------------------
# 2. Consultation / préparation : jamais de consommation
# ----------------------------------------------------------------------


class TestReadsNeverConsume(_Sandbox):
    def test_repeated_evaluations_never_consume_nor_write(self):
        provider, _, gate, _ = self._chain()
        request = _request()
        for _ in range(5):
            self.assertEqual(gate.evaluate(request).decision, D.APPROVED)
        self.assertFalse(gate.is_authorization_consumed(request.real_generation_authorization.authorization_id))
        self.assertFalse((self.sandbox / "state").exists())
        self.assertEqual(provider.create_calls, 0)

    def test_repeated_activation_preparations_and_readiness_never_consume(self):
        from agents.activation_contract import RequestScopedActivationService
        from agents.activation_readiness import ActivationReadinessEvaluator
        from agents.prompt_assembly_system import PromptAssemblySystem
        from agents.release_candidate_identity_lock import (
            ReleaseCandidateIdentityLock,
            VIDEO_005_RELEASE_CANDIDATE as C,
        )
        from integrations.higgsfield.types import MediaReference

        auth = _auth(C.request_id)
        request = GenerationRequest(
            request_id=C.request_id, job_type=C.job_type,
            prompt=PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id),
            duration=C.duration, resolution=C.resolution, aspect_ratio=C.aspect_ratio,
            approved=True,
            start_image=MediaReference(
                role="master_avatar",
                source=str(PROJECT_ROOT / "assets" / "zephyr" / "avatar" / "avatar_master.png"),
                sha256=None,
            ),
            image_references=(MediaReference(
                role="face_reference",
                source=str(PROJECT_ROOT / "assets" / "zephyr" / "references" / "mon avatar habille.png"),
                sha256=None,
            ),),
            real_generation_authorization=auth,
        )
        provider = _CountingProvider(cost_per_job=67.5, available_credits=100.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(provider, executed_request_store=self._store(), identity_lock=identity_lock)
        activation_service = RequestScopedActivationService(gate, identity_lock)
        readiness = ActivationReadinessEvaluator(gate, identity_lock, activation_service)

        for _ in range(3):
            contract = activation_service.prepare_activation(request)
            self.assertEqual(activation_service.inspect_activation(request, contract), [])
            readiness.evaluate(request, activation_contract=contract)

        self.assertFalse(gate.is_authorization_consumed(auth.authorization_id))
        self.assertFalse((self.sandbox / "state").exists())
        self.assertEqual(gate.evaluate(request).decision, D.APPROVED)
        self.assertEqual(provider.create_calls, 0)


# ----------------------------------------------------------------------
# 3. Consommation unique, juste avant le marqueur et create_job()
# ----------------------------------------------------------------------


class TestConsumedOnceBeforeCreateJob(_Sandbox):
    def test_consumption_is_durable_before_create_job_is_called(self):
        seen = {}
        auth = _auth()

        def _observe(params):
            reader = FileExecutedRequestStore(self.state_path)
            seen["consumed"] = reader.authorization_registry.is_consumed(auth.authorization_id)
            seen["in_flight"] = reader.is_unknown(RID)

        provider, _, _, service = self._chain(on_create=_observe)
        service.execute(_request(auth), interval_seconds=0)
        self.assertEqual(seen, {"consumed": True, "in_flight": True})
        self.assertEqual(provider.create_calls, 1)

    def test_same_authorization_never_reaches_create_job_twice(self):
        auth = _auth()
        provider, _, _, service = self._chain()
        service.execute(_request(auth), interval_seconds=0)
        with self.assertRaises(GenerationJobExecutionError):
            service.execute(_request(auth), interval_seconds=0)
        self.assertEqual(provider.create_calls, 1)

    def test_execute_orders_consumption_before_marker_before_create_job(self):
        tree = ast.parse((PROJECT_ROOT / "agents" / "generation_job_service.py").read_text(encoding="utf-8"))
        execute = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "execute")
        first = {}
        for node in ast.walk(execute):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                first.setdefault(node.func.attr, node.lineno)
                first[node.func.attr] = min(first[node.func.attr], node.lineno)
        self.assertLess(first["evaluate"], first["consume_authorization"])
        self.assertLess(first["consume"], first["consume_authorization"])
        self.assertLess(first["consume_authorization"], first["in_flight"])
        self.assertLess(first["in_flight"], first["create_job"])
        calls = [n.func.attr for n in ast.walk(execute)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        self.assertEqual(calls.count("consume_authorization"), 1)

    def test_invalid_authorization_id_is_refused_before_any_write(self):
        _, _, gate, _ = self._chain()
        for bad in (None, "", "../escape", "x" * 129, 42, " lead"):
            with self.subTest(bad=bad), self.assertRaises(InvalidAuthorizationIdError):
                gate.consume_authorization(RID, bad)
        self.assertFalse((self.sandbox / "state").exists())


# ----------------------------------------------------------------------
# 4. Refus AVANT le point de consommation : rien n'est consommé
# ----------------------------------------------------------------------


class TestRefusalBeforeConsumptionPoint(_Sandbox):
    def _assert_untouched(self, provider, gate, auth):
        self.assertEqual(provider.create_calls, 0)
        self.assertFalse(gate.is_authorization_consumed(auth.authorization_id))
        self.assertFalse(self.registry_path.exists())

    def test_gate_refusal_does_not_consume(self):
        auth = _auth()
        provider, _, gate, service = self._chain()
        with self.assertRaises(GenerationJobExecutionError):
            service.execute(_request(auth, approved=False), interval_seconds=0)
        self._assert_untouched(provider, gate, auth)

    def test_budget_refusal_does_not_consume(self):
        auth = _auth()
        provider = _CountingProvider(cost_per_job=10.0, available_credits=1.0)
        gate = GenerationApprovalGate(provider, executed_request_store=self._store())
        with self.assertRaises(GenerationJobExecutionError):
            GenerationJobService(provider, gate).execute(_request(auth), interval_seconds=0)
        self._assert_untouched(provider, gate, auth)

    def test_busy_critical_section_does_not_consume(self):
        auth = _auth()
        provider, _, gate, service = self._chain()
        with FileCriticalSectionLock(self.lock_dir).acquire(RID):
            with self.assertRaises(CriticalSectionBusyError):
                service.execute(_request(auth), interval_seconds=0)
        self._assert_untouched(provider, gate, auth)

    def test_request_already_recorded_does_not_consume(self):
        auth = _auth()
        provider, store, gate, service = self._chain()
        store.mark_unknown(RID, reason="prior ambiguity")
        with self.assertRaises(GenerationJobExecutionError):
            service.execute(_request(auth), interval_seconds=0)
        self._assert_untouched(provider, gate, auth)

    def test_rejected_activation_contract_does_not_consume(self):
        from agents.activation_contract import RequestScopedActivationContract

        auth = _auth()
        provider = _CountingProvider(cost_per_job=10.0, available_credits=1000.0)
        gate = GenerationApprovalGate(provider, executed_request_store=self._store())
        activation_service = MagicMock()
        activation_service.inspect_activation.return_value = ["forged contract"]
        service = GenerationJobService(provider, gate, activation_service=activation_service)
        forged = RequestScopedActivationContract(
            activation_id="forged", request_id=RID, job_type="seedance_2_0", duration=5,
            resolution=None, aspect_ratio=None, prompt_sha256="0" * 64,
            authorization_id=auth.authorization_id, created_at="x",
        )
        with self.assertRaises(GenerationJobExecutionError):
            service.execute(_request(auth), activation_contract=forged, interval_seconds=0)
        self._assert_untouched(provider, gate, auth)
        activation_service.consume.assert_not_called()


# ----------------------------------------------------------------------
# 5. Définitive : refus du Provider, erreur, arrêt après consommation
# ----------------------------------------------------------------------


class TestConsumptionIsNeverUndone(_Sandbox):
    def test_provider_refusal_rolls_back_marker_but_keeps_consumption(self):
        auth = _auth()
        provider, store, gate, service = self._chain(refuse=True)
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            service.execute(_request(auth), interval_seconds=0)

        self.assertFalse(self.state_path.exists())  # marqueur retiré (P3.91 inchangé)
        self.assertFalse(store.is_unknown(RID))
        self.assertTrue(gate.is_authorization_consumed(auth.authorization_id))

        result = gate.evaluate(_request(auth))
        self.assertEqual(result.decision, D.NEEDS_APPROVAL)
        self.assertTrue(any(CONSUMED_REASON in r for r in result.reasons), result.reasons)
        with self.assertRaises(GenerationJobExecutionError):
            service.execute(_request(auth), interval_seconds=0)
        self.assertEqual(provider.create_calls, 1)
        # Une NOUVELLE autorisation reste possible pour cette requête.
        self.assertEqual(gate.evaluate(_request(_auth())).decision, D.APPROVED)

    def test_real_provider_refusal_keeps_consumption(self):
        client = MagicMock()
        client.estimate_cost.return_value = {"credits": 10.0}
        client.account_status.return_value = {"credits": 1000.0}
        client.get_model.return_value = {
            "job_type": "seedance_2_0", "display_name": "d",
            "params": [
                {"name": "prompt", "type": "string", "required": True},
                {"name": "duration", "type": "integer", "required": False, "default": 5},
            ],
        }
        provider = HiggsfieldProvider(client=client)
        gate = GenerationApprovalGate(provider, executed_request_store=self._store())
        service = GenerationJobService(provider, gate, lock=FileCriticalSectionLock(self.lock_dir))
        auth = _auth()
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            service.execute(_request(auth), interval_seconds=0)
        client.create_job.assert_not_called()
        self.assertTrue(gate.is_authorization_consumed(auth.authorization_id))
        self.assertEqual(gate.evaluate(_request(auth)).decision, D.NEEDS_APPROVAL)

    def test_other_provider_failure_keeps_consumption_and_unknown(self):
        auth = _auth()

        def _boom(params):
            raise TimeoutError("response lost")

        _, store, gate, service = self._chain(on_create=_boom)
        with self.assertRaises(TimeoutError):
            service.execute(_request(auth), interval_seconds=0)
        self.assertTrue(gate.is_authorization_consumed(auth.authorization_id))
        self.assertTrue(store.is_unknown(RID))

    def test_failure_between_consumption_and_marker_burns_the_authorization(self):
        auth = _auth()
        provider, store, gate, service = self._chain()
        with patch.object(FileExecutedRequestStore, "_begin_in_flight", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                service.execute(_request(auth), interval_seconds=0)
        self.assertEqual(provider.create_calls, 0)
        self.assertFalse(store.is_unknown(RID))  # exécution jamais démarrée
        self.assertTrue(gate.is_authorization_consumed(auth.authorization_id))  # brûlée
        self.assertEqual(gate.evaluate(_request(auth)).decision, D.NEEDS_APPROVAL)
        self.assertEqual(gate.evaluate(_request(_auth())).decision, D.APPROVED)

    def test_in_memory_consumption_is_never_undone_by_rollback(self):
        store = InMemoryExecutedRequestStore()
        provider = _CountingProvider(cost_per_job=10.0, available_credits=1000.0, refuse=True)
        gate = GenerationApprovalGate(provider, executed_request_store=store)
        auth = _auth()
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            GenerationJobService(provider, gate).execute(_request(auth), interval_seconds=0)
        self.assertFalse(store.is_unknown(RID))
        self.assertTrue(store.authorization_registry.is_consumed(auth.authorization_id))


# ----------------------------------------------------------------------
# 6. Redémarrage
# ----------------------------------------------------------------------


class TestRestart(_Sandbox):
    def test_consumption_survives_store_and_gate_recreation(self):
        auth = _auth()
        _, _, _, service = self._chain(refuse=True)
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            service.execute(_request(auth), interval_seconds=0)

        provider, _, gate, service = self._chain()  # "redémarrage"
        self.assertTrue(gate.is_authorization_consumed(auth.authorization_id))
        self.assertEqual(gate.evaluate(_request(auth)).decision, D.NEEDS_APPROVAL)
        with self.assertRaises(GenerationJobExecutionError):
            service.execute(_request(auth), interval_seconds=0)
        self.assertEqual(provider.create_calls, 0)

    def test_process_killed_after_consumption_before_marker_stays_burned(self):
        proc = subprocess.run(
            [sys.executable, "-B", __file__, WORKER_FLAG, "burn", str(self.sandbox), "0"],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(proc.returncode, 97, proc.stderr[-500:])
        provider, store, gate, _ = self._chain()
        self.assertFalse(store.is_unknown(RID))
        self.assertFalse(self.state_path.exists())
        auth = _auth(authorization_id="burned-auth")
        self.assertTrue(gate.is_authorization_consumed(auth.authorization_id))
        self.assertEqual(gate.evaluate(_request(auth)).decision, D.NEEDS_APPROVAL)
        self.assertEqual(provider.create_calls, 0)

    def test_in_memory_registry_does_not_survive_restart(self):
        first = InMemoryAuthorizationConsumptionRegistry()
        first.consume("auth-1", RID)
        self.assertTrue(first.is_consumed("auth-1"))
        self.assertFalse(InMemoryAuthorizationConsumptionRegistry().is_consumed("auth-1"))


# ----------------------------------------------------------------------
# 7. Concurrence : threads et processus
# ----------------------------------------------------------------------


def _race(workers, target):
    barrier = threading.Barrier(workers)
    results = []

    def run(i):
        barrier.wait()
        try:
            target(i)
            results.append("OK")
        except BaseException as error:  # noqa: B902 -- résultat observé
            results.append(type(error).__name__)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    return results


class TestThreadConcurrency(_Sandbox):
    def _assert_single_consumer(self, registry):
        results = _race(8, lambda i: registry.consume("shared-auth", f"r{i}"))
        self.assertEqual(results.count("OK"), 1, results)
        self.assertEqual(results.count("AuthorizationAlreadyConsumedError"), 7, results)

    def test_file_registry_threads_consume_once(self):
        self._assert_single_consumer(self._store().authorization_registry)
        self.assertEqual(self._consumed_digests(), {_digest("shared-auth")})

    def test_in_memory_registry_threads_consume_once(self):
        self._assert_single_consumer(InMemoryAuthorizationConsumptionRegistry())

    def test_execute_threads_with_noop_lock_create_at_most_one_job(self):
        for store in (self._store(), InMemoryExecutedRequestStore()):
            with self.subTest(store=type(store).__name__):
                provider = _CountingProvider(
                    cost_per_job=10.0, available_credits=1000.0,
                    on_create=lambda params: time.sleep(0.05),
                )
                gate = GenerationApprovalGate(provider, executed_request_store=store)
                service = GenerationJobService(provider, gate)  # NoOp lock
                auth = _auth(authorization_id=f"thread-auth-{type(store).__name__}")
                results = _race(6, lambda i: service.execute(_request(auth), interval_seconds=0))
                self.assertEqual(provider.create_calls, 1, results)
                self.assertEqual(results.count("OK"), 1, results)


def _worker(mode, sandbox, wid):
    sandbox = Path(sandbox)
    state_path, _, _ = _paths(sandbox)
    if mode == "burn":
        provider = _CountingProvider(cost_per_job=10.0, available_credits=1000.0)
        gate = GenerationApprovalGate(provider, executed_request_store=FileExecutedRequestStore(state_path))
        gate.in_flight = lambda request_id: os._exit(97)  # arrêt dur après consommation
        GenerationJobService(provider, gate).execute(
            _request(_auth(authorization_id="burned-auth")), interval_seconds=0
        )
        os._exit(1)
    (sandbox / f"ready-{wid}").write_text("1")
    while not (sandbox / "go").exists():
        time.sleep(0.001)
    try:
        if mode == "registry":
            FileExecutedRequestStore(state_path).authorization_registry.consume("shared-auth", f"r{wid}")
        else:
            provider = _CountingProvider(cost_per_job=10.0, available_credits=1000.0)
            ledger = sandbox / "ledger"
            ledger.mkdir(exist_ok=True)
            provider.on_create = lambda params: (ledger / f"job-{wid}").write_text("1")
            gate = GenerationApprovalGate(provider, executed_request_store=FileExecutedRequestStore(state_path))
            service = GenerationJobService(provider, gate)  # NoOp lock : le registre arbitre
            service.execute(_request(_auth(authorization_id="shared-auth")), interval_seconds=0)
        print(json.dumps({"result": "OK"}))
    except BaseException as error:  # noqa: B902
        print(json.dumps({"result": type(error).__name__}))


class TestProcessConcurrency(_Sandbox):
    def _run(self, mode, count=6):
        procs = [
            subprocess.Popen(
                [sys.executable, "-B", __file__, WORKER_FLAG, mode, str(self.sandbox), str(i)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            for i in range(count)
        ]
        deadline = time.monotonic() + 120
        while len(list(self.sandbox.glob("ready-*"))) < count:
            self.assertLess(time.monotonic(), deadline, "workers never reached the barrier")
            time.sleep(0.01)
        (self.sandbox / "go").write_text("1")
        results = []
        for proc in procs:
            out, err = proc.communicate(timeout=240)
            lines = [line for line in out.splitlines() if line.startswith("{")]
            self.assertTrue(lines, err[-500:])
            results.append(json.loads(lines[-1])["result"])
        return results

    def test_processes_consume_the_same_authorization_once(self):
        results = self._run("registry")
        self.assertEqual(results.count("OK"), 1, results)
        self.assertEqual(results.count("AuthorizationAlreadyConsumedError"), 5, results)
        self.assertEqual(self._consumed_digests(), {_digest("shared-auth")})

    def test_processes_executing_the_same_authorization_create_one_job(self):
        results = self._run("execute")
        self.assertEqual(results.count("OK"), 1, results)
        self.assertEqual(len(list((self.sandbox / "ledger").glob("job-*"))), 1, results)
        for result in results:
            self.assertIn(result, {"OK", "GenerationJobExecutionError", "AuthorizationAlreadyConsumedError",
                                   "ExecutedRequestStoreConflictError"})


# ----------------------------------------------------------------------
# 8. Corruption, verrou, écriture, registre absent : fail closed
# ----------------------------------------------------------------------


class TestFailClosed(_Sandbox):
    def _write_registry(self, payload):
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        text = payload if isinstance(payload, str) else json.dumps(payload)
        self.registry_path.write_text(text, encoding="utf-8")

    def test_corrupted_registry_blocks_without_create_job(self):
        good = {"request_id": RID, "consumed_at": "x"}
        for bad in ("{not json", [], {}, {"consumed_authorization_sha256": []},
                    {"consumed_authorization_sha256": {"raw-id": good}},
                    {"consumed_authorization_sha256": {"0" * 64: "not-a-record"}},
                    {"consumed_authorization_sha256": {"0" * 64: {"consumed_at": "x"}}}):
            with self.subTest(bad=bad):
                self._write_registry(bad)
                provider, store, gate, service = self._chain()
                self.assertEqual(gate.evaluate(_request()).decision, D.BLOCKED)
                with self.assertRaises(GenerationJobExecutionError):
                    service.execute(_request(), interval_seconds=0)
                with self.assertRaises(AuthorizationRegistryCorruptedError):
                    store.authorization_registry.consume("auth-x", RID)
                self.assertEqual(provider.create_calls, 0)

    def test_registry_lock_timeout_blocks_evaluation_and_consumption(self):
        store = self._store(lock_timeout_seconds=0.2)
        provider, _, gate, service = self._chain(store=store)
        self.registry_path.parent.mkdir(parents=True)
        store.authorization_registry.lock_path.write_text("held by a test")

        # Registre absent : l'évaluation ne verrouille pas (APPROVED),
        # mais la consommation échoue fermée -> aucun create_job().
        self.assertEqual(gate.evaluate(_request()).decision, D.APPROVED)
        with self.assertRaises(AuthorizationRegistryLockTimeoutError):
            service.execute(_request(), interval_seconds=0)
        self.assertEqual(provider.create_calls, 0)
        self.assertFalse(store.is_unknown(RID))

        # Registre présent : l'évaluation elle-même est BLOCKED.
        self._write_registry({"consumed_authorization_sha256": {}})
        self.assertEqual(gate.evaluate(_request()).decision, D.BLOCKED)
        self.assertTrue(store.authorization_registry.lock_path.exists(), "never auto-removed")

    def test_write_failure_neither_consumes_nor_calls_create_job(self):
        auth = _auth()
        provider, store, gate, service = self._chain()
        with patch.object(FileAuthorizationConsumptionRegistry, "_write", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                service.execute(_request(auth), interval_seconds=0)
        self.assertEqual(provider.create_calls, 0)
        self.assertFalse(gate.is_authorization_consumed(auth.authorization_id))
        self.assertFalse(store.is_unknown(RID))
        self.assertEqual(list(self.registry_path.parent.glob(".tmp-*")), [])

    def test_invalid_authorization_id_never_approves_nor_creates(self):
        for bad in ("", "../escape", "x" * 129, " leading-space"):
            for cost in (10.0, None):
                with self.subTest(bad=bad, cost=cost):
                    provider, _, gate, service = self._chain(cost=cost)
                    auth = _auth(authorization_id=bad)
                    result = gate.evaluate(_request(auth))
                    self.assertEqual(result.decision, D.NEEDS_APPROVAL)
                    self.assertTrue(any("authorization_id is invalid" in r for r in result.reasons))
                    with self.assertRaises(GenerationJobExecutionError):
                        service.execute(_request(auth), interval_seconds=0)
                    self.assertEqual(provider.create_calls, 0)

    def test_store_without_registry_fails_closed(self):
        class _LegacyStore:
            def is_executed(self, request_id):
                return False

            def is_unknown(self, request_id):
                return False

            def in_flight(self, request_id):
                raise AssertionError("must never be reached")

        provider = _CountingProvider(cost_per_job=10.0, available_credits=1000.0)
        gate = GenerationApprovalGate(provider, executed_request_store=_LegacyStore())
        self.assertEqual(gate.evaluate(_request()).decision, D.BLOCKED)
        with self.assertRaises(ExecutedRequestStoreCorruptedError):
            gate.consume_authorization(RID, "auth-1")
        with self.assertRaises(GenerationJobExecutionError):
            GenerationJobService(provider, gate).execute(_request(), interval_seconds=0)
        self.assertEqual(provider.create_calls, 0)


# ----------------------------------------------------------------------
# 9. Compatibilité des anciens fichiers
# ----------------------------------------------------------------------


class TestLegacyFileCompatibility(_Sandbox):
    def test_missing_registry_file_reads_as_empty_and_first_use_is_accepted(self):
        self.state_path.parent.mkdir(parents=True)
        self.state_path.write_text(
            json.dumps({"executed_requests": {"old": {"executed_at": "x"}}, "unknown_requests": {}}),
            encoding="utf-8",
        )
        auth = _auth()
        provider, store, gate, service = self._chain()
        self.assertFalse(gate.is_authorization_consumed(auth.authorization_id))
        self.assertEqual(gate.evaluate(_request(auth)).decision, D.APPROVED)
        self.assertFalse(self.registry_path.exists())  # lectures : rien créé
        self.assertFalse(store.authorization_registry.lock_path.exists())

        service.execute(_request(auth), interval_seconds=0)  # premier usage accepté
        self.assertEqual(provider.create_calls, 1)
        self.assertEqual(self._consumed_digests(), {_digest(auth.authorization_id)})
        self.assertFalse(store.authorization_registry.lock_path.exists())

    def test_p2_15_and_p2_20_files_are_unchanged_in_shape(self):
        legacy_payloads = (
            {"executed_requests": {"old": {"executed_at": "x"}}},
            {"executed_requests": {"old": {"executed_at": "x"}},
             "unknown_requests": {"amb": {"marked_at": "y", "reason": "r"}}},
        )
        for payload in legacy_payloads:
            with self.subTest(keys=sorted(payload)):
                shutil.rmtree(self.sandbox / "state", ignore_errors=True)
                self.state_path.parent.mkdir(parents=True)
                self.state_path.write_text(json.dumps(payload), encoding="utf-8")
                _, _, gate, service = self._chain()
                self.assertEqual(gate.evaluate(_request(request_id="old")).decision, D.ALREADY_EXECUTED)
                auth = _auth("new")
                service.execute(_request(auth, request_id="new"), interval_seconds=0)
                state = json.loads(self.state_path.read_text(encoding="utf-8"))
                self.assertEqual(set(state), {"executed_requests", "unknown_requests"})
                self.assertEqual(set(state["executed_requests"]), {"old", "new"})
                self.assertEqual(state["unknown_requests"], payload.get("unknown_requests", {}))
                self.assertEqual(self._consumed_digests(), {_digest(auth.authorization_id)})


# ----------------------------------------------------------------------
# 10. Autorisation consommée : jamais APPROVED, KNOWN et UNKNOWN
# ----------------------------------------------------------------------


class TestConsumedAuthorizationNeverApproved(_Sandbox):
    def test_known_and_unknown_cost_paths(self):
        for store_factory in (InMemoryExecutedRequestStore, self._store):
            for cost in (10.0, None):
                with self.subTest(store=store_factory.__name__, cost=cost):
                    shutil.rmtree(self.sandbox / "state", ignore_errors=True)
                    store = store_factory()
                    auth = _auth()
                    store.authorization_registry.consume(auth.authorization_id, RID)
                    provider = _CountingProvider(cost_per_job=cost, available_credits=1000.0)
                    gate = GenerationApprovalGate(provider, executed_request_store=store)
                    result = gate.evaluate(_request(auth))
                    self.assertEqual(result.decision, D.NEEDS_APPROVAL)
                    self.assertIn(
                        f"real_generation_authorization '{auth.authorization_id}' has already been "
                        f"consumed by a prior execution attempt; a new explicit human authorization "
                        f"is required.",
                        result.reasons,
                    )
                    with self.assertRaises(GenerationJobExecutionError):
                        GenerationJobService(provider, gate).execute(_request(auth), interval_seconds=0)
                    self.assertEqual(provider.create_calls, 0)


# ----------------------------------------------------------------------
# 11. Readiness : signale le stockage non persistant, ne consomme rien
# ----------------------------------------------------------------------


class TestReadinessSignals(_Sandbox):
    def _evaluator(self, store):
        from agents.activation_contract import RequestScopedActivationService
        from agents.activation_readiness import ActivationReadinessEvaluator
        from agents.release_candidate_identity_lock import (
            ReleaseCandidateIdentityLock,
            VIDEO_005_RELEASE_CANDIDATE as C,
        )

        provider = _CountingProvider(cost_per_job=10.0, available_credits=1000.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(provider, executed_request_store=store, identity_lock=identity_lock)
        return ActivationReadinessEvaluator(gate, identity_lock, RequestScopedActivationService(gate, identity_lock))

    def test_non_persistent_store_is_reported(self):
        safe, reasons = self._evaluator(InMemoryExecutedRequestStore())._check_replay(_request())
        self.assertFalse(safe)
        self.assertTrue(any("not persistent" in r for r in reasons), reasons)

    def test_persistent_store_accepted_and_consumption_reported_without_consuming(self):
        store = self._store()
        auth = _auth()
        evaluator = self._evaluator(store)
        self.assertEqual(evaluator._check_replay(_request(auth)), (True, []))
        self.assertFalse((self.sandbox / "state").exists())

        store.authorization_registry.consume(auth.authorization_id, RID)
        safe, reasons = evaluator._check_replay(_request(auth))
        self.assertFalse(safe)
        self.assertTrue(any("already been consumed" in r for r in reasons), reasons)


# ----------------------------------------------------------------------
# 12. Configuration de production inchangée ; isolation des tests
# ----------------------------------------------------------------------


class TestDirectorStateConfiguration(_Sandbox):
    def test_default_chain_points_to_the_real_state_directory_without_touching_it(self):
        from director import AIDirector

        director = AIDirector()
        chain = director._build_default_chain()  # construction pure : aucun accès disque
        store = chain.gate.executed_request_store
        self.assertIsInstance(store, FileExecutedRequestStore)
        self.assertEqual(store.path, director.root / "state" / "executed_requests.json")
        self.assertEqual(store.authorization_registry.path, director.root / "state" / "consumed_authorizations.json")
        self.assertEqual(chain.lock.lock_dir, director.root / "state" / "locks")

    def test_isolation_helper_redirects_only_the_paths(self):
        from director import AIDirector

        director = AIDirector()
        with isolated_director_state(self.sandbox) as state:
            chain = director._build_default_chain()
        store = chain.gate.executed_request_store
        self.assertEqual(state, self.sandbox / "state")
        self.assertIsInstance(store, FileExecutedRequestStore)
        self.assertIsInstance(chain.provider, HiggsfieldProvider)
        self.assertEqual(store.path, state / "executed_requests.json")
        self.assertEqual(store.authorization_registry.path, state / "consumed_authorizations.json")
        self.assertIsInstance(chain.lock, FileCriticalSectionLock)
        self.assertEqual(chain.lock.lock_dir, state / "locks")
        # Hors du contexte, le Director retrouve ses chemins de production.
        self.assertEqual(
            director._build_default_chain().gate.executed_request_store.path,
            director.root / "state" / "executed_requests.json",
        )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == WORKER_FLAG:
        _worker(*sys.argv[2:])
    else:
        unittest.main()
