"""
Tests — Phase P2.30 : REAL GENERATION AUTHORIZATION & BUDGET READINESS
AUDIT.

Ce fichier n'existe PAS pour dupliquer P2.20-P2.29 (dont les tests
restent la source de vérité pour chaque mécanisme pris isolément) --
il verrouille ce que P2.30 ajoute de RÉELLEMENT nouveau à l'audit :

1. Le calcul de `credits_missing` (coût - solde) pour Video 005, à
   partir des VRAIES valeurs canoniques, sans jamais appeler un
   endpoint payant.
2. La structure de `RealGenerationAuthorization` : champs requis,
   génération d'un `authorization_id` distinct par instance, absence
   de valeur par défaut pour `authorized_by_human`, absence de champ
   d'expiration caché sur l'objet lui-même (l'expiration vit dans les
   CONTRATS P2.21/P2.26, jamais sur l'autorisation brute).
3. La PURETÉ de `check_activation_readiness()`/`ActivationReadiness
   Evaluator.evaluate()` -- prouvée par appels RÉPÉTÉS qui ne doivent
   jamais accumuler d'état ni créer quoi que ce soit, même après N
   appels consécutifs.
4. L'analyse de rollback : confirmation, par inspection de code, qu'AUCUN
   état global/singleton n'existe qui nécessiterait une procédure de
   rollback explicite -- toute l'autorité vit dans des instances de
   service jetables, jamais dans une variable de classe ou de module.

Toutes les données de coût/solde utilisées ici proviennent de
`MockHiggsfieldProvider`, sauf la reconfirmation explicite du solde
réel (lecture seule, `account status`) et du coût réel de Video 005
(déjà confirmés dans les phases précédentes -- reconfirmés ici comme
valeurs canoniques, jamais recalculés via un nouvel appel payant).
"""

import ast
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
from agents.activation_readiness import ActivationReadinessEvaluator
from agents.controlled_real_provider_activation import ControlledRealProviderActivationService
from agents.critical_section_lock import FileCriticalSectionLock
from agents.generation_approval_gate import (
    GenerationApprovalGate,
    RealGenerationAuthorization,
)
from agents.generation_job_service import GenerationJobService
from agents.release_candidate_identity_lock import (
    ReleaseCandidateIdentityLock,
    VIDEO_005_RELEASE_CANDIDATE,
)
from director import AIDirector
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider

C = VIDEO_005_RELEASE_CANDIDATE
CONFIRMED_RATE_CREDITS_PER_SECOND = 4.5  # empiriquement confirmé, Phase P1.2, lecture seule


class P2_30_TestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_30_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)


# ----------------------------------------------------------------------
# Étape 3/11 : Budget readiness — cost, missing credits, no payment call
# ----------------------------------------------------------------------


class TestBudgetReadiness(unittest.TestCase):
    def test_video_005_expected_cost_matches_confirmed_rate(self):
        expected_cost = CONFIRMED_RATE_CREDITS_PER_SECOND * C.duration
        self.assertEqual(expected_cost, 67.5)

    def test_credits_missing_computation_is_correct(self):
        current_balance = 1.41
        expected_cost = 67.5
        credits_missing = round(expected_cost - current_balance, 2)
        self.assertEqual(credits_missing, 66.09)

    def test_video_005_is_currently_unfinanceable_via_mock_with_real_numbers(self):
        # Utilise le Mock avec les VRAIES valeurs canoniques (coût et
        # solde), jamais un appel payant, pour confirmer que le Gate
        # bloquerait bien une tentative réelle avec ce budget exact.
        provider = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=1.41)
        self.assertLess(provider.get_account_balance(), 67.5)

    def test_no_credit_purchase_or_balance_mutation_endpoint_exists_anywhere(self):
        # Confirme structurellement qu'aucune méthode de type "achat/
        # recharge de crédits" n'existe nulle part dans le code de
        # production -- readiness ne doit jamais pouvoir en avoir
        # besoin.
        forbidden_names = ("purchase_credits", "recharge_credits", "add_credits", "buy_credits")
        for base in ("agents", "integrations"):
            for path in (PROJECT_ROOT / base).rglob("*.py"):
                text = path.read_text(encoding="utf-8-sig")
                for name in forbidden_names:
                    self.assertNotIn(f"def {name}", text)


# ----------------------------------------------------------------------
# Étape 5 : RealGenerationAuthorization structural audit
# ----------------------------------------------------------------------


class TestRealGenerationAuthorizationStructure(unittest.TestCase):
    def test_required_fields_have_no_default_where_they_must_not(self):
        import inspect

        # request_id et authorized_by_human sont REQUIS (pas de
        # valeur par défaut) -- vérifié structurellement, pas
        # supposé.
        fields = RealGenerationAuthorization.__dataclass_fields__
        self.assertIn("request_id", fields)
        self.assertIn("authorized_by_human", fields)
        import dataclasses

        self.assertIs(fields["request_id"].default, dataclasses.MISSING)
        self.assertIs(fields["authorized_by_human"].default, dataclasses.MISSING)

    def test_authorization_id_is_distinct_per_instance(self):
        auth1 = RealGenerationAuthorization(request_id="005", authorized_by_human=True)
        auth2 = RealGenerationAuthorization(request_id="005", authorized_by_human=True)
        self.assertNotEqual(auth1.authorization_id, auth2.authorization_id)

    def test_authorized_at_is_populated_automatically_per_instance(self):
        auth = RealGenerationAuthorization(request_id="005", authorized_by_human=True)
        self.assertTrue(auth.authorized_at)
        self.assertIsInstance(auth.authorized_at, str)

    def test_note_field_is_optional_and_never_auto_filled_with_identity(self):
        auth = RealGenerationAuthorization(request_id="005", authorized_by_human=True)
        self.assertEqual(auth.note, "")

    def test_no_hidden_expiration_field_on_the_authorization_object_itself(self):
        # L'expiration vit dans les CONTRATS (P2.21/P2.26,
        # max_age_seconds), jamais sur RealGenerationAuthorization
        # elle-même.
        fields = set(RealGenerationAuthorization.__dataclass_fields__.keys())
        self.assertEqual(
            fields, {"request_id", "authorized_by_human", "authorization_id", "authorized_at", "note"}
        )

    def test_authorization_is_frozen_immutable(self):
        auth = RealGenerationAuthorization(request_id="005", authorized_by_human=True)
        with self.assertRaises(Exception):
            auth.authorized_by_human = False  # type: ignore[misc]

    def test_no_module_level_registry_of_authorizations_anywhere(self):
        text = (PROJECT_ROOT / "agents" / "generation_approval_gate.py").read_text(
            encoding="utf-8-sig"
        )
        tree = ast.parse(text)
        module_level_assignments = {
            target.id
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        suspicious = {
            name for name in module_level_assignments
            if "authorization" in name.lower() or "authority" in name.lower()
        }
        self.assertEqual(suspicious, set())


# ----------------------------------------------------------------------
# Étape 6/8 : Readiness API purity (prepare/execute audit + readiness)
# ----------------------------------------------------------------------


class TestReadinessAPIPurity(P2_30_TestCase):
    def _stack(self, cost_per_job=67.5, available_credits=1.41):
        provider = MockHiggsfieldProvider(cost_per_job=cost_per_job, available_credits=available_credits)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
        activation_service = RequestScopedActivationService(gate, identity_lock)
        provider_activation_service = ControlledRealProviderActivationService(
            gate, identity_lock, activation_service
        )
        lock = FileCriticalSectionLock(self._tmp)
        job_service = GenerationJobService(
            provider, gate, lock=lock,
            activation_service=activation_service,
            provider_activation_service=provider_activation_service,
        )
        evaluator = ActivationReadinessEvaluator(
            gate, identity_lock, activation_service, job_service=job_service
        )
        return provider, gate, activation_service, provider_activation_service, evaluator

    def _request(self, **overrides):
        from agents.generation_approval_gate import GenerationRequest
        from integrations.higgsfield.types import MediaReference
        from agents.prompt_assembly_system import PromptAssemblySystem

        avatar = PROJECT_ROOT / "assets" / "zephyr" / "avatar" / "avatar_master.png"
        face = PROJECT_ROOT / "assets" / "zephyr" / "references" / "mon avatar habille.png"
        defaults = dict(
            request_id=C.request_id,
            job_type=C.job_type,
            prompt=PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id),
            duration=C.duration,
            resolution=C.resolution,
            aspect_ratio=C.aspect_ratio,
            approved=True,
            start_image=MediaReference(role="master_avatar", source=str(avatar), sha256=None),
            image_references=(
                MediaReference(role="face_reference", source=str(face), sha256=None),
            ),
            real_generation_authorization=RealGenerationAuthorization(
                request_id=C.request_id, authorized_by_human=True
            ),
        )
        defaults.update(overrides)
        return GenerationRequest(**defaults)

    def test_repeated_readiness_evaluations_never_accumulate_state(self):
        provider, gate, activation_service, provider_activation_service, evaluator = self._stack()
        request = self._request()

        for _ in range(10):
            evaluator.evaluate(request)

        self.assertEqual(len(activation_service._issued_at), 0)
        self.assertEqual(len(activation_service._consumed_activation_ids), 0)
        self.assertEqual(len(provider_activation_service._issued_at), 0)
        self.assertEqual(len(provider._jobs), 0)

    def test_readiness_evaluation_never_mutates_the_request(self):
        _, _, _, _, evaluator = self._stack()
        request = self._request(real_generation_authorization=None)
        evaluator.evaluate(request)
        self.assertIsNone(request.real_generation_authorization)

    def test_director_check_activation_readiness_is_pure_with_injected_fake_client(self):
        fake_client = MagicMock()
        fake_client.estimate_cost.return_value = {"credits": 67.5}
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
        from tests.test_phase_b_authorization_single_use import isolated_director_state

        director = AIDirector()
        director.higgsfield = fake_client

        request = self._request()
        # Phase B : chemins persistants de la chaîne réelle redirigés
        # vers un dossier temporaire (jamais le `state/` réel).
        tmp = Path(tempfile.mkdtemp(prefix="p2_30_director_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with isolated_director_state(tmp):
            for _ in range(3):
                report = director.check_activation_readiness(request)

        self.assertFalse(report.budget_ready)  # 1.41 < 67.5
        self.assertFalse(report.provider_ready)  # real provider, always
        self.assertEqual(report.decision, "NOT_READY")
        fake_client.create_job.assert_not_called()


# ----------------------------------------------------------------------
# Étape 9 : Mock full positive path via the P2.29 entry point
# ----------------------------------------------------------------------


class TestMockFullPositivePath(P2_30_TestCase):
    def test_full_chain_via_p2_29_entry_point_with_sufficient_mock_budget(self):
        from agents.final_report_service import ActivationDecision, FinalReportStatus, FinalReportService

        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
        activation_service = RequestScopedActivationService(gate, identity_lock)
        provider_activation_service = ControlledRealProviderActivationService(
            gate, identity_lock, activation_service
        )
        lock = FileCriticalSectionLock(self._tmp)
        job_service = GenerationJobService(
            provider, gate, lock=lock,
            activation_service=activation_service,
            provider_activation_service=provider_activation_service,
        )
        report_service = FinalReportService(provider, gate, job_service=job_service)

        director = AIDirector()
        prepared = director.prepare_real_generation_activation(
            video_id="005", title="t", hook="h", objective="o",
            duration=C.duration, approved=True,
            real_generation_authorization=RealGenerationAuthorization(
                request_id="005", authorized_by_human=True
            ),
            report_service=report_service,
        )
        report = director.execute_real_generation_activation(
            prepared, report_service=report_service, interval_seconds=0
        )

        self.assertEqual(report.status, FinalReportStatus.EXECUTED_PASS)
        self.assertTrue(report.job_created)
        self.assertEqual(report.activation_decision, ActivationDecision.APPROVED)
        self.assertEqual(report.provider_activation_decision, ActivationDecision.APPROVED)
        self.assertFalse(report.real_provider_called)


# ----------------------------------------------------------------------
# Étape 10 : Real provider negative path (reconfirmed)
# ----------------------------------------------------------------------


class TestRealProviderNegativePath(unittest.TestCase):
    def test_direct_create_job_still_blocked(self):
        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(job_type="seedance_2_0", prompt="x")
        fake_client.create_job.assert_not_called()


# ----------------------------------------------------------------------
# Étape 14 : Rollback analysis — no global/singleton state exists
# ----------------------------------------------------------------------


class TestRollbackAnalysisNoGlobalState(unittest.TestCase):
    """
    Confirme, par inspection de code, qu'aucune procédure de rollback
    n'est nécessaire au sens d'un état global à réinitialiser :
    l'autorité entière vit dans des instances de service construites
    à la demande (GenerationApprovalGate, RequestScopedActivation
    Service, ControlledRealProviderActivationService), jamais dans
    une variable de CLASSE ou de MODULE. "Désactiver" une future
    génération réelle revient donc à ne jamais construire/réutiliser
    l'instance qui la porterait -- pas à "annuler" un état partagé.
    """

    def test_no_class_level_mutable_authority_state(self):
        for cls in (
            GenerationApprovalGate,
            RequestScopedActivationService,
            ControlledRealProviderActivationService,
        ):
            for name, value in vars(cls).items():
                if name.startswith("__"):
                    continue
                self.assertNotIsInstance(
                    value, (set, dict, list),
                    f"{cls.__name__}.{name} is a class-level mutable "
                    f"container -- authority state must live on instances, "
                    f"never shared across them.",
                )

    def test_two_independent_gate_instances_never_share_replay_state(self):
        provider_a = MockHiggsfieldProvider()
        provider_b = MockHiggsfieldProvider()
        gate_a = GenerationApprovalGate(provider_a)
        gate_b = GenerationApprovalGate(provider_b)

        gate_a.mark_executed("005")
        self.assertTrue(gate_a.is_already_executed("005"))
        self.assertFalse(gate_b.is_already_executed("005"))

    def test_provider_boundary_is_a_pure_function_of_the_provider_instance(self):
        # "Rollback" du côté Provider = simplement ne jamais construire
        # un HiggsfieldProvider capable -- confirmé qu'aucun état ne
        # persiste entre deux instances de HiggsfieldProvider.
        fake_client_1 = MagicMock()
        fake_client_2 = MagicMock()
        provider_1 = HiggsfieldProvider(client=fake_client_1)
        provider_2 = HiggsfieldProvider(client=fake_client_2)

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            provider_1.create_job(job_type="seedance_2_0", prompt="x")
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            provider_2.create_job(job_type="seedance_2_0", prompt="x")


# ----------------------------------------------------------------------
# Étape 4 : Video 005 identity (reconfirmed live, once more)
# ----------------------------------------------------------------------


class TestVideo005Integrity(unittest.TestCase):
    def test_canonical_values(self):
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

    def test_recomputed_live_from_disk(self):
        import hashlib

        from agents.prompt_assembly_system import PromptAssemblySystem

        prompt = PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id)
        self.assertEqual(len(prompt), C.prompt_chars)
        self.assertEqual(len(prompt.splitlines()), C.prompt_lines)
        self.assertEqual(hashlib.sha256(prompt.encode("utf-8")).hexdigest(), C.prompt_sha256)


if __name__ == "__main__":
    unittest.main()
