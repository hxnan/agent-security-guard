"""Deterministic paired hard-negative dataset for P4 Targeted V2."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from typing import Iterable

from guard.contracts import GuardRequest, GuardResult
from guard.taxonomy import CATEGORY_DEFINITIONS, RiskCategory
from training.contrastive_catalog import (
    CONTRASTIVE_PAIRS,
    EXPECTED_RISK_PAIR_COUNTS,
    ContrastivePair,
    validate_contrastive_catalog,
)
from training.data_quality import (
    EvalIsolationKeys,
    canonical_context,
    request_fingerprint,
    validate_dataset_bundle,
)
from training.schema import TrainingExample


class ContrastiveDatasetError(ValueError):
    """Raised when the P4 Targeted V2 bundle violates its fixed profile."""


DATA_VERSION = "p4-targeted-v2"
GENERATION_SOURCE = "curated_contrastive_catalog_v2"
GENERATOR_VERSION = "p4-targeted-generator-v2"
INSTRUCTION = "Analyze this Agent tool call for security risk."
TRAIN_PATH = "data/train/agent_security_targeted_train_v2.jsonl"
VALIDATION_PATH = "data/val/agent_security_targeted_validation_v2.jsonl"
DIAGNOSTIC_BASIS = {
    "report_version": "fusion-eval-report-v1",
    "total_samples": 100,
    "high_risk_allow_miss_count": 0,
    "risk_false_negative_count": 3,
    "benign_false_positive_count": 9,
    "category_error_count": 26,
    "effective_decision_error_count": 19,
}
EXPECTED_CATEGORY_ROWS = Counter(
    {
        RiskCategory.BENIGN: 500,
        **{
            category: pair_count * 10
            for category, pair_count in EXPECTED_RISK_PAIR_COUNTS.items()
        },
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
class ContrastiveDatasetSummary:
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


def _scenario_kind(pair: ContrastivePair, role: str) -> str:
    if role == "benign":
        return "normal"
    if pair.category in {
        RiskCategory.REMOTE_EXECUTION,
        RiskCategory.DATA_EXFILTRATION,
        RiskCategory.DEFENSE_EVASION,
        RiskCategory.DESTRUCTIVE_OPERATION,
        RiskCategory.CREDENTIAL_ACCESS,
        RiskCategory.PERSISTENCE,
    }:
        return "dangerous"
    return "boundary"


def _build_record(
    pair: ContrastivePair,
    role: str,
    variant: int,
    global_index: int,
) -> TrainingExample:
    benign = role == "benign"
    category = RiskCategory.BENIGN if benign else pair.category
    definition = CATEGORY_DEFINITIONS[category]
    command = pair.render(role, variant)
    source_base = pair.benign_source if benign else pair.risky_source
    source = source_base.replace(
        "contrastive_context:", "verified_context:", 1
    )
    summary = pair.benign_summary if benign else pair.risky_summary
    return TrainingExample.model_validate(
        {
            "id": f"TR-{global_index:06d}",
            "instruction": INSTRUCTION,
            "input": GuardRequest(
                type=pair.tool_type,
                command=command,
                context={
                    "cwd": f"/workspace/project-{variant}",
                    "actor": "local-agent",
                    "tool_name": pair.tool_type.value,
                    "privilege": "user",
                    "source": source,
                },
            ).model_dump(mode="json"),
            "output": GuardResult(
                risk=not benign,
                decision=(
                    definition.default_decision
                    if benign or pair.decision is None
                    else pair.decision
                ),
                severity=(
                    definition.default_severity
                    if benign or pair.severity is None
                    else pair.severity
                ),
                category=category,
                summary=summary,
                confidence=0.95,
                evidence=[command, f"context: {source}"],
                rule_hits=[],
                model_version="p4-contrastive-target-v2",
                policy_version="policy-v1",
            ).model_dump(mode="json"),
            "metadata": {
                "data_version": DATA_VERSION,
                "generation_source": GENERATION_SOURCE,
                "semantic_template": (
                    f"contrastive_{pair.split}_{pair.pair_id}_{role}"
                ),
                "split": pair.split,
                "scenario_kind": _scenario_kind(pair, role),
                "batch_id": (
                    "p4-targeted-v2-batch-"
                    f"{(global_index - 1501) // 100 + 1:03d}"
                ),
                "generator_version": GENERATOR_VERSION,
            },
        }
    )


def generate_contrastive_dataset() -> tuple[list[TrainingExample], list[TrainingExample]]:
    validate_contrastive_catalog(CONTRASTIVE_PAIRS)
    train: list[TrainingExample] = []
    validation: list[TrainingExample] = []
    ordered = [
        *(pair for pair in CONTRASTIVE_PAIRS if pair.split == "train"),
        *(pair for pair in CONTRASTIVE_PAIRS if pair.split == "validation"),
    ]
    global_index = 1501
    for pair in ordered:
        destination = train if pair.split == "train" else validation
        for role in ("benign", "risky"):
            for variant in range(1, 11):
                destination.append(
                    _build_record(pair, role, variant, global_index)
                )
                global_index += 1
    return train, validation


def validate_contrastive_profile(
    train: list[TrainingExample],
    validation: list[TrainingExample],
    eval_keys: EvalIsolationKeys,
    *,
    prior_request_fingerprints: set[str],
    prior_semantic_templates: set[str],
    prior_commands: set[str],
    prior_contexts: set[str],
    prior_context_sources: set[str],
) -> ContrastiveDatasetSummary:
    errors: set[str] = set()
    if len(train) != 800:
        errors.add(f"train rows must be 800, got {len(train)}")
    if len(validation) != 200:
        errors.add(f"validation rows must be 200, got {len(validation)}")
    records = [*train, *validation]
    expected_ids = [f"TR-{number:06d}" for number in range(1501, 2501)]
    if [record.sample_id for record in records] != expected_ids:
        errors.add("sample IDs must be contiguous TR-001501 through TR-002500")

    expected_train, expected_validation = generate_contrastive_dataset()
    expected_by_id = {
        record.sample_id: record
        for record in [*expected_train, *expected_validation]
    }
    for record in records:
        if expected_by_id.get(record.sample_id) != record:
            errors.add(
                f"{record.sample_id} does not match its curated contrastive record"
            )

    fingerprints = [request_fingerprint(record.input) for record in records]
    if len(fingerprints) != len(set(fingerprints)):
        errors.add("all contrastive requests must be unique")
    for record, fingerprint in zip(records, fingerprints):
        if fingerprint in prior_request_fingerprints:
            errors.add(f"{record.sample_id} request duplicates prior P4 data")
        if record.metadata.semantic_template in prior_semantic_templates:
            errors.add(f"{record.sample_id} semantic_template overlaps prior P4 data")
        if record.input.command in prior_commands:
            errors.add(f"{record.sample_id} command duplicates prior P4 data")
        if canonical_context(record.input.context) in prior_contexts:
            errors.add(f"{record.sample_id} context duplicates prior P4 data")
        if (record.input.context.source or "") in prior_context_sources:
            errors.add(f"{record.sample_id} context source duplicates prior P4 data")
        if record.input.command in eval_keys.commands:
            errors.add(f"{record.sample_id} command duplicates frozen Eval V1")
        if canonical_context(record.input.context) in eval_keys.contexts:
            errors.add(f"{record.sample_id} context duplicates frozen Eval V1")
        if record.input.context.source in eval_keys.context_sources:
            errors.add(f"{record.sample_id} context source duplicates frozen Eval V1")
        if record.metadata.semantic_template in eval_keys.semantic_templates:
            errors.add(
                f"{record.sample_id} semantic_template duplicates frozen Eval V1"
            )

    categories = Counter(record.output.category for record in records)
    if categories != EXPECTED_CATEGORY_ROWS:
        errors.add("category row counts do not match the contrastive profile")
    batches = Counter(record.metadata.batch_id for record in records)
    expected_batches = Counter(
        {f"p4-targeted-v2-batch-{number:03d}": 100 for number in range(1, 11)}
    )
    if batches != expected_batches:
        errors.add("batch counts must be exactly 100 for ten contrastive batches")
    templates = Counter(record.metadata.semantic_template for record in records)
    if len(templates) != 100 or set(templates.values()) != {10}:
        errors.add("each of 100 semantic templates must own exactly 10 rows")

    quality_report = validate_dataset_bundle(
        train, validation, set(eval_keys.request_fingerprints)
    )
    errors.update(quality_report.errors)
    if errors:
        raise ContrastiveDatasetError(
            "P4 contrastive profile validation failed:\n- "
            + "\n- ".join(sorted(errors))
        )

    return ContrastiveDatasetSummary(
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


def build_contrastive_manifest(
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
        "categories": _sorted_values(
            Counter(record.output.category for record in records)
        ),
        "contrastive_pairs": 50,
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
