import unittest

from scripts.validate_guard_result_v2 import validate_result


def valid_result(**overrides):
    result = {
        "decision": "review",
        "risk_level": "medium",
        "category": "unsafe_download",
        "summary": "download needs review",
        "confidence": 0.75,
        "provenance": {
            "model_version": "qwen-test",
            "policy_version": "model-only-v2",
        },
    }
    result.update(overrides)
    return result


class GuardResultV2ValidationTests(unittest.TestCase):
    def test_accepts_complete_result(self):
        self.assertEqual(validate_result(valid_result()), [])

    def test_rejects_non_object_result(self):
        self.assertEqual(validate_result([]), ["result must be an object"])

    def test_rejects_unknown_decision_and_risk_level(self):
        errors = validate_result(valid_result(decision="permit", risk_level="severe"))

        self.assertEqual(
            errors,
            [
                "decision must be one of: allow, review, block",
                "risk_level must be one of: none, low, medium, high, critical",
            ],
        )

    def test_rejects_boolean_confidence(self):
        self.assertEqual(
            validate_result(valid_result(confidence=True)),
            ["confidence must be a number between 0 and 1"],
        )

    def test_rejects_invalid_text_and_provenance_types(self):
        errors = validate_result(
            valid_result(category=3, summary=None, provenance="generated")
        )

        self.assertEqual(
            errors,
            [
                "category must be a string",
                "summary must be a string",
                "provenance must be an object",
            ],
        )


if __name__ == "__main__":
    unittest.main()
