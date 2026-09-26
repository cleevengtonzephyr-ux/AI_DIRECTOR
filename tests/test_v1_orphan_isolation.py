"""
Tests -- V1 Orphan Code Isolation (Phase P3.42).

P3.42's Section 17 re-examined the modules historically described as
"V1 legacy" and classified each one precisely via a real import-graph
walk (not by trusting the label) -- see the P3.42 report for the full
per-module evidence. Confirmed orphaned (zero path from director.py's
transitive import graph): `higgsfield_executor.py`, `job_monitor.py`,
`qa_engine.py`, `asset_manager.py`, `pipeline_orchestrator.py`,
`production_controller.py`, `production_gate.py`,
`asset_intake_manager.py`, `cost_engine.py`, `asset_resolver.py`.

This is the one genuinely new, durable guardrail this phase's audit
justified: a permanent regression test that fails loudly if any of
these ever becomes reachable from `director.py` again (accidental
re-wiring, a future refactor importing the wrong "gate"/"cost" module
by name -- `production_gate.py` vs `generation_approval_gate.py`, or
`cost_engine.py` vs `generation_cost_service.py`, are exactly the kind
of confusable near-duplicate names a future developer could mis-import).

Not a deletion, not a modification of the orphan files themselves --
purely an additive detection test, per this phase's "ne pas supprimer
automatiquement" instruction.
"""

import ast
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CONFIRMED_V1_ORPHANS = frozenset({
    "agents.higgsfield_executor",
    "agents.job_monitor",
    "agents.qa_engine",
    "agents.asset_manager",
    "agents.pipeline_orchestrator",
    "agents.production_controller",
    "agents.production_gate",
    "agents.asset_intake_manager",
    "agents.cost_engine",
    "agents.asset_resolver",
})


def _module_imports(path: Path) -> set:
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
    return imports


def _transitive_import_closure(entry_file: Path) -> set:
    """BFS over local (agents.*/director) module names only -- never
    follows third-party or stdlib imports, and never executes any
    code (ast.parse only, same discipline as the Architecture Drift
    Detector, agents/architecture_drift_detector.py)."""
    visited = set()
    frontier = [entry_file]
    while frontier:
        current = frontier.pop()
        current_imports = _module_imports(current)
        for module_name in current_imports:
            if module_name in visited:
                continue
            if not (module_name.startswith("agents.") or module_name == "director"):
                continue
            visited.add(module_name)
            candidate = (
                PROJECT_ROOT / (module_name.replace(".", "/") + ".py")
                if module_name != "director"
                else PROJECT_ROOT / "director.py"
            )
            if candidate.exists():
                frontier.append(candidate)
    return visited


class V1OrphanIsolationTests(unittest.TestCase):
    def test_confirmed_v1_orphans_are_unreachable_from_director(self):
        closure = _transitive_import_closure(PROJECT_ROOT / "director.py")
        reachable_orphans = closure & CONFIRMED_V1_ORPHANS
        self.assertFalse(
            reachable_orphans,
            f"V1 orphan module(s) became reachable from director.py's import "
            f"graph -- this is exactly the accidental-rewiring regression "
            f"this guardrail exists to catch: {reachable_orphans}",
        )

    def test_confirmed_v1_orphans_still_exist_on_disk(self):
        """If one of these files is ever deleted, this test should be
        updated deliberately (removed from the set), not silently pass
        as vacuously true -- this assertion makes that an explicit,
        visible decision rather than a silent one."""
        for module_name in CONFIRMED_V1_ORPHANS:
            path = PROJECT_ROOT / (module_name.replace(".", "/") + ".py")
            self.assertTrue(path.exists(), f"{module_name} no longer exists on disk -- update this test's orphan set")


if __name__ == "__main__":
    unittest.main()
