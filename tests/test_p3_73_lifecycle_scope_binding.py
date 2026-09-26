"""
Tests -- Certificate Lifecycle Scope Binding & Mission Identity Closure
(Phase P3.73).

Pins the two residual limits P3.72 surfaced, as the contracts they are:
- `CertificateLifecycleRegistry.status_of(id)` is keyed by id only; the
  presented scope is never an input (substitution stays detectable via
  `record_for(id).scope`, `current_record_for(scope)`, and integrity).
- `certificate_still_matches()` takes no `mission_id`;
  `verify_certificate()` is the mission-aware comparator.

And the one guardrail gap P3.73 closed: `record_for` / `history_for`
called from the authority surface now trip
CERTIFICATE_VERDICT_INTERPRETED_BY_AUTHORITY, like `status_of`.

MockHiggsfieldProvider only -- no real create_job(), no credits.
"""

import inspect
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.architecture_drift_detector import ArchitectureDriftDetector
from agents.certificate_integrity import IntegrityResult, compute_integrity_digest, verify_integrity
from agents.certificate_lifecycle import (
    CertificateLifecycleRegistry,
    CertificateLifecycleStatus,
    certificate_scope,
)
from agents.certificate_lifecycle_store import FileCertificateLifecycleStore
from agents.certificate_verification import CertificateVerificationResult, verify_certificate
from agents.generation_job_service import GenerationJobExecutionError
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.production_activation_readiness_certificate import (
    ProductionActivationReadinessCertificateIssuer,
    certificate_still_matches,
)
from tests.test_certificate_integrity import C, _conforming_request, _issuer
from tests.test_p3_71_certificate_drift_runtime_boundary import TestRuntimeBoundary as _P371Runtime

LS = CertificateLifecycleStatus
R = CertificateVerificationResult
VERDICT_CODE = "CERTIFICATE_VERDICT_INTERPRETED_BY_AUTHORITY"


def _issue(issuer, request_id=None, mission_id="M-A", video_plan_identity="VP-A"):
    request = _conforming_request() if request_id is None else _conforming_request(request_id=request_id)
    return issuer.issue(request, mission_id=mission_id, video_plan_identity=video_plan_identity)


# ----------------------------------------------------------------------
# status_of() -- id-keyed contract and S1-S5
# ----------------------------------------------------------------------


class TestStatusOfContract(unittest.TestCase):
    def test_status_of_takes_only_a_certificate_id(self):
        self.assertEqual(list(inspect.signature(CertificateLifecycleRegistry.status_of).parameters), ["self", "certificate_id"])

    def test_s1_to_s5_substitution_is_never_bound_by_status_alone_but_always_detectable(self):
        issuer, _ = _issuer()
        cert = _issue(issuer)
        digest = compute_integrity_digest(cert)
        registry = CertificateLifecycleRegistry()
        registry.register(cert)

        cases = {
            "S1": (cert, True),
            "S2": (replace(cert, request_id="006"), False),
            "S3": (replace(cert, mission_id="M-B"), False),
            "S4": (replace(cert, video_plan_identity="VP-B"), True),  # plan is not lifecycle scope
            "S5": (replace(cert, request_id="006", mission_id="M-B", video_plan_identity="VP-B"), False),
        }
        for label, (presented, scope_matches) in cases.items():
            with self.subTest(case=label):
                self.assertEqual(registry.status_of(presented.certificate_id), LS.CURRENT)
                self.assertEqual(registry.record_for(presented.certificate_id).scope == certificate_scope(presented), scope_matches)
                self.assertEqual(registry.current_record_for(certificate_scope(presented)) is not None, scope_matches)
                expected_integrity = IntegrityResult.INTEGRITY_VALID if label == "S1" else IntegrityResult.INTEGRITY_INVALID
                self.assertEqual(verify_integrity(presented, digest)[0], expected_integrity)
                self.assertEqual(verify_certificate(presented, cert).result == R.VALID, label == "S1")

    def test_video_plan_change_supersedes_within_scope_mission_change_does_not(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        plan_a, plan_b = _issue(issuer), _issue(issuer, video_plan_identity="VP-B")
        mission_b = _issue(issuer, mission_id="M-B")
        for cert in (plan_a, plan_b, mission_b):
            registry.register(cert)
        self.assertEqual(registry.status_of(plan_a.certificate_id), LS.SUPERSEDED)
        self.assertEqual(registry.status_of(plan_b.certificate_id), LS.CURRENT)
        self.assertEqual(registry.status_of(mission_b.certificate_id), LS.CURRENT)


# ----------------------------------------------------------------------
# certificate_still_matches() -- mission-blind by signature
# ----------------------------------------------------------------------


class TestStillMatchesMissionScope(unittest.TestCase):
    def test_signature_has_no_mission_parameter(self):
        params = list(inspect.signature(certificate_still_matches).parameters)
        self.assertEqual(params, ["certificate", "request", "video_plan_identity"])

    def test_passing_a_mission_positionally_is_a_type_error(self):
        issuer, _ = _issuer()
        with self.assertRaises(TypeError):
            certificate_still_matches(_issue(issuer), _conforming_request(), "M-B", "VP-A")

    def test_mission_substitution_is_invisible_to_still_matches_but_caught_by_verify(self):
        issuer, _ = _issuer()
        cert_a = _issue(issuer, mission_id="M-A")
        cert_b = _issue(issuer, mission_id="M-B")
        self.assertTrue(certificate_still_matches(cert_a, _conforming_request(), "VP-A")[0])
        self.assertTrue(certificate_still_matches(cert_b, _conforming_request(), "VP-A")[0])
        self.assertEqual(verify_certificate(cert_a, cert_b).result, R.MISMATCH)
        self.assertEqual(verify_certificate(cert_b, cert_a).result, R.MISMATCH)

    def test_cross_scope_matrix(self):
        issuer_a, _ = _issuer()
        issuer_b, _ = _issuer()
        cert_a = _issue(issuer_a)
        cert_b = _issue(issuer_b, "006", "M-B", "VP-B")
        rows = (  # (certificate, request_id, mission, plan, still_matches, verify)
            (cert_a, None, "M-A", "VP-A", True, R.VALID),
            (cert_a, "006", "M-A", "VP-A", False, R.MISMATCH),
            (cert_a, None, "M-B", "VP-A", True, R.MISMATCH),
            (cert_a, None, "M-A", "VP-B", False, R.MISMATCH),
            (cert_b, None, "M-A", "VP-A", False, R.MISMATCH),
            (cert_b, "006", "M-B", "VP-B", True, R.VALID),
        )
        for cert, request_id, mission, plan, expected_match, expected_verify in rows:
            issuer = issuer_a if request_id is None else issuer_b
            request = _conforming_request() if request_id is None else _conforming_request(request_id=request_id)
            current = issuer.issue(request, mission_id=mission, video_plan_identity=plan)
            with self.subTest(cert=cert.request_id, request=request.request_id, mission=mission, plan=plan):
                self.assertEqual(certificate_still_matches(cert, request, plan)[0], expected_match)
                self.assertEqual(verify_certificate(cert, current).result, expected_verify)


# ----------------------------------------------------------------------
# Lifecycle + persistence under scope substitution
# ----------------------------------------------------------------------


class TestLifecycleAcrossRestart(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="p373_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _hydrated(self):
        registry = CertificateLifecycleRegistry(store=FileCertificateLifecycleStore(self.tmp / "lifecycle.json"))
        registry.hydrate_from_store()
        return registry

    def test_restart_lookup_with_foreign_scope_is_deterministic(self):
        issuer, _ = _issuer()
        cert = _issue(issuer)
        CertificateLifecycleRegistry(store=FileCertificateLifecycleStore(self.tmp / "lifecycle.json")).register(cert)
        moved = replace(cert, mission_id="M-B")
        for _ in range(2):
            registry = self._hydrated()
            self.assertEqual(registry.status_of(cert.certificate_id), LS.CURRENT)
            self.assertEqual(registry.record_for(moved.certificate_id).scope, (C.request_id, "M-A"))
            self.assertIsNone(registry.current_record_for((C.request_id, "M-B")))
            self.assertEqual(registry.register(moved).scope, (C.request_id, "M-A"))

    def test_scope_substitution_never_resurrects_or_promotes_after_restart(self):
        issuer, _ = _issuer()
        old, new = _issue(issuer), _issue(issuer)
        registry = CertificateLifecycleRegistry(store=FileCertificateLifecycleStore(self.tmp / "lifecycle.json"))
        registry.register(old)
        registry.register(new)
        restarted = self._hydrated()
        self.assertEqual(restarted.register(replace(old, mission_id="M-B")).status, LS.SUPERSEDED)
        self.assertEqual(restarted.status_of(_issue(issuer, mission_id="M-B").certificate_id), LS.UNKNOWN)
        self.assertEqual(restarted.current_record_for((C.request_id, "M-A")).certificate_id, new.certificate_id)


# ----------------------------------------------------------------------
# Future consumers F1-F6 -- detected on the authority surface
# ----------------------------------------------------------------------


class TestFutureConsumersDetected(unittest.TestCase):
    FIXTURES = {
        "F1": ("agents/generation_job_service.py",
               "def f(lifecycle, cid, svc, req):\n    if lifecycle.status_of(cid).value == 'CURRENT':\n        svc.execute(req)\n"),
        "F2": ("director.py",
               "def f(cert, req, plan, svc):\n    if certificate_still_matches(cert, req, plan)[0]:\n        svc.execute(req)\n"),
        "F3": ("agents/production_authority_intake.py",
               "def f(c, r, m, p, auth):\n    if certificate_still_matches(c, r, m, p):\n        auth.authorize(r)\n"),
        "F5": ("agents/final_report_service.py",
               "def f(lifecycle, cid, svc, req):\n    if lifecycle.record_for(cid).status.value == 'CURRENT':\n        svc.execute(req)\n"),
        "F6": ("agents/generation_approval_gate.py",
               "def f(lifecycle, scope):\n    return bool(lifecycle.history_for(scope))\n"),
    }

    def _codes(self, rel, source):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
            return {f.code for f in ArchitectureDriftDetector(root=Path(tmp)).analyze().findings}

    def test_every_lifecycle_or_match_lookup_on_authority_surface_is_detected(self):
        for label, (rel, source) in self.FIXTURES.items():
            with self.subTest(fixture=label):
                self.assertIn(VERDICT_CODE, self._codes(rel, source))

    def test_f4_readiness_of_foreign_mission_read_by_gate_is_detected(self):
        codes = self._codes(
            "agents/generation_approval_gate.py",
            "def f(cert, mission_b):\n    if cert.readiness_report.decision == 'READY':\n        return 'APPROVED'\n",
        )
        self.assertIn("CERTIFICATE_VERDICT_READ_BY_AUTHORITY", codes)

    def test_lifecycle_lookups_inside_the_subsystem_stay_clean(self):
        codes = self._codes(
            "agents/certificate_lifecycle.py",
            "def g(registry, cid, scope):\n    return registry.record_for(cid), registry.history_for(scope)\n",
        )
        self.assertNotIn(VERDICT_CODE, codes)


# ----------------------------------------------------------------------
# Runtime -- CURRENT + still_matches for a foreign mission grants nothing
# ----------------------------------------------------------------------


class TestForeignMissionCertificateGrantsNothing(unittest.TestCase):
    _request = _P371Runtime._request
    _chain = _P371Runtime._chain

    @classmethod
    def setUpClass(cls):
        cls.prompt = PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id)

    def test_hostile_composition_still_hits_every_p2_check(self):
        gate, _activation, job_service, _report, evaluator, created = self._chain()
        cert_a = ProductionActivationReadinessCertificateIssuer(evaluator).issue(
            self._request(), mission_id="M-A", video_plan_identity="VP-A"
        )
        registry = CertificateLifecycleRegistry()
        registry.register(cert_a)

        # Simulated future misuse for mission B: both informational checks pass ...
        request_for_mission_b = self._request(real_generation_authorization=None)
        self.assertEqual(registry.status_of(cert_a.certificate_id), LS.CURRENT)
        self.assertTrue(certificate_still_matches(cert_a, request_for_mission_b, "VP-A")[0])

        # ... yet execute() takes no certificate and re-runs the P2 chain itself:
        # the request P2 blocks stays blocked, whatever the certificate says.
        with self.assertRaises(GenerationJobExecutionError):
            job_service.execute(request_for_mission_b)
        self.assertEqual(created, [])
        self.assertNotIn("certificate", inspect.signature(job_service.execute).parameters)


if __name__ == "__main__":
    unittest.main()
