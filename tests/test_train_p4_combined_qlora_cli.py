import json
from pathlib import Path
import subprocess
import sys
import unittest

from guard.training_config import TrainingConfigError
from scripts.train_p4_combined_qlora import parse_config


class TrainP4CombinedQloraCliTests(unittest.TestCase):
    repository_root = Path(__file__).resolve().parents[1]

    def test_parser_exposes_combined_defaults(self):
        config = parse_config([])

        self.assertEqual(config.num_train_epochs, 1.0)
        self.assertEqual(config.max_length, 768)
        self.assertEqual(config.output_dir.name, "p4-seed-targeted-qlora-v2")
        self.assertEqual(
            config.targeted_train_path.name,
            "agent_security_targeted_train_v1.jsonl",
        )
        with self.assertRaisesRegex(TrainingConfigError, "exactly 1.0"):
            parse_config(["--num-train-epochs", "2"])
        with self.assertRaisesRegex(TrainingConfigError, "max_length"):
            parse_config(["--max-length", "576"])

    def test_cpu_preflight_reports_combined_dataset_before_environment(self):
        completed = subprocess.run(
            [sys.executable, "scripts/train_p4_combined_qlora.py", "--preflight-only"],
            cwd=self.repository_root,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stderr, "")
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "not_ready")
        self.assertEqual(payload["dataset"]["train_count"], 1200)
        self.assertEqual(payload["dataset"]["validation_count"], 300)
        self.assertEqual(payload["dataset"]["data_version"], "p4-seed-targeted-v2")


if __name__ == "__main__":
    unittest.main()
