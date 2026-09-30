"""
Tests — Phase E2 : dernier contrôle du contenu avant toute consommation
(limite A2-c de
docs/phase_e_authorization_limits_ceiling_revocation_shutdown_design.md).

`GenerationJobService.execute()` vérifie une dernière fois, après le Gate
et les contrats et avant toute consommation, que le contenu de la requête
(prompt, avatar, référence visage) est celui que porte l'autorisation,
puis transmet à `create_job()` exactement les empreintes de ce contrôle.

Ces tests verrouillent :

1. un fichier remplacé, supprimé ou devenu illisible APRÈS la vérification
   du Gate (et l'inspection du contrat P2.21) est refusé avant toute
   consommation : autorisation et contrats P2.21/P2.26 intacts, aucun
   marqueur, aucun enregistrement, aucun job. Le contrat P2.26 est
   consommé par sa propre validation : le dernier contrôle la précède, et
   une altération entre les deux est refusée par cette validation, elle
   aussi sans rien consommer ;
2. le cas nominal transmet exactement les empreintes vérifiées ;
3. la limite résiduelle : un remplacement APRÈS le dernier contrôle n'est
   pas détecté -- les empreintes transmises restent celles contrôlées et
   aucun fichier n'est relu ;
4. `FinalReportService` rapporte NOT_EXECUTED, avec des champs de
   diagnostic exacts : le contrat P2.21 inspecté est APPROVED (non
   consommé), le contrat P2.26 jamais validé reste NOT_EVALUATED ;
5. l'ordre des étapes dans `execute()` (statique), le Provider réel
   toujours refusé et la garde Phase D inchangée.

MOCK-ONLY : `MockHiggsfieldProvider`, ou vrai `HiggsfieldProvider` sur un
client factice (jamais de réseau ni de sous-processus). Stores, registres
et verrous dans un dossier temporaire ; `state/` réel n'est jamais touché.
Les assets réels de Video 005 sont uniquement LUS (copiés dans le dossier
temporaire, où seuls les tests les modifient).
"""

import ast
import dataclasses
import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import agents.generation_job_service as job_service_module
from agents.activation_contract import RequestScopedActivationService
from agents.controlled_real_provider_activation import ControlledRealProviderActivationService
from agents.critical_section_lock import FileCriticalSectionLock
from agents.executed_request_store import FileExecutedRequestStore
from agents.final_report_service import ActivationDecision, FinalReportService, FinalReportStatus
from agents.generation_approval_gate import (
    AUTHORIZATION_CONTENT_DIGEST_FIELDS,
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationApprovalResult,
    GenerationRequest,
    RealGenerationAuthorization,
    authorization_content_digests,
)
from agents.generation_job_service import (
    GenerationJobContentChangedError,
    GenerationJobExecutionError,
    GenerationJobProviderActivationRejectedError,
    GenerationJobProviderNotAllowedError,
    GenerationJobService,
    _final_content_violations,
)
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.release_candidate_identity_lock import (
    ReleaseCandidateIdentityLock,
    VIDEO_005_RELEASE_CANDIDATE as C,
)
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider
from tests.authorization_content_helpers import (
    REAL_AVATAR_PATH,
    REAL_FACE_PATH,
    bound_authorization,
    content_media,
)
from tests.real_provider_path_fixtures import FIXTURE_MAX_COST_CREDITS_PER_REQUEST
from tests.test_phase_d_cost_fail_closed import _fake_client

D = GenerationApprovalDecision
CANONICAL_PROMPT = PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id)
SERVICE_FILE = PROJECT_ROOT / "agents" / "generation_job_service.py"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Sandbox(unittest.TestCase):
    """Dossier temporaire avec des COPIES octet-à-octet des assets réels
    (même SHA-256, donc conformes à l'Identity Lock), que les tests
    peuvent remplacer sans jamais toucher aux originaux."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="phase_e2_final_content_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.avatar = self.tmp / "avatar.png"
        self.face = self.tmp / "face.png"
        shutil.copyfile(REAL_AVATAR_PATH, self.avatar)
        shutil.copyfile(REAL_FACE_PATH, self.face)
        self.state_dir = self.tmp / "state"
        self.state_path = self.state_dir / "executed_requests.json"
        self.lock_dir = self.tmp / "locks"

    # --- requêtes -----------------------------------------------------

    def _request(self) -> GenerationRequest:
        unbound = GenerationRequest(
            **content_media(self.avatar, self.face),
            request_id=C.request_id,
            job_type=C.job_type,
            prompt=CANONICAL_PROMPT,
            duration=C.duration,
            resolution=C.resolution,
            aspect_ratio=C.aspect_ratio,
            approved=True,
        )
        return dataclasses.replace(unbound, real_generation_authorization=bound_authorization(unbound))

    # --- chaînes ------------------------------------------------------

    def _gate_chain(self, provider=None, **gate_kwargs):
        provider = provider or MockHiggsfieldProvider(cost_per_job=67.5, available_credits=1000.0)
        gate = GenerationApprovalGate(
            provider, executed_request_store=FileExecutedRequestStore(self.state_path), **gate_kwargs
        )
        service = GenerationJobService(provider, gate, lock=FileCriticalSectionLock(self.lock_dir))
        return provider, gate, service

    def _contract_stack(self):
        provider = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=1000.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(
            provider,
            executed_request_store=FileExecutedRequestStore(self.state_path),
            identity_lock=identity_lock,
        )
        activation = RequestScopedActivationService(gate, identity_lock)
        provider_activation = ControlledRealProviderActivationService(gate, identity_lock, activation)
        service = GenerationJobService(
            provider,
            gate,
            lock=FileCriticalSectionLock(self.lock_dir),
            activation_service=activation,
            provider_activation_service=provider_activation,
        )
        return provider, gate, activation, provider_activation, service

    # --- altérations du contenu ---------------------------------------

    # (libellé, empreinte concernée, attribut du fichier, altération,
    # fragment attendu dans la raison du refus).
    ALTERATIONS = (
        ("avatar replaced", "avatar_sha256", "avatar", "replace", "the content changed after the Gate verified it"),
        ("face reference replaced", "face_reference_sha256", "face", "replace",
         "the content changed after the Gate verified it"),
        ("avatar deleted", "avatar_sha256", "avatar", "delete", "is missing or unreadable"),
        ("face reference deleted", "face_reference_sha256", "face", "delete", "is missing or unreadable"),
        ("avatar unreadable", "avatar_sha256", "avatar", "make_unreadable", "is missing or unreadable"),
        ("face reference unreadable", "face_reference_sha256", "face", "make_unreadable",
         "is missing or unreadable"),
    )

    def _alteration(self, attribute, kind):
        """Altération du fichier `self.<attribute>` du sandbox COURANT,
        résolu au moment de l'appel (jamais celui d'un `setUp()` antérieur)."""

        def alter():
            path = getattr(self, attribute)
            if kind == "replace":
                path.write_bytes(b"replaced after the Gate's verification")
            elif kind == "delete":
                path.unlink()
            else:
                # Un dossier à la place du fichier : l'ouverture en lecture
                # échoue (OSError) sur toutes les plateformes.
                path.unlink()
                path.mkdir()

        return alter

    def _restore_assets(self):
        for path, original in ((self.avatar, REAL_AVATAR_PATH), (self.face, REAL_FACE_PATH)):
            if path.is_dir():
                path.rmdir()
            shutil.copyfile(original, path)

    @staticmethod
    def _after_first_call(target, attribute, alter):
        """Enveloppe `target.attribute` : le PREMIER appel s'exécute
        réellement, puis `alter()` est appliqué une seule fois -- le
        contenu change donc juste APRÈS cette étape de vérification."""

        original = getattr(target, attribute)
        state = {"done": False}

        def wrapper(*args, **kwargs):
            result = original(*args, **kwargs)
            if not state["done"]:
                state["done"] = True
                alter()
            return result

        return mock.patch.object(target, attribute, side_effect=wrapper)

    # --- assertions ---------------------------------------------------

    def assertNothingWasConsumedOrWritten(self, provider, gate, request):
        authorization = request.real_generation_authorization
        self.assertEqual(provider._jobs, {}, "no job may exist in the Mock")
        self.assertFalse(gate.is_authorization_consumed(authorization.authorization_id))
        self.assertFalse(gate.is_already_executed(request.request_id))
        self.assertFalse(gate.executed_request_store.is_unknown(request.request_id))
        written = sorted(p.name for p in self.state_dir.glob("*")) if self.state_dir.exists() else []
        self.assertEqual(written, [], "no execution record, in-flight marker or consumption registry")
        leftover_locks = sorted(p.name for p in self.lock_dir.glob("*")) if self.lock_dir.exists() else []
        self.assertEqual(leftover_locks, [], "the critical section must be released")

    def assertRefusedAtFinalCheck(self, error, field_name, fragment):
        self.assertIsInstance(error, GenerationJobContentChangedError)
        # Le Gate AVAIT approuvé : c'est après lui que le contenu a changé.
        self.assertEqual(error.approval.decision, D.APPROVED)
        self.assertTrue(
            any(reason.startswith(f"{field_name} ") and fragment in reason for reason in error.reasons),
            error.reasons,
        )


# ----------------------------------------------------------------------
# 1. Contenu altéré après la vérification : refus avant toute consommation
# ----------------------------------------------------------------------


class ContentAlteredAfterGateEvaluationIsRefused(_Sandbox):
    def test_without_contracts_nothing_is_consumed_or_written(self):
        for label, field_name, attribute, kind, fragment in self.ALTERATIONS:
            with self.subTest(alteration=label):
                self.setUp()
                alter = self._alteration(attribute, kind)
                provider, gate, service = self._gate_chain()
                request = self._request()

                with self._after_first_call(gate, "evaluate", alter) as evaluate:
                    with self.assertRaises(GenerationJobContentChangedError) as caught:
                        service.execute(request, interval_seconds=0)

                self.assertEqual(evaluate.call_count, 1)
                self.assertRefusedAtFinalCheck(caught.exception, field_name, fragment)
                self.assertNothingWasConsumedOrWritten(provider, gate, request)

    def test_same_authorization_still_executes_once_the_content_is_restored(self):
        """Preuve directe que le refus n'a rien consommé : la MÊME
        autorisation reste utilisable dès que le contenu autorisé est
        de retour."""

        provider, gate, service = self._gate_chain()
        request = self._request()
        alter = self._alteration("avatar", "replace")

        with self._after_first_call(gate, "evaluate", alter):
            with self.assertRaises(GenerationJobContentChangedError):
                service.execute(request, interval_seconds=0)
        self.assertNothingWasConsumedOrWritten(provider, gate, request)

        self._restore_assets()
        outcome = service.execute(request, interval_seconds=0)
        self.assertEqual(list(provider._jobs), [outcome.job.job_id])
        self.assertTrue(gate.is_authorization_consumed(request.real_generation_authorization.authorization_id))

    def test_with_p2_21_and_p2_26_contracts_both_contracts_stay_unconsumed(self):
        for label, field_name, attribute, kind, fragment in self.ALTERATIONS:
            with self.subTest(alteration=label):
                self.setUp()
                alter = self._alteration(attribute, kind)
                provider, gate, activation, provider_activation, service = self._contract_stack()
                request = self._request()
                rs_contract = activation.prepare_activation(request)
                pa_contract = provider_activation.prepare(request, rs_contract)

                # Altération juste après l'inspection du contrat P2.21 par
                # `execute()` (qui suit l'évaluation du Gate) : dernière
                # validation avant le contrôle final.
                with self._after_first_call(activation, "inspect_activation", alter), \
                        mock.patch.object(
                            provider_activation, "validate", wraps=provider_activation.validate
                        ) as validate:
                    with self.assertRaises(GenerationJobContentChangedError) as caught:
                        service.execute(
                            request, interval_seconds=0,
                            activation_contract=rs_contract, provider_activation_contract=pa_contract,
                        )

                validate.assert_not_called()
                self.assertRefusedAtFinalCheck(caught.exception, field_name, fragment)
                self.assertNothingWasConsumedOrWritten(provider, gate, request)
                self.assertEqual(activation._consumed_activation_ids, set())
                self.assertEqual(provider_activation._consumed_activation_ids, set())

    def test_contracts_remain_usable_once_the_content_is_restored(self):
        provider, gate, activation, provider_activation, service = self._contract_stack()
        request = self._request()
        rs_contract = activation.prepare_activation(request)
        pa_contract = provider_activation.prepare(request, rs_contract)
        alter = self._alteration("face", "replace")

        with self._after_first_call(activation, "inspect_activation", alter):
            with self.assertRaises(GenerationJobContentChangedError):
                service.execute(
                    request, interval_seconds=0,
                    activation_contract=rs_contract, provider_activation_contract=pa_contract,
                )

        self._restore_assets()
        outcome = service.execute(
            request, interval_seconds=0,
            activation_contract=rs_contract, provider_activation_contract=pa_contract,
        )
        self.assertEqual(list(provider._jobs), [outcome.job.job_id])
        self.assertEqual(activation._consumed_activation_ids, {rs_contract.activation_id})
        self.assertEqual(provider_activation._consumed_activation_ids, {pa_contract.activation_id})

    def test_with_p2_21_contract_only_refusal_consumes_nothing(self):
        """Contrat P2.21 SEUL (sans P2.26) : le dernier contrôle suit son
        inspection et précède directement sa consommation."""

        for label, field_name, attribute, kind, fragment in self.ALTERATIONS:
            with self.subTest(alteration=label):
                self.setUp()
                alter = self._alteration(attribute, kind)
                provider, gate, activation, provider_activation, service = self._contract_stack()
                request = self._request()
                rs_contract = activation.prepare_activation(request)

                with self._after_first_call(activation, "inspect_activation", alter) as inspect, \
                        mock.patch.object(activation, "consume", wraps=activation.consume) as consume:
                    with self.assertRaises(GenerationJobContentChangedError) as caught:
                        service.execute(request, interval_seconds=0, activation_contract=rs_contract)

                self.assertEqual(inspect.call_count, 1)
                consume.assert_not_called()
                self.assertRefusedAtFinalCheck(caught.exception, field_name, fragment)
                self.assertNothingWasConsumedOrWritten(provider, gate, request)
                self.assertEqual(activation._consumed_activation_ids, set())
                self.assertEqual(provider_activation._consumed_activation_ids, set())

    def test_with_p2_21_contract_only_executes_once_the_content_is_restored(self):
        provider, gate, activation, provider_activation, service = self._contract_stack()
        request = self._request()
        authorization = request.real_generation_authorization
        rs_contract = activation.prepare_activation(request)
        alter = self._alteration("avatar", "replace")

        with self._after_first_call(activation, "inspect_activation", alter):
            with self.assertRaises(GenerationJobContentChangedError):
                service.execute(request, interval_seconds=0, activation_contract=rs_contract)
        self.assertNothingWasConsumedOrWritten(provider, gate, request)
        self.assertEqual(activation._consumed_activation_ids, set())

        self._restore_assets()
        outcome = service.execute(request, interval_seconds=0, activation_contract=rs_contract)

        self.assertEqual(list(provider._jobs), [outcome.job.job_id])
        raw = provider._jobs[outcome.job.job_id]
        self.assertEqual(raw["avatar_sha256"], authorization.avatar_sha256)
        self.assertEqual(raw["face_reference_sha256"], authorization.face_reference_sha256)
        self.assertIsNone(raw["provider_activation_contract"])
        self.assertEqual(activation._consumed_activation_ids, {rs_contract.activation_id})
        self.assertEqual(provider_activation._consumed_activation_ids, set())
        self.assertTrue(gate.is_authorization_consumed(authorization.authorization_id))
        self.assertTrue(gate.is_already_executed(request.request_id))

    def test_alteration_between_the_final_check_and_p2_26_validation_is_refused_by_p2_26(self):
        """Le contrat P2.26 est consommé par sa propre validation, qui suit
        donc le dernier contrôle. Une altération entre les deux est refusée
        par cette validation (elle relit les fichiers), sans rien consommer."""

        for label, _, attribute, kind, _ in self.ALTERATIONS:
            with self.subTest(alteration=label):
                self.setUp()
                alter = self._alteration(attribute, kind)
                provider, gate, activation, provider_activation, service = self._contract_stack()
                request = self._request()
                rs_contract = activation.prepare_activation(request)
                pa_contract = provider_activation.prepare(request, rs_contract)

                with self._after_first_call(job_service_module, "_final_content_violations", alter) as final_check:
                    with self.assertRaises(GenerationJobProviderActivationRejectedError):
                        service.execute(
                            request, interval_seconds=0,
                            activation_contract=rs_contract, provider_activation_contract=pa_contract,
                        )

                self.assertEqual(final_check.call_count, 1)
                self.assertNothingWasConsumedOrWritten(provider, gate, request)
                self.assertEqual(activation._consumed_activation_ids, set())
                self.assertEqual(provider_activation._consumed_activation_ids, set())

    def test_final_check_does_not_rely_on_the_gate_decision_alone(self):
        """Défense en profondeur : même si une décision APPROVED était
        obtenue pour un contenu que l'autorisation ne couvre pas, le
        dernier contrôle compare lui-même le contenu à l'autorisation."""

        provider, gate, service = self._gate_chain()
        request = self._request()
        self.avatar.write_bytes(b"never authorized")
        forced = GenerationApprovalResult(decision=D.APPROVED, request_id=request.request_id, job_type=request.job_type)

        with mock.patch.object(gate, "evaluate", return_value=forced):
            with self.assertRaises(GenerationJobContentChangedError) as caught:
                service.execute(request, interval_seconds=0)

        self.assertRefusedAtFinalCheck(caught.exception, "avatar_sha256", "the content changed")
        self.assertNothingWasConsumedOrWritten(provider, gate, request)


# ----------------------------------------------------------------------
# 2. Contrat des empreintes : aucune n'est optionnelle
# ----------------------------------------------------------------------


class AuthorizedDigestsAreNeverOptional(_Sandbox):
    def test_gate_never_approves_a_request_without_a_face_reference(self):
        """Ce que le dernier contrôle suppose : le Gate n'approuve jamais
        une requête sans référence visage, même si l'autorisation déclare
        elle aussi `None`. `None` n'est donc jamais une valeur autorisée."""

        provider, gate, service = self._gate_chain()
        unbound = dataclasses.replace(self._request(), image_references=(), real_generation_authorization=None)
        authorization = bound_authorization(unbound)
        self.assertIsNone(authorization.face_reference_sha256)
        request = dataclasses.replace(unbound, real_generation_authorization=authorization)

        with self.assertRaises(GenerationJobExecutionError) as caught:
            service.execute(request, interval_seconds=0)

        self.assertNotIsInstance(caught.exception, GenerationJobContentChangedError)
        self.assertNotEqual(caught.exception.approval.decision, D.APPROVED)
        self.assertNothingWasConsumedOrWritten(provider, gate, request)

    def test_final_check_compares_the_exact_authorized_values(self):
        request = self._request()
        live = authorization_content_digests(request)
        authorization = request.real_generation_authorization
        self.assertEqual({name: getattr(authorization, name) for name in AUTHORIZATION_CONTENT_DIGEST_FIELDS}, live)
        self.assertEqual(_final_content_violations(request, live), [])

        for name in AUTHORIZATION_CONTENT_DIGEST_FIELDS:
            with self.subTest(field=name, case="live value missing"):
                reasons = _final_content_violations(request, {**live, name: None})
                self.assertEqual(len(reasons), 1)
                self.assertIn(f"{name} cannot be verified", reasons[0])
            with self.subTest(field=name, case="live value differs"):
                reasons = _final_content_violations(request, {**live, name: _sha256(b"other")})
                self.assertEqual(len(reasons), 1)
                self.assertIn("the content changed after the Gate verified it", reasons[0])
            with self.subTest(field=name, case="both missing is never a match"):
                unbound_field = dataclasses.replace(
                    request, real_generation_authorization=dataclasses.replace(authorization, **{name: None})
                )
                self.assertEqual(len(_final_content_violations(unbound_field, {**live, name: None})), 1)
            with self.subTest(field=name, case="authorization does not declare it"):
                unbound_field = dataclasses.replace(
                    request, real_generation_authorization=dataclasses.replace(authorization, **{name: None})
                )
                self.assertEqual(len(_final_content_violations(unbound_field, live)), 1)

    def test_request_without_a_real_authorization_is_refused(self):
        request = dataclasses.replace(self._request(), real_generation_authorization=None)
        live = authorization_content_digests(request)
        for authorization in (None, "authorized", object()):
            with self.subTest(authorization=authorization):
                candidate = dataclasses.replace(request, real_generation_authorization=authorization)
                reasons = _final_content_violations(candidate, live)
                self.assertEqual(len(reasons), 1)
                self.assertIn("no RealGenerationAuthorization", reasons[0])


# ----------------------------------------------------------------------
# 3. Cas nominal et limite résiduelle
# ----------------------------------------------------------------------


class VerifiedDigestsAreTheOnesTransmitted(_Sandbox):
    def _transmitted(self, provider, outcome):
        raw = provider._jobs[outcome.job.job_id]
        return {"avatar_sha256": raw["avatar_sha256"], "face_reference_sha256": raw["face_reference_sha256"]}

    def test_nominal_mock_records_exactly_the_verified_digests(self):
        provider, gate, service = self._gate_chain()
        request = self._request()
        authorization = request.real_generation_authorization

        outcome = service.execute(request, interval_seconds=0)

        self.assertEqual(
            self._transmitted(provider, outcome),
            {
                "avatar_sha256": authorization.avatar_sha256,
                "face_reference_sha256": authorization.face_reference_sha256,
            },
        )
        self.assertEqual(authorization.avatar_sha256, C.avatar_master_sha256)
        self.assertEqual(authorization.face_reference_sha256, C.face_reference_sha256)
        self.assertEqual(provider._jobs[outcome.job.job_id]["prompt"], CANONICAL_PROMPT)

    def test_nominal_with_contracts_transmits_the_contract_digests(self):
        provider, gate, activation, provider_activation, service = self._contract_stack()
        request = self._request()
        rs_contract = activation.prepare_activation(request)
        pa_contract = provider_activation.prepare(request, rs_contract)

        outcome = service.execute(
            request, interval_seconds=0,
            activation_contract=rs_contract, provider_activation_contract=pa_contract,
        )

        self.assertEqual(
            self._transmitted(provider, outcome),
            {"avatar_sha256": pa_contract.avatar_sha256, "face_reference_sha256": pa_contract.face_reference_sha256},
        )

    def test_replacement_after_the_final_check_is_not_detected_and_no_file_is_read_again(self):
        """LIMITE RÉSIDUELLE, documentée et non corrigée par la Phase E2 :
        un fichier remplacé APRÈS le dernier contrôle (ici, pendant la
        consommation de l'autorisation) n'est pas détecté. Les empreintes
        transmises restent celles du contrôle, et plus aucun fichier
        d'asset n'est ouvert ensuite."""

        provider, gate, service = self._gate_chain()
        request = self._request()
        authorization = request.real_generation_authorization
        late_content = b"replaced after the final check"
        assets = {self.avatar.resolve(), self.face.resolve()}
        events = []

        original_open = Path.open

        def recording_open(path, *args, **kwargs):
            mode = args[0] if args else kwargs.get("mode", "r")
            if "r" in mode and Path(path).resolve() in assets:
                events.append(("asset read", Path(path).name))
            return original_open(path, *args, **kwargs)

        original_consume = gate.consume_authorization

        def consume_then_replace(*args, **kwargs):
            events.append(("consumption", None))
            self.avatar.write_bytes(late_content)
            self.face.write_bytes(late_content)
            return original_consume(*args, **kwargs)

        with mock.patch.object(Path, "open", autospec=True, side_effect=recording_open), \
                mock.patch.object(gate, "consume_authorization", side_effect=consume_then_replace):
            outcome = service.execute(request, interval_seconds=0)

        consumption_index = events.index(("consumption", None))
        opened_before = events[:consumption_index]
        self.assertIn(("asset read", self.avatar.name), opened_before, "the recorder must see asset reads")
        self.assertIn(("asset read", self.face.name), opened_before)
        self.assertEqual(events[consumption_index + 1:], [], "no asset file may be read after the final check")

        transmitted = self._transmitted(provider, outcome)
        self.assertEqual(transmitted["avatar_sha256"], authorization.avatar_sha256)
        self.assertEqual(transmitted["face_reference_sha256"], authorization.face_reference_sha256)
        # Le fichier sur disque n'est plus celui dont l'empreinte a été
        # transmise : c'est exactement la limite documentée.
        self.assertEqual(authorization_content_digests(request)["avatar_sha256"], _sha256(late_content))
        self.assertNotEqual(transmitted["avatar_sha256"], _sha256(late_content))


    def test_with_contracts_replacement_after_p2_26_validation_is_not_detected_either(self):
        """Même limite sur le chemin à contrats : après la validation P2.26
        (dernière lecture des fichiers), un remplacement n'est pas détecté
        et les empreintes transmises restent celles contrôlées."""

        provider, gate, activation, provider_activation, service = self._contract_stack()
        request = self._request()
        authorization = request.real_generation_authorization
        rs_contract = activation.prepare_activation(request)
        pa_contract = provider_activation.prepare(request, rs_contract)
        assets = {self.avatar.resolve(), self.face.resolve()}
        events = []
        original_open = Path.open

        def recording_open(path, *args, **kwargs):
            mode = args[0] if args else kwargs.get("mode", "r")
            if "r" in mode and Path(path).resolve() in assets:
                events.append(("asset read", Path(path).name))
            return original_open(path, *args, **kwargs)

        def replace_after_validation():
            events.append(("P2.26 validated", None))
            self.avatar.write_bytes(b"replaced after the P2.26 validation")

        with mock.patch.object(Path, "open", autospec=True, side_effect=recording_open), \
                self._after_first_call(provider_activation, "validate", replace_after_validation):
            outcome = service.execute(
                request, interval_seconds=0,
                activation_contract=rs_contract, provider_activation_contract=pa_contract,
            )

        validated_index = events.index(("P2.26 validated", None))
        self.assertIn(("asset read", self.avatar.name), events[:validated_index])
        self.assertEqual(events[validated_index + 1:], [], "no asset file may be read after the P2.26 validation")
        transmitted = self._transmitted(provider, outcome)
        self.assertEqual(transmitted["avatar_sha256"], authorization.avatar_sha256)
        self.assertEqual(transmitted["avatar_sha256"], pa_contract.avatar_sha256)
        self.assertEqual(transmitted["face_reference_sha256"], authorization.face_reference_sha256)


# ----------------------------------------------------------------------
# 4. FinalReportService
# ----------------------------------------------------------------------


class FinalReportIsNotExecuted(_Sandbox):
    def test_refusal_at_the_final_check_is_reported_not_executed(self):
        provider, gate, service = self._gate_chain()
        request = self._request()
        alter = self._alteration("avatar", "replace")

        with self._after_first_call(gate, "evaluate", alter):
            report = FinalReportService(provider, gate, job_service=service).generate(request, interval_seconds=0)

        self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)
        self.assertFalse(report.job_created)
        self.assertFalse(report.real_provider_called)
        # `approval_decision` reste la décision du Gate (APPROVED), qui ne
        # prouve jamais une exécution ; le résumé porte la raison du refus.
        self.assertEqual(report.approval_decision, D.APPROVED)
        self.assertIn("no longer matches the authorization at the final check", report.summary)
        # Aucun contrat fourni : aucun niveau d'activation n'a été évalué.
        self.assertEqual(report.activation_decision, ActivationDecision.NOT_EVALUATED)
        self.assertEqual(report.provider_activation_decision, ActivationDecision.NOT_EVALUATED)
        self.assertNothingWasConsumedOrWritten(provider, gate, request)

    def assertNotExecutedReport(self, report):
        self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)
        self.assertEqual(report.execution_state, "NOT_EXECUTED")
        self.assertFalse(report.succeeded)
        self.assertFalse(report.job_created)
        self.assertFalse(report.real_provider_called)
        self.assertIsNone(report.job_id)
        self.assertIsNone(report.job_status)
        self.assertEqual(report.output_urls, ())
        self.assertIsNone(report.quality_decision)

    def test_with_both_contracts_the_report_says_exactly_what_was_evaluated(self):
        """P2.21 et P2.26 fournis, refus au dernier contrôle : le contrat
        P2.21 a été inspecté et accepté (non consommé) ; la validation
        P2.26 n'a PAS eu lieu et ne doit jamais apparaître approuvée."""

        provider, gate, activation, provider_activation, service = self._contract_stack()
        request = self._request()
        rs_contract = activation.prepare_activation(request)
        pa_contract = provider_activation.prepare(request, rs_contract)
        alter = self._alteration("avatar", "replace")

        with self._after_first_call(activation, "inspect_activation", alter), \
                mock.patch.object(provider_activation, "validate", wraps=provider_activation.validate) as validate:
            report = FinalReportService(provider, gate, job_service=service).generate(
                request, interval_seconds=0,
                activation_contract=rs_contract, provider_activation_contract=pa_contract,
            )

        validate.assert_not_called()
        self.assertNotExecutedReport(report)
        self.assertEqual(report.approval_decision, D.APPROVED)
        self.assertEqual(report.activation_decision, ActivationDecision.APPROVED)
        self.assertEqual(report.activation_reasons, [])
        self.assertEqual(report.provider_activation_decision, ActivationDecision.NOT_EVALUATED)
        self.assertEqual(report.provider_activation_reasons, [])
        self.assertIn("activation APPROVED (not consumed)", report.summary)
        self.assertIn("final content check REFUSED before any provider activation validation", report.summary)
        self.assertIn("no longer matches the authorization at the final check", report.summary)
        self.assertIn("avatar_sha256", report.summary)
        self.assertNotIn("provider activation APPROVED", report.summary)
        self.assertNothingWasConsumedOrWritten(provider, gate, request)
        self.assertEqual(activation._consumed_activation_ids, set())
        self.assertEqual(provider_activation._consumed_activation_ids, set())

    def test_with_p2_21_contract_only_the_report_says_activation_approved(self):
        provider, gate, activation, provider_activation, service = self._contract_stack()
        request = self._request()
        rs_contract = activation.prepare_activation(request)
        alter = self._alteration("face", "delete")

        with self._after_first_call(activation, "inspect_activation", alter):
            report = FinalReportService(provider, gate, job_service=service).generate(
                request, interval_seconds=0, activation_contract=rs_contract,
            )

        self.assertNotExecutedReport(report)
        self.assertEqual(report.activation_decision, ActivationDecision.APPROVED)
        self.assertEqual(report.provider_activation_decision, ActivationDecision.NOT_EVALUATED)
        self.assertIn("face_reference_sha256 cannot be verified at the final check", report.summary)
        self.assertNothingWasConsumedOrWritten(provider, gate, request)
        self.assertEqual(activation._consumed_activation_ids, set())

    def test_refusal_by_p2_26_after_the_final_check_is_still_reported_as_a_p2_26_rejection(self):
        """Distinction conservée : une altération APRÈS le dernier contrôle,
        refusée par la validation P2.26, reste un rejet P2.26 (REJECTED),
        jamais confondu avec un refus du dernier contrôle."""

        provider, gate, activation, provider_activation, service = self._contract_stack()
        request = self._request()
        rs_contract = activation.prepare_activation(request)
        pa_contract = provider_activation.prepare(request, rs_contract)
        alter = self._alteration("avatar", "replace")

        with self._after_first_call(job_service_module, "_final_content_violations", alter):
            report = FinalReportService(provider, gate, job_service=service).generate(
                request, interval_seconds=0,
                activation_contract=rs_contract, provider_activation_contract=pa_contract,
            )

        self.assertNotExecutedReport(report)
        self.assertEqual(report.activation_decision, ActivationDecision.APPROVED)
        self.assertEqual(report.provider_activation_decision, ActivationDecision.REJECTED)
        self.assertTrue(report.provider_activation_reasons)
        self.assertNotIn("final content check REFUSED", report.summary)
        self.assertNothingWasConsumedOrWritten(provider, gate, request)
        self.assertEqual(activation._consumed_activation_ids, set())
        self.assertEqual(provider_activation._consumed_activation_ids, set())


# ----------------------------------------------------------------------
# 5. Ordre des étapes, Provider réel, garde Phase D
# ----------------------------------------------------------------------


def _execute_node() -> ast.FunctionDef:
    tree = ast.parse(SERVICE_FILE.read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "GenerationJobService":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "execute":
                    return item
    raise AssertionError("GenerationJobService.execute not found")


def _call_lines(root: ast.AST, dotted_name: str):
    return sorted(
        node.lineno for node in ast.walk(root)
        if isinstance(node, ast.Call) and ast.unparse(node.func) == dotted_name
    )


class FinalCheckPositionInExecute(unittest.TestCase):
    """Statique (AST) : lit le source du service, ne l'exécute pas."""

    def setUp(self):
        self.execute = _execute_node()
        self.lock_block = next(
            stmt for stmt in self.execute.body
            if isinstance(stmt, ast.With) and ast.unparse(stmt.items[0].context_expr).startswith("self.lock.acquire(")
        )

    def _single_line(self, dotted_name: str) -> int:
        lines = _call_lines(self.lock_block, dotted_name)
        self.assertEqual(len(lines), 1, f"{dotted_name} must be called exactly once inside the lock: {lines}")
        return lines[0]

    def test_final_check_is_inside_the_lock_after_non_mutating_validations_and_before_any_consumption(self):
        digests = self._single_line("authorization_content_digests")
        comparison = self._single_line("_final_content_violations")
        self.assertEqual(_call_lines(self.execute, "authorization_content_digests"), [digests])

        validations = (
            "self.gate.evaluate",
            "self.activation_service.inspect_activation",
        )
        # `provider_activation_service.validate()` consomme le contrat P2.26
        # dans le même appel que sa validation : c'est une consommation.
        consumptions = (
            "self.provider_activation_service.validate",
            "self.activation_service.consume",
            "self.gate.consume_authorization",
            "self.gate.in_flight",
            "self.provider.create_job",
            "self.gate.mark_executed",
        )
        for name in validations:
            with self.subTest(before=name):
                self.assertLess(self._single_line(name), digests)
        self.assertLess(digests, comparison)
        for name in consumptions:
            with self.subTest(after=name):
                self.assertLess(comparison, self._single_line(name))

    def test_create_job_receives_the_verified_digests_and_nothing_recomputed(self):
        create_job = next(
            node for node in ast.walk(self.lock_block)
            if isinstance(node, ast.Call) and ast.unparse(node.func) == "self.provider.create_job"
        )
        keywords = {keyword.arg: ast.unparse(keyword.value) for keyword in create_job.keywords if keyword.arg}
        self.assertEqual(keywords["avatar_sha256"], "verified_digests['avatar_sha256']")
        self.assertEqual(keywords["face_reference_sha256"], "verified_digests['face_reference_sha256']")
        assignments = [
            node for node in ast.walk(self.execute)
            if isinstance(node, ast.Assign) and any(ast.unparse(target) == "verified_digests" for target in node.targets)
        ]
        self.assertEqual(len(assignments), 1, "verified_digests must be assigned exactly once")
        self.assertEqual(ast.unparse(assignments[0].value), "authorization_content_digests(request)")

    def test_service_module_has_no_file_hashing_of_its_own(self):
        tree = ast.parse(SERVICE_FILE.read_text(encoding="utf-8-sig"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree) if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertNotIn("hashlib", imported)
        self.assertFalse(hasattr(job_service_module, "_sha256_of_file_or_none"))
        self.assertFalse(hasattr(job_service_module, "_face_reference_sha256_or_none"))
        opens = [
            node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and (ast.unparse(node.func) == "open" or ast.unparse(node.func).endswith(".open"))
        ]
        self.assertEqual(opens, [], "the service must not open any file itself")
        self.assertIs(job_service_module.authorization_content_digests, authorization_content_digests)


class RealProviderAndPhaseDGuardAreUnchanged(_Sandbox):
    def _real_chain(self):
        client = _fake_client()
        provider, gate, service = self._gate_chain(
            provider=HiggsfieldProvider(client=client),
            identity_lock=ReleaseCandidateIdentityLock(C),
            max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST,
        )
        return client, provider, gate, service

    def test_exact_real_provider_still_refuses_unconditionally(self):
        client, provider, gate, service = self._real_chain()
        request = self._request()

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            service.execute(request, interval_seconds=0)

        client.create_job.assert_not_called()
        self.assertFalse(gate.is_already_executed(request.request_id))
        self.assertFalse(gate.executed_request_store.is_unknown(request.request_id))

    def test_real_provider_path_with_altered_content_is_refused_before_consumption(self):
        client, provider, gate, service = self._real_chain()
        request = self._request()
        alter = self._alteration("avatar", "replace")

        with self._after_first_call(gate, "evaluate", alter):
            with self.assertRaises(GenerationJobContentChangedError):
                service.execute(request, interval_seconds=0)

        client.create_job.assert_not_called()
        self.assertFalse(gate.is_authorization_consumed(request.real_generation_authorization.authorization_id))
        self.assertFalse(self.state_dir.exists() and any(self.state_dir.glob("*")))

    def test_unsafe_provider_is_still_refused_before_anything_else(self):
        class _MockSubclass(MockHiggsfieldProvider):
            pass

        provider = _MockSubclass(cost_per_job=67.5, available_credits=1000.0)
        _, gate, _ = self._gate_chain()
        service = GenerationJobService(provider, gate, lock=FileCriticalSectionLock(self.lock_dir))
        request = self._request()
        self.avatar.write_bytes(b"altered before execute")

        with mock.patch.object(job_service_module, "authorization_content_digests") as digests:
            with self.assertRaises(GenerationJobProviderNotAllowedError):
                service.execute(request, interval_seconds=0)

        digests.assert_not_called()
        self.assertEqual(provider._jobs, {})
        self.assertFalse(self.state_dir.exists() and any(self.state_dir.glob("*")))


if __name__ == "__main__":
    unittest.main()
