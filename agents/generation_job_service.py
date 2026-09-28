"""
AI DIRECTOR — Generation Job Service v0.1 (Phase H, MASTER PROMPT V2)

Orchestration finale du pipeline "APPROVED -> createJob() -> WAIT/POLL
-> RESULT". Ce service est le SEUL point du projet autorisé à appeler
provider.create_job(), et UNIQUEMENT après avoir lui-même interrogé le
GenerationApprovalGate (Phase G) — jamais avec une décision fournie
par l'appelant, qui pourrait être falsifiée ou périmée.

Architecture (MASTER PROMPT V2) :

    GenerationRequest
         v
    GenerationJobService.execute()
         v
    GenerationApprovalGate.evaluate()   (Phase G, réutilisé tel quel,
         v                               ré-évalué à chaque exécution)
    [doit être APPROVED, sinon refus immédiat]
         v
    HiggsfieldProvider.create_job()     (réel : reste DISABLED, cf.
         v                               HiggsfieldRealGenerationDisabledError,
         v                               Phase C/D — NON modifié)
    GenerationApprovalGate.mark_executed(request_id)
         v
    HiggsfieldProvider.wait_for_job()
         v
    VideoResult (integrations.higgsfield.types)
         v
    GenerationJobOutcome

SÉCURITÉ (Phase H) — ne contourne JAMAIS les protections existantes :
- execute() n'appelle create_job() QUE si gate.evaluate(request),
  appelé à l'instant même, renvoie APPROVED. Aucun raccourci n'existe
  pour sauter cette vérification.
- Une requête déjà exécutée (mark_executed) est automatiquement
  refusée : gate.evaluate() renverra ALREADY_EXECUTED (logique déjà
  posée en Phase G, non dupliquée ici).
- La désactivation de create_job() sur le HiggsfieldProvider réel
  (Phase C/D) n'est ni modifiée ni contournée : si ce service était
  utilisé par erreur avec le Provider réel, HiggsfieldRealGeneration
  DisabledError se propage telle quelle, exactement comme avant cette
  phase.
- Ce module n'importe ni HiggsfieldClient, ni subprocess.

CRITICAL SECTION & CRASH RECOVERY (Phase P2.20) :
- `lock` (optionnel, `agents/critical_section_lock.py`) entoure
  TOUTE la séquence check-not-executed -> approbation finale (fraîche)
  -> create_job() -> mark_executed() -- jamais seulement une partie.
  Par défaut (`None`), un `NoOpCriticalSectionLock` est utilisé :
  AUCUNE exclusion mutuelle, comportement STRICTEMENT identique à
  avant cette phase pour tout code/test existant qui construit
  `GenerationJobService(provider, gate)` sans 3e argument. Le chemin
  de production réel (director.py) injecte explicitement un
  `FileCriticalSectionLock`. `CriticalSectionBusyError` (une autre
  exécution détient déjà le verrou pour ce `request_id`) n'est jamais
  interceptée ici : elle se propage telle quelle, fail-closed.
- `wait_for_job()` reste délibérément HORS du verrou : le polling
  peut durer jusqu'à `timeout_seconds`, et `mark_executed()` (déjà
  appelé avant) suffit à empêcher tout rejeu -- retenir le verrou
  pendant tout ce temps n'apporterait aucune garantie supplémentaire.
- Fenêtre de crash restante après P2.19 : `create_job()` peut réussir
  puis `mark_executed()` peut échouer (I/O, crash partiel) -- l'état
  réel devient ambigu (le job a peut-être été créé côté Higgsfield
  sans que ce fait soit enregistré localement). Ce module ne tente
  JAMAIS de deviner ni de re-essayer silencieusement dans ce cas :
    - `mark_executed()` échoue -> tentative de `gate.mark_unknown()`
      pour consigner explicitement l'ambiguïté (cf.
      agents/executed_request_store.py) ; en cas de succès,
      `GenerationJobUnknownStateError` est levée (revue humaine
      requise, aucun rejeu automatique possible -- le Gate renverra
      désormais EXECUTION_STATE_UNKNOWN pour ce `request_id`).
    - si `gate.mark_unknown()` échoue LUI AUSSI, aucun registre n'a
      pu consigner quoi que ce soit : `CriticalStateUnknownAndUnrecordedError`
      est levée à la place -- délibérément non capturée par ce module
      ni par `FinalReportService`, pour ne jamais masquer cette
      situation derrière un rapport typé qui laisserait croire à un
      état géré.

ACTIVATION CONTRACT WIRING (Phase P2.22) :
- `activation_service` (optionnel, `agents/activation_contract.py`,
  Phase P2.21) : par défaut (`None`), AUCUNE vérification
  supplémentaire n'est effectuée -- comportement STRICTEMENT
  identique à avant cette phase pour tout code/test existant qui
  construit `GenerationJobService(provider, gate)` sans cet argument.
- `execute()` accepte désormais `activation_contract` (Étape 3, API
  contract explicite -- JAMAIS créé implicitement : `execute(request)`
  seul ne construit, ne "devine" ni ne réutilise aucun contrat).
  `activation_contract=None` (défaut) -> comportement IDENTIQUE à
  P2.20, la notion même de contrat d'activation n'existe pas pour cet
  appel. `activation_contract` fourni -> exige `self.activation_service`
  configuré (sinon `ValueError` immédiat, avant même d'acquérir le
  verrou -- refuser de silencieusement ignorer un contrat fourni
  explicitement), puis, DANS le verrou, APRÈS la vérification fraîche
  du Gate et AVANT `create_job()` : `activation_service.
  validate_activation(request, activation_contract)` (qui ré-exécute
  lui-même, depuis zéro, Identity Lock + Gate + fraîcheur du contrat
  -- cf. agents/activation_contract.py). Un rejet devient
  `GenerationJobActivationRejectedError` (sous-classe de
  `GenerationJobExecutionError` : `FinalReportService` le traite donc
  automatiquement comme un NOT_EXECUTED, sans modification requise).
- Ordre de sécurité dans le verrou : fresh Gate.evaluate() -> [si
  contrat fourni] validate_activation() -> create_job() ->
  mark_executed(). Aucune étape n'est sautée, aucun raccourci
  n'existe. Le Provider réel reste inconditionnellement désactivé
  (HiggsfieldRealGenerationDisabledError, Phase C/D, non modifié) :
  même un contrat intégralement validé ne débloque RIEN au niveau du
  Provider -- cf. tests/test_phase_p2_22_activation_wiring.py.

WRITE-AHEAD (Phase P3.91, RISK #1 de P3.90) :
- P3.90 a démontré qu'un crash dur ou un `BaseException`
  (KeyboardInterrupt) entre `create_job()` et `mark_executed()`, ou
  une exception de `create_job()` après acceptation côté backend, ne
  laissait AUCUNE trace : le Gate renvoyait APPROVED et un second job
  était créé. Désormais `gate.mark_in_flight()` persiste, DANS le
  verrou et JUSTE AVANT `create_job()`, un marqueur lu comme
  EXECUTION_STATE_UNKNOWN ; `mark_executed()` le remplace dans la même
  écriture atomique. `gate.in_flight()` (context manager autour de
  `create_job()`) n'annule QUE son propre marqueur, et UNIQUEMENT sur
  `HiggsfieldRealGenerationDisabledError` (refus du Provider AVANT
  tout appel client) -- aucune méthode ne permet d'effacer un UNKNOWN
  existant (invariant P3.38). Le verrou orphelin reste une garde
  supplémentaire, plus la seule : le supprimer manuellement laisse la
  requête UNKNOWN.

CONTROLLED REAL-PROVIDER ACTIVATION WIRING (Phase P2.27) :
- `provider_activation_service` (optionnel,
  `agents/controlled_real_provider_activation.py`, Phase P2.26) : par
  défaut (`None`), comportement STRICTEMENT identique à avant cette
  phase.
- `execute()` accepte désormais `provider_activation_contract`
  (jamais créé implicitement). Fourni sans `self.
  provider_activation_service` configuré -> `ValueError` immédiat,
  avant même d'acquérir le verrou. Fourni sans `activation_contract`
  (Phase P2.21) également fourni -> `ValueError` immédiat : ce
  contrat P2.26 est TOUJOURS lié à un contrat P2.21 précis (`Controlled
  RealProviderActivationContract.request_scoped_activation_id`) et ne
  peut donc jamais être validé seul.
- Ordre de sécurité complet dans le verrou : fresh Gate.evaluate() ->
  [si fourni] validate_activation() (P2.21) -> [si fourni]
  ControlledRealProviderActivationService.validate() (P2.26, qui
  ré-inspecte lui-même le contrat P2.21 sans le consommer, et vérifie
  la frontière Provider par identité de méthode, jamais un booléen) ->
  create_job() -> mark_executed(). Un rejet à cette étape devient
  `GenerationJobProviderActivationRejectedError` (sous-classe de
  `GenerationJobExecutionError`, donc traité automatiquement comme
  NOT_EXECUTED par `FinalReportService`, sans modification requise).
- Contre le Provider réel, cette validation échoue TOUJOURS (la
  frontière Provider du contrat P2.26 le détecte AVANT même d'atteindre
  la ligne `create_job()`) -- mais `HiggsfieldProvider.create_job()`
  lui-même reste, de toute façon, inconditionnellement désactivé et
  n'est ni modifié ni contourné : double garde-fou, jamais un
  remplacement de l'autre.
"""

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import (
    ActivationRejectedError,
    RequestScopedActivationContract,
    RequestScopedActivationService,
)
from agents.controlled_real_provider_activation import (
    ControlledRealProviderActivationContract,
    ControlledRealProviderActivationRejectedError,
    ControlledRealProviderActivationService,
)
from agents.critical_section_lock import NoOpCriticalSectionLock
from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationApprovalResult,
    GenerationRequest,
)
from integrations.higgsfield.provider import BaseHiggsfieldProvider
from integrations.higgsfield.types import Job, VideoResult


def _sha256_of_file_or_none(path: Optional[str]) -> Optional[str]:
    """
    Phase P2.35 — recalcule le SHA-256 depuis le FICHIER RÉEL, jamais
    une valeur déclarée. `None` si le fichier est absent/illisible ou
    si `path` est `None` -- jamais une exception, jamais une valeur
    inventée. Logique de hachage identique à `AssetPreparationSystem.
    calculate_hash()`, `agents/release_candidate_identity_lock.py::
    _sha256_of_file()` et `agents/controlled_real_provider_activation.
    py::_sha256_of_file_or_none()` -- délibérément dupliquée ici (même
    convention déjà établie par ces deux modules) plutôt que
    ré-instanciée, pour ne pas coupler ce module à leurs effets de bord.
    """

    if path is None:
        return None

    try:
        sha256 = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except OSError:
        return None


def _face_reference_sha256_or_none(request: GenerationRequest) -> Optional[str]:
    """Phase P2.35 — SHA-256 réel du premier `image_references` de rôle
    "face_reference" porté par `request`, jamais une valeur déclarée."""

    for ref in request.image_references:
        if ref.role == "face_reference":
            return _sha256_of_file_or_none(ref.source)
    return None


class GenerationJobUnknownStateError(RuntimeError):
    """
    Phase P2.20 — Levée quand `create_job()` a réussi mais que
    `gate.mark_executed()` a échoué juste après. L'ambiguïté A ÉTÉ
    consignée avec succès via `gate.mark_unknown()` (cf.
    agents/executed_request_store.py) : le Gate renverra désormais
    `EXECUTION_STATE_UNKNOWN` pour ce `request_id`, bloquant tout
    rejeu automatique. Cette exception signale néanmoins l'anomalie à
    l'appelant immédiat -- elle n'est jamais transformée en rapport
    "réussi" ou "échoué" ordinaire, et n'est pas interceptée par
    `FinalReportService`.
    """

    def __init__(self, message: str, job: Optional[Job] = None):
        super().__init__(message)
        self.job = job


class CriticalStateUnknownAndUnrecordedError(RuntimeError):
    """
    Phase P2.20 — Levée quand `create_job()` a réussi, que
    `gate.mark_executed()` a échoué, ET que la tentative de secours
    `gate.mark_unknown()` a ÉGALEMENT échoué : AUCUN registre n'a pu
    consigner quoi que ce soit sur cette requête. Cas le plus grave
    prévu par ce module -- délibérément non capturée nulle part dans
    ce module ni dans `FinalReportService`, pour ne jamais présenter
    cette situation comme un état géré.
    """


class GenerationJobExecutionError(RuntimeError):
    """
    Levée lorsque execute() est appelé sans qu'une décision APPROVED
    fraîche du GenerationApprovalGate n'existe pour la requête. Aucun
    appel Provider n'a lieu avant que cette vérification ne passe.

    `approval` (Phase J) porte la décision structurée du Gate ayant
    causé le refus, pour éviter à un appelant (ex. FinalReportService)
    de devoir ré-appeler gate.evaluate() une seconde fois.
    """

    def __init__(
        self,
        message: str,
        approval: Optional[GenerationApprovalResult] = None,
    ):
        super().__init__(message)
        self.approval = approval


class GenerationJobActivationRejectedError(GenerationJobExecutionError):
    """
    Phase P2.22 — Levée quand un `activation_contract` a été fourni
    explicitement à `execute()` mais que
    `RequestScopedActivationService.validate_activation()` l'a rejeté
    (Phase P2.21 : mauvais request_id, contrat expiré/consommé/
    étranger, ou n'importe quelle re-vérification fraîche -- Gate,
    Identity Lock, coût, solde, replay -- ayant échoué À CET INSTANT
    PRÉCIS). Sous-classe de `GenerationJobExecutionError` : tout code
    existant qui capture ce dernier (ex. `FinalReportService.generate()`)
    traite donc automatiquement ce rejet comme un NOT_EXECUTED, sans
    modification. `create_job()` n'est jamais appelé dans ce cas.

    `activation_rejection` porte l'exception `ActivationRejectedError`
    d'origine (avec la liste complète des raisons), pour une revue
    humaine exhaustive sans devoir reconstituer l'appel.
    """

    def __init__(
        self,
        message: str,
        approval: Optional[GenerationApprovalResult] = None,
        activation_rejection: Optional[ActivationRejectedError] = None,
    ):
        super().__init__(message, approval=approval)
        self.activation_rejection = activation_rejection


class GenerationJobProviderActivationRejectedError(GenerationJobExecutionError):
    """
    Phase P2.27 — Levée quand un `provider_activation_contract` a été
    fourni explicitement à `execute()` mais que
    `ControlledRealProviderActivationService.validate()` l'a rejeté
    (Phase P2.26 : mauvais binding request_scoped_activation_id,
    contrat expiré/consommé, mutation de prompt/coût/identité depuis
    la préparation, ou -- systématiquement contre le Provider réel --
    frontière Provider non franchissable). Sous-classe de
    `GenerationJobExecutionError` : traité automatiquement comme
    NOT_EXECUTED par `FinalReportService.generate()`, sans
    modification. `create_job()` n'est jamais appelé dans ce cas.

    `provider_activation_rejection` porte l'exception
    `ControlledRealProviderActivationRejectedError` d'origine (liste
    complète des raisons), pour une revue humaine exhaustive.
    """

    def __init__(
        self,
        message: str,
        approval: Optional[GenerationApprovalResult] = None,
        provider_activation_rejection: Optional[
            ControlledRealProviderActivationRejectedError
        ] = None,
    ):
        super().__init__(message, approval=approval)
        self.provider_activation_rejection = provider_activation_rejection


@dataclass(frozen=True)
class GenerationJobOutcome:
    """Résultat complet d'une exécution de job réussie (job créé + polling terminé)."""

    request_id: str
    job_type: str
    approval: GenerationApprovalResult
    job: Job
    result: VideoResult

    @property
    def succeeded(self) -> bool:
        return self.result.succeeded


class GenerationJobService:
    """
    AI DIRECTOR — Generation Job Service v0.1 (Phase H)

    Ne connaît aucun détail du CLI (toute communication passe par un
    BaseHiggsfieldProvider injecté). Ne connaît aucun détail interne
    du Gate au-delà de son contrat public (evaluate/mark_executed).
    """

    def __init__(
        self,
        provider: BaseHiggsfieldProvider,
        gate: GenerationApprovalGate,
        lock: Optional[object] = None,
        activation_service: Optional[RequestScopedActivationService] = None,
        provider_activation_service: Optional[ControlledRealProviderActivationService] = None,
    ):
        """
        `lock` (Phase P2.20, `agents/critical_section_lock.py`) : par
        défaut (`None`), un `NoOpCriticalSectionLock` est utilisé --
        comportement STRICTEMENT identique à avant cette phase pour
        tout code/test existant qui construit
        `GenerationJobService(provider, gate)` sans 3e argument. Le
        chemin de production réel (director.py) injecte explicitement
        un `FileCriticalSectionLock`.

        `activation_service` (Phase P2.21/P2.22,
        `agents/activation_contract.py`) : par défaut (`None`), aucune
        vérification de contrat d'activation n'est possible --
        fournir un `activation_contract` à `execute()` sans avoir
        injecté ce service lève alors `ValueError` (fail closed,
        jamais un contrat silencieusement ignoré).

        `provider_activation_service` (Phase P2.26/P2.27,
        `agents/controlled_real_provider_activation.py`) : même
        comportement par défaut (`None`) -- fournir un
        `provider_activation_contract` à `execute()` sans avoir
        injecté ce service lève `ValueError` (fail closed).
        """

        self.provider = provider
        self.gate = gate
        self.lock = lock or NoOpCriticalSectionLock()
        self.activation_service = activation_service
        self.provider_activation_service = provider_activation_service

    def execute(
        self,
        request: GenerationRequest,
        timeout_seconds: float = 600,
        interval_seconds: float = 3,
        activation_contract: Optional[RequestScopedActivationContract] = None,
        provider_activation_contract: Optional[ControlledRealProviderActivationContract] = None,
    ) -> GenerationJobOutcome:
        """
        Exécute une génération SI ET SEULEMENT SI le Gate approuve la
        requête à l'instant de l'appel. Lève GenerationJobExecutionError
        sans jamais toucher au Provider si ce n'est pas le cas.

        Phase P2.20 : la séquence check-not-executed -> approbation
        fraîche -> create_job() -> mark_executed() est entièrement
        protégée par `self.lock` (cf. docstring de module).
        `CriticalSectionBusyError` se propage sans être interceptée.
        `wait_for_job()` reste délibérément hors du verrou.

        Phase P2.22 : `activation_contract`, si fourni EXPLICITEMENT
        par l'appelant (jamais créé ici), est validé DANS le verrou,
        juste après l'approbation fraîche du Gate et juste avant
        `create_job()` -- cf. docstring de module pour l'ordre complet
        et `agents/activation_contract.py` pour ce que
        `validate_activation()` revérifie.

        Phase P2.27 : `provider_activation_contract`, si fourni
        EXPLICITEMENT (jamais créé ici), est validé DANS le verrou,
        APRÈS `activation_contract` et AVANT `create_job()` -- exige
        `activation_contract` également fourni (ce contrat P2.26 est
        toujours lié à un contrat P2.21 précis, jamais autonome).
        """

        if activation_contract is not None and self.activation_service is None:
            raise ValueError(
                f"execute() received an activation_contract for request "
                f"'{request.request_id}' but this GenerationJobService "
                f"has no activation_service configured -- refusing to "
                f"silently ignore an explicitly supplied contract "
                f"(fail closed)."
            )

        if provider_activation_contract is not None:
            if self.provider_activation_service is None:
                raise ValueError(
                    f"execute() received a provider_activation_contract "
                    f"for request '{request.request_id}' but this "
                    f"GenerationJobService has no provider_activation_"
                    f"service configured -- refusing to silently ignore "
                    f"an explicitly supplied contract (fail closed)."
                )
            if activation_contract is None:
                raise ValueError(
                    f"execute() received a provider_activation_contract "
                    f"for request '{request.request_id}' without an "
                    f"activation_contract -- a Controlled Real-Provider "
                    f"Activation Contract is always bound to a specific "
                    f"RequestScopedActivationContract and can never be "
                    f"validated on its own (fail closed)."
                )

        with self.lock.acquire(request.request_id):
            approval = self.gate.evaluate(request)

            if approval.decision != GenerationApprovalDecision.APPROVED:
                raise GenerationJobExecutionError(
                    f"Cannot execute job for request '{request.request_id}': "
                    f"GenerationApprovalGate decision is "
                    f"{approval.decision.value}, not APPROVED. "
                    f"Reasons: {'; '.join(approval.reasons) or 'none provided'}",
                    approval=approval,
                )

            if activation_contract is not None:
                # Phase P2.27 : vérifié via `inspect_activation()` --
                # NON MUTANTE -- plutôt que `validate_activation()`
                # directement, pour que la couche P2.26 ci-dessous
                # (qui ré-inspecte elle-même ce même contrat P2.21)
                # le trouve encore fraîchement valide. La consommation
                # définitive du contrat P2.21 est différée après TOUTE
                # vérification (cf. `self.activation_service.consume()`
                # juste avant `create_job()` ci-dessous) -- comportement
                # observable STRICTEMENT identique à avant P2.27 pour
                # tout appelant qui ne fournit pas de
                # `provider_activation_contract` : la même vérification
                # (`_activation_violations()`) est exécutée, puis le
                # contrat est consommé avant `create_job()`, exactement
                # comme le faisait `validate_activation()` seule.
                activation_violations = self.activation_service.inspect_activation(
                    request, activation_contract
                )
                if activation_violations:
                    raise GenerationJobActivationRejectedError(
                        f"Cannot execute job for request "
                        f"'{request.request_id}': activation contract "
                        f"'{activation_contract.activation_id}' was "
                        f"rejected. Reasons: "
                        f"{'; '.join(activation_violations) or 'none provided'}",
                        approval=approval,
                        activation_rejection=ActivationRejectedError(
                            f"Cannot validate activation contract "
                            f"'{activation_contract.activation_id}' for "
                            f"request '{request.request_id}'.",
                            activation_violations,
                        ),
                    )

            if provider_activation_contract is not None:
                try:
                    self.provider_activation_service.validate(
                        request, activation_contract, provider_activation_contract
                    )
                except ControlledRealProviderActivationRejectedError as provider_activation_error:
                    raise GenerationJobProviderActivationRejectedError(
                        f"Cannot execute job for request "
                        f"'{request.request_id}': controlled "
                        f"real-provider activation contract "
                        f"'{provider_activation_contract.activation_id}' "
                        f"was rejected. Reasons: "
                        f"{'; '.join(provider_activation_error.reasons) or 'none provided'}",
                        approval=approval,
                        provider_activation_rejection=provider_activation_error,
                    ) from provider_activation_error

            # Consommation définitive du contrat P2.21 -- APRÈS que la
            # couche P2.26 (si présente) a également validé avec
            # succès, jamais avant (cf. commentaire ci-dessus).
            if activation_contract is not None:
                self.activation_service.consume(activation_contract)

            job_params = {
                key: value
                for key, value in {
                    "duration": request.duration,
                    "resolution": request.resolution,
                    "aspect_ratio": request.aspect_ratio,
                }.items()
                if value is not None
            }

            # Phase P2.32 : `provider_activation_contract` (P2.26),
            # s'il a été fourni ET validé ci-dessus, est désormais
            # transmis EXPLICITEMENT au Provider -- jamais deviné,
            # jamais construit ici. `None` (cas de TOUT chemin de
            # production actuel : director.py ne fournit jamais ce
            # contrat aujourd'hui) préserve un comportement strictement
            # identique à avant P2.32.
            #
            # Phase P2.35 : `request_id`/`avatar_sha256`/`face_reference_
            # sha256` sont désormais ÉGALEMENT transmis explicitement --
            # calculés ICI, EN DIRECT, depuis la `GenerationRequest`
            # RÉELLEMENT évaluée par ce `execute()` (jamais mis en
            # cache, jamais réutilisés d'un appel précédent) -- afin que
            # le Provider puisse comparer ces valeurs LIVE à celles
            # portées par `provider_activation_contract`, comme une
            # couche de vérification supplémentaire et INDÉPENDANTE à sa
            # propre frontière (cf. integrations/higgsfield/provider.py).
            # Le Provider réel (HiggsfieldProvider.create_job()) reste
            # néanmoins INCONDITIONNELLEMENT bloqué -- ce transfert
            # prépare uniquement l'interface pour une future phase
            # explicitement autorisée.
            # Phase P3.91 (RISK #1 de P3.90) : write-ahead DURABLE avant
            # `create_job()`. Tant que `mark_executed()` ne l'a pas
            # remplacé (même écriture atomique), ce marqueur est lu comme
            # EXECUTION_STATE_UNKNOWN : un crash dur, un KeyboardInterrupt
            # ou une exception de `create_job()` après acceptation côté
            # backend laissent une trace BLOQUANTE, jamais une absence de
            # trace. S'il ne peut pas être écrit, `create_job()` n'est
            # jamais appelé.
            # Seul `HiggsfieldRealGenerationDisabledError` (refus du
            # Provider AVANT tout appel client) annule CE marqueur ; toute
            # autre sortie par exception laisse la requête UNKNOWN.
            # Phase B : consommation DÉFINITIVE de l'autorisation approuvée
            # ci-dessus, dans le registre séparé (jamais executed_requests
            # .json, invariant P3.89), AVANT le marqueur et `create_job()`.
            # Pas de transaction commune : un arrêt entre cette écriture et
            # le marqueur brûle l'autorisation sans exécution (échec
            # fermé). Identifiant invalide, déjà consommé, registre
            # absent/illisible/verrouillé, écriture impossible :
            # exception ici, `create_job()` n'est jamais appelé.
            self.gate.consume_authorization(
                request.request_id,
                getattr(request.real_generation_authorization, "authorization_id", None),
            )
            with self.gate.in_flight(request.request_id):
                job = self.provider.create_job(
                    job_type=request.job_type,
                    prompt=request.prompt,
                    provider_activation_contract=provider_activation_contract,
                    request_id=request.request_id,
                    avatar_sha256=_sha256_of_file_or_none(
                        request.start_image.source if request.start_image else None
                    ),
                    face_reference_sha256=_face_reference_sha256_or_none(request),
                    **job_params,
                )

            # Marqué exécuté immédiatement après création — avant même
            # le polling — car c'est la CRÉATION du job qui ne doit
            # jamais être dupliquée, indépendamment de l'issue du
            # polling. Phase P2.20 : si CET enregistrement échoue,
            # create_job() a déjà réussi -- l'état est désormais
            # ambigu et ne doit jamais être traité en silence.
            # Phase P3.89 (GAP #1) : `job.job_id` est persisté DANS le
            # même enregistrement anti-rejeu, pour que le job créé reste
            # retrouvable localement après un crash pendant le polling.
            try:
                self.gate.mark_executed(request.request_id, job_id=job.job_id)
            except Exception as mark_executed_error:
                try:
                    self.gate.mark_unknown(
                        request.request_id,
                        reason=(
                            f"create_job() succeeded (job_id="
                            f"{job.job_id!r}) but mark_executed() failed: "
                            f"{mark_executed_error}"
                        ),
                        job_id=job.job_id,
                    )
                except Exception as mark_unknown_error:
                    raise CriticalStateUnknownAndUnrecordedError(
                        f"Request '{request.request_id}': create_job() "
                        f"succeeded (job_id={job.job_id!r}) but BOTH "
                        f"mark_executed() and mark_unknown() failed. "
                        f"mark_executed error: {mark_executed_error}; "
                        f"mark_unknown error: {mark_unknown_error}. "
                        f"Manual review required immediately."
                    ) from mark_unknown_error

                raise GenerationJobUnknownStateError(
                    f"Request '{request.request_id}': create_job() "
                    f"succeeded (job_id={job.job_id!r}) but "
                    f"mark_executed() failed ({mark_executed_error}); "
                    f"state recorded as UNKNOWN (EXECUTION_STATE_UNKNOWN). "
                    f"Manual review required before any further action.",
                    job=job,
                ) from mark_executed_error

        result = self.provider.wait_for_job(
            job.job_id,
            timeout_seconds=timeout_seconds,
            interval_seconds=interval_seconds,
        )

        return GenerationJobOutcome(
            request_id=request.request_id,
            job_type=request.job_type,
            approval=approval,
            job=job,
            result=result,
        )
