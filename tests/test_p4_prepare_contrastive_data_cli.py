import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_contrastive_training_data.py"
EVAL_DIR = ROOT / "data" / "eval-v1" / "gold"


class PrepareContrastiveDataCliTests(unittest.TestCase):
    def test_cli_writes_valid_bundle_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            train = directory / "train.jsonl"
            validation = directory / "validation.jsonl"
            manifest = directory / "manifest.json"
            command = [
                sys.executable,
                str(SCRIPT),
                "--train-output",
                str(train),
                "--validation-output",
                str(validation),
                "--manifest-output",
                str(manifest),
                "--eval-dir",
                str(EVAL_DIR),
            ]

            generated = subprocess.run(
                command, cwd=ROOT, text=True, capture_output=True
            )
            refused = subprocess.run(
                command, cwd=ROOT, text=True, capture_output=True
            )

            self.assertEqual(generated.returncode, 0, generated.stdout)
            payload = json.loads(generated.stdout)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["splits"], {"train": 800, "validation": 200})
            self.assertEqual(len(train.read_text(encoding="utf-8").splitlines()), 800)
            self.assertEqual(
                len(validation.read_text(encoding="utf-8").splitlines()), 200
            )
            self.assertEqual(refused.returncode, 1)
            self.assertIn("already exists", json.loads(refused.stdout)["errors"][0])

    def test_argument_error_is_single_json_without_traceback(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--unknown"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stderr, "")
        self.assertEqual(json.loads(completed.stdout)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
