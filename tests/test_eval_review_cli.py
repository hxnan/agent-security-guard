import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.test_eval_dataset import make_record


class EvalReviewCliTests(unittest.TestCase):
    def write_dataset(self, root: Path) -> Path:
        dataset = root / "gold.jsonl"
        dataset.write_text(
            json.dumps(make_record().model_dump(mode="json"), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return dataset

    def write_answers(
        self,
        root: Path,
        *,
        category: str = "benign",
        summary: str = "查看项目状态",
    ) -> Path:
        answers = root / "answers.jsonl"
        answers.write_text(
            json.dumps(
                {
                    "sample_id": "EV001",
                    "decision": "allow",
                    "severity": "none",
                    "category": category,
                    "summary": summary,
                    "confidence": 0.99,
                    "evidence": ["git status --short"],
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return answers

    def test_export_cli_writes_blind_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = self.write_dataset(root)
            output = root / "blind.jsonl"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/export_eval_review_packet.py",
                    "--dataset",
                    str(dataset),
                    "--output",
                    str(output),
                ],
                cwd=Path(__file__).parents[1],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            row = json.loads(output.read_text(encoding="utf-8").strip())
            self.assertEqual(set(row), {"sample_id", "request"})
            self.assertNotIn("expected", row)
            self.assertNotIn("metadata", row)

    def test_compare_cli_returns_zero_for_exact_label_agreement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = self.write_dataset(root)
            answers = self.write_answers(root)
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/compare_eval_review.py",
                    "--dataset",
                    str(dataset),
                    "--answers",
                    str(answers),
                ],
                cwd=Path(__file__).parents[1],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "agreed")
            self.assertEqual(payload["compared"], 1)
            self.assertEqual(payload["label_disagreements"], [])
            self.assertEqual(payload["summary_differences"], [])

    def test_compare_cli_summary_only_difference_is_not_substantive_dispute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = self.write_dataset(root)
            answers = self.write_answers(root, summary="查看仓库状态")
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/compare_eval_review.py",
                    "--dataset",
                    str(dataset),
                    "--answers",
                    str(answers),
                ],
                cwd=Path(__file__).parents[1],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "agreed")
            self.assertEqual(payload["label_disagreements"], [])
            self.assertEqual(payload["summary_differences"], ["EV001"])

    def test_compare_cli_returns_three_for_substantive_label_disagreement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = self.write_dataset(root)
            answers = self.write_answers(root, category="credential_access")
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/compare_eval_review.py",
                    "--dataset",
                    str(dataset),
                    "--answers",
                    str(answers),
                ],
                cwd=Path(__file__).parents[1],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 3, result.stderr or result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "disputed")
            self.assertEqual(payload["label_disagreements"][0]["sample_id"], "EV001")
            self.assertEqual(
                payload["label_disagreements"][0]["label_differences"],
                ["category"],
            )


if __name__ == "__main__":
    unittest.main()
