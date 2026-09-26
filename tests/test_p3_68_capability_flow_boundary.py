"""
Tests -- Capability Flow & Object Reference Boundary Audit (Phase P3.68).

P3.63-P3.67 closed the Certificate->Authority edge at the IMPORT and
REFLECTION level. P3.68's question was about CAPABILITY FLOW: can a real
Authority capability enter, be retained by, be invoked by, or be
transmitted out of the certificate subsystem through object references
(constructor/function injection, callbacks, closures, partials,
containers, return values, bound methods), even with no import edge?

Findings this phase established, pinned here permanently:

  - REAL REPOSITORY: no production module outside the certificate
    subsystem constructs `ProductionActivationReadinessCertificateIssuer`,
    `CertificateLifecycleRegistry` or `FileCertificateLifecycleStore`,
    or calls `verify_certificate*` -- the subsystem is wired only by
    tests. No object of any kind flows into it from production code.
  - The subsystem's only injection points are: the Issuer's `evaluator`
    (isinstance-checked `ActivationReadinessEvaluator`) and `clock`
    (callable), and the Registry's duck-typed `store`. The informational
    layer (P3.55-P3.60) passes the store ONLY strings/ints.
  - The Issuer (P3.54, sanctioned composition) RETAINS an object
    reference into the Authority graph (`issuer.evaluator.gate`,
    `.job_service`, `gate.provider`) -- a reference supplied by, and
    already held by, its caller. `issue()` performs ZERO operational
    calls through it (no execute/create_job/mark_executed/mark_unknown/
    prepare_activation/validate_activation), and invoking the reachable
    `execute()` without human authorization still hard-raises: a
    reference is not a capability amplification.
  - The ISSUED certificate, lifecycle records, and verification/
    integrity reports are pure data graphs (str/int/float/bool/None/
    Enum inside tuples/lists/frozen dataclasses) -- no callable, no
    service, no authority object reaches them from the real Issuer.
  - `evidence_references` values are `str()`-sanitised, so a bound
    authority method passed there is stored as text, never retained.
  - HYPOTHETICAL (caller-injected, not present in the repository): the
    certificate code will invoke a callable its CALLER injects as
    `clock`/`store` (or an object with a hostile `__str__`), and will
    retain an object passed into an untyped-at-runtime field. In every
    case the capability originated with the caller (no amplification),
    and the P2 guards inside `execute()` still block -- pinned below.

MockHiggsfieldProvider exclusively; no real generation, no real
create_job(), no credits consumed.
"""

import ast
import dataclasses
import enum
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import RequestScopedActivationService
from agents.activation_readiness import ActivationReadinessEvaluator
from agents.canonical_architecture_contract import CERTIFICATE_SUBSYSTEM_FILES
from agents.certificate_integrity import (
    compute_integrity_digest,
    verify_certificate_provenance_and_integrity,
)
from agents.certificate_lifecycle import CertificateLifecycleRegistry
from agents.certificate_lifecycle_store import FileCertificateLifecycleStore
from agents.certificate_verification import verify_certificate
from agents.generation_approval_gate import (
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from agents.generation_job_service import GenerationJobExecutionError, GenerationJobService
from agents.production_activation_readiness_certificate import (
    ProductionActivationReadinessCertificateIssuer,
)
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.release_candidate_identity_lock import (
    ReleaseCandidateIdentityLock,
    VIDEO_005_RELEASE_CANDIDATE as C,
)
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.types import MediaReference

PRODUCTION_DIRS = ("agents", "integrations", "scripts")
CERTIFICATE_ENTRY_SYMBOLS = {
    "ProductionActivationReadinessCertificateIssuer",
    "CertificateLifecycleRegistry",
    "FileCertificateLifecycleStore",
    "verify_certificate",
    "verify_certificate_provenance_and_integrity",
}
OPERATIONAL_METHODS = {
    GenerationJobService: ("execute",),
    GenerationApprovalGate: ("mark_executed", "mark_unknown"),
    RequestScopedActivationService: ("prepare_activation", "validate_activation"),
    MockHiggsfieldProvider: ("create_job", "get_job", "wait_for_job"),
}
DATA_LEAVES = (str, int, float, bool, type(None), enum.Enum)


def _production_files():
    files = [p for d in PRODUCTION_DIRS for p in (PROJECT_ROOT / d).rglob("*.py")]
    files.append(PROJECT_ROOT / "director.py")
    return [p for p in files if "__pycache__" not in p.parts]


def _rel(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _non_data_leaves(obj, path="root", seen=None, out=None):
    seen = set() if seen is None else seen
    out = [] if out is None else out
    if id(obj) in seen or isinstance(obj, DATA_LEAVES):
        return out
    seen.add(id(obj))
    if isinstance(obj, (tuple, list)):
        for i, item in enumerate(obj):
            _non_data_leaves(item, f"{path}[{i}]", seen, out)
    elif isinstance(obj, dict):
        for key, value in obj.items():
            _non_data_leaves(key, f"{path}<key>", seen, out)
            _non_data_leaves(value, f"{path}[{key!r}]", seen, out)
    elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            _non_data_leaves(getattr(obj, f.name), f"{path}.{f.name}", seen, out)
    else:
        out.append(f"{path}: {type(obj).__name__}")
    return out


class _Clock:
    def isoformat(self):
        return "2026-09-22T00:00:00+00:00"


class _World(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prompt = PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id)

    def setUp(self):
        self.calls = []
        self.provider = self._spy(MockHiggsfieldProvider(cost_per_job=67.5, available_credits=1000.0))
        lock = ReleaseCandidateIdentityLock(C)
        self.gate = self._spy(GenerationApprovalGate(self.provider, identity_lock=lock))
        self.activation = self._spy(RequestScopedActivationService(self.gate, lock))
        self.job_service = self._spy(
            GenerationJobService(self.provider, self.gate, activation_service=self.activation)
        )
        self.evaluator = ActivationReadinessEvaluator(
            self.gate, lock, self.activation, job_service=self.job_service
        )

    def _spy(self, obj):
        for method in OPERATIONAL_METHODS[type(obj)]:
            original = getattr(obj, method)

            def wrapper(*args, _original=original, _name=f"{type(obj).__name__}.{method}", **kwargs):
                self.calls.append(_name)
                return _original(*args, **kwargs)

            setattr(obj, method, wrapper)
        return obj

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
        return GenerationRequest(**values)

    def _unauthorized_execute_attempt(self):
        try:
            self.job_service.execute(self._request(real_generation_authorization=None))
        except GenerationJobExecutionError:
            self.calls.append("blocked")

    def assert_nothing_operational_ran(self):
        self.assertNotIn("MockHiggsfieldProvider.create_job", self.calls)
        self.assertFalse(self.gate.executed_request_store.is_executed(C.request_id))
        self.assertFalse(self.gate.executed_request_store.is_unknown(C.request_id))


class TestRealRepositoryCapabilityPaths(unittest.TestCase):
    """Section 4/11/17: the certificate subsystem receives no object from
    production code, and its informational layer holds no authority
    reference."""

    def test_no_production_module_outside_subsystem_wires_certificate_components(self):
        offenders = []
        for path in _production_files():
            if _rel(path) in CERTIFICATE_SUBSYSTEM_FILES:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                    if name in CERTIFICATE_ENTRY_SYMBOLS:
                        offenders.append(f"{_rel(path)}:{node.lineno}")
        self.assertEqual(offenders, [], "certificate subsystem is now wired by production code -- re-audit P3.68 capability flow")

    def test_no_bound_authority_method_is_stored_or_passed_in_production(self):
        """Every non-call reference to execute/create_job in production
        code is an identity comparison (`x is HiggsfieldProvider.create_job`),
        never a stored/passed bound method."""
        offenders = []
        for path in _production_files():
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in ("execute", "create_job") and isinstance(node.ctx, ast.Load):
                    parent = parents.get(node)
                    if isinstance(parent, ast.Call) and parent.func is node:
                        continue
                    if isinstance(parent, ast.Compare) and all(isinstance(op, (ast.Is, ast.IsNot)) for op in parent.ops):
                        continue
                    offenders.append(f"{_rel(path)}:{node.lineno}")
        self.assertEqual(offenders, [])

    def test_no_functools_partial_in_production(self):
        offenders = [
            _rel(p) for p in _production_files()
            if "functools" in p.read_text(encoding="utf-8-sig")
        ]
        self.assertEqual(offenders, [])


class TestRealIssuerCapabilityFlow(_World):
    """Section 5/13/16: the Issuer retains a caller-supplied reference but
    never exercises or leaks an operational capability."""

    def test_issue_performs_zero_operational_calls(self):
        issuer = ProductionActivationReadinessCertificateIssuer(self.evaluator)
        issuer.issue(self._request(), mission_id="m-005", video_plan_identity="plan-005")
        self.assertEqual(self.calls, [])
        self.assert_nothing_operational_ran()

    def test_issued_certificate_is_a_pure_data_graph(self):
        cert = ProductionActivationReadinessCertificateIssuer(self.evaluator).issue(
            self._request(), mission_id="m-005", video_plan_identity="plan-005",
            evidence_references={"note": "x"},
        )
        self.assertEqual(_non_data_leaves(cert, "certificate"), [])

    def test_reachable_execute_through_issuer_grants_nothing(self):
        issuer = ProductionActivationReadinessCertificateIssuer(self.evaluator)
        self.assertIs(issuer.evaluator.job_service, self.job_service)  # reference exists (sanctioned P3.54 composition)
        with self.assertRaises(GenerationJobExecutionError):
            issuer.evaluator.job_service.execute(self._request(real_generation_authorization=None))
        self.assert_nothing_operational_ran()

    def test_non_evaluator_injection_rejected(self):
        with self.assertRaises(ValueError):
            ProductionActivationReadinessCertificateIssuer(self.job_service)

    def test_bound_method_in_evidence_references_is_stringified(self):
        cert = ProductionActivationReadinessCertificateIssuer(self.evaluator).issue(
            self._request(), evidence_references={"ref": self.job_service.execute}
        )
        self.assertIsInstance(cert.evidence_references[0][1], str)
        self.assertEqual(_non_data_leaves(cert, "certificate"), [])


class TestRealInformationalLayerCapabilityFlow(_World):
    """Section 9/12/13: lifecycle records and verification/integrity
    reports stay pure data; no operational call happens."""

    def test_lifecycle_verification_integrity_are_pure_data_and_inert(self):
        cert = ProductionActivationReadinessCertificateIssuer(self.evaluator).issue(self._request())
        registry = CertificateLifecycleRegistry()
        record = registry.register(cert)
        with tempfile.TemporaryDirectory() as tmp:
            file_registry = CertificateLifecycleRegistry(
                store=FileCertificateLifecycleStore(Path(tmp) / "lifecycle.json")
            )
            file_record = file_registry.register(cert)
        report = verify_certificate(cert, cert)
        integrity = verify_certificate_provenance_and_integrity(cert, cert, None, compute_integrity_digest(cert))
        for label, obj in (("record", record), ("file_record", file_record), ("verification", report), ("integrity", integrity)):
            self.assertEqual(_non_data_leaves(obj, label), [])
        self.assertEqual(self.calls, [])
        self.assert_nothing_operational_ran()

    def test_store_receives_only_primitive_data(self):
        received = []

        class RecordingStore:
            def register_certificate(self, **kwargs):
                received.append(kwargs)
                raise RuntimeError("stop after capture")

        cert = ProductionActivationReadinessCertificateIssuer(self.evaluator).issue(self._request(), mission_id="m-005")
        with self.assertRaises(RuntimeError):
            CertificateLifecycleRegistry(store=RecordingStore()).register(cert)
        self.assertEqual(len(received), 1)
        self.assertEqual(_non_data_leaves(received[0], "store_kwargs"), [])


class TestHypotheticalCallerInjectedCapability(_World):
    """Section 18/19: HYPOTHETICAL flows (not present in the repository).
    The certificate code can act as a conduit for a capability its CALLER
    already holds -- never an amplifier: P2 guards still block."""

    def _callback_clock(self):
        self._unauthorized_execute_attempt()
        return _Clock()

    def test_injected_clock_callback_cannot_bypass_p2(self):
        ProductionActivationReadinessCertificateIssuer(self.evaluator, clock=self._callback_clock).issue(self._request())
        self.assertIn("blocked", self.calls)
        self.assert_nothing_operational_ran()

    def test_injected_store_cannot_bypass_p2(self):
        world = self

        class HostileStore:
            def register_certificate(self, **kwargs):
                world._unauthorized_execute_attempt()
                raise RuntimeError("hostile store")

        cert = ProductionActivationReadinessCertificateIssuer(self.evaluator).issue(self._request())
        with self.assertRaises(RuntimeError):
            CertificateLifecycleRegistry(store=HostileStore()).register(cert)
        self.assertIn("blocked", self.calls)
        self.assert_nothing_operational_ran()

    def test_retained_bound_method_is_never_invoked_by_certificate_code(self):
        cert = ProductionActivationReadinessCertificateIssuer(self.evaluator).issue(
            self._request(), mission_id=self.job_service.execute, video_plan_identity=self.gate.mark_executed
        )
        verify_certificate(cert, cert)
        compute_integrity_digest(cert)
        CertificateLifecycleRegistry().register(cert)
        self.assertEqual(self.calls, [])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(TypeError):  # file store refuses to persist a non-str scope
                CertificateLifecycleRegistry(
                    store=FileCertificateLifecycleStore(Path(tmp) / "lifecycle.json")
                ).register(cert)
        self.assert_nothing_operational_ran()


if __name__ == "__main__":
    unittest.main()
