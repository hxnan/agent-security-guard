from pathlib import Path
import tempfile
import unittest

from guard.eval_freeze import (
    DEFAULT_ADJUDICATIONS,
    DEFAULT_BLUEPRINT,
    DEFAULT_DATASET,
    DEFAULT_MANIFEST,
    DEFAULT_REVIEW,
    EvalFreezeValidationError,
    load_freeze_manifest,
    load_resolved_eval_v1,
)


class EvalFreezeLibraryTests(unittest.TestCase):
    def test_committed_bundle_resolves_exact_technical_freeze(self):
        bundle = load_resolved_eval_v1()

        self.assertEqual(len(bundle.records), 100)
        self.assertEqual(
            [record.sample_id for record in bundle.records],
            [f"EV{i:03d}" for i in range(1, 101)],
        )
        statuses = [record.metadata.review_status.value for record in bundle.records]
        self.assertEqual(statuses.count("agreed"), 86)
        self.assertEqual(statuses.count("adjudicated"), 14)
        self.assertNotIn("pending", statuses)
        self.assertNotIn("disputed", statuses)
        self.assertEqual(bundle.substantive_disagreements, 14)
        self.assertEqual(bundle.adjudication_counts, {"gold": 6, "review": 8})
        self.assertEqual(bundle.manifest["freeze_version"], "eval-v1-agent-reviewed-rc1")
        self.assertIs(bundle.manifest["human_reviewed"], False)

    def test_default_paths_point_to_committed_eval_v1_inputs(self):
        for path in (
            DEFAULT_DATASET,
            DEFAULT_REVIEW,
            DEFAULT_ADJUDICATIONS,
            DEFAULT_BLUEPRINT,
            DEFAULT_MANIFEST,
        ):
            self.assertTrue(Path(path).exists(), path)

    def test_manifest_rejects_human_review_claim_for_agent_freeze(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text(
                '{"status":"technical-frozen","reviewer_type":"independent-agent",'
                '"resolved_reviewer_id":"agent","freeze_version":"x",'
                '"human_reviewed":true}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(EvalFreezeValidationError, "human_reviewed"):
                load_freeze_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
