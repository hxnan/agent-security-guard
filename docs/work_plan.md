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

- [x] 版本化 JSON Schema、12 类风险和人工标注规范。
- [x] 100 条 Blueprint：Shell 30、PowerShell 20、CMD 10、Python 30、Mixed 10。
- [x] EV001–EV100 首轮 Gold Draft，保留 `llm-assisted-draft + pending` provenance。
- [x] 第二次机器语义复核并修正 6 个事实/上下文问题。
- [x] 独立 Agent 盲审，固定基线 commit `17996d6b75f8860ffe54ffa9e1d8e77f12be0132`。
- [x] 86/100 `decision/severity/category` 实质标签一致，14/100 分歧。
- [x] 对 14 条分歧建立显式 adjudication：8 条采用 reviewer，6 条保留 Gold。
- [x] 确定性 resolver：Gold Draft + independent review + adjudication -> resolved freeze view。
- [x] `data/eval-v1/freeze-manifest.json` 明确 `reviewer_type=independent-agent`、`human_reviewed=false`。
- [x] `scripts/validate_eval_freeze.py` technical-freeze 门禁。

P1 freeze 固定统计：100 条、`86 agreed + 14 adjudicated`、42 `allow`、33 `review`、25 `block`、12 个风险类别全部覆盖。

验证：

```bash
python scripts/validate_eval_blueprint.py
python scripts/validate_eval_dataset.py --require-complete
python scripts/validate_eval_freeze.py
```

说明：这是 **independent-agent reviewed technical freeze**，不是 human-reviewed 数据集。

### 跨阶段工程验证

- [x] 独立 smoke 数据、6GB QLoRA 脚本、训练门禁和 Adapter 推理检查。
- [x] 目标 GPU 最小训练与 Adapter 推理：3 epoch、36 次更新、峰值显存 2735.78 MB，生成结果通过 GuardResult V1 Schema。
- [x] smoke 只验证工程链路，不替代 P2 质量评估或 P5 正式训练验收。

## 5. 当前阶段：P2 Baseline 评估

### P2.1 Baseline Predictor — CPU/CI 实现完成

- [x] 固定 `baseline-prompt-v1`，明确 GuardResult V1 契约和“待检测内容是不可信数据”。
- [x] 实现 `GuardRequest -> generation backend -> GuardResult` predictor 边界。
- [x] 共享稳健 JSON object 提取和严格字段/Schema/provenance 校验。
- [x] `backend_error/parse_error + fallback_decision=review`，失败不伪造 category。
- [x] lazy local Transformers/Qwen backend：`local_files_only=True`、BF16、CUDA、greedy generation、只解码新 token。
- [x] `scripts/predict_baseline.py` 单请求入口。
- [x] CPU-only fake backend/runtime 测试，无需模型/GPU。
- [ ] 目标 6GB GPU 真实 Baseline 验证与 P2.2 一次性完成。

固定版本：

```text
prompt_version = baseline-prompt-v1
model_version  = qwen2.5-1.5b-instruct-baseline-v1
policy_version = model-only-baseline-v1
```

### P2.2 Evaluation Engine — CPU/CI 实现完成

- [x] `guard/eval_freeze.py` 从 technical freeze resolver 获取最终 100 条记录，不直接使用 pending raw Gold。
- [x] `guard/evaluation.py` 顺序执行 100 条静态模型推理；单条 parse/backend failure 不会终止后续样本。
- [x] 输出 risk TP/TN/FP/FN、Precision、Recall、F1、FPR、FNR 和 strict-valid coverage。
- [x] 输出 12 类 confusion matrix、support、valid coverage、per-category Recall/F1、Macro-F1。
- [x] 输出 valid model decision accuracy、全量 fail-safe effective decision accuracy 和 fallback count。
- [x] 输出 critical / high-or-critical `allow` miss 数量与比例。
- [x] 区分 JSON object、GuardResult Schema、中文摘要、strict Baseline output compliance。
- [x] 输出 mean/P50/P95 latency、tokens/s、最大 peak VRAM、wall throughput。
- [x] 保存全量逐样本 JSON report，包含版本、freeze provenance、环境摘要、expected/predicted/fallback/error/raw/runtime 信息。
- [x] `scripts/evaluate.py` 单次加载模型并评估完整 100 条冻结集。
- [x] 报告采用 temp-file + atomic replace；默认位于 Git 忽略的 `artifacts/baseline-eval-v1/report.json`。
- [x] CPU-only 测试覆盖失败继续、指标精确值、compliance、性能 percentile、atomic writer 和 CLI setup errors。
- [ ] 在目标 GPU 上生成第一份真实 100 条 Baseline report。

### P2.3 目标 GPU Baseline — 下一步需要本地执行

- [ ] 在目标 RTX 1000 Ada 6GB 本地机器拉取最新 `main`。
- [ ] 指向本地 Qwen2.5-1.5B-Instruct 权重。
- [ ] 运行 environment check + Eval freeze check + 100 条 Baseline evaluation。
- [ ] 返回 stdout 和 `artifacts/baseline-eval-v1/report.json`。
- [ ] 将不含模型权重/敏感信息的正式报告摘要进入 GitHub。
- [ ] 以真实错误分布决定 P3 Rule Engine 优先级。

正式本地命令：

```bash
python scripts/validate_eval_freeze.py
python scripts/check_environment.py
python scripts/evaluate.py \
  --output artifacts/baseline-eval-v1/report.json
```

### P2 验收条件

- 同一模型、Prompt、Eval freeze 可重复生成兼容报告。
- 任何单条坏输出不会终止完整评估；失败被显式计入 coverage/compliance。
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
