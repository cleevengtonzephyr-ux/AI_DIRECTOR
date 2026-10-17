"""Pure local tests for the first mock-only Phase G2 primitive."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPROVAL_SERVICE_ROOT = PROJECT_ROOT / "approval_service"
if str(APPROVAL_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(APPROVAL_SERVICE_ROOT))

from approval_service.canonical_json import canonical_json_bytes, canonical_json_sha256


class CanonicalJsonTests(unittest.TestCase):
    def test_object_key_order_does_not_change_bytes_or_digest(self):
        first = {"z": 3, "nested": {"b": True, "a": None}, "a": "value"}
        second = {"a": "value", "nested": {"a": None, "b": True}, "z": 3}

        self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))
        self.assertEqual(canonical_json_sha256(first), canonical_json_sha256(second))

    def test_uses_compact_utf8_json(self):
        self.assertEqual(canonical_json_bytes({"é": "vidéo", "n": 1}), '{"n":1,"é":"vidéo"}'.encode("utf-8"))

    def test_does_not_mutate_input(self):
        value = {"items": [1, {"name": "fixture"}]}
        before = {"items": [1, {"name": "fixture"}]}

        canonical_json_bytes(value)

        self.assertEqual(value, before)

    def test_rejects_floats_including_non_finite_values(self):
        for value in (1.5, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_json_bytes({"amount": value})

    def test_rejects_non_string_keys_and_non_json_python_values(self):
        invalid_values = (
            {1: "not a string key"},
            {"value": object()},
            {"value": (1, 2)},
        )
        for value in invalid_values:
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                canonical_json_bytes(value)

    def test_rejects_non_object_top_level_values(self):
        for value in ([], "text", 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_json_bytes(value)  # type: ignore[arg-type]

    def test_rejects_unpaired_surrogates_in_utf8_output(self):
        with self.assertRaises(ValueError):
            canonical_json_bytes({"value": "\ud800"})


if __name__ == "__main__":
    unittest.main()
