from contextlib import nullcontext
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from guard.p4_adapter_backend import (
    P4_ADAPTER_MODEL_VERSION,
    P4_COMBINED_ADAPTER_MODEL_VERSION,
    P4AdapterBackendError,
    P4AdapterQwenBackend,
    parse_p4_adapter_semantic_result,
)


class FakeCuda:
    def is_available(self):
        return True

    def reset_peak_memory_stats(self):
        pass

    def max_memory_allocated(self):
        return 256 * 1024 * 1024


class FakeTorch:
    bfloat16 = "bf16"
    cuda = FakeCuda()

    @staticmethod
    def inference_mode():
        return nullcontext()


class FakeInputIds:
    shape = (1, 2)


class FakeInputs(dict):
    def __init__(self):
        super().__init__({"input_ids": FakeInputIds()})
        self.device = None

    def to(self, device):
        self.device = device
        return self


class FakeTokenizer:
    pad_token_id = 151643
    eos_token_id = 151645

    def apply_chat_template(self, messages, tokenize, add_generation_prompt):
        return "prompt"

    def __call__(self, prompt, return_tensors):
        return FakeInputs()

    def decode(self, tokens, skip_special_tokens):
        return (
            '{"decision":"allow","severity":"none","category":"benign",'
            '"summary":"查看仓库状态","confidence":0.99,"evidence":[]}'
        )


class FakeSequence:
    def __getitem__(self, key):
        return [11, 12, 21, 22][key]


class FakeOutput:
    def __getitem__(self, key):
        if key == 0:
            return FakeSequence()
        if isinstance(key, tuple) and key[0] == 0:
            return FakeSequence()[key[1]]
        raise IndexError(key)


class FakeModel:
    def __init__(self):
        self.eval_called = False

    def eval(self):
        self.eval_called = True
        return self

    def generate(self, **kwargs):
        return FakeOutput()


class P4AdapterBackendTests(unittest.TestCase):
    def test_adapter_parser_marks_results_with_pilot_model_version(self):
        result = parse_p4_adapter_semantic_result(
            '{"decision":"allow","severity":"none","category":"benign",'
            '"summary":"查看仓库状态","confidence":0.99,"evidence":[]}'
        )

        self.assertEqual(result.model_version, P4_ADAPTER_MODEL_VERSION)

        combined = parse_p4_adapter_semantic_result(
            '{"decision":"allow","severity":"none","category":"benign",'
            '"summary":"查看仓库状态","confidence":0.99,"evidence":[]}',
            model_version=P4_COMBINED_ADAPTER_MODEL_VERSION,
        )
        self.assertEqual(combined.model_version, P4_COMBINED_ADAPTER_MODEL_VERSION)

    def test_validated_adapter_runtime_generates_through_shared_backend_contract(self):
        tokenizer = FakeTokenizer()
        model = FakeModel()
        manifest = {
            "method": "qlora-p4-seed-pilot",
            "adapter_sha256": {"adapter_model.safetensors": "a" * 64},
        }
        with tempfile.TemporaryDirectory() as directory, patch(
            "guard.p4_adapter_backend.validate_p4_adapter_artifacts",
            return_value=manifest,
        ), patch(
            "guard.p4_adapter_backend.load_adapter_runtime",
            return_value=(tokenizer, model),
        ):
            root = Path(directory)
            model_path = root / "model"
            model_path.mkdir()
            backend = P4AdapterQwenBackend.from_local_adapter(
                root / "adapter",
                model_path,
                torch_module=FakeTorch,
                transformers_module=object(),
                peft_module=object(),
            )
            generated = backend.generate(
                [{"role": "user", "content": "{}"}],
                max_new_tokens=64,
            )

        self.assertTrue(model.eval_called)
        self.assertEqual(generated.generated_tokens, 2)
        self.assertEqual(generated.peak_gpu_memory_mb, 256.0)
        self.assertEqual(backend.manifest, manifest)
        self.assertEqual(backend.adapter_dir, root / "adapter")

    def test_backend_selects_combined_model_provenance_from_manifest(self):
        backend = P4AdapterQwenBackend(
            FakeTokenizer(),
            FakeModel(),
            FakeTorch,
            "cuda:0",
            adapter_dir=Path("combined/adapter"),
            manifest={"method": "qlora-p4-seed-targeted-v2"},
        )

        self.assertEqual(backend.model_version, P4_COMBINED_ADAPTER_MODEL_VERSION)

    def test_missing_adapter_is_rejected_before_runtime_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(P4AdapterBackendError, "incomplete"):
                P4AdapterQwenBackend.from_local_adapter(
                    Path(directory) / "missing-adapter",
                    Path(directory) / "model",
                    torch_module=FakeTorch,
                    transformers_module=object(),
                    peft_module=object(),
                )

    def test_validation_io_failure_becomes_adapter_backend_error(self):
        with patch(
            "guard.p4_adapter_backend.validate_p4_adapter_artifacts",
            side_effect=OSError("adapter storage unavailable"),
        ):
            with self.assertRaisesRegex(
                P4AdapterBackendError,
                "adapter validation failed.*adapter storage unavailable",
            ):
                P4AdapterQwenBackend.from_local_adapter(
                    Path("adapter"),
                    Path("model"),
                    torch_module=FakeTorch,
                    transformers_module=object(),
                    peft_module=object(),
                )

    def test_cuda_probe_failure_becomes_adapter_backend_error(self):
        class BrokenCuda:
            @staticmethod
            def is_available():
                raise RuntimeError("CUDA driver probe failed")

        class BrokenTorch:
            cuda = BrokenCuda()

        with patch(
            "guard.p4_adapter_backend.validate_p4_adapter_artifacts",
            return_value={},
        ):
            with self.assertRaisesRegex(
                P4AdapterBackendError,
                "CUDA probe failed.*CUDA driver probe failed",
            ):
                P4AdapterQwenBackend.from_local_adapter(
                    Path("adapter"),
                    Path("model"),
                    torch_module=BrokenTorch,
                    transformers_module=object(),
                    peft_module=object(),
                )


if __name__ == "__main__":
    unittest.main()
