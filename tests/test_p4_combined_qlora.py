from pathlib import Path
import tempfile
import unittest

from guard.p4_qlora import (
    EXPECTED_P4_COMBINED_SHA256,
    build_p4_training_manifest,
    load_p4_combined_dataset_bundle,
    P4QloraError,
)
from guard.training_config import (
    P4CombinedTrainingConfig,
    TrainingConfigError,
)


class P4CombinedTrainingTests(unittest.TestCase):
    def test_defaults_match_fixed_six_gb_combined_contract(self):
        config = P4CombinedTrainingConfig()

        self.assertEqual(config.num_train_epochs, 1.0)
        self.assertEqual(config.max_length, 576)
        self.assertEqual(config.micro_batch_size, 1)
        self.assertEqual(config.gradient_accumulation_steps, 16)
        self.assertEqual(config.output_dir.name, "p4-seed-targeted-qlora-v2")

        with self.assertRaisesRegex(TrainingConfigError, "num_train_epochs"):
            P4CombinedTrainingConfig(num_train_epochs=2.0)

    def test_bundle_loads_seed_then_targeted_with_exact_source_hashes(self):
        bundle = load_p4_combined_dataset_bundle(P4CombinedTrainingConfig())

        self.assertEqual((len(bundle.train), len(bundle.validation)), (1200, 300))
        self.assertEqual(bundle.train[0].sample_id, "TR-000001")
        self.assertEqual(bundle.train[799].sample_id, "TR-000800")
        self.assertEqual(bundle.train[800].sample_id, "TR-001001")
        self.assertEqual(bundle.validation[199].sample_id, "TR-001000")
        self.assertEqual(bundle.validation[200].sample_id, "TR-001401")
        self.assertEqual(bundle.sha256, EXPECTED_P4_COMBINED_SHA256)
        self.assertEqual(bundle.data_version, "p4-seed-targeted-v2")

    def test_manifest_records_combined_method_hashes_and_counts(self):
        config = P4CombinedTrainingConfig()
        bundle = load_p4_combined_dataset_bundle(config)

        manifest = build_p4_training_manifest(
            config,
            bundle,
            resolved_model=Path("/models/qwen"),
            trainable_parameters=123,
        )

        self.assertEqual(manifest["method"], "qlora-p4-seed-targeted-v2")
        self.assertEqual(manifest["data_version"], "p4-seed-targeted-v2")
        self.assertEqual(manifest["dataset_sha256"], EXPECTED_P4_COMBINED_SHA256)
        self.assertEqual(manifest["train_count"], 1200)
        self.assertEqual(manifest["validation_count"], 300)
        self.assertEqual(manifest["num_train_epochs"], 1.0)

    def test_targeted_hash_drift_fails_before_training_environment_checks(self):
        source = P4CombinedTrainingConfig().targeted_train_path
        with tempfile.TemporaryDirectory() as directory:
            tampered = Path(directory) / "targeted.jsonl"
            tampered.write_bytes(source.read_bytes() + b"\n")

            with self.assertRaisesRegex(P4QloraError, "targeted dataset SHA-256"):
                load_p4_combined_dataset_bundle(
                    P4CombinedTrainingConfig(targeted_train_path=tampered)
                )


if __name__ == "__main__":
    unittest.main()
