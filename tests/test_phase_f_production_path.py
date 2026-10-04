"""
Phase F — chemin de production REST Higgsfield, fermé.

Tests mock-only : aucun réseau (toute connexion HTTPS est remplacée par un
objet qui échoue le test), aucun secret, aucun crédit, aucun accès au
`state/` réel. Vérifient le manifeste, l'idempotence, la classification
fermée des réponses, les verrous F-1 à F-4, le journal d'audit, le script
du workflow et le workflow lui-même.
"""

import ast
import contextlib
import hashlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.production_audit_journal import (
    AuditJournal,
    AuditJournalCorruptedError,
    AuditJournalError,
    AuditJournalMissingError,
)
from agents.release_candidate_identity_lock import VIDEO_005_RELEASE_CANDIDATE
from integrations.higgsfield import https_transport, rest_api
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.https_transport import HiggsfieldApiCredentials, HttpsTransport
from integrations.higgsfield.manifest import (
    ManifestError,
    ManifestMismatchError,
    build_manifest,
    derive_idempotency_key,
    verify_manifest,
)
from integrations.higgsfield.rest_api import (
    HIGGSFIELD_REST_FACTS,
    ApiFact,
    CancelOutcomeKind,
    FactStatus,
    HiggsfieldApiSpecUnconfirmedError,
    HiggsfieldRestClient,
    HttpRequest,
    HttpResponse,
    RetryDecision,
    SubmitOutcome,
    SubmitOutcomeKind,
    SubmitRetryPolicy,
    TransportAmbiguousError,
    TransportNotSentError,
    classify_cancel_response,
    classify_status_response,
    classify_submit_response,
    classify_submit_transport_error,
    launch_blockers,
    operation_blockers,
    plan_next_submit_attempt,
)
from integrations.higgsfield.types import JobStatus
from scripts import higgsfield_production_run as run_script
from tests.strict_workflow_yaml import UnsupportedWorkflowYamlError, parse_workflow_yaml

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x01" * 32
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "higgsfield-production.yml"
CONFIRMED_FACTS = {name: ApiFact(fact.value, FactStatus.CONFIRMED) for name, fact in HIGGSFIELD_REST_FACTS.items()}


class _NoNetwork:
    """Remplace `http.client.HTTPSConnection` : toute construction échoue le test."""

    instances = 0

    def __init__(self, *args, **kwargs):
        type(self).instances += 1
        raise AssertionError("a network connection was attempted")


def no_network():
    _NoNetwork.instances = 0
    return mock.patch.object(https_transport.http.client, "HTTPSConnection", _NoNetwork)


class _RecordingTransport:
    def __init__(self, response=None, error=None):
        self.requests = []
        self.response = response
        self.error = error

    def send(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response


class _Workspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.avatar = self.root / "avatar.png"
        self.face = self.root / "face.jpg"
        self.avatar.write_bytes(PNG)
        self.face.write_bytes(JPEG)

    def tearDown(self):
        self._tmp.cleanup()

    def manifest(self, prompt="Zephyr speaks.", duration=15, media=None):
        return build_manifest(
            request_id="005",
            model_id="seedance_2_0",
            prompt=prompt,
            parameters={"duration": duration, "resolution": "720p", "aspect_ratio": "9:16"},
            media=media or [("master_avatar", str(self.avatar)), ("face_reference", str(self.face))],
        )


class TestManifest(_Workspace):
    def test_manifest_is_deterministic_and_hides_prompt_and_paths(self):
        first, second = self.manifest(), self.manifest()
        self.assertEqual(first.manifest_sha256, second.manifest_sha256)
        canonical = first.canonical_json().decode("utf-8")
        self.assertNotIn("Zephyr speaks", canonical)
        self.assertNotIn(str(self.root), canonical)
        self.assertEqual(json.loads(canonical)["parameters"], {"aspect_ratio": "9:16", "duration": 15, "resolution": "720p"})
        self.assertNotIn("Zephyr", repr(first))

    def test_any_change_changes_the_digest(self):
        base = self.manifest().manifest_sha256
        self.assertNotEqual(base, self.manifest(prompt="Other.").manifest_sha256)
        self.assertNotEqual(base, self.manifest(duration=10).manifest_sha256)
        self.avatar.write_bytes(PNG + b"\x01")
        self.assertNotEqual(base, self.manifest().manifest_sha256)

    def test_media_bytes_are_read_once_and_kept(self):
        manifest = self.manifest()
        self.avatar.write_bytes(PNG + b"replaced")
        media = manifest.media_for_role("master_avatar")
        self.assertEqual(media.content, PNG)
        self.assertEqual(media.sha256, hashlib.sha256(PNG).hexdigest())
        self.assertEqual(media.media_type, "image/png")

    def test_invalid_inputs_are_refused(self):
        unknown = self.root / "a.bin"
        unknown.write_bytes(b"not an image")
        empty = self.root / "e.png"
        empty.write_bytes(b"")
        for media in (
            [("master_avatar", str(unknown))],
            [("master_avatar", str(empty))],
            [("master_avatar", str(self.root / "missing.png"))],
            [("master_avatar", str(self.avatar)), ("master_avatar", str(self.avatar))],
        ):
            with self.assertRaises(ManifestError):
                self.manifest(media=media)
        for parameters in ({"duration": 15.0}, {"duration": True}, {"Bad-Name": 1}, {"duration": None}):
            with self.assertRaises(ManifestError):
                build_manifest("005", "seedance_2_0", "p", parameters, [])
        with self.assertRaises(ManifestError):
            build_manifest("005", "seedance_2_0", "   ", {}, [])

    def test_verify_manifest_stops_on_any_divergence(self):
        manifest = self.manifest()
        verify_manifest(manifest.manifest_sha256, manifest)
        for approved in ("0" * 64, manifest.manifest_sha256.upper(), "", None, manifest.manifest_sha256[:-1]):
            with self.assertRaises(ManifestMismatchError):
                verify_manifest(approved, manifest)

    def test_idempotency_key_is_stable_per_approval_and_new_per_approval(self):
        digest = self.manifest().manifest_sha256
        key = derive_idempotency_key(digest, "gh-123")
        self.assertEqual(key, derive_idempotency_key(digest, "gh-123"))
        self.assertNotEqual(key, derive_idempotency_key(digest, "gh-124"))
        self.assertNotEqual(key, derive_idempotency_key(self.manifest(duration=10).manifest_sha256, "gh-123"))
        self.assertRegex(key, r"^aidir1-[0-9a-f]{64}$")
        for bad in ("", "a b", "x://y"):
            with self.assertRaises(ManifestError):
                derive_idempotency_key(digest, bad)


class TestVideo005Manifest(unittest.TestCase):
    def test_real_video_005_manifest_matches_the_locked_release_candidate(self):
        manifest = run_script.build_video_005_manifest()
        contract = VIDEO_005_RELEASE_CANDIDATE
        self.assertEqual(manifest.prompt_sha256, contract.prompt_sha256)
        self.assertEqual(manifest.media_for_role("master_avatar").sha256, contract.avatar_master_sha256)
        self.assertEqual(manifest.media_for_role("face_reference").sha256, contract.face_reference_sha256)
        self.assertEqual(manifest.model_id, contract.job_type)
        self.assertEqual(
            dict(manifest.parameters),
            {"duration": contract.duration, "resolution": contract.resolution, "aspect_ratio": contract.aspect_ratio},
        )


class TestRequests(_Workspace):
    def test_estimate_and_submit_share_one_body_builder(self):
        manifest = self.manifest()
        media = {"master_avatar": "m1", "face_reference": "m2"}
        client = HiggsfieldRestClient(_RecordingTransport())
        key = derive_idempotency_key(manifest.manifest_sha256, "gh-1")
        submit = client.build_submit_request(manifest, media, key)
        self.assertEqual(submit.body, HiggsfieldRestClient.request_body(manifest, media))
        body = json.loads(submit.body)
        self.assertEqual(body["duration"], 15)
        self.assertEqual(body["prompt"], "Zephyr speaks.")
        with self.assertRaises(HiggsfieldApiSpecUnconfirmedError):
            client.build_estimate_request(manifest, media)
        with self.assertRaises(ValueError):
            HiggsfieldRestClient.request_body(manifest, {"master_avatar": "m1"})

    def test_submit_request_carries_explicit_idempotency_key_and_no_credentials(self):
        manifest = self.manifest()
        key = derive_idempotency_key(manifest.manifest_sha256, "gh-1")
        request = HiggsfieldRestClient().build_submit_request(manifest, {"master_avatar": "a", "face_reference": "b"}, key)
        self.assertEqual(request.header("Idempotency-Key"), key)
        self.assertIsNone(request.header("Authorization"))
        self.assertEqual((request.method, request.path), ("POST", "/seedance_2_0"))
        self.assertNotIn("Zephyr", repr(request))
        self.assertNotIn("Zephyr", json.dumps(request.public_summary()))
        with self.assertRaises(ValueError):
            HiggsfieldRestClient().build_submit_request(manifest, {"master_avatar": "a", "face_reference": "b"}, "random")

    def test_status_and_cancel_paths_validate_the_provider_id(self):
        client = HiggsfieldRestClient()
        self.assertEqual(client.build_status_request("abc-1").path, "/requests/abc-1/status")
        self.assertEqual(client.build_cancel_request("abc-1").path, "/requests/abc-1/cancel")
        for bad in ("../x", "a/b", "", "a?b"):
            with self.assertRaises(ValueError):
                client.build_status_request(bad)


class TestClassification(unittest.TestCase):
    def test_submit_responses(self):
        cases = [
            (HttpResponse(202, b'{"request_id":"r-1"}'), SubmitOutcomeKind.ACCEPTED),
            (HttpResponse(202, b"{}"), SubmitOutcomeKind.AMBIGUOUS),
            (HttpResponse(200, b"not json"), SubmitOutcomeKind.AMBIGUOUS),
            (HttpResponse(402, b""), SubmitOutcomeKind.INSUFFICIENT_CREDITS),
            (HttpResponse(400, b'{"detail":"Insufficient credits"}'), SubmitOutcomeKind.INSUFFICIENT_CREDITS),
            (HttpResponse(401, b""), SubmitOutcomeKind.AUTH_FAILED),
            (HttpResponse(422, b""), SubmitOutcomeKind.REJECTED),
            (HttpResponse(409, b""), SubmitOutcomeKind.AMBIGUOUS),
            (HttpResponse(429, b""), SubmitOutcomeKind.AMBIGUOUS),
            (HttpResponse(503, b""), SubmitOutcomeKind.AMBIGUOUS),
            (HttpResponse(302, b""), SubmitOutcomeKind.AMBIGUOUS),
        ]
        for response, expected in cases:
            self.assertIs(classify_submit_response(response).kind, expected, response)
        accepted = classify_submit_response(HttpResponse(202, b'{"request_id":"r-1"}'))
        self.assertEqual(accepted.provider_request_id, "r-1")

    def test_definitive_refusals_require_a_new_approval(self):
        insufficient = classify_submit_response(HttpResponse(402))
        self.assertTrue(insufficient.requires_new_approval)
        for kind in (SubmitOutcomeKind.ACCEPTED, SubmitOutcomeKind.AMBIGUOUS, SubmitOutcomeKind.NOT_SENT):
            self.assertFalse(SubmitOutcome(kind).requires_new_approval)

    def test_transport_errors(self):
        self.assertIs(classify_submit_transport_error(TransportNotSentError("x")).kind, SubmitOutcomeKind.NOT_SENT)
        self.assertIs(classify_submit_transport_error(TransportAmbiguousError("x")).kind, SubmitOutcomeKind.AMBIGUOUS)
        self.assertIs(classify_submit_transport_error(RuntimeError("x")).kind, SubmitOutcomeKind.AMBIGUOUS)

    def test_retry_plan_never_resends_an_ambiguous_submission_without_confirmed_idempotency(self):
        policy = SubmitRetryPolicy(max_attempts=3)
        ambiguous = SubmitOutcome(SubmitOutcomeKind.AMBIGUOUS)
        not_sent = SubmitOutcome(SubmitOutcomeKind.NOT_SENT)
        plan = plan_next_submit_attempt
        self.assertIs(plan(ambiguous, 1, policy, idempotency_confirmed=False), RetryDecision.STOP_STATE_UNKNOWN)
        self.assertIs(plan(ambiguous, 1, policy, idempotency_confirmed=True), RetryDecision.RETRY_SAME_KEY)
        self.assertIs(plan(ambiguous, 3, policy, idempotency_confirmed=True), RetryDecision.STOP_STATE_UNKNOWN)
        self.assertIs(plan(not_sent, 1, policy, idempotency_confirmed=False), RetryDecision.RETRY_SAME_KEY)
        self.assertIs(plan(not_sent, 3, policy, idempotency_confirmed=False), RetryDecision.STOP_NEW_APPROVAL_REQUIRED)
        self.assertIs(
            plan(SubmitOutcome(SubmitOutcomeKind.INSUFFICIENT_CREDITS), 1, policy, idempotency_confirmed=True),
            RetryDecision.STOP_NEW_APPROVAL_REQUIRED,
        )
        self.assertIs(plan(SubmitOutcome(SubmitOutcomeKind.ACCEPTED), 1, policy, True), RetryDecision.STOP_ACCEPTED)
        self.assertIs(plan(ambiguous, 1, policy, idempotency_confirmed="yes"), RetryDecision.STOP_STATE_UNKNOWN)
        for bad in (0, True, 1.5):
            with self.assertRaises(ValueError):
                SubmitRetryPolicy(max_attempts=bad)

    def test_status_never_reports_success_without_result_and_hides_urls(self):
        done = classify_status_response("r-1", HttpResponse(200, b'{"status":"completed","video":{"url":"https://cdn/x.mp4?sig=1"}}'))
        self.assertIs(done.status, JobStatus.SUCCEEDED)
        self.assertEqual(done.public_summary(), {"status": "succeeded", "http_status": 200, "output_count": 1})
        self.assertNotIn("cdn", repr(done))
        for body, status in (
            (b'{"status":"completed"}', 200),
            (b'{"status":"teleported"}', 200),
            (b"oops", 200),
            (b'{"status":"completed","video":{"url":"https://cdn/x"}}', 500),
        ):
            self.assertIs(classify_status_response("r-1", HttpResponse(status, body)).status, JobStatus.UNKNOWN)
        self.assertIs(classify_status_response("r", HttpResponse(200, b'{"status":"in_progress"}')).status, JobStatus.RUNNING)

    def test_cancel_responses(self):
        self.assertIs(classify_cancel_response(HttpResponse(202)), CancelOutcomeKind.ACCEPTED)
        self.assertIs(classify_cancel_response(HttpResponse(400)), CancelOutcomeKind.REFUSED)
        self.assertIs(classify_cancel_response(HttpResponse(429)), CancelOutcomeKind.AMBIGUOUS)
        self.assertIs(classify_cancel_response(HttpResponse(500)), CancelOutcomeKind.AMBIGUOUS)


def _function(path: Path, class_name: str, method: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    return next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method)


class TestLocks(_Workspace):
    MUTATING = ("submit_generation", "cancel_generation", "upload_media")

    def test_f1_to_f3_mutating_methods_are_a_single_unconditional_raise(self):
        path = PROJECT_ROOT / "integrations" / "higgsfield" / "rest_api.py"
        for method in self.MUTATING:
            body = _function(path, "HiggsfieldRestClient", method).body
            if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body = body[1:]
            self.assertEqual(len(body), 1, method)
            self.assertIsInstance(body[0], ast.Raise, method)
            self.assertEqual(body[0].exc.func.id, "HiggsfieldRealGenerationDisabledError", method)

    def test_mutating_methods_raise_without_touching_the_transport(self):
        transport = _RecordingTransport(HttpResponse(202, b'{"request_id":"r"}'))
        client = HiggsfieldRestClient(transport)
        manifest = self.manifest()
        for method in self.MUTATING:
            with self.assertRaises(HiggsfieldRealGenerationDisabledError):
                getattr(client, method)(manifest, {"master_avatar": "a", "face_reference": "b"}, "k")
        self.assertEqual(transport.requests, [])

    def test_default_transport_refuses_everything(self):
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            HiggsfieldRestClient().get_status("r-1")

    def test_f4_https_transport_refuses_mutating_operations_before_any_connection(self):
        credentials = HiggsfieldApiCredentials("id", "secret")
        transport = HttpsTransport(credentials, 30, facts=CONFIRMED_FACTS)
        with no_network():
            for operation, method in (("submit", "POST"), ("cancel", "POST"), ("upload", "POST"), ("other", "GET")):
                with self.assertRaises(HiggsfieldRealGenerationDisabledError):
                    transport.send(HttpRequest(operation, method, "/x"))
        self.assertEqual(_NoNetwork.instances, 0)

    def test_allowed_operation_label_cannot_carry_another_method_path_or_body(self):
        """Même avec tous les faits confirmés, l'étiquette `status` n'ouvre que GET /requests/<id>/status sans corps."""

        transport = HttpsTransport(HiggsfieldApiCredentials("id", "secret"), 30, facts=CONFIRMED_FACTS)
        manifest = self.manifest()
        submit = HiggsfieldRestClient().build_submit_request(
            manifest, {"master_avatar": "a", "face_reference": "b"}, derive_idempotency_key(manifest.manifest_sha256, "gh-1")
        )
        disguised = (
            HttpRequest("status", submit.method, submit.path, submit.headers, submit.body),
            HttpRequest("status", "POST", "/requests/r-1/status"),
            HttpRequest("status", "GET", "/seedance_2_0"),
            HttpRequest("status", "GET", "/requests/r-1/cancel"),
            HttpRequest("status", "GET", "/requests/r-1/status/extra"),
            HttpRequest("status", "GET", "/requests/r-1/status?x=1"),
            HttpRequest("status", "GET", "//requests/r-1/status"),
            HttpRequest("status", "GET", "/requests/../status"),
            HttpRequest("status", "get", "/requests/r-1/status"),
            HttpRequest("status", "GET", "/requests/r-1/status", body=b"{}"),
            HttpRequest("estimate", "POST", "/seedance_2_0", body=submit.body),
        )
        with no_network():
            for request in disguised:
                with self.assertRaises(HiggsfieldRealGenerationDisabledError, msg=request):
                    transport.send(request)
        self.assertEqual(_NoNetwork.instances, 0)
        self.assertEqual(set(https_transport.OPERATION_ROUTES), {"status"})
        with self.assertRaises(TypeError):
            https_transport.OPERATION_ROUTES["submit"] = https_transport.OPERATION_ROUTES["status"]

    def test_https_transport_refuses_read_only_operations_while_facts_are_unconfirmed(self):
        transport = HttpsTransport(HiggsfieldApiCredentials("id", "secret"), 30)
        with no_network():
            for request in (HiggsfieldRestClient().build_status_request("r-1"), HttpRequest("estimate", "POST", "/x")):
                with self.assertRaises(HiggsfieldApiSpecUnconfirmedError):
                    transport.send(request)
            with self.assertRaises(HiggsfieldApiSpecUnconfirmedError):
                HiggsfieldRestClient(transport).get_status("r-1")
        self.assertEqual(_NoNetwork.instances, 0)

    def test_https_transport_sends_a_confirmed_read_only_request_with_fake_connection(self):
        sent = {}

        class FakeConnection:
            def __init__(self, host, **kwargs):
                sent.update(host=host, kwargs=kwargs)

            def connect(self):
                pass

            def request(self, method, path, body=None, headers=None):
                sent.update(method=method, path=path, headers=headers)

            def getresponse(self):
                return mock.Mock(status=200, read=lambda n: b'{"status":"queued"}')

            def close(self):
                sent["closed"] = True

        transport = HttpsTransport(HiggsfieldApiCredentials("kid", "ksecret"), 30, facts=CONFIRMED_FACTS)
        with mock.patch.object(https_transport.http.client, "HTTPSConnection", FakeConnection):
            observation = HiggsfieldRestClient(transport).get_status("r-1")
        self.assertIs(observation.status, JobStatus.QUEUED)
        self.assertEqual(sent["host"], "platform.higgsfield.ai")
        self.assertEqual(sent["kwargs"], {"timeout": 30.0})
        self.assertEqual((sent["method"], sent["path"]), ("GET", "/requests/r-1/status"))
        self.assertEqual(sent["headers"]["Authorization"], "Key kid:ksecret")
        self.assertTrue(sent["closed"])

    def test_https_transport_maps_connection_failures(self):
        class Refused:
            def __init__(self, *a, **k):
                pass

            def connect(self):
                raise ConnectionRefusedError("Key kid:ksecret")

            def close(self):
                pass

        class Reset(Refused):
            def connect(self):
                pass

            def request(self, *a, **k):
                raise TimeoutError()

        transport = HttpsTransport(HiggsfieldApiCredentials("kid", "ksecret"), 30, facts=CONFIRMED_FACTS)
        request = HiggsfieldRestClient().build_status_request("r-1")
        with mock.patch.object(https_transport.http.client, "HTTPSConnection", Refused):
            with self.assertRaises(TransportNotSentError) as raised:
                transport.send(request)
        self.assertNotIn("ksecret", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        with mock.patch.object(https_transport.http.client, "HTTPSConnection", Reset):
            with self.assertRaises(TransportAmbiguousError):
                transport.send(request)

    def test_credentials_are_never_shown(self):
        credentials = HiggsfieldApiCredentials("kid", "ksecret")
        self.assertNotIn("ksecret", repr(credentials) + str(credentials))
        with self.assertRaises(TypeError):
            import pickle
            pickle.dumps(credentials)
        for environ in ({}, {"HIGGSFIELD_API_KEY_ID": "kid"}, {"HIGGSFIELD_API_KEY_ID": "k:x", "HIGGSFIELD_API_KEY_SECRET": "s"}):
            with self.assertRaises(ValueError):
                HiggsfieldApiCredentials.from_environment(environ)

    def test_no_api_fact_is_confirmed_so_launch_stays_blocked(self):
        self.assertFalse(any(f.status is FactStatus.CONFIRMED for f in HIGGSFIELD_REST_FACTS.values()))
        blockers = launch_blockers()
        for name in ("idempotency_key_header", "insufficient_credits_signal", "estimate_is_binding_ceiling", "estimate_endpoint"):
            self.assertIn(name, blockers)
        for operation in ("submit", "status", "cancel", "estimate", "upload", "unknown"):
            self.assertTrue(operation_blockers(operation))
        self.assertEqual(operation_blockers("status", CONFIRMED_FACTS), [])

    def test_rest_path_is_wired_nowhere_in_production(self):
        """Aucun chemin parallèle : le client REST n'est importé que par son transport, le script n'importe ni l'un ni l'autre."""

        names = set(self.MUTATING) | {"HiggsfieldRestClient", "HttpsTransport", "HiggsfieldApiCredentials"}
        allowed = {"integrations/higgsfield/rest_api.py", "integrations/higgsfield/https_transport.py"}
        files = [PROJECT_ROOT / "director.py"]
        for directory in ("agents", "integrations", "scripts"):
            files.extend((PROJECT_ROOT / directory).rglob("*.py"))
        for path in files:
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            if rel in allowed or "__pycache__" in rel:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(
                    ("integrations.higgsfield.rest_api", "integrations.higgsfield.https_transport")
                ):
                    self.fail(f"{rel} imports the REST path")
                if isinstance(node, ast.Attribute) and node.attr in names:
                    self.fail(f"{rel} references {node.attr}")
                if isinstance(node, ast.Name) and node.id in names:
                    self.fail(f"{rel} references {node.id}")

    def test_existing_four_locks_still_refuse(self):
        from integrations.higgsfield.client import HiggsfieldClient
        from integrations.higgsfield.provider import HiggsfieldProvider

        client = HiggsfieldClient(command="unused-cli")
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            client.create_job("seedance_2_0", "p")
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            client.run("generate", "create", "seedance_2_0")
        with self.assertRaises(HiggsfieldRealGenerationDisabledError):
            HiggsfieldProvider(client=client).create_job("seedance_2_0", "p")


class TestAuditJournal(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "audit.jsonl"
        self.journal = AuditJournal(self.path)
        self.journal.initialize()

    def tearDown(self):
        self._tmp.cleanup()

    def _three_entries(self):
        for approval in ("gh-1", "gh-2", "gh-3"):
            self.journal.append("manifest_verified", "005", {"approval_id": approval})
        return self.path.read_text(encoding="utf-8").splitlines()

    def _rewrite(self, lines):
        self.path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")

    def assert_corrupted_and_append_blocked(self):
        with self.assertRaises(AuditJournalCorruptedError):
            self.journal.verify()
        size = self.path.stat().st_size if self.path.exists() else None
        with self.assertRaises(AuditJournalCorruptedError):
            self.journal.append("manifest_verified", "005", {})
        self.assertEqual(self.path.stat().st_size if self.path.exists() else None, size)

    def test_initialized_journal_is_empty_and_cannot_be_reinitialized(self):
        self.assertEqual(self.journal.verify(), 0)
        with self.assertRaises(AuditJournalError):
            self.journal.initialize()

    def test_append_and_verify_chain(self):
        self.journal.append("manifest_verified", "005", {"manifest_sha256": "a" * 64, "approval_id": "gh-1"})
        self.journal.append("submission_refused_provider_closed", "005", {"decision": "NO-GO"})
        entries = self.journal.entries()
        self.assertEqual([e["seq"] for e in entries], [1, 2])
        self.assertEqual(entries[1]["prev_sha256"], entries[0]["entry_sha256"])

    def test_tampering_is_detected_and_blocks_appends(self):
        self.journal.append("manifest_verified", "005", {"approval_id": "gh-1"})
        self.journal.append("manifest_verified", "005", {"approval_id": "gh-2"})
        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.path.write_text(lines[0].replace("gh-1", "gh-9") + "\n" + lines[1] + "\n", encoding="utf-8")
        with self.assertRaises(AuditJournalCorruptedError):
            self.journal.verify()
        size = self.path.stat().st_size
        with self.assertRaises(AuditJournalCorruptedError):
            self.journal.append("manifest_verified", "005", {})
        self.assertEqual(self.path.stat().st_size, size)
        self.path.write_text(lines[1] + "\n", encoding="utf-8")
        with self.assertRaises(AuditJournalCorruptedError):
            self.journal.verify()

    def test_partial_deletion_in_the_middle_is_detected(self):
        lines = self._three_entries()
        self._rewrite([lines[0], lines[2]])
        self.assert_corrupted_and_append_blocked()

    def test_deletion_of_trailing_entries_is_detected(self):
        lines = self._three_entries()
        for kept in (lines[:2], lines[:1]):
            self._rewrite(kept)
            self.assert_corrupted_and_append_blocked()

    def test_truncation_to_empty_is_detected(self):
        self._three_entries()
        self.path.write_bytes(b"")
        self.assert_corrupted_and_append_blocked()

    def test_deleting_only_the_journal_or_only_its_head_is_detected(self):
        self._three_entries()
        head = self.journal.head_path.read_bytes()
        self.journal.head_path.unlink()
        self.assert_corrupted_and_append_blocked()
        self.journal.head_path.write_bytes(head)
        self.assertEqual(self.journal.verify(), 3)
        self.path.unlink()
        self.assert_corrupted_and_append_blocked()
        self.assertFalse(self.path.exists())
        with self.assertRaises(AuditJournalError):
            self.journal.initialize()

    def test_absent_journal_is_an_explicit_state_never_an_empty_valid_journal(self):
        self._three_entries()
        self.path.unlink()
        self.journal.head_path.unlink()
        self.assertTrue(self.journal.is_absent())
        with self.assertRaises(AuditJournalMissingError):
            self.journal.verify()
        with self.assertRaises(AuditJournalMissingError):
            self.journal.entries()
        with self.assertRaises(AuditJournalMissingError):
            self.journal.append("manifest_verified", "005", {})
        self.assertTrue(self.journal.is_absent())
        self.journal.initialize()
        self.assertEqual(self.journal.verify(), 0)

    def test_secrets_urls_and_prompts_are_refused_and_nothing_is_written(self):
        for details in (
            {"api_key": "x"},
            {"key_secret": "x"},
            {"result_url": "x"},
            {"prompt": "x"},
            {"note": "https://cdn.example/x.mp4?sig=1"},
            {"note": "Key kid:ksecret"},
            {"note": "Bearer abcdefghijkl"},
            {"note": "a\nb"},
            {"nested": {"a": 1}},
            {"Bad Key": 1},
        ):
            with self.assertRaises(AuditJournalError, msg=details):
                self.journal.append("submit_outcome", "005", details)
        with self.assertRaises(AuditJournalError):
            self.journal.append("not_an_event", "005", {})
        self.assertEqual(self.path.stat().st_size, 0)
        self.assertEqual(self.journal.verify(), 0)


class TestRunScript(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.journal = Path(self._tmp.name) / "audit.jsonl"
        self.digest = run_script.build_video_005_manifest().manifest_sha256

    def tearDown(self):
        self._tmp.cleanup()

    def run_main(self, *argv):
        output = io.StringIO()
        with no_network(), contextlib.redirect_stdout(output):
            code = run_script.main(list(argv))
        return code, output.getvalue()

    def execute(self, digest, attempt="1", approval="gh-42", new_journal=True):
        return self.run_main(
            "verify-and-execute", "--approved-manifest-sha256", digest, "--approval-id", approval,
            "--run-attempt", attempt, "--journal", str(self.journal), *(["--new-journal"] if new_journal else []),
        )

    def test_prepare_publishes_digest_without_prompt(self):
        summary = Path(self._tmp.name) / "summary.md"
        code, output = self.run_main("prepare", "--summary-file", str(summary))
        self.assertEqual(code, run_script.EXIT_OK)
        self.assertIn(f"manifest_sha256={self.digest}", output)
        prompt = run_script.build_video_005_manifest().prompt
        self.assertNotIn(prompt[:80], output + summary.read_text(encoding="utf-8"))

    def test_matching_manifest_stops_on_provider_closed(self):
        code, output = self.execute(self.digest)
        self.assertEqual(code, run_script.EXIT_PROVIDER_CLOSED)
        self.assertIn("PROVIDER_CLOSED", output)
        events = [e["event"] for e in AuditJournal(self.journal).entries()]
        self.assertEqual(events, ["manifest_verified", "submission_refused_provider_closed"])
        key = AuditJournal(self.journal).entries()[0]["details"]["idempotency_key"]
        self.assertEqual(key, derive_idempotency_key(self.digest, "gh-42"))

    def test_divergent_manifest_stops_before_anything_else(self):
        code, output = self.execute("0" * 64)
        self.assertEqual(code, run_script.EXIT_MISMATCH)
        self.assertEqual([e["event"] for e in AuditJournal(self.journal).entries()], ["manifest_mismatch"])

    def test_rerun_is_refused_without_durable_state(self):
        code, _ = self.execute(self.digest, attempt="2")
        self.assertEqual(code, run_script.EXIT_RERUN_REFUSED)
        self.assertEqual([e["event"] for e in AuditJournal(self.journal).entries()], ["execution_refused"])

    def test_malformed_arguments_and_corrupted_journal(self):
        self.assertEqual(self.execute(self.digest, approval="x://y")[0], run_script.EXIT_INVALID)
        self.assertEqual(self.execute(self.digest, attempt="0")[0], run_script.EXIT_INVALID)
        self.assertFalse(self.journal.exists())
        self.journal.write_text("garbage\n", encoding="utf-8")
        self.assertEqual(self.execute(self.digest, new_journal=False)[0], run_script.EXIT_JOURNAL)
        # `--new-journal` ne réinitialise jamais un journal existant.
        self.assertEqual(self.execute(self.digest)[0], run_script.EXIT_JOURNAL)
        self.assertEqual(self.journal.read_text(encoding="utf-8"), "garbage\n")

    def test_absent_journal_is_refused_without_explicit_new_journal(self):
        code, output = self.execute(self.digest, new_journal=False)
        self.assertEqual(code, run_script.EXIT_JOURNAL)
        self.assertIn("AUDIT_JOURNAL_FAILURE", output)
        self.assertTrue(AuditJournal(self.journal).is_absent())

    def test_workflow_creates_a_new_journal_explicitly(self):
        self.assertIn("--new-journal", WORKFLOW.read_text(encoding="utf-8"))

    def test_script_reads_no_environment_and_builds_no_client(self):
        source = (PROJECT_ROOT / "scripts" / "higgsfield_production_run.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, ("environ", "getenv", "putenv"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Name):
                imported.add(node.id)
        for forbidden in (
            "integrations.higgsfield.rest_api", "integrations.higgsfield.https_transport",
            "integrations.higgsfield.client", "integrations.higgsfield.provider",
            "agents.generation_job_service", "HiggsfieldClient", "HiggsfieldProvider",
            "GenerationJobService", "subprocess", "os",
        ):
            self.assertNotIn(forbidden, imported)


CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
ALL_WORKFLOWS = sorted((PROJECT_ROOT / ".github" / "workflows").glob("*.yml"))

# Références vérifiées par le propriétaire (SHA de commit complet + version).
PINNED_ACTIONS = {
    "actions/checkout": ("3d3c42e5aac5ba805825da76410c181273ba90b1", "v7.0.1"),
    "actions/setup-python": ("5fda3b95a4ea91299a34e894583c3862153e4b97", "v7.0.0"),
}


def _walk(node, path=()):
    """Toutes les clés et tous les scalaires, avec leur chemin."""

    if isinstance(node, dict):
        for key, value in node.items():
            yield path + (key,), key
            yield from _walk(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, path + (index,))
    elif isinstance(node, str):
        yield path, node


def _steps(workflow):
    for job_name, job in workflow["jobs"].items():
        for step in job.get("steps", []):
            yield job_name, step


class TestStrictWorkflowYaml(unittest.TestCase):
    """L'analyseur strict ne couvre que le sous-ensemble des workflows du dépôt, et refuse le reste."""

    SAMPLE = (
        "# commentaire\n"
        "name: Exemple (CLOSED)\n"
        "\n"
        "on:\n"
        "  push:\n"
        "    branches: [main, release/*]\n"
        "  workflow_dispatch:\n"
        "    inputs:\n"
        "      digest:\n"
        '        description: "empreinte: approuvée"\n'
        "        required: true\n"
        "\n"
        "permissions: {}\n"
        "\n"
        "jobs:\n"
        "  build:\n"
        "    if: github.ref == 'refs/heads/main'\n"
        "    steps:\n"
        "      - uses: actions/checkout@" + "a" * 40 + " # v1.2.3\n"
        "        with:\n"
        "          persist-credentials: false\n"
        "\n"
        "      - name: Run\n"
        "        env:\n"
        "          DIGEST: ${{ inputs.digest }}\n"
        "        run: |\n"
        "          $x = 1 # pas un commentaire YAML\n"
        "\n"
        "          if ($x) { exit 4 }\n"
        "      - plain item\n"
    )

    def test_sample_with_every_supported_construct(self):
        parsed = parse_workflow_yaml(self.SAMPLE)
        self.assertEqual(parsed["name"], "Exemple (CLOSED)")
        self.assertEqual(parsed["on"]["push"]["branches"], ["main", "release/*"])
        self.assertEqual(parsed["on"]["workflow_dispatch"]["inputs"]["digest"]["description"], "empreinte: approuvée")
        self.assertEqual(parsed["on"]["workflow_dispatch"]["inputs"]["digest"]["required"], "true")
        self.assertEqual(parsed["permissions"], {})
        steps = parsed["jobs"]["build"]["steps"]
        self.assertEqual(steps[0], {"uses": "actions/checkout@" + "a" * 40, "with": {"persist-credentials": "false"}})
        self.assertEqual(steps[1]["env"], {"DIGEST": "${{ inputs.digest }}"})
        self.assertEqual(steps[1]["run"], "$x = 1 # pas un commentaire YAML\n\nif ($x) { exit 4 }\n")
        self.assertEqual(steps[2], "plain item")
        self.assertEqual(parsed["jobs"]["build"]["if"], "github.ref == 'refs/heads/main'")
        self.assertIsNone(parse_workflow_yaml("on:\n  workflow_dispatch:\n")["on"]["workflow_dispatch"])

    def test_every_repository_workflow_parses(self):
        self.assertEqual({path.name for path in ALL_WORKFLOWS}, {"ci.yml", "higgsfield-production.yml"})
        for path in ALL_WORKFLOWS:
            parsed = parse_workflow_yaml(path.read_text(encoding="utf-8"))
            self.assertIn("jobs", parsed, path.name)

    def test_unsupported_or_invalid_constructs_fail_explicitly(self):
        cases = {
            "tab": "a:\n\tb: c\n",
            "carriage return": "a: b\r\nc: d\n",
            "byte order mark": "\ufeffa: b\n",
            "document marker": "---\na: b\n",
            "document end": "a: b\n...\n",
            "directive": "%YAML 1.2\na: b\n",
            "anchor": "a: &x b\n",
            "alias": "a: *x\n",
            "merge key": "a:\n  <<: *x\n",
            "tag": "a: !!str b\n",
            "complex key": "? a\n: b\n",
            "single quotes": "a: 'b'\n",
            "folded block": "a: >\n  b\n",
            "chomping indicator": "a: |-\n  b\n",
            "flow mapping": "a: {b: c}\n",
            "nested flow sequence": "a: [b, [c]]\n",
            "quoted flow item": 'a: ["b"]\n',
            "unclosed flow sequence": "a: [b,\n  c]\n",
            "escape": 'a: "b\\n"\n',
            "unterminated quote": 'a: "b\n',
            "text after quote": 'a: "b" c\n',
            "duplicate key": "a: b\na: c\n",
            "duplicate nested key": "a:\n  b: 1\n  b: 2\n",
            "multi-line plain scalar": "a: b\n  c\n",
            "colon in plain scalar": "a: b: c\n",
            "same-indent sequence": "a:\n- b\n",
            "nested sequence": "a:\n  - - b\n",
            "empty sequence item": "a:\n  -\n",
            "mixed mapping and sequence": "a:\n  b: c\n  - d\n",
            "bad dedent": "a:\n    b: c\n  d: e\n",
            "quoted key": '"a": b\n',
            "empty literal": "a: |\nb: c\n",
            "indented root": "  a: b\n",
            "root sequence": "- a\n",
            "empty document": "# rien\n",
        }
        for label, text in cases.items():
            with self.assertRaises(UnsupportedWorkflowYamlError, msg=label):
                parse_workflow_yaml(text)

    def test_errors_name_the_offending_line(self):
        with self.assertRaises(UnsupportedWorkflowYamlError) as raised:
            parse_workflow_yaml("a: b\nc: &x d\n")
        self.assertEqual(raised.exception.line_number, 2)

    def test_dash_followed_only_by_spaces_is_refused_with_its_line(self):
        for item in ("- ", "-  ", "-    "):
            for text, line_number in (
                ("a:\n  " + item + "\n", 2),
                ("a:\n  - b\n  " + item + "\n", 3),
                ("a:\n  " + item + "\n  - b\n", 2),
            ):
                with self.subTest(text=text):
                    try:
                        parse_workflow_yaml(text)
                    except UnsupportedWorkflowYamlError as error:
                        self.assertEqual(error.line_number, line_number)
                    except Exception as error:  # IndexError compris : jamais accepté
                        self.fail(f"{type(error).__name__} instead of UnsupportedWorkflowYamlError: {error}")
                    else:
                        self.fail("accepted an empty sequence item")


_GITHUB_EXPRESSION = re.compile(r"\$\{\{(?:(?!\}\}).)*\bgithub\.")


def _github_expressions_in_run(workflow):
    """Chemins des blocs `run:` contenant une expression `${{ github.* }}`."""

    return [path for path, value in _walk(workflow) if path[-1:] == ("run",) and _GITHUB_EXPRESSION.search(value)]


class TestWorkflow(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")
        self.workflow = parse_workflow_yaml(self.text)
        self.jobs = self.workflow["jobs"]

    def test_only_manual_trigger_and_no_default_permissions(self):
        self.assertEqual(set(self.workflow["on"]), {"workflow_dispatch"})
        self.assertEqual(set(self.workflow["on"]["workflow_dispatch"]["inputs"]), {"approved_manifest_sha256"})
        self.assertEqual(self.workflow["permissions"], {})
        self.assertEqual(self.workflow["concurrency"], {"group": "higgsfield-production", "cancel-in-progress": "false"})

    def test_execute_job_is_gated_by_environment_and_main(self):
        self.assertEqual(set(self.jobs), {"prepare", "execute"})
        execute = self.jobs["execute"]
        self.assertEqual(execute["environment"], "higgsfield-production")
        self.assertEqual(execute["needs"], "prepare")
        self.assertEqual(execute["if"], "github.ref == 'refs/heads/main'")
        self.assertNotIn("environment", self.jobs["prepare"])
        for job in self.jobs.values():
            self.assertEqual(job["permissions"], {"contents": "read"})

    def test_no_secret_is_referenced_while_provider_is_closed(self):
        for path, value in _walk(self.workflow):
            self.assertNotRegex(value, r"(?i)\bsecrets\b", path)

    def test_inputs_reach_scripts_only_through_environment_variables(self):
        uses = 0
        for path, value in _walk(self.workflow):
            if "inputs." in value and path[:1] != ("on",):
                uses += 1
                self.assertEqual(path[-2], "env", path)
                self.assertRegex(path[-1], r"^[A-Z0-9_]+$")
                self.assertRegex(value, r"^\$\{\{ inputs\.[a-z0-9_]+ \}\}$")
        self.assertEqual(uses, 2)

    def test_github_context_never_appears_in_run_blocks_and_goes_through_env(self):
        for path in ALL_WORKFLOWS:
            workflow = parse_workflow_yaml(path.read_text(encoding="utf-8"))
            self.assertEqual(_github_expressions_in_run(workflow), [], path.name)
        step = self.jobs["execute"]["steps"][-1]
        self.assertEqual(step["env"]["APPROVAL_ID"], "gh-${{ github.run_id }}")
        self.assertEqual(step["env"]["RUN_ATTEMPT"], "${{ github.run_attempt }}")
        self.assertIn('--approval-id "$env:APPROVAL_ID"', step["run"])
        self.assertIn('--run-attempt "$env:RUN_ATTEMPT"', step["run"])

    def test_github_expression_in_run_block_is_detected(self):
        for expression in ("${{ github.run_id }}", "${{github.event.inputs.x}}", "${{ format('{0}', github.ref) }}"):
            unsafe = parse_workflow_yaml(
                "jobs:\n"
                "  a:\n"
                "    steps:\n"
                "      - name: Bad\n"
                "        run: |\n"
                f"          echo {expression}\n"
            )
            self.assertEqual(_github_expressions_in_run(unsafe), [("jobs", "a", "steps", 0, "run")], expression)
        safe = parse_workflow_yaml(
            "jobs:\n"
            "  a:\n"
            "    steps:\n"
            "      - name: Good\n"
            "        env:\n"
            "          RUN_ID: ${{ github.run_id }}\n"
            "        run: echo $env:RUN_ID\n"
        )
        self.assertEqual(_github_expressions_in_run(safe), [])

    def test_workflow_runs_the_execute_step_with_a_new_ephemeral_journal(self):
        run = self.jobs["execute"]["steps"][-1]["run"]
        self.assertIn("verify-and-execute", run)
        self.assertIn("--new-journal", run)
        self.assertIn("$env:RUNNER_TEMP/production_audit.jsonl", run)


class TestPinnedActions(unittest.TestCase):
    """Chaque action de chaque workflow du dépôt est épinglée sur un SHA vérifié, avec sa version en commentaire."""

    def test_every_action_is_pinned_to_its_verified_sha(self):
        seen = set()
        for path in ALL_WORKFLOWS:
            for job_name, step in _steps(parse_workflow_yaml(path.read_text(encoding="utf-8"))):
                if "uses" not in step:
                    continue
                action, _, ref = step["uses"].partition("@")
                self.assertIn(action, PINNED_ACTIONS, f"{path.name}/{job_name}: unverified action {action}")
                self.assertEqual(ref, PINNED_ACTIONS[action][0], f"{path.name}/{job_name}")
                seen.add((path.name, action))
        self.assertEqual(seen, {(p.name, a) for p in ALL_WORKFLOWS for a in PINNED_ACTIONS})

    def test_every_pin_carries_its_version_comment(self):
        count = 0
        for path in ALL_WORKFLOWS:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith(("- uses:", "uses:")):
                    count += 1
                    action = line.split("uses:", 1)[1].split("@", 1)[0].strip()
                    sha, version = PINNED_ACTIONS[action]
                    self.assertTrue(line.rstrip().endswith(f"@{sha} # {version}"), line)
        self.assertEqual(count, 6)

    def test_checkout_never_persists_credentials_in_any_workflow(self):
        for path in ALL_WORKFLOWS:
            for job_name, step in _steps(parse_workflow_yaml(path.read_text(encoding="utf-8"))):
                if step.get("uses", "").startswith("actions/checkout@"):
                    self.assertEqual(step.get("with", {}).get("persist-credentials"), "false", f"{path.name}/{job_name}")

    def test_ci_workflow_structure_is_unchanged_apart_from_pins(self):
        ci = parse_workflow_yaml(CI_WORKFLOW.read_text(encoding="utf-8"))
        self.assertEqual(ci["on"], {"push": {"branches": ["main"]}, "pull_request": {"branches": ["main"]}, "workflow_dispatch": None})
        self.assertEqual(ci["permissions"], {"contents": "read"})
        runs = [step.get("run") for step in ci["jobs"]["tests"]["steps"] if "run" in step]
        self.assertEqual(runs, ["python -m unittest discover -s tests -t . -v", "python scripts/architecture_audit.py"])
        for path, value in _walk(ci):
            self.assertNotRegex(value, r"(?i)\bsecrets\b", path)


if __name__ == "__main__":
    unittest.main()
