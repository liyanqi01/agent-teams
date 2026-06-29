# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, JsonValue

from relay_teams.computer import ComputerActionRisk, ComputerPermissionScope
from relay_teams.tools.runtime.context import ToolContext
from relay_teams.tools.runtime.models import ToolApprovalRequest
from relay_teams.tools.runtime.policy import EXTERNAL_DIRECTORY_SOURCE
from relay_teams.workspace.handle import WorkspacePathScope


class WorkspaceWritePathResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    requested_path: str
    resolved_path: Path
    directory_path: Path
    external_directory: bool


def resolve_workspace_write_path(
    ctx: ToolContext,
    path: str,
) -> WorkspaceWritePathResolution:
    resolved = ctx.deps.workspace.resolve_workspace_path(
        path,
        write=True,
        allow_external_directory=True,
    )
    if resolved.local_path is None:
        raise ValueError(
            f"Workspace path resolves to non-local mount: {resolved.mount_name}"
        )
    resolved_path = resolved.local_path
    return WorkspaceWritePathResolution(
        requested_path=path,
        resolved_path=resolved_path,
        directory_path=resolved_path.parent.resolve(),
        external_directory=resolved.scope == WorkspacePathScope.EXTERNAL_DIRECTORY,
    )


def build_external_directory_approval_request(
    ctx: ToolContext,
    *,
    tool_name: str,
    tool_input: dict[str, JsonValue],
) -> ToolApprovalRequest | None:
    access = _resolve_external_directory_access(ctx, tool_input)
    if access is None:
        return None
    directory_text = str(access.directory_path)
    return ToolApprovalRequest(
        permission_scope=ComputerPermissionScope.DESTRUCTIVE,
        risk_level=ComputerActionRisk.GUARDED,
        target_summary=directory_text,
        source=EXTERNAL_DIRECTORY_SOURCE,
        cache_key=f"{EXTERNAL_DIRECTORY_SOURCE}:{directory_text}",
        metadata={
            "tool_name": tool_name,
            "requested_path": access.requested_path,
            "resolved_path": str(access.resolved_path),
            "directory_path": directory_text,
        },
    )


def build_external_directory_approval_args_summary(
    ctx: ToolContext,
    *,
    tool_name: str,
    tool_input: dict[str, JsonValue],
) -> dict[str, JsonValue] | None:
    access = _resolve_external_directory_access(ctx, tool_input)
    if access is None:
        return None
    return {
        "permission": EXTERNAL_DIRECTORY_SOURCE,
        "tool": tool_name,
        "path": access.requested_path,
        "directory": str(access.directory_path),
    }


def external_directory_internal_data(
    access: WorkspaceWritePathResolution,
) -> dict[str, JsonValue]:
    return {
        "resolved_path": str(access.resolved_path),
        "external_directory": access.external_directory,
        "external_directory_root": str(access.directory_path),
    }


def _resolve_external_directory_access(
    ctx: ToolContext,
    tool_input: dict[str, JsonValue],
) -> WorkspaceWritePathResolution | None:
    raw_path = tool_input.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    access = resolve_workspace_write_path(ctx, raw_path)
    if not access.external_directory:
        return None
    return access
