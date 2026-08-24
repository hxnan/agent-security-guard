import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path

from guard.taxonomy import RiskCategory, ToolType
from training.data_quality import (
    load_eval_isolation_keys,
    load_eval_request_fingerprints,
    load_training_jsonl,
    request_fingerprint,
)
from training.targeted_dataset import (
    build_targeted_manifest,
    canonical_jsonl_bytes,
    generate_targeted_dataset,
    validate_targeted_profile,
)
from training.seed_dataset import generate_seed_dataset


ROOT = Path(__file__).resolve().parents[1]


class TargetedDatasetTests(unittest.TestCase):
    def test_generation_has_exact_ids_splits_batches_and_unique_requests(self):
        train, validation = generate_targeted_dataset()
        records = train + validation

        self.assertEqual((len(train), len(validation)), (400, 100))
        self.assertEqual(train[0].sample_id, "TR-001001")
        self.assertEqual(train[-1].sample_id, "TR-001400")
        self.assertEqual(validation[0].sample_id, "TR-001401")
        self.assertEqual(validation[-1].sample_id, "TR-001500")
        self.assertEqual(
            Counter(record.metadata.batch_id for record in records),
            Counter(
                {f"p4-targeted-v1-batch-{number:03d}": 100 for number in range(1, 6)}
            ),
        )
        self.assertEqual(
            len({request_fingerprint(record.input) for record in records}), 500
        )

    def test_generation_has_expected_category_rows_and_semantic_split_isolation(self):
        train, validation = generate_targeted_dataset()
        records = train + validation

        self.assertEqual(
            Counter(record.output.category for record in records),
            Counter(
                {
                    RiskCategory.BENIGN: 200,
                    RiskCategory.REMOTE_EXECUTION: 80,
                    RiskCategory.PRIVILEGE_ESCALATION: 50,
                    RiskCategory.RESOURCE_ABUSE: 40,
                    RiskCategory.DATA_EXFILTRATION: 20,
                    RiskCategory.SENSITIVE_WRITE: 30,
                    RiskCategory.UNSAFE_DOWNLOAD: 30,
                    RiskCategory.PERSISTENCE: 10,
                    RiskCategory.NETWORK_CHANGE: 10,
                    RiskCategory.DEFENSE_EVASION: 10,
                    RiskCategory.DESTRUCTIVE_OPERATION: 10,
                    RiskCategory.CREDENTIAL_ACCESS: 10,
                }
            ),
        )
        self.assertTrue(
            {record.metadata.semantic_template for record in train}.isdisjoint(
                record.metadata.semantic_template for record in validation
            )
        )

    def test_profile_passes_exact_frozen_eval_request_leakage_gate(self):
        train, validation = generate_targeted_dataset()

        summary = validate_targeted_profile(
            train,
            validation,
            load_eval_request_fingerprints(ROOT / "data" / "eval-v1" / "gold"),
        )

        self.assertEqual(summary.total, 500)
        self.assertEqual(summary.splits, {"train": 400, "validation": 100})

    def test_profile_rejects_seed_v1_request_and_semantic_overlap(self):
        seed_train, seed_validation = generate_seed_dataset()
        seed_records = seed_train + seed_validation
        seed_fingerprints = {
            request_fingerprint(record.input) for record in seed_records
        }
        seed_templates = {
            record.metadata.semantic_template for record in seed_records
        }
        train, validation = generate_targeted_dataset()
        copied_request = train[0].model_copy(update={"input": seed_records[0].input})

        with self.assertRaisesRegex(
            ValueError, "request duplicates P4 Seed V1"
        ):
            validate_targeted_profile(
                [copied_request, *train[1:]],
                validation,
                set(),
                seed_request_fingerprints=seed_fingerprints,
                seed_semantic_templates=seed_templates,
            )

        copied_metadata = train[0].metadata.model_copy(
            update={"semantic_template": seed_records[0].metadata.semantic_template}
        )
        copied_template = train[0].model_copy(update={"metadata": copied_metadata})
        with self.assertRaisesRegex(
            ValueError, "semantic_template overlaps P4 Seed V1"
        ):
            validate_targeted_profile(
                [copied_template, *train[1:]],
                validation,
                set(),
                seed_request_fingerprints=seed_fingerprints,
                seed_semantic_templates=seed_templates,
            )

    def test_profile_rejects_independent_eval_component_overlap(self):
        eval_keys = load_eval_isolation_keys(ROOT / "data" / "eval-v1" / "gold")
        train, validation = generate_targeted_dataset()
        tool_type, command = next(iter(eval_keys.tool_commands))
        copied_input = train[0].input.model_copy(
            update={"type": ToolType(tool_type), "command": command}
        )
        copied_command = train[0].model_copy(update={"input": copied_input})

        with self.assertRaisesRegex(ValueError, "command duplicates frozen Eval V1"):
            validate_targeted_profile(
                [copied_command, *train[1:]],
                validation,
                eval_keys.request_fingerprints,
                eval_tool_commands=eval_keys.tool_commands,
                eval_contexts=eval_keys.contexts,
                eval_semantic_templates=eval_keys.semantic_templates,
            )

        copied_context = train[0].input.context.model_validate_json(
            next(iter(eval_keys.contexts))
        )
        copied_input = train[0].input.model_copy(update={"context": copied_context})
        copied_record = train[0].model_copy(update={"input": copied_input})
        with self.assertRaisesRegex(ValueError, "context duplicates frozen Eval V1"):
            validate_targeted_profile(
                [copied_record, *train[1:]],
                validation,
                eval_keys.request_fingerprints,
                eval_tool_commands=eval_keys.tool_commands,
                eval_contexts=eval_keys.contexts,
                eval_semantic_templates=eval_keys.semantic_templates,
            )

        copied_metadata = train[0].metadata.model_copy(
            update={"semantic_template": next(iter(eval_keys.semantic_templates))}
        )
        copied_record = train[0].model_copy(update={"metadata": copied_metadata})
        with self.assertRaisesRegex(
            ValueError, "semantic_template duplicates frozen Eval V1"
        ):
            validate_targeted_profile(
                [copied_record, *train[1:]],
                validation,
                eval_keys.request_fingerprints,
                eval_tool_commands=eval_keys.tool_commands,
                eval_contexts=eval_keys.contexts,
                eval_semantic_templates=eval_keys.semantic_templates,
            )

    def test_manifest_is_deterministic_and_discloses_eval_adaptation(self):
        train, validation = generate_targeted_dataset()
        train_bytes = canonical_jsonl_bytes(train)
        validation_bytes = canonical_jsonl_bytes(validation)

        manifest = build_targeted_manifest(
            train, validation, train_bytes, validation_bytes
        )

        self.assertEqual(manifest["data_version"], "p4-targeted-v1")
        self.assertIs(manifest["evaluation_adaptive"], True)
        self.assertEqual(
            manifest["diagnostic_basis"],
            {
                "report_version": "p4-adapter-eval-report-v1",
                "total_samples": 100,
                "high_risk_allow_miss_count": 1,
                "risk_false_negative_count": 3,
                "benign_false_positive_count": 11,
            },
        )
        self.assertEqual(
            manifest["sha256"],
            {
                "train": hashlib.sha256(train_bytes).hexdigest(),
                "validation": hashlib.sha256(validation_bytes).hexdigest(),
            },
        )

    def test_committed_targeted_files_are_exact_generated_bundle(self):
        train_path = ROOT / "data" / "train" / "agent_security_targeted_train_v1.jsonl"
        validation_path = (
            ROOT / "data" / "val" / "agent_security_targeted_validation_v1.jsonl"
        )
        manifest_path = (
            ROOT / "data" / "train" / "agent_security_targeted_v1_manifest.json"
        )
        generated_train, generated_validation = generate_targeted_dataset()

        self.assertEqual(train_path.read_bytes(), canonical_jsonl_bytes(generated_train))
        self.assertEqual(
            validation_path.read_bytes(), canonical_jsonl_bytes(generated_validation)
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["total"], 500)
        loaded_train = load_training_jsonl(train_path, expected_split="train")
        loaded_validation = load_training_jsonl(
            validation_path, expected_split="validation"
        )
        self.assertEqual((len(loaded_train), len(loaded_validation)), (400, 100))


if __name__ == "__main__":
    unittest.main()
