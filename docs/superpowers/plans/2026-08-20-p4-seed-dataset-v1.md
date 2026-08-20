# P4 Seed Dataset V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate and commit a deterministic 1,000-row P4 seed corpus with semantic-cluster train/validation isolation, complete provenance, and frozen-Eval leakage validation.

**Architecture:** `training.seed_catalog` contains 100 curated semantic cluster definitions and no file I/O. `training.seed_dataset` validates and expands those clusters into strict `TrainingExample` rows, computes summaries and a manifest, and writes canonical files. A thin CLI invokes generation and the existing quality gate; committed-data tests lock the generated corpus.

**Tech Stack:** Python 3.10+, Pydantic 2, standard-library `dataclasses`, `json`, `hashlib`, `pathlib`, and `unittest`.

**Spec:** `docs/superpowers/specs/2026-08-20-p4-seed-dataset-v1-design.md`

## Global Constraints

- Produce exactly 1,000 committed rows: 800 train and 200 validation.
- Split 100 semantic clusters, not rows: 80 train-only and 20 validation-only, with 10 variants per cluster.
- Produce ten batches of exactly 100 rows using `p4-seed-v1-batch-NNN` identifiers.
- Use no model, GPU, Torch, Transformers, PEFT, or bitsandbytes in generation or validation.
- Never use Eval labels or requests to construct records; Eval V1 is read only after generation for fingerprint rejection.
- Do not modify `data/eval-v1/**`, `schemas/v1/**`, model files, or artifacts.
- Commit the generated train, validation, and manifest files.

---

### Task 1: Extend strict training provenance

**Files:**
- Modify: `training/schema.py`
- Modify: `tests/test_p4_training_data_quality.py`

**Interfaces:**
- Consumes: existing `TrainingMetadata` and `TrainingExample`.
- Produces: required `scenario_kind`, `batch_id`, and `generator_version` metadata fields.

- [ ] **Step 1: Update the test row fixture and write failing contract tests**

Add these metadata values to `row()`:

```python
"scenario_kind": "normal",
"batch_id": "p4-seed-v1-batch-001",
"generator_version": "p4-seed-generator-v1",
```

Add tests that remove each new field and reject invalid scenario/batch/version values:

```python
for field in ("scenario_kind", "batch_id", "generator_version"):
    value = row()
    value["metadata"].pop(field)
    with self.assertRaises(ValidationError):
        TrainingExample.model_validate(value)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m unittest tests.test_p4_training_data_quality -v`

Expected: failures because `TrainingMetadata` rejects the newly supplied fields as extras.

- [ ] **Step 3: Implement the exact metadata contract**

Add:

```python
scenario_kind: Literal["normal", "dangerous", "boundary", "injection"]
batch_id: str = Field(pattern=r"^p4-seed-v1-batch-[0-9]{3}$")
generator_version: str = Field(pattern=r"^p4-seed-generator-v[0-9]+$")
```

- [ ] **Step 4: Run the focused quality-gate tests and verify GREEN**

Run: `python -m unittest tests.test_p4_training_data_quality tests.test_p4_training_dataset_cli -v`

Expected: all tests pass.

- [ ] **Step 5: Commit exact files**

```bash
git add -- training/schema.py tests/test_p4_training_data_quality.py
git commit -m "feat: add P4 seed provenance contract"
```

### Task 2: Curated semantic-cluster catalog

**Files:**
- Create: `training/seed_catalog.py`
- Create: `tests/test_p4_seed_catalog.py`

**Interfaces:**
- Consumes: `Decision`, `RiskCategory`, `Severity`, `ToolType`, and `CATEGORY_DEFINITIONS`.
- Produces: `SeedCluster`, `SEED_CLUSTERS`, and `validate_seed_catalog(clusters) -> None`.

- [ ] **Step 1: Write failing catalog tests**

Require:

```python
self.assertEqual(len(SEED_CLUSTERS), 100)
self.assertEqual(Counter(c.split for c in SEED_CLUSTERS), {"train": 80, "validation": 20})
self.assertEqual(Counter(c.category for c in SEED_CLUSTERS)[RiskCategory.BENIGN], 30)
self.assertEqual(Counter(c.category for c in SEED_CLUSTERS)[RiskCategory.REMOTE_EXECUTION], 8)
self.assertEqual(Counter(c.category for c in SEED_CLUSTERS)[RiskCategory.UNSAFE_DOWNLOAD], 8)
```

Also require every other non-benign category to have six clusters, unique semantic templates, every tool/scenario kind to occur, every command template to render distinct non-empty variants 1–10, and a deliberately duplicated template to raise `SeedCatalogError`.

- [ ] **Step 2: Run the catalog module and verify RED**

Run: `python -m unittest tests.test_p4_seed_catalog -v`

Expected: import failure because `training.seed_catalog` does not exist.

- [ ] **Step 3: Implement the catalog contract and validation**

Define:

```python
@dataclass(frozen=True)
class SeedCluster:
    semantic_template: str
    split: Literal["train", "validation"]
    category: RiskCategory
    tool_type: ToolType
    scenario_kind: Literal["normal", "dangerous", "boundary", "injection"]
    command_template: str
    summary: str
    confidence: float = 0.95
    privilege: str = "user"

    def render_command(self, variant: int) -> str:
        if variant not in range(1, 11):
            raise SeedCatalogError("variant must be between 1 and 10")
        return self.command_template.format(n=variant, port=8000 + variant)
```

`validate_seed_catalog` must aggregate deterministic errors for count, split,
category, template, coverage, rendering, summary, and taxonomy-default label
invariants. Populate 100 explicit catalog entries; do not derive them from Eval
or the smoke catalog.

- [ ] **Step 4: Run catalog tests and verify GREEN**

Run: `python -m unittest tests.test_p4_seed_catalog -v`

Expected: all tests pass.

- [ ] **Step 5: Commit exact files**

```bash
git add -- training/seed_catalog.py tests/test_p4_seed_catalog.py
git commit -m "feat: add curated P4 seed scenario catalog"
```

### Task 3: Deterministic expansion, profile, and manifest

**Files:**
- Create: `training/seed_dataset.py`
- Create: `tests/test_p4_seed_dataset.py`

**Interfaces:**
- Consumes: `SEED_CLUSTERS`, `TrainingExample`, and `validate_dataset_bundle`.
- Produces: `generate_seed_dataset() -> tuple[list[TrainingExample], list[TrainingExample]]`, `validate_seed_profile(train, validation, eval_request_fingerprints) -> SeedDatasetSummary`, and `build_seed_manifest(train, validation, train_bytes, validation_bytes) -> dict[str, object]`.

- [ ] **Step 1: Write failing expansion tests**

Require exact IDs, 800/200 split, unique fingerprints, category counts, ten
100-row batch IDs, complete tool/scenario coverage, disjoint templates, and
byte-stable regeneration:

```python
train, validation = generate_seed_dataset()
self.assertEqual([train[0].sample_id, validation[-1].sample_id], ["TR-000001", "TR-001000"])
self.assertEqual((len(train), len(validation)), (800, 200))
self.assertEqual(len({request_fingerprint(x.input) for x in train + validation}), 1000)
```

Require the manifest hashes to equal SHA-256 of the exact canonical JSONL
bytes and mutation tests to reject an incorrect count, batch size, or category
quota.

- [ ] **Step 2: Run the dataset module and verify RED**

Run: `python -m unittest tests.test_p4_seed_dataset -v`

Expected: import failure because `training.seed_dataset` does not exist.

- [ ] **Step 3: Implement deterministic record expansion**

Use these fixed values:

```python
DATA_VERSION = "p4-seed-v1"
GENERATION_SOURCE = "curated_scenario_catalog_v1"
GENERATOR_VERSION = "p4-seed-generator-v1"
INSTRUCTION = "Analyze this Agent tool call for security risk."
```

For each catalog entry and variant, construct `GuardRequest`, taxonomy-default
`GuardResult`, and `TrainingMetadata`. Assign IDs by original catalog position
and variant so the full logical order is `TR-000001`–`TR-001000`; return train
and validation lists without renumbering. Assign batch number from global row
index: `(index - 1) // 100 + 1`.

- [ ] **Step 4: Implement profile and manifest validation**

`validate_seed_profile` must require the exact spec counts and pass the supplied
Eval fingerprints to the existing bundle gate. Manifest output must
sort all distribution dictionaries and include:

```python
{
    "data_version": DATA_VERSION,
    "generator_version": GENERATOR_VERSION,
    "total": 1000,
    "batch_size": 100,
    "batch_count": 10,
    "splits": {"train": 800, "validation": 200},
    "sha256": {"train": ..., "validation": ...},
}
```

- [ ] **Step 5: Run dataset and existing gate tests and verify GREEN**

Run: `python -m unittest tests.test_p4_seed_dataset tests.test_p4_training_data_quality -v`

Expected: all tests pass.

- [ ] **Step 6: Commit exact files**

```bash
git add -- training/seed_dataset.py tests/test_p4_seed_dataset.py
git commit -m "feat: generate deterministic P4 seed records"
```

### Task 4: Atomic CLI and committed dataset

**Files:**
- Create: `scripts/prepare_training_data.py`
- Create: `tests/test_p4_prepare_training_data_cli.py`
- Create: `data/train/agent_security_train_v1.jsonl`
- Create: `data/val/agent_security_validation_v1.jsonl`
- Create: `data/train/agent_security_seed_v1_manifest.json`

**Interfaces:**
- Consumes: generation, profile/manifest, frozen Eval fingerprint loader, and bundle validation.
- Produces: `prepare_seed_dataset(train_path, validation_path, manifest_path, eval_dir, force=False) -> dict[str, object]` and a deterministic JSON CLI.

- [ ] **Step 1: Write failing writer and CLI tests**

In a temporary directory require successful creation, quality status `ok`,
manifest hash agreement, overwrite refusal without `--force`, force
regeneration with byte-identical outputs, missing Eval error JSON/exit 1, and
operation from a non-repository working directory.

```python
self.assertEqual(completed.returncode, 0, completed.stderr)
self.assertEqual(payload["status"], "ok")
self.assertEqual(payload["total"], 1000)
self.assertNotIn("Traceback", completed.stderr)
```

- [ ] **Step 2: Run CLI tests and verify RED**

Run: `python -m unittest tests.test_p4_prepare_training_data_cli -v`

Expected: failure because the CLI does not exist.

- [ ] **Step 3: Implement atomic generation and deterministic error output**

Write all three payloads to sibling `.tmp` files, run strict parsing and the
frozen-Eval bundle gate against those contents, then replace final paths only
when every validation succeeds. Refuse if any final path exists and `force` is
false. Catch only expected `SeedDatasetError`, `DatasetQualityError`,
`OSError`, and `UnicodeError`; print one sorted JSON object and exit 1.

- [ ] **Step 4: Run CLI tests and verify GREEN**

Run: `python -m unittest tests.test_p4_prepare_training_data_cli -v`

Expected: all tests pass.

- [ ] **Step 5: Generate the committed corpus through the CLI**

Run:

```bash
python scripts/prepare_training_data.py --force
python scripts/check_training_dataset.py \
  --train data/train/agent_security_train_v1.jsonl \
  --validation data/val/agent_security_validation_v1.jsonl
```

Expected: both commands emit `status=ok`; counts are 800/200 and the manifest
reports 1,000 rows and ten batches.

- [ ] **Step 6: Add committed-data regression assertions**

Extend `tests/test_p4_seed_dataset.py` to load the three repository files,
re-generate bytes in memory, and require byte-for-byte equality plus frozen
Eval gate success.

- [ ] **Step 7: Commit exact files**

```bash
git add -- scripts/prepare_training_data.py tests/test_p4_prepare_training_data_cli.py \
  tests/test_p4_seed_dataset.py data/train/agent_security_train_v1.jsonl \
  data/val/agent_security_validation_v1.jsonl \
  data/train/agent_security_seed_v1_manifest.json
git commit -m "feat: commit P4 seed dataset v1"
```

### Task 5: Documentation, status, and release verification

**Files:**
- Modify: `README.md`
- Modify: `docs/p4_qlora_pipeline_v1.md`
- Modify: `docs/work_plan.md`
- Create: `docs/superpowers/plans/2026-08-20-p4-seed-dataset-v1.md`

**Interfaces:**
- Consumes: all earlier task commands and manifest values.
- Produces: operator instructions and accurate P3/P4 project status.

- [ ] **Step 1: Document measured Fusion and P4 status**

Record the supplied Fusion V1 compact metrics, mark P3 formal evaluation
complete, document generation/check commands, and state that P4 Seed V1 is the
first 1,000-row batch rather than the final 5,000–10,000 corpus.

- [ ] **Step 2: Run full verification**

Run:

```bash
python -m unittest discover -s tests -v
python scripts/validate_eval_blueprint.py
python scripts/validate_eval_freeze.py
python scripts/export_schemas.py
git diff --exit-code -- schemas/v1
python scripts/prepare_training_data.py --force
python scripts/check_training_dataset.py \
  --train data/train/agent_security_train_v1.jsonl \
  --validation data/val/agent_security_validation_v1.jsonl
git diff --exit-code -- data/train/agent_security_train_v1.jsonl \
  data/val/agent_security_validation_v1.jsonl \
  data/train/agent_security_seed_v1_manifest.json
git diff --check
```

Expected: all commands exit 0; full suite is green; regeneration causes no
committed-data drift.

- [ ] **Step 3: Verify protected scope and package artifact**

Require no changes under `data/eval-v1/**`, `schemas/v1/**`, model, or artifact
paths. Build a wheel and require `training/seed_catalog.py` and
`training/seed_dataset.py` to be present.

- [ ] **Step 4: Commit exact documentation and plan files**

```bash
git add -- README.md docs/p4_qlora_pipeline_v1.md docs/work_plan.md \
  docs/superpowers/plans/2026-08-20-p4-seed-dataset-v1.md
git commit -m "docs: record P4 seed dataset workflow"
```

- [ ] **Step 5: Request independent code review and resolve all Critical/Important findings**

Review against the spec, exact main base, generated-data determinism, label
semantics, leakage boundaries, CLI atomicity, and protected path scope. Re-run
the full verification after any fix.
