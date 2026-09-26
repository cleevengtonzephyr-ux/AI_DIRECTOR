"""
Tests -- Certificate Boundary Enforcement & Static Analysis Completeness
Audit (Phase P3.66).

P3.63 established the contract (NO CERTIFICATE -> AUTHORITY EDGE), P3.64
closed a one-hop re-export bypass, P3.65 generalized detection to
arbitrary transitive depth. P3.66 audited the guardrail's SURFACE
completeness rather than its graph depth: which directories/files are
actually scanned, whether any certificate-bearing or authority-bearing
code exists outside the declared surfaces, and whether Python usage
syntax (decorators, default values, re-assignment, TypedDict/Protocol,
string references) can carry a certificate reference around the
import-based detection mechanism.

Conclusion this phase reached, pinned here permanently:
  - Every one of the 22 currently UNCLASSIFIED_LEGACY files under
    `agents/` was inspected: none imports a certificate-subsystem
    module, none constructs an AUTHORITY_BEARING_SYMBOL outside its
    allowlist (already governed by a separate, pre-existing check), and
    the two that are genuinely orphaned/dead V1 code
    (`agents/job_monitor.py`, `agents/higgsfield_executor.py`) are
    reachable from nothing. No certificate code exists outside
    `CERTIFICATE_SUBSYSTEM_FILES`; no authority-bearing code was found
    outside the declared authority surface.
  - Detection operates at the IMPORT-EDGE level, never at the usage-
    syntax level: once a certificate symbol is imported into an
    authority-surface file (or vice versa), it does not matter whether
    it is then used as a decorator, a default parameter value, a
    module-level re-assignment, a function return value, or a class
    attribute -- the import itself is already flagged, regardless of
    downstream usage. This is a strength, not a gap: it means the
    detector does not need bespoke handling for every Python usage
    form, only for the (already-tested) import statement forms.
  - A double-dot relative import (`from ..certificate_x import Y`)
    behaves identically to a single-dot one (P3.64 Class E): NOT
    detected, for the same reason (a relative import's `ast.ImportFrom.
    module` never carries the absolute package prefix this detector's
    matching relies on) -- and, like the single-dot form, has zero real
    usage anywhere in this repository today.
  - `TypedDict`/structural forms with NO import of the real certificate
    type, and inert string/f-string references, remain undetected and
    out of scope, consistent with P3.64's `Protocol` finding.

Every test uses isolated `tempfile.TemporaryDirectory` fixtures (never
the real repository, except the explicit real-repo confirmation class)
and never touches Higgsfield, a real Provider, or credits.
"""

import ast
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.architecture_drift_detector import ArchitectureDriftDetector, DriftStatus
from agents.canonical_architecture_contract import (
    CANONICAL_ARCHITECTURE_CONTRACT,
    AUTHORITY_BEARING_SYMBOLS,
    Domain,
)

_EDGE_CODES = {
    "CERTIFICATE_TO_AUTHORITY_IMPORT",
    "CERTIFICATE_OUTBOUND_AUTHORITY_IMPORT",
    "CERTIFICATE_OUTBOUND_AUTHORITY_CALL",
    "CERTIFICATE_INDIRECT_AUTHORITY_IMPORT",
    "CERTIFICATE_INDIRECT_OUTBOUND_AUTHORITY_IMPORT",
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


# ----------------------------------------------------------------------
# Section 3/4/5: surface inventory -- no certificate/authority code
# exists outside the declared surfaces, in the REAL repository.
# ----------------------------------------------------------------------


class TestSurfaceInventory(unittest.TestCase):
    def test_no_unclassified_agents_file_imports_a_certificate_module(self):
        """Permanent pin of the P3.66 manual audit finding: every
        currently UNCLASSIFIED_LEGACY file under agents/ was checked --
        none imports a certificate-subsystem module directly. If a
        future file ever did, and were reachable from the authority
        surface, P3.65's transitive check would already catch it; this
        test additionally confirms the CURRENT unclassified population
        contains no such file at all."""

        contract = CANONICAL_ARCHITECTURE_CONTRACT
        cert_prefixes = contract.certificate_subsystem_import_prefixes

        for path in sorted((PROJECT_ROOT / "agents").glob("*.py")):
            rel = f"agents/{path.name}"
            if contract.domain_of(rel) != Domain.UNCLASSIFIED_LEGACY:
                continue
            if rel in contract.certificate_subsystem_files:
                continue  # the subsystem's own internal composition is expected and legitimate
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=rel)
            for node in ast.walk(tree):
                module = None
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name
                        self.assertNotIn(
                            module, cert_prefixes,
                            f"unclassified file {rel} imports certificate module '{module}'",
                        )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn(
                        node.module, cert_prefixes,
                        f"unclassified file {rel} imports certificate module '{node.module}'",
                    )

    def test_no_unclassified_agents_file_constructs_an_unauthorized_authority_symbol(self):
        """Cross-check against the PRE-EXISTING, separate authority-
        construction guardrail (not new to P3.66): confirms it already
        covers every unclassified file, not just the declared domains."""

        report = ArchitectureDriftDetector(contract=CANONICAL_ARCHITECTURE_CONTRACT).analyze()
        hits = [
            f for f in report.findings
            if f.code in ("AUTHORITY_CONSTRUCTOR_OUTSIDE_ALLOWLIST", "AUTOMATIC_ACTIVATION_CONSTRUCTION", "AUTOMATIC_HUMAN_AUTHORIZATION")
        ]
        self.assertEqual(hits, [])

    def test_orphaned_v1_files_are_reachable_from_nothing(self):
        """agents/job_monitor.py and agents/higgsfield_executor.py both
        name-resemble execution paths but are confirmed, this phase, to
        be imported by NOTHING anywhere in agents/, integrations/,
        scripts/, tests/, or director.py -- dead code, not a live
        architectural surface."""

        all_py = []
        for d in ("agents", "integrations", "scripts", "tests"):
            all_py.extend(sorted((PROJECT_ROOT / d).rglob("*.py")))
        all_py.append(PROJECT_ROOT / "director.py")

        orphan_candidates = {"agents.job_monitor", "agents.higgsfield_executor"}
        importers = set()
        for path in all_py:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    importers.update(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    importers.add(node.module)

        for candidate in orphan_candidates:
            self.assertNotIn(candidate, importers, f"{candidate} is no longer orphaned -- re-audit required")


# ----------------------------------------------------------------------
# Section 9: double-dot relative import (extends P3.64 Class E).
# ----------------------------------------------------------------------


class TestDoubleDotRelativeImport(_TempRepoTestCase):
    def test_not_detected_confirming_the_documented_gap_extends_to_double_dot(self):
        _write(
            self.root, "agents/generation_approval_gate.py",
            "from ..certificate_integrity import ISSUER_IDENTITY\n",
        )
        report = self._detector().analyze()
        self.assertEqual(self._edge_findings(report), [])


# ----------------------------------------------------------------------
# Sections 12/13: usage-syntax irrelevance -- detection is import-edge
# based, not usage based. Each of these already-imports the symbol, so
# each is (correctly) detected regardless of how the symbol is then used.
# ----------------------------------------------------------------------


class TestUsageSyntaxIsIrrelevantOnceImported(_TempRepoTestCase):
    def test_decorator_usage_is_detected_via_the_underlying_import(self):
        _write(
            self.root, "agents/generation_approval_gate.py",
            "from agents.certificate_integrity import verify_provenance\n\n"
            "@verify_provenance\ndef f():\n    pass\n",
        )
        report = self._detector().analyze()
        self.assertTrue(any(f.code == "CERTIFICATE_TO_AUTHORITY_IMPORT" for f in report.findings))

    def test_default_parameter_value_is_detected_via_the_underlying_import(self):
        _write(
            self.root, "agents/generation_approval_gate.py",
            "from agents.certificate_integrity import ISSUER_IDENTITY\n\n"
            "def f(issuer=ISSUER_IDENTITY):\n    pass\n",
        )
        report = self._detector().analyze()
        self.assertTrue(any(f.code == "CERTIFICATE_TO_AUTHORITY_IMPORT" for f in report.findings))

    def test_module_level_reassignment_is_detected_via_the_underlying_import(self):
        _write(
            self.root, "agents/generation_approval_gate.py",
            "from agents.certificate_integrity import ISSUER_IDENTITY\nALIAS = ISSUER_IDENTITY\n",
        )
        report = self._detector().analyze()
        self.assertTrue(any(f.code == "CERTIFICATE_TO_AUTHORITY_IMPORT" for f in report.findings))

    def test_function_returning_the_symbol_is_detected_via_the_underlying_import(self):
        _write(
            self.root, "agents/generation_approval_gate.py",
            "from agents.certificate_integrity import ISSUER_IDENTITY\n\n"
            "def get_it():\n    return ISSUER_IDENTITY\n",
        )
        report = self._detector().analyze()
        self.assertTrue(any(f.code == "CERTIFICATE_TO_AUTHORITY_IMPORT" for f in report.findings))

    def test_class_attribute_wrapping_is_detected_via_the_underlying_import(self):
        _write(
            self.root, "agents/generation_approval_gate.py",
            "from agents.certificate_integrity import ISSUER_IDENTITY\n\n"
            "class Wrapper:\n    X = ISSUER_IDENTITY\n",
        )
        report = self._detector().analyze()
        self.assertTrue(any(f.code == "CERTIFICATE_TO_AUTHORITY_IMPORT" for f in report.findings))

    def test_class_attribute_wrapping_via_a_helper_is_detected_transitively(self):
        _write(
            self.root, "agents/helper.py",
            "from agents.certificate_integrity import ISSUER_IDENTITY\n\n"
            "class Wrapper:\n    X = ISSUER_IDENTITY\n",
        )
        _write(self.root, "agents/generation_approval_gate.py", "from agents.helper import Wrapper\n")
        report = self._detector().analyze()
        self.assertTrue(any(f.code == "CERTIFICATE_INDIRECT_AUTHORITY_IMPORT" for f in report.findings))

    def test_typed_dict_with_no_real_import_is_not_detected(self):
        """Structural typing without importing the real certificate type
        remains out of scope, consistent with P3.64's Protocol finding."""
        _write(
            self.root, "agents/generation_approval_gate.py",
            "from typing import TypedDict\nclass CertLike(TypedDict):\n    readiness_result: str\n",
        )
        report = self._detector().analyze()
        self.assertEqual(self._edge_findings(report), [])

    def test_fstring_reference_is_not_detected(self):
        _write(
            self.root, "agents/generation_approval_gate.py",
            "def f():\n    raise ValueError(f'see agents.certificate_integrity.ISSUER_IDENTITY')\n",
        )
        report = self._detector().analyze()
        self.assertEqual(self._edge_findings(report), [])


# ----------------------------------------------------------------------
# Section 20: contract/detector consistency -- no orphaned constant.
# ----------------------------------------------------------------------


class TestContractFieldsAreAllReferenced(unittest.TestCase):
    def test_every_certificate_contract_field_is_used_by_the_detector(self):
        detector_source = (PROJECT_ROOT / "agents" / "architecture_drift_detector.py").read_text(encoding="utf-8")
        certificate_fields = [
            "certificate_subsystem_files",
            "certificate_informational_layer_files",
            "certificate_guardrail_authority_surface_files",
            "certificate_subsystem_import_prefixes",
            "certificate_outbound_forbidden_import_prefixes",
            "certificate_forbidden_authority_call_names",
        ]
        for field_name in certificate_fields:
            self.assertIn(
                f"self.contract.{field_name}", detector_source,
                f"contract field '{field_name}' is never referenced by the detector -- orphaned constant.",
            )


class TestRealRepositoryStillClean(unittest.TestCase):
    def test_real_repository_has_no_certificate_authority_edge_of_any_kind(self):
        report = ArchitectureDriftDetector(contract=CANONICAL_ARCHITECTURE_CONTRACT).analyze()
        hits = [f for f in report.findings if f.code in _EDGE_CODES]
        self.assertEqual(hits, [])
        self.assertEqual(report.status, DriftStatus.NO_DRIFT)


if __name__ == "__main__":
    unittest.main()
