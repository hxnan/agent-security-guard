import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.prepare_targeted_training_data import prepare_targeted_dataset
from training.targeted_dataset import TargetedDatasetError


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_targeted_training_data.py"
EVAL_DIR = ROOT / "data" / "eval-v1" / "gold"


class PrepareTargetedDataCliTests(unittest.TestCase):
    def test_help_exposes_versioned_targeted_outputs(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--train-output", completed.stdout)
        self.assertIn("--validation-output", completed.stdout)
        self.assertIn("--manifest-output", completed.stdout)

    def test_prepare_writes_valid_400_100_bundle_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            train = directory / "train.jsonl"
            validation = directory / "validation.jsonl"
            manifest = directory / "manifest.json"

            result = prepare_targeted_dataset(
                train, validation, manifest, EVAL_DIR
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["splits"], {"train": 400, "validation": 100})
            self.assertEqual(len(train.read_text(encoding="utf-8").splitlines()), 400)
            self.assertEqual(
                len(validation.read_text(encoding="utf-8").splitlines()), 100
            )
            self.assertIs(
                json.loads(manifest.read_text(encoding="utf-8"))[
                    "evaluation_adaptive"
                ],
                True,
            )

    def test_prepare_refuses_existing_output_without_force(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            train = directory / "train.jsonl"
            validation = directory / "validation.jsonl"
            manifest = directory / "manifest.json"
            train.write_text("owned\n", encoding="utf-8")

            with self.assertRaisesRegex(TargetedDatasetError, "already exists"):
                prepare_targeted_dataset(
                    train, validation, manifest, EVAL_DIR
                )

            self.assertEqual(train.read_text(encoding="utf-8"), "owned\n")
            self.assertFalse(validation.exists())
            self.assertFalse(manifest.exists())

    def test_prepare_rejects_nested_output_paths_without_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            train = root / "bundle"
            validation = root / "validation.jsonl"
            manifest = train / "manifest.json"

            with self.assertRaisesRegex(TargetedDatasetError, "nested"):
                prepare_targeted_dataset(
                    train, validation, manifest, EVAL_DIR
                )

            self.assertFalse(train.exists())
            self.assertFalse(validation.exists())
            self.assertFalse(manifest.exists())


if __name__ == "__main__":
    unittest.main()
