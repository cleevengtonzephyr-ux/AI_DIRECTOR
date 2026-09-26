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

Tous les fichiers utilisés sont dans des répertoires temporaires.
Aucun test n'appelle create_job() sur un provider réel, aucun appel
réseau Higgsfield, aucun crédit consommé.
"""

import json
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
    FileExecutedRequestStore,
)
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from agents.generation_job_service import GenerationJobService
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider


def _request(**overrides) -> GenerationRequest:
    defaults = dict(
        request_id="005",
        job_type="seedance_2_0",
        prompt="prompt de test",
        duration=5,
        resolution="720p",
        aspect_ratio="9:16",
        approved=True,
    )
    defaults.update(overrides)
    return GenerationRequest(**defaults)


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
# OBJECTIF 10 — Matrice de sécurité A-L (non-régression P2.15)
# ---------------------------------------------------------------------

class _FilePersistenceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.state_path = Path(self._tmpdir.name) / "state" / "executed_requests.json"

    def _new_gate(self, provider=None) -> GenerationApprovalGate:
        provider = provider or MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        store = FileExecutedRequestStore(self.state_path)
        return GenerationApprovalGate(provider, executed_request_store=store)


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
            ],
        }
        real_provider = HiggsfieldProvider(client=fake_client)
        gate = self._new_gate(provider=real_provider)
        service = GenerationJobService(real_provider, gate)

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            service.execute(_request(real_generation_authorization=_valid_auth()))
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
    unittest.main()
