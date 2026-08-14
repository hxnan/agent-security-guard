# Eval V1 Adjudication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the committed independent-agent blind review into a deterministic, auditable Eval V1 technical freeze while preserving raw Gold and review evidence.

**Architecture:** Keep Gold Draft and blind-review files immutable. Add an adjudication ledger plus resolver that produces reviewed `EvalGoldRecord` objects in memory, separates substantive label disagreements from summary paraphrases, and permits planned-category overrides only after explicit adjudication. A freeze CLI validates the resolved 100-record view and prints deterministic stats.

**Tech Stack:** Python 3.10+, Pydantic v2, unittest, existing Eval V1 contracts and GitHub Actions CI.

## Global Constraints

- Never execute any command contained in Eval V1.
- Blind-review evidence remains unchanged.
- Reviewer identity is `independent-agent:gpt-5.6-sol`; this is not human review.
- Substantive equality fields are exactly `decision`, `severity`, `category`.
- `summary` differences are reported separately and are not an equality gate.
- All 14 substantive disagreements require explicit adjudication.
- Final technical-freeze manifest must state `human_reviewed=false`.

---

### Task 1: Separate label disagreements from summary wording

**Files:**
- Modify: `guard/eval_review.py`
- Modify: `scripts/compare_eval_review.py`
- Modify: `tests/test_eval_review.py`
- Modify: `tests/test_eval_review_cli.py`

**Interfaces:**
- Produce a comparison object containing `label_differences: tuple[str, ...]` and `summary_differs: bool`.
- CLI returns exit `3` only when at least one substantive label disagreement exists.

- [ ] Write failing tests proving summary-only paraphrases are reported separately and do not count as substantive disagreement.
- [ ] Run the focused tests and verify RED.
- [ ] Implement the smallest comparison/CLI change.
- [ ] Run focused tests and verify GREEN.
- [ ] Commit.

### Task 2: Add adjudication contracts and resolver

**Files:**
- Create: `guard/eval_adjudication.py`
- Create: `tests/test_eval_adjudication.py`

**Interfaces:**
- `EvalAdjudicationRecord`: sample ID, resolution (`gold|review`), note, optional override reason.
- `load_adjudications(path: Path)`.
- `resolve_reviewed_dataset(gold_records, review_answers, adjudications, reviewer_id)` -> `list[EvalGoldRecord]`.

Behavior:
- Label-agree records become `agreed` and keep Gold expected result.
- Label-disagree records require one adjudication.
- `gold` resolution keeps Gold result and marks `adjudicated`.
- `review` resolution applies reviewer result fields, recalculates `risk`, and marks `adjudicated`.
- Actual differing label field names populate `disputed_fields`.
- Missing/duplicate/unused adjudications fail validation.

- [ ] Write focused failing resolver tests.
- [ ] Run and verify RED.
- [ ] Implement minimal resolver.
- [ ] Run and verify GREEN.
- [ ] Commit.

### Task 3: Permit adjudicated planned-category corrections

**Files:**
- Modify: `guard/eval_dataset.py`
- Modify: `tests/test_eval_dataset.py`

**Interfaces:**
- `validate_against_blueprint` continues exact matching for identity fields.
- A `planned_category` mismatch is allowed only when `review_status=adjudicated`; pending/agreed mismatches remain errors.

- [ ] Write failing tests for allowed adjudicated mismatch and rejected agreed mismatch.
- [ ] Run and verify RED.
- [ ] Implement minimal conditional exception.
- [ ] Run and verify GREEN.
- [ ] Commit.

### Task 4: Commit adjudication ledger and technical-freeze manifest

**Files:**
- Create: `data/eval-v1/reviews/adjudication-2026-08-14.jsonl`
- Create: `data/eval-v1/freeze-manifest.json`
- Test: `tests/test_eval_adjudication.py`

Adjudication ledger contains exactly 14 rows:
- reviewer selected: EV022, EV024, EV026, EV050, EV060, EV081, EV082, EV087
- Gold selected: EV023, EV046, EV047, EV058, EV083, EV084

- [ ] Add a failing committed-data test requiring 14 exact adjudications and manifest provenance.
- [ ] Run and verify RED.
- [ ] Add ledger and manifest.
- [ ] Run and verify GREEN.
- [ ] Commit.

### Task 5: Add freeze validator CLI

**Files:**
- Create: `scripts/validate_eval_freeze.py`
- Create: `tests/test_eval_freeze_cli.py`
- Modify: `README.md`
- Modify: `docs/work_plan.md`

**Interfaces:**
- Defaults load committed Gold, blind review, adjudication ledger and blueprint.
- Resolve in memory, validate `require_complete=True`, `require_frozen=True`, then validate blueprint identity.
- JSON output includes total, review statuses, final category/decision/severity counts, substantive disagreement count, reviewer-selected adjudications, Gold-selected adjudications, and `human_reviewed=false`.

- [ ] Write CLI failure/success tests first.
- [ ] Run and verify RED.
- [ ] Implement CLI and docs.
- [ ] Run focused and full unit tests.
- [ ] Run the real committed freeze validation.
- [ ] Commit.

### Task 6: Integration gate

- [ ] Run `python -m unittest discover -s tests -v`.
- [ ] Run `python scripts/validate_eval_blueprint.py`.
- [ ] Run `python scripts/validate_eval_dataset.py --require-complete` to ensure raw Draft remains valid.
- [ ] Run `python scripts/validate_eval_freeze.py` and confirm 100 resolved records, 86 agreed, 14 adjudicated, 0 pending/disputed, and `human_reviewed=false`.
- [ ] Open PR, require Python 3.10/3.12 CI green, review diff, squash merge, then verify `main` CI again.
