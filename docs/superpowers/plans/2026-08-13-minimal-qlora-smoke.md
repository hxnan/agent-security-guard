# Minimal QLoRA Smoke Training Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a reproducible, 6GB-GPU smoke loop from independent synthetic data generation through QLoRA Adapter training and schema-valid adapter inference.

**Architecture:** Keep all deterministic data and prompt logic in lightweight `guard` modules that CI can test without ML packages. Training and inference scripts lazy-import Torch/Transformers/PEFT/bitsandbytes only after validating arguments and local files. Generated data and artifacts remain ignored and are never committed.

**Tech Stack:** Python 3.10, Pydantic 2.13.4, PyTorch 2.5.1+cu124, Transformers 4.57.6, Accelerate 1.14.0, PEFT 0.20.0, bitsandbytes 0.49.2, unittest, JSONL.

## Global Constraints

- Do not train on or copy records from `data/eval-v1/blueprint.jsonl`.
- Generate exactly 96 train and 24 validation records, with 8/2 records for every RiskCategory.
- All generated requests and results must pass `GuardRequest` and `GuardResult` validation.
- Train and validation template identifiers are disjoint and do not overlap Eval V1 template identifiers.
- Training loss applies only to assistant JSON and EOS; prompt labels are `-100`.
- Default maximum sequence length is 512 and overlong examples fail rather than truncate.
- CI must not import or install training dependencies, download a model, or require GPU.
- Never save or commit full model weights; only PEFT Adapter files and local metrics are permitted under ignored `artifacts/`.
- A successful smoke run proves the pipeline only, not security quality or P5 completion.

---

### Task 1: Deterministic smoke dataset generator

**Files:**
- Create: `guard/smoke_data.py`
- Create: `scripts/generate_smoke_data.py`
- Create: `tests/test_smoke_data.py`

**Interfaces:**
- Produces: `SmokeRecord`, `generate_smoke_records() -> tuple[list[SmokeRecord], list[SmokeRecord]]`, `validate_smoke_records(train, validation, eval_templates) -> SmokeSummary`, and `write_smoke_dataset(output_dir, force=False) -> SmokeSummary`.

- [ ] Write failing tests for the literal 96/24 and 8/2 category counts, schema-valid nested request/result objects, deterministic output, split/template disjointness, Eval V1 template rejection, duplicate IDs, and safe overwrite behavior.
- [ ] Run `python -m unittest tests.test_smoke_data -v`; verify failure because the module is absent.
- [ ] Implement twelve category recipes with ten concrete variants each. Use variants 1–8 for train and 9–10 for validation, category defaults for labels, stable `ST-<category>-NN` IDs, and canonical JSONL serialization.
- [ ] Implement a CLI defaulting to `data/generated/smoke-v1`, with `--force`, deterministic JSON summary, concise exit 2 errors, and repository-root behavior from any CWD.
- [ ] Run focused tests and `python scripts/generate_smoke_data.py --force`; validate literal totals and ensure generated files remain ignored.
- [ ] Commit with `git commit -m "data: add deterministic smoke dataset generator"`.

### Task 2: Assistant-only training preprocessing

**Files:**
- Create: `guard/training_data.py`
- Create: `tests/test_training_data.py`

**Interfaces:**
- Consumes: `SmokeRecord` dictionaries and a tokenizer exposing `apply_chat_template`, `encode`, `eos_token_id`, and `pad_token_id`.
- Produces: `SYSTEM_PROMPT`, `format_training_messages(record)`, `tokenize_training_record(record, tokenizer, max_length)`, `CausalJsonCollator(tokenizer)`.

- [ ] Write failing tests using a deterministic fake tokenizer. Assert canonical request/result JSON, untrusted-data system text, all prompt labels `-100`, assistant/EOS labels equal input IDs, overlength rejection, right-padding, attention masks, and `-100` label padding.
- [ ] Run `python -m unittest tests.test_training_data -v`; verify missing-module failure.
- [ ] Implement pure-Python formatting/token boundary calculation. Import Torch only inside the collator call so formatting tests remain lightweight; raise a concise dependency error if collating without Torch.
- [ ] Run focused tests and the full suite.
- [ ] Commit with `git commit -m "feat: add assistant-only training preprocessing"`.

### Task 3: Training configuration and environment gate

**Files:**
- Create: `guard/training_config.py`
- Create: `scripts/check_training_environment.py`
- Create: `requirements-train-smoke.txt`
- Create: `tests/test_training_config.py`

**Interfaces:**
- Produces: immutable `SmokeTrainingConfig`, `resolve_model_path(explicit, environ)`, `inspect_training_environment(...) -> dict[str, object]`, and `assert_training_ready(report)`.

- [ ] Write failing tests for defaults, positive numeric argument validation, model path precedence, missing model files, missing package versions, CUDA/BF16/GPU-memory failures, and deterministic readiness reports using injected probes.
- [ ] Run focused tests and verify failure.
- [ ] Implement configuration with defaults from the spec. The script lazy-imports packages, checks exact installed versions, calls the existing model-file inspector, and reports CUDA name, total memory, BF16 support, and generated split presence without loading the model.
- [ ] Record the complete known environment in `requirements-train-smoke.txt`; README must warn not to reinstall Torch from this file.
- [ ] Run focused/full tests.
- [ ] Commit with `git commit -m "feat: add qlora training readiness gate"`.

### Task 4: Local QLoRA trainer

**Files:**
- Create: `guard/qlora.py`
- Create: `scripts/train_smoke_qlora.py`
- Create: `tests/test_qlora.py`

**Interfaces:**
- Produces: `build_quantization_kwargs(torch_module, transformers_module)`, `build_lora_config(peft_module, target)`, `build_training_arguments(transformers_module, config)`, `train_smoke(config) -> dict[str, object]`.

- [ ] Write failing tests against injected fake modules for NF4/double-quant/BF16 configuration, `all-linear` versus attention fallback targets, exact Trainer arguments, existing-output protection, and manifest field construction. Tests must not instantiate a real model.
- [ ] Run focused tests and verify failure.
- [ ] Implement lazy imports and the runtime flow: readiness gate, load local tokenizer/model on CUDA 0, disable cache, prepare k-bit model, attach LoRA, tokenize 96/24 records, train/evaluate, save Adapter/tokenizer only, and atomically write JSON metrics/manifests.
- [ ] Catch CUDA OOM to print the exact lower-memory retry command and re-raise. Assert saved artifacts do not contain full-model filenames.
- [ ] Run focused/full tests and compile all Python files.
- [ ] Commit with `git commit -m "feat: add minimal qlora smoke trainer"`.

### Task 5: Adapter inference smoke check and handoff docs

**Files:**
- Create: `scripts/smoke_test_adapter.py`
- Create: `tests/test_adapter_smoke.py`
- Modify: `README.md`
- Modify: `docs/work_plan.md`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `extract_first_json_object(text) -> dict[str, object]`, `validate_generated_result(text) -> GuardResult`, and local `adapter_smoke_report.json`.

- [ ] Write failing tests for JSON extraction with surrounding text, braces inside JSON strings, missing/malformed JSON, GuardResult schema rejection, and report serialization.
- [ ] Run focused tests and verify failure.
- [ ] Implement lazy model/adapter loading, one held-out generation, schema validation, category-match reporting, elapsed time, and peak-memory reporting. Invalid generations remain in the ignored local report and exit 1.
- [ ] Document the four-command local sequence: install only PEFT/bitsandbytes, generate data, check readiness, train, smoke-test Adapter. Mark only a new “QLoRA engineering smoke prepared” work-plan item complete; leave P1/P2/P4/P5 milestone gates incomplete.
- [ ] Add CI commands for smoke data generation/validation in a temporary directory; do not install training dependencies.
- [ ] Run `python -m unittest discover -s tests -v`, temporary smoke generation, Eval V1 validation, Schema drift, compileall, `git diff --check`, and ignored-artifact checks.
- [ ] Commit with `git commit -m "docs: add minimal qlora smoke handoff"`.

### Task 6: Review, publish, and local GPU execution

**Files:** No new files unless review finds a defect.

- [ ] Request a read-only review against this plan and fix all Critical/Important findings with regression tests.
- [ ] Re-run every verification command on the final tree.
- [ ] Publish the exact tree to GitHub `main` with a non-force update and verify remote Blob SHAs.
- [ ] Wait for GitHub Actions success on Python 3.10 and 3.12.
- [ ] Ask the user to pull and run the local GPU sequence. This is the first required user intervention.
- [ ] Diagnose the returned training output; if OOM, use the documented 256-token attention-only fallback before changing any other variable.
