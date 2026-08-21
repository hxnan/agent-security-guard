import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from guard.p4_qlora import (
    EXPECTED_P4_SHA256,
    P4QloraError,
    audit_p4_token_lengths,
    build_p4_training_arguments,
    build_p4_training_manifest,
    format_p4_training_messages,
    load_p4_dataset_bundle,
    preflight_p4_seed_training,
    train_p4_seed,
    validate_finite_training_metrics,
)
from guard.training_config import P4SeedTrainingConfig, TrainingConfigError


class P4SeedTrainingConfigTests(unittest.TestCase):
    def test_defaults_match_six_gb_pilot_contract(self):
        config = P4SeedTrainingConfig()

        self.assertEqual(config.max_length, 576)
        self.assertEqual(config.num_train_epochs, 2.0)
        self.assertEqual(config.micro_batch_size, 1)
        self.assertEqual(config.gradient_accumulation_steps, 16)
        self.assertEqual(config.learning_rate, 1e-4)
        self.assertEqual(config.lora_target, "all-linear")
        self.assertEqual(config.seed, 42)
        self.assertEqual(config.output_dir.name, "p4-seed-qlora-pilot-v1")

    def test_invalid_numeric_and_lora_values_are_rejected(self):
        for field, value in (
            ("max_length", 0),
            ("num_train_epochs", float("nan")),
            ("micro_batch_size", -1),
            ("gradient_accumulation_steps", 0),
            ("learning_rate", float("inf")),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(TrainingConfigError, field):
                    P4SeedTrainingConfig(**{field: value})

        with self.assertRaisesRegex(TrainingConfigError, "lora_target"):
            P4SeedTrainingConfig(lora_target="unsupported")


class P4DatasetBundleTests(unittest.TestCase):
    def test_committed_bundle_loads_exact_rows_hashes_and_normalized_records(self):
        bundle = load_p4_dataset_bundle(P4SeedTrainingConfig())

        self.assertEqual((len(bundle.train), len(bundle.validation)), (800, 200))
        self.assertEqual(bundle.sha256, EXPECTED_P4_SHA256)
        self.assertEqual(bundle.train[0].sample_id, "TR-000001")
        self.assertEqual(bundle.train[0].request.command, "git branch --list 'feature-1'")
        self.assertEqual(bundle.validation[-1].sample_id, "TR-001000")
        self.assertEqual(bundle.data_version, "p4-seed-v1")

    def test_manifest_hash_drift_is_rejected(self):
        root = Path(__file__).resolve().parents[1]
        source_manifest = (
            root / "data" / "train" / "agent_security_seed_v1_manifest.json"
        )
        manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
        manifest["sha256"]["train"] = "0" * 64

        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            config = P4SeedTrainingConfig(manifest_path=manifest_path)

            with self.assertRaisesRegex(P4QloraError, "manifest SHA-256"):
                load_p4_dataset_bundle(config)

    def test_actual_file_hash_drift_is_rejected_before_profile_validation(self):
        root = Path(__file__).resolve().parents[1]
        source_train = root / "data" / "train" / "agent_security_train_v1.jsonl"

        with tempfile.TemporaryDirectory() as directory:
            train_path = Path(directory) / "train.jsonl"
            train_path.write_bytes(source_train.read_bytes() + b"\n")
            config = P4SeedTrainingConfig(train_path=train_path)

            with self.assertRaisesRegex(P4QloraError, "dataset SHA-256"):
                load_p4_dataset_bundle(config)


class CapturingFactory:
    def __init__(self):
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return kwargs


class P4LengthAuditTokenizer:
    eos_token_id = 2

    def apply_chat_template(self, messages, tokenize, add_generation_prompt):
        prompt = [1] * 100
        if len(messages) == 2:
            return prompt
        user_content = messages[1]["content"]
        length = 514 if "a-10.cmd" in user_content else 500
        return prompt + [3] * (length - len(prompt) - 1) + [self.eos_token_id]

    def decode(self, token_ids, skip_special_tokens=False):
        return ""


class P4TrainingContractTests(unittest.TestCase):
    ready_environment = {
        "bf16_supported": True,
        "cuda_available": True,
        "gpu_free_memory_gb": 4.96,
        "gpu_memory_gb": 6.0,
        "missing_data_files": [],
        "missing_model_files": [],
        "package_mismatches": [],
        "ready": True,
    }

    def test_length_audit_finds_real_overlength_sample_without_truncation(self):
        bundle = load_p4_dataset_bundle(P4SeedTrainingConfig())

        report = audit_p4_token_lengths(
            bundle,
            P4LengthAuditTokenizer(),
            max_length=512,
        )

        self.assertEqual(report["max_observed_length"], 514)
        self.assertEqual(report["overlength_count"], 1)
        self.assertEqual(report["overlength_samples"], ["TR-000290:514"])
        self.assertFalse(report["ready"])

    def test_preflight_includes_token_audit_when_environment_is_ready(self):
        with patch(
            "guard.p4_qlora.inspect_training_environment_for_files",
            return_value=self.ready_environment,
        ), patch(
            "guard.p4_qlora.load_p4_tokenizer",
            return_value=P4LengthAuditTokenizer(),
        ):
            report = preflight_p4_seed_training(
                P4SeedTrainingConfig(max_length=512)
            )

        self.assertEqual(report["status"], "not_ready")
        self.assertEqual(report["tokenization"]["overlength_count"], 1)
        self.assertEqual(
            report["tokenization"]["overlength_samples"], ["TR-000290:514"]
        )

    def test_default_preflight_accepts_all_records_after_full_token_audit(self):
        with patch(
            "guard.p4_qlora.inspect_training_environment_for_files",
            return_value=self.ready_environment,
        ), patch(
            "guard.p4_qlora.load_p4_tokenizer",
            return_value=P4LengthAuditTokenizer(),
        ):
            report = preflight_p4_seed_training(P4SeedTrainingConfig())

        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["tokenization"]["records_checked"], 1000)
        self.assertEqual(report["tokenization"]["max_observed_length"], 514)
        self.assertEqual(report["tokenization"]["overlength_count"], 0)

    def test_training_reuses_the_tokenizer_that_passed_the_audit(self):
        tokenizer = P4LengthAuditTokenizer()
        observed = {}

        def capture_training(*args, **kwargs):
            observed["tokenizer"] = kwargs.get("tokenizer")
            return {"tokenizer_reused": observed["tokenizer"] is tokenizer}

        with tempfile.TemporaryDirectory() as directory:
            config = P4SeedTrainingConfig(output_dir=Path(directory) / "output")
            with patch(
                "guard.p4_qlora.inspect_training_environment_for_files",
                return_value=self.ready_environment,
            ), patch(
                "guard.p4_qlora.load_p4_tokenizer", return_value=tokenizer
            ), patch(
                "guard.p4_qlora.run_qlora_training", side_effect=capture_training
            ):
                result = train_p4_seed(config)

        self.assertEqual(result, {"tokenizer_reused": True})
        self.assertIs(observed["tokenizer"], tokenizer)

    def test_overlength_audit_preserves_existing_output_before_training(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            output.mkdir()
            sentinel = output / "keep.txt"
            sentinel.write_text("keep", encoding="utf-8")
            config = P4SeedTrainingConfig(
                output_dir=output,
                max_length=512,
                overwrite_output=True,
            )

            with patch(
                "guard.p4_qlora.inspect_training_environment_for_files",
                return_value=self.ready_environment,
            ), patch(
                "guard.p4_qlora.load_p4_tokenizer",
                return_value=P4LengthAuditTokenizer(),
            ):
                try:
                    train_p4_seed(config)
                except Exception as exc:
                    error = exc
                else:
                    error = None

            self.assertIsInstance(error, P4QloraError)
            self.assertIn("TR-000290:514", str(error))
            self.assertTrue(sentinel.exists())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_training_target_matches_baseline_v2_six_field_contract(self):
        bundle = load_p4_dataset_bundle(P4SeedTrainingConfig())

        messages = format_p4_training_messages(bundle.train[0])
        assistant = json.loads(messages[2]["content"])

        self.assertEqual(
            set(assistant),
            {"decision", "severity", "category", "summary", "confidence", "evidence"},
        )
        self.assertNotIn("risk", assistant)
        self.assertNotIn("model_version", assistant)
        self.assertIn("不要输出risk", messages[0]["content"])

    def test_training_arguments_use_validation_selected_pilot_defaults(self):
        factory = CapturingFactory()
        transformers = type("Transformers", (), {"TrainingArguments": factory})
        config = P4SeedTrainingConfig(output_dir=Path("pilot-output"))

        result = build_p4_training_arguments(transformers, config)

        self.assertIs(result, factory.kwargs)
        self.assertEqual(factory.kwargs["per_device_train_batch_size"], 1)
        self.assertEqual(factory.kwargs["gradient_accumulation_steps"], 16)
        self.assertEqual(factory.kwargs["num_train_epochs"], 2.0)
        self.assertEqual(factory.kwargs["learning_rate"], 1e-4)
        self.assertEqual(factory.kwargs["eval_strategy"], "epoch")
        self.assertEqual(factory.kwargs["save_strategy"], "epoch")
        self.assertEqual(factory.kwargs["save_total_limit"], 1)
        self.assertTrue(factory.kwargs["load_best_model_at_end"])
        self.assertEqual(factory.kwargs["metric_for_best_model"], "eval_loss")
        self.assertFalse(factory.kwargs["greater_is_better"])

    def test_manifest_records_fixed_dataset_and_non_milestone_status(self):
        bundle = load_p4_dataset_bundle(P4SeedTrainingConfig())
        config = P4SeedTrainingConfig(
            model_path=Path("models/base/Qwen2.5-1.5B-Instruct")
        )

        manifest = build_p4_training_manifest(
            config,
            bundle,
            resolved_model=Path("/models/qwen"),
            trainable_parameters=123456,
        )

        self.assertEqual(manifest["method"], "qlora-p4-seed-pilot")
        self.assertEqual(manifest["data_version"], "p4-seed-v1")
        self.assertEqual(manifest["dataset_sha256"], EXPECTED_P4_SHA256)
        self.assertEqual(manifest["train_count"], 800)
        self.assertEqual(manifest["validation_count"], 200)
        self.assertEqual(manifest["base_model_path"], "/models/qwen")
        self.assertEqual(manifest["trainable_parameters"], 123456)
        self.assertEqual(
            manifest["training_prompt_version"], "baseline-prompt-v2"
        )
        self.assertEqual(manifest["training_target"], "baseline-semantic-v2")
        self.assertEqual(
            manifest["quantization"],
            {
                "bits": 4,
                "compute_dtype": "bfloat16",
                "double_quant": True,
                "quant_type": "nf4",
            },
        )
        self.assertEqual(
            manifest["lora"],
            {
                "alpha": 16,
                "bias": "none",
                "dropout": 0.05,
                "rank": 8,
                "target_policy": "all-linear",
                "task_type": "CAUSAL_LM",
            },
        )
        self.assertEqual(manifest["optimizer"], "paged_adamw_8bit")
        self.assertTrue(manifest["gradient_checkpointing"])
        self.assertEqual(
            manifest["checkpoint_policy"],
            {
                "eval_strategy": "epoch",
                "greater_is_better": False,
                "load_best_model_at_end": True,
                "max_retained": 1,
                "metric_for_best_model": "eval_loss",
                "save_strategy": "epoch",
            },
        )
        self.assertFalse(manifest["quality_milestone"])

    def test_nonfinite_training_metrics_are_rejected(self):
        validate_finite_training_metrics(
            {"training": {"train_loss": 0.5}, "evaluation": {"eval_loss": 0.4}}
        )

        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(P4QloraError, "finite"):
                    validate_finite_training_metrics(
                        {
                            "training": {"train_loss": 0.5},
                            "evaluation": {"eval_loss": value},
                        }
                    )

        for metrics in ({}, {"evaluation": {}}, {"evaluation": {"eval_loss": "0.4"}}):
            with self.subTest(metrics=metrics):
                with self.assertRaisesRegex(P4QloraError, "eval_loss"):
                    validate_finite_training_metrics(metrics)


if __name__ == "__main__":
    unittest.main()
