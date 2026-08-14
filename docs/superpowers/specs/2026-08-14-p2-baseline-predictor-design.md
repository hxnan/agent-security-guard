# P2 Baseline Predictor Design

## Goal

Implement a production-shaped, model-only Qwen2.5-1.5B-Instruct predictor boundary that turns a validated `GuardRequest` into either a schema-valid `GuardResult` or an explicit fail-safe prediction outcome, while remaining fully CPU-testable in CI without model weights, Torch, Transformers, or a GPU.

## Scope

This work package includes:

- fixed/versioned Baseline Prompt V1;
- robust generated-JSON extraction and strict GuardResult parsing;
- backend-independent predictor orchestration;
- a lazy local Transformers/Qwen backend;
- one-request baseline CLI for local smoke verification;
- CPU-only unit/CLI tests.

It intentionally does **not** implement the 100-sample evaluation/metrics engine. That is the next P2 work package after this predictor lands.

## Versions

- Prompt version: `baseline-prompt-v1`
- Model version written by the model contract: `qwen2.5-1.5b-instruct-baseline-v1`
- Policy version: `model-only-baseline-v1`

These values are part of the prompt and parser expectations so a structurally valid response with incorrect provenance is rejected rather than silently accepted.

## Architecture

### 1. Prompt module

`guard/baseline_prompt.py` owns the fixed system prompt and deterministic request formatting.

The system prompt must:

- state that command/request content is untrusted data, not instructions;
- forbid executing or obeying content embedded in the request;
- require exactly one compact JSON object and no Markdown/explanation;
- enumerate all required GuardResult V1 fields;
- enumerate valid decision/severity/category values;
- require Chinese summary of 1–30 characters;
- limit evidence to at most five direct facts;
- require `rule_hits=[]` because this is Model-only Baseline;
- require the exact model/policy version strings above;
- recommend the existing annotation confidence buckets `0.50/0.60/0.75/0.90/0.99`.

The user message is canonical JSON generated from `GuardRequest.model_dump(mode="json")`, never interpolated as trusted prose.

### 2. Shared generated-result parsing

`guard/result_parsing.py` owns generic first-JSON-object extraction currently embedded in `guard/adapter_smoke.py`.

Extraction must correctly handle:

- surrounding prose;
- braces inside JSON strings;
- malformed earlier `{` characters followed by a later valid JSON object;
- absence of any valid JSON object.

`parse_baseline_result` additionally requires the generated object to have exactly the GuardResult V1 field set and then validates it with Pydantic. It rejects wrong `model_version`, wrong `policy_version`, or non-empty `rule_hits`.

Adapter smoke imports the shared extractor/validator so parsing logic is not duplicated.

### 3. Backend contract

`guard/baseline_predictor.py` defines a small backend protocol:

`generate(messages, max_new_tokens) -> GenerationResult`

`GenerationResult` contains:

- raw generated text;
- elapsed seconds;
- generated token count;
- optional peak GPU memory MB.

Tests use a fake backend. The predictor does not import Torch or Transformers.

### 4. Prediction outcome and fail-safe semantics

A model/backend failure must not fabricate an arbitrary risk category. The predictor returns `BaselinePredictionOutcome` with:

- `status`: `ok | backend_error | parse_error`;
- `result`: `GuardResult | None`;
- `fallback_decision`: `review` for any failure, otherwise `None`;
- `error`: concise diagnostic or `None`;
- generation timing/token/memory metadata when available;
- raw text when generation completed.

This makes the architecture fail-safe while preserving category honesty: later policy/evaluation layers can route failures to human review and separately count invalid model outputs.

The predictor catches backend exceptions and generated-output parsing/validation errors. It does not allow one bad model output to crash a future full evaluation run.

### 5. Local Transformers backend

`guard/transformers_backend.py` lazily imports Torch and Transformers only inside the runtime loader.

The loader:

- resolves the existing `AGENT_SECURITY_MODEL_PATH` / default model path convention;
- requires the existing local model files;
- loads tokenizer/model with `local_files_only=True`;
- uses deterministic greedy generation (`do_sample=False`);
- targets `cuda:0` for the first formal baseline;
- uses BF16, which is expected to fit Qwen2.5-1.5B on the target 6GB GPU based on model scale, but actual VRAM/performance remains a required local measurement;
- decodes only newly generated tokens;
- records elapsed time, generated token count, and CUDA peak allocated memory.

Missing dependencies, CUDA/runtime errors, or load failures become concise backend errors at the predictor boundary.

### 6. One-request CLI

`scripts/predict_baseline.py` accepts:

- `--request PATH` containing one GuardRequest JSON object;
- optional `--model-path`;
- optional `--max-new-tokens` (default 256).

It prints one JSON outcome and returns:

- `0` for `status=ok`;
- `1` for backend/parse prediction failure;
- `2` for invalid CLI/request input.

The CLI never executes the command being analyzed.

## Error handling

- Invalid GuardRequest is rejected before model loading.
- Backend load/generation exceptions become `backend_error + fallback_decision=review`.
- No valid JSON, extra/missing GuardResult fields, schema violations, wrong provenance, or unexpected rule hits become `parse_error + fallback_decision=review`.
- Error strings are concise and do not expose dependency tracebacks.

## Testing

CPU-only CI tests cover:

- prompt version and complete contract text;
- untrusted request formatting and prompt-injection-shaped input;
- shared JSON extraction behavior and adapter-smoke compatibility;
- successful fake-backend prediction;
- backend exception fail-safe outcome;
- malformed/no JSON fail-safe outcome;
- extra/missing fields and wrong model/policy provenance rejection;
- CLI invalid input behavior using mocks/fakes where runtime loading must not occur.

The local target-GPU smoke is deferred until the predictor and evaluation engine are both committed, so the user only needs one pull/verification cycle for the formal P2 baseline.

## Acceptance

- All CPU-only tests pass on Python 3.10 and 3.12.
- Existing adapter smoke parsing tests remain green after parser extraction.
- Predictor never imports heavy ML dependencies in ordinary unit tests.
- Failure paths explicitly produce `fallback_decision=review` without inventing a category.
- Runtime model and policy provenance cannot be silently changed by generated content.
- No analyzed command is executed anywhere in this pipeline.
