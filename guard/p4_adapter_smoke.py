"""Post-training artifact and generation checks for the P4 QLoRA pilot."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import time

from .adapter_smoke import (
    load_adapter_runtime,
    write_adapter_report,
)
from .baseline_output import parse_baseline_semantic_result
from .baseline_prompt import BASELINE_PROMPT_VERSION
from .p4_qlora import (
    EXPECTED_P4_SHA256,
    P4_CHECKPOINT_POLICY,
    P4_QUANTIZATION_CONTRACT,
    P4QloraError,
    load_p4_dataset_bundle,
    validate_finite_training_metrics,
    format_p4_training_messages,
)
from .result_parsing import GeneratedResultError
from .qlora import QloraError, assert_adapter_only_output
from .training_config import P4SeedTrainingConfig, resolve_training_model_path


class P4AdapterSmokeError(RuntimeError):
    """Raised when P4 pilot adapter artifacts fail their fixed contract."""


def _validate_adapter_config(
    adapter_config: object,
    manifest: dict[str, object],
    expected_model: Path | None,
) -> None:
    if not isinstance(adapter_config, dict):
        raise P4AdapterSmokeError("adapter_config.json must be a JSON object")
    lora = manifest.get("lora")
    if not isinstance(lora, dict):
        raise P4AdapterSmokeError("training_manifest.json has no valid LoRA contract")
    expected_values = {
        "bias": (lora.get("bias"), "bias"),
        "lora_alpha": (lora.get("alpha"), "alpha"),
        "lora_dropout": (lora.get("dropout"), "dropout"),
        "peft_type": ("LORA", "peft_type"),
        "r": (lora.get("rank"), "rank"),
        "task_type": (lora.get("task_type"), "task_type"),
    }
    for field, (expected, label) in expected_values.items():
        if adapter_config.get(field) != expected:
            raise P4AdapterSmokeError(
                f"adapter_config.json {label} does not match the pilot manifest"
            )

    recorded_model = adapter_config.get("base_model_name_or_path")
    manifest_model = manifest.get("base_model_path")
    if not isinstance(recorded_model, str) or not isinstance(manifest_model, str):
        raise P4AdapterSmokeError("adapter config or manifest has no base model path")
    if Path(recorded_model).resolve() != Path(manifest_model).resolve():
        raise P4AdapterSmokeError(
            "adapter_config.json base model does not match the pilot manifest"
        )
    if (
        expected_model is not None
        and Path(recorded_model).resolve() != expected_model.resolve()
    ):
        raise P4AdapterSmokeError(
            "adapter_config.json base model does not match the requested base model"
        )

    target_modules = adapter_config.get("target_modules")
    if not isinstance(target_modules, (list, tuple, set)):
        raise P4AdapterSmokeError("adapter_config.json target modules must be a list")
    targets = set(target_modules)
    policy = lora.get("target_policy")
    attention = {"q_proj", "k_proj", "v_proj", "o_proj"}
    if policy == "attention":
        valid_targets = targets == attention
    elif policy == "all-linear":
        valid_targets = targets == attention | {
            "gate_proj",
            "up_proj",
            "down_proj",
        }
    else:
        raise P4AdapterSmokeError(
            "training_manifest.json has an unexpected LoRA target policy"
        )
    if not valid_targets:
        raise P4AdapterSmokeError(
            "adapter_config.json target modules do not match the pilot manifest"
        )

    disabled_or_empty = {
        "alpha_pattern": ({},),
        "modules_to_save": (None, []),
        "rank_pattern": ({},),
        "target_parameters": (None, []),
        "use_dora": (False,),
        "use_rslora": (False,),
    }
    for field, allowed in disabled_or_empty.items():
        if adapter_config.get(field) not in allowed:
            raise P4AdapterSmokeError(
                f"adapter_config.json {field} must remain disabled or empty"
            )


def _validate_training_manifest_contract(manifest: dict[str, object]) -> None:
    fixed = {
        "checkpoint_policy": P4_CHECKPOINT_POLICY,
        "gradient_accumulation_steps": 16,
        "gradient_checkpointing": True,
        "max_grad_norm": 0.3,
        "micro_batch_size": 1,
        "optimizer": "paged_adamw_8bit",
        "precision": {"bf16": True, "fp16": False},
        "quantization": P4_QUANTIZATION_CONTRACT,
        "seed": 42,
        "train_count": 800,
        "validation_count": 200,
        "warmup_ratio": 0.03,
    }
    for field, expected in fixed.items():
        if manifest.get(field) != expected:
            raise P4AdapterSmokeError(
                f"training_manifest.json has an unexpected {field}"
            )
    for field in (
        "learning_rate",
        "max_length",
        "num_train_epochs",
        "trainable_parameters",
    ):
        value = manifest.get(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise P4AdapterSmokeError(
                f"training_manifest.json has an invalid {field}"
            )


def _validate_adapter_hashes(
    adapter_dir: Path, manifest: dict[str, object]
) -> None:
    recorded = manifest.get("adapter_sha256")
    if not isinstance(recorded, dict):
        raise P4AdapterSmokeError(
            "training_manifest.json has no adapter artifact SHA-256"
        )
    try:
        actual = {
            str(path.relative_to(adapter_dir)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in adapter_dir.rglob("*")
            if path.is_file()
        }
    except OSError as exc:
        raise P4AdapterSmokeError(f"cannot hash P4 adapter artifacts: {exc}") from exc
    if actual != recorded:
        raise P4AdapterSmokeError(
            "P4 adapter artifact SHA-256 does not match the training manifest"
        )


def inference_runtime_error(exc: Exception, torch_module) -> P4AdapterSmokeError:
    oom_type = getattr(getattr(torch_module, "cuda", None), "OutOfMemoryError", None)
    if isinstance(oom_type, type) and isinstance(exc, oom_type):
        return P4AdapterSmokeError(
            "CUDA out of memory during P4 adapter smoke; retry with "
            "--max-new-tokens 128"
        )
    return P4AdapterSmokeError(
        f"P4 adapter smoke failed ({type(exc).__name__}): {exc}"
    )


def validate_p4_adapter_artifacts(
    adapter_dir: Path, expected_model: Path | None = None
) -> dict[str, object]:
    manifest_path = adapter_dir.parent / "training_manifest.json"
    metrics_path = adapter_dir.parent / "training_metrics.json"
    config_path = adapter_dir / "adapter_config.json"
    required = (config_path, manifest_path, metrics_path)
    missing = [path.name for path in required if not path.is_file()]
    weights = [
        path
        for path in (
            adapter_dir / "adapter_model.safetensors",
            adapter_dir / "adapter_model.bin",
        )
        if path.is_file()
    ]
    if len(weights) != 1:
        missing.append("exactly one adapter_model.safetensors or adapter_model.bin")
    if missing:
        raise P4AdapterSmokeError(
            f"P4 adapter artifacts are incomplete in {adapter_dir}: "
            + ", ".join(missing)
        )
    try:
        assert_adapter_only_output(adapter_dir)
    except QloraError as exc:
        raise P4AdapterSmokeError(str(exc)) from exc

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        adapter_config = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        raise P4AdapterSmokeError(f"P4 adapter artifact JSON is invalid: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("method") != "qlora-p4-seed-pilot":
        raise P4AdapterSmokeError("training_manifest.json has an unexpected method")
    if manifest.get("data_version") != "p4-seed-v1":
        raise P4AdapterSmokeError("training_manifest.json has an unexpected data_version")
    if manifest.get("dataset_sha256") != EXPECTED_P4_SHA256:
        raise P4AdapterSmokeError("training_manifest.json has an unexpected dataset SHA-256")
    if manifest.get("training_prompt_version") != BASELINE_PROMPT_VERSION:
        raise P4AdapterSmokeError(
            "training_manifest.json has an unexpected training prompt version"
        )
    if manifest.get("training_target") != "baseline-semantic-v2":
        raise P4AdapterSmokeError(
            "training_manifest.json has an unexpected training target"
        )
    if manifest.get("quality_milestone") is not False:
        raise P4AdapterSmokeError(
            "training_manifest.json must mark the pilot quality_milestone=false"
        )
    _validate_training_manifest_contract(manifest)
    _validate_adapter_config(adapter_config, manifest, expected_model)
    _validate_adapter_hashes(adapter_dir, manifest)
    if not isinstance(metrics, dict):
        raise P4AdapterSmokeError("training_metrics.json must be a JSON object")
    try:
        validate_finite_training_metrics(metrics)
    except P4QloraError as exc:
        raise P4AdapterSmokeError(str(exc)) from exc
    if expected_model is not None:
        recorded_model = manifest.get("base_model_path")
        if not isinstance(recorded_model, str) or (
            Path(recorded_model).resolve() != expected_model.resolve()
        ):
            raise P4AdapterSmokeError(
                "training_manifest.json base model does not match the requested base model"
            )
    return manifest


def validate_p4_generated_result(text: str):
    try:
        return parse_baseline_semantic_result(text)
    except GeneratedResultError as exc:
        raise P4AdapterSmokeError(str(exc)) from exc


def smoke_test_p4_adapter(
    adapter_dir: Path,
    config: P4SeedTrainingConfig,
    report_path: Path,
    max_new_tokens: int = 256,
) -> dict[str, object]:
    if max_new_tokens < 1:
        raise P4AdapterSmokeError("max_new_tokens must be positive")
    resolved_model = resolve_training_model_path(config.model_path)
    validate_p4_adapter_artifacts(adapter_dir, resolved_model)
    bundle = load_p4_dataset_bundle(config)
    if not bundle.validation:
        raise P4AdapterSmokeError("P4 validation split is empty")
    record = bundle.validation[0]
    try:
        import peft
        import torch
        import transformers
    except ImportError as exc:
        raise P4AdapterSmokeError(f"missing inference dependency: {exc.name}") from exc

    try:
        tokenizer, model = load_adapter_runtime(
            adapter_dir, resolved_model, peft, torch, transformers
        )
        model.eval()
        prompt = tokenizer.apply_chat_template(
            format_p4_training_messages(record)[:2],
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = tokenizer(prompt, return_tensors="pt").to("cuda:0")
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        with torch.inference_mode():
            output = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        elapsed = time.perf_counter() - started
        new_tokens = output[0, inputs["input_ids"].shape[1] :]
        raw_text = tokenizer.decode(new_tokens, skip_special_tokens=True)
    except P4AdapterSmokeError:
        raise
    except Exception as exc:
        raise inference_runtime_error(exc, torch) from exc
    report = {
        "category_match": False,
        "elapsed_seconds": round(elapsed, 3),
        "expected_category": record.result.category.value,
        "peak_gpu_memory_mb": round(torch.cuda.max_memory_allocated() / 1024**2, 2),
        "raw_text": raw_text,
        "sample_id": record.sample_id,
        "valid": False,
    }
    try:
        result = validate_p4_generated_result(raw_text)
        report["actual_category"] = result.category.value
        report["category_match"] = result.category is record.result.category
        report["result"] = result.model_dump(mode="json")
        report["valid"] = True
    finally:
        write_adapter_report(report_path, report)
    return report
