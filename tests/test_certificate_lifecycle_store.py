"""
Tests -- Certificate Lifecycle Persistence & Restart Recovery (Phase
P3.58).

Covers the mission's full test matrix (items 1-32). Every test uses
MockHiggsfieldProvider exclusively, and all files are created in a
temporary directory (never the real project); no real generation, no
real create_job(), no credits consumed.
"""

import ast
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.activation_contract import RequestScopedActivationService
from agents.activation_readiness import ActivationReadinessEvaluator
from agents.certificate_lifecycle import (
    CertificateLifecycleRecord,
    CertificateLifecycleRegistry,
    CertificateLifecycleStatus,
    certificate_scope,
)
from agents.certificate_lifecycle_store import (
    LIFECYCLE_STORAGE_VERSION,
    CertificateLifecycleStoreCorruptedError,
    FileCertificateLifecycleStore,
)
from agents.generation_approval_gate import GenerationApprovalGate, GenerationRequest, RealGenerationAuthorization
from agents.production_activation_readiness_certificate import ProductionActivationReadinessCertificateIssuer
from agents.release_candidate_identity_lock import ReleaseCandidateIdentityLock, VIDEO_005_RELEASE_CANDIDATE
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from integrations.higgsfield.types import MediaReference

C = VIDEO_005_RELEASE_CANDIDATE
REAL_AVATAR_PATH = PROJECT_ROOT / "assets" / "zephyr" / "avatar" / "avatar_master.png"
REAL_FACE_PATH = PROJECT_ROOT / "assets" / "zephyr" / "references" / "mon avatar habille.png"


def _real_prompt() -> str:
    from agents.prompt_assembly_system import PromptAssemblySystem

    return PromptAssemblySystem(PROJECT_ROOT).assemble(C.request_id)


def _conforming_request(**overrides) -> GenerationRequest:
    defaults = dict(
        request_id=C.request_id, job_type=C.job_type, prompt=_real_prompt(),
        duration=C.duration, resolution=C.resolution, aspect_ratio=C.aspect_ratio,
        approved=True,
        start_image=MediaReference(role="master_avatar", source=str(REAL_AVATAR_PATH), sha256=None),
        image_references=(MediaReference(role="face_reference", source=str(REAL_FACE_PATH), sha256=None),),
        real_generation_authorization=RealGenerationAuthorization(request_id=C.request_id, authorized_by_human=True),
    )
    defaults.update(overrides)
    return GenerationRequest(**defaults)


def _issuer(available_credits=1000.0):
    provider = MockHiggsfieldProvider(cost_per_job=10.0, available_credits=available_credits)
    identity_lock = ReleaseCandidateIdentityLock(C)
    gate = GenerationApprovalGate(provider, identity_lock=identity_lock)
    activation_service = RequestScopedActivationService(gate, identity_lock)
    evaluator = ActivationReadinessEvaluator(gate, identity_lock, activation_service)
    return ProductionActivationReadinessCertificateIssuer(evaluator), gate


def _cert(issuer, mission_id="mission-A", request_id=None):
    request = _conforming_request(**({"request_id": request_id} if request_id else {}))
    return issuer.issue(request, mission_id=mission_id, video_plan_identity="plan-v1")


class _FileStoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.state_path = Path(self._tmpdir.name) / "state" / "certificate_lifecycle.json"

    def _store(self) -> FileCertificateLifecycleStore:
        return FileCertificateLifecycleStore(self.state_path)

    def _write_raw(self, obj) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(obj), encoding="utf-8")


# 1 -- initial empty state --------------------------------------------


class Test01_InitialEmptyState(_FileStoreTestCase):
    def test_missing_file_loads_as_empty_not_corrupted(self):
        records, current_by_scope, sequence = self._store().load()
        self.assertEqual(records, {})
        self.assertEqual(current_by_scope, {})
        self.assertEqual(sequence, 0)


# 2 -- first persistence ------------------------------------------------


class Test02_FirstPersistence(_FileStoreTestCase):
    def test_first_registration_creates_a_valid_file(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry(store=self._store())
        c1 = _cert(issuer)
        registry.register(c1)
        self.assertTrue(self.state_path.exists())
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(data["lifecycle_storage_version"], LIFECYCLE_STORAGE_VERSION)
        self.assertIn(c1.certificate_id, data["records"])


# 3 -- reload current -----------------------------------------------------


class Test03_ReloadCurrent(_FileStoreTestCase):
    def test_reload_restores_current(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry(store=self._store())
        c1 = _cert(issuer)
        registry.register(c1)

        new_registry = CertificateLifecycleRegistry(store=self._store())
        new_registry.hydrate_from_store()
        self.assertEqual(new_registry.status_of(c1.certificate_id), CertificateLifecycleStatus.CURRENT)
        record = new_registry.current_record_for(certificate_scope(c1))
        self.assertEqual(record.certificate_id, c1.certificate_id)


# 4 -- reload superseded history -------------------------------------------


class Test04_ReloadSupersededHistory(_FileStoreTestCase):
    def test_reload_restores_superseded_and_current(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry(store=self._store())
        c1 = _cert(issuer)
        c2 = _cert(issuer)
        registry.register(c1)
        registry.register(c2)

        new_registry = CertificateLifecycleRegistry(store=self._store())
        new_registry.hydrate_from_store()
        self.assertEqual(new_registry.status_of(c1.certificate_id), CertificateLifecycleStatus.SUPERSEDED)
        self.assertEqual(new_registry.status_of(c2.certificate_id), CertificateLifecycleStatus.CURRENT)
        record_1 = new_registry.record_for(c1.certificate_id)
        self.assertEqual(record_1.superseded_by, c2.certificate_id)


# 5/6 -- multiple requests / multiple missions -----------------------------


class Test05_06_MultipleRequestsMissions(_FileStoreTestCase):
    def test_multiple_requests_isolated_after_reload(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry(store=self._store())
        c1 = issuer.issue(_conforming_request(), mission_id="mission-A", video_plan_identity="plan-v1")
        c2 = issuer.issue(_conforming_request(request_id="not-005"), mission_id="mission-A", video_plan_identity="plan-v1")
        registry.register(c1)
        registry.register(c2)

        new_registry = CertificateLifecycleRegistry(store=self._store())
        new_registry.hydrate_from_store()
        self.assertEqual(new_registry.status_of(c1.certificate_id), CertificateLifecycleStatus.CURRENT)
        self.assertEqual(new_registry.status_of(c2.certificate_id), CertificateLifecycleStatus.CURRENT)

    def test_multiple_missions_isolated_after_reload(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry(store=self._store())
        request = _conforming_request()
        c1 = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        c2 = issuer.issue(request, mission_id="mission-B", video_plan_identity="plan-v1")
        registry.register(c1)
        registry.register(c2)

        new_registry = CertificateLifecycleRegistry(store=self._store())
        new_registry.hydrate_from_store()
        self.assertEqual(new_registry.status_of(c1.certificate_id), CertificateLifecycleStatus.CURRENT)
        self.assertEqual(new_registry.status_of(c2.certificate_id), CertificateLifecycleStatus.CURRENT)


# 7/8/9 -- missing file / empty file / malformed JSON -----------------------


class Test07_08_09_FileCorruption(_FileStoreTestCase):
    def test_missing_file_is_not_corruption(self):
        records, current_by_scope, sequence = self._store().load()
        self.assertEqual((records, current_by_scope, sequence), ({}, {}, 0))

    def test_empty_file_is_corrupted(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text("", encoding="utf-8")
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()

    def test_malformed_json_is_corrupted(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text("{not valid json", encoding="utf-8")
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()


# 10 -- unknown schema version ----------------------------------------


class Test10_UnknownSchemaVersion(_FileStoreTestCase):
    def test_unknown_version_is_corrupted(self):
        self._write_raw({"lifecycle_storage_version": 999, "records": {}})
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()

    def test_missing_version_is_corrupted(self):
        self._write_raw({"records": {}})
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()


# 11/12 -- missing required field / wrong field type ----------------------


def _valid_record_dict(**overrides):
    base = dict(
        certificate_id="cert-1", request_id="005", mission_id="mission-A",
        status="CURRENT", superseded_by=None, sequence=1, issued_at="2026-01-01T00:00:00+00:00",
    )
    base.update(overrides)
    return base


class Test11_12_MissingFieldWrongType(_FileStoreTestCase):
    def test_missing_required_field_is_corrupted(self):
        raw = _valid_record_dict()
        del raw["issued_at"]
        self._write_raw({"lifecycle_storage_version": 1, "records": {"cert-1": raw}})
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()

    def test_wrong_field_type_is_corrupted(self):
        raw = _valid_record_dict(sequence="one")
        self._write_raw({"lifecycle_storage_version": 1, "records": {"cert-1": raw}})
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()

    def test_bool_for_sequence_is_corrupted(self):
        raw = _valid_record_dict(sequence=True)
        self._write_raw({"lifecycle_storage_version": 1, "records": {"cert-1": raw}})
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()


# 13 -- duplicate certificate ID ----------------------------------------


class Test13_DuplicateCertificateId(_FileStoreTestCase):
    def test_record_key_mismatch_with_its_own_certificate_id_is_corrupted(self):
        raw = _valid_record_dict(certificate_id="cert-OTHER")
        self._write_raw({"lifecycle_storage_version": 1, "records": {"cert-1": raw}})
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()

    def test_literal_duplicate_json_key_is_rejected(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        raw_text = (
            '{"lifecycle_storage_version": 1, "records": {'
            '"cert-1": {"certificate_id": "cert-1", "request_id": "005", '
            '"mission_id": null, "status": "CURRENT", "superseded_by": null, '
            '"sequence": 1, "issued_at": "x", "sequence": 2}}}'
        )
        self.state_path.write_text(raw_text, encoding="utf-8")
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()


# 14 -- duplicate CURRENT -------------------------------------------------


class Test14_DuplicateCurrent(_FileStoreTestCase):
    def test_two_current_records_same_scope_is_corrupted(self):
        raw_1 = _valid_record_dict(certificate_id="cert-1", sequence=1)
        raw_2 = _valid_record_dict(certificate_id="cert-2", sequence=2)
        self._write_raw({
            "lifecycle_storage_version": 1,
            "records": {"cert-1": raw_1, "cert-2": raw_2},
        })
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()


# 15 -- broken superseded_by -----------------------------------------------


class Test15_BrokenSupersededBy(_FileStoreTestCase):
    def test_superseded_by_pointing_nowhere_is_corrupted(self):
        raw = _valid_record_dict(status="SUPERSEDED", superseded_by="does-not-exist")
        self._write_raw({"lifecycle_storage_version": 1, "records": {"cert-1": raw}})
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()


# 16 -- sequence inconsistency ---------------------------------------------


class Test16_SequenceInconsistency(_FileStoreTestCase):
    def test_successor_with_lower_sequence_is_corrupted(self):
        raw_1 = _valid_record_dict(certificate_id="cert-1", status="SUPERSEDED", superseded_by="cert-2", sequence=5)
        raw_2 = _valid_record_dict(certificate_id="cert-2", status="CURRENT", superseded_by=None, sequence=1)
        self._write_raw({
            "lifecycle_storage_version": 1,
            "records": {"cert-1": raw_1, "cert-2": raw_2},
        })
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()

    def test_duplicate_sequence_is_corrupted(self):
        raw_1 = _valid_record_dict(certificate_id="cert-1", request_id="005", sequence=1)
        raw_2 = _valid_record_dict(certificate_id="cert-2", request_id="not-005", sequence=1)
        self._write_raw({
            "lifecycle_storage_version": 1,
            "records": {"cert-1": raw_1, "cert-2": raw_2},
        })
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()


# 17 -- request/mission inconsistency --------------------------------------


class Test17_RequestMissionInconsistency(_FileStoreTestCase):
    def test_cross_scope_supersession_is_corrupted(self):
        raw_1 = _valid_record_dict(
            certificate_id="cert-1", request_id="005", mission_id="mission-A",
            status="SUPERSEDED", superseded_by="cert-2", sequence=1,
        )
        raw_2 = _valid_record_dict(
            certificate_id="cert-2", request_id="005", mission_id="mission-B",
            status="CURRENT", superseded_by=None, sequence=2,
        )
        self._write_raw({
            "lifecycle_storage_version": 1,
            "records": {"cert-1": raw_1, "cert-2": raw_2},
        })
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()


# 18 -- invalid lifecycle status -------------------------------------------


class Test18_InvalidLifecycleStatus(_FileStoreTestCase):
    def test_unknown_status_value_is_corrupted(self):
        raw = _valid_record_dict(status="ACTIVE")
        self._write_raw({"lifecycle_storage_version": 1, "records": {"cert-1": raw}})
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()

    def test_current_with_superseded_by_set_is_corrupted(self):
        raw = _valid_record_dict(status="CURRENT", superseded_by="cert-2")
        self._write_raw({"lifecycle_storage_version": 1, "records": {"cert-1": raw}})
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()

    def test_superseded_without_superseded_by_is_corrupted(self):
        raw = _valid_record_dict(status="SUPERSEDED", superseded_by=None)
        self._write_raw({"lifecycle_storage_version": 1, "records": {"cert-1": raw}})
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()


# 19 -- partial storage (extra/unexpected structure) -----------------------


class Test19_PartialStorage(_FileStoreTestCase):
    def test_record_with_extra_unexpected_field_is_corrupted(self):
        raw = _valid_record_dict()
        raw["unexpected_extra_field"] = "surprise"
        self._write_raw({"lifecycle_storage_version": 1, "records": {"cert-1": raw}})
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()

    def test_records_not_an_object_is_corrupted(self):
        self._write_raw({"lifecycle_storage_version": 1, "records": ["not", "a", "dict"]})
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()


# 20 -- semantic inconsistency ---------------------------------------------


class Test20_SemanticInconsistency(_FileStoreTestCase):
    def test_self_referential_superseded_by_is_corrupted(self):
        raw = _valid_record_dict(status="SUPERSEDED", superseded_by="cert-1")
        self._write_raw({"lifecycle_storage_version": 1, "records": {"cert-1": raw}})
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()


# 21 -- supersession cycle -------------------------------------------------


class Test21_SupersessionCycle(_FileStoreTestCase):
    def test_two_node_cycle_is_corrupted(self):
        raw_1 = _valid_record_dict(certificate_id="cert-1", status="SUPERSEDED", superseded_by="cert-2", sequence=1)
        raw_2 = _valid_record_dict(certificate_id="cert-2", status="SUPERSEDED", superseded_by="cert-1", sequence=2)
        self._write_raw({
            "lifecycle_storage_version": 1,
            "records": {"cert-1": raw_1, "cert-2": raw_2},
        })
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()


# 22 -- cross-request supersession (see also Test17) -----------------------


class Test22_CrossRequestSupersession(_FileStoreTestCase):
    def test_cross_request_supersession_is_corrupted(self):
        raw_1 = _valid_record_dict(
            certificate_id="cert-1", request_id="005", status="SUPERSEDED", superseded_by="cert-2", sequence=1,
        )
        raw_2 = _valid_record_dict(
            certificate_id="cert-2", request_id="not-005", status="CURRENT", superseded_by=None, sequence=2,
        )
        self._write_raw({
            "lifecycle_storage_version": 1,
            "records": {"cert-1": raw_1, "cert-2": raw_2},
        })
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            self._store().load()


# 23 -- concurrent writes ---------------------------------------------------


class Test23_ConcurrentWrites(_FileStoreTestCase):
    def test_concurrent_registration_leaves_the_file_consistent(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry(store=self._store())
        request = _conforming_request()
        c1 = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        c2 = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")

        barrier = threading.Barrier(2)

        def _register(cert):
            barrier.wait(timeout=5)
            registry.register(cert)

        t1 = threading.Thread(target=_register, args=(c1,))
        t2 = threading.Thread(target=_register, args=(c2,))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        # File must be valid JSON, exactly one CURRENT for the scope.
        records, current_by_scope, _ = self._store().load()
        self.assertEqual(len(records), 2)
        current_statuses = [r for r in records.values() if r.status == CertificateLifecycleStatus.CURRENT]
        self.assertEqual(len(current_statuses), 1)


# 24 -- temp-file scenario ---------------------------------------------


class Test24_TempFileScenario(_FileStoreTestCase):
    def test_stray_temp_file_does_not_affect_load(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry(store=self._store())
        c1 = _cert(issuer)
        registry.register(c1)

        # Simulate a crash mid-write: a leftover temp file next to the
        # real one, never renamed into place.
        stray = self.state_path.parent / ".tmp-certificate-lifecycle-stray.json"
        stray.write_text("not even valid json", encoding="utf-8")
        self.addCleanup(lambda: stray.unlink(missing_ok=True))

        records, _, _ = self._store().load()
        self.assertIn(c1.certificate_id, records)

    def test_final_file_absent_temp_file_present_is_treated_as_missing(self):
        stray = self.state_path.parent / ".tmp-certificate-lifecycle-stray.json"
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        stray.write_text("garbage", encoding="utf-8")
        self.addCleanup(lambda: stray.unlink(missing_ok=True))

        records, current_by_scope, sequence = self._store().load()
        self.assertEqual((records, current_by_scope, sequence), ({}, {}, 0))


# 25/26/27/28 -- no certificate mutation / no authority / no execute/create_job


class Test25_28_NoMutationNoAuthority(_FileStoreTestCase):
    def test_persistence_never_mutates_the_certificate(self):
        from dataclasses import FrozenInstanceError

        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry(store=self._store())
        c1 = _cert(issuer)
        registry.register(c1)
        self.assertEqual(c1.request_id, C.request_id)
        with self.assertRaises(FrozenInstanceError):
            c1.request_id = "tampered"  # type: ignore[misc]

    def test_module_never_calls_authority_or_execution_methods(self):
        source = (PROJECT_ROOT / "agents" / "certificate_lifecycle_store.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden_attr_calls = {
            n.func.attr for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("create_job", "execute", "prepare_activation", "validate_activation", "consume")
        }
        self.assertFalse(forbidden_attr_calls, f"forbidden call(s) found: {forbidden_attr_calls}")

        forbidden_authority_symbols = {
            "GenerationApprovalGate", "GenerationJobService", "FileCriticalSectionLock",
            "FileExecutedRequestStore", "HiggsfieldProvider", "HiggsfieldClient",
            "RealGenerationAuthorization", "RequestScopedActivationContract",
            "ControlledRealProviderActivationContract", "RequestScopedActivationService",
            "ControlledRealProviderActivationService",
        }
        constructed = {
            n.func.id for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id in forbidden_authority_symbols
        }
        self.assertFalse(constructed, f"forbidden authority construction found: {constructed}")

    def test_module_imports_no_p2_execution_mechanism(self):
        source = (PROJECT_ROOT / "agents" / "certificate_lifecycle_store.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

        forbidden_import_substrings = (
            "generation_job_service", "critical_section_lock", "executed_request_store",
            "generation_approval_gate", "activation_contract", "controlled_real_provider_activation",
            "higgsfield",
        )
        for module_name in imported_modules:
            for needle in forbidden_import_substrings:
                self.assertNotIn(
                    needle, module_name,
                    f"unexpected import of '{module_name}' in certificate_lifecycle_store.py",
                )

    def test_no_p2_file_or_director_references_the_module(self):
        p2_files = (
            "agents/generation_approval_gate.py",
            "agents/generation_job_service.py",
            "agents/activation_contract.py",
            "agents/controlled_real_provider_activation.py",
            "agents/critical_section_lock.py",
            "agents/executed_request_store.py",
            "agents/release_candidate_identity_lock.py",
            "agents/production_activation_readiness_certificate.py",
            "agents/certificate_verification.py",
            "agents/certificate_integrity.py",
            "integrations/higgsfield/provider.py",
            "director.py",
        )
        offenders = []
        for rel in p2_files:
            text = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
            if "certificate_lifecycle_store" in text:
                offenders.append(rel)
        self.assertFalse(offenders, offenders)


# 29/30 -- restart preserves CURRENT / preserves history -------------------


class Test29_30_RestartPreservesCurrentAndHistory(_FileStoreTestCase):
    def test_restart_preserves_current_across_several_certificates(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry(store=self._store())
        certs = [_cert(issuer) for _ in range(4)]
        for cert in certs:
            registry.register(cert)

        restarted = CertificateLifecycleRegistry(store=self._store())
        restarted.hydrate_from_store()
        self.assertEqual(restarted.status_of(certs[-1].certificate_id), CertificateLifecycleStatus.CURRENT)
        for cert in certs[:-1]:
            self.assertEqual(restarted.status_of(cert.certificate_id), CertificateLifecycleStatus.SUPERSEDED)

    def test_restart_preserves_full_history_ordering(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry(store=self._store())
        certs = [_cert(issuer) for _ in range(3)]
        for cert in certs:
            registry.register(cert)

        restarted = CertificateLifecycleRegistry(store=self._store())
        restarted.hydrate_from_store()
        history = restarted.history_for(certificate_scope(certs[0]))
        self.assertEqual([r.certificate_id for r in history], [c.certificate_id for c in certs])
        self.assertEqual([r.registered_sequence for r in history], [1, 2, 3])


# 31 -- restart corruption = UNKNOWN ----------------------------------------


class Test31_RestartCorruptionIsUnknown(_FileStoreTestCase):
    def test_hydrate_from_store_raises_on_corruption_never_fabricates_state(self):
        self._write_raw({"lifecycle_storage_version": 999, "records": {}})
        registry = CertificateLifecycleRegistry(store=self._store())
        with self.assertRaises(CertificateLifecycleStoreCorruptedError):
            registry.hydrate_from_store()
        # Fail-closed: no partial/guessed state was adopted.
        self.assertEqual(registry.status_of("anything"), CertificateLifecycleStatus.UNKNOWN)
        self.assertIsNone(registry.current_record_for(("005", "mission-A")))


# 32 -- deterministic serialization ------------------------------------


class Test32_DeterministicSerialization(_FileStoreTestCase):
    def test_two_independent_registrations_of_the_same_logical_state_serialize_identically(self):
        issuer, _ = _issuer()
        request = _conforming_request()

        dir_a = Path(self._tmpdir.name) / "a"
        dir_b = Path(self._tmpdir.name) / "b"
        store_a = FileCertificateLifecycleStore(dir_a / "lifecycle.json")
        store_b = FileCertificateLifecycleStore(dir_b / "lifecycle.json")
        registry_a = CertificateLifecycleRegistry(store=store_a)
        registry_b = CertificateLifecycleRegistry(store=store_b)

        cert = issuer.issue(request, mission_id="mission-A", video_plan_identity="plan-v1")
        record_a = registry_a.register(cert)
        record_b = registry_b.register(cert)
        self.assertEqual(record_a, record_b)

        text_a = store_a.path.read_text(encoding="utf-8")
        text_b = store_b.path.read_text(encoding="utf-8")
        self.assertEqual(text_a, text_b)

    def test_repeated_load_of_the_same_file_is_identical(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry(store=self._store())
        registry.register(_cert(issuer))
        store = self._store()
        self.assertEqual(store.load(), store.load())


# Additional: hydration safety / constants --------------------------------


class AdditionalStructuralTests(_FileStoreTestCase):
    def test_lifecycle_storage_version_constant(self):
        self.assertEqual(LIFECYCLE_STORAGE_VERSION, 1)

    def test_hydrate_without_a_store_raises(self):
        registry = CertificateLifecycleRegistry()
        with self.assertRaises(ValueError):
            registry.hydrate_from_store()

    def test_hydrate_after_register_raises(self):
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry(store=self._store())
        registry.register(_cert(issuer))
        with self.assertRaises(RuntimeError):
            registry.hydrate_from_store()

    def test_in_memory_registry_default_behavior_is_unchanged(self):
        """P3.57 zero-regression guarantee: no `store` argument means
        pure in-memory, exactly as before this phase."""
        issuer, _ = _issuer()
        registry = CertificateLifecycleRegistry()
        c1 = _cert(issuer)
        record = registry.register(c1)
        self.assertIsInstance(record, CertificateLifecycleRecord)
        self.assertEqual(record.status, CertificateLifecycleStatus.CURRENT)

    def test_failed_persistence_leaves_in_memory_state_untouched(self):
        issuer, _ = _issuer()
        # Point the store at a path that cannot be written (a file
        # where a directory is expected), forcing append_registration
        # to fail, to confirm register() propagates and does not
        # partially commit in-memory state.
        blocked_path = Path(self._tmpdir.name) / "not-a-directory"
        blocked_path.write_text("occupied", encoding="utf-8")
        store = FileCertificateLifecycleStore(blocked_path / "lifecycle.json")
        registry = CertificateLifecycleRegistry(store=store)
        c1 = _cert(issuer)
        with self.assertRaises(OSError):
            registry.register(c1)
        self.assertEqual(registry.status_of(c1.certificate_id), CertificateLifecycleStatus.UNKNOWN)
        self.assertIsNone(registry.current_record_for(certificate_scope(c1)))


if __name__ == "__main__":
    unittest.main()
