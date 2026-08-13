"""Local model and CUDA environment checks."""

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
from typing import Mapping, Sequence


DEFAULT_MODEL_PATH = Path("models/base/Qwen2.5-1.5B-Instruct")
MODEL_PATH_ENV = "AGENT_SECURITY_MODEL_PATH"
REQUIRED_MODEL_FILES = (
    "config.json",
    "generation_config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
)


def resolve_model_path(
    explicit_path: str | os.PathLike[str] | None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve explicit path, then environment setting, then repository default."""
    environment = os.environ if environ is None else environ
    if explicit_path:
        return Path(explicit_path).expanduser()
    if environment.get(MODEL_PATH_ENV):
        return Path(environment[MODEL_PATH_ENV]).expanduser()
    return DEFAULT_MODEL_PATH


def validate_model_directory(model_path: Path) -> list[str]:
    """Return required model files that are absent from *model_path*."""
    return [name for name in REQUIRED_MODEL_FILES if not (model_path / name).is_file()]


def _package_version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def collect_environment(model_path: Path) -> dict[str, object]:
    """Collect a JSON-serializable environment report without loading model weights."""
    cuda_available = False
    gpu_name = None
    try:
        import torch

        cuda_available = torch.cuda.is_available()
        if cuda_available:
            gpu_name = torch.cuda.get_device_name(0)
    except ImportError:
        pass

    return {
        "model_path": str(model_path),
        "missing_model_files": validate_model_directory(model_path),
        "torch_version": _package_version("torch"),
        "transformers_version": _package_version("transformers"),
        "cuda_available": cuda_available,
        "gpu_name": gpu_name,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Agent Security Guard runtime prerequisites")
    parser.add_argument("--model-path", help=f"Model path; overrides {MODEL_PATH_ENV}")
    args = parser.parse_args(argv)

    report = collect_environment(resolve_model_path(args.model_path))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["cuda_available"] and not report["missing_model_files"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
