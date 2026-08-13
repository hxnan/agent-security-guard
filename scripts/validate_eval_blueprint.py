#!/usr/bin/env python3
"""Validate the committed Eval V1 sample blueprint."""

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from guard.eval_blueprint import (
    BlueprintValidationError,
    load_blueprint,
    validate_blueprint,
)


DEFAULT_BLUEPRINT_PATH = REPOSITORY_ROOT / "data" / "eval-v1" / "blueprint.jsonl"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_BLUEPRINT_PATH)
    args = parser.parse_args(argv)

    try:
        summary = validate_blueprint(load_blueprint(args.path))
    except BlueprintValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (OSError, UnicodeError) as exc:
        print(f"unable to read blueprint {args.path}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
