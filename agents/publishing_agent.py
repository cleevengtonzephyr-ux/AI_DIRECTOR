"""
AI DIRECTOR — Publishing Agent v1.0 (Phase P3.8)

Fourth business agent of the future multi-agent AI Director, built
directly against the REAL `agents/content_agent.py` (P3.6) and
`agents/quality_agent.py` (P3.7) contracts -- `ContentArtifact`,
`ScriptArtifact`, `QualityArtifact`, `QualityAgentStatus`,
`EvaluatedArtifactReference`, their `*_TYPE`/`CONTRACT_VERSION`
constants, and their real `compute_*_hash()` functions -- none of which
are re-invented here. `agents/strategy_agent.py`'s `ALLOWED_PLATFORMS`
whitelist is imported directly (not through a re-export) for the same
reason ContentAgent and QualityAgent both do this: independent
re-verification, never trusting an upstream layer already did it. All
three upstream agent modules, plus their test files, were re-read from
disk in full before writing a single line of this module.

EXISTING PUBLISHING-RELATED CODE, CONFIRMED ABSENT (Section 3): a
repository-wide search for publisher/publishing/publication/social/
upload/post/schedule/scheduler/platform-name terms found zero existing
PublishingAgent, publisher, scheduler, or social-platform-API code
anywhere in this project. The only unrelated matches were prose in
`integrations/higgsfield/types.py` and `agents/video_agent.py`
docstrings explaining that "no real upload occurs" for image
references -- unrelated to this phase. There is nothing to duplicate
and nothing to avoid breaking.

THE SINGLE MOST IMPORTANT DISTINCTION IN THIS MODULE (Section 4/32):

    Publication preparation  !=  Publication authorization  !=  Real publication

This module implements ONLY the first. It produces a `PublicationArtifact`
describing WHAT would be published, WHERE, and (optionally) WHEN --
purely as data. It never contacts a social platform, never uploads
anything, never uses an OAuth/credential of any kind, and never creates
any authorization object (human or production). See
tests/test_publishing_agent.py::SecurityTests, which statically parses
this file's AST to enforce every one of these boundaries, exactly as
P3.5/P3.6/P3.7 were.

QUALITY DEPENDENCY RULE (Section 9/10), stated once, precisely:
Publication preparation may proceed ONLY if
`quality_artifact.quality_status` is `PASS` or `PASS_WITH_WARNINGS`.
Any other quality status (`FAIL`, `INTEGRITY_FAILURE`, `REJECTED`, or
anything else) yields `QUALITY_REJECTED` with NO `PublicationArtifact`
produced -- preparation never proceeds on untrustworthy or failing
content. `quality_artifact.quality_status == PASS` NEVER means
"publication authorized" -- it means only "publication preparation MAY
proceed." Tested explicitly (`test_quality_pass_does_not_authorize_publication`).

AUTHORITY (P3.2 Section 14 / P3.8 Section 4): PREPARE_PUBLICATION. Can
inspect artifacts, prepare metadata, produce a `PublicationArtifact`
candidate, validate platforms, and produce warnings -- cannot publish,
upload, call any social API, call HTTP, use OAuth/credentials, create a
real publication, mutate mission state, or create any human/production
authorization.

DETERMINISM: identical discipline to P3.5/P3.6/P3.7 -- no `random`, no
LLM call, no network/web call, no external trend/hashtag API. Only
`created_at` and `artifact_id` (technical, never fed into content_hash)
vary between calls with the same input.
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

from agents.content_agent import (
    CONTENT_ARTIFACT_TYPE,
    CONTRACT_VERSION as CONTENT_CONTRACT_VERSION,
    SCRIPT_ARTIFACT_TYPE,
    ContentArtifact,
    ScriptArtifact,
    compute_content_artifact_hash,
    compute_script_artifact_hash,
)
from agents.quality_agent import (
    CONTRACT_VERSION as QUALITY_CONTRACT_VERSION,
    QUALITY_ARTIFACT_TYPE,
    EvaluatedArtifactReference,
    QualityAgentStatus,
    QualityArtifact,
    compute_quality_artifact_hash,
)
from agents.strategy_agent import ALLOWED_PLATFORMS

# ----------------------------------------------------------------------
# VERSIONING (P3.8 Section 21)
# ----------------------------------------------------------------------

AGENT_ID = "publishing-agent"
AGENT_VERSION = "1.0"
CONTRACT_VERSION = 1
PUBLICATION_ARTIFACT_TYPE = "PublicationArtifact"
ARTIFACT_VERSION = 1

# This PublishingAgent version only knows how to interpret upstream
# artifacts produced under these exact contract_versions. An
# incompatible future contract_version is REJECTED (DEPENDENCY), never
# guess-parsed -- same discipline every prior agent in this series applies.
SUPPORTED_CONTENT_CONTRACT_VERSIONS = frozenset({CONTENT_CONTRACT_VERSION})
SUPPORTED_SCRIPT_CONTRACT_VERSIONS = frozenset({CONTENT_CONTRACT_VERSION})
SUPPORTED_QUALITY_CONTRACT_VERSIONS = frozenset({QUALITY_CONTRACT_VERSION})

# ----------------------------------------------------------------------
# WHITELISTS -- small, explicit, closed sets (P3.8 Section 13/17).
# ----------------------------------------------------------------------

ALLOWED_PUBLICATION_PROFILES = frozenset(
    {"default", "short_video", "professional", "educational", "cinematic"}
)

ALLOWED_TIMEZONES = frozenset(
    {
        "UTC",
        "America/New_York",
        "America/Los_Angeles",
        "Europe/Paris",
        "Europe/London",
        "Asia/Tokyo",
    }
)


class PublishingAgentStatus(str, Enum):
    """
    Doubles as `PublicationArtifact.publication_status`'s type (same
    reasoning as `QualityAgentStatus` in P3.7: both live in this module
    and their value sets legitimately overlap for the real outcomes).
    `NOT_PREPARED` is reserved vocabulary (never returned by
    `PublishingAgent.run()` today, same precedent as P3.7's
    `NOT_EVALUATED`). `REJECTED`/`VALIDATION_ERROR`/`QUALITY_REJECTED`
    never carry a produced artifact EXCEPT `INTEGRITY_FAILURE`, which --
    like P3.7's `INTEGRITY_FAILURE` -- produces a minimal artifact
    recording the fact as audit evidence, with zero prepared items.
    """

    NOT_PREPARED = "NOT_PREPARED"
    REJECTED = "REJECTED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTEGRITY_FAILURE = "INTEGRITY_FAILURE"
    QUALITY_REJECTED = "QUALITY_REJECTED"
    PREPARED = "PREPARED"
    PREPARATION_WARNING = "PREPARATION_WARNING"


class PublicationItemStatus(str, Enum):
    PREPARED = "PREPARED"
    WARNING = "WARNING"
    REJECTED = "REJECTED"


# Quality statuses that permit publication preparation to proceed
# (P3.8 Section 9) -- deliberately a closed allow-list, not a deny-list:
# anything not explicitly PASS/PASS_WITH_WARNINGS is rejected, fail-closed.
QUALITY_STATUSES_PERMITTING_PREPARATION = frozenset(
    {QualityAgentStatus.PASS, QualityAgentStatus.PASS_WITH_WARNINGS}
)

# ----------------------------------------------------------------------
# PUBLICATION PROFILE (P3.8 Section 13) -- minimal, explicit.
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class PublicationProfile:
    name: str = "default"


DEFAULT_PUBLICATION_PROFILE = PublicationProfile()


def _profile_to_dict(profile: PublicationProfile) -> dict:
    return {"name": profile.name}


# ----------------------------------------------------------------------
# INPUT CONTRACT (P3.8 Section 5)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class PublishingAgentInput:
    mission_id: str
    content_artifact: ContentArtifact
    script_artifact: ScriptArtifact
    quality_artifact: QualityArtifact
    publication_profile: Optional[PublicationProfile] = None
    platform_override: Optional[Tuple[str, ...]] = None
    scheduled_at: Optional[str] = None
    timezone: Optional[str] = None
    constraints: Tuple[str, ...] = field(default_factory=tuple)


# ----------------------------------------------------------------------
# PUBLICATION ITEM / MEDIA REFERENCE / SCHEDULE (P3.8 Sections 12/16/17)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class PublicationItem:
    platform: str
    title: str
    caption: str
    description: str
    hashtags: Tuple[str, ...]
    language: str
    content_format: str
    status: PublicationItemStatus


def _item_to_dict(item: PublicationItem) -> dict:
    return {
        "platform": item.platform,
        "title": item.title,
        "caption": item.caption,
        "description": item.description,
        "hashtags": list(item.hashtags),
        "language": item.language,
        "content_format": item.content_format,
        "status": item.status.value,
    }


@dataclass(frozen=True)
class PublicationMediaReference:
    """
    PURELY DECLARATIVE (P3.8 Section 16) -- points at the ScriptArtifact
    that WILL become a real video once a future VideoAgent/execution
    phase produces one. Never a file path to upload, never a CDN
    reference, never anything this module could act on.
    """

    reference_type: str
    artifact_id: str
    artifact_type: str
    content_hash: str


def _media_reference_to_dict(reference: PublicationMediaReference) -> dict:
    return {
        "reference_type": reference.reference_type,
        "artifact_id": reference.artifact_id,
        "artifact_type": reference.artifact_type,
        "content_hash": reference.content_hash,
    }


@dataclass(frozen=True)
class PublicationSchedule:
    scheduled_at: Optional[str]
    timezone: Optional[str]
    schedule_status: str  # "NOT_SCHEDULED" | "SCHEDULED"


def _schedule_to_dict(schedule: PublicationSchedule) -> dict:
    return {
        "scheduled_at": schedule.scheduled_at,
        "timezone": schedule.timezone,
        "schedule_status": schedule.schedule_status,
    }


NOT_SCHEDULED = PublicationSchedule(scheduled_at=None, timezone=None, schedule_status="NOT_SCHEDULED")


def _reference_to_dict(reference: EvaluatedArtifactReference) -> dict:
    return {
        "artifact_id": reference.artifact_id,
        "artifact_type": reference.artifact_type,
        "artifact_version": reference.artifact_version,
        "content_hash": reference.content_hash,
    }


# ----------------------------------------------------------------------
# PUBLICATION ARTIFACT (P3.8 Section 18)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class PublicationArtifact:
    artifact_id: str
    artifact_type: str
    mission_id: str
    created_at: str
    version: int
    status: str  # Artifact lifecycle status (DRAFT|FINAL|SUPERSEDED),
    # distinct from `publication_status` below -- same discipline as
    # P3.5/P3.6/P3.7's artifact-status-vs-agent-status separation.

    publication_status: PublishingAgentStatus
    platforms: Tuple[str, ...]
    publication_items: Tuple[PublicationItem, ...]
    media_reference: Optional[PublicationMediaReference]
    schedule: PublicationSchedule
    profile: PublicationProfile
    evaluated_artifacts: Tuple[EvaluatedArtifactReference, ...]

    producer_agent: str
    producer_version: str
    contract_version: int

    content_hash: str


# ----------------------------------------------------------------------
# OUTPUT CONTRACT
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class PublishingAgentOutput:
    mission_id: str
    status: PublishingAgentStatus
    publication_artifact: Optional[PublicationArtifact] = None
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    errors: Tuple[str, ...] = field(default_factory=tuple)
    producer_agent: str = AGENT_ID
    producer_version: str = AGENT_VERSION
    contract_version: int = CONTRACT_VERSION


# ----------------------------------------------------------------------
# PUBLISHING ENGINE (P3.8 Section 35) -- PublishingAgent = validation,
# integrity, quality-gate, orchestration, hashing; PublishingEngine =
# per-platform item preparation. Swappable without changing
# PublishingAgent's own contract, mirroring every prior agent's engine
# split.
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class PublicationPreparationContext:
    content_artifact: ContentArtifact
    platforms: Tuple[str, ...]
    profile: PublicationProfile


@dataclass(frozen=True)
class PublicationPreparationResult:
    items: Tuple[PublicationItem, ...]
    warnings: Tuple[str, ...] = field(default_factory=tuple)


class PublishingEngine(ABC):
    """Contract every publishing backend (deterministic V1, a future
    real platform-API-backed engine) must satisfy. Never called before
    integrity AND the quality gate have already passed."""

    @abstractmethod
    def prepare(self, context: PublicationPreparationContext) -> PublicationPreparationResult:
        raise NotImplementedError


class DeterministicPublishingEngine(PublishingEngine):
    """
    V1 default engine: purely local, template-based, deterministic. No
    random, no LLM, no network, no trending-hashtag API. Same
    PublicationPreparationContext always produces the same items, in the
    same per-platform order as `context.platforms`.

    DERIVATION RULES (P3.8 Section 14/15), documented exactly:
    - title       <- content_artifact.title (verbatim)
    - caption     <- content_artifact.hook (verbatim; the hook IS the
                     opening/attention material, exactly the role a
                     caption's first line plays)
    - description <- content_artifact.concept (verbatim)
    - hashtags    <- derived ONLY from already-available artifact
                     metadata (tone, content_format, platform name) --
                     never from title/hook/description text (no keyword
                     extraction, no NLP, no invented semantic tags) and
                     never from any external trending/search API.
    - language, content_format <- content_artifact fields, verbatim.
    `profile.name` is reserved for a future engine to branch on; this
    V1 engine applies the identical derivation regardless of profile,
    documented here rather than pretending a profile-specific behavior
    that does not exist.
    """

    def prepare(self, context: PublicationPreparationContext) -> PublicationPreparationResult:
        content = context.content_artifact
        items = tuple(
            PublicationItem(
                platform=platform,
                title=content.title,
                caption=content.hook,
                description=content.concept,
                hashtags=(
                    f"#{content.tone}",
                    f"#{content.content_format}",
                    f"#{platform}",
                ),
                language=content.language,
                content_format=content.content_format,
                status=PublicationItemStatus.PREPARED,
            )
            for platform in context.platforms
        )
        return PublicationPreparationResult(items=items)


# ----------------------------------------------------------------------
# VALIDATION (P3.8 Sections 6/7/8/9) -- four structurally separate
# checks, never merged.
# ----------------------------------------------------------------------


def _validate_artifact_dependencies(agent_input: PublishingAgentInput) -> List[str]:
    errors: List[str] = []

    content_artifact = agent_input.content_artifact
    script_artifact = agent_input.script_artifact
    quality_artifact = agent_input.quality_artifact

    if content_artifact is None:
        errors.append("content_artifact is missing.")
    elif not isinstance(content_artifact, ContentArtifact):
        errors.append("content_artifact is not a valid ContentArtifact instance.")

    if script_artifact is None:
        errors.append("script_artifact is missing.")
    elif not isinstance(script_artifact, ScriptArtifact):
        errors.append("script_artifact is not a valid ScriptArtifact instance.")

    if quality_artifact is None:
        errors.append("quality_artifact is missing.")
    elif not isinstance(quality_artifact, QualityArtifact):
        errors.append("quality_artifact is not a valid QualityArtifact instance.")

    if errors:
        # Cannot safely inspect further attributes on a missing/wrong-type
        # object -- return what was already found (fail closed).
        return errors

    if content_artifact.artifact_type != CONTENT_ARTIFACT_TYPE:
        errors.append(
            f"content_artifact.artifact_type '{content_artifact.artifact_type}' "
            f"is not '{CONTENT_ARTIFACT_TYPE}'."
        )
    if script_artifact.artifact_type != SCRIPT_ARTIFACT_TYPE:
        errors.append(
            f"script_artifact.artifact_type '{script_artifact.artifact_type}' "
            f"is not '{SCRIPT_ARTIFACT_TYPE}'."
        )
    if quality_artifact.artifact_type != QUALITY_ARTIFACT_TYPE:
        errors.append(
            f"quality_artifact.artifact_type '{quality_artifact.artifact_type}' "
            f"is not '{QUALITY_ARTIFACT_TYPE}'."
        )

    for label, artifact in (
        ("content_artifact", content_artifact),
        ("script_artifact", script_artifact),
        ("quality_artifact", quality_artifact),
    ):
        if artifact.mission_id != agent_input.mission_id:
            errors.append(
                f"{label}.mission_id '{artifact.mission_id}' does not match "
                f"this PublishingAgentInput.mission_id "
                f"'{agent_input.mission_id}' -- refusing to consume an "
                f"artifact belonging to a different mission."
            )
        if artifact.status != "FINAL":
            errors.append(f"{label}.status '{artifact.status}' is not 'FINAL'.")

    if content_artifact.contract_version not in SUPPORTED_CONTENT_CONTRACT_VERSIONS:
        errors.append(
            f"content_artifact.contract_version "
            f"{content_artifact.contract_version} is not supported "
            f"(supported: {sorted(SUPPORTED_CONTENT_CONTRACT_VERSIONS)})."
        )
    if script_artifact.contract_version not in SUPPORTED_SCRIPT_CONTRACT_VERSIONS:
        errors.append(
            f"script_artifact.contract_version "
            f"{script_artifact.contract_version} is not supported "
            f"(supported: {sorted(SUPPORTED_SCRIPT_CONTRACT_VERSIONS)})."
        )
    if quality_artifact.contract_version not in SUPPORTED_QUALITY_CONTRACT_VERSIONS:
        errors.append(
            f"quality_artifact.contract_version "
            f"{quality_artifact.contract_version} is not supported "
            f"(supported: {sorted(SUPPORTED_QUALITY_CONTRACT_VERSIONS)})."
        )

    if script_artifact.source_content_artifact_id != content_artifact.artifact_id:
        errors.append(
            f"script_artifact.source_content_artifact_id "
            f"'{script_artifact.source_content_artifact_id}' does not match "
            f"the supplied content_artifact.artifact_id "
            f"'{content_artifact.artifact_id}' -- this script was not "
            f"derived from this content artifact."
        )

    evaluated_ids = {(ref.artifact_id, ref.content_hash) for ref in quality_artifact.evaluated_artifacts}
    if (content_artifact.artifact_id, content_artifact.content_hash) not in evaluated_ids:
        errors.append(
            "quality_artifact.evaluated_artifacts does not reference the "
            "supplied content_artifact (by id and content_hash) -- this "
            "quality evaluation was not performed against this content."
        )
    if (script_artifact.artifact_id, script_artifact.content_hash) not in evaluated_ids:
        errors.append(
            "quality_artifact.evaluated_artifacts does not reference the "
            "supplied script_artifact (by id and content_hash) -- this "
            "quality evaluation was not performed against this script."
        )

    return errors


def _validate_publishing_input(agent_input: PublishingAgentInput) -> List[str]:
    errors: List[str] = []

    if not isinstance(agent_input.mission_id, str) or not agent_input.mission_id.strip():
        errors.append("mission_id is missing or empty.")

    profile = agent_input.publication_profile
    if profile is not None:
        if not isinstance(profile, PublicationProfile):
            errors.append("publication_profile is not a valid PublicationProfile instance.")
        elif profile.name not in ALLOWED_PUBLICATION_PROFILES:
            errors.append(
                f"publication_profile.name '{profile.name}' is invalid "
                f"(allowed: {sorted(ALLOWED_PUBLICATION_PROFILES)})."
            )

    if agent_input.platform_override is not None:
        if not isinstance(agent_input.platform_override, tuple) or not agent_input.platform_override:
            errors.append(
                "platform_override is provided but empty; supply at least "
                "one platform or omit the override entirely."
            )
        else:
            for platform in agent_input.platform_override:
                if platform not in ALLOWED_PLATFORMS:
                    errors.append(
                        f"platform_override contains unsupported platform "
                        f"'{platform}' (allowed: {sorted(ALLOWED_PLATFORMS)})."
                    )

    has_scheduled_at = agent_input.scheduled_at is not None
    has_timezone = agent_input.timezone is not None
    if has_scheduled_at != has_timezone:
        errors.append(
            "scheduled_at and timezone must both be provided together, or "
            "both omitted -- refusing to schedule with an incomplete "
            "configuration."
        )
    elif has_scheduled_at and has_timezone:
        if agent_input.timezone not in ALLOWED_TIMEZONES:
            errors.append(
                f"timezone '{agent_input.timezone}' is invalid "
                f"(allowed: {sorted(ALLOWED_TIMEZONES)})."
            )
        try:
            datetime.fromisoformat(agent_input.scheduled_at)
        except (TypeError, ValueError):
            errors.append(
                f"scheduled_at '{agent_input.scheduled_at}' is not a valid "
                f"ISO 8601 datetime string."
            )

    return errors


def _integrity_errors(agent_input: PublishingAgentInput) -> List[str]:
    """
    Recomputes all THREE upstream artifacts' content_hash from their own
    real fields via the REAL, imported hash functions -- never trusting
    the declared value. Never converts a mismatch into a warning or a
    soft pass (P3.8 Section 8: "Ne jamais préparer une publication à
    partir d'un artifact corrompu").
    """

    content = agent_input.content_artifact
    script = agent_input.script_artifact
    quality = agent_input.quality_artifact
    errors: List[str] = []

    try:
        recomputed_content_hash = compute_content_artifact_hash(
            mission_id=content.mission_id,
            concept=content.concept,
            angle=content.angle,
            hook=content.hook,
            title=content.title,
            cta=content.cta,
            target_platforms=content.target_platforms,
            language=content.language,
            tone=content.tone,
            content_format=content.content_format,
            constraints=content.constraints,
            contract_version=content.contract_version,
            source_strategy_content_hash=content.source_strategy_content_hash,
        )
        if recomputed_content_hash != content.content_hash:
            errors.append(
                "content_artifact.content_hash does not match a recomputed "
                "hash of its own fields -- possible tampering or corruption."
            )
    except Exception as error:  # noqa: BLE001 -- surfaced, never masked
        errors.append(f"content_artifact integrity could not be verified: {error}")

    try:
        recomputed_script_hash = compute_script_artifact_hash(
            mission_id=script.mission_id,
            scenes=script.scenes,
            total_duration_target=script.total_duration_target,
            language=script.language,
            contract_version=script.contract_version,
            source_content_content_hash=content.content_hash,
        )
        if recomputed_script_hash != script.content_hash:
            errors.append(
                "script_artifact.content_hash does not match a recomputed "
                "hash bound to the supplied content_artifact -- possible "
                "tampering, corruption, or a mismatched pair."
            )
    except Exception as error:  # noqa: BLE001
        errors.append(f"script_artifact integrity could not be verified: {error}")

    try:
        recomputed_quality_hash = compute_quality_artifact_hash(
            mission_id=quality.mission_id,
            quality_status=quality.quality_status,
            score=quality.score,
            findings=quality.findings,
            evaluated_artifacts=quality.evaluated_artifacts,
            profile=quality.profile,
            contract_version=quality.contract_version,
        )
        if recomputed_quality_hash != quality.content_hash:
            errors.append(
                "quality_artifact.content_hash does not match a recomputed "
                "hash of its own fields -- possible tampering or corruption."
            )
    except Exception as error:  # noqa: BLE001
        errors.append(f"quality_artifact integrity could not be verified: {error}")

    return errors


# ----------------------------------------------------------------------
# HASH / INTEGRITY (P3.8 Section 22) -- deterministic, stable, canonical.
# Excludes artifact_id/created_at (technical/temporal).
# ----------------------------------------------------------------------


def compute_publication_artifact_hash(
    mission_id: str,
    publication_status: PublishingAgentStatus,
    platforms: Tuple[str, ...],
    publication_items: Tuple[PublicationItem, ...],
    media_reference: Optional[PublicationMediaReference],
    schedule: PublicationSchedule,
    profile: PublicationProfile,
    evaluated_artifacts: Tuple[EvaluatedArtifactReference, ...],
    contract_version: int,
) -> str:
    canonical = {
        "mission_id": mission_id,
        "publication_status": publication_status.value,
        "platforms": list(platforms),
        "publication_items": [_item_to_dict(item) for item in publication_items],
        "media_reference": (
            _media_reference_to_dict(media_reference) if media_reference is not None else None
        ),
        "schedule": _schedule_to_dict(schedule),
        "profile": _profile_to_dict(profile),
        "evaluated_artifacts": [_reference_to_dict(ref) for ref in evaluated_artifacts],
        "contract_version": contract_version,
    }
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# IDEMPOTENCY (P3.8 Section 25) -- pure function, no store, no
# persistence, no database.
# ----------------------------------------------------------------------


def compute_publishing_idempotency_key(agent_input: PublishingAgentInput) -> str:
    content = agent_input.content_artifact
    script = agent_input.script_artifact
    quality = agent_input.quality_artifact
    profile = agent_input.publication_profile or DEFAULT_PUBLICATION_PROFILE

    canonical = {
        "mission_id": agent_input.mission_id,
        "content_artifact_id": getattr(content, "artifact_id", None),
        "content_artifact_version": getattr(content, "version", None),
        "content_content_hash": getattr(content, "content_hash", None),
        "script_artifact_id": getattr(script, "artifact_id", None),
        "script_artifact_version": getattr(script, "version", None),
        "script_content_hash": getattr(script, "content_hash", None),
        "quality_artifact_id": getattr(quality, "artifact_id", None),
        "quality_artifact_version": getattr(quality, "version", None),
        "quality_content_hash": getattr(quality, "content_hash", None),
        "profile": _profile_to_dict(profile),
        "platform_override": (
            list(agent_input.platform_override)
            if agent_input.platform_override is not None
            else None
        ),
        "scheduled_at": agent_input.scheduled_at,
        "timezone": agent_input.timezone,
        "constraints": list(agent_input.constraints),
    }
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# PUBLISHING AGENT (P3.8 Section 4)
# ----------------------------------------------------------------------


class PublishingAgent:
    """
    AI DIRECTOR — Publishing Agent v1.0 (P3.8)

    Depends on `agents.content_agent`/`agents.quality_agent` for the
    real contracts/hash functions it must consume, and on
    `agents.strategy_agent` ONLY for the platform whitelist it needs to
    independently re-verify an override -- no dependency on Higgsfield,
    any P2 gate/authority module, the Director, any event bus, or any
    network/social-platform library of any kind.
    """

    def __init__(self, engine: Optional[PublishingEngine] = None):
        self.engine = engine or DeterministicPublishingEngine()

    def run(self, agent_input: PublishingAgentInput) -> PublishingAgentOutput:
        """
        Order: (1) artifact dependency validation -> REJECTED; (2) this
        agent's own input validation -> VALIDATION_ERROR; (3) integrity
        (hash recomputation across all three upstream artifacts) ->
        INTEGRITY_FAILURE, WITH a minimal PublicationArtifact recording
        the fact (zero items); (4) quality gate -> QUALITY_REJECTED, NO
        artifact, if quality_status is not PASS/PASS_WITH_WARNINGS; (5)
        engine preparation -> PREPARED / PREPARATION_WARNING, WITH a
        fully populated PublicationArtifact. Never mutates
        `content_artifact`/`script_artifact`/`quality_artifact`. Never
        emits an event. Never constructs any authorization object. Never
        calls any social platform, HTTP client, or credential.
        """

        mission_id = (
            agent_input.mission_id if isinstance(agent_input.mission_id, str) else ""
        )

        dependency_errors = _validate_artifact_dependencies(agent_input)
        if dependency_errors:
            return PublishingAgentOutput(
                mission_id=mission_id,
                status=PublishingAgentStatus.REJECTED,
                errors=tuple(dependency_errors),
            )

        input_errors = _validate_publishing_input(agent_input)
        if input_errors:
            return PublishingAgentOutput(
                mission_id=mission_id,
                status=PublishingAgentStatus.VALIDATION_ERROR,
                errors=tuple(input_errors),
            )

        content = agent_input.content_artifact
        script = agent_input.script_artifact
        quality = agent_input.quality_artifact
        profile = agent_input.publication_profile or DEFAULT_PUBLICATION_PROFILE

        evaluated_artifacts = (
            EvaluatedArtifactReference(
                artifact_id=content.artifact_id,
                artifact_type=content.artifact_type,
                artifact_version=content.version,
                content_hash=content.content_hash,
            ),
            EvaluatedArtifactReference(
                artifact_id=script.artifact_id,
                artifact_type=script.artifact_type,
                artifact_version=script.version,
                content_hash=script.content_hash,
            ),
            EvaluatedArtifactReference(
                artifact_id=quality.artifact_id,
                artifact_type=quality.artifact_type,
                artifact_version=quality.version,
                content_hash=quality.content_hash,
            ),
        )

        integrity_errors = _integrity_errors(agent_input)
        if integrity_errors:
            return self._build_output(
                mission_id=agent_input.mission_id,
                publication_status=PublishingAgentStatus.INTEGRITY_FAILURE,
                platforms=(),
                items=(),
                media_reference=None,
                schedule=NOT_SCHEDULED,
                profile=profile,
                evaluated_artifacts=evaluated_artifacts,
                errors=tuple(integrity_errors),
            )

        # QUALITY GATE (P3.8 Section 9/10) -- fail-closed allow-list.
        # `PASS`/`PASS_WITH_WARNINGS` permit PREPARATION only, never
        # publication authority.
        if quality.quality_status not in QUALITY_STATUSES_PERMITTING_PREPARATION:
            return PublishingAgentOutput(
                mission_id=agent_input.mission_id,
                status=PublishingAgentStatus.QUALITY_REJECTED,
                errors=(
                    f"quality_artifact.quality_status is "
                    f"'{quality.quality_status.value}', which does not "
                    f"permit publication preparation (only PASS or "
                    f"PASS_WITH_WARNINGS do).",
                ),
            )

        if agent_input.platform_override is not None:
            platforms = agent_input.platform_override
        else:
            platforms = content.target_platforms

        if agent_input.scheduled_at is not None:
            schedule = PublicationSchedule(
                scheduled_at=agent_input.scheduled_at,
                timezone=agent_input.timezone,
                schedule_status="SCHEDULED",
            )
        else:
            schedule = NOT_SCHEDULED

        context = PublicationPreparationContext(
            content_artifact=content, platforms=platforms, profile=profile
        )
        result = self.engine.prepare(context)

        media_reference = PublicationMediaReference(
            reference_type="script_artifact",
            artifact_id=script.artifact_id,
            artifact_type=script.artifact_type,
            content_hash=script.content_hash,
        )

        has_engine_warnings = bool(result.warnings)
        if quality.quality_status == QualityAgentStatus.PASS and not has_engine_warnings:
            publication_status = PublishingAgentStatus.PREPARED
        else:
            publication_status = PublishingAgentStatus.PREPARATION_WARNING

        return self._build_output(
            mission_id=agent_input.mission_id,
            publication_status=publication_status,
            platforms=platforms,
            items=result.items,
            media_reference=media_reference,
            schedule=schedule,
            profile=profile,
            evaluated_artifacts=evaluated_artifacts,
            warnings=result.warnings,
        )

    @staticmethod
    def _build_output(
        mission_id: str,
        publication_status: PublishingAgentStatus,
        platforms: Tuple[str, ...],
        items: Tuple[PublicationItem, ...],
        media_reference: Optional[PublicationMediaReference],
        schedule: PublicationSchedule,
        profile: PublicationProfile,
        evaluated_artifacts: Tuple[EvaluatedArtifactReference, ...],
        warnings: Tuple[str, ...] = (),
        errors: Tuple[str, ...] = (),
    ) -> PublishingAgentOutput:
        artifact_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()

        content_hash = compute_publication_artifact_hash(
            mission_id=mission_id,
            publication_status=publication_status,
            platforms=platforms,
            publication_items=items,
            media_reference=media_reference,
            schedule=schedule,
            profile=profile,
            evaluated_artifacts=evaluated_artifacts,
            contract_version=CONTRACT_VERSION,
        )

        publication_artifact = PublicationArtifact(
            artifact_id=artifact_id,
            artifact_type=PUBLICATION_ARTIFACT_TYPE,
            mission_id=mission_id,
            created_at=created_at,
            version=ARTIFACT_VERSION,
            status="FINAL",
            publication_status=publication_status,
            platforms=platforms,
            publication_items=items,
            media_reference=media_reference,
            schedule=schedule,
            profile=profile,
            evaluated_artifacts=evaluated_artifacts,
            producer_agent=AGENT_ID,
            producer_version=AGENT_VERSION,
            contract_version=CONTRACT_VERSION,
            content_hash=content_hash,
        )

        return PublishingAgentOutput(
            mission_id=mission_id,
            status=publication_status,
            publication_artifact=publication_artifact,
            warnings=warnings,
            errors=errors,
        )
