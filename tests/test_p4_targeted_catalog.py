import unittest
from collections import Counter

from guard.taxonomy import RiskCategory, ToolType
from training.targeted_catalog import (
    TARGETED_CLUSTERS,
    TargetedCatalogError,
    validate_targeted_catalog,
)


class TargetedCatalogTests(unittest.TestCase):
    def test_catalog_has_fixed_40_10_split_and_error_driven_profile(self):
        self.assertEqual(len(TARGETED_CLUSTERS), 50)
        self.assertEqual(
            Counter(cluster.split for cluster in TARGETED_CLUSTERS),
            {"train": 40, "validation": 10},
        )
        self.assertEqual(
            Counter(cluster.category for cluster in TARGETED_CLUSTERS),
            Counter(
                {
                    RiskCategory.BENIGN: 20,
                    RiskCategory.REMOTE_EXECUTION: 8,
                    RiskCategory.PRIVILEGE_ESCALATION: 5,
                    RiskCategory.RESOURCE_ABUSE: 4,
                    RiskCategory.DATA_EXFILTRATION: 2,
                    RiskCategory.SENSITIVE_WRITE: 3,
                    RiskCategory.UNSAFE_DOWNLOAD: 3,
                    RiskCategory.PERSISTENCE: 1,
                    RiskCategory.NETWORK_CHANGE: 1,
                    RiskCategory.DEFENSE_EVASION: 1,
                    RiskCategory.DESTRUCTIVE_OPERATION: 1,
                    RiskCategory.CREDENTIAL_ACCESS: 1,
                }
            ),
        )

    def test_catalog_covers_priority_patterns_without_eval_identifiers(self):
        templates = {cluster.semantic_template for cluster in TARGETED_CLUSTERS}

        self.assertTrue(
            {
                "target_train_remote_verified_binary_execute",
                "target_train_resource_disguised_mining",
                "target_train_privilege_approved_setuid_status",
                "target_train_benign_network_socket_inventory",
                "target_validation_benign_dns_status_read",
            }.issubset(templates)
        )
        self.assertTrue(
            all("eval" not in template and "gold" not in template for template in templates)
        )

    def test_templates_and_all_500_rendered_requests_are_unique(self):
        templates = [cluster.semantic_template for cluster in TARGETED_CLUSTERS]
        requests = [
            (cluster.tool_type, cluster.render_command(variant))
            for cluster in TARGETED_CLUSTERS
            for variant in range(1, 11)
        ]

        self.assertEqual(len(set(templates)), 50)
        self.assertEqual(len(set(requests)), 500)
        self.assertEqual({cluster.tool_type for cluster in TARGETED_CLUSTERS}, set(ToolType))

    def test_catalog_validation_and_variant_bounds_are_enforced(self):
        validate_targeted_catalog(TARGETED_CLUSTERS)
        for variant in (0, 11):
            with self.subTest(variant=variant):
                with self.assertRaisesRegex(
                    TargetedCatalogError, "variant must be between 1 and 10"
                ):
                    TARGETED_CLUSTERS[0].render_command(variant)

    def test_verified_remote_execution_commands_gate_execution_on_verification(self):
        commands = {
            cluster.semantic_template: cluster.render_command(1)
            for cluster in TARGETED_CLUSTERS
        }

        self.assertIn(
            ".Status -eq 'Valid'",
            commands["target_train_remote_signed_msi_execute"],
        )
        for template in (
            "target_train_remote_verified_python_execute",
            "target_validation_remote_verified_zipapp_execute",
        ):
            with self.subTest(template=template):
                command = commands[template]
                self.assertNotIn("assert ", command)
                self.assertIn("if not hmac.compare_digest", command)
                self.assertIn("raise SystemExit", command)
                self.assertLess(
                    command.index("if not hmac.compare_digest"),
                    command.index("subprocess.run"),
                )

    def test_sensitive_write_validation_cluster_has_a_non_network_primary_effect(self):
        cluster = next(
            cluster
            for cluster in TARGETED_CLUSTERS
            if cluster.semantic_template
            == "target_validation_sensitive_password_policy_write"
        )

        self.assertEqual(cluster.category, RiskCategory.SENSITIVE_WRITE)
        self.assertFalse(
            any(
                "net.ipv4.ip_forward" in item.command_template
                and item.category is RiskCategory.SENSITIVE_WRITE
                for item in TARGETED_CLUSTERS
            )
        )


if __name__ == "__main__":
    unittest.main()
