"""Blind-review helpers for independent Eval V1 annotation review."""

import json
from pathlib import Path
from typing import Sequence

from pydantic import BaseModel, Field, ValidationError, field_validator

from .contracts import GuardRequest
from .eval_dataset import EvalGoldRecord
from .taxonomy import Decision, RiskCategory, Severity


_ALLOWED_CONFIDENCE = {0.50, 0.60, 0.75, 0.90, 0.99}
_CORE_FIELDS = ("decision", "severity", "category", "summary")


class EvalReviewValidationError(ValueError):
    """Raised when reviewer answer data cannot be compared safely."""


class EvalBlindReviewRecord(BaseModel):
    """Request-only record that intentionally hides the primary Gold label."""

    sample_id: str = Field(pattern=r"^EV[0-9]{3}$")
    request: GuardRequest


class EvalReviewAnswer(BaseModel):
    """Independent reviewer answer for one Eval V1 request."""

    sample_id: str = Field(pattern=r"^EV[0-9]{3}$")
    decision: Decision
    severity: Severity
    category: RiskCategory
    summary: str = Field(min_length=1, max_length=30)
    confidence: float
    evidence: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("summary")
    @classmethod
    def summary_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("summary must not be blank")
        return value

    @field_validator("confidence")
    @classmethod
    def confidence_must_use_annotation_bucket(cls, value: float) -> float:
        if value not in _ALLOWED_CONFIDENCE:
            raise ValueError(f"confidence must be one of {sorted(_ALLOWED_CONFIDENCE)}")
        return value


class EvalReviewComparison(BaseModel):
    """Core-field disagreement for one independently reviewed sample."""

    sample_id: str = Field(pattern=r"^EV[0-9]{3}$")
    differing_fields: tuple[str, ...]


def build_blind_review_packet(
    records: Sequence[EvalGoldRecord],
) -> list[EvalBlindReviewRecord]:
    """Strip all primary labels and governance metadata from review input."""
    return [
        EvalBlindReviewRecord(sample_id=record.sample_id, request=record.request)
        for record in records
    ]


def load_review_answers(path: Path) -> list[EvalReviewAnswer]:
    """Load independent reviewer answers from JSONL."""
    answers: list[EvalReviewAnswer] = []
    with path.open(encoding="utf-8") as answer_file:
        for line_number, line in enumerate(answer_file, start=1):
            if not line.strip():
                raise EvalReviewValidationError(
                    f"line {line_number}: blank lines are not allowed"
                )
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvalReviewValidationError(
                    f"line {line_number}: invalid JSON: {exc.msg}"
                ) from exc
            try:
                answers.append(EvalReviewAnswer.model_validate(value))
            except ValidationError as exc:
                raise EvalReviewValidationError(
                    f"line {line_number}: invalid review answer: {exc}"
                ) from exc
    return answers


def compare_review_answers(
    records: Sequence[EvalGoldRecord],
    answers: Sequence[EvalReviewAnswer],
) -> list[EvalReviewComparison]:
    """Return only disagreements in the four Annotation Guideline core fields."""
    gold_by_id = {record.sample_id: record for record in records}
    seen: set[str] = set()
    comparisons: list[EvalReviewComparison] = []

    for answer in answers:
        if answer.sample_id in seen:
            raise EvalReviewValidationError(
                f"duplicate reviewer answer for {answer.sample_id}"
            )
        seen.add(answer.sample_id)
        gold = gold_by_id.get(answer.sample_id)
        if gold is None:
            raise EvalReviewValidationError(
                f"review answer references unknown sample_id {answer.sample_id}"
            )

        differing_fields = tuple(
            field
            for field in _CORE_FIELDS
            if getattr(answer, field) != getattr(gold.expected, field)
        )
        if differing_fields:
            comparisons.append(
                EvalReviewComparison(
                    sample_id=answer.sample_id,
                    differing_fields=differing_fields,
                )
            )

    return comparisons
