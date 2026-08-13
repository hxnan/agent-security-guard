import unittest

from guard.taxonomy import CATEGORY_DEFINITIONS, RiskCategory, Severity


class RiskTaxonomyTests(unittest.TestCase):
    def test_every_category_has_exactly_one_definition(self):
        self.assertEqual(set(CATEGORY_DEFINITIONS), set(RiskCategory))

    def test_benign_defaults_to_no_severity(self):
        self.assertEqual(
            CATEGORY_DEFINITIONS[RiskCategory.BENIGN].default_severity,
            Severity.NONE,
        )

    def test_remote_execution_defaults_to_critical(self):
        self.assertEqual(
            CATEGORY_DEFINITIONS[RiskCategory.REMOTE_EXECUTION].default_severity,
            Severity.CRITICAL,
        )

    def test_category_identifiers_are_stable_snake_case(self):
        for category in RiskCategory:
            self.assertRegex(category.value, r"^[a-z][a-z0-9_]*$")


if __name__ == "__main__":
    unittest.main()
