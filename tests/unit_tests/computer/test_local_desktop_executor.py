# -*- coding: utf-8 -*-
from __future__ import annotations


import pytest

from agent_teams.computer import (
    ComputerActionWait,
    ComputerContext,
    ComputerScreenshot,
)
from agent_teams.computer.action_models import ComputerAction, ComputerActionResult
from agent_teams.computer.local_desktop_executor import LocalDesktopExecutor
import agent_teams.computer.local_desktop_executor as local_desktop_module


class _FakeLocalDesktopDriver:
    def __init__(self) -> None:
        self.start_calls: list[tuple[str, str]] = []
        self.execute_calls: list[tuple[str, str]] = []
        self.capture_calls: list[str] = []
        self.context_calls: list[str] = []
        self.stop_calls: list[str] = []

    def start_session(self, *, run_id: str, instance_id: str) -> str:
        self.start_calls.append((run_id, instance_id))
        return "local-session-1"

    def execute_action(
        self,
        *,
        session_id: str,
        action: ComputerAction,
    ) -> ComputerActionResult:
        self.execute_calls.append((session_id, action.type))
        return ComputerActionResult(ok=True, action_type=action.type, message="done")

    def capture_screenshot(self, *, session_id: str) -> ComputerScreenshot:
        self.capture_calls.append(session_id)
        return ComputerScreenshot(
            image_base64="aGVsbG8=",
            mime_type="image/png",
            width=1280,
            height=800,
        )

    def get_context(self, *, session_id: str) -> ComputerContext:
        self.context_calls.append(session_id)
        return ComputerContext(
            screen_width=1280,
            screen_height=800,
            current_url=None,
            active_window_title="Desktop",
        )

    def stop_session(self, *, session_id: str) -> None:
        self.stop_calls.append(session_id)


@pytest.mark.asyncio
async def test_local_desktop_executor_runs_full_session_flow() -> None:
    driver = _FakeLocalDesktopDriver()
    executor = LocalDesktopExecutor(driver=driver)

    session_id = await executor.start_session(run_id="run-1", instance_id="instance-1")
    context = await executor.get_context(session_id=session_id)
    screenshot = await executor.capture_screenshot(session_id=session_id)
    result = await executor.execute_action(
        session_id=session_id,
        action=ComputerActionWait(type="wait", seconds=0.1),
    )
    await executor.stop_session(session_id=session_id)

    assert session_id == "local-session-1"
    assert context.active_window_title == "Desktop"
    assert screenshot.width == 1280
    assert result.ok is True
    assert driver.start_calls == [("run-1", "instance-1")]
    assert driver.execute_calls == [("local-session-1", "wait")]
    assert driver.stop_calls == ["local-session-1"]


def test_local_desktop_executor_rejects_unsupported_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(local_desktop_module.platform, "system", lambda: "Linux")

    with pytest.raises(RuntimeError, match="Windows only"):
        LocalDesktopExecutor()
