# Eval V1 Gold Dataset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a machine-validated Eval V1 gold-dataset contract, draft/freeze validation, statistics tooling, tests, and documentation without changing runtime Guard contracts.

**Architecture:** `guard/eval_dataset.py` owns the evaluation-only Pydantic models and dataset-wide validation. Two small CLI scripts expose validation and statistics. The committed blueprint remains the source of quota/planning metadata; gold rows wrap the existing runtime request/result contracts plus governance metadata.

**Tech Stack:** Python 3.10+, Pydantic v2, standard library `json`/`collections`/`pathlib`, `unittest`.

## Global Constraints

- Do not execute any command contained in evaluation data.
- Do not import Torch, Transformers, PEFT, or model files from evaluation validation code.
- Keep `GuardRequest` and `GuardResult` V1 unchanged.
- Confidence values are exactly `0.50`, `0.60`, `0.75`, `0.90`, or `0.99`.
- Frozen rows must have review state `agreed` or `adjudicated`.
- Draft/pending rows must never be represented as independently reviewed.

---

### Task 1: Gold record contract and safety consistency

**Files:**
- Create: `tests/test_eval_dataset.py`
- Create: `guard/eval_dataset.py`

**Interfaces:**
- Consumes: `GuardRequest`, `GuardResult`, `Decision`, `RiskCategory`, `Severity`, `ToolType`, `ToolFamily`, `ScenarioKind`.
- Produces: `ReviewStatus`, `EvalGoldMetadata`, `EvalGoldRecord`, `EvalDatasetValidationError`, `validate_record_consistency(record)`.

- [ ] **Step 1: Write failing tests** for a valid benign record, invalid `risk=true + allow`, invalid confidence, non-benign missing evidence, and default override without `override_reason`.
- [ ] **Step 2: Run** `python -m unittest tests.test_eval_dataset -v` and confirm failures are caused by missing `guard.eval_dataset`.
- [ ] **Step 3: Implement minimal Pydantic models and consistency validation.**
- [ ] **Step 4: Re-run** `python -m unittest tests.test_eval_dataset -v` and confirm Task 1 tests pass.

### Task 2: JSONL loading and dataset-wide validation

**Files:**
- Modify: `tests/test_eval_dataset.py`
- Modify: `guard/eval_dataset.py`

**Interfaces:**
- Produces: `load_eval_dataset(path) -> list[EvalGoldRecord]`, `validate_eval_dataset(records, *, require_complete=False, require_frozen=False)`.

- [ ] **Step 1: Add failing tests** for malformed JSONL, duplicate IDs, non-contiguous IDs, mixed/non-mixed tool metadata mismatch, and frozen review-state enforcement.
- [ ] **Step 2: Run targeted tests and confirm RED.**
- [ ] **Step 3: Implement loader and dataset checks with deterministic error messages.**
- [ ] **Step 4: Run targeted tests and confirm GREEN.**

### Task 3: Blueprint preservation and statistics

**Files:**
- Modify: `tests/test_eval_dataset.py`
- Modify: `guard/eval_dataset.py`

**Interfaces:**
- Produces: `validate_against_blueprint(records, blueprint_records)`, `build_eval_dataset_stats(records) -> dict[str, object]`.

- [ ] **Step 1: Add failing tests** showing a category mismatch against blueprint and stable count output.
- [ ] **Step 2: Run targeted tests and confirm RED.**
- [ ] **Step 3: Implement blueprint comparison and deterministic counters.**
- [ ] **Step 4: Run targeted tests and confirm GREEN.**

### Task 4: Validation/report command-line tools

**Files:**
- Create: `scripts/validate_eval_dataset.py`
- Create: `scripts/report_eval_dataset.py`
- Modify: `tests/test_eval_dataset.py`

**Interfaces:**
- Validation CLI: `python scripts/validate_eval_dataset.py [--dataset PATH] [--require-complete] [--require-frozen]`.
- Report CLI: `python scripts/report_eval_dataset.py [--dataset PATH]`.

- [ ] **Step 1: Add failing CLI tests** for parser defaults and JSON success/error payload functions without subprocess/model dependencies.
- [ ] **Step 2: Run targeted tests and confirm RED.**
- [ ] **Step 3: Implement thin CLIs around `guard.eval_dataset`.**
- [ ] **Step 4: Run targeted tests and confirm GREEN.**

### Task 5: Seed gold authoring file and documentation

**Files:**
- Create: `data/eval-v1/gold.jsonl`
- Modify: `README.md`
- Modify: `docs/work_plan.md`

**Interfaces:**
- The seed file is draft-authoring data and may contain `pending` rows; it must pass structural validation but not `--require-frozen` until independent review is complete.

- [ ] **Step 1: Author gold rows from the existing blueprint, preserving IDs/tool families/scenario kinds/categories.**
- [ ] **Step 2: Run draft validation and statistics.**
- [ ] **Step 3: Update README commands and work-plan status so draft and frozen states are explicit.**

### Task 6: Full verification and publish

**Files:** all changed files.

- [ ] **Step 1: Run** `python -m unittest discover -s tests -v` in the reconstructed isolated test workspace.
- [ ] **Step 2: Review branch diff against this plan and the design spec.**
- [ ] **Step 3: Push all verified files to `feat/eval-v1-gold-dataset`.**
- [ ] **Step 4: Open a draft PR, observe GitHub Actions, fix any CI failures, and only merge after CI is green.**
