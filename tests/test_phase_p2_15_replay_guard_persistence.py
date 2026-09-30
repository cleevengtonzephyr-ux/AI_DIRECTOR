"""
Tests — Phase P2.15 : REPLAY GUARD PERSISTENCE & ACTIVATION SAFETY.

Verrouille le comportement de `FileExecutedRequestStore`
(agents/executed_request_store.py) et son intégration dans
`GenerationApprovalGate` : un `request_id` marqué exécuté doit le
rester après un "redémarrage" (simulé ici par la construction d'un
NOUVEAU `GenerationApprovalGate` pointant vers le même fichier), sans
jamais dépendre d'un cache mémoire.

Tous les fichiers utilisés sont créés dans un répertoire temporaire
(tempfile.TemporaryDirectory), jamais dans le projet réel. Aucun test
n'appelle create_job() sur un provider réel ni ne consomme de crédit.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.executed_request_store import (
    ExecutedRequestStoreCorruptedError,
    FileExecutedRequestStore,
    InMemoryExecutedRequestStore,
)
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from tests.real_provider_path_fixtures import FIXTURE_MAX_COST_CREDITS_PER_REQUEST, fixture_identity_lock_for
from tests.authorization_content_helpers import bind_request, content_media
from agents.generation_job_service import GenerationJobExecutionError, GenerationJobService
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


class _FilePersistenceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.state_path = Path(self._tmpdir.name) / "state" / "executed_requests.json"

    def _new_gate(self, provider=None, **gate_kwargs) -> GenerationApprovalGate:
        provider = provider or MockHiggsfieldProvider(
            cost_per_job=10.0, available_credits=100.0
        )
        store = FileExecutedRequestStore(self.state_path)
        return GenerationApprovalGate(provider, executed_request_store=store, **gate_kwargs)


class TestA_FreshRequestNotYetExecuted(_FilePersistenceTestCase):
    """Test A — nouvelle requête 005, pas encore exécutée -> comportement normal."""

    def test_new_request_is_not_already_executed(self):
        gate = self._new_gate()

        result = gate.evaluate(_request(real_generation_authorization=_valid_auth()))

        self.assertEqual(result.decision, GenerationApprovalDecision.APPROVED)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.ALREADY_EXECUTED)


class TestB_MarkedExecutedYieldsAlreadyExecuted(_FilePersistenceTestCase):
    """Test B — marquer 005 exécutée -> nouvelle évaluation -> ALREADY_EXECUTED."""

    def test_marked_executed_is_reported(self):
        gate = self._new_gate()
        gate.mark_executed("005")

        result = gate.evaluate(_request(real_generation_authorization=_valid_auth()))

        self.assertEqual(result.decision, GenerationApprovalDecision.ALREADY_EXECUTED)


class TestC_SurvivesNewGateInstance(_FilePersistenceTestCase):
    """
    Test C — simule un redémarrage du processus : une NOUVELLE
    instance de GenerationApprovalGate (donc un nouveau store en
    mémoire par défaut, MAIS pointant vers le MÊME fichier) doit
    toujours reconnaître 005 comme exécuté.
    """

    def test_new_gate_instance_still_recognizes_execution(self):
        first_gate = self._new_gate()
        first_gate.mark_executed("005")

        # "Redémarrage" : nouvelle instance de Gate, nouveau store
        # Python en mémoire, mais même fichier sur disque.
        second_gate = self._new_gate()

        result = second_gate.evaluate(_request(real_generation_authorization=_valid_auth()))

        self.assertEqual(result.decision, GenerationApprovalDecision.ALREADY_EXECUTED)
        self.assertTrue(second_gate.is_already_executed("005"))


class TestD_NewAuthorizationAfterRestartStillBlocked(_FilePersistenceTestCase):
    """Test D — nouvelle RealGenerationAuthorization après 'redémarrage' -> toujours ALREADY_EXECUTED."""

    def test_fresh_authorization_does_not_unlock_replay_after_restart(self):
        first_gate = self._new_gate()
        first_gate.mark_executed("005")

        second_gate = self._new_gate()
        fresh_auth = RealGenerationAuthorization(request_id="005", authorized_by_human=True)

        result = second_gate.evaluate(_request(real_generation_authorization=fresh_auth))

        self.assertEqual(result.decision, GenerationApprovalDecision.ALREADY_EXECUTED)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestE_DifferentRequestIdNotBlocked(_FilePersistenceTestCase):
    """Test E — nouveau request_id=006 -> ne doit PAS être bloqué à cause de 005."""

    def test_unrelated_request_id_is_unaffected(self):
        gate = self._new_gate()
        gate.mark_executed("005")

        result = gate.evaluate(
            _request(request_id="006", real_generation_authorization=_valid_auth(request_id="006"))
        )

        self.assertEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestF_CorruptedPersistenceFailsClosed(_FilePersistenceTestCase):
    """Test F — état persistant corrompu/invalide -> comportement sûr (jamais APPROVED)."""

    def test_invalid_json_fails_closed_on_evaluate(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text("{not valid json", encoding="utf-8")

        gate = self._new_gate()
        result = gate.evaluate(_request(real_generation_authorization=_valid_auth()))

        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)
        self.assertTrue(any("failing closed" in reason for reason in result.reasons))

    def test_unexpected_shape_fails_closed_on_evaluate(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(["not", "the", "expected", "shape"]), encoding="utf-8")

        gate = self._new_gate()
        result = gate.evaluate(_request(real_generation_authorization=_valid_auth()))

        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)

    def test_store_raises_explicitly_rather_than_silently_returning_false(self):
        # Vérifie directement le store (pas seulement le Gate) :
        # une corruption ne doit JAMAIS ressembler silencieusement à
        # "non exécuté".
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text("{}", encoding="utf-8")  # forme inattendue (pas de clé "executed_requests")

        store = FileExecutedRequestStore(self.state_path)
        with self.assertRaises(ExecutedRequestStoreCorruptedError):
            store.is_executed("005")

    def test_missing_file_is_not_treated_as_corruption(self):
        # Absence légitime (rien n'a encore été exécuté) != corruption.
        store = FileExecutedRequestStore(self.state_path)
        self.assertFalse(store.is_executed("005"))


class TestG_NoHumanAuthorizationStillRefused(_FilePersistenceTestCase):
    """Test G — aucune autorisation humaine -> aucune approbation, même avec persistance active."""

    def test_no_authorization_never_approves(self):
        gate = self._new_gate()

        result = gate.evaluate(_request(real_generation_authorization=None))

        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestH_InsufficientBudgetStillBlocked(_FilePersistenceTestCase):
    """Test H — budget insuffisant -> BLOCKED, même avec autorisation valide et store persistant."""

    def test_insufficient_budget_blocks(self):
        provider = MockHiggsfieldProvider(cost_per_job=50.0, available_credits=1.41)
        gate = self._new_gate(provider=provider)

        result = gate.evaluate(_request(real_generation_authorization=_valid_auth()))

        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)


class TestI_RealProviderStillDisabled(_FilePersistenceTestCase):
    """Test I — le provider réel continue de lever HiggsfieldRealGenerationDisabledError."""

    def test_real_create_job_still_disabled_with_persistent_store(self):
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
        # Aucune exécution réelle n'a eu lieu : rien ne doit avoir été
        # écrit dans le store persistant.
        self.assertFalse(self.state_path.exists())


class TestBackwardCompatibility(unittest.TestCase):
    """
    Non-régression : GenerationApprovalGate(provider) SANS store
    explicite doit garder EXACTEMENT le comportement d'avant P2.15
    (en mémoire uniquement, aucune écriture disque).
    """

    def test_default_store_is_in_memory_and_writes_no_file(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        self.assertIsInstance(gate.executed_request_store, InMemoryExecutedRequestStore)

        gate.mark_executed("005")
        result = gate.evaluate(_request(real_generation_authorization=_valid_auth()))

        self.assertEqual(result.decision, GenerationApprovalDecision.ALREADY_EXECUTED)

    def test_a_fresh_gate_without_a_store_forgets_everything(self):
        # Comportement historique conservé : sans store injecté, un
        # "redémarrage" (nouvelle instance) oublie tout -- c'est
        # exactement la lacune P2.14 pour QUI N'INJECTE PAS de store
        # persistant explicitement (les tests, par défaut).
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        first_gate = GenerationApprovalGate(provider)
        first_gate.mark_executed("005")

        second_gate = GenerationApprovalGate(provider)
        result = second_gate.evaluate(_request(real_generation_authorization=_valid_auth()))

        self.assertEqual(result.decision, GenerationApprovalDecision.APPROVED)


if __name__ == "__main__":
    unittest.main()
