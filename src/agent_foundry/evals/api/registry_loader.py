"""Resolve the ``module:attribute`` spec from the config into a live registry.

The spec string comes from ``agent_foundry.config``'s ``registry`` key
and identifies where the application's :class:`AICallRegistry`
instance lives in its own Python package. This module imports that
module and pulls out the named attribute. Errors are reported as
distinct exception types so callers can render targeted messages.
"""

from __future__ import annotations

import importlib

from agent_foundry.evals.registry import AICallRegistry


class InvalidRegistrySpecError(ValueError):
    """Raised when the registry spec is not a ``module:attribute`` string."""


class RegistryModuleImportError(ImportError):
    """Raised when the declared module cannot be imported."""


class RegistryAttributeError(AttributeError):
    """Raised when the named attribute is missing from the imported module."""


def load_registry(spec: str) -> AICallRegistry:
    """Resolve ``spec`` (``"module.path:VAR"``) and return the registry instance.

    Raises :class:`InvalidRegistrySpecError` if ``spec`` is malformed,
    :class:`RegistryModuleImportError` if the module cannot be imported,
    :class:`RegistryAttributeError` if the attribute is missing, and
    ``TypeError`` if the attribute is not an :class:`AICallRegistry`.
    """
    if ":" not in spec:
        raise InvalidRegistrySpecError(f"Registry spec must be 'module:attribute', got {spec!r}")
    module_name, _, attr_name = spec.partition(":")
    if not module_name or not attr_name:
        raise InvalidRegistrySpecError(f"Registry spec must be 'module:attribute', got {spec!r}")

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise RegistryModuleImportError(
            f"Could not import registry module {module_name!r}: {exc}"
        ) from exc

    if not hasattr(module, attr_name):
        raise RegistryAttributeError(f"Module {module_name!r} has no attribute {attr_name!r}")

    registry = getattr(module, attr_name)
    if not isinstance(registry, AICallRegistry):
        raise TypeError(
            f"{module_name}:{attr_name} is {type(registry).__name__}, expected AICallRegistry"
        )
    return registry
