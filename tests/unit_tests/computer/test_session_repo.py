# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from agent_teams.computer import (
    ComputerSessionRecord,
    ComputerSessionRepository,
    ComputerSessionStatus,
    ComputerTurnRecord,
    ComputerTurnStatus,
)


def test_computer_session_repository_persists_session_and_turns(tmp_path: Path) -> None:
    repo = ComputerSessionRepository(tmp_path / "computer_sessions.db")

    stored_session = repo.upsert_session(
        ComputerSessionRecord(
            computer_session_id="computer-session-1",
            session_id="session-1",
            run_id="run-1",
            task_id="task-1",
            instance_id="instance-1",
            role_id="desktop_operator",
            status=ComputerSessionStatus.ACTIVE,
            current_url="https://example.test/start",
            active_window_title="Start",
        )
    )
    stored_turn = repo.record_turn(
        ComputerTurnRecord(
            computer_session_id="computer-session-1",
            session_id="session-1",
            run_id="run-1",
            task_id="task-1",
            instance_id="instance-1",
            role_id="desktop_operator",
            step_index=0,
            response_id="resp-1",
            tool_call_id="call-1",
            action_type="click",
            action_json='{"type":"click","x":1,"y":2}',
            result_json='{"ok":true}',
            screenshot_artifact_path="computer/run-1/instance-1/step-0001.png",
            current_url="https://example.test/done",
            active_window_title="Done",
            status=ComputerTurnStatus.COMPLETED,
        )
    )
    completed_session = repo.upsert_session(
        stored_session.model_copy(
            update={
                "status": ComputerSessionStatus.COMPLETED,
                "current_url": "https://example.test/done",
                "active_window_title": "Done",
                "completed_at": stored_session.updated_at,
            }
        )
    )

    assert stored_turn.turn_id is not None
    assert repo.get_session("computer-session-1") == completed_session
    turns = repo.list_turns("computer-session-1")
    assert len(turns) == 1
    assert turns[0].tool_call_id == "call-1"
    assert (
        turns[0].screenshot_artifact_path == "computer/run-1/instance-1/step-0001.png"
    )
    assert repo.list_sessions_by_run("run-1") == (completed_session,)


def test_computer_session_repository_deletes_by_agent_session(tmp_path: Path) -> None:
    repo = ComputerSessionRepository(tmp_path / "computer_sessions.db")
    _ = repo.upsert_session(
        ComputerSessionRecord(
            computer_session_id="computer-session-1",
            session_id="session-1",
            run_id="run-1",
            task_id="task-1",
            instance_id="instance-1",
            role_id="desktop_operator",
        )
    )
    _ = repo.record_turn(
        ComputerTurnRecord(
            computer_session_id="computer-session-1",
            session_id="session-1",
            run_id="run-1",
            task_id="task-1",
            instance_id="instance-1",
            role_id="desktop_operator",
            step_index=0,
            action_type="click",
            action_json='{"type":"click"}',
        )
    )

    repo.delete_by_session("session-1")

    assert repo.get_session("computer-session-1") is None
    assert repo.list_turns("computer-session-1") == ()
