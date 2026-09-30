"""
Tests -- Certificate-to-Authority Drift & Runtime Boundary Hardening Audit
(Phase P3.71).

P3.70 listed the forms outside its static rule: attribute reads without a
call, duck typing, generic readiness objects, direct certificate
construction, transitive imports, unclassified helpers. P3.71 tested each
one on disposable repository copies (detector + existing permanent AST
guardrail tests) and at runtime (MockHiggsfieldProvider only).

Findings this phase established, pinned here permanently:

  - STATIC GAP 1 (fixed): `from agents import certificate_lifecycle`
    imports a MODULE but was recorded as module `agents`, matching no
    prefix -- it evaded EVERY import rule (certificate edge in both
    directions, P3.70 readiness rule, business/production-modeling
    rules). `_extract_file_facts` now also records `package.name` when it
    is a known module (never for symbol imports: no double report).
  - STATIC GAP 2 (fixed): the P3.70 verdict rule matched CALLS only;
    `certificate.is_ready` / `.readiness_result` / `.readiness_report`
    read without a call evaded it (`if certificate.is_ready:` is even
    always true). New finding CERTIFICATE_VERDICT_READ_BY_AUTHORITY on
    certificate-owned attribute names, zero hits on the real repository.
  - RUNTIME: a directly constructed (forged) READY certificate, a READY
    `ActivationReadinessReport`, and a duck object exposing every
    readiness attribute are REFUSED by `gate.evaluate`, by `execute()`
    (as request, as activation contract, as provider contract), by
    `FinalReportService.generate` and by `prepare_activation` --
    `create_job` never reached. The P2 guards never read certificate
    information.
  - OUT OF STATIC SCOPE (documented, not fixed): generic names
    (`.status`, `.decision`), local Protocols, string annotations,
    certificate construction outside the subsystem (data only, refused at
    runtime, detected by integrity), unclassified helpers not imported by
    the authority surface (no new call site possible without the
    execute/create_job cardinality tests firing).
"""

import dataclasses
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import ActivationRejectedError, RequestScopedActivationService
from agents.activation_readiness import ActivationReadinessEvaluator, ActivationReadinessReport
from agents.architecture_drift_detector import ArchitectureDriftDetector, DriftStatus
from agents.certificate_integrity import compute_integrity_digest, verify_integrity, IntegrityResult
from agents.controlled_real_provider_activation import ControlledRealProviderActivationService
from agents.final_report_service import FinalReportService
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from tests.real_provider_path_fixtures import FIXTURE_MAX_COST_CREDITS_PER_REQUEST
from tests.authorization_content_helpers import bind_request
from agents.generation_job_service import GenerationJobService
from agents.production_activation_readiness_certificate import (
    ProductionActivationReadinessCertificate,
    ProductionActivationReadinessCertificateIssuer,
)
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.release_candidate_identity_lock import (
    ReleaseCandidateIdentityLock,
    VIDEO_005_RELEASE_CANDIDATE as C,
)
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.types import MediaReference

READ_CODE = "CERTIFICATE_VERDICT_READ_BY_AUTHORITY"
NEW_CODES = {READ_CODE}
GATE = "agents/generation_approval_gate.py"


def _write(root: Path, relative_path: str, content: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class _TempRepoTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _findings(self):
        return ArchitectureDriftDetector(root=self.root).analyze().findings

    def _codes(self):
        return {f.code for f in self._findings()}


class TestRealRepository(unittest.TestCase):
    def test_real_repository_no_new_findings_and_no_drift(self):
        report = ArchitectureDriftDetector(root=PROJECT_ROOT).analyze()
        self.assertFalse(NEW_CODES & {f.code for f in report.findings})
        self.assertEqual(report.status, DriftStatus.NO_DRIFT)


class TestPackageSubmoduleImport(_TempRepoTestCase):
    """Static gap 1: `from package import module`."""

    def test_certificate_module_into_authority_file(self):
        _write(self.root, GATE, "from agents import certificate_lifecycle\n")
        self.assertIn("CERTIFICATE_TO_AUTHORITY_IMPORT", self._codes())

    def test_readiness_module_into_decision_core(self):
        _write(self.root, GATE, "from agents import activation_readiness\n")
        self.assertIn("READINESS_VERDICT_CONSUMED_BY_EXECUTION_CORE", self._codes())

    def test_informational_layer_to_authority_module(self):
        _write(self.root, "agents/certificate_integrity.py", "from agents import generation_job_service\n")
        self.assertIn("CERTIFICATE_OUTBOUND_AUTHORITY_IMPORT", self._codes())

    def test_aliased_package_submodule_import(self):
        _write(self.root, GATE, "from agents import certificate_verification as cv\n")
        self.assertIn("CERTIFICATE_TO_AUTHORITY_IMPORT", self._codes())

    def test_transitive_through_package_submodule_import(self):
        _write(self.root, "agents/helper_x.py", "from agents import certificate_integrity\n")
        _write(self.root, GATE, "from agents import helper_x\n")
        self.assertIn("CERTIFICATE_INDIRECT_AUTHORITY_IMPORT", self._codes())

    def test_symbol_import_is_not_double_reported(self):
        _write(self.root, GATE, "from agents.certificate_lifecycle import CertificateLifecycleStatus\n")
        hits = [f for f in self._findings() if f.code == "CERTIFICATE_TO_AUTHORITY_IMPORT"]
        self.assertEqual(len(hits), 1)

    def test_unrelated_package_submodule_import_is_clean(self):
        _write(self.root, GATE, "from agents import prompt_assembly_system\n")
        codes = self._codes()
        self.assertNotIn("CERTIFICATE_TO_AUTHORITY_IMPORT", codes)
        self.assertNotIn("READINESS_VERDICT_CONSUMED_BY_EXECUTION_CORE", codes)


class TestVerdictAttributeRead(_TempRepoTestCase):
    """Static gap 2: certificate vocabulary read without a call."""

    def test_is_ready_attribute_in_production_authority(self):  # F1
        _write(self.root, "agents/production_authority_intake.py",
               "def f(c, authority):\n    if c.is_ready:\n        authority.authorize()\n")
        self.assertIn(READ_CODE, self._codes())

    def test_readiness_result_in_gate(self):  # S9
        _write(self.root, GATE, "def f(c):\n    return c.readiness_result == 'READY'\n")
        self.assertIn(READ_CODE, self._codes())

    def test_readiness_report_into_gate_evaluate(self):  # F3
        _write(self.root, "agents/final_report_service.py",
               "def f(c, gate):\n    return gate.evaluate(c.readiness_report)\n")
        self.assertIn(READ_CODE, self._codes())

    def test_call_form_is_not_double_reported_as_read(self):
        _write(self.root, GATE, "def f(c):\n    return c.is_ready()\n")
        codes = self._codes()
        self.assertIn("CERTIFICATE_VERDICT_INTERPRETED_BY_AUTHORITY", codes)
        self.assertNotIn(READ_CODE, codes)


class TestFalsePositivesControlled(_TempRepoTestCase):
    def _assert_clean(self):
        self.assertNotIn(READ_CODE, self._codes())

    def test_generic_names_on_authority_surface(self):
        _write(self.root, GATE,
               "def f(result, report, record):\n"
               "    return result.decision, report.status, record.approval_decision, result.unknown_state\n")
        self._assert_clean()

    def test_certificate_subsystem_reads_its_own_fields(self):
        _write(self.root, "agents/production_activation_readiness_certificate.py",
               "def f(c):\n    return c.readiness_report.decision, c.certificate_id\n")
        _write(self.root, "agents/certificate_lifecycle.py", "def g(r):\n    return r.superseded_by\n")
        self._assert_clean()

    def test_informational_module_outside_surface(self):
        _write(self.root, "agents/certificate_audit_log.py",
               "def f(c):\n    return c.certificate_id, c.readiness_result, c.is_ready\n")
        _write(self.root, "agents/asset_resolver.py", "def g(r):\n    return r.is_ready\n")
        _write(self.root, "tests/test_x.py", "def h(c):\n    return c.readiness_result\n")
        self._assert_clean()


class TestRuntimeBoundary(unittest.TestCase):
    """Sections 6/7/9: objects carrying READY information never unlock
    anything at runtime (MockHiggsfieldProvider only)."""

    @classmethod
    def setUpClass(cls):
        cls.prompt = PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id)

    def _request(self, **overrides):
        values = dict(
            request_id=C.request_id, job_type=C.job_type, prompt=self.prompt,
            duration=C.duration, resolution=C.resolution, aspect_ratio=C.aspect_ratio,
            approved=True,
            start_image=MediaReference(role="master_avatar", source=str(PROJECT_ROOT / "assets" / "zephyr" / "avatar" / "avatar_master.png"), sha256=None),
            image_references=(MediaReference(role="face_reference", source=str(PROJECT_ROOT / "assets" / "zephyr" / "references" / "mon avatar habille.png"), sha256=None),),
            real_generation_authorization=RealGenerationAuthorization(request_id=C.request_id, authorized_by_human=True),
        )
        values.update(overrides)
        return bind_request(GenerationRequest(**values))

    def _chain(self):
        provider = MockHiggsfieldProvider(cost_per_job=67.5, available_credits=1000.0)
        # Phase D : le Mock reconnu enregistre chaque appel de create_job()
        # dans `_jobs` (un spy remplaçant create_job sur l'instance le
        # rendrait non reconnu, donc refusé avant create_job).
        created = provider._jobs
        lock = ReleaseCandidateIdentityLock(C)
        # Phase D : plafond de FIXTURE explicite (sans effet sur le Mock reconnu).
        gate = GenerationApprovalGate(provider, identity_lock=lock, max_cost_credits_per_request=FIXTURE_MAX_COST_CREDITS_PER_REQUEST)
        activation = RequestScopedActivationService(gate, lock)
        provider_activation = ControlledRealProviderActivationService(gate, lock, activation)
        job_service = GenerationJobService(provider, gate, activation_service=activation, provider_activation_service=provider_activation)
        report_service = FinalReportService(provider, gate, job_service=job_service)
        evaluator = ActivationReadinessEvaluator(gate, lock, activation, job_service=job_service)
        return gate, activation, job_service, report_service, evaluator, created

    def _ready_objects(self):
        *_, evaluator, _created = self._chain()
        real = ProductionActivationReadinessCertificateIssuer(evaluator).issue(self._request())
        report = ActivationReadinessReport(
            request_id=C.request_id, technical_ready=True, request_identity_ready=True, prompt_ready=True,
            asset_ready=True, budget_ready=True, authorization_ready=True, activation_ready=True,
            replay_safe=True, crash_safe=True, provider_ready=True,
        )
        forged_values = {f.name: getattr(real, f.name) for f in dataclasses.fields(real)}
        forged_values.update(certificate_id="forged", readiness_report=report, readiness_result="READY", blocking_reasons=())
        forged = ProductionActivationReadinessCertificate(**forged_values)  # direct construction outside the Issuer

        class Duck:
            request_id = C.request_id
            decision = "READY"
            status = "CURRENT"
            readiness_result = "READY"
            activation_id = "duck"

            def is_ready(self):
                return True

        return real, {"forged_certificate": forged, "ready_report": report, "duck": Duck()}

    def test_forged_certificate_is_information_only(self):
        real, objects = self._ready_objects()
        forged = objects["forged_certificate"]
        self.assertTrue(forged.is_ready())
        result, _ = verify_integrity(forged, compute_integrity_digest(real))
        self.assertEqual(result, IntegrityResult.INTEGRITY_INVALID)

    def test_ready_objects_refused_on_every_authority_path(self):
        _real, objects = self._ready_objects()
        for name, obj in objects.items():
            attempts = {
                "gate.evaluate(obj)": lambda g, a, j, r: g.evaluate(obj),
                "execute(request=obj)": lambda g, a, j, r: j.execute(obj),
                "execute(unauthorized, activation_contract=obj)": lambda g, a, j, r: j.execute(self._request(real_generation_authorization=None), activation_contract=obj),
                "execute(authorized, activation_contract=obj)": lambda g, a, j, r: j.execute(self._request(), activation_contract=obj),
                "generate(authorized, activation_contract=obj)": lambda g, a, j, r: r.generate(self._request(), activation_contract=obj),
                "execute(authorized, real contract, provider_contract=obj)": lambda g, a, j, r: j.execute(self._request(), activation_contract=a.prepare_activation(self._request()), provider_activation_contract=obj),
            }
            for label, attempt in attempts.items():
                with self.subTest(obj=name, path=label):
                    gate, activation, job_service, report_service, _ev, created = self._chain()
                    with self.assertRaises(Exception):
                        attempt(gate, activation, job_service, report_service)
                    self.assertEqual(created, {})
                    self.assertFalse(gate.executed_request_store.is_executed(C.request_id))

    def test_prepare_activation_ignores_certificate_information(self):
        _real, objects = self._ready_objects()
        gate, activation, *_ = self._chain()
        self.assertTrue(objects)
        with self.assertRaises(ActivationRejectedError):
            activation.prepare_activation(self._request(real_generation_authorization=None))
        self.assertNotEqual(
            gate.evaluate(self._request(real_generation_authorization=None)).decision,
            GenerationApprovalDecision.APPROVED,
        )


if __name__ == "__main__":
    unittest.main()
