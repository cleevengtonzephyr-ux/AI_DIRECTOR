"""
AI DIRECTOR — Content Agent v1.0 (Phase P3.6)

Second business agent of the future multi-agent AI Director, built
directly against the REAL `agents/strategy_agent.py` (P3.5) contracts --
`StrategyArtifact`, `StrategyAgentStatus`, `ARTIFACT_TYPE`,
`CONTRACT_VERSION`, `ALLOWED_PLATFORMS`, `ALLOWED_LANGUAGES`,
`DEFAULT_LANGUAGE`, `compute_content_hash` -- none of which are
re-invented here. This module is additive: it does not modify
`agents/strategy_agent.py`, `agents/planner.py`, `agents/task_manager.py`,
`agents/video_agent.py`, or `director.py`.

AUDIT FINDING CARRIED FORWARD FROM P3.5 (read in full before writing this
module, per instruction not to assume a contract that doesn't exist):
`StrategyArtifact` (agents/strategy_agent.py) has NO `language` field --
only `StrategyAgentInput` validates a `language`, and it is never
propagated onto the artifact. The mission brief for this phase assumed a
`StrategyArtifact.language` fallback would exist; it does not. This
module therefore resolves language as: (1) an explicit, validated
`language_override` on `ContentAgentInput`, or (2) a documented,
non-critical default (`DEFAULT_CONTENT_LANGUAGE`), ALWAYS accompanied by
an explicit warning when defaulted -- never silently presented as
something the strategy dictated.

RESPONSIBILITY (P3.6 Section 4):
StrategyArtifact -> ContentArtifact + ScriptArtifact. Nothing more. Does
not prepare assets, assemble the final generation prompt, generate video,
call Higgsfield, publish, analyze real performance, apply an
optimization, create a human authorization, create an activation
contract, or mutate any mission state -- none of these capabilities
exist anywhere in this module (see tests/test_content_agent.py::
SecurityTests, which statically parses this file's AST to enforce it,
exactly as P3.5 did for StrategyAgent).

AUTHORITY: PLAN / TRANSFORM (P3.2 Section 14 / P3.6 Section 5). Cannot
grant TECHNICAL_APPROVAL, HUMAN_AUTHORIZATION, PRODUCTION_AUTHORIZATION,
EXECUTION, or PUBLICATION.

DETERMINISM: identical to P3.5's discipline -- no `random`, no LLM call,
no network/web call, no cached external data feeds content. Only
`created_at` and the two artifacts' `artifact_id`s (technical, never fed
into any content_hash) are permitted to vary between calls with the same
input.
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

from agents.strategy_agent import (
    ALLOWED_LANGUAGES as STRATEGY_ALLOWED_LANGUAGES,
    ALLOWED_PLATFORMS as STRATEGY_ALLOWED_PLATFORMS,
    ARTIFACT_TYPE as STRATEGY_ARTIFACT_TYPE,
    CONTRACT_VERSION as STRATEGY_CONTRACT_VERSION,
    DEFAULT_LANGUAGE as DEFAULT_CONTENT_LANGUAGE,
    StrategyArtifact,
    compute_content_hash as compute_strategy_content_hash,
)

# ----------------------------------------------------------------------
# VERSIONING (P3.6 Section 21) -- independent from StrategyAgent's own
# versioning constants, imported above only where this module genuinely
# depends on StrategyAgent's contract shape (SUPPORTED_STRATEGY_
# CONTRACT_VERSIONS below).
# ----------------------------------------------------------------------

AGENT_ID = "content-agent"
AGENT_VERSION = "1.0"
CONTRACT_VERSION = 1
CONTENT_ARTIFACT_TYPE = "ContentArtifact"
SCRIPT_ARTIFACT_TYPE = "ScriptArtifact"
ARTIFACT_VERSION = 1

# This ContentAgent version only knows how to interpret a StrategyArtifact
# produced under this exact contract_version. An incompatible future
# StrategyArtifact contract_version is REJECTED (DEPENDENCY), never
# guess-parsed (P3.1 Section 19 / P3.4 Section 16 versioning discipline).
SUPPORTED_STRATEGY_CONTRACT_VERSIONS = frozenset({STRATEGY_CONTRACT_VERSION})

# ----------------------------------------------------------------------
# VALIDATION WHITELISTS -- deliberately small. Platforms/languages reuse
# StrategyAgent's own whitelists verbatim (imported above) rather than a
# second, potentially divergent list -- a risk explicitly flagged in the
# P3.5 report (Section 22, risk #2) and avoided here by construction.
# ----------------------------------------------------------------------

ALLOWED_TONES = frozenset(
    {"professional", "dramatic", "educational", "cinematic", "conversational"}
)
DEFAULT_TONE = "conversational"

ALLOWED_FORMATS = frozenset({"short_video", "long_video", "social_post", "educational"})
DEFAULT_FORMAT = "short_video"

# Non-critical scaffold default (P3.6 Section 18) -- never presented as a
# user requirement; always accompanied by an explicit warning when used.
DEFAULT_TOTAL_DURATION_TARGET_SECONDS = 30

# Fixed, documented three-scene structure for V1 (Hook / Body / CTA).
# Weights sum to 1.0 by construction; a future engine could return a
# different scene count without changing this module's contract.
HOOK_WEIGHT = 0.2
BODY_WEIGHT = 0.6
CTA_WEIGHT = 0.2


class ContentAgentStatus(str, Enum):
    """
    Deliberately mirrors StrategyAgentStatus's vocabulary (P3.5 Section 9)
    for cross-agent consistency, without importing that enum -- each
    agent module stays self-contained (P3.2's low-coupling principle).
    """

    READY = "READY"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    # DEPENDENCY-category failures against the supplied StrategyArtifact
    # (missing, wrong mission, wrong shape, tampered) are reported as
    # REJECTED -- never conflated with this agent's OWN input validation
    # (VALIDATION_ERROR), per P3.6 Section 23's explicit category split.
    REJECTED = "REJECTED"


# ----------------------------------------------------------------------
# INPUT CONTRACT (P3.6 Section 6)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ContentAgentInput:
    mission_id: str
    strategy_artifact: StrategyArtifact  # REQUIRED -- no default. A
    # ContentAgent cannot be asked to produce content without a concrete
    # StrategyArtifact object (P3.6 Section 6's explicit requirement);
    # Python's type system does not forbid passing None here, so
    # `_validate_strategy_dependency()` re-checks this at runtime.
    language_override: Optional[str] = None
    tone: Optional[str] = None
    content_format: Optional[str] = None  # named to avoid shadowing the
    # `format()` builtin; maps directly to the mission's "format" concept.
    platform_override: Optional[Tuple[str, ...]] = None
    duration_target_seconds: Optional[int] = None
    constraints: Tuple[str, ...] = field(default_factory=tuple)


# ----------------------------------------------------------------------
# SCENE / SCRIPT ARTIFACT (P3.6 Section 10)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Scene:
    scene_id: str
    order: int
    duration: int
    narration: str
    visual_direction: str
    transition: Optional[str]
    notes: str = ""


@dataclass(frozen=True)
class ScriptArtifact:
    artifact_id: str
    artifact_type: str
    mission_id: str
    created_at: str
    version: int
    status: str  # Artifact lifecycle status (DRAFT|FINAL|SUPERSEDED),
    # distinct from ContentAgentStatus -- same discipline as P3.5's
    # StrategyArtifact.status vs StrategyAgentStatus.

    scenes: Tuple[Scene, ...]
    total_duration_target: int
    language: str

    producer_agent: str
    producer_version: str
    contract_version: int

    source_content_artifact_id: str
    dependencies: Tuple[str, ...]

    content_hash: str


# ----------------------------------------------------------------------
# CONTENT ARTIFACT (P3.6 Section 9)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ContentArtifact:
    artifact_id: str
    artifact_type: str
    mission_id: str
    created_at: str
    version: int
    status: str

    concept: str
    angle: str
    hook: str
    title: str
    cta: str
    target_platforms: Tuple[str, ...]
    language: str
    tone: str
    content_format: str
    constraints: Tuple[str, ...]

    producer_agent: str
    producer_version: str
    contract_version: int

    source_strategy_artifact_id: str
    source_strategy_content_hash: str
    dependencies: Tuple[str, ...]

    content_hash: str


# ----------------------------------------------------------------------
# OUTPUT CONTRACT (P3.6 Section 8)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ContentAgentOutput:
    mission_id: str
    status: ContentAgentStatus
    content_artifact: Optional[ContentArtifact] = None
    script_artifact: Optional[ScriptArtifact] = None
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    errors: Tuple[str, ...] = field(default_factory=tuple)
    producer_agent: str = AGENT_ID
    producer_version: str = AGENT_VERSION
    contract_version: int = CONTRACT_VERSION


# ----------------------------------------------------------------------
# CONTENT ENGINE (P3.6 Sections 11/12) -- ContentAgent = validation and
# orchestration; ContentEngine = content generation. Swappable without
# changing ContentAgent's own contract, exactly mirroring StrategyEngine/
# DeterministicStrategyEngine from P3.5.
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ContentGenerationContext:
    """Everything an engine needs, already resolved (overrides applied,
    defaults filled) by ContentAgent -- an engine never sees a raw,
    unresolved ContentAgentInput."""

    strategy_artifact: StrategyArtifact
    language: str
    tone: str
    content_format: str
    platforms: Tuple[str, ...]
    constraints: Tuple[str, ...]


@dataclass(frozen=True)
class SceneDraft:
    """Pure content payload for one scene; ContentAgent (not the engine)
    assigns scene_id/order/duration -- those are orchestration concerns,
    not content."""

    narration: str
    visual_direction: str
    transition: Optional[str]
    notes: str
    weight: float


@dataclass(frozen=True)
class ContentGenerationResult:
    concept: str
    angle: str
    hook: str
    title: str
    cta: str
    scene_drafts: Tuple[SceneDraft, ...]
    warnings: Tuple[str, ...] = field(default_factory=tuple)


class ContentEngine(ABC):
    """Contract every content backend (deterministic, LLM, human-in-the-
    loop) must satisfy. Never called with an unvalidated/unresolved
    input -- ContentAgent.run() validates and resolves first."""

    @abstractmethod
    def build_content(self, context: ContentGenerationContext) -> ContentGenerationResult:
        raise NotImplementedError


class DeterministicContentEngine(ContentEngine):
    """
    V1 default engine: purely local, template-based, deterministic. No
    random, no LLM, no network, no external data. Same
    ContentGenerationContext always produces the same
    ContentGenerationResult.
    """

    def build_content(self, context: ContentGenerationContext) -> ContentGenerationResult:
        warnings: List[str] = []
        objective = context.strategy_artifact.objective.strip()

        angles = context.strategy_artifact.strategic_angles
        if angles:
            angle = angles[0]
        else:
            warnings.append(
                "strategy_artifact.strategic_angles was empty; using a "
                "generic angle derived from the objective instead."
            )
            angle = f"General angle on: {objective}"

        concept = f"A {context.tone} {context.content_format} built around: {objective}"
        hook = f"Here's why {objective.rstrip('.')} matters."
        title = objective[:80]

        cta = (
            f"If this resonated, follow for more on "
            f"{', '.join(context.platforms)}."
        )

        content_goals = context.strategy_artifact.content_goals
        if content_goals:
            body_narration = " ".join(content_goals)
        else:
            warnings.append(
                "strategy_artifact.content_goals was empty; using the "
                "objective directly as body narration instead."
            )
            body_narration = f"Explore: {objective}"

        scene_drafts: Tuple[SceneDraft, ...] = (
            SceneDraft(
                narration=hook,
                visual_direction=(
                    f"Open on a strong visual hook aligned with angle: {angle}"
                ),
                transition="cut",
                notes="",
                weight=HOOK_WEIGHT,
            ),
            SceneDraft(
                narration=body_narration,
                visual_direction=f"Develop the concept: {concept}",
                transition="cut",
                notes="",
                weight=BODY_WEIGHT,
            ),
            SceneDraft(
                narration=cta,
                visual_direction="Close on a branded call-to-action visual.",
                transition=None,
                notes="",
                weight=CTA_WEIGHT,
            ),
        )

        return ContentGenerationResult(
            concept=concept,
            angle=angle,
            hook=hook,
            title=title,
            cta=cta,
            scene_drafts=scene_drafts,
            warnings=tuple(warnings),
        )


# ----------------------------------------------------------------------
# VALIDATION (P3.6 Sections 7/23) -- two structurally separate checks,
# never merged: dependency validity (the supplied StrategyArtifact
# itself) vs. this agent's own input validity.
# ----------------------------------------------------------------------


def _validate_strategy_dependency(agent_input: ContentAgentInput) -> List[str]:
    errors: List[str] = []
    strategy_artifact = agent_input.strategy_artifact

    if strategy_artifact is None:
        errors.append(
            "strategy_artifact is missing; ContentAgent cannot run "
            "without a valid StrategyArtifact."
        )
        return errors

    if not isinstance(strategy_artifact, StrategyArtifact):
        errors.append("strategy_artifact is not a valid StrategyArtifact instance.")
        return errors

    if strategy_artifact.artifact_type != STRATEGY_ARTIFACT_TYPE:
        errors.append(
            f"strategy_artifact.artifact_type '{strategy_artifact.artifact_type}' "
            f"is not '{STRATEGY_ARTIFACT_TYPE}'."
        )

    if strategy_artifact.mission_id != agent_input.mission_id:
        errors.append(
            f"strategy_artifact.mission_id '{strategy_artifact.mission_id}' does "
            f"not match this ContentAgentInput.mission_id "
            f"'{agent_input.mission_id}' -- refusing to consume a "
            f"StrategyArtifact belonging to a different mission."
        )

    if strategy_artifact.status != "FINAL":
        errors.append(
            f"strategy_artifact.status '{strategy_artifact.status}' is not "
            f"'FINAL'."
        )

    if strategy_artifact.contract_version not in SUPPORTED_STRATEGY_CONTRACT_VERSIONS:
        errors.append(
            f"strategy_artifact.contract_version "
            f"{strategy_artifact.contract_version} is not supported by this "
            f"ContentAgent (supported: "
            f"{sorted(SUPPORTED_STRATEGY_CONTRACT_VERSIONS)})."
        )

    if not strategy_artifact.objective or not strategy_artifact.objective.strip():
        errors.append("strategy_artifact.objective is missing or empty.")

    if not strategy_artifact.platforms:
        errors.append("strategy_artifact.platforms is missing or empty.")

    # Integrity check: recompute StrategyArtifact's own content_hash from
    # its own fields (never trust the declared value), exactly mirroring
    # ReleaseCandidateIdentityLock's file-hash recomputation philosophy,
    # now applied inter-artifact rather than inter-file.
    try:
        recomputed = compute_strategy_content_hash(
            mission_id=strategy_artifact.mission_id,
            objective=strategy_artifact.objective,
            audience=strategy_artifact.audience,
            platforms=strategy_artifact.platforms,
            content_goals=strategy_artifact.content_goals,
            strategic_angles=strategy_artifact.strategic_angles,
            priorities=strategy_artifact.priorities,
            constraints=strategy_artifact.constraints,
            contract_version=strategy_artifact.contract_version,
        )
        if recomputed != strategy_artifact.content_hash:
            errors.append(
                "strategy_artifact.content_hash does not match a "
                "recomputed hash of its own fields -- possible tampering "
                "or corruption; refusing to consume."
            )
    except Exception as error:  # noqa: BLE001 -- surfaced as a reason, never masked
        errors.append(f"strategy_artifact integrity could not be verified: {error}")

    return errors


def _validate_content_input(agent_input: ContentAgentInput) -> List[str]:
    errors: List[str] = []

    if not isinstance(agent_input.mission_id, str) or not agent_input.mission_id.strip():
        errors.append("mission_id is missing or empty.")

    if (
        agent_input.language_override is not None
        and agent_input.language_override not in STRATEGY_ALLOWED_LANGUAGES
    ):
        errors.append(
            f"language_override '{agent_input.language_override}' is invalid "
            f"(allowed: {sorted(STRATEGY_ALLOWED_LANGUAGES)})."
        )

    if agent_input.tone is not None and agent_input.tone not in ALLOWED_TONES:
        errors.append(
            f"tone '{agent_input.tone}' is invalid "
            f"(allowed: {sorted(ALLOWED_TONES)})."
        )

    if (
        agent_input.content_format is not None
        and agent_input.content_format not in ALLOWED_FORMATS
    ):
        errors.append(
            f"content_format '{agent_input.content_format}' is invalid "
            f"(allowed: {sorted(ALLOWED_FORMATS)})."
        )

    if agent_input.platform_override is not None:
        if not isinstance(agent_input.platform_override, tuple) or not agent_input.platform_override:
            errors.append(
                "platform_override is provided but empty; supply at least "
                "one platform or omit the override entirely."
            )
        else:
            for platform in agent_input.platform_override:
                if platform not in STRATEGY_ALLOWED_PLATFORMS:
                    errors.append(
                        f"platform_override contains unsupported platform "
                        f"'{platform}' (allowed: "
                        f"{sorted(STRATEGY_ALLOWED_PLATFORMS)})."
                    )

    if agent_input.duration_target_seconds is not None:
        value = agent_input.duration_target_seconds
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append("duration_target_seconds must be a positive integer when provided.")

    return errors


# ----------------------------------------------------------------------
# DURATION SPLITTING -- pure, deterministic. Floors each scene's share
# and assigns the entire rounding remainder to the last scene, so the
# sum always equals the target exactly.
# ----------------------------------------------------------------------


def _split_duration(total_seconds: int, weights: Tuple[float, ...]) -> Tuple[int, ...]:
    floors = [int(total_seconds * weight) for weight in weights]
    remainder = total_seconds - sum(floors)
    if floors:
        floors[-1] += remainder
    return tuple(floors)


# ----------------------------------------------------------------------
# HASH / INTEGRITY (P3.6 Section 19) -- deterministic, stable, canonical.
# Excludes artifact_id/created_at (technical/temporal) and dependencies
# (a technical linkage list of ids, not content) from both hashes; each
# hash INCLUDES its upstream artifact's content_hash instead, which is
# the tamper-evident, content-derived value worth binding to.
# ----------------------------------------------------------------------


def compute_content_artifact_hash(
    mission_id: str,
    concept: str,
    angle: str,
    hook: str,
    title: str,
    cta: str,
    target_platforms: Tuple[str, ...],
    language: str,
    tone: str,
    content_format: str,
    constraints: Tuple[str, ...],
    contract_version: int,
    source_strategy_content_hash: str,
) -> str:
    canonical = {
        "mission_id": mission_id,
        "concept": concept,
        "angle": angle,
        "hook": hook,
        "title": title,
        "cta": cta,
        "target_platforms": list(target_platforms),
        "language": language,
        "tone": tone,
        "content_format": content_format,
        "constraints": list(constraints),
        "contract_version": contract_version,
        "source_strategy_content_hash": source_strategy_content_hash,
    }
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def compute_script_artifact_hash(
    mission_id: str,
    scenes: Tuple[Scene, ...],
    total_duration_target: int,
    language: str,
    contract_version: int,
    source_content_content_hash: str,
) -> str:
    canonical = {
        "mission_id": mission_id,
        "scenes": [
            {
                "order": scene.order,
                "duration": scene.duration,
                "narration": scene.narration,
                "visual_direction": scene.visual_direction,
                "transition": scene.transition,
                "notes": scene.notes,
            }
            for scene in scenes
        ],
        "total_duration_target": total_duration_target,
        "language": language,
        "contract_version": contract_version,
        "source_content_content_hash": source_content_content_hash,
    }
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# IDEMPOTENCY (P3.6 Section 22) -- pure function, no store, no
# persistence, no database. Bound to the exact StrategyArtifact CONTENT
# (via its content_hash), not merely its artifact_id, so a different
# strategy content under the same mission never collides.
# ----------------------------------------------------------------------


def compute_content_idempotency_key(agent_input: ContentAgentInput) -> str:
    strategy_artifact = agent_input.strategy_artifact
    canonical = {
        "mission_id": agent_input.mission_id,
        "strategy_artifact_id": getattr(strategy_artifact, "artifact_id", None),
        "strategy_artifact_version": getattr(strategy_artifact, "version", None),
        "strategy_content_hash": getattr(strategy_artifact, "content_hash", None),
        "language_override": agent_input.language_override,
        "tone": agent_input.tone,
        "content_format": agent_input.content_format,
        "platform_override": (
            list(agent_input.platform_override)
            if agent_input.platform_override is not None
            else None
        ),
        "duration_target_seconds": agent_input.duration_target_seconds,
        "constraints": list(agent_input.constraints),
    }
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# CONTENT AGENT (P3.6 Section 3)
# ----------------------------------------------------------------------


class ContentAgent:
    """
    AI DIRECTOR — Content Agent v1.0 (P3.6)

    Depends on `agents.strategy_agent` ONLY for the `StrategyArtifact`
    contract/whitelists/hash function it must consume -- no dependency on
    Higgsfield, any P2 gate/authority module, the Director, or any event
    bus.
    """

    def __init__(self, engine: Optional[ContentEngine] = None):
        self.engine = engine or DeterministicContentEngine()

    def run(self, agent_input: ContentAgentInput) -> ContentAgentOutput:
        """
        Validates the StrategyArtifact dependency FIRST (REJECTED on
        failure -- a DEPENDENCY-category outcome), then this agent's own
        input fields (VALIDATION_ERROR on failure). Never mutates any
        mission state, never emits an event, never constructs any
        authority object.
        """

        mission_id = (
            agent_input.mission_id if isinstance(agent_input.mission_id, str) else ""
        )

        dependency_errors = _validate_strategy_dependency(agent_input)
        if dependency_errors:
            return ContentAgentOutput(
                mission_id=mission_id,
                status=ContentAgentStatus.REJECTED,
                errors=tuple(dependency_errors),
            )

        input_errors = _validate_content_input(agent_input)
        if input_errors:
            return ContentAgentOutput(
                mission_id=mission_id,
                status=ContentAgentStatus.VALIDATION_ERROR,
                errors=tuple(input_errors),
            )

        warnings: List[str] = []
        strategy_artifact = agent_input.strategy_artifact

        if agent_input.language_override is not None:
            resolved_language = agent_input.language_override
        else:
            resolved_language = DEFAULT_CONTENT_LANGUAGE
            warnings.append(
                "no language_override provided and StrategyArtifact "
                "carries no language field (P3.5 contract gap); "
                f"defaulting content language to '{DEFAULT_CONTENT_LANGUAGE}'."
            )

        resolved_tone = agent_input.tone or DEFAULT_TONE
        resolved_format = agent_input.content_format or DEFAULT_FORMAT

        if agent_input.platform_override is not None:
            resolved_platforms = agent_input.platform_override
            if set(resolved_platforms) != set(strategy_artifact.platforms):
                warnings.append(
                    f"platform_override {list(resolved_platforms)} explicitly "
                    f"diverges from strategy_artifact.platforms "
                    f"{list(strategy_artifact.platforms)}; using the override "
                    f"per explicit instruction."
                )
        else:
            resolved_platforms = strategy_artifact.platforms

        if agent_input.duration_target_seconds is not None:
            resolved_duration = agent_input.duration_target_seconds
        else:
            resolved_duration = DEFAULT_TOTAL_DURATION_TARGET_SECONDS
            warnings.append(
                "no duration_target_seconds provided; using a non-binding "
                f"scaffold default of {DEFAULT_TOTAL_DURATION_TARGET_SECONDS}s "
                f"-- this is NOT a user-specified requirement."
            )

        merged_constraints = tuple(strategy_artifact.constraints) + tuple(
            agent_input.constraints
        )

        context = ContentGenerationContext(
            strategy_artifact=strategy_artifact,
            language=resolved_language,
            tone=resolved_tone,
            content_format=resolved_format,
            platforms=resolved_platforms,
            constraints=merged_constraints,
        )

        result = self.engine.build_content(context)
        warnings.extend(result.warnings)

        content_artifact_id = uuid.uuid4().hex
        script_artifact_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()

        content_hash = compute_content_artifact_hash(
            mission_id=agent_input.mission_id,
            concept=result.concept,
            angle=result.angle,
            hook=result.hook,
            title=result.title,
            cta=result.cta,
            target_platforms=resolved_platforms,
            language=resolved_language,
            tone=resolved_tone,
            content_format=resolved_format,
            constraints=merged_constraints,
            contract_version=CONTRACT_VERSION,
            source_strategy_content_hash=strategy_artifact.content_hash,
        )

        content_artifact = ContentArtifact(
            artifact_id=content_artifact_id,
            artifact_type=CONTENT_ARTIFACT_TYPE,
            mission_id=agent_input.mission_id,
            created_at=created_at,
            version=ARTIFACT_VERSION,
            status="FINAL",
            concept=result.concept,
            angle=result.angle,
            hook=result.hook,
            title=result.title,
            cta=result.cta,
            target_platforms=resolved_platforms,
            language=resolved_language,
            tone=resolved_tone,
            content_format=resolved_format,
            constraints=merged_constraints,
            producer_agent=AGENT_ID,
            producer_version=AGENT_VERSION,
            contract_version=CONTRACT_VERSION,
            source_strategy_artifact_id=strategy_artifact.artifact_id,
            source_strategy_content_hash=strategy_artifact.content_hash,
            dependencies=(strategy_artifact.artifact_id,),
            content_hash=content_hash,
        )

        durations = _split_duration(
            resolved_duration, tuple(draft.weight for draft in result.scene_drafts)
        )

        scenes = tuple(
            Scene(
                scene_id=f"scene-{index + 1}",
                order=index + 1,
                duration=durations[index],
                narration=draft.narration,
                visual_direction=draft.visual_direction,
                transition=draft.transition,
                notes=draft.notes,
            )
            for index, draft in enumerate(result.scene_drafts)
        )

        script_hash = compute_script_artifact_hash(
            mission_id=agent_input.mission_id,
            scenes=scenes,
            total_duration_target=resolved_duration,
            language=resolved_language,
            contract_version=CONTRACT_VERSION,
            source_content_content_hash=content_artifact.content_hash,
        )

        script_artifact = ScriptArtifact(
            artifact_id=script_artifact_id,
            artifact_type=SCRIPT_ARTIFACT_TYPE,
            mission_id=agent_input.mission_id,
            created_at=created_at,
            version=ARTIFACT_VERSION,
            status="FINAL",
            scenes=scenes,
            total_duration_target=resolved_duration,
            language=resolved_language,
            producer_agent=AGENT_ID,
            producer_version=AGENT_VERSION,
            contract_version=CONTRACT_VERSION,
            source_content_artifact_id=content_artifact.artifact_id,
            dependencies=(content_artifact.artifact_id,),
            content_hash=script_hash,
        )

        return ContentAgentOutput(
            mission_id=agent_input.mission_id,
            status=ContentAgentStatus.READY,
            content_artifact=content_artifact,
            script_artifact=script_artifact,
            warnings=tuple(warnings),
        )
