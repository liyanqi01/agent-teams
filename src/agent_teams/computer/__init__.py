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
        MouseButton,
    )
    from agent_teams.computer.executor_contracts import ComputerExecutor
    from agent_teams.computer.unavailable_executor import UnavailableComputerExecutor

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
    "ComputerContext",
    "ComputerExecutor",
    "UnavailableComputerExecutor",
    "ComputerPoint",
    "ComputerSafetyCheck",
    "ComputerScreenshot",
    "ComputerSessionRecord",
    "MouseButton",
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
    "ComputerContext": ("agent_teams.computer.action_models", "ComputerContext"),
    "ComputerExecutor": ("agent_teams.computer.executor_contracts", "ComputerExecutor"),
    "UnavailableComputerExecutor": (
        "agent_teams.computer.unavailable_executor",
        "UnavailableComputerExecutor",
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
    "MouseButton": ("agent_teams.computer.action_models", "MouseButton"),
}


def __getattr__(name: str) -> object:
    module_info = _LAZY_IMPORTS.get(name)
    if module_info is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = module_info
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)
