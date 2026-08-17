"""Evaluation metrics for rules-first Fusion V1."""

from collections import Counter
import json
from pathlib import Path
import time
from typing import Protocol, Sequence

from .eval_dataset import EvalGoldRecord
from .fusion import FUSION_POLICY_VERSION, FusionOutcome, FusionSource
from .taxonomy import Decision, RiskCategory, Severity


FUSION_EVAL_REPORT_VERSION = "fusion-eval-report-v1"


class FusionPredictorProtocol(Protocol):
    def predict(self, request) -> FusionOutcome: ...


def _rate(count: int | float, total: int | float) -> float:
    return count / total if total else 0.0


def _f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def _risk_metrics(samples: Sequence[dict[str, object]]) -> dict[str, object]:
    valid = [sample for sample in samples if sample["predicted"] is not None]
    tp = tn = fp = fn = 0
    for sample in valid:
        expected = bool(sample["expected"]["risk"])
        predicted = bool(sample["predicted"]["risk"])
        if expected and predicted:
            tp += 1
        elif not expected and not predicted:
            tn += 1
        elif not expected and predicted:
            fp += 1
        else:
            fn += 1
    precision = _rate(tp, tp + fp)
    recall = _rate(tp, tp + fn)
    return {
        "evaluated": len(valid),
        "total": len(samples),
        "coverage": _rate(len(valid), len(samples)),
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": _f1(precision, recall),
        "false_positive_rate": _rate(fp, fp + tn),
        "false_negative_rate": _rate(fn, fn + tp),
    }


def _category_metrics(samples: Sequence[dict[str, object]]) -> dict[str, object]:
    categories = [category.value for category in RiskCategory]
    support = {category: 0 for category in categories}
    predicted_count = {category: 0 for category in categories}
    true_positive = {category: 0 for category in categories}
    for sample in samples:
        expected = str(sample["expected"]["category"])
        support[expected] += 1
        predicted = sample["predicted"]
        if predicted is None:
            continue
        category = str(predicted["category"])
        predicted_count[category] += 1
        if category == expected:
            true_positive[category] += 1
    precision = {
        category: _rate(true_positive[category], predicted_count[category])
        for category in categories
    }
    recall = {
        category: _rate(true_positive[category], support[category])
        for category in categories
    }
    f1 = {
        category: _f1(precision[category], recall[category])
        for category in categories
    }
    return {
        "support": support,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "macro_f1": _rate(sum(f1.values()), len(categories)),
    }


def _performance(
    samples: Sequence[dict[str, object]],
    *,
    wall_seconds: float | None,
    measure_performance: bool,
) -> dict[str, object]:
    if not measure_performance:
        return {
            "measurement_mode": "not_measured",
            "mean_latency_seconds": None,
            "p50_latency_seconds": None,
            "p95_latency_seconds": None,
            "total_generated_tokens": None,
            "tokens_per_second": None,
            "peak_gpu_memory_mb": None,
            "evaluation_wall_seconds": None,
            "samples_per_second": None,
        }

    latencies = [float(sample["latency_seconds"]) for sample in samples]
    model_seconds = [
        float(sample["model_elapsed_seconds"])
        for sample in samples
        if sample["model_elapsed_seconds"] is not None
    ]
    tokens = sum(
        int(sample["generated_tokens"] or 0)
        for sample in samples
    )
    peaks = [
        float(sample["peak_gpu_memory_mb"])
        for sample in samples
        if sample["peak_gpu_memory_mb"] is not None
    ]
    model_total = sum(model_seconds)
    return {
        "measurement_mode": "live",
        "mean_latency_seconds": sum(latencies) / len(latencies) if latencies else None,
        "p50_latency_seconds": _percentile(latencies, 0.50),
        "p95_latency_seconds": _percentile(latencies, 0.95),
        "total_generated_tokens": tokens,
        "tokens_per_second": tokens / model_total if model_total > 0 else None,
        "peak_gpu_memory_mb": max(peaks) if peaks else None,
        "evaluation_wall_seconds": wall_seconds,
        "samples_per_second": (
            len(samples) / wall_seconds if wall_seconds and wall_seconds > 0 else None
        ),
    }


def evaluate_fusion(
    records: Sequence[EvalGoldRecord],
    predictor: FusionPredictorProtocol,
    *,
    freeze_version: str,
    measure_performance: bool,
) -> dict[str, object]:
    """Evaluate final Fusion outcomes while retaining their causal source."""
    started = time.perf_counter() if measure_performance else None
    samples: list[dict[str, object]] = []
    source_counts: Counter[str] = Counter()
    per_rule_contribution: Counter[str] = Counter()
    model_invocation_count = 0
    model_repair_attempt_count = 0
    model_repair_success_count = 0
    benign_false_positives: list[dict[str, str]] = []
    high_risk_allow_misses: list[dict[str, str]] = []

    for gold in records:
        sample_started = time.perf_counter() if measure_performance else None
        outcome = predictor.predict(gold.request)
        latency = (
            time.perf_counter() - sample_started
            if sample_started is not None
            else None
        )
        source = outcome.source.value
        source_counts[source] += 1
        if outcome.source is FusionSource.RULE and outcome.selected_rule_id:
            per_rule_contribution[outcome.selected_rule_id] += 1
        if outcome.model_invoked:
            model_invocation_count += 1
            if outcome.model_outcome and outcome.model_outcome.repair_attempted:
                model_repair_attempt_count += 1
            if outcome.model_outcome and outcome.model_outcome.repair_succeeded:
                model_repair_success_count += 1

        predicted = (
            outcome.result.model_dump(mode="json")
            if outcome.result is not None
            else None
        )
        effective_decision = (
            outcome.result.decision
            if outcome.result is not None
            else (outcome.fallback_decision or Decision.REVIEW)
        )
        expected = gold.expected
        decision_correct = (
            outcome.result.decision is expected.decision
            if outcome.result is not None
            else None
        )
        category_correct = (
            outcome.result.category is expected.category
            if outcome.result is not None
            else None
        )
        benign_fp = (
            expected.category is RiskCategory.BENIGN
            and outcome.result is not None
            and outcome.result.category is not RiskCategory.BENIGN
        )
        if benign_fp:
            benign_false_positives.append(
                {"sample_id": gold.sample_id, "source": source}
            )
        high_risk_miss = (
            expected.risk
            and expected.severity in {Severity.HIGH, Severity.CRITICAL}
            and effective_decision is Decision.ALLOW
        )
        if high_risk_miss:
            high_risk_allow_misses.append(
                {"sample_id": gold.sample_id, "source": source}
            )

        model_outcome = outcome.model_outcome
        samples.append(
            {
                "sample_id": gold.sample_id,
                "expected": {
                    "risk": expected.risk,
                    "decision": expected.decision.value,
                    "severity": expected.severity.value,
                    "category": expected.category.value,
                },
                "source": source,
                "status": outcome.status.value,
                "predicted": predicted,
                "fallback_decision": (
                    outcome.fallback_decision.value
                    if outcome.fallback_decision is not None
                    else None
                ),
                "effective_decision": effective_decision.value,
                "matched_rule_ids": [match.rule_id for match in outcome.rule_matches],
                "selected_rule_id": outcome.selected_rule_id,
                "model_invoked": outcome.model_invoked,
                "model_repair_attempted": bool(
                    model_outcome and model_outcome.repair_attempted
                ),
                "model_repair_succeeded": bool(
                    model_outcome and model_outcome.repair_succeeded
                ),
                "decision_correct": decision_correct,
                "category_correct": category_correct,
                "effective_decision_correct": effective_decision is expected.decision,
                "latency_seconds": latency,
                "model_elapsed_seconds": (
                    model_outcome.elapsed_seconds if model_outcome is not None else None
                ),
                "generated_tokens": (
                    model_outcome.generated_tokens if model_outcome is not None else 0
                ),
                "peak_gpu_memory_mb": (
                    model_outcome.peak_gpu_memory_mb if model_outcome is not None else None
                ),
            }
        )

    wall_seconds = (
        time.perf_counter() - started if started is not None else None
    )
    total = len(records)
    valid = [sample for sample in samples if sample["predicted"] is not None]
    effective_correct = sum(
        sample["effective_decision_correct"] is True for sample in samples
    )
    rule_short_circuit_count = source_counts[FusionSource.RULE.value]

    return {
        "report_version": FUSION_EVAL_REPORT_VERSION,
        "policy_version": FUSION_POLICY_VERSION,
        "freeze_version": freeze_version,
        "total_samples": total,
        "source_counts": dict(sorted(source_counts.items())),
        "rule_short_circuit_count": rule_short_circuit_count,
        "rule_short_circuit_rate": _rate(rule_short_circuit_count, total),
        "model_invocation_count": model_invocation_count,
        "model_invocation_rate": _rate(model_invocation_count, total),
        "valid_output_count": len(valid),
        "valid_output_rate": _rate(len(valid), total),
        "per_rule_contribution": dict(sorted(per_rule_contribution.items())),
        "model_repair_metrics": {
            "model_invoked_count": model_invocation_count,
            "attempt_count": model_repair_attempt_count,
            "attempt_rate": _rate(model_repair_attempt_count, model_invocation_count),
            "success_count": model_repair_success_count,
            "success_rate": _rate(
                model_repair_success_count, model_repair_attempt_count
            ),
        },
        "risk_metrics": _risk_metrics(samples),
        "category_metrics": _category_metrics(samples),
        "decision_metrics": {
            "valid_predictions": len(valid),
            "decision_accuracy_valid": _rate(
                sum(sample["decision_correct"] is True for sample in valid),
                len(valid),
            ),
            "effective_decision_accuracy_all": _rate(effective_correct, total),
            "fallback_count": source_counts[FusionSource.FALLBACK.value],
        },
        "benign_false_positive_count": len(benign_false_positives),
        "benign_false_positives": benign_false_positives,
        "high_risk_allow_miss_count": len(high_risk_allow_misses),
        "high_risk_allow_misses": high_risk_allow_misses,
        "performance": _performance(
            samples,
            wall_seconds=wall_seconds,
            measure_performance=measure_performance,
        ),
        "samples": samples,
    }


def write_fusion_evaluation_report(path: Path, report: dict[str, object]) -> None:
    """Atomically write a deterministic UTF-8 Fusion evaluation report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
