import unittest

from guard.eval_blueprint import BlueprintRecord, ScenarioKind, ToolFamily
from guard.eval_dataset import EvalDatasetValidationError, validate_against_blueprint
from guard.taxonomy import RiskCategory, ToolType
from tests.test_eval_dataset import make_record


def mismatching_blueprint():
    return BlueprintRecord(
        sample_id="EV001",
        tool_family=ToolFamily.SHELL,
        request_type=ToolType.SHELL,
        scenario_kind=ScenarioKind.NORMAL,
        planned_category=RiskCategory.REMOTE_EXECUTION,
        scenario="example",
        semantic_template="repo_status_read_only",
        variant="git_status_short",
        risk_factors=(),
        required_context=(),
        mixed_components=(),
        authoring_status="planned",
    )


class EvalBlueprintAdjudicationTests(unittest.TestCase):
    def test_adjudicated_record_may_correct_planned_category(self):
        record = make_record()
        record.metadata.review_status = "adjudicated"
        record.metadata.reviewer = "independent-agent:gpt-5.6-sol"
        record.metadata.adjudication_note = "Independent review corrected the planning category."

        validate_against_blueprint([record], [mismatching_blueprint()])

    def test_agreed_record_cannot_change_planned_category(self):
        record = make_record()
        record.metadata.review_status = "agreed"
        record.metadata.reviewer = "independent-agent:gpt-5.6-sol"

        with self.assertRaisesRegex(EvalDatasetValidationError, "planned_category"):
            validate_against_blueprint([record], [mismatching_blueprint()])


if __name__ == "__main__":
    unittest.main()
