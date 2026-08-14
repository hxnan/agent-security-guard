import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class PredictBaselineCliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "scripts/predict_baseline.py", *map(str, args)],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
        )

    def test_invalid_request_json_exits_two_without_loading_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp) / "request.json"
            request.write_text("{not json", encoding="utf-8")
            result = self.run_cli("--request", request)
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertIn("invalid request JSON", payload["error"])
        self.assertNotIn("Traceback", result.stderr)

    def test_invalid_request_contract_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp) / "request.json"
            request.write_text(
                json.dumps({"type": "shell", "command": "   "}),
                encoding="utf-8",
            )
            result = self.run_cli("--request", request)
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertIn("invalid GuardRequest", payload["error"])

    def test_nonpositive_max_new_tokens_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp) / "request.json"
            request.write_text(
                json.dumps({"type": "shell", "command": "git status"}),
                encoding="utf-8",
            )
            result = self.run_cli(
                "--request",
                request,
                "--max-new-tokens",
                "0",
            )
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertIn("max_new_tokens", payload["error"])

    def test_missing_model_returns_backend_error_and_review_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = root / "request.json"
            request.write_text(
                json.dumps({"type": "shell", "command": "git status"}),
                encoding="utf-8",
            )
            result = self.run_cli(
                "--request",
                request,
                "--model-path",
                root / "missing-model",
            )
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "backend_error")
        self.assertEqual(payload["fallback_decision"], "review")
        self.assertIn("missing model files", payload["error"])
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
