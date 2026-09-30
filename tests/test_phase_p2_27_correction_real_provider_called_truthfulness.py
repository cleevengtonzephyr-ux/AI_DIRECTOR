"""
Tests — P2.27 CORRECTION CIBLÉE : FINAL REPORT TRUTHFULNESS
(`real_provider_called`).

BUG CORRIGÉ : `FinalReportService.generate()` renvoyait
`real_provider_called=True` INCONDITIONNELLEMENT dans son bloc de
succès -- y compris avec `MockHiggsfieldProvider`, ce qui était
factuellement faux : `real_provider_called` doit signifier
littéralement "le VRAI HiggsfieldProvider a été utilisé", jamais "un
job a été créé, quel que soit le provider".

CORRECTION : `real_provider_called` est désormais déterminé par
identité de méthode sur le provider RÉELLEMENT utilisé par
`GenerationJobService` (`agents/final_report_service.py::
FinalReportService._is_real_provider()`), jamais déduit de
`job_created`. `integrations/higgsfield/provider.py` n'a PAS été
modifié : `HiggsfieldProvider.create_job()` continue de lever
inconditionnellement `HiggsfieldRealGenerationDisabledError`.

Ce fichier verrouille les quatre scénarios minimaux exigés par l'audit :
A. Mock positive path -- job_created=True, status=EXECUTED_PASS,
   real_provider_called=False.
B. Real provider path -- create_job() reste bloqué, aucune génération
   réelle.
C. Direct provider call -- appel direct à create_job() sans passer par
   AUCUN garde-fou, toujours bloqué.
D. No ambiguity -- job_created=True ne peut jamais, à lui seul,
   produire real_provider_called=True.
"""

import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import RequestScopedActivationService
from agents.controlled_real_provider_activation import ControlledRealProviderActivationService
from agents.critical_section_lock import FileCriticalSectionLock
from agents.final_report_service import FinalReportService, FinalReportStatus
from agents.generation_approval_gate import (
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from tests.real_provider_path_fixtures import FIXTURE_MAX_COST_CREDITS_PER_REQUEST
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


class TestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_27_correction_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)


# ----------------------------------------------------------------------
# A. Mock positive path
# ----------------------------------------------------------------------


class TestA_MockPositivePath(TestCase):
    def test_mock_success_reports_real_provider_called_false(self):
        provider = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=100.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
        activation_service = RequestScopedActivationService(gate, identity_lock)
        lock = FileCriticalSectionLock(self._tmp)
        job_service = GenerationJobService(
            provider, gate, lock=lock, activation_service=activation_service
        )
        report_service = FinalReportService(provider, gate, job_service=job_service)

        request = _conforming_request()
        contract = activation_service.prepare_activation(request)

        report = report_service.generate(
            request, activation_contract=contract, interval_seconds=0
        )

        self.assertTrue(report.job_created)
        self.assertEqual(report.status, FinalReportStatus.EXECUTED_PASS)
        self.assertFalse(report.real_provider_called)

    def test_mock_success_without_any_contract_also_reports_false(self):
        # Chemin legacy (P2.20, sans contrat d'activation) -- même
        # correction s'applique.
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)
        report_service = FinalReportService(provider, gate)

        request = _conforming_request(request_id="005")
        report = report_service.generate(request, interval_seconds=0)

        self.assertTrue(report.job_created)
        self.assertFalse(report.real_provider_called)


# ----------------------------------------------------------------------
# B. Real provider path -- blocked
# ----------------------------------------------------------------------


class TestB_RealProviderPathBlocked(TestCase):
    def test_real_provider_create_job_stays_blocked_no_real_generation(self):
        fake_client = MagicMock()
        fake_client.estimate_cost.return_value = {"credits": 67.5}
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
        identity_lock = ReleaseCandidateIdentityLock(C)
        # Phase D : fixtures de TEST explicites (plafond + Identity Lock) ;
        # sans elles, la Gate bloque le chemin réel avant create_job().
        gate = GenerationApprovalGate(
            real_provider,
            identity_lock=identity_lock,
            max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST,
        )
        activation_service = RequestScopedActivationService(gate, identity_lock)
        pa_service = ControlledRealProviderActivationService(gate, identity_lock, activation_service)
        lock = FileCriticalSectionLock(self._tmp)
        job_service = GenerationJobService(
            real_provider, gate, lock=lock,
            activation_service=activation_service, provider_activation_service=pa_service,
        )
        report_service = FinalReportService(real_provider, gate, job_service=job_service)

        request = _conforming_request()

        # Aucun rapport n'est jamais produit dans ce cas -- l'exception
        # de désactivation propage telle quelle, non capturée (Phase
        # P2.23, décision délibérée, reconfirmée ici) : c'est la
        # garantie la plus forte qu'aucun rapport ne puisse jamais
        # afficher real_provider_called=True/EXECUTED_PASS.
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            report_service.generate(request, interval_seconds=0)

        fake_client.create_job.assert_not_called()

    def test_is_real_provider_helper_correctly_identifies_the_real_class(self):
        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)
        gate = GenerationApprovalGate(real_provider)
        job_service = GenerationJobService(real_provider, gate)
        report_service = FinalReportService(real_provider, gate, job_service=job_service)

        self.assertTrue(report_service._is_real_provider())

    def test_is_real_provider_helper_correctly_identifies_mock_as_not_real(self):
        provider = MockHiggsfieldProvider()
        gate = GenerationApprovalGate(provider)
        job_service = GenerationJobService(provider, gate)
        report_service = FinalReportService(provider, gate, job_service=job_service)

        self.assertFalse(report_service._is_real_provider())


# ----------------------------------------------------------------------
# C. Direct provider call
# ----------------------------------------------------------------------


class TestC_DirectProviderCall(unittest.TestCase):
    def test_direct_create_job_call_with_zero_guards_still_raises(self):
        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(job_type="seedance_2_0", prompt="anything")
        fake_client.create_job.assert_not_called()


# ----------------------------------------------------------------------
# D. No ambiguity -- job_created alone can never imply real_provider_called
# ----------------------------------------------------------------------


class TestD_NoAmbiguityBetweenJobCreatedAndRealProviderCalled(TestCase):
    def test_job_created_true_does_not_imply_real_provider_called_true(self):
        # Démonstration directe et minimale : deux FinalReport tous
        # deux avec job_created=True (l'un Mock, l'autre -- s'il
        # existait -- réel) ne doivent JAMAIS partager la même valeur
        # de real_provider_called simplement parce que job_created
        # est identique des deux côtés.
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(provider)
        job_service = GenerationJobService(provider, gate)
        report_service = FinalReportService(provider, gate, job_service=job_service)

        request = _conforming_request()
        report = report_service.generate(request, interval_seconds=0)

        self.assertTrue(report.job_created)
        self.assertFalse(
            report.real_provider_called,
            "job_created=True must never automatically imply "
            "real_provider_called=True -- they are two independent facts.",
        )

    def test_real_provider_called_field_is_computed_from_provider_type_not_from_outcome(self):
        # Preuve structurelle, sur le CODE réel (jamais le docstring,
        # qui mentionne légitimement "job_created"/"outcome" en prose
        # pour expliquer ce que la méthode NE fait PAS) : `_is_real_
        # provider()` ne référence, dans son corps exécutable, ni
        # `outcome` ni `job_created` -- uniquement
        # `self.job_service.provider`.
        import ast
        import inspect

        sig = inspect.signature(FinalReportService._is_real_provider)
        self.assertEqual(list(sig.parameters), ["self"])

        source = inspect.getsource(FinalReportService._is_real_provider)
        tree = ast.parse(source.strip())
        func_node = tree.body[0]
        # Ignore le docstring (premier Expr/Constant du corps) --
        # n'inspecte que les instructions RÉELLEMENT exécutées.
        body_without_docstring = func_node.body[1:] if (
            func_node.body
            and isinstance(func_node.body[0], ast.Expr)
            and isinstance(getattr(func_node.body[0], "value", None), ast.Constant)
        ) else func_node.body

        names_referenced = {
            node.id
            for stmt in body_without_docstring
            for node in ast.walk(stmt)
            if isinstance(node, ast.Name)
        }
        attrs_referenced = {
            node.attr
            for stmt in body_without_docstring
            for node in ast.walk(stmt)
            if isinstance(node, ast.Attribute)
        }

        self.assertNotIn("outcome", names_referenced)
        self.assertNotIn("job_created", attrs_referenced)
        self.assertIn("provider", attrs_referenced)
        self.assertIn("job_service", attrs_referenced)


if __name__ == "__main__":
    unittest.main()
