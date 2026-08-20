# P4 Training Data Quality Gate V1

## Goal

Define the CPU-only contract, deterministic first 1,000-row seed, and
acceptance gate for the future 5k–10k P4 training corpus while keeping Eval V1
frozen.

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
- data version, generation source, semantic template, split, scenario kind,
  batch ID, and generator-version provenance.

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

## Generate P4 Seed V1

```bash
python scripts/prepare_training_data.py --force
```

The generator expands 100 curated semantic clusters into 1,000 strict rows:
800 train and 200 validation. Each cluster owns ten variants and exactly one
split. Ten fixed batch IDs own 100 rows each. The category profile contains
300 benign rows, 80 remote-execution rows, 80 unsafe-download rows, and 60 rows
for every other non-benign category.

Committed outputs:

- `data/train/agent_security_train_v1.jsonl`;
- `data/val/agent_security_validation_v1.jsonl`;
- `data/train/agent_security_seed_v1_manifest.json`.

Regeneration is byte deterministic. The manifest records exact distributions
and SHA-256 hashes. Generation never reads Eval; the frozen request set is
loaded only after expansion to reject exact leakage.

## Remaining non-goals

- It does not load Qwen2.5, Torch, Transformers, PEFT, or bitsandbytes.
- It does not run QLoRA or write adapters/checkpoints.
- It does not replace the existing 6GB engineering smoke pipeline.

## Acceptance targets

P4 Seed V1 is the first committed batch, not the final 5k–10k corpus. P5
training remains subject to the existing quality targets: valid output rate
above 95%, repair rate below 10%, zero high-risk allow misses, and improved
category macro F1.
