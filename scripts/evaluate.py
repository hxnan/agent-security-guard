#!/usr/bin/env python3
"""Run the formal Qwen2.5 Model-only Baseline over resolved Eval V1."""

import argparse
import json
from pathlib import Path
import platform
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from guard.baseline_predictor import BaselinePredictor
from guard.environment import resolve_model_path
from guard.eval_freeze import load_resolved_eval_v1
from guard.evaluation import evaluate_baseline, write_evaluation_report
from guard.transformers_backend import TransformersBackendError, TransformersQwenBackend


DEFAULT_OUTPUT = REPOSITORY_ROOT / "artifacts" / "baseline-eval-v2" / "report.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _error(stage: str, message: str, exit_code: int) -> int:
    _emit({"status": "error", "stage": stage, "error": message})
    return exit_code


def _environment_metadata(backend: TransformersQwenBackend, model_path: Path) -> dict[str, object]:
    torch_module = backend.torch
    metadata: dict[str, object] = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "model_path": str(model_path),
        "device": backend.device,
        "torch_version": getattr(torch_module, "__version__", None),
        "transformers_version": None,
        "cuda_device_name": None,
        "cuda_total_memory_mb": None,
    }
    try:
        import transformers

        metadata["transformers_version"] = getattr(transformers, "__version__", None)
    except Exception:
        pass
    try:
        metadata["cuda_device_name"] = torch_module.cuda.get_device_name(0)
        properties = torch_module.cuda.get_device_properties(0)
        metadata["cuda_total_memory_mb"] = round(properties.total_memory / 1024**2, 2)
    except Exception:
        pass
    return metadata


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_new_tokens < 1:
        return _error("arguments", "max_new_tokens must be positive", 2)

    try:
        bundle = load_resolved_eval_v1()
    except (OSError, RuntimeError, ValueError) as exc:
        return _error("freeze_load", str(exc), 1)

    resolved_model = resolve_model_path(args.model_path)
    try:
        backend = TransformersQwenBackend.from_local_model(args.model_path)
    except TransformersBackendError as exc:
        return _error("model_load", str(exc), 1)

    predictor = BaselinePredictor(
        backend,
        max_new_tokens=args.max_new_tokens,
    )
    environment = _environment_metadata(backend, resolved_model)
    try:
        report = evaluate_baseline(
            bundle.records,
            predictor,
            freeze_version=str(bundle.manifest["freeze_version"]),
            max_new_tokens=args.max_new_tokens,
            environment=environment,
        )
    except Exception as exc:
        return _error("evaluation", f"evaluation failed: {exc}", 1)

    report["freeze_human_reviewed"] = bundle.manifest["human_reviewed"]
    report["freeze_reviewer_type"] = bundle.manifest["reviewer_type"]
    report["freeze_substantive_disagreements"] = bundle.substantive_disagreements
    report["freeze_adjudications"] = bundle.adjudication_counts

    try:
        write_evaluation_report(args.output, report)
    except OSError as exc:
        return _error("report_write", f"could not write evaluation report: {exc}", 1)

    performance = report["performance"]
    summary = {
        "status": "ok",
        "output": str(args.output),
        "total_samples": report["total_samples"],
        "valid_output_rate": report["compliance"]["valid_output_rate"],
        "risk_f1": report["risk_metrics"]["f1"],
        "category_macro_f1": report["category_metrics"]["macro_f1"],
        "effective_decision_accuracy": report["decision_metrics"][
            "effective_decision_accuracy_all"
        ],
        "high_or_critical_allow_miss_rate": report["safety_metrics"][
            "high_or_critical_allow_miss_rate"
        ],
        "p50_latency_seconds": performance["p50_latency_seconds"],
        "p95_latency_seconds": performance["p95_latency_seconds"],
        "tokens_per_second": performance["tokens_per_second"],
        "peak_gpu_memory_mb": performance["peak_gpu_memory_mb"],
        "evaluation_wall_seconds": performance["evaluation_wall_seconds"],
    }
    _emit(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
