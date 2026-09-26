import sys
from dataclasses import dataclass, replace as _dataclasses_replace
from pathlib import Path
from typing import Optional

from integrations.higgsfield.client import HiggsfieldClient

PROJECT_ROOT = Path(__file__).resolve().parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import (
    RequestScopedActivationContract,
    RequestScopedActivationService,
)
from agents.activation_readiness import ActivationReadinessEvaluator, ActivationReadinessReport
from agents.asset_preparation_system import AssetPreparationSystem
from agents.controlled_real_provider_activation import (
    ControlledRealProviderActivationContract,
    ControlledRealProviderActivationService,
)
from agents.critical_section_lock import FileCriticalSectionLock
from agents.director_pipeline import (
    BusinessMissionRequest,
    BusinessPipelineOrchestrator,
    DirectorPipelineContext,
)
from agents.executed_request_store import FileExecutedRequestStore
from agents.final_report_service import FinalReport, FinalReportService
from agents.generation_approval_gate import GenerationApprovalGate, GenerationRequest, RealGenerationAuthorization
from agents.generation_job_service import GenerationJobService
from agents.planner import VideoPlanner
from agents.pre_production_review import (
    PreProductionReview,
    PreProductionReviewInput,
    PreProductionReviewer,
)
from agents.activation_eligibility import (
    ActivationEligibilityChecker,
    ActivationEligibilityInput,
    ActivationEligibilityResult,
)
from agents.controlled_activation_composition import (
    extract_production_parameters,
    verify_authorization_binding,
    verify_generation_request_consistency,
    verify_handoff_ready,
)
from agents.human_authorization_handoff import (
    HumanAuthorizationHandoff,
    HumanAuthorizationHandoffBuilder,
    HumanAuthorizationHandoffInput,
)
from agents.production_activation_handoff import (
    ProductionActivationHandoff,
    ProductionActivationHandoffBuilder,
    ProductionActivationHandoffInput,
)
from agents.production_authority_intake import (
    ProductionAuthorityIntake,
    ProductionAuthorityIntakeInput,
    ProductionAuthorityIntakeReport,
)
from agents.production_readiness_handoff import (
    ProductionReadinessHandoff,
    ProductionReadinessHandoffBuilder,
    ProductionReadinessHandoffInput,
)
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.real_provider_activation_preflight import (
    ActivationPreflightEvaluator,
    ActivationPreflightReport,
)
from agents.real_provider_execution_gate import (
    RealProviderExecutionGate,
    RealProviderExecutionGateReport,
)
from agents.release_candidate_identity_lock import (
    ReleaseCandidateIdentityLock,
    VIDEO_005_RELEASE_CANDIDATE,
)
from agents.script_production_bridge import (
    ProductionPreparationInput,
    ProductionPreparationRequest,
    ScriptProductionBridge,
)
from agents.video_agent import DEFAULT_JOB_TYPE, VideoAgent
from agents.video_production_preparation import (
    VideoProductionPreparation,
    VideoProductionPreparationInput,
    VideoProductionPreparationResult,
)
from integrations.higgsfield.provider import HiggsfieldProvider


@dataclass(frozen=True)
class _DefaultChain:
    """Composants réels construits une seule fois (Phases C/D, G, P2.15,
    P2.18, P2.20, P2.21/22) et réutilisés par `_build_default_report_
    service()` ET `check_activation_readiness()` -- jamais dupliqués."""

    provider: HiggsfieldProvider
    identity_lock: ReleaseCandidateIdentityLock
    gate: GenerationApprovalGate
    lock: FileCriticalSectionLock
    activation_service: RequestScopedActivationService
    provider_activation_service: ControlledRealProviderActivationService
    job_service: GenerationJobService


@dataclass(frozen=True)
class PreparedRealGenerationActivation:
    """
    AI DIRECTOR — Explicit Human Activation Bundle (Phase P2.29).

    PRODUIT UNIQUEMENT par `AIDirector.prepare_real_generation_
    activation()` -- ne déclenche RIEN par lui-même. Transporte
    ensemble la `GenerationRequest` construite et les DEUX contrats
    d'activation (P2.21 + P2.26) déjà validés au moment de la
    préparation, mais PAS ENCORE consommés : la consommation
    définitive n'a lieu que si `AIDirector.execute_real_generation_
    activation()` est appelé EXPLICITEMENT et séparément, et
    uniquement si TOUTES les vérifications fraîches (Gate, Identity
    Lock, replay, UNKNOWN, budget, provider boundary) réussissent À
    CET INSTANT PRÉCIS -- rien dans ce bundle n'est une autorisation
    permanente.

    `mission_id` (Phase P3.34, optionnel, `None` par defaut) :
    OBSERVABILITY METADATA ONLY. Jamais lu, inspecte, ou compare par
    `prepare_real_generation_activation()` (qui ne le fixe jamais --
    il reste `None` sur tout bundle qu'elle construit elle-meme) ;
    stampe UNIQUEMENT par `compose_controlled_activation()`, APRES
    coup, via `dataclasses.replace()`, depuis `handoff.mission_id` --
    le meme handoff dont `request_id` a deja ete extrait, donc
    toujours coherent par construction avec `request.request_id`
    (jamais une valeur independante ou devinee). N'influence, ne
    remplace, ni ne duplique `request.request_id`, qui reste seul
    l'identite d'execution P2.
    """

    request: GenerationRequest
    activation_contract: RequestScopedActivationContract
    provider_activation_contract: ControlledRealProviderActivationContract
    mission_id: Optional[str] = None


class AIDirector:
    """Core controller for the AI automation system."""

    def __init__(self):
        self.root = Path(__file__).resolve().parent
        self.name = "AI DIRECTOR"
        self.version = "0.2.0"
        self.higgsfield = HiggsfieldClient()

    def check_higgsfield(self):
        """Check that the Higgsfield connector is operational."""
        try:
            workflows = self.higgsfield.list_workflows()

            video_workflows = [
                workflow
                for workflow in workflows
                if workflow.get("type") == "video"
            ]

            cinema_40 = any(
                workflow.get("job_type") == "cinematic_studio_video_4_0"
                for workflow in video_workflows
            )

            return {
                "connected": True,
                "video_workflows": len(video_workflows),
                "cinema_4_available": cinema_40,
            }

        except Exception as error:
            return {
                "connected": False,
                "error": str(error),
            }

    def _build_default_chain(self) -> _DefaultChain:
        """
        Construit la chaîne réelle Provider -> ApprovalGate ->
        GenerationJobService (Phases C/D, G, P2.15, P2.18, P2.20,
        P2.21/22), réutilisant le HiggsfieldClient déjà détenu par ce
        Director. Ne fait AUCUN appel réseau/CLI : seules des
        constructions d'objets. Factorisée hors de
        `_build_default_report_service()` (Phase P2.24) afin que
        `check_activation_readiness()` réutilise EXACTEMENT les mêmes
        composants réels, sans jamais les reconstruire séparément.

        Injecte un `FileExecutedRequestStore` (Phase P2.15,
        agents/executed_request_store.py) dans le Gate : ce projet
        n'ayant aucun processus long-vivant (uniquement des scripts
        CLI à courte durée de vie), le registre anti-rejeu doit
        survivre au-delà d'une seule invocation pour avoir un sens.
        Rien n'est écrit sur disque tant qu'aucune exécution réelle
        n'a lieu (mark_executed() n'est appelé qu'après un
        create_job() réel réussi, cf. GenerationJobService).

        Injecte également un `ReleaseCandidateIdentityLock` (Phase
        P2.18, agents/release_candidate_identity_lock.py) lié à la
        Release Candidate actuellement validée (Video 005) : ce
        CHEMIN RÉEL est donc le seul, avec les tests dédiés, à
        refuser toute requête dont le prompt, les assets ou les
        paramètres vidéo diffèrent de cette Release Candidate exacte
        — fermant le gap identifié en P2.17. Portée volontairement
        étroite à Video 005 (cf. docstring du module) : toute future
        vidéo nécessitera un nouveau contrat explicite.

        Injecte un `FileCriticalSectionLock` (Phase P2.20,
        agents/critical_section_lock.py) dans le `GenerationJobService`
        construit explicitement ici : ce CHEMIN RÉEL est donc le seul
        à fermer le risque TOCTOU (P2.16) entre deux processus réels
        partageant le même répertoire d'état
        (`self.root / "state" / "locks"`).

        Injecte un `RequestScopedActivationService` (Phase P2.21/P2.22,
        agents/activation_contract.py) et un
        `ControlledRealProviderActivationService` (Phase P2.26/P2.27,
        agents/controlled_real_provider_activation.py) dans ce même
        `GenerationJobService` -- ce câblage rend les deux mécanismes
        d'activation STRUCTURELLEMENT disponibles sur le chemin réel,
        mais ne les ACTIVE jamais : `run_video_mission()` ne
        construit, ne devine ni ne fournit AUCUN `activation_contract`
        ni AUCUN `provider_activation_contract` à `video_agent.run()`
        aujourd'hui -- ces deux arguments de
        `GenerationJobService.execute()` restent donc `None` sur ce
        chemin, exactement comme avant P2.22/P2.27, tant qu'une phase
        future ne décide pas explicitement de les fournir.
        """

        provider = HiggsfieldProvider(client=self.higgsfield)
        executed_request_store = FileExecutedRequestStore(
            self.root / "state" / "executed_requests.json"
        )
        identity_lock = ReleaseCandidateIdentityLock(VIDEO_005_RELEASE_CANDIDATE)
        gate = GenerationApprovalGate(
            provider,
            executed_request_store=executed_request_store,
            identity_lock=identity_lock,
        )
        lock = FileCriticalSectionLock(self.root / "state" / "locks")
        activation_service = RequestScopedActivationService(gate, identity_lock)
        provider_activation_service = ControlledRealProviderActivationService(
            gate, identity_lock, activation_service
        )
        job_service = GenerationJobService(
            provider,
            gate,
            lock=lock,
            activation_service=activation_service,
            provider_activation_service=provider_activation_service,
        )
        return _DefaultChain(
            provider=provider,
            identity_lock=identity_lock,
            gate=gate,
            lock=lock,
            activation_service=activation_service,
            provider_activation_service=provider_activation_service,
            job_service=job_service,
        )

    def _build_default_report_service(self) -> FinalReportService:
        """Construit la chaîne réelle (cf. `_build_default_chain()`)
        et l'enveloppe dans un `FinalReportService` (Phase J)."""

        chain = self._build_default_chain()
        return FinalReportService(chain.provider, chain.gate, job_service=chain.job_service)

    def check_activation_readiness(
        self,
        request: GenerationRequest,
        activation_contract: Optional[RequestScopedActivationContract] = None,
    ) -> ActivationReadinessReport:
        """
        AI DIRECTOR — Activation Readiness Protocol (Phase P2.24).

        Évaluation PURE EN LECTURE de readiness pour `request`, contre
        la chaîne réelle (`_build_default_chain()`, mêmes composants
        que `run_video_mission()`). N'appelle JAMAIS `create_job()`,
        ne construit JAMAIS de `RealGenerationAuthorization` ni ne
        consomme un `activation_contract` -- cf.
        agents/activation_readiness.py. Une réponse `READY` NE
        SIGNIFIE JAMAIS que ce Director va générer quoi que ce soit :
        `run_video_mission()` reste le seul point d'entrée qui exécute
        réellement, et lui seul décide, séparément, s'il exécute.
        """

        chain = self._build_default_chain()
        evaluator = ActivationReadinessEvaluator(
            chain.gate,
            chain.identity_lock,
            chain.activation_service,
            job_service=chain.job_service,
        )
        return evaluator.evaluate(request, activation_contract=activation_contract)

    def check_real_provider_execution_gate(
        self,
        request: GenerationRequest,
        activation_contract: Optional[RequestScopedActivationContract] = None,
        provider_activation_contract: Optional[ControlledRealProviderActivationContract] = None,
    ) -> RealProviderExecutionGateReport:
        """
        AI DIRECTOR — Real Provider Execution Gate Entry Point (Phase P2.36).

        Évaluation PURE EN LECTURE, contre la chaîne réelle (mêmes
        composants que `run_video_mission()`/`check_activation_
        readiness()`), des ONZE dimensions du Gate d'exécution (les dix
        de `check_activation_readiness()` plus la frontière d'activation
        Provider, P2.26). N'appelle JAMAIS `create_job()`, ne construit
        JAMAIS de `RealGenerationAuthorization` ni ne consomme un
        `activation_contract`/`provider_activation_contract` -- cf.
        agents/real_provider_execution_gate.py. Une réponse `APPROVED`
        NE SIGNIFIE JAMAIS que ce Director va générer quoi que ce soit :
        `run_video_mission()` et `execute_real_generation_activation()`
        restent les seuls points qui exécutent réellement, et eux seuls
        décident, séparément, s'ils exécutent.
        """

        chain = self._build_default_chain()
        execution_gate = RealProviderExecutionGate(
            chain.gate,
            chain.identity_lock,
            chain.activation_service,
            chain.provider_activation_service,
            job_service=chain.job_service,
        )
        return execution_gate.evaluate(
            request,
            activation_contract=activation_contract,
            provider_activation_contract=provider_activation_contract,
        )

    def check_activation_preflight(
        self,
        request: GenerationRequest,
        activation_contract: Optional[RequestScopedActivationContract] = None,
        provider_activation_contract: Optional[ControlledRealProviderActivationContract] = None,
    ) -> ActivationPreflightReport:
        """
        AI DIRECTOR — Real Provider Activation Preflight Entry Point (Phase P2.37).

        Évaluation PURE EN LECTURE, contre la chaîne réelle (mêmes
        composants que `run_video_mission()`/`check_activation_
        readiness()`/`check_real_provider_execution_gate()`), du
        preflight complet -- cf. agents/real_provider_activation_
        preflight.py. Répond à « si une phase future devait ouvrir le
        Provider réel, quelles conditions sont déjà satisfaites ? »,
        jamais à « puis-je lancer maintenant la génération ? ».
        N'appelle JAMAIS `create_job()` sur la chaîne réelle de ce
        Director (seule une sonde interne, contre un Provider jetable
        à client inerte, touche `create_job()` -- cf. docstring de
        `agents/real_provider_activation_preflight.py`). Ne construit
        jamais d'autorisation ni de contrat, ne consomme jamais rien.
        """

        chain = self._build_default_chain()
        preflight_evaluator = ActivationPreflightEvaluator(
            chain.gate,
            chain.identity_lock,
            chain.activation_service,
            chain.provider_activation_service,
            job_service=chain.job_service,
        )
        return preflight_evaluator.evaluate(
            request,
            activation_contract=activation_contract,
            provider_activation_contract=provider_activation_contract,
        )

    def run_video_mission(
        self,
        video_id: str,
        title: str,
        hook: str,
        objective: str,
        # Aligné sur le plafond réel confirmé pour seedance_2_0
        # (Phase P1.2-bis) — cf. agents/planner.py:create_zephyr_plan().
        duration: int = 15,
        job_type: str = DEFAULT_JOB_TYPE,
        approved: bool = False,
        real_generation_authorization: Optional[RealGenerationAuthorization] = None,
        report_service: Optional[FinalReportService] = None,
        timeout_seconds: float = 600,
        interval_seconds: float = 3,
    ) -> FinalReport:
        """
        AI DIRECTOR — Orchestration Director -> Planner -> VideoAgent
        -> FinalReportService (Phase L, MASTER PROMPT V2).

        Réutilise intégralement les Phases précédentes sans dupliquer
        leur logique :
        - VideoPlanner (V1) construit le VideoPlan.
        - PromptAssemblySystem (V1) fournit le Master Prompt.
        - VideoAgent (Phase K) traduit le plan en GenerationRequest.
        - FinalReportService (Phase J), qui délègue lui-même à
          GenerationApprovalGate (Phase G) et GenerationJobService
          (Phase H), reste seul responsable de toute décision
          d'approbation, de coût, et de la (non-)création de job.

        SÉCURITÉ :
        - `approved` reste `False` par défaut : ce Director n'approuve
          JAMAIS automatiquement une génération.
        - `real_generation_authorization` (Phase P2.11) reste `None`
          par défaut : simple relais explicite vers VideoAgent ->
          GenerationRequest, jamais déduit d'`approved` ni construit
          automatiquement ici. Sans lui, GenerationApprovalGate ne
          renvoie jamais APPROVED (cf. generation_approval_gate.py).
        - `report_service` est injectable pour les tests (Mock) ; sans
          injection, la chaîne réelle est construite (mais reste
          protégée par HiggsfieldRealGenerationDisabledError au niveau
          de HiggsfieldProvider.create_job(), Phase C/D, non modifiée).
        - Cette méthode n'appelle jamais create_job() directement.
        """

        planner = VideoPlanner(self.root)

        plan = planner.create_zephyr_plan(
            video_id=video_id,
            title=title,
            hook=hook,
            objective=objective,
            duration=duration,
        )

        prompt_assembly = PromptAssemblySystem(self.root)
        asset_preparation = AssetPreparationSystem(self.root)
        video_agent = VideoAgent(
            prompt_assembly=prompt_assembly,
            asset_preparation=asset_preparation,
        )

        active_report_service = report_service or self._build_default_report_service()

        return video_agent.run(
            plan,
            active_report_service,
            job_type=job_type,
            approved=approved,
            real_generation_authorization=real_generation_authorization,
            timeout_seconds=timeout_seconds,
            interval_seconds=interval_seconds,
        )

    def prepare_real_generation_activation(
        self,
        video_id: str,
        title: str,
        hook: str,
        objective: str,
        real_generation_authorization: RealGenerationAuthorization,
        duration: int = 15,
        job_type: str = DEFAULT_JOB_TYPE,
        approved: bool = False,
        report_service: Optional[FinalReportService] = None,
    ) -> PreparedRealGenerationActivation:
        """
        AI DIRECTOR — Explicit Human Activation Entry Point (Phase P2.29).

        STOP -- CE QUE CETTE MÉTHODE N'EST PAS :
        Ce n'EST PAS `run_video_mission()`. Elle ne génère RIEN,
        n'appelle JAMAIS `create_job()`, et ne consomme aucun contrat
        -- elle prépare UNIQUEMENT, à partir d'une autorisation
        humaine EXPLICITEMENT fournie par l'appelant (jamais
        construite ici), les DEUX contrats d'activation (P2.21 +
        P2.26) nécessaires à une future EXÉCUTION SÉPARÉE et
        EXPLICITE via `execute_real_generation_activation()`.
        `preparation réussie != génération exécutée` (Étape 7,
        rapport P2.29) : le `GenerationRequest` retourné n'a jamais
        été soumis à `GenerationJobService.execute()`.

        `real_generation_authorization` est un paramètre REQUIS
        (aucune valeur par défaut) : appeler cette méthode sans en
        fournir une lève immédiatement une `TypeError` Python -- ce
        n'est jamais un comportement silencieux. Ce Director ne
        construit, ne devine ni ne dérive JAMAIS cet objet lui-même,
        ni de `approved`, ni d'aucune autre valeur -- `approved`
        (consentement technique/budgétaire) et
        `real_generation_authorization` (autorité humaine) restent
        deux axes strictement indépendants (Étape 7).

        Double consentement -- la préparation ÉCHOUE (`Activation
        RejectedError` ou `ControlledRealProviderActivationRejected
        Error`, propagées telles quelles) si L'UN QUELCONQUE des
        éléments suivants n'est pas réuni, FRAIS, à cet instant : Gate
        technique (coût/budget/replay/UNKNOWN), Identity Lock
        (request/prompt/assets), autorisation humaine liée à ce
        request_id exact, frontière Provider (P2.26 -- toujours
        refusée contre le vrai `HiggsfieldProvider`, cf.
        `agents/controlled_real_provider_activation.py`).

        `report_service` (optionnel, réservé aux tests) : si fourni,
        ses `gate`/`job_service.activation_service`/`job_service.
        provider_activation_service` sont réutilisés TELS QUELS
        (jamais reconstruits) pour la préparation -- permet de
        démontrer un scénario Mock positif sans jamais toucher au
        vrai CLI Higgsfield. Sans injection, la chaîne réelle
        (`_build_default_chain()`) est utilisée, protégée comme
        toujours par `HiggsfieldRealGenerationDisabledError`.
        """

        planner = VideoPlanner(self.root)

        plan = planner.create_zephyr_plan(
            video_id=video_id,
            title=title,
            hook=hook,
            objective=objective,
            duration=duration,
        )

        prompt_assembly = PromptAssemblySystem(self.root)
        asset_preparation = AssetPreparationSystem(self.root)
        video_agent = VideoAgent(
            prompt_assembly=prompt_assembly,
            asset_preparation=asset_preparation,
        )

        request = video_agent.build_request(
            plan,
            job_type=job_type,
            approved=approved,
            real_generation_authorization=real_generation_authorization,
        )

        if report_service is not None:
            gate = report_service.gate
            identity_lock = gate.identity_lock
            activation_service = report_service.job_service.activation_service
            provider_activation_service = report_service.job_service.provider_activation_service
            if activation_service is None or provider_activation_service is None:
                raise ValueError(
                    "prepare_real_generation_activation() requires the "
                    "supplied report_service's job_service to have both "
                    "activation_service and provider_activation_service "
                    "configured -- refusing to silently skip either "
                    "activation layer (fail closed)."
                )
        else:
            chain = self._build_default_chain()
            identity_lock = chain.identity_lock
            activation_service = chain.activation_service
            provider_activation_service = chain.provider_activation_service

        activation_contract = activation_service.prepare_activation(request)
        provider_activation_contract = provider_activation_service.prepare(
            request, activation_contract
        )

        return PreparedRealGenerationActivation(
            request=request,
            activation_contract=activation_contract,
            provider_activation_contract=provider_activation_contract,
        )

    def execute_real_generation_activation(
        self,
        prepared: PreparedRealGenerationActivation,
        report_service: Optional[FinalReportService] = None,
        timeout_seconds: float = 600,
        interval_seconds: float = 3,
    ) -> FinalReport:
        """
        AI DIRECTOR — Explicit Execution of a Prepared Activation (Phase P2.29).

        Appel EXPLICITE et SÉPARÉ de `prepare_real_generation_
        activation()` -- jamais chaîné automatiquement. C'est, avec
        `run_video_mission()` (qui ne fournit JAMAIS de contrats), le
        SEUL autre point de ce Director qui puisse mener à
        `GenerationJobService.execute()` avec des contrats
        d'activation -- aucun nouveau chemin vers le Provider n'est
        introduit : cette méthode délègue intégralement à
        `FinalReportService.generate()`, exactement comme
        `run_video_mission()`. `HiggsfieldProvider.create_job()`
        (integrations/higgsfield/provider.py, NON MODIFIÉ) reste
        inconditionnellement désactivé -- une préparation valide,
        même les deux contrats validés, ne change rien à cette
        frontière.

        Phase P3.34 : `prepared.mission_id` (OBSERVABILITY METADATA
        ONLY, `None` unless `prepared` came from `compose_controlled_
        activation()`) est relayé tel quel à `FinalReportService.
        generate()`, jamais utilisé pour une décision ici.
        """

        active_report_service = report_service or self._build_default_report_service()

        return active_report_service.generate(
            prepared.request,
            timeout_seconds=timeout_seconds,
            interval_seconds=interval_seconds,
            activation_contract=prepared.activation_contract,
            provider_activation_contract=prepared.provider_activation_contract,
            mission_id=prepared.mission_id,
        )

    def status(self):
        print("=" * 60)
        print(f"{self.name} v{self.version}")
        print("=" * 60)

        print(f"Project root : {self.root}")
        print("Status       : ONLINE")

        result = self.check_higgsfield()

        if result["connected"]:
            print("Higgsfield   : CONNECTED")
            print(f"Video models : {result['video_workflows']}")
            print(
                "Cinema 4.0   : "
                + ("AVAILABLE" if result["cinema_4_available"] else "NOT FOUND")
            )
        else:
            print("Higgsfield   : ERROR")
            print(f"Error        : {result['error']}")

        print("Claude       : READY FOR INTEGRATION")
        print("=" * 60)

    def run_business_pipeline(
        self,
        request: BusinessMissionRequest,
        orchestrator: Optional[BusinessPipelineOrchestrator] = None,
    ) -> DirectorPipelineContext:
        """
        AI DIRECTOR — Business Pipeline Integration Entry Point (Phase P3.11).

        Orchestrates the six P3 business agents (Strategy -> Content ->
        Quality -> Publishing preparation -> Analytics -> Optimization)
        via `BusinessPipelineOrchestrator` (agents/director_pipeline.py,
        default: real, deterministic agent instances). Entirely SEPARATE
        from `run_video_mission()`/the P2 real-generation chain: this
        method never touches `HiggsfieldProvider`, `GenerationApprovalGate`,
        `GenerationJobService`, or any activation contract, and never
        calls `create_job()` directly or indirectly. `orchestrator` is
        injectable (tests may supply one built from fake agents) --
        without injection, the real chain is constructed, but "real" here
        means the real STRATEGY/CONTENT/QUALITY/PUBLISHING-PREPARATION/
        ANALYTICS/OPTIMIZATION agents, none of which can reach Higgsfield,
        a social platform, or any P2 authority mechanism (verified
        structurally by each agent's own AST security tests, P3.5-P3.10).
        """

        active_orchestrator = orchestrator or BusinessPipelineOrchestrator()
        return active_orchestrator.run(request)

    def prepare_production_from_script(
        self,
        request: ProductionPreparationInput,
        bridge: Optional[ScriptProductionBridge] = None,
    ) -> ProductionPreparationRequest:
        """
        AI DIRECTOR — Script -> Production Bridge Integration Entry Point (Phase P3.13).

        Delegates entirely to `ScriptProductionBridge.prepare()`
        (agents/script_production_bridge.py, default: a real,
        unconfigured bridge -- no `PromptAssemblySystem`/
        `AssetPreparationSystem` injected unless the caller does so via
        `bridge`). Purely additive: never called from
        `run_business_pipeline()` or `run_video_mission()`, never
        constructs a `VideoPlan`, never calls `VideoAgent`,
        `GenerationApprovalGate`, `GenerationJobService`, or
        `HiggsfieldProvider`. A `READY` result means only "technical
        preparation possible" -- this method never generates, approves,
        or authorizes anything (P3.13 Section 13).
        """

        active_bridge = bridge or ScriptProductionBridge()
        return active_bridge.prepare(request)

    def prepare_video_generation_request(
        self,
        request: VideoProductionPreparationInput,
        preparation: Optional[VideoProductionPreparation] = None,
    ) -> VideoProductionPreparationResult:
        """
        AI DIRECTOR — Video Production Preparation Integration Entry Point (Phase P3.14).

        Delegates entirely to `VideoProductionPreparation.prepare()`
        (agents/video_production_preparation.py, default: a real,
        unconfigured integration -- no `PromptAssemblySystem`/
        `AssetPreparationSystem` injected unless the caller does so via
        `preparation`). Sequences `ScriptProductionBridge` (P3.13) then
        `VideoAgent` (Phase K) and STOPS: the result carries a PREPARED
        `GenerationRequest` only -- never approved, never authorized,
        never executed. This method never calls
        `GenerationApprovalGate`, `GenerationJobService`,
        `HiggsfieldProvider`, or `create_job`, and is purely additive:
        never invoked from `run_business_pipeline()` or
        `run_video_mission()`.
        """

        active_preparation = preparation or VideoProductionPreparation()
        return active_preparation.prepare(request)

    def review_video_generation_request(
        self,
        request: PreProductionReviewInput,
        reviewer: Optional[PreProductionReviewer] = None,
    ) -> PreProductionReview:
        """
        AI DIRECTOR — Pre-Production Review Integration Entry Point (Phase P3.15).

        Delegates entirely to `PreProductionReviewer.review()` (agents/
        pre_production_review.py, default: a real, stateless reviewer).
        Reviews a P3.14 `VideoProductionPreparationResult` for
        structural production readiness and STOPS: the result is a
        `PASS`/`FAIL` `PreProductionReview` only -- never an approval,
        never an authorization, never an activation, never an
        execution. This method never calls `GenerationApprovalGate`,
        `GenerationJobService`, `HiggsfieldProvider`, `create_job`, or
        `MissionStateMachine.transition`, and is purely additive: never
        invoked from `run_business_pipeline()`, `run_video_mission()`,
        or `prepare_video_generation_request()`.
        """

        active_reviewer = reviewer or PreProductionReviewer()
        return active_reviewer.review(request)

    def handoff_video_generation_request(
        self,
        request: ProductionReadinessHandoffInput,
        builder: Optional[ProductionReadinessHandoffBuilder] = None,
    ) -> ProductionReadinessHandoff:
        """
        AI DIRECTOR — Production Readiness Handoff Integration Entry Point (Phase P3.17).

        Delegates entirely to `ProductionReadinessHandoffBuilder.build()`
        (agents/production_readiness_handoff.py, default: a real,
        stateless builder). Formalizes that a P3.15 `PreProductionReview`
        has completed the P3 technical review process and STOPS: the
        result is a `READY_FOR_PRODUCTION_AUTHORITY`/`NOT_READY`
        `ProductionReadinessHandoff` only -- never an approval, never an
        authorization, never an activation, never an execution. This
        method never calls `GenerationApprovalGate`, `GenerationJob
        Service`, `HiggsfieldProvider`, `create_job`, or `MissionState
        Machine.transition`, and is purely additive: never invoked from
        `run_business_pipeline()`, `run_video_mission()`, `prepare_
        video_generation_request()`, or `review_video_generation_
        request()`.
        """

        active_builder = builder or ProductionReadinessHandoffBuilder()
        return active_builder.build(request)

    def production_authority_intake(
        self,
        request: ProductionAuthorityIntakeInput,
        intake: Optional[ProductionAuthorityIntake] = None,
    ) -> ProductionAuthorityIntakeReport:
        """
        AI DIRECTOR — Production Authority Intake Integration Entry Point (Phase P3.18).

        Delegates entirely to `ProductionAuthorityIntake.intake()`
        (agents/production_authority_intake.py, default: a real,
        stateless intake). Determines whether a P3.17 `ProductionReadiness
        Handoff` is STRUCTURALLY ACCEPTABLE for the existing P2
        production authority chain to consider, and STOPS: the result
        is an `ACCEPTED_FOR_P2_CONSIDERATION`/`REJECTED` `Production
        AuthorityIntakeReport` only -- never an approval, never an
        authorization, never an activation, never an execution. This
        method never calls `GenerationApprovalGate`, `GenerationJob
        Service`, `HiggsfieldProvider`, `create_job`, or `MissionState
        Machine.transition`, and is purely additive: never invoked from
        `run_business_pipeline()`, `run_video_mission()`, `prepare_
        video_generation_request()`, `review_video_generation_request()`,
        or `handoff_video_generation_request()`. A caller who wants a
        live P2 readiness/approval/activation opinion must invoke
        `check_activation_readiness()`, `check_real_provider_execution_
        gate()`, `check_activation_preflight()`, or `prepare_real_
        generation_activation()` separately and explicitly -- this
        method never chains into any of them.
        """

        active_intake = intake or ProductionAuthorityIntake()
        return active_intake.intake(request)

    def human_authorization_handoff(
        self,
        request: HumanAuthorizationHandoffInput,
        builder: Optional[HumanAuthorizationHandoffBuilder] = None,
    ) -> HumanAuthorizationHandoff:
        """
        AI DIRECTOR — Human Authorization Handoff Integration Entry Point (Phase P3.19).

        Delegates entirely to `HumanAuthorizationHandoffBuilder.build()`
        (agents/human_authorization_handoff.py, default: a real,
        stateless builder). Determines whether a P3.18 `Production
        AuthorityIntakeReport` is merely ELIGIBLE to receive explicit
        human authorization, or whether an already-supplied `Real
        GenerationAuthorization` (passed in via `request.real_
        generation_authorization`, NEVER constructed by this method)
        is structurally valid and correctly bound -- and STOPS: the
        result is an `INTAKE_NOT_ACCEPTED`/`ELIGIBLE_FOR_HUMAN_
        AUTHORIZATION`/`AUTHORIZATION_STRUCTURALLY_VALID`/
        `AUTHORIZATION_REJECTED` `HumanAuthorizationHandoff` only --
        never an approval, never an activation, never an execution.
        This method never calls `GenerationApprovalGate`, `Generation
        JobService`, `HiggsfieldProvider`, `create_job`, `prepare_real_
        generation_activation()`, `execute_real_generation_activation()`,
        or `MissionStateMachine.transition`, and is purely additive:
        never invoked from `run_business_pipeline()`, `run_video_
        mission()`, `prepare_video_generation_request()`, `review_video_
        generation_request()`, `handoff_video_generation_request()`, or
        `production_authority_intake()`. A caller who wants to actually
        prepare/execute a real generation with a validated authorization
        must call `prepare_real_generation_activation()`/`execute_real_
        generation_activation()` separately and explicitly -- this
        method never chains into either of them.
        """

        active_builder = builder or HumanAuthorizationHandoffBuilder()
        return active_builder.build(request)

    def activation_eligibility(
        self,
        request: ActivationEligibilityInput,
        checker: Optional[ActivationEligibilityChecker] = None,
    ) -> ActivationEligibilityResult:
        """
        AI DIRECTOR — Activation Eligibility Integration Entry Point (Phase P3.20).

        Delegates entirely to `ActivationEligibilityChecker.check_
        eligibility()` (agents/activation_eligibility.py, default: a
        real, stateless checker). Determines whether a P3.19 `Human
        AuthorizationHandoff` is eligible to proceed to the existing P2
        activation boundary, or whether an already-prepared activation
        snapshot (`activation_contract`/`provider_activation_contract`,
        NEVER constructed by this method) is structurally valid and
        correctly bound -- and STOPS: the result is a `HUMAN_
        AUTHORIZATION_NOT_VALID`/`ELIGIBLE_FOR_ACTIVATION`/`ACTIVATION_
        CONTRACT_STRUCTURALLY_VALID`/`NOT_ELIGIBLE_FOR_ACTIVATION`
        `ActivationEligibilityResult` only -- never an activation, never
        an execution. This method never calls `GenerationApprovalGate`,
        `RequestScopedActivationService`, `ControlledRealProviderActiv
        ationService`, `GenerationJobService`, `HiggsfieldProvider`,
        `create_job`, `prepare_activation()`, `validate_activation()`,
        `prepare_real_generation_activation()`, `execute_real_
        generation_activation()`, or `MissionStateMachine.transition`,
        and is purely additive: never invoked from `run_business_
        pipeline()`, `run_video_mission()`, `prepare_video_generation_
        request()`, `review_video_generation_request()`, `handoff_video_
        generation_request()`, `production_authority_intake()`, or
        `human_authorization_handoff()`. A caller who wants to actually
        prepare/execute a real activation must call `prepare_real_
        generation_activation()`/`execute_real_generation_activation()`
        separately and explicitly -- this method never chains into
        either of them.
        """

        active_checker = checker or ActivationEligibilityChecker()
        return active_checker.check_eligibility(request)

    def production_activation_handoff(
        self,
        request: ProductionActivationHandoffInput,
        builder: Optional[ProductionActivationHandoffBuilder] = None,
    ) -> ProductionActivationHandoff:
        """
        AI DIRECTOR — Production Activation Handoff Integration Entry Point (Phase P3.21).

        Delegates entirely to `ProductionActivationHandoffBuilder.
        build()` (agents/production_activation_handoff.py, default: a
        real, stateless builder). Packages a P3.20 `ActivationEligibility
        Result` into a single, immutable, fully traceable `Production
        ActivationHandoff` -- the LAST handoff object before a future,
        separately-authorized "Controlled Activation / Execution" phase
        -- and STOPS: the result is a `NOT_ELIGIBLE_FOR_HANDOFF`/
        `ACTIVATION_HANDOFF_READY` `ProductionActivationHandoff` only --
        never an activation, never an execution. This method never
        calls `GenerationApprovalGate`, `RequestScopedActivationService`,
        `ControlledRealProviderActivationService`, `GenerationJobService`,
        `HiggsfieldProvider`, `create_job`, `prepare_activation()`,
        `validate_activation()`, `prepare_real_generation_activation()`,
        `execute_real_generation_activation()`, or `MissionStateMachine.
        transition`, and is purely additive: never invoked from
        `run_business_pipeline()`, `run_video_mission()`, `prepare_video_
        generation_request()`, `review_video_generation_request()`,
        `handoff_video_generation_request()`, `production_authority_
        intake()`, `human_authorization_handoff()`, or `activation_
        eligibility()`. A caller who wants to actually prepare/execute a
        real activation must call `prepare_real_generation_activation()`/
        `execute_real_generation_activation()` separately and explicitly
        -- this method never chains into either of them.
        """

        active_builder = builder or ProductionActivationHandoffBuilder()
        return active_builder.build(request)

    def compose_controlled_activation(
        self,
        handoff: ProductionActivationHandoff,
        real_generation_authorization: RealGenerationAuthorization,
        title: str,
        hook: str,
        objective: str,
        approved: bool = False,
        report_service: Optional[FinalReportService] = None,
    ) -> PreparedRealGenerationActivation:
        """
        AI DIRECTOR — Controlled Activation Composition Entry Point (Phase P3.23).

        Composes a P3.21 `ProductionActivationHandoff` with an
        EXPLICITLY caller-supplied `real_generation_authorization`
        (never constructed here) into a real call to the existing,
        UNMODIFIED `prepare_real_generation_activation()` (Phase
        P2.29) -- and returns exactly what that method already
        returns, `PreparedRealGenerationActivation`. No new result
        type is introduced (Section 19). `COMPOSED` here means exactly
        what P2.29 already means by "prepared" -- never `ACTIVATED`,
        never `EXECUTING`, never `EXECUTED`: this method never calls
        `execute_real_generation_activation()`, `GenerationJobService.
        execute()`, or `create_job()`.

        Sequence (agents/controlled_activation_composition.py, reused
        verbatim, never duplicated):
        1. `verify_handoff_ready(handoff)` -- structural, offline;
           raises `ControlledActivationCompositionError` unless
           `handoff.status == ACTIVATION_HANDOFF_READY` and its
           content_hash is internally consistent.
        2. `verify_authorization_binding(handoff, real_generation_
           authorization)` -- structural, offline; raises unless the
           supplied authorization is a real `RealGenerationAuthorization`
           whose `authorization_id`/`request_id` exactly match this
           handoff's own.
        3. `extract_production_parameters(handoff)` -- reads
           `request_id`/`job_type`/`duration` from the handoff's own
           embedded, already-reviewed `GenerationRequest` (never
           reinvented). `title`/`hook`/`objective` are NOT extractable
           from any P3 contract (see module docstring's "WHY title/
           hook/objective ARE REQUIRED" -- `VideoPlan` is never
           embedded in the P3.13-P3.21 chain) and therefore remain
           REQUIRED, EXPLICIT parameters of this method, exactly
           mirroring `prepare_real_generation_activation()`'s own
           signature.
        4. Delegates, unmodified, to `self.prepare_real_generation_
           activation(...)` -- the SAME real entry point a human
           caller would use directly. Any `ActivationRejectedError`/
           `ControlledRealProviderActivationRejectedError` it raises
           (fresh Gate, Identity Lock, budget, replay, provider
           boundary -- all P2, none reimplemented here) propagates
           UNMODIFIED.
        5. `verify_generation_request_consistency(prepared.request,
           <the handoff's own reviewed GenerationRequest>)` -- the one
           genuinely new check this phase adds: confirms the freshly
           REBUILT request (Phase P2.29 always rebuilds from scratch)
           matches the one actually reviewed and authorized. Raises on
           ANY divergence -- never silently accepted.
        6. (Phase P3.34) `dataclasses.replace(prepared, mission_id=
           handoff.mission_id)` -- stamps OBSERVABILITY METADATA ONLY
           onto the returned bundle, post-hoc, from the exact same
           handoff `params.request_id` was already extracted from in
           step 3 (so mission_id and request_id are always consistent
           by single-source construction, never independently
           verified or guessed). Never passed into step 4's delegated
           call, never influences any P2 decision made there.

        Never calls `GenerationApprovalGate`, `RequestScopedActivation
        Service`, `ControlledRealProviderActivationService`,
        `GenerationJobService`, `HiggsfieldProvider`, `HiggsfieldClient`,
        or `MissionStateMachine.transition` directly -- all of that
        remains exclusively inside the single delegated call. Purely
        additive: never invoked from `run_business_pipeline()`,
        `run_video_mission()`, or any other P3.13-P3.22 entry point.
        """

        verify_handoff_ready(handoff)
        verify_authorization_binding(handoff, real_generation_authorization)
        params = extract_production_parameters(handoff)

        prepared = self.prepare_real_generation_activation(
            video_id=params.request_id,
            title=title,
            hook=hook,
            objective=objective,
            real_generation_authorization=real_generation_authorization,
            duration=params.duration,
            job_type=params.job_type,
            approved=approved,
            report_service=report_service,
        )

        reviewed_generation_request = (
            handoff.eligibility.human_authorization_handoff.intake.handoff.review.generation_request
        )
        verify_generation_request_consistency(prepared.request, reviewed_generation_request)

        # Phase P3.34 -- stamp mission_id (OBSERVABILITY METADATA ONLY,
        # see PreparedRealGenerationActivation docstring) from the SAME
        # handoff params.request_id was already extracted from above,
        # so it is trivially consistent with prepared.request.request_id
        # by single-source construction -- no separate binding check
        # is needed, and no P2 file (prepare_real_generation_activation
        # itself, GenerationApprovalGate, GenerationJobService, ...) is
        # touched or even aware this happened.
        return _dataclasses_replace(prepared, mission_id=handoff.mission_id)


def main():
    director = AIDirector()
    director.status()


if __name__ == "__main__":
    main()