# P2 Baseline Predictor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a versioned, fail-safe Qwen2.5 model-only predictor that is fully CPU-testable and locally runnable against the existing model-path convention.

**Architecture:** Separate prompt formatting, shared result parsing, backend-independent prediction orchestration, and the lazy Transformers runtime backend. Prediction failures return explicit outcomes with `fallback_decision=review` instead of fabricating a risk category.

**Tech Stack:** Python 3.10+, Pydantic v2, unittest, optional local Torch/Transformers runtime.

## Global Constraints

- Prompt version is `baseline-prompt-v1`.
- Model version is `qwen2.5-1.5b-instruct-baseline-v1`.
- Policy version is `model-only-baseline-v1`.
- Never execute analyzed commands.
- ML dependencies remain lazy/optional in CPU-only CI.
- Any backend/parse failure must be explicit and fail-safe to `review` without inventing a category.
- Model-only baseline requires `rule_hits=[]`.

---

### Task 1: Versioned Baseline Prompt

**Files:**
- Create: `guard/baseline_prompt.py`
- Create: `tests/test_baseline_prompt.py`

**Interfaces:**
- `BASELINE_PROMPT_VERSION`, `BASELINE_MODEL_VERSION`, `BASELINE_POLICY_VERSION`.
- `BASELINE_SYSTEM_PROMPT`.
- `format_baseline_messages(request: GuardRequest) -> list[dict[str, str]]`.

- [ ] Write tests asserting exact version constants, complete GuardResult field/enumeration contract, untrusted-data warning, `rule_hits=[]`, Chinese summary constraint, and canonical JSON user content.
- [ ] Run tests and verify import/behavior RED.
- [ ] Implement constants and deterministic formatter.
- [ ] Run focused tests and verify GREEN.
- [ ] Commit.

### Task 2: Shared Result Parsing

**Files:**
- Create: `guard/result_parsing.py`
- Modify: `guard/adapter_smoke.py`
- Create: `tests/test_result_parsing.py`
- Modify: `tests/test_adapter_smoke.py` only if import ownership requires it.

**Interfaces:**
- `GeneratedResultError`.
- `extract_first_json_object(text: str) -> dict[str, object]`.
- `parse_guard_result(text, *, expected_model_version, expected_policy_version, require_empty_rule_hits=False) -> GuardResult`.

- [ ] Write tests for surrounding prose, braces inside strings, malformed leading braces, no object, exact GuardResult field set, wrong provenance, non-empty rule hits and valid output.
- [ ] Run and verify RED.
- [ ] Implement shared parser and make adapter smoke delegate to it while preserving `AdapterSmokeError` behavior.
- [ ] Run parser + adapter tests and verify GREEN.
- [ ] Commit.

### Task 3: Backend-independent Predictor

**Files:**
- Create: `guard/baseline_predictor.py`
- Create: `tests/test_baseline_predictor.py`

**Interfaces:**
- `GenerationResult(raw_text, elapsed_seconds, generated_tokens, peak_gpu_memory_mb=None)`.
- `GenerationBackend` protocol: `generate(messages, max_new_tokens) -> GenerationResult`.
- `PredictionStatus`: `ok`, `backend_error`, `parse_error`.
- `BaselinePredictionOutcome` fields: status, result, fallback_decision, error, raw_text, elapsed_seconds, generated_tokens, peak_gpu_memory_mb.
- `BaselinePredictor(backend, max_new_tokens=256).predict(request)`.

- [ ] Write fake-backend tests for valid prediction, backend exception, malformed JSON, wrong provenance, propagation of timing/token/memory metadata and prompt-injection-shaped request content.
- [ ] Run and verify RED.
- [ ] Implement minimal predictor; catch backend exceptions and parser errors; use `fallback_decision=review` only on failure.
- [ ] Run focused tests and verify GREEN.
- [ ] Commit.

### Task 4: Local Transformers/Qwen Backend

**Files:**
- Create: `guard/transformers_backend.py`
- Create: `tests/test_transformers_backend.py`

**Interfaces:**
- `TransformersBackendError`.
- `TransformersQwenBackend.from_local_model(model_path: Path | None = None, device="cuda:0")`.
- `.generate(messages, max_new_tokens) -> GenerationResult`.

- [ ] Write tests with fake Torch/Transformers modules for model-path resolution, missing model files, tokenizer pad fallback, local-only loading, BF16/device config, deterministic generation, decode-only-new-tokens and concise dependency/runtime errors.
- [ ] Run and verify RED.
- [ ] Implement lazy runtime loader and generation path without importing ML modules at module import time.
- [ ] Run focused tests and verify GREEN.
- [ ] Commit.

### Task 5: One-request CLI

**Files:**
- Create: `scripts/predict_baseline.py`
- Create: `tests/test_predict_baseline_cli.py`
- Modify: `README.md`
- Modify: `docs/work_plan.md`

**Interfaces:**
- `--request PATH`, `--model-path PATH`, `--max-new-tokens INT`.
- stdout is one JSON outcome.
- exit 0 ok, 1 prediction failure, 2 invalid input/setup.

- [ ] Write CLI tests for invalid request JSON/contract and argument validation without loading ML dependencies.
- [ ] Run and verify RED.
- [ ] Implement CLI, documentation and concise runtime errors.
- [ ] Run focused tests and verify GREEN.
- [ ] Commit.

### Task 6: Integration Gate

- [ ] Run `python -m unittest discover -s tests -v` through GitHub Actions Python 3.10 and 3.12.
- [ ] Confirm `python scripts/validate_eval_freeze.py` remains covered and green.
- [ ] Review PR changed files for accidental model weights or generated artifacts.
- [ ] Squash merge to `main` only after final-head CI succeeds.
- [ ] Verify merged `main` CI.
- [ ] Continue immediately with the separate P2 Evaluation Engine work package; defer user local/GPU action until predictor + evaluator are both ready.
