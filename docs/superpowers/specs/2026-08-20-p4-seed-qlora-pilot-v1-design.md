# P4 Seed QLoRA Pilot V1 Design

## Goal

Run one auditable, adapter-only QLoRA pilot on the frozen P4 Seed Dataset V1
before expanding the corpus from 1,000 rows to 5k–10k. The pilot validates the
formal data path, training prompt, 6GB GPU settings, validation-loss reporting,
and adapter loadability. It is not a release-quality P5 model.

The committed rows retain complete GuardResult V1 labels for auditability, but
the model-facing training target is the same six-field semantic contract used
by Baseline/Fusion V2.1: `decision`, `severity`, `category`, `summary`,
`confidence`, and `evidence`. System-owned fields are excluded from assistant
labels and are reconstructed by the existing deterministic envelope.

## Fixed inputs and isolation

The pilot consumes the committed files only:

- `data/train/agent_security_train_v1.jsonl` (800 rows);
- `data/val/agent_security_validation_v1.jsonl` (200 rows);
- `data/train/agent_security_seed_v1_manifest.json`;
- frozen Eval V1 requests only for the existing leakage gate.

Before importing Torch, Transformers, PEFT, or bitsandbytes, the loader must:

1. parse both JSONL files with the strict `TrainingExample` contract;
2. run `validate_seed_profile`, including exact curated-record comparison;
3. recompute both SHA-256 values and require the committed manifest values;
4. reject missing, malformed, mismatched, or Eval-leaking input.

Eval labels never enter training or validation. The 200-row validation split
remains semantic-cluster-disjoint from the 800-row training split.

## Training configuration

The fixed pilot defaults target the known RTX 1000 Ada Laptop GPU with 6GB:

```text
base model                 Qwen2.5-1.5B-Instruct (local only)
quantization               4-bit NF4, double quantization, BF16 compute
LoRA                       r=8, alpha=16, dropout=0.05, all-linear
maximum sequence length    512
micro batch                1
gradient accumulation      16
epochs                     2
learning rate              1e-4
optimizer                  paged_adamw_8bit
gradient checkpointing     enabled
validation                 every epoch
checkpoint retention       best eval-loss checkpoint, at most one
seed/data seed             42
```

The CLI may override model path, output path, maximum length, epoch count,
learning rate, and LoRA target. Every numeric override must be finite and
positive. Input records are never truncated: any row over `max_length` fails
before training starts.

## Components and data flow

`guard.training_config.P4SeedTrainingConfig` owns the pilot defaults and
validation. `guard.p4_qlora` loads and freezes the dataset bundle, converts the
complete labels to the Baseline V2 six-field assistant target, builds
pilot-specific Trainer arguments and manifest provenance, and delegates the
shared model/Trainer mechanics to `guard.qlora`.

`scripts/train_p4_seed_qlora.py` is the operator entrypoint. `--preflight-only`
runs data, model, package, CUDA, BF16, and free-memory checks without loading
the model. A real run writes only local ignored artifacts under
`artifacts/p4-seed-qlora-pilot-v1`.

`guard.p4_adapter_smoke` and `scripts/smoke_test_p4_adapter.py` load the saved
adapter against the same local base model and generate one held-out validation
record. The report records strict GuardResult validity and category agreement;
it parses exactly six fields through the production Baseline V2 parser, then
records the deterministic GuardResult envelope and category agreement. It never
modifies the adapter or dataset.

## Outputs and provenance

The run writes:

- `adapter/` containing PEFT adapter weights/config and tokenizer files;
- `trainer/` containing at most one best checkpoint;
- `training_manifest.json` with exact dataset hashes, prompt version, model
  target (`baseline-semantic-v2`), path, hyperparameters, row counts, trainable parameters, and
  `quality_milestone=false`;
- `training_metrics.json` with train metrics, final validation metrics, elapsed
  time, and peak allocated GPU memory;
- `adapter_smoke_report.json` after the post-training probe.

Full-model weight filenames are rejected in the adapter directory. Existing
non-empty output is protected unless `--overwrite-output` is explicit; an
overwritten run is moved to a timestamped sibling backup.

## Failure behavior

All expected configuration, data, artifact, dependency, and environment
failures exit concisely without a traceback. CUDA OOM retains the existing
explicit retry guidance using `--max-length 256 --lora-target attention`.
Unexpected programmer errors are not silently converted into successful
reports.

## Acceptance and next decision

CPU CI must cover configuration, dataset/hash preflight, manifest construction,
CLI failure shape, and adapter-artifact validation on Python 3.10 and 3.12.
The local GPU gate is complete only when training finishes, validation metrics
are finite, adapter-only artifacts pass preflight, and the held-out smoke probe
returns a strict six-field semantic result that can be enveloped as GuardResult.

The pilot result does not claim the final quality target. After the local run,
the next work item is adapter-backed evaluation on frozen Eval V1. Its error
profile determines targeted P4 expansion; no blind 5k–10k generation occurs
before this feedback.
