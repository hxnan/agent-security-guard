import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


def valid_record(**overrides):
    record = {
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
        "authoring_status": "planned",
    }
    record.update(overrides)
    return record


TOOL_KIND_LAYOUT = [
    ("shell", "shell", {"normal": 12, "dangerous": 10, "boundary": 5, "injection": 3}),
    ("powershell", "powershell", {"normal": 8, "dangerous": 7, "boundary": 3, "injection": 2}),
    ("cmd", "cmd", {"normal": 4, "dangerous": 3, "boundary": 2, "injection": 1}),
    ("python", "python", {"normal": 12, "dangerous": 10, "boundary": 5, "injection": 3}),
    ("mixed", "shell", {"normal": 4, "dangerous": 4, "boundary": 1, "injection": 1}),
]
RISK_CATEGORY_COUNTS = [
    ("remote_execution", 8),
    ("privilege_escalation", 5),
    ("destructive_operation", 7),
    ("credential_access", 5),
    ("data_exfiltration", 6),
    ("persistence", 5),
    ("defense_evasion", 5),
    ("unsafe_download", 5),
    ("network_change", 5),
    ("sensitive_write", 5),
    ("resource_abuse", 4),
]


def synthetic_raw_records():
    remaining = dict(RISK_CATEGORY_COUNTS)
    category_order = [name for name, _ in RISK_CATEGORY_COUNTS]
    risky_categories = []
    while remaining:
        for category in category_order:
            if category not in remaining:
                continue
            risky_categories.append(category)
            remaining[category] -= 1
            if remaining[category] == 0:
                del remaining[category]

    rows = []
    risky_index = 0
    for tool_family, request_type, kind_counts in TOOL_KIND_LAYOUT:
        for scenario_kind, count in kind_counts.items():
            for _ in range(count):
                number = len(rows) + 1
                category = "benign"
                if scenario_kind != "normal":
                    category = risky_categories[risky_index]
                    risky_index += 1
                rows.append(
                    valid_record(
                        sample_id=f"EV{number:03d}",
                        tool_family=tool_family,
                        request_type=request_type,
                        scenario_kind=scenario_kind,
                        planned_category=category,
                        scenario=f"Synthetic scenario {number}",
                        semantic_template=f"synthetic_{number:03d}",
                        variant=f"variant_{number:03d}",
                        risk_factors=[] if category == "benign" else [category],
                        mixed_components=(
                            ["shell", "python"] if tool_family == "mixed" else []
                        ),
                    )
                )
    return rows


def parsed_synthetic_records(api):
    return [
        api.BlueprintRecord.from_dict(row, line_number=index)
        for index, row in enumerate(synthetic_raw_records(), start=1)
    ]


class BlueprintRecordTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module("guard.eval_blueprint")
        except ModuleNotFoundError:
            self.fail("guard.eval_blueprint is missing")

    def assert_invalid(self, value, field):
        api = self.api()
        with self.assertRaisesRegex(api.BlueprintValidationError, field):
            api.BlueprintRecord.from_dict(value, line_number=7)

    def test_parses_valid_record_into_enum_backed_fields(self):
        api = self.api()

        record = api.BlueprintRecord.from_dict(valid_record(), line_number=1)

        self.assertEqual(record.sample_id, "EV001")
        self.assertEqual(record.tool_family, api.ToolFamily.SHELL)
        self.assertEqual(record.request_type.value, "shell")
        self.assertEqual(record.scenario_kind, api.ScenarioKind.NORMAL)
        self.assertEqual(record.planned_category.value, "benign")
        self.assertEqual(record.risk_factors, ())
        self.assertEqual(record.required_context, ("cwd_inside_workspace",))
        self.assertEqual(record.mixed_components, ())

    def test_rejects_unknown_field(self):
        self.assert_invalid(valid_record(unexpected=True), "unexpected")

    def test_rejects_non_contiguous_sample_id_shape(self):
        self.assert_invalid(valid_record(sample_id="EV1"), "sample_id")

    def test_rejects_non_snake_case_metadata(self):
        self.assert_invalid(
            valid_record(semantic_template="Repo-Status"),
            "semantic_template",
        )

    def test_rejects_blank_scenario(self):
        self.assert_invalid(valid_record(scenario="   "), "scenario")

    def test_rejects_duplicate_risk_factors(self):
        self.assert_invalid(
            valid_record(risk_factors=["remote_source", "remote_source"]),
            "risk_factors",
        )

    def test_rejects_mixed_record_with_one_component(self):
        self.assert_invalid(
            valid_record(
                tool_family="mixed",
                mixed_components=["shell"],
            ),
            "mixed_components",
        )

    def test_rejects_mixed_record_without_entrypoint_component(self):
        self.assert_invalid(
            valid_record(
                tool_family="mixed",
                request_type="shell",
                mixed_components=["python", "tool"],
            ),
            "request_type",
        )

    def test_rejects_components_on_single_family_record(self):
        self.assert_invalid(
            valid_record(mixed_components=["shell", "python"]),
            "mixed_components",
        )

    def test_rejects_request_type_that_disagrees_with_single_family(self):
        self.assert_invalid(valid_record(request_type="python"), "request_type")


class BlueprintDatasetTests(unittest.TestCase):
    def setUp(self):
        self.api = importlib.import_module("guard.eval_blueprint")
        for name in ("load_blueprint", "validate_blueprint", "BlueprintSummary"):
            if not hasattr(self.api, name):
                self.fail(f"guard.eval_blueprint.{name} is missing")

    def test_validates_exact_quota_fixture_and_returns_literal_summary(self):
        summary = self.api.validate_blueprint(parsed_synthetic_records(self.api))

        self.assertEqual(
            summary.to_dict(),
            {
                "categories": {
                    "benign": 40,
                    "credential_access": 5,
                    "data_exfiltration": 6,
                    "defense_evasion": 5,
                    "destructive_operation": 7,
                    "network_change": 5,
                    "persistence": 5,
                    "privilege_escalation": 5,
                    "remote_execution": 8,
                    "resource_abuse": 4,
                    "sensitive_write": 5,
                    "unsafe_download": 5,
                },
                "scenario_kinds": {
                    "boundary": 16,
                    "dangerous": 34,
                    "injection": 10,
                    "normal": 40,
                },
                "tool_families": {
                    "cmd": 10,
                    "mixed": 10,
                    "powershell": 20,
                    "python": 30,
                    "shell": 30,
                },
                "total": 100,
            },
        )

    def assert_dataset_invalid(self, rows, pattern):
        records = [
            self.api.BlueprintRecord.from_dict(row, line_number=index)
            for index, row in enumerate(rows, start=1)
        ]
        with self.assertRaisesRegex(self.api.BlueprintValidationError, pattern):
            self.api.validate_blueprint(records)

    def test_rejects_duplicate_sample_ids(self):
        rows = synthetic_raw_records()
        rows[1]["sample_id"] = "EV001"
        self.assert_dataset_invalid(rows, "duplicate sample_id")

    def test_rejects_non_contiguous_sample_ids(self):
        rows = synthetic_raw_records()
        rows[-1]["sample_id"] = "EV101"
        self.assert_dataset_invalid(rows, "contiguous")

    def test_rejects_duplicate_template_variant_pair(self):
        rows = synthetic_raw_records()
        rows[1]["semantic_template"] = rows[0]["semantic_template"]
        rows[1]["variant"] = rows[0]["variant"]
        self.assert_dataset_invalid(rows, "semantic_template.*variant")

    def test_rejects_duplicate_scenario_text(self):
        rows = synthetic_raw_records()
        rows[1]["scenario"] = rows[0]["scenario"]
        self.assert_dataset_invalid(rows, "duplicate scenario")

    def test_rejects_tool_quota_drift(self):
        rows = synthetic_raw_records()
        rows[0]["tool_family"] = "python"
        rows[0]["request_type"] = "python"
        self.assert_dataset_invalid(rows, "tool_family quota")

    def test_rejects_quota_preserving_cross_family_kind_swap(self):
        rows = synthetic_raw_records()
        shell_normal = rows[0]
        python_dangerous = next(
            row
            for row in rows
            if row["tool_family"] == "python"
            and row["scenario_kind"] == "dangerous"
        )
        shell_normal["tool_family"] = "python"
        shell_normal["request_type"] = "python"
        python_dangerous["tool_family"] = "shell"
        python_dangerous["request_type"] = "shell"

        self.assert_dataset_invalid(rows, "tool_family/scenario_kind quota")

    def test_rejects_normal_record_with_non_benign_category(self):
        rows = synthetic_raw_records()
        rows[0]["planned_category"] = "unsafe_download"
        self.assert_dataset_invalid(rows, "normal.*benign")

    def test_rejects_risky_record_with_benign_category(self):
        rows = synthetic_raw_records()
        first_risky = next(
            index for index, row in enumerate(rows) if row["scenario_kind"] != "normal"
        )
        rows[first_risky]["planned_category"] = "benign"
        self.assert_dataset_invalid(rows, "non-normal.*non-benign")

    def test_rejects_category_limited_to_one_tool_family(self):
        rows = synthetic_raw_records()
        for row in rows:
            if row["planned_category"] == "resource_abuse":
                row["tool_family"] = "shell"
                row["request_type"] = "shell"
                row["mixed_components"] = []
        self.assert_dataset_invalid(rows, "resource_abuse.*two tool families")

    def test_rejects_tool_family_missing_a_scenario_kind(self):
        rows = synthetic_raw_records()
        cmd_injection = next(
            row
            for row in rows
            if row["tool_family"] == "cmd" and row["scenario_kind"] == "injection"
        )
        cmd_injection["scenario_kind"] = "dangerous"
        self.assert_dataset_invalid(rows, "cmd.*injection")

    def test_load_blueprint_reports_malformed_json_line(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "bad.jsonl"
            path.write_text(
                json.dumps(valid_record()) + '\n{"broken":\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                self.api.BlueprintValidationError,
                "line 2.*invalid JSON",
            ):
                self.api.load_blueprint(path)


class BlueprintCliTests(unittest.TestCase):
    repository_root = Path(__file__).resolve().parents[1]
    script_path = repository_root / "scripts" / "validate_eval_blueprint.py"

    def run_cli(self, path):
        return subprocess.run(
            [sys.executable, str(self.script_path), str(path)],
            cwd=self.repository_root,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_valid_blueprint_prints_parseable_summary(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "valid.jsonl"
            path.write_text(
                "".join(
                    json.dumps(row, sort_keys=True) + "\n"
                    for row in synthetic_raw_records()
                ),
                encoding="utf-8",
            )

            result = self.run_cli(path)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["total"], 100)
        self.assertEqual(result.stderr, "")

    def test_invalid_blueprint_exits_two_with_line_number(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "invalid.jsonl"
            path.write_text("{not-json}\n", encoding="utf-8")

            result = self.run_cli(path)

        self.assertEqual(result.returncode, 2)
        self.assertRegex(result.stderr, r"line 1.*invalid JSON")
        self.assertEqual(result.stdout, "")

    def test_missing_blueprint_exits_two_without_traceback(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "missing.jsonl"

            result = self.run_cli(path)

        self.assertEqual(result.returncode, 2)
        self.assertRegex(result.stderr, r"unable to read blueprint.*missing\.jsonl")
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(result.stdout, "")


class CommittedBlueprintTests(unittest.TestCase):
    blueprint_path = (
        Path(__file__).resolve().parents[1] / "data" / "eval-v1" / "blueprint.jsonl"
    )

    def test_committed_blueprint_meets_all_quotas_and_uniqueness_rules(self):
        api = importlib.import_module("guard.eval_blueprint")
        self.assertTrue(self.blueprint_path.exists(), "committed blueprint is missing")

        records = api.load_blueprint(self.blueprint_path)
        summary = api.validate_blueprint(records)

        self.assertEqual(summary.total, 100)
        self.assertEqual(len({record.scenario for record in records}), 100)
        for category in api.RiskCategory:
            if category is api.RiskCategory.BENIGN:
                continue
            families = {
                record.tool_family
                for record in records
                if record.planned_category is category
            }
            self.assertGreaterEqual(len(families), 2, category.value)


if __name__ == "__main__":
    unittest.main()
