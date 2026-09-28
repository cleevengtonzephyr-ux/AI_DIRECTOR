"""
Tests — Phase P2.29 : EXPLICIT HUMAN ACTIVATION ENTRY POINT.

Verrouille les deux nouvelles méthodes de `director.py` :

- `AIDirector.prepare_real_generation_activation(..., real_generation_
  authorization, ...)` -- EXIGE une autorisation humaine explicite
  (paramètre sans valeur par défaut), construit la `GenerationRequest`
  (même chemin que `run_video_mission()`), puis prépare les DEUX
  contrats d'activation (P2.21 + P2.26). Ne consomme rien, n'exécute
  rien, n'appelle jamais `create_job()`.
- `AIDirector.execute_real_generation_activation(prepared, ...)` --
  appel SÉPARÉ et EXPLICITE qui délègue à `FinalReportService.
  generate()` avec les contrats préparés -- toujours re-vérifiés
  fraîchement à l'intérieur, toujours bloqué par le Provider réel
  désactivé.

`run_video_mission()` reste INCHANGÉ et ne fournit jamais aucun
contrat -- reconfirmé structurellement dans ce fichier.

Toutes les données de coût/solde utilisées ici proviennent de
`MockHiggsfieldProvider` (via un `report_service` injecté), sauf le
test explicitement dédié au Provider réel (fake client MagicMock --
zéro subprocess/réseau réel). AUCUN test de ce fichier n'invoque le
vrai CLI Higgsfield.
"""

import ast
import inspect
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import (
    ActivationRejectedError,
    RequestScopedActivationService,
)
from agents.controlled_real_provider_activation import (
    ControlledRealProviderActivationRejectedError,
    ControlledRealProviderActivationService,
)
from agents.critical_section_lock import FileCriticalSectionLock
from agents.final_report_service import (
    ActivationDecision,
    FinalReportService,
    FinalReportStatus,
)
from agents.generation_approval_gate import (
    GenerationApprovalGate,
    RealGenerationAuthorization,
)
from agents.generation_job_service import GenerationJobService
from agents.release_candidate_identity_lock import (
    ReleaseCandidateIdentityLock,
    VIDEO_005_RELEASE_CANDIDATE,
)
from director import AIDirector, PreparedRealGenerationActivation
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import HiggsfieldProvider

C = VIDEO_005_RELEASE_CANDIDATE
CONFIRMED_DURATION = 15


def _valid_auth(request_id=None):
    return RealGenerationAuthorization(
        request_id=request_id or C.request_id, authorized_by_human=True
    )


def _fake_client(cost=67.5, balance=100.0):
    fake_client = MagicMock()
    fake_client.estimate_cost.return_value = {"credits": cost}
    fake_client.account_status.return_value = {"credits": balance}
    fake_client.get_model.return_value = {
        "job_type": C.job_type,
        "display_name": "d",
        "params": [
            {"name": "prompt", "type": "string", "required": True},
            {"name": "duration", "type": "integer", "required": False, "default": 5},
            {"name": "start_image", "type": "object|null", "required": False},
            {"name": "image_references", "type": "array", "required": False},
        ],
    }
    return fake_client


class P2_29_TestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_29_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def _mock_report_service(self, cost_per_job=67.5, available_credits=100.0):
        provider = MockHiggsfieldProvider(cost_per_job=cost_per_job, available_credits=available_credits)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
        activation_service = RequestScopedActivationService(gate, identity_lock)
        provider_activation_service = ControlledRealProviderActivationService(
            gate, identity_lock, activation_service
        )
        lock = FileCriticalSectionLock(self._tmp)
        job_service = GenerationJobService(
            provider, gate, lock=lock,
            activation_service=activation_service,
            provider_activation_service=provider_activation_service,
        )
        return FinalReportService(provider, gate, job_service=job_service)


# ----------------------------------------------------------------------
# RÈGLE FONDAMENTALE : run_video_mission() n'est jamais une autorisation
# ----------------------------------------------------------------------


class TestRunVideoMissionIsNeverAuthorization(unittest.TestCase):
    def test_run_video_mission_signature_unchanged_no_contract_params(self):
        sig = inspect.signature(AIDirector.run_video_mission)
        self.assertNotIn("activation_contract", sig.parameters)
        self.assertNotIn("provider_activation_contract", sig.parameters)
        self.assertNotIn("real_generation_authorization_required", sig.parameters)

    def test_run_video_mission_never_calls_the_new_p2_29_methods(self):
        source = inspect.getsource(AIDirector.run_video_mission)
        tree = ast.parse(source.strip())
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn("prepare_real_generation_activation", called)
        self.assertNotIn("execute_real_generation_activation", called)

    def test_approved_true_alone_is_not_authorization_in_prepare(self):
        # Sans real_generation_authorization explicite, il n'existe
        # AUCUN moyen d'appeler prepare_real_generation_activation()
        # -- paramètre requis, pas de valeur par défaut.
        sig = inspect.signature(AIDirector.prepare_real_generation_activation)
        self.assertIs(
            sig.parameters["real_generation_authorization"].default,
            inspect.Parameter.empty,
        )

    def test_calling_prepare_without_authorization_raises_type_error(self):
        director = AIDirector()
        with self.assertRaises(TypeError):
            director.prepare_real_generation_activation(  # noqa: missing required arg
                video_id="005", title="t", hook="h", objective="o",
            )


# ----------------------------------------------------------------------
# Étape 3/5 : human authorization required, explicit, request-scoped,
# never fabricated, no global authority
# ----------------------------------------------------------------------


class TestHumanAuthorizationRequirement(P2_29_TestCase):
    def test_director_never_constructs_real_generation_authorization(self):
        text = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8-sig")
        self.assertNotIn("RealGenerationAuthorization(", text)

    def test_no_global_authority_attributes_on_director(self):
        director = AIDirector()
        for attr in (
            "real_generation_enabled", "production_mode", "force_generation",
            "global_authorization", "cached_authorization", "_authority",
        ):
            self.assertFalse(hasattr(director, attr))
            self.assertFalse(hasattr(AIDirector, attr))

    def test_missing_authorization_cannot_be_bypassed_via_approved_true(self):
        director = AIDirector()
        director.higgsfield = _fake_client()
        report_service = self._mock_report_service()

        # Aucune façon de fournir approved=True SANS fournir
        # real_generation_authorization -- le paramètre est requis.
        sig = inspect.signature(director.prepare_real_generation_activation)
        params = list(sig.parameters)
        self.assertIn("real_generation_authorization", params)
        self.assertIn("approved", params)
        # Les deux existent, mais authorization n'a pas de défaut.


# ----------------------------------------------------------------------
# Étape 4 : request identity binding
# ----------------------------------------------------------------------


class TestRequestIdentityBinding(P2_29_TestCase):
    def test_authorization_for_006_cannot_be_used_for_video_005(self):
        # video_006.md n'existe pas dans ce projet (seule Video 005 est
        # une Release Candidate réelle) -- le scénario pertinent est
        # donc : construire la requête RÉELLE 005, mais fournir une
        # autorisation humaine liée à "006" -- rejetée par le binding
        # request_id de la Gate/Identity Lock, jamais par un simple
        # fichier manquant.
        director = AIDirector()
        report_service = self._mock_report_service()

        with self.assertRaises(ActivationRejectedError):
            director.prepare_real_generation_activation(
                video_id="005", title="t", hook="h", objective="o",
                duration=CONFIRMED_DURATION, approved=True,
                real_generation_authorization=_valid_auth("006"),
                report_service=report_service,
            )

    def test_authorization_bound_to_wrong_request_id_rejected(self):
        director = AIDirector()
        report_service = self._mock_report_service()

        with self.assertRaises(ActivationRejectedError):
            director.prepare_real_generation_activation(
                video_id="005", title="t", hook="h", objective="o",
                duration=CONFIRMED_DURATION, approved=True,
                real_generation_authorization=_valid_auth("999"),
                report_service=report_service,
            )


# ----------------------------------------------------------------------
# Étape 7 : Double consent (A-F)
# ----------------------------------------------------------------------


class TestDoubleConsent(P2_29_TestCase):
    def _prepare(self, director=None, report_service=None, **overrides):
        director = director or AIDirector()
        report_service = report_service or self._mock_report_service()
        kwargs = dict(
            video_id="005", title="t", hook="h", objective="o",
            duration=CONFIRMED_DURATION, approved=True,
            real_generation_authorization=_valid_auth("005"),
            report_service=report_service,
        )
        kwargs.update(overrides)
        return director.prepare_real_generation_activation(**kwargs)

    def test_A_approved_true_without_authorization_is_impossible_to_express(self):
        # Ne peut même pas être exprimé : real_generation_authorization
        # est requis. On simule l'équivalent "sans autorité" avec une
        # autorisation non liée (cf. TestRequestIdentityBinding) --
        # déjà couvert. Ici on vérifie juste qu'aucun défaut n'existe.
        sig = inspect.signature(AIDirector.prepare_real_generation_activation)
        self.assertIs(
            sig.parameters["real_generation_authorization"].default,
            inspect.Parameter.empty,
        )

    def test_B_authorization_without_gate_approval_rejected(self):
        with self.assertRaises(ActivationRejectedError):
            self._prepare(approved=False)

    def test_C_authorization_wrong_request_id_rejected(self):
        with self.assertRaises(ActivationRejectedError):
            self._prepare(real_generation_authorization=_valid_auth("006"))

    def test_D_insufficient_budget_blocks_p2_21_contract(self):
        report_service = self._mock_report_service(cost_per_job=67.5, available_credits=1.41)
        with self.assertRaises(ActivationRejectedError):
            self._prepare(report_service=report_service)

    def test_E_real_provider_blocks_p2_26_contract(self):
        from tests.test_phase_b_authorization_single_use import isolated_director_state

        director = AIDirector()
        director.higgsfield = _fake_client(cost=10.0, balance=100.0)
        # report_service=None -> chaîne réelle (HiggsfieldProvider réel) ;
        # Phase B : ses chemins persistants redirigés vers self._tmp.
        with isolated_director_state(self._tmp):
            with self.assertRaises(ControlledRealProviderActivationRejectedError):
                director.prepare_real_generation_activation(
                    video_id="005", title="t", hook="h", objective="o",
                    duration=CONFIRMED_DURATION, approved=True,
                    real_generation_authorization=_valid_auth("005"),
                )

    def test_F_all_correct_preparation_succeeds(self):
        prepared = self._prepare()
        self.assertIsInstance(prepared, PreparedRealGenerationActivation)
        self.assertEqual(prepared.request.request_id, "005")

    def test_preparation_success_does_not_mean_execution(self):
        report_service = self._mock_report_service()
        prepared = self._prepare(report_service=report_service)
        # Aucun job Mock n'existe -- rien n'a été exécuté.
        self.assertEqual(len(report_service.provider._jobs), 0)


# ----------------------------------------------------------------------
# Étape 8 : Freshness between prepare and execute
# ----------------------------------------------------------------------


class TestFreshnessBetweenPrepareAndExecute(P2_29_TestCase):
    def test_cost_change_between_prepare_and_execute_blocks_execution(self):
        director = AIDirector()
        report_service = self._mock_report_service(cost_per_job=10.0, available_credits=100.0)

        prepared = director.prepare_real_generation_activation(
            video_id="005", title="t", hook="h", objective="o",
            duration=CONFIRMED_DURATION, approved=True,
            real_generation_authorization=_valid_auth("005"),
            report_service=report_service,
        )

        report_service.provider._cost_per_job = 1000.0  # coût frais, différent

        # GenerationJobExecutionError (Gate BLOCKED, coût frais
        # insuffisant) est capturée par generate() -- comportement
        # voulu depuis P2.23, jamais une exception non gérée. Le
        # rapport retourné doit rester fidèle : NOT_EXECUTED, jamais
        # EXECUTED_PASS.
        report = director.execute_real_generation_activation(
            prepared, report_service=report_service, interval_seconds=0
        )
        self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)
        self.assertFalse(report.job_created)

    def test_balance_change_between_prepare_and_execute_blocks_execution(self):
        director = AIDirector()
        report_service = self._mock_report_service(cost_per_job=10.0, available_credits=100.0)

        prepared = director.prepare_real_generation_activation(
            video_id="005", title="t", hook="h", objective="o",
            duration=CONFIRMED_DURATION, approved=True,
            real_generation_authorization=_valid_auth("005"),
            report_service=report_service,
        )

        report_service.provider._available_credits = 1.41

        report = director.execute_real_generation_activation(
            prepared, report_service=report_service, interval_seconds=0
        )
        self.assertEqual(report.status, FinalReportStatus.NOT_EXECUTED)
        self.assertFalse(report.job_created)


# ----------------------------------------------------------------------
# Étape 9 : Mock positive path
# ----------------------------------------------------------------------


class TestMockPositivePath(P2_29_TestCase):
    def test_full_mock_positive_scenario_via_new_entry_point(self):
        director = AIDirector()
        report_service = self._mock_report_service(cost_per_job=10.0, available_credits=100.0)

        prepared = director.prepare_real_generation_activation(
            video_id="005", title="t", hook="h", objective="o",
            duration=CONFIRMED_DURATION, approved=True,
            real_generation_authorization=_valid_auth("005"),
            report_service=report_service,
        )

        report = director.execute_real_generation_activation(
            prepared, report_service=report_service, interval_seconds=0
        )

        self.assertEqual(report.status, FinalReportStatus.EXECUTED_PASS)
        self.assertTrue(report.job_created)
        self.assertEqual(report.activation_decision, ActivationDecision.APPROVED)
        self.assertEqual(report.provider_activation_decision, ActivationDecision.APPROVED)
        # Le point central : MÊME avec un job Mock créé, real_provider_called reste False.
        self.assertFalse(report.real_provider_called)


# ----------------------------------------------------------------------
# Étape 10 : Real provider negative path
# ----------------------------------------------------------------------


class TestRealProviderNegativePath(unittest.TestCase):
    def test_real_provider_blocks_even_with_valid_authorization_and_gate(self):
        from tests.test_phase_b_authorization_single_use import isolated_director_state

        director = AIDirector()
        director.higgsfield = _fake_client(cost=10.0, balance=100.0)

        # La frontière P2.26 refuse déjà à la préparation. Phase B :
        # chemins persistants de la chaîne réelle redirigés vers un
        # dossier temporaire (jamais le `state/` réel).
        tmp = Path(tempfile.mkdtemp(prefix="p2_29_director_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with isolated_director_state(tmp):
            with self.assertRaises(ControlledRealProviderActivationRejectedError):
                director.prepare_real_generation_activation(
                    video_id="005", title="t", hook="h", objective="o",
                    duration=CONFIRMED_DURATION, approved=True,
                    real_generation_authorization=_valid_auth("005"),
                )

        director.higgsfield.create_job.assert_not_called()

    def test_direct_provider_call_still_blocked(self):
        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(job_type="seedance_2_0", prompt="x")
        fake_client.create_job.assert_not_called()

    def test_provider_py_unchanged_create_job_still_disabled(self):
        """
        Phase P2.35 — REVISED INVARIANT (documented, not weakened).

        Before P2.35, `HiggsfieldProvider.create_job()`'s body was
        exactly one bare `raise` statement (no branching at all), which
        this test used to assert directly (`len(body) == 1`). P2.35
        deliberately introduces real structural validation of
        `provider_activation_contract` (see integrations/higgsfield/
        provider.py module docstring) -- the body necessarily now
        contains more than one statement.

        The invariant this test protects has NOT weakened: it now
        asserts, via AST, the properties that actually matter for
        safety and that P2.35's design guarantees regardless of how
        many statements the body contains:
          1. every top-level statement in the body still ends in the
             function unconditionally raising (the last top-level
             statement is an `ast.Raise` -- there is no fall-through
             path that could return normally) ;
          2. there is NO `ast.Return` anywhere in the function (a `Job`
             can never be produced by this method) ;
          3. `self.client` (the only path to a real network/CLI call)
             is referenced NOWHERE in this function -- proving no
             branch, however the activation validates, ever reaches
             the real Higgsfield client.
        """

        text = (PROJECT_ROOT / "integrations" / "higgsfield" / "provider.py").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("HiggsfieldRealGenerationDisabledError", text)
        import ast

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

        # 1. Last top-level statement unconditionally raises.
        self.assertIsInstance(real_create_job.body[-1], ast.Raise)

        # 2. No Return anywhere in the function.
        returns = [n for n in ast.walk(real_create_job) if isinstance(n, ast.Return)]
        self.assertEqual(returns, [])

        # 3. self.client is never referenced anywhere in the function.
        self_client_refs = [
            n
            for n in ast.walk(real_create_job)
            if isinstance(n, ast.Attribute)
            and n.attr == "client"
            and isinstance(n.value, ast.Name)
            and n.value.id == "self"
        ]
        self.assertEqual(self_client_refs, [])


# ----------------------------------------------------------------------
# Étape 12 : FinalReport axis separation
# ----------------------------------------------------------------------


class TestFinalReportAxisSeparation(P2_29_TestCase):
    def test_successful_preparation_alone_never_produces_executed(self):
        director = AIDirector()
        report_service = self._mock_report_service()

        prepared = director.prepare_real_generation_activation(
            video_id="005", title="t", hook="h", objective="o",
            duration=CONFIRMED_DURATION, approved=True,
            real_generation_authorization=_valid_auth("005"),
            report_service=report_service,
        )
        # Aucun FinalReport n'existe encore -- prepare_* ne renvoie
        # jamais un FinalReport, uniquement un bundle non exécuté.
        self.assertIsInstance(prepared, PreparedRealGenerationActivation)
        self.assertFalse(hasattr(prepared, "status"))
        self.assertFalse(hasattr(prepared, "job_created"))


# ----------------------------------------------------------------------
# Étape 13 : Replay
# ----------------------------------------------------------------------


class TestReplay(P2_29_TestCase):
    def test_new_authorization_and_new_activation_cannot_replay_executed_request(self):
        director = AIDirector()
        report_service = self._mock_report_service(cost_per_job=10.0, available_credits=100.0)

        prepared_1 = director.prepare_real_generation_activation(
            video_id="005", title="t", hook="h", objective="o",
            duration=CONFIRMED_DURATION, approved=True,
            real_generation_authorization=_valid_auth("005"),
            report_service=report_service,
        )
        report_1 = director.execute_real_generation_activation(
            prepared_1, report_service=report_service, interval_seconds=0
        )
        self.assertTrue(report_1.job_created)

        # Nouvelle autorisation, nouvelle préparation, même request_id.
        with self.assertRaises(ActivationRejectedError) as ctx:
            director.prepare_real_generation_activation(
                video_id="005", title="t", hook="h", objective="o",
                duration=CONFIRMED_DURATION, approved=True,
                real_generation_authorization=RealGenerationAuthorization(
                    request_id="005", authorized_by_human=True, note="brand new"
                ),
                report_service=report_service,
            )
        self.assertTrue(any("already been executed" in r for r in ctx.exception.reasons))
        self.assertEqual(len(report_service.provider._jobs), 1)


# ----------------------------------------------------------------------
# Étape 14 : UNKNOWN never bypassed by the new API
# ----------------------------------------------------------------------


class TestUnknownStateNotBypassed(P2_29_TestCase):
    def test_mark_executed_failure_yields_unknown_via_new_entry_point(self):
        from agents.generation_job_service import GenerationJobUnknownStateError

        class _RaisingMarkExecutedGate(GenerationApprovalGate):
            def mark_executed(self, request_id: str, job_id=None) -> None:
                raise OSError("simulated disk failure")

        provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = _RaisingMarkExecutedGate(provider, identity_lock=identity_lock)
        activation_service = RequestScopedActivationService(gate, identity_lock)
        provider_activation_service = ControlledRealProviderActivationService(
            gate, identity_lock, activation_service
        )
        lock = FileCriticalSectionLock(self._tmp)
        job_service = GenerationJobService(
            provider, gate, lock=lock,
            activation_service=activation_service,
            provider_activation_service=provider_activation_service,
        )
        report_service = FinalReportService(provider, gate, job_service=job_service)

        director = AIDirector()
        prepared = director.prepare_real_generation_activation(
            video_id="005", title="t", hook="h", objective="o",
            duration=CONFIRMED_DURATION, approved=True,
            real_generation_authorization=_valid_auth("005"),
            report_service=report_service,
        )

        with self.assertRaises(GenerationJobUnknownStateError):
            director.execute_real_generation_activation(
                prepared, report_service=report_service, interval_seconds=0
            )

        self.assertTrue(gate.is_unknown("005"))
        # Jamais NOT_EXECUTED silencieux : une nouvelle évaluation
        # renvoie EXECUTION_STATE_UNKNOWN, pas APPROVED ni un vide.
        from agents.generation_approval_gate import GenerationApprovalDecision

        fresh_check = gate.evaluate(prepared.request)
        self.assertEqual(fresh_check.decision, GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN)


# ----------------------------------------------------------------------
# Étape 15 : Security scan reconfirmed
# ----------------------------------------------------------------------


class TestSecurityScan(unittest.TestCase):
    def test_no_forbidden_tokens_in_director(self):
        import re

        tokens = (
            "REAL_GENERATION_ENABLED", "HIGGSFIELD_ENABLED", "PRODUCTION_MODE",
            "FORCE_GENERATION", "force_generate", "generate_now",
            "skip_gate", "bypass", "auto_authorize", "auto_activation",
        )
        text = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8-sig")
        for token in tokens:
            self.assertIsNone(
                re.search(r"\b" + re.escape(token) + r"\b", text),
                f"forbidden token {token!r} found in director.py",
            )

    def test_no_forbidden_tokens_anywhere_in_production_code(self):
        import re

        tokens = (
            "REAL_GENERATION_ENABLED", "HIGGSFIELD_ENABLED", "PRODUCTION_MODE",
            "FORCE_GENERATION", "force_generate", "generate_now",
            "skip_gate", "bypass", "auto_authorize", "auto_activation",
        )
        excluded = {"agents/production_activation_boundary.py"}
        patterns = {t: re.compile(r"\b" + re.escape(t) + r"\b") for t in tokens}
        offenders = []
        for base in ("agents", "integrations"):
            for path in (PROJECT_ROOT / base).rglob("*.py"):
                rel = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
                if rel in excluded:
                    continue
                text = path.read_text(encoding="utf-8-sig")
                for tok, pat in patterns.items():
                    if pat.search(text):
                        offenders.append((rel, tok))
        director_text = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8-sig")
        for tok, pat in patterns.items():
            if pat.search(director_text):
                offenders.append(("director.py", tok))
        self.assertEqual(offenders, [])


# ----------------------------------------------------------------------
# Étape 16 : Video 005 integrity
# ----------------------------------------------------------------------


class TestVideo005Integrity(unittest.TestCase):
    def test_canonical_values_unchanged(self):
        self.assertEqual(C.request_id, "005")
        self.assertEqual(C.job_type, "seedance_2_0")
        self.assertEqual(C.duration, 15)
        self.assertEqual(C.resolution, "720p")
        self.assertEqual(C.aspect_ratio, "9:16")
        self.assertEqual(C.prompt_chars, 7284)
        self.assertEqual(C.prompt_lines, 265)
        self.assertEqual(
            C.prompt_sha256,
            "1c498617adb4603bcf2fc114a9cb9e8fe2219f09285adbff4d1e6c7a10a669e1",
        )
        self.assertEqual(
            C.avatar_master_sha256,
            "d293e41a63f66fd43afbebee3f7f9f1bd29143b465fa57a18ab4e1df5faf7280",
        )
        self.assertEqual(
            C.face_reference_sha256,
            "df83a97b71cff9a90191c19d15ff989228b9fef2e57c96cf7c76c68652e3a343",
        )

    def test_recomputed_live(self):
        import hashlib

        from agents.prompt_assembly_system import PromptAssemblySystem

        prompt = PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id)
        self.assertEqual(len(prompt), C.prompt_chars)
        self.assertEqual(len(prompt.splitlines()), C.prompt_lines)
        self.assertEqual(hashlib.sha256(prompt.encode("utf-8")).hexdigest(), C.prompt_sha256)


if __name__ == "__main__":
    unittest.main()
