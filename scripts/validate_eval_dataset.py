#!/usr/bin/env python3
"""Validate Eval V1 gold data in draft or frozen mode."""

import argparse
import json
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from guard.eval_blueprint import BlueprintValidationError, load_blueprint
from guard.eval_dataset import (
    EvalDatasetValidationError,
    build_eval_dataset_stats,
    load_eval_dataset,
    validate_against_blueprint,
    validate_eval_dataset,
)

DEFAULT_DATASET = REPOSITORY_ROOT / "data" / "eval-v1" / "gold"
DEFAULT_BLUEPRINT = REPOSITORY_ROOT / "data" / "eval-v1" / "blueprint.jsonl"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--blueprint", type=Path, default=DEFAULT_BLUEPRINT)
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--require-frozen", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        records = load_eval_dataset(args.dataset)
        validate_eval_dataset(
            records,
            require_complete=args.require_complete,
            require_frozen=args.require_frozen,
        )
        blueprint = load_blueprint(args.blueprint)
        validate_against_blueprint(records, blueprint)
    except (EvalDatasetValidationError, BlueprintValidationError, OSError) as exc:
        print(
            json.dumps(
                {"status": "error", "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "status": "ok",
                "require_complete": args.require_complete,
                "require_frozen": args.require_frozen,
                "stats": build_eval_dataset_stats(records),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
