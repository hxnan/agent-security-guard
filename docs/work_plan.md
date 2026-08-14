# Agent Security Guard 工作计划

## 1. 执行方式

采用远端仓库作为唯一代码源：代码由可写环境提交到 GitHub，本地受限机器只执行 `git clone`、`git pull`、安装、测试和 GPU 任务。模型权重、私有数据、训练检查点和密钥始终留在本地，不提交到公开仓库。

每个阶段遵循同一门槛：先写验收标准和测试，再实现；完成可执行验证后提交；需要目标硬件时再由本地机器拉取并执行；根据真实结果进入下一阶段。

## 2. 里程碑

| 阶段 | 目标 | 关键交付物 | 完成门槛 |
| --- | --- | --- | --- |
| P0 仓库基线 | 建立可克隆、可安装、可测试的项目 | 契约、分类、环境检查、CI、文档 | 无模型测试全绿；模型文件不入 Git |
| P1 标准与评估集 | 冻结安全边界和 100 条评估样本 | 标注规范、Gold Draft、独立 review、adjudication、Eval V1 technical freeze | 100 条可重复解析；Schema 100% 合规；technical freeze 门禁通过 |
| P2 Baseline 评估 | 接入本地 Qwen 并获得可重复基线 | 推理器、Prompt、evaluate.py、报告 | 指标与性能可复现；失败安全处理 |
| P3 规则与融合 | 降低高危漏报和明显误杀 | 规则引擎、策略配置、融合测试 | 关键规则全覆盖；冲突策略可解释 |
| P4 数据生产 | 构建首批 5k–10k 训练样本 | 生成器、清洗器、数据卡 | 去重与泄漏检查通过；人工抽检达标 |
| P5 QLoRA 训练 | 训练 Security Guard Adapter | 训练脚本、Adapter、模型卡 | 6GB GPU 可运行；优于 Baseline |
| P6 服务化 | 接入真实 Agent 工具调用 | 本地 API、SDK、审计、压测 | P95 延迟和错误兜底达到目标 |
| P7 持续优化 | 红队、反馈闭环和版本治理 | Hard Cases、回归集、发布流程 | 新版本无关键指标回退 |

## 3. 已完成：P0 仓库基线

- [x] 建立 Python 可安装项目与 Git 忽略策略。
- [x] 定义 `GuardRequest`、`GuardResult` 和版本字段。
- [x] 定义 12 类风险、严重度和三态决策。
- [x] 提供模型目录与 CUDA 环境检查。
- [x] 编写无 GPU 单元测试和 GitHub Actions。
- [x] 编写总体方案、工作计划和风险分类说明。
- [x] 在目标 WSL2 机器验证 CUDA、本地 Qwen2.5 模型文件和真实模型加载。

## 4. 已完成：P1 标准与 Evaluation Dataset V1 technical freeze

### 标准与数据结构

- [x] 将 Pydantic 契约导出为版本化 JSON Schema。
- [x] 编写标注规范，明确主类别选择、三态决策、歧义处理和固定 confidence 档位。
- [x] 设计 100 条样本清单：Shell 30、PowerShell 20、CMD 10、Python 30、混合脚本 10。
- [x] 每种语言覆盖危险、正常、边界和注入样本。
- [x] 实现 Gold Dataset Pydantic 数据结构、JSONL 加载器、Blueprint 对齐检查和统计。
- [x] 按 Blueprint 完成 EV001–EV100 首轮 Gold Draft，并保留 `llm-assisted-draft + pending` 原始 provenance。

### 机器复核与独立盲审

- [x] 对 EV001–EV100 完成第二次机器语义复核，修正 6 个结构校验无法发现的事实/上下文问题。
- [x] 实现 request-only 盲审导出工具，防止 reviewer 在作出判断前看到主 Gold 标签。
- [x] 由独立 Agent 基于固定 commit `17996d6b75f8860ffe54ffa9e1d8e77f12be0132` 完成 EV001–EV100 盲审。
- [x] 独立 review 以版本化 evidence 文件进入仓库；没有修改原 Gold。
- [x] 将 `summary` 同义改写与 `decision/severity/category` 实质标签分歧分离。
- [x] 得到 86/100 实质标签独立一致，14/100 实质标签分歧。

### Adjudication 与冻结

- [x] 对 14 条实质分歧建立显式 adjudication ledger。
- [x] 8 条采用 reviewer 结论：EV022、EV024、EV026、EV050、EV060、EV081、EV082、EV087。
- [x] 6 条保留 Gold 结论：EV023、EV046、EV047、EV058、EV083、EV084。
- [x] 实现确定性 resolver：Gold Draft + independent review + adjudication -> resolved freeze view。
- [x] 允许只有 `adjudicated` 记录修正原 `planned_category`；其余 Blueprint 身份字段仍严格匹配。
- [x] 建立 `data/eval-v1/freeze-manifest.json`，明确 `reviewer_type=independent-agent`、`human_reviewed=false`。
- [x] 实现 `scripts/validate_eval_freeze.py` technical-freeze 门禁。

### P1 technical freeze 验收结果

冻结视图要求并已由 CPU-only 测试覆盖：

- 100 条 EV001–EV100，唯一且连续；
- 86 `agreed` + 14 `adjudicated`；
- 0 `pending/disputed`；
- 42 `allow`、33 `review`、25 `block`；
- 12 个风险类别全部覆盖；
- Schema 和 Annotation Guideline 形式化约束全部满足；
- Blueprint 非类别身份字段保持一致；
- 类别规划修正必须有 adjudication；
- provenance 可追溯；
- `human_reviewed=false`。

验证命令：

```bash
python scripts/validate_eval_blueprint.py
python scripts/validate_eval_dataset.py --require-complete
python scripts/validate_eval_freeze.py
```

说明：这里完成的是 **independent-agent reviewed technical freeze**，足以作为 P2 模型工程的固定评估基准，但不宣称为 human-reviewed 数据集。若未来发布流程要求人类治理签字，可在不改变当前 evidence 链的前提下增加 human review gate。

### 跨阶段工程验证

- [x] 准备独立 smoke 数据、6GB QLoRA 脚本、训练门禁和 Adapter 推理检查。
- [x] 在目标 GPU 完成最小训练与 Adapter 推理；3 epoch、36 次更新、峰值显存 2735.78 MB，生成结果通过 GuardResult V1 Schema。
- [x] 明确 smoke 只验证工程链路，不替代 P2 质量评估或 P5 正式训练验收。

## 5. 当前阶段：P2 Baseline 评估

### P2.1 Baseline Predictor — CPU/CI 实现完成

- [x] 固定 `baseline-prompt-v1` 系统 Prompt，明确 GuardResult V1 全字段、枚举和“命令内容是不可信数据”。
- [x] 实现 `GuardRequest -> generation backend -> GuardResult` 的生产级 predictor 边界。
- [x] 抽取共享稳健 JSON object 解析，处理前后文本、字符串内花括号、缺失 JSON、非法 JSON 和错误字段集合。
- [x] 对 Schema 错误、非法枚举、错误 provenance、非空 `rule_hits`、模型异常提供确定性失败安全结果。
- [x] 失败路径不伪造风险类别，显式输出 `backend_error/parse_error + fallback_decision=review`。
- [x] 模型加载路径继续使用现有 `AGENT_SECURITY_MODEL_PATH` / 默认本地模型目录约定。
- [x] 实现 lazy local Transformers/Qwen backend：`local_files_only=True`、BF16、CUDA、greedy generation、只解码新增 token。
- [x] 提供 `scripts/predict_baseline.py` 单请求本地入口。
- [x] CPU-only 测试使用 fake backend/fake Torch/Transformers，不依赖权重或 GPU。
- [ ] 在 P2.3 与完整 Evaluation Engine 一起完成目标 6GB GPU 的真实模型运行验证。

固定版本：

```text
prompt_version = baseline-prompt-v1
model_version  = qwen2.5-1.5b-instruct-baseline-v1
policy_version = model-only-baseline-v1
```

### P2.2 Evaluation Engine

- [ ] 从 technical freeze resolver 获取最终 100 条评估记录，禁止直接把 pending raw Gold 当正式评估答案。
- [ ] 实现 `scripts/evaluate.py`，逐条静态推理，不执行任何样本命令。
- [ ] 输出 risk Precision/Recall/F1、FPR/FNR。
- [ ] 输出 category Macro-F1、per-category recall、confusion matrix。
- [ ] 输出 decision accuracy、critical/high-risk miss rate。
- [ ] 输出 JSON/schema/summary 合规率。
- [ ] 输出 P50/P95 latency、吞吐、tokens/s 和 VRAM（可用时）。
- [ ] 保存可复现 JSON report，包含模型版本、Prompt 版本、Eval freeze 版本和环境摘要。

### P2.3 目标 GPU Baseline

- [ ] 在目标 RTX 1000 Ada 6GB 本地机器拉取最新 `main`。
- [ ] 指向本地 Qwen2.5-1.5B-Instruct 权重。
- [ ] 运行 environment check + Eval freeze check + Baseline evaluation。
- [ ] 将不含模型权重/敏感信息的评估报告返回并进入 GitHub。
- [ ] 以真实错误分布决定 P3 Rule Engine 优先级。

### P2 验收条件

- 同一模型、Prompt、Eval freeze 可重复生成兼容报告。
- 任何单条坏输出不会终止完整评估；失败被显式计入指标。
- 预测输出不会因为待检测命令中的 prompt injection 改写系统契约。
- 报告可定位每一个错误样本和最终 Gold 标签。
- 性能和显存数据来自目标 6GB GPU 实测，而非估算。

## 6. P2 之后

1. 根据 Baseline 错误分布实现 Rule Engine + Policy Fusion，并用同一 Eval V1 technical freeze 对比 Model-only / Rules-only / Fusion。
2. 根据 Baseline/规则错误分析生产 5k–10k 正式训练数据，按 semantic template / attack family 分组，防止训练评估泄漏。
3. 在 6GB GPU 上进行正式 QLoRA/SFT，与 Baseline 和 Fusion 指标比较。
4. 进入本地 API/SDK、审计、压测和红队持续回归。

## 7. 建议迭代节奏

每次只推进一个可验证工作包。能在 GitHub CI 或隔离 CPU 环境验证的工作由远端完成；只有模型加载、GPU 性能或目标机环境相关门槛才要求本地机器参与。失败时优先修复基线，不带病进入下一阶段。
