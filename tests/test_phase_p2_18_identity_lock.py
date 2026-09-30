"""
Tests — Phase P2.18 : RELEASE CANDIDATE IDENTITY LOCK.

Verrouille le mécanisme introduit par
agents/release_candidate_identity_lock.py, qui ferme le gap
structurel identifié en P2.17 : `GenerationApprovalGate.evaluate()`
recalcule désormais réellement le SHA-256 du Master Prompt et des
fichiers d'assets référencés (avatar_master, face_reference) lorsqu'un
`ReleaseCandidateIdentityLock` est injecté (comportement par défaut
INCHANGÉ si non injecté — cf. TestJ_NoCacheOfAnyPriorDecision de
P2.12, mis à jour pour connaître ce nouvel attribut).

Aucun fichier canonique n'est jamais modifié : les scénarios
adversariaux (assets modifiés) opèrent sur des COPIES temporaires
(tempfile.TemporaryDirectory), jamais sur
`assets/zephyr/avatar/avatar_master.png` ni
`assets/zephyr/references/mon avatar habille.png`. Toutes les données
Higgsfield (coût, solde) sont simulées via MockHiggsfieldProvider ou un
HiggsfieldProvider réel avec un client factice (MagicMock) — AUCUN
réseau, AUCUN CLI réel, AUCUN crédit consommé, AUCUN create_job() réel.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.asset_preparation_system import AssetPreparationSystem
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from tests.real_provider_path_fixtures import FIXTURE_MAX_COST_CREDITS_PER_REQUEST
from tests.authorization_content_helpers import bind_request
from agents.generation_job_service import GenerationJobService
from agents.planner import VideoPlanner
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.release_candidate_identity_lock import (
    ReleaseCandidateIdentityLock,
    VIDEO_005_RELEASE_CANDIDATE,
)
from agents.video_agent import VideoAgent
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
    return PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id)


def _conforming_request(**overrides) -> GenerationRequest:
    """Requête strictement conforme au contrat Video 005 -- toute
    modification se fait via `overrides`."""

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
    return bind_request(GenerationRequest(**defaults))


def _build_real_chain_request(**overrides) -> GenerationRequest:
    """Reconstruit la GenerationRequest via la chaîne RÉELLE
    (VideoPlanner + PromptAssemblySystem + AssetPreparationSystem +
    VideoAgent), pour prouver que le contrat correspond à ce que le
    chemin de production construit réellement (Objectif 8 : "VERIFY
    WHAT WILL ACTUALLY BE SENT")."""

    planner = VideoPlanner(PROJECT_ROOT)
    plan = planner.create_zephyr_plan(
        video_id=C.request_id, title="t", hook="h", objective="o"
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

    return request


def _new_gate(cost_per_job=10.0, available_credits=100.0) -> GenerationApprovalGate:
    provider = MockHiggsfieldProvider(
        cost_per_job=cost_per_job, available_credits=available_credits
    )
    lock = ReleaseCandidateIdentityLock(C)
    return GenerationApprovalGate(provider, identity_lock=lock)


def _valid_auth(request_id=None) -> RealGenerationAuthorization:
    return RealGenerationAuthorization(
        request_id=request_id or C.request_id, authorized_by_human=True
    )


class TestA_ExactRequestAcceptedByIdentityLock(unittest.TestCase):
    """A — la Release Candidate exacte (chaîne réelle ET requête
    manuelle conforme) est acceptée par le contrat d'identité."""

    def test_no_violations_for_conforming_request(self):
        lock = ReleaseCandidateIdentityLock(C)
        self.assertEqual(lock.violations(_conforming_request()), [])

    def test_no_violations_for_real_chain_request(self):
        lock = ReleaseCandidateIdentityLock(C)
        request = _build_real_chain_request()
        self.assertEqual(lock.violations(request), [])

    def test_gate_approves_when_everything_else_is_satisfied(self):
        gate = _new_gate()
        request = _conforming_request(real_generation_authorization=_valid_auth())
        result = gate.evaluate(request)
        self.assertEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestB_ModifiedPromptRejected(unittest.TestCase):
    """Attack A — un seul caractère du Master Prompt modifié -> BLOCKED."""

    def test_one_character_changed_detected(self):
        prompt = _real_prompt()
        tampered = prompt[:-1] + ("X" if prompt[-1] != "X" else "Y")

        lock = ReleaseCandidateIdentityLock(C)
        violations = lock.violations(_conforming_request(prompt=tampered))

        self.assertTrue(any("sha256" in v for v in violations))

    def test_gate_never_approves_tampered_prompt(self):
        gate = _new_gate()
        prompt = _real_prompt()
        tampered = prompt[:-1] + ("X" if prompt[-1] != "X" else "Y")

        request = _conforming_request(
            prompt=tampered, real_generation_authorization=_valid_auth()
        )
        result = gate.evaluate(request)

        self.assertEqual(result.decision, GenerationApprovalDecision.INVALID_REQUEST)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestC_TruncatedPromptRejected(unittest.TestCase):
    """C — prompt tronqué -> BLOCKED."""

    def test_truncated_prompt_detected(self):
        truncated = _real_prompt()[:-1]

        lock = ReleaseCandidateIdentityLock(C)
        violations = lock.violations(_conforming_request(prompt=truncated))

        self.assertTrue(any("length" in v for v in violations))
        self.assertTrue(any("sha256" in v for v in violations))

    def test_gate_never_approves_truncated_prompt(self):
        gate = _new_gate()
        truncated = _real_prompt()[:-1]

        request = _conforming_request(
            prompt=truncated, real_generation_authorization=_valid_auth()
        )
        result = gate.evaluate(request)

        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestD_ModifiedAvatarRejected(unittest.TestCase):
    """Attack B — un byte du fichier avatar modifié -> BLOCKED."""

    def test_tampered_avatar_file_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tampered_path = Path(tmpdir) / "avatar_master.png"
            data = bytearray(REAL_AVATAR_PATH.read_bytes())
            data[0] ^= 0xFF  # Un seul byte modifié.
            tampered_path.write_bytes(bytes(data))

            request = _conforming_request(
                start_image=MediaReference(
                    role="master_avatar",
                    source=str(tampered_path),
                    sha256=C.avatar_master_sha256,  # Hash déclaré INCHANGÉ, correct.
                )
            )

            lock = ReleaseCandidateIdentityLock(C)
            violations = lock.violations(request)

            self.assertTrue(any("master_avatar" in v for v in violations))

    def test_gate_never_approves_tampered_avatar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tampered_path = Path(tmpdir) / "avatar_master.png"
            data = bytearray(REAL_AVATAR_PATH.read_bytes())
            data[0] ^= 0xFF
            tampered_path.write_bytes(bytes(data))

            gate = _new_gate()
            request = _conforming_request(
                start_image=MediaReference(
                    role="master_avatar",
                    source=str(tampered_path),
                    sha256=C.avatar_master_sha256,
                ),
                real_generation_authorization=_valid_auth(),
            )
            result = gate.evaluate(request)

            self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)

    def test_original_avatar_file_untouched(self):
        # Non-régression P2.15/P2.17 : le fichier canonique reste intact.
        self.assertEqual(
            AssetPreparationSystem(PROJECT_ROOT).calculate_hash(REAL_AVATAR_PATH),
            C.avatar_master_sha256,
        )


class TestE_ModifiedFaceReferenceRejected(unittest.TestCase):
    """Attack C — un byte du fichier face_reference modifié -> BLOCKED."""

    def test_tampered_face_reference_file_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tampered_path = Path(tmpdir) / "face.png"
            data = bytearray(REAL_FACE_PATH.read_bytes())
            data[0] ^= 0xFF
            tampered_path.write_bytes(bytes(data))

            request = _conforming_request(
                image_references=(
                    MediaReference(
                        role="face_reference",
                        source=str(tampered_path),
                        sha256=C.face_reference_sha256,
                    ),
                )
            )

            lock = ReleaseCandidateIdentityLock(C)
            violations = lock.violations(request)

            self.assertTrue(any("face_reference" in v for v in violations))

    def test_gate_never_approves_tampered_face_reference(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tampered_path = Path(tmpdir) / "face.png"
            data = bytearray(REAL_FACE_PATH.read_bytes())
            data[0] ^= 0xFF
            tampered_path.write_bytes(bytes(data))

            gate = _new_gate()
            request = _conforming_request(
                image_references=(
                    MediaReference(
                        role="face_reference",
                        source=str(tampered_path),
                        sha256=C.face_reference_sha256,
                    ),
                ),
                real_generation_authorization=_valid_auth(),
            )
            result = gate.evaluate(request)

            self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)

    def test_original_face_reference_file_untouched(self):
        self.assertEqual(
            AssetPreparationSystem(PROJECT_ROOT).calculate_hash(REAL_FACE_PATH),
            C.face_reference_sha256,
        )


class TestF_WrongRequestIdRejected(unittest.TestCase):
    """F — mauvais request_id -> BLOCKED."""

    def test_wrong_request_id_detected(self):
        lock = ReleaseCandidateIdentityLock(C)
        violations = lock.violations(_conforming_request(request_id="006"))
        self.assertTrue(any("request_id" in v for v in violations))

    def test_gate_never_approves_wrong_request_id(self):
        gate = _new_gate()
        request = _conforming_request(
            request_id="006",
            real_generation_authorization=_valid_auth(request_id="006"),
        )
        result = gate.evaluate(request)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestG_WrongModelRejected(unittest.TestCase):
    """G — mauvais model -> BLOCKED."""

    def test_wrong_model_detected(self):
        lock = ReleaseCandidateIdentityLock(C)
        violations = lock.violations(_conforming_request(job_type="other_model_9000"))
        self.assertTrue(any("job_type" in v for v in violations))

    def test_gate_never_approves_wrong_model(self):
        gate = _new_gate()
        request = _conforming_request(
            job_type="other_model_9000",
            real_generation_authorization=_valid_auth(),
        )
        result = gate.evaluate(request)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestH_WrongDurationRejected(unittest.TestCase):
    """H — mauvaise duration (même une valeur par ailleurs "confirmée"
    pour le modèle en général, ex. 5s) -> BLOCKED par le contrat de
    Release Candidate, qui exige EXACTEMENT 15s pour Video 005."""

    def test_wrong_duration_detected(self):
        lock = ReleaseCandidateIdentityLock(C)
        violations = lock.violations(_conforming_request(duration=5))
        self.assertTrue(any("duration" in v for v in violations))

    def test_gate_never_approves_wrong_duration(self):
        gate = _new_gate()
        request = _conforming_request(
            duration=5, real_generation_authorization=_valid_auth()
        )
        result = gate.evaluate(request)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestI_WrongResolutionRejected(unittest.TestCase):
    """I — mauvaise résolution -> BLOCKED."""

    def test_wrong_resolution_detected(self):
        lock = ReleaseCandidateIdentityLock(C)
        violations = lock.violations(_conforming_request(resolution="1080p"))
        self.assertTrue(any("resolution" in v for v in violations))

    def test_gate_never_approves_wrong_resolution(self):
        gate = _new_gate()
        request = _conforming_request(
            resolution="1080p", real_generation_authorization=_valid_auth()
        )
        result = gate.evaluate(request)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestJ_WrongAspectRatioRejected(unittest.TestCase):
    """J — mauvais aspect ratio -> BLOCKED."""

    def test_wrong_aspect_ratio_detected(self):
        lock = ReleaseCandidateIdentityLock(C)
        violations = lock.violations(_conforming_request(aspect_ratio="16:9"))
        self.assertTrue(any("aspect_ratio" in v for v in violations))

    def test_gate_never_approves_wrong_aspect_ratio(self):
        gate = _new_gate()
        request = _conforming_request(
            aspect_ratio="16:9", real_generation_authorization=_valid_auth()
        )
        result = gate.evaluate(request)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestK_MissingAssetRejected(unittest.TestCase):
    """K — asset absent -> BLOCKED."""

    def test_missing_start_image_detected(self):
        lock = ReleaseCandidateIdentityLock(C)
        violations = lock.violations(_conforming_request(start_image=None))
        self.assertTrue(any("start_image" in v for v in violations))

    def test_missing_face_reference_detected(self):
        lock = ReleaseCandidateIdentityLock(C)
        violations = lock.violations(_conforming_request(image_references=()))
        self.assertTrue(any("face_reference" in v for v in violations))

    def test_gate_never_approves_with_missing_assets(self):
        gate = _new_gate()
        request = _conforming_request(
            start_image=None,
            image_references=(),
            real_generation_authorization=_valid_auth(),
        )
        result = gate.evaluate(request)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestL_MissingPromptRejected(unittest.TestCase):
    """L — prompt absent/vide -> BLOCKED."""

    def test_empty_prompt_detected(self):
        lock = ReleaseCandidateIdentityLock(C)
        violations = lock.violations(_conforming_request(prompt=""))
        self.assertTrue(any("prompt" in v for v in violations))

    def test_gate_never_approves_empty_prompt(self):
        gate = _new_gate()
        request = _conforming_request(
            prompt="", real_generation_authorization=_valid_auth()
        )
        result = gate.evaluate(request)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestM_DeclaredHashMismatchRejected(unittest.TestCase):
    """Attack E — le fichier réel est INCHANGÉ et correct, mais le
    hash déclaré (MediaReference.sha256) est falsifié -> BLOCKED (le
    contrat ne fait jamais confiance à un hash transmis qui contredit
    la réalité, même quand la réalité elle-même est correcte)."""

    def test_falsified_declared_hash_on_correct_file_detected(self):
        request = _conforming_request(
            start_image=MediaReference(
                role="master_avatar",
                source=str(REAL_AVATAR_PATH),  # fichier réel, inchangé, correct.
                sha256="0" * 64,  # hash déclaré falsifié.
            )
        )

        lock = ReleaseCandidateIdentityLock(C)
        violations = lock.violations(request)

        self.assertTrue(any("inconsistent metadata" in v for v in violations))

    def test_gate_never_approves_with_falsified_declared_hash(self):
        gate = _new_gate()
        request = _conforming_request(
            start_image=MediaReference(
                role="master_avatar",
                source=str(REAL_AVATAR_PATH),
                sha256="0" * 64,
            ),
            real_generation_authorization=_valid_auth(),
        )
        result = gate.evaluate(request)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestN_HumanAuthorizationCannotRescueChangedIdentity(unittest.TestCase):
    """Attack F — une autorisation humaine fraîche et valide, liée au
    bon request_id, n'autorise JAMAIS une requête dont l'IDENTITÉ a
    changé par ailleurs (ex. duration)."""

    def test_fresh_valid_authorization_does_not_bypass_identity_lock(self):
        gate = _new_gate()
        request = _conforming_request(
            duration=5,  # identité modifiée
            real_generation_authorization=_valid_auth(),  # autorisation valide et fraîche
        )
        result = gate.evaluate(request)

        self.assertEqual(result.decision, GenerationApprovalDecision.INVALID_REQUEST)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestO_ProviderRemainsDisabledEvenWithPerfectContract(unittest.TestCase):
    """Objectif 11 — requête parfaitement conforme (identité, budget
    simulé suffisant, approved=True, autorisation humaine valide) :
    le PROVIDER RÉEL reste désactivé."""

    def test_real_create_job_still_disabled_with_full_contract(self):
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
        # Phase D : fixtures de TEST explicites (plafond + Identity Lock) ;
        # sans elles, la Gate bloque le chemin réel avant create_job().
        gate = GenerationApprovalGate(
            real_provider,
            identity_lock=lock,
            max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST,
        )
        service = GenerationJobService(real_provider, gate)

        request = _conforming_request(real_generation_authorization=_valid_auth())

        approval = gate.evaluate(request)
        self.assertEqual(approval.decision, GenerationApprovalDecision.APPROVED)

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            service.execute(request)

        fake_client.create_job.assert_not_called()


class TestP_IdentityLockDoesNotBreakOtherGuards(unittest.TestCase):
    """Objectif 10 — l'Identity Lock ne casse pas les garde-fous
    existants (replay, budget, autorisation humaine), et respecte la
    hiérarchie Identity -> Replay -> Cost -> Balance -> ..."""

    def test_replay_guard_still_blocks_with_identity_lock_active(self):
        gate = _new_gate()
        gate.mark_executed(C.request_id)

        request = _conforming_request(real_generation_authorization=_valid_auth())
        result = gate.evaluate(request)

        self.assertEqual(result.decision, GenerationApprovalDecision.ALREADY_EXECUTED)

    def test_insufficient_budget_still_blocks_with_identity_lock_active(self):
        gate = _new_gate(cost_per_job=50.0, available_credits=1.41)

        request = _conforming_request(real_generation_authorization=_valid_auth())
        result = gate.evaluate(request)

        self.assertEqual(result.decision, GenerationApprovalDecision.BLOCKED)

    def test_missing_human_authorization_still_needs_approval(self):
        gate = _new_gate()

        request = _conforming_request(real_generation_authorization=None)
        result = gate.evaluate(request)

        self.assertEqual(result.decision, GenerationApprovalDecision.NEEDS_APPROVAL)

    def test_default_gate_without_identity_lock_is_unaffected(self):
        # Comportement historique préservé : sans injection explicite,
        # AUCUNE vérification d'identité n'a lieu (cf. docstring du
        # module release_candidate_identity_lock.py).
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)  # identity_lock=None implicite

        request = _conforming_request(
            duration=5,  # violerait le contrat P2.18 s'il était actif
            real_generation_authorization=_valid_auth(),
        )
        result = gate.evaluate(request)

        self.assertEqual(result.decision, GenerationApprovalDecision.APPROVED)


class TestQ_DirectorRealChainWiresIdentityLock(unittest.TestCase):
    """Vérifie que le chemin de production réel (director.py) injecte
    bien un ReleaseCandidateIdentityLock lié à Video 005 -- sans
    jamais invoquer le CLI (construction d'objets uniquement)."""

    def test_default_report_service_gate_has_identity_lock(self):
        from director import AIDirector

        director = AIDirector()
        report_service = director._build_default_report_service()

        self.assertIsInstance(
            report_service.gate.identity_lock, ReleaseCandidateIdentityLock
        )
        self.assertEqual(
            report_service.gate.identity_lock.contract.request_id, "005"
        )


class TestR_NoRealGenerationNoNetworkInThisModule(unittest.TestCase):
    """Vérification structurelle : ce module ne construit jamais de
    HiggsfieldClient réel ni de dépendance réseau."""

    def test_module_has_no_real_client_or_network_import(self):
        import inspect

        import tests.test_phase_p2_18_identity_lock as module

        imported_names = {
            name
            for name, value in vars(module).items()
            if inspect.ismodule(value) or inspect.isclass(value)
        }
        self.assertNotIn("HiggsfieldClient", imported_names)
        self.assertFalse(hasattr(module, "requests"))
        self.assertFalse(hasattr(module, "socket"))


if __name__ == "__main__":
    unittest.main()
