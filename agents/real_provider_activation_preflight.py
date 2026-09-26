"""
AI DIRECTOR — Real Provider Activation Preflight (Phase P2.37, MASTER PROMPT V2)

Répond, de façon déterministe et PUREMENT EN LECTURE, à UNE question,
plus large que celle de `agents/real_provider_execution_gate.py`
(Phase P2.36) mais tout aussi non-exécutante :

    « Si une phase future devait ouvrir le Provider réel, quelles
      conditions sont déjà satisfaites, lesquelles restent
      bloquantes, et le dernier verrou lui-même est-il toujours en
      place, RÉELLEMENT vérifié plutôt que supposé ? »

Ce module NE RÉPOND PAS à « puis-je lancer maintenant la génération ? »
-- aucune méthode ici ne peut, directement ou indirectement, mener à
`provider.create_job()` avec le vrai Provider.

STOP -- CE QUE CE MODULE N'EST PAS :
- N'APPELLE JAMAIS `create_job()`, ni sur le Provider réel, ni sur un
  Mock, ni sur quelque instance que ce soit -- AUCUN appel, direct ou
  indirect. La vérification du dernier verrou (`HiggsfieldProvider.
  create_job()` reste-t-il inconditionnellement bloqué ?) est
  effectuée PAR ANALYSE STATIQUE (AST) du fichier source réel de
  `integrations/higgsfield/provider.py`, JAMAIS par invocation -- Phase
  P2.37 s'interdit explicitement d'ajouter un second call-site de
  production, même pour un usage de sonde de sécurité interne à ce
  module (cf. `_probe_real_provider_execution_path()` ci-dessous).
- NE CONSTRUIT JAMAIS de `RealGenerationAuthorization`,
  `RequestScopedActivationContract`, ni
  `ControlledRealProviderActivationContract`.
- NE CONSOMME JAMAIS un contrat (délègue entièrement à
  `RealProviderExecutionGate`, Phase P2.36, qui lui-même ne consomme
  jamais rien).
- N'importe ni HiggsfieldClient, ni subprocess, et ne construit jamais
  de VRAI client.

COMPOSITION, JAMAIS DUPLICATION (Étape 1/8, rapport P2.37) :
Ce module RÉUTILISE, tel quel, sans aucune modification :
- `RealProviderExecutionGate` (Phase P2.36) pour les onze dimensions
  de readiness/activation ;
- `agents.production_activation_boundary.FORBIDDEN_GLOBAL_AUTHORITY_
  TOKENS` (Phase P2.25) comme SEULE liste de tokens interdits -- jamais
  une seconde liste divergente ;
- `agents.release_candidate_identity_lock.VIDEO_005_RELEASE_CANDIDATE`
  (Phase P2.18) comme snapshot canonique déjà existant -- AUCUN nouveau
  "parameter snapshot" n'est créé ici (Étape 16, rapport P2.37) : ce
  contrat gelé, déjà immuable/informatif/non-autoritaire (l'Identity
  Lock recalcule toujours depuis les fichiers réels), suffit déjà.

ONE-SHOT AUTHORIZATION (Étape 8, rapport P2.37) : AUCUNE nouvelle
abstraction n'est introduite. La composition déjà existante --
`RealGenerationAuthorization` (P2.11, request-scoped, jamais dérivée
de `approved`) + `RequestScopedActivationContract` (P2.21, single-use,
expirant, en mémoire uniquement) + `ControlledRealProviderActivation
Contract` (P2.26, single-use, expirant, révocable, lié request-scoped
au P2.21 dont il découle) -- satisfait DÉJÀ chacune des propriétés
requises (unique, request-scoped, non persistante, courte durée, non
transférable, non réutilisable, jamais dérivée de `approved`).
Construire un second objet dupliquerait une garantie déjà apportée par
trois couches indépendantes.
"""

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import (
    RequestScopedActivationContract,
    RequestScopedActivationService,
)
from agents.controlled_real_provider_activation import (
    ControlledRealProviderActivationContract,
    ControlledRealProviderActivationService,
)
from agents.generation_approval_gate import GenerationApprovalGate, GenerationRequest
from agents.generation_job_service import GenerationJobService
from agents.production_activation_boundary import FORBIDDEN_GLOBAL_AUTHORITY_TOKENS
from agents.real_provider_execution_gate import (
    RealProviderExecutionDecision,
    RealProviderExecutionGate,
    RealProviderExecutionGateReport,
)
from agents.release_candidate_identity_lock import ReleaseCandidateIdentityLock

_SCAN_DIRS = ("agents", "integrations", "scripts")
_SCAN_EXTRA_FILES = ("director.py",)
_SECURITY_SCAN_EXCLUDED = {"agents/production_activation_boundary.py"}


def _probe_real_provider_execution_path() -> "tuple[bool, str]":
    """
    Vérification STRUCTURELLE, PAR AST -- délibérément PAS une
    invocation de `create_job()` (Phase P2.37 s'interdit explicitement
    d'ajouter un second call-site de production : l'invariant
    "exactement un production call-site", vérifié par de nombreux
    tests à travers tout le projet depuis P2.24, ne doit JAMAIS être
    élargi, pas même pour un usage de sonde interne à ce module).

    Relit le FICHIER SOURCE RÉEL à chaque appel (jamais une valeur
    mise en cache ou codée en dur) et confirme, par analyse AST du
    corps de `HiggsfieldProvider.create_job()`
    (integrations/higgsfield/provider.py), les trois mêmes garanties
    déjà vérifiées indépendamment par tests/test_phase_p2_29_*.py et
    tests/test_phase_p2_32_*.py (non modifiés par cette phase) :
    - le dernier statement du corps est un `raise` (pas de retour
      normal possible) ;
    - aucun `Return` n'existe nulle part dans la méthode ;
    - `self.client` n'est référencé nulle part dans la méthode (le
      seul chemin vers un appel réseau/CLI réel est donc inatteignable).

    Retourne `(execution_path_open, reason)` : `(False, ...)`
    UNIQUEMENT si les trois garanties tiennent simultanément -- FAIL
    CLOSED côté RAPPORT dans tout autre cas (méthode introuvable,
    dernier statement différent, un Return détecté, ou une référence à
    `self.client` détectée) : ce module préfère signaler un chemin
    potentiellement ouvert plutôt que de proclamer à tort une
    fermeture qu'il n'a pas pu confirmer.
    """

    provider_path = PROJECT_ROOT / "integrations" / "higgsfield" / "provider.py"
    text = provider_path.read_text(encoding="utf-8-sig")
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

    if real_create_job is None:
        return (
            True,
            "HiggsfieldProvider.create_job() no longer contains an "
            "unconditional raise at the top level of its body -- "
            "cannot confirm the execution path is closed.",
        )

    if not isinstance(real_create_job.body[-1], ast.Raise):
        return (
            True,
            "HiggsfieldProvider.create_job()'s last top-level statement "
            "is not a raise -- a normal return path may exist.",
        )

    returns = [n for n in ast.walk(real_create_job) if isinstance(n, ast.Return)]
    if returns:
        return (
            True,
            f"HiggsfieldProvider.create_job() contains {len(returns)} "
            f"Return statement(s) -- cannot confirm the execution path "
            f"is closed.",
        )

    client_refs = [
        n
        for n in ast.walk(real_create_job)
        if isinstance(n, ast.Attribute)
        and n.attr == "client"
        and isinstance(n.value, ast.Name)
        and n.value.id == "self"
    ]
    if client_refs:
        return (
            True,
            f"HiggsfieldProvider.create_job() references self.client "
            f"{len(client_refs)} time(s) -- cannot confirm the "
            f"execution path is closed.",
        )

    return (
        False,
        "HiggsfieldProvider.create_job()'s AST confirms: the last "
        "top-level statement unconditionally raises, zero Return "
        "statements exist, and self.client is never referenced "
        "anywhere in the method.",
    )


def _scan_for_forbidden_global_authority_tokens() -> List[str]:
    """
    Phase P2.37 — réutilise EXCLUSIVEMENT la liste canonique déjà
    définie en Phase P2.25 (`agents.production_activation_boundary.
    FORBIDDEN_GLOBAL_AUTHORITY_TOKENS`) -- jamais une seconde liste. Un
    token qui n'est pas un identifiant Python valide (par exemple une
    affectation littérale complète plutôt qu'un simple nom) est
    recherché comme sous-chaîne ; un token identifiant pur est
    recherché avec des limites de mot (jamais de faux positif sur un
    identifiant plus long qui le contiendrait). Ce docstring évite
    délibérément de recopier un token interdit tel quel, pour ne pas
    se déclencher lui-même lors du scan."""

    offenders: List[str] = []

    def _scan_text(rel_path: str, text: str) -> None:
        for token in FORBIDDEN_GLOBAL_AUTHORITY_TOKENS:
            if token.isidentifier():
                found = re.search(r"\b" + re.escape(token) + r"\b", text) is not None
            else:
                found = token in text
            if found:
                offenders.append(f"{rel_path}:{token}")

    for base in _SCAN_DIRS:
        base_dir = PROJECT_ROOT / base
        if not base_dir.exists():
            continue
        for path in base_dir.rglob("*.py"):
            rel = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
            if rel in _SECURITY_SCAN_EXCLUDED:
                continue
            _scan_text(rel, path.read_text(encoding="utf-8-sig"))

    for extra in _SCAN_EXTRA_FILES:
        path = PROJECT_ROOT / extra
        if path.exists():
            _scan_text(extra, path.read_text(encoding="utf-8-sig"))

    return offenders


@dataclass(frozen=True)
class ActivationPreflightReport:
    """
    Photographie du preflight pour UNE requête, à UN instant précis.
    Rien n'est mis en cache au-delà de cet objet : un nouvel appel à
    `ActivationPreflightEvaluator.evaluate()` relit tout depuis zéro,
    y compris la sonde comportementale du Provider et le scan de
    sécurité -- jamais des valeurs figées d'un run précédent.
    """

    request_id: str
    execution_gate: RealProviderExecutionGateReport

    technically_ready: bool
    preflight_ready: bool
    budget_ready: bool
    human_authorized: bool

    real_provider_execution_path_open: bool
    real_provider_execution_path_reason: str

    forbidden_token_offenders: List[str] = field(default_factory=list)

    # Faits STRUCTURELS et PERMANENTS de cette phase du projet --
    # jamais dérivés du Gate (qui répond à une question différente :
    # "cette requête précise qualifierait-elle", pas "le dernier
    # verrou lui-même a-t-il été retiré du code"). `real_provider_
    # enabled` est calculé depuis `forbidden_token_offenders` ci-dessus
    # (jamais codé en dur) ; `real_generation_executed` reste toujours
    # `False` PAR CONSTRUCTION -- ce module ne contient, structurellement,
    # aucun chemin de code qui pourrait jamais le rendre vrai (vérifié
    # par AST, cf. tests/test_phase_p2_37_*.py).
    real_generation_executed: bool = False

    @property
    def real_provider_enabled(self) -> bool:
        return len(self.forbidden_token_offenders) > 0

    @property
    def decision(self) -> RealProviderExecutionDecision:
        """Relais direct de la décision du Gate (Phase P2.36) -- ce
        module n'invente jamais une décision différente."""

        return self.execution_gate.decision

    @property
    def all_reasons(self) -> List[str]:
        reasons = list(self.execution_gate.all_reasons)
        if self.forbidden_token_offenders:
            reasons.append(
                f"Forbidden global-authority tokens found: "
                f"{', '.join(self.forbidden_token_offenders)}."
            )
        if self.real_provider_execution_path_open:
            reasons.append(
                f"Real provider execution path probe: "
                f"{self.real_provider_execution_path_reason}"
            )
        return reasons


class ActivationPreflightEvaluator:
    """
    AI DIRECTOR — Real Provider Activation Preflight Evaluator (Phase P2.37)

    Compose EXCLUSIVEMENT `RealProviderExecutionGate` (Phase P2.36,
    RÉUTILISÉ tel quel) + deux vérifications structurelles
    supplémentaires (sonde comportementale du Provider, scan de
    sécurité) -- aucune logique de décision métier n'est dupliquée ici.
    """

    def __init__(
        self,
        gate: GenerationApprovalGate,
        identity_lock: ReleaseCandidateIdentityLock,
        activation_service: RequestScopedActivationService,
        provider_activation_service: ControlledRealProviderActivationService,
        job_service: Optional[GenerationJobService] = None,
    ):
        self.execution_gate = RealProviderExecutionGate(
            gate,
            identity_lock,
            activation_service,
            provider_activation_service,
            job_service=job_service,
        )

    def evaluate(
        self,
        request: GenerationRequest,
        activation_contract: Optional[RequestScopedActivationContract] = None,
        provider_activation_contract: Optional[ControlledRealProviderActivationContract] = None,
    ) -> ActivationPreflightReport:
        """
        Évalue le preflight complet pour `request` à cet instant
        précis. N'appelle jamais `create_job()` sur le Provider RÉEL de
        `request` (seule la sonde interne, contre un Provider jetable
        avec client inerte, touche `create_job()`). Ne construit
        jamais d'autorisation ni de contrat, ne consomme jamais rien.
        """

        egr = self.execution_gate.evaluate(
            request,
            activation_contract=activation_contract,
            provider_activation_contract=provider_activation_contract,
        )
        r = egr.readiness

        # "preflight_ready" -- tout ce qui NE dépend PAS de l'argent ou
        # d'une décision humaine encore à venir : le mécanisme
        # lui-même fonctionnerait-il si l'autorisation/le budget
        # arrivaient ? Exclut délibérément budget_ready/authorization_
        # ready/activation_ready/provider_activation_ready/provider_
        # ready -- ces cinq dimensions dépendent de faits externes
        # (solde réel, décision humaine, contrats pas encore préparés)
        # qui restent LÉGITIMEMENT non satisfaits aujourd'hui, sans
        # que cela ne signifie que le MÉCANISME soit défaillant.
        preflight_ready = all(
            (
                r.technical_ready,
                r.request_identity_ready,
                r.prompt_ready,
                r.asset_ready,
                r.replay_safe,
                r.crash_safe,
            )
        )

        path_open, path_reason = _probe_real_provider_execution_path()
        forbidden_offenders = _scan_for_forbidden_global_authority_tokens()

        return ActivationPreflightReport(
            request_id=request.request_id,
            execution_gate=egr,
            technically_ready=r.technical_ready,
            preflight_ready=preflight_ready,
            budget_ready=r.budget_ready,
            human_authorized=r.authorization_ready,
            real_provider_execution_path_open=path_open,
            real_provider_execution_path_reason=path_reason,
            forbidden_token_offenders=forbidden_offenders,
            real_generation_executed=False,
        )
