"""Evaluation-only gold dataset contracts and validation helpers."""

from collections import Counter
import json
from pathlib import Path
from typing import Literal, Sequence

from pydantic import BaseModel, Field, ValidationError

from .contracts import GuardRequest, GuardResult
from .eval_blueprint import BlueprintRecord, ScenarioKind, ToolFamily
from .taxonomy import CATEGORY_DEFINITIONS, Decision, RiskCategory, Severity, StringEnum

_ALLOWED_CONFIDENCE = {0.50, 0.60, 0.75, 0.90, 0.99}


class EvalDatasetValidationError(ValueError):
    """Raised when an Eval V1 gold record violates dataset policy."""


class ReviewStatus(StringEnum):
    PENDING = "pending"
    AGREED = "agreed"
    DISPUTED = "disputed"
    ADJUDICATED = "adjudicated"


class EvalGoldMetadata(BaseModel):
    data_version: Literal["eval-v1"] = "eval-v1"
    source: str = Field(min_length=1)
    semantic_template: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    variant: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    scenario_kind: ScenarioKind
    tool_family: ToolFamily
    review_status: ReviewStatus = ReviewStatus.PENDING
    primary_annotator: str = Field(min_length=1)
    reviewer: str | None = None
    disputed_fields: list[str] = Field(default_factory=list)
    adjudication_note: str | None = None
    override_reason: str | None = None
    supersedes: str | None = None


class EvalGoldRecord(BaseModel):
    sample_id: str = Field(pattern=r"^EV[0-9]{3}$")
    request: GuardRequest
    expected: GuardResult
    metadata: EvalGoldMetadata


def _fail(record: EvalGoldRecord, message: str) -> None:
    raise EvalDatasetValidationError(f"{record.sample_id}: {message}")


def validate_record_consistency(record: EvalGoldRecord) -> None:
    """Validate annotation-guideline invariants for one gold record."""
    result = record.expected

    if result.confidence not in _ALLOWED_CONFIDENCE:
        _fail(record, f"confidence must be one of {sorted(_ALLOWED_CONFIDENCE)}")

    if result.risk and result.decision is Decision.ALLOW:
        _fail(record, "risk=true cannot use decision=allow")
    if not result.risk and result.decision is not Decision.ALLOW:
        _fail(record, "risk=false must use decision=allow")

    if result.category is RiskCategory.BENIGN:
        if (
            result.risk
            or result.decision is not Decision.ALLOW
            or result.severity is not Severity.NONE
        ):
            _fail(record, "benign requires risk=false, decision=allow, severity=none")
    else:
        if not result.risk:
            _fail(record, "non-benign category requires risk=true")
        if result.decision is Decision.ALLOW:
            _fail(record, "non-benign category cannot use decision=allow")
        if result.severity is Severity.NONE:
            _fail(record, "non-benign category cannot use severity=none")
        if not result.evidence:
            _fail(record, "non-benign category requires evidence")

    if result.decision is Decision.BLOCK and result.severity not in {
        Severity.HIGH,
        Severity.CRITICAL,
    }:
        _fail(record, "decision=block requires severity high or critical")

    defaults = CATEGORY_DEFINITIONS[result.category]
    if (
        result.decision is not defaults.default_decision
        or result.severity is not defaults.default_severity
    ) and not (record.metadata.override_reason or "").strip():
        _fail(record, "override_reason is required when category defaults are changed")

    review_status = ReviewStatus(record.metadata.review_status)
    if review_status in {
        ReviewStatus.AGREED,
        ReviewStatus.DISPUTED,
        ReviewStatus.ADJUDICATED,
    } and not (record.metadata.reviewer or "").strip():
        _fail(record, f"reviewer is required for review_status={review_status.value}")
    if review_status is ReviewStatus.DISPUTED and not record.metadata.disputed_fields:
        _fail(record, "disputed_fields are required for review_status=disputed")
    if review_status is ReviewStatus.ADJUDICATED and not (
        record.metadata.adjudication_note or ""
    ).strip():
        _fail(record, "adjudication_note is required for review_status=adjudicated")


def load_eval_dataset(path: Path) -> list[EvalGoldRecord]:
    """Load Eval V1 gold JSONL without executing any contained command."""
    records: list[EvalGoldRecord] = []
    with path.open(encoding="utf-8") as dataset_file:
        for line_number, line in enumerate(dataset_file, start=1):
            if not line.strip():
                raise EvalDatasetValidationError(
                    f"line {line_number}: blank lines are not allowed"
                )
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvalDatasetValidationError(
                    f"line {line_number}: invalid JSON: {exc.msg}"
                ) from exc
            try:
                records.append(EvalGoldRecord.model_validate(value))
            except ValidationError as exc:
                raise EvalDatasetValidationError(
                    f"line {line_number}: invalid gold record: {exc}"
                ) from exc
    return records


def validate_eval_dataset(
    records: Sequence[EvalGoldRecord],
    *,
    require_complete: bool = False,
    require_frozen: bool = False,
) -> None:
    """Validate dataset-wide invariants independent of model execution."""
    for record in records:
        validate_record_consistency(record)

    sample_ids = [record.sample_id for record in records]
    duplicate_ids = sorted(
        sample_id for sample_id, count in Counter(sample_ids).items() if count > 1
    )
    if duplicate_ids:
        raise EvalDatasetValidationError(f"duplicate sample_id values: {duplicate_ids}")

    expected_ids = [f"EV{number:03d}" for number in range(1, len(records) + 1)]
    if sample_ids != expected_ids:
        raise EvalDatasetValidationError(
            "sample_id values must be contiguous from EV001 in order"
        )

    pairs = [
        (record.metadata.semantic_template, record.metadata.variant) for record in records
    ]
    duplicate_pairs = sorted(
        pair for pair, count in Counter(pairs).items() if count > 1
    )
    if duplicate_pairs:
        raise EvalDatasetValidationError(
            f"duplicate semantic_template/variant pairs: {duplicate_pairs}"
        )

    for record in records:
        if (
            record.metadata.tool_family is not ToolFamily.MIXED
            and record.request.type.value != record.metadata.tool_family.value
        ):
            raise EvalDatasetValidationError(
                f"{record.sample_id}: request type {record.request.type.value!r} "
                f"does not match tool_family {record.metadata.tool_family.value!r}"
            )
        if require_frozen and record.metadata.review_status not in {
            ReviewStatus.AGREED,
            ReviewStatus.ADJUDICATED,
        }:
            raise EvalDatasetValidationError(
                f"{record.sample_id}: review_status must be agreed or adjudicated "
                "when frozen validation is required"
            )

    if require_complete and len(records) != 100:
        raise EvalDatasetValidationError(
            f"complete Eval V1 must contain 100 records, got {len(records)}"
        )


def validate_against_blueprint(
    records: Sequence[EvalGoldRecord],
    blueprint_records: Sequence[BlueprintRecord],
) -> None:
    """Ensure authored gold rows preserve their committed blueprint identity."""
    blueprint_by_id = {record.sample_id: record for record in blueprint_records}
    for record in records:
        blueprint = blueprint_by_id.get(record.sample_id)
        if blueprint is None:
            raise EvalDatasetValidationError(
                f"{record.sample_id}: sample_id is not present in Eval V1 blueprint"
            )
        checks = (
            ("tool_family", record.metadata.tool_family, blueprint.tool_family),
            ("request_type", record.request.type, blueprint.request_type),
            ("scenario_kind", record.metadata.scenario_kind, blueprint.scenario_kind),
            ("planned_category", record.expected.category, blueprint.planned_category),
            (
                "semantic_template",
                record.metadata.semantic_template,
                blueprint.semantic_template,
            ),
            ("variant", record.metadata.variant, blueprint.variant),
        )
        for field, actual, expected in checks:
            if actual != expected:
                actual_value = getattr(actual, "value", actual)
                expected_value = getattr(expected, "value", expected)
                raise EvalDatasetValidationError(
                    f"{record.sample_id}: {field} mismatch: "
                    f"expected {expected_value!r}, got {actual_value!r}"
                )


def _sorted_counter(values: Sequence[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def build_eval_dataset_stats(records: Sequence[EvalGoldRecord]) -> dict[str, object]:
    """Build deterministic review statistics for a gold dataset."""
    return {
        "categories": _sorted_counter(
            [record.expected.category.value for record in records]
        ),
        "confidences": _sorted_counter(
            [f"{record.expected.confidence:.2f}" for record in records]
        ),
        "decisions": _sorted_counter(
            [record.expected.decision.value for record in records]
        ),
        "review_statuses": _sorted_counter(
            [record.metadata.review_status.value for record in records]
        ),
        "scenario_kinds": _sorted_counter(
            [record.metadata.scenario_kind.value for record in records]
        ),
        "severities": _sorted_counter(
            [record.expected.severity.value for record in records]
        ),
        "tool_families": _sorted_counter(
            [record.metadata.tool_family.value for record in records]
        ),
        "total": len(records),
    }
