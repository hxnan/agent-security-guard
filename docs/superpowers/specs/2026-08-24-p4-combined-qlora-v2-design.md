# P4 Seed + Targeted QLoRA V2 Design

## Goal

Train one reproducible 6 GB GPU QLoRA adapter from the frozen Seed V1 and
Targeted V1 bundles, without rewriting or concatenating the committed JSONL
files. The combined run contains 1,200 training and 300 validation records.

## Fixed contract

- data version: `p4-seed-targeted-v2`;
- method: `qlora-p4-seed-targeted-v2`;
- output: `artifacts/p4-seed-targeted-qlora-v2`;
- one epoch, max length 768, micro batch 1, gradient accumulation 16, NF4,
  BF16; 768 covers the observed 711-token maximum without truncation;
- exact Seed and Targeted file hashes and both manifests are checked before
  environment or model loading;
- Targeted data is revalidated against Seed overlap and independent frozen
  Eval V1 command, context-source, context-object, request, and template gates;
- the training manifest records each source bundle's hashes and row counts;
- adapter validation and Eval V1 provenance accept only the fixed Seed pilot or
  the fixed combined V2 contract.

Eval V1 is development-adaptive after Targeted V1. Its results are regression
diagnostics, not a final generalization claim; that claim requires untouched
Eval V2.

## Operator flow

1. `python scripts/train_p4_combined_qlora.py --preflight-only`
2. `python scripts/train_p4_combined_qlora.py --overwrite-output`
3. `python scripts/smoke_test_p4_adapter.py --adapter-dir artifacts/p4-seed-targeted-qlora-v2/adapter --report artifacts/p4-seed-targeted-qlora-v2/adapter_smoke_report.json`
4. `python scripts/evaluate_p4_adapter.py --adapter-dir artifacts/p4-seed-targeted-qlora-v2/adapter --output artifacts/p4-seed-targeted-eval-v2/report.json`
