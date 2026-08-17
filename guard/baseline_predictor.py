"""Backend-independent orchestration for the model-only security baseline."""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Sequence

from pydantic import BaseModel

from .baseline_output import parse_baseline_semantic_result
from .baseline_prompt import format_baseline_messages, format_baseline_repair_messages
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
    repair_attempted: bool = False
    repair_succeeded: bool = False
    initial_raw_text: str | None = None
    initial_error: str | None = None
    repair_raw_text: str | None = None
    repair_error: str | None = None


def _max_peak_memory(*values: float | None) -> float | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


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
            initial = self.backend.generate(messages, self.max_new_tokens)
        except Exception as exc:
            return BaselinePredictionOutcome(
                status=PredictionStatus.BACKEND_ERROR,
                fallback_decision=Decision.REVIEW,
                error=f"backend generation failed: {exc}",
            )

        try:
            result = parse_baseline_semantic_result(initial.raw_text)
        except GeneratedResultError as initial_exc:
            initial_error = str(initial_exc)
        else:
            return BaselinePredictionOutcome(
                status=PredictionStatus.OK,
                result=result,
                raw_text=initial.raw_text,
                initial_raw_text=initial.raw_text,
                elapsed_seconds=initial.elapsed_seconds,
                generated_tokens=initial.generated_tokens,
                peak_gpu_memory_mb=initial.peak_gpu_memory_mb,
            )

        repair_messages = format_baseline_repair_messages(
            request,
            initial.raw_text,
            initial_error,
        )
        try:
            repair = self.backend.generate(repair_messages, self.max_new_tokens)
        except Exception as exc:
            repair_error = f"backend repair generation failed: {exc}"
            return BaselinePredictionOutcome(
                status=PredictionStatus.BACKEND_ERROR,
                fallback_decision=Decision.REVIEW,
                error=repair_error,
                raw_text=initial.raw_text,
                elapsed_seconds=initial.elapsed_seconds,
                generated_tokens=initial.generated_tokens,
                peak_gpu_memory_mb=initial.peak_gpu_memory_mb,
                repair_attempted=True,
                initial_raw_text=initial.raw_text,
                initial_error=initial_error,
                repair_error=repair_error,
            )

        elapsed_seconds = initial.elapsed_seconds + repair.elapsed_seconds
        generated_tokens = initial.generated_tokens + repair.generated_tokens
        peak_gpu_memory_mb = _max_peak_memory(
            initial.peak_gpu_memory_mb,
            repair.peak_gpu_memory_mb,
        )

        try:
            result = parse_baseline_semantic_result(repair.raw_text)
        except GeneratedResultError as repair_exc:
            repair_error = str(repair_exc)
            return BaselinePredictionOutcome(
                status=PredictionStatus.PARSE_ERROR,
                fallback_decision=Decision.REVIEW,
                error=repair_error,
                raw_text=repair.raw_text,
                elapsed_seconds=elapsed_seconds,
                generated_tokens=generated_tokens,
                peak_gpu_memory_mb=peak_gpu_memory_mb,
                repair_attempted=True,
                initial_raw_text=initial.raw_text,
                initial_error=initial_error,
                repair_raw_text=repair.raw_text,
                repair_error=repair_error,
            )

        return BaselinePredictionOutcome(
            status=PredictionStatus.OK,
            result=result,
            raw_text=repair.raw_text,
            elapsed_seconds=elapsed_seconds,
            generated_tokens=generated_tokens,
            peak_gpu_memory_mb=peak_gpu_memory_mb,
            repair_attempted=True,
            repair_succeeded=True,
            initial_raw_text=initial.raw_text,
            initial_error=initial_error,
            repair_raw_text=repair.raw_text,
        )
