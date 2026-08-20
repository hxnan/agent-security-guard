from __future__ import annotations

import argparse

from training.data_builder import build_seed_dataset


def main():
    parser = argparse.ArgumentParser(description="Prepare Agent Security Guard training data")
    parser.add_argument(
        "--output",
        default="data/train/agent_security_train_v1.jsonl",
    )
    args = parser.parse_args()
    count = build_seed_dataset(args.output)
    print({"status": "ok", "samples": count, "output": args.output})


if __name__ == "__main__":
    main()
