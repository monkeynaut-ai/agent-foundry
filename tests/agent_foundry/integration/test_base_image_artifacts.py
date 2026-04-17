"""Integration tests — base image ships the generic agent brief and skills.

Verifies that the `agent-worker:latest` image contains the two artifacts
the CS7 agents depend on:

- `/home/claude/.claude/CLAUDE.md` — generic agent brief referencing
  the structured-output protocol via `AgentTurnEnvelope`.
- `/home/claude/.claude/skills/lessons-learned/SKILL.md` — the skill an
  agent invokes at task-completion to log observations.

These are verified by `docker run` + `cat`, not by image-layer
inspection, so they catch both missing-file and wrong-content failures.
"""

from __future__ import annotations

import subprocess

import pytest

pytestmark = pytest.mark.integration


IMAGE_TAG = "agent-worker:latest"


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _image_exists(tag: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", tag],
        capture_output=True,
        timeout=5,
    )
    return result.returncode == 0


def _read_file_from_image(tag: str, path: str) -> str:
    result = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "cat", tag, path],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"failed to read {path} from {tag}: exit={result.returncode} stderr={result.stderr}"
        )
    return result.stdout


@pytest.fixture(scope="module", autouse=True)
def ensure_image() -> None:
    if not _docker_available():
        pytest.skip("docker daemon not available")
    if not _image_exists(IMAGE_TAG):
        pytest.skip(f"{IMAGE_TAG} not built (run `pdm docker-base`)")


def test_base_image_ships_generic_claude_md() -> None:
    content = _read_file_from_image(IMAGE_TAG, "/home/claude/.claude/CLAUDE.md")
    assert "AgentTurnEnvelope" in content, (
        "base CLAUDE.md must describe the structured-output protocol via AgentTurnEnvelope"
    )
    assert "/workspace" in content
    assert "Archipelago" not in content, (
        "base CLAUDE.md must be generic — no product-specific names"
    )


def test_base_image_ships_lessons_learned_skill() -> None:
    content = _read_file_from_image(
        IMAGE_TAG,
        "/home/claude/.claude/skills/lessons-learned/SKILL.md",
    )
    assert "name: lessons-learned" in content
    assert "lessons-learned.md" in content
