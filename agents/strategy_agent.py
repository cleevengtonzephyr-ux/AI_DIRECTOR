"""
AI DIRECTOR — Strategy Agent v1.0 (Phase P3.5)

First business agent of the future multi-agent AI Director, built against
the conceptual contracts defined in P3.1 (DirectorMission/Artifact Model),
P3.2 (Agent Interfaces/AgentContract/AgentContext) and P3.3 (Mission State
Machine) -- none of which produced runnable code themselves. This module
is the first controlled implementation and deliberately narrow in scope.

RESPONSIBILITY (P3.2 Section 5, restated here as code):
Transforms a raw mission intent (objective/topic/audience/platforms/
priority/constraints) into a structured, immutable StrategyArtifact.
Nothing more.

WHAT THIS MODULE DELIBERATELY DOES NOT DO, BY CONSTRUCTION (not merely by
convention -- see tests/test_strategy_agent.py::SecurityTests, which
statically parses this file's AST to enforce it):
- Does not import HiggsfieldClient, HiggsfieldProvider, or anything under
  integrations/higgsfield/.
- Does not import GenerationApprovalGate, RequestScopedActivationService,
  ControlledRealProviderActivationService, or any other P2 gate/authority
  module.
- Does not import director.py (no mission-state mutation authority).
- Does not import subprocess, socket, urllib, http, or any networking
  primitive.
- Never constructs a RealGenerationAuthorization or any activation
  contract.
- Never calls an event bus (none exists in this codebase -- P3.4 was
  architecture only) -- it returns a plain StrategyAgentOutput to its
  caller and nothing else.
- Never mutates DirectorMission.current_state (no such class exists in
  code yet -- P3.1/P3.3 were architecture only); a future Director/state
  machine implementation is the only thing ever entitled to decide
  IDEA -> PLANNED.

DETERMINISM (P3.5 Section 7):
No `random`, no randomly-seeded UUID content, no LLM call, no web/API
call, no cached/external data feeds the *content* of a StrategyArtifact.
The only technical (non-content) source of variance permitted is
`created_at` (wall-clock timestamp) and `artifact_id` (a technical
identifier, generated via `uuid.uuid4()`, which never influences the
artifact's `content_hash` -- see `compute_content_hash()`).

AUTHORITY (P3.2 Section 14 / P3.3 Section 3): PLAN. This agent may
produce a StrategyArtifact and recommend a structure. It cannot approve
a generation, authorize spend, authorize production, call a provider, or
publish -- none of those capabilities exist anywhere in this module.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Tuple

# ----------------------------------------------------------------------
# VERSIONING (P3.5 Section 16) -- explicit, independent axes. A future
# version bump of any one of these must never silently invalidate an
# artifact produced under an earlier version (P3.1 Section 19/P3.2
# Section 19: producer_agent + producer_version + contract_version are
# stamped on every artifact so a consumer can tell exactly which rules
# produced it).
# ----------------------------------------------------------------------

AGENT_ID = "strategy-agent"
AGENT_VERSION = "1.0"
CONTRACT_VERSION = 1
ARTIFACT_TYPE = "StrategyArtifact"
ARTIFACT_VERSION = 1

# ----------------------------------------------------------------------
# VALIDATION WHITELISTS -- deliberately small, explicit, closed sets.
# An input value outside these sets is a VALIDATION error, never
# silently coerced/lowercased/guessed (P3.5 Section 8).
# ----------------------------------------------------------------------

ALLOWED_PLATFORMS = frozenset(
    {"tiktok", "youtube", "instagram", "facebook", "x", "linkedin"}
)
ALLOWED_PRIORITIES = frozenset({"LOW", "NORMAL", "HIGH", "URGENT"})
ALLOWED_LANGUAGES = frozenset({"en", "fr", "es", "de", "pt", "it"})

DEFAULT_PRIORITY = "NORMAL"
DEFAULT_LANGUAGE = "en"


class StrategyAgentStatus(str, Enum):
    """
    Minimal status vocabulary (P3.5 Section 9) -- deliberately NOT a
    second mission-state machine. This describes only the outcome of
    ONE call to StrategyAgent.run(), never DirectorMission.current_state
    (which this agent has no authority to read or write, P3.5 Section
    10/11).
    """

    READY = "READY"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    # Reserved for a future business-rule rejection layer (e.g. a
    # strategy engine that can refuse an otherwise well-formed input on
    # domain grounds). Never produced by DeterministicStrategyEngine
    # (P3.5 V1 has no such business-rule layer) -- kept in the
    # vocabulary now so a future engine does not need a second enum.
    REJECTED = "REJECTED"


# ----------------------------------------------------------------------
# INPUT CONTRACT (P3.5 Section 4)
#
# Field classification (explicit, per instruction not to silently
# invent a missing critical value):
#   REQUIRED, no default   -> mission_id, objective, platforms
#   OPTIONAL, never invented, surfaced via a warning if absent
#                           -> topic, audience
#   OPTIONAL, safely defaultable (non-critical, purely presentational
#   or sequencing concerns) -> language (default "en"), priority
#                              (default "NORMAL"), constraints
#                              (default empty tuple)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class StrategyAgentInput:
    mission_id: str
    objective: str
    platforms: Tuple[str, ...]
    topic: Optional[str] = None
    audience: Optional[str] = None
    language: str = DEFAULT_LANGUAGE
    priority: str = DEFAULT_PRIORITY
    constraints: Tuple[str, ...] = field(default_factory=tuple)


# ----------------------------------------------------------------------
# STRATEGY ARTIFACT (P3.5 Section 6) -- immutable (frozen dataclass, no
# setter, no mutation method anywhere in this module). A correction is
# always a NEW artifact (new artifact_id, new created_at), never an
# in-place edit -- consistent with the immutability rule already
# enforced throughout the P2 stack for hashes/contracts.
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class StrategyArtifact:
    artifact_id: str
    artifact_type: str
    mission_id: str
    created_at: str
    version: int
    status: str  # Artifact lifecycle status (DRAFT|FINAL|SUPERSEDED) --
    # NOT StrategyAgentStatus. This module only ever produces "FINAL"
    # artifacts (no draft workflow exists yet); kept as a plain str
    # field rather than a second enum to avoid inventing an unused
    # DRAFT/SUPERSEDED code path this phase never exercises.

    objective: str
    audience: Optional[str]
    platforms: Tuple[str, ...]
    content_goals: Tuple[str, ...]
    strategic_angles: Tuple[str, ...]
    priorities: Tuple[str, ...]
    constraints: Tuple[str, ...]

    producer_agent: str
    producer_version: str
    contract_version: int

    content_hash: str


# ----------------------------------------------------------------------
# OUTPUT CONTRACT (P3.5 Section 5)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class StrategyAgentOutput:
    mission_id: str
    status: StrategyAgentStatus
    strategy_artifact: Optional[StrategyArtifact] = None
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    errors: Tuple[str, ...] = field(default_factory=tuple)
    producer_agent: str = AGENT_ID
    producer_version: str = AGENT_VERSION
    contract_version: int = CONTRACT_VERSION


# ----------------------------------------------------------------------
# STRATEGY ENGINE INTERFACE (P3.5 Section 19) -- allows a future
# LLMStrategyEngine/HumanStrategyEngine to be substituted behind the
# exact same contract, without StrategyAgent itself changing. No engine
# implementation, present or future, gains any authority beyond PLAN by
# virtue of being "smarter" -- StrategyAgent (not the engine) is the
# only thing that assembles the final StrategyArtifact and stamps
# producer_agent/producer_version/contract_version.
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class StrategyContent:
    """Pure content payload an engine produces; StrategyAgent wraps this
    into a full StrategyArtifact with identity/versioning/hash fields."""

    content_goals: Tuple[str, ...]
    strategic_angles: Tuple[str, ...]
    priorities: Tuple[str, ...]
    warnings: Tuple[str, ...] = field(default_factory=tuple)


class StrategyEngine(ABC):
    """Contract every strategy backend (deterministic, LLM, human-in-
    the-loop) must satisfy. Never called with an unvalidated input --
    StrategyAgent.run() validates first and only calls the engine on
    success."""

    @abstractmethod
    def build_content(self, agent_input: StrategyAgentInput) -> StrategyContent:
        raise NotImplementedError


class DeterministicStrategyEngine(StrategyEngine):
    """
    V1 default engine (P3.5 Section 18): purely local, template-based,
    deterministic. No random, no LLM, no network, no external data.
    Same input (module `constraints`/`platforms` order included) always
    produces the same StrategyContent.
    """

    def build_content(self, agent_input: StrategyAgentInput) -> StrategyContent:
        warnings: List[str] = []

        if agent_input.audience is None or not agent_input.audience.strip():
            warnings.append(
                "audience not specified; strategic angles will be generic "
                "rather than audience-targeted."
            )

        if agent_input.topic is not None and agent_input.topic.strip():
            topic_label = agent_input.topic.strip()
        else:
            warnings.append(
                "topic not specified; falling back to the objective text "
                "for angle generation."
            )
            topic_label = agent_input.objective.strip()

        content_goals: Tuple[str, ...] = tuple(
            [f"Deliver on stated objective: {agent_input.objective.strip()}"]
            + [
                f"Optimize content for platform '{platform}'"
                for platform in agent_input.platforms
            ]
        )

        strategic_angles: Tuple[str, ...] = (
            f"Educational angle on: {topic_label}",
            f"Narrative/emotional angle on: {topic_label}",
            f"Direct value-proposition angle on: {topic_label}",
        )

        # `priorities`: mission-level priority first, then platforms in
        # the exact order supplied (their order IS their rollout
        # priority -- never re-sorted, never guessed).
        priorities: Tuple[str, ...] = (
            f"mission_priority:{agent_input.priority}",
        ) + tuple(
            f"platform_priority:{platform}" for platform in agent_input.platforms
        )

        return StrategyContent(
            content_goals=content_goals,
            strategic_angles=strategic_angles,
            priorities=priorities,
            warnings=tuple(warnings),
        )


# ----------------------------------------------------------------------
# VALIDATION (P3.5 Section 8) -- returns a list of human-readable
# reason strings, following the exact convention already established by
# GenerationApprovalGate._validate() / ReleaseCandidateIdentityLock.
# violations() elsewhere in this codebase: an empty list means valid,
# any non-empty list is a VALIDATION-category failure. This module does
# not invent a new AgentError class hierarchy (P3.5 Section 14): P3.2's
# AgentError was conceptual only, never implemented as code, so there is
# nothing real to reuse, and inventing an unused hierarchy here would
# violate the "do not build a global error framework prematurely" rule.
# ----------------------------------------------------------------------


def _validate(agent_input: StrategyAgentInput) -> List[str]:
    errors: List[str] = []

    if not isinstance(agent_input.mission_id, str) or not agent_input.mission_id.strip():
        errors.append("mission_id is missing or empty.")

    if not isinstance(agent_input.objective, str) or not agent_input.objective.strip():
        errors.append("objective is missing or empty.")

    if not isinstance(agent_input.platforms, tuple) or not agent_input.platforms:
        errors.append("platforms is missing or empty; at least one platform is required.")
    else:
        for platform in agent_input.platforms:
            if platform not in ALLOWED_PLATFORMS:
                errors.append(
                    f"platform '{platform}' is not supported "
                    f"(allowed: {sorted(ALLOWED_PLATFORMS)})."
                )

    if agent_input.priority not in ALLOWED_PRIORITIES:
        errors.append(
            f"priority '{agent_input.priority}' is invalid "
            f"(allowed: {sorted(ALLOWED_PRIORITIES)})."
        )

    if agent_input.language not in ALLOWED_LANGUAGES:
        errors.append(
            f"language '{agent_input.language}' is invalid "
            f"(allowed: {sorted(ALLOWED_LANGUAGES)})."
        )

    return errors


# ----------------------------------------------------------------------
# HASH / INTEGRITY (P3.5 Section 17) -- deterministic, stable, computed
# from a canonical representation. Excludes artifact_id/created_at
# (technical/temporal fields that never affect content, P3.5 Section 7)
# and excludes `warnings` (advisory metadata, not strategic content).
# ----------------------------------------------------------------------


def compute_content_hash(
    mission_id: str,
    objective: str,
    audience: Optional[str],
    platforms: Tuple[str, ...],
    content_goals: Tuple[str, ...],
    strategic_angles: Tuple[str, ...],
    priorities: Tuple[str, ...],
    constraints: Tuple[str, ...],
    contract_version: int,
) -> str:
    canonical = {
        "mission_id": mission_id,
        "objective": objective,
        "audience": audience,
        "platforms": list(platforms),
        "content_goals": list(content_goals),
        "strategic_angles": list(strategic_angles),
        "priorities": list(priorities),
        "constraints": list(constraints),
        "contract_version": contract_version,
    }
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# IDEMPOTENCY (P3.5 Section 15) -- pure function, no store, no
# persistence, no database. A future phase may use this key to detect
# "same mission_id + same strategic input already produced an
# equivalent strategy" without this module ever needing to know how or
# where that detection is implemented.
# ----------------------------------------------------------------------


def compute_strategy_idempotency_key(agent_input: StrategyAgentInput) -> str:
    canonical = {
        "mission_id": agent_input.mission_id,
        "objective": agent_input.objective,
        "topic": agent_input.topic,
        "audience": agent_input.audience,
        "platforms": list(agent_input.platforms),
        "language": agent_input.language,
        "priority": agent_input.priority,
        "constraints": list(agent_input.constraints),
    }
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# STRATEGY AGENT (P3.5 Section 3)
# ----------------------------------------------------------------------


class StrategyAgent:
    """
    AI DIRECTOR — Strategy Agent v1.0 (P3.5)

    Zero dependency on Higgsfield, any P2 gate/authority module, the
    Director, or any event bus (P3.5 Section 13). The only dependency is
    an injected StrategyEngine (default: DeterministicStrategyEngine),
    which is itself dependency-free.
    """

    def __init__(self, engine: Optional[StrategyEngine] = None):
        self.engine = engine or DeterministicStrategyEngine()

    def run(self, agent_input: StrategyAgentInput) -> StrategyAgentOutput:
        """
        Validates `agent_input`; on failure returns a VALIDATION_ERROR
        output with no artifact (never a partially-built one). On
        success, delegates content generation to `self.engine` and
        assembles an immutable StrategyArtifact.

        Never mutates any mission state, never emits an event, never
        constructs any authority object -- none of those capabilities
        exist in this class.
        """

        errors = _validate(agent_input)

        mission_id = agent_input.mission_id if isinstance(agent_input.mission_id, str) else ""

        if errors:
            return StrategyAgentOutput(
                mission_id=mission_id,
                status=StrategyAgentStatus.VALIDATION_ERROR,
                errors=tuple(errors),
            )

        content = self.engine.build_content(agent_input)

        artifact_id = uuid.uuid4().hex  # Technical identity only -- never fed into content_hash.
        created_at = datetime.now(timezone.utc).isoformat()

        content_hash = compute_content_hash(
            mission_id=agent_input.mission_id,
            objective=agent_input.objective,
            audience=agent_input.audience,
            platforms=agent_input.platforms,
            content_goals=content.content_goals,
            strategic_angles=content.strategic_angles,
            priorities=content.priorities,
            constraints=agent_input.constraints,
            contract_version=CONTRACT_VERSION,
        )

        artifact = StrategyArtifact(
            artifact_id=artifact_id,
            artifact_type=ARTIFACT_TYPE,
            mission_id=agent_input.mission_id,
            created_at=created_at,
            version=ARTIFACT_VERSION,
            status="FINAL",
            objective=agent_input.objective,
            audience=agent_input.audience,
            platforms=agent_input.platforms,
            content_goals=content.content_goals,
            strategic_angles=content.strategic_angles,
            priorities=content.priorities,
            constraints=agent_input.constraints,
            producer_agent=AGENT_ID,
            producer_version=AGENT_VERSION,
            contract_version=CONTRACT_VERSION,
            content_hash=content_hash,
        )

        return StrategyAgentOutput(
            mission_id=agent_input.mission_id,
            status=StrategyAgentStatus.READY,
            strategy_artifact=artifact,
            warnings=content.warnings,
        )
