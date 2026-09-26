"""
Tests — PublishingAgent v1.0 (Phase P3.8).

Fully offline: no network, no Higgsfield, no social platform, no OAuth,
no credential of any kind is imported or constructed anywhere in this
file.
"""

import ast
import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.content_agent import (
    ContentAgent,
    ContentAgentInput,
    compute_content_artifact_hash,
    compute_script_artifact_hash,
)
from agents.publishing_agent import (
    AGENT_VERSION,
    CONTRACT_VERSION,
    PUBLICATION_ARTIFACT_TYPE,
    DeterministicPublishingEngine,
    PublicationItem,
    PublicationItemStatus,
    PublicationPreparationContext,
    PublicationPreparationResult,
    PublicationProfile,
    PublishingAgent,
    PublishingAgentInput,
    PublishingAgentOutput,
    PublishingAgentStatus,
    PublishingEngine,
    compute_publication_artifact_hash,
    compute_publishing_idempotency_key,
)
from agents.quality_agent import QualityAgent, QualityAgentInput, QualityAgentStatus, compute_quality_artifact_hash
from agents.strategy_agent import StrategyAgent, StrategyAgentInput

PUBLISHING_AGENT_SOURCE_PATH = PROJECT_ROOT / "agents" / "publishing_agent.py"


def _valid_triplet(mission_id="mission-001"):
    strategy_output = StrategyAgent().run(
        StrategyAgentInput(
            mission_id=mission_id,
            objective="Explain why discipline beats talent over time.",
            platforms=("tiktok", "youtube"),
            topic="discipline vs talent",
            audience="young adults pursuing self-improvement",
        )
    )
    content_output = ContentAgent().run(
        ContentAgentInput(
            mission_id=mission_id,
            strategy_artifact=strategy_output.strategy_artifact,
            language_override="en",
        )
    )
    quality_output = QualityAgent().run(
        QualityAgentInput(
            mission_id=mission_id,
            content_artifact=content_output.content_artifact,
            script_artifact=content_output.script_artifact,
        )
    )
    assert quality_output.status == QualityAgentStatus.PASS
    return content_output.content_artifact, content_output.script_artifact, quality_output.quality_artifact


def _valid_input(**overrides):
    content_artifact, script_artifact, quality_artifact = _valid_triplet("mission-001")
    defaults = dict(
        mission_id="mission-001",
        content_artifact=content_artifact,
        script_artifact=script_artifact,
        quality_artifact=quality_artifact,
    )
    defaults.update(overrides)
    return PublishingAgentInput(**defaults)


def _rebind_content(content_artifact, **field_overrides):
    """Tamper content_artifact fields and correctly recompute its own
    content_hash (never leaving a stale hash behind)."""

    tampered = replace(content_artifact, **field_overrides)
    new_hash = compute_content_artifact_hash(
        mission_id=tampered.mission_id,
        concept=tampered.concept,
        angle=tampered.angle,
        hook=tampered.hook,
        title=tampered.title,
        cta=tampered.cta,
        target_platforms=tampered.target_platforms,
        language=tampered.language,
        tone=tampered.tone,
        content_format=tampered.content_format,
        constraints=tampered.constraints,
        contract_version=tampered.contract_version,
        source_strategy_content_hash=tampered.source_strategy_content_hash,
    )
    return replace(tampered, content_hash=new_hash)


def _rebind_script(script_artifact, content_artifact, **field_overrides):
    tampered = replace(script_artifact, **field_overrides)
    new_hash = compute_script_artifact_hash(
        mission_id=tampered.mission_id,
        scenes=tampered.scenes,
        total_duration_target=tampered.total_duration_target,
        language=tampered.language,
        contract_version=tampered.contract_version,
        source_content_content_hash=content_artifact.content_hash,
    )
    return replace(tampered, content_hash=new_hash)


class PublishingAgentBehaviorTests(unittest.TestCase):
    """Tests 1-8 from the P3.8 mandatory list."""

    def test_valid_input_produces_prepared_output(self):
        output = PublishingAgent().run(_valid_input())
        self.assertIn(
            output.status,
            (PublishingAgentStatus.PREPARED, PublishingAgentStatus.PREPARATION_WARNING),
        )
        self.assertIsNotNone(output.publication_artifact)

    def test_missing_content_artifact_is_rejected(self):
        output = PublishingAgent().run(_valid_input(content_artifact=None))
        self.assertEqual(output.status, PublishingAgentStatus.REJECTED)
        self.assertIsNone(output.publication_artifact)

    def test_missing_script_artifact_is_rejected(self):
        output = PublishingAgent().run(_valid_input(script_artifact=None))
        self.assertEqual(output.status, PublishingAgentStatus.REJECTED)

    def test_missing_quality_artifact_is_rejected(self):
        output = PublishingAgent().run(_valid_input(quality_artifact=None))
        self.assertEqual(output.status, PublishingAgentStatus.REJECTED)

    def test_wrong_mission_content_is_rejected(self):
        content_a, script_a, quality_a = _valid_triplet("mission-A")
        _, _, quality_b = _valid_triplet("mission-B")
        output = PublishingAgent().run(
            PublishingAgentInput(
                mission_id="mission-A",
                content_artifact=content_a,
                script_artifact=script_a,
                quality_artifact=quality_b,
            )
        )
        self.assertEqual(output.status, PublishingAgentStatus.REJECTED)

    def test_wrong_mission_script_is_rejected(self):
        content_a, script_a, quality_a = _valid_triplet("mission-A")
        _, script_other, _ = _valid_triplet("mission-OTHER")
        output = PublishingAgent().run(
            PublishingAgentInput(
                mission_id="mission-A",
                content_artifact=content_a,
                script_artifact=script_other,
                quality_artifact=quality_a,
            )
        )
        self.assertEqual(output.status, PublishingAgentStatus.REJECTED)

    def test_wrong_mission_quality_is_rejected(self):
        content_a, script_a, _ = _valid_triplet("mission-A")
        _, _, quality_other = _valid_triplet("mission-OTHER")
        output = PublishingAgent().run(
            PublishingAgentInput(
                mission_id="mission-A",
                content_artifact=content_a,
                script_artifact=script_a,
                quality_artifact=quality_other,
            )
        )
        self.assertEqual(output.status, PublishingAgentStatus.REJECTED)

    def test_wrong_artifact_types_is_rejected(self):
        content_artifact, script_artifact, quality_artifact = _valid_triplet("mission-001")
        tampered_content = _rebind_content(content_artifact, artifact_type="NotAContentArtifact")
        output = PublishingAgent().run(
            _valid_input(content_artifact=tampered_content, script_artifact=script_artifact, quality_artifact=quality_artifact)
        )
        self.assertEqual(output.status, PublishingAgentStatus.REJECTED)
        self.assertTrue(any("artifact_type" in reason for reason in output.errors))


class PublishingAgentIntegrityTests(unittest.TestCase):
    """Tests 9-11 from the P3.8 mandatory list."""

    def test_content_integrity_failure(self):
        content_artifact, script_artifact, quality_artifact = _valid_triplet("mission-001")
        tampered = replace(content_artifact, hook="a tampered hook, hash left stale")
        output = PublishingAgent().run(
            _valid_input(content_artifact=tampered, script_artifact=script_artifact, quality_artifact=quality_artifact)
        )
        self.assertEqual(output.status, PublishingAgentStatus.INTEGRITY_FAILURE)
        self.assertIsNotNone(output.publication_artifact)
        self.assertEqual(output.publication_artifact.publication_items, ())

    def test_script_integrity_failure(self):
        content_artifact, script_artifact, quality_artifact = _valid_triplet("mission-001")
        tampered = replace(script_artifact, total_duration_target=999999)
        output = PublishingAgent().run(
            _valid_input(content_artifact=content_artifact, script_artifact=tampered, quality_artifact=quality_artifact)
        )
        self.assertEqual(output.status, PublishingAgentStatus.INTEGRITY_FAILURE)

    def test_quality_integrity_failure(self):
        content_artifact, script_artifact, quality_artifact = _valid_triplet("mission-001")
        tampered_quality = replace(quality_artifact, score=1)
        output = PublishingAgent().run(
            _valid_input(content_artifact=content_artifact, script_artifact=script_artifact, quality_artifact=tampered_quality)
        )
        self.assertEqual(output.status, PublishingAgentStatus.INTEGRITY_FAILURE)


class PublishingAgentQualityGateTests(unittest.TestCase):
    """Tests 12-16 from the P3.8 mandatory list."""

    def test_quality_pass_permits_preparation(self):
        output = PublishingAgent().run(_valid_input())
        self.assertNotEqual(output.status, PublishingAgentStatus.QUALITY_REJECTED)

    def test_quality_pass_with_warnings_permits_preparation(self):
        content_artifact, script_artifact, quality_artifact = _valid_triplet("mission-001")
        # Force a PASS_WITH_WARNINGS quality artifact via a genuine
        # QualityAgent re-evaluation against a tone that fails the
        # "consistency" dimension (WARNING severity).
        tampered_content = _rebind_content(content_artifact, tone="an_unlisted_tone")
        rebound_script = _rebind_script(script_artifact, tampered_content)
        quality_output = QualityAgent().run(
            QualityAgentInput(mission_id="mission-001", content_artifact=tampered_content, script_artifact=rebound_script)
        )
        self.assertEqual(quality_output.status, QualityAgentStatus.PASS_WITH_WARNINGS)

        output = PublishingAgent().run(
            PublishingAgentInput(
                mission_id="mission-001",
                content_artifact=tampered_content,
                script_artifact=rebound_script,
                quality_artifact=quality_output.quality_artifact,
            )
        )
        self.assertEqual(output.status, PublishingAgentStatus.PREPARATION_WARNING)
        self.assertIsNotNone(output.publication_artifact)

    def test_quality_fail_is_rejected(self):
        content_artifact, script_artifact, _ = _valid_triplet("mission-001")
        empty_script = replace(script_artifact, scenes=())
        rebound_empty_script = _rebind_script(empty_script, content_artifact)
        quality_output = QualityAgent().run(
            QualityAgentInput(mission_id="mission-001", content_artifact=content_artifact, script_artifact=rebound_empty_script)
        )
        self.assertEqual(quality_output.status, QualityAgentStatus.FAIL)

        output = PublishingAgent().run(
            PublishingAgentInput(
                mission_id="mission-001",
                content_artifact=content_artifact,
                script_artifact=rebound_empty_script,
                quality_artifact=quality_output.quality_artifact,
            )
        )
        self.assertEqual(output.status, PublishingAgentStatus.QUALITY_REJECTED)
        self.assertIsNone(output.publication_artifact)

    def test_quality_integrity_failure_status_is_rejected(self):
        content_artifact, script_artifact, _ = _valid_triplet("mission-001")
        tampered_content_for_quality = replace(content_artifact, hook="tampered for quality integrity")
        quality_output = QualityAgent().run(
            QualityAgentInput(mission_id="mission-001", content_artifact=tampered_content_for_quality, script_artifact=script_artifact)
        )
        self.assertEqual(quality_output.status, QualityAgentStatus.INTEGRITY_FAILURE)

        # Rebind content/script hashes so PUBLISHING's own integrity check
        # passes, isolating the QUALITY_REJECTED behavior being tested.
        rebound_content = _rebind_content(content_artifact)
        rebound_script = _rebind_script(script_artifact, rebound_content)
        output = PublishingAgent().run(
            PublishingAgentInput(
                mission_id="mission-001",
                content_artifact=rebound_content,
                script_artifact=rebound_script,
                quality_artifact=quality_output.quality_artifact,
            )
        )
        self.assertEqual(output.status, PublishingAgentStatus.QUALITY_REJECTED)

    def test_quality_rejected_status_is_rejected(self):
        # Simulate a QualityAgentStatus.REJECTED-shaped quality_artifact by
        # directly testing the gate logic's allow-list, since QualityAgent
        # itself never PRODUCES an artifact for REJECTED (no artifact to
        # pass through) -- confirm structurally that REJECTED is excluded.
        from agents.publishing_agent import QUALITY_STATUSES_PERMITTING_PREPARATION

        self.assertNotIn(QualityAgentStatus.REJECTED, QUALITY_STATUSES_PERMITTING_PREPARATION)
        self.assertNotIn(QualityAgentStatus.FAIL, QUALITY_STATUSES_PERMITTING_PREPARATION)
        self.assertNotIn(QualityAgentStatus.INTEGRITY_FAILURE, QUALITY_STATUSES_PERMITTING_PREPARATION)
        self.assertEqual(
            QUALITY_STATUSES_PERMITTING_PREPARATION,
            {QualityAgentStatus.PASS, QualityAgentStatus.PASS_WITH_WARNINGS},
        )

    def test_quality_pass_does_not_authorize_publication(self):
        """The single most important test in this suite: PASS means
        'preparation may proceed', never 'publication is authorized'."""

        output = PublishingAgent().run(_valid_input())
        self.assertIsNotNone(output.publication_artifact)
        self.assertFalse(hasattr(output.publication_artifact, "publication_authorized"))
        self.assertFalse(hasattr(output.publication_artifact, "published"))
        self.assertFalse(hasattr(output, "publication_authorization"))
        # The artifact's own publication_status is never the string
        # "PUBLISHED" -- that value does not even exist in the enum.
        self.assertNotIn("PUBLISHED", [s.value for s in PublishingAgentStatus])


class PublishingAgentPlatformTests(unittest.TestCase):
    """Tests 17-20 from the P3.8 mandatory list."""

    def test_platform_preservation_without_override(self):
        content_artifact, script_artifact, quality_artifact = _valid_triplet("mission-001")
        output = PublishingAgent().run(
            _valid_input(content_artifact=content_artifact, script_artifact=script_artifact, quality_artifact=quality_artifact)
        )
        self.assertEqual(output.publication_artifact.platforms, content_artifact.target_platforms)

    def test_invalid_platform_override_is_validation_error(self):
        output = PublishingAgent().run(_valid_input(platform_override=("myspace",)))
        self.assertEqual(output.status, PublishingAgentStatus.VALIDATION_ERROR)

    def test_valid_platform_override_is_used_and_traced(self):
        output = PublishingAgent().run(_valid_input(platform_override=("instagram",)))
        self.assertIn(output.status, (PublishingAgentStatus.PREPARED, PublishingAgentStatus.PREPARATION_WARNING))
        self.assertEqual(output.publication_artifact.platforms, ("instagram",))

    def test_override_cannot_bypass_quality_rejection(self):
        content_artifact, script_artifact, _ = _valid_triplet("mission-001")
        empty_script = replace(script_artifact, scenes=())
        rebound_empty_script = _rebind_script(empty_script, content_artifact)
        quality_output = QualityAgent().run(
            QualityAgentInput(mission_id="mission-001", content_artifact=content_artifact, script_artifact=rebound_empty_script)
        )
        self.assertEqual(quality_output.status, QualityAgentStatus.FAIL)

        output = PublishingAgent().run(
            PublishingAgentInput(
                mission_id="mission-001",
                content_artifact=content_artifact,
                script_artifact=rebound_empty_script,
                quality_artifact=quality_output.quality_artifact,
                platform_override=("instagram",),
            )
        )
        # A platform override must never turn a FAIL into a preparable state.
        self.assertEqual(output.status, PublishingAgentStatus.QUALITY_REJECTED)
        self.assertIsNone(output.publication_artifact)


class PublishingAgentDerivationTests(unittest.TestCase):
    """Tests 21-25 from the P3.8 mandatory list."""

    def test_title_derivation(self):
        content_artifact, script_artifact, quality_artifact = _valid_triplet("mission-001")
        output = PublishingAgent().run(
            _valid_input(content_artifact=content_artifact, script_artifact=script_artifact, quality_artifact=quality_artifact)
        )
        for item in output.publication_artifact.publication_items:
            self.assertEqual(item.title, content_artifact.title)

    def test_caption_derivation(self):
        content_artifact, script_artifact, quality_artifact = _valid_triplet("mission-001")
        output = PublishingAgent().run(
            _valid_input(content_artifact=content_artifact, script_artifact=script_artifact, quality_artifact=quality_artifact)
        )
        for item in output.publication_artifact.publication_items:
            self.assertEqual(item.caption, content_artifact.hook)

    def test_description_derivation(self):
        content_artifact, script_artifact, quality_artifact = _valid_triplet("mission-001")
        output = PublishingAgent().run(
            _valid_input(content_artifact=content_artifact, script_artifact=script_artifact, quality_artifact=quality_artifact)
        )
        for item in output.publication_artifact.publication_items:
            self.assertEqual(item.description, content_artifact.concept)

    def test_deterministic_hashtags(self):
        content_artifact, script_artifact, quality_artifact = _valid_triplet("mission-001")
        agent = PublishingAgent()
        first = agent.run(_valid_input(content_artifact=content_artifact, script_artifact=script_artifact, quality_artifact=quality_artifact))
        second = agent.run(_valid_input(content_artifact=content_artifact, script_artifact=script_artifact, quality_artifact=quality_artifact))
        self.assertEqual(
            [item.hashtags for item in first.publication_artifact.publication_items],
            [item.hashtags for item in second.publication_artifact.publication_items],
        )
        for item in first.publication_artifact.publication_items:
            self.assertIn(f"#{content_artifact.tone}", item.hashtags)
            self.assertIn(f"#{content_artifact.content_format}", item.hashtags)
            self.assertIn(f"#{item.platform}", item.hashtags)

    def test_media_reference(self):
        content_artifact, script_artifact, quality_artifact = _valid_triplet("mission-001")
        output = PublishingAgent().run(
            _valid_input(content_artifact=content_artifact, script_artifact=script_artifact, quality_artifact=quality_artifact)
        )
        ref = output.publication_artifact.media_reference
        self.assertEqual(ref.artifact_id, script_artifact.artifact_id)
        self.assertEqual(ref.content_hash, script_artifact.content_hash)
        self.assertEqual(ref.reference_type, "script_artifact")


class PublishingAgentScheduleTests(unittest.TestCase):
    """Tests 26-28 from the P3.8 mandatory list."""

    def test_schedule_present(self):
        output = PublishingAgent().run(
            _valid_input(scheduled_at="2026-01-01T12:00:00", timezone="UTC")
        )
        self.assertEqual(output.publication_artifact.schedule.schedule_status, "SCHEDULED")
        self.assertEqual(output.publication_artifact.schedule.scheduled_at, "2026-01-01T12:00:00")
        self.assertEqual(output.publication_artifact.schedule.timezone, "UTC")

    def test_schedule_absent(self):
        output = PublishingAgent().run(_valid_input())
        self.assertEqual(output.publication_artifact.schedule.schedule_status, "NOT_SCHEDULED")
        self.assertIsNone(output.publication_artifact.schedule.scheduled_at)

    def test_invalid_timezone_is_validation_error(self):
        output = PublishingAgent().run(
            _valid_input(scheduled_at="2026-01-01T12:00:00", timezone="Mars/OlympusMons")
        )
        self.assertEqual(output.status, PublishingAgentStatus.VALIDATION_ERROR)

    def test_invalid_scheduled_at_format_is_validation_error(self):
        output = PublishingAgent().run(
            _valid_input(scheduled_at="not-a-date", timezone="UTC")
        )
        self.assertEqual(output.status, PublishingAgentStatus.VALIDATION_ERROR)

    def test_scheduled_at_without_timezone_is_validation_error(self):
        output = PublishingAgent().run(_valid_input(scheduled_at="2026-01-01T12:00:00"))
        self.assertEqual(output.status, PublishingAgentStatus.VALIDATION_ERROR)


class PublishingAgentDeterminismTests(unittest.TestCase):
    """Tests 29-30 from the P3.8 mandatory list."""

    def test_deterministic_publication_output(self):
        content_artifact, script_artifact, quality_artifact = _valid_triplet("mission-001")
        agent = PublishingAgent()
        first = agent.run(_valid_input(content_artifact=content_artifact, script_artifact=script_artifact, quality_artifact=quality_artifact))
        second = agent.run(_valid_input(content_artifact=content_artifact, script_artifact=script_artifact, quality_artifact=quality_artifact))
        self.assertEqual(first.status, second.status)
        self.assertEqual(
            [(i.platform, i.title, i.caption, i.description, i.hashtags) for i in first.publication_artifact.publication_items],
            [(i.platform, i.title, i.caption, i.description, i.hashtags) for i in second.publication_artifact.publication_items],
        )

    def test_deterministic_publication_hash(self):
        content_artifact, script_artifact, quality_artifact = _valid_triplet("mission-001")
        agent = PublishingAgent()
        first = agent.run(_valid_input(content_artifact=content_artifact, script_artifact=script_artifact, quality_artifact=quality_artifact))
        second = agent.run(_valid_input(content_artifact=content_artifact, script_artifact=script_artifact, quality_artifact=quality_artifact))
        self.assertEqual(first.publication_artifact.content_hash, second.publication_artifact.content_hash)


class PublishingAgentImmutabilityTests(unittest.TestCase):
    """Tests 31-32 from the P3.8 mandatory list."""

    def test_immutable_source_artifacts(self):
        content_artifact, script_artifact, quality_artifact = _valid_triplet("mission-001")
        content_before = replace(content_artifact)
        script_before = replace(script_artifact)
        quality_before = replace(quality_artifact)

        PublishingAgent().run(
            _valid_input(content_artifact=content_artifact, script_artifact=script_artifact, quality_artifact=quality_artifact)
        )

        self.assertEqual(content_artifact, content_before)
        self.assertEqual(script_artifact, script_before)
        self.assertEqual(quality_artifact, quality_before)

    def test_immutable_publication_artifact(self):
        output = PublishingAgent().run(_valid_input())
        with self.assertRaises(FrozenInstanceError):
            output.publication_artifact.platforms = ()
        with self.assertRaises(FrozenInstanceError):
            output.publication_artifact.publication_items[0].title = "tampered"


class PublishingAgentMetadataTests(unittest.TestCase):
    """Tests 33-36 from the P3.8 mandatory list."""

    def test_version_metadata(self):
        output = PublishingAgent().run(_valid_input())
        self.assertEqual(output.publication_artifact.artifact_type, PUBLICATION_ARTIFACT_TYPE)
        self.assertEqual(output.publication_artifact.version, 1)

    def test_producer_metadata(self):
        output = PublishingAgent().run(_valid_input())
        self.assertEqual(output.producer_agent, "publishing-agent")
        self.assertEqual(output.producer_version, AGENT_VERSION)
        self.assertEqual(output.publication_artifact.producer_agent, "publishing-agent")

    def test_contract_version(self):
        output = PublishingAgent().run(_valid_input())
        self.assertEqual(output.contract_version, CONTRACT_VERSION)
        self.assertEqual(output.publication_artifact.contract_version, CONTRACT_VERSION)

    def test_traceability(self):
        content_artifact, script_artifact, quality_artifact = _valid_triplet("mission-001")
        output = PublishingAgent().run(
            _valid_input(content_artifact=content_artifact, script_artifact=script_artifact, quality_artifact=quality_artifact)
        )
        refs = {ref.artifact_id: ref for ref in output.publication_artifact.evaluated_artifacts}
        self.assertEqual(refs[content_artifact.artifact_id].content_hash, content_artifact.content_hash)
        self.assertEqual(refs[script_artifact.artifact_id].content_hash, script_artifact.content_hash)
        self.assertEqual(refs[quality_artifact.artifact_id].content_hash, quality_artifact.content_hash)


class PublishingAgentIdempotencyTests(unittest.TestCase):
    """Tests 37-38 from the P3.8 mandatory list."""

    def test_idempotency_same_input(self):
        content_artifact, script_artifact, quality_artifact = _valid_triplet("mission-001")
        k1 = compute_publishing_idempotency_key(
            _valid_input(content_artifact=content_artifact, script_artifact=script_artifact, quality_artifact=quality_artifact)
        )
        k2 = compute_publishing_idempotency_key(
            _valid_input(content_artifact=content_artifact, script_artifact=script_artifact, quality_artifact=quality_artifact)
        )
        self.assertEqual(k1, k2)

    def test_idempotency_changed_input(self):
        content_a, script_a, quality_a = _valid_triplet("mission-001")
        k1 = compute_publishing_idempotency_key(
            _valid_input(content_artifact=content_a, script_artifact=script_a, quality_artifact=quality_a)
        )
        k2 = compute_publishing_idempotency_key(
            _valid_input(content_artifact=content_a, script_artifact=script_a, quality_artifact=quality_a, platform_override=("instagram",))
        )
        self.assertNotEqual(k1, k2)


class FakePublishingEngine(PublishingEngine):
    """Test-only engine proving the PublishingEngine contract is
    substitutable (mandatory tests 39/40)."""

    def prepare(self, context: PublicationPreparationContext) -> PublicationPreparationResult:
        return PublicationPreparationResult(
            items=(
                PublicationItem(
                    platform="tiktok",
                    title="fake title",
                    caption="fake caption",
                    description="fake description",
                    hashtags=("#fake",),
                    language="en",
                    content_format="short_video",
                    status=PublicationItemStatus.PREPARED,
                ),
            ),
            warnings=("fake engine used",),
        )


class PublishingAgentEngineTests(unittest.TestCase):
    def test_fake_engine_compatibility(self):
        agent = PublishingAgent(engine=FakePublishingEngine())
        output = agent.run(_valid_input())
        self.assertEqual(output.status, PublishingAgentStatus.PREPARATION_WARNING)
        self.assertEqual(len(output.publication_artifact.publication_items), 1)
        self.assertEqual(output.publication_artifact.publication_items[0].title, "fake title")
        self.assertIn("fake engine used", output.warnings)

    def test_default_engine_is_deterministic_engine(self):
        agent = PublishingAgent()
        self.assertIsInstance(agent.engine, DeterministicPublishingEngine)


class PublishingAgentAuthorityBoundaryTests(unittest.TestCase):
    """Test 41 from the P3.8 mandatory list."""

    def test_mission_state_unchanged(self):
        output = PublishingAgent().run(_valid_input())
        self.assertFalse(hasattr(output, "current_state"))
        self.assertFalse(hasattr(output.publication_artifact, "current_state"))

    def test_no_event_bus(self):
        agent = PublishingAgent()
        self.assertFalse(hasattr(agent, "event_bus"))
        self.assertFalse(hasattr(agent, "emit"))
        self.assertFalse(hasattr(agent, "publish"))
        self.assertFalse(hasattr(agent, "subscribe"))


class PublishingAgentSecurityTests(unittest.TestCase):
    """
    Tests 43-50 from the P3.8 mandatory list: static (AST) verification
    that agents/publishing_agent.py cannot reach any social platform,
    HTTP client, subprocess, OS command, credential, OAuth flow,
    Higgsfield, or P2 authority mechanism -- checked structurally, never
    a naive substring scan.
    """

    FORBIDDEN_MODULES = {
        "integrations.higgsfield.client",
        "integrations.higgsfield.provider",
        "integrations.higgsfield.mock_provider",
        "director",
        "agents.generation_approval_gate",
        "agents.generation_job_service",
        "agents.activation_contract",
        "agents.controlled_real_provider_activation",
        "agents.real_provider_execution_gate",
        "agents.real_provider_activation_preflight",
        "agents.critical_section_lock",
        "agents.executed_request_store",
        "agents.video_agent",
        "agents.final_report_service",
        "subprocess",
        "socket",
        "urllib",
        "http",
        "http.client",
        "requests",
        "aiohttp",
        "httpx",
        "os",
        "webbrowser",
        "oauthlib",
        "requests_oauthlib",
    }

    FORBIDDEN_CALL_NAMES = {
        "create_job",
        "system",
        "popen",
        "Popen",
        "post",
        "get",
        "upload",
        "connect",
        "socket",
    }

    @classmethod
    def setUpClass(cls):
        cls.source = PUBLISHING_AGENT_SOURCE_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def _called_names(self):
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    names.add(func.id)
                elif isinstance(func, ast.Attribute):
                    names.add(func.attr)
        return names

    def _imported_modules(self):
        modules = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.add(node.module)
        return modules

    def test_no_forbidden_module_imports(self):
        offenders = self._imported_modules() & self.FORBIDDEN_MODULES
        self.assertFalse(
            offenders,
            f"agents/publishing_agent.py imports forbidden module(s): {offenders}",
        )

    def test_no_network_or_social_calls(self):
        # `post`/`get`/`upload`/`connect` are broad names that COULD
        # appear legitimately (e.g. a dict .get()) -- verify none of the
        # ACTUAL call targets in this file match them at all, which is
        # true only because this module never calls any object that
        # exposes such a method (no requests/session/client object
        # exists anywhere in this file to call .get()/.post() on).
        offenders = self._called_names() & self.FORBIDDEN_CALL_NAMES
        self.assertFalse(
            offenders,
            f"agents/publishing_agent.py contains forbidden call(s): {offenders}",
        )

    def test_no_create_job_call(self):
        self.assertNotIn("create_job", self._called_names())

    def test_no_authorization_construction(self):
        self.assertNotIn("RealGenerationAuthorization", self._called_names())

    def test_no_activation_construction(self):
        called = self._called_names()
        self.assertFalse(
            {n for n in called if "ActivationContract" in n or "ControlledRealProviderActivation" in n}
        )

    def test_no_provider_dependency(self):
        self.assertNotIn("HiggsfieldProvider", self.source)
        self.assertNotIn("HiggsfieldClient", self.source)

    def _non_docstring_identifiers_and_literals(self):
        """
        Collects every identifier name (Name/Attribute/arg/function/class)
        PLUS every string constant that is NOT a docstring (module, class,
        or function docstrings are excluded) -- so prose in this module's
        own extensive docstrings explaining what it deliberately does NOT
        do (which legitimately names things like "OAuth"/"credential") can
        never cause a false positive, while actual code identifiers or
        non-docstring string literals still would.
        """

        docstring_nodes = set()
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if (
                    node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)
                ):
                    docstring_nodes.add(id(node.body[0].value))

        texts = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name):
                texts.append(node.id)
            elif isinstance(node, ast.Attribute):
                texts.append(node.attr)
            elif isinstance(node, ast.arg):
                texts.append(node.arg)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                texts.append(node.name)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) not in docstring_nodes:
                    texts.append(node.value)

        return texts

    def test_no_credential_oauth_or_token_handling(self):
        texts = self._non_docstring_identifiers_and_literals()
        for token in ("api_key", "apikey", "password", "secret", "oauth", "credential", "access_token", "bearer"):
            offenders = [t for t in texts if token in t.lower()]
            self.assertFalse(
                offenders,
                f"Found credential/OAuth-like identifier or non-docstring "
                f"literal containing '{token}': {offenders}",
            )

    def test_no_network_related_substrings_at_all(self):
        for banned_substring in (
            "requests.",
            "urllib.",
            "socket.",
            "http.client",
            "subprocess.",
            "os.system",
            "aiohttp.",
            "httpx.",
        ):
            self.assertNotIn(banned_substring, self.source)

    def test_publish_word_usage_is_documentary_only(self):
        """
        Confirms Section 42's explicit instruction: the word "publish"
        appearing in this file (module name, docstrings, class/field
        names like `publication_status`) is never an actual OUTBOUND
        call to something external. Verified by AST: every "publish"-
        containing name ever called in this file is a name DEFINED in
        this very module (a class or function this file itself declares)
        -- i.e. in-process construction/orchestration, never a call into
        an external client/SDK/library that this file did not define.
        """

        locally_defined_names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                locally_defined_names.add(node.name)

        suspicious_calls = {
            name for name in self._called_names() if "publish" in name.lower()
        }
        undefined_elsewhere = suspicious_calls - locally_defined_names
        self.assertFalse(
            undefined_elsewhere,
            f"Call(s) to a 'publish'-related name not defined in this "
            f"module (possible external call): {undefined_elsewhere}",
        )


if __name__ == "__main__":
    unittest.main()
