# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, final

from httpx import AsyncClient, HTTPStatusError, Response
from pydantic import BaseModel, ConfigDict, Field

from agent_teams.computer.action_models import (
    ComputerAction,
    ComputerActionResult,
    ComputerContext,
    ComputerScreenshot,
)
from agent_teams.computer.executor_config import VmHttpExecutorConfig
from agent_teams.computer.executor_contracts import ComputerExecutor
from agent_teams.logger import get_logger
from agent_teams.net.clients import create_async_http_client

logger = get_logger(__name__)


class _VmHttpClient(Protocol):
    async def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json: object | None = None,
    ) -> Response: ...

    async def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response: ...

    async def delete(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response: ...


class _VmSessionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_id: str = Field(min_length=1)


@final
class VmComputerExecutor(ComputerExecutor):
    def __init__(
        self,
        config: VmHttpExecutorConfig,
        *,
        http_client: _VmHttpClient | None = None,
    ) -> None:
        self._config = config
        self._http_client = http_client or self._build_http_client(config)

    async def start_session(self, *, run_id: str, instance_id: str) -> str:
        response = await self._request(
            "POST",
            "/sessions",
            json={
                "run_id": run_id,
                "instance_id": instance_id,
            },
        )
        payload = _VmSessionResponse.model_validate(response.json())
        return payload.session_id

    async def execute_action(
        self,
        *,
        session_id: str,
        action: ComputerAction,
    ) -> ComputerActionResult:
        response = await self._request(
            "POST",
            f"/sessions/{session_id}/actions",
            json=action.model_dump(mode="json"),
        )
        return ComputerActionResult.model_validate(response.json())

    async def capture_screenshot(self, *, session_id: str) -> ComputerScreenshot:
        response = await self._request("GET", f"/sessions/{session_id}/screenshot")
        return ComputerScreenshot.model_validate(response.json())

    async def get_context(self, *, session_id: str) -> ComputerContext:
        response = await self._request("GET", f"/sessions/{session_id}/context")
        return ComputerContext.model_validate(response.json())

    async def stop_session(self, *, session_id: str) -> None:
        try:
            _ = await self._request("DELETE", f"/sessions/{session_id}")
        except RuntimeError as exc:
            logger.warning(
                "Failed to stop VM computer session %s: %s",
                session_id,
                exc,
            )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: object | None = None,
    ) -> Response:
        url = self._url(path)
        headers = self._headers()
        try:
            if method == "POST":
                response = await self._http_client.post(url, headers=headers, json=json)
            elif method == "GET":
                response = await self._http_client.get(url, headers=headers)
            else:
                response = await self._http_client.delete(url, headers=headers)
            response.raise_for_status()
            return response
        except HTTPStatusError as exc:
            detail = exc.response.text.strip() if exc.response.text else str(exc)
            raise RuntimeError(
                "VM computer executor request failed with status "
                f"{exc.response.status_code}: {detail}"
            ) from exc

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._config.api_key is not None and self._config.api_key.strip():
            headers["Authorization"] = f"Bearer {self._config.api_key.strip()}"
        return headers

    def _url(self, path: str) -> str:
        return f"{self._config.base_url.rstrip('/')}/{path.lstrip('/')}"

    @staticmethod
    def _build_http_client(config: VmHttpExecutorConfig) -> AsyncClient:
        return create_async_http_client(
            ssl_verify=config.ssl_verify,
            timeout_seconds=config.timeout_seconds,
            follow_redirects=False,
        )
