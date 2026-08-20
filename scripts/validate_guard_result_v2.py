"""Validate model outputs against the GuardResult V2 contract.

This utility intentionally validates structure only. It does not grant execution
permission; policy fusion remains the authority for allow/review/block decisions.
"""

from __future__ import annotations

import json
from pathlib import Path

from guard.result_v2 import validate_result


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
