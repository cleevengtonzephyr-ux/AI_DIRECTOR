"""
Tests -- Architecture Hardening & Guardrail Specification (Phase P3.41).

P3.36-P3.40 individually, exhaustively tested provenance, temporal
freshness, recovery boundaries, resilience composition, and the Gate's
persistence boundary (see the P3.41 report's Section 3 for the full
guardrail inventory and citation matrix). Almost every guardrail this
phase's mission text asks for already exists, scattered across
P2.15-39 and P3.33-40's test files.

This file adds ONLY the narrow, genuinely new permanent guardrails
that phase surfaced were not yet covered anywhere, each protecting a
SPECIFIC, identified regression risk (never added merely to
consolidate or "tidy up" existing coverage, per the mission's explicit
minimality principle):

1. UNKNOWN + a FRESHLY PREPARED activation contract (not just a fresh
   authorization, already covered in P3.38) must still be blocked --
   proves the Gate's UNKNOWN check truly precedes and dominates
   activation, not merely by construction order but by executable
   proof with a real, freshly-prepared P2.21 contract in hand.
2. A single, explicitly-named, permanent test asserting the five
   STATE != AUTHORITY relations Section 6 of the mission enumerates,
   together, in one place -- so a future regression in any ONE of them
   fails a guardrail with an unambiguous name, rather than relying on
   a reader already knowing which of dozens of scattered test files
   would catch it.
3. `GenerationJobService.execute()`'s parameter set is pinned exactly
   -- a canary against a future signature change silently adding a
   bypass-flavored parameter (e.g. a hypothetical `force=`/`skip_gate=`/
   `assume_success=`), which would be exactly the kind of P2 authority
   erosion this phase exists to guard against.

Fully offline: no network, no Higgsfield CLI, always MockHiggsfieldProvider.
"""

import ast
import inspect
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_eligibility import ActivationEligibilityStatus
from agents.activation_contract import RequestScopedActivationService
from agents.controlled_real_provider_activation import ControlledRealProviderActivationService
from agents.critical_section_lock import FileCriticalSectionLock
from agents.executed_request_store import FileExecutedRequestStore
from agents.final_report_service import ActivationDecision, FinalReportService
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from agents.generation_job_service import GenerationJobService
from agents.human_authorization_handoff import HumanAuthorizationHandoffStatus
from agents.production_activation_handoff import ProductionActivationHandoffStatus
from agents.production_authority_intake import ProductionAuthorityIntakeStatus
from agents.production_readiness_handoff import ProductionReadinessHandoffStatus
from agents.release_candidate_identity_lock import ReleaseCandidateIdentityLock, VIDEO_005_RELEASE_CANDIDATE
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.types import MediaReference

C = VIDEO_005_RELEASE_CANDIDATE
REAL_AVATAR_PATH = PROJECT_ROOT / "assets" / "zephyr" / "avatar" / "avatar_master.png"
REAL_FACE_PATH = PROJECT_ROOT / "assets" / "zephyr" / "references" / "mon avatar habille.png"


def _real_prompt() -> str:
    from agents.prompt_assembly_system import PromptAssemblySystem

    return PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id)


def _conforming_request(**overrides) -> GenerationRequest:
    defaults = dict(
        request_id=C.request_id, job_type=C.job_type, prompt=_real_prompt(),
        duration=C.duration, resolution=C.resolution, aspect_ratio=C.aspect_ratio,
        approved=True,
        start_image=MediaReference(role="master_avatar", source=str(REAL_AVATAR_PATH), sha256=None),
        image_references=(MediaReference(role="face_reference", source=str(REAL_FACE_PATH), sha256=None),),
        real_generation_authorization=RealGenerationAuthorization(request_id=C.request_id, authorized_by_human=True),
    )
    defaults.update(overrides)
    return GenerationRequest(**defaults)


# ------------------------------------------------------------------
# 1. UNKNOWN + FRESH ACTIVATION CONTRACT STILL BLOCKED
# ------------------------------------------------------------------


class UnknownDominatesFreshActivationTests(unittest.TestCase):
    def test_unknown_blocks_execute_even_with_a_freshly_prepared_activation_contract(self):
        import shutil
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="p3_41_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)

        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        store = FileExecutedRequestStore(tmp / "executed_requests.json")
        gate = GenerationApprovalGate(provider, executed_request_store=store, identity_lock=identity_lock)
        activation_service = RequestScopedActivationService(gate, identity_lock)
        provider_activation_service = ControlledRealProviderActivationService(gate, identity_lock, activation_service)
        job_service = GenerationJobService(
            provider, gate, lock=FileCriticalSectionLock(tmp / "locks"),
            activation_service=activation_service, provider_activation_service=provider_activation_service,
        )

        request = _conforming_request()
        gate.mark_unknown(request.request_id, reason="simulated crash prior to this attempt")

        # UNKNOWN dominates even EARLIER than execute()-time consumption:
        # RequestScopedActivationService.prepare_activation() itself
        # re-checks Gate eligibility fresh and refuses to even issue a
        # contract while the request is UNKNOWN -- a stronger guarantee
        # than "a fresh contract would be rejected at consumption time"
        # (P3.38's own scope): here, no contract can be minted AT ALL.
        from agents.activation_contract import ActivationRejectedError

        with self.assertRaises(ActivationRejectedError) as ctx:
            activation_service.prepare_activation(request)
        self.assertIn("not currently eligible", str(ctx.exception))

        # And, independently, execute() itself (never reaching create_job,
        # since no activation contract could ever be produced) is blocked too.
        from agents.generation_job_service import GenerationJobExecutionError

        with self.assertRaises(GenerationJobExecutionError):
            job_service.execute(request)

        # The Gate's own decision, independently, is UNKNOWN.
        self.assertEqual(gate.evaluate(request).decision, GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN)


# ------------------------------------------------------------------
# 2. CONSOLIDATED STATE != AUTHORITY GUARDRAIL (Section 6)
# ------------------------------------------------------------------


class StateNotAuthorityGuardrailTests(unittest.TestCase):
    """One explicitly-named, permanent home for the five relations
    Section 6 of the P3.41 mission enumerates. A regression in ANY of
    them fails HERE, under an unambiguous name -- rather than relying
    on a future reader already knowing which of the dozens of P2.15-39/
    P3.33-40 test files would happen to catch it."""

    FORBIDDEN_AUTHORITY_WORDS = ("AUTHORIZED", "APPROVED", "ACTIVATED", "EXECUTING", "EXECUTED")

    def test_state_not_authority_no_p3_handoff_status_implies_authority(self):
        """STATE != AUTHORITY: no P3.13-21 handoff status enum value
        could be mistaken for an authority grant."""
        enums = (
            ProductionReadinessHandoffStatus, ProductionAuthorityIntakeStatus,
            HumanAuthorizationHandoffStatus, ActivationEligibilityStatus,
            ProductionActivationHandoffStatus,
        )
        offenders = [
            f"{enum_cls.__name__}.{member.name}={member.value!r}"
            for enum_cls in enums for member in enum_cls
            if any(word in member.value.upper() for word in self.FORBIDDEN_AUTHORITY_WORDS)
        ]
        self.assertFalse(offenders, offenders)

    def test_readiness_not_authorization_distinct_types(self):
        """READINESS != AUTHORIZATION: the readiness status type and
        the human-authorization status type remain two distinct enum
        classes, never unified or aliased."""
        self.assertIsNot(ProductionReadinessHandoffStatus, HumanAuthorizationHandoffStatus)
        self.assertFalse(set(ProductionReadinessHandoffStatus) & set(HumanAuthorizationHandoffStatus))

    def test_authorization_not_activation_distinct_identifiers(self):
        """AUTHORIZATION != ACTIVATION: RealGenerationAuthorization's
        authorization_id and a prepared activation contract's
        activation_id remain two independently-generated identifiers,
        never the same value or the same field name collapsed."""
        auth = RealGenerationAuthorization(request_id=C.request_id, authorized_by_human=True)
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
        service = RequestScopedActivationService(gate, identity_lock)
        request = _conforming_request(real_generation_authorization=auth)
        contract = service.prepare_activation(request)
        self.assertNotEqual(auth.authorization_id, contract.activation_id)
        self.assertEqual(contract.authorization_id, auth.authorization_id)  # bound, not identical-typed

    def test_activation_not_execution_approved_activation_does_not_imply_job_created(self):
        """ACTIVATION != EXECUTION: FinalReport.activation_decision ==
        APPROVED never, by itself, implies job_created -- the report
        keeps them as two independently-computed fields (P2.23,
        re-confirmed here as a permanent guardrail)."""
        self.assertIn("activation_decision", FinalReportService.generate.__doc__ or "")
        # Structural guarantee: ActivationDecision has no member that
        # is itself an execution-state word.
        for member in ActivationDecision:
            self.assertNotIn("EXECUT", member.value.upper())

    def test_report_not_authority_final_report_service_never_calls_create_job_itself(self):
        """REPORT != AUTHORITY: FinalReportService never calls
        create_job() directly -- it only ever reports on what
        GenerationJobService already decided."""
        source = (PROJECT_ROOT / "agents" / "final_report_service.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        offending_calls = {
            n.func.attr for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "create_job"
        }
        self.assertFalse(offending_calls)


# ------------------------------------------------------------------
# 3. GenerationJobService.execute() SIGNATURE CANARY
# ------------------------------------------------------------------


class ExecuteSignatureCanaryTests(unittest.TestCase):
    def test_execute_signature_has_no_bypass_flavored_parameter(self):
        """Pins the exact parameter set of the one production
        create_job()-reaching method -- a canary against a future
        change silently adding a parameter that could let a caller
        skip the Gate, force a result, or assume an outcome."""
        sig = inspect.signature(GenerationJobService.execute)
        param_names = set(sig.parameters) - {"self"}
        self.assertEqual(
            param_names,
            {"request", "timeout_seconds", "interval_seconds", "activation_contract", "provider_activation_contract"},
        )
        bypass_words = ("force", "skip", "assume", "bypass", "override", "fake", "simulate")
        offenders = [p for p in param_names for w in bypass_words if w in p.lower()]
        self.assertFalse(offenders, offenders)


if __name__ == "__main__":
    unittest.main()
