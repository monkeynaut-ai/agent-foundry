"""Import resolution for capability implementation pointers."""

import importlib
from typing import Any

from agent_foundry.registry.errors import CapabilityImportError
from agent_foundry.registry.spec import ImplementationPointer

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
