#!/usr/bin/env python3
"""Export the versioned public JSON Schema artifacts."""

import argparse
import sys
from pathlib import Path
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from guard.schema_export import export_schemas


DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "schemas" / "v1"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    export_schemas(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
