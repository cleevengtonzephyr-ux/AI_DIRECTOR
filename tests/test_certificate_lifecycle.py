"""
Tests -- Certificate Lifecycle & Supersession Boundary (Phase P3.57).

Covers the mission's full test matrix (items 1-25). Every test uses
MockHiggsfieldProvider exclusively; no real generation, no real
create_job(), no credits consumed.
"""

import ast
import sys
import threading
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import RequestScopedActivationService
from agents.activation_readiness import ActivationReadinessEvaluator
from agents.certificate_integrity import (
    ISSUER_IDENTITY,
    IntegrityResult,
    compute_integrity_digest,
    verify_integrity,
)
from agents.certificate_lifecycle import (
    LIFECYCLE_VERSION,
    CertificateLifecycleRecord,
    CertificateLifecycleRegistry,
    CertificateLifecycleStatus,
    certificate_scope,
)
from agents.certificate_verification import CertificateVerificationResult, verify_certificate
from agents.generation_approval_gate import GenerationApprovalGate, GenerationRequest, RealGenerationAuthorization
from agents.production_activation_readiness_certificate import ProductionActivationReadinessCertificateIssuer
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


def _cert(issuer, mission_id="mission-A", **overrides):
    request = _conforming_request(**overrides.pop("request_overrides", {}))
    return issuer.issue(request, mission_id=mission_id, video_plan_identity="plan-v1")


# 1/2/3 -- first CURRENT, second CURRENT, first becomes SUPERSEDED ------


class Test01_02_03_BasicSupersession(unittest.TestCase):
    def test_first_certificate_is_current(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        c1 = _cert(issuer)
        record_1 = registry.register(c1)
        self.assertEqual(record_1.status, CertificateLifecycleStatus.CURRENT)

    def test_second_certificate_is_current_and_first_becomes_superseded(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        c1 = _cert(issuer)
        c2 = _cert(issuer)
        registry.register(c1)
        record_2 = registry.register(c2)

        self.assertEqual(record_2.status, CertificateLifecycleStatus.CURRENT)
        self.assertEqual(registry.status_of(c1.certificate_id), CertificateLifecycleStatus.SUPERSEDED)
        self.assertEqual(registry.status_of(c2.certificate_id), CertificateLifecycleStatus.CURRENT)


# 4 -- superseded certificate remains immutable --------------------------


class Test04_SupersededImmutability(unittest.TestCase):
    def test_certificate_object_and_record_stay_frozen(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        c1 = _cert(issuer)
        c2 = _cert(issuer)
        registry.register(c1)
        registry.register(c2)

        # The certificate itself was never touched by lifecycle tracking.
        self.assertEqual(c1.request_id, C.request_id)
        with self.assertRaises(FrozenInstanceError):
            c1.request_id = "tampered"  # type: ignore[misc]

        record = registry.record_for(c1.certificate_id)
        with self.assertRaises(FrozenInstanceError):
            record.status = CertificateLifecycleStatus.CURRENT  # type: ignore[misc]

    def test_superseding_does_not_change_the_certificates_own_fields(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        c1 = _cert(issuer)
        digest_before = compute_integrity_digest(c1)
        registry.register(c1)
        c2 = _cert(issuer)
        registry.register(c2)
        digest_after = compute_integrity_digest(c1)
        self.assertEqual(digest_before, digest_after)


# 5 -- superseded != invalid -----------------------------------------------


class Test05_SupersededIsNotInvalid(unittest.TestCase):
    def test_superseded_certificate_can_still_have_valid_integrity(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        c1 = _cert(issuer)
        digest = compute_integrity_digest(c1)
        registry.register(c1)
        registry.register(_cert(issuer))

        self.assertEqual(registry.status_of(c1.certificate_id), CertificateLifecycleStatus.SUPERSEDED)
        integrity_result, _ = verify_integrity(c1, digest)
        self.assertEqual(integrity_result, IntegrityResult.INTEGRITY_VALID)


# 6 -- stale != superseded --------------------------------------------------


class Test06_StaleIsNotSuperseded(unittest.TestCase):
    def test_lifecycle_current_can_coexist_with_stale_freshness(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        request = _conforming_request()
        reference = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        registry.register(reference)
        current_eval = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        drifted = "READY" if current_eval.readiness_result != "READY" else "NOT_READY"
        forged_current = replace(current_eval, readiness_result=drifted)

        freshness = verify_certificate(reference, forged_current)
        self.assertEqual(freshness.result, CertificateVerificationResult.STALE)
        # The registry was never told about this -- reference is still CURRENT.
        self.assertEqual(registry.status_of(reference.certificate_id), CertificateLifecycleStatus.CURRENT)


# 7 -- invalid != superseded ------------------------------------------------


class Test07_InvalidIsNotSuperseded(unittest.TestCase):
    def test_lifecycle_current_can_coexist_with_invalid_integrity(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        c1 = _cert(issuer)
        digest = compute_integrity_digest(c1)
        registry.register(c1)

        tampered = replace(c1, estimated_cost=(c1.estimated_cost or 0.0) + 999.0)
        integrity_result, _ = verify_integrity(tampered, digest)
        self.assertEqual(integrity_result, IntegrityResult.INTEGRITY_INVALID)
        # Registry still reports the ORIGINAL (untampered) object's status
        # as CURRENT -- lifecycle tracking is orthogonal to integrity.
        self.assertEqual(registry.status_of(c1.certificate_id), CertificateLifecycleStatus.CURRENT)


# 8/9 -- different request/mission isolation --------------------------


class Test08_09_ScopeIsolation(unittest.TestCase):
    def test_different_request_never_shares_a_lifecycle(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        c1 = issuer.issue(_conforming_request(), mission_id="mission-A", video_plan_identity="plan-v1")
        c2 = issuer.issue(_conforming_request(request_id="not-005"), mission_id="mission-A", video_plan_identity="plan-v1")
        registry.register(c1)
        registry.register(c2)
        self.assertEqual(registry.status_of(c1.certificate_id), CertificateLifecycleStatus.CURRENT)
        self.assertEqual(registry.status_of(c2.certificate_id), CertificateLifecycleStatus.CURRENT)
        self.assertNotEqual(certificate_scope(c1), certificate_scope(c2))

    def test_different_mission_never_shares_a_lifecycle(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        request = _conforming_request()
        c1 = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        c2 = issuer.issue(request, mission_id="mission-B", video_plan_identity="plan-v1")
        registry.register(c1)
        registry.register(c2)
        self.assertEqual(registry.status_of(c1.certificate_id), CertificateLifecycleStatus.CURRENT)
        self.assertEqual(registry.status_of(c2.certificate_id), CertificateLifecycleStatus.CURRENT)


# 10/11 -- current certificate lookup / missing current -----------------


class Test10_11_CurrentLookup(unittest.TestCase):
    def test_current_certificate_lookup_returns_the_latest(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        c1 = _cert(issuer)
        c2 = _cert(issuer)
        registry.register(c1)
        registry.register(c2)
        record = registry.current_record_for(certificate_scope(c2))
        self.assertEqual(record.certificate_id, c2.certificate_id)

    def test_missing_current_certificate_is_none_not_guessed(self):
        registry = CertificateLifecycleRegistry()
        self.assertIsNone(registry.current_record_for(("never-seen", None)))


# 12 -- conflicting / corrupted current certificates ----------------------


class Test12_CorruptedCurrentPointer(unittest.TestCase):
    def test_dangling_current_pointer_is_fail_closed_none(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        c1 = _cert(issuer)
        registry.register(c1)
        scope = certificate_scope(c1)
        # Simulate corrupted metadata: the pointer names an id with no
        # matching record at all.
        registry._current_by_scope[scope] = "does-not-exist"  # white-box corruption injection
        self.assertIsNone(registry.current_record_for(scope))

    def test_pointer_to_a_non_current_record_is_fail_closed_none(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        c1 = _cert(issuer)
        registry.register(c1)
        scope = certificate_scope(c1)
        # Corrupt: the record itself says SUPERSEDED but the pointer
        # still names it as current.
        registry._records[c1.certificate_id] = replace(
            registry._records[c1.certificate_id], status=CertificateLifecycleStatus.SUPERSEDED,
        )
        self.assertIsNone(registry.current_record_for(scope))


# 13 -- duplicate issuance -------------------------------------------------


class Test13_DuplicateIssuance(unittest.TestCase):
    def test_registering_the_same_certificate_twice_is_idempotent(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        c1 = _cert(issuer)
        record_1 = registry.register(c1)
        record_2 = registry.register(c1)
        self.assertEqual(record_1, record_2)
        self.assertEqual(registry.status_of(c1.certificate_id), CertificateLifecycleStatus.CURRENT)
        self.assertEqual(len(registry.history_for(certificate_scope(c1))), 1)


# 14 -- concurrent issuance -------------------------------------------------


class Test14_ConcurrentIssuance(unittest.TestCase):
    def test_concurrent_registration_never_produces_two_current_records(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        request = _conforming_request()
        c1 = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        c2 = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        scope = certificate_scope(c1)

        barrier = threading.Barrier(2)

        def _register(cert):
            barrier.wait(timeout=5)
            registry.register(cert)

        t1 = threading.Thread(target=_register, args=(c1,))
        t2 = threading.Thread(target=_register, args=(c2,))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        history = registry.history_for(scope)
        current_statuses = [r for r in history if r.status == CertificateLifecycleStatus.CURRENT]
        self.assertEqual(len(current_statuses), 1)
        self.assertEqual(len(history), 2)


# 15 -- deterministic ordering ---------------------------------------------


class Test15_DeterministicOrdering(unittest.TestCase):
    def test_history_is_ordered_by_registration_sequence(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        c1 = _cert(issuer)
        c2 = _cert(issuer)
        c3 = _cert(issuer)
        registry.register(c1)
        registry.register(c2)
        registry.register(c3)
        history = registry.history_for(certificate_scope(c1))
        self.assertEqual([r.certificate_id for r in history], [c1.certificate_id, c2.certificate_id, c3.certificate_id])
        self.assertEqual([r.registered_sequence for r in history], sorted(r.registered_sequence for r in history))


# 16/17 -- process restart / historical preservation -----------------------


class Test16_17_RestartAndHistoryPreservation(unittest.TestCase):
    def test_fresh_registry_has_no_memory_of_a_previous_one(self):
        """Documented gap (module docstring, Section 8): no persistence
        in this phase -- a new process (simulated by a new registry
        instance) never fabricates knowledge of prior certificates."""
        issuer, _ = _issuer()
        old_registry = CertificateLifecycleRegistry()
        c1 = _cert(issuer)
        old_registry.register(c1)

        new_registry = CertificateLifecycleRegistry()
        self.assertEqual(new_registry.status_of(c1.certificate_id), CertificateLifecycleStatus.UNKNOWN)
        self.assertIsNone(new_registry.current_record_for(certificate_scope(c1)))

    def test_history_within_one_process_preserves_every_certificate(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        certs = [_cert(issuer) for _ in range(4)]
        for cert in certs:
            registry.register(cert)
        history = registry.history_for(certificate_scope(certs[0]))
        self.assertEqual(len(history), 4)
        self.assertEqual({r.certificate_id for r in history}, {c.certificate_id for c in certs})


# 18 -- supersession relation -----------------------------------------------


class Test18_SupersessionRelation(unittest.TestCase):
    def test_superseded_record_points_at_its_successor(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        c1 = _cert(issuer)
        c2 = _cert(issuer)
        registry.register(c1)
        registry.register(c2)
        record_1 = registry.record_for(c1.certificate_id)
        self.assertEqual(record_1.superseded_by, c2.certificate_id)
        record_2 = registry.record_for(c2.certificate_id)
        self.assertIsNone(record_2.superseded_by)


# 19 -- UNKNOWN lifecycle ----------------------------------------------


class Test19_UnknownLifecycle(unittest.TestCase):
    def test_unregistered_certificate_id_is_unknown(self):
        registry = CertificateLifecycleRegistry()
        self.assertEqual(registry.status_of("never-registered"), CertificateLifecycleStatus.UNKNOWN)


# 20 -- corrupted lifecycle metadata (see also Test12) ---------------------


class Test20_CorruptedMetadata(unittest.TestCase):
    def test_record_missing_for_a_known_scope_pointer_is_handled_fail_closed(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        c1 = _cert(issuer)
        registry.register(c1)
        scope = certificate_scope(c1)
        del registry._records[c1.certificate_id]  # white-box corruption injection
        self.assertIsNone(registry.current_record_for(scope))
        self.assertEqual(registry.status_of(c1.certificate_id), CertificateLifecycleStatus.UNKNOWN)


# 21 -- forged certificate interaction --------------------------------------


class Test21_ForgedCertificateInteraction(unittest.TestCase):
    def test_lifecycle_registration_alone_never_proves_authenticity(self):
        """The registry has no way to distinguish an Issuer-produced
        certificate from a manually constructed one with a plausible
        certificate_id -- lifecycle status must always be combined with
        P3.56 integrity/provenance before being treated as meaningful
        (module docstring 'WHAT THIS MODULE IS NOT'). This test asserts
        that gap explicitly, exactly like P3.56 did for provenance."""
        from agents.activation_readiness import ActivationReadinessReport
        from agents.production_activation_readiness_certificate import (
            ProductionActivationReadinessCertificate,
        )

        forged = ProductionActivationReadinessCertificate(
            certificate_id="forged-but-plausible-id",
            request_id=C.request_id,
            mission_id="mission-A",
            issued_at="2026-01-01T00:00:00+00:00",
            contract_version=1,
            prompt_identity="a" * 64,
            asset_identity=("b" * 64,),
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
        registry = CertificateLifecycleRegistry()
        record = registry.register(forged)
        self.assertEqual(record.status, CertificateLifecycleStatus.CURRENT)
        # Lifecycle CURRENT status was granted purely on structure --
        # provenance must be checked separately (P3.56), never implied here.


# 22 -- altered supersession relation ---------------------------------------


class Test22_AlteredSupersessionRelation(unittest.TestCase):
    def test_record_cannot_be_mutated_to_forge_a_supersession_link(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        c1 = _cert(issuer)
        registry.register(c1)
        record = registry.record_for(c1.certificate_id)
        with self.assertRaises(FrozenInstanceError):
            record.superseded_by = "forged-successor-id"  # type: ignore[misc]

    def test_forging_a_replacement_record_outside_the_registry_does_not_affect_it(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        c1 = _cert(issuer)
        record = registry.register(c1)
        forged_copy = replace(record, superseded_by="forged-successor-id", status=CertificateLifecycleStatus.SUPERSEDED)
        # The forged copy is a detached object -- the registry's own
        # record is untouched.
        self.assertNotEqual(forged_copy, registry.record_for(c1.certificate_id))
        self.assertEqual(registry.status_of(c1.certificate_id), CertificateLifecycleStatus.CURRENT)


# 23/24/25 -- authority escalation prevention -------------------------------


class Test23_25_NoAuthorityEscalation(unittest.TestCase):
    def test_current_plus_valid_integrity_plus_valid_freshness_grants_no_authority(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        request = _conforming_request()
        reference = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        digest = compute_integrity_digest(reference)
        registry.register(reference)
        current_eval = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")

        lifecycle_status = registry.status_of(reference.certificate_id)
        integrity_result, _ = verify_integrity(reference, digest)
        freshness = verify_certificate(reference, current_eval)

        self.assertEqual(lifecycle_status, CertificateLifecycleStatus.CURRENT)
        self.assertEqual(integrity_result, IntegrityResult.INTEGRITY_VALID)
        self.assertEqual(freshness.result, CertificateVerificationResult.VALID)

        # Even with every dimension maximally positive, none of these
        # objects expose any execute/authorize/activate/create_job surface.
        for obj in (registry, registry.record_for(reference.certificate_id), lifecycle_status):
            self.assertFalse(hasattr(obj, "execute"))
            self.assertFalse(hasattr(obj, "create_job"))
            self.assertFalse(hasattr(obj, "authorize"))
            self.assertFalse(hasattr(obj, "activate"))

        self.assertNotIsInstance(registry, RealGenerationAuthorization)

    def test_module_never_calls_authority_or_execution_methods(self):
        source = (PROJECT_ROOT / "agents" / "certificate_lifecycle.py").read_text(encoding="utf-8")
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
        source = (PROJECT_ROOT / "agents" / "certificate_lifecycle.py").read_text(encoding="utf-8")
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
                    f"unexpected import of '{module_name}' in certificate_lifecycle.py",
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
            "agents/certificate_integrity.py",
            "integrations/higgsfield/provider.py",
            "director.py",
        )
        offenders = []
        for rel in p2_files:
            text = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
            if "certificate_lifecycle" in text:
                offenders.append(rel)
        self.assertFalse(offenders, offenders)


# Additional: structural robustness -----------------------------------------


class AdditionalStructuralTests(unittest.TestCase):
    def test_lifecycle_version_constant(self):
        self.assertEqual(LIFECYCLE_VERSION, 1)

    def test_register_rejects_non_certificate(self):
        registry = CertificateLifecycleRegistry()
        with self.assertRaises(TypeError):
            registry.register(object())  # type: ignore[arg-type]

    def test_certificate_scope_rejects_non_certificate(self):
        with self.assertRaises(TypeError):
            certificate_scope(object())  # type: ignore[arg-type]

    def test_record_is_the_documented_dataclass(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        record = registry.register(_cert(issuer))
        self.assertIsInstance(record, CertificateLifecycleRecord)


if __name__ == "__main__":
    unittest.main()
