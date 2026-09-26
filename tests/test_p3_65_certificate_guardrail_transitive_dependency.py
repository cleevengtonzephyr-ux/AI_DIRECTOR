"""
Tests -- Certificate Guardrail Transitive Dependency & Contract Closure
Audit (Phase P3.65).

P3.64 closed exactly ONE intermediate hop of re-export
(`agents/helper.py: from agents.certificate_x import Y`, then
`authority.py: from agents.helper import Y`), and explicitly documented
a deeper chain (helper1 -> helper2 -> certificate) as an accepted
residual gap. P3.65's job was to determine whether that residual gap is
real, how deep it goes, and whether it can be closed without building a
general dependency-graph engine.

Finding: the gap WAS real and demonstrably unbounded (any chain length
evaded the P3.64 one-hop check). It is closed here by generalizing the
existing one-hop resolution into a genuinely transitive, but still
bounded and cycle-safe, breadth-first search
(`ArchitectureDriftDetector._check_no_transitive_certificate_authority_
edge()`), reusing the SAME import graph (`facts_by_file`) every other
check in this detector already builds -- no new parsing pass, no new
infrastructure, no runtime instrumentation, no unbounded recursion (a
`visited` set makes every traversal terminate in at most
`len(facts_by_file)` steps regardless of cycles in the underlying import
graph).

Scope, stated precisely (never oversold):
  - SOUND: every edge this check reports is a real, walkable chain of
    `ast.Import`/`ast.ImportFrom` edges that genuinely exists in the
    scanned files.
  - COMPLETE only within STATIC, FIRST-PARTY, RESOLVABLE import edges --
    the same boundary every other check in this detector already has.
    Dynamic imports, reflection, and structural typing remain the same
    honestly-documented, out-of-scope limitation P3.64 already
    established; this phase does not change that boundary.

Every test uses isolated `tempfile.TemporaryDirectory` fixtures (never
the real repository, except the explicit real-repo confirmation class)
and never touches Higgsfield, a real Provider, or credits.
"""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.architecture_drift_detector import ArchitectureDriftDetector, DriftStatus
from agents.canonical_architecture_contract import CANONICAL_ARCHITECTURE_CONTRACT

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


class TestRealRepositoryZeroTransitivePaths(unittest.TestCase):
    """Section 4/15: the real repository has no certificate<->authority
    path of ANY depth."""

    def test_real_repository_has_no_certificate_authority_path(self):
        report = ArchitectureDriftDetector(contract=CANONICAL_ARCHITECTURE_CONTRACT).analyze()
        hits = [f for f in report.findings if f.code in _EDGE_CODES]
        self.assertEqual(hits, [])
        self.assertEqual(report.status, DriftStatus.NO_DRIFT)


class TestDepth0_NoRelation(_TempRepoTestCase):
    """Section 5, Depth 0: an authority file with no certificate-related
    import at all -- the trivial baseline."""

    def test_no_finding(self):
        _write(self.root, "agents/generation_approval_gate.py", "X = 1\n")
        report = self._detector().analyze()
        self.assertEqual(self._edge_findings(report), [])
        self.assertEqual(report.status, DriftStatus.NO_DRIFT)


class TestDepth1_Direct(_TempRepoTestCase):
    """Section 5, Depth 1: authority directly imports certificate --
    unchanged behavior, handled by the P3.63 direct-edge check, never
    double-reported by the new transitive check."""

    def test_exactly_one_finding_from_the_direct_check(self):
        _write(
            self.root, "agents/generation_approval_gate.py",
            "from agents.certificate_integrity import ISSUER_IDENTITY\n",
        )
        report = self._detector().analyze()
        hits = self._edge_findings(report)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].code, "CERTIFICATE_TO_AUTHORITY_IMPORT")


class TestDepth2_AuthorityToCertificate(_TempRepoTestCase):
    """Section 5, Depth 2 (Fixture A): authority -> helper -> certificate."""

    def test_detected(self):
        _write(self.root, "agents/helper.py", "from agents.certificate_integrity import ISSUER_IDENTITY\n")
        _write(self.root, "agents/generation_approval_gate.py", "from agents.helper import ISSUER_IDENTITY\n")
        report = self._detector().analyze()
        hits = [f for f in report.findings if f.code == "CERTIFICATE_INDIRECT_AUTHORITY_IMPORT"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].file, "agents/generation_approval_gate.py")
        self.assertIn("agents/certificate_integrity.py", hits[0].evidence)


class TestDepth3_AuthorityToCertificate(_TempRepoTestCase):
    """Section 5, Depth 3 (Fixture B): authority -> helper1 -> helper2 ->
    certificate -- this is the exact chain P3.64 documented as an
    accepted residual gap. Now closed."""

    def test_detected(self):
        _write(self.root, "agents/helper2.py", "from agents.certificate_integrity import ISSUER_IDENTITY\n")
        _write(self.root, "agents/helper1.py", "from agents.helper2 import ISSUER_IDENTITY\n")
        _write(self.root, "agents/generation_approval_gate.py", "from agents.helper1 import ISSUER_IDENTITY\n")
        report = self._detector().analyze()
        hits = [f for f in report.findings if f.code == "CERTIFICATE_INDIRECT_AUTHORITY_IMPORT"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].file, "agents/generation_approval_gate.py")


class TestDepth4Plus_AuthorityToCertificate(_TempRepoTestCase):
    """Section 5, Depth 4 (Fixture C): authority -> helper1 -> helper2 ->
    helper3 -> certificate -- confirms the resolution is genuinely
    unbounded in depth (not a fixed-depth patch), while still
    terminating deterministically."""

    def test_detected(self):
        _write(self.root, "agents/helper3.py", "from agents.certificate_integrity import ISSUER_IDENTITY\n")
        _write(self.root, "agents/helper2.py", "from agents.helper3 import ISSUER_IDENTITY\n")
        _write(self.root, "agents/helper1.py", "from agents.helper2 import ISSUER_IDENTITY\n")
        _write(self.root, "agents/generation_approval_gate.py", "from agents.helper1 import ISSUER_IDENTITY\n")
        report = self._detector().analyze()
        hits = [f for f in report.findings if f.code == "CERTIFICATE_INDIRECT_AUTHORITY_IMPORT"]
        self.assertEqual(len(hits), 1)

    def test_determinism_on_repeated_analysis(self):
        _write(self.root, "agents/helper3.py", "from agents.certificate_integrity import ISSUER_IDENTITY\n")
        _write(self.root, "agents/helper2.py", "from agents.helper3 import ISSUER_IDENTITY\n")
        _write(self.root, "agents/helper1.py", "from agents.helper2 import ISSUER_IDENTITY\n")
        _write(self.root, "agents/generation_approval_gate.py", "from agents.helper1 import ISSUER_IDENTITY\n")
        detector = self._detector()
        first = detector.analyze()
        second = detector.analyze()
        self.assertEqual(first.findings, second.findings)


class TestReverseDirection_CertificateToAuthority(_TempRepoTestCase):
    """Section 5/6, mirrored direction: certificate informational layer
    -> helper(s) -> authority, at depth 2 and depth 3."""

    def test_depth_2_detected(self):
        _write(self.root, "agents/helper.py", "from agents.generation_approval_gate import GenerationApprovalGate\n")
        _write(self.root, "agents/certificate_integrity.py", "from agents.helper import GenerationApprovalGate\n")
        report = self._detector().analyze()
        hits = [f for f in report.findings if f.code == "CERTIFICATE_INDIRECT_OUTBOUND_AUTHORITY_IMPORT"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].file, "agents/certificate_integrity.py")

    def test_depth_3_detected(self):
        _write(self.root, "agents/helper2.py", "from agents.generation_approval_gate import GenerationApprovalGate\n")
        _write(self.root, "agents/helper1.py", "from agents.helper2 import GenerationApprovalGate\n")
        _write(self.root, "agents/certificate_integrity.py", "from agents.helper1 import GenerationApprovalGate\n")
        report = self._detector().analyze()
        hits = [f for f in report.findings if f.code == "CERTIFICATE_INDIRECT_OUTBOUND_AUTHORITY_IMPORT"]
        self.assertEqual(len(hits), 1)


class TestFixtureD_Cycles(_TempRepoTestCase):
    """Section 5/7 (Fixture D). Cycles must never hang the detector, must
    terminate deterministically, and must never produce a false edge
    when no authority-surface file actually participates."""

    def test_pure_cycle_with_no_authority_involvement_is_not_flagged(self):
        """certificate-adjacent helper <-> another helper, cyclic, but
        NEITHER is an authority-surface file and NEITHER is imported by
        one -- must terminate instantly and report nothing."""
        _write(self.root, "agents/cycle_a.py", "import agents.cycle_b\n")
        _write(self.root, "agents/cycle_b.py", "import agents.cycle_a\n")
        report = self._detector().analyze()
        self.assertEqual(self._edge_findings(report), [])
        self.assertEqual(report.status, DriftStatus.NO_DRIFT)

    def test_cycle_reachable_from_authority_still_terminates_and_is_correctly_classified(self):
        """authority -> helper -> authority-surface-file (cycle back into
        the authority surface itself, never touching a certificate
        module) -- must terminate and report NOTHING, since no
        certificate module is ever actually reached."""
        _write(
            self.root, "agents/helper.py",
            "from agents.generation_job_service import GenerationJobService\n",
        )
        _write(
            self.root, "agents/generation_approval_gate.py",
            "from agents.helper import GenerationJobService\n",
        )
        report = self._detector().analyze()
        self.assertEqual(self._edge_findings(report), [])

    def test_cycle_that_does_reach_a_certificate_module_is_still_detected(self):
        """authority -> helper1 -> helper2 -> helper1 (cycle among the
        helpers themselves) with helper2 also reaching a certificate
        module -- the cycle must not prevent detection of the genuine
        edge, and must not hang."""
        _write(
            self.root, "agents/helper2.py",
            (
                "import agents.helper1\n"
                "from agents.certificate_integrity import ISSUER_IDENTITY\n"
            ),
        )
        _write(self.root, "agents/helper1.py", "import agents.helper2\n")
        _write(self.root, "agents/generation_approval_gate.py", "import agents.helper1\n")
        report = self._detector().analyze()
        hits = [f for f in report.findings if f.code == "CERTIFICATE_INDIRECT_AUTHORITY_IMPORT"]
        self.assertEqual(len(hits), 1)


class TestFixtureE_TwoIndependentPaths(_TempRepoTestCase):
    """Section 5 (Fixture E): two independent chains from the same
    authority file to two different certificate modules must both be
    reported, independently."""

    def test_both_paths_detected(self):
        _write(self.root, "agents/helperA.py", "from agents.certificate_integrity import ISSUER_IDENTITY\n")
        _write(self.root, "agents/helperB.py", "from agents.certificate_lifecycle import CertificateLifecycleRegistry\n")
        _write(
            self.root, "agents/generation_approval_gate.py",
            "from agents.helperA import ISSUER_IDENTITY\nfrom agents.helperB import CertificateLifecycleRegistry\n",
        )
        report = self._detector().analyze()
        hits = [f for f in report.findings if f.code == "CERTIFICATE_INDIRECT_AUTHORITY_IMPORT"]
        self.assertEqual(len(hits), 2)
        files_reached = {"agents/certificate_integrity.py", "agents/certificate_lifecycle.py"}
        reached_in_evidence = {r for hit in hits for r in files_reached if r in hit.evidence}
        self.assertEqual(reached_in_evidence, files_reached)


class TestFixtureF_SharedNeutralUtility(_TempRepoTestCase):
    """Section 6/12 (Fixture F): certificate and authority independently
    sharing a neutral utility that itself imports NEITHER must never be
    flagged -- `certificate -> utils` and `authority -> utils` does not
    imply `certificate -> authority`."""

    def test_shared_utility_with_no_certificate_import_is_not_flagged(self):
        _write(self.root, "agents/common_util.py", "X = 1\n")
        _write(self.root, "agents/certificate_verification.py", "from agents.common_util import X\n")
        _write(self.root, "agents/generation_approval_gate.py", "from agents.common_util import X\n")
        report = self._detector().analyze()
        self.assertEqual(self._edge_findings(report), [])
        self.assertEqual(report.status, DriftStatus.NO_DRIFT)


class TestAliasAtIntermediateHop(_TempRepoTestCase):
    """Section 9: an intermediate hop importing under a module alias
    (`import agents.helper2 as h2`) must not evade detection -- the
    resolution follows dotted module NAMES, never local bindings, at
    every hop, not just the first."""

    def test_module_alias_at_an_intermediate_hop_still_detected(self):
        _write(self.root, "agents/helper2.py", "from agents.certificate_integrity import ISSUER_IDENTITY\n")
        _write(self.root, "agents/helper1.py", "import agents.helper2 as h2\n")
        _write(self.root, "agents/generation_approval_gate.py", "from agents.helper1 import h2\n")
        report = self._detector().analyze()
        hits = [f for f in report.findings if f.code == "CERTIFICATE_INDIRECT_AUTHORITY_IMPORT"]
        self.assertEqual(len(hits), 1)


class TestDynamicBoundaryUnchanged(_TempRepoTestCase):
    """Section 10: the transitive upgrade changes nothing about the
    static/dynamic boundary already established in P3.64 -- dynamic
    resolution anywhere in the chain still evades detection, and this
    is not claimed otherwise."""

    def test_dynamic_import_at_an_intermediate_hop_is_not_detected(self):
        _write(
            self.root, "agents/helper.py",
            "import importlib\ncert = importlib.import_module('agents.certificate_integrity')\n",
        )
        _write(self.root, "agents/generation_approval_gate.py", "from agents.helper import cert\n")
        report = self._detector().analyze()
        self.assertEqual(self._edge_findings(report), [])


class TestFalsePositiveAnalysis(_TempRepoTestCase):
    """Section 12/14: legitimate architecture must never be flagged
    transitively, mirroring the direct-edge false-positive suite."""

    def test_issuer_transitively_reaching_p2_authority_types_is_not_flagged(self):
        _write(
            self.root, "agents/helper.py",
            "from agents.activation_readiness import ActivationReadinessEvaluator\n",
        )
        _write(
            self.root, "agents/production_activation_readiness_certificate.py",
            "from agents.helper import ActivationReadinessEvaluator\n",
        )
        report = self._detector().analyze()
        self.assertEqual(self._edge_findings(report), [])

    def test_test_domain_helper_is_never_traversed(self):
        """A helper living under `tests/` must never be treated as a
        legitimate intermediate hop, even if it happens to import both
        a certificate module and be importable by name."""
        _write(self.root, "tests/fixture_helper.py", "from agents.certificate_integrity import ISSUER_IDENTITY\n")
        _write(self.root, "agents/generation_approval_gate.py", "from tests.fixture_helper import ISSUER_IDENTITY\n")
        report = self._detector().analyze()
        self.assertEqual(self._edge_findings(report), [])

    def test_certificate_subsystem_importing_its_own_modules_is_not_flagged(self):
        """The informational layer's ordinary internal composition
        (e.g. certificate_integrity.py importing certificate_
        verification.py) must never be treated as a chain toward
        authority."""
        _write(
            self.root, "agents/certificate_integrity.py",
            "from agents.certificate_verification import verify_certificate\n",
        )
        report = self._detector().analyze()
        self.assertEqual(self._edge_findings(report), [])


class TestMutationRoundTrip(_TempRepoTestCase):
    """Section 5/20 protocol: introduce a multi-hop chain, confirm
    detection, remove it, confirm the same temp repository returns to
    NO_DRIFT."""

    def test_three_hop_chain_round_trip(self):
        _write(self.root, "agents/helper2.py", "from agents.certificate_integrity import ISSUER_IDENTITY\n")
        _write(self.root, "agents/helper1.py", "from agents.helper2 import ISSUER_IDENTITY\n")
        entry_file = self.root / "agents" / "generation_approval_gate.py"
        _write(self.root, "agents/generation_approval_gate.py", "from agents.helper1 import ISSUER_IDENTITY\n")

        drifted = self._detector().analyze()
        self.assertEqual(drifted.status, DriftStatus.DRIFT_DETECTED)
        self.assertTrue(any(f.code == "CERTIFICATE_INDIRECT_AUTHORITY_IMPORT" for f in drifted.findings))

        entry_file.unlink()

        clean = self._detector().analyze()
        self.assertEqual(clean.status, DriftStatus.NO_DRIFT)
        self.assertEqual(clean.findings, ())


if __name__ == "__main__":
    unittest.main()
