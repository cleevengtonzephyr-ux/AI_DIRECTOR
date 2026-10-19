"""
AI DIRECTOR — higgsfield:check (Phase N, MASTER PROMPT V2, Priorité 6)

Affiche l'état du connecteur Higgsfield SANS le contacter : tant que
Provider = CLOSED, aucun point d'entrée du dépôt ne lance la CLI
Higgsfield, pas même une commande en lecture seule. Ne crée jamais de
job, ne consomme aucun crédit, n'ouvre aucune connexion.

Ce script se contente d'appeler AIDirector.status()/check_higgsfield(),
qui rapportent l'état fermé sans utiliser le client Higgsfield
(tests/test_provider_egress_closure.py).

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
