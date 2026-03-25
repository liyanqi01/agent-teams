# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import final, override

from agent_teams.agents.execution.computer_use_session import ComputerUseSession
from agent_teams.agents.execution.message_repository import MessageRepository
from agent_teams.computer import ComputerExecutor
from agent_teams.providers.model_config import ModelEndpointConfig
from agent_teams.providers.provider_contracts import LLMProvider, LLMRequest
from agent_teams.sessions.runs.event_stream import RunEventHub
from agent_teams.sessions.runs.run_control_manager import RunControlManager


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
    ) -> None:
        self._session = ComputerUseSession(
            config,
            computer_executor=computer_executor,
            message_repo=message_repo,
            run_event_hub=run_event_hub,
            run_control_manager=run_control_manager,
        )

    @override
    async def generate(self, request: LLMRequest) -> str:
        return await self._session.run(request)
