# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Mapping

import httpx
import pytest

from agent_teams.computer import ComputerActionWait
from agent_teams.computer.executor_config import VmHttpExecutorConfig
from agent_teams.computer.vm_executor import VmComputerExecutor


class _FakeVmHttpClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, str, Mapping[str, str] | None, object | None]] = []

    async def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json: object | None = None,
    ) -> httpx.Response:
        self.calls.append(("POST", url, headers, json))
        return self._responses.pop(0)

    async def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        self.calls.append(("GET", url, headers, None))
        return self._responses.pop(0)

    async def delete(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        self.calls.append(("DELETE", url, headers, None))
        return self._responses.pop(0)


def _response(status_code: int, payload: object) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=payload,
        request=httpx.Request("POST", "https://vm.example/api/sessions"),
    )


@pytest.mark.asyncio
async def test_vm_executor_runs_full_session_flow() -> None:
    client = _FakeVmHttpClient(
        responses=[
            _response(200, {"session_id": "vm-session-1"}),
            _response(200, {"screen_width": 1440, "screen_height": 900}),
            _response(
                200,
                {
                    "image_base64": "aGVsbG8=",
                    "mime_type": "image/png",
                    "width": 1440,
                    "height": 900,
                },
            ),
            _response(200, {"ok": True, "action_type": "wait", "message": "done"}),
            _response(200, {"ok": True}),
        ]
    )
    executor = VmComputerExecutor(
        VmHttpExecutorConfig(
            base_url="https://vm.example/api",
            api_key="secret",
            ssl_verify=False,
            timeout_seconds=9.0,
        ),
        http_client=client,
    )

    session_id = await executor.start_session(run_id="run-1", instance_id="instance-1")
    context = await executor.get_context(session_id=session_id)
    screenshot = await executor.capture_screenshot(session_id=session_id)
    result = await executor.execute_action(
        session_id=session_id,
        action=ComputerActionWait(type="wait", seconds=1.0),
    )
    await executor.stop_session(session_id=session_id)

    assert session_id == "vm-session-1"
    assert context.screen_width == 1440
    assert screenshot.image_base64 == "aGVsbG8="
    assert result.ok is True
    assert client.calls[0][0] == "POST"
    assert client.calls[0][1] == "https://vm.example/api/sessions"
    assert client.calls[0][2] is not None
    assert client.calls[0][2]["Authorization"] == "Bearer secret"


@pytest.mark.asyncio
async def test_vm_executor_raises_runtime_error_for_http_failure() -> None:
    client = _FakeVmHttpClient(responses=[_response(500, {"error": "boom"})])
    executor = VmComputerExecutor(
        VmHttpExecutorConfig(base_url="https://vm.example/api"),
        http_client=client,
    )

    with pytest.raises(RuntimeError, match="status 500"):
        await executor.start_session(run_id="run-1", instance_id="instance-1")
