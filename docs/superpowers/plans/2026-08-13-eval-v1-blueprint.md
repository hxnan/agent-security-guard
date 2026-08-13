# Eval V1 Sample Blueprint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Commit and continuously validate an exact 100-row planning manifest for Eval V1.

**Architecture:** A focused `guard.eval_blueprint` module owns record parsing, quota constants, validation, and deterministic summaries. A thin command-line script loads the committed JSONL file and reports validation results. The data file contains planning metadata only; unit tests and CI prevent quota or structural drift.

**Tech Stack:** Python 3.10 standard library, existing `guard.taxonomy` enums, `unittest`, JSONL, GitHub Actions.

## Global Constraints

- The manifest has exactly 100 records with contiguous IDs `EV001` through `EV100`.
- Tool quotas are Shell 30, PowerShell 20, CMD 10, Python 30, and Mixed 10.
- Kind quotas are Normal 40, Dangerous 34, Boundary 16, and Injection 10, with every kind present in every tool family.
- Category quotas are exactly those in `docs/superpowers/specs/2026-08-13-eval-v1-blueprint-design.md`.
- All normal records use `benign`; all other records use a non-benign category.
- Every non-benign category spans at least two tool families.
- The implementation must not import Torch, Transformers, or model files.
- The file contains no final commands, `GuardResult`, confidence, evidence, reviewer identity, or gold-label status.

---

### Task 1: Blueprint record parser and field validation

**Files:**
- Create: `guard/eval_blueprint.py`
- Create: `tests/test_eval_blueprint.py`

**Interfaces:**
- Consumes: `ToolType` and `RiskCategory` from `guard.taxonomy`.
- Produces: `BlueprintRecord.from_dict(value: object, line_number: int) -> BlueprintRecord`, `BlueprintValidationError`, and the enums `ToolFamily`, `ScenarioKind`, `AuthoringStatus`.

- [ ] **Step 1: Write failing unit tests for valid parsing and rejected fields**

Add tests that build a valid `EV001` dictionary and assert its enum-backed fields. Add separate tests asserting `BlueprintValidationError` for an unknown key, invalid `sample_id`, invalid snake-case metadata, empty scenario, duplicate values within `risk_factors`, and a mixed record without at least two entries in `mixed_components`.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `python -m unittest tests.test_eval_blueprint.BlueprintRecordTests -v`

Expected: FAIL because `guard.eval_blueprint` does not exist.

- [ ] **Step 3: Implement the immutable record parser**

Create string enums for:

```python
class ToolFamily(StringEnum):
    SHELL = "shell"
    POWERSHELL = "powershell"
    CMD = "cmd"
    PYTHON = "python"
    MIXED = "mixed"

class ScenarioKind(StringEnum):
    NORMAL = "normal"
    DANGEROUS = "dangerous"
    BOUNDARY = "boundary"
    INJECTION = "injection"

class AuthoringStatus(StringEnum):
    PLANNED = "planned"
```

Define a frozen `BlueprintRecord` dataclass with the eleven fields in the design, plus `mixed_components: tuple[ToolType, ...]`. Non-mixed rows require an empty tuple; mixed rows require at least two distinct components and `request_type` must be one component. `from_dict` requires the exact key set, converts enum strings, rejects booleans where strings/lists are required, strips no user content silently, and raises `BlueprintValidationError` with the line number and field name.

- [ ] **Step 4: Run focused tests**

Run: `python -m unittest tests.test_eval_blueprint.BlueprintRecordTests -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add guard/eval_blueprint.py tests/test_eval_blueprint.py
git commit -m "feat: validate eval blueprint records"
```

### Task 2: Dataset quotas, cross-record validation, and CLI

**Files:**
- Modify: `guard/eval_blueprint.py`
- Modify: `tests/test_eval_blueprint.py`
- Create: `scripts/validate_eval_blueprint.py`

**Interfaces:**
- Consumes: `BlueprintRecord.from_dict`.
- Produces: `load_blueprint(path: Path) -> list[BlueprintRecord]`, `validate_blueprint(records: Sequence[BlueprintRecord]) -> BlueprintSummary`, and `BlueprintSummary.to_dict() -> dict[str, object]`.

- [ ] **Step 1: Write failing aggregate-validation tests**

Use a helper that loads the committed fixture path once it exists, plus focused in-memory mutations. Assert errors for duplicate IDs, gaps, duplicate `(semantic_template, variant)` pairs, quota drift, a normal/non-benign mismatch, a risky/benign mismatch, a non-benign category present in only one tool family, and a missing kind in one family. Assert `BlueprintSummary.to_dict()` orders keys deterministically.

- [ ] **Step 2: Run aggregate tests and verify failure**

Run: `python -m unittest tests.test_eval_blueprint.BlueprintDatasetTests -v`

Expected: FAIL because aggregate functions are absent.

- [ ] **Step 3: Implement quota constants and aggregate validation**

Define exact `Counter` constants copied from the design. `load_blueprint` parses one nonblank JSON object per line and reports JSON errors with a line number. `validate_blueprint` accumulates all detectable errors before raising one `BlueprintValidationError`, so a data author gets a complete repair list. The summary contains total count and sorted mappings for tool families, scenario kinds, and categories.

- [ ] **Step 4: Add the thin validation CLI**

The script defaults to `data/eval-v1/blueprint.jsonl`, accepts an optional positional path, prints the successful summary as indented JSON with `sort_keys=True`, writes a concise validation error to stderr, and returns exit code 2 for invalid data.

- [ ] **Step 5: Run focused tests**

Run: `python -m unittest tests.test_eval_blueprint.BlueprintDatasetTests -v`

Expected: PASS after Task 3 adds the committed manifest; until then, parser-only aggregate fixtures must pass and the committed-file test remains intentionally failing.

- [ ] **Step 6: Commit**

```bash
git add guard/eval_blueprint.py tests/test_eval_blueprint.py scripts/validate_eval_blueprint.py
git commit -m "feat: add eval blueprint validator"
```

### Task 3: Author the 100-row blueprint

**Files:**
- Create: `data/eval-v1/blueprint.jsonl`
- Modify: `tests/test_eval_blueprint.py`

**Interfaces:**
- Consumes: the exact quotas and record format from Tasks 1–2.
- Produces: the stable planning inputs for later Eval V1 command authoring.

- [ ] **Step 1: Add the failing committed-manifest test**

Load `data/eval-v1/blueprint.jsonl`, call `validate_blueprint`, and assert the exact expected summary totals. Also assert each `scenario` is unique and every category other than `benign` spans at least two tool families.

- [ ] **Step 2: Run the committed-manifest test and verify failure**

Run: `python -m unittest tests.test_eval_blueprint.CommittedBlueprintTests -v`

Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Write rows `EV001` through `EV100`**

Order rows by tool-family blocks: Shell `EV001`–`EV030`, PowerShell `EV031`–`EV050`, CMD `EV051`–`EV060`, Python `EV061`–`EV090`, and Mixed `EV091`–`EV100`. Within every block, place normal rows first, then dangerous, boundary, and injection rows. Use concrete scenario families spanning repository inspection, bounded cleanup, package operations, remote content execution, privilege changes, deletion, credential reads, uploads, startup mechanisms, security-control changes, untrusted downloads, firewall/DNS changes, protected writes, and bounded versus unbounded resource consumption.

Mixed rows must declare two or more values from `shell`, `powershell`, `cmd`, `python`, or `tool` in `mixed_components`; their scenarios must describe the boundary between those components. Reuse of a `semantic_template` is allowed only with a distinct `variant`, while every pair remains unique.

- [ ] **Step 4: Run the validator and tests**

Run: `python scripts/validate_eval_blueprint.py`

Expected: exit 0 with totals `100`, tool counts `30/20/10/30/10`, kind counts `40/34/16/10`, and exact category counts from the design.

Run: `python -m unittest tests.test_eval_blueprint -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add data/eval-v1/blueprint.jsonl tests/test_eval_blueprint.py
git commit -m "data: add eval v1 sample blueprint"
```

### Task 4: Documentation and CI drift gate

**Files:**
- Modify: `README.md`
- Modify: `docs/work_plan.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_eval_blueprint.py`

**Interfaces:**
- Consumes: `scripts/validate_eval_blueprint.py` and the committed manifest.
- Produces: contributor instructions and an explicit CI validation step.

- [ ] **Step 1: Add a CLI smoke test**

Run the script in a subprocess against a temporary invalid JSONL file and assert exit code 2 plus a line-numbered stderr message. Run it against the committed file and assert exit code 0 plus parseable JSON output.

- [ ] **Step 2: Run the smoke test and verify its initial state**

Run: `python -m unittest tests.test_eval_blueprint.BlueprintCliTests -v`

Expected: PASS only when the CLI contract is complete; fix CLI contract defects before documentation.

- [ ] **Step 3: Document validation and progress**

Add README links for the design and blueprint plus the command `python scripts/validate_eval_blueprint.py`. Mark the two P1 work-plan items for the 100-sample design and four-kind coverage complete. Do not mark JSONL gold-data validation or human review complete.

- [ ] **Step 4: Add the explicit CI command**

After unit tests, add:

```yaml
      - run: python scripts/validate_eval_blueprint.py
```

- [ ] **Step 5: Run all verification**

Run: `python -m unittest discover -s tests -v`

Expected: all tests PASS.

Run: `python scripts/validate_eval_blueprint.py`

Expected: exit 0 with deterministic JSON summary.

Run: `python scripts/export_schemas.py && git diff --exit-code -- schemas/v1`

Expected: exit 0 and no schema drift.

Run: `git diff --check`

Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/work_plan.md .github/workflows/ci.yml tests/test_eval_blueprint.py
git commit -m "ci: enforce eval blueprint quotas"
```
