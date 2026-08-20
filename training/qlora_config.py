from dataclasses import dataclass


@dataclass(frozen=True)
class QLoRAConfig:
    model_name: str = "Qwen2.5-1.5B-Instruct"
    load_in_4bit: bool = True
    quant_type: str = "nf4"
    lora_rank: int = 8
    lora_alpha: int = 16
    learning_rate: float = 2e-4
    batch_size: int = 1
    gradient_accumulation_steps: int = 16
    epochs: int = 3


DEFAULT_CONFIG = QLoRAConfig()
