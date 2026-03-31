"""LangGraph connector for TypedAgent instances.

Bridges the gap between typed agents (which know nothing about dicts or
LangGraph) and the LangGraph execution model (which passes state as
``dict[str, Any]``).

Input mapping:
    For each parameter in the agent's ``__call__`` signature, the connector
    extracts ``state[param_name]``.  If the parameter type is a ``BaseModel``
    subclass, the value is validated via ``model_validate()``.  Primitives
    and type aliases are passed through directly.

Output mapping:
    The agent returns a Pydantic output model.  The connector calls
    ``model_dump()`` to produce a flat dict that LangGraph merges into state.
"""

import inspect
import logging
from collections.abc import Callable
from typing import Any, get_type_hints

from pydantic import BaseModel

logger = logging.getLogger(__name__)


def make_typed_connector(agent: object) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Wrap a typed agent into a ``dict -> dict`` callable for LangGraph.

    Args:
        agent: An object satisfying the TypedAgent protocol.

    Returns:
        A callable that accepts a LangGraph state dict and returns an
        updated state dict.
    """
    hints = get_type_hints(type(agent).__call__)
    param_specs = {name: hint for name, hint in hints.items() if name not in ("self", "return")}
    return_type = hints.get("return")

    if not param_specs:
        raise TypeError(
            f"{type(agent).__name__}.__call__ has no typed parameters. "
            "TypedAgent requires at least one typed parameter."
        )

    if return_type is None or not (
        isinstance(return_type, type) and issubclass(return_type, BaseModel)
    ):
        raise TypeError(
            f"{type(agent).__name__}.__call__ must return a BaseModel subclass, "
            f"got {return_type!r}."
        )

    # Determine which parameters have defaults (and are therefore optional)
    sig = inspect.signature(type(agent).__call__)
    defaults: dict[str, Any] = {}
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        if param.default is not inspect.Parameter.empty:
            defaults[name] = param.default

    required_params = {name for name in param_specs if name not in defaults}

    def connected(state: dict[str, Any]) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        for name, hint in param_specs.items():
            if name not in state:
                if name in required_params:
                    raise KeyError(
                        f"TypedAgent {type(agent).__name__} requires '{name}' "
                        f"but it is missing from state. Available keys: {sorted(state.keys())}"
                    )
                # Optional parameter not in state — skip, let the default apply
                continue
            value = state[name]
            if isinstance(hint, type) and issubclass(hint, BaseModel):
                kwargs[name] = hint.model_validate(value)
            else:
                kwargs[name] = value

        output = agent(**kwargs)  # type: ignore[operator]
        return output.model_dump()

    return connected
