"""
Tests — Phase C : invariants « aucune identité authentifiée, NO-GO
maintenu » (cf. docs/phase_c_authorizer_identity_design.md).

Ces gardes figent l'état honnête du projet tant qu'aucune phase dédiée
n'implémente une identité d'autorisateur :

1. aucun code de production n'importe de bibliothèque d'authentification
   ni de signature -- rien ne peut donc prétendre authentifier ;
2. `note` n'est lu par aucune couche de vérification : un texte qui
   prétend une identité ne change aucune décision ;
3. une autorisation construite par du code quelconque est acceptée par
   la Gate (Mock) -- la condition 1 doit donc rester un motif de NO-GO
   dans la décision de Phase A ;
4. les quatre verrous d'exécution restent fermés.

MOCK-ONLY : `MockHiggsfieldProvider`, store en mémoire, et un
`subprocess` factice qui échoue s'il est appelé. Aucun réseau, aucune
génération, aucun accès à `state/`.
"""

import ast
import dataclasses
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import integrations.higgsfield.client as client_mod
from agents.generation_approval_gate import (
    AUTHORIZATION_CONTENT_DIGEST_FIELDS,
    GenerationApprovalDecision,
    GenerationApprovalGate,
    GenerationRequest,
    RealGenerationAuthorization,
)
from integrations.higgsfield.client import HiggsfieldClient
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from tests.authorization_content_helpers import bound_authorization, content_media

DECISION_DOC = PROJECT_ROOT / "docs" / "phase_a_real_generation_decision.md"
DESIGN_DOC = PROJECT_ROOT / "docs" / "phase_c_authorizer_identity_design.md"

# Modules dont l'import signalerait l'introduction d'un mécanisme
# d'authentification ou de signature. Leur arrivée en production doit
# passer par une phase dédiée qui met à jour ce test ET la décision de
# Phase A -- jamais silencieusement.
AUTHENTICATION_MODULES = frozenset(
    {"hmac", "secrets", "getpass", "jwt", "cryptography", "nacl", "keyring", "pyotp", "ssl"}
)

# Couches qui vérifient ou transportent l'autorisation.
AUTHORIZATION_VERIFIERS = (
    "agents/generation_approval_gate.py",
    "agents/activation_contract.py",
    "agents/controlled_real_provider_activation.py",
    "agents/generation_job_service.py",
    "agents/executed_request_store.py",
    "agents/activation_readiness.py",
    "agents/activation_eligibility.py",
    "agents/human_authorization_handoff.py",
    "agents/controlled_activation_composition.py",
    "integrations/higgsfield/provider.py",
)


def _production_files():
    for base in ("agents", "integrations", "scripts"):
        yield from sorted((PROJECT_ROOT / base).rglob("*.py"))
    yield PROJECT_ROOT / "director.py"


def _tree(relative_path: str) -> ast.Module:
    return ast.parse((PROJECT_ROOT / relative_path).read_text(encoding="utf-8-sig"))


def _method(tree: ast.Module, class_name: str, method_name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method_name:
                    return item
    raise AssertionError(f"{class_name}.{method_name} not found")


def _statements_without_docstring(function: ast.FunctionDef):
    return [
        s for s in function.body
        if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))
    ]


def _table_row(markdown: str, section_heading: str, row_prefix: str) -> str:
    section = markdown.split(section_heading, 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith(row_prefix)]
    if len(rows) != 1:
        raise AssertionError(f"expected exactly one row starting with {row_prefix!r} in {section_heading!r}, got {rows}")
    return rows[0]


# ----------------------------------------------------------------------
# 1. Aucun mécanisme d'authentification dans le code de production
# ----------------------------------------------------------------------


class NoAuthenticationMechanismInProduction(unittest.TestCase):
    def test_no_authentication_or_signature_module_is_imported(self):
        offenders = []
        for path in _production_files():
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                else:
                    continue
                for name in names:
                    if name.split(".")[0] in AUTHENTICATION_MODULES:
                        offenders.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}:{node.lineno} imports {name}")
        self.assertEqual(
            offenders, [],
            "an authentication/signature module entered production code: a dedicated "
            "phase must update this test and docs/phase_a_real_generation_decision.md",
        )

    def test_authorization_carries_no_identity_proof(self):
        """Les seuls champs de `RealGenerationAuthorization` sont ceux de
        P2.11 et de la Phase B : rien qui porte une preuve d'identité
        (sujet authentifié, signature, jeton)."""

        self.assertEqual(
            {f.name for f in dataclasses.fields(RealGenerationAuthorization)},
            {
                "request_id", "authorized_by_human", "authorization_id", "authorized_at", "note",
                *AUTHORIZATION_CONTENT_DIGEST_FIELDS,
            },
        )


# ----------------------------------------------------------------------
# 2. `note` n'est pas une preuve d'identité
# ----------------------------------------------------------------------


class NoteIsNotAnIdentityProof(unittest.TestCase):
    def test_no_verification_layer_reads_note(self):
        offenders = []
        for relative_path in AUTHORIZATION_VERIFIERS:
            for node in ast.walk(_tree(relative_path)):
                if isinstance(node, ast.Attribute) and node.attr == "note":
                    offenders.append(f"{relative_path}:{node.lineno} reads .note")
                elif (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in {"getattr", "hasattr"}
                    and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value == "note"
                ):
                    offenders.append(f"{relative_path}:{node.lineno} {node.func.id}(..., 'note')")
        self.assertEqual(offenders, [])

    def _request(self, authorization):
        unbound = GenerationRequest(
            **content_media(),
            request_id="phase-c-note",
            job_type="seedance_2_0",
            prompt="Phase C mock-only prompt.",
            duration=5,
            approved=True,
        )
        return dataclasses.replace(
            unbound, real_generation_authorization=bound_authorization(unbound, authorization)
        )

    def test_identity_claims_in_note_never_change_the_gate_decision(self):
        gate = GenerationApprovalGate(MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0))
        claims = (
            "",
            "authenticated owner, identity verified",
            "signed-by: project-owner; signature=deadbeef",
        )
        for authorized_by_human, expected in ((True, GenerationApprovalDecision.APPROVED),
                                              (False, GenerationApprovalDecision.NEEDS_APPROVAL)):
            decisions = set()
            for note in claims:
                with self.subTest(authorized_by_human=authorized_by_human, note=note):
                    authorization = RealGenerationAuthorization(
                        request_id="phase-c-note",
                        authorized_by_human=authorized_by_human,
                        authorization_id=f"phase-c-note-{int(authorized_by_human)}",
                        authorized_at=RealGenerationAuthorization(
                            request_id="x", authorized_by_human=True
                        ).authorized_at,
                        note=note,
                    )
                    result = gate.evaluate(self._request(authorization))
                    self.assertEqual(result.decision, expected)
                    decisions.add((result.decision, tuple(result.reasons)))
            self.assertEqual(len(decisions), 1, decisions)


# ----------------------------------------------------------------------
# 3. La condition 1 reste un motif de NO-GO
# ----------------------------------------------------------------------


class IdentityConditionRemainsNoGo(unittest.TestCase):
    def test_gate_cannot_distinguish_a_human_from_in_process_code(self):
        """Une autorisation construite ici même, par du code de test, sans
        aucun humain, est APPROVED (Mock) : l'identité n'est pas
        authentifiée. Tant que c'est vrai, la décision de Phase A doit
        garder la condition 1 comme motif de NO-GO."""

        unbound = GenerationRequest(
            **content_media(),
            request_id="phase-c-no-human",
            job_type="seedance_2_0",
            prompt="Phase C mock-only prompt.",
            duration=5,
            approved=True,
        )
        request = dataclasses.replace(
            unbound, real_generation_authorization=bound_authorization(unbound)
        )
        gate = GenerationApprovalGate(MockHiggsfieldProvider(cost_per_job=10.0, available_credits=100.0))
        self.assertEqual(gate.evaluate(request).decision, GenerationApprovalDecision.APPROVED)

        decision = DECISION_DOC.read_text(encoding="utf-8")
        row = _table_row(decision, "## Lacunes à combler", "| 1. Identité authentifiée |")
        self.assertIn("**NO-GO**", row)
        self.assertIn("(phase_c_authorizer_identity_design.md)", row)

    def test_decision_remains_no_go_with_provider_closed(self):
        decision = DECISION_DOC.read_text(encoding="utf-8")
        section = decision.split("## Décision", 1)[1].split("\n## ", 1)[0]
        self.assertRegex(section, r"\*\*NO-GO pour toute activation réelle[^*]*Provider = CLOSED\.\*\*")
        conditions = decision.split("## Conditions préalables", 1)[1].split("\n## ", 1)[0]
        self.assertRegex(conditions, r"(?m)^1\. \*\*Identité authentifiée de l'autorisateur\.\*\*")

    def test_design_document_keeps_condition_open_and_links_back(self):
        design = DESIGN_DOC.read_text(encoding="utf-8")
        intro = design.split("## 1.", 1)[0]
        self.assertIn("(phase_a_real_generation_decision.md)", intro)
        self.assertIn("**reste ouverte**", intro)
        self.assertIn("**NO-GO**", intro)
        self.assertIn("**Provider = CLOSED**", intro)
        for link in re.findall(r"\]\(([^)#]+\.md)\)", design):
            self.assertTrue((DESIGN_DOC.parent / link).is_file(), link)


# ----------------------------------------------------------------------
# 4. Les quatre verrous d'exécution restent fermés
# ----------------------------------------------------------------------


def _is_disabled_error_raise(node: ast.AST) -> bool:
    if not isinstance(node, ast.Raise) or node.exc is None:
        return False
    target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
    return isinstance(target, ast.Name) and target.id == "HiggsfieldRealGenerationDisabledError"


class FourExecutionLocksRemainClosed(unittest.TestCase):
    def test_lock_1_p2_26_refuses_the_real_provider_by_method_identity(self):
        fresh = _method(
            _tree("agents/controlled_real_provider_activation.py"),
            "ControlledRealProviderActivationService",
            "_fresh_violations",
        )
        guards = [
            node for node in ast.walk(fresh)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.Is)
            and ast.unparse(node.test.left) == "type(provider).create_job"
            and ast.unparse(node.test.comparators[0]) == "HiggsfieldProvider.create_job"
        ]
        self.assertEqual(len(guards), 1)
        appended = [
            n for n in ast.walk(guards[0])
            if isinstance(n, ast.Call) and ast.unparse(n.func) == "reasons.append"
        ]
        self.assertTrue(appended, "the real-provider identity check must add a refusal reason")

    def test_lock_2_real_provider_create_job_always_raises(self):
        create_job = _method(_tree("integrations/higgsfield/provider.py"), "HiggsfieldProvider", "create_job")
        statements = _statements_without_docstring(create_job)
        self.assertTrue(_is_disabled_error_raise(statements[-1]))
        self.assertFalse([n for n in ast.walk(create_job) if isinstance(n, ast.Return)])
        client_accesses = [
            n for n in ast.walk(create_job)
            if isinstance(n, ast.Attribute) and n.attr == "client"
            and isinstance(n.value, ast.Name) and n.value.id == "self"
        ]
        self.assertEqual(client_accesses, [], "HiggsfieldProvider.create_job must never touch self.client")

    def test_lock_3_client_create_job_is_a_single_raise(self):
        create_job = _method(_tree("integrations/higgsfield/client.py"), "HiggsfieldClient", "create_job")
        statements = _statements_without_docstring(create_job)
        self.assertEqual(len(statements), 1)
        self.assertTrue(_is_disabled_error_raise(statements[0]))

    def test_lock_4_client_run_refuses_generation_before_any_process(self):
        self.assertNotIn(("generate", "create"), client_mod._READ_ONLY_CLI_VERBS)
        exploding = mock.Mock(spec=["run", "TimeoutExpired"])
        exploding.run.side_effect = AssertionError("a process was launched")
        exploding.TimeoutExpired = client_mod.subprocess.TimeoutExpired
        with mock.patch.object(client_mod, "subprocess", exploding):
            client = HiggsfieldClient()
            with self.assertRaises(HiggsfieldRealGenerationDisabledError):
                client.run("generate", "create", "seedance_2_0")
            with self.assertRaises(HiggsfieldRealGenerationDisabledError):
                client.create_job("seedance_2_0", "P")
        exploding.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
