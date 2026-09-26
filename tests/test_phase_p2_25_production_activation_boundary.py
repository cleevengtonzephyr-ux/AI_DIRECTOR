"""
Tests — Phase P2.25 : PRODUCTION ACTIVATION BOUNDARY CONTRACT.

Ce fichier NE RÉ-IMPLÉMENTE PAS les tests déjà couverts en profondeur
par P2.20-P2.24 (verrou, crash/UNKNOWN, contrat d'activation, rapport
final, readiness) -- il les RECONFIRME de façon compacte tout en
ajoutant les angles genuinely NOUVEAUX de P2.25 :

- Le contrat documentaire `agents/production_activation_boundary.py`
  ne doit jamais dériver de la réalité du code (chaque référence de
  `FRESH_CHECK_IMPLEMENTED_BY` doit pointer vers un attribut qui
  existe RÉELLEMENT).
- Direct-call protection EXPLICITE pour LES CINQ composants nommés
  par le rapport P2.25 (Director/Planner/VideoAgent/TaskManager/
  FinalReportService) -- aucun n'importe ni n'appelle jamais
  `provider.create_job()`.
- `ActivationReadinessEvaluator` (Phase P2.24) est désormais
  explicitement inclus dans l'audit "jamais de prepare_activation()
  automatique" (absent du fichier P2.24 lui-même, puisqu'il n'existait
  pas encore quand ce module a été écrit).
- Un appel DIRECT à `create_job()` (sans passer par AUCUN garde-fou)
  reste bloqué par la seule protection qui ne peut jamais être
  contournée : le Provider réel lui-même.

Toutes les données Higgsfield (coût, solde) utilisées ici sont
simulées via MockHiggsfieldProvider, sauf les tests explicitement
dédiés au Provider réel (avec un client factice, MagicMock -- zéro
subprocess/réseau). AUCUN test de ce fichier n'invoque le vrai CLI
Higgsfield.
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
from agents.critical_section_lock import CriticalSectionBusyError, FileCriticalSectionLock
from agents.final_report_service import FinalReportService
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from agents.generation_job_service import (
    GenerationJobActivationRejectedError,
    GenerationJobExecutionError,
    GenerationJobService,
)
from agents.production_activation_boundary import (
    FORBIDDEN_GLOBAL_AUTHORITY_TOKENS,
    FRESH_CHECK_IMPLEMENTED_BY,
    FRESH_CHECK_REQUIREMENTS,
    PRODUCTION_ACTIVATION_BOUNDARY,
    AuthorityLevel,
)
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


class _WiredStack:
    def __init__(self, tmp_dir: Path, cost_per_job=10.0, available_credits=100.0):
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
            self.provider,
            self.gate,
            lock=self.lock,
            activation_service=self.activation_service,
        )
        self.evaluator = ActivationReadinessEvaluator(
            self.gate, self.identity_lock, self.activation_service,
            job_service=self.job_service,
        )
        self.report_service = FinalReportService(
            self.provider, self.gate, job_service=self.job_service
        )


class P2_25_TestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_25_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def _stack(self, **kwargs) -> _WiredStack:
        return _WiredStack(self._tmp, **kwargs)


# ----------------------------------------------------------------------
# Boundary contract self-consistency (never allowed to drift from reality)
# ----------------------------------------------------------------------


class TestBoundaryContractConsistency(unittest.TestCase):
    def test_fresh_check_implemented_by_covers_every_requirement(self):
        self.assertEqual(
            set(FRESH_CHECK_REQUIREMENTS), set(FRESH_CHECK_IMPLEMENTED_BY.keys())
        )

    def test_every_referenced_mechanism_actually_exists(self):
        import importlib

        for requirement, dotted_path in FRESH_CHECK_IMPLEMENTED_BY.items():
            module_path, _, remainder = dotted_path.rpartition(".")
            module_path, _, cls_name = module_path.rpartition(".")
            module = importlib.import_module(module_path)
            cls = getattr(module, cls_name, None)
            self.assertIsNotNone(
                cls, f"{requirement}: class '{cls_name}' not found in {module_path}"
            )
            self.assertTrue(
                hasattr(cls, remainder),
                f"{requirement}: '{remainder}' not found on {cls_name} "
                f"({dotted_path}) -- documentation has drifted from the code.",
            )

    def test_authority_levels_are_the_four_documented_ones_in_order(self):
        self.assertEqual(
            PRODUCTION_ACTIVATION_BOUNDARY.authority_levels,
            (
                AuthorityLevel.TECHNICAL_READINESS,
                AuthorityLevel.HUMAN_AUTHORIZATION,
                AuthorityLevel.REQUEST_SCOPED_ACTIVATION,
                AuthorityLevel.EXECUTION,
            ),
        )

    def test_real_provider_currently_disabled_flag_matches_reality(self):
        # Le contrat AFFIRME que le Provider réel est désactivé --
        # vérifié ici contre le VRAI comportement, jamais pris pour
        # acquis.
        self.assertTrue(PRODUCTION_ACTIVATION_BOUNDARY.real_provider_currently_disabled)
        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(job_type="seedance_2_0", prompt="x")
        fake_client.create_job.assert_not_called()


# ----------------------------------------------------------------------
# A/B/C/D. Authority level separation
# ----------------------------------------------------------------------


class TestABCD_AuthorityLevelSeparation(P2_25_TestCase):
    def test_A_readiness_positive_is_not_authorization(self):
        stack = self._stack()
        request = _conforming_request(real_generation_authorization=None)
        report = stack.evaluator.evaluate(request)
        # Toutes les autres dimensions peuvent être vertes...
        self.assertTrue(report.technical_ready)
        self.assertTrue(report.budget_ready)
        # ... mais AUCUNE autorisation n'existe, et readiness n'en a
        # créé aucune.
        self.assertFalse(report.authorization_ready)
        self.assertIsNone(request.real_generation_authorization)
        self.assertEqual(report.decision, "NOT_READY")

    def test_B_no_authorization_makes_activation_impossible(self):
        stack = self._stack()
        request = _conforming_request(real_generation_authorization=None)
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)

    def test_C_valid_authorization_does_not_auto_create_activation(self):
        stack = self._stack()
        request = _conforming_request()  # has valid authorization
        report = stack.evaluator.evaluate(request)  # no contract passed
        self.assertTrue(report.authorization_ready)
        self.assertFalse(report.activation_ready)
        self.assertEqual(len(stack.activation_service._issued_at), 0)

    def test_D_valid_activation_does_not_auto_execute(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)
        # Le contrat existe, valide -- mais execute() n'a jamais été
        # appelé : aucun job ne doit exister.
        self.assertEqual(len(stack.provider._jobs), 0)
        # inspect_activation() (readiness) confirme même sa validité
        # sans jamais rien exécuter.
        self.assertEqual(
            stack.activation_service.inspect_activation(request, contract), []
        )
        self.assertEqual(len(stack.provider._jobs), 0)


# ----------------------------------------------------------------------
# E-L. Mutation matrix -> BLOCK (data-driven, avoids 8 near-duplicate tests)
# ----------------------------------------------------------------------


class TestEL_MutationMatrix(P2_25_TestCase):
    def _assert_mutation_blocks(self, **overrides):
        stack = self._stack()
        request = _conforming_request(**overrides)
        report = stack.evaluator.evaluate(request)
        self.assertEqual(report.decision, "NOT_READY")

        with self.assertRaises(Exception):
            stack.job_service.execute(request, interval_seconds=0)
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_E_prompt_mutation_blocks(self):
        self._assert_mutation_blocks(prompt=_real_prompt() + " ")

    def test_F_avatar_mutation_blocks(self):
        self._assert_mutation_blocks(
            start_image=MediaReference(
                role="master_avatar", source=str(REAL_FACE_PATH), sha256=None
            )
        )

    def test_G_face_reference_mutation_blocks(self):
        self._assert_mutation_blocks(
            image_references=(
                MediaReference(
                    role="face_reference", source=str(REAL_AVATAR_PATH), sha256=None
                ),
            )
        )

    def test_H_request_mismatch_blocks(self):
        self._assert_mutation_blocks(
            request_id="006", real_generation_authorization=_valid_auth("006")
        )

    def test_I_model_mismatch_blocks(self):
        self._assert_mutation_blocks(job_type="other_model")

    def test_J_duration_mismatch_blocks(self):
        self._assert_mutation_blocks(duration=5)

    def test_K_resolution_mismatch_blocks(self):
        self._assert_mutation_blocks(resolution="1080p")

    def test_L_aspect_ratio_mismatch_blocks(self):
        self._assert_mutation_blocks(aspect_ratio="16:9")


# ----------------------------------------------------------------------
# M/N. Cost / balance freshness
# ----------------------------------------------------------------------


class TestMN_CostAndBalanceFreshness(P2_25_TestCase):
    def test_M_cost_change_is_recalculated_fresh_never_cached(self):
        stack = self._stack(cost_per_job=10.0, available_credits=100.0)
        request = _conforming_request()

        first = stack.evaluator.evaluate(request)
        self.assertTrue(first.budget_ready)

        stack.provider._cost_per_job = 1000.0  # coût frais, différent
        second = stack.evaluator.evaluate(request)
        self.assertFalse(second.budget_ready)

    def test_N_insufficient_balance_blocks(self):
        stack = self._stack(cost_per_job=67.5, available_credits=1.41)
        report = stack.evaluator.evaluate(_conforming_request())
        self.assertFalse(report.budget_ready)
        self.assertEqual(report.decision, "NOT_READY")


# ----------------------------------------------------------------------
# O/P. Replay / UNKNOWN
# ----------------------------------------------------------------------


class TestOP_ReplayAndUnknown(P2_25_TestCase):
    def test_O_already_executed_blocks(self):
        stack = self._stack()
        request = _conforming_request()
        stack.gate.mark_executed(request.request_id)
        report = stack.evaluator.evaluate(request)
        self.assertFalse(report.replay_safe)
        self.assertEqual(report.decision, "NOT_READY")

        with self.assertRaises(GenerationJobExecutionError) as ctx:
            stack.job_service.execute(request, interval_seconds=0)
        self.assertEqual(
            ctx.exception.approval.decision, GenerationApprovalDecision.ALREADY_EXECUTED
        )

    def test_P_unknown_state_blocks_and_new_authorization_does_not_clear_it(self):
        stack = self._stack()
        stack.gate.mark_unknown(C.request_id, reason="test")

        fresh_request = _conforming_request(
            real_generation_authorization=RealGenerationAuthorization(
                request_id=C.request_id, authorized_by_human=True, note="brand new"
            )
        )
        report = stack.evaluator.evaluate(fresh_request)
        self.assertFalse(report.replay_safe)
        self.assertEqual(report.decision, "NOT_READY")

        with self.assertRaises(GenerationJobExecutionError) as ctx:
            stack.job_service.execute(fresh_request, interval_seconds=0)
        self.assertEqual(
            ctx.exception.approval.decision,
            GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN,
        )


# ----------------------------------------------------------------------
# Q/R/S/T. Activation lifetime & authorization binding
# ----------------------------------------------------------------------


class TestQRST_ActivationLifetimeAndBinding(P2_25_TestCase):
    def test_Q_expired_activation_blocks(self):
        fake_time = {"t": 1000.0}
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
        activation_service = RequestScopedActivationService(
            gate, identity_lock, max_age_seconds=60.0, clock=lambda: fake_time["t"]
        )
        lock = FileCriticalSectionLock(self._tmp)
        job_service = GenerationJobService(
            provider, gate, lock=lock, activation_service=activation_service
        )

        request = _conforming_request()
        contract = activation_service.prepare_activation(request)
        fake_time["t"] += 61.0

        with self.assertRaises(GenerationJobActivationRejectedError):
            job_service.execute(request, activation_contract=contract, interval_seconds=0)
        self.assertEqual(len(provider._jobs), 0)

    def test_R_consumed_activation_blocks(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)
        stack.activation_service.validate_activation(request, contract)  # consume

        with self.assertRaises(GenerationJobActivationRejectedError):
            stack.job_service.execute(
                request, activation_contract=contract, interval_seconds=0
            )
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_S_foreign_activation_contract_blocks(self):
        stack_a = self._stack()
        other_tmp = Path(tempfile.mkdtemp(prefix="p2_25_other_"))
        self.addCleanup(shutil.rmtree, other_tmp, ignore_errors=True)
        stack_b = _WiredStack(other_tmp)

        request = _conforming_request()
        foreign_contract = stack_b.activation_service.prepare_activation(request)

        with self.assertRaises(GenerationJobActivationRejectedError):
            stack_a.job_service.execute(
                request, activation_contract=foreign_contract, interval_seconds=0
            )
        self.assertEqual(len(stack_a.provider._jobs), 0)

    def test_T_wrong_authorization_binding_blocks(self):
        stack = self._stack()
        request = _conforming_request(
            real_generation_authorization=_valid_auth("not-005")
        )
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)
        with self.assertRaises(GenerationJobExecutionError):
            stack.job_service.execute(request, interval_seconds=0)


# ----------------------------------------------------------------------
# U. Direct provider call still blocks (no guard involved at all)
# ----------------------------------------------------------------------


class TestU_DirectProviderCallBlocks(unittest.TestCase):
    def test_calling_real_create_job_directly_with_zero_guards_still_blocks(self):
        # Aucun Gate, aucun Lock, aucune Activation -- juste le
        # Provider réel, appelé directement. La SEULE protection qui
        # ne peut jamais être contournée doit encore tenir.
        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(job_type="seedance_2_0", prompt="anything")

        fake_client.create_job.assert_not_called()


# ----------------------------------------------------------------------
# Direct-call protection audit (Étape 16) -- five named components
# ----------------------------------------------------------------------


class TestDirectCallProtectionAudit(unittest.TestCase):
    """
    Audite, PAR NOM, les cinq chemins explicitement listés par le
    rapport P2.25 : Director / Planner / VideoAgent / TaskManager /
    FinalReportService -> Provider. Aucun ne doit appeler
    `create_job()` directement (AST : seul un appel EN SOURCE compte,
    jamais une simple mention dans un docstring/commentaire).
    """

    FILES_UNDER_AUDIT = {
        "Director": "director.py",
        "Planner": "agents/planner.py",
        "VideoAgent": "agents/video_agent.py",
        "TaskManager": "agents/task_manager.py",
        "FinalReportService": "agents/final_report_service.py",
    }

    def test_none_of_the_five_named_components_call_create_job_directly(self):
        offenders = {}
        for component, relative_path in self.FILES_UNDER_AUDIT.items():
            text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8-sig")
            tree = ast.parse(text)
            calls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "create_job"
            ]
            if calls:
                offenders[component] = len(calls)

        self.assertEqual(offenders, {}, f"unexpected direct create_job() calls: {offenders}")

    def test_planner_holds_a_real_client_but_only_for_read_only_workflow_lookup(self):
        # VideoPlanner (V1) construit bien un HiggsfieldClient réel --
        # classé et confirmé ici comme lecture seule (get_workflow),
        # jamais create_job, jamais un nouveau chemin de production.
        text = (PROJECT_ROOT / "agents/planner.py").read_text(encoding="utf-8-sig")
        self.assertIn("HiggsfieldClient", text)
        tree = ast.parse(text)
        client_calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "higgsfield"
        }
        self.assertEqual(client_calls, {"get_workflow"})

    @staticmethod
    def _imported_names(relative_path: str) -> set:
        """Noms RÉELLEMENT importés (ast.Import/ImportFrom) -- jamais
        une simple mention dans un docstring/commentaire expliquant
        pourquoi ce module N'importe PAS quelque chose."""

        text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8-sig")
        tree = ast.parse(text)
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.update(alias.name for alias in node.names)
        return names

    def test_video_agent_and_task_manager_never_import_a_provider_or_client(self):
        for relative_path in ("agents/video_agent.py", "agents/task_manager.py"):
            imported = self._imported_names(relative_path)
            self.assertNotIn("HiggsfieldClient", imported)
            self.assertNotIn("HiggsfieldProvider", imported)

    def test_final_report_service_delegates_execution_entirely_to_job_service(self):
        imported = self._imported_names("agents/final_report_service.py")
        self.assertNotIn("HiggsfieldClient", imported)

        # Le seul point d'exécution doit être self.job_service.execute(...).
        text = (PROJECT_ROOT / "agents/final_report_service.py").read_text(
            encoding="utf-8-sig"
        )
        tree = ast.parse(text)
        execute_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
        ]
        self.assertEqual(len(execute_calls), 1)
        self.assertEqual(execute_calls[0].func.value.attr, "job_service")


# ----------------------------------------------------------------------
# V. Provider disabled, full stack, all other conditions simulated valid
# ----------------------------------------------------------------------


class TestV_ProviderDisabledWithFullStackValid(P2_25_TestCase):
    def test_all_conditions_valid_except_provider_still_blocks(self):
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
        activation_service = RequestScopedActivationService(gate, identity_lock)
        lock = FileCriticalSectionLock(self._tmp)
        job_service = GenerationJobService(
            real_provider, gate, lock=lock, activation_service=activation_service
        )
        evaluator = ActivationReadinessEvaluator(
            gate, identity_lock, activation_service, job_service=job_service
        )

        request = _conforming_request()
        contract = activation_service.prepare_activation(request)
        report = evaluator.evaluate(request, activation_contract=contract)

        # technical/identity/prompt/asset/budget/authorization/activation
        # /replay/crash all green...
        self.assertTrue(report.technical_ready)
        self.assertTrue(report.request_identity_ready)
        self.assertTrue(report.prompt_ready)
        self.assertTrue(report.asset_ready)
        self.assertTrue(report.budget_ready)
        self.assertTrue(report.authorization_ready)
        self.assertTrue(report.activation_ready)
        self.assertTrue(report.replay_safe)
        self.assertTrue(report.crash_safe)
        # ... but the provider is not, and the overall decision reflects it.
        self.assertFalse(report.provider_ready)
        self.assertEqual(report.decision, "NOT_READY")

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            job_service.execute(request, activation_contract=contract, interval_seconds=0)
        fake_client.create_job.assert_not_called()


# ----------------------------------------------------------------------
# W/X. Readiness never creates authorization/activation
# ----------------------------------------------------------------------


class TestWX_ReadinessNeverCreates(P2_25_TestCase):
    def test_W_readiness_never_creates_authorization(self):
        stack = self._stack()
        request = _conforming_request(real_generation_authorization=None)
        stack.evaluator.evaluate(request)
        self.assertIsNone(request.real_generation_authorization)

    def test_X_readiness_never_creates_activation(self):
        stack = self._stack()
        request = _conforming_request()
        stack.evaluator.evaluate(request)
        self.assertEqual(len(stack.activation_service._issued_at), 0)


# ----------------------------------------------------------------------
# Y. No automatic prepare_activation anywhere, including the readiness evaluator
# ----------------------------------------------------------------------


class TestY_NoAutomaticPrepareActivation(unittest.TestCase):
    @staticmethod
    def _called_attribute_names(relative_path: str) -> set:
        """Noms de méthode RÉELLEMENT appelés (ast.Call sur un
        ast.Attribute) -- jamais une simple mention textuelle dans un
        docstring expliquant que cette méthode N'est PAS appelée."""

        text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8-sig")
        tree = ast.parse(text)
        return {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

    def test_prepare_activation_never_called_by_any_named_component(self):
        # MIS À JOUR Phase P2.29 : `director.py` appelle désormais
        # légitimement `prepare_activation()` depuis
        # `prepare_real_generation_activation()` (Explicit Human
        # Activation Entry Point, requiert un `real_generation_
        # authorization` fourni par l'appelant, sans défaut). Vérifié
        # ici au niveau du FICHIER ENTIER pour les 4 autres
        # composants (inchangé), et au niveau de la FONCTION
        # `run_video_mission()` uniquement pour `director.py` -- le
        # chemin normal, lui, ne doit toujours jamais l'appeler.
        import ast
        import inspect

        from director import AIDirector

        source = inspect.getsource(AIDirector.run_video_mission)
        tree = ast.parse(source.strip())
        called_in_run_video_mission = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn(
            "prepare_activation", called_in_run_video_mission,
            "run_video_mission() must never call prepare_activation()",
        )

        for relative_path in (
            "agents/planner.py",
            "agents/video_agent.py",
            "agents/task_manager.py",
            "agents/activation_readiness.py",
        ):
            called = self._called_attribute_names(relative_path)
            self.assertNotIn(
                "prepare_activation",
                called,
                f"{relative_path} must never call prepare_activation()",
            )

    def test_activation_readiness_uses_inspect_not_validate_or_prepare(self):
        called = self._called_attribute_names("agents/activation_readiness.py")
        self.assertIn("inspect_activation", called)
        self.assertNotIn("validate_activation", called)
        self.assertNotIn("prepare_activation", called)


# ----------------------------------------------------------------------
# Z. No global activation flag (fresh grep, this phase's token list)
# ----------------------------------------------------------------------


class TestZ_NoGlobalActivationFlag(unittest.TestCase):
    def test_no_forbidden_tokens_anywhere_in_production_code(self):
        # `production_activation_boundary.py` est volontairement
        # exclu : c'est LUI qui déclare la liste des motifs interdits
        # (FORBIDDEN_GLOBAL_AUTHORITY_TOKENS) comme littéraux de
        # chaîne à des fins de documentation/audit -- leur présence
        # ici est le contrat négatif lui-même, jamais un usage réel.
        import re

        excluded = {"agents/production_activation_boundary.py"}

        # Correspondance sur FRONTIÈRE DE MOT : une simple sous-chaîne
        # produirait un faux positif, ex. "PRODUCTION_MODE" est une
        # sous-chaîne de la constante légitime et préexistante
        # `PRODUCTION_MODEL` (agents/production_model.py, Phase P2.2).
        patterns = {
            token: re.compile(r"\b" + re.escape(token) + r"\b")
            for token in FORBIDDEN_GLOBAL_AUTHORITY_TOKENS
        }

        offenders = []
        for base in ("agents", "integrations"):
            for path in (PROJECT_ROOT / base).rglob("*.py"):
                relative = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
                if relative in excluded:
                    continue
                text = path.read_text(encoding="utf-8-sig")
                for token, pattern in patterns.items():
                    if pattern.search(text):
                        offenders.append((relative, token))

        director_text = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8-sig")
        for token, pattern in patterns.items():
            if pattern.search(director_text):
                offenders.append(("director.py", token))

        self.assertEqual(offenders, [], f"forbidden tokens found: {offenders}")


# ----------------------------------------------------------------------
# AA/AB/AC/AD. No real create_job / network / credits / balance change
# ----------------------------------------------------------------------


class TestAAABACAD_NoRealEffectsWhatsoever(P2_25_TestCase):
    def test_AA_generation_job_service_is_the_only_real_call_site(self):
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
        self.assertEqual(offenders, [])

    def test_AB_no_network_or_client_import_in_new_p2_25_modules(self):
        text = (PROJECT_ROOT / "agents/production_activation_boundary.py").read_text(
            encoding="utf-8-sig"
        )
        self.assertNotIn("requests", text)
        self.assertNotIn("socket", text)
        self.assertNotIn("HiggsfieldClient", text)
        self.assertNotIn("subprocess", text)

    def test_AC_no_credits_consumed_across_a_full_readiness_and_inspection_cycle(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)
        stack.evaluator.evaluate(request, activation_contract=contract)
        stack.activation_service.inspect_activation(request, contract)
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_AD_balance_unchanged_across_repeated_evaluations(self):
        stack = self._stack(cost_per_job=67.5, available_credits=1.41)
        before = stack.provider._available_credits
        for _ in range(5):
            stack.evaluator.evaluate(_conforming_request())
        after = stack.provider._available_credits
        self.assertEqual(before, after)
        self.assertEqual(before, 1.41)


# ----------------------------------------------------------------------
# Video 005 integrity re-check
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


if __name__ == "__main__":
    unittest.main()
