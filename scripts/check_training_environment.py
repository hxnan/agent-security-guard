#!/usr/bin/env python3
"""Check local prerequisites for the QLoRA smoke run without loading a model."""

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from guard.training_config import (
    DEFAULT_DATA_DIR,
    assert_training_ready,
    inspect_training_environment,
    resolve_training_model_path,
    TrainingEnvironmentError,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args(argv)
    report = inspect_training_environment(
        resolve_training_model_path(args.model_path), args.data_dir
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    try:
        assert_training_ready(report)
    except TrainingEnvironmentError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
