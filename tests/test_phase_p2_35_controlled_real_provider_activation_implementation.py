"""
Tests — Phase P2.35 : CONTROLLED REAL PROVIDER ACTIVATION IMPLEMENTATION.

Verrouille ce que P2.35 a réellement changé dans
`integrations/higgsfield/provider.py` :

- `HiggsfieldProvider.create_job()` INSPECTE désormais réellement
  `provider_activation_contract` (type, binding request_id/job_type/
  duration/resolution/aspect_ratio/prompt-sha/avatar-sha/face-sha,
  présence authorization_id/request_scoped_activation_id, fraîcheur
  locale via `created_at` + horloge injectable) -- ce qu'elle ne
  faisait PAS avant P2.35 (P2.32 acceptait le paramètre sans jamais le
  lire).
- Que la liste de violations soit vide ou non, `create_job()` lève
  TOUJOURS `HiggsfieldRealGenerationDisabledError` et n'appelle JAMAIS
  `self.client.create_job()` -- vérifié explicitement ici pour le cas
  le PLUS favorable (activation structurellement parfaitement valide),
  qui est le test le plus important de ce fichier
  (`TestRealProviderStillNeverCallsClientEvenWhenFullyValid`).

Ce fichier NE re-teste PAS ce qui est inchangé depuis P2.26/P2.27/P2.32
(expiry/single-use/revoke AUTHORITATIFS, qui restent la responsabilité
exclusive de `ControlledRealProviderActivationService`, appelée par
`GenerationJobService.execute()` immédiatement avant `create_job()`,
dans le même verrou de section critique -- déjà exhaustivement couvert
par tests/test_phase_p2_26_*.py et tests/test_phase_p2_27_*.py).
"""

import ast
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import RequestScopedActivationService
from agents.controlled_real_provider_activation import (
    ControlledRealProviderActivationContract,
    ControlledRealProviderActivationService,
)
from agents.critical_section_lock import FileCriticalSectionLock
from agents.generation_approval_gate import (
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from tests.authorization_content_helpers import bind_request
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
    return bind_request(GenerationRequest(**defaults))


class _Stack:
    """Mêmes composants que director.py::_build_default_chain(), mais
    avec un MockHiggsfieldProvider et un lock temporaire (Étape 22,
    P2.34/35 : jamais le véritable state/ du dépôt)."""

    def __init__(self, tmp_dir: Path, cost_per_job=67.5, available_credits=100.0):
        self.provider = MockHiggsfieldProvider(
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

    def prepared(self, request):
        rs_contract = self.activation_service.prepare_activation(request)
        pa_contract = self.provider_activation_service.prepare(request, rs_contract)
        return rs_contract, pa_contract


class _TmpDirTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_35_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def _stack(self, **kwargs) -> _Stack:
        return _Stack(self._tmp, **kwargs)


def _real_provider(clock=None, max_age_seconds=300.0):
    fake_client = MagicMock()
    kwargs = {"client": fake_client, "max_age_seconds": max_age_seconds}
    if clock is not None:
        kwargs["clock"] = clock
    return HiggsfieldProvider(**kwargs), fake_client


AVATAR_SHA = C.avatar_master_sha256
FACE_SHA = C.face_reference_sha256


class _ValidContractCase(_TmpDirTestCase):
    """Fabrique un ControlledRealProviderActivationContract authentique
    (préparé ET validé via la chaîne Mock réelle, jamais falsifié à la
    main) pour request_id 005, réutilisé par plusieurs tests."""

    def _valid_contract_for_005(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)
        validated = stack.provider_activation_service.validate(request, rs_contract, pa_contract)
        return validated


# ----------------------------------------------------------------------
# A-J, N : STRUCTURAL BINDING MISMATCHES (Phase 15 checklist)
# ----------------------------------------------------------------------


class TestStructuralBindingChecks(_ValidContractCase):
    def test_A_no_activation_contract_rejects(self):
        real_provider, fake_client = _real_provider()
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
            real_provider.create_job(job_type="seedance_2_0", prompt="x")
        self.assertTrue(ctx.exception.reasons)
        fake_client.create_job.assert_not_called()

    def test_B_wrong_type_rejects(self):
        real_provider, fake_client = _real_provider()
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
            real_provider.create_job(
                job_type="seedance_2_0",
                prompt="x",
                provider_activation_contract="not-a-real-contract",
            )
        self.assertTrue(any("not a" in r for r in ctx.exception.reasons))
        fake_client.create_job.assert_not_called()

    def test_C_wrong_request_id_rejects(self):
        contract = self._valid_contract_for_005()
        real_provider, fake_client = _real_provider()
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
            real_provider.create_job(
                job_type=contract.job_type,
                prompt=_real_prompt(),
                provider_activation_contract=contract,
                request_id="006",
                avatar_sha256=AVATAR_SHA,
                face_reference_sha256=FACE_SHA,
                duration=contract.duration,
                resolution=contract.resolution,
                aspect_ratio=contract.aspect_ratio,
            )
        self.assertTrue(any("request_id" in r for r in ctx.exception.reasons))
        fake_client.create_job.assert_not_called()

    def test_D_wrong_model_rejects(self):
        contract = self._valid_contract_for_005()
        real_provider, fake_client = _real_provider()
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
            real_provider.create_job(
                job_type="other_model",
                prompt=_real_prompt(),
                provider_activation_contract=contract,
                request_id="005",
                avatar_sha256=AVATAR_SHA,
                face_reference_sha256=FACE_SHA,
                duration=contract.duration,
                resolution=contract.resolution,
                aspect_ratio=contract.aspect_ratio,
            )
        self.assertTrue(any("job_type" in r for r in ctx.exception.reasons))
        fake_client.create_job.assert_not_called()

    def test_E_wrong_duration_rejects(self):
        contract = self._valid_contract_for_005()
        real_provider, fake_client = _real_provider()
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
            real_provider.create_job(
                job_type=contract.job_type,
                prompt=_real_prompt(),
                provider_activation_contract=contract,
                request_id="005",
                avatar_sha256=AVATAR_SHA,
                face_reference_sha256=FACE_SHA,
                duration=5,
                resolution=contract.resolution,
                aspect_ratio=contract.aspect_ratio,
            )
        self.assertTrue(any("duration" in r for r in ctx.exception.reasons))
        fake_client.create_job.assert_not_called()

    def test_F_wrong_resolution_rejects(self):
        contract = self._valid_contract_for_005()
        real_provider, fake_client = _real_provider()
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
            real_provider.create_job(
                job_type=contract.job_type,
                prompt=_real_prompt(),
                provider_activation_contract=contract,
                request_id="005",
                avatar_sha256=AVATAR_SHA,
                face_reference_sha256=FACE_SHA,
                duration=contract.duration,
                resolution="1080p",
                aspect_ratio=contract.aspect_ratio,
            )
        self.assertTrue(any("resolution" in r for r in ctx.exception.reasons))
        fake_client.create_job.assert_not_called()

    def test_G_wrong_aspect_ratio_rejects(self):
        contract = self._valid_contract_for_005()
        real_provider, fake_client = _real_provider()
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
            real_provider.create_job(
                job_type=contract.job_type,
                prompt=_real_prompt(),
                provider_activation_contract=contract,
                request_id="005",
                avatar_sha256=AVATAR_SHA,
                face_reference_sha256=FACE_SHA,
                duration=contract.duration,
                resolution=contract.resolution,
                aspect_ratio="16:9",
            )
        self.assertTrue(any("aspect_ratio" in r for r in ctx.exception.reasons))
        fake_client.create_job.assert_not_called()

    def test_H_wrong_prompt_hash_rejects(self):
        contract = self._valid_contract_for_005()
        real_provider, fake_client = _real_provider()
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
            real_provider.create_job(
                job_type=contract.job_type,
                prompt=_real_prompt() + " mutated",
                provider_activation_contract=contract,
                request_id="005",
                avatar_sha256=AVATAR_SHA,
                face_reference_sha256=FACE_SHA,
                duration=contract.duration,
                resolution=contract.resolution,
                aspect_ratio=contract.aspect_ratio,
            )
        self.assertTrue(any("prompt sha256" in r for r in ctx.exception.reasons))
        fake_client.create_job.assert_not_called()

    def test_I_wrong_avatar_hash_rejects(self):
        contract = self._valid_contract_for_005()
        real_provider, fake_client = _real_provider()
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
            real_provider.create_job(
                job_type=contract.job_type,
                prompt=_real_prompt(),
                provider_activation_contract=contract,
                request_id="005",
                avatar_sha256="0" * 64,
                face_reference_sha256=FACE_SHA,
                duration=contract.duration,
                resolution=contract.resolution,
                aspect_ratio=contract.aspect_ratio,
            )
        self.assertTrue(any("avatar_sha256" in r for r in ctx.exception.reasons))
        fake_client.create_job.assert_not_called()

    def test_J_wrong_face_reference_hash_rejects(self):
        contract = self._valid_contract_for_005()
        real_provider, fake_client = _real_provider()
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
            real_provider.create_job(
                job_type=contract.job_type,
                prompt=_real_prompt(),
                provider_activation_contract=contract,
                request_id="005",
                avatar_sha256=AVATAR_SHA,
                face_reference_sha256="0" * 64,
                duration=contract.duration,
                resolution=contract.resolution,
                aspect_ratio=contract.aspect_ratio,
            )
        self.assertTrue(any("face_reference_sha256" in r for r in ctx.exception.reasons))
        fake_client.create_job.assert_not_called()

    def test_N_missing_request_id_never_accepted_as_wildcard(self):
        """Phase 4 : aucun `request_id=None` accepté comme bypass."""

        contract = self._valid_contract_for_005()
        real_provider, fake_client = _real_provider()
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
            real_provider.create_job(
                job_type=contract.job_type,
                prompt=_real_prompt(),
                provider_activation_contract=contract,
                request_id=None,
                avatar_sha256=AVATAR_SHA,
                face_reference_sha256=FACE_SHA,
                duration=contract.duration,
                resolution=contract.resolution,
                aspect_ratio=contract.aspect_ratio,
            )
        self.assertTrue(any("wildcard" in r for r in ctx.exception.reasons))
        fake_client.create_job.assert_not_called()


# ----------------------------------------------------------------------
# REQUEST-SCOPED UNIQUENESS (Phase 4) : 005-contract unusable for 006.
# ----------------------------------------------------------------------


class TestRequestScopedUniqueness(_ValidContractCase):
    def test_005_contract_cannot_authorize_a_006_live_call(self):
        contract_005 = self._valid_contract_for_005()
        real_provider, fake_client = _real_provider()
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
            real_provider.create_job(
                job_type="other_model",
                prompt="unrelated 006 prompt",
                provider_activation_contract=contract_005,
                request_id="006",
                avatar_sha256="1" * 64,
                face_reference_sha256="2" * 64,
                duration=5,
                resolution="480p",
                aspect_ratio="1:1",
            )
        self.assertTrue(any("request_id" in r for r in ctx.exception.reasons))
        fake_client.create_job.assert_not_called()

    def test_006_style_contract_cannot_authorize_a_005_live_call(self):
        """Un contrat parfaitement auto-cohérent pour une identité
        étrangère (jamais validée contre le vrai Video 005 -- ce test
        construit un contrat directement, sans passer par l'Identity
        Lock, pour isoler EXCLUSIVEMENT le comportement du Provider face
        à un contrat structurellement complet mais non-005) ne peut pas
        davantage autoriser un appel prétendant être pour 005."""

        foreign_contract = ControlledRealProviderActivationContract(
            activation_id="foreign-activation",
            request_id="006",
            request_scoped_activation_id="foreign-rs-activation",
            job_type="other_model",
            duration=5,
            resolution="480p",
            aspect_ratio="1:1",
            prompt_sha256="a" * 64,
            avatar_sha256="b" * 64,
            face_reference_sha256="c" * 64,
            expected_cost_credits=1.0,
            authorization_id="foreign-auth",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        real_provider, fake_client = _real_provider()
        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
            real_provider.create_job(
                job_type="seedance_2_0",
                prompt=_real_prompt(),
                provider_activation_contract=foreign_contract,
                request_id="005",
                avatar_sha256=AVATAR_SHA,
                face_reference_sha256=FACE_SHA,
                duration=15,
                resolution="720p",
                aspect_ratio="9:16",
            )
        self.assertTrue(any("request_id" in r for r in ctx.exception.reasons))
        fake_client.create_job.assert_not_called()


# ----------------------------------------------------------------------
# K : EXPIRY (Provider-local freshness sanity check, injectable clock)
# ----------------------------------------------------------------------


class TestProviderLocalFreshness(_ValidContractCase):
    def test_K_stale_contract_rejected_by_injected_clock(self):
        contract = self._valid_contract_for_005()

        far_future = datetime.fromisoformat(contract.created_at) + timedelta(seconds=301)
        real_provider, fake_client = _real_provider(clock=lambda: far_future, max_age_seconds=300.0)

        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
            real_provider.create_job(
                job_type=contract.job_type,
                prompt=_real_prompt(),
                provider_activation_contract=contract,
                request_id="005",
                avatar_sha256=AVATAR_SHA,
                face_reference_sha256=FACE_SHA,
                duration=contract.duration,
                resolution=contract.resolution,
                aspect_ratio=contract.aspect_ratio,
            )
        self.assertTrue(any("age" in r for r in ctx.exception.reasons))
        fake_client.create_job.assert_not_called()

    def test_fresh_contract_within_window_not_rejected_on_freshness_grounds(self):
        """Un contrat dans la fenêtre ne doit PAS être refusé pour des
        raisons de fraîcheur -- il reste néanmoins refusé au dernier
        verrou inconditionnel (cf. TestRealProviderStillNeverCallsClient
        EvenWhenFullyValid), mais PAS avec une raison "age"."""

        contract = self._valid_contract_for_005()
        just_after = datetime.fromisoformat(contract.created_at) + timedelta(seconds=1)
        real_provider, fake_client = _real_provider(clock=lambda: just_after, max_age_seconds=300.0)

        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
            real_provider.create_job(
                job_type=contract.job_type,
                prompt=_real_prompt(),
                provider_activation_contract=contract,
                request_id="005",
                avatar_sha256=AVATAR_SHA,
                face_reference_sha256=FACE_SHA,
                duration=contract.duration,
                resolution=contract.resolution,
                aspect_ratio=contract.aspect_ratio,
            )
        self.assertFalse(any("age" in r for r in ctx.exception.reasons))
        fake_client.create_job.assert_not_called()


# ----------------------------------------------------------------------
# L, M : REVOKED / CONSUMED — architecture note + honest test.
# ----------------------------------------------------------------------


class TestRevokedAndConsumedRemainServiceAuthoritative(_ValidContractCase):
    """
    Phase 3 (P2.35) : le Provider ne doit PAS dupliquer l'autorité. Le
    suivi authoritatif de consommation/révocation reste EXCLUSIVEMENT
    la responsabilité de `ControlledRealProviderActivationService`
    (déjà exhaustivement testé par tests/test_phase_p2_26_*.py ::
    test_P_consumed_contract_blocks_second_validation et
    test_revoke_makes_a_still_valid_contract_immediately_unusable) --
    appelée par `GenerationJobService.execute()` IMMÉDIATEMENT avant
    `create_job()`, dans le même verrou de section critique. Une
    bookkeeping locale par instance de Provider serait TROMPEUSE (elle
    ne survivrait pas à la reconstruction du Provider, cf. Phase 8 de
    la consigne P2.35) -- délibérément non implémentée ici, documenté
    plutôt que simulé.

    Ce que ce test démontre honnêtement : le Provider refuse un
    contrat révoqué/consommé pour la MÊME raison finale que n'importe
    quel contrat structurellement valide -- le dernier verrou
    inconditionnel -- jamais parce qu'il aurait lui-même détecté la
    révocation/consommation.
    """

    def test_revoked_contract_still_refused_at_the_provider_boundary(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)
        stack.provider_activation_service.revoke(pa_contract)

        real_provider, fake_client = _real_provider()
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(
                job_type=pa_contract.job_type,
                prompt=_real_prompt(),
                provider_activation_contract=pa_contract,
                request_id="005",
                avatar_sha256=AVATAR_SHA,
                face_reference_sha256=FACE_SHA,
                duration=pa_contract.duration,
                resolution=pa_contract.resolution,
                aspect_ratio=pa_contract.aspect_ratio,
            )
        fake_client.create_job.assert_not_called()

        # Authoritative detection remains at the SERVICE layer:
        from agents.controlled_real_provider_activation import (
            ControlledRealProviderActivationRejectedError,
        )

        with self.assertRaises(ControlledRealProviderActivationRejectedError):
            stack.provider_activation_service.validate(request, rs_contract, pa_contract)


# ----------------------------------------------------------------------
# O, P, Q, R, S, T : upstream layers block BEFORE the provider is ever
# reached (spy provider proves create_job() is never called).
# ----------------------------------------------------------------------


class _SpyProvider(MockHiggsfieldProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.create_job_called = False

    def create_job(self, *args, **kwargs):
        self.create_job_called = True
        return super().create_job(*args, **kwargs)


class TestUpstreamLayersBlockBeforeProvider(_TmpDirTestCase):
    def _spy_stack(self, **kwargs):
        provider = _SpyProvider(**kwargs)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
        activation_service = RequestScopedActivationService(gate, identity_lock)
        provider_activation_service = ControlledRealProviderActivationService(
            gate, identity_lock, activation_service
        )
        job_service = GenerationJobService(
            provider,
            gate,
            lock=FileCriticalSectionLock(self._tmp),
            activation_service=activation_service,
            provider_activation_service=provider_activation_service,
        )
        return provider, gate, activation_service, provider_activation_service, job_service

    def test_R_insufficient_budget_never_reaches_provider(self):
        provider, gate, activation_service, pa_service, job_service = self._spy_stack(
            cost_per_job=67.5, available_credits=1.41
        )
        request = _conforming_request()
        from agents.activation_contract import ActivationRejectedError

        with self.assertRaises(ActivationRejectedError):
            activation_service.prepare_activation(request)
        self.assertFalse(provider.create_job_called)

    def test_T_already_executed_never_reaches_provider_on_replay(self):
        provider, gate, activation_service, pa_service, job_service = self._spy_stack()
        request = _conforming_request()
        rs_contract = activation_service.prepare_activation(request)
        pa_contract = pa_service.prepare(request, rs_contract)

        outcome = job_service.execute(
            request,
            interval_seconds=0,
            activation_contract=rs_contract,
            provider_activation_contract=pa_contract,
        )
        self.assertTrue(outcome.succeeded)
        self.assertTrue(provider.create_job_called)

        provider.create_job_called = False  # reset for the replay attempt

        new_auth_request = _conforming_request(
            real_generation_authorization=RealGenerationAuthorization(
                request_id="005", authorized_by_human=True
            )
        )
        from agents.activation_contract import ActivationRejectedError

        with self.assertRaises(ActivationRejectedError):
            activation_service.prepare_activation(new_auth_request)
        self.assertFalse(provider.create_job_called)


# ----------------------------------------------------------------------
# U : MOCK VALID ACTIVATION -> PASS (never confused with real generation)
# ----------------------------------------------------------------------


class TestMockValidActivationPasses(_TmpDirTestCase):
    def test_U_mock_full_chain_still_executed_pass_with_new_params_observable(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)

        outcome = stack.job_service.execute(
            request,
            interval_seconds=0,
            activation_contract=rs_contract,
            provider_activation_contract=pa_contract,
        )
        self.assertTrue(outcome.succeeded)
        self.assertEqual(outcome.job.raw["provider_activation_contract"], pa_contract)
        self.assertEqual(outcome.job.raw["request_id"], "005")
        self.assertEqual(outcome.job.raw["avatar_sha256"], AVATAR_SHA)
        self.assertEqual(outcome.job.raw["face_reference_sha256"], FACE_SHA)

        is_real = type(stack.job_service.provider).create_job is HiggsfieldProvider.create_job
        self.assertFalse(is_real)


# ----------------------------------------------------------------------
# V, W & Phase 16 : the single most important test in this file.
# ----------------------------------------------------------------------


class TestRealProviderStillNeverCallsClientEvenWhenFullyValid(_ValidContractCase):
    def test_V_fully_valid_structurally_correct_activation_still_refused(self):
        """Construit une activation P2.26 authentique et PARFAITEMENT
        cohérente avec Video 005 (request_id/model/duration/resolution/
        aspect_ratio/prompt/avatar/face tous exacts), l'inspecte
        directement contre le VRAI HiggsfieldProvider (fake client) avec
        les mêmes valeurs live -- ZÉRO violation structurelle -- et
        prouve que create_job() refuse malgré tout, EXPLICITEMENT parce
        que la transition finale reste fermée (pas pour une raison de
        mismatch), et que le client réel n'est jamais atteint."""

        contract = self._valid_contract_for_005()
        real_provider, fake_client = _real_provider()

        with self.assertRaises(HiggsfieldRealGenerationDisabledError) as ctx:
            real_provider.create_job(
                job_type=contract.job_type,
                prompt=_real_prompt(),
                provider_activation_contract=contract,
                request_id="005",
                avatar_sha256=AVATAR_SHA,
                face_reference_sha256=FACE_SHA,
                duration=contract.duration,
                resolution=contract.resolution,
                aspect_ratio=contract.aspect_ratio,
            )

        self.assertEqual(
            ctx.exception.reasons,
            [
                "activation_structurally_valid_but_real_execution_"
                "transition_intentionally_closed_in_this_phase"
            ],
        )
        fake_client.create_job.assert_not_called()
        fake_client.run.assert_not_called()
        fake_client.account_status.assert_not_called()
        fake_client.estimate_cost.assert_not_called()
        fake_client.get_model.assert_not_called()

    def test_W_direct_client_call_protection(self):
        """Même en contournant intégralement GenerationJobService et en
        appelant HiggsfieldProvider.create_job() à la main avec zéro
        garde-fou amont, aucune génération réelle n'a lieu."""

        real_provider, fake_client = _real_provider()
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(job_type="seedance_2_0", prompt="anything at all")
        fake_client.create_job.assert_not_called()
        fake_client.run.assert_not_called()


# ----------------------------------------------------------------------
# CALL-SITE INVARIANT (Phase 12)
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


# ----------------------------------------------------------------------
# SECURITY SCAN (Phase 18)
# ----------------------------------------------------------------------


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

    def test_no_second_call_site_hidden_via_getattr_or_direct_client(self):
        """Recherche explicite d'un appel direct à `self.client.
        create_job` (le seul chemin réseau réel) n'importe où dans
        integrations/higgsfield/provider.py -- doit rester absent."""

        text = (PROJECT_ROOT / "integrations" / "higgsfield" / "provider.py").read_text(
            encoding="utf-8-sig"
        )
        tree = ast.parse(text)
        client_create_job_calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "create_job"
            and isinstance(n.func.value, ast.Attribute)
            and n.func.value.attr == "client"
        ]
        self.assertEqual(client_create_job_calls, [])


if __name__ == "__main__":
    unittest.main()
