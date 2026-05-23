"""FastAPI application factory for the eval API.

Two entry points:

- :func:`create_app` — explicit construction with a supplied registry.
  Used by tests and any host that wants programmatic control.
- :func:`get_app` — factory that reads ``agent_foundry.config`` from
  the current working directory and builds an app bound to the
  declared registry. Run with ``uvicorn --factory
  agent_foundry.evals.api.app:get_app``.

No module-level ``app`` instance — registry loading is deferred to
explicit construction so that importing this module is side-effect-free.
"""

from __future__ import annotations

from fastapi import FastAPI

from agent_foundry.evals.api.config import load_config
from agent_foundry.evals.api.registry_loader import load_registry
from agent_foundry.evals.api.targets import get_registry, router
from agent_foundry.evals.registry import AICallRegistry


def create_app(registry: AICallRegistry) -> FastAPI:
    """Build a FastAPI app bound to ``registry``."""
    app = FastAPI(title="Agent Foundry Eval API")
    app.include_router(router)
    app.dependency_overrides[get_registry] = lambda: registry
    return app


def get_app() -> FastAPI:
    """Factory for ``uvicorn --factory`` — reads config + loads registry."""
    config = load_config()
    registry = load_registry(config.registry)
    return create_app(registry)
