"""Deterministic adjudication for an independent Eval V1 review."""

import json
from pathlib import Path
from typing import Literal, Sequence

from pydantic import BaseModel, Field, ValidationError

from .contracts import GuardResult
from .eval_dataset import (
    EvalGoldRecord,
    ReviewStatus,
    validate_record_consistency,
)
from .eval_review import EvalReviewAnswer
from .taxonomy import RiskCategory


_LABEL_FIELDS = ("decision", "severity", "category")


class EvalAdjudicationValidationError(ValueError):
    """Raised when an adjudication ledger cannot resolve the review safely."""


class EvalAdjudicationRecord(BaseModel):
    """Explicit resolution for one substantive Gold/reviewer disagreement."""

    sample_id: str = Field(pattern=r"^EV[0-9]{3}$")
    resolution: Literal["gold", "review"]
    note: str = Field(min_length=1)
    override_reason: str | None = None


def load_adjudications(path: Path) -> list[EvalAdjudicationRecord]:
    """Load a versioned adjudication JSONL ledger."""
    rows: list[EvalAdjudicationRecord] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as adjudication_file:
        for line_number, line in enumerate(adjudication_file, start=1):
            if not line.strip():
                raise EvalAdjudicationValidationError(
                    f"line {line_number}: blank lines are not allowed"
                )
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvalAdjudicationValidationError(
                    f"line {line_number}: invalid JSON: {exc.msg}"
                ) from exc
            try:
                row = EvalAdjudicationRecord.model_validate(value)
            except ValidationError as exc:
                raise EvalAdjudicationValidationError(
                    f"line {line_number}: invalid adjudication: {exc}"
                ) from exc
            if row.sample_id in seen:
                raise EvalAdjudicationValidationError(
                    f"duplicate adjudication for {row.sample_id}"
                )
            seen.add(row.sample_id)
            rows.append(row)
    return rows


def _label_differences(
    gold: EvalGoldRecord,
    review: EvalReviewAnswer,
) -> list[str]:
    return [
        field
        for field in _LABEL_FIELDS
        if getattr(gold.expected, field) != getattr(review, field)
    ]


def _review_result(gold: EvalGoldRecord, review: EvalReviewAnswer) -> GuardResult:
    payload = gold.expected.model_dump(mode="python")
    payload.update(
        {
            "risk": review.category is not RiskCategory.BENIGN,
            "decision": review.decision,
            "severity": review.severity,
            "category": review.category,
            "summary": review.summary,
            "confidence": review.confidence,
            "evidence": list(review.evidence),
        }
    )
    return GuardResult.model_validate(payload)


def resolve_reviewed_dataset(
    gold_records: Sequence[EvalGoldRecord],
    review_answers: Sequence[EvalReviewAnswer],
    adjudications: Sequence[EvalAdjudicationRecord],
    *,
    reviewer_id: str,
) -> list[EvalGoldRecord]:
    """Resolve blind-review labels without mutating raw Gold or reviewer evidence."""
    if not reviewer_id.strip():
        raise EvalAdjudicationValidationError("reviewer_id must not be blank")

    gold_ids = [record.sample_id for record in gold_records]
    review_ids = [answer.sample_id for answer in review_answers]
    if len(review_ids) != len(set(review_ids)) or set(review_ids) != set(gold_ids):
        raise EvalAdjudicationValidationError(
            "review answers must exactly cover all Gold sample IDs once"
        )

    adjudication_by_id: dict[str, EvalAdjudicationRecord] = {}
    for adjudication in adjudications:
        if adjudication.sample_id in adjudication_by_id:
            raise EvalAdjudicationValidationError(
                f"duplicate adjudication for {adjudication.sample_id}"
            )
        adjudication_by_id[adjudication.sample_id] = adjudication

    review_by_id = {answer.sample_id: answer for answer in review_answers}
    resolved_records: list[EvalGoldRecord] = []
    used_adjudications: set[str] = set()

    for gold in gold_records:
        review = review_by_id[gold.sample_id]
        differing_fields = _label_differences(gold, review)
        adjudication = adjudication_by_id.get(gold.sample_id)
        resolved = gold.model_copy(deep=True)
        resolved.metadata.reviewer = reviewer_id
        resolved.metadata.disputed_fields = []
        resolved.metadata.adjudication_note = None

        if not differing_fields:
            if adjudication is not None:
                raise EvalAdjudicationValidationError(
                    f"{gold.sample_id}: adjudication is not required for label agreement"
                )
            resolved.metadata.review_status = ReviewStatus.AGREED
        else:
            if adjudication is None:
                raise EvalAdjudicationValidationError(
                    f"{gold.sample_id}: substantive label disagreement requires adjudication"
                )
            used_adjudications.add(gold.sample_id)
            resolved.metadata.review_status = ReviewStatus.ADJUDICATED
            resolved.metadata.disputed_fields = differing_fields
            resolved.metadata.adjudication_note = adjudication.note.strip()

            if adjudication.resolution == "review":
                resolved.expected = _review_result(gold, review)
                resolved.metadata.override_reason = adjudication.override_reason

        validate_record_consistency(resolved)
        resolved_records.append(resolved)

    unused = sorted(set(adjudication_by_id) - used_adjudications)
    if unused:
        raise EvalAdjudicationValidationError(
            f"adjudication is not required for samples: {unused}"
        )

    return resolved_records
