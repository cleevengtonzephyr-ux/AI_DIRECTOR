"""
Tests -- Execution Ordering Guardrail (Phase P3.44).

P3.44's refactoring-hazard simulation (Scenarios H and I) asked
specifically: if a future developer moved the identity check after
create_job(), or moved mark_executed() outside the critical section,
would anything catch it?

Direct investigation this phase found the answer was: only indirectly,
and only under true OS-level concurrency (the historical P2.16
subprocess demonstration) -- no test asserted the STRUCTURAL position
of these calls relative to each other or to the `with self.lock.
acquire(...)` block in agents/generation_job_service.py::execute().
A single-threaded regression test cannot distinguish "mark_executed()
one line before the `with` block ends" from "mark_executed() one line
after it ends" -- both produce identical observable behavior absent
real concurrent timing, so a silent, `git diff`-invisible-to-a-quick-
review refactor moving it would pass the entire existing suite.

This file closes that gap with AST-based structural (STATIC) tests --
the codebase's own established idiom (agents/architecture_drift_
detector.py, and every P2.25/P3.19-23/33-42 construction-absence test)
-- rather than a fragile timing-based test. It reads
agents/generation_job_service.py's source; it never imports, executes,
or modifies it.

Fully offline: no network, no Higgsfield CLI, no execution of any kind.
"""

import ast
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TARGET_FILE = PROJECT_ROOT / "agents" / "generation_job_service.py"


def _execute_method_node() -> ast.FunctionDef:
    source = TARGET_FILE.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "GenerationJobService":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "execute":
                    return item
    raise AssertionError("GenerationJobService.execute not found")


def _with_lock_acquire_node(execute_node: ast.FunctionDef):
    """The top-level `with self.lock.acquire(...)` statement inside
    execute()'s body -- not nested inside any conditional, matching
    the documented "entire sequence lives inside one lock" design."""
    for stmt in execute_node.body:
        if isinstance(stmt, ast.With):
            for item in stmt.items:
                call = item.context_expr
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "acquire"
                    and isinstance(call.func.value, ast.Attribute)
                    and call.func.value.attr == "lock"
                ):
                    return stmt
    raise AssertionError("with self.lock.acquire(...) not found as a top-level statement in execute()")


def _call_line_numbers(node, attr_name: str, value_attr: str = None):
    """Every ast.Call line number where `.<attr_name>(` is invoked,
    optionally restricted to calls on `self.<value_attr>`."""
    lines = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr_name:
            if value_attr is not None:
                if not (isinstance(n.func.value, ast.Attribute) and n.func.value.attr == value_attr):
                    continue
            lines.append(n.lineno)
    return lines


class ExecutionOrderingGuardrailTests(unittest.TestCase):
    def test_lock_acquire_is_a_top_level_statement_in_execute(self):
        """Baseline structural fact this whole file depends on."""
        execute_node = _execute_method_node()
        lock_stmt = _with_lock_acquire_node(execute_node)
        self.assertIsNotNone(lock_stmt)

    def test_mark_executed_and_mark_unknown_remain_inside_the_lock(self):
        """Scenario I: if a future refactor moved gate.mark_executed()/
        mark_unknown() to after the `with` block, this test fails --
        it asserts both calls are lexically nested within the with-
        statement's own body, not merely present somewhere in
        execute()."""
        execute_node = _execute_method_node()
        lock_stmt = _with_lock_acquire_node(execute_node)

        calls_inside_lock = {
            n.func.attr
            for n in ast.walk(lock_stmt)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("mark_executed", "mark_unknown")
            and isinstance(n.func.value, ast.Attribute) and n.func.value.attr == "gate"
        }
        self.assertIn("mark_executed", calls_inside_lock)
        self.assertIn("mark_unknown", calls_inside_lock)

        # And NOT present anywhere in execute() outside the lock body.
        all_gate_marks = {
            n.func.attr
            for n in ast.walk(execute_node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("mark_executed", "mark_unknown")
            and isinstance(n.func.value, ast.Attribute) and n.func.value.attr == "gate"
        }
        outside_lock_body_ids = {id(n) for n in ast.walk(execute_node)} - {id(n) for n in ast.walk(lock_stmt)}
        marks_outside = [
            n for n in ast.walk(execute_node)
            if id(n) in outside_lock_body_ids
            and isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("mark_executed", "mark_unknown")
            and isinstance(n.func.value, ast.Attribute) and n.func.value.attr == "gate"
        ]
        self.assertFalse(marks_outside, "gate.mark_executed()/mark_unknown() found OUTSIDE the critical section")
        self.assertEqual(all_gate_marks, calls_inside_lock)

    def test_wait_for_job_remains_outside_the_lock(self):
        """Positive control / documents the deliberate counter-case:
        provider.wait_for_job() is intentionally NOT inside the lock
        (polling doesn't need exclusivity once mark_executed() has
        already closed the replay window) -- confirms this test suite
        distinguishes "must be inside" from "must be outside", not
        just "everything should be inside the lock"."""
        execute_node = _execute_method_node()
        lock_stmt = _with_lock_acquire_node(execute_node)
        wait_calls_inside_lock = [
            n for n in ast.walk(lock_stmt)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "wait_for_job"
        ]
        self.assertFalse(wait_calls_inside_lock, "wait_for_job() unexpectedly found inside the critical section")

    def test_identity_verification_precedes_create_job_in_source_order(self):
        """Scenario H: fresh Gate evaluation (which performs identity
        verification via the Identity Lock, cf. GenerationApprovalGate.
        evaluate) must appear, in source order, before provider.
        create_job() -- both inside the same lock. A future refactor
        reordering these two calls fails this test even though a
        single-threaded functional test might not distinguish the two
        orderings for a single non-adversarial input."""
        execute_node = _execute_method_node()
        gate_evaluate_lines = _call_line_numbers(execute_node, "evaluate", value_attr="gate")
        create_job_lines = _call_line_numbers(execute_node, "create_job", value_attr="provider")
        self.assertTrue(gate_evaluate_lines, "gate.evaluate(...) call not found in execute()")
        self.assertTrue(create_job_lines, "provider.create_job(...) call not found in execute()")
        self.assertLess(
            min(gate_evaluate_lines), min(create_job_lines),
            "gate.evaluate() (identity/budget/replay verification) must precede provider.create_job() in source order",
        )

    def test_activation_consumption_precedes_create_job_in_source_order(self):
        """Activation must be consumed (single-use enforced) before
        create_job() is reached -- a future refactor swapping this
        order would let create_job() run before the activation
        contract is irreversibly marked used."""
        execute_node = _execute_method_node()
        consume_lines = _call_line_numbers(execute_node, "consume", value_attr="activation_service")
        create_job_lines = _call_line_numbers(execute_node, "create_job", value_attr="provider")
        if consume_lines:  # only called when activation_contract is not None, but the call site itself always exists
            self.assertLess(min(consume_lines), min(create_job_lines))


if __name__ == "__main__":
    unittest.main()
