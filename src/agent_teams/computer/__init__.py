# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_teams.computer.action_models import (
        ComputerAction,
        ComputerActionClick,
        ComputerActionDoubleClick,
        ComputerActionDrag,
        ComputerActionKeypress,
        ComputerActionResult,
        ComputerActionScreenshot,
        ComputerActionScroll,
        ComputerActionType,
        ComputerActionWait,
        ComputerContext,
        ComputerPoint,
        ComputerSafetyCheck,
        ComputerScreenshot,
        ComputerSessionRecord,
        ComputerSessionStatus,
        ComputerTurnRecord,
        ComputerTurnStatus,
        MouseButton,
    )
    from agent_teams.computer.artifact_store import ComputerArtifactStore
    from agent_teams.computer.executor_config import (
        ComputerExecutorBackend,
        ComputerExecutorConfig,
        LocalDesktopExecutorConfig,
        VmHttpExecutorConfig,
    )
    from agent_teams.computer.executor_contracts import ComputerExecutor
    from agent_teams.computer.local_desktop_executor import LocalDesktopExecutor
    from agent_teams.computer.session_repo import ComputerSessionRepository
    from agent_teams.computer.unavailable_executor import UnavailableComputerExecutor
    from agent_teams.computer.vm_executor import VmComputerExecutor

__all__ = [
    "ComputerAction",
    "ComputerActionClick",
    "ComputerActionDoubleClick",
    "ComputerActionDrag",
    "ComputerActionKeypress",
    "ComputerActionResult",
    "ComputerActionScreenshot",
    "ComputerActionScroll",
    "ComputerActionType",
    "ComputerActionWait",
    "ComputerArtifactStore",
    "ComputerContext",
    "ComputerExecutor",
    "ComputerExecutorBackend",
    "ComputerExecutorConfig",
    "ComputerPoint",
    "ComputerSafetyCheck",
    "ComputerScreenshot",
    "ComputerSessionRecord",
    "ComputerSessionRepository",
    "ComputerSessionStatus",
    "ComputerTurnRecord",
    "ComputerTurnStatus",
    "LocalDesktopExecutor",
    "LocalDesktopExecutorConfig",
    "MouseButton",
    "UnavailableComputerExecutor",
    "VmComputerExecutor",
    "VmHttpExecutorConfig",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "ComputerAction": ("agent_teams.computer.action_models", "ComputerAction"),
    "ComputerActionClick": (
        "agent_teams.computer.action_models",
        "ComputerActionClick",
    ),
    "ComputerActionDoubleClick": (
        "agent_teams.computer.action_models",
        "ComputerActionDoubleClick",
    ),
    "ComputerActionDrag": ("agent_teams.computer.action_models", "ComputerActionDrag"),
    "ComputerActionKeypress": (
        "agent_teams.computer.action_models",
        "ComputerActionKeypress",
    ),
    "ComputerActionResult": (
        "agent_teams.computer.action_models",
        "ComputerActionResult",
    ),
    "ComputerActionScreenshot": (
        "agent_teams.computer.action_models",
        "ComputerActionScreenshot",
    ),
    "ComputerActionScroll": (
        "agent_teams.computer.action_models",
        "ComputerActionScroll",
    ),
    "ComputerActionType": ("agent_teams.computer.action_models", "ComputerActionType"),
    "ComputerActionWait": ("agent_teams.computer.action_models", "ComputerActionWait"),
    "ComputerArtifactStore": (
        "agent_teams.computer.artifact_store",
        "ComputerArtifactStore",
    ),
    "ComputerContext": ("agent_teams.computer.action_models", "ComputerContext"),
    "ComputerExecutor": ("agent_teams.computer.executor_contracts", "ComputerExecutor"),
    "ComputerExecutorBackend": (
        "agent_teams.computer.executor_config",
        "ComputerExecutorBackend",
    ),
    "ComputerExecutorConfig": (
        "agent_teams.computer.executor_config",
        "ComputerExecutorConfig",
    ),
    "ComputerPoint": ("agent_teams.computer.action_models", "ComputerPoint"),
    "ComputerSafetyCheck": (
        "agent_teams.computer.action_models",
        "ComputerSafetyCheck",
    ),
    "ComputerScreenshot": ("agent_teams.computer.action_models", "ComputerScreenshot"),
    "ComputerSessionRecord": (
        "agent_teams.computer.action_models",
        "ComputerSessionRecord",
    ),
    "ComputerSessionRepository": (
        "agent_teams.computer.session_repo",
        "ComputerSessionRepository",
    ),
    "ComputerSessionStatus": (
        "agent_teams.computer.action_models",
        "ComputerSessionStatus",
    ),
    "ComputerTurnRecord": (
        "agent_teams.computer.action_models",
        "ComputerTurnRecord",
    ),
    "ComputerTurnStatus": (
        "agent_teams.computer.action_models",
        "ComputerTurnStatus",
    ),
    "LocalDesktopExecutor": (
        "agent_teams.computer.local_desktop_executor",
        "LocalDesktopExecutor",
    ),
    "LocalDesktopExecutorConfig": (
        "agent_teams.computer.executor_config",
        "LocalDesktopExecutorConfig",
    ),
    "MouseButton": ("agent_teams.computer.action_models", "MouseButton"),
    "UnavailableComputerExecutor": (
        "agent_teams.computer.unavailable_executor",
        "UnavailableComputerExecutor",
    ),
    "VmComputerExecutor": ("agent_teams.computer.vm_executor", "VmComputerExecutor"),
    "VmHttpExecutorConfig": (
        "agent_teams.computer.executor_config",
        "VmHttpExecutorConfig",
    ),
}


def __getattr__(name: str) -> object:
    module_info = _LAZY_IMPORTS.get(name)
    if module_info is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = module_info
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)
