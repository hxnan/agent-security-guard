import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path

from guard.taxonomy import Decision, RiskCategory, ToolType
from training.data_quality import (
    load_eval_request_fingerprints,
    load_training_jsonl,
    request_fingerprint,
)
from training.seed_dataset import (
    SeedDatasetError,
    build_seed_manifest,
    canonical_jsonl_bytes,
    generate_seed_dataset,
    validate_seed_profile,
)


class SeedDatasetTests(unittest.TestCase):
    def test_generation_has_exact_ids_splits_and_unique_requests(self):
        train, validation = generate_seed_dataset()
        records = train + validation

        self.assertEqual((len(train), len(validation)), (800, 200))
        self.assertEqual(train[0].sample_id, "TR-000001")
        self.assertEqual(train[-1].sample_id, "TR-000800")
        self.assertEqual(validation[0].sample_id, "TR-000801")
        self.assertEqual(validation[-1].sample_id, "TR-001000")
        self.assertEqual(
            len({request_fingerprint(record.input) for record in records}), 1000
        )

    def test_generation_has_fixed_category_batch_and_coverage_profile(self):
        train, validation = generate_seed_dataset()
        records = train + validation
        categories = Counter(record.output.category for record in records)
        batches = Counter(record.metadata.batch_id for record in records)

        self.assertEqual(categories[RiskCategory.BENIGN], 300)
        self.assertEqual(categories[RiskCategory.REMOTE_EXECUTION], 80)
        self.assertEqual(categories[RiskCategory.UNSAFE_DOWNLOAD], 80)
        for category in set(RiskCategory) - {
            RiskCategory.BENIGN,
            RiskCategory.REMOTE_EXECUTION,
            RiskCategory.UNSAFE_DOWNLOAD,
        }:
            self.assertEqual(categories[category], 60, category)
        self.assertEqual(
            batches,
            Counter(
                {f"p4-seed-v1-batch-{number:03d}": 100 for number in range(1, 11)}
            ),
        )
        self.assertEqual({record.input.type for record in records}, set(ToolType))
        self.assertEqual(
            {record.metadata.scenario_kind for record in records},
            {"normal", "dangerous", "boundary", "injection"},
        )

    def test_profile_accepts_generated_dataset_and_disjoint_templates(self):
        train, validation = generate_seed_dataset()

        summary = validate_seed_profile(train, validation, set())

        self.assertEqual(summary.total, 1000)
        self.assertEqual(summary.splits, {"train": 800, "validation": 200})
        self.assertTrue(
            {record.metadata.semantic_template for record in train}.isdisjoint(
                record.metadata.semantic_template for record in validation
            )
        )

    def test_profile_rejects_count_and_batch_drift(self):
        train, validation = generate_seed_dataset()

        with self.assertRaisesRegex(SeedDatasetError, "train rows must be 800"):
            validate_seed_profile(train[:-1], validation, set())

        changed_metadata = train[0].metadata.model_copy(
            update={"batch_id": "p4-seed-v1-batch-010"}
        )
        changed = train[0].model_copy(update={"metadata": changed_metadata})
        with self.assertRaisesRegex(SeedDatasetError, "batch counts must be exactly 100"):
            validate_seed_profile([changed, *train[1:]], validation, set())

    def test_profile_rejects_curated_label_and_provenance_drift(self):
        train, validation = generate_seed_dataset()
        credential_index = next(
            index
            for index, record in enumerate(train)
            if record.output.category is RiskCategory.CREDENTIAL_ACCESS
        )
        changed_output = train[credential_index].output.model_copy(
            update={"decision": Decision.BLOCK}
        )
        changed_label = train[credential_index].model_copy(
            update={"output": changed_output}
        )

        with self.assertRaisesRegex(SeedDatasetError, "curated seed record"):
            validate_seed_profile(
                [
                    *train[:credential_index],
                    changed_label,
                    *train[credential_index + 1 :],
                ],
                validation,
                set(),
            )

        changed_metadata = train[0].metadata.model_copy(
            update={"data_version": "other-v9"}
        )
        changed_provenance = train[0].model_copy(update={"metadata": changed_metadata})
        with self.assertRaisesRegex(SeedDatasetError, "curated seed record"):
            validate_seed_profile([changed_provenance, *train[1:]], validation, set())

    def test_canonical_bytes_and_manifest_are_deterministic(self):
        first_train, first_validation = generate_seed_dataset()
        second_train, second_validation = generate_seed_dataset()
        train_bytes = canonical_jsonl_bytes(first_train)
        validation_bytes = canonical_jsonl_bytes(first_validation)

        self.assertEqual(train_bytes, canonical_jsonl_bytes(second_train))
        self.assertEqual(
            validation_bytes, canonical_jsonl_bytes(second_validation)
        )

        manifest = build_seed_manifest(
            first_train, first_validation, train_bytes, validation_bytes
        )
        self.assertEqual(manifest["total"], 1000)
        self.assertEqual(manifest["batch_size"], 100)
        self.assertEqual(manifest["batch_count"], 10)
        self.assertEqual(manifest["splits"], {"train": 800, "validation": 200})
        self.assertEqual(
            manifest["sha256"],
            {
                "train": hashlib.sha256(train_bytes).hexdigest(),
                "validation": hashlib.sha256(validation_bytes).hexdigest(),
            },
        )

    def test_committed_seed_is_exact_generated_dataset_and_passes_eval_gate(self):
        root = Path(__file__).resolve().parents[1]
        train_path = root / "data" / "train" / "agent_security_train_v1.jsonl"
        validation_path = (
            root / "data" / "val" / "agent_security_validation_v1.jsonl"
        )
        manifest_path = (
            root / "data" / "train" / "agent_security_seed_v1_manifest.json"
        )
        generated_train, generated_validation = generate_seed_dataset()

        self.assertEqual(train_path.read_bytes(), canonical_jsonl_bytes(generated_train))
        self.assertEqual(
            validation_path.read_bytes(), canonical_jsonl_bytes(generated_validation)
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["sha256"],
            {
                "train": "1897e89d11a730ad0922081bda0cf18da3b643a1fc887c2e27abaa7cc5e96208",
                "validation": "c4228d11dd08e8e0cf2a48b01398b5ee0be8a7270a572285e870e74eb939915e",
            },
        )
        loaded_train = load_training_jsonl(train_path, expected_split="train")
        loaded_validation = load_training_jsonl(
            validation_path, expected_split="validation"
        )
        summary = validate_seed_profile(
            loaded_train,
            loaded_validation,
            load_eval_request_fingerprints(root / "data" / "eval-v1" / "gold"),
        )
        self.assertEqual(summary.total, 1000)


if __name__ == "__main__":
    unittest.main()
