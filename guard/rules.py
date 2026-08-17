"""Deterministic rule-engine contracts and conflict resolution."""

from dataclasses import dataclass
from typing import Callable, Iterable

from .contracts import GuardRequest, GuardResult
from .taxonomy import Decision, RiskCategory, Severity


RULE_ENGINE_VERSION = "rule-engine-v1"
RULES_POLICY_VERSION = "rules-v1"


@dataclass(frozen=True)
class RuleMatch:
    rule_id: str
    category: RiskCategory
    decision: Decision
    severity: Severity
    summary: str
    evidence: tuple[str, ...]
    priority: int = 0


@dataclass(frozen=True)
class RuleEvaluation:
    matches: tuple[RuleMatch, ...]
    selected: RuleMatch | None


RuleMatcher = Callable[[GuardRequest], RuleMatch | None]


_DECISION_RANK = {
    Decision.ALLOW: 0,
    Decision.REVIEW: 1,
    Decision.BLOCK: 2,
}

_SEVERITY_RANK = {
    Severity.NONE: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


def _selection_key(rule_match: RuleMatch) -> tuple[int, int, int, int, str]:
    dangerous_rank = 0 if rule_match.category is not RiskCategory.BENIGN else 1
    return (
        dangerous_rank,
        -_DECISION_RANK[rule_match.decision],
        -_SEVERITY_RANK[rule_match.severity],
        -rule_match.priority,
        rule_match.rule_id,
    )


def select_decisive_match(matches: Iterable[RuleMatch]) -> RuleMatch | None:
    """Select one decisive match using the stable policy ordering."""
    collected = tuple(matches)
    if not collected:
        return None
    return min(collected, key=_selection_key)


class RuleEngine:
    """Evaluate a validated GuardRequest against deterministic pure matchers."""

    def __init__(self, matchers: Iterable[RuleMatcher] | None = None):
        if matchers is None:
            from .rule_patterns import RULE_MATCHERS

            matchers = RULE_MATCHERS
        self._matchers = tuple(matchers)

    def evaluate(self, request: GuardRequest) -> RuleEvaluation:
        matches = tuple(
            rule_match
            for matcher in self._matchers
            if (rule_match := matcher(request)) is not None
        )
        return RuleEvaluation(
            matches=matches,
            selected=select_decisive_match(matches),
        )


def build_rule_guard_result(
    evaluation: RuleEvaluation,
    *,
    policy_version: str,
    model_version: str = "not-invoked",
) -> GuardResult:
    """Build a public GuardResult from one decisive deterministic rule."""
    selected = evaluation.selected
    if selected is None:
        raise ValueError("cannot build GuardResult without a decisive rule match")

    return GuardResult(
        schema_version="1.0",
        risk=selected.category is not RiskCategory.BENIGN,
        decision=selected.decision,
        severity=selected.severity,
        category=selected.category,
        summary=selected.summary,
        confidence=1.0,
        evidence=list(selected.evidence),
        rule_hits=[rule_match.rule_id for rule_match in evaluation.matches],
        model_version=model_version,
        policy_version=policy_version,
    )
