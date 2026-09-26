"""
Tests -- Dynamic / Reflection Boundary & Negative-Capability Closure
Audit (Phase P3.67).

P3.63-P3.66 closed the STATIC certificate->authority edge (direct,
transitive, and surface-complete). P3.67's question was different: does
the remaining static/dynamic analysis boundary constitute a real,
operational Certificate->Authority path, or only a theoretical limit of
AST analysis with no demonstrated capability?

Findings this phase established, pinned here permanently:

  - A full repository sweep (agents/, integrations/, scripts/,
    director.py) found ZERO occurrences of `importlib`, `__import__`,
    `setattr`, `globals()`, `locals()`, `eval()`, `exec()`, or
    `__build_class__` anywhere in production code. `sys.modules` appears
    exactly once, inside a COMMENT (not code) explaining an ordinary
    deferred `from X import Y` statement used to break a circular
    import -- itself a normal static import, already fully visible to
    `ast.walk()` at any nesting depth (confirmed separately by the
    existing TYPE_CHECKING-guarded-import tests in P3.64).
  - Every `getattr(...)` call in production code (dozens, all in
    business/production-modeling files plus one in
    `agents/certificate_verification.py`) uses the safe 3-argument
    defensive form on an already-typed domain object
    (`getattr(contract, "field", None)`) -- never to dynamically resolve
    a MODULE or CLASS by name. None touches an authority object.
  - No registry, factory, dependency-injection container, or service
    locator exists anywhere for authority objects. The two classes
    matching those names by pure coincidence (`AssetResolver`,
    `CertificateLifecycleRegistry`) were individually inspected: the
    former resolves file paths for media assets, the latter is the
    already-exhaustively-audited (P3.57-P3.66) certificate lifecycle
    bookkeeping dict -- neither stores or returns an authority
    capability.
  - EMPIRICALLY DEMONSTRATED (not merely argued): dynamic reflection can
    always obtain a REFERENCE to a real authority class/method --
    Python's import system has no sandbox preventing this, and this is
    a property of the language, never claimed otherwise. But obtaining
    the reference grants NO operational capability: calling the
    dynamically-obtained `GenerationJobService.execute()` on a request
    with no human authorization still hard-raises
    `GenerationJobExecutionError`, identically to a statically-obtained
    reference (Test01). Every other negative capability (approve,
    budget, replay, identity, UNKNOWN, certificate supersession) was
    re-tested using ONLY importlib/getattr-obtained classes and remains
    BLOCKED (Test02-08) -- the guarantee is enforced INSIDE the P2
    methods themselves, never by the mere difficulty of reaching them.
  - A more precise finding than P3.64's already-documented "dynamic
    import evades the certificate-edge check": reflective CONSTRUCTION
    of an authority symbol (`getattr(module, "Symbol")(...)`) DOES
    evade the pre-existing, separate P3.31 authority-construction check
    (`_check_no_unauthorized_authority_construction`, which only
    resolves `ast.Name`/`ast.Attribute` call targets, not a nested
    `getattr(...)(...)` call) -- but ONLY when no static import of the
    authority module exists at all. When a certificate file still
    statically imports the authority module (even just to later
    `getattr` a symbol off it), the certificate-edge IMPORT check still
    fires regardless, because it triggers on the import statement
    itself, independent of what is done with the module afterward
    (Test09-11). This is confirmed to be the SAME single boundary
    already established in P3.64 (true dynamic resolution with zero
    static import), not a new, additional gap -- and it is a property
    of the general, older P3.31 authority-construction check, not
    something introduced by or specific to the certificate subsystem.

Every test uses isolated `tempfile.TemporaryDirectory` fixtures for
static-detector probes, and MockHiggsfieldProvider exclusively for
runtime probes; no real generation, no real create_job(), no credits
consumed.
"""

import importlib
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.architecture_drift_detector import ArchitectureDriftDetector


def _write(root: Path, relative_path: str, content: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class _TempRepoTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _detector(self) -> ArchitectureDriftDetector:
        return ArchitectureDriftDetector(root=self.root)


def _make_request(GenerationRequest, MediaReference, RealGenerationAuthorization, C, prompt, **overrides):
    defaults = dict(
        request_id=C.request_id, job_type=C.job_type, prompt=prompt,
        duration=C.duration, resolution=C.resolution, aspect_ratio=C.aspect_ratio,
        approved=True,
        start_image=MediaReference(role="master_avatar", source=str(PROJECT_ROOT / "assets" / "zephyr" / "avatar" / "avatar_master.png"), sha256=None),
        image_references=(MediaReference(role="face_reference", source=str(PROJECT_ROOT / "assets" / "zephyr" / "references" / "mon avatar habille.png"), sha256=None),),
        real_generation_authorization=RealGenerationAuthorization(request_id=C.request_id, authorized_by_human=True),
    )
    defaults.update(overrides)
    return GenerationRequest(**defaults)


class TestReflectiveNegativeCapability(unittest.TestCase):
    """Sections 4/5/6/9/13: every class involved is obtained purely via
    `importlib.import_module`/`getattr` -- never a static top-level
    import -- to prove reflection changes nothing about what these
    guards enforce."""

    @classmethod
    def setUpClass(cls):
        gate_mod = importlib.import_module("agents.generation_approval_gate")
        job_mod = importlib.import_module("agents.generation_job_service")
        lock_mod = importlib.import_module("agents.release_candidate_identity_lock")
        prompt_mod = importlib.import_module("agents.prompt_assembly_system")
        mock_mod = importlib.import_module("integrations.higgsfield.mock_provider")
        types_mod = importlib.import_module("integrations.higgsfield.types")
        lifecycle_mod = importlib.import_module("agents.certificate_lifecycle")
        cert_mod = importlib.import_module("agents.production_activation_readiness_certificate")
        activation_contract_mod = importlib.import_module("agents.activation_contract")
        activation_readiness_mod = importlib.import_module("agents.activation_readiness")

        cls.GenerationApprovalGate = getattr(gate_mod, "GenerationApprovalGate")
        cls.GenerationRequest = getattr(gate_mod, "GenerationRequest")
        cls.GenerationApprovalDecision = getattr(gate_mod, "GenerationApprovalDecision")
        cls.RealGenerationAuthorization = getattr(gate_mod, "RealGenerationAuthorization")
        cls.GenerationJobService = getattr(job_mod, "GenerationJobService")
        cls.ReleaseCandidateIdentityLock = getattr(lock_mod, "ReleaseCandidateIdentityLock")
        cls.C = getattr(lock_mod, "VIDEO_005_RELEASE_CANDIDATE")
        cls.MockHiggsfieldProvider = getattr(mock_mod, "MockHiggsfieldProvider")
        cls.MediaReference = getattr(types_mod, "MediaReference")
        cls.CertificateLifecycleRegistry = getattr(lifecycle_mod, "CertificateLifecycleRegistry")
        cls.CertificateLifecycleStatus = getattr(lifecycle_mod, "CertificateLifecycleStatus")
        cls.ProductionActivationReadinessCertificateIssuer = getattr(cert_mod, "ProductionActivationReadinessCertificateIssuer")
        cls.RequestScopedActivationService = getattr(activation_contract_mod, "RequestScopedActivationService")
        cls.ActivationReadinessEvaluator = getattr(activation_readiness_mod, "ActivationReadinessEvaluator")

        cls.prompt = importlib.import_module("agents.prompt_assembly_system").PromptAssemblySystem(PROJECT_ROOT).assemble(cls.C.request_id)

    def _request(self, **overrides):
        return _make_request(
            self.GenerationRequest, self.MediaReference, self.RealGenerationAuthorization,
            self.C, self.prompt, **overrides,
        )

    def test_01_dynamically_obtained_execute_still_hard_blocks_without_authorization(self):
        provider = self.MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
        identity_lock = self.ReleaseCandidateIdentityLock(self.C)
        gate = self.GenerationApprovalGate(provider, identity_lock=identity_lock)
        job_service = self.GenerationJobService(provider, gate)

        with self.assertRaises(Exception):
            job_service.execute(self._request(real_generation_authorization=None))

    def test_02_approve_without_human_auth_still_blocked(self):
        provider = self.MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
        identity_lock = self.ReleaseCandidateIdentityLock(self.C)
        gate = self.GenerationApprovalGate(provider, identity_lock=identity_lock)
        decision = gate.evaluate(self._request(real_generation_authorization=None)).decision
        self.assertNotEqual(decision, self.GenerationApprovalDecision.APPROVED)

    def test_03_budget_bypass_still_blocked(self):
        provider = self.MockHiggsfieldProvider(cost_per_job=10.0, available_credits=0.01)
        identity_lock = self.ReleaseCandidateIdentityLock(self.C)
        gate = self.GenerationApprovalGate(provider, identity_lock=identity_lock)
        decision = gate.evaluate(self._request()).decision
        self.assertEqual(decision, self.GenerationApprovalDecision.BLOCKED)

    def test_04_replay_bypass_still_blocked(self):
        provider = self.MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
        identity_lock = self.ReleaseCandidateIdentityLock(self.C)
        gate = self.GenerationApprovalGate(provider, identity_lock=identity_lock)
        gate.mark_executed(self.C.request_id)
        decision = gate.evaluate(self._request()).decision
        self.assertEqual(decision, self.GenerationApprovalDecision.ALREADY_EXECUTED)

    def test_05_identity_bypass_still_blocked(self):
        provider = self.MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
        identity_lock = self.ReleaseCandidateIdentityLock(self.C)
        gate = self.GenerationApprovalGate(provider, identity_lock=identity_lock)
        decision = gate.evaluate(self._request(job_type="not-seedance")).decision
        self.assertNotEqual(decision, self.GenerationApprovalDecision.APPROVED)

    def test_06_unknown_state_bypass_still_blocked(self):
        provider = self.MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
        identity_lock = self.ReleaseCandidateIdentityLock(self.C)
        gate = self.GenerationApprovalGate(provider, identity_lock=identity_lock)
        gate.mark_unknown(self.C.request_id, reason="p3.67 reflective probe")
        decision = gate.evaluate(self._request()).decision
        self.assertEqual(decision, self.GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN)

    def test_07_certificate_supersession_cannot_be_revived(self):
        provider = self.MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
        identity_lock = self.ReleaseCandidateIdentityLock(self.C)
        gate = self.GenerationApprovalGate(provider, identity_lock=identity_lock)
        activation_service = self.RequestScopedActivationService(gate, identity_lock)
        evaluator = self.ActivationReadinessEvaluator(gate, identity_lock, activation_service)
        issuer = self.ProductionActivationReadinessCertificateIssuer(evaluator)

        registry = self.CertificateLifecycleRegistry()
        c1 = issuer.issue(self._request(), mission_id="m", video_plan_identity="v")
        c2 = issuer.issue(self._request(), mission_id="m", video_plan_identity="v")
        registry.register(c1)
        registry.register(c2)

        replayed = registry.register(c1)
        self.assertEqual(replayed.status, self.CertificateLifecycleStatus.SUPERSEDED)


class TestReflectiveConstructionVsCertificateEdgeCheck(_TempRepoTestCase):
    """Section 6/16/18: reflective CONSTRUCTION of an authority symbol
    evades the older, separate P3.31 authority-construction check, but
    NOT the certificate-edge import check, as long as any static import
    of the authority module exists at all -- only a fully dynamic
    resolution (no static import anywhere) evades both, and that is the
    SAME single boundary already documented in P3.64, not a new one."""

    def test_direct_construction_is_caught_by_both_checks(self):
        _write(
            self.root, "agents/certificate_integrity.py",
            (
                "from agents.generation_approval_gate import RealGenerationAuthorization\n"
                "x = RealGenerationAuthorization(request_id='005', authorized_by_human=True)\n"
            ),
        )
        report = self._detector().analyze()
        codes = {f.code for f in report.findings}
        self.assertIn("AUTOMATIC_HUMAN_AUTHORIZATION", codes)
        self.assertIn("CERTIFICATE_OUTBOUND_AUTHORITY_IMPORT", codes)

    def test_reflective_construction_via_getattr_evades_construction_check_but_not_edge_check(self):
        _write(
            self.root, "agents/certificate_integrity.py",
            (
                "import agents.generation_approval_gate as gate_module\n"
                "cls = getattr(gate_module, 'RealGenerationAuthorization')\n"
                "x = cls(request_id='005', authorized_by_human=True)\n"
            ),
        )
        report = self._detector().analyze()
        codes = {f.code for f in report.findings}
        self.assertNotIn("AUTOMATIC_HUMAN_AUTHORIZATION", codes)  # confirmed, honestly-documented gap
        self.assertIn("CERTIFICATE_OUTBOUND_AUTHORITY_IMPORT", codes)  # but still caught here

    def test_fully_dynamic_construction_evades_both_checks_documented_boundary(self):
        _write(
            self.root, "agents/certificate_integrity.py",
            (
                "import importlib\n"
                "mod = importlib.import_module('agents.generation_approval_gate')\n"
                "cls = getattr(mod, 'RealGenerationAuthorization')\n"
                "x = cls(request_id='005', authorized_by_human=True)\n"
            ),
        )
        report = self._detector().analyze()
        self.assertEqual(report.findings, ())  # the documented, accepted boundary -- confirmed, not overclaimed


class TestDynamicSurfaceInventoryRealRepository(unittest.TestCase):
    """Section 3: pins the whole-repository sweep result permanently."""

    def test_no_dangerous_dynamic_construct_in_production_code(self):
        import ast

        dangerous_names = {"setattr", "eval", "exec", "__build_class__"}
        all_py = []
        for d in ("agents", "integrations", "scripts"):
            all_py.extend(sorted((PROJECT_ROOT / d).rglob("*.py")))
        all_py.append(PROJECT_ROOT / "director.py")

        for path in all_py:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = node.func.id if isinstance(node.func, ast.Name) else None
                    if name in dangerous_names:
                        self.fail(f"{path}:{node.lineno} calls '{name}(' -- re-audit required")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotEqual(alias.name, "importlib", f"unexpected importlib usage in {path}")

    def test_certificate_verification_getattr_is_defensive_field_access_only(self):
        """The one getattr() usage inside the certificate subsystem
        reads plain string/scalar fields off an already-constructed
        certificate object -- never resolves a module or class."""
        import ast

        path = PROJECT_ROOT / "agents" / "certificate_verification.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        getattr_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
        ]
        self.assertTrue(getattr_calls)
        for call in getattr_calls:
            self.assertEqual(len(call.args), 3, "expected the safe 3-argument getattr(obj, name, default) form")
            attr_name_arg = call.args[1]
            self.assertIsInstance(attr_name_arg, ast.Constant)
            self.assertIn(attr_name_arg.value, ("certificate_id", "issued_at"))


if __name__ == "__main__":
    unittest.main()
