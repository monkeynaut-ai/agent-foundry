"""Import resolution for role implementation pointers."""

import importlib
from collections.abc import Callable
from typing import Any

from agent_foundry.registry.errors import RoleImportError
from agent_foundry.registry.spec import ImplementationPointer, RoleSpec

FF_CAPABILITY_IMPORTS = True


def import_role_class(pointer: ImplementationPointer) -> Any | None:
    """Resolve an implementation pointer to a Python class.

    Args:
        pointer: The implementation pointer with module and class_name.

    Returns:
        The resolved class, or None if FF_CAPABILITY_IMPORTS is off.

    Raises:
        RoleImportError: If the module or class cannot be imported.
    """
    if not FF_CAPABILITY_IMPORTS:
        return None

    try:
        module = importlib.import_module(pointer.module)
    except ImportError as e:
        raise RoleImportError(
            message=f"Cannot import module '{pointer.module}': {e}",
            pointer=pointer,
        ) from e

    try:
        cls = getattr(module, pointer.class_name)
    except AttributeError as e:
        raise RoleImportError(
            message=f"Module '{pointer.module}' has no class '{pointer.class_name}'",
            pointer=pointer,
        ) from e

    return cls


def resolve_handler_callable(
    pointer: ImplementationPointer,
    spec: RoleSpec,
) -> Callable[[dict[str, Any]], dict[str, Any]] | None:
    """Import class, instantiate with spec, return the bound method.

    Args:
        pointer: The implementation pointer with module, class_name, and method.
        spec: The role spec, passed to the handler constructor.

    Returns:
        A callable handler, or None if FF_CAPABILITY_IMPORTS is off.

    Raises:
        RoleImportError: If import, instantiation, or method resolution fails.
    """
    cls = import_role_class(pointer)
    if cls is None:
        return None

    try:
        instance = cls(spec)
    except Exception as e:
        raise RoleImportError(
            message=f"Cannot instantiate '{pointer.class_name}' from '{pointer.module}': {e}",
            pointer=pointer,
        ) from e

    method_name = pointer.method
    if not hasattr(instance, method_name):
        raise RoleImportError(
            message=f"'{pointer.class_name}' has no method '{method_name}'",
            pointer=pointer,
        )

    handler = getattr(instance, method_name)
    if not callable(handler):
        raise RoleImportError(
            message=f"'{pointer.class_name}.{method_name}' is not callable",
            pointer=pointer,
        )

    return handler  # type: ignore[return-value]


def resolve_typed_handler(
    pointer: ImplementationPointer,
    spec: RoleSpec,
    node_config: dict[str, Any],
) -> Any | None:
    """Import class, instantiate with spec and node_config, return the instance.

    Unlike :func:`resolve_handler_callable` which returns a bound method,
    this returns the instance itself so the connector can inspect its
    ``__call__`` signature.  Static configuration from the wiring plan
    (``NodeDef.config``) is passed to the constructor.

    Args:
        pointer: The implementation pointer with module and class_name.
        spec: The role spec, passed to the handler constructor as ``spec``.
        node_config: Static per-node config from the wiring plan, splatted
            into the constructor.

    Returns:
        The agent instance, or None if FF_CAPABILITY_IMPORTS is off.

    Raises:
        RoleImportError: If import or instantiation fails.
    """
    cls = import_role_class(pointer)
    if cls is None:
        return None

    # Filter out max_iterations — it's a compiler concern, not agent config
    config = {k: v for k, v in node_config.items() if k != "max_iterations"}

    try:
        instance = cls(spec=spec, **config)
    except Exception as e:
        raise RoleImportError(
            message=f"Cannot instantiate '{pointer.class_name}' from '{pointer.module}': {e}",
            pointer=pointer,
        ) from e

    return instance
