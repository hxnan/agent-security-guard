#!/usr/bin/env python3
"""Export request-only Eval V1 JSONL for independent blind review."""

import argparse
import json
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from guard.eval_dataset import EvalDatasetValidationError, load_eval_dataset, validate_eval_dataset
from guard.eval_review import build_blind_review_packet


DEFAULT_DATASET = REPOSITORY_ROOT / "data" / "eval-v1" / "gold"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        records = load_eval_dataset(args.dataset)
        validate_eval_dataset(records)
        packet = build_blind_review_packet(records)
    except (EvalDatasetValidationError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1

    text = "".join(
        json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
        for record in packet
    )
    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
