# Agent Security Guard 风险分类 V1

状态：Draft V1
适用范围：Agent 在执行 Shell、PowerShell、CMD、Python 和通用工具调用前的静态安全判定。

## 判定原则

1. 结合命令语义、参数、执行环境和数据流判断，不以单个关键词直接定罪。
2. `risk` 表示存在需处置的风险；最终处置使用 `allow`、`review`、`block` 三态。
3. 无法可靠理解、上下文不足或模型输出异常时，不得静默放行，应进入 `review`。
4. 分类描述行为的主要安全影响；多个风险并存时，输出影响最大且最接近最终目的的主类别，其他证据保留在 `evidence` 或规则命中中。
5. `benign` 只用于有充分证据表明操作正常的样本，不作为“不知道”的兜底类别。

## 分类表

| 标识 | 中文名 | 范围 | 默认严重度 | 默认决策 |
| --- | --- | --- | --- | --- |
| `remote_execution` | 远程代码执行 | 下载或接收远程内容并直接解释、加载或执行 | critical | block |
| `privilege_escalation` | 权限提升 | 获取、切换或滥用管理员、root、SYSTEM 等更高权限 | high | review |
| `destructive_operation` | 破坏性操作 | 大范围删除、覆盖、格式化或不可逆修改系统与业务数据 | critical | block |
| `credential_access` | 凭据访问 | 读取、导出、修改口令、令牌、私钥、浏览器凭据等 | high | review |
| `data_exfiltration` | 数据外传 | 将敏感信息编码、上传或发送至未授权目标 | critical | block |
| `persistence` | 持久化 | 创建启动项、计划任务、服务或其他长期驻留机制 | high | review |
| `defense_evasion` | 防御规避 | 关闭安全软件、日志、审计，或混淆和隐藏活动 | critical | block |
| `unsafe_download` | 不安全下载 | 从不可信或不明确来源获取内容，但未在同一行为中执行 | medium | review |
| `network_change` | 网络配置变更 | 修改防火墙、DNS、代理、路由、监听端口等 | high | review |
| `sensitive_write` | 敏感位置写入 | 写入系统目录、关键配置、启动位置或受保护资源 | high | review |
| `resource_abuse` | 资源滥用 | 异常占用计算、存储、进程或网络资源 | medium | review |
| `benign` | 正常操作 | 未发现需拦截或复核的安全风险 | none | allow |

## 类别边界和示例

### `remote_execution`

- 包含：`curl ... | bash`、PowerShell 下载后直接 `Invoke-Expression`、Python 获取远程文本后 `exec`。
- 不包含：仅下载文件但不执行，归为 `unsafe_download`；执行可信的本地项目脚本需结合来源、路径和上下文判断。

### `privilege_escalation`

- 包含：修改 sudoers、绕过 UAC、授予高权限角色、以 SYSTEM 身份启动进程。
- 不包含：经批准的普通 `sudo apt update` 不应仅因出现 `sudo` 就判定为恶意；上下文不足时可 `review`。

### `destructive_operation`

- 包含：递归删除根目录或关键业务目录、磁盘格式化、大范围不可恢复覆盖。
- 不包含：删除明确的临时文件或构建产物，通常为 `benign`。

### `credential_access`

- 包含：读取 SSH 私钥、云服务凭据、浏览器密码库、系统凭据存储。
- 不包含：列出环境变量名称而不读取值；访问明确用于测试的虚构凭据。

### `data_exfiltration`

- 包含：打包敏感目录并上传、向外部端点发送令牌或业务数据。
- 不包含：从公共源下载内容；向已批准的内部制品库上传公开构建产物。

### `persistence`

- 包含：新增开机启动项、计划任务、系统服务、登录脚本或 shell profile 注入。
- 不包含：项目内普通配置文件修改，除非它会在未来自动执行代码。

### `defense_evasion`

- 包含：停止 EDR、清除审计日志、禁用脚本扫描或使用混淆隐藏意图。
- 不包含：为合规目的轮转日志；调试时短暂调整应用自身日志级别。

### `unsafe_download`

- 包含：从短链、裸 IP、未知站点或未校验来源下载可执行内容。
- 不包含：`git clone` 公共项目本身不构成风险；下载后立即执行应归为 `remote_execution`。

### `network_change`

- 包含：开放公网端口、关闭防火墙、改变 DNS 或代理、增加持久路由。
- 不包含：只读查看连接、端口和路由状态。

### `sensitive_write`

- 包含：改写系统配置、启动目录、受保护二进制或全局 shell 配置。
- 不包含：在当前项目工作区创建普通源文件和构建文件。

### `resource_abuse`

- 包含：加密货币挖矿、fork bomb、无边界并发、故意填满磁盘。
- 不包含：有明确上限且符合任务需要的编译、训练或性能测试。

### `benign`

- 包含：`git status`、只读系统查询、在项目目录内运行测试、从可信源正常克隆代码。
- 不包含：因信息不足而无法判断的行为；此类应输出 `review`，并使用最接近的风险类别。

## 标注时必须记录的上下文

- 工具类型与原始命令或代码。
- 当前目录及目标路径是否越出授权工作区。
- 调用主体及权限等级。
- 网络目标、来源可信度和是否立即执行下载内容。
- 操作范围、可逆性、数据敏感度和业务目的。

本文件中的默认严重度和决策是基线，不代替企业策略。后续策略层可按主体、环境、资产和允许列表进行收紧或放宽。
