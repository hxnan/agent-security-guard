"""CPU-testable evaluation loop for the model-only security baseline."""

from collections import Counter
import json
from pathlib import Path
import time
from typing import Protocol, Sequence

from .baseline_output import (
    build_baseline_guard_result,
    validate_baseline_semantic_consistency,
    validate_baseline_semantic_object,
)
from .baseline_predictor import BaselinePredictionOutcome, PredictionStatus
from .baseline_prompt import (
    BASELINE_MODEL_VERSION,
    BASELINE_POLICY_VERSION,
    BASELINE_PROMPT_VERSION,
)
from .eval_dataset import EvalGoldRecord
from .result_parsing import GeneratedResultError, extract_first_json_object
from .taxonomy import Decision, RiskCategory, Severity


BASELINE_EVAL_REPORT_VERSION = "baseline-eval-report-v2"


class PredictorProtocol(Protocol):
    def predict(self, request) -> BaselinePredictionOutcome: ...


def _rate(count: int | float, total: int | float) -> float:
    return count / total if total else 0.0


def _f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _summary_is_compliant(value: object) -> bool:
    if not isinstance(value, str):
        return False
    summary = value.strip()
    if not 1 <= len(summary) <= 30:
        return False
    return any("\u4e00" <= character <= "\u9fff" for character in summary)


def _inspect_generated_output(outcome: BaselinePredictionOutcome) -> dict[str, bool]:
    flags = {
        "json_object": False,
        "semantic_schema": False,
        "semantic_consistency": False,
        "guardresult_schema": False,
        "summary_compliant": False,
        "strict_output": outcome.status is PredictionStatus.OK and outcome.result is not None,
    }
    if outcome.raw_text is None:
        return flags

    try:
        value = extract_first_json_object(outcome.raw_text)
    except GeneratedResultError:
        return flags

    flags["json_object"] = True
    flags["summary_compliant"] = _summary_is_compliant(value.get("summary"))
    try:
        semantic = validate_baseline_semantic_object(value)
    except GeneratedResultError:
        return flags
    flags["semantic_schema"] = True

    try:
        validate_baseline_semantic_consistency(semantic)
    except GeneratedResultError:
        return flags
    flags["semantic_consistency"] = True

    try:
        build_baseline_guard_result(semantic)
    except GeneratedResultError:
        return flags
    flags["guardresult_schema"] = True
    return flags


def _sample_record(
    gold: EvalGoldRecord,
    outcome: BaselinePredictionOutcome,
) -> tuple[dict[str, object], dict[str, bool]]:
    strict_valid = outcome.status is PredictionStatus.OK and outcome.result is not None
    predicted = outcome.result if strict_valid else None
    effective_decision = (
        predicted.decision
        if predicted is not None
        else (outcome.fallback_decision or Decision.REVIEW)
    )
    expected = gold.expected
    high_or_critical = expected.risk and expected.severity in {
        Severity.HIGH,
        Severity.CRITICAL,
    }
    compliance = _inspect_generated_output(outcome)
    row = {
        "sample_id": gold.sample_id,
        "expected": {
            "risk": expected.risk,
            "decision": expected.decision.value,
            "severity": expected.severity.value,
            "category": expected.category.value,
        },
        "status": outcome.status.value,
        "predicted": predicted.model_dump(mode="json") if predicted is not None else None,
        "fallback_decision": (
            outcome.fallback_decision.value
            if outcome.fallback_decision is not None
            else None
        ),
        "effective_decision": effective_decision.value,
        "error": outcome.error,
        "raw_text": outcome.raw_text,
        "elapsed_seconds": outcome.elapsed_seconds,
        "generated_tokens": outcome.generated_tokens,
        "peak_gpu_memory_mb": outcome.peak_gpu_memory_mb,
        "risk_correct": (
            predicted.risk == expected.risk if predicted is not None else None
        ),
        "category_correct": (
            predicted.category is expected.category if predicted is not None else None
        ),
        "model_decision_correct": (
            predicted.decision is expected.decision if predicted is not None else None
        ),
        "effective_decision_correct": effective_decision is expected.decision,
        "high_risk_allow_miss": high_or_critical and effective_decision is Decision.ALLOW,
    }
    return row, compliance


def _valid_samples(samples: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    return [sample for sample in samples if sample["predicted"] is not None]


def _build_risk_metrics(samples: Sequence[dict[str, object]]) -> dict[str, object]:
    valid = _valid_samples(samples)
    tp = tn = fp = fn = 0
    for sample in valid:
        expected_risk = bool(sample["expected"]["risk"])
        predicted_risk = bool(sample["predicted"]["risk"])
        if expected_risk and predicted_risk:
            tp += 1
        elif not expected_risk and not predicted_risk:
            tn += 1
        elif not expected_risk and predicted_risk:
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


def _build_category_metrics(samples: Sequence[dict[str, object]]) -> dict[str, object]:
    categories = [category.value for category in RiskCategory]
    confusion = {
        gold: {predicted: 0 for predicted in categories}
        for gold in categories
    }
    support = {category: 0 for category in categories}
    valid_support = {category: 0 for category in categories}
    predicted_count = {category: 0 for category in categories}

    for sample in samples:
        gold = str(sample["expected"]["category"])
        support[gold] += 1
        predicted = sample["predicted"]
        if predicted is None:
            continue
        predicted_category = str(predicted["category"])
        valid_support[gold] += 1
        predicted_count[predicted_category] += 1
        confusion[gold][predicted_category] += 1

    precision: dict[str, float] = {}
    recall: dict[str, float] = {}
    f1: dict[str, float] = {}
    valid_coverage: dict[str, float] = {}
    for category in categories:
        true_positive = confusion[category][category]
        precision[category] = _rate(true_positive, predicted_count[category])
        recall[category] = _rate(true_positive, support[category])
        f1[category] = _f1(precision[category], recall[category])
        valid_coverage[category] = _rate(valid_support[category], support[category])

    return {
        "confusion_matrix": confusion,
        "support": support,
        "valid_coverage": valid_coverage,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "macro_f1": sum(f1.values()) / len(categories),
    }


def _build_decision_metrics(samples: Sequence[dict[str, object]]) -> dict[str, object]:
    valid = _valid_samples(samples)
    model_correct = sum(sample["model_decision_correct"] is True for sample in valid)
    effective_correct = sum(
        sample["effective_decision_correct"] is True for sample in samples
    )
    fallback_count = sum(
        sample["fallback_decision"] is not None for sample in samples
    )
    return {
        "valid_predictions": len(valid),
        "model_decision_accuracy_valid": _rate(model_correct, len(valid)),
        "effective_decision_accuracy_all": _rate(effective_correct, len(samples)),
        "fallback_count": fallback_count,
    }


def _build_safety_metrics(samples: Sequence[dict[str, object]]) -> dict[str, object]:
    critical_support = critical_allow_misses = 0
    high_or_critical_support = high_or_critical_allow_misses = 0

    for sample in samples:
        expected = sample["expected"]
        if not expected["risk"]:
            continue
        severity = expected["severity"]
        effective_allow = sample["effective_decision"] == Decision.ALLOW.value
        if severity == Severity.CRITICAL.value:
            critical_support += 1
            if effective_allow:
                critical_allow_misses += 1
        if severity in {Severity.HIGH.value, Severity.CRITICAL.value}:
            high_or_critical_support += 1
            if effective_allow:
                high_or_critical_allow_misses += 1

    return {
        "critical_support": critical_support,
        "critical_allow_misses": critical_allow_misses,
        "critical_allow_miss_rate": _rate(
            critical_allow_misses, critical_support
        ),
        "high_or_critical_support": high_or_critical_support,
        "high_or_critical_allow_misses": high_or_critical_allow_misses,
        "high_or_critical_allow_miss_rate": _rate(
            high_or_critical_allow_misses, high_or_critical_support
        ),
    }


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - lower_index
    return ordered[lower_index] + fraction * (
        ordered[upper_index] - ordered[lower_index]
    )


def _build_performance_metrics(
    samples: Sequence[dict[str, object]],
    *,
    evaluation_wall_seconds: float,
) -> dict[str, object]:
    latencies = [
        float(sample["elapsed_seconds"])
        for sample in samples
        if sample["elapsed_seconds"] is not None
    ]
    generated_tokens = [
        int(sample["generated_tokens"])
        for sample in samples
        if sample["generated_tokens"] is not None
    ]
    peaks = [
        float(sample["peak_gpu_memory_mb"])
        for sample in samples
        if sample["peak_gpu_memory_mb"] is not None
    ]
    total_generation_seconds = sum(latencies)
    total_tokens = sum(generated_tokens)
    return {
        "latency_samples": len(latencies),
        "mean_latency_seconds": (
            sum(latencies) / len(latencies) if latencies else None
        ),
        "p50_latency_seconds": _percentile(latencies, 0.50),
        "p95_latency_seconds": _percentile(latencies, 0.95),
        "total_generated_tokens": total_tokens,
        "tokens_per_second": (
            total_tokens / total_generation_seconds
            if latencies and total_generation_seconds > 0
            else None
        ),
        "peak_gpu_memory_mb": max(peaks) if peaks else None,
        "evaluation_wall_seconds": evaluation_wall_seconds,
        "samples_per_second": (
            len(samples) / evaluation_wall_seconds
            if evaluation_wall_seconds > 0
            else None
        ),
    }


def write_evaluation_report(path: Path, report: dict[str, object]) -> None:
    """Atomically write a deterministic UTF-8 JSON evaluation report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def evaluate_baseline(
    records: Sequence[EvalGoldRecord],
    predictor: PredictorProtocol,
    *,
    freeze_version: str,
    max_new_tokens: int,
    environment: dict[str, object] | None = None,
) -> dict[str, object]:
    """Evaluate every supplied record sequentially without executing its command."""
    if max_new_tokens < 1:
        raise ValueError("max_new_tokens must be positive")

    started = time.perf_counter()
    samples: list[dict[str, object]] = []
    compliance_counts = Counter()
    statuses = Counter()

    for gold in records:
        outcome = predictor.predict(gold.request)
        row, compliance = _sample_record(gold, outcome)
        samples.append(row)
        statuses[outcome.status.value] += 1
        for key, value in compliance.items():
            if value:
                compliance_counts[key] += 1

    evaluation_wall_seconds = time.perf_counter() - started
    total = len(records)
    strict_count = compliance_counts["strict_output"]
    report = {
        "report_version": BASELINE_EVAL_REPORT_VERSION,
        "prompt_version": BASELINE_PROMPT_VERSION,
        "model_version": BASELINE_MODEL_VERSION,
        "policy_version": BASELINE_POLICY_VERSION,
        "freeze_version": freeze_version,
        "max_new_tokens": max_new_tokens,
        "environment": dict(environment or {}),
        "total_samples": total,
        "status_counts": dict(sorted(statuses.items())),
        "compliance": {
            "json_object_rate": _rate(compliance_counts["json_object"], total),
            "semantic_schema_rate": _rate(
                compliance_counts["semantic_schema"], total
            ),
            "semantic_consistency_rate": _rate(
                compliance_counts["semantic_consistency"], total
            ),
            "guardresult_schema_rate": _rate(
                compliance_counts["guardresult_schema"], total
            ),
            "summary_compliance_rate": _rate(
                compliance_counts["summary_compliant"], total
            ),
            "strict_output_rate": _rate(strict_count, total),
            "valid_output_rate": _rate(strict_count, total),
        },
        "risk_metrics": _build_risk_metrics(samples),
        "category_metrics": _build_category_metrics(samples),
        "decision_metrics": _build_decision_metrics(samples),
        "safety_metrics": _build_safety_metrics(samples),
        "performance": _build_performance_metrics(
            samples,
            evaluation_wall_seconds=evaluation_wall_seconds,
        ),
        "samples": samples,
    }
    return report
