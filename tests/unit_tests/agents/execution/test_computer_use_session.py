# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
from pydantic_ai.messages import ModelRequest, UserPromptPart

from agent_teams.agents.execution.computer_use_session import ComputerUseSession
from agent_teams.agents.execution.message_repository import MessageRepository
from agent_teams.computer import (
    ComputerAction,
    ComputerActionClick,
    ComputerActionResult,
    ComputerContext,
    ComputerExecutor,
    ComputerScreenshot,
)
from agent_teams.providers.model_config import ModelEndpointConfig, ProviderType
from agent_teams.providers.provider_contracts import LLMRequest
from agent_teams.sessions.runs.enums import RunEventType
from agent_teams.sessions.runs.event_stream import RunEventHub
from agent_teams.sessions.runs.run_control_manager import RunControlManager
from agent_teams.sessions.runs.run_models import RunEvent


class _FakeHttpClient:
    def __init__(self, responses: Sequence[httpx.Response]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: object,
    ) -> httpx.Response:
        self.calls.append({"url": url, "headers": headers, "json": json})
        if not self._responses:
            raise AssertionError("No more fake responses are available.")
        return self._responses.pop(0)


class _FakeComputerExecutor(ComputerExecutor):
    def __init__(self) -> None:
        self.start_calls: list[tuple[str, str]] = []
        self.execute_calls: list[tuple[str, ComputerAction]] = []
        self.stop_calls: list[str] = []
        self._contexts = [
            ComputerContext(
                screen_width=1280,
                screen_height=720,
                current_url="https://example.test/start",
                active_window_title="Start",
            ),
            ComputerContext(
                screen_width=1280,
                screen_height=720,
                current_url="https://example.test/done",
                active_window_title="Done",
            ),
        ]
        self._screenshots = [
            ComputerScreenshot(
                image_base64="Zmlyc3Q=",
                mime_type="image/png",
                width=1280,
                height=720,
            ),
            ComputerScreenshot(
                image_base64="c2Vjb25k",
                mime_type="image/png",
                width=1280,
                height=720,
            ),
        ]
        self._context_index = 0
        self._screenshot_index = 0

    async def start_session(self, *, run_id: str, instance_id: str) -> str:
        self.start_calls.append((run_id, instance_id))
        return "computer-session-1"

    async def execute_action(
        self,
        *,
        session_id: str,
        action: ComputerAction,
    ) -> ComputerActionResult:
        self.execute_calls.append((session_id, action))
        return ComputerActionResult(ok=True, action_type=action.type, message="ok")

    async def capture_screenshot(self, *, session_id: str) -> ComputerScreenshot:
        index = min(self._screenshot_index, len(self._screenshots) - 1)
        self._screenshot_index += 1
        return self._screenshots[index]

    async def get_context(self, *, session_id: str) -> ComputerContext:
        index = min(self._context_index, len(self._contexts) - 1)
        self._context_index += 1
        return self._contexts[index]

    async def stop_session(self, *, session_id: str) -> None:
        self.stop_calls.append(session_id)


class _FakeMessageRepository:
    def __init__(self, history: Sequence[ModelRequest]) -> None:
        self._history = list(history)

    def get_history_for_conversation_task(
        self,
        conversation_id: str,
        task_id: str,
    ) -> list[ModelRequest]:
        return list(self._history)


class _FakeRunEventHub:
    def __init__(self) -> None:
        self.events: list[RunEvent] = []

    def publish(self, event: RunEvent) -> None:
        self.events.append(event)


class _FakeRunControlManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def raise_if_cancelled(self, *, run_id: str, instance_id: str) -> None:
        self.calls.append((run_id, instance_id))


def _request(*, user_prompt: str | None = None) -> LLMRequest:
    return LLMRequest(
        run_id="run-1",
        trace_id="trace-1",
        task_id="task-1",
        session_id="session-1",
        workspace_id="workspace-1",
        conversation_id="conversation-1",
        instance_id="instance-1",
        role_id="role-1",
        system_prompt="System instructions.",
        user_prompt=user_prompt,
    )


def _response(payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        status_code=200,
        json=payload,
        request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
    )


@pytest.mark.asyncio
async def test_computer_use_session_runs_loop_and_emits_events() -> None:
    hub = _FakeRunEventHub()
    control_manager = _FakeRunControlManager()
    executor = _FakeComputerExecutor()
    message_repo = _FakeMessageRepository(
        history=[ModelRequest(parts=[UserPromptPart(content="Open the settings app.")])]
    )
    http_client = _FakeHttpClient(
        responses=[
            _response(
                {
                    "id": "resp-1",
                    "output": [
                        {
                            "type": "computer_call",
                            "id": "item-1",
                            "call_id": "call-1",
                            "action": {
                                "type": "click",
                                "x": 48,
                                "y": 96,
                                "button": "left",
                            },
                            "pending_safety_checks": [],
                            "status": "completed",
                        }
                    ],
                    "output_text": "",
                }
            ),
            _response(
                {
                    "id": "resp-2",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "Finished desktop task.",
                                }
                            ],
                        }
                    ],
                    "output_text": "Finished desktop task.",
                }
            ),
        ]
    )
    session = ComputerUseSession(
        ModelEndpointConfig(
            provider=ProviderType.OPENAI_RESPONSES_COMPUTER,
            model="computer-use-preview",
            base_url="https://api.openai.com/v1",
            api_key="secret-key",
        ),
        computer_executor=executor,
        message_repo=cast(MessageRepository, message_repo),
        run_event_hub=cast(RunEventHub, hub),
        run_control_manager=cast(RunControlManager, control_manager),
        http_client=http_client,
    )

    result = await session.run(_request(user_prompt=None))

    assert result == "Finished desktop task."
    assert executor.start_calls == [("run-1", "instance-1")]
    assert executor.stop_calls == ["computer-session-1"]
    assert len(executor.execute_calls) == 1
    _, action = executor.execute_calls[0]
    assert isinstance(action, ComputerActionClick)
    assert action.x == 48
    assert len(http_client.calls) == 2

    initial_payload = cast(dict[str, object], http_client.calls[0]["json"])
    initial_tools = cast(list[dict[str, object]], initial_payload["tools"])
    initial_input = cast(list[dict[str, object]], initial_payload["input"])
    initial_content = cast(list[dict[str, object]], initial_input[0]["content"])
    assert initial_tools[0]["type"] == "computer_use_preview"
    assert initial_tools[0]["environment"] == "windows"
    assert initial_content[0]["text"] == "Open the settings app."
    assert str(initial_content[1]["image_url"]).startswith("data:image/png;base64,")

    follow_up_payload = cast(dict[str, object], http_client.calls[1]["json"])
    follow_up_input = cast(list[dict[str, object]], follow_up_payload["input"])
    follow_up_output = cast(dict[str, object], follow_up_input[0]["output"])
    assert follow_up_payload["previous_response_id"] == "resp-1"
    assert follow_up_output["type"] == "computer_screenshot"
    assert follow_up_input[0]["current_url"] == "https://example.test/done"

    event_types = [event.event_type for event in hub.events]
    assert event_types == [
        RunEventType.MODEL_STEP_STARTED,
        RunEventType.MODEL_STEP_FINISHED,
        RunEventType.TOOL_CALL,
        RunEventType.TOOL_RESULT,
        RunEventType.MODEL_STEP_STARTED,
        RunEventType.MODEL_STEP_FINISHED,
        RunEventType.TEXT_DELTA,
    ]
    tool_call_payload = json.loads(hub.events[2].payload_json)
    assert tool_call_payload["tool_name"] == "computer_use"
    assert tool_call_payload["args"]["action"]["type"] == "click"
    tool_result_payload = json.loads(hub.events[3].payload_json)
    assert (
        tool_result_payload["result"]["data"]["current_url"]
        == "https://example.test/done"
    )
    assert tool_result_payload["error"] is False
    assert control_manager.calls


@pytest.mark.asyncio
async def test_computer_use_session_blocks_on_pending_safety_checks() -> None:
    hub = _FakeRunEventHub()
    control_manager = _FakeRunControlManager()
    executor = _FakeComputerExecutor()
    message_repo = _FakeMessageRepository(
        history=[ModelRequest(parts=[UserPromptPart(content="Open the browser.")])]
    )
    http_client = _FakeHttpClient(
        responses=[
            _response(
                {
                    "id": "resp-1",
                    "output": [
                        {
                            "type": "computer_call",
                            "id": "item-1",
                            "call_id": "call-1",
                            "action": {
                                "type": "click",
                                "x": 100,
                                "y": 200,
                                "button": "left",
                            },
                            "pending_safety_checks": [
                                {
                                    "id": "safety-1",
                                    "code": "requires_confirmation",
                                    "message": "Confirm desktop action.",
                                }
                            ],
                            "status": "in_progress",
                        }
                    ],
                }
            )
        ]
    )
    session = ComputerUseSession(
        ModelEndpointConfig(
            provider=ProviderType.OPENAI_RESPONSES_COMPUTER,
            model="computer-use-preview",
            base_url="https://api.openai.com/v1",
            api_key="secret-key",
        ),
        computer_executor=executor,
        message_repo=cast(MessageRepository, message_repo),
        run_event_hub=cast(RunEventHub, hub),
        run_control_manager=cast(RunControlManager, control_manager),
        http_client=http_client,
    )

    with pytest.raises(RuntimeError, match="pending safety checks"):
        await session.run(_request(user_prompt=None))

    assert executor.execute_calls == []
    assert executor.stop_calls == ["computer-session-1"]
    event_types = [event.event_type for event in hub.events]
    assert event_types == [
        RunEventType.MODEL_STEP_STARTED,
        RunEventType.MODEL_STEP_FINISHED,
        RunEventType.AWAITING_MANUAL_ACTION,
    ]
    awaiting_payload = json.loads(hub.events[2].payload_json)
    assert awaiting_payload["pending_safety_checks"][0]["id"] == "safety-1"
