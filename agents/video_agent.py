"""
AI DIRECTOR — Video Agent v0.1 (Phase K, MASTER PROMPT V2)

Traduit un VideoPlan (agents/planner.py, V1) en une GenerationRequest
(agents/generation_approval_gate.py, Phase G) consommable par le
pipeline Provider construit en Phases F-J.

Architecture (MASTER PROMPT V2) :

    VideoPlan (Planner, V1)
         v
    VideoAgent.build_request()
         v
    GenerationRequest
         v
    FinalReportService.generate()   (Phase J, fourni par l'appelant)

RELATION AVEC L'EXISTANT — IMPORTANT :

- Ne duplique PAS l'assemblage de prompt : réutilise
  PromptAssemblySystem (V1, déjà éprouvé) pour obtenir le Master
  Prompt d'un video_id, au lieu de reconstruire une concaténation de
  scènes — c'est exactement le défaut qu'avait
  HiggsfieldExecutor.build_request() (champ scene.visual inexistant),
  jamais corrigé et toujours hors périmètre des Phases B-J.

- Ne lit JAMAIS `plan.workflow` (identifiant de WORKFLOW V1, ex.
  "cinematic_studio_video_4_0") comme job_type. Le MASTER PROMPT V2
  exige des modèles interchangeables, avec "seedance_2_0" par défaut
  (vérifié réel en Phase A comme MODÈLE Higgsfield, pas WORKFLOW).
  `job_type` reste un paramètre explicite de build_request(), jamais
  déduit du plan V1 — les deux architectures (workflow V1 / modèle V2)
  restent volontairement découplées.

- Réutilise la même logique d'extraction resolution/aspect_ratio
  depuis la première scène que agents/cost_engine.py
  (CostEngine.evaluate_plan()), sans dupliquer son code, en restant
  cohérent avec elle.

SÉCURITÉ :
- build_request() ne crée, n'estime ni n'approuve AUCUN job : elle
  produit uniquement une GenerationRequest, avec `approved=False`
  par défaut (jamais déduit automatiquement d'un plan).
- run() est une simple composition (build_request +
  report_service.generate()) : elle n'appelle jamais create_job()
  directement et n'introduit aucune nouvelle voie d'exécution — toute
  la sécurité (CostService/ApprovalGate/protection réelle) reste
  entièrement dans FinalReportService/GenerationJobService (Phases
  F-J), non modifiés par cette phase.
- N'importe ni HiggsfieldClient, ni subprocess.

RÉFÉRENCES VISUELLES (Phase P1.1) :
Si un AssetPreparationSystem est fourni, build_request() y puise les
assets READY pour peupler start_image/image_references :
- rôle "master_avatar"   -> start_image (référence d'identité unique)
- rôle "face_reference"  -> image_references
Le système AUDIO n'est jamais touché dans cette phase (rôle
"main_voice"/"background_music" toujours ignorés ici). Aucun autre
rôle (ex. "brand_logo") n'est transmis automatiquement — seuls les
fichiers explicitement nécessaires à l'identité Zephyr le sont. Aucun
upload réel n'a lieu ici : `MediaReference.source` reste un chemin de
fichier local, traçable par son sha256 (calculé par
AssetPreparationSystem, jamais recalculé ici).
"""

import sys
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.asset_preparation_system import AssetPreparationSystem
from agents.final_report_service import FinalReport, FinalReportService
from agents.generation_approval_gate import GenerationRequest, RealGenerationAuthorization
from agents.planner import VideoPlan
from agents.production_model import PRODUCTION_MODEL
from agents.prompt_assembly_system import PromptAssemblySystem
from integrations.higgsfield.types import MediaReference

# Source unique de vérité (Phase P2.2) : agents/production_model.py.
DEFAULT_JOB_TYPE = PRODUCTION_MODEL
DEFAULT_RESOLUTION = "720p"
DEFAULT_ASPECT_RATIO = "9:16"

# Rôles AssetPreparationSystem transmis automatiquement en références
# visuelles — jamais le rôle audio ("main_voice"), non touché en P1.1.
START_IMAGE_ROLE = "master_avatar"
IMAGE_REFERENCE_ROLES = ("face_reference",)


class VideoAgent:
    """
    AI DIRECTOR — Video Agent v0.1 (Phase K)

    Ne connaît aucun détail du CLI Higgsfield ni du Provider : il ne
    produit que des GenerationRequest, à charge de l'appelant de les
    soumettre à un FinalReportService (Phase J).
    """

    def __init__(
        self,
        prompt_assembly: Optional[PromptAssemblySystem] = None,
        asset_preparation: Optional[AssetPreparationSystem] = None,
    ):
        self.prompt_assembly = prompt_assembly
        self.asset_preparation = asset_preparation

    def _resolve_media_references(self):
        """
        Puise dans AssetPreparationSystem les assets READY à joindre.

        Ne renvoie QUE ce qui est explicitement nécessaire à
        l'identité Zephyr (master_avatar -> start_image,
        face_reference -> image_references) ; jamais le système audio ;
        jamais un asset non READY.
        """

        start_image: Optional[MediaReference] = None
        image_references: List[MediaReference] = []

        if self.asset_preparation is None:
            return start_image, image_references

        for asset in self.asset_preparation.scan():

            if asset.status != "READY":
                continue

            if asset.role == START_IMAGE_ROLE:
                start_image = MediaReference(
                    role=asset.role,
                    source=asset.path,
                    sha256=asset.sha256,
                )

            elif asset.role in IMAGE_REFERENCE_ROLES:
                image_references.append(
                    MediaReference(
                        role=asset.role,
                        source=asset.path,
                        sha256=asset.sha256,
                    )
                )

        return start_image, image_references

    def build_request(
        self,
        plan: VideoPlan,
        prompt: Optional[str] = None,
        job_type: str = DEFAULT_JOB_TYPE,
        approved: bool = False,
        request_id: Optional[str] = None,
        real_generation_authorization: Optional[RealGenerationAuthorization] = None,
    ) -> GenerationRequest:
        """
        Construit une GenerationRequest à partir d'un VideoPlan.

        `prompt`, si non fourni, est obtenu via PromptAssemblySystem
        (réutilisation V1) — jamais reconstruit par concaténation de
        scènes ici. Les références visuelles (start_image/
        image_references) sont puisées dans AssetPreparationSystem si
        configuré (Phase P1.1) — jamais inventées.

        `real_generation_authorization` (Phase P2.11) reste `None` par
        défaut : simple relais explicite vers `GenerationRequest`,
        jamais déduit d'`approved` ni construit automatiquement ici.
        """

        resolved_prompt = prompt

        if resolved_prompt is None:
            if self.prompt_assembly is None:
                raise ValueError(
                    "No prompt provided and no PromptAssemblySystem "
                    "configured on this VideoAgent."
                )
            resolved_prompt = self.prompt_assembly.assemble(plan.video_id)

        scenes = getattr(plan, "scenes", [])

        resolution = (
            getattr(scenes[0], "resolution", DEFAULT_RESOLUTION)
            if scenes
            else DEFAULT_RESOLUTION
        )
        aspect_ratio = (
            getattr(scenes[0], "aspect_ratio", DEFAULT_ASPECT_RATIO)
            if scenes
            else DEFAULT_ASPECT_RATIO
        )

        start_image, image_references = self._resolve_media_references()

        return GenerationRequest(
            request_id=request_id or plan.video_id,
            job_type=job_type,
            prompt=resolved_prompt,
            duration=getattr(plan, "duration", None),
            resolution=resolution,
            aspect_ratio=aspect_ratio,
            approved=approved,
            start_image=start_image,
            image_references=tuple(image_references),
            real_generation_authorization=real_generation_authorization,
        )

    def run(
        self,
        plan: VideoPlan,
        report_service: FinalReportService,
        prompt: Optional[str] = None,
        job_type: str = DEFAULT_JOB_TYPE,
        approved: bool = False,
        request_id: Optional[str] = None,
        real_generation_authorization: Optional[RealGenerationAuthorization] = None,
        timeout_seconds: float = 600,
        interval_seconds: float = 3,
    ) -> FinalReport:
        """
        Construit la requête puis délègue intégralement au
        FinalReportService fourni (Phase J). N'exécute rien lui-même.
        """

        request = self.build_request(
            plan,
            prompt=prompt,
            job_type=job_type,
            approved=approved,
            request_id=request_id,
            real_generation_authorization=real_generation_authorization,
        )

        return report_service.generate(
            request,
            timeout_seconds=timeout_seconds,
            interval_seconds=interval_seconds,
        )
