"""
Tests -- Alias / Reassignment and CLI-create Guardrail Closure (P3.77-R1).

Pins the two gaps P3.77 demonstrated, each reproduced before the fix:

G1. `_extract_file_facts` recorded a call by its SYNTACTIC name only, so an
    authority-bearing symbol constructed (or an authority primitive called)
    through an import alias (`import X as H; H(...)`), a simple
    reassignment (`H = X; H(...)`) or both was invisible to every
    name-based check -- the full suite and the detector stayed green.

G2. Production create_job cardinality only counted calls NAMED
    `create_job`; `client.run("generate", "create", ...)` -- the exact CLI
    verb `HiggsfieldClient.create_job()` wraps -- was a second, uncounted
    creation path. Option B (P3.77 decision): any `.run(...)` carrying the
    literal positional argument "create", outside
    `integrations/higgsfield/client.py`, counts as a production create_job
    call-site.

G3. (P3.77-R1-G3) The create_job relevance test read direct imports
    only, so `create_job()` on a Provider/Client pulled THROUGH a module
    that re-exports it was logged as an unrelated namesake (INFORMATIONAL)
    -- `reexport_modules` (P3.76-R1) was consulted by the bridge checks
    but not here.

Documented static limits (never claimed as detected): a CLI verb that is
not a literal at the call (`args = [...]; c.run(*args)`, a wrapper that
forwards `*args`) and duck-typed rebinding through containers or
`getattr()` -- the analysed code is never executed.

Temporary fixtures only -- no provider, no create_job(), no credits.
"""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.architecture_drift_detector import ArchitectureDriftDetector

RGA = "agents.generation_approval_gate"
HUMAN = "AUTOMATIC_HUMAN_AUTHORIZATION"
CTOR = "AUTHORITY_CONSTRUCTOR_OUTSIDE_ALLOWLIST"
CARD = "CREATE_JOB_CARDINALITY_VIOLATION"
OUT_CALL = "CERTIFICATE_OUTBOUND_AUTHORITY_CALL"
BRIDGE = "CERTIFICATE_AUTHORITY_BRIDGE_MODULE"
TO_AUTH = "CERTIFICATE_TO_AUTHORITY_IMPORT"
# The one sanctioned production create_job() call-site, so a second one is
# a cardinality change (1 -> 2), exactly as in the real repository.
SANCTIONED = ("agents/generation_job_service.py", "def execute(p):\n    p.create_job('m', 'p')\n")
CLIENT_IMPORT = "from integrations.higgsfield.client import HiggsfieldClient\n"


def _codes(*files):
    with tempfile.TemporaryDirectory() as tmp:
        for rel, source in files:
            path = Path(tmp) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        return {
            f.code
            for f in ArchitectureDriftDetector(root=Path(tmp)).analyze().findings
            if f.severity.value != "INFORMATIONAL"
        }


class TestG1AliasAndReassignment(unittest.TestCase):
    def test_human_authorization_construction_is_detected(self):
        cases = {
            "G1-A import alias": f"from {RGA} import RealGenerationAuthorization as H\nH(authorized_by_human=True, request_id='005')\n",
            "G1-B simple reassignment": f"from {RGA} import RealGenerationAuthorization\nX = RealGenerationAuthorization\nX(authorized_by_human=True, request_id='005')\n",
            "G1-C alias + reassignment": f"from {RGA} import RealGenerationAuthorization as C\nX = C\nX(authorized_by_human=True, request_id='005')\n",
            "reassignment chain": f"from {RGA} import RealGenerationAuthorization as C\nX = C\nY = X\nY(authorized_by_human=True, request_id='005')\n",
            "module attribute reassignment": f"import {RGA} as g\nX = g.RealGenerationAuthorization\nX(authorized_by_human=True, request_id='005')\n",
            "function-local reassignment": f"from {RGA} import RealGenerationAuthorization as C\ndef f():\n    X = C\n    return X(authorized_by_human=True, request_id='005')\n",
            "annotated reassignment": f"from {RGA} import RealGenerationAuthorization as C\nX: type = C\nX(authorized_by_human=True, request_id='005')\n",
        }
        for label, source in cases.items():
            with self.subTest(case=label):
                self.assertIn(HUMAN, _codes(("agents/unknown_helper.py", source)))

    def test_other_authority_constructors_are_detected(self):
        cases = {
            "GenerationJobService alias": "from agents.generation_job_service import GenerationJobService as S\nS(None, None)\n",
            "GenerationApprovalGate reassignment": "from agents.generation_approval_gate import GenerationApprovalGate\nG = GenerationApprovalGate\nG(None)\n",
            "HiggsfieldClient alias + reassignment": CLIENT_IMPORT.replace("HiggsfieldClient\n", "HiggsfieldClient as K\n") + "C = K\nC()\n",
        }
        for label, source in cases.items():
            with self.subTest(case=label):
                self.assertIn(CTOR, _codes(("agents/unknown_helper.py", source)))

    def test_aliased_create_job_is_counted(self):
        cases = {
            "bound-method alias": "from integrations.higgsfield.provider import HiggsfieldProvider\ndef f(p):\n    cj = p.create_job\n    return cj('m', 'p')\n",
            "class-attribute reassignment": "from integrations.higgsfield.provider import HiggsfieldProvider\nCJ = HiggsfieldProvider.create_job\ndef f(p):\n    return CJ(p, 'm', 'p')\n",
        }
        for label, source in cases.items():
            with self.subTest(case=label):
                self.assertIn(CARD, _codes(SANCTIONED, ("agents/unknown_helper.py", source)))

    def test_informational_layer_aliased_authority_calls_are_detected(self):
        for name in ("execute", "create_job", "mark_executed", "prepare_activation", "validate_activation"):
            with self.subTest(call=name):
                source = f"def f(svc, r):\n    op = svc.{name}\n    return op(r)\n"
                self.assertIn(OUT_CALL, _codes(("agents/certificate_lifecycle.py", source)))

    def test_allowlisted_aliased_construction_stays_allowed(self):
        source = "from agents.generation_job_service import GenerationJobService as S\nX = S\nX(None, None)\n"
        self.assertNotIn(CTOR, _codes(("director.py", source)))

    def test_unrelated_aliases_and_reassignments_are_not_flagged(self):
        cases = {
            "unrelated reassignment": "def unrelated_symbol():\n    return 1\nX = unrelated_symbol\nX()\n",
            "neutral first-party alias": "from agents.planner import VideoPlanner as P\nX = P\nX(None)\n",
            "non-authority P2 symbol alias": f"from {RGA} import GenerationRequest as R\nX = R\nX(request_id='005')\n",
            "rebinding to a literal": "X = 3\nY = X\n",
            "self attribute is never a module reference": "class A:\n    def f(self):\n        X = self.helper\n        return X()\n",
        }
        for label, source in cases.items():
            with self.subTest(case=label):
                self.assertEqual(set(), _codes(("agents/unknown_helper.py", source)))

    def test_reassignment_cycle_terminates(self):
        self.assertEqual(set(), _codes(("agents/unknown_helper.py", "A = B\nB = A\nA()\n")))


class TestG2CliCreateCallSite(unittest.TestCase):
    def test_cli_create_call_outside_client_is_counted(self):
        cases = {
            "direct call": CLIENT_IMPORT + "def f(c):\n    return c.run('generate', 'create', 'seedance_2_0', '--prompt', 'p')\n",
            "verb-first form": CLIENT_IMPORT + "def f(c):\n    return c.run('create', 'seedance_2_0')\n",
            "client alias": CLIENT_IMPORT + "def f(client):\n    c = client\n    return c.run('generate', 'create')\n",
            "attribute access": CLIENT_IMPORT + "class A:\n    def f(self):\n        return self.higgsfield.run('generate', 'create')\n",
            "bound-method alias": CLIENT_IMPORT + "def f(c):\n    r = c.run\n    return r('generate', 'create')\n",
            "module-level reference": CLIENT_IMPORT + "R = HiggsfieldClient.run\ndef f(c):\n    return R(c, 'generate', 'create')\n",
            "literal star-args": CLIENT_IMPORT + "def f(c):\n    return c.run(*('generate', 'create'))\n",
            "duck-typed, no import": "def f(c):\n    return c.run('generate', 'create')\n",
        }
        for label, source in cases.items():
            with self.subTest(case=label):
                self.assertIn(CARD, _codes(SANCTIONED, ("agents/unknown_helper.py", source)))

    def test_cli_create_in_transitive_helper_is_counted(self):
        self.assertIn(CARD, _codes(
            SANCTIONED,
            ("agents/h2.py", "def g(c):\n    return c.run('generate', 'create')\n"),
            ("agents/h1.py", "from agents.h2 import g\ndef f(c):\n    return g(c)\n"),
        ))

    def test_cli_create_is_counted_even_when_it_is_the_only_call_site(self):
        # Relocated creation path: zero create_job() calls, one CLI create.
        self.assertTrue({CARD, "CREATE_JOB_CALLSITE_RELOCATED"} & _codes(
            ("agents/unknown_helper.py", "def f(c):\n    return c.run('generate', 'create')\n"),
        ))

    def test_client_module_itself_is_the_cli_boundary(self):
        source = "class HiggsfieldClient:\n    def create_job(self, t, p):\n        return self.run('generate', 'create', t, '--prompt', p)\n"
        self.assertNotIn(CARD, _codes(SANCTIONED, ("integrations/higgsfield/client.py", source)))

    def test_non_create_run_calls_are_not_counted(self):
        cases = {
            "status": "c.run('status')",
            "estimate": "c.run('estimate', 'seedance_2_0')",
            "balance": "c.run('balance')",
            "metadata": "c.run('metadata')",
            "generate cost": "c.run('generate', 'cost', 'seedance_2_0')",
            "generate get": "c.run('generate', 'get', 'job-1')",
            "generate wait": "c.run('generate', 'wait', 'job-1')",
            "generate list": "c.run('generate', 'list')",
            "account status": "c.run('account', 'status')",
            "non-literal verb": "c.run('generate', verb)",
            "similar literal": "c.run('generate', 'created')",
            "case differs": "c.run('generate', 'Create')",
            "keyword only": "c.run(cmd='create')",
            "list argument (subprocess-style)": "c.run(['git', 'create'])",
            "business agent run(request)": "c.run(request)",
        }
        for label, call in cases.items():
            with self.subTest(case=label):
                source = CLIENT_IMPORT + f"def f(c, verb=None, request=None):\n    return {call}\n"
                self.assertNotIn(CARD, _codes(SANCTIONED, ("agents/unknown_helper.py", source)))


class TestG3ReexportedCreatePath(unittest.TestCase):
    PROVIDER = "from integrations.higgsfield.provider import HiggsfieldProvider\n"
    CALL = "def f(p):\n    p.create_job('m', 'p')\n"

    def test_create_job_through_a_reexporting_module_is_counted(self):
        cases = {
            "named re-export": [("agents/h.py", self.PROVIDER), ("agents/u.py", "from agents.h import HiggsfieldProvider\n" + self.CALL)],
            "star re-export": [("agents/h.py", self.PROVIDER), ("agents/u.py", "from agents.h import *\n" + self.CALL)],
            "module-attribute re-export": [("agents/h.py", self.PROVIDER), ("agents/u.py", "import agents.h as h\nX = h.HiggsfieldProvider\n" + self.CALL)],
            "re-export chain": [("agents/h2.py", self.PROVIDER), ("agents/h1.py", "from agents.h2 import HiggsfieldProvider\n"), ("agents/u.py", "from agents.h1 import HiggsfieldProvider\n" + self.CALL)],
            "client re-export": [("agents/h.py", CLIENT_IMPORT), ("agents/u.py", "from agents.h import HiggsfieldClient\n" + self.CALL)],
        }
        for label, files in cases.items():
            with self.subTest(case=label):
                self.assertIn(CARD, _codes(SANCTIONED, *files))

    def test_namesakes_without_a_higgsfield_link_stay_unrelated(self):
        cases = {
            "no Higgsfield link at all": [("agents/u.py", self.CALL)],
            "helper re-exports a non-Higgsfield symbol": [("agents/h.py", "from agents.planner import VideoPlanner\n"), ("agents/u.py", "from agents.h import VideoPlanner\n" + self.CALL)],
            "unrelated name from a Higgsfield-importing helper": [("agents/h.py", self.PROVIDER + "def unrelated():\n    return 1\n"), ("agents/u.py", "from agents.h import unrelated\n" + self.CALL)],
        }
        for label, files in cases.items():
            with self.subTest(case=label):
                self.assertNotIn(CARD, _codes(SANCTIONED, *files))


class TestRepositoryStaysClean(unittest.TestCase):
    def test_real_repository_has_no_drift_and_single_create_path(self):
        report = ArchitectureDriftDetector().analyze()
        self.assertEqual(report.status.value, "NO_DRIFT", [f.code for f in report.findings])
