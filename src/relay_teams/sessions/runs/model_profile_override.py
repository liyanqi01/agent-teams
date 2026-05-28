# -*- coding: utf-8 -*-
from __future__ import annotations

from relay_teams.roles.role_models import RoleDefinition


def apply_run_model_profile_override(
    role: RoleDefinition,
    model_profile: str | None,
) -> RoleDefinition:
    normalized = model_profile.strip() if model_profile is not None else ""
    if not normalized or role.model_profile == normalized:
        return role
    return role.model_copy(update={"model_profile": normalized})
