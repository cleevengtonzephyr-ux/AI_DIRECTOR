"""
AI DIRECTOR — Manifeste de génération Higgsfield (Phase F)

Le manifeste est l'énoncé EXACT de ce qui serait exécuté : modèle,
paramètres, empreinte du prompt et empreintes des médias. Il est sérialisé
de façon déterministe (JSON à clés triées, UTF-8, empreintes en hexadécimal
minuscule) et identifié par `manifest_sha256`.

Usage prévu (docs/phase_f_production_path_design.md) :
- le job « prepare » calcule le manifeste et publie son empreinte ;
- l'humain approuve CETTE empreinte (entrée du workflow, revue de
  l'environnement GitHub) ;
- le job « execute » recalcule le manifeste depuis les fichiers et refuse
  toute divergence (`ManifestMismatchError`) avant tout envoi.

Les médias sont lus UNE seule fois (`prepare_media`) : les octets hachés
sont ceux que le futur envoi utiliserait, jamais une seconde lecture du
disque (option (ii) de la limite A2-c, côté Director).

Ce module ne fait aucun appel réseau, aucun sous-processus, et ne décide
rien : il décrit et compare.
"""

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from integrations.higgsfield.errors import HiggsfieldError


MANIFEST_SCHEMA = "ai_director.higgsfield.generation_manifest"
MANIFEST_SCHEMA_VERSION = 1

_HEX64 = re.compile(r"[0-9a-f]{64}")
_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_PARAMETER_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_ROLE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_APPROVAL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")

# Types reconnus par leur signature binaire, jamais par l'extension : un
# fichier dont le contenu n'est pas reconnu est refusé (fail closed).
_MEDIA_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)


class ManifestError(HiggsfieldError):
    """Manifeste impossible à construire : entrée invalide, média absent ou illisible."""


class ManifestMismatchError(HiggsfieldError):
    """Le manifeste recalculé ne correspond pas à l'empreinte approuvée : arrêt."""

    def __init__(self, message: str, approved_sha256: Optional[str], actual_sha256: Optional[str]):
        super().__init__(message)
        self.approved_sha256 = approved_sha256
        self.actual_sha256 = actual_sha256


def _sniff_media_type(content: bytes) -> Optional[str]:
    for signature, media_type in _MEDIA_SIGNATURES:
        if content.startswith(signature):
            return media_type
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


@dataclass(frozen=True)
class PreparedMedia:
    """
    Un média lu une seule fois. `content` porte les octets hachés : c'est
    ce contenu, et lui seul, qu'un futur envoi transmettrait. `source` est
    le chemin local d'origine : jamais publié dans le manifeste canonique.
    """

    role: str
    sha256: str
    size_bytes: int
    media_type: str
    source: str = field(repr=False)
    content: bytes = field(repr=False, compare=False)

    def canonical(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
        }


def prepare_media(role: str, path: str) -> PreparedMedia:
    """Lit `path` une seule fois, l'identifie par sa signature et le hache."""

    if not isinstance(role, str) or not _ROLE.fullmatch(role):
        raise ManifestError(f"media role {role!r} is not a plain lower-case identifier")
    if not isinstance(path, str) or not path or "\x00" in path:
        raise ManifestError(f"media path for role {role!r} is empty or invalid")
    candidate = Path(path)
    if candidate.is_symlink():
        raise ManifestError(f"media for role {role!r} is a symbolic link: refused")
    if not candidate.is_file():
        raise ManifestError(f"media for role {role!r} is not a regular file")
    try:
        content = candidate.read_bytes()
    except OSError as error:
        raise ManifestError(f"media for role {role!r} could not be read ({type(error).__name__})") from error
    if not content:
        raise ManifestError(f"media for role {role!r} is empty")
    media_type = _sniff_media_type(content)
    if media_type is None:
        raise ManifestError(f"media for role {role!r} has an unrecognized content type: refused")
    return PreparedMedia(
        role=role,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        media_type=media_type,
        source=path,
        content=content,
    )


def _validated_parameters(parameters: Mapping[str, Any]) -> Tuple[Tuple[str, Any], ...]:
    if not isinstance(parameters, Mapping):
        raise ManifestError("parameters must be a mapping")
    validated = []
    for name, value in parameters.items():
        if not isinstance(name, str) or not _PARAMETER_NAME.fullmatch(name):
            raise ManifestError(f"parameter name {name!r} is not a plain snake_case identifier")
        # Ni float (représentation ambiguë), ni bool (sous-type d'int), ni None :
        # une valeur absente n'est jamais sérialisée « par défaut ».
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ManifestError(f"parameter {name!r} must be an int or a str, got {type(value).__name__}")
        validated.append((name, value))
    return tuple(sorted(validated))


@dataclass(frozen=True)
class GenerationManifest:
    """Énoncé exact d'une génération. `prompt` n'apparaît jamais dans la forme canonique."""

    request_id: str
    model_id: str
    prompt_sha256: str
    prompt_utf8_bytes: int
    parameters: Tuple[Tuple[str, Any], ...]
    media: Tuple[PreparedMedia, ...]
    prompt: str = field(repr=False, compare=False)

    def canonical(self) -> Dict[str, Any]:
        return {
            "schema": MANIFEST_SCHEMA,
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "request_id": self.request_id,
            "model_id": self.model_id,
            "prompt": {"sha256": self.prompt_sha256, "utf8_bytes": self.prompt_utf8_bytes},
            "parameters": dict(self.parameters),
            "media": [item.canonical() for item in self.media],
        }

    def canonical_json(self) -> bytes:
        return json.dumps(
            self.canonical(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")

    @property
    def manifest_sha256(self) -> str:
        return hashlib.sha256(self.canonical_json()).hexdigest()

    def parameter(self, name: str) -> Any:
        return dict(self.parameters).get(name)

    def media_for_role(self, role: str) -> Optional[PreparedMedia]:
        return next((item for item in self.media if item.role == role), None)


def build_manifest(
    request_id: str,
    model_id: str,
    prompt: str,
    parameters: Mapping[str, Any],
    media: Sequence[Tuple[str, str]],
) -> GenerationManifest:
    """
    Construit le manifeste depuis les valeurs et les fichiers réels.
    `media` : couples (rôle, chemin), dans l'ordre d'envoi ; chaque rôle est unique.
    """

    if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
        raise ManifestError(f"request_id {request_id!r} is not a plain identifier")
    if not isinstance(model_id, str) or not _MODEL_ID.fullmatch(model_id):
        raise ManifestError(f"model_id {model_id!r} is not a plain identifier")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ManifestError("prompt must be a non-empty str")
    prompt_bytes = prompt.encode("utf-8")

    prepared = []
    for entry in media:
        role, path = entry
        if any(item.role == role for item in prepared):
            raise ManifestError(f"media role {role!r} appears more than once")
        prepared.append(prepare_media(role, path))

    return GenerationManifest(
        request_id=request_id,
        model_id=model_id,
        prompt_sha256=hashlib.sha256(prompt_bytes).hexdigest(),
        prompt_utf8_bytes=len(prompt_bytes),
        parameters=_validated_parameters(parameters),
        media=tuple(prepared),
        prompt=prompt,
    )


def verify_manifest(approved_manifest_sha256: str, manifest: GenerationManifest) -> None:
    """Lève `ManifestMismatchError` sauf si `manifest` est exactement celui approuvé."""

    if not isinstance(approved_manifest_sha256, str) or not _HEX64.fullmatch(approved_manifest_sha256):
        raise ManifestMismatchError(
            "approved manifest digest is missing or is not 64 lower-case hex characters",
            approved_sha256=approved_manifest_sha256 if isinstance(approved_manifest_sha256, str) else None,
            actual_sha256=manifest.manifest_sha256,
        )
    actual = manifest.manifest_sha256
    if actual != approved_manifest_sha256:
        raise ManifestMismatchError(
            f"recomputed manifest {actual} differs from the approved manifest "
            f"{approved_manifest_sha256}: nothing is sent",
            approved_sha256=approved_manifest_sha256,
            actual_sha256=actual,
        )


def derive_idempotency_key(manifest_sha256: str, approval_id: str) -> str:
    """
    Clé d'idempotence STABLE pour une approbation donnée d'un manifeste
    donné : toute reprise réseau de la même soumission réutilise la même
    clé ; une nouvelle approbation (par exemple après un refus pour crédits
    insuffisants) produit une nouvelle clé. Dérivée, jamais aléatoire :
    elle se recalcule après un redémarrage sans état. Ce n'est pas un
    secret, et sa prise en charge par Higgsfield n'est PAS confirmée
    (voir `rest_api.HIGGSFIELD_REST_FACTS["idempotency_key_header"]`).
    """

    if not isinstance(manifest_sha256, str) or not _HEX64.fullmatch(manifest_sha256):
        raise ManifestError("manifest_sha256 must be 64 lower-case hex characters")
    if not isinstance(approval_id, str) or not _APPROVAL_ID.fullmatch(approval_id):
        raise ManifestError(f"approval_id {approval_id!r} is not a plain identifier")
    material = f"ai_director.idempotency.v1\n{manifest_sha256}\n{approval_id}".encode("utf-8")
    return "aidir1-" + hashlib.sha256(material).hexdigest()
