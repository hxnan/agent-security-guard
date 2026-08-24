"""Deterministic diagnostics for a completed P4 adapter Eval V1 report."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re

from .p4_adapter_backend import (
    P4_ADAPTER_MODEL_VERSION,
    P4_COMBINED_ADAPTER_MODEL_VERSION,
)
from .p4_adapter_smoke import validate_p4_adapter_artifacts
from .p4_qlora import EXPECTED_P4_COMBINED_SHA256, EXPECTED_P4_SHA256


P4_ADAPTER_EVAL_REPORT_VERSION = "p4-adapter-eval-report-v1"
_ADAPTER_CONTRACTS = {
    "qlora-p4-seed-pilot": {
        "data_version": "p4-seed-v1",
        "dataset_sha256": EXPECTED_P4_SHA256,
        "model_version": P4_ADAPTER_MODEL_VERSION,
    },
    "qlora-p4-seed-targeted-v2": {
        "data_version": "p4-seed-targeted-v2",
        "dataset_sha256": EXPECTED_P4_COMBINED_SHA256,
        "model_version": P4_COMBINED_ADAPTER_MODEL_VERSION,
    },
}
_EXPECTED_LABEL_FIELDS = ("risk", "decision", "severity", "category")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _require_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _require_sample_id(sample: dict[str, object]) -> str:
    sample_id = sample.get("sample_id")
    if not isinstance(sample_id, str) or not sample_id:
        raise ValueError("every report sample must have a non-empty sample_id")
    return sample_id


def _sample_ids(
    samples: list[dict[str, object]],
    predicate,
) -> list[str]:
    return sorted(
        _require_sample_id(sample)
        for sample in samples
        if predicate(sample)
    )


def _weakest_categories(
    category_metrics: dict[str, object],
) -> list[dict[str, object]]:
    support = _require_mapping(category_metrics.get("support"), "category support")
    precision = _require_mapping(
        category_metrics.get("precision"),
        "category precision",
    )
    recall = _require_mapping(category_metrics.get("recall"), "category recall")
    f1 = _require_mapping(category_metrics.get("f1"), "category f1")
    rows = []
    for category, value in f1.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 0 <= value <= 1
        ):
            raise ValueError(f"category f1 for {category} must be between 0 and 1")
        rows.append(
            {
                "category": category,
                "f1": value,
                "precision": precision.get(category),
                "recall": recall.get(category),
                "support": support.get(category),
            }
        )
    return sorted(rows, key=lambda row: (row["f1"], row["category"]))[:5]


def _category_confusions(
    samples: list[dict[str, object]],
) -> tuple[dict[str, dict[str, object]], list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    error_ids = []
    for sample in samples:
        predicted = sample.get("predicted")
        if not isinstance(predicted, dict):
            continue
        expected = _require_mapping(sample.get("expected"), "sample expected")
        expected_category = expected.get("category")
        predicted_category = predicted.get("category")
        if (
            not isinstance(expected_category, str)
            or not isinstance(predicted_category, str)
        ):
            raise ValueError("sample categories must be strings")
        if expected_category == predicted_category:
            continue
        sample_id = _require_sample_id(sample)
        error_ids.append(sample_id)
        grouped[f"{expected_category}->{predicted_category}"].append(sample_id)
    return (
        {
            key: {"count": len(ids), "sample_ids": sorted(ids)}
            for key, ids in sorted(grouped.items())
        },
        sorted(error_ids),
    )


def _unique_in_priority_order(*groups: list[str]) -> list[str]:
    seen = set()
    ordered = []
    for group in groups:
        for sample_id in group:
            if sample_id not in seen:
                seen.add(sample_id)
                ordered.append(sample_id)
    return ordered


def _validate_adapter_provenance(
    provenance: dict[str, object],
) -> dict[str, object]:
    method = provenance.get("method")
    if not isinstance(method, str):
        raise ValueError("adapter_provenance has unexpected method")
    contract = _ADAPTER_CONTRACTS.get(method)
    if contract is None:
        raise ValueError("adapter_provenance has unexpected method")
    expected_fields = {
        "data_version": contract["data_version"],
        "dataset_sha256": contract["dataset_sha256"],
        "method": method,
        "training_prompt_version": "baseline-prompt-v2",
        "training_target": "baseline-semantic-v2",
    }
    for field, expected in expected_fields.items():
        if provenance.get(field) != expected:
            raise ValueError(f"adapter_provenance has unexpected {field}")
    adapter_dir = provenance.get("adapter_dir")
    if not isinstance(adapter_dir, str) or not adapter_dir:
        raise ValueError("adapter_provenance adapter_dir must be a non-empty string")
    base_model_path = provenance.get("base_model_path")
    if not isinstance(base_model_path, str) or not base_model_path:
        raise ValueError(
            "adapter_provenance base_model_path must be a non-empty string"
        )
    hashes = _require_mapping(
        provenance.get("adapter_sha256"),
        "adapter_provenance.adapter_sha256",
    )
    if not hashes:
        raise ValueError("adapter_provenance.adapter_sha256 must not be empty")
    weights = {
        "adapter_model.safetensors",
        "adapter_model.bin",
    }.intersection(hashes)
    if len(weights) != 1:
        raise ValueError(
            "adapter_provenance must contain exactly one adapter model hash"
        )
    for filename, digest in hashes.items():
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError("adapter_provenance contains an unsafe adapter filename")
        if not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
            raise ValueError(
                f"adapter_provenance has an invalid SHA-256 for {filename}"
            )
    return contract


def validate_local_adapter_provenance(
    report: dict[str, object],
) -> dict[str, object]:
    """Validate the complete local pilot artifacts and report provenance."""
    provenance = _require_mapping(
        report.get("adapter_provenance"),
        "report.adapter_provenance",
    )
    _validate_adapter_provenance(provenance)
    adapter_dir = Path(str(provenance["adapter_dir"]))
    manifest = validate_p4_adapter_artifacts(adapter_dir)
    validated = {
        "adapter_dir": str(adapter_dir),
        **{
            field: manifest.get(field)
            for field in (
                "adapter_sha256",
                "base_model_path",
                "data_version",
                "dataset_sha256",
                "method",
                "training_prompt_version",
                "training_target",
            )
        },
    }
    _validate_adapter_provenance(validated)
    if provenance != validated:
        raise ValueError(
            "adapter_provenance does not match the validated training manifest"
        )
    return validated


def _validate_freeze_samples(
    samples: list[dict[str, object]],
    expected_samples: dict[str, dict[str, object]],
) -> None:
    sample_ids = [_require_sample_id(sample) for sample in samples]
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("report contains a duplicate sample_id")
    if set(sample_ids) != set(expected_samples):
        raise ValueError("report sample ID coverage does not match the Eval V1 freeze")
    for sample in samples:
        sample_id = _require_sample_id(sample)
        actual = _require_mapping(sample.get("expected"), "sample expected")
        expected = expected_samples[sample_id]
        for field in _EXPECTED_LABEL_FIELDS:
            if actual.get(field) != expected.get(field):
                raise ValueError(
                    f"{sample_id} expected label {field} does not match the freeze"
                )


def analyze_p4_adapter_report(
    report: dict[str, object],
    *,
    expected_freeze_version: str,
    expected_samples: dict[str, dict[str, object]],
    expected_adapter_provenance: dict[str, object],
) -> dict[str, object]:
    """Extract safety-first error clusters without loading model weights."""
    if report.get("report_version") != P4_ADAPTER_EVAL_REPORT_VERSION:
        raise ValueError("report_version is not p4-adapter-eval-report-v1")
    if report.get("freeze_version") != expected_freeze_version:
        raise ValueError("freeze_version does not match the current Eval V1 freeze")
    provenance = _require_mapping(
        report.get("adapter_provenance"),
        "report.adapter_provenance",
    )
    contract = _validate_adapter_provenance(provenance)
    _validate_adapter_provenance(expected_adapter_provenance)
    if provenance != expected_adapter_provenance:
        raise ValueError("adapter_provenance does not match validated local assets")
    if report.get("model_version") != contract["model_version"]:
        raise ValueError("model_version does not match adapter provenance")
    raw_samples = report.get("samples")
    if not isinstance(raw_samples, list) or not all(
        isinstance(sample, dict) for sample in raw_samples
    ):
        raise ValueError("report.samples must be a list of JSON objects")
    samples: list[dict[str, object]] = raw_samples
    if report.get("total_samples") != len(samples):
        raise ValueError("report total_samples does not match report.samples")
    _validate_freeze_samples(samples, expected_samples)

    high_risk_allow_misses = _sample_ids(
        samples,
        lambda sample: sample.get("high_risk_allow_miss") is True,
    )
    risk_false_negatives = _sample_ids(
        samples,
        lambda sample: (
            isinstance(sample.get("expected"), dict)
            and sample["expected"].get("risk") is True
            and isinstance(sample.get("predicted"), dict)
            and sample["predicted"].get("risk") is False
        ),
    )
    invalid_outputs = _sample_ids(
        samples,
        lambda sample: sample.get("predicted") is None,
    )
    repair_failures = _sample_ids(
        samples,
        lambda sample: (
            sample.get("repair_attempted") is True
            and sample.get("repair_succeeded") is not True
        ),
    )
    benign_false_positives = _sample_ids(
        samples,
        lambda sample: (
            isinstance(sample.get("expected"), dict)
            and sample["expected"].get("category") == "benign"
            and sample.get("effective_decision") != "allow"
        ),
    )
    decision_errors = _sample_ids(
        samples,
        lambda sample: sample.get("effective_decision_correct") is False,
    )
    category_confusions, category_errors = _category_confusions(samples)
    category_metrics = _require_mapping(
        report.get("category_metrics"),
        "report.category_metrics",
    )
    priority_ids = _unique_in_priority_order(
        high_risk_allow_misses,
        risk_false_negatives,
        invalid_outputs,
        repair_failures,
        benign_false_positives,
        decision_errors,
        category_errors,
    )
    return {
        "status": "ok",
        "total_samples": len(samples),
        "high_risk_allow_miss_sample_ids": high_risk_allow_misses,
        "risk_false_negative_sample_ids": risk_false_negatives,
        "invalid_output_sample_ids": invalid_outputs,
        "repair_failure_sample_ids": repair_failures,
        "benign_false_positive_sample_ids": benign_false_positives,
        "effective_decision_error_sample_ids": decision_errors,
        "category_error_sample_ids": category_errors,
        "category_confusions": category_confusions,
        "weakest_categories": _weakest_categories(category_metrics),
        "target_priority_sample_ids": priority_ids,
    }
