"""
Tests — Phase P2.38 : FINAL EXECUTION BOUNDARY AUDIT.

Phase READ-ONLY / ZERO-SPEND / ZERO-GENERATION : ce fichier n'introduit
AUCUN nouveau mécanisme de production -- il consolide, en un seul
endroit, une vérification directe de chacun des points de la checklist
P2.38 contre l'architecture existante (P2.11/15/16/18/20/21/24/25/26/
29/32/35/36/37, toutes inchangées). Les matrices de mutation
exhaustives (chaque champ individuellement muté) restent dans
tests/test_phase_p2_21/24/26/27/30_*.py -- non dupliquées ici ; ce
fichier vérifie plutôt que la FRONTIÈRE D'EXÉCUTION COMPLÈTE, de bout
en bout, se comporte comme documentée.
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

from agents.activation_contract import (
    ActivationRejectedError,
    RequestScopedActivationService,
)
from agents.controlled_real_provider_activation import (
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
from tests.real_provider_path_fixtures import FIXTURE_MAX_COST_CREDITS_PER_REQUEST
from tests.authorization_content_helpers import bind_request
from agents.generation_job_service import (
    GenerationJobService,
    GenerationJobUnknownStateError,
    CriticalStateUnknownAndUnrecordedError,
)
from agents.production_activation_boundary import FORBIDDEN_GLOBAL_AUTHORITY_TOKENS
from agents.real_provider_activation_preflight import ActivationPreflightEvaluator
from agents.real_provider_execution_gate import (
    RealProviderExecutionDecision,
    RealProviderExecutionGate,
)
from agents.release_candidate_identity_lock import (
    ReleaseCandidateIdentityLock,
    VIDEO_005_RELEASE_CANDIDATE,
)
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
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
    return bind_request(GenerationRequest(**defaults))


class _Stack:
    def __init__(self, tmp_dir: Path, cost_per_job=67.5, available_credits=100.0, provider=None,
                 max_cost_credits_per_request=None):
        self.provider = provider or MockHiggsfieldProvider(
            cost_per_job=cost_per_job, available_credits=available_credits
        )
        self.identity_lock = ReleaseCandidateIdentityLock(C)
        # Phase B : store persistant TEMPORAIRE propre à ce stack (la
        # readiness exige une garantie durable ; jamais le `state/` réel).
        from agents.executed_request_store import FileExecutedRequestStore

        self.gate = GenerationApprovalGate(
            self.provider,
            executed_request_store=FileExecutedRequestStore(
                Path(tempfile.mkdtemp(prefix="state_", dir=tmp_dir)) / "executed_requests.json"
            ),
            identity_lock=self.identity_lock,
            max_cost_credits_per_request=max_cost_credits_per_request,
        )
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
        self.preflight = ActivationPreflightEvaluator(
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
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_38_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def _stack(self, **kwargs) -> _Stack:
        return _Stack(self._tmp, **kwargs)


def _SpyProvider(**kwargs):
    """Mock RECONNU : chaque appel de create_job() est enregistré dans
    `_jobs`. Phase D : un Provider qui redéfinit create_job() n'atteint
    plus la frontière."""

    return MockHiggsfieldProvider(**kwargs)


# ------------------------------------------------------------------ #
# 1. Baseline / 2. Video 005 identity / 3-5. hashes / 6. exact format
# ------------------------------------------------------------------ #


class Test01_Baseline(unittest.TestCase):
    def test_no_persistent_execution_state_before_this_suite_runs(self):
        self.assertFalse((PROJECT_ROOT / "state" / "executed_requests.json").exists())


class Test02_06_Video005IdentityPromptAssets(unittest.TestCase):
    def test_canonical_identity_exact(self):
        self.assertEqual(C.request_id, "005")
        self.assertEqual(C.job_type, "seedance_2_0")
        self.assertEqual(C.duration, 15)
        self.assertEqual(C.resolution, "720p")
        self.assertEqual(C.aspect_ratio, "9:16")

    def test_prompt_hash_live_matches_canonical(self):
        import hashlib

        prompt = _real_prompt()
        self.assertEqual(len(prompt), C.prompt_chars)
        self.assertEqual(len(prompt.splitlines()), C.prompt_lines)
        self.assertEqual(hashlib.sha256(prompt.encode("utf-8")).hexdigest(), C.prompt_sha256)

    def test_avatar_hash_live_matches_canonical(self):
        import hashlib

        h = hashlib.sha256()
        with REAL_AVATAR_PATH.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        self.assertEqual(h.hexdigest(), C.avatar_master_sha256)

    def test_face_hash_live_matches_canonical(self):
        import hashlib

        h = hashlib.sha256()
        with REAL_FACE_PATH.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        self.assertEqual(h.hexdigest(), C.face_reference_sha256)

    def test_exact_duration_format_not_a_neighboring_confirmed_value(self):
        """Étape 6 : 15 exactement -- ni 5 ni 10 (autres valeurs
        confirmées pour seedance_2_0, mais pas celle de Video 005)."""

        request_10 = _conforming_request(duration=10)
        violations = ReleaseCandidateIdentityLock(C).violations(request_10)
        self.assertTrue(any("duration" in v for v in violations))


# ------------------------------------------------------------------ #
# 7. Budget
# ------------------------------------------------------------------ #


class Test07_Budget(_TmpDirTestCase):
    def test_budget_not_ready_with_real_numbers_1_41_vs_67_5(self):
        stack = self._stack(cost_per_job=67.5, available_credits=1.41)
        request = _conforming_request()
        report = stack.preflight.evaluate(request)
        self.assertFalse(report.budget_ready)
        self.assertEqual(report.decision, RealProviderExecutionDecision.NOT_APPROVED)


# ------------------------------------------------------------------ #
# 8. Human authority
# ------------------------------------------------------------------ #


class Test08_HumanAuthority(_TmpDirTestCase):
    def test_approved_true_alone_never_suffices(self):
        stack = self._stack()
        request = _conforming_request(real_generation_authorization=None)
        self.assertTrue(request.approved)
        decision = stack.gate.evaluate(request).decision
        self.assertNotEqual(decision, GenerationApprovalDecision.APPROVED)

    def test_missing_authorization(self):
        stack = self._stack()
        request = _conforming_request(real_generation_authorization=None)
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)

    def test_wrong_request_authorization(self):
        stack = self._stack()
        request = _conforming_request(
            real_generation_authorization=RealGenerationAuthorization(
                request_id="006", authorized_by_human=True
            )
        )
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)

    def test_authorization_has_no_expiry_field_of_its_own(self):
        """L'expiration est portée par les CONTRATS P2.21/P2.26, jamais
        par RealGenerationAuthorization elle-même (déjà confirmé par
        P2.30 -- re-vérifié ici comme partie de l'audit frontière)."""

        auth = RealGenerationAuthorization(request_id="005", authorized_by_human=True)
        field_names = {f for f in auth.__dataclass_fields__}
        self.assertNotIn("expires_at", field_names)
        self.assertNotIn("expiry", field_names)
        self.assertNotIn("ttl", field_names)

    def test_malformed_authorization_object_rejected(self):
        stack = self._stack()
        request = _conforming_request(real_generation_authorization="not-an-authorization-object")
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)

    def test_replayed_authorization_after_execution_still_blocked(self):
        stack = self._stack()
        request = _conforming_request()
        rs, pa = stack.prepared(request)
        outcome = stack.job_service.execute(
            request, interval_seconds=0, activation_contract=rs, provider_activation_contract=pa
        )
        self.assertTrue(outcome.succeeded)

        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)

    def test_new_authorization_after_execution_still_blocked(self):
        stack = self._stack()
        request = _conforming_request()
        rs, pa = stack.prepared(request)
        stack.job_service.execute(
            request, interval_seconds=0, activation_contract=rs, provider_activation_contract=pa
        )

        fresh_request = _conforming_request(
            real_generation_authorization=RealGenerationAuthorization(
                request_id="005", authorized_by_human=True
            )
        )
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(fresh_request)


# ------------------------------------------------------------------ #
# 9. P2.21 / 10. P2.26
# ------------------------------------------------------------------ #


class Test09_P221(_TmpDirTestCase):
    def test_request_scoped_single_use(self):
        stack = self._stack()
        request = _conforming_request()
        rs, _ = stack.prepared(request)
        stack.activation_service.validate_activation(request, rs)
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.validate_activation(request, rs)

    def test_foreign_p2_21_contract_rejected_by_a_different_service_instance(self):
        stack_a = self._stack()
        stack_b = self._stack()
        request = _conforming_request()
        rs_a = stack_a.activation_service.prepare_activation(request)
        with self.assertRaises(ActivationRejectedError):
            stack_b.activation_service.validate_activation(request, rs_a)


class Test10_P226(_TmpDirTestCase):
    def test_wrong_request_id_activation_id_model_duration_resolution_aspect(self):
        stack = self._stack()
        request = _conforming_request()
        rs, pa = stack.prepared(request)

        mismatches = [
            ("job_type", "other_model"),
            ("duration", 5),
            ("resolution", "1080p"),
            ("aspect_ratio", "16:9"),
        ]
        for field_name, bad_value in mismatches:
            bad_pa = pa.__class__(**{**pa.__dict__, field_name: bad_value})
            reasons = stack.provider_activation_service.inspect(request, rs, bad_pa)
            self.assertTrue(reasons, f"expected rejection for {field_name}")

    def test_expired_revoked_consumed(self):
        stack = self._stack()
        request = _conforming_request()

        # expired
        rs1, pa1 = stack.prepared(request)
        stack.provider_activation_service._issued_at[pa1.activation_id] -= 301
        self.assertTrue(stack.provider_activation_service.inspect(request, rs1, pa1))

        # revoked
        request2 = _conforming_request()
        rs2, pa2 = stack.prepared(request2)
        stack.provider_activation_service.revoke(pa2)
        self.assertTrue(stack.provider_activation_service.inspect(request2, rs2, pa2))

        # consumed
        request3 = _conforming_request()
        rs3, pa3 = stack.prepared(request3)
        stack.provider_activation_service.validate(request3, rs3, pa3)
        self.assertTrue(stack.provider_activation_service.inspect(request3, rs3, pa3))


# ------------------------------------------------------------------ #
# 11. Execution Gate
# ------------------------------------------------------------------ #


class Test11_ExecutionGate(_TmpDirTestCase):
    def test_gate_approved_does_not_itself_call_create_job(self):
        # Phase D : plafond de FIXTURE explicite (sans effet sur le Mock reconnu).
        stack = self._stack(
            provider=_SpyProvider(cost_per_job=67.5, available_credits=100.0),
            max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST,
        )
        stack.execution_gate = RealProviderExecutionGate(
            stack.gate, stack.identity_lock, stack.activation_service,
            stack.provider_activation_service, job_service=stack.job_service,
        )
        request = _conforming_request()
        rs, pa = stack.prepared(request)
        report = stack.execution_gate.evaluate(
            request, activation_contract=rs, provider_activation_contract=pa
        )
        self.assertEqual(report.decision, RealProviderExecutionDecision.APPROVED)
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_gate_module_has_zero_create_job_calls_in_its_own_source(self):
        text = (PROJECT_ROOT / "agents" / "real_provider_execution_gate.py").read_text(
            encoding="utf-8-sig"
        )
        calls = [
            n for n in ast.walk(ast.parse(text))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "create_job"
        ]
        self.assertEqual(calls, [])


# ------------------------------------------------------------------ #
# 12. Provider disabled / 13. Client inaccessible
# ------------------------------------------------------------------ #


class Test12_13_ProviderDisabledClientInaccessible(_TmpDirTestCase):
    def test_real_provider_refuses_even_with_fully_simulated_valid_chain(self):
        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)
        real_provider.get_model = lambda job_type: ModelSchema(
            job_type=job_type, display_name=job_type,
            params=(
                ModelParam(name="prompt", type="string", required=True),
                ModelParam(name="duration", type="integer", required=False, default=5),
                ModelParam(name="resolution", type="string", required=False, default="720p",
                           enum=("480p", "720p", "1080p", "4k")),
                ModelParam(name="aspect_ratio", type="string", required=False, default="16:9",
                           enum=("9:16", "16:9")),
                ModelParam(name="start_image", type="object|null", required=False, default=None),
                ModelParam(name="image_references", type="array", required=False, default=None),
            ),
            raw={},
        )
        real_provider.estimate_cost = (
            lambda job_type, prompt, duration=None, resolution=None, aspect_ratio=None:
            CostEstimate(job_type=job_type, credits=67.5, raw={"credits": 67.5})
        )
        real_provider.get_account_balance = lambda: 1000.0

        # Phase D : plafond de FIXTURE explicite (chemin réel).
        stack = self._stack(provider=real_provider, max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST)
        request = _conforming_request()

        self.assertEqual(stack.gate.evaluate(request).decision.value, "APPROVED")

        rs = stack.activation_service.prepare_activation(request)
        with self.assertRaises(ControlledRealProviderActivationRejectedError):
            stack.provider_activation_service.prepare(request, rs)

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(job_type="seedance_2_0", prompt=_real_prompt())

        fake_client.create_job.assert_not_called()
        fake_client.run.assert_not_called()
        fake_client.get_model.assert_not_called()
        fake_client.estimate_cost.assert_not_called()
        fake_client.account_status.assert_not_called()

    def test_self_client_never_referenced_in_real_create_job(self):
        text = (PROJECT_ROOT / "integrations" / "higgsfield" / "provider.py").read_text(
            encoding="utf-8-sig"
        )
        tree = ast.parse(text)
        node = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "create_job"
            and any(isinstance(s, ast.Raise) for s in n.body)
        )
        client_refs = [
            n for n in ast.walk(node)
            if isinstance(n, ast.Attribute) and n.attr == "client"
            and isinstance(n.value, ast.Name) and n.value.id == "self"
        ]
        self.assertEqual(client_refs, [])


# ------------------------------------------------------------------ #
# 14. Exactly one create_job call-site
# ------------------------------------------------------------------ #


class Test14_CallSiteInvariant(unittest.TestCase):
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
                    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                            and node.func.attr == "create_job"):
                        offenders.append(str(path.relative_to(PROJECT_ROOT)))
        director_text = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8-sig")
        for node in ast.walk(ast.parse(director_text)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "create_job"):
                offenders.append("director.py")
        self.assertEqual(offenders, [])

        gjs_text = (PROJECT_ROOT / "agents" / "generation_job_service.py").read_text(
            encoding="utf-8-sig"
        )
        real_calls = [
            n for n in ast.walk(ast.parse(gjs_text))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "create_job"
        ]
        self.assertEqual(len(real_calls), 1)


# ------------------------------------------------------------------ #
# 15. Replay / 16. UNKNOWN
# ------------------------------------------------------------------ #


class Test15_16_ReplayUnknown(_TmpDirTestCase):
    def test_already_executed_never_calls_create_job(self):
        # Phase D : plafond de FIXTURE explicite (sans effet sur le Mock reconnu).
        stack = self._stack(
            provider=_SpyProvider(cost_per_job=67.5, available_credits=100.0),
            max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST,
        )
        stack.job_service = GenerationJobService(
            stack.provider, stack.gate, lock=stack.lock,
            activation_service=stack.activation_service,
            provider_activation_service=stack.provider_activation_service,
        )
        request = _conforming_request()
        rs, pa = stack.prepared(request)
        stack.job_service.execute(
            request, interval_seconds=0, activation_contract=rs, provider_activation_contract=pa
        )
        self.assertEqual(len(stack.provider._jobs), 1)

        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(
                _conforming_request(
                    real_generation_authorization=RealGenerationAuthorization(
                        request_id="005", authorized_by_human=True
                    )
                )
            )
        self.assertEqual(len(stack.provider._jobs), 1)

    def test_unknown_request_never_calls_create_job(self):
        provider = _SpyProvider(cost_per_job=67.5, available_credits=100.0)
        stack = self._stack(provider=provider)
        request = _conforming_request()
        stack.gate.executed_request_store.mark_unknown("005", reason="test-induced UNKNOWN")

        decision = stack.gate.evaluate(request).decision
        self.assertEqual(decision, GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN)
        self.assertEqual(len(provider._jobs), 0)


# ------------------------------------------------------------------ #
# 17. Crash safety
# ------------------------------------------------------------------ #


class Test17_CrashSafety(_TmpDirTestCase):
    def test_mark_executed_failure_yields_unknown(self):
        stack = self._stack()
        request = _conforming_request()
        rs, pa = stack.prepared(request)

        def _boom(request_id):
            raise RuntimeError("simulated mark_executed failure")

        stack.gate.mark_executed = _boom

        with self.assertRaises(GenerationJobUnknownStateError):
            stack.job_service.execute(
                request, interval_seconds=0, activation_contract=rs, provider_activation_contract=pa
            )
        self.assertTrue(stack.gate.is_unknown("005"))

    def test_mark_executed_and_mark_unknown_both_failing_yields_unrecorded_error(self):
        stack = self._stack()
        request = _conforming_request()
        rs, pa = stack.prepared(request)

        stack.gate.mark_executed = lambda request_id: (_ for _ in ()).throw(RuntimeError("boom1"))
        stack.gate.mark_unknown = lambda request_id, reason="": (_ for _ in ()).throw(RuntimeError("boom2"))

        with self.assertRaises(CriticalStateUnknownAndUnrecordedError):
            stack.job_service.execute(
                request, interval_seconds=0, activation_contract=rs, provider_activation_contract=pa
            )


# ------------------------------------------------------------------ #
# 18. Freshness / TOCTOU
# ------------------------------------------------------------------ #


class Test18_FreshnessTOCTOU(_TmpDirTestCase):
    def test_prompt_mutated_between_preflight_and_execution_rejected(self):
        stack = self._stack()
        request = _conforming_request()
        rs, pa = stack.prepared(request)

        mutated_request = _conforming_request(prompt=request.prompt + " mutated after preflight")
        reasons = stack.provider_activation_service.inspect(mutated_request, rs, pa)
        self.assertTrue(any("prompt" in r.lower() for r in reasons))

    def test_balance_drop_between_preflight_and_execution_rejected(self):
        provider = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=100.0)
        stack = self._stack(provider=provider)
        request = _conforming_request()
        rs, pa = stack.prepared(request)

        provider._available_credits = 1.41  # balance drops after preflight
        with self.assertRaises(ControlledRealProviderActivationRejectedError):
            stack.provider_activation_service.validate(request, rs, pa)


# ------------------------------------------------------------------ #
# 19. Mock positive path / 20. Real negative path
# ------------------------------------------------------------------ #


class Test19_MockPositivePath(_TmpDirTestCase):
    def test_full_mock_chain_approved_and_executes_without_real_provider(self):
        stack = self._stack()
        request = _conforming_request()
        rs, pa = stack.prepared(request)

        self.assertEqual(stack.gate.evaluate(request).decision.value, "APPROVED")
        gate_report = stack.execution_gate.evaluate(
            request, activation_contract=rs, provider_activation_contract=pa
        )
        self.assertEqual(gate_report.decision, RealProviderExecutionDecision.APPROVED)

        outcome = stack.job_service.execute(
            request, interval_seconds=0, activation_contract=rs, provider_activation_contract=pa
        )
        self.assertTrue(outcome.succeeded)
        is_real = type(stack.job_service.provider).create_job is HiggsfieldProvider.create_job
        self.assertFalse(is_real)


class Test20_RealNegativePath(_TmpDirTestCase):
    def test_real_provider_direct_call_still_blocked(self):
        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(job_type="seedance_2_0", prompt="x")
        fake_client.create_job.assert_not_called()


# ------------------------------------------------------------------ #
# 21. No global enable / 22. No bypass / 23. No automatic authorization
# ------------------------------------------------------------------ #


class Test21_22_SecurityScan(unittest.TestCase):
    def test_no_forbidden_global_authority_tokens(self):
        offenders = []
        excluded = {"agents/production_activation_boundary.py"}
        for base in ("agents", "integrations", "scripts"):
            base_dir = PROJECT_ROOT / base
            if not base_dir.exists():
                continue
            for path in base_dir.rglob("*.py"):
                rel = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
                if rel in excluded:
                    continue
                text = path.read_text(encoding="utf-8-sig")
                for token in FORBIDDEN_GLOBAL_AUTHORITY_TOKENS:
                    found = (
                        re.search(r"\b" + re.escape(token) + r"\b", text) is not None
                        if token.isidentifier() else token in text
                    )
                    if found:
                        offenders.append((rel, token))
        director_text = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8-sig")
        for token in FORBIDDEN_GLOBAL_AUTHORITY_TOKENS:
            found = (
                re.search(r"\b" + re.escape(token) + r"\b", director_text) is not None
                if token.isidentifier() else token in director_text
            )
            if found:
                offenders.append(("director.py", token))
        self.assertEqual(offenders, [])


class Test23_NoAutomaticAuthorization(unittest.TestCase):
    def test_no_real_generation_authorization_construction_anywhere_in_production_code(self):
        offenders = []
        for base in ("agents",):
            for path in (PROJECT_ROOT / base).rglob("*.py"):
                text = path.read_text(encoding="utf-8-sig")
                for node in ast.walk(ast.parse(text)):
                    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                            and node.func.id == "RealGenerationAuthorization"):
                        offenders.append(str(path.relative_to(PROJECT_ROOT)))
        director_text = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8-sig")
        for node in ast.walk(ast.parse(director_text)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "RealGenerationAuthorization"):
                offenders.append("director.py")
        self.assertEqual(offenders, [])


# ------------------------------------------------------------------ #
# 24. Rollback boundary
# ------------------------------------------------------------------ #


class Test24_RollbackBoundary(unittest.TestCase):
    def test_real_create_job_is_self_contained_single_raise_reachable_and_no_self_assignment(self):
        text = (PROJECT_ROOT / "integrations" / "higgsfield" / "provider.py").read_text(
            encoding="utf-8-sig"
        )
        tree = ast.parse(text)
        node = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "create_job"
            and any(isinstance(s, ast.Raise) for s in n.body)
        )
        self.assertIsInstance(node.body[-1], ast.Raise)
        self.assertEqual([n for n in ast.walk(node) if isinstance(n, ast.Return)], [])
        self_assignments = [
            n for n in ast.walk(node)
            if isinstance(n, (ast.Assign, ast.AugAssign))
            for target in (n.targets if isinstance(n, ast.Assign) else [n.target])
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        ]
        self.assertEqual(self_assignments, [])


if __name__ == "__main__":
    unittest.main()
