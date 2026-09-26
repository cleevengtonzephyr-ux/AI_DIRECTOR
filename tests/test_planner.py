"""
Tests — VideoPlanner.create_zephyr_plan() (alignement duration, Phase P1.4).

Vérifie que le VideoPlan 005 (Zephyr AI) est désormais construit avec
une durée réellement confirmée par Higgsfield pour seedance_2_0 (Phase
P1.2-bis : 5/10/15s acceptés en lecture seule, 40s rejeté par l'API
réelle avec "duration: Input should be less than or equal to 15").

create_zephyr_plan() ne fait aucun appel réseau/CLI : c'est une pure
construction de dataclass. Aucun appel Higgsfield. Aucune génération.
Lecture seule.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.planner import VideoPlanner

CONFIRMED_SEEDANCE_2_0_MAX_DURATION = 15


def _build_zephyr_005_plan(planner: VideoPlanner, **overrides):
    kwargs = dict(
        video_id="005",
        title="Pourquoi la discipline vaut plus que le talent.",
        hook="Le talent impressionne. La discipline construit des empires.",
        objective=(
            "Créer une vidéo courte, cinématique et motivante expliquant "
            "pourquoi la discipline répétée produit des résultats "
            "supérieurs au talent seul."
        ),
    )
    kwargs.update(overrides)
    return planner.create_zephyr_plan(**kwargs)


class TestZephyr005DurationAlignedWithConfirmedSeedance(unittest.TestCase):
    """1. VideoPlan 005 produit duration=15 (valeur confirmée réelle)."""

    def test_default_duration_matches_confirmed_seedance_ceiling(self):
        planner = VideoPlanner(PROJECT_ROOT)

        plan = _build_zephyr_005_plan(planner)

        self.assertEqual(
            plan.duration,
            CONFIRMED_SEEDANCE_2_0_MAX_DURATION,
        )

    def test_duration_is_no_longer_the_unconfirmed_value_of_forty(self):
        planner = VideoPlanner(PROJECT_ROOT)

        plan = _build_zephyr_005_plan(planner)

        self.assertNotEqual(plan.duration, 40)


if __name__ == "__main__":
    unittest.main()
