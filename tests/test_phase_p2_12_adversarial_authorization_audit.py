"""
Tests — Phase P2.12 : ADVERSARIAL AUTHORIZATION & SAFETY AUDIT.

Audit adversarial du verrou d'autorisation humaine introduit en P2.11
(RealGenerationAuthorization). Chaque classe de test ci-dessous
correspond à un scénario d'attaque numéroté A-Q de l'énoncé P2.12 et
tente ACTIVEMENT de faire échouer le Gate vers un APPROVED illégitime
ou un create_job() non autorisé.

Aucune génération réelle : tous les scénarios utilisent
MockHiggsfieldProvider ou un HiggsfieldProvider réel avec un client
factice (MagicMock, zéro subprocess/réseau) — jamais le vrai CLI.
"""

import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from tests.authorization_content_helpers import bind_request, content_media
from agents.executed_request_store import InMemoryExecutedRequestStore
from agents.generation_job_service import GenerationJobExecutionError, GenerationJobService
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider


def _request(**overrides) -> GenerationRequest:
    defaults = dict(
        **content_media(),
        request_id="005",
        job_type="seedance_2_0",
        prompt="prompt de test",
        duration=5,
        resolution="720p",
        aspect_ratio="9:16",
        approved=True,
    )
    defaults.update(overrides)
    return bind_request(GenerationRequest(**defaults))


def _valid_auth(request_id="005") -> RealGenerationAuthorization:
    return RealGenerationAuthorization(request_id=request_id, authorized_by_human=True)


class TestA_ApprovedTrueWithoutAuthorization(unittest.TestCase):
    """Attaque A — approved=True + budget suffisant, SANS autorisation."""

    def test_gate_never_approves(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(real_generation_authorization=None))

        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)

    def test_jobservice_never_creates_job(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)
        service = GenerationJobService(provider, gate)

        with self.assertRaises(GenerationJobExecutionError):
            service.execute(_request(real_generation_authorization=None))

        self.assertEqual(len(provider._jobs), 0)


class TestB_NoDangerousDefaultAnywhere(unittest.TestCase):
    """Attaque B — recherche d'une valeur par défaut dangereuse dans les signatures."""

    def test_generation_request_default_is_none(self):
        import inspect

        sig = inspect.signature(GenerationRequest.__init__)
        default = sig.parameters["real_generation_authorization"].default
        self.assertIsNone(default)

    def test_approved_defaults_to_false_everywhere_it_appears(self):
        import inspect

        from agents.video_agent import VideoAgent
        from agents.task_manager import TaskManager
        from director import AIDirector

        targets = [
            (GenerationRequest.__init__, "approved"),
            (VideoAgent.build_request, "approved"),
            (VideoAgent.run, "approved"),
            (AIDirector.run_video_mission, "approved"),
            (TaskManager.process, "approved"),
            (TaskManager.process_next_pending, "approved"),
        ]
        for func, param_name in targets:
            with self.subTest(func=func.__qualname__):
                sig = inspect.signature(func)
                self.assertFalse(sig.parameters[param_name].default)

    def test_real_generation_authorization_defaults_to_none_everywhere_it_appears(self):
        import inspect

        from agents.video_agent import VideoAgent
        from agents.task_manager import TaskManager
        from director import AIDirector

        targets = [
            VideoAgent.build_request,
            VideoAgent.run,
            AIDirector.run_video_mission,
            TaskManager.process,
            TaskManager.process_next_pending,
        ]
        for func in targets:
            with self.subTest(func=func.__qualname__):
                sig = inspect.signature(func)
                self.assertIsNone(
                    sig.parameters["real_generation_authorization"].default
                )

    def test_authorized_by_human_has_no_default_at_all(self):
        # Champ OBLIGATOIRE : aucune construction de
        # RealGenerationAuthorization ne peut omettre authorized_by_human.
        import inspect

        sig = inspect.signature(RealGenerationAuthorization.__init__)
        self.assertEqual(
            sig.parameters["authorized_by_human"].default, inspect.Parameter.empty
        )
        with self.assertRaises(TypeError):
            RealGenerationAuthorization(request_id="005")  # manque authorized_by_human


class TestC_AuthorizationForAnotherRequest(unittest.TestCase):
    """Attaque C — autorisation valide pour A, injectée dans B."""

    def test_cross_request_authorization_never_approves(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        auth_for_a = _valid_auth(request_id="request-A")
        request_b = _request(request_id="request-B", real_generation_authorization=auth_for_a)

        result = gate.evaluate(request_b)

        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)

    def test_cross_request_authorization_never_creates_job(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)
        service = GenerationJobService(provider, gate)

        auth_for_a = _valid_auth(request_id="request-A")
        request_b = _request(request_id="request-B", real_generation_authorization=auth_for_a)

        with self.assertRaises(GenerationJobExecutionError):
            service.execute(request_b)

        self.assertEqual(len(provider._jobs), 0)


class TestD_NoExpirationInventedNoImplicitReuse(unittest.TestCase):
    """
    Attaque D — une autorisation ne peut jamais être récupérée
    automatiquement pour une NOUVELLE requête qui n'en porte pas
    elle-même une. Phase B : `authorized_at` est désormais vérifié par
    le Gate (expiration, cf. tests/test_phase_b_authorization_expiry.py).
    """

    def test_invalid_authorized_at_is_refused_by_the_gate(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        garbage_timestamp_auth = RealGenerationAuthorization(
            request_id="005", authorized_by_human=True, authorized_at="not-a-timestamp"
        )
        result = gate.evaluate(_request(real_generation_authorization=garbage_timestamp_auth))

        # Phase B : un horodatage invalide n'est plus une simple
        # métadonnée -- l'autorisation est refusée, jamais APPROVED.
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)

    def test_a_fresh_request_without_its_own_authorization_never_inherits_a_prior_one(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        first = gate.evaluate(_request(real_generation_authorization=_valid_auth()))
        self.assertEqual(first.decision, GenerationApprovalDecision.APPROVED)

        # Même request_id, MAIS un nouvel objet GenerationRequest SANS
        # autorisation -- le Gate ne doit rien "se souvenir" de l'appel
        # précédent (aucun cache par request_id avant exécution).
        second = gate.evaluate(_request(real_generation_authorization=None))
        self.assertNotEqual(second.decision, GenerationApprovalDecision.APPROVED)


class TestE_Replay(unittest.TestCase):
    """Attaque E — autorisée, exécutée, puis rejouée avec la MÊME autorisation."""

    def test_second_execute_with_same_authorization_is_refused(self):
        provider = MockHiggsfieldProvider(
            cost_per_job=10.0, available_credits=100.0, succeed_after_polls=1
        )
        gate = GenerationApprovalGate(provider)
        service = GenerationJobService(provider, gate)

        auth = _valid_auth()
        service.execute(_request(real_generation_authorization=auth), interval_seconds=0)
        self.assertEqual(len(provider._jobs), 1)

        with self.assertRaises(GenerationJobExecutionError) as ctx:
            service.execute(_request(real_generation_authorization=auth), interval_seconds=0)

        self.assertIn("ALREADY_EXECUTED", str(ctx.exception))
        self.assertEqual(len(provider._jobs), 1)  # Toujours 1, pas 2.


class TestF_NewAuthorizationAfterExecutionStillBlocked(unittest.TestCase):
    """Attaque F — nouvelle autorisation (nouvel authorization_id) après exécution."""

    def test_brand_new_authorization_does_not_unlock_a_replay(self):
        provider = MockHiggsfieldProvider(
            cost_per_job=10.0, available_credits=100.0, succeed_after_polls=1
        )
        gate = GenerationApprovalGate(provider)
        service = GenerationJobService(provider, gate)

        first_auth = _valid_auth()
        service.execute(_request(real_generation_authorization=first_auth), interval_seconds=0)

        second_auth = _valid_auth()  # authorization_id DIFFÉRENT (uuid4 frais)
        self.assertNotEqual(first_auth.authorization_id, second_auth.authorization_id)

        result = gate.evaluate(_request(real_generation_authorization=second_auth))

        self.assertEqual(result.decision, GenerationApprovalDecision.ALREADY_EXECUTED)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)
        self.assertEqual(len(provider._jobs), 1)


class TestG_InsufficientBudgetWithValidAuthorization(unittest.TestCase):
    """Attaque G — autorisation valide + approved=True, mais budget insuffisant."""

    def test_blocked_regardless_of_authorization(self):
        provider = MockHiggsfieldProvider(cost_per_job=50.0, available_credits=1.41)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(real_generation_authorization=_valid_auth()))

        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)


class TestH_BalanceDegradesAfterAuthorization(unittest.TestCase):
    """Attaque H — solde suffisant au 1er evaluate(), insuffisant au 2e."""

    def test_second_evaluation_blocks_on_fresh_balance(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)
        auth = _valid_auth()

        first = gate.evaluate(_request(real_generation_authorization=auth))
        self.assertEqual(first.decision, GenerationApprovalDecision.APPROVED)

        provider._available_credits = 0.0  # Le solde "chute" avant l'exécution.

        second = gate.evaluate(_request(real_generation_authorization=auth))
        self.assertEqual(second.decision, GenerationApprovalDecision.BLOCKED)


class TestI_CostIncreasesAfterAuthorization(unittest.TestCase):
    """Attaque I — coût compatible au 1er evaluate(), supérieur au budget au 2e."""

    def test_second_evaluation_blocks_on_fresh_cost(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)
        auth = _valid_auth()

        first = gate.evaluate(_request(real_generation_authorization=auth))
        self.assertEqual(first.decision, GenerationApprovalDecision.APPROVED)

        provider._cost_per_job = 1000.0  # Le coût "augmente" avant l'exécution.

        second = gate.evaluate(_request(real_generation_authorization=auth))
        self.assertEqual(second.decision, GenerationApprovalDecision.BLOCKED)


class TestJ_NoCacheOfAnyPriorDecision(unittest.TestCase):
    """Attaque J — le Gate ne doit stocker AUCUNE décision/coût/solde/autorisation réutilisable."""

    def test_gate_internal_state_holds_only_the_replay_set(self):
        # Phase P2.15 : `_executed_request_ids` (un set[str] direct) a
        # été remplacé par `executed_request_store` (un objet
        # InMemoryExecutedRequestStore par défaut, cf.
        # agents/executed_request_store.py) pour permettre la
        # persistance sur le chemin de production réel -- l'invariant
        # vérifié ici reste le même : AUCUN état de
        # décision/coût/solde/autorisation n'est jamais mis en cache,
        # seul le FAIT qu'un request_id a été exécuté peut l'être.
        #
        # Phase P2.18 : `identity_lock` (défaut `None` ici, cf.
        # agents/release_candidate_identity_lock.py) est un attribut
        # supplémentaire, mais c'est une simple RÉFÉRENCE à un
        # contrat immuable injecté par l'appelant -- jamais une
        # décision/coût/solde/autorisation mise en cache par le Gate
        # lui-même, donc conforme au même invariant.
        #
        # Phase B : `_clock` est une fonction d'horloge sans état,
        # relue à chaque évaluation pour l'expiration de
        # `authorized_at` -- jamais une valeur mise en cache.
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        gate.evaluate(_request(real_generation_authorization=_valid_auth()))

        attribute_names = set(vars(gate).keys())
        self.assertEqual(
            attribute_names,
            {"provider", "cost_service", "executed_request_store", "identity_lock", "_clock"},
        )
        self.assertTrue(callable(gate._clock))

        store = gate.executed_request_store
        self.assertIsInstance(store, InMemoryExecutedRequestStore)
        # Le store par défaut ne contient qu'un ensemble d'IDs — pas
        # de décision/coût/solde/autorisation.
        for item in store._executed_request_ids:
            self.assertIsInstance(item, str)

    def test_evaluate_called_twice_recomputes_cost_and_balance_each_time(self):
        provider = MagicMock(wraps=MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0))
        gate = GenerationApprovalGate(provider)
        auth = _valid_auth()

        gate.evaluate(_request(real_generation_authorization=auth))
        gate.evaluate(_request(real_generation_authorization=auth))

        self.assertEqual(provider.estimate_cost.call_count, 2)
        self.assertEqual(provider.get_account_balance.call_count, 2)


class TestK_JobServiceCalledDirectlyBypassingDirector(unittest.TestCase):
    """Attaque K — GenerationJobService.execute() appelé directement, sans Director/TaskManager."""

    def test_no_create_job_without_authorization_even_called_directly(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)
        service = GenerationJobService(provider, gate)

        request = _request(approved=True, real_generation_authorization=None)

        with self.assertRaises(GenerationJobExecutionError):
            service.execute(request)

        self.assertEqual(len(provider._jobs), 0)


class TestL_DirectRealProviderCall(unittest.TestCase):
    """Attaque L — appel direct au (vrai) Provider, aucun réseau réel (client factice)."""

    def test_real_create_job_always_raises_regardless_of_authorization_existing(self):
        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)

        # Une autorisation valide existe dans le scope -- mais
        # HiggsfieldProvider.create_job() ne prend même pas de
        # GenerationRequest/autorisation en paramètre : il est
        # protégé INDÉPENDAMMENT du Gate (défense en profondeur).
        _unused_auth = _valid_auth()

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(job_type="seedance_2_0", prompt="prompt de test")

        fake_client.create_job.assert_not_called()


class TestM_MutationProbeGateWouldBeCaughtIfBroken(unittest.TestCase):
    """
    Attaque M — démontre que les tests A/C/G ci-dessus ont un réel
    pouvoir discriminant : si le verrou d'autorisation humaine était
    accidentellement cassé (patch en mémoire uniquement, restauré
    immédiatement, aucun fichier modifié), un APPROVED illégitime
    deviendrait effectivement détectable/reproductible -- preuve que
    ce n'est PAS le cas aujourd'hui.
    """

    def test_removing_the_human_authorization_check_would_produce_a_false_approved(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        original_method = GenerationApprovalGate._human_authorization_reasons
        try:
            # Simule EN MÉMOIRE, pour la durée du test seulement, un
            # Gate régressé qui ne vérifierait plus l'autorisation.
            GenerationApprovalGate._human_authorization_reasons = lambda self, request: []

            broken_result = gate.evaluate(_request(real_generation_authorization=None))
            self.assertEqual(broken_result.decision, GenerationApprovalDecision.APPROVED)
        finally:
            GenerationApprovalGate._human_authorization_reasons = original_method

        # Une fois restauré : le même scénario redevient bloqué --
        # confirme que le code RÉEL (non patché) est sûr.
        restored_result = gate.evaluate(_request(real_generation_authorization=None))
        self.assertNotEqual(restored_result.decision, GenerationApprovalDecision.APPROVED)


class TestN_RequestManipulation(unittest.TestCase):
    """Attaque N — manipulations diverses de l'objet d'autorisation."""

    def test_empty_request_id_in_authorization_never_matches(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        empty_auth = RealGenerationAuthorization(request_id="", authorized_by_human=True)
        result = gate.evaluate(_request(request_id="005", real_generation_authorization=empty_auth))

        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)

    def test_authorized_by_human_false_never_approves(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        auth = RealGenerationAuthorization(request_id="005", authorized_by_human=False)
        result = gate.evaluate(_request(real_generation_authorization=auth))

        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)

    def test_truthy_non_bool_authorized_by_human_is_rejected(self):
        # "is True" littéral : un entier 1 (truthy mais pas `True`)
        # ne doit PAS être accepté comme autorisation valide.
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        auth = RealGenerationAuthorization(request_id="005", authorized_by_human=1)
        result = gate.evaluate(_request(real_generation_authorization=auth))

        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)

    def test_duplicate_authorization_id_across_two_legitimate_requests_is_harmless(self):
        # authorization_id est un champ METADATA, jamais utilisé par
        # la décision de sécurité (seuls request_id +
        # authorized_by_human comptent) : le dupliquer entre deux
        # autorisations chacune correctement liée à SA PROPRE requête
        # ne doit rien changer -- ni les autoriser ni les bloquer
        # anormalement.
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        shared_id = "duplicated-authorization-id"
        auth_a = RealGenerationAuthorization(
            request_id="request-A", authorized_by_human=True, authorization_id=shared_id
        )
        auth_b = RealGenerationAuthorization(
            request_id="request-B", authorized_by_human=True, authorization_id=shared_id
        )

        result_a = gate.evaluate(_request(request_id="request-A", real_generation_authorization=auth_a))
        result_b = gate.evaluate(_request(request_id="request-B", real_generation_authorization=auth_b))

        self.assertEqual(result_a.decision, GenerationApprovalDecision.APPROVED)
        self.assertEqual(result_b.decision, GenerationApprovalDecision.APPROVED)

        # Mais A ne doit toujours PAS pouvoir utiliser l'autorisation de B et vice-versa.
        cross_result = gate.evaluate(
            _request(request_id="request-A", real_generation_authorization=auth_b)
        )
        self.assertNotEqual(cross_result.decision, GenerationApprovalDecision.APPROVED)

    def test_duck_typed_lookalike_object_is_rejected(self):
        # Objet "falsifié" imitant les champs mais n'héritant PAS de
        # la vraie classe -- doit échouer à la vérification isinstance().
        class _FakeAuthorization:
            def __init__(self, request_id, authorized_by_human):
                self.request_id = request_id
                self.authorized_by_human = authorized_by_human

        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        fake = _FakeAuthorization(request_id="005", authorized_by_human=True)
        result = gate.evaluate(_request(real_generation_authorization=fake))

        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)

    def test_authorization_object_is_frozen_cannot_be_mutated_after_construction(self):
        auth = _valid_auth(request_id="005")
        with self.assertRaises(FrozenInstanceError):
            auth.request_id = "tampered-request-id"


class TestO_NoPersistenceEnvOrCacheSource(unittest.TestCase):
    """
    Attaque O — recherche structurelle : aucune autorisation ne peut
    être chargée depuis un fichier, l'environnement, ou une variable
    globale.
    """

    def test_generation_approval_gate_module_touches_no_filesystem_or_env(self):
        import agents.generation_approval_gate as module

        source = Path(module.__file__).read_text(encoding="utf-8")

        for forbidden in ("open(", "os.environ", "json.load", "yaml.", "pickle."):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_no_module_level_container_holds_any_authorization_instance(self):
        import agents.generation_approval_gate as module

        # Recherche précise : aucun conteneur au niveau module (quel
        # que soit son nom) ne doit contenir une instance de
        # RealGenerationAuthorization -- ce serait la signature d'un
        # registre/cache global permettant une réutilisation
        # implicite. Les constantes non liées à l'autorisation (ex.
        # CONFIRMED_DURATIONS_BY_MODEL) sont explicitement HORS scope
        # de cette vérification.
        def _contains_authorization(value, seen=None) -> bool:
            if seen is None:
                seen = set()
            if id(value) in seen:
                return False
            seen.add(id(value))

            if isinstance(value, RealGenerationAuthorization):
                return True
            if isinstance(value, dict):
                return any(
                    _contains_authorization(v, seen) for v in value.values()
                )
            if isinstance(value, (list, tuple, set, frozenset)):
                return any(_contains_authorization(v, seen) for v in value)
            return False

        for name, value in vars(module).items():
            if name.startswith("__"):
                continue
            with self.subTest(name=name):
                self.assertFalse(
                    _contains_authorization(value),
                    f"Module-level attribute '{name}' holds a "
                    f"RealGenerationAuthorization instance.",
                )


class TestP_DryRunNeverCreatesAuthorization(unittest.TestCase):
    """Attaque P — un dry-run ne crée/ne réutilise jamais une autorisation humaine."""

    def test_prompt_assembly_and_asset_preparation_never_reference_authorization(self):
        import agents.prompt_assembly_system as prompt_module
        import agents.asset_preparation_system as asset_module
        import agents.cost_engine as cost_engine_module
        import agents.production_gate as production_gate_module

        for module in (
            prompt_module,
            asset_module,
            cost_engine_module,
            production_gate_module,
        ):
            with self.subTest(module=module.__name__):
                source = Path(module.__file__).read_text(encoding="utf-8")
                self.assertNotIn("RealGenerationAuthorization", source)

    def test_a_dry_run_style_request_without_authorization_never_approves(self):
        # `approved=False` (posture par défaut d'un dry-run) : même
        # avec budget confortable, jamais APPROVED, et a fortiori
        # jamais de fabrication d'autorisation.
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(_request(approved=False, real_generation_authorization=None))

        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)
        self.assertIsNone(_request(approved=False).real_generation_authorization)


if __name__ == "__main__":
    unittest.main()
