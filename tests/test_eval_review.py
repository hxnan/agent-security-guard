import unittest

from pydantic import ValidationError

from guard.eval_review import (
    EvalReviewAnswer,
    build_blind_review_packet,
    compare_review_answers,
)
from guard.taxonomy import Decision, RiskCategory, Severity
from tests.test_eval_dataset import make_record


def make_answer(**overrides):
    payload = {
        "sample_id": "EV001",
        "decision": Decision.ALLOW,
        "severity": Severity.NONE,
        "category": RiskCategory.BENIGN,
        "summary": "查看项目状态",
        "confidence": 0.99,
        "evidence": ["git status --short"],
    }
    payload.update(overrides)
    return EvalReviewAnswer(**payload)


class EvalBlindReviewTests(unittest.TestCase):
    def test_blind_packet_exposes_only_id_and_request(self):
        packet = build_blind_review_packet([make_record()])
        self.assertEqual(len(packet), 1)
        payload = packet[0].model_dump(mode="json")
        self.assertEqual(set(payload), {"sample_id", "request"})
        self.assertNotIn("expected", payload)
        self.assertNotIn("metadata", payload)

    def test_review_answer_requires_core_fields(self):
        with self.assertRaises(ValidationError):
            EvalReviewAnswer(
                sample_id="EV001",
                decision=Decision.ALLOW,
                severity=Severity.NONE,
                summary="查看项目状态",
                confidence=0.99,
                evidence=[],
            )

    def test_compare_reports_substantive_label_difference(self):
        record = make_record()
        answer = make_answer(category=RiskCategory.CREDENTIAL_ACCESS)
        comparisons = compare_review_answers([record], [answer])
        self.assertEqual(len(comparisons), 1)
        self.assertEqual(comparisons[0].sample_id, "EV001")
        self.assertEqual(comparisons[0].label_differences, ("category",))
        self.assertFalse(comparisons[0].summary_differs)

    def test_compare_reports_summary_paraphrase_without_label_dispute(self):
        record = make_record()
        answer = make_answer(summary="查看仓库状态")
        comparisons = compare_review_answers([record], [answer])
        self.assertEqual(len(comparisons), 1)
        self.assertEqual(comparisons[0].label_differences, ())
        self.assertTrue(comparisons[0].summary_differs)

    def test_compare_ignores_support_only_differences(self):
        record = make_record()
        answer = make_answer(confidence=0.90, evidence=["independent evidence"])
        self.assertEqual(compare_review_answers([record], [answer]), [])


if __name__ == "__main__":
    unittest.main()
