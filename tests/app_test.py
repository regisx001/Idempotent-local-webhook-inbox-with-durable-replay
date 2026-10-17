from __future__ import annotations

import subprocess
import sys
import unittest


def _run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "app.py", *arguments], capture_output=True, text=True, check=False)


class StarterTests(unittest.TestCase):
    def testCli_whenHelpRequested_returnsUsage(self) -> None:
        result = _run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--input", result.stdout)

    def testCli_whenInputMissing_reportsReadableError(self) -> None:
        result = _run_cli("--input", "inputs/does-not-exist.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def testCli_whenJsonMalformed_reportsReadableError(self) -> None:
        result = _run_cli("--input", "inputs/malformed-input.txt")
        self.assertEqual(result.returncode, 2)
        self.assertIn("error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def testCli_whenFeatureUnimplemented_returnsExplicitPlaceholder(self) -> None:
        result = _run_cli("--input", "inputs/primary.json")
        self.assertEqual(result.returncode, 3)
        self.assertIn("STARTER: implement", result.stderr)
        self.assertEqual(result.stdout, "")


from app import validate_delivery_row, validate_top_level_payload


class ValidationTests(unittest.TestCase):
    def testValidateRow_whenValidWithWhitespace_returnsTrimmedCanonical(self) -> None:
        row = {
            "delivery_id": "  d1  ",
            "tenant": "  north  ",
            "finding_id": "  f1  ",
            "version": 2,
            "status": " open "
        }
        is_valid, canonical, delivery_id, reason = validate_delivery_row(row, "north")
        self.assertTrue(is_valid)
        self.assertIsNone(reason)
        self.assertEqual(delivery_id, "d1")
        self.assertEqual(canonical, {
            "tenant": "north",
            "finding_id": "f1",
            "version": 2,
            "status": "open"
        })

    def testValidateRow_whenForeignTenant_rejectsWithReason(self) -> None:
        row = {
            "delivery_id": "d4",
            "tenant": "south",
            "finding_id": "f9",
            "version": 1,
            "status": "open"
        }
        is_valid, canonical, delivery_id, reason = validate_delivery_row(row, "north")
        self.assertFalse(is_valid)
        self.assertIsNone(canonical)
        self.assertEqual(delivery_id, "d4")
        self.assertIn("foreign tenant", reason)

    def testValidateRow_whenVersionZero_rejects(self) -> None:
        row = {
            "delivery_id": "d5",
            "tenant": "north",
            "finding_id": "f2",
            "version": 0,
            "status": "open"
        }
        is_valid, canonical, delivery_id, reason = validate_delivery_row(row, "north")
        self.assertFalse(is_valid)
        self.assertIsNone(canonical)
        self.assertEqual(delivery_id, "d5")
        self.assertIn("version must be a positive integer", reason)

    def testValidateRow_whenVersionBoolean_rejects(self) -> None:
        row = {
            "delivery_id": "d5",
            "tenant": "north",
            "finding_id": "f2",
            "version": True,
            "status": "open"
        }
        is_valid, canonical, delivery_id, reason = validate_delivery_row(row, "north")
        self.assertFalse(is_valid)
        self.assertIsNone(canonical)
        self.assertIn("version must be a positive integer", reason)

    def testValidateRow_whenMissingOrEmptyField_rejects(self) -> None:
        row = {
            "delivery_id": "   ",
            "tenant": "north",
            "finding_id": "f1",
            "version": 1,
            "status": "open"
        }
        is_valid, canonical, delivery_id, reason = validate_delivery_row(row, "north")
        self.assertFalse(is_valid)
        self.assertIsNone(canonical)
        self.assertIn("delivery_id must be a non-empty string", reason)

    def testValidateTopLevel_whenTenantMismatch_raisesValueError(self) -> None:
        with self.assertRaises(ValueError):
            validate_top_level_payload({"tenant": "south", "deliveries": []}, "north")


if __name__ == "__main__":
    unittest.main()
