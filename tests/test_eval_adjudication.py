import json
from pathlib import Path
import tempfile
import unittest

from guard.eval_adjudication import (
    EvalAdjudicationRecord,
    EvalAdjudicationValidationError,
    load_adjudications,
    resolve_reviewed_dataset,
)
from guard.eval_review import EvalReviewAnswer
from guard.taxonomy import Decision, RiskCategory, Severity
from tests.test_eval_dataset import make_record


REVIEWER_ID = "independent-agent:gpt-5.6-sol"


def make_answer(**overrides):
    payload = {
        "sample_id": "EV001",
        "decision": Decision.ALLOW,
        "severity": Severity.NONE,
        "category": RiskCategory.BENIGN,
        "summary": "查看仓库状态",
        "confidence": 0.99,
        "evidence": ["git status --short"],
    }
    payload.update(overrides)
    return EvalReviewAnswer(**payload)


def make_adjudication(**overrides):
    payload = {
        "sample_id": "EV001",
        "resolution": "gold",
        "note": "保留原始 Gold 标签。",
    }
    payload.update(overrides)
    return EvalAdjudicationRecord(**payload)


class EvalAdjudicationTests(unittest.TestCase):
    def test_label_agreement_becomes_agreed_and_keeps_gold_result(self):
        gold = make_record()
        review = make_answer(summary="查看仓库状态")

        resolved = resolve_reviewed_dataset(
            [gold], [review], [], reviewer_id=REVIEWER_ID
        )

        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].expected.summary, gold.expected.summary)
        self.assertEqual(resolved[0].metadata.review_status.value, "agreed")
        self.assertEqual(resolved[0].metadata.reviewer, REVIEWER_ID)
        self.assertEqual(resolved[0].metadata.disputed_fields, [])
        self.assertIsNone(resolved[0].metadata.adjudication_note)
        self.assertEqual(gold.metadata.review_status.value, "pending")

    def test_label_disagreement_requires_adjudication(self):
        gold = make_record()
        review = make_answer(
            decision=Decision.REVIEW,
            severity=Severity.HIGH,
            category=RiskCategory.CREDENTIAL_ACCESS,
        )

        with self.assertRaisesRegex(
            EvalAdjudicationValidationError, "EV001.*requires adjudication"
        ):
            resolve_reviewed_dataset(
                [gold], [review], [], reviewer_id=REVIEWER_ID
            )

    def test_review_resolution_applies_reviewer_result_and_marks_adjudicated(self):
        gold = make_record()
        review = make_answer(
            decision=Decision.REVIEW,
            severity=Severity.HIGH,
            category=RiskCategory.CREDENTIAL_ACCESS,
            summary="读取敏感凭据",
            confidence=0.90,
            evidence=["credential-shaped file"],
        )
        adjudication = make_adjudication(
            resolution="review",
            note="独立复核更符合凭据访问边界。",
        )

        resolved = resolve_reviewed_dataset(
            [gold], [review], [adjudication], reviewer_id=REVIEWER_ID
        )[0]

        self.assertTrue(resolved.expected.risk)
        self.assertEqual(resolved.expected.decision, Decision.REVIEW)
        self.assertEqual(resolved.expected.severity, Severity.HIGH)
        self.assertEqual(resolved.expected.category, RiskCategory.CREDENTIAL_ACCESS)
        self.assertEqual(resolved.expected.summary, "读取敏感凭据")
        self.assertEqual(resolved.expected.confidence, 0.90)
        self.assertEqual(resolved.expected.evidence, ["credential-shaped file"])
        self.assertEqual(resolved.expected.model_version, "gold-label-v1")
        self.assertEqual(resolved.expected.policy_version, "general-baseline-v1")
        self.assertEqual(resolved.metadata.review_status.value, "adjudicated")
        self.assertEqual(resolved.metadata.reviewer, REVIEWER_ID)
        self.assertEqual(
            resolved.metadata.disputed_fields,
            ["decision", "severity", "category"],
        )
        self.assertEqual(
            resolved.metadata.adjudication_note,
            "独立复核更符合凭据访问边界。",
        )

    def test_gold_resolution_keeps_gold_result_and_records_disputed_fields(self):
        gold = make_record()
        review = make_answer(
            decision=Decision.REVIEW,
            severity=Severity.HIGH,
            category=RiskCategory.CREDENTIAL_ACCESS,
        )
        adjudication = make_adjudication(note="行为仍属于正常项目查询。")

        resolved = resolve_reviewed_dataset(
            [gold], [review], [adjudication], reviewer_id=REVIEWER_ID
        )[0]

        self.assertEqual(resolved.expected, gold.expected)
        self.assertEqual(resolved.metadata.review_status.value, "adjudicated")
        self.assertEqual(
            resolved.metadata.disputed_fields,
            ["decision", "severity", "category"],
        )
        self.assertEqual(resolved.metadata.adjudication_note, "行为仍属于正常项目查询。")

    def test_unused_adjudication_is_rejected(self):
        gold = make_record()
        review = make_answer()
        adjudication = make_adjudication()

        with self.assertRaisesRegex(
            EvalAdjudicationValidationError, "adjudication.*not required"
        ):
            resolve_reviewed_dataset(
                [gold], [review], [adjudication], reviewer_id=REVIEWER_ID
            )

    def test_review_answers_must_cover_all_gold_samples(self):
        with self.assertRaisesRegex(
            EvalAdjudicationValidationError, "review answers must exactly cover"
        ):
            resolve_reviewed_dataset(
                [make_record()], [], [], reviewer_id=REVIEWER_ID
            )

    def test_load_adjudications_rejects_duplicate_sample_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "adjudication.jsonl"
            row = make_adjudication().model_dump(mode="json")
            path.write_text(
                json.dumps(row, ensure_ascii=False) + "\n"
                + json.dumps(row, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                EvalAdjudicationValidationError, "duplicate adjudication"
            ):
                load_adjudications(path)


if __name__ == "__main__":
    unittest.main()
