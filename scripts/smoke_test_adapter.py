#!/usr/bin/env python3
"""Load the local smoke Adapter and validate one generated GuardResult."""

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from guard.adapter_smoke import AdapterSmokeError, smoke_test_adapter
from guard.training_config import DEFAULT_DATA_DIR, DEFAULT_OUTPUT_DIR


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--adapter-dir", type=Path, default=DEFAULT_OUTPUT_DIR / "adapter")
    parser.add_argument("--report", type=Path, default=DEFAULT_OUTPUT_DIR / "adapter_smoke_report.json")
    args = parser.parse_args(argv)
    try:
        report = smoke_test_adapter(
            args.adapter_dir, args.data_dir, args.model_path, args.report
        )
    except (AdapterSmokeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
