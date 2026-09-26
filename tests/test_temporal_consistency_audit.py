"""
Tests -- Temporal Consistency & Authority Freshness Audit (Phase P3.37).

The vast majority of the temporal test matrix this phase asks for
(VALID/EXPIRED/CONSUMED/REVOKED/FOREIGN INSTANCE/REQUEST MISMATCH) is
already exhaustively covered elsewhere in this suite -- see the P3.37
report's Section 14 for the full citation list (tests/test_phase_p2_
18/19/21/22/24/25/26/27/35/38/39_*.py). This file adds ONLY the
genuinely new angles those did not already cover at this precision:

1. EXACT clock-injection boundary tests (just-before-expiry /
   exact-expiry / just-after-expiry) for RequestScopedActivationContract
   -- existing coverage (test_phase_p2_21_activation_contract.py::
   test_expired_contract_is_rejected) only tests a clearly-past
   timestamp (max_age + 61s past a 60s window), not the boundary
   itself.
2. Confirmation that revoke() and "already consumed" are LITERALLY the
   same underlying state (same set, same rejection text) -- a fact
   established by direct code reading this phase, now backed by an
   executable test rather than only a report citation.
3. Confirmation that ControlledRealProviderActivationService.revoke()
   has zero production call sites (grep-based, so this documents drift
   if a future phase wires one in without updating this test).
4. Confirmation that ProductionActivationHandoff.created_at is never
   consulted by ControlledActivationComposition's checks -- freshness
   is deliberately concentrated at the P2.21/P2.26 contract layer, not
   the handoff layer (an architectural choice, not an oversight).
5. Monotonic-clock rollback safety for the same expiry mechanism.

Fully offline: no network, no Higgsfield CLI, always MockHiggsfieldProvider.
"""

import inspect
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import ActivationRejectedError, RequestScopedActivationService
from agents.controlled_real_provider_activation import (
    ControlledRealProviderActivationRejectedError,
    ControlledRealProviderActivationService,
)
from agents.generation_approval_gate import GenerationApprovalGate, GenerationRequest, RealGenerationAuthorization
from agents.release_candidate_identity_lock import ReleaseCandidateIdentityLock, VIDEO_005_RELEASE_CANDIDATE
from agents.production_activation_handoff import ProductionActivationHandoff
from agents.controlled_activation_composition import verify_handoff_ready, verify_authorization_binding
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


def _new_p2_21_service(clock):
    provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
    identity_lock = ReleaseCandidateIdentityLock(C)
    gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
    return RequestScopedActivationService(gate, identity_lock, clock=clock)


def _new_p2_26_service(clock):
    provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
    identity_lock = ReleaseCandidateIdentityLock(C)
    gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
    rs_service = RequestScopedActivationService(gate, identity_lock)
    return rs_service, ControlledRealProviderActivationService(gate, identity_lock, rs_service, clock=clock)


# ------------------------------------------------------------------
# 1. EXACT CLOCK-INJECTION BOUNDARY (P2.21's max_age_seconds)
# ------------------------------------------------------------------


class ExpiryBoundaryTests(unittest.TestCase):
    def test_just_before_expiry_still_valid(self):
        fake_time = {"t": 1000.0}
        service = _new_p2_21_service(clock=lambda: fake_time["t"])
        service.max_age_seconds = 60.0
        request = _conforming_request()
        contract = service.prepare_activation(request)

        fake_time["t"] += 59.999  # 0.001s before the boundary
        service.validate_activation(request, contract)  # must not raise

    def test_exact_expiry_boundary_is_still_valid_strict_greater_than(self):
        """The implementation uses `elapsed > max_age_seconds` (strict),
        confirmed by direct code reading -- so the EXACT boundary value
        is still valid, not yet expired. This test locks that exact
        semantic in place rather than assuming it."""
        fake_time = {"t": 1000.0}
        service = _new_p2_21_service(clock=lambda: fake_time["t"])
        service.max_age_seconds = 60.0
        request = _conforming_request()
        contract = service.prepare_activation(request)

        fake_time["t"] += 60.0  # exactly at the boundary
        service.validate_activation(request, contract)  # must not raise

    def test_just_after_expiry_rejected(self):
        fake_time = {"t": 1000.0}
        service = _new_p2_21_service(clock=lambda: fake_time["t"])
        service.max_age_seconds = 60.0
        request = _conforming_request()
        contract = service.prepare_activation(request)

        fake_time["t"] += 60.001  # 0.001s after the boundary
        with self.assertRaises(ActivationRejectedError) as ctx:
            service.validate_activation(request, contract)
        self.assertTrue(any("expired" in r for r in ctx.exception.reasons))

    def test_large_forward_clock_jump_expires(self):
        fake_time = {"t": 1000.0}
        service = _new_p2_21_service(clock=lambda: fake_time["t"])
        service.max_age_seconds = 60.0
        request = _conforming_request()
        contract = service.prepare_activation(request)

        fake_time["t"] += 1_000_000.0  # a large jump forward
        with self.assertRaises(ActivationRejectedError):
            service.validate_activation(request, contract)

    def test_monotonic_clock_rollback_does_not_crash_and_does_not_falsely_expire(self):
        """A monotonic clock is not supposed to roll back, but this
        confirms the arithmetic (`clock() - issued_at`) degrades safely
        (stays valid, never raises a spurious/unrelated error) if it
        somehow did -- documenting actual behavior per Section 4's
        instruction, not asserting a policy that doesn't exist."""
        fake_time = {"t": 1000.0}
        service = _new_p2_21_service(clock=lambda: fake_time["t"])
        service.max_age_seconds = 60.0
        request = _conforming_request()
        contract = service.prepare_activation(request)

        fake_time["t"] -= 10.0  # clock rolled backward
        service.validate_activation(request, contract)  # must not raise


# ------------------------------------------------------------------
# 2. REVOKE == CONSUMED (same underlying state, confirmed by test)
# ------------------------------------------------------------------


class RevokeConsumedAmbiguityTests(unittest.TestCase):
    def test_revoked_and_consumed_produce_identical_rejection_text(self):
        """Confirms, by execution rather than by reading source, that
        revoke() and normal consumption are indistinguishable from the
        rejection reason alone -- both add to the exact same
        _consumed_activation_ids set (agents/controlled_real_provider_
        activation.py::revoke(), one line, no separate REVOKED state)."""
        request = _conforming_request()
        rs_service_a, pa_service_a = _new_p2_26_service(clock=lambda: 1000.0)
        rs_contract_a = rs_service_a.prepare_activation(request)
        pa_contract_a = pa_service_a.prepare(request, rs_contract_a)
        pa_service_a.revoke(pa_contract_a)
        with self.assertRaises(ControlledRealProviderActivationRejectedError) as ctx_revoked:
            pa_service_a.validate(request, rs_contract_a, pa_contract_a)

        request_b = _conforming_request()
        rs_service_b, pa_service_b = _new_p2_26_service(clock=lambda: 1000.0)
        rs_contract_b = rs_service_b.prepare_activation(request_b)
        pa_contract_b = pa_service_b.prepare(request_b, rs_contract_b)
        pa_service_b.validate(request_b, rs_contract_b, pa_contract_b)  # normal consumption
        with self.assertRaises(ControlledRealProviderActivationRejectedError) as ctx_consumed:
            pa_service_b.validate(request_b, rs_contract_b, pa_contract_b)  # second use

        # Reason text is identical apart from the embedded activation_id
        # -- same template, same "consumed or revoked" phrasing, proving
        # the two states are indistinguishable from the rejection alone.
        revoked_reason = ctx_revoked.exception.reasons[0].split("'")[-1]
        consumed_reason = ctx_consumed.exception.reasons[0].split("'")[-1]
        self.assertEqual(revoked_reason, consumed_reason)
        self.assertIn("already been consumed or revoked", revoked_reason)

    def test_revoke_has_zero_production_call_sites(self):
        """Documents drift if a future phase wires revoke() into a real
        call path without this test being updated -- per Section 12's
        explicit instruction not to create one automatically."""
        offenders = []
        for path in (PROJECT_ROOT / "director.py",):
            source = path.read_text(encoding="utf-8")
            if ".revoke(" in source:
                offenders.append(str(path))
        for path in (PROJECT_ROOT / "agents").glob("*.py"):
            if path.name == "controlled_real_provider_activation.py":
                continue  # the method's own definition site
            source = path.read_text(encoding="utf-8")
            if ".revoke(" in source:
                offenders.append(str(path))
        self.assertFalse(offenders, f"unexpected production revoke() call site(s): {offenders}")


# ------------------------------------------------------------------
# 3. HANDOFF STALENESS -- created_at never consulted by composition
# ------------------------------------------------------------------


class HandoffStalenessTests(unittest.TestCase):
    def test_production_activation_handoff_created_at_not_read_by_verify_functions(self):
        """AST-based: neither verify_handoff_ready() nor verify_
        authorization_binding() (agents/controlled_activation_
        composition.py) ever accesses `.created_at` -- freshness is
        deliberately concentrated at the P2.21/P2.26 contract layer,
        re-verified live at every use, not at the handoff layer."""
        import ast

        source = (PROJECT_ROOT / "agents" / "controlled_activation_composition.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in (
                "verify_handoff_ready", "verify_authorization_binding",
            ):
                attr_names = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
                self.assertNotIn("created_at", attr_names, f"{node.name} unexpectedly reads created_at")

    def test_handoff_created_at_field_exists_but_is_purely_descriptive(self):
        self.assertIn("created_at", ProductionActivationHandoff.__dataclass_fields__)


if __name__ == "__main__":
    unittest.main()
