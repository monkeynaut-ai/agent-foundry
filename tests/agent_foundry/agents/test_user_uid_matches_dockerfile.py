"""Regression test: AGENT_USER_UID/GID stay in sync with Dockerfile.base.

The Python constants and the Dockerfile's ``useradd -u/-g`` numbers must
agree, or hosts that ``chown`` files for the in-container ``claude`` user
will write the wrong UID and the agent will fail to read or write them.
This test parses the Dockerfile and asserts the numbers match.
"""

from __future__ import annotations

import re
from pathlib import Path

from agent_foundry.agents import AGENT_USER_GID, AGENT_USER_UID

DOCKERFILE = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "agent_foundry"
    / "agents"
    / "docker"
    / "Dockerfile.base"
)


def test_agent_user_uid_matches_dockerfile() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    match = re.search(r"useradd\s+[^\n]*-u\s+(\d+)", text)
    assert match is not None, f"could not find 'useradd -u <N>' in {DOCKERFILE}"
    dockerfile_uid = int(match.group(1))
    assert dockerfile_uid == AGENT_USER_UID, (
        f"AGENT_USER_UID ({AGENT_USER_UID}) drifted from Dockerfile useradd -u "
        f"({dockerfile_uid}); update one to match the other."
    )


def test_agent_user_gid_matches_dockerfile() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    match = re.search(r"groupadd\s+-g\s+(\d+)", text)
    assert match is not None, f"could not find 'groupadd -g <N>' in {DOCKERFILE}"
    dockerfile_gid = int(match.group(1))
    assert dockerfile_gid == AGENT_USER_GID, (
        f"AGENT_USER_GID ({AGENT_USER_GID}) drifted from Dockerfile groupadd -g "
        f"({dockerfile_gid}); update one to match the other."
    )
