# P4 Training Data Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a strict CPU-only gate that validates P4 train/validation JSONL contracts and rejects split or Eval V1 leakage.

**Architecture:** `training.schema` owns the reusable row contract. `training.data_quality` loads rows, fingerprints requests, and validates the bundle; the CLI is a thin deterministic JSON adapter. Existing placeholder generation, random splitting, and fake training entrypoints are removed because they do not meet the isolation contract.

**Tech Stack:** Python 3.10+, Pydantic 2.13.4, standard-library `json`, `hashlib`, `unittest`.

**Spec:** `docs/superpowers/specs/2026-08-20-p4-training-data-quality-gate-design.md`

## Global Constraints

- Do not modify `data/eval-v1/**` or model weights.
- Eval V1 labels must never enter training records.
- Train and validation must be separate inputs with disjoint IDs, requests, and semantic templates.
- The gate must run without model, GPU, Torch, Transformers, PEFT, or pytest.
- CLI failures must be deterministic JSON with exit code 1 and no traceback.

---

### Task 1: Training row contract and loader

**Files:**
- Replace: `training/schema.py`
- Replace: `training/data_quality.py`
- Create: `tests/test_p4_training_data_quality.py`

**Interfaces:**
- Consumes: `guard.contracts.GuardRequest`, `guard.contracts.GuardResult`.
- Produces: `TrainingExample`, `load_training_jsonl(path, expected_split)`.

- [x] **Step 1: Write failing unittest cases** for valid rows, malformed JSON with line numbers, duplicate IDs, split mismatch, and GuardResult semantic contradictions, including:

```python
with self.assertRaisesRegex(DatasetQualityError, "line 2: invalid JSON"):
    load_training_jsonl(path, expected_split="train")

with self.assertRaisesRegex(ValidationError, "non-benign output cannot allow"):
    TrainingExample.model_validate(non_benign_allow_row)
```
- [x] **Step 2: Run** `python -m unittest tests.test_p4_training_data_quality -v` and confirm failures come from missing strict behavior.
- [x] **Step 3: Implement** the exact public surface:

```python
class TrainingExample(BaseModel):
    sample_id: str = Field(alias="id", pattern=r"^TR-[0-9]{6}$")
    instruction: str
    input: GuardRequest
    output: GuardResult
    metadata: TrainingMetadata

def load_training_jsonl(
    path: Path | str,
    expected_split: Literal["train", "validation"],
) -> list[TrainingExample]:
    examples = []
    seen_ids = set()
    for line_number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if line.strip():
            example = TrainingExample.model_validate_json(line)
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
```
- [x] **Step 4: Re-run** the focused module and require all Task 1 cases to pass.

### Task 2: Bundle isolation and CLI

**Files:**
- Modify: `training/data_quality.py`
- Replace: `scripts/check_training_dataset.py`
- Modify: `tests/test_p4_training_data_quality.py`
- Create: `tests/test_p4_training_dataset_cli.py`

**Interfaces:**
- Consumes: validated `TrainingExample` lists and frozen Eval V1 requests.
- Produces: `validate_dataset_bundle(train, validation, eval_requests)` and deterministic CLI JSON.

- [x] **Step 1: Write failing unittest cases** for overlapping IDs, request fingerprints, semantic templates, `EV###`/Eval/Gold provenance, exact Eval request leakage, valid distributions, and CLI success/failure exit codes, including:

```python
report = validate_dataset_bundle(train, validation, eval_fingerprints)
self.assertIn("cross-split semantic_template overlap", " ".join(report.errors))
self.assertEqual(completed.returncode, 1)
self.assertNotIn("Traceback", completed.stderr)
```
- [x] **Step 2: Run** `python -m unittest tests.test_p4_training_data_quality tests.test_p4_training_dataset_cli -v` and confirm the isolation cases fail for missing behavior.
- [x] **Step 3: Implement** canonical SHA-256 request fingerprints, marker scanning, sorted error aggregation, category summaries, and these CLI arguments:

```python
parser.add_argument("--train", required=True)
parser.add_argument("--validation", required=True)
parser.add_argument("--eval-dir", default=str(DEFAULT_EVAL_DIR))
```
- [x] **Step 4: Re-run** both focused modules and require all Task 2 cases to pass.

### Task 3: Remove misleading scaffolds and document the gate

**Files:**
- Delete: `training/data_builder.py`
- Delete: `training/qlora_config.py`
- Delete: `training/split_dataset.py`
- Delete: `scripts/prepare_training_data.py`
- Delete: `scripts/train_qlora_guard.py`
- Modify: `docs/p4_qlora_pipeline_v1.md`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: Task 1/2 public functions.
- Produces: installed `training` package and accurate operator documentation.

- [x] **Step 1: Update documentation** with the exact two-file checker command, gate meanings, and explicit non-goals.
- [x] **Step 2: Remove** placeholder four-row generation, random row splitting, duplicate QLoRA config, and the no-op training entrypoint.
- [x] **Step 3: Package** `training*` alongside `guard*` and `evaluation*`.
- [x] **Step 4: Verify** focused tests, full `unittest` discovery, Blueprint/freeze/schema drift gates, wheel contents, changed-file scope, and `git diff --check`.
