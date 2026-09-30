"""
Tests -- Phase P3.89 : fermeture de GAP #1 (audit P3.88).

GAP #1 (P3.87 limitation 2, reproduit en P3.88) : `mark_executed()` ne
persistait que `request_id` et `executed_at`, jamais le `job_id` renvoyé
par `create_job()`. Un crash pendant `wait_for_job()` (hors verrou,
après `mark_executed()`) laissait un job créé -- et facturé -- sans
aucun lien local job <-> requête ; le rejeu restait bloqué mais le job
devenait introuvable localement. En UNKNOWN, le `job_id` ne survivait
que dans le texte libre `reason`.

Correction P3.89 : `job_id` est persisté comme champ structuré dans LE
MÊME enregistrement anti-rejeu (même écriture atomique), relu par
`recorded_job_id(request_id)`. Ce fichier verrouille : exécution
normale, rejeu, redémarrage, UNKNOWN, crash, concurrence, cross-scope,
et le fait que cette trace ne devient JAMAIS une autorisation.

Uniquement MockHiggsfieldProvider : aucun réseau, aucun CLI, aucun
crédit.
"""

import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.critical_section_lock import CriticalSectionBusyError, FileCriticalSectionLock
from agents.executed_request_store import (
    ExecutedRequestStoreConflictError,
    ExecutedRequestStoreCorruptedError,
    FileExecutedRequestStore,
    InMemoryExecutedRequestStore,
)
from agents.final_report_service import FinalReportService
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from tests.real_provider_path_fixtures import (
    counting_mock_provider,
    fixture_real_path_gate_kwargs,
    install_create_job_probe,
)
from tests.authorization_content_helpers import bind_request, content_media
from agents.generation_job_service import (
    CriticalStateUnknownAndUnrecordedError,
    GenerationJobService,
    GenerationJobUnknownStateError,
)
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.types import Job, JobStatus

D = GenerationApprovalDecision


def _request(request_id="005") -> GenerationRequest:
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


def _CrashDuringPollingProvider(**kwargs):
    """Le job est créé, puis le processus "meurt" pendant le polling.
    Phase D : Mock RECONNU dont seul `wait_for_job` (hors frontière
    `create_job`) est remplacé sur l'instance."""

    provider = MockHiggsfieldProvider(**kwargs)

    def _crash_during_polling(job_id, **_kwargs):
        raise KeyboardInterrupt("[test] simulated crash during wait_for_job()")

    provider.wait_for_job = _crash_during_polling
    return provider


class _FailingMarkExecutedStore(FileExecutedRequestStore):
    def mark_executed(self, request_id, executed_at=None, job_id=None):
        raise OSError("[test] simulated disk failure during mark_executed()")


class _Case(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p389-"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.state_path = self._tmp / "state" / "executed_requests.json"

    def _stack(self, provider=None, store=None, request_ids=None):
        provider = provider or MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        store = store or FileExecutedRequestStore(self.state_path)
        # Phase D : un Provider instrumenté (non reconnu comme mock) exige des
        # fixtures EXPLICITES -- plafond + Identity Lock lié au contenu exact
        # des `request_ids` évalués, fournis par le test lui-même.
        fixtures = (
            fixture_real_path_gate_kwargs(*(_request(request_id) for request_id in request_ids))
            if request_ids is not None
            else {}
        )
        gate = install_create_job_probe(
            GenerationApprovalGate(provider, executed_request_store=store, **fixtures), provider
        )
        job_service = GenerationJobService(
            provider, gate, lock=FileCriticalSectionLock(self._tmp / "locks")
        )
        return provider, store, gate, job_service

    def _restarted_gate(self, provider=None):
        """Nouveau processus : nouveau store et nouveau Gate relus depuis le disque."""
        store = FileExecutedRequestStore(self.state_path)
        provider = provider or MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        return store, GenerationApprovalGate(provider, executed_request_store=store)

    def _state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))


# ----------------------------------------------------------------------
# Normal
# ----------------------------------------------------------------------


class TestNormalExecution(_Case):
    def test_job_id_is_persisted_in_the_replay_record(self):
        provider, store, _, job_service = self._stack()
        outcome = job_service.execute(_request("005"), interval_seconds=0)

        record = self._state()["executed_requests"]["005"]
        self.assertEqual(record["job_id"], outcome.job.job_id)
        self.assertEqual(set(record), {"executed_at", "job_id"})
        self.assertEqual(store.recorded_job_id("005"), outcome.job.job_id)
        self.assertEqual(list(provider._jobs), [outcome.job.job_id])

    def test_in_memory_store_keeps_the_same_identity(self):
        _, store, _, job_service = self._stack(store=InMemoryExecutedRequestStore())
        outcome = job_service.execute(_request("005"), interval_seconds=0)
        self.assertEqual(store.recorded_job_id("005"), outcome.job.job_id)

    def test_final_report_job_id_matches_the_persisted_identity(self):
        provider, store, gate, job_service = self._stack()
        report = FinalReportService(provider, gate, job_service=job_service).generate(
            _request("005"), interval_seconds=0
        )
        self.assertTrue(report.job_created)
        self.assertIsNotNone(report.job_id)
        self.assertEqual(report.request_id, "005")
        self.assertEqual(FileExecutedRequestStore(self.state_path).recorded_job_id("005"), report.job_id)


# ----------------------------------------------------------------------
# GAP #1 itself : crash during polling, then restart
# ----------------------------------------------------------------------


class TestCrashDuringPollingIsRecoverable(_Case):
    def test_created_job_is_findable_after_crash_and_restart(self):
        provider, _, _, job_service = self._stack(
            provider=_CrashDuringPollingProvider(cost_per_job=10.0, available_credits=100.0),
            request_ids=("005",),  # Phase D : fixtures explicites
        )
        with self.assertRaises(KeyboardInterrupt):
            job_service.execute(_request("005"), interval_seconds=0)

        [created_job_id] = list(provider._jobs)
        store, gate = self._restarted_gate()
        self.assertEqual(store.recorded_job_id("005"), created_job_id)
        self.assertEqual(gate.evaluate(_request("005")).decision, D.ALREADY_EXECUTED)
        self.assertFalse((self._tmp / "locks" / "005.lock").exists())

    def test_recovery_reads_the_job_through_the_recorded_identity_only(self):
        provider, _, _, job_service = self._stack(
            provider=_CrashDuringPollingProvider(cost_per_job=10.0, available_credits=100.0),
            request_ids=("005",),  # Phase D : fixtures explicites
        )
        with self.assertRaises(KeyboardInterrupt):
            job_service.execute(_request("005"), interval_seconds=0)
        store, _ = self._restarted_gate()
        # Reprise en lecture seule : get_job() sur l'identité enregistrée,
        # sans aucun nouvel appel à create_job().
        job = MockHiggsfieldProvider.get_job(provider, store.recorded_job_id("005"))
        self.assertEqual(job.job_id, store.recorded_job_id("005"))
        self.assertEqual(len(provider._jobs), 1)


# ----------------------------------------------------------------------
# Replay
# ----------------------------------------------------------------------


class TestReplay(_Case):
    def test_same_request_replay_is_blocked_and_identity_unchanged(self):
        provider, store, _, job_service = self._stack()
        first = job_service.execute(_request("005"), interval_seconds=0)
        report = FinalReportService(provider, job_service.gate, job_service=job_service).generate(
            _request("005"), interval_seconds=0
        )
        self.assertFalse(report.job_created)
        self.assertEqual(report.approval_decision, D.ALREADY_EXECUTED)
        self.assertEqual(len(provider._jobs), 1)
        self.assertEqual(store.recorded_job_id("005"), first.job.job_id)

    def test_replay_after_restart_is_blocked_and_identity_survives(self):
        provider, _, _, job_service = self._stack()
        first = job_service.execute(_request("005"), interval_seconds=0)

        new_provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        _, _, _, restarted_service = self._stack(provider=new_provider)
        report = FinalReportService(new_provider, restarted_service.gate, job_service=restarted_service).generate(
            _request("005"), interval_seconds=0
        )
        self.assertEqual(report.approval_decision, D.ALREADY_EXECUTED)
        self.assertEqual(new_provider._jobs, {})
        self.assertEqual(FileExecutedRequestStore(self.state_path).recorded_job_id("005"), first.job.job_id)

    def test_new_request_follows_existing_rules_and_gets_its_own_identity(self):
        _, store, _, job_service = self._stack()
        a = job_service.execute(_request("005"), interval_seconds=0)
        b = job_service.execute(_request("006"), interval_seconds=0)
        self.assertNotEqual(a.job.job_id, b.job.job_id)
        self.assertEqual(store.recorded_job_id("005"), a.job.job_id)
        self.assertEqual(store.recorded_job_id("006"), b.job.job_id)


# ----------------------------------------------------------------------
# UNKNOWN / crash before-after persistence
# ----------------------------------------------------------------------


class TestUnknownAndCrash(_Case):
    def test_unknown_state_keeps_a_structured_job_id(self):
        provider, _, _, job_service = self._stack(store=_FailingMarkExecutedStore(self.state_path))
        with self.assertRaises(GenerationJobUnknownStateError) as ctx:
            job_service.execute(_request("005"), interval_seconds=0)

        record = self._state()["unknown_requests"]["005"]
        self.assertEqual(record["job_id"], ctx.exception.job.job_id)
        store, gate = self._restarted_gate()
        self.assertEqual(store.recorded_job_id("005"), ctx.exception.job.job_id)
        self.assertEqual(gate.evaluate(_request("005")).decision, D.EXECUTION_STATE_UNKNOWN)
        self.assertEqual(len(provider._jobs), 1)

    def test_malformed_provider_job_id_never_prevents_the_unknown_record(self):
        # Phase D : un Provider qui redéfinit create_job() n'atteint plus la
        # frontière ; le Mock reconnu crée donc le job, et c'est la RÉPONSE
        # qu'il renvoie (le `Job` construit par son module) qui porte un
        # identifiant vide, pendant ce seul appel.
        from integrations.higgsfield import mock_provider as mock_provider_module

        def _empty_id_job(**job_fields):
            return Job(**{**job_fields, "job_id": ""})

        provider, _, _, job_service = self._stack(
            provider=MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0),
            request_ids=("005",),  # Phase D : fixtures explicites
        )
        with self.assertRaises(GenerationJobUnknownStateError):
            with mock.patch.object(mock_provider_module, "Job", _empty_id_job):
                job_service.execute(_request("005"), interval_seconds=0)
        self.assertEqual(len(provider._jobs), 1)  # le job a bien été créé
        store, gate = self._restarted_gate()
        self.assertNotIn("job_id", self._state()["unknown_requests"]["005"])
        self.assertIsNone(store.recorded_job_id("005"))
        self.assertEqual(gate.evaluate(_request("005")).decision, D.EXECUTION_STATE_UNKNOWN)

    def test_create_job_failure_records_no_job_id_and_stays_unknown(self):
        # P3.91 : une exception de create_job() ne prouve pas l'absence
        # de job côté backend (P3.90 C2) -- le write-ahead reste UNKNOWN,
        # sans job_id inventé.
        # Phase D : échec à l'instant de l'appel, porté par la sonde
        # `gate.in_flight()` (le Mock reconnu n'est jamais redéfini).
        def _create_fails(params):
            raise ConnectionError("[test] failure before any job exists")

        provider, store, gate, job_service = self._stack(
            provider=counting_mock_provider(on_create=_create_fails, cost_per_job=10.0, available_credits=100.0),
            request_ids=("005",),  # Phase D : fixtures explicites
        )
        with self.assertRaises(ConnectionError):
            job_service.execute(_request("005"), interval_seconds=0)
        self.assertIsNone(store.recorded_job_id("005"))
        self.assertEqual(gate.evaluate(_request("005")).decision, D.EXECUTION_STATE_UNKNOWN)
        self.assertEqual(provider._jobs, {})  # aucun job n'existe

    def test_double_persistence_failure_still_raises_critical_error(self):
        class _BothFail(_FailingMarkExecutedStore):
            def mark_unknown(self, request_id, reason="", marked_at=None, job_id=None):
                raise OSError("[test] mark_unknown fails too")

        _, _, _, job_service = self._stack(store=_BothFail(self.state_path))
        with self.assertRaises(CriticalStateUnknownAndUnrecordedError):
            job_service.execute(_request("005"), interval_seconds=0)

    def test_legacy_record_without_job_id_stays_blocking(self):
        self.state_path.parent.mkdir(parents=True)
        self.state_path.write_text(json.dumps(
            {"executed_requests": {"005": {"executed_at": "2026-01-01T00:00:00+00:00"}}}
        ), encoding="utf-8")
        store, gate = self._restarted_gate()
        self.assertIsNone(store.recorded_job_id("005"))
        self.assertEqual(gate.evaluate(_request("005")).decision, D.ALREADY_EXECUTED)

    def test_malformed_job_id_on_disk_is_corruption_but_replay_stays_blocked(self):
        self.state_path.parent.mkdir(parents=True)
        self.state_path.write_text(json.dumps(
            {"executed_requests": {"005": {"executed_at": "x", "job_id": 42}}}
        ), encoding="utf-8")
        store, gate = self._restarted_gate()
        with self.assertRaises(ExecutedRequestStoreCorruptedError):
            store.recorded_job_id("005")
        self.assertEqual(gate.evaluate(_request("005")).decision, D.ALREADY_EXECUTED)


# ----------------------------------------------------------------------
# Cross-scope
# ----------------------------------------------------------------------


class TestCrossScope(_Case):
    def test_request_a_identity_is_never_visible_under_request_b(self):
        _, store, _, job_service = self._stack()
        a = job_service.execute(_request("005"), interval_seconds=0)
        self.assertEqual(store.recorded_job_id("005"), a.job.job_id)
        self.assertIsNone(store.recorded_job_id("006"))

    def test_foreign_identity_for_request_a_is_rejected_without_overwrite(self):
        for store in (FileExecutedRequestStore(self.state_path), InMemoryExecutedRequestStore()):
            with self.subTest(store=type(store).__name__):
                store.mark_executed("005", job_id="job-A")
                with self.assertRaises(ExecutedRequestStoreConflictError):
                    store.mark_executed("005", job_id="job-B")
                store.mark_executed("005")  # sans identité : conserve l'existante
                self.assertEqual(store.recorded_job_id("005"), "job-A")

    def test_foreign_identity_in_unknown_registry_is_rejected(self):
        store = FileExecutedRequestStore(self.state_path)
        store.mark_unknown("005", reason="r", job_id="job-A")
        with self.assertRaises(ExecutedRequestStoreConflictError):
            store.mark_unknown("005", reason="r", job_id="job-B")
        self.assertEqual(store.recorded_job_id("005"), "job-A")

    def test_result_of_a_is_not_attributable_to_request_b(self):
        provider, store, gate, job_service = self._stack()
        service = FinalReportService(provider, gate, job_service=job_service)
        report_a = service.generate(_request("005"), interval_seconds=0)
        report_b = service.generate(_request("006"), interval_seconds=0)
        self.assertEqual(store.recorded_job_id("005"), report_a.job_id)
        self.assertEqual(store.recorded_job_id("006"), report_b.job_id)
        self.assertNotEqual(report_a.job_id, report_b.job_id)

    def test_mission_b_cannot_reuse_the_execution_state_of_mission_a(self):
        provider, store, gate, job_service = self._stack()
        service = FinalReportService(provider, gate, job_service=job_service)
        report_a = service.generate(_request("005"), interval_seconds=0, mission_id="mission-A")
        report_b = service.generate(_request("005"), interval_seconds=0, mission_id="mission-B")
        self.assertTrue(report_a.job_created)
        self.assertFalse(report_b.job_created)
        self.assertIsNone(report_b.job_id)
        self.assertEqual(report_b.approval_decision, D.ALREADY_EXECUTED)
        self.assertEqual(report_b.mission_id, "mission-B")
        self.assertEqual(len(provider._jobs), 1)
        self.assertEqual(store.recorded_job_id("005"), report_a.job_id)


# ----------------------------------------------------------------------
# Concurrency
# ----------------------------------------------------------------------


class TestConcurrency(_Case):
    def test_concurrent_executions_of_one_request_create_and_record_one_job(self):
        # Phase D : attente à l'instant de l'appel, portée par la sonde
        # `gate.in_flight()` (le Mock reconnu n'est jamais redéfini).
        barrier_passed = threading.Event()
        provider, store, _, job_service = self._stack(
            provider=counting_mock_provider(
                on_create=lambda params: barrier_passed.wait(timeout=5),
                cost_per_job=10.0, available_credits=100.0,
            ),
            request_ids=("005",),  # Phase D : fixtures explicites
        )
        results = []

        def run():
            try:
                results.append(job_service.execute(_request("005"), interval_seconds=0))
            except Exception as error:  # noqa: BLE001 -- collected for assertions
                results.append(error)

        threads = [threading.Thread(target=run) for _ in range(4)]
        for t in threads:
            t.start()
        while sum(isinstance(r, CriticalSectionBusyError) for r in results) < 3:
            if all(not t.is_alive() for t in threads):
                break
        barrier_passed.set()
        for t in threads:
            t.join(timeout=10)

        outcomes = [r for r in results if not isinstance(r, Exception)]
        self.assertEqual(len(outcomes), 1, results)
        self.assertTrue(all(isinstance(r, CriticalSectionBusyError) for r in results if r not in outcomes))
        self.assertEqual(list(provider._jobs), [outcomes[0].job.job_id])
        self.assertEqual(store.recorded_job_id("005"), outcomes[0].job.job_id)


# ----------------------------------------------------------------------
# Negative capability : a trace never becomes an authorization
# ----------------------------------------------------------------------


class TestTraceIsNeverAuthority(_Case):
    def test_gate_evaluate_never_reads_the_recorded_identity(self):
        _, store, gate, job_service = self._stack()
        job_service.execute(_request("005"), interval_seconds=0)
        with mock.patch.object(type(store), "recorded_job_id", side_effect=AssertionError("read by evaluate")):
            self.assertEqual(gate.evaluate(_request("005")).decision, D.ALREADY_EXECUTED)
            self.assertEqual(gate.evaluate(_request("006")).decision, D.APPROVED)

    def test_a_job_id_never_marks_another_request_as_executed(self):
        store = FileExecutedRequestStore(self.state_path)
        store.mark_executed("005", job_id="006")
        _, gate = self._restarted_gate()
        self.assertEqual(gate.evaluate(_request("006")).decision, D.APPROVED)

    def test_knowing_a_recorded_job_id_does_not_unblock_or_approve(self):
        _, store, gate, job_service = self._stack()
        outcome = job_service.execute(_request("005"), interval_seconds=0)
        job_id = store.recorded_job_id("005")
        self.assertEqual(job_id, outcome.job.job_id)
        # Aucune API n'accepte un job_id comme preuve d'autorisation.
        self.assertFalse(hasattr(RealGenerationAuthorization(request_id="005", authorized_by_human=True), "job_id"))
        self.assertEqual(gate.evaluate(_request("005")).decision, D.ALREADY_EXECUTED)

    def test_approval_without_human_authorization_is_unchanged_by_any_trace(self):
        store = FileExecutedRequestStore(self.state_path)
        store.mark_unknown("007", reason="r", job_id="job-X")
        _, gate = self._restarted_gate()
        unauthorized = GenerationRequest(
            request_id="008", job_type="seedance_2_0",
            prompt="Un prompt de test suffisamment explicite.", duration=5, approved=True,
        )
        self.assertEqual(gate.evaluate(unauthorized).decision, D.NEEDS_APPROVAL)
        self.assertEqual(gate.evaluate(_request("007")).decision, D.EXECUTION_STATE_UNKNOWN)

    def test_persisted_record_contains_no_authorization_material(self):
        _, _, _, job_service = self._stack()
        job_service.execute(_request("005"), interval_seconds=0)
        text = self.state_path.read_text(encoding="utf-8")
        for forbidden in ("authorization", "authorized_by_human", "prompt", "approved"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
