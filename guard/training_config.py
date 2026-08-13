"""Configuration and fast-fail checks for the local QLoRA smoke run."""

from dataclasses import dataclass
import importlib.metadata
import os
from pathlib import Path
from typing import Callable, Mapping

from .environment import resolve_model_path, validate_model_directory


class TrainingConfigError(ValueError):
    """Raised when training arguments are invalid."""


class TrainingEnvironmentError(RuntimeError):
    """Raised when the local machine is not ready for smoke training."""


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = REPOSITORY_ROOT / "data" / "generated" / "smoke-v1"
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "artifacts" / "smoke-qlora-v1"
MINIMUM_GPU_MEMORY_BYTES = int(5.5 * 1024**3)
MINIMUM_FREE_GPU_MEMORY_BYTES = int(4.75 * 1024**3)
EXPECTED_PACKAGE_VERSIONS = {
    "accelerate": "1.14.0",
    "bitsandbytes": "0.49.2",
    "numpy": "1.26.4",
    "peft": "0.20.0",
    "safetensors": "0.8.0",
    "torch": "2.5.1",
    "transformers": "4.57.6",
}


@dataclass(frozen=True)
class SmokeTrainingConfig:
    model_path: Path | None = None
    data_dir: Path = DEFAULT_DATA_DIR
    output_dir: Path = DEFAULT_OUTPUT_DIR
    max_length: int = 512
    num_train_epochs: float = 1.0
    micro_batch_size: int = 1
    gradient_accumulation_steps: int = 8
    learning_rate: float = 2e-4
    lora_target: str = "all-linear"
    seed: int = 42
    overwrite_output: bool = False

    def __post_init__(self) -> None:
        for field in (
            "max_length",
            "num_train_epochs",
            "micro_batch_size",
            "gradient_accumulation_steps",
            "learning_rate",
        ):
            if getattr(self, field) <= 0:
                raise TrainingConfigError(f"{field} must be positive")
        if self.lora_target not in {"all-linear", "attention"}:
            raise TrainingConfigError("lora_target must be 'all-linear' or 'attention'")
        if self.seed < 0:
            raise TrainingConfigError("seed must be nonnegative")


def resolve_training_model_path(
    explicit_path: str | os.PathLike[str] | None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    return resolve_model_path(explicit_path, environ)


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _cuda_probe() -> dict[str, object]:
    try:
        import torch
    except ImportError:
        return {
            "available": False,
            "bf16_supported": False,
            "gpu_name": None,
            "total_memory_bytes": 0,
            "free_memory_bytes": 0,
        }
    available = torch.cuda.is_available()
    free_memory = torch.cuda.mem_get_info(0)[0] if available else 0
    return {
        "available": available,
        "bf16_supported": available and torch.cuda.is_bf16_supported(),
        "gpu_name": torch.cuda.get_device_name(0) if available else None,
        "total_memory_bytes": (
            torch.cuda.get_device_properties(0).total_memory if available else 0
        ),
        "free_memory_bytes": free_memory,
    }


def _version_matches(package: str, actual: str | None) -> bool:
    if actual is None:
        return False
    expected = EXPECTED_PACKAGE_VERSIONS[package]
    if package == "torch":
        return actual == expected or actual.startswith(expected + "+")
    return actual == expected


def inspect_training_environment(
    model_path: Path,
    data_dir: Path,
    package_version: Callable[[str], str | None] = _package_version,
    cuda_probe: Callable[[], dict[str, object]] = _cuda_probe,
) -> dict[str, object]:
    packages = {
        name: package_version(name) for name in sorted(EXPECTED_PACKAGE_VERSIONS)
    }
    mismatches = [
        f"{name}: expected {EXPECTED_PACKAGE_VERSIONS[name]}, got {packages[name] or 'missing'}"
        for name in sorted(packages)
        if not _version_matches(name, packages[name])
    ]
    cuda = cuda_probe()
    total_memory = int(cuda.get("total_memory_bytes") or 0)
    free_memory = int(cuda.get("free_memory_bytes", total_memory) or 0)
    missing_model_files = validate_model_directory(model_path)
    missing_data_files = [
        name for name in ("train.jsonl", "validation.jsonl") if not (data_dir / name).is_file()
    ]
    ready = (
        not mismatches
        and not missing_model_files
        and not missing_data_files
        and cuda.get("available") is True
        and cuda.get("bf16_supported") is True
        and total_memory >= MINIMUM_GPU_MEMORY_BYTES
        and free_memory >= MINIMUM_FREE_GPU_MEMORY_BYTES
    )
    return {
        "bf16_supported": bool(cuda.get("bf16_supported")),
        "cuda_available": bool(cuda.get("available")),
        "data_dir": str(data_dir),
        "gpu_memory_gb": round(total_memory / 1024**3, 2),
        "gpu_free_memory_gb": round(free_memory / 1024**3, 2),
        "gpu_name": cuda.get("gpu_name"),
        "missing_data_files": missing_data_files,
        "missing_model_files": missing_model_files,
        "model_path": str(model_path),
        "package_mismatches": mismatches,
        "packages": packages,
        "ready": ready,
    }


def assert_training_ready(report: Mapping[str, object]) -> None:
    errors = []
    errors.extend(report.get("package_mismatches", []))
    if report.get("missing_model_files"):
        errors.append(f"missing model files: {report['missing_model_files']}")
    if report.get("missing_data_files"):
        errors.append(f"missing data files: {report['missing_data_files']}")
    if not report.get("cuda_available"):
        errors.append("CUDA is unavailable")
    if not report.get("bf16_supported"):
        errors.append("GPU BF16 support is unavailable")
    if float(report.get("gpu_memory_gb") or 0) < 5.5:
        errors.append("GPU must provide at least 5.5 GB memory")
    if float(report.get("gpu_free_memory_gb") or 0) < 4.75:
        errors.append("GPU must provide at least 4.75 GB free GPU memory")
    if errors:
        raise TrainingEnvironmentError(
            "training environment is not ready:\n- " + "\n- ".join(errors)
        )
