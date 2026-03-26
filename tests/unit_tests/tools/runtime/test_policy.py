# -*- coding: utf-8 -*-
from __future__ import annotations

from agent_teams.tools.runtime import ToolApprovalPolicy


def test_default_policy_requires_high_risk_tools() -> None:
    policy = ToolApprovalPolicy()
    assert policy.requires_approval("shell")
    assert policy.requires_approval("edit")
    assert policy.requires_approval("write")
    assert policy.requires_approval("write_tmp")
    assert not policy.requires_approval("read")


def test_default_policy_requires_high_risk_computer_actions() -> None:
    policy = ToolApprovalPolicy()

    assert policy.requires_computer_action_approval(
        "click",
        has_pending_safety_checks=False,
    )
    assert policy.requires_computer_action_approval(
        "type",
        has_pending_safety_checks=False,
    )
    assert not policy.requires_computer_action_approval(
        "wait",
        has_pending_safety_checks=False,
    )
    assert policy.requires_computer_action_approval(
        "wait",
        has_pending_safety_checks=True,
    )
    assert (
        policy.computer_action_risk_level(
            "click",
            has_pending_safety_checks=False,
        )
        == "high"
    )
    assert (
        policy.computer_action_risk_level(
            "wait",
            has_pending_safety_checks=False,
        )
        == "low"
    )


def test_yolo_policy_disables_approval_for_all_tools_and_actions() -> None:
    policy = ToolApprovalPolicy(yolo=True)

    assert not policy.requires_approval("shell")
    assert not policy.requires_approval("edit")
    assert not policy.requires_approval("write")
    assert not policy.requires_approval("write_tmp")
    assert not policy.requires_approval("create_tasks")
    assert not policy.requires_computer_action_approval(
        "click",
        has_pending_safety_checks=False,
    )
    assert policy.requires_computer_action_approval(
        "click",
        has_pending_safety_checks=True,
    )
