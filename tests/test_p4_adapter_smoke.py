import hashlib
import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from guard.p4_adapter_smoke import (
    P4AdapterSmokeError,
    inference_runtime_error,
    validate_p4_generated_result,
    validate_p4_adapter_artifacts,
)
from guard.p4_qlora import EXPECTED_P4_SHA256
from scripts.smoke_test_p4_adapter import main as smoke_cli_main


def write_pilot_artifacts(output: Path, model_path: Path) -> Path:
    adapter = output / "adapter"
    adapter.mkdir(parents=True)
    (adapter / "adapter_config.json").write_text(
        json.dumps(
            {
                "base_model_name_or_path": str(model_path),
                "bias": "none",
                "lora_alpha": 16,
                "lora_dropout": 0.05,
                "peft_type": "LORA",
                "r": 8,
                "alpha_pattern": {},
                "modules_to_save": None,
                "rank_pattern": {},
                "target_modules": [
                    "down_proj",
                    "gate_proj",
                    "k_proj",
                    "o_proj",
                    "q_proj",
                    "up_proj",
                    "v_proj",
                ],
                "task_type": "CAUSAL_LM",
                "target_parameters": None,
                "use_dora": False,
                "use_rslora": False,
            }
        ),
        encoding="utf-8",
    )
    (adapter / "adapter_model.safetensors").write_text("weights", encoding="utf-8")
    (adapter / "tokenizer_config.json").write_text(
        json.dumps({"model_max_length": 512}), encoding="utf-8"
    )
    (output / "training_metrics.json").write_text(
        json.dumps(
            {
                "training": {"train_loss": 0.5},
                "evaluation": {"eval_loss": 0.4},
            }
        ),
        encoding="utf-8",
    )
    manifest = json.dumps(
        {
                "adapter_sha256": {
                    str(path.relative_to(adapter)): hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
                    for path in adapter.rglob("*")
                    if path.is_file()
                },
                "base_model_path": str(model_path),
                "data_version": "p4-seed-v1",
                "dataset_sha256": EXPECTED_P4_SHA256,
                "method": "qlora-p4-seed-pilot",
                "lora": {
                    "alpha": 16,
                    "bias": "none",
                    "dropout": 0.05,
                    "rank": 8,
                    "target_policy": "all-linear",
                    "task_type": "CAUSAL_LM",
                },
                "quantization": {
                    "bits": 4,
                    "compute_dtype": "bfloat16",
                    "double_quant": True,
                    "quant_type": "nf4",
                },
                "optimizer": "paged_adamw_8bit",
                "gradient_checkpointing": True,
                "precision": {"bf16": True, "fp16": False},
                "warmup_ratio": 0.03,
                "max_grad_norm": 0.3,
                "gradient_accumulation_steps": 16,
                "learning_rate": 1e-4,
                "max_length": 512,
                "micro_batch_size": 1,
                "num_train_epochs": 2.0,
                "seed": 42,
                "train_count": 800,
                "trainable_parameters": 123456,
                "validation_count": 200,
                "checkpoint_policy": {
                    "eval_strategy": "epoch",
                    "greater_is_better": False,
                    "load_best_model_at_end": True,
                    "max_retained": 1,
                    "metric_for_best_model": "eval_loss",
                    "save_strategy": "epoch",
                },
                "quality_milestone": False,
                "training_prompt_version": "baseline-prompt-v2",
                "training_target": "baseline-semantic-v2",
        }
    )
    (output / "training_manifest.json").write_text(manifest, encoding="utf-8")
    return adapter


class P4AdapterArtifactTests(unittest.TestCase):
    def test_generated_result_uses_six_field_baseline_parser(self):
        semantic = {
            "decision": "allow",
            "severity": "none",
            "category": "benign",
            "summary": "查看本地分支列表",
            "confidence": 0.95,
            "evidence": ["git branch --list 'feature-1'"],
        }

        result = validate_p4_generated_result(
            json.dumps(semantic, ensure_ascii=False)
        )

        self.assertEqual(result.category.value, "benign")
        self.assertEqual(result.model_version, "qwen2.5-1.5b-instruct-baseline-v1")
        with self.assertRaisesRegex(P4AdapterSmokeError, "extra"):
            validate_p4_generated_result(
                json.dumps({**semantic, "risk": False}, ensure_ascii=False)
            )
    def test_valid_pilot_artifacts_require_method_hash_metrics_and_base_model(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            model = Path(directory) / "model"
            model.mkdir()
            adapter = write_pilot_artifacts(output, model)

            manifest = validate_p4_adapter_artifacts(adapter, model)

        self.assertEqual(manifest["method"], "qlora-p4-seed-pilot")
        self.assertEqual(manifest["dataset_sha256"], EXPECTED_P4_SHA256)

    def test_wrong_method_hash_or_model_is_rejected(self):
        mutations = (
            ("method", "qlora-smoke", "method"),
            ("dataset_sha256", {"train": "0" * 64}, "SHA-256"),
            ("base_model_path", "/different/model", "base model"),
        )
        for field, value, message in mutations:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as directory:
                    output = Path(directory) / "output"
                    model = Path(directory) / "model"
                    model.mkdir()
                    adapter = write_pilot_artifacts(output, model)
                    manifest_path = output / "training_manifest.json"
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest[field] = value
                    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

                    with self.assertRaisesRegex(P4AdapterSmokeError, message):
                        validate_p4_adapter_artifacts(adapter, model)

    def test_adapter_config_must_match_manifest_and_base_model(self):
        mutations = (
            ("base_model_name_or_path", "/different/model", "base model"),
            ("peft_type", "IA3", "peft_type"),
            ("task_type", "SEQ_CLS", "task_type"),
            ("r", 4, "rank"),
            ("lora_alpha", 8, "alpha"),
            ("lora_dropout", 0.1, "dropout"),
            (
                "target_modules",
                [
                    "down_proj",
                    "gate_proj",
                    "k_proj",
                    "lm_head",
                    "o_proj",
                    "q_proj",
                    "up_proj",
                    "v_proj",
                ],
                "target modules",
            ),
            ("modules_to_save", ["lm_head"], "modules_to_save"),
            ("use_rslora", True, "use_rslora"),
            ("use_dora", True, "use_dora"),
            ("rank_pattern", {"q_proj": 4}, "rank_pattern"),
            ("alpha_pattern", {"q_proj": 8}, "alpha_pattern"),
            ("target_parameters", ["lm_head.weight"], "target_parameters"),
        )
        for field, value, message in mutations:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as directory:
                    output = Path(directory) / "output"
                    model = Path(directory) / "model"
                    model.mkdir()
                    adapter = write_pilot_artifacts(output, model)
                    config_path = adapter / "adapter_config.json"
                    config = json.loads(config_path.read_text(encoding="utf-8"))
                    config[field] = value
                    config_path.write_text(json.dumps(config), encoding="utf-8")

                    with self.assertRaisesRegex(P4AdapterSmokeError, message):
                        validate_p4_adapter_artifacts(adapter, model)

    def test_missing_or_nonfinite_metrics_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            model = Path(directory) / "model"
            model.mkdir()
            adapter = write_pilot_artifacts(output, model)
            (output / "training_metrics.json").write_text(
                json.dumps({"evaluation": {"eval_loss": float("nan")}}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(P4AdapterSmokeError, "finite"):
                validate_p4_adapter_artifacts(adapter, model)

            (output / "training_metrics.json").unlink()
            with self.assertRaisesRegex(P4AdapterSmokeError, "training_metrics"):
                validate_p4_adapter_artifacts(adapter, model)

    def test_full_model_weights_are_rejected_even_with_valid_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            model = Path(directory) / "model"
            model.mkdir()
            adapter = write_pilot_artifacts(output, model)
            (adapter / "model.safetensors").write_text(
                "forbidden full weights", encoding="utf-8"
            )

            with self.assertRaisesRegex(P4AdapterSmokeError, "full-model"):
                validate_p4_adapter_artifacts(adapter, model)

    def test_adapter_weight_substitution_is_rejected_by_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            model = Path(directory) / "model"
            model.mkdir()
            adapter = write_pilot_artifacts(output, model)
            (adapter / "adapter_model.safetensors").write_text(
                "substituted weights", encoding="utf-8"
            )

            with self.assertRaisesRegex(P4AdapterSmokeError, "artifact SHA-256"):
                validate_p4_adapter_artifacts(adapter, model)

    def test_tokenizer_substitution_is_rejected_by_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            model = Path(directory) / "model"
            model.mkdir()
            adapter = write_pilot_artifacts(output, model)
            (adapter / "tokenizer_config.json").write_text(
                json.dumps({"model_max_length": 1}), encoding="utf-8"
            )

            with self.assertRaisesRegex(P4AdapterSmokeError, "artifact SHA-256"):
                validate_p4_adapter_artifacts(adapter, model)

    def test_inference_oom_and_runtime_failures_become_domain_errors(self):
        class OutOfMemoryError(RuntimeError):
            pass

        torch = type(
            "Torch", (), {"cuda": type("Cuda", (), {"OutOfMemoryError": OutOfMemoryError})}
        )

        oom = inference_runtime_error(OutOfMemoryError("allocation failed"), torch)
        backend = inference_runtime_error(ValueError("bad tokenizer"), torch)

        self.assertIn("CUDA out of memory", str(oom))
        self.assertEqual(
            str(backend), "P4 adapter smoke failed (ValueError): bad tokenizer"
        )


class P4AdapterSmokeCliTests(unittest.TestCase):
    def test_missing_adapter_is_json_failure_without_loading_model(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/smoke_test_p4_adapter.py",
                    "--adapter-dir",
                    str(Path(directory) / "missing-adapter"),
                ],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stderr, "")
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertIn("incomplete", payload["errors"][0])
        self.assertNotIn("Traceback", completed.stdout)

    def test_invalid_argument_is_json_failure(self):
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/smoke_test_p4_adapter.py",
                "--max-new-tokens",
                "invalid",
            ],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stderr, "")
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertIn("argument error", payload["errors"][0])

    def test_inference_domain_error_is_single_json_failure(self):
        output = StringIO()
        with patch(
            "scripts.smoke_test_p4_adapter.smoke_test_p4_adapter",
            side_effect=P4AdapterSmokeError("CUDA out of memory during adapter smoke"),
        ), redirect_stdout(output):
            exit_code = smoke_cli_main([])

        self.assertEqual(exit_code, 1)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "failed")
        self.assertIn("CUDA out of memory", payload["errors"][0])
        self.assertNotIn("Traceback", output.getvalue())


if __name__ == "__main__":
    unittest.main()
