import json
import unittest

from guard.baseline_output import parse_baseline_semantic_result
from guard.baseline_prompt import BASELINE_MODEL_VERSION, BASELINE_POLICY_VERSION
from guard.result_parsing import GeneratedResultError


def semantic_text(**overrides):
    payload = {
        "decision": "allow",
        "severity": "none",
        "category": "benign",
        "summary": "查看仓库状态",
        "confidence": 0.99,
        "evidence": ["git status --short"],
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


class BaselineSemanticOutputTests(unittest.TestCase):
    def test_valid_six_field_object_builds_complete_guardresult(self):
        result = parse_baseline_semantic_result(semantic_text())
        self.assertEqual(result.schema_version, "1.0")
        self.assertFalse(result.risk)
        self.assertEqual(result.decision.value, "allow")
        self.assertEqual(result.severity.value, "none")
        self.assertEqual(result.category.value, "benign")
        self.assertEqual(result.summary, "查看仓库状态")
        self.assertEqual(result.confidence, 0.99)
        self.assertEqual(result.evidence, ["git status --short"])
        self.assertEqual(result.rule_hits, [])
        self.assertEqual(result.model_version, BASELINE_MODEL_VERSION)
        self.assertEqual(result.policy_version, BASELINE_POLICY_VERSION)

    def test_markdown_fence_does_not_prevent_extraction(self):
        result = parse_baseline_semantic_result(
            "```json\n" + semantic_text() + "\n```"
        )
        self.assertEqual(result.category.value, "benign")

    def test_numeric_confidence_string_is_losslessly_converted(self):
        result = parse_baseline_semantic_result(semantic_text(confidence="0.95"))
        self.assertEqual(result.confidence, 0.95)

    def test_non_bucket_numeric_confidence_values_are_preserved(self):
        for confidence in (0.85, 0.95, "0.85", "0.95"):
            with self.subTest(confidence=confidence):
                result = parse_baseline_semantic_result(
                    semantic_text(confidence=confidence)
                )
                self.assertEqual(result.confidence, float(confidence))

    def test_system_owned_fields_are_rejected_as_extra_model_fields(self):
        for field, value in (
            ("risk", False),
            ("schema_version", "1.0"),
            ("rule_hits", []),
            ("model_version", BASELINE_MODEL_VERSION),
            ("policy_version", BASELINE_POLICY_VERSION),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(GeneratedResultError, "extra"):
                    parse_baseline_semantic_result(semantic_text(**{field: value}))

    def test_missing_semantic_field_is_rejected(self):
        payload = json.loads(semantic_text())
        payload.pop("decision")
        with self.assertRaisesRegex(GeneratedResultError, "decision"):
            parse_baseline_semantic_result(json.dumps(payload, ensure_ascii=False))

    def test_unknown_enum_is_rejected(self):
        with self.assertRaisesRegex(GeneratedResultError, "category"):
            parse_baseline_semantic_result(semantic_text(category="other"))

    def test_non_numeric_confidence_string_is_rejected(self):
        with self.assertRaisesRegex(GeneratedResultError, "confidence"):
            parse_baseline_semantic_result(semantic_text(confidence="very sure"))

    def test_confidence_outside_unit_interval_is_rejected(self):
        with self.assertRaisesRegex(GeneratedResultError, "confidence"):
            parse_baseline_semantic_result(semantic_text(confidence="1.2"))

    def test_summary_requires_chinese(self):
        with self.assertRaisesRegex(GeneratedResultError, "summary"):
            parse_baseline_semantic_result(semantic_text(summary="check repo status"))

    def test_summary_longer_than_thirty_characters_is_rejected(self):
        with self.assertRaisesRegex(GeneratedResultError, "summary"):
            parse_baseline_semantic_result(semantic_text(summary="风险" * 16))

    def test_evidence_must_be_string_list_with_at_most_five_items(self):
        with self.assertRaisesRegex(GeneratedResultError, "evidence"):
            parse_baseline_semantic_result(semantic_text(evidence="git status"))
        with self.assertRaisesRegex(GeneratedResultError, "evidence"):
            parse_baseline_semantic_result(semantic_text(evidence=["x"] * 6))

    def test_benign_requires_allow_and_none(self):
        for overrides in (
            {"decision": "review"},
            {"decision": "block", "severity": "high"},
            {"severity": "low"},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(GeneratedResultError, "benign"):
                    parse_baseline_semantic_result(semantic_text(**overrides))

    def test_non_benign_cannot_allow_or_use_none(self):
        with self.assertRaisesRegex(GeneratedResultError, "non-benign"):
            parse_baseline_semantic_result(
                semantic_text(category="unsafe_download", decision="allow", severity="medium")
            )
        with self.assertRaisesRegex(GeneratedResultError, "non-benign"):
            parse_baseline_semantic_result(
                semantic_text(category="unsafe_download", decision="review", severity="none")
            )

    def test_block_requires_high_or_critical(self):
        for severity in ("low", "medium"):
            with self.subTest(severity=severity):
                with self.assertRaisesRegex(GeneratedResultError, "block"):
                    parse_baseline_semantic_result(
                        semantic_text(
                            category="unsafe_download",
                            decision="block",
                            severity=severity,
                        )
                    )

    def test_non_benign_envelope_derives_risk_true(self):
        result = parse_baseline_semantic_result(
            semantic_text(
                category="remote_execution",
                decision="block",
                severity="critical",
                summary="下载远程脚本并执行",
            )
        )
        self.assertTrue(result.risk)
        self.assertEqual(result.category.value, "remote_execution")
        self.assertEqual(result.decision.value, "block")
        self.assertEqual(result.severity.value, "critical")


if __name__ == "__main__":
    unittest.main()
