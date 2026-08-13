"""Validated request and result contracts for guard integrations."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .taxonomy import Decision, RiskCategory, Severity, ToolType


class GuardContext(BaseModel):
    cwd: str | None = None
    actor: str | None = None
    tool_name: str | None = None
    privilege: str | None = None
    source: str | None = None


class GuardRequest(BaseModel):
    type: ToolType
    command: str = Field(min_length=1, max_length=32_768)
    context: GuardContext = Field(default_factory=GuardContext)

    @field_validator("command")
    @classmethod
    def command_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("command must not be blank")
        return value


class GuardResult(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    risk: bool
    decision: Decision
    severity: Severity
    category: RiskCategory
    summary: str = Field(min_length=1, max_length=30)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list, max_length=5)
    rule_hits: list[str] = Field(default_factory=list)
    model_version: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)

    @field_validator("summary")
    @classmethod
    def summary_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("summary must not be blank")
        return value
