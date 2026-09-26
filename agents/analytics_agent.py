"""
AI DIRECTOR — Analytics Agent v1.0 (Phase P3.10)

Fifth business agent of the future multi-agent AI Director. Collects,
validates, and normalizes analytics OBSERVATIONS that have ALREADY been
supplied to the system (never fetched by this module itself) into the
REAL `AnalyticsArtifact` contract already established and consumed by
`agents/optimization_agent.py` (P3.9) -- re-read from disk in full
before writing a single line of this module, along with
`agents/strategy_agent.py`, `agents/content_agent.py`,
`agents/quality_agent.py`, `agents/publishing_agent.py`, and all five
corresponding test files.

ANALYTICS CONTRACT AUDIT (Section 2) -- CRITICAL DECISION, DOCUMENTED:
`AnalyticsArtifact`, `AnalyticsPeriod`, `MetricValue`, and
`compute_analytics_artifact_hash()` were confirmed, by direct reading of
`agents/optimization_agent.py`, to already be real, tested, and consumed
by `OptimizationAgent` and `tests/test_optimization_agent.py`. Per
instruction ("NE PAS créer deux contrats concurrents" / "adapter
exactement au contrat déjà consommé par P3.9"), this module does NOT
define a second, competing `AnalyticsArtifact` -- it imports and reuses
the real one. The contract's HOME remains `agents/optimization_agent.py`
(the module that already owned it and whose tests already depend on its
exact field layout); this module is a CONSUMER-AND-PRODUCER of that
contract, exactly the same relationship `ContentAgent` has to
`StrategyArtifact` (defined in `strategy_agent.py`, not duplicated
elsewhere).

THE ONE CONTRACT EXTENSION MADE, AND WHY IT IS SAFE (Section 21/42):
`AnalyticsArtifact` gained three new fields in `optimization_agent.py`
as part of this phase -- `observations`, `source_references`,
`observations_hash` -- each APPENDED with a default value. Every P3.9
construction of `AnalyticsArtifact` uses keyword arguments exclusively
and never supplies these three, so every existing P3.9 call site is
unaffected. Critically, `compute_analytics_artifact_hash()` (the
function whose output IS `AnalyticsArtifact.content_hash`, the field
`OptimizationAgent`'s own integrity check re-verifies) was NOT modified
at all -- it still takes exactly the same 5 parameters and computes
exactly the same canonical dict as it did in P3.9. The three new fields
are covered by a SEPARATE, independent hash (`observations_hash`,
computed by `compute_observations_hash()` in THIS module), so P3.9's
integrity guarantee is untouched. `tests/test_optimization_agent.py`
(all 59 tests, unmodified) was re-run after this extension and confirmed
still green before any other P3.10 code was written.

ARCHITECTURE (Section 5):

    AnalyticsAgent
         v
    AnalyticsEngine (DeterministicAnalyticsEngine, this phase)
         v
    AnalyticsCollectionResult
         v
    AnalyticsArtifact (the REAL, P3.9-compatible contract)
         v
    OptimizationAgent (P3.9, unchanged)

A future `PlatformAnalyticsAdapter` family (YouTube/TikTok/Instagram/
Facebook/LinkedIn/X) is anticipated by the `AnalyticsSourceTrust.
FUTURE_PLATFORM_ADAPTER` enum member existing in the vocabulary -- but
NO adapter is implemented here, NO adapter interface is even sketched
beyond that one reserved enum value, and NOTHING in this module's code
ever constructs a `FUTURE_PLATFORM_ADAPTER`-sourced observation (see
tests/test_analytics_agent.py::SecurityTests).

THE TWO MOST IMPORTANT RULES IN THIS MODULE:

1. NO FABRICATED DATA (Section 10): a metric with no observation behind
   it is ABSENT from `AnalyticsArtifact.metrics` -- never coerced to
   `0`. `0` means "an observation reported exactly zero."
2. NO FABRICATED PUBLICATION RESULTS (Section 31): this module never
   constructs, assigns, or implies the literal status "PUBLISHED"
   anywhere -- a `publication_artifact` cross-reference, if supplied,
   is validated for integrity/mission binding and traced, but its
   `publication_status` is never read as evidence that real publication
   occurred (P3.8's own `PREPARED != PUBLISHED` rule, respected here at
   the consuming end, exactly as `OptimizationAgent` already does).

AUTHORITY (P3.2 Section 14 / P3.10 Section 6): OBSERVE / NORMALIZE /
REPORT. Cannot modify any other artifact, apply an optimization,
publish, generate, call Higgsfield, call any social/platform API, or
create any authorization.

DETERMINISM: identical discipline to every prior agent -- no `random`,
no LLM call, no network/web call, no real platform API call. Only
`created_at`/`artifact_id` vary between calls with the same input.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple

from agents.content_agent import (
    CONTENT_ARTIFACT_TYPE,
    CONTRACT_VERSION as CONTENT_CONTRACT_VERSION,
    SCRIPT_ARTIFACT_TYPE,
    ContentArtifact,
    ScriptArtifact,
    compute_content_artifact_hash,
    compute_script_artifact_hash,
)
from agents.optimization_agent import (
    ANALYTICS_ARTIFACT_TYPE,
    ANALYTICS_ARTIFACT_VERSION,
    ANALYTICS_CONTRACT_VERSION,
    NON_NEGATIVE_METRIC_NAMES,
    RATIO_METRIC_NAMES,
    AnalyticsArtifact,
    AnalyticsPeriod,
    MetricValue,
    compute_analytics_artifact_hash,
)
from agents.publishing_agent import (
    ALLOWED_TIMEZONES,
    CONTRACT_VERSION as PUBLISHING_CONTRACT_VERSION,
    PUBLICATION_ARTIFACT_TYPE,
    PublicationArtifact,
    compute_publication_artifact_hash,
)
from agents.quality_agent import (
    CONTRACT_VERSION as QUALITY_CONTRACT_VERSION,
    QUALITY_ARTIFACT_TYPE,
    QualityArtifact,
    compute_quality_artifact_hash,
)
from agents.strategy_agent import ALLOWED_PLATFORMS

# ----------------------------------------------------------------------
# VERSIONING (P3.10 Section 27) -- this module's OWN Input/Output
# contract version, DISTINCT from `ANALYTICS_CONTRACT_VERSION` (imported
# above), which is the AnalyticsArtifact SHAPE version owned by
# `optimization_agent.py`. Never confuse the two: this agent stamps
# `AnalyticsArtifact.contract_version = ANALYTICS_CONTRACT_VERSION`
# (the artifact's own shape version) while its OWN
# `AnalyticsAgentOutput.contract_version` is this module's `CONTRACT_
# VERSION` below.
# ----------------------------------------------------------------------

AGENT_ID = "analytics-agent"
AGENT_VERSION = "1.0"
CONTRACT_VERSION = 1

SUPPORTED_CONTENT_CONTRACT_VERSIONS = frozenset({CONTENT_CONTRACT_VERSION})
SUPPORTED_QUALITY_CONTRACT_VERSIONS = frozenset({QUALITY_CONTRACT_VERSION})
SUPPORTED_PUBLISHING_CONTRACT_VERSIONS = frozenset({PUBLISHING_CONTRACT_VERSION})

# ----------------------------------------------------------------------
# METRIC CONTRACT (P3.10 Section 11) -- EXTENDS, never duplicates, the
# REAL whitelists already defined and consumed by OptimizationAgent
# (imported above). One new ratio metric (`retention_rate`) and one
# currency metric (`revenue`) are added here, since P3.9 never needed
# either. STRATEGY CHOSEN (Section 11 requires picking exactly one):
# an unknown metric name is REJECTED (VALIDATION_ERROR), never silently
# kept as an untyped "custom" metric -- downstream consumers (today:
# OptimizationAgent) have a fixed, closed vocabulary they know how to
# interpret safely, and this module never extends that vocabulary
# implicitly.
# ----------------------------------------------------------------------

EXTENDED_RATIO_METRIC_NAMES = RATIO_METRIC_NAMES | {"retention_rate"}
CURRENCY_METRIC_NAMES = frozenset({"revenue"})
ALL_KNOWN_NUMERIC_METRIC_NAMES = NON_NEGATIVE_METRIC_NAMES | EXTENDED_RATIO_METRIC_NAMES

# Canonical unit expected per known metric (Section 12) -- a ratio
# metric MAY also arrive as "percentage" (normalized by /100, Section
# 13); every other metric's unit must match EXACTLY, never guessed.
METRIC_CANONICAL_UNIT: Dict[str, str] = {
    "views": "count",
    "impressions": "count",
    "likes": "count",
    "comments": "count",
    "shares": "count",
    "saves": "count",
    "conversions": "count",
    "watch_time": "seconds",
    "completion_rate": "ratio",
    "click_through_rate": "ratio",
    "retention_rate": "ratio",
    "revenue": "currency",
}

ALLOWED_UNITS = frozenset({"count", "seconds", "ratio", "percentage", "currency"})


class AnalyticsSourceTrust(str, Enum):
    """
    Section 32: minimum conceptual vocabulary. `FUTURE_PLATFORM_ADAPTER`
    is reserved interface surface for a future phase -- THIS module's
    code never constructs an observation with this source (verified by
    tests/test_analytics_agent.py::SecurityTests, both behaviorally and
    via AST).
    """

    EXPLICIT_INPUT = "explicit_input"
    FUTURE_PLATFORM_ADAPTER = "future_platform_adapter"
    DERIVED = "derived"


# ----------------------------------------------------------------------
# RAW OBSERVATION MODEL (P3.10 Section 8)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class AnalyticsObservation:
    """
    One reported data point. `source`/`source_reference` are REQUIRED
    (no default) -- Section 9: every datum must be traceable, never
    silently attributed. `observed_at`, if given, is preserved EXACTLY
    (Section 17) -- never replaced by current time, never invented if
    absent. `currency` is only meaningful when `metric` is a currency
    metric (Section 35). `is_derived`/`derived_from` distinguish a
    computed value from a directly-reported one (Section 19/20) -- a
    derived observation is NEVER presented as directly platform-reported.
    """

    metric: str
    value: float
    unit: str
    platform: str
    source: str
    source_reference: str
    observed_at: Optional[str] = None
    period: Optional[AnalyticsPeriod] = None
    currency: Optional[str] = None
    is_derived: bool = False
    derived_from: Tuple[str, ...] = field(default_factory=tuple)


def _period_to_dict(period: AnalyticsPeriod) -> dict:
    return {"start": period.start, "end": period.end, "timezone": period.timezone}


def _observation_to_dict(observation: AnalyticsObservation) -> dict:
    return {
        "metric": observation.metric,
        "value": observation.value,
        "unit": observation.unit,
        "platform": observation.platform,
        "source": observation.source,
        "source_reference": observation.source_reference,
        "observed_at": observation.observed_at,
        "period": _period_to_dict(observation.period) if observation.period is not None else None,
        "currency": observation.currency,
        "is_derived": observation.is_derived,
        "derived_from": list(observation.derived_from),
    }


def compute_observations_hash(observations: Tuple[AnalyticsObservation, ...]) -> str:
    """
    Independent hash covering ONLY `observations` -- deliberately
    SEPARATE from `compute_analytics_artifact_hash()` (P3.9, UNCHANGED)
    so extending observation-level integrity never touches the hash
    P3.9's OptimizationAgent already verifies. Sorted by a stable
    composite key so incidental input ordering never changes the hash.
    """

    canonical_list = sorted(
        (_observation_to_dict(o) for o in observations),
        key=lambda d: (d["metric"], d["source_reference"], d["observed_at"] or ""),
    )
    canonical_json = json.dumps(canonical_list, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# COLLECTION PROFILE (P3.10 Section 13) -- deliberately minimal.
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class AnalyticsCollectionProfile:
    name: str = "default"


DEFAULT_COLLECTION_PROFILE = AnalyticsCollectionProfile()
ALLOWED_COLLECTION_PROFILES = frozenset({"default"})


class AnalyticsAgentStatus(str, Enum):
    """
    Section 22 -- explicitly excludes PUBLISHED/EXECUTED/APPLIED: this
    agent only ever observes/normalizes/reports.
    """

    NOT_COLLECTED = "NOT_COLLECTED"
    REJECTED = "REJECTED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTEGRITY_FAILURE = "INTEGRITY_FAILURE"
    PARTIAL = "PARTIAL"
    COLLECTED = "COLLECTED"


# ----------------------------------------------------------------------
# INPUT CONTRACT (P3.10 Section 7)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class AnalyticsAgentInput:
    mission_id: str
    platform: str
    period: AnalyticsPeriod
    observations: Tuple[AnalyticsObservation, ...]
    content_artifact: Optional[ContentArtifact] = None
    script_artifact: Optional[ScriptArtifact] = None
    quality_artifact: Optional[QualityArtifact] = None
    publication_artifact: Optional[PublicationArtifact] = None
    collection_profile: Optional[AnalyticsCollectionProfile] = None
    constraints: Tuple[str, ...] = field(default_factory=tuple)


# ----------------------------------------------------------------------
# OUTPUT CONTRACT
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class AnalyticsAgentOutput:
    mission_id: str
    status: AnalyticsAgentStatus
    analytics_artifact: Optional[AnalyticsArtifact] = None
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    errors: Tuple[str, ...] = field(default_factory=tuple)
    producer_agent: str = AGENT_ID
    producer_version: str = AGENT_VERSION
    contract_version: int = CONTRACT_VERSION


# ----------------------------------------------------------------------
# ANALYTICS ENGINE (P3.10 Section 13/14) -- AnalyticsAgent = validation,
# integrity, orchestration, hashing; AnalyticsEngine = normalization/
# canonicalization/aggregation ONLY. NO intelligent analysis here --
# that is OptimizationAgent's exclusive responsibility (P3.9).
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class AnalyticsCollectionContext:
    platform: str
    period: AnalyticsPeriod
    observations: Tuple[AnalyticsObservation, ...]
    profile: AnalyticsCollectionProfile


@dataclass(frozen=True)
class AnalyticsCollectionResult:
    metrics: Tuple[MetricValue, ...]
    derived_observations: Tuple[AnalyticsObservation, ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    partial: bool = False


class AnalyticsEngine(ABC):
    """Contract every analytics backend (deterministic V1, a future
    platform-adapter-backed engine) must satisfy. Never called before
    validation AND integrity have already passed."""

    @abstractmethod
    def collect(self, context: AnalyticsCollectionContext) -> AnalyticsCollectionResult:
        raise NotImplementedError


class DeterministicAnalyticsEngine(AnalyticsEngine):
    """
    V1 default engine: purely local, rule-based, deterministic. No
    random, no LLM, no network, no platform API.

    AGGREGATION RULE (Section 18), documented exactly: if MORE THAN ONE
    observation exists for the same metric name (within this
    platform/period), aggregation is NOT SAFE (summing views is fine,
    summing completion_rate or CTR is meaningless) -- rather than guess,
    that metric is EXCLUDED from the canonical `metrics` tuple entirely,
    a warning is recorded, and the caller (AnalyticsAgent) marks the
    result PARTIAL. The raw observations remain fully available,
    unaltered, in `AnalyticsArtifact.observations` for a future consumer
    to resolve.

    NORMALIZATION (Section 12/13): a ratio-type metric reported with
    `unit="percentage"` is divided by 100 to produce the canonical ratio
    value -- the ONLY normalization this engine performs, always
    explicit, always documented, never silent.

    DERIVED METRICS (Section 19), documented exactly:
    `engagement_rate = (likes + comments + shares) / impressions`,
    computed ONLY if all four are present as single (non-ambiguous)
    canonical metrics AND `impressions != 0` (never divides by zero).
    The result is a NEW `AnalyticsObservation` with `is_derived=True`
    and `derived_from=("likes","comments","shares","impressions")` --
    it is NEVER injected into the canonical `metrics` tuple (Section 20:
    a derived metric must never be presented as directly platform-
    reported); it exists only within `observations`.

    Currency metrics (`revenue`) are NEVER included in the canonical
    `metrics` tuple (which has no currency slot) -- they remain
    observations-only, preserving `amount`+`currency` without ever
    converting currencies (Section 35).
    """

    def collect(self, context: AnalyticsCollectionContext) -> AnalyticsCollectionResult:
        warnings: List[str] = []
        partial = False

        by_metric: Dict[str, List[AnalyticsObservation]] = {}
        for observation in context.observations:
            if observation.metric in CURRENCY_METRIC_NAMES:
                continue
            by_metric.setdefault(observation.metric, []).append(observation)

        metrics_list: List[MetricValue] = []
        for name in sorted(by_metric.keys()):
            group = by_metric[name]
            if len(group) > 1:
                warnings.append(
                    f"metric '{name}' has {len(group)} observations for "
                    f"platform '{context.platform}' in this period -- "
                    f"aggregation is not safe (unclear whether to sum, "
                    f"average, or take the latest); excluding it from "
                    f"canonical metrics rather than guessing."
                )
                partial = True
                continue

            observation = group[0]
            value = observation.value
            if observation.unit == "percentage" and name in EXTENDED_RATIO_METRIC_NAMES:
                value = value / 100.0
            metrics_list.append(MetricValue(name=name, value=value))

        canonical = {m.name: m.value for m in metrics_list}
        derived_observations: List[AnalyticsObservation] = []
        required = ("likes", "comments", "shares", "impressions")
        if all(name in canonical for name in required) and canonical["impressions"] != 0:
            engagement_rate = (
                canonical["likes"] + canonical["comments"] + canonical["shares"]
            ) / canonical["impressions"]
            derived_observations.append(
                AnalyticsObservation(
                    metric="engagement_rate",
                    value=engagement_rate,
                    unit="ratio",
                    platform=context.platform,
                    source=AnalyticsSourceTrust.DERIVED.value,
                    source_reference="derived:(likes+comments+shares)/impressions",
                    is_derived=True,
                    derived_from=required,
                )
            )

        return AnalyticsCollectionResult(
            metrics=tuple(metrics_list),
            derived_observations=tuple(derived_observations),
            warnings=tuple(warnings),
            partial=partial,
        )


# ----------------------------------------------------------------------
# VALIDATION (P3.10 Sections 15/16/17/33/34) -- structurally separate
# tiers, never merged.
# ----------------------------------------------------------------------


def _validate_optional_artifact(
    label: str, artifact, expected_cls, expected_type: str, mission_id: str, supported_versions: frozenset
) -> List[str]:
    if artifact is None:
        return []
    if not isinstance(artifact, expected_cls):
        return [f"{label} is not a valid {expected_cls.__name__} instance."]
    errors: List[str] = []
    if artifact.artifact_type != expected_type:
        errors.append(f"{label}.artifact_type '{artifact.artifact_type}' is not '{expected_type}'.")
    if artifact.mission_id != mission_id:
        errors.append(
            f"{label}.mission_id '{artifact.mission_id}' does not match this "
            f"AnalyticsAgentInput.mission_id '{mission_id}' -- refusing to "
            f"consume an artifact belonging to a different mission."
        )
    if artifact.status != "FINAL":
        errors.append(f"{label}.status '{artifact.status}' is not 'FINAL'.")
    if artifact.contract_version not in supported_versions:
        errors.append(
            f"{label}.contract_version {artifact.contract_version} is not "
            f"supported (supported: {sorted(supported_versions)})."
        )
    return errors


def _validate_dependencies(agent_input: AnalyticsAgentInput) -> List[str]:
    errors: List[str] = []

    if not agent_input.observations:
        errors.append("observations is missing or empty; at least one observation is required.")

    errors.extend(
        _validate_optional_artifact(
            "content_artifact", agent_input.content_artifact, ContentArtifact, CONTENT_ARTIFACT_TYPE,
            agent_input.mission_id, SUPPORTED_CONTENT_CONTRACT_VERSIONS,
        )
    )
    errors.extend(
        _validate_optional_artifact(
            "script_artifact", agent_input.script_artifact, ScriptArtifact, SCRIPT_ARTIFACT_TYPE,
            agent_input.mission_id, SUPPORTED_CONTENT_CONTRACT_VERSIONS,
        )
    )
    errors.extend(
        _validate_optional_artifact(
            "quality_artifact", agent_input.quality_artifact, QualityArtifact, QUALITY_ARTIFACT_TYPE,
            agent_input.mission_id, SUPPORTED_QUALITY_CONTRACT_VERSIONS,
        )
    )
    errors.extend(
        _validate_optional_artifact(
            "publication_artifact", agent_input.publication_artifact, PublicationArtifact,
            PUBLICATION_ARTIFACT_TYPE, agent_input.mission_id, SUPPORTED_PUBLISHING_CONTRACT_VERSIONS,
        )
    )

    return errors


def _validate_period(label: str, period: AnalyticsPeriod) -> List[str]:
    errors: List[str] = []
    if period.timezone not in ALLOWED_TIMEZONES:
        errors.append(f"{label}.timezone '{period.timezone}' is invalid (allowed: {sorted(ALLOWED_TIMEZONES)}).")
    try:
        start = datetime.fromisoformat(period.start)
        end = datetime.fromisoformat(period.end)
        if start > end:
            errors.append(f"{label}.start ({period.start}) is after {label}.end ({period.end}).")
    except (TypeError, ValueError):
        errors.append(f"{label} has an invalid start/end ISO 8601 datetime.")
    return errors


def _validate_observation(index: int, observation: AnalyticsObservation, top_platform: str) -> List[str]:
    errors: List[str] = []
    label = f"observations[{index}]"

    if observation.metric not in ALL_KNOWN_NUMERIC_METRIC_NAMES and observation.metric not in CURRENCY_METRIC_NAMES:
        errors.append(
            f"{label}.metric '{observation.metric}' is unknown "
            f"(allowed: {sorted(ALL_KNOWN_NUMERIC_METRIC_NAMES | CURRENCY_METRIC_NAMES)}) "
            f"-- unrecognized metrics are rejected rather than silently "
            f"accepted as an untyped custom metric."
        )
        return errors  # cannot meaningfully validate unit/value domain for an unknown metric

    if not isinstance(observation.value, (int, float)) or isinstance(observation.value, bool):
        errors.append(f"{label}.value {observation.value!r} is not numeric.")
        return errors

    if observation.unit not in ALLOWED_UNITS:
        errors.append(f"{label}.unit '{observation.unit}' is invalid (allowed: {sorted(ALLOWED_UNITS)}).")
        return errors

    expected_unit = METRIC_CANONICAL_UNIT[observation.metric]
    is_ratio_as_percentage = expected_unit == "ratio" and observation.unit == "percentage"
    if observation.unit != expected_unit and not is_ratio_as_percentage:
        errors.append(
            f"{label}.unit '{observation.unit}' does not match the "
            f"canonical unit '{expected_unit}' for metric "
            f"'{observation.metric}' (a ratio metric may also be reported "
            f"as 'percentage', normalized explicitly by /100 -- no other "
            f"substitution is accepted)."
        )
        return errors

    if expected_unit == "count" and observation.value < 0:
        errors.append(f"{label}.value {observation.value} must not be negative for a count metric.")
    elif expected_unit == "seconds" and observation.value < 0:
        errors.append(f"{label}.value {observation.value} must not be negative for a duration metric.")
    elif observation.unit == "ratio" and not (0.0 <= observation.value <= 1.0):
        errors.append(f"{label}.value {observation.value} must be within [0.0, 1.0] for a ratio.")
    elif observation.unit == "percentage" and not (0.0 <= observation.value <= 100.0):
        errors.append(f"{label}.value {observation.value} must be within [0.0, 100.0] for a percentage.")
    elif expected_unit == "currency" and observation.value < 0:
        errors.append(f"{label}.value {observation.value} must not be negative for revenue.")

    if expected_unit == "currency" and not observation.currency:
        errors.append(f"{label}.currency is required when metric is '{observation.metric}'.")

    if observation.platform != top_platform:
        errors.append(
            f"{label}.platform '{observation.platform}' does not match "
            f"this AnalyticsAgentInput.platform '{top_platform}'."
        )

    if observation.source not in {s.value for s in AnalyticsSourceTrust}:
        errors.append(f"{label}.source '{observation.source}' is invalid.")

    if not observation.source_reference or not observation.source_reference.strip():
        errors.append(f"{label}.source_reference is missing or empty -- every observation must be traceable.")

    if observation.period is not None:
        errors.extend(_validate_period(f"{label}.period", observation.period))

    return errors


def _validate_analytics_input(agent_input: AnalyticsAgentInput) -> List[str]:
    errors: List[str] = []

    if not isinstance(agent_input.mission_id, str) or not agent_input.mission_id.strip():
        errors.append("mission_id is missing or empty.")

    if agent_input.platform not in ALLOWED_PLATFORMS:
        errors.append(f"platform '{agent_input.platform}' is invalid (allowed: {sorted(ALLOWED_PLATFORMS)}).")

    errors.extend(_validate_period("period", agent_input.period))

    profile = agent_input.collection_profile
    if profile is not None:
        if not isinstance(profile, AnalyticsCollectionProfile):
            errors.append("collection_profile is not a valid AnalyticsCollectionProfile instance.")
        elif profile.name not in ALLOWED_COLLECTION_PROFILES:
            errors.append(
                f"collection_profile.name '{profile.name}' is invalid "
                f"(allowed: {sorted(ALLOWED_COLLECTION_PROFILES)})."
            )

    for index, observation in enumerate(agent_input.observations):
        errors.extend(_validate_observation(index, observation, agent_input.platform))

    return errors


def _integrity_errors(agent_input: AnalyticsAgentInput) -> List[str]:
    errors: List[str] = []

    content = agent_input.content_artifact
    if content is not None:
        try:
            recomputed = compute_content_artifact_hash(
                mission_id=content.mission_id, concept=content.concept, angle=content.angle,
                hook=content.hook, title=content.title, cta=content.cta,
                target_platforms=content.target_platforms, language=content.language,
                tone=content.tone, content_format=content.content_format,
                constraints=content.constraints, contract_version=content.contract_version,
                source_strategy_content_hash=content.source_strategy_content_hash,
            )
            if recomputed != content.content_hash:
                errors.append("content_artifact.content_hash does not match a recomputed hash of its own fields.")
        except Exception as error:  # noqa: BLE001
            errors.append(f"content_artifact integrity could not be verified: {error}")

    script = agent_input.script_artifact
    if script is not None and content is not None:
        try:
            recomputed = compute_script_artifact_hash(
                mission_id=script.mission_id, scenes=script.scenes,
                total_duration_target=script.total_duration_target, language=script.language,
                contract_version=script.contract_version, source_content_content_hash=content.content_hash,
            )
            if recomputed != script.content_hash:
                errors.append("script_artifact.content_hash does not match a recomputed hash bound to the supplied content_artifact.")
        except Exception as error:  # noqa: BLE001
            errors.append(f"script_artifact integrity could not be verified: {error}")

    quality = agent_input.quality_artifact
    if quality is not None:
        try:
            recomputed = compute_quality_artifact_hash(
                mission_id=quality.mission_id, quality_status=quality.quality_status, score=quality.score,
                findings=quality.findings, evaluated_artifacts=quality.evaluated_artifacts,
                profile=quality.profile, contract_version=quality.contract_version,
            )
            if recomputed != quality.content_hash:
                errors.append("quality_artifact.content_hash does not match a recomputed hash of its own fields.")
        except Exception as error:  # noqa: BLE001
            errors.append(f"quality_artifact integrity could not be verified: {error}")

    publication = agent_input.publication_artifact
    if publication is not None:
        try:
            recomputed = compute_publication_artifact_hash(
                mission_id=publication.mission_id, publication_status=publication.publication_status,
                platforms=publication.platforms, publication_items=publication.publication_items,
                media_reference=publication.media_reference, schedule=publication.schedule,
                profile=publication.profile, evaluated_artifacts=publication.evaluated_artifacts,
                contract_version=publication.contract_version,
            )
            if recomputed != publication.content_hash:
                errors.append("publication_artifact.content_hash does not match a recomputed hash of its own fields.")
        except Exception as error:  # noqa: BLE001
            errors.append(f"publication_artifact integrity could not be verified: {error}")

    return errors


# ----------------------------------------------------------------------
# IDEMPOTENCY (P3.10 Section 28)
# ----------------------------------------------------------------------


def compute_analytics_idempotency_key(agent_input: AnalyticsAgentInput) -> str:
    def _ref(artifact) -> dict:
        if artifact is None:
            return {"artifact_id": None, "version": None, "content_hash": None}
        return {"artifact_id": artifact.artifact_id, "version": artifact.version, "content_hash": artifact.content_hash}

    profile = agent_input.collection_profile or DEFAULT_COLLECTION_PROFILE

    canonical = {
        "mission_id": agent_input.mission_id,
        "platform": agent_input.platform,
        "period": _period_to_dict(agent_input.period),
        "observations": sorted(
            (_observation_to_dict(o) for o in agent_input.observations),
            key=lambda d: (d["metric"], d["source_reference"], d["observed_at"] or ""),
        ),
        "content": _ref(agent_input.content_artifact),
        "script": _ref(agent_input.script_artifact),
        "quality": _ref(agent_input.quality_artifact),
        "publication": _ref(agent_input.publication_artifact),
        "profile": {"name": profile.name},
        "constraints": list(agent_input.constraints),
    }
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# ANALYTICS AGENT (P3.10 Section 5)
# ----------------------------------------------------------------------


class AnalyticsAgent:
    """
    AI DIRECTOR — Analytics Agent v1.0 (P3.10)

    Depends on `agents.optimization_agent` for the REAL AnalyticsArtifact
    contract it produces, on `agents.content_agent`/`agents.quality_agent`/
    `agents.publishing_agent` for optional cross-reference validation, and
    on `agents.strategy_agent` ONLY for the platform whitelist -- no
    dependency on Higgsfield, any P2 gate/authority module, the Director,
    any event bus, or any network/social-platform library of any kind.
    """

    def __init__(self, engine: Optional[AnalyticsEngine] = None):
        self.engine = engine or DeterministicAnalyticsEngine()

    def run(self, agent_input: AnalyticsAgentInput) -> AnalyticsAgentOutput:
        """
        Order: (1) dependency validation -> REJECTED; (2) this agent's
        own input + observation validation -> VALIDATION_ERROR; (3)
        integrity (hash recomputation across every cross-referenced
        artifact) -> INTEGRITY_FAILURE, WITH a minimal AnalyticsArtifact
        recording the fact; (4) engine collection -> PARTIAL / COLLECTED,
        WITH a fully populated AnalyticsArtifact. Never mutates any input
        artifact. Never emits an event. Never constructs any
        authorization object. Never constructs a "PUBLISHED" status.
        """

        mission_id = agent_input.mission_id if isinstance(agent_input.mission_id, str) else ""

        dependency_errors = _validate_dependencies(agent_input)
        if dependency_errors:
            return AnalyticsAgentOutput(mission_id=mission_id, status=AnalyticsAgentStatus.REJECTED, errors=tuple(dependency_errors))

        input_errors = _validate_analytics_input(agent_input)
        if input_errors:
            return AnalyticsAgentOutput(mission_id=mission_id, status=AnalyticsAgentStatus.VALIDATION_ERROR, errors=tuple(input_errors))

        integrity_errors = _integrity_errors(agent_input)
        if integrity_errors:
            return self._build_output(
                mission_id=agent_input.mission_id,
                status=AnalyticsAgentStatus.INTEGRITY_FAILURE,
                platform=agent_input.platform,
                period=agent_input.period,
                metrics=(),
                observations=(),
                errors=tuple(integrity_errors),
            )

        profile = agent_input.collection_profile or DEFAULT_COLLECTION_PROFILE
        context = AnalyticsCollectionContext(
            platform=agent_input.platform, period=agent_input.period,
            observations=agent_input.observations, profile=profile,
        )
        result = self.engine.collect(context)

        final_observations = tuple(agent_input.observations) + tuple(result.derived_observations)
        status = AnalyticsAgentStatus.PARTIAL if result.warnings else AnalyticsAgentStatus.COLLECTED

        return self._build_output(
            mission_id=agent_input.mission_id,
            status=status,
            platform=agent_input.platform,
            period=agent_input.period,
            metrics=result.metrics,
            observations=final_observations,
            warnings=result.warnings,
        )

    @staticmethod
    def _build_output(
        mission_id: str,
        status: AnalyticsAgentStatus,
        platform: str,
        period: AnalyticsPeriod,
        metrics: Tuple[MetricValue, ...],
        observations: Tuple[AnalyticsObservation, ...],
        warnings: Tuple[str, ...] = (),
        errors: Tuple[str, ...] = (),
    ) -> AnalyticsAgentOutput:
        artifact_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()

        # UNCHANGED P3.9 function -- exactly 5 parameters, exactly the
        # same canonical dict as before this phase (Section 42).
        content_hash = compute_analytics_artifact_hash(
            mission_id=mission_id, platform=platform, period=period,
            metrics=metrics, contract_version=ANALYTICS_CONTRACT_VERSION,
        )

        source_references = tuple(sorted({o.source_reference for o in observations}))
        observations_hash = compute_observations_hash(observations)

        analytics_artifact = AnalyticsArtifact(
            artifact_id=artifact_id,
            artifact_type=ANALYTICS_ARTIFACT_TYPE,
            mission_id=mission_id,
            created_at=created_at,
            version=ANALYTICS_ARTIFACT_VERSION,
            status="FINAL",
            platform=platform,
            period=period,
            metrics=metrics,
            producer_agent=AGENT_ID,
            producer_version=AGENT_VERSION,
            contract_version=ANALYTICS_CONTRACT_VERSION,
            content_hash=content_hash,
            observations=observations,
            source_references=source_references,
            observations_hash=observations_hash,
        )

        return AnalyticsAgentOutput(
            mission_id=mission_id, status=status, analytics_artifact=analytics_artifact,
            warnings=warnings, errors=errors,
        )
