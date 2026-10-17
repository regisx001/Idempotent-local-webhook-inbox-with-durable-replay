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


if __name__ == "__main__":
    unittest.main()
