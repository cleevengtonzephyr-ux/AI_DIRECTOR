"""
Tests — Architecture Drift Detector (Phase P3.31).

Aucun test ici n'écrit dans `state/`, ne touche un vrai verrou de
production, ne modifie un fichier P2 réel, ni n'appelle le CLI
Higgsfield. Les scénarios de dérive utilisent exclusivement des
fixtures Python synthétiques dans des répertoires temporaires
(`tempfile.TemporaryDirectory`) -- jamais le repository réel, sauf pour
le test d'intégration explicite qui vérifie que le repository RÉEL
actuel ne présente aucune dérive actionnable (lecture seule).
"""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.architecture_drift_detector import (
    ArchitectureDriftDetector,
    DriftStatus,
    Severity,
)
from agents.canonical_architecture_contract import CANONICAL_ARCHITECTURE_CONTRACT


def _write(root: Path, relative_path: str, content: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class _TempRepoTestCase(unittest.TestCase):
    """Base commune : un répertoire temporaire par test, jamais partagé,
    jamais laissé sur disque après le test (`tempfile.TemporaryDirectory`
    nettoie automatiquement, y compris si le test échoue)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _detector(self) -> ArchitectureDriftDetector:
        return ArchitectureDriftDetector(root=self.root)


class TestCanonicalArchitecturePasses(unittest.TestCase):
    """1. L'architecture canonique actuelle (repository réel, lecture
    seule) ne présente aucune dérive ACTIONNABLE."""

    def test_real_repository_has_no_actionable_drift(self):
        detector = ArchitectureDriftDetector(contract=CANONICAL_ARCHITECTURE_CONTRACT)
        report = detector.analyze()

        self.assertEqual(report.files_unreadable, ())
        self.assertFalse(
            report.has_actionable_drift,
            f"Unexpected actionable drift in the real repository: "
            f"{[ (f.code, f.file, f.line) for f in report.findings if f.severity != Severity.INFORMATIONAL ]}",
        )

    def test_real_repository_status_is_literally_no_drift(self):
        """Phase P3.32 (Section 16/21) : le repository canonique actuel
        doit retourner le statut littéral `NO_DRIFT`, pas seulement
        "aucune dérive actionnable" -- un finding purement
        `INFORMATIONAL` (le homonyme `job_monitor.py::create_job`,
        cf. test ci-dessous) ne gouverne jamais `status`."""

        detector = ArchitectureDriftDetector(contract=CANONICAL_ARCHITECTURE_CONTRACT)
        report = detector.analyze()

        self.assertEqual(report.status, DriftStatus.NO_DRIFT)

    def test_real_repository_has_exactly_one_production_create_job_call_site(self):
        """Phase P3.32 (Section 16/21) : confirmation explicite de la
        cardinalité, indépendamment du statut global."""

        detector = ArchitectureDriftDetector(contract=CANONICAL_ARCHITECTURE_CONTRACT)
        report = detector.analyze()

        cardinality_violations = [
            f for f in report.findings if f.code == "CREATE_JOB_CARDINALITY_VIOLATION"
        ]
        relocations = [f for f in report.findings if f.code == "CREATE_JOB_CALLSITE_RELOCATED"]
        self.assertEqual(cardinality_violations, [])
        self.assertEqual(relocations, [])

    def test_real_repository_only_known_informational_findings(self):
        detector = ArchitectureDriftDetector(contract=CANONICAL_ARCHITECTURE_CONTRACT)
        report = detector.analyze()

        for finding in report.findings:
            self.assertEqual(finding.severity, Severity.INFORMATIONAL)
            self.assertEqual(finding.code, "CREATE_JOB_NAMESAKE_UNRELATED")
            self.assertEqual(finding.file, "agents/job_monitor.py")


class TestBusinessToHiggsfieldDetected(_TempRepoTestCase):
    """2. Business -> Higgsfield est détecté."""

    def test_business_agent_importing_higgsfield_is_critical_drift(self):
        _write(
            self.root,
            "agents/strategy_agent.py",
            "import integrations.higgsfield.provider\n\n\ndef run():\n    pass\n",
        )

        report = self._detector().analyze()

        self.assertEqual(report.status, DriftStatus.DRIFT_DETECTED)
        codes = {f.code for f in report.findings}
        self.assertIn("BUS_FORBIDDEN_IMPORT", codes)
        hit = next(f for f in report.findings if f.code == "BUS_FORBIDDEN_IMPORT")
        self.assertEqual(hit.severity, Severity.CRITICAL)
        self.assertEqual(hit.file, "agents/strategy_agent.py")
        self.assertEqual(hit.line, 1)


class TestBusinessToGenerationJobServiceDetected(_TempRepoTestCase):
    """3. Business -> GenerationJobService est détecté."""

    def test_business_agent_importing_generation_job_service_is_critical_drift(self):
        _write(
            self.root,
            "agents/content_agent.py",
            "from agents.generation_job_service import GenerationJobService\n",
        )

        report = self._detector().analyze()

        codes = {f.code for f in report.findings}
        self.assertIn("BUS_FORBIDDEN_IMPORT", codes)
        self.assertTrue(report.has_actionable_drift)


class TestProductionModelingBypassDetected(_TempRepoTestCase):
    """4. Production -> GenerationJobService direct (hors bridge) est détecté."""

    def test_production_modeling_importing_generation_job_service_is_critical_drift(self):
        _write(
            self.root,
            "agents/activation_eligibility.py",
            "import agents.generation_job_service\n",
        )

        report = self._detector().analyze()

        codes = {f.code for f in report.findings}
        self.assertIn("PM_FORBIDDEN_IMPORT", codes)
        hit = next(f for f in report.findings if f.code == "PM_FORBIDDEN_IMPORT")
        self.assertEqual(hit.severity, Severity.CRITICAL)

    def test_production_modeling_type_only_import_is_not_flagged(self):
        """Un import de TYPE (isinstance) reste légitime -- seule une
        construction (Call) doit être signalée, jamais un simple import
        de classe utilisée en isinstance (cf. activation_eligibility.py
        réel, qui importe RequestScopedActivationContract comme type)."""

        _write(
            self.root,
            "agents/activation_eligibility.py",
            (
                "from agents.activation_contract import RequestScopedActivationContract\n\n\n"
                "def check(x):\n"
                "    return isinstance(x, RequestScopedActivationContract)\n"
            ),
        )

        report = self._detector().analyze()

        self.assertEqual(report.status, DriftStatus.NO_DRIFT)
        self.assertEqual(report.findings, ())


class TestSecondCreateJobCallSiteDetected(_TempRepoTestCase):
    """5. Un second create_job() call-site est détecté."""

    def test_second_relevant_create_job_call_site_is_critical_drift(self):
        _write(
            self.root,
            "agents/generation_job_service.py",
            (
                "from integrations.higgsfield.provider import BaseHiggsfieldProvider\n\n\n"
                "class GenerationJobService:\n"
                "    def execute(self, provider):\n"
                "        return provider.create_job('seedance_2_0', 'p')\n"
            ),
        )
        _write(
            self.root,
            "agents/rogue_executor.py",
            (
                "import integrations.higgsfield.provider\n\n\n"
                "def run(provider):\n"
                "    return provider.create_job('seedance_2_0', 'p')\n"
            ),
        )

        report = self._detector().analyze()

        self.assertTrue(report.has_actionable_drift)
        cardinality_findings = [
            f for f in report.findings if f.code == "CREATE_JOB_CARDINALITY_VIOLATION"
        ]
        self.assertEqual(len(cardinality_findings), 2)
        for finding in cardinality_findings:
            self.assertEqual(finding.severity, Severity.CRITICAL)
        files_hit = {f.file for f in cardinality_findings}
        self.assertEqual(
            files_hit, {"agents/generation_job_service.py", "agents/rogue_executor.py"}
        )

    def test_single_relevant_create_job_call_site_is_not_drift(self):
        _write(
            self.root,
            "agents/generation_job_service.py",
            (
                "from integrations.higgsfield.provider import BaseHiggsfieldProvider\n\n\n"
                "class GenerationJobService:\n"
                "    def execute(self, provider):\n"
                "        return provider.create_job('seedance_2_0', 'p')\n"
            ),
        )

        report = self._detector().analyze()

        cardinality_findings = [
            f for f in report.findings if f.code == "CREATE_JOB_CARDINALITY_VIOLATION"
        ]
        self.assertEqual(cardinality_findings, [])

    def test_unrelated_namesake_create_job_is_informational_only(self):
        """Une méthode create_job() sans AUCUN lien avec Higgsfield
        (aucun import integrations.higgsfield.*) ne doit jamais être
        comptée comme un second call-site de production -- cas réel :
        agents/job_monitor.py::JobMonitor.create_job."""

        _write(
            self.root,
            "agents/unrelated_job_thing.py",
            (
                "class Thing:\n"
                "    def create_job(self, job_id):\n"
                "        return job_id\n\n\n"
                "t = Thing()\n"
                "t.create_job('x')\n"
            ),
        )

        report = self._detector().analyze()

        self.assertFalse(report.has_actionable_drift)
        codes = {f.code for f in report.findings}
        self.assertIn("CREATE_JOB_NAMESAKE_UNRELATED", codes)
        hit = next(f for f in report.findings if f.code == "CREATE_JOB_NAMESAKE_UNRELATED")
        self.assertEqual(hit.severity, Severity.INFORMATIONAL)


class TestAutomaticAuthorizationDetected(_TempRepoTestCase):
    """6. Automatic human authorization est détecté."""

    def test_automatic_real_generation_authorization_construction_is_critical(self):
        _write(
            self.root,
            "agents/content_agent.py",
            (
                "from agents.generation_approval_gate import RealGenerationAuthorization\n\n\n"
                "def build():\n"
                "    return RealGenerationAuthorization(\n"
                "        request_id='005', authorized_by_human=True\n"
                "    )\n"
            ),
        )

        report = self._detector().analyze()

        hits = [f for f in report.findings if f.code == "AUTOMATIC_HUMAN_AUTHORIZATION"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].severity, Severity.CRITICAL)
        self.assertEqual(hits[0].file, "agents/content_agent.py")


class TestAutomaticActivationDetected(_TempRepoTestCase):
    """7. Automatic activation est détecté."""

    def test_automatic_activation_contract_construction_is_critical(self):
        _write(
            self.root,
            "agents/production_activation_handoff.py",
            (
                "from agents.activation_contract import RequestScopedActivationContract\n\n\n"
                "def build():\n"
                "    return RequestScopedActivationContract(\n"
                "        activation_id='a', request_id='005', job_type='seedance_2_0',\n"
                "        duration=15, resolution='720p', aspect_ratio='9:16',\n"
                "        prompt_sha256='x', authorization_id='y', created_at='z'\n"
                "    )\n"
            ),
        )

        report = self._detector().analyze()

        hits = [f for f in report.findings if f.code == "AUTOMATIC_ACTIVATION_CONSTRUCTION"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].severity, Severity.CRITICAL)


class TestProviderBypassDetected(_TempRepoTestCase):
    """8. Provider bypass (construction hors chemin autorisé) est détecté."""

    def test_higgsfield_provider_constructed_outside_allowlist_is_critical(self):
        _write(
            self.root,
            "agents/rogue_executor.py",
            (
                "from integrations.higgsfield.provider import HiggsfieldProvider\n\n\n"
                "def build():\n"
                "    return HiggsfieldProvider()\n"
            ),
        )

        report = self._detector().analyze()

        hits = [
            f
            for f in report.findings
            if f.code == "AUTHORITY_CONSTRUCTOR_OUTSIDE_ALLOWLIST"
            and f.file == "agents/rogue_executor.py"
        ]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].severity, Severity.CRITICAL)


class TestFalsePositiveAvoidance(_TempRepoTestCase):
    """9/10. Les commentaires et docstrings ne créent jamais de faux positifs."""

    def test_comment_mentioning_forbidden_import_is_not_drift(self):
        _write(
            self.root,
            "agents/strategy_agent.py",
            "# import integrations.higgsfield.provider  (do not do this)\n\ndef run():\n    pass\n",
        )

        report = self._detector().analyze()

        self.assertEqual(report.status, DriftStatus.NO_DRIFT)
        self.assertEqual(report.findings, ())

    def test_docstring_mentions_never_trigger_drift(self):
        _write(
            self.root,
            "agents/content_agent.py",
            (
                '"""\n'
                "This module never constructs RealGenerationAuthorization(...)\n"
                "nor calls provider.create_job(...) nor imports "
                "integrations.higgsfield.provider -- see agents.generation_job_service "
                "for the real mechanism.\n"
                '"""\n\n'
                "def run():\n    pass\n"
            ),
        )

        report = self._detector().analyze()

        self.assertEqual(report.status, DriftStatus.NO_DRIFT)
        self.assertEqual(report.findings, ())

    def test_variable_named_like_a_forbidden_symbol_is_not_drift(self):
        """Un simple nom de variable ne doit jamais être confondu avec
        un appel de constructeur (ast.Call vs ast.Name en position de
        variable)."""

        _write(
            self.root,
            "agents/content_agent.py",
            (
                "RealGenerationAuthorization = 'just a string label, not a class'\n\n\n"
                "def run():\n"
                "    HiggsfieldProvider = None\n"
                "    return HiggsfieldProvider\n"
            ),
        )

        report = self._detector().analyze()

        self.assertEqual(report.status, DriftStatus.NO_DRIFT)
        self.assertEqual(report.findings, ())


class TestMocksExplicitlyAuthorizedNoFalsePositive(_TempRepoTestCase):
    """11. Les tests/mocks explicitement autorisés (domaine TEST/SCRIPT)
    ne déclenchent jamais de finding, même s'ils construisent des objets
    normalement interdits en production -- c'est exactement leur rôle
    légitime (vérifier que le Gate/les services les REJETTENT)."""

    def test_test_domain_file_constructing_forbidden_objects_is_not_drift(self):
        _write(
            self.root,
            "tests/test_something_fake.py",
            (
                "from integrations.higgsfield.provider import HiggsfieldProvider\n"
                "from agents.generation_approval_gate import RealGenerationAuthorization\n\n\n"
                "def test_x():\n"
                "    auth = RealGenerationAuthorization(request_id='005', authorized_by_human=True)\n"
                "    provider = HiggsfieldProvider()\n"
                "    provider.create_job('seedance_2_0', 'p')\n"
            ),
        )

        report = self._detector().analyze()

        self.assertEqual(report.status, DriftStatus.NO_DRIFT)
        self.assertEqual(report.findings, ())

    def test_script_domain_file_constructing_authorization_is_not_drift(self):
        _write(
            self.root,
            "scripts/demo_test.py",
            (
                "from agents.generation_approval_gate import RealGenerationAuthorization\n\n\n"
                "auth = RealGenerationAuthorization(request_id='005', authorized_by_human=True)\n"
            ),
        )

        report = self._detector().analyze()

        self.assertEqual(report.status, DriftStatus.NO_DRIFT)
        self.assertEqual(report.findings, ())

    def test_identical_fixture_outside_test_domain_does_trigger_drift(self):
        """Contrôle négatif : le MÊME contenu, placé hors de tests/ ou
        scripts/, DOIT déclencher un finding -- la clémence est bien
        liée au domaine du fichier, jamais à son contenu seul."""

        _write(
            self.root,
            "agents/content_agent.py",
            (
                "from agents.generation_approval_gate import RealGenerationAuthorization\n\n\n"
                "auth = RealGenerationAuthorization(request_id='005', authorized_by_human=True)\n"
            ),
        )

        report = self._detector().analyze()

        self.assertTrue(report.has_actionable_drift)


class TestDeterminism(_TempRepoTestCase):
    """12. Sortie déterministe."""

    def test_two_analyses_of_the_same_fixtures_are_identical(self):
        _write(
            self.root,
            "agents/strategy_agent.py",
            "import integrations.higgsfield.provider\n",
        )
        _write(
            self.root,
            "agents/content_agent.py",
            "import agents.generation_job_service\n",
        )

        detector = self._detector()
        report_a = detector.analyze()
        report_b = detector.analyze()

        self.assertEqual(report_a.status, report_b.status)
        self.assertEqual(report_a.findings, report_b.findings)
        self.assertEqual(report_a.files_analyzed, report_b.files_analyzed)


class TestContractNeverMutatedByAnalysis(_TempRepoTestCase):
    """13. Le contrat reste immuable après une analyse."""

    def test_contract_collections_unchanged_after_analyze(self):
        before = CANONICAL_ARCHITECTURE_CONTRACT.business_editorial_files
        _write(self.root, "agents/strategy_agent.py", "import integrations.higgsfield.provider\n")

        ArchitectureDriftDetector(root=self.root).analyze()

        self.assertEqual(before, CANONICAL_ARCHITECTURE_CONTRACT.business_editorial_files)


class TestSeverityCorrectness(_TempRepoTestCase):
    """14. Chaque code de finding porte la sévérité attendue."""

    def test_all_findings_use_a_valid_severity(self):
        _write(self.root, "agents/strategy_agent.py", "import integrations.higgsfield.provider\n")
        _write(self.root, "agents/activation_eligibility.py", "import agents.generation_job_service\n")

        report = self._detector().analyze()

        for finding in report.findings:
            self.assertIsInstance(finding.severity, Severity)
            self.assertIn(
                finding.severity,
                (
                    Severity.CRITICAL,
                    Severity.HIGH,
                    Severity.MEDIUM,
                    Severity.LOW,
                    Severity.INFORMATIONAL,
                ),
            )


class TestEmptyFindingSetProducesNoDrift(_TempRepoTestCase):
    """15. Un ensemble de findings vide produit NO_DRIFT."""

    def test_innocuous_file_produces_no_drift(self):
        _write(self.root, "agents/strategy_agent.py", "def run():\n    return 1\n")

        report = self._detector().analyze()

        self.assertEqual(report.status, DriftStatus.NO_DRIFT)
        self.assertEqual(report.findings, ())

    def test_empty_repository_produces_no_drift(self):
        report = self._detector().analyze()

        self.assertEqual(report.status, DriftStatus.NO_DRIFT)
        self.assertEqual(report.findings, ())
        self.assertEqual(report.files_analyzed, ())


class TestAnalysisIncomplete(_TempRepoTestCase):
    """16. Une analyse corrompue/incomplète produit ANALYSIS_INCOMPLETE,
    jamais un faux NO_DRIFT/PASS."""

    def test_unparsable_file_produces_analysis_incomplete(self):
        _write(self.root, "agents/strategy_agent.py", "def broken(:\n    pass\n")

        report = self._detector().analyze()

        self.assertEqual(report.status, DriftStatus.ANALYSIS_INCOMPLETE)
        self.assertIn("agents/strategy_agent.py", report.files_unreadable)

    def test_analysis_incomplete_even_if_another_file_has_findings(self):
        """Un fichier illisible ne doit JAMAIS être masqué par la
        présence par ailleurs de findings normaux -- le statut le plus
        prudent (ANALYSIS_INCOMPLETE) l'emporte toujours."""

        _write(self.root, "agents/strategy_agent.py", "import integrations.higgsfield.provider\n")
        _write(self.root, "agents/content_agent.py", "def broken(:\n    pass\n")

        report = self._detector().analyze()

        self.assertEqual(report.status, DriftStatus.ANALYSIS_INCOMPLETE)


class TestSecondAuthorityCoreSignal(_TempRepoTestCase):
    """G. Signal heuristique d'un second noyau d'autorité en formation."""

    def test_unclassified_file_importing_multiple_p2_modules_is_flagged(self):
        _write(
            self.root,
            "agents/rogue_authority.py",
            (
                "import agents.generation_approval_gate\n"
                "import agents.critical_section_lock\n"
            ),
        )

        report = self._detector().analyze()

        hits = [f for f in report.findings if f.code == "POTENTIAL_SECOND_AUTHORITY_CORE"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].severity, Severity.MEDIUM)

    def test_production_modeling_file_importing_two_p2_types_is_not_flagged_as_second_core(self):
        """Les fichiers DÉJÀ classifiés (Business/Production-Modeling/
        Bridge) sont couverts par leurs propres règles dédiées -- le
        signal heuristique G ne doit jamais les dupliquer ou les
        contredire."""

        _write(
            self.root,
            "agents/activation_eligibility.py",
            (
                "from agents.activation_contract import RequestScopedActivationContract\n"
                "from agents.controlled_real_provider_activation import "
                "ControlledRealProviderActivationContract\n"
            ),
        )

        report = self._detector().analyze()

        hits = [f for f in report.findings if f.code == "POTENTIAL_SECOND_AUTHORITY_CORE"]
        self.assertEqual(hits, [])


class TestCertificateAuthorityEdgeRealRepository(unittest.TestCase):
    """H0. Le repository réel a exactement zéro edge certificate <->
    authority dans les deux sens (rapport P3.63 Section 10)."""

    def test_real_repository_has_zero_certificate_authority_edges(self):
        detector = ArchitectureDriftDetector(contract=CANONICAL_ARCHITECTURE_CONTRACT)
        report = detector.analyze()

        edge_codes = {
            "CERTIFICATE_TO_AUTHORITY_IMPORT",
            "CERTIFICATE_OUTBOUND_AUTHORITY_IMPORT",
            "CERTIFICATE_OUTBOUND_AUTHORITY_CALL",
        }
        hits = [f for f in report.findings if f.code in edge_codes]
        self.assertEqual(hits, [])


class TestCertificateToAuthorityImportDetected(_TempRepoTestCase):
    """H1 (Scenario A, mission Section 6). An authority-surface file
    importing a certificate subsystem module is CRITICAL drift."""

    def test_authority_file_importing_certificate_module_is_critical_drift(self):
        _write(
            self.root,
            "agents/generation_approval_gate.py",
            "from agents.certificate_integrity import verify_integrity\n",
        )

        report = self._detector().analyze()

        hits = [f for f in report.findings if f.code == "CERTIFICATE_TO_AUTHORITY_IMPORT"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].severity, Severity.CRITICAL)
        self.assertEqual(hits[0].file, "agents/generation_approval_gate.py")
        self.assertTrue(report.has_actionable_drift)

    def test_production_modeling_file_importing_certificate_module_is_critical_drift(self):
        """Mission Section 4: the human-authorization/production-
        activation chain (Domain B) is part of the guarded surface too,
        even though it holds no authority of its own."""

        _write(
            self.root,
            "agents/human_authorization_handoff.py",
            "import agents.production_activation_readiness_certificate\n",
        )

        report = self._detector().analyze()

        hits = [f for f in report.findings if f.code == "CERTIFICATE_TO_AUTHORITY_IMPORT"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].file, "agents/human_authorization_handoff.py")

    def test_director_importing_certificate_module_is_critical_drift(self):
        _write(
            self.root,
            "director.py",
            "from agents.certificate_lifecycle import CertificateLifecycleRegistry\n",
        )

        report = self._detector().analyze()

        hits = [f for f in report.findings if f.code == "CERTIFICATE_TO_AUTHORITY_IMPORT"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].file, "director.py")


class TestCertificateOutboundToAuthorityDetected(_TempRepoTestCase):
    """H2 (Scenario B/E/F, mission Section 6). The certificate
    subsystem's informational layer reaching into the authority surface
    -- by import or by a forbidden call name -- is CRITICAL drift."""

    def test_certificate_module_importing_authority_module_is_critical_drift(self):
        _write(
            self.root,
            "agents/certificate_integrity.py",
            "from agents.generation_approval_gate import GenerationApprovalGate\n",
        )

        report = self._detector().analyze()

        hits = [f for f in report.findings if f.code == "CERTIFICATE_OUTBOUND_AUTHORITY_IMPORT"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].file, "agents/certificate_integrity.py")

    def test_certificate_module_calling_execute_is_critical_drift(self):
        _write(
            self.root,
            "agents/certificate_lifecycle.py",
            "def sneaky(job_service, request):\n    return job_service.execute(request)\n",
        )

        report = self._detector().analyze()

        hits = [f for f in report.findings if f.code == "CERTIFICATE_OUTBOUND_AUTHORITY_CALL"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].file, "agents/certificate_lifecycle.py")

    def test_certificate_module_calling_create_job_is_critical_drift(self):
        _write(
            self.root,
            "agents/certificate_verification.py",
            "def sneaky(provider):\n    return provider.create_job('x', 'y')\n",
        )

        report = self._detector().analyze()

        hits = [f for f in report.findings if f.code == "CERTIFICATE_OUTBOUND_AUTHORITY_CALL"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].file, "agents/certificate_verification.py")


class TestCertificateAuthorityEdgeAliasCoverage(_TempRepoTestCase):
    """H3 (mission Section 9). Import aliasing must never evade the
    guardrail -- only the real dotted module path is checked, never the
    local binding name."""

    def test_module_alias_still_detected(self):
        _write(
            self.root,
            "agents/generation_approval_gate.py",
            "import agents.certificate_integrity as cert\n",
        )

        report = self._detector().analyze()

        hits = [f for f in report.findings if f.code == "CERTIFICATE_TO_AUTHORITY_IMPORT"]
        self.assertEqual(len(hits), 1)

    def test_from_import_with_symbol_alias_still_detected(self):
        _write(
            self.root,
            "agents/generation_approval_gate.py",
            "from agents.certificate_integrity import ISSUER_IDENTITY as ISSUER\n",
        )

        report = self._detector().analyze()

        hits = [f for f in report.findings if f.code == "CERTIFICATE_TO_AUTHORITY_IMPORT"]
        self.assertEqual(len(hits), 1)


class TestCertificateAuthorityEdgeFalsePositiveAvoidance(_TempRepoTestCase):
    """H4 (mission Section 7). Legitimate, already-sanctioned
    architecture must never be flagged."""

    def test_issuer_module_importing_p2_authority_is_not_flagged(self):
        """agents/production_activation_readiness_certificate.py (the
        P3.54 Issuer) legitimately composes ActivationReadinessEvaluator
        -- it is deliberately excluded from the outbound (Direction 2)
        check, and its own imports are never certificate-subsystem
        modules, so Direction 1 finds nothing either."""

        _write(
            self.root,
            "agents/production_activation_readiness_certificate.py",
            (
                "from agents.activation_readiness import ActivationReadinessEvaluator\n"
                "from agents.generation_approval_gate import GenerationRequest\n"
            ),
        )

        report = self._detector().analyze()

        edge_codes = {
            "CERTIFICATE_TO_AUTHORITY_IMPORT",
            "CERTIFICATE_OUTBOUND_AUTHORITY_IMPORT",
            "CERTIFICATE_OUTBOUND_AUTHORITY_CALL",
        }
        hits = [f for f in report.findings if f.code in edge_codes]
        self.assertEqual(hits, [])

    def test_certificate_module_importing_the_issuer_module_is_not_flagged(self):
        """The informational layer legitimately depends on the
        certificate TYPE the Issuer defines -- this is vocabulary, never
        'authority' being guarded against."""

        _write(
            self.root,
            "agents/certificate_verification.py",
            "from agents.production_activation_readiness_certificate import "
            "ProductionActivationReadinessCertificate\n",
        )

        report = self._detector().analyze()

        hits = [f for f in report.findings if f.code == "CERTIFICATE_OUTBOUND_AUTHORITY_IMPORT"]
        self.assertEqual(hits, [])

    def test_docstring_mention_of_execute_in_certificate_module_is_not_flagged(self):
        _write(
            self.root,
            "agents/certificate_integrity.py",
            '"""This module never calls execute() or create_job()."""\n',
        )

        report = self._detector().analyze()

        hits = [f for f in report.findings if f.code == "CERTIFICATE_OUTBOUND_AUTHORITY_CALL"]
        self.assertEqual(hits, [])

    def test_test_domain_file_is_never_scanned_by_this_guardrail(self):
        """tests/ is excluded from file-set membership entirely (it is
        classified Domain.TEST, never a member of either guarded file
        set) -- certificate tests importing authority modules for
        fixture construction is exactly the P3.54-P3.62 test pattern,
        never a drift."""

        _write(
            self.root,
            "tests/test_certificate_integrity.py",
            "from agents.generation_approval_gate import GenerationApprovalGate\n",
        )

        report = self._detector().analyze()

        edge_codes = {
            "CERTIFICATE_TO_AUTHORITY_IMPORT",
            "CERTIFICATE_OUTBOUND_AUTHORITY_IMPORT",
        }
        hits = [f for f in report.findings if f.code in edge_codes]
        self.assertEqual(hits, [])


class TestCertificateAuthorityEdgeMutationRoundTrip(_TempRepoTestCase):
    """Section 8. Full mutation-test protocol: introduce a fixture
    representing a future drift, confirm detection, remove the fixture,
    confirm the same (temp) repository returns to NO_DRIFT."""

    def test_violation_detected_then_repository_returns_to_no_drift_after_removal(self):
        violating_file = self.root / "agents" / "generation_approval_gate.py"

        _write(
            self.root,
            "agents/generation_approval_gate.py",
            "from agents.certificate_integrity import verify_integrity\n",
        )
        drifted_report = self._detector().analyze()
        self.assertEqual(drifted_report.status, DriftStatus.DRIFT_DETECTED)
        self.assertTrue(
            any(f.code == "CERTIFICATE_TO_AUTHORITY_IMPORT" for f in drifted_report.findings)
        )

        violating_file.unlink()

        clean_report = self._detector().analyze()
        self.assertEqual(clean_report.status, DriftStatus.NO_DRIFT)
        self.assertEqual(clean_report.findings, ())


if __name__ == "__main__":
    unittest.main()
