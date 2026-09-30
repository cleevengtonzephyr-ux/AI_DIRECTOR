"""
Tests -- Readiness Data Integrity & Scope-Binding Hardening (Phase P3.72).

Permanent guardrails for:
- ActivationReadinessReport immutability as it really is (shallow
  frozen dataclass, List[str] reason fields) and the guarantee that
  matters: any post-issuance mutation is DETECTED by integrity, never
  able to change the report's `decision`.
- request_id / mission_id / video_plan_identity scope binding across
  verification, integrity, and lifecycle.
- P3.72 fix 1: a certificate embedding ANOTHER request's readiness
  report is structurally INVALID (was VALID + INTEGRITY_VALID).
- P3.72 fix 2: the lifecycle store refuses to persist a record its own
  reader would reject (was: one bad write poisoned the whole file).

MockHiggsfieldProvider only -- no real create_job(), no credits.
"""

import copy
import json
import shutil
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.real_provider_path_fixtures import FIXTURE_MAX_COST_CREDITS_PER_REQUEST
from agents.certificate_integrity import (
    ISSUER_IDENTITY,
    IntegrityResult,
    compute_integrity_digest,
    verify_certificate_provenance_and_integrity,
    verify_integrity,
)
from agents.certificate_lifecycle import (
    CertificateLifecycleRecord,
    CertificateLifecycleRegistry,
    CertificateLifecycleStatus,
    certificate_scope,
)
from agents.certificate_lifecycle_store import FileCertificateLifecycleStore
from agents.certificate_verification import CertificateVerificationResult, verify_certificate
from tests.test_certificate_integrity import C, _conforming_request, _issuer

R = CertificateVerificationResult


def _issue(request_id=None, mission_id="M-A", video_plan_identity="VP-A", issuer=None):
    issuer = issuer or _issuer()[0]
    request = _conforming_request() if request_id is None else _conforming_request(request_id=request_id)
    return issuer.issue(request, mission_id=mission_id, video_plan_identity=video_plan_identity)


class _TempDir(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="p372_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)


# ----------------------------------------------------------------------
# ActivationReadinessReport -- immutability vs detectability
# ----------------------------------------------------------------------


class TestReadinessReportImmutability(unittest.TestCase):
    def test_scalar_fields_of_report_and_certificate_are_frozen(self):
        cert = _issue()
        for obj, name, value in (
            (cert.readiness_report, "request_id", "006"),
            (cert.readiness_report, "provider_ready", True),
            (cert, "request_id", "006"),
            (cert, "mission_id", "M-B"),
            (cert, "video_plan_identity", "VP-B"),
            (cert, "readiness_report", None),
        ):
            with self.subTest(field=name), self.assertRaises(FrozenInstanceError):
                setattr(obj, name, value)

    def test_reason_list_mutation_never_changes_decision(self):
        cert = _issue()
        decision = cert.readiness_report.decision
        cert.readiness_report.activation_reasons.clear()
        cert.readiness_report.technical_reasons.append("injected")
        self.assertEqual(cert.readiness_report.decision, decision)

    def test_every_reason_list_mutation_after_digest_is_integrity_invalid(self):
        for mutate in (
            lambda rep: rep.provider_reasons.append("injected"),
            lambda rep: rep.activation_reasons.clear(),
            lambda rep: rep.technical_reasons.insert(0, "injected"),
        ):
            cert = _issue()
            self.assertTrue(cert.readiness_report.activation_reasons)  # no contract supplied -> non-empty
            digest = compute_integrity_digest(cert)
            mutate(cert.readiness_report)
            self.assertEqual(verify_integrity(cert, digest)[0], IntegrityResult.INTEGRITY_INVALID)

    def test_returned_alias_mutation_is_integrity_invalid(self):
        cert = _issue()
        digest = compute_integrity_digest(cert)
        alias = cert.readiness_report.provider_reasons
        alias.append("via alias")
        self.assertEqual(verify_integrity(cert, digest)[0], IntegrityResult.INTEGRITY_INVALID)

    def test_all_reasons_is_a_defensive_copy(self):
        cert = _issue()
        digest = compute_integrity_digest(cert)
        cert.readiness_report.all_reasons.append("never stored")
        self.assertEqual(verify_integrity(cert, digest)[0], IntegrityResult.INTEGRITY_VALID)

    def test_deepcopy_is_independent_and_digest_identical(self):
        cert = _issue()
        digest = compute_integrity_digest(cert)
        clone = copy.deepcopy(cert)
        self.assertEqual(compute_integrity_digest(clone), digest)
        clone.readiness_report.provider_reasons.append("clone only")
        self.assertEqual(verify_integrity(cert, digest)[0], IntegrityResult.INTEGRITY_VALID)


# ----------------------------------------------------------------------
# Cross-scope matrix (request / mission / video plan)
# ----------------------------------------------------------------------


class TestCrossScopeMatrix(unittest.TestCase):
    def test_matrix(self):
        issuer_a, _ = _issuer()
        issuer_b, _ = _issuer()
        reference = _issue(issuer=issuer_a)
        rows = (
            ("A A A A", _issue(issuer=issuer_a), R.VALID),
            ("A B A A", _issue(request_id="006", issuer=issuer_b), R.MISMATCH),
            ("A A B A", _issue(mission_id="M-B", issuer=issuer_a), R.MISMATCH),
            ("A A A B", _issue(video_plan_identity="VP-B", issuer=issuer_a), R.MISMATCH),
            ("A B B B", _issue("006", "M-B", "VP-B", issuer=issuer_b), R.MISMATCH),
            ("mission absent", _issue(mission_id=None, issuer=issuer_a), R.MISMATCH),
            ("plan absent", _issue(video_plan_identity=None, issuer=issuer_a), R.UNKNOWN),
        )
        for label, current, expected in rows:
            with self.subTest(row=label):
                self.assertEqual(verify_certificate(reference, current).result, expected)
        with self.subTest(row="B presented against A"):
            self.assertEqual(
                verify_certificate(_issue("006", "M-B", "VP-B", issuer=issuer_b), _issue(issuer=issuer_a)).result,
                R.MISMATCH,
            )

    def test_post_issuance_scope_substitution_is_integrity_invalid(self):
        cert = _issue()
        digest = compute_integrity_digest(cert)
        for altered in (
            replace(cert, request_id="006"),
            replace(cert, mission_id="M-B"),
            replace(cert, mission_id=None),
            replace(cert, video_plan_identity="VP-B"),
            replace(cert, video_plan_identity=None),
            replace(cert, readiness_report=replace(cert.readiness_report, request_id="006")),
        ):
            self.assertEqual(verify_integrity(altered, digest)[0], IntegrityResult.INTEGRITY_INVALID)

    def test_digest_of_one_scope_never_validates_another(self):
        cert_a = _issue()
        cert_b = _issue("006", "M-B", "VP-B")
        self.assertEqual(
            verify_integrity(cert_a, compute_integrity_digest(cert_b))[0], IntegrityResult.INTEGRITY_INVALID
        )


# ----------------------------------------------------------------------
# Fix 1 -- embedded readiness_report bound to the certificate's request
# ----------------------------------------------------------------------


class TestEmbeddedReportRequestBinding(unittest.TestCase):
    def _spliced(self):
        issuer_b, _ = _issuer()
        cert_005 = _issue()
        cert_006 = _issue("006", issuer=issuer_b)
        honest_006 = _issue("006", issuer=issuer_b)
        return replace(cert_006, readiness_report=cert_005.readiness_report), honest_006

    def test_spliced_certificate_is_invalid_on_either_side(self):
        spliced, honest = self._spliced()
        self.assertEqual(verify_certificate(spliced, honest).result, R.INVALID)
        self.assertEqual(verify_certificate(honest, spliced).result, R.INVALID)

    def test_spliced_certificate_is_never_trustworthy_even_with_its_own_digest(self):
        spliced, honest = self._spliced()
        report = verify_certificate_provenance_and_integrity(
            spliced, honest, ISSUER_IDENTITY, compute_integrity_digest(spliced)
        )
        self.assertEqual(report.integrity_result, IntegrityResult.INTEGRITY_VALID)  # integrity != authenticity
        self.assertEqual(report.freshness_result, R.INVALID)
        self.assertFalse(report.is_trustworthy_and_current())

    def test_issuer_output_is_always_self_consistent(self):
        for request_id in (C.request_id, "006"):
            cert = _issue(request_id)
            self.assertEqual(cert.readiness_report.request_id, cert.request_id)
            self.assertEqual(verify_certificate(cert, cert).result, R.VALID)


# ----------------------------------------------------------------------
# Lifecycle compatibility under scope change
# ----------------------------------------------------------------------


class TestLifecycleScopeBinding(unittest.TestCase):
    def test_scope_change_never_resurrects_or_promotes(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        old, new = _issue(issuer=issuer), _issue(issuer=issuer)
        registry.register(old)
        registry.register(new)

        record = registry.register(replace(old, mission_id="M-Z"))
        self.assertEqual(record.status, CertificateLifecycleStatus.SUPERSEDED)
        self.assertEqual(record.scope, (C.request_id, "M-A"))
        self.assertIsNone(registry.current_record_for((C.request_id, "M-Z")))
        self.assertEqual(registry.current_record_for((C.request_id, "M-A")).certificate_id, new.certificate_id)

    def test_current_id_presented_with_foreign_scope_is_detectable(self):
        registry = CertificateLifecycleRegistry()
        cert = _issue()
        registry.register(cert)
        digest = compute_integrity_digest(cert)
        moved = replace(cert, request_id="006")
        # lifecycle is keyed by certificate_id only (P3.57 contract) ...
        self.assertEqual(registry.status_of(moved.certificate_id), CertificateLifecycleStatus.CURRENT)
        # ... but the recorded scope and integrity both expose the substitution.
        self.assertNotEqual(registry.record_for(moved.certificate_id).scope, certificate_scope(moved))
        self.assertEqual(verify_integrity(moved, digest)[0], IntegrityResult.INTEGRITY_INVALID)

    def test_unregistered_certificate_with_valid_scope_stays_unknown(self):
        registry = CertificateLifecycleRegistry()
        registry.register(_issue())
        self.assertEqual(registry.status_of(_issue().certificate_id), CertificateLifecycleStatus.UNKNOWN)


# ----------------------------------------------------------------------
# Fix 2 -- store never persists what its own reader rejects
# ----------------------------------------------------------------------


class TestStoreScopeValidation(_TempDir):
    BAD_SCOPES = (("", "M"), (None, "M"), (5, "M"), (C.request_id, 5), (C.request_id, ["M"]))

    def _store(self):
        return FileCertificateLifecycleStore(self.tmp / "lifecycle.json")

    def test_register_certificate_rejects_invalid_scope_and_leaves_file_usable(self):
        store = self._store()
        store.register_certificate("good-1", C.request_id, "M-A", "2026-01-01T00:00:00+00:00")
        before = (self.tmp / "lifecycle.json").read_bytes()
        for request_id, mission_id in self.BAD_SCOPES:
            with self.subTest(scope=(request_id, mission_id)), self.assertRaises((ValueError, TypeError)):
                store.register_certificate("bad", request_id, mission_id, "2026-01-01T00:00:00+00:00")
        self.assertEqual((self.tmp / "lifecycle.json").read_bytes(), before)
        store.register_certificate("good-2", C.request_id, "M-A", "2026-01-01T00:00:01+00:00")
        records, current, _ = self._store().load()
        self.assertEqual(current[(C.request_id, "M-A")], "good-2")
        self.assertNotIn("bad", records)

    def test_append_registration_rejects_invalid_scope(self):
        store = self._store()
        for request_id, mission_id in self.BAD_SCOPES:
            record = CertificateLifecycleRecord(
                certificate_id="bad", scope=(request_id, mission_id),
                status=CertificateLifecycleStatus.CURRENT, superseded_by=None,
                registered_sequence=1, issued_at="2026-01-01T00:00:00+00:00",
            )
            expected = ValueError if request_id == "" else TypeError
            with self.subTest(scope=(request_id, mission_id)), self.assertRaises(expected):
                store.append_registration(record, None)
        self.assertFalse((self.tmp / "lifecycle.json").exists())

    def test_registry_with_store_stays_consistent_after_rejection(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry(store=self._store())
        good = _issue(issuer=issuer)
        registry.register(good)
        bad = issuer.issue(_conforming_request(request_id=None), mission_id="M-A")
        with self.assertRaises(TypeError):
            registry.register(bad)
        self.assertEqual(registry.status_of(bad.certificate_id), CertificateLifecycleStatus.UNKNOWN)
        hydrated = CertificateLifecycleRegistry(store=self._store())
        hydrated.hydrate_from_store()
        self.assertEqual(hydrated.status_of(good.certificate_id), CertificateLifecycleStatus.CURRENT)

    def test_persisted_scope_round_trips_and_disk_tampering_fails_closed(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry(store=self._store())
        cert = _issue(issuer=issuer)
        registry.register(cert)
        hydrated = CertificateLifecycleRegistry(store=self._store())
        hydrated.hydrate_from_store()
        self.assertEqual(hydrated.record_for(cert.certificate_id).scope, certificate_scope(cert))

        path = self.tmp / "lifecycle.json"
        data = json.loads(path.read_text("utf-8"))
        data["records"][cert.certificate_id]["mission_id"] = 5
        path.write_text(json.dumps(data), "utf-8")
        with self.assertRaises(Exception):
            CertificateLifecycleRegistry(store=self._store()).hydrate_from_store()


# ----------------------------------------------------------------------
# Negative capability -- nothing above reaches create_job()
# ----------------------------------------------------------------------


class TestNegativeCapability(unittest.TestCase):
    def test_full_scope_audit_path_never_calls_create_job(self):
        # Phase D : `create_job` est remplacé sur l'instance ci-dessous (Provider
        # alors non reconnu comme mock) -> plafond de FIXTURE explicite.
        issuer, gate = _issuer(max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST)
        calls = []
        gate.provider.create_job = lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError)
        cert = issuer.issue(_conforming_request(), mission_id="M-A", video_plan_identity="VP-A")
        digest = compute_integrity_digest(cert)
        registry = CertificateLifecycleRegistry()
        registry.register(cert)
        verify_certificate_provenance_and_integrity(cert, cert, ISSUER_IDENTITY, digest)
        verify_certificate(replace(cert, readiness_report=replace(cert.readiness_report, request_id="x")), cert)
        self.assertEqual(calls, [])
        for name in ("approve", "authorize", "execute", "create_job", "consume", "activate"):
            self.assertFalse(hasattr(cert, name) or hasattr(cert.readiness_report, name), name)


if __name__ == "__main__":
    unittest.main()
