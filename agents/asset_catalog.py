"""
AI DIRECTOR — Asset Catalog v0.1

Source unique de vérité pour les règles des catégories d'assets ZEPHYR
(extensions autorisées, obligation, rôle sémantique).

Consommé par :
- AssetIntakeManager    (découverte / validation structurelle)
- AssetPreparationSystem (préparation / hash / dédoublonnage — référence)
- AssetManager          (registre canonique / référencement)

Ce module ne contient aucune logique métier, uniquement des données
statiques. Il ne fait aucun appel Higgsfield et ne génère aucun média.
"""

from typing import Dict, Tuple, TypedDict


class AssetCategoryRule(TypedDict):
    required: bool
    extensions: Tuple[str, ...]
    role: str


ASSET_CATALOG: Dict[str, AssetCategoryRule] = {
    "avatar": {
        "required": True,
        "extensions": (".png", ".jpg", ".jpeg", ".webp"),
        "role": "master_avatar",
    },
    "references": {
        "required": True,
        "extensions": (".png", ".jpg", ".jpeg", ".webp"),
        "role": "face_reference",
    },
    "audio": {
        "required": True,
        "extensions": (".wav", ".mp3", ".m4a", ".aac"),
        "role": "main_voice",
    },
    "prompts": {
        "required": True,
        "extensions": (".txt", ".md", ".json"),
        "role": "production_prompts",
    },
    "music": {
        "required": False,
        "extensions": (".wav", ".mp3", ".m4a", ".aac"),
        "role": "background_music",
    },
    "logo": {
        "required": False,
        "extensions": (".png", ".jpg", ".jpeg", ".webp", ".svg"),
        "role": "brand_logo",
    },
}
