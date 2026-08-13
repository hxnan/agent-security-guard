# QLoRA Epoch Diagnostic Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the existing QLoRA epoch setting through the training CLI so a three-epoch retry can test whether 12 optimizer steps were insufficient to learn GuardResult V1.

**Architecture:** Keep `SmokeTrainingConfig` and all training behavior unchanged. Extract CLI parsing into a pure `parse_config(argv)` boundary that returns `SmokeTrainingConfig`, then have `main()` pass that configuration to `train_smoke()`.

**Tech Stack:** Python 3.10, argparse, dataclasses, unittest, existing QLoRA smoke pipeline.

## Global Constraints

- Default training remains exactly one epoch.
- The retry changes only `num_train_epochs`; data, prompt, LoRA, learning rate, generation, and validation remain unchanged.
- `num_train_epochs` must continue to use `SmokeTrainingConfig` positive-value validation.
- The training manifest must record the requested value through the existing manifest builder.
- CPU CI must not import training-only ML packages or require CUDA.

---

### Task 1: Configurable epoch CLI

**Files:**
- Modify: `scripts/train_smoke_qlora.py`
- Modify: `tests/test_train_smoke_cli.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `SmokeTrainingConfig(num_train_epochs: float)`.
- Produces: `parse_config(argv: Sequence[str] | None) -> SmokeTrainingConfig` and CLI option `--num-train-epochs FLOAT`.

- [ ] **Step 1: Write the failing parser test**

```python
from scripts.train_smoke_qlora import parse_config

config = parse_config(["--num-train-epochs", "3"])
self.assertEqual(config.num_train_epochs, 3.0)
self.assertFalse(config.overwrite_output)
```

- [ ] **Step 2: Run the focused test and verify red**

Run: `python -m unittest tests.test_train_smoke_cli.TrainSmokeCliTests.test_epoch_option_populates_training_config -v`

Expected: FAIL because `parse_config` does not exist.

- [ ] **Step 3: Implement the minimal parser boundary**

Add `--num-train-epochs` with `type=float` and `default=1.0`. Return a `SmokeTrainingConfig` containing every existing CLI field plus `num_train_epochs=args.num_train_epochs`. Change `main()` to call `train_smoke(parse_config(argv))`.

- [ ] **Step 4: Add invalid-value behavior coverage**

```python
with self.assertRaisesRegex(TrainingConfigError, "num_train_epochs"):
    parse_config(["--num-train-epochs", "0"])
```

This exercises the real `SmokeTrainingConfig` validation rather than duplicating it in argparse.

- [ ] **Step 5: Run focused and full verification**

Run:

```bash
python -m unittest tests.test_train_smoke_cli -v
python -m unittest discover -s tests -v
python -m compileall -q guard scripts tests
git diff --check
```

Expected: all tests pass, compilation succeeds, and no whitespace errors are reported.

- [ ] **Step 6: Document and commit**

Add the diagnostic command to README:

```bash
python scripts/train_smoke_qlora.py --num-train-epochs 3 --overwrite-output
python scripts/smoke_test_adapter.py
```

Commit:

```bash
git add scripts/train_smoke_qlora.py tests/test_train_smoke_cli.py README.md
git commit -m "feat: add qlora epoch retry option"
```
