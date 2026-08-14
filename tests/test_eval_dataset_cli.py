import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.test_eval_dataset import make_record


def blueprint_payload():
    return {
        "sample_id": "EV001",
        "tool_family": "shell",
        "request_type": "shell",
        "scenario_kind": "normal",
        "planned_category": "benign",
        "scenario": "Inspect repository status without changing files",
        "semantic_template": "repo_status_read_only",
        "variant": "git_status_short",
        "risk_factors": [],
        "required_context": ["cwd_inside_workspace"],
        "mixed_components": [],
        "authoring_status": "planned",
    }


class EvalDatasetCliTests(unittest.TestCase):
    def write_fixture(self, root: Path):
        dataset = root / "gold.jsonl"
        dataset.write_text(
            json.dumps(make_record().model_dump(mode="json"), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        blueprint = root / "blueprint.jsonl"
        blueprint.write_text(
            json.dumps(blueprint_payload(), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return dataset, blueprint

    def test_validate_cli_reports_ok_for_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset, blueprint = self.write_fixture(Path(tmp))
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/validate_eval_dataset.py",
                    "--dataset",
                    str(dataset),
                    "--blueprint",
                    str(blueprint),
                ],
                cwd=Path(__file__).parents[1],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["stats"]["total"], 1)

    def test_validate_cli_frozen_mode_rejects_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset, blueprint = self.write_fixture(Path(tmp))
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/validate_eval_dataset.py",
                    "--dataset",
                    str(dataset),
                    "--blueprint",
                    str(blueprint),
                    "--require-frozen",
                ],
                cwd=Path(__file__).parents[1],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "error")
            self.assertIn("review_status", payload["error"])

    def test_report_cli_prints_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset, _ = self.write_fixture(Path(tmp))
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/report_eval_dataset.py",
                    "--dataset",
                    str(dataset),
                ],
                cwd=Path(__file__).parents[1],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertEqual(json.loads(result.stdout)["total"], 1)


if __name__ == "__main__":
    unittest.main()
