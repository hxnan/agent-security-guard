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

## P4 Seed QLoRA Pilot

The deterministic data generator remains CPU-only. A separate pilot consumes
the committed 800/200 files only after strict parsing, exact profile validation,
Eval request leakage checks, and SHA-256 comparison against the manifest.

```bash
python scripts/train_p4_seed_qlora.py --preflight-only
python scripts/train_p4_seed_qlora.py --overwrite-output
python scripts/smoke_test_p4_adapter.py
```

The fixed 6GB defaults are maximum length 512, micro batch 1, gradient
accumulation 16, two epochs, learning rate `1e-4`, all-linear LoRA, 4-bit NF4
double quantization, BF16 compute, and gradient checkpointing. Validation and
checkpoint selection run each epoch. At most one best eval-loss checkpoint is
retained.

The committed records keep complete GuardResult V1 labels, while the assistant
training target contains exactly the six Baseline/Fusion V2.1 semantic fields.
The model does not learn system-owned `schema_version`, `risk`, `rule_hits`,
`model_version`, or `policy_version`; the existing envelope reconstructs them.

The pilot writes ignored local artifacts under
`artifacts/p4-seed-qlora-pilot-v1/`. Its manifest records exact dataset hashes,
training prompt version, base model, the complete effective quantization/LoRA/
optimizer/checkpoint contract, counts, trainable parameters, and SHA-256 values
for every adapter-directory inference asset, including tokenizer files. The
smoke probe rejects substituted files, unexpected PEFT behavior switches, or
provenance drift before loading the model. It must remain
`quality_milestone=false`; no pilot adapter is a P5 release candidate until
frozen Eval V1 comparison is complete.

Expected dependency, local-model, runtime, and CUDA OOM failures return one
concise JSON result without a traceback. The OOM result includes the supported
256-token/attention-only retry command.

The existing smoke pipeline remains independent and backward compatible.

## Acceptance targets

P4 Seed V1 is the first committed batch, not the final 5k–10k corpus. The pilot
tests whether its data and training design are directionally useful before
targeted expansion. P5 remains subject to the existing quality targets: valid
output rate above 95%, repair rate below 10%, zero high-risk allow misses, and
improved category macro F1.
