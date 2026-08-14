"""CPU-testable evaluation loop for the model-only security baseline."""

from collections import Counter
from typing import Protocol, Sequence

from .baseline_predictor import BaselinePredictionOutcome, PredictionStatus
from .baseline_prompt import (
    BASELINE_MODEL_VERSION,
    BASELINE_POLICY_VERSION,
    BASELINE_PROMPT_VERSION,
)
from .eval_dataset import EvalGoldRecord
from .result_parsing import GeneratedResultError, extract_first_json_object, parse_guard_result
from .taxonomy import Decision, Severity


BASELINE_EVAL_REPORT_VERSION = "baseline-eval-report-v1"


class PredictorProtocol(Protocol):
    def predict(self, request) -> BaselinePredictionOutcome: ...


def _rate(count: int, total: int) -> float:
    return count / total if total else 0.0


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
        parse_guard_result(outcome.raw_text)
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
            "guardresult_schema_rate": _rate(
                compliance_counts["guardresult_schema"], total
            ),
            "summary_compliance_rate": _rate(
                compliance_counts["summary_compliant"], total
            ),
            "strict_output_rate": _rate(strict_count, total),
            "valid_output_rate": _rate(strict_count, total),
        },
        "samples": samples,
    }
    return report
