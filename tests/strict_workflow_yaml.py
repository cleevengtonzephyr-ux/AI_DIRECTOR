"""
AI DIRECTOR — Analyseur STRICT du sous-ensemble YAML des workflows du dépôt (tests)

Ce n'est PAS un analyseur YAML général ni complet. Il ne reconnaît que les
constructions effectivement employées dans `.github/workflows/*.yml`, et
lève `UnsupportedWorkflowYamlError` dès qu'il rencontre autre chose, au
lieu de deviner. Sans dépendance, sans réseau.

Pris en charge :
- mappings en bloc, indentés par des espaces, clés simples
  (`[A-Za-z0-9_][A-Za-z0-9_.-]*`) ; clé en double refusée ;
- séquences en bloc (`- valeur`, `- clé: valeur` suivi d'un mapping),
  plus indentées que leur clé parente ;
- scalaires simples sur une ligne, scalaires entre guillemets doubles sans
  échappement, bloc littéral `|` ;
- `{}` (mapping vide) et séquence en ligne de scalaires simples (`[main]`) ;
- valeur vide (`clé:` seule) -> None ;
- commentaires de ligne entière et commentaires de fin (` #`) hors bloc
  littéral et hors guillemets.

Aucune résolution de type : tout scalaire est rendu comme `str`
(`false` reste "false", `on` reste "on").

Refusé explicitement, entre autres : tabulation, retour chariot isolé,
marqueurs de document, directives, ancres, alias, étiquettes, clés
complexes, clés de fusion, scalaires entre apostrophes, blocs repliés `>`
ou indicateurs `|-`/`|+`, mappings en ligne non vides, flux imbriqués,
échappements, scalaires sur plusieurs lignes, `: ` dans un scalaire simple.
"""

import re
from typing import Any, Dict, List, Optional

_KEY_LINE = re.compile(r"([A-Za-z0-9_][A-Za-z0-9_.-]*):(?: (.*))?")
_FLOW_ITEM = re.compile(r"[A-Za-z0-9_./*-]+")
_FORBIDDEN_FIRST = set("'&*!%@`>?|,]}#")


class UnsupportedWorkflowYamlError(ValueError):
    """Construction absente du sous-ensemble pris en charge, ou YAML invalide."""

    def __init__(self, line_number: int, message: str):
        super().__init__(f"line {line_number}: {message}")
        self.line_number = line_number


def parse_workflow_yaml(text: str) -> Dict[str, Any]:
    return _Parser(text).parse()


class _Parser:
    def __init__(self, text: str):
        if not isinstance(text, str):
            raise TypeError("text must be a str")
        if text.startswith("﻿"):
            raise UnsupportedWorkflowYamlError(1, "byte order mark is not supported")
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        for number, line in enumerate(lines, start=1):
            if "\t" in line:
                raise UnsupportedWorkflowYamlError(number, "tab character is not supported")
            if "\r" in line:
                raise UnsupportedWorkflowYamlError(number, "carriage return is not supported")
        self.lines = lines
        self.i = 0

    # -- lignes -------------------------------------------------------

    def _error(self, message: str, index: Optional[int] = None) -> UnsupportedWorkflowYamlError:
        return UnsupportedWorkflowYamlError((self.i if index is None else index) + 1, message)

    @staticmethod
    def _indent(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def _skip_ignorable(self) -> None:
        while self.i < len(self.lines):
            stripped = self.lines[self.i].strip()
            if stripped and not stripped.startswith("#"):
                return
            self.i += 1

    def _at_end(self) -> bool:
        self._skip_ignorable()
        return self.i >= len(self.lines)

    # -- structure ----------------------------------------------------

    def parse(self) -> Dict[str, Any]:
        if self._at_end():
            raise self._error("document is empty")
        if self._indent(self.lines[self.i]) != 0:
            raise self._error("document must start at column 0")
        root = self._block(0)
        if not self._at_end():
            raise self._error("unexpected content after the document")
        if not isinstance(root, dict):
            raise UnsupportedWorkflowYamlError(1, "document root must be a mapping")
        return root

    def _block(self, indent: int) -> Any:
        content = self.lines[self.i][indent:]
        if content == "-" or content.startswith("- "):
            return self._sequence(indent)
        return self._mapping(indent)

    def _mapping(self, indent: int) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        while not self._at_end():
            line = self.lines[self.i]
            current = self._indent(line)
            if current < indent:
                break
            if current > indent:
                raise self._error("unexpected indentation (multi-line scalars are not supported)")
            content = line[indent:]
            if content == "-" or content.startswith("- "):
                raise self._error("sequence item where a mapping key was expected")
            match = _KEY_LINE.fullmatch(content)
            if match is None:
                raise self._error(f"unsupported construct: {content[:40]!r}")
            key, raw = match.group(1), (match.group(2) or "").strip()
            if key in result:
                raise self._error(f"duplicate key {key!r}")
            key_index = self.i
            self.i += 1
            if raw == "" or raw.startswith("#"):
                result[key] = self._nested_or_none(indent, key_index)
            elif raw == "|" or (raw.startswith("| ") and raw[1:].strip().startswith("#")):
                result[key] = self._literal(indent, key_index)
            else:
                result[key] = self._scalar(raw, key_index)
        return result

    def _nested_or_none(self, indent: int, key_index: int) -> Any:
        if self._at_end():
            return None
        current = self._indent(self.lines[self.i])
        if current > indent:
            return self._block(current)
        content = self.lines[self.i][current:]
        if current == indent and (content == "-" or content.startswith("- ")):
            raise self._error("sequence at the same indentation as its key is not supported", key_index)
        return None

    def _sequence(self, indent: int) -> List[Any]:
        items: List[Any] = []
        while not self._at_end():
            line = self.lines[self.i]
            current = self._indent(line)
            if current < indent:
                break
            if current > indent:
                raise self._error("unexpected indentation in a sequence")
            content = line[indent:]
            if content == "-":
                raise self._error("empty or nested sequence item is not supported")
            if not content.startswith("- "):
                raise self._error("mapping key where a sequence item was expected")
            rest = content[2:]
            if rest.strip() == "":
                raise self._error("empty sequence item is not supported")
            if rest.startswith(" ") or rest.startswith("-"):
                raise self._error("irregular or nested sequence item is not supported")
            if _KEY_LINE.fullmatch(rest):
                # « - clé: valeur » : mapping dont la première clé est sur la ligne du tiret.
                self.lines[self.i] = " " * (indent + 2) + rest
                items.append(self._mapping(indent + 2))
            else:
                items.append(self._scalar(rest, self.i))
                self.i += 1
        return items

    def _literal(self, indent: int, key_index: int) -> str:
        collected: List[str] = []
        block_indent: Optional[int] = None
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if line.strip() == "":
                collected.append("")
                self.i += 1
                continue
            current = self._indent(line)
            if current <= indent:
                break
            if block_indent is None:
                block_indent = current
            elif current < block_indent:
                raise self._error("literal block line is less indented than the block")
            collected.append(line[block_indent:])
            self.i += 1
        if block_indent is None:
            raise self._error("empty literal block is not supported", key_index)
        while collected and collected[-1] == "":
            collected.pop()
        return "\n".join(collected) + "\n"

    # -- scalaires ----------------------------------------------------

    def _scalar(self, raw: str, index: int) -> Any:
        if raw.startswith('"'):
            end = raw.find('"', 1)
            if end == -1:
                raise self._error("unterminated double-quoted scalar", index)
            value, remainder = raw[1:end], raw[end + 1:]
            if "\\" in value:
                raise self._error("escape sequences are not supported", index)
            if remainder and not remainder.startswith(" #"):
                raise self._error("unexpected text after a double-quoted scalar", index)
            return value
        plain = raw.split(" #", 1)[0].rstrip()
        if plain == "{}":
            return {}
        if plain.startswith("{"):
            raise self._error("non-empty flow mappings are not supported", index)
        if plain.startswith("["):
            if not plain.endswith("]"):
                raise self._error("flow sequence must close on the same line", index)
            inner = plain[1:-1].strip()
            items = [item.strip() for item in inner.split(",")] if inner else []
            for item in items:
                if not _FLOW_ITEM.fullmatch(item):
                    raise self._error(f"unsupported flow sequence item {item!r}", index)
            return items
        if plain[0] in _FORBIDDEN_FIRST or plain.startswith("- ") or plain in ("-", "---", "..."):
            raise self._error(f"unsupported scalar {plain[:40]!r}", index)
        if ": " in plain or plain.endswith(":"):
            raise self._error("': ' inside a plain scalar is not supported", index)
        return plain
