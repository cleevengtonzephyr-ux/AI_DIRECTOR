"""
AI DIRECTOR — Optimization Agent v1.0 (Phase P3.9)

Sixth business agent of the future multi-agent AI Director, built
directly against the REAL `agents/content_agent.py` (P3.6),
`agents/quality_agent.py` (P3.7), and `agents/publishing_agent.py`
(P3.8) contracts -- `ContentArtifact`, `QualityArtifact`,
`PublicationArtifact`, their `*_TYPE`/`CONTRACT_VERSION` constants,
their real `compute_*_hash()` functions, and `EvaluatedArtifactReference`
(reused directly from `agents.quality_agent`, never redefined) -- plus
`agents.publishing_agent.ALLOWED_TIMEZONES` (reused directly rather than
a second, divergent timezone whitelist). All four upstream agent
modules, plus their test files, were re-read from disk in full before
writing a single line of this module.

ANALYTICS CONTRACT AUDIT (Section 2/6) -- CONFIRMED ABSENT: a
repository-wide, case-insensitive search for `AnalyticsArtifact`,
`AnalyticsAgent`, `analytics`, `metrics`, `engagement`, `retention`,
`views`, `likes`, `comments`, `shares`, `watch time`, `CTR`,
`conversion`, `publication results` found ZERO existing analytics
contract, agent, or metrics model anywhere in this repository (the only
incidental hits were an unrelated French "conversion entre niveaux"
sentence in `agents/production_activation_boundary.py` and this
project's own prose about what ContentAgent does not do). Per
instruction, no complex analytics architecture is invented here: this
module defines the SMALLEST possible `AnalyticsArtifact` contract
(Section "MINIMAL ANALYTICS CONTRACT" below) sufficient for
OptimizationAgent to consume, explicitly documented as a placeholder a
future dedicated `AnalyticsAgent` phase should own and may need to
extend. A repository-wide search for `OptimizationAgent`, `optimization`,
`optimizer`, `recommendation`, `feedback loop`, `learning`, `adaptation`,
`strategy update` similarly found nothing to duplicate or replace.

THE SINGLE MOST IMPORTANT DISTINCTION IN THIS MODULE (Section 4):

    RECOMMENDATION  !=  COMMAND
    RECOMMENDATION  !=  EXECUTION
    RECOMMENDATION  !=  AUTHORITY

This agent produces `OptimizationRecommendation`s with `status=PROPOSED`
ONLY -- it can never construct a recommendation with any other status
(`ACCEPTED`/`APPLIED`/`REJECTED` all imply an external authority this
agent does not have), never mutates any input artifact, never calls
Higgsfield/any provider/any network, and never creates any human or
production authorization. See tests/test_optimization_agent.py::
SecurityTests, AST-verified exactly as P3.5-P3.8 were, with the
docstring/identifier false-positive lesson from P3.5/P3.8 applied from
the start (Section 28/43).

NO FABRICATED DATA (Section 7/10), the second most important rule:
a metric that is not present in `AnalyticsArtifact.metrics` is ABSENT,
never coerced to `0`. `0` means "observed value of exactly zero";
absence means "no data available for this metric." This distinction is
enforced structurally: `metrics` is a tuple of `(name, value)` pairs
where a name simply not appearing means ABSENT -- there is no
`Optional[float]` sentinel that could be misread.

CAUSALITY SAFETY (Section 15/17): every recommendation's `rationale`
is built from a fixed three-part template -- OBSERVATION (what the data
shows), INTERPRETATION (association, explicitly never causation), and
RECOMMENDATION (the proposed action) -- and never uses a causal verb
("caused", "resulted in", "because of") to describe what is only a
correlation.

AUTHORITY (P3.2 Section 14 / P3.9 Section 4): RECOMMEND. Can analyze
input data, detect trends within fixed deterministic thresholds,
identify weaknesses, and produce `OptimizationArtifact` -- cannot apply
a recommendation, modify any existing artifact, publish, generate, call
a provider, create any authorization, or call an event bus.

DETERMINISM: identical discipline to every prior agent in this series --
no `random`, no LLM call, no network/web call, no external
trend/benchmark API. Only `created_at` and `artifact_id` (technical,
never fed into content_hash) vary between calls with the same input.
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
    ContentArtifact,
    compute_content_artifact_hash,
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
    EvaluatedArtifactReference,
    QualityArtifact,
    compute_quality_artifact_hash,
)

# ----------------------------------------------------------------------
# MINIMAL ANALYTICS CONTRACT (P3.9 Section 2/6) -- PLACEHOLDER.
#
# No AnalyticsAgent/AnalyticsArtifact exists anywhere in this repository
# today (confirmed by repository-wide search, module docstring above).
# This is the SMALLEST contract that lets OptimizationAgent function; a
# future dedicated AnalyticsAgent phase owns producing real instances of
# it and may need to extend `ANALYTICS_CONTRACT_VERSION` if the shape
# changes -- this module never assumes more than what is defined here.
# ----------------------------------------------------------------------

ANALYTICS_ARTIFACT_TYPE = "AnalyticsArtifact"
ANALYTICS_CONTRACT_VERSION = 1
ANALYTICS_ARTIFACT_VERSION = 1

# Documented example metric names (Section 6) -- NOT an exhaustive or
# enforced whitelist: a platform may report a metric not listed here,
# and it is still a legitimate MetricValue. These names are used only to
# apply KNOWN domain rules (non-negative / ratio) where applicable.
NON_NEGATIVE_METRIC_NAMES = frozenset(
    {"views", "impressions", "likes", "comments", "shares", "saves", "watch_time", "conversions"}
)
RATIO_METRIC_NAMES = frozenset({"completion_rate", "click_through_rate"})


@dataclass(frozen=True)
class MetricValue:
    """
    One observed metric. A metric NOT present in an
    `AnalyticsArtifact.metrics` tuple is ABSENT -- there is no `None`/
    sentinel value representing absence; absence is represented purely
    by the metric's name not appearing at all (Section 7).
    """

    name: str
    value: float


@dataclass(frozen=True)
class AnalyticsPeriod:
    start: str  # ISO 8601
    end: str  # ISO 8601
    timezone: str


@dataclass(frozen=True)
class AnalyticsArtifact:
    artifact_id: str
    artifact_type: str
    mission_id: str
    created_at: str
    version: int
    status: str  # Artifact lifecycle status (DRAFT|FINAL|SUPERSEDED)

    platform: str
    period: AnalyticsPeriod
    metrics: Tuple[MetricValue, ...]

    producer_agent: str
    producer_version: str
    contract_version: int

    content_hash: str

    # ------------------------------------------------------------------
    # P3.10 ADDITIVE EXTENSION -- backward-compatible with P3.9.
    #
    # Three new OPTIONAL fields, appended at the end with defaults, so
    # every P3.9 construction of AnalyticsArtifact (which always uses
    # keyword arguments and never supplies these three) remains valid
    # and unchanged. `AnalyticsObservation` is defined in
    # agents/analytics_agent.py (P3.10), never imported here -- this
    # module's `from __future__ import annotations` (already present,
    # P3.9) makes this a lazily-evaluated string annotation that is
    # never resolved at runtime by dataclasses, so no import is needed
    # and no circular dependency is created (optimization_agent.py is
    # the contract's home; analytics_agent.py imports FROM it, not the
    # other way around).
    #
    # `content_hash` above is computed by `compute_analytics_artifact_
    # hash()` (UNCHANGED, still exactly 5 parameters, still exactly the
    # same canonical dict as P3.9) and therefore NEVER covers these
    # three fields -- deliberately, to guarantee byte-identical hash
    # computation with P3.9 and zero regression risk. `observations_hash`
    # (below) is a SEPARATE, independent hash covering `observations`
    # only, computed by `agents.analytics_agent.compute_observations_
    # hash()`, verified by that module's own integrity check -- never by
    # OptimizationAgent, which continues to verify only `content_hash`
    # exactly as it did in P3.9.
    # ------------------------------------------------------------------
    observations: Tuple["AnalyticsObservation", ...] = field(default_factory=tuple)
    source_references: Tuple[str, ...] = field(default_factory=tuple)
    observations_hash: str = ""


def _metrics_to_list(metrics: Tuple[MetricValue, ...]) -> List[dict]:
    return [{"name": m.name, "value": m.value} for m in metrics]


def _period_to_dict(period: AnalyticsPeriod) -> dict:
    return {"start": period.start, "end": period.end, "timezone": period.timezone}


def compute_analytics_artifact_hash(
    mission_id: str,
    platform: str,
    period: AnalyticsPeriod,
    metrics: Tuple[MetricValue, ...],
    contract_version: int,
) -> str:
    canonical = {
        "mission_id": mission_id,
        "platform": platform,
        "period": _period_to_dict(period),
        "metrics": sorted(_metrics_to_list(metrics), key=lambda m: m["name"]),
        "contract_version": contract_version,
    }
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _metric_value(metrics: Tuple[MetricValue, ...], name: str) -> Optional[float]:
    """Returns the metric's value, or None if ABSENT (not the same as 0)."""

    for metric in metrics:
        if metric.name == name:
            return metric.value
    return None


# ----------------------------------------------------------------------
# VERSIONING (P3.9 Section 22)
# ----------------------------------------------------------------------

AGENT_ID = "optimization-agent"
AGENT_VERSION = "1.0"
CONTRACT_VERSION = 1
OPTIMIZATION_ARTIFACT_TYPE = "OptimizationArtifact"
ARTIFACT_VERSION = 1

SUPPORTED_ANALYTICS_CONTRACT_VERSIONS = frozenset({ANALYTICS_CONTRACT_VERSION})
SUPPORTED_CONTENT_CONTRACT_VERSIONS = frozenset({CONTENT_CONTRACT_VERSION})
SUPPORTED_QUALITY_CONTRACT_VERSIONS = frozenset({QUALITY_CONTRACT_VERSION})
SUPPORTED_PUBLISHING_CONTRACT_VERSIONS = frozenset({PUBLISHING_CONTRACT_VERSION})

ALLOWED_OPTIMIZATION_PROFILES = frozenset(
    {"content", "engagement", "retention", "conversion", "platform"}
)


class OptimizationAgentStatus(str, Enum):
    """
    Doubles as `OptimizationArtifact.status`'s meaningful outcome value
    via the `optimization_status` field below (same reasoning as every
    prior agent's shared status enum). `NOT_EVALUATED` is reserved
    vocabulary (never returned today). Explicitly excludes `EXECUTED`/
    `APPLIED`/`PUBLISHED` (P3.9 Section 19) -- this agent never produces
    or implies any of those outcomes.
    """

    NOT_EVALUATED = "NOT_EVALUATED"
    REJECTED = "REJECTED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTEGRITY_FAILURE = "INTEGRITY_FAILURE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    READY = "READY"
    WARNING = "WARNING"


class OptimizationRecommendationPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class OptimizationRecommendationStatus(str, Enum):
    """
    Full vocabulary defined for forward compatibility with a future
    external review process (a human or a future authority layer could
    set ACCEPTED/REJECTED/APPLIED elsewhere) -- but THIS module's code
    contains no path that ever constructs anything other than
    `PROPOSED` (verified by tests/test_optimization_agent.py, both
    behaviorally and via AST: no `ACCEPTED`/`APPLIED` literal is ever
    the argument to an `OptimizationRecommendation(...)` construction
    in this file).
    """

    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"


# ----------------------------------------------------------------------
# THRESHOLDS / PROFILE (P3.9 Section 11/17) -- explicit, documented,
# versioned via CONTRACT_VERSION, never hidden.
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class OptimizationThresholds:
    low_completion_rate: float = 0.30
    low_click_through_rate: float = 0.02
    decline_ratio_threshold: float = 0.10
    low_sample_size_views: int = 100


@dataclass(frozen=True)
class OptimizationProfile:
    name: str = "content"
    thresholds: OptimizationThresholds = field(default_factory=OptimizationThresholds)


DEFAULT_OPTIMIZATION_PROFILE = OptimizationProfile()


def _thresholds_to_dict(thresholds: OptimizationThresholds) -> dict:
    return {
        "low_completion_rate": thresholds.low_completion_rate,
        "low_click_through_rate": thresholds.low_click_through_rate,
        "decline_ratio_threshold": thresholds.decline_ratio_threshold,
        "low_sample_size_views": thresholds.low_sample_size_views,
    }


def _profile_to_dict(profile: OptimizationProfile) -> dict:
    return {"name": profile.name, "thresholds": _thresholds_to_dict(profile.thresholds)}


# Confidence formula constants (P3.9 Section 14) -- documented exactly,
# never an arbitrary/hidden number. Confidence NEVER reaches 1.0: this
# V1 engine never claims artificial certainty.
BASE_CONFIDENCE_SINGLE_METRIC = 0.5
BASE_CONFIDENCE_WITH_COMPARISON = 0.7
LOW_SAMPLE_SIZE_PENALTY = 0.2
MAX_CONFIDENCE = 0.9
MIN_CONFIDENCE = 0.1

# Below this confidence, the overall OptimizationAgentStatus becomes
# WARNING rather than READY, even though recommendations were produced.
WARNING_CONFIDENCE_THRESHOLD = 0.6


# ----------------------------------------------------------------------
# INPUT CONTRACT (P3.9 Section 5)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class OptimizationAgentInput:
    mission_id: str
    analytics_artifact: AnalyticsArtifact  # REQUIRED -- Section 5: no
    # other input in this V1 (ContentArtifact/QualityArtifact/
    # PublicationArtifact) carries any performance metric at all
    # (confirmed by re-reading their real contracts), so there is no
    # scenario today where "sufficient performance data" could come
    # from elsewhere.
    previous_analytics_artifact: Optional[AnalyticsArtifact] = None
    quality_artifact: Optional[QualityArtifact] = None
    content_artifact: Optional[ContentArtifact] = None
    publication_artifact: Optional[PublicationArtifact] = None
    optimization_profile: Optional[OptimizationProfile] = None
    constraints: Tuple[str, ...] = field(default_factory=tuple)


# ----------------------------------------------------------------------
# RECOMMENDATION / EVIDENCE (P3.9 Section 12/13)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class OptimizationEvidence:
    metric: str
    observed_value: float
    source_artifact_id: str
    source_artifact_type: str
    source_artifact_hash: str
    comparison_value: Optional[float] = None


def _evidence_to_dict(evidence: OptimizationEvidence) -> dict:
    return {
        "metric": evidence.metric,
        "observed_value": evidence.observed_value,
        "comparison_value": evidence.comparison_value,
        "source_artifact_id": evidence.source_artifact_id,
        "source_artifact_type": evidence.source_artifact_type,
        "source_artifact_hash": evidence.source_artifact_hash,
    }


@dataclass(frozen=True)
class OptimizationRecommendation:
    recommendation_id: str
    category: str
    priority: OptimizationRecommendationPriority
    target: str
    action: str
    rationale: str
    evidence: Tuple[OptimizationEvidence, ...]
    expected_effect: str
    confidence: float
    status: OptimizationRecommendationStatus


def _recommendation_to_dict(recommendation: OptimizationRecommendation) -> dict:
    return {
        "recommendation_id": recommendation.recommendation_id,
        "category": recommendation.category,
        "priority": recommendation.priority.value,
        "target": recommendation.target,
        "action": recommendation.action,
        "rationale": recommendation.rationale,
        "evidence": [_evidence_to_dict(e) for e in recommendation.evidence],
        "expected_effect": recommendation.expected_effect,
        "confidence": recommendation.confidence,
        "status": recommendation.status.value,
    }


def _build_rationale(observation: str, interpretation: str, recommendation_text: str) -> str:
    """
    Fixed three-part template (P3.9 Section 15/17) -- never a causal
    claim. `interpretation` must describe an ASSOCIATION, never a cause;
    this function does not itself forbid causal wording (that discipline
    lives in the call sites below, verified by tests scanning for banned
    causal verbs), but it does guarantee the three-part structure is
    always present and always labeled.
    """

    return (
        f"OBSERVATION: {observation} "
        f"INTERPRETATION: {interpretation} "
        f"RECOMMENDATION: {recommendation_text}"
    )


def _clamp_confidence(value: float) -> float:
    return max(MIN_CONFIDENCE, min(MAX_CONFIDENCE, value))


def _reference_to_dict(reference: EvaluatedArtifactReference) -> dict:
    return {
        "artifact_id": reference.artifact_id,
        "artifact_type": reference.artifact_type,
        "artifact_version": reference.artifact_version,
        "content_hash": reference.content_hash,
    }


# ----------------------------------------------------------------------
# OPTIMIZATION ARTIFACT (P3.9 Section 18)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class OptimizationArtifact:
    artifact_id: str
    artifact_type: str
    mission_id: str
    created_at: str
    version: int
    status: str  # Artifact lifecycle status (DRAFT|FINAL|SUPERSEDED),
    # distinct from `optimization_status` below.

    optimization_status: OptimizationAgentStatus
    platform: str
    profile: OptimizationProfile
    recommendations: Tuple[OptimizationRecommendation, ...]
    source_artifacts: Tuple[EvaluatedArtifactReference, ...]

    producer_agent: str
    producer_version: str
    contract_version: int

    content_hash: str


# ----------------------------------------------------------------------
# OUTPUT CONTRACT
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class OptimizationAgentOutput:
    mission_id: str
    status: OptimizationAgentStatus
    optimization_artifact: Optional[OptimizationArtifact] = None
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    errors: Tuple[str, ...] = field(default_factory=tuple)
    producer_agent: str = AGENT_ID
    producer_version: str = AGENT_VERSION
    contract_version: int = CONTRACT_VERSION


# ----------------------------------------------------------------------
# OPTIMIZATION ENGINE (P3.9 Section 9) -- OptimizationAgent = validation,
# integrity, orchestration, status decision, hashing; OptimizationEngine
# = the actual rule evaluation -> recommendations. Swappable without
# changing OptimizationAgent's own contract, mirroring every prior
# agent's engine split.
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class OptimizationEvaluationContext:
    analytics_artifact: AnalyticsArtifact
    previous_analytics_artifact: Optional[AnalyticsArtifact]
    quality_artifact: Optional[QualityArtifact]
    content_artifact: Optional[ContentArtifact]
    publication_artifact: Optional[PublicationArtifact]
    profile: OptimizationProfile


@dataclass(frozen=True)
class OptimizationEvaluationResult:
    recommendations: Tuple[OptimizationRecommendation, ...]
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    insufficient_data: bool = False
    insufficient_data_reason: Optional[str] = None


class OptimizationEngine(ABC):
    """Contract every optimization backend (deterministic V1, a future
    LLM-assisted engine) must satisfy. Never called before integrity has
    already been confirmed."""

    @abstractmethod
    def evaluate(self, context: OptimizationEvaluationContext) -> OptimizationEvaluationResult:
        raise NotImplementedError


class DeterministicOptimizationEngine(OptimizationEngine):
    """
    V1 default engine: purely local, threshold-based, deterministic. No
    random, no LLM, no network, no external benchmark/trend API. Same
    context always produces the same recommendations, in the same order.

    RULES (documented exactly, P3.9 Section 17 -- deliberately few):
    1. completion_rate present and < thresholds.low_completion_rate
       -> a "retention" recommendation about hook/pacing.
    2. click_through_rate present and < thresholds.low_click_through_rate
       -> a "conversion" recommendation about the call-to-action.
    3. IF a previous_analytics_artifact is supplied, for each of
       completion_rate/click_through_rate/views present in BOTH periods:
       if current < previous * (1 - decline_ratio_threshold) -> a
       "performance_decline" recommendation, with `comparison_value` set
       (Section 16). No baseline is ever invented when none is supplied.

    CONFIDENCE (Section 14): `BASE_CONFIDENCE_SINGLE_METRIC` (0.5) for a
    threshold-only finding, `BASE_CONFIDENCE_WITH_COMPARISON` (0.7) when
    a previous-period comparison independently corroborates the same
    metric's weakness, minus `LOW_SAMPLE_SIZE_PENALTY` (0.2) if `views`
    is present and below `thresholds.low_sample_size_views`, clamped to
    [`MIN_CONFIDENCE`, `MAX_CONFIDENCE`] (0.1-0.9) -- never 1.0.

    INSUFFICIENT DATA: if none of completion_rate/click_through_rate/
    views is present at all, no rule can be evaluated -- returns
    `insufficient_data=True` with zero recommendations, never a
    fabricated one.
    """

    def evaluate(self, context: OptimizationEvaluationContext) -> OptimizationEvaluationResult:
        analytics = context.analytics_artifact
        previous = context.previous_analytics_artifact
        thresholds = context.profile.thresholds
        warnings: List[str] = []

        completion_rate = _metric_value(analytics.metrics, "completion_rate")
        click_through_rate = _metric_value(analytics.metrics, "click_through_rate")
        views = _metric_value(analytics.metrics, "views")

        if completion_rate is None and click_through_rate is None and views is None:
            return OptimizationEvaluationResult(
                recommendations=(),
                insufficient_data=True,
                insufficient_data_reason=(
                    "None of completion_rate, click_through_rate, or views "
                    "is present in analytics_artifact.metrics -- no rule "
                    "in this engine can be evaluated without at least one "
                    "of them."
                ),
            )

        low_sample = views is not None and views < thresholds.low_sample_size_views
        if low_sample:
            warnings.append(
                f"views ({views}) is below the low-sample-size threshold "
                f"({thresholds.low_sample_size_views}) -- confidence of "
                f"any recommendation below is reduced accordingly."
            )

        if (
            context.content_artifact is not None
            and analytics.platform not in context.content_artifact.target_platforms
        ):
            warnings.append(
                f"analytics_artifact.platform '{analytics.platform}' is not "
                f"among content_artifact.target_platforms "
                f"{list(context.content_artifact.target_platforms)}."
            )

        raw: List[Tuple[str, OptimizationRecommendationPriority, str, str, str, Tuple[OptimizationEvidence, ...], str, float]] = []

        def _confidence(has_comparison: bool) -> float:
            base = BASE_CONFIDENCE_WITH_COMPARISON if has_comparison else BASE_CONFIDENCE_SINGLE_METRIC
            if low_sample:
                base -= LOW_SAMPLE_SIZE_PENALTY
            return _clamp_confidence(base)

        analytics_ref_id = analytics.artifact_id
        analytics_ref_hash = analytics.content_hash

        if completion_rate is not None and completion_rate < thresholds.low_completion_rate:
            evidence = (
                OptimizationEvidence(
                    metric="completion_rate",
                    observed_value=completion_rate,
                    source_artifact_id=analytics_ref_id,
                    source_artifact_type=ANALYTICS_ARTIFACT_TYPE,
                    source_artifact_hash=analytics_ref_hash,
                ),
            )
            raw.append(
                (
                    "retention",
                    OptimizationRecommendationPriority.HIGH
                    if completion_rate < thresholds.low_completion_rate / 2
                    else OptimizationRecommendationPriority.MEDIUM,
                    "hook_and_early_pacing",
                    "Consider shortening the hook or tightening early "
                    "pacing to reduce early drop-off.",
                    _build_rationale(
                        observation=(
                            f"completion_rate is {completion_rate} on "
                            f"platform '{analytics.platform}', below the "
                            f"configured threshold of "
                            f"{thresholds.low_completion_rate}."
                        ),
                        interpretation=(
                            "A low completion rate is associated with "
                            "viewers disengaging early in the video; this "
                            "does not by itself identify which specific "
                            "moment causes disengagement."
                        ),
                        recommendation_text=(
                            "Test a shorter or stronger hook and tighter "
                            "early pacing."
                        ),
                    ),
                    evidence,
                    "A stronger hook may increase completion_rate in a "
                    "future measurement period.",
                    _confidence(has_comparison=False),
                )
            )

        if click_through_rate is not None and click_through_rate < thresholds.low_click_through_rate:
            evidence = (
                OptimizationEvidence(
                    metric="click_through_rate",
                    observed_value=click_through_rate,
                    source_artifact_id=analytics_ref_id,
                    source_artifact_type=ANALYTICS_ARTIFACT_TYPE,
                    source_artifact_hash=analytics_ref_hash,
                ),
            )
            raw.append(
                (
                    "conversion",
                    OptimizationRecommendationPriority.MEDIUM,
                    "call_to_action",
                    "Consider testing a more explicit or urgent "
                    "call-to-action.",
                    _build_rationale(
                        observation=(
                            f"click_through_rate is {click_through_rate} "
                            f"on platform '{analytics.platform}', below "
                            f"the configured threshold of "
                            f"{thresholds.low_click_through_rate}."
                        ),
                        interpretation=(
                            "A low click-through rate is associated with "
                            "a call-to-action that is not prompting "
                            "action; this does not by itself identify why."
                        ),
                        recommendation_text=(
                            "Test a more explicit or more urgent "
                            "call-to-action."
                        ),
                    ),
                    evidence,
                    "A clearer call-to-action may increase "
                    "click_through_rate in a future measurement period.",
                    _confidence(has_comparison=False),
                )
            )

        if previous is not None:
            for metric_name in ("completion_rate", "click_through_rate", "views"):
                current_value = _metric_value(analytics.metrics, metric_name)
                previous_value = _metric_value(previous.metrics, metric_name)
                if current_value is None or previous_value is None:
                    continue
                if previous_value <= 0:
                    continue
                if current_value < previous_value * (1 - thresholds.decline_ratio_threshold):
                    evidence = (
                        OptimizationEvidence(
                            metric=metric_name,
                            observed_value=current_value,
                            comparison_value=previous_value,
                            source_artifact_id=analytics_ref_id,
                            source_artifact_type=ANALYTICS_ARTIFACT_TYPE,
                            source_artifact_hash=analytics_ref_hash,
                        ),
                    )
                    raw.append(
                        (
                            "performance_decline",
                            OptimizationRecommendationPriority.MEDIUM,
                            metric_name,
                            f"Review recent changes that may relate to the "
                            f"decline in {metric_name}.",
                            _build_rationale(
                                observation=(
                                    f"{metric_name} declined from "
                                    f"{previous_value} to {current_value} "
                                    f"(more than "
                                    f"{thresholds.decline_ratio_threshold * 100:.0f}% "
                                    f"relative decline) between the "
                                    f"previous and current period."
                                ),
                                interpretation=(
                                    f"The data shows a decline in "
                                    f"{metric_name} associated with this "
                                    f"period; this comparison does not by "
                                    f"itself identify a cause."
                                ),
                                recommendation_text=(
                                    f"Review recent content/strategy "
                                    f"changes that coincide with this "
                                    f"period for a possible explanation."
                                ),
                            ),
                            evidence,
                            f"Identifying and reverting/adjusting the "
                            f"associated change may recover {metric_name}.",
                            _confidence(has_comparison=True),
                        )
                    )

        recommendations = tuple(
            OptimizationRecommendation(
                recommendation_id=f"recommendation-{index + 1:03d}",
                category=category,
                priority=priority,
                target=target,
                action=action,
                rationale=rationale,
                evidence=evidence,
                expected_effect=expected_effect,
                confidence=confidence,
                status=OptimizationRecommendationStatus.PROPOSED,
            )
            for index, (category, priority, target, action, rationale, evidence, expected_effect, confidence)
            in enumerate(raw)
        )

        return OptimizationEvaluationResult(recommendations=recommendations, warnings=tuple(warnings))


# ----------------------------------------------------------------------
# VALIDATION (P3.9 Sections 29/33/34) -- three structurally separate
# checks, never merged.
# ----------------------------------------------------------------------


def _validate_optional_artifact(
    label: str,
    artifact,
    expected_cls,
    expected_type: str,
    mission_id: str,
    supported_contract_versions: frozenset,
) -> List[str]:
    if artifact is None:
        return []
    errors: List[str] = []
    if not isinstance(artifact, expected_cls):
        return [f"{label} is not a valid {expected_cls.__name__} instance."]
    if artifact.artifact_type != expected_type:
        errors.append(f"{label}.artifact_type '{artifact.artifact_type}' is not '{expected_type}'.")
    if artifact.mission_id != mission_id:
        errors.append(
            f"{label}.mission_id '{artifact.mission_id}' does not match "
            f"this OptimizationAgentInput.mission_id '{mission_id}' -- "
            f"refusing to consume an artifact belonging to a different "
            f"mission."
        )
    if artifact.status != "FINAL":
        errors.append(f"{label}.status '{artifact.status}' is not 'FINAL'.")
    if artifact.contract_version not in supported_contract_versions:
        errors.append(
            f"{label}.contract_version {artifact.contract_version} is not "
            f"supported (supported: {sorted(supported_contract_versions)})."
        )
    return errors


def _validate_artifact_dependencies(agent_input: OptimizationAgentInput) -> List[str]:
    errors: List[str] = []

    analytics = agent_input.analytics_artifact
    if analytics is None:
        errors.append("analytics_artifact is missing.")
        return errors
    if not isinstance(analytics, AnalyticsArtifact):
        errors.append("analytics_artifact is not a valid AnalyticsArtifact instance.")
        return errors

    errors.extend(
        _validate_optional_artifact(
            "analytics_artifact", analytics, AnalyticsArtifact, ANALYTICS_ARTIFACT_TYPE,
            agent_input.mission_id, SUPPORTED_ANALYTICS_CONTRACT_VERSIONS,
        )
    )
    errors.extend(
        _validate_optional_artifact(
            "previous_analytics_artifact", agent_input.previous_analytics_artifact, AnalyticsArtifact,
            ANALYTICS_ARTIFACT_TYPE, agent_input.mission_id, SUPPORTED_ANALYTICS_CONTRACT_VERSIONS,
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
            "content_artifact", agent_input.content_artifact, ContentArtifact, CONTENT_ARTIFACT_TYPE,
            agent_input.mission_id, SUPPORTED_CONTENT_CONTRACT_VERSIONS,
        )
    )
    errors.extend(
        _validate_optional_artifact(
            "publication_artifact", agent_input.publication_artifact, PublicationArtifact,
            PUBLICATION_ARTIFACT_TYPE, agent_input.mission_id, SUPPORTED_PUBLISHING_CONTRACT_VERSIONS,
        )
    )

    return errors


def _validate_metrics(label: str, metrics: Tuple[MetricValue, ...]) -> List[str]:
    errors: List[str] = []
    for metric in metrics:
        if not isinstance(metric.name, str) or not metric.name.strip():
            errors.append(f"{label}: a metric has a missing/empty name.")
            continue
        if not isinstance(metric.value, (int, float)) or isinstance(metric.value, bool):
            errors.append(f"{label}.{metric.name}: value {metric.value!r} is not numeric.")
            continue
        if metric.name in NON_NEGATIVE_METRIC_NAMES and metric.value < 0:
            errors.append(f"{label}.{metric.name}: value {metric.value} must not be negative.")
        if metric.name in RATIO_METRIC_NAMES and not (0.0 <= metric.value <= 1.0):
            errors.append(
                f"{label}.{metric.name}: value {metric.value} must be within [0.0, 1.0]."
            )
    return errors


def _validate_period(label: str, period: AnalyticsPeriod) -> List[str]:
    errors: List[str] = []
    if period.timezone not in ALLOWED_TIMEZONES:
        errors.append(
            f"{label}.period.timezone '{period.timezone}' is invalid "
            f"(allowed: {sorted(ALLOWED_TIMEZONES)})."
        )
    try:
        start = datetime.fromisoformat(period.start)
        end = datetime.fromisoformat(period.end)
        if start > end:
            errors.append(f"{label}.period.start ({period.start}) is after {label}.period.end ({period.end}).")
    except (TypeError, ValueError):
        errors.append(f"{label}.period has an invalid start/end ISO 8601 datetime.")
    return errors


def _validate_optimization_input(agent_input: OptimizationAgentInput) -> List[str]:
    errors: List[str] = []

    if not isinstance(agent_input.mission_id, str) or not agent_input.mission_id.strip():
        errors.append("mission_id is missing or empty.")

    profile = agent_input.optimization_profile
    if profile is not None:
        if not isinstance(profile, OptimizationProfile):
            errors.append("optimization_profile is not a valid OptimizationProfile instance.")
        elif profile.name not in ALLOWED_OPTIMIZATION_PROFILES:
            errors.append(
                f"optimization_profile.name '{profile.name}' is invalid "
                f"(allowed: {sorted(ALLOWED_OPTIMIZATION_PROFILES)})."
            )

    analytics = agent_input.analytics_artifact
    if isinstance(analytics, AnalyticsArtifact):
        errors.extend(_validate_period("analytics_artifact", analytics.period))
        errors.extend(_validate_metrics("analytics_artifact.metrics", analytics.metrics))

    previous = agent_input.previous_analytics_artifact
    if isinstance(previous, AnalyticsArtifact):
        errors.extend(_validate_period("previous_analytics_artifact", previous.period))
        errors.extend(_validate_metrics("previous_analytics_artifact.metrics", previous.metrics))

    return errors


def _integrity_errors(agent_input: OptimizationAgentInput) -> List[str]:
    """Recomputes every provided artifact's content_hash from its own
    real fields via the REAL, imported hash functions -- never trusting
    the declared value."""

    errors: List[str] = []

    def _check_analytics(label: str, artifact: Optional[AnalyticsArtifact]) -> None:
        if artifact is None:
            return
        try:
            recomputed = compute_analytics_artifact_hash(
                mission_id=artifact.mission_id,
                platform=artifact.platform,
                period=artifact.period,
                metrics=artifact.metrics,
                contract_version=artifact.contract_version,
            )
            if recomputed != artifact.content_hash:
                errors.append(f"{label}.content_hash does not match a recomputed hash of its own fields.")
        except Exception as error:  # noqa: BLE001
            errors.append(f"{label} integrity could not be verified: {error}")

    _check_analytics("analytics_artifact", agent_input.analytics_artifact)
    _check_analytics("previous_analytics_artifact", agent_input.previous_analytics_artifact)

    quality = agent_input.quality_artifact
    if quality is not None:
        try:
            recomputed = compute_quality_artifact_hash(
                mission_id=quality.mission_id,
                quality_status=quality.quality_status,
                score=quality.score,
                findings=quality.findings,
                evaluated_artifacts=quality.evaluated_artifacts,
                profile=quality.profile,
                contract_version=quality.contract_version,
            )
            if recomputed != quality.content_hash:
                errors.append("quality_artifact.content_hash does not match a recomputed hash of its own fields.")
        except Exception as error:  # noqa: BLE001
            errors.append(f"quality_artifact integrity could not be verified: {error}")

    content = agent_input.content_artifact
    if content is not None:
        try:
            recomputed = compute_content_artifact_hash(
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
            if recomputed != content.content_hash:
                errors.append("content_artifact.content_hash does not match a recomputed hash of its own fields.")
        except Exception as error:  # noqa: BLE001
            errors.append(f"content_artifact integrity could not be verified: {error}")

    publication = agent_input.publication_artifact
    if publication is not None:
        try:
            recomputed = compute_publication_artifact_hash(
                mission_id=publication.mission_id,
                publication_status=publication.publication_status,
                platforms=publication.platforms,
                publication_items=publication.publication_items,
                media_reference=publication.media_reference,
                schedule=publication.schedule,
                profile=publication.profile,
                evaluated_artifacts=publication.evaluated_artifacts,
                contract_version=publication.contract_version,
            )
            if recomputed != publication.content_hash:
                errors.append("publication_artifact.content_hash does not match a recomputed hash of its own fields.")
        except Exception as error:  # noqa: BLE001
            errors.append(f"publication_artifact integrity could not be verified: {error}")

    return errors


# ----------------------------------------------------------------------
# HASH / INTEGRITY (P3.9 Section 21)
# ----------------------------------------------------------------------


def compute_optimization_artifact_hash(
    mission_id: str,
    optimization_status: OptimizationAgentStatus,
    platform: str,
    profile: OptimizationProfile,
    recommendations: Tuple[OptimizationRecommendation, ...],
    source_artifacts: Tuple[EvaluatedArtifactReference, ...],
    contract_version: int,
) -> str:
    canonical = {
        "mission_id": mission_id,
        "optimization_status": optimization_status.value,
        "platform": platform,
        "profile": _profile_to_dict(profile),
        "recommendations": [_recommendation_to_dict(r) for r in recommendations],
        "source_artifacts": [_reference_to_dict(ref) for ref in source_artifacts],
        "contract_version": contract_version,
    }
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# IDEMPOTENCY (P3.9 Section 23)
# ----------------------------------------------------------------------


def compute_optimization_idempotency_key(agent_input: OptimizationAgentInput) -> str:
    def _ref(artifact) -> dict:
        if artifact is None:
            return {"artifact_id": None, "version": None, "content_hash": None}
        return {
            "artifact_id": artifact.artifact_id,
            "version": artifact.version,
            "content_hash": artifact.content_hash,
        }

    profile = agent_input.optimization_profile or DEFAULT_OPTIMIZATION_PROFILE

    canonical = {
        "mission_id": agent_input.mission_id,
        "analytics": _ref(agent_input.analytics_artifact),
        "previous_analytics": _ref(agent_input.previous_analytics_artifact),
        "quality": _ref(agent_input.quality_artifact),
        "content": _ref(agent_input.content_artifact),
        "publication": _ref(agent_input.publication_artifact),
        "profile": _profile_to_dict(profile),
        "constraints": list(agent_input.constraints),
    }
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# OPTIMIZATION AGENT (P3.9 Section 4)
# ----------------------------------------------------------------------


class OptimizationAgent:
    """
    AI DIRECTOR — Optimization Agent v1.0 (P3.9)

    Depends on `agents.content_agent`/`agents.quality_agent`/
    `agents.publishing_agent` for the real contracts/hash functions it
    must consume -- no dependency on Higgsfield, any P2 gate/authority
    module, the Director, any event bus, or any network/social-platform
    library of any kind.
    """

    def __init__(self, engine: Optional[OptimizationEngine] = None):
        self.engine = engine or DeterministicOptimizationEngine()

    def run(self, agent_input: OptimizationAgentInput) -> OptimizationAgentOutput:
        """
        Order: (1) artifact dependency validation -> REJECTED; (2) this
        agent's own input + data validation (period/metrics/profile) ->
        VALIDATION_ERROR; (3) integrity (hash recomputation across every
        provided artifact) -> INTEGRITY_FAILURE, WITH a minimal
        OptimizationArtifact recording the fact; (4) engine evaluation ->
        INSUFFICIENT_DATA / READY / WARNING, WITH a fully populated
        OptimizationArtifact whose recommendations are ALWAYS `PROPOSED`.
        Never mutates any input artifact. Never emits an event. Never
        constructs any authorization object. Never applies a
        recommendation.
        """

        mission_id = (
            agent_input.mission_id if isinstance(agent_input.mission_id, str) else ""
        )

        dependency_errors = _validate_artifact_dependencies(agent_input)
        if dependency_errors:
            return OptimizationAgentOutput(
                mission_id=mission_id,
                status=OptimizationAgentStatus.REJECTED,
                errors=tuple(dependency_errors),
            )

        input_errors = _validate_optimization_input(agent_input)
        if input_errors:
            return OptimizationAgentOutput(
                mission_id=mission_id,
                status=OptimizationAgentStatus.VALIDATION_ERROR,
                errors=tuple(input_errors),
            )

        analytics = agent_input.analytics_artifact
        profile = agent_input.optimization_profile or DEFAULT_OPTIMIZATION_PROFILE

        source_artifacts: List[EvaluatedArtifactReference] = [
            EvaluatedArtifactReference(
                artifact_id=analytics.artifact_id,
                artifact_type=analytics.artifact_type,
                artifact_version=analytics.version,
                content_hash=analytics.content_hash,
            )
        ]
        for artifact in (
            agent_input.previous_analytics_artifact,
            agent_input.quality_artifact,
            agent_input.content_artifact,
            agent_input.publication_artifact,
        ):
            if artifact is not None:
                source_artifacts.append(
                    EvaluatedArtifactReference(
                        artifact_id=artifact.artifact_id,
                        artifact_type=artifact.artifact_type,
                        artifact_version=artifact.version,
                        content_hash=artifact.content_hash,
                    )
                )
        source_artifacts_tuple = tuple(source_artifacts)

        integrity_errors = _integrity_errors(agent_input)
        if integrity_errors:
            return self._build_output(
                mission_id=agent_input.mission_id,
                optimization_status=OptimizationAgentStatus.INTEGRITY_FAILURE,
                platform=analytics.platform,
                profile=profile,
                recommendations=(),
                source_artifacts=source_artifacts_tuple,
                errors=tuple(integrity_errors),
            )

        context = OptimizationEvaluationContext(
            analytics_artifact=analytics,
            previous_analytics_artifact=agent_input.previous_analytics_artifact,
            quality_artifact=agent_input.quality_artifact,
            content_artifact=agent_input.content_artifact,
            publication_artifact=agent_input.publication_artifact,
            profile=profile,
        )
        result = self.engine.evaluate(context)

        if result.insufficient_data:
            return self._build_output(
                mission_id=agent_input.mission_id,
                optimization_status=OptimizationAgentStatus.INSUFFICIENT_DATA,
                platform=analytics.platform,
                profile=profile,
                recommendations=(),
                source_artifacts=source_artifacts_tuple,
                warnings=(
                    (result.insufficient_data_reason,) if result.insufficient_data_reason else ()
                ),
            )

        has_low_confidence = any(
            recommendation.confidence < WARNING_CONFIDENCE_THRESHOLD
            for recommendation in result.recommendations
        )
        status = (
            OptimizationAgentStatus.WARNING
            if (has_low_confidence or result.warnings)
            else OptimizationAgentStatus.READY
        )

        return self._build_output(
            mission_id=agent_input.mission_id,
            optimization_status=status,
            platform=analytics.platform,
            profile=profile,
            recommendations=result.recommendations,
            source_artifacts=source_artifacts_tuple,
            warnings=result.warnings,
        )

    @staticmethod
    def _build_output(
        mission_id: str,
        optimization_status: OptimizationAgentStatus,
        platform: str,
        profile: OptimizationProfile,
        recommendations: Tuple[OptimizationRecommendation, ...],
        source_artifacts: Tuple[EvaluatedArtifactReference, ...],
        warnings: Tuple[str, ...] = (),
        errors: Tuple[str, ...] = (),
    ) -> OptimizationAgentOutput:
        artifact_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()

        content_hash = compute_optimization_artifact_hash(
            mission_id=mission_id,
            optimization_status=optimization_status,
            platform=platform,
            profile=profile,
            recommendations=recommendations,
            source_artifacts=source_artifacts,
            contract_version=CONTRACT_VERSION,
        )

        optimization_artifact = OptimizationArtifact(
            artifact_id=artifact_id,
            artifact_type=OPTIMIZATION_ARTIFACT_TYPE,
            mission_id=mission_id,
            created_at=created_at,
            version=ARTIFACT_VERSION,
            status="FINAL",
            optimization_status=optimization_status,
            platform=platform,
            profile=profile,
            recommendations=recommendations,
            source_artifacts=source_artifacts,
            producer_agent=AGENT_ID,
            producer_version=AGENT_VERSION,
            contract_version=CONTRACT_VERSION,
            content_hash=content_hash,
        )

        return OptimizationAgentOutput(
            mission_id=mission_id,
            status=optimization_status,
            optimization_artifact=optimization_artifact,
            warnings=warnings,
            errors=errors,
        )
