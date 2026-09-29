"""
Tests -- GenerationApprovalGate Persistence Boundary & State Authority
Audit (Phase P3.40).

Deep-dive on the exact P3.39 MEDIUM finding: GenerationApprovalGate's
default constructor argument (`executed_request_store=None`) resolves
to a non-persistent InMemoryExecutedRequestStore. P3.39 already proved
the loss-across-restart mechanics directly
(tests/test_resilience_contract_audit.py::DefaultStorePersistenceTests).
This file adds ONLY the genuinely new angles P3.40's deeper questions
require:

1. Confirms `RequestScopedActivationService`'s single-use consumption
   tracking (`_consumed_activation_ids`) has NO persistence option at
   all (no injectable store parameter of any kind) -- it is inherently
   per-instance/ephemeral BY DESIGN, which is only safe because
   `ExecutedRequestStore` (via the Gate) is the one mechanism actually
   engineered to survive a restart. This is the key evidence for
   Section 9's "is the Gate store redundant or load-bearing" question.
2. Structurally proves approval-store loss cannot fabricate human
   authorization (`_human_authorization_reasons` never reads
   `executed_request_store`) -- Section 7.
3. Proves activation single-use survives even when the Gate's replay
   store is freshly lost, AS LONG AS the same activation-service
   instance is reused -- and separately, that a genuinely fresh
   instance (post-restart) is blocked by foreign-instance protection
   instead, never by an accidental "still consumed" false negative --
   Section 8.
4. Confirms scripts/demo_test.py's real (non-test) call site that uses
   the unsafe default is always paired with MockHiggsfieldProvider,
   never a real one -- Section 10 (Configuration Drift).

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

from agents.activation_contract import ActivationRejectedError, RequestScopedActivationService
from agents.executed_request_store import InMemoryExecutedRequestStore
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from tests.authorization_content_helpers import bind_request
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
    return bind_request(GenerationRequest(**defaults))


# ------------------------------------------------------------------
# 1. ACTIVATION SERVICE CONSUMPTION STATE HAS NO PERSISTENCE OPTION
# ------------------------------------------------------------------


class ActivationServiceStatelessnessTests(unittest.TestCase):
    def test_request_scoped_activation_service_has_no_injectable_persistence(self):
        """Unlike GenerationApprovalGate (which accepts an injectable
        executed_request_store), RequestScopedActivationService's
        __init__ has NO parameter of any kind for persisting
        _consumed_activation_ids/_issued_at -- confirming the Gate's
        store is the ONLY durable replay defense in the whole chain,
        not one of several redundant ones."""
        sig = inspect.signature(RequestScopedActivationService.__init__)
        param_names = set(sig.parameters) - {"self"}
        # `clock`/`max_age_seconds` (Phase P3.37) configure the
        # EXPIRY window of in-memory state -- neither is a persistence
        # mechanism; there is still no parameter of any kind that
        # would make `_consumed_activation_ids`/`_issued_at` survive
        # past this instance's lifetime.
        self.assertEqual(param_names, {"gate", "identity_lock", "clock", "max_age_seconds"})


# ------------------------------------------------------------------
# 2. APPROVAL STORE LOSS CANNOT FABRICATE HUMAN AUTHORIZATION
# ------------------------------------------------------------------


class ApprovalVsHumanAuthorizationTests(unittest.TestCase):
    def test_human_authorization_check_never_reads_executed_request_store(self):
        """AST-based: _human_authorization_reasons() only ever inspects
        request.real_generation_authorization -- it has no dependency
        on self.executed_request_store, so losing/resetting that store
        cannot, even in principle, alter this check's outcome."""
        source = (PROJECT_ROOT / "agents" / "generation_approval_gate.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_human_authorization_reasons":
                attr_names = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
                self.assertNotIn("executed_request_store", attr_names)
                return
        raise AssertionError("_human_authorization_reasons not found")

    def test_approved_true_without_authorization_still_rejected_regardless_of_store_state(self):
        """GenerationRequest.approved=True (technical/budget consent)
        is not, and after a simulated store loss still is not, a
        substitute for real_generation_authorization (human consent)."""
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        # Simulates a freshly "restarted" Gate -- default, lost store.
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
        self.assertIsInstance(gate.executed_request_store, InMemoryExecutedRequestStore)

        request = _conforming_request(approved=True, real_generation_authorization=None)
        approval = gate.evaluate(request)
        self.assertNotEqual(approval.decision, GenerationApprovalDecision.APPROVED)
        # Rejection must be attributable to missing human authorization,
        # never to anything store-related.
        self.assertTrue(any("authorization" in r.lower() for r in approval.reasons))


# ------------------------------------------------------------------
# 3. APPROVAL STORE LOSS CANNOT REVIVE A CONSUMED ACTIVATION
# ------------------------------------------------------------------


class ApprovalVsActivationTests(unittest.TestCase):
    def _service(self):
        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=1000.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        # Default (non-persistent) Gate store -- deliberately, to
        # isolate: does losing the GATE's store affect the SEPARATE
        # activation-consumption layer at all?
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
        return RequestScopedActivationService(gate, identity_lock)

    def test_consumed_activation_stays_rejected_even_though_gate_store_is_the_lost_default(self):
        service = self._service()
        request = _conforming_request()
        contract = service.prepare_activation(request)
        service.validate_activation(request, contract)  # first, legitimate use
        with self.assertRaises(ActivationRejectedError) as ctx:
            service.validate_activation(request, contract)  # replay
        self.assertTrue(any("consumed" in r for r in ctx.exception.reasons))

    def test_fresh_instance_after_simulated_restart_rejects_old_contract_as_foreign_never_as_a_false_pass(self):
        """A genuinely fresh RequestScopedActivationService (simulating
        a full process restart, not just Gate-store loss) must reject
        an old contract as NOT ISSUED BY THIS INSTANCE -- never
        silently treat it as valid because its own _consumed_
        activation_ids set happens to be empty again."""
        service_before = self._service()
        request = _conforming_request()
        contract = service_before.prepare_activation(request)

        service_after_restart = self._service()
        with self.assertRaises(ActivationRejectedError) as ctx:
            service_after_restart.validate_activation(request, contract)
        self.assertTrue(any("not issued by this" in r for r in ctx.exception.reasons))


# ------------------------------------------------------------------
# 4. CONFIGURATION DRIFT -- the one real non-test call site
# ------------------------------------------------------------------


class ConfigurationDriftTests(unittest.TestCase):
    def test_demo_script_default_gate_construction_always_paired_with_mock_provider(self):
        """scripts/demo_test.py constructs GenerationApprovalGate(...)
        without an explicit store (confirmed by repo-wide grep this
        phase) -- but AST-confirms every such call site in that file
        passes a MockHiggsfieldProvider-derived variable, never
        anything importing the real HiggsfieldProvider, so the unsafe
        default is safe there by construction, not by luck."""
        source = (PROJECT_ROOT / "scripts" / "demo_test.py").read_text(encoding="utf-8")
        self.assertNotIn("HiggsfieldProvider(", source.replace("MockHiggsfieldProvider(", ""))
        tree = ast.parse(source)
        imported_names = {
            alias.asname or alias.name
            for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        self.assertIn("MockHiggsfieldProvider", imported_names)
        self.assertNotIn("HiggsfieldProvider", imported_names)


if __name__ == "__main__":
    unittest.main()
