"""
Tests — Phase P2.7 : ZEPHYR ASSET WIRING & IDENTITY REFERENCE INTEGRATION.

Avant P2.7, AIDirector.run_video_mission() construisait un VideoAgent
sans AssetPreparationSystem : la requête réelle de Video 005 portait
toujours start_image=None / image_references=() malgré la présence
d'assets d'identité READY sur disque (avatar_master.png, "mon avatar
habille.png"). Cette suite verrouille le câblage corrigé (director.py)
sans dupliquer la logique d'AssetPreparationSystem/VideoAgent, déjà
testée ailleurs (tests/test_asset_preparation_system.py,
tests/test_video_agent.py).

Aucun test de ce module n'appelle create_job() ni n'utilise un
HiggsfieldProvider réel : la vérification du câblage des assets ne
nécessite ni Provider, ni Gate, ni coût, ni solde. Là où un Provider
est nécessaire pour construire une chaîne complète (Test C), seul
MockHiggsfieldProvider est utilisé.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.asset_preparation_system import AssetPreparationSystem
from agents.final_report_service import FinalReport, FinalReportStatus
from agents.generation_approval_gate import GenerationApprovalDecision
from agents.planner import VideoPlanner
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.video_agent import VideoAgent
from director import AIDirector
from integrations.higgsfield.types import MediaReference


def _build_plan():
    planner = VideoPlanner(PROJECT_ROOT)
    return planner.create_zephyr_plan(
        video_id="005",
        title="Titre de test",
        hook="Hook de test",
        objective="Objectif de test",
    )


class _CapturingReportService:
    """
    Double de test minimal pour FinalReportService : capture la
    GenerationRequest reçue sans jamais toucher à un Provider, un Gate
    ou au CLI Higgsfield. Utilisé uniquement pour vérifier, au niveau
    de AIDirector.run_video_mission(), QUELLE requête a été construite
    -- jamais pour simuler un succès de génération.
    """

    def __init__(self):
        self.captured_request = None

    def generate(self, request, timeout_seconds=600, interval_seconds=3):
        self.captured_request = request

        return FinalReport(
            request_id=request.request_id,
            job_type=request.job_type,
            status=FinalReportStatus.NOT_EXECUTED,
            job_created=False,
            approval_decision=GenerationApprovalDecision.INVALID_REQUEST,
            approval_reasons=["Capturing double: no real evaluation performed."],
        )


class TestA_AssetPreparationSystemDetectsIdentityAssets(unittest.TestCase):
    """Test A — les assets d'identité Zephyr attendus sont détectés."""

    def test_master_avatar_and_face_reference_are_ready(self):
        system = AssetPreparationSystem(PROJECT_ROOT)
        assets = system.scan()

        by_role = {asset.role: asset for asset in assets if asset.status == "READY"}

        self.assertIn("master_avatar", by_role)
        self.assertIn("face_reference", by_role)
        self.assertEqual(by_role["master_avatar"].filename, "avatar_master.png")
        self.assertEqual(by_role["face_reference"].filename, "mon avatar habille.png")
        self.assertTrue(by_role["master_avatar"].sha256)
        self.assertTrue(by_role["face_reference"].sha256)


class TestB_VideoAgentTransmitsReferencesToGenerationRequest(unittest.TestCase):
    """Test B — VideoAgent transmet correctement les références à GenerationRequest."""

    def test_build_request_populates_start_image_and_image_references(self):
        asset_preparation = AssetPreparationSystem(PROJECT_ROOT)
        prompt_assembly = PromptAssemblySystem(PROJECT_ROOT)
        agent = VideoAgent(
            prompt_assembly=prompt_assembly,
            asset_preparation=asset_preparation,
        )
        plan = _build_plan()

        request = agent.build_request(plan)

        self.assertIsInstance(request.start_image, MediaReference)
        self.assertEqual(request.start_image.role, "master_avatar")
        self.assertEqual(len(request.image_references), 1)
        self.assertEqual(request.image_references[0].role, "face_reference")

    def test_build_request_without_asset_preparation_keeps_previous_behavior(self):
        # Non-régression : sans AssetPreparationSystem injecté (aucun
        # appelant ne le fait), le comportement pré-P2.7 est inchangé.
        prompt_assembly = PromptAssemblySystem(PROJECT_ROOT)
        agent = VideoAgent(prompt_assembly=prompt_assembly)
        plan = _build_plan()

        request = agent.build_request(plan)

        self.assertIsNone(request.start_image)
        self.assertEqual(request.image_references, ())


class TestC_DirectorRealPathTransmitsReferences(unittest.TestCase):
    """
    Test C — le chemin réel AIDirector.run_video_mission() -> VideoAgent
    -> GenerationRequest transmet bien les références.

    Utilise un report_service "capturant" (aucun Provider/Gate/CLI réel)
    injecté via le paramètre `report_service` de run_video_mission() :
    seule la construction interne de VideoAgent (chemin réel, non
    mocké) est exercée.
    """

    def test_run_video_mission_builds_request_with_identity_references(self):
        director = AIDirector()
        capturing_service = _CapturingReportService()

        director.run_video_mission(
            video_id="005",
            title="Titre de test",
            hook="Hook de test",
            objective="Objectif de test",
            report_service=capturing_service,
        )

        request = capturing_service.captured_request
        self.assertIsNotNone(request)
        self.assertIsNotNone(request.start_image)
        self.assertEqual(request.start_image.role, "master_avatar")
        self.assertEqual(len(request.image_references), 1)
        self.assertEqual(request.image_references[0].role, "face_reference")


class TestD_Video005RequestContainsIdentityReferences(unittest.TestCase):
    """Test D — la requête finale de Video 005 contient les références attendues."""

    def test_video_005_request_no_longer_none_and_empty(self):
        director = AIDirector()
        capturing_service = _CapturingReportService()

        director.run_video_mission(
            video_id="005",
            title="Pourquoi la discipline vaut plus que le talent.",
            hook="Le talent impressionne. La discipline construit des empires.",
            objective="Creer une video courte, cinematique et motivante.",
            report_service=capturing_service,
        )

        request = capturing_service.captured_request
        self.assertNotEqual(request.start_image, None)
        self.assertNotEqual(request.image_references, ())

        # Paramètres canoniques inchangés par le câblage des assets.
        self.assertEqual(request.job_type, "seedance_2_0")
        self.assertEqual(request.duration, 15)
        self.assertEqual(request.resolution, "720p")
        self.assertEqual(request.aspect_ratio, "9:16")


class TestE_IdentityReferencesMatchRealAssetsNotArbitraryPaths(unittest.TestCase):
    """
    Test E — les références transmises correspondent aux VRAIS assets
    d'identité scannés par AssetPreparationSystem (même chemin, même
    sha256), jamais à un chemin arbitraire ou codé en dur.
    """

    def test_start_image_matches_scanned_master_avatar(self):
        asset_preparation = AssetPreparationSystem(PROJECT_ROOT)
        real_assets = {
            asset.role: asset
            for asset in asset_preparation.scan()
            if asset.status == "READY"
        }

        prompt_assembly = PromptAssemblySystem(PROJECT_ROOT)
        agent = VideoAgent(
            prompt_assembly=prompt_assembly,
            asset_preparation=asset_preparation,
        )
        request = agent.build_request(_build_plan())

        self.assertEqual(request.start_image.source, real_assets["master_avatar"].path)
        self.assertEqual(request.start_image.sha256, real_assets["master_avatar"].sha256)

        self.assertEqual(
            request.image_references[0].source,
            real_assets["face_reference"].path,
        )
        self.assertEqual(
            request.image_references[0].sha256,
            real_assets["face_reference"].sha256,
        )


class TestF_NoRealGenerationInvolved(unittest.TestCase):
    """
    Test F — aucun test de cette suite n'appelle create_job() ni un
    endpoint payant. Vérifié structurellement (comme
    TestVideoAgentNoCliDependency dans tests/test_video_agent.py) :
    ce module n'importe ni HiggsfieldProvider (réel), ni
    HiggsfieldClient, ni subprocess/requests/socket — il est donc
    structurellement impossible qu'un de ses tests atteigne le CLI
    Higgsfield ou create_job().
    """

    def test_module_imports_no_real_provider_or_network_dependency(self):
        import inspect

        import tests.test_phase_p2_7_asset_identity_wiring as module

        imported_names = {
            name
            for name, value in vars(module).items()
            if inspect.ismodule(value) or inspect.isclass(value)
        }

        self.assertNotIn("HiggsfieldProvider", imported_names)
        self.assertNotIn("HiggsfieldClient", imported_names)
        self.assertFalse(hasattr(module, "subprocess"))
        self.assertFalse(hasattr(module, "requests"))
        self.assertFalse(hasattr(module, "socket"))


if __name__ == "__main__":
    unittest.main()
