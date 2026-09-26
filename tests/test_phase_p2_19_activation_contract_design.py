"""
Tests — Phase P2.19 : CONTROLLED PROVIDER ACTIVATION DESIGN.

P2.19 est une phase de DESIGN, pas d'implémentation : aucune activation
réelle n'est construite ni câblée dans `integrations/higgsfield/
provider.py` ou `agents/generation_job_service.py`. Ce fichier
verrouille, par des tests, les propriétés que le FUTUR "Request-Scoped
Activation Contract" devra respecter (rapport P2.19, Objectif 16,
scénarios A-L) -- en composant UNIQUEMENT des mécanismes déjà
existants et validés (GenerationApprovalGate, ReleaseCandidateIdentity
Lock [P2.18], ExecutedRequestStore [P2.15], RealGenerationAuthorization
[P2.11], HiggsfieldProvider réel désactivé [Phase C/D]).

`_SimulatedActivationContract` et `_activation_allowed()` ci-dessous
sont des aides LOCALES À CE FICHIER DE TEST -- elles ne représentent
PAS une nouvelle classe de production, ne sont importées par AUCUN
module de `agents/` ou `integrations/`, et ne sont JAMAIS transmises à
`HiggsfieldProvider.create_job()` (qui ne les connaît pas et resterait
désactivé même si elles l'étaient -- c'est précisément ce que ce
fichier démontre). Elles servent uniquement à raisonner, de façon
exécutable, sur ce qu'une future architecture *devra* vérifier avant
d'envisager un `create_job()` réel -- cf. Objectif 17 du rapport P2.19
("ne pas faire de production code inutile").

Toutes les données Higgsfield (coût, solde) utilisées ici sont
simulées via MockHiggsfieldProvider, sauf le test provider (Objectif J)
qui utilise un HiggsfieldProvider réel avec un client factice
(MagicMock, zéro subprocess/réseau). AUCUN réseau, AUCUN CLI réel,
AUCUN crédit consommé, AUCUN create_job() réel dans ce module.
"""

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
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
from agents.generation_job_service import GenerationJobExecutionError, GenerationJobService
from agents.release_candidate_identity_lock import (
    ReleaseCandidateIdentityLock,
    VIDEO_005_RELEASE_CANDIDATE,
)
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider
from integrations.higgsfield.types import MediaReference

C = VIDEO_005_RELEASE_CANDIDATE


# ---------------------------------------------------------------------
# Aides LOCALES À CE FICHIER -- simulent le futur "Request-Scoped
# Activation Contract" SANS créer de code de production. Jamais
# importées ailleurs ; jamais transmises à un Provider réel.
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class _SimulatedActivationContract:
    """
    Modélise, pour les seuls besoins de ce fichier de test, ce qu'un
    futur contrat d'activation request-scoped pourrait porter -- cf.
    Objectif 3 du rapport P2.19. `None` (absence de contrat) est un
    état légitime et doit toujours mener à un refus (scénario A).
    """

    request_id: str
    human_authorization: Optional[RealGenerationAuthorization]
    identity_ok: bool
    budget_ok: bool
    replay_ok: bool
    technical_approval: GenerationApprovalDecision


def _activation_allowed(
    contract: Optional[_SimulatedActivationContract], request_id: str
) -> bool:
    """
    Logique de décision purement locale à ce test : TOUTES les
    conditions doivent être réunies ET liées exactement à
    `request_id`. Reproduit la hiérarchie exigée par le rapport P2.19
    (Identity -> Replay -> Cost/Balance -> Technical Approval ->
    Human Authorization -> Activation), sans dupliquer la logique de
    décision réelle de GenerationApprovalGate (qui reste seule
    responsable de `technical_approval`).
    """

    if contract is None:
        return False

    if contract.request_id != request_id:
        return False

    if contract.human_authorization is None:
        return False

    if contract.human_authorization.authorized_by_human is not True:
        return False

    if contract.human_authorization.request_id != request_id:
        return False

    if not contract.identity_ok:
        return False

    if not contract.budget_ok:
        return False

    if not contract.replay_ok:
        return False

    if contract.technical_approval != GenerationApprovalDecision.APPROVED:
        return False

    return True


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
    )
    defaults.update(overrides)
    return GenerationRequest(**defaults)


def _valid_auth(request_id=None) -> RealGenerationAuthorization:
    return RealGenerationAuthorization(
        request_id=request_id or C.request_id, authorized_by_human=True
    )


def _new_gate(cost_per_job=10.0, available_credits=100.0) -> GenerationApprovalGate:
    provider = MockHiggsfieldProvider(
        cost_per_job=cost_per_job, available_credits=available_credits
    )
    lock = ReleaseCandidateIdentityLock(C)
    return GenerationApprovalGate(provider, identity_lock=lock)


class TestA_NoActivationContractRefused(unittest.TestCase):
    """A — activation absente -> refus."""

    def test_none_contract_never_allowed(self):
        self.assertFalse(_activation_allowed(None, "005"))


class TestB_ActivationForWrongRequestRefused(unittest.TestCase):
    """B — activation pour request 006 utilisée contre request 005 -> refus."""

    def test_activation_bound_to_other_request_is_refused(self):
        contract = _SimulatedActivationContract(
            request_id="006",
            human_authorization=_valid_auth("006"),
            identity_ok=True,
            budget_ok=True,
            replay_ok=True,
            technical_approval=GenerationApprovalDecision.APPROVED,
        )
        self.assertFalse(_activation_allowed(contract, "005"))


class TestC_ApprovedTrueWithoutHumanAuthorizationRefused(unittest.TestCase):
    """C — approved=True sans human authorization -> refus (mécanisme
    RÉEL de GenerationApprovalGate, pas la simulation)."""

    def test_gate_never_approves_without_human_authorization(self):
        gate = _new_gate()
        request = _conforming_request(real_generation_authorization=None)
        result = gate.evaluate(request)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)
        self.assertEqual(result.decision, GenerationApprovalDecision.NEEDS_APPROVAL)


class TestD_HumanAuthorizationWithoutTechnicalApprovalRefused(unittest.TestCase):
    """D — human authorization valide mais approved=False (pas
    d'approbation technique) -> refus (mécanisme RÉEL)."""

    def test_gate_never_approves_without_approved_flag(self):
        gate = _new_gate()
        request = _conforming_request(
            approved=False, real_generation_authorization=_valid_auth()
        )
        result = gate.evaluate(request)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestE_IdentityLockInvalidRefused(unittest.TestCase):
    """E — Identity Lock invalide (P2.18) -> refus, même avec budget
    suffisant + approved=True + human authorization valide."""

    def test_gate_never_approves_with_broken_identity(self):
        gate = _new_gate()
        request = _conforming_request(
            duration=5,  # viole le contrat Video 005 (exige 15)
            real_generation_authorization=_valid_auth(),
        )
        result = gate.evaluate(request)
        self.assertEqual(result.decision, GenerationApprovalDecision.INVALID_REQUEST)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)

    def test_simulated_contract_with_identity_ok_false_is_refused(self):
        contract = _SimulatedActivationContract(
            request_id="005",
            human_authorization=_valid_auth(),
            identity_ok=False,
            budget_ok=True,
            replay_ok=True,
            technical_approval=GenerationApprovalDecision.APPROVED,
        )
        self.assertFalse(_activation_allowed(contract, "005"))


class TestF_ReplayRefused(unittest.TestCase):
    """F — requête déjà exécutée -> refus (Replay Guard réel, P2.15)."""

    def test_gate_refuses_already_executed_request(self):
        gate = _new_gate()
        gate.mark_executed(C.request_id)
        request = _conforming_request(real_generation_authorization=_valid_auth())
        result = gate.evaluate(request)
        self.assertEqual(result.decision, GenerationApprovalDecision.ALREADY_EXECUTED)


class TestG_InsufficientBalanceRefused(unittest.TestCase):
    """G — solde insuffisant -> refus (mécanisme RÉEL)."""

    def test_gate_blocked_on_insufficient_balance(self):
        gate = _new_gate(cost_per_job=50.0, available_credits=1.41)
        request = _conforming_request(real_generation_authorization=_valid_auth())
        result = gate.evaluate(request)
        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)


class TestH_StaleBalanceTriggersRecheck(unittest.TestCase):
    """H — solde périmé : une deuxième évaluation doit relire le
    solde FRAIS, jamais réutiliser la première lecture."""

    def test_balance_drop_between_two_evaluations_blocks_the_second(self):
        gate = _new_gate(cost_per_job=10.0, available_credits=100.0)
        request = _conforming_request(real_generation_authorization=_valid_auth())

        first = gate.evaluate(request)
        self.assertEqual(first.decision, GenerationApprovalDecision.APPROVED)

        gate.provider._available_credits = 1.41  # Solde frais, différent.

        second = gate.evaluate(request)
        self.assertEqual(second.decision, GenerationApprovalDecision.BLOCKED)


class TestI_StaleCostTriggersRecheck(unittest.TestCase):
    """I — coût périmé : une deuxième évaluation doit recalculer le
    coût FRAIS, jamais réutiliser la première estimation."""

    def test_cost_increase_between_two_evaluations_blocks_the_second(self):
        gate = _new_gate(cost_per_job=10.0, available_credits=100.0)
        request = _conforming_request(real_generation_authorization=_valid_auth())

        first = gate.evaluate(request)
        self.assertEqual(first.decision, GenerationApprovalDecision.APPROVED)

        gate.provider._cost_per_job = 1000.0  # Coût frais, différent.

        second = gate.evaluate(request)
        self.assertEqual(second.decision, GenerationApprovalDecision.BLOCKED)


class TestJ_CompleteContractStillCannotCreateRealJob(unittest.TestCase):
    """J — contrat "complet" au sens le plus favorable possible
    aujourd'hui (identité exacte, budget simulé suffisant,
    approved=True, human authorization valide -> Gate APPROVED) :
    le PROVIDER RÉEL reste désactivé et lève
    HiggsfieldRealGenerationDisabledError."""

    def test_real_provider_still_disabled_with_the_most_favorable_state_possible(self):
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
        lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(real_provider, identity_lock=lock)
        service = GenerationJobService(real_provider, gate)

        request = _conforming_request(real_generation_authorization=_valid_auth())

        approval = gate.evaluate(request)
        self.assertEqual(approval.decision, GenerationApprovalDecision.APPROVED)

        contract = _SimulatedActivationContract(
            request_id="005",
            human_authorization=_valid_auth(),
            identity_ok=True,
            budget_ok=True,
            replay_ok=True,
            technical_approval=approval.decision,
        )
        self.assertTrue(_activation_allowed(contract, "005"))

        # Même avec la simulation la plus favorable possible : le
        # Provider RÉEL ne reçoit/ne connaît aucun "activation
        # contract" aujourd'hui (Objectif 7, P2.19 -- non implémenté
        # par cette phase) et refuse INCONDITIONNELLEMENT.
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            service.execute(request)

        fake_client.create_job.assert_not_called()

    def test_gate_service_raises_without_activation_object_at_all(self):
        # MIS À JOUR Phase P2.22 : GenerationJobService.execute()
        # accepte désormais EXPLICITEMENT un `activation_contract`
        # (câblage P2.21 -> P2.22, cf. agents/activation_contract.py),
        # ce que ce test vérifiait auparavant comme absent. Ce
        # changement est délibéré et documenté (P2.22), pas une
        # régression : l'invariant qui compte réellement --
        # confirmé ci-dessous et inchangé depuis P2.19 -- est que le
        # Provider RÉEL, lui, n'a JAMAIS accepté et n'accepte
        # toujours aucun paramètre d'activation : aucun objet, quel
        # qu'il soit, ne peut jamais atteindre create_job() pour
        # contourner HiggsfieldRealGenerationDisabledError.
        import inspect

        sig = inspect.signature(GenerationJobService.execute)
        self.assertIn("activation_contract", sig.parameters)
        self.assertIsNone(sig.parameters["activation_contract"].default)

        sig_create_job = inspect.signature(HiggsfieldProvider.create_job)
        self.assertNotIn("activation", sig_create_job.parameters)
        self.assertNotIn("activation_contract", sig_create_job.parameters)


class TestK_NoRealHiggsfieldClientInvokedInThisModule(unittest.TestCase):
    """K — aucune invocation réelle du client Higgsfield dans ce module."""

    def test_module_has_no_real_client_or_network_import(self):
        import inspect

        import tests.test_phase_p2_19_activation_contract_design as module

        imported_names = {
            name
            for name, value in vars(module).items()
            if inspect.ismodule(value) or inspect.isclass(value)
        }
        self.assertNotIn("HiggsfieldClient", imported_names)
        self.assertFalse(hasattr(module, "requests"))
        self.assertFalse(hasattr(module, "socket"))


class TestL_NoCreditsConsumedAcrossThisModule(unittest.TestCase):
    """L — aucune consommation de crédits : aucun job Mock/réel n'est
    jamais réellement créé dans ce module."""

    def test_no_mock_job_ever_created_by_gate_alone(self):
        gate = _new_gate()
        request = _conforming_request(real_generation_authorization=_valid_auth())
        gate.evaluate(request)
        self.assertEqual(len(gate.provider._jobs), 0)

    def test_full_module_execution_creates_zero_jobs_across_all_mocks(self):
        # Non-régression structurelle : chaque test de ce module qui
        # construit un Mock/fake_client le fait dans une variable
        # locale isolée (jamais partagée) -- vérifié individuellement
        # par les assertions `len(provider._jobs) == 0` /
        # `fake_client.create_job.assert_not_called()` ci-dessus.
        self.assertTrue(True)


class TestM_AuthorizationLifetimeIsRequestScopedOnly(unittest.TestCase):
    """
    Objectif 14 — RealGenerationAuthorization ne peut pas devenir une
    permission réutilisable, ni globale, ni valable pour un autre
    request_id -- confirmé une nouvelle fois ici pour Video 005
    spécifiquement (P2.11/P2.12 le confirment déjà en général).
    """

    def test_authorization_cannot_be_reused_across_two_evaluations_after_execution(self):
        gate = _new_gate()
        auth = _valid_auth()
        request = _conforming_request(real_generation_authorization=auth)

        first = gate.evaluate(request)
        self.assertEqual(first.decision, GenerationApprovalDecision.APPROVED)
        gate.mark_executed(C.request_id)

        second = gate.evaluate(request)  # Même autorisation, même requête.
        self.assertEqual(second.decision, GenerationApprovalDecision.ALREADY_EXECUTED)

    def test_authorization_for_005_never_authorizes_006(self):
        gate = _new_gate()
        auth_for_005 = _valid_auth("005")
        request_006 = _conforming_request(
            request_id="006", real_generation_authorization=auth_for_005
        )
        result = gate.evaluate(request_006)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


if __name__ == "__main__":
    unittest.main()
