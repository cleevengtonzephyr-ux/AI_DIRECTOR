"""
Tests -- Certificate Record/History Scope Boundary & Informational
Consumer Audit (Phase P3.74).

Pins the real contracts of `CertificateLifecycleRegistry.record_for()`
(keyed by certificate_id, returns a frozen record that CARRIES its own
registered scope) and `history_for()` (keyed by a (request_id,
mission_id) scope tuple -- never by id; anything else matches nothing),
plus the information/authority boundary: informational consumers
outside the authority surface stay clean, every authority-surface use
is flagged.

No production change in P3.74. MockHiggsfieldProvider only.
"""

import inspect
import shutil
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.architecture_drift_detector import ArchitectureDriftDetector
from agents.certificate_lifecycle import (
    CertificateLifecycleRegistry,
    CertificateLifecycleStatus,
    certificate_scope,
)
from agents.certificate_lifecycle_store import FileCertificateLifecycleStore
from tests.test_certificate_integrity import C, _conforming_request, _issuer

LS = CertificateLifecycleStatus


def _two_scopes():
    issuer_a, _ = _issuer()
    issuer_b, _ = _issuer()
    cert_a = issuer_a.issue(_conforming_request(), mission_id="M-A", video_plan_identity="VP-A")
    cert_b = issuer_b.issue(_conforming_request(request_id="006"), mission_id="M-B", video_plan_identity="VP-B")
    return issuer_a, cert_a, cert_b


def _observe(registry, certs, scopes):
    return (
        tuple(registry.record_for(c.certificate_id) for c in certs),
        tuple(registry.history_for(s) for s in scopes),
        tuple(registry.current_record_for(s) for s in scopes),
    )


class TestRecordForContract(unittest.TestCase):
    def test_signature_is_id_only(self):
        self.assertEqual(list(inspect.signature(CertificateLifecycleRegistry.record_for).parameters), ["self", "certificate_id"])

    def test_record_carries_its_registered_scope_whatever_the_caller_assumes(self):
        _, cert_a, cert_b = _two_scopes()
        registry = CertificateLifecycleRegistry()
        registry.register(cert_a)
        registry.register(cert_b)
        for cert, other in ((cert_a, cert_b), (cert_b, cert_a)):
            record = registry.record_for(cert.certificate_id)
            self.assertEqual(record.scope, certificate_scope(cert))
            self.assertNotEqual(record.scope, certificate_scope(other))

    def test_unknown_id_is_none_and_record_is_frozen(self):
        _, cert_a, _ = _two_scopes()
        registry = CertificateLifecycleRegistry()
        registry.register(cert_a)
        self.assertIsNone(registry.record_for("never-registered"))
        with self.assertRaises(FrozenInstanceError):
            registry.record_for(cert_a.certificate_id).status = LS.CURRENT

    def test_superseded_record_stays_superseded_under_repeated_reads(self):
        issuer_a, cert_a, _ = _two_scopes()
        newer = issuer_a.issue(_conforming_request(), mission_id="M-A", video_plan_identity="VP-A")
        registry = CertificateLifecycleRegistry()
        registry.register(cert_a)
        registry.register(newer)
        for _ in range(3):
            record = registry.record_for(cert_a.certificate_id)
            self.assertEqual(record.status, LS.SUPERSEDED)
            self.assertEqual(record.superseded_by, newer.certificate_id)
        self.assertEqual(registry.current_record_for(certificate_scope(cert_a)).certificate_id, newer.certificate_id)


class TestHistoryForContract(unittest.TestCase):
    def test_signature_is_scope_keyed(self):
        self.assertEqual(list(inspect.signature(CertificateLifecycleRegistry.history_for).parameters), ["self", "scope"])

    def test_history_is_scope_isolated_and_ordered(self):
        issuer_a, cert_a, cert_b = _two_scopes()
        newer = issuer_a.issue(_conforming_request(), mission_id="M-A", video_plan_identity="VP-A")
        registry = CertificateLifecycleRegistry()
        for cert in (cert_a, cert_b, newer):
            registry.register(cert)
        history_a = registry.history_for(certificate_scope(cert_a))
        self.assertIsInstance(history_a, tuple)
        self.assertEqual([r.certificate_id for r in history_a], [cert_a.certificate_id, newer.certificate_id])
        self.assertEqual([r.status for r in history_a], [LS.SUPERSEDED, LS.CURRENT])
        self.assertEqual([r.certificate_id for r in registry.history_for(certificate_scope(cert_b))], [cert_b.certificate_id])

    def test_anything_but_an_exact_scope_matches_nothing(self):
        _, cert_a, _ = _two_scopes()
        registry = CertificateLifecycleRegistry()
        registry.register(cert_a)
        for probe in (
            cert_a.certificate_id,               # an id passed as a scope (F4 misuse)
            (C.request_id, "M-B"),               # same request, other mission
            ("006", "M-A"),                      # other request, same mission
            (C.request_id,),                     # partial scope
            [C.request_id, "M-A"],               # list, not tuple
        ):
            with self.subTest(probe=probe):
                self.assertEqual(registry.history_for(probe), ())


class TestReadsNeverMutate(unittest.TestCase):
    def test_reads_leave_memory_and_disk_unchanged_and_restart_is_deterministic(self):
        issuer_a, cert_a, cert_b = _two_scopes()
        newer = issuer_a.issue(_conforming_request(), mission_id="M-A", video_plan_identity="VP-A")
        certs = (cert_a, cert_b, newer)
        scopes = (certificate_scope(cert_a), certificate_scope(cert_b), (C.request_id, "M-B"))

        tmp = Path(tempfile.mkdtemp(prefix="p374_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        path = tmp / "lifecycle.json"
        registry = CertificateLifecycleRegistry(store=FileCertificateLifecycleStore(path))
        for cert in certs:
            registry.register(cert)
        disk = path.read_bytes()
        before = _observe(registry, certs, scopes)

        for _ in range(3):
            registry.record_for(cert_a.certificate_id)
            registry.history_for(cert_a.certificate_id)
            registry.history_for(scopes[2])
        self.assertEqual(_observe(registry, certs, scopes), before)

        restarted = []
        for _ in range(2):
            hydrated = CertificateLifecycleRegistry(store=FileCertificateLifecycleStore(path))
            hydrated.hydrate_from_store()
            restarted.append(_observe(hydrated, certs, scopes))
        self.assertEqual(restarted[0], restarted[1])
        self.assertEqual(restarted[0], before)
        self.assertEqual(path.read_bytes(), disk)


class TestInformationAuthorityBoundary(unittest.TestCase):
    VERDICT = "CERTIFICATE_VERDICT_INTERPRETED_BY_AUTHORITY"

    def _codes(self, *files):
        with tempfile.TemporaryDirectory() as tmp:
            for rel, source in files:
                path = Path(tmp) / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding="utf-8")
            return {f.code for f in ArchitectureDriftDetector(root=Path(tmp)).analyze().findings if "CERTIFICATE" in f.code}

    def test_informational_consumers_outside_authority_surface_stay_clean(self):
        for rel, source in (
            ("agents/lifecycle_dashboard.py", "def show(lifecycle, cid):\n    print(lifecycle.record_for(cid).status)\n"),
            ("scripts/lifecycle_report.py", "def report(lifecycle, cid):\n    return repr(lifecycle.record_for(cid))\n"),
            ("agents/lifecycle_export.py",
             "import json\ndef dump(lifecycle, scope):\n    return json.dumps([r.certificate_id for r in lifecycle.history_for(scope)])\n"),
            ("tests/test_lifecycle_probe.py", "def t(lifecycle, scope):\n    return lifecycle.history_for(scope)\n"),
        ):
            with self.subTest(file=rel):
                self.assertEqual(self._codes((rel, source)), set())

    def test_record_and_history_on_the_authority_surface_are_flagged(self):
        for rel, source in (
            ("agents/generation_job_service.py",
             "def f(lifecycle, cid, svc, req):\n    if lifecycle.record_for(cid).status == 'CURRENT':\n        svc.execute(req)\n"),
            ("agents/production_authority_intake.py",
             "def f(lifecycle, cid, auth, req):\n    if any(r.status == 'CURRENT' for r in lifecycle.history_for(cid)):\n        auth.authorize(req)\n"),
            ("agents/human_authorization_handoff.py",
             "def f(lifecycle, cid_a, mission_b, auth):\n    return auth.human_authorize(mission_b) if lifecycle.record_for(cid_a) else None\n"),
            ("director.py", "def log(lifecycle, cid):\n    print(lifecycle.record_for(cid))\n"),
        ):
            with self.subTest(file=rel):
                self.assertIn(self.VERDICT, self._codes((rel, source)))

    def test_helper_importing_the_lifecycle_module_is_flagged_when_authority_uses_it(self):
        codes = self._codes(
            ("agents/lifecycle_helpers.py",
             "from agents.certificate_lifecycle import CertificateLifecycleRegistry\n"
             "def is_live(lifecycle, scope):\n    return any(r.status.value == 'CURRENT' for r in lifecycle.history_for(scope))\n"),
            ("agents/generation_approval_gate.py",
             "from agents.lifecycle_helpers import is_live\n"
             "def f(reg, scope):\n    return 'APPROVED' if is_live(reg, scope) else 'BLOCKED'\n"),
        )
        self.assertIn("CERTIFICATE_INDIRECT_AUTHORITY_IMPORT", codes)

    def test_lifecycle_record_exposes_no_authority_capability(self):
        _, cert_a, _ = _two_scopes()
        registry = CertificateLifecycleRegistry()
        record = registry.register(cert_a)
        for name in ("approve", "authorize", "human_authorize", "execute", "create_job", "consume", "activate"):
            self.assertFalse(hasattr(record, name), name)
            self.assertFalse(hasattr(registry, name), name)


if __name__ == "__main__":
    unittest.main()
