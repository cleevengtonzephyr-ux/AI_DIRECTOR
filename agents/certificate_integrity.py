"""
AI DIRECTOR — Certificate Provenance & Integrity Boundary (Phase P3.56)

P3.55's Certificate Verifier compares a presented certificate against
current state (freshness), but never asked a prior question: is the
presented certificate itself the genuine, unmodified output of the
Certificate Issuer? This module studies and closes that boundary.

DEFINITIONS (Section 1, P3.56 mission) -- never merged:

    ISSUER       -- the one component authorized to PRODUCE a
                    certificate: `ProductionActivationReadinessCertificate
                    Issuer` (agents/production_activation_readiness_
                    certificate.py, Phase P3.54, untouched by this
                    phase). Named here as the constant `ISSUER_IDENTITY`.
    CERTIFICATE  -- the immutable proof that Issuer produces.
    VERIFICATION -- checking a certificate's content against CURRENT
                    STATE (Phase P3.55, `certificate_verification.py`,
                    untouched by this phase).
    PROVENANCE   -- evidence that a certificate genuinely originates
                    from the expected Issuer.
    INTEGRITY    -- evidence that a certificate's data has not been
                    altered since it was produced.
    AUTHORITY    -- a wholly separate permission, held exclusively by
                    the existing P2 production mechanisms
                    (GenerationApprovalGate, GenerationJobService,
                    HiggsfieldProvider, ...). Nothing in this module
                    ever grants, checks, or substitutes for it.

AUDIT FINDING (Section 2, P3.56 mission): the repository contains NO
`hmac`, `secrets`, `cryptography`, digital-signing, or "digest"
terminology anywhere (verified by repository-wide search before this
module was written). The ONLY cryptographic primitive in use anywhere
is `hashlib.sha256` for plain CONTENT HASHING -- prompt/asset file
hashes in `agents/production_activation_readiness_certificate.py`
(P3.54) and `agents/release_candidate_identity_lock.py` (P2.18), always
"recompute from the real source, never trust a carried value". This
module reuses that exact convention and introduces NO new dependency,
NO signing key, NO HMAC secret -- per Section 2/14 of the mission,
inventing one would be out of scope, and per Section 5/19, presenting
a bare SHA-256 as a "signature" would be dishonest. See "WHAT THIS DOES
NOT PROVE" below.

HASH/DIGEST vs DIGITAL SIGNATURE vs PROVENANCE (Section 5, P3.56
mission -- read this before using this module):

    A SHA-256 digest of a certificate's canonical content proves only
    that the content is SELF-CONSISTENT with a digest recorded earlier
    (`compute_integrity_digest()` at genuine issuance time, compared
    later by `verify_integrity()`). It detects any POST-ISSUANCE
    MUTATION of the fields. It is NOT a digital signature: it uses no
    private key, no HMAC secret, nothing that an adversary who can
    fabricate a certificate object cannot also recompute over their own
    fabricated fields. It therefore CANNOT authenticate an external
    issuer against a malicious/careless caller who is willing to lie
    about where an object came from.

    Provenance in this module is consequently DEFINITIONAL, not
    cryptographic: `verify_provenance()` checks that a caller's
    `claimed_issuer` string equals the one canonical `ISSUER_IDENTITY`
    this codebase recognizes. A manually constructed
    `ProductionActivationReadinessCertificate` (Section 10 of the
    mission) accompanied by a caller who (incorrectly or dishonestly)
    claims `claimed_issuer == ISSUER_IDENTITY` WILL pass
    `verify_provenance()` -- this is the honest, documented gap the
    mission's Section 19 STOP clause asks to be surfaced rather than
    papered over with a fake sense of cryptographic assurance. A real
    signature (e.g. HMAC with a secret only the real Issuer process
    holds) would close this gap but is a materially larger piece of
    infrastructure (key management, distribution, rotation) than this
    phase's minimal, dependency-free, read-only scope justifies --
    per Section 19, this is DOCUMENTED, not improvised.

WHAT THIS MODULE IS NOT AND NEVER DOES (same posture as P3.54/P3.55):
- Never constructs a Gate/Evaluator/Issuer/Provider/Authorization/
  Activation object of any kind; never imports a P2 execution module.
- Never calls `create_job()`, `.execute()`, `prepare_activation()`,
  `validate_activation()`, or `consume()`.
- Never mutates a certificate; every function here is a pure read of
  already-constructed, frozen objects.
- `is_trustworthy_and_current() == True` on the combined report below
  is NOT authorization, activation, or execution permission -- exactly
  like a `READY` certificate itself is not (P3.54 docstring) and a
  `VALID` freshness result is not (P3.55 docstring).
- Never wired into `director.py` or any existing entry point.
- Does NOT modify `agents/production_activation_readiness_certificate.py`
  (a PROTECTED_P2_FILES entry): no new field is added to the frozen
  certificate dataclass. Provenance/integrity evidence is carried
  ALONGSIDE the certificate by the caller (the digest from
  `compute_integrity_digest()`, the issuer name from `ISSUER_IDENTITY`),
  never embedded into the protected class itself.

FRESHNESS STAYS SEPARATE (Section 9, P3.56 mission): a certificate can
be integrity-valid-but-stale, integrity-valid-and-current, altered,
provenance-UNKNOWN, or structurally not applicable to the current
request -- `CertificateProvenanceIntegrityReport` keeps
`provenance_result`/`integrity_result`/`freshness_result` as three
independent fields, never fused into one opaque verdict.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.certificate_verification import CertificateVerificationResult, verify_certificate
from agents.production_activation_readiness_certificate import ProductionActivationReadinessCertificate

# The single canonical, logical issuer identity this codebase
# recognizes -- deliberately never "user"/"provider"/"authorization"/
# "activation" (Section 6, P3.56 mission): the issuer is the PROOF
# component, nothing else.
ISSUER_IDENTITY = "ProductionActivationReadinessCertificateIssuer"


class ProvenanceResult(str, Enum):
    VALID_PROVENANCE = "VALID_PROVENANCE"
    INVALID_PROVENANCE = "INVALID_PROVENANCE"
    UNKNOWN_PROVENANCE = "UNKNOWN_PROVENANCE"


class IntegrityResult(str, Enum):
    INTEGRITY_VALID = "INTEGRITY_VALID"
    INTEGRITY_INVALID = "INTEGRITY_INVALID"
    UNKNOWN_INTEGRITY = "UNKNOWN_INTEGRITY"


def canonical_certificate_payload(certificate: ProductionActivationReadinessCertificate) -> str:
    """
    Deterministic canonical serialization (Section 4, P3.56 mission):
    the same certificate always produces the exact same string,
    independent of field-declaration order. Built with
    `dataclasses.asdict()` (recurses into the nested `readiness_report`
    dataclass automatically) and `json.dumps(sort_keys=True)` (orders
    every key, at every nesting level, alphabetically -- field order
    never affects the result). `ensure_ascii=True` makes Unicode
    handling explicit/escaped rather than encoding-dependent.
    `default=str` is a defensive fallback only -- every field on this
    certificate is already a plain str/int/float/bool/None/tuple/list,
    never actually exercised in practice, added so an unexpected future
    field type degrades to a stable string form instead of raising.

    Never mutates `certificate`. Raises `TypeError` for anything that
    is not a real `ProductionActivationReadinessCertificate` --
    fail-closed, never silently hashes an unrelated object.
    """

    if not isinstance(certificate, ProductionActivationReadinessCertificate):
        raise TypeError(
            "canonical_certificate_payload() requires a "
            "ProductionActivationReadinessCertificate instance."
        )

    payload = dataclasses.asdict(certificate)
    return json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)


def compute_integrity_digest(certificate: ProductionActivationReadinessCertificate) -> str:
    """
    The TRUSTED reference digest a caller should capture IMMEDIATELY
    upon receiving a certificate from the Issuer (genuine issuance
    time) and keep alongside it -- this module introduces no new
    persistence of its own (Section 14, P3.56 mission: minimal, no new
    storage). Later, `verify_integrity()` recomputes this SAME function
    over the certificate AS PRESENTED and compares -- the identical
    "never trust a carried value, always recompute from the real
    source" pattern `agents/release_candidate_identity_lock.py` already
    established for prompt/asset hashes (Phase P2.18).

    NOT A SIGNATURE -- see module docstring "HASH/DIGEST vs DIGITAL
    SIGNATURE vs PROVENANCE". Proves content self-consistency with a
    digest recorded earlier, never proves WHO produced it.
    """

    return hashlib.sha256(canonical_certificate_payload(certificate).encode("utf-8")).hexdigest()


def verify_integrity(
    certificate: ProductionActivationReadinessCertificate,
    expected_integrity_digest: Optional[str],
) -> Tuple[IntegrityResult, Tuple[str, ...]]:
    """
    Pure, read-only. Recomputes `compute_integrity_digest(certificate)`
    fresh and compares to `expected_integrity_digest` -- NEVER trusts a
    digest carried on the certificate itself (it carries none; see
    module docstring). Fail-closed: no expected digest supplied ->
    `UNKNOWN_INTEGRITY`, never `INTEGRITY_VALID`.
    """

    if not expected_integrity_digest:
        return (
            IntegrityResult.UNKNOWN_INTEGRITY,
            (
                "no expected_integrity_digest was supplied -- integrity "
                "cannot be established; never treated as valid.",
            ),
        )

    if not isinstance(certificate, ProductionActivationReadinessCertificate):
        return (
            IntegrityResult.INTEGRITY_INVALID,
            ("certificate is not a ProductionActivationReadinessCertificate instance.",),
        )

    actual_digest = compute_integrity_digest(certificate)
    if actual_digest != expected_integrity_digest:
        return (
            IntegrityResult.INTEGRITY_INVALID,
            (
                f"recomputed integrity digest '{actual_digest}' does not match "
                f"the expected digest '{expected_integrity_digest}' -- certificate "
                f"content changed since the digest was recorded.",
            ),
        )

    return IntegrityResult.INTEGRITY_VALID, ()


def verify_provenance(claimed_issuer: Optional[str]) -> Tuple[ProvenanceResult, Tuple[str, ...]]:
    """
    DEFINITIONAL, NOT CRYPTOGRAPHIC -- see module docstring. Confirms
    the caller's CLAIM names the one canonical issuer identity this
    codebase recognizes. Cannot authenticate the actual code path that
    produced the object (documented gap). Fail-closed: no claim
    supplied -> `UNKNOWN_PROVENANCE`, never `VALID_PROVENANCE`.
    """

    if not claimed_issuer:
        return (
            ProvenanceResult.UNKNOWN_PROVENANCE,
            (
                "no claimed_issuer was supplied -- provenance cannot be "
                "established; never treated as valid.",
            ),
        )

    if claimed_issuer != ISSUER_IDENTITY:
        return (
            ProvenanceResult.INVALID_PROVENANCE,
            (
                f"claimed_issuer '{claimed_issuer}' does not match the canonical "
                f"issuer identity '{ISSUER_IDENTITY}'.",
            ),
        )

    return ProvenanceResult.VALID_PROVENANCE, ()


@dataclass(frozen=True)
class CertificateProvenanceIntegrityReport:
    """
    Immutable, read-only. Keeps provenance/integrity/freshness as THREE
    SEPARATE fields (Section 9, P3.56 mission) -- never fused into one
    opaque verdict. Never itself an authority, approval, activation, or
    execution artifact.
    """

    provenance_result: ProvenanceResult
    integrity_result: IntegrityResult
    freshness_result: Optional[CertificateVerificationResult]
    reasons: Tuple[str, ...]

    def is_trustworthy_and_current(self) -> bool:
        """`True` only if provenance is VALID, integrity is VALID, and
        freshness is VALID -- convenience for readability ONLY. NEVER
        treat this as authorization, activation, or execution
        permission (see module docstring)."""
        return (
            self.provenance_result == ProvenanceResult.VALID_PROVENANCE
            and self.integrity_result == IntegrityResult.INTEGRITY_VALID
            and self.freshness_result == CertificateVerificationResult.VALID
        )


def verify_certificate_provenance_and_integrity(
    reference: ProductionActivationReadinessCertificate,
    current: Optional[ProductionActivationReadinessCertificate],
    claimed_issuer: Optional[str],
    expected_integrity_digest: Optional[str],
) -> CertificateProvenanceIntegrityReport:
    """
    Orchestrates, WITHOUT fusing (Section 9): provenance -> integrity
    -> (only if integrity is INTEGRITY_VALID) freshness, delegating
    freshness entirely to the untouched P3.55
    `agents.certificate_verification.verify_certificate()`. Per Section
    7 of the P3.56 mission, `reference`'s content is only reliable
    enough to compare against `current` once integrity is established
    -- if integrity is anything other than `INTEGRITY_VALID`,
    `freshness_result` stays `None` (never guessed, never silently
    computed anyway) and `reasons` explains why.

    Pure, read-only: never mutates `reference`/`current`, never
    constructs a Gate/Evaluator/Issuer/Provider, never calls
    `create_job()`/`.execute()`/`prepare_activation()`/
    `validate_activation()`/`consume()`.
    """

    reasons: List[str] = []

    provenance_result, provenance_reasons = verify_provenance(claimed_issuer)
    reasons.extend(provenance_reasons)

    integrity_result, integrity_reasons = verify_integrity(reference, expected_integrity_digest)
    reasons.extend(integrity_reasons)

    freshness_result: Optional[CertificateVerificationResult] = None

    if integrity_result != IntegrityResult.INTEGRITY_VALID:
        reasons.append(
            "freshness was not evaluated: certificate content is not yet "
            "established as integrity-valid (Section 7, P3.56 mission -- "
            "content is never trusted before integrity is confirmed)."
        )
    elif current is None:
        reasons.append("freshness was not evaluated: no 'current' certificate was supplied.")
    else:
        freshness_report = verify_certificate(reference, current)
        freshness_result = freshness_report.result
        reasons.extend(freshness_report.reasons)

    return CertificateProvenanceIntegrityReport(
        provenance_result=provenance_result,
        integrity_result=integrity_result,
        freshness_result=freshness_result,
        reasons=tuple(reasons),
    )
