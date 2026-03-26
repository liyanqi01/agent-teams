# -*- coding: utf-8 -*-
from __future__ import annotations

import agent_teams.interfaces.server.container as container_module
from agent_teams.computer import (
    ComputerExecutorBackend,
    ComputerExecutorConfig,
    LocalDesktopExecutorConfig,
)
from agent_teams.interfaces.server.container import ServerContainer


def test_build_computer_executor_returns_local_desktop_executor(
    monkeypatch,
) -> None:
    sentinel = object()
    monkeypatch.setattr(container_module, "LocalDesktopExecutor", lambda: sentinel)
    server_container = ServerContainer.__new__(ServerContainer)
    server_container.computer_executor_config = ComputerExecutorConfig(
        backend=ComputerExecutorBackend.LOCAL_DESKTOP,
        local_desktop=LocalDesktopExecutorConfig(),
    )

    executor = ServerContainer._build_computer_executor(server_container)

    assert executor is sentinel
