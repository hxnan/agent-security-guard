"""Deterministic generator and quality profile for P4 Targeted Batch V1."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from typing import Iterable

from guard.contracts import GuardRequest, GuardResult
from guard.taxonomy import RiskCategory
from training.data_quality import (
    canonical_context,
    request_fingerprint,
    validate_dataset_bundle,
)
from training.schema import TrainingExample
from training.targeted_catalog import (
    EXPECTED_CATEGORY_COUNTS,
    TARGETED_CLUSTERS,
    validate_targeted_catalog,
)


class TargetedDatasetError(ValueError):
    """Raised when the generated targeted bundle drifts from its fixed profile."""


DATA_VERSION = "p4-targeted-v1"
GENERATION_SOURCE = "curated_targeted_catalog_v1"
GENERATOR_VERSION = "p4-targeted-generator-v1"
INSTRUCTION = "Analyze this Agent tool call for security risk."
TRAIN_PATH = "data/train/agent_security_targeted_train_v1.jsonl"
VALIDATION_PATH = "data/val/agent_security_targeted_validation_v1.jsonl"
DIAGNOSTIC_BASIS = {
    "report_version": "p4-adapter-eval-report-v1",
    "total_samples": 100,
    "high_risk_allow_miss_count": 1,
    "risk_false_negative_count": 3,
    "benign_false_positive_count": 11,
}
EXPECTED_CATEGORY_ROWS = Counter(
    {category: count * 10 for category, count in EXPECTED_CATEGORY_COUNTS.items()}
)


def _sorted_values(counter: Counter) -> dict[str, int]:
    return dict(
        sorted(
            (
                key.value if hasattr(key, "value") else str(key),
                count,
            )
            for key, count in counter.items()
        )
    )


@dataclass(frozen=True)
class TargetedDatasetSummary:
    total: int
    splits: dict[str, int]
    categories: dict[str, int]
    tools: dict[str, int]
    scenario_kinds: dict[str, int]
    batches: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "batches": self.batches,
            "categories": self.categories,
            "scenario_kinds": self.scenario_kinds,
            "splits": self.splits,
            "tools": self.tools,
            "total": self.total,
        }


def _build_record(cluster, variant: int, global_index: int) -> TrainingExample:
    command = cluster.render_command(variant)
    risk = cluster.category is not RiskCategory.BENIGN
    return TrainingExample.model_validate(
        {
            "id": f"TR-{global_index:06d}",
            "instruction": INSTRUCTION,
            "input": GuardRequest(
                type=cluster.tool_type,
                command=command,
                context={
                    "cwd": f"/workspace/targeted-project-{variant}",
                    "actor": "p4-targeted-agent",
                    "tool_name": cluster.tool_type.value,
                    "privilege": cluster.privilege,
                    "source": cluster.context_source,
                },
            ).model_dump(mode="json"),
            "output": GuardResult(
                risk=risk,
                decision=cluster.decision,
                severity=cluster.severity,
                category=cluster.category,
                summary=cluster.summary,
                confidence=cluster.confidence,
                evidence=[command, f"context: {cluster.context_source}"],
                rule_hits=[],
                model_version="p4-targeted-target-v1",
                policy_version="policy-v1",
            ).model_dump(mode="json"),
            "metadata": {
                "data_version": DATA_VERSION,
                "generation_source": GENERATION_SOURCE,
                "semantic_template": cluster.semantic_template,
                "split": cluster.split,
                "scenario_kind": cluster.scenario_kind,
                "batch_id": (
                    "p4-targeted-v1-batch-"
                    f"{(global_index - 1001) // 100 + 1:03d}"
                ),
                "generator_version": GENERATOR_VERSION,
            },
        }
    )


def generate_targeted_dataset() -> tuple[list[TrainingExample], list[TrainingExample]]:
    validate_targeted_catalog(TARGETED_CLUSTERS)
    train: list[TrainingExample] = []
    validation: list[TrainingExample] = []
    for cluster_index, cluster in enumerate(TARGETED_CLUSTERS):
        for variant in range(1, 11):
            global_index = 1001 + cluster_index * 10 + variant - 1
            record = _build_record(cluster, variant, global_index)
            (train if cluster.split == "train" else validation).append(record)
    return train, validation


def _category_counter(records: Iterable[TrainingExample]) -> Counter:
    return Counter(record.output.category for record in records)


def validate_targeted_profile(
    train: list[TrainingExample],
    validation: list[TrainingExample],
    eval_request_fingerprints: set[str],
    *,
    seed_request_fingerprints: set[str] | None = None,
    seed_semantic_templates: set[str] | None = None,
    eval_tool_commands: set[tuple[str, str]] | frozenset[tuple[str, str]] | None = None,
    eval_contexts: set[str] | frozenset[str] | None = None,
    eval_semantic_templates: set[str] | frozenset[str] | None = None,
) -> TargetedDatasetSummary:
    errors: set[str] = set()
    if len(train) != 400:
        errors.add(f"train rows must be 400, got {len(train)}")
    if len(validation) != 100:
        errors.add(f"validation rows must be 100, got {len(validation)}")
    records = [*train, *validation]

    expected_ids = [f"TR-{number:06d}" for number in range(1001, 1501)]
    if [record.sample_id for record in records] != expected_ids:
        errors.add("sample IDs must be contiguous TR-001001 through TR-001500")

    expected_train, expected_validation = generate_targeted_dataset()
    expected_by_id = {
        record.sample_id: record
        for record in [*expected_train, *expected_validation]
    }
    for record in records:
        if expected_by_id.get(record.sample_id) != record:
            errors.add(
                f"{record.sample_id} does not match its curated targeted record"
            )

    fingerprints = [request_fingerprint(record.input) for record in records]
    if len(fingerprints) != len(set(fingerprints)):
        errors.add("all targeted requests must be unique")
    seed_request_fingerprints = seed_request_fingerprints or set()
    seed_semantic_templates = seed_semantic_templates or set()
    eval_tool_commands = eval_tool_commands or set()
    eval_contexts = eval_contexts or set()
    eval_semantic_templates = eval_semantic_templates or set()
    for record, fingerprint in zip(records, fingerprints):
        if fingerprint in seed_request_fingerprints:
            errors.add(
                f"{record.sample_id} request duplicates P4 Seed V1"
            )
        if record.metadata.semantic_template in seed_semantic_templates:
            errors.add(
                f"{record.sample_id} semantic_template overlaps P4 Seed V1"
            )
        if (record.input.type.value, record.input.command) in eval_tool_commands:
            errors.add(
                f"{record.sample_id} command duplicates frozen Eval V1"
            )
        if canonical_context(record.input.context) in eval_contexts:
            errors.add(
                f"{record.sample_id} context duplicates frozen Eval V1"
            )
        if record.metadata.semantic_template in eval_semantic_templates:
            errors.add(
                f"{record.sample_id} semantic_template duplicates frozen Eval V1"
            )
    categories = _category_counter(records)
    if categories != EXPECTED_CATEGORY_ROWS:
        errors.add("category row counts do not match the targeted profile")
    batches = Counter(record.metadata.batch_id for record in records)
    expected_batches = Counter(
        {f"p4-targeted-v1-batch-{number:03d}": 100 for number in range(1, 6)}
    )
    if batches != expected_batches:
        errors.add("batch counts must be exactly 100 for five targeted batches")
    templates = Counter(record.metadata.semantic_template for record in records)
    if len(templates) != 50 or set(templates.values()) != {10}:
        errors.add("each of 50 semantic templates must own exactly 10 rows")

    quality_report = validate_dataset_bundle(
        train, validation, eval_request_fingerprints
    )
    errors.update(quality_report.errors)
    if errors:
        raise TargetedDatasetError(
            "P4 targeted profile validation failed:\n- "
            + "\n- ".join(sorted(errors))
        )

    return TargetedDatasetSummary(
        total=len(records),
        splits={"train": len(train), "validation": len(validation)},
        categories=_sorted_values(categories),
        tools=_sorted_values(Counter(record.input.type for record in records)),
        scenario_kinds=_sorted_values(
            Counter(record.metadata.scenario_kind for record in records)
        ),
        batches=_sorted_values(batches),
    )


def canonical_jsonl_bytes(records: Iterable[TrainingExample]) -> bytes:
    content = "".join(
        json.dumps(
            record.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
        for record in records
    )
    return content.encode("utf-8")


def build_targeted_manifest(
    train: list[TrainingExample],
    validation: list[TrainingExample],
    train_bytes: bytes,
    validation_bytes: bytes,
) -> dict[str, object]:
    records = [*train, *validation]
    return {
        "batch_count": 5,
        "batch_size": 100,
        "batches": _sorted_values(
            Counter(record.metadata.batch_id for record in records)
        ),
        "categories": _sorted_values(_category_counter(records)),
        "data_version": DATA_VERSION,
        "diagnostic_basis": dict(DIAGNOSTIC_BASIS),
        "evaluation_adaptive": True,
        "generation_source": GENERATION_SOURCE,
        "generator_version": GENERATOR_VERSION,
        "human_reviewed": False,
        "outputs": {"train": TRAIN_PATH, "validation": VALIDATION_PATH},
        "scenario_kinds": _sorted_values(
            Counter(record.metadata.scenario_kind for record in records)
        ),
        "sha256": {
            "train": hashlib.sha256(train_bytes).hexdigest(),
            "validation": hashlib.sha256(validation_bytes).hexdigest(),
        },
        "splits": {"train": len(train), "validation": len(validation)},
        "tools": _sorted_values(Counter(record.input.type for record in records)),
        "total": len(records),
    }
