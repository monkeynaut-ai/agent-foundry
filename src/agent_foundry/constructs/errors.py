"""Typed exceptions for construct graph validation."""


class ConstructValidationError(Exception):
    """Base for all construct graph validation errors."""

    def __init__(self, message: str):
        super().__init__(message)


class TypeMismatchError(ConstructValidationError):
    """Adjacent constructs have incompatible input/output types."""

    def __init__(self, message: str, expected: type, actual: type, position: str):
        self.expected = expected
        self.actual = actual
        self.position = position
        super().__init__(message)


class InvalidPromptKeyError(ConstructValidationError):
    """GateAction prompt_key not found in input type's model_fields."""

    def __init__(self, message: str, prompt_key: str, available_fields: list[str]):
        self.prompt_key = prompt_key
        self.available_fields = available_fields
        super().__init__(message)


class UnregisteredConstructError(ConstructValidationError):
    """No validator registered for a construct type encountered during validation."""

    def __init__(self, message: str, construct_type: type):
        self.construct_type = construct_type
        super().__init__(message)


class ConstructCompilationError(Exception):
    """Raised when a construct cannot be compiled or validated at runtime."""

    def __init__(self, message: str, construct_type: str = ""):
        self.construct_type = construct_type
        super().__init__(message)


class ConstructTimeoutError(Exception):
    """Raised when a construct's executor exceeds its declared ``timeout_seconds``."""

    def __init__(self, node_id: str, timeout_seconds: float, construct_type: str = ""):
        self.node_id = node_id
        self.timeout_seconds = timeout_seconds
        self.construct_type = construct_type
        super().__init__(
            f"{construct_type or 'Construct'} {node_id} exceeded its "
            f"timeout_seconds ({timeout_seconds:g}s)"
        )
