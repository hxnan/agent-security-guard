import inspect
import unittest

from guard.contracts import GuardRequest
from guard.rules import (
    RULE_ENGINE_VERSION,
    RULES_POLICY_VERSION,
    RuleEngine,
    RuleEvaluation,
    RuleMatch,
    build_rule_guard_result,
    select_decisive_match,
)
from guard.taxonomy import Decision, RiskCategory, Severity


class StaticMatcher:
    def __init__(self, match):
        self.match = match

    def __call__(self, request):
        return self.match


def match(
    rule_id,
    *,
    category=RiskCategory.REMOTE_EXECUTION,
    decision=Decision.BLOCK,
    severity=Severity.CRITICAL,
    priority=0,
):
    return RuleMatch(
        rule_id=rule_id,
        category=category,
        decision=decision,
        severity=severity,
        summary="测试规则命中",
        evidence=("fixture",),
        priority=priority,
    )


class RuleEngineCoreTests(unittest.TestCase):
    def test_versions_are_fixed(self):
        self.assertEqual(RULE_ENGINE_VERSION, "rule-engine-v1")
        self.assertEqual(RULES_POLICY_VERSION, "rules-v1")

    def test_public_evaluate_contract_accepts_only_guard_request(self):
        parameters = list(inspect.signature(RuleEngine.evaluate).parameters)
        self.assertEqual(parameters, ["self", "request"])
        request = GuardRequest(type="shell", command="echo hello")
        self.assertIsInstance(RuleEngine(matchers=()).evaluate(request), RuleEvaluation)

    def test_no_match_abstains(self):
        request = GuardRequest(type="shell", command="echo hello")
        evaluation = RuleEngine(matchers=()).evaluate(request)
        self.assertEqual(evaluation.matches, ())
        self.assertIsNone(evaluation.selected)

    def test_all_matches_are_retained_in_matcher_order(self):
        request = GuardRequest(type="shell", command="fixture")
        first = match("rule.z.v1")
        second = match("rule.a.v1", decision=Decision.REVIEW, severity=Severity.HIGH)
        evaluation = RuleEngine(
            matchers=(StaticMatcher(first), StaticMatcher(second))
        ).evaluate(request)
        self.assertEqual(evaluation.matches, (first, second))

    def test_dangerous_match_always_beats_benign_match(self):
        benign = match(
            "rule.benign.v1",
            category=RiskCategory.BENIGN,
            decision=Decision.ALLOW,
            severity=Severity.NONE,
            priority=999,
        )
        dangerous = match(
            "rule.danger.v1",
            category=RiskCategory.CREDENTIAL_ACCESS,
            decision=Decision.REVIEW,
            severity=Severity.HIGH,
            priority=-999,
        )
        self.assertEqual(select_decisive_match((benign, dangerous)), dangerous)

    def test_block_then_severity_then_priority_then_rule_id_break_ties(self):
        review = match(
            "rule.review.v1",
            decision=Decision.REVIEW,
            severity=Severity.CRITICAL,
            priority=100,
        )
        block_low = match(
            "rule.block.low.v1",
            decision=Decision.BLOCK,
            severity=Severity.HIGH,
            priority=100,
        )
        block_high_low_priority = match(
            "rule.block.high.z.v1",
            decision=Decision.BLOCK,
            severity=Severity.CRITICAL,
            priority=1,
        )
        block_high_high_priority_z = match(
            "rule.block.high.priority.z.v1",
            decision=Decision.BLOCK,
            severity=Severity.CRITICAL,
            priority=2,
        )
        block_high_high_priority_a = match(
            "rule.block.high.priority.a.v1",
            decision=Decision.BLOCK,
            severity=Severity.CRITICAL,
            priority=2,
        )
        self.assertEqual(
            select_decisive_match(
                (
                    review,
                    block_low,
                    block_high_low_priority,
                    block_high_high_priority_z,
                    block_high_high_priority_a,
                )
            ),
            block_high_high_priority_a,
        )

    def test_rule_result_derives_public_contract_and_keeps_all_hits(self):
        selected = match("rule.selected.v1")
        secondary = match(
            "rule.secondary.v1",
            category=RiskCategory.UNSAFE_DOWNLOAD,
            decision=Decision.REVIEW,
            severity=Severity.MEDIUM,
        )
        evaluation = RuleEvaluation(
            matches=(secondary, selected),
            selected=selected,
        )
        result = build_rule_guard_result(evaluation, policy_version=RULES_POLICY_VERSION)
        self.assertTrue(result.risk)
        self.assertEqual(result.decision, Decision.BLOCK)
        self.assertEqual(result.severity, Severity.CRITICAL)
        self.assertEqual(result.category, RiskCategory.REMOTE_EXECUTION)
        self.assertEqual(result.summary, "测试规则命中")
        self.assertEqual(result.confidence, 1.0)
        self.assertEqual(result.evidence, ["fixture"])
        self.assertEqual(result.rule_hits, ["rule.secondary.v1", "rule.selected.v1"])
        self.assertEqual(result.model_version, "not-invoked")
        self.assertEqual(result.policy_version, "rules-v1")

    def test_benign_rule_result_is_allow_none_and_risk_false(self):
        selected = match(
            "rule.benign.git_status.v1",
            category=RiskCategory.BENIGN,
            decision=Decision.ALLOW,
            severity=Severity.NONE,
        )
        result = build_rule_guard_result(
            RuleEvaluation(matches=(selected,), selected=selected),
            policy_version=RULES_POLICY_VERSION,
        )
        self.assertFalse(result.risk)
        self.assertEqual(result.decision, Decision.ALLOW)
        self.assertEqual(result.severity, Severity.NONE)
        self.assertEqual(result.category, RiskCategory.BENIGN)

    def test_cannot_build_rule_result_from_abstention(self):
        with self.assertRaisesRegex(ValueError, "decisive rule match"):
            build_rule_guard_result(
                RuleEvaluation(matches=(), selected=None),
                policy_version=RULES_POLICY_VERSION,
            )


if __name__ == "__main__":
    unittest.main()
