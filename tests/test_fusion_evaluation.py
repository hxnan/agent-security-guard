import unittest

from guard.baseline_predictor import BaselinePredictionOutcome, PredictionStatus
from guard.contracts import GuardResult
from guard.fusion import FusionOutcome, FusionSource
from guard.fusion_evaluation import FUSION_EVAL_REPORT_VERSION, evaluate_fusion
from guard.rules import RuleMatch
from guard.taxonomy import Decision, RiskCategory, Severity
from tests.test_eval_dataset import make_record


def gold(
    sample_id,
    *,
    risk=False,
    decision=Decision.ALLOW,
    severity=Severity.NONE,
    category=RiskCategory.BENIGN,
):
    item = make_record(
        sample_id=sample_id,
        metadata__variant=f"fusion_{sample_id.lower()}",
    )
    item.expected.risk = risk
    item.expected.decision = decision
    item.expected.severity = severity
    item.expected.category = category
    item.expected.summary = "融合评估样本"
    item.expected.evidence = ["fixture"] if risk else []
    return item


def result(
    *,
    risk,
    decision,
    severity,
    category,
    policy_version="fusion-v1",
    rule_hits=None,
    model_version="qwen2.5-1.5b-instruct-baseline-v1",
):
    return GuardResult(
        schema_version="1.0",
        risk=risk,
        decision=decision,
        severity=severity,
        category=category,
        summary="融合判断结果",
        confidence=1.0 if model_version == "not-invoked" else 0.9,
        evidence=["fixture"],
        rule_hits=rule_hits or [],
        model_version=model_version,
        policy_version=policy_version,
    )


def rule_match(rule_id, category, decision, severity):
    return RuleMatch(
        rule_id=rule_id,
        category=category,
        decision=decision,
        severity=severity,
        summary="规则判断结果",
        evidence=("fixture",),
        priority=1,
    )


def rule_outcome(rule_id, category, decision, severity):
    match = rule_match(rule_id, category, decision, severity)
    return FusionOutcome(
        status=PredictionStatus.OK,
        result=result(
            risk=category is not RiskCategory.BENIGN,
            decision=decision,
            severity=severity,
            category=category,
            rule_hits=[rule_id],
            model_version="not-invoked",
        ),
        fallback_decision=None,
        source=FusionSource.RULE,
        rule_matches=(match,),
        selected_rule_id=rule_id,
        model_invoked=False,
        model_outcome=None,
    )


def model_outcome(*, repaired=False):
    model_result = result(
        risk=True,
        decision=Decision.REVIEW,
        severity=Severity.MEDIUM,
        category=RiskCategory.UNSAFE_DOWNLOAD,
    )
    baseline = BaselinePredictionOutcome(
        status=PredictionStatus.OK,
        result=model_result.model_copy(
            update={"policy_version": "model-only-baseline-v2.1"}
        ),
        elapsed_seconds=0.5,
        generated_tokens=20,
        peak_gpu_memory_mb=100.0,
        repair_attempted=repaired,
        repair_succeeded=repaired,
    )
    return FusionOutcome(
        status=PredictionStatus.OK,
        result=model_result,
        fallback_decision=None,
        source=FusionSource.MODEL,
        rule_matches=(),
        selected_rule_id=None,
        model_invoked=True,
        model_outcome=baseline,
    )


def fallback_outcome():
    baseline = BaselinePredictionOutcome(
        status=PredictionStatus.PARSE_ERROR,
        fallback_decision=Decision.REVIEW,
        error="invalid model output",
        repair_attempted=True,
        repair_succeeded=False,
    )
    return FusionOutcome(
        status=PredictionStatus.PARSE_ERROR,
        result=None,
        fallback_decision=Decision.REVIEW,
        source=FusionSource.FALLBACK,
        rule_matches=(),
        selected_rule_id=None,
        model_invoked=True,
        model_outcome=baseline,
    )


def rule_error_outcome():
    return FusionOutcome(
        status=PredictionStatus.PARSE_ERROR,
        result=None,
        fallback_decision=Decision.REVIEW,
        source=FusionSource.FALLBACK,
        rule_matches=(),
        selected_rule_id=None,
        model_invoked=False,
        model_outcome=None,
        rule_errors=("ExplodingMatcher: matcher boom",),
    )


class SequenceFusionPredictor:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def predict(self, request):
        outcome = self.outcomes[self.calls]
        self.calls += 1
        return outcome


class FusionEvaluationTests(unittest.TestCase):
    def test_report_tracks_sources_rules_model_repairs_and_final_coverage(self):
        records = [
            gold("EV001"),
            gold(
                "EV002",
                risk=True,
                decision=Decision.BLOCK,
                severity=Severity.CRITICAL,
                category=RiskCategory.REMOTE_EXECUTION,
            ),
            gold(
                "EV003",
                risk=True,
                decision=Decision.REVIEW,
                severity=Severity.MEDIUM,
                category=RiskCategory.UNSAFE_DOWNLOAD,
            ),
            gold(
                "EV004",
                risk=True,
                decision=Decision.BLOCK,
                severity=Severity.CRITICAL,
                category=RiskCategory.DATA_EXFILTRATION,
            ),
        ]
        outcomes = [
            rule_outcome(
                "rule.benign.git_status.v1",
                RiskCategory.BENIGN,
                Decision.ALLOW,
                Severity.NONE,
            ),
            rule_outcome(
                "rule.remote_execution.pipe_shell.v1",
                RiskCategory.REMOTE_EXECUTION,
                Decision.BLOCK,
                Severity.CRITICAL,
            ),
            model_outcome(repaired=True),
            fallback_outcome(),
        ]

        report = evaluate_fusion(
            records,
            SequenceFusionPredictor(outcomes),
            freeze_version="test-freeze",
            measure_performance=False,
        )

        self.assertEqual(FUSION_EVAL_REPORT_VERSION, "fusion-eval-report-v1")
        self.assertEqual(report["report_version"], FUSION_EVAL_REPORT_VERSION)
        self.assertEqual(report["policy_version"], "fusion-v1")
        self.assertEqual(report["freeze_version"], "test-freeze")
        self.assertEqual(report["total_samples"], 4)
        self.assertEqual(
            report["source_counts"], {"fallback": 1, "model": 1, "rule": 2}
        )
        self.assertEqual(report["rule_short_circuit_count"], 2)
        self.assertEqual(report["rule_short_circuit_rate"], 0.5)
        self.assertEqual(report["model_invocation_count"], 2)
        self.assertEqual(report["model_invocation_rate"], 0.5)
        self.assertEqual(report["valid_output_count"], 3)
        self.assertEqual(report["valid_output_rate"], 0.75)
        self.assertEqual(report["rule_error_count"], 0)
        self.assertEqual(report["rule_error_rate"], 0.0)
        self.assertEqual(
            report["per_rule_contribution"],
            {
                "rule.benign.git_status.v1": 1,
                "rule.remote_execution.pipe_shell.v1": 1,
            },
        )
        self.assertEqual(report["model_repair_metrics"]["attempt_count"], 2)
        self.assertEqual(report["model_repair_metrics"]["attempt_rate"], 1.0)
        self.assertEqual(report["model_repair_metrics"]["success_count"], 1)
        self.assertEqual(report["model_repair_metrics"]["success_rate"], 0.5)
        self.assertEqual(report["benign_false_positive_count"], 0)
        self.assertEqual(report["high_risk_allow_miss_count"], 0)
        self.assertEqual(report["performance"]["measurement_mode"], "not_measured")
        self.assertIsNone(report["performance"]["p50_latency_seconds"])
        self.assertIsNone(report["performance"]["tokens_per_second"])
        self.assertEqual(report["samples"][0]["rule_errors"], [])

    def test_rule_errors_are_reported_separately_from_model_fallback(self):
        report = evaluate_fusion(
            [gold("EV001")],
            SequenceFusionPredictor([rule_error_outcome()]),
            freeze_version="test",
            measure_performance=False,
        )
        self.assertEqual(report["source_counts"], {"fallback": 1})
        self.assertEqual(report["rule_error_count"], 1)
        self.assertEqual(report["rule_error_rate"], 1.0)
        self.assertEqual(report["model_invocation_count"], 0)
        self.assertEqual(len(report["samples"][0]["rule_errors"]), 1)
        self.assertIn("matcher boom", report["samples"][0]["rule_errors"][0])

    def test_benign_false_positive_records_source(self):
        records = [gold("EV001")]
        outcome = model_outcome()
        report = evaluate_fusion(
            records,
            SequenceFusionPredictor([outcome]),
            freeze_version="test",
            measure_performance=False,
        )
        self.assertEqual(report["benign_false_positive_count"], 1)
        self.assertEqual(
            report["benign_false_positives"],
            [{"sample_id": "EV001", "source": "model"}],
        )

    def test_high_risk_allow_miss_records_rule_source(self):
        records = [
            gold(
                "EV001",
                risk=True,
                decision=Decision.REVIEW,
                severity=Severity.HIGH,
                category=RiskCategory.SENSITIVE_WRITE,
            )
        ]
        outcome = rule_outcome(
            "rule.benign.git_status.v1",
            RiskCategory.BENIGN,
            Decision.ALLOW,
            Severity.NONE,
        )
        report = evaluate_fusion(
            records,
            SequenceFusionPredictor([outcome]),
            freeze_version="test",
            measure_performance=False,
        )
        self.assertEqual(report["high_risk_allow_miss_count"], 1)
        self.assertEqual(
            report["high_risk_allow_misses"],
            [{"sample_id": "EV001", "source": "rule"}],
        )

    def test_model_repair_denominator_is_only_model_invoked_requests(self):
        records = [gold("EV001"), gold("EV002"), gold("EV003")]
        outcomes = [
            rule_outcome(
                "rule.benign.git_status.v1",
                RiskCategory.BENIGN,
                Decision.ALLOW,
                Severity.NONE,
            ),
            model_outcome(repaired=False),
            fallback_outcome(),
        ]
        report = evaluate_fusion(
            records,
            SequenceFusionPredictor(outcomes),
            freeze_version="test",
            measure_performance=False,
        )
        metrics = report["model_repair_metrics"]
        self.assertEqual(metrics["model_invoked_count"], 2)
        self.assertEqual(metrics["attempt_count"], 1)
        self.assertEqual(metrics["attempt_rate"], 0.5)
        self.assertEqual(metrics["success_count"], 0)
        self.assertEqual(metrics["success_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
