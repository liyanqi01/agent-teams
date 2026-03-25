# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class MouseButton(StrEnum):
    LEFT = "left"
    MIDDLE = "middle"
    RIGHT = "right"


class ComputerPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: int = Field(ge=0)
    y: int = Field(ge=0)


class ComputerActionClick(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["click"] = "click"
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    button: MouseButton = MouseButton.LEFT


class ComputerActionDoubleClick(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["double_click"] = "double_click"
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    button: MouseButton = MouseButton.LEFT


class ComputerActionDrag(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["drag"] = "drag"
    path: tuple[ComputerPoint, ...] = Field(min_length=2)


class ComputerActionScroll(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["scroll"] = "scroll"
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    scroll_x: int
    scroll_y: int


class ComputerActionKeypress(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["keypress"] = "keypress"
    keys: tuple[str, ...] = Field(min_length=1)


class ComputerActionType(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["type"] = "type"
    text: str = Field(min_length=1)


class ComputerActionWait(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["wait"] = "wait"
    seconds: float | None = Field(default=None, ge=0.0, le=300.0)


class ComputerActionScreenshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["screenshot"] = "screenshot"


ComputerAction = Annotated[
    ComputerActionClick
    | ComputerActionDoubleClick
    | ComputerActionDrag
    | ComputerActionScroll
    | ComputerActionKeypress
    | ComputerActionType
    | ComputerActionWait
    | ComputerActionScreenshot,
    Field(discriminator="type"),
]


class ComputerActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    action_type: str = Field(min_length=1)
    message: str = Field(default="")


class ComputerScreenshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    image_base64: str = Field(min_length=1)
    mime_type: str = Field(default="image/png", min_length=1)
    width: int = Field(ge=1)
    height: int = Field(ge=1)


class ComputerContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    screen_width: int = Field(ge=1)
    screen_height: int = Field(ge=1)
    current_url: str | None = None
    active_window_title: str | None = None


class ComputerSafetyCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: str = Field(min_length=1)
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ComputerSessionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    instance_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    current_url: str | None = None
    active_window_title: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
