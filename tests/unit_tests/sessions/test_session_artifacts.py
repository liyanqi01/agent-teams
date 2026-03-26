# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import pytest

from agent_teams.agents.execution.message_repository import MessageRepository
from agent_teams.agents.instances.instance_repository import AgentInstanceRepository
from agent_teams.agents.tasks.task_repository import TaskRepository
from agent_teams.providers.token_usage_repo import TokenUsageRepository
from agent_teams.sessions.runs.run_runtime_repo import RunRuntimeRepository
from agent_teams.sessions.session_repository import SessionRepository
from agent_teams.sessions.session_service import SessionService
from agent_teams.tools.runtime.approval_ticket_repo import ApprovalTicketRepository
from agent_teams.workspace import WorkspaceManager
from agent_teams.workspace.workspace_repository import WorkspaceRepository
from agent_teams.workspace.workspace_service import WorkspaceService


def _build_service(db_path: Path, project_root: Path) -> SessionService:
    workspace_repo = WorkspaceRepository(db_path)
    workspace_service = WorkspaceService(repository=workspace_repo)
    _ = workspace_service.create_workspace(
        workspace_id="default",
        root_path=project_root,
    )
    return SessionService(
        session_repo=SessionRepository(db_path),
        task_repo=TaskRepository(db_path),
        agent_repo=AgentInstanceRepository(db_path),
        message_repo=MessageRepository(db_path),
        approval_ticket_repo=ApprovalTicketRepository(db_path),
        run_runtime_repo=RunRuntimeRepository(db_path),
        token_usage_repo=TokenUsageRepository(db_path),
        workspace_manager=WorkspaceManager(
            project_root=project_root,
            workspace_repo=workspace_repo,
        ),
        workspace_service=workspace_service,
    )


def test_get_session_artifact_path_returns_session_scoped_artifact(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    service = _build_service(tmp_path / "session_artifacts.db", project_root)
    session = service.create_session(session_id="session-1", workspace_id="default")

    session_dir = project_root / ".agent_teams" / "sessions" / session.session_id
    artifact_path = session_dir / "computer" / "run-1" / "instance-1" / "step-0001.png"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(b"png-bytes")

    resolved = service.get_session_artifact_path(
        session.session_id,
        "computer/run-1/instance-1/step-0001.png",
    )

    assert resolved == artifact_path.resolve()


def test_get_session_artifact_path_rejects_escape_paths(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    service = _build_service(tmp_path / "session_artifacts.db", project_root)
    _ = service.create_session(session_id="session-1", workspace_id="default")

    with pytest.raises(ValueError, match="escapes the session scope"):
        service.get_session_artifact_path("session-1", "../outside.txt")


def test_get_session_artifact_path_rejects_missing_artifact(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    service = _build_service(tmp_path / "session_artifacts.db", project_root)
    _ = service.create_session(session_id="session-1", workspace_id="default")

    with pytest.raises(FileNotFoundError):
        service.get_session_artifact_path(
            "session-1",
            "computer/run-1/instance-1/missing.png",
        )
