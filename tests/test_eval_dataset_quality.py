import unittest
from pathlib import Path

from guard.eval_dataset import load_eval_dataset


REPOSITORY_ROOT = Path(__file__).parents[1]
DATASET_PATH = REPOSITORY_ROOT / "data" / "eval-v1" / "gold"


class EvalDatasetQualityRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = {record.sample_id: record for record in load_eval_dataset(DATASET_PATH)}

    def test_ev026_summary_matches_verified_download_context(self):
        record = self.records["EV026"]
        self.assertIn("signature_verified", record.request.context.source or "")
        self.assertNotIn("未验证", record.expected.summary)

    def test_ev044_summary_describes_antivirus_protection(self):
        record = self.records["EV044"]
        self.assertIn("DisableRealtimeMonitoring", record.request.command)
        self.assertIn("防护", record.expected.summary)
        self.assertNotIn("审计", record.expected.summary)

    def test_ev058_command_explicitly_elevates(self):
        record = self.records["EV058"]
        self.assertIn("runas", record.request.command.lower())

    def test_ev084_context_states_setuid_semantics(self):
        record = self.records["EV084"]
        self.assertIn("helper_is_setuid", record.request.context.source or "")

    def test_ev087_has_privilege_that_can_write_hosts(self):
        record = self.records["EV087"]
        self.assertEqual(record.request.context.privilege, "root")

    def test_ev099_context_states_firewall_script_behavior(self):
        record = self.records["EV099"]
        self.assertIn("script_changes_firewall", record.request.context.source or "")


if __name__ == "__main__":
    unittest.main()
