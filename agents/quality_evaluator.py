"""
AI DIRECTOR — Quality Evaluator v0.1 (Phase I, MASTER PROMPT V2)

Couche "QUALITY EVALUATOR" du pipeline :

    ... -> REAL HIGGSFIELD JOB -> WAIT/POLL -> RESULT -> QUALITY EVALUATOR -> FINAL REPORT

Ce composant évalue le RÉSULTAT d'une exécution (GenerationJobOutcome,
Phase H) sans jamais avoir besoin d'un fichier vidéo réel : puisque
aucune génération réelle n'est autorisée pendant cette phase du
projet, l'évaluation porte sur la COHÉRENCE DU RÉSULTAT DU PIPELINE
(statut terminal du job, présence d'une sortie) — jamais sur un
contenu vidéo qui n'existe pas et ne doit pas être inventé.

RELATION AVEC agents/qa_engine.py (V1) — IMPORTANT :

`QAEngine` (V1) reste la référence pour la validation D'UN FICHIER
VIDÉO RÉEL déjà téléchargé (extension, taille, durée, ratio,
résolution, intégrité). Cette responsabilité N'EST PAS dupliquée ici
et `QAEngine` n'est PAS modifié par cette phase.

`QualityEvaluator` couvre la couche immédiatement en amont, qui
n'existe pas encore dans le projet : "le pipeline a-t-il produit un
résultat cohérent ?", évaluable dès maintenant à partir du seul
VideoResult typé (Phase B), avant même qu'un fichier existe. Une fois
qu'une vraie génération sera autorisée (hors périmètre actuel),
`QAEngine` prendra le relais sur le fichier réellement obtenu ; les
deux composants partagent le même vocabulaire de décision (PASS/FAIL,
retry recommandé) déjà établi par QAEngine v1, sans dupliquer sa
logique de vérification de fichier.

SÉCURITÉ :
Ce module n'appelle jamais create_job(), n'importe ni
HiggsfieldClient, ni subprocess. Il ne fait aucun appel réseau : toute
l'information provient du GenerationJobOutcome déjà produit par le
pipeline (Phase H).
"""

import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.generation_job_service import GenerationJobOutcome
from integrations.higgsfield.types import JobStatus


class QualityDecision(str, Enum):
    """Vocabulaire de décision réutilisé de QAEngine v1 (PASS/FAIL),
    complété par RETRY_RECOMMENDED pour un job non terminal (timeout)."""

    PASS = "PASS"
    FAIL = "FAIL"
    RETRY_RECOMMENDED = "RETRY_RECOMMENDED"


@dataclass(frozen=True)
class QualityEvaluationResult:
    """Décision typée — ne contient aucune métadonnée vidéo inventée."""

    decision: QualityDecision
    request_id: str
    job_id: str
    reasons: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.decision == QualityDecision.PASS


class QualityEvaluator:
    """
    AI DIRECTOR — Quality Evaluator v0.1 (Phase I)

    Évalue un GenerationJobOutcome (Phase H). Ne nécessite aucun accès
    réseau, fichier ou CLI.
    """

    def evaluate(self, outcome: GenerationJobOutcome) -> QualityEvaluationResult:
        result = outcome.result

        if not result.status.is_terminal:
            return QualityEvaluationResult(
                decision=QualityDecision.RETRY_RECOMMENDED,
                request_id=outcome.request_id,
                job_id=outcome.job.job_id,
                reasons=[
                    f"Job did not reach a terminal state (status="
                    f"{result.status.value}); retry recommended."
                ],
            )

        if result.status != JobStatus.SUCCEEDED:
            return QualityEvaluationResult(
                decision=QualityDecision.FAIL,
                request_id=outcome.request_id,
                job_id=outcome.job.job_id,
                reasons=[f"Job ended with status '{result.status.value}'."],
            )

        if not result.output_urls:
            return QualityEvaluationResult(
                decision=QualityDecision.FAIL,
                request_id=outcome.request_id,
                job_id=outcome.job.job_id,
                reasons=[
                    "Job reported SUCCEEDED but no output URL was provided "
                    "— inconsistent result, treated as a failure."
                ],
            )

        return QualityEvaluationResult(
            decision=QualityDecision.PASS,
            request_id=outcome.request_id,
            job_id=outcome.job.job_id,
            reasons=[
                f"Job succeeded with {len(result.output_urls)} output "
                f"URL(s)."
            ],
        )
