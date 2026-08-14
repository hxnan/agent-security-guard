# Agent Security Guard 工作计划

## 1. 执行方式

采用远端仓库作为唯一代码源：代码由可写环境提交到 GitHub，本地受限机器只执行 `git clone`、`git pull`、安装、测试和 GPU 任务。模型权重、私有数据、训练检查点和密钥始终留在本地，不提交到公开仓库。

每个阶段遵循同一门槛：先写验收标准和测试，再实现；完成可执行验证后提交；需要目标硬件时再由本地机器拉取并执行；根据真实结果进入下一阶段。

## 2. 里程碑

| 阶段 | 目标 | 关键交付物 | 完成门槛 |
| --- | --- | --- | --- |
| P0 仓库基线 | 建立可克隆、可安装、可测试的项目 | 契约、分类、环境检查、CI、文档 | 无模型测试全绿；模型文件不入 Git |
| P1 标准与评估集 | 冻结安全边界和 100 条金标样本 | 标注规范、Gold Dataset、Eval V1 | 独立复核；Schema 100% 合规；冻结门禁通过 |
| P2 Baseline 评估 | 接入本地 Qwen 并获得可重复基线 | 推理器、Prompt、evaluate.py、报告 | 指标与性能可复现；失败安全处理 |
| P3 规则与融合 | 降低高危漏报和明显误杀 | 规则引擎、策略配置、融合测试 | 关键规则全覆盖；冲突策略可解释 |
| P4 数据生产 | 构建首批 5k–10k 训练样本 | 生成器、清洗器、数据卡 | 去重与泄漏检查通过；人工抽检达标 |
| P5 QLoRA 训练 | 训练 Security Guard Adapter | 训练脚本、Adapter、模型卡 | 6GB GPU 可运行；优于 Baseline |
| P6 服务化 | 接入真实 Agent 工具调用 | 本地 API、SDK、审计、压测 | P95 延迟和错误兜底达到目标 |
| P7 持续优化 | 红队、反馈闭环和版本治理 | Hard Cases、回归集、发布流程 | 新版本无关键指标回退 |

## 3. 已完成阶段：P0 仓库基线

### 任务

- [x] 建立 Python 可安装项目与 Git 忽略策略。
- [x] 定义 `GuardRequest`、`GuardResult` 和版本字段。
- [x] 定义 12 类风险、严重度和三态决策。
- [x] 提供模型目录与 CUDA 环境检查。
- [x] 编写无 GPU 单元测试和 GitHub Actions。
- [x] 编写总体方案、工作计划和风险分类说明。
- [x] 在目标 WSL2 机器拉取、安装并运行测试。
- [x] 指向本地 Qwen2.5 模型并验证 CUDA、模型文件和真实加载。

### 本地验收命令

```bash
git clone https://github.com/hxnan/agent-security-guard.git
cd agent-security-guard
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m unittest discover -s tests -v

export AGENT_SECURITY_MODEL_PATH=/你的绝对路径/Qwen2.5-1.5B-Instruct
python scripts/check_environment.py
```

### P0 验收条件

- Python 3.10 环境安装成功。
- 所有单元测试通过。
- 环境检查报告 `cuda_available: true`。
- `missing_model_files` 为空。
- 模型权重未出现在 Git 跟踪文件中。

## 4. 当前阶段：P1 标准与 Evaluation Dataset V1

### 已完成工作包

- [x] 将 Pydantic 契约导出为版本化 JSON Schema。
- [x] 编写标注规范，明确主类别选择、三态决策和歧义处理。
- [x] 设计 100 条样本清单：Shell 30、PowerShell 20、CMD 10、Python 30、混合脚本 10。
- [x] 每种语言同时覆盖危险、正常、边界和注入样本。
- [x] 实现 Gold Dataset Pydantic 数据结构、JSONL 加载器、Blueprint 对齐检查和数据统计。
- [x] 实现 Draft/Freeze 两级校验命令；冻结门禁只接受 `agreed` / `adjudicated`。
- [x] 按 Blueprint 完成 EV001–EV100 首轮 Gold Draft，拆成 10 个可复核 shard。
- [x] Gold Draft 明确记录 `source=llm-assisted-draft`、`review_status=pending`，不伪造人工复核状态。
- [x] 对 EV001–EV100 完成第二次机器语义复核，修正 6 个结构校验无法发现的事实、上下文或摘要问题；该复核不计作独立人工复核。
- [x] 实现独立盲审工具：导出只含 `sample_id + request` 的复核包，并自动比较 reviewer 与主 Gold 的 `decision/severity/category/summary` 核心字段。

### 尚未完成

- [ ] 由独立人工 reviewer 在看不到主 Gold 标签的情况下，对 EV001–EV100 逐条判断核心字段并提交复核答案。
- [ ] 对核心字段分歧样本执行讨论/裁决，必要时修改命令、标签、摘要、证据和上下文，并填写 reviewer、disputed/adjudication 元数据。
- [ ] 将一致样本标记为 `agreed`，裁决样本标记为 `adjudicated`，且保留可追溯 reviewer 信息。
- [ ] 运行 `python scripts/validate_eval_dataset.py --require-complete --require-frozen` 并通过。
- [ ] 冻结 `eval-v1`，记录版本和后续变更治理规则。

### 当前 Draft 机器校验

```bash
python scripts/validate_eval_blueprint.py
python scripts/validate_eval_dataset.py --require-complete
python scripts/report_eval_dataset.py
```

冻结前的预期行为：

```bash
python scripts/validate_eval_dataset.py --require-complete --require-frozen
# 应失败，因为当前 100 条仍为 pending
```

### 独立人工盲审流程

导出不包含主 Gold 标签、场景类型、计划类别和治理状态的盲审包：

```bash
python scripts/export_eval_review_packet.py --output /tmp/eval-v1-blind.jsonl
```

reviewer 独立填写答案 JSONL 后进行比对：

```bash
python scripts/compare_eval_review.py --answers /path/to/reviewer-answers.jsonl
```

比对返回码：

- `0`：已提交答案的四个核心字段全部一致；
- `3`：至少一个样本存在核心字段分歧，需要讨论或裁决；
- `1`：输入或数据校验失败。

机器比对不会自动修改 Gold，也不会把任何样本标记为 `agreed` 或 `adjudicated`。

### 跨阶段工程验证

- [x] 准备独立 smoke 数据、6GB QLoRA 脚本、训练门禁和 Adapter 推理检查。
- [x] 在目标 GPU 完成最小训练与 Adapter 推理；3 epoch、36 次更新、峰值显存 2735.78 MB，生成结果通过 GuardResult V1 Schema。该项只验证工程链路，不替代 P1、P2、P4 或 P5 验收。

### P1 验收条件

- 100 条样本唯一且 Schema 合规率 100%。
- 正常样本不少于 40%，防止模型形成“看到命令即危险”的偏差。
- 12 个风险类别均有覆盖；高风险类别包含混淆或组合变体。
- 相同语义模板的近重复样本不跨未来的训练集与评估集。
- 数据版本、生成来源、复核状态和变更记录可追溯。
- 全部样本独立复核完成，并通过 `--require-complete --require-frozen`。

## 5. P1 完成后的执行顺序

1. 实现 Qwen2.5-1.5B-Instruct Baseline Predictor 和固定版本 Prompt。
2. 实现 `evaluate.py`，输出风险检测、多分类、决策、格式和性能指标。
3. 在目标 6GB GPU 上运行第一次正式 Baseline；此时再要求本地机器拉取和验证。
4. 根据真实错误分布实现 Rule Engine + Policy Fusion，并用同一 Eval V1 对比。
5. 根据 Baseline/规则错误分析生产 5k–10k 正式训练数据，再进入正式 QLoRA。

## 6. 建议迭代节奏

每次只推进一个可验证工作包。能在 GitHub CI 或隔离 CPU 环境验证的工作由远端完成；只有模型加载、GPU 性能或目标机环境相关门槛才要求本地机器参与。失败时优先修复基线，不带病进入下一阶段。
