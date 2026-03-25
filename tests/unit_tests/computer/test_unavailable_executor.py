# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from agent_teams.computer import ComputerActionWait, UnavailableComputerExecutor


@pytest.mark.asyncio
async def test_unavailable_executor_raises_for_runtime_methods() -> None:
    executor = UnavailableComputerExecutor()

    with pytest.raises(RuntimeError, match="Computer executor is not configured"):
        await executor.start_session(run_id="run-1", instance_id="instance-1")

    with pytest.raises(RuntimeError, match="Computer executor is not configured"):
        await executor.execute_action(
            session_id="session-1",
            action=ComputerActionWait(type="wait", seconds=0.25),
        )

    with pytest.raises(RuntimeError, match="Computer executor is not configured"):
        await executor.capture_screenshot(session_id="session-1")

    with pytest.raises(RuntimeError, match="Computer executor is not configured"):
        await executor.get_context(session_id="session-1")


@pytest.mark.asyncio
async def test_unavailable_executor_stop_session_is_noop() -> None:
    executor = UnavailableComputerExecutor()

    await executor.stop_session(session_id="session-1")
