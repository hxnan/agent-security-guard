"""QLoRA training entrypoint scaffold.

The first version only validates that the training pipeline can be wired.
Actual GPU execution is intentionally left for local validation.
"""

from __future__ import annotations

import argparse



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--dataset", default="data/train/agent_security_train_v1.jsonl")
    args = parser.parse_args()

    print(
        {
            "status": "prepared",
            "smoke_test": args.smoke_test,
            "dataset": args.dataset,
            "next_step": "load Qwen2.5 base model and attach LoRA adapter",
        }
    )


if __name__ == "__main__":
    main()
