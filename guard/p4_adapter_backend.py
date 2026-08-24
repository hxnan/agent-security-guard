"""Local-only P4 pilot adapter backend for formal Eval V1 runs."""

from __future__ import annotations

from pathlib import Path

from .adapter_smoke import load_adapter_runtime
from .baseline_output import parse_baseline_semantic_result
from .contracts import GuardResult
from .p4_adapter_smoke import (
    P4_ADAPTER_MODEL_VERSION,
    P4_COMBINED_ADAPTER_MODEL_VERSION,
    P4AdapterSmokeError,
    p4_adapter_model_version,
    validate_p4_adapter_artifacts,
)
from .training_config import resolve_training_model_path
from .transformers_backend import TransformersQwenBackend


class P4AdapterBackendError(RuntimeError):
    """Raised when the validated local P4 adapter runtime cannot be used."""


def parse_p4_adapter_semantic_result(
    text: str,
    *,
    model_version: str = P4_ADAPTER_MODEL_VERSION,
) -> GuardResult:
    """Parse the shared semantic contract with adapter-specific provenance."""
    result = parse_baseline_semantic_result(text)
    return result.model_copy(update={"model_version": model_version})


class P4AdapterQwenBackend(TransformersQwenBackend):
    """Greedy Qwen backend loaded from a validated P4 PEFT adapter."""

    def __init__(
        self,
        tokenizer,
        model,
        torch_module,
        device: str,
        *,
        adapter_dir: Path,
        manifest: dict[str, object],
    ):
        super().__init__(tokenizer, model, torch_module, device)
        self.adapter_dir = adapter_dir
        self.manifest = manifest
        self.model_version = p4_adapter_model_version(manifest)

    @classmethod
    def from_local_adapter(
        cls,
        adapter_dir: Path,
        model_path: Path | None = None,
        device: str = "cuda:0",
        *,
        peft_module=None,
        torch_module=None,
        transformers_module=None,
    ) -> "P4AdapterQwenBackend":
        if device != "cuda:0":
            raise P4AdapterBackendError(
                "P4 adapter evaluation currently requires device cuda:0"
            )
        adapter_dir = Path(adapter_dir)
        resolved_model = resolve_training_model_path(model_path)
        try:
            manifest = validate_p4_adapter_artifacts(
                adapter_dir,
                resolved_model,
            )
        except P4AdapterSmokeError as exc:
            raise P4AdapterBackendError(str(exc)) from exc
        except OSError as exc:
            raise P4AdapterBackendError(
                "P4 adapter validation failed "
                f"({type(exc).__name__}): {exc}"
            ) from exc

        if peft_module is None:
            try:
                import peft as peft_module
            except ImportError as exc:
                raise P4AdapterBackendError(
                    f"missing adapter evaluation dependency: {exc.name or 'peft'}"
                ) from exc
            except Exception as exc:
                raise P4AdapterBackendError(
                    f"could not initialize adapter dependency peft: {exc}"
                ) from exc
        if torch_module is None:
            try:
                import torch as torch_module
            except ImportError as exc:
                raise P4AdapterBackendError(
                    f"missing adapter evaluation dependency: {exc.name or 'torch'}"
                ) from exc
            except Exception as exc:
                raise P4AdapterBackendError(
                    f"could not initialize adapter dependency torch: {exc}"
                ) from exc
        if transformers_module is None:
            try:
                import transformers as transformers_module
            except ImportError as exc:
                raise P4AdapterBackendError(
                    "missing adapter evaluation dependency: "
                    f"{exc.name or 'transformers'}"
                ) from exc
            except Exception as exc:
                raise P4AdapterBackendError(
                    f"could not initialize adapter dependency transformers: {exc}"
                ) from exc

        try:
            cuda_available = torch_module.cuda.is_available()
        except Exception as exc:
            raise P4AdapterBackendError(
                f"P4 adapter CUDA probe failed ({type(exc).__name__}): {exc}"
            ) from exc
        if not cuda_available:
            raise P4AdapterBackendError(
                "CUDA is not available for P4 adapter evaluation"
            )
        try:
            tokenizer, model = load_adapter_runtime(
                adapter_dir,
                resolved_model,
                peft_module,
                torch_module,
                transformers_module,
            )
            model.eval()
        except Exception as exc:
            raise P4AdapterBackendError(
                f"could not load P4 adapter runtime: {exc}"
            ) from exc
        return cls(
            tokenizer,
            model,
            torch_module,
            device,
            adapter_dir=adapter_dir,
            manifest=manifest,
        )
