"""Strict P4 JSONL record contract built on the public guard contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from guard.contracts import GuardContext, GuardRequest, GuardResult
from guard.taxonomy import Decision, RiskCategory, Severity


class TrainingMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_version: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    generation_source: str = Field(
        min_length=1, pattern=r"^[a-z][a-z0-9_]*$"
    )
    semantic_template: str = Field(
        min_length=1, pattern=r"^[a-z][a-z0-9_]*$"
    )
    split: Literal["train", "validation"]


class TrainingExample(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    sample_id: str = Field(alias="id", pattern=r"^TR-[0-9]{6}$")
    instruction: str = Field(min_length=1, max_length=500)
    input: GuardRequest
    output: GuardResult
    metadata: TrainingMetadata

    @field_validator("input", mode="before")
    @classmethod
    def input_has_only_public_fields(cls, value):
        if isinstance(value, dict):
            extras = set(value) - set(GuardRequest.model_fields)
            if extras:
                raise ValueError(f"input has extra fields: {sorted(extras)}")
            context = value.get("context")
            if isinstance(context, dict):
                context_extras = set(context) - set(GuardContext.model_fields)
                if context_extras:
                    raise ValueError(
                        f"input.context has extra fields: {sorted(context_extras)}"
                    )
        return value

    @field_validator("output", mode="before")
    @classmethod
    def output_has_only_public_fields(cls, value):
        if isinstance(value, dict):
            expected_fields = set(GuardResult.model_fields)
            actual_fields = set(value)
            if actual_fields != expected_fields:
                missing = sorted(expected_fields - actual_fields)
                extras = sorted(actual_fields - expected_fields)
                raise ValueError(
                    "output fields must exactly match GuardResult; "
                    f"missing={missing}, extra={extras}"
                )
            if "risk" in value and not isinstance(value["risk"], bool):
                raise ValueError("output.risk must be a boolean")
            confidence = value.get("confidence")
            if "confidence" in value and (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
            ):
                raise ValueError("output.confidence must be a number")
        return value

    @model_validator(mode="after")
    def labels_are_consistent(self):
        if self.output.summary != self.output.summary.strip():
            raise ValueError("summary must not contain surrounding whitespace")
        if not any("\u4e00" <= character <= "\u9fff" for character in self.output.summary):
            raise ValueError("summary must contain Chinese characters")

        if self.output.category is RiskCategory.BENIGN:
            if self.output.risk:
                raise ValueError("benign output must be risk=false")
            if self.output.decision is not Decision.ALLOW:
                raise ValueError("benign output must allow")
            if self.output.severity is not Severity.NONE:
                raise ValueError("benign output must use severity none")
        else:
            if not self.output.risk:
                raise ValueError("non-benign output must be risk=true")
            if self.output.decision is Decision.ALLOW:
                raise ValueError("non-benign output cannot allow")
            if self.output.severity is Severity.NONE:
                raise ValueError("non-benign output cannot use severity none")
            if (
                self.output.decision is Decision.BLOCK
                and self.output.severity not in {Severity.HIGH, Severity.CRITICAL}
            ):
                raise ValueError("block output requires high or critical severity")
        return self
