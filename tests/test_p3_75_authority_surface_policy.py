"""
Tests -- Authority-Surface Informational Use & Drift Policy (Phase P3.75).

Pins the certificate policy recorded in
agents/canonical_architecture_contract.py ("STRICT", by location):
- on the authority surface, even a purely informational certificate use
  is a finding;
- outside it, informational use is clean -- unless the same module also
  reaches the authority surface: CERTIFICATE_AUTHORITY_BRIDGE_MODULE
  (the P3.70 "unclassified helper" gap, closed in P3.75);
- transitive import chains (1-3 hops) stay detected (P3.65);
- at runtime, a certificate is never accepted as P2 input.

MockHiggsfieldProvider only -- no real create_job(), no credits.
"""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.architecture_drift_detector import ArchitectureDriftDetector
from agents.certificate_lifecycle import CertificateLifecycleRegistry, CertificateLifecycleStatus
from agents.generation_approval_gate import GenerationApprovalDecision
from agents.generation_job_service import GenerationJobExecutionError
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.production_activation_readiness_certificate import ProductionActivationReadinessCertificateIssuer
from agents.release_candidate_identity_lock import VIDEO_005_RELEASE_CANDIDATE as C
from tests.test_p3_71_certificate_drift_runtime_boundary import TestRuntimeBoundary as _P371Runtime

BRIDGE = "CERTIFICATE_AUTHORITY_BRIDGE_MODULE"
CL = "from agents.certificate_lifecycle import CertificateLifecycleRegistry\n"
FRS = "from agents.final_report_service import FinalReportService\n"


def _codes(*files):
    with tempfile.TemporaryDirectory() as tmp:
        for rel, source in files:
            path = Path(tmp) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        return {f.code for f in ArchitectureDriftDetector(root=Path(tmp)).analyze().findings}


class TestRealRepository(unittest.TestCase):
    def test_no_bridge_module_in_the_real_repository(self):
        findings = ArchitectureDriftDetector(root=PROJECT_ROOT).analyze().findings
        self.assertEqual([f for f in findings if f.code == BRIDGE], [])


class TestBridgeModuleDetected(unittest.TestCase):
    def test_unclassified_module_reaching_both_sides(self):
        cases = {
            "direct imports, generate() if CURRENT": [
                ("agents/unclassified_helper.py",
                 CL + FRS + "def go(reg, cid, svc, req):\n    if reg.status_of(cid).value == 'CURRENT':\n        return svc.generate(req)\n")],
            "aliased module imports": [
                ("agents/unclassified_helper.py",
                 "import agents.certificate_lifecycle as cl\nimport agents.generation_approval_gate as g\n")],
            "certificate side reached transitively": [
                ("agents/h1.py", CL),
                ("agents/unclassified_helper.py", "from agents.h1 import *\n" + FRS)],
            "authority side reached transitively": [
                ("agents/h1.py", FRS),
                ("agents/unclassified_helper.py", CL + "from agents.h1 import *\n")],
            "package submodule form": [
                ("agents/unclassified_helper.py",
                 "from agents import certificate_verification\nfrom agents import generation_job_service\n")],
        }
        for label, files in cases.items():
            with self.subTest(case=label):
                self.assertIn(BRIDGE, _codes(*files))


class TestInformationalUseStaysClean(unittest.TestCase):
    def test_no_false_positive_outside_the_authority_surface(self):
        cases = {
            "certificate-only report module": [
                ("agents/lifecycle_report.py", CL + "import json\ndef dump(reg, scope):\n    return json.dumps([r.certificate_id for r in reg.history_for(scope)])\n")],
            "authority-only module": [("agents/other_helper.py", FRS)],
            "issuer-only module (authority reached only through the subsystem)": [
                ("agents/issue_helper.py",
                 "from agents.production_activation_readiness_certificate import ProductionActivationReadinessCertificateIssuer\n")],
            "test importing both": [("tests/test_something.py", CL + FRS)],
            # A script importing both is a bridge since P3.76-R1
            # (tests/test_p3_76_r1_bridge_guardrail_closure.py).
        }
        for label, files in cases.items():
            with self.subTest(case=label):
                self.assertNotIn(BRIDGE, _codes(*files))


class TestStrictPolicyOnAuthoritySurface(unittest.TestCase):
    def test_informational_use_on_authority_surface_is_still_a_finding(self):
        cases = {
            "record_for + log (gate)": ("agents/generation_approval_gate.py",
                                        "def f(reg, cid, log):\n    log(reg.record_for(cid).status)\n"),
            "certificate_id audit (final report)": ("agents/final_report_service.py",
                                                    "def f(certificate, audit):\n    audit(certificate.certificate_id)\n"),
            "type-only import (handoff)": ("agents/human_authorization_handoff.py",
                                           "from agents.certificate_lifecycle import CertificateLifecycleRecord\n"),
            "director informational read": ("director.py", "def f(c):\n    print(c.readiness_result)\n"),
        }
        for label, (rel, source) in cases.items():
            with self.subTest(case=label):
                self.assertTrue(any(code.startswith("CERTIFICATE_") for code in _codes((rel, source))))

    def test_transitive_chains_up_to_three_hops_are_detected(self):
        chain = [("agents/h1.py", CL)]
        for depth in (1, 2, 3):
            if depth > 1:
                chain.append((f"agents/h{depth}.py", f"from agents.h{depth - 1} import *\n"))
            files = chain + [("agents/generation_approval_gate.py", f"from agents.h{depth} import *\n")]
            with self.subTest(hops=depth):
                self.assertIn("CERTIFICATE_INDIRECT_AUTHORITY_IMPORT", _codes(*files))


class TestRuntimeNegativeCapability(unittest.TestCase):
    _request = _P371Runtime._request
    _chain = _P371Runtime._chain

    @classmethod
    def setUpClass(cls):
        cls.prompt = PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id)

    def test_a_certificate_is_never_accepted_as_p2_input(self):
        gate, _activation, job_service, report_service, evaluator, created = self._chain()
        certificate = ProductionActivationReadinessCertificateIssuer(evaluator).issue(self._request(), mission_id="M-A")
        registry = CertificateLifecycleRegistry()
        registry.register(certificate)
        self.assertEqual(registry.status_of(certificate.certificate_id), CertificateLifecycleStatus.CURRENT)

        try:
            decision = gate.evaluate(certificate).decision
        except Exception:  # noqa: BLE001 -- refusing the object outright is equally acceptable
            decision = None
        self.assertNotEqual(decision, GenerationApprovalDecision.APPROVED)

        with self.assertRaises(Exception):
            job_service.execute(certificate)
        with self.assertRaises(GenerationJobExecutionError):
            job_service.execute(self._request(real_generation_authorization=None))
        self.assertEqual(created, {})  # Phase D : registre `_jobs` du Mock reconnu (cf. P3.71 `_chain`)


if __name__ == "__main__":
    unittest.main()
