# Eval V1 Machine Review — 2026-08-14

## Scope

A second machine review inspected EV001–EV100 against the committed Blueprint and Annotation Guideline V1. This pass focuses on factual and semantic consistency that structural Pydantic/JSONL validation cannot detect.

This review is **not** an independent human review. It must not change any row from `review_status=pending`, and it does not satisfy the P1 freeze gate.

## Findings selected for correction

- `EV026`: the context says the vendor is approved and the signature is verified, but the summary says the download is unverified.
- `EV044`: the command disables Microsoft Defender real-time monitoring, while the summary describes audit-log shutdown/removal.
- `EV058`: the Blueprint requires an approved elevated read-only service query, but the authored CMD command does not elevate.
- `EV084`: the Blueprint requires a setuid maintenance helper, but the trusted context does not state that the helper is setuid.
- `EV087`: the Python code directly writes `/etc/hosts`, but the authored privilege context is ordinary user and therefore muddies the intended sensitive-write behavior with a likely permission failure.
- `EV099`: the mixed-language Blueprint says the local Python program is a firewall updater, but the trusted context does not explicitly state the local script's behavior.

## Review-policy boundary

The machine review may correct request realization, trusted context, summaries, and evidence while preserving the approved Blueprint identity and primary category. It may not change category quotas or mark samples `agreed`/`adjudicated`.

Independent human review should be blind to the primary Gold labels. The accompanying review tooling exports only `sample_id` and `request`; a reviewer supplies their own `decision`, `severity`, `category`, `summary`, `confidence`, and `evidence`. The comparison tool reports disagreements in the four core fields: `decision`, `severity`, `category`, and `summary`.
