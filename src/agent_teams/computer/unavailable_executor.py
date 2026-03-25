# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import final

from agent_teams.computer.action_models import (
    ComputerAction,
    ComputerActionResult,
    ComputerContext,
    ComputerScreenshot,
)
from agent_teams.computer.executor_contracts import ComputerExecutor


@final
class UnavailableComputerExecutor(ComputerExecutor):
    def __init__(self, message: str | None = None) -> None:
        self._message = message or (
            "Computer executor is not configured. Please provide a VM or desktop "
            "executor before using the openai_responses_computer provider."
        )

    async def start_session(self, *, run_id: str, instance_id: str) -> str:
        raise RuntimeError(self._message)

    async def execute_action(
        self,
        *,
        session_id: str,
        action: ComputerAction,
    ) -> ComputerActionResult:
        raise RuntimeError(self._message)

    async def capture_screenshot(self, *, session_id: str) -> ComputerScreenshot:
        raise RuntimeError(self._message)

    async def get_context(self, *, session_id: str) -> ComputerContext:
        raise RuntimeError(self._message)

    async def stop_session(self, *, session_id: str) -> None:
        return None
