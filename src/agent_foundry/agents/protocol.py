"""TypedAgent protocol — agents decoupled from orchestration.

A TypedAgent declares its contract through its ``__call__`` signature:
- Parameters are individually typed inputs (mapped from state by name)
- Return type is a Pydantic output model (dumped to dict for state merge)

The agent knows nothing about LangGraph, shared state, or dicts.
The connector (see ``connector.py``) bridges the gap.
"""

from typing import Any, Protocol, get_type_hints, runtime_checkable

from pydantic import BaseModel


@runtime_checkable
class TypedAgent(Protocol):
    """Agent that declares typed parameters and returns a typed output model.

    The connector discovers input types from ``__call__`` type hints.
    The return annotation must be a ``BaseModel`` subclass.

    Example::

        class CodeWriter:
            def __init__(self, *, prompt_preamble=None, **kwargs):
                self.prompt_preamble = prompt_preamble or []

            def __call__(
                self,
                current_task: CurrentTask,
                workspace_volume: WorkSpace,
            ) -> CodeWriterOutput:
                ...
    """

    def __call__(self, **kwargs: Any) -> BaseModel: ...


def is_typed_agent(obj: object) -> bool:
    """Check whether *obj* satisfies the TypedAgent contract.

    A plain ``isinstance(obj, TypedAgent)`` check is unreliable because
    ``Protocol`` runtime checks only verify method existence, not
    signatures.  This helper also verifies that:

    1. ``__call__`` has at least one typed parameter (beyond ``self``).
    2. The return annotation is a ``BaseModel`` subclass.
    """
    if not callable(obj):
        return False

    try:
        hints = get_type_hints(type(obj).__call__)
    except Exception:
        return False

    # Must have a return annotation that is a BaseModel subclass
    return_type = hints.get("return")
    if return_type is None:
        return False
    if not (isinstance(return_type, type) and issubclass(return_type, BaseModel)):
        return False

    # Must have at least one typed parameter beyond 'self' and 'return'
    param_hints = {k: v for k, v in hints.items() if k not in ("self", "return")}
    return len(param_hints) > 0
