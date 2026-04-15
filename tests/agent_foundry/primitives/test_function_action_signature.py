"""Tests for FunctionAction.function signature evolution (CS7 Plan 2, Task A.3).

The plan evolves ``FunctionAction.function`` to carry the contract
``function(state: I, run_ctx: AgentRunContext) -> O``. During Plan 2 migration,
single-argument callables ``function(state: I) -> O`` remain accepted at
construct time (the compiler's arity probe handles invocation differences).

Phase B Task B.1 Step 5 will tighten the annotation to
``Callable[[I, "AgentRunContext"], BaseModel]`` via a forward reference and
``model_rebuild`` finalizer; this test file pins the A.3 baseline (both
arities accepted by the Pydantic model).
"""

from __future__ import annotations

from pydantic import BaseModel

from agent_foundry.orchestration.run_context import AgentRunContext
from agent_foundry.primitives.models import FunctionAction


class InputModel(BaseModel):
    pass


class OutputModel(BaseModel):
    pass


def test_function_action_accepts_two_arg_callable():
    def fn(state: InputModel, ctx: AgentRunContext) -> OutputModel:
        return OutputModel()

    action = FunctionAction[InputModel, OutputModel](function=fn)
    assert action.function is fn


def test_function_action_still_accepts_one_arg_callable_back_compat():
    # Back-compat: Plan 2 keeps the compiler tolerant of 1-arg callables
    # during migration (see compiler arity-probe in G.1).
    action = FunctionAction[InputModel, OutputModel](function=lambda s: OutputModel())
    assert callable(action.function)
