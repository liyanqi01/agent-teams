# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Protocol

from agent_teams.computer.action_models import (
    ComputerAction,
    ComputerActionResult,
    ComputerContext,
    ComputerScreenshot,
)


class ComputerExecutor(Protocol):
    async def start_session(self, *, run_id: str, instance_id: str) -> str: ...

    async def execute_action(
        self,
        *,
        session_id: str,
        action: ComputerAction,
    ) -> ComputerActionResult: ...

    async def capture_screenshot(
        self,
        *,
        session_id: str,
    ) -> ComputerScreenshot: ...

    async def get_context(self, *, session_id: str) -> ComputerContext: ...

    async def stop_session(self, *, session_id: str) -> None: ...
