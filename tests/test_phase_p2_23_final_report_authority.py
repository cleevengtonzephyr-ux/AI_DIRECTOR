"""
Tests — Phase P2.23 : FINAL REPORT TRUTHFULNESS & EXPLICIT ACTIVATION
AUTHORITY BOUNDARY.

Deux axes verrouillés ici :

1. `FinalReport` distingue désormais explicitement TECHNICAL_GATE_
   DECISION (`approval_decision`, existant, réutilisé) /
   ACTIVATION_DECISION (`activation_decision`, nouveau) / EXECUTION_
   STATE (`execution_state`, propriété calculée) / JOB_CREATED
   (`job_created`, existant) / REAL_PROVIDER_CALLED
   (`real_provider_called`, nouveau) -- cf. agents/final_report_service.py.
   Un `approval_decision == APPROVED` ne peut plus, à lui seul, être lu
   comme "génération effectuée" ou "activation accordée".

2. `RequestScopedActivationService.prepare_activation()` vérifie
   désormais l'Activation Authority (RealGenerationAuthorization) EN
   PREMIER, indépendamment du Gate -- jamais appelée automatiquement
   par le Director/Planner (cf. agents/activation_contract.py).

Utilise le VRAI `FileCriticalSectionLock` et les VRAIS fichiers/prompt
de Video 005, comme P2.22. Aucun mock n'est utilisé pour prétendre
qu'une génération réelle a eu lieu.
"""

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
    GenerationJobService,
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
    return bind_request(GenerationRequest(**defaults))


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
        self.report_service = FinalReportService(
            self.provider, self.gate, job_service=self.job_service
        )


class P2_23_TestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_23_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def _stack(self, **kwargs) -> _WiredStack:
        return _WiredStack(self._tmp, **kwargs)


# ----------------------------------------------------------------------
# A/B. Gate rejected reports (Cas 1)
# ----------------------------------------------------------------------


class TestAB_GateRejectedReports(P2_23_TestCase):
    def test_gate_blocked_report_is_fully_truthful(self):
        stack = self._stack(cost_per_job=50.0, available_credits=1.41)
        report = stack.report_service.generate(_conforming_request(), interval_seconds=0)

        self.assertEqual(report.approval_decision, GenerationApprovalDecision.BLOCKED)
        self.assertEqual(report.activation_decision, ActivationDecision.NOT_EVALUATED)
        self.assertEqual(report.execution_state, "NOT_EXECUTED")
        self.assertFalse(report.job_created)
        self.assertFalse(report.real_provider_called)
        self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)

    def test_gate_needs_approval_report_is_fully_truthful(self):
        stack = self._stack()
        report = stack.report_service.generate(
            _conforming_request(approved=False), interval_seconds=0
        )

        self.assertEqual(
            report.approval_decision, GenerationApprovalDecision.NEEDS_APPROVAL
        )
        self.assertEqual(report.activation_decision, ActivationDecision.NOT_EVALUATED)
        self.assertEqual(report.execution_state, "NOT_EXECUTED")
        self.assertFalse(report.job_created)
        self.assertFalse(report.real_provider_called)


# ----------------------------------------------------------------------
# C. Gate APPROVED but activation rejected (Cas 2)
# ----------------------------------------------------------------------


class TestC_GateApprovedActivationRejected(P2_23_TestCase):
    def test_report_distinguishes_technical_approval_from_activation_rejection(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)
        stack.activation_service.validate_activation(request, contract)  # consume it

        report = stack.report_service.generate(
            request, activation_contract=contract, interval_seconds=0
        )

        self.assertEqual(report.approval_decision, GenerationApprovalDecision.APPROVED)
        self.assertEqual(report.activation_decision, ActivationDecision.REJECTED)
        self.assertTrue(
            any("already been consumed" in r for r in report.activation_reasons)
        )
        self.assertFalse(report.job_created)
        self.assertFalse(report.real_provider_called)
        self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)
        self.assertEqual(report.execution_state, "NOT_EXECUTED")
        self.assertIn("Gate APPROVED but activation REJECTED", report.summary)


# ----------------------------------------------------------------------
# D. Gate APPROVED + activation APPROVED + provider disabled (Cas 3)
# ----------------------------------------------------------------------


class TestD_ProviderDisabledNeverReportsExecutedPass(P2_23_TestCase):
    def test_real_provider_disabled_still_propagates_uncaught_never_a_report(self):
        # Décision architecturale P2.23, documentée dans
        # agents/final_report_service.py : ne JAMAIS transformer
        # HiggsfieldRealGenerationDisabledError en un rapport
        # NOT_EXECUTED "propre" -- l'ABSENCE de rapport reste la
        # garantie la plus forte qu'aucun rapport ne puisse jamais
        # afficher EXECUTED_PASS dans ce cas. Reconfirme
        # tests/test_final_report_service.py::
        # test_real_provider_protection_propagates_uncaught, avec
        # cette fois toute la pile P2.21/P2.22 (contrat + lock réel).
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
        report_service = FinalReportService(real_provider, gate, job_service=job_service)

        request = _conforming_request()
        contract = activation_service.prepare_activation(request)
        self.assertEqual(
            gate.evaluate(request).decision, GenerationApprovalDecision.APPROVED
        )

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            report_service.generate(
                request, activation_contract=contract, interval_seconds=0
            )

        fake_client.create_job.assert_not_called()
        self.assertFalse((self._tmp / "005.lock").exists())


# ----------------------------------------------------------------------
# E/F/G/H. Report field correctness
# ----------------------------------------------------------------------


class TestEFGH_ReportFieldCorrectness(P2_23_TestCase):
    def test_approval_decision_alone_never_implies_generation(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)
        stack.activation_service.validate_activation(request, contract)

        report = stack.report_service.generate(
            request, activation_contract=contract, interval_seconds=0
        )
        # APPROVED, mais RIEN n'a été créé -- prouvé par les AUTRES
        # champs, jamais déductible de approval_decision seul.
        self.assertEqual(report.approval_decision, GenerationApprovalDecision.APPROVED)
        self.assertFalse(report.job_created)
        self.assertNotEqual(report.status, FinalReportStatus.EXECUTED_PASS)

    def test_activation_decision_explicitly_represented_on_success(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)

        report = stack.report_service.generate(
            request, activation_contract=contract, interval_seconds=0
        )
        self.assertEqual(report.activation_decision, ActivationDecision.APPROVED)
        self.assertEqual(report.execution_state, "EXECUTED")
        self.assertTrue(report.job_created)
        # CORRIGÉ (audit post-P2.27) : `stack` utilise
        # MockHiggsfieldProvider -- `real_provider_called` doit donc
        # être False. `job_created=True` seul ne prouve jamais qu'il
        # s'agit du vrai HiggsfieldProvider (cf.
        # agents/final_report_service.py::_is_real_provider()).
        self.assertFalse(report.real_provider_called)

    def test_job_created_false_and_real_provider_called_false_when_never_reached(self):
        stack = self._stack(cost_per_job=50.0, available_credits=1.41)
        report = stack.report_service.generate(_conforming_request(), interval_seconds=0)
        self.assertFalse(report.job_created)
        self.assertFalse(report.real_provider_called)


# ----------------------------------------------------------------------
# I/J. UNKNOWN / ALREADY_EXECUTED representation
# ----------------------------------------------------------------------


class TestIJ_UnknownAndAlreadyExecutedRepresentation(P2_23_TestCase):
    def test_unknown_state_represented_distinctly_from_not_executed(self):
        stack = self._stack()
        request = _conforming_request()
        stack.gate.mark_unknown(request.request_id, reason="test")

        report = stack.report_service.generate(request, interval_seconds=0)

        self.assertEqual(
            report.approval_decision, GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN
        )
        self.assertEqual(report.execution_state, "EXECUTION_STATE_UNKNOWN")
        self.assertNotEqual(report.execution_state, "NOT_EXECUTED")
        self.assertFalse(report.job_created)

    def test_already_executed_represented_as_not_executed_not_unknown(self):
        stack = self._stack()
        request = _conforming_request()
        stack.gate.mark_executed(request.request_id)

        report = stack.report_service.generate(request, interval_seconds=0)

        self.assertEqual(
            report.approval_decision, GenerationApprovalDecision.ALREADY_EXECUTED
        )
        self.assertEqual(report.execution_state, "NOT_EXECUTED")
        self.assertNotEqual(report.execution_state, "EXECUTION_STATE_UNKNOWN")
        self.assertFalse(report.job_created)

    def test_new_authorization_never_clears_unknown(self):
        stack = self._stack()
        stack.gate.mark_unknown(C.request_id, reason="test")

        fresh_request = _conforming_request(
            real_generation_authorization=RealGenerationAuthorization(
                request_id=C.request_id, authorized_by_human=True, note="brand new"
            )
        )
        report = stack.report_service.generate(fresh_request, interval_seconds=0)
        self.assertEqual(report.execution_state, "EXECUTION_STATE_UNKNOWN")


# ----------------------------------------------------------------------
# K. Human authorization remains independent
# ----------------------------------------------------------------------


class TestK_HumanAuthorizationIndependent(P2_23_TestCase):
    def test_missing_authorization_rejected_regardless_of_approved_flag(self):
        stack = self._stack()
        request = _conforming_request(real_generation_authorization=None)
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)

    def test_wrong_authorization_rejected(self):
        stack = self._stack()
        request = _conforming_request(
            real_generation_authorization=_valid_auth("not-005")
        )
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)


# ----------------------------------------------------------------------
# L/M/N. Activation Authority Boundary -- never automatic
# ----------------------------------------------------------------------


class TestLMN_ActivationAuthorityBoundary(P2_23_TestCase):
    def test_authority_checked_before_gate_even_with_a_gate_that_would_approve(self):
        # Défense en profondeur : simule un Gate COMPROMIS qui
        # renverrait APPROVED sans authority -- prepare_activation()
        # doit REFUSER quand même, car il ne fait jamais confiance
        # au Gate seul pour l'autorité d'activation.
        stack = self._stack()
        request = _conforming_request(real_generation_authorization=None)

        fake_approved = MagicMock()
        fake_approved.decision = GenerationApprovalDecision.APPROVED
        fake_approved.reasons = []
        stack.gate.evaluate = MagicMock(return_value=fake_approved)

        with self.assertRaises(ActivationRejectedError) as ctx:
            stack.activation_service.prepare_activation(request)
        self.assertTrue(
            any("Activation Authority" in r or "authorization" in r
                for r in ctx.exception.reasons)
        )

    def test_prepare_activation_never_called_from_director_planner_or_video_agent(self):
        # MIS À JOUR Phase P2.29 : `director.py` appelle désormais
        # légitimement `prepare_activation()` -- mais UNIQUEMENT
        # depuis `prepare_real_generation_activation()`, l'Explicit
        # Human Activation Entry Point de P2.29, qui exige un
        # `real_generation_authorization` fourni par l'appelant (sans
        # valeur par défaut). L'invariant qui compte réellement, et
        # que ce test vérifie désormais, est que le CHEMIN NORMAL
        # (`run_video_mission()`) ne l'appelle toujours JAMAIS --
        # vérifié par AST sur le corps de CETTE fonction précise,
        # jamais sur le fichier entier.
        import ast
        import inspect

        from director import AIDirector

        source = inspect.getsource(AIDirector.run_video_mission)
        tree = ast.parse(source.strip())
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn(
            "prepare_activation", called,
            "run_video_mission() must never call prepare_activation()",
        )

        for relative_path in ("agents/planner.py", "agents/video_agent.py", "agents/task_manager.py"):
            text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn(
                "prepare_activation(",
                text,
                f"prepare_activation() must never be called from {relative_path}",
            )

    def test_execute_without_contract_still_never_creates_one_implicitly(self):
        stack = self._stack()
        stack.job_service.activation_service = MagicMock(wraps=stack.activation_service)

        outcome = stack.job_service.execute(_conforming_request(), interval_seconds=0)

        self.assertTrue(outcome.succeeded)
        stack.job_service.activation_service.prepare_activation.assert_not_called()


# ----------------------------------------------------------------------
# O/P/Q/R. Contract remains request-bound, fresh checks enforced
# ----------------------------------------------------------------------


class TestOPQR_ContractBindingAndFreshness(P2_23_TestCase):
    def test_contract_remains_request_bound(self):
        stack = self._stack()
        contract = stack.activation_service.prepare_activation(_conforming_request())

        other_request = _conforming_request(
            request_id="006", real_generation_authorization=_valid_auth("006")
        )
        # Rejeté en profondeur (defense in depth) : le fresh
        # Gate.evaluate() d'execute() (identity_lock injecté dans le
        # Gate lui-même) refuse déjà 006 -> INVALID_REQUEST, avant
        # même d'atteindre validate_activation() -- l'exception
        # générique GenerationJobExecutionError est donc attendue ici,
        # pas nécessairement sa sous-classe spécifique au contrat.
        with self.assertRaises(Exception) as ctx:
            stack.job_service.execute(
                other_request, activation_contract=contract, interval_seconds=0
            )
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_identity_mutation_rejected(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)
        mutated = _conforming_request(prompt=request.prompt + " ")
        with self.assertRaises(Exception):
            stack.job_service.execute(
                mutated, activation_contract=contract, interval_seconds=0
            )
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_balance_mutation_rejected(self):
        stack = self._stack(cost_per_job=10.0, available_credits=100.0)
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)
        stack.provider._available_credits = 1.41
        with self.assertRaises(Exception):
            stack.job_service.execute(
                request, activation_contract=contract, interval_seconds=0
            )
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_cost_mutation_rejected(self):
        stack = self._stack(cost_per_job=10.0, available_credits=100.0)
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)
        stack.provider._cost_per_job = 1000.0
        with self.assertRaises(Exception):
            stack.job_service.execute(
                request, activation_contract=contract, interval_seconds=0
            )
        self.assertEqual(len(stack.provider._jobs), 0)


# ----------------------------------------------------------------------
# S/T/U. Lock busy, provider disabled, fake client never called
# ----------------------------------------------------------------------


class TestSTU_LockAndProviderSafety(P2_23_TestCase):
    def test_lock_busy_rejected(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)

        with stack.lock.acquire(request.request_id):
            with self.assertRaises(CriticalSectionBusyError):
                stack.job_service.execute(
                    request, activation_contract=contract, interval_seconds=0
                )
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_provider_still_disabled_and_fake_client_never_called(self):
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

        request = _conforming_request()
        contract = activation_service.prepare_activation(request)

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            job_service.execute(
                request, activation_contract=contract, interval_seconds=0
            )
        fake_client.create_job.assert_not_called()


# ----------------------------------------------------------------------
# V. No global activation flag
# ----------------------------------------------------------------------


class TestV_NoGlobalActivationFlag(unittest.TestCase):
    FORBIDDEN_TOKENS = (
        "enabled=True",
        "enabled = True",
        "real_generation_enabled",
        "activate_higgsfield",
        "bypass",
        "skip_gate",
        "skip_approval",
        "force_generation",
        "force=True",
        "production=True",
    )

    def test_no_forbidden_tokens_anywhere_in_production_code(self):
        # MIS À JOUR Phase P2.25 : `agents/production_activation_
        # boundary.py` déclare délibérément ces motifs comme
        # littéraux de chaîne (FORBIDDEN_GLOBAL_AUTHORITY_TOKENS) --
        # c'est le contrat négatif LUI-MÊME, jamais un usage réel.
        # Exclu ici pour la même raison que dans
        # tests/test_phase_p2_25_production_activation_boundary.py.
        excluded = {"agents/production_activation_boundary.py"}

        offenders = []
        for base in ("agents", "integrations"):
            for path in (PROJECT_ROOT / base).rglob("*.py"):
                relative = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
                if relative in excluded:
                    continue
                text = path.read_text(encoding="utf-8")
                for token in self.FORBIDDEN_TOKENS:
                    if token in text:
                        offenders.append((relative, token))

        director_text = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        for token in self.FORBIDDEN_TOKENS:
            if token in director_text:
                offenders.append(("director.py", token))

        self.assertEqual(offenders, [], f"forbidden tokens found: {offenders}")


# ----------------------------------------------------------------------
# W/X. No persistence of authorization or activation contract
# ----------------------------------------------------------------------


class TestWX_NoPersistence(P2_23_TestCase):
    def test_no_authorization_persisted_after_full_success(self):
        from agents.executed_request_store import FileExecutedRequestStore

        store_path = self._tmp / "executed_requests.json"
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        store = FileExecutedRequestStore(store_path)
        gate = GenerationApprovalGate(
            provider, executed_request_store=store, identity_lock=identity_lock
        )
        activation_service = RequestScopedActivationService(gate, identity_lock)
        lock = FileCriticalSectionLock(self._tmp / "locks")
        job_service = GenerationJobService(
            provider, gate, lock=lock, activation_service=activation_service
        )
        report_service = FinalReportService(provider, gate, job_service=job_service)

        request = _conforming_request()
        contract = activation_service.prepare_activation(request)
        report_service.generate(request, activation_contract=contract, interval_seconds=0)

        raw = store_path.read_text(encoding="utf-8")
        for forbidden in ("authorized_by_human", "authorization_id", "note"):
            self.assertNotIn(forbidden, raw)

    def test_no_activation_contract_file_ever_written_anywhere(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)
        stack.report_service.generate(
            request, activation_contract=contract, interval_seconds=0
        )
        # Le seul fichier attendu dans ce répertoire temporaire est,
        # le cas échéant, un verrou déjà libéré (donc absent) -- aucun
        # fichier de contrat n'existe nulle part.
        self.assertEqual(list(self._tmp.rglob("*contract*")), [])
        self.assertEqual(list(self._tmp.rglob("*activation*")), [])


# ----------------------------------------------------------------------
# Y. Video 005 integrity
# ----------------------------------------------------------------------


class TestY_Video005Integrity(unittest.TestCase):
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
# Z. FinalReport remains truthful across every scenario, exhaustively
# ----------------------------------------------------------------------


class TestZ_FinalReportRemainsTruthful(P2_23_TestCase):
    def test_status_executed_pass_implies_job_created_and_real_provider_called(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)
        report = stack.report_service.generate(
            request, activation_contract=contract, interval_seconds=0
        )
        if report.status == FinalReportStatus.EXECUTED_PASS:
            self.assertTrue(report.job_created)
            # CORRIGÉ (audit post-P2.27) : Mock provider -> False, cf.
            # commentaire de test_activation_decision_explicitly_
            # represented_on_success ci-dessus.
            self.assertFalse(report.real_provider_called)
            self.assertEqual(report.execution_state, "EXECUTED")
            self.assertEqual(report.activation_decision, ActivationDecision.APPROVED)

    def test_not_executed_never_carries_job_id_or_output_urls(self):
        stack = self._stack(cost_per_job=50.0, available_credits=1.41)
        report = stack.report_service.generate(_conforming_request(), interval_seconds=0)
        self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)
        self.assertIsNone(report.job_id)
        self.assertEqual(report.output_urls, tuple())

    def test_activation_rejected_never_produces_executed_status(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)
        stack.activation_service.validate_activation(request, contract)

        report = stack.report_service.generate(
            request, activation_contract=contract, interval_seconds=0
        )
        self.assertNotIn(
            report.status,
            (
                FinalReportStatus.EXECUTED_PASS,
                FinalReportStatus.EXECUTED_FAIL,
                FinalReportStatus.EXECUTED_RETRY_RECOMMENDED,
            ),
        )


if __name__ == "__main__":
    unittest.main()
