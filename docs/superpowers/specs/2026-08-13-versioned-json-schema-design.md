# Versioned JSON Schema Design

## Goal

Publish machine-readable, versioned JSON Schema artifacts for the Agent Security Guard request and result contracts. The schemas freeze the P1 integration boundary for dataset validation, model-output validation, and non-Python clients.

## Scope

This work package exports the existing Pydantic `GuardRequest` and `GuardResult` contracts as two independent files:

- `schemas/v1/guard-request.schema.json`
- `schemas/v1/guard-result.schema.json`

It also adds a deterministic export command and contract tests. Evaluation samples, prompting, model inference, policy fusion, and runtime JSON repair are outside this work package.

## Architecture

`guard/contracts.py` remains the single source of truth. A focused exporter in `guard/schema_export.py` obtains each model's Pydantic JSON Schema and writes both artifacts. The CLI wrapper `scripts/export_schemas.py` exposes this operation to developers and CI.

Generated files are committed to the repository so JavaScript, Java, Go, data tooling, and other consumers can use the contracts without importing Python or installing Pydantic.

## Public Interface

The exporter provides:

```python
export_schemas(output_dir: Path) -> tuple[Path, Path]
```

The command-line interface defaults to `schemas/v1` and supports an explicit output directory for testing and tooling:

```bash
python scripts/export_schemas.py
python scripts/export_schemas.py --output-dir /tmp/guard-schemas
```

Missing output directories are created automatically. Files are encoded as UTF-8, formatted with two-space indentation and sorted keys, and end with one newline. Repeated export with unchanged contracts must produce byte-identical files.

## Schema Boundaries

The request schema represents `GuardRequest` and includes:

- the five supported tool types;
- a non-empty command with a maximum length of 32,768 characters;
- the structured guard context.

The result schema represents `GuardResult` and includes:

- schema version `1.0`;
- decisions `allow`, `review`, and `block`;
- the stable severity and risk-category enums;
- summary length from 1 through 30 characters;
- confidence from 0.0 through 1.0;
- evidence and version fields.

Pydantic validators that cannot be fully represented by generated JSON Schema remain enforced at Python runtime. In particular, whitespace-only strings are rejected by Pydantic validators; JSON Schema communicates the structural length constraints generated from the fields.

## Data Flow

1. A developer changes a Pydantic contract in `guard/contracts.py` or an enum in `guard/taxonomy.py`.
2. The export command derives both schemas from the current Python definitions.
3. The command writes deterministic artifacts under `schemas/v1`.
4. Tests regenerate schemas in a temporary directory and compare their bytes with the committed artifacts.
5. CI fails when contract code and committed schemas differ.

## Error Handling

Filesystem errors and Pydantic schema-generation errors are not hidden. The CLI exits non-zero and preserves the underlying exception so CI and developers receive an actionable failure. The exporter never loads model weights, imports Transformers, or requires CUDA.

Each file is serialized completely before it is written. This work package does not add cross-file transactional replacement; if a write fails, rerunning the deterministic exporter safely restores both artifacts.

## Testing

Tests use `unittest` and temporary directories, matching the repository's current test style. They verify:

- both files are created in a missing output directory;
- repeated exports are byte-identical;
- generated artifacts match the committed files exactly;
- request tool types and command length constraints are present;
- result schema version, decisions, all 12 categories, confidence bounds, and summary bounds are present;
- the full existing test suite remains independent of model weights and GPU hardware.

## Acceptance Criteria

- Both versioned schema files are committed under `schemas/v1`.
- `python scripts/export_schemas.py` succeeds and is idempotent.
- The committed files exactly match schemas generated from the current Pydantic models.
- All existing and new `unittest` tests pass on Python 3.10 and 3.12.
- No model, Transformers, PyTorch, or CUDA dependency is introduced into schema export or its tests.
