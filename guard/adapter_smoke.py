"""Adapter-generation parsing and the local post-training smoke check."""

import json
from pathlib import Path
import time

from .contracts import GuardResult
from .qlora import build_quantization_config, _load_split
from .result_parsing import GeneratedResultError, extract_first_json_object as _extract_json
from .training_config import resolve_training_model_path
from .training_data import format_training_messages


class AdapterSmokeError(RuntimeError):
    """Raised when adapter output is absent or violates GuardResult V1."""


def validate_adapter_artifacts(
    adapter_dir: Path, expected_model: Path | None = None
) -> dict[str, object]:
    required = (
        adapter_dir / "adapter_config.json",
        adapter_dir.parent / "training_manifest.json",
        adapter_dir.parent / "training_metrics.json",
    )
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
        raise AdapterSmokeError(
            f"adapter artifacts are incomplete in {adapter_dir}: " + ", ".join(missing)
        )
    try:
        manifest = json.loads(required[1].read_text(encoding="utf-8"))
        json.loads(required[0].read_text(encoding="utf-8"))
        json.loads(required[2].read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise AdapterSmokeError(f"adapter artifact JSON is invalid: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("method") != "qlora-smoke":
        raise AdapterSmokeError("training_manifest.json has an unexpected method")
    if manifest.get("data_version") != "smoke-v1":
        raise AdapterSmokeError("training_manifest.json has an unexpected data_version")
    if expected_model is not None:
        recorded_model = manifest.get("base_model_path")
        if not isinstance(recorded_model, str) or (
            Path(recorded_model).resolve() != expected_model.resolve()
        ):
            raise AdapterSmokeError(
                "training_manifest.json base model does not match the requested model"
            )
    return manifest


def extract_first_json_object(text: str) -> dict[str, object]:
    """Compatibility wrapper around the shared generated-result extractor."""
    try:
        return _extract_json(text)
    except GeneratedResultError as exc:
        raise AdapterSmokeError(str(exc)) from exc


def validate_generated_result(text: str) -> GuardResult:
    value = extract_first_json_object(text)
    try:
        return GuardResult.model_validate(value)
    except ValueError as exc:
        raise AdapterSmokeError(f"generated JSON is not a valid GuardResult: {exc}") from exc


def write_adapter_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def load_adapter_runtime(
    adapter_dir: Path,
    resolved_model: Path,
    peft_module,
    torch_module,
    transformers_module,
):
    try:
        tokenizer = transformers_module.AutoTokenizer.from_pretrained(
            adapter_dir, local_files_only=True
        )
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        model = transformers_module.AutoModelForCausalLM.from_pretrained(
            resolved_model,
            quantization_config=build_quantization_config(
                torch_module, transformers_module
            ),
            device_map={"": 0},
            dtype=torch_module.bfloat16,
            local_files_only=True,
        )
        model = peft_module.PeftModel.from_pretrained(
            model, adapter_dir, is_trainable=False
        )
    except Exception as exc:
        raise AdapterSmokeError(f"could not load adapter runtime: {exc}") from exc
    return tokenizer, model


def smoke_test_adapter(
    adapter_dir: Path,
    data_dir: Path,
    model_path: Path | None,
    report_path: Path,
    max_new_tokens: int = 256,
) -> dict[str, object]:
    resolved_model = resolve_training_model_path(model_path)
    validate_adapter_artifacts(adapter_dir, resolved_model)
    records = _load_split(data_dir / "validation.jsonl")
    if not records:
        raise AdapterSmokeError("validation split is empty")
    record = records[0]
    try:
        import peft
        import torch
        import transformers
    except ImportError as exc:
        raise AdapterSmokeError(f"missing inference dependency: {exc.name}") from exc

    tokenizer, model = load_adapter_runtime(
        adapter_dir, resolved_model, peft, torch, transformers
    )
    model.eval()
    messages = format_training_messages(record)[:2]
    prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
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
        result = validate_generated_result(raw_text)
        report["actual_category"] = result.category.value
        report["category_match"] = result.category is record.result.category
        report["result"] = result.model_dump(mode="json")
        report["valid"] = True
    finally:
        write_adapter_report(report_path, report)
    return report
