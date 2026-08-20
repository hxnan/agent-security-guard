import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_p4_training_data_quality import row


class TrainingDatasetCliTests(unittest.TestCase):
    def run_cli(self, directory, train_rows, validation_rows, eval_rows=None):
        root = Path(__file__).resolve().parents[1]
        train = Path(directory) / "train.jsonl"
        validation = Path(directory) / "validation.jsonl"
        eval_dir = Path(directory) / "eval"
        eval_dir.mkdir()
        train.write_text(
            "".join(json.dumps(item) + "\n" for item in train_rows),
            encoding="utf-8",
        )
        validation.write_text(
            "".join(json.dumps(item) + "\n" for item in validation_rows),
            encoding="utf-8",
        )
        if eval_rows is None:
            eval_rows = ({"request": row(command="echo eval sentinel")["input"]},)
        (eval_dir / "part.jsonl").write_text(
            "".join(json.dumps(item) + "\n" for item in eval_rows),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(root / "scripts" / "check_training_dataset.py"),
                "--train",
                str(train),
                "--validation",
                str(validation),
                "--eval-dir",
                str(eval_dir),
            ],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        return completed, json.loads(completed.stdout)

    def test_success_prints_deterministic_json(self):
        with tempfile.TemporaryDirectory() as directory:
            completed, output = self.run_cli(
                directory,
                [row()],
                [
                    row(
                        sample_id="TR-000002",
                        split="validation",
                        command="pwd",
                        template="benign_pwd_validation",
                    )
                ],
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["train"]["samples"], 1)
        self.assertEqual(output["validation"]["samples"], 1)

    def test_failure_is_json_without_traceback(self):
        copied = row(
            sample_id="TR-000002",
            split="validation",
            template="benign_copy_validation",
        )
        with tempfile.TemporaryDirectory() as directory:
            completed, output = self.run_cli(
                directory,
                [row()],
                [copied],
                [{"request": copied["input"], "result": {"ignored": "label"}}],
            )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(output["status"], "failed")
        self.assertIn("duplicates frozen Eval V1", " ".join(output["errors"]))
        self.assertNotIn("Traceback", completed.stderr)

    def test_invalid_utf8_failure_is_json_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(__file__).resolve().parents[1]
            train = Path(directory) / "train.jsonl"
            validation = Path(directory) / "validation.jsonl"
            eval_dir = Path(directory) / "eval"
            eval_dir.mkdir()
            train.write_bytes(b"\xff\xfe")
            validation.write_text(json.dumps(row(split="validation")) + "\n")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts" / "check_training_dataset.py"),
                    "--train",
                    str(train),
                    "--validation",
                    str(validation),
                    "--eval-dir",
                    str(eval_dir),
                ],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

        output = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(output["status"], "failed")
        self.assertNotIn("Traceback", completed.stderr)

    def test_argument_failure_is_json_without_usage_traceback(self):
        root = Path(__file__).resolve().parents[1]

        completed = subprocess.run(
            [
                sys.executable,
                str(root / "scripts" / "check_training_dataset.py"),
                "--unknown-option",
            ],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )

        output = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(output["status"], "failed")
        self.assertIn("argument error", output["errors"][0])
        self.assertEqual(completed.stderr, "")


if __name__ == "__main__":
    unittest.main()
