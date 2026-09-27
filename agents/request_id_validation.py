"""
AI DIRECTOR — Request ID Validation (Phase P3.103, F7)

Un `request_id` (ou `video_id`, même identifiant : "005") sert de
composant de NOM DE FICHIER dans `FileCriticalSectionLock`
(`<lock_dir>/<request_id>.lock`) et dans `PromptAssemblySystem`
(`<prompt_root>/video_<video_id>.md`). Sans contrôle, `../escape`,
`C:\\temp\\escape` ou `\\\\server\\share` sortaient de ces répertoires.

DEUX COUCHES INDÉPENDANTES, aucune ne remplaçant l'autre :

1. `validate_request_id()` -- allowlist stricte, appliquée AVANT toute
   construction de chemin :

       ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$     (fullmatch, jamais `$` seul)

   Exclut par construction séparateurs, `:`, `.`, espaces, contrôles et
   non-ASCII ; les noms réservés Windows (CON, NUL, COM1...) sont refusés
   en plus. Une entrée invalide est REFUSÉE, jamais normalisée.

2. `contained_child_path()` -- le chemin construit, une fois rendu
   absolu et normalisé, doit être un enfant DIRECT du répertoire racine
   normalisé de la même façon.

Module neutre : aucun import P2, aucune écriture disque.
"""

import os
import re
from pathlib import Path

REQUEST_ID_MAX_LENGTH = 64

_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")

# Noms de périphériques Windows, réservés quelle que soit la casse.
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(10)}
    | {f"LPT{index}" for index in range(10)}
)


class InvalidRequestIdError(ValueError):
    """`request_id` hors contrat -- refusé avant toute construction de
    chemin."""


class PathContainmentError(ValueError):
    """Le chemin normalisé sort du répertoire racine attendu."""


def validate_request_id(request_id: object) -> str:
    """Retourne `request_id` INCHANGÉ s'il respecte le contrat, lève
    `InvalidRequestIdError` sinon."""

    if not isinstance(request_id, str):
        raise InvalidRequestIdError(
            f"request_id must be a str, got {type(request_id).__name__}."
        )
    if _REQUEST_ID_PATTERN.fullmatch(request_id) is None:
        raise InvalidRequestIdError(
            f"request_id {request_id!r} is invalid: expected 1-"
            f"{REQUEST_ID_MAX_LENGTH} characters from [A-Za-z0-9_-], "
            f"starting with a letter or digit."
        )
    if request_id.upper() in _WINDOWS_RESERVED_NAMES:
        raise InvalidRequestIdError(
            f"request_id {request_id!r} is a reserved Windows device name."
        )
    return request_id


def contained_child_path(root: Path, file_name: str) -> Path:
    """Retourne `root / file_name` si ce chemin, rendu absolu et
    normalisé, est un enfant DIRECT de `root` normalisé ; lève
    `PathContainmentError` sinon. Le chemin retourné est `root / file_name`
    (forme d'origine inchangée).

    Normalisation LEXICALE (`os.path.abspath` + `normcase`), jamais
    `Path.resolve()` : sous Windows, `resolve()` retourne de façon non
    déterministe un préfixe de chemin étendu pendant qu'un autre processus crée le
    répertoire, ce qui refusait à tort des verrous légitimes concurrents.
    """

    root = Path(root)
    candidate = root / file_name
    normalized_root = os.path.normcase(os.path.abspath(root))
    normalized_candidate = os.path.normcase(os.path.abspath(candidate))
    # Le nom final doit être EXACTEMENT celui demandé : `C:x` (relatif au
    # lecteur) est rejoint par pathlib en `root\x` -- un autre fichier,
    # bien qu'à l'intérieur de `root`.
    if (
        candidate.name != file_name
        or os.path.basename(normalized_candidate) != os.path.normcase(file_name)
        or os.path.dirname(normalized_candidate) != normalized_root
    ):
        raise PathContainmentError(
            f"Path {str(candidate)!r} normalizes to {normalized_candidate!r}, "
            f"outside {normalized_root!r}."
        )
    return candidate
