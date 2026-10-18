from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
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

    def testCli_whenPrimaryRun_producesDocumentedCounts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = pathlib.Path(tmp_dir) / "state.json"
            result = _run_cli("--input", "inputs/primary.json", "--tenant", "north", "--state", str(state_file))
            self.assertEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data["counts"], {
                "applied": 3,
                "duplicate": 1,
                "redundant": 0,
                "rejected": 4,
                "stale": 1,
            })
            self.assertTrue(state_file.exists())

    def testCli_whenPrimaryReplayed_producesDocumentedReplayCounts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = pathlib.Path(tmp_dir) / "state.json"
            # First run
            _run_cli("--input", "inputs/primary.json", "--tenant", "north", "--state", str(state_file))
            # Second run (replay)
            result = _run_cli("--input", "inputs/primary.json", "--tenant", "north", "--state", str(state_file))
            self.assertEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data["counts"], {
                "applied": 0,
                "duplicate": 6,
                "redundant": 0,
                "rejected": 3,
                "stale": 0,
            })

    def testCli_whenSecondaryRunOnPrimaryState_producesDocumentedCounts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = pathlib.Path(tmp_dir) / "state.json"
            _run_cli("--input", "inputs/primary.json", "--tenant", "north", "--state", str(state_file))
            result = _run_cli("--input", "inputs/secondary.json", "--tenant", "north", "--state", str(state_file))
            self.assertEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data["counts"], {
                "applied": 2,
                "duplicate": 0,
                "redundant": 1,
                "rejected": 0,
                "stale": 0,
            })
            self.assertEqual(data["findings"]["f1"], {"version": 4, "status": "open"})
            self.assertEqual(data["findings"]["f2"], {"version": 2, "status": "resolved"})

    def testCli_whenStateMalformed_exitsTwoAndPreservesBytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = pathlib.Path(tmp_dir) / "corrupt_state.json"
            corrupt_bytes = b"{\n  \"tenant\": \"north\",\n  \"deliveries\": TRUNCATED"
            state_file.write_bytes(corrupt_bytes)

            result = _run_cli("--input", "inputs/primary.json", "--tenant", "north", "--state", str(state_file))
            self.assertEqual(result.returncode, 2)
            self.assertIn("error:", result.stderr)
            # Verify the exact bytes were not overwritten
            self.assertEqual(state_file.read_bytes(), corrupt_bytes)


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

    def testValidateRow_whenStatusNotLowerCase_rejectsDueToCaseSensitivity(self) -> None:
        row = {
            "delivery_id": "d1",
            "tenant": "north",
            "finding_id": "f1",
            "version": 1,
            "status": "OPEN",
        }
        is_valid, canonical, delivery_id, reason = validate_delivery_row(row, "north")
        self.assertFalse(is_valid)
        self.assertIsNone(canonical)
        self.assertIn("status must be 'open' or 'resolved'", reason)

    def testValidateRow_whenDeliveryIdNotString_rejects(self) -> None:
        row = {
            "delivery_id": 999,
            "tenant": "north",
            "finding_id": "f1",
            "version": 1,
            "status": "open",
        }
        is_valid, canonical, delivery_id, reason = validate_delivery_row(row, "north")
        self.assertFalse(is_valid)
        self.assertIsNone(canonical)
        self.assertIn("delivery_id must be a non-empty string", reason)


class BoundaryAndEdgeCaseTests(unittest.TestCase):
    def testCli_whenEmptyDeliveries_succeedsWithZeroCountsAndCreatesState(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_file = pathlib.Path(tmp_dir) / "empty_input.json"
            state_file = pathlib.Path(tmp_dir) / "state.json"
            input_file.write_text(json.dumps({"tenant": "north", "deliveries": []}), encoding="utf-8")

            result = _run_cli("--input", str(input_file), "--tenant", "north", "--state", str(state_file))
            self.assertEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data["counts"], {
                "applied": 0,
                "duplicate": 0,
                "redundant": 0,
                "rejected": 0,
                "stale": 0,
            })
            self.assertEqual(data["results"], [])
            self.assertEqual(data["findings"], {})
            self.assertTrue(state_file.exists())
            saved = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["tenant"], "north")
            self.assertEqual(saved["deliveries"], {})
            self.assertEqual(saved["findings"], {})

    def testCli_whenStateTenantMismatch_exitsTwoAndPreservesState(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = pathlib.Path(tmp_dir) / "south_state.json"
            original_bytes = json.dumps({
                "tenant": "south",
                "deliveries": {},
                "findings": {},
            }, indent=2).encode("utf-8")
            state_file.write_bytes(original_bytes)

            result = _run_cli("--input", "inputs/primary.json", "--tenant", "north", "--state", str(state_file))
            self.assertEqual(result.returncode, 2)
            self.assertIn("error:", result.stderr)
            self.assertIn("state tenant mismatch", result.stderr)
            self.assertEqual(state_file.read_bytes(), original_bytes)

    def testCli_whenVersionConflictRejected_keyIsReservedForReplayDeduplication(self) -> None:
        """Constructed boundary case: verifies that a row rejected with 'version conflict'

        reserves its idempotency key so subsequent redelivery is classified as 'duplicate'.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_file = pathlib.Path(tmp_dir) / "conflict_input.json"
            state_file = pathlib.Path(tmp_dir) / "state.json"

            # Row 1 applies f1 @ v3 resolved.
            # Row 2 arrives with d2 @ v3 open -> version conflict rejection.
            # Row 3 arrives redelivering d2 @ v3 open -> must be duplicate!
            payload = {
                "tenant": "north",
                "deliveries": [
                    {"delivery_id": "d1", "tenant": "north", "finding_id": "f1", "version": 3, "status": "resolved"},
                    {"delivery_id": "d2", "tenant": "north", "finding_id": "f1", "version": 3, "status": "open"},
                    {"delivery_id": "d2", "tenant": "north", "finding_id": "f1", "version": 3, "status": "open"},
                ],
            }
            input_file.write_text(json.dumps(payload), encoding="utf-8")

            result = _run_cli("--input", str(input_file), "--tenant", "north", "--state", str(state_file))
            self.assertEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data["counts"]["applied"], 1)
            self.assertEqual(data["counts"]["rejected"], 1)
            self.assertEqual(data["counts"]["duplicate"], 1)
            self.assertEqual(data["results"][1]["outcome"], "rejected")
            self.assertEqual(data["results"][1]["reason"], "version conflict")
            self.assertEqual(data["results"][2]["outcome"], "duplicate")
            self.assertEqual(data["results"][2]["reason"], "duplicate delivery")


if __name__ == "__main__":
    unittest.main()

