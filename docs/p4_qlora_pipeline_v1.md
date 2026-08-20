# P4 QLoRA Pipeline V1

## Goal

Train Qwen2.5-1.5B-Instruct into an Agent Security Guard model while keeping Eval V1 frozen.

## Dataset isolation

- train/validation are generated independently.
- eval-v1 remains frozen and is never used for training.

## Training target

Input:

- tool family
- command/tool arguments
- execution context

Output:

- risk
- decision
- severity
- category
- summary
- confidence

## Initial QLoRA configuration

- 4bit NF4 quantization
- LoRA rank 8
- batch size 1
- gradient accumulation 16
- 3 epochs

## Acceptance targets

- valid output rate > 95%
- repair rate < 10%
- high-risk allow miss = 0
- category macro F1 improvement
