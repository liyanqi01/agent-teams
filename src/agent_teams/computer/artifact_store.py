# -*- coding: utf-8 -*-
from __future__ import annotations

from base64 import b64decode
from binascii import Error as BinasciiError
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from agent_teams.computer.action_models import ComputerScreenshot
from agent_teams.workspace import WorkspaceManager


class ComputerArtifactStore(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    workspace_manager: WorkspaceManager

    def save_screenshot(
        self,
        *,
        workspace_id: str,
        session_id: str,
        run_id: str,
        instance_id: str,
        step_index: int,
        screenshot: ComputerScreenshot,
    ) -> Path:
        artifact_dir = (
            self.session_artifact_root(
                workspace_id=workspace_id,
                session_id=session_id,
            )
            / "computer"
            / run_id
            / instance_id
        )
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = (
            artifact_dir
            / f"step-{step_index:04d}{_mime_type_suffix(screenshot.mime_type)}"
        )
        try:
            image_bytes = b64decode(screenshot.image_base64, validate=True)
        except BinasciiError as exc:
            raise ValueError(
                "Computer screenshot payload is not valid base64."
            ) from exc
        artifact_path.write_bytes(image_bytes)
        return artifact_path

    def session_artifact_root(
        self,
        *,
        workspace_id: str,
        session_id: str,
    ) -> Path:
        return self.workspace_manager.session_artifact_dir(
            workspace_id=workspace_id,
            session_id=session_id,
        ).resolve()

    def relative_artifact_path(
        self,
        *,
        workspace_id: str,
        session_id: str,
        artifact_path: Path,
    ) -> str:
        root = self.session_artifact_root(
            workspace_id=workspace_id,
            session_id=session_id,
        )
        resolved_artifact = artifact_path.resolve()
        if resolved_artifact != root and root not in resolved_artifact.parents:
            raise ValueError("Artifact path escapes the session artifact root.")
        return resolved_artifact.relative_to(root).as_posix()

    def resolve_artifact_path(
        self,
        *,
        workspace_id: str,
        session_id: str,
        relative_path: str,
    ) -> Path:
        root = self.session_artifact_root(
            workspace_id=workspace_id,
            session_id=session_id,
        )
        candidate = (root / relative_path).resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError("Artifact path escapes the session artifact root.")
        return candidate


def _mime_type_suffix(mime_type: str) -> str:
    normalized = mime_type.strip().lower()
    if normalized == "image/png":
        return ".png"
    if normalized == "image/jpeg":
        return ".jpg"
    if normalized == "image/webp":
        return ".webp"
    return ".bin"
