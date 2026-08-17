import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = REPOSITORY_ROOT / "scripts" / "evaluate_rules.py"
    spec = importlib.util.spec_from_file_location("evaluate_rules_script", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class EvaluateRulesCliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "scripts/evaluate_rules.py", *map(str, args)],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
        )

    def test_default_output_path_is_rules_eval_v1(self):
        module = load_module()
        self.assertEqual(
            module.DEFAULT_OUTPUT,
            REPOSITORY_ROOT / "artifacts" / "rules-eval-v1" / "report.json",
        )

    def test_compact_summary_contains_only_decision_useful_metrics(self):
        module = load_module()
        report = {
            "total_samples": 100,
            "decisive_rate": 0.31,
            "abstain_rate": 0.69,
            "benign_rule_rate": 0.08,
            "dangerous_rule_rate": 0.23,
            "decision_accuracy_decisive": 0.97,
            "category_accuracy_decisive": 0.94,
            "false_benign_allow_count": 0,
            "high_or_critical_allow_miss_count": 0,
        }
        summary = module._compact_summary(report, Path("out.json"))
        self.assertEqual(
            set(summary),
            {
                "status",
                "total_samples",
                "decisive_rate",
                "abstain_rate",
                "benign_rule_rate",
                "dangerous_rule_rate",
                "decision_accuracy_decisive",
                "category_accuracy_decisive",
                "false_benign_allow_count",
                "high_or_critical_allow_miss_count",
                "output",
            },
        )
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["output"], "out.json")

    def test_committed_freeze_runs_cpu_only_and_writes_100_sample_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.json"
            result = self.run_cli("--output", output)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["total_samples"], 100)
            self.assertTrue(output.exists())
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["total_samples"], 100)
            self.assertEqual(len(report["samples"]), 100)
            self.assertNotIn("torch", sys.modules)
            self.assertNotIn("transformers", sys.modules)


if __name__ == "__main__":
    unittest.main()
