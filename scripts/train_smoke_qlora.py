#!/usr/bin/env python3
"""Run one minimal local QLoRA smoke-training epoch."""

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from guard.qlora import QloraError, train_smoke
from guard.smoke_data import SmokeDataError
from guard.training_config import (
    DEFAULT_DATA_DIR,
    DEFAULT_OUTPUT_DIR,
    SmokeTrainingConfig,
    TrainingConfigError,
    TrainingEnvironmentError,
)


def parse_config(argv: Sequence[str] | None = None) -> SmokeTrainingConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--num-train-epochs", type=float, default=1.0)
    parser.add_argument("--lora-target", choices=("all-linear", "attention"), default="all-linear")
    parser.add_argument("--overwrite-output", action="store_true")
    args = parser.parse_args(argv)
    return SmokeTrainingConfig(
        model_path=args.model_path,
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        max_length=args.max_length,
        num_train_epochs=args.num_train_epochs,
        lora_target=args.lora_target,
        overwrite_output=args.overwrite_output,
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        result = train_smoke(parse_config(argv))
    except (
        QloraError,
        SmokeDataError,
        TrainingConfigError,
        TrainingEnvironmentError,
        OSError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
