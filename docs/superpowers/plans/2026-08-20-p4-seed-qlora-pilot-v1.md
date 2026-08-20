# P4 Seed QLoRA Pilot V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe local QLoRA pilot that trains on the frozen 800/200 P4 Seed Dataset V1 and produces auditable adapter-only artifacts.

**Architecture:** A P4-specific configuration and strict dataset loader wrap the existing QLoRA mechanics. The shared trainer accepts normalized records while P4 code owns formal-data hashes, manifest provenance, pilot Trainer arguments, CLI behavior, and a held-out adapter smoke probe.

**Tech Stack:** Python 3.10+, Pydantic 2.13.4, Torch 2.5.1+cu124, Transformers 4.57.6, PEFT 0.20.0, bitsandbytes 0.49.2, standard-library `unittest`.

**Spec:** `docs/superpowers/specs/2026-08-20-p4-seed-qlora-pilot-v1-design.md`

## Global Constraints

- Do not modify `data/eval-v1/**`, P4 Seed JSONL bytes, schemas, model weights, adapters, checkpoints, or artifacts in version control.
- Eval labels must never enter training or validation.
- Validate data and exact SHA-256 values before importing ML dependencies.
- Keep smoke QLoRA behavior and commands backward compatible.
- Default to 4-bit NF4/double-quant/BF16, max length 512, micro batch 1, gradient accumulation 16, two epochs, learning rate `1e-4`, and seed 42.
- Do not truncate overlength records.
- Persist PEFT adapter-only output and mark the pilot `quality_milestone=false`.

---

### Task 1: P4 configuration and strict dataset bundle

**Files:**
- Modify: `guard/training_config.py`
- Create: `guard/p4_qlora.py`
- Create: `tests/test_p4_qlora.py`

**Interfaces:**
- Consumes: `TrainingExample`, `load_training_jsonl`, `validate_seed_profile`, committed manifest and Eval request fingerprints.
- Produces: `P4SeedTrainingConfig`, `P4DatasetBundle`, `load_p4_dataset_bundle(config)` and `inspect_training_environment_for_files(model_path, data_files)`.

- [ ] **Step 1: Write failing tests** proving fixed defaults, numeric validation, exact 800/200 loading, manifest hashes, and rejection of a tampered manifest/hash before any ML import.
- [ ] **Step 2: Run** `python -m unittest tests.test_p4_qlora -v` and confirm failures are caused by missing P4 interfaces.
- [ ] **Step 3: Implement** `P4SeedTrainingConfig`, a shared named-file environment inspector, immutable normalized training records, and strict bundle loading with these literal hashes:

```python
EXPECTED_P4_SHA256 = {
    "train": "1897e89d11a730ad0922081bda0cf18da3b643a1fc887c2e27abaa7cc5e96208",
    "validation": "c4228d11dd08e8e0cf2a48b01398b5ee0be8a7270a572285e870e74eb939915e",
}
```

- [ ] **Step 4: Re-run** `python -m unittest tests.test_p4_qlora tests.test_training_config -v` and require all cases to pass.
- [ ] **Step 5: Commit** only Task 1 files with message `feat: add P4 QLoRA pilot preflight`.

### Task 2: Shared training core and P4 training provenance

**Files:**
- Modify: `guard/qlora.py`
- Modify: `guard/training_data.py`
- Modify: `guard/p4_qlora.py`
- Modify: `tests/test_qlora.py`
- Modify: `tests/test_training_data.py`
- Modify: `tests/test_p4_qlora.py`

**Interfaces:**
- Consumes: normalized objects with `sample_id`, `request`, and `result`; `P4DatasetBundle`; `P4SeedTrainingConfig`.
- Produces: `run_qlora_training(...)`, six-field `format_p4_training_messages(...)`, `build_p4_training_arguments(...)`, `build_p4_training_manifest(...)`, and `train_p4_seed(config)`.

- [ ] **Step 1: Write failing tests** for the exact Baseline V2 six-field assistant target, generic record formatting, pilot arguments (`gradient_accumulation_steps=16`, `learning_rate=1e-4`, epoch eval/save, best eval loss, one checkpoint), and a manifest containing exact dataset hashes and `quality_milestone=false`.
- [ ] **Step 2: Run** the three focused modules and confirm the new expectations fail while existing smoke expectations remain green.
- [ ] **Step 3: Extract** the existing lazy-import model/Trainer/save mechanics into `run_qlora_training` without changing smoke defaults, then implement P4 arguments, manifest callback, finite metric enforcement, and adapter-only checks.
- [ ] **Step 4: Re-run** the focused modules and the existing smoke CLI tests.
- [ ] **Step 5: Commit** Task 2 files with message `feat: add P4 QLoRA pilot training core`.

### Task 3: Operator CLI and concise preflight

**Files:**
- Create: `scripts/train_p4_seed_qlora.py`
- Create: `tests/test_train_p4_seed_qlora_cli.py`
- Modify: `guard/p4_qlora.py`

**Interfaces:**
- Consumes: `P4SeedTrainingConfig`, `preflight_p4_seed_training(config)`, `train_p4_seed(config)`.
- Produces: deterministic JSON for `--preflight-only` and the real local training result.

- [ ] **Step 1: Write failing subprocess tests** for defaults, invalid/non-finite numeric arguments, malformed data failure before ML loading, and deterministic preflight JSON.
- [ ] **Step 2: Run** `python -m unittest tests.test_train_p4_seed_qlora_cli -v` and confirm the script/interface is missing.
- [ ] **Step 3: Implement** CLI flags `--model-path`, `--train`, `--validation`, `--manifest`, `--eval-dir`, `--output-dir`, `--max-length`, `--num-train-epochs`, `--learning-rate`, `--lora-target`, `--overwrite-output`, and `--preflight-only`.
- [ ] **Step 4: Re-run** CLI and P4 QLoRA tests.
- [ ] **Step 5: Commit** Task 3 files with message `feat: add P4 QLoRA pilot CLI`.

### Task 4: P4 adapter smoke probe

**Files:**
- Create: `guard/p4_adapter_smoke.py`
- Create: `scripts/smoke_test_p4_adapter.py`
- Create: `tests/test_p4_adapter_smoke.py`

**Interfaces:**
- Consumes: pilot adapter directory, P4 manifest/bundle, local base model, shared adapter runtime and strict Baseline V2 six-field parser/envelope.
- Produces: `validate_p4_adapter_artifacts(...)`, `smoke_test_p4_adapter(...)`, and `adapter_smoke_report.json`.

- [ ] **Step 1: Write failing tests** for required adapter/config/metrics/manifest artifacts, method/data version/hash checks, base-model mismatch, and missing/invalid validation rows.
- [ ] **Step 2: Run** `python -m unittest tests.test_p4_adapter_smoke -v` and confirm the module is missing.
- [ ] **Step 3: Implement** P4 artifact validation and one-record held-out generation by reusing shared runtime loading, message formatting, strict result validation, and atomic report writing.
- [ ] **Step 4: Re-run** P4 and existing smoke adapter tests.
- [ ] **Step 5: Commit** Task 4 files with message `feat: add P4 adapter smoke probe`.

### Task 5: Documentation, verification, review, and publication

**Files:**
- Modify: `README.md`
- Modify: `docs/p4_qlora_pipeline_v1.md`
- Modify: `docs/work_plan.md`

**Interfaces:**
- Consumes: all earlier commands and artifact paths.
- Produces: exact local pull/preflight/train/smoke instructions and accurate pilot status.

- [ ] **Step 1: Document** the pilot as a feedback gate before blind expansion, including exact commands and the distinction between pilot completion and P5 quality acceptance.
- [ ] **Step 2: Run** focused P4 tests, `python -m unittest discover -s tests -v`, dataset regeneration/gate, Eval blueprint/freeze validation, schema drift hashes, wheel-content inspection, protected-path scope review, and `git diff --check`.
- [ ] **Step 3: Request** independent code review and fix every Critical/Important finding with RED/GREEN tests.
- [ ] **Step 4: Publish** one non-draft PR, wait for Python 3.10/3.12 CI, and squash merge only the reviewed head SHA.
- [ ] **Step 5: Notify** the user to pull main and run preflight, training, and adapter smoke; collect compact JSON for the next adapter-backed Eval V1 work item.
