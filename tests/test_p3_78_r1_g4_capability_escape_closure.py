"""
Tests -- Authority Capability Escape Closure (P3.78-R1, G4-a/b/d).

P3.78 reproduced authority capabilities escaping as VALUES -- never as a
call the detector could see -- through callbacks, containers, returns,
registrations, `functools.partial`, class attributes and base classes.
The existing P3.68 production scan only covered `execute`/`create_job`,
and only under agents/, integrations/, scripts/ and director.py:

G4-a/d  An authority METHOD stored or passed instead of called
        (`call(client.run)`, `[gate.mark_executed]`, `return svc.consume`
        ...) -> AUTHORITY_METHOD_REFERENCE_ESCAPE.
G4-b    An authority-bearing SYMBOL used as a value (`[RealGeneration
        Authorization]`, `partial(RealGenerationAuthorization, ...)`,
        `class X(RealGenerationAuthorization)`) -> AUTHORITY_SYMBOL_AS_VALUE,
        only when its provenance really resolves (import, alias,
        re-export) to the P2 authority core -- never a textual name.

Allowed: calls, `isinstance`/`issubclass`, annotations, `is`/`is not`.

G4-c (`dataclasses.replace(rga, ...)`, `type(rga)(...)`) is NOT closed
here: it is a type-blind static limitation, characterized read-only in
the P3.78-R1 report -- see TestG4cDocumentedStaticLimitation.

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

METHOD = "AUTHORITY_METHOD_REFERENCE_ESCAPE"
SYMBOL = "AUTHORITY_SYMBOL_AS_VALUE"
GATE_FILE = "agents/generation_approval_gate.py"
JOB_FILE = "agents/generation_job_service.py"
G = "agents.generation_approval_gate"
AUTHORITY_METHODS = ("execute", "create_job", "run", "mark_executed", "mark_unknown",
                     "consume", "prepare_activation", "validate_activation")


def _real(rel):
    return rel, (PROJECT_ROOT / rel).read_text(encoding="utf-8")


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


class TestG4adAuthorityMethodReferenceEscape(unittest.TestCase):
    FORMS = {
        "assignment": "def f(o):\n    cb = o.{m}\n",
        "container": "def f(o):\n    callbacks = [o.{m}]\n",
        "dict registry": "def f(o):\n    return {{'go': o.{m}}}\n",
        "registration": "def register(cb):\n    return cb\ndef f(o):\n    register(o.{m})\n",
        "return value": "def f(o):\n    return o.{m}\n",
        "functools.partial": "import functools\ndef f(o):\n    return functools.partial(o.{m}, 'x')\n",
        "map": "def f(o, xs):\n    return list(map(o.{m}, xs))\n",
        "class attribute": "class K:\n    pass\nref = K.{m}\n",
        "default argument": "def f(o, cb=None):\n    return cb\ndef g(o):\n    return f(o, cb=o.{m})\n",
    }

    def test_every_authority_method_escape_form_is_detected(self):
        for method in AUTHORITY_METHODS:
            for label, template in self.FORMS.items():
                with self.subTest(method=method, form=label):
                    self.assertIn(METHOD, _codes(("agents/unknown_helper.py", template.format(m=method))))

    def test_p378_reproduced_callback_run_create_is_detected(self):
        source = ("def call(cb):\n    return cb('generate', 'create', 'seedance_2_0')\n"
                  "def f(c):\n    return call(c.run)\n")
        self.assertIn(METHOD, _codes(("agents/unknown_helper.py", source)))

    def test_detected_on_every_scanned_surface(self):
        source = "import functools\ndef f(p):\n    return functools.partial(p.create_job, 'm')\n"
        for rel in ("tools/helper.py", "helper.py", "scripts/tool.py", "director.py",
                    "agents/certificate_lifecycle.py", "integrations/higgsfield/extra.py"):
            with self.subTest(file=rel):
                self.assertIn(METHOD, _codes((rel, source)))

    def test_allowed_forms_are_not_flagged(self):
        cases = {
            "direct calls": "def f(o, r):\n    o.execute(r)\n    o.run('status')\n    o.mark_executed('005')\n",
            "identity comparison": "def f(p, P):\n    return type(p).create_job is P.create_job\n",
            "is not comparison": "def f(p, P):\n    return type(p).create_job is not P.create_job\n",
            "unrelated attributes": "def f(o):\n    return [o.status, o.running, o.executed, o.runner]\n",
            "method definitions": "class S:\n    def run(self):\n        return 1\n    def execute(self):\n        return self.run()\n",
            "attribute store": "def f(o, v):\n    o.run = v\n",
        }
        for label, source in cases.items():
            with self.subTest(case=label):
                self.assertNotIn(METHOD, _codes(("agents/unknown_helper.py", source)))

    def test_test_domain_is_exempt(self):
        self.assertNotIn(METHOD, _codes(("tests/test_x.py", "def f(o):\n    return [o.execute]\n")))


class TestG4bAuthoritySymbolAsValue(unittest.TestCase):
    FORMS = {
        "assignment": "x = {s}\n",
        "container": "items = [{s}]\n",
        "return": "def f():\n    return {s}\n",
        "registration": "def register(c):\n    return c\nregister({s})\n",
        "functools.partial": "import functools\nmk = functools.partial({s}, authorized_by_human=True)\n",
        "dict": "table = {{'a': {s}}}\n",
        "default argument": "def f(c={s}):\n    return c\n",
        "equality comparison": "def f(x):\n    return type(x) == {s}\n",
        "base class": "class Fake({s}):\n    pass\n",
    }

    def test_every_value_form_is_detected(self):
        for label, template in self.FORMS.items():
            with self.subTest(form=label):
                source = f"from {G} import RealGenerationAuthorization\n" + template.format(s="RealGenerationAuthorization")
                self.assertIn(SYMBOL, _codes(_real(GATE_FILE), ("agents/unknown_helper.py", source)))

    def test_provenance_forms_are_detected(self):
        cases = {
            "import alias (G1)": [("agents/u.py", f"from {G} import RealGenerationAuthorization as H\nitems = [H]\n")],
            "alias + reassignment (G1)": [("agents/u.py", f"from {G} import RealGenerationAuthorization as H\nX = H\n")],
            "module attribute": [("agents/u.py", f"import {G} as g\nitems = [g.RealGenerationAuthorization]\n")],
            "absolute module attribute": [("agents/u.py", f"import {G}\nitems = [{G}.RealGenerationAuthorization]\n")],
            "relative import": [("agents/u.py", "from .generation_approval_gate import RealGenerationAuthorization\nitems = [RealGenerationAuthorization]\n")],
            "re-export (G3 family)": [("agents/h.py", f"from {G} import RealGenerationAuthorization\n"), ("agents/u.py", "from agents.h import RealGenerationAuthorization\nitems = [RealGenerationAuthorization]\n")],
            "star re-export": [("agents/h.py", f"from {G} import RealGenerationAuthorization\n"), ("agents/u.py", "from agents.h import *\nitems = [RealGenerationAuthorization]\n")],
            "GenerationJobService": [_real(JOB_FILE), ("agents/u.py", "from agents.generation_job_service import GenerationJobService\nitems = [GenerationJobService]\n")],
            "root-level unknown helper": [("tools/helper.py", f"from {G} import RealGenerationAuthorization\nitems = [RealGenerationAuthorization]\n")],
            "script": [("scripts/tool.py", f"from {G} import RealGenerationAuthorization\nitems = [RealGenerationAuthorization]\n")],
            "defining module leaks its own class": [(GATE_FILE, (PROJECT_ROOT / GATE_FILE).read_text(encoding="utf-8") + "\nLEAK = [RealGenerationAuthorization]\n")],
        }
        for label, files in cases.items():
            with self.subTest(case=label):
                extra = [] if any(rel == GATE_FILE for rel, _ in files) else [_real(GATE_FILE)]
                self.assertIn(SYMBOL, _codes(*extra, *files))

    def test_allowed_contexts_are_not_flagged(self):
        cases = {
            "construction call": "RealGenerationAuthorization(authorized_by_human=True, request_id='005')\n",
            "isinstance": "def f(x):\n    return isinstance(x, RealGenerationAuthorization)\n",
            "isinstance tuple": "def f(x):\n    return isinstance(x, (RealGenerationAuthorization, int))\n",
            "issubclass": "def f(t):\n    return issubclass(t, RealGenerationAuthorization)\n",
            "annotations": "from typing import Optional\ndef f(a: Optional[RealGenerationAuthorization]) -> RealGenerationAuthorization:\n    b: RealGenerationAuthorization = a\n    return b\n",
            "is comparison": "def f(x):\n    return type(x) is RealGenerationAuthorization\n",
        }
        for label, body in cases.items():
            with self.subTest(case=label):
                source = f"from {G} import RealGenerationAuthorization\n" + body
                self.assertNotIn(SYMBOL, _codes(_real(GATE_FILE), ("agents/unknown_helper.py", source)))

    def test_provenance_is_required_never_a_textual_name(self):
        cases = {
            "parameter named like the symbol": [("agents/u.py", "def f(RealGenerationAuthorization):\n    return [RealGenerationAuthorization]\n")],
            "local class with the same name": [("agents/u.py", "class GenerationJobService:\n    pass\nitems = [GenerationJobService]\n")],
            "same name imported from a non-authority module": [("agents/fake.py", "class GenerationJobService:\n    pass\n"), ("agents/u.py", "from agents.fake import GenerationJobService\nitems = [GenerationJobService]\n")],
            "non-authority P2 symbol": [("agents/u.py", f"from {G} import GenerationRequest\nitems = [GenerationRequest]\n")],
            "authority module name as a value": [("agents/u.py", f"import {G} as g\nmods = [g]\n")],
        }
        for label, files in cases.items():
            with self.subTest(case=label):
                self.assertNotIn(SYMBOL, _codes(_real(GATE_FILE), *files))


class TestG4cDocumentedStaticLimitation(unittest.TestCase):
    """G4-c: deriving an authorization from an EXISTING object is
    syntactically identical to a benign dataclass copy -- the detector
    has no type/provenance information for `a` and never claims to."""

    def test_replace_and_type_derivation_remain_undetected_by_design(self):
        source = (
            "import dataclasses\n"
            "def f(a):\n    return dataclasses.replace(a, request_id='006')\n"
            "def g(a):\n    return type(a)(authorized_by_human=True, request_id='006')\n"
        )
        codes = _codes(_real(GATE_FILE), ("agents/unknown_helper.py", source))
        self.assertNotIn(SYMBOL, codes)  # documented static limitation -- not closed, not overclaimed
        self.assertNotIn("AUTOMATIC_HUMAN_AUTHORIZATION", codes)


class TestRepositoryStaysClean(unittest.TestCase):
    def test_real_repository_has_no_capability_escape(self):
        report = ArchitectureDriftDetector().analyze()
        self.assertEqual(report.status.value, "NO_DRIFT", [(f.code, f.file, f.line) for f in report.findings])
