#!/usr/bin/env python3
"""Evaluate the validated P4 pilot adapter over frozen Eval V1."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from guard.baseline_predictor import BaselinePredictor
from guard.eval_freeze import load_resolved_eval_v1
from guard.evaluation import evaluate_baseline, write_evaluation_report
from guard.p4_adapter_backend import (
    P4_ADAPTER_MODEL_VERSION,
    P4AdapterBackendError,
    P4AdapterQwenBackend,
    parse_p4_adapter_semantic_result,
)
from guard.training_config import DEFAULT_P4_OUTPUT_DIR, resolve_training_model_path


P4_ADAPTER_EVAL_REPORT_VERSION = "p4-adapter-eval-report-v1"
DEFAULT_ADAPTER_DIR = DEFAULT_P4_OUTPUT_DIR / "adapter"
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT / "artifacts" / "p4-adapter-eval-v1" / "report.json"
)


class P4AdapterArgumentError(ValueError):
    """Raised when CLI arguments violate the JSON-only error contract."""


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise P4AdapterArgumentError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--adapter-dir", type=Path, default=DEFAULT_ADAPTER_DIR)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _error(stage: str, message: str, exit_code: int) -> int:
    _emit({"status": "error", "stage": stage, "error": message})
    return exit_code


def _environment_metadata(
    backend: P4AdapterQwenBackend,
    model_path: Path,
) -> dict[str, object]:
    torch_module = backend.torch
    metadata: dict[str, object] = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "model_path": str(model_path),
        "adapter_dir": str(backend.adapter_dir),
        "device": backend.device,
        "torch_version": getattr(torch_module, "__version__", None),
        "transformers_version": None,
        "peft_version": None,
        "cuda_device_name": None,
        "cuda_total_memory_mb": None,
    }
    for package in ("transformers", "peft"):
        try:
            module = __import__(package)
            metadata[f"{package}_version"] = getattr(module, "__version__", None)
        except Exception:
            pass
    try:
        metadata["cuda_device_name"] = torch_module.cuda.get_device_name(0)
        properties = torch_module.cuda.get_device_properties(0)
        metadata["cuda_total_memory_mb"] = round(
            properties.total_memory / 1024**2,
            2,
        )
    except Exception:
        pass
    return metadata


def _compact_summary(
    report: dict[str, object],
    output: Path,
) -> dict[str, object]:
    compliance = report["compliance"]
    repair = report["repair_metrics"]
    performance = report["performance"]
    return {
        "status": "ok",
        "output": str(output),
        "total_samples": report["total_samples"],
        "first_pass_valid_output_rate": compliance[
            "first_pass_valid_output_rate"
        ],
        "repair_attempt_rate": repair["repair_attempt_rate"],
        "repair_success_rate": repair["repair_success_rate"],
        "valid_output_rate": compliance["valid_output_rate"],
        "risk_f1": report["risk_metrics"]["f1"],
        "category_macro_f1": report["category_metrics"]["macro_f1"],
        "effective_decision_accuracy": report["decision_metrics"][
            "effective_decision_accuracy_all"
        ],
        "high_risk_allow_miss_count": report["safety_metrics"][
            "high_or_critical_allow_misses"
        ],
        "p50_latency_seconds": performance["p50_latency_seconds"],
        "p95_latency_seconds": performance["p95_latency_seconds"],
        "tokens_per_second": performance["tokens_per_second"],
        "peak_gpu_memory_mb": performance["peak_gpu_memory_mb"],
        "evaluation_wall_seconds": performance["evaluation_wall_seconds"],
    }


def _adapter_provenance(
    adapter_dir: Path,
    manifest: dict[str, object],
) -> dict[str, object]:
    return {
        "adapter_dir": str(adapter_dir),
        "adapter_sha256": manifest.get("adapter_sha256"),
        "base_model_path": manifest.get("base_model_path"),
        "data_version": manifest.get("data_version"),
        "dataset_sha256": manifest.get("dataset_sha256"),
        "method": manifest.get("method"),
        "training_prompt_version": manifest.get("training_prompt_version"),
        "training_target": manifest.get("training_target"),
    }


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except P4AdapterArgumentError as exc:
        return _error("arguments", str(exc), 2)
    if args.max_new_tokens < 1:
        return _error("arguments", "max_new_tokens must be positive", 2)

    try:
        bundle = load_resolved_eval_v1()
    except (OSError, RuntimeError, ValueError) as exc:
        return _error("freeze_load", str(exc), 1)

    try:
        resolved_model = resolve_training_model_path(args.model_path)
        backend = P4AdapterQwenBackend.from_local_adapter(
            args.adapter_dir,
            resolved_model,
        )
    except (OSError, P4AdapterBackendError, RuntimeError) as exc:
        return _error("adapter_load", str(exc), 1)

    predictor = BaselinePredictor(
        backend,
        max_new_tokens=args.max_new_tokens,
        result_parser=lambda text: parse_p4_adapter_semantic_result(
            text, model_version=backend.model_version
        ),
    )
    try:
        report = evaluate_baseline(
            bundle.records,
            predictor,
            freeze_version=str(bundle.manifest["freeze_version"]),
            max_new_tokens=args.max_new_tokens,
            environment=_environment_metadata(backend, resolved_model),
        )
    except Exception as exc:
        return _error("evaluation", f"evaluation failed: {exc}", 1)

    report["report_version"] = P4_ADAPTER_EVAL_REPORT_VERSION
    report["model_version"] = backend.model_version
    report["adapter_provenance"] = _adapter_provenance(
        backend.adapter_dir,
        backend.manifest,
    )
    report["freeze_human_reviewed"] = bundle.manifest["human_reviewed"]
    report["freeze_reviewer_type"] = bundle.manifest["reviewer_type"]
    report["freeze_substantive_disagreements"] = bundle.substantive_disagreements
    report["freeze_adjudications"] = bundle.adjudication_counts

    try:
        write_evaluation_report(args.output, report)
    except OSError as exc:
        return _error("report_write", f"could not write evaluation report: {exc}", 1)

    _emit(_compact_summary(report, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
