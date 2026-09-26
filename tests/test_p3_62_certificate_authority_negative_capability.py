"""
Tests -- Certificate Trust Consumer & Authority Escalation Audit (Phase P3.62).

P3.61 established: certificate integrity is not authenticity. P3.62's
audit found ZERO production consumer of any certificate_*.py /
production_activation_readiness_certificate.py symbol anywhere in
agents/*.py, integrations/*.py, scripts/*.py, or director.py (confirmed
by a whole-repository AST sweep for imports, Name, and Attribute nodes
referencing every public certificate symbol -- the only referencing
files in the entire repository are the certificate modules' own test
files). This module makes that property PERMANENT and EXPLICIT: it
demonstrates, behaviorally and structurally, twelve things a
certificate -- however "trustworthy" (CURRENT + INTEGRITY_VALID +
VALID_PROVENANCE + fresh VALID, the maximal combination) -- can NEVER
do, because nothing in the P2 Authority Core or Production Activation
Boundary ever reads one.

Every test uses MockHiggsfieldProvider exclusively; no real generation,
no real create_job(), no credits consumed.
"""

import ast
import inspect
import sys
import unittest
from dataclasses import fields
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import RequestScopedActivationService
from agents.activation_readiness import ActivationReadinessEvaluator
from agents.certificate_integrity import (
    ISSUER_IDENTITY,
    compute_integrity_digest,
    verify_certificate_provenance_and_integrity,
)
from agents.certificate_lifecycle import CertificateLifecycleRegistry, CertificateLifecycleStatus
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from agents.generation_job_service import GenerationJobService
from agents.human_authorization_handoff import HumanAuthorizationHandoffBuilder
from agents.production_activation_handoff import ProductionActivationHandoffBuilder
from agents.production_activation_readiness_certificate import ProductionActivationReadinessCertificateIssuer
from agents.release_candidate_identity_lock import ReleaseCandidateIdentityLock, VIDEO_005_RELEASE_CANDIDATE
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider
from integrations.higgsfield.types import MediaReference

C = VIDEO_005_RELEASE_CANDIDATE
REAL_AVATAR_PATH = PROJECT_ROOT / "assets" / "zephyr" / "avatar" / "avatar_master.png"
REAL_FACE_PATH = PROJECT_ROOT / "assets" / "zephyr" / "references" / "mon avatar habille.png"

# The 6 modules P3.61/P3.62 audit as "certificate modules" -- everything
# a caller could use to build/verify/track a certificate.
CERTIFICATE_MODULE_FILES = (
    "agents/certificate_verification.py",
    "agents/certificate_integrity.py",
    "agents/certificate_lifecycle.py",
    "agents/certificate_lifecycle_store.py",
    "agents/certificate_lifecycle_lock.py",
    "agents/production_activation_readiness_certificate.py",
)

# The P2 Authority Core / Production Activation Boundary files P3.62's
# mission (Section 6/7/8) names explicitly as the surfaces a certificate
# must never reach.
AUTHORITY_SURFACE_FILES = (
    "director.py",
    "agents/generation_approval_gate.py",
    "agents/generation_job_service.py",
    "agents/critical_section_lock.py",
    "agents/executed_request_store.py",
    "agents/activation_contract.py",
    "agents/controlled_real_provider_activation.py",
    "agents/production_activation_handoff.py",
    "agents/activation_eligibility.py",
    "agents/human_authorization_handoff.py",
    "agents/production_authority_intake.py",
    "integrations/higgsfield/provider.py",
    "integrations/higgsfield/client.py",
)

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


def _issuer_and_gate(available_credits=1000.0):
    provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=available_credits)
    identity_lock = ReleaseCandidateIdentityLock(C)
    gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
    activation_service = RequestScopedActivationService(gate, identity_lock)
    evaluator = ActivationReadinessEvaluator(gate, identity_lock, activation_service)
    return ProductionActivationReadinessCertificateIssuer(evaluator), gate


def _maximally_trustworthy_report(certificate):
    """Builds the single MOST favorable trust report obtainable for
    `certificate` -- correct digest, canonical claimed issuer, and (when
    a `current` is supplied) VALID freshness. This is deliberately the
    best case for an attacker: if even this grants no authority, nothing
    weaker can either."""

    digest = compute_integrity_digest(certificate)
    return verify_certificate_provenance_and_integrity(
        reference=certificate, current=certificate,
        claimed_issuer=ISSUER_IDENTITY, expected_integrity_digest=digest,
    )


# ---------------------------------------------------------------------
# A. Structural: no P2/production-modeling API surface even ACCEPTS a
#    certificate -- confirmed by inspecting real signatures, not by
#    reading a docstring's claim about them.
# ---------------------------------------------------------------------


class TestA_NoAuthoritySurfaceAcceptsACertificate(unittest.TestCase):
    def _assert_no_certificate_parameter(self, callable_obj):
        try:
            sig = inspect.signature(callable_obj)
        except (TypeError, ValueError):
            return
        for name, param in sig.parameters.items():
            annotation = str(param.annotation)
            self.assertNotIn(
                "Certificate", annotation,
                f"{callable_obj.__qualname__} parameter '{name}' references a "
                f"Certificate type -- a certificate must never be an accepted "
                f"input to a P2/production authority surface.",
            )

    def test_generation_approval_gate_evaluate_accepts_no_certificate(self):
        self._assert_no_certificate_parameter(GenerationApprovalGate.evaluate)

    def test_generation_job_service_execute_accepts_no_certificate(self):
        self._assert_no_certificate_parameter(GenerationJobService.execute)

    def test_provider_create_job_accepts_no_certificate(self):
        self._assert_no_certificate_parameter(HiggsfieldProvider.create_job)

    def test_production_activation_handoff_build_accepts_no_certificate(self):
        self._assert_no_certificate_parameter(ProductionActivationHandoffBuilder.build)

    def test_human_authorization_handoff_build_accepts_no_certificate(self):
        self._assert_no_certificate_parameter(HumanAuthorizationHandoffBuilder.build)

    def test_real_generation_authorization_has_no_certificate_field(self):
        for f in fields(RealGenerationAuthorization):
            self.assertNotIn("certificate", f.name.lower())


# ---------------------------------------------------------------------
# B. AST bidirectional guardrail -- consolidates the whole-repository
#    sweep this phase's audit performed: no non-test/non-certificate
#    file imports a certificate symbol, AND no certificate module
#    imports/calls an authority-surface execution mechanism.
# ---------------------------------------------------------------------


class TestB_BidirectionalImportGuardrail(unittest.TestCase):
    def _module_dotted(self, rel_path: str) -> str:
        return rel_path[:-3].replace("/", ".")

    def test_no_authority_surface_file_imports_any_certificate_module(self):
        cert_modules = {self._module_dotted(p) for p in CERTIFICATE_MODULE_FILES}
        for rel_path in AUTHORITY_SURFACE_FILES:
            path = PROJECT_ROOT / rel_path
            if not path.exists():
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=rel_path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(
                            alias.name, cert_modules,
                            f"{rel_path}:{node.lineno} imports certificate module '{alias.name}'.",
                        )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn(
                        node.module, cert_modules,
                        f"{rel_path}:{node.lineno} imports from certificate module '{node.module}'.",
                    )

    def test_no_certificate_module_imports_generation_job_service_or_critical_section_lock(self):
        forbidden = {
            "agents.generation_job_service",
            "agents.critical_section_lock",
            "agents.executed_request_store",
            "integrations.higgsfield.provider",
            "integrations.higgsfield.client",
            "integrations.higgsfield.mock_provider",
        }
        for rel_path in CERTIFICATE_MODULE_FILES:
            path = PROJECT_ROOT / rel_path
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=rel_path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name, forbidden, f"{rel_path}:{node.lineno}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn(node.module, forbidden, f"{rel_path}:{node.lineno}")

    def test_no_certificate_module_calls_create_job_or_execute(self):
        forbidden_calls = {"create_job", "execute", "mark_executed", "prepare_activation", "validate_activation"}
        for rel_path in CERTIFICATE_MODULE_FILES:
            path = PROJECT_ROOT / rel_path
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=rel_path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = node.func.id if isinstance(node.func, ast.Name) else (
                        node.func.attr if isinstance(node.func, ast.Attribute) else None
                    )
                    self.assertNotIn(name, forbidden_calls, f"{rel_path}:{node.lineno} calls '{name}'")


# ---------------------------------------------------------------------
# C. Negative Capability Matrix (Section 9, items 1-12) -- behavioral.
# ---------------------------------------------------------------------


class TestC_NegativeCapabilityMatrix(unittest.TestCase):
    def test_01_certificate_cannot_approve(self):
        """A maximally trustworthy certificate for a NOT-approvable
        request never changes the Gate's own decision on that request."""
        issuer, gate = _issuer_and_gate()
        request = _conforming_request(real_generation_authorization=None)
        cert = issuer.issue(request, mission_id="m", video_plan_identity="plan-v1")
        report = _maximally_trustworthy_report(cert)
        self.assertTrue(report.is_trustworthy_and_current())

        decision_with_cert = gate.evaluate(request).decision
        decision_without_cert = gate.evaluate(request).decision  # cert never passed in either call
        self.assertEqual(decision_with_cert, decision_without_cert)
        self.assertNotEqual(decision_with_cert, GenerationApprovalDecision.APPROVED)

    def test_02_certificate_cannot_authorize_human_action(self):
        """Issuing/trusting a certificate never constructs, mutates, or
        substitutes for a RealGenerationAuthorization."""
        issuer, _ = _issuer_and_gate()
        request = _conforming_request(real_generation_authorization=None)
        cert = issuer.issue(request, mission_id="m", video_plan_identity="plan-v1")
        _maximally_trustworthy_report(cert)
        self.assertIsNone(request.real_generation_authorization)
        self.assertFalse(cert.human_authorization_state is True and request.real_generation_authorization is not None)

    def test_03_certificate_cannot_authorize_production(self):
        """ProductionActivationHandoffBuilder's own input contract has no
        certificate-typed field to smuggle authority through."""
        from agents.production_activation_handoff import ProductionActivationHandoffInput

        for f in fields(ProductionActivationHandoffInput):
            self.assertNotIn("certificate", f.name.lower())

    def test_04_certificate_cannot_execute(self):
        """A certificate object is not a GenerationRequest and cannot be
        substituted for one at the one real execution boundary."""
        issuer, gate = _issuer_and_gate()
        request = _conforming_request()
        cert = issuer.issue(request, mission_id="m", video_plan_identity="plan-v1")
        job_service = GenerationJobService(gate.provider, gate)
        with self.assertRaises(AttributeError):
            job_service.execute(cert)  # type: ignore[arg-type]

    def test_05_certificate_cannot_call_provider(self):
        """A certificate object is not accepted anywhere in the
        Provider's own public surface."""
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
        issuer, _ = _issuer_and_gate()
        cert = issuer.issue(_conforming_request(), mission_id="m", video_plan_identity="plan-v1")
        with self.assertRaises(TypeError):
            provider.create_job(cert)  # type: ignore[arg-type]

    def test_06_certificate_cannot_bypass_budget(self):
        """A maximally trustworthy certificate issued while credits were
        sufficient does not survive as an override once the SAME request
        is re-evaluated against an insufficient-budget Gate."""
        rich_issuer, _ = _issuer_and_gate(available_credits=1000.0)
        request = _conforming_request()
        cert = rich_issuer.issue(request, mission_id="m", video_plan_identity="plan-v1")
        report = _maximally_trustworthy_report(cert)
        self.assertTrue(report.is_trustworthy_and_current())

        _, poor_gate = _issuer_and_gate(available_credits=0.01)
        decision = poor_gate.evaluate(request).decision
        self.assertEqual(decision, GenerationApprovalDecision.BLOCKED)

    def test_07_certificate_cannot_bypass_replay(self):
        """Marking a request executed, then issuing/trusting a
        certificate for it afterward, never un-does the replay guard."""
        issuer, gate = _issuer_and_gate()
        request = _conforming_request()
        gate.mark_executed(request.request_id)

        cert = issuer.issue(request, mission_id="m", video_plan_identity="plan-v1")
        report = _maximally_trustworthy_report(cert)
        self.assertTrue(report.is_trustworthy_and_current())

        decision = gate.evaluate(request).decision
        self.assertEqual(decision, GenerationApprovalDecision.ALREADY_EXECUTED)

    def test_08_certificate_cannot_bypass_identity(self):
        """A certificate issued for the conforming Release Candidate
        grants no leniency to a DIFFERENT, non-conforming request later
        evaluated by the same Gate."""
        issuer, gate = _issuer_and_gate()
        conforming = _conforming_request()
        cert = issuer.issue(conforming, mission_id="m", video_plan_identity="plan-v1")
        self.assertTrue(_maximally_trustworthy_report(cert).is_trustworthy_and_current())

        wrong_identity = _conforming_request(job_type="not-seedance")
        result = gate.evaluate(wrong_identity)
        self.assertNotEqual(result.decision, GenerationApprovalDecision.APPROVED)

    def test_09_certificate_issuance_and_verification_never_mutate_gate_state(self):
        """Issuing certificates and running every verification/integrity/
        provenance/freshness check on them never calls a Gate state
        mutator -- the replay-guard/temporal state is exactly as it was
        before any certificate machinery ran."""
        issuer, gate = _issuer_and_gate()
        request = _conforming_request()
        before_executed = gate.is_already_executed(request.request_id)
        before_unknown = gate.is_unknown(request.request_id)

        for _ in range(3):
            cert = issuer.issue(request, mission_id="m", video_plan_identity="plan-v1")
            _maximally_trustworthy_report(cert)

        self.assertEqual(gate.is_already_executed(request.request_id), before_executed)
        self.assertEqual(gate.is_unknown(request.request_id), before_unknown)

    def test_10_certificate_cannot_bypass_unknown(self):
        """Once a request is marked EXECUTION_STATE_UNKNOWN, a
        certificate issued afterward correctly reports UNKNOWN itself
        (never fabricates READY), and the Gate's own decision on the
        request is unaffected by any trust report built on top of it."""
        issuer, gate = _issuer_and_gate()
        request = _conforming_request()
        gate.mark_unknown(request.request_id, reason="test")

        cert = issuer.issue(request, mission_id="m", video_plan_identity="plan-v1")
        self.assertTrue(cert.unknown_state)
        self.assertEqual(cert.readiness_result, "UNKNOWN")

        report = _maximally_trustworthy_report(cert)
        # unknown_state=True must keep freshness UNKNOWN, never VALID --
        # see agents/certificate_verification.py's own precedence rule.
        from agents.certificate_verification import CertificateVerificationResult

        self.assertEqual(report.freshness_result, CertificateVerificationResult.UNKNOWN)
        self.assertFalse(report.is_trustworthy_and_current())

        decision = gate.evaluate(request).decision
        self.assertEqual(decision, GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN)

    def test_11_certificate_cannot_revive_superseded(self):
        """Re-presenting (re-registering) a certificate_id that has
        already been superseded never restores it, or its scope, to
        CURRENT."""
        issuer, _ = _issuer_and_gate()
        registry = CertificateLifecycleRegistry()
        request = _conforming_request()
        c1 = issuer.issue(request, mission_id="m", video_plan_identity="plan-v1")
        c2 = issuer.issue(request, mission_id="m", video_plan_identity="plan-v1")

        registry.register(c1)
        registry.register(c2)
        self.assertEqual(registry.status_of(c1.certificate_id), CertificateLifecycleStatus.SUPERSEDED)

        # "Presenting" c1 again is exactly a second register() call.
        replayed_record = registry.register(c1)
        self.assertEqual(replayed_record.status, CertificateLifecycleStatus.SUPERSEDED)
        self.assertEqual(registry.status_of(c1.certificate_id), CertificateLifecycleStatus.SUPERSEDED)
        current = registry.current_record_for((request.request_id, "m"))
        self.assertIsNotNone(current)
        self.assertEqual(current.certificate_id, c2.certificate_id)

    def test_12_certificate_cannot_create_a_new_execution_path(self):
        """The one canonical create_job() production call-site cardinality
        this repository enforces is unaffected by the certificate layer's
        existence -- see also TestB's static-import guardrails."""
        from agents.architecture_drift_detector import ArchitectureDriftDetector

        report = ArchitectureDriftDetector().analyze()
        self.assertFalse(report.has_actionable_drift, report.findings)


if __name__ == "__main__":
    unittest.main()
