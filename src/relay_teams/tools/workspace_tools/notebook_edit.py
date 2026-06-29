# -*- coding: utf-8 -*-
from __future__ import annotations

from pydantic import JsonValue
from pydantic_ai import Agent

from relay_teams.tools._description_loader import load_tool_description
from relay_teams.tools.runtime.context import (
    ToolContext,
    ToolDeps,
)
from relay_teams.tools.runtime.execution import execute_tool_call
from relay_teams.tools.runtime.models import ToolResultProjection
from relay_teams.tools.workspace_tools.external_directory import (
    build_external_directory_approval_args_summary,
    build_external_directory_approval_request,
    external_directory_internal_data,
    resolve_workspace_write_path,
)
from relay_teams.tools.workspace_tools.notebook import (
    CellType,
    EditMode,
    notebook_edit_file_with_guard,
)

DESCRIPTION = load_tool_description(__file__)


def _project_notebook_edit_result(
    result: dict[str, JsonValue],
    *,
    extra_internal_data: dict[str, JsonValue] | None = None,
) -> ToolResultProjection:
    internal_data = dict(result)
    if extra_internal_data is not None:
        internal_data.update(extra_internal_data)
    return ToolResultProjection(
        visible_data={"output": result["output"]},
        internal_data=internal_data,
    )


def register(agent: Agent[ToolDeps, str]) -> None:
    @agent.tool(description=DESCRIPTION)
    async def notebook_edit(
        ctx: ToolContext,
        path: str,
        new_source: str,
        cell_id: str | None = None,
        cell_type: CellType | None = None,
        edit_mode: EditMode = "replace",
    ) -> dict[str, JsonValue]:
        """Edit a Jupyter notebook cell without editing raw JSON."""

        def _action(
            path: str,
            new_source: str,
            cell_id: str | None = None,
            cell_type: CellType | None = None,
            edit_mode: EditMode = "replace",
        ) -> ToolResultProjection:
            access = resolve_workspace_write_path(ctx, path)
            file_path = access.resolved_path
            result = notebook_edit_file_with_guard(
                shared_store=ctx.deps.shared_store,
                session_id=ctx.deps.session_id,
                conversation_id=ctx.deps.conversation_id,
                file_path=file_path,
                cell_id=cell_id,
                new_source=new_source,
                cell_type=cell_type,
                edit_mode=edit_mode,
            )
            return _project_notebook_edit_result(
                result,
                extra_internal_data=external_directory_internal_data(access),
            )

        return await execute_tool_call(
            ctx,
            tool_name="notebook_edit",
            args_summary={
                "path": path,
                "cell_id": cell_id,
                "new_source_len": len(new_source),
                "cell_type": cell_type,
                "edit_mode": edit_mode,
            },
            action=_action,
            raw_args=locals(),
            approval_request_factory=lambda tool_input: (
                build_external_directory_approval_request(
                    ctx,
                    tool_name="notebook_edit",
                    tool_input=tool_input,
                )
            ),
            approval_args_summary_factory=lambda tool_input: (
                build_external_directory_approval_args_summary(
                    ctx,
                    tool_name="notebook_edit",
                    tool_input=tool_input,
                )
            ),
        )
