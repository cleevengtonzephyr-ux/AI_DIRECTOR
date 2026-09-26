"""
Tests -- Certificate Guardrail Completeness, Bypass Resistance & Contract
Closure Audit (Phase P3.64).

P3.63 added ONE architectural rule -- NO CERTIFICATE -> AUTHORITY EDGE --
enforced by `ArchitectureDriftDetector._check_no_certificate_authority_edge()`.
P3.64's job was to determine precisely what that guardrail does and does
not catch, by testing every plausible bypass class against real,
isolated fixtures -- never by assumption.

Findings this phase established, each pinned here permanently:
  - Direct imports, module imports, symbol aliases, and TYPE_CHECKING-
    guarded imports are ALL detected (the AST walk visits every nesting
    level, and the check is indifferent to `asname`).
  - A one-hop re-export through an intermediate, otherwise-unclassified
    helper file was NOT detected before this phase -- demonstrated with
    a synthetic fixture, then closed with a new, narrowly-scoped,
    single-hop check. NOTE (superseded by Phase P3.65): that single-hop
    check was later generalized into a bounded, cycle-safe, ARBITRARY-
    depth breadth-first search (`_check_no_transitive_certificate_
    authority_edge()`) once P3.65 demonstrated a two-hop chain still
    evaded the single-hop version -- see `tests/test_p3_65_certificate_
    guardrail_transitive_dependency.py`. The finding code
    (`CERTIFICATE_INDIRECT_AUTHORITY_IMPORT`) is unchanged; only the
    underlying resolution depth grew.
  - Relative imports, dynamic imports (`importlib.import_module`,
    `__import__`), reflection (`getattr`/`sys.modules`), inert string
    references, and structural typing (`Protocol` with no import of the
    real certificate type) are NOT detected -- confirmed empirically,
    and accepted as documented, out-of-scope limitations consistent
    with every other check in this detector (AST-only, no data-flow, no
    runtime instrumentation).

Every test uses isolated `tempfile.TemporaryDirectory` fixtures (never
the real repository, except for the explicit real-repo confirmation
class) and never touches Higgsfield, a real Provider, or credits.
"""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.architecture_drift_detector import ArchitectureDriftDetector, DriftStatus, Severity
from agents.canonical_architecture_contract import CANONICAL_ARCHITECTURE_CONTRACT

_EDGE_CODES = {
    "CERTIFICATE_TO_AUTHORITY_IMPORT",
    "CERTIFICATE_OUTBOUND_AUTHORITY_IMPORT",
    "CERTIFICATE_OUTBOUND_AUTHORITY_CALL",
    "CERTIFICATE_INDIRECT_AUTHORITY_IMPORT",
}


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

    def _edge_findings(self, report):
        return [f for f in report.findings if f.code in _EDGE_CODES]


class TestRealRepositoryZeroEdges(unittest.TestCase):
    """Section 3/13/21: the real repository has zero certificate<->
    authority edges of any kind this guardrail knows how to detect."""

    def test_real_repository_has_no_certificate_authority_edges(self):
        report = ArchitectureDriftDetector(contract=CANONICAL_ARCHITECTURE_CONTRACT).analyze()
        hits = [f for f in report.findings if f.code in _EDGE_CODES]
        self.assertEqual(hits, [])
        self.assertEqual(report.status, DriftStatus.NO_DRIFT)


class TestBypassClassA_DirectImport(_TempRepoTestCase):
    """Class A. `from agents.certificate_x import Y` in an authority file."""

    def test_detected(self):
        _write(
            self.root, "agents/generation_approval_gate.py",
            "from agents.certificate_integrity import verify_integrity\n",
        )
        report = self._detector().analyze()
        self.assertTrue(any(f.code == "CERTIFICATE_TO_AUTHORITY_IMPORT" for f in report.findings))


class TestBypassClassB_ModuleImport(_TempRepoTestCase):
    """Class B. `import agents.certificate_x as alias`."""

    def test_detected(self):
        _write(
            self.root, "agents/generation_approval_gate.py",
            "import agents.certificate_integrity as cert\n",
        )
        report = self._detector().analyze()
        self.assertTrue(any(f.code == "CERTIFICATE_TO_AUTHORITY_IMPORT" for f in report.findings))


class TestBypassClassC_AliasedSymbolImport(_TempRepoTestCase):
    """Class C. `from agents.certificate_x import Y as Z`."""

    def test_detected(self):
        _write(
            self.root, "agents/generation_approval_gate.py",
            "from agents.certificate_integrity import ISSUER_IDENTITY as ISSUER\n",
        )
        report = self._detector().analyze()
        self.assertTrue(any(f.code == "CERTIFICATE_TO_AUTHORITY_IMPORT" for f in report.findings))


class TestBypassClassD_AttributeAccessAfterAlias(_TempRepoTestCase):
    """Class D. `cert.Symbol` after a static module-alias import -- the
    import statement itself already trips the check; attribute access
    adds nothing the detector needs to separately understand."""

    def test_detected_via_the_underlying_import(self):
        _write(
            self.root, "agents/generation_approval_gate.py",
            "import agents.certificate_integrity as cert\nx = cert.ISSUER_IDENTITY\n",
        )
        report = self._detector().analyze()
        hits = [f for f in report.findings if f.code == "CERTIFICATE_TO_AUTHORITY_IMPORT"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].line, 1)  # the import line, not the attribute-access line


class TestBypassClassE_RelativeImport(_TempRepoTestCase):
    """Class E. `from .certificate_x import Y`.

    CLOSED IN P3.76-R1 (relative imports are now resolved to their
    absolute module before any check runs). Historical note -- P3.64
    CONFIRMED NOT DETECTED: a relative import's `ast.ImportFrom.module`
    is the bare submodule name ("certificate_integrity"), never the
    absolute dotted path ("agents.certificate_integrity") this
    detector's prefix-matching compares against. This is an honestly
    documented, accepted gap (Section 9), NOT silently promised covered
    -- and it has zero real exposure: a repository-wide search (this
    phase) confirmed ZERO relative imports exist anywhere in `agents/`,
    `integrations/`, or `director.py` today; every file in this
    repository uses the same `sys.path.insert(PROJECT_ROOT)` + absolute-
    import convention. Fixing this would require reworking the SAME
    prefix-matching primitive every other check in this detector
    already relies on (Business/Production-Modeling forbidden imports,
    Second-Authority-Core-Signal) -- out of scope for a certificate-only
    guardrail per Section 10's prohibition on a general detector
    rewrite.
    """

    def test_detected_since_p3_76_r1(self):
        _write(
            self.root, "agents/generation_approval_gate.py",
            "from .certificate_integrity import ISSUER_IDENTITY\n",
        )
        report = self._detector().analyze()
        self.assertEqual(
            [f.code for f in self._edge_findings(report)], ["CERTIFICATE_TO_AUTHORITY_IMPORT"]
        )

    def test_repository_uses_zero_relative_imports_today(self):
        """The gap above has no real exposure: nothing in production
        code uses this form at all."""
        import ast

        for rel_dir in ("agents", "integrations"):
            for path in sorted((PROJECT_ROOT / rel_dir).rglob("*.py")):
                tree = ast.parse(path.read_text(encoding="utf-8-sig"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.level and node.level > 0:
                        self.fail(f"unexpected relative import in {path}")


class TestBypassClassF_DynamicImportlib(_TempRepoTestCase):
    """Class F. `importlib.import_module('agents.certificate_x')`.

    CONFIRMED NOT DETECTED and NOT CLAIMED COVERED: the detector only
    inspects `ast.Import`/`ast.ImportFrom` nodes; a call passing a
    module name as a plain string literal is an `ast.Call`, structurally
    indistinguishable (without full data-flow analysis) from any other
    call with a string argument. Static AST analysis does not prove the
    absence of dynamic imports -- documented, not silently promised
    otherwise (Section 9)."""

    def test_not_detected_confirming_the_documented_gap(self):
        _write(
            self.root, "agents/generation_approval_gate.py",
            "import importlib\ncert = importlib.import_module('agents.certificate_integrity')\n",
        )
        report = self._detector().analyze()
        self.assertEqual(self._edge_findings(report), [])


class TestBypassClassG_DunderImport(_TempRepoTestCase):
    """Class G. `__import__('agents.certificate_x')` -- same limitation
    class as F, confirmed separately since it is a different call form."""

    def test_not_detected_confirming_the_documented_gap(self):
        _write(
            self.root, "agents/generation_approval_gate.py",
            "cert = __import__('agents.certificate_integrity')\n",
        )
        report = self._detector().analyze()
        self.assertEqual(self._edge_findings(report), [])


class TestBypassClassH_ReflectionGetattr(_TempRepoTestCase):
    """Class H. `getattr(sys.modules[...], 'Symbol')` -- inherits the
    same limitation as F/G: the module reference was never obtained via
    a detectable `ast.Import`/`ast.ImportFrom` node."""

    def test_not_detected_confirming_the_documented_gap(self):
        _write(
            self.root, "agents/generation_approval_gate.py",
            (
                "import sys\n"
                "cert = sys.modules.get('agents.certificate_integrity')\n"
                "x = getattr(cert, 'ISSUER_IDENTITY', None)\n"
            ),
        )
        report = self._detector().analyze()
        self.assertEqual(self._edge_findings(report), [])


class TestBypassClassI_StringReferenceOnly(_TempRepoTestCase):
    """Class I. An inert string that merely resembles a dotted
    certificate reference, never resolved by anything. Correctly never
    flagged -- identical in kind to a docstring/comment mention, which
    P3.31's own detector already guarantees never triggers drift."""

    def test_not_flagged(self):
        _write(
            self.root, "agents/generation_approval_gate.py",
            "REF = 'agents.certificate_integrity.ISSUER_IDENTITY'\n",
        )
        report = self._detector().analyze()
        self.assertEqual(self._edge_findings(report), [])


class TestBypassClassJK_ReexportViaHelper(_TempRepoTestCase):
    """Class J/K. A certificate symbol re-exported through an
    intermediate, otherwise-unclassified helper file, then imported by
    an authority-surface file.

    THIS WAS A REAL GAP before P3.64 (empirically demonstrated against
    the P3.63 detector before any indirect-edge check existed) --
    CLOSED in P3.64 for exactly one hop, then GENERALIZED to arbitrary
    depth in P3.65 (`_check_no_transitive_certificate_authority_edge`,
    a bounded breadth-first search over the already-built import graph
    -- see `tests/test_p3_65_certificate_guardrail_transitive_
    dependency.py` for the full depth 2/3/4+ matrix)."""

    def test_now_detected(self):
        _write(
            self.root, "agents/some_helper.py",
            "from agents.certificate_integrity import ISSUER_IDENTITY\n",
        )
        _write(
            self.root, "agents/generation_approval_gate.py",
            "from agents.some_helper import ISSUER_IDENTITY\n",
        )
        report = self._detector().analyze()
        hits = [f for f in report.findings if f.code == "CERTIFICATE_INDIRECT_AUTHORITY_IMPORT"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].file, "agents/generation_approval_gate.py")

    def test_control_helper_without_certificate_import_is_not_flagged(self):
        """False-positive control: an ordinary helper unrelated to
        certificates must never be flagged just for being imported by
        an authority-surface file."""
        _write(self.root, "agents/some_helper.py", "X = 1\n")
        _write(
            self.root, "agents/generation_approval_gate.py",
            "from agents.some_helper import X\n",
        )
        report = self._detector().analyze()
        self.assertEqual(self._edge_findings(report), [])

    def test_two_hop_chain_is_now_detected_by_p3_65(self):
        """helper1 -> helper2 -> certificate, authority -> helper1: as of
        P3.65, this IS detected -- superseding this test's former
        assertion that it was an accepted residual gap (P3.64 Section
        10). See `tests/test_p3_65_certificate_guardrail_transitive_
        dependency.py` for the full depth analysis and rationale."""
        _write(
            self.root, "agents/helper_two.py",
            "from agents.certificate_integrity import ISSUER_IDENTITY\n",
        )
        _write(
            self.root, "agents/helper_one.py",
            "from agents.helper_two import ISSUER_IDENTITY\n",
        )
        _write(
            self.root, "agents/generation_approval_gate.py",
            "from agents.helper_one import ISSUER_IDENTITY\n",
        )
        report = self._detector().analyze()
        hits = [f for f in report.findings if f.code == "CERTIFICATE_INDIRECT_AUTHORITY_IMPORT"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].file, "agents/generation_approval_gate.py")


class TestBypassClassL_TypeCheckingGuardedImport(_TempRepoTestCase):
    """Class L. A certificate import guarded by `if TYPE_CHECKING:`,
    used only in a parameter annotation.

    CONFIRMED DETECTED, deliberately: `ast.walk()` visits nodes at every
    nesting depth, including inside an `if` body, so a TYPE_CHECKING-
    guarded import is exactly as visible as a top-level one. This is an
    intentional design position, not an oversight: unlike
    `agents/activation_contract.py`'s types (which Domain B has a
    long-established, audited, legitimate need to reference, per
    P3.28-P3.30 -- reflected by those specific modules being absent from
    `FORBIDDEN_IMPORT_PREFIXES_FOR_PRODUCTION_MODELING`), no
    authority-surface file has ANY established legitimate need, type-only
    or otherwise, to reference a certificate type today. Should one ever
    arise, the correct remedy mirrors that precedent: a deliberate,
    documented, CONTRACT_VERSION-bumping narrowing of the forbidden set
    -- never a silent TYPE_CHECKING carve-out added to this check."""

    def test_detected(self):
        _write(
            self.root, "agents/generation_approval_gate.py",
            (
                "from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n"
                "    from agents.certificate_integrity import CertificateProvenanceIntegrityReport\n"
                "\n"
                "def evaluate(report: 'CertificateProvenanceIntegrityReport') -> None:\n"
                "    pass\n"
            ),
        )
        report = self._detector().analyze()
        self.assertTrue(any(f.code == "CERTIFICATE_TO_AUTHORITY_IMPORT" for f in report.findings))


class TestBypassClassM_ReturnTypeAnnotation(_TempRepoTestCase):
    """Class M. `def evaluate() -> Certificate:` -- the import needed to
    reference the return-type name is the same `ast.ImportFrom` node
    Class A/L already cover; detection does not depend on whether the
    imported name is used as a parameter or return annotation."""

    def test_detected(self):
        _write(
            self.root, "agents/generation_approval_gate.py",
            (
                "from agents.production_activation_readiness_certificate import "
                "ProductionActivationReadinessCertificate\n"
                "\n"
                "def issue_something() -> ProductionActivationReadinessCertificate:\n"
                "    ...\n"
            ),
        )
        report = self._detector().analyze()
        self.assertTrue(any(f.code == "CERTIFICATE_TO_AUTHORITY_IMPORT" for f in report.findings))


class TestBypassClassN_StructuralProtocol(_TempRepoTestCase):
    """Class N. A locally-defined `Protocol` with fields shaped like a
    certificate, importing NOTHING from the real certificate module.

    CONFIRMED NOT DETECTED, and cannot be by any import-based check: no
    certificate module is imported at all, so there is no import edge to
    see. Whether a real certificate instance is ever passed to something
    typed against this Protocol is a runtime question requiring a real
    type-checker plus data-flow analysis -- explicitly out of scope
    (Section 10: no full Python analyzer). Documented as a structural
    limitation inherent to import-based static analysis, not specific to
    this guardrail."""

    def test_not_detected_confirming_the_documented_gap(self):
        _write(
            self.root, "agents/generation_approval_gate.py",
            (
                "from typing import Protocol\n"
                "class CertificateLike(Protocol):\n"
                "    readiness_result: str\n"
                "    unknown_state: bool\n"
            ),
        )
        report = self._detector().analyze()
        self.assertEqual(self._edge_findings(report), [])


class TestFalsePositiveBoundary(_TempRepoTestCase):
    """Section 4/15. Legitimate, already-sanctioned usage must never be
    flagged."""

    def test_issuer_composing_activation_readiness_evaluator_is_not_flagged(self):
        _write(
            self.root, "agents/production_activation_readiness_certificate.py",
            (
                "from agents.activation_readiness import ActivationReadinessEvaluator\n"
                "from agents.generation_approval_gate import GenerationRequest\n"
            ),
        )
        report = self._detector().analyze()
        self.assertEqual(self._edge_findings(report), [])

    def test_informational_layer_importing_the_certificate_type_is_not_flagged(self):
        _write(
            self.root, "agents/certificate_verification.py",
            "from agents.production_activation_readiness_certificate import "
            "ProductionActivationReadinessCertificate\n",
        )
        report = self._detector().analyze()
        self.assertEqual(self._edge_findings(report), [])

    def test_test_domain_file_is_never_scanned(self):
        _write(
            self.root, "tests/test_certificate_integrity.py",
            "from agents.generation_approval_gate import GenerationApprovalGate\n",
        )
        report = self._detector().analyze()
        self.assertEqual(self._edge_findings(report), [])


class TestMutationRoundTrip(_TempRepoTestCase):
    """Section 7. Full protocol: introduce -> detect -> remove -> NO_DRIFT."""

    def test_direct_edge_round_trip(self):
        violating_file = self.root / "agents" / "generation_approval_gate.py"
        _write(
            self.root, "agents/generation_approval_gate.py",
            "from agents.certificate_integrity import verify_integrity\n",
        )
        drifted = self._detector().analyze()
        self.assertEqual(drifted.status, DriftStatus.DRIFT_DETECTED)

        violating_file.unlink()

        clean = self._detector().analyze()
        self.assertEqual(clean.status, DriftStatus.NO_DRIFT)
        self.assertEqual(clean.findings, ())

    def test_indirect_edge_round_trip(self):
        helper_file = self.root / "agents" / "some_helper.py"
        _write(self.root, "agents/some_helper.py", "from agents.certificate_integrity import ISSUER_IDENTITY\n")
        _write(self.root, "agents/generation_approval_gate.py", "from agents.some_helper import ISSUER_IDENTITY\n")

        drifted = self._detector().analyze()
        self.assertEqual(drifted.status, DriftStatus.DRIFT_DETECTED)

        helper_file.unlink()
        (self.root / "agents" / "generation_approval_gate.py").unlink()

        clean = self._detector().analyze()
        self.assertEqual(clean.status, DriftStatus.NO_DRIFT)
        self.assertEqual(clean.findings, ())


class TestDetectorSoundness(_TempRepoTestCase):
    """Section 17. Findings are explicit, deterministic, and correctly
    attributed."""

    def test_finding_identifies_file_edge_and_direction_unambiguously(self):
        _write(
            self.root, "agents/human_authorization_handoff.py",
            "from agents.certificate_lifecycle import CertificateLifecycleRegistry\n",
        )
        report = self._detector().analyze()
        hit = next(f for f in report.findings if f.code == "CERTIFICATE_TO_AUTHORITY_IMPORT")
        self.assertEqual(hit.file, "agents/human_authorization_handoff.py")
        self.assertEqual(hit.line, 1)
        self.assertEqual(hit.severity, Severity.CRITICAL)
        self.assertIn("certificate", hit.violated_rule.lower())
        self.assertTrue(hit.evidence)
        self.assertTrue(hit.explanation)

    def test_two_analyses_of_the_same_fixtures_are_deterministic(self):
        _write(
            self.root, "agents/generation_approval_gate.py",
            "from agents.certificate_integrity import verify_integrity\n",
        )
        first = self._detector().analyze()
        second = self._detector().analyze()
        self.assertEqual(first.findings, second.findings)
        self.assertEqual(first.status, second.status)


if __name__ == "__main__":
    unittest.main()
