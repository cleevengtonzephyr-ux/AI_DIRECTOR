"""
Tests -- Certificate Verification / Freshness Validation (Phase P3.55).

Covers the mission's full test matrix (items 1-23). Every test uses
MockHiggsfieldProvider exclusively; no real generation, no real
create_job(), no credits consumed.
"""

import ast
import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import RequestScopedActivationService
from agents.activation_readiness import ActivationReadinessEvaluator
from agents.certificate_verification import (
    CertificateVerificationReport,
    CertificateVerificationResult,
    verify_certificate,
)
from agents.generation_approval_gate import GenerationApprovalGate, GenerationRequest, RealGenerationAuthorization
from agents.production_activation_readiness_certificate import (
    CONTRACT_VERSION,
    ProductionActivationReadinessCertificateIssuer,
)
from agents.release_candidate_identity_lock import ReleaseCandidateIdentityLock, VIDEO_005_RELEASE_CANDIDATE
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.types import MediaReference

C = VIDEO_005_RELEASE_CANDIDATE
REAL_AVATAR_PATH = PROJECT_ROOT / "assets" / "zephyr" / "avatar" / "avatar_master.png"
REAL_FACE_PATH = PROJECT_ROOT / "assets" / "zephyr" / "references" / "mon avatar habille.png"


def _real_prompt() -> str:
    from agents.prompt_assembly_system import PromptAssemblySystem

    return PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id)


def _conforming_request(**overrides) -> GenerationRequest:
    defaults = dict(
        request_id=C.request_id, job_type=C.job_type, prompt=_real_prompt(),
        duration=C.duration, resolution=C.resolution, aspect_ratio=C.aspect_ratio,
        approved=True,
        start_image=MediaReference(role="master_avatar", source=str(REAL_AVATAR_PATH), sha256=None),
        image_references=(MediaReference(role="face_reference", source=str(REAL_FACE_PATH), sha256=None),),
        real_generation_authorization=RealGenerationAuthorization(request_id=C.request_id, authorized_by_human=True),
    )
    defaults.update(overrides)
    return GenerationRequest(**defaults)


def _issuer(available_credits=1000.0):
    provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=available_credits)
    identity_lock = ReleaseCandidateIdentityLock(C)
    gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
    activation_service = RequestScopedActivationService(gate, identity_lock)
    evaluator = ActivationReadinessEvaluator(gate, identity_lock, activation_service)
    return ProductionActivationReadinessCertificateIssuer(evaluator), gate


def _baseline_pair(issuer=None, gate=None, mission_id="mission-A", video_plan_identity="plan-v1"):
    """A reference certificate and a freshly re-issued 'current' one for
    the exact same, unchanged request -- the VALID baseline."""
    if issuer is None:
        issuer, gate = _issuer()
    request = _conforming_request()
    reference = issuer.issue(request, mission_id=mission_id, video_plan_identity=video_plan_identity)
    current = issuer.issue(request, mission_id=mission_id, video_plan_identity=video_plan_identity)
    return issuer, gate, reference, current


# 1 -- valid certificate -------------------------------------------------


class Test01_ValidCertificate(unittest.TestCase):
    def test_unchanged_state_is_valid(self):
        _, _, reference, current = _baseline_pair()
        report = verify_certificate(reference, current)
        self.assertEqual(report.result, CertificateVerificationResult.VALID)
        self.assertTrue(report.is_valid())
        self.assertEqual(report.reasons, ())
        self.assertNotEqual(report.reference_certificate_id, report.current_certificate_id)


# 2 -- request mismatch ---------------------------------------------------


class Test02_RequestMismatch(unittest.TestCase):
    def test_request_id_substitution_is_mismatch(self):
        issuer, _ = _issuer()
        reference = issuer.issue(_conforming_request(), mission_id="mission-A", video_plan_identity="plan-v1")
        other_request = _conforming_request(request_id="not-005")
        current = issuer.issue(other_request, mission_id="mission-A", video_plan_identity="plan-v1")
        report = verify_certificate(reference, current)
        self.assertEqual(report.result, CertificateVerificationResult.MISMATCH)
        self.assertTrue(any("request_id" in r for r in report.reasons))


# 3 -- mission mismatch ----------------------------------------------------


class Test03_MissionMismatch(unittest.TestCase):
    def test_mission_id_substitution_is_mismatch(self):
        issuer, _ = _issuer()
        request = _conforming_request()
        reference = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        current = issuer.issue(request, mission_id="mission-B", video_plan_identity="plan-v1")
        report = verify_certificate(reference, current)
        self.assertEqual(report.result, CertificateVerificationResult.MISMATCH)
        self.assertTrue(any("mission_id" in r for r in report.reasons))


# 4 -- prompt mismatch -------------------------------------------------


class Test04_PromptMismatch(unittest.TestCase):
    def test_prompt_change_is_mismatch(self):
        issuer, _ = _issuer()
        request = _conforming_request()
        reference = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        mutated = _conforming_request(prompt=request.prompt + " mutated")
        current = issuer.issue(mutated, mission_id="mission-A", video_plan_identity="plan-v1")
        report = verify_certificate(reference, current)
        self.assertEqual(report.result, CertificateVerificationResult.MISMATCH)
        self.assertTrue(any("prompt" in r for r in report.reasons))


# 5 -- asset mismatch -------------------------------------------------


class Test05_AssetMismatch(unittest.TestCase):
    def test_asset_change_is_mismatch(self):
        issuer, _ = _issuer()
        request = _conforming_request()
        reference = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        mutated = _conforming_request(
            start_image=MediaReference(role="master_avatar", source=str(REAL_FACE_PATH), sha256=None)
        )
        current = issuer.issue(mutated, mission_id="mission-A", video_plan_identity="plan-v1")
        report = verify_certificate(reference, current)
        self.assertEqual(report.result, CertificateVerificationResult.MISMATCH)
        self.assertTrue(any("asset" in r for r in report.reasons))


# 6 -- VideoPlan mismatch -------------------------------------------------


class Test06_VideoPlanMismatch(unittest.TestCase):
    def test_video_plan_identity_change_is_mismatch(self):
        issuer, _ = _issuer()
        request = _conforming_request()
        reference = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        current = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v2")
        report = verify_certificate(reference, current)
        self.assertEqual(report.result, CertificateVerificationResult.MISMATCH)
        self.assertTrue(any("VideoPlan" in r for r in report.reasons))


# 7 -- provider mismatch -------------------------------------------------


class Test07_ProviderMismatch(unittest.TestCase):
    def test_provider_identity_change_is_mismatch(self):
        _, _, reference, current = _baseline_pair()
        forged_current = replace(current, provider_identity="SomeOtherProvider")
        report = verify_certificate(reference, forged_current)
        self.assertEqual(report.result, CertificateVerificationResult.MISMATCH)
        self.assertTrue(any("provider identity" in r for r in report.reasons))


# 8 -- model mismatch -------------------------------------------------


class Test08_ModelMismatch(unittest.TestCase):
    def test_model_change_is_mismatch(self):
        _, _, reference, current = _baseline_pair()
        forged_current = replace(current, model="some_other_model")
        report = verify_certificate(reference, forged_current)
        self.assertEqual(report.result, CertificateVerificationResult.MISMATCH)
        self.assertTrue(any("model" in r for r in report.reasons))


# 9 -- duration mismatch -------------------------------------------------


class Test09_DurationMismatch(unittest.TestCase):
    def test_duration_change_is_mismatch(self):
        issuer, _ = _issuer()
        request = _conforming_request()
        reference = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        mutated = _conforming_request(duration=request.duration + 1)
        current = issuer.issue(mutated, mission_id="mission-A", video_plan_identity="plan-v1")
        report = verify_certificate(reference, current)
        self.assertEqual(report.result, CertificateVerificationResult.MISMATCH)
        self.assertTrue(any("duration" in r for r in report.reasons))


# 10 -- resolution mismatch -------------------------------------------------


class Test10_ResolutionMismatch(unittest.TestCase):
    def test_resolution_change_is_mismatch(self):
        _, _, reference, current = _baseline_pair()
        forged_current = replace(current, resolution="1080p")
        report = verify_certificate(reference, forged_current)
        self.assertEqual(report.result, CertificateVerificationResult.MISMATCH)
        self.assertTrue(any("resolution" in r for r in report.reasons))


# 11 -- aspect ratio mismatch -------------------------------------------------


class Test11_AspectRatioMismatch(unittest.TestCase):
    def test_aspect_ratio_change_is_mismatch(self):
        _, _, reference, current = _baseline_pair()
        forged_current = replace(current, aspect_ratio="16:9")
        report = verify_certificate(reference, forged_current)
        self.assertEqual(report.result, CertificateVerificationResult.MISMATCH)
        self.assertTrue(any("aspect_ratio" in r for r in report.reasons))


# 12 -- cost mismatch -------------------------------------------------


class Test12_CostMismatch(unittest.TestCase):
    def test_estimated_cost_change_is_mismatch(self):
        _, _, reference, current = _baseline_pair()
        forged_current = replace(current, estimated_cost=(current.estimated_cost or 0.0) + 1.0)
        report = verify_certificate(reference, forged_current)
        self.assertEqual(report.result, CertificateVerificationResult.MISMATCH)
        self.assertTrue(any("estimated cost" in r for r in report.reasons))


# 13 -- UNKNOWN evidence -------------------------------------------------


class Test13_UnknownEvidence(unittest.TestCase):
    def test_gate_level_unknown_state_never_becomes_valid(self):
        issuer, gate = _issuer()
        request = _conforming_request()
        reference = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        gate.mark_unknown(request.request_id, reason="simulated crash")
        current = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        report = verify_certificate(reference, current)
        self.assertEqual(report.result, CertificateVerificationResult.UNKNOWN)
        self.assertNotEqual(report.result, CertificateVerificationResult.VALID)


# 14 -- missing evidence -------------------------------------------------


class Test14_MissingEvidence(unittest.TestCase):
    def test_missing_video_plan_identity_is_unknown_not_valid(self):
        issuer, _ = _issuer()
        request = _conforming_request()
        reference = issuer.issue(request, mission_id="mission-A")  # no video_plan_identity
        current = issuer.issue(request, mission_id="mission-A")  # no video_plan_identity
        report = verify_certificate(reference, current)
        self.assertEqual(report.result, CertificateVerificationResult.UNKNOWN)
        self.assertTrue(any("VideoPlan" in r for r in report.reasons))

    def test_missing_estimated_cost_is_unknown_not_valid(self):
        _, _, reference, current = _baseline_pair()
        forged_current = replace(current, estimated_cost=None)
        report = verify_certificate(reference, forged_current)
        self.assertEqual(report.result, CertificateVerificationResult.UNKNOWN)
        self.assertTrue(any("estimated cost" in r for r in report.reasons))


# 15 -- immutable certificate -------------------------------------------------


class Test15_ImmutableCertificate(unittest.TestCase):
    def test_verify_never_mutates_either_certificate(self):
        _, _, reference, current = _baseline_pair()
        reference_before = reference
        current_before = current
        verify_certificate(reference, current)
        self.assertEqual(reference, reference_before)
        self.assertEqual(current, current_before)
        with self.assertRaises(FrozenInstanceError):
            reference.request_id = "tampered"  # type: ignore[misc]


# 16 -- verifier purity -------------------------------------------------


class Test16_VerifierPurity(unittest.TestCase):
    def test_verify_certificate_has_no_side_effect_on_module_state(self):
        _, _, reference, current = _baseline_pair()
        report_1 = verify_certificate(reference, current)
        report_2 = verify_certificate(reference, current)
        self.assertEqual(report_1, report_2)


# 17/18/19/20 -- cannot authorize/activate/execute/create_job ---------------


class Test17_18_19_20_CannotGrantAuthority(unittest.TestCase):
    def test_report_is_not_an_authorization_or_activation_or_approval(self):
        _, _, reference, current = _baseline_pair()
        report = verify_certificate(reference, current)
        self.assertNotIsInstance(report, RealGenerationAuthorization)
        self.assertFalse(hasattr(report, "authorized_by_human"))

    def test_module_never_calls_authority_or_execution_methods(self):
        """AST-confirms the verifier module never calls create_job(,
        .execute(, prepare_activation(, validate_activation(, consume(,
        or constructs any P2 authority-bearing symbol."""
        source = (PROJECT_ROOT / "agents" / "certificate_verification.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden_attr_calls = {
            n.func.attr for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("create_job", "execute", "prepare_activation", "validate_activation", "consume")
        }
        self.assertFalse(forbidden_attr_calls, f"forbidden call(s) found: {forbidden_attr_calls}")

        forbidden_authority_symbols = {
            "GenerationApprovalGate", "GenerationJobService", "FileCriticalSectionLock",
            "FileExecutedRequestStore", "HiggsfieldProvider", "HiggsfieldClient",
            "RealGenerationAuthorization", "RequestScopedActivationContract",
            "ControlledRealProviderActivationContract", "RequestScopedActivationService",
            "ControlledRealProviderActivationService",
        }
        constructed = {
            n.func.id for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id in forbidden_authority_symbols
        }
        self.assertFalse(constructed, f"forbidden authority construction found: {constructed}")

    def test_module_imports_no_p2_execution_mechanism(self):
        """AST-based (never a raw substring scan -- a docstring may
        legitimately NAME another module in prose without importing it,
        exactly as agents/architecture_drift_detector.py itself treats
        comment/docstring mentions as never triggering drift)."""
        source = (PROJECT_ROOT / "agents" / "certificate_verification.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

        forbidden_import_substrings = (
            "generation_job_service", "critical_section_lock", "executed_request_store",
            "generation_approval_gate", "activation_contract", "controlled_real_provider_activation",
            "higgsfield",
        )
        for module_name in imported_modules:
            for needle in forbidden_import_substrings:
                self.assertNotIn(
                    needle, module_name,
                    f"unexpected import of '{module_name}' in certificate_verification.py",
                )

    def test_no_p2_file_or_director_references_the_verifier_module(self):
        p2_files = (
            "agents/generation_approval_gate.py",
            "agents/generation_job_service.py",
            "agents/activation_contract.py",
            "agents/controlled_real_provider_activation.py",
            "agents/critical_section_lock.py",
            "agents/executed_request_store.py",
            "agents/release_candidate_identity_lock.py",
            "agents/production_activation_readiness_certificate.py",
            "integrations/higgsfield/provider.py",
            "director.py",
        )
        offenders = []
        for rel in p2_files:
            text = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
            if "certificate_verification" in text:
                offenders.append(rel)
        self.assertFalse(offenders, offenders)


# 21 -- duplicate verification -------------------------------------------------


class Test21_DuplicateVerification(unittest.TestCase):
    def test_repeated_verification_of_same_pair_is_identical(self):
        _, _, reference, current = _baseline_pair()
        reports = [verify_certificate(reference, current) for _ in range(5)]
        self.assertTrue(all(r == reports[0] for r in reports))


# 22 -- deterministic result -------------------------------------------------


class Test22_DeterministicResult(unittest.TestCase):
    def test_two_independent_issuer_instances_verify_identically(self):
        issuer_1, _ = _issuer()
        issuer_2, _ = _issuer()
        request = _conforming_request()
        reference = issuer_1.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        current = issuer_2.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        report = verify_certificate(reference, current)
        self.assertEqual(report.result, CertificateVerificationResult.VALID)


# 23 -- stale certificate behavior -------------------------------------------------


class Test23_StaleCertificateBehavior(unittest.TestCase):
    def test_readiness_result_drift_on_unchanged_artifacts_is_stale(self):
        issuer, _ = _issuer()
        request = _conforming_request()
        reference = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        current = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        drifted_value = "READY" if current.readiness_result != "READY" else "NOT_READY"
        forged_current = replace(current, readiness_result=drifted_value)
        report = verify_certificate(reference, forged_current)
        self.assertEqual(report.result, CertificateVerificationResult.STALE)
        self.assertTrue(any("readiness_result" in r for r in report.reasons))

    def test_approval_decision_drift_is_stale(self):
        _, _, reference, current = _baseline_pair()
        forged_current = replace(current, approval_decision="BLOCKED")
        report = verify_certificate(reference, forged_current)
        self.assertEqual(report.result, CertificateVerificationResult.STALE)
        self.assertTrue(any("approval_decision" in r for r in report.reasons))

    def test_stale_never_conflated_with_mismatch(self):
        """A stale certificate (same identity, different verdict) must
        never be reported as MISMATCH -- the two taxonomy buckets are
        mutually exclusive by construction."""
        issuer, _ = _issuer()
        request = _conforming_request()
        reference = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        current = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        forged_current = replace(current, readiness_result="UNKNOWN" if current.readiness_result != "UNKNOWN" else "NOT_READY")
        report = verify_certificate(reference, forged_current)
        self.assertIn(report.result, (CertificateVerificationResult.STALE, CertificateVerificationResult.UNKNOWN))
        self.assertNotEqual(report.result, CertificateVerificationResult.MISMATCH)


# Additional: structural INVALID, contract version, report shape --------


class AdditionalStructuralTests(unittest.TestCase):
    def test_contract_version_mismatch_is_invalid(self):
        _, _, reference, current = _baseline_pair()
        forged_current = replace(current, contract_version=CONTRACT_VERSION + 1)
        report = verify_certificate(reference, forged_current)
        self.assertEqual(report.result, CertificateVerificationResult.INVALID)

    def test_missing_certificate_id_is_invalid(self):
        _, _, reference, current = _baseline_pair()
        forged_current = replace(current, certificate_id="")
        report = verify_certificate(reference, forged_current)
        self.assertEqual(report.result, CertificateVerificationResult.INVALID)

    def test_report_carries_both_certificate_ids_and_issued_at(self):
        _, _, reference, current = _baseline_pair()
        report = verify_certificate(reference, current)
        self.assertIsInstance(report, CertificateVerificationReport)
        self.assertEqual(report.reference_certificate_id, reference.certificate_id)
        self.assertEqual(report.current_certificate_id, current.certificate_id)
        self.assertEqual(report.reference_issued_at, reference.issued_at)
        self.assertEqual(report.current_issued_at, current.issued_at)

    def test_report_is_frozen(self):
        _, _, reference, current = _baseline_pair()
        report = verify_certificate(reference, current)
        with self.assertRaises(FrozenInstanceError):
            report.result = CertificateVerificationResult.INVALID  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
