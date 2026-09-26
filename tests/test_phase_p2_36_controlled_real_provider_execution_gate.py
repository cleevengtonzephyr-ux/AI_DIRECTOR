"""
Tests — Phase P2.36 : CONTROLLED REAL PROVIDER EXECUTION GATE.

Verrouille ce que P2.36 a réellement ajouté :

- `ControlledRealProviderActivationService.inspect()` (agents/
  controlled_real_provider_activation.py) -- variante NON MUTANTE de
  `validate()`, mirroir exact de `RequestScopedActivationService.
  inspect_activation()` (Phase P2.24). `validate()` elle-même est
  refactorée (extraction de `_violations()`) mais son comportement
  observable est INCHANGÉ -- déjà re-confirmé par une exécution
  complète de tests/test_phase_p2_26_*.py et tests/test_phase_p2_27_
  *.py (99/99 PASS, non dupliqués ici).
- `agents/real_provider_execution_gate.py` (`RealProviderExecutionGate`
  / `RealProviderExecutionGateReport`) -- composition PURE de
  `ActivationReadinessEvaluator` (Phase P2.24, RÉUTILISÉ tel quel, zéro
  ligne modifiée) + la nouvelle dimension `provider_activation_ready`.
- `AIDirector.check_real_provider_execution_gate()` (director.py) --
  entrée read-only, mêmes garanties que `check_activation_readiness()`.

Ce fichier NE re-teste PAS les mutations individuelles déjà couvertes
par tests/test_phase_p2_21_*.py, tests/test_phase_p2_24_*.py,
tests/test_phase_p2_26_*.py, tests/test_phase_p2_27_*.py,
tests/test_phase_p2_30_*.py (identity/prompt/asset/model/duration/
resolution/aspect_ratio/cost/balance/replay/UNKNOWN mismatches, P2.21
expiry/consumption, P2.26 expiry/revoke/consumption) -- ces mécanismes
sont RÉUTILISÉS par ce Gate, jamais dupliqués, et restent inchangés.
"""

import ast
import re
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
from agents.controlled_real_provider_activation import (
    ControlledRealProviderActivationService,
)
from agents.critical_section_lock import FileCriticalSectionLock
from agents.generation_approval_gate import (
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from agents.generation_job_service import GenerationJobService
from agents.real_provider_execution_gate import (
    RealProviderExecutionDecision,
    RealProviderExecutionGate,
)
from agents.release_candidate_identity_lock import (
    ReleaseCandidateIdentityLock,
    VIDEO_005_RELEASE_CANDIDATE,
)
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider
from integrations.higgsfield.types import CostEstimate, MediaReference, ModelParam, ModelSchema

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


class _Stack:
    def __init__(self, tmp_dir: Path, cost_per_job=67.5, available_credits=100.0, provider=None):
        self.provider = provider or MockHiggsfieldProvider(
            cost_per_job=cost_per_job, available_credits=available_credits
        )
        self.identity_lock = ReleaseCandidateIdentityLock(C)
        self.gate = GenerationApprovalGate(self.provider, identity_lock=self.identity_lock)
        self.activation_service = RequestScopedActivationService(self.gate, self.identity_lock)
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
        self.execution_gate = RealProviderExecutionGate(
            self.gate,
            self.identity_lock,
            self.activation_service,
            self.provider_activation_service,
            job_service=self.job_service,
        )

    def prepared(self, request):
        rs_contract = self.activation_service.prepare_activation(request)
        pa_contract = self.provider_activation_service.prepare(request, rs_contract)
        return rs_contract, pa_contract


class _TmpDirTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_36_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def _stack(self, **kwargs) -> _Stack:
        return _Stack(self._tmp, **kwargs)


# ----------------------------------------------------------------------
# ControlledRealProviderActivationService.inspect() -- non-mutating,
# equivalent to validate(), never consumes.
# ----------------------------------------------------------------------


class TestProviderActivationInspectNonMutating(_TmpDirTestCase):
    def test_inspect_never_consumes_and_matches_validate_reasons(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)

        first = stack.provider_activation_service.inspect(request, rs_contract, pa_contract)
        second = stack.provider_activation_service.inspect(request, rs_contract, pa_contract)
        self.assertEqual(first, [])
        self.assertEqual(second, [])  # still unconsumed after two inspections

        # validate() must still succeed afterwards -- inspect() never
        # burned the contract.
        validated = stack.provider_activation_service.validate(request, rs_contract, pa_contract)
        self.assertIs(validated, pa_contract)

        # And a THIRD inspect(), now genuinely post-consumption, must
        # report the contract as consumed.
        third = stack.provider_activation_service.inspect(request, rs_contract, pa_contract)
        self.assertTrue(any("consumed" in r for r in third))

    def test_inspect_reports_mismatch_identically_to_validate_rejection(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)

        mutated = _conforming_request(prompt=request.prompt + " mutated")
        inspected_reasons = stack.provider_activation_service.inspect(mutated, rs_contract, pa_contract)
        self.assertTrue(any("prompt sha256" in r for r in inspected_reasons))

        from agents.controlled_real_provider_activation import (
            ControlledRealProviderActivationRejectedError,
        )

        with self.assertRaises(ControlledRealProviderActivationRejectedError) as ctx:
            stack.provider_activation_service.validate(mutated, rs_contract, pa_contract)
        self.assertEqual(sorted(ctx.exception.reasons), sorted(inspected_reasons))


# ----------------------------------------------------------------------
# RealProviderExecutionGate -- construction guard
# ----------------------------------------------------------------------


class TestGateConstructionGuard(_TmpDirTestCase):
    def test_provider_activation_service_is_mandatory(self):
        stack = self._stack()
        with self.assertRaises(ValueError):
            RealProviderExecutionGate(
                stack.gate,
                stack.identity_lock,
                stack.activation_service,
                None,
            )


# ----------------------------------------------------------------------
# A, W, X, S : missing / foreign provider activation contract
# ----------------------------------------------------------------------


class TestGateProviderActivationDimension(_TmpDirTestCase):
    def test_A_W_missing_provider_activation_contract_not_approved(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, _ = stack.prepared(request)

        report = stack.execution_gate.evaluate(request, activation_contract=rs_contract)
        self.assertFalse(report.provider_activation_ready)
        self.assertEqual(report.decision, RealProviderExecutionDecision.NOT_APPROVED)

    def test_missing_underlying_p2_21_contract_also_blocks_provider_dimension(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)

        report = stack.execution_gate.evaluate(
            request, activation_contract=None, provider_activation_contract=pa_contract
        )
        self.assertFalse(report.provider_activation_ready)
        self.assertEqual(report.decision, RealProviderExecutionDecision.NOT_APPROVED)

    def test_X_S_foreign_provider_activation_contract_not_approved(self):
        """Un contrat P2.26 préparé pour UN P2.21 ne peut jamais être
        inspecté avec succès contre un AUTRE contrat P2.21, même pour
        la même requête (single-use / binding exact -- Phase 6)."""

        stack = self._stack()
        request = _conforming_request()
        rs_contract_a, pa_contract_a = stack.prepared(request)
        rs_contract_b = stack.activation_service.prepare_activation(
            _conforming_request(
                real_generation_authorization=RealGenerationAuthorization(
                    request_id="005", authorized_by_human=True
                )
            )
        )

        report = stack.execution_gate.evaluate(
            request,
            activation_contract=rs_contract_b,
            provider_activation_contract=pa_contract_a,
        )
        self.assertFalse(report.provider_activation_ready)
        self.assertTrue(
            any("request-scoped activation" in r for r in report.provider_activation_reasons)
        )
        self.assertEqual(report.decision, RealProviderExecutionDecision.NOT_APPROVED)


# ----------------------------------------------------------------------
# Z : Mock valid path -> APPROVED
# ----------------------------------------------------------------------


class TestGateMockValidPath(_TmpDirTestCase):
    def test_Z_full_valid_mock_chain_is_approved(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)

        report = stack.execution_gate.evaluate(
            request,
            activation_contract=rs_contract,
            provider_activation_contract=pa_contract,
        )

        self.assertEqual(report.decision, RealProviderExecutionDecision.APPROVED)
        self.assertEqual(report.all_reasons, [])
        self.assertTrue(report.readiness.provider_ready)  # Mock, not the real disabled Provider

        # Gate APPROVED never means executed: no job was created by
        # evaluate() itself.
        self.assertEqual(len(stack.provider._jobs), 0)

        # Only now, SEPARATELY, does the Mock simulate an execution --
        # still real_provider_called=False (never confused with a real
        # generation, cf. FinalReportService._is_real_provider()).
        outcome = stack.job_service.execute(
            request,
            interval_seconds=0,
            activation_contract=rs_contract,
            provider_activation_contract=pa_contract,
        )
        self.assertTrue(outcome.succeeded)
        is_real = type(stack.job_service.provider).create_job is HiggsfieldProvider.create_job
        self.assertFalse(is_real)


# ----------------------------------------------------------------------
# AA, Y : real provider path -- technically eligible on every OTHER
# dimension, but provider_ready (inherited from P2.24) permanently
# closes the overall decision.
# ----------------------------------------------------------------------


class TestGateRealProviderPathRemainsClosed(_TmpDirTestCase):
    def test_AA_Y_real_provider_dimension_alone_blocks_even_when_everything_else_valid(self):
        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)

        real_provider.get_model = lambda job_type: ModelSchema(
            job_type=job_type,
            display_name=job_type,
            params=(
                ModelParam(name="prompt", type="string", required=True),
                ModelParam(name="duration", type="integer", required=False, default=5),
                ModelParam(
                    name="resolution", type="string", required=False,
                    default="720p", enum=("480p", "720p", "1080p", "4k"),
                ),
                ModelParam(
                    name="aspect_ratio", type="string", required=False,
                    default="16:9", enum=("9:16", "16:9"),
                ),
                ModelParam(name="start_image", type="object|null", required=False, default=None),
                ModelParam(name="image_references", type="array", required=False, default=None),
            ),
            raw={},
        )
        real_provider.estimate_cost = (
            lambda job_type, prompt, duration=None, resolution=None, aspect_ratio=None: (
                CostEstimate(job_type=job_type, credits=67.5, raw={"credits": 67.5})
            )
        )
        real_provider.get_account_balance = lambda: 1000.0

        stack = self._stack(provider=real_provider)
        request = _conforming_request()

        # The Gate technique lui-même APPROVE (readiness quasi-complet)...
        self.assertEqual(stack.gate.evaluate(request).decision.value, "APPROVED")

        # ...mais la préparation P2.21 -> P2.26 échoue déjà à la
        # frontière Provider (comme documenté en P2.26/P2.31/P2.35) --
        # aucun contrat P2.26 valide ne peut donc jamais exister contre
        # le vrai Provider, et le Gate d'exécution ne peut donc jamais
        # renvoyer APPROVED.
        rs_contract = stack.activation_service.prepare_activation(request)
        from agents.controlled_real_provider_activation import (
            ControlledRealProviderActivationRejectedError,
        )

        with self.assertRaises(ControlledRealProviderActivationRejectedError):
            stack.provider_activation_service.prepare(request, rs_contract)

        # Sans contrat P2.26 valide, le Gate d'exécution reste
        # structurellement incapable de renvoyer APPROVED.
        report = stack.execution_gate.evaluate(request, activation_contract=rs_contract)
        self.assertFalse(report.readiness.provider_ready)
        self.assertEqual(report.decision, RealProviderExecutionDecision.NOT_APPROVED)

        fake_client.create_job.assert_not_called()
        fake_client.run.assert_not_called()


# ----------------------------------------------------------------------
# Director entry point -- pure, read-only.
# ----------------------------------------------------------------------


class TestDirectorEntryPoint(unittest.TestCase):
    def test_check_real_provider_execution_gate_is_pure_and_never_executes(self):
        import director

        d = director.AIDirector()
        d.higgsfield = MagicMock()  # never actually touched by this pure evaluation path guard below

        # This call would, against the REAL chain, attempt a live
        # balance/model/cost read -- deliberately NOT exercised here
        # (Phase P2.36 forbids any real Higgsfield call). Instead we
        # confirm, statically via AST (not naive substring matching,
        # which would false-positive on this method's own docstring
        # explaining that it never calls create_job()), that the
        # method's actual CODE never calls create_job() and never
        # constructs RealGenerationAuthorization.
        self.assertTrue(callable(d.check_real_provider_execution_gate))

        import inspect
        import textwrap

        source = textwrap.dedent(
            inspect.getsource(director.AIDirector.check_real_provider_execution_gate)
        )
        tree = ast.parse(source)
        create_job_calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "create_job"
        ]
        auth_calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "RealGenerationAuthorization"
        ]
        self.assertEqual(create_job_calls, [])
        self.assertEqual(auth_calls, [])


# ----------------------------------------------------------------------
# CALL-SITE INVARIANT + SECURITY SCAN
# ----------------------------------------------------------------------


class TestCallSiteInvariant(unittest.TestCase):
    def test_exactly_one_production_create_job_call_site(self):
        offenders = []
        for base in ("agents", "integrations", "scripts"):
            base_dir = PROJECT_ROOT / base
            if not base_dir.exists():
                continue
            for path in base_dir.rglob("*.py"):
                if path.name in ("generation_job_service.py", "job_monitor.py"):
                    continue
                if "mock_provider.py" in str(path):
                    continue
                text = path.read_text(encoding="utf-8-sig")
                for node in ast.walk(ast.parse(text)):
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "create_job"
                    ):
                        offenders.append(str(path.relative_to(PROJECT_ROOT)))
        director_text = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8-sig")
        for node in ast.walk(ast.parse(director_text)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "create_job"
            ):
                offenders.append("director.py")
        self.assertEqual(offenders, [])

        gjs_text = (PROJECT_ROOT / "agents" / "generation_job_service.py").read_text(
            encoding="utf-8-sig"
        )
        real_calls = [
            n
            for n in ast.walk(ast.parse(gjs_text))
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "create_job"
        ]
        self.assertEqual(len(real_calls), 1)

    def test_real_provider_execution_gate_module_never_calls_create_job(self):
        text = (PROJECT_ROOT / "agents" / "real_provider_execution_gate.py").read_text(
            encoding="utf-8-sig"
        )
        tree = ast.parse(text)
        calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "create_job"
        ]
        self.assertEqual(calls, [])


class TestSecurityScan(unittest.TestCase):
    TOKENS = (
        "REAL_GENERATION_ENABLED", "HIGGSFIELD_ENABLED", "PRODUCTION_MODE",
        "FORCE_GENERATION", "force_generate", "generate_now", "skip_gate",
        "skip_approval", "bypass", "auto_authorize", "auto_activation",
    )
    EXCLUDED = {"agents/production_activation_boundary.py"}

    def test_no_forbidden_tokens_in_production_code(self):
        patterns = {t: re.compile(r"\b" + re.escape(t) + r"\b") for t in self.TOKENS}
        offenders = []
        for base in ("agents", "integrations", "scripts"):
            base_dir = PROJECT_ROOT / base
            if not base_dir.exists():
                continue
            for path in base_dir.rglob("*.py"):
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

    def test_no_real_generation_authorization_construction_in_new_files(self):
        for path in (
            PROJECT_ROOT / "agents" / "real_provider_execution_gate.py",
            PROJECT_ROOT / "agents" / "controlled_real_provider_activation.py",
        ):
            text = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(text)
            offenders = [
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "RealGenerationAuthorization"
            ]
            self.assertEqual(offenders, [], str(path))


if __name__ == "__main__":
    unittest.main()
