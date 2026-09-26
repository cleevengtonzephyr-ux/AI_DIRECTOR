"""
AI DIRECTOR — architecture:audit (Phase P3.32, MASTER PROMPT V2)

Exécute le Architecture Drift Detector (Phase P3.31,
agents/architecture_drift_detector.py) contre le repository RÉEL et
imprime un rapport lisible par un humain, pour une revue ponctuelle
sans avoir à relancer toute la suite de tests.

Ce script est purement LECTURE SEULE : il ne modifie, ne supprime, ni
ne déplace aucun fichier ; il n'appelle jamais Higgsfield, le réseau,
ni `create_job()` ; il ne construit aucune autorisation ni activation.
Il ne réimplémente aucune règle de dérive -- il se contente d'appeler
`ArchitectureDriftDetector.analyze()` (Phase P3.31) et de formater son
`DriftReport`. Aucune deuxième source de vérité n'est introduite ici.

NE CORRIGE JAMAIS AUTOMATIQUEMENT une dérive détectée (Section 17/18,
rapport P3.32) : ce script s'arrête à l'affichage du rapport, jamais à
une modification de code.

Code de sortie :
    0  si DriftStatus.NO_DRIFT
    1  si DriftStatus.DRIFT_DETECTED (au moins un finding actionnable)
    2  si DriftStatus.ANALYSIS_INCOMPLETE (fail-closed : jamais traité
       comme un succès)

Usage :
    python scripts/architecture_audit.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.architecture_drift_detector import ArchitectureDriftDetector, DriftStatus


_EXIT_CODE_BY_STATUS = {
    DriftStatus.NO_DRIFT: 0,
    DriftStatus.DRIFT_DETECTED: 1,
    DriftStatus.ANALYSIS_INCOMPLETE: 2,
}


def main() -> int:
    report = ArchitectureDriftDetector().analyze()

    print("=" * 70)
    print("AI DIRECTOR -- Architecture Drift Audit (Phase P3.31/P3.32)")
    print("=" * 70)
    print(f"Status          : {report.status.value}")
    print(f"Files analyzed  : {len(report.files_analyzed)}")
    print(f"Files unreadable: {len(report.files_unreadable)}")
    for path in report.files_unreadable:
        print(f"    UNREADABLE: {path}")
    print(f"Findings        : {len(report.findings)}")

    for finding in report.findings:
        print(
            f"  [{finding.severity.value}] {finding.code} "
            f"{finding.file}:{finding.line}"
        )
        print(f"      rule       : {finding.violated_rule}")
        print(f"      evidence   : {finding.evidence}")
        print(f"      explanation: {finding.explanation}")

    print("=" * 70)

    if report.status == DriftStatus.NO_DRIFT:
        print("NO_DRIFT -- architecture matches the canonical contract.")
    elif report.status == DriftStatus.DRIFT_DETECTED:
        print(
            "DRIFT_DETECTED -- review the findings above. This script "
            "never auto-corrects; a human/developer decision is required."
        )
    else:
        print(
            "ANALYSIS_INCOMPLETE -- one or more files could not be read "
            "or parsed. Treated as a FAILURE, never as a silent PASS."
        )

    print("=" * 70)

    return _EXIT_CODE_BY_STATUS[report.status]


if __name__ == "__main__":
    sys.exit(main())
