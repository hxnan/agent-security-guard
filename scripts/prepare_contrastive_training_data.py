#!/usr/bin/env python3
"""Generate and validate the committed P4 Targeted V2 contrastive files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.prepare_targeted_training_data import (
    _backup_path,
    _publish_bundle,
    _temporary_path,
)
from training.contrastive_dataset import (
    ContrastiveDatasetError,
    build_contrastive_manifest,
    canonical_jsonl_bytes,
    generate_contrastive_dataset,
    validate_contrastive_profile,
)
from training.data_quality import (
    canonical_context,
    DatasetQualityError,
    load_eval_isolation_keys,
    load_training_jsonl,
    request_fingerprint,
)


DEFAULT_TRAIN_OUTPUT = REPOSITORY_ROOT / "data/train/agent_security_targeted_train_v2.jsonl"
DEFAULT_VALIDATION_OUTPUT = REPOSITORY_ROOT / "data/val/agent_security_targeted_validation_v2.jsonl"
DEFAULT_MANIFEST_OUTPUT = REPOSITORY_ROOT / "data/train/agent_security_targeted_v2_manifest.json"
DEFAULT_EVAL_DIR = REPOSITORY_ROOT / "data/eval-v1/gold"
DEFAULT_PRIOR_PATHS = (
    (REPOSITORY_ROOT / "data/train/agent_security_train_v1.jsonl", "train"),
    (REPOSITORY_ROOT / "data/val/agent_security_validation_v1.jsonl", "validation"),
    (REPOSITORY_ROOT / "data/train/agent_security_targeted_train_v1.jsonl", "train"),
    (REPOSITORY_ROOT / "data/val/agent_security_targeted_validation_v1.jsonl", "validation"),
)


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ContrastiveDatasetError(f"argument error: {message}")


def _assert_safe_outputs(outputs: tuple[Path, ...], *, force: bool) -> tuple[Path, ...]:
    temporary_paths = tuple(_temporary_path(path) for path in outputs)
    backup_paths = tuple(_backup_path(path) for path in outputs)
    resolved = [path.resolve(strict=False) for path in (*outputs, *temporary_paths, *backup_paths)]
    for index, left in enumerate(resolved):
        for right in resolved[index + 1 :]:
            if left == right or left.is_relative_to(right) or right.is_relative_to(left):
                raise ContrastiveDatasetError(
                    "P4 contrastive output and auxiliary paths collide or are nested; choose disjoint paths"
                )
    existing = [path for path in outputs if path.exists()]
    if existing and not force:
        raise ContrastiveDatasetError(
            "P4 contrastive output already exists: "
            + ", ".join(str(path) for path in existing)
        )
    non_files = [path for path in existing if not path.is_file()]
    if non_files:
        raise IsADirectoryError(
            "P4 contrastive output must be a regular file: "
            + ", ".join(str(path) for path in non_files)
        )
    auxiliary = [path for path in (*temporary_paths, *backup_paths) if path.exists()]
    if auxiliary:
        raise OSError(
            "P4 contrastive auxiliary path already exists: "
            + ", ".join(str(path) for path in auxiliary)
        )
    return temporary_paths


def prepare_contrastive_dataset(
    train_path: Path,
    validation_path: Path,
    manifest_path: Path,
    eval_dir: Path,
    *,
    force: bool = False,
    prior_paths: tuple[tuple[Path, str], ...] = DEFAULT_PRIOR_PATHS,
) -> dict[str, object]:
    outputs = (train_path, validation_path, manifest_path)
    temporary_paths = _assert_safe_outputs(outputs, force=force)
    train, validation = generate_contrastive_dataset()
    eval_keys = load_eval_isolation_keys(eval_dir)
    prior_records = []
    for path, split in prior_paths:
        prior_records.extend(load_training_jsonl(path, expected_split=split))
    prior_fingerprints = {request_fingerprint(record.input) for record in prior_records}
    prior_templates = {record.metadata.semantic_template for record in prior_records}
    prior_commands = {record.input.command for record in prior_records}
    prior_contexts = {canonical_context(record.input.context) for record in prior_records}
    prior_context_sources = {
        record.input.context.source or "" for record in prior_records
    }

    summary = validate_contrastive_profile(
        train,
        validation,
        eval_keys,
        prior_request_fingerprints=prior_fingerprints,
        prior_semantic_templates=prior_templates,
        prior_commands=prior_commands,
        prior_contexts=prior_contexts,
        prior_context_sources=prior_context_sources,
    )
    train_bytes = canonical_jsonl_bytes(train)
    validation_bytes = canonical_jsonl_bytes(validation)
    manifest = build_contrastive_manifest(train, validation, train_bytes, validation_bytes)
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    try:
        for path in outputs:
            path.parent.mkdir(parents=True, exist_ok=True)
        temporary_paths[0].write_bytes(train_bytes)
        temporary_paths[1].write_bytes(validation_bytes)
        temporary_paths[2].write_bytes(manifest_bytes)
        serialized_train = load_training_jsonl(temporary_paths[0], expected_split="train")
        serialized_validation = load_training_jsonl(
            temporary_paths[1], expected_split="validation"
        )
        validate_contrastive_profile(
            serialized_train,
            serialized_validation,
            eval_keys,
            prior_request_fingerprints=prior_fingerprints,
            prior_semantic_templates=prior_templates,
            prior_commands=prior_commands,
            prior_contexts=prior_contexts,
            prior_context_sources=prior_context_sources,
        )
        _publish_bundle(temporary_paths, outputs)
    finally:
        for temporary in temporary_paths:
            temporary.unlink(missing_ok=True)

    result = summary.to_dict()
    result.update(
        {
            "outputs": {
                "manifest": str(manifest_path),
                "train": str(train_path),
                "validation": str(validation_path),
            },
            "sha256": manifest["sha256"],
            "status": "ok",
        }
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("--train-output", type=Path, default=DEFAULT_TRAIN_OUTPUT)
    parser.add_argument("--validation-output", type=Path, default=DEFAULT_VALIDATION_OUTPUT)
    parser.add_argument("--manifest-output", type=Path, default=DEFAULT_MANIFEST_OUTPUT)
    parser.add_argument("--eval-dir", type=Path, default=DEFAULT_EVAL_DIR)
    parser.add_argument("--force", action="store_true")
    try:
        args = parser.parse_args(argv)
        result = prepare_contrastive_dataset(
            args.train_output,
            args.validation_output,
            args.manifest_output,
            args.eval_dir,
            force=args.force,
        )
    except (ContrastiveDatasetError, DatasetQualityError, OSError, UnicodeError) as exc:
        result = {"errors": [str(exc)], "status": "failed"}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
