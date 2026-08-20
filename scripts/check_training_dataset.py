from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from training.data_quality import (
    DatasetQualityError,
    load_eval_request_fingerprints,
    load_training_jsonl,
    validate_dataset_bundle,
)


DEFAULT_EVAL_DIR = REPOSITORY_ROOT / "data" / "eval-v1" / "gold"


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise DatasetQualityError(f"argument error: {message}")


def main() -> int:
    parser = JsonArgumentParser(
        description="Validate isolated P4 train and validation JSONL files"
    )
    parser.add_argument("--train", required=True)
    parser.add_argument("--validation", required=True)
    parser.add_argument("--eval-dir", default=str(DEFAULT_EVAL_DIR))
    train = []
    validation = []
    try:
        args = parser.parse_args()
        train = load_training_jsonl(args.train, expected_split="train")
        validation = load_training_jsonl(
            args.validation, expected_split="validation"
        )
        eval_fingerprints = load_eval_request_fingerprints(args.eval_dir)
        result = validate_dataset_bundle(
            train, validation, eval_fingerprints
        ).to_dict()
    except DatasetQualityError as exc:
        train_summary = validate_dataset_bundle(train, [], set()).train
        validation_summary = validate_dataset_bundle([], validation, set()).validation
        result = {
            "status": "failed",
            "train": train_summary,
            "validation": validation_summary,
            "errors": [str(exc)],
        }

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
