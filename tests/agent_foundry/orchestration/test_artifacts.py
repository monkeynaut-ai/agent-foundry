"""Tests for the artifacts directory bootstrap.

Covers ``bootstrap_run_artifacts``, ``agent_turn_dir``, and
``agent_log_path`` in ``agent_foundry.orchestration.artifacts``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_foundry.orchestration.artifacts import (
    agent_log_path,
    agent_turn_dir,
    bootstrap_run_artifacts,
)

RUN_ID = "run-abc"
WORKSPACE_VOLUME = "run-abc-ws"
BASE_IMAGE_TAG = "acp-cc-worker:latest"


def test_bootstrap_creates_run_dir_and_returns_its_path(tmp_path: Path) -> None:
    run_dir = bootstrap_run_artifacts(
        artifacts_dir=tmp_path,
        run_id=RUN_ID,
        workspace_volume=WORKSPACE_VOLUME,
        base_image_tag=BASE_IMAGE_TAG,
    )

    assert run_dir == tmp_path / RUN_ID
    assert run_dir.is_dir()


def test_bootstrap_collision_raises_file_exists_error(tmp_path: Path) -> None:
    bootstrap_run_artifacts(
        artifacts_dir=tmp_path,
        run_id=RUN_ID,
        workspace_volume=WORKSPACE_VOLUME,
        base_image_tag=BASE_IMAGE_TAG,
    )

    with pytest.raises(FileExistsError):
        bootstrap_run_artifacts(
            artifacts_dir=tmp_path,
            run_id=RUN_ID,
            workspace_volume=WORKSPACE_VOLUME,
            base_image_tag=BASE_IMAGE_TAG,
        )


def test_bootstrap_writes_inspect_workspace_script_with_bash_header(
    tmp_path: Path,
) -> None:
    run_dir = bootstrap_run_artifacts(
        artifacts_dir=tmp_path,
        run_id=RUN_ID,
        workspace_volume=WORKSPACE_VOLUME,
        base_image_tag=BASE_IMAGE_TAG,
    )

    script_path = run_dir / "inspect-workspace.sh"
    assert script_path.is_file()
    contents = script_path.read_text(encoding="utf-8")
    assert contents.startswith("#!/bin/bash")


def test_inspect_script_contains_volume_image_and_run_id(tmp_path: Path) -> None:
    run_dir = bootstrap_run_artifacts(
        artifacts_dir=tmp_path,
        run_id=RUN_ID,
        workspace_volume=WORKSPACE_VOLUME,
        base_image_tag=BASE_IMAGE_TAG,
    )

    contents = (run_dir / "inspect-workspace.sh").read_text(encoding="utf-8")
    assert WORKSPACE_VOLUME in contents
    assert BASE_IMAGE_TAG in contents
    assert RUN_ID in contents


def test_inspect_script_is_executable(tmp_path: Path) -> None:
    run_dir = bootstrap_run_artifacts(
        artifacts_dir=tmp_path,
        run_id=RUN_ID,
        workspace_volume=WORKSPACE_VOLUME,
        base_image_tag=BASE_IMAGE_TAG,
    )

    script_path = run_dir / "inspect-workspace.sh"
    assert script_path.stat().st_mode & 0o111 != 0


def test_agent_turn_dir_returns_expected_path_and_creates_it(tmp_path: Path) -> None:
    run_dir = bootstrap_run_artifacts(
        artifacts_dir=tmp_path,
        run_id=RUN_ID,
        workspace_volume=WORKSPACE_VOLUME,
        base_image_tag=BASE_IMAGE_TAG,
    )

    turn_dir = agent_turn_dir(run_dir, "reviewer", 3)

    assert turn_dir == run_dir / "reviewer" / "turns" / "3"
    assert turn_dir.is_dir()
    assert (turn_dir / "collected_files").is_dir()


def test_agent_turn_dir_is_idempotent(tmp_path: Path) -> None:
    run_dir = bootstrap_run_artifacts(
        artifacts_dir=tmp_path,
        run_id=RUN_ID,
        workspace_volume=WORKSPACE_VOLUME,
        base_image_tag=BASE_IMAGE_TAG,
    )

    first = agent_turn_dir(run_dir, "reviewer", 3)
    second = agent_turn_dir(run_dir, "reviewer", 3)

    assert first == second
    assert first.is_dir()


def test_agent_log_path_returns_container_log_without_creating_file(
    tmp_path: Path,
) -> None:
    run_dir = bootstrap_run_artifacts(
        artifacts_dir=tmp_path,
        run_id=RUN_ID,
        workspace_volume=WORKSPACE_VOLUME,
        base_image_tag=BASE_IMAGE_TAG,
    )

    log_path = agent_log_path(run_dir, "reviewer")

    assert log_path == run_dir / "reviewer" / "container.log"
    assert log_path.parent.is_dir()
    assert not log_path.exists()
