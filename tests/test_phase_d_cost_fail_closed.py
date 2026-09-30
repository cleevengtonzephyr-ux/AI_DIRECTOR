"""
Tests — Phase D : coûts en échec fermé.

Verrouille les correctifs de coût de la Phase D :

1. un coût UNKNOWN n'est jamais APPROVED, même avec approbation
   explicite et autorisation humaine liée au contenu ;
2. un coût ou un solde non fini, négatif ou d'un type inattendu n'est
   jamais exploité comme un montant (NaN, +inf, -inf, négatif, bool,
   chaîne) ;
3. un plafond par requête explicitement configuré bloque tout coût
   supérieur, à la Gate et dans le contrat P2.26 ;
4. `expected_cost_credits` du contrat P2.26 doit correspondre au coût
   que la Gate évalue au moment de `validate()` ;
5. sur le chemin du vrai `HiggsfieldProvider`, un plafond par requête
   absent ou inexploitable, ou un Identity Lock absent, donne BLOCKED
   avant toute estimation, consommation ou création de job -- y compris
   pour la chaîne construite par `AIDirector`, qui ne configure aucun
   plafond.

Les plafonds utilisés ici sont des valeurs FICTIVES de test, alignées
sur le coût simulé : aucun montant réel n'est choisi par ces tests.

MOCK-ONLY : `MockHiggsfieldProvider` ou vrai `HiggsfieldProvider` sur un
client factice (`MagicMock`, jamais de réseau ni de sous-processus),
stores en mémoire ou temporaires. Aucun `create_job()` réel, aucun
accès au `state/` réel.
"""

import dataclasses
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import ActivationRejectedError, RequestScopedActivationService
from agents.controlled_real_provider_activation import (
    ControlledRealProviderActivationRejectedError,
    ControlledRealProviderActivationService,
)
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from agents.generation_cost_service import (
    CostEstimationStatus,
    GenerationCostResult,
    GenerationCostService,
    is_usable_credit_amount,
)
from agents.activation_readiness import ActivationReadinessEvaluator
from agents.executed_request_store import FileExecutedRequestStore
from agents.final_report_service import FinalReportService, FinalReportStatus
from agents.generation_job_service import (
    GenerationJobExecutionError,
    GenerationJobProviderNotAllowedError,
    GenerationJobService,
)
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.release_candidate_identity_lock import (
    ReleaseCandidateIdentityLock,
    VIDEO_005_RELEASE_CANDIDATE,
)
from director import AIDirector
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import BaseHiggsfieldProvider, HiggsfieldProvider
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.types import CostEstimate, Job, JobStatus, MediaReference
from tests.authorization_content_helpers import (
    REAL_AVATAR_PATH,
    REAL_FACE_PATH,
    bind_request,
    content_media,
    video_005_authorization,
)
from tests.test_phase_b_authorization_single_use import isolated_director_state

D = GenerationApprovalDecision
C = VIDEO_005_RELEASE_CANDIDATE

class _IntSubclass(int):
    pass


class _FloatSubclass(float):
    pass


INVALID_AMOUNTS = {
    "NaN": float("nan"),
    "+inf": float("inf"),
    "-inf": float("-inf"),
    "negative": -1.0,
    "negative int": -1,
    # Trop grand pour un float : `math.isfinite()` lèverait OverflowError.
    "huge int": 10 ** 400,
    "huge negative int": -(10 ** 400),
    "int subclass": _IntSubclass(10),
    "float subclass": _FloatSubclass(10.0),
    "bool True": True,
    "bool False": False,
    "string": "10",
    "None": None,
    "list": [10.0],
}


def _request(**overrides) -> GenerationRequest:
    defaults = dict(
        **content_media(),
        request_id="phase-d",
        job_type="seedance_2_0",
        prompt="Phase D mock-only prompt.",
        duration=5,
        resolution="720p",
        aspect_ratio="9:16",
        approved=True,
    )
    defaults.update(overrides)
    if "real_generation_authorization" not in overrides:
        defaults["real_generation_authorization"] = RealGenerationAuthorization(
            request_id=defaults["request_id"], authorized_by_human=True
        )
    return bind_request(GenerationRequest(**defaults))


class _FixedCostService:
    """Cost service injecté qui renvoie un résultat arbitraire (défense en
    profondeur de la Gate contre un service qui mentirait sur KNOWN)."""

    def __init__(self, result: GenerationCostResult):
        self.result = result

    def estimate(self, **_kwargs) -> GenerationCostResult:
        return self.result


# ----------------------------------------------------------------------
# 1. Montants exploitables : une seule définition
# ----------------------------------------------------------------------


class UsableCreditAmount(unittest.TestCase):
    def test_finite_non_negative_numbers_are_usable(self):
        for value in (0, 0.0, 10, 67.5):
            with self.subTest(value=value):
                self.assertTrue(is_usable_credit_amount(value))

    def test_invalid_amounts_are_never_usable(self):
        for label, value in INVALID_AMOUNTS.items():
            with self.subTest(case=label):
                self.assertFalse(is_usable_credit_amount(value))

    def test_never_raises_even_for_values_that_cannot_be_converted(self):
        class _Hostile:
            def __float__(self):
                raise RuntimeError("never convertible")

            def __ge__(self, other):
                raise RuntimeError("never comparable")

        for value in (10 ** 400, -(10 ** 400), 10 ** 10000, _Hostile(), object(), b"10", 1j):
            with self.subTest(value=type(value).__name__):
                self.assertIs(is_usable_credit_amount(value), False)

    def test_large_but_finite_int_is_usable(self):
        self.assertTrue(is_usable_credit_amount(10 ** 300))


# ----------------------------------------------------------------------
# 2. GenerationCostService : jamais KNOWN pour un montant invalide
# ----------------------------------------------------------------------


class CostServiceNeverKnownForInvalidCost(unittest.TestCase):
    def test_invalid_cost_is_unknown_not_known(self):
        for label, value in INVALID_AMOUNTS.items():
            with self.subTest(case=label):
                result = GenerationCostService(MockHiggsfieldProvider(cost_per_job=value)).estimate(
                    job_type="seedance_2_0", prompt="P"
                )
                self.assertEqual(result.status, CostEstimationStatus.UNKNOWN)

    def test_non_cost_estimate_response_is_error(self):
        provider = MockHiggsfieldProvider()
        for response in (None, {"credits": 10.0}, 10.0):
            with self.subTest(response=response):
                provider.estimate_cost = lambda **_kwargs: response
                result = GenerationCostService(provider).estimate(job_type="seedance_2_0", prompt="P")
                self.assertEqual(result.status, CostEstimationStatus.ERROR)


# ----------------------------------------------------------------------
# 3. Gate : UNKNOWN et montants invalides ne mènent jamais à APPROVED
# ----------------------------------------------------------------------


class GateUnknownCostNeverApproved(unittest.TestCase):
    def test_unknown_cost_with_approval_and_authorization_is_blocked(self):
        provider = MockHiggsfieldProvider(cost_per_job=None)
        result = GenerationApprovalGate(provider).evaluate(_request())
        self.assertEqual(result.decision, D.BLOCKED)
        self.assertTrue(any("never approvable" in r for r in result.reasons), result.reasons)

    def test_unknown_cost_without_approval_states_it_is_never_approvable(self):
        provider = MockHiggsfieldProvider(cost_per_job=None)
        result = GenerationApprovalGate(provider).evaluate(_request(approved=False))
        self.assertEqual(result.decision, D.NEEDS_APPROVAL)
        self.assertTrue(any("never approvable" in r for r in result.reasons), result.reasons)

    def test_invalid_cost_values_never_approve(self):
        for label, value in INVALID_AMOUNTS.items():
            with self.subTest(case=label):
                provider = MockHiggsfieldProvider(cost_per_job=value, available_credits=100.0)
                result = GenerationApprovalGate(provider).evaluate(_request())
                self.assertNotEqual(result.decision, D.APPROVED)
                self.assertEqual(len(provider._jobs), 0)

    def test_injected_cost_service_cannot_pass_an_invalid_known_cost(self):
        for label, value in INVALID_AMOUNTS.items():
            with self.subTest(case=label):
                provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
                lying = _FixedCostService(
                    GenerationCostResult(
                        status=CostEstimationStatus.KNOWN,
                        job_type="seedance_2_0",
                        estimate=CostEstimate(job_type="seedance_2_0", credits=value),
                    )
                )
                result = GenerationApprovalGate(provider, cost_service=lying).evaluate(_request())
                self.assertEqual(result.decision, D.BLOCKED)

    def test_unexpected_cost_status_never_approves(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        odd = _FixedCostService(
            GenerationCostResult(
                status="known-ish",
                job_type="seedance_2_0",
                estimate=CostEstimate(job_type="seedance_2_0", credits=10.0),
            )
        )
        result = GenerationApprovalGate(provider, cost_service=odd).evaluate(_request())
        self.assertNotEqual(result.decision, D.APPROVED)


class GateInvalidBalanceNeverApproved(unittest.TestCase):
    def test_invalid_balance_is_blocked(self):
        for label, value in INVALID_AMOUNTS.items():
            if value is None:
                continue  # déjà couvert : solde None -> BLOCKED (Phase G)
            with self.subTest(case=label):
                provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=value)
                result = GenerationApprovalGate(provider).evaluate(_request())
                self.assertEqual(result.decision, D.BLOCKED)
                self.assertEqual(len(provider._jobs), 0)


# ----------------------------------------------------------------------
# 4. Gate : plafond par requête explicitement configuré
# ----------------------------------------------------------------------


class GatePerRequestCeiling(unittest.TestCase):
    def test_cost_above_configured_ceiling_is_blocked(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider, max_cost_credits_per_request=9.99)
        result = gate.evaluate(_request())
        self.assertEqual(result.decision, D.BLOCKED)
        self.assertTrue(any("ceiling" in r for r in result.reasons), result.reasons)

    def test_cost_above_ceiling_is_blocked_even_without_approval(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider, max_cost_credits_per_request=9.99)
        self.assertEqual(gate.evaluate(_request(approved=False)).decision, D.BLOCKED)

    def test_cost_equal_to_ceiling_is_approvable(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider, max_cost_credits_per_request=10.0)
        self.assertEqual(gate.evaluate(_request()).decision, D.APPROVED)

    def test_invalid_ceiling_is_refused_at_construction(self):
        provider = MockHiggsfieldProvider()
        for label, value in INVALID_AMOUNTS.items():
            if value is None:
                continue  # None == aucun plafond configuré
            with self.subTest(case=label):
                with self.assertRaises(ValueError):
                    GenerationApprovalGate(provider, max_cost_credits_per_request=value)

    def test_no_ceiling_by_default(self):
        self.assertIsNone(GenerationApprovalGate(MockHiggsfieldProvider()).max_cost_credits_per_request)


# ----------------------------------------------------------------------
# 5. Contrat P2.26 : coût attendu lié au coût autorisé et au plafond
# ----------------------------------------------------------------------


def _conforming_request() -> GenerationRequest:
    return bind_request(
        GenerationRequest(
            request_id=C.request_id,
            job_type=C.job_type,
            prompt=PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id),
            duration=C.duration,
            resolution=C.resolution,
            aspect_ratio=C.aspect_ratio,
            approved=True,
            start_image=MediaReference(role="master_avatar", source=str(REAL_AVATAR_PATH)),
            image_references=(MediaReference(role="face_reference", source=str(REAL_FACE_PATH)),),
            real_generation_authorization=RealGenerationAuthorization(
                request_id=C.request_id, authorized_by_human=True
            ),
        )
    )


class ProviderContractExpectedCost(unittest.TestCase):
    COST = 67.5

    def _stack(self, ceiling=None):
        self.provider = MockHiggsfieldProvider(cost_per_job=self.COST, available_credits=100.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(
            self.provider, identity_lock=identity_lock, max_cost_credits_per_request=ceiling
        )
        activation_service = RequestScopedActivationService(gate, identity_lock)
        service = ControlledRealProviderActivationService(gate, identity_lock, activation_service)
        request = _conforming_request()
        rs_contract = activation_service.prepare_activation(request)
        return service, request, rs_contract

    def _rejection_reasons(self, service, request, rs_contract, contract):
        with self.assertRaises(ControlledRealProviderActivationRejectedError) as caught:
            service.validate(request, rs_contract, contract)
        self.assertEqual(service.inspect(request, rs_contract, contract), caught.exception.reasons)
        return caught.exception.reasons

    def test_contract_within_configured_ceiling_validates(self):
        service, request, rs_contract = self._stack(ceiling=self.COST)
        contract = service.prepare(request, rs_contract)
        self.assertEqual(contract.expected_cost_credits, self.COST)
        self.assertIs(service.validate(request, rs_contract, contract), contract)

    def test_prepare_refused_when_cost_exceeds_configured_ceiling(self):
        service, request, rs_contract = self._stack(ceiling=self.COST)
        self.provider._cost_per_job = self.COST + 0.5
        with self.assertRaises(ControlledRealProviderActivationRejectedError):
            service.prepare(request, rs_contract)

    def test_forged_expected_cost_above_ceiling_is_refused(self):
        service, request, rs_contract = self._stack(ceiling=self.COST)
        contract = service.prepare(request, rs_contract)
        forged = dataclasses.replace(contract, expected_cost_credits=self.COST + 100.0)
        reasons = self._rejection_reasons(service, request, rs_contract, forged)
        self.assertTrue(any("ceiling" in r for r in reasons), reasons)
        self.assertTrue(any("does not match the cost currently authorized" in r for r in reasons), reasons)

    def test_forged_lower_expected_cost_is_refused(self):
        service, request, rs_contract = self._stack()
        contract = service.prepare(request, rs_contract)
        forged = dataclasses.replace(contract, expected_cost_credits=1.0)
        reasons = self._rejection_reasons(service, request, rs_contract, forged)
        self.assertTrue(any("does not match the cost currently authorized" in r for r in reasons), reasons)

    def test_invalid_expected_cost_in_contract_is_refused(self):
        service, request, rs_contract = self._stack()
        contract = service.prepare(request, rs_contract)
        for label, value in INVALID_AMOUNTS.items():
            with self.subTest(case=label):
                forged = dataclasses.replace(contract, expected_cost_credits=value)
                reasons = self._rejection_reasons(service, request, rs_contract, forged)
                self.assertTrue(
                    any("not a finite, non-negative number of credits" in r for r in reasons), reasons
                )

    def test_cost_becoming_unknown_after_prepare_is_refused(self):
        service, request, rs_contract = self._stack()
        contract = service.prepare(request, rs_contract)
        self.provider._cost_per_job = None
        self._rejection_reasons(service, request, rs_contract, contract)

    def test_no_job_is_ever_created(self):
        service, request, rs_contract = self._stack(ceiling=self.COST)
        contract = service.prepare(request, rs_contract)
        service.validate(request, rs_contract, contract)
        self.assertEqual(len(self.provider._jobs), 0)


# ----------------------------------------------------------------------
# 6. Chemin du VRAI HiggsfieldProvider non configuré : BLOCKED
# ----------------------------------------------------------------------


def _fake_client(cost=67.5, balance=1000.0):
    """Client factice : jamais de réseau ni de sous-processus. Son
    `create_job` échoue bruyamment s'il était jamais atteint."""

    client = MagicMock()
    client.estimate_cost.return_value = {"credits": cost}
    client.account_status.return_value = {"credits": balance}
    client.get_model.return_value = {
        "job_type": C.job_type,
        "display_name": "d",
        "params": [
            {"name": "prompt", "type": "string", "required": True},
            {"name": "duration", "type": "integer", "required": False, "default": 5},
            {"name": "start_image", "type": "object|null", "required": False},
            {"name": "image_references", "type": "array", "required": False},
        ],
    }
    client.create_job.side_effect = AssertionError("real client create_job reached")
    return client


class RealProviderPathUnconfiguredIsBlocked(unittest.TestCase):
    """(a) Sans plafond par requête explicite ou sans Identity Lock, le
    chemin du vrai `HiggsfieldProvider` est BLOCKED -- avant toute
    estimation de coût, toute consommation et toute création de job --
    même quand tout le reste (approbation, autorisation liée au contenu,
    Identity Lock, solde) est favorable."""

    def setUp(self):
        self.client = _fake_client()
        self.provider = HiggsfieldProvider(client=self.client)
        self.request = _conforming_request()

    def _assert_blocked_before_any_call(self, result, *fragments):
        self.assertEqual(result.decision, D.BLOCKED, result.reasons)
        for fragment in fragments:
            self.assertTrue(any(fragment in r for r in result.reasons), result.reasons)
        self.assertIsNone(result.cost_result)
        self.client.estimate_cost.assert_not_called()
        self.client.account_status.assert_not_called()
        self.client.create_job.assert_not_called()

    def test_missing_ceiling_is_blocked_even_when_everything_else_is_valid(self):
        gate = GenerationApprovalGate(self.provider, identity_lock=ReleaseCandidateIdentityLock(C))
        self.assertTrue(gate.requires_real_path_protections())
        self.assertIsNone(gate.max_cost_credits_per_request)
        self._assert_blocked_before_any_call(gate.evaluate(self.request), "per-request credit ceiling")

    def test_missing_identity_lock_is_blocked_even_with_a_ceiling(self):
        gate = GenerationApprovalGate(self.provider, max_cost_credits_per_request=100.0)
        self._assert_blocked_before_any_call(gate.evaluate(self.request), "ReleaseCandidateIdentityLock")

    def test_missing_both_reports_both_reasons(self):
        gate = GenerationApprovalGate(self.provider)
        self._assert_blocked_before_any_call(
            gate.evaluate(self.request), "per-request credit ceiling", "ReleaseCandidateIdentityLock"
        )

    def test_unconfigured_real_path_is_blocked_not_needs_approval(self):
        gate = GenerationApprovalGate(self.provider, identity_lock=ReleaseCandidateIdentityLock(C))
        unapproved = dataclasses.replace(self.request, approved=False, real_generation_authorization=None)
        self._assert_blocked_before_any_call(gate.evaluate(unapproved), "per-request credit ceiling")

    def test_ceiling_made_unusable_after_construction_is_blocked(self):
        gate = GenerationApprovalGate(
            self.provider, identity_lock=ReleaseCandidateIdentityLock(C), max_cost_credits_per_request=100.0
        )
        for label, value in INVALID_AMOUNTS.items():
            with self.subTest(case=label):
                gate.max_cost_credits_per_request = value
                self._assert_blocked_before_any_call(gate.evaluate(self.request), "per-request credit ceiling")

    def test_non_identity_lock_object_is_not_accepted(self):
        gate = GenerationApprovalGate(
            self.provider, identity_lock=ReleaseCandidateIdentityLock(C), max_cost_credits_per_request=100.0
        )
        gate.identity_lock = MagicMock(violations=lambda request: [])
        self._assert_blocked_before_any_call(gate.evaluate(self.request), "ReleaseCandidateIdentityLock")

    def test_job_service_refuses_before_consumption_and_create_job(self):
        gate = GenerationApprovalGate(self.provider, identity_lock=ReleaseCandidateIdentityLock(C))
        with self.assertRaises(GenerationJobExecutionError) as caught:
            GenerationJobService(self.provider, gate).execute(self.request, interval_seconds=0)
        self.assertEqual(caught.exception.approval.decision, D.BLOCKED)
        self.assertFalse(
            gate.is_authorization_consumed(self.request.real_generation_authorization.authorization_id)
        )
        self.assertFalse(gate.is_already_executed(self.request.request_id))
        self.client.create_job.assert_not_called()

    def test_p2_26_expected_cost_refused_without_configured_ceiling(self):
        gate = GenerationApprovalGate(self.provider, identity_lock=ReleaseCandidateIdentityLock(C))
        identity_lock = ReleaseCandidateIdentityLock(C)
        service = ControlledRealProviderActivationService(
            gate, identity_lock, RequestScopedActivationService(gate, identity_lock)
        )
        reasons = service._expected_cost_violations(67.5)
        self.assertTrue(any("per-request credit ceiling" in r for r in reasons), reasons)
        self.client.create_job.assert_not_called()


# ----------------------------------------------------------------------
# 7. Classification du Provider : seul le Mock EXACT et intact est dispensé
# ----------------------------------------------------------------------


class _RecordingRealSubclass(HiggsfieldProvider):
    """Sous-classe du vrai Provider qui REDÉFINIT create_job()."""

    def create_job(self, job_type, prompt, **params):
        self.create_job_calls = getattr(self, "create_job_calls", 0) + 1
        raise AssertionError("create_job must never be reached from the Gate")


class _UnknownWrapper(BaseHiggsfieldProvider):
    """Provider inconnu qui enveloppe un Mock (wrapper) -- jamais reconnu."""

    def __init__(self):
        self.inner = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=1000.0)
        self.create_job_calls = 0

    def list_models(self, video=True):
        return self.inner.list_models(video)

    def get_model(self, job_type):
        return self.inner.get_model(job_type)

    def estimate_cost(self, *args, **kwargs):
        return self.inner.estimate_cost(*args, **kwargs)

    def get_account_balance(self):
        return self.inner.get_account_balance()

    def create_job(self, job_type, prompt, **params):
        self.create_job_calls += 1
        return self.inner.create_job(job_type, prompt, **params)

    def get_job(self, job_id):
        return self.inner.get_job(job_id)

    def wait_for_job(self, job_id, **kwargs):
        return self.inner.wait_for_job(job_id, **kwargs)


class _DuckTypedUnknownProvider:
    """Provider inconnu, sans lien de classe avec BaseHiggsfieldProvider :
    délègue au Mock, mais n'est pas un Mock."""

    def __init__(self):
        self.inner = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=1000.0)

    def __getattr__(self, name):
        return getattr(self.inner, name)


class _MockSubclassWithoutOverride(MockHiggsfieldProvider):
    pass


class _MockSubclassOverridingCreateJob(MockHiggsfieldProvider):
    def create_job(self, job_type, prompt, **params):
        raise AssertionError("create_job must never be reached from the Gate")


class _RealAndMock(HiggsfieldProvider, MockHiggsfieldProvider):
    pass


class _SpoofedMockClass(_DuckTypedUnknownProvider):
    """`isinstance()` le prendrait pour un Mock via `__class__` ; la Gate
    lit le type réel par `type()`."""

    @property
    def __class__(self):
        return MockHiggsfieldProvider


def _mock_with(**instance_overrides):
    provider = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=1000.0)
    for name, value in instance_overrides.items():
        setattr(provider, name, value)
    return provider


def _unrecognized_providers():
    return {
        "real HiggsfieldProvider subclass overriding create_job": lambda: _RecordingRealSubclass(client=_fake_client()),
        "real HiggsfieldProvider + Mock (multiple inheritance)": lambda: _RealAndMock(client=_fake_client()),
        "unknown BaseHiggsfieldProvider wrapper": _UnknownWrapper,
        "duck-typed unknown provider": _DuckTypedUnknownProvider,
        "MagicMock wrapping a Mock": lambda: MagicMock(
            wraps=MockHiggsfieldProvider(cost_per_job=67.5, available_credits=1000.0)
        ),
        "MagicMock with Mock spec": lambda: MagicMock(spec=MockHiggsfieldProvider),
        "Mock subclass without override": lambda: _MockSubclassWithoutOverride(
            cost_per_job=67.5, available_credits=1000.0
        ),
        "Mock subclass overriding create_job": lambda: _MockSubclassOverridingCreateJob(
            cost_per_job=67.5, available_credits=1000.0
        ),
        "Mock with create_job replaced on the instance": lambda: _mock_with(create_job=lambda *a, **k: None),
        "Mock with replaced job id source": lambda: _mock_with(_job_ids=iter(range(10))),
        "Mock with replaced job registry": lambda: _mock_with(_jobs=type("_Registry", (dict,), {})()),
        "object spoofing __class__": _SpoofedMockClass,
    }


_POSITIVE_UNRECOGNIZED = (
    ("real subclass", lambda: _RecordingRealSubclass(client=_fake_client())),
    ("unknown wrapper", _UnknownWrapper),
    (
        "MagicMock wrapper",
        lambda: MagicMock(wraps=MockHiggsfieldProvider(cost_per_job=67.5, available_credits=1000.0)),
    ),
)


class ProviderClassificationFailsClosed(unittest.TestCase):
    """Tout Provider autre qu'une instance EXACTE et intacte de
    `MockHiggsfieldProvider` exige plafond ET Identity Lock : sans l'un
    ou l'autre, BLOCKED avant toute estimation ou création de job, et
    aucune autorisation n'est consommée."""

    def setUp(self):
        self.request = _conforming_request()

    def _evaluate(self, provider, **gate_kwargs):
        gate = GenerationApprovalGate(provider, **gate_kwargs)
        return gate, gate.evaluate(self.request)

    def test_only_an_exact_intact_mock_is_recognized(self):
        gate = GenerationApprovalGate(MockHiggsfieldProvider())
        self.assertTrue(gate.is_recognized_test_mock())
        self.assertFalse(gate.requires_real_path_protections())
        for label, factory in _unrecognized_providers().items():
            with self.subTest(provider=label):
                gate = GenerationApprovalGate(factory())
                self.assertFalse(gate.is_recognized_test_mock())
                self.assertTrue(gate.requires_real_path_protections())

    def test_class_spoof_fools_isinstance_but_not_the_gate(self):
        spoof = _SpoofedMockClass()
        self.assertIsInstance(spoof, MockHiggsfieldProvider)  # isinstance() est trompé...
        self.assertFalse(GenerationApprovalGate(spoof).is_recognized_test_mock())  # ...la Gate non.

    def test_real_provider_itself_is_never_recognized(self):
        gate = GenerationApprovalGate(HiggsfieldProvider(client=_fake_client()))
        self.assertFalse(gate.is_recognized_test_mock())
        self.assertTrue(gate.requires_real_path_protections())

    def test_unrecognized_provider_without_ceiling_is_blocked(self):
        for label, factory in _unrecognized_providers().items():
            with self.subTest(provider=label):
                gate, result = self._evaluate(factory(), identity_lock=ReleaseCandidateIdentityLock(C))
                self.assertEqual(result.decision, D.BLOCKED, result.reasons)
                self.assertTrue(any("per-request credit ceiling" in r for r in result.reasons), result.reasons)
                self.assertIsNone(result.cost_result)
                self.assertFalse(
                    gate.is_authorization_consumed(self.request.real_generation_authorization.authorization_id)
                )

    def test_unrecognized_provider_without_identity_lock_is_blocked(self):
        for label, factory in _unrecognized_providers().items():
            with self.subTest(provider=label):
                _, result = self._evaluate(factory(), max_cost_credits_per_request=100.0)
                self.assertEqual(result.decision, D.BLOCKED, result.reasons)
                self.assertTrue(any("ReleaseCandidateIdentityLock" in r for r in result.reasons), result.reasons)
                self.assertIsNone(result.cost_result)

    def test_unrecognized_provider_never_reaches_create_job_through_the_job_service(self):
        for label, factory in _POSITIVE_UNRECOGNIZED:
            with self.subTest(provider=label):
                provider = factory()
                gate = GenerationApprovalGate(provider)
                # Refus à la frontière d'exécution, AVANT même l'évaluation :
                # aucune décision n'est attachée (plus strict que BLOCKED).
                with self.assertRaises(GenerationJobProviderNotAllowedError) as caught:
                    GenerationJobService(provider, gate).execute(self.request, interval_seconds=0)
                self.assertIsNone(caught.exception.approval)
                self.assertFalse(
                    gate.is_authorization_consumed(self.request.real_generation_authorization.authorization_id)
                )
                if isinstance(provider, MagicMock):
                    provider.create_job.assert_not_called()
                else:
                    self.assertEqual(getattr(provider, "create_job_calls", 0), 0)

    def test_both_protections_lift_only_the_real_path_block(self):
        # Avec plafond ET Identity Lock explicites, la GATE (décision de
        # politique seule) évalue normalement -- sans jamais appeler
        # create_job(). La frontière d'exécution, elle, refuse toujours
        # ces Providers (cf. ExecutionBoundaryNeverReachesUnsafeCreateJob).
        for label, factory in _POSITIVE_UNRECOGNIZED:
            with self.subTest(provider=label):
                provider = factory()
                gate, result = self._evaluate(
                    provider, identity_lock=ReleaseCandidateIdentityLock(C), max_cost_credits_per_request=100.0
                )
                self.assertEqual(result.decision, D.APPROVED, result.reasons)
                with self.assertRaises(GenerationJobProviderNotAllowedError):
                    GenerationJobService(provider, gate).execute(self.request, interval_seconds=0)
                self.assertFalse(
                    gate.is_authorization_consumed(self.request.real_generation_authorization.authorization_id)
                )
                if isinstance(provider, MagicMock):
                    provider.create_job.assert_not_called()
                else:
                    self.assertEqual(getattr(provider, "create_job_calls", 0), 0)

    def test_recognized_mock_without_ceiling_or_lock_can_still_be_approved(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)
        self.assertEqual(gate.evaluate(_request()).decision, D.APPROVED)
        self.assertEqual(provider._jobs, {})

    def test_detection_never_raises(self):
        class _Hostile:
            def __getattribute__(self, name):
                raise RuntimeError("hostile provider")

        for provider in (_Hostile(), None, 42):
            with self.subTest(provider=type(provider).__name__):
                gate = GenerationApprovalGate(provider)
                self.assertFalse(gate.is_recognized_test_mock())
                self.assertTrue(gate.requires_real_path_protections())

    def test_p2_26_expected_cost_requires_a_ceiling_for_unrecognized_providers(self):
        identity_lock = ReleaseCandidateIdentityLock(C)
        for label, provider, expected in (
            ("recognized mock", MockHiggsfieldProvider(), False),
            ("unknown wrapper", _UnknownWrapper(), True),
            ("real subclass", _RecordingRealSubclass(client=_fake_client()), True),
        ):
            with self.subTest(provider=label):
                gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
                service = ControlledRealProviderActivationService(
                    gate, identity_lock, RequestScopedActivationService(gate, identity_lock)
                )
                reasons = service._expected_cost_violations(67.5)
                self.assertEqual(any("per-request credit ceiling" in r for r in reasons), expected, reasons)


# ----------------------------------------------------------------------
# 8. Frontière d'exécution : create_job() jamais atteint par un Provider
#    non explicitement sûr, même avec plafond + Identity Lock valides
# ----------------------------------------------------------------------


def _tripwire_job(job_type):
    # Si un create_job() redéfini était atteint, il RÉUSSIRAIT : le test
    # échouerait alors sur `reached`, jamais masqué par une exception.
    return Job(job_id="tripwire-job", job_type=job_type, status=JobStatus.SUCCEEDED)


class _TripwireRealSubclass(HiggsfieldProvider):
    """Sous-classe du VRAI Provider qui redéfinit create_job()."""

    def create_job(self, job_type, prompt, **params):
        self.reached = getattr(self, "reached", []) + [job_type]
        return _tripwire_job(job_type)


class _TripwireRealAndMock(HiggsfieldProvider, MockHiggsfieldProvider):
    def create_job(self, job_type, prompt, **params):
        self.reached = getattr(self, "reached", []) + [job_type]
        return _tripwire_job(job_type)


class _TripwireMockSubclass(MockHiggsfieldProvider):
    def create_job(self, job_type, prompt, **params):
        self.reached = getattr(self, "reached", []) + [job_type]
        return super().create_job(job_type, prompt, **params)


class _TripwireWrapper(_UnknownWrapper):
    def create_job(self, job_type, prompt, **params):
        self.reached = getattr(self, "reached", []) + [job_type]
        return self.inner.create_job(job_type, prompt, **params)


class _TripwireDuckTyped(_DuckTypedUnknownProvider):
    def create_job(self, job_type, prompt, **params):
        self.reached = getattr(self, "reached", []) + [job_type]
        return self.inner.create_job(job_type, prompt, **params)


def _tripwire_mock_with_instance_create_job():
    provider = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=1000.0)
    provider.reached = []

    def _replaced_create_job(job_type, prompt, **params):
        provider.reached.append(job_type)
        return _tripwire_job(job_type)

    provider.create_job = _replaced_create_job
    return provider


def _tripwire_providers():
    """Chaque Provider enregistre dans `reached` tout appel de son
    create_job() (sauf `MagicMock` : `create_job.called`)."""

    return {
        "real HiggsfieldProvider subclass overriding create_job": lambda: _TripwireRealSubclass(client=_fake_client()),
        "real HiggsfieldProvider + Mock (multiple inheritance)": lambda: _TripwireRealAndMock(client=_fake_client()),
        "Mock subclass overriding create_job": lambda: _TripwireMockSubclass(cost_per_job=67.5, available_credits=1000.0),
        "Mock with create_job replaced on the instance": _tripwire_mock_with_instance_create_job,
        "unknown BaseHiggsfieldProvider wrapper": _TripwireWrapper,
        "duck-typed unknown provider": _TripwireDuckTyped,
        "MagicMock wrapping a Mock": lambda: MagicMock(
            wraps=MockHiggsfieldProvider(cost_per_job=67.5, available_credits=1000.0)
        ),
    }


def _reached(provider):
    if isinstance(provider, MagicMock):
        return provider.create_job.call_args_list
    return getattr(provider, "reached", [])


class ExecutionBoundaryNeverReachesUnsafeCreateJob(unittest.TestCase):
    """De bout en bout, via `GenerationJobService.execute()` : avec un
    plafond et un Identity Lock VALIDES (la Gate approuve), aucune
    sous-classe, aucun wrapper, aucun Provider inconnu n'atteint
    create_job(), aucune autorisation n'est consommée, rien n'est écrit ;
    le vrai `HiggsfieldProvider` exact reste bloqué par son propre refus
    inconditionnel."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="phase_d_boundary_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _gate(self, provider, name):
        state = self.tmp / name / "executed_requests.json"
        gate = GenerationApprovalGate(
            provider,
            executed_request_store=FileExecutedRequestStore(state),
            identity_lock=ReleaseCandidateIdentityLock(C),
            max_cost_credits_per_request=100.0,
        )
        return gate, state.parent

    def test_unsafe_provider_never_reaches_create_job_even_when_the_gate_approves(self):
        for index, (label, factory) in enumerate(_tripwire_providers().items()):
            with self.subTest(provider=label):
                provider = factory()
                gate, state_dir = self._gate(provider, f"p{index}")
                request = _conforming_request()
                auth_id = request.real_generation_authorization.authorization_id
                # Plafond et Identity Lock valides : la Gate approuve.
                self.assertEqual(gate.evaluate(request).decision, D.APPROVED)

                with self.assertRaises(GenerationJobProviderNotAllowedError):
                    GenerationJobService(provider, gate).execute(request, interval_seconds=0)

                self.assertEqual(list(_reached(provider)), [])
                self.assertFalse(gate.is_authorization_consumed(auth_id))
                self.assertFalse(gate.is_already_executed(request.request_id))
                self.assertFalse(gate.executed_request_store.is_unknown(request.request_id))
                self.assertEqual(sorted(p.name for p in state_dir.glob("*")), [], "nothing may be written")

    def test_final_report_path_reports_not_executed_and_never_reaches_create_job(self):
        for index, (label, factory) in enumerate(_tripwire_providers().items()):
            with self.subTest(provider=label):
                provider = factory()
                gate, _ = self._gate(provider, f"r{index}")
                request = _conforming_request()
                report = FinalReportService(provider, gate).generate(request, interval_seconds=0)
                self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)
                self.assertFalse(report.job_created)
                self.assertEqual(list(_reached(provider)), [])
                self.assertFalse(
                    gate.is_authorization_consumed(request.real_generation_authorization.authorization_id)
                )

    def test_gate_approving_a_recognized_mock_does_not_open_the_boundary_for_another_provider(self):
        # Gate construite sur un Mock reconnu (sans protections), service
        # d'exécution portant un Provider non sûr : la frontière vérifie
        # le Provider qu'elle appellerait réellement.
        for label, factory in _tripwire_providers().items():
            with self.subTest(provider=label):
                provider = factory()
                gate = GenerationApprovalGate(MockHiggsfieldProvider(cost_per_job=67.5, available_credits=1000.0))
                request = _conforming_request()
                self.assertEqual(gate.evaluate(request).decision, D.APPROVED)
                with self.assertRaises(GenerationJobProviderNotAllowedError):
                    GenerationJobService(provider, gate).execute(request, interval_seconds=0)
                self.assertEqual(list(_reached(provider)), [])
                self.assertFalse(
                    gate.is_authorization_consumed(request.real_generation_authorization.authorization_id)
                )

    def test_p2_26_contract_and_readiness_never_accept_an_unsafe_provider(self):
        for label, factory in _tripwire_providers().items():
            with self.subTest(provider=label):
                provider = factory()
                identity_lock = ReleaseCandidateIdentityLock(C)
                gate = GenerationApprovalGate(
                    provider, identity_lock=identity_lock, max_cost_credits_per_request=100.0
                )
                activation = RequestScopedActivationService(gate, identity_lock)
                request = _conforming_request()
                rs_contract = activation.prepare_activation(request)
                with self.assertRaises(ControlledRealProviderActivationRejectedError) as caught:
                    ControlledRealProviderActivationService(gate, identity_lock, activation).prepare(
                        request, rs_contract
                    )
                self.assertTrue(
                    any("neither the real HiggsfieldProvider nor a recognized test mock" in r
                        for r in caught.exception.reasons),
                    caught.exception.reasons,
                )
                readiness = ActivationReadinessEvaluator(gate, identity_lock, activation)._check_provider()
                self.assertEqual(readiness[0], False, readiness)
                self.assertEqual(list(_reached(provider)), [])

    def test_exact_real_provider_stays_closed_by_its_own_unconditional_refusal(self):
        client = _fake_client()
        provider = HiggsfieldProvider(client=client)
        gate, _ = self._gate(provider, "real")
        request = _conforming_request()
        self.assertEqual(gate.evaluate(request).decision, D.APPROVED)
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            GenerationJobService(provider, gate).execute(request, interval_seconds=0)
        client.create_job.assert_not_called()
        self.assertFalse(gate.is_already_executed(request.request_id))

    def test_recognized_mock_still_reaches_its_simulated_create_job(self):
        provider = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=1000.0, succeed_after_polls=0)
        gate = GenerationApprovalGate(provider)
        outcome = GenerationJobService(provider, gate).execute(_conforming_request(), interval_seconds=0)
        self.assertTrue(outcome.succeeded)
        self.assertEqual(list(provider._jobs), [outcome.job.job_id])


class DirectorRealChainStaysClosed(unittest.TestCase):
    """(a) La chaîne réelle construite par `AIDirector` n'a AUCUN
    plafond : elle reste BLOCKED avant toute création de job. Le
    Director n'injecte aucun plafond et aucune configuration de test
    n'est référencée par le code de production."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="phase_d_director_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.director = AIDirector()
        self.director.higgsfield = _fake_client()

    def test_default_chain_has_no_ceiling_and_is_blocked(self):
        with isolated_director_state(self.tmp):
            chain = self.director._build_default_chain()
        self.assertIsInstance(chain.provider, HiggsfieldProvider)
        self.assertTrue(chain.gate.requires_real_path_protections())
        self.assertIsNone(chain.gate.max_cost_credits_per_request)
        self.assertIsInstance(chain.gate.identity_lock, ReleaseCandidateIdentityLock)

        result = chain.gate.evaluate(_conforming_request())
        self.assertEqual(result.decision, D.BLOCKED)
        self.assertTrue(any("per-request credit ceiling" in r for r in result.reasons), result.reasons)
        self.director.higgsfield.create_job.assert_not_called()

    def test_run_video_mission_is_blocked_before_create_job(self):
        authorization = video_005_authorization()
        with isolated_director_state(self.tmp) as state:
            report = self.director.run_video_mission(
                video_id="005", title="t", hook="h", objective="o",
                duration=C.duration, approved=True,
                real_generation_authorization=authorization, interval_seconds=0,
            )
        self.assertEqual(report.approval_decision, D.BLOCKED)
        self.assertFalse(report.job_created)
        self.assertTrue(any("per-request credit ceiling" in r for r in report.approval_reasons))
        self.director.higgsfield.create_job.assert_not_called()
        self.assertFalse((state / "executed_requests.json").exists())
        self.assertFalse((state / "consumed_authorizations.json").exists())

    def test_prepare_real_generation_activation_is_refused(self):
        with isolated_director_state(self.tmp):
            with self.assertRaises(ActivationRejectedError) as caught:
                self.director.prepare_real_generation_activation(
                    video_id="005", title="t", hook="h", objective="o",
                    duration=C.duration, approved=True,
                    real_generation_authorization=video_005_authorization(),
                )
        self.assertTrue(
            any("per-request credit ceiling" in r for r in caught.exception.reasons), caught.exception.reasons
        )
        self.director.higgsfield.create_job.assert_not_called()

    def test_production_code_never_configures_a_ceiling_or_uses_test_fixtures(self):
        director_source = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        self.assertNotIn("max_cost_credits_per_request", director_source)
        for folder in ("agents", "integrations", "scripts"):
            for path in (PROJECT_ROOT / folder).rglob("*.py"):
                with self.subTest(path=str(path.relative_to(PROJECT_ROOT))):
                    self.assertNotIn("real_provider_path_fixtures", path.read_text(encoding="utf-8-sig"))
        self.assertNotIn("real_provider_path_fixtures", director_source)


if __name__ == "__main__":
    unittest.main()
