"""Typed exceptions for compiler operations."""


class PlanCompilationError(Exception):
    """Raised when a plan cannot be compiled."""

    def __init__(self, message: str):
        super().__init__(message)


class CapabilityInstantiationError(Exception):
    """Raised when a capability handler cannot be instantiated."""

    def __init__(self, message: str, node_id: str, capability: str):
        self.node_id = node_id
        self.capability = capability
        super().__init__(message)


class MaxIterationsExceededError(Exception):
    """Raised when a loop exceeds its max iteration count."""

    def __init__(self, message: str, node_id: str, iterations: int):
        self.node_id = node_id
        self.iterations = iterations
        super().__init__(message)
