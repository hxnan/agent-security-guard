import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = REPOSITORY_ROOT / "scripts" / "evaluate_p4_adapter.py"
    spec = importlib.util.spec_from_file_location("evaluate_p4_adapter_script", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class EvaluateP4AdapterCliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "scripts/evaluate_p4_adapter.py", *map(str, args)],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
        )

    def test_nonpositive_max_new_tokens_is_concise_argument_error(self):
        completed = self.run_cli("--max-new-tokens", "0")

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stderr, "")
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["stage"], "arguments")
        self.assertIn("max_new_tokens", payload["error"])

    def test_invalid_typed_argument_is_json_without_stderr(self):
        completed = self.run_cli("--max-new-tokens", "not-an-integer")

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stderr, "")
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["stage"], "arguments")
        self.assertIn("invalid int value", payload["error"])

    def test_missing_adapter_fails_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "not-created" / "report.json"
            completed = self.run_cli(
                "--adapter-dir",
                root / "missing-adapter",
                "--output",
                output,
            )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stderr, "")
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["stage"], "adapter_load")
        self.assertIn("incomplete", payload["error"])
        self.assertFalse(output.parent.exists())

    def test_model_path_resolution_failure_is_json_without_traceback(self):
        completed = self.run_cli(
            "--model-path",
            "~definitely_no_such_user_734829/model",
        )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stderr, "")
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["stage"], "adapter_load")
        self.assertIn("Could not determine home directory", payload["error"])

    def test_compact_summary_exposes_comparable_quality_and_safety_metrics(self):
        module = load_module()
        report = {
            "total_samples": 100,
            "compliance": {
                "first_pass_valid_output_rate": 0.96,
                "valid_output_rate": 0.98,
            },
            "repair_metrics": {
                "repair_attempt_rate": 0.04,
                "repair_success_rate": 0.5,
            },
            "risk_metrics": {"f1": 0.9},
            "category_metrics": {"macro_f1": 0.7},
            "decision_metrics": {"effective_decision_accuracy_all": 0.85},
            "safety_metrics": {"high_or_critical_allow_misses": 0},
            "performance": {
                "p50_latency_seconds": 1.2,
                "p95_latency_seconds": 2.5,
                "tokens_per_second": 35.0,
                "peak_gpu_memory_mb": 1800.0,
                "evaluation_wall_seconds": 150.0,
            },
        }

        summary = module._compact_summary(report, Path("report.json"))

        self.assertEqual(summary["valid_output_rate"], 0.98)
        self.assertEqual(summary["category_macro_f1"], 0.7)
        self.assertEqual(summary["high_risk_allow_miss_count"], 0)
        self.assertEqual(summary["output"], "report.json")


if __name__ == "__main__":
    unittest.main()
