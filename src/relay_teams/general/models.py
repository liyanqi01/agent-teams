# -*- coding: utf-8 -*-
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from relay_teams.tools.runtime.policy import ExternalDirectoryPermissionMode


class GeneralConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shell_safety_policy_enabled: bool = True
    external_directory_permission: ExternalDirectoryPermissionMode = (
        ExternalDirectoryPermissionMode.ASK
    )


class GeneralConfigUpdate(GeneralConfig):
    model_config = ConfigDict(extra="forbid")
