import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from training.data_quality import (
    DatasetQualityError,
    load_eval_request_fingerprints,
    load_training_jsonl,
    request_fingerprint,
    validate_dataset_bundle,
)
from training.schema import TrainingExample


def row(
    sample_id="TR-000001",
    split="train",
    command="git status --short",
    template="benign_git_status_train",
    category="benign",
    generation_source="curated_template_v1",
    **overrides,
):
    risky = category != "benign"
    value = {
        "id": sample_id,
        "instruction": "Analyze this Agent tool call for security risk.",
        "input": {
            "type": "shell",
            "command": command,
            "context": {"cwd": "/workspace", "privilege": "user"},
        },
        "output": {
            "schema_version": "1.0",
            "risk": risky,
            "decision": "review" if risky else "allow",
            "severity": "high" if risky else "none",
            "category": category,
            "summary": "需要安全复核" if risky else "正常只读操作",
            "confidence": 0.9,
            "evidence": [command],
            "rule_hits": [],
            "model_version": "training-target-v1",
            "policy_version": "policy-v1",
        },
        "metadata": {
            "data_version": "p4-train-v1",
            "generation_source": generation_source,
            "semantic_template": template,
            "split": split,
        },
    }
    value.update(overrides)
    return value


class TrainingExampleContractTests(unittest.TestCase):
    def test_valid_row_reuses_request_and_result_contracts(self):
        example = TrainingExample.model_validate(row())

        self.assertEqual(example.sample_id, "TR-000001")
        self.assertEqual(example.input.command, "git status --short")
        self.assertEqual(example.output.category.value, "benign")

    def test_rejects_bad_id_split_and_template_shape(self):
        value = row(sample_id="EV001", split="test", template="Not Snake Case")

        with self.assertRaises(ValidationError):
            TrainingExample.model_validate(value)

    def test_rejects_benign_risk_contradiction(self):
        value = row()
        value["output"]["risk"] = True

        with self.assertRaisesRegex(ValidationError, "benign output must be risk=false"):
            TrainingExample.model_validate(value)

    def test_rejects_non_benign_allow_contradiction(self):
        value = row(category="credential_access")
        value["output"]["decision"] = "allow"

        with self.assertRaisesRegex(ValidationError, "non-benign output cannot allow"):
            TrainingExample.model_validate(value)

    def test_rejects_coerced_risk_and_confidence_scalars(self):
        value = row()
        value["output"]["risk"] = "false"
        value["output"]["confidence"] = "0.9"

        with self.assertRaisesRegex(ValidationError, "output.risk must be a boolean"):
            TrainingExample.model_validate(value)

    def test_rejects_incomplete_guard_result_even_when_contract_has_defaults(self):
        value = row()
        for field in ("schema_version", "evidence", "rule_hits"):
            value["output"].pop(field)

        with self.assertRaisesRegex(ValidationError, "output fields must exactly match"):
            TrainingExample.model_validate(value)

    def test_rejects_unknown_guard_context_fields_before_pydantic_drops_them(self):
        value = row()
        value["input"]["context"]["unexpected"] = "EV001"

        with self.assertRaisesRegex(ValidationError, "input.context has extra fields"):
            TrainingExample.model_validate(value)

    def test_rejects_non_chinese_summary(self):
        value = row()
        value["output"]["summary"] = "safe read only operation"

        with self.assertRaisesRegex(ValidationError, "summary must contain Chinese"):
            TrainingExample.model_validate(value)

    def test_block_requires_high_or_critical_severity(self):
        value = row(category="unsafe_download")
        value["output"]["decision"] = "block"
        value["output"]["severity"] = "medium"

        with self.assertRaisesRegex(ValidationError, "block output requires high or critical"):
            TrainingExample.model_validate(value)


class TrainingJsonlLoaderTests(unittest.TestCase):
    def write_lines(self, directory, *lines):
        path = Path(directory) / "records.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_loads_rows_and_enforces_expected_split(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_lines(directory, json.dumps(row()))

            examples = load_training_jsonl(path, expected_split="train")

        self.assertEqual([item.sample_id for item in examples], ["TR-000001"])

    def test_reports_malformed_json_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_lines(directory, json.dumps(row()), "{")

            with self.assertRaisesRegex(DatasetQualityError, "line 2: invalid JSON"):
                load_training_jsonl(path, expected_split="train")

    def test_wraps_invalid_utf8_without_unicode_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            path.write_bytes(b"\xff\xfe")

            with self.assertRaisesRegex(DatasetQualityError, "cannot read"):
                load_training_jsonl(path, expected_split="train")

    def test_rejects_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_lines(
                directory,
                json.dumps(row()),
                json.dumps(row(command="pwd", template="benign_pwd_train")),
            )

            with self.assertRaisesRegex(DatasetQualityError, "duplicate id TR-000001"):
                load_training_jsonl(path, expected_split="train")

    def test_rejects_row_from_wrong_split(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_lines(directory, json.dumps(row(split="validation")))

            with self.assertRaisesRegex(DatasetQualityError, "metadata.split must be train"):
                load_training_jsonl(path, expected_split="train")

    def test_eval_request_loader_wraps_non_object_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "part.jsonl"
            path.write_text("[]\n", encoding="utf-8")

            with self.assertRaisesRegex(DatasetQualityError, "invalid Eval request"):
                load_eval_request_fingerprints(directory)

    def test_eval_request_loader_rejects_empty_fingerprint_source(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "part.jsonl").write_text("", encoding="utf-8")

            with self.assertRaisesRegex(DatasetQualityError, "contains no requests"):
                load_eval_request_fingerprints(directory)

    def test_eval_request_loader_wraps_invalid_utf8(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "part.jsonl").write_bytes(b"\xff\xfe")

            with self.assertRaisesRegex(DatasetQualityError, "cannot read Eval shard"):
                load_eval_request_fingerprints(directory)


class TrainingBundleQualityTests(unittest.TestCase):
    def example(self, **changes):
        return TrainingExample.model_validate(row(**changes))

    def test_valid_bundle_reports_deterministic_counts(self):
        train = [self.example()]
        validation = [
            self.example(
                sample_id="TR-000002",
                split="validation",
                command="cat ~/.ssh/id_rsa",
                template="credential_private_key_validation",
                category="credential_access",
            )
        ]

        report = validate_dataset_bundle(train, validation, set())

        self.assertEqual(
            report.to_dict(),
            {
                "status": "ok",
                "train": {"samples": 1, "categories": {"benign": 1}},
                "validation": {
                    "samples": 1,
                    "categories": {"credential_access": 1},
                },
                "errors": [],
            },
        )

    def test_rejects_empty_splits(self):
        report = validate_dataset_bundle([], [], set())

        self.assertEqual(
            report.errors,
            ("train split is empty", "validation split is empty"),
        )

    def test_rejects_cross_split_id_request_and_template_overlap(self):
        train = [self.example(template="shared_template")]
        validation = [
            self.example(
                sample_id="TR-000001",
                split="validation",
                template="shared_template",
            )
        ]

        report = validate_dataset_bundle(train, validation, set())

        self.assertEqual(
            report.errors,
            (
                "cross-split id overlap: TR-000001",
                "cross-split request overlap: TR-000001",
                "cross-split semantic_template overlap: shared_template",
            ),
        )

    def test_rejects_eval_markers_and_exact_eval_request(self):
        train = [
            self.example(
                command="echo EV001",
                template="copied_eval_case",
                generation_source="eval_v1_gold",
            )
        ]
        eval_fingerprints = {request_fingerprint(train[0].input)}
        validation = [
            self.example(
                sample_id="TR-000002",
                split="validation",
                command="pwd",
                template="benign_pwd_validation",
            )
        ]

        report = validate_dataset_bundle(train, validation, eval_fingerprints)

        self.assertEqual(
            report.errors,
            (
                "TR-000001 contains Eval sample identifier EV001",
                "TR-000001 contains forbidden Eval/Gold provenance",
                "TR-000001 request duplicates frozen Eval V1",
            ),
        )

    def test_provenance_scanner_handles_snake_case_without_golden_false_positive(self):
        copied = self.example(generation_source="eval_v1_copy")
        safe = self.example(
            sample_id="TR-000002",
            split="validation",
            command="pwd",
            template="golden_template",
            generation_source="golden_template",
        )

        report = validate_dataset_bundle([copied], [safe], set())

        self.assertEqual(
            report.errors,
            ("TR-000001 contains forbidden Eval/Gold provenance",),
        )

    def test_provenance_scanner_rejects_compact_eval_version(self):
        copied = self.example(generation_source="evalv1_copy")
        validation = [
            self.example(
                sample_id="TR-000002",
                split="validation",
                command="pwd",
                template="benign_pwd_validation",
            )
        ]

        report = validate_dataset_bundle([copied], validation, set())

        self.assertIn(
            "TR-000001 contains forbidden Eval/Gold provenance", report.errors
        )

    def test_rejects_eval_marker_next_to_underscores(self):
        train = [self.example(command="echo copied_EV001_case")]
        validation = [
            self.example(
                sample_id="TR-000002",
                split="validation",
                command="pwd",
                template="benign_pwd_validation",
            )
        ]

        report = validate_dataset_bundle(train, validation, set())

        self.assertIn(
            "TR-000001 contains Eval sample identifier EV001", report.errors
        )

    def test_rejects_output_model_and_policy_eval_provenance(self):
        model_copy = row()
        model_copy["output"]["model_version"] = "gold-label-v1"
        policy_copy = row(
            sample_id="TR-000002",
            split="validation",
            command="pwd",
            template="benign_pwd_validation",
        )
        policy_copy["output"]["policy_version"] = "eval-v1"

        report = validate_dataset_bundle(
            [TrainingExample.model_validate(model_copy)],
            [TrainingExample.model_validate(policy_copy)],
            set(),
        )

        self.assertEqual(
            report.errors,
            (
                "TR-000001 contains forbidden Eval/Gold provenance",
                "TR-000002 contains forbidden Eval/Gold provenance",
            ),
        )


if __name__ == "__main__":
    unittest.main()
