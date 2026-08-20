# Baseline V2 Evaluation

The evaluator separates three dimensions:

1. Schema correctness
   - strict GuardResult V2 pass rate
   - validation error distribution

2. Semantic quality
   - decision distribution and category accuracy
   - false allow and false block analysis

3. Calibration
   - valid confidence average and distribution
   - confidence versus correctness correlation

Schema metrics reuse the same validator as the command-line validation tool.
Malformed enum values, invalid field types, out-of-range confidence values and
incomplete provenance are not counted as valid outputs. This prevents transport
failures from hiding actual model capability.

The repository uses the standard-library test runner:

```bash
python -m unittest tests.test_guard_result_metrics \
  tests.test_guard_result_v2_validation -v
```
