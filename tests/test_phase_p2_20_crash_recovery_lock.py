"""
Tests — Phase P2.20 : CRASH RECOVERY & CRITICAL-SECTION LOCK.

Verrouille par des tests le CÂBLAGE réel manquant identifié à la fin
de P2.19/P2.20 : `agents/critical_section_lock.py` et le couple
`mark_unknown()`/`EXECUTION_STATE_UNKNOWN` (agents/executed_request_
store.py, agents/generation_approval_gate.py) existaient déjà, mais
`GenerationJobService.execute()` n'utilisait encore ni l'un ni
l'autre. Ce fichier couvre :

- A : comportement par défaut STRICTEMENT inchangé
      (NoOpCriticalSectionLock implicite).
- B : FileCriticalSectionLock -- verrou déjà détenu pour un
      request_id -> CriticalSectionBusyError, fail-closed, create_job()
      jamais appelé.
- C : le verrou est libéré après une exécution réussie (pas de fichier
      de verrou orphelin dans le cas nominal).
- D : create_job() réussit mais mark_executed() échoue ->
      GenerationJobUnknownStateError + mark_unknown() appelé avec
      succès (le Gate renvoie ensuite EXECUTION_STATE_UNKNOWN).
- E : create_job() réussit, mark_executed() ET mark_unknown() échouent
      tous les deux -> CriticalStateUnknownAndUnrecordedError.
- F : FinalReportService ne capture NI GenerationJobUnknownStateError
      NI CriticalStateUnknownAndUnrecordedError -- ces exceptions se
      propagent, jamais transformées en rapport NOT_EXECUTED.
- G : câblage réel (director.py) -- FileCriticalSectionLock injecté
      dans le GenerationJobService de la chaîne de production réelle.

Toutes les créations de job utilisent exclusivement MockHiggsfield
Provider. Aucun appel réseau, aucun CLI réel, aucun crédit consommé.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.critical_section_lock import (
    CriticalSectionBusyError,
    FileCriticalSectionLock,
    NoOpCriticalSectionLock,
)
from agents.executed_request_store import (
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
    FIXTURE_MAX_COST_CREDITS_PER_REQUEST,
    counting_mock_provider,
    fixture_identity_lock_for,
    install_create_job_probe,
)
from tests.real_provider_path_fixtures import fixture_real_path_gate_kwargs
from tests.authorization_content_helpers import bind_request, content_media
from agents.generation_job_service import (
    CriticalStateUnknownAndUnrecordedError,
    GenerationJobExecutionError,
    GenerationJobService,
    GenerationJobUnknownStateError,
)
from agents.release_candidate_identity_lock import ReleaseCandidateContract, ReleaseCandidateIdentityLock
from director import AIDirector
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider

CONFIRMED_DURATION = 5


def _request(request_id="005", **overrides) -> GenerationRequest:
    defaults = dict(
        **content_media(),
        request_id=request_id,
        job_type="seedance_2_0",
        prompt="Un prompt de test suffisamment explicite.",
        duration=CONFIRMED_DURATION,
        approved=True,
        real_generation_authorization=RealGenerationAuthorization(
            request_id=request_id, authorized_by_human=True
        ),
    )
    defaults.update(overrides)
    return bind_request(GenerationRequest(**defaults))


def _gate(cost_per_job=10.0, available_credits=100.0, store=None):
    provider = MockHiggsfieldProvider(
        cost_per_job=cost_per_job, available_credits=available_credits
    )
    gate = GenerationApprovalGate(
        provider, executed_request_store=store or InMemoryExecutedRequestStore()
    )
    return provider, gate


class _RaisingMarkExecutedGate(GenerationApprovalGate):
    """
    Double de test : `mark_executed()` échoue systématiquement (simule
    une écriture disque qui casse APRÈS un create_job() réel réussi),
    tout en déléguant `mark_unknown()`/`evaluate()` normalement au
    store réel injecté.
    """

    def __init__(self, *args, mark_unknown_fails=False, **kwargs):
        super().__init__(*args, **kwargs)
        self._mark_unknown_fails = mark_unknown_fails

    def mark_executed(self, request_id: str, job_id=None) -> None:
        raise OSError("[test] simulated disk failure during mark_executed()")

    def mark_unknown(self, request_id: str, reason: str = "", job_id=None) -> None:
        if self._mark_unknown_fails:
            raise OSError("[test] simulated disk failure during mark_unknown() too")
        super().mark_unknown(request_id, reason=reason, job_id=job_id)


def _create_job_fails(params):
    raise ConnectionError("[test] simulated create_job() network failure")


def _CreateJobFailsProvider(**kwargs):
    """Double de test : `create_job()` échoue systématiquement (ex.
    coupure réseau/CLI AVANT toute création réelle) -- aucun job n'a
    jamais existé, donc rien à marquer. Phase D : Mock RECONNU ; l'échec
    est levé à l'instant de l'appel par `install_create_job_probe()`."""

    return counting_mock_provider(on_create=_create_job_fails, **kwargs)


class TestA_DefaultBehaviorUnchanged(unittest.TestCase):
    """A -- sans lock explicite, comportement strictement identique à
    avant P2.20 (NoOpCriticalSectionLock implicite)."""

    def test_default_lock_is_noop(self):
        provider, gate = _gate()
        service = GenerationJobService(provider, gate)
        self.assertIsInstance(service.lock, NoOpCriticalSectionLock)

    def test_execute_still_succeeds_without_explicit_lock(self):
        provider, gate = _gate()
        service = GenerationJobService(provider, gate)
        outcome = service.execute(_request(), interval_seconds=0)
        self.assertTrue(outcome.succeeded)
        self.assertEqual(len(provider._jobs), 1)

    def test_noop_lock_never_creates_a_lock_file(self):
        lock = NoOpCriticalSectionLock()
        with lock.acquire("005"):
            pass  # Aucune ressource externe créée -- rien à vérifier sur disque.


class TestB_FileLockBusyFailsClosed(unittest.TestCase):
    """B -- un verrou déjà détenu pour ce request_id refuse
    IMMÉDIATEMENT (pas d'attente), et create_job() n'est jamais
    appelé."""

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_20_lock_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def test_busy_lock_raises_and_blocks_create_job(self):
        provider, gate = _gate()
        lock = FileCriticalSectionLock(self._tmp)
        service = GenerationJobService(provider, gate, lock=lock)

        request = _request()

        with lock.acquire(request.request_id):
            with self.assertRaises(CriticalSectionBusyError):
                service.execute(request, interval_seconds=0)

        self.assertEqual(len(provider._jobs), 0)

    def test_busy_lock_for_one_request_does_not_block_another(self):
        provider, gate = _gate()
        lock = FileCriticalSectionLock(self._tmp)
        service = GenerationJobService(provider, gate, lock=lock)

        with lock.acquire("005"):
            outcome = service.execute(
                _request(request_id="006"), interval_seconds=0
            )
            self.assertTrue(outcome.succeeded)


class TestC_LockReleasedAfterSuccess(unittest.TestCase):
    """C -- cas nominal : le fichier de verrou ne survit pas à une
    exécution réussie."""

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_20_lock_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def test_lock_file_removed_after_successful_execute(self):
        provider, gate = _gate()
        lock = FileCriticalSectionLock(self._tmp)
        service = GenerationJobService(provider, gate, lock=lock)

        service.execute(_request(), interval_seconds=0)

        self.assertFalse((self._tmp / "005.lock").exists())

    def test_lock_reacquirable_for_same_request_after_release(self):
        # Une deuxième acquisition (indépendante de execute()) pour le
        # même request_id doit réussir une fois le verrou libéré --
        # confirme qu'aucun verrou orphelin n'est laissé par le chemin
        # nominal.
        lock = FileCriticalSectionLock(self._tmp)
        with lock.acquire("005"):
            pass
        with lock.acquire("005"):
            pass  # Ne doit pas lever CriticalSectionBusyError.


class TestD_MarkExecutedFailsButMarkUnknownSucceeds(unittest.TestCase):
    """D -- fenêtre de crash P2.20 : create_job() réussit mais
    mark_executed() échoue -> ambiguïté consignée via mark_unknown(),
    GenerationJobUnknownStateError levée, aucun rejeu automatique
    possible ensuite (EXECUTION_STATE_UNKNOWN)."""

    def test_unknown_state_error_raised_and_job_was_really_created(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        store = InMemoryExecutedRequestStore()
        gate = _RaisingMarkExecutedGate(provider, executed_request_store=store)
        service = GenerationJobService(provider, gate)

        request = _request()

        with self.assertRaises(GenerationJobUnknownStateError) as ctx:
            service.execute(request, interval_seconds=0)

        # create_job() a bien eu lieu -- c'est précisément ce qui rend
        # l'état ambigu (pas "rien ne s'est passé").
        self.assertEqual(len(provider._jobs), 1)
        self.assertIsNotNone(ctx.exception.job)
        self.assertEqual(ctx.exception.job.job_id, "mock-job-1")

    def test_mark_unknown_was_actually_recorded(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        store = InMemoryExecutedRequestStore()
        gate = _RaisingMarkExecutedGate(provider, executed_request_store=store)
        service = GenerationJobService(provider, gate)

        request = _request()

        with self.assertRaises(GenerationJobUnknownStateError):
            service.execute(request, interval_seconds=0)

        self.assertTrue(store.is_unknown(request.request_id))

    def test_subsequent_evaluation_is_execution_state_unknown_never_approved(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        store = InMemoryExecutedRequestStore()
        gate = _RaisingMarkExecutedGate(provider, executed_request_store=store)
        service = GenerationJobService(provider, gate)

        request = _request()
        with self.assertRaises(GenerationJobUnknownStateError):
            service.execute(request, interval_seconds=0)

        second_look = gate.evaluate(request)
        self.assertEqual(
            second_look.decision, GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN
        )
        self.assertNotEqual(second_look.decision, GenerationApprovalDecision.APPROVED)


class TestE_BothMarkExecutedAndMarkUnknownFail(unittest.TestCase):
    """E -- pire cas prévu : ni mark_executed() ni mark_unknown()
    n'ont pu consigner quoi que ce soit -> CriticalStateUnknownAndUn
    recordedError, non masquée."""

    def test_critical_state_unknown_and_unrecorded_error_raised(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        store = InMemoryExecutedRequestStore()
        gate = _RaisingMarkExecutedGate(
            provider, executed_request_store=store, mark_unknown_fails=True
        )
        service = GenerationJobService(provider, gate)

        request = _request()

        with self.assertRaises(CriticalStateUnknownAndUnrecordedError):
            service.execute(request, interval_seconds=0)

        # create_job() a quand même eu lieu -- le pire cas ne prétend
        # jamais que rien n'a été tenté.
        self.assertEqual(len(provider._jobs), 1)
        # Ni mark_executed() ni mark_unknown() n'ont pu consigner quoi
        # que ce soit ; depuis P3.91, le marqueur write-ahead écrit
        # AVANT create_job() maintient néanmoins la requête UNKNOWN.
        self.assertTrue(store.is_unknown(request.request_id))
        self.assertFalse(store.is_executed(request.request_id))


class TestF_FinalReportServiceNeverMasksTheseErrors(unittest.TestCase):
    """F -- FinalReportService.generate() ne capture QUE
    GenerationJobExecutionError (décisions normales du Gate) ; les
    erreurs P2.20 se propagent, jamais transformées en rapport
    NOT_EXECUTED qui laisserait croire à un état géré."""

    def test_unknown_state_error_propagates_through_final_report_service(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        store = InMemoryExecutedRequestStore()
        gate = _RaisingMarkExecutedGate(provider, executed_request_store=store)
        job_service = GenerationJobService(provider, gate)
        report_service = FinalReportService(provider, gate, job_service=job_service)

        with self.assertRaises(GenerationJobUnknownStateError):
            report_service.generate(_request(), interval_seconds=0)

    def test_critical_state_unknown_and_unrecorded_error_propagates_too(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        store = InMemoryExecutedRequestStore()
        gate = _RaisingMarkExecutedGate(
            provider, executed_request_store=store, mark_unknown_fails=True
        )
        job_service = GenerationJobService(provider, gate)
        report_service = FinalReportService(provider, gate, job_service=job_service)

        with self.assertRaises(CriticalStateUnknownAndUnrecordedError):
            report_service.generate(_request(), interval_seconds=0)


class TestG_RealProductionWiring(unittest.TestCase):
    """G -- le chemin de production réel (director.py) injecte bien un
    FileCriticalSectionLock, structurellement, sans jamais appeler le
    CLI (construction pure)."""

    def test_default_report_service_uses_a_file_critical_section_lock(self):
        director = AIDirector()
        report_service = director._build_default_report_service()

        self.assertIsInstance(report_service.job_service, GenerationJobService)
        self.assertIsInstance(report_service.job_service.lock, FileCriticalSectionLock)
        self.assertEqual(
            report_service.job_service.lock.lock_dir, director.root / "state" / "locks"
        )

    def test_construction_alone_makes_no_cli_call(self):
        director = AIDirector()
        try:
            director._build_default_report_service()
        except Exception as error:  # pragma: no cover - ne doit jamais arriver
            self.fail(f"Construction should never touch the CLI: {error}")


class TestH_LockReleasedAfterException(unittest.TestCase):
    """H -- Étape 8 (Lock) : le verrou doit être libéré MÊME quand une
    exception est levée à l'intérieur de la section critique -- ici,
    un refus normal du Gate (GenerationJobExecutionError), pas une
    erreur de bas niveau."""

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_20_lock_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def test_lock_file_removed_even_when_gate_refuses(self):
        provider, gate = _gate()
        lock = FileCriticalSectionLock(self._tmp)
        service = GenerationJobService(provider, gate, lock=lock)

        # approved=False -> NEEDS_APPROVAL -> GenerationJobExecutionError
        # levée DANS le bloc `with self.lock.acquire(...)`.
        request = _request(approved=False, real_generation_authorization=None)

        with self.assertRaises(GenerationJobExecutionError):
            service.execute(request, interval_seconds=0)

        self.assertFalse((self._tmp / "005.lock").exists())
        self.assertEqual(len(provider._jobs), 0)

        # Le verrou étant bien libéré, une acquisition indépendante
        # pour ce même request_id doit immédiatement réussir.
        with lock.acquire("005"):
            pass


class TestI_CreateJobFailureLeavesNoMarking(unittest.TestCase):
    """I -- Étape 8 (Crash safety) : `create_job()` échoue -- l'exception
    d'origine se propage sans être maquillée en
    GenerationJobUnknownStateError et mark_executed() n'est jamais
    appelé. P3.91 : une exception ne prouve pas qu'aucun job n'existe
    côté backend (P3.90 C2) -- le marqueur write-ahead laisse donc la
    requête UNKNOWN (fail closed)."""

    def test_create_job_failure_propagates_and_marks_nothing(self):
        provider = _CreateJobFailsProvider(cost_per_job=10.0, available_credits=100.0)
        store = InMemoryExecutedRequestStore()
        # Phase D : Provider instrumenté (non reconnu comme mock) -> fixtures
        # EXPLICITES : plafond + Identity Lock lié au contenu exact.
        gate = GenerationApprovalGate(provider, executed_request_store=store, **fixture_real_path_gate_kwargs(_request()))
        install_create_job_probe(gate, provider)
        service = GenerationJobService(provider, gate)

        request = _request()

        with self.assertRaises(ConnectionError):
            service.execute(request, interval_seconds=0)

        self.assertFalse(store.is_executed(request.request_id))
        self.assertTrue(store.is_unknown(request.request_id))

    def test_create_job_failure_releases_the_real_file_lock(self):
        tmp = Path(tempfile.mkdtemp(prefix="p2_20_lock_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)

        provider = _CreateJobFailsProvider(cost_per_job=10.0, available_credits=100.0)
        # Phase D : Provider instrumenté (non reconnu comme mock) -> fixtures
        # EXPLICITES : plafond + Identity Lock lié au contenu exact.
        gate = GenerationApprovalGate(provider, **fixture_real_path_gate_kwargs(_request()))
        install_create_job_probe(gate, provider)
        lock = FileCriticalSectionLock(tmp)
        service = GenerationJobService(provider, gate, lock=lock)

        with self.assertRaises(ConnectionError):
            service.execute(_request(), interval_seconds=0)

        self.assertFalse((tmp / "005.lock").exists())


class TestJ_NominalSuccessRecordsExecutedNeverUnknown(unittest.TestCase):
    """J -- Étape 8 (Crash safety) : le chemin nominal (create_job() +
    mark_executed() réussissent tous les deux) doit enregistrer
    is_executed()=True et JAMAIS is_unknown()=True."""

    def test_store_reflects_executed_not_unknown(self):
        provider, gate = _gate()
        store = gate.executed_request_store
        service = GenerationJobService(provider, gate)

        request = _request()
        outcome = service.execute(request, interval_seconds=0)

        self.assertTrue(outcome.succeeded)
        self.assertTrue(store.is_executed(request.request_id))
        self.assertFalse(store.is_unknown(request.request_id))


class TestK_ReplayAndCrossProcessPersistence(unittest.TestCase):
    """K -- Étape 4 (Replay safety) : le nouveau verrou reste
    compatible avec FileExecutedRequestStore -- ALREADY_EXECUTED est
    toujours renvoyé après une exécution lock-wrapped réussie, et un
    état UNKNOWN persistant survit à un redémarrage de processus
    (nouvelle instance de Gate/Store pointant vers le même fichier)."""

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_20_replay_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def test_already_executed_still_blocks_second_attempt_under_lock(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        store = FileExecutedRequestStore(self._tmp / "executed_requests.json")
        gate = GenerationApprovalGate(provider, executed_request_store=store)
        lock = FileCriticalSectionLock(self._tmp / "locks")
        service = GenerationJobService(provider, gate, lock=lock)

        request = _request()
        first = service.execute(request, interval_seconds=0)
        self.assertTrue(first.succeeded)

        with self.assertRaises(GenerationJobExecutionError) as ctx:
            service.execute(request, interval_seconds=0)

        self.assertEqual(
            ctx.exception.approval.decision,
            GenerationApprovalDecision.ALREADY_EXECUTED,
        )
        # create_job() n'a été appelé qu'une seule fois -- le replay
        # guard a bloqué AVANT toute seconde création.
        self.assertEqual(len(provider._jobs), 1)

    def test_unknown_state_survives_a_simulated_process_restart(self):
        store_path = self._tmp / "executed_requests.json"
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        store = FileExecutedRequestStore(store_path)
        gate = _RaisingMarkExecutedGate(provider, executed_request_store=store)
        service = GenerationJobService(provider, gate)

        request = _request()
        with self.assertRaises(GenerationJobUnknownStateError):
            service.execute(request, interval_seconds=0)

        # "Redémarrage du processus" simulé : nouvelle instance de
        # Store/Gate, aucun état en mémoire partagé avec ce qui
        # précède -- seul le fichier sur disque relie les deux.
        restarted_store = FileExecutedRequestStore(store_path)
        restarted_gate = GenerationApprovalGate(
            provider, executed_request_store=restarted_store
        )
        result = restarted_gate.evaluate(request)
        self.assertEqual(
            result.decision, GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN
        )
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestL_HumanAuthorizationAndBudgetRegressionUnderLock(unittest.TestCase):
    """L -- Étape 5/8 : le double consentement (approbation technique +
    RealGenerationAuthorization) et le budget restent appliqués
    IDENTIQUEMENT une fois le service enveloppé par un verrou réel --
    aucune régression introduite par P2.20."""

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_20_auth_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self._lock = FileCriticalSectionLock(self._tmp)

    def _service(self, cost_per_job=10.0, available_credits=100.0):
        provider = MockHiggsfieldProvider(
            cost_per_job=cost_per_job, available_credits=available_credits
        )
        gate = GenerationApprovalGate(provider)
        return provider, GenerationJobService(provider, gate, lock=self._lock)

    def test_no_human_authorization_is_rejected(self):
        provider, service = self._service()
        request = _request(real_generation_authorization=None)

        with self.assertRaises(GenerationJobExecutionError):
            service.execute(request, interval_seconds=0)
        self.assertEqual(len(provider._jobs), 0)

    def test_authorization_bound_to_wrong_request_id_is_rejected(self):
        provider, service = self._service()
        request = _request(
            real_generation_authorization=RealGenerationAuthorization(
                request_id="not-005", authorized_by_human=True
            )
        )

        with self.assertRaises(GenerationJobExecutionError):
            service.execute(request, interval_seconds=0)
        self.assertEqual(len(provider._jobs), 0)

    def test_insufficient_budget_is_blocked(self):
        provider, service = self._service(cost_per_job=50.0, available_credits=1.41)
        request = _request()

        with self.assertRaises(GenerationJobExecutionError) as ctx:
            service.execute(request, interval_seconds=0)

        self.assertEqual(
            ctx.exception.approval.decision, GenerationApprovalDecision.BLOCKED
        )
        self.assertEqual(len(provider._jobs), 0)

    def test_identity_lock_violation_is_rejected(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        contract = ReleaseCandidateContract(
            request_id="005",
            job_type="seedance_2_0",
            duration=CONFIRMED_DURATION,
            resolution="720p",
            aspect_ratio="9:16",
            prompt_sha256="0" * 64,  # Ne correspondra jamais au prompt de test.
            prompt_chars=999999,
            prompt_lines=999999,
            avatar_master_sha256="0" * 64,
            face_reference_sha256="0" * 64,
        )
        identity_lock = ReleaseCandidateIdentityLock(contract)
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
        service = GenerationJobService(provider, gate, lock=self._lock)

        request = _request()

        with self.assertRaises(GenerationJobExecutionError) as ctx:
            service.execute(request, interval_seconds=0)

        self.assertEqual(
            ctx.exception.approval.decision,
            GenerationApprovalDecision.INVALID_REQUEST,
        )
        self.assertEqual(len(provider._jobs), 0)


class TestM_RealProviderStaysDisabledWithLock(unittest.TestCase):
    """M -- Étape 7 : même avec un FileCriticalSectionLock réel
    injecté, le HiggsfieldProvider réel reste inconditionnellement
    désactivé -- le verrou ne crée aucune voie de contournement."""

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_20_real_provider_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def test_real_provider_raises_disabled_error_and_releases_the_lock(self):
        from unittest.mock import MagicMock

        fake_client = MagicMock()
        fake_client.estimate_cost.return_value = {"credits": 10.0}
        fake_client.account_status.return_value = {"credits": 1000.0}
        fake_client.get_model.return_value = {
            "job_type": "seedance_2_0",
            "display_name": "d",
            "params": [
                {"name": "prompt", "type": "string", "required": True},
                {"name": "duration", "type": "integer", "required": False, "default": 5},
                {"name": "start_image", "type": "object|null", "required": False},
                {"name": "image_references", "type": "array", "required": False},
            ],
        }

        real_provider = HiggsfieldProvider(client=fake_client)
        request = _request(duration=5)
        # Phase D : fixtures de TEST explicites (plafond + Identity Lock) ;
        # sans elles, la Gate bloque le chemin réel avant create_job().
        gate = GenerationApprovalGate(
            real_provider,
            identity_lock=fixture_identity_lock_for(request),
            max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST,
        )
        lock = FileCriticalSectionLock(self._tmp)
        service = GenerationJobService(real_provider, gate, lock=lock)

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            service.execute(request, interval_seconds=0)

        fake_client.create_job.assert_not_called()
        # Fail-closed du Provider réel ET libération correcte du
        # verrou réel ne s'excluent pas : les deux tiennent ensemble.
        self.assertFalse((self._tmp / "005.lock").exists())


if __name__ == "__main__":
    unittest.main()
