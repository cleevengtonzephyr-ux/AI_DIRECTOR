"""
AI DIRECTOR — Quality Agent v1.0 (Phase P3.7)

Third business agent of the future multi-agent AI Director, built
directly against the REAL `agents/content_agent.py` (P3.6) contracts --
`ContentArtifact`, `ScriptArtifact`, `CONTENT_ARTIFACT_TYPE`,
`SCRIPT_ARTIFACT_TYPE`, `CONTRACT_VERSION`, `ALLOWED_TONES`,
`ALLOWED_FORMATS`, `compute_content_artifact_hash`,
`compute_script_artifact_hash` -- and, transitively but directly (not
through content_agent's internal aliases), `agents/strategy_agent.py`'s
`ALLOWED_LANGUAGES`/`ALLOWED_PLATFORMS` whitelists, to independently
re-verify artifact metadata rather than trusting that ContentAgent
already did so. Both files, plus their test files, were re-read from
disk in full before writing a single line of this module.

RELATIONSHIP TO EXISTING QUALITY MECHANISMS -- NEITHER IS TOUCHED,
NEITHER IS DUPLICATED:
- `agents/quality_evaluator.py` (Phase I / P2 era) evaluates a
  `GenerationJobOutcome` (a REAL or mocked Higgsfield job result) into
  PASS/FAIL/RETRY_RECOMMENDED. It operates strictly AFTER a job has been
  created and polled. This module never touches it, never imports it,
  and answers a completely different, EARLIER question: "is the
  editorial content/script itself internally sound, BEFORE any
  generation is even requested?"
- `agents/qa_engine.py` (V1) validates a REAL, already-downloaded video
  FILE (extension, size, duration, ratio, resolution). It operates on
  bytes on disk that do not exist at this stage of the pipeline. This
  module never touches it, never imports it, and never inspects a video
  file.
This QualityAgent is a THIRD, new, earlier-stage mechanism: content/
script artifact quality, prior to and independent of both.

RESPONSIBILITY (P3.7 Section 4):
ContentArtifact + ScriptArtifact -> QualityArtifact. QualityAgent =
EVALUATION, never AUTHORITY. A `QUALITY_PASS` result NEVER means
`TECHNICAL_APPROVAL`, `HUMAN_AUTHORIZATION`, `PRODUCTION_AUTHORIZATION`,
`EXECUTION` readiness, or publication approval -- none of those concepts
exist anywhere in this module (see tests/test_quality_agent.py::
SecurityTests, AST-verified exactly as P3.5/P3.6 were).

THREE DISTINCT FAILURE FAMILIES (Section 9) -- never conflated:
- INVALID       -- the request itself cannot be evaluated at all: wrong
                   artifact type, wrong mission_id, missing artifact, or
                   this agent's own input malformed. Reported as
                   `REJECTED` (structural/dependency problem) or
                   `VALIDATION_ERROR` (this agent's own input problem).
                   NO QualityArtifact is produced in either case.
- INTEGRITY_FAILURE -- the artifacts are the RIGHT type/mission, but a
                   recomputed content_hash does not match the declared
                   one (tampering, corruption, or a script/content pair
                   that were never really bound together). A
                   QualityArtifact IS produced, recording this fact as
                   the evaluation's own outcome -- this is itself
                   valuable, permanent audit evidence, not a case to
                   silently discard. Score is `None` (untrustworthy
                   input cannot be meaningfully scored).
- QUALITY_FAILURE  -- the artifacts are structurally/cryptographically
                   sound, but the deterministic rules below found real
                   editorial/structural problems. Reported as `FAIL`
                   (or `PASS_WITH_WARNINGS` for milder findings) on a
                   fully-populated QualityArtifact with a real score.

AUTHORITY (P3.2 Section 14 / P3.7 Section 5): EVALUATE / REVIEW. Cannot
call create_job, publish, create RealGenerationAuthorization or any
activation contract, modify any P2 authority mechanism, or mutate the
Mission State Machine.

DETERMINISM: identical discipline to P3.5/P3.6 -- no `random`, no LLM
call, no network/web call. Only `created_at` and `artifact_id`
(technical, never fed into content_hash) vary between calls with the
same input. Findings are generated in a fixed, documented order so
`finding_id` assignment (by position) is itself deterministic.

READ-ONLY vis-a-vis inputs (Section 26): this module never calls
`dataclasses.replace()`, never assigns an attribute, and never mutates
`content_artifact`/`script_artifact` in any way -- both are frozen
dataclasses already, but this module additionally never even attempts a
copy-and-modify pattern; it only reads.
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
    ALLOWED_FORMATS,
    ALLOWED_TONES,
    CONTENT_ARTIFACT_TYPE,
    CONTRACT_VERSION as CONTENT_CONTRACT_VERSION,
    SCRIPT_ARTIFACT_TYPE,
    ContentArtifact,
    ScriptArtifact,
    compute_content_artifact_hash,
    compute_script_artifact_hash,
)
from agents.strategy_agent import ALLOWED_LANGUAGES, ALLOWED_PLATFORMS

# ----------------------------------------------------------------------
# VERSIONING (P3.7 Section 19)
# ----------------------------------------------------------------------

AGENT_ID = "quality-agent"
AGENT_VERSION = "1.0"
CONTRACT_VERSION = 1
QUALITY_ARTIFACT_TYPE = "QualityArtifact"
ARTIFACT_VERSION = 1

# This QualityAgent version only knows how to interpret a ContentArtifact/
# ScriptArtifact produced under this exact contract_version. An
# incompatible future contract_version is REJECTED (DEPENDENCY), never
# guess-parsed -- same discipline ContentAgent applies to StrategyArtifact.
SUPPORTED_CONTENT_CONTRACT_VERSIONS = frozenset({CONTENT_CONTRACT_VERSION})
SUPPORTED_SCRIPT_CONTRACT_VERSIONS = frozenset({CONTENT_CONTRACT_VERSION})

# ----------------------------------------------------------------------
# QUALITY DIMENSIONS (P3.7 Section 11) -- small, explicit, closed set.
# ----------------------------------------------------------------------

QUALITY_DIMENSIONS = (
    "completeness",
    "consistency",
    "structure",
    "platform_alignment",
    "language_consistency",
    "script_coherence",
    "metadata_integrity",
)

# Reserved category used ONLY for the integrity short-circuit path
# (Section 9) -- never produced by the normal dimension checks below.
INTEGRITY_CATEGORY = "integrity"

# ----------------------------------------------------------------------
# SEVERITY / SCORE FORMULA (P3.7 Section 13) -- explicit, documented,
# deterministic. score = 100 - sum(deduction[finding.severity] for
# finding in findings), floored at 0. This IS the entire scoring
# formula: no hidden weighting, no per-dimension sub-scores.
# ----------------------------------------------------------------------


class QualityFindingSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


SEVERITY_DEDUCTIONS = {
    QualityFindingSeverity.INFO: 0,
    QualityFindingSeverity.WARNING: 5,
    QualityFindingSeverity.ERROR: 25,
    QualityFindingSeverity.CRITICAL: 60,
}


class QualityAgentStatus(str, Enum):
    """
    Doubles as `QualityArtifact.quality_status`'s type (both live in
    this module and their value sets legitimately overlap for the four
    real evaluation outcomes) -- `REJECTED`/`VALIDATION_ERROR`/
    `NOT_EVALUATED` never appear on a produced QualityArtifact (no
    artifact is produced for those two; `NOT_EVALUATED` is reserved
    vocabulary, never returned by `QualityAgent.run()` today), enforced
    by construction and checked by tests/test_quality_agent.py.
    """

    NOT_EVALUATED = "NOT_EVALUATED"
    REJECTED = "REJECTED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTEGRITY_FAILURE = "INTEGRITY_FAILURE"
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    FAIL = "FAIL"


# ----------------------------------------------------------------------
# QUALITY PROFILE (P3.7 Section 11) -- minimal, explicit.
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class QualityProfile:
    name: str = "default"
    pass_threshold: int = 80
    warning_threshold: int = 60
    # Maximum allowed |sum(scene.duration) - total_duration_target|
    # before it becomes a structural finding. Zero by default: ContentAgent
    # guarantees an exact match by construction, but QualityAgent never
    # trusts that guarantee -- it always recomputes independently.
    max_duration_variance_seconds: int = 0


DEFAULT_QUALITY_PROFILE = QualityProfile()


def _profile_to_dict(profile: QualityProfile) -> dict:
    return {
        "name": profile.name,
        "pass_threshold": profile.pass_threshold,
        "warning_threshold": profile.warning_threshold,
        "max_duration_variance_seconds": profile.max_duration_variance_seconds,
    }


# ----------------------------------------------------------------------
# INPUT CONTRACT (P3.7 Section 6)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class QualityAgentInput:
    mission_id: str
    content_artifact: ContentArtifact
    script_artifact: ScriptArtifact
    quality_profile: Optional[QualityProfile] = None
    constraints: Tuple[str, ...] = field(default_factory=tuple)


# ----------------------------------------------------------------------
# FINDINGS (P3.7 Section 12)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    finding_id: str
    severity: QualityFindingSeverity
    category: str
    code: str
    message: str
    artifact_reference: str
    field_reference: Optional[str] = None


def _findings_to_dicts(findings: Tuple[Finding, ...]) -> List[dict]:
    return [
        {
            "finding_id": finding.finding_id,
            "severity": finding.severity.value,
            "category": finding.category,
            "code": finding.code,
            "message": finding.message,
            "artifact_reference": finding.artifact_reference,
            "field_reference": finding.field_reference,
        }
        for finding in findings
    ]


def _assign_finding_ids(
    raw_findings: List[Tuple[QualityFindingSeverity, str, str, str, str, Optional[str]]]
) -> Tuple[Finding, ...]:
    """
    Stamps `finding_id` by FIXED POSITION in the (already deterministically
    ordered) input list -- never by hashing, never by uuid. Two runs with
    the same artifacts always produce findings in the same order, so the
    same `finding_id`s (P3.7 Section 12: "meme input -> memes findings").
    """

    return tuple(
        Finding(
            finding_id=f"finding-{index + 1:03d}",
            severity=severity,
            category=category,
            code=code,
            message=message,
            artifact_reference=artifact_reference,
            field_reference=field_reference,
        )
        for index, (severity, category, code, message, artifact_reference, field_reference)
        in enumerate(raw_findings)
    )


# ----------------------------------------------------------------------
# EVALUATED ARTIFACT REFERENCES (P3.7 Section 16) -- traceability without
# copying source content into QualityArtifact.
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluatedArtifactReference:
    artifact_id: str
    artifact_type: str
    artifact_version: int
    content_hash: str


def _reference_to_dict(reference: EvaluatedArtifactReference) -> dict:
    return {
        "artifact_id": reference.artifact_id,
        "artifact_type": reference.artifact_type,
        "artifact_version": reference.artifact_version,
        "content_hash": reference.content_hash,
    }


# ----------------------------------------------------------------------
# QUALITY ARTIFACT (P3.7 Section 15)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class QualityArtifact:
    artifact_id: str
    artifact_type: str
    mission_id: str
    created_at: str
    version: int
    status: str  # Artifact lifecycle status (DRAFT|FINAL|SUPERSEDED),
    # distinct from `quality_status` below -- same discipline as P3.5/
    # P3.6's artifact-status-vs-agent-status separation.

    quality_status: QualityAgentStatus
    score: Optional[int]
    findings: Tuple[Finding, ...]
    evaluated_artifacts: Tuple[EvaluatedArtifactReference, ...]
    profile: QualityProfile

    producer_agent: str
    producer_version: str
    contract_version: int

    content_hash: str


# ----------------------------------------------------------------------
# OUTPUT CONTRACT
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class QualityAgentOutput:
    mission_id: str
    status: QualityAgentStatus
    quality_artifact: Optional[QualityArtifact] = None
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    errors: Tuple[str, ...] = field(default_factory=tuple)
    producer_agent: str = AGENT_ID
    producer_version: str = AGENT_VERSION
    contract_version: int = CONTRACT_VERSION


# ----------------------------------------------------------------------
# QUALITY ENGINE (P3.7 Section 10) -- QualityAgent = validation,
# integrity, orchestration, status/score decision; QualityEngine =
# dimension checks -> findings. Swappable without changing QualityAgent's
# own contract, mirroring StrategyEngine/ContentEngine exactly.
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class QualityEvaluationContext:
    content_artifact: ContentArtifact
    script_artifact: ScriptArtifact
    profile: QualityProfile


@dataclass(frozen=True)
class QualityEvaluationResult:
    findings: Tuple[Finding, ...]


class QualityEngine(ABC):
    """Contract every quality backend (deterministic, LLM, human review)
    must satisfy. Never called before integrity has already been
    confirmed -- QualityAgent.run() checks integrity first."""

    @abstractmethod
    def evaluate(self, context: QualityEvaluationContext) -> QualityEvaluationResult:
        raise NotImplementedError


class DeterministicQualityEngine(QualityEngine):
    """
    V1 default engine: purely local, rule-based, deterministic. No
    random, no LLM, no network, no external data. Same
    QualityEvaluationContext always produces the same findings, in the
    same order.

    NOTE on `script_coherence` (Section 21): this dimension checks that
    scene 1's narration equals `content_artifact.hook` and the last
    scene's narration equals `content_artifact.cta`. This assumes the
    Hook/Body/CTA convention `DeterministicContentEngine` (P3.6)
    currently follows -- a future ContentEngine using a different
    structural convention would need this dimension's rules revisited to
    match it. Documented here rather than silently assumed.
    """

    def evaluate(self, context: QualityEvaluationContext) -> QualityEvaluationResult:
        content = context.content_artifact
        script = context.script_artifact
        profile = context.profile

        raw: List[Tuple[QualityFindingSeverity, str, str, str, str, Optional[str]]] = []

        if context.profile is DEFAULT_QUALITY_PROFILE:
            raw.append(
                (
                    QualityFindingSeverity.INFO,
                    "metadata_integrity",
                    "USING_DEFAULT_QUALITY_PROFILE",
                    "No quality_profile was supplied; the default profile was used.",
                    content.artifact_id,
                    "quality_profile",
                )
            )

        # -- completeness --------------------------------------------------
        for field_name, value in (
            ("title", content.title),
            ("concept", content.concept),
            ("angle", content.angle),
            ("hook", content.hook),
            ("cta", content.cta),
            ("language", content.language),
        ):
            if not isinstance(value, str) or not value.strip():
                raw.append(
                    (
                        QualityFindingSeverity.ERROR,
                        "completeness",
                        f"MISSING_{field_name.upper()}",
                        f"content_artifact.{field_name} is missing or empty.",
                        content.artifact_id,
                        field_name,
                    )
                )

        if not content.target_platforms:
            raw.append(
                (
                    QualityFindingSeverity.ERROR,
                    "completeness",
                    "MISSING_TARGET_PLATFORMS",
                    "content_artifact.target_platforms is missing or empty.",
                    content.artifact_id,
                    "target_platforms",
                )
            )

        # -- consistency (own declared metadata re-verified against the
        # canonical whitelists -- never trusted merely because ContentAgent
        # should have validated it already) -----------------------------
        if content.language not in ALLOWED_LANGUAGES:
            raw.append(
                (
                    QualityFindingSeverity.ERROR,
                    "consistency",
                    "INVALID_CONTENT_LANGUAGE",
                    f"content_artifact.language '{content.language}' is not a "
                    f"recognized language.",
                    content.artifact_id,
                    "language",
                )
            )

        if content.tone not in ALLOWED_TONES:
            raw.append(
                (
                    QualityFindingSeverity.WARNING,
                    "consistency",
                    "INVALID_CONTENT_TONE",
                    f"content_artifact.tone '{content.tone}' is not a recognized "
                    f"tone.",
                    content.artifact_id,
                    "tone",
                )
            )

        if content.content_format not in ALLOWED_FORMATS:
            raw.append(
                (
                    QualityFindingSeverity.WARNING,
                    "consistency",
                    "INVALID_CONTENT_FORMAT",
                    f"content_artifact.content_format '{content.content_format}' "
                    f"is not a recognized format.",
                    content.artifact_id,
                    "content_format",
                )
            )

        # -- structure -------------------------------------------------
        if not script.scenes:
            raw.append(
                (
                    QualityFindingSeverity.CRITICAL,
                    "structure",
                    "EMPTY_SCRIPT",
                    "script_artifact.scenes is empty.",
                    script.artifact_id,
                    "scenes",
                )
            )
        else:
            expected_orders = list(range(1, len(script.scenes) + 1))
            actual_orders = [scene.order for scene in script.scenes]
            if actual_orders != expected_orders:
                raw.append(
                    (
                        QualityFindingSeverity.ERROR,
                        "structure",
                        "INVALID_SCENE_ORDER",
                        f"script_artifact scene order {actual_orders} is not the "
                        f"expected contiguous sequence {expected_orders}.",
                        script.artifact_id,
                        "scenes[].order",
                    )
                )

            for scene in script.scenes:
                if scene.duration <= 0:
                    raw.append(
                        (
                            QualityFindingSeverity.WARNING,
                            "structure",
                            "NON_POSITIVE_SCENE_DURATION",
                            f"scene '{scene.scene_id}' has non-positive duration "
                            f"{scene.duration}.",
                            script.artifact_id,
                            f"scenes[{scene.order}].duration",
                        )
                    )
                if not isinstance(scene.narration, str) or not scene.narration.strip():
                    raw.append(
                        (
                            QualityFindingSeverity.ERROR,
                            "structure",
                            "MISSING_SCENE_NARRATION",
                            f"scene '{scene.scene_id}' has missing/empty narration.",
                            script.artifact_id,
                            f"scenes[{scene.order}].narration",
                        )
                    )
                if not isinstance(scene.visual_direction, str) or not scene.visual_direction.strip():
                    raw.append(
                        (
                            QualityFindingSeverity.ERROR,
                            "structure",
                            "MISSING_VISUAL_DIRECTION",
                            f"scene '{scene.scene_id}' has missing/empty "
                            f"visual_direction.",
                            script.artifact_id,
                            f"scenes[{scene.order}].visual_direction",
                        )
                    )

            duration_sum = sum(scene.duration for scene in script.scenes)
            variance = abs(duration_sum - script.total_duration_target)
            if variance > profile.max_duration_variance_seconds:
                raw.append(
                    (
                        QualityFindingSeverity.ERROR,
                        "structure",
                        "DURATION_SUM_MISMATCH",
                        f"sum(scene.duration)={duration_sum} does not match "
                        f"total_duration_target={script.total_duration_target} "
                        f"(variance {variance}s exceeds allowed "
                        f"{profile.max_duration_variance_seconds}s).",
                        script.artifact_id,
                        "total_duration_target",
                    )
                )

        # -- platform_alignment -----------------------------------------
        for platform in content.target_platforms:
            if platform not in ALLOWED_PLATFORMS:
                raw.append(
                    (
                        QualityFindingSeverity.ERROR,
                        "platform_alignment",
                        "UNSUPPORTED_PLATFORM",
                        f"content_artifact.target_platforms contains "
                        f"unsupported platform '{platform}'.",
                        content.artifact_id,
                        "target_platforms",
                    )
                )

        # -- language_consistency ----------------------------------------
        if content.language != script.language:
            raw.append(
                (
                    QualityFindingSeverity.ERROR,
                    "language_consistency",
                    "LANGUAGE_MISMATCH",
                    f"content_artifact.language '{content.language}' does not "
                    f"match script_artifact.language '{script.language}'.",
                    script.artifact_id,
                    "language",
                )
            )

        # -- script_coherence ---------------------------------------------
        if script.scenes:
            first_scene = script.scenes[0]
            if first_scene.narration != content.hook:
                raw.append(
                    (
                        QualityFindingSeverity.ERROR,
                        "script_coherence",
                        "HOOK_SCENE_MISMATCH",
                        "The first scene's narration does not match "
                        "content_artifact.hook.",
                        script.artifact_id,
                        "scenes[1].narration",
                    )
                )

            last_scene = script.scenes[-1]
            if last_scene.narration != content.cta:
                raw.append(
                    (
                        QualityFindingSeverity.ERROR,
                        "script_coherence",
                        "CTA_SCENE_MISMATCH",
                        "The last scene's narration does not match "
                        "content_artifact.cta.",
                        script.artifact_id,
                        f"scenes[{last_scene.order}].narration",
                    )
                )

        # -- metadata_integrity (presence only -- hash-based integrity is
        # handled separately by QualityAgent BEFORE this engine even runs) --
        for artifact, label in ((content, "content_artifact"), (script, "script_artifact")):
            if not artifact.producer_agent:
                raw.append(
                    (
                        QualityFindingSeverity.WARNING,
                        "metadata_integrity",
                        "MISSING_PRODUCER_AGENT",
                        f"{label}.producer_agent is missing or empty.",
                        artifact.artifact_id,
                        "producer_agent",
                    )
                )
            if not artifact.producer_version:
                raw.append(
                    (
                        QualityFindingSeverity.WARNING,
                        "metadata_integrity",
                        "MISSING_PRODUCER_VERSION",
                        f"{label}.producer_version is missing or empty.",
                        artifact.artifact_id,
                        "producer_version",
                    )
                )
            if not artifact.dependencies:
                raw.append(
                    (
                        QualityFindingSeverity.WARNING,
                        "metadata_integrity",
                        "MISSING_DEPENDENCIES",
                        f"{label}.dependencies is missing or empty.",
                        artifact.artifact_id,
                        "dependencies",
                    )
                )

        return QualityEvaluationResult(findings=_assign_finding_ids(raw))


# ----------------------------------------------------------------------
# VALIDATION (P3.7 Sections 7/8/9) -- three structurally separate checks.
# ----------------------------------------------------------------------


def _validate_artifact_dependencies(agent_input: QualityAgentInput) -> List[str]:
    errors: List[str] = []

    content_artifact = agent_input.content_artifact
    script_artifact = agent_input.script_artifact

    if content_artifact is None:
        errors.append("content_artifact is missing.")
    elif not isinstance(content_artifact, ContentArtifact):
        errors.append("content_artifact is not a valid ContentArtifact instance.")

    if script_artifact is None:
        errors.append("script_artifact is missing.")
    elif not isinstance(script_artifact, ScriptArtifact):
        errors.append("script_artifact is not a valid ScriptArtifact instance.")

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

    if content_artifact.mission_id != agent_input.mission_id:
        errors.append(
            f"content_artifact.mission_id '{content_artifact.mission_id}' does "
            f"not match this QualityAgentInput.mission_id "
            f"'{agent_input.mission_id}' -- refusing to consume a "
            f"ContentArtifact belonging to a different mission."
        )

    if script_artifact.mission_id != agent_input.mission_id:
        errors.append(
            f"script_artifact.mission_id '{script_artifact.mission_id}' does "
            f"not match this QualityAgentInput.mission_id "
            f"'{agent_input.mission_id}' -- refusing to consume a "
            f"ScriptArtifact belonging to a different mission."
        )

    if content_artifact.status != "FINAL":
        errors.append(
            f"content_artifact.status '{content_artifact.status}' is not 'FINAL'."
        )

    if script_artifact.status != "FINAL":
        errors.append(
            f"script_artifact.status '{script_artifact.status}' is not 'FINAL'."
        )

    if content_artifact.contract_version not in SUPPORTED_CONTENT_CONTRACT_VERSIONS:
        errors.append(
            f"content_artifact.contract_version "
            f"{content_artifact.contract_version} is not supported by this "
            f"QualityAgent (supported: "
            f"{sorted(SUPPORTED_CONTENT_CONTRACT_VERSIONS)})."
        )

    if script_artifact.contract_version not in SUPPORTED_SCRIPT_CONTRACT_VERSIONS:
        errors.append(
            f"script_artifact.contract_version "
            f"{script_artifact.contract_version} is not supported by this "
            f"QualityAgent (supported: "
            f"{sorted(SUPPORTED_SCRIPT_CONTRACT_VERSIONS)})."
        )

    if script_artifact.source_content_artifact_id != content_artifact.artifact_id:
        errors.append(
            f"script_artifact.source_content_artifact_id "
            f"'{script_artifact.source_content_artifact_id}' does not match "
            f"the supplied content_artifact.artifact_id "
            f"'{content_artifact.artifact_id}' -- this script was not derived "
            f"from this content artifact."
        )

    return errors


def _validate_quality_input(agent_input: QualityAgentInput) -> List[str]:
    errors: List[str] = []

    if not isinstance(agent_input.mission_id, str) or not agent_input.mission_id.strip():
        errors.append("mission_id is missing or empty.")

    profile = agent_input.quality_profile
    if profile is not None:
        if not isinstance(profile, QualityProfile):
            errors.append("quality_profile is not a valid QualityProfile instance.")
        else:
            if not (0 <= profile.pass_threshold <= 100):
                errors.append("quality_profile.pass_threshold must be between 0 and 100.")
            if not (0 <= profile.warning_threshold <= 100):
                errors.append("quality_profile.warning_threshold must be between 0 and 100.")
            if profile.warning_threshold > profile.pass_threshold:
                errors.append(
                    "quality_profile.warning_threshold must not exceed "
                    "quality_profile.pass_threshold."
                )
            if profile.max_duration_variance_seconds < 0:
                errors.append(
                    "quality_profile.max_duration_variance_seconds must not be negative."
                )

    return errors


def _integrity_findings(agent_input: QualityAgentInput) -> Tuple[Finding, ...]:
    """
    Recomputes both artifacts' content_hash from their own real fields
    (never trusting the declared value) via the REAL, imported hash
    functions from content_agent.py. The ScriptArtifact recomputation
    uses `content_artifact.content_hash` AS ACTUALLY SUPPLIED in this
    call (not merely `script_artifact.source_content_artifact_id`,
    an id) -- this catches BOTH internal tampering of either artifact's
    own fields AND a script/content pair that do not truly share the
    same content, even if their ids happen to line up. Returns an empty
    tuple if both pass.
    """

    content = agent_input.content_artifact
    script = agent_input.script_artifact
    raw: List[Tuple[QualityFindingSeverity, str, str, str, str, Optional[str]]] = []

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
            raw.append(
                (
                    QualityFindingSeverity.CRITICAL,
                    INTEGRITY_CATEGORY,
                    "CONTENT_ARTIFACT_HASH_MISMATCH",
                    "content_artifact.content_hash does not match a "
                    "recomputed hash of its own fields -- possible "
                    "tampering or corruption.",
                    content.artifact_id,
                    "content_hash",
                )
            )
    except Exception as error:  # noqa: BLE001 -- surfaced, never masked
        raw.append(
            (
                QualityFindingSeverity.CRITICAL,
                INTEGRITY_CATEGORY,
                "CONTENT_ARTIFACT_INTEGRITY_UNVERIFIABLE",
                f"content_artifact integrity could not be verified: {error}",
                content.artifact_id,
                None,
            )
        )

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
            raw.append(
                (
                    QualityFindingSeverity.CRITICAL,
                    INTEGRITY_CATEGORY,
                    "SCRIPT_ARTIFACT_HASH_MISMATCH",
                    "script_artifact.content_hash does not match a "
                    "recomputed hash of its own fields bound to the "
                    "supplied content_artifact -- possible tampering, "
                    "corruption, or a mismatched content/script pair.",
                    script.artifact_id,
                    "content_hash",
                )
            )
    except Exception as error:  # noqa: BLE001 -- surfaced, never masked
        raw.append(
            (
                QualityFindingSeverity.CRITICAL,
                INTEGRITY_CATEGORY,
                "SCRIPT_ARTIFACT_INTEGRITY_UNVERIFIABLE",
                f"script_artifact integrity could not be verified: {error}",
                script.artifact_id,
                None,
            )
        )

    return _assign_finding_ids(raw)


# ----------------------------------------------------------------------
# SCORE / STATUS DECISION (P3.7 Sections 13/14) -- fully deterministic,
# documented. PASS requires ZERO findings above INFO severity (INFO is
# purely informational and never blocks a clean PASS). Any CRITICAL
# finding, or a score below warning_threshold, is FAIL. Everything else
# is PASS_WITH_WARNINGS.
# ----------------------------------------------------------------------


def _compute_score(findings: Tuple[Finding, ...]) -> int:
    deductions = sum(SEVERITY_DEDUCTIONS[finding.severity] for finding in findings)
    return max(0, 100 - deductions)


def _decide_status(
    findings: Tuple[Finding, ...], score: int, profile: QualityProfile
) -> QualityAgentStatus:
    has_critical = any(
        finding.severity == QualityFindingSeverity.CRITICAL for finding in findings
    )
    if has_critical:
        return QualityAgentStatus.FAIL

    if score < profile.warning_threshold:
        return QualityAgentStatus.FAIL

    non_info_findings = [
        finding for finding in findings if finding.severity != QualityFindingSeverity.INFO
    ]
    if not non_info_findings and score >= profile.pass_threshold:
        return QualityAgentStatus.PASS

    return QualityAgentStatus.PASS_WITH_WARNINGS


# ----------------------------------------------------------------------
# HASH / INTEGRITY (P3.7 Section 17) -- deterministic, stable, canonical.
# Excludes artifact_id/created_at (technical/temporal).
# ----------------------------------------------------------------------


def compute_quality_artifact_hash(
    mission_id: str,
    quality_status: QualityAgentStatus,
    score: Optional[int],
    findings: Tuple[Finding, ...],
    evaluated_artifacts: Tuple[EvaluatedArtifactReference, ...],
    profile: QualityProfile,
    contract_version: int,
) -> str:
    canonical = {
        "mission_id": mission_id,
        "quality_status": quality_status.value,
        "score": score,
        "findings": _findings_to_dicts(findings),
        "evaluated_artifacts": [_reference_to_dict(ref) for ref in evaluated_artifacts],
        "profile": _profile_to_dict(profile),
        "contract_version": contract_version,
    }
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# IDEMPOTENCY (P3.7 Section 20) -- pure function, no store, no
# persistence, no database.
# ----------------------------------------------------------------------


def compute_quality_idempotency_key(agent_input: QualityAgentInput) -> str:
    content = agent_input.content_artifact
    script = agent_input.script_artifact
    profile = agent_input.quality_profile or DEFAULT_QUALITY_PROFILE

    canonical = {
        "mission_id": agent_input.mission_id,
        "content_artifact_id": getattr(content, "artifact_id", None),
        "content_artifact_version": getattr(content, "version", None),
        "content_content_hash": getattr(content, "content_hash", None),
        "script_artifact_id": getattr(script, "artifact_id", None),
        "script_artifact_version": getattr(script, "version", None),
        "script_content_hash": getattr(script, "content_hash", None),
        "profile": _profile_to_dict(profile),
        "constraints": list(agent_input.constraints),
    }
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# QUALITY AGENT (P3.7 Section 4)
# ----------------------------------------------------------------------


class QualityAgent:
    """
    AI DIRECTOR — Quality Agent v1.0 (P3.7)

    Depends on `agents.content_agent` for the ContentArtifact/
    ScriptArtifact contracts/whitelists/hash functions it must consume,
    and on `agents.strategy_agent` ONLY for the platform/language
    whitelists it needs to independently re-verify content metadata --
    no dependency on Higgsfield, any P2 gate/authority module, the
    Director, or any event bus.
    """

    def __init__(self, engine: Optional[QualityEngine] = None):
        self.engine = engine or DeterministicQualityEngine()

    def run(self, agent_input: QualityAgentInput) -> QualityAgentOutput:
        """
        Order: (1) artifact dependency validation -> REJECTED; (2) this
        agent's own input validation -> VALIDATION_ERROR; (3) integrity
        (hash recomputation) -> INTEGRITY_FAILURE, WITH a QualityArtifact
        recording the fact; (4) engine evaluation -> PASS /
        PASS_WITH_WARNINGS / FAIL, WITH a fully populated QualityArtifact.
        Never mutates `content_artifact`/`script_artifact`. Never emits
        an event. Never constructs any authority object.
        """

        mission_id = (
            agent_input.mission_id if isinstance(agent_input.mission_id, str) else ""
        )

        dependency_errors = _validate_artifact_dependencies(agent_input)
        if dependency_errors:
            return QualityAgentOutput(
                mission_id=mission_id,
                status=QualityAgentStatus.REJECTED,
                errors=tuple(dependency_errors),
            )

        input_errors = _validate_quality_input(agent_input)
        if input_errors:
            return QualityAgentOutput(
                mission_id=mission_id,
                status=QualityAgentStatus.VALIDATION_ERROR,
                errors=tuple(input_errors),
            )

        profile = agent_input.quality_profile or DEFAULT_QUALITY_PROFILE
        content = agent_input.content_artifact
        script = agent_input.script_artifact

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
        )

        integrity_findings = _integrity_findings(agent_input)
        if integrity_findings:
            artifact_id = uuid.uuid4().hex
            created_at = datetime.now(timezone.utc).isoformat()

            content_hash = compute_quality_artifact_hash(
                mission_id=agent_input.mission_id,
                quality_status=QualityAgentStatus.INTEGRITY_FAILURE,
                score=None,
                findings=integrity_findings,
                evaluated_artifacts=evaluated_artifacts,
                profile=profile,
                contract_version=CONTRACT_VERSION,
            )

            quality_artifact = QualityArtifact(
                artifact_id=artifact_id,
                artifact_type=QUALITY_ARTIFACT_TYPE,
                mission_id=agent_input.mission_id,
                created_at=created_at,
                version=ARTIFACT_VERSION,
                status="FINAL",
                quality_status=QualityAgentStatus.INTEGRITY_FAILURE,
                score=None,
                findings=integrity_findings,
                evaluated_artifacts=evaluated_artifacts,
                profile=profile,
                producer_agent=AGENT_ID,
                producer_version=AGENT_VERSION,
                contract_version=CONTRACT_VERSION,
                content_hash=content_hash,
            )

            return QualityAgentOutput(
                mission_id=agent_input.mission_id,
                status=QualityAgentStatus.INTEGRITY_FAILURE,
                quality_artifact=quality_artifact,
            )

        context = QualityEvaluationContext(
            content_artifact=content, script_artifact=script, profile=profile
        )
        result = self.engine.evaluate(context)

        score = _compute_score(result.findings)
        quality_status = _decide_status(result.findings, score, profile)

        artifact_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()

        content_hash = compute_quality_artifact_hash(
            mission_id=agent_input.mission_id,
            quality_status=quality_status,
            score=score,
            findings=result.findings,
            evaluated_artifacts=evaluated_artifacts,
            profile=profile,
            contract_version=CONTRACT_VERSION,
        )

        quality_artifact = QualityArtifact(
            artifact_id=artifact_id,
            artifact_type=QUALITY_ARTIFACT_TYPE,
            mission_id=agent_input.mission_id,
            created_at=created_at,
            version=ARTIFACT_VERSION,
            status="FINAL",
            quality_status=quality_status,
            score=score,
            findings=result.findings,
            evaluated_artifacts=evaluated_artifacts,
            profile=profile,
            producer_agent=AGENT_ID,
            producer_version=AGENT_VERSION,
            contract_version=CONTRACT_VERSION,
            content_hash=content_hash,
        )

        return QualityAgentOutput(
            mission_id=agent_input.mission_id,
            status=quality_status,
            quality_artifact=quality_artifact,
        )
