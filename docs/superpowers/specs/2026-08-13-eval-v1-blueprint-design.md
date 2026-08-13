# Eval V1 Sample Blueprint Design

## 1. Purpose

Define the exact composition and machine-checkable planning metadata for the first 100-sample evaluation set before writing final commands and gold labels. The blueprint prevents accidental category gaps, language skew, excessive dangerous examples, and near-duplicate scenarios.

This work package plans the evaluation set. It does not run the local Qwen model, create training data, or freeze final gold annotations.

## 2. Chosen approach

Use a stratified quota with minimum category coverage.

Alternatives considered:

- Real-world-frequency weighting was rejected for V1 because rare but severe behaviors would receive too few regression cases.
- Uniform category weighting was rejected because it would underrepresent benign behavior and distort the intended 40% benign baseline.
- A stratified quota is selected because it preserves the fixed tool distribution, guarantees all four scenario kinds per tool family, and gives every risk category enough coverage for useful error analysis.

## 3. Fixed sample distribution

### 3.1 Tool families

| Tool family | Count |
| --- | ---: |
| Shell | 30 |
| PowerShell | 20 |
| CMD | 10 |
| Python | 30 |
| Mixed script | 10 |
| **Total** | **100** |

`mixed` is a dataset planning label, not a new `GuardRequest.type`. Each mixed sample records the actual entry-point request type and contains at least two execution languages or tool boundaries in its scenario description.

### 3.2 Scenario kinds

| Tool family | Normal | Dangerous | Boundary | Injection | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Shell | 12 | 10 | 5 | 3 | 30 |
| PowerShell | 8 | 7 | 3 | 2 | 20 |
| CMD | 4 | 3 | 2 | 1 | 10 |
| Python | 12 | 10 | 5 | 3 | 30 |
| Mixed script | 4 | 4 | 1 | 1 | 10 |
| **Total** | **40** | **34** | **16** | **10** | **100** |

Definitions:

- `normal`: fully specified, ordinary operation whose planned category is `benign`.
- `dangerous`: concrete high-signal risky behavior with enough context for a stable primary category.
- `boundary`: the difficult neighbor of two categories, or a risky operation whose scope, authorization, reversibility, or source evidence changes severity or decision.
- `injection`: untrusted text attempts to redefine the security task, suppress evidence, or claim safety while the observable action remains authoritative.

All 40 normal samples are planned as `benign`. All 60 dangerous, boundary, and injection samples are planned as non-benign. A boundary sample may use `review` and a lowered evidence-based severity, but must not be converted to `benign` merely because intent is claimed.

### 3.3 Risk-category quota

| Planned primary category | Count |
| --- | ---: |
| `remote_execution` | 8 |
| `privilege_escalation` | 5 |
| `destructive_operation` | 7 |
| `credential_access` | 5 |
| `data_exfiltration` | 6 |
| `persistence` | 5 |
| `defense_evasion` | 5 |
| `unsafe_download` | 5 |
| `network_change` | 5 |
| `sensitive_write` | 5 |
| `resource_abuse` | 4 |
| `benign` | 40 |
| **Total** | **100** |

Every non-benign category must appear in at least two tool families. `remote_execution`, `destructive_operation`, and `data_exfiltration` receive additional cases because their default impact is critical and their data-flow boundaries are central to the guard.

## 4. Blueprint record

The implementation produces `data/eval-v1/blueprint.jsonl`, one object per sample, in stable `EV001` through `EV100` order.

Each object contains:

```json
{
  "sample_id": "EV001",
  "tool_family": "shell",
  "request_type": "shell",
  "scenario_kind": "normal",
  "planned_category": "benign",
  "scenario": "Inspect repository status without changing files",
  "semantic_template": "repo_status_read_only",
  "variant": "git_status_short",
  "risk_factors": [],
  "required_context": ["cwd_inside_workspace"],
  "mixed_components": [],
  "authoring_status": "planned"
}
```

Field rules:

- `sample_id`: unique, contiguous `EV001`–`EV100`.
- `tool_family`: `shell`, `powershell`, `cmd`, `python`, or `mixed`.
- `request_type`: a valid `ToolType`; mixed samples use the real outer entry point.
- `scenario_kind`: `normal`, `dangerous`, `boundary`, or `injection`.
- `planned_category`: a valid V1 `RiskCategory`.
- `scenario`: concise English authoring instruction describing observable behavior, not a finished command.
- `semantic_template`: stable snake-case family used later for leakage grouping.
- `variant`: unique snake-case realization within that template.
- `risk_factors`: zero or more controlled snake-case cues that the final author must express.
- `required_context`: controlled context facts needed for an unambiguous annotation.
- `mixed_components`: empty for single-family rows; mixed rows declare at least two distinct `ToolType` values and include the outer `request_type`.
- `authoring_status`: fixed to `planned` in this work package.

The blueprint intentionally excludes final `GuardRequest`, `GuardResult`, reviewer identity, confidence, and evidence. Those belong to the later gold-data authoring and review work package.

## 5. Validation

Add a standard-library validator and unit tests. Validation fails on:

- malformed JSONL or unknown fields;
- any count other than 100;
- duplicate or non-contiguous IDs;
- invalid enum values or non-snake-case template metadata;
- a quota mismatch in tool family, scenario kind, or planned category;
- fewer than two tool families for any non-benign category;
- a normal sample not planned as `benign`;
- a dangerous, boundary, or injection sample planned as `benign`;
- duplicate `(semantic_template, variant)` pairs;
- a mixed sample without at least two declared execution components, or a non-mixed sample with components.

The validator prints a deterministic JSON summary for CI and exits nonzero on any error. It must not import Torch, Transformers, or model files.

## 6. Workflow integration

- Unit tests validate both individual records and the committed 100-row file.
- CI runs the unit tests; no GPU or network access is required.
- README links to the blueprint and its validation command.
- `docs/work_plan.md` marks the 100-sample design and per-language four-kind coverage complete only after the committed manifest passes all tests.

## 7. Acceptance criteria

- Exactly 100 unique, contiguous blueprint rows.
- Exact tool, kind, and category quotas from this specification.
- Every tool family contains normal, dangerous, boundary, and injection cases.
- Every non-benign category spans at least two tool families.
- Every row has a distinct scenario and a unique template/variant pair.
- Validation uses Python standard library plus existing project enums only.
- Full unit suite passes without a model or GPU.
- No model weight, generated command corpus, or final gold label is introduced in this work package.
