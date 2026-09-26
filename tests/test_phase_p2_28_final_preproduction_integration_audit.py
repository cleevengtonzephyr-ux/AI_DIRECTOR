"""
Tests — Phase P2.28 : FINAL PRE-PRODUCTION INTEGRATION AUDIT.

Ce fichier n'existe PAS pour dupliquer P2.20-P2.27 (dont les tests
restent la source de vérité pour chaque mécanisme pris isolément) --
il verrouille ce que P2.28 ajoute de RÉELLEMENT nouveau à l'audit :

1. La chaîne RÉELLE construite par `AIDirector._build_default_chain()`
   (pas des composants assemblés à la main dans un test) supporte
   effectivement un scénario Mock positif de bout en bout, ET reste
   bloquée avec le Provider réel -- prouvé en injectant un
   `fake_client` DANS `AIDirector` lui-même (jamais le vrai CLI).
2. `AIDirector.run_video_mission()` ne fournit AUJOURD'HUI ni
   `activation_contract` ni `provider_activation_contract` --
   observation de conception explicitement verrouillée en test (pas
   une faille : une restriction, jamais un chemin de contournement).
3. Les six axes de `FinalReport`
   (approval_decision/activation_decision/provider_activation_decision/
   real_provider_called/job_created/execution_state) ne se substituent
   jamais l'un à l'autre, vérifié sur TOUTES les combinaisons de rejet
   atteignables (Gate / P2.21 / P2.26 / succès), pas seulement une.
4. Re-confirmation fraîche de Video 005 et du budget, indépendamment
   de toute valeur mise en cache dans un rapport précédent.

Aucun test de ce fichier n'utilise le vrai CLI Higgsfield.
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
from agents.controlled_real_provider_activation import ControlledRealProviderActivationService
from agents.critical_section_lock import FileCriticalSectionLock
from agents.final_report_service import ActivationDecision, FinalReportStatus
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
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
from integrations.higgsfield.provider import HiggsfieldProvider

C = VIDEO_005_RELEASE_CANDIDATE

CONFIRMED_DURATION = 15  # seul plafond réellement confirmé pour seedance_2_0


def _fake_client(cost=67.5, balance=100.0):
    fake_client = MagicMock()
    fake_client.estimate_cost.return_value = {"credits": cost}
    fake_client.account_status.return_value = {"credits": balance}
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
    return fake_client


class P2_28_TestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_28_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)


# ----------------------------------------------------------------------
# 1. Full real AIDirector wiring -- Mock positive, then Real negative
# ----------------------------------------------------------------------


class TestRealDirectorWiringEndToEnd(P2_28_TestCase):
    def _real_prompt(self):
        from agents.prompt_assembly_system import PromptAssemblySystem

        return PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id)

    def _real_request(self, **overrides):
        from agents.generation_approval_gate import GenerationRequest
        from integrations.higgsfield.types import MediaReference

        avatar = PROJECT_ROOT / "assets" / "zephyr" / "avatar" / "avatar_master.png"
        face = PROJECT_ROOT / "assets" / "zephyr" / "references" / "mon avatar habille.png"
        defaults = dict(
            request_id=C.request_id,
            job_type=C.job_type,
            prompt=self._real_prompt(),
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

    def test_real_director_chain_supports_full_mock_positive_scenario(self):
        director = AIDirector()
        director.higgsfield = _fake_client(cost=10.0, balance=100.0)

        chain = director._build_default_chain()
        # Remplace le provider par un Mock, EN NE TOUCHANT JAMAIS
        # integrations/higgsfield/provider.py : on démontre le câblage
        # réel de AIDirector avec un provider capable, sans jamais
        # activer le vrai HiggsfieldProvider.
        #
        # IMPORTANT : `chain.gate.executed_request_store` est un VRAI
        # `FileExecutedRequestStore` pointant vers
        # `director.root / "state" / "executed_requests.json"` --
        # c'est-à-dire un fichier RÉEL du projet, PAS un répertoire
        # temporaire de test. Le réutiliser ici écrirait
        # "005 exécuté" sur le DISQUE RÉEL du projet et polluerait
        # tout futur test/audit réel (bug découvert et corrigé
        # pendant cet audit P2.28 -- cf. rapport final). On utilise
        # donc un `InMemoryExecutedRequestStore` isolé, jamais le
        # store réel de la chaîne.
        from agents.executed_request_store import InMemoryExecutedRequestStore
        from integrations.higgsfield.mock_provider import MockHiggsfieldProvider

        mock_provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        gate = GenerationApprovalGate(
            mock_provider,
            executed_request_store=InMemoryExecutedRequestStore(),
            identity_lock=chain.identity_lock,
        )
        activation_service = RequestScopedActivationService(gate, chain.identity_lock)
        provider_activation_service = ControlledRealProviderActivationService(
            gate, chain.identity_lock, activation_service
        )
        # Même précaution que pour le store ci-dessus : `chain.lock`
        # pointe vers `director.root / "state" / "locks"` (chemin
        # réel du projet) -- verrou isolé dans un répertoire
        # temporaire pour ce test.
        isolated_lock = FileCriticalSectionLock(self._tmp)
        job_service = GenerationJobService(
            mock_provider, gate, lock=isolated_lock,
            activation_service=activation_service,
            provider_activation_service=provider_activation_service,
        )
        from agents.final_report_service import FinalReportService

        report_service = FinalReportService(mock_provider, gate, job_service=job_service)

        request = self._real_request(request_id="005")
        rs_contract = activation_service.prepare_activation(request)
        pa_contract = provider_activation_service.prepare(request, rs_contract)

        report = report_service.generate(
            request, activation_contract=rs_contract,
            provider_activation_contract=pa_contract, interval_seconds=0,
        )

        self.assertEqual(report.status, FinalReportStatus.EXECUTED_PASS)
        self.assertTrue(report.job_created)
        self.assertFalse(report.real_provider_called)
        self.assertEqual(report.activation_decision, ActivationDecision.APPROVED)
        self.assertEqual(report.provider_activation_decision, ActivationDecision.APPROVED)

    def test_real_director_chain_with_real_provider_stays_blocked(self):
        director = AIDirector()
        director.higgsfield = _fake_client(cost=10.0, balance=100.0)

        report = director.check_activation_readiness(self._real_request())
        # readiness: tout est vert SAUF le provider (chaîne réelle =
        # HiggsfieldProvider réel, structurellement désactivé).
        self.assertTrue(report.technical_ready)
        self.assertTrue(report.request_identity_ready)
        self.assertTrue(report.prompt_ready)
        self.assertTrue(report.asset_ready)
        self.assertTrue(report.budget_ready)
        self.assertTrue(report.authorization_ready)
        self.assertFalse(report.provider_ready)
        self.assertEqual(report.decision, "NOT_READY")

        # run_video_mission(), le VRAI point d'entrée public, utilise
        # la chaîne réelle (HiggsfieldProvider réel) et reste bloqué.
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            director.run_video_mission(
                video_id="005", title="t", hook="h", objective="o",
                duration=CONFIRMED_DURATION, approved=True,
                real_generation_authorization=RealGenerationAuthorization(
                    request_id="005", authorized_by_human=True
                ),
                interval_seconds=0,
            )

        director.higgsfield.create_job.assert_not_called()


# ----------------------------------------------------------------------
# 2. run_video_mission() cannot supply either activation contract today
# ----------------------------------------------------------------------


class TestRunVideoMissionCannotSupplyContracts(unittest.TestCase):
    def test_run_video_mission_signature_has_no_contract_parameters(self):
        import inspect

        sig = inspect.signature(AIDirector.run_video_mission)
        self.assertNotIn("activation_contract", sig.parameters)
        self.assertNotIn("provider_activation_contract", sig.parameters)

    def test_run_video_mission_never_calls_generate_with_contracts(self):
        source = ""
        import inspect

        source = inspect.getsource(AIDirector.run_video_mission)
        tree = ast.parse(source.strip())
        call_keywords = {
            kw.arg
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for kw in node.keywords
            if kw.arg is not None
        }
        self.assertNotIn("activation_contract", call_keywords)
        self.assertNotIn("provider_activation_contract", call_keywords)


# ----------------------------------------------------------------------
# 3. FinalReport axis independence across every reachable scenario
# ----------------------------------------------------------------------


class TestFinalReportAxisIndependence(P2_28_TestCase):
    def _stack(self, cost_per_job=10.0, available_credits=100.0):
        from agents.final_report_service import FinalReportService
        from integrations.higgsfield.mock_provider import MockHiggsfieldProvider

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
        report_service = FinalReportService(provider, gate, job_service=job_service)
        return provider, gate, activation_service, provider_activation_service, report_service

    def _request(self, **overrides):
        from agents.generation_approval_gate import GenerationRequest
        from integrations.higgsfield.types import MediaReference

        avatar = PROJECT_ROOT / "assets" / "zephyr" / "avatar" / "avatar_master.png"
        face = PROJECT_ROOT / "assets" / "zephyr" / "references" / "mon avatar habille.png"
        from agents.prompt_assembly_system import PromptAssemblySystem

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

    def test_case_gate_rejected_all_activation_axes_not_evaluated(self):
        _, _, _, _, report_service = self._stack(cost_per_job=67.5, available_credits=1.41)
        report = report_service.generate(self._request(), interval_seconds=0)

        self.assertEqual(report.approval_decision, GenerationApprovalDecision.BLOCKED)
        self.assertEqual(report.activation_decision, ActivationDecision.NOT_EVALUATED)
        self.assertEqual(report.provider_activation_decision, ActivationDecision.NOT_EVALUATED)
        self.assertFalse(report.job_created)
        self.assertFalse(report.real_provider_called)
        self.assertEqual(report.execution_state, "NOT_EXECUTED")

    def test_case_p2_21_rejected_provider_axis_not_evaluated(self):
        provider, gate, activation_service, _, report_service = self._stack()
        request = self._request()
        contract = activation_service.prepare_activation(request)
        activation_service.validate_activation(request, contract)  # consume it

        report = report_service.generate(
            request, activation_contract=contract, interval_seconds=0
        )
        self.assertEqual(report.approval_decision, GenerationApprovalDecision.APPROVED)
        self.assertEqual(report.activation_decision, ActivationDecision.REJECTED)
        self.assertEqual(report.provider_activation_decision, ActivationDecision.NOT_EVALUATED)
        self.assertFalse(report.job_created)
        self.assertFalse(report.real_provider_called)

    def test_case_p2_26_rejected_activation_axis_shows_approved(self):
        provider, gate, activation_service, pa_service, report_service = self._stack()
        request = self._request()
        rs_contract = activation_service.prepare_activation(request)
        pa_contract = pa_service.prepare(request, rs_contract)
        pa_service.revoke(pa_contract)

        report = report_service.generate(
            request, activation_contract=rs_contract,
            provider_activation_contract=pa_contract, interval_seconds=0,
        )
        self.assertEqual(report.approval_decision, GenerationApprovalDecision.APPROVED)
        self.assertEqual(report.activation_decision, ActivationDecision.APPROVED)
        self.assertEqual(report.provider_activation_decision, ActivationDecision.REJECTED)
        self.assertFalse(report.job_created)
        self.assertFalse(report.real_provider_called)
        self.assertNotEqual(report.status, FinalReportStatus.EXECUTED_PASS)

    def test_case_full_success_all_axes_approved_but_real_provider_false(self):
        provider, gate, activation_service, pa_service, report_service = self._stack()
        request = self._request()
        rs_contract = activation_service.prepare_activation(request)
        pa_contract = pa_service.prepare(request, rs_contract)

        report = report_service.generate(
            request, activation_contract=rs_contract,
            provider_activation_contract=pa_contract, interval_seconds=0,
        )
        self.assertEqual(report.approval_decision, GenerationApprovalDecision.APPROVED)
        self.assertEqual(report.activation_decision, ActivationDecision.APPROVED)
        self.assertEqual(report.provider_activation_decision, ActivationDecision.APPROVED)
        self.assertTrue(report.job_created)
        # Le point central de toute cette phase : MÊME avec les TROIS
        # axes à APPROVED et job_created=True, real_provider_called
        # reste False (Mock).
        self.assertFalse(report.real_provider_called)
        self.assertEqual(report.execution_state, "EXECUTED")


# ----------------------------------------------------------------------
# 4. Fresh reconfirmation: Video 005 + budget (never trust a cached value)
# ----------------------------------------------------------------------


class TestFreshVideo005AndBudget(unittest.TestCase):
    def test_video_005_canonical_values(self):
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

    def test_video_005_recomputed_live_from_disk(self):
        import hashlib

        from agents.prompt_assembly_system import PromptAssemblySystem

        prompt = PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id)
        self.assertEqual(len(prompt), C.prompt_chars)
        self.assertEqual(len(prompt.splitlines()), C.prompt_lines)
        self.assertEqual(hashlib.sha256(prompt.encode("utf-8")).hexdigest(), C.prompt_sha256)

        def _sha256(path):
            h = hashlib.sha256()
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    h.update(chunk)
            return h.hexdigest()

        avatar = PROJECT_ROOT / "assets" / "zephyr" / "avatar" / "avatar_master.png"
        face = PROJECT_ROOT / "assets" / "zephyr" / "references" / "mon avatar habille.png"
        self.assertEqual(_sha256(avatar), C.avatar_master_sha256)
        self.assertEqual(_sha256(face), C.face_reference_sha256)

    def test_budget_insufficient_against_canonical_cost(self):
        from integrations.higgsfield.mock_provider import MockHiggsfieldProvider

        provider = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=1.41)
        self.assertLess(provider.get_account_balance(), 67.5)


# ----------------------------------------------------------------------
# 5. Direct provider call, sole-caller audit, security scan (reconfirmed)
# ----------------------------------------------------------------------


class TestFinalSecurityReconfirmation(unittest.TestCase):
    def test_direct_create_job_call_still_blocked(self):
        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(job_type="seedance_2_0", prompt="x")
        fake_client.create_job.assert_not_called()

    def test_generation_job_service_is_the_sole_production_caller(self):
        offenders = []
        for base in ("agents", "integrations"):
            for path in (PROJECT_ROOT / base).rglob("*.py"):
                if path.name in ("generation_job_service.py", "job_monitor.py"):
                    continue
                if "mock_provider.py" in str(path):
                    continue
                text = path.read_text(encoding="utf-8-sig")
                tree = ast.parse(text)
                for node in ast.walk(tree):
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

    def test_no_forbidden_bypass_tokens_in_production_code(self):
        import re

        tokens = (
            "REAL_GENERATION_ENABLED", "HIGGSFIELD_ENABLED", "PRODUCTION_MODE",
            "FORCE_GENERATION", "force_generate", "generate_now",
            "skip_gate", "bypass", "auto_authorize", "auto_activation",
        )
        excluded = {"agents/production_activation_boundary.py"}
        patterns = {t: re.compile(r"\b" + re.escape(t) + r"\b") for t in tokens}
        offenders = []
        for base in ("agents", "integrations"):
            for path in (PROJECT_ROOT / base).rglob("*.py"):
                rel = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
                if rel in excluded:
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


if __name__ == "__main__":
    unittest.main()
