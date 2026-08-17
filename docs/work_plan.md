# Agent Security Guard 工作计划

## 1. 执行方式

远端 GitHub 仓库是代码事实来源；本地受限机器负责 `git pull`、CPU 验证和必须依赖本地模型/GPU 的任务。模型权重、私有数据、训练检查点和密钥不提交到公开仓库。

每个工作包遵循：design/spec → implementation plan → RED/GREEN TDD → full CI → scope review → merge → 必要的本地硬件门禁。失败时先修当前层，不带病进入下一阶段。

## 2. 里程碑

| 阶段 | 状态 | 目标 |
| --- | --- | --- |
| P0 仓库基线 | 完成 | 可克隆、可安装、可测试的项目骨架与契约 |
| P1 标准与评估集 | 完成 | Eval V1 independent-agent reviewed technical freeze |
| P2 Model-only Baseline | 完成 | 本地 Qwen 的真实 100 条质量/性能基线 |
| P3 Rule Engine + Fusion | 当前 | 用高置信规则降低明显误杀并补关键安全边界 |
| P4 数据生产 | 后续 | 5k–10k 正式训练数据、去重与泄漏控制 |
| P5 QLoRA 正式训练 | 后续 | 6GB GPU 可运行且优于基线 |
| P6 服务化 | 后续 | 本地 API/SDK、审计、性能 |
| P7 持续优化 | 后续 | Hard Cases、红队与发布回归 |

## 3. P0/P1 已完成

- [x] `GuardRequest / GuardResult`、12 类 taxonomy、版本化 JSON Schema。
- [x] Python 3.10/3.12 CPU CI、环境检查、schema drift 门禁。
- [x] EV001–EV100 Blueprint 与 Gold Draft。
- [x] 第二次机器语义复核并修正 6 个事实/上下文问题。
- [x] 固定 commit 的独立 Agent blind review。
- [x] 86/100 实质标签一致；14 条分歧显式 adjudication。
- [x] deterministic resolver 与 `eval-v1-agent-reviewed-rc1` technical freeze。
- [x] `human_reviewed=false`；不将 Agent review 描述为 human review。

P1 固定统计：100 条；42 `allow`、33 `review`、25 `block`；12 类全部覆盖。

## 4. P2 已完成：Model-only Baseline

### P2.1 V1

完整 GuardResult 直接交给 1.5B 模型生成，正式 100 条运行 `valid_output_rate=0.0`。该运行证明 GPU/backend 链路可用，但语义质量指标因输出契约失败而不可解释。

### P2.2 V2 semantic envelope

模型责任缩到六字段：

```text
decision / severity / category / summary / confidence / evidence
```

系统拥有 `schema_version / risk / rule_hits / model_version / policy_version`。两条真实 probe 证明一次严格契约遵循仍不稳定。

### P2.3 V2.1 bounded repair

固定版本：

```text
prompt_version        = baseline-prompt-v2
repair_prompt_version = baseline-repair-prompt-v1
model_version         = qwen2.5-1.5b-instruct-baseline-v1
policy_version        = model-only-baseline-v2.1
report_version        = baseline-eval-report-v2.1
```

- [x] 首轮 parse/consistency failure 最多一次同模型 repair。
- [x] 首轮 backend failure 不 retry；repair failure 后无第三次生成。
- [x] repair 使用同一 strict parser，不存在 permissive parser。
- [x] 程序不自动修 category/decision/severity，不静默删除 extra fields。
- [x] 两轮 raw/error、latency/token/VRAM provenance 可审计。
- [x] 目标 RTX 1000 Ada 6GB 正式完成 100 条 Eval V1。

正式 Baseline V2.1：

```text
valid_output_rate              = 0.54
first_pass_valid_output_rate   = 0.10
repair_attempt_rate            = 0.90
repair_success_rate            = 0.4888888888888889
risk_f1                        = 0.7088607594936709
category_macro_f1              = 0.13206686930091183
effective_decision_accuracy    = 0.40
terminal_parse_errors          = 46
valid_benign_false_positives   = 21
high_or_critical_allow_misses  = 0
p50_latency_seconds            = 4.823194064999996
p95_latency_seconds            = 8.206673038300053
peak_gpu_memory_mb             = 3043.18505859375
evaluation_wall_seconds        = 495.861809923
```

结论：P2 已建立真实、可重复的 Model-only Baseline；1.5B zero-shot 模型不适合单独承担最终策略。主要问题已从格式失败转为 taxonomy 能力弱、benign 误杀高和 repair 依赖高。

## 5. 当前：P3 Rule Engine + Fusion V1

设计：`docs/superpowers/specs/2026-08-17-p3-rule-engine-fusion-v1-design.md`

计划：`docs/superpowers/plans/2026-08-17-p3-rule-engine-fusion-v1.md`

### P3.1 Rule Engine V1

- [x] `RuleEngine.evaluate` 只接收 `GuardRequest`，不能访问 Eval ID/Gold/freeze metadata。
- [x] 稳定 `RuleMatch / RuleEvaluation` 与确定性冲突处理。
- [x] dangerous 始终优先于 benign；再按 decision、severity、priority、rule_id 排序。
- [x] 首批 `remote_execution / destructive_operation / credential_access / defense_evasion / persistence` 高置信规则。
- [x] 极窄 benign `git status` grammar；任意 pipeline、重定向、chaining、substitution、未知参数均不 allow-shortcut。
- [x] rule result 使用 `confidence=1.0`、`model_version=not-invoked`、稳定 `rule_hits`。
- [x] matcher exception 被记录；异常时禁止 benign allow；已有 dangerous match 仍可 review/block，否则 fail-safe `review`。
- [x] 生产规则无 benchmark sample-ID 依赖；正例与 near-miss 反例均由 synthetic tests 覆盖。

当前 rule engine 版本：

```text
rule_engine_version = rule-engine-v1
rule_policy_version = rules-v1
```

### P3.2 Rules-first Fusion V1

- [x] decisive rule 直接 short-circuit，模型调用次数为 0。
- [x] 无 decisive rule 且规则引擎健康时调用 Baseline V2.1。
- [x] valid model semantic labels 保持原值，只切换 public policy provenance 到 `fusion-v1`。
- [x] model parse/backend failure 继续 fail-safe `review`，不伪造 category。
- [x] rule matcher error 无 dangerous 决策时在模型前 fail-safe `review`，避免损坏的规则注册表继续授权/推理。
- [x] rule/model/fallback source、model repair、rule errors 都可审计。

```text
fusion_policy_version = fusion-v1
```

### P3.3 Rules-only CPU evaluation

- [x] `rules-eval-report-v1`。
- [x] decisive/abstain、benign/dangerous coverage。
- [x] decisive decision/category accuracy。
- [x] false benign allow、high/critical allow miss。
- [x] per-rule hit/correct/incorrect。
- [x] `rule_error_count/rate` 与逐样本 `rule_errors`。
- [x] committed Eval V1 100 条在 CI 中 CPU-only 可执行，不导入模型/GPU。

正式本地门禁：

```bash
python scripts/evaluate_rules.py \
  --output artifacts/rules-eval-v1/report.json
```

只需要返回 compact stdout。关注顺序：

1. `rule_error_count` 必须为 0；
2. `false_benign_allow_count` 与 `high_or_critical_allow_miss_count` 优先为 0；
3. decisive decision/category accuracy；
4. decisive/benign/dangerous coverage。

如果规则 precision 或安全边界不合格，先修 Rule Engine，不跑 GPU Fusion。

### P3.4 Fusion formal evaluation

- [x] `fusion-eval-report-v1` CPU-testable evaluation surface。
- [x] source counts、rule short-circuit、model invocation、rule contribution。
- [x] model repair metrics 的分母仅为 model-invoked 请求。
- [x] benign FP / high-risk allow miss 按 source 归因。
- [x] CPU 测试性能字段为 `not_measured`；正式 CLI 才测 live end-to-end latency/GPU metrics。
- [x] `scripts/evaluate_fusion.py` target-GPU 入口。
- [ ] **Rules-only 注册表验收通过后**，再运行正式 100 条 Fusion GPU 评估。

正式 Fusion 命令（暂不执行）：

```bash
python scripts/evaluate_fusion.py \
  --output artifacts/fusion-eval-v1/report.json
```

## 6. P3 验收与 merge gate

合并 P3.1 前必须满足：

- [ ] PR 最新 HEAD Python 3.10/3.12 full CI 全绿。
- [ ] full unittest、Blueprint、freeze、schema export/drift 门禁通过。
- [ ] 100 条 committed-freeze Rules-only CPU evaluation 可执行。
- [ ] changed-files scope 不包含 `data/eval-v1/**`、`schemas/v1/**`、`guard/result_parsing.py`、模型权重或 artifacts。
- [ ] 生产 `guard/` / `scripts/` 中没有 `EV###` benchmark-specific 分支。
- [ ] critical diff review 通过，尤其是 benign grammar、matcher exception fail-closed、Fusion no-semantic-rewrite。
- [ ] squash merge 后 exact main commit 的 post-merge CI 全绿。

## 7. P3 之后

1. 分析本地 Rules-only compact result；必要时只按行为级错误扩/收窄规则。
2. Rules-only registry 通过后跑同一 Eval V1 的正式 Fusion GPU 报告，与 Model-only V2.1 公平对比。
3. 使用 Model-only / Rules-only / Fusion 的真实错误分布规划 P4 训练数据，而不是围绕 Eval ID 写特例。
4. P4 数据生产后进入 P5 正式 QLoRA/SFT。
5. 最终进入 API/SDK、审计、压测和持续红队回归。
