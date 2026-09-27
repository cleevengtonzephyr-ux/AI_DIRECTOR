"""
AI DIRECTOR — Architecture Drift Detector (Phase P3.31, MASTER PROMPT V2)

Compare l'état RÉEL du repository (analyse AST, jamais du texte brut) au
`CanonicalArchitectureContract` (`agents/canonical_architecture_contract.py`)
et répond factuellement à la question posée par P3.31 :

    "Une modification future du repository a-t-elle créé une dépendance
     interdite, une nouvelle autorité, ou un second chemin de
     production ?"

STOP -- CE QUE CE MODULE N'EST PAS :
- Il ne modifie, ne supprime, ni ne déplace AUCUN fichier.
- Il n'appelle jamais Higgsfield, le réseau, ou `create_job()`.
- Il ne construit jamais de `RealGenerationAuthorization`, de contrat
  d'activation, ni aucune instance des mécanismes P2 qu'il surveille --
  il lit leur CODE SOURCE (`ast.parse`), il ne les IMPORTE ni ne les
  INSTANCIE jamais lui-même.
- Il ne réimplémente aucune logique de `GenerationApprovalGate`,
  `ReleaseCandidateIdentityLock`, `RequestScopedActivationService`,
  `ControlledRealProviderActivationService`, `CriticalSectionLock`,
  `ExecutedRequestStore`, `GenerationJobService`, ou `HiggsfieldProvider`
  -- il vérifie seulement, depuis l'extérieur, que ces frontières
  n'ont pas été contournées ailleurs dans le repository.

MÉTHODE -- AST, PAS GREP (Section 8, rapport P3.31) :
Chaque fichier `.py` pertinent est analysé via `ast.parse()`. Seuls les
noeuds `ast.Import`/`ast.ImportFrom` (imports), `ast.Call` (appels) et
`ast.ClassDef`/`ast.FunctionDef` (définitions) sont inspectés. Un nom
de symbole apparaissant dans un docstring, un commentaire, ou une
chaîne de caractères n'est JAMAIS un noeud `Import`/`Call` -- il est
donc structurellement impossible que ce détecteur les confonde avec du
code exécutable (contrairement à un grep textuel). Vérifié explicitement
par `tests/test_architecture_drift_detector.py::test_docstring_mentions_
never_trigger_drift`.

PORTÉE -- DOMAINES TEST/SCRIPT EXCLUS PAR CONCEPTION :
Les fichiers sous `tests/` et `scripts/` sont exclus de TOUTES les
vérifications d'autorité (Domain.TEST/Domain.SCRIPT, cf. contrat) : les
tests construisent délibérément des objets interdits en production pour
vérifier que le Gate/les services les REJETTENT (ex. `Real
GenerationAuthorization` invalide), et `scripts/demo_test.py` construit
une autorisation humaine explicite à des fins de démonstration
documentée (cf. rapport P3.28-P3.30). Scanner ces répertoires avec les
mêmes règles produirait des centaines de faux positifs et masquerait
les vrais signaux dans le bruit -- exclusion délibérée, jamais une
lacune de couverture (cf. Section 9, "avoid false positives ... test
mocks explicitly authorized").
P3.76-R1 : l'exemption SCRIPT ne couvre plus que la CONSTRUCTION
d'autorité et la cardinalité create_job -- la règle certificate/authority
(bridge, marche transitive) s'applique aux scripts comme à tout module
non-TEST. Tout autre `.py` first-party hors des répertoires nommés est
aussi balayé (UNCLASSIFIED_LEGACY, cf. `_EXCLUDED_SCAN_DIR_NAMES`).

FAIL CLOSED (Section 10, rapport P3.31) : un fichier illisible ou dont
la syntaxe ne peut pas être analysée (`SyntaxError`) transforme le
résultat global en `ANALYSIS_INCOMPLETE`, JAMAIS en `NO_DRIFT` -- un
doute n'est jamais silencieusement transformé en succès.

DÉTERMINISME : les fichiers sont énumérés triés (`sorted()`), les
findings sont triés par (sévérité, fichier, ligne) avant d'être
renvoyés -- deux exécutions successives sur un repository inchangé
renvoient toujours exactement le même `DriftReport`.
"""

from __future__ import annotations

import ast
import os
import sys
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.canonical_architecture_contract import (
    CANONICAL_ARCHITECTURE_CONTRACT,
    CanonicalArchitectureContract,
    Domain,
)

# Répertoires balayés par défaut -- jamais `state/`, `assets/`,
# `projects/`, `logs/`, `outputs/` (aucun code Python n'y vit).
_DEFAULT_SCAN_DIRS: Tuple[str, ...] = ("agents", "integrations", "scripts", "tests")
_DEFAULT_SCAN_ROOT_FILES: Tuple[str, ...] = ("director.py",)

# SCAN BOUNDARY (P3.76-R1): being outside the directories above never
# makes a file safe -- every other first-party `.py` under the root (a
# new top-level package, a root-level module, `config/*.py`, ...) is
# scanned too, as UNCLASSIFIED_LEGACY. The ONLY exclusions are
# directories that never hold first-party code: hidden directories
# (`.git`, `.venv`, `.claude`, caches) and the names below (virtualenvs,
# build output, third-party installs, bytecode caches).
_EXCLUDED_SCAN_DIR_NAMES: FrozenSet[str] = frozenset(
    {"__pycache__", "venv", "env", "build", "dist", "node_modules", "site-packages"}
)


def _is_excluded_scan_dir(name: str) -> bool:
    return name.startswith(".") or name in _EXCLUDED_SCAN_DIR_NAMES or name.endswith(".egg-info")


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFORMATIONAL = "INFORMATIONAL"


_SEVERITY_ORDER: Dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFORMATIONAL: 4,
}


class DriftStatus(str, Enum):
    NO_DRIFT = "NO_DRIFT"
    DRIFT_DETECTED = "DRIFT_DETECTED"
    ANALYSIS_INCOMPLETE = "ANALYSIS_INCOMPLETE"


@dataclass(frozen=True)
class DriftFinding:
    """Un constat unique -- jamais de doute résorbé en silence : toute
    condition suspecte produit un finding, sa `severity` seule indique
    l'urgence, jamais son absence."""

    code: str
    severity: Severity
    file: str
    line: int
    component: str
    violated_rule: str
    evidence: str
    explanation: str


@dataclass(frozen=True)
class DriftReport:
    status: DriftStatus
    findings: Tuple[DriftFinding, ...]
    files_analyzed: Tuple[str, ...]
    files_unreadable: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_critical(self) -> bool:
        return any(f.severity == Severity.CRITICAL for f in self.findings)

    @property
    def has_actionable_drift(self) -> bool:
        """
        Depuis Phase P3.32 (Section 16/21) : strictement équivalent à
        `status == DRIFT_DETECTED` (un finding `INFORMATIONAL` ne gouverne
        plus le statut global -- cf. `ArchitectureDriftDetector.analyze()`).
        Conservée comme alias de lecture explicite : le nom lui-même
        documente l'intention ("y a-t-il une dérive qui nécessite une
        action ?"), sans qu'un lecteur ait à connaître la sémantique
        exacte de `status`.
        """

        return any(
            f.severity in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW)
            for f in self.findings
        )


@dataclass(frozen=True)
class _FileFacts:
    """Faits AST bruts extraits d'un seul fichier -- jamais de
    jugement porté ici, uniquement des observations structurelles."""

    relative_path: str
    domain: Domain
    import_modules: Tuple[Tuple[str, int], ...]  # (module_dotté, ligne)
    calls: Tuple[Tuple[str, int], ...]  # (nom_du_symbole_appelé, ligne)
    class_defs: Tuple[Tuple[str, int], ...]
    function_defs: Tuple[Tuple[str, int], ...]
    # Attribute reads that are NOT the target of a call (P3.71) --
    # `x.is_ready` in `if x.is_ready:`, never `x.is_ready()`.
    attribute_loads: Tuple[Tuple[str, int], ...] = ()
    # P3.76-R1: absolute dotted names this file pulls a SYMBOL from --
    # `from M import N` -> "M.N" (`*` kept as-is), and `alias.N` where
    # `alias` is bound by an import -> "<bound module>.N". Resolved against
    # other files' `module_bindings` in `analyze()`, so a name re-exported
    # by module M (e.g. the P3.54 Issuer re-exposing `GenerationRequest`)
    # counts as an import of the module that really defines it.
    symbol_refs: Tuple[Tuple[str, int], ...] = ()
    # Names bound at MODULE level by an import (what `from this import X`
    # or `this.X` can reach): local name -> absolute dotted source.
    module_bindings: Tuple[Tuple[str, str], ...] = ()
    # Modules reached ONLY through such a re-export (filled by
    # `_resolve_symbol_imports`). Kept apart from `import_modules` so the
    # P3.63-P3.65 edge findings keep their exact semantics; consumed where
    # the Issuer exception cut the walk (bridge rule, outbound direct check).
    reexport_modules: Tuple[Tuple[str, int], ...] = ()
    # P3.77-R1 (G2): every call resolving to `run` -- (line, its literal
    # positional string arguments). The CLI-create policy itself lives in
    # `_check_create_job_cardinality`, never here.
    run_calls: Tuple[Tuple[int, Tuple[str, ...]], ...] = ()
    # P3.78-R1 (G4): loads in a VALUE position -- anything but a callee,
    # an `is`/`is not` operand, an isinstance/issubclass class argument or
    # an annotation. Watched method names (`o.execute` passed/stored), and
    # absolute dotted provenance of watched symbols (import-bound or
    # defined here), resolved against the authority core in `analyze()`.
    method_value_refs: Tuple[Tuple[str, int], ...] = ()
    symbol_value_refs: Tuple[Tuple[str, int], ...] = ()
    # P3.101 (P3.81 restoration): the subset of `import_modules` imported as
    # MODULES (`import X`, `from pkg import module`) -- a module import
    # exposes that module's whole namespace; a symbol import
    # (`from M import Name`) only exposes `Name` (P3.77-R1 G3).
    module_imports: Tuple[Tuple[str, int], ...] = ()


def _package_parts(relative_path: str) -> List[str]:
    """Package a file belongs to: `agents/x.py` -> ["agents"],
    `agents/sub/__init__.py` -> ["agents", "sub"]."""

    parts = relative_path.replace("\\", "/")[:-3].split("/")
    return parts[:-1]


def _absolute_import_module(relative_path: str, node: ast.ImportFrom) -> Optional[str]:
    """P3.76-R1: `from .x import` / `from ..x import` / `from . import x`
    resolved to the absolute dotted module Python itself would load --
    the raw `node.module` ("x") never matched a contract prefix. Returns
    `None` when the relative import escapes the top-level package (Python
    raises ImportError there too)."""

    if not node.level:
        return node.module
    package = _package_parts(relative_path)
    if node.level > len(package):
        return None
    base = package[: len(package) - (node.level - 1)]
    parts = base + ([node.module] if node.module else [])
    return ".".join(parts) or None


def _dotted_name(node: ast.AST) -> Optional[str]:
    """`a.b.c` (Attribute chain ending on a Name) -> "a.b.c", else None."""

    segments: List[str] = []
    while isinstance(node, ast.Attribute):
        segments.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    segments.append(node.id)
    return ".".join(reversed(segments))


def _module_level_statements(body: Sequence[ast.stmt]):
    for statement in body:
        yield statement
        if isinstance(statement, (ast.If, ast.Try, ast.With)):
            for block in ("body", "orelse", "finalbody"):
                yield from _module_level_statements(getattr(statement, block, []))
            for handler in getattr(statement, "handlers", []):
                yield from _module_level_statements(handler.body)


def _import_bindings(relative_path: str, statement: ast.stmt) -> List[Tuple[str, str]]:
    """(local name, absolute dotted source) bound by one import statement."""

    bindings: List[Tuple[str, str]] = []
    if isinstance(statement, ast.Import):
        for alias in statement.names:
            if alias.asname:
                bindings.append((alias.asname, alias.name))
            else:
                head = alias.name.split(".")[0]
                bindings.append((head, head))
    elif isinstance(statement, ast.ImportFrom):
        module = _absolute_import_module(relative_path, statement)
        if module:
            for alias in statement.names:
                if alias.name == "*":
                    bindings.append(("*", f"{module}.*"))
                else:
                    bindings.append((alias.asname or alias.name, f"{module}.{alias.name}"))
    return bindings


def _call_target_name(func_node: ast.AST) -> Optional[str]:
    """Résout le nom appelé d'un noeud `ast.Call.func` : `Name` ->
    son identifiant ; `Attribute` (ex. `self.provider.create_job`) ->
    son dernier segment (`create_job`). Renvoie `None` pour toute
    autre forme (ex. un appel sur le résultat d'un appel) -- jamais
    une supposition."""

    if isinstance(func_node, ast.Name):
        return func_node.id
    if isinstance(func_node, ast.Attribute):
        return func_node.attr
    return None


def _resolve_rebound_names(
    name: str, rebinds: Dict[str, List[str]], seen: Optional[set] = None
) -> set:
    """
    P3.77-R1 (G1): every symbol name `name` may stand for through import
    aliases (`from M import Sym as name`) and simple reassignments
    (`name = Sym`, `name = obj.Sym`), followed transitively. `rebinds` is
    FILE-WIDE and keeps every candidate a name was ever bound to -- an
    over-approximation (never scope-aware), so a rebinding can only ADD a
    name to what the checks see, never hide one. Cycle-safe (`seen`),
    purely syntactic: the analysed code is never executed.
    """
    seen = set() if seen is None else seen
    resolved: set = set()
    for target in rebinds.get(name, ()):
        if target in seen:
            continue
        seen.add(target)
        resolved.add(target)
        resolved |= _resolve_rebound_names(target, rebinds, seen)
    return resolved


def _literal_positional_strings(call: ast.Call) -> Tuple[str, ...]:
    """P3.77-R1 (G2): string literals passed positionally, including a
    literal `*("generate", "create")`. Anything computed at runtime is
    unknown statically and is never guessed."""
    values: List[str] = []
    for arg in call.args:
        items = arg.value.elts if isinstance(arg, ast.Starred) and isinstance(arg.value, (ast.Tuple, ast.List)) else [arg]
        for item in items:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                values.append(item.value)
    return tuple(values)


def _allow_chain(node: ast.AST, not_values: set) -> None:
    """P3.78-R1 (G4): `node` and the base chain of an attribute access
    (`a.b.c` -> `a.b`, `a`) are in a non-value position."""
    while True:
        not_values.add(id(node))
        if not isinstance(node, ast.Attribute):
            return
        node = node.value


def _allow_subtree(node: ast.AST, not_values: set) -> None:
    """P3.78-R1 (G4): every node of an annotation is a type, never a value."""
    not_values.update(id(child) for child in ast.walk(node))


def _extract_file_facts(
    relative_path: str,
    source: str,
    domain: Domain,
    known_modules: FrozenSet[str] = frozenset(),
    watched_methods: FrozenSet[str] = frozenset(),
    watched_symbols: FrozenSet[str] = frozenset(),
) -> _FileFacts:
    tree = ast.parse(source, filename=relative_path)

    import_modules: List[Tuple[str, int]] = []
    module_imports: List[Tuple[str, int]] = []
    calls: List[Tuple[str, int]] = []
    class_defs: List[Tuple[str, int]] = []
    function_defs: List[Tuple[str, int]] = []
    attribute_loads: List[Tuple[str, int]] = []
    # Filled in the SAME pass below: `ast.walk` is breadth-first, so a
    # Call is always visited before its own `func` Attribute (a second
    # full walk here doubled the detector's cost -- measured in P3.71).
    call_targets: set = set()

    local_bindings: Dict[str, str] = {}
    symbol_refs: List[Tuple[str, int]] = []
    dotted_loads: List[Tuple[str, int]] = []
    # P3.77-R1 (G1): local name -> symbol names it was bound to (import
    # alias or simple reassignment), and every Call node for the post-pass.
    rebinds: Dict[str, List[str]] = {}
    call_nodes: List[ast.Call] = []
    # P3.78-R1 (G4): ids of nodes in a NON-value position (callee chain,
    # `is` operand, isinstance/issubclass classes, annotations). `ast.walk`
    # is breadth-first, so a parent always marks them before they are met.
    not_values: set = set()
    method_value_refs: List[Tuple[str, int]] = []
    value_names: List[Tuple[str, int]] = []
    value_dotted: List[Tuple[ast.Attribute, int]] = []
    all_bindings: List[Tuple[str, str]] = []  # every `from` binding, star imports included

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                import_modules.append((alias.name, node.lineno))
                module_imports.append((alias.name, node.lineno))
            local_bindings.update(_import_bindings(relative_path, node))
        elif isinstance(node, ast.ImportFrom):
            # P3.76-R1: relative forms resolved to their absolute module
            # FIRST, so every check below sees `agents.certificate_x`,
            # never the raw `certificate_x` / `None` of `from . import`.
            module = _absolute_import_module(relative_path, node)
            if module:
                import_modules.append((module, node.lineno))
                # `from agents import certificate_lifecycle` imports a
                # MODULE, yet `node.module` is only `agents` -- matched by
                # no prefix (rapport P3.71). Record `package.name` too,
                # but only when it is a known module, so a symbol import
                # (`from agents.x import Symbol`) never double-reports.
                for alias in node.names:
                    candidate = f"{module}.{alias.name}"
                    if candidate in known_modules:
                        import_modules.append((candidate, node.lineno))
                        module_imports.append((candidate, node.lineno))
                    else:
                        symbol_refs.append((candidate, node.lineno))
                local_bindings.update(_import_bindings(relative_path, node))
                all_bindings.extend(_import_bindings(relative_path, node))
            for alias in node.names:
                if alias.asname and alias.asname != alias.name:
                    rebinds.setdefault(alias.asname, []).append(alias.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            # `X = Sym` / `X = obj.Sym` / `X: T = Sym` -- single Name target
            # only; tuple unpacking, containers and getattr() stay out of
            # reach of a static pass (documented limit, never guessed).
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value_name = _call_target_name(node.value) if node.value is not None else None
            if value_name and len(targets) == 1 and isinstance(targets[0], ast.Name):
                rebinds.setdefault(targets[0].id, []).append(value_name)
            if isinstance(node, ast.AnnAssign):
                _allow_subtree(node.annotation, not_values)
        elif isinstance(node, ast.Attribute):
            if isinstance(node.ctx, ast.Load) and id(node) not in call_targets:
                attribute_loads.append((node.attr, node.lineno))
            if isinstance(node.ctx, ast.Load) and id(node) not in not_values:
                if node.attr in watched_methods:
                    method_value_refs.append((node.attr, node.lineno))
                if node.attr in watched_symbols:
                    value_dotted.append((node, node.lineno))
            dotted = _dotted_name(node)
            if dotted:
                dotted_loads.append((dotted, node.lineno))
        elif isinstance(node, ast.Name):
            # Aliases are only known once every import is read: resolved
            # after the walk, never filtered here by textual name.
            if watched_symbols and isinstance(node.ctx, ast.Load) and id(node) not in not_values:
                value_names.append((node.id, node.lineno))
        elif isinstance(node, ast.Call):
            call_targets.add(id(node.func))
            _allow_chain(node.func, not_values)
            if isinstance(node.func, ast.Name) and node.func.id in ("isinstance", "issubclass") and len(node.args) >= 2:
                classes = node.args[1]
                for item in classes.elts if isinstance(classes, (ast.Tuple, ast.List)) else [classes]:
                    _allow_chain(item, not_values)
            name = _call_target_name(node.func)
            if name:
                calls.append((name, node.lineno))
            call_nodes.append(node)
        elif isinstance(node, ast.Compare):
            if all(isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops):
                for operand in [node.left, *node.comparators]:
                    _allow_chain(operand, not_values)
        elif isinstance(node, ast.ClassDef):
            class_defs.append((node.name, node.lineno))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function_defs.append((node.name, node.lineno))
            arguments = node.args
            for arg in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, arguments.vararg, arguments.kwarg]:
                if arg is not None and arg.annotation is not None:
                    _allow_subtree(arg.annotation, not_values)
            if node.returns is not None:
                _allow_subtree(node.returns, not_values)

    # `alias.N` -> "<module alias is bound to>.N" (only for import-bound
    # heads: `self.x`, locals, etc. are never module references).
    for dotted, line in dotted_loads:
        head, _, rest = dotted.partition(".")
        if head in local_bindings:
            symbol_refs.append((f"{local_bindings[head]}.{rest}", line))

    # P3.77-R1 (G1): `H(...)` where `H` is an alias/reassignment of `Sym`
    # is ALSO recorded as a call to `Sym` (the syntactic name is kept), so
    # every name-based check below sees the symbol really called.
    # P3.77-R1 (G2): calls resolving to `run` keep their literal arguments.
    run_calls: List[Tuple[int, Tuple[str, ...]]] = []
    for call in call_nodes:
        names = {_call_target_name(call.func)}
        if isinstance(call.func, ast.Name):
            resolved = _resolve_rebound_names(call.func.id, rebinds)
            calls.extend((symbol, call.lineno) for symbol in sorted(resolved))
            names |= resolved
        if "run" in names:
            run_calls.append((call.lineno, _literal_positional_strings(call)))

    # P3.78-R1 (G4-b): absolute provenance of watched symbols used as values
    # -- import-bound names/aliases, import-bound module attributes, or a
    # class this very file defines. Whether that provenance really is the
    # authority core is decided in `analyze()`, across files.
    symbol_value_refs: List[Tuple[str, int]] = []
    this_module = relative_path[:-3].replace("/", ".")
    local_classes = {name for name, _ in class_defs}
    for name, line in value_names:
        if name in local_bindings:
            candidates = [local_bindings[name]]
        elif name in local_classes:
            candidates = [f"{this_module}.{name}"]
        else:
            # `from M import *`: M may provide `name` -- `analyze()` only
            # keeps it if M really defines or re-exports that symbol.
            candidates = [f"{source[:-2]}.{name}" for local, source in all_bindings if local == "*"]
        symbol_value_refs.extend(
            (dotted, line) for dotted in candidates if dotted.rpartition(".")[2] in watched_symbols
        )
    for node, line in value_dotted:
        dotted = _dotted_name(node)
        head, _, rest = (dotted or "").partition(".")
        if head in local_bindings:
            symbol_value_refs.append((f"{local_bindings[head]}.{rest}", line))

    module_bindings: List[Tuple[str, str]] = []
    for statement in _module_level_statements(tree.body):
        module_bindings.extend(_import_bindings(relative_path, statement))

    return _FileFacts(
        relative_path=relative_path,
        domain=domain,
        import_modules=tuple(import_modules),
        calls=tuple(calls),
        class_defs=tuple(class_defs),
        function_defs=tuple(function_defs),
        attribute_loads=tuple(attribute_loads),
        symbol_refs=tuple(symbol_refs),
        module_bindings=tuple(module_bindings),
        run_calls=tuple(run_calls),
        method_value_refs=tuple(method_value_refs),
        symbol_value_refs=tuple(symbol_value_refs),
        module_imports=tuple(module_imports),
    )


def _resolve_symbol_imports(
    facts_by_file: Dict[str, _FileFacts], known_modules: FrozenSet[str]
) -> Dict[str, _FileFacts]:
    """
    P3.76-R1 -- resolution of symbol re-exports, applied once in
    `analyze()` on top of the (relative-aware) `import_modules`. A symbol
    pulled through a module that merely re-exports it
    (`from agents.production_activation_readiness_certificate import
    GenerationRequest`, `iss.GenerationRequest`, `from helper import *`)
    is recorded (`reexport_modules`) against the module that binds it, following
    re-export chains of any length. Cycle-safe (`seen`), first-party only.
    """

    bindings_by_module = {
        path[:-3].replace("/", "."): facts.module_bindings
        for path, facts in facts_by_file.items()
    }

    def split_known(dotted: str) -> Tuple[Optional[str], Optional[str]]:
        # Longest known-module prefix of `dotted`, plus the next segment.
        parts = dotted.split(".")
        for cut in range(len(parts), 0, -1):
            prefix = ".".join(parts[:cut])
            if prefix in known_modules:
                return prefix, (parts[cut] if cut < len(parts) else None)
        return None, None

    def sources(dotted: str, seen: set) -> List[str]:
        module, name = split_known(dotted)
        if module is None:
            return []
        found = [module]
        if name is None or (module, name) in seen:
            return found
        seen.add((module, name))
        for local, source in bindings_by_module.get(module, ()):
            if local == "*":  # `from X import *` inside module: N may come from X
                found.extend(sources(f"{source[:-2]}.{name}", seen))
            elif local == name or (name == "*" and not local.startswith("_")):
                found.extend(sources(source, seen))
        return found

    resolved: Dict[str, _FileFacts] = {}
    for path, facts in facts_by_file.items():
        seen_modules = {path[:-3].replace("/", ".")} | {m for m, _line in facts.import_modules}
        extra: List[Tuple[str, int]] = []
        for dotted, line in facts.symbol_refs:
            for module in sources(dotted, set()):
                if module not in seen_modules:
                    seen_modules.add(module)
                    extra.append((module, line))
        resolved[path] = replace(facts, reexport_modules=tuple(extra)) if extra else facts
    return resolved


def _with_reexports(facts: _FileFacts) -> _FileFacts:
    return replace(facts, import_modules=facts.import_modules + facts.reexport_modules)


def _has_import_with_prefix(
    facts: _FileFacts, prefixes: Sequence[str]
) -> List[Tuple[str, str, int]]:
    """Renvoie la liste des (module_importé, préfixe_correspondant, ligne)
    pour lesquels `module_importé` est exactement `prefixe` ou un
    sous-module de `prefixe` (`prefixe + '.'`) -- jamais une simple
    sous-chaîne, pour éviter un faux positif sur un module dont le nom
    contiendrait `prefixe` sans en être un membre réel."""

    hits: List[Tuple[str, str, int]] = []
    for module, line in facts.import_modules:
        for prefix in prefixes:
            if module == prefix or module.startswith(prefix + "."):
                hits.append((module, prefix, line))
    return hits


class ArchitectureDriftDetector:
    """
    AI DIRECTOR — Architecture Drift Detector (Phase P3.31)

    Purement analytique : `analyze()` ne fait que lire des fichiers
    `.py` sous `root` et comparer leurs faits AST au contrat. Aucun
    effet de bord, aucun réseau, aucune construction d'objet P2 réel.
    """

    def __init__(
        self,
        contract: CanonicalArchitectureContract = CANONICAL_ARCHITECTURE_CONTRACT,
        root: Optional[Path] = None,
        scan_dirs: Sequence[str] = _DEFAULT_SCAN_DIRS,
        scan_root_files: Sequence[str] = _DEFAULT_SCAN_ROOT_FILES,
    ):
        self.contract = contract
        self.root = Path(root) if root is not None else PROJECT_ROOT
        self.scan_dirs = tuple(scan_dirs)
        self.scan_root_files = tuple(scan_root_files)

    # ------------------------------------------------------------------
    # DÉCOUVERTE DES FICHIERS -- triée, déterministe.
    # ------------------------------------------------------------------

    def _discover_files(self) -> List[str]:
        discovered: List[str] = []

        for dir_name in self.scan_dirs:
            base = self.root / dir_name
            if not base.exists():
                continue
            for path in sorted(base.rglob("*.py")):
                if "__pycache__" in path.parts:
                    continue
                rel = str(path.relative_to(self.root)).replace("\\", "/")
                discovered.append(rel)

        for file_name in self.scan_root_files:
            path = self.root / file_name
            if path.exists():
                discovered.append(file_name)

        # P3.76-R1 scan boundary: everything else first-party, too.
        for dir_path, dir_names, file_names in os.walk(self.root):
            dir_names[:] = sorted(d for d in dir_names if not _is_excluded_scan_dir(d))
            for file_name in file_names:
                if file_name.endswith(".py"):
                    rel = str((Path(dir_path) / file_name).relative_to(self.root))
                    discovered.append(rel.replace("\\", "/"))

        return sorted(set(discovered))

    # ------------------------------------------------------------------
    # ANALYSE PRINCIPALE
    # ------------------------------------------------------------------

    def analyze(self) -> DriftReport:
        relative_paths = self._discover_files()

        facts_by_file: Dict[str, _FileFacts] = {}
        unreadable: List[str] = []

        # Every module the repository has, plus every module the contract
        # names (so a contract module absent from a partial tree is still
        # resolvable) -- used only to recognise `from package import module`.
        contract_files = (
            self.contract.business_editorial_files
            | self.contract.production_modeling_files
            | self.contract.bridge_files
            | self.contract.p2_authority_core_files
            | self.contract.dispatch_files
            | self.contract.entry_point_files
            | self.contract.certificate_subsystem_files
        )
        known_modules = frozenset(
            path[:-3].replace("/", ".") for path in set(relative_paths) | contract_files
        )

        for rel_path in relative_paths:
            domain = self.contract.domain_of(rel_path)
            try:
                source = (self.root / rel_path).read_text(encoding="utf-8-sig")
                facts_by_file[rel_path] = _extract_file_facts(
                    rel_path,
                    source,
                    domain,
                    known_modules,
                    watched_methods=self.contract.authority_capability_method_names,
                    watched_symbols=self.contract.authority_bearing_symbols,
                )
            except (OSError, SyntaxError, ValueError):
                unreadable.append(rel_path)

        facts_by_file = _resolve_symbol_imports(facts_by_file, known_modules)

        findings: List[DriftFinding] = []

        findings.extend(self._check_business_no_forbidden_imports(facts_by_file))
        findings.extend(self._check_production_modeling_no_forbidden_imports(facts_by_file))
        findings.extend(self._check_no_unauthorized_authority_construction(facts_by_file))
        findings.extend(self._check_create_job_cardinality(facts_by_file))
        findings.extend(self._check_second_authority_core_signal(facts_by_file))
        findings.extend(self._check_no_certificate_authority_edge(facts_by_file))
        findings.extend(self._check_no_transitive_certificate_authority_edge(facts_by_file))
        findings.extend(self._check_no_certificate_verdict_interpretation(facts_by_file))
        findings.extend(self._check_no_certificate_authority_bridge_module(facts_by_file))
        findings.extend(self._check_no_authority_capability_escape(facts_by_file))

        findings_sorted = tuple(
            sorted(
                findings,
                key=lambda f: (_SEVERITY_ORDER[f.severity], f.file, f.line),
            )
        )

        # Phase P3.32 (Section 16/21) : le statut global ne doit jamais
        # être gouverné par un finding PUREMENT informationnel -- celui-ci
        # reste intégralement visible dans `findings` (jamais masqué,
        # jamais supprimé), mais ne représente par construction AUCUNE
        # violation de règle (cf. code CREATE_JOB_NAMESAKE_UNRELATED,
        # `violated_rule="none -- informational only"`). Un finding
        # CRITICAL/HIGH/MEDIUM/LOW, à l'inverse, gouverne TOUJOURS le
        # statut -- exactement comme avant cette phase, aucune règle
        # réelle n'est affaiblie par ce changement (Section 7 : "ne pas
        # affaiblir les règles simplement pour faire passer la suite").
        actionable_findings = tuple(
            f for f in findings_sorted if f.severity != Severity.INFORMATIONAL
        )

        if unreadable:
            status = DriftStatus.ANALYSIS_INCOMPLETE
        elif actionable_findings:
            status = DriftStatus.DRIFT_DETECTED
        else:
            status = DriftStatus.NO_DRIFT

        return DriftReport(
            status=status,
            findings=findings_sorted,
            files_analyzed=tuple(sorted(facts_by_file.keys())),
            files_unreadable=tuple(sorted(unreadable)),
        )

    # ------------------------------------------------------------------
    # A. BUSINESS AGENT -> HIGGSFIELD / P2 (import direct)
    # ------------------------------------------------------------------

    def _check_business_no_forbidden_imports(
        self, facts_by_file: Dict[str, _FileFacts]
    ) -> List[DriftFinding]:
        findings: List[DriftFinding] = []

        for rel_path, facts in facts_by_file.items():
            if facts.domain != Domain.BUSINESS_EDITORIAL:
                continue

            hits = _has_import_with_prefix(
                facts, sorted(self.contract.forbidden_import_prefixes_for_business_editorial)
            )
            for module, prefix, line in hits:
                findings.append(
                    DriftFinding(
                        code="BUS_FORBIDDEN_IMPORT",
                        severity=Severity.CRITICAL,
                        file=rel_path,
                        line=line,
                        component=rel_path,
                        violated_rule=(
                            "Domain A (Business/Editorial) must never import "
                            f"'{prefix}' (Higgsfield/P2 execution internals)."
                        ),
                        evidence=f"import of '{module}' found in {rel_path}",
                        explanation=(
                            "A Business/Editorial agent importing a Higgsfield "
                            "or P2 execution module could reach real generation "
                            "authority directly, circumventing the canonical bridge "
                            "(P3.23)."
                        ),
                    )
                )

        return findings

    # ------------------------------------------------------------------
    # B/C. PRODUCTION-MODELING AGENT -> P2 execution internals (import)
    # ------------------------------------------------------------------

    def _check_production_modeling_no_forbidden_imports(
        self, facts_by_file: Dict[str, _FileFacts]
    ) -> List[DriftFinding]:
        findings: List[DriftFinding] = []

        for rel_path, facts in facts_by_file.items():
            if facts.domain not in (Domain.PRODUCTION_MODELING, Domain.BRIDGE):
                continue

            hits = _has_import_with_prefix(
                facts,
                sorted(self.contract.forbidden_import_prefixes_for_production_modeling),
            )
            for module, prefix, line in hits:
                findings.append(
                    DriftFinding(
                        code="PM_FORBIDDEN_IMPORT",
                        severity=Severity.CRITICAL,
                        file=rel_path,
                        line=line,
                        component=rel_path,
                        violated_rule=(
                            "Domain B (Production/Modeling) and the Bridge must "
                            f"never import '{prefix}' as a MODULE (execution "
                            "mechanism) -- type-only imports for isinstance "
                            "checks are the only sanctioned pattern, and those "
                            "never trigger this check (see forbidden-call-based "
                            "checks below for the real enforcement)."
                        ),
                        evidence=f"import of '{module}' found in {rel_path}",
                        explanation=(
                            "A Production/Modeling component importing a P2 "
                            "execution module directly could circumvent the single "
                            "canonical bridge (P3.23) into the P2 Authority Core."
                        ),
                    )
                )

        return findings

    # ------------------------------------------------------------------
    # E/F/H. Appels de construction d'objets porteurs d'autorité, hors
    # des fichiers explicitement autorisés par le contrat.
    # ------------------------------------------------------------------

    def _check_no_unauthorized_authority_construction(
        self, facts_by_file: Dict[str, _FileFacts]
    ) -> List[DriftFinding]:
        findings: List[DriftFinding] = []

        for rel_path, facts in facts_by_file.items():
            if facts.domain in (Domain.TEST, Domain.SCRIPT):
                continue

            for symbol, line in facts.calls:
                if symbol not in self.contract.authority_bearing_symbols:
                    continue

                allowed_files = self.contract.constructor_allowlist.get(symbol, frozenset())
                if rel_path in allowed_files:
                    continue

                # Toute construction d'un symbole porteur d'autorité hors de
                # son allowlist est CRITICAL, sans exception : chacun de ces
                # symboles représente une pièce du noyau d'autorité P2 --
                # un contournement de l'un quelconque d'entre eux a la même
                # gravité potentielle (jamais sous-évalué "par type").
                severity = Severity.CRITICAL

                code = (
                    "AUTOMATIC_HUMAN_AUTHORIZATION"
                    if symbol == "RealGenerationAuthorization"
                    else "AUTOMATIC_ACTIVATION_CONSTRUCTION"
                    if symbol
                    in (
                        "RequestScopedActivationContract",
                        "ControlledRealProviderActivationContract",
                        "RequestScopedActivationService",
                        "ControlledRealProviderActivationService",
                    )
                    else "AUTHORITY_CONSTRUCTOR_OUTSIDE_ALLOWLIST"
                )

                findings.append(
                    DriftFinding(
                        code=code,
                        severity=severity,
                        file=rel_path,
                        line=line,
                        component=rel_path,
                        violated_rule=(
                            f"'{symbol}(' may only be constructed in "
                            f"{sorted(allowed_files) or '[no file -- never in production]'}."
                        ),
                        evidence=f"call to '{symbol}(' found at {rel_path}:{line}",
                        explanation=(
                            f"'{symbol}' is an authority-bearing symbol of the "
                            "P2 Production Authority Core. A construction call "
                            "outside its allowlisted file(s) is either an "
                            "automatic-authorization/activation path or a "
                            "second, parallel authority instance -- both "
                            "forbidden by the canonical architecture contract."
                        ),
                    )
                )

        return findings

    # ------------------------------------------------------------------
    # D/H. Cardinalité du call-site de production create_job()
    # ------------------------------------------------------------------

    def _check_create_job_cardinality(
        self, facts_by_file: Dict[str, _FileFacts]
    ) -> List[DriftFinding]:
        findings: List[DriftFinding] = []
        relevant_call_sites: List[Tuple[str, int]] = []

        for rel_path, facts in facts_by_file.items():
            if facts.domain in (Domain.TEST, Domain.SCRIPT):
                continue

            # P3.77-R1 (G2, option B): `.run(... "create" ...)` is the CLI
            # verb `HiggsfieldClient.create_job()` wraps -- always a
            # creation call-site (the literal verb IS the Higgsfield link,
            # no import required), except in the file defining that verb.
            if rel_path != self.contract.cli_create_verb_owner_file:
                relevant_call_sites.extend(
                    (rel_path, line)
                    for line, literals in facts.run_calls
                    if self.contract.cli_create_verb in literals
                )

            has_create_job_calls = any(name == "create_job" for name, _ in facts.calls)
            if not has_create_job_calls:
                continue

            is_relevant = (
                facts.domain == Domain.P2_AUTHORITY_CORE
                or bool(
                    _has_import_with_prefix(
                        _with_reexports(facts), sorted(self.contract.create_job_relevance_import_prefixes)
                    )
                )
                # P3.101 (P3.81): the client reached through the import
                # closure -- `AIDirector().higgsfield.create_job(...)`,
                # `gate.provider.client.create_job(...)`, helper chains.
                or self._import_closure_reaches_create_job_relevance(rel_path, facts_by_file) is not None
            )

            if not is_relevant:
                # Homonyme sans lien Higgsfield démontré (ex. JobMonitor.
                # create_job) -- signalé séparément, jamais silencieusement
                # ignoré, mais jamais compté dans la cardinalité réelle.
                for _, line in (c for c in facts.calls if c[0] == "create_job"):
                    findings.append(
                        DriftFinding(
                            code="CREATE_JOB_NAMESAKE_UNRELATED",
                            severity=Severity.INFORMATIONAL,
                            file=rel_path,
                            line=line,
                            component=rel_path,
                            violated_rule="none -- informational only",
                            evidence=f"call to 'create_job(' found at {rel_path}:{line}",
                            explanation=(
                                f"'{rel_path}' calls a method named 'create_job' "
                                "but neither it nor its import closure reaches "
                                "integrations.higgsfield, and it is not part of "
                                "the P2 Authority Core -- "
                                "almost certainly an unrelated same-named method "
                                "(known case: agents/job_monitor.py, a dead-code "
                                "V1 module). Not counted toward production "
                                "create_job cardinality."
                            ),
                        )
                    )
                continue

            for name, line in facts.calls:
                if name == "create_job":
                    relevant_call_sites.append((rel_path, line))

        count = len(relevant_call_sites)
        expected = self.contract.expected_create_job_production_call_site_count
        expected_file = self.contract.expected_create_job_production_file

        if count != expected:
            for rel_path, line in relevant_call_sites:
                findings.append(
                    DriftFinding(
                        code="CREATE_JOB_CARDINALITY_VIOLATION",
                        severity=Severity.CRITICAL,
                        file=rel_path,
                        line=line,
                        component=rel_path,
                        violated_rule=(
                            f"Exactly {expected} production create_job() "
                            f"call-site is expected (in '{expected_file}'); "
                            f"found {count}."
                        ),
                        evidence=f"create_job( call at {rel_path}:{line}",
                        explanation=(
                            "A change in the number of Higgsfield-relevant "
                            "create_job() call-sites is a direct sign of a "
                            "second production execution path."
                        ),
                    )
                )
        elif relevant_call_sites and relevant_call_sites[0][0] != expected_file:
            rel_path, line = relevant_call_sites[0]
            findings.append(
                DriftFinding(
                    code="CREATE_JOB_CALLSITE_RELOCATED",
                    severity=Severity.CRITICAL,
                    file=rel_path,
                    line=line,
                    component=rel_path,
                    violated_rule=f"The single production create_job() call-site must be in '{expected_file}'.",
                    evidence=f"create_job( call at {rel_path}:{line}",
                    explanation=(
                        "The sole production call-site moved outside "
                        "GenerationJobService -- the critical-section lock "
                        "and fresh Gate re-evaluation guarantees only hold "
                        "inside that exact method."
                    ),
                )
            )

        return findings

    # ------------------------------------------------------------------
    # P3.101 (restores P3.81) -- create_job relevance through the import
    # closure. The direct check above misses a client reached through the
    # object graph: `AIDirector().higgsfield` (director.py imports the
    # client), `gate.provider.client` (the Gate imports the Provider), and
    # helper/re-export chains leading there. Walks the facts already
    # extracted -- `module_imports`, `import_modules` and the re-export
    # provenance resolved by `_resolve_symbol_imports` -- never a new parse.
    #
    # Edge kinds (compatible with P3.77-R1 G3): a MODULE import exposes the
    # whole module, so its closure is followed; a SYMBOL import
    # (`from M import Name`) is followed only when M -- or the module the
    # symbol is re-exported from -- is an authority module (P2 Authority
    # Core or entry point), whose objects carry the provider/client. An
    # unrelated name taken from a helper that merely imports Higgsfield
    # stays a namesake. Test files are never walked through. Documented
    # limit, as in P3.81: a duck-typed call in a file with no such import
    # (`def go(c): c.create_job(...)`) remains CREATE_JOB_NAMESAKE_UNRELATED.
    # `_reaches_target_transitively` is not reused: it looks for target
    # FILES and skips the first hop for the certificate edge rules.
    # ------------------------------------------------------------------

    def _import_closure_reaches_create_job_relevance(
        self, rel_path: str, facts_by_file: Dict[str, _FileFacts]
    ) -> Optional[str]:
        """Relative path of the first module reached through `rel_path`'s
        import closure that itself imports a create_job relevance prefix,
        or `None`. Breadth-first, cycle-safe (`visited`), first-party only."""

        prefixes = sorted(self.contract.create_job_relevance_import_prefixes)
        authority_files = self.contract.p2_authority_core_files | self.contract.entry_point_files

        def module_file(module: str) -> Optional[str]:
            base = module.replace(".", "/")
            for candidate in (base + ".py", base + "/__init__.py"):
                if candidate in facts_by_file:
                    return candidate
            return None

        def next_modules(facts: _FileFacts) -> List[str]:
            module_edges = {m for m, _line in facts.module_imports}
            symbol_edges = {m for m, _line in facts.import_modules + facts.reexport_modules} - module_edges
            return sorted(module_edges) + sorted(m for m in symbol_edges if module_file(m) in authority_files)

        visited = {rel_path}
        frontier = next_modules(facts_by_file[rel_path])
        while frontier:
            path = module_file(frontier.pop(0))
            if path is None or path in visited:
                continue
            visited.add(path)
            facts = facts_by_file[path]
            if facts.domain == Domain.TEST:
                continue
            if _has_import_with_prefix(_with_reexports(facts), prefixes):
                return path
            frontier.extend(next_modules(facts))
        return None

    # ------------------------------------------------------------------
    # G. Signal d'un second noyau d'autorité (heuristique, fichiers non
    # classifiés uniquement -- jamais A/B/Bridge, déjà couverts ailleurs).
    # ------------------------------------------------------------------

    def _check_second_authority_core_signal(
        self, facts_by_file: Dict[str, _FileFacts]
    ) -> List[DriftFinding]:
        findings: List[DriftFinding] = []
        signal_modules = self.contract.second_authority_core_signal_modules
        threshold = self.contract.second_authority_core_signal_threshold

        for rel_path, facts in facts_by_file.items():
            if facts.domain != Domain.UNCLASSIFIED_LEGACY:
                continue

            matched = sorted(
                {
                    module
                    for module, _line in facts.import_modules
                    if module in signal_modules
                }
            )

            if len(matched) >= threshold:
                findings.append(
                    DriftFinding(
                        code="POTENTIAL_SECOND_AUTHORITY_CORE",
                        severity=Severity.MEDIUM,
                        file=rel_path,
                        line=1,
                        component=rel_path,
                        violated_rule=(
                            "An unclassified file importing multiple P2 "
                            "execution-core modules is a heuristic signal of "
                            "a forming second authority core -- requires human "
                            "review, never auto-resolved."
                        ),
                        evidence=f"imports {matched} in unclassified file {rel_path}",
                        explanation=(
                            "This file is not part of any recognized canonical "
                            "domain, yet imports "
                            f"{len(matched)} P2 execution-core modules "
                            f"({', '.join(matched)}). This may be entirely "
                            "benign (e.g. a new, not-yet-catalogued P2-domain "
                            "file) but must be reviewed and, if legitimate, "
                            "added to the canonical contract explicitly rather "
                            "than left unclassified."
                        ),
                    )
                )

        return findings

    # ------------------------------------------------------------------
    # H/I/J. Certificate subsystem <-> Authority surface edge (Phase P3.63)
    #
    # P3.62 demonstrated, by manual whole-repository AST audit, that ZERO
    # production consumer of any certificate_*.py /
    # production_activation_readiness_certificate.py symbol exists. This
    # check makes that property permanent: it is re-verified on every
    # `analyze()` instead of depending on a one-time manual audit being
    # re-run by hand in a future phase.
    # ------------------------------------------------------------------

    def _check_no_certificate_authority_edge(
        self, facts_by_file: Dict[str, _FileFacts]
    ) -> List[DriftFinding]:
        findings: List[DriftFinding] = []

        # Direction 1: nothing on the authority surface (P2 Authority
        # Core + Production Modeling + entry point) may import ANY
        # certificate-subsystem module -- a certificate must never flow
        # INTO an approval/authorization/activation/execution decision.
        for rel_path, facts in facts_by_file.items():
            if rel_path not in self.contract.certificate_guardrail_authority_surface_files:
                continue

            hits = _has_import_with_prefix(
                facts, sorted(self.contract.certificate_subsystem_import_prefixes)
            )
            for module, prefix, line in hits:
                findings.append(
                    DriftFinding(
                        code="CERTIFICATE_TO_AUTHORITY_IMPORT",
                        severity=Severity.CRITICAL,
                        file=rel_path,
                        line=line,
                        component=rel_path,
                        violated_rule=(
                            "No file on the P2 Authority Core / Production "
                            "Modeling / entry-point surface may import a "
                            f"certificate subsystem module ('{prefix}')."
                        ),
                        evidence=f"import of '{module}' found in {rel_path}",
                        explanation=(
                            "A certificate is proof-of-preflight information, "
                            "never authorization/activation/execution "
                            "permission (Phases P3.54-P3.62). An authority-"
                            "surface file importing a certificate module is "
                            "the first step toward treating its verdict as "
                            "authority -- forbidden regardless of what the "
                            "import is actually used for."
                        ),
                    )
                )

        # Direction 2: the certificate subsystem's purely informational
        # layer (verification/integrity/lifecycle bookkeeping) must never
        # import, or call into, the authority surface. The P3.54 Issuer
        # itself is excluded from this direction -- its composition of
        # ActivationReadinessEvaluator is pre-existing, sanctioned
        # architecture already governed by PROTECTED_P2_FILES.
        for rel_path, facts in facts_by_file.items():
            if rel_path not in self.contract.certificate_informational_layer_files:
                continue

            # P3.76-R1: including symbols laundered through a re-export
            # (`from <issuer> import GenerationRequest`).
            import_hits = _has_import_with_prefix(
                _with_reexports(facts), sorted(self.contract.certificate_outbound_forbidden_import_prefixes)
            )
            for module, prefix, line in import_hits:
                findings.append(
                    DriftFinding(
                        code="CERTIFICATE_OUTBOUND_AUTHORITY_IMPORT",
                        severity=Severity.CRITICAL,
                        file=rel_path,
                        line=line,
                        component=rel_path,
                        violated_rule=(
                            "The certificate subsystem's informational layer "
                            f"must never import an authority-surface module ('{prefix}')."
                        ),
                        evidence=f"import of '{module}' found in {rel_path}",
                        explanation=(
                            "This module exists to verify/track an "
                            "already-issued certificate as pure information -- "
                            "it has no legitimate reason to reach into the P2 "
                            "execution boundary or the production activation/"
                            "human-authorization chain."
                        ),
                    )
                )

            for name, line in facts.calls:
                if name in self.contract.certificate_forbidden_authority_call_names:
                    findings.append(
                        DriftFinding(
                            code="CERTIFICATE_OUTBOUND_AUTHORITY_CALL",
                            severity=Severity.CRITICAL,
                            file=rel_path,
                            line=line,
                            component=rel_path,
                            violated_rule=(
                                "The certificate subsystem's informational "
                                f"layer must never call '{name}('."
                            ),
                            evidence=f"call to '{name}(' found at {rel_path}:{line}",
                            explanation=(
                                "A call named like an execution/authorization/"
                                "activation primitive from inside the "
                                "certificate subsystem's informational layer "
                                "is exactly the escalation path P3.62/P3.63 "
                                "audit and guard against."
                            ),
                        )
                    )

        return findings

    # ------------------------------------------------------------------
    # Certificate subsystem <-> Authority surface, TRANSITIVE edge
    # (Phase P3.65, generalizing P3.64's one-hop-only check).
    #
    # `_check_no_certificate_authority_edge` above only sees a DIRECT
    # (depth-1) import in either direction. P3.64 closed exactly ONE
    # intermediate hop. P3.65's audit asked whether a SECOND intermediate
    # hop (helper1 -> helper2 -> certificate) still evades detection --
    # confirmed empirically that it did, before this method existed.
    #
    # This performs a bounded breadth-first search over the import graph
    # `facts_by_file` ALREADY built by `analyze()` for every other check
    # -- no new parsing pass, no new infrastructure, no runtime
    # instrumentation. It is genuinely transitive (arbitrary depth, not a
    # fixed hop count), and it is provably terminating and deterministic:
    # each traversal carries its own `visited` set, so no file is ever
    # expanded twice, bounding the walk to at most `len(facts_by_file)`
    # steps regardless of cycles in the underlying import graph (Section
    # 7, P3.65 mission -- cycle-safe by construction, not by assumption
    # that the repository happens to be acyclic).
    #
    # Both directions of the P3.63 contract are generalized identically:
    #   Direction 1 (transitive): an authority-surface file reaches a
    #     certificate-subsystem file through a chain of >=1 intermediate,
    #     otherwise-unrelated first-party modules.
    #   Direction 2 (transitive): a certificate informational-layer file
    #     reaches an authority-surface file the same way.
    # Depth-1 (direct) edges are deliberately EXCLUDED here -- they
    # remain the sole responsibility of `_check_no_certificate_authority_
    # edge` above, so the two checks never double-report the same edge.
    #
    # SCOPE, honestly stated (Section 13/17, P3.65 mission): this proves
    # SOUNDNESS (every edge reported is a real import chain that exists
    # in the AST) and COMPLETENESS bounded to STATIC, FIRST-PARTY,
    # RESOLVABLE import edges only -- exactly the same boundary every
    # other check in this detector already has. It says nothing about
    # dynamic imports, reflection, or structural typing (P3.64 Sections
    # 9/10/N), which remain the same honestly-documented, out-of-scope
    # limitation as before -- this method does not change that boundary,
    # only how much of the STATIC graph is actually walked.
    # ------------------------------------------------------------------

    def _reaches_target_transitively(
        self,
        entry_module: str,
        exclude_domains: Tuple[Domain, ...],
        excluded_first_hop_targets: FrozenSet[str],
        target_files: FrozenSet[str],
        facts_by_file: Dict[str, _FileFacts],
    ) -> Optional[str]:
        """
        Breadth-first search, starting from `entry_module` (a single
        top-level import of the file under inspection), over first-party
        modules resolvable in `facts_by_file`. Returns the relative path
        of the first `target_files` member reached, or `None`. A `visited`
        set local to this single call makes it cycle-safe and terminating
        without depending on the repository being acyclic.
        """

        entry_path = entry_module.replace(".", "/") + ".py"
        if entry_path in target_files or entry_path in excluded_first_hop_targets:
            return None  # depth-1 -- handled by the direct-edge check, never double-reported here

        entry_facts = facts_by_file.get(entry_path)
        if entry_facts is None or entry_facts.domain in exclude_domains:
            return None

        visited = {entry_path}
        frontier: List[str] = [m for m, _line in entry_facts.import_modules]

        while frontier:
            module = frontier.pop(0)
            candidate_path = module.replace(".", "/") + ".py"
            if candidate_path in visited:
                continue
            visited.add(candidate_path)

            if candidate_path in target_files:
                return candidate_path

            candidate_facts = facts_by_file.get(candidate_path)
            if candidate_facts is None:
                continue
            if candidate_path in excluded_first_hop_targets:
                continue
            if candidate_facts.domain in exclude_domains:
                continue

            frontier.extend(m for m, _line in candidate_facts.import_modules)

        return None

    # ------------------------------------------------------------------
    # Certificate verdict -> Authority INTERPRETATION (Phase P3.70).
    #
    # The two edge checks around this one are import-based: they miss an
    # authority-surface file that interprets a certificate verdict on a
    # duck-typed object it never imports (`if certificate.is_ready():
    # return APPROVED`), and a decision-core file that imports the
    # readiness report a certificate embeds and treats `READY` as
    # permission. P3.70 confirmed both forms evaded every existing check
    # and permanent test. Same facts, no new parsing pass.
    # ------------------------------------------------------------------

    def _check_no_certificate_verdict_interpretation(
        self, facts_by_file: Dict[str, _FileFacts]
    ) -> List[DriftFinding]:
        findings: List[DriftFinding] = []

        for rel_path, facts in facts_by_file.items():
            if rel_path not in self.contract.certificate_guardrail_authority_surface_files:
                continue
            if rel_path in self.contract.certificate_subsystem_files:
                continue  # the subsystem defines this vocabulary; never "interpreting" it

            for name, line in facts.calls:
                if name not in self.contract.certificate_verdict_call_names:
                    continue
                findings.append(
                    DriftFinding(
                        code="CERTIFICATE_VERDICT_INTERPRETED_BY_AUTHORITY",
                        severity=Severity.CRITICAL,
                        file=rel_path,
                        line=line,
                        component=rel_path,
                        violated_rule=(
                            "No file on the authority surface may call certificate-"
                            f"verdict vocabulary ('{name}(')."
                        ),
                        evidence=f"call to '{name}(' found at {rel_path}:{line}",
                        explanation=(
                            "A certificate verdict (READY/CURRENT/VALID/INTEGRITY_VALID) "
                            "is information, never authorization. Reading it from an "
                            "authority-surface file -- even on a duck-typed object with "
                            "no certificate import -- is the first step toward treating "
                            "it as permission."
                        ),
                    )
                )

            # P3.71: the same vocabulary read WITHOUT a call evaded the
            # call-based branch above (`if certificate.is_ready:`).
            for name, line in facts.attribute_loads:
                if name not in self.contract.certificate_verdict_attribute_names:
                    continue
                findings.append(
                    DriftFinding(
                        code="CERTIFICATE_VERDICT_READ_BY_AUTHORITY",
                        severity=Severity.CRITICAL,
                        file=rel_path,
                        line=line,
                        component=rel_path,
                        violated_rule=(
                            "No file on the authority surface may read certificate-"
                            f"verdict vocabulary ('.{name}')."
                        ),
                        evidence=f"attribute read '.{name}' found at {rel_path}:{line}",
                        explanation=(
                            "Same rule as CERTIFICATE_VERDICT_INTERPRETED_BY_AUTHORITY, "
                            "for a plain attribute read -- `if certificate.is_ready:` is "
                            "both a certificate verdict consumed by authority code and "
                            "always true."
                        ),
                    )
                )

        for rel_path, facts in facts_by_file.items():
            if rel_path not in self.contract.readiness_verdict_forbidden_consumer_files:
                continue

            hits = _has_import_with_prefix(
                facts, sorted(self.contract.readiness_verdict_module_prefixes)
            )
            for module, prefix, line in hits:
                findings.append(
                    DriftFinding(
                        code="READINESS_VERDICT_CONSUMED_BY_EXECUTION_CORE",
                        severity=Severity.CRITICAL,
                        file=rel_path,
                        line=line,
                        component=rel_path,
                        violated_rule=(
                            "Files that make or enforce the approval/activation/execution "
                            f"decision must never import a readiness-verdict module ('{prefix}')."
                        ),
                        evidence=f"import of '{module}' found in {rel_path}",
                        explanation=(
                            "ActivationReadinessReport -- the report every certificate "
                            "embeds -- is an observation (Phase P2.24). The decision core "
                            "must reach its verdict from its own fresh checks, never from "
                            "a readiness READY."
                        ),
                    )
                )

        return findings

    def _check_no_transitive_certificate_authority_edge(
        self, facts_by_file: Dict[str, _FileFacts]
    ) -> List[DriftFinding]:
        findings: List[DriftFinding] = []
        # P3.76-R1: only TEST is exempt. No script is production-reachable
        # (none is imported by agents/, integrations/ or director.py), but a
        # script has no legitimate reason to join certificate and authority
        # either -- its SCRIPT exemption covers authority CONSTRUCTION only.
        excluded_domains = (Domain.TEST,)

        # Direction 1 (transitive): authority-surface file -> ... -> certificate.
        for rel_path, facts in facts_by_file.items():
            if rel_path not in self.contract.certificate_guardrail_authority_surface_files:
                continue

            for entry_module, entry_line in facts.import_modules:
                reached = self._reaches_target_transitively(
                    entry_module,
                    excluded_domains,
                    self.contract.certificate_guardrail_authority_surface_files,
                    self.contract.certificate_subsystem_files,
                    facts_by_file,
                )
                if reached is None:
                    continue
                findings.append(
                    DriftFinding(
                        code="CERTIFICATE_INDIRECT_AUTHORITY_IMPORT",
                        severity=Severity.CRITICAL,
                        file=rel_path,
                        line=entry_line,
                        component=rel_path,
                        violated_rule=(
                            "No file on the authority surface may reach a certificate "
                            "subsystem module through any chain of intermediate imports."
                        ),
                        evidence=(
                            f"{rel_path}:{entry_line} imports '{entry_module}', which "
                            f"transitively reaches certificate subsystem module '{reached}'."
                        ),
                        explanation=(
                            "A chain of otherwise-unrelated helper modules that eventually "
                            "imports a certificate subsystem module, reached from an "
                            "authority-surface file, achieves the same certificate->"
                            "authority coupling the direct-edge check forbids -- laundered "
                            "through one or more intermediate files instead of one."
                        ),
                    )
                )

        # Direction 2 (transitive): certificate informational layer -> ... -> authority.
        for rel_path, facts in facts_by_file.items():
            if rel_path not in self.contract.certificate_informational_layer_files:
                continue

            for entry_module, entry_line in facts.import_modules:
                reached = self._reaches_target_transitively(
                    entry_module,
                    excluded_domains,
                    self.contract.certificate_subsystem_files,
                    self.contract.certificate_guardrail_authority_surface_files,
                    facts_by_file,
                )
                if reached is None:
                    continue
                findings.append(
                    DriftFinding(
                        code="CERTIFICATE_INDIRECT_OUTBOUND_AUTHORITY_IMPORT",
                        severity=Severity.CRITICAL,
                        file=rel_path,
                        line=entry_line,
                        component=rel_path,
                        violated_rule=(
                            "The certificate subsystem's informational layer must never "
                            "reach an authority-surface module through any chain of "
                            "intermediate imports."
                        ),
                        evidence=(
                            f"{rel_path}:{entry_line} imports '{entry_module}', which "
                            f"transitively reaches authority-surface module '{reached}'."
                        ),
                        explanation=(
                            "A chain of otherwise-unrelated helper modules that eventually "
                            "imports an authority-surface module, reached from the "
                            "certificate subsystem's informational layer, achieves the "
                            "same escalation the direct-edge check forbids -- laundered "
                            "through one or more intermediate files instead of one."
                        ),
                    )
                )

        return findings

    # ------------------------------------------------------------------
    # Certificate <-> Authority BRIDGE in an unclassified module (P3.75).
    #
    # Every edge check above is anchored on a classified file set, so a
    # NEW module outside both sets -- importing a certificate module AND
    # an authority module, e.g. `if registry.status_of(cid) ...:
    # service.generate(request)` -- joined the two sides with no finding
    # at all (P3.70 "unclassified helper", confirmed in P3.75). Same
    # facts and reachability search as above, no new parsing pass.
    # Reaching authority only THROUGH the certificate subsystem (the
    # P3.54 Issuer's sanctioned composition) is never counted -- but only
    # the Issuer's OWN vocabulary is sanctioned (the certificate, the
    # Issuer, `certificate_still_matches`). An authority symbol the Issuer
    # merely re-exports (`GenerationRequest`, `RequestScopedActivation
    # Contract`, ...) counts as reaching its defining module (P3.76-R1).
    # ------------------------------------------------------------------

    def _check_no_certificate_authority_bridge_module(
        self, facts_by_file: Dict[str, _FileFacts]
    ) -> List[DriftFinding]:
        findings: List[DriftFinding] = []
        # P3.76-R1: only TEST is exempt. No script is production-reachable
        # (none is imported by agents/, integrations/ or director.py), but a
        # script has no legitimate reason to join certificate and authority
        # either -- its SCRIPT exemption covers authority CONSTRUCTION only.
        excluded_domains = (Domain.TEST,)
        subsystem = self.contract.certificate_subsystem_files
        authority = self.contract.certificate_guardrail_authority_surface_files

        def first_reach(facts, direct_prefixes, excluded_first_hops, targets):
            for module, _prefix, line in _has_import_with_prefix(facts, sorted(direct_prefixes)):
                return module, line
            for module, line in facts.import_modules:
                reached = self._reaches_target_transitively(
                    module, excluded_domains, excluded_first_hops, targets, facts_by_file
                )
                if reached is not None:
                    return reached, line
            return None

        for rel_path, facts in facts_by_file.items():
            if facts.domain in excluded_domains or rel_path in subsystem or rel_path in authority:
                continue

            facts = _with_reexports(facts)  # P3.76-R1: the Issuer is no laundering conduit
            certificate_hit = first_reach(
                facts, self.contract.certificate_subsystem_import_prefixes, authority, subsystem
            )
            if certificate_hit is None:
                continue
            authority_hit = first_reach(
                facts, self.contract.certificate_outbound_forbidden_import_prefixes, subsystem, authority - subsystem
            )
            if authority_hit is None:
                continue

            findings.append(
                DriftFinding(
                    code="CERTIFICATE_AUTHORITY_BRIDGE_MODULE",
                    severity=Severity.CRITICAL,
                    file=rel_path,
                    line=authority_hit[1],
                    component=rel_path,
                    violated_rule=(
                        "No module outside the certificate subsystem and the authority "
                        "surface may reach both a certificate module and an authority module."
                    ),
                    evidence=(
                        f"{rel_path} reaches certificate module '{certificate_hit[0]}' "
                        f"(line {certificate_hit[1]}) and authority module "
                        f"'{authority_hit[0]}' (line {authority_hit[1]})."
                    ),
                    explanation=(
                        "Such a module can turn a certificate verdict into the trigger of an "
                        "approval/authorization/execution path -- the certificate->authority "
                        "coupling NO CERTIFICATE -> AUTHORITY EDGE forbids, hosted in a file "
                        "no classified edge check covers. Informational certificate consumers "
                        "must not import the authority surface."
                    ),
                )
            )

        return findings

    # ------------------------------------------------------------------
    # P3.78-R1 (G4-a/b/d). Capacités d'autorité hors position d'appel.
    # ------------------------------------------------------------------

    def _check_no_authority_capability_escape(
        self, facts_by_file: Dict[str, _FileFacts]
    ) -> List[DriftFinding]:
        """
        An authority method (`o.execute`, `c.run`, `g.mark_executed` ...)
        or an authority-bearing symbol (`RealGenerationAuthorization` ...)
        read as a VALUE -- stored, passed, returned, registered, wrapped
        in `partial`, subclassed -- can later be invoked where no call-site
        check ever sees it. Every first-party file is covered (P3.76-R1
        scan boundary), scripts included; only tests are exempt.

        A symbol counts only when its provenance really resolves -- through
        imports, aliases and re-exports -- to a class defined in the P2
        authority core (or to a core module the contract names but a partial
        tree lacks): a local class or parameter merely sharing the name never
        does. Not covered, by construction: reflection (`getattr`, P3.67)
        and derivation from an existing object (`dataclasses.replace`,
        `type(obj)(...)`) -- the analysed code is never typed or executed.
        """
        core = self.contract.p2_authority_core_files
        bindings_by_module = {
            path[:-3].replace("/", "."): facts.module_bindings for path, facts in facts_by_file.items()
        }
        classes_by_module = {
            path[:-3].replace("/", "."): {name for name, _ in facts.class_defs}
            for path, facts in facts_by_file.items()
        }

        def is_authority_core_symbol(dotted: str, seen: set) -> bool:
            module, _, symbol = dotted.rpartition(".")
            if not module or dotted in seen or symbol not in self.contract.authority_bearing_symbols:
                return False
            seen.add(dotted)
            path = module.replace(".", "/") + ".py"
            if module not in bindings_by_module:
                return path in core
            if symbol in classes_by_module[module]:
                return path in core
            for local, source in bindings_by_module[module]:
                if local == symbol and is_authority_core_symbol(source, seen):
                    return True
                if local == "*" and is_authority_core_symbol(f"{source[:-2]}.{symbol}", seen):
                    return True
            return False

        findings: List[DriftFinding] = []
        for rel_path, facts in facts_by_file.items():
            if facts.domain == Domain.TEST:
                continue
            for name, line in facts.method_value_refs:
                findings.append(
                    DriftFinding(
                        code="AUTHORITY_METHOD_REFERENCE_ESCAPE",
                        severity=Severity.CRITICAL,
                        file=rel_path,
                        line=line,
                        component=rel_path,
                        violated_rule=(
                            f"Authority method '.{name}' may only be called or compared "
                            "by identity (`is`), never stored, passed, returned or wrapped."
                        ),
                        evidence=f"non-call reference '.{name}' at {rel_path}:{line}",
                        explanation=(
                            "A bound authority method handed around as a value (callback, "
                            "container, registry, partial, return) can be invoked later at a "
                            "site no call-site or cardinality check sees -- e.g. "
                            "`call(client.run)` then `cb('generate', 'create')`."
                        ),
                    )
                )
            for dotted, line in facts.symbol_value_refs:
                if not is_authority_core_symbol(dotted, set()):
                    continue
                symbol = dotted.rpartition(".")[2]
                findings.append(
                    DriftFinding(
                        code="AUTHORITY_SYMBOL_AS_VALUE",
                        severity=Severity.CRITICAL,
                        file=rel_path,
                        line=line,
                        component=rel_path,
                        violated_rule=(
                            f"Authority-bearing symbol '{symbol}' may only be called, "
                            "isinstance/issubclass-checked, annotated or compared with `is`."
                        ),
                        evidence=f"'{dotted}' used as a value at {rel_path}:{line}",
                        explanation=(
                            "An authority class stored, passed, registered, wrapped in "
                            "`partial` or subclassed can be constructed later under another "
                            "name, out of reach of the construction allowlist."
                        ),
                    )
                )
        return findings
