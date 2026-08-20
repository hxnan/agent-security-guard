"""Metrics helpers for GuardResult V2 baseline evaluation.

The evaluator separates output contract quality from model semantic quality.
"""

from __future__ import annotations

from collections import Counter

from guard.result_v2 import DECISIONS, validate_result


def schema_pass_rate(results: list[object]) -> float:
    if not results:
        return 0.0
    passed = sum(not validate_result(item) for item in results)
    return passed / len(results)


def schema_error_distribution(results: list[object]) -> dict[str, int]:
    errors = Counter(
        error
        for result in results
        for error in validate_result(result)
    )
    return dict(errors)


def decision_distribution(results: list[object]) -> dict[str, int]:
    buckets = []
    for item in results:
        if not isinstance(item, dict) or "decision" not in item:
            buckets.append("missing")
        elif item["decision"] in DECISIONS:
            buckets.append(item["decision"])
        else:
            buckets.append("invalid")
    return dict(Counter(buckets))


def confidence_average(results: list[object]) -> float:
    values = [
        item["confidence"]
        for item in results
        if isinstance(item, dict)
        and not isinstance(item.get("confidence"), bool)
        and isinstance(item.get("confidence"), (int, float))
        and 0 <= item["confidence"] <= 1
    ]
    return sum(values) / len(values) if values else 0.0
