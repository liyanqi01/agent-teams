# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import pytest

from agent_teams.computer import ComputerScreenshot
from agent_teams.computer.artifact_store import ComputerArtifactStore
from agent_teams.workspace import WorkspaceManager


def test_computer_artifact_store_persists_png_screenshot(tmp_path: Path) -> None:
    store = ComputerArtifactStore(
        workspace_manager=WorkspaceManager(project_root=tmp_path)
    )

    artifact_path = store.save_screenshot(
        workspace_id="workspace-1",
        session_id="session-1",
        run_id="run-1",
        instance_id="instance-1",
        step_index=3,
        screenshot=ComputerScreenshot(
            image_base64="aGVsbG8=",
            mime_type="image/png",
            width=32,
            height=32,
        ),
    )

    assert artifact_path.name == "step-0003.png"
    assert artifact_path.read_bytes() == b"hello"
    assert (
        store.relative_artifact_path(
            workspace_id="workspace-1",
            session_id="session-1",
            artifact_path=artifact_path,
        )
        == "computer/run-1/instance-1/step-0003.png"
    )


def test_computer_artifact_store_resolves_relative_artifact_path(
    tmp_path: Path,
) -> None:
    store = ComputerArtifactStore(
        workspace_manager=WorkspaceManager(project_root=tmp_path)
    )

    artifact_path = store.save_screenshot(
        workspace_id="workspace-1",
        session_id="session-1",
        run_id="run-1",
        instance_id="instance-1",
        step_index=1,
        screenshot=ComputerScreenshot(
            image_base64="aGVsbG8=",
            mime_type="image/png",
            width=32,
            height=32,
        ),
    )

    resolved = store.resolve_artifact_path(
        workspace_id="workspace-1",
        session_id="session-1",
        relative_path="computer/run-1/instance-1/step-0001.png",
    )

    assert resolved == artifact_path.resolve()


@pytest.mark.parametrize(
    ("method_name", "kwargs"),
    [
        (
            "relative_artifact_path",
            {
                "workspace_id": "workspace-1",
                "session_id": "session-1",
                "artifact_path": Path("..") / "outside.png",
            },
        ),
        (
            "resolve_artifact_path",
            {
                "workspace_id": "workspace-1",
                "session_id": "session-1",
                "relative_path": "../outside.png",
            },
        ),
    ],
)
def test_computer_artifact_store_rejects_escape_paths(
    tmp_path: Path,
    method_name: str,
    kwargs: dict[str, str | Path],
) -> None:
    store = ComputerArtifactStore(
        workspace_manager=WorkspaceManager(project_root=tmp_path)
    )

    with pytest.raises(ValueError, match="escapes the session artifact root"):
        getattr(store, method_name)(**kwargs)


def test_computer_artifact_store_rejects_invalid_base64(tmp_path: Path) -> None:
    store = ComputerArtifactStore(
        workspace_manager=WorkspaceManager(project_root=tmp_path)
    )

    with pytest.raises(ValueError, match="not valid base64"):
        store.save_screenshot(
            workspace_id="workspace-1",
            session_id="session-1",
            run_id="run-1",
            instance_id="instance-1",
            step_index=0,
            screenshot=ComputerScreenshot(
                image_base64="***",
                mime_type="image/png",
                width=32,
                height=32,
            ),
        )
