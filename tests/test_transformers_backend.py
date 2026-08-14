from contextlib import nullcontext
from pathlib import Path
import tempfile
import unittest

from guard.transformers_backend import TransformersBackendError, TransformersQwenBackend


REQUIRED_FILES = (
    "config.json",
    "generation_config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
)


class FakeCuda:
    def __init__(self, available=True):
        self.available = available
        self.reset_calls = 0

    def is_available(self):
        return self.available

    def reset_peak_memory_stats(self):
        self.reset_calls += 1

    def max_memory_allocated(self):
        return 128 * 1024 * 1024


class FakeTorch:
    bfloat16 = "bf16"

    def __init__(self, available=True):
        self.cuda = FakeCuda(available)

    def inference_mode(self):
        return nullcontext()


class FakeInputIds:
    shape = (1, 3)


class FakeInputs(dict):
    def __init__(self):
        super().__init__({"input_ids": FakeInputIds()})
        self.device = None

    def to(self, device):
        self.device = device
        return self


class FakeSequence:
    def __getitem__(self, key):
        if isinstance(key, slice):
            start = key.start or 0
            return [101, 102, 103, 201, 202][start:key.stop:key.step]
        return [101, 102, 103, 201, 202][key]


class FakeOutput:
    def __getitem__(self, key):
        if key == 0:
            return FakeSequence()
        raise IndexError(key)


class FakeTokenizer:
    def __init__(self):
        self.pad_token_id = None
        self.eos_token_id = 99
        self.eos_token = "<eos>"
        self.pad_token = None
        self.prompt = None
        self.inputs = None
        self.decoded = None

    def apply_chat_template(self, messages, tokenize, add_generation_prompt):
        self.prompt = (messages, tokenize, add_generation_prompt)
        return "rendered prompt"

    def __call__(self, prompt, return_tensors):
        self.inputs = FakeInputs()
        return self.inputs

    def decode(self, tokens, skip_special_tokens):
        self.decoded = (list(tokens), skip_special_tokens)
        return '{"ok":true}'


class FakeModel:
    def __init__(self):
        self.eval_called = False
        self.generate_kwargs = None

    def eval(self):
        self.eval_called = True
        return self

    def generate(self, **kwargs):
        self.generate_kwargs = kwargs
        return FakeOutput()


class FakeAutoTokenizer:
    calls = []
    tokenizer = None

    @classmethod
    def from_pretrained(cls, path, **kwargs):
        cls.calls.append((path, kwargs))
        cls.tokenizer = FakeTokenizer()
        return cls.tokenizer


class FakeAutoModel:
    calls = []
    model = None

    @classmethod
    def from_pretrained(cls, path, **kwargs):
        cls.calls.append((path, kwargs))
        cls.model = FakeModel()
        return cls.model


class FakeTransformers:
    AutoTokenizer = FakeAutoTokenizer
    AutoModelForCausalLM = FakeAutoModel


class TransformersBackendTests(unittest.TestCase):
    def complete_model_dir(self, root: Path) -> Path:
        model = root / "model"
        model.mkdir()
        for name in REQUIRED_FILES:
            (model / name).write_text("{}", encoding="utf-8")
        return model

    def setUp(self):
        FakeAutoTokenizer.calls = []
        FakeAutoTokenizer.tokenizer = None
        FakeAutoModel.calls = []
        FakeAutoModel.model = None

    def test_missing_model_files_are_rejected_before_runtime_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(TransformersBackendError, "missing model files"):
                TransformersQwenBackend.from_local_model(
                    Path(tmp),
                    torch_module=FakeTorch(),
                    transformers_module=FakeTransformers,
                )
        self.assertEqual(FakeAutoTokenizer.calls, [])
        self.assertEqual(FakeAutoModel.calls, [])

    def test_cuda_device_requires_available_cuda(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = self.complete_model_dir(Path(tmp))
            with self.assertRaisesRegex(TransformersBackendError, "CUDA"):
                TransformersQwenBackend.from_local_model(
                    model_path,
                    torch_module=FakeTorch(available=False),
                    transformers_module=FakeTransformers,
                )

    def test_loads_local_model_with_bf16_and_pad_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = self.complete_model_dir(Path(tmp))
            backend = TransformersQwenBackend.from_local_model(
                model_path,
                torch_module=FakeTorch(),
                transformers_module=FakeTransformers,
            )

        tokenizer_path, tokenizer_kwargs = FakeAutoTokenizer.calls[0]
        model_call_path, model_kwargs = FakeAutoModel.calls[0]
        self.assertEqual(Path(tokenizer_path), model_path)
        self.assertEqual(Path(model_call_path), model_path)
        self.assertEqual(tokenizer_kwargs, {"local_files_only": True})
        self.assertEqual(model_kwargs["local_files_only"], True)
        self.assertEqual(model_kwargs["device_map"], {"": 0})
        self.assertEqual(model_kwargs["dtype"], "bf16")
        self.assertEqual(backend.tokenizer.pad_token, "<eos>")
        self.assertTrue(backend.model.eval_called)

    def test_generation_is_greedy_and_decodes_only_new_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = self.complete_model_dir(Path(tmp))
            torch_module = FakeTorch()
            backend = TransformersQwenBackend.from_local_model(
                model_path,
                torch_module=torch_module,
                transformers_module=FakeTransformers,
            )
            result = backend.generate(
                [{"role": "system", "content": "guard"}, {"role": "user", "content": "{}"}],
                max_new_tokens=64,
            )

        self.assertEqual(result.raw_text, '{"ok":true}')
        self.assertEqual(result.generated_tokens, 2)
        self.assertEqual(result.peak_gpu_memory_mb, 128.0)
        self.assertGreaterEqual(result.elapsed_seconds, 0.0)
        self.assertEqual(backend.tokenizer.inputs.device, "cuda:0")
        self.assertEqual(backend.tokenizer.decoded, ([201, 202], True))
        kwargs = backend.model.generate_kwargs
        self.assertEqual(kwargs["max_new_tokens"], 64)
        self.assertIs(kwargs["do_sample"], False)
        self.assertEqual(kwargs["pad_token_id"], backend.tokenizer.pad_token_id)
        self.assertEqual(kwargs["eos_token_id"], 99)
        self.assertEqual(torch_module.cuda.reset_calls, 1)

    def test_runtime_loader_wraps_dependency_errors_concisely(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = self.complete_model_dir(Path(tmp))

            class BrokenTokenizer:
                @staticmethod
                def from_pretrained(*args, **kwargs):
                    raise ValueError("corrupt tokenizer")

            class BrokenTransformers:
                AutoTokenizer = BrokenTokenizer
                AutoModelForCausalLM = FakeAutoModel

            with self.assertRaisesRegex(
                TransformersBackendError, "could not load local baseline runtime: corrupt tokenizer"
            ):
                TransformersQwenBackend.from_local_model(
                    model_path,
                    torch_module=FakeTorch(),
                    transformers_module=BrokenTransformers,
                )


if __name__ == "__main__":
    unittest.main()
