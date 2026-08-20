from evaluation.guard_result_metrics import (
    confidence_average,
    decision_distribution,
    schema_pass_rate,
)


def test_schema_pass_rate():
    data = [
        {
            "decision": "allow",
            "risk_level": "none",
            "category": "benign",
            "summary": "ok",
            "confidence": 0.9,
            "provenance": {},
        },
        {"decision": "block"},
    ]
    assert schema_pass_rate(data) == 0.5


def test_distribution_and_confidence():
    data = [
        {"decision": "allow", "confidence": 0.8},
        {"decision": "block", "confidence": 0.6},
    ]
    assert decision_distribution(data) == {"allow": 1, "block": 1}
    assert confidence_average(data) == 0.7
