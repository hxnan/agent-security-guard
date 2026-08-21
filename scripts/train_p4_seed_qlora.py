#!/usr/bin/env python3
"""Run the local P4 Seed Dataset V1 QLoRA pilot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from guard.p4_qlora import (
    P4QloraError,
    preflight_p4_seed_training,
    train_p4_seed,
)
from guard.qlora import QloraError
from guard.training_config import (
    DEFAULT_P4_EVAL_DIR,
    DEFAULT_P4_MANIFEST_PATH,
    DEFAULT_P4_MAX_LENGTH,
    DEFAULT_P4_OUTPUT_DIR,
    DEFAULT_P4_TRAIN_PATH,
    DEFAULT_P4_VALIDATION_PATH,
    P4SeedTrainingConfig,
    TrainingConfigError,
    TrainingEnvironmentError,
)
from guard.training_data import TrainingDataError


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise TrainingConfigError(f"argument error: {message}")


def _parse_options(
    argv: Sequence[str] | None = None,
) -> tuple[P4SeedTrainingConfig, bool]:
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--train", type=Path, default=DEFAULT_P4_TRAIN_PATH)
    parser.add_argument(
        "--validation", type=Path, default=DEFAULT_P4_VALIDATION_PATH
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_P4_MANIFEST_PATH)
    parser.add_argument("--eval-dir", type=Path, default=DEFAULT_P4_EVAL_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_P4_OUTPUT_DIR)
    parser.add_argument("--max-length", type=int, default=DEFAULT_P4_MAX_LENGTH)
    parser.add_argument("--num-train-epochs", type=float, default=2.0)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument(
        "--lora-target",
        choices=("all-linear", "attention"),
        default="all-linear",
    )
    parser.add_argument("--overwrite-output", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    config = P4SeedTrainingConfig(
        model_path=args.model_path,
        train_path=args.train,
        validation_path=args.validation,
        manifest_path=args.manifest,
        eval_dir=args.eval_dir,
        output_dir=args.output_dir,
        max_length=args.max_length,
        num_train_epochs=args.num_train_epochs,
        learning_rate=args.learning_rate,
        lora_target=args.lora_target,
        overwrite_output=args.overwrite_output,
    )
    return config, args.preflight_only


def parse_config(argv: Sequence[str] | None = None) -> P4SeedTrainingConfig:
    return _parse_options(argv)[0]


def main(argv: Sequence[str] | None = None) -> int:
    try:
        config, preflight_only = _parse_options(argv)
        if preflight_only:
            result = preflight_p4_seed_training(config)
            exit_code = 0 if result["status"] == "ready" else 2
        else:
            result = {"status": "ok", **train_p4_seed(config)}
            exit_code = 0
    except (
        OSError,
        P4QloraError,
        QloraError,
        TrainingConfigError,
        TrainingDataError,
        TrainingEnvironmentError,
    ) as exc:
        result = {"errors": [str(exc)], "status": "failed"}
        exit_code = 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
