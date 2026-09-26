"""
AI DIRECTOR — Real Mission State Machine (Phase P3.12)

Transforms the conceptual P3.3 Mission State Machine into a real,
controlled, tested software component. Built directly against the real
code re-read in full before writing a single line of this module:
`agents/director_pipeline.py`, `director.py`, `tests/test_director_
orchestration.py`, and all six P3 business agents. Confirmed, again,
what P3.3 already stated and P3.11 restated: no real state machine
existed anywhere before this phase (`StageOutcome`/`DirectorPipelineContext`,
P3.11, are pipeline bookkeeping, never a state machine with a
transition table, illegal-transition detection, or immutable history).

CANONICAL STATES (P3.3 Section 4, used verbatim -- none added, none
removed):

    IDEA -> PLANNED -> SCRIPT_READY -> PROMPT_READY -> ASSETS_READY ->
    VIDEO_READY_FOR_REVIEW -> TECHNICAL_APPROVAL -> HUMAN_AUTHORIZATION ->
    PRODUCTION_AUTHORIZATION -> EXECUTION -> QUALITY_CHECK -> PUBLISHED ->
    ANALYTICS -> OPTIMIZATION

ONE DOCUMENTED ADAPTATION TO REAL CODE (per this phase's own Section 3
instruction: "si un état doit être représenté différemment... documenter
précisément pourquoi") -- stated once, precisely, because it matters:

The REAL P3 business pipeline (P3.6/P3.11) has ContentAgent producing a
complete ScriptArtifact directly -- there is no PromptAgent/AssetAgent/
VideoAgent stage in the real pipeline (P3.11 Section 23: deliberately
left unintegrated, still part of the separate P2 chain). `QualityAgent`
(P3.7) evaluates editorial CONTENT/SCRIPT quality, never a generated
video's quality -- so, in THIS pipeline's honest current meaning,
QUALITY_CHECK is reachable directly from SCRIPT_READY without ever
passing through PROMPT_READY/ASSETS_READY/VIDEO_READY_FOR_REVIEW/
TECHNICAL_APPROVAL/HUMAN_AUTHORIZATION/PRODUCTION_AUTHORIZATION/
EXECUTION -- none of which have any real artifact evidence in this
pipeline today. The full fine-grained chain remains in the transition
table (Section 5 below) as RESERVED, forward-compatible edges for a
future phase that actually integrates those stages -- this module adds
exactly one additional table edge, `SCRIPT_READY -> QUALITY_CHECK`,
clearly marked, rather than silently skipping validation or inventing a
new state.

THE CENTRAL RULE OF THIS MODULE, STATED ONCE (Section 7): STATE != AUTHORITY.
This class never constructs, holds a reference to, or calls:
`RealGenerationAuthorization`, `RequestScopedActivationContract`,
`ControlledRealProviderActivationContract`, `GenerationApprovalGate`,
`GenerationJobService`, `HiggsfieldProvider`, any social/analytics API,
or an Event Bus. A transition to `HUMAN_AUTHORIZATION` records ONLY
that the caller told this machine that state was reached -- it never
verifies, grants, or implies that a real human authorization object
exists anywhere. Verified by tests/test_mission_state_machine.py's
AST-based security suite (docstring-false-positive-safe, per the
lesson already learned across P3.5-P3.11).

AN EMERGENT SAFETY PROPERTY WORTH STATING EXPLICITLY: because
`PUBLISHED` requires `current_state == QUALITY_CHECK` (Section 5's
table) and NOTHING in the real orchestrator integration (P3.12 Section
15, `agents/director_pipeline.py`) ever calls
`transition(MissionState.PUBLISHED, ...)` automatically (P3.12 Section
23: no real publication authority exists to justify it), the mission
state machine, when driven only by today's real orchestrator, PROVABLY
CANNOT advance past `QUALITY_CHECK` -- not merely by convention, but
because the code path that would call `transition(PUBLISHED, ...)`
simply does not exist. This is enforced, not just documented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, FrozenSet, List, Optional, Tuple

# ----------------------------------------------------------------------
# VERSIONING (P3.12 Section 18) -- explicit, no migration infrastructure.
# ----------------------------------------------------------------------

STATE_MACHINE_VERSION = 1


class MissionState(str, Enum):
    IDEA = "IDEA"
    PLANNED = "PLANNED"
    SCRIPT_READY = "SCRIPT_READY"
    PROMPT_READY = "PROMPT_READY"
    ASSETS_READY = "ASSETS_READY"
    VIDEO_READY_FOR_REVIEW = "VIDEO_READY_FOR_REVIEW"
    TECHNICAL_APPROVAL = "TECHNICAL_APPROVAL"
    HUMAN_AUTHORIZATION = "HUMAN_AUTHORIZATION"
    PRODUCTION_AUTHORIZATION = "PRODUCTION_AUTHORIZATION"
    EXECUTION = "EXECUTION"
    QUALITY_CHECK = "QUALITY_CHECK"
    PUBLISHED = "PUBLISHED"
    ANALYTICS = "ANALYTICS"
    OPTIMIZATION = "OPTIMIZATION"


# ----------------------------------------------------------------------
# TRANSITION TABLE (P3.12 Section 5) -- the FULL conceptual P3.3 chain,
# PLUS the one documented adaptation above (SCRIPT_READY -> QUALITY_CHECK).
# Every edge not listed here is illegal by construction (fails closed):
# IDEA -> EXECUTION, IDEA -> PUBLISHED, QUALITY_CHECK -> EXECUTION,
# OPTIMIZATION -> EXECUTION, ANALYTICS -> PUBLISHED, and every other
# unlisted pair, all correctly rejected because they are simply absent
# from this table -- never because of a special-cased blacklist.
# ----------------------------------------------------------------------

ALLOWED_TRANSITIONS: Dict[MissionState, FrozenSet[MissionState]] = {
    MissionState.IDEA: frozenset({MissionState.PLANNED}),
    MissionState.PLANNED: frozenset({MissionState.SCRIPT_READY}),
    MissionState.SCRIPT_READY: frozenset(
        {
            MissionState.PROMPT_READY,  # reserved -- no real code path uses this today
            MissionState.QUALITY_CHECK,  # the one documented adaptation (see module docstring)
        }
    ),
    MissionState.PROMPT_READY: frozenset({MissionState.ASSETS_READY}),  # reserved
    MissionState.ASSETS_READY: frozenset({MissionState.VIDEO_READY_FOR_REVIEW}),  # reserved
    MissionState.VIDEO_READY_FOR_REVIEW: frozenset({MissionState.TECHNICAL_APPROVAL}),  # reserved
    MissionState.TECHNICAL_APPROVAL: frozenset({MissionState.HUMAN_AUTHORIZATION}),  # reserved
    MissionState.HUMAN_AUTHORIZATION: frozenset({MissionState.PRODUCTION_AUTHORIZATION}),  # reserved
    MissionState.PRODUCTION_AUTHORIZATION: frozenset({MissionState.EXECUTION}),  # reserved
    MissionState.EXECUTION: frozenset({MissionState.QUALITY_CHECK}),  # reserved
    MissionState.QUALITY_CHECK: frozenset({MissionState.PUBLISHED}),
    MissionState.PUBLISHED: frozenset({MissionState.ANALYTICS}),
    MissionState.ANALYTICS: frozenset({MissionState.OPTIMIZATION}),
    MissionState.OPTIMIZATION: frozenset(),  # terminal
}


# ----------------------------------------------------------------------
# ERRORS (P3.12 Section 6/19/20) -- explicit, typed, never silently
# "corrected".
# ----------------------------------------------------------------------


class InvalidMissionTransitionError(RuntimeError):
    """Raised when `to_state` is not a member of
    `ALLOWED_TRANSITIONS[current_state]`. Never auto-corrected to the
    "closest legal" state."""

    def __init__(self, mission_id: str, from_state: MissionState, to_state: MissionState):
        super().__init__(
            f"Mission '{mission_id}': transition {from_state.value} -> "
            f"{to_state.value} is not allowed."
        )
        self.mission_id = mission_id
        self.from_state = from_state
        self.to_state = to_state


class StateConflictError(RuntimeError):
    """
    Raised when the caller's `expected_from` does not match the
    machine's actual `current_state` -- the minimal, lock-free
    stale-state protection P3.12 Section 20 asks for. Real inter-process
    concurrency protection (a TOCTOU-safe lock, analogous to P2.20's
    `FileCriticalSectionLock`) remains explicitly a FUTURE responsibility,
    never claimed here.
    """

    def __init__(self, mission_id: str, expected_from: MissionState, actual_current: MissionState):
        super().__init__(
            f"Mission '{mission_id}': expected current state "
            f"{expected_from.value}, but it is actually "
            f"{actual_current.value} -- refusing a transition based on "
            f"stale state."
        )
        self.mission_id = mission_id
        self.expected_from = expected_from
        self.actual_current = actual_current


class DuplicateTransitionError(RuntimeError):
    """
    Raised only when a REUSED `idempotency_key` requests a DIFFERENT
    `to_state` than the one already recorded for that key -- a genuinely
    inconsistent replay, never masked. Reusing the same key for the SAME
    `to_state` is instead an idempotent no-op (Section 19's other
    explicitly offered option) -- see `MissionStateMachine.transition()`.
    """

    def __init__(self, mission_id: str, idempotency_key: str, recorded_to: MissionState, requested_to: MissionState):
        super().__init__(
            f"Mission '{mission_id}': idempotency_key '{idempotency_key}' "
            f"was already used for a transition to {recorded_to.value}, "
            f"but this call requests {requested_to.value} -- refusing an "
            f"inconsistent replay."
        )
        self.mission_id = mission_id
        self.idempotency_key = idempotency_key
        self.recorded_to = recorded_to
        self.requested_to = requested_to


# ----------------------------------------------------------------------
# IMMUTABLE TRANSITION RECORD (P3.12 Section 15/17)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class MissionStateTransition:
    mission_id: str
    from_state: MissionState
    to_state: MissionState
    reason: str
    timestamp: str
    transition_index: int


# Injectable clock (P3.12 Section 17) -- never `datetime.now()` called
# directly inside transition logic; the default below is the ONLY place
# real wall-clock time is read, and only as a replaceable default.
Clock = Callable[[], str]


def _default_clock() -> str:
    return datetime.now(timezone.utc).isoformat()


# ----------------------------------------------------------------------
# MISSION STATE MACHINE (P3.12 Section 4)
# ----------------------------------------------------------------------


class MissionStateMachine:
    """
    One instance per mission (Section 16: `mission_id` is required at
    construction, never a global). Holds its own private, append-only
    history -- `history` returns a tuple copy; external code cannot
    append to it directly (Section 15/21).
    """

    def __init__(
        self,
        mission_id: str,
        initial_state: MissionState = MissionState.IDEA,
        clock: Optional[Clock] = None,
    ):
        if not isinstance(mission_id, str) or not mission_id.strip():
            raise ValueError("MissionStateMachine requires a non-empty mission_id.")

        self._mission_id = mission_id
        self._current_state = initial_state
        self._clock = clock or _default_clock
        self._history: List[MissionStateTransition] = []
        self._idempotency_seen: Dict[str, MissionStateTransition] = {}

    @property
    def mission_id(self) -> str:
        return self._mission_id

    @property
    def current_state(self) -> MissionState:
        return self._current_state

    @property
    def history(self) -> Tuple[MissionStateTransition, ...]:
        return tuple(self._history)

    @property
    def transition_count(self) -> int:
        return len(self._history)

    def can_transition(self, to_state: MissionState) -> bool:
        """PURE, read-only -- never mutates state, never records
        anything. Safe to call speculatively at any time."""

        return to_state in ALLOWED_TRANSITIONS.get(self._current_state, frozenset())

    def transition(
        self,
        to_state: MissionState,
        reason: str,
        expected_from: Optional[MissionState] = None,
        idempotency_key: Optional[str] = None,
    ) -> MissionStateTransition:
        """
        Order of checks (Section 19/20/6, all fail-closed):
        1. idempotency_key already seen -> return the existing record if
           `to_state` matches (no-op), else DuplicateTransitionError.
        2. `expected_from` provided and does not match `current_state`
           -> StateConflictError (stale-state protection).
        3. `to_state` not in `ALLOWED_TRANSITIONS[current_state]` ->
           InvalidMissionTransitionError.
        Only then is a new, immutable `MissionStateTransition` appended
        to history and `current_state` advanced.
        """

        if idempotency_key is not None and idempotency_key in self._idempotency_seen:
            existing = self._idempotency_seen[idempotency_key]
            if existing.to_state == to_state:
                return existing
            raise DuplicateTransitionError(self._mission_id, idempotency_key, existing.to_state, to_state)

        if expected_from is not None and expected_from != self._current_state:
            raise StateConflictError(self._mission_id, expected_from, self._current_state)

        if not self.can_transition(to_state):
            raise InvalidMissionTransitionError(self._mission_id, self._current_state, to_state)

        record = MissionStateTransition(
            mission_id=self._mission_id,
            from_state=self._current_state,
            to_state=to_state,
            reason=reason,
            timestamp=self._clock(),
            transition_index=len(self._history) + 1,
        )
        self._history.append(record)
        self._current_state = to_state

        if idempotency_key is not None:
            self._idempotency_seen[idempotency_key] = record

        return record
