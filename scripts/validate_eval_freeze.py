#!/usr/bin/env python3
"""Resolve and validate the committed Eval V1 independent-agent technical freeze."""

import argparse
import json
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from guard.eval_adjudication import EvalAdjudicationValidationError
from guard.eval_blueprint import BlueprintValidationError
from guard.eval_dataset import EvalDatasetValidationError, build_eval_dataset_stats
from guard.eval_freeze import (
    DEFAULT_ADJUDICATIONS,
    DEFAULT_BLUEPRINT,
    DEFAULT_DATASET,
    DEFAULT_MANIFEST,
    DEFAULT_REVIEW,
    EvalFreezeValidationError,
    load_resolved_eval_v1,
)
from guard.eval_review import EvalReviewValidationError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--adjudications", type=Path, default=DEFAULT_ADJUDICATIONS)
    parser.add_argument("--blueprint", type=Path, default=DEFAULT_BLUEPRINT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        bundle = load_resolved_eval_v1(
            dataset_path=args.dataset,
            review_path=args.review,
            adjudication_path=args.adjudications,
            blueprint_path=args.blueprint,
            manifest_path=args.manifest,
        )
    except (
        BlueprintValidationError,
        EvalAdjudicationValidationError,
        EvalDatasetValidationError,
        EvalFreezeValidationError,
        EvalReviewValidationError,
        OSError,
    ) as exc:
        print(
            json.dumps(
                {"status": "error", "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1

    payload = {
        "status": "ok",
        "freeze_version": bundle.manifest["freeze_version"],
        "technical_freeze": True,
        "human_reviewed": False,
        "substantive_disagreements": bundle.substantive_disagreements,
        "adjudications": bundle.adjudication_counts,
        "stats": build_eval_dataset_stats(bundle.records),
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
