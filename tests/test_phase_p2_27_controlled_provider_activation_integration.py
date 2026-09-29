"""
Tests — Phase P2.27 : CONTROLLED PROVIDER ACTIVATION INTEGRATION &
FINAL PRE-PRODUCTION SAFETY GATE.

Verrouille le câblage introduit cette phase :
`GenerationJobService.execute(request, activation_contract=None,
provider_activation_contract=None)` valide désormais, DANS le
FileCriticalSectionLock, un `ControlledRealProviderActivationContract`
(Phase P2.26) fourni EXPLICITEMENT -- APRÈS le contrat P2.21 et AVANT
`create_job()`.

Ce fichier prouve, avec le VRAI `FileCriticalSectionLock` et les VRAIS
fichiers/prompt de Video 005, qu'un scénario COMPLET, positif,
utilisant EXCLUSIVEMENT `MockHiggsfieldProvider`, traverse RÉELLEMENT
les deux couches d'activation et crée un job simulé -- tandis que le
MÊME scénario, avec le VRAI `HiggsfieldProvider`, reste bloqué par
`HiggsfieldRealGenerationDisabledError`, quelle que soit la validité
de tout le reste.
"""

import ast
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import (
    ActivationRejectedError,
    RequestScopedActivationService,
)
from agents.activation_readiness import ActivationReadinessEvaluator
from agents.controlled_real_provider_activation import (
    ControlledRealProviderActivationRejectedError,
    ControlledRealProviderActivationService,
)
from agents.critical_section_lock import CriticalSectionBusyError, FileCriticalSectionLock
from agents.final_report_service import (
    ActivationDecision,
    FinalReportService,
    FinalReportStatus,
)
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from tests.authorization_content_helpers import bind_request
from agents.generation_job_service import (
    GenerationJobActivationRejectedError,
    GenerationJobExecutionError,
    GenerationJobProviderActivationRejectedError,
    GenerationJobService,
)
from agents.release_candidate_identity_lock import (
    ReleaseCandidateIdentityLock,
    VIDEO_005_RELEASE_CANDIDATE,
)
from director import AIDirector
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


class _Stack:
    def __init__(self, tmp_dir: Path, cost_per_job=67.5, available_credits=100.0):
        self.provider = MockHiggsfieldProvider(
            cost_per_job=cost_per_job, available_credits=available_credits
        )
        self.identity_lock = ReleaseCandidateIdentityLock(C)
        self.gate = GenerationApprovalGate(self.provider, identity_lock=self.identity_lock)
        self.activation_service = RequestScopedActivationService(
            self.gate, self.identity_lock
        )
        self.provider_activation_service = ControlledRealProviderActivationService(
            self.gate, self.identity_lock, self.activation_service
        )
        self.lock = FileCriticalSectionLock(tmp_dir)
        self.job_service = GenerationJobService(
            self.provider,
            self.gate,
            lock=self.lock,
            activation_service=self.activation_service,
            provider_activation_service=self.provider_activation_service,
        )
        self.report_service = FinalReportService(
            self.provider, self.gate, job_service=self.job_service
        )

    def prepared(self, request):
        rs_contract = self.activation_service.prepare_activation(request)
        pa_contract = self.provider_activation_service.prepare(request, rs_contract)
        return rs_contract, pa_contract


class P2_27_TestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_27_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def _stack(self, **kwargs) -> _Stack:
        return _Stack(self._tmp, **kwargs)


# ----------------------------------------------------------------------
# 17. Complete positive scenario, MockProvider only
# ----------------------------------------------------------------------


class TestMockPositiveScenario(P2_27_TestCase):
    def test_full_positive_scenario_traverses_both_activation_layers(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)

        outcome = stack.job_service.execute(
            request,
            activation_contract=rs_contract,
            provider_activation_contract=pa_contract,
            interval_seconds=0,
        )

        self.assertTrue(outcome.succeeded)
        self.assertEqual(len(stack.provider._jobs), 1)
        # Replay est bien enregistré.
        self.assertTrue(stack.gate.is_already_executed(request.request_id))

    def test_final_report_mechanism_works_end_to_end(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)

        report = stack.report_service.generate(
            request,
            activation_contract=rs_contract,
            provider_activation_contract=pa_contract,
            interval_seconds=0,
        )

        self.assertEqual(report.status, FinalReportStatus.EXECUTED_PASS)
        self.assertTrue(report.job_created)
        # CORRIGÉ (audit truthfulness post-P2.27) : `stack` utilise
        # MockHiggsfieldProvider -- `real_provider_called` doit être
        # False. `job_created=True` ne prouve jamais, à lui seul,
        # qu'il s'agit du vrai HiggsfieldProvider (cf.
        # agents/final_report_service.py::_is_real_provider()).
        self.assertFalse(report.real_provider_called)
        self.assertEqual(report.activation_decision, ActivationDecision.APPROVED)
        self.assertEqual(report.provider_activation_decision, ActivationDecision.APPROVED)
        self.assertEqual(report.execution_state, "EXECUTED")


# ----------------------------------------------------------------------
# 18. Complete scenario, real provider -> blocked
# ----------------------------------------------------------------------


class TestRealProviderBlockedScenario(P2_27_TestCase):
    def test_same_scenario_with_real_provider_stays_blocked(self):
        fake_client = MagicMock()
        fake_client.estimate_cost.return_value = {"credits": 67.5}
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
        rs_service = RequestScopedActivationService(gate, identity_lock)
        pa_service = ControlledRealProviderActivationService(gate, identity_lock, rs_service)
        lock = FileCriticalSectionLock(self._tmp)
        job_service = GenerationJobService(
            real_provider, gate, lock=lock,
            activation_service=rs_service, provider_activation_service=pa_service,
        )
        report_service = FinalReportService(real_provider, gate, job_service=job_service)

        request = _conforming_request()
        rs_contract = rs_service.prepare_activation(request)

        # La frontière P2.26 elle-même refuse AVANT même create_job() --
        # prepare() échoue déjà contre le Provider réel.
        with self.assertRaises(ControlledRealProviderActivationRejectedError):
            pa_service.prepare(request, rs_contract)

        # Même en forçant artificiellement un contrat P2.26 déjà
        # préparé contre un Mock, puis en l'utilisant contre le VRAI
        # provider via execute(), la validation à l'intérieur du
        # verrou doit encore bloquer AVANT create_job().
        mock_provider = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=100.0)
        mock_gate = GenerationApprovalGate(mock_provider, identity_lock=identity_lock)
        mock_rs_service = RequestScopedActivationService(mock_gate, identity_lock)
        mock_pa_service = ControlledRealProviderActivationService(
            mock_gate, identity_lock, mock_rs_service
        )
        mock_rs_contract = mock_rs_service.prepare_activation(request)
        mock_pa_contract = mock_pa_service.prepare(request, mock_rs_contract)

        with self.assertRaises(GenerationJobProviderActivationRejectedError):
            job_service.execute(
                request,
                activation_contract=rs_contract,
                provider_activation_contract=mock_pa_contract,
                interval_seconds=0,
            )
        fake_client.create_job.assert_not_called()

        # Rapport : GenerationJobProviderActivationRejectedError EST
        # une sous-classe de GenerationJobExecutionError -- generate()
        # la capture donc (comportement voulu depuis P2.23, jamais
        # une exception non gérée) et produit un rapport NOT_EXECUTED
        # fidèle, jamais EXECUTED_PASS, real_provider_called=False.
        report = report_service.generate(
            request,
            activation_contract=rs_contract,
            provider_activation_contract=mock_pa_contract,
            interval_seconds=0,
        )
        self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)
        self.assertFalse(report.job_created)
        self.assertFalse(report.real_provider_called)
        self.assertEqual(report.activation_decision, ActivationDecision.APPROVED)
        self.assertEqual(report.provider_activation_decision, ActivationDecision.REJECTED)


# ----------------------------------------------------------------------
# 19. Budget tests
# ----------------------------------------------------------------------


class TestBudget(P2_27_TestCase):
    def test_insufficient_budget_blocks_before_activation(self):
        stack = self._stack(cost_per_job=67.5, available_credits=1.41)
        request = _conforming_request()
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)

    def test_sufficient_budget_allows_mock_execution_but_provider_boundary_persists_for_real(self):
        stack = self._stack(cost_per_job=67.5, available_credits=100.0)
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)
        outcome = stack.job_service.execute(
            request, activation_contract=rs_contract,
            provider_activation_contract=pa_contract, interval_seconds=0,
        )
        self.assertTrue(outcome.succeeded)


# ----------------------------------------------------------------------
# 20. Mutation-after-activation adversarial tests (1-16, data-driven)
# ----------------------------------------------------------------------


class TestMutationAfterActivation(P2_27_TestCase):
    def _prepare_then_mutate_and_execute(self, **overrides):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)

        mutated = _conforming_request(**overrides)
        with self.assertRaises(Exception):
            stack.job_service.execute(
                mutated, activation_contract=rs_contract,
                provider_activation_contract=pa_contract, interval_seconds=0,
            )
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_1_prompt_modified(self):
        self._prepare_then_mutate_and_execute(prompt=_real_prompt() + " ")

    def test_2_avatar_modified(self):
        self._prepare_then_mutate_and_execute(
            start_image=MediaReference(
                role="master_avatar", source=str(REAL_FACE_PATH), sha256=None
            )
        )

    def test_3_face_reference_modified(self):
        self._prepare_then_mutate_and_execute(
            image_references=(
                MediaReference(
                    role="face_reference", source=str(REAL_AVATAR_PATH), sha256=None
                ),
            )
        )

    def test_4_model_modified(self):
        self._prepare_then_mutate_and_execute(job_type="other_model")

    def test_5_duration_modified(self):
        self._prepare_then_mutate_and_execute(duration=5)

    def test_6_resolution_modified(self):
        self._prepare_then_mutate_and_execute(resolution="1080p")

    def test_7_aspect_ratio_modified(self):
        self._prepare_then_mutate_and_execute(aspect_ratio="16:9")

    def test_8_cost_modified(self):
        stack = self._stack(cost_per_job=10.0, available_credits=100.0)
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)
        stack.provider._cost_per_job = 1000.0
        with self.assertRaises(Exception):
            stack.job_service.execute(
                request, activation_contract=rs_contract,
                provider_activation_contract=pa_contract, interval_seconds=0,
            )
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_9_balance_becomes_insufficient(self):
        stack = self._stack(cost_per_job=10.0, available_credits=100.0)
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)
        stack.provider._available_credits = 1.41
        with self.assertRaises(Exception):
            stack.job_service.execute(
                request, activation_contract=rs_contract,
                provider_activation_contract=pa_contract, interval_seconds=0,
            )
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_10_authorization_replaced(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)
        swapped = _conforming_request(
            real_generation_authorization=_valid_auth("not-005")
        )
        with self.assertRaises(Exception):
            stack.job_service.execute(
                swapped, activation_contract=rs_contract,
                provider_activation_contract=pa_contract, interval_seconds=0,
            )
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_11_p2_21_activation_replaced_with_foreign(self):
        stack_a = self._stack()
        other_tmp = Path(tempfile.mkdtemp(prefix="p2_27_other_"))
        self.addCleanup(shutil.rmtree, other_tmp, ignore_errors=True)
        stack_b = _Stack(other_tmp)

        request = _conforming_request()
        _, pa_contract_a = stack_a.prepared(request)
        foreign_rs_contract = stack_b.activation_service.prepare_activation(request)

        # Rejeté dès la couche P2.21 : `foreign_rs_contract` n'a
        # jamais été émis par `stack_a.activation_service` -- la
        # couche P2.26 n'est même pas atteinte.
        with self.assertRaises(GenerationJobActivationRejectedError):
            stack_a.job_service.execute(
                request, activation_contract=foreign_rs_contract,
                provider_activation_contract=pa_contract_a, interval_seconds=0,
            )
        self.assertEqual(len(stack_a.provider._jobs), 0)

    def test_12_p2_26_contract_replaced_with_foreign(self):
        stack_a = self._stack()
        other_tmp = Path(tempfile.mkdtemp(prefix="p2_27_other2_"))
        self.addCleanup(shutil.rmtree, other_tmp, ignore_errors=True)
        stack_b = _Stack(other_tmp)

        request = _conforming_request()
        rs_contract_a, _ = stack_a.prepared(request)
        _, foreign_pa_contract = stack_b.prepared(request)

        with self.assertRaises(GenerationJobProviderActivationRejectedError):
            stack_a.job_service.execute(
                request, activation_contract=rs_contract_a,
                provider_activation_contract=foreign_pa_contract, interval_seconds=0,
            )
        self.assertEqual(len(stack_a.provider._jobs), 0)

    def test_13_activation_expired(self):
        fake_time = {"t": 1000.0}
        provider = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=100.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
        rs_service = RequestScopedActivationService(gate, identity_lock)
        pa_service = ControlledRealProviderActivationService(
            gate, identity_lock, rs_service, max_age_seconds=60.0, clock=lambda: fake_time["t"]
        )
        lock = FileCriticalSectionLock(self._tmp)
        job_service = GenerationJobService(
            provider, gate, lock=lock, activation_service=rs_service,
            provider_activation_service=pa_service,
        )

        request = _conforming_request()
        rs_contract = rs_service.prepare_activation(request)
        pa_contract = pa_service.prepare(request, rs_contract)
        fake_time["t"] += 61.0

        with self.assertRaises(GenerationJobProviderActivationRejectedError):
            job_service.execute(
                request, activation_contract=rs_contract,
                provider_activation_contract=pa_contract, interval_seconds=0,
            )
        self.assertEqual(len(provider._jobs), 0)

    def test_14_activation_already_consumed(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)
        stack.provider_activation_service.validate(request, rs_contract, pa_contract)

        with self.assertRaises(GenerationJobProviderActivationRejectedError):
            stack.job_service.execute(
                request, activation_contract=rs_contract,
                provider_activation_contract=pa_contract, interval_seconds=0,
            )
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_15_request_already_executed(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)
        stack.gate.mark_executed(request.request_id)

        with self.assertRaises(GenerationJobExecutionError) as ctx:
            stack.job_service.execute(
                request, activation_contract=rs_contract,
                provider_activation_contract=pa_contract, interval_seconds=0,
            )
        self.assertEqual(
            ctx.exception.approval.decision, GenerationApprovalDecision.ALREADY_EXECUTED
        )
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_16_request_unknown(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)
        stack.gate.mark_unknown(request.request_id, reason="test")

        with self.assertRaises(GenerationJobExecutionError) as ctx:
            stack.job_service.execute(
                request, activation_contract=rs_contract,
                provider_activation_contract=pa_contract, interval_seconds=0,
            )
        self.assertEqual(
            ctx.exception.approval.decision,
            GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN,
        )
        self.assertEqual(len(stack.provider._jobs), 0)


# ----------------------------------------------------------------------
# 21. Critical section tests
# ----------------------------------------------------------------------


class TestCriticalSection(P2_27_TestCase):
    def test_lock_busy_blocks_even_with_fully_valid_contracts(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)

        with stack.lock.acquire(request.request_id):
            with self.assertRaises(CriticalSectionBusyError):
                stack.job_service.execute(
                    request, activation_contract=rs_contract,
                    provider_activation_contract=pa_contract, interval_seconds=0,
                )
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_lock_released_after_provider_activation_rejection(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)
        stack.provider_activation_service.revoke(pa_contract)

        with self.assertRaises(GenerationJobProviderActivationRejectedError):
            stack.job_service.execute(
                request, activation_contract=rs_contract,
                provider_activation_contract=pa_contract, interval_seconds=0,
            )

        self.assertFalse((self._tmp / "005.lock").exists())
        with stack.lock.acquire("005"):
            pass  # doit réussir : verrou bien libéré

    def test_mark_executed_failure_still_yields_unknown_not_lost(self):
        from agents.generation_job_service import GenerationJobUnknownStateError

        class _RaisingMarkExecutedGate(GenerationApprovalGate):
            def mark_executed(self, request_id: str, job_id=None) -> None:
                raise OSError("simulated disk failure")

        provider = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=100.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = _RaisingMarkExecutedGate(provider, identity_lock=identity_lock)
        rs_service = RequestScopedActivationService(gate, identity_lock)
        pa_service = ControlledRealProviderActivationService(gate, identity_lock, rs_service)
        lock = FileCriticalSectionLock(self._tmp)
        job_service = GenerationJobService(
            provider, gate, lock=lock, activation_service=rs_service,
            provider_activation_service=pa_service,
        )

        request = _conforming_request()
        rs_contract = rs_service.prepare_activation(request)
        pa_contract = pa_service.prepare(request, rs_contract)

        with self.assertRaises(GenerationJobUnknownStateError):
            job_service.execute(
                request, activation_contract=rs_contract,
                provider_activation_contract=pa_contract, interval_seconds=0,
            )
        # Le job a bien été "créé" côté Mock (l'ambiguïté vient d'APRÈS).
        self.assertEqual(len(provider._jobs), 1)
        self.assertTrue(gate.is_unknown(request.request_id))


# ----------------------------------------------------------------------
# 22. Crash test (UNKNOWN, never silently NOT_EXECUTED)
# ----------------------------------------------------------------------


class TestCrashSafety(P2_27_TestCase):
    def test_unknown_state_blocks_new_attempt_with_fresh_contracts(self):
        provider = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=100.0)
        identity_lock = ReleaseCandidateIdentityLock(C)

        class _RaisingMarkExecutedGate(GenerationApprovalGate):
            def mark_executed(self, request_id: str, job_id=None) -> None:
                raise OSError("simulated disk failure")

        gate = _RaisingMarkExecutedGate(provider, identity_lock=identity_lock)
        rs_service = RequestScopedActivationService(gate, identity_lock)
        pa_service = ControlledRealProviderActivationService(gate, identity_lock, rs_service)
        lock = FileCriticalSectionLock(self._tmp)
        job_service = GenerationJobService(
            provider, gate, lock=lock, activation_service=rs_service,
            provider_activation_service=pa_service,
        )

        request = _conforming_request()
        rs_contract = rs_service.prepare_activation(request)
        pa_contract = pa_service.prepare(request, rs_contract)

        from agents.generation_job_service import GenerationJobUnknownStateError
        with self.assertRaises(GenerationJobUnknownStateError):
            job_service.execute(
                request, activation_contract=rs_contract,
                provider_activation_contract=pa_contract, interval_seconds=0,
            )

        # Nouvelle tentative, avec un Gate normal (pas de nouveau bug
        # simulé) et de TOUT nouveaux contrats -- doit rester bloquée
        # par EXECUTION_STATE_UNKNOWN, jamais NOT_EXECUTED "ordinaire".
        normal_gate = GenerationApprovalGate(
            provider,
            executed_request_store=gate.executed_request_store,
            identity_lock=identity_lock,
        )
        result = normal_gate.evaluate(request)
        self.assertEqual(
            result.decision, GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN
        )
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


# ----------------------------------------------------------------------
# 23. Replay test after a successful mock execution
# ----------------------------------------------------------------------


class TestReplayAfterSuccess(P2_27_TestCase):
    def test_second_execution_blocked_even_with_brand_new_contracts(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)

        outcome = stack.job_service.execute(
            request, activation_contract=rs_contract,
            provider_activation_contract=pa_contract, interval_seconds=0,
        )
        self.assertTrue(outcome.succeeded)

        # Nouvelle autorisation, nouveau P2.21, nouveau P2.26 --
        # toujours bloqué par ALREADY_EXECUTED.
        new_request = _conforming_request(
            real_generation_authorization=RealGenerationAuthorization(
                request_id=C.request_id, authorized_by_human=True, note="brand new"
            )
        )
        with self.assertRaises(ActivationRejectedError) as ctx:
            stack.activation_service.prepare_activation(new_request)
        self.assertTrue(any("already been executed" in r for r in ctx.exception.reasons))
        self.assertEqual(len(stack.provider._jobs), 1)


# ----------------------------------------------------------------------
# 24. Double-consent tests
# ----------------------------------------------------------------------


class TestDoubleConsent(P2_27_TestCase):
    def test_A_approved_true_but_no_authorization_blocks(self):
        stack = self._stack()
        request = _conforming_request(real_generation_authorization=None)
        with self.assertRaises(GenerationJobExecutionError):
            stack.job_service.execute(request, interval_seconds=0)

    def test_B_authorization_valid_but_gate_not_approved_blocks(self):
        stack = self._stack()
        request = _conforming_request(approved=False)
        with self.assertRaises(GenerationJobExecutionError):
            stack.job_service.execute(request, interval_seconds=0)

    def test_C_gate_and_authorization_valid_but_no_p2_21_activation_means_no_p2_26_either(self):
        # Sans contrat P2.21, execute() réussit quand même (comportement
        # legacy inchangé, cf. P2.20) -- mais AUCUNE des deux couches
        # d'activation n'a jamais été évaluée.
        stack = self._stack()
        request = _conforming_request()
        report = stack.report_service.generate(request, interval_seconds=0)
        self.assertEqual(report.activation_decision, ActivationDecision.NOT_EVALUATED)
        self.assertEqual(report.provider_activation_decision, ActivationDecision.NOT_EVALUATED)

    def test_D_gate_authorization_and_p2_21_valid_but_no_p2_26_contract(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract = stack.activation_service.prepare_activation(request)
        report = stack.report_service.generate(
            request, activation_contract=rs_contract, interval_seconds=0
        )
        self.assertEqual(report.activation_decision, ActivationDecision.APPROVED)
        self.assertEqual(report.provider_activation_decision, ActivationDecision.NOT_EVALUATED)
        self.assertTrue(report.job_created)  # P2.26 n'est jamais requis pour exécuter

    def test_E_everything_valid_but_real_provider_disabled(self):
        fake_client = MagicMock()
        fake_client.estimate_cost.return_value = {"credits": 67.5}
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
        rs_service = RequestScopedActivationService(gate, identity_lock)
        pa_service = ControlledRealProviderActivationService(gate, identity_lock, rs_service)

        request = _conforming_request()
        rs_contract = rs_service.prepare_activation(request)

        with self.assertRaises(ControlledRealProviderActivationRejectedError):
            pa_service.prepare(request, rs_contract)
        fake_client.create_job.assert_not_called()


# ----------------------------------------------------------------------
# 25. No automatic authority (AST audit, including ActivationReadinessEvaluator)
# ----------------------------------------------------------------------


class TestNoAutomaticAuthority(unittest.TestCase):
    FILES = (
        "director.py",
        "agents/planner.py",
        "agents/video_agent.py",
        "agents/task_manager.py",
        "agents/activation_readiness.py",
    )

    def test_no_component_constructs_real_generation_authorization(self):
        for relative_path in self.FILES:
            text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8-sig")
            self.assertNotIn(
                "RealGenerationAuthorization(",
                text,
                f"{relative_path} must never construct a RealGenerationAuthorization",
            )

    def test_no_component_calls_prepare_activation_or_pa_service_prepare(self):
        # MIS À JOUR Phase P2.29 : `director.py` appelle désormais
        # légitimement `prepare_activation()` ET `.prepare()`
        # (ControlledRealProviderActivationService) depuis
        # `prepare_real_generation_activation()` -- l'Explicit Human
        # Activation Entry Point, qui exige un `real_generation_
        # authorization` fourni par l'appelant (sans défaut), jamais
        # automatique. Vérifié désormais au niveau de la fonction
        # `run_video_mission()` uniquement pour `director.py` (le
        # chemin normal, qui doit rester sans autorité) ; inchangé
        # (fichier entier) pour les 4 autres composants.
        import inspect

        from director import AIDirector

        source = inspect.getsource(AIDirector.run_video_mission)
        tree = ast.parse(source.strip())
        called_in_run_video_mission = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn("prepare_activation", called_in_run_video_mission)
        self.assertNotIn("prepare", called_in_run_video_mission)

        for relative_path in (
            "agents/planner.py",
            "agents/video_agent.py",
            "agents/task_manager.py",
            "agents/activation_readiness.py",
        ):
            text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8-sig")
            tree = ast.parse(text)
            called = {
                node.func.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            }
            self.assertNotIn(
                "prepare_activation", called,
                f"{relative_path} must never call prepare_activation()",
            )
            self.assertNotIn(
                "prepare", called,
                f"{relative_path} must never call a .prepare() method "
                f"(ControlledRealProviderActivationService.prepare)",
            )


# ----------------------------------------------------------------------
# 26. Sole real caller reconfirmed
# ----------------------------------------------------------------------


class TestSoleRealCaller(unittest.TestCase):
    def test_generation_job_service_is_the_only_real_call_site(self):
        offenders = []
        for base in ("agents", "integrations"):
            for path in (PROJECT_ROOT / base).rglob("*.py"):
                if path.name in ("generation_job_service.py", "job_monitor.py"):
                    continue
                if "mock_provider.py" in str(path):
                    continue
                text = path.read_text(encoding="utf-8-sig")
                tree = ast.parse(text)
                for node in ast.walk(tree):
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "create_job"
                    ):
                        offenders.append(str(path.relative_to(PROJECT_ROOT)))
        director_text = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8-sig")
        director_tree = ast.parse(director_text)
        for node in ast.walk(director_tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "create_job"
            ):
                offenders.append("director.py")
        self.assertEqual(offenders, [])


# ----------------------------------------------------------------------
# 27. Direct provider call
# ----------------------------------------------------------------------


class TestDirectProviderCall(unittest.TestCase):
    def test_direct_create_job_still_raises_disabled_error(self):
        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(job_type="seedance_2_0", prompt="anything")
        fake_client.create_job.assert_not_called()


# ----------------------------------------------------------------------
# 28. Security scan (AST/regex, word-boundary, excluding legitimate docs)
# ----------------------------------------------------------------------


class TestSecurityScan(unittest.TestCase):
    TOKENS = (
        "REAL_GENERATION_ENABLED", "HIGGSFIELD_ENABLED", "ENABLE_REAL_GENERATION",
        "PRODUCTION_MODE", "FORCE_GENERATION", "force_generate", "generate_now",
        "skip_gate", "bypass", "auto_authorize", "auto_activation", "direct_provider",
    )
    EXCLUDED = {"agents/production_activation_boundary.py"}

    def test_no_forbidden_tokens_in_production_code(self):
        import re

        patterns = {t: re.compile(r"\b" + re.escape(t) + r"\b") for t in self.TOKENS}
        offenders = []
        for base in ("agents", "integrations"):
            for path in (PROJECT_ROOT / base).rglob("*.py"):
                rel = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
                if rel in self.EXCLUDED:
                    continue
                text = path.read_text(encoding="utf-8-sig")
                for tok, pat in patterns.items():
                    if pat.search(text):
                        offenders.append((rel, tok))
        director_text = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8-sig")
        for tok, pat in patterns.items():
            if pat.search(director_text):
                offenders.append(("director.py", tok))
        self.assertEqual(offenders, [])


# ----------------------------------------------------------------------
# 29. Video 005 integrity
# ----------------------------------------------------------------------


class TestVideo005Integrity(unittest.TestCase):
    def test_canonical_values_unchanged(self):
        self.assertEqual(C.request_id, "005")
        self.assertEqual(C.job_type, "seedance_2_0")
        self.assertEqual(C.duration, 15)
        self.assertEqual(C.resolution, "720p")
        self.assertEqual(C.aspect_ratio, "9:16")
        self.assertEqual(C.prompt_chars, 7284)
        self.assertEqual(C.prompt_lines, 265)
        self.assertEqual(
            C.prompt_sha256,
            "1c498617adb4603bcf2fc114a9cb9e8fe2219f09285adbff4d1e6c7a10a669e1",
        )
        self.assertEqual(
            C.avatar_master_sha256,
            "d293e41a63f66fd43afbebee3f7f9f1bd29143b465fa57a18ab4e1df5faf7280",
        )
        self.assertEqual(
            C.face_reference_sha256,
            "df83a97b71cff9a90191c19d15ff989228b9fef2e57c96cf7c76c68652e3a343",
        )

    def test_recomputed_live_from_disk_and_prompt_assembly(self):
        import hashlib

        prompt = _real_prompt()
        self.assertEqual(len(prompt), C.prompt_chars)
        self.assertEqual(len(prompt.splitlines()), C.prompt_lines)
        self.assertEqual(
            hashlib.sha256(prompt.encode("utf-8")).hexdigest(), C.prompt_sha256
        )

        def _sha256(path):
            h = hashlib.sha256()
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    h.update(chunk)
            return h.hexdigest()

        self.assertEqual(_sha256(REAL_AVATAR_PATH), C.avatar_master_sha256)
        self.assertEqual(_sha256(REAL_FACE_PATH), C.face_reference_sha256)


# ----------------------------------------------------------------------
# Director wiring (structural + fake-client, never real CLI)
# ----------------------------------------------------------------------


class TestDirectorWiring(unittest.TestCase):
    def test_build_default_chain_wires_provider_activation_service(self):
        director = AIDirector()
        try:
            chain = director._build_default_chain()
        except Exception as error:  # pragma: no cover
            self.fail(f"Construction should never touch the CLI: {error}")

        self.assertIsInstance(
            chain.provider_activation_service, ControlledRealProviderActivationService
        )
        self.assertIs(chain.job_service.provider_activation_service, chain.provider_activation_service)

    def test_run_video_mission_never_supplies_a_provider_activation_contract(self):
        import inspect

        source = inspect.getsource(AIDirector.run_video_mission)
        self.assertNotIn("provider_activation_contract", source)


if __name__ == "__main__":
    unittest.main()
