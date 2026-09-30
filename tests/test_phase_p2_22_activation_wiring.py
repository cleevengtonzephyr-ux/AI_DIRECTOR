"""
Tests — Phase P2.22 : CONTROLLED ACTIVATION WIRING & FINAL
PRE-GENERATION SAFETY BOUNDARY.

Verrouille le câblage introduit cette phase :
`GenerationJobService.execute(request, activation_contract=None)`
(agents/generation_job_service.py) valide désormais, DANS le
FileCriticalSectionLock, un `RequestScopedActivationContract` fourni
EXPLICITEMENT (jamais créé implicitement), juste après l'approbation
fraîche du Gate et juste avant `create_job()`.

Ce fichier prouve, avec le VRAI `FileCriticalSectionLock` (jamais un
mock du verrou) et les VRAIS fichiers/prompt de Video 005, que même un
contrat intégralement validé (Gate APPROVED, Identity Lock conforme,
double consentement présent, replay clean) ne fait JAMAIS franchir la
dernière protection : `HiggsfieldProvider.create_job()` réel continue
de lever `HiggsfieldRealGenerationDisabledError`, et
`fake_client.create_job` n'est jamais appelé. Aucun mock n'est
utilisé pour prétendre qu'une génération réelle a eu lieu (Étape 16) :
`MockHiggsfieldProvider` sert uniquement à démontrer les chemins de
sécurité et le câblage, jamais un succès réel.
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
from agents.executed_request_store import FileExecutedRequestStore
from agents.final_report_service import FinalReportService, FinalReportStatus
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from tests.real_provider_path_fixtures import FIXTURE_MAX_COST_CREDITS_PER_REQUEST
from tests.authorization_content_helpers import bind_request
from agents.generation_job_service import (
    GenerationJobActivationRejectedError,
    GenerationJobExecutionError,
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
    """
    Assemble une pile complète (Provider Mock -> Gate -> Identity Lock
    -> ActivationService -> Lock réel -> GenerationJobService), comme
    le fait `director.py::_build_default_report_service()`, mais avec
    `MockHiggsfieldProvider` et un répertoire de verrous temporaire.
    """

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


class P2_22_TestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_22_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def _stack(self, **kwargs) -> _WiredStack:
        return _WiredStack(self._tmp, **kwargs)


# ----------------------------------------------------------------------
# A. Explicit contract required (never created implicitly)
# ----------------------------------------------------------------------


class TestA_ExplicitContractRequired(P2_22_TestCase):
    def test_execute_without_contract_never_touches_activation_service(self):
        stack = self._stack()
        stack.job_service.activation_service = MagicMock(wraps=stack.activation_service)

        outcome = stack.job_service.execute(_conforming_request(), interval_seconds=0)

        self.assertTrue(outcome.succeeded)
        stack.job_service.activation_service.prepare_activation.assert_not_called()
        stack.job_service.activation_service.validate_activation.assert_not_called()

    def test_contract_supplied_without_activation_service_configured_raises(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
        service = RequestScopedActivationService(gate, identity_lock)
        job_service = GenerationJobService(provider, gate)  # activation_service=None

        request = _conforming_request()
        contract = service.prepare_activation(request)

        with self.assertRaises(ValueError):
            job_service.execute(request, activation_contract=contract, interval_seconds=0)
        self.assertEqual(len(provider._jobs), 0)


# ----------------------------------------------------------------------
# B/C. Contract identity binding (exact request_id + exact content)
# ----------------------------------------------------------------------


class TestBC_ContractIdentityBinding(P2_22_TestCase):
    def test_contract_bound_to_005_rejected_for_006(self):
        stack = self._stack()
        contract = stack.activation_service.prepare_activation(_conforming_request())

        request_006 = _conforming_request(
            request_id="006", real_generation_authorization=_valid_auth("006")
        )
        # Rejeté DEUX FOIS en profondeur : d'abord par le propre
        # fresh Gate.evaluate() d'execute() (identity_lock injecté
        # dans le Gate lui-même -> INVALID_REQUEST, avant même
        # d'atteindre validate_activation()) -- defense in depth
        # attendue, cf. GenerationJobExecutionError générique plutôt
        # que la sous-classe spécifique au contrat.
        with self.assertRaises(GenerationJobExecutionError):
            stack.job_service.execute(
                request_006, activation_contract=contract, interval_seconds=0
            )
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_exact_content_match_required_for_005(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)

        outcome = stack.job_service.execute(
            request, activation_contract=contract, interval_seconds=0
        )
        self.assertTrue(outcome.succeeded)


# ----------------------------------------------------------------------
# D/E/F. Double consent
# ----------------------------------------------------------------------


class TestDEF_DoubleConsent(P2_22_TestCase):
    def test_missing_authorization_rejected_before_create_job(self):
        stack = self._stack()
        request = _conforming_request(real_generation_authorization=None)

        with self.assertRaises(GenerationJobExecutionError):
            stack.job_service.execute(request, interval_seconds=0)
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_wrong_authorization_rejected_before_create_job(self):
        stack = self._stack()
        request = _conforming_request(
            real_generation_authorization=_valid_auth("not-005")
        )
        with self.assertRaises(GenerationJobExecutionError):
            stack.job_service.execute(request, interval_seconds=0)
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_valid_double_consent_with_contract_succeeds_on_mock(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)

        outcome = stack.job_service.execute(
            request, activation_contract=contract, interval_seconds=0
        )
        self.assertTrue(outcome.succeeded)
        self.assertEqual(len(stack.provider._jobs), 1)


# ----------------------------------------------------------------------
# G/H. Freshness -- stale balance / stale cost
# ----------------------------------------------------------------------


class TestGH_Freshness(P2_22_TestCase):
    def test_stale_balance_blocks_execute_with_contract(self):
        stack = self._stack(cost_per_job=10.0, available_credits=100.0)
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)

        stack.provider._available_credits = 1.41  # Solde frais, différent.

        # execute()'s OWN fresh Gate.evaluate() (avant même
        # validate_activation()) relit déjà le solde à cet instant et
        # bloque -- defense in depth : GenerationJobExecutionError
        # générique, la requête n'atteint jamais la vérification du
        # contrat.
        with self.assertRaises(GenerationJobExecutionError):
            stack.job_service.execute(
                request, activation_contract=contract, interval_seconds=0
            )
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_stale_cost_blocks_execute_with_contract(self):
        stack = self._stack(cost_per_job=10.0, available_credits=100.0)
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)

        stack.provider._cost_per_job = 1000.0  # Coût frais, différent.

        with self.assertRaises(GenerationJobExecutionError):
            stack.job_service.execute(
                request, activation_contract=contract, interval_seconds=0
            )
        self.assertEqual(len(stack.provider._jobs), 0)


# ----------------------------------------------------------------------
# I/J/K/L. Prompt / asset / model / format mutation
# ----------------------------------------------------------------------


class TestIJKL_Mutation(P2_22_TestCase):
    def test_prompt_mutation_blocks_execute(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)

        mutated = _conforming_request(prompt=request.prompt + " ")
        with self.assertRaises(GenerationJobExecutionError):
            stack.job_service.execute(
                mutated, activation_contract=contract, interval_seconds=0
            )
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_asset_mutation_blocks_execute(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)

        mutated = _conforming_request(
            start_image=MediaReference(
                role="master_avatar", source=str(REAL_FACE_PATH), sha256=None
            )
        )
        with self.assertRaises(GenerationJobExecutionError):
            stack.job_service.execute(
                mutated, activation_contract=contract, interval_seconds=0
            )
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_model_mutation_blocks_execute(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)

        mutated = _conforming_request(job_type="other_model")
        with self.assertRaises(GenerationJobExecutionError):
            stack.job_service.execute(
                mutated, activation_contract=contract, interval_seconds=0
            )
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_format_mutation_blocks_execute(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)

        mutated = _conforming_request(aspect_ratio="16:9")
        with self.assertRaises(GenerationJobExecutionError):
            stack.job_service.execute(
                mutated, activation_contract=contract, interval_seconds=0
            )
        self.assertEqual(len(stack.provider._jobs), 0)


# ----------------------------------------------------------------------
# M/N. ALREADY_EXECUTED / UNKNOWN
# ----------------------------------------------------------------------


class TestMN_ReplayAndUnknown(P2_22_TestCase):
    def test_already_executed_blocks_execute_even_with_valid_contract(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)

        stack.gate.mark_executed(request.request_id)

        with self.assertRaises(GenerationJobExecutionError) as ctx:
            stack.job_service.execute(
                request, activation_contract=contract, interval_seconds=0
            )
        self.assertEqual(
            ctx.exception.approval.decision, GenerationApprovalDecision.ALREADY_EXECUTED
        )
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_unknown_state_blocks_execute_even_with_valid_contract(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)

        stack.gate.mark_unknown(request.request_id, reason="test")

        with self.assertRaises(GenerationJobExecutionError) as ctx:
            stack.job_service.execute(
                request, activation_contract=contract, interval_seconds=0
            )
        self.assertEqual(
            ctx.exception.approval.decision,
            GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN,
        )
        self.assertEqual(len(stack.provider._jobs), 0)


# ----------------------------------------------------------------------
# O/P/Q. Contract lifetime -- expired / consumed / foreign
# ----------------------------------------------------------------------


class TestOPQ_ContractLifetime(P2_22_TestCase):
    def test_expired_contract_blocks_execute(self):
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
            job_service.execute(
                request, activation_contract=contract, interval_seconds=0
            )
        self.assertEqual(len(provider._jobs), 0)

    def test_consumed_contract_blocks_a_second_execute(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)

        # Consommé manuellement (simule un premier usage légitime déjà
        # validé ailleurs), isolé de tout replay guard sur la requête
        # elle-même -- prouve que le rejet vient bien du contrat.
        stack.activation_service.validate_activation(request, contract)

        with self.assertRaises(GenerationJobActivationRejectedError) as ctx:
            stack.job_service.execute(
                request, activation_contract=contract, interval_seconds=0
            )
        self.assertTrue(
            any(
                "already been consumed" in r
                for r in ctx.exception.activation_rejection.reasons
            )
        )
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_foreign_contract_blocks_execute(self):
        stack_a = self._stack()
        other_tmp = Path(tempfile.mkdtemp(prefix="p2_22_other_"))
        self.addCleanup(shutil.rmtree, other_tmp, ignore_errors=True)
        stack_b = _WiredStack(other_tmp)

        request = _conforming_request()
        foreign_contract = stack_b.activation_service.prepare_activation(request)

        with self.assertRaises(GenerationJobActivationRejectedError):
            stack_a.job_service.execute(
                request, activation_contract=foreign_contract, interval_seconds=0
            )
        self.assertEqual(len(stack_a.provider._jobs), 0)


# ----------------------------------------------------------------------
# R/S. Critical section -- lock busy / release on exception
# ----------------------------------------------------------------------


class TestRS_CriticalSection(P2_22_TestCase):
    def test_lock_busy_blocks_execute_even_with_valid_contract(self):
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)

        with stack.lock.acquire(request.request_id):
            with self.assertRaises(CriticalSectionBusyError):
                stack.job_service.execute(
                    request, activation_contract=contract, interval_seconds=0
                )
        self.assertEqual(len(stack.provider._jobs), 0)

    def test_lock_released_after_activation_rejection_exception(self):
        # Scénario qui atteint RÉELLEMENT validate_activation() (le
        # fresh Gate.evaluate() d'execute() reste APPROVED : la
        # requête elle-même n'a pas encore été exécutée) -- seul le
        # contrat, déjà consommé manuellement, est rejeté --
        # GenerationJobActivationRejectedError levée DANS le verrou.
        stack = self._stack()
        request = _conforming_request()
        contract = stack.activation_service.prepare_activation(request)
        stack.activation_service.validate_activation(request, contract)  # consumed

        with self.assertRaises(GenerationJobActivationRejectedError):
            stack.job_service.execute(
                request, activation_contract=contract, interval_seconds=0
            )

        self.assertFalse((self._tmp / "005.lock").exists())
        with stack.lock.acquire("005"):
            pass  # Doit réussir : le verrou a bien été libéré.


# ----------------------------------------------------------------------
# T/U/V. Provider still disabled -- the actual security boundary
# ----------------------------------------------------------------------


class TestTUV_ProviderStillDisabled(P2_22_TestCase):
    def test_fully_validated_contract_still_hits_disabled_real_provider(self):
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
        # Phase D : fixtures de TEST explicites (plafond + Identity Lock) ;
        # sans elles, la Gate bloque le chemin réel avant create_job().
        gate = GenerationApprovalGate(
            real_provider,
            identity_lock=identity_lock,
            max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST,
        )
        activation_service = RequestScopedActivationService(gate, identity_lock)
        lock = FileCriticalSectionLock(self._tmp)
        job_service = GenerationJobService(
            real_provider, gate, lock=lock, activation_service=activation_service
        )

        request = _conforming_request()

        # Chaque étage est prouvé "vert" AVANT le dernier appel :
        contract = activation_service.prepare_activation(request)  # OK
        approval = gate.evaluate(request)
        self.assertEqual(approval.decision, GenerationApprovalDecision.APPROVED)

        # ONLY THEN would create_job() be eligible -- et c'est
        # exactement là que le Provider réel bloque encore tout.
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            job_service.execute(
                request, activation_contract=contract, interval_seconds=0
            )

        fake_client.create_job.assert_not_called()
        # Le verrou réel a bien été libéré malgré l'exception.
        self.assertFalse((self._tmp / "005.lock").exists())

    def test_no_real_generation_no_credits_no_real_network(self):
        import inspect

        import agents.activation_contract as activation_module
        import agents.generation_job_service as job_module

        for module in (activation_module, job_module):
            self.assertFalse(hasattr(module, "requests"))
            self.assertFalse(hasattr(module, "socket"))
            imported_names = {
                name
                for name, value in vars(module).items()
                if inspect.ismodule(value) or inspect.isclass(value)
            }
            self.assertNotIn("HiggsfieldClient", imported_names)


# ----------------------------------------------------------------------
# W. Video 005 canonical integrity (independently recomputed)
# ----------------------------------------------------------------------


class TestW_Video005Integrity(unittest.TestCase):
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
        self.assertEqual(len(C.prompt_sha256), 64)
        self.assertEqual(
            C.avatar_master_sha256,
            "d293e41a63f66fd43afbebee3f7f9f1bd29143b465fa57a18ab4e1df5faf7280",
        )
        self.assertEqual(
            C.face_reference_sha256,
            "df83a97b71cff9a90191c19d15ff989228b9fef2e57c96cf7c76c68652e3a343",
        )

    def test_prompt_recomputed_live_from_real_prompt_assembly_system(self):
        import hashlib

        prompt = _real_prompt()
        self.assertEqual(len(prompt), C.prompt_chars)
        self.assertEqual(len(prompt.splitlines()), C.prompt_lines)
        self.assertEqual(
            hashlib.sha256(prompt.encode("utf-8")).hexdigest(), C.prompt_sha256
        )

    def test_asset_files_recomputed_live_from_disk(self):
        import hashlib

        def _sha256(path):
            h = hashlib.sha256()
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    h.update(chunk)
            return h.hexdigest()

        self.assertEqual(_sha256(REAL_AVATAR_PATH), C.avatar_master_sha256)
        self.assertEqual(_sha256(REAL_FACE_PATH), C.face_reference_sha256)


# ----------------------------------------------------------------------
# X. wait_for_job() remains outside the lock
# ----------------------------------------------------------------------


class TestX_WaitForJobOutsideLock(P2_22_TestCase):
    def test_lock_file_absent_during_wait_for_job(self):
        lock_dir = self._tmp
        observed = {"lock_present_during_poll": None}

        # Phase D : Mock RECONNU ; seul `wait_for_job` (hors frontière
        # `create_job`) est instrumenté, sur l'instance.
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)

        def _lock_checking_wait_for_job(job_id, timeout_seconds=600, interval_seconds=0):
            observed["lock_present_during_poll"] = (
                lock_dir / "005.lock"
            ).exists()
            return MockHiggsfieldProvider.wait_for_job(
                provider, job_id, timeout_seconds=timeout_seconds, interval_seconds=interval_seconds
            )

        provider.wait_for_job = _lock_checking_wait_for_job
        identity_lock = ReleaseCandidateIdentityLock(C)
        # Phase D : plafond de FIXTURE explicite (sans effet sur le Mock reconnu).
        gate = GenerationApprovalGate(
            provider, identity_lock=identity_lock, max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST
        )
        activation_service = RequestScopedActivationService(gate, identity_lock)
        lock = FileCriticalSectionLock(lock_dir)
        job_service = GenerationJobService(
            provider, gate, lock=lock, activation_service=activation_service
        )

        request = _conforming_request()
        contract = activation_service.prepare_activation(request)

        outcome = job_service.execute(
            request, activation_contract=contract, interval_seconds=0
        )

        self.assertTrue(outcome.succeeded)
        self.assertIs(observed["lock_present_during_poll"], False)


# ----------------------------------------------------------------------
# Y. No global activation flag anywhere in the wiring
# ----------------------------------------------------------------------


class TestY_NoGlobalActivationFlag(unittest.TestCase):
    FORBIDDEN_TOKENS = (
        "enabled=True",
        "enabled = True",
        "real_generation_enabled",
        "activate_higgsfield",
        "skip_gate",
        "skip_approval",
        "force_generation",
    )

    def test_no_forbidden_global_activation_tokens_in_wiring_modules(self):
        for relative_path in (
            "agents/activation_contract.py",
            "agents/generation_job_service.py",
            "agents/final_report_service.py",
            "director.py",
        ):
            text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
            for token in self.FORBIDDEN_TOKENS:
                self.assertNotIn(
                    token, text, f"forbidden token {token!r} found in {relative_path}"
                )

    def test_no_class_or_instance_level_enabled_flag_on_job_service(self):
        provider = MockHiggsfieldProvider()
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
        job_service = GenerationJobService(provider, gate)
        self.assertFalse(hasattr(job_service, "enabled"))
        self.assertFalse(hasattr(GenerationJobService, "enabled"))
        self.assertFalse(hasattr(job_service, "real_generation_enabled"))


# ----------------------------------------------------------------------
# Z. RealGenerationAuthorization is never persisted
# ----------------------------------------------------------------------


class TestZ_AuthorizationNotPersisted(P2_22_TestCase):
    def test_executed_requests_file_never_contains_authorization_fields(self):
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

        request = _conforming_request()
        contract = activation_service.prepare_activation(request)
        job_service.execute(request, activation_contract=contract, interval_seconds=0)

        raw_text = store_path.read_text(encoding="utf-8")
        for forbidden in (
            "authorized_by_human",
            "authorization_id",
            "RealGenerationAuthorization",
            "note",
        ):
            self.assertNotIn(forbidden, raw_text)

    def test_activation_contract_object_carries_no_authorization_object(self):
        provider = MockHiggsfieldProvider()
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
        service = RequestScopedActivationService(gate, identity_lock)

        contract = service.prepare_activation(_conforming_request())
        contract_fields = contract.__dict__
        self.assertNotIn("real_generation_authorization", contract_fields)
        self.assertNotIn("authorized_by_human", contract_fields)


if __name__ == "__main__":
    unittest.main()
