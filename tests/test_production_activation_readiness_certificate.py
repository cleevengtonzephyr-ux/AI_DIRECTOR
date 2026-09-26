"""
Tests -- Production Activation Readiness Certificate (Phase P3.54).

Covers the mission's full A-T test matrix. Every test uses
MockHiggsfieldProvider exclusively; no real generation, no real
create_job(), no credits consumed.
"""

import ast
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import RequestScopedActivationService
from agents.activation_readiness import ActivationReadinessEvaluator
from agents.generation_approval_gate import GenerationApprovalGate, GenerationRequest, RealGenerationAuthorization
from agents.production_activation_readiness_certificate import (
    ProductionActivationReadinessCertificate,
    ProductionActivationReadinessCertificateIssuer,
    certificate_still_matches,
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


# A -------------------------------------------------------------------


class A_CertificateCreationTests(unittest.TestCase):
    def test_certificate_created_with_expected_fields(self):
        issuer, _ = _issuer()
        cert = issuer.issue(_conforming_request(), mission_id="mission-A")
        self.assertIsInstance(cert, ProductionActivationReadinessCertificate)
        self.assertTrue(cert.certificate_id)
        self.assertEqual(cert.request_id, "005")
        self.assertEqual(cert.mission_id, "mission-A")
        self.assertEqual(cert.contract_version, 1)
        self.assertIsNotNone(cert.prompt_identity)
        self.assertTrue(cert.asset_identity)
        self.assertIn(cert.readiness_result, ("READY", "NOT_READY", "UNKNOWN"))

    def test_mission_id_optional(self):
        issuer, _ = _issuer()
        cert = issuer.issue(_conforming_request())
        self.assertIsNone(cert.mission_id)


# B/C -------------------------------------------------------------------


class BC_RequestMissionBindingTests(unittest.TestCase):
    def test_request_binding(self):
        issuer, _ = _issuer()
        cert = issuer.issue(_conforming_request(request_id="005"))
        self.assertEqual(cert.request_id, "005")

    def test_mission_binding(self):
        issuer, _ = _issuer()
        cert = issuer.issue(_conforming_request(), mission_id="mission-X")
        self.assertEqual(cert.mission_id, "mission-X")


# D/E/F -------------------------------------------------------------------


class DEF_PromptAssetVideoPlanBindingTests(unittest.TestCase):
    def test_prompt_binding(self):
        issuer, _ = _issuer()
        cert = issuer.issue(_conforming_request())
        self.assertEqual(len(cert.prompt_identity), 64)  # sha256 hex

    def test_asset_binding(self):
        issuer, _ = _issuer()
        cert = issuer.issue(_conforming_request())
        self.assertEqual(len(cert.asset_identity), 2)
        for h in cert.asset_identity:
            self.assertEqual(len(h), 64)

    def test_video_plan_binding_only_when_supplied(self):
        issuer, _ = _issuer()
        cert_without = issuer.issue(_conforming_request())
        self.assertIsNone(cert_without.video_plan_identity)
        cert_with = issuer.issue(_conforming_request(), video_plan_identity="plan-hash-abc")
        self.assertEqual(cert_with.video_plan_identity, "plan-hash-abc")


# G -------------------------------------------------------------------


class G_ImmutabilityTests(unittest.TestCase):
    def test_certificate_is_frozen(self):
        issuer, _ = _issuer()
        cert = issuer.issue(_conforming_request())
        with self.assertRaises(FrozenInstanceError):
            cert.request_id = "tampered"  # type: ignore[misc]

    def test_state_change_requires_new_certificate_id(self):
        issuer, gate = _issuer()
        request = _conforming_request()
        cert_1 = issuer.issue(request)
        gate.mark_unknown(request.request_id, reason="simulated crash")
        cert_2 = issuer.issue(request)
        self.assertNotEqual(cert_1.certificate_id, cert_2.certificate_id)
        self.assertNotEqual(cert_1.readiness_result, cert_2.readiness_result)
        # The OLD certificate is untouched.
        self.assertNotEqual(cert_1.readiness_result, "UNKNOWN")


# H -------------------------------------------------------------------


class H_StaleCertificateDetectionTests(unittest.TestCase):
    def test_unchanged_request_still_matches(self):
        issuer, _ = _issuer()
        request = _conforming_request()
        cert = issuer.issue(request)
        matches, reasons = certificate_still_matches(cert, request)
        self.assertTrue(matches)
        self.assertEqual(reasons, ())

    def test_changed_duration_is_stale(self):
        issuer, _ = _issuer()
        request = _conforming_request()
        cert = issuer.issue(request)
        mutated = _conforming_request(duration=request.duration + 1)
        matches, reasons = certificate_still_matches(cert, mutated)
        self.assertFalse(matches)
        self.assertTrue(any("duration" in r for r in reasons))


# I -------------------------------------------------------------------


class I_UnknownHandlingTests(unittest.TestCase):
    def test_unknown_request_yields_unknown_readiness_result_never_ready(self):
        issuer, gate = _issuer()
        request = _conforming_request()
        gate.mark_unknown(request.request_id, reason="simulated crash")
        cert = issuer.issue(request)
        self.assertEqual(cert.readiness_result, "UNKNOWN")
        self.assertTrue(cert.unknown_state)
        self.assertFalse(cert.is_ready())
        self.assertTrue(any("UNKNOWN" in r for r in cert.blocking_reasons))


# J/K/L/M -------------------------------------------------------------------


class JKLM_SeparationOfAuthorityTests(unittest.TestCase):
    def test_certificate_is_not_an_approval(self):
        issuer, _ = _issuer()
        cert = issuer.issue(_conforming_request())
        self.assertNotIsInstance(cert, type(None))
        # A certificate's approval_decision is a STRING snapshot, never
        # itself the GenerationApprovalDecision object the Gate uses
        # for its own authority.
        self.assertIsInstance(cert.approval_decision, str)

    def test_certificate_is_not_an_authorization(self):
        issuer, _ = _issuer()
        cert = issuer.issue(_conforming_request())
        self.assertNotIsInstance(cert, RealGenerationAuthorization)
        self.assertFalse(hasattr(cert, "authorized_by_human"))

    def test_certificate_is_not_an_activation_contract(self):
        from agents.activation_contract import RequestScopedActivationContract

        issuer, _ = _issuer()
        cert = issuer.issue(_conforming_request())
        self.assertNotIsInstance(cert, RequestScopedActivationContract)

    def test_certificate_never_reaches_create_job_or_execute(self):
        """AST-confirms the certificate module never calls create_job(
        or .execute( anywhere."""
        source = (PROJECT_ROOT / "agents" / "production_activation_readiness_certificate.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        offenders = {
            n.func.attr for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("create_job", "execute", "prepare_activation", "validate_activation", "consume")
        }
        self.assertFalse(offenders, f"forbidden call(s) found: {offenders}")

    def test_no_p2_file_references_the_certificate_module(self):
        """Confirms the certificate can never be smuggled in as
        authority: no P2-protected file imports it."""
        p2_files = (
            "agents/generation_approval_gate.py",
            "agents/generation_job_service.py",
            "agents/activation_contract.py",
            "agents/controlled_real_provider_activation.py",
            "agents/critical_section_lock.py",
            "agents/executed_request_store.py",
            "agents/release_candidate_identity_lock.py",
            "integrations/higgsfield/provider.py",
        )
        offenders = []
        for rel in p2_files:
            text = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
            if "production_activation_readiness_certificate" in text:
                offenders.append(rel)
        self.assertFalse(offenders, offenders)

    def test_director_does_not_reference_certificate_module(self):
        """Confirms this phase introduced no new entry point: director.py
        is untouched by this feature."""
        text = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8")
        self.assertNotIn("production_activation_readiness_certificate", text)


# N/O -------------------------------------------------------------------


class NO_CrossRequestCrossMissionTests(unittest.TestCase):
    def test_cross_request_substitution_rejected_by_freshness_check(self):
        issuer, _ = _issuer()
        request_a = _conforming_request()
        cert_a = issuer.issue(request_a, mission_id="mission-A")
        # A different (non-canonical) request_id -- freshness check
        # must flag the mismatch; it must never silently "still apply".
        request_b_like = _conforming_request(request_id="not-005")
        matches, reasons = certificate_still_matches(cert_a, request_b_like)
        self.assertFalse(matches)
        self.assertTrue(any("request_id" in r for r in reasons))

    def test_cross_mission_substitution_is_observability_only_never_authority(self):
        issuer, _ = _issuer()
        request = _conforming_request()
        cert_mission_a = issuer.issue(request, mission_id="mission-A")
        cert_mission_b = issuer.issue(request, mission_id="mission-B")
        # Same request, different mission_id -- readiness_result must
        # be identical; mission_id never influences the decision.
        self.assertEqual(cert_mission_a.readiness_result, cert_mission_b.readiness_result)
        self.assertEqual(cert_mission_a.approval_decision, cert_mission_b.approval_decision)
        self.assertNotEqual(cert_mission_a.mission_id, cert_mission_b.mission_id)


# P/Q/R -------------------------------------------------------------------


class PQR_ChangedArtifactsTests(unittest.TestCase):
    def test_changed_prompt_detected_as_stale(self):
        issuer, _ = _issuer()
        request = _conforming_request()
        cert = issuer.issue(request)
        mutated = _conforming_request(prompt=request.prompt + " mutated")
        matches, reasons = certificate_still_matches(cert, mutated)
        self.assertFalse(matches)
        self.assertTrue(any("prompt" in r for r in reasons))

    def test_changed_assets_detected_as_stale(self):
        issuer, _ = _issuer()
        request = _conforming_request()
        cert = issuer.issue(request)
        mutated = _conforming_request(image_references=())  # face reference removed
        matches, reasons = certificate_still_matches(cert, mutated)
        self.assertFalse(matches)
        self.assertTrue(any("asset" in r for r in reasons))

    def test_changed_video_plan_identity_detected_as_stale(self):
        issuer, _ = _issuer()
        request = _conforming_request()
        cert = issuer.issue(request, video_plan_identity="plan-v1")
        matches, reasons = certificate_still_matches(cert, request, video_plan_identity="plan-v2")
        self.assertFalse(matches)
        self.assertTrue(any("video_plan_identity" in r for r in reasons))


# S -------------------------------------------------------------------


class S_DuplicateCertificateTests(unittest.TestCase):
    def test_two_certificates_for_the_same_unchanged_request_have_distinct_ids_but_equal_content(self):
        issuer, _ = _issuer()
        request = _conforming_request()
        cert_1 = issuer.issue(request, mission_id="mission-A")
        cert_2 = issuer.issue(request, mission_id="mission-A")
        self.assertNotEqual(cert_1.certificate_id, cert_2.certificate_id)
        self.assertEqual(cert_1.readiness_result, cert_2.readiness_result)
        self.assertEqual(cert_1.prompt_identity, cert_2.prompt_identity)
        self.assertEqual(cert_1.asset_identity, cert_2.asset_identity)


# T -------------------------------------------------------------------


class T_DeterministicSnapshotTests(unittest.TestCase):
    def test_prompt_and_asset_identity_deterministic_across_two_independent_issuances(self):
        issuer_1, _ = _issuer()
        issuer_2, _ = _issuer()
        request = _conforming_request()
        cert_1 = issuer_1.issue(request)
        cert_2 = issuer_2.issue(request)
        self.assertEqual(cert_1.prompt_identity, cert_2.prompt_identity)
        self.assertEqual(cert_1.asset_identity, cert_2.asset_identity)
        self.assertEqual(cert_1.readiness_result, cert_2.readiness_result)


# Additional: no secrets, provider identity, architecture drift adjacency


class NoSecretsTests(unittest.TestCase):
    def test_evidence_references_rejects_secret_looking_keys(self):
        issuer, _ = _issuer()
        with self.assertRaises(ValueError):
            issuer.issue(_conforming_request(), evidence_references={"api_key": "irrelevant"})

    def test_provider_identity_is_descriptive_not_authoritative(self):
        issuer, _ = _issuer()
        cert = issuer.issue(_conforming_request())
        self.assertEqual(cert.provider_identity, "MockHiggsfieldProvider")


if __name__ == "__main__":
    unittest.main()
