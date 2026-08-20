import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.prepare_training_data import prepare_seed_dataset
from training.seed_dataset import SeedDatasetError, generate_seed_dataset


class PrepareTrainingDataCliTests(unittest.TestCase):
    def run_cli(self, directory: str, *extra: str):
        root = Path(__file__).resolve().parents[1]
        output = Path(directory) / "output"
        train = output / "train.jsonl"
        validation = output / "validation.jsonl"
        manifest = output / "manifest.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(root / "scripts" / "prepare_training_data.py"),
                "--train-output",
                str(train),
                "--validation-output",
                str(validation),
                "--manifest-output",
                str(manifest),
                "--eval-dir",
                str(root / "data" / "eval-v1" / "gold"),
                *extra,
            ],
            cwd=directory,
            check=False,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        return completed, payload, train, validation, manifest

    def test_cli_generates_valid_files_from_external_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            completed, payload, train, validation, manifest = self.run_cli(directory)
            manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["total"], 1000)
            self.assertEqual(payload["splits"], {"train": 800, "validation": 200})
            self.assertEqual(
                manifest_payload["sha256"],
                {
                    "train": hashlib.sha256(train.read_bytes()).hexdigest(),
                    "validation": hashlib.sha256(validation.read_bytes()).hexdigest(),
                },
            )

    def test_cli_refuses_overwrite_and_force_is_byte_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            first, _, train, validation, manifest = self.run_cli(directory)
            original = (train.read_bytes(), validation.read_bytes(), manifest.read_bytes())
            refused, payload, *_ = self.run_cli(directory)
            forced, _, *_ = self.run_cli(directory, "--force")

            self.assertEqual(first.returncode, 0)
            self.assertEqual(refused.returncode, 1)
            self.assertEqual(payload["status"], "failed")
            self.assertIn("already exists", payload["errors"][0])
            self.assertEqual(forced.returncode, 0, forced.stderr)
            self.assertEqual(
                (train.read_bytes(), validation.read_bytes(), manifest.read_bytes()),
                original,
            )

    def test_missing_eval_directory_is_json_failure_without_partial_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(__file__).resolve().parents[1]
            output = Path(directory) / "output"
            train = output / "train.jsonl"
            validation = output / "validation.jsonl"
            manifest = output / "manifest.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts" / "prepare_training_data.py"),
                    "--train-output",
                    str(train),
                    "--validation-output",
                    str(validation),
                    "--manifest-output",
                    str(manifest),
                    "--eval-dir",
                    str(Path(directory) / "missing-eval"),
                ],
                cwd=directory,
                check=False,
                capture_output=True,
                text=True,
            )

            payload = json.loads(completed.stdout)
            self.assertEqual(completed.returncode, 1)
            self.assertEqual(payload["status"], "failed")
            self.assertNotIn("Traceback", completed.stderr)
            self.assertFalse(train.exists())
            self.assertFalse(validation.exists())
            self.assertFalse(manifest.exists())

    def test_force_rejects_non_file_output_without_overwriting_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(__file__).resolve().parents[1]
            output = Path(directory) / "output"
            output.mkdir()
            train = output / "train.jsonl"
            validation = output / "validation.jsonl"
            manifest = output / "manifest.json"
            train.write_bytes(b"existing train\n")
            validation.write_bytes(b"existing validation\n")
            manifest.mkdir()

            with self.assertRaisesRegex(OSError, "regular file"):
                prepare_seed_dataset(
                    train,
                    validation,
                    manifest,
                    root / "data" / "eval-v1" / "gold",
                    force=True,
                )

            self.assertEqual(train.read_bytes(), b"existing train\n")
            self.assertEqual(validation.read_bytes(), b"existing validation\n")
            self.assertTrue(manifest.is_dir())

    def test_generation_precedes_eval_fingerprint_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(__file__).resolve().parents[1]
            output = Path(directory) / "output"
            events = []
            generated = generate_seed_dataset()

            with patch(
                "scripts.prepare_training_data.generate_seed_dataset",
                side_effect=lambda: events.append("generate") or generated,
            ), patch(
                "scripts.prepare_training_data.load_eval_request_fingerprints",
                side_effect=lambda _path: events.append("eval") or set(),
            ):
                prepare_seed_dataset(
                    output / "train.jsonl",
                    output / "validation.jsonl",
                    output / "manifest.json",
                    root / "data" / "eval-v1" / "gold",
                )

            self.assertEqual(events, ["generate", "eval"])

    def test_force_rolls_back_all_outputs_when_final_publish_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(__file__).resolve().parents[1]
            output = Path(directory) / "output"
            output.mkdir()
            train = output / "train.jsonl"
            validation = output / "validation.jsonl"
            manifest = output / "manifest.json"
            originals = (b"existing train\n", b"existing validation\n", b"{}\n")
            for path, content in zip((train, validation, manifest), originals):
                path.write_bytes(content)

            original_replace = Path.replace

            def fail_manifest_publish(source, target):
                if source.name == "manifest.json.tmp" and target == manifest:
                    raise OSError("injected manifest publication failure")
                return original_replace(source, target)

            with patch.object(
                Path,
                "replace",
                autospec=True,
                side_effect=fail_manifest_publish,
            ):
                with self.assertRaisesRegex(OSError, "injected manifest"):
                    prepare_seed_dataset(
                        train,
                        validation,
                        manifest,
                        root / "data" / "eval-v1" / "gold",
                        force=True,
                    )

            self.assertEqual(
                tuple(path.read_bytes() for path in (train, validation, manifest)),
                originals,
            )
            self.assertFalse(any(output.glob("*.bak")))
            self.assertFalse(any(output.glob("*.tmp")))

    def test_force_rejects_final_staging_path_collision_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(__file__).resolve().parents[1]
            output = Path(directory) / "output"
            output.mkdir()
            train = output / "data.jsonl"
            validation = output / "data.jsonl.tmp"
            manifest = output / "manifest.json"
            originals = (b"existing train\n", b"existing validation\n", b"{}\n")
            for path, content in zip((train, validation, manifest), originals):
                path.write_bytes(content)

            with self.assertRaisesRegex(SeedDatasetError, "auxiliary paths collide"):
                prepare_seed_dataset(
                    train,
                    validation,
                    manifest,
                    root / "data" / "eval-v1" / "gold",
                    force=True,
                )

            self.assertEqual(
                tuple(path.read_bytes() for path in (train, validation, manifest)),
                originals,
            )


if __name__ == "__main__":
    unittest.main()
