# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import final, override

from agent_teams.providers.model_config import ModelEndpointConfig
from agent_teams.providers.provider_contracts import LLMProvider, LLMRequest


@final
class OpenAIResponsesComputerProvider(LLMProvider):
    def __init__(self, config: ModelEndpointConfig) -> None:
        self._config = config

    @override
    async def generate(self, request: LLMRequest) -> str:
        raise RuntimeError(
            "Computer use execution is not implemented yet for provider "
            f"'{self._config.provider.value}' on role '{request.role_id}'."
        )
