import importlib
from pathlib import Path
import tempfile
import unittest


class TrainingConfigTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module("guard.training_config")
        except ModuleNotFoundError:
            self.fail("guard.training_config is missing")

    def test_defaults_match_six_gb_smoke_contract(self):
        api = self.api()
        config = api.SmokeTrainingConfig()

        self.assertEqual(config.max_length, 512)
        self.assertEqual(config.num_train_epochs, 1.0)
        self.assertEqual(config.micro_batch_size, 1)
        self.assertEqual(config.gradient_accumulation_steps, 8)
        self.assertEqual(config.learning_rate, 2e-4)
        self.assertEqual(config.lora_target, "all-linear")

    def test_nonpositive_numeric_values_are_rejected(self):
        api = self.api()
        for field, value in (
            ("max_length", 0),
            ("num_train_epochs", 0),
            ("micro_batch_size", -1),
            ("gradient_accumulation_steps", 0),
            ("learning_rate", 0),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(api.TrainingConfigError, field):
                    api.SmokeTrainingConfig(**{field: value})

    def test_model_path_precedence_uses_existing_environment_contract(self):
        api = self.api()
        self.assertEqual(
            api.resolve_training_model_path("explicit", {"AGENT_SECURITY_MODEL_PATH": "env"}),
            Path("explicit"),
        )
        self.assertEqual(
            api.resolve_training_model_path(None, {"AGENT_SECURITY_MODEL_PATH": "env"}),
            Path("env"),
        )


class TrainingEnvironmentTests(unittest.TestCase):
    expected_versions = {
        "accelerate": "1.14.0",
        "bitsandbytes": "0.49.2",
        "numpy": "1.26.4",
        "peft": "0.20.0",
        "safetensors": "0.8.0",
        "torch": "2.5.1+cu124",
        "transformers": "4.57.6",
    }

    def api(self):
        return importlib.import_module("guard.training_config")

    def make_layout(self, root):
        model_path = root / "model"
        model_path.mkdir()
        for name in (
            "config.json",
            "generation_config.json",
            "model.safetensors",
            "tokenizer.json",
            "tokenizer_config.json",
        ):
            (model_path / name).write_text("{}", encoding="utf-8")
        data_dir = root / "data"
        data_dir.mkdir()
        (data_dir / "train.jsonl").write_text("{}\n", encoding="utf-8")
        (data_dir / "validation.jsonl").write_text("{}\n", encoding="utf-8")
        return model_path, data_dir

    def test_ready_report_is_deterministic(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as temporary_directory:
            model_path, data_dir = self.make_layout(Path(temporary_directory))
            report = api.inspect_training_environment(
                model_path,
                data_dir,
                package_version=lambda name: self.expected_versions.get(name),
                cuda_probe=lambda: {
                    "available": True,
                    "bf16_supported": True,
                    "gpu_name": "Test Ada GPU",
                    "total_memory_bytes": 6 * 1024**3,
                    "free_memory_bytes": int(5.75 * 1024**3),
                },
            )

        self.assertTrue(report["ready"])
        self.assertEqual(report["package_mismatches"], [])
        self.assertEqual(report["gpu_memory_gb"], 6.0)
        self.assertEqual(report["gpu_free_memory_gb"], 5.75)
        self.assertEqual(report["missing_model_files"], [])
        self.assertEqual(report["missing_data_files"], [])
        api.assert_training_ready(report)

    def test_reports_all_missing_prerequisites(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            report = api.inspect_training_environment(
                root / "missing-model",
                root / "missing-data",
                package_version=lambda name: None,
                cuda_probe=lambda: {
                    "available": False,
                    "bf16_supported": False,
                    "gpu_name": None,
                    "total_memory_bytes": 0,
                },
            )

        self.assertFalse(report["ready"])
        self.assertEqual(len(report["package_mismatches"]), 7)
        self.assertIn("train.jsonl", report["missing_data_files"])
        with self.assertRaisesRegex(api.TrainingEnvironmentError, "CUDA is unavailable"):
            api.assert_training_ready(report)

    def test_wrong_version_and_insufficient_memory_are_not_ready(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as temporary_directory:
            model_path, data_dir = self.make_layout(Path(temporary_directory))
            versions = dict(self.expected_versions, peft="0.19.0")
            report = api.inspect_training_environment(
                model_path,
                data_dir,
                package_version=lambda name: versions.get(name),
                cuda_probe=lambda: {
                    "available": True,
                    "bf16_supported": True,
                    "gpu_name": "Small GPU",
                    "total_memory_bytes": 4 * 1024**3,
                },
            )

        self.assertFalse(report["ready"])
        self.assertIn("peft: expected 0.20.0, got 0.19.0", report["package_mismatches"])
        with self.assertRaisesRegex(api.TrainingEnvironmentError, "at least 5.5 GB"):
            api.assert_training_ready(report)

    def test_busy_gpu_with_insufficient_free_memory_is_not_ready(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as temporary_directory:
            model_path, data_dir = self.make_layout(Path(temporary_directory))
            report = api.inspect_training_environment(
                model_path,
                data_dir,
                package_version=lambda name: self.expected_versions.get(name),
                cuda_probe=lambda: {
                    "available": True,
                    "bf16_supported": True,
                    "gpu_name": "Busy Ada GPU",
                    "total_memory_bytes": 6 * 1024**3,
                    "free_memory_bytes": 2 * 1024**3,
                },
            )

        self.assertFalse(report["ready"])
        self.assertEqual(report["gpu_free_memory_gb"], 2.0)
        with self.assertRaisesRegex(api.TrainingEnvironmentError, "free GPU memory"):
            api.assert_training_ready(report)


if __name__ == "__main__":
    unittest.main()
