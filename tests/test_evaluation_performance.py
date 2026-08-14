import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from guard import evaluation
from guard.baseline_predictor import BaselinePredictionOutcome, PredictionStatus
from guard.baseline_prompt import BASELINE_MODEL_VERSION, BASELINE_POLICY_VERSION
from guard.contracts import GuardResult
from tests.test_eval_dataset import make_record


def outcome(elapsed, tokens, peak):
    result = GuardResult.model_validate(
        {
            "schema_version": "1.0",
            "risk": False,
            "decision": "allow",
            "severity": "none",
            "category": "benign",
            "summary": "查看仓库状态",
            "confidence": 0.99,
            "evidence": ["git status --short"],
            "rule_hits": [],
            "model_version": BASELINE_MODEL_VERSION,
            "policy_version": BASELINE_POLICY_VERSION,
        }
    )
    return BaselinePredictionOutcome(
        status=PredictionStatus.OK,
        result=result,
        raw_text=json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
        elapsed_seconds=elapsed,
        generated_tokens=tokens,
        peak_gpu_memory_mb=peak,
    )


class SequencePredictor:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.index = 0

    def predict(self, request):
        value = self.outcomes[self.index]
        self.index += 1
        return value


class EvaluationPerformanceTests(unittest.TestCase):
    def test_performance_metrics_use_interpolated_percentiles_and_aggregate_tokens(self):
        records = [
            make_record(sample_id="EV001", metadata__variant="perf_1"),
            make_record(sample_id="EV002", metadata__variant="perf_2"),
            make_record(sample_id="EV003", metadata__variant="perf_3"),
        ]
        predictor = SequencePredictor(
            [
                outcome(1.0, 10, 100.0),
                outcome(2.0, 20, 300.0),
                outcome(4.0, 40, 200.0),
            ]
        )
        with patch("guard.evaluation.time.perf_counter", side_effect=[10.0, 15.0]):
            report = evaluation.evaluate_baseline(
                records,
                predictor,
                freeze_version="freeze",
                max_new_tokens=256,
            )

        performance = report["performance"]
        self.assertEqual(performance["latency_samples"], 3)
        self.assertAlmostEqual(performance["mean_latency_seconds"], 7 / 3)
        self.assertEqual(performance["p50_latency_seconds"], 2.0)
        self.assertAlmostEqual(performance["p95_latency_seconds"], 3.8)
        self.assertEqual(performance["total_generated_tokens"], 70)
        self.assertEqual(performance["tokens_per_second"], 10.0)
        self.assertEqual(performance["peak_gpu_memory_mb"], 300.0)
        self.assertEqual(performance["evaluation_wall_seconds"], 5.0)
        self.assertEqual(performance["samples_per_second"], 0.6)

    def test_missing_runtime_metrics_do_not_break_performance_summary(self):
        record = make_record()
        failed = BaselinePredictionOutcome(
            status=PredictionStatus.BACKEND_ERROR,
            fallback_decision="review",
            error="backend unavailable",
        )
        with patch("guard.evaluation.time.perf_counter", side_effect=[1.0, 3.0]):
            report = evaluation.evaluate_baseline(
                [record],
                SequencePredictor([failed]),
                freeze_version="freeze",
                max_new_tokens=256,
            )
        performance = report["performance"]
        self.assertEqual(performance["latency_samples"], 0)
        self.assertIsNone(performance["mean_latency_seconds"])
        self.assertIsNone(performance["p50_latency_seconds"])
        self.assertIsNone(performance["p95_latency_seconds"])
        self.assertEqual(performance["total_generated_tokens"], 0)
        self.assertIsNone(performance["tokens_per_second"])
        self.assertIsNone(performance["peak_gpu_memory_mb"])
        self.assertEqual(performance["evaluation_wall_seconds"], 2.0)
        self.assertEqual(performance["samples_per_second"], 0.5)

    def test_report_writer_is_atomic_utf8_and_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "report.json"
            report = {"z": 1, "中文": "值", "a": {"b": 2}}
            evaluation.write_evaluation_report(path, report)

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), report)
            self.assertFalse(path.with_suffix(path.suffix + ".tmp").exists())
            text = path.read_text(encoding="utf-8")
            self.assertLess(text.index('"a"'), text.index('"z"'))
            self.assertIn("中文", text)


if __name__ == "__main__":
    unittest.main()
