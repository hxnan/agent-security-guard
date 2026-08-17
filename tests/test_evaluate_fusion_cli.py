import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = REPOSITORY_ROOT / "scripts" / "evaluate_fusion.py"
    spec = importlib.util.spec_from_file_location("evaluate_fusion_script", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class EvaluateFusionCliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "scripts/evaluate_fusion.py", *map(str, args)],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
        )

    def test_default_output_path_is_fusion_eval_v1(self):
        module = load_module()
        self.assertEqual(
            module.DEFAULT_OUTPUT,
            REPOSITORY_ROOT / "artifacts" / "fusion-eval-v1" / "report.json",
        )

    def test_compact_summary_exposes_source_quality_safety_and_performance(self):
        module = load_module()
        report = {
            "total_samples": 100,
            "valid_output_rate": 0.8,
            "rule_short_circuit_rate": 0.3,
            "model_invocation_rate": 0.7,
            "source_counts": {"rule": 30, "model": 50, "fallback": 20},
            "model_repair_metrics": {"attempt_rate": 0.6, "success_rate": 0.5},
            "risk_metrics": {"f1": 0.85},
            "category_metrics": {"macro_f1": 0.4},
            "decision_metrics": {"effective_decision_accuracy_all": 0.7},
            "benign_false_positive_count": 8,
            "high_risk_allow_miss_count": 0,
            "performance": {
                "p50_latency_seconds": 2.1,
                "p95_latency_seconds": 5.2,
                "tokens_per_second": 29.0,
                "peak_gpu_memory_mb": 3000.0,
                "evaluation_wall_seconds": 300.0,
            },
        }
        summary = module._compact_summary(report, Path("out.json"))
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["rule_short_circuit_rate"], 0.3)
        self.assertEqual(summary["model_invocation_rate"], 0.7)
        self.assertEqual(summary["valid_output_rate"], 0.8)
        self.assertEqual(summary["risk_f1"], 0.85)
        self.assertEqual(summary["category_macro_f1"], 0.4)
        self.assertEqual(summary["benign_false_positive_count"], 8)
        self.assertEqual(summary["high_risk_allow_miss_count"], 0)
        self.assertEqual(summary["output"], "out.json")

    def test_nonpositive_max_new_tokens_exits_two_before_model_loading(self):
        result = self.run_cli("--max-new-tokens", "0")
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["stage"], "arguments")
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_model_exits_one_without_creating_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "nested" / "report.json"
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
            self.assertFalse(output.exists())
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
