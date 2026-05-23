"""FastAPI application factory for the eval API.

:func:`create_app` is the explicit construction entry — used by tests
with a fixture-built registry and by ``__main__`` after the config
loader resolves the application's registry.

No module-level ``app`` instance — registry loading is deferred to
explicit construction so that importing this module is side-effect-free.
"""

from __future__ import annotations

from fastapi import FastAPI

from agent_foundry.evals.api.targets import get_registry, router
from agent_foundry.evals.registry import AICallRegistry


def create_app(registry: AICallRegistry) -> FastAPI:
    """Build a FastAPI app bound to ``registry``."""
    app = FastAPI(title="Agent Foundry Eval API")
    app.include_router(router)
    app.dependency_overrides[get_registry] = lambda: registry
    return app
