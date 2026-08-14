#!/usr/bin/env python3
"""Resolve and validate the committed Eval V1 independent-agent technical freeze."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from guard.eval_adjudication import (
    EvalAdjudicationValidationError,
    load_adjudications,
    resolve_reviewed_dataset,
)
from guard.eval_blueprint import load_blueprint
from guard.eval_dataset import (
    EvalDatasetValidationError,
    build_eval_dataset_stats,
    load_eval_dataset,
    validate_against_blueprint,
    validate_eval_dataset,
)
from guard.eval_review import (
    EvalReviewValidationError,
    compare_review_answers,
    load_review_answers,
)


DEFAULT_DATASET = REPOSITORY_ROOT / "data" / "eval-v1" / "gold"
DEFAULT_REVIEW = (
    REPOSITORY_ROOT
    / "data"
    / "eval-v1"
    / "reviews"
    / "agent-blind-review-2026-08-14.jsonl"
)
DEFAULT_ADJUDICATIONS = (
    REPOSITORY_ROOT
    / "data"
    / "eval-v1"
    / "reviews"
    / "adjudication-2026-08-14.jsonl"
)
DEFAULT_BLUEPRINT = REPOSITORY_ROOT / "data" / "eval-v1" / "blueprint.jsonl"
DEFAULT_MANIFEST = REPOSITORY_ROOT / "data" / "eval-v1" / "freeze-manifest.json"


class EvalFreezeValidationError(ValueError):
    """Raised when freeze provenance is not safe to treat as a technical freeze."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--adjudications", type=Path, default=DEFAULT_ADJUDICATIONS)
    parser.add_argument("--blueprint", type=Path, default=DEFAULT_BLUEPRINT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser


def _load_manifest(path: Path) -> dict[str, object]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvalFreezeValidationError(f"invalid freeze manifest JSON: {exc.msg}") from exc
    if not isinstance(manifest, dict):
        raise EvalFreezeValidationError("freeze manifest must be a JSON object")
    if manifest.get("status") != "technical-frozen":
        raise EvalFreezeValidationError("freeze manifest status must be technical-frozen")
    if manifest.get("human_reviewed") is not False:
        raise EvalFreezeValidationError(
            "freeze manifest human_reviewed must be false for independent-agent review"
        )
    if manifest.get("reviewer_type") != "independent-agent":
        raise EvalFreezeValidationError(
            "freeze manifest reviewer_type must be independent-agent"
        )
    reviewer_id = manifest.get("resolved_reviewer_id")
    if not isinstance(reviewer_id, str) or not reviewer_id.strip():
        raise EvalFreezeValidationError(
            "freeze manifest resolved_reviewer_id must be a non-empty string"
        )
    freeze_version = manifest.get("freeze_version")
    if not isinstance(freeze_version, str) or not freeze_version.strip():
        raise EvalFreezeValidationError(
            "freeze manifest freeze_version must be a non-empty string"
        )
    return manifest


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = _load_manifest(args.manifest)
        gold_records = load_eval_dataset(args.dataset)
        review_answers = load_review_answers(args.review)
        adjudications = load_adjudications(args.adjudications)
        blueprint = load_blueprint(args.blueprint)

        comparisons = compare_review_answers(gold_records, review_answers)
        substantive_disagreements = sum(
            1 for item in comparisons if item.label_differences
        )
        resolved = resolve_reviewed_dataset(
            gold_records,
            review_answers,
            adjudications,
            reviewer_id=str(manifest["resolved_reviewer_id"]),
        )
        validate_eval_dataset(
            resolved,
            require_complete=True,
            require_frozen=True,
        )
        validate_against_blueprint(resolved, blueprint)
    except (
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

    adjudication_counts = dict(
        sorted(Counter(row.resolution for row in adjudications).items())
    )
    payload = {
        "status": "ok",
        "freeze_version": manifest["freeze_version"],
        "technical_freeze": True,
        "human_reviewed": False,
        "substantive_disagreements": substantive_disagreements,
        "adjudications": adjudication_counts,
        "stats": build_eval_dataset_stats(resolved),
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
