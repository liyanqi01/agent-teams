# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import final, override

from agent_teams.agents.execution.computer_use_session import ComputerUseSession
from agent_teams.agents.execution.message_repository import MessageRepository
from agent_teams.computer import ComputerArtifactStore, ComputerExecutor
from agent_teams.notifications import NotificationService
from agent_teams.providers.model_config import ModelEndpointConfig
from agent_teams.providers.provider_contracts import LLMProvider, LLMRequest
from agent_teams.sessions.runs.event_stream import RunEventHub
from agent_teams.sessions.runs.run_control_manager import RunControlManager
from agent_teams.sessions.runs.run_runtime_repo import RunRuntimeRepository
from agent_teams.tools.runtime import ToolApprovalManager, ToolApprovalPolicy
from agent_teams.tools.runtime.approval_ticket_repo import ApprovalTicketRepository


@final
class OpenAIResponsesComputerProvider(LLMProvider):
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
    ) -> None:
        self._session = ComputerUseSession(
            config,
            computer_executor=computer_executor,
            message_repo=message_repo,
            run_event_hub=run_event_hub,
            run_control_manager=run_control_manager,
            approval_ticket_repo=approval_ticket_repo,
            tool_approval_manager=tool_approval_manager,
            tool_approval_policy=tool_approval_policy,
            run_runtime_repo=run_runtime_repo,
            computer_artifact_store=computer_artifact_store,
            notification_service=notification_service,
        )

    @override
    async def generate(self, request: LLMRequest) -> str:
        return await self._session.run(request)
