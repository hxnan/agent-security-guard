# Annotation Guideline V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish an operational human-labeling manual that makes Agent Security Guard `eval-v1` labels consistent, reviewable, and traceable.

**Architecture:** Keep taxonomy identifiers and runtime field constraints in their existing authoritative files. Add one focused annotation manual that translates those contracts into ordered human decisions, examples, and review governance; then update navigation and milestone status without creating evaluation records or executable policy.

**Tech Stack:** Markdown, existing Pydantic/JSON Schema contracts, Python `unittest` regression suite, GitHub Actions.

## Global Constraints

- Use the general-purpose product baseline, not a personal-machine or enterprise-specific policy.
- Behavior overrides unsupported purpose claims; only concrete evidence may lower risk.
- Choose exactly one primary category by final security impact, then higher default severity, then closest observable behavior with `review`.
- Missing trusted context uses `risk=true` and `review`; `benign` is never an unknown fallback.
- Use only confidence values `0.99`, `0.90`, `0.75`, `0.60`, and `0.50`; values below `0.50` cannot enter `eval-v1`.
- Category decision/severity defaults may be overridden only with evidence and annotation metadata `override_reason`.
- Keep annotation governance metadata outside runtime `GuardResult`.
- Use primary annotation plus independent second review; unresolved disagreement cannot enter frozen `eval-v1`.
- Do not create the 100 production evaluation samples, JSONL validation code, model prompts, inference, organization policy, or executable commands.
- Human prose is reviewed for semantic consistency; do not add brittle tests that grep exact documentation wording.

---

### Task 1: Operational annotation manual

**Files:**

- Create: `docs/annotation_guideline_v1.md`

**Interfaces:**

- Consumes: the identifiers and defaults in `docs/risk_taxonomy_v1.md` and `guard/taxonomy.py`.
- Consumes: field types and limits in `schemas/v1/guard-result.schema.json` and `guard/contracts.py`.
- Produces: the normative human procedure for labeling and reviewing future `eval-v1` records.

- [ ] **Step 1: Write the scope and context-trust sections**

Document the general product baseline, required sample inputs, non-goals, evidence hierarchy, untrusted embedded instructions, and the rule that unsupported purpose statements cannot lower risk.

- [ ] **Step 2: Write the ordered annotation procedure**

Include all ten steps from input completeness through independent review. Make explicit that commands are never executed during labeling and that behavior must be reconstructed across variables, pipes, redirection, encoding, subprocesses, and multi-step flows.

- [ ] **Step 3: Write field consistency and decision rules**

Include the valid matrix and every invalid combination from the design. Define `allow`, `review`, `block`, default adjustment evidence, `critical + review`, and the metadata-only `override_reason` rule.

- [ ] **Step 4: Write category selection and all 12 boundaries**

For every taxonomy identifier, give inclusion, exclusion, and a confusing-neighbor boundary. Define final-impact selection and the deterministic tie breakers. Do not invent new category identifiers.

- [ ] **Step 5: Write confidence, summary, evidence, and governance rules**

Include the five exact confidence tiers and rejection floor. Define the Chinese 1–30-character summary, maximum five evidence items, metadata fields, independent review procedure, dispute status, adjudication, and freeze criteria.

- [ ] **Step 6: Add ten complete normative examples**

Cover the ten design cases. Each accepted example must show a `GuardRequest`-shaped input, a schema-valid `GuardResult`-shaped result, reasoning trace limited to observable rules, and governance notes. The rejected-below-confidence example must be explicitly outside `eval-v1` and must not pretend to be a valid gold result.

- [ ] **Step 7: Add primary and reviewer checklists**

Provide short checklists that can be followed without rereading the whole manual. Include category identifiers, core consistency, confidence tier, summary/evidence limits, default overrides, independent review, and dispute resolution.

- [ ] **Step 8: Perform structured manual verification**

Compare every identifier, default severity/decision, decision enum, severity enum, summary limit, evidence limit, and confidence range against the current taxonomy and Schema. Verify every valid example against the consistency matrix and count all 12 categories in the boundary section.

- [ ] **Step 9: Run repository regression tests**

Run:

```bash
python -m unittest discover -s tests -v
python scripts/export_schemas.py
git diff --exit-code -- schemas/v1
git diff --check
```

Expected: 20 tests pass, schemas remain byte-identical, and no whitespace errors appear.

- [ ] **Step 10: Commit Task 1**

```bash
git add docs/annotation_guideline_v1.md
git commit -m "docs: add annotation guideline v1"
```

### Task 2: Navigation and milestone synchronization

**Files:**

- Modify: `README.md`
- Modify: `docs/work_plan.md`

**Interfaces:**

- Consumes: the completed `docs/annotation_guideline_v1.md` from Task 1.
- Produces: discoverable documentation and accurate P0/P1 progress without changing runtime behavior.

- [ ] **Step 1: Add README navigation**

Add `docs/annotation_guideline_v1.md` to the project-document list and describe it as the human standard for category, decision, severity, confidence, evidence, and review.

- [ ] **Step 2: Synchronize completed milestones**

Update `docs/work_plan.md` to mark target-machine P0 installation/tests and model/CUDA validation complete. Mark P1 work package 1 (versioned JSON Schema) and work package 2 (annotation guideline) complete, while leaving the 100-sample design, JSONL validator/statistics, review, and `eval-v1` freeze incomplete.

- [ ] **Step 3: Review scope and links**

Verify every new relative link resolves, the work plan does not claim `eval-v1` exists, and no model/training/policy milestone is marked complete.

- [ ] **Step 4: Run final acceptance**

Run:

```bash
python -m unittest discover -s tests -v
python scripts/export_schemas.py
git diff --exit-code -- schemas/v1
git diff --check
git status --short --branch
```

Expected: 20 tests pass, schema diff is empty, and only the two Task 2 documentation files are modified before commit.

- [ ] **Step 5: Commit Task 2**

```bash
git add README.md docs/work_plan.md
git commit -m "docs: update P1 annotation progress"
```

- [ ] **Step 6: Final semantic review**

Review the full feature diff against `docs/superpowers/specs/2026-08-13-annotation-guideline-v1-design.md`. Reject any mismatch in taxonomy identifiers, valid combinations, confidence tiers, metadata/runtime separation, review workflow, or claimed milestone status before publication.
