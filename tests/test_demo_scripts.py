"""
Tests — scripts/demo_test.py et scripts/higgsfield_check.py (Phase N).

demo_test.run_demo() est appelé directement : il n'utilise QUE
MockHiggsfieldProvider en interne, donc aucun appel réseau/CLI n'est
jamais déclenché par ce test, quel que soit l'état du compte réel.

higgsfield_check.py n'est qu'IMPORTÉ (jamais son main() appelé) : ce
script est un outil interactif read-only destiné à un lancement manuel
(`python scripts/higgsfield_check.py`), pas à la suite de tests
automatisée hors-ligne.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SCRIPTS_DIR = PROJECT_ROOT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import demo_test  # noqa: E402  (import après manipulation de sys.path, nécessaire)

from agents.final_report_service import FinalReportStatus


class TestDemoTestScript(unittest.TestCase):

    def test_run_demo_produces_the_three_expected_scenarios(self):
        results = demo_test.run_demo()

        self.assertEqual(results["scenario_1"].status, FinalReportStatus.NOT_EXECUTED)
        self.assertEqual(results["scenario_2"].status, FinalReportStatus.EXECUTED_PASS)
        self.assertEqual(results["scenario_3"].status, FinalReportStatus.NOT_EXECUTED)

    def test_scenario_2_actually_created_a_mock_job_not_a_real_one(self):
        results = demo_test.run_demo()

        self.assertTrue(results["scenario_2"].job_created)
        self.assertTrue(results["scenario_2"].job_id.startswith("mock-job-"))
        self.assertTrue(
            all(url.startswith("mock://") for url in results["scenario_2"].output_urls)
        )

    def test_demo_module_uses_mock_provider_exclusively(self):
        # Vérifie les imports RÉELS du module (pas une recherche de
        # sous-chaîne naïve : "HiggsfieldProvider(" matcherait aussi
        # à l'intérieur de "MockHiggsfieldProvider(").
        imported_names = {
            name
            for name, value in vars(demo_test).items()
            if isinstance(value, type)
        }

        self.assertIn("MockHiggsfieldProvider", imported_names)
        self.assertNotIn("HiggsfieldProvider", imported_names)
        self.assertNotIn("HiggsfieldClient", imported_names)


class TestHiggsfieldCheckScript(unittest.TestCase):

    def test_script_imports_without_executing_main(self):
        spec = importlib.util.spec_from_file_location(
            "higgsfield_check_under_test",
            SCRIPTS_DIR / "higgsfield_check.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # exécute uniquement le module-level code

        self.assertTrue(hasattr(module, "main"))
        self.assertTrue(callable(module.main))


if __name__ == "__main__":
    unittest.main()
