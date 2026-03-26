# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from agent_teams.env.runtime_env import load_merged_env_vars

_EXECUTOR_BACKEND_ENV = "AGENT_TEAMS_COMPUTER_EXECUTOR_BACKEND"
_VM_BASE_URL_ENV = "AGENT_TEAMS_COMPUTER_VM_BASE_URL"
_VM_API_KEY_ENV = "AGENT_TEAMS_COMPUTER_VM_API_KEY"
_VM_SSL_VERIFY_ENV = "AGENT_TEAMS_COMPUTER_VM_SSL_VERIFY"
_VM_TIMEOUT_ENV = "AGENT_TEAMS_COMPUTER_VM_TIMEOUT_SECONDS"


class ComputerExecutorBackend(StrEnum):
    UNAVAILABLE = "unavailable"
    VM_HTTP = "vm_http"


class VmHttpExecutorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: str = Field(min_length=1)
    api_key: str | None = None
    ssl_verify: bool | None = None
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)

    @field_validator("base_url", "api_key", mode="before")
    @classmethod
    def _normalize_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ComputerExecutorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    backend: ComputerExecutorBackend = ComputerExecutorBackend.UNAVAILABLE
    vm_http: VmHttpExecutorConfig | None = None

    @model_validator(mode="after")
    def _validate_backend_requirements(self) -> ComputerExecutorConfig:
        if self.backend == ComputerExecutorBackend.VM_HTTP and self.vm_http is None:
            raise ValueError("vm_http backend requires vm_http configuration.")
        return self


def load_computer_executor_config(
    *,
    config_dir: Path,
    merged_env: Mapping[str, str] | None = None,
) -> ComputerExecutorConfig:
    resolved_env = (
        load_merged_env_vars(extra_env_files=(config_dir / ".env",))
        if merged_env is None
        else dict(merged_env)
    )

    payload: dict[str, object] = {
        "backend": resolved_env.get(
            _EXECUTOR_BACKEND_ENV,
            ComputerExecutorBackend.UNAVAILABLE.value,
        ),
    }
    vm_http_payload: dict[str, object] = {}

    base_url = _normalized_env_value(resolved_env.get(_VM_BASE_URL_ENV))
    if base_url is not None:
        vm_http_payload["base_url"] = base_url

    api_key = _normalized_env_value(resolved_env.get(_VM_API_KEY_ENV))
    if api_key is not None:
        vm_http_payload["api_key"] = api_key

    ssl_verify = _parse_optional_bool(resolved_env.get(_VM_SSL_VERIFY_ENV))
    if ssl_verify is not None:
        vm_http_payload["ssl_verify"] = ssl_verify

    timeout_seconds = _parse_optional_float(resolved_env.get(_VM_TIMEOUT_ENV))
    if timeout_seconds is not None:
        vm_http_payload["timeout_seconds"] = timeout_seconds

    if vm_http_payload:
        payload["vm_http"] = vm_http_payload

    try:
        return ComputerExecutorConfig.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"Invalid computer executor configuration: {exc}") from exc


def _normalized_env_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized


def _parse_optional_bool(value: str | None) -> bool | None:
    normalized = _normalized_env_value(value)
    if normalized is None:
        return None
    lowered = normalized.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value for {_VM_SSL_VERIFY_ENV}: {value!r}")


def _parse_optional_float(value: str | None) -> float | None:
    normalized = _normalized_env_value(value)
    if normalized is None:
        return None
    try:
        return float(normalized)
    except ValueError as exc:
        raise ValueError(
            f"Invalid float value for {_VM_TIMEOUT_ENV}: {value!r}"
        ) from exc
