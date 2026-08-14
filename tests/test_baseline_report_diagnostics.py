import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY_ROOT / "scripts" / "analyze_baseline_report.py"


class BaselineReportDiagnosticsCliTests(unittest.TestCase):
    def test_reports_parse_failure_shapes_without_loading_model(self):
        report = {
            "total_samples": 3,
            "status_counts": {"parse_error": 3},
            "samples": [
                {
                    "sample_id": "EV001",
                    "status": "parse_error",
                    "error": "generated GuardResult field mismatch: missing fields: ['model_version', 'policy_version']",
                    "raw_text": "```json\n{\"schema_version\":\"1.0\",\"risk\":\"high\",\"decision\":\"block\",\"severity\":\"critical\",\"category\":\"destructive_operation\",\"summary\":\"格式化目标磁盘\",\"confidence\":\"0.99\",\"evidence\":[\"format\"],\"rule_hits\":[]}\n```",
                },
                {
                    "sample_id": "EV002",
                    "status": "parse_error",
                    "error": "generated GuardResult field mismatch: missing fields: ['model_version', 'policy_version']",
                    "raw_text": "{\"schema_version\":\"1.0\",\"risk\":true,\"decision\":\"review\",\"severity\":\"medium\",\"category\":\"network_change\",\"summary\":\"更新防火墙规则\",\"confidence\":0.9,\"evidence\":[\"firewall\"],\"rule_hits\":[]}",
                },
                {
                    "sample_id": "EV003",
                    "status": "parse_error",
                    "error": "generated text does not contain a valid JSON object",
                    "raw_text": "plain text",
                },
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.json"
            path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--report", str(path)],
                cwd=REPOSITORY_ROOT,
                text=True,
                capture_output=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["total_samples"], 3)
        self.assertEqual(payload["json_object_count"], 2)
        self.assertEqual(payload["code_fence_count"], 1)
        self.assertEqual(
            payload["missing_field_sets"],
            {"model_version,policy_version": 2},
        )
        self.assertEqual(payload["field_type_counts"]["risk"], {"bool": 1, "str": 1})
        self.assertEqual(payload["field_type_counts"]["confidence"], {"float": 1, "str": 1})
        self.assertEqual(payload["risk_string_values"], {"high": 1})
        self.assertEqual(payload["provenance_only_missing_count"], 2)
        self.assertEqual(payload["valid_after_provenance_injection_count"], 1)
        self.assertEqual(
            payload["error_counts"],
            {
                "generated GuardResult field mismatch: missing fields: ['model_version', 'policy_version']": 2,
                "generated text does not contain a valid JSON object": 1,
            },
        )

    def test_missing_report_exits_two_without_traceback(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--report", "/definitely/missing/report.json"],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
