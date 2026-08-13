import unittest

from pydantic import ValidationError

from guard.contracts import GuardRequest, GuardResult
from guard.taxonomy import Decision, RiskCategory, Severity, ToolType


class GuardRequestTests(unittest.TestCase):
    def test_accepts_minimal_shell_request(self):
        request = GuardRequest(type=ToolType.SHELL, command="git status")

        self.assertEqual(request.type, ToolType.SHELL)
        self.assertEqual(request.command, "git status")

    def test_rejects_blank_command(self):
        with self.assertRaises(ValidationError):
            GuardRequest(type=ToolType.SHELL, command="   ")


class GuardResultTests(unittest.TestCase):
    def test_accepts_valid_block_result(self):
        result = GuardResult(
            risk=True,
            decision=Decision.BLOCK,
            severity=Severity.CRITICAL,
            category=RiskCategory.REMOTE_EXECUTION,
            summary="下载远程脚本并直接执行",
            confidence=0.98,
            evidence=["curl ... | bash"],
            model_version="qwen2.5-1.5b-baseline",
            policy_version="policy-v1",
        )

        self.assertEqual(result.schema_version, "1.0")
        self.assertEqual(result.category, RiskCategory.REMOTE_EXECUTION)

    def test_rejects_confidence_outside_unit_interval(self):
        with self.assertRaises(ValidationError):
            GuardResult(
                risk=True,
                decision=Decision.BLOCK,
                severity=Severity.HIGH,
                category=RiskCategory.CREDENTIAL_ACCESS,
                summary="读取敏感凭据",
                confidence=1.1,
                model_version="baseline",
                policy_version="policy-v1",
            )

    def test_rejects_summary_longer_than_thirty_characters(self):
        with self.assertRaises(ValidationError):
            GuardResult(
                risk=True,
                decision=Decision.REVIEW,
                severity=Severity.MEDIUM,
                category=RiskCategory.UNSAFE_DOWNLOAD,
                summary="过长" * 16,
                confidence=0.5,
                model_version="baseline",
                policy_version="policy-v1",
            )


if __name__ == "__main__":
    unittest.main()
