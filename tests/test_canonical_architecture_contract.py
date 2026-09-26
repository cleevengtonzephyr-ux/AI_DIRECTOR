"""
Tests — Canonical Architecture Contract (Phase P3.31).

Vérifie que `agents/canonical_architecture_contract.py` est réellement
immuable, déterministe, et cohérent avec lui-même -- jamais que son
contenu "semble correct" à la lecture.
"""

import dataclasses
import sys
import unittest
from pathlib import Path
from types import MappingProxyType

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.canonical_architecture_contract import (
    CANONICAL_ARCHITECTURE_CONTRACT,
    CONTRACT_VERSION,
    CanonicalArchitectureContract,
    CanonicalComponent,
    Domain,
)


class TestContractImmutability(unittest.TestCase):
    def test_contract_is_frozen(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            CANONICAL_ARCHITECTURE_CONTRACT.version = 999  # type: ignore[misc]

    def test_component_is_frozen(self):
        component = CANONICAL_ARCHITECTURE_CONTRACT.canonical_components[0]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            component.name = "tampered"  # type: ignore[misc]

    def test_constructor_allowlist_is_a_read_only_mapping(self):
        self.assertIsInstance(
            CANONICAL_ARCHITECTURE_CONTRACT.constructor_allowlist, MappingProxyType
        )
        with self.assertRaises(TypeError):
            CANONICAL_ARCHITECTURE_CONTRACT.constructor_allowlist["Injected"] = frozenset()

    def test_all_frozenset_collections_reject_mutation(self):
        with self.assertRaises(AttributeError):
            CANONICAL_ARCHITECTURE_CONTRACT.business_editorial_files.add("agents/evil.py")  # type: ignore[attr-defined]


class TestContractDeterminism(unittest.TestCase):
    def test_two_fresh_instances_are_value_equal(self):
        a = CanonicalArchitectureContract()
        b = CanonicalArchitectureContract()
        self.assertEqual(a.business_editorial_files, b.business_editorial_files)
        self.assertEqual(a.production_modeling_files, b.production_modeling_files)
        self.assertEqual(a.protected_p2_files, b.protected_p2_files)
        self.assertEqual(a.canonical_components, b.canonical_components)

    def test_version_is_a_positive_int(self):
        self.assertIsInstance(CONTRACT_VERSION, int)
        self.assertGreater(CONTRACT_VERSION, 0)
        self.assertEqual(CANONICAL_ARCHITECTURE_CONTRACT.version, CONTRACT_VERSION)


class TestContractInternalConsistency(unittest.TestCase):
    """Le contrat ne doit jamais se contredire lui-même."""

    def test_protected_p2_files_subset_of_core_plus_director(self):
        c = CANONICAL_ARCHITECTURE_CONTRACT
        allowed_superset = c.p2_authority_core_files | c.entry_point_files
        self.assertTrue(
            c.protected_p2_files <= allowed_superset,
            "PROTECTED_P2_FILES must never name a file outside "
            "P2_AUTHORITY_CORE_FILES or the entry point (director.py).",
        )

    def test_domain_file_sets_are_pairwise_disjoint(self):
        c = CANONICAL_ARCHITECTURE_CONTRACT
        domain_sets = [
            c.business_editorial_files,
            c.production_modeling_files,
            c.bridge_files,
            c.p2_authority_core_files,
            c.dispatch_files,
            c.entry_point_files,
        ]
        seen: set = set()
        for file_set in domain_sets:
            overlap = seen & file_set
            self.assertFalse(
                overlap,
                f"A file must belong to exactly one canonical domain; "
                f"found in more than one: {overlap}",
            )
            seen |= file_set

    def test_every_canonical_component_file_matches_its_declared_domain(self):
        c = CANONICAL_ARCHITECTURE_CONTRACT
        for component in c.canonical_components:
            self.assertIsInstance(component, CanonicalComponent)
            resolved = c.domain_of(component.file)
            self.assertEqual(
                resolved,
                component.domain,
                f"CanonicalComponent '{component.name}' declares domain "
                f"{component.domain}, but domain_of('{component.file}') "
                f"resolves to {resolved}.",
            )

    def test_constructor_allowlist_never_names_a_file_outside_expected_domains(self):
        """Chaque fichier autorisé à construire un symbole porteur
        d'autorité doit être soit un fichier P2_AUTHORITY_CORE, soit
        l'entry point (director.py) -- jamais un fichier Business ou
        Production/Modeling (ce serait, par construction, un bypass).

        SEULE EXCEPTION CONNUE ET AUDITÉE (rapport P3.30, AST/Call-Site
        Audit) : `HiggsfieldClient` peut aussi être construit dans
        `agents/cost_engine.py` et `agents/planner.py` -- deux modules
        V1 déjà vérifiés comme strictement en lecture seule
        (`account_status()`/`estimate_cost()`/`get_workflow()`, jamais
        `create_job()`). Cette exception est nommée explicitement,
        jamais élargie silencieusement : tout AUTRE symbole doit rester
        strictement confiné à P2_AUTHORITY_CORE_FILES + director.py."""

        c = CANONICAL_ARCHITECTURE_CONTRACT
        allowed_superset = c.p2_authority_core_files | c.entry_point_files
        known_v1_read_only_exceptions = {
            "HiggsfieldClient": frozenset(
                {"agents/cost_engine.py", "agents/planner.py"}
            ),
        }

        for symbol, files in c.constructor_allowlist.items():
            extra_allowed = known_v1_read_only_exceptions.get(symbol, frozenset())
            self.assertTrue(
                files <= (allowed_superset | extra_allowed),
                f"Constructor allowlist for '{symbol}' names a file outside "
                f"the P2 core / entry point / known V1 exceptions: "
                f"{files - (allowed_superset | extra_allowed)}",
            )

    def test_real_generation_authorization_has_no_production_allowlist(self):
        """Invariante la plus critique du contrat : AUCUN fichier de
        production ne peut jamais construire une RealGenerationAuthorization."""

        c = CANONICAL_ARCHITECTURE_CONTRACT
        self.assertEqual(
            c.constructor_allowlist["RealGenerationAuthorization"],
            frozenset(),
        )


class TestDomainOf(unittest.TestCase):
    def setUp(self):
        self.contract = CANONICAL_ARCHITECTURE_CONTRACT

    def test_business_editorial_classification(self):
        self.assertEqual(
            self.contract.domain_of("agents/strategy_agent.py"),
            Domain.BUSINESS_EDITORIAL,
        )

    def test_production_modeling_classification(self):
        self.assertEqual(
            self.contract.domain_of("agents/activation_eligibility.py"),
            Domain.PRODUCTION_MODELING,
        )

    def test_bridge_classification(self):
        self.assertEqual(
            self.contract.domain_of("agents/controlled_activation_composition.py"),
            Domain.BRIDGE,
        )

    def test_p2_authority_core_classification(self):
        self.assertEqual(
            self.contract.domain_of("agents/generation_job_service.py"),
            Domain.P2_AUTHORITY_CORE,
        )
        self.assertEqual(
            self.contract.domain_of("integrations/higgsfield/provider.py"),
            Domain.P2_AUTHORITY_CORE,
        )

    def test_dispatch_classification(self):
        self.assertEqual(
            self.contract.domain_of("agents/task_manager.py"), Domain.DISPATCH
        )

    def test_entry_point_classification(self):
        self.assertEqual(self.contract.domain_of("director.py"), Domain.ENTRY_POINT)

    def test_test_directory_classification(self):
        self.assertEqual(
            self.contract.domain_of("tests/test_whatever.py"), Domain.TEST
        )

    def test_scripts_directory_classification(self):
        self.assertEqual(
            self.contract.domain_of("scripts/demo_test.py"), Domain.SCRIPT
        )

    def test_unknown_file_is_unclassified_legacy(self):
        self.assertEqual(
            self.contract.domain_of("agents/job_monitor.py"),
            Domain.UNCLASSIFIED_LEGACY,
        )

    def test_backslash_paths_are_normalized(self):
        self.assertEqual(
            self.contract.domain_of("agents\\strategy_agent.py"),
            Domain.BUSINESS_EDITORIAL,
        )


if __name__ == "__main__":
    unittest.main()
