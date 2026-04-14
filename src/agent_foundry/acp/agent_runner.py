"""Container executor for AgentAction — runs an agent in a Docker container.

This is the platform-provided container executor. Products pass it (or a
substitute) as the ``executor`` field on an ``AgentAction``:

    action = AgentAction[...](
        ...,
        executor=run_agent_in_container,
    )

The real implementation lands in Plan 2 of CS7. Plan 1 establishes only
the function signature so products can wire it up and the compiler has
a callable to invoke. The Plan 1 body raises ``NotImplementedError`` —
any real invocation before Plan 2 fails loudly. Tests that exercise
the compiler supply their own executor directly on the ``AgentAction``
(no monkeypatching — ``executor`` is an explicit field).

Design note: the executor returns an instance of the ``AgentAction``'s
output type ``O``, not a wrapper result object. This mirrors
``FunctionAction.function``: the thing the compiler calls returns ``O``
or raises. Diagnostics (exit codes, stdout lines) flow to the lifecycle
tracker in Plan 2, not through the return value.
"""

from __future__ import annotations

from pydantic import BaseModel

from agent_foundry.primitives.models import AgentAction


def run_agent_in_container(
    *,
    primitive: AgentAction,
    prompt: str,
) -> BaseModel:
    """Run the agent described by ``primitive`` with ``prompt``.

    The runner takes the full ``AgentAction`` primitive so it can read
    all configuration (instructions provider, response channel, container
    settings, reuse policy) without the compiler having to forward each
    field individually.

    Returns an instance of the primitive's output type ``O``. The caller
    is expected to merge it into graph state.

    Raises:
        NotImplementedError: Always, until Plan 2 lands.
    """
    raise NotImplementedError(
        "run_agent_in_container is a stub until CS7 Plan 2 lands. "
        "Tests exercising the AgentAction compiler should supply their own "
        "executor callable on the AgentAction rather than using this stub."
    )
