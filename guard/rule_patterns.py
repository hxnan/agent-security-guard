"""Pure high-confidence matcher functions for deterministic security rules."""

import re

from .contracts import GuardRequest
from .rules import RuleMatch
from .taxonomy import Decision, RiskCategory, Severity, ToolType


def _match(
    rule_id: str,
    *,
    category: RiskCategory,
    decision: Decision,
    severity: Severity,
    summary: str,
    evidence: str,
    priority: int = 0,
) -> RuleMatch:
    return RuleMatch(
        rule_id=rule_id,
        category=category,
        decision=decision,
        severity=severity,
        summary=summary,
        evidence=(evidence,),
        priority=priority,
    )


def _contains_control_composition(command: str) -> bool:
    """Conservatively reject command composition before any benign shortcut."""
    return any(
        token in command
        for token in ("|", ">", "<", "&&", "||", ";", "`", "$(", "\n", "\r", "&")
    )


def match_remote_execution_pipe_shell(request: GuardRequest) -> RuleMatch | None:
    if request.type is not ToolType.SHELL:
        return None
    command = request.command
    if not re.search(r"\b(?:curl|wget)\b", command, flags=re.IGNORECASE):
        return None
    if not re.search(r"\|\s*(?:sh|bash|dash|zsh)\b", command, flags=re.IGNORECASE):
        return None
    return _match(
        "rule.remote_execution.pipe_shell.v1",
        category=RiskCategory.REMOTE_EXECUTION,
        decision=Decision.BLOCK,
        severity=Severity.CRITICAL,
        summary="远程内容直接交给解释器执行",
        evidence=command,
        priority=100,
    )


def match_destructive_disk_format(request: GuardRequest) -> RuleMatch | None:
    command = request.command.strip()
    if request.type is ToolType.SHELL:
        matched = re.match(r"^mkfs(?:\.[A-Za-z0-9_-]+)?\s+\S+", command, flags=re.IGNORECASE)
    elif request.type is ToolType.CMD:
        matched = re.match(r"^format\s+[A-Za-z]:(?:\s|$)", command, flags=re.IGNORECASE)
    else:
        matched = None
    if not matched:
        return None
    return _match(
        "rule.destructive_operation.disk_format.v1",
        category=RiskCategory.DESTRUCTIVE_OPERATION,
        decision=Decision.BLOCK,
        severity=Severity.CRITICAL,
        summary="格式化磁盘或文件系统",
        evidence=command,
        priority=100,
    )


def match_destructive_unbounded_delete(request: GuardRequest) -> RuleMatch | None:
    if request.type is not ToolType.SHELL:
        return None
    command = request.command.strip()
    matched = re.match(
        r"^rm\s+-(?=[A-Za-z]*r)(?=[A-Za-z]*f)[A-Za-z]+\s+/(?:\*)?\s*$",
        command,
        flags=re.IGNORECASE,
    )
    if not matched:
        return None
    return _match(
        "rule.destructive_operation.unbounded_delete.v1",
        category=RiskCategory.DESTRUCTIVE_OPERATION,
        decision=Decision.BLOCK,
        severity=Severity.CRITICAL,
        summary="递归强制删除根路径数据",
        evidence=command,
        priority=100,
    )


def _is_direct_read_command(command: str) -> bool:
    return bool(re.match(r"^\s*(?:cat|type|get-content)\b", command, flags=re.IGNORECASE))


def match_private_key_read(request: GuardRequest) -> RuleMatch | None:
    command = request.command
    if request.type not in {ToolType.SHELL, ToolType.CMD, ToolType.POWERSHELL}:
        return None
    if not _is_direct_read_command(command):
        return None
    if not re.search(
        r"\.ssh[\\/](?:id_rsa|id_ed25519|id_ecdsa|id_dsa)(?:\s|$|['\"])",
        command,
        flags=re.IGNORECASE,
    ):
        return None
    return _match(
        "rule.credential_access.private_key_read.v1",
        category=RiskCategory.CREDENTIAL_ACCESS,
        decision=Decision.REVIEW,
        severity=Severity.HIGH,
        summary="读取私有SSH密钥",
        evidence=command,
        priority=90,
    )


def match_credential_store_read(request: GuardRequest) -> RuleMatch | None:
    command = request.command
    if request.type not in {ToolType.SHELL, ToolType.CMD, ToolType.POWERSHELL}:
        return None
    if not _is_direct_read_command(command):
        return None
    if not re.search(r"\.aws[\\/]credentials(?:\s|$|['\"])", command, flags=re.IGNORECASE):
        return None
    return _match(
        "rule.credential_access.credential_store_read.v1",
        category=RiskCategory.CREDENTIAL_ACCESS,
        decision=Decision.REVIEW,
        severity=Severity.HIGH,
        summary="读取已知凭据存储文件",
        evidence=command,
        priority=90,
    )


def match_disable_security_control(request: GuardRequest) -> RuleMatch | None:
    command = request.command.strip()
    lower = command.lower()
    powershell_disable = (
        request.type is ToolType.POWERSHELL
        and re.search(r"\bset-mppreference\b", lower)
        and re.search(r"-disablerealtimemonitoring\s+\$true\b", lower)
    )
    firewall_disable = (
        request.type is ToolType.CMD
        and re.search(
            r"^netsh\s+advfirewall\s+set\s+allprofiles\s+state\s+off(?:\s|$)",
            lower,
        )
    )
    if not (powershell_disable or firewall_disable):
        return None
    return _match(
        "rule.defense_evasion.disable_security_control.v1",
        category=RiskCategory.DEFENSE_EVASION,
        decision=Decision.BLOCK,
        severity=Severity.CRITICAL,
        summary="显式关闭系统安全防护",
        evidence=command,
        priority=100,
    )


def match_autostart_install(request: GuardRequest) -> RuleMatch | None:
    if request.type is not ToolType.SHELL:
        return None
    command = request.command.strip()
    if not re.search(r"\|\s*crontab\s+-\s*$", command, flags=re.IGNORECASE):
        return None
    return _match(
        "rule.persistence.autostart_install.v1",
        category=RiskCategory.PERSISTENCE,
        decision=Decision.REVIEW,
        severity=Severity.HIGH,
        summary="写入定时或启动持久化任务",
        evidence=command,
        priority=80,
    )


_GIT_STATUS_OPTIONS = {
    "--short",
    "-s",
    "--porcelain",
    "--porcelain=v1",
    "--branch",
    "-b",
}


def match_benign_git_status(request: GuardRequest) -> RuleMatch | None:
    if request.type is not ToolType.SHELL:
        return None
    command = request.command.strip()
    if _contains_control_composition(command):
        return None
    tokens = command.split()
    if len(tokens) < 2 or tokens[0] != "git" or tokens[1] != "status":
        return None
    if any(token not in _GIT_STATUS_OPTIONS for token in tokens[2:]):
        return None
    return _match(
        "rule.benign.git_status.v1",
        category=RiskCategory.BENIGN,
        decision=Decision.ALLOW,
        severity=Severity.NONE,
        summary="只读查看Git工作区状态",
        evidence=command,
        priority=10,
    )


RULE_MATCHERS = (
    match_remote_execution_pipe_shell,
    match_destructive_disk_format,
    match_destructive_unbounded_delete,
    match_private_key_read,
    match_credential_store_read,
    match_disable_security_control,
    match_autostart_install,
    match_benign_git_status,
)
