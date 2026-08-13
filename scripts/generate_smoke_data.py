#!/usr/bin/env python3
"""Generate the deterministic local smoke-training dataset."""

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from guard.smoke_data import SmokeDataError, write_smoke_dataset


DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "data" / "generated" / "smoke-v1"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        summary = write_smoke_dataset(args.output_dir, force=args.force)
    except (SmokeDataError, OSError, UnicodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
