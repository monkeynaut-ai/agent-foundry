"""Typed exceptions for compiler operations."""


class PlanCompilationError(Exception):
    """Raised when a plan cannot be compiled."""

    def __init__(self, message: str):
        super().__init__(message)


class RoleInstantiationError(Exception):
    """Raised when a role handler cannot be instantiated."""

    def __init__(self, message: str, node_id: str, role: str):
        self.node_id = node_id
        self.role = role
        super().__init__(message)


class StateSchemaViolationError(Exception):
    """Raised at runtime when a handler returns keys not declared in state_schema."""

    def __init__(self, message: str, node_id: str, undeclared_keys: set[str]):
        self.node_id = node_id
        self.undeclared_keys = undeclared_keys
        super().__init__(message)


class MaxIterationsExceededError(Exception):
    """Raised when a loop exceeds its max iteration count."""

    def __init__(self, message: str, node_id: str, iterations: int):
        self.node_id = node_id
        self.iterations = iterations
        super().__init__(message)
