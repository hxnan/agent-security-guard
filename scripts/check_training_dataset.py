from __future__ import annotations

import argparse
import json
from pathlib import Path

FORBIDDEN_MARKERS = ("EV001", "EV002", "eval-v1", "gold", "blueprint")


def validate_sample(sample: dict) -> list[str]:
    errors = []
    output = sample.get("output", {})
    for key in ("risk", "decision", "severity", "category", "summary", "confidence"):
        if key not in output:
            errors.append(f"missing:{key}")
    text = json.dumps(sample, ensure_ascii=False)
    for marker in FORBIDDEN_MARKERS:
        if marker in text:
            errors.append(f"forbidden:{marker}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset")
    args = parser.parse_args()

    total = 0
    errors = []
    for line in Path(args.dataset).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        total += 1
        errors.extend(validate_sample(json.loads(line)))

    print(json.dumps({
        "status": "ok" if not errors else "failed",
        "samples": total,
        "errors": len(errors),
        "details": errors[:20],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
