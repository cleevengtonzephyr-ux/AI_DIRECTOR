"""
Tests — Phase P2.39 : FINAL PRODUCTION CONTRACT & ACTIVATION SIMULATION.

SIMULATION ONLY. Ce fichier ne construit ni ne modifie aucun mécanisme
de production -- il compose exclusivement des mécanismes déjà existants
et validés (P2.11/15/16/18/20/21/24/25/26/29/32/35/36/37/38, tous
inchangés) pour démontrer, de bout en bout, que l'architecture complète
transporte une autorisation explicite, l'identité exacte de Video 005,
le budget, la fraîcheur, le replay/UNKNOWN, la Critical Section et les
paramètres du Provider -- jusqu'à un `MockHiggsfieldProvider`, JAMAIS
jusqu'au vrai `HiggsfieldClient`.

REAL BALANCE (lecture seule, hors de ce fichier, cf. rapport P2.39) :
1.41 credits. AUCUN test ici n'utilise ce nombre pour approuver quoi
que ce soit -- le budget "suffisant" utilisé par les scénarios positifs
est TOUJOURS une valeur injectée dans un `MockHiggsfieldProvider` de
test (typiquement 100.0), jamais écrite quelque part comme solde réel,
jamais lue depuis Higgsfield, et jamais utilisée par le vrai Provider.
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
from agents.generation_job_service import (
    CriticalStateUnknownAndUnrecordedError,
    GenerationJobService,
    GenerationJobUnknownStateError,
)
from agents.production_activation_boundary import FORBIDDEN_GLOBAL_AUTHORITY_TOKENS
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
SIMULATED_SUFFICIENT_BALANCE = 100.0
SIMULATED_INSUFFICIENT_BALANCE = 1.41  # mirrors the REAL balance, injected only

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
            request_id=C.request_id, authorized_by_human=True,
            note="P2.39 SIMULATION ONLY -- never a real human authorization.",
        ),
    )
    defaults.update(overrides)
    return GenerationRequest(**defaults)


class _Stack:
    """Simulation stack -- ALWAYS a MockHiggsfieldProvider unless a
    `provider` override is explicitly passed for the real-provider
    negative-path tests (which use a MagicMock client, never a real
    subprocess)."""

    def __init__(self, tmp_dir: Path, cost_per_job=67.5, available_credits=SIMULATED_SUFFICIENT_BALANCE, provider=None):
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
            self.gate, self.identity_lock, self.activation_service,
            self.provider_activation_service, job_service=self.job_service,
        )
        self.report_service = FinalReportService(
            self.provider, self.gate, job_service=self.job_service
        )

    def prepared(self, request):
        rs_contract = self.activation_service.prepare_activation(request)
        pa_contract = self.provider_activation_service.prepare(request, rs_contract)
        return rs_contract, pa_contract


class _TmpDirTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_39_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def _stack(self, **kwargs) -> _Stack:
        return _Stack(self._tmp, **kwargs)


# ------------------------------------------------------------------ #
# 1-3. Canonical identity / prompt / asset (live recompute)
# ------------------------------------------------------------------ #


class Test01_03_CanonicalIdentity(unittest.TestCase):
    def test_canonical_video_005_exact(self):
        self.assertEqual(C.request_id, "005")
        self.assertEqual(C.job_type, "seedance_2_0")
        self.assertEqual(C.duration, 15)
        self.assertEqual(C.resolution, "720p")
        self.assertEqual(C.aspect_ratio, "9:16")

    def test_prompt_identity_live(self):
        import hashlib

        prompt = _real_prompt()
        self.assertEqual(len(prompt), 7284)
        self.assertEqual(len(prompt.splitlines()), 265)
        self.assertEqual(
            hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "1c498617adb4603bcf2fc114a9cb9e8fe2219f09285adbff4d1e6c7a10a669e1",
        )

    def test_asset_identity_live(self):
        import hashlib

        def sha256_of(path):
            h = hashlib.sha256()
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            return h.hexdigest()

        self.assertEqual(
            sha256_of(REAL_AVATAR_PATH),
            "d293e41a63f66fd43afbebee3f7f9f1bd29143b465fa57a18ab4e1df5faf7280",
        )
        self.assertEqual(
            sha256_of(REAL_FACE_PATH),
            "df83a97b71cff9a90191c19d15ff989228b9fef2e57c96cf7c76c68652e3a343",
        )


# ------------------------------------------------------------------ #
# 4. Simulated budget approval
# ------------------------------------------------------------------ #


class Test04_SimulatedBudget(_TmpDirTestCase):
    def test_simulated_sufficient_balance_never_touches_real_account(self):
        stack = self._stack(cost_per_job=67.5, available_credits=SIMULATED_SUFFICIENT_BALANCE)
        self.assertIsInstance(stack.provider, MockHiggsfieldProvider)
        self.assertEqual(stack.provider.get_account_balance(), SIMULATED_SUFFICIENT_BALANCE)
        self.assertNotEqual(SIMULATED_SUFFICIENT_BALANCE, 1.41)  # never confused with the real balance


# ------------------------------------------------------------------ #
# 5. Human authorization simulation
# ------------------------------------------------------------------ #


class Test05_HumanAuthorizationSimulation(unittest.TestCase):
    def test_simulated_authorization_is_a_real_typed_object_never_persisted(self):
        auth = RealGenerationAuthorization(
            request_id="005", authorized_by_human=True, note="SIMULATED ONLY"
        )
        self.assertIsInstance(auth, RealGenerationAuthorization)
        self.assertTrue(auth.authorized_by_human)
        self.assertEqual(auth.request_id, "005")
        # Not persisted anywhere: constructing a second one yields a
        # distinct authorization_id -- no shared/global registry exists.
        auth2 = RealGenerationAuthorization(request_id="005", authorized_by_human=True)
        self.assertNotEqual(auth.authorization_id, auth2.authorization_id)

    def test_director_never_constructs_authorization_automatically(self):
        import director
        for method_name in (
            "run_video_mission",
            "check_activation_preflight",
            "check_real_provider_execution_gate",
            "check_activation_readiness",
            "prepare_real_generation_activation",
            "execute_real_generation_activation",
        ):
            import inspect
            source = inspect.getsource(getattr(director.AIDirector, method_name))
            tree = ast.parse(_dedent(source))
            calls = [
                n for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "RealGenerationAuthorization"
            ]
            self.assertEqual(calls, [], method_name)


def _dedent(source: str) -> str:
    import textwrap
    return textwrap.dedent(source)


# ------------------------------------------------------------------ #
# 6. P2.21 / 7. P2.26 contracts
# ------------------------------------------------------------------ #


class Test06_07_ContractCreation(_TmpDirTestCase):
    def test_p2_21_contract_fields_exact(self):
        stack = self._stack()
        request = _conforming_request()
        rs = stack.activation_service.prepare_activation(request)
        self.assertEqual(rs.request_id, "005")
        self.assertEqual(rs.job_type, "seedance_2_0")
        self.assertEqual(rs.duration, 15)
        self.assertEqual(rs.resolution, "720p")
        self.assertEqual(rs.aspect_ratio, "9:16")
        self.assertEqual(rs.authorization_id, request.real_generation_authorization.authorization_id)
        self.assertTrue(rs.activation_id)

    def test_p2_26_contract_fields_exact_and_bound_to_p2_21(self):
        stack = self._stack()
        request = _conforming_request()
        rs, pa = stack.prepared(request)
        self.assertEqual(pa.request_id, "005")
        self.assertEqual(pa.request_scoped_activation_id, rs.activation_id)
        self.assertEqual(pa.job_type, "seedance_2_0")
        self.assertEqual(pa.duration, 15)
        self.assertEqual(pa.resolution, "720p")
        self.assertEqual(pa.aspect_ratio, "9:16")
        self.assertEqual(pa.prompt_sha256, C.prompt_sha256)
        self.assertEqual(pa.avatar_sha256, C.avatar_master_sha256)
        self.assertEqual(pa.face_reference_sha256, C.face_reference_sha256)
        self.assertEqual(pa.authorization_id, request.real_generation_authorization.authorization_id)
        self.assertEqual(pa.expected_cost_credits, 67.5)


# ------------------------------------------------------------------ #
# 8. Execution Gate
# ------------------------------------------------------------------ #


class Test08_ExecutionGate(_TmpDirTestCase):
    def test_execution_gate_approved_is_not_real_generation_authorized(self):
        stack = self._stack()
        request = _conforming_request()
        rs, pa = stack.prepared(request)
        report = stack.execution_gate.evaluate(
            request, activation_contract=rs, provider_activation_contract=pa
        )
        self.assertEqual(report.decision, RealProviderExecutionDecision.APPROVED)
        # APPROVED alone creates nothing:
        self.assertEqual(len(stack.provider._jobs), 0)


# ------------------------------------------------------------------ #
# 9. Final fresh checks / 10. Critical Section / 11. Captured payload
# 12. Mock execution / 13. FinalReport
# ------------------------------------------------------------------ #


class Test09_13_GoldenPathAndPayloadCapture(_TmpDirTestCase):
    def test_full_simulation_golden_path_with_exact_payload_capture(self):
        stack = self._stack()
        request = _conforming_request()
        rs, pa = stack.prepared(request)

        # Étape 8 : re-verify everything fresh immediately before
        # simulating execution -- nothing from `prepared()` above is
        # trusted as final authority.
        self.assertEqual(stack.gate.evaluate(request).decision, GenerationApprovalDecision.APPROVED)
        self.assertEqual(
            stack.provider_activation_service.inspect(request, rs, pa), []
        )

        report = stack.report_service.generate(
            request, interval_seconds=0, activation_contract=rs, provider_activation_contract=pa
        )

        # 12/13. FinalReport truthfulness.
        self.assertEqual(report.status, FinalReportStatus.EXECUTED_PASS)
        self.assertEqual(report.approval_decision, GenerationApprovalDecision.APPROVED)
        self.assertEqual(report.activation_decision, ActivationDecision.APPROVED)
        self.assertEqual(report.provider_activation_decision, ActivationDecision.APPROVED)
        self.assertTrue(report.job_created)
        self.assertFalse(report.real_provider_called)
        self.assertEqual(report.execution_state, "EXECUTED")

        # 11. Captured payload -- exactly what would have been sent to
        # the real Provider, compared field-by-field to canonical
        # Video 005.
        job = stack.provider._jobs[report.job_id]
        self.assertEqual(job["job_type"], "seedance_2_0")
        self.assertEqual(job["prompt"], _real_prompt())
        self.assertEqual(job["params"]["duration"], 15)
        self.assertEqual(job["params"]["resolution"], "720p")
        self.assertEqual(job["params"]["aspect_ratio"], "9:16")
        self.assertEqual(job["request_id"], "005")
        self.assertEqual(job["avatar_sha256"], C.avatar_master_sha256)
        self.assertEqual(job["face_reference_sha256"], C.face_reference_sha256)
        captured_contract = job["provider_activation_contract"]
        self.assertEqual(captured_contract.authorization_id, request.real_generation_authorization.authorization_id)
        self.assertEqual(captured_contract.request_scoped_activation_id, rs.activation_id)
        self.assertEqual(captured_contract.activation_id, pa.activation_id)
        self.assertEqual(captured_contract.expected_cost_credits, 67.5)


# ------------------------------------------------------------------ #
# 14. Replay after simulation
# ------------------------------------------------------------------ #


class Test14_ReplayAfterSimulation(_TmpDirTestCase):
    def test_replay_after_mock_execution_is_blocked_no_second_job(self):
        stack = self._stack()
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
        self.assertEqual(
            stack.gate.evaluate(request).decision, GenerationApprovalDecision.ALREADY_EXECUTED
        )


# ------------------------------------------------------------------ #
# 15. UNKNOWN simulation
# ------------------------------------------------------------------ #


class Test15_UnknownSimulation(_TmpDirTestCase):
    def test_mark_executed_failure_yields_unknown_no_retry(self):
        stack = self._stack()
        request = _conforming_request()
        rs, pa = stack.prepared(request)
        stack.gate.mark_executed = lambda request_id: (_ for _ in ()).throw(RuntimeError("simulated"))

        with self.assertRaises(GenerationJobUnknownStateError):
            stack.job_service.execute(
                request, interval_seconds=0, activation_contract=rs, provider_activation_contract=pa
            )
        self.assertTrue(stack.gate.is_unknown("005"))
        self.assertEqual(
            stack.gate.evaluate(request).decision, GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN
        )

    def test_mark_unknown_also_failing_yields_unrecorded_error(self):
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
# 16. Authorization mutations (A-F)
# ------------------------------------------------------------------ #


class Test16_AuthorizationMutations(_TmpDirTestCase):
    def test_A_missing_authorization(self):
        stack = self._stack()
        request = _conforming_request(real_generation_authorization=None)
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)

    def test_B_authorization_for_006_used_with_005(self):
        stack = self._stack()
        request = _conforming_request(
            real_generation_authorization=RealGenerationAuthorization(
                request_id="006", authorized_by_human=True
            )
        )
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)

    def test_C_authorization_expired_no_field_exists_so_use_p2_21_contract_expiry_instead(self):
        """`RealGenerationAuthorization` porte volontairement AUCUN
        champ d'expiration propre (P2.30, re-confirmé P2.38) --
        l'expiration est une propriété du CONTRAT P2.21/P2.26, jamais
        de l'autorisation. Ce test démontre donc l'expiration au niveau
        où elle existe réellement."""

        stack = self._stack()
        request = _conforming_request()
        rs = stack.activation_service.prepare_activation(request)
        stack.activation_service._issued_at[rs.activation_id] -= 301
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.validate_activation(request, rs)

    def test_D_malformed_authorization(self):
        stack = self._stack()
        request = _conforming_request(real_generation_authorization=object())
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.prepare_activation(request)

    def test_E_consumed_authorization_replayed(self):
        stack = self._stack()
        request = _conforming_request()
        rs = stack.activation_service.prepare_activation(request)
        stack.activation_service.validate_activation(request, rs)
        with self.assertRaises(ActivationRejectedError):
            stack.activation_service.validate_activation(request, rs)

    def test_F_approved_true_without_human_authorization(self):
        stack = self._stack()
        request = _conforming_request(real_generation_authorization=None)
        self.assertTrue(request.approved)
        self.assertNotEqual(
            stack.gate.evaluate(request).decision, GenerationApprovalDecision.APPROVED
        )


# ------------------------------------------------------------------ #
# 17. Contract mutations (P2.21 + P2.26 fields)
# ------------------------------------------------------------------ #


class Test17_ContractMutations(_TmpDirTestCase):
    def test_p2_26_field_mutations_all_rejected(self):
        stack = self._stack()
        request = _conforming_request()
        rs, pa = stack.prepared(request)

        for field_name, bad_value in (
            ("request_id", "006"),
            ("request_scoped_activation_id", "not-the-real-one"),
            ("job_type", "other_model"),
            ("duration", 5),
            ("resolution", "1080p"),
            ("aspect_ratio", "16:9"),
            ("prompt_sha256", "0" * 64),
            ("avatar_sha256", "0" * 64),
            ("face_reference_sha256", "0" * 64),
        ):
            bad_pa = pa.__class__(**{**pa.__dict__, field_name: bad_value})
            reasons = stack.provider_activation_service.inspect(request, rs, bad_pa)
            self.assertTrue(reasons, f"expected rejection for mutated {field_name}")

    def test_authorization_id_is_traceability_only_not_a_security_boundary(self):
        """Étape 16 (rapport P2.39) : contrairement à request_id/job_type/
        duration/resolution/aspect_ratio/prompt/avatar/face (tous
        re-vérifiés contre la requête live, cf. test ci-dessus),
        `authorization_id` reste délibérément NON re-vérifié ici -- il
        n'a jamais été, et ne peut pas être, une frontière de sécurité :
        `RealGenerationAuthorization` n'a aucun mécanisme de révocation
        propre (confirmé par P2.30 :
        test_no_module_level_registry_of_authorizations_anywhere), donc
        TOUTE autorisation valide (authorized_by_human=True, request_id
        correspondant -- re-vérifiées fraîchement par _fresh_violations()
        à chaque appel) accorde une autorité STRICTEMENT ÉQUIVALENTE
        pour cette requête, quel que soit son authorization_id précis.
        Ce champ reste un identifiant de traçabilité opaque, jamais une
        preuve d'autorité (cf. docstring de
        ControlledRealProviderActivationContract, inchangé)."""

        stack = self._stack()
        request = _conforming_request()
        rs, pa = stack.prepared(request)

        bad_pa = pa.__class__(**{**pa.__dict__, "authorization_id": "not-the-real-auth-id"})
        reasons = stack.provider_activation_service.inspect(request, rs, bad_pa)
        self.assertEqual(reasons, [])

    def test_expiry_revoke_consumed(self):
        stack = self._stack()

        req_a = _conforming_request()
        rs_a, pa_a = stack.prepared(req_a)
        stack.provider_activation_service._issued_at[pa_a.activation_id] -= 301
        self.assertTrue(stack.provider_activation_service.inspect(req_a, rs_a, pa_a))

        req_b = _conforming_request()
        rs_b, pa_b = stack.prepared(req_b)
        stack.provider_activation_service.revoke(pa_b)
        self.assertTrue(stack.provider_activation_service.inspect(req_b, rs_b, pa_b))

        req_c = _conforming_request()
        rs_c, pa_c = stack.prepared(req_c)
        stack.provider_activation_service.validate(req_c, rs_c, pa_c)
        self.assertTrue(stack.provider_activation_service.inspect(req_c, rs_c, pa_c))


# ------------------------------------------------------------------ #
# 18-20. Identity mutations after preparation (prompt/asset/format)
# ------------------------------------------------------------------ #


class Test18_20_IdentityMutationsAfterPreparation(_TmpDirTestCase):
    def test_prompt_avatar_face_model_duration_resolution_aspect_mutation_after_preparation(self):
        stack = self._stack()
        request = _conforming_request()
        rs, pa = stack.prepared(request)

        mutation_kwargs_list = [
            dict(prompt=request.prompt + " mutated"),
            dict(start_image=MediaReference(role="master_avatar", source=str(REAL_FACE_PATH), sha256=None)),
            dict(image_references=(MediaReference(role="face_reference", source=str(REAL_AVATAR_PATH), sha256=None),)),
            dict(job_type="other_model"),
            dict(duration=5),
            dict(resolution="1080p"),
            dict(aspect_ratio="16:9"),
        ]
        for kwargs in mutation_kwargs_list:
            mutated = _conforming_request(**{**{}, **kwargs})
            reasons = stack.provider_activation_service.inspect(mutated, rs, pa)
            self.assertTrue(reasons, f"expected rejection for mutation {kwargs.keys()}")
        # No job was ever created by any of these inspections.
        self.assertEqual(len(stack.provider._jobs), 0)


# ------------------------------------------------------------------ #
# 21. Budget mutation
# ------------------------------------------------------------------ #


class Test21_BudgetMutation(_TmpDirTestCase):
    def test_balance_drops_to_simulated_insufficient_between_prepare_and_execute(self):
        provider = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=SIMULATED_SUFFICIENT_BALANCE)
        stack = self._stack(provider=provider)
        request = _conforming_request()
        rs, pa = stack.prepared(request)

        provider._available_credits = SIMULATED_INSUFFICIENT_BALANCE
        with self.assertRaises(ControlledRealProviderActivationRejectedError):
            stack.provider_activation_service.validate(request, rs, pa)
        self.assertEqual(len(provider._jobs), 0)


# ------------------------------------------------------------------ #
# 22. Real provider negative path / 23. Real client sentinel
# ------------------------------------------------------------------ #


class Test22_23_RealProviderNegativePath(_TmpDirTestCase):
    def test_fully_simulated_valid_chain_still_blocked_by_real_provider(self):
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
        real_provider.get_account_balance = lambda: 1000.0  # simulated-sufficient, never real

        stack = self._stack(provider=real_provider)
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

    def test_mock_success_does_not_imply_real_provider_called(self):
        stack = self._stack()
        request = _conforming_request()
        rs, pa = stack.prepared(request)
        report = stack.report_service.generate(
            request, interval_seconds=0, activation_contract=rs, provider_activation_contract=pa
        )
        self.assertTrue(report.job_created)
        self.assertFalse(report.real_provider_called)


# ------------------------------------------------------------------ #
# 24. Exactly one production create_job call-site
# ------------------------------------------------------------------ #


class Test24_CallSiteInvariant(unittest.TestCase):
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

    def test_real_client_access_zero_in_real_create_job(self):
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
        client_calls = [
            n for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "create_job" and isinstance(n.func.value, ast.Attribute)
            and n.func.value.attr == "client"
        ]
        self.assertEqual(client_refs, [])
        self.assertEqual(client_calls, [])


# ------------------------------------------------------------------ #
# 25. No global switch / 26. No automatic authorization
# ------------------------------------------------------------------ #


class Test25_NoGlobalSwitch(unittest.TestCase):
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


class Test26_NoAutomaticAuthorization(unittest.TestCase):
    def test_no_real_generation_authorization_construction_in_production_code(self):
        offenders = []
        for path in (PROJECT_ROOT / "agents").rglob("*.py"):
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
# 27. Rollback simulation
# ------------------------------------------------------------------ #


class Test27_RollbackSimulation(_TmpDirTestCase):
    def test_simulation_can_be_stopped_before_any_provider_call_leaving_no_trace(self):
        stack = self._stack()
        request = _conforming_request()
        rs, pa = stack.prepared(request)

        # Stop here -- never call execute()/report_service.generate().
        # Confirm the "rollback" state (nothing happened) holds:
        self.assertEqual(len(stack.provider._jobs), 0)
        self.assertFalse(stack.gate.is_already_executed("005"))
        self.assertFalse(stack.gate.is_unknown("005"))

        # And the real provider remains closed regardless, unaffected
        # by any of the above:
        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(job_type="seedance_2_0", prompt="x")
        fake_client.create_job.assert_not_called()


# ------------------------------------------------------------------ #
# 28. State isolation
# ------------------------------------------------------------------ #


class Test28_StateIsolation(unittest.TestCase):
    def test_no_real_state_files_touched_by_this_module(self):
        self.assertFalse((PROJECT_ROOT / "state" / "executed_requests.json").exists())


if __name__ == "__main__":
    unittest.main()
