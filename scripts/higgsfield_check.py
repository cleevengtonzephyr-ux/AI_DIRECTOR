"""
AI DIRECTOR — higgsfield:check (Phase N, MASTER PROMPT V2, Priorité 6)

Vérification de connectivité Higgsfield en LECTURE SEULE (compte,
workflows). Ne crée jamais de job, ne consomme aucun crédit.

Ce script se contente d'appeler AIDirector.status()/check_higgsfield()
(V1, inchangés) — aucune nouvelle logique n'est introduite ici, il ne
fait que documenter/nommer un point d'entrée déjà existant et déjà
sûr, comme demandé par la Priorité 6 de la roadmap.

Usage :
    python scripts/higgsfield_check.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from director import AIDirector


def main() -> dict:
    """Affiche le statut du Director et retourne le résultat de check_higgsfield()."""

    director = AIDirector()
    director.status()
    return director.check_higgsfield()


if __name__ == "__main__":
    main()
