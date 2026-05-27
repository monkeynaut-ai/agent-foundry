import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from types import TracebackType

from agent_foundry.observability.models import AgentTurnRecord


class ObservabilityStore(ABC):
    @abstractmethod
    def append(self, record: AgentTurnRecord) -> None: ...

    @abstractmethod
    def iter_records(self) -> Iterator[AgentTurnRecord]: ...

    @abstractmethod
    def close(self) -> None: ...


class JsonlObservabilityStore(ObservabilityStore):
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._file = path.open("a", encoding="utf-8")
        self._lock = threading.Lock()
        self._closed = False

    def append(self, record: AgentTurnRecord) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("Store is closed")
            self._file.write(record.model_dump_json() + "\n")
            self._file.flush()

    def iter_records(self) -> Iterator[AgentTurnRecord]:
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                yield AgentTurnRecord.model_validate_json(line)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._file.flush()
            self._file.close()
            self._closed = True

    def __enter__(self) -> JsonlObservabilityStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()


class NoOpObservabilityStore(ObservabilityStore):
    def append(self, record: AgentTurnRecord) -> None:
        pass

    def iter_records(self) -> Iterator[AgentTurnRecord]:
        return iter([])

    def close(self) -> None:
        pass
