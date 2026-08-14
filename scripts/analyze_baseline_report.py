#!/usr/bin/env python3
"""Summarize structural failures in an existing baseline evaluation report."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from guard.baseline_prompt import BASELINE_MODEL_VERSION, BASELINE_POLICY_VERSION
from guard.contracts import GuardResult
from guard.result_parsing import GUARD_RESULT_FIELDS, GeneratedResultError, extract_first_json_object


DEFAULT_REPORT = REPOSITORY_ROOT / "artifacts" / "baseline-eval-v1" / "report.json"
TRUSTED_PROVENANCE_FIELDS = {"model_version", "policy_version"}


def _type_name(value: object) -> str:
    if isinstance(value, bool):
        return "bool"
    if value is None:
        return "null"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def _sorted_nested_counts(values: dict[str, Counter]) -> dict[str, dict[str, int]]:
    return {
        field: dict(sorted(counter.items()))
        for field, counter in sorted(values.items())
    }


def _valid_after_provenance_injection(value: dict[str, object]) -> bool:
    candidate = dict(value)
    candidate.setdefault("model_version", BASELINE_MODEL_VERSION)
    candidate.setdefault("policy_version", BASELINE_POLICY_VERSION)
    try:
        result = GuardResult.model_validate(candidate)
    except ValueError:
        return False
    return (
        result.model_version == BASELINE_MODEL_VERSION
        and result.policy_version == BASELINE_POLICY_VERSION
        and result.rule_hits == []
    )


def analyze_report(report: dict[str, object]) -> dict[str, object]:
    samples = report.get("samples")
    if not isinstance(samples, list):
        raise ValueError("report.samples must be a list")

    expected_fields = set(GUARD_RESULT_FIELDS)
    error_counts = Counter()
    missing_field_sets = Counter()
    extra_field_sets = Counter()
    field_type_counts: dict[str, Counter] = defaultdict(Counter)
    field_presence_counts = Counter()
    risk_string_values = Counter()
    confidence_string_values = Counter()
    json_object_count = 0
    code_fence_count = 0
    provenance_only_missing_count = 0
    valid_after_provenance_injection_count = 0

    for sample in samples:
        if not isinstance(sample, dict):
            continue
        error = sample.get("error")
        if isinstance(error, str) and error:
            error_counts[error] += 1
        raw_text = sample.get("raw_text")
        if not isinstance(raw_text, str):
            continue
        if "```" in raw_text:
            code_fence_count += 1
        try:
            value = extract_first_json_object(raw_text)
        except GeneratedResultError:
            continue

        json_object_count += 1
        actual_fields = set(value)
        missing = sorted(expected_fields - actual_fields)
        extra = sorted(actual_fields - expected_fields)
        if missing:
            missing_field_sets[",".join(missing)] += 1
        if extra:
            extra_field_sets[",".join(extra)] += 1

        if missing and set(missing).issubset(TRUSTED_PROVENANCE_FIELDS) and not extra:
            provenance_only_missing_count += 1
        if _valid_after_provenance_injection(value):
            valid_after_provenance_injection_count += 1

        for field, field_value in value.items():
            field_presence_counts[field] += 1
            field_type_counts[field][_type_name(field_value)] += 1
        risk_value = value.get("risk")
        if isinstance(risk_value, str):
            risk_string_values[risk_value] += 1
        confidence_value = value.get("confidence")
        if isinstance(confidence_value, str):
            confidence_string_values[confidence_value] += 1

    total_samples = report.get("total_samples", len(samples))
    return {
        "total_samples": total_samples,
        "status_counts": report.get("status_counts", {}),
        "error_counts": dict(sorted(error_counts.items())),
        "json_object_count": json_object_count,
        "json_object_rate": json_object_count / len(samples) if samples else 0.0,
        "code_fence_count": code_fence_count,
        "code_fence_rate": code_fence_count / len(samples) if samples else 0.0,
        "missing_field_sets": dict(sorted(missing_field_sets.items())),
        "extra_field_sets": dict(sorted(extra_field_sets.items())),
        "field_presence_counts": dict(sorted(field_presence_counts.items())),
        "field_type_counts": _sorted_nested_counts(field_type_counts),
        "risk_string_values": dict(sorted(risk_string_values.items())),
        "confidence_string_values": dict(sorted(confidence_string_values.items())),
        "provenance_only_missing_count": provenance_only_missing_count,
        "valid_after_provenance_injection_count": valid_after_provenance_injection_count,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("report root must be a JSON object")
        diagnostics = analyze_report(report)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        _emit({"status": "error", "error": str(exc)})
        return 2
    _emit(diagnostics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
