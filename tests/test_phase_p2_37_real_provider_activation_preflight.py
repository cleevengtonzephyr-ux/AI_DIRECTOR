"""
Tests — Phase P2.37 : REAL PROVIDER ACTIVATION PREFLIGHT & ONE-SHOT
AUTHORIZATION BOUNDARY.

Verrouille ce que P2.37 a réellement ajouté :

- `agents/real_provider_activation_preflight.py`
  (`ActivationPreflightEvaluator`/`ActivationPreflightReport`) --
  composition PURE de `RealProviderExecutionGate` (Phase P2.36, RÉUTILISÉ
  tel quel) + une vérification STATIQUE (AST, jamais une invocation)
  du dernier verrou Provider + un scan de tokens interdits réutilisant
  la liste canonique de Phase P2.25.
- `AIDirector.check_activation_preflight()` (director.py) -- entrée
  read-only.

Ce fichier NE re-teste PAS les mutations individuelles déjà couvertes
par tests/test_phase_p2_21/24/26/27/30/36_*.py (identity/prompt/asset/
model/duration/resolution/aspect_ratio/cost/balance/replay/UNKNOWN,
P2.21/P2.26 expiry/consumption/revoke) -- ces mécanismes sont RÉUTILISÉS
par ce module via `RealProviderExecutionGate`, jamais dupliqués, et
restent inchangés.
"""

import ast
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import RequestScopedActivationService
from agents.controlled_real_provider_activation import (
    ControlledRealProviderActivationService,
)
from agents.critical_section_lock import FileCriticalSectionLock
from agents.generation_approval_gate import (
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from agents.generation_job_service import GenerationJobService
from agents.real_provider_activation_preflight import (
    ActivationPreflightEvaluator,
    _probe_real_provider_execution_path,
    _scan_for_forbidden_global_authority_tokens,
)
from agents.real_provider_execution_gate import RealProviderExecutionDecision
from agents.release_candidate_identity_lock import (
    ReleaseCandidateIdentityLock,
    VIDEO_005_RELEASE_CANDIDATE,
)
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider
from integrations.higgsfield.types import CostEstimate, MediaReference, ModelParam, ModelSchema

C = VIDEO_005_RELEASE_CANDIDATE

REAL_AVATAR_PATH = PROJECT_ROOT / "assets" / "zephyr" / "avatar" / "avatar_master.png"
REAL_FACE_PATH = (
    PROJECT_ROOT / "assets" / "zephyr" / "references" / "mon avatar habille.png"
)


def _real_prompt() -> str:
    from agents.prompt_assembly_system import PromptAssemblySystem

    return PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id)


def _conforming_request(**overrides) -> GenerationRequest:
    defaults = dict(
        request_id=C.request_id,
        job_type=C.job_type,
        prompt=_real_prompt(),
        duration=C.duration,
        resolution=C.resolution,
        aspect_ratio=C.aspect_ratio,
        approved=True,
        start_image=MediaReference(
            role="master_avatar", source=str(REAL_AVATAR_PATH), sha256=None
        ),
        image_references=(
            MediaReference(
                role="face_reference", source=str(REAL_FACE_PATH), sha256=None
            ),
        ),
        real_generation_authorization=RealGenerationAuthorization(
            request_id=C.request_id, authorized_by_human=True
        ),
    )
    defaults.update(overrides)
    return GenerationRequest(**defaults)


class _Stack:
    def __init__(self, tmp_dir: Path, cost_per_job=67.5, available_credits=100.0, provider=None):
        self.provider = provider or MockHiggsfieldProvider(
            cost_per_job=cost_per_job, available_credits=available_credits
        )
        self.identity_lock = ReleaseCandidateIdentityLock(C)
        # Phase B : store persistant TEMPORAIRE propre à ce stack (la
        # readiness exige une garantie durable ; jamais le `state/` réel).
        from agents.executed_request_store import FileExecutedRequestStore

        self.gate = GenerationApprovalGate(
            self.provider,
            executed_request_store=FileExecutedRequestStore(
                Path(tempfile.mkdtemp(prefix="state_", dir=tmp_dir)) / "executed_requests.json"
            ),
            identity_lock=self.identity_lock,
        )
        self.activation_service = RequestScopedActivationService(self.gate, self.identity_lock)
        self.provider_activation_service = ControlledRealProviderActivationService(
            self.gate, self.identity_lock, self.activation_service
        )
        self.lock = FileCriticalSectionLock(tmp_dir)
        self.job_service = GenerationJobService(
            self.provider,
            self.gate,
            lock=self.lock,
            activation_service=self.activation_service,
            provider_activation_service=self.provider_activation_service,
        )
        self.preflight = ActivationPreflightEvaluator(
            self.gate,
            self.identity_lock,
            self.activation_service,
            self.provider_activation_service,
            job_service=self.job_service,
        )

    def prepared(self, request):
        rs_contract = self.activation_service.prepare_activation(request)
        pa_contract = self.provider_activation_service.prepare(request, rs_contract)
        return rs_contract, pa_contract


class _TmpDirTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_37_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def _stack(self, **kwargs) -> _Stack:
        return _Stack(self._tmp, **kwargs)


# ----------------------------------------------------------------------
# Static execution-path probe (no create_job() invocation whatsoever)
# ----------------------------------------------------------------------


class TestExecutionPathProbeIsStatic(unittest.TestCase):
    def test_probe_confirms_closed_against_current_provider_py(self):
        is_open, reason = _probe_real_provider_execution_path()
        self.assertFalse(is_open)
        self.assertIn("unconditionally raises", reason)

    def test_probe_never_calls_create_job_itself(self):
        """AST-confirm the probe function's OWN body never contains a
        `create_job(...)` call -- it must only ever read source text
        and walk an AST, never invoke anything."""

        import inspect

        source = inspect.getsource(_probe_real_provider_execution_path)
        tree = ast.parse(source)
        calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "create_job"
        ]
        self.assertEqual(calls, [])


class TestSecurityTokenScan(unittest.TestCase):
    def test_no_offenders_in_current_repository(self):
        self.assertEqual(_scan_for_forbidden_global_authority_tokens(), [])

    def test_reuses_the_canonical_p2_25_token_list_not_a_second_one(self):
        import agents.real_provider_activation_preflight as mod
        from agents.production_activation_boundary import FORBIDDEN_GLOBAL_AUTHORITY_TOKENS

        self.assertIs(mod.FORBIDDEN_GLOBAL_AUTHORITY_TOKENS, FORBIDDEN_GLOBAL_AUTHORITY_TOKENS)


# ----------------------------------------------------------------------
# Report field mapping
# ----------------------------------------------------------------------


class TestPreflightReportMapping(_TmpDirTestCase):
    def test_full_valid_mock_chain_approved_with_all_fields_true(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)

        report = stack.preflight.evaluate(
            request, activation_contract=rs_contract, provider_activation_contract=pa_contract
        )

        self.assertEqual(report.decision, RealProviderExecutionDecision.APPROVED)
        self.assertTrue(report.technically_ready)
        self.assertTrue(report.preflight_ready)
        self.assertTrue(report.budget_ready)
        self.assertTrue(report.human_authorized)
        self.assertFalse(report.real_provider_execution_path_open)
        self.assertFalse(report.real_provider_enabled)
        self.assertFalse(report.real_generation_executed)
        self.assertEqual(report.all_reasons, [])

    def test_insufficient_budget_reported_but_preflight_ready_stays_true(self):
        """Étape 4 : budget_ready et preflight_ready/technically_ready
        sont des axes DISTINCTS -- un déficit budgétaire ne signifie
        jamais que le mécanisme lui-même est cassé."""

        stack = self._stack(cost_per_job=67.5, available_credits=1.41)
        request = _conforming_request()

        report = stack.preflight.evaluate(request)

        self.assertFalse(report.budget_ready)
        self.assertTrue(report.technically_ready)
        self.assertTrue(report.preflight_ready)
        self.assertFalse(report.human_authorized is None)
        self.assertEqual(report.decision, RealProviderExecutionDecision.NOT_APPROVED)

    def test_no_authorization_reported_but_preflight_ready_stays_true(self):
        stack = self._stack()
        request = _conforming_request(real_generation_authorization=None)

        report = stack.preflight.evaluate(request)

        self.assertFalse(report.human_authorized)
        self.assertTrue(report.technically_ready)
        self.assertTrue(report.preflight_ready)
        self.assertEqual(report.decision, RealProviderExecutionDecision.NOT_APPROVED)

    def test_no_contracts_supplied_not_approved(self):
        stack = self._stack()
        request = _conforming_request()

        report = stack.preflight.evaluate(request)

        self.assertEqual(report.decision, RealProviderExecutionDecision.NOT_APPROVED)
        self.assertFalse(report.execution_gate.provider_activation_ready)


# ----------------------------------------------------------------------
# Étape 9 : exact request binding (005 -> 005 / 005 -> 006 / 006 -> 005)
# ----------------------------------------------------------------------


class TestExactRequestBinding(_TmpDirTestCase):
    def test_005_contract_used_for_005_request_approved(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)

        report = stack.preflight.evaluate(
            request, activation_contract=rs_contract, provider_activation_contract=pa_contract
        )
        self.assertEqual(report.decision, RealProviderExecutionDecision.APPROVED)

    def test_005_contract_cannot_be_inspected_against_a_006_request(self):
        stack = self._stack()
        request_005 = _conforming_request()
        rs_005, pa_005 = stack.prepared(request_005)

        request_006 = _conforming_request(
            request_id="006",
            job_type="other_model",
            real_generation_authorization=RealGenerationAuthorization(
                request_id="006", authorized_by_human=True
            ),
        )

        report = stack.preflight.evaluate(
            request_006, activation_contract=rs_005, provider_activation_contract=pa_005
        )
        self.assertEqual(report.decision, RealProviderExecutionDecision.NOT_APPROVED)
        self.assertFalse(report.execution_gate.provider_activation_ready)

    def test_006_authorization_cannot_activate_a_005_request(self):
        stack = self._stack()
        request_005 = _conforming_request()

        with self.assertRaises(Exception):
            # A RealGenerationAuthorization bound to 006 can never
            # prepare an activation for a 005 request in the first
            # place -- prepare_activation() itself refuses (Phase
            # P2.21/P2.23 authority boundary).
            bogus_request = _conforming_request(
                real_generation_authorization=RealGenerationAuthorization(
                    request_id="006", authorized_by_human=True
                )
            )
            stack.activation_service.prepare_activation(bogus_request)


# ----------------------------------------------------------------------
# Real provider negative path (Étape 22)
# ----------------------------------------------------------------------


class TestRealProviderPathStaysClosed(_TmpDirTestCase):
    def test_real_provider_never_reaches_approved_even_with_simulated_valid_conditions(self):
        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)

        real_provider.get_model = lambda job_type: ModelSchema(
            job_type=job_type,
            display_name=job_type,
            params=(
                ModelParam(name="prompt", type="string", required=True),
                ModelParam(name="duration", type="integer", required=False, default=5),
                ModelParam(
                    name="resolution", type="string", required=False,
                    default="720p", enum=("480p", "720p", "1080p", "4k"),
                ),
                ModelParam(
                    name="aspect_ratio", type="string", required=False,
                    default="16:9", enum=("9:16", "16:9"),
                ),
                ModelParam(name="start_image", type="object|null", required=False, default=None),
                ModelParam(name="image_references", type="array", required=False, default=None),
            ),
            raw={},
        )
        real_provider.estimate_cost = (
            lambda job_type, prompt, duration=None, resolution=None, aspect_ratio=None: (
                CostEstimate(job_type=job_type, credits=67.5, raw={"credits": 67.5})
            )
        )
        real_provider.get_account_balance = lambda: 1000.0

        stack = self._stack(provider=real_provider)
        request = _conforming_request()
        rs_contract = stack.activation_service.prepare_activation(request)

        report = stack.preflight.evaluate(request, activation_contract=rs_contract)

        self.assertEqual(report.decision, RealProviderExecutionDecision.NOT_APPROVED)
        self.assertFalse(report.execution_gate.readiness.provider_ready)
        # The static probe is provider-instance-independent -- it
        # always inspects the real HiggsfieldProvider class itself.
        self.assertFalse(report.real_provider_execution_path_open)
        fake_client.create_job.assert_not_called()
        fake_client.run.assert_not_called()


# ----------------------------------------------------------------------
# Rollback identifiability (Étape 17)
# ----------------------------------------------------------------------


class TestRollbackIsIdentifiableAndSelfContained(unittest.TestCase):
    def test_real_create_job_never_assigns_to_self_attributes(self):
        """Confirme que revenir à un simple `raise` inconditionnel dans
        `HiggsfieldProvider.create_job()` ne laisserait aucun état
        `self.*` orphelin ailleurs : cette méthode ne fait jamais
        `self.x = ...` -- son rollback est donc strictement localisé à
        son propre corps, jamais couplé à un effet de bord persistant."""

        text = (PROJECT_ROOT / "integrations" / "higgsfield" / "provider.py").read_text(
            encoding="utf-8-sig"
        )
        tree = ast.parse(text)
        real_create_job = None
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "create_job"
                and any(isinstance(n, ast.Raise) for n in node.body)
            ):
                real_create_job = node
                break
        self.assertIsNotNone(real_create_job)

        self_assignments = [
            n
            for n in ast.walk(real_create_job)
            if isinstance(n, (ast.Assign, ast.AugAssign))
            for target in (n.targets if isinstance(n, ast.Assign) else [n.target])
            if isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        ]
        self.assertEqual(self_assignments, [])


# ----------------------------------------------------------------------
# CLI preflight documentation accuracy (Étape 15) -- never executed.
# ----------------------------------------------------------------------


class TestClientCommandConstructionDocumentedNeverExecuted(unittest.TestCase):
    def test_create_job_builds_the_documented_cli_args_without_running_anything(self):
        # Phase P3.83 (verrou runtime D, autorisé) : `create_job()` est
        # désormais fermée inconditionnellement -- l'argv documenté est figé
        # via la fonction pure `build_create_job_args()` (extraite telle
        # quelle de l'ancien corps de `create_job()`), et le refus est figé
        # en plus : `run()` n'est jamais atteint.
        from integrations.higgsfield.client import HiggsfieldClient, build_create_job_args
        from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError

        client = HiggsfieldClient.__new__(HiggsfieldClient)  # bypass __init__ (no subprocess probing)
        captured = {}

        def _spy_run(*args, **kwargs):
            captured["args"] = args
            return {"id": "would-be-a-real-job-id"}

        client.run = _spy_run

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            client.create_job(
                "seedance_2_0",
                "PROMPT TEXT",
                duration=15,
                resolution="720p",
                aspect_ratio="9:16",
            )
        self.assertEqual(captured, {}, "create_job() must never reach run()")

        self.assertEqual(
            tuple(
                build_create_job_args(
                    "seedance_2_0",
                    "PROMPT TEXT",
                    duration=15,
                    resolution="720p",
                    aspect_ratio="9:16",
                )
            ),
            (
                "generate",
                "create",
                "seedance_2_0",
                "--prompt",
                "PROMPT TEXT",
                "--duration",
                "15",
                "--resolution",
                "720p",
                "--aspect-ratio",
                "9:16",
            ),
        )


# ----------------------------------------------------------------------
# Director entry point
# ----------------------------------------------------------------------


class TestDirectorEntryPoint(unittest.TestCase):
    def test_check_activation_preflight_never_calls_create_job_or_constructs_authorization(self):
        import director
        import inspect
        import textwrap

        source = textwrap.dedent(
            inspect.getsource(director.AIDirector.check_activation_preflight)
        )
        tree = ast.parse(source)
        create_job_calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "create_job"
        ]
        auth_calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "RealGenerationAuthorization"
        ]
        self.assertEqual(create_job_calls, [])
        self.assertEqual(auth_calls, [])


# ----------------------------------------------------------------------
# CALL-SITE INVARIANT (Étape 18)
# ----------------------------------------------------------------------


class TestCallSiteInvariant(unittest.TestCase):
    def test_exactly_one_production_create_job_call_site(self):
        offenders = []
        for base in ("agents", "integrations", "scripts"):
            base_dir = PROJECT_ROOT / base
            if not base_dir.exists():
                continue
            for path in base_dir.rglob("*.py"):
                if path.name in ("generation_job_service.py", "job_monitor.py"):
                    continue
                if "mock_provider.py" in str(path):
                    continue
                text = path.read_text(encoding="utf-8-sig")
                for node in ast.walk(ast.parse(text)):
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "create_job"
                    ):
                        offenders.append(str(path.relative_to(PROJECT_ROOT)))
        director_text = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8-sig")
        for node in ast.walk(ast.parse(director_text)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "create_job"
            ):
                offenders.append("director.py")
        self.assertEqual(offenders, [])

        gjs_text = (PROJECT_ROOT / "agents" / "generation_job_service.py").read_text(
            encoding="utf-8-sig"
        )
        real_calls = [
            n
            for n in ast.walk(ast.parse(gjs_text))
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "create_job"
        ]
        self.assertEqual(len(real_calls), 1)


if __name__ == "__main__":
    unittest.main()
