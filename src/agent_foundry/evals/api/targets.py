"""HTTP routes for the ``/targets`` resource.

Exposes the application's registered :class:`AICallRegistry` as a
read-only listing. The registry itself is injected via the
:func:`get_registry` dependency — production wiring overrides it with
the live registry at app construction time; tests override it with a
fixture-built one.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from agent_foundry.evals.api.schemas import TargetSpec, target_spec_from_ai_call
from agent_foundry.evals.registry import AICallRegistry

router = APIRouter()


def get_registry() -> AICallRegistry:
    """Dependency placeholder for the application's registered targets.

    Bound at app-construction time via ``app.dependency_overrides``;
    calling it directly raises to surface unwired tests early.
    """
    raise RuntimeError("get_registry was not bound — construct the app via create_app(registry)")


@router.get("/targets", response_model=list[TargetSpec])
def list_targets(
    registry: Annotated[AICallRegistry, Depends(get_registry)],
) -> list[TargetSpec]:
    """Return every target registered with the running application."""
    return [target_spec_from_ai_call(name, call) for name, call in registry]


@router.get("/targets/{name}", response_model=TargetSpec)
def get_target(
    name: str,
    registry: Annotated[AICallRegistry, Depends(get_registry)],
) -> TargetSpec:
    """Return the target registered under ``name``, or 404 if absent."""
    if name not in registry:
        raise HTTPException(status_code=404, detail=f"No target named {name!r}")
    return target_spec_from_ai_call(name, registry.get(name))
