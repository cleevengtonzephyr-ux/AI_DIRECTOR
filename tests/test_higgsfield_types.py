"""
Tests — Types et erreurs Higgsfield (Phase B, MASTER PROMPT V2).

Tests purement structurels : aucun appel réseau ni CLI n'est possible
ici, ces modules ne contiennent que des définitions de données.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from integrations.higgsfield.errors import (
    HiggsfieldAuthenticationError,
    HiggsfieldCLINotFoundError,
    HiggsfieldCommandError,
    HiggsfieldError,
    HiggsfieldInvalidResponseError,
    HiggsfieldRealGenerationDisabledError,
    HiggsfieldTimeoutError,
)
from integrations.higgsfield.types import (
    Job,
    JobStatus,
    ModelParam,
    ModelSchema,
    VideoResult,
)


class TestHiggsfieldTypes(unittest.TestCase):

    def test_job_status_terminal_states(self):
        terminal = {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELED}
        non_terminal = {JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.UNKNOWN}

        for status in terminal:
            with self.subTest(status=status):
                self.assertTrue(status.is_terminal)

        for status in non_terminal:
            with self.subTest(status=status):
                self.assertFalse(status.is_terminal)

    def test_model_schema_param_lookup(self):
        schema = ModelSchema(
            job_type="seedance_2_0",
            display_name="Seedance 2.0",
            params=(ModelParam(name="prompt", type="string", required=True),),
        )

        self.assertIsNotNone(schema.param("prompt"))
        self.assertIsNone(schema.param("does_not_exist"))

    def test_video_result_succeeded_property(self):
        succeeded = VideoResult(job_id="j1", status=JobStatus.SUCCEEDED)
        failed = VideoResult(job_id="j2", status=JobStatus.FAILED)

        self.assertTrue(succeeded.succeeded)
        self.assertFalse(failed.succeeded)

    def test_all_higgsfield_errors_are_runtimeerror_subclasses(self):
        for error_cls in (
            HiggsfieldError,
            HiggsfieldCLINotFoundError,
            HiggsfieldAuthenticationError,
            HiggsfieldCommandError,
            HiggsfieldTimeoutError,
            HiggsfieldInvalidResponseError,
            HiggsfieldRealGenerationDisabledError,
        ):
            with self.subTest(error_cls=error_cls):
                self.assertTrue(issubclass(error_cls, RuntimeError))


if __name__ == "__main__":
    unittest.main()
