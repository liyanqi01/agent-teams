# -*- coding: utf-8 -*-
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


DEFAULT_APPROVAL_REQUIRED_TOOLS = frozenset(
    {
        "create_tasks",
        "dispatch_task",
        "update_task",
        "shell",
        "edit",
        "write",
        "write_tmp",
    }
)
DEFAULT_APPROVAL_REQUIRED_COMPUTER_ACTIONS = frozenset(
    {
        "click",
        "double_click",
        "drag",
        "keypress",
        "type",
    }
)


class ToolApprovalPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    yolo: bool = False
    approval_required_tools: frozenset[str] = DEFAULT_APPROVAL_REQUIRED_TOOLS
    approval_required_computer_actions: frozenset[str] = (
        DEFAULT_APPROVAL_REQUIRED_COMPUTER_ACTIONS
    )
    timeout_seconds: float = 300.0

    def requires_approval(self, tool_name: str) -> bool:
        if self.yolo:
            return False
        return tool_name in self.approval_required_tools

    def requires_computer_action_approval(
        self,
        action_type: str,
        *,
        has_pending_safety_checks: bool,
    ) -> bool:
        if has_pending_safety_checks:
            return True
        if self.yolo:
            return False
        return action_type in self.approval_required_computer_actions

    def computer_action_risk_level(
        self,
        action_type: str,
        *,
        has_pending_safety_checks: bool,
    ) -> str:
        if has_pending_safety_checks:
            return "high"
        if action_type in self.approval_required_computer_actions:
            return "high"
        return "low"

    def with_yolo(self, yolo: bool) -> ToolApprovalPolicy:
        if yolo == self.yolo:
            return self
        return ToolApprovalPolicy(
            yolo=yolo,
            approval_required_tools=self.approval_required_tools,
            approval_required_computer_actions=self.approval_required_computer_actions,
            timeout_seconds=self.timeout_seconds,
        )
