"""
Tests -- Production Wiring Boundary & Certificate Authority-Consumer
Closure Audit (Phase P3.70).

P3.63-P3.69 closed the Certificate->Authority edge from the certificate
side. P3.70 audited the CONSUMER side: can an authority consumer turn a
certificate verdict (READY/CURRENT/VALID/INTEGRITY_VALID) or the
`ActivationReadinessReport` a certificate embeds into operational
permission, and would the architecture notice such wiring early?

Findings this phase established, pinned here permanently:

  - REAL REPOSITORY: zero consumers. No production module outside the
    certificate subsystem reads a certificate status, `certificate_id`,
    verification/integrity result or `is_ready()`; no production
    function outside the subsystem accepts a certificate or readiness
    report; `GenerationJobService.execute()` takes neither. The two
    `ActivationReadinessReport` consumers (`director.py`,
    `real_provider_execution_gate.py`) always evaluate a FRESH report.
  - Future-wiring fixtures, run against disposable repository copies:
    every import-based and new-call-site form was already caught (by the
    detector, or by the execute/create_job cardinality and P3.68 wiring
    tests). Two forms evaded EVERYTHING: the Gate short-circuiting on a
    duck-typed `certificate.is_ready()` (no certificate import), and the
    Gate importing `ActivationReadinessReport` and treating READY as
    APPROVED. Minimum fix: `_check_no_certificate_verdict_interpretation`
    in agents/architecture_drift_detector.py (certificate-verdict call
    vocabulary on the authority surface; readiness-verdict imports in the
    decision core), zero findings on the real repository.
  - False positives: certificate logging/serialisation/audit modules,
    tests, scripts and immutable data stay NO_DRIFT.

Static analysis only (isolated `tempfile.TemporaryDirectory` fixtures)
plus AST reads of the real repository; nothing executes, no provider.
"""

import ast
import inspect
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.architecture_drift_detector import ArchitectureDriftDetector, DriftStatus
from agents.canonical_architecture_contract import (
    CERTIFICATE_GUARDRAIL_AUTHORITY_SURFACE_FILES,
    CERTIFICATE_SUBSYSTEM_FILES,
    CERTIFICATE_VERDICT_CALL_NAMES,
    READINESS_VERDICT_FORBIDDEN_CONSUMER_FILES,
)
from agents.generation_job_service import GenerationJobService

VERDICT_CODE = "CERTIFICATE_VERDICT_INTERPRETED_BY_AUTHORITY"
READINESS_CODE = "READINESS_VERDICT_CONSUMED_BY_EXECUTION_CORE"
CERTIFICATE_TYPE_MARKERS = (
    "Certificate", "ReadinessReport", "LifecycleRecord", "VerificationReport", "IntegrityReport",
)


def _write(root: Path, relative_path: str, content: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _production_files():
    files = [p for d in ("agents", "integrations", "scripts") for p in (PROJECT_ROOT / d).rglob("*.py")]
    files.append(PROJECT_ROOT / "director.py")
    return [p for p in files if "__pycache__" not in p.parts]


class _TempRepoTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _codes(self):
        return {f.code for f in ArchitectureDriftDetector(root=self.root).analyze().findings}


class TestRealRepositoryConsumerClosure(unittest.TestCase):
    """Sections 3-9: zero real certificate consumers, and the new rule is
    silent on the real repository."""

    def test_real_repository_has_no_verdict_interpretation_findings(self):
        report = ArchitectureDriftDetector(root=PROJECT_ROOT).analyze()
        codes = {f.code for f in report.findings}
        self.assertNotIn(VERDICT_CODE, codes)
        self.assertNotIn(READINESS_CODE, codes)
        self.assertEqual(report.status, DriftStatus.NO_DRIFT)

    def test_no_production_function_outside_subsystem_accepts_certificate_or_report(self):
        offenders = []
        for path in _production_files():
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            if rel in CERTIFICATE_SUBSYSTEM_FILES:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for arg in node.args.args + node.args.kwonlyargs:
                        annotation = ast.unparse(arg.annotation) if arg.annotation else ""
                        text = f"{arg.arg} {annotation}"
                        if "certificate" in arg.arg.lower() or any(m in annotation for m in CERTIFICATE_TYPE_MARKERS):
                            offenders.append(f"{rel}:{node.lineno} {node.name}({text})")
        self.assertEqual(offenders, [])

    def test_execute_signature_takes_no_certificate_or_readiness_input(self):
        params = set(inspect.signature(GenerationJobService.execute).parameters)
        self.assertEqual(
            params,
            {"self", "request", "timeout_seconds", "interval_seconds", "activation_contract", "provider_activation_contract"},
        )

    def test_verdict_vocabulary_is_certificate_owned(self):
        """Every verdict name is defined inside the certificate subsystem
        -- the rule never flags authority code's own vocabulary."""
        defined = set()
        for rel in CERTIFICATE_SUBSYSTEM_FILES:
            tree = ast.parse((PROJECT_ROOT / rel).read_text(encoding="utf-8-sig"))
            defined |= {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertLessEqual(set(CERTIFICATE_VERDICT_CALL_NAMES), defined)

    def test_readiness_forbidden_consumers_are_on_the_authority_surface(self):
        self.assertLessEqual(set(READINESS_VERDICT_FORBIDDEN_CONSUMER_FILES), set(CERTIFICATE_GUARDRAIL_AUTHORITY_SURFACE_FILES))


class TestFutureWiringDetected(_TempRepoTestCase):
    """Sections 12/13/16: the two forms that evaded every check before
    P3.70, plus the duck-typed variants of Fixtures A/C/F."""

    def test_gate_duck_typed_is_ready_short_circuit(self):  # Fixture B2
        _write(self.root, "agents/generation_approval_gate.py",
               "def evaluate_with_certificate(request, certificate):\n"
               "    if certificate is not None and certificate.is_ready():\n"
               "        return 'APPROVED'\n")
        self.assertIn(VERDICT_CODE, self._codes())

    def test_gate_imports_readiness_report_and_trusts_ready(self):  # Fixture B1
        _write(self.root, "agents/generation_approval_gate.py",
               "def evaluate_from_report(report):\n"
               "    from agents.activation_readiness import ActivationReadinessReport\n"
               "    if isinstance(report, ActivationReadinessReport) and report.decision == 'READY':\n"
               "        return 'APPROVED'\n")
        self.assertIn(READINESS_CODE, self._codes())

    def test_job_service_imports_real_provider_execution_gate(self):
        _write(self.root, "agents/generation_job_service.py",
               "from agents.real_provider_execution_gate import RealProviderExecutionGateReport\n")
        self.assertIn(READINESS_CODE, self._codes())

    def test_production_authority_duck_typed_is_ready(self):  # Fixture A3
        _write(self.root, "agents/production_authority_intake.py",
               "def certificate_says_authorized(certificate):\n    return certificate.is_ready()\n")
        self.assertIn(VERDICT_CODE, self._codes())

    def test_final_report_service_lifecycle_status_check(self):  # Fixture C3
        _write(self.root, "agents/final_report_service.py",
               "def current(registry, certificate_id):\n"
               "    return registry.status_of(certificate_id).value == 'CURRENT'\n")
        self.assertIn(VERDICT_CODE, self._codes())

    def test_developer_snippet_in_director(self):  # Section 16 / Fixture F
        _write(self.root, "director.py",
               "def gated(certificate, generation_service, request):\n"
               "    if certificate.is_ready():\n"
               "        generation_service.execute(request)\n")
        self.assertIn(VERDICT_CODE, self._codes())

    def test_verification_verdict_in_authority_surface(self):
        _write(self.root, "agents/human_authorization_handoff.py",
               "def accept(reference, current, verify_certificate):\n"
               "    return verify_certificate(reference, current).is_valid()\n")
        self.assertIn(VERDICT_CODE, self._codes())


class TestFalsePositivesControlled(_TempRepoTestCase):
    """Section 14/15: informational uses outside the authority surface,
    and the subsystem's own definitions, are never flagged."""

    def _assert_clean(self):
        codes = self._codes()
        self.assertNotIn(VERDICT_CODE, codes)
        self.assertNotIn(READINESS_CODE, codes)

    def test_certificate_logging_and_serialisation_module(self):
        _write(self.root, "agents/certificate_audit_log.py",
               "from agents.certificate_integrity import compute_integrity_digest\n"
               "def record(certificate):\n"
               "    return certificate.certificate_id, compute_integrity_digest(certificate), certificate.is_ready()\n")
        self._assert_clean()

    def test_certificate_subsystem_defining_and_using_its_own_vocabulary(self):
        _write(self.root, "agents/production_activation_readiness_certificate.py",
               "class C:\n    def is_ready(self):\n        return False\n"
               "def f(c):\n    return c.is_ready()\n")
        _write(self.root, "agents/certificate_lifecycle.py",
               "def g(registry, cid):\n    return registry.status_of(cid)\n")
        self._assert_clean()

    def test_tests_and_scripts(self):
        _write(self.root, "tests/test_helper_certificate.py",
               "from agents.activation_readiness import ActivationReadinessReport\n"
               "def f(c):\n    return c.is_ready()\n")
        _write(self.root, "scripts/print_certificate.py",
               "def f(c):\n    print(c.is_ready())\n")
        self._assert_clean()

    def test_sanctioned_fresh_readiness_consumers(self):
        _write(self.root, "agents/real_provider_execution_gate.py",
               "from agents.activation_readiness import ActivationReadinessEvaluator, ActivationReadinessReport\n")
        _write(self.root, "director.py",
               "from agents.activation_readiness import ActivationReadinessEvaluator, ActivationReadinessReport\n")
        self._assert_clean()

    def test_asset_resolver_is_ready_is_not_certificate_vocabulary_scope(self):
        _write(self.root, "agents/asset_resolver.py",
               "class AssetResolver:\n    def is_ready(self, requirements):\n        return True\n"
               "    def check(self, r):\n        return self.is_ready(r)\n")
        self._assert_clean()


if __name__ == "__main__":
    unittest.main()
