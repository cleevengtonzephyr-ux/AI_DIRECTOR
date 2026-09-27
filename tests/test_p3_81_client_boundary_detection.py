"""
Tests -- Higgsfield Client Boundary Detection (P3.81, versioned in P3.101).

P3.80/P3.81 reproduced that `AIDirector().higgsfield.create_job(...)` -- and
the same call through `gate.provider.client`, `job_service.provider.client`
... -- reaches the unguarded `HiggsfieldClient.create_job()` (a real,
billable `generate create`) while the drift detector only counted a
create_job() call-site in a file importing `integrations.higgsfield` itself.
The client is reached through the IMPORT CLOSURE, so the detector must count
those call-sites as production create paths (CREATE_JOB_CARDINALITY_
VIOLATION), and report the file that really holds the call.

P3.101: this module had survived only as orphaned bytecode
(`tests/__pycache__/test_p3_81_client_boundary_detection.cpython-314.pyc`,
never committed). Its 6 tests / 16 assertions are restored here from that
bytecode -- same fixtures, same expectations -- against the P3.101 detector
rule, which also keeps P3.77-R1 G3 intact (an unrelated symbol taken from a
Higgsfield-importing helper stays a namesake; see
tests/test_p3_77_r1_alias_and_cli_create_closure.py).

Purely static: fixtures are written to a temporary directory and parsed,
never imported or executed. No provider, no CLI, no generation, no credits.
"""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.architecture_drift_detector import ArchitectureDriftDetector

CARD = "CREATE_JOB_CARDINALITY_VIOLATION"
NAMESAKE = "CREATE_JOB_NAMESAKE_UNRELATED"
SANCTIONED = ("agents/generation_job_service.py", "def execute(p):\n    p.create_job('m', 'p')\n")
DIRECTOR = (
    "director.py",
    "from integrations.higgsfield.client import HiggsfieldClient\n"
    "class AIDirector:\n"
    "    def __init__(self):\n"
    "        self.higgsfield = HiggsfieldClient()\n",
)
PROVIDER = (
    "integrations/higgsfield/provider.py",
    "from integrations.higgsfield.client import HiggsfieldClient\nclass HiggsfieldProvider:\n    pass\n",
)
GATE = (
    "agents/generation_approval_gate.py",
    "from integrations.higgsfield.provider import HiggsfieldProvider\nclass GenerationApprovalGate:\n    pass\n",
)
CALL = "    return c.create_job('seedance_2_0', 'p')\n"


def _findings(*files):
    with tempfile.TemporaryDirectory() as tmp:
        for rel_path, source in files:
            path = Path(tmp) / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        return [(f.code, f.file) for f in ArchitectureDriftDetector(root=Path(tmp)).analyze().findings]


def _codes(*files):
    return {code for code, _file in _findings(*files)}


class TestClientReachedThroughImportClosureIsCounted(unittest.TestCase):
    def test_director_client_forms_are_counted(self):
        cases = {
            "AIDirector().higgsfield.create_job": [
                DIRECTOR,
                ("agents/u.py", "from director import AIDirector\ndef f():\n    return AIDirector().higgsfield.create_job('seedance_2_0', 'p')\n"),
            ],
            "attribute alias chain": [
                DIRECTOR,
                ("agents/u.py", "from director import AIDirector\ndef f():\n    alias = AIDirector().higgsfield\n    c = alias\n" + CALL),
            ],
            "module attribute": [
                DIRECTOR,
                ("agents/u.py", "import director as d\ndef f():\n    return d.AIDirector().higgsfield.create_job('seedance_2_0', 'p')\n"),
            ],
            "import alias": [
                DIRECTOR,
                ("agents/u.py", "from director import AIDirector as D\ndef f():\n    return D().higgsfield.create_job('seedance_2_0', 'p')\n"),
            ],
            "re-export": [
                DIRECTOR,
                ("agents/h.py", "from director import AIDirector\n"),
                ("agents/u.py", "from agents.h import AIDirector\ndef f():\n    return AIDirector().higgsfield.create_job('seedance_2_0', 'p')\n"),
            ],
            "transitive helper chain": [
                DIRECTOR,
                ("agents/h2.py", "import director\n"),
                ("agents/h1.py", "from agents import h2\n"),
                ("agents/u.py", "import agents.h1\ndef f(c):\n" + CALL),
            ],
            "relative import": [
                ("agents/x.py", "from integrations.higgsfield.client import HiggsfieldClient\n"),
                ("agents/u.py", "from .x import HiggsfieldClient\ndef f(c):\n" + CALL),
            ],
            "gate.provider.client (P2 object path)": [
                PROVIDER,
                GATE,
                ("agents/u.py", "from agents.generation_approval_gate import GenerationApprovalGate\ndef f(gate):\n    return gate.provider.client.create_job('seedance_2_0', 'p')\n"),
            ],
            "direct client import (unchanged)": [
                ("agents/u.py", "from integrations.higgsfield.client import HiggsfieldClient\ndef f(c):\n" + CALL),
            ],
            "root-level helper": [
                DIRECTOR,
                ("tools/helper.py", "from director import AIDirector\ndef f():\n    return AIDirector().higgsfield.create_job('seedance_2_0', 'p')\n"),
            ],
        }
        for label, files in cases.items():
            with self.subTest(case=label):
                self.assertIn(CARD, _codes(SANCTIONED, *files))

    def test_helper_holding_the_call_is_the_reported_site(self):
        findings = _findings(
            SANCTIONED,
            DIRECTOR,
            ("agents/h.py", "from director import AIDirector\ndef go():\n    return AIDirector().higgsfield.create_job('seedance_2_0', 'p')\n"),
            ("agents/u.py", "from agents.h import go\ngo()\n"),
        )
        self.assertIn((CARD, "agents/h.py"), findings)


class TestUnrelatedNamesakesStayInformational(unittest.TestCase):
    def test_no_higgsfield_in_import_closure_stays_namesake(self):
        cases = {
            "no imports (job_monitor-like)": [
                ("agents/u.py", "class M:\n    def create_job(self, i):\n        return i\ndef f(m):\n    return m.create_job('SIM')\n"),
            ],
            "imports only an unrelated module": [
                ("agents/other.py", "import json\n"),
                ("agents/u.py", "import agents.other\ndef f(m):\n    return m.create_job('SIM')\n"),
            ],
        }
        for label, files in cases.items():
            with self.subTest(case=label):
                codes = _codes(SANCTIONED, *files)
                self.assertNotIn(CARD, codes)
                self.assertIn(NAMESAKE, codes)

    def test_documented_limit_duck_typed_helper_is_reported_not_counted(self):
        # Documented limit: the call sits in a file with no Higgsfield link
        # at all (the client arrives as a plain argument) -- reported, not counted.
        codes = _codes(
            SANCTIONED,
            DIRECTOR,
            ("agents/h.py", "def go(c):\n" + CALL),
            ("agents/u.py", "from director import AIDirector\nfrom agents.h import go\ngo(AIDirector().higgsfield)\n"),
        )
        self.assertIn(NAMESAKE, codes)

    def test_test_domain_is_exempt(self):
        self.assertNotIn(
            CARD,
            _codes(SANCTIONED, DIRECTOR, ("tests/test_x.py", "from director import AIDirector\nAIDirector().higgsfield.create_job('m', 'p')\n")),
        )


class TestRepositoryStaysClean(unittest.TestCase):
    def test_real_repository_single_create_path_and_single_namesake(self):
        report = ArchitectureDriftDetector().analyze()
        self.assertEqual(report.status.value, "NO_DRIFT", [(f.code, f.file) for f in report.findings])
        self.assertEqual([f.file for f in report.findings if f.code == CARD], [])
        self.assertEqual({f.file for f in report.findings if f.code == NAMESAKE}, {"agents/job_monitor.py"})


if __name__ == "__main__":
    unittest.main()
