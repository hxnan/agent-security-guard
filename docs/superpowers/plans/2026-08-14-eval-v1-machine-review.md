# Eval V1 Machine Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct factual/semantic defects found during a second machine review of Eval V1 Draft and add a blind-review workflow that lets an independent human reviewer annotate without seeing the primary Gold labels.

**Architecture:** Keep `GuardRequest`, `GuardResult`, and `EvalGoldRecord` unchanged. Add a small evaluation-only review module that exports request-only blind packets and compares completed reviewer answers with the committed Gold labels. Dataset corrections remain `llm-assisted-draft + pending`; no machine action may mark a row `agreed`, `adjudicated`, or frozen.

**Tech Stack:** Python 3.10+, Pydantic v2, standard-library `json`/`pathlib`, `unittest`.

## Global Constraints

- Never execute a command contained in Eval V1.
- Never expose `expected`, `planned_category`, `scenario_kind`, primary annotation status, or override reasons in a blind review packet.
- Never change `review_status` from `pending` as part of machine review.
- Preserve EV001–EV100 IDs and all Blueprint quotas.
- Corrections may fix request/context/summary/evidence when they better realize the already-approved Blueprint scenario; category changes require a separate governance decision and are out of scope.

---

### Task 1: Blind review contract

**Files:**
- Create: `tests/test_eval_review.py`
- Create: `guard/eval_review.py`

**Interfaces:**
- Consumes: `Sequence[EvalGoldRecord]`.
- Produces: `EvalBlindReviewRecord`, `EvalReviewAnswer`, `EvalReviewComparison`, `build_blind_review_packet(records)`, `compare_review_answers(records, answers)`.

- [ ] **Step 1: Write failing tests** proving blind packets contain only `sample_id` and `request`, reviewer answers require decision/severity/category/summary/confidence/evidence, and comparison reports only differing core fields.
- [ ] **Step 2: Run** `python -m unittest tests.test_eval_review -v` and confirm RED because `guard.eval_review` does not exist.
- [ ] **Step 3: Implement the minimal Pydantic models and comparison functions.**
- [ ] **Step 4: Re-run** `python -m unittest tests.test_eval_review -v` and confirm GREEN.

### Task 2: Blind-review CLI

**Files:**
- Create: `scripts/export_eval_review_packet.py`
- Create: `scripts/compare_eval_review.py`
- Create: `tests/test_eval_review_cli.py`

**Interfaces:**
- Export: `python scripts/export_eval_review_packet.py [--dataset PATH] [--output PATH]`.
- Compare: `python scripts/compare_eval_review.py --answers PATH [--dataset PATH]`.

- [ ] **Step 1: Add failing CLI tests** for default dataset discovery, output that excludes Gold labels, and non-zero comparison result when reviewer answers disagree.
- [ ] **Step 2: Run targeted tests and confirm RED.**
- [ ] **Step 3: Implement thin CLIs around `guard.eval_review`; JSONL only, no model or GPU dependencies.**
- [ ] **Step 4: Run targeted tests and confirm GREEN.**

### Task 3: Correct machine-review findings

**Files:**
- Modify: `data/eval-v1/gold/030-shell-ev021-030.jsonl`
- Modify: `data/eval-v1/gold/050-powershell-ev041-050.jsonl`
- Modify: `data/eval-v1/gold/060-cmd-ev051-060.jsonl`
- Modify: `data/eval-v1/gold/090-python-ev081-090.jsonl`
- Modify: `data/eval-v1/gold/100-mixed-ev091-100.jsonl`
- Create: `tests/test_eval_dataset_quality.py`

**Interfaces:** committed Eval V1 Draft remains the single dataset source.

- [ ] **Step 1: Add failing regression assertions** for EV026 verified-download summary, EV044 Defender summary, EV058 explicit elevation, EV084 setuid context, EV087 executable privilege context, and EV099 explicit firewall-script behavior context.
- [ ] **Step 2: Run targeted tests and confirm RED against the current Draft.**
- [ ] **Step 3: Make the minimum data corrections without changing IDs/categories/quotas/review status.**
- [ ] **Step 4: Run** `python scripts/validate_eval_dataset.py --require-complete` and the targeted tests; confirm GREEN.

### Task 4: Review report and documentation

**Files:**
- Create: `docs/eval_v1_machine_review_2026-08-14.md`
- Modify: `README.md`
- Modify: `docs/work_plan.md`

- [ ] **Step 1: Record the 100-row second-pass scope, exact corrected sample IDs, and the limitation that this is not independent human review.**
- [ ] **Step 2: Document blind-review export/compare commands and the remaining human freeze gate.**
- [ ] **Step 3: Keep P1 status open; do not mark Eval V1 frozen.**

### Task 5: Verification and publish

**Files:** all changed files.

- [ ] **Step 1: Run the full unit suite and complete Draft validation.**
- [ ] **Step 2: Verify `--require-frozen` still fails because rows remain pending.**
- [ ] **Step 3: Open a PR, confirm GitHub Actions success, review the diff, squash-merge to `main`, and confirm post-merge CI success.**
