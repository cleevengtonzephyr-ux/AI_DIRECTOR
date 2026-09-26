"""
Tests -- Certificate/Authority Bridge Guardrail Corrective Closure (P3.76-R1).

Pins the four gaps P3.76 demonstrated, each reproduced before the fix:
1. relative imports (`from .certificate_x import`, `from . import x`)
   were recorded raw and matched no contract prefix;
2. the P3.54 Issuer's sanctioned composition let a module pull authority
   symbols THROUGH it (`from <issuer> import GenerationRequest`) unseen;
3. `scripts/` was exempt from the bridge rule, not only from authority
   construction;
4. first-party `.py` files outside agents/integrations/scripts/tests and
   director.py were never scanned.

Temporary fixtures only -- no provider, no create_job(), no credits.
"""

import ast
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.architecture_drift_detector import ArchitectureDriftDetector

BRIDGE = "CERTIFICATE_AUTHORITY_BRIDGE_MODULE"
ISS = "agents.production_activation_readiness_certificate"
ISSUER_FILE = "agents/production_activation_readiness_certificate.py"
CL = "from agents.certificate_lifecycle import CertificateLifecycleRegistry\n"
FRS = "from agents.final_report_service import FinalReportService\n"


def _codes(*files, with_issuer=False):
    if with_issuer:  # re-exports resolve against the REAL Issuer source
        files = ((ISSUER_FILE, (PROJECT_ROOT / ISSUER_FILE).read_text(encoding="utf-8")),) + files
    with tempfile.TemporaryDirectory() as tmp:
        for rel, source in files:
            path = Path(tmp) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        return {f.code for f in ArchitectureDriftDetector(root=Path(tmp)).analyze().findings}


class TestRelativeImportResolution(unittest.TestCase):
    def test_relative_certificate_authority_edges_are_detected(self):
        cases = {
            "from .x import (bridge)": ([("agents/m.py", "from .certificate_lifecycle import X\nfrom .final_report_service import Y\n")], BRIDGE),
            "from . import x (bridge)": ([("agents/m.py", "from . import certificate_verification\nfrom . import generation_job_service\n")], BRIDGE),
            "from ..x import (bridge)": ([("agents/sub/m.py", "from ..certificate_lifecycle import X\nfrom ..final_report_service import Y\n")], BRIDGE),
            "authority surface, relative": ([("agents/generation_job_service.py", "from .certificate_lifecycle import X\n")], "CERTIFICATE_TO_AUTHORITY_IMPORT"),
            "informational layer, relative": ([("agents/certificate_lifecycle.py", "from .generation_job_service import X\n")], "CERTIFICATE_OUTBOUND_AUTHORITY_IMPORT"),
        }
        for label, (files, code) in cases.items():
            with self.subTest(case=label):
                self.assertIn(code, _codes(*files))

    def test_relative_transitive_bridge_is_detected(self):
        self.assertIn(BRIDGE, _codes(
            ("agents/h2.py", FRS),
            ("agents/h1.py", "from . import h2\n"),
            ("agents/m.py", CL + "from .h1 import *\n"),
        ))

    def test_relative_import_beyond_top_level_package_is_not_resolved(self):
        # Python itself raises ImportError here -- never a real edge.
        self.assertNotIn(BRIDGE, _codes(("tool.py", "from .certificate_lifecycle import X\nfrom .final_report_service import Y\n")))


class TestSanctionedIssuerBoundary(unittest.TestCase):
    def test_issuer_cannot_launder_authority_symbols(self):
        cases = {
            "named re-export": "from %s import GenerationRequest\n" % ISS,
            "star import": "from %s import *\n" % ISS,
            "module attribute": "import %s as i\nx = i.RequestScopedActivationContract\n" % ISS,
        }
        for label, source in cases.items():
            with self.subTest(case=label):
                self.assertIn(BRIDGE, _codes(("newpkg/m.py", CL + source), with_issuer=True))

    def test_transitive_issuer_laundering_is_detected(self):
        self.assertIn(BRIDGE, _codes(
            ("agents/h1.py", "from %s import GenerationRequest\n" % ISS),
            ("agents/m.py", "from agents.h1 import GenerationRequest\n"),
            with_issuer=True,
        ))

    def test_issuer_defined_vocabulary_stays_legitimate(self):
        source = CL + "from %s import ProductionActivationReadinessCertificate, ProductionActivationReadinessCertificateIssuer, certificate_still_matches\n" % ISS
        self.assertEqual(_codes(("newpkg/report.py", source), with_issuer=True), set())
        self.assertEqual(_codes(with_issuer=True), set())  # the P3.54 crossing itself


class TestScriptPolicy(unittest.TestCase):
    def test_script_bridge_is_detected(self):
        self.assertIn(BRIDGE, _codes(("scripts/m.py", CL + FRS)))

    def test_no_script_is_production_reachable(self):
        # scripts/ keeps its authority-CONSTRUCTION exemption (demo_test.py)
        # only because nothing outside tests/ and scripts/ imports it.
        offenders = []
        for path in [PROJECT_ROOT / "director.py", *(PROJECT_ROOT / "agents").rglob("*.py"), *(PROJECT_ROOT / "integrations").rglob("*.py")]:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
                offenders += [f"{path.name}:{n}" for n in names if n == "scripts" or n.startswith("scripts.")]
        self.assertEqual(offenders, [])


class TestScanBoundaryPolicy(unittest.TestCase):
    def test_first_party_file_outside_the_named_dirs_is_scanned(self):
        for rel in ("tool.py", "newpkg/m.py", "config/m.py", "integrations/extra/m.py"):
            with self.subTest(file=rel):
                self.assertIn(BRIDGE, _codes((rel, CL + FRS)))

    def test_non_first_party_directories_are_excluded(self):
        for rel in (".venv/lib/m.py", "venv/m.py", "build/m.py", "pkg/__pycache__/m.py", "x.egg-info/m.py"):
            with self.subTest(file=rel):
                self.assertEqual(_codes((rel, CL + FRS)), set())

    def test_every_first_party_python_file_of_the_repository_is_analyzed(self):
        report = ArchitectureDriftDetector(root=PROJECT_ROOT).analyze()
        on_disk = {
            str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")
            for p in PROJECT_ROOT.rglob("*.py")
            if not any(part.startswith(".") or part == "__pycache__" for part in p.relative_to(PROJECT_ROOT).parts)
        }
        self.assertEqual(on_disk - set(report.files_analyzed), set())
        self.assertEqual(report.status.value, "NO_DRIFT")


if __name__ == "__main__":
    unittest.main()
