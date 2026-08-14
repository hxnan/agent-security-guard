#!/usr/bin/env python3
"""Print deterministic statistics for Eval V1 gold data."""

import argparse
import json
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from guard.eval_dataset import (
    EvalDatasetValidationError,
    build_eval_dataset_stats,
    load_eval_dataset,
    validate_eval_dataset,
)

DEFAULT_DATASET = REPOSITORY_ROOT / "data" / "eval-v1" / "gold.jsonl"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        records = load_eval_dataset(args.dataset)
        validate_eval_dataset(records)
    except (EvalDatasetValidationError, OSError) as exc:
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
            build_eval_dataset_stats(records),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
