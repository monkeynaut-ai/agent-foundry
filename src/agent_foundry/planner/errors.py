"""Typed exceptions for planner operations."""


class UnknownRoleError(Exception):
    """Raised when a plan references a role not in the registry."""

    def __init__(self, message: str, role: str, node_id: str):
        self.role = role
        self.node_id = node_id
        super().__init__(message)


class DuplicateNodeIdError(Exception):
    """Raised when a plan contains duplicate node IDs."""

    def __init__(self, message: str, node_id: str):
        self.node_id = node_id
        super().__init__(message)


class DanglingEdgeError(Exception):
    """Raised when an edge references a non-existent node."""

    def __init__(self, message: str, node_id: str):
        self.node_id = node_id
        super().__init__(message)


class PlanValidationError(Exception):
    """General plan validation error for tool, breakpoint, version, and loop rules."""

    def __init__(self, message: str):
        super().__init__(message)


class SchemaContractError(PlanValidationError):
    """Raised when a node's declared I/O keys violate the state_schema contract."""

    def __init__(self, message: str, node_id: str, undeclared_keys: set[str]):
        self.node_id = node_id
        self.undeclared_keys = undeclared_keys
        super().__init__(message)


class PlanningInsufficientContextError(Exception):
    """Raised when planner has insufficient context (no snippets in strict mode)."""

    def __init__(self, message: str):
        super().__init__(message)


class PlanningTimeoutError(Exception):
    """Raised when planning exceeds the time budget."""

    def __init__(self, message: str):
        super().__init__(message)
