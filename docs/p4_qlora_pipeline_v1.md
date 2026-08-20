# P4 Training Data Quality Gate V1

## Goal

Define the CPU-only contract and acceptance gate for the future 5k–10k P4
training corpus while keeping Eval V1 frozen.

## Dataset isolation

- Train and validation are separate JSONL inputs.
- IDs, canonical requests, and semantic templates must be disjoint.
- Any `EV###` marker or Eval/Gold provenance fails validation.
- Exact request matches against frozen Eval V1 fail validation.
- Eval labels are never used to construct a training row.

## Training target

Each row contains:

- stable `TR-######` ID;
- instruction;
- production `GuardRequest` under `input`;
- complete production `GuardResult` V1 under `output`;
- data version, generation source, semantic template, and split provenance.

Nested request/result validation reuses the production Pydantic contracts.
Additional consistency rules prevent benign-risk and non-benign-allow label
contradictions, require high/critical severity for `block`, enforce Chinese
summaries, and reject coerced risk/confidence scalar types.

## Run the gate

```bash
python scripts/check_training_dataset.py \
  --train data/train/agent_security_train_v1.jsonl \
  --validation data/val/agent_security_validation_v1.jsonl
```

The command prints deterministic JSON. `status=ok` exits 0; malformed rows,
split overlap, contamination, or Eval request leakage exits 1 without a
traceback.

## Non-goals of this PR

- It does not generate or commit the formal P4 corpus.
- It does not load Qwen2.5, Torch, Transformers, PEFT, or bitsandbytes.
- It does not run QLoRA or write adapters/checkpoints.
- It does not replace the existing 6GB engineering smoke pipeline.

## Acceptance targets

After the formal corpus is produced and passes this gate, P5 training remains
subject to the existing quality targets: valid output rate above 95%, repair
rate below 10%, zero high-risk allow misses, and improved category macro F1.
