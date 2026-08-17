#!/usr/bin/env python3
"""Evaluate deterministic Rules-only V1 on the frozen Eval V1 dataset."""

import argparse
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from guard.eval_freeze import EvalFreezeValidationError, load_resolved_eval_v1
from guard.rule_evaluation import evaluate_rules, write_rule_evaluation_report
from guard.rules import RuleEngine


DEFAULT_OUTPUT = REPOSITORY_ROOT / "artifacts" / "rules-eval-v1" / "report.json"


def _compact_summary(report: dict[str, object], output: Path) -> dict[str, object]:
    return {
        "status": "ok",
        "total_samples": report["total_samples"],
        "decisive_rate": report["decisive_rate"],
        "abstain_rate": report["abstain_rate"],
        "benign_rule_rate": report["benign_rule_rate"],
        "dangerous_rule_rate": report["dangerous_rule_rate"],
        "decision_accuracy_decisive": report["decision_accuracy_decisive"],
        "category_accuracy_decisive": report["category_accuracy_decisive"],
        "false_benign_allow_count": report["false_benign_allow_count"],
        "high_or_critical_allow_miss_count": report[
            "high_or_critical_allow_miss_count"
        ],
        "output": str(output),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        bundle = load_resolved_eval_v1()
    except (OSError, ValueError, EvalFreezeValidationError) as exc:
        print(
            json.dumps(
                {"status": "error", "stage": "freeze", "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2

    report = evaluate_rules(
        bundle.records,
        RuleEngine(),
        freeze_version=str(bundle.manifest["freeze_version"]),
    )
    write_rule_evaluation_report(args.output, report)
    print(
        json.dumps(
            _compact_summary(report, args.output),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
