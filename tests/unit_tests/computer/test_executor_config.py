# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import pytest

from agent_teams.computer.executor_config import (
    ComputerExecutorBackend,
    load_computer_executor_config,
)


def test_load_computer_executor_config_defaults_to_unavailable(tmp_path: Path) -> None:
    config = load_computer_executor_config(config_dir=tmp_path, merged_env={})

    assert config.backend == ComputerExecutorBackend.UNAVAILABLE
    assert config.vm_http is None


def test_load_computer_executor_config_reads_vm_http_env(tmp_path: Path) -> None:
    config = load_computer_executor_config(
        config_dir=tmp_path,
        merged_env={
            "AGENT_TEAMS_COMPUTER_EXECUTOR_BACKEND": "vm_http",
            "AGENT_TEAMS_COMPUTER_VM_BASE_URL": " https://vm.example/api ",
            "AGENT_TEAMS_COMPUTER_VM_API_KEY": " secret ",
            "AGENT_TEAMS_COMPUTER_VM_SSL_VERIFY": "false",
            "AGENT_TEAMS_COMPUTER_VM_TIMEOUT_SECONDS": "12.5",
        },
    )

    assert config.backend == ComputerExecutorBackend.VM_HTTP
    assert config.vm_http is not None
    assert config.vm_http.base_url == "https://vm.example/api"
    assert config.vm_http.api_key == "secret"
    assert config.vm_http.ssl_verify is False
    assert config.vm_http.timeout_seconds == 12.5


def test_load_computer_executor_config_rejects_invalid_boolean(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Invalid boolean value"):
        load_computer_executor_config(
            config_dir=tmp_path,
            merged_env={
                "AGENT_TEAMS_COMPUTER_VM_SSL_VERIFY": "maybe",
            },
        )


def test_load_computer_executor_config_requires_vm_base_url(tmp_path: Path) -> None:
    with pytest.raises(
        ValueError, match="vm_http backend requires vm_http configuration"
    ):
        load_computer_executor_config(
            config_dir=tmp_path,
            merged_env={
                "AGENT_TEAMS_COMPUTER_EXECUTOR_BACKEND": "vm_http",
            },
        )
