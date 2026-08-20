import unittest
from collections import Counter
from dataclasses import replace

from guard.taxonomy import RiskCategory, ToolType
from training.seed_catalog import (
    SEED_CLUSTERS,
    SeedCatalogError,
    validate_seed_catalog,
)


class SeedCatalogTests(unittest.TestCase):
    def test_catalog_has_fixed_split_and_category_profile(self):
        self.assertEqual(len(SEED_CLUSTERS), 100)
        self.assertEqual(
            Counter(cluster.split for cluster in SEED_CLUSTERS),
            {"train": 80, "validation": 20},
        )

        counts = Counter(cluster.category for cluster in SEED_CLUSTERS)
        self.assertEqual(counts[RiskCategory.BENIGN], 30)
        self.assertEqual(counts[RiskCategory.REMOTE_EXECUTION], 8)
        self.assertEqual(counts[RiskCategory.UNSAFE_DOWNLOAD], 8)
        for category in set(RiskCategory) - {
            RiskCategory.BENIGN,
            RiskCategory.REMOTE_EXECUTION,
            RiskCategory.UNSAFE_DOWNLOAD,
        }:
            self.assertEqual(counts[category], 6, category)

    def test_catalog_templates_and_rendered_requests_are_unique(self):
        templates = [cluster.semantic_template for cluster in SEED_CLUSTERS]
        commands = [
            (cluster.tool_type, cluster.render_command(variant))
            for cluster in SEED_CLUSTERS
            for variant in range(1, 11)
        ]

        self.assertEqual(len(set(templates)), 100)
        self.assertEqual(len(set(commands)), 1000)

    def test_catalog_covers_every_tool_and_scenario_kind(self):
        self.assertEqual(
            {cluster.tool_type for cluster in SEED_CLUSTERS}, set(ToolType)
        )
        self.assertEqual(
            {cluster.scenario_kind for cluster in SEED_CLUSTERS},
            {"normal", "dangerous", "boundary", "injection"},
        )

    def test_catalog_validation_rejects_duplicate_template(self):
        duplicate = replace(
            SEED_CLUSTERS[-1],
            semantic_template=SEED_CLUSTERS[0].semantic_template,
        )

        with self.assertRaisesRegex(SeedCatalogError, "duplicate semantic_template"):
            validate_seed_catalog((*SEED_CLUSTERS[:-1], duplicate))

    def test_render_command_rejects_out_of_range_variant(self):
        for variant in (0, 11):
            with self.subTest(variant=variant):
                with self.assertRaisesRegex(
                    SeedCatalogError, "variant must be between 1 and 10"
                ):
                    SEED_CLUSTERS[0].render_command(variant)

    def test_catalog_wraps_malformed_templates_as_catalog_errors(self):
        for command_template in ("echo {0}", "echo {n.foo}"):
            with self.subTest(command_template=command_template):
                malformed = replace(
                    SEED_CLUSTERS[-1], command_template=command_template
                )
                with self.assertRaisesRegex(
                    SeedCatalogError, "command rendering failed"
                ):
                    validate_seed_catalog((*SEED_CLUSTERS[:-1], malformed))

    def test_catalog_rejects_nonnumeric_confidence_as_catalog_error(self):
        malformed = replace(SEED_CLUSTERS[-1], confidence="high")

        with self.assertRaisesRegex(SeedCatalogError, "invalid confidence"):
            validate_seed_catalog((*SEED_CLUSTERS[:-1], malformed))


if __name__ == "__main__":
    unittest.main()
