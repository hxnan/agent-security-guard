import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from guard.contracts import GuardRequest, GuardResult
from guard.taxonomy import RiskCategory, Severity


class SmokeDataTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module("guard.smoke_data")
        except ModuleNotFoundError:
            self.fail("guard.smoke_data is missing")

    def test_generation_has_literal_split_and_category_counts(self):
        api = self.api()
        train, validation = api.generate_smoke_records()

        self.assertEqual(len(train), 96)
        self.assertEqual(len(validation), 24)
        for category in RiskCategory:
            self.assertEqual(
                sum(record.result.category is category for record in train),
                8,
                category.value,
            )
            self.assertEqual(
                sum(record.result.category is category for record in validation),
                2,
                category.value,
            )

    def test_every_nested_contract_is_runtime_valid(self):
        api = self.api()
        train, validation = api.generate_smoke_records()

        for record in train + validation:
            GuardRequest.model_validate(record.request.model_dump(mode="json"))
            GuardResult.model_validate(record.result.model_dump(mode="json"))
            self.assertEqual(record.data_version, "smoke-v1")
            self.assertEqual(record.generation_source, "curated-template-v1")

    def test_generation_is_deterministic_and_ids_are_unique(self):
        api = self.api()
        first = api.generate_smoke_records()
        second = api.generate_smoke_records()

        self.assertEqual(
            [[record.to_dict() for record in split] for split in first],
            [[record.to_dict() for record in split] for split in second],
        )
        all_records = first[0] + first[1]
        self.assertEqual(len({record.sample_id for record in all_records}), 120)

    def test_split_templates_are_disjoint_and_do_not_overlap_eval(self):
        api = self.api()
        train, validation = api.generate_smoke_records()
        train_templates = {record.semantic_template for record in train}
        validation_templates = {record.semantic_template for record in validation}
        train_requests = {
            (record.request.type, record.request.command) for record in train
        }
        validation_requests = {
            (record.request.type, record.request.command) for record in validation
        }

        self.assertTrue(train_templates.isdisjoint(validation_templates))
        self.assertTrue(train_requests.isdisjoint(validation_requests))
        self.assertEqual(len(train_templates), 12)
        self.assertEqual(len(validation_templates), 12)
        summary = api.validate_smoke_records(
            train,
            validation,
            eval_templates={"eval_only_template"},
        )
        self.assertEqual(summary.total, 120)

        leaked = list(validation)
        leaked[0] = api.replace_record(
            leaked[0], semantic_template=next(iter(train_templates))
        )
        with self.assertRaisesRegex(api.SmokeDataError, "train/validation template"):
            api.validate_smoke_records(train, leaked, eval_templates=set())

        with self.assertRaisesRegex(api.SmokeDataError, "Eval V1 template"):
            api.validate_smoke_records(
                train,
                validation,
                eval_templates={train[0].semantic_template},
            )

    def test_duplicate_sample_id_is_rejected(self):
        api = self.api()
        train, validation = api.generate_smoke_records()
        changed = list(validation)
        changed[0] = api.replace_record(changed[0], sample_id=train[0].sample_id)

        with self.assertRaisesRegex(api.SmokeDataError, "duplicate sample_id"):
            api.validate_smoke_records(train, changed, eval_templates=set())

    def test_fixed_gold_fields_cannot_be_changed_on_disk(self):
        api = self.api()
        train, validation = api.generate_smoke_records()
        mutations = (
            {"confidence": 0.1},
            {"model_version": "wrong"},
            {"policy_version": "wrong"},
            {"rule_hits": ["unexpected"]},
            {"evidence": ["different command"]},
        )
        for result_changes in mutations:
            with self.subTest(result_changes=result_changes):
                changed = list(train)
                changed[0] = api.replace_record(
                    changed[0],
                    result=changed[0].result.model_copy(update=result_changes),
                )
                with self.assertRaisesRegex(api.SmokeDataError, "fixed gold contract"):
                    api.validate_smoke_records(changed, validation, eval_templates=set())

    def test_category_default_labels_cannot_be_changed(self):
        api = self.api()
        train, validation = api.generate_smoke_records()
        changed = list(train)
        changed[0] = api.replace_record(
            changed[0],
            result=changed[0].result.model_copy(update={"severity": Severity.LOW}),
        )
        with self.assertRaisesRegex(api.SmokeDataError, "category defaults"):
            api.validate_smoke_records(changed, validation, eval_templates=set())

    def test_sample_and_template_conventions_cannot_be_changed_on_disk(self):
        api = self.api()
        train, validation = api.generate_smoke_records()
        mutations = (
            {"sample_id": "tampered"},
            {"semantic_template": "unrelated_family"},
        )
        for changes in mutations:
            with self.subTest(changes=changes):
                changed = list(train)
                changed[0] = api.replace_record(changed[0], **changes)
                with self.assertRaisesRegex(api.SmokeDataError, "naming convention"):
                    api.validate_smoke_records(changed, validation, eval_templates=set())

    def test_writer_refuses_existing_outputs_without_force(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "smoke-v1"
            output_dir.mkdir()
            (output_dir / "train.jsonl").write_text("keep", encoding="utf-8")

            with self.assertRaisesRegex(api.SmokeDataError, "already exists"):
                api.write_smoke_dataset(output_dir, force=False)

            api.write_smoke_dataset(output_dir, force=True)
            self.assertEqual(
                len((output_dir / "train.jsonl").read_text(encoding="utf-8").splitlines()),
                96,
            )
            self.assertEqual(
                len(
                    (output_dir / "validation.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                ),
                24,
            )


class SmokeDataCliTests(unittest.TestCase):
    repository_root = Path(__file__).resolve().parents[1]
    script = repository_root / "scripts" / "generate_smoke_data.py"

    def test_cli_generates_from_another_working_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            output_dir = temporary_path / "generated"
            result = subprocess.run(
                [sys.executable, str(self.script), "--output-dir", str(output_dir)],
                cwd=temporary_path,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["total"], 120)
            self.assertTrue((output_dir / "train.jsonl").is_file())


if __name__ == "__main__":
    unittest.main()
