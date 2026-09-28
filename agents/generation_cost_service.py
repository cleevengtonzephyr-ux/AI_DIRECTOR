"""
AI DIRECTOR — Generation Cost Service v0.1 (Phase F, MASTER PROMPT V2)

Couche responsable de l'ESTIMATION du coût d'une génération vidéo AVANT
toute création de job, en s'appuyant exclusivement sur un
BaseHiggsfieldProvider injecté — jamais directement sur HiggsfieldClient
ni sur le CLI Higgsfield.

Architecture (MASTER PROMPT V2) :

    Video request
         v
    GenerationCostService
         v
    HiggsfieldProvider.estimate_cost()
         v
    CostEstimate (integrations.higgsfield.types)

Ce service ne connaît AUCUN détail du CLI : il ne fait qu'appeler
`provider.estimate_cost(...)` et traduire le résultat (ou l'erreur) en
un GenerationCostResult typé à 3 états : KNOWN / UNKNOWN / ERROR.

RELATION AVEC agents/cost_engine.py (V1) — IMPORTANT :

`CostEngine` (V1) n'est plus sur le chemin de production actif : ses
appelants (`ProductionGate`, `production_controller.py`) sont, comme
lui, des modules V1 orphelins jamais atteints depuis director.py
(tests/test_v1_orphan_isolation.py). La DÉCISION BUDGÉTAIRE active
(comparaison coût vs solde disponible) est prise par
`GenerationApprovalGate` (agents/generation_approval_gate.py), qui lit
le solde via le Provider. Ce service ne prend aucune décision
budgétaire, et `CostEngine` n'est pas modifié.

`GenerationCostService` distingue explicitement un coût CONNU, un coût
INCONNU (le Provider a répondu sans erreur mais sans valeur
exploitable) et une ERREUR survenue pendant l'estimation — là où
`CostEngine.get_verified_cost()` (V1) confond ces deux derniers cas
dans un même retour `None` (`except Exception: return None`).
`GenerationApprovalGate` consomme aujourd'hui ce résultat typé :
ERROR -> BLOCKED ; UNKNOWN ->
NEEDS_APPROVAL si l'approbation explicite ou l'autorisation humaine
explicite manque, et APPROVED seulement si les deux sont fournies
(jamais d'autorisation silencieuse).

RÈGLE ABSOLUE :
- Aucun prix n'est jamais inventé ou codé en dur ici (délégation
  intégrale à HiggsfieldProvider.estimate_cost()).
- Ce service n'appelle JAMAIS create_job(). Aucune génération réelle
  n'est possible via cette classe.
"""

import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from integrations.higgsfield.errors import HiggsfieldError
from integrations.higgsfield.provider import BaseHiggsfieldProvider
from integrations.higgsfield.types import CostEstimate


class CostEstimationStatus(str, Enum):
    """Les 3 états distincts requis par la Phase F du MASTER PROMPT V2."""

    KNOWN = "known"
    UNKNOWN = "unknown"
    ERROR = "error"


@dataclass(frozen=True)
class GenerationCostResult:
    """
    Résultat typé d'une demande d'estimation de coût.

    - status == KNOWN   : `estimate` est renseigné et
                           `estimate.credits` est un nombre exploitable.
    - status == UNKNOWN : le Provider a répondu SANS lever d'erreur,
                           mais sans coût exploitable (`estimate` peut
                           être renseigné, avec `credits is None`) —
                           aucune valeur n'est inventée.
    - status == ERROR   : l'appel au Provider a échoué ; `error`
                           contient le message de l'exception
                           Higgsfield typée (Phase B/C), `estimate`
                           vaut None.
    """

    status: CostEstimationStatus
    job_type: str
    estimate: Optional[CostEstimate] = None
    message: str = ""
    error: Optional[str] = None

    @property
    def known(self) -> bool:
        return self.status == CostEstimationStatus.KNOWN


class GenerationCostService:
    """
    AI DIRECTOR — Generation Cost Service v0.1 (Phase F)

    Ne connaît RIEN du CLI Higgsfield : toute communication passe par
    un BaseHiggsfieldProvider injecté (HiggsfieldProvider réel ou
    MockHiggsfieldProvider pour les tests/dev hors-ligne).
    """

    def __init__(self, provider: BaseHiggsfieldProvider):
        self.provider = provider

    def estimate(
        self,
        job_type: str,
        prompt: str,
        duration: Optional[int] = None,
        resolution: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
    ) -> GenerationCostResult:
        """
        Demande une estimation de coût au Provider pour les paramètres
        de génération donnés.

        Ne crée JAMAIS de job : cette méthode n'appelle jamais
        `provider.create_job()`, quel que soit le résultat.
        """

        if not job_type:
            return GenerationCostResult(
                status=CostEstimationStatus.ERROR,
                job_type=job_type,
                message="job_type is missing.",
                error="job_type is missing.",
            )

        if not isinstance(prompt, str) or not prompt.strip():
            return GenerationCostResult(
                status=CostEstimationStatus.ERROR,
                job_type=job_type,
                message="Prompt is missing or empty.",
                error="Prompt is missing or empty.",
            )

        try:
            estimate = self.provider.estimate_cost(
                job_type=job_type,
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
            )
        except HiggsfieldError as error:
            return GenerationCostResult(
                status=CostEstimationStatus.ERROR,
                job_type=job_type,
                message="Cost estimation failed.",
                error=str(error),
            )

        if not self._is_usable_cost(estimate.credits):
            return GenerationCostResult(
                status=CostEstimationStatus.UNKNOWN,
                job_type=job_type,
                estimate=estimate,
                message=(
                    "Higgsfield did not return a usable cost for this "
                    "request."
                ),
            )

        return GenerationCostResult(
            status=CostEstimationStatus.KNOWN,
            job_type=job_type,
            estimate=estimate,
            message="Cost estimated successfully.",
        )

    @staticmethod
    def _is_usable_cost(credits: Optional[float]) -> bool:
        return (
            isinstance(credits, (int, float))
            and not isinstance(credits, bool)
            and credits >= 0
        )
