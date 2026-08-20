#!/usr/bin/env python3
"""Load the P4 pilot adapter and probe one held-out validation record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from guard.adapter_smoke import AdapterSmokeError
from guard.p4_adapter_smoke import P4AdapterSmokeError, smoke_test_p4_adapter
from guard.p4_qlora import P4QloraError
from guard.training_config import (
    DEFAULT_P4_EVAL_DIR,
    DEFAULT_P4_MANIFEST_PATH,
    DEFAULT_P4_OUTPUT_DIR,
    DEFAULT_P4_TRAIN_PATH,
    DEFAULT_P4_VALIDATION_PATH,
    P4SeedTrainingConfig,
    TrainingConfigError,
)


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise TrainingConfigError(f"argument error: {message}")


def _parse_args(argv: Sequence[str] | None):
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--train", type=Path, default=DEFAULT_P4_TRAIN_PATH)
    parser.add_argument(
        "--validation", type=Path, default=DEFAULT_P4_VALIDATION_PATH
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_P4_MANIFEST_PATH)
    parser.add_argument("--eval-dir", type=Path, default=DEFAULT_P4_EVAL_DIR)
    parser.add_argument(
        "--adapter-dir", type=Path, default=DEFAULT_P4_OUTPUT_DIR / "adapter"
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_P4_OUTPUT_DIR / "adapter_smoke_report.json",
    )
    parser.add_argument("--max-new-tokens", type=int, default=256)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        config = P4SeedTrainingConfig(
            model_path=args.model_path,
            train_path=args.train,
            validation_path=args.validation,
            manifest_path=args.manifest,
            eval_dir=args.eval_dir,
        )
        report = smoke_test_p4_adapter(
            args.adapter_dir,
            config,
            args.report,
            max_new_tokens=args.max_new_tokens,
        )
        result = {"status": "ok" if report["valid"] else "failed", **report}
        exit_code = 0 if report["valid"] else 1
    except (
        AdapterSmokeError,
        OSError,
        P4AdapterSmokeError,
        P4QloraError,
        TrainingConfigError,
    ) as exc:
        result = {"errors": [str(exc)], "status": "failed"}
        exit_code = 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
