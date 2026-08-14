"""Lazy local Transformers backend for the Qwen2.5 model-only baseline."""

from pathlib import Path
import time

from .baseline_predictor import GenerationResult
from .environment import resolve_model_path, validate_model_directory


class TransformersBackendError(RuntimeError):
    """Raised when the local baseline runtime cannot load or generate safely."""


class TransformersQwenBackend:
    """Local-only deterministic Qwen generation backend."""

    def __init__(self, tokenizer, model, torch_module, device: str):
        self.tokenizer = tokenizer
        self.model = model
        self.torch = torch_module
        self.device = device

    @classmethod
    def from_local_model(
        cls,
        model_path: Path | None = None,
        device: str = "cuda:0",
        *,
        torch_module=None,
        transformers_module=None,
    ) -> "TransformersQwenBackend":
        resolved_model = resolve_model_path(model_path)
        missing = validate_model_directory(resolved_model)
        if missing:
            raise TransformersBackendError(
                f"missing model files in {resolved_model}: {', '.join(missing)}"
            )

        if torch_module is None:
            try:
                import torch as torch_module
            except ImportError as exc:
                raise TransformersBackendError(
                    f"missing baseline dependency: {exc.name or 'torch'}"
                ) from exc
        if transformers_module is None:
            try:
                import transformers as transformers_module
            except ImportError as exc:
                raise TransformersBackendError(
                    f"missing baseline dependency: {exc.name or 'transformers'}"
                ) from exc

        if not device.startswith("cuda:"):
            raise TransformersBackendError(
                "baseline backend currently requires an explicit CUDA device such as cuda:0"
            )
        if not torch_module.cuda.is_available():
            raise TransformersBackendError("CUDA is not available for the baseline backend")

        try:
            device_index = int(device.split(":", 1)[1])
        except (IndexError, ValueError) as exc:
            raise TransformersBackendError(f"invalid CUDA device: {device}") from exc

        try:
            tokenizer = transformers_module.AutoTokenizer.from_pretrained(
                resolved_model,
                local_files_only=True,
            )
            if tokenizer.pad_token_id is None:
                tokenizer.pad_token = tokenizer.eos_token
            model = transformers_module.AutoModelForCausalLM.from_pretrained(
                resolved_model,
                device_map={"": device_index},
                dtype=torch_module.bfloat16,
                local_files_only=True,
            )
            model.eval()
        except Exception as exc:
            raise TransformersBackendError(
                f"could not load local baseline runtime: {exc}"
            ) from exc

        return cls(tokenizer, model, torch_module, device)

    def generate(
        self,
        messages: list[dict[str, str]],
        max_new_tokens: int,
    ) -> GenerationResult:
        if max_new_tokens < 1:
            raise TransformersBackendError("max_new_tokens must be positive")
        try:
            prompt = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
            inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
            self.torch.cuda.reset_peak_memory_stats()
            started = time.perf_counter()
            with self.torch.inference_mode():
                output = self.model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                    pad_token_id=self.tokenizer.pad_token_id,
                    eos_token_id=self.tokenizer.eos_token_id,
                )
            elapsed = time.perf_counter() - started
            input_length = inputs["input_ids"].shape[1]
            new_tokens = output[0, input_length:]
            raw_text = self.tokenizer.decode(
                new_tokens,
                skip_special_tokens=True,
            )
            peak_gpu_memory_mb = (
                self.torch.cuda.max_memory_allocated() / 1024**2
            )
        except Exception as exc:
            raise TransformersBackendError(
                f"baseline generation failed: {exc}"
            ) from exc

        return GenerationResult(
            raw_text=raw_text,
            elapsed_seconds=elapsed,
            generated_tokens=len(new_tokens),
            peak_gpu_memory_mb=peak_gpu_memory_mb,
        )
