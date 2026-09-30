"""
Tests — Phase P2.17 : PRODUCTION ACTIVATION CONTRACT & PRE-GENERATION
FINAL GATE.

Cette phase ne construit AUCUN nouveau mécanisme d'exécution : elle
VERROUILLE, par des tests, le contrat de conditions qui devront toutes
être réunies avant qu'une future phase dédiée puisse envisager
d'autoriser un `create_job()` réel. Toute la logique de décision
(coût, budget, autorisation humaine, replay guard, compatibilité
modèle) reste exclusivement dans GenerationApprovalGate/
GenerationCostService/ExecutedRequestStore (Phases F/G/P2.11/P2.15,
non modifiées) — ce module ne fait qu'assembler des scénarios contre
ces mécanismes existants, plus une petite fonction d'aide LOCALE
(_contract_violations) qui compare une requête à la Release Candidate
Video 005 gelée. Cette fonction n'est PAS câblée dans le pipeline réel
(agents/generation_approval_gate.py n'est pas modifié) : elle ne fait
que documenter, sous forme exécutable, l'écart actuel identifié en
Objectif 7 du rapport P2.17 (l'identité prompt/assets n'est aujourd'hui
vérifiée que par un test de non-régression — cf.
tests/test_phase_p2_11_human_authorization_guard.py::TestH — jamais par
le Gate lui-même au moment de l'évaluation).

Toutes les données Higgsfield (coût, solde) utilisées dans cette suite
automatisée sont simulées via MockHiggsfieldProvider — AUCUN réseau,
AUCUN CLI réel, AUCUN crédit consommé. La vérification READ-ONLY contre
le vrai compte (balance réelle = 1.41, coût frais réel = 67.5 pour
Video 005 exactement) a été effectuée séparément, hors suite
automatisée (cf. rapport P2.17), exactement comme pour les phases
précédentes (P2.9-P2.11).
"""

import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.asset_preparation_system import AssetPreparationSystem
from agents.executed_request_store import InMemoryExecutedRequestStore
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from tests.real_provider_path_fixtures import FIXTURE_MAX_COST_CREDITS_PER_REQUEST, fixture_identity_lock_for
from tests.authorization_content_helpers import (
    bind_request,
    content_media,
    video_005_authorization,
)
from agents.generation_job_service import GenerationJobExecutionError, GenerationJobService
from agents.planner import VideoPlanner
from agents.production_model import PRODUCTION_MODEL
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.video_agent import VideoAgent
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider


# ---------------------------------------------------------------------
# PRODUCTION ACTIVATION CONTRACT — valeurs canoniques de la Release
# Candidate Video 005, identiques à celles déjà gelées et vérifiées en
# Phase P2.9/P2.10/P2.11 (tests/test_phase_p2_11_human_authorization_
# guard.py::TestH). Reproduites ici (jamais recalculées à la baisse)
# pour que ce fichier reste un verrou autonome du contrat.
# ---------------------------------------------------------------------

CONTRACT_REQUEST_ID = "005"
CONTRACT_MODEL = PRODUCTION_MODEL  # "seedance_2_0"
CONTRACT_DURATION = 15
CONTRACT_RESOLUTION = "720p"
CONTRACT_ASPECT_RATIO = "9:16"
CONTRACT_COST_CREDITS = 67.5
CONTRACT_PROMPT_CHARS = 7284
CONTRACT_PROMPT_LINES = 265
CONTRACT_PROMPT_SHA256 = (
    "1c498617adb4603bcf2fc114a9cb9e8fe2219f09285adbff4d1e6c7a10a669e1"
)
CONTRACT_AVATAR_SHA256 = (
    "d293e41a63f66fd43afbebee3f7f9f1bd29143b465fa57a18ab4e1df5faf7280"
)
CONTRACT_FACE_SHA256 = (
    "df83a97b71cff9a90191c19d15ff989228b9fef2e57c96cf7c76c68652e3a343"
)

# Balance réelle vérifiée en lecture seule (Objectif 8/13) au moment de
# cette phase : 1.41 < 67.5 -> BUDGET INSUFFICIENT. Reproduite ici comme
# donnée FIGÉE du rapport, jamais comme une valeur que ce fichier
# recalculerait via le réseau.
CONTRACT_REAL_BALANCE_AT_AUDIT_TIME = 1.41


def _contract_violations(prompt: str, assets_by_role: dict) -> list:
    """
    Fonction d'aide LOCALE À CE FICHIER DE TEST (pas de nouveau code de
    production) : compare une reconstruction réelle de Video 005 aux
    valeurs canoniques ci-dessus et renvoie la liste des écarts.

    Documente sous forme exécutable l'écart connu : ce contrôle
    n'existe PAS aujourd'hui dans GenerationApprovalGate.evaluate() —
    seul un test de non-régression séparé (P2.11::TestH) le vérifie.
    """

    violations = []

    if len(prompt) != CONTRACT_PROMPT_CHARS:
        violations.append(
            f"prompt length {len(prompt)} != {CONTRACT_PROMPT_CHARS}"
        )

    if len(prompt.splitlines()) != CONTRACT_PROMPT_LINES:
        violations.append(
            f"prompt lines {len(prompt.splitlines())} != {CONTRACT_PROMPT_LINES}"
        )

    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if prompt_sha256 != CONTRACT_PROMPT_SHA256:
        violations.append(
            f"prompt sha256 {prompt_sha256} != {CONTRACT_PROMPT_SHA256}"
        )

    avatar = assets_by_role.get("master_avatar")
    if avatar is None or avatar.sha256 != CONTRACT_AVATAR_SHA256:
        violations.append("master_avatar sha256 mismatch or asset missing")

    face = assets_by_role.get("face_reference")
    if face is None or face.sha256 != CONTRACT_FACE_SHA256:
        violations.append("face_reference sha256 mismatch or asset missing")

    return violations


def _real_video_005_prompt_and_assets():
    pa = PromptAssemblySystem(PROJECT_ROOT)
    prompt = pa.assemble(CONTRACT_REQUEST_ID)

    aps = AssetPreparationSystem(PROJECT_ROOT)
    assets_by_role = {a.role: a for a in aps.scan() if a.status == "READY"}

    return prompt, assets_by_role


def _build_real_video_005_request(**overrides) -> GenerationRequest:
    """Reconstruit la GenerationRequest Video 005 via la CHAÎNE RÉELLE
    (VideoPlanner + PromptAssemblySystem + AssetPreparationSystem +
    VideoAgent) — jamais une requête inventée à la main."""

    planner = VideoPlanner(PROJECT_ROOT)
    plan = planner.create_zephyr_plan(
        video_id=CONTRACT_REQUEST_ID, title="t", hook="h", objective="o"
    )
    pa = PromptAssemblySystem(PROJECT_ROOT)
    aps = AssetPreparationSystem(PROJECT_ROOT)
    agent = VideoAgent(prompt_assembly=pa, asset_preparation=aps)

    request = agent.build_request(plan, approved=True)

    if overrides:
        request_dict = {
            "request_id": request.request_id,
            "job_type": request.job_type,
            "prompt": request.prompt,
            "duration": request.duration,
            "resolution": request.resolution,
            "aspect_ratio": request.aspect_ratio,
            "approved": request.approved,
            "start_image": request.start_image,
            "image_references": request.image_references,
            "real_generation_authorization": request.real_generation_authorization,
        }
        request_dict.update(overrides)
        request = GenerationRequest(**request_dict)

    return bind_request(request)


def _valid_auth(request_id=CONTRACT_REQUEST_ID) -> RealGenerationAuthorization:
    return RealGenerationAuthorization(request_id=request_id, authorized_by_human=True)


class TestA_Video005StructurallyValidButBudgetInsufficient(unittest.TestCase):
    """A — Video 005 exacte, contrat structurellement valide, mais
    budget insuffisant (solde réel 1.41 < coût réel 67.5) -> BLOCKED."""

    def test_identity_matches_contract(self):
        prompt, assets_by_role = _real_video_005_prompt_and_assets()
        self.assertEqual(_contract_violations(prompt, assets_by_role), [])

    def test_request_matches_contract_shape(self):
        request = _build_real_video_005_request()

        self.assertEqual(request.request_id, CONTRACT_REQUEST_ID)
        self.assertEqual(request.job_type, CONTRACT_MODEL)
        self.assertEqual(request.duration, CONTRACT_DURATION)
        self.assertEqual(request.resolution, CONTRACT_RESOLUTION)
        self.assertEqual(request.aspect_ratio, CONTRACT_ASPECT_RATIO)

    def test_blocked_with_real_cost_and_real_balance(self):
        request = _build_real_video_005_request(
            real_generation_authorization=_valid_auth()
        )
        provider = MockHiggsfieldProvider(
            cost_per_job=CONTRACT_COST_CREDITS,
            available_credits=CONTRACT_REAL_BALANCE_AT_AUDIT_TIME,
        )
        gate = GenerationApprovalGate(provider)

        result = gate.evaluate(request)

        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestB_InsufficientBudgetAlwaysBlocked(unittest.TestCase):
    """B — budget insuffisant, indépendamment de la requête précise -> BLOCKED."""

    def test_generic_insufficient_budget_blocked(self):
        provider = MockHiggsfieldProvider(cost_per_job=50.0, available_credits=1.41)
        gate = GenerationApprovalGate(provider)

        request = _build_real_video_005_request(
            real_generation_authorization=_valid_auth()
        )
        result = gate.evaluate(request)

        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)


class TestC_NoHumanAuthorizationNeverApproved(unittest.TestCase):
    """C — budget suffisant, approved=True, MAIS aucune autorisation
    humaine -> jamais APPROVED (approved=True n'est pas une
    autorisation)."""

    def test_no_authorization_yields_needs_approval_not_approved(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        request = _build_real_video_005_request(real_generation_authorization=None)
        result = gate.evaluate(request)

        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)
        self.assertEqual(result.decision, GenerationApprovalDecision.NEEDS_APPROVAL)


class TestD_AuthorizationRequestIdMismatchRefused(unittest.TestCase):
    """D — autorisation valide mais liée à un AUTRE request_id -> refus."""

    def test_mismatched_request_id_refused(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        request = _build_real_video_005_request(
            real_generation_authorization=RealGenerationAuthorization(
                request_id="NOT-005", authorized_by_human=True
            )
        )
        result = gate.evaluate(request)

        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestE_ReplayRefusedEvenWithFreshValidAuthorization(unittest.TestCase):
    """E — requête déjà exécutée -> refusée même avec budget suffisant
    et une autorisation humaine fraîche et valide."""

    def test_already_executed_refused(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)
        gate.mark_executed(CONTRACT_REQUEST_ID)

        request = _build_real_video_005_request(
            real_generation_authorization=_valid_auth()
        )
        result = gate.evaluate(request)

        self.assertEqual(result.decision, GenerationApprovalDecision.ALREADY_EXECUTED)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestF_TamperedPromptViolatesContract(unittest.TestCase):
    """F — un Master Prompt différent de la Release Candidate viole le
    contrat d'identité (détecté par _contract_violations). L'écart
    documenté en P2.17 (Objectif 7 : le Gate sans Identity Lock ne
    regardait jamais le prompt) est fermé en Phase B : l'autorisation
    porte l'empreinte du contenu approuvé, et le Gate refuse un prompt
    qu'elle ne couvre pas."""

    def test_tampered_prompt_hash_detected_as_violation(self):
        _, assets_by_role = _real_video_005_prompt_and_assets()
        tampered_prompt = "this is not the real master prompt"

        violations = _contract_violations(tampered_prompt, assets_by_role)

        self.assertTrue(any("sha256" in v for v in violations))

    def test_gate_refuses_prompt_not_covered_by_the_authorization(self):
        # Phase B : même SANS Identity Lock, le Gate compare le prompt
        # réellement évalué à l'empreinte portée par l'autorisation
        # humaine (donnée ici pour le Master Prompt réel de Video 005).
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)

        tampered_request = GenerationRequest(
            **content_media(),
            request_id=CONTRACT_REQUEST_ID,
            job_type=CONTRACT_MODEL,
            prompt="this is not the real master prompt",
            duration=5,
            resolution=CONTRACT_RESOLUTION,
            aspect_ratio=CONTRACT_ASPECT_RATIO,
            approved=True,
            real_generation_authorization=video_005_authorization(),
        )
        result = gate.evaluate(tampered_request)

        self.assertEqual(result.decision, GenerationApprovalDecision.NEEDS_APPROVAL)
        self.assertTrue(
            any("prompt_sha256" in reason for reason in result.reasons), result.reasons
        )


class TestG_TamperedAssetHashViolatesContract(unittest.TestCase):
    """G — un asset dont le sha256 diffère de la Release Candidate
    viole le contrat d'identité (détecté par _contract_violations)."""

    def test_tampered_asset_hash_detected_as_violation(self):
        prompt, assets_by_role = _real_video_005_prompt_and_assets()

        class _FakeAsset:
            sha256 = "0" * 64

        tampered_assets = dict(assets_by_role)
        tampered_assets["master_avatar"] = _FakeAsset()

        violations = _contract_violations(prompt, tampered_assets)

        self.assertTrue(any("master_avatar" in v for v in violations))


class TestH_CostRecomputedEachEvaluation(unittest.TestCase):
    """H — un coût différent (fraîchement recalculé) doit être
    reflété dans une réévaluation, jamais réutiliser une ancienne
    estimation mise en cache."""

    def test_cost_increase_between_two_evaluations_blocks_the_second(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)
        auth = _valid_auth()

        request = _build_real_video_005_request(real_generation_authorization=auth)

        first = gate.evaluate(request)
        self.assertEqual(first.decision, GenerationApprovalDecision.APPROVED)

        provider._cost_per_job = 1000.0  # Coût frais, différent, dépasse le solde.

        second = gate.evaluate(request)
        self.assertEqual(second.decision, GenerationApprovalDecision.BLOCKED)


class TestI_BalanceRereadEachEvaluation(unittest.TestCase):
    """I — un solde différent (fraîchement relu) doit être reflété
    dans une réévaluation, jamais une ancienne lecture mise en cache."""

    def test_balance_drop_between_two_evaluations_blocks_the_second(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)
        auth = _valid_auth()

        request = _build_real_video_005_request(real_generation_authorization=auth)

        first = gate.evaluate(request)
        self.assertEqual(first.decision, GenerationApprovalDecision.APPROVED)

        provider._available_credits = CONTRACT_REAL_BALANCE_AT_AUDIT_TIME  # Solde frais, différent.

        second = gate.evaluate(request)
        self.assertEqual(second.decision, GenerationApprovalDecision.BLOCKED)


class TestJ_RealProviderCreateJobAlwaysDisabled(unittest.TestCase):
    """J — HiggsfieldProvider.create_job() (réel) reste bloqué par
    HiggsfieldRealGenerationDisabledError, quel que soit l'état du
    contrat par ailleurs."""

    def test_real_create_job_disabled_even_with_full_contract_satisfied(self):
        fake_client = MagicMock()
        fake_client.estimate_cost.return_value = {"credits": CONTRACT_COST_CREDITS}
        fake_client.account_status.return_value = {"credits": 1000.0}
        fake_client.get_model.return_value = {
            "job_type": CONTRACT_MODEL,
            "display_name": "d",
            "params": [
                {"name": "prompt", "type": "string", "required": True},
                {"name": "duration", "type": "integer", "required": False, "default": 5},
                {"name": "start_image", "type": "object|null", "required": False},
                {"name": "image_references", "type": "array", "required": False},
            ],
        }

        real_provider = HiggsfieldProvider(client=fake_client)
        request = _build_real_video_005_request(
            duration=5,  # confirmé pour ce Mock (5/10/15 acceptés)
            real_generation_authorization=_valid_auth(),
        )
        # Phase D : fixtures de TEST explicites (plafond + Identity Lock) ;
        # sans elles, la Gate bloque le chemin réel avant create_job().
        gate = GenerationApprovalGate(
            real_provider,
            identity_lock=fixture_identity_lock_for(request),
            max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST,
        )
        service = GenerationJobService(real_provider, gate)

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            service.execute(request)

        fake_client.create_job.assert_not_called()


class TestK_NoCombinationOfConditionsPermitsRealCreateJob(unittest.TestCase):
    """K — même en combinant TOUTES les conditions favorables
    (identité contractuelle exacte, coût connu, budget largement
    suffisant, autorisation humaine valide, aucune exécution
    préalable), le Provider RÉEL reste protégé : aucune combinaison de
    conditions gérées par ce projet ne permet un vrai create_job()."""

    def test_full_favorable_contract_still_cannot_create_a_real_job(self):
        prompt, assets_by_role = _real_video_005_prompt_and_assets()
        self.assertEqual(_contract_violations(prompt, assets_by_role), [])

        fake_client = MagicMock()
        fake_client.estimate_cost.return_value = {"credits": 5.0}
        fake_client.account_status.return_value = {"credits": 100000.0}
        fake_client.get_model.return_value = {
            "job_type": CONTRACT_MODEL,
            "display_name": "d",
            "params": [
                {"name": "prompt", "type": "string", "required": True},
                {"name": "duration", "type": "integer", "required": False, "default": 5},
                {"name": "start_image", "type": "object|null", "required": False},
                {"name": "image_references", "type": "array", "required": False},
            ],
        }
        real_provider = HiggsfieldProvider(client=fake_client)
        request = _build_real_video_005_request(
            prompt=prompt,
            duration=5,
            real_generation_authorization=_valid_auth(),
        )
        # Phase D : fixtures de TEST explicites (plafond + Identity Lock) ;
        # sans elles, la Gate bloque le chemin réel avant create_job().
        gate = GenerationApprovalGate(
            real_provider,
            identity_lock=fixture_identity_lock_for(request),
            max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST,
        )
        service = GenerationJobService(real_provider, gate)

        approval = gate.evaluate(request)
        self.assertEqual(approval.decision, GenerationApprovalDecision.APPROVED)

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            service.execute(request)

        fake_client.create_job.assert_not_called()


class TestL_NoRealGenerationNoNetworkDependencyInThisModule(unittest.TestCase):
    """L — vérification structurelle : ce module de test n'importe
    aucune dépendance réseau réelle et ne construit jamais de
    HiggsfieldClient réel."""

    def test_module_has_no_real_client_or_network_import(self):
        import inspect

        import tests.test_phase_p2_17_production_activation_contract as module

        imported_names = {
            name
            for name, value in vars(module).items()
            if inspect.ismodule(value) or inspect.isclass(value)
        }
        self.assertNotIn("HiggsfieldClient", imported_names)
        self.assertFalse(hasattr(module, "requests"))
        self.assertFalse(hasattr(module, "socket"))


class TestM_NoCreditsConsumedAcrossThisModule(unittest.TestCase):
    """M — aucun crédit consommé : chaque scénario Mock/fake_client de
    ce module n'a jamais réellement créé de job facturable."""

    def test_gate_alone_never_creates_a_mock_job(self):
        provider = MockHiggsfieldProvider(
            cost_per_job=CONTRACT_COST_CREDITS,
            available_credits=CONTRACT_REAL_BALANCE_AT_AUDIT_TIME,
        )
        gate = GenerationApprovalGate(provider)

        request = _build_real_video_005_request(
            real_generation_authorization=_valid_auth()
        )
        gate.evaluate(request)

        self.assertEqual(len(provider._jobs), 0)


if __name__ == "__main__":
    unittest.main()
