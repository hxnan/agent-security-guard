import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from guard.qlora import QloraError
from guard.training_config import TrainingConfigError
from scripts.train_p4_seed_qlora import main, parse_config


class TrainP4SeedQloraCliTests(unittest.TestCase):
    repository_root = Path(__file__).resolve().parents[1]

    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "scripts/train_p4_seed_qlora.py", *arguments],
            cwd=self.repository_root,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_parser_exposes_pilot_defaults_and_overrides(self):
        defaults = parse_config([])
        overridden = parse_config(
            [
                "--max-length",
                "256",
                "--num-train-epochs",
                "3",
                "--learning-rate",
                "0.0002",
                "--lora-target",
                "attention",
                "--overwrite-output",
            ]
        )

        self.assertEqual(defaults.max_length, 512)
        self.assertEqual(defaults.num_train_epochs, 2.0)
        self.assertEqual(defaults.learning_rate, 1e-4)
        self.assertEqual(overridden.max_length, 256)
        self.assertEqual(overridden.num_train_epochs, 3.0)
        self.assertEqual(overridden.learning_rate, 2e-4)
        self.assertEqual(overridden.lora_target, "attention")
        self.assertTrue(overridden.overwrite_output)

    def test_parser_uses_config_validation_for_nonfinite_values(self):
        for option, value, field in (
            ("--max-length", "0", "max_length"),
            ("--num-train-epochs", "nan", "num_train_epochs"),
            ("--learning-rate", "inf", "learning_rate"),
        ):
            with self.subTest(option=option):
                with self.assertRaisesRegex(TrainingConfigError, field):
                    parse_config([option, value])

    def test_invalid_numeric_value_is_json_failure_without_traceback(self):
        completed = self.run_cli("--num-train-epochs", "nan")

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stderr, "")
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertIn("num_train_epochs", payload["errors"][0])
        self.assertNotIn("Traceback", completed.stdout)

    def test_preflight_reports_fixed_dataset_before_missing_local_environment(self):
        completed = self.run_cli("--preflight-only")

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stderr, "")
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "not_ready")
        self.assertEqual(payload["dataset"]["train_count"], 800)
        self.assertEqual(payload["dataset"]["validation_count"], 200)
        self.assertEqual(
            payload["dataset"]["sha256"]["train"],
            "1897e89d11a730ad0922081bda0cf18da3b643a1fc887c2e27abaa7cc5e96208",
        )
        self.assertFalse(payload["environment"]["ready"])

    def test_tampered_data_fails_preflight_before_environment_report(self):
        source = (
            self.repository_root
            / "data"
            / "train"
            / "agent_security_train_v1.jsonl"
        )
        with tempfile.TemporaryDirectory() as directory:
            train = Path(directory) / "train.jsonl"
            train.write_bytes(source.read_bytes() + b"\n")
            completed = self.run_cli(
                "--preflight-only", "--train", str(train)
            )

        self.assertEqual(completed.returncode, 2)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertIn("dataset SHA-256", payload["errors"][0])
        self.assertNotIn("environment", payload)

    def test_runtime_domain_error_is_single_json_failure(self):
        output = StringIO()
        with patch(
            "scripts.train_p4_seed_qlora.train_p4_seed",
            side_effect=QloraError(
                "CUDA out of memory; retry: python scripts/train_p4_seed_qlora.py --max-length 256"
            ),
        ), redirect_stdout(output):
            exit_code = main([])

        self.assertEqual(exit_code, 2)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "failed")
        self.assertIn("CUDA out of memory", payload["errors"][0])
        self.assertNotIn("Traceback", output.getvalue())


if __name__ == "__main__":
    unittest.main()
