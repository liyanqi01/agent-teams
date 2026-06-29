# -*- coding: utf-8 -*-
from __future__ import annotations

from relay_teams.computer import ComputerActionRisk, ComputerPermissionScope
from relay_teams.tools.runtime.models import ToolApprovalRequest
from relay_teams.tools.runtime.policy import (
    EXTERNAL_DIRECTORY_SOURCE,
    ExternalDirectoryPermissionMode,
    ToolApprovalPolicy,
    ToolRuntimeDecision,
)


def test_default_policy_requires_high_risk_tools() -> None:
    policy = ToolApprovalPolicy()
    assert policy.requires_approval("shell")
    assert policy.requires_approval("edit")
    assert policy.requires_approval("write")
    assert policy.requires_approval("write_tmp")
    assert policy.requires_approval("notebook_edit")
    assert policy.requires_approval("webfetch")
    assert policy.requires_approval("websearch")
    assert not policy.requires_approval("read")


def test_yolo_policy_disables_approval_for_all_tools() -> None:
    policy = ToolApprovalPolicy(yolo=True)

    assert not policy.requires_approval("shell")
    assert not policy.requires_approval("edit")
    assert not policy.requires_approval("write")
    assert not policy.requires_approval("write_tmp")
    assert not policy.requires_approval("orch_create_tasks")


def test_external_directory_policy_asks_by_default() -> None:
    decision = ToolApprovalPolicy().evaluate(
        "write",
        request=_external_directory_request(),
    )

    assert decision.runtime_decision == ToolRuntimeDecision.REQUIRE_APPROVAL


def test_external_directory_policy_can_allow_without_approval() -> None:
    policy = ToolApprovalPolicy(
        external_directory_permission=ExternalDirectoryPermissionMode.ALLOW
    )

    decision = policy.evaluate("write", request=_external_directory_request())

    assert decision.runtime_decision == ToolRuntimeDecision.ALLOW


def test_external_directory_policy_can_deny_access() -> None:
    policy = ToolApprovalPolicy(
        external_directory_permission=ExternalDirectoryPermissionMode.DENY
    )

    decision = policy.evaluate("write", request=_external_directory_request())

    assert decision.runtime_decision == ToolRuntimeDecision.DENY


def test_yolo_policy_overrides_external_directory_denial() -> None:
    policy = ToolApprovalPolicy(
        yolo=True,
        external_directory_permission=ExternalDirectoryPermissionMode.DENY,
    )

    decision = policy.evaluate("write", request=_external_directory_request())

    assert decision.runtime_decision == ToolRuntimeDecision.ALLOW


def _external_directory_request() -> ToolApprovalRequest:
    return ToolApprovalRequest(
        permission_scope=ComputerPermissionScope.DESTRUCTIVE,
        risk_level=ComputerActionRisk.GUARDED,
        target_summary="/tmp/outside",
        source=EXTERNAL_DIRECTORY_SOURCE,
        cache_key="external_directory:/tmp/outside",
    )
