"""Quality checks for Agent Security Guard training datasets."""

from collections import Counter
from typing import Any

REQUIRED_OUTPUT_FIELDS = {
    "risk",
    "decision",
    "severity",
    "category",
    "summary",
    "confidence",
}

FORBIDDEN_MARKERS = {
    "EV001",
    "EV002",
    "eval-v1",
    "gold",
}


class DatasetQualityError(ValueError):
    pass


def validate_sample(sample: dict[str, Any]) -> None:
    output = sample.get("output")
    if not isinstance(output, dict):
        raise DatasetQualityError("missing output")

    missing = REQUIRED_OUTPUT_FIELDS - set(output)
    if missing:
        raise DatasetQualityError(f"missing output fields: {sorted(missing)}")

    category = output["category"]
    decision = output["decision"]
    if category == "benign" and decision != "allow":
        raise DatasetQualityError("benign samples must allow")

    if category != "benign" and decision == "allow":
        raise DatasetQualityError("risky samples cannot allow")


def scan_contamination(sample: dict[str, Any]) -> list[str]:
    text = str(sample)
    return [marker for marker in FORBIDDEN_MARKERS if marker in text]


def summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    categories = Counter(
        item.get("output", {}).get("category", "unknown") for item in samples
    )
    return {
        "samples": len(samples),
        "categories": dict(categories),
    }
