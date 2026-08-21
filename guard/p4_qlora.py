"""Strict formal-data preflight for the P4 Seed QLoRA pilot."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

from .baseline_prompt import (
    BASELINE_PROMPT_VERSION,
    MODEL_FACING_FIELDS,
    format_baseline_messages,
)
from .contracts import GuardRequest, GuardResult
from .qlora import ensure_output_directory, run_qlora_training
from .training_config import (
    assert_training_ready,
    inspect_training_environment_for_files,
    P4SeedTrainingConfig,
    resolve_training_model_path,
)
from .training_data import tokenize_training_record
from training.data_quality import (
    DatasetQualityError,
    load_eval_request_fingerprints,
    load_training_jsonl,
)
from training.seed_dataset import SeedDatasetError, validate_seed_profile


class P4QloraError(RuntimeError):
    """Raised when the P4 pilot cannot safely consume its fixed dataset."""


EXPECTED_P4_SHA256 = {
    "train": "1897e89d11a730ad0922081bda0cf18da3b643a1fc887c2e27abaa7cc5e96208",
    "validation": "c4228d11dd08e8e0cf2a48b01398b5ee0be8a7270a572285e870e74eb939915e",
}

P4_QUANTIZATION_CONTRACT = {
    "bits": 4,
    "compute_dtype": "bfloat16",
    "double_quant": True,
    "quant_type": "nf4",
}

P4_CHECKPOINT_POLICY = {
    "eval_strategy": "epoch",
    "greater_is_better": False,
    "load_best_model_at_end": True,
    "max_retained": 1,
    "metric_for_best_model": "eval_loss",
    "save_strategy": "epoch",
}


@dataclass(frozen=True)
class P4TrainingRecord:
    sample_id: str
    request: GuardRequest
    result: GuardResult


@dataclass(frozen=True)
class P4DatasetBundle:
    train: tuple[P4TrainingRecord, ...]
    validation: tuple[P4TrainingRecord, ...]
    sha256: dict[str, str]
    data_version: str


def _read_manifest(config: P4SeedTrainingConfig) -> dict[str, object]:
    try:
        manifest = json.loads(config.manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise P4QloraError(f"cannot read P4 seed manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise P4QloraError("P4 seed manifest must be a JSON object")
    return manifest


def _file_sha256(path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise P4QloraError(f"cannot hash P4 dataset file {path}: {exc}") from exc


def _normalized(records) -> tuple[P4TrainingRecord, ...]:
    return tuple(
        P4TrainingRecord(
            sample_id=record.sample_id,
            request=record.input,
            result=record.output,
        )
        for record in records
    )


def load_p4_dataset_bundle(config: P4SeedTrainingConfig) -> P4DatasetBundle:
    manifest = _read_manifest(config)
    actual_hashes = {
        "train": _file_sha256(config.train_path),
        "validation": _file_sha256(config.validation_path),
    }
    if actual_hashes != EXPECTED_P4_SHA256:
        raise P4QloraError(
            f"P4 dataset SHA-256 mismatch: expected {EXPECTED_P4_SHA256}, "
            f"got {actual_hashes}"
        )
    if manifest.get("sha256") != EXPECTED_P4_SHA256:
        raise P4QloraError("P4 seed manifest SHA-256 does not match the frozen pilot")
    if manifest.get("data_version") != "p4-seed-v1":
        raise P4QloraError("P4 seed manifest has an unexpected data_version")

    try:
        train = load_training_jsonl(config.train_path, expected_split="train")
        validation = load_training_jsonl(
            config.validation_path, expected_split="validation"
        )
        eval_fingerprints = load_eval_request_fingerprints(config.eval_dir)
        validate_seed_profile(train, validation, eval_fingerprints)
    except (DatasetQualityError, SeedDatasetError) as exc:
        raise P4QloraError(f"P4 seed dataset validation failed: {exc}") from exc

    return P4DatasetBundle(
        train=_normalized(train),
        validation=_normalized(validation),
        sha256=dict(actual_hashes),
        data_version="p4-seed-v1",
    )


def format_p4_training_messages(record: P4TrainingRecord) -> list[dict[str, str]]:
    output = record.result.model_dump(mode="json")
    semantic = {field: output[field] for field in MODEL_FACING_FIELDS}
    return [
        *format_baseline_messages(record.request),
        {
            "role": "assistant",
            "content": json.dumps(
                semantic,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        },
    ]


def tokenize_p4_training_record(
    record: P4TrainingRecord, tokenizer, max_length: int
) -> dict[str, list[int]]:
    return tokenize_training_record(
        record,
        tokenizer,
        max_length,
        message_formatter=format_p4_training_messages,
    )


def load_p4_tokenizer(model_path: Path):
    try:
        import transformers
    except ImportError as exc:
        raise P4QloraError(f"missing tokenizer dependency: {exc.name}") from exc
    try:
        return transformers.AutoTokenizer.from_pretrained(
            model_path,
            local_files_only=True,
        )
    except Exception as exc:
        raise P4QloraError(
            f"cannot load local tokenizer ({type(exc).__name__}): {exc}"
        ) from exc


def audit_p4_token_lengths(
    bundle: P4DatasetBundle,
    tokenizer,
    max_length: int,
) -> dict[str, object]:
    lengths = []
    for record in (*bundle.train, *bundle.validation):
        tokenized = tokenize_p4_training_record(
            record,
            tokenizer,
            max_length=2**31 - 1,
        )
        lengths.append((record.sample_id, len(tokenized["input_ids"])))
    maximum = max((length for _, length in lengths), default=0)
    overlength = [
        f"{sample_id}:{length}"
        for sample_id, length in lengths
        if length > max_length
    ]
    return {
        "configured_max_length": max_length,
        "max_observed_length": maximum,
        "overlength_count": len(overlength),
        "overlength_samples": overlength[:20],
        "records_checked": len(lengths),
        "ready": not overlength,
    }


def assert_p4_token_lengths(report: dict[str, object]) -> None:
    if report.get("ready") is not True:
        raise P4QloraError(
            "P4 token-length audit failed: "
            f"max_observed_length={report.get('max_observed_length')}, "
            f"configured_max_length={report.get('configured_max_length')}, "
            f"overlength_samples={report.get('overlength_samples')}"
        )


def build_p4_training_arguments(transformers_module, config: P4SeedTrainingConfig):
    return transformers_module.TrainingArguments(
        output_dir=str(config.output_dir / "trainer"),
        overwrite_output_dir=config.overwrite_output,
        per_device_train_batch_size=config.micro_batch_size,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        num_train_epochs=config.num_train_epochs,
        learning_rate=config.learning_rate,
        warmup_ratio=0.03,
        max_grad_norm=0.3,
        optim="paged_adamw_8bit",
        bf16=True,
        fp16=False,
        gradient_checkpointing=True,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=1,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        logging_steps=5,
        report_to="none",
        remove_unused_columns=False,
        seed=config.seed,
        data_seed=config.seed,
    )


def build_p4_training_manifest(
    config: P4SeedTrainingConfig,
    bundle: P4DatasetBundle,
    *,
    resolved_model: Path,
    trainable_parameters: int,
) -> dict[str, object]:
    return {
        "base_model_path": str(resolved_model),
        "data_version": bundle.data_version,
        "dataset_sha256": dict(bundle.sha256),
        "gradient_accumulation_steps": config.gradient_accumulation_steps,
        "gradient_checkpointing": True,
        "learning_rate": config.learning_rate,
        "lora": {
            "alpha": 16,
            "bias": "none",
            "dropout": 0.05,
            "rank": 8,
            "target_policy": config.lora_target,
            "task_type": "CAUSAL_LM",
        },
        "lora_target": config.lora_target,
        "max_length": config.max_length,
        "method": "qlora-p4-seed-pilot",
        "micro_batch_size": config.micro_batch_size,
        "num_train_epochs": config.num_train_epochs,
        "optimizer": "paged_adamw_8bit",
        "precision": {"bf16": True, "fp16": False},
        "quantization": dict(P4_QUANTIZATION_CONTRACT),
        "quality_milestone": False,
        "seed": config.seed,
        "train_count": len(bundle.train),
        "trainable_parameters": trainable_parameters,
        "training_prompt_version": BASELINE_PROMPT_VERSION,
        "training_target": "baseline-semantic-v2",
        "validation_count": len(bundle.validation),
        "warmup_ratio": 0.03,
        "max_grad_norm": 0.3,
        "checkpoint_policy": dict(P4_CHECKPOINT_POLICY),
    }


def validate_finite_training_metrics(metrics: dict[str, object]) -> None:
    evaluation = metrics.get("evaluation")
    eval_loss = evaluation.get("eval_loss") if isinstance(evaluation, dict) else None
    if (
        isinstance(eval_loss, bool)
        or not isinstance(eval_loss, (int, float))
        or not math.isfinite(eval_loss)
    ):
        raise P4QloraError("P4 pilot evaluation must contain a finite eval_loss")

    def visit(value) -> bool:
        if isinstance(value, dict):
            return all(visit(item) for item in value.values())
        if isinstance(value, (list, tuple)):
            return all(visit(item) for item in value)
        if isinstance(value, float):
            return math.isfinite(value)
        return True

    if not visit(metrics):
        raise P4QloraError("P4 pilot training metrics must contain only finite values")


def preflight_p4_seed_training(config: P4SeedTrainingConfig) -> dict[str, object]:
    bundle = load_p4_dataset_bundle(config)
    resolved_model = resolve_training_model_path(config.model_path)
    environment = inspect_training_environment_for_files(
        resolved_model,
        {
            "manifest": config.manifest_path,
            "train": config.train_path,
            "validation": config.validation_path,
        },
    )
    tokenization = {"ready": False, "status": "not_checked"}
    if environment["ready"]:
        tokenization = audit_p4_token_lengths(
            bundle,
            load_p4_tokenizer(resolved_model),
            config.max_length,
        )
        tokenization["status"] = (
            "ready" if tokenization["ready"] else "overlength"
        )
    ready = environment["ready"] and tokenization["ready"]
    return {
        "dataset": {
            "data_version": bundle.data_version,
            "sha256": dict(bundle.sha256),
            "train_count": len(bundle.train),
            "validation_count": len(bundle.validation),
        },
        "environment": environment,
        "status": "ready" if ready else "not_ready",
        "tokenization": tokenization,
    }


def train_p4_seed(config: P4SeedTrainingConfig) -> dict[str, object]:
    bundle = load_p4_dataset_bundle(config)
    resolved_model = resolve_training_model_path(config.model_path)
    environment = inspect_training_environment_for_files(
        resolved_model,
        {
            "manifest": config.manifest_path,
            "train": config.train_path,
            "validation": config.validation_path,
        },
    )
    assert_training_ready(environment)
    tokenizer = load_p4_tokenizer(resolved_model)
    token_audit = audit_p4_token_lengths(bundle, tokenizer, config.max_length)
    assert_p4_token_lengths(token_audit)
    ensure_output_directory(config)
    return run_qlora_training(
        config,
        resolved_model,
        bundle.train,
        bundle.validation,
        build_p4_training_arguments,
        lambda trainable_parameters: build_p4_training_manifest(
            config,
            bundle,
            resolved_model=resolved_model,
            trainable_parameters=trainable_parameters,
        ),
        metrics_validator=validate_finite_training_metrics,
        oom_retry_command=(
            "python scripts/train_p4_seed_qlora.py "
            "--lora-target attention --overwrite-output"
        ),
        record_tokenizer=tokenize_p4_training_record,
        tokenizer=tokenizer,
    )
