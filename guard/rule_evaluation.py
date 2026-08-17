"""CPU-only evaluation for deterministic security rules."""

from collections import Counter
import json
from pathlib import Path
from typing import Sequence

from .eval_dataset import EvalGoldRecord
from .rules import (
    RULE_ENGINE_VERSION,
    RULES_POLICY_VERSION,
    RuleEngine,
    build_rule_guard_result,
)
from .taxonomy import Decision, RiskCategory, Severity


RULE_EVAL_REPORT_VERSION = "rules-eval-report-v1"


def _rate(count: int | float, total: int | float) -> float:
    return count / total if total else 0.0


def evaluate_rules(
    records: Sequence[EvalGoldRecord],
    engine: RuleEngine,
    *,
    freeze_version: str,
) -> dict[str, object]:
    """Evaluate deterministic rules without importing or invoking any model."""
    samples: list[dict[str, object]] = []
    per_rule_hits: Counter[str] = Counter()
    per_rule_correct: Counter[str] = Counter()
    per_rule_incorrect: Counter[str] = Counter()
    decisive_count = 0
    benign_rule_count = 0
    dangerous_rule_count = 0
    decision_correct_count = 0
    category_correct_count = 0
    rule_error_count = 0
    false_benign_allow_ids: list[str] = []
    high_or_critical_allow_miss_ids: list[str] = []

    for gold in records:
        evaluation = engine.evaluate(gold.request)
        if evaluation.errors:
            rule_error_count += 1
        for rule_match in evaluation.matches:
            per_rule_hits[rule_match.rule_id] += 1

        expected = gold.expected
        selected = evaluation.selected
        if selected is None:
            predicted = None
            effective_decision = Decision.REVIEW
            decision_correct = None
            category_correct = None
        else:
            decisive_count += 1
            result = build_rule_guard_result(
                evaluation,
                policy_version=RULES_POLICY_VERSION,
            )
            predicted = result.model_dump(mode="json")
            effective_decision = result.decision
            decision_correct = result.decision is expected.decision
            category_correct = result.category is expected.category
            decision_correct_count += int(decision_correct)
            category_correct_count += int(category_correct)
            if result.category is RiskCategory.BENIGN:
                benign_rule_count += 1
            else:
                dangerous_rule_count += 1

            selected_correct = decision_correct and category_correct
            if selected_correct:
                per_rule_correct[selected.rule_id] += 1
            else:
                per_rule_incorrect[selected.rule_id] += 1

            if result.category is RiskCategory.BENIGN and expected.risk:
                false_benign_allow_ids.append(gold.sample_id)

        if (
            expected.risk
            and expected.severity in {Severity.HIGH, Severity.CRITICAL}
            and effective_decision is Decision.ALLOW
        ):
            high_or_critical_allow_miss_ids.append(gold.sample_id)

        samples.append(
            {
                "sample_id": gold.sample_id,
                "expected": {
                    "risk": expected.risk,
                    "decision": expected.decision.value,
                    "severity": expected.severity.value,
                    "category": expected.category.value,
                },
                "matched_rule_ids": [
                    rule_match.rule_id for rule_match in evaluation.matches
                ],
                "selected_rule_id": selected.rule_id if selected is not None else None,
                "rule_errors": list(evaluation.errors),
                "predicted": predicted,
                "effective_decision": effective_decision.value,
                "decision_correct": decision_correct,
                "category_correct": category_correct,
            }
        )

    total = len(records)
    abstain_count = total - decisive_count
    return {
        "report_version": RULE_EVAL_REPORT_VERSION,
        "rule_engine_version": RULE_ENGINE_VERSION,
        "policy_version": RULES_POLICY_VERSION,
        "freeze_version": freeze_version,
        "total_samples": total,
        "decisive_count": decisive_count,
        "decisive_rate": _rate(decisive_count, total),
        "abstain_count": abstain_count,
        "abstain_rate": _rate(abstain_count, total),
        "benign_rule_count": benign_rule_count,
        "benign_rule_rate": _rate(benign_rule_count, total),
        "dangerous_rule_count": dangerous_rule_count,
        "dangerous_rule_rate": _rate(dangerous_rule_count, total),
        "rule_error_count": rule_error_count,
        "rule_error_rate": _rate(rule_error_count, total),
        "decision_accuracy_decisive": _rate(
            decision_correct_count, decisive_count
        ),
        "category_accuracy_decisive": _rate(
            category_correct_count, decisive_count
        ),
        "false_benign_allow_count": len(false_benign_allow_ids),
        "false_benign_allow_ids": false_benign_allow_ids,
        "high_or_critical_allow_miss_count": len(
            high_or_critical_allow_miss_ids
        ),
        "high_or_critical_allow_miss_ids": high_or_critical_allow_miss_ids,
        "per_rule_hits": dict(sorted(per_rule_hits.items())),
        "per_rule_correct": dict(sorted(per_rule_correct.items())),
        "per_rule_incorrect": dict(sorted(per_rule_incorrect.items())),
        "samples": samples,
    }


def write_rule_evaluation_report(path: Path, report: dict[str, object]) -> None:
    """Atomically write a deterministic UTF-8 Rules-only report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
