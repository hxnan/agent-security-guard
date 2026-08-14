import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class EvalFreezeCliTests(unittest.TestCase):
    def test_committed_technical_freeze_validates_and_reports_expected_counts(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "scripts/validate_eval_freeze.py"],
            cwd=root,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["freeze_version"], "eval-v1-agent-reviewed-rc1")
        self.assertIs(payload["technical_freeze"], True)
        self.assertIs(payload["human_reviewed"], False)
        self.assertEqual(payload["substantive_disagreements"], 14)
        self.assertEqual(payload["adjudications"], {"gold": 6, "review": 8})
        self.assertEqual(payload["stats"]["total"], 100)
        self.assertEqual(
            payload["stats"]["review_statuses"],
            {"adjudicated": 14, "agreed": 86},
        )
        self.assertEqual(
            payload["stats"]["decisions"],
            {"allow": 42, "block": 25, "review": 33},
        )
        self.assertEqual(
            payload["stats"]["categories"],
            {
                "benign": 42,
                "credential_access": 5,
                "data_exfiltration": 6,
                "defense_evasion": 5,
                "destructive_operation": 7,
                "network_change": 7,
                "persistence": 5,
                "privilege_escalation": 4,
                "remote_execution": 8,
                "resource_abuse": 4,
                "sensitive_write": 3,
                "unsafe_download": 4,
            },
        )

    def test_manifest_claiming_human_review_is_rejected(self):
        root = Path(__file__).resolve().parents[1]
        committed = json.loads(
            (root / "data" / "eval-v1" / "freeze-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        committed["human_reviewed"] = True
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "freeze-manifest.json"
            manifest.write_text(
                json.dumps(committed, ensure_ascii=False), encoding="utf-8"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/validate_eval_freeze.py",
                    "--manifest",
                    str(manifest),
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertIn("human_reviewed", payload["error"])


if __name__ == "__main__":
    unittest.main()
