"""
Tests — Phase P2.26 : CONTROLLED REAL-PROVIDER ACTIVATION DESIGN &
PREFLIGHT.

Verrouille `agents/controlled_real_provider_activation.py` :
`ControlledRealProviderActivationContract` +
`ControlledRealProviderActivationService`. Ce module N'EST PAS câblé
dans `GenerationJobService.execute()` -- vérifié explicitement ici --
et n'appelle jamais `create_job()`. Toutes les données de coût/solde
utilisées proviennent de `MockHiggsfieldProvider` (sauf les tests
dédiés au Provider réel, avec un client factice MagicMock -- zéro
subprocess/réseau) ; les vérifications d'identité utilisent les VRAIS
fichiers/prompt de Video 005.
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
from agents.controlled_real_provider_activation import (
    ControlledRealProviderActivationContract,
    ControlledRealProviderActivationRejectedError,
    ControlledRealProviderActivationService,
)
from agents.critical_section_lock import FileCriticalSectionLock
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
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
    return GenerationRequest(**defaults)


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
        self.lock = FileCriticalSectionLock(tmp_dir)
        self.job_service = GenerationJobService(
            self.provider, self.gate, lock=self.lock,
            activation_service=self.activation_service,
        )
        self.provider_activation_service = ControlledRealProviderActivationService(
            self.gate, self.identity_lock, self.activation_service
        )

    def prepared(self, request):
        """Prépare le contrat P2.21 puis le contrat P2.26 à partir de lui."""
        rs_contract = self.activation_service.prepare_activation(request)
        pa_contract = self.provider_activation_service.prepare(request, rs_contract)
        return rs_contract, pa_contract


class P2_26_TestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_26_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def _stack(self, **kwargs) -> _Stack:
        return _Stack(self._tmp, **kwargs)


# ----------------------------------------------------------------------
# A. Contract valid for request 005
# ----------------------------------------------------------------------


class TestA_ValidContract(P2_26_TestCase):
    def test_valid_contract_prepares_and_validates_for_005(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)

        self.assertIsInstance(pa_contract, ControlledRealProviderActivationContract)
        self.assertEqual(pa_contract.request_id, "005")
        self.assertEqual(pa_contract.request_scoped_activation_id, rs_contract.activation_id)

        validated = stack.provider_activation_service.validate(
            request, rs_contract, pa_contract
        )
        self.assertIs(validated, pa_contract)


# ----------------------------------------------------------------------
# B-F. Identity mismatches -> BLOCK (data-driven)
# ----------------------------------------------------------------------


class TestBF_IdentityMismatches(P2_26_TestCase):
    def test_B_request_id_different_blocks(self):
        stack = self._stack()
        request_006 = _conforming_request(
            request_id="006", real_generation_authorization=_valid_auth("006")
        )
        # Rejeté dès la couche P2.21 (Identity Lock) -- la couche
        # P2.26 n'est jamais atteinte, il n'existe donc même pas de
        # RequestScopedActivationContract à partir duquel préparer un
        # ControlledRealProviderActivationContract pour 006.
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request_006)

    def test_C_model_different_blocks(self):
        stack = self._stack()
        request = _conforming_request(job_type="other_model")
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)

    def test_D_duration_different_blocks(self):
        stack = self._stack()
        request = _conforming_request(duration=5)
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)

    def test_E_resolution_different_blocks(self):
        stack = self._stack()
        request = _conforming_request(resolution="1080p")
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)

    def test_F_aspect_ratio_different_blocks(self):
        stack = self._stack()
        request = _conforming_request(aspect_ratio="16:9")
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)


# ----------------------------------------------------------------------
# G-I. Prompt/asset SHA mismatches -> BLOCK
# ----------------------------------------------------------------------


class TestGI_ContentMismatches(P2_26_TestCase):
    def test_G_prompt_sha_different_blocks_at_prepare(self):
        stack = self._stack()
        request = _conforming_request(prompt=_real_prompt() + " ")
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)

    def test_G2_prompt_mutated_between_rs_prepare_and_pa_validate_blocks(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)

        mutated = _conforming_request(prompt=request.prompt + " ")
        with self.assertRaises(ControlledRealProviderActivationRejectedError):
            stack.provider_activation_service.validate(mutated, rs_contract, pa_contract)

    def test_H_avatar_sha_different_blocks(self):
        stack = self._stack()
        request = _conforming_request(
            start_image=MediaReference(
                role="master_avatar", source=str(REAL_FACE_PATH), sha256=None
            )
        )
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)

    def test_I_face_sha_different_blocks(self):
        stack = self._stack()
        request = _conforming_request(
            image_references=(
                MediaReference(
                    role="face_reference", source=str(REAL_AVATAR_PATH), sha256=None
                ),
            )
        )
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)


# ----------------------------------------------------------------------
# J. Cost changed -> BLOCK / fresh recalculation
# ----------------------------------------------------------------------


class TestJ_CostFreshness(P2_26_TestCase):
    def test_cost_increase_between_prepare_and_validate_blocks(self):
        stack = self._stack(cost_per_job=10.0, available_credits=100.0)
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)

        stack.provider._cost_per_job = 1000.0  # coût frais, différent

        with self.assertRaises(ControlledRealProviderActivationRejectedError):
            stack.provider_activation_service.validate(request, rs_contract, pa_contract)

    def test_expected_cost_field_is_populated_for_observability_only(self):
        stack = self._stack(cost_per_job=67.5, available_credits=100.0)
        request = _conforming_request()
        _, pa_contract = stack.prepared(request)
        self.assertEqual(pa_contract.expected_cost_credits, 67.5)


# ----------------------------------------------------------------------
# K/L. Authorization absent / mismatch -> BLOCK
# ----------------------------------------------------------------------


class TestKL_AuthorizationChecks(P2_26_TestCase):
    def test_K_no_authorization_blocks_preparation(self):
        stack = self._stack()
        request = _conforming_request(real_generation_authorization=None)
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)

    def test_L_authorization_request_mismatch_blocks(self):
        stack = self._stack()
        request = _conforming_request(
            real_generation_authorization=_valid_auth("not-005")
        )
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)


# ----------------------------------------------------------------------
# M/N. Underlying activation absent / mismatched -> BLOCK
# ----------------------------------------------------------------------


class TestMN_UnderlyingActivationBinding(P2_26_TestCase):
    def test_M_no_request_scoped_contract_means_prepare_cannot_happen(self):
        # Il n'existe littéralement aucune API pour préparer un
        # ControlledRealProviderActivationContract sans fournir un
        # RequestScopedActivationContract -- vérifié structurellement.
        import inspect

        sig = inspect.signature(ControlledRealProviderActivationService.prepare)
        self.assertIn("request_scoped_contract", sig.parameters)
        self.assertNotEqual(
            sig.parameters["request_scoped_contract"].default, None
        )  # pas de défaut -- obligatoire

    def test_N_mismatched_request_scoped_contract_blocks_validation(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)

        other_rs_contract = stack.activation_service.prepare_activation(request)

        with self.assertRaises(ControlledRealProviderActivationRejectedError) as ctx:
            stack.provider_activation_service.validate(
                request, other_rs_contract, pa_contract
            )
        self.assertTrue(
            any("not transferable" in r for r in ctx.exception.reasons)
        )


# ----------------------------------------------------------------------
# O/P. Expired / consumed -> BLOCK
# ----------------------------------------------------------------------


class TestOP_ContractLifetime(P2_26_TestCase):
    def test_O_expired_contract_blocks(self):
        fake_time = {"t": 1000.0}
        provider = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=100.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
        rs_service = RequestScopedActivationService(gate, identity_lock)
        pa_service = ControlledRealProviderActivationService(
            gate, identity_lock, rs_service,
            max_age_seconds=60.0, clock=lambda: fake_time["t"],
        )

        request = _conforming_request()
        rs_contract = rs_service.prepare_activation(request)
        pa_contract = pa_service.prepare(request, rs_contract)
        fake_time["t"] += 61.0

        with self.assertRaises(ControlledRealProviderActivationRejectedError) as ctx:
            pa_service.validate(request, rs_contract, pa_contract)
        self.assertTrue(any("expired" in r for r in ctx.exception.reasons))

    def test_P_consumed_contract_blocks_second_validation(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)

        stack.provider_activation_service.validate(request, rs_contract, pa_contract)

        with self.assertRaises(ControlledRealProviderActivationRejectedError) as ctx:
            stack.provider_activation_service.validate(request, rs_contract, pa_contract)
        self.assertTrue(
            any("already been consumed" in r for r in ctx.exception.reasons)
        )

    def test_revoke_makes_a_still_valid_contract_immediately_unusable(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)

        stack.provider_activation_service.revoke(pa_contract)

        with self.assertRaises(ControlledRealProviderActivationRejectedError) as ctx:
            stack.provider_activation_service.validate(request, rs_contract, pa_contract)
        self.assertTrue(
            any("already been consumed" in r for r in ctx.exception.reasons)
        )


# ----------------------------------------------------------------------
# Q/R. Replay -> BLOCK
# ----------------------------------------------------------------------


class TestQR_Replay(P2_26_TestCase):
    def test_Q_already_executed_blocks_preparation(self):
        stack = self._stack()
        request = _conforming_request()
        stack.gate.mark_executed(request.request_id)
        with self.assertRaises(ActivationRejectedError) as ctx:
            stack.activation_service.prepare_activation(request)
        self.assertTrue(any("ALREADY_EXECUTED" in r for r in ctx.exception.reasons))

    def test_R_unknown_state_blocks_preparation_and_new_auth_does_not_clear_it(self):
        stack = self._stack()
        stack.gate.mark_unknown(C.request_id, reason="test")
        request = _conforming_request(
            real_generation_authorization=RealGenerationAuthorization(
                request_id=C.request_id, authorized_by_human=True, note="new"
            )
        )
        with self.assertRaises(ActivationRejectedError) as ctx:
            stack.activation_service.prepare_activation(request)
        self.assertTrue(
            any("EXECUTION_STATE_UNKNOWN" in r for r in ctx.exception.reasons)
        )


# ----------------------------------------------------------------------
# S. Budget insufficient -> BLOCK
# ----------------------------------------------------------------------


class TestS_Budget(P2_26_TestCase):
    def test_insufficient_budget_blocks_preparation(self):
        stack = self._stack(cost_per_job=67.5, available_credits=1.41)
        request = _conforming_request()
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)


# ----------------------------------------------------------------------
# T. Provider disabled -> BLOCK (even with everything else valid)
# ----------------------------------------------------------------------


class TestT_ProviderDisabled(P2_26_TestCase):
    def test_real_provider_blocks_validation_even_with_everything_else_valid(self):
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

        with self.assertRaises(ControlledRealProviderActivationRejectedError) as ctx:
            pa_service.prepare(request, rs_contract)
        self.assertTrue(
            any("HiggsfieldRealGenerationDisabledError" in r for r in ctx.exception.reasons)
        )
        fake_client.create_job.assert_not_called()


# ----------------------------------------------------------------------
# U/V/W. No global flag / no automatic authorization or activation
# ----------------------------------------------------------------------


class TestUVW_NoAutomaticAuthorityCreation(unittest.TestCase):
    def test_U_no_global_flag_attribute_anywhere_on_the_service(self):
        stack_provider = MockHiggsfieldProvider()
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(stack_provider, identity_lock=identity_lock)
        rs_service = RequestScopedActivationService(gate, identity_lock)
        pa_service = ControlledRealProviderActivationService(gate, identity_lock, rs_service)

        for attr in ("enabled", "real_generation_enabled", "production_mode", "force_generation"):
            self.assertFalse(hasattr(pa_service, attr))
            self.assertFalse(hasattr(ControlledRealProviderActivationService, attr))

    def test_V_authorization_never_auto_created_by_the_service(self):
        text = (
            PROJECT_ROOT / "agents/controlled_real_provider_activation.py"
        ).read_text(encoding="utf-8-sig")
        self.assertNotIn("RealGenerationAuthorization(", text)

    def test_W_prepare_never_calls_prepare_activation_automatically(self):
        text = (
            PROJECT_ROOT / "agents/controlled_real_provider_activation.py"
        ).read_text(encoding="utf-8-sig")
        tree = ast.parse(text)
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn("prepare_activation", called)
        # inspect_activation() (non consommant) est utilisé, jamais
        # validate_activation() (qui consommerait le contrat P2.21).
        self.assertIn("inspect_activation", called)
        self.assertNotIn("validate_activation", called)


# ----------------------------------------------------------------------
# X/Y. Readiness never triggers activation; activation never auto-executes
# ----------------------------------------------------------------------


class TestXY_LayerSeparation(P2_26_TestCase):
    def test_X_readiness_module_never_imports_this_new_service(self):
        text = (PROJECT_ROOT / "agents/activation_readiness.py").read_text(
            encoding="utf-8-sig"
        )
        self.assertNotIn("controlled_real_provider_activation", text)
        self.assertNotIn("ControlledRealProviderActivationService", text)

    def test_Y_valid_provider_contract_does_not_auto_execute(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)
        stack.provider_activation_service.validate(request, rs_contract, pa_contract)

        # Rien n'a jamais été exécuté : aucun job Mock n'existe.
        self.assertEqual(len(stack.provider._jobs), 0)


# ----------------------------------------------------------------------
# Z. Direct provider call remains blocked
# ----------------------------------------------------------------------


class TestZ_DirectProviderCallBlocked(unittest.TestCase):
    def test_direct_create_job_with_zero_guards_still_blocks(self):
        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(job_type="seedance_2_0", prompt="anything")
        fake_client.create_job.assert_not_called()


# ----------------------------------------------------------------------
# AA/AB/AC. No real network call / no credits / no create_job
# ----------------------------------------------------------------------


class TestAAABAC_NoRealEffects(P2_26_TestCase):
    def test_AA_no_real_higgsfield_call_anywhere_in_this_module(self):
        # Vérification par IMPORT RÉEL (ast.Import/ImportFrom), jamais
        # par sous-chaîne : le docstring du module mentionne
        # légitimement "HiggsfieldClient" en prose pour expliquer que
        # ce module ne l'importe PAS -- une simple recherche de
        # sous-chaîne y verrait un faux positif.
        text = (
            PROJECT_ROOT / "agents/controlled_real_provider_activation.py"
        ).read_text(encoding="utf-8-sig")
        tree = ast.parse(text)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.update(alias.name for alias in node.names)
                if node.module:
                    imported.add(node.module.split(".")[0])

        self.assertNotIn("HiggsfieldClient", imported)
        self.assertNotIn("subprocess", imported)
        self.assertNotIn("requests", imported)
        self.assertNotIn("socket", imported)

    def test_AB_no_credits_consumed_across_full_prepare_and_validate_cycle(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)
        stack.provider_activation_service.validate(request, rs_contract, pa_contract)
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_AC_module_never_calls_create_job(self):
        text = (
            PROJECT_ROOT / "agents/controlled_real_provider_activation.py"
        ).read_text(encoding="utf-8-sig")
        tree = ast.parse(text)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "create_job"
        ]
        self.assertEqual(calls, [])


# ----------------------------------------------------------------------
# AD. Balance unchanged
# ----------------------------------------------------------------------


class TestAD_BalanceUnchanged(P2_26_TestCase):
    def test_balance_unchanged_across_multiple_prepare_validate_cycles(self):
        stack = self._stack(cost_per_job=67.5, available_credits=1.41)
        before = stack.provider._available_credits
        request = _conforming_request()
        for _ in range(3):
            try:
                stack.activation_service.prepare_activation(request)
            except ActivationRejectedError:
                pass  # budget insuffisant -- attendu
        after = stack.provider._available_credits
        self.assertEqual(before, after)
        self.assertEqual(before, 1.41)


# ----------------------------------------------------------------------
# Adversarial attack scenarios (Étape 26)
# ----------------------------------------------------------------------


class TestAdversarialScenarios(P2_26_TestCase):
    def test_01_budget_becomes_insufficient_after_preparation(self):
        stack = self._stack(cost_per_job=10.0, available_credits=100.0)
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)
        stack.provider._available_credits = 1.41
        with self.assertRaises(ControlledRealProviderActivationRejectedError):
            stack.provider_activation_service.validate(request, rs_contract, pa_contract)

    def test_02_prompt_modified_after_preparation(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)
        mutated = _conforming_request(prompt=request.prompt + "x")
        with self.assertRaises(ControlledRealProviderActivationRejectedError):
            stack.provider_activation_service.validate(mutated, rs_contract, pa_contract)

    def test_03_asset_modified_after_preparation(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)
        mutated = _conforming_request(
            start_image=MediaReference(
                role="master_avatar", source=str(REAL_FACE_PATH), sha256=None
            )
        )
        with self.assertRaises(ControlledRealProviderActivationRejectedError):
            stack.provider_activation_service.validate(mutated, rs_contract, pa_contract)

    def test_04_authorization_replaced(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)
        swapped = _conforming_request(
            real_generation_authorization=_valid_auth("not-005")
        )
        with self.assertRaises(ControlledRealProviderActivationRejectedError):
            stack.provider_activation_service.validate(swapped, rs_contract, pa_contract)

    def test_05_activation_replaced_with_a_foreign_one(self):
        stack_a = self._stack()
        other_tmp = Path(tempfile.mkdtemp(prefix="p2_26_other_"))
        self.addCleanup(shutil.rmtree, other_tmp, ignore_errors=True)
        stack_b = _Stack(other_tmp)

        request = _conforming_request()
        _, pa_contract_a = stack_a.prepared(request)
        foreign_rs_contract = stack_b.activation_service.prepare_activation(request)

        with self.assertRaises(ControlledRealProviderActivationRejectedError):
            stack_a.provider_activation_service.validate(
                request, foreign_rs_contract, pa_contract_a
            )

    def test_06_activation_expired(self):
        fake_time = {"t": 1000.0}
        provider = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=100.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
        rs_service = RequestScopedActivationService(gate, identity_lock)
        pa_service = ControlledRealProviderActivationService(
            gate, identity_lock, rs_service, max_age_seconds=30.0, clock=lambda: fake_time["t"]
        )
        request = _conforming_request()
        rs_contract = rs_service.prepare_activation(request)
        pa_contract = pa_service.prepare(request, rs_contract)
        fake_time["t"] += 31.0
        with self.assertRaises(ControlledRealProviderActivationRejectedError):
            pa_service.validate(request, rs_contract, pa_contract)

    def test_07_request_id_modified_after_preparation(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)
        swapped = _conforming_request(
            request_id="006", real_generation_authorization=_valid_auth("006")
        )
        with self.assertRaises(ControlledRealProviderActivationRejectedError):
            stack.provider_activation_service.validate(swapped, rs_contract, pa_contract)

    def test_08_cost_modified_after_preparation(self):
        stack = self._stack(cost_per_job=10.0, available_credits=100.0)
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)
        stack.provider._cost_per_job = 500.0
        with self.assertRaises(ControlledRealProviderActivationRejectedError):
            stack.provider_activation_service.validate(request, rs_contract, pa_contract)

    def test_09_replay_state_becomes_unknown_after_preparation(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)
        stack.gate.mark_unknown(request.request_id, reason="race")
        with self.assertRaises(ControlledRealProviderActivationRejectedError):
            stack.provider_activation_service.validate(request, rs_contract, pa_contract)

    def test_10_replay_state_becomes_already_executed_after_preparation(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)
        stack.gate.mark_executed(request.request_id)
        with self.assertRaises(ControlledRealProviderActivationRejectedError):
            stack.provider_activation_service.validate(request, rs_contract, pa_contract)

    def test_11_provider_disabled_between_prepare_and_validate(self):
        # Simule un "downgrade" vers le Provider réel entre la
        # préparation et la validation (scénario improbable mais
        # explicitement testé -- fail-closed attendu).
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)

        fake_client = MagicMock()
        fake_client.estimate_cost.return_value = {"credits": 67.5}
        fake_client.account_status.return_value = {"credits": 1000.0}
        real_provider = HiggsfieldProvider(client=fake_client)
        stack.gate.provider = real_provider  # simulate a swapped provider

        with self.assertRaises(ControlledRealProviderActivationRejectedError) as ctx:
            stack.provider_activation_service.validate(request, rs_contract, pa_contract)
        self.assertTrue(
            any("HiggsfieldRealGenerationDisabledError" in r for r in ctx.exception.reasons)
        )

    def test_12_attempted_direct_call_bypassing_everything(self):
        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(job_type=C.job_type, prompt="bypass attempt")
        fake_client.create_job.assert_not_called()

    def test_13_attempted_global_enable_has_no_effect(self):
        stack = self._stack()
        # Tentative d'ajouter un flag global a posteriori -- ne doit
        # avoir AUCUN effet, car aucune branche du code ne le lit
        # jamais (vérifié structurellement ailleurs ; ici on prouve
        # que même le poser sur l'instance ne change rien).
        stack.provider_activation_service.enabled = True  # type: ignore[attr-defined]
        request = _conforming_request(real_generation_authorization=None)
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)

    def test_14_attempted_automatic_activation_via_readiness_has_no_route(self):
        from agents.activation_readiness import ActivationReadinessEvaluator

        stack = self._stack()
        evaluator = ActivationReadinessEvaluator(
            stack.gate, stack.identity_lock, stack.activation_service,
            job_service=stack.job_service,
        )
        request = _conforming_request()
        evaluator.evaluate(request)  # readiness only
        # Aucun contrat P2.21 ni P2.26 n'a été créé par cette seule évaluation.
        self.assertEqual(len(stack.activation_service._issued_at), 0)
        self.assertEqual(len(stack.provider_activation_service._issued_at), 0)


# ----------------------------------------------------------------------
# AE (partially): P2.24 and P2.25 are re-run as part of the mandated
# final regression sequence (see final report) -- not duplicated here
# as nested unittest invocations, which would be a fragile pattern.
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


class TestNotWiredIntoExecute(unittest.TestCase):
    """
    MIS À JOUR Phase P2.27 : au moment de P2.26, `GenerationJobService.
    execute()` n'acceptait aucun paramètre lié à ce module -- c'est
    précisément ce câblage que P2.27 a ensuite ajouté, délibérément et
    documenté (cf. agents/generation_job_service.py, section
    "CONTROLLED REAL-PROVIDER ACTIVATION WIRING"), suivant exactement
    le même schéma que P2.21 -> P2.22. Ce n'est plus l'invariant
    pertinent : ce qui compte désormais, et que ce test vérifie, est
    que le paramètre reste FACULTATIF (défaut `None`, jamais créé
    implicitement) et que le Provider réel reste inconditionnellement
    désactivé même une fois ce câblage en place (cf.
    tests/test_phase_p2_27_controlled_provider_activation_integration.py).
    """

    def test_generation_job_service_execute_has_an_optional_provider_contract_parameter(self):
        import inspect

        sig = inspect.signature(GenerationJobService.execute)
        self.assertIn("provider_activation_contract", sig.parameters)
        self.assertIsNone(sig.parameters["provider_activation_contract"].default)

    def test_generation_job_service_module_now_imports_this_module_for_wiring(self):
        text = (PROJECT_ROOT / "agents/generation_job_service.py").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("controlled_real_provider_activation", text)


if __name__ == "__main__":
    unittest.main()
