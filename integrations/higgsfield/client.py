import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from integrations.higgsfield.errors import (
    HiggsfieldAuthenticationError,
    HiggsfieldCLINotFoundError,
    HiggsfieldCommandError,
    HiggsfieldInvalidResponseError,
    HiggsfieldRealGenerationDisabledError,
    HiggsfieldTimeoutError,
)


# Phase P3.83 -- verrou runtime D (spécification P3.82). `run()` n'exécute
# QUE ces paires (verbe, sous-verbe) en lecture seule ; toute autre paire,
# dont `generate create`, est refusée AVANT la construction de la commande.
# Liste fermée (fail closed), sans état : aucune variable, aucun appelant,
# aucun booléen ne peut l'élargir -- ce n'est pas une autorité, c'est une
# fermeture. Une future activation réelle ne rouvrira jamais `run()` : elle
# passera uniquement par `create_job()` avec une capacité émise par P2.
_READ_ONLY_CLI_VERBS = frozenset(
    {
        ("workflow", "list"),
        ("workflow", "get"),
        ("account", "status"),
        ("account", "transactions"),
        ("model", "list"),
        ("model", "get"),
        ("generate", "cost"),
        ("generate", "get"),
        ("generate", "list"),
        ("generate", "wait"),
    }
)


# Phase P3.85 -- `generate cost` reste une ESTIMATION : seule la forme exacte
# émise par `estimate_cost()` est acceptée. Toute autre option (référence
# média -- un chemin local est téléversé par la CLI --, `--wait*`, `--count`,
# forme `--x=v`, option inconnue) ou sous-commande (`workflow`) est refusée,
# fail closed. La valeur qui suit une option autorisée est consommée telle
# quelle, comme le fait l'analyseur d'options de la CLI (un prompt peut donc
# commencer par « - »).
_READ_ONLY_COST_OPTIONS = frozenset({"--prompt", "--duration", "--resolution", "--aspect-ratio"})
_RESERVED_CLI_WORDS = frozenset({"workflow", "create", "cost", "get", "list", "wait", "submit", "cancel", "delete", "upload"})


def _generate_cost_violations(args: tuple) -> List[str]:
    """Pure : raisons pour lesquelles `args` (argv complet commençant par
    `generate cost`) n'est PAS la forme d'estimation autorisée. Vide = OK."""

    rest = list(args[2:])
    if not rest:
        return ["generate cost requires a job_type"]
    job_type, options = rest[0], rest[1:]
    reasons = []
    if (
        not isinstance(job_type, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", job_type)
        or job_type.lower() in _RESERVED_CLI_WORDS
    ):
        reasons.append(f"job_type {job_type!r} is not a plain model identifier")
    seen = set()
    index = 0
    while index < len(options):
        option = options[index]
        if option not in _READ_ONLY_COST_OPTIONS:
            reasons.append(f"option {option!r} is not allowed for generate cost")
            index += 1
            continue
        if option in seen:
            reasons.append(f"option {option!r} is repeated")
        seen.add(option)
        if index + 1 >= len(options):
            reasons.append(f"option {option!r} has no value")
        index += 2
    return reasons


# Phase P3.86-C -- `account transactions` (historique de crédits, lecture
# seule) n'est accepté QUE sous la forme canonique
#     account transactions [--size <1..100>] [--cursor <jeton>]
# (bornes : exemples de la CLI installée, `--size 50` / `--size 100 --cursor
# <cursor>`). Aucun positionnel -- un verbe injecté (`generate create` ...) ne
# peut donc jamais être relayé --, aucune autre option, aucun doublon, aucune
# forme `--x=v`, ordre fixe. Format du curseur non documenté : validation
# conservatrice (un curseur inattendu est refusé, jamais transmis).
_TRANSACTIONS_MAX_PAGE_SIZE = 100
_TRANSACTIONS_CURSOR_PATTERN = r"[A-Za-z0-9_=+/.:-]{1,512}"


def _account_transactions_violations(args: tuple) -> List[str]:
    """Pure : raisons pour lesquelles `args` (argv complet commençant par
    `account transactions`) n'est PAS la forme canonique autorisée. Vide = OK."""

    rest = list(args[2:])
    reasons = []
    expected_order = ["--size", "--cursor"]
    index = 0
    while index < len(rest):
        option = rest[index]
        if option not in expected_order:
            reasons.append(f"argument {option!r} is not allowed for account transactions")
            index += 1
            continue
        # Canonical order, each option at most once: drop every option up to and including this one.
        expected_order = expected_order[expected_order.index(option) + 1:]
        if index + 1 >= len(rest):
            reasons.append(f"option {option!r} has no value")
            break
        value = rest[index + 1]
        if option == "--size" and not (
            isinstance(value, str) and value.isdigit() and 1 <= int(value) <= _TRANSACTIONS_MAX_PAGE_SIZE
            and value == str(int(value))
        ):
            reasons.append(f"--size {value!r} is not an integer in 1..{_TRANSACTIONS_MAX_PAGE_SIZE}")
        if option == "--cursor" and not (
            isinstance(value, str) and not value.startswith("-") and re.fullmatch(_TRANSACTIONS_CURSOR_PATTERN, value)
        ):
            reasons.append(f"--cursor {value!r} is not an opaque pagination token")
        index += 2
    return reasons


# Phase P3.92-R1 (F-1) -- sous Windows, lancer un .cmd/.bat passe par
# cmd.exe, qui ne respecte pas l'échappement de `list2cmdline` : un argument
# d'un verbe autorisé (ex. `model get <job_type>`) peut alors enchaîner une
# seconde commande (`& higgsfield generate create ...`), hors de toute
# allowlist. Windows ignore les points/espaces finaux d'un nom de fichier
# (`x.cmd.` exécute `x.cmd`) : ils sont retirés avant la comparaison.
def _runs_through_cmd_exe(command: str) -> bool:
    return os.name == "nt" and Path(str(command).rstrip(" .")).suffix.lower() in (".cmd", ".bat")


# Phase P3.92-R2 (F-1bis) -- `shutil.which("node")` suit PATHEXT et peut
# renvoyer un `node.cmd`/`node.bat` placé plus tôt sur le PATH : l'invocation
# « directe » repasserait alors par cmd.exe (même injection que F-1). Seul un
# vrai `node.exe` est accepté comme interpréteur de l'invocation directe.
def _is_node_exe(executable: str) -> bool:
    return Path(str(executable).rstrip(" .")).name.lower() == "node.exe"


# Phase P3.105 (F8-2) -- résolution de l'exécutable CLI, sans lancer quoi que
# ce soit. Priorité :
#   1. `HiggsfieldClient(command=...)` explicite (non None) ;
#   2. variable d'environnement `HIGGSFIELD_CLI_PATH` ;
#   3. défaut npm global Windows : `%APPDATA%\npm\higgsfield.cmd`.
# Une source présente mais invalide ne retombe JAMAIS sur la suivante : le
# client reste non configuré et `run()` refuse avant tout processus. Le
# chemin résolu reste soumis à TOUS les contrôles P3.92 de `run()`
# (repli cmd.exe refusé, interpréteur node.exe exigé) et, en plus, un
# interpréteur de commandes désigné directement est refusé.
HIGGSFIELD_CLI_ENV_VAR = "HIGGSFIELD_CLI_PATH"

# Interpréteurs qui ré-analysent leurs arguments comme des commandes : les
# désigner comme « CLI » rouvrirait l'injection P3.92 par un autre chemin.
_SHELL_INTERPRETER_NAMES = frozenset(
    {"cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"}
)


def _is_shell_interpreter(command: str) -> bool:
    return Path(str(command).rstrip(" .")).name.lower() in _SHELL_INTERPRETER_NAMES


def _default_cli_command() -> Optional[str]:
    if os.name != "nt":
        return None
    appdata = os.environ.get("APPDATA")
    if not appdata or not Path(appdata).is_absolute():
        return None
    return str(Path(appdata) / "npm" / "higgsfield.cmd")


def _resolve_cli_command(command: Optional[str]):
    """Retourne `(command, source, error)` ; `command` est None si la
    source retenue est absente ou invalide (jamais de repli)."""

    if command is not None:
        if not isinstance(command, str) or not command.strip() or "\x00" in command:
            return None, "explicit", f"explicit command {command!r} is empty or invalid"
        return command, "explicit", None

    configured = os.environ.get(HIGGSFIELD_CLI_ENV_VAR)
    if configured is not None:
        path = Path(configured) if configured.strip() and "\x00" not in configured else None
        if path is None or not path.is_absolute() or not path.is_file():
            return None, "environment", (
                f"{HIGGSFIELD_CLI_ENV_VAR}={configured!r} must be an absolute "
                f"path to an existing file"
            )
        return configured, "environment", None

    default = _default_cli_command()
    if default is None:
        return None, "default", (
            f"no Higgsfield CLI configured: set {HIGGSFIELD_CLI_ENV_VAR} or pass "
            f"command= (no default outside Windows or without %APPDATA%)"
        )
    return default, "default", None


def build_create_job_args(job_type: str, prompt: str, **params: Any) -> List[str]:
    """
    Arguments CLI documentés d'une génération réelle (`generate create`).
    Pure : construit une liste, n'exécute RIEN. Extraite telle quelle de
    l'ancien corps de `HiggsfieldClient.create_job()` (Phase P3.83) pour
    que le contrat d'arguments reste figé par les tests sans jamais
    atteindre `run()`.
    """

    args = ["generate", "create", job_type, "--prompt", prompt]

    for name, value in params.items():
        if value is None:
            continue
        flag = "--" + name.replace("_", "-")
        args.extend([flag, str(value)])

    return args


class HiggsfieldClient:
    """
    Safe interface between AI Director and Higgsfield CLI.

    v0.2 (Phase C, MASTER PROMPT V2) :
    - Timeout, CLI introuvable, échec d'authentification et sortie
      invalide sont désormais des erreurs typées (voir
      integrations/higgsfield/errors.py), toutes héritées de
      RuntimeError pour rester 100% compatibles avec le code V1
      existant (agents/cost_engine.py, agents/planner.py, director.py)
      qui capture des `except Exception` génériques.
    - Les méthodes existantes (list_workflows, get_workflow,
      account_status, estimate_cost) conservent EXACTEMENT leur
      signature et leur comportement précédents.
    - Nouvelles méthodes en lecture seule : list_models, get_model,
      get_job, list_jobs, wait_for_job.
    - create_job() existe pour compléter le wrapper CLI, mais n'est
      appelée par AUCUN code de cette phase. Phase P3.83 : elle est
      désormais verrouillée ICI aussi (et plus seulement au niveau du
      Provider, voir provider.py), et `run()` n'exécute que des verbes
      en lecture seule (`_READ_ONLY_CLI_VERBS`).

    Sécurité :
    - Les commandes sont toujours exécutées via une liste d'arguments
      séparés (`shell=False`), jamais via une chaîne shell : aucune
      injection shell n'est possible quel que soit le contenu des
      paramètres.
    - Aucun credential/token n'est jamais passé en argument CLI par ce
      client (l'authentification est gérée par `higgsfield auth login`,
      côté CLI) ni journalisé.
    """

    DEFAULT_TIMEOUT_SECONDS = 120

    _AUTH_FAILURE_MARKERS = (
        "not authenticated",
        "not logged in",
        "unauthorized",
        "invalid token",
        "please run",
        "auth login",
        "authentication failed",
    )

    # Repère le script JS relayé par un shim npm .cmd/.bat Windows
    # ("%_prog%" "%dp0%\...\<entry>.js" %*), pour pouvoir l'invoquer
    # directement (Phase P2.1, cf. run()).
    _CMD_SHIM_JS_ENTRY_PATTERN = re.compile(r'"%dp0%\\([^"]+\.js)"', re.IGNORECASE)

    def __init__(
        self,
        command: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        # Phase P3.105 (F8-2) : cf. `_resolve_cli_command()`.
        self.command, self.command_source, self.command_error = _resolve_cli_command(command)
        self.timeout = timeout or self.DEFAULT_TIMEOUT_SECONDS
        self._direct_invocation = self._resolve_direct_invocation()

    def _resolve_direct_invocation(self) -> Optional[List[str]]:
        """
        Contourne le shim npm .cmd/.bat quand c'est possible (Phase P2.1).

        PROBLÈME CONFIRMÉ (lecture seule, `generate cost`) : sur Windows,
        lancer un fichier .cmd/.bat via subprocess.run(shell=False) passe
        transparemment par cmd.exe (comportement du chargeur Windows,
        indépendant de Python). Le parseur de cmd.exe est orienté ligne :
        tout argument contenant un retour à la ligne littéral (le Master
        Prompt réel en contient toujours) est tronqué à sa première
        ligne, ce qui décale/perd les arguments suivants (ex. --duration)
        sans jamais lever d'erreur. Reproduit : un même prompt donne un
        coût correct sur une seule ligne et un coût différent (calculé
        sur la durée par défaut du modèle) réparti sur plusieurs lignes.

        CONTOURNEMENT : quand self.command est un shim .cmd/.bat suivant
        la disposition npm standard (visible dans son propre contenu :
        "%_prog%" "%dp0%\\...\\<entry>.js" %*), on invoque directement
        l'exécutable Node.js réel sur ce script .js — un vrai exécutable
        Win32, dont l'analyse d'arguments (CommandLineToArgvW) ne scinde
        jamais un argument entre guillemets sur un retour à la ligne.

        Retourne None (comportement inchangé, aucune régression) si :
        - la plateforme n'est pas Windows ;
        - self.command n'est pas un .cmd/.bat ;
        - son contenu ne correspond pas à la disposition npm attendue ;
        - le script .js résolu n'existe pas ;
        - aucun exécutable Node.js n'est trouvable.
        """

        if os.name != "nt" or self.command is None:
            return None

        command_path = Path(self.command)

        if command_path.suffix.lower() not in (".cmd", ".bat"):
            return None

        try:
            shim_text = command_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None

        match = self._CMD_SHIM_JS_ENTRY_PATTERN.search(shim_text)

        if not match:
            return None

        script_path = command_path.parent / match.group(1)

        if not script_path.is_file():
            return None

        bundled_node = command_path.parent / "node.exe"

        if bundled_node.is_file():
            node_executable = str(bundled_node)
        else:
            node_executable = shutil.which("node")

        if not node_executable:
            return None

        return [node_executable, str(script_path)]

    def run(self, *args: str, timeout: Optional[float] = None) -> Any:
        """
        Run a Higgsfield CLI command and return JSON when available.

        Raises (toutes héritées de RuntimeError — compatible V1) :
        - HiggsfieldCLINotFoundError   si l'exécutable est introuvable.
        - HiggsfieldTimeoutError       si la commande dépasse le délai.
        - HiggsfieldAuthenticationError si le CLI signale un échec d'auth.
        - HiggsfieldCommandError       pour tout autre exit code != 0.
        - HiggsfieldInvalidResponseError si la sortie n'est pas un JSON
          valide alors qu'une sortie était attendue.
        - HiggsfieldRealGenerationDisabledError (Phase P3.83) si
          `args[:2]` n'est pas un verbe en lecture seule
          (`_READ_ONLY_CLI_VERBS`) -- levée AVANT toute construction de
          commande et tout `subprocess`, quel que soit le détenteur du
          Client.
        """

        verb = tuple(args[:2])
        if verb not in _READ_ONLY_CLI_VERBS:
            raise HiggsfieldRealGenerationDisabledError(
                "HiggsfieldClient.run() only executes read-only Higgsfield CLI "
                "verbs (Phase P3.83 runtime lock): generation and every "
                "non-allowlisted verb are refused before any process is "
                "started, whoever holds this client.",
                reasons=[f"cli_verb_not_read_only: {verb!r}"],
            )
        if verb == ("generate", "cost"):
            cost_violations = _generate_cost_violations(args)
            if cost_violations:
                raise HiggsfieldRealGenerationDisabledError(
                    "HiggsfieldClient.run() only executes the exact read-only "
                    "cost-estimation form (Phase P3.85): generate cost "
                    "<job_type> [--prompt] [--duration] [--resolution] "
                    "[--aspect-ratio].",
                    reasons=cost_violations,
                )
        if verb == ("account", "transactions"):
            transactions_violations = _account_transactions_violations(args)
            if transactions_violations:
                raise HiggsfieldRealGenerationDisabledError(
                    "HiggsfieldClient.run() only executes the canonical read-only "
                    "form (Phase P3.86-C): account transactions [--size <1..100>] "
                    "[--cursor <token>].",
                    reasons=transactions_violations,
                )
        if self.command is None:
            # Phase P3.105 (F8-2) : source absente ou invalide -- aucun repli.
            raise HiggsfieldCLINotFoundError(
                f"Higgsfield CLI not configured ({self.command_source}): "
                f"{self.command_error}. No process started."
            )
        if _is_shell_interpreter(self.command):
            raise HiggsfieldRealGenerationDisabledError(
                "HiggsfieldClient.run() never launches a command interpreter as "
                "the Higgsfield CLI (Phase P3.105): it would re-parse the "
                "arguments exactly like the refused cmd.exe fallback (P3.92).",
                reasons=[f"shell_interpreter_refused: {self.command!r}"],
            )
        if self._direct_invocation is None and _runs_through_cmd_exe(self.command):
            raise HiggsfieldRealGenerationDisabledError(
                "HiggsfieldClient.run() never executes the Higgsfield CLI through "
                "a .cmd/.bat shim (Phase P3.92-R1): cmd.exe would re-parse the "
                "arguments and could chain a generation command outside the "
                "read-only allowlist. Only the resolved direct Node.js "
                "invocation (npm layout) is executed.",
                reasons=[f"cmd_exe_fallback_refused: {self.command!r}"],
            )

        base_command = self._direct_invocation or [self.command]
        if self._direct_invocation is not None and not _is_node_exe(base_command[0]):
            raise HiggsfieldRealGenerationDisabledError(
                "HiggsfieldClient.run() only launches the direct invocation "
                "through a real node.exe (Phase P3.92-R2): a node.cmd/node.bat "
                "or any other wrapper resolved on PATH would run through "
                "cmd.exe and could chain a generation command outside the "
                "read-only allowlist.",
                reasons=[f"direct_invocation_interpreter_refused: {base_command[0]!r}"],
            )
        command = [*base_command, "--json", *args]
        effective_timeout = timeout if timeout is not None else self.timeout

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=effective_timeout,
                shell=False,
            )
        except FileNotFoundError as error:
            raise HiggsfieldCLINotFoundError(
                f"Higgsfield CLI executable not found: {command[0]}"
            ) from error
        except subprocess.TimeoutExpired as error:
            raise HiggsfieldTimeoutError(
                f"Higgsfield CLI command timed out after "
                f"{effective_timeout}s: {' '.join(args)}"
            ) from error

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()

        if result.returncode != 0:
            combined = stderr or stdout

            if self._looks_like_auth_failure(combined):
                raise HiggsfieldAuthenticationError(
                    "Higgsfield CLI authentication failure. "
                    "Run 'higgsfield auth login' to re-authenticate."
                )

            raise HiggsfieldCommandError(
                f"Higgsfield CLI command failed (exit code "
                f"{result.returncode}): {' '.join(args)}",
                exit_code=result.returncode,
                stderr=stderr,
            )

        if not stdout:
            return None

        try:
            return json.loads(stdout)
        except json.JSONDecodeError as error:
            raise HiggsfieldInvalidResponseError(
                f"Higgsfield CLI returned non-JSON output for: "
                f"{' '.join(args)}"
            ) from error

    @classmethod
    def _looks_like_auth_failure(cls, text: str) -> bool:
        lowered = text.lower()
        return any(marker in lowered for marker in cls._AUTH_FAILURE_MARKERS)

    # ========================================================
    # MÉTHODES EXISTANTES (inchangées — signature et comportement V1)
    # ========================================================

    def list_workflows(self) -> Any:
        """Return available Higgsfield workflows."""
        return self.run("workflow", "list")

    def get_workflow(self, workflow_name: str) -> Any:
        """Return parameters for a specific workflow."""
        return self.run("workflow", "get", workflow_name)

    def account_status(self) -> Any:
        """Return the current Higgsfield account status."""
        return self.run("account", "status")

    def get_account_transactions(self, size: Optional[int] = None, cursor: Optional[str] = None) -> Any:
        """
        Read-only credit/transaction history (Phase P3.86-C), never used by
        the P2 decision path. `size` : entier 1..100 ; `cursor` : jeton de
        pagination renvoyé par la CLI. Paramètres validés ICI (types) puis
        à nouveau par `run()` (forme canonique) -- aucune autre option,
        aucun argument libre.
        """

        args = ["account", "transactions"]
        if size is not None:
            if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= _TRANSACTIONS_MAX_PAGE_SIZE:
                raise ValueError(f"size must be an int in 1..{_TRANSACTIONS_MAX_PAGE_SIZE}, got {size!r}")
            args.extend(["--size", str(size)])
        if cursor is not None:
            if not isinstance(cursor, str):
                raise ValueError(f"cursor must be a str, got {type(cursor).__name__}")
            args.extend(["--cursor", cursor])
        return self.run(*args)

    def estimate_cost(
        self,
        job_type: str,
        prompt: str,
        duration: int | None = None,
        resolution: str | None = None,
        aspect_ratio: str | None = None,
    ) -> Any:
        """Estimate Higgsfield credits without creating a generation job."""

        args = [
            "generate",
            "cost",
            job_type,
            "--prompt",
            prompt,
        ]

        if duration is not None:
            args.extend(["--duration", str(duration)])

        if resolution is not None:
            args.extend(["--resolution", resolution])

        if aspect_ratio is not None:
            args.extend(["--aspect-ratio", aspect_ratio])

        return self.run(*args)

    # ========================================================
    # NOUVELLES MÉTHODES — lecture seule (Phase C)
    # ========================================================

    def list_models(self, video: bool = True) -> Any:
        """List available Higgsfield models (read-only)."""

        args = ["model", "list"]

        if video:
            args.append("--video")

        return self.run(*args)

    def get_model(self, job_type: str) -> Any:
        """Return the parameter schema for a specific model (read-only)."""
        return self.run("model", "get", job_type)

    def get_job(self, job_id: str) -> Any:
        """Show one generation job (read-only, no credits spent)."""
        return self.run("generate", "get", job_id)

    def list_jobs(self) -> Any:
        """List recent generation jobs (read-only)."""
        return self.run("generate", "list")

    def wait_for_job(
        self,
        job_id: str,
        timeout_seconds: float = 600,
        interval_seconds: float = 3,
    ) -> Any:
        """
        Poll an EXISTING job until it finishes (read-only — does not
        create any job, does not spend additional credits).
        """

        return self.run(
            "generate",
            "wait",
            job_id,
            "--timeout",
            f"{int(timeout_seconds)}s",
            "--interval",
            f"{int(interval_seconds)}s",
            timeout=timeout_seconds + 15,
        )

    # ========================================================
    # GÉNÉRATION RÉELLE — verrouillée inconditionnellement (P3.83)
    # ========================================================

    def create_job(self, job_type: str, prompt: str, **params: Any) -> Any:
        """
        Create a REAL Higgsfield generation job (BILLABLE) -- CLOSED.

        Phase P3.83 (verrou runtime D, spécification P3.82) : lève
        TOUJOURS `HiggsfieldRealGenerationDisabledError`, en première
        instruction -- aucun argument construit, `self.run()` jamais
        appelé, aucun `subprocess`. Avant P3.83, seul
        `HiggsfieldProvider.create_job()` était verrouillé : tout
        détenteur du Client (`AIDirector.higgsfield`,
        `<objet P2>.provider.client`, instance directe) pouvait facturer
        sans passer par P2.

        Sans état et sans autorité : ni appelant, ni variable, ni
        booléen ne rouvre ce verrou. Une future activation réelle (phase
        dédiée) le remplacera uniquement par la consommation d'une
        capacité émise par `GenerationJobService.execute()` après toute
        la chaîne P2 -- jamais par une décision du Client lui-même.
        Arguments documentés : `build_create_job_args()`.
        """

        raise HiggsfieldRealGenerationDisabledError(
            "HiggsfieldClient.create_job() is disabled (Phase P3.83 runtime "
            "lock): real Higgsfield generation is only reachable through the "
            "P2 chain, which keeps HiggsfieldProvider.create_job() closed in "
            "this phase. Use MockHiggsfieldProvider to test job creation.",
            reasons=["client_create_job_unconditionally_closed"],
        )


if __name__ == "__main__":
    client = HiggsfieldClient()

    print("Higgsfield Client - TEST")
    print("-" * 40)

    print("ACCOUNT:")
    print(client.account_status())

    print("\nWORKFLOWS:")
    print(client.list_workflows())
