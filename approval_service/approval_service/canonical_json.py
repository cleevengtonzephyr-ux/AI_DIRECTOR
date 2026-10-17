"""Deterministic JSON primitives for approval statements.

This module intentionally implements only the format fixed by G1:
UTF-8 JSON with lexicographically sorted object keys. It does not define
the approval-statement schema, verify credentials, access the network,
or make approval decisions.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def _validate_json_value(value: Any, path: str = "$") -> None:
    """Reject values outside the deliberately narrow canonical JSON subset."""

    if value is None or type(value) in (str, int, bool):
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError(f"JSON object key at {path} must be a string")
            _validate_json_value(item, f"{path}.{key}")
        return
    raise ValueError(
        f"Unsupported canonical JSON value at {path}: {type(value).__name__}"
    )


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Serialize a JSON object deterministically as UTF-8 bytes.

    Floats and custom Python objects are refused so multiple runtimes cannot
    silently encode the same statement differently. Callers must represent
    exact numeric values as integers or strings according to their schema.
    """

    if type(value) is not dict:
        raise ValueError("Canonical JSON top-level value must be a dict")
    _validate_json_value(value)
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return serialized.encode("utf-8")
    except (UnicodeEncodeError, RecursionError) as error:
        raise ValueError("Value cannot be represented as canonical UTF-8 JSON") from error


def canonical_json_sha256(value: Mapping[str, Any]) -> str:
    """Return the lowercase SHA-256 digest of ``canonical_json_bytes(value)``."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()

