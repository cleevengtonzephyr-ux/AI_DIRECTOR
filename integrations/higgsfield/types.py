"""
AI DIRECTOR — Higgsfield Provider Types (Phase B, MASTER PROMPT V2)

Contrats typés pour la couche Provider Higgsfield.

Ces types décrivent la réponse BRUTE du Provider (réel ou Mock) — ils
ne dupliquent pas `agents.cost_engine.CostEstimate`, qui reste un
résultat d'évaluation MÉTIER (plan vidéo + budget disponible + décision
APPROVED/BLOCKED) propre à l'architecture V1. Le `CostEstimate` défini
ici est plus bas niveau : il représente simplement ce que le Provider
répond pour un job_type/prompt donné, sans connaître la notion de plan
ou de budget. `agents.cost_engine.CostEngine` pourra, dans une phase
ultérieure, consommer ce type au lieu d'appeler le CLI directement —
mais ce changement n'est PAS fait ici (hors périmètre de cette phase).

Convention de nommage : le dépôt est intégralement en Python (aucune
trace de TypeScript). Les noms de méthodes du Provider suivent donc le
style snake_case déjà utilisé par HiggsfieldClient (list_workflows,
get_workflow, account_status, estimate_cost) plutôt que le camelCase
du MASTER PROMPT V2 (estimateCost, createJob, getJob, waitForJob,
listModels), afin de rester cohérent avec le reste du code :

    MASTER PROMPT V2      →  Provider (ce dépôt)
    estimateCost()        →  estimate_cost()
    createJob()           →  create_job()
    getJob()               →  get_job()
    waitForJob()           →  wait_for_job()
    listModels()           →  list_models()

Ce module ne contient que des définitions de données (dataclasses/enum)
— aucune logique métier, aucun appel réseau ou CLI.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class JobStatus(str, Enum):
    """États réels d'un job de génération Higgsfield (CLI `generate get`/`wait`)."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    UNKNOWN = "unknown"

    @property
    def is_terminal(self) -> bool:
        return self in (
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELED,
        )


@dataclass(frozen=True)
class ModelParam:
    """Un paramètre accepté par un modèle/workflow Higgsfield."""

    name: str
    type: str
    required: bool
    default: Any = None
    enum: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ModelSchema:
    """Schéma d'un modèle Higgsfield (sortie de `model get <job_type>`)."""

    job_type: str
    display_name: str
    params: Tuple[ModelParam, ...] = field(default_factory=tuple)
    raw: Dict[str, Any] = field(default_factory=dict)

    def param(self, name: str) -> Optional[ModelParam]:
        return next((p for p in self.params if p.name == name), None)


@dataclass(frozen=True)
class CostEstimate:
    """
    Réponse brute du Provider pour une estimation de coût.

    `credits` est `None` (et non 0.0) lorsque le CLI n'a renvoyé aucune
    valeur exploitable — RIEN n'est jamais inventé ici (Phase F,
    MASTER PROMPT V2 : ne jamais hardcoder/inventer un prix). Un coût
    de 0.0 explicite (renvoyé tel quel par le CLI) reste distinct d'un
    coût manquant (`None`).
    """

    job_type: str
    credits: Optional[float]
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MediaReference:
    """
    Référence média (image) à joindre à une génération (Phase P1.1).

    `source` est un chemin de fichier local — traçable jusqu'à
    l'asset validé par AssetPreparationSystem — jamais une URL/UUID
    Higgsfield déjà uploadée : ce type ne représente AUCUN upload
    réel, il ne fait que porter la référence jusqu'au Provider. Le CLI
    accepte nativement un chemin local pour ces champs (auto-upload
    interne à `generate create`, jamais appelé dans ces phases).

    `sha256`, quand fourni, provient tel quel d'AssetPreparationSystem
    (jamais recalculé ici) et permet de vérifier que la référence
    correspond bien au fichier attendu.
    """

    role: str
    source: str
    sha256: Optional[str] = None


@dataclass(frozen=True)
class JobRequest:
    """Requête de création de job, avant envoi au Provider."""

    job_type: str
    prompt: str
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Job:
    """Représentation d'un job Higgsfield (créé, en cours, ou terminé)."""

    job_id: str
    job_type: str
    status: JobStatus
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VideoResult:
    """Résultat final d'un job vidéo Higgsfield, après polling."""

    job_id: str
    status: JobStatus
    output_urls: Tuple[str, ...] = field(default_factory=tuple)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status == JobStatus.SUCCEEDED
