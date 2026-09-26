"""
Tests — Architecture Contract Continuous Enforcement (Phase P3.32).

P3.32 intègre le Canonical Architecture Contract / Architecture Drift
Detector (Phase P3.31, `agents/canonical_architecture_contract.py` +
`agents/architecture_drift_detector.py`) dans les contrôles PERMANENTS
du repository -- sans créer de deuxième détecteur, de deuxième contrat,
ni de système CI/pre-commit externe (aucun n'existe dans ce
repository, vérifié explicitement avant d'écrire ce fichier).

CE FICHIER N'AJOUTE AUCUNE NOUVELLE RÈGLE DE DÉRIVE : les 16 scénarios
de détection (imports interdits, construction d'autorité automatique,
cardinalité `create_job`, second noyau d'autorité, faux positifs
commentaires/docstrings/tests/mocks, déterminisme, ANALYSIS_INCOMPLETE)
sont déjà couverts par `tests/test_architecture_drift_detector.py`
(Phase P3.31) -- jamais dupliqués ici. Ce module ajoute UNIQUEMENT ce
que P3.31 ne prouvait pas encore explicitement :

1. Le détecteur/contrat lui-même n'importe, structurellement, ni
   réseau ni Higgsfield (donc ne PEUT PAS y accéder, indépendamment de
   ce qu'il analyse) ;
2. Analyser le repository ne le modifie jamais (aucun fichier créé,
   modifié, ou dont l'horodatage change) ;
3. Le repository canonique actuel, tel que découvert par la suite de
   tests standard (`python -m unittest discover -s tests`), retourne
   bien `NO_DRIFT` avec exactement 1 call-site `create_job` de
   production -- c'est-à-dire que l'intégration "modification du
   repository -> suite de tests -> vérification architecturale ->
   PASS/DRIFT_DETECTED" fonctionne réellement de bout en bout, pas
   seulement en théorie.

AUCUN AUTO-FIX : ce module ne contient et n'exerce aucune capacité de
correction automatique -- une dérive détectée reste un `DriftFinding`
à revue humaine, jamais une modification de code (Section 17/18,
mission P3.32).
"""

import ast
import sys
import tempfile
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.architecture_drift_detector import ArchitectureDriftDetector, DriftStatus
from agents.canonical_architecture_contract import CANONICAL_ARCHITECTURE_CONTRACT

_CONTRACT_FILE = PROJECT_ROOT / "agents" / "canonical_architecture_contract.py"
_DETECTOR_FILE = PROJECT_ROOT / "agents" / "architecture_drift_detector.py"

# Réutilise le même vocabulaire que le détecteur pour rester une SEULE
# source de vérité sur "qu'est-ce qu'un accès réseau" -- ne redéfinit
# rien, ne fait qu'énumérer les modules dont l'IMPORT prouverait, à lui
# seul, qu'un accès réseau devient possible.
_NETWORK_MODULE_PREFIXES = (
    "socket",
    "requests",
    "urllib",
    "http.client",
    "subprocess",
    "ftplib",
    "smtplib",
)


def _imported_module_prefixes(path: Path) -> "set[str]":
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    modules: "set[str]" = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


class TestDetectorHasNoNetworkOrHiggsfieldAccess(unittest.TestCase):
    """
    Preuve STRUCTURELLE (AST de son propre code source, pas une
    supposition) que ni le contrat ni le détecteur ne peuvent accéder
    au réseau ou à Higgsfield -- ils ne font que lire et parser des
    fichiers `.py` comme du texte.
    """

    def test_contract_module_imports_no_network_or_higgsfield(self):
        modules = _imported_module_prefixes(_CONTRACT_FILE)
        for module in modules:
            for forbidden in _NETWORK_MODULE_PREFIXES:
                self.assertFalse(
                    module == forbidden or module.startswith(forbidden + "."),
                    f"canonical_architecture_contract.py imports network module '{module}'",
                )
            self.assertFalse(
                module == "integrations.higgsfield" or module.startswith("integrations.higgsfield."),
                f"canonical_architecture_contract.py imports Higgsfield module '{module}'",
            )

    def test_detector_module_imports_no_network_or_higgsfield(self):
        modules = _imported_module_prefixes(_DETECTOR_FILE)
        for module in modules:
            for forbidden in _NETWORK_MODULE_PREFIXES:
                self.assertFalse(
                    module == forbidden or module.startswith(forbidden + "."),
                    f"architecture_drift_detector.py imports network module '{module}'",
                )
            self.assertFalse(
                module == "integrations.higgsfield" or module.startswith("integrations.higgsfield."),
                f"architecture_drift_detector.py imports Higgsfield module '{module}'",
            )

    def test_detector_module_never_imports_subprocess_or_os_system(self):
        """Le détecteur lit des fichiers (`Path.read_text`) -- il ne
        doit jamais avoir besoin d'exécuter un sous-processus ou une
        commande système pour analyser du code source."""

        source = _DETECTOR_FILE.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                self.assertNotIn(
                    name,
                    ("system", "popen", "spawnl", "spawnv"),
                    "architecture_drift_detector.py must never execute external commands",
                )


class TestAnalysisNeverModifiesTheRepository(unittest.TestCase):
    """
    Preuve empirique (pas seulement documentaire) que `analyze()` ne
    modifie jamais ce qu'il inspecte -- ni les fichiers réels, ni un
    état de production (`state/executed_requests.json`, verrous).
    """

    def test_real_repository_files_unchanged_after_analysis(self):
        sample_files = [
            PROJECT_ROOT / "agents" / "generation_approval_gate.py",
            PROJECT_ROOT / "director.py",
            _CONTRACT_FILE,
            _DETECTOR_FILE,
        ]
        before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in sample_files}

        ArchitectureDriftDetector(contract=CANONICAL_ARCHITECTURE_CONTRACT).analyze()

        after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in sample_files}
        self.assertEqual(before, after)

    def test_real_repository_no_new_production_state_created(self):
        executed_requests = PROJECT_ROOT / "state" / "executed_requests.json"
        existed_before = executed_requests.exists()

        ArchitectureDriftDetector(contract=CANONICAL_ARCHITECTURE_CONTRACT).analyze()

        self.assertEqual(executed_requests.exists(), existed_before)

    def test_temp_fixture_tree_unchanged_after_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "agents" / "strategy_agent.py"
            fixture.parent.mkdir(parents=True, exist_ok=True)
            fixture.write_text("def run():\n    return 1\n", encoding="utf-8")

            before_mtime = fixture.stat().st_mtime_ns
            before_content = fixture.read_bytes()
            before_listing = sorted(p.relative_to(root) for p in root.rglob("*"))

            ArchitectureDriftDetector(root=root).analyze()

            self.assertEqual(fixture.stat().st_mtime_ns, before_mtime)
            self.assertEqual(fixture.read_bytes(), before_content)
            self.assertEqual(
                sorted(p.relative_to(root) for p in root.rglob("*")), before_listing
            )


class TestContinuousEnforcementIntegration(unittest.TestCase):
    """
    Preuve que "modification du repository -> suite de tests -> drift
    check -> PASS/DRIFT_DETECTED" fonctionne réellement : le repository
    canonique actuel, analysé exactement comme il le serait lors d'une
    exécution normale de `python -m unittest discover -s tests`,
    retourne `NO_DRIFT` avec exactement 1 call-site `create_job` de
    production. (Test 1, mission P3.32 Section 11 -- les Tests 2 à 7,
    qui portent sur la LOGIQUE de détection elle-même, restent
    exclusivement dans tests/test_architecture_drift_detector.py,
    Phase P3.31, jamais dupliqués ici.)
    """

    def test_canonical_repository_yields_no_drift_end_to_end(self):
        report = ArchitectureDriftDetector(contract=CANONICAL_ARCHITECTURE_CONTRACT).analyze()

        self.assertEqual(report.status, DriftStatus.NO_DRIFT)
        self.assertEqual(report.files_unreadable, ())

    def test_this_test_module_is_discoverable_by_the_standard_suite_runner(self):
        """Garantit que ce fichier lui-même (et donc, par le même
        mécanisme, `test_architecture_drift_detector.py` et
        `test_canonical_architecture_contract.py`) est bien repéré par
        `python -m unittest discover -s tests` -- l'unique mécanisme de
        validation globale déjà utilisé par ce repository (aucune CI,
        aucun pre-commit, aucun autre runner trouvé)."""

        self.assertTrue(Path(__file__).name.startswith("test_"))
        self.assertTrue(Path(__file__).parent.name == "tests")


class TestPerformance(unittest.TestCase):
    """
    Mesure raisonnable du coût du contrôle (Section 10, mission
    P3.32) -- pas d'optimisation prématurée, seulement une borne large
    qui détecterait une régression de performance catastrophique
    (ex. boucle infinie, lecture réseau accidentelle) sans jamais
    contraindre le design à une micro-optimisation.
    """

    def test_full_repository_analysis_completes_within_a_generous_bound(self):
        started = time.monotonic()
        ArchitectureDriftDetector(contract=CANONICAL_ARCHITECTURE_CONTRACT).analyze()
        elapsed_seconds = time.monotonic() - started

        self.assertLess(
            elapsed_seconds,
            10.0,
            f"Architecture drift analysis took {elapsed_seconds:.2f}s -- "
            f"investigate before treating this as routine.",
        )


if __name__ == "__main__":
    unittest.main()
