"""
AI DIRECTOR — Higgsfield Provider Errors (Phase B, MASTER PROMPT V2)

Hiérarchie d'erreurs typée pour la couche Higgsfield (CLI + Provider).

Toutes les erreurs héritent de RuntimeError afin de préserver une
compatibilité totale avec le code V1 existant (agents/cost_engine.py,
agents/planner.py, director.py), qui capture aujourd'hui des
`except Exception` génériques sans connaître ces sous-types. Le code
V1 continue donc de fonctionner sans aucune modification, tandis que
le nouveau code (Provider, tests) peut cibler des exceptions précises.

Aucune de ces classes n'exécute d'appel réseau ou CLI : ce module ne
contient que des définitions d'exceptions.
"""

from typing import List, Optional


class HiggsfieldError(RuntimeError):
    """Base pour toute erreur liée à Higgsfield (CLI ou Provider)."""


class HiggsfieldCLINotFoundError(HiggsfieldError):
    """L'exécutable Higgsfield CLI est introuvable sur le système."""


class HiggsfieldAuthenticationError(HiggsfieldError):
    """Le CLI Higgsfield a signalé un échec d'authentification."""


class HiggsfieldCommandError(HiggsfieldError):
    """Une commande Higgsfield CLI a échoué (exit code != 0)."""

    def __init__(self, message: str, exit_code: int = None, stderr: str = ""):
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


class HiggsfieldTimeoutError(HiggsfieldError):
    """Une commande Higgsfield CLI a dépassé le délai imparti (timeout)."""


class HiggsfieldInvalidResponseError(HiggsfieldError):
    """La sortie du CLI Higgsfield est invalide ou malformée (JSON attendu)."""


class HiggsfieldRealGenerationDisabledError(HiggsfieldError):
    """
    Garde-fou explicite et volontaire.

    La génération réelle (`higgsfield generate create`) est désactivée
    pour cette phase du projet (Phase B/C du MASTER PROMPT V2 —
    "Construire la base du Provider Higgsfield sans aucune génération
    réelle et sans consommer de crédit"). HiggsfieldProvider.create_job()
    lève systématiquement cette erreur au lieu d'appeler le CLI, quelle
    que soit la façon dont elle est invoquée. Seul MockHiggsfieldProvider
    simule réellement la création d'un job, en mémoire, sans réseau.

    `reasons` (Phase P2.35, optionnel, `[]` par défaut) — liste
    optionnelle de raisons structurées expliquant POURQUOI ce refus a
    eu lieu (ex. "provider_activation_contract missing", "prompt sha256
    mismatch", ou, quand toutes les vérifications structurelles
    passent, un marqueur explicite signalant que la transition finale
    vers un appel réel reste volontairement fermée). Purement
    informatif/observabilité -- ne change jamais LE FAIT que cette
    exception est levée, et n'est jamais requis par le code appelant
    existant (tous les appels historiques `HiggsfieldRealGeneration
    DisabledError(message)` restent valides sans modification).
    """

    def __init__(self, message: str, reasons: Optional[List[str]] = None):
        super().__init__(message)
        self.reasons: List[str] = list(reasons) if reasons else []
