"""Strict structural validation for the GuardResult V2 model signal."""

from __future__ import annotations

from typing import Any


DECISIONS = ("allow", "review", "block")
RISK_LEVELS = ("none", "low", "medium", "high", "critical")
REQUIRED_FIELDS = {
    "decision",
    "risk_level",
    "category",
    "summary",
    "confidence",
    "provenance",
}


def validate_result(result: Any) -> list[str]:
    """Return deterministic contract errors for a model-produced V2 result."""

    if not isinstance(result, dict):
        return ["result must be an object"]

    errors: list[str] = []
    missing = REQUIRED_FIELDS - result.keys()
    if missing:
        errors.append(f"missing fields: {sorted(missing)}")

    if "decision" in result and result["decision"] not in DECISIONS:
        errors.append("decision must be one of: allow, review, block")

    if "risk_level" in result and result["risk_level"] not in RISK_LEVELS:
        errors.append(
            "risk_level must be one of: none, low, medium, high, critical"
        )

    for field in ("category", "summary"):
        if field in result and not isinstance(result[field], str):
            errors.append(f"{field} must be a string")

    confidence = result.get("confidence")
    if "confidence" in result and (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        errors.append("confidence must be a number between 0 and 1")

    if "provenance" in result:
        provenance = result["provenance"]
        if not isinstance(provenance, dict):
            errors.append("provenance must be an object")
        else:
            for key in ("model_version", "policy_version"):
                if not isinstance(provenance.get(key), str) or not provenance[key]:
                    errors.append(f"missing provenance.{key}")

    return errors
