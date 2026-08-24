import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path

from guard.taxonomy import RiskCategory
from training.contrastive_catalog import CONTRASTIVE_PAIRS
from training.contrastive_dataset import (
    build_contrastive_manifest,
    canonical_jsonl_bytes,
    generate_contrastive_dataset,
    validate_contrastive_profile,
)
from training.data_quality import (
    canonical_context,
    load_eval_isolation_keys,
    load_training_jsonl,
    request_fingerprint,
)
from training.seed_dataset import generate_seed_dataset
from training.targeted_dataset import generate_targeted_dataset


ROOT = Path(__file__).resolve().parents[1]


class ContrastiveDatasetTests(unittest.TestCase):
    def test_model_inputs_do_not_contain_contrastive_answer_markers(self):
        train, validation = generate_contrastive_dataset()

        for record in train + validation:
            source = record.input.context.source or ""
            self.assertNotIn("role=", source)
            self.assertNotIn("bounded_local_operation", source)
            self.assertNotIn("protected_or_external_effect", source)
            serialized_context = json.dumps(
                record.input.context.model_dump(mode="json"), sort_keys=True
            )
            self.assertNotIn("contrastive", serialized_context)
            for pair in CONTRASTIVE_PAIRS:
                self.assertNotIn(pair.pair_id, serialized_context)

    def test_sensitive_write_does_not_claim_dns_configuration_changes(self):
        train, validation = generate_contrastive_dataset()
        sensitive_commands = [
            record.input.command
            for record in train + validation
            if record.output.category is RiskCategory.SENSITIVE_WRITE
        ]

        self.assertFalse(
            any("/etc/resolv.conf" in command for command in sensitive_commands)
        )
        self.assertFalse(any("/etc/hosts" in command for command in sensitive_commands))

    def test_verified_remote_benign_inputs_disclose_trust_and_no_execution(self):
        train, validation = generate_contrastive_dataset()
        verified_downloads = [
            record
            for record in train + validation
            if record.output.category is RiskCategory.BENIGN
            and "curl " in record.input.command
            and ("sha256sum -c" in record.input.command or "gpg --verify" in record.input.command)
        ]

        self.assertTrue(verified_downloads)
        for record in verified_downloads:
            source = record.input.context.source or ""
            self.assertTrue("approved" in source or "trusted" in source)
            self.assertIn("no_execution", source)

    def test_policy_overrides_calibrate_setuid_and_unbounded_process_impacts(self):
        train, validation = generate_contrastive_dataset()
        records = train + validation
        setuid = [
            record for record in records
            if "helper_has_setuid" in (record.input.context.source or "")
        ]
        unbounded_processes = [
            record for record in records
            if ":(){" in record.input.command
            or "replicas=4096" in record.input.command
        ]

        self.assertTrue(setuid)
        self.assertTrue(unbounded_processes)
        for record in setuid:
            self.assertEqual(record.output.decision.value, "review")
            self.assertEqual(record.output.severity.value, "medium")
        for record in unbounded_processes:
            self.assertEqual(record.output.decision.value, "block")
            self.assertEqual(record.output.severity.value, "high")

    def test_generated_pairs_cover_current_false_positive_and_false_negative_shapes(self):
        train, validation = generate_contrastive_dataset()
        records = train + validation
        benign_commands = [
            record.input.command
            for record in records
            if record.output.category is RiskCategory.BENIGN
        ]
        risky_commands = [
            record.input.command
            for record in records
            if record.output.category is not RiskCategory.BENIGN
        ]
        risky_sources = [
            record.input.context.source or ""
            for record in records
            if record.output.category is not RiskCategory.BENIGN
        ]

        for shape in (
            "compileall.compile_dir",
            "ps -u",
            "apt-get update",
            "gpg --verify",
            "struct.unpack",
        ):
            with self.subTest(benign_shape=shape):
                self.assertTrue(any(shape in command for command in benign_commands))
        for shape in ("stratum+tcp", "urlretrieve", "/etc/"):
            with self.subTest(risky_shape=shape):
                self.assertTrue(any(shape in command for command in risky_commands))
        self.assertTrue(any("setuid" in source for source in risky_sources))

    def test_generation_has_literal_size_ids_batches_and_category_profile(self):
        train, validation = generate_contrastive_dataset()
        records = train + validation

        self.assertEqual((len(train), len(validation)), (800, 200))
        self.assertEqual(train[0].sample_id, "TR-001501")
        self.assertEqual(train[-1].sample_id, "TR-002300")
        self.assertEqual(validation[0].sample_id, "TR-002301")
        self.assertEqual(validation[-1].sample_id, "TR-002500")
        self.assertEqual(
            Counter(record.output.category for record in records),
            Counter(
                {
                    RiskCategory.BENIGN: 500,
                    RiskCategory.SENSITIVE_WRITE: 150,
                    RiskCategory.REMOTE_EXECUTION: 70,
                    RiskCategory.UNSAFE_DOWNLOAD: 70,
                    RiskCategory.NETWORK_CHANGE: 50,
                    RiskCategory.PRIVILEGE_ESCALATION: 50,
                    RiskCategory.RESOURCE_ABUSE: 40,
                    RiskCategory.DATA_EXFILTRATION: 30,
                    RiskCategory.CREDENTIAL_ACCESS: 10,
                    RiskCategory.DEFENSE_EVASION: 10,
                    RiskCategory.DESTRUCTIVE_OPERATION: 10,
                    RiskCategory.PERSISTENCE: 10,
                }
            ),
        )
        self.assertEqual(
            Counter(record.metadata.batch_id for record in records),
            Counter(
                {
                    f"p4-targeted-v2-batch-{number:03d}": 100
                    for number in range(1, 11)
                }
            ),
        )

    def test_profile_enforces_prior_data_and_eval_isolation(self):
        train, validation = generate_contrastive_dataset()
        seed_train, seed_validation = generate_seed_dataset()
        targeted_train, targeted_validation = generate_targeted_dataset()
        prior = [*seed_train, *seed_validation, *targeted_train, *targeted_validation]
        eval_keys = load_eval_isolation_keys(ROOT / "data" / "eval-v1" / "gold")

        summary = validate_contrastive_profile(
            train,
            validation,
            eval_keys,
            prior_request_fingerprints={
                request_fingerprint(record.input) for record in prior
            },
            prior_semantic_templates={
                record.metadata.semantic_template for record in prior
            },
            prior_commands={record.input.command for record in prior},
            prior_contexts={canonical_context(record.input.context) for record in prior},
            prior_context_sources={
                record.input.context.source or "" for record in prior
            },
        )

        self.assertEqual(summary.total, 1000)
        self.assertEqual(summary.splits, {"train": 800, "validation": 200})
        self.assertEqual(
            len({request_fingerprint(record.input) for record in train + validation}),
            1000,
        )
        self.assertTrue(
            {record.metadata.semantic_template for record in train}.isdisjoint(
                record.metadata.semantic_template for record in validation
            )
        )

    def test_profile_rejects_prior_command_even_when_context_differs(self):
        train, validation = generate_contrastive_dataset()
        seed_train, _ = generate_seed_dataset()
        prior_command = seed_train[0].input.command
        copied_input = train[0].input.model_copy(update={"command": prior_command})
        copied = train[0].model_copy(update={"input": copied_input})
        eval_keys = load_eval_isolation_keys(ROOT / "data" / "eval-v1" / "gold")

        with self.assertRaisesRegex(ValueError, "command duplicates prior P4 data"):
            validate_contrastive_profile(
                [copied, *train[1:]],
                validation,
                eval_keys,
                prior_request_fingerprints=set(),
                prior_semantic_templates=set(),
                prior_commands={prior_command},
                prior_contexts=set(),
                prior_context_sources=set(),
            )

    def test_manifest_records_current_fusion_diagnostics_and_hashes(self):
        train, validation = generate_contrastive_dataset()
        train_bytes = canonical_jsonl_bytes(train)
        validation_bytes = canonical_jsonl_bytes(validation)
        manifest = build_contrastive_manifest(
            train, validation, train_bytes, validation_bytes
        )

        self.assertEqual(manifest["data_version"], "p4-targeted-v2")
        self.assertIs(manifest["evaluation_adaptive"], True)
        self.assertEqual(
            manifest["diagnostic_basis"],
            {
                "report_version": "fusion-eval-report-v1",
                "total_samples": 100,
                "high_risk_allow_miss_count": 0,
                "risk_false_negative_count": 3,
                "benign_false_positive_count": 9,
                "category_error_count": 26,
                "effective_decision_error_count": 19,
            },
        )
        self.assertEqual(
            manifest["sha256"],
            {
                "train": hashlib.sha256(train_bytes).hexdigest(),
                "validation": hashlib.sha256(validation_bytes).hexdigest(),
            },
        )

    def test_committed_files_are_exact_generated_bundle(self):
        train_path = ROOT / "data" / "train" / "agent_security_targeted_train_v2.jsonl"
        validation_path = ROOT / "data" / "val" / "agent_security_targeted_validation_v2.jsonl"
        manifest_path = ROOT / "data" / "train" / "agent_security_targeted_v2_manifest.json"
        generated_train, generated_validation = generate_contrastive_dataset()

        self.assertEqual(train_path.read_bytes(), canonical_jsonl_bytes(generated_train))
        self.assertEqual(
            validation_path.read_bytes(), canonical_jsonl_bytes(generated_validation)
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["total"], 1000)
        self.assertEqual(
            (
                len(load_training_jsonl(train_path, expected_split="train")),
                len(load_training_jsonl(validation_path, expected_split="validation")),
            ),
            (800, 200),
        )


if __name__ == "__main__":
    unittest.main()
