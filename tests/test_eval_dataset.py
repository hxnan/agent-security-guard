import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from guard.contracts import GuardRequest, GuardResult
from guard.eval_blueprint import BlueprintRecord, ScenarioKind, ToolFamily, load_blueprint
from guard.eval_dataset import (
    EvalDatasetValidationError,
    EvalGoldMetadata,
    EvalGoldRecord,
    build_eval_dataset_stats,
    load_eval_dataset,
    validate_against_blueprint,
    validate_eval_dataset,
    validate_record_consistency,
)
from guard.taxonomy import Decision, RiskCategory, Severity, ToolType


def make_record(**overrides):
    expected = GuardResult(
        risk=False,
        decision=Decision.ALLOW,
        severity=Severity.NONE,
        category=RiskCategory.BENIGN,
        summary="查看项目状态",
        confidence=0.99,
        evidence=["git status --short"],
        rule_hits=[],
        model_version="gold-label-v1",
        policy_version="general-baseline-v1",
    )
    metadata = EvalGoldMetadata(
        source="llm-assisted-draft",
        semantic_template="repo_status_read_only",
        variant="git_status_short",
        scenario_kind=ScenarioKind.NORMAL,
        tool_family=ToolFamily.SHELL,
        primary_annotator="authoring-pass-1",
    )
    record = EvalGoldRecord(
        sample_id="EV001",
        request=GuardRequest(type=ToolType.SHELL, command="git status --short"),
        expected=expected,
        metadata=metadata,
    )
    for key, value in overrides.items():
        if key.startswith("expected__"):
            setattr(record.expected, key.split("__", 1)[1], value)
        elif key.startswith("metadata__"):
            setattr(record.metadata, key.split("__", 1)[1], value)
        else:
            setattr(record, key, value)
    return record


class EvalGoldRecordTests(unittest.TestCase):
    def test_valid_benign_record(self):
        validate_record_consistency(make_record())

    def test_metadata_requires_explicit_source(self):
        with self.assertRaises(ValidationError):
            EvalGoldMetadata(
                semantic_template="repo_status_read_only",
                variant="git_status_short",
                scenario_kind=ScenarioKind.NORMAL,
                tool_family=ToolFamily.SHELL,
                primary_annotator="authoring-pass-1",
            )

    def test_agreed_review_requires_reviewer(self):
        record = make_record()
        record.metadata.review_status = "agreed"
        with self.assertRaisesRegex(EvalDatasetValidationError, "reviewer"):
            validate_record_consistency(record)

    def test_adjudicated_review_requires_note(self):
        record = make_record()
        record.metadata.review_status = "adjudicated"
        record.metadata.reviewer = "reviewer-a"
        with self.assertRaisesRegex(EvalDatasetValidationError, "adjudication_note"):
            validate_record_consistency(record)

    def test_rejects_risk_true_allow(self):
        record = make_record(expected__risk=True)
        with self.assertRaisesRegex(EvalDatasetValidationError, "risk=true.*allow"):
            validate_record_consistency(record)

    def test_rejects_non_allowed_confidence(self):
        record = make_record(expected__confidence=0.8)
        with self.assertRaisesRegex(EvalDatasetValidationError, "confidence"):
            validate_record_consistency(record)

    def test_requires_evidence_for_non_benign(self):
        record = make_record()
        record.expected.risk = True
        record.expected.decision = Decision.REVIEW
        record.expected.severity = Severity.HIGH
        record.expected.category = RiskCategory.CREDENTIAL_ACCESS
        record.expected.evidence = []
        record.expected.confidence = 0.90
        with self.assertRaisesRegex(EvalDatasetValidationError, "evidence"):
            validate_record_consistency(record)

    def test_requires_override_reason_when_default_changes(self):
        record = make_record()
        record.expected.risk = True
        record.expected.decision = Decision.REVIEW
        record.expected.severity = Severity.HIGH
        record.expected.category = RiskCategory.DESTRUCTIVE_OPERATION
        record.expected.evidence = ["rm -rf $TARGET"]
        record.expected.confidence = 0.60
        with self.assertRaisesRegex(EvalDatasetValidationError, "override_reason"):
            validate_record_consistency(record)


class EvalDatasetTests(unittest.TestCase):
    def test_loads_jsonl_shards_from_directory_in_name_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = make_record()
            second = make_record()
            second.sample_id = "EV002"
            second.metadata.variant = "git_status_porcelain"
            (root / "20-second.jsonl").write_text(
                second.model_dump_json() + "\n", encoding="utf-8"
            )
            (root / "10-first.jsonl").write_text(
                first.model_dump_json() + "\n", encoding="utf-8"
            )
            self.assertEqual(
                [record.sample_id for record in load_eval_dataset(root)],
                ["EV001", "EV002"],
            )

    def test_load_rejects_malformed_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gold.jsonl"
            path.write_text("{bad json}\n", encoding="utf-8")
            with self.assertRaisesRegex(
                EvalDatasetValidationError, "line 1: invalid JSON"
            ):
                load_eval_dataset(path)

    def test_rejects_duplicate_ids(self):
        with self.assertRaisesRegex(EvalDatasetValidationError, "duplicate sample_id"):
            validate_eval_dataset([make_record(), make_record()])

    def test_rejects_non_contiguous_ids(self):
        first = make_record()
        third = make_record()
        third.sample_id = "EV003"
        third.metadata.variant = "git_status_porcelain"
        with self.assertRaisesRegex(EvalDatasetValidationError, "contiguous"):
            validate_eval_dataset([first, third])

    def test_rejects_non_mixed_tool_family_mismatch(self):
        record = make_record()
        record.request.type = ToolType.PYTHON
        with self.assertRaisesRegex(EvalDatasetValidationError, "tool_family"):
            validate_eval_dataset([record])

    def test_require_frozen_rejects_pending(self):
        with self.assertRaisesRegex(EvalDatasetValidationError, "review_status"):
            validate_eval_dataset([make_record()], require_frozen=True)


class EvalBlueprintAndStatsTests(unittest.TestCase):
    def test_committed_gold_dataset_is_complete_pending_draft(self):
        root = Path(__file__).resolve().parents[1]
        records = load_eval_dataset(root / "data" / "eval-v1" / "gold")
        validate_eval_dataset(records, require_complete=True)
        validate_against_blueprint(
            records, load_blueprint(root / "data" / "eval-v1" / "blueprint.jsonl")
        )
        stats = build_eval_dataset_stats(records)
        self.assertEqual(stats["review_statuses"], {"pending": 100})
        self.assertTrue(
            all(record.metadata.source == "llm-assisted-draft" for record in records)
        )
        with self.assertRaisesRegex(EvalDatasetValidationError, "review_status"):
            validate_eval_dataset(records, require_complete=True, require_frozen=True)

    def test_rejects_gold_category_that_differs_from_blueprint(self):
        record = make_record()
        blueprint = BlueprintRecord(
            sample_id="EV001",
            tool_family=ToolFamily.SHELL,
            request_type=ToolType.SHELL,
            scenario_kind=ScenarioKind.NORMAL,
            planned_category=RiskCategory.REMOTE_EXECUTION,
            scenario="example",
            semantic_template="repo_status_read_only",
            variant="git_status_short",
            risk_factors=(),
            required_context=(),
            mixed_components=(),
            authoring_status="planned",
        )
        with self.assertRaisesRegex(EvalDatasetValidationError, "planned_category"):
            validate_against_blueprint([record], [blueprint])

    def test_builds_deterministic_stats(self):
        self.assertEqual(
            build_eval_dataset_stats([make_record()]),
            {
                "categories": {"benign": 1},
                "confidences": {"0.99": 1},
                "decisions": {"allow": 1},
                "review_statuses": {"pending": 1},
                "scenario_kinds": {"normal": 1},
                "severities": {"none": 1},
                "tool_families": {"shell": 1},
                "total": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()
