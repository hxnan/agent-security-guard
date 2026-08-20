"""Deterministic P4 training-data validation and leakage gates."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable, Literal

from pydantic import ValidationError

from guard.contracts import GuardRequest
from training.schema import TrainingExample


class DatasetQualityError(ValueError):
    """Raised when a JSONL input cannot be treated as a training split."""


_EVAL_ID_PATTERN = re.compile(r"EV[0-9]{3}")
_PROVENANCE_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def request_fingerprint(request: GuardRequest | dict) -> str:
    if not isinstance(request, GuardRequest):
        request = GuardRequest.model_validate(request)
    payload = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_training_jsonl(
    path: Path | str,
    expected_split: Literal["train", "validation"],
) -> list[TrainingExample]:
    path = Path(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise DatasetQualityError(f"cannot read {path}: {exc}") from exc

    examples: list[TrainingExample] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetQualityError(
                f"line {line_number}: invalid JSON: {exc.msg}"
            ) from exc
        try:
            example = TrainingExample.model_validate(raw)
        except ValidationError as exc:
            message = exc.errors(include_url=False)[0]["msg"]
            raise DatasetQualityError(
                f"line {line_number}: invalid training record: {message}"
            ) from exc
        if example.metadata.split != expected_split:
            raise DatasetQualityError(
                f"line {line_number}: metadata.split must be {expected_split}"
            )
        if example.sample_id in seen_ids:
            raise DatasetQualityError(
                f"line {line_number}: duplicate id {example.sample_id}"
            )
        seen_ids.add(example.sample_id)
        examples.append(example)
    return examples


def load_eval_request_fingerprints(eval_dir: Path | str) -> set[str]:
    eval_dir = Path(eval_dir)
    if not eval_dir.is_dir():
        raise DatasetQualityError(f"Eval directory does not exist: {eval_dir}")
    fingerprints: set[str] = set()
    paths = sorted(eval_dir.glob("*.jsonl"))
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise DatasetQualityError(
                f"cannot read Eval shard {path}: {exc}"
            ) from exc
        for line_number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                request = raw["request"]
                fingerprints.add(request_fingerprint(request))
            except (
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValidationError,
                ValueError,
            ) as exc:
                raise DatasetQualityError(
                    f"{path.name} line {line_number}: invalid Eval request: {exc}"
                ) from exc
    if not fingerprints:
        raise DatasetQualityError(f"Eval directory contains no requests: {eval_dir}")
    return fingerprints


def _summary(examples: Iterable[TrainingExample]) -> dict[str, object]:
    examples = list(examples)
    categories = Counter(item.output.category.value for item in examples)
    return {
        "samples": len(examples),
        "categories": dict(sorted(categories.items())),
    }


@dataclass(frozen=True)
class DatasetQualityReport:
    train: dict[str, object]
    validation: dict[str, object]
    errors: tuple[str, ...]

    @property
    def status(self) -> str:
        return "ok" if not self.errors else "failed"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "train": self.train,
            "validation": self.validation,
            "errors": list(self.errors),
        }


def _provenance_contains_forbidden_marker(example: TrainingExample) -> bool:
    metadata = example.metadata.model_dump(mode="json")
    values = [
        *metadata.values(),
        example.output.model_version,
        example.output.policy_version,
    ]
    for value in values:
        tokens = _PROVENANCE_TOKEN_PATTERN.findall(str(value).lower())
        if any(
            token in {"eval", "gold"}
            or re.fullmatch(r"(?:eval|gold)v[0-9]+", token)
            for token in tokens
        ):
            return True
    return False


def validate_dataset_bundle(
    train: list[TrainingExample],
    validation: list[TrainingExample],
    eval_request_fingerprints: set[str],
) -> DatasetQualityReport:
    errors: set[str] = set()

    if not train:
        errors.add("train split is empty")
    if not validation:
        errors.add("validation split is empty")

    train_by_id = {item.sample_id: item for item in train}
    validation_by_id = {item.sample_id: item for item in validation}
    for sample_id in train_by_id.keys() & validation_by_id.keys():
        errors.add(f"cross-split id overlap: {sample_id}")

    train_requests = {request_fingerprint(item.input): item for item in train}
    validation_requests = {
        request_fingerprint(item.input): item for item in validation
    }
    for fingerprint in train_requests.keys() & validation_requests.keys():
        errors.add(
            f"cross-split request overlap: {train_requests[fingerprint].sample_id}"
        )

    train_templates = {item.metadata.semantic_template for item in train}
    validation_templates = {
        item.metadata.semantic_template for item in validation
    }
    for template in train_templates & validation_templates:
        errors.add(f"cross-split semantic_template overlap: {template}")

    for example in [*train, *validation]:
        serialized = json.dumps(
            example.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            sort_keys=True,
        )
        for marker in _EVAL_ID_PATTERN.findall(serialized):
            errors.add(f"{example.sample_id} contains Eval sample identifier {marker}")
        if _provenance_contains_forbidden_marker(example):
            errors.add(
                f"{example.sample_id} contains forbidden Eval/Gold provenance"
            )
        if request_fingerprint(example.input) in eval_request_fingerprints:
            errors.add(f"{example.sample_id} request duplicates frozen Eval V1")

    return DatasetQualityReport(
        train=_summary(train),
        validation=_summary(validation),
        errors=tuple(sorted(errors)),
    )
