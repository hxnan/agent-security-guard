"""Reusable loading and validation for the Eval V1 technical freeze."""

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path

from .eval_adjudication import load_adjudications, resolve_reviewed_dataset
from .eval_blueprint import load_blueprint
from .eval_dataset import EvalGoldRecord, load_eval_dataset, validate_against_blueprint, validate_eval_dataset
from .eval_review import compare_review_answers, load_review_answers


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
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
    """Raised when freeze provenance is not safe to use as a technical freeze."""


@dataclass(frozen=True)
class EvalFreezeBundle:
    """Resolved Eval V1 records plus immutable freeze provenance."""

    records: list[EvalGoldRecord]
    manifest: dict[str, object]
    substantive_disagreements: int
    adjudication_counts: dict[str, int]


def load_freeze_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, object]:
    """Load and validate the technical-freeze provenance manifest."""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvalFreezeValidationError(
            f"invalid freeze manifest JSON: {exc.msg}"
        ) from exc
    if not isinstance(manifest, dict):
        raise EvalFreezeValidationError("freeze manifest must be a JSON object")
    if manifest.get("status") != "technical-frozen":
        raise EvalFreezeValidationError(
            "freeze manifest status must be technical-frozen"
        )
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


def load_resolved_eval_v1(
    *,
    dataset_path: Path = DEFAULT_DATASET,
    review_path: Path = DEFAULT_REVIEW,
    adjudication_path: Path = DEFAULT_ADJUDICATIONS,
    blueprint_path: Path = DEFAULT_BLUEPRINT,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> EvalFreezeBundle:
    """Resolve and validate the complete 100-record Eval V1 technical freeze."""
    manifest = load_freeze_manifest(manifest_path)
    gold_records = load_eval_dataset(dataset_path)
    review_answers = load_review_answers(review_path)
    adjudications = load_adjudications(adjudication_path)
    blueprint = load_blueprint(blueprint_path)

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

    adjudication_counts = dict(
        sorted(Counter(row.resolution for row in adjudications).items())
    )
    return EvalFreezeBundle(
        records=resolved,
        manifest=manifest,
        substantive_disagreements=substantive_disagreements,
        adjudication_counts=adjudication_counts,
    )
