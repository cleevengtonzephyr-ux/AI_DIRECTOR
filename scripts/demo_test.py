"""
AI DIRECTOR — demo:test (Phase N, MASTER PROMPT V2, Priorité 6)

Démonstration de bout en bout du pipeline complet :

    AIDirector -> TaskManager -> VideoAgent -> HiggsfieldProvider
    -> GenerationCostService -> GenerationApprovalGate
    -> GenerationJobService -> QualityEvaluator -> FinalReportService

EXCLUSIVEMENT via MockHiggsfieldProvider : aucun appel réseau, aucun
appel CLI réel, aucune génération réelle, aucun crédit consommé, quel
que soit l'état du compte Higgsfield réel.

Trois scénarios illustrent le comportement de sécurité du pipeline :
1. Coût connu, budget suffisant, PAS d'approbation -> NEEDS_APPROVAL.
2. Même mission, approuvée explicitement -> EXECUTED_PASS.
3. Coût connu, budget insuffisant -> BLOCKED, même approuvée.

Usage :
    python scripts/demo_test.py
"""

import sys
from pathlib import Path
from typing import Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.final_report_service import FinalReport, FinalReportService, FinalReportStatus
from agents.generation_approval_gate import GenerationApprovalGate, RealGenerationAuthorization
from agents.release_candidate_identity_lock import VIDEO_005_RELEASE_CANDIDATE
from agents.task_manager import TaskManager
from director import AIDirector
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider

# Seule duree reellement confirmee pour seedance_2_0 par lecture seule
# (Phase P1.2 : 5/10/15s acceptes, >15s rejete par l'API reelle). La
# demo utilise donc explicitement cette valeur plutot que le defaut
# TaskManager (40s), desormais correctement rejete par
# GenerationApprovalGate (Phase P1.3).
CONFIRMED_DURATION = 5


def _print_report(label: str, report: FinalReport) -> None:
    print()
    print(f"--- {label} ---")
    print(f"Status            : {report.status.value}")
    print(f"Approval decision : {report.approval_decision.value}")
    print(f"Job created       : {report.job_created}")

    if report.job_id:
        print(f"Job ID            : {report.job_id}")
        print(f"Output URLs       : {report.output_urls}")

    print(f"Summary           : {report.summary}")


def run_demo() -> Dict[str, FinalReport]:
    """
    Exécute les 3 scénarios illustratifs décrits ci-dessus, tous via
    MockHiggsfieldProvider. Retourne les 3 FinalReport produits (utile
    pour un test automatisé de non-régression du script lui-même).
    """

    print("=" * 70)
    print("AI DIRECTOR - DEMO:TEST (pipeline complet, MockHiggsfieldProvider)")
    print("=" * 70)
    print("Aucun appel reseau. Aucun appel CLI reel. Aucun credit consomme.")

    director = AIDirector()
    task_manager = TaskManager()

    # Scenarios 1 et 2 : budget confortable, meme mission.
    provider_ok = MockHiggsfieldProvider(
        cost_per_job=10.0,
        available_credits=100.0,
        succeed_after_polls=2,
    )
    gate_ok = GenerationApprovalGate(provider_ok)
    report_service_ok = FinalReportService(provider_ok, gate_ok)

    task_1 = task_manager.submit(
        video_id="005",
        title="Demo - sans approbation",
        hook="hook de demonstration",
        objective="objectif de demonstration",
        duration=CONFIRMED_DURATION,
    )
    report_1 = task_manager.process(
        task_1.task_id,
        director,
        approved=False,
        report_service=report_service_ok,
    )
    _print_report("Scenario 1 : sans approbation explicite", report_1)
    assert report_1.status == FinalReportStatus.NOT_EXECUTED

    task_2 = task_manager.submit(
        video_id="005",
        title="Demo - approuvee",
        hook="hook de demonstration",
        objective="objectif de demonstration",
        duration=CONFIRMED_DURATION,
    )
    report_2 = task_manager.process(
        task_2.task_id,
        director,
        approved=True,
        # Phase P2.11 : le budget/`approved` seul ne suffit plus — une
        # autorisation humaine explicite, liée à CETTE requête précise
        # (task_2.video_id == "005"), est désormais requise pour
        # APPROVED. Ceci reste une démonstration MockHiggsfieldProvider
        # (aucune génération réelle) : ne pas reproduire cette
        # construction pour un run réel sans un consentement humain
        # authentique en amont.
        # Phase B : l'autorisation est liée au contenu approuvé exact
        # (empreintes canoniques de Video 005, que l'Identity Lock exige
        # déjà) -- jamais recalculée ni devinée par le Director.
        real_generation_authorization=RealGenerationAuthorization(
            request_id=task_2.video_id,
            authorized_by_human=True,
            note="scripts/demo_test.py Scenario 2 — MockHiggsfieldProvider only.",
            prompt_sha256=VIDEO_005_RELEASE_CANDIDATE.prompt_sha256,
            avatar_sha256=VIDEO_005_RELEASE_CANDIDATE.avatar_master_sha256,
            face_reference_sha256=VIDEO_005_RELEASE_CANDIDATE.face_reference_sha256,
        ),
        report_service=report_service_ok,
        interval_seconds=0,
    )
    _print_report("Scenario 2 : approuvee explicitement", report_2)
    assert report_2.status == FinalReportStatus.EXECUTED_PASS

    # Scenario 3 : budget insuffisant, meme approuvee.
    provider_low = MockHiggsfieldProvider(cost_per_job=50.0, available_credits=1.41)
    gate_low = GenerationApprovalGate(provider_low)
    report_service_low = FinalReportService(provider_low, gate_low)

    task_3 = task_manager.submit(
        video_id="005",
        title="Demo - budget insuffisant",
        hook="hook de demonstration",
        objective="objectif de demonstration",
        duration=CONFIRMED_DURATION,
    )
    report_3 = task_manager.process(
        task_3.task_id,
        director,
        approved=True,
        report_service=report_service_low,
    )
    _print_report("Scenario 3 : budget insuffisant", report_3)
    assert report_3.status == FinalReportStatus.NOT_EXECUTED

    print()
    print("=" * 70)
    print("DEMO TERMINEE")
    print("ZERO REAL GENERATION")
    print("ZERO HIGGSFIELD CREDITS CONSUMED")
    print("=" * 70)

    return {"scenario_1": report_1, "scenario_2": report_2, "scenario_3": report_3}


if __name__ == "__main__":
    run_demo()
