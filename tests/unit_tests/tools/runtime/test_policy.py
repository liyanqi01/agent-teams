# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from relay_teams.computer import ComputerActionRisk, ComputerPermissionScope
from relay_teams.tools.runtime.models import ToolApprovalRequest
from relay_teams.tools.runtime.policy import (
    EXTERNAL_DIRECTORY_SOURCE,
    ExternalDirectoryPermissionMode,
    ExternalDirectoryRule,
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


def test_external_directory_rule_can_allow_specific_path(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    target = allowed_root / "nested" / "file.txt"
    policy = ToolApprovalPolicy(
        external_directory_permission=ExternalDirectoryPermissionMode.DENY,
        external_directory_rules=(
            ExternalDirectoryRule(
                path=str(allowed_root),
                permission=ExternalDirectoryPermissionMode.ALLOW,
            ),
        ),
    )

    decision = policy.evaluate(
        "write",
        request=_external_directory_request(target),
    )

    assert decision.runtime_decision == ToolRuntimeDecision.ALLOW


def test_external_directory_rule_can_deny_specific_path(tmp_path: Path) -> None:
    denied_root = tmp_path / "denied"
    target = denied_root / "file.txt"
    policy = ToolApprovalPolicy(
        external_directory_permission=ExternalDirectoryPermissionMode.ALLOW,
        external_directory_rules=(
            ExternalDirectoryRule(
                path=str(denied_root),
                permission=ExternalDirectoryPermissionMode.DENY,
            ),
        ),
    )

    decision = policy.evaluate(
        "write",
        request=_external_directory_request(target),
    )

    assert decision.runtime_decision == ToolRuntimeDecision.DENY


def test_external_directory_rules_use_last_match(tmp_path: Path) -> None:
    shared_root = tmp_path / "shared"
    target = shared_root / "private" / "secret.txt"
    policy = ToolApprovalPolicy(
        external_directory_permission=ExternalDirectoryPermissionMode.DENY,
        external_directory_rules=(
            ExternalDirectoryRule(
                path=str(shared_root),
                permission=ExternalDirectoryPermissionMode.ALLOW,
            ),
            ExternalDirectoryRule(
                path=str(shared_root / "private"),
                permission=ExternalDirectoryPermissionMode.ASK,
            ),
        ),
    )

    decision = policy.evaluate(
        "write",
        request=_external_directory_request(target),
    )

    assert decision.runtime_decision == ToolRuntimeDecision.REQUIRE_APPROVAL


def test_external_directory_glob_rule_matches_resolved_path(tmp_path: Path) -> None:
    target = tmp_path / "projects" / "personal" / "notes.md"
    rule_path = f"{(tmp_path / 'projects').as_posix()}/*/*.md"
    policy = ToolApprovalPolicy(
        external_directory_permission=ExternalDirectoryPermissionMode.DENY,
        external_directory_rules=(
            ExternalDirectoryRule(
                path=rule_path,
                permission=ExternalDirectoryPermissionMode.ALLOW,
            ),
        ),
    )

    decision = policy.evaluate(
        "write",
        request=_external_directory_request(target),
    )

    assert decision.runtime_decision == ToolRuntimeDecision.ALLOW


def test_external_directory_unmatched_rule_uses_global_policy(tmp_path: Path) -> None:
    target = tmp_path / "other" / "file.txt"
    policy = ToolApprovalPolicy(
        external_directory_permission=ExternalDirectoryPermissionMode.DENY,
        external_directory_rules=(
            ExternalDirectoryRule(
                path=str(tmp_path / "allowed"),
                permission=ExternalDirectoryPermissionMode.ALLOW,
            ),
        ),
    )

    decision = policy.evaluate(
        "write",
        request=_external_directory_request(target),
    )

    assert decision.runtime_decision == ToolRuntimeDecision.DENY


def _external_directory_request(path: Path | None = None) -> ToolApprovalRequest:
    target_path = Path("/tmp/outside") if path is None else path
    return ToolApprovalRequest(
        permission_scope=ComputerPermissionScope.DESTRUCTIVE,
        risk_level=ComputerActionRisk.GUARDED,
        target_summary=str(target_path),
        source=EXTERNAL_DIRECTORY_SOURCE,
        cache_key=f"external_directory:{target_path}",
        metadata={"resolved_path": str(target_path)},
    )
