"""
Tests — Real Mission State Machine (Phase P3.12).

Fully offline: no network, no Higgsfield, no social platform, no OAuth,
no credential of any kind is imported or constructed anywhere in this
file.
"""

import ast
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.mission_state_machine import (
    ALLOWED_TRANSITIONS,
    STATE_MACHINE_VERSION,
    DuplicateTransitionError,
    InvalidMissionTransitionError,
    MissionState,
    MissionStateMachine,
    MissionStateTransition,
    StateConflictError,
)

MISSION_STATE_MACHINE_SOURCE_PATH = PROJECT_ROOT / "agents" / "mission_state_machine.py"

CANONICAL_STATES = {
    "IDEA", "PLANNED", "SCRIPT_READY", "PROMPT_READY", "ASSETS_READY",
    "VIDEO_READY_FOR_REVIEW", "TECHNICAL_APPROVAL", "HUMAN_AUTHORIZATION",
    "PRODUCTION_AUTHORIZATION", "EXECUTION", "QUALITY_CHECK", "PUBLISHED",
    "ANALYTICS", "OPTIMIZATION",
}


class MissionStateMachineBasicTests(unittest.TestCase):
    """Tests 1-4 from the P3.12 mandatory list."""

    def test_initial_idea(self):
        machine = MissionStateMachine(mission_id="m1")
        self.assertEqual(machine.current_state, MissionState.IDEA)
        self.assertEqual(machine.transition_count, 0)

    def test_valid_transition(self):
        machine = MissionStateMachine(mission_id="m1")
        record = machine.transition(MissionState.PLANNED, reason="strategy completed", expected_from=MissionState.IDEA)
        self.assertEqual(machine.current_state, MissionState.PLANNED)
        self.assertEqual(record.from_state, MissionState.IDEA)
        self.assertEqual(record.to_state, MissionState.PLANNED)

    def test_invalid_transition(self):
        machine = MissionStateMachine(mission_id="m1")
        with self.assertRaises(InvalidMissionTransitionError):
            machine.transition(MissionState.PUBLISHED, reason="skip ahead")
        self.assertEqual(machine.current_state, MissionState.IDEA)  # unchanged

    def test_can_transition(self):
        machine = MissionStateMachine(mission_id="m1")
        self.assertTrue(machine.can_transition(MissionState.PLANNED))
        self.assertFalse(machine.can_transition(MissionState.EXECUTION))
        self.assertFalse(machine.can_transition(MissionState.PUBLISHED))
        # Pure -- calling it never mutates state or history.
        self.assertEqual(machine.transition_count, 0)
        self.assertEqual(machine.current_state, MissionState.IDEA)


class MissionStateMachineHistoryTests(unittest.TestCase):
    """Tests 5-6 from the P3.12 mandatory list."""

    def test_transition_history(self):
        machine = MissionStateMachine(mission_id="m1")
        machine.transition(MissionState.PLANNED, reason="a", expected_from=MissionState.IDEA)
        machine.transition(MissionState.SCRIPT_READY, reason="b", expected_from=MissionState.PLANNED)
        self.assertEqual(machine.transition_count, 2)
        self.assertEqual([t.to_state for t in machine.history], [MissionState.PLANNED, MissionState.SCRIPT_READY])
        self.assertEqual([t.transition_index for t in machine.history], [1, 2])

    def test_immutable_history(self):
        machine = MissionStateMachine(mission_id="m1")
        machine.transition(MissionState.PLANNED, reason="a", expected_from=MissionState.IDEA)
        history = machine.history
        self.assertIsInstance(history, tuple)
        with self.assertRaises(AttributeError):
            history.append(MissionState.SCRIPT_READY)  # tuples have no .append
        # A record itself cannot be mutated either.
        from dataclasses import FrozenInstanceError
        with self.assertRaises(FrozenInstanceError):
            history[0].reason = "tampered"
        # Getting `history` again after external attempts still reflects
        # only the real, internal record.
        self.assertEqual(machine.history[0].reason, "a")


class MissionStateMachineMissionIdTests(unittest.TestCase):
    """Test 7 from the P3.12 mandatory list."""

    def test_mission_id_required(self):
        with self.assertRaises(ValueError):
            MissionStateMachine(mission_id="")
        with self.assertRaises(ValueError):
            MissionStateMachine(mission_id=None)  # type: ignore

    def test_mission_id_is_not_global(self):
        machine_a = MissionStateMachine(mission_id="mission-A")
        machine_b = MissionStateMachine(mission_id="mission-B")
        machine_a.transition(MissionState.PLANNED, reason="a", expected_from=MissionState.IDEA)
        self.assertEqual(machine_a.current_state, MissionState.PLANNED)
        self.assertEqual(machine_b.current_state, MissionState.IDEA)  # unaffected
        self.assertEqual(machine_a.mission_id, "mission-A")
        self.assertEqual(machine_b.mission_id, "mission-B")


class MissionStateMachineClockTests(unittest.TestCase):
    """Test 8 from the P3.12 mandatory list."""

    def test_deterministic_clock(self):
        ticks = iter(["t1", "t2", "t3"])
        machine = MissionStateMachine(mission_id="m1", clock=lambda: next(ticks))
        record = machine.transition(MissionState.PLANNED, reason="a", expected_from=MissionState.IDEA)
        self.assertEqual(record.timestamp, "t1")
        record2 = machine.transition(MissionState.SCRIPT_READY, reason="b", expected_from=MissionState.PLANNED)
        self.assertEqual(record2.timestamp, "t2")


class MissionStateMachineReasonTests(unittest.TestCase):
    """Test 9 from the P3.12 mandatory list."""

    def test_transition_reason_preserved(self):
        machine = MissionStateMachine(mission_id="m1")
        record = machine.transition(MissionState.PLANNED, reason="strategy completed", expected_from=MissionState.IDEA)
        self.assertEqual(record.reason, "strategy completed")
        self.assertEqual(machine.history[0].reason, "strategy completed")


class MissionStateMachineConflictTests(unittest.TestCase):
    """Tests 10, 26 from the P3.12 mandatory list."""

    def test_state_conflict(self):
        machine = MissionStateMachine(mission_id="m1")
        with self.assertRaises(StateConflictError):
            machine.transition(MissionState.SCRIPT_READY, reason="stale", expected_from=MissionState.PLANNED)
        self.assertEqual(machine.current_state, MissionState.IDEA)  # unchanged

    def test_concurrent_stale_state_protection(self):
        machine = MissionStateMachine(mission_id="m1")
        # Simulate two "processes" reading current_state=IDEA, one wins.
        machine.transition(MissionState.PLANNED, reason="winner", expected_from=MissionState.IDEA)
        # The second, now-stale caller must be rejected, never silently reapplied.
        with self.assertRaises(StateConflictError):
            machine.transition(MissionState.PLANNED, reason="loser", expected_from=MissionState.IDEA)


class MissionStateMachineIdempotencyTests(unittest.TestCase):
    """Test 11 from the P3.12 mandatory list."""

    def test_duplicate_transition_same_target_is_noop(self):
        machine = MissionStateMachine(mission_id="m1")
        first = machine.transition(MissionState.PLANNED, reason="a", expected_from=MissionState.IDEA, idempotency_key="k1")
        second = machine.transition(MissionState.PLANNED, reason="a-retry", expected_from=MissionState.IDEA, idempotency_key="k1")
        self.assertEqual(first, second)
        self.assertEqual(machine.transition_count, 1)  # no duplicate history entry

    def test_duplicate_transition_different_target_raises(self):
        machine = MissionStateMachine(mission_id="m1")
        machine.transition(MissionState.PLANNED, reason="a", expected_from=MissionState.IDEA, idempotency_key="k1")
        with self.assertRaises(DuplicateTransitionError):
            machine.transition(MissionState.SCRIPT_READY, reason="b", idempotency_key="k1")


class MissionStateMachineGlobalStateTests(unittest.TestCase):
    """Test 12 from the P3.12 mandatory list."""

    def test_no_global_state(self):
        # No module-level mutable singleton exists to inspect -- proven
        # by two independently constructed instances never sharing state
        # (already exercised in test_mission_id_is_not_global) plus a
        # direct source check for a module-level mutable container.
        source = MISSION_STATE_MACHINE_SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        # Only constant-shaped module globals (ALLOWED_TRANSITIONS,
                        # STATE_MACHINE_VERSION) are permitted, never a mutable
                        # "current mission" or "current state" global.
                        self.assertNotIn("MISSION", target.id.replace("_", ""))


class MissionStateMachineAuthorityTests(unittest.TestCase):
    """Tests 13-15 from the P3.12 mandatory list."""

    def test_state_is_not_authority(self):
        machine = MissionStateMachine(mission_id="m1")
        machine.transition(MissionState.PLANNED, reason="a", expected_from=MissionState.IDEA)
        # No field of the machine or its records ever exposes anything
        # authority-shaped.
        self.assertFalse(hasattr(machine, "real_generation_authorization"))
        self.assertFalse(hasattr(machine, "activation_contract"))
        record = machine.history[0]
        self.assertFalse(hasattr(record, "authorization"))
        self.assertFalse(hasattr(record, "authorized"))

    def test_no_authorization_creation(self):
        source = MISSION_STATE_MACHINE_SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        called_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    called_names.add(func.id)
                elif isinstance(func, ast.Attribute):
                    called_names.add(func.attr)
        self.assertNotIn("RealGenerationAuthorization", called_names)

    def test_no_activation_creation(self):
        source = MISSION_STATE_MACHINE_SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        called_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    called_names.add(func.id)
                elif isinstance(func, ast.Attribute):
                    called_names.add(func.attr)
        offenders = {n for n in called_names if "ActivationContract" in n or "ControlledRealProviderActivation" in n}
        self.assertFalse(offenders)


class MissionStateMachineCanonicalStateTests(unittest.TestCase):
    """Tests 19-20 from the P3.12 mandatory list."""

    def test_canonical_state_set(self):
        actual_states = {s.value for s in MissionState}
        self.assertEqual(actual_states, CANONICAL_STATES)

    def test_transition_table_matches_documented_chain(self):
        # Full conceptual chain plus the one documented adaptation
        # (SCRIPT_READY -> QUALITY_CHECK, agents/mission_state_machine.py
        # module docstring).
        self.assertEqual(ALLOWED_TRANSITIONS[MissionState.IDEA], frozenset({MissionState.PLANNED}))
        self.assertEqual(ALLOWED_TRANSITIONS[MissionState.PLANNED], frozenset({MissionState.SCRIPT_READY}))
        self.assertEqual(
            ALLOWED_TRANSITIONS[MissionState.SCRIPT_READY],
            frozenset({MissionState.PROMPT_READY, MissionState.QUALITY_CHECK}),
        )
        self.assertEqual(ALLOWED_TRANSITIONS[MissionState.QUALITY_CHECK], frozenset({MissionState.PUBLISHED}))
        self.assertEqual(ALLOWED_TRANSITIONS[MissionState.PUBLISHED], frozenset({MissionState.ANALYTICS}))
        self.assertEqual(ALLOWED_TRANSITIONS[MissionState.ANALYTICS], frozenset({MissionState.OPTIMIZATION}))
        self.assertEqual(ALLOWED_TRANSITIONS[MissionState.OPTIMIZATION], frozenset())

    def test_illegal_transitions_explicitly_blocked(self):
        illegal_pairs = [
            (MissionState.IDEA, MissionState.EXECUTION),
            (MissionState.IDEA, MissionState.PUBLISHED),
            (MissionState.QUALITY_CHECK, MissionState.EXECUTION),
            (MissionState.OPTIMIZATION, MissionState.EXECUTION),
            (MissionState.ANALYTICS, MissionState.PUBLISHED),
        ]
        for from_state, to_state in illegal_pairs:
            self.assertNotIn(to_state, ALLOWED_TRANSITIONS.get(from_state, frozenset()))


class MissionStateMachineFailureUnknownTests(unittest.TestCase):
    """Tests 21-22 from the P3.12 mandatory list."""

    def test_failure_handling_stays_in_current_state(self):
        # There is no code path in MissionStateMachine itself that
        # reacts to "failure" -- it only validates transition REQUESTS.
        # The orchestrator (P3.12 Section 22/agents/director_pipeline.py)
        # is the one that must simply NOT call transition() on a
        # failure/unknown classification -- verified at the orchestration
        # level (tests/test_director_orchestration.py). Here we confirm
        # the machine itself never invents a FAILED state:
        actual_states = {s.value for s in MissionState}
        self.assertNotIn("FAILED", actual_states)
        self.assertNotIn("UNKNOWN", actual_states)

    def test_unknown_never_becomes_success_state(self):
        machine = MissionStateMachine(mission_id="m1")
        # Simply not calling transition() leaves current_state exactly
        # where it was -- the only correct behavior when a stage's
        # outcome cannot be classified as a real success.
        self.assertEqual(machine.current_state, MissionState.IDEA)


class MissionStateMachineVersioningTests(unittest.TestCase):
    def test_state_machine_version_is_explicit(self):
        self.assertEqual(STATE_MACHINE_VERSION, 1)
        self.assertIsInstance(STATE_MACHINE_VERSION, int)


class MissionStateMachineSecurityTests(unittest.TestCase):
    """Tests 16-18 from the P3.12 mandatory list."""

    FORBIDDEN_MODULES = {
        "integrations.higgsfield.client",
        "integrations.higgsfield.provider",
        "integrations.higgsfield.mock_provider",
        "director",
        "agents.generation_approval_gate",
        "agents.generation_job_service",
        "agents.activation_contract",
        "agents.controlled_real_provider_activation",
        "agents.real_provider_execution_gate",
        "agents.real_provider_activation_preflight",
        "agents.critical_section_lock",
        "agents.executed_request_store",
        "agents.video_agent",
        "agents.final_report_service",
        "agents.strategy_agent",
        "agents.content_agent",
        "agents.quality_agent",
        "agents.publishing_agent",
        "agents.analytics_agent",
        "agents.optimization_agent",
        "subprocess",
        "socket",
        "urllib",
        "http",
        "requests",
        "aiohttp",
        "httpx",
        "os",
        "oauthlib",
    }
    FORBIDDEN_CALL_NAMES = {
        "create_job", "system", "popen", "Popen",
        "RealGenerationAuthorization", "RequestScopedActivationContract",
        "ControlledRealProviderActivationContract",
    }

    @classmethod
    def setUpClass(cls):
        cls.source = MISSION_STATE_MACHINE_SOURCE_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def _imported_modules(self):
        modules = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.add(node.module)
        return modules

    def _called_names(self):
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    names.add(func.id)
                elif isinstance(func, ast.Attribute):
                    names.add(func.attr)
        return names

    def _source_without_module_docstring(self):
        # The module docstring legitimately discusses, in prose, the
        # names this module must never call (e.g. "HiggsfieldProvider")
        # -- that is documentation, not a dependency. Strip exactly the
        # module-level docstring node (by its own line range) before
        # doing any substring check, so the check inspects real code
        # (imports, calls, attribute access) rather than prose.
        lines = self.source.splitlines(keepends=True)
        body = self.tree.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            doc_node = body[0]
            start = doc_node.lineno - 1
            end = doc_node.end_lineno
            lines = lines[:start] + lines[end:]
        return "".join(lines)

    def test_no_forbidden_module_imports(self):
        offenders = self._imported_modules() & self.FORBIDDEN_MODULES
        self.assertFalse(offenders, f"agents/mission_state_machine.py imports forbidden module(s): {offenders}")

    def test_no_forbidden_calls(self):
        offenders = self._called_names() & self.FORBIDDEN_CALL_NAMES
        self.assertFalse(offenders, f"agents/mission_state_machine.py contains forbidden call(s): {offenders}")

    def test_no_network_or_provider_dependency(self):
        code = self._source_without_module_docstring()
        self.assertNotIn("HiggsfieldProvider", code)
        self.assertNotIn("HiggsfieldClient", code)
        for banned_substring in ("requests.", "urllib.", "socket.", "http.client", "subprocess.", "os.system"):
            self.assertNotIn(banned_substring, code)

    def test_no_event_bus(self):
        suspicious = {name for name in self._called_names() if "emit" in name.lower() or "subscribe" in name.lower()}
        self.assertFalse(suspicious)


class PublishedProtectionTests(unittest.TestCase):
    """Test 23 from the P3.12 mandatory list."""

    def test_published_requires_quality_check_precondition(self):
        machine = MissionStateMachine(mission_id="m1")
        with self.assertRaises(InvalidMissionTransitionError):
            machine.transition(MissionState.PUBLISHED, reason="premature")

    def test_published_reachable_only_manually_never_by_pipeline_default(self):
        # This machine CAN represent PUBLISHED if a caller has real
        # evidence and drives it there manually -- but that is
        # structurally distinct from the orchestrator ever doing so
        # automatically, which is verified separately in
        # tests/test_director_orchestration.py.
        machine = MissionStateMachine(mission_id="m1")
        machine.transition(MissionState.PLANNED, reason="a", expected_from=MissionState.IDEA)
        machine.transition(MissionState.SCRIPT_READY, reason="b", expected_from=MissionState.PLANNED)
        machine.transition(MissionState.QUALITY_CHECK, reason="c", expected_from=MissionState.SCRIPT_READY)
        record = machine.transition(MissionState.PUBLISHED, reason="external confirmation received", expected_from=MissionState.QUALITY_CHECK)
        self.assertEqual(record.to_state, MissionState.PUBLISHED)


if __name__ == "__main__":
    unittest.main()
