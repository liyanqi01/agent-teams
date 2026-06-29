# -*- coding: utf-8 -*-
from __future__ import annotations

import fnmatch
import os
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from relay_teams.computer import ComputerActionRisk
from relay_teams.tools.runtime.guardrails import RuntimeGuardrailPolicy
from relay_teams.tools.runtime.models import (
    ToolApprovalDecision,
    ToolApprovalRequest,
    ToolRuntimeDecision,
)

EXTERNAL_DIRECTORY_SOURCE = "external_directory"

DEFAULT_APPROVAL_REQUIRED_TOOLS = frozenset(
    {
        "orch_create_tasks",
        "orch_dispatch_task",
        "orch_update_task",
        "shell",
        "edit",
        "notebook_edit",
        "write",
        "write_tmp",
        "webfetch",
        "websearch",
    }
)


class ExternalDirectoryPermissionMode(str, Enum):
    ASK = "ask"
    ALLOW = "allow"
    DENY = "deny"


class ExternalDirectoryRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1)
    permission: ExternalDirectoryPermissionMode = ExternalDirectoryPermissionMode.ALLOW

    @field_validator("path")
    @classmethod
    def _normalize_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("External directory rule path must not be blank")
        return normalized


class ToolRuntimePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    yolo: bool = False
    shell_safety_policy_enabled: bool = True
    external_directory_permission: ExternalDirectoryPermissionMode = (
        ExternalDirectoryPermissionMode.ASK
    )
    external_directory_rules: tuple[ExternalDirectoryRule, ...] = ()
    approval_required_tools: frozenset[str] = DEFAULT_APPROVAL_REQUIRED_TOOLS
    denied_tools: frozenset[str] = frozenset()
    guardrails: RuntimeGuardrailPolicy = Field(default_factory=RuntimeGuardrailPolicy)
    timeout_seconds: float = 300.0

    def requires_approval(self, tool_name: str) -> bool:
        return self.evaluate(tool_name).required

    def evaluate(
        self,
        tool_name: str,
        request: ToolApprovalRequest | None = None,
        *,
        role_id: str = "",
        task_id: str = "",
        allowed_tools: tuple[str, ...] | None = None,
    ) -> ToolApprovalDecision:
        _ = task_id
        if tool_name in self.denied_tools:
            return _runtime_decision(
                required=False,
                runtime_decision=ToolRuntimeDecision.DENY,
                reason=f"Tool {tool_name} is denied by runtime policy.",
                request=request,
            )
        if allowed_tools is not None and tool_name not in allowed_tools:
            role_label = role_id or "current role"
            return _runtime_decision(
                required=False,
                runtime_decision=ToolRuntimeDecision.DENY,
                reason=f"Tool {tool_name} is not authorized for {role_label}.",
                request=request,
            )
        if self.yolo:
            return _runtime_decision(
                required=False,
                runtime_decision=ToolRuntimeDecision.ALLOW,
                request=request,
            )
        if request is not None and request.source == EXTERNAL_DIRECTORY_SOURCE:
            external_directory_permission = (
                self.external_directory_permission_for_request(request)
            )
            if external_directory_permission == ExternalDirectoryPermissionMode.DENY:
                return _runtime_decision(
                    required=False,
                    runtime_decision=ToolRuntimeDecision.DENY,
                    reason="External directory access is denied by runtime policy.",
                    request=request,
                )
            if external_directory_permission == ExternalDirectoryPermissionMode.ALLOW:
                return _runtime_decision(
                    required=False,
                    runtime_decision=ToolRuntimeDecision.ALLOW,
                    reason="External directory access is allowed by runtime policy.",
                    request=request,
                )
        if request is not None:
            if request.risk_level in {
                ComputerActionRisk.GUARDED,
                ComputerActionRisk.DESTRUCTIVE,
            }:
                return _runtime_decision(
                    required=True,
                    runtime_decision=ToolRuntimeDecision.REQUIRE_APPROVAL,
                    request=request,
                )
            if request.risk_level == ComputerActionRisk.SAFE:
                return _runtime_decision(
                    required=False,
                    runtime_decision=ToolRuntimeDecision.ALLOW,
                    request=request,
                )
        required = tool_name in self.approval_required_tools
        return _runtime_decision(
            required=required,
            runtime_decision=(
                ToolRuntimeDecision.REQUIRE_APPROVAL
                if required
                else ToolRuntimeDecision.ALLOW
            ),
            request=request,
        )

    def external_directory_permission_for_request(
        self,
        request: ToolApprovalRequest,
    ) -> ExternalDirectoryPermissionMode:
        resolved_path = request.metadata.get("resolved_path")
        if not isinstance(resolved_path, str) or not resolved_path.strip():
            return self.external_directory_permission
        return self.external_directory_permission_for_path(resolved_path)

    def external_directory_permission_for_path(
        self,
        resolved_path: str,
    ) -> ExternalDirectoryPermissionMode:
        target = _resolve_external_directory_target(resolved_path)
        if target is None:
            return self.external_directory_permission
        permission = self.external_directory_permission
        for rule in self.external_directory_rules:
            if _external_directory_rule_matches(rule.path, target):
                permission = rule.permission
        return permission


class ToolApprovalPolicy(ToolRuntimePolicy):
    def with_yolo(self, yolo: bool) -> ToolApprovalPolicy:
        return self.with_runtime_overrides(yolo=yolo)

    def with_runtime_overrides(
        self,
        *,
        yolo: bool | None = None,
        shell_safety_policy_enabled: bool | None = None,
        external_directory_permission: ExternalDirectoryPermissionMode | None = None,
        external_directory_rules: tuple[ExternalDirectoryRule, ...] | None = None,
    ) -> ToolApprovalPolicy:
        next_yolo = self.yolo if yolo is None else yolo
        next_shell_safety_policy_enabled = (
            self.shell_safety_policy_enabled
            if shell_safety_policy_enabled is None
            else shell_safety_policy_enabled
        )
        next_external_directory_permission = (
            self.external_directory_permission
            if external_directory_permission is None
            else external_directory_permission
        )
        next_external_directory_rules = (
            self.external_directory_rules
            if external_directory_rules is None
            else external_directory_rules
        )
        if (
            next_yolo == self.yolo
            and next_shell_safety_policy_enabled == self.shell_safety_policy_enabled
            and next_external_directory_permission == self.external_directory_permission
            and next_external_directory_rules == self.external_directory_rules
        ):
            return self
        return ToolApprovalPolicy(
            yolo=next_yolo,
            shell_safety_policy_enabled=next_shell_safety_policy_enabled,
            external_directory_permission=next_external_directory_permission,
            external_directory_rules=next_external_directory_rules,
            approval_required_tools=self.approval_required_tools,
            denied_tools=self.denied_tools,
            guardrails=self.guardrails,
            timeout_seconds=self.timeout_seconds,
        )


def _runtime_decision(
    *,
    required: bool,
    runtime_decision: ToolRuntimeDecision,
    request: ToolApprovalRequest | None = None,
    reason: str = "",
) -> ToolApprovalDecision:
    return ToolApprovalDecision(
        required=required,
        runtime_decision=runtime_decision,
        reason=reason,
        permission_scope=request.permission_scope if request is not None else None,
        risk_level=request.risk_level if request is not None else None,
        target_summary=request.target_summary if request is not None else "",
        source=request.source if request is not None else "",
        execution_surface=request.execution_surface if request is not None else None,
    )


def _resolve_external_directory_target(value: str) -> Path | None:
    try:
        return Path(_expand_external_directory_home(value)).resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def _external_directory_rule_matches(rule_path: str, target: Path) -> bool:
    expanded = _expand_external_directory_home(rule_path)
    if _contains_glob(expanded):
        pattern = _normalize_external_directory_glob(expanded)
        if pattern is None:
            return False
        return fnmatch.fnmatchcase(_path_match_text(target), pattern)
    root = _resolve_external_directory_target(expanded)
    if root is None or not root.is_absolute():
        return False
    return target == root or target.is_relative_to(root)


def _expand_external_directory_home(value: str) -> str:
    normalized = value.strip()
    home = str(Path.home())
    if normalized == "~":
        return home
    if normalized.startswith("~/") or normalized.startswith("~\\"):
        return f"{home}{normalized[1:]}"
    if normalized == "$HOME":
        return home
    if normalized.startswith("$HOME/") or normalized.startswith("$HOME\\"):
        return f"{home}{normalized[5:]}"
    if normalized == "${HOME}":
        return home
    if normalized.startswith("${HOME}/") or normalized.startswith("${HOME}\\"):
        return f"{home}{normalized[7:]}"
    return normalized


def _contains_glob(value: str) -> bool:
    return _first_glob_index(value) is not None


def _first_glob_index(value: str) -> int | None:
    indexes = tuple(
        index
        for index in (value.find("*"), value.find("?"), value.find("["))
        if index >= 0
    )
    if not indexes:
        return None
    return min(indexes)


def _normalize_external_directory_glob(value: str) -> str | None:
    wildcard_index = _first_glob_index(value)
    if wildcard_index is None:
        return None
    parent_index = max(
        value.rfind("/", 0, wildcard_index),
        value.rfind("\\", 0, wildcard_index),
    )
    if parent_index < 0:
        return None
    if parent_index == 0:
        base_text = value[:1]
        suffix_text = value[1:]
    else:
        base_text = value[:parent_index]
        suffix_text = value[parent_index:]
    base = _resolve_external_directory_target(base_text)
    if base is None or not base.is_absolute():
        return None
    pattern = f"{_path_match_text(base)}{_normalize_glob_suffix(suffix_text)}"
    if os.name == "nt":
        return pattern.casefold()
    return pattern


def _normalize_glob_suffix(value: str) -> str:
    return value.replace("\\", "/")


def _path_match_text(path: Path) -> str:
    text = path.as_posix()
    if os.name == "nt":
        return text.casefold()
    return text
