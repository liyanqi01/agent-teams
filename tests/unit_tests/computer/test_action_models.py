# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import cast

from pydantic import TypeAdapter

from agent_teams.computer import (
    ComputerAction,
    ComputerActionClick,
    ComputerActionDrag,
    ComputerExecutor,
    ComputerPoint,
    ComputerSessionRecord,
    MouseButton,
)


def test_computer_action_union_parses_click_payload() -> None:
    adapter = TypeAdapter(ComputerAction)

    action = adapter.validate_python(
        {
            "type": "click",
            "x": 12,
            "y": 34,
            "button": "right",
        }
    )

    assert isinstance(action, ComputerActionClick)
    assert action.button == MouseButton.RIGHT


def test_computer_action_drag_requires_at_least_two_points() -> None:
    try:
        ComputerActionDrag(path=(ComputerPoint(x=1, y=2),))
    except Exception as exc:
        assert "at least 2 items" in str(exc)
    else:  # pragma: no cover - defensive path
        raise AssertionError("Expected drag path validation to fail")


def test_computer_session_record_tracks_context_fields() -> None:
    record = ComputerSessionRecord(
        session_id="computer_session_1",
        run_id="run_1",
        instance_id="instance_1",
        status="running",
        current_url="https://openai.com",
        active_window_title="OpenAI",
    )

    assert record.current_url == "https://openai.com"
    assert record.active_window_title == "OpenAI"


def test_computer_package_exports_executor_protocol() -> None:
    executor = cast(type[object], ComputerExecutor)

    assert executor.__name__ == "ComputerExecutor"
