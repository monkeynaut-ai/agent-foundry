"""Resolve a runner ``module:Class`` spec into a live :class:`Runner` instance.

Both the CLI and the (future) ``/runs`` API endpoint use this loader
to materialize the configured execution backend. Neither needs to
statically import a concrete runner — the import is deferred to
:func:`importlib.import_module` here, so the rest of the eval package
depends only on the :class:`Runner` Protocol from the model layer.

The default spec points at :class:`PydanticEvalsRunner`; callers can
override (e.g. via a future config field or CLI flag) when alternate
backends land.
"""

from __future__ import annotations

import importlib

from agent_foundry.evals.models import Runner

DEFAULT_RUNNER_SPEC = "agent_foundry.evals.runners.pydantic_evals:PydanticEvalsRunner"


class InvalidRunnerSpecError(ValueError):
    """Raised when the runner spec is not a ``module:Class`` string."""


class RunnerModuleImportError(ImportError):
    """Raised when the declared module cannot be imported."""


class RunnerAttributeError(AttributeError):
    """Raised when the named attribute is missing from the imported module."""


def load_runner(spec: str = DEFAULT_RUNNER_SPEC) -> Runner:
    """Resolve ``spec`` (``"module.path:Class"``) and return an instance.

    The class is instantiated with no arguments; the resulting object
    must conform to the :class:`Runner` Protocol.

    Raises :class:`InvalidRunnerSpecError` if ``spec`` is malformed,
    :class:`RunnerModuleImportError` if the module cannot be imported,
    :class:`RunnerAttributeError` if the attribute is missing, and
    ``TypeError`` if the resolved class doesn't satisfy
    :class:`Runner`.
    """
    if ":" not in spec:
        raise InvalidRunnerSpecError(f"Runner spec must be 'module:Class', got {spec!r}")
    module_name, _, attr_name = spec.partition(":")
    if not module_name or not attr_name:
        raise InvalidRunnerSpecError(f"Runner spec must be 'module:Class', got {spec!r}")

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise RunnerModuleImportError(
            f"Could not import runner module {module_name!r}: {exc}"
        ) from exc

    if not hasattr(module, attr_name):
        raise RunnerAttributeError(f"Module {module_name!r} has no attribute {attr_name!r}")

    runner_class = getattr(module, attr_name)
    instance = runner_class()
    if not isinstance(instance, Runner):
        raise TypeError(
            f"{module_name}:{attr_name} does not satisfy Runner Protocol (missing 'run' method)"
        )
    return instance
