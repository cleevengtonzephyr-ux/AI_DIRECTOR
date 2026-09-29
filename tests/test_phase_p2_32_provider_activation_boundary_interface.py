"""
Tests — Phase P2.32 : REAL PROVIDER ACTIVATION BOUNDARY IMPLEMENTATION
& DRY-RUN VERIFICATION.

Ce fichier ne re-teste PAS les mécanismes P2.21/P2.26 eux-mêmes
(freshness, mutation de prompt/asset/model/duration/resolution/
aspect_ratio, replay, UNKNOWN, expiry, revoke, consumed -- déjà
exhaustivement couverts par tests/test_phase_p2_26_controlled_real_
provider_activation.py et tests/test_phase_p2_27_controlled_provider_
activation_integration.py, inchangés par cette phase). Il verrouille
UNIQUEMENT ce que P2.32 a réellement changé :

- `BaseHiggsfieldProvider.create_job()` / `HiggsfieldProvider.
  create_job()` / `MockHiggsfieldProvider.create_job()` acceptent
  désormais un paramètre optionnel `provider_activation_contract`
  (Phase P2.26) -- une INTERFACE, jamais une activation.
- `GenerationJobService.execute()` transmet désormais explicitement ce
  paramètre au Provider (au lieu de ne jamais le lui passer).
- Le VRAI `HiggsfieldProvider.create_job()` continue de lever
  `HiggsfieldRealGenerationDisabledError` INCONDITIONNELLEMENT, que
  `provider_activation_contract` soit `None`, un contrat parfaitement
  valide, ou un contrat étranger/mal lié -- jamais inspecté.
"""

import ast
import re
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
from tests.authorization_content_helpers import bind_request
from agents.generation_job_service import GenerationJobService
from agents.release_candidate_identity_lock import (
    ReleaseCandidateIdentityLock,
    VIDEO_005_RELEASE_CANDIDATE,
)
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.provider import BaseHiggsfieldProvider, HiggsfieldProvider
from integrations.higgsfield.types import Job, JobStatus, MediaReference

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
    return bind_request(GenerationRequest(**defaults))


class _Stack:
    """Reproduit exactement le câblage réel de
    director.py::_build_default_chain(), mais avec un
    MockHiggsfieldProvider et un FileCriticalSectionLock pointé vers un
    répertoire temporaire -- jamais `state/` du dépôt (Étape 22, P2.32 :
    aucun test de ce fichier ne doit laisser d'état parasite)."""

    def __init__(self, tmp_dir: Path, cost_per_job=67.5, available_credits=100.0):
        self.provider = MockHiggsfieldProvider(
            cost_per_job=cost_per_job, available_credits=available_credits
        )
        self.identity_lock = ReleaseCandidateIdentityLock(C)
        self.gate = GenerationApprovalGate(self.provider, identity_lock=self.identity_lock)
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

    def prepared(self, request):
        rs_contract = self.activation_service.prepare_activation(request)
        pa_contract = self.provider_activation_service.prepare(request, rs_contract)
        return rs_contract, pa_contract


class _TmpDirTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="p2_32_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def _stack(self, **kwargs) -> _Stack:
        return _Stack(self._tmp, **kwargs)


# ----------------------------------------------------------------------
# INTERFACE 1-4 : le Provider reconnaît la surface d'activation, sans
# jamais l'honorer avec le vrai Provider.
# ----------------------------------------------------------------------


class TestInterfaceAcceptsActivationSurface(_TmpDirTestCase):
    def test_1_real_provider_signature_accepts_provider_activation_contract(self):
        """Le vrai Provider n'échoue pas avec un TypeError quand ce
        nouveau paramètre est fourni -- l'interface existe réellement."""

        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(
                job_type="seedance_2_0", prompt="x", provider_activation_contract=None
            )

    def test_2_missing_activation_cannot_silently_authorize(self):
        """provider_activation_contract=None (comportement par défaut,
        identique à avant P2.32) ne débloque rien."""

        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(job_type="seedance_2_0", prompt="x")

    def test_3_a_genuinely_valid_contract_still_does_not_authorize_the_real_provider(self):
        """Un contrat P2.26 authentiquement préparé ET validé (via un
        Mock, puisque le vrai Provider refuse déjà à l'étape validate())
        n'a AUCUN effet quand il est transmis directement au vrai
        Provider : celui-ci l'ignore inconditionnellement."""

        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)
        validated = stack.provider_activation_service.validate(request, rs_contract, pa_contract)

        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(
                job_type=request.job_type,
                prompt=request.prompt,
                provider_activation_contract=validated,
            )
        fake_client.create_job.assert_not_called()
        fake_client.run.assert_not_called()

    def test_4_a_foreign_mismatched_contract_is_equally_powerless(self):
        """Un contrat lié à un AUTRE request_id (jamais validé pour
        cette requête) est, sans surprise, tout aussi inoffensif contre
        le vrai Provider -- la frontière ne dépend d'AUCUNE inspection
        du contrat, ce qui inclut le cas où il serait étranger."""

        stack = self._stack()
        other_request = _conforming_request(
            request_id="not-005",
            job_type="other_model",
            real_generation_authorization=RealGenerationAuthorization(
                request_id="not-005", authorized_by_human=True
            ),
        )

        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(
                job_type="other_model",
                prompt="unrelated prompt",
                provider_activation_contract="not-even-a-real-contract-object",
            )
        fake_client.create_job.assert_not_called()

    def test_5_abstract_base_declares_the_same_parameter(self):
        """BaseHiggsfieldProvider (le contrat commun) déclare aussi ce
        paramètre -- MockHiggsfieldProvider et HiggsfieldProvider ne
        divergent pas silencieusement du contrat abstrait."""

        import inspect

        sig = inspect.signature(BaseHiggsfieldProvider.create_job)
        self.assertIn("provider_activation_contract", sig.parameters)
        self.assertIsNone(sig.parameters["provider_activation_contract"].default)

    def test_6_mock_provider_accepts_and_records_the_contract_for_observability_only(self):
        """Le Mock accepte le même paramètre et le conserve tel quel
        (observabilité pure) -- il ne l'utilise jamais pour décider
        quoi que ce soit (le job simulé est créé identiquement, avec
        ou sans lui)."""

        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)

        job = stack.provider.create_job(
            job_type=request.job_type,
            prompt=request.prompt,
            provider_activation_contract=pa_contract,
        )
        self.assertIs(job.raw["provider_activation_contract"], pa_contract)

        # Sans le paramètre -- comportement inchangé, toujours accepté.
        job_without = stack.provider.create_job(job_type=request.job_type, prompt=request.prompt)
        self.assertIsNone(job_without.raw["provider_activation_contract"])


# ----------------------------------------------------------------------
# WIRING : GenerationJobService.execute() transmet désormais le contrat
# jusqu'au Provider (jamais avant P2.32).
# ----------------------------------------------------------------------


class _SpyProvider(MockHiggsfieldProvider):
    """Enregistre les arguments exacts reçus par create_job(), sans
    changer son comportement (délègue intégralement au Mock)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.received_provider_activation_contract = "UNSET"

    def create_job(self, job_type, prompt, provider_activation_contract=None, **params):
        self.received_provider_activation_contract = provider_activation_contract
        return super().create_job(
            job_type,
            prompt,
            provider_activation_contract=provider_activation_contract,
            **params,
        )


class TestGenerationJobServiceForwardsContract(_TmpDirTestCase):
    def _spy_stack(self, cost_per_job=67.5, available_credits=100.0):
        provider = _SpyProvider(cost_per_job=cost_per_job, available_credits=available_credits)
        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
        activation_service = RequestScopedActivationService(gate, identity_lock)
        provider_activation_service = ControlledRealProviderActivationService(
            gate, identity_lock, activation_service
        )
        job_service = GenerationJobService(
            provider,
            gate,
            lock=FileCriticalSectionLock(self._tmp),
            activation_service=activation_service,
            provider_activation_service=provider_activation_service,
        )
        return provider, gate, activation_service, provider_activation_service, job_service

    def test_7_execute_forwards_a_provided_and_validated_contract_to_the_provider(self):
        provider, gate, activation_service, provider_activation_service, job_service = (
            self._spy_stack()
        )
        request = _conforming_request()
        rs_contract = activation_service.prepare_activation(request)
        pa_contract = provider_activation_service.prepare(request, rs_contract)

        outcome = job_service.execute(
            request,
            interval_seconds=0,
            activation_contract=rs_contract,
            provider_activation_contract=pa_contract,
        )

        self.assertTrue(outcome.succeeded)
        self.assertIs(provider.received_provider_activation_contract, pa_contract)

    def test_8_execute_without_a_contract_forwards_none_unchanged_from_before(self):
        """Chemin de production actuel (director.py ne fournit jamais
        de contrat) : comportement STRICTEMENT identique à avant P2.32
        -- `None` est transmis, jamais deviné ni construit."""

        provider, gate, activation_service, provider_activation_service, job_service = (
            self._spy_stack()
        )
        request = _conforming_request(
            request_id="005-no-contract",
            real_generation_authorization=RealGenerationAuthorization(
                request_id="005-no-contract", authorized_by_human=True
            ),
        )
        # Sans activation_contract/provider_activation_contract, identity
        # lock bloquerait (request_id différent de 005) -- on désactive
        # l'identity lock pour ce test isolé de wiring uniquement.
        job_service.gate.identity_lock = None

        outcome = job_service.execute(request, interval_seconds=0)

        self.assertTrue(outcome.succeeded)
        self.assertIsNone(provider.received_provider_activation_contract)


# ----------------------------------------------------------------------
# MOCK POSITIVE PATH (Étape 10, 12)
# ----------------------------------------------------------------------


class TestMockPositivePathStillWorks(_TmpDirTestCase):
    def test_9_full_mock_positive_path_with_forwarded_contract_is_executed_pass(self):
        stack = self._stack()
        request = _conforming_request()
        rs_contract, pa_contract = stack.prepared(request)

        outcome = stack.job_service.execute(
            request,
            interval_seconds=0,
            activation_contract=rs_contract,
            provider_activation_contract=pa_contract,
        )

        self.assertTrue(outcome.succeeded)
        self.assertTrue(outcome.job.job_id.startswith("mock-job-"))
        self.assertEqual(outcome.job.raw["provider_activation_contract"], pa_contract)

    def test_10_real_provider_called_is_false_for_this_mock_outcome(self):
        stack = self._stack()
        provider_used = stack.job_service.provider
        is_real = type(provider_used).create_job is HiggsfieldProvider.create_job
        self.assertFalse(is_real)


# ----------------------------------------------------------------------
# REAL PROVIDER NEGATIVE PATH / NETWORK SAFETY (Étape 11-13)
# ----------------------------------------------------------------------


class TestRealProviderStaysDisabledAndNetworkSafe(_TmpDirTestCase):
    def test_11_full_chain_against_real_provider_never_reaches_create_job_success(self):
        """Même en construisant la chaîne complète (Gate/Identity/P2.21)
        avec un budget/coût/modèle hypothétiquement favorables contre le
        VRAI Provider (méthodes Provider individuellement monkeypatchées
        -- jamais le CLI/réseau réel, cf. Étape 12/26 : aucun subprocess
        n'est jamais impliqué ici), `ControlledRealProviderActivation
        Service.prepare()` refuse déjà à la frontière -- create_job()
        n'est jamais atteint avec un état "réussi"."""

        from integrations.higgsfield.types import CostEstimate, ModelParam, ModelSchema

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

        identity_lock = ReleaseCandidateIdentityLock(C)
        gate = GenerationApprovalGate(real_provider, identity_lock=identity_lock)
        activation_service = RequestScopedActivationService(gate, identity_lock)
        provider_activation_service = ControlledRealProviderActivationService(
            gate, identity_lock, activation_service
        )

        request = _conforming_request()

        # Le Gate technique APPROVE bel et bien (démontrant que la
        # frontière P2.26 n'est PAS un doublon du Gate) ...
        self.assertEqual(gate.evaluate(request).decision.value, "APPROVED")

        # ... mais la préparation P2.21 -> P2.26 refuse quand même, à
        # cause EXCLUSIVEMENT de la frontière Provider.
        from agents.controlled_real_provider_activation import (
            ControlledRealProviderActivationRejectedError,
        )

        rs_contract = activation_service.prepare_activation(request)

        with self.assertRaises(ControlledRealProviderActivationRejectedError) as ctx:
            provider_activation_service.prepare(request, rs_contract)

        self.assertTrue(
            any("real" in reason.lower() for reason in ctx.exception.reasons),
            ctx.exception.reasons,
        )
        fake_client.create_job.assert_not_called()
        fake_client.run.assert_not_called()

    def test_12_client_create_job_never_invoked_by_the_real_provider(self):
        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(job_type="seedance_2_0", prompt="anything")

        fake_client.create_job.assert_not_called()

    def test_13_no_subprocess_or_cli_invocation_reaches_the_real_client(self):
        """`HiggsfieldProvider.create_job()` raises avant même de
        toucher `self.client` -- aucune méthode du client (et donc
        aucun subprocess/CLI réel) n'est jamais appelée."""

        fake_client = MagicMock()
        real_provider = HiggsfieldProvider(client=fake_client)

        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            real_provider.create_job(job_type="seedance_2_0", prompt="anything")

        fake_client.run.assert_not_called()
        fake_client.create_job.assert_not_called()
        fake_client.account_status.assert_not_called()
        fake_client.estimate_cost.assert_not_called()


# ----------------------------------------------------------------------
# CALL-SITE INVARIANT (Étape 16)
# ----------------------------------------------------------------------


class TestCallSiteInvariant(unittest.TestCase):
    def test_14_exactly_one_production_create_job_call_site(self):
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
                tree = ast.parse(text)
                for node in ast.walk(tree):
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "create_job"
                    ):
                        offenders.append(str(path.relative_to(PROJECT_ROOT)))

        director_text = (PROJECT_ROOT / "director.py").read_text(encoding="utf-8-sig")
        director_tree = ast.parse(director_text)
        for node in ast.walk(director_tree):
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
        gjs_tree = ast.parse(gjs_text)
        real_calls = [
            node
            for node in ast.walk(gjs_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "create_job"
        ]
        self.assertEqual(len(real_calls), 1)

    def test_15_real_create_job_never_returns_and_never_touches_client(self):
        """
        Phase P2.35 — REVISED (superseded "body == 1 raise statement"
        invariant, which P2.35 intentionally supersedes by design; see
        the equivalent, more detailed note in tests/test_phase_p2_29_
        explicit_human_activation_entry_point.py::test_provider_py_
        unchanged_create_job_still_disabled). Re-asserts, at this
        phase's snapshot too, the properties that actually matter: no
        `ast.Return` anywhere in the function, no reference to
        `self.client` anywhere in the function, and the function's last
        top-level statement unconditionally raises.
        """

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
        self.assertIsInstance(real_create_job.body[-1], ast.Raise)
        self.assertEqual(
            [n for n in ast.walk(real_create_job) if isinstance(n, ast.Return)], []
        )
        self.assertEqual(
            [
                n
                for n in ast.walk(real_create_job)
                if isinstance(n, ast.Attribute)
                and n.attr == "client"
                and isinstance(n.value, ast.Name)
                and n.value.id == "self"
            ],
            [],
        )


# ----------------------------------------------------------------------
# SECURITY SCAN (Étape 23)
# ----------------------------------------------------------------------


class TestSecurityScan(unittest.TestCase):
    TOKENS = (
        "REAL_GENERATION_ENABLED",
        "HIGGSFIELD_ENABLED",
        "PRODUCTION_MODE",
        "FORCE_GENERATION",
        "force_generate",
        "generate_now",
        "skip_gate",
        "bypass",
        "auto_authorize",
        "auto_activation",
    )
    EXCLUDED = {"agents/production_activation_boundary.py"}

    def test_16_no_forbidden_tokens_in_production_code(self):
        patterns = {t: re.compile(r"\b" + re.escape(t) + r"\b") for t in self.TOKENS}
        offenders = []
        for base in ("agents", "integrations", "scripts"):
            base_dir = PROJECT_ROOT / base
            if not base_dir.exists():
                continue
            for path in base_dir.rglob("*.py"):
                rel = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
                if rel in self.EXCLUDED:
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

    def test_17_no_component_constructs_real_generation_authorization_in_new_code(self):
        """Ni provider.py, ni mock_provider.py, ni generation_job_
        service.py ne construisent jamais une RealGenerationAuthorization
        -- l'autorité humaine reste strictement externe."""

        offenders = []
        for path in (
            PROJECT_ROOT / "integrations" / "higgsfield" / "provider.py",
            PROJECT_ROOT / "integrations" / "higgsfield" / "mock_provider.py",
            PROJECT_ROOT / "agents" / "generation_job_service.py",
        ):
            text = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "RealGenerationAuthorization"
                ):
                    offenders.append(str(path.relative_to(PROJECT_ROOT)))
        self.assertEqual(offenders, [])

    def test_18_no_module_level_or_class_level_global_authority_flag_in_touched_files(self):
        """Aucune variable de module/classe ressemblant à un flag
        d'activation globale n'existe dans les 3 fichiers modifiés par
        cette phase."""

        forbidden_names_pattern = re.compile(
            r"^\s*(?:[A-Z_]*ENABLED[A-Z_]*|[A-Z_]*ACTIVATION[A-Z_]*|"
            r"PRODUCTION_MODE|REAL_GENERATION_ENABLED)\s*(?::\s*\w+\s*)?=",
            re.MULTILINE,
        )
        for path in (
            PROJECT_ROOT / "integrations" / "higgsfield" / "provider.py",
            PROJECT_ROOT / "integrations" / "higgsfield" / "mock_provider.py",
            PROJECT_ROOT / "agents" / "generation_job_service.py",
        ):
            text = path.read_text(encoding="utf-8-sig")
            self.assertIsNone(
                forbidden_names_pattern.search(text),
                f"{path} appears to declare a module/class-level authority flag.",
            )


if __name__ == "__main__":
    unittest.main()
