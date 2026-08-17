"""Rules-first orchestration for deterministic policy/model fusion."""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .baseline_predictor import BaselinePredictionOutcome, PredictionStatus
from .contracts import GuardRequest, GuardResult
from .rules import RuleEngine, RuleMatch, build_rule_guard_result
from .taxonomy import Decision


FUSION_POLICY_VERSION = "fusion-v1"


class FusionSource(str, Enum):
    RULE = "rule"
    MODEL = "model"
    FALLBACK = "fallback"


class ModelPredictorProtocol(Protocol):
    def predict(self, request: GuardRequest) -> BaselinePredictionOutcome: ...


@dataclass(frozen=True)
class FusionOutcome:
    status: PredictionStatus
    result: GuardResult | None
    fallback_decision: Decision | None
    source: FusionSource
    rule_matches: tuple[RuleMatch, ...]
    selected_rule_id: str | None
    model_invoked: bool
    model_outcome: BaselinePredictionOutcome | None


class FusionPredictor:
    """Short-circuit on decisive rules, otherwise delegate once to the model."""

    def __init__(
        self,
        rule_engine: RuleEngine,
        model_predictor: ModelPredictorProtocol,
    ):
        self.rule_engine = rule_engine
        self.model_predictor = model_predictor

    def predict(self, request: GuardRequest) -> FusionOutcome:
        evaluation = self.rule_engine.evaluate(request)
        if evaluation.selected is not None:
            result = build_rule_guard_result(
                evaluation,
                policy_version=FUSION_POLICY_VERSION,
            )
            return FusionOutcome(
                status=PredictionStatus.OK,
                result=result,
                fallback_decision=None,
                source=FusionSource.RULE,
                rule_matches=evaluation.matches,
                selected_rule_id=evaluation.selected.rule_id,
                model_invoked=False,
                model_outcome=None,
            )

        model_outcome = self.model_predictor.predict(request)
        if model_outcome.result is None:
            return FusionOutcome(
                status=model_outcome.status,
                result=None,
                fallback_decision=model_outcome.fallback_decision or Decision.REVIEW,
                source=FusionSource.FALLBACK,
                rule_matches=evaluation.matches,
                selected_rule_id=None,
                model_invoked=True,
                model_outcome=model_outcome,
            )

        result = model_outcome.result.model_copy(
            update={"policy_version": FUSION_POLICY_VERSION}
        )
        return FusionOutcome(
            status=model_outcome.status,
            result=result,
            fallback_decision=None,
            source=FusionSource.MODEL,
            rule_matches=evaluation.matches,
            selected_rule_id=None,
            model_invoked=True,
            model_outcome=model_outcome,
        )
