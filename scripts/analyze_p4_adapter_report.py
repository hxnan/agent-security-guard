#!/usr/bin/env python3
"""Summarize safety-first error clusters in a P4 adapter Eval V1 report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from guard.eval_freeze import load_resolved_eval_v1
from guard.p4_adapter_diagnostics import (
    analyze_p4_adapter_report,
    validate_local_adapter_provenance,
)


DEFAULT_REPORT = (
    REPOSITORY_ROOT / "artifacts" / "p4-adapter-eval-v1" / "report.json"
)


class DiagnosticsArgumentError(ValueError):
    """Raised when analyzer arguments violate the JSON-only CLI contract."""


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise DiagnosticsArgumentError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _expected_samples(records) -> dict[str, dict[str, object]]:
    return {
        record.sample_id: {
            "risk": record.expected.risk,
            "decision": record.expected.decision.value,
            "severity": record.expected.severity.value,
            "category": record.expected.category.value,
        }
        for record in records
    }


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        report = json.loads(args.report.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("report root must be a JSON object")
        freeze = load_resolved_eval_v1()
        adapter_provenance = validate_local_adapter_provenance(report)
        diagnostics = analyze_p4_adapter_report(
            report,
            expected_freeze_version=str(freeze.manifest["freeze_version"]),
            expected_samples=_expected_samples(freeze.records),
            expected_adapter_provenance=adapter_provenance,
        )
    except DiagnosticsArgumentError as exc:
        _emit({"status": "error", "error": str(exc)})
        return 2
    except (OSError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        _emit({"status": "error", "error": str(exc)})
        return 2
    _emit(diagnostics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
