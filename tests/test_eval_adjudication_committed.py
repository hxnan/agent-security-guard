import json
from pathlib import Path
import unittest

from guard.eval_adjudication import load_adjudications


class CommittedEvalAdjudicationTests(unittest.TestCase):
    def test_committed_adjudications_cover_exact_substantive_disagreements(self):
        root = Path(__file__).resolve().parents[1]
        rows = load_adjudications(
            root / "data" / "eval-v1" / "reviews" / "adjudication-2026-08-14.jsonl"
        )
        by_resolution = {
            "review": {row.sample_id for row in rows if row.resolution == "review"},
            "gold": {row.sample_id for row in rows if row.resolution == "gold"},
        }
        self.assertEqual(len(rows), 14)
        self.assertEqual(len({row.sample_id for row in rows}), 14)
        self.assertEqual(
            by_resolution["review"],
            {"EV022", "EV024", "EV026", "EV050", "EV060", "EV081", "EV082", "EV087"},
        )
        self.assertEqual(
            by_resolution["gold"],
            {"EV023", "EV046", "EV047", "EV058", "EV083", "EV084"},
        )

    def test_freeze_manifest_records_agent_review_provenance_without_human_claim(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads(
            (root / "data" / "eval-v1" / "freeze-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["data_version"], "eval-v1")
        self.assertEqual(manifest["freeze_version"], "eval-v1-agent-reviewed-rc1")
        self.assertEqual(manifest["status"], "technical-frozen")
        self.assertEqual(
            manifest["base_gold_commit"],
            "17996d6b75f8860ffe54ffa9e1d8e77f12be0132",
        )
        self.assertEqual(
            manifest["review_merge_commit"],
            "dafab5a47faaf1ade2c5fe97d7fc90acd8b0cf6f",
        )
        self.assertEqual(
            manifest["review_file"],
            "data/eval-v1/reviews/agent-blind-review-2026-08-14.jsonl",
        )
        self.assertEqual(manifest["reviewer_type"], "independent-agent")
        self.assertEqual(manifest["reviewer"], "ChatGPT / GPT-5.6 Sol")
        self.assertEqual(
            manifest["resolved_reviewer_id"], "independent-agent:gpt-5.6-sol"
        )
        self.assertEqual(
            manifest["adjudication_file"],
            "data/eval-v1/reviews/adjudication-2026-08-14.jsonl",
        )
        self.assertEqual(manifest["adjudicator"], "ChatGPT / GPT-5.6 Sol")
        self.assertIs(manifest["human_reviewed"], False)


if __name__ == "__main__":
    unittest.main()
