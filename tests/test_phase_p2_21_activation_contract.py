"""
Tests — Phase P2.21 : REQUEST-SCOPED ACTIVATION CONTRACT.

Verrouille par des tests le contrat introduit par
`agents/activation_contract.py` : `RequestScopedActivationContract` +
`RequestScopedActivationService`. Ce module ne câble RIEN dans
`GenerationJobService.execute()` -- vérifié explicitement ici
(TestG) -- et n'appelle jamais `create_job()`. Toutes les données de
coût/solde utilisées proviennent de `MockHiggsfieldProvider` ; les
vérifications d'identité utilisent les VRAIS fichiers/prompt de Video
005 (comme `tests/test_phase_p2_19_activation_contract_design.py`).
Aucun appel réseau, aucun CLI réel, aucun crédit consommé.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import (
    ActivationRejectedError,
    RequestScopedActivationContract,
    RequestScopedActivationService,
)
from agents.critical_section_lock import CriticalSectionBusyError, FileCriticalSectionLock
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from tests.authorization_content_helpers import bind_request
from agents.generation_job_service import GenerationJobService
from agents.release_candidate_identity_lock import (
    ReleaseCandidateIdentityLock,
    VIDEO_005_RELEASE_CANDIDATE,
)
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider
from integrations.higgsfield.types import MediaReference

C = VIDEO_005_RELEASE_CANDIDATE

REAL_AVATAR_PATH = PROJECT_ROOT / "assets" / "zephyr" / "avatar" / "avatar_master.png"
REAL_FACE_PATH = (
    PROJECT_ROOT / "assets" / "zephyr" / "references" / "mon avatar habille.png"
)


def _real_prompt() -> str:
    from agents.prompt_assembly_system import PromptAssemblySystem

    return PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id)


def _conforming_request(**overrides) -> GenerationRequest:
    defaults = dict(
        request_id=C.request_id,
        job_type=C.job_type,
        prompt=_real_prompt(),
        duration=C.duration,
        resolution=C.resolution,
        aspect_ratio=C.aspect_ratio,
        approved=True,
        start_image=MediaReference(
            role="master_avatar", source=str(REAL_AVATAR_PATH), sha256=None
        ),
        image_references=(
            MediaReference(
                role="face_reference", source=str(REAL_FACE_PATH), sha256=None
            ),
        ),
        real_generation_authorization=RealGenerationAuthorization(
            request_id=C.request_id, authorized_by_human=True
        ),
    )
    defaults.update(overrides)
    return bind_request(GenerationRequest(**defaults))


def _valid_auth(request_id=None) -> RealGenerationAuthorization:
    return RealGenerationAuthorization(
        request_id=request_id or C.request_id, authorized_by_human=True
    )


def _new_gate(cost_per_job=10.0, available_credits=100.0, store=None):
    provider = MockHiggsfieldProvider(
        cost_per_job=cost_per_job, available_credits=available_credits
    )
    identity_lock = ReleaseCandidateIdentityLock(C)
    gate = GenerationApprovalGate(
        provider, executed_request_store=store, identity_lock=identity_lock
    )
    return provider, gate, identity_lock


def _new_service(cost_per_job=10.0, available_credits=100.0, store=None, clock=None):
    provider, gate, identity_lock = _new_gate(
        cost_per_job=cost_per_job, available_credits=available_credits, store=store
    )
    kwargs = {}
    if clock is not None:
        kwargs["clock"] = clock
    service = RequestScopedActivationService(gate, identity_lock, **kwargs)
    return provider, gate, identity_lock, service


class TestA_ContractIdentityBinding(unittest.TestCase):
    """Étape 3 / Étape 13 (Contract identity) -- une activation 005 ne
    vaut que pour 005, et exactement pour le contenu Video 005."""

    def test_prepared_for_005_validates_for_005(self):
        _, _, _, service = _new_service()
        request = _conforming_request()

        contract = service.prepare_activation(request)
        self.assertEqual(contract.request_id, "005")

        validated = service.validate_activation(request, contract)
        self.assertIs(validated, contract)

    def test_activation_005_used_against_request_006_is_rejected(self):
        _, _, _, service = _new_service()
        request_005 = _conforming_request()
        contract = service.prepare_activation(request_005)

        request_006 = _conforming_request(
            request_id="006",
            real_generation_authorization=_valid_auth("006"),
        )

        with self.assertRaises(ActivationRejectedError) as ctx:
            service.validate_activation(request_006, contract)
        self.assertTrue(
            any("bound to request '005'" in r for r in ctx.exception.reasons)
        )

    def test_prepare_rejected_for_wrong_request_id_entirely(self):
        # 006 n'est même pas la Release Candidate verrouillée : rejeté
        # dès prepare_activation(), avant qu'un contrat n'existe.
        _, _, _, service = _new_service()
        request_006 = _conforming_request(
            request_id="006", real_generation_authorization=_valid_auth("006")
        )
        with self.assertRaises(ActivationRejectedError):
            service.prepare_activation(request_006)

    def test_prepare_rejected_when_prompt_differs(self):
        _, _, _, service = _new_service()
        request = _conforming_request(prompt="Un prompt totalement différent.")
        with self.assertRaises(ActivationRejectedError) as ctx:
            service.prepare_activation(request)
        self.assertTrue(any("prompt" in r.lower() for r in ctx.exception.reasons))

    def test_prepare_rejected_when_asset_differs(self):
        _, _, _, service = _new_service()
        # Fichier réel existant mais différent de l'avatar canonique.
        request = _conforming_request(
            start_image=MediaReference(
                role="master_avatar", source=str(REAL_FACE_PATH), sha256=None
            )
        )
        with self.assertRaises(ActivationRejectedError) as ctx:
            service.prepare_activation(request)
        self.assertTrue(
            any("master_avatar" in r for r in ctx.exception.reasons)
        )

    def test_prepare_rejected_when_model_differs(self):
        _, _, _, service = _new_service()
        request = _conforming_request(job_type="other_model")
        with self.assertRaises(ActivationRejectedError) as ctx:
            service.prepare_activation(request)
        self.assertTrue(any("job_type" in r for r in ctx.exception.reasons))

    def test_prepare_rejected_when_duration_differs(self):
        _, _, _, service = _new_service()
        request = _conforming_request(duration=5)
        with self.assertRaises(ActivationRejectedError) as ctx:
            service.prepare_activation(request)
        self.assertTrue(any("duration" in r for r in ctx.exception.reasons))

    def test_prepare_rejected_when_resolution_differs(self):
        _, _, _, service = _new_service()
        request = _conforming_request(resolution="1080p")
        with self.assertRaises(ActivationRejectedError) as ctx:
            service.prepare_activation(request)
        self.assertTrue(any("resolution" in r for r in ctx.exception.reasons))

    def test_prepare_rejected_when_aspect_ratio_differs(self):
        _, _, _, service = _new_service()
        request = _conforming_request(aspect_ratio="16:9")
        with self.assertRaises(ActivationRejectedError) as ctx:
            service.prepare_activation(request)
        self.assertTrue(any("aspect_ratio" in r for r in ctx.exception.reasons))


class TestB_DoubleConsent(unittest.TestCase):
    """Étape 4 / Étape 13 (Double consent)."""

    def test_no_approval_is_rejected(self):
        _, _, _, service = _new_service()
        request = _conforming_request(approved=False)
        with self.assertRaises(ActivationRejectedError) as ctx:
            service.prepare_activation(request)
        self.assertTrue(
            any("APPROVED" in r or "approval" in r for r in ctx.exception.reasons)
        )

    def test_no_human_authorization_is_rejected(self):
        _, _, _, service = _new_service()
        request = _conforming_request(real_generation_authorization=None)
        with self.assertRaises(ActivationRejectedError):
            service.prepare_activation(request)

    def test_wrong_authorization_request_id_is_rejected(self):
        _, _, _, service = _new_service()
        request = _conforming_request(
            real_generation_authorization=_valid_auth("not-005")
        )
        with self.assertRaises(ActivationRejectedError):
            service.prepare_activation(request)

    def test_valid_approval_and_authorization_makes_contract_eligible(self):
        _, _, _, service = _new_service()
        request = _conforming_request()
        contract = service.prepare_activation(request)
        self.assertIsInstance(contract, RequestScopedActivationContract)

    def test_no_human_authorization_is_ever_auto_created(self):
        # `authorized_by_human` n'apparaît nulle part sur le contrat --
        # seul un authorization_id de traçabilité est conservé.
        _, _, _, service = _new_service()
        request = _conforming_request()
        contract = service.prepare_activation(request)
        self.assertFalse(hasattr(contract, "authorized_by_human"))
        self.assertFalse(hasattr(contract, "real_generation_authorization"))


class TestC_Freshness(unittest.TestCase):
    """Étape 6 / Étape 13 (Freshness) -- rien n'est jamais réutilisé
    d'une évaluation à l'autre."""

    def test_budget_drop_between_prepare_and_validate_blocks_validation(self):
        provider, _, _, service = _new_service(cost_per_job=10.0, available_credits=100.0)
        request = _conforming_request()

        contract = service.prepare_activation(request)
        provider._available_credits = 1.41  # Solde frais, différent.

        with self.assertRaises(ActivationRejectedError):
            service.validate_activation(request, contract)

    def test_cost_increase_between_prepare_and_validate_blocks_validation(self):
        provider, _, _, service = _new_service(cost_per_job=10.0, available_credits=100.0)
        request = _conforming_request()

        contract = service.prepare_activation(request)
        provider._cost_per_job = 1000.0  # Coût frais, différent.

        with self.assertRaises(ActivationRejectedError):
            service.validate_activation(request, contract)

    def test_identity_change_between_prepare_and_validate_blocks_validation(self):
        _, _, _, service = _new_service()
        request = _conforming_request()
        contract = service.prepare_activation(request)

        mutated_request = _conforming_request(prompt=request.prompt + " ")

        with self.assertRaises(ActivationRejectedError) as ctx:
            service.validate_activation(mutated_request, contract)
        self.assertTrue(
            any(
                "prompt" in r.lower() or "sha256" in r.lower()
                for r in ctx.exception.reasons
            )
        )

    def test_replay_state_change_between_prepare_and_validate_blocks_validation(self):
        provider, gate, _, service = _new_service()
        request = _conforming_request()
        contract = service.prepare_activation(request)

        gate.mark_executed(request.request_id)

        with self.assertRaises(ActivationRejectedError) as ctx:
            service.validate_activation(request, contract)
        self.assertTrue(
            any("ALREADY_EXECUTED" in r for r in ctx.exception.reasons)
        )


class TestD_Replay(unittest.TestCase):
    """Étape 8 / Étape 13 (Replay)."""

    def test_already_executed_request_cannot_be_prepared(self):
        _, gate, _, service = _new_service()
        gate.mark_executed(C.request_id)
        request = _conforming_request()

        with self.assertRaises(ActivationRejectedError) as ctx:
            service.prepare_activation(request)
        self.assertTrue(
            any("ALREADY_EXECUTED" in r for r in ctx.exception.reasons)
        )

    def test_unknown_state_request_cannot_be_prepared(self):
        _, gate, _, service = _new_service()
        gate.mark_unknown(C.request_id, reason="test")
        request = _conforming_request()

        with self.assertRaises(ActivationRejectedError) as ctx:
            service.prepare_activation(request)
        self.assertTrue(
            any("EXECUTION_STATE_UNKNOWN" in r for r in ctx.exception.reasons)
        )

    def test_new_human_authorization_after_unknown_still_rejected(self):
        _, gate, _, service = _new_service()
        gate.mark_unknown(C.request_id, reason="test")
        # Nouvelle autorisation humaine "fraîche" -- ne doit rien
        # débloquer : UNKNOWN reste UNKNOWN quelle que soit
        # l'autorisation fournie.
        request = _conforming_request(
            real_generation_authorization=RealGenerationAuthorization(
                request_id=C.request_id, authorized_by_human=True, note="new auth"
            )
        )
        with self.assertRaises(ActivationRejectedError) as ctx:
            service.prepare_activation(request)
        self.assertTrue(
            any("EXECUTION_STATE_UNKNOWN" in r for r in ctx.exception.reasons)
        )


class TestE_Lifetime(unittest.TestCase):
    """Étape 7 / Étape 13 (Lifetime) -- usage unique, non réutilisable,
    jamais partagé entre instances."""

    def test_contract_cannot_be_validated_twice(self):
        _, _, _, service = _new_service()
        request = _conforming_request()
        contract = service.prepare_activation(request)

        service.validate_activation(request, contract)  # 1ère fois : OK.

        with self.assertRaises(ActivationRejectedError) as ctx:
            service.validate_activation(request, contract)  # 2ème : refus.
        self.assertTrue(
            any("already been consumed" in r for r in ctx.exception.reasons)
        )

    def test_contract_from_another_service_instance_is_rejected(self):
        _, _, _, service_a = _new_service()
        _, _, _, service_b = _new_service()

        request = _conforming_request()
        contract = service_a.prepare_activation(request)

        with self.assertRaises(ActivationRejectedError) as ctx:
            service_b.validate_activation(request, contract)
        self.assertTrue(
            any("not issued by this" in r for r in ctx.exception.reasons)
        )

    def test_expired_contract_is_rejected(self):
        fake_time = {"t": 1000.0}
        contract_holder = {}

        _, _, _, service = _new_service(clock=lambda: fake_time["t"])
        service.max_age_seconds = 60.0

        request = _conforming_request()
        contract = service.prepare_activation(request)
        contract_holder["c"] = contract

        fake_time["t"] += 61.0  # Dépasse max_age_seconds.

        with self.assertRaises(ActivationRejectedError) as ctx:
            service.validate_activation(request, contract_holder["c"])
        self.assertTrue(any("expired" in r for r in ctx.exception.reasons))

    def test_activation_prepared_for_005_cannot_validate_another_request_object(self):
        _, _, _, service = _new_service()
        request_a = _conforming_request()
        contract = service.prepare_activation(request_a)

        # Même request_id, mais objet de requête différent portant un
        # prompt légèrement différent -- doit rester bloqué (couvre
        # aussi Freshness/identité, cf. TestC, ici sous l'angle
        # Lifetime : le contrat ne "suit" jamais une requête modifiée).
        request_b = _conforming_request(prompt=request_a.prompt + "\n")

        with self.assertRaises(ActivationRejectedError):
            service.validate_activation(request_b, contract)


class TestF_CriticalSection(unittest.TestCase):
    """Étape 9 / Étape 13 (Critical section) -- le contrat ne remplace
    ni ne contourne jamais le verrou P2.20 ; il compose avec lui sans
    lui être couplé."""

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_21_lock_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def test_validate_activation_never_touches_any_lock(self):
        import inspect

        sig = inspect.signature(RequestScopedActivationService.validate_activation)
        self.assertNotIn("lock", sig.parameters)
        sig_prepare = inspect.signature(RequestScopedActivationService.prepare_activation)
        self.assertNotIn("lock", sig_prepare.parameters)

    def test_valid_contract_does_not_bypass_a_busy_lock(self):
        # Composition volontaire : le SERVICE ne connaît pas le
        # verrou, mais rien n'empêche un futur appelant d'entourer
        # validate_activation() avec le même FileCriticalSectionLock
        # que GenerationJobService -- et ce verrou continue de refuser
        # normalement, contrat valide ou non.
        _, _, _, service = _new_service()
        request = _conforming_request()
        contract = service.prepare_activation(request)

        lock = FileCriticalSectionLock(self._tmp)
        with lock.acquire(request.request_id):
            with self.assertRaises(CriticalSectionBusyError):
                with lock.acquire(request.request_id):
                    service.validate_activation(request, contract)

    def test_lock_busy_leaves_contract_unconsumed_for_a_later_legitimate_attempt(self):
        _, _, _, service = _new_service()
        request = _conforming_request()
        contract = service.prepare_activation(request)

        lock = FileCriticalSectionLock(self._tmp)
        with lock.acquire(request.request_id):
            pass  # Acquisition/relâche normales, aucune contention ici.

        # Le contrat n'a jamais été touché par le cycle de verrou
        # ci-dessus : il reste valide pour un usage légitime.
        validated = service.validate_activation(request, contract)
        self.assertIs(validated, contract)


class TestG_NoWiringIntoGenerationJobService(unittest.TestCase):
    """Étape 10 -- au moment de P2.21, le contrat ne pouvait
    déclencher AUCUNE génération : GenerationJobService.execute()
    n'acceptait aucun paramètre d'activation, structurellement, pas
    seulement par convention (même style de preuve que P2.19 TestJ).

    MIS À JOUR Phase P2.22 : ce câblage explicite existe désormais
    (agents/generation_job_service.py::execute(activation_contract=None)),
    délibérément et documenté -- ce n'est plus l'invariant testé ici.
    Ce qui doit rester vrai en permanence, et que ce test vérifie
    maintenant : le paramètre reste facultatif (défaut `None`, jamais
    de contrat créé implicitement), et surtout que
    `tests/test_phase_p2_22_activation_wiring.py` prouve que même un
    contrat explicite et intégralement validé ne fait jamais franchir
    `HiggsfieldRealGenerationDisabledError`."""

    def test_execute_signature_has_an_optional_activation_contract_parameter(self):
        import inspect

        sig = inspect.signature(GenerationJobService.execute)
        self.assertIn("activation_contract", sig.parameters)
        self.assertIsNone(sig.parameters["activation_contract"].default)

    def test_activation_contract_module_imports_no_client_or_network(self):
        import inspect

        import agents.activation_contract as module

        imported_names = {
            name
            for name, value in vars(module).items()
            if inspect.ismodule(value) or inspect.isclass(value)
        }
        self.assertNotIn("HiggsfieldClient", imported_names)
        self.assertFalse(hasattr(module, "requests"))
        self.assertFalse(hasattr(module, "socket"))
        self.assertFalse(hasattr(module, "subprocess"))


class TestH_ProviderStaysDisabled(unittest.TestCase):
    """Étape 10 / Étape 13 (Provider) -- même un contrat pleinement
    validé, appliqué au VRAI HiggsfieldProvider, ne débloque rien."""

    def test_real_provider_still_disabled_even_with_a_validated_contract(self):
        from unittest.mock import MagicMock

        fake_client = MagicMock()
        fake_client.estimate_cost.return_value = {"credits": 10.0}
        fake_client.account_status.return_value = {"credits": 1000.0}
        fake_client.get_model.return_value = {
            "job_type": C.job_type,
            "display_name": "d",
            "params": [
                {"name": "prompt", "type": "string", "required": True},
                {"name": "duration", "type": "integer", "required": False, "default": 5},
                {"name": "start_image", "type": "object|null", "required": False},
                {"name": "image_references", "type": "array", "required": False},
            ],
        }

        real_provider = HiggsfieldProvider(client=fake_client)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(real_provider, identity_lock=identity_lock)
        service = RequestScopedActivationService(gate, identity_lock)

        request = _conforming_request()

        contract = service.prepare_activation(request)
        validated = service.validate_activation(request, contract)
        self.assertIs(validated, contract)

        # Le contrat "validé" (au sens de ce module) ne connecte à
        # RIEN : create_job() reste inaccessible depuis ce contrat, et
        # le Provider réel reste inconditionnellement désactivé.
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(job_type=C.job_type, prompt=request.prompt)

        fake_client.create_job.assert_not_called()

    def test_no_mock_job_ever_created_by_this_module_alone(self):
        provider, _, _, service = _new_service()
        request = _conforming_request()
        contract = service.prepare_activation(request)
        service.validate_activation(request, contract)
        self.assertEqual(len(provider._jobs), 0)


if __name__ == "__main__":
    unittest.main()
