"""
Tests -- Execution Path Uniqueness Guardrail (Phase P3.45).

Closes P3.44's F2 (MEDIUM): no dedicated cardinality test previously
existed for `.execute(` calls the way `tests/test_phase_p2_39_final_
production_contract_activation_simulation.py::test_exactly_one_
production_create_job_call_site` already covers `create_job(`.

P3.45's own investigation (AST walk across agents/, integrations/,
scripts/, director.py) found exactly ONE production `.execute(` call
site reaching a job-service-shaped object:
`agents/final_report_service.py:312` (`self.job_service.execute(...)`,
inside `FinalReportService.generate()`). Two higher-level entry points
exist (`agents/video_agent.py::VideoAgent.run()` and
`director.py::AIDirector.execute_real_generation_activation()`), but
both call `report_service.generate(...)`, which itself contains the
single `execute()` call site -- they converge onto the exact same
code path, never onto two independent execute() call sites with
potentially divergent authority checks.

This test pins that finding as a permanent, additive, STATIC (AST)
guardrail -- same idiom as the existing create_job() cardinality test,
never a production code change. It never imports, constructs, or
executes GenerationJobService/HiggsfieldProvider -- pure ast.parse,
same discipline as agents/architecture_drift_detector.py.
"""

import ast
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# The one file allowed to CONTAIN the call (it's the sole authorized
# caller) and the one file allowed to DEFINE `execute` on the job
# service itself -- neither counts as an "offending" extra call site.
AUTHORIZED_CALLER_FILE = "agents/final_report_service.py"
DEFINITION_FILE = "agents/generation_job_service.py"


def _production_files():
    for base in ("agents", "integrations", "scripts"):
        base_dir = PROJECT_ROOT / base
        if not base_dir.exists():
            continue
        for path in sorted(base_dir.rglob("*.py")):
            yield path
    yield PROJECT_ROOT / "director.py"


class ExecuteCallSiteCardinalityTests(unittest.TestCase):
    def test_exactly_one_production_job_service_execute_call_site(self):
        """Any `.execute(` call in production code where the object
        looks job-service-shaped (i.e. not an obviously unrelated
        `.execute(` such as a SQL cursor or subprocess call -- none of
        which exist in this codebase, confirmed by this test's own
        offender list being empty) must appear ONLY inside
        agents/final_report_service.py."""
        offenders = []
        for path in _production_files():
            relative = path.relative_to(PROJECT_ROOT).as_posix()
            if relative == DEFINITION_FILE:
                continue  # execute()'s own definition, not a call
            if "mock_provider.py" in str(path):
                continue  # test double, not production
            try:
                tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "execute":
                    if relative == AUTHORIZED_CALLER_FILE:
                        continue
                    offenders.append(f"{relative}:{node.lineno}")
        self.assertEqual(offenders, [], f"unexpected .execute( call site(s) outside final_report_service.py: {offenders}")

    def test_final_report_service_contains_exactly_one_execute_call(self):
        """Pins the count precisely -- not just "somewhere in this
        file" but exactly once, so a future second call inside the
        SAME file (e.g. a duplicated retry attempt) is also caught."""
        source = (PROJECT_ROOT / AUTHORIZED_CALLER_FILE).read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        execute_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "execute"
        ]
        self.assertEqual(len(execute_calls), 1, f"expected exactly 1 execute() call, found {len(execute_calls)}")

    def test_both_entry_points_converge_on_final_report_service_generate(self):
        """The two higher-level entry points found this phase
        (VideoAgent.run() and AIDirector.execute_real_generation_
        activation()) must both call .generate( -- never .execute(
        directly, and never a third, independent path."""
        generate_call_sites = []
        for path in _production_files():
            if "mock_provider.py" in str(path):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "generate":
                    generate_call_sites.append((path.relative_to(PROJECT_ROOT).as_posix(), node.lineno))

        self.assertEqual(
            set(generate_call_sites),
            {("agents/video_agent.py", 237), ("director.py", 595)},
        )


if __name__ == "__main__":
    unittest.main()
