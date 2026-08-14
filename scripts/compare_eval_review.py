#!/usr/bin/env python3
"""Compare independent Eval V1 reviewer answers with the committed Gold Draft."""

import argparse
import json
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from guard.eval_dataset import EvalDatasetValidationError, load_eval_dataset, validate_eval_dataset
from guard.eval_review import (
    EvalReviewValidationError,
    compare_review_answers,
    load_review_answers,
)


DEFAULT_DATASET = REPOSITORY_ROOT / "data" / "eval-v1" / "gold"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--answers", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        records = load_eval_dataset(args.dataset)
        validate_eval_dataset(records)
        answers = load_review_answers(args.answers)
        disagreements = compare_review_answers(records, answers)
    except (EvalDatasetValidationError, EvalReviewValidationError, OSError) as exc:
        print(
            json.dumps(
                {"status": "error", "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1

    payload = {
        "status": "disputed" if disagreements else "agreed",
        "compared": len(answers),
        "disagreements": [
            item.model_dump(mode="json") for item in disagreements
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 3 if disagreements else 0


if __name__ == "__main__":
    raise SystemExit(main())
