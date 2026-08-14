#!/usr/bin/env python3
"""Run one local Qwen2.5 model-only baseline prediction for a GuardRequest."""

import argparse
import json
from pathlib import Path
import sys

from pydantic import ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from guard.baseline_predictor import (
    BaselinePredictionOutcome,
    BaselinePredictor,
    PredictionStatus,
)
from guard.contracts import GuardRequest
from guard.taxonomy import Decision
from guard.transformers_backend import TransformersBackendError, TransformersQwenBackend


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    return parser


def _emit(value: object) -> None:
    if isinstance(value, BaselinePredictionOutcome):
        value = value.model_dump(mode="json")
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _input_error(message: str) -> int:
    _emit({"status": "error", "error": message})
    return 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.max_new_tokens < 1:
        return _input_error("max_new_tokens must be positive")

    try:
        text = args.request.read_text(encoding="utf-8")
    except OSError as exc:
        return _input_error(f"could not read request file: {exc}")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return _input_error(f"invalid request JSON: {exc.msg}")

    try:
        request = GuardRequest.model_validate(payload)
    except (ValidationError, ValueError, TypeError) as exc:
        return _input_error(f"invalid GuardRequest: {exc}")

    try:
        backend = TransformersQwenBackend.from_local_model(args.model_path)
    except TransformersBackendError as exc:
        outcome = BaselinePredictionOutcome(
            status=PredictionStatus.BACKEND_ERROR,
            fallback_decision=Decision.REVIEW,
            error=str(exc),
        )
        _emit(outcome)
        return 1

    predictor = BaselinePredictor(backend, max_new_tokens=args.max_new_tokens)
    outcome = predictor.predict(request)
    _emit(outcome)
    return 0 if outcome.status is PredictionStatus.OK else 1


if __name__ == "__main__":
    raise SystemExit(main())
