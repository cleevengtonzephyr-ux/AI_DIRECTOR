"""
AI DIRECTOR — Certificate Verification / Freshness Validation (Phase P3.55)

P3.54 introduced `ProductionActivationReadinessCertificate`: an
IMMUTABLE PROOF of the state observed at preflight. It answers "was a
certificate issued for this request, and what did it observe?". It
never answers a different, later question:

    IS THIS EXISTING CERTIFICATE STILL VALID FOR THE STATE PRESENTED
    RIGHT NOW?

`certificate_still_matches()` (already in
agents/production_activation_readiness_certificate.py, untouched by
this phase) partially answers this for identity fields against a raw
`GenerationRequest` (prompt/asset/video_plan/model/duration/
resolution/aspect_ratio), returning a bare `(bool, reasons)`. This
module closes the remaining boundary the P3.55 mission identifies:
a CERTIFICATE-to-CERTIFICATE comparison across every field the
mission enumerates (including `mission_id`, `provider_identity`,
`estimated_cost`, `readiness_result`, `contract_version`), with an
EXPLICIT result taxonomy (VALID / STALE / MISMATCH / UNKNOWN /
INVALID) instead of a single boolean -- so a caller can distinguish
"the artifacts changed" (MISMATCH) from "the artifacts are the same
but the verdict about them has changed" (STALE) from "we cannot tell"
(UNKNOWN, never silently promoted to VALID) from "one of the two
certificates is structurally broken" (INVALID).

STOP -- WHAT THIS MODULE IS NOT AND NEVER DOES:
- It is NOT a second ApprovalGate, Evaluator, or Issuer. It never
  constructs a `GenerationApprovalGate`, `ActivationReadinessEvaluator`,
  `ProductionActivationReadinessCertificateIssuer`, or any Provider --
  it accepts two ALREADY-ISSUED `ProductionActivationReadinessCertificate`
  instances (a `reference` -- the certificate being checked -- and a
  `current` -- a fresh certificate the CALLER already obtained, by
  whatever means the caller already had, typically re-issuing via the
  unmodified P3.54 Issuer) and does nothing but compare their fields.
- It NEVER reads a file, a prompt, an asset, the network, or a clock.
  Purely a function of its two arguments -- deterministic, side-effect
  free, callable any number of times with identical results.
- It NEVER mutates either certificate (both are already frozen
  dataclasses; this module holds no reference to either beyond the
  single call it is invoked within).
- It NEVER calls `create_job()`, `GenerationJobService.execute()`,
  `prepare_activation()`, `validate_activation()`, or `consume()` --
  it does not import any module capable of reaching them.
- A `VALID` result is NOT an authorization, activation, or execution
  permission -- exactly like a `READY` certificate itself (see P3.54
  module docstring). It only means: "the two certificates describe the
  same artifacts/parameters, and their observed verdicts agree."
- This module is NEVER wired into `director.py` or any existing entry
  point -- purely additive, opt-in, exactly like P3.54's Issuer.

NO TTL (Section 6, P3.55 mission): freshness is determined by binding
of artifacts/parameters/verdict between the two certificates, never by
elapsed wall-clock time. `issued_at` on both certificates is carried
into the report for observability only -- it never drives the result.

FAIL-CLOSED UNKNOWN (Section 7, P3.55 mission): whenever a field
needed for comparison is itself absent (`None`/empty) on either
certificate, the result can never become `VALID`. Missing evidence is
`UNKNOWN`, never silently treated as a match.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.production_activation_readiness_certificate import (
    CONTRACT_VERSION,
    ProductionActivationReadinessCertificate,
)


class CertificateVerificationResult(str, Enum):
    """Explicit taxonomy for "is this certificate still applicable?" --
    see module docstring. Never confused with `GenerationApprovalDecision`
    (agents/generation_approval_gate.py) or `readiness_result` on the
    certificate itself: this is a verification-of-a-proof outcome, not
    an approval/readiness outcome."""

    VALID = "VALID"
    STALE = "STALE"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"


@dataclass(frozen=True)
class CertificateVerificationReport:
    """Immutable, read-only result of one `verify_certificate()` call.
    Never itself an authority, approval, or activation artifact --
    purely descriptive of the comparison it just performed."""

    result: CertificateVerificationResult
    reference_certificate_id: str
    current_certificate_id: str
    reference_issued_at: str
    current_issued_at: str
    reasons: Tuple[str, ...]

    def is_valid(self) -> bool:
        """`True` only if `result == VALID`. NEVER treat this as
        authorization, activation, or execution permission (see module
        docstring)."""
        return self.result == CertificateVerificationResult.VALID


def _structural_violations(
    reference: ProductionActivationReadinessCertificate,
    current: ProductionActivationReadinessCertificate,
) -> List[str]:
    """Fail-closed structural check: is each argument actually a real,
    minimally well-formed certificate of the CURRENT contract version?
    A schema/version mismatch is never treated as comparable -- issuing
    a NEW certificate is the only correct remedy (see module docstring;
    never patched, never coerced)."""

    violations: List[str] = []

    for label, cert in (("reference", reference), ("current", current)):
        if not isinstance(cert, ProductionActivationReadinessCertificate):
            violations.append(
                f"{label} is not a ProductionActivationReadinessCertificate instance."
            )
            continue
        if not cert.certificate_id:
            violations.append(f"{label} certificate_id is missing/empty.")
        if not cert.request_id:
            violations.append(f"{label} request_id is missing/empty.")
        if cert.contract_version != CONTRACT_VERSION:
            violations.append(
                f"{label} contract_version ({cert.contract_version}) does not "
                f"match the current CONTRACT_VERSION ({CONTRACT_VERSION}) -- "
                f"not comparable under this verifier."
            )
        # P3.72 scope binding: the Issuer always embeds a readiness_report
        # evaluated for the certificate's own request_id. A certificate
        # carrying another request's report is self-contradictory -- never
        # comparable, whatever its digest (plain duck-typed field read:
        # this layer never imports agents.activation_readiness).
        try:
            report_request_id = cert.readiness_report.request_id
        except AttributeError:
            report_request_id = None
        if report_request_id != cert.request_id:
            violations.append(
                f"{label} embedded readiness_report is bound to request "
                f"{report_request_id!r}, not to the certificate's own request "
                f"{cert.request_id!r} -- cross-request scope substitution."
            )

    return violations


def _identity_and_parameter_comparison(
    reference: ProductionActivationReadinessCertificate,
    current: ProductionActivationReadinessCertificate,
) -> Tuple[List[str], List[str]]:
    """Compares every identity/parameter field the P3.55 mission
    enumerates. Returns `(mismatch_reasons, unknown_reasons)` --
    NEVER mutates either certificate. A field missing on either side is
    reported as UNKNOWN evidence, never silently treated as a match."""

    mismatch: List[str] = []
    unknown: List[str] = []

    if reference.request_id != current.request_id:
        mismatch.append(
            f"request_id changed: '{reference.request_id}' -> '{current.request_id}'."
        )

    if reference.mission_id != current.mission_id:
        mismatch.append(
            f"mission_id changed: {reference.mission_id!r} -> {current.mission_id!r}."
        )

    if reference.prompt_identity is None or current.prompt_identity is None:
        unknown.append("prompt identity unavailable on one or both certificates.")
    elif reference.prompt_identity != current.prompt_identity:
        mismatch.append("prompt identity changed since the reference certificate was issued.")

    if not reference.asset_identity or not current.asset_identity:
        unknown.append("asset identity unavailable on one or both certificates.")
    elif reference.asset_identity != current.asset_identity:
        mismatch.append("asset identity changed since the reference certificate was issued.")

    if reference.video_plan_identity is None or current.video_plan_identity is None:
        unknown.append("VideoPlan identity unavailable on one or both certificates.")
    elif reference.video_plan_identity != current.video_plan_identity:
        mismatch.append("VideoPlan identity changed since the reference certificate was issued.")

    if not reference.provider_identity or not current.provider_identity:
        unknown.append("provider identity unavailable on one or both certificates.")
    elif reference.provider_identity != current.provider_identity:
        mismatch.append(
            f"provider identity changed: '{reference.provider_identity}' -> "
            f"'{current.provider_identity}'."
        )

    if not reference.model or not current.model:
        unknown.append("model unavailable on one or both certificates.")
    elif reference.model != current.model:
        mismatch.append(f"model changed: '{reference.model}' -> '{current.model}'.")

    if not reference.duration or not current.duration:
        unknown.append("duration unavailable on one or both certificates.")
    elif reference.duration != current.duration:
        mismatch.append(f"duration changed: {reference.duration} -> {current.duration}.")

    if not reference.resolution or not current.resolution:
        unknown.append("resolution unavailable on one or both certificates.")
    elif reference.resolution != current.resolution:
        mismatch.append(
            f"resolution changed: '{reference.resolution}' -> '{current.resolution}'."
        )

    if not reference.aspect_ratio or not current.aspect_ratio:
        unknown.append("aspect_ratio unavailable on one or both certificates.")
    elif reference.aspect_ratio != current.aspect_ratio:
        mismatch.append(
            f"aspect_ratio changed: '{reference.aspect_ratio}' -> '{current.aspect_ratio}'."
        )

    if reference.estimated_cost is None or current.estimated_cost is None:
        unknown.append("estimated cost unavailable on one or both certificates.")
    elif reference.estimated_cost != current.estimated_cost:
        mismatch.append(
            f"estimated cost changed: {reference.estimated_cost} -> {current.estimated_cost}."
        )

    return mismatch, unknown


def _state_drift(
    reference: ProductionActivationReadinessCertificate,
    current: ProductionActivationReadinessCertificate,
) -> List[str]:
    """Same artifacts/parameters, but has the OBSERVED VERDICT about
    them changed since the reference certificate was issued? This is
    STALE, never MISMATCH -- nothing was substituted, the world simply
    moved on (see module docstring)."""

    reasons: List[str] = []

    if reference.readiness_result != current.readiness_result:
        reasons.append(
            f"readiness_result changed: '{reference.readiness_result}' -> "
            f"'{current.readiness_result}'."
        )

    if reference.approval_decision != current.approval_decision:
        reasons.append(
            f"approval_decision changed: '{reference.approval_decision}' -> "
            f"'{current.approval_decision}'."
        )

    return reasons


def verify_certificate(
    reference: ProductionActivationReadinessCertificate,
    current: ProductionActivationReadinessCertificate,
) -> CertificateVerificationReport:
    """
    Pure, read-only comparison of `reference` (the certificate being
    checked) against `current` (a certificate the CALLER already
    obtained representing the present state -- this function never
    issues one itself). Never mutates either argument. Never
    authorizes, activates, or executes anything -- see module
    docstring.

    Precedence (fail-closed, never permits a substitution to slip
    through as merely "stale", and never lets missing evidence read as
    a match):

        1. INVALID  -- either argument is structurally broken or was
                       issued under a different contract version.
        2. MISMATCH -- an identity/parameter field genuinely differs.
        3. UNKNOWN  -- evidence needed for comparison is missing on
                       either side, OR either certificate itself
                       carries `unknown_state=True`
                       (EXECUTION_STATE_UNKNOWN) -- never promoted to
                       VALID, per P3.54's own UNKNOWN semantics.
        4. STALE    -- identity/parameters match, but the observed
                       verdict (`readiness_result`/`approval_decision`)
                       has changed.
        5. VALID    -- everything compared matches.
    """

    reference_id = getattr(reference, "certificate_id", "") or ""
    current_id = getattr(current, "certificate_id", "") or ""
    reference_issued_at = getattr(reference, "issued_at", "") or ""
    current_issued_at = getattr(current, "issued_at", "") or ""

    def _report(result: CertificateVerificationResult, reasons: Tuple[str, ...]) -> CertificateVerificationReport:
        return CertificateVerificationReport(
            result=result,
            reference_certificate_id=reference_id,
            current_certificate_id=current_id,
            reference_issued_at=reference_issued_at,
            current_issued_at=current_issued_at,
            reasons=reasons,
        )

    structural_reasons = _structural_violations(reference, current)
    if structural_reasons:
        return _report(CertificateVerificationResult.INVALID, tuple(structural_reasons))

    mismatch_reasons, unknown_reasons = _identity_and_parameter_comparison(reference, current)

    if mismatch_reasons:
        return _report(CertificateVerificationResult.MISMATCH, tuple(mismatch_reasons))

    if unknown_reasons:
        return _report(CertificateVerificationResult.UNKNOWN, tuple(unknown_reasons))

    if reference.unknown_state or current.unknown_state:
        return _report(
            CertificateVerificationResult.UNKNOWN,
            (
                "one or both certificates carry unknown_state=True "
                "(EXECUTION_STATE_UNKNOWN) -- never convertible to VALID.",
            ),
        )

    stale_reasons = _state_drift(reference, current)
    if stale_reasons:
        return _report(CertificateVerificationResult.STALE, tuple(stale_reasons))

    return _report(CertificateVerificationResult.VALID, ())
