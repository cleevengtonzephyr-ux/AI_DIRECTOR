"""
AI DIRECTOR — Release Candidate Identity Lock (Phase P2.18, MASTER PROMPT V2)

Ferme le gap structurel identifié en P2.17 : `GenerationApprovalGate.
evaluate()` vérifiait déjà `request_id`/`job_type`/`duration`/
`resolution`/`aspect_ratio` de façon PARTIELLE (via
`_validate_model_compatibility`, qui ne connaît que la compatibilité
avec le SCHÉMA du modèle, jamais une valeur canonique précise), mais ne
vérifiait JAMAIS :
- le contenu réel du Master Prompt (SHA-256/longueur/lignes) ;
- le contenu réel des fichiers d'assets référencés (avatar_master,
  face_reference).

Seul un test de non-régression séparé
(tests/test_phase_p2_11_human_authorization_guard.py::TestH,
tests/test_phase_p2_17_production_activation_contract.py) le vérifiait
— HORS du chemin d'exécution réel utilisé par `GenerationJobService`.

Ce module ajoute UN SEUL mécanisme, minimal et FAIL CLOSED :
`ReleaseCandidateIdentityLock.violations(request)` -> `List[str]`, qui
recalcule RÉELLEMENT (ne fait jamais confiance à une valeur déjà
portée par l'objet, cf. Objectif 7 P2.18) :

- le SHA-256 du prompt tel qu'il apparaît RÉELLEMENT dans la
  `GenerationRequest` évaluée — jamais un objet parallèle, jamais
  recalculé depuis `PromptAssemblySystem` (Objectif 8 P2.18 : "VERIFY
  WHAT WILL ACTUALLY BE SENT") ;
- le SHA-256 du FICHIER RÉEL référencé par `request.start_image.
  source` — jamais `request.start_image.sha256`, qui pourrait être
  périmé ou falsifié (Objectif 7 P2.18 : fichier remplacé après coup,
  hash stale, référence incorrecte) ;
- le SHA-256 du FICHIER RÉEL référencé par le premier
  `request.image_references` de rôle "face_reference".

Portée volontairement étroite : ce contrat verrouille EXACTEMENT LA
RELEASE CANDIDATE ACTUELLEMENT VALIDÉE (Video 005). Toute requête dont
`request_id` diffère de celle-ci est un mismatch d'identité — pas une
erreur, un refus légitime : ce module ne prétend pas généraliser à un
futur catalogue multi-vidéos (hors périmètre de cette phase).

N'appelle JAMAIS `create_job()`. N'importe ni `HiggsfieldClient`, ni
`subprocess`, ni le réseau. Injecté de façon OPTIONNELLE dans
`GenerationApprovalGate` (défaut `None`, cf. agents/
generation_approval_gate.py) : un Gate construit sans cet argument
(comme le font les 356 tests existant avant cette phase) garde un
comportement STRICTEMENT identique à avant P2.18 — aucune régression.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class ReleaseCandidateContract:
    """
    Snapshot gelé d'une Release Candidate vérifiée en lecture réelle
    (Phases P2.9-P2.11, re-confirmé en P2.17). Valeurs canoniques,
    jamais recalculées "à la baisse" : toute divergence par rapport à
    ce contrat doit bloquer, jamais passer silencieusement.
    """

    request_id: str
    job_type: str
    duration: int
    resolution: str
    aspect_ratio: str
    prompt_sha256: str
    prompt_chars: int
    prompt_lines: int
    avatar_master_sha256: str
    face_reference_sha256: str


# Video 005 — valeurs vérifiées réellement depuis le projet (Phase
# P2.17 : PromptAssemblySystem.assemble("005") + AssetPreparationSystem
# .scan() sur les fichiers réels, ré-exécuté et confirmé identique en
# P2.18). Jamais inventées ; cf. rapport P2.18 pour la preuve.
VIDEO_005_RELEASE_CANDIDATE = ReleaseCandidateContract(
    request_id="005",
    job_type="seedance_2_0",
    duration=15,
    resolution="720p",
    aspect_ratio="9:16",
    prompt_sha256="1c498617adb4603bcf2fc114a9cb9e8fe2219f09285adbff4d1e6c7a10a669e1",
    prompt_chars=7284,
    prompt_lines=265,
    avatar_master_sha256="d293e41a63f66fd43afbebee3f7f9f1bd29143b465fa57a18ab4e1df5faf7280",
    face_reference_sha256="df83a97b71cff9a90191c19d15ff989228b9fef2e57c96cf7c76c68652e3a343",
)


def _sha256_of_file(path: str) -> Optional[str]:
    """
    Recalcule le SHA-256 depuis le FICHIER RÉEL sur disque, jamais
    depuis une valeur déjà portée en mémoire (Objectif 7, P2.18).
    Renvoie `None` si le fichier est absent/illisible — jamais une
    exception qui pourrait être mal interprétée plus haut dans
    `GenerationApprovalGate.evaluate()`, jamais une valeur inventée :
    l'appelant (`ReleaseCandidateIdentityLock`) traite `None` comme un
    échec (FAIL CLOSED).

    Logique de hachage identique à `AssetPreparationSystem.
    calculate_hash()` (agents/asset_preparation_system.py) —
    délibérément dupliquée ici (8 lignes) plutôt que ré-instanciée,
    pour ne pas coupler ce module aux effets de bord de construction
    d'AssetPreparationSystem (création de répertoires projet) ni à un
    `project_root` dont ce module n'a par ailleurs besoin.
    """

    try:
        sha256 = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except OSError:
        return None


class ReleaseCandidateIdentityLock:
    """
    Vérifie qu'une `GenerationRequest` correspond EXACTEMENT au contrat
    de Release Candidate injecté. Ne modifie jamais la requête. Ne
    décide jamais `APPROVED` elle-même : `violations()` renvoie une
    liste de raisons — liste vide == identité conforme au contrat (le
    Gate reste seul décisionnaire de la décision finale).
    """

    def __init__(self, contract: ReleaseCandidateContract):
        self.contract = contract

    def violations(self, request) -> List[str]:
        c = self.contract
        violations: List[str] = []

        if request.request_id != c.request_id:
            violations.append(
                f"Identity lock: request_id '{request.request_id}' does not "
                f"match the locked Release Candidate '{c.request_id}'."
            )

        if request.job_type != c.job_type:
            violations.append(
                f"Identity lock: job_type '{request.job_type}' does not "
                f"match the locked Release Candidate '{c.job_type}'."
            )

        if request.duration != c.duration:
            violations.append(
                f"Identity lock: duration {request.duration!r} does not "
                f"match the locked Release Candidate {c.duration}."
            )

        if request.resolution != c.resolution:
            violations.append(
                f"Identity lock: resolution {request.resolution!r} does not "
                f"match the locked Release Candidate {c.resolution!r}."
            )

        if request.aspect_ratio != c.aspect_ratio:
            violations.append(
                f"Identity lock: aspect_ratio {request.aspect_ratio!r} does "
                f"not match the locked Release Candidate {c.aspect_ratio!r}."
            )

        violations.extend(self._prompt_violations(request))
        violations.extend(self._asset_violations(request))

        return violations

    def _prompt_violations(self, request) -> List[str]:
        c = self.contract
        prompt = request.prompt

        if not isinstance(prompt, str) or not prompt:
            return ["Identity lock: prompt is missing or empty."]

        violations = []

        if len(prompt) != c.prompt_chars:
            violations.append(
                f"Identity lock: prompt length {len(prompt)} does not match "
                f"the locked Release Candidate ({c.prompt_chars})."
            )

        if len(prompt.splitlines()) != c.prompt_lines:
            violations.append(
                f"Identity lock: prompt line count "
                f"{len(prompt.splitlines())} does not match the locked "
                f"Release Candidate ({c.prompt_lines})."
            )

        actual_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if actual_sha256 != c.prompt_sha256:
            violations.append(
                f"Identity lock: prompt sha256 '{actual_sha256}' does not "
                f"match the locked Release Candidate '{c.prompt_sha256}'."
            )

        return violations

    def _asset_violations(self, request) -> List[str]:
        c = self.contract
        violations = []

        start_image = request.start_image
        if start_image is None or start_image.role != "master_avatar":
            violations.append(
                "Identity lock: start_image (role 'master_avatar') is missing."
            )
        else:
            actual = _sha256_of_file(start_image.source)
            if actual is None:
                violations.append(
                    f"Identity lock: master_avatar file could not be read "
                    f"from '{start_image.source}'."
                )
            elif actual != c.avatar_master_sha256:
                violations.append(
                    f"Identity lock: master_avatar sha256 '{actual}' does "
                    f"not match the locked Release Candidate "
                    f"'{c.avatar_master_sha256}' (file replaced or modified)."
                )
            elif start_image.sha256 is not None and start_image.sha256 != actual:
                # Défense en profondeur (Objectif 7, P2.18) : le fichier
                # réel est correct, mais la métadonnée transportée par
                # la requête (`MediaReference.sha256`) ne correspond pas
                # à ce fichier -- signe qu'un maillon amont a été
                # falsifié ou est incohérent. Ne JAMAIS faire confiance
                # à un hash déclaré qui contredit la réalité, même si la
                # réalité elle-même est correcte.
                violations.append(
                    f"Identity lock: master_avatar declared sha256 "
                    f"'{start_image.sha256}' does not match the actual "
                    f"file content ('{actual}') -- inconsistent metadata."
                )

        face_reference = next(
            (
                ref
                for ref in request.image_references
                if ref.role == "face_reference"
            ),
            None,
        )
        if face_reference is None:
            violations.append(
                "Identity lock: image_references (role 'face_reference') "
                "is missing."
            )
        else:
            actual = _sha256_of_file(face_reference.source)
            if actual is None:
                violations.append(
                    f"Identity lock: face_reference file could not be read "
                    f"from '{face_reference.source}'."
                )
            elif actual != c.face_reference_sha256:
                violations.append(
                    f"Identity lock: face_reference sha256 '{actual}' does "
                    f"not match the locked Release Candidate "
                    f"'{c.face_reference_sha256}' (file replaced or "
                    f"modified)."
                )
            elif face_reference.sha256 is not None and face_reference.sha256 != actual:
                # Même défense en profondeur que pour master_avatar
                # ci-dessus : un hash déclaré incohérent avec le
                # fichier réel est TOUJOURS un refus, même si le
                # fichier réel est correct.
                violations.append(
                    f"Identity lock: face_reference declared sha256 "
                    f"'{face_reference.sha256}' does not match the actual "
                    f"file content ('{actual}') -- inconsistent metadata."
                )

        return violations
