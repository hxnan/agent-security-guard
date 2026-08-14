import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class EvaluateCliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "scripts/evaluate.py", *map(str, args)],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
        )

    def test_nonpositive_max_new_tokens_exits_two_before_model_loading(self):
        result = self.run_cli("--max-new-tokens", "0")
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertIn("max_new_tokens", payload["error"])
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_model_after_valid_freeze_exits_one_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "report.json"
            result = self.run_cli(
                "--model-path",
                root / "missing-model",
                "--output",
                output,
            )
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["stage"], "model_load")
        self.assertIn("missing model files", payload["error"])
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(output.exists())

    def test_missing_output_parent_is_not_created_before_model_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "not-created" / "report.json"
            result = self.run_cli(
                "--model-path",
                root / "missing-model",
                "--output",
                output,
            )
        self.assertEqual(result.returncode, 1)
        self.assertFalse(output.parent.exists())


if __name__ == "__main__":
    unittest.main()
