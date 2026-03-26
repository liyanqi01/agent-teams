# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Protocol, cast

from httpx import HTTPStatusError, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart

from agent_teams.agents.execution.message_repository import MessageRepository
from agent_teams.computer import (
    ComputerAction,
    ComputerActionResult,
    ComputerArtifactStore,
    ComputerContext,
    ComputerExecutor,
    ComputerScreenshot,
)
from agent_teams.net.llm_client import build_llm_http_client
from agent_teams.notifications import (
    NotificationContext,
    NotificationService,
    NotificationType,
)
from agent_teams.providers.model_config import ComputerUseConfig, ModelEndpointConfig
from agent_teams.providers.provider_contracts import LLMRequest
from agent_teams.sessions.runs.enums import RunEventType
from agent_teams.sessions.runs.event_stream import RunEventHub
from agent_teams.sessions.runs.run_control_manager import RunControlManager
from agent_teams.sessions.runs.run_models import RunEvent
from agent_teams.sessions.runs.run_runtime_repo import (
    RunRuntimePhase,
    RunRuntimeRepository,
    RunRuntimeStatus,
)
from agent_teams.tools.runtime import ToolApprovalManager, ToolApprovalPolicy
from agent_teams.tools.runtime.approval_ticket_repo import (
    ApprovalTicketRepository,
    ApprovalTicketStatus,
)
from agent_teams.workspace import build_conversation_id

_COMPUTER_TOOL_NAME = "computer_use"
_RESPONSES_PATH = "/responses"
_VALID_ENVIRONMENTS = frozenset(("windows", "mac", "linux", "ubuntu", "browser"))
_ENVIRONMENT_ALIASES = {
    "computer": "windows",
    "desktop": "windows",
}


class _AsyncHttpClient(Protocol):
    async def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: object,
    ) -> Response: ...


class _ResponsesUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class _ResponsesOutputItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str = Field(min_length=1)


class _ResponsesPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    output: tuple[_ResponsesOutputItem, ...] = ()
    output_text: str = ""
    usage: _ResponsesUsage | None = None


class _ResponsesMessageText(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str = Field(min_length=1)
    text: str = ""


class _ResponsesMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str = Field(default="message")
    content: tuple[_ResponsesMessageText, ...] = ()


class _ResponsesPendingSafetyCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    code: str | None = None
    message: str | None = None


class _ResponsesComputerCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str = Field(default="computer_call")
    id: str | None = None
    call_id: str = Field(min_length=1)
    action: ComputerAction | None = None
    pending_safety_checks: tuple[_ResponsesPendingSafetyCheck, ...] = ()
    status: str | None = None


class _RuntimeSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: RunRuntimeStatus
    phase: RunRuntimePhase
    active_instance_id: str | None = None
    active_task_id: str | None = None
    active_role_id: str | None = None
    active_subagent_instance_id: str | None = None


class ComputerUseSession:
    def __init__(
        self,
        config: ModelEndpointConfig,
        *,
        computer_executor: ComputerExecutor,
        message_repo: MessageRepository,
        run_event_hub: RunEventHub,
        run_control_manager: RunControlManager,
        approval_ticket_repo: ApprovalTicketRepository,
        tool_approval_manager: ToolApprovalManager,
        tool_approval_policy: ToolApprovalPolicy,
        run_runtime_repo: RunRuntimeRepository,
        computer_artifact_store: ComputerArtifactStore | None = None,
        notification_service: NotificationService | None = None,
        http_client: _AsyncHttpClient | None = None,
    ) -> None:
        self._config = config
        self._computer_config = config.computer_use or ComputerUseConfig()
        self._computer_executor = computer_executor
        self._message_repo = message_repo
        self._run_event_hub = run_event_hub
        self._run_control_manager = run_control_manager
        self._approval_ticket_repo = approval_ticket_repo
        self._tool_approval_manager = tool_approval_manager
        self._tool_approval_policy = tool_approval_policy
        self._run_runtime_repo = run_runtime_repo
        self._computer_artifact_store = computer_artifact_store
        self._notification_service = notification_service
        self._http_client: _AsyncHttpClient = http_client or build_llm_http_client(
            ssl_verify=config.ssl_verify,
            connect_timeout_seconds=config.connect_timeout_seconds,
        )

    async def run(self, request: LLMRequest) -> str:
        conversation_id = request.conversation_id or build_conversation_id(
            request.session_id,
            request.role_id,
        )
        prompt = self._resolve_prompt(request=request, conversation_id=conversation_id)
        self._raise_if_cancelled(request)
        session_id = await self._computer_executor.start_session(
            run_id=request.run_id,
            instance_id=request.instance_id,
        )
        try:
            step_index = 0
            context = await self._computer_executor.get_context(session_id=session_id)
            screenshot = await self._computer_executor.capture_screenshot(
                session_id=session_id
            )
            _, _ = self._store_screenshot(
                request=request,
                screenshot=screenshot,
                step_index=step_index,
            )
            step_index += 1
            response = await self._create_initial_response(
                request=request,
                prompt=prompt,
                screenshot=screenshot,
                context=context,
            )
            while True:
                self._raise_if_cancelled(request)
                computer_call = self._extract_first_computer_call(response)
                if computer_call is None:
                    text = self._extract_output_text(response)
                    if text:
                        self._publish_text_delta_event(request=request, text=text)
                    return text
                action = self._require_action(computer_call)
                approval_ticket_id: str | None = None
                if self._tool_approval_policy.requires_computer_action_approval(
                    action.type,
                    has_pending_safety_checks=bool(computer_call.pending_safety_checks),
                ):
                    approval_ticket_id = await self._await_computer_action_approval(
                        request=request,
                        computer_call=computer_call,
                        action=action,
                    )
                self._publish_tool_call_event(
                    request=request,
                    computer_call=computer_call,
                    action=action,
                )
                action_result = await self._computer_executor.execute_action(
                    session_id=session_id,
                    action=action,
                )
                context = await self._computer_executor.get_context(
                    session_id=session_id
                )
                screenshot = await self._computer_executor.capture_screenshot(
                    session_id=session_id
                )
                (
                    screenshot_artifact_path,
                    screenshot_artifact_url,
                ) = self._store_screenshot(
                    request=request,
                    screenshot=screenshot,
                    step_index=step_index,
                )
                step_index += 1
                self._publish_tool_result_event(
                    request=request,
                    computer_call=computer_call,
                    action_result=action_result,
                    screenshot=screenshot,
                    context=context,
                    screenshot_artifact_path=screenshot_artifact_path,
                    screenshot_artifact_url=screenshot_artifact_url,
                )
                if approval_ticket_id is not None:
                    self._approval_ticket_repo.mark_completed(approval_ticket_id)
                response = await self._create_follow_up_response(
                    request=request,
                    previous_response_id=response.id,
                    computer_call=computer_call,
                    screenshot=screenshot,
                    context=context,
                )
        finally:
            await self._computer_executor.stop_session(session_id=session_id)

    async def _await_computer_action_approval(
        self,
        *,
        request: LLMRequest,
        computer_call: _ResponsesComputerCall,
        action: ComputerAction,
    ) -> str:
        args_preview = self._approval_args_preview(
            computer_call=computer_call,
            action=action,
        )
        ticket = self._approval_ticket_repo.upsert_requested(
            tool_call_id=computer_call.call_id,
            run_id=request.run_id,
            session_id=request.session_id,
            task_id=request.task_id,
            instance_id=request.instance_id,
            role_id=request.role_id,
            tool_name=_COMPUTER_TOOL_NAME,
            args_preview=args_preview,
        )
        publish_request = False
        existing_approval = self._tool_approval_manager.get_approval(
            run_id=request.run_id,
            tool_call_id=ticket.tool_call_id,
        )
        if existing_approval is None:
            self._tool_approval_manager.open_approval(
                run_id=request.run_id,
                tool_call_id=ticket.tool_call_id,
                instance_id=request.instance_id,
                role_id=request.role_id,
                tool_name=_COMPUTER_TOOL_NAME,
                args_preview=args_preview,
                risk_level=self._tool_approval_policy.computer_action_risk_level(
                    action.type,
                    has_pending_safety_checks=bool(computer_call.pending_safety_checks),
                ),
            )
            publish_request = True
        runtime_snapshot = self._pause_for_tool_approval(request)
        if publish_request:
            self._publish_tool_approval_requested_event(
                request=request,
                tool_call_id=ticket.tool_call_id,
                args_preview=args_preview,
            )
            self._publish_tool_approval_notification(
                request=request,
                tool_call_id=ticket.tool_call_id,
            )
        try:
            action_decision, feedback = await asyncio.to_thread(
                self._tool_approval_manager.wait_for_approval,
                run_id=request.run_id,
                tool_call_id=ticket.tool_call_id,
                timeout=self._tool_approval_policy.timeout_seconds,
            )
        except TimeoutError as exc:
            self._tool_approval_manager.close_approval(
                run_id=request.run_id,
                tool_call_id=ticket.tool_call_id,
            )
            self._approval_ticket_repo.resolve(
                tool_call_id=ticket.tool_call_id,
                status=ApprovalTicketStatus.TIMED_OUT,
            )
            self._update_runtime_after_approval_error(
                request=request,
                message="Computer use safety check timed out.",
            )
            self._publish_tool_approval_resolved_event(
                request=request,
                tool_call_id=ticket.tool_call_id,
                action="timeout",
                feedback="",
            )
            raise RuntimeError("Computer use safety check timed out.") from exc

        self._tool_approval_manager.close_approval(
            run_id=request.run_id,
            tool_call_id=ticket.tool_call_id,
        )
        resolved_status = (
            ApprovalTicketStatus.APPROVED
            if action_decision == "approve"
            else ApprovalTicketStatus.DENIED
        )
        self._approval_ticket_repo.resolve(
            tool_call_id=ticket.tool_call_id,
            status=resolved_status,
            feedback=feedback,
        )
        self._publish_tool_approval_resolved_event(
            request=request,
            tool_call_id=ticket.tool_call_id,
            action=action_decision,
            feedback=feedback,
        )
        if action_decision == "deny":
            self._update_runtime_after_approval_error(
                request=request,
                message="Computer use safety check was denied by user.",
            )
            raise RuntimeError("Computer use safety check was denied by user.")
        self._restore_runtime_after_approval(
            request=request,
            snapshot=runtime_snapshot,
        )
        return ticket.tool_call_id

    async def _create_initial_response(
        self,
        *,
        request: LLMRequest,
        prompt: str,
        screenshot: ComputerScreenshot,
        context: ComputerContext,
    ) -> _ResponsesPayload:
        payload: dict[str, object] = {
            "model": self._config.model,
            "instructions": request.system_prompt,
            "tools": [self._tool_payload(context=context)],
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt,
                        },
                        {
                            "type": "input_image",
                            "image_url": self._image_data_url(screenshot),
                        },
                    ],
                }
            ],
            "truncation": self._computer_config.truncation,
        }
        self._apply_reasoning_payload(payload)
        return await self._post_response(request=request, payload=payload)

    async def _create_follow_up_response(
        self,
        *,
        request: LLMRequest,
        previous_response_id: str,
        computer_call: _ResponsesComputerCall,
        screenshot: ComputerScreenshot,
        context: ComputerContext,
    ) -> _ResponsesPayload:
        computer_call_output: dict[str, object] = {
            "type": "computer_call_output",
            "call_id": computer_call.call_id,
            "acknowledged_safety_checks": [],
            "output": {
                "type": "computer_screenshot",
                "image_url": self._image_data_url(screenshot),
            },
        }
        if context.current_url is not None and context.current_url.strip():
            computer_call_output["current_url"] = context.current_url.strip()
        payload: dict[str, object] = {
            "model": self._config.model,
            "instructions": request.system_prompt,
            "previous_response_id": previous_response_id,
            "tools": [self._tool_payload(context=context)],
            "input": [computer_call_output],
            "truncation": self._computer_config.truncation,
        }
        self._apply_reasoning_payload(payload)
        return await self._post_response(request=request, payload=payload)

    async def _post_response(
        self,
        *,
        request: LLMRequest,
        payload: dict[str, object],
    ) -> _ResponsesPayload:
        self._publish_model_step_event(
            request=request,
            event_type=RunEventType.MODEL_STEP_STARTED,
            payload={
                "role_id": request.role_id,
                "instance_id": request.instance_id,
                "provider": self._config.provider.value,
            },
        )
        try:
            response = await self._http_client.post(
                self._responses_url(),
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
        except HTTPStatusError as exc:
            detail = exc.response.text.strip() if exc.response.text else str(exc)
            raise RuntimeError(
                f"Computer use request failed with status {exc.response.status_code}: {detail}"
            ) from exc
        parsed = _ResponsesPayload.model_validate(response.json())
        self._publish_model_step_event(
            request=request,
            event_type=RunEventType.MODEL_STEP_FINISHED,
            payload={
                "role_id": request.role_id,
                "instance_id": request.instance_id,
                "response_id": parsed.id,
            },
        )
        return parsed

    def _resolve_prompt(self, *, request: LLMRequest, conversation_id: str) -> str:
        prompt = str(request.user_prompt or "").strip()
        if prompt:
            return prompt
        history = cast(
            Sequence[ModelRequest | ModelResponse],
            self._message_repo.get_history_for_conversation_task(
                conversation_id,
                request.task_id,
            ),
        )
        latest_prompt = self._latest_user_prompt(history)
        if latest_prompt:
            return latest_prompt
        fallback = request.system_prompt.strip()
        if fallback:
            return fallback
        raise RuntimeError("Computer use request requires a non-empty prompt.")

    def _latest_user_prompt(
        self,
        history: Sequence[ModelRequest | ModelResponse],
    ) -> str | None:
        for message in reversed(history):
            if not isinstance(message, ModelRequest):
                continue
            for part in message.parts:
                if isinstance(part, UserPromptPart):
                    content = str(part.content).strip()
                    if content:
                        return content
        return None

    def _extract_first_computer_call(
        self,
        response: _ResponsesPayload,
    ) -> _ResponsesComputerCall | None:
        for item in response.output:
            if item.type != "computer_call":
                continue
            try:
                return _ResponsesComputerCall.model_validate(
                    item.model_dump(mode="json")
                )
            except ValidationError as exc:
                raise RuntimeError(
                    "Computer use returned an unsupported computer_call payload."
                ) from exc
        return None

    def _require_action(self, computer_call: _ResponsesComputerCall) -> ComputerAction:
        if computer_call.action is None:
            raise RuntimeError(
                "Computer use returned a computer_call without an action payload."
            )
        return computer_call.action

    def _extract_output_text(self, response: _ResponsesPayload) -> str:
        if response.output_text.strip():
            return response.output_text.strip()
        parts: list[str] = []
        for item in response.output:
            if item.type != "message":
                continue
            message = _ResponsesMessage.model_validate(item.model_dump(mode="json"))
            for content in message.content:
                if content.type == "output_text" and content.text.strip():
                    parts.append(content.text.strip())
        return "\n".join(parts).strip()

    def _tool_payload(self, *, context: ComputerContext) -> dict[str, object]:
        return {
            "type": "computer_use_preview",
            "display_width": context.screen_width,
            "display_height": context.screen_height,
            "environment": self._resolve_environment(),
        }

    def _resolve_environment(self) -> str:
        normalized = self._computer_config.environment.strip().lower()
        if normalized in _ENVIRONMENT_ALIASES:
            return _ENVIRONMENT_ALIASES[normalized]
        if normalized in _VALID_ENVIRONMENTS:
            return normalized
        return "windows"

    def _apply_reasoning_payload(self, payload: dict[str, object]) -> None:
        if self._computer_config.reasoning_summary is None:
            return
        payload["reasoning"] = {"summary": self._computer_config.reasoning_summary}

    def _responses_url(self) -> str:
        return self._config.base_url.rstrip("/") + _RESPONSES_PATH

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }

    def _image_data_url(self, screenshot: ComputerScreenshot) -> str:
        return f"data:{screenshot.mime_type};base64,{screenshot.image_base64}"

    def _approval_args_preview(
        self,
        *,
        computer_call: _ResponsesComputerCall,
        action: ComputerAction,
    ) -> str:
        approval_reason = (
            "safety_check" if computer_call.pending_safety_checks else "policy"
        )
        return json.dumps(
            {
                "action": action.model_dump(mode="json"),
                "approval_reason": approval_reason,
                "pending_safety_checks": [
                    item.model_dump(mode="json")
                    for item in computer_call.pending_safety_checks
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def _pause_for_tool_approval(self, request: LLMRequest) -> _RuntimeSnapshot:
        current = self._run_runtime_repo.ensure(
            run_id=request.run_id,
            session_id=request.session_id,
            root_task_id=request.task_id,
        )
        snapshot = _RuntimeSnapshot(
            status=current.status,
            phase=current.phase,
            active_instance_id=current.active_instance_id,
            active_task_id=current.active_task_id,
            active_role_id=current.active_role_id,
            active_subagent_instance_id=current.active_subagent_instance_id,
        )
        self._run_runtime_repo.update(
            request.run_id,
            status=RunRuntimeStatus.PAUSED,
            phase=RunRuntimePhase.AWAITING_TOOL_APPROVAL,
            active_instance_id=request.instance_id,
            active_task_id=request.task_id,
            active_role_id=request.role_id,
            active_subagent_instance_id=current.active_subagent_instance_id,
            last_error=None,
        )
        return snapshot

    def _restore_runtime_after_approval(
        self,
        *,
        request: LLMRequest,
        snapshot: _RuntimeSnapshot,
    ) -> None:
        restored_status = RunRuntimeStatus.RUNNING
        restored_phase = (
            snapshot.phase
            if snapshot.phase != RunRuntimePhase.TERMINAL
            else RunRuntimePhase.COORDINATOR_RUNNING
        )
        self._run_runtime_repo.update(
            request.run_id,
            status=restored_status,
            phase=restored_phase,
            active_instance_id=snapshot.active_instance_id or request.instance_id,
            active_task_id=snapshot.active_task_id or request.task_id,
            active_role_id=snapshot.active_role_id or request.role_id,
            active_subagent_instance_id=snapshot.active_subagent_instance_id,
            last_error=None,
        )

    def _update_runtime_after_approval_error(
        self,
        *,
        request: LLMRequest,
        message: str,
    ) -> None:
        self._run_runtime_repo.update(
            request.run_id,
            status=RunRuntimeStatus.PAUSED,
            phase=RunRuntimePhase.AWAITING_TOOL_APPROVAL,
            active_instance_id=request.instance_id,
            active_task_id=request.task_id,
            active_role_id=request.role_id,
            active_subagent_instance_id=None,
            last_error=message,
        )

    def _raise_if_cancelled(self, request: LLMRequest) -> None:
        self._run_control_manager.raise_if_cancelled(
            run_id=request.run_id,
            instance_id=request.instance_id,
        )

    def _publish_model_step_event(
        self,
        *,
        request: LLMRequest,
        event_type: RunEventType,
        payload: dict[str, object],
    ) -> None:
        self._run_event_hub.publish(
            RunEvent(
                session_id=request.session_id,
                run_id=request.run_id,
                trace_id=request.trace_id,
                task_id=request.task_id,
                instance_id=request.instance_id,
                role_id=request.role_id,
                event_type=event_type,
                payload_json=json.dumps(payload, ensure_ascii=False),
            )
        )

    def _publish_tool_call_event(
        self,
        *,
        request: LLMRequest,
        computer_call: _ResponsesComputerCall,
        action: ComputerAction,
    ) -> None:
        action_payload = cast(dict[str, object], action.model_dump(mode="json"))
        self._run_event_hub.publish(
            RunEvent(
                session_id=request.session_id,
                run_id=request.run_id,
                trace_id=request.trace_id,
                task_id=request.task_id,
                instance_id=request.instance_id,
                role_id=request.role_id,
                event_type=RunEventType.TOOL_CALL,
                payload_json=json.dumps(
                    {
                        "tool_name": _COMPUTER_TOOL_NAME,
                        "tool_call_id": computer_call.call_id,
                        "args": {"action": action_payload},
                        "role_id": request.role_id,
                        "instance_id": request.instance_id,
                    },
                    ensure_ascii=False,
                ),
            )
        )

    def _publish_tool_result_event(
        self,
        *,
        request: LLMRequest,
        computer_call: _ResponsesComputerCall,
        action_result: ComputerActionResult,
        screenshot: ComputerScreenshot,
        context: ComputerContext,
        screenshot_artifact_path: str | None,
        screenshot_artifact_url: str | None,
    ) -> None:
        action_result_payload = cast(
            dict[str, object],
            action_result.model_dump(mode="json"),
        )
        result_payload: dict[str, object] = {
            "ok": action_result.ok,
            "data": {
                "action_result": action_result_payload,
                "current_url": context.current_url,
                "active_window_title": context.active_window_title,
                "screenshot": {
                    "artifact_path": screenshot_artifact_path,
                    "artifact_url": screenshot_artifact_url,
                    "mime_type": screenshot.mime_type,
                    "width": screenshot.width,
                    "height": screenshot.height,
                },
            },
        }
        self._run_event_hub.publish(
            RunEvent(
                session_id=request.session_id,
                run_id=request.run_id,
                trace_id=request.trace_id,
                task_id=request.task_id,
                instance_id=request.instance_id,
                role_id=request.role_id,
                event_type=RunEventType.TOOL_RESULT,
                payload_json=json.dumps(
                    {
                        "tool_name": _COMPUTER_TOOL_NAME,
                        "tool_call_id": computer_call.call_id,
                        "result": result_payload,
                        "error": not action_result.ok,
                        "role_id": request.role_id,
                        "instance_id": request.instance_id,
                    },
                    ensure_ascii=False,
                ),
            )
        )

    def _store_screenshot(
        self,
        *,
        request: LLMRequest,
        screenshot: ComputerScreenshot,
        step_index: int,
    ) -> tuple[str | None, str | None]:
        if self._computer_artifact_store is None:
            return None, None
        artifact_path = self._computer_artifact_store.save_screenshot(
            workspace_id=request.workspace_id,
            session_id=request.session_id,
            run_id=request.run_id,
            instance_id=request.instance_id,
            step_index=step_index,
            screenshot=screenshot,
        )
        relative_path = self._computer_artifact_store.relative_artifact_path(
            workspace_id=request.workspace_id,
            session_id=request.session_id,
            artifact_path=artifact_path,
        )
        return relative_path, self._artifact_url(
            session_id=request.session_id,
            artifact_path=relative_path,
        )

    def _artifact_url(self, *, session_id: str, artifact_path: str) -> str:
        return f"/api/sessions/{session_id}/artifacts/{artifact_path}"

    def _publish_tool_approval_notification(
        self,
        *,
        request: LLMRequest,
        tool_call_id: str,
    ) -> None:
        if self._notification_service is None:
            return
        role_label = request.role_id or "An agent"
        body = f"{role_label} requests approval for computer_use."
        _ = self._notification_service.emit(
            notification_type=NotificationType.TOOL_APPROVAL_REQUESTED,
            title="Approval Required",
            body=body,
            dedupe_key=f"tool_approval_requested:{request.run_id}:{tool_call_id}",
            context=NotificationContext(
                session_id=request.session_id,
                run_id=request.run_id,
                trace_id=request.trace_id,
                task_id=request.task_id,
                instance_id=request.instance_id,
                role_id=request.role_id,
                tool_call_id=tool_call_id,
                tool_name=_COMPUTER_TOOL_NAME,
            ),
        )

    def _publish_tool_approval_requested_event(
        self,
        *,
        request: LLMRequest,
        tool_call_id: str,
        args_preview: str,
    ) -> None:
        self._run_event_hub.publish(
            RunEvent(
                session_id=request.session_id,
                run_id=request.run_id,
                trace_id=request.trace_id,
                task_id=request.task_id,
                instance_id=request.instance_id,
                role_id=request.role_id,
                event_type=RunEventType.TOOL_APPROVAL_REQUESTED,
                payload_json=json.dumps(
                    {
                        "tool_call_id": tool_call_id,
                        "tool_name": _COMPUTER_TOOL_NAME,
                        "args_preview": args_preview,
                        "instance_id": request.instance_id,
                        "role_id": request.role_id,
                        "risk_level": "high",
                    },
                    ensure_ascii=False,
                ),
            )
        )

    def _publish_tool_approval_resolved_event(
        self,
        *,
        request: LLMRequest,
        tool_call_id: str,
        action: str,
        feedback: str,
    ) -> None:
        self._run_event_hub.publish(
            RunEvent(
                session_id=request.session_id,
                run_id=request.run_id,
                trace_id=request.trace_id,
                task_id=request.task_id,
                instance_id=request.instance_id,
                role_id=request.role_id,
                event_type=RunEventType.TOOL_APPROVAL_RESOLVED,
                payload_json=json.dumps(
                    {
                        "tool_call_id": tool_call_id,
                        "tool_name": _COMPUTER_TOOL_NAME,
                        "action": action,
                        "feedback": feedback,
                        "instance_id": request.instance_id,
                        "role_id": request.role_id,
                    },
                    ensure_ascii=False,
                ),
            )
        )

    def _publish_text_delta_event(self, *, request: LLMRequest, text: str) -> None:
        self._run_event_hub.publish(
            RunEvent(
                session_id=request.session_id,
                run_id=request.run_id,
                trace_id=request.trace_id,
                task_id=request.task_id,
                instance_id=request.instance_id,
                role_id=request.role_id,
                event_type=RunEventType.TEXT_DELTA,
                payload_json=json.dumps({"text": text}, ensure_ascii=False),
            )
        )
