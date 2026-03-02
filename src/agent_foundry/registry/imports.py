"""Import resolution for capability implementation pointers."""

import importlib
from collections.abc import Callable
from typing import Any

from agent_foundry.registry.errors import CapabilityImportError
from agent_foundry.registry.spec import CapabilitySpec, ImplementationPointer

FF_CAPABILITY_IMPORTS = True


def import_capability_class(pointer: ImplementationPointer) -> Any | None:
    """Resolve an implementation pointer to a Python class.

    Args:
        pointer: The implementation pointer with module and class_name.

    Returns:
        The resolved class, or None if FF_CAPABILITY_IMPORTS is off.

    Raises:
        CapabilityImportError: If the module or class cannot be imported.
    """
    if not FF_CAPABILITY_IMPORTS:
        return None

    try:
        module = importlib.import_module(pointer.module)
    except ImportError as e:
        raise CapabilityImportError(
            message=f"Cannot import module '{pointer.module}': {e}",
            pointer=pointer,
        ) from e

    try:
        cls = getattr(module, pointer.class_name)
    except AttributeError as e:
        raise CapabilityImportError(
            message=f"Module '{pointer.module}' has no class '{pointer.class_name}'",
            pointer=pointer,
        ) from e

    return cls


def resolve_handler_callable(
    pointer: ImplementationPointer,
    spec: CapabilitySpec,
) -> Callable[[dict[str, Any]], dict[str, Any]] | None:
    """Import class, instantiate with spec, return the bound method.

    Args:
        pointer: The implementation pointer with module, class_name, and method.
        spec: The capability spec, passed to the handler constructor.

    Returns:
        A callable handler, or None if FF_CAPABILITY_IMPORTS is off.

    Raises:
        CapabilityImportError: If import, instantiation, or method resolution fails.
    """
    cls = import_capability_class(pointer)
    if cls is None:
        return None

    try:
        instance = cls(spec)
    except Exception as e:
        raise CapabilityImportError(
            message=f"Cannot instantiate '{pointer.class_name}' from '{pointer.module}': {e}",
            pointer=pointer,
        ) from e

    method_name = pointer.method
    if not hasattr(instance, method_name):
        raise CapabilityImportError(
            message=f"'{pointer.class_name}' has no method '{method_name}'",
            pointer=pointer,
        )

    handler = getattr(instance, method_name)
    if not callable(handler):
        raise CapabilityImportError(
            message=f"'{pointer.class_name}.{method_name}' is not callable",
            pointer=pointer,
        )

    return handler
