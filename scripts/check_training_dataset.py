from __future__ import annotations

import argparse
import json
from pathlib import Path

from training.data_quality import scan_contamination, summarize, validate_sample


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset")
    args = parser.parse_args()

    samples = []
    errors = []
    contamination = []

    for line_no, line in enumerate(Path(args.dataset).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        sample = json.loads(line)
        samples.append(sample)
        try:
            validate_sample(sample)
        except Exception as exc:
            errors.append({"line": line_no, "error": str(exc)})
        contamination.extend(scan_contamination(sample))

    result = {
        "status": "ok" if not errors and not contamination else "failed",
        "summary": summarize(samples),
        "schema_errors": errors,
        "contamination": sorted(set(contamination)),
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
