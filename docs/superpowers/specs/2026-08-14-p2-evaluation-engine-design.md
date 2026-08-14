# P2 Baseline Evaluation Engine Design

## Goal

Evaluate the Qwen2.5-1.5B-Instruct Model-only Baseline against the resolved Eval V1 technical freeze, producing a reproducible per-sample JSON report with model-quality, fail-safe decision, output-compliance, latency, token-throughput and GPU-memory metrics.

## Scope

This work package includes:

- a reusable library loader for the resolved Eval V1 technical freeze;
- a CPU-testable evaluation engine driven by a predictor protocol;
- deterministic metric computation without adding sklearn/numpy dependencies;
- a local `scripts/evaluate.py` entry point that loads the Qwen backend once and evaluates all 100 samples;
- atomic JSON report writing under the already ignored `artifacts/` tree;
- CPU-only unit/CLI tests.

It does not run the real model in GitHub Actions. Target RTX 1000 Ada 6GB execution is the local P2.3 acceptance step after this PR merges.

## Versions

- Report version: `baseline-eval-report-v1`
- Prompt version: `baseline-prompt-v1`
- Model version: `qwen2.5-1.5b-instruct-baseline-v1`
- Policy version: `model-only-baseline-v1`
- Eval freeze version comes from `data/eval-v1/freeze-manifest.json` and is currently `eval-v1-agent-reviewed-rc1`.

## 1. Resolved Eval V1 library boundary

Move the reusable technical-freeze loading/validation flow out of `scripts/validate_eval_freeze.py` into `guard/eval_freeze.py`.

`load_resolved_eval_v1(...) -> EvalFreezeBundle` must:

- load raw Gold Draft, independent review, adjudication ledger, blueprint and freeze manifest;
- enforce the existing manifest provenance rules, especially `reviewer_type=independent-agent` and `human_reviewed=false`;
- resolve Gold + review + adjudication in memory;
- require exactly 100 frozen records;
- validate Blueprint identity and adjudicated category corrections;
- expose resolved records, manifest, substantive disagreement count and adjudication counts.

`validate_eval_freeze.py` becomes a thin CLI adapter over this library. Existing output semantics and tests must remain green.

The evaluator must never use pending raw Gold directly as final labels.

## 2. Evaluation input and per-sample result

`guard/evaluation.py` consumes:

- a sequence of resolved `EvalGoldRecord` objects;
- any predictor exposing `predict(GuardRequest) -> BaselinePredictionOutcome`;
- fixed version/provenance metadata;
- optional environment metadata supplied by the CLI.

For each sample it records:

- `sample_id`;
- expected `risk`, `decision`, `severity`, `category`;
- predictor status;
- predicted GuardResult when valid;
- fallback/effective decision;
- concise error when invalid;
- raw generated text when available;
- elapsed generation seconds, generated token count and peak GPU memory when available;
- correctness flags for risk/category/model decision/effective decision;
- whether a high/critical-risk sample was incorrectly allowed.

No command from the Eval dataset is ever executed.

## 3. Model-output coverage and compliance

A model failure is not silently converted into a classification label.

Report these separately:

- `status_counts`: `ok`, `parse_error`, `backend_error`;
- `valid_output_rate`: `status=ok / total`;
- `json_object_rate`: generated text contains a decodable JSON object;
- `guardresult_schema_rate`: generated JSON has the exact GuardResult field set and passes GuardResult schema, regardless of Baseline provenance/rule-hit policy;
- `summary_compliance_rate`: extracted JSON contains a nonblank 1–30 character summary with at least one CJK Unified Ideograph;
- `strict_output_rate`: generated output passes the full Baseline contract, equivalent to `status=ok`.

This distinction makes it possible to diagnose “valid JSON but wrong schema/provenance” separately from total generation failure.

## 4. Risk classification metrics

Risk classification metrics are computed only over schema-valid strict model outputs, because invalid outputs are abstentions/failures rather than `risk=false` predictions.

Report:

- evaluated/valid count and coverage;
- TP/TN/FP/FN;
- precision;
- recall;
- F1;
- false-positive rate;
- false-negative rate.

The report must always display coverage next to these valid-only metrics so output failures cannot be hidden.

## 5. Category metrics

Category metrics are also model-quality metrics over valid outputs only.

For all 12 RiskCategory values report:

- confusion matrix `gold_category -> predicted_category -> count`;
- per-category recall;
- per-category support in the full Eval freeze;
- per-category valid coverage;
- per-category F1;
- Macro-F1 across all 12 categories.

A category with no valid prediction still receives F1/recall 0 where its full-gold support is nonzero. Invalid outputs reduce category coverage and remain visible in status/compliance metrics rather than being invented as another category.

## 6. Decision and safety metrics

Two decision views are required:

1. `model_decision_accuracy_valid`: exact decision accuracy on valid model outputs only.
2. `effective_decision_accuracy_all`: accuracy over all samples where invalid model outputs use the Predictor fail-safe `fallback_decision=review`.

Also report:

- fallback count;
- gold critical support;
- critical `allow` misses and miss rate;
- gold high-or-critical risky support;
- high-or-critical `allow` misses and miss rate.

An invalid output falls back to `review`; therefore it is a generation/coverage failure but not an unsafe `allow` miss.

## 7. Performance metrics

Using outcomes that contain generation timing:

- latency sample count;
- mean latency;
- P50 latency;
- P95 latency;
- total generated tokens;
- aggregate generated tokens/second = total tokens / summed generation seconds;
- maximum reported peak GPU memory MB.

Across the complete evaluation loop also report wall-clock seconds and samples/second.

Percentiles use deterministic linear interpolation over sorted observed latencies. Missing runtime metrics do not abort evaluation.

## 8. Report structure and reproducibility

Top-level report includes:

- `report_version`;
- prompt/model/policy versions;
- freeze version and `human_reviewed` provenance;
- `max_new_tokens`;
- environment metadata;
- total samples;
- status/compliance metrics;
- risk/category/decision/safety/performance metrics;
- `samples` list with all 100 per-sample records.

The report writer uses temp-file + atomic replace and sorted/indented UTF-8 JSON.

`artifacts/` is already Git-ignored, so the formal local report defaults to:

`artifacts/baseline-eval-v1/report.json`

## 9. CLI

`scripts/evaluate.py` accepts:

- optional `--model-path` using the existing environment/default convention;
- `--max-new-tokens` default 256;
- `--output` default `artifacts/baseline-eval-v1/report.json`.

Execution order:

1. resolve and validate Eval V1 technical freeze before loading the model;
2. load the local Qwen backend once;
3. construct one `BaselinePredictor`;
4. evaluate all 100 requests sequentially;
5. write the report atomically;
6. print a compact JSON summary with report path and key metrics.

Exit codes:

- `0`: evaluation loop completed and report was written, even if individual samples had parse/backend prediction failures;
- `1`: fatal setup/runtime failure preventing the evaluation run (freeze load, model load, report write);
- `2`: invalid CLI argument.

Individual prediction failures must never terminate the full 100-sample loop.

## 10. Environment metadata

The local CLI records non-secret reproducibility metadata:

- Python version;
- platform string;
- resolved model path;
- device (`cuda:0`);
- Torch version;
- Transformers version;
- CUDA device name when available;
- CUDA total memory MB when available.

No model weights, environment variables, secrets, private paths beyond the explicit model path, or arbitrary system environment are serialized.

## 11. Testing

CPU-only tests use fake predictors/outcomes and cover:

- resolved technical-freeze library returns 100 frozen records and preserves validator CLI behavior;
- evaluator continues after parse/backend failures;
- risk TP/TN/FP/FN and precision/recall/F1/FPR/FNR;
- category confusion, recall, F1, Macro-F1 and coverage;
- model-valid versus effective fail-safe decision accuracy;
- critical/high-risk allow-miss semantics;
- JSON/schema/Chinese-summary compliance distinctions;
- deterministic P50/P95/token throughput/peak memory;
- atomic report writing;
- CLI rejects nonpositive generation length before loading the model;
- CLI reports missing model/freeze setup failures without tracebacks.

## Acceptance

Before merge:

- complete CPU-only suite passes on Python 3.10 and 3.12;
- existing technical-freeze validator remains green;
- evaluator test proves one invalid sample does not abort later samples;
- report contract contains all required P2 metrics and version provenance;
- no generated reports or model weights are committed.

After merge, the next required step is the real local RTX 1000 Ada 6GB Baseline run over all 100 frozen samples.
