"""Run artifacts directory bootstrap for CS7 Plan 2 orchestration.

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
set -euo pipefail
docker run --rm -it \\
  --entrypoint bash \\
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
