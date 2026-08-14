# Eval V1 Gold Dataset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a machine-validated Eval V1 gold-dataset contract, draft/freeze validation, statistics tooling, tests, and documentation without changing runtime Guard contracts.

**Architecture:** `guard/eval_dataset.py` owns the evaluation-only Pydantic models and dataset-wide validation. Two small CLI scripts expose validation and statistics. The committed blueprint remains the source of quota/planning metadata; ordered JSONL shards under `data/eval-v1/gold/` wrap the existing runtime request/result contracts plus governance metadata.

**Tech Stack:** Python 3.10+, Pydantic v2, standard library `json`/`collections`/`pathlib`, `unittest`.

## Global Constraints

- Do not execute any command contained in evaluation data.
- Do not import Torch, Transformers, PEFT, or model files from evaluation validation code.
- Keep `GuardRequest` and `GuardResult` V1 unchanged.
- Confidence values are exactly `0.50`, `0.60`, `0.75`, `0.90`, or `0.99`.
- Frozen rows must have review state `agreed` or `adjudicated`.
- Draft/pending rows must never be represented as independently reviewed.
- Generated first-pass rows must use explicit provenance (`source=llm-assisted-draft`).

---

### Task 1: Gold record contract and safety consistency

**Files:**
- Create: `tests/test_eval_dataset.py`
- Create: `guard/eval_dataset.py`

- [x] **Step 1: Write failing tests** for a valid benign record, invalid `risk=true + allow`, invalid confidence, non-benign missing evidence, and default override without `override_reason`.
- [x] **Step 2: Run targeted tests and confirm RED.**
- [x] **Step 3: Implement minimal Pydantic models and consistency validation.**
- [x] **Step 4: Re-run targeted tests and confirm GREEN.**

### Task 2: JSONL loading and dataset-wide validation

**Files:**
- Modify: `tests/test_eval_dataset.py`
- Modify: `guard/eval_dataset.py`

- [x] **Step 1: Add failing tests** for malformed JSONL, duplicate IDs, non-contiguous IDs, tool metadata mismatch, frozen review-state enforcement, and directory shard loading.
- [x] **Step 2: Run targeted tests and confirm RED.**
- [x] **Step 3: Implement file/directory loader and dataset checks with deterministic error messages.**
- [x] **Step 4: Run targeted tests and confirm GREEN.**

### Task 3: Blueprint preservation and statistics

**Files:**
- Modify: `tests/test_eval_dataset.py`
- Modify: `guard/eval_dataset.py`

- [x] **Step 1: Add failing tests** showing a category mismatch against blueprint and stable count output.
- [x] **Step 2: Run targeted tests and confirm RED.**
- [x] **Step 3: Implement blueprint comparison and deterministic counters.**
- [x] **Step 4: Run targeted tests and confirm GREEN.**

### Task 4: Validation/report command-line tools

**Files:**
- Create: `scripts/validate_eval_dataset.py`
- Create: `scripts/report_eval_dataset.py`
- Create: `tests/test_eval_dataset_cli.py`

- [x] **Step 1: Add failing CLI subprocess tests** for draft success, frozen rejection, and report output.
- [x] **Step 2: Run targeted tests and confirm RED.**
- [x] **Step 3: Implement thin CLIs around `guard.eval_dataset`.**
- [x] **Step 4: Run targeted tests and confirm GREEN.**

### Task 5: Seed gold authoring shards and documentation

**Files:**
- Create: `data/eval-v1/gold/*.jsonl`
- Modify: `README.md`
- Modify: `docs/work_plan.md`

- [x] **Step 1: Author EV001–EV100 from the existing blueprint, preserving IDs/tool families/scenario kinds/categories/templates/variants.**
- [x] **Step 2: Keep every generated row explicitly `llm-assisted-draft + pending`.**
- [x] **Step 3: Split records into ten ordered 10-row review shards and verify directory loading.**
- [x] **Step 4: Run complete draft validation and statistics.**
- [x] **Step 5: Add a committed-data regression test requiring 100 pending rows and proving frozen validation fails.**
- [x] **Step 6: Update README commands and work-plan status so draft and frozen states are explicit.**

### Task 6: Full verification and publish

**Files:** all changed files.

- [x] **Step 1: Run targeted Eval dataset/CLI tests in the reconstructed isolated workspace.**
- [x] **Step 2: Run complete draft validation against the committed Blueprint in the isolated workspace.**
- [x] **Step 3: Push implementation, tests, 100 draft rows, and docs to `feat/eval-v1-gold-dataset`.**
- [x] **Step 4: Open Draft PR #1.**
- [ ] **Step 5: Observe the latest GitHub Actions run and fix any CI failures.**
- [ ] **Step 6: Run final branch review and merge to `main` only after CI is green.**
