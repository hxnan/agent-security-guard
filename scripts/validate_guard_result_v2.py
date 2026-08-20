"""Validate model outputs against the GuardResult V2 contract.

This utility intentionally validates structure only. It does not grant execution
permission; policy fusion remains the authority for allow/review/block decisions.
"""

from __future__ import annotations

import json
from pathlib import Path


REQUIRED_FIELDS = {
    "decision",
    "risk_level",
    "category",
    "summary",
    "confidence",
    "provenance",
}


def validate_result(result: dict) -> list[str]:
    errors: list[str] = []
    missing = REQUIRED_FIELDS - result.keys()
    if missing:
        errors.append(f"missing fields: {sorted(missing)}")

    provenance = result.get("provenance", {})
    if isinstance(provenance, dict):
        for key in ("model_version", "policy_version"):
            if not provenance.get(key):
                errors.append(f"missing provenance.{key}")

    confidence = result.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        errors.append("confidence must be a number between 0 and 1")

    return errors


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("result_json")
    args = parser.parse_args()

    result = json.loads(Path(args.result_json).read_text())
    errors = validate_result(result)
    if errors:
        raise SystemExit("\n".join(errors))
    print("GUARD_RESULT_V2_OK")


if __name__ == "__main__":
    main()
