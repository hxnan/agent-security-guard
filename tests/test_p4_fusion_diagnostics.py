import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from guard.eval_freeze import load_resolved_eval_v1
from guard.p4_adapter_backend import P4_COMBINED_ADAPTER_MODEL_VERSION
from guard.p4_adapter_diagnostics import analyze_p4_fusion_report
from guard.p4_qlora import EXPECTED_P4_COMBINED_SHA256
from guard.taxonomy import RiskCategory
from tests.test_p4_adapter_diagnostics import combined_provenance_fixture
from tests.test_p4_adapter_smoke import write_pilot_artifacts


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY_ROOT / "scripts" / "analyze_p4_fusion_report.py"


def predicted(*, risk, decision, severity, category, model_version=None, rule_hits=None):
    return {
        "schema_version": "1.0",
        "risk": risk,
        "decision": decision,
        "severity": severity,
        "category": category,
        "summary": "融合诊断样本",
        "confidence": 1.0,
        "evidence": ["fixture"],
        "rule_hits": rule_hits or [],
        "model_version": model_version or P4_COMBINED_ADAPTER_MODEL_VERSION,
        "policy_version": "fusion-v1",
    }


def sample(
    sample_id,
    *,
    expected,
    predicted_result,
    source="model",
    effective_decision=None,
    model_invoked=True,
    selected_rule_id=None,
    rule_errors=None,
    repair_attempted=False,
    repair_succeeded=False,
):
    return {
        "sample_id": sample_id,
        "expected": expected,
        "source": source,
        "status": "ok" if predicted_result is not None else "parse_error",
        "predicted": predicted_result,
        "fallback_decision": "review" if predicted_result is None else None,
        "effective_decision": effective_decision or (
            predicted_result["decision"] if predicted_result is not None else "review"
        ),
        "matched_rule_ids": [selected_rule_id] if selected_rule_id else [],
        "selected_rule_id": selected_rule_id,
        "rule_errors": rule_errors or [],
        "model_invoked": model_invoked,
        "model_repair_attempted": repair_attempted,
        "model_repair_succeeded": repair_succeeded,
        "decision_correct": (
            predicted_result["decision"] == expected["decision"]
            if predicted_result is not None
            else None
        ),
        "category_correct": (
            predicted_result["category"] == expected["category"]
            if predicted_result is not None
            else None
        ),
        "effective_decision_correct": (
            effective_decision
            or (predicted_result["decision"] if predicted_result else "review")
        )
        == expected["decision"],
        "latency_seconds": 0.1,
        "model_elapsed_seconds": 0.1 if model_invoked else None,
        "generated_tokens": 10 if model_invoked else 0,
        "peak_gpu_memory_mb": 100.0 if model_invoked else None,
    }


def report_fixture():
    rows = [
        sample(
            "EV001",
            expected={
                "risk": True,
                "decision": "block",
                "severity": "critical",
                "category": "destructive_operation",
            },
            predicted_result=predicted(
                risk=False,
                decision="allow",
                severity="none",
                category="benign",
            ),
        ),
        sample(
            "EV002",
            expected={
                "risk": False,
                "decision": "allow",
                "severity": "none",
                "category": "benign",
            },
            predicted_result=predicted(
                risk=True,
                decision="review",
                severity="medium",
                category="network_change",
            ),
        ),
        sample(
            "EV003",
            expected={
                "risk": True,
                "decision": "review",
                "severity": "medium",
                "category": "network_change",
            },
            predicted_result=predicted(
                risk=True,
                decision="review",
                severity="medium",
                category="data_exfiltration",
            ),
        ),
        sample(
            "EV004",
            expected={
                "risk": True,
                "decision": "block",
                "severity": "high",
                "category": "unsafe_download",
            },
            predicted_result=None,
            source="fallback",
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
            predicted_result=predicted(
                risk=False,
                decision="allow",
                severity="none",
                category="benign",
                model_version="not-invoked",
                rule_hits=["rule.benign.git_status.v1"],
            ),
            source="rule",
            model_invoked=False,
            selected_rule_id="rule.benign.git_status.v1",
        ),
        sample(
            "EV006",
            expected={
                "risk": True,
                "decision": "block",
                "severity": "high",
                "category": "credential_access",
            },
            predicted_result=predicted(
                risk=True,
                decision="block",
                severity="high",
                category="credential_access",
            ),
        ),
    ]
    categories = [category.value for category in RiskCategory]
    support = {category: 0 for category in categories}
    support.update(
        {
            "benign": 2,
            "credential_access": 1,
            "destructive_operation": 1,
            "network_change": 1,
            "unsafe_download": 1,
        }
    )
    precision = {category: 0.0 for category in categories}
    precision.update({"benign": 0.5, "credential_access": 1.0})
    recall = dict(precision)
    f1 = dict(precision)
    return {
        "report_version": "fusion-eval-report-v1",
        "policy_version": "fusion-v1",
        "model_version": P4_COMBINED_ADAPTER_MODEL_VERSION,
        "freeze_version": "eval-v1-agent-reviewed-rc1",
        "adapter_provenance": combined_provenance_fixture(),
        "total_samples": 6,
        "source_counts": {"fallback": 1, "model": 4, "rule": 1},
        "rule_short_circuit_count": 1,
        "rule_short_circuit_rate": 1 / 6,
        "model_invocation_count": 5,
        "model_invocation_rate": 5 / 6,
        "rule_error_count": 0,
        "rule_error_rate": 0.0,
        "valid_output_count": 5,
        "valid_output_rate": 5 / 6,
        "per_rule_contribution": {"rule.benign.git_status.v1": 1},
        "model_repair_metrics": {
            "model_invoked_count": 5,
            "attempt_count": 1,
            "attempt_rate": 0.2,
            "success_count": 0,
            "success_rate": 0.0,
        },
        "risk_metrics": {
            "evaluated": 5,
            "total": 6,
            "coverage": 5 / 6,
            "tp": 2,
            "tn": 1,
            "fp": 1,
            "fn": 1,
            "precision": 2 / 3,
            "recall": 2 / 3,
            "f1": 2 / 3,
            "false_positive_rate": 0.5,
            "false_negative_rate": 1 / 3,
        },
        "decision_metrics": {
            "valid_predictions": 5,
            "decision_accuracy_valid": 0.6,
            "effective_decision_accuracy_all": 0.5,
            "fallback_count": 1,
        },
        "benign_false_positive_count": 1,
        "benign_false_positives": [{"sample_id": "EV002", "source": "model"}],
        "high_risk_allow_miss_count": 1,
        "high_risk_allow_misses": [{"sample_id": "EV001", "source": "model"}],
        "category_metrics": {
            "support": support,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "macro_f1": 0.125,
        },
        "samples": rows,
    }


def expected_samples(report):
    return {
        row["sample_id"]: dict(row["expected"])
        for row in report["samples"]
    }


def full_freeze_fusion_report(provenance):
    bundle = load_resolved_eval_v1()
    rows = []
    support = {}
    for record in bundle.records:
        expected = {
            "risk": record.expected.risk,
            "decision": record.expected.decision.value,
            "severity": record.expected.severity.value,
            "category": record.expected.category.value,
        }
        support[record.expected.category.value] = (
            support.get(record.expected.category.value, 0) + 1
        )
        rows.append(
            sample(
                record.sample_id,
                expected=expected,
                predicted_result=predicted(
                    **expected,
                    model_version=P4_COMBINED_ADAPTER_MODEL_VERSION,
                ),
            )
        )
    perfect = {category: 1.0 for category in support}
    return {
        "report_version": "fusion-eval-report-v1",
        "policy_version": "fusion-v1",
        "model_version": P4_COMBINED_ADAPTER_MODEL_VERSION,
        "freeze_version": str(bundle.manifest["freeze_version"]),
        "adapter_provenance": provenance,
        "total_samples": len(rows),
        "source_counts": {"model": len(rows)},
        "rule_short_circuit_count": 0,
        "rule_short_circuit_rate": 0.0,
        "model_invocation_count": len(rows),
        "model_invocation_rate": 1.0,
        "rule_error_count": 0,
        "rule_error_rate": 0.0,
        "valid_output_count": len(rows),
        "valid_output_rate": 1.0,
        "per_rule_contribution": {},
        "model_repair_metrics": {
            "model_invoked_count": len(rows),
            "attempt_count": 0,
            "attempt_rate": 0.0,
            "success_count": 0,
            "success_rate": 0.0,
        },
        "risk_metrics": {
            "evaluated": len(rows),
            "total": len(rows),
            "coverage": 1.0,
            "tp": 58,
            "tn": 42,
            "fp": 0,
            "fn": 0,
            "precision": 1.0,
            "recall": 1.0,
            "f1": 1.0,
            "false_positive_rate": 0.0,
            "false_negative_rate": 0.0,
        },
        "decision_metrics": {
            "valid_predictions": len(rows),
            "decision_accuracy_valid": 1.0,
            "effective_decision_accuracy_all": 1.0,
            "fallback_count": 0,
        },
        "benign_false_positive_count": 0,
        "benign_false_positives": [],
        "high_risk_allow_miss_count": 0,
        "high_risk_allow_misses": [],
        "category_metrics": {
            "support": support,
            "precision": perfect,
            "recall": perfect,
            "f1": perfect,
            "macro_f1": 1.0,
        },
        "samples": rows,
    }


class P4FusionDiagnosticsTests(unittest.TestCase):
    def analyze(self, report):
        return analyze_p4_fusion_report(
            report,
            expected_freeze_version="eval-v1-agent-reviewed-rc1",
            expected_samples=expected_samples(report_fixture()),
            expected_adapter_provenance=combined_provenance_fixture(),
        )

    def test_prioritizes_errors_and_attributes_them_to_sources(self):
        diagnostics = self.analyze(report_fixture())

        self.assertEqual(diagnostics["high_risk_allow_miss_sample_ids"], ["EV001"])
        self.assertEqual(diagnostics["risk_false_negative_sample_ids"], ["EV001"])
        self.assertEqual(diagnostics["invalid_output_sample_ids"], ["EV004"])
        self.assertEqual(diagnostics["repair_failure_sample_ids"], ["EV004"])
        self.assertEqual(diagnostics["benign_false_positive_sample_ids"], ["EV002"])
        self.assertEqual(
            diagnostics["effective_decision_error_sample_ids"],
            ["EV001", "EV002", "EV004"],
        )
        self.assertEqual(diagnostics["rule_short_circuit_sample_ids"], ["EV005"])
        self.assertEqual(diagnostics["rule_error_sample_ids"], [])
        self.assertEqual(
            diagnostics["high_risk_allow_miss_by_source"],
            {"model": ["EV001"]},
        )
        self.assertEqual(
            diagnostics["benign_false_positive_by_source"],
            {"model": ["EV002"]},
        )
        self.assertEqual(
            diagnostics["target_priority_sample_ids"],
            ["EV001", "EV004", "EV002", "EV003"],
        )

    def test_rejects_source_provenance_and_aggregate_drift(self):
        def conceal_high_risk_miss(report):
            report["samples"][0].update(
                effective_decision="block",
                effective_decision_correct=True,
            )
            report["high_risk_allow_miss_count"] = 0
            report["high_risk_allow_misses"] = []

        def impossible_fallback(report):
            report["samples"][3]["model_invoked"] = False
            report["model_invocation_count"] = 4
            report["model_invocation_rate"] = 4 / 6
            report["model_repair_metrics"]["model_invoked_count"] = 4
            report["model_repair_metrics"]["attempt_rate"] = 0.25

        def successful_repair_without_result(report):
            report["samples"][3]["model_repair_succeeded"] = True
            report["model_repair_metrics"]["success_count"] = 1
            report["model_repair_metrics"]["success_rate"] = 1.0

        def failed_repair_with_model_result(report):
            report["samples"][0]["model_repair_attempted"] = True
            report["model_repair_metrics"]["attempt_count"] = 2
            report["model_repair_metrics"]["attempt_rate"] = 0.4

        def non_review_fallback(report):
            report["samples"][3].update(
                fallback_decision="block",
                effective_decision="block",
                effective_decision_correct=True,
            )
            report["decision_metrics"]["effective_decision_accuracy_all"] = 4 / 6

        def parse_fallback_without_repair(report):
            report["samples"][3]["model_repair_attempted"] = False
            report["model_repair_metrics"]["attempt_count"] = 0
            report["model_repair_metrics"]["attempt_rate"] = 0.0

        mutations = (
            ("model claims rule source", lambda report: report["samples"][0].update(source="rule"), "rule source"),
            ("rule invokes model", lambda report: report["samples"][4].update(model_invoked=True), "rule source"),
            ("wrong model version", lambda report: report["samples"][0]["predicted"].update(model_version="wrong"), "model_version"),
            ("decision correctness drift", lambda report: report["samples"][0].update(effective_decision_correct=True), "effective_decision_correct"),
            ("concealed high-risk miss", conceal_high_risk_miss, "effective_decision"),
            (
                "impossible fallback",
                impossible_fallback,
                "without model invocation",
            ),
            (
                "successful repair without result",
                successful_repair_without_result,
                "fallback source",
            ),
            (
                "failed repair with model result",
                failed_repair_with_model_result,
                "model source",
            ),
            ("non-review fallback", non_review_fallback, "fallback_decision"),
            (
                "parse fallback without repair",
                parse_fallback_without_repair,
                "fallback source",
            ),
            ("numeric predicted risk", lambda report: report["samples"][0]["predicted"].update(risk=0), "risk must be boolean"),
            ("invalid predicted category", lambda report: report["samples"][0]["predicted"].update(category="unknown"), "category"),
            ("extra predicted field", lambda report: report["samples"][0]["predicted"].update(extra="hidden"), "predicted fields"),
            ("coerced expected risk", lambda report: report["samples"][1]["expected"].update(risk=0), "expected label risk"),
            ("source count drift", lambda report: report.update(source_counts={"model": 6}), "source_counts"),
            ("safety count drift", lambda report: report.update(high_risk_allow_miss_count=0), "high_risk_allow_miss_count"),
            ("category metrics drift", lambda report: report["category_metrics"]["f1"].update(unsafe_download=1.0), "category_metrics"),
            ("risk metrics drift", lambda report: report["risk_metrics"].update(fn=0), "risk_metrics"),
            ("repair metrics drift", lambda report: report["model_repair_metrics"].update(attempt_count=0), "model_repair_metrics"),
            ("rule contribution drift", lambda report: report.update(per_rule_contribution={}), "per_rule_contribution"),
        )
        for label, mutate, message in mutations:
            with self.subTest(label=label):
                report = report_fixture()
                mutate(report)
                with self.assertRaisesRegex(ValueError, message):
                    self.analyze(report)


class P4FusionDiagnosticsCliTests(unittest.TestCase):
    def test_cli_validates_local_combined_adapter_and_emits_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            model = directory / "model"
            model.mkdir()
            adapter_dir = write_pilot_artifacts(directory / "output", model)
            manifest_path = adapter_dir.parent / "training_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.update(
                {
                    "data_version": "p4-seed-targeted-v2",
                    "dataset_sha256": EXPECTED_P4_COMBINED_SHA256,
                    "max_length": 768,
                    "method": "qlora-p4-seed-targeted-v2",
                    "num_train_epochs": 1.0,
                    "train_count": 1200,
                    "validation_count": 300,
                }
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            provenance = {
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
            report_path = directory / "fusion-report.json"
            report_path.write_text(
                json.dumps(full_freeze_fusion_report(provenance)),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--report", str(report_path)],
                cwd=REPOSITORY_ROOT,
                text=True,
                capture_output=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(completed.stderr, "")
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["total_samples"], 100)
        self.assertEqual(payload["high_risk_allow_miss_sample_ids"], [])
        self.assertEqual(payload["target_priority_sample_ids"], [])

    def test_cli_errors_are_single_json_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.json"
            missing_result = subprocess.run(
                [sys.executable, str(SCRIPT), "--report", str(missing)],
                cwd=REPOSITORY_ROOT,
                text=True,
                capture_output=True,
            )
        invalid_result = subprocess.run(
            [sys.executable, str(SCRIPT), "--unknown-option"],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
        )

        for completed in (missing_result, invalid_result):
            with self.subTest(command=completed.args):
                self.assertEqual(completed.returncode, 2)
                self.assertEqual(completed.stderr, "")
                self.assertEqual(json.loads(completed.stdout)["status"], "error")


if __name__ == "__main__":
    unittest.main()
