import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from guard.p4_adapter_diagnostics import analyze_p4_adapter_report
from guard.eval_freeze import load_resolved_eval_v1
from tests.test_p4_adapter_smoke import write_pilot_artifacts


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY_ROOT / "scripts" / "analyze_p4_adapter_report.py"


def sample(
    sample_id,
    *,
    expected,
    predicted,
    effective_decision,
    effective_correct,
    category_correct,
    high_risk_allow_miss=False,
    repair_attempted=False,
    repair_succeeded=False,
):
    return {
        "sample_id": sample_id,
        "expected": expected,
        "predicted": predicted,
        "effective_decision": effective_decision,
        "effective_decision_correct": effective_correct,
        "category_correct": category_correct,
        "high_risk_allow_miss": high_risk_allow_miss,
        "repair_attempted": repair_attempted,
        "repair_succeeded": repair_succeeded,
    }


def provenance_fixture():
    return {
        "adapter_dir": "/tmp/p4-adapter",
        "adapter_sha256": {
            "adapter_config.json": "a" * 64,
            "adapter_model.safetensors": "b" * 64,
        },
        "base_model_path": "models/base/Qwen2.5-1.5B-Instruct",
        "data_version": "p4-seed-v1",
        "dataset_sha256": {
            "train": "1897e89d11a730ad0922081bda0cf18da3b643a1fc887c2e27abaa7cc5e96208",
            "validation": "c4228d11dd08e8e0cf2a48b01398b5ee0be8a7270a572285e870e74eb939915e",
        },
        "method": "qlora-p4-seed-pilot",
        "training_prompt_version": "baseline-prompt-v2",
        "training_target": "baseline-semantic-v2",
    }


def report_fixture():
    return {
        "report_version": "p4-adapter-eval-report-v1",
        "model_version": "qwen2.5-1.5b-instruct-p4-seed-qlora-pilot-v1",
        "freeze_version": "eval-v1-agent-reviewed-rc1",
        "total_samples": 6,
        "adapter_provenance": provenance_fixture(),
        "category_metrics": {
            "support": {
                "benign": 2,
                "credential_access": 1,
                "destructive_operation": 1,
                "network_change": 1,
                "unsafe_download": 1,
            },
            "precision": {
                "benign": 0.5,
                "credential_access": 1.0,
                "destructive_operation": 0.0,
                "network_change": 0.0,
                "unsafe_download": 0.0,
            },
            "recall": {
                "benign": 0.5,
                "credential_access": 1.0,
                "destructive_operation": 0.0,
                "network_change": 0.0,
                "unsafe_download": 0.0,
            },
            "f1": {
                "benign": 0.5,
                "credential_access": 1.0,
                "destructive_operation": 0.0,
                "network_change": 0.0,
                "unsafe_download": 0.0,
            },
        },
        "samples": [
            sample(
                "EV001",
                expected={
                    "risk": True,
                    "decision": "block",
                    "severity": "critical",
                    "category": "destructive_operation",
                },
                predicted={
                    "risk": False,
                    "decision": "allow",
                    "severity": "none",
                    "category": "benign",
                },
                effective_decision="allow",
                effective_correct=False,
                category_correct=False,
                high_risk_allow_miss=True,
            ),
            sample(
                "EV002",
                expected={
                    "risk": False,
                    "decision": "allow",
                    "severity": "none",
                    "category": "benign",
                },
                predicted={
                    "risk": True,
                    "decision": "review",
                    "severity": "medium",
                    "category": "network_change",
                },
                effective_decision="review",
                effective_correct=False,
                category_correct=False,
            ),
            sample(
                "EV003",
                expected={
                    "risk": True,
                    "decision": "review",
                    "severity": "medium",
                    "category": "network_change",
                },
                predicted={
                    "risk": True,
                    "decision": "review",
                    "severity": "medium",
                    "category": "data_exfiltration",
                },
                effective_decision="review",
                effective_correct=True,
                category_correct=False,
            ),
            sample(
                "EV004",
                expected={
                    "risk": True,
                    "decision": "block",
                    "severity": "high",
                    "category": "unsafe_download",
                },
                predicted=None,
                effective_decision="review",
                effective_correct=False,
                category_correct=None,
                repair_attempted=True,
                repair_succeeded=False,
            ),
            sample(
                "EV005",
                expected={
                    "risk": False,
                    "decision": "allow",
                    "severity": "none",
                    "category": "benign",
                },
                predicted={
                    "risk": False,
                    "decision": "allow",
                    "severity": "none",
                    "category": "benign",
                },
                effective_decision="allow",
                effective_correct=True,
                category_correct=True,
                repair_attempted=True,
                repair_succeeded=True,
            ),
            sample(
                "EV006",
                expected={
                    "risk": True,
                    "decision": "block",
                    "severity": "high",
                    "category": "credential_access",
                },
                predicted={
                    "risk": True,
                    "decision": "block",
                    "severity": "high",
                    "category": "credential_access",
                },
                effective_decision="block",
                effective_correct=True,
                category_correct=True,
            ),
        ],
    }


def expected_samples(report):
    return {
        row["sample_id"]: dict(row["expected"])
        for row in report["samples"]
    }


def full_freeze_report():
    bundle = load_resolved_eval_v1()
    rows = []
    categories = set()
    for record in bundle.records:
        expected = {
            "risk": record.expected.risk,
            "decision": record.expected.decision.value,
            "severity": record.expected.severity.value,
            "category": record.expected.category.value,
        }
        categories.add(record.expected.category.value)
        rows.append(
            sample(
                record.sample_id,
                expected=expected,
                predicted=dict(expected),
                effective_decision=record.expected.decision.value,
                effective_correct=True,
                category_correct=True,
            )
        )
    metrics = {category: 1.0 for category in categories}
    support = {
        category: sum(
            row["expected"]["category"] == category for row in rows
        )
        for category in categories
    }
    report = report_fixture()
    report["total_samples"] = len(rows)
    report["samples"] = rows
    report["category_metrics"] = {
        "support": support,
        "precision": metrics,
        "recall": metrics,
        "f1": metrics,
    }
    return report


class P4AdapterDiagnosticsTests(unittest.TestCase):
    def test_prioritizes_safety_format_benign_and_category_error_samples(self):
        report = report_fixture()
        diagnostics = analyze_p4_adapter_report(
            report,
            expected_freeze_version="eval-v1-agent-reviewed-rc1",
            expected_samples=expected_samples(report),
            expected_adapter_provenance=provenance_fixture(),
        )

        self.assertEqual(diagnostics["high_risk_allow_miss_sample_ids"], ["EV001"])
        self.assertEqual(diagnostics["risk_false_negative_sample_ids"], ["EV001"])
        self.assertEqual(diagnostics["invalid_output_sample_ids"], ["EV004"])
        self.assertEqual(diagnostics["repair_failure_sample_ids"], ["EV004"])
        self.assertEqual(diagnostics["benign_false_positive_sample_ids"], ["EV002"])
        self.assertEqual(
            diagnostics["effective_decision_error_sample_ids"],
            ["EV001", "EV002", "EV004"],
        )
        self.assertEqual(
            diagnostics["category_confusions"],
            {
                "benign->network_change": {"count": 1, "sample_ids": ["EV002"]},
                "destructive_operation->benign": {
                    "count": 1,
                    "sample_ids": ["EV001"],
                },
                "network_change->data_exfiltration": {
                    "count": 1,
                    "sample_ids": ["EV003"],
                },
            },
        )
        self.assertEqual(
            diagnostics["target_priority_sample_ids"],
            ["EV001", "EV004", "EV002", "EV003"],
        )
        self.assertEqual(
            [row["category"] for row in diagnostics["weakest_categories"][:3]],
            ["destructive_operation", "network_change", "unsafe_download"],
        )

    def test_rejects_stale_report_model_or_freeze_provenance(self):
        mutations = (
            ("report_version", "baseline-eval-report-v2.1", "report_version"),
            ("model_version", "base-model", "model_version"),
            ("freeze_version", "stale-freeze", "freeze_version"),
        )
        for field, value, message in mutations:
            with self.subTest(field=field):
                report = report_fixture()
                report[field] = value
                with self.assertRaisesRegex(ValueError, message):
                    analyze_p4_adapter_report(
                        report,
                        expected_freeze_version="eval-v1-agent-reviewed-rc1",
                        expected_samples=expected_samples(report_fixture()),
                        expected_adapter_provenance=provenance_fixture(),
                    )

    def test_rejects_adapter_provenance_drift(self):
        report = report_fixture()
        report["adapter_provenance"]["dataset_sha256"]["train"] = "0" * 64

        with self.assertRaisesRegex(ValueError, "adapter_provenance"):
            analyze_p4_adapter_report(
                report,
                expected_freeze_version="eval-v1-agent-reviewed-rc1",
                expected_samples=expected_samples(report),
                expected_adapter_provenance=provenance_fixture(),
            )

    def test_rejects_missing_duplicate_or_relabelled_freeze_samples(self):
        for mutation, message in (
            ("missing", "sample ID coverage"),
            ("duplicate", "duplicate sample_id"),
            ("relabelled", "expected label"),
        ):
            with self.subTest(mutation=mutation):
                report = report_fixture()
                expected = expected_samples(report)
                if mutation == "missing":
                    report["samples"].pop()
                    report["total_samples"] -= 1
                elif mutation == "duplicate":
                    report["samples"][-1]["sample_id"] = "EV005"
                else:
                    report["samples"][0]["expected"]["category"] = "benign"
                with self.assertRaisesRegex(ValueError, message):
                    analyze_p4_adapter_report(
                        report,
                        expected_freeze_version="eval-v1-agent-reviewed-rc1",
                        expected_samples=expected,
                        expected_adapter_provenance=provenance_fixture(),
                    )

    def test_prioritizes_same_category_decision_errors(self):
        report = report_fixture()
        report["samples"][5]["effective_decision_correct"] = False

        diagnostics = analyze_p4_adapter_report(
            report,
            expected_freeze_version="eval-v1-agent-reviewed-rc1",
            expected_samples=expected_samples(report),
            expected_adapter_provenance=provenance_fixture(),
        )

        self.assertEqual(
            diagnostics["target_priority_sample_ids"],
            ["EV001", "EV004", "EV002", "EV006", "EV003"],
        )

    def test_missing_report_is_single_json_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.json"
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--report", str(missing)],
                cwd=REPOSITORY_ROOT,
                text=True,
                capture_output=True,
            )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stderr, "")
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertIn("No such file", payload["error"])

    def test_cli_emits_diagnostics_for_valid_local_report(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            model = directory / "model"
            model.mkdir()
            adapter_dir = write_pilot_artifacts(directory / "output", model)
            manifest = json.loads(
                (adapter_dir.parent / "training_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            report = full_freeze_report()
            report["adapter_provenance"] = {
                "adapter_dir": str(adapter_dir),
                **{
                    field: manifest[field]
                    for field in (
                        "adapter_sha256",
                        "base_model_path",
                        "data_version",
                        "dataset_sha256",
                        "method",
                        "training_prompt_version",
                        "training_target",
                    )
                },
            }
            path = directory / "report.json"
            path.write_text(
                json.dumps(report),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--report", str(path)],
                cwd=REPOSITORY_ROOT,
                text=True,
                capture_output=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["total_samples"], 100)
        self.assertEqual(payload["high_risk_allow_miss_sample_ids"], [])
        self.assertEqual(payload["target_priority_sample_ids"], [])

    def test_cli_rejects_incomplete_adapter_even_when_reported_hash_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            adapter_dir = directory / "adapter"
            adapter_dir.mkdir()
            adapter_file = adapter_dir / "adapter_model.safetensors"
            adapter_file.write_bytes(b"not a complete adapter")
            report = full_freeze_report()
            report["adapter_provenance"]["adapter_dir"] = str(adapter_dir)
            report["adapter_provenance"]["adapter_sha256"] = {
                adapter_file.name: hashlib.sha256(adapter_file.read_bytes()).hexdigest()
            }
            path = directory / "report.json"
            path.write_text(json.dumps(report), encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--report", str(path)],
                cwd=REPOSITORY_ROOT,
                text=True,
                capture_output=True,
            )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stderr, "")
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertIn("incomplete", payload["error"])

    def test_invalid_cli_argument_is_single_json_error(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--unknown-option"],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stderr, "")
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertIn("unrecognized arguments", payload["error"])


if __name__ == "__main__":
    unittest.main()
