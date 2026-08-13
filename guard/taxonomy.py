"""Stable risk taxonomy shared by policy, datasets, and model outputs."""

from dataclasses import dataclass
from enum import Enum


class StringEnum(str, Enum):
    """String-valued enum compatible with Python 3.10."""


class ToolType(StringEnum):
    SHELL = "shell"
    POWERSHELL = "powershell"
    CMD = "cmd"
    PYTHON = "python"
    TOOL = "tool"


class Decision(StringEnum):
    ALLOW = "allow"
    REVIEW = "review"
    BLOCK = "block"


class Severity(StringEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskCategory(StringEnum):
    REMOTE_EXECUTION = "remote_execution"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    DESTRUCTIVE_OPERATION = "destructive_operation"
    CREDENTIAL_ACCESS = "credential_access"
    DATA_EXFILTRATION = "data_exfiltration"
    PERSISTENCE = "persistence"
    DEFENSE_EVASION = "defense_evasion"
    UNSAFE_DOWNLOAD = "unsafe_download"
    NETWORK_CHANGE = "network_change"
    SENSITIVE_WRITE = "sensitive_write"
    RESOURCE_ABUSE = "resource_abuse"
    BENIGN = "benign"


@dataclass(frozen=True)
class CategoryDefinition:
    name_zh: str
    description: str
    default_severity: Severity
    default_decision: Decision


CATEGORY_DEFINITIONS: dict[RiskCategory, CategoryDefinition] = {
    RiskCategory.REMOTE_EXECUTION: CategoryDefinition(
        "远程代码执行", "下载或接收远程内容并直接执行", Severity.CRITICAL, Decision.BLOCK
    ),
    RiskCategory.PRIVILEGE_ESCALATION: CategoryDefinition(
        "权限提升", "获取或使用高于当前主体的系统权限", Severity.HIGH, Decision.REVIEW
    ),
    RiskCategory.DESTRUCTIVE_OPERATION: CategoryDefinition(
        "破坏性操作", "删除、覆盖或不可逆修改系统与业务数据", Severity.CRITICAL, Decision.BLOCK
    ),
    RiskCategory.CREDENTIAL_ACCESS: CategoryDefinition(
        "凭据访问", "读取、导出或修改口令、令牌、密钥等凭据", Severity.HIGH, Decision.REVIEW
    ),
    RiskCategory.DATA_EXFILTRATION: CategoryDefinition(
        "数据外传", "将敏感数据发送到未授权目标", Severity.CRITICAL, Decision.BLOCK
    ),
    RiskCategory.PERSISTENCE: CategoryDefinition(
        "持久化", "建立开机、自启动、定时或隐蔽驻留机制", Severity.HIGH, Decision.REVIEW
    ),
    RiskCategory.DEFENSE_EVASION: CategoryDefinition(
        "防御规避", "关闭审计、安全软件或隐藏恶意活动", Severity.CRITICAL, Decision.BLOCK
    ),
    RiskCategory.UNSAFE_DOWNLOAD: CategoryDefinition(
        "不安全下载", "从不可信来源获取文件但未直接执行", Severity.MEDIUM, Decision.REVIEW
    ),
    RiskCategory.NETWORK_CHANGE: CategoryDefinition(
        "网络配置变更", "修改防火墙、代理、DNS、路由或监听配置", Severity.HIGH, Decision.REVIEW
    ),
    RiskCategory.SENSITIVE_WRITE: CategoryDefinition(
        "敏感位置写入", "写入系统目录、启动项或关键配置", Severity.HIGH, Decision.REVIEW
    ),
    RiskCategory.RESOURCE_ABUSE: CategoryDefinition(
        "资源滥用", "异常消耗计算、存储或网络资源", Severity.MEDIUM, Decision.REVIEW
    ),
    RiskCategory.BENIGN: CategoryDefinition(
        "正常操作", "未发现需要拦截或复核的安全风险", Severity.NONE, Decision.ALLOW
    ),
}
