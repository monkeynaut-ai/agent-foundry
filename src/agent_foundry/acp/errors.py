"""Error classes for the Agent Container Protocol subsystem."""


class ContainerCreationError(Exception):
    """Raised when container creation fails."""

    def __init__(self, message: str, image: str | None = None):
        super().__init__(message)
        self.image = image


class ContainerLifecycleError(Exception):
    """Raised when a container lifecycle operation fails."""

    def __init__(self, message: str, container_id: str | None = None):
        super().__init__(message)
        self.container_id = container_id


class SessionError(Exception):
    """Raised when a session operation fails."""

    def __init__(self, message: str, container_id: str | None = None):
        super().__init__(message)
        self.container_id = container_id


class AdapterError(Exception):
    """Raised when an adapter operation fails (connection, parsing, etc.)."""


class ProtocolError(Exception):
    """Raised on protocol parse failures (invalid JSON, unknown type, etc.)."""
