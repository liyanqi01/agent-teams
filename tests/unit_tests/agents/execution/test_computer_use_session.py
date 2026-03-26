# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
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
    ComputerArtifactStore,
    ComputerContext,
    ComputerExecutor,
    ComputerScreenshot,
    ComputerSessionRepository,
    ComputerSessionStatus,
)
from agent_teams.notifications import NotificationService
from agent_teams.providers.model_config import ModelEndpointConfig, ProviderType
from agent_teams.providers.provider_contracts import LLMRequest
from agent_teams.sessions.runs.enums import RunEventType
from agent_teams.sessions.runs.event_stream import RunEventHub
from agent_teams.sessions.runs.run_control_manager import RunControlManager
from agent_teams.sessions.runs.run_models import RunEvent
from agent_teams.sessions.runs.run_runtime_repo import (
    RunRuntimePhase,
    RunRuntimeRecord,
    RunRuntimeRepository,
    RunRuntimeStatus,
)
from agent_teams.tools.runtime import ToolApprovalManager, ToolApprovalPolicy
from agent_teams.tools.runtime.approval_ticket_repo import (
    ApprovalTicketRepository,
    ApprovalTicketStatus,
)
from agent_teams.workspace import WorkspaceManager


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
        self.calls.append({"url": url, "headers": dict(headers), "json": json})
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


class _FakeNotificationService:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def emit(
        self,
        *,
        notification_type: object,
        title: str,
        body: str,
        context: object,
        dedupe_key: str | None = None,
    ) -> bool:
        self.requests.append(
            {
                "notification_type": notification_type,
                "title": title,
                "body": body,
                "context": context,
                "dedupe_key": dedupe_key,
            }
        )
        return True


class _FakeToolApprovalManager:
    def __init__(
        self,
        *,
        wait_result: tuple[str, str] = ("approve", ""),
        should_timeout: bool = False,
    ) -> None:
        self.wait_result = wait_result
        self.should_timeout = should_timeout
        self.last_open: dict[str, str] | None = None
        self.closed: list[tuple[str, str]] = []
        self._approvals: dict[str, dict[str, dict[str, str]]] = {}

    def open_approval(
        self,
        *,
        run_id: str,
        tool_call_id: str,
        instance_id: str,
        role_id: str,
        tool_name: str,
        args_preview: str,
        risk_level: str = "medium",
    ) -> None:
        entry = {
            "tool_call_id": tool_call_id,
            "instance_id": instance_id,
            "role_id": role_id,
            "tool_name": tool_name,
            "args_preview": args_preview,
            "risk_level": risk_level,
            "feedback": "",
        }
        self._approvals.setdefault(run_id, {})[tool_call_id] = entry
        self.last_open = entry

    def get_approval(self, *, run_id: str, tool_call_id: str) -> dict[str, str] | None:
        return self._approvals.get(run_id, {}).get(tool_call_id)

    def wait_for_approval(
        self,
        *,
        run_id: str,
        tool_call_id: str,
        timeout: float = 300.0,
    ) -> tuple[str, str]:
        _ = timeout
        if self.should_timeout:
            raise TimeoutError("timed out")
        return self.wait_result

    def close_approval(self, *, run_id: str, tool_call_id: str) -> None:
        self.closed.append((run_id, tool_call_id))
        run_approvals = self._approvals.get(run_id)
        if run_approvals is None:
            return
        run_approvals.pop(tool_call_id, None)


class _FakeRunRuntimeRepo:
    def __init__(self) -> None:
        self.records: dict[str, RunRuntimeRecord] = {}

    def ensure(
        self,
        *,
        run_id: str,
        session_id: str,
        root_task_id: str | None = None,
        status: RunRuntimeStatus = RunRuntimeStatus.QUEUED,
        phase: RunRuntimePhase = RunRuntimePhase.IDLE,
    ) -> RunRuntimeRecord:
        record = self.records.get(run_id)
        if record is not None:
            if root_task_id is not None and record.root_task_id is None:
                record = record.model_copy(update={"root_task_id": root_task_id})
                self.records[run_id] = record
            return record
        record = RunRuntimeRecord(
            run_id=run_id,
            session_id=session_id,
            root_task_id=root_task_id,
            status=status,
            phase=phase,
        )
        self.records[run_id] = record
        return record

    def update(self, run_id: str, **changes: object) -> RunRuntimeRecord:
        current = self.records[run_id]
        next_record = current.model_copy(update=changes)
        self.records[run_id] = next_record
        return next_record

    def get(self, run_id: str) -> RunRuntimeRecord | None:
        return self.records.get(run_id)


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


def _session(
    *,
    http_client: _FakeHttpClient,
    executor: _FakeComputerExecutor,
    message_repo: _FakeMessageRepository,
    hub: _FakeRunEventHub,
    control_manager: _FakeRunControlManager,
    approval_manager: _FakeToolApprovalManager,
    approval_ticket_repo: ApprovalTicketRepository,
    run_runtime_repo: _FakeRunRuntimeRepo,
    policy: ToolApprovalPolicy | None = None,
    artifact_store: ComputerArtifactStore | None = None,
    computer_session_repo: ComputerSessionRepository | None = None,
    notification_service: _FakeNotificationService | None = None,
) -> ComputerUseSession:
    return ComputerUseSession(
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
        approval_ticket_repo=approval_ticket_repo,
        tool_approval_manager=cast(ToolApprovalManager, approval_manager),
        tool_approval_policy=policy
        or ToolApprovalPolicy(
            timeout_seconds=0.01,
            approval_required_computer_actions=frozenset(),
        ),
        run_runtime_repo=cast(RunRuntimeRepository, run_runtime_repo),
        computer_artifact_store=artifact_store,
        computer_session_repo=computer_session_repo,
        notification_service=cast(NotificationService | None, notification_service),
        http_client=http_client,
    )


@pytest.mark.asyncio
async def test_computer_use_session_runs_loop_and_emits_events(
    tmp_path: Path,
) -> None:
    hub = _FakeRunEventHub()
    control_manager = _FakeRunControlManager()
    approval_manager = _FakeToolApprovalManager()
    executor = _FakeComputerExecutor()
    run_runtime_repo = _FakeRunRuntimeRepo()
    message_repo = _FakeMessageRepository(
        history=[ModelRequest(parts=[UserPromptPart(content="Open the settings app.")])]
    )
    artifact_store = ComputerArtifactStore(
        workspace_manager=WorkspaceManager(project_root=tmp_path)
    )
    computer_session_repo = ComputerSessionRepository(tmp_path / "computer_sessions.db")
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
    session = _session(
        http_client=http_client,
        executor=executor,
        message_repo=message_repo,
        hub=hub,
        control_manager=control_manager,
        approval_manager=approval_manager,
        approval_ticket_repo=ApprovalTicketRepository(tmp_path / "tickets.db"),
        run_runtime_repo=run_runtime_repo,
        artifact_store=artifact_store,
        computer_session_repo=computer_session_repo,
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
    screenshot_payload = tool_result_payload["result"]["data"]["screenshot"]
    artifact_path = screenshot_payload["artifact_path"]
    assert artifact_path == "computer/run-1/instance-1/step-0001.png"
    assert (
        screenshot_payload["artifact_url"]
        == "/api/sessions/session-1/artifacts/computer/run-1/instance-1/step-0001.png"
    )
    assert (
        tmp_path
        / ".agent_teams"
        / "sessions"
        / "session-1"
        / "computer"
        / "run-1"
        / "instance-1"
        / "step-0000.png"
    ).exists()
    assert (
        tmp_path
        / ".agent_teams"
        / "sessions"
        / "session-1"
        / "computer"
        / "run-1"
        / "instance-1"
        / "step-0001.png"
    ).exists()
    assert tool_result_payload["error"] is False
    computer_session = computer_session_repo.get_session("computer-session-1")
    assert computer_session is not None
    assert computer_session.status == ComputerSessionStatus.COMPLETED
    assert computer_session.current_url == "https://example.test/done"
    turns = computer_session_repo.list_turns("computer-session-1")
    assert len(turns) == 1
    assert turns[0].tool_call_id == "call-1"
    assert (
        turns[0].screenshot_artifact_path == "computer/run-1/instance-1/step-0001.png"
    )
    assert control_manager.calls


@pytest.mark.asyncio
async def test_computer_use_session_uses_tool_approval_for_safety_checks(
    tmp_path: Path,
) -> None:
    hub = _FakeRunEventHub()
    control_manager = _FakeRunControlManager()
    approval_manager = _FakeToolApprovalManager(wait_result=("approve", "looks good"))
    executor = _FakeComputerExecutor()
    run_runtime_repo = _FakeRunRuntimeRepo()
    message_repo = _FakeMessageRepository(
        history=[ModelRequest(parts=[UserPromptPart(content="Open the browser.")])]
    )
    ticket_repo = ApprovalTicketRepository(tmp_path / "tickets.db")
    computer_session_repo = ComputerSessionRepository(tmp_path / "computer_sessions.db")
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
            ),
            _response(
                {
                    "id": "resp-2",
                    "output_text": "Approved and completed.",
                }
            ),
        ]
    )
    session = _session(
        http_client=http_client,
        executor=executor,
        message_repo=message_repo,
        hub=hub,
        control_manager=control_manager,
        approval_manager=approval_manager,
        approval_ticket_repo=ticket_repo,
        run_runtime_repo=run_runtime_repo,
        computer_session_repo=computer_session_repo,
    )

    result = await session.run(_request(user_prompt=None))

    assert result == "Approved and completed."
    assert approval_manager.last_open is not None
    assert approval_manager.last_open["tool_name"] == "computer_use"
    assert "pending_safety_checks" in approval_manager.last_open["args_preview"]
    assert executor.execute_calls
    ticket = ticket_repo.get("call-1")
    assert ticket is not None
    assert ticket.status == ApprovalTicketStatus.COMPLETED
    runtime = run_runtime_repo.get("run-1")
    assert runtime is not None
    assert runtime.status == RunRuntimeStatus.RUNNING
    computer_session = computer_session_repo.get_session("computer-session-1")
    assert computer_session is not None
    assert computer_session.status == ComputerSessionStatus.COMPLETED

    event_types = [event.event_type for event in hub.events]
    assert event_types == [
        RunEventType.MODEL_STEP_STARTED,
        RunEventType.MODEL_STEP_FINISHED,
        RunEventType.TOOL_APPROVAL_REQUESTED,
        RunEventType.TOOL_APPROVAL_RESOLVED,
        RunEventType.TOOL_CALL,
        RunEventType.TOOL_RESULT,
        RunEventType.MODEL_STEP_STARTED,
        RunEventType.MODEL_STEP_FINISHED,
        RunEventType.TEXT_DELTA,
    ]
    resolved_payload = json.loads(hub.events[3].payload_json)
    assert resolved_payload["action"] == "approve"
    assert resolved_payload["feedback"] == "looks good"


@pytest.mark.asyncio
async def test_computer_use_session_stops_when_safety_check_is_denied(
    tmp_path: Path,
) -> None:
    hub = _FakeRunEventHub()
    control_manager = _FakeRunControlManager()
    approval_manager = _FakeToolApprovalManager(wait_result=("deny", "not safe"))
    executor = _FakeComputerExecutor()
    run_runtime_repo = _FakeRunRuntimeRepo()
    message_repo = _FakeMessageRepository(
        history=[ModelRequest(parts=[UserPromptPart(content="Open the browser.")])]
    )
    ticket_repo = ApprovalTicketRepository(tmp_path / "tickets.db")
    computer_session_repo = ComputerSessionRepository(tmp_path / "computer_sessions.db")
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
    session = _session(
        http_client=http_client,
        executor=executor,
        message_repo=message_repo,
        hub=hub,
        control_manager=control_manager,
        approval_manager=approval_manager,
        approval_ticket_repo=ticket_repo,
        run_runtime_repo=run_runtime_repo,
        computer_session_repo=computer_session_repo,
    )

    with pytest.raises(RuntimeError, match="denied by user"):
        await session.run(_request(user_prompt=None))

    assert executor.execute_calls == []
    assert executor.stop_calls == ["computer-session-1"]
    ticket = ticket_repo.get("call-1")
    assert ticket is not None
    assert ticket.status == ApprovalTicketStatus.DENIED
    runtime = run_runtime_repo.get("run-1")
    assert runtime is not None
    assert runtime.status == RunRuntimeStatus.PAUSED
    assert runtime.phase == RunRuntimePhase.AWAITING_TOOL_APPROVAL
    assert runtime.last_error == "Computer use safety check was denied by user."
    computer_session = computer_session_repo.get_session("computer-session-1")
    assert computer_session is not None
    assert computer_session.status == ComputerSessionStatus.FAILED
    assert (
        computer_session.last_error == "Computer use safety check was denied by user."
    )

    event_types = [event.event_type for event in hub.events]
    assert event_types == [
        RunEventType.MODEL_STEP_STARTED,
        RunEventType.MODEL_STEP_FINISHED,
        RunEventType.TOOL_APPROVAL_REQUESTED,
        RunEventType.TOOL_APPROVAL_RESOLVED,
    ]
    resolved_payload = json.loads(hub.events[3].payload_json)
    assert resolved_payload["action"] == "deny"
    assert resolved_payload["feedback"] == "not safe"


@pytest.mark.asyncio
async def test_computer_use_session_uses_policy_approval_for_clicks_and_emits_notification(
    tmp_path: Path,
) -> None:
    hub = _FakeRunEventHub()
    control_manager = _FakeRunControlManager()
    approval_manager = _FakeToolApprovalManager(wait_result=("approve", "policy ok"))
    notification_service = _FakeNotificationService()
    executor = _FakeComputerExecutor()
    run_runtime_repo = _FakeRunRuntimeRepo()
    message_repo = _FakeMessageRepository(
        history=[ModelRequest(parts=[UserPromptPart(content="Open the browser.")])]
    )
    ticket_repo = ApprovalTicketRepository(tmp_path / "tickets.db")
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
                            "pending_safety_checks": [],
                            "status": "in_progress",
                        }
                    ],
                }
            ),
            _response(
                {
                    "id": "resp-2",
                    "output_text": "Policy-approved desktop action completed.",
                }
            ),
        ]
    )
    session = _session(
        http_client=http_client,
        executor=executor,
        message_repo=message_repo,
        hub=hub,
        control_manager=control_manager,
        approval_manager=approval_manager,
        approval_ticket_repo=ticket_repo,
        run_runtime_repo=run_runtime_repo,
        policy=ToolApprovalPolicy(timeout_seconds=0.01),
        notification_service=notification_service,
    )

    result = await session.run(_request(user_prompt=None))

    assert result == "Policy-approved desktop action completed."
    assert approval_manager.last_open is not None
    assert '"approval_reason": "policy"' in approval_manager.last_open["args_preview"]
    assert notification_service.requests
    notification_payload = notification_service.requests[0]
    assert notification_payload["title"] == "Approval Required"
    assert "computer_use" in cast(str, notification_payload["body"])
    assert executor.execute_calls
