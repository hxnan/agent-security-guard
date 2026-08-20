"""Metrics helpers for GuardResult V2 baseline evaluation.

The evaluator separates output contract quality from model semantic quality.
"""

from __future__ import annotations

from collections import Counter


REQUIRED_FIELDS = {
    "decision",
    "risk_level",
    "category",
    "summary",
    "confidence",
    "provenance",
}


def schema_pass_rate(results: list[dict]) -> float:
    if not results:
        return 0.0
    passed = sum(REQUIRED_FIELDS.issubset(item.keys()) for item in results)
    return passed / len(results)


def decision_distribution(results: list[dict]) -> dict[str, int]:
    return dict(Counter(item.get("decision", "missing") for item in results))


def confidence_average(results: list[dict]) -> float:
    values = [item["confidence"] for item in results if isinstance(item.get("confidence"), (int, float))]
    return sum(values) / len(values) if values else 0.0
