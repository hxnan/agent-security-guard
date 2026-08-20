# P4 Training Data Quality Gate Design

## Scope

This work establishes the CPU-only contract and acceptance gate for future P4
training data. It does not generate the planned 5k–10k corpus, load model
weights, train an adapter, or modify the frozen Eval V1 bundle.

## Record contract

Every JSONL row contains:

- a stable `TR-######` ID;
- an instruction;
- a `GuardRequest` under `input`;
- a complete public `GuardResult` V1 under `output`;
- metadata with `data_version`, `generation_source`, `semantic_template`, and
  literal `train` or `validation` split provenance.

The nested request/result reuse the production Pydantic contracts. Benign rows
must be `risk=false`, `allow`, and severity `none`. Non-benign rows must be
`risk=true`, must not `allow`, and must not use severity `none`.
`block` requires severity `high` or `critical`. Summaries must contain Chinese
characters without surrounding whitespace, matching the Baseline V2 semantic
contract. Boolean and confidence JSON scalar types are validated without
Pydantic coercion.

## Isolation gates

The checker receives separate train and validation JSONL files. It fails when:

- either file has malformed JSON, schema-invalid rows, duplicate IDs, or a row
  whose metadata split disagrees with its file;
- IDs, exact canonical requests, or semantic templates overlap across splits;
- any row contains an `EV###` identifier or explicit Eval/Gold provenance;
- any training or validation request exactly matches a frozen Eval V1 request.

Eval V1 Gold JSONL is read only to extract each row's `request` and compute
fingerprints for leakage detection. Its labels are never validated as training
labels, loaded into a training example, or copied to generated data.

## Output and compatibility

The CLI prints one deterministic JSON object containing status, per-split row
counts, category distributions, and sorted errors. Success exits 0; any parse,
contract, overlap, or contamination failure exits 1 without a traceback.

The implementation uses Python 3.10+, Pydantic already required by the project,
and `unittest`. No ML dependency, model directory, GPU, or pytest is required.
