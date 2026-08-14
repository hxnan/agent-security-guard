"""Model-facing semantic output parsing for Baseline V2."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .baseline_prompt import BASELINE_MODEL_VERSION, BASELINE_POLICY_VERSION
from .contracts import GuardResult
from .result_parsing import GeneratedResultError, extract_first_json_object
from .taxonomy import Decision, RiskCategory, Severity


class BaselineSemanticResult(BaseModel):
    """The six security-judgment fields the baseline model must infer."""

    model_config = ConfigDict(extra="forbid")

    decision: Decision
    severity: Severity
    category: RiskCategory
    summary: str = Field(min_length=1, max_length=30)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_numeric_confidence_string(cls, value):
        if isinstance(value, bool):
            raise ValueError("confidence must be a JSON number, not a boolean")
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError as exc:
                raise ValueError("confidence string must be numeric") from exc
        return value

    @field_validator("summary")
    @classmethod
    def summary_must_be_chinese(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("summary must not be blank")
        if not any("\u4e00" <= character <= "\u9fff" for character in value):
            raise ValueError("summary must contain Chinese characters")
        return value


def validate_baseline_semantic_object(value: dict[str, object]) -> BaselineSemanticResult:
    """Validate model-facing fields and lossless representation normalization."""
    try:
        return BaselineSemanticResult.model_validate(value)
    except ValueError as exc:
        raise GeneratedResultError(
            f"generated semantic result is invalid: {exc}"
        ) from exc


def validate_baseline_semantic_consistency(semantic: BaselineSemanticResult) -> None:
    """Reject contradictory labels without repairing model semantics."""
    if semantic.category is RiskCategory.BENIGN:
        if semantic.decision is not Decision.ALLOW or semantic.severity is not Severity.NONE:
            raise GeneratedResultError(
                "generated semantic result is inconsistent: benign requires decision=allow and severity=none"
            )
        return

    if semantic.decision is Decision.ALLOW or semantic.severity is Severity.NONE:
        raise GeneratedResultError(
            "generated semantic result is inconsistent: non-benign requires decision in {review,block} and non-none severity"
        )
    if semantic.decision is Decision.BLOCK and semantic.severity not in {
        Severity.HIGH,
        Severity.CRITICAL,
    }:
        raise GeneratedResultError(
            "generated semantic result is inconsistent: block requires severity high or critical"
        )


def build_baseline_guard_result(semantic: BaselineSemanticResult) -> GuardResult:
    """Construct and validate the immutable system-owned GuardResult envelope."""
    payload = semantic.model_dump(mode="json")
    payload.update(
        {
            "schema_version": "1.0",
            "risk": semantic.category is not RiskCategory.BENIGN,
            "rule_hits": [],
            "model_version": BASELINE_MODEL_VERSION,
            "policy_version": BASELINE_POLICY_VERSION,
        }
    )
    try:
        return GuardResult.model_validate(payload)
    except ValueError as exc:
        raise GeneratedResultError(
            f"system-enveloped GuardResult is invalid: {exc}"
        ) from exc


def parse_baseline_semantic_result(text: str) -> GuardResult:
    """Parse six model fields and build the system-owned GuardResult envelope."""
    value = extract_first_json_object(text)
    semantic = validate_baseline_semantic_object(value)
    validate_baseline_semantic_consistency(semantic)
    return build_baseline_guard_result(semantic)
