"""
Tests — Phase E1 : invariants documentaires (cf.
docs/phase_e_authorization_limits_ceiling_revocation_shutdown_design.md).

La Phase E1 n'ajoute que de la documentation. Ces gardes figent ce que
les documents doivent continuer à dire tant qu'aucune décision écrite
distincte n'existe :

1. le NO-GO et `Provider = CLOSED` restent explicites ;
2. les statuts des conditions restent exacts : 1, 3, 5 et 7 ouvertes,
   2 partiellement traitée -- et la Phase E1 ne prétend en résoudre
   aucune ;
3. la décision de Phase A renvoie au document de la Phase E1, qui
   renvoie lui-même à la conception de la Phase C pour la condition 1 ;
4. aucun montant de plafond n'est inventé ;
5. la décision de Phase A décrit les protections de la Phase D qui
   existent réellement dans le code.

LECTURE SEULE : ces tests lisent des fichiers du dépôt et n'importent
aucun module de production. Aucun Provider, aucun réseau, aucun
sous-processus, aucun accès à `state/`.
"""

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS = PROJECT_ROOT / "docs"

DECISION_NAME = "phase_a_real_generation_decision.md"
IDENTITY_DESIGN_NAME = "phase_c_authorizer_identity_design.md"
E1_NAME = "phase_e_authorization_limits_ceiling_revocation_shutdown_design.md"

DECISION_DOC = DOCS / DECISION_NAME
IDENTITY_DESIGN_DOC = DOCS / IDENTITY_DESIGN_NAME
E1_DOC = DOCS / E1_NAME

GAPS_HEADING = "## Lacunes à combler"
E1_STATUS_HEADING = "## État des conditions traitées ici"

OPEN = "**Ouverte**"
PARTIAL = "**Partiellement traitée**"

# Conditions dont le statut est figé par la Phase E1, avec le préfixe de
# leur ligne dans chacun des deux tableaux.
EXPECTED_STATUSES = (
    ("| 1. Identité authentifiée |", OPEN),
    ("| 3. Plafond de crédits |", OPEN),
    ("| 5. Révocation et audit |", OPEN),
    ("| 7. Arrêt et refermeture |", OPEN),
)
DECISION_PARTIAL_ROW = "| 2. Autorisation expirante |"
E1_PARTIAL_ROW = "| 2. Autorisation explicite, liée, courte et à usage unique |"

# Un nombre suivi de « crédits » : la forme que prendrait un montant.
CREDIT_AMOUNT = re.compile(r"\d+(?:[\s.,]\d+)*\s*(?:crédits?|credits?)\b", re.IGNORECASE)
# Une valeur numérique affectée au paramètre de plafond.
CEILING_ASSIGNMENT = re.compile(r"max_cost_credits_per_request\s*[=:]\s*\.?\d")
# Références légitimes contenant des chiffres dans les passages consacrés
# au plafond : numéros de condition et de section, phases P2.x, exigences
# L de la Phase C et limites A2-x de la Phase E1. Tout autre chiffre y est
# refusé.
ALLOWED_NUMERIC_REFERENCES = re.compile(
    r"conditions? \d|sections? \d|\bP\d\.\d+\b|\bL\d\b|\bA2-[a-j]\b"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(markdown: str, heading: str) -> str:
    """Corps de la section `heading`, jusqu'au prochain titre de niveau 2."""

    parts = markdown.split(heading, 1)
    if len(parts) != 2:
        raise AssertionError(f"section {heading!r} not found")
    return parts[1].split("\n## ", 1)[0]


def _table_row(markdown: str, heading: str, row_prefix: str) -> str:
    rows = [line for line in _section(markdown, heading).splitlines() if line.startswith(row_prefix)]
    if len(rows) != 1:
        raise AssertionError(f"expected exactly one row starting with {row_prefix!r} in {heading!r}, got {rows}")
    return rows[0]


def _cells(row: str):
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def _digits_outside_allowed_references(text: str):
    return re.findall(r"\d+", ALLOWED_NUMERIC_REFERENCES.sub("", text))


# ----------------------------------------------------------------------
# 1. NO-GO et Provider = CLOSED restent explicites
# ----------------------------------------------------------------------


class NoGoAndClosedProviderStayExplicit(unittest.TestCase):
    def test_decision_states_no_go_and_provider_closed(self):
        decision = _read(DECISION_DOC)
        self.assertRegex(
            _section(decision, "## Décision"),
            r"\*\*NO-GO pour toute activation réelle[^*]*Provider = CLOSED\.\*\*",
        )
        self.assertIn(
            "**Provider = CLOSED, génération réelle = 0, crédits = 0.**",
            _section(decision, "## Révision de cette décision"),
        )

    def test_decision_status_is_still_in_force(self):
        self.assertIn("- **Statut :** décision en vigueur\n", _read(DECISION_DOC))

    def test_e1_states_no_go_and_provider_closed(self):
        e1 = _read(E1_DOC)
        intro = e1.split("\n## ", 1)[0]
        self.assertIn("**NO-GO**", intro)
        self.assertIn("**Provider = CLOSED**", intro)
        self.assertTrue(
            e1.rstrip().endswith("**Provider = CLOSED · Real generation = 0 · Credits = 0**"),
            "the Phase E1 document must end on the closed-provider statement",
        )

    def test_e1_is_a_design_document_that_chooses_nothing(self):
        e1 = _read(E1_DOC)
        intro = e1.split("\n## ", 1)[0]
        self.assertIn("Il n'implémente rien, n'autorise rien et ne choisit aucune option.", intro)
        self.assertIn("Il ne résout aucune de ces conditions.", intro)
        for phrase in ("option retenue :", "option choisie :", "option recommandée", "décision prise :"):
            self.assertNotIn(phrase, e1.lower())


# ----------------------------------------------------------------------
# 2. Statuts exacts des conditions
# ----------------------------------------------------------------------


class ConditionStatusesStayExact(unittest.TestCase):
    def test_open_conditions_are_marked_open_in_both_documents(self):
        for path, heading in ((DECISION_DOC, GAPS_HEADING), (E1_DOC, E1_STATUS_HEADING)):
            markdown = _read(path)
            for row_prefix, expected in EXPECTED_STATUSES:
                with self.subTest(document=path.name, condition=row_prefix):
                    self.assertEqual(_cells(_table_row(markdown, heading, row_prefix))[1], expected)

    def test_condition_2_is_partially_addressed_in_the_decision(self):
        cells = _cells(_table_row(_read(DECISION_DOC), GAPS_HEADING, DECISION_PARTIAL_ROW))
        self.assertEqual(cells[1], PARTIAL)
        gap = cells[2]
        # Ce qui est présent...
        self.assertIn("Expiration vérifiée depuis Phase B", gap)
        self.assertIn("L'usage unique est désormais appliqué **localement**", gap)
        self.assertIn("liée aux hashes du prompt, de l'avatar et de la référence visage", gap)
        # ... et ce qui reste ouvert.
        self.assertIn("Restent ouverts :", gap)
        self.assertGreaterEqual(gap.count("<br>•"), 5)

    def test_condition_2_is_partially_addressed_in_e1(self):
        cells = _cells(_table_row(_read(E1_DOC), E1_STATUS_HEADING, E1_PARTIAL_ROW))
        self.assertEqual(cells[1], PARTIAL)
        self.assertIn("Expiration, usage unique et liaison au contenu sont présentes", cells[2])
        self.assertIn("limites restantes", cells[2])

    def test_e1_status_table_covers_exactly_the_five_conditions(self):
        rows = [
            line for line in _section(_read(E1_DOC), E1_STATUS_HEADING).splitlines()
            if re.match(r"\| \d\. ", line)
        ]
        self.assertEqual([row[2] for row in rows], ["1", "2", "3", "5", "7"])
        self.assertEqual(
            [_cells(row)[1] for row in rows],
            [OPEN, PARTIAL, OPEN, OPEN, OPEN],
        )

    def test_e1_never_claims_to_resolve_a_condition(self):
        e1 = _read(E1_DOC)
        self.assertIsNone(
            re.search(
                r"conditions? \d(?:, \d| et \d)* (?:est|sont|devient|deviennent) "
                r"(?:désormais )?(?:satisfaites?|remplies?|résolues?|fermées?)",
                e1,
                re.IGNORECASE,
            )
        )
        closing = _section(e1, "## 8. Ce que cette phase ne fait pas")
        self.assertIn(
            "Les conditions 1, 3, 5 et 7 restent **ouvertes**, la condition 2 reste "
            "**partiellement traitée**, et le **NO-GO** reste en vigueur.",
            closing,
        )

    def test_decision_does_not_say_e1_resolves_anything(self):
        gaps = _section(_read(DECISION_DOC), GAPS_HEADING)
        self.assertIn("ne choisit rien, n'implémente rien et ne résout aucune condition", gaps)
        self.assertIn(
            "La condition reste ouverte",
            _table_row(_read(DECISION_DOC), GAPS_HEADING, "| 3. Plafond de crédits |"),
        )


# ----------------------------------------------------------------------
# 3. Liens entre les documents
# ----------------------------------------------------------------------


class DocumentsLinkToEachOther(unittest.TestCase):
    def test_decision_links_to_e1(self):
        decision = _read(DECISION_DOC)
        self.assertTrue(E1_DOC.is_file())
        self.assertIn(f"({E1_NAME})", _section(decision, GAPS_HEADING))
        for row_prefix in (
            DECISION_PARTIAL_ROW,
            "| 3. Plafond de crédits |",
            "| 5. Révocation et audit |",
            "| 7. Arrêt et refermeture |",
        ):
            with self.subTest(condition=row_prefix):
                self.assertIn(f"({E1_NAME})", _table_row(decision, GAPS_HEADING, row_prefix))

    def test_decision_still_links_condition_1_to_phase_c(self):
        row = _table_row(_read(DECISION_DOC), GAPS_HEADING, "| 1. Identité authentifiée |")
        self.assertIn(f"({IDENTITY_DESIGN_NAME})", row)
        self.assertIn("**NO-GO**", row)

    def test_e1_links_back_to_the_decision_and_sends_condition_1_to_phase_c(self):
        e1 = _read(E1_DOC)
        self.assertIn(f"({DECISION_NAME})", e1.split("\n## ", 1)[0])
        self.assertIn(
            f"({IDENTITY_DESIGN_NAME})",
            _table_row(e1, E1_STATUS_HEADING, "| 1. Identité authentifiée |"),
        )
        condition_1 = _section(e1, "## 2. Condition 1")
        self.assertIn(f"({IDENTITY_DESIGN_NAME})", condition_1)
        self.assertIn("Elle reste **ouverte**", condition_1)

    def test_every_relative_markdown_link_resolves(self):
        for path in (DECISION_DOC, IDENTITY_DESIGN_DOC, E1_DOC):
            for link in re.findall(r"\]\(([^)#]+\.md)\)", _read(path)):
                with self.subTest(document=path.name, link=link):
                    self.assertTrue((path.parent / link).is_file())


# ----------------------------------------------------------------------
# 4. Aucun montant de plafond inventé
# ----------------------------------------------------------------------


class NoCeilingAmountIsInvented(unittest.TestCase):
    def test_no_document_states_a_credit_amount(self):
        for path in (DECISION_DOC, IDENTITY_DESIGN_DOC, E1_DOC):
            markdown = _read(path)
            with self.subTest(document=path.name):
                self.assertEqual(CREDIT_AMOUNT.findall(markdown), [])
                self.assertEqual(CEILING_ASSIGNMENT.findall(markdown), [])

    def test_decision_says_no_amount_is_set(self):
        decision = _read(DECISION_DOC)
        conditions = _section(decision, "## Conditions préalables")
        condition_3 = [line for line in conditions.splitlines() if line.startswith("3. **Plafond de crédits par requête.**")]
        self.assertEqual(len(condition_3), 1)
        self.assertIn("**Aucun montant n'est fixé par ce document.**", condition_3[0])
        self.assertEqual(_digits_outside_allowed_references(condition_3[0][len("3. "):]), [])

        cells = _cells(_table_row(decision, GAPS_HEADING, "| 3. Plafond de crédits |"))
        self.assertIn("Aucun montant n'est fixé", cells[2])
        self.assertEqual(_digits_outside_allowed_references(cells[2]), [])

    def test_e1_ceiling_section_contains_no_number_at_all(self):
        ceiling = _section(_read(E1_DOC), "## 4. Condition 3 — plafond de crédits")
        self.assertIn("**Aucun montant n'est fixé par ce document.**", ceiling)
        self.assertIn("appartient au propriétaire du projet", ceiling)
        self.assertEqual(
            _digits_outside_allowed_references(ceiling), [],
            "the ceiling section must not contain any figure: no amount is chosen by Phase E1",
        )

    def test_the_digit_guard_would_catch_an_amount(self):
        """Garde de la garde : un montant écrit dans ces passages serait
        bien détecté, sous les formes les plus probables."""

        for sample in ("plafond de 100 crédits", "Plafond : 50", "max 12.5 credits", "1 000 crédits par mois"):
            with self.subTest(sample=sample):
                self.assertNotEqual(_digits_outside_allowed_references(sample), [])
        for sample in ("100 crédits", "12.5 credits", "1 000 crédits", "1\u00a0000 Crédits"):
            with self.subTest(sample=sample):
                self.assertNotEqual(CREDIT_AMOUNT.findall(sample), [])
        self.assertNotEqual(CEILING_ASSIGNMENT.findall("max_cost_credits_per_request=100"), [])
        self.assertEqual(CEILING_ASSIGNMENT.findall("GenerationApprovalGate(max_cost_credits_per_request=...)"), [])
        self.assertEqual(_digits_outside_allowed_references("condition 3, section 4, P2.26, L1, A2-g"), [])


# ----------------------------------------------------------------------
# 5. Protections de la Phase D décrites fidèlement
# ----------------------------------------------------------------------


class PhaseDProtectionsAreDescribedFaithfully(unittest.TestCase):
    # Nom documenté -> (fichier qui le définit, définition attendue).
    DOCUMENTED_DEFINITIONS = {
        "may_reach_create_job": ("agents/generation_approval_gate.py", "def may_reach_create_job(provider)"),
        "is_recognized_test_mock_provider": (
            "agents/generation_approval_gate.py", "def is_recognized_test_mock_provider(provider)",
        ),
        "is_exact_disabled_real_provider": (
            "agents/generation_approval_gate.py", "def is_exact_disabled_real_provider(provider)",
        ),
        "GenerationJobProviderNotAllowedError": (
            "agents/generation_job_service.py",
            "class GenerationJobProviderNotAllowedError(GenerationJobExecutionError):",
        ),
        "ActivationReadinessEvaluator._check_provider": (
            "agents/activation_readiness.py", "def _check_provider(self):",
        ),
        "ControlledRealProviderActivationService._fresh_violations": (
            "agents/controlled_real_provider_activation.py", "def _fresh_violations(",
        ),
    }

    def _safe_provider_row(self) -> str:
        return _table_row(_read(DECISION_DOC), "## Contrôles déjà présents", "| Provider explicitement sûr (Phase D) |")

    def test_documented_names_exist_in_the_code(self):
        row = self._safe_provider_row()
        for name, (relative_path, definition) in self.DOCUMENTED_DEFINITIONS.items():
            with self.subTest(name=name):
                self.assertIn(f"`{name}", row)
                self.assertIn(f"`{relative_path}`", row)
                self.assertIn(definition, (PROJECT_ROOT / relative_path).read_text(encoding="utf-8-sig"))

    def test_safe_provider_prechecks_are_documented(self):
        mechanism = _cells(self._safe_provider_row())[1]
        self.assertIn("`GenerationJobService.execute()` lève `GenerationJobProviderNotAllowedError` **avant toute autre étape**", mechanism)
        self.assertIn("rien n'est évalué, consommé ni écrit", mechanism)
        self.assertIn("`NOT_EXECUTED`", mechanism)
        self.assertEqual(mechanism.count("<br>•"), 3, "three pre-checks are documented")
        self.assertIn("Cette garde n'ouvre rien", mechanism)

    def test_execute_checks_the_provider_before_anything_else(self):
        """Ce que le document affirme (« avant toute autre étape ») est
        vrai dans le code : la garde précède le verrou et la Gate."""

        source = (PROJECT_ROOT / "agents/generation_job_service.py").read_text(encoding="utf-8-sig")
        guard = source.index("if not may_reach_create_job(self.provider):")
        for later_step in (
            "with self.lock.acquire(request.request_id):",
            "approval = self.gate.evaluate(request)",
            "if activation_contract is not None and self.activation_service is None:",
        ):
            with self.subTest(step=later_step):
                self.assertLess(guard, source.index(later_step))

    def test_four_locks_are_still_listed_and_the_guard_replaces_none(self):
        section = _section(_read(DECISION_DOC), "## Décision")
        self.assertEqual(len(re.findall(r"(?m)^[1-4]\. `", section)), 4)
        self.assertIn("une garde s'ajoute en amont de ces verrous sans en remplacer aucun", section)
        self.assertIn("`may_reach_create_job()`", section)
        self.assertIn("`GenerationJobProviderNotAllowedError`", section)


if __name__ == "__main__":
    unittest.main()
