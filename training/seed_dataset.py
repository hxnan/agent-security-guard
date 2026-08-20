"""Deterministic expansion and validation for P4 Seed Dataset V1."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from typing import Iterable

from guard.contracts import GuardRequest, GuardResult
from guard.taxonomy import CATEGORY_DEFINITIONS, RiskCategory, ToolType
from training.data_quality import request_fingerprint, validate_dataset_bundle
from training.schema import TrainingExample
from training.seed_catalog import SEED_CLUSTERS, validate_seed_catalog


class SeedDatasetError(ValueError):
    """Raised when generated P4 seed rows drift from the fixed profile."""


DATA_VERSION = "p4-seed-v1"
GENERATION_SOURCE = "curated_scenario_catalog_v1"
GENERATOR_VERSION = "p4-seed-generator-v1"
INSTRUCTION = "Analyze this Agent tool call for security risk."
TRAIN_PATH = "data/train/agent_security_train_v1.jsonl"
VALIDATION_PATH = "data/val/agent_security_validation_v1.jsonl"


EXPECTED_CATEGORY_ROWS = Counter(
    {
        RiskCategory.BENIGN: 300,
        RiskCategory.REMOTE_EXECUTION: 80,
        RiskCategory.UNSAFE_DOWNLOAD: 80,
        RiskCategory.PRIVILEGE_ESCALATION: 60,
        RiskCategory.DESTRUCTIVE_OPERATION: 60,
        RiskCategory.CREDENTIAL_ACCESS: 60,
        RiskCategory.DATA_EXFILTRATION: 60,
        RiskCategory.PERSISTENCE: 60,
        RiskCategory.DEFENSE_EVASION: 60,
        RiskCategory.NETWORK_CHANGE: 60,
        RiskCategory.SENSITIVE_WRITE: 60,
        RiskCategory.RESOURCE_ABUSE: 60,
    }
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
class SeedDatasetSummary:
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
    definition = CATEGORY_DEFINITIONS[cluster.category]
    risk = cluster.category is not RiskCategory.BENIGN
    return TrainingExample.model_validate(
        {
            "id": f"TR-{global_index:06d}",
            "instruction": INSTRUCTION,
            "input": GuardRequest(
                type=cluster.tool_type,
                command=command,
                context={
                    "cwd": f"/workspace/project-{variant}",
                    "actor": "p4-seed-agent",
                    "tool_name": cluster.tool_type.value,
                    "privilege": cluster.privilege,
                    "source": "p4-seed-curated",
                },
            ).model_dump(mode="json"),
            "output": GuardResult(
                risk=risk,
                decision=definition.default_decision,
                severity=definition.default_severity,
                category=cluster.category,
                summary=cluster.summary,
                confidence=cluster.confidence,
                evidence=[command],
                rule_hits=[],
                model_version="p4-seed-target-v1",
                policy_version="policy-v1",
            ).model_dump(mode="json"),
            "metadata": {
                "data_version": DATA_VERSION,
                "generation_source": GENERATION_SOURCE,
                "semantic_template": cluster.semantic_template,
                "split": cluster.split,
                "scenario_kind": cluster.scenario_kind,
                "batch_id": f"p4-seed-v1-batch-{(global_index - 1) // 100 + 1:03d}",
                "generator_version": GENERATOR_VERSION,
            },
        }
    )


def generate_seed_dataset() -> tuple[list[TrainingExample], list[TrainingExample]]:
    validate_seed_catalog(SEED_CLUSTERS)
    train: list[TrainingExample] = []
    validation: list[TrainingExample] = []
    for cluster_index, cluster in enumerate(SEED_CLUSTERS):
        for variant in range(1, 11):
            global_index = cluster_index * 10 + variant
            record = _build_record(cluster, variant, global_index)
            (train if cluster.split == "train" else validation).append(record)
    return train, validation


def _category_counter(records: Iterable[TrainingExample]) -> Counter:
    return Counter(record.output.category for record in records)


def validate_seed_profile(
    train: list[TrainingExample],
    validation: list[TrainingExample],
    eval_request_fingerprints: set[str],
) -> SeedDatasetSummary:
    errors: set[str] = set()
    if len(train) != 800:
        errors.add(f"train rows must be 800, got {len(train)}")
    if len(validation) != 200:
        errors.add(f"validation rows must be 200, got {len(validation)}")
    records = [*train, *validation]

    expected_ids = [f"TR-{number:06d}" for number in range(1, 1001)]
    actual_ids = [record.sample_id for record in records]
    if actual_ids != expected_ids:
        errors.add("sample IDs must be contiguous TR-000001 through TR-001000")

    expected_train, expected_validation = generate_seed_dataset()
    expected_by_id = {
        record.sample_id: record for record in [*expected_train, *expected_validation]
    }
    for record in records:
        expected = expected_by_id.get(record.sample_id)
        if expected is None or record != expected:
            errors.add(
                f"{record.sample_id} does not match its curated seed record"
            )

    fingerprints = [request_fingerprint(record.input) for record in records]
    if len(fingerprints) != len(set(fingerprints)):
        errors.add("all generated requests must be unique")

    categories = _category_counter(records)
    if categories != EXPECTED_CATEGORY_ROWS:
        errors.add("category row counts do not match the fixed profile")

    batches = Counter(record.metadata.batch_id for record in records)
    expected_batches = Counter(
        {f"p4-seed-v1-batch-{number:03d}": 100 for number in range(1, 11)}
    )
    if batches != expected_batches:
        errors.add("batch counts must be exactly 100 for ten fixed batches")

    templates = Counter(record.metadata.semantic_template for record in records)
    if len(templates) != 100 or set(templates.values()) != {10}:
        errors.add("each of 100 semantic templates must own exactly 10 rows")
    if {record.input.type for record in records} != set(ToolType):
        errors.add("generated rows must cover every tool type")
    if {record.metadata.scenario_kind for record in records} != {
        "normal",
        "dangerous",
        "boundary",
        "injection",
    }:
        errors.add("generated rows must cover every scenario kind")

    quality_report = validate_dataset_bundle(
        train, validation, eval_request_fingerprints
    )
    errors.update(quality_report.errors)
    if errors:
        raise SeedDatasetError(
            "P4 seed profile validation failed:\n- " + "\n- ".join(sorted(errors))
        )

    return SeedDatasetSummary(
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


def build_seed_manifest(
    train: list[TrainingExample],
    validation: list[TrainingExample],
    train_bytes: bytes,
    validation_bytes: bytes,
) -> dict[str, object]:
    records = [*train, *validation]
    return {
        "batch_count": 10,
        "batch_size": 100,
        "batches": _sorted_values(
            Counter(record.metadata.batch_id for record in records)
        ),
        "categories": _sorted_values(_category_counter(records)),
        "data_version": DATA_VERSION,
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
