"""Backend-independent orchestration for the model-only security baseline."""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Sequence

from pydantic import BaseModel

from .baseline_output import parse_baseline_semantic_result
from .baseline_prompt import format_baseline_messages
from .contracts import GuardRequest, GuardResult
from .result_parsing import GeneratedResultError
from .taxonomy import Decision


@dataclass(frozen=True)
class GenerationResult:
    """Raw backend generation plus runtime measurements."""

    raw_text: str
    elapsed_seconds: float
    generated_tokens: int
    peak_gpu_memory_mb: float | None = None


class GenerationBackend(Protocol):
    """Minimal generation interface consumed by BaselinePredictor."""

    def generate(
        self,
        messages: Sequence[dict[str, str]],
        max_new_tokens: int,
    ) -> GenerationResult: ...


class PredictionStatus(str, Enum):
    OK = "ok"
    BACKEND_ERROR = "backend_error"
    PARSE_ERROR = "parse_error"


class BaselinePredictionOutcome(BaseModel):
    """One model prediction or an explicit fail-safe outcome."""

    status: PredictionStatus
    result: GuardResult | None = None
    fallback_decision: Decision | None = None
    error: str | None = None
    raw_text: str | None = None
    elapsed_seconds: float | None = None
    generated_tokens: int | None = None
    peak_gpu_memory_mb: float | None = None


class BaselinePredictor:
    """Format, generate, validate and fail safely for one GuardRequest."""

    def __init__(self, backend: GenerationBackend, max_new_tokens: int = 256):
        if max_new_tokens < 1:
            raise ValueError("max_new_tokens must be positive")
        self.backend = backend
        self.max_new_tokens = max_new_tokens

    def predict(self, request: GuardRequest) -> BaselinePredictionOutcome:
        messages = format_baseline_messages(request)
        try:
            generation = self.backend.generate(messages, self.max_new_tokens)
        except Exception as exc:
            return BaselinePredictionOutcome(
                status=PredictionStatus.BACKEND_ERROR,
                fallback_decision=Decision.REVIEW,
                error=f"backend generation failed: {exc}",
            )

        try:
            result = parse_baseline_semantic_result(generation.raw_text)
        except GeneratedResultError as exc:
            return BaselinePredictionOutcome(
                status=PredictionStatus.PARSE_ERROR,
                fallback_decision=Decision.REVIEW,
                error=str(exc),
                raw_text=generation.raw_text,
                elapsed_seconds=generation.elapsed_seconds,
                generated_tokens=generation.generated_tokens,
                peak_gpu_memory_mb=generation.peak_gpu_memory_mb,
            )

        return BaselinePredictionOutcome(
            status=PredictionStatus.OK,
            result=result,
            raw_text=generation.raw_text,
            elapsed_seconds=generation.elapsed_seconds,
            generated_tokens=generation.generated_tokens,
            peak_gpu_memory_mb=generation.peak_gpu_memory_mb,
        )
