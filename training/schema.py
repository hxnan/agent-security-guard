from __future__ import annotations

from dataclasses import dataclass
from typing import Any


REQUIRED_OUTPUT_FIELDS = (
    "risk",
    "decision",
    "severity",
    "category",
    "summary",
    "confidence",
)


@dataclass(frozen=True)
class GuardTrainingExample:
    sample_id: str
    instruction: str
    input: dict[str, Any]
    output: dict[str, Any]
    metadata: dict[str, Any]

    def validate(self) -> list[str]:
        errors: list[str] = []
        for field in REQUIRED_OUTPUT_FIELDS:
            if field not in self.output:
                errors.append(f"missing output field: {field}")
        return errors
