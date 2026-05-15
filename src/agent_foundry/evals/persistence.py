"""Persistence for eval ``RunResult`` artifacts.

Writes one ``report.json`` per run, under ``<out_dir>/<run_id>/``. The
file is the canonical contract for any downstream viewer (CLI renderer,
future UI, cross-run diffing tool) — keep the schema stable and
self-describing.

Reading returns the raw parsed dict rather than reconstructing a typed
``RunResult``: case inputs and outputs are user-defined Pydantic models
whose classes the reader doesn't know about. Typed round-trip is left
to consumers that have access to the original types.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_foundry.evals.models import RunResult


def write_report(result: RunResult, out_dir: Path) -> Path:
    """Persist ``result`` to ``<out_dir>/<result.run_id>/report.json``.

    Creates intermediate directories if absent. Returns the absolute
    path of the written file.
    """
    run_dir = out_dir / result.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "report.json"
    data = result.model_dump(mode="json")
    path.write_text(json.dumps(data, indent=2, default=str))
    return path


def read_report_json(path: Path) -> dict[str, Any]:
    """Load a persisted ``report.json`` as a parsed dict.

    Raises :class:`FileNotFoundError` if ``path`` does not exist.
    """
    return json.loads(path.read_text())
