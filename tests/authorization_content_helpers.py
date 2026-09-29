"""
Helpers de TEST (Phase B, liaison autorisation <-> contenu).

Une `RealGenerationAuthorization` n'est approuvée par la Gate que si
elle porte les empreintes exactes du prompt, de l'avatar et de la
référence visage de la requête évaluée. Ces helpers permettent aux
tests d'exprimer EXPLICITEMENT « l'humain a approuvé exactement ce
contenu » sans affaiblir aucune vérification : les empreintes sont
recalculées par la même fonction que la Gate
(`authorization_content_digests`), et une requête déjà incohérente
(référence absente/illisible) produit une autorisation incomplète que
la Gate refusera.

Mock-only : ne construit aucune Gate ni aucun Provider, ne touche
jamais `state/`. Les deux fichiers d'assets réels sont uniquement LUS.
"""

import dataclasses
from pathlib import Path
from typing import Optional

from agents.generation_approval_gate import (
    AUTHORIZATION_CONTENT_DIGEST_FIELDS,
    GenerationRequest,
    RealGenerationAuthorization,
    authorization_content_digests,
)
from agents.release_candidate_identity_lock import VIDEO_005_RELEASE_CANDIDATE
from integrations.higgsfield.types import MediaReference

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_AVATAR_PATH = PROJECT_ROOT / "assets" / "zephyr" / "avatar" / "avatar_master.png"
REAL_FACE_PATH = PROJECT_ROOT / "assets" / "zephyr" / "references" / "mon avatar habille.png"


def content_media(avatar_path=REAL_AVATAR_PATH, face_path=REAL_FACE_PATH) -> dict:
    """`start_image`/`image_references` pointant vers des fichiers
    lisibles (par défaut les assets réels de Video 005, lus seulement)."""

    return {
        "start_image": MediaReference(role="master_avatar", source=str(avatar_path)),
        "image_references": (
            MediaReference(role="face_reference", source=str(face_path)),
        ),
    }


def bound_authorization(
    request: GenerationRequest,
    authorization: Optional[RealGenerationAuthorization] = None,
    **authorization_kwargs,
) -> RealGenerationAuthorization:
    """Autorisation liée au contenu EXACT de `request`. Si
    `authorization` est fournie, seules ses empreintes ABSENTES sont
    complétées (une empreinte explicitement fournie n'est jamais
    écrasée) ; sinon une nouvelle autorisation est construite pour
    `request.request_id` (`authorized_by_human=True` par défaut)."""

    digests = authorization_content_digests(request)
    if authorization is None:
        authorization_kwargs.setdefault("request_id", request.request_id)
        authorization_kwargs.setdefault("authorized_by_human", True)
        for name in AUTHORIZATION_CONTENT_DIGEST_FIELDS:
            authorization_kwargs.setdefault(name, digests[name])
        return RealGenerationAuthorization(**authorization_kwargs)

    missing = {
        name: digests[name]
        for name in AUTHORIZATION_CONTENT_DIGEST_FIELDS
        if getattr(authorization, name) is None
    }
    return dataclasses.replace(authorization, **missing, **authorization_kwargs)


def video_005_authorization(request_id: str = "005", **authorization_kwargs) -> RealGenerationAuthorization:
    """Autorisation liée au contenu CANONIQUE de Video 005 (les valeurs
    figées de `VIDEO_005_RELEASE_CANDIDATE`, que l'Identity Lock exige
    déjà) -- pour les tests où la requête est construite APRÈS
    l'autorisation (Director/VideoAgent). Toute requête dont le contenu
    diffère de ce canon est refusée par la Gate."""

    contract = VIDEO_005_RELEASE_CANDIDATE
    authorization_kwargs.setdefault("authorized_by_human", True)
    authorization_kwargs.setdefault("prompt_sha256", contract.prompt_sha256)
    authorization_kwargs.setdefault("avatar_sha256", contract.avatar_master_sha256)
    authorization_kwargs.setdefault("face_reference_sha256", contract.face_reference_sha256)
    return RealGenerationAuthorization(request_id=request_id, **authorization_kwargs)


def bind_request(request: GenerationRequest) -> GenerationRequest:
    """Renvoie `request` avec son autorisation (si c'est une vraie
    `RealGenerationAuthorization`) liée à son contenu exact. Toute autre
    valeur (None, objet malformé) est laissée intacte."""

    auth = request.real_generation_authorization
    if not isinstance(auth, RealGenerationAuthorization):
        return request
    return dataclasses.replace(
        request, real_generation_authorization=bound_authorization(request, auth)
    )
