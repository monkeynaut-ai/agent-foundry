"""Run artifacts directory bootstrap.

Creates the per-run artifacts directory layout and generates the
``inspect-workspace.sh`` helper script that lets operators drop into
the retained workspace volume after a run completes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

__all__ = [
    "agent_log_path",
    "agent_turn_dir",
    "bootstrap_run_artifacts",
    "write_inspect_container_script",
]


_INSPECT_SCRIPT_TEMPLATE = """\
#!/bin/bash
# Auto-generated on {iso_timestamp}
# Inspect the workspace volume for run {run_id}.
# The volume is retained after the run so this script works as long as
# the volume has not been pruned manually.
#
# ``--entrypoint bash`` bypasses the base image's entrypoint (which
# requires auth and runs the full setup sequence). We just want a
# shell on the volume, not a running agent.
#
# ``--user claude`` plus ``--group-add`` for the workspace GIDs (typical
# archipelago convention: 1001 documents, 1002 codebase, 1003 tests)
# reproduces the perms the agents themselves run with. Without this you
# land as root and any test or tool you invoke creates root-owned files
# in the volume, which blocks subsequent agent-user processes.
set -euo pipefail
docker run --rm -it \\
  --entrypoint bash \\
  --user claude \\
  --group-add 1001 \\
  --group-add 1002 \\
  --group-add 1003 \\
  -v "{workspace_volume}:/workspace" \\
  --workdir /workspace \\
  "{base_image_tag}"
"""


def bootstrap_run_artifacts(
    *,
    artifacts_dir: Path,
    run_id: str,
    workspace_volume: str,
    base_image_tag: str,
) -> Path:
    """Create ``<artifacts_dir>/<run_id>/`` and write ``inspect-workspace.sh``.

    Raises ``FileExistsError`` if the run directory already exists, so
    callers see collisions instead of silently overwriting prior runs.
    """
    run_dir = artifacts_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    script_path = run_dir / "inspect-workspace.sh"
    script_path.write_text(
        _INSPECT_SCRIPT_TEMPLATE.format(
            iso_timestamp=datetime.now(UTC).isoformat(),
            run_id=run_id,
            workspace_volume=workspace_volume,
            base_image_tag=base_image_tag,
        ),
        encoding="utf-8",
    )
    script_path.chmod(0o755)
    return run_dir


_INSPECT_CONTAINER_SCRIPT_TEMPLATE = """\
#!/bin/bash
# Auto-generated on {iso_timestamp}
# Drop a shell into the retained container for run {run_id}, agent {agent_name}.
#
# When you're done inspecting:
#   docker rm -f {container_id}
set -euo pipefail
docker exec -it {container_id} bash
"""


def write_inspect_container_script(
    *,
    run_dir: Path,
    agent_name: str,
    container_id: str,
    run_id: str = "",
) -> Path:
    """Write ``<run_dir>/<agent_name>/inspect-container.sh``.

    Generated when a retained container leaves a postmortem trail. The
    script wraps ``docker exec -it <container_id> bash`` so a developer
    doesn't have to re-derive the container id or the docker command.

    The agent directory is created on demand (parents=True, exist_ok).
    Returns the path to the script.
    """
    agent_dir = run_dir / agent_name
    agent_dir.mkdir(parents=True, exist_ok=True)
    script_path = agent_dir / "inspect-container.sh"
    script_path.write_text(
        _INSPECT_CONTAINER_SCRIPT_TEMPLATE.format(
            iso_timestamp=datetime.now(UTC).isoformat(),
            run_id=run_id,
            agent_name=agent_name,
            container_id=container_id,
        ),
        encoding="utf-8",
    )
    script_path.chmod(0o755)
    return script_path


def agent_turn_dir(run_dir: Path, agent_name: str, turn: int) -> Path:
    """Return ``<run_dir>/<agent_name>/turns/<turn>/``, creating it if needed.

    Also ensures the ``collected_files/`` subdirectory exists so the
    review-feedback-loop collection step has a stable target.
    """
    turn_dir = run_dir / agent_name / "turns" / str(turn)
    (turn_dir / "collected_files").mkdir(parents=True, exist_ok=True)
    return turn_dir


def agent_log_path(run_dir: Path, agent_name: str) -> Path:
    """Return ``<run_dir>/<agent_name>/container.log`` (does not create it).

    The agent directory itself is created so callers can open the log
    for writing without an intermediate ``mkdir``.
    """
    agent_dir = run_dir / agent_name
    agent_dir.mkdir(parents=True, exist_ok=True)
    return agent_dir / "container.log"
