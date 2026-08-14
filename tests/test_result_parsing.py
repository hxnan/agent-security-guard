import json
import unittest

from guard.baseline_prompt import BASELINE_MODEL_VERSION, BASELINE_POLICY_VERSION
from guard.result_parsing import (
    GeneratedResultError,
    extract_first_json_object,
    parse_guard_result,
)


def valid_payload(**overrides):
    payload = {
        "schema_version": "1.0",
        "risk": False,
        "decision": "allow",
        "severity": "none",
        "category": "benign",
        "summary": "查看仓库状态",
        "confidence": 0.99,
        "evidence": ["git status --short"],
        "rule_hits": [],
        "model_version": BASELINE_MODEL_VERSION,
        "policy_version": BASELINE_POLICY_VERSION,
    }
    payload.update(overrides)
    return payload


class GeneratedResultParsingTests(unittest.TestCase):
    def test_extracts_valid_object_with_surrounding_prose_and_braces_in_string(self):
        text = 'prefix {"text":"brace } inside","value":1} suffix'
        self.assertEqual(
            extract_first_json_object(text),
            {"text": "brace } inside", "value": 1},
        )

    def test_skips_malformed_leading_brace_and_finds_later_object(self):
        text = 'bad {not json then later {"ok":true} trailing'
        self.assertEqual(extract_first_json_object(text), {"ok": True})

    def test_rejects_text_without_json_object(self):
        with self.assertRaisesRegex(GeneratedResultError, "valid JSON object"):
            extract_first_json_object("no object here")

    def test_parses_valid_baseline_guard_result(self):
        result = parse_guard_result(
            json.dumps(valid_payload(), ensure_ascii=False),
            expected_model_version=BASELINE_MODEL_VERSION,
            expected_policy_version=BASELINE_POLICY_VERSION,
            require_empty_rule_hits=True,
        )
        self.assertEqual(result.summary, "查看仓库状态")
        self.assertEqual(result.rule_hits, [])

    def test_rejects_extra_guardresult_field(self):
        payload = valid_payload(extra_field="surprise")
        with self.assertRaisesRegex(GeneratedResultError, "extra fields.*extra_field"):
            parse_guard_result(
                json.dumps(payload, ensure_ascii=False),
                expected_model_version=BASELINE_MODEL_VERSION,
                expected_policy_version=BASELINE_POLICY_VERSION,
            )

    def test_rejects_missing_guardresult_field(self):
        payload = valid_payload()
        payload.pop("evidence")
        with self.assertRaisesRegex(GeneratedResultError, "missing fields.*evidence"):
            parse_guard_result(
                json.dumps(payload, ensure_ascii=False),
                expected_model_version=BASELINE_MODEL_VERSION,
                expected_policy_version=BASELINE_POLICY_VERSION,
            )

    def test_rejects_wrong_model_version(self):
        with self.assertRaisesRegex(GeneratedResultError, "model_version"):
            parse_guard_result(
                json.dumps(valid_payload(model_version="wrong"), ensure_ascii=False),
                expected_model_version=BASELINE_MODEL_VERSION,
                expected_policy_version=BASELINE_POLICY_VERSION,
            )

    def test_rejects_wrong_policy_version(self):
        with self.assertRaisesRegex(GeneratedResultError, "policy_version"):
            parse_guard_result(
                json.dumps(valid_payload(policy_version="wrong"), ensure_ascii=False),
                expected_model_version=BASELINE_MODEL_VERSION,
                expected_policy_version=BASELINE_POLICY_VERSION,
            )

    def test_rejects_nonempty_rule_hits_for_model_only_baseline(self):
        with self.assertRaisesRegex(GeneratedResultError, "rule_hits"):
            parse_guard_result(
                json.dumps(valid_payload(rule_hits=["rule-x"]), ensure_ascii=False),
                expected_model_version=BASELINE_MODEL_VERSION,
                expected_policy_version=BASELINE_POLICY_VERSION,
                require_empty_rule_hits=True,
            )

    def test_rejects_schema_invalid_result(self):
        with self.assertRaisesRegex(GeneratedResultError, "valid GuardResult"):
            parse_guard_result(
                json.dumps(valid_payload(confidence=1.5), ensure_ascii=False),
                expected_model_version=BASELINE_MODEL_VERSION,
                expected_policy_version=BASELINE_POLICY_VERSION,
            )


if __name__ == "__main__":
    unittest.main()
