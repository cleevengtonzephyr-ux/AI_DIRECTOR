"""
Tests — Phase B : liaison de `RealGenerationAuthorization` au contenu
approuvé (prompt, avatar, référence visage) et aux contrats P2.21/P2.26.

MOCK-ONLY. Aucun test ne lance de génération Higgsfield ni n'atteint un
vrai client : les chaînes positives utilisent `MockHiggsfieldProvider`,
les chaînes « Provider réel » un `HiggsfieldProvider` à client
`MagicMock` qui refuse avant tout appel client. Tout état persistant
(store, registre de consommation, verrous) vit dans un dossier
temporaire ; `state/` n'est jamais touché. Les assets réels de Video 005
sont uniquement LUS (copiés dans le dossier temporaire quand un test doit
les modifier).
"""

import ast
import dataclasses
import inspect
import json
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
from agents.controlled_real_provider_activation import _sha256_of_file_or_none as p2_26_file_sha256
from agents.critical_section_lock import FileCriticalSectionLock
from agents.executed_request_store import FileExecutedRequestStore, authorization_id_sha256
from agents.final_report_service import FinalReportService, FinalReportStatus
from agents.generation_approval_gate import (
    AUTHORIZATION_CONTENT_DIGEST_FIELDS,
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
    authorization_content_digests,
)
from agents.generation_job_service import (
    GenerationJobActivationRejectedError,
    GenerationJobExecutionError,
    GenerationJobProviderActivationRejectedError,
    GenerationJobService,
)
from agents.generation_job_service import _sha256_of_file_or_none as job_service_file_sha256
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.release_candidate_identity_lock import (
    ReleaseCandidateIdentityLock,
    VIDEO_005_RELEASE_CANDIDATE as C,
)
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider
from tests.real_provider_path_fixtures import (
    FIXTURE_MAX_COST_CREDITS_PER_REQUEST,
    counting_mock_provider,
    fixture_identity_lock_for,
    install_create_job_probe,
)
from tests.authorization_content_helpers import (
    REAL_AVATAR_PATH,
    REAL_FACE_PATH,
    bound_authorization,
    content_media,
    video_005_authorization,
)

D = GenerationApprovalDecision
CANONICAL_PROMPT = PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id)


def _counting_provider(refuse=False, **kwargs):
    """Mock RECONNU : compte chaque create_job() ; peut refuser comme le vrai
    Provider (avant tout appel client). Phase D : instrumentation portée
    par `gate.in_flight()` (`install_create_job_probe()`), jamais par un
    `create_job()` redéfini, qui n'atteindrait plus la frontière."""

    return counting_mock_provider(refuse=refuse, **kwargs)


def _create_calls(provider) -> int:
    """Appels à `create_job()`. Phase D : seule une instance EXACTE de
    `MockHiggsfieldProvider` est un mock reconnu (Gate sans plafond ni
    Identity Lock) ; elle enregistre exactement un job simulé par appel
    dans `_jobs`. `_counting_provider()` (refus instrumenté) garde son
    propre compteur, tenu par `install_create_job_probe()`."""

    counted = getattr(provider, "create_calls", None)
    return counted if counted is not None else len(provider._jobs)


class _Sandbox(unittest.TestCase):
    """Dossier temporaire avec des COPIES octet-à-octet des assets réels
    (même SHA-256, donc conformes à l'Identity Lock) que les tests
    peuvent modifier sans jamais toucher aux originaux."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="phase_b_content_binding_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.avatar = self.tmp / "avatar.png"
        self.face = self.tmp / "face.png"
        shutil.copyfile(REAL_AVATAR_PATH, self.avatar)
        shutil.copyfile(REAL_FACE_PATH, self.face)
        self.other = self.tmp / "other.png"
        self.other.write_bytes(b"not the approved asset")
        self.state_path = self.tmp / "state" / "executed_requests.json"
        self.registry_path = self.state_path.with_name("consumed_authorizations.json")

    # --- requêtes -----------------------------------------------------

    def _unbound(self, **overrides) -> GenerationRequest:
        values = dict(
            **content_media(self.avatar, self.face),
            request_id=C.request_id,
            job_type=C.job_type,
            prompt=CANONICAL_PROMPT,
            duration=C.duration,
            resolution=C.resolution,
            aspect_ratio=C.aspect_ratio,
            approved=True,
        )
        values.update(overrides)
        return GenerationRequest(**values)

    def _approved_authorization(self, **kwargs) -> RealGenerationAuthorization:
        """Autorisation donnée par l'humain pour le contenu CANONIQUE."""

        return bound_authorization(self._unbound(), **kwargs)

    def _request(self, authorization=None, **overrides) -> GenerationRequest:
        """Requête (éventuellement modifiée par `overrides`) portant
        `authorization` -- par défaut une autorisation pour le contenu
        canonique, jamais recalculée sur le contenu modifié."""

        authorization = authorization or self._approved_authorization()
        return dataclasses.replace(
            self._unbound(**overrides), real_generation_authorization=authorization
        )

    # --- chaînes ------------------------------------------------------

    def _gate_chain(self, cost=67.5, identity_lock=False, provider=None,
                    max_cost_credits_per_request=None, **provider_kwargs):
        # Phase D : Mock RECONNU par défaut (la Gate peut rester sans Identity
        # Lock pour isoler la liaison au contenu) ; `_CountingProvider` n'est
        # utilisé que pour un comportement instrumenté (`refuse=...`), porté
        # par `gate.in_flight()` (cf. `install_create_job_probe()` ci-dessous).
        if provider is None:
            provider = (
                _counting_provider(cost_per_job=cost, available_credits=1000.0, **provider_kwargs)
                if provider_kwargs
                else MockHiggsfieldProvider(cost_per_job=cost, available_credits=1000.0)
            )
        store = FileExecutedRequestStore(self.state_path)
        gate = GenerationApprovalGate(
            provider,
            executed_request_store=store,
            identity_lock=(
                ReleaseCandidateIdentityLock(C) if identity_lock is True else (identity_lock or None)
            ),
            max_cost_credits_per_request=max_cost_credits_per_request,
        )
        if provider_kwargs:
            install_create_job_probe(gate, provider)
        service = GenerationJobService(
            provider, gate, lock=FileCriticalSectionLock(self.tmp / "locks")
        )
        return provider, gate, service

    def _contract_stack(self, provider=None, gate_identity_lock=True, max_cost_credits_per_request=None):
        """`gate_identity_lock=False` : la Gate n'a pas d'Identity Lock
        (qui, sinon, refuse en premier -- INVALID_REQUEST) afin d'isoler
        la liaison autorisation <-> contenu ; les services P2.21/P2.26
        gardent le leur, obligatoire."""

        # Phase D : Mock RECONNU par défaut (cf. `_gate_chain`).
        provider = provider or MockHiggsfieldProvider(cost_per_job=67.5, available_credits=1000.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(
            provider,
            executed_request_store=FileExecutedRequestStore(self.state_path),
            identity_lock=identity_lock if gate_identity_lock else None,
            max_cost_credits_per_request=max_cost_credits_per_request,
        )
        activation = RequestScopedActivationService(gate, identity_lock)
        provider_activation = ControlledRealProviderActivationService(
            gate, identity_lock, activation
        )
        service = GenerationJobService(
            provider,
            gate,
            lock=FileCriticalSectionLock(self.tmp / "locks"),
            activation_service=activation,
            provider_activation_service=provider_activation,
        )
        return provider, gate, activation, provider_activation, service

    # --- assertions ---------------------------------------------------

    def _consumed_digests(self):
        if not self.registry_path.exists():
            return set()
        data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        return set(data["consumed_authorization_sha256"])

    def assertNothingHappened(self, provider, gate, *authorizations):
        self.assertEqual(_create_calls(provider), 0)
        self.assertEqual(provider._jobs, {})
        for authorization in authorizations:
            self.assertFalse(gate.is_authorization_consumed(authorization.authorization_id))
        self.assertFalse(self.state_path.exists(), "no execution marker may be written")

    def assertReasonsMention(self, reasons, *fragments):
        for fragment in fragments:
            self.assertTrue(any(fragment in reason for reason in reasons), (fragment, reasons))


# ----------------------------------------------------------------------
# 1. Format et cohérence des empreintes entre les couches
# ----------------------------------------------------------------------


class TestDigestConsistencyAcrossLayers(_Sandbox):
    def test_live_digests_of_video_005_equal_identity_lock_canon(self):
        request = self._unbound(**content_media())
        self.assertEqual(
            authorization_content_digests(request),
            {
                "prompt_sha256": C.prompt_sha256,
                "avatar_sha256": C.avatar_master_sha256,
                "face_reference_sha256": C.face_reference_sha256,
            },
        )

    def test_same_file_digest_as_job_service_and_p2_26(self):
        digests = authorization_content_digests(self._unbound())
        self.assertEqual(digests["avatar_sha256"], job_service_file_sha256(str(self.avatar)))
        self.assertEqual(digests["avatar_sha256"], p2_26_file_sha256(str(self.avatar)))
        self.assertEqual(digests["face_reference_sha256"], job_service_file_sha256(str(self.face)))
        self.assertEqual(digests["face_reference_sha256"], p2_26_file_sha256(str(self.face)))

    def test_missing_or_unreadable_content_yields_none_never_a_value(self):
        self.assertIsNone(authorization_content_digests(self._unbound(start_image=None))["avatar_sha256"])
        self.assertIsNone(
            authorization_content_digests(self._unbound(image_references=()))["face_reference_sha256"]
        )
        missing = self._unbound(**content_media(self.tmp / "absent.png", self.tmp))
        self.assertIsNone(authorization_content_digests(missing)["avatar_sha256"])
        self.assertIsNone(authorization_content_digests(missing)["face_reference_sha256"])

    def test_digest_helper_never_constructs_an_authorization(self):
        source = inspect.getsource(authorization_content_digests)
        calls = {
            node.func.id
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertNotIn("RealGenerationAuthorization", calls)

    def test_legacy_constructor_still_builds_but_is_never_approved(self):
        provider, gate, service = self._gate_chain()
        legacy = RealGenerationAuthorization(request_id=C.request_id, authorized_by_human=True)
        for name in AUTHORIZATION_CONTENT_DIGEST_FIELDS:
            self.assertIsNone(getattr(legacy, name))

        result = gate.evaluate(self._request(legacy))
        self.assertEqual(result.decision, D.NEEDS_APPROVAL)
        self.assertReasonsMention(result.reasons, *AUTHORIZATION_CONTENT_DIGEST_FIELDS)
        with self.assertRaises(GenerationJobExecutionError):
            service.execute(self._request(legacy), interval_seconds=0)
        self.assertNothingHappened(provider, gate, legacy)


# ----------------------------------------------------------------------
# 2. Divergence séparée du prompt / de l'avatar / de la référence visage
#    (Gate SANS Identity Lock : seule la liaison au contenu protège)
# ----------------------------------------------------------------------


class TestSeparateContentDivergence(_Sandbox):
    def _divergences(self):
        return {
            "prompt_sha256": dict(prompt=CANONICAL_PROMPT + "\nAltered after approval."),
            "avatar_sha256": content_media(self.other, self.face),
            "face_reference_sha256": content_media(self.avatar, self.other),
        }

    def test_each_divergence_alone_is_refused_without_job_or_consumption(self):
        for field_name, overrides in self._divergences().items():
            with self.subTest(field=field_name):
                provider, gate, service = self._gate_chain()
                authorization = self._approved_authorization()
                request = self._request(authorization, **overrides)

                result = gate.evaluate(request)
                self.assertEqual(result.decision, D.NEEDS_APPROVAL)
                content_reasons = [r for r in result.reasons if "given for different content" in r]
                self.assertEqual(len(content_reasons), 1, result.reasons)
                self.assertIn(field_name, content_reasons[0])

                with self.assertRaises(GenerationJobExecutionError):
                    service.execute(request, interval_seconds=0)
                self.assertNothingHappened(provider, gate, authorization)

    def test_identical_content_is_approved_and_executes_once(self):
        provider, gate, service = self._gate_chain()
        authorization = self._approved_authorization()
        request = self._request(authorization)

        self.assertEqual(gate.evaluate(request).decision, D.APPROVED)
        outcome = service.execute(request, interval_seconds=0)
        self.assertTrue(outcome.succeeded)
        self.assertEqual(_create_calls(provider), 1)
        self.assertEqual(self._consumed_digests(), {authorization_id_sha256(authorization.authorization_id)})


# ----------------------------------------------------------------------
# 3. Empreinte absente / mal formée, fichier absent ou illisible
# ----------------------------------------------------------------------


class TestMissingMalformedOrUnreadable(_Sandbox):
    def test_each_missing_digest_is_refused(self):
        for field_name in AUTHORIZATION_CONTENT_DIGEST_FIELDS:
            with self.subTest(field=field_name):
                provider, gate, service = self._gate_chain()
                authorization = self._approved_authorization(**{field_name: None})
                request = self._request(authorization)

                result = gate.evaluate(request)
                self.assertEqual(result.decision, D.NEEDS_APPROVAL)
                self.assertReasonsMention(result.reasons, f"{field_name} is missing")
                with self.assertRaises(GenerationJobExecutionError):
                    service.execute(request, interval_seconds=0)
                self.assertNothingHappened(provider, gate, authorization)

    def test_malformed_digests_are_refused(self):
        canonical = authorization_content_digests(self._unbound())
        for bad in (canonical["prompt_sha256"].upper(), canonical["prompt_sha256"][:-1], "", 123, b"x"):
            with self.subTest(bad=bad):
                provider, gate, _ = self._gate_chain()
                authorization = self._approved_authorization(prompt_sha256=bad)
                result = gate.evaluate(self._request(authorization))
                self.assertEqual(result.decision, D.NEEDS_APPROVAL)
                self.assertReasonsMention(result.reasons, "prompt_sha256 is missing or not a lowercase")

    def test_missing_references_are_refused(self):
        for overrides, field_name in (
            (dict(start_image=None), "avatar_sha256"),
            (dict(image_references=()), "face_reference_sha256"),
        ):
            with self.subTest(field=field_name):
                provider, gate, service = self._gate_chain()
                authorization = self._approved_authorization()
                request = self._request(authorization, **overrides)
                result = gate.evaluate(request)
                self.assertEqual(result.decision, D.NEEDS_APPROVAL)
                self.assertReasonsMention(result.reasons, f"{field_name} cannot be verified")
                with self.assertRaises(GenerationJobExecutionError):
                    service.execute(request, interval_seconds=0)
                self.assertNothingHappened(provider, gate, authorization)

    def test_unreadable_files_are_refused(self):
        for overrides, field_name in (
            (content_media(self.tmp / "absent.png", self.face), "avatar_sha256"),
            (content_media(self.avatar, self.tmp), "face_reference_sha256"),  # a directory
        ):
            with self.subTest(field=field_name):
                provider, gate, service = self._gate_chain()
                authorization = self._approved_authorization()
                request = self._request(authorization, **overrides)
                result = gate.evaluate(request)
                self.assertEqual(result.decision, D.NEEDS_APPROVAL)
                self.assertReasonsMention(result.reasons, f"{field_name} cannot be verified")
                with self.assertRaises(GenerationJobExecutionError):
                    service.execute(request, interval_seconds=0)
                self.assertNothingHappened(provider, gate, authorization)

    def test_file_deleted_after_approval_is_refused_at_execution(self):
        provider, gate, service = self._gate_chain()
        authorization = self._approved_authorization()
        request = self._request(authorization)
        self.assertEqual(gate.evaluate(request).decision, D.APPROVED)

        self.face.unlink()
        with self.assertRaises(GenerationJobExecutionError) as ctx:
            service.execute(request, interval_seconds=0)
        self.assertReasonsMention(ctx.exception.approval.reasons, "face_reference_sha256 cannot be verified")
        self.assertNothingHappened(provider, gate, authorization)


# ----------------------------------------------------------------------
# 4. Mutation du contenu entre préparation et exécution
# ----------------------------------------------------------------------


class TestMutationBetweenPreparationAndExecution(_Sandbox):
    def _mutations(self):
        return (
            ("avatar_sha256", lambda request: self.avatar.write_bytes(b"replaced after approval") and request),
            ("face_reference_sha256", lambda request: self.face.write_bytes(b"replaced after approval") and request),
            ("prompt_sha256", lambda request: dataclasses.replace(request, prompt=CANONICAL_PROMPT + " ")),
        )

    def test_content_mutated_after_contract_preparation_is_refused(self):
        for gate_identity_lock in (False, True):
            for field_name, mutate in self._mutations():
                with self.subTest(field=field_name, gate_identity_lock=gate_identity_lock):
                    self.setUp()
                    provider, gate, activation, provider_activation, service = self._contract_stack(
                        gate_identity_lock=gate_identity_lock
                    )
                    authorization = self._approved_authorization()
                    request = self._request(authorization)
                    rs = activation.prepare_activation(request)
                    pa = provider_activation.prepare(request, rs)

                    mutated = mutate(request)
                    with self.assertRaises(GenerationJobExecutionError) as ctx:
                        service.execute(
                            mutated, interval_seconds=0,
                            activation_contract=rs, provider_activation_contract=pa,
                        )
                    if not gate_identity_lock:
                        # Seule la liaison autorisation <-> contenu refuse ici.
                        self.assertEqual(ctx.exception.approval.decision, D.NEEDS_APPROVAL)
                        self.assertReasonsMention(
                            ctx.exception.approval.reasons, f"{field_name} '", "given for different content"
                        )
                    else:
                        self.assertNotEqual(ctx.exception.approval.decision, D.APPROVED)
                    self.assertNothingHappened(provider, gate, authorization)
                    self.assertEqual(activation._consumed_activation_ids, set())
                    self.assertEqual(provider_activation._consumed_activation_ids, set())

    def test_asset_rewritten_between_evaluation_and_execution_without_contracts(self):
        provider, gate, service = self._gate_chain()
        authorization = self._approved_authorization()
        request = self._request(authorization)
        self.assertEqual(gate.evaluate(request).decision, D.APPROVED)

        self.avatar.write_bytes(b"swapped avatar")
        with self.assertRaises(GenerationJobExecutionError):
            service.execute(request, interval_seconds=0)
        self.assertNothingHappened(provider, gate, authorization)


# ----------------------------------------------------------------------
# 5. Contrat P2.21 lié à une autre autorisation
# ----------------------------------------------------------------------


class TestRequestScopedContractBoundToAnotherAuthorization(_Sandbox):
    def test_p2_21_contract_of_authorization_a_refused_for_authorization_b(self):
        provider, gate, activation, _, service = self._contract_stack()
        authorization_a = self._approved_authorization()
        authorization_b = self._approved_authorization()
        request_a = self._request(authorization_a)
        request_b = self._request(authorization_b)
        rs_a = activation.prepare_activation(request_a)

        reasons = activation.inspect_activation(request_b, rs_a)
        self.assertReasonsMention(reasons, f"bound to authorization '{authorization_a.authorization_id}'")
        with self.assertRaises(ActivationRejectedError):
            activation.validate_activation(request_b, rs_a)

        with self.assertRaises(GenerationJobActivationRejectedError):
            service.execute(request_b, interval_seconds=0, activation_contract=rs_a)
        self.assertNothingHappened(provider, gate, authorization_a, authorization_b)
        self.assertEqual(activation._consumed_activation_ids, set())

    def test_p2_21_contract_refused_when_request_has_no_authorization(self):
        _, _, activation, _, _ = self._contract_stack()
        request = self._request()
        rs = activation.prepare_activation(request)
        reasons = activation.inspect_activation(
            dataclasses.replace(request, real_generation_authorization=None), rs
        )
        self.assertReasonsMention(reasons, "not to this request's authorization None")


# ----------------------------------------------------------------------
# 6. Contrat P2.26 lié à une autre autorisation / paire incohérente
# ----------------------------------------------------------------------


class TestProviderContractBindingAndPairConsistency(_Sandbox):
    def _two_prepared_pairs(self):
        stack = self._contract_stack()
        _, _, activation, provider_activation, _ = stack
        authorization_a = self._approved_authorization()
        authorization_b = self._approved_authorization()
        request_a = self._request(authorization_a)
        request_b = self._request(authorization_b)
        rs_a = activation.prepare_activation(request_a)
        pa_a = provider_activation.prepare(request_a, rs_a)
        rs_b = activation.prepare_activation(request_b)
        pa_b = provider_activation.prepare(request_b, rs_b)
        return stack, (authorization_a, request_a, rs_a, pa_a), (authorization_b, request_b, rs_b, pa_b)

    def test_p2_26_contract_of_authorization_a_refused_for_authorization_b(self):
        stack, (auth_a, _, _, pa_a), (auth_b, request_b, rs_b, _) = self._two_prepared_pairs()
        provider, gate, activation, provider_activation, service = stack

        reasons = provider_activation.inspect(request_b, rs_b, pa_a)
        self.assertReasonsMention(
            reasons,
            f"bound to authorization '{auth_a.authorization_id}'",
            "contract pair was not prepared under one single authorization",
        )
        with self.assertRaises(GenerationJobProviderActivationRejectedError):
            service.execute(request_b, interval_seconds=0, activation_contract=rs_b, provider_activation_contract=pa_a)
        self.assertNothingHappened(provider, gate, auth_a, auth_b)
        self.assertEqual(activation._consumed_activation_ids, set())
        self.assertEqual(provider_activation._consumed_activation_ids, set())

    def test_inconsistent_pair_is_refused(self):
        stack, (auth_a, _, rs_a, _), (auth_b, request_b, _, pa_b) = self._two_prepared_pairs()
        provider, gate, activation, provider_activation, service = stack

        reasons = provider_activation.inspect(request_b, rs_a, pa_b)
        self.assertReasonsMention(reasons, "contract pair was not prepared under one single authorization")
        with self.assertRaises(GenerationJobExecutionError):
            service.execute(request_b, interval_seconds=0, activation_contract=rs_a, provider_activation_contract=pa_b)
        self.assertNothingHappened(provider, gate, auth_a, auth_b)

    def test_preparing_a_p2_26_contract_on_a_foreign_p2_21_contract_is_refused(self):
        stack, (_, _, rs_a, _), (_, request_b, _, _) = self._two_prepared_pairs()
        _, _, _, provider_activation, _ = stack
        with self.assertRaises(ControlledRealProviderActivationRejectedError) as ctx:
            provider_activation.prepare(request_b, rs_a)
        self.assertReasonsMention(ctx.exception.reasons, "contract pair was not prepared under one single authorization")

    def test_pair_prepared_under_a_cannot_be_executed_under_b(self):
        """Scénario de l'audit : contrats préparés sous A, requête
        présentée avec B (même request_id, même contenu, B valide)."""

        stack, (auth_a, _, rs_a, pa_a), (auth_b, request_b, _, _) = self._two_prepared_pairs()
        provider, gate, _, _, service = stack
        with self.assertRaises(GenerationJobExecutionError):
            service.execute(request_b, interval_seconds=0, activation_contract=rs_a, provider_activation_contract=pa_a)
        self.assertNothingHappened(provider, gate, auth_a, auth_b)

    def test_matching_pair_executes_and_consumes_only_its_own_authorization(self):
        stack, (auth_a, _, _, _), (auth_b, request_b, rs_b, pa_b) = self._two_prepared_pairs()
        provider, gate, _, _, service = stack
        outcome = service.execute(
            request_b, interval_seconds=0, activation_contract=rs_b, provider_activation_contract=pa_b
        )
        self.assertTrue(outcome.succeeded)
        self.assertEqual(_create_calls(provider), 1)
        self.assertEqual(outcome.job.raw["provider_activation_contract"].authorization_id, auth_b.authorization_id)
        self.assertTrue(gate.is_authorization_consumed(auth_b.authorization_id))
        self.assertFalse(gate.is_authorization_consumed(auth_a.authorization_id))


# ----------------------------------------------------------------------
# 7. Appels sans contrats (GenerationJobService / FinalReportService /
#    run_video_mission)
# ----------------------------------------------------------------------


class TestCallsWithoutContracts(_Sandbox):
    def test_final_report_service_without_contracts_refuses_foreign_content(self):
        provider, gate, service = self._gate_chain()
        authorization = self._approved_authorization()
        report = FinalReportService(provider, gate, job_service=service).generate(
            self._request(authorization, prompt="another prompt"), interval_seconds=0
        )
        self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)
        self.assertEqual(report.approval_decision, D.NEEDS_APPROVAL)
        self.assertFalse(report.job_created)
        self.assertNothingHappened(provider, gate, authorization)

    def test_run_video_mission_requires_authorization_for_the_assembled_content(self):
        from director import AIDirector

        for authorization, expected in (
            (video_005_authorization(prompt_sha256="0" * 64), FinalReportStatus.NOT_EXECUTED),
            (video_005_authorization(avatar_sha256="0" * 64), FinalReportStatus.NOT_EXECUTED),
            (video_005_authorization(face_reference_sha256="0" * 64), FinalReportStatus.NOT_EXECUTED),
            (video_005_authorization(), FinalReportStatus.EXECUTED_PASS),
        ):
            with self.subTest(authorization=authorization):
                self.setUp()
                provider, gate, service = self._gate_chain(cost=10.0, identity_lock=True)
                report = AIDirector().run_video_mission(
                    video_id=C.request_id, title="t", hook="h", objective="o",
                    duration=C.duration, approved=True,
                    real_generation_authorization=authorization,
                    report_service=FinalReportService(provider, gate, job_service=service),
                    interval_seconds=0,
                )
                self.assertEqual(report.status, expected)
                consumed = gate.is_authorization_consumed(authorization.authorization_id)
                self.assertEqual(consumed, expected == FinalReportStatus.EXECUTED_PASS)
                self.assertEqual(_create_calls(provider), int(expected == FinalReportStatus.EXECUTED_PASS))


# ----------------------------------------------------------------------
# 8. APPROVED (coût KNOWN et UNKNOWN) uniquement si tout concorde
# ----------------------------------------------------------------------


class TestKnownAndUnknownCostApproval(_Sandbox):
    def test_approved_only_when_every_digest_matches(self):
        for cost, label in ((67.5, "KNOWN"), (None, "UNKNOWN")):
            provider, gate, _ = self._gate_chain(cost=cost)
            with self.subTest(cost=label, case="all match"):
                result = gate.evaluate(self._request())
                # Phase D : un coût UNKNOWN n'est jamais approuvable, même
                # quand toutes les empreintes correspondent.
                self.assertEqual(result.decision, D.APPROVED if label == "KNOWN" else D.BLOCKED)
                self.assertEqual(result.cost_result.status.value, label.lower())

            divergent = {
                "prompt": dict(prompt="another prompt"),
                "avatar": content_media(self.other, self.face),
                "face": content_media(self.avatar, self.other),
            }
            for case, overrides in divergent.items():
                with self.subTest(cost=label, case=case):
                    result = gate.evaluate(self._request(**overrides))
                    self.assertEqual(result.decision, D.NEEDS_APPROVAL)
                    self.assertEqual(result.cost_result.status.value, label.lower())

            for field_name in AUTHORIZATION_CONTENT_DIGEST_FIELDS:
                with self.subTest(cost=label, case=f"{field_name} missing"):
                    authorization = self._approved_authorization(**{field_name: None})
                    self.assertEqual(gate.evaluate(self._request(authorization)).decision, D.NEEDS_APPROVAL)
            self.assertEqual(_create_calls(provider), 0)


# ----------------------------------------------------------------------
# 9. Usage unique conservé ; aucune consommation après un refus préalable
# ----------------------------------------------------------------------


class TestSingleUsePreserved(_Sandbox):
    def test_refused_attempt_consumes_nothing_then_the_matching_attempt_consumes_once(self):
        provider, gate, service = self._gate_chain()
        authorization = self._approved_authorization()

        with self.assertRaises(GenerationJobExecutionError):
            service.execute(self._request(authorization, prompt="another prompt"), interval_seconds=0)
        self.assertNothingHappened(provider, gate, authorization)

        service.execute(self._request(authorization), interval_seconds=0)
        self.assertEqual(_create_calls(provider), 1)
        self.assertEqual(self._consumed_digests(), {authorization_id_sha256(authorization.authorization_id)})

        self.assertEqual(gate.evaluate(self._request(authorization)).decision, D.ALREADY_EXECUTED)
        with self.assertRaises(GenerationJobExecutionError):
            service.execute(self._request(authorization), interval_seconds=0)
        self.assertEqual(_create_calls(provider), 1)

    def test_provider_refusal_keeps_the_bound_authorization_consumed(self):
        # Phase D : fixtures explicites (sans effet sur le Mock reconnu,
        # conservées) : plafond + Identity Lock (contenu canonique C).
        provider, gate, service = self._gate_chain(
            refuse=True, identity_lock=True, max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST
        )
        authorization = self._approved_authorization()

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            service.execute(self._request(authorization), interval_seconds=0)
        self.assertTrue(gate.is_authorization_consumed(authorization.authorization_id))

        result = gate.evaluate(self._request(authorization))
        self.assertEqual(result.decision, D.NEEDS_APPROVAL)
        self.assertReasonsMention(result.reasons, "has already been consumed")
        with self.assertRaises(GenerationJobExecutionError):
            service.execute(self._request(authorization), interval_seconds=0)
        self.assertEqual(provider.create_calls, 1)

    def test_content_binding_does_not_make_a_consumed_authorization_reusable(self):
        # Phase D : fixtures explicites (sans effet sur le Mock reconnu,
        # conservées) : plafond + Identity Lock liés aux DEUX
        # contenus exacts évalués (canonique, puis « another prompt »).
        provider, gate, service = self._gate_chain(
            refuse=True,
            identity_lock=fixture_identity_lock_for(
                self._unbound(), self._unbound(prompt="another prompt")
            ),
            max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST,
        )
        authorization = self._approved_authorization()
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            service.execute(self._request(authorization), interval_seconds=0)

        rebound = bound_authorization(
            self._unbound(prompt="another prompt"), authorization,
            prompt_sha256=authorization_content_digests(self._unbound(prompt="another prompt"))["prompt_sha256"],
        )
        self.assertEqual(rebound.authorization_id, authorization.authorization_id)
        result = gate.evaluate(self._request(rebound, prompt="another prompt"))
        self.assertEqual(result.decision, D.NEEDS_APPROVAL)
        self.assertReasonsMention(result.reasons, "has already been consumed")
        self.assertEqual(provider.create_calls, 1)


# ----------------------------------------------------------------------
# 10. Aucun vrai client Higgsfield n'est jamais atteint
# ----------------------------------------------------------------------


class TestRealClientNeverReached(_Sandbox):
    def _real_provider(self):
        client = MagicMock()
        client.estimate_cost.return_value = {"credits": 67.5}
        client.account_status.return_value = {"credits": 1000.0}
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
        return HiggsfieldProvider(client=client), client

    def test_fully_bound_request_still_stops_at_the_real_provider(self):
        provider, client = self._real_provider()
        # Phase D : plafond de FIXTURE explicite (chemin réel).
        _, gate, service = self._gate_chain(
            provider=provider, identity_lock=True, max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST
        )
        authorization = self._approved_authorization()
        request = self._request(authorization)

        self.assertEqual(gate.evaluate(request).decision, D.APPROVED)
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            service.execute(request, interval_seconds=0)
        client.create_job.assert_not_called()
        self.assertNotIn("create_job", [call[0] for call in client.method_calls])

    def test_p2_26_preparation_is_refused_against_the_real_provider(self):
        provider, client = self._real_provider()
        # Phase D : plafond de FIXTURE explicite (chemin réel).
        _, _, activation, provider_activation, _ = self._contract_stack(
            provider=provider, max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST
        )
        request = self._request()
        rs = activation.prepare_activation(request)
        with self.assertRaises(ControlledRealProviderActivationRejectedError):
            provider_activation.prepare(request, rs)
        client.create_job.assert_not_called()

    def test_foreign_content_never_reaches_the_real_provider(self):
        provider, client = self._real_provider()
        authorization = self._approved_authorization()
        # Phase D : vrai Provider -> plafond + Identity Lock EXPLICITES, ce
        # dernier lié au contenu étranger évalué, pour que le refus vienne de
        # la liaison autorisation <-> contenu (et non du chemin réel).
        _, gate, service = self._gate_chain(
            provider=provider,
            identity_lock=fixture_identity_lock_for(self._unbound(prompt="another prompt")),
            max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST,
        )
        with self.assertRaises(GenerationJobExecutionError) as ctx:
            service.execute(self._request(authorization, prompt="another prompt"), interval_seconds=0)
        self.assertEqual(ctx.exception.approval.decision, D.NEEDS_APPROVAL)
        self.assertReasonsMention(ctx.exception.approval.reasons, "given for different content")
        client.create_job.assert_not_called()
        self.assertFalse(gate.is_authorization_consumed(authorization.authorization_id))


if __name__ == "__main__":
    unittest.main()
