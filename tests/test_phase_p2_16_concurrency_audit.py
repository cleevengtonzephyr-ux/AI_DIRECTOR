"""
Tests — Phase P2.16 : CONCURRENCY & ATOMIC ACTIVATION SAFETY AUDIT.

Contient :
- Objectif 4 : un test expérimental RÉEL (deux processus OS distincts
  via subprocess, synchronisés par un fichier barrière) qui mesure
  empiriquement si `FileExecutedRequestStore` laisse passer une
  fenêtre TOCTOU entre `is_executed()` et `mark_executed()`. Ce n'est
  pas une simulation : deux vrais processus Python séparés lisent le
  même fichier d'état.
- Objectif 10 : la matrice de tests de sécurité A-L (non-régression
  P2.15, réexécutée ici pour confirmer qu'aucune correction
  éventuelle de P2.16 ne les a affaiblis).
- Objectif 4, suite (Phase G2) : la même course, sous la réservation
  atomique `execution_claims.claim()`, avec quatre vrais processus --
  au niveau du store, puis par `GenerationJobService.execute()`. Le
  détenteur garde la réservation jusqu'à ce que tous les autres aient
  été refusés : exactement un gagnant, quel que soit l'ordonnancement.

Tous les fichiers utilisés sont dans des répertoires temporaires.
Aucun test n'appelle create_job() sur un provider réel, aucun appel
réseau Higgsfield, aucun crédit consommé.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.executed_request_store import (
    ExecutedRequestStoreCorruptedError,
    ExecutionClaimBusyError,
    FileExecutedRequestStore,
)
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
from tests.authorization_content_helpers import bind_request, content_media
from agents.generation_job_service import GenerationJobService
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider


def _request(**overrides) -> GenerationRequest:
    defaults = dict(
        **content_media(),
        request_id="005",
        job_type="seedance_2_0",
        prompt="prompt de test",
        duration=5,
        resolution="720p",
        aspect_ratio="9:16",
        approved=True,
    )
    defaults.update(overrides)
    return bind_request(GenerationRequest(**defaults))


def _valid_auth(request_id="005") -> RealGenerationAuthorization:
    return RealGenerationAuthorization(request_id=request_id, authorized_by_human=True)


# ---------------------------------------------------------------------
# OBJECTIF 4 — Test de concurrence RÉEL (deux vrais processus OS)
# ---------------------------------------------------------------------

_CHILD_SCRIPT = """
import sys, time, json
sys.path.insert(0, {project_root!r})
from agents.executed_request_store import FileExecutedRequestStore

store = FileExecutedRequestStore({state_path!r})
go_file = {go_file!r}
out_file = {out_file!r}

# Attente active (polling serré) jusqu'au signal de depart commun.
while not __import__("os").path.exists(go_file):
    pass

t_read = time.perf_counter()
was_executed = store.is_executed("005")
t_after_read = time.perf_counter()

store.mark_executed("005")
t_after_write = time.perf_counter()

with open(out_file, "w", encoding="utf-8") as f:
    json.dump({{
        "was_executed_at_read_time": was_executed,
        "t_read": t_read,
        "t_after_read": t_after_read,
        "t_after_write": t_after_write,
    }}, f)
"""


class TestObjective4_RealTwoProcessConcurrencyExperiment(unittest.TestCase):
    """
    Lance deux VRAIS processus Python (subprocess), synchronisés par
    un fichier barrière, ciblant le MÊME fichier d'état temporaire.
    Mesure si les deux ont pu lire "non exécuté" avant que l'un des
    deux n'écrive mark_executed().
    """

    def test_two_real_processes_can_both_observe_not_executed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            state_path = tmp_path / "state" / "executed_requests.json"
            go_file = str(tmp_path / "go.signal")
            out_a = str(tmp_path / "out_a.json")
            out_b = str(tmp_path / "out_b.json")

            script = _CHILD_SCRIPT.format(
                project_root=str(PROJECT_ROOT),
                state_path=str(state_path),
                go_file=go_file,
                out_file=out_a,
            )
            script_b = script.replace(out_a, out_b)

            script_path_a = tmp_path / "child_a.py"
            script_path_b = tmp_path / "child_b.py"
            script_path_a.write_text(script, encoding="utf-8")
            script_path_b.write_text(
                _CHILD_SCRIPT.format(
                    project_root=str(PROJECT_ROOT),
                    state_path=str(state_path),
                    go_file=go_file,
                    out_file=out_b,
                ),
                encoding="utf-8",
            )

            proc_a = subprocess.Popen([sys.executable, str(script_path_a)])
            proc_b = subprocess.Popen([sys.executable, str(script_path_b)])

            # Laisse les deux processus entrer dans leur boucle de
            # polling avant de lâcher le signal de départ commun.
            time.sleep(0.3)
            Path(go_file).write_text("go", encoding="utf-8")

            return_a = proc_a.wait(timeout=30)
            return_b = proc_b.wait(timeout=30)

            self.assertEqual(return_a, 0, "Le processus A a échoué (voir stderr manuel si besoin).")
            self.assertEqual(return_b, 0, "Le processus B a échoué (voir stderr manuel si besoin).")

            result_a = json.loads(Path(out_a).read_text(encoding="utf-8"))
            result_b = json.loads(Path(out_b).read_text(encoding="utf-8"))

            both_saw_not_executed = (
                result_a["was_executed_at_read_time"] is False
                and result_b["was_executed_at_read_time"] is False
            )

            # Rapporté tel quel, jamais fabriqué : ce résultat prouve
            # (ou infirme) empiriquement l'existence de la fenêtre
            # TOCTOU sur CETTE machine, à cet instant.
            print(
                f"\n[P2.16 Objectif 4] A saw not-executed={result_a['was_executed_at_read_time']} "
                f"| B saw not-executed={result_b['was_executed_at_read_time']} "
                f"| both saw not-executed simultaneously={both_saw_not_executed}"
            )

            # Le store final ne doit contenir qu'UNE seule exécution
            # enregistrée pour "005" (les deux mark_executed() finissent
            # par écrire, la dernière écriture gagne) -- mais le POINT
            # est que les deux ont pu passer la vérification READ avant
            # que l'un des deux n'écrive.
            self.assertTrue(state_path.exists())
            final_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertIn("005", final_state["executed_requests"])

            # Ce test documente le comportement RÉEL, sans jamais le
            # transformer artificiellement en succès : si le store
            # actuel (sans verrou) est utilisé, les deux processus
            # PEUVENT observer "non exécuté" au même instant.
            self.result_both_saw_not_executed = both_saw_not_executed


# ---------------------------------------------------------------------
# OBJECTIF 4, SUITE (Phase G2) — même course, sous la réservation
# atomique : UN SEUL gagnant, déterministe
# ---------------------------------------------------------------------

WORKER_FLAG = "--p2-16-claim-worker"
CLAIM_PROCESS_COUNT = 4
_PROVIDER_READS = ("list_models", "get_model", "estimate_cost", "get_account_balance", "get_job", "wait_for_job")


def _wait_for_go(sandbox: Path, wid: str) -> None:
    (sandbox / f"ready-{wid}").write_text("1", encoding="utf-8")
    while not (sandbox / "go").exists():
        time.sleep(0.001)


def _hold_until_others_refused(sandbox: Path, count: int) -> None:
    """Le détenteur garde la réservation tant que les `count - 1` autres
    processus n'ont pas tous été refusés : l'issue ne dépend d'aucun
    ordonnancement."""

    deadline = time.monotonic() + 120
    while len(list(sandbox.glob("refused-*"))) < count - 1:
        if time.monotonic() > deadline:
            raise AssertionError("the other processes never reported their refusal")
        time.sleep(0.005)


def _claim_worker(mode, sandbox, wid, count):
    sandbox, count = Path(sandbox), int(count)
    state_path = sandbox / "state" / "executed_requests.json"

    if mode == "store":
        # L'expérience de l'Objectif 4, sous la réservation.
        store = FileExecutedRequestStore(state_path)
        _wait_for_go(sandbox, wid)
        try:
            with store.execution_claims.claim("005"):
                was_executed = store.is_executed("005")
                _hold_until_others_refused(sandbox, count)
                if not was_executed:
                    store.mark_executed("005", job_id=f"job-{wid}")
            print(json.dumps({"result": "CLAIMED", "was_executed_at_read_time": was_executed}))
        except ExecutionClaimBusyError:
            (sandbox / f"refused-{wid}").write_text("1", encoding="utf-8")
            print(json.dumps({"result": "ExecutionClaimBusyError"}))
        return

    # mode == "execute" : parcours de décision complet, verrou de section
    # critique par défaut (NoOp) -- la réservation est la seule exclusion.
    provider = counting_mock_provider(cost_per_job=10.0, available_credits=100.0, succeed_after_polls=1)
    provider_calls = []
    for name in _PROVIDER_READS:
        original = getattr(provider, name)

        def observed(*args, _name=name, _original=original, **kwargs):
            provider_calls.append(_name)
            if len(provider_calls) == 1:
                # Premier appel Provider : seul le détenteur y parvient.
                _hold_until_others_refused(sandbox, count)
            return _original(*args, **kwargs)

        # Mock toujours reconnu : seul `create_job` ne doit pas être remplacé.
        setattr(provider, name, observed)
    gate = install_create_job_probe(
        GenerationApprovalGate(provider, executed_request_store=FileExecutedRequestStore(state_path)),
        provider,
    )
    service = GenerationJobService(provider, gate)
    _wait_for_go(sandbox, wid)
    try:
        service.execute(_request(real_generation_authorization=_valid_auth()), interval_seconds=0)
        result = "EXECUTED"
    except BaseException as error:  # noqa: B902 -- rapporté au processus parent
        result = type(error).__name__
        if isinstance(error, ExecutionClaimBusyError):
            (sandbox / f"refused-{wid}").write_text("1", encoding="utf-8")
    print(json.dumps({"result": result, "provider_calls": provider_calls, "create_calls": provider.create_calls}))


class TestObjective4G2_AtomicClaimHasExactlyOneWinner(unittest.TestCase):
    """
    Quatre VRAIS processus (subprocess), libérés ensemble par un fichier
    barrière, visent la même requête "005" dans le même dossier d'état.
    Le détenteur de la réservation ne la rend qu'après le refus de tous
    les autres : un second gagnant est donc impossible par construction,
    et non simplement improbable.
    """

    def setUp(self):
        self.sandbox = Path(tempfile.mkdtemp(prefix="p2_16_claim_"))
        self.addCleanup(shutil.rmtree, self.sandbox, ignore_errors=True)
        self.state_path = self.sandbox / "state" / "executed_requests.json"

    def _race(self, mode):
        procs = [
            subprocess.Popen(
                [sys.executable, "-B", __file__, WORKER_FLAG, mode, str(self.sandbox), str(i), str(CLAIM_PROCESS_COUNT)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            for i in range(CLAIM_PROCESS_COUNT)
        ]
        try:
            deadline = time.monotonic() + 120
            while len(list(self.sandbox.glob("ready-*"))) < CLAIM_PROCESS_COUNT:
                self.assertLess(time.monotonic(), deadline, "workers never reached the start barrier")
                time.sleep(0.01)
            (self.sandbox / "go").write_text("go", encoding="utf-8")
            results = []
            for proc in procs:
                out, err = proc.communicate(timeout=240)
                lines = [line for line in out.splitlines() if line.startswith("{")]
                self.assertTrue(lines, err[-800:])
                results.append(json.loads(lines[-1]))
            return results
        finally:
            for proc in procs:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()

    def _assert_no_claim_left(self):
        self.assertEqual(list(self.state_path.parent.glob("*.execution-claim")), [])

    def test_only_one_process_obtains_the_claim_and_observes_not_executed(self):
        results = self._race("store")
        winners = [r for r in results if r["result"] == "CLAIMED"]
        self.assertEqual(len(winners), 1, results)
        self.assertIs(winners[0]["was_executed_at_read_time"], False)
        self.assertEqual(
            [r["result"] for r in results].count("ExecutionClaimBusyError"), CLAIM_PROCESS_COUNT - 1, results
        )
        final_state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(list(final_state["executed_requests"]), ["005"])
        self._assert_no_claim_left()

    def test_decision_path_has_one_winner_and_refused_processes_never_reach_the_provider(self):
        results = self._race("execute")
        outcomes = [r["result"] for r in results]
        self.assertEqual(outcomes.count("EXECUTED"), 1, results)
        self.assertEqual(outcomes.count("ExecutionClaimBusyError"), CLAIM_PROCESS_COUNT - 1, results)
        for r in results:
            if r["result"] == "EXECUTED":
                self.assertEqual(r["create_calls"], 1, r)
            else:
                self.assertEqual(r["provider_calls"], [], f"a refused process reached the provider: {r}")
                self.assertEqual(r["create_calls"], 0, r)

        store = FileExecutedRequestStore(self.state_path)
        self.assertTrue(store.is_executed("005"))
        self.assertFalse(store.is_unknown("005"))
        consumed = json.loads((self.state_path.parent / "consumed_authorizations.json").read_text(encoding="utf-8"))
        self.assertEqual(len(consumed["consumed_authorization_sha256"]), 1, "only the winner consumes")
        self._assert_no_claim_left()


# ---------------------------------------------------------------------
# OBJECTIF 10 — Matrice de sécurité A-L (non-régression P2.15)
# ---------------------------------------------------------------------

class _FilePersistenceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.state_path = Path(self._tmpdir.name) / "state" / "executed_requests.json"

    def _new_gate(self, provider=None, **gate_kwargs) -> GenerationApprovalGate:
        provider = provider or MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        store = FileExecutedRequestStore(self.state_path)
        return GenerationApprovalGate(provider, executed_request_store=store, **gate_kwargs)


class TestA_NotExecuted(_FilePersistenceTestCase):
    def test_normal_behavior(self):
        gate = self._new_gate()
        result = gate.evaluate(_request(real_generation_authorization=_valid_auth()))
        self.assertEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestB_MarkedExecuted(_FilePersistenceTestCase):
    def test_already_executed(self):
        gate = self._new_gate()
        gate.mark_executed("005")
        result = gate.evaluate(_request(real_generation_authorization=_valid_auth()))
        self.assertEqual(result.decision, GenerationApprovalDecision.ALREADY_EXECUTED)


class TestC_NewGateAfterPersistence(_FilePersistenceTestCase):
    def test_survives_new_instance(self):
        self._new_gate().mark_executed("005")
        result = self._new_gate().evaluate(_request(real_generation_authorization=_valid_auth()))
        self.assertEqual(result.decision, GenerationApprovalDecision.ALREADY_EXECUTED)


class TestD_UnrelatedRequestId(_FilePersistenceTestCase):
    def test_006_not_blocked_by_005(self):
        gate = self._new_gate()
        gate.mark_executed("005")
        result = gate.evaluate(
            _request(request_id="006", real_generation_authorization=_valid_auth("006"))
        )
        self.assertEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestE_CorruptedState(_FilePersistenceTestCase):
    def test_blocked_on_corruption(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text("{not valid json", encoding="utf-8")
        gate = self._new_gate()
        result = gate.evaluate(_request(real_generation_authorization=_valid_auth()))
        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)


class TestF_NoAuthorization(_FilePersistenceTestCase):
    def test_no_approval_without_authorization(self):
        gate = self._new_gate()
        result = gate.evaluate(_request(real_generation_authorization=None))
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestG_InsufficientBudget(_FilePersistenceTestCase):
    def test_blocked(self):
        provider = MockHiggsfieldProvider(cost_per_job=50.0, available_credits=1.41)
        gate = self._new_gate(provider=provider)
        result = gate.evaluate(_request(real_generation_authorization=_valid_auth()))
        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)


class TestH_ValidAuthorizationSufficientBudget(_FilePersistenceTestCase):
    def test_approved_mock_only(self):
        gate = self._new_gate()
        result = gate.evaluate(_request(real_generation_authorization=_valid_auth()))
        self.assertEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestI_ReplayAfterNewInstance(_FilePersistenceTestCase):
    def test_replay_after_restart_blocked(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0, succeed_after_polls=1)
        gate1 = self._new_gate(provider=provider)
        service1 = GenerationJobService(provider, gate1)
        service1.execute(_request(real_generation_authorization=_valid_auth()), interval_seconds=0)

        gate2 = self._new_gate(provider=provider)
        result = gate2.evaluate(_request(real_generation_authorization=_valid_auth()))
        self.assertEqual(result.decision, GenerationApprovalDecision.ALREADY_EXECUTED)


class TestJ_RealProviderDisabled(_FilePersistenceTestCase):
    def test_real_create_job_disabled(self):
        fake_client = MagicMock()
        fake_client.estimate_cost.return_value = {"credits": 10.0}
        fake_client.account_status.return_value = {"credits": 100.0}
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
        request = _request(real_generation_authorization=_valid_auth())
        # Phase D : fixtures de TEST explicites (plafond + Identity Lock) ;
        # sans elles, la Gate bloque le chemin réel avant create_job().
        gate = self._new_gate(
            provider=real_provider,
            identity_lock=fixture_identity_lock_for(request),
            max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST,
        )
        service = GenerationJobService(real_provider, gate)

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            service.execute(request)
        fake_client.create_job.assert_not_called()


class TestKL_NoRealJobNoCreditsAcrossThisModule(unittest.TestCase):
    """K/L — vérification structurelle : ce module n'importe pas de dépendance réseau/CLI réelle."""

    def test_module_has_no_cli_or_network_dependency(self):
        import inspect

        import tests.test_phase_p2_16_concurrency_audit as module

        imported_names = {
            name
            for name, value in vars(module).items()
            if inspect.ismodule(value) or inspect.isclass(value)
        }
        self.assertNotIn("HiggsfieldClient", imported_names)
        self.assertFalse(hasattr(module, "requests"))
        self.assertFalse(hasattr(module, "socket"))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == WORKER_FLAG:
        _claim_worker(*sys.argv[2:])
    else:
        unittest.main()
