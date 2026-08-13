import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from guard.smoke_data import generate_smoke_records


class TrainSmokeCliTests(unittest.TestCase):
    def test_data_integrity_failure_is_concise_exit_two_before_ml_checks(self):
        train, validation = generate_smoke_records()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            data_dir = root / "data"
            data_dir.mkdir()
            duplicate = train[0].to_dict()
            (data_dir / "train.jsonl").write_text(
                "\n".join(json.dumps(duplicate) for _ in range(2)) + "\n",
                encoding="utf-8",
            )
            (data_dir / "validation.jsonl").write_text(
                "\n".join(
                    json.dumps(record.to_dict()) for record in validation
                )
                + "\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/train_smoke_qlora.py",
                    "--data-dir",
                    str(data_dir),
                    "--output-dir",
                    str(root / "output"),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("duplicate sample_id", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
