"""
Tests — QualityEvaluator (Phase I, MASTER PROMPT V2).

Le scénario PASS utilise la chaîne complète (MockHiggsfieldProvider ->
GenerationApprovalGate -> GenerationJobService) pour prouver
l'intégration réelle avec la Phase H. Les autres scénarios (FAIL,
RETRY_RECOMMENDED, résultat incohérent) construisent directement un
GenerationJobOutcome — aucune génération réelle n'est requise ni
possible pour un simple test de logique d'évaluation.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.generation_approval_gate import (
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationApprovalResult,
    GenerationRequest,
    RealGenerationAuthorization,
)
from tests.authorization_content_helpers import bind_request, content_media
from agents.generation_job_service import GenerationJobOutcome, GenerationJobService
from agents.quality_evaluator import QualityDecision, QualityEvaluator
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.types import Job, JobStatus, VideoResult


def _fake_outcome(
    request_id="req-1",
    job_type="seedance_2_0",
    job_status=JobStatus.SUCCEEDED,
    output_urls=("mock://output/req-1.mp4",),
) -> GenerationJobOutcome:
    approval = GenerationApprovalResult(
        decision=GenerationApprovalDecision.APPROVED,
        request_id=request_id,
        job_type=job_type,
    )
    job = Job(job_id="job-1", job_type=job_type, status=JobStatus.QUEUED)
    result = VideoResult(job_id="job-1", status=job_status, output_urls=output_urls)

    return GenerationJobOutcome(
        request_id=request_id,
        job_type=job_type,
        approval=approval,
        job=job,
        result=result,
    )


class TestQualityEvaluatorPassEndToEnd(unittest.TestCase):
    """PASS — via la chaîne complète Phase E/G/H (MockHiggsfieldProvider)."""

    def test_successful_pipeline_run_passes_quality_evaluation(self):
        provider = MockHiggsfieldProvider(
            cost_per_job=10.0, available_credits=100.0, succeed_after_polls=2
        )
        gate = GenerationApprovalGate(provider)
        job_service = GenerationJobService(provider, gate)
        evaluator = QualityEvaluator()

        request = bind_request(GenerationRequest(
            **content_media(),
            request_id="req-e2e",
            job_type="seedance_2_0",
            prompt="prompt de test",
            duration=5,
            resolution="720p",
            aspect_ratio="9:16",
            approved=True,
            # Phase P2.11 : deuxième verrou requis en plus d'`approved`.
            real_generation_authorization=RealGenerationAuthorization(
                request_id="req-e2e",
                authorized_by_human=True,
            ),
        ))

        outcome = job_service.execute(request, interval_seconds=0)
        evaluation = evaluator.evaluate(outcome)

        self.assertEqual(evaluation.decision, QualityDecision.PASS)
        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.request_id, "req-e2e")
        self.assertEqual(evaluation.job_id, outcome.job.job_id)


class TestQualityEvaluatorFail(unittest.TestCase):

    def test_failed_job_status_results_in_fail(self):
        outcome = _fake_outcome(job_status=JobStatus.FAILED, output_urls=())
        evaluation = QualityEvaluator().evaluate(outcome)

        self.assertEqual(evaluation.decision, QualityDecision.FAIL)
        self.assertFalse(evaluation.passed)

    def test_canceled_job_status_results_in_fail(self):
        outcome = _fake_outcome(job_status=JobStatus.CANCELED, output_urls=())
        evaluation = QualityEvaluator().evaluate(outcome)

        self.assertEqual(evaluation.decision, QualityDecision.FAIL)

    def test_succeeded_status_without_output_url_is_treated_as_fail(self):
        # État incohérent : ne doit jamais être traité comme un succès.
        outcome = _fake_outcome(job_status=JobStatus.SUCCEEDED, output_urls=())
        evaluation = QualityEvaluator().evaluate(outcome)

        self.assertEqual(evaluation.decision, QualityDecision.FAIL)
        self.assertIn("no output URL", evaluation.reasons[0])


class TestQualityEvaluatorRetryRecommended(unittest.TestCase):

    def test_non_terminal_status_recommends_retry(self):
        for status in (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.UNKNOWN):
            with self.subTest(status=status):
                outcome = _fake_outcome(job_status=status, output_urls=())
                evaluation = QualityEvaluator().evaluate(outcome)

                self.assertEqual(evaluation.decision, QualityDecision.RETRY_RECOMMENDED)
                self.assertFalse(evaluation.passed)


class TestQualityEvaluatorNoFabrication(unittest.TestCase):
    """Ne jamais inventer de métadonnées vidéo — vérification structurelle."""

    def test_result_never_contains_duration_or_resolution_fields(self):
        outcome = _fake_outcome()
        evaluation = QualityEvaluator().evaluate(outcome)

        result_fields = vars(evaluation).keys()
        self.assertNotIn("duration", result_fields)
        self.assertNotIn("resolution", result_fields)

    def test_module_has_no_cli_or_network_dependency(self):
        import inspect

        import agents.quality_evaluator as module

        imported_names = {
            name
            for name, value in vars(module).items()
            if inspect.ismodule(value) or inspect.isclass(value)
        }

        self.assertNotIn("HiggsfieldClient", imported_names)
        self.assertFalse(hasattr(module, "subprocess"))
        self.assertFalse(hasattr(module, "requests"))
        self.assertFalse(hasattr(module, "socket"))


if __name__ == "__main__":
    unittest.main()
