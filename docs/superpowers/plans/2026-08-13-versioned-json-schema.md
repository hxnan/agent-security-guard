# Versioned JSON Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export the `GuardRequest` and `GuardResult` Pydantic contracts as deterministic, committed JSON Schema V1 artifacts with automatic drift detection.

**Architecture:** Keep `guard/contracts.py` as the only contract source. Add a small `guard.schema_export` module that serializes Pydantic-generated schemas deterministically, a CLI wrapper for developers and CI, and `unittest` coverage that exercises real filesystem output and compares it with committed artifacts.

**Tech Stack:** Python 3.10+, Pydantic 2.x, standard-library `argparse`, `json`, `pathlib`, `tempfile`, and `unittest`.

## Global Constraints

- Publish two independent files: `schemas/v1/guard-request.schema.json` and `schemas/v1/guard-result.schema.json`.
- Serialize UTF-8 JSON with two-space indentation, sorted keys, and exactly one trailing newline.
- Repeated exports from unchanged contracts must be byte-identical.
- Create a missing output directory automatically.
- Do not import or require model weights, Transformers, PyTorch, or CUDA.
- Keep evaluation data, prompts, inference, policy fusion, and JSON repair outside this work package.
- Retain Python 3.10 and 3.12 compatibility and the repository's `unittest` test style.

---

## File Structure

- Create `guard/schema_export.py`: deterministic schema serialization and the `export_schemas` public function.
- Create `scripts/export_schemas.py`: command-line wrapper with the repository-relative default output directory.
- Create `tests/test_schema_export.py`: exporter, schema-boundary, idempotence, and drift-detection tests.
- Create `schemas/v1/guard-request.schema.json`: committed generated request contract.
- Create `schemas/v1/guard-result.schema.json`: committed generated result contract.
- Modify `README.md`: document the artifacts, export command, and drift behavior.
- Modify `.github/workflows/ci.yml`: run the exporter and require a clean Git diff after unit tests.

### Task 1: Deterministic schema exporter

**Files:**

- Create: `guard/schema_export.py`
- Create: `tests/test_schema_export.py`

**Interfaces:**

- Consumes: `GuardRequest.model_json_schema()` and `GuardResult.model_json_schema()`.
- Produces: `export_schemas(output_dir: Path) -> tuple[Path, Path]`.
- Produces files named `guard-request.schema.json` and `guard-result.schema.json` below `output_dir`.

- [ ] **Step 1: Write the failing filesystem behavior test**

Create `tests/test_schema_export.py` with a test that names the production break: failing to create a missing directory, returning paths in the wrong order, or producing nondeterministic bytes.

```python
import importlib
import tempfile
import unittest
from pathlib import Path


class SchemaExportTests(unittest.TestCase):
    def test_export_creates_both_deterministic_files(self):
        try:
            schema_export = importlib.import_module("guard.schema_export")
        except ModuleNotFoundError:
            self.fail("guard.schema_export is not implemented")

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "missing" / "v1"

            first_paths = schema_export.export_schemas(output_dir)
            first_bytes = tuple(path.read_bytes() for path in first_paths)
            second_paths = schema_export.export_schemas(output_dir)
            second_bytes = tuple(path.read_bytes() for path in second_paths)

        self.assertEqual(
            first_paths,
            (
                output_dir / "guard-request.schema.json",
                output_dir / "guard-result.schema.json",
            ),
        )
        self.assertEqual(first_paths, second_paths)
        self.assertEqual(first_bytes, second_bytes)
        self.assertTrue(all(content.endswith(b"\n") for content in first_bytes))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
python -m unittest tests.test_schema_export.SchemaExportTests.test_export_creates_both_deterministic_files -v
```

Expected: `FAIL` with `guard.schema_export is not implemented`. This proves the assertion fails at the missing production boundary rather than crashing during test discovery.

- [ ] **Step 3: Implement the minimal exporter**

Create `guard/schema_export.py`:

```python
"""Deterministic JSON Schema export for public guard contracts."""

import json
from pathlib import Path

from .contracts import GuardRequest, GuardResult


SCHEMA_FILES = (
    ("guard-request.schema.json", GuardRequest),
    ("guard-result.schema.json", GuardResult),
)


def _serialized_schema(model: type[GuardRequest] | type[GuardResult]) -> str:
    return json.dumps(
        model.model_json_schema(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def export_schemas(output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for filename, model in SCHEMA_FILES:
        path = output_dir / filename
        path.write_text(_serialized_schema(model), encoding="utf-8")
        paths.append(path)
    return paths[0], paths[1]
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```bash
python -m unittest tests.test_schema_export.SchemaExportTests.test_export_creates_both_deterministic_files -v
```

Expected: one test passes.

- [ ] **Step 5: Add failing semantic-boundary tests**

After the first GREEN run, replace the dynamic import with `from guard.schema_export import export_schemas`, update the first test to call `export_schemas`, and extend `tests/test_schema_export.py` with literal, hand-derived expectations. These tests catch wrong model selection, missing constraints, or incomplete enum export without recomputing expectations through the production code.

```python
import json

# Add inside SchemaExportTests.
def test_request_schema_contains_tool_and_command_contract(self):
    with tempfile.TemporaryDirectory() as temporary_directory:
        request_path, _ = export_schemas(Path(temporary_directory))
        schema = json.loads(request_path.read_text(encoding="utf-8"))

    self.assertEqual(
        schema["$defs"]["ToolType"]["enum"],
        ["shell", "powershell", "cmd", "python", "tool"],
    )
    self.assertEqual(schema["properties"]["command"]["minLength"], 1)
    self.assertEqual(schema["properties"]["command"]["maxLength"], 32768)
    self.assertEqual(schema["required"], ["type", "command"])

def test_result_schema_contains_version_and_risk_contract(self):
    with tempfile.TemporaryDirectory() as temporary_directory:
        _, result_path = export_schemas(Path(temporary_directory))
        schema = json.loads(result_path.read_text(encoding="utf-8"))

    self.assertEqual(
        schema["$defs"]["Decision"]["enum"],
        ["allow", "review", "block"],
    )
    self.assertEqual(
        schema["$defs"]["RiskCategory"]["enum"],
        [
            "remote_execution",
            "privilege_escalation",
            "destructive_operation",
            "credential_access",
            "data_exfiltration",
            "persistence",
            "defense_evasion",
            "unsafe_download",
            "network_change",
            "sensitive_write",
            "resource_abuse",
            "benign",
        ],
    )
    self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0")
    self.assertEqual(schema["properties"]["confidence"]["minimum"], 0.0)
    self.assertEqual(schema["properties"]["confidence"]["maximum"], 1.0)
    self.assertEqual(schema["properties"]["summary"]["minLength"], 1)
    self.assertEqual(schema["properties"]["summary"]["maxLength"], 30)
```

- [ ] **Step 6: Run the semantic tests and verify their result**

Run:

```bash
python -m unittest tests.test_schema_export -v
```

Expected: three tests pass. If one fails, make only the smallest exporter correction needed; do not change the approved Pydantic contracts to fit the exporter tests.

- [ ] **Step 7: Run the full regression suite**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: the existing 14 tests plus the 3 exporter tests pass.

- [ ] **Step 8: Commit Task 1**

```bash
git add guard/schema_export.py tests/test_schema_export.py
git commit -m "feat: add deterministic schema exporter"
```

### Task 2: Command-line export and committed V1 artifacts

**Files:**

- Create: `scripts/export_schemas.py`
- Modify: `tests/test_schema_export.py`
- Create: `schemas/v1/guard-request.schema.json`
- Create: `schemas/v1/guard-result.schema.json`

**Interfaces:**

- Consumes: `export_schemas(output_dir: Path) -> tuple[Path, Path]` from Task 1.
- Produces: CLI `python scripts/export_schemas.py [--output-dir PATH]` with a default of `<repository>/schemas/v1`.
- Produces: exit code `0` on success; filesystem and schema-generation exceptions remain visible and yield a non-zero exit.

- [ ] **Step 1: Write the failing CLI behavior test**

Add imports to `tests/test_schema_export.py`:

```python
import subprocess
import sys
```

Add a test that runs the real script and asserts its filesystem effect:

```python
def test_cli_exports_to_explicit_output_directory(self):
    repository_root = Path(__file__).resolve().parents[1]
    script = repository_root / "scripts" / "export_schemas.py"
    with tempfile.TemporaryDirectory() as temporary_directory:
        output_dir = Path(temporary_directory) / "schemas"
        completed = subprocess.run(
            [sys.executable, str(script), "--output-dir", str(output_dir)],
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
        )

        generated_names = sorted(path.name for path in output_dir.glob("*.json"))

    self.assertEqual(completed.returncode, 0, completed.stderr)
    self.assertEqual(
        generated_names,
        ["guard-request.schema.json", "guard-result.schema.json"],
    )
```

- [ ] **Step 2: Run the CLI test and verify RED**

Run:

```bash
python -m unittest tests.test_schema_export.SchemaExportTests.test_cli_exports_to_explicit_output_directory -v
```

Expected: `FAIL` because `scripts/export_schemas.py` does not exist and the subprocess returns a non-zero exit code.

- [ ] **Step 3: Implement the minimal CLI**

Create `scripts/export_schemas.py`:

```python
#!/usr/bin/env python3
"""Export the versioned public JSON Schema artifacts."""

import argparse
from pathlib import Path
from typing import Sequence

from guard.schema_export import export_schemas


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "schemas" / "v1"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    export_schemas(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the CLI test and verify GREEN**

Run:

```bash
python -m unittest tests.test_schema_export.SchemaExportTests.test_cli_exports_to_explicit_output_directory -v
```

Expected: one test passes.

- [ ] **Step 5: Write the failing drift-detection test**

Add this test before staging the generated files. It compares independent byte output from a temporary directory with the repository artifacts:

```python
def test_committed_schemas_match_current_contracts(self):
    repository_root = Path(__file__).resolve().parents[1]
    committed_dir = repository_root / "schemas" / "v1"
    names = (
        "guard-request.schema.json",
        "guard-result.schema.json",
    )
    with tempfile.TemporaryDirectory() as temporary_directory:
        generated_paths = export_schemas(Path(temporary_directory))
        generated = {path.name: path.read_bytes() for path in generated_paths}

    for name in names:
        self.assertTrue((committed_dir / name).is_file(), f"missing committed schema: {name}")
    committed = {
        name: (committed_dir / name).read_bytes()
        for name in names
    }
    self.assertEqual(committed, generated)
```

- [ ] **Step 6: Run the drift test and verify RED**

Run:

```bash
python -m unittest tests.test_schema_export.SchemaExportTests.test_committed_schemas_match_current_contracts -v
```

Expected: `FAIL` with `missing committed schema: guard-request.schema.json`. The missing artifact is the behavior this test requires Task 2 to add.

- [ ] **Step 7: Generate the committed artifacts and verify GREEN**

Run:

```bash
python scripts/export_schemas.py
python -m unittest tests.test_schema_export.SchemaExportTests.test_committed_schemas_match_current_contracts -v
```

Expected: both JSON files appear under `schemas/v1`, the focused test passes, and neither command output nor imports mention model, Transformers, PyTorch, or CUDA.

- [ ] **Step 8: Mutation-check drift detection**

Temporarily append one newline to `schemas/v1/guard-request.schema.json`, run the focused test, and confirm it fails with a byte mismatch. Restore the generated file by rerunning the exporter, then rerun:

```bash
python scripts/export_schemas.py
python -m unittest tests.test_schema_export.SchemaExportTests.test_committed_schemas_match_current_contracts -v
```

Expected: the mutation check fails; after regeneration, one test passes.

- [ ] **Step 9: Run all schema and regression tests**

Run:

```bash
python -m unittest tests.test_schema_export -v
python -m unittest discover -s tests -v
```

Expected: 5 schema-export tests pass and the full suite has 19 passing tests.

- [ ] **Step 10: Commit Task 2**

```bash
git add scripts/export_schemas.py tests/test_schema_export.py schemas/v1
git commit -m "feat: publish JSON Schema v1 artifacts"
```

### Task 3: CI drift gate and developer documentation

**Files:**

- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`

**Interfaces:**

- Consumes: default CLI from Task 2.
- Produces: CI failure when exporting current contracts changes either committed schema.
- Produces: developer instructions for locating and regenerating V1 schemas.

- [ ] **Step 1: Add the CI drift gate**

After the unit-test step in `.github/workflows/ci.yml`, add:

```yaml
      - run: python scripts/export_schemas.py
      - run: git diff --exit-code -- schemas/v1
```

This exercises the real exporter and fails if generated output differs from committed artifacts.

- [ ] **Step 2: Document schema use and regeneration**

In `README.md`, add a concise `JSON Schema` section after the data-contract example. It must identify both files, state that Pydantic is the source of truth, and show:

```bash
python scripts/export_schemas.py
git diff -- schemas/v1
```

Also add `schemas/` to the directory overview as the language-neutral V1 request/result contracts.

- [ ] **Step 3: Verify exporter idempotence and clean artifacts**

Run:

```bash
python scripts/export_schemas.py
git diff --exit-code -- schemas/v1
```

Expected: both commands exit `0` and the diff is empty.

- [ ] **Step 4: Run the full local acceptance suite**

Run:

```bash
python -m unittest discover -s tests -v
python scripts/export_schemas.py
git diff --exit-code -- schemas/v1
python - <<'PY'
import json
from pathlib import Path

for path in sorted(Path("schemas/v1").glob("*.json")):
    with path.open(encoding="utf-8") as stream:
        json.load(stream)
    print(f"VALID_JSON {path}")
PY
```

Expected: 19 tests pass, schema diff is empty, and both files print `VALID_JSON`.

- [ ] **Step 5: Review the final diff for scope**

Run:

```bash
git status --short
git diff --check
git diff --stat
git diff
```

Expected: only `.github/workflows/ci.yml` and `README.md` remain unstaged for Task 3; no model files, runtime dependencies, evaluation data, prompt, inference, or policy code appears.

- [ ] **Step 6: Commit Task 3**

```bash
git add .github/workflows/ci.yml README.md
git commit -m "ci: verify committed JSON Schemas"
```

- [ ] **Step 7: Run fresh completion verification**

Run:

```bash
python -m unittest discover -s tests -v
python scripts/export_schemas.py
git diff --exit-code -- schemas/v1
git status --short --branch
```

Expected: 19 tests pass, schema diff is empty, and the worktree is clean before publication.
