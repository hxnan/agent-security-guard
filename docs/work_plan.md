# Agent Security Guard 工作计划

## 1. 执行方式

采用远端仓库作为唯一代码源：代码由可写环境提交到 GitHub，本地受限机器只执行 `git clone`、`git pull`、安装、测试和 GPU 任务。模型权重、私有数据、训练检查点和密钥始终留在本地，不提交到公开仓库。

每个阶段遵循同一门槛：先写验收标准和测试，再实现；完成本地验证后提交；本地机器拉取并执行；根据真实结果进入下一阶段。

## 2. 里程碑

| 阶段 | 目标 | 关键交付物 | 完成门槛 |
| --- | --- | --- | --- |
| P0 仓库基线 | 建立可克隆、可安装、可测试的项目 | 契约、分类、环境检查、CI、文档 | 无模型测试全绿；模型文件不入 Git |
| P1 标准与评估集 | 冻结安全边界和 100 条金标样本 | 标注规范、JSONL Schema、Eval V1 | 双人或二次复核；Schema 100% 合规 |
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

### 工作包

- [x] 将 Pydantic 契约导出为版本化 JSON Schema。
- [x] 编写标注规范，明确主类别选择、三态决策和歧义处理。
- [x] 设计 100 条样本清单：Shell 30、PowerShell 20、CMD 10、Python 30、混合脚本 10。
- [x] 每种语言同时覆盖危险、正常、边界和注入样本。
- [ ] 实现 JSONL 校验器和数据统计脚本。
- [ ] 人工逐条复核标签与摘要，冻结 `eval-v1`。

### P1 验收条件

- 100 条样本唯一且 Schema 合规率 100%。
- 正常样本不少于 40%，防止模型形成“看到命令即危险”的偏差。
- 12 个风险类别均有覆盖；高风险类别包含混淆或组合变体。
- 相同语义模板的近重复样本不跨未来的训练集与评估集。
- 数据版本、生成来源、复核状态和变更记录可追溯。

## 5. 建议迭代节奏

每次只推进一个可验证工作包。远端提交后，本地机器执行验收命令并反馈完整输出；若失败，优先修复基线，不带病进入下一阶段。P1 完成后再接入模型 Baseline，避免在风险定义仍变化时反复修改推理和训练代码。
