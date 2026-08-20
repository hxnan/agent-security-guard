# Baseline V2 Output Contract

## Motivation

The first GPU baseline showed that the model could generate useful risk semantics, but evaluation was polluted by missing machine-readable metadata and inconsistent output wrappers.

Baseline V2 separates two concerns:

1. Model output provides a normalized security signal.
2. Policy fusion remains the authority for execution decisions.

## Required fields

- `decision`: allow/review/block suggestion
- `risk_level`: none/low/medium/high/critical
- `category`: taxonomy category
- `summary`: short explanation
- `confidence`: calibrated score between 0 and 1
- `provenance.model_version`: model identifier
- `provenance.policy_version`: policy identifier

## Next step

The local GPU evaluation should rerun with this contract and compare semantic accuracy separately from transport/schema failures.
