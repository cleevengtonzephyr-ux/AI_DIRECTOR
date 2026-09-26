"""
Tests -- GenerationApprovalGate Construction Inventory Guardrail (P3.47).

P3.47's full repository AST inventory (211 total `GenerationApprovalGate(`
construction sites) found: exactly ONE in production (`director.py:242`,
both `executed_request_store` and `identity_lock` supplied explicitly),
exactly TWO in `scripts/demo_test.py` (unsafe defaults, but confirmed
paired only with `MockHiggsfieldProvider`, P3.40), and 208 in `tests/`.
No aliased import of the class was found anywhere (`GenerationApprovalGate
as X`), and no `agents/*.py` file other than none at all constructs the
class -- the two files that import it as a type
(`real_provider_activation_preflight.py`, `real_provider_execution_gate.py`)
never call it.

This file pins that inventory shape as a permanent, additive, STATIC
(AST) guardrail: any FUTURE construction site appearing anywhere in
`agents/`, `integrations/`, or `director.py` (i.e. real production
code, never `tests/` or `scripts/`) that does NOT supply both
`executed_request_store` and `identity_lock` explicitly fails this
test immediately -- closing exactly the gap Scenario A/B/D of P3.47's
mission asked about (a new unsafe construction appearing in a P3 agent
or a new wrapper, undetected).

Pure `ast.parse` -- never imports, constructs, or executes
GenerationApprovalGate itself.
"""

import ast
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# The one production construction site this test knows to be safe --
# any OTHER production construction site, safe or not, is itself new
# and must be reviewed (this test fails loud rather than silently
# accepting a second "safe-looking" site it hasn't seen before).
KNOWN_SAFE_PRODUCTION_SITE = ("director.py", 242)

REQUIRED_KWARGS = {"executed_request_store", "identity_lock"}


def _scan_directory_for_constructions(base_dir: Path):
    sites = []
    for path in sorted(base_dir.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name == "GenerationApprovalGate":
                    kwarg_names = {kw.arg for kw in node.keywords if kw.arg}
                    sites.append((path.relative_to(PROJECT_ROOT).as_posix(), node.lineno, kwarg_names))
    return sites


class GateConstructionInventoryTests(unittest.TestCase):
    def test_every_production_construction_supplies_store_and_identity_lock(self):
        """Scans agents/, integrations/, and director.py (never tests/
        or scripts/ -- those are explicitly out of scope, same
        exclusion the Architecture Drift Detector itself documents)
        for GenerationApprovalGate(...) construction sites. Every one
        found must supply both executed_request_store and
        identity_lock explicitly -- the unsafe default combination
        must never appear in real production code."""
        sites = []
        for d in ("agents", "integrations"):
            sites += _scan_directory_for_constructions(PROJECT_ROOT / d)
        sites += [
            (rel, lineno, kwargs)
            for rel, lineno, kwargs in _scan_directory_for_constructions(PROJECT_ROOT)
            if rel == "director.py"
        ]

        unsafe = [(f, ln, kw) for f, ln, kw in sites if not REQUIRED_KWARGS.issubset(kw)]
        self.assertEqual(
            unsafe, [],
            f"unsafe GenerationApprovalGate construction (missing executed_request_store "
            f"and/or identity_lock) found in production code: {unsafe}",
        )

    def test_exactly_one_known_safe_production_construction_site(self):
        """Pins the exact count and location -- a SECOND production
        construction site (even a safe-looking one) is itself new and
        must be reviewed by a human, not silently accepted."""
        sites = []
        for d in ("agents", "integrations"):
            sites += _scan_directory_for_constructions(PROJECT_ROOT / d)
        sites += [
            (rel, lineno, kwargs)
            for rel, lineno, kwargs in _scan_directory_for_constructions(PROJECT_ROOT)
            if rel == "director.py"
        ]
        locations = [(f, ln) for f, ln, _ in sites]
        self.assertEqual(locations, [KNOWN_SAFE_PRODUCTION_SITE])

    def test_no_aliased_import_evades_this_scan(self):
        """Confirms no `from agents.generation_approval_gate import
        GenerationApprovalGate as X` exists anywhere -- which would
        let a construction site evade the name-matching scan above."""
        offenders = []
        for base in ("agents", "integrations", "director.py"):
            base_path = PROJECT_ROOT / base
            paths = [base_path] if base_path.is_file() else list(base_path.rglob("*.py"))
            for path in paths:
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
                except (SyntaxError, UnicodeDecodeError):
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        for alias in node.names:
                            if alias.name == "GenerationApprovalGate" and alias.asname:
                                offenders.append(f"{path.relative_to(PROJECT_ROOT)}: as {alias.asname}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
