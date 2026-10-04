"""
AI DIRECTOR — Exécution de production Higgsfield, étapes du workflow (Phase F)

Point d'entrée de `.github/workflows/higgsfield-production.yml`.

    prepare
        Calcule le manifeste Video 005 depuis les fichiers réels, vérifie
        qu'il correspond à la Release Candidate verrouillée, publie son
        empreinte et sa forme canonique (sans prompt, sans chemin). Aucun
        réseau, aucun secret.

    verify-and-execute --approved-manifest-sha256 H --approval-id ID --run-attempt N [--new-journal]
        Recalcule le manifeste et le compare à l'empreinte approuvée : toute
        divergence arrête le processus avant tout envoi. Puis s'arrête sur
        Provider = CLOSED : aucune soumission n'est possible depuis ce script.
        Un journal absent est refusé (code 6) sauf avec `--new-journal`, qui
        crée explicitement un journal neuf et refuse s'il en existe déjà un.
        Sur un runner GitHub Actions, ce journal est éphémère : il ne
        survit pas au job et ne fournit aucun anti-rejeu entre exécutions.

Ce script ne lit AUCUNE variable d'environnement, aucun secret, et
n'instancie ni client REST ni transport : il ne peut rien envoyer. Le
câblage réel (autorisation issue de l'approbation GitHub ->
GenerationJobService -> HiggsfieldProvider.create_job() -> client REST)
appartient à une décision de lancement distincte (docs/phase_f_production_path_design.md).

Codes de sortie :
    0  prepare réussi
    2  entrée invalide ou manifeste impossible à construire
    3  manifeste divergent de l'empreinte approuvée
    4  Provider = CLOSED : exécution refusée (issue attendue aujourd'hui)
    5  reprise d'exécution refusée (rapprochement requis)
    6  journal d'audit corrompu ou impossible à écrire
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.production_audit_journal import AuditJournal, AuditJournalError
from agents.prompt_assembly_system import PromptAssemblySystem
from agents.release_candidate_identity_lock import VIDEO_005_RELEASE_CANDIDATE
from integrations.higgsfield.manifest import (
    GenerationManifest,
    ManifestError,
    ManifestMismatchError,
    build_manifest,
    derive_idempotency_key,
    verify_manifest,
)

EXIT_OK = 0
EXIT_INVALID = 2
EXIT_MISMATCH = 3
EXIT_PROVIDER_CLOSED = 4
EXIT_RERUN_REFUSED = 5
EXIT_JOURNAL = 6

DEFAULT_JOURNAL = PROJECT_ROOT / "state" / "production_audit.jsonl"

# Rôles et fichiers de la Release Candidate Video 005 (mêmes fichiers que
# ceux retenus par AssetPreparationSystem, lus ici sans réécrire
# l'inventaire versionné).
VIDEO_005_MEDIA = (
    ("master_avatar", "assets/zephyr/avatar/avatar_master.png"),
    ("face_reference", "assets/zephyr/references/mon avatar habille.png"),
)


def build_video_005_manifest(root: Path = PROJECT_ROOT) -> GenerationManifest:
    contract = VIDEO_005_RELEASE_CANDIDATE
    prompt = PromptAssemblySystem(root).assemble(contract.request_id)
    manifest = build_manifest(
        request_id=contract.request_id,
        model_id=contract.job_type,
        prompt=prompt,
        parameters={
            "duration": contract.duration,
            "resolution": contract.resolution,
            "aspect_ratio": contract.aspect_ratio,
        },
        media=[(role, str(root / relative)) for role, relative in VIDEO_005_MEDIA],
    )
    expected = {
        "prompt": contract.prompt_sha256,
        "master_avatar": contract.avatar_master_sha256,
        "face_reference": contract.face_reference_sha256,
    }
    actual = {
        "prompt": manifest.prompt_sha256,
        **{item.role: item.sha256 for item in manifest.media},
    }
    divergent = sorted(name for name in expected if actual.get(name) != expected[name])
    if divergent:
        raise ManifestError(f"Video 005 content differs from the locked Release Candidate: {divergent}")
    return manifest


def _write_summary(path: Optional[str], lines: List[str]) -> None:
    if path:
        with open(path, "a", encoding="utf-8") as summary:
            summary.write("\n".join(lines) + "\n")


def _prepare(args) -> int:
    try:
        manifest = build_video_005_manifest()
    except (ManifestError, OSError, ValueError) as error:
        print(f"MANIFEST_INVALID: {error}")
        return EXIT_INVALID
    canonical = json.dumps(manifest.canonical(), sort_keys=True, indent=2, ensure_ascii=False)
    print(f"manifest_sha256={manifest.manifest_sha256}")
    print(canonical)
    _write_summary(args.summary_file, [
        "## Manifeste à approuver",
        "",
        f"`manifest_sha256` : `{manifest.manifest_sha256}`",
        "",
        "```json",
        canonical,
        "```",
        "",
        "L'estimation de coût n'est pas un plafond garanti. Provider = CLOSED.",
    ])
    return EXIT_OK


def _verify_and_execute(args) -> int:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", args.approval_id) or not re.fullmatch(
        r"[1-9][0-9]{0,5}", args.run_attempt
    ):
        print("INVALID_ARGUMENTS: approval id or run attempt is malformed.")
        return EXIT_INVALID
    journal = AuditJournal(Path(args.journal))
    request_id = VIDEO_005_RELEASE_CANDIDATE.request_id
    try:
        if args.new_journal:
            journal.initialize()
        journal.verify()
        if args.run_attempt != "1":
            # Le registre anti-rejeu d'un runner éphémère est vide : une
            # reprise ne peut pas savoir si la tentative précédente a été
            # reçue. Refus, rapprochement humain requis.
            journal.append("execution_refused", request_id, {
                "reason": "rerun_without_durable_state", "approval_id": args.approval_id,
                "run_attempt": args.run_attempt,
            })
            print("RERUN_REFUSED: reconcile the previous attempt before any new send.")
            return EXIT_RERUN_REFUSED
        try:
            manifest = build_video_005_manifest()
            verify_manifest(args.approved_manifest_sha256, manifest)
        except ManifestMismatchError as error:
            journal.append("manifest_mismatch", request_id, {
                "approved_manifest_sha256": error.approved_sha256,
                "actual_manifest_sha256": error.actual_sha256,
                "approval_id": args.approval_id,
            })
            print(f"MANIFEST_MISMATCH: {error}")
            return EXIT_MISMATCH
        except (ManifestError, OSError, ValueError) as error:
            journal.append("execution_refused", request_id, {"reason": "manifest_invalid", "approval_id": args.approval_id})
            print(f"MANIFEST_INVALID: {error}")
            return EXIT_INVALID
        idempotency_key = derive_idempotency_key(manifest.manifest_sha256, args.approval_id)
        journal.append("manifest_verified", request_id, {
            "manifest_sha256": manifest.manifest_sha256,
            "approval_id": args.approval_id,
            "idempotency_key": idempotency_key,
        })
        journal.append("submission_refused_provider_closed", request_id, {
            "manifest_sha256": manifest.manifest_sha256,
            "approval_id": args.approval_id,
            "decision": "NO-GO",
        })
    except AuditJournalError as error:
        print(f"AUDIT_JOURNAL_FAILURE: {error}")
        return EXIT_JOURNAL
    print(f"manifest_sha256={manifest.manifest_sha256} verified")
    print("PROVIDER_CLOSED: NO-GO in force (docs/phase_a_real_generation_decision.md). Nothing was sent.")
    return EXIT_PROVIDER_CLOSED


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--summary-file", default=None)
    execute = commands.add_parser("verify-and-execute")
    execute.add_argument("--approved-manifest-sha256", required=True)
    execute.add_argument("--approval-id", required=True)
    execute.add_argument("--run-attempt", required=True)
    execute.add_argument("--journal", default=str(DEFAULT_JOURNAL))
    execute.add_argument("--new-journal", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "prepare":
        return _prepare(args)
    return _verify_and_execute(args)


if __name__ == "__main__":
    sys.exit(main())
