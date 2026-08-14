"""Shared extraction and strict validation for generated GuardResult objects."""

import json

from .contracts import GuardResult


GUARD_RESULT_FIELDS = (
    "schema_version",
    "risk",
    "decision",
    "severity",
    "category",
    "summary",
    "confidence",
    "evidence",
    "rule_hits",
    "model_version",
    "policy_version",
)


class GeneratedResultError(ValueError):
    """Raised when generated text cannot be accepted as a GuardResult."""


def extract_first_json_object(text: str) -> dict[str, object]:
    """Return the first decodable JSON object found in generated text."""
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise GeneratedResultError("generated text does not contain a valid JSON object")


def parse_guard_result(
    text: str,
    *,
    expected_model_version: str | None = None,
    expected_policy_version: str | None = None,
    require_empty_rule_hits: bool = False,
) -> GuardResult:
    """Extract and strictly validate one generated GuardResult object."""
    value = extract_first_json_object(text)
    expected_fields = set(GUARD_RESULT_FIELDS)
    actual_fields = set(value)
    missing = sorted(expected_fields - actual_fields)
    extra = sorted(actual_fields - expected_fields)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing fields: {missing}")
        if extra:
            details.append(f"extra fields: {extra}")
        raise GeneratedResultError("generated GuardResult field mismatch: " + "; ".join(details))

    try:
        result = GuardResult.model_validate(value)
    except ValueError as exc:
        raise GeneratedResultError(
            f"generated JSON is not a valid GuardResult: {exc}"
        ) from exc

    if expected_model_version is not None and result.model_version != expected_model_version:
        raise GeneratedResultError(
            "generated GuardResult model_version mismatch: "
            f"expected {expected_model_version!r}, got {result.model_version!r}"
        )
    if expected_policy_version is not None and result.policy_version != expected_policy_version:
        raise GeneratedResultError(
            "generated GuardResult policy_version mismatch: "
            f"expected {expected_policy_version!r}, got {result.policy_version!r}"
        )
    if require_empty_rule_hits and result.rule_hits:
        raise GeneratedResultError(
            "generated GuardResult rule_hits must be empty for model-only baseline"
        )
    return result
