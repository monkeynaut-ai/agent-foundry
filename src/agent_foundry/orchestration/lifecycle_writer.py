"""Append-only JSONL writer for run lifecycle events.

CS7 Plan 2 Task B.2. Provides :class:`LifecycleWriter`, which auto-stamps
every record with ``ts`` (ISO 8601 UTC) and ``run_id``, is safe to call
from multiple threads, and flushes per record so a crashed process still
leaves a readable partial log.
"""

from __future__ import annotations

import datetime
import json
import threading
from pathlib import Path
from types import TracebackType
from typing import Any


class LifecycleWriter:
    """Append-only JSONL writer for run lifecycle events.

    Auto-stamps every record with ``ts`` (ISO 8601 UTC) and ``run_id``.
    Thread-safe and safe to call from async contexts. Writes are flushed
    per record so a crashed process still leaves a readable partial log.
    """

    def __init__(self, run_id: str, path: Path) -> None:
        self._run_id = run_id
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fh = path.open("a", encoding="utf-8")
        self._closed = False

    def append(self, event: dict[str, Any]) -> None:
        """Append ``event`` to the log, stamped with ``ts`` and ``run_id``."""
        record: dict[str, Any] = dict(event)
        record["ts"] = datetime.datetime.now(datetime.UTC).isoformat()
        record["run_id"] = self._run_id
        line = json.dumps(record) + "\n"
        with self._lock:
            if self._closed:
                raise RuntimeError("LifecycleWriter is closed")
            self._fh.write(line)
            self._fh.flush()

    def append_run_event(self, event: dict[str, Any]) -> None:
        """Public alias exposed to product hooks (FunctionAction callables)."""
        self.append(event)

    def close(self) -> None:
        """Close the underlying file. Idempotent."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._fh.close()

    def __enter__(self) -> LifecycleWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
