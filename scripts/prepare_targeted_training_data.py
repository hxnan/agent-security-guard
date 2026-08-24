#!/usr/bin/env python3
"""Generate and validate the committed P4 Targeted Batch V1 files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from training.data_quality import (
    DatasetQualityError,
    load_eval_isolation_keys,
    load_training_jsonl,
    request_fingerprint,
)
from training.targeted_dataset import (
    TargetedDatasetError,
    build_targeted_manifest,
    canonical_jsonl_bytes,
    generate_targeted_dataset,
    validate_targeted_profile,
)


DEFAULT_TRAIN_OUTPUT = (
    REPOSITORY_ROOT / "data" / "train" / "agent_security_targeted_train_v1.jsonl"
)
DEFAULT_VALIDATION_OUTPUT = (
    REPOSITORY_ROOT / "data" / "val" / "agent_security_targeted_validation_v1.jsonl"
)
DEFAULT_MANIFEST_OUTPUT = (
    REPOSITORY_ROOT / "data" / "train" / "agent_security_targeted_v1_manifest.json"
)
DEFAULT_EVAL_DIR = REPOSITORY_ROOT / "data" / "eval-v1" / "gold"
DEFAULT_SEED_TRAIN = (
    REPOSITORY_ROOT / "data" / "train" / "agent_security_train_v1.jsonl"
)
DEFAULT_SEED_VALIDATION = (
    REPOSITORY_ROOT / "data" / "val" / "agent_security_validation_v1.jsonl"
)


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise TargetedDatasetError(f"argument error: {message}")


def _temporary_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".tmp")


def _backup_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".bak")


def _publish_bundle(
    temporary_paths: tuple[Path, ...],
    outputs: tuple[Path, ...],
) -> None:
    backups = tuple(_backup_path(path) for path in outputs)
    conflicting_backups = [path for path in backups if path.exists()]
    if conflicting_backups:
        raise OSError(
            "backup path already exists: "
            + ", ".join(str(path) for path in conflicting_backups)
        )
    moved: list[tuple[Path, Path]] = []
    published: list[Path] = []
    try:
        for final, backup in zip(outputs, backups):
            if final.exists():
                final.replace(backup)
                moved.append((final, backup))
        for temporary, final in zip(temporary_paths, outputs):
            temporary.replace(final)
            published.append(final)
    except OSError:
        for final in reversed(published):
            final.unlink(missing_ok=True)
        for final, backup in reversed(moved):
            backup.replace(final)
        raise
    else:
        for _, backup in moved:
            backup.unlink()


def prepare_targeted_dataset(
    train_path: Path,
    validation_path: Path,
    manifest_path: Path,
    eval_dir: Path,
    *,
    force: bool = False,
    seed_train_path: Path = DEFAULT_SEED_TRAIN,
    seed_validation_path: Path = DEFAULT_SEED_VALIDATION,
) -> dict[str, object]:
    outputs = (train_path, validation_path, manifest_path)
    temporary_paths = tuple(_temporary_path(path) for path in outputs)
    backup_paths = tuple(_backup_path(path) for path in outputs)
    resolved_paths = [
        path.resolve(strict=False)
        for path in (*outputs, *temporary_paths, *backup_paths)
    ]
    for index, left in enumerate(resolved_paths):
        for right in resolved_paths[index + 1 :]:
            if (
                left == right
                or left.is_relative_to(right)
                or right.is_relative_to(left)
            ):
                raise TargetedDatasetError(
                    "P4 targeted output and auxiliary paths collide or are nested; "
                    "choose disjoint paths"
                )
    existing = [path for path in outputs if path.exists()]
    if existing and not force:
        raise TargetedDatasetError(
            "P4 targeted output already exists: "
            + ", ".join(str(path) for path in existing)
        )
    non_files = [path for path in existing if not path.is_file()]
    if non_files:
        raise IsADirectoryError(
            "P4 targeted output must be a regular file: "
            + ", ".join(str(path) for path in non_files)
        )
    existing_auxiliary = [
        path for path in (*temporary_paths, *backup_paths) if path.exists()
    ]
    if existing_auxiliary:
        raise OSError(
            "P4 targeted auxiliary path already exists: "
            + ", ".join(str(path) for path in existing_auxiliary)
        )

    train, validation = generate_targeted_dataset()
    eval_keys = load_eval_isolation_keys(eval_dir)
    seed_records = [
        *load_training_jsonl(seed_train_path, expected_split="train"),
        *load_training_jsonl(
            seed_validation_path, expected_split="validation"
        ),
    ]
    seed_request_fingerprints = {
        request_fingerprint(record.input) for record in seed_records
    }
    seed_semantic_templates = {
        record.metadata.semantic_template for record in seed_records
    }
    summary = validate_targeted_profile(
        train,
        validation,
        eval_keys.request_fingerprints,
        seed_request_fingerprints=seed_request_fingerprints,
        seed_semantic_templates=seed_semantic_templates,
        eval_commands=eval_keys.commands,
        eval_contexts=eval_keys.contexts,
        eval_context_sources=eval_keys.context_sources,
        eval_semantic_templates=eval_keys.semantic_templates,
    )
    train_bytes = canonical_jsonl_bytes(train)
    validation_bytes = canonical_jsonl_bytes(validation)
    manifest = build_targeted_manifest(
        train, validation, train_bytes, validation_bytes
    )
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    try:
        for path in outputs:
            path.parent.mkdir(parents=True, exist_ok=True)
        temporary_paths[0].write_bytes(train_bytes)
        temporary_paths[1].write_bytes(validation_bytes)
        temporary_paths[2].write_bytes(manifest_bytes)
        serialized_train = load_training_jsonl(
            temporary_paths[0], expected_split="train"
        )
        serialized_validation = load_training_jsonl(
            temporary_paths[1], expected_split="validation"
        )
        validate_targeted_profile(
            serialized_train,
            serialized_validation,
            eval_keys.request_fingerprints,
            seed_request_fingerprints=seed_request_fingerprints,
            seed_semantic_templates=seed_semantic_templates,
            eval_commands=eval_keys.commands,
            eval_contexts=eval_keys.contexts,
            eval_context_sources=eval_keys.context_sources,
            eval_semantic_templates=eval_keys.semantic_templates,
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
    parser.add_argument(
        "--validation-output", type=Path, default=DEFAULT_VALIDATION_OUTPUT
    )
    parser.add_argument(
        "--manifest-output", type=Path, default=DEFAULT_MANIFEST_OUTPUT
    )
    parser.add_argument("--eval-dir", type=Path, default=DEFAULT_EVAL_DIR)
    parser.add_argument("--force", action="store_true")
    try:
        args = parser.parse_args(argv)
        result = prepare_targeted_dataset(
            args.train_output,
            args.validation_output,
            args.manifest_output,
            args.eval_dir,
            force=args.force,
        )
    except (
        TargetedDatasetError,
        DatasetQualityError,
        OSError,
        UnicodeError,
    ) as exc:
        result = {"errors": [str(exc)], "status": "failed"}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
