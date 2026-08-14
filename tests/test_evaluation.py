import json
import unittest

from guard.baseline_predictor import BaselinePredictionOutcome, PredictionStatus
from guard.baseline_prompt import (
    BASELINE_MODEL_VERSION,
    BASELINE_POLICY_VERSION,
    BASELINE_PROMPT_VERSION,
)
from guard.contracts import GuardResult
from guard.evaluation import BASELINE_EVAL_REPORT_VERSION, evaluate_baseline
from guard.taxonomy import Decision
from tests.test_eval_dataset import make_record


def valid_result(**overrides):
    payload = {
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
    payload.update(overrides)
    return GuardResult.model_validate(payload)


def ok_outcome(**result_overrides):
    result = valid_result(**result_overrides)
    return BaselinePredictionOutcome(
        status=PredictionStatus.OK,
        result=result,
        raw_text=json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
        elapsed_seconds=0.1,
        generated_tokens=10,
        peak_gpu_memory_mb=100.0,
    )


class SequencePredictor:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def predict(self, request):
        self.calls.append(request.command)
        return self.outcomes[len(self.calls) - 1]


class BaselineEvaluationLoopTests(unittest.TestCase):
    def records(self):
        return [
            make_record(sample_id="EV001"),
            make_record(sample_id="EV002", metadata__variant="git_status_short_2"),
            make_record(sample_id="EV003", metadata__variant="git_status_short_3"),
        ]

    def test_evaluation_continues_after_parse_and_backend_failures(self):
        wrong_provenance = valid_result(model_version="wrong-model")
        outcomes = [
            ok_outcome(),
            BaselinePredictionOutcome(
                status=PredictionStatus.PARSE_ERROR,
                fallback_decision=Decision.REVIEW,
                error="model_version mismatch",
                raw_text=json.dumps(
                    wrong_provenance.model_dump(mode="json"), ensure_ascii=False
                ),
                elapsed_seconds=0.2,
                generated_tokens=20,
                peak_gpu_memory_mb=150.0,
            ),
            BaselinePredictionOutcome(
                status=PredictionStatus.BACKEND_ERROR,
                fallback_decision=Decision.REVIEW,
                error="temporary backend failure",
            ),
        ]
        predictor = SequencePredictor(outcomes)

        report = evaluate_baseline(
            self.records(),
            predictor,
            freeze_version="eval-v1-agent-reviewed-rc1",
            max_new_tokens=256,
            environment={"device": "fake"},
        )

        self.assertEqual(len(predictor.calls), 3)
        self.assertEqual(len(report["samples"]), 3)
        self.assertEqual(
            report["status_counts"],
            {"backend_error": 1, "ok": 1, "parse_error": 1},
        )
        self.assertEqual(report["samples"][0]["sample_id"], "EV001")
        self.assertEqual(report["samples"][1]["sample_id"], "EV002")
        self.assertEqual(report["samples"][2]["sample_id"], "EV003")
        self.assertEqual(report["samples"][1]["effective_decision"], "review")
        self.assertEqual(report["samples"][2]["effective_decision"], "review")
        self.assertIsNone(report["samples"][1]["risk_correct"])
        self.assertIsNone(report["samples"][2]["category_correct"])
        self.assertEqual(report["samples"][1]["raw_text"], outcomes[1].raw_text)
        self.assertEqual(report["samples"][1]["generated_tokens"], 20)
        self.assertEqual(report["samples"][1]["peak_gpu_memory_mb"], 150.0)

    def test_report_versions_and_environment_are_explicit(self):
        report = evaluate_baseline(
            [make_record()],
            SequencePredictor([ok_outcome()]),
            freeze_version="eval-v1-agent-reviewed-rc1",
            max_new_tokens=192,
            environment={"python_version": "test-python", "device": "fake"},
        )
        self.assertEqual(report["report_version"], BASELINE_EVAL_REPORT_VERSION)
        self.assertEqual(report["prompt_version"], BASELINE_PROMPT_VERSION)
        self.assertEqual(report["model_version"], BASELINE_MODEL_VERSION)
        self.assertEqual(report["policy_version"], BASELINE_POLICY_VERSION)
        self.assertEqual(report["freeze_version"], "eval-v1-agent-reviewed-rc1")
        self.assertEqual(report["max_new_tokens"], 192)
        self.assertEqual(report["environment"]["device"], "fake")

    def test_compliance_distinguishes_json_schema_summary_and_strict_output(self):
        schema_valid_wrong_provenance = valid_result(model_version="other-model")
        outcomes = [
            ok_outcome(),
            BaselinePredictionOutcome(
                status=PredictionStatus.PARSE_ERROR,
                fallback_decision=Decision.REVIEW,
                error="model_version mismatch",
                raw_text=json.dumps(
                    schema_valid_wrong_provenance.model_dump(mode="json"),
                    ensure_ascii=False,
                ),
                elapsed_seconds=0.2,
                generated_tokens=12,
            ),
            BaselinePredictionOutcome(
                status=PredictionStatus.PARSE_ERROR,
                fallback_decision=Decision.REVIEW,
                error="no JSON",
                raw_text="plain text only",
                elapsed_seconds=0.3,
                generated_tokens=4,
            ),
        ]
        report = evaluate_baseline(
            self.records(),
            SequencePredictor(outcomes),
            freeze_version="eval-v1-agent-reviewed-rc1",
            max_new_tokens=256,
        )
        compliance = report["compliance"]
        self.assertAlmostEqual(compliance["json_object_rate"], 2 / 3)
        self.assertAlmostEqual(compliance["guardresult_schema_rate"], 2 / 3)
        self.assertAlmostEqual(compliance["summary_compliance_rate"], 2 / 3)
        self.assertAlmostEqual(compliance["strict_output_rate"], 1 / 3)
        self.assertAlmostEqual(compliance["valid_output_rate"], 1 / 3)

    def test_summary_compliance_requires_chinese_and_length_bound(self):
        english_payload = valid_result().model_dump(mode="json")
        english_payload["summary"] = "read repository status"
        long_payload = valid_result().model_dump(mode="json")
        long_payload["summary"] = "这是一个超过三十个字符的中文安全摘要用于验证长度边界而不是合法输出文本示例"
        outcomes = [
            BaselinePredictionOutcome(
                status=PredictionStatus.PARSE_ERROR,
                fallback_decision=Decision.REVIEW,
                error="summary language",
                raw_text=json.dumps(english_payload, ensure_ascii=False),
            ),
            BaselinePredictionOutcome(
                status=PredictionStatus.PARSE_ERROR,
                fallback_decision=Decision.REVIEW,
                error="summary length",
                raw_text=json.dumps(long_payload, ensure_ascii=False),
            ),
        ]
        report = evaluate_baseline(
            self.records()[:2],
            SequencePredictor(outcomes),
            freeze_version="freeze",
            max_new_tokens=256,
        )
        self.assertEqual(report["compliance"]["json_object_rate"], 1.0)
        self.assertEqual(report["compliance"]["summary_compliance_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
