# P2 Baseline Evaluation Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evaluate the Model-only Qwen baseline over the resolved 100-sample Eval V1 technical freeze and produce a reproducible JSON quality/performance report without requiring GPU/model weights in CI.

**Architecture:** Extract technical-freeze resolution into a reusable library, then build a predictor-driven evaluation module that separates model classification metrics from fail-safe system decision metrics. A thin local CLI loads the Qwen backend once, runs all 100 samples, and atomically writes the ignored report artifact.

**Tech Stack:** Python 3.10+, Pydantic v2, stdlib statistics/math/time/platform/json, unittest, optional local Torch/Transformers runtime.

## Global Constraints

- Report version is `baseline-eval-report-v1`.
- Prompt/model/policy versions are fixed by the merged Baseline Predictor.
- Eval records must come from the resolved technical freeze, never pending raw Gold directly.
- No Eval command/code is ever executed.
- Individual prediction failures never abort the full evaluation loop.
- Classification metrics are valid-output model metrics and must always expose coverage.
- Effective decision metrics use `review` fallback for invalid outputs.
- No sklearn/numpy dependency is added.
- Reports are written under ignored `artifacts/` by default.

---

### Task 1: Reusable Eval Freeze Loader

**Files:**
- Create: `guard/eval_freeze.py`
- Modify: `scripts/validate_eval_freeze.py`
- Create: `tests/test_eval_freeze.py`
- Preserve: `tests/test_eval_freeze_cli.py`

**Interfaces:**
- `EvalFreezeValidationError`.
- `EvalFreezeBundle(records, manifest, substantive_disagreements, adjudication_counts)`.
- `load_freeze_manifest(path)`.
- `load_resolved_eval_v1(dataset_path=..., review_path=..., adjudication_path=..., blueprint_path=..., manifest_path=...) -> EvalFreezeBundle`.
- Export default repository paths from the library.

- [ ] Write failing library tests requiring 100 frozen records, 86 agreed, 14 adjudicated and manifest provenance.
- [ ] Run and verify RED.
- [ ] Move reusable loading/validation logic into `guard/eval_freeze.py` and delegate the existing CLI to it.
- [ ] Run focused + existing freeze CLI tests and verify GREEN.
- [ ] Commit.

### Task 2: Per-sample Evaluation Loop and Compliance Inspection

**Files:**
- Create: `guard/evaluation.py`
- Create: `tests/test_evaluation.py`

**Interfaces:**
- `BASELINE_EVAL_REPORT_VERSION = "baseline-eval-report-v1"`.
- `evaluate_baseline(records, predictor, *, freeze_version, max_new_tokens, environment=None) -> dict[str, object]`.
- `inspect_generated_output(outcome) -> compliance flags` internal helper.

- [ ] Write fake-predictor tests proving later samples still run after parse/backend failures and each sample records expected/predicted/fallback/runtime fields.
- [ ] Add tests distinguishing JSON-object, GuardResult-schema, Chinese-summary and strict-output compliance.
- [ ] Run and verify RED.
- [ ] Implement the minimal sequential evaluation loop and compliance inspection.
- [ ] Run focused tests and verify GREEN.
- [ ] Commit.

### Task 3: Risk, Category and Decision Metrics

**Files:**
- Modify: `guard/evaluation.py`
- Extend: `tests/test_evaluation.py`

**Interfaces:**
- Risk valid-only metrics: TP/TN/FP/FN, precision, recall, F1, FPR, FNR, coverage.
- Category metrics across all 12 categories: confusion matrix, support, valid coverage, recall, F1, Macro-F1.
- Decision metrics: model-valid accuracy, effective-all accuracy and fallback count.
- Safety metrics: critical and high-or-critical risky supports, allow misses and miss rates.

- [ ] Add exact failing metric fixtures with mixed valid/invalid outcomes.
- [ ] Run and verify RED.
- [ ] Implement zero-safe deterministic metric helpers.
- [ ] Run focused tests and verify GREEN.
- [ ] Commit.

### Task 4: Performance Metrics and Atomic Report Writer

**Files:**
- Modify: `guard/evaluation.py`
- Extend: `tests/test_evaluation.py`

**Interfaces:**
- Deterministic interpolated P50/P95 latency.
- Mean latency, summed tokens, tokens/second, max peak VRAM, evaluation wall seconds, samples/second.
- `write_evaluation_report(path: Path, report: dict[str, object])` using temp-file + replace.

- [ ] Add failing percentile/throughput/atomic-write tests.
- [ ] Run and verify RED.
- [ ] Implement helpers and writer.
- [ ] Run focused tests and verify GREEN.
- [ ] Commit.

### Task 5: Formal Evaluation CLI

**Files:**
- Create: `scripts/evaluate.py`
- Create: `tests/test_evaluate_cli.py`
- Modify: `README.md`
- Modify: `docs/work_plan.md`

**Interfaces:**
- `--model-path PATH` optional.
- `--max-new-tokens INT` default 256.
- `--output PATH` default `artifacts/baseline-eval-v1/report.json`.
- Exit 0 completed report, 1 fatal setup/write failure, 2 invalid CLI argument.
- Compact stdout summary includes output path, sample count, valid output rate, risk F1, category Macro-F1, effective decision accuracy, high-risk allow-miss rate and performance summary.

- [ ] Write CLI RED tests for nonpositive generation length and missing model path; verify freeze resolution happens before model loading through a corrupted custom freeze fixture where useful.
- [ ] Run and verify RED.
- [ ] Implement CLI environment metadata, single backend load, predictor construction, full evaluation and atomic report write.
- [ ] Update docs with exact local formal-run commands.
- [ ] Run focused tests and verify GREEN.
- [ ] Commit.

### Task 6: Integration Gate

- [ ] Run final-head GitHub Actions on Python 3.10 and 3.12.
- [ ] Confirm existing `scripts/validate_eval_freeze.py` regressions remain green.
- [ ] Review PR changed files; no `artifacts/`, model weights, private data or generated report may be committed.
- [ ] Squash merge to `main` only after final-head CI succeeds.
- [ ] Verify merged `main` CI.
- [ ] Then request one local target-GPU validation cycle: pull main, validate environment/freeze, run full 100-sample baseline, return report/output.
