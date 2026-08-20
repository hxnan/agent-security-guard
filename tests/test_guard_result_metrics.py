import unittest

from evaluation.guard_result_metrics import (
    confidence_average,
    decision_distribution,
    schema_error_distribution,
    schema_pass_rate,
)


def valid_result(**overrides):
    result = {
        "decision": "allow",
        "risk_level": "none",
        "category": "benign",
        "summary": "safe inspection",
        "confidence": 0.9,
        "provenance": {
            "model_version": "qwen-test",
            "policy_version": "model-only-v2",
        },
    }
    result.update(overrides)
    return result


class GuardResultMetricsTests(unittest.TestCase):
    def test_schema_pass_rate_uses_complete_v2_validation(self):
        results = [
            valid_result(),
            valid_result(decision="permit"),
            valid_result(confidence=1.1),
            valid_result(provenance={"model_version": "qwen-test"}),
        ]

        self.assertEqual(schema_pass_rate(results), 0.25)

    def test_schema_pass_rate_is_zero_for_empty_input(self):
        self.assertEqual(schema_pass_rate([]), 0.0)

    def test_schema_error_distribution_counts_each_validation_error(self):
        results = [
            valid_result(decision="permit"),
            valid_result(confidence=True),
            valid_result(provenance={}),
        ]

        self.assertEqual(
            schema_error_distribution(results),
            {
                "decision must be one of: allow, review, block": 1,
                "confidence must be a number between 0 and 1": 1,
                "missing provenance.model_version": 1,
                "missing provenance.policy_version": 1,
            },
        )

    def test_decision_distribution_includes_missing_decisions(self):
        results = [
            {"decision": "allow"},
            {"decision": "block"},
            {},
        ]

        self.assertEqual(
            decision_distribution(results),
            {"allow": 1, "block": 1, "missing": 1},
        )

    def test_decision_distribution_groups_malformed_values_without_crashing(self):
        results = [
            {"decision": ["allow"]},
            {"decision": None},
        ]

        self.assertEqual(decision_distribution(results), {"invalid": 2})

    def test_confidence_average_excludes_booleans_and_out_of_range_values(self):
        results = [
            {"confidence": 0.8},
            {"confidence": 0.6},
            {"confidence": True},
            {"confidence": -0.1},
            {"confidence": 1.1},
            {},
        ]

        self.assertAlmostEqual(confidence_average(results), 0.7)


if __name__ == "__main__":
    unittest.main()
