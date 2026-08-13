# Explicit GuardResult Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the shared training/inference system prompt define every required GuardResult V1 field and legal enum so the model cannot reasonably invent categories such as `network_access`.

**Architecture:** Keep `format_training_messages()` as the single shared prompt path. Build deterministic enum fragments directly from the existing `Decision`, `Severity`, and `RiskCategory` classes, then compose them into `SYSTEM_PROMPT` with a literal required-key list.

**Tech Stack:** Python 3.10, Pydantic contracts, Enum-backed taxonomy, unittest, existing Qwen chat preprocessing.

## Global Constraints

- Change only the shared system prompt; do not modify smoke data, QLoRA parameters, learning rate, generation settings, or validation behavior.
- List all 11 required GuardResult keys and forbid extra keys.
- Source legal enum values from existing runtime enum classes in deterministic declaration order.
- Training and inference must continue using `format_training_messages()`.
- CPU CI must not load a model or import training-only dependencies.

---

### Task 1: Explicit prompt contract

**Files:**
- Modify: `guard/training_data.py`
- Modify: `tests/test_training_data.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `Decision`, `Severity`, and `RiskCategory` enum classes from `guard.taxonomy`.
- Produces: deterministic `SYSTEM_PROMPT` consumed by `format_training_messages(record)`.

- [ ] **Step 1: Write failing prompt-contract tests**

Add a test that asserts every literal required key appears in `SYSTEM_PROMPT`, every enum `.value` appears in its labeled contract fragment, and the text forbids extra fields.

- [ ] **Step 2: Run the focused test and verify red**

Run: `python -m unittest tests.test_training_data.TrainingDataTests.test_system_prompt_defines_complete_guardresult_contract -v`

Expected: FAIL because the current prompt only names GuardResult V1.

- [ ] **Step 3: Implement the prompt from existing enums**

Import `Decision`, `Severity`, and `RiskCategory` from `guard.taxonomy`. Use a pure helper that joins `member.value for member in enum_type`, and compose `SYSTEM_PROMPT` with required keys, labeled legal values, and the no-extra-key rule.

- [ ] **Step 4: Verify shared-path behavior**

Extend the existing message-format test to assert `format_training_messages(record)[0]["content"] == SYSTEM_PROMPT`. This protects both training and adapter inference because each consumes the same formatter.

- [ ] **Step 5: Run focused and full verification**

```bash
python -m unittest tests.test_training_data -v
python -m unittest discover -s tests -v
python -m compileall -q guard scripts tests
git diff --check
```

Expected: all tests pass, compilation succeeds, and the worktree contains only the intended files.

- [ ] **Step 6: Document and commit**

Update README to state that the shared prompt enumerates GuardResult V1 fields and legal values, then commit:

```bash
git add guard/training_data.py tests/test_training_data.py README.md
git commit -m "feat: define guardresult prompt contract"
```
