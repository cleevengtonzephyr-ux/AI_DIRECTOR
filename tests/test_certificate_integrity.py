"""
Tests -- Certificate Provenance & Integrity Boundary (Phase P3.56).

Covers the mission's full test matrix (items 1-28). Every test uses
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
from agents.activation_readiness import ActivationReadinessEvaluator, ActivationReadinessReport
from agents.certificate_integrity import (
    ISSUER_IDENTITY,
    CertificateProvenanceIntegrityReport,
    IntegrityResult,
    ProvenanceResult,
    canonical_certificate_payload,
    compute_integrity_digest,
    verify_certificate_provenance_and_integrity,
    verify_integrity,
    verify_provenance,
)
from agents.certificate_verification import CertificateVerificationResult
from agents.generation_approval_gate import GenerationApprovalGate, GenerationRequest, RealGenerationAuthorization
from agents.production_activation_readiness_certificate import (
    ProductionActivationReadinessCertificate,
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


def _issuer(available_credits=1000.0, max_cost_credits_per_request=None):
    provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=available_credits)
    identity_lock = ReleaseCandidateIdentityLock(C)
    gate = GenerationApprovalGate(
        provider, identity_lock=identity_lock, max_cost_credits_per_request=max_cost_credits_per_request
    )
    activation_service = RequestScopedActivationService(gate, identity_lock)
    evaluator = ActivationReadinessEvaluator(gate, identity_lock, activation_service)
    return ProductionActivationReadinessCertificateIssuer(evaluator), gate


def _cert(issuer=None, **overrides):
    if issuer is None:
        issuer, _ = _issuer()
    request = _conforming_request()
    return issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1", **overrides)


def _manual_certificate(**overrides) -> ProductionActivationReadinessCertificate:
    """A certificate built directly, NOT via the Issuer -- Section 10."""
    defaults = dict(
        certificate_id="manually-forged-id",
        request_id=C.request_id,
        mission_id="mission-A",
        issued_at="2026-01-01T00:00:00+00:00",
        contract_version=1,
        prompt_identity="a" * 64,
        asset_identity=("b" * 64, "c" * 64),
        video_plan_identity="plan-v1",
        provider_identity="MockHiggsfieldProvider",
        model=C.job_type,
        duration=C.duration,
        resolution=C.resolution,
        aspect_ratio=C.aspect_ratio,
        estimated_cost=67.5,
        approval_decision="APPROVED",
        unknown_state=False,
        readiness_report=ActivationReadinessReport(request_id=C.request_id, technical_ready=True),
        readiness_result="READY",
        blocking_reasons=(),
        evidence_references=(),
    )
    defaults.update(overrides)
    return ProductionActivationReadinessCertificate(**defaults)


# 1/2 -- canonical / deterministic serialization -----------------------


class Test01_02_CanonicalDeterministicSerialization(unittest.TestCase):
    def test_two_independent_issuances_of_the_same_state_serialize_identically(self):
        issuer_1, _ = _issuer()
        issuer_2, _ = _issuer()
        request = _conforming_request()
        cert_1 = issuer_1.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        cert_2 = issuer_2.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        # certificate_id/issued_at legitimately differ per issuance -- align them
        # to isolate whether the REST of the payload serializes identically.
        aligned = replace(cert_2, certificate_id=cert_1.certificate_id, issued_at=cert_1.issued_at)
        self.assertEqual(canonical_certificate_payload(cert_1), canonical_certificate_payload(aligned))

    def test_repeated_serialization_of_the_same_object_is_byte_identical(self):
        cert = _cert()
        self.assertEqual(canonical_certificate_payload(cert), canonical_certificate_payload(cert))

    def test_field_order_on_the_dataclass_does_not_affect_the_payload(self):
        cert = _cert()
        payload = canonical_certificate_payload(cert)
        # sort_keys=True must have ordered top-level keys alphabetically.
        import json

        parsed = json.loads(payload)
        self.assertEqual(list(parsed.keys()), sorted(parsed.keys()))


# 3/4 -- integrity digest / valid integrity -----------------------------


class Test03_04_IntegrityDigest(unittest.TestCase):
    def test_digest_is_a_sha256_hex_string(self):
        cert = _cert()
        digest = compute_integrity_digest(cert)
        self.assertEqual(len(digest), 64)
        int(digest, 16)  # raises if not valid hex

    def test_valid_integrity_when_digest_matches(self):
        cert = _cert()
        digest = compute_integrity_digest(cert)
        result, reasons = verify_integrity(cert, digest)
        self.assertEqual(result, IntegrityResult.INTEGRITY_VALID)
        self.assertEqual(reasons, ())


# 5-13 -- altered fields ---------------------------------------------------


class Test05_13_AlteredFieldsBreakIntegrity(unittest.TestCase):
    def _assert_alteration_breaks_integrity(self, **overrides):
        cert = _cert()
        digest = compute_integrity_digest(cert)
        altered = replace(cert, **overrides)
        result, reasons = verify_integrity(altered, digest)
        self.assertEqual(result, IntegrityResult.INTEGRITY_INVALID)
        self.assertTrue(reasons)

    def test_altered_request_id(self):
        self._assert_alteration_breaks_integrity(request_id="not-005")

    def test_altered_mission_id(self):
        self._assert_alteration_breaks_integrity(mission_id="mission-forged")

    def test_altered_prompt_hash(self):
        self._assert_alteration_breaks_integrity(prompt_identity="f" * 64)

    def test_altered_asset_hash(self):
        self._assert_alteration_breaks_integrity(asset_identity=("f" * 64,))

    def test_altered_video_plan_identity(self):
        self._assert_alteration_breaks_integrity(video_plan_identity="plan-forged")

    def test_altered_cost(self):
        self._assert_alteration_breaks_integrity(estimated_cost=1.0)

    def test_altered_provider(self):
        self._assert_alteration_breaks_integrity(provider_identity="SomeOtherProvider")

    def test_altered_readiness(self):
        self._assert_alteration_breaks_integrity(readiness_result="READY_FORGED")

    def test_altered_issued_at(self):
        self._assert_alteration_breaks_integrity(issued_at="1999-01-01T00:00:00+00:00")

    def test_altered_certificate_id(self):
        self._assert_alteration_breaks_integrity(certificate_id="swapped-certificate-id")


# 14 -- altered issuer (claim, not a certificate field) ----------------


class Test14_AlteredIssuerClaim(unittest.TestCase):
    def test_wrong_claimed_issuer_is_invalid_provenance_while_integrity_stays_valid(self):
        cert = _cert()
        digest = compute_integrity_digest(cert)
        report = verify_certificate_provenance_and_integrity(
            reference=cert, current=None, claimed_issuer="SomeOtherComponent",
            expected_integrity_digest=digest,
        )
        self.assertEqual(report.provenance_result, ProvenanceResult.INVALID_PROVENANCE)
        self.assertEqual(report.integrity_result, IntegrityResult.INTEGRITY_VALID)


# 15 -- reconstructed certificate ----------------------------------------


class Test15_ReconstructedCertificate(unittest.TestCase):
    def test_content_identical_reconstruction_preserves_integrity(self):
        cert = _cert()
        digest = compute_integrity_digest(cert)
        reconstructed = replace(cert)  # new object, identical content
        self.assertIsNot(reconstructed, cert)
        result, _ = verify_integrity(reconstructed, digest)
        self.assertEqual(result, IntegrityResult.INTEGRITY_VALID)


# 16 -- manually constructed certificate (documented gap) ---------------


class Test16_ManuallyConstructedCertificate(unittest.TestCase):
    def test_manual_certificate_is_internally_self_consistent(self):
        """A manually built certificate still hashes deterministically
        -- the digest mechanism itself doesn't care about origin."""
        manual = _manual_certificate()
        digest = compute_integrity_digest(manual)
        result, _ = verify_integrity(manual, digest)
        self.assertEqual(result, IntegrityResult.INTEGRITY_VALID)

    def test_manual_certificate_with_claimed_canonical_issuer_still_passes_provenance(self):
        """DOCUMENTED GAP (module docstring, Section 5/10/19 of the
        mission): provenance here is a definitional string check, not a
        cryptographic authentication -- it cannot, by itself,
        distinguish a genuine Issuer-produced certificate from a
        manually fabricated one accompanied by a matching claim. This
        test asserts the gap explicitly rather than hiding it."""
        manual = _manual_certificate()
        result, _ = verify_provenance(ISSUER_IDENTITY)
        self.assertEqual(result, ProvenanceResult.VALID_PROVENANCE)
        # The certificate object itself carries no `issuer` field at all
        # -- provenance is never read FROM the certificate.
        self.assertFalse(hasattr(manual, "issuer"))


# 17/18 -- cross-request / cross-mission certificates --------------------


class Test17_18_CrossRequestCrossMission(unittest.TestCase):
    def test_cross_request_is_rejected_as_freshness_mismatch_even_with_valid_integrity(self):
        issuer, _ = _issuer()
        reference = _cert(issuer=issuer)
        digest = compute_integrity_digest(reference)
        other_request = _conforming_request(request_id="not-005")
        current = issuer.issue(other_request, mission_id="mission-A", video_plan_identity="plan-v1")
        report = verify_certificate_provenance_and_integrity(
            reference=reference, current=current, claimed_issuer=ISSUER_IDENTITY,
            expected_integrity_digest=digest,
        )
        self.assertEqual(report.integrity_result, IntegrityResult.INTEGRITY_VALID)
        self.assertEqual(report.freshness_result, CertificateVerificationResult.MISMATCH)
        self.assertFalse(report.is_trustworthy_and_current())

    def test_cross_mission_is_rejected_as_freshness_mismatch(self):
        issuer, _ = _issuer()
        request = _conforming_request()
        reference = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        digest = compute_integrity_digest(reference)
        current = issuer.issue(request, mission_id="mission-B", video_plan_identity="plan-v1")
        report = verify_certificate_provenance_and_integrity(
            reference=reference, current=current, claimed_issuer=ISSUER_IDENTITY,
            expected_integrity_digest=digest,
        )
        self.assertEqual(report.freshness_result, CertificateVerificationResult.MISMATCH)


# 19/20 -- integrity vs freshness separation / valid integrity + stale ---


class Test19_20_IntegrityFreshnessSeparation(unittest.TestCase):
    def test_valid_integrity_can_coexist_with_stale_freshness(self):
        issuer, _ = _issuer()
        request = _conforming_request()
        reference = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        digest = compute_integrity_digest(reference)
        current = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        drifted = "READY" if current.readiness_result != "READY" else "NOT_READY"
        forged_current = replace(current, readiness_result=drifted)
        report = verify_certificate_provenance_and_integrity(
            reference=reference, current=forged_current, claimed_issuer=ISSUER_IDENTITY,
            expected_integrity_digest=digest,
        )
        self.assertEqual(report.integrity_result, IntegrityResult.INTEGRITY_VALID)
        self.assertEqual(report.freshness_result, CertificateVerificationResult.STALE)
        self.assertFalse(report.is_trustworthy_and_current())


# 21 -- invalid integrity + apparently current certificate --------------


class Test21_InvalidIntegrityApparentlyCurrent(unittest.TestCase):
    def test_tampered_reference_never_has_freshness_evaluated(self):
        issuer, _ = _issuer()
        request = _conforming_request()
        reference = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        digest = compute_integrity_digest(reference)
        tampered_reference = replace(reference, estimated_cost=(reference.estimated_cost or 0.0) + 100.0)
        current = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        report = verify_certificate_provenance_and_integrity(
            reference=tampered_reference, current=current, claimed_issuer=ISSUER_IDENTITY,
            expected_integrity_digest=digest,
        )
        self.assertEqual(report.integrity_result, IntegrityResult.INTEGRITY_INVALID)
        self.assertIsNone(report.freshness_result)
        self.assertFalse(report.is_trustworthy_and_current())


# 22/23 -- UNKNOWN provenance / UNKNOWN integrity ------------------------


class Test22_23_UnknownProvenanceIntegrity(unittest.TestCase):
    def test_unknown_provenance_when_no_claim_supplied(self):
        result, reasons = verify_provenance(None)
        self.assertEqual(result, ProvenanceResult.UNKNOWN_PROVENANCE)
        self.assertTrue(reasons)

    def test_unknown_integrity_when_no_expected_digest_supplied(self):
        cert = _cert()
        result, reasons = verify_integrity(cert, None)
        self.assertEqual(result, IntegrityResult.UNKNOWN_INTEGRITY)
        self.assertTrue(reasons)

    def test_full_report_never_promotes_unknown_to_trustworthy(self):
        cert = _cert()
        report = verify_certificate_provenance_and_integrity(
            reference=cert, current=None, claimed_issuer=None, expected_integrity_digest=None,
        )
        self.assertEqual(report.provenance_result, ProvenanceResult.UNKNOWN_PROVENANCE)
        self.assertEqual(report.integrity_result, IntegrityResult.UNKNOWN_INTEGRITY)
        self.assertIsNone(report.freshness_result)
        self.assertFalse(report.is_trustworthy_and_current())


# 24 -- verifier purity -------------------------------------------------


class Test24_VerifierPurity(unittest.TestCase):
    def test_repeated_calls_are_identical_and_non_mutating(self):
        cert = _cert()
        digest = compute_integrity_digest(cert)
        before = cert
        report_1 = verify_certificate_provenance_and_integrity(
            reference=cert, current=None, claimed_issuer=ISSUER_IDENTITY, expected_integrity_digest=digest,
        )
        report_2 = verify_certificate_provenance_and_integrity(
            reference=cert, current=None, claimed_issuer=ISSUER_IDENTITY, expected_integrity_digest=digest,
        )
        self.assertEqual(report_1, report_2)
        self.assertEqual(cert, before)
        with self.assertRaises(FrozenInstanceError):
            cert.request_id = "tampered"  # type: ignore[misc]


# 25/26/27/28 -- no authorization/activation/execution/create_job escalation


class Test25_28_NoAuthorityEscalation(unittest.TestCase):
    def test_report_is_not_an_authorization_or_activation(self):
        cert = _cert()
        digest = compute_integrity_digest(cert)
        report = verify_certificate_provenance_and_integrity(
            reference=cert, current=None, claimed_issuer=ISSUER_IDENTITY, expected_integrity_digest=digest,
        )
        self.assertNotIsInstance(report, RealGenerationAuthorization)
        self.assertFalse(hasattr(report, "authorized_by_human"))

        from agents.activation_contract import RequestScopedActivationContract

        self.assertNotIsInstance(report, RequestScopedActivationContract)

    def test_even_maximally_trustworthy_report_grants_no_authority(self):
        """Even provenance VALID + integrity VALID + freshness VALID
        together never grant human authorization, production
        activation, provider permission, execute permission, or
        create_job permission (Section 12, P3.56 mission)."""
        issuer, _ = _issuer()
        request = _conforming_request()
        reference = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        digest = compute_integrity_digest(reference)
        current = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        report = verify_certificate_provenance_and_integrity(
            reference=reference, current=current, claimed_issuer=ISSUER_IDENTITY,
            expected_integrity_digest=digest,
        )
        # Whatever the combined verdict is, the report exposes no method
        # or attribute resembling an execution/activation capability.
        self.assertFalse(hasattr(report, "execute"))
        self.assertFalse(hasattr(report, "create_job"))
        self.assertFalse(hasattr(report, "activate"))
        self.assertFalse(hasattr(report, "authorize"))

    def test_module_never_calls_authority_or_execution_methods(self):
        source = (PROJECT_ROOT / "agents" / "certificate_integrity.py").read_text(encoding="utf-8")
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
        source = (PROJECT_ROOT / "agents" / "certificate_integrity.py").read_text(encoding="utf-8")
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
                    f"unexpected import of '{module_name}' in certificate_integrity.py",
                )

    def test_no_p2_file_or_director_references_the_module(self):
        p2_files = (
            "agents/generation_approval_gate.py",
            "agents/generation_job_service.py",
            "agents/activation_contract.py",
            "agents/controlled_real_provider_activation.py",
            "agents/critical_section_lock.py",
            "agents/executed_request_store.py",
            "agents/release_candidate_identity_lock.py",
            "agents/production_activation_readiness_certificate.py",
            "agents/certificate_verification.py",
            "integrations/higgsfield/provider.py",
            "director.py",
        )
        offenders = []
        for rel in p2_files:
            text = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
            if "certificate_integrity" in text:
                offenders.append(rel)
        self.assertFalse(offenders, offenders)


# Additional: report shape ------------------------------------------------


class AdditionalReportShapeTests(unittest.TestCase):
    def test_report_is_frozen(self):
        cert = _cert()
        digest = compute_integrity_digest(cert)
        report = verify_certificate_provenance_and_integrity(
            reference=cert, current=None, claimed_issuer=ISSUER_IDENTITY, expected_integrity_digest=digest,
        )
        self.assertIsInstance(report, CertificateProvenanceIntegrityReport)
        with self.assertRaises(FrozenInstanceError):
            report.integrity_result = IntegrityResult.INTEGRITY_INVALID  # type: ignore[misc]

    def test_fully_valid_end_to_end_report_is_trustworthy_and_current(self):
        issuer, _ = _issuer()
        request = _conforming_request()
        reference = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        digest = compute_integrity_digest(reference)
        current = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        report = verify_certificate_provenance_and_integrity(
            reference=reference, current=current, claimed_issuer=ISSUER_IDENTITY,
            expected_integrity_digest=digest,
        )
        self.assertEqual(report.provenance_result, ProvenanceResult.VALID_PROVENANCE)
        self.assertEqual(report.integrity_result, IntegrityResult.INTEGRITY_VALID)
        self.assertEqual(report.freshness_result, CertificateVerificationResult.VALID)
        self.assertTrue(report.is_trustworthy_and_current())


if __name__ == "__main__":
    unittest.main()
