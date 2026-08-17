# P3 Rule Engine + Fusion V1 Design

## Status

Proposed design for P3.1. This design follows the completed Model-only Baseline V2.1 and uses the same Eval V1 technical freeze for later comparison.

## 1. Motivation and measured baseline

The target-GPU Baseline V2.1 run over all 100 frozen Eval V1 samples produced:

- `valid_output_rate = 0.54`
- `first_pass_valid_output_rate = 0.10`
- `repair_attempt_rate = 0.90`
- `repair_success_rate = 0.4889`
- `risk_f1 = 0.7089`
- `category_macro_f1 = 0.1321`
- `effective_decision_accuracy = 0.40`
- `high_or_critical_allow_miss_rate = 0.0`
- 46 terminal parse failures
- 21 valid benign predictions misclassified as risky
- zero category recall for `credential_access`, `data_exfiltration`, `defense_evasion`, `persistence`, `privilege_escalation`, and `resource_abuse`

The result is sufficient as a reproducible Model-only Baseline, but not sufficient as a standalone security policy. The primary P3 problem is no longer JSON formatting. It is semantic reliability: the model is too conservative on benign requests and weak at fine-grained risk taxonomy.

P3 therefore introduces a deterministic rule layer for narrow, high-confidence cases and a fusion policy that uses the model only when no decisive rule applies.

## 2. Goals

P3 Rule Engine + Fusion V1 MUST:

1. Detect a first set of high-confidence dangerous behaviors without requiring model inference.
2. Recognize a very narrow set of high-confidence benign introspection commands so obvious read-only operations are not promoted to risk by the model.
3. Preserve the existing 12-category taxonomy and public GuardResult V1 contract.
4. Keep every rule hit auditable through a stable `rule_id`, evidence, category, severity, and decision.
5. Never execute the inspected command, script, code, or tool call.
6. Never inspect Eval sample IDs or expected labels at runtime.
7. Use rules only for behavior patterns that can be stated independently of the benchmark examples.
8. Fall back to the existing Baseline V2.1 predictor only when no decisive rule applies.
9. Preserve fail-safe behavior: an invalid or failed model prediction yields `review` when rules did not decide the request.
10. Support Rules-only and Fusion evaluation on the same resolved Eval V1 freeze.
11. Make rule/model provenance explicit enough to distinguish rule short-circuit, model fallback, and model failure.
12. Keep CPU tests independent of model weights and GPU.

## 3. Non-goals

P3 V1 will NOT:

- replace the 12-category taxonomy;
- modify Eval V1 Gold, review, adjudication, or freeze files;
- create sample-specific rules for EV001-EV100;
- attempt to cover every category or every command syntax in the first rule set;
- silently rewrite model `category`, `decision`, or `severity` after model inference;
- use a broad allowlist such as "all git commands are safe" or "all read-looking commands are safe";
- claim that a zero high-risk allow-miss rate proves safety;
- introduce AST parsers or shell execution/sandboxing in V1;
- tune rule thresholds against individual Eval IDs;
- train or fine-tune the model.

## 4. Chosen architecture

### 4.1 Decision flow

The selected architecture is **Rules-first, model-on-no-decision**:

```text
GuardRequest
   |
   v
RuleEngine.evaluate(request)
   |
   +-- decisive dangerous match ---> rule GuardResult
   |
   +-- decisive benign match ------> allow/benign GuardResult
   |
   `-- no decisive match ----------> BaselinePredictor V2.1
                                        |
                                        +-- valid result ---> model GuardResult
                                        `-- failure -------> fail-safe review
```

There is no post-hoc rule that edits a valid model result in V1. The rule engine either short-circuits before model invocation or abstains completely.

This keeps the provenance and causal path simple: a final semantic label came either from a decisive deterministic rule or from the model, never from an opaque merge of both.

### 4.2 Why not "rules only escalate risk"

A risk-only rule layer would preserve the current major false-positive problem. The measured baseline already has 21 valid benign predictions incorrectly categorized as risky. P3 therefore needs a narrow benign short-circuit path as well as dangerous rules.

### 4.3 Why not broad Rules-first coverage

A large keyword ruleset could optimize Eval V1 quickly while overfitting the benchmark and weakening generalization. V1 deliberately starts with a small rule registry whose behavior can be explained independently of Eval V1.

## 5. Internal rule contract

Create an internal immutable rule-match contract, conceptually:

```python
RuleMatch(
    rule_id: str,
    category: RiskCategory,
    decision: Decision,
    severity: Severity,
    summary: str,
    evidence: tuple[str, ...],
    priority: int,
)
```

Requirements:

- `rule_id` is stable and versioned.
- `summary` is Chinese and satisfies the public 1-30 character GuardResult bound.
- `evidence` contains only request-derived fragments or context facts.
- `priority` is deterministic configuration, not a probability.
- RuleMatch has no access to sample ID, Gold result, scenario kind, or review metadata.

The engine returns a `RuleEvaluation` containing zero or more matches plus the selected decisive match, if any.

## 6. Rule registry and conflict resolution

### 6.1 Stable IDs

Rule IDs use namespaced stable strings, for example:

```text
rule.remote_execution.pipe_shell.v1
rule.destructive_operation.disk_format.v1
rule.credential_access.private_key_read.v1
rule.defense_evasion.disable_security_control.v1
rule.persistence.autostart_install.v1
rule.benign.git_status.v1
```

Renaming or materially changing semantics requires a new rule version.

### 6.2 Multiple matches

A request may match multiple rules. For example, remote content piped directly into a shell could also resemble an unsafe download.

Selection is deterministic:

1. dangerous matches always outrank benign matches;
2. `block` outranks `review`, which outranks `allow`;
3. higher severity outranks lower severity;
4. higher explicit rule priority wins;
5. `rule_id` lexical order is the final deterministic tie-breaker.

All matched rule IDs are retained in `rule_hits`; the selected match determines the final semantic fields.

A benign rule can only decide `allow/none/benign` when **no dangerous rule matched**.

## 7. First V1 rule families

The first set intentionally favors precision over coverage.

### 7.1 Remote execution

High-confidence examples include behavior where remotely obtained content is immediately executed by a shell/interpreter, such as:

- `curl`/`wget` output piped into `sh`/`bash`;
- PowerShell download/invoke expressions where fetched content is immediately passed to execution;
- direct interpreter execution of freshly fetched remote source where the command structure makes the data-flow explicit.

Expected rule result is normally `remote_execution`, `block`, `critical`.

A download without immediate execution must NOT match this family solely because `curl`, `wget`, or a URL is present.

### 7.2 Destructive operation

Only unmistakably destructive patterns belong in V1, for example:

- explicit filesystem or disk formatting commands;
- disk wipe/clean operations;
- broad destructive deletion patterns whose target is clearly system-wide or unbounded.

Routine file deletion is not automatically classified as destructive.

### 7.3 Credential access

V1 covers direct access to well-known credential material when the command explicitly reads or exports it, such as:

- private SSH keys;
- cloud credential stores/files;
- explicit password/token/key stores where the path or command semantics identify credential access.

Generic file reads must not be promoted merely because a filename contains a vague word such as `key`.

### 7.4 Defense evasion

V1 covers explicit commands that disable or materially suppress a security control, for example:

- disabling antivirus/real-time protection;
- disabling firewall/security enforcement where the behavior is directly stated by the command.

Ordinary status inspection of security software must not match.

### 7.5 Persistence

V1 covers explicit installation of durable autorun mechanisms, for example:

- adding startup/autorun entries;
- creating or installing scheduled/cron persistence;
- enabling a newly installed persistent service where the command sequence makes the persistence action explicit.

Merely listing services, timers, tasks, or cron state must not match.

### 7.6 Narrow benign introspection

Benign rules require both a recognized safe command shape and absence of shell composition that could add side effects.

V1 starts with a deliberately narrow `git status` rule and may include similarly unambiguous introspection commands only when their safe grammar is explicit.

Before a benign rule can match, reject command composition containing side-effect/control constructs such as redirection, pipelines, command chaining, command substitution, or embedded secondary commands.

The rule must recognize safe `git status` output options such as `--short`/`--porcelain` without treating arbitrary `git ...` commands as benign.

The purpose is to fix a class of obvious false positives, not create a broad allowlist.

## 8. Parsing strategy

V1 remains dependency-light and does not execute or fully parse shell grammars.

Each rule family uses:

1. normalized tool type;
2. conservative lexical/regex recognition;
3. explicit negative guards for near-miss cases;
4. request context only when a context field has direct semantic meaning.

The engine MUST treat quoted user content and prompt-injection-like strings as data. It must not evaluate substitutions or expand environment variables.

Case normalization is permitted where the underlying command language is case-insensitive. Original request text must be preserved for evidence.

## 9. Rule-produced GuardResult

A decisive rule creates a public GuardResult V1 with:

```text
schema_version = 1.0
risk            = (category != benign)
decision        = selected rule decision
severity        = selected rule severity
category        = selected rule category
summary         = selected rule summary
confidence      = 1.0
rule_hits       = all matched stable rule IDs
model_version   = not-invoked
policy_version  = rules-v1          # Rules-only mode
                  fusion-v1         # Fusion rule short-circuit
```

`confidence=1.0` means deterministic rule certainty under the rule contract; it is not a calibrated model probability.

For Fusion requests that reach the model, the model result keeps its model provenance and confidence, while Fusion sets the public policy provenance to the Fusion policy version without changing model semantic labels.

Implementation must preserve separate internal provenance indicating whether the model was invoked.

## 10. Fusion result contract

Create a fusion outcome with enough audit fields to explain the path, conceptually:

```python
FusionOutcome(
    status,
    result,
    fallback_decision,
    source,              # "rule" | "model" | "fallback"
    rule_matches,
    selected_rule_id,
    model_invoked,
    model_outcome,
)
```

Rules-only and Fusion outcomes must not claim model participation when `model_invoked=false`.

If the rule engine abstains and BaselinePredictor returns a valid result, Fusion returns those semantic labels unchanged.

If the rule engine abstains and BaselinePredictor ends in parse/backend failure, Fusion uses `review` fail-safe behavior and does not invent a category.

## 11. Versioning

Initial versions:

```text
rule_engine_version = rule-engine-v1
rule_policy_version = rules-v1
fusion_policy_version = fusion-v1
model_version = qwen2.5-1.5b-instruct-baseline-v1
model_prompt_version = baseline-prompt-v2
model_repair_prompt_version = baseline-repair-prompt-v1
```

Rule registry changes that alter decisions require a rule engine or policy version change.

## 12. Evaluation design

P3 must make three modes comparable on the same resolved Eval V1 freeze:

1. Model-only V2.1 — existing historical report.
2. Rules-only V1.
3. Fusion V1.

### 12.1 Rules-only

Rules-only evaluation is CPU-only. If no decisive rule matches, the effective decision is `review` and no category prediction is fabricated.

Report at least:

- decisive rule coverage;
- benign-rule coverage;
- dangerous-rule coverage;
- rule decision accuracy on decisive samples;
- rule category accuracy on decisive samples;
- false benign allows;
- high/critical allow misses;
- per-rule hit counts;
- per-rule correct/incorrect counts;
- abstain count/rate.

### 12.2 Fusion

Fusion evaluation uses the same metrics as Model-only plus:

- rule short-circuit count/rate;
- model invocation count/rate;
- source counts (`rule`, `model`, `fallback`);
- per-rule contribution;
- high-risk allow misses by source;
- benign false positives by source;
- model repair metrics only for requests that actually invoke the model.

Performance metrics must not pretend replayed results are live latency measurements. Formal Fusion performance requires target-GPU execution.

### 12.3 Acceptance focus

P3 V1 is successful if it demonstrates measurable improvement without benchmark-specific logic. The initial acceptance emphasis is:

- no new high/critical `allow` miss caused by a benign rule;
- zero known broad-allow behavior such as treating arbitrary `git` commands as benign;
- deterministic/auditable rule decisions;
- obvious benign introspection such as the safe `git status` shape does not depend on model inference;
- explicit remote-execution/destructive/security-disable patterns do not depend on model taxonomy recall;
- Fusion quality is compared against the frozen Model-only V2.1 baseline rather than an altered Eval dataset.

No fixed Macro-F1 target is chosen before the first Rules-only/Fusion measurements; P3.2 priorities will be driven by measured errors.

## 13. Anti-overfitting controls

The following controls are mandatory:

1. `RuleEngine.evaluate` accepts only GuardRequest, never EvalGoldRecord.
2. Production rule code contains no `EV###` identifiers.
3. Production rule code cannot read Eval paths or freeze metadata.
4. Each rule requires synthetic positive and near-miss negative tests beyond exact Eval commands.
5. Tests include command variants across spacing, casing where relevant, and safe/dangerous neighbors.
6. A rule must have a behavior-level rationale independent of its Eval score contribution.
7. Eval V1 remains unchanged and is used only to measure the resulting system.

## 14. Security boundaries

- No request command is executed.
- No shell expansion or interpolation is performed.
- URLs are not fetched.
- Paths are not opened merely because they appear in the inspected command.
- Prompt-injection text inside commands remains inert data.
- Rules are deterministic and side-effect free.
- A parser/rule exception must fail closed to `review`, never implicit allow.
- Benign rules have stricter matching requirements than dangerous rules because a false benign rule can create an unsafe allow.

## 15. Code boundaries

Expected implementation boundaries:

```text
guard/rules.py             # RuleMatch, RuleEvaluation, registry and engine
guard/rule_patterns.py     # focused pure matching helpers / rule definitions
guard/fusion.py            # Rules-first fusion orchestration
guard/rule_evaluation.py   # Rules-only metrics/report helpers
scripts/evaluate_rules.py  # CPU Rules-only evaluation entry point
scripts/evaluate_fusion.py # target-GPU Fusion evaluation entry point
```

Exact filenames may be adjusted during planning if existing project structure provides a cleaner fit, but the responsibilities must remain separated.

Existing `guard/result_parsing.py`, public schemas, Eval V1 freeze, and Baseline V2.1 semantic parser remain unchanged unless a separately justified compatibility bug is found.

## 16. Required TDD regressions

At minimum, tests must prove:

1. engine accepts GuardRequest only and has no Eval metadata dependency;
2. `curl ... | bash`-style direct remote execution matches; download-only near-miss does not;
3. destructive disk/format patterns match; bounded ordinary deletion near-miss does not;
4. direct private-key/credential-store reads match; generic key-like filename near-miss does not;
5. disabling security control matches; status query does not;
6. explicit persistence installation matches; persistence inspection does not;
7. safe `git status`/`git status --short` matches benign;
8. `git status` combined with redirection/pipeline/chaining/substitution does not benign-match;
9. arbitrary `git` commands do not benign-match;
10. dangerous match beats benign match;
11. multiple dangerous matches resolve deterministically;
12. all matched rule IDs are preserved in `rule_hits`;
13. rule-produced GuardResult has exact risk/provenance fields;
14. rule short-circuit never calls the model backend;
15. no-rule Fusion path calls BaselinePredictor exactly once at orchestration level and preserves its bounded repair behavior internally;
16. model success labels are not rewritten by Fusion;
17. model terminal failure remains fail-safe review;
18. prompt-injection strings inside requests cannot change rule/fusion control flow;
19. Rules-only evaluator reports abstention and per-rule metrics;
20. Fusion evaluator reports source/model-invocation metrics;
21. production code contains no Eval sample IDs;
22. existing Baseline V2.1, Adapter, Schema, freeze, and dataset regression suites remain green.

## 17. Delivery sequence

Implementation should proceed in small TDD slices:

1. internal rule contracts and deterministic resolution;
2. narrow benign matcher and anti-composition guard;
3. first dangerous rule families;
4. rule-produced GuardResult and Rules-only predictor/evaluator;
5. Fusion orchestration;
6. Fusion evaluation and CLI;
7. documentation and final scope audit;
8. CPU CI merge;
9. local Rules-only evaluation first;
10. only after Rules-only analysis, run formal target-GPU Fusion evaluation.

This sequence avoids paying GPU cost before the deterministic rule layer has been measured independently.
