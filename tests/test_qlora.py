import importlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from guard.training_config import SmokeTrainingConfig


class CapturingFactory:
    def __init__(self):
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return kwargs


class FakeTorch:
    bfloat16 = "bf16"


class QloraConfigurationTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module("guard.qlora")
        except ModuleNotFoundError:
            self.fail("guard.qlora is missing")

    def test_quantization_uses_nf4_double_quant_and_bf16(self):
        api = self.api()
        factory = CapturingFactory()
        transformers = type("Transformers", (), {"BitsAndBytesConfig": factory})

        result = api.build_quantization_config(FakeTorch, transformers)

        self.assertIs(result, factory.kwargs)
        self.assertEqual(
            factory.kwargs,
            {
                "load_in_4bit": True,
                "bnb_4bit_quant_type": "nf4",
                "bnb_4bit_use_double_quant": True,
                "bnb_4bit_compute_dtype": "bf16",
            },
        )

    def test_lora_targets_all_linear_or_attention_projections(self):
        api = self.api()
        factory = CapturingFactory()
        peft = type("Peft", (), {"LoraConfig": factory})

        api.build_lora_config(peft, "all-linear")
        self.assertEqual(factory.kwargs["target_modules"], "all-linear")
        self.assertEqual(factory.kwargs["r"], 8)
        self.assertEqual(factory.kwargs["lora_alpha"], 16)

        api.build_lora_config(peft, "attention")
        self.assertEqual(
            factory.kwargs["target_modules"],
            ["q_proj", "k_proj", "v_proj", "o_proj"],
        )

    def test_training_arguments_match_smoke_contract(self):
        api = self.api()
        factory = CapturingFactory()
        transformers = type("Transformers", (), {"TrainingArguments": factory})
        config = SmokeTrainingConfig(output_dir=Path("out"))

        api.build_training_arguments(transformers, config)

        self.assertEqual(factory.kwargs["per_device_train_batch_size"], 1)
        self.assertEqual(factory.kwargs["gradient_accumulation_steps"], 8)
        self.assertEqual(factory.kwargs["num_train_epochs"], 1.0)
        self.assertEqual(factory.kwargs["learning_rate"], 2e-4)
        self.assertEqual(factory.kwargs["optim"], "paged_adamw_8bit")
        self.assertTrue(factory.kwargs["bf16"])
        self.assertEqual(factory.kwargs["eval_strategy"], "epoch")
        self.assertEqual(factory.kwargs["save_strategy"], "no")

    def test_existing_output_is_protected_and_manifest_is_explicit(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "output"
            output.mkdir()
            (output / "keep.txt").write_text("keep", encoding="utf-8")
            config = SmokeTrainingConfig(output_dir=output)
            with self.assertRaisesRegex(api.QloraError, "already contains files"):
                api.ensure_output_directory(config)

            overwritten = SmokeTrainingConfig(output_dir=output, overwrite_output=True)
            api.ensure_output_directory(overwritten)
            self.assertTrue(output.is_dir())
            self.assertEqual(list(output.iterdir()), [])
            backups = list(output.parent.glob("output.previous-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / "keep.txt").read_text(encoding="utf-8"), "keep")

        manifest = api.build_training_manifest(
            SmokeTrainingConfig(model_path=Path("model")),
            train_count=96,
            validation_count=24,
            trainable_parameters=1234,
        )
        self.assertEqual(manifest["method"], "qlora-smoke")
        self.assertEqual(manifest["train_count"], 96)
        self.assertEqual(manifest["validation_count"], 24)
        self.assertEqual(manifest["trainable_parameters"], 1234)
        self.assertFalse(manifest["quality_milestone"])

    def test_full_model_weight_patterns_are_rejected(self):
        api = self.api()
        forbidden = (
            "model.safetensors",
            "model-00001-of-00002.safetensors",
            "model.safetensors.index.json",
            "pytorch_model.bin",
            "pytorch_model-00001-of-00002.bin",
            "pytorch_model.bin.index.json",
        )
        for name in forbidden:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    adapter = Path(temporary_directory)
                    (adapter / name).write_text("weight", encoding="utf-8")
                    with self.assertRaisesRegex(api.QloraError, "full-model"):
                        api.assert_adapter_only_output(adapter)

    def test_full_model_weights_are_rejected_recursively(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as temporary_directory:
            adapter = Path(temporary_directory)
            nested = adapter / "unexpected"
            nested.mkdir()
            (nested / "model.safetensors").write_text("weight", encoding="utf-8")

            with self.assertRaisesRegex(api.QloraError, "unexpected/model.safetensors"):
                api.assert_adapter_only_output(adapter)

    def test_checkpoint_pruning_keeps_only_selected_best_checkpoint(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as temporary_directory:
            trainer = Path(temporary_directory) / "trainer"
            best = trainer / "checkpoint-5"
            final = trainer / "checkpoint-10"
            best.mkdir(parents=True)
            final.mkdir()

            api.prune_trainer_checkpoints(trainer, best)

            self.assertTrue(best.is_dir())
            self.assertFalse(final.exists())
            self.assertEqual([path.name for path in trainer.iterdir()], ["checkpoint-5"])

    def test_runtime_failures_become_concise_domain_errors(self):
        api = self.api()

        class OutOfMemoryError(RuntimeError):
            pass

        torch = type(
            "Torch", (), {"cuda": type("Cuda", (), {"OutOfMemoryError": OutOfMemoryError})}
        )
        oom = api.training_runtime_error(
            OutOfMemoryError("allocation failed"),
            torch,
            "python retry.py --smaller",
        )
        load = api.training_runtime_error(
            ValueError("bad local config"), torch, "python retry.py --smaller"
        )

        self.assertIsInstance(oom, api.QloraError)
        self.assertIn("CUDA out of memory", str(oom))
        self.assertIn("python retry.py --smaller", str(oom))
        self.assertNotIn("Traceback", str(oom))
        self.assertEqual(
            str(load), "QLoRA training failed (ValueError): bad local config"
        )


if __name__ == "__main__":
    unittest.main()
