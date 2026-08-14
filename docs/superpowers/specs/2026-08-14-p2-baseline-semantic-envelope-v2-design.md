# P2 Baseline Semantic Envelope V2 Design

## Status

Approved direction: model-facing semantic core plus system-owned GuardResult envelope.

## Problem

The first formal Qwen2.5-1.5B-Instruct Baseline run completed all 100 Eval V1 samples on the target RTX 1000 Ada 6GB GPU, but every sample ended as `parse_error`.

Offline diagnostics showed:

- 99/100 generations contained a valid JSON object;
- 100/100 generations used Markdown code fences;
- 99/99 JSON objects omitted `model_version` and `policy_version`;
- 99/99 emitted `risk` as a string severity-like label rather than a boolean;
- 99/99 emitted `confidence` as a string;
- `risk` string values were `none/low/medium/high/critical`, showing a systematic semantic collision rather than random noise;
- injecting only provenance recovered 0/99 records because the remaining model-facing object was still not a valid GuardResult.

The root cause is therefore not GPU/runtime failure. The current model-facing schema asks a 1.5B model to generate redundant system-owned fields and a `risk` boolean whose name is naturally interpreted as risk severity. The strict full-GuardResult parser then discards otherwise useful semantic predictions when any one of those fields is malformed.

## Goals

1. Make the model responsible only for security judgments it actually needs to infer.
2. Keep the final public `GuardResult` V1 contract unchanged.
3. Preserve fail-safe behavior: malformed or contradictory model semantics must still become `parse_error + fallback_decision=review`.
4. Never infer, repair, or overwrite a model's category/decision/severity to improve metrics.
5. Keep the runtime local, deterministic, dependency-light, and CPU-testable.
6. Preserve reproducibility and clear provenance between Baseline V1 and V2.

## Non-goals

- Do not change Eval V1 Gold/freeze/adjudication data.
- Do not introduce grammar-constrained decoding or third-party JSON generation libraries.
- Do not silently truncate summaries or evidence.
- Do not snap model confidence to Gold annotation confidence buckets.
- Do not auto-correct contradictory security labels.
- Do not claim the old Baseline V1 report is comparable as a valid quality baseline; it remains a formatting-failure diagnostic run.

## Versioning

Baseline V2 changes the prompt and model-only policy, but not the underlying model weights.

Use:

```text
prompt_version = baseline-prompt-v2
model_version  = qwen2.5-1.5b-instruct-baseline-v1
policy_version = model-only-baseline-v2
report_version = baseline-eval-report-v2
```

Rationale:

- `model_version` remains unchanged because the same local Qwen2.5-1.5B-Instruct weights/backend are used;
- `prompt_version` changes because the model-facing contract changes;
- `policy_version` changes because the system now derives/injects final GuardResult fields;
- `report_version` changes because output-compliance metric semantics change.

The formal V2 report default path becomes:

```text
artifacts/baseline-eval-v2/report.json
```

so the V1 diagnostic report is not overwritten.

## Architecture

### 1. Model-facing semantic object

The model must return exactly these six fields:

```json
{
  "decision": "allow|review|block",
  "severity": "none|low|medium|high|critical",
  "category": "...RiskCategory...",
  "summary": "中文摘要",
  "confidence": 0.99,
  "evidence": ["直接证据"]
}
```

The model must not generate:

- `schema_version`
- `risk`
- `rule_hits`
- `model_version`
- `policy_version`

This removes redundant/provenance fields and eliminates the ambiguous `risk` name from the model-facing schema.

### 2. Lossless normalization

The parser may perform only representation-level normalization that does not change security meaning.

Allowed:

- extract the first JSON object from surrounding text/code fences;
- convert a numeric confidence string such as `"0.99"` or `"0.85"` to the corresponding float;
- preserve all category/decision/severity/summary/evidence values exactly.

Rejected rather than repaired:

- unknown category/decision/severity;
- non-numeric confidence strings;
- confidence outside `[0, 1]`;
- summary longer than 30 characters;
- summary without Chinese characters;
- evidence not a list of strings or more than 5 entries;
- missing or extra model-facing fields;
- any semantic contradiction described below.

No conversion may map a severity-like token to `risk`, change a category, downgrade/upgrade severity, choose a decision, truncate text, or rewrite evidence.

### 3. Semantic consistency gate

Before constructing the final GuardResult, the semantic object must satisfy project invariants.

For `category=benign`:

```text
decision = allow
severity = none
```

For any non-benign category:

```text
decision in {review, block}
severity in {low, medium, high, critical}
```

Additionally:

```text
block is valid only with severity in {high, critical}
```

`critical + review` remains valid because the annotation guideline allows high-impact but context-uncertain cases.

Category default severity/decision from the taxonomy is not enforced here because Eval V1 contains legitimate boundary overrides.

### 4. System-owned GuardResult envelope

After the semantic object passes validation, the system constructs the final `GuardResult`:

```text
schema_version = "1.0"
risk = (category != benign)
rule_hits = []
model_version = qwen2.5-1.5b-instruct-baseline-v1
policy_version = model-only-baseline-v2
```

The six model-generated semantic fields are copied unchanged except for allowed confidence string-to-float normalization.

The resulting object is validated again through the normal `GuardResult` Pydantic contract.

This is not label repair: every injected/derived field is either immutable runtime provenance or a deterministic redundant representation of `category`.

### 5. Failure behavior

Any backend exception remains:

```text
status = backend_error
fallback_decision = review
```

Any extraction, model-facing schema, normalization, semantic consistency, or final GuardResult failure remains:

```text
status = parse_error
fallback_decision = review
```

No category is invented on failure.

### 6. Code boundaries

Create a focused `guard/baseline_output.py` module responsible for:

- the model-facing semantic Pydantic model;
- extraction + allowed confidence normalization;
- semantic consistency validation;
- deterministic construction of the final GuardResult envelope.

Keep `guard/result_parsing.py` unchanged as the generic strict full-GuardResult parser used by Adapter smoke and other callers. Baseline V2 must not weaken that shared parser.

Update `guard/baseline_predictor.py` to call the new Baseline V2 semantic parser/enveloper.

Update `guard/baseline_prompt.py` to ask for exactly six semantic fields and remove the ambiguous/system-owned fields from the requested output.

### 7. Evaluation compliance semantics

Baseline Eval Report V2 distinguishes raw model-output compliance from final system contract compliance.

Report these rates:

- `json_object_rate`: raw generation contains a JSON object;
- `semantic_schema_rate`: extracted object passes the six-field model-facing schema and representation normalization;
- `semantic_consistency_rate`: semantic object also passes label consistency rules;
- `guardresult_schema_rate`: system-enveloped final result validates as GuardResult V1;
- `summary_compliance_rate`: raw semantic summary satisfies Chinese/length rules;
- `strict_output_rate` / `valid_output_rate`: predictor returns `status=ok`.

The final quality metrics continue to use only `status=ok` predictions. Failed predictions still use `review` only for fail-safe system-level decision metrics.

## Prompt V2

The system prompt must:

1. keep the existing instruction that user command/code/context is untrusted data;
2. explicitly say `risk`, provenance, `schema_version`, and `rule_hits` are system-managed and must not be emitted;
3. provide the exact six-field JSON shape;
4. state field types explicitly, especially:
   - `confidence` is a JSON number, not a quoted string;
   - `evidence` is an array of strings;
5. keep category/decision/severity enum lists;
6. keep Chinese summary length 1-30 characters;
7. request no Markdown/code fence, while the extractor remains tolerant of surrounding fences.

## Testing Strategy

All behavior is developed with RED -> GREEN TDD.

Required regression coverage:

1. V2 semantic parser accepts a valid six-field object.
2. Quoted numeric confidence is converted losslessly to float.
3. Numeric confidence values such as `0.85` and `0.95` are accepted; they are not snapped to Gold annotation buckets.
4. Markdown code fences do not prevent extraction.
5. Missing/extra semantic fields fail.
6. Unknown enums fail.
7. Non-Chinese or >30-character summaries fail.
8. Benign + review/block fails.
9. Benign + non-none severity fails.
10. Non-benign + allow fails.
11. Block + low/medium fails.
12. Final envelope derives `risk` only from `category` and injects exact provenance/rule hits.
13. Predictor returns `parse_error + review` for contradictions and `ok` for valid V2 output.
14. Shared `parse_guard_result()` remains strict and all Adapter smoke regression tests stay green.
15. Evaluation report V2 exposes the new compliance rates and V2 provenance.
16. `scripts/evaluate.py` defaults to `artifacts/baseline-eval-v2/report.json`.

## Local Validation Sequence

After CPU/CI implementation merges to `main`, do not immediately spend another full 100-sample run.

First run one benign and one risky request through `scripts/predict_baseline.py` on the target GPU. Both must return `status=ok` with a complete system-enveloped GuardResult.

Only after the two-sample probe succeeds, run the formal 100-sample evaluation:

```bash
python scripts/evaluate.py \
  --output artifacts/baseline-eval-v2/report.json
```

The V2 acceptance target for the first rerun is primarily structural:

- `valid_output_rate` must be materially above zero and should approach 1.0;
- any remaining parse failures must be explicitly attributable;
- quality metrics are considered meaningful only once output coverage is sufficiently high;
- performance/VRAM must remain within the target 6GB GPU envelope.

No quality threshold is pre-selected before observing the real V2 baseline; P3 priorities will be driven by the measured error distribution.

## Security and Governance

- Eval V1 technical freeze is immutable for this change.
- No sample command is executed; all inference remains static analysis.
- System-derived `risk` is deterministic from the model-selected category and therefore auditable.
- System-injected provenance cannot be overridden by model output because those fields are not part of the model-facing object.
- Contradictory semantic labels fail closed to `review` rather than being normalized into an apparently valid prediction.
- Baseline V1 and V2 remain distinguishable through prompt/policy/report versions and separate report paths.
