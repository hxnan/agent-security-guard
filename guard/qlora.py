"""Minimal local QLoRA training orchestration with lazy ML imports."""

from dataclasses import asdict
from fnmatch import fnmatch
import hashlib
import json
from pathlib import Path
import shutil
import time
from typing import Callable

from .contracts import GuardRequest, GuardResult
from .smoke_data import SmokeRecord, load_eval_templates, validate_smoke_records
from .training_config import (
    assert_training_ready,
    inspect_training_environment,
    resolve_training_model_path,
    SmokeTrainingConfig,
)
from .training_data import CausalJsonCollator, tokenize_training_record


class QloraError(RuntimeError):
    """Raised when the smoke trainer cannot safely proceed."""


def build_quantization_config(torch_module, transformers_module):
    return transformers_module.BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch_module.bfloat16,
    )


def build_lora_config(peft_module, target: str):
    modules = (
        "all-linear"
        if target == "all-linear"
        else ["q_proj", "k_proj", "v_proj", "o_proj"]
    )
    return peft_module.LoraConfig(
        r=8,
        lora_alpha=16,
        target_modules=modules,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )


def build_training_arguments(transformers_module, config: SmokeTrainingConfig):
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
        save_strategy="no",
        logging_steps=1,
        report_to="none",
        remove_unused_columns=False,
        seed=config.seed,
        data_seed=config.seed,
    )


def ensure_output_directory(config: SmokeTrainingConfig) -> None:
    if config.output_dir.exists() and any(config.output_dir.iterdir()):
        if not config.overwrite_output:
            raise QloraError(
                f"output directory already contains files: {config.output_dir}; "
                "pass --overwrite-output only for this explicit output directory"
            )
        backup = config.output_dir.with_name(
            f"{config.output_dir.name}.previous-{time.time_ns()}"
        )
        config.output_dir.replace(backup)
    config.output_dir.mkdir(parents=True, exist_ok=True)


def assert_adapter_only_output(adapter_dir: Path) -> None:
    forbidden_patterns = (
        "model.safetensors",
        "model-*.safetensors",
        "model.safetensors.index.json",
        "pytorch_model.bin",
        "pytorch_model-*.bin",
        "pytorch_model.bin.index.json",
    )
    forbidden = sorted(
        str(path.relative_to(adapter_dir))
        for path in adapter_dir.rglob("*")
        if path.is_file()
        and any(fnmatch(path.name, pattern) for pattern in forbidden_patterns)
    )
    if forbidden:
        raise QloraError(
            "full-model weight file found in adapter output: " + ", ".join(forbidden)
        )


def adapter_artifact_sha256(adapter_dir: Path) -> dict[str, str]:
    config_path = adapter_dir / "adapter_config.json"
    tokenizer_config_path = adapter_dir / "tokenizer_config.json"
    weights = [
        path
        for path in (
            adapter_dir / "adapter_model.safetensors",
            adapter_dir / "adapter_model.bin",
        )
        if path.is_file()
    ]
    if (
        not config_path.is_file()
        or not tokenizer_config_path.is_file()
        or len(weights) != 1
    ):
        raise QloraError(
            "adapter output must contain adapter_config.json, tokenizer_config.json, "
            "and exactly one weight file"
        )
    paths = sorted(
        (path for path in adapter_dir.rglob("*") if path.is_file()),
        key=lambda path: str(path.relative_to(adapter_dir)),
    )
    try:
        return {
            str(path.relative_to(adapter_dir)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in paths
        }
    except OSError as exc:
        raise QloraError(f"cannot hash adapter artifact: {exc}") from exc


def prune_trainer_checkpoints(
    trainer_dir: Path, best_checkpoint: str | Path | None
) -> None:
    """Enforce the pilot's one-checkpoint retention contract."""
    checkpoints = sorted(
        (path for path in trainer_dir.glob("checkpoint-*") if path.is_dir()),
        key=lambda path: path.name,
    )
    if len(checkpoints) <= 1:
        return
    if best_checkpoint is None:
        raise QloraError(
            "multiple trainer checkpoints exist but no best checkpoint was selected"
        )
    selected = Path(best_checkpoint).resolve()
    if selected not in {path.resolve() for path in checkpoints}:
        raise QloraError(
            f"selected best checkpoint is missing from trainer output: {selected}"
        )
    try:
        for checkpoint in checkpoints:
            if checkpoint.resolve() != selected:
                shutil.rmtree(checkpoint)
    except OSError as exc:
        raise QloraError(f"cannot prune trainer checkpoints: {exc}") from exc


def training_runtime_error(
    exc: Exception, torch_module, oom_retry_command: str
) -> QloraError:
    oom_type = getattr(getattr(torch_module, "cuda", None), "OutOfMemoryError", None)
    if isinstance(oom_type, type) and isinstance(exc, oom_type):
        return QloraError(f"CUDA out of memory; retry: {oom_retry_command}")
    return QloraError(f"QLoRA training failed ({type(exc).__name__}): {exc}")


def build_training_manifest(
    config: SmokeTrainingConfig,
    train_count: int,
    validation_count: int,
    trainable_parameters: int,
) -> dict[str, object]:
    return {
        "base_model_path": str(config.model_path or "environment/default"),
        "data_version": "smoke-v1",
        "gradient_accumulation_steps": config.gradient_accumulation_steps,
        "learning_rate": config.learning_rate,
        "lora_target": config.lora_target,
        "max_length": config.max_length,
        "method": "qlora-smoke",
        "micro_batch_size": config.micro_batch_size,
        "num_train_epochs": config.num_train_epochs,
        "quality_milestone": False,
        "seed": config.seed,
        "train_count": train_count,
        "trainable_parameters": trainable_parameters,
        "validation_count": validation_count,
    }


def _load_split(path: Path) -> list[SmokeRecord]:
    records = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            try:
                value = json.loads(line)
                records.append(
                    SmokeRecord(
                        sample_id=value["sample_id"],
                        data_version=value["data_version"],
                        split=value["split"],
                        semantic_template=value["semantic_template"],
                        generation_source=value["generation_source"],
                        request=GuardRequest.model_validate(value["request"]),
                        result=GuardResult.model_validate(value["result"]),
                    )
                )
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                raise QloraError(f"{path}: line {line_number}: invalid smoke record: {exc}") from exc
    return records


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def run_qlora_training(
    config,
    model_path: Path,
    train_records,
    validation_records,
    arguments_builder: Callable,
    manifest_builder: Callable[[int], dict[str, object]],
    *,
    metrics_validator: Callable[[dict[str, object]], None] | None = None,
    oom_retry_command: str,
    record_tokenizer: Callable = tokenize_training_record,
) -> dict[str, object]:
    try:
        import peft
        import torch
        import transformers
    except ImportError as exc:
        raise QloraError(f"missing training dependency: {exc.name}") from exc

    try:
        transformers.set_seed(config.seed)
        tokenizer = transformers.AutoTokenizer.from_pretrained(
            model_path, local_files_only=True
        )
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        train_data = [
            record_tokenizer(record, tokenizer, config.max_length)
            for record in train_records
        ]
        validation_data = [
            record_tokenizer(record, tokenizer, config.max_length)
            for record in validation_records
        ]

        quantization_config = build_quantization_config(torch, transformers)
        model = transformers.AutoModelForCausalLM.from_pretrained(
            model_path,
            quantization_config=quantization_config,
            device_map={"": 0},
            dtype=torch.bfloat16,
            local_files_only=True,
        )
        model.config.use_cache = False
        model = peft.prepare_model_for_kbit_training(
            model, use_gradient_checkpointing=True
        )
        model = peft.get_peft_model(
            model, build_lora_config(peft, config.lora_target)
        )
        trainable_parameters = sum(
            parameter.numel()
            for parameter in model.parameters()
            if parameter.requires_grad
        )
        trainer = transformers.Trainer(
            model=model,
            args=arguments_builder(transformers, config),
            train_dataset=train_data,
            eval_dataset=validation_data,
            data_collator=CausalJsonCollator(tokenizer),
            processing_class=tokenizer,
        )
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        train_result = trainer.train()
        evaluation = trainer.evaluate()
        prune_trainer_checkpoints(
            config.output_dir / "trainer",
            getattr(getattr(trainer, "state", None), "best_model_checkpoint", None),
        )
        elapsed = time.perf_counter() - started
        metrics = {
            "elapsed_seconds": round(elapsed, 3),
            "evaluation": evaluation,
            "peak_gpu_memory_mb": round(
                torch.cuda.max_memory_allocated() / 1024**2, 2
            ),
            "training": train_result.metrics,
        }
        if metrics_validator is not None:
            metrics_validator(metrics)

        adapter_dir = config.output_dir / "adapter"
        model.save_pretrained(adapter_dir, safe_serialization=True)
        tokenizer.save_pretrained(adapter_dir)
        manifest = manifest_builder(trainable_parameters)
        manifest["adapter_sha256"] = adapter_artifact_sha256(adapter_dir)
        _write_json(config.output_dir / "training_manifest.json", manifest)
        _write_json(config.output_dir / "training_metrics.json", metrics)
        assert_adapter_only_output(adapter_dir)
        return {
            "manifest": manifest,
            "metrics": metrics,
            "adapter_dir": str(adapter_dir),
        }
    except QloraError:
        raise
    except Exception as exc:
        raise training_runtime_error(exc, torch, oom_retry_command) from exc


def train_smoke(config: SmokeTrainingConfig) -> dict[str, object]:
    ensure_output_directory(config)
    model_path = resolve_training_model_path(config.model_path)
    train_records = _load_split(config.data_dir / "train.jsonl")
    validation_records = _load_split(config.data_dir / "validation.jsonl")
    validate_smoke_records(
        train_records, validation_records, eval_templates=load_eval_templates()
    )
    report = inspect_training_environment(model_path, config.data_dir)
    assert_training_ready(report)
    manifest_config = SmokeTrainingConfig(**{**asdict(config), "model_path": model_path})
    return run_qlora_training(
        config,
        model_path,
        train_records,
        validation_records,
        build_training_arguments,
        lambda trainable_parameters: build_training_manifest(
            manifest_config,
            len(train_records),
            len(validation_records),
            trainable_parameters,
        ),
        oom_retry_command=(
            "python scripts/train_smoke_qlora.py --max-length 256 "
            "--lora-target attention --overwrite-output"
        ),
    )
