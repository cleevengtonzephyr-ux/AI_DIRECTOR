"""
AI DIRECTOR — Production Activation Readiness Certificate (Phase P3.54)

A Production Activation Readiness Certificate is an IMMUTABLE PROOF of
the state observed at preflight, for exactly one `request_id` (and,
when available, the `mission_id` it belongs to). It grants NO
authority and permits NO execution.

STOP -- WHAT THIS MODULE IS NOT:
- It is NOT a second `GenerationApprovalGate`. It never re-implements
  any of the ten readiness dimensions -- it composes the existing,
  unmodified `ActivationReadinessEvaluator` (Phase P2.24) exactly as
  that module was already designed to be composed, and embeds its
  `ActivationReadinessReport` verbatim.
- It is NOT a second Authorization system. It never constructs a
  `RealGenerationAuthorization` (Phase P2.11) -- it only records
  whether one was already present on the inspected request, via the
  evaluator's own read-only inspection.
- It is NOT a second Activation system. It never calls
  `prepare_activation()`/`validate_activation()`/`consume()` -- at
  most, it performs the same non-mutating `inspect_activation()` the
  evaluator itself already performs when a caller supplies an
  `activation_contract`.
- It is NOT a second persistence authority. Nothing about this
  certificate is written to `ExecutedRequestStore` or any other P2
  store; issuing one has zero side effects on any P2 mechanism.
- It is NOT a second FinalReport authority. It never claims a job was
  created, never sets anything resembling `job_created`/
  `real_provider_called`, and is issued strictly BEFORE any execution
  attempt, never after.
- It NEVER calls `create_job()`, `GenerationJobService.execute()`, or
  any Provider method beyond the same read-only
  `get_account_balance()`/`estimate_cost()` calls the evaluator it
  wraps already performs.
- It is NEVER wired into `director.py` or any existing entry point --
  purely additive, opt-in: a caller who already holds a
  `GenerationApprovalGate`/`ActivationReadinessEvaluator` may choose to
  issue one; nothing in the existing production path does so
  automatically, and this phase introduces no new call site toward
  `create_job()` or `execute()` (verified by the Architecture Drift
  Detector and a dedicated permanent test, see
  tests/test_production_activation_readiness_certificate.py).

SNAPSHOT SEMANTICS (Section 3, P3.54 report):
Every value-bearing field on this certificate is what it says on the
tin -- OBSERVED_AT_PREFLIGHT, at `issued_at`, never a guarantee about
the future. `estimated_cost` is the cost observed at that instant, not
a locked-in price. `approval_decision` is the Gate's decision at that
instant, re-evaluated fresh (the Gate itself never caches). A
certificate never claims CURRENT_RUNTIME_STATE -- callers who need
current state must re-evaluate, or call `certificate_still_matches()`
below, which recomputes fresh and compares, never trusts the old
snapshot's own claim of freshness.

IMMUTABILITY (Section 4): frozen dataclass. If the state changes, the
correct action is to issue a NEW certificate with a NEW
`certificate_id` -- never to mutate this one. No method on this class
or the issuer below ever mutates an already-issued certificate.

UNKNOWN (Section 7): `readiness_result` is `"UNKNOWN"` -- not
`"READY"`, not silently folded into `"NOT_READY"` -- whenever
`GenerationApprovalGate.is_unknown(request_id)` is true at issuance
time. UNKNOWN is never convertible to READY/APPROVED/AUTHORIZED/
ACTIVATED/EXECUTED by this module or by re-issuing a certificate for
the same still-UNKNOWN `request_id` (the underlying Gate remains the
single source of truth for that fact, unchanged).
"""

from __future__ import annotations

import hashlib
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import RequestScopedActivationContract
from agents.activation_readiness import ActivationReadinessEvaluator, ActivationReadinessReport
from agents.generation_approval_gate import GenerationRequest
from agents.generation_cost_service import CostEstimationStatus

CONTRACT_VERSION = 1

# Section 2 -- never store secrets/credentials. Only content hashes,
# ids, and plain scalar generation parameters are ever recorded.
_FORBIDDEN_EVIDENCE_KEY_SUBSTRINGS = ("key", "token", "secret", "credential", "password")


def _sha256_of_file(path: str) -> Optional[str]:
    """Local, minimal utility -- deliberately NOT imported from
    agents/release_candidate_identity_lock.py (a private, underscore-
    prefixed helper there, never intended for cross-module reuse).
    Returns None if the file cannot be read; never raises, since a
    missing/unreadable asset is itself a fact the certificate should
    be able to represent (via the embedded readiness_report's own
    asset_reasons), not a crash."""

    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return None


def _prompt_identity(request: GenerationRequest) -> Optional[str]:
    if not request.prompt:
        return None
    return hashlib.sha256(request.prompt.encode("utf-8")).hexdigest()


def _asset_identity(request: GenerationRequest) -> Tuple[str, ...]:
    hashes = []
    if request.start_image is not None:
        h = _sha256_of_file(request.start_image.source)
        if h is not None:
            hashes.append(h)
    for ref in request.image_references:
        h = _sha256_of_file(ref.source)
        if h is not None:
            hashes.append(h)
    return tuple(hashes)


@dataclass(frozen=True)
class ProductionActivationReadinessCertificate:
    """
    Immutable, request-scoped (and mission-scoped when available)
    snapshot of preflight state. See module docstring -- this is a
    PROOF ARTIFACT, never an authorization, activation, approval, or
    execution token.
    """

    certificate_id: str
    request_id: str
    mission_id: Optional[str]
    issued_at: str
    contract_version: int

    prompt_identity: Optional[str]
    asset_identity: Tuple[str, ...]
    video_plan_identity: Optional[str]

    provider_identity: str
    model: str
    duration: int
    resolution: str
    aspect_ratio: str

    estimated_cost: Optional[float]
    approval_decision: str
    unknown_state: bool

    readiness_report: ActivationReadinessReport
    readiness_result: str
    blocking_reasons: Tuple[str, ...]

    evidence_references: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)

    # ------------------------------------------------------------------
    # Convenience read-only views -- never independently stored state,
    # always derived from readiness_report/approval_decision above, so
    # nothing here can ever diverge from the single embedded report.
    # ------------------------------------------------------------------

    @property
    def human_authorization_state(self) -> bool:
        return self.readiness_report.authorization_ready

    @property
    def activation_eligibility_state(self) -> bool:
        return self.readiness_report.activation_ready

    @property
    def approval_state(self) -> str:
        return self.approval_decision

    @property
    def replay_state(self) -> bool:
        return self.readiness_report.replay_safe

    @property
    def identity_lock_state(self) -> bool:
        return (
            self.readiness_report.request_identity_ready
            and self.readiness_report.prompt_ready
            and self.readiness_report.asset_ready
        )

    @property
    def execution_boundary_identity(self) -> str:
        """Purely descriptive -- names, never reaches, the one real
        execution boundary (GenerationJobService.execute() ->
        HiggsfieldProvider.create_job(), cf. P3.45)."""
        return "GenerationJobService.execute -> HiggsfieldProvider.create_job"

    def is_ready(self) -> bool:
        """`True` only if `readiness_result == "READY"` -- provided
        purely for readability; NEVER treat this as authorization,
        activation, or execution permission (see module docstring)."""
        return self.readiness_result == "READY"


class ProductionActivationReadinessCertificateIssuer:
    """
    Wraps an already-constructed `ActivationReadinessEvaluator`
    (never constructs the Gate/identity_lock/activation_service
    itself -- that responsibility stays exactly where Phase P2.24 put
    it) and adds ONLY the snapshot/identity fields a certificate needs
    beyond what `ActivationReadinessReport` already provides. Reuses,
    never duplicates, every P2 decision.
    """

    def __init__(
        self,
        evaluator: ActivationReadinessEvaluator,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        if not isinstance(evaluator, ActivationReadinessEvaluator):
            raise ValueError(
                "ProductionActivationReadinessCertificateIssuer requires an "
                "ActivationReadinessEvaluator instance -- it composes, never "
                "reimplements, the ten readiness dimensions."
            )
        self.evaluator = evaluator
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def issue(
        self,
        request: GenerationRequest,
        mission_id: Optional[str] = None,
        activation_contract: Optional[RequestScopedActivationContract] = None,
        video_plan_identity: Optional[str] = None,
        evidence_references: Optional[Dict[str, str]] = None,
    ) -> ProductionActivationReadinessCertificate:
        """
        Issues a fresh, immutable certificate for `request` at this
        instant. Every value is OBSERVED_AT_PREFLIGHT -- see module
        docstring's Snapshot Semantics section. Never mutates
        `request`, never calls `create_job()`, never constructs a
        `RealGenerationAuthorization`, never calls
        `prepare_activation()`/`validate_activation()`.
        """

        gate = self.evaluator.gate

        readiness_report = self.evaluator.evaluate(request, activation_contract=activation_contract)
        approval = gate.evaluate(request)  # fresh, read-only, same Gate the evaluator already uses
        unknown_state = gate.is_unknown(request.request_id)

        cost_result = gate.cost_service.estimate(
            job_type=request.job_type,
            prompt=request.prompt,
            duration=request.duration,
            resolution=request.resolution,
            aspect_ratio=request.aspect_ratio,
        )
        estimated_cost = (
            cost_result.estimate.credits
            if cost_result.status != CostEstimationStatus.ERROR and cost_result.estimate is not None
            else None
        )

        if unknown_state:
            readiness_result = "UNKNOWN"
        elif readiness_report.decision == "READY":
            readiness_result = "READY"
        else:
            readiness_result = "NOT_READY"

        blocking_reasons = list(readiness_report.all_reasons)
        if unknown_state:
            blocking_reasons = [
                f"Request '{request.request_id}' is in EXECUTION_STATE_UNKNOWN -- "
                f"a certificate can never represent this as ready, regardless of "
                f"any other dimension."
            ] + blocking_reasons

        clean_evidence = tuple(
            sorted((str(k), str(v)) for k, v in (evidence_references or {}).items())
        )
        for key, _ in clean_evidence:
            lowered = key.lower()
            if any(bad in lowered for bad in _FORBIDDEN_EVIDENCE_KEY_SUBSTRINGS):
                raise ValueError(
                    f"evidence_references key '{key}' looks like it could hold a "
                    f"secret/credential -- certificates never store these."
                )

        return ProductionActivationReadinessCertificate(
            certificate_id=uuid.uuid4().hex,
            request_id=request.request_id,
            mission_id=mission_id,
            issued_at=self._clock().isoformat(),
            contract_version=CONTRACT_VERSION,
            prompt_identity=_prompt_identity(request),
            asset_identity=_asset_identity(request),
            video_plan_identity=video_plan_identity,
            provider_identity=type(gate.provider).__name__,
            model=request.job_type,
            duration=request.duration,
            resolution=request.resolution,
            aspect_ratio=request.aspect_ratio,
            estimated_cost=estimated_cost,
            approval_decision=approval.decision.value,
            unknown_state=unknown_state,
            readiness_report=readiness_report,
            readiness_result=readiness_result,
            blocking_reasons=tuple(blocking_reasons),
            evidence_references=clean_evidence,
        )


def certificate_still_matches(
    certificate: ProductionActivationReadinessCertificate,
    request: GenerationRequest,
    video_plan_identity: Optional[str] = None,
) -> Tuple[bool, Tuple[str, ...]]:
    """
    Section 9 (Freshness). Recomputes identity fields fresh from
    `request` and compares them to the certificate's stored snapshot
    -- NEVER mutates `certificate`. A mismatch means the certificate no
    longer applies to the current artifacts; the caller must issue a
    NEW certificate (new `certificate_id`), never treat this old one
    as still valid, and never patch it in place.
    """

    reasons = []

    if certificate.request_id != request.request_id:
        reasons.append(
            f"request_id changed: certificate was issued for "
            f"'{certificate.request_id}', current request is "
            f"'{request.request_id}'."
        )
    if certificate.prompt_identity != _prompt_identity(request):
        reasons.append("prompt changed since certificate was issued.")
    if certificate.asset_identity != _asset_identity(request):
        reasons.append("asset(s) changed since certificate was issued.")
    if certificate.video_plan_identity != video_plan_identity:
        reasons.append("video_plan_identity changed since certificate was issued.")
    if certificate.model != request.job_type:
        reasons.append(f"model changed: '{certificate.model}' -> '{request.job_type}'.")
    if certificate.duration != request.duration:
        reasons.append(f"duration changed: {certificate.duration} -> {request.duration}.")
    if certificate.resolution != request.resolution:
        reasons.append(f"resolution changed: '{certificate.resolution}' -> '{request.resolution}'.")
    if certificate.aspect_ratio != request.aspect_ratio:
        reasons.append(f"aspect_ratio changed: '{certificate.aspect_ratio}' -> '{request.aspect_ratio}'.")

    return (len(reasons) == 0, tuple(reasons))
