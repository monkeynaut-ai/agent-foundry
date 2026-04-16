"""Lifecycle writer contract and implementations.

This module defines:

* :class:`LifecycleWriter` — the abstract base class (contract) for
  run lifecycle event sinks. Product code that implements the
  contract declares inheritance explicitly.
* :class:`JsonlLifecycleWriter` — the concrete append-only JSONL
  implementation, auto-stamping every record with ``ts``
  (ISO 8601 UTC) and ``run_id``, thread-safe, and flushing per
  record so a crashed process still leaves a readable partial log.
* :class:`NoOpLifecycleWriter` — a sink that discards every event;
  useful for unit tests and other callers that do not need a
  persistent lifecycle log.
"""

from __future__ import annotations

import datetime
import json
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from types import TracebackType
from typing import Any

from agent_foundry.orchestration.lifecycle_events import LifecycleEvent


class LifecycleWriter(ABC):
    """Abstract contract for lifecycle event sinks.

    Concrete implementations must supply :meth:`append`,
    :meth:`append_run_event`, and :meth:`close`. The append methods
    are typed at the entry point: :meth:`append` requires a
    :class:`LifecycleEvent` member as the first argument, with extra
    fields supplied via ``**fields``. Products emit their own
    open-schema events via :meth:`append_run_event`, which stamps
    ``type=LifecycleEvent.DOMAIN`` and accepts a product-chosen
    ``kind`` string.
    """

    @abstractmethod
    def append(self, event_type: LifecycleEvent, **fields: Any) -> None:
        """Append a platform lifecycle event."""

    @abstractmethod
    def append_run_event(self, kind: str, **fields: Any) -> None:
        """Emit a product-defined (``type=domain``) event."""

    @abstractmethod
    def close(self) -> None:
        """Release any underlying resources. Must be idempotent."""


class JsonlLifecycleWriter(LifecycleWriter):
    """Append-only JSONL writer for run lifecycle events.

    Auto-stamps every record with ``ts`` (ISO 8601 UTC) and ``run_id``.
    Thread-safe and safe to call from async contexts. Writes are flushed
    per record so a crashed process still leaves a readable partial log.

    Events are typed at the entry point: :meth:`append` requires a
    :class:`LifecycleEvent` member as the first argument, with extra
    fields supplied via ``**fields``. Pyright rejects untyped strings
    and typos on the enum at call time. Products emit their own
    open-schema events via :meth:`append_run_event`, which stamps
    ``type=LifecycleEvent.DOMAIN`` and accepts a product-chosen ``kind``.
    """

    def __init__(self, run_id: str, path: Path) -> None:
        self._run_id = run_id
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fh = path.open("a", encoding="utf-8")
        self._closed = False

    def append(self, event_type: LifecycleEvent, **fields: Any) -> None:
        """Append a platform lifecycle event, stamped with ``ts`` / ``run_id``.

        Example::

            writer.append(
                LifecycleEvent.TURN_STARTED,
                agent_name="reviewer",
                invocation=1,
                turn=0,
            )

        The recorded JSON line has shape::

            {"type": "turn_started", "ts": "...", "run_id": "...",
             "agent_name": "reviewer", "invocation": 1, "turn": 0}
        """
        record: dict[str, Any] = {
            "type": event_type.value,
            "ts": datetime.datetime.now(datetime.UTC).isoformat(),
            "run_id": self._run_id,
            **fields,
        }
        line = json.dumps(record) + "\n"
        with self._lock:
            if self._closed:
                raise RuntimeError("LifecycleWriter is closed")
            self._fh.write(line)
            self._fh.flush()

    def append_run_event(self, kind: str, **fields: Any) -> None:
        """Emit a product-defined (``type=domain``) event.

        The convention for products extending the lifecycle stream with
        their own vocabulary. ``kind`` is a product-chosen subtype
        string used by downstream consumers (summary renderers, etc.)
        to route on the event's meaning. Extra fields are free-form.

        Example (from a ``FunctionAction`` callable)::

            run_ctx.lifecycle_writer.append_run_event(
                "step_committed",
                change_set="cs7-plan2",
                step="lifecycle-orchestration",
                commit_sha="a1b2c3d",
            )
        """
        self.append(LifecycleEvent.DOMAIN, kind=kind, **fields)

    def close(self) -> None:
        """Close the underlying file. Idempotent."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._fh.close()

    def __enter__(self) -> JsonlLifecycleWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class NoOpLifecycleWriter(LifecycleWriter):
    """Satisfies the :class:`LifecycleWriter` contract by discarding events."""

    def append(self, event_type: LifecycleEvent, **fields: Any) -> None:
        return None

    def append_run_event(self, kind: str, **fields: Any) -> None:
        return None

    def close(self) -> None:
        return None
