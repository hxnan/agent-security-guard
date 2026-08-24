# P4 Targeted Batch V1 Design

## Goal

Create the first deterministic, versioned training-data expansion driven by
the P4 pilot adapter's aggregate error profile. The batch must prioritize the
single high-risk allow miss, three risk false negatives, benign boundary false
positives, and category confusion without copying frozen Eval requests.

## Scope

P4 Targeted Batch V1 contains 50 curated semantic clusters with ten variants
each. The first 40 clusters produce 400 training rows; ten different semantic
families produce 100 validation rows. IDs continue after Seed V1 as
`TR-001001` through `TR-001500`, and five fixed 100-row batch IDs preserve
generation provenance.

The category profile is intentionally error-driven: 200 benign rows, 80 remote
execution, 50 privilege escalation, 40 resource abuse, 30 each for sensitive
write and unsafe download, 20 data exfiltration, and 10 each for persistence,
network change, defense evasion, destructive operation, and credential access.

## Safety and isolation

- Never execute a generated command or access a referenced URL.
- Do not copy Eval commands, context, semantic-template names, or sample IDs.
- Reject every exact request fingerprint shared with frozen Eval V1.
- Reject every exact request fingerprint or semantic template shared with P4
  Seed V1.
- Keep train and validation IDs, requests, and semantic templates disjoint.
- Preserve complete GuardRequest/GuardResult and generation provenance.

The catalog contains independent examples of trusted or verified remote
content that is nevertheless executed, approved operations that still cross a
privilege boundary, misleading benchmark labels hiding resource abuse, and
benign read-only or bounded-workspace operations that resemble dangerous
syntax.

## Reproducibility

`training.targeted_catalog` owns the fixed scenarios.
`training.targeted_dataset` deterministically renders, labels, validates, and
serializes them. `scripts/prepare_targeted_training_data.py` performs atomic
publication of train, validation, and manifest files and refuses overwrite
without `--force`.

The manifest records the exact aggregate diagnostics that motivated the batch,
all category/tool/scenario/batch counts, output paths, and SHA-256 values.
Committed files must equal fresh generator output byte for byte.

## Evaluation validity

The manifest must set `evaluation_adaptive=true`. Eval V1 has now influenced
training-data selection, so it remains useful for regression and safety-gate
tracking but no longer provides an untouched generalization estimate. A new,
unseen Eval V2 is required before P5 can claim model-quality acceptance.

## Acceptance

- Exactly 500 rows with a 400/100 semantic-cluster split.
- Exactly 50 unique templates and 500 unique requests.
- Fixed category profile and five 100-row batches.
- Seed V1 and Eval V1 isolation gates pass.
- Repeated generation is byte-identical.
- Existing Seed V1 files, frozen Eval V1, schemas, and model artifacts remain
  unchanged.
