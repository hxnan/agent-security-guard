# P4 Seed Dataset V1 Design

## Scope and measured motivation

P4 Seed Dataset V1 is the first committed formal training-data batch. It
contains 1,000 records and is generated without model weights, GPU access, or
Eval labels. It builds on the strict P4 quality gate already merged on `main`.

The dataset priorities come from measured behavior rather than benchmark IDs:

- Model-only V2.1 category Macro-F1 was 0.132 and valid output rate was 0.54.
- Fusion V1 category Macro-F1 is 0.238 and valid output rate is 0.56.
- Fusion still has 20 benign false positives and 44 fallback outcomes.
- Rules-only and Fusion both have zero high-risk allow misses and zero rule
  errors.

The first seed therefore emphasizes ordinary benign operations, taxonomy
separation, boundary cases, and exact GuardResult contract learning. It does
not expand the production rule registry or copy any Eval request or label.

## Dataset shape

The committed corpus has exactly 1,000 records:

- 100 curated semantic clusters;
- 10 deterministic request variants per cluster;
- 80 train-only clusters and 20 validation-only clusters;
- 800 train rows and 200 validation rows;
- 10 generation batches of 100 rows.

Semantic clusters, not individual rows, own the split. A semantic template can
appear in only one split. The 80/20 ratio is therefore enforced at cluster
level and row level.

The category profile is fixed at cluster level:

| Category | Clusters | Rows |
| --- | ---: | ---: |
| benign | 30 | 300 |
| remote_execution | 8 | 80 |
| unsafe_download | 8 | 80 |
| each other non-benign category | 6 | 60 |

All five tool types and all four scenario kinds (`normal`, `dangerous`,
`boundary`, `injection`) must occur in the corpus. Benign rows include
read-only repository inspection, bounded search, checksums, package metadata,
service status, and compilation/test commands. Risky clusters cover all eleven
non-benign taxonomy categories with both obvious and boundary-shaped behavior.

## Curated catalog and deterministic expansion

`training.seed_catalog` owns the curated cluster definitions. A cluster fixes:

- category, decision, severity, Chinese summary, and confidence;
- split, semantic-template identifier, tool type, and scenario kind;
- a side-effect-free command-rendering function driven only by variant 1–10;
- stable context fields that explain the intended semantics.

`training.seed_dataset` validates the catalog and expands it. Variant values
change inert names, paths, hosts, ports, package names, or project names. The
generator never executes a command and never reads Eval files. Stable IDs are
assigned as `TR-000001` through `TR-001000` in catalog and variant order.

Every output is a complete GuardResult V1. Labels come only from the curated
cluster definition and taxonomy defaults; they are not inferred from Eval.
Evidence contains the generated command. `rule_hits` is empty because these
are training targets, not runtime rule decisions.

## Provenance and batches

Training metadata extends the existing strict contract with:

- `scenario_kind`;
- `batch_id` in the form `p4-seed-v1-batch-NNN`;
- `generator_version=p4-seed-generator-v1`.

The existing `data_version`, `generation_source`, `semantic_template`, and
`split` fields remain required. `generation_source` is
`curated_scenario_catalog_v1`.

The committed manifest records exact counts, category/split/tool/scenario
distributions, generator version, batch size, batch IDs, output paths, and
SHA-256 hashes. It contains no claim of human review and no Eval provenance.

## CLI and files

`scripts/prepare_training_data.py` writes:

- `data/train/agent_security_train_v1.jsonl`;
- `data/val/agent_security_validation_v1.jsonl`;
- `data/train/agent_security_seed_v1_manifest.json`.

The CLI defaults to repository paths, refuses to overwrite existing files
without `--force`, writes canonical deterministic JSONL, loads frozen Eval V1
only after generation to compute request fingerprints, and runs the existing
bundle quality gate before finalizing outputs. Expected failures produce one
JSON error object and exit 1 without a traceback.

## Validation and acceptance

Unit and committed-data tests require:

1. exactly 1,000 unique IDs and requests;
2. 800/200 rows with disjoint semantic templates;
3. exact category quotas and coverage of every tool/scenario kind;
4. exactly ten 100-row batch IDs;
5. deterministic byte-identical regeneration and manifest hashes;
6. every row passes `TrainingExample` and semantic label checks;
7. the existing cross-split and frozen-Eval leakage gate returns `status=ok`;
8. overwrite refusal and deterministic JSON CLI errors;
9. no changes under `data/eval-v1/**`, `schemas/v1/**`, model, or artifact paths.

P4 Seed V1 is not the final 5,000–10,000 corpus and is not sufficient by itself
to authorize P5. After this seed is generated and reviewed, the same catalog
and gates can be expanded in independently versioned 500–1,000-row batches.
