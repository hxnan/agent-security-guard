import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from guard.schema_export import export_schemas


class SchemaExportTests(unittest.TestCase):
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

    def test_cli_uses_repository_default_from_another_working_directory(self):
        repository_root = Path(__file__).resolve().parents[1]
        script = repository_root / "scripts" / "export_schemas.py"
        committed_dir = repository_root / "schemas" / "v1"
        names = (
            "guard-request.schema.json",
            "guard-result.schema.json",
        )
        committed_paths = {name: committed_dir / name for name in names}
        original = {name: path.read_bytes() for name, path in committed_paths.items()}

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            try:
                completed = subprocess.run(
                    [sys.executable, str(script)],
                    cwd=temporary_path,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                generated = {
                    name: path.read_bytes()
                    for name, path in committed_paths.items()
                }
                wrote_to_working_directory = (temporary_path / "schemas").exists()
            finally:
                for name, path in committed_paths.items():
                    path.write_bytes(original[name])

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(generated, original)
        self.assertFalse(wrote_to_working_directory)

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

    def test_export_creates_both_deterministic_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "missing" / "v1"

            first_paths = export_schemas(output_dir)
            first_bytes = tuple(path.read_bytes() for path in first_paths)
            second_paths = export_schemas(output_dir)
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
        for content in first_bytes:
            self.assertEqual(len(content) - len(content.rstrip(b"\n")), 1)
            self.assertFalse(content.endswith(b"\r\n"))

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


if __name__ == "__main__":
    unittest.main()
