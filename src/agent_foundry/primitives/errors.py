"""Typed exceptions for primitive graph validation."""


class PrimitiveValidationError(Exception):
    """Base for all primitive graph validation errors."""

    def __init__(self, message: str):
        super().__init__(message)


class TypeMismatchError(PrimitiveValidationError):
    """Adjacent primitives have incompatible input/output types."""

    def __init__(self, message: str, expected: type, actual: type, position: str):
        self.expected = expected
        self.actual = actual
        self.position = position
        super().__init__(message)


class InvalidPromptKeyError(PrimitiveValidationError):
    """GateAction prompt_key not found in input type's model_fields."""

    def __init__(self, message: str, prompt_key: str, available_fields: list[str]):
        self.prompt_key = prompt_key
        self.available_fields = available_fields
        super().__init__(message)


class PrimitiveCompilationError(Exception):
    """Raised when a primitive cannot be compiled or validated at runtime."""

    def __init__(self, message: str, primitive_type: str = ""):
        self.primitive_type = primitive_type
        super().__init__(message)
