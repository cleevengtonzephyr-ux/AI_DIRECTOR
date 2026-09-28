"""
Tests — Phase P2.24 : ACTIVATION READINESS PROTOCOL & FINAL
PRE-GENERATION GATE.

Verrouille `agents/activation_readiness.py`
(`ActivationReadinessEvaluator`/`ActivationReadinessReport`) : une
évaluation PUREMENT EN LECTURE de dix dimensions indépendantes
(technical/request_identity/prompt/asset/budget/authorization/
activation/replay/crash/provider), dont AUCUNE ne crée jamais
d'autorisation humaine ni de contrat d'activation, et dont la décision
`"READY"` ne signifie jamais "génère maintenant" -- notamment parce
que `provider_ready` reste TOUJOURS `False` face au vrai
`HiggsfieldProvider`.

Utilise le VRAI `FileCriticalSectionLock` et les VRAIS fichiers/prompt
de Video 005, comme P2.22/P2.23. Aucun mock n'est utilisé pour
prétendre qu'une génération réelle a eu lieu.
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

from agents.activation_contract import RequestScopedActivationService
from agents.activation_readiness import (
    ActivationReadinessEvaluator,
    ActivationReadinessReport,
)
from agents.critical_section_lock import FileCriticalSectionLock
from agents.executed_request_store import FileExecutedRequestStore
from agents.generation_approval_gate import (
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from agents.generation_job_service import GenerationJobService
from agents.release_candidate_identity_lock import (
    ReleaseCandidateIdentityLock,
    VIDEO_005_RELEASE_CANDIDATE,
)
from director import AIDirector
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
        # Phase B : store persistant TEMPORAIRE (la readiness exige une
        # garantie durable ; jamais le `state/` réel).
        self.gate = GenerationApprovalGate(
            self.provider,
            executed_request_store=FileExecutedRequestStore(tmp_dir / "state" / "executed_requests.json"),
            identity_lock=self.identity_lock,
        )
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
            self.gate,
            self.identity_lock,
            self.activation_service,
            job_service=self.job_service,
        )


class P2_24_TestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_24_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def _stack(self, **kwargs) -> _WiredStack:
        return _WiredStack(self._tmp, **kwargs)


# ----------------------------------------------------------------------
# A. Technical readiness
# ----------------------------------------------------------------------


class TestA_TechnicalReadiness(P2_24_TestCase):
    def test_full_valid_stack_is_technically_ready(self):
        stack = self._stack()
        report = stack.evaluator.evaluate(_conforming_request())
        self.assertTrue(report.technical_ready)
        self.assertEqual(report.technical_reasons, [])

    def test_noop_lock_is_not_technically_ready(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
        activation_service = RequestScopedActivationService(gate, identity_lock)
        job_service = GenerationJobService(
            provider, gate, activation_service=activation_service
        )  # no real lock injected
        evaluator = ActivationReadinessEvaluator(
            gate, identity_lock, activation_service, job_service=job_service
        )
        report = evaluator.evaluate(_conforming_request())
        self.assertFalse(report.technical_ready)


# ----------------------------------------------------------------------
# B/C. Prompt readiness
# ----------------------------------------------------------------------


class TestBC_PromptReadiness(P2_24_TestCase):
    def test_exact_prompt_is_ready(self):
        stack = self._stack()
        report = stack.evaluator.evaluate(_conforming_request())
        self.assertTrue(report.prompt_ready)

    def test_mutated_prompt_is_not_ready(self):
        stack = self._stack()
        report = stack.evaluator.evaluate(
            _conforming_request(prompt=_real_prompt() + " ")
        )
        self.assertFalse(report.prompt_ready)
        self.assertEqual(report.decision, "NOT_READY")


# ----------------------------------------------------------------------
# D/E. Asset readiness
# ----------------------------------------------------------------------


class TestDE_AssetReadiness(P2_24_TestCase):
    def test_mutated_avatar_is_not_ready(self):
        stack = self._stack()
        request = _conforming_request(
            start_image=MediaReference(
                role="master_avatar", source=str(REAL_FACE_PATH), sha256=None
            )
        )
        report = stack.evaluator.evaluate(request)
        self.assertFalse(report.asset_ready)
        self.assertEqual(report.decision, "NOT_READY")

    def test_mutated_face_reference_is_not_ready(self):
        stack = self._stack()
        request = _conforming_request(
            image_references=(
                MediaReference(
                    role="face_reference", source=str(REAL_AVATAR_PATH), sha256=None
                ),
            )
        )
        report = stack.evaluator.evaluate(request)
        self.assertFalse(report.asset_ready)


# ----------------------------------------------------------------------
# F. Request identity readiness
# ----------------------------------------------------------------------


class TestF_RequestIdentityReadiness(P2_24_TestCase):
    def test_different_request_id_is_not_ready(self):
        stack = self._stack()
        request = _conforming_request(
            request_id="006", real_generation_authorization=_valid_auth("006")
        )
        report = stack.evaluator.evaluate(request)
        self.assertFalse(report.request_identity_ready)
        self.assertEqual(report.decision, "NOT_READY")


# ----------------------------------------------------------------------
# G/H. Budget readiness
# ----------------------------------------------------------------------


class TestGH_BudgetReadiness(P2_24_TestCase):
    def test_insufficient_budget_is_not_ready(self):
        stack = self._stack(cost_per_job=50.0, available_credits=1.41)
        report = stack.evaluator.evaluate(_conforming_request())
        self.assertFalse(report.budget_ready)
        self.assertEqual(report.decision, "NOT_READY")

    def test_sufficient_budget_never_creates_authorization(self):
        stack = self._stack(cost_per_job=10.0, available_credits=100.0)
        request = _conforming_request(real_generation_authorization=None)

        report = stack.evaluator.evaluate(request)

        self.assertTrue(report.budget_ready)
        # Le budget est suffisant, mais AUCUNE autorisation n'a été
        # créée par cette seule évaluation.
        self.assertIsNone(request.real_generation_authorization)
        self.assertFalse(report.authorization_ready)


# ----------------------------------------------------------------------
# I/J. Authorization readiness
# ----------------------------------------------------------------------


class TestIJ_AuthorizationReadiness(P2_24_TestCase):
    def test_no_authorization_is_not_ready(self):
        stack = self._stack()
        request = _conforming_request(real_generation_authorization=None)
        report = stack.evaluator.evaluate(request)
        self.assertFalse(report.authorization_ready)
        self.assertEqual(report.decision, "NOT_READY")

    def test_valid_authorization_is_recognized_but_activation_not_auto_created(self):
        stack = self._stack()
        request = _conforming_request()  # has a valid authorization

        report = stack.evaluator.evaluate(request)  # no activation_contract passed

        self.assertTrue(report.authorization_ready)
        self.assertFalse(report.activation_ready)
        self.assertEqual(
            len(stack.activation_service._issued_at), 0,
            "prepare_activation() must never be called automatically by readiness",
        )


# ----------------------------------------------------------------------
# K/L. Activation contract lifetime
# ----------------------------------------------------------------------


class TestKL_ActivationContractLifetime(P2_24_TestCase):
    def test_foreign_activation_contract_is_not_ready(self):
        stack_a = self._stack()
        other_tmp = Path(tempfile.mkdtemp(prefix="p2_24_other_"))
        self.addCleanup(shutil.rmtree, other_tmp, ignore_errors=True)
        stack_b = _WiredStack(other_tmp)

        request = _conforming_request()
        foreign_contract = stack_b.activation_service.prepare_activation(request)

        report = stack_a.evaluator.evaluate(request, activation_contract=foreign_contract)
        self.assertFalse(report.activation_ready)
        self.assertEqual(report.decision, "NOT_READY")

    def test_expired_activation_contract_is_not_ready(self):
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
        evaluator = ActivationReadinessEvaluator(
            gate, identity_lock, activation_service, job_service=job_service
        )

        request = _conforming_request()
        contract = activation_service.prepare_activation(request)
        fake_time["t"] += 61.0

        report = evaluator.evaluate(request, activation_contract=contract)
        self.assertFalse(report.activation_ready)

    def test_inspecting_a_contract_never_consumes_it(self):
        # Étape 24 P2.24 : une simple lecture de readiness ne doit
        # jamais brûler un contrat réel à usage unique.
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)

        report1 = stack.evaluator.evaluate(request, activation_contract=contract)
        report2 = stack.evaluator.evaluate(request, activation_contract=contract)

        self.assertTrue(report1.activation_ready)
        self.assertTrue(report2.activation_ready)  # toujours vrai la 2e fois


# ----------------------------------------------------------------------
# M/N. Replay readiness
# ----------------------------------------------------------------------


class TestMN_ReplayReadiness(P2_24_TestCase):
    def test_already_executed_is_not_ready(self):
        stack = self._stack()
        request = _conforming_request()
        stack.gate.mark_executed(request.request_id)
        report = stack.evaluator.evaluate(request)
        self.assertFalse(report.replay_safe)
        self.assertEqual(report.decision, "NOT_READY")

    def test_unknown_state_is_not_ready(self):
        stack = self._stack()
        request = _conforming_request()
        stack.gate.mark_unknown(request.request_id, reason="test")
        report = stack.evaluator.evaluate(request)
        self.assertFalse(report.replay_safe)
        self.assertEqual(report.decision, "NOT_READY")


# ----------------------------------------------------------------------
# O. Provider readiness
# ----------------------------------------------------------------------


class TestO_ProviderReadiness(P2_24_TestCase):
    def test_real_provider_is_never_ready(self):
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
        gate = GenerationApprovalGate(
            real_provider,
            executed_request_store=FileExecutedRequestStore(self._tmp / "state" / "executed_requests.json"),
            identity_lock=identity_lock,
        )
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

        self.assertFalse(report.provider_ready)
        self.assertEqual(report.decision, "NOT_READY")
        # Toutes les AUTRES dimensions peuvent pourtant être vertes --
        # readiness != authorization != activation != execution.
        self.assertTrue(report.technical_ready)
        self.assertTrue(report.request_identity_ready)
        self.assertTrue(report.prompt_ready)
        self.assertTrue(report.asset_ready)
        self.assertTrue(report.budget_ready)
        self.assertTrue(report.authorization_ready)
        self.assertTrue(report.activation_ready)
        self.assertTrue(report.replay_safe)
        self.assertTrue(report.crash_safe)

        fake_client.create_job.assert_not_called()


# ----------------------------------------------------------------------
# P/Q/R. Readiness never touches create_job / real client / credits
# ----------------------------------------------------------------------


class TestPQR_ReadinessNeverActs(P2_24_TestCase):
    def test_fully_mock_ready_evaluation_never_calls_create_job(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)

        stack.provider.create_job = MagicMock(
            wraps=stack.provider.create_job
        )

        report = stack.evaluator.evaluate(request, activation_contract=contract)
        self.assertEqual(report.decision, "READY")  # Mock provider -> provider_ready True
        stack.provider.create_job.assert_not_called()

    def test_readiness_never_touches_a_real_higgsfield_client(self):
        fake_client = MagicMock()
        fake_client.estimate_cost.return_value = {"credits": 10.0}
        fake_client.account_status.return_value = {"credits": 1000.0}
        fake_client.get_model.return_value = {
            "job_type": C.job_type,
            "display_name": "d",
            "params": [{"name": "prompt", "type": "string", "required": True}],
        }
        real_provider = HiggsfieldProvider(client=fake_client)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(real_provider, identity_lock=identity_lock)
        activation_service = RequestScopedActivationService(gate, identity_lock)
        evaluator = ActivationReadinessEvaluator(gate, identity_lock, activation_service)

        evaluator.evaluate(_conforming_request(duration=5))

        fake_client.create_job.assert_not_called()
        # Seules des méthodes read-only ont pu être invoquées.
        for name in ("delete", "auth_login", "publish"):
            self.assertFalse(hasattr(fake_client, name) and getattr(fake_client, name).called)

    def test_no_mock_jobs_ever_created_by_a_readiness_evaluation(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)
        stack.evaluator.evaluate(request, activation_contract=contract)
        self.assertEqual(len(stack.provider._jobs), 0)


# ----------------------------------------------------------------------
# S. Balance unaffected
# ----------------------------------------------------------------------


class TestS_BalanceUnaffected(P2_24_TestCase):
    def test_balance_unchanged_across_multiple_evaluations(self):
        stack = self._stack(cost_per_job=10.0, available_credits=1.41)
        request = _conforming_request()
        before = stack.provider._available_credits
        for _ in range(5):
            stack.evaluator.evaluate(request)
        after = stack.provider._available_credits
        self.assertEqual(before, after)


# ----------------------------------------------------------------------
# T/U. No automatic authorization/activation creation
# ----------------------------------------------------------------------


class TestTU_NoAutomaticCreation(P2_24_TestCase):
    def test_authorization_never_auto_created(self):
        stack = self._stack()
        request = _conforming_request(real_generation_authorization=None)
        stack.evaluator.evaluate(request)
        self.assertIsNone(request.real_generation_authorization)

    def test_activation_contract_never_auto_created(self):
        stack = self._stack()
        request = _conforming_request()
        stack.evaluator.evaluate(request)  # no activation_contract passed
        self.assertEqual(len(stack.activation_service._issued_at), 0)
        self.assertEqual(len(stack.activation_service._consumed_activation_ids), 0)


# ----------------------------------------------------------------------
# V/W/X/Y. No component auto-generates an authorization
# ----------------------------------------------------------------------


class TestVWXY_NoComponentAutoGeneratesAuthorization(unittest.TestCase):
    def test_no_automatic_authorization_construction_anywhere(self):
        for relative_path in (
            "director.py",
            "agents/planner.py",
            "agents/video_agent.py",
            "agents/task_manager.py",
        ):
            text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn(
                "RealGenerationAuthorization(",
                text,
                f"{relative_path} must never construct a RealGenerationAuthorization",
            )

    def test_run_video_mission_never_calls_prepare_activation(self):
        text = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        # `prepare_activation(` doit apparaître UNIQUEMENT dans le
        # docstring de check_activation_readiness()/du module -- jamais
        # comme appel réel dans run_video_mission().
        import ast

        tree = ast.parse(text)
        run_video_mission = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "run_video_mission"
        )
        calls = [
            n.func.attr
            for n in ast.walk(run_video_mission)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        ]
        self.assertNotIn("prepare_activation", calls)


# ----------------------------------------------------------------------
# Z. Readiness never modifies the Master Prompt
# ----------------------------------------------------------------------


class TestZ_ReadinessNeverModifiesPrompt(P2_24_TestCase):
    def test_prompt_file_and_hash_unchanged_after_evaluations(self):
        import hashlib

        prompt_before = _real_prompt()
        hash_before = hashlib.sha256(prompt_before.encode("utf-8")).hexdigest()

        stack = self._stack()
        for _ in range(3):
            stack.evaluator.evaluate(_conforming_request())

        prompt_after = _real_prompt()
        hash_after = hashlib.sha256(prompt_after.encode("utf-8")).hexdigest()

        self.assertEqual(hash_before, hash_after)
        self.assertEqual(hash_after, C.prompt_sha256)


# ----------------------------------------------------------------------
# Video 005 full integrity re-check
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
# Sole real production caller of create_job()
# ----------------------------------------------------------------------


class TestSoleRealProductionCaller(unittest.TestCase):
    def test_generation_job_service_is_the_only_real_call_site(self):
        # `agents/job_monitor.py` is a pre-existing, unrelated, pure
        # simulation helper (JobMonitor.create_job(job_id)) -- it
        # never imports HiggsfieldClient/BaseHiggsfieldProvider, is
        # never wired into the real generation chain, and was already
        # classified as benign during the P2.22 security audit.
        import ast

        offenders = []
        for base in ("agents", "integrations"):
            for path in (PROJECT_ROOT / base).rglob("*.py"):
                if path.name in ("generation_job_service.py", "job_monitor.py"):
                    continue
                if "mock_provider.py" in str(path):
                    continue  # simulated create_job, not a real call site
                text = path.read_text(encoding="utf-8-sig")
                tree = ast.parse(text)
                for node in ast.walk(tree):
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "create_job"
                    ):
                        # provider.py's own create_job DEFINITION is fine
                        # (it's the disabled implementation); only flag
                        # actual CALL sites, which this ast.Call check
                        # already restricts to.
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

        self.assertEqual(offenders, [], f"unexpected create_job() call sites: {offenders}")


# ----------------------------------------------------------------------
# Live wiring through AIDirector.check_activation_readiness()
# ----------------------------------------------------------------------


class TestDirectorReadinessWiring(unittest.TestCase):
    """
    IMPORTANT : `check_activation_readiness()` évalue réellement le
    budget (coût + solde), ce qui invoquerait un VRAI appel CLI si on
    le laissait utiliser le `HiggsfieldClient` réel du Director --
    exactement ce que ce fichier de tests doit éviter (règle du
    projet : aucun test ne fait d'appel réseau/CLI réel). On injecte
    donc un `fake_client` (MagicMock, même technique que
    tests/test_phase_p2_22_activation_wiring.py::TestT) AVANT
    d'appeler la méthode, pour exercer le VRAI câblage
    (director -> _build_default_chain() -> ActivationReadinessEvaluator)
    sans jamais toucher au CLI réel.
    """

    def test_build_default_chain_returns_correct_types_without_any_cli_call(self):
        director = AIDirector()
        try:
            chain = director._build_default_chain()
        except Exception as error:  # pragma: no cover - ne doit jamais arriver
            self.fail(f"Construction should never touch the CLI: {error}")

        self.assertIsInstance(chain.provider, HiggsfieldProvider)
        self.assertIsInstance(chain.identity_lock, ReleaseCandidateIdentityLock)
        self.assertIsInstance(chain.gate, GenerationApprovalGate)
        self.assertIsInstance(chain.lock, FileCriticalSectionLock)
        self.assertIsInstance(chain.activation_service, RequestScopedActivationService)
        self.assertIsInstance(chain.job_service, GenerationJobService)

    def test_check_activation_readiness_with_injected_fake_client_never_hits_real_cli(self):
        fake_client = MagicMock()
        fake_client.estimate_cost.return_value = {"credits": 10.0}
        fake_client.account_status.return_value = {"credits": 1.41}
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

        director = AIDirector()
        director.higgsfield = fake_client  # remplace le CLIENT réel avant tout appel

        # Phase B : chemins persistants de la chaîne réelle redirigés
        # vers un dossier temporaire (jamais le `state/` réel).
        from tests.test_phase_b_authorization_single_use import isolated_director_state

        tmp = Path(tempfile.mkdtemp(prefix="p2_24_director_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with isolated_director_state(tmp):
            report = director.check_activation_readiness(_conforming_request())

        self.assertIsInstance(report, ActivationReadinessReport)
        # Chemin réel : provider_ready doit être False (HiggsfieldProvider réel).
        self.assertFalse(report.provider_ready)
        self.assertEqual(report.decision, "NOT_READY")
        fake_client.create_job.assert_not_called()


if __name__ == "__main__":
    unittest.main()
