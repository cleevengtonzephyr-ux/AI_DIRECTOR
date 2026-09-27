"""
Tests — Phase P3.102 : verrou du replay store, handle conservé (F5).

Défaut démontré en P3.102 (audit), avec de vrais processus OS sous
Windows : `FileExecutedRequestStore._locked()` fermait le fd du verrou
juste après l'écriture du marqueur, AVANT le `yield`. Le fichier de
verrou n'avait alors plus aucun handle ouvert : un autre processus
pouvait le supprimer pendant qu'il était détenu, créer un verrou de
remplacement et entrer dans la section critique en même temps que le
détenteur. Scénario reproduit (4/4) :

    A détient le verrou (état lu) -> B supprime le verrou -> B acquiert
    -> B écrit -> A écrit -> l'enregistrement de B est effacé.

Correction : le fd reste ouvert jusqu'à la libération (fermé, puis
verrou supprimé), comme `critical_section_lock.py` et
`certificate_lifecycle_lock.py`. Sous Windows, la suppression par un
autre processus est alors refusée (WinError 32) et B échoue en timeout
(fail closed, BLOCKED au Gate).

Toutes les évaluations utilisent exclusivement MockHiggsfieldProvider,
dans des répertoires temporaires. Aucun appel réseau, aucun CLI réel,
aucun `create_job()`, aucun crédit consommé. Les workers
multiprocessing sont des fonctions de module (pickling sous 'spawn',
Windows) ; la synchronisation passe par des `Event`, jamais par des
délais.
"""

import json
import multiprocessing
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.executed_request_store import FileExecutedRequestStore, ExecutedRequestStoreLockTimeoutError
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider

RID = "p3-102"


def _request(request_id=RID) -> GenerationRequest:
    return GenerationRequest(
        request_id=request_id,
        job_type="seedance_2_0",
        prompt="Un prompt de test suffisamment explicite.",
        duration=5,
        approved=True,
        real_generation_authorization=RealGenerationAuthorization(
            request_id=request_id, authorized_by_human=True
        ),
    )


def _worker_paused_mark_executed(state_path_str, request_id, inside, proceed, result_queue):
    """Processus A : `mark_executed()` réel, suspendu entre sa lecture et
    son écriture atomique -- donc DANS la section critique, verrou tenu."""

    store = FileExecutedRequestStore(Path(state_path_str), lock_timeout_seconds=10.0)
    write_full = store._write_full

    def paused_write(data):
        inside.set()
        proceed.wait(120)
        write_full(data)

    store._write_full = paused_write
    try:
        store.mark_executed(request_id)
        result_queue.put("OK")
    except Exception as error:  # noqa: BLE001 -- rapporté, jamais avalé
        result_queue.put(repr(error))


class _SandboxCase(unittest.TestCase):
    def setUp(self):
        self.sandbox = Path(tempfile.mkdtemp(prefix="p3_102_"))
        self.addCleanup(shutil.rmtree, self.sandbox, ignore_errors=True)
        self.state_path = self.sandbox / "state" / "executed_requests.json"
        self.lock_path = self.state_path.with_name(self.state_path.name + ".lock")

    def _start_holder(self, request_id):
        """Démarre A et attend qu'il soit dans la section critique."""

        inside, proceed = multiprocessing.Event(), multiprocessing.Event()
        results = multiprocessing.Queue()
        holder = multiprocessing.Process(
            target=_worker_paused_mark_executed,
            args=(str(self.state_path), request_id, inside, proceed, results),
        )
        holder.start()

        def stop():
            proceed.set()
            holder.join(timeout=120)
            if holder.is_alive():
                holder.kill()

        self.addCleanup(stop)
        self.assertTrue(inside.wait(120), "holder never entered the critical section")
        return holder, proceed, results

    def _finish_holder(self, holder, proceed, results):
        proceed.set()
        holder.join(timeout=120)
        self.assertFalse(holder.is_alive(), "holder process did not terminate in time")
        self.assertEqual(holder.exitcode, 0)
        return results.get(timeout=10)

    def _executed(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))["executed_requests"]


@unittest.skipUnless(os.name == "nt", "the delete is only refused while open on Windows")
class TestF5_HeldLockCannotBeReplaced(_SandboxCase):
    def test_held_lock_delete_is_refused_and_a_second_process_fails_closed(self):
        holder, proceed, results = self._start_holder("REQ-A")

        # B (ce processus) : la suppression du verrou détenu est refusée.
        with self.assertRaises(PermissionError) as refused:
            os.unlink(self.lock_path)
        self.assertEqual(refused.exception.winerror, 32)
        self.assertTrue(self.lock_path.exists())
        # Le marqueur de diagnostic reste lisible pendant la détention.
        self.assertIn('"pid"', self.lock_path.read_text(encoding="utf-8"))

        # B ne peut pas acquérir de remplacement : timeout, fail closed.
        store = FileExecutedRequestStore(self.state_path, lock_timeout_seconds=0.3)
        with self.assertRaises(ExecutedRequestStoreLockTimeoutError):
            store.mark_executed("REQ-B")
        with self.assertRaises(ExecutedRequestStoreLockTimeoutError):
            store.is_executed("REQ-B")

        # Gate : BLOCKED, jamais APPROVED ; aucun job créé.
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
        gate = GenerationApprovalGate(provider, executed_request_store=store)
        self.assertEqual(gate.evaluate(_request()).decision, GenerationApprovalDecision.BLOCKED)
        self.assertEqual(len(provider._jobs), 0)

        self.assertEqual(self._finish_holder(holder, proceed, results), "OK")
        self.assertFalse(self.lock_path.exists(), "a cleanly released store lock was left on disk")
        self.assertEqual(sorted(self._executed()), ["REQ-A"])

    def test_historical_lost_update_is_no_longer_possible(self):
        # A détient le verrou et a déjà lu l'état (sans REQ-B).
        holder, proceed, results = self._start_holder("REQ-A")

        # B supprime le verrou puis tente d'écrire : avant P3.102, la
        # suppression réussissait, B écrivait REQ-B, puis A l'effaçait.
        delete_refused = False
        try:
            os.unlink(self.lock_path)
        except PermissionError:
            delete_refused = True
        self.assertTrue(delete_refused, "the held replay-store lock was deleted by another process")

        store = FileExecutedRequestStore(self.state_path, lock_timeout_seconds=0.3)
        with self.assertRaises(ExecutedRequestStoreLockTimeoutError):
            store.mark_executed("REQ-B")
        self.assertFalse(self.state_path.exists(), "B wrote while A was inside the critical section")

        # A écrit ; B réessaie ensuite, séquentiellement : rien n'est perdu.
        self.assertEqual(self._finish_holder(holder, proceed, results), "OK")
        store.mark_executed("REQ-B")
        self.assertEqual(sorted(self._executed()), ["REQ-A", "REQ-B"])
        self.assertFalse(self.lock_path.exists())


class TestF5_LockHandleLifetime(_SandboxCase):
    """Indépendant de la plateforme : le fd n'est jamais fermé avant la
    fin de la section critique."""

    def test_fd_stays_open_for_the_whole_critical_section(self):
        store = FileExecutedRequestStore(self.state_path)
        with mock.patch("agents.executed_request_store.os.close", wraps=os.close) as close:
            with store._locked(context="p3.102", write=True):
                close.assert_not_called()
                self.assertTrue(self.lock_path.exists())
                self.assertIn('"pid"', self.lock_path.read_text(encoding="utf-8"))
            close.assert_called_once()
        self.assertFalse(self.lock_path.exists())

    def test_exception_inside_the_section_still_closes_and_releases(self):
        store = FileExecutedRequestStore(self.state_path)
        with mock.patch("agents.executed_request_store.os.close", wraps=os.close) as close:
            with self.assertRaises(ZeroDivisionError):
                with store._locked(context="p3.102", write=True):
                    close.assert_not_called()
                    1 / 0
            close.assert_called_once()
        self.assertFalse(self.lock_path.exists())
        store.mark_executed(RID)
        self.assertTrue(store.is_executed(RID))

    def test_marker_write_failure_still_closes_and_releases(self):
        store = FileExecutedRequestStore(self.state_path)
        with mock.patch("agents.executed_request_store.os.write", side_effect=OSError("disk full")), \
                mock.patch("agents.executed_request_store.os.close", wraps=os.close) as close:
            with self.assertRaises(OSError):
                with store._locked(context="p3.102", write=True):
                    self.fail("the critical section must never be entered")
            close.assert_called_once()
        self.assertFalse(self.lock_path.exists())


if __name__ == "__main__":
    unittest.main()
