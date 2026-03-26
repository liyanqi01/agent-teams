# -*- coding: utf-8 -*-
from __future__ import annotations

from importlib import import_module


def test_computer_package_exports_action_models_lazily() -> None:
    module = import_module("agent_teams.computer")

    exported = getattr(module, "ComputerActionClick", None)
    assert exported is not None


def test_computer_package_exports_unavailable_executor_lazily() -> None:
    module = import_module("agent_teams.computer")

    exported = getattr(module, "UnavailableComputerExecutor", None)
    assert exported is not None


def test_computer_package_exports_vm_executor_lazily() -> None:
    module = import_module("agent_teams.computer")

    exported = getattr(module, "VmComputerExecutor", None)
    assert exported is not None


def test_computer_package_exports_executor_config_lazily() -> None:
    module = import_module("agent_teams.computer")

    exported = getattr(module, "ComputerExecutorConfig", None)
    assert exported is not None


def test_computer_package_exports_artifact_store_lazily() -> None:
    module = import_module("agent_teams.computer")

    exported = getattr(module, "ComputerArtifactStore", None)
    assert exported is not None
