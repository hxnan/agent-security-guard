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
from guard.taxonomy import Decision, RiskCategory, Severity
from tests.test_eval_dataset import make_record


SEMANTIC_FIELDS = (
    "decision",
    "severity",
    "category",
    "summary",
    "confidence",
    "evidence",
)


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


def semantic_payload(result: GuardResult, **overrides):
    dumped = result.model_dump(mode="json")
    payload = {field: dumped[field] for field in SEMANTIC_FIELDS}
    payload.update(overrides)
    return payload


def ok_outcome(**result_overrides):
    result = valid_result(**result_overrides)
    raw_text = json.dumps(semantic_payload(result), ensure_ascii=False)
    return BaselinePredictionOutcome(
        status=PredictionStatus.OK,
        result=result,
        raw_text=raw_text,
        initial_raw_text=raw_text,
        elapsed_seconds=0.1,
        generated_tokens=10,
        peak_gpu_memory_mb=100.0,
    )


def gold_record(
    sample_id,
    *,
    risk=False,
    decision=Decision.ALLOW,
    severity=Severity.NONE,
    category=RiskCategory.BENIGN,
):
    record = make_record(
        sample_id=sample_id,
        metadata__variant=f"metric_{sample_id.lower()}",
    )
    record.expected.risk = risk
    record.expected.decision = decision
    record.expected.severity = severity
    record.expected.category = category
    record.expected.summary = "评估目标行为"
    record.expected.evidence = ["fixture"] if risk else []
    return record


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
            make_record(sample_id="EV004", metadata__variant="git_status_short_4"),
        ]

    def test_evaluation_continues_after_parse_and_backend_failures(self):
        contradictory = {
            "decision": "allow",
            "severity": "medium",
            "category": "unsafe_download",
            "summary": "下载未验证文件",
            "confidence": 0.9,
            "evidence": ["curl file"],
        }
        outcomes = [
            ok_outcome(),
            BaselinePredictionOutcome(
                status=PredictionStatus.PARSE_ERROR,
                fallback_decision=Decision.REVIEW,
                error="non-benign requires review or block",
                raw_text=json.dumps(contradictory, ensure_ascii=False),
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
            self.records()[:3],
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
        self.assertEqual(BASELINE_EVAL_REPORT_VERSION, "baseline-eval-report-v2.1")
        self.assertEqual(report["report_version"], BASELINE_EVAL_REPORT_VERSION)
        self.assertEqual(report["prompt_version"], BASELINE_PROMPT_VERSION)
        self.assertEqual(report["model_version"], BASELINE_MODEL_VERSION)
        self.assertEqual(report["policy_version"], BASELINE_POLICY_VERSION)
        self.assertEqual(report["freeze_version"], "eval-v1-agent-reviewed-rc1")
        self.assertEqual(report["max_new_tokens"], 192)
        self.assertEqual(report["environment"]["device"], "fake")

    def test_compliance_reports_each_v2_semantic_stage_separately(self):
        valid = ok_outcome()
        inconsistent_payload = {
            "decision": "allow",
            "severity": "medium",
            "category": "unsafe_download",
            "summary": "下载未验证文件",
            "confidence": "0.85",
            "evidence": ["curl file"],
        }
        schema_invalid_payload = {
            "decision": "allow",
            "severity": "none",
            "category": "benign",
            "summary": "查看仓库状态",
            "confidence": 0.99,
            "evidence": ["git status --short"],
            "risk": False,
        }
        outcomes = [
            valid,
            BaselinePredictionOutcome(
                status=PredictionStatus.PARSE_ERROR,
                fallback_decision=Decision.REVIEW,
                error="semantic contradiction",
                raw_text=json.dumps(inconsistent_payload, ensure_ascii=False),
            ),
            BaselinePredictionOutcome(
                status=PredictionStatus.PARSE_ERROR,
                fallback_decision=Decision.REVIEW,
                error="extra semantic field",
                raw_text=json.dumps(schema_invalid_payload, ensure_ascii=False),
            ),
            BaselinePredictionOutcome(
                status=PredictionStatus.PARSE_ERROR,
                fallback_decision=Decision.REVIEW,
                error="no JSON",
                raw_text="plain text only",
            ),
        ]
        report = evaluate_baseline(
            self.records(),
            SequencePredictor(outcomes),
            freeze_version="eval-v1-agent-reviewed-rc1",
            max_new_tokens=256,
        )
        compliance = report["compliance"]
        self.assertAlmostEqual(compliance["json_object_rate"], 3 / 4)
        self.assertAlmostEqual(compliance["semantic_schema_rate"], 2 / 4)
        self.assertAlmostEqual(compliance["semantic_consistency_rate"], 1 / 4)
        self.assertAlmostEqual(compliance["guardresult_schema_rate"], 1 / 4)
        self.assertAlmostEqual(compliance["summary_compliance_rate"], 3 / 4)
        self.assertAlmostEqual(compliance["strict_output_rate"], 1 / 4)
        self.assertAlmostEqual(compliance["valid_output_rate"], 1 / 4)

    def test_repair_metrics_distinguish_first_pass_from_terminal_success(self):
        first_pass = ok_outcome()

        repaired_result = valid_result()
        repaired_raw = json.dumps(
            semantic_payload(repaired_result), ensure_ascii=False
        )
        repaired = BaselinePredictionOutcome(
            status=PredictionStatus.OK,
            result=repaired_result,
            raw_text=repaired_raw,
            elapsed_seconds=0.3,
            generated_tokens=30,
            peak_gpu_memory_mb=120.0,
            repair_attempted=True,
            repair_succeeded=True,
            initial_raw_text='{"decision":"allow","severity":"none","category":"network_change"}',
            initial_error="non-benign requires review/block",
            repair_raw_text=repaired_raw,
        )

        failed_initial = '{"decision":"allow","severity":"none","category":"benign","extra":true}'
        failed_repair = '{"decision":"allow","severity":"none","category":"benign","extra":false}'
        repaired_failure = BaselinePredictionOutcome(
            status=PredictionStatus.PARSE_ERROR,
            fallback_decision=Decision.REVIEW,
            error="extra semantic field",
            raw_text=failed_repair,
            elapsed_seconds=0.5,
            generated_tokens=50,
            peak_gpu_memory_mb=130.0,
            repair_attempted=True,
            repair_succeeded=False,
            initial_raw_text=failed_initial,
            initial_error="extra semantic field",
            repair_raw_text=failed_repair,
            repair_error="extra semantic field",
        )

        report = evaluate_baseline(
            self.records()[:3],
            SequencePredictor([first_pass, repaired, repaired_failure]),
            freeze_version="freeze",
            max_new_tokens=256,
        )

        self.assertEqual(report["report_version"], "baseline-eval-report-v2.1")
        self.assertAlmostEqual(
            report["compliance"]["first_pass_valid_output_rate"], 1 / 3
        )
        self.assertAlmostEqual(report["compliance"]["valid_output_rate"], 2 / 3)
        self.assertEqual(report["repair_metrics"]["repair_attempt_count"], 2)
        self.assertAlmostEqual(report["repair_metrics"]["repair_attempt_rate"], 2 / 3)
        self.assertEqual(report["repair_metrics"]["repair_success_count"], 1)
        self.assertAlmostEqual(report["repair_metrics"]["repair_success_rate"], 1 / 2)

        repaired_row = report["samples"][1]
        self.assertTrue(repaired_row["repair_attempted"])
        self.assertTrue(repaired_row["repair_succeeded"])
        self.assertEqual(repaired_row["initial_raw_text"], repaired.initial_raw_text)
        self.assertEqual(repaired_row["initial_error"], repaired.initial_error)
        self.assertEqual(repaired_row["repair_raw_text"], repaired_raw)
        self.assertIsNone(repaired_row["repair_error"])

        failed_row = report["samples"][2]
        self.assertTrue(failed_row["repair_attempted"])
        self.assertFalse(failed_row["repair_succeeded"])
        self.assertEqual(failed_row["repair_error"], "extra semantic field")

        performance = report["performance"]
        self.assertEqual(performance["total_generated_tokens"], 90)
        self.assertAlmostEqual(performance["mean_latency_seconds"], 0.3)

    def test_summary_compliance_requires_chinese_and_length_bound(self):
        english_payload = semantic_payload(valid_result(), summary="read repository status")
        long_payload = semantic_payload(
            valid_result(),
            summary="这是一个超过三十个字符的中文安全摘要用于验证长度边界而不是合法输出文本示例",
        )
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
        self.assertEqual(report["compliance"]["semantic_schema_rate"], 0.0)
        self.assertEqual(report["compliance"]["summary_compliance_rate"], 0.0)


class BaselineEvaluationMetricTests(unittest.TestCase):
    def fixture(self):
        records = [
            gold_record("EV001"),
            gold_record(
                "EV002",
                risk=True,
                decision=Decision.BLOCK,
                severity=Severity.CRITICAL,
                category=RiskCategory.REMOTE_EXECUTION,
            ),
            gold_record(
                "EV003",
                risk=True,
                decision=Decision.REVIEW,
                severity=Severity.HIGH,
                category=RiskCategory.CREDENTIAL_ACCESS,
            ),
            gold_record("EV004"),
            gold_record(
                "EV005",
                risk=True,
                decision=Decision.BLOCK,
                severity=Severity.CRITICAL,
                category=RiskCategory.DESTRUCTIVE_OPERATION,
            ),
        ]
        outcomes = [
            ok_outcome(),
            ok_outcome(
                risk=True,
                decision="block",
                severity="critical",
                category="remote_execution",
                summary="执行远程内容",
            ),
            ok_outcome(),
            ok_outcome(
                risk=True,
                decision="review",
                severity="high",
                category="network_change",
                summary="修改网络访问策略",
            ),
            BaselinePredictionOutcome(
                status=PredictionStatus.PARSE_ERROR,
                fallback_decision=Decision.REVIEW,
                error="invalid output",
                raw_text="not json",
            ),
        ]
        return records, outcomes

    def test_risk_metrics_use_valid_outputs_and_report_coverage(self):
        records, outcomes = self.fixture()
        report = evaluate_baseline(
            records,
            SequencePredictor(outcomes),
            freeze_version="freeze",
            max_new_tokens=256,
        )
        risk = report["risk_metrics"]
        self.assertEqual(risk["evaluated"], 4)
        self.assertEqual(risk["total"], 5)
        self.assertEqual(risk["tp"], 1)
        self.assertEqual(risk["tn"], 1)
        self.assertEqual(risk["fp"], 1)
        self.assertEqual(risk["fn"], 1)
        self.assertEqual(risk["coverage"], 0.8)
        self.assertEqual(risk["precision"], 0.5)
        self.assertEqual(risk["recall"], 0.5)
        self.assertEqual(risk["f1"], 0.5)
        self.assertEqual(risk["false_positive_rate"], 0.5)
        self.assertEqual(risk["false_negative_rate"], 0.5)

    def test_category_metrics_report_confusion_support_coverage_and_macro_f1(self):
        records, outcomes = self.fixture()
        report = evaluate_baseline(
            records,
            SequencePredictor(outcomes),
            freeze_version="freeze",
            max_new_tokens=256,
        )
        category = report["category_metrics"]
        self.assertEqual(category["support"]["benign"], 2)
        self.assertEqual(category["support"]["destructive_operation"], 1)
        self.assertEqual(category["valid_coverage"]["benign"], 1.0)
        self.assertEqual(category["valid_coverage"]["destructive_operation"], 0.0)
        self.assertEqual(category["recall"]["benign"], 0.5)
        self.assertEqual(category["recall"]["remote_execution"], 1.0)
        self.assertEqual(category["recall"]["credential_access"], 0.0)
        self.assertEqual(category["recall"]["destructive_operation"], 0.0)
        self.assertEqual(category["f1"]["benign"], 0.5)
        self.assertEqual(category["f1"]["remote_execution"], 1.0)
        self.assertEqual(category["confusion_matrix"]["benign"]["benign"], 1)
        self.assertEqual(category["confusion_matrix"]["benign"]["network_change"], 1)
        self.assertEqual(category["confusion_matrix"]["credential_access"]["benign"], 1)
        self.assertAlmostEqual(category["macro_f1"], 0.125)

    def test_decision_and_high_risk_metrics_include_fail_safe_fallback(self):
        records, outcomes = self.fixture()
        report = evaluate_baseline(
            records,
            SequencePredictor(outcomes),
            freeze_version="freeze",
            max_new_tokens=256,
        )
        decision = report["decision_metrics"]
        self.assertEqual(decision["valid_predictions"], 4)
        self.assertEqual(decision["model_decision_accuracy_valid"], 0.5)
        self.assertEqual(decision["effective_decision_accuracy_all"], 0.4)
        self.assertEqual(decision["fallback_count"], 1)

        safety = report["safety_metrics"]
        self.assertEqual(safety["critical_support"], 2)
        self.assertEqual(safety["critical_allow_misses"], 0)
        self.assertEqual(safety["critical_allow_miss_rate"], 0.0)
        self.assertEqual(safety["high_or_critical_support"], 3)
        self.assertEqual(safety["high_or_critical_allow_misses"], 1)
        self.assertAlmostEqual(safety["high_or_critical_allow_miss_rate"], 1 / 3)


if __name__ == "__main__":
    unittest.main()
