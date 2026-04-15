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


# -- CS7 Plan 2 Task B.1 Step 5: annotation-resolvability --


def test_function_action_function_annotation_resolves():
    """After B.1 Step 5, FunctionAction's forward-ref to AgentRunContext
    must resolve cleanly. This pins that `model_fields["function"]` can
    be introspected without raising a NameError for ``AgentRunContext``.
    """
    # Triggers schema materialisation; if the forward ref is broken
    # (e.g. missing model_rebuild after orchestration import), this raises.
    field = FunctionAction[InputModel, OutputModel].model_fields["function"]
    assert field is not None


# -- CS7 Plan 2 Task B.1: run_ctx threading through compiled node --
#
# Task B.1 tightens the annotation only; G.1 rewires the compiler to call
# ``fn(state, run_ctx)`` for 2-arg callables. This test is expected RED
# until G.1 lands — it pins the end-to-end contract that a FunctionAction
# whose function takes ``(state, run_ctx)`` receives the ContextVar's
# current AgentRunContext at invocation time.


def test_function_action_two_arg_callable_receives_run_ctx_from_compiled_node(
    tmp_path,
):
    import asyncio

    from langgraph.graph import StateGraph

    from agent_foundry.compiler.primitive_compiler import _compile_function_action
    from agent_foundry.orchestration.run_context import (
        AgentRunContext,
        NoOpLifecycleWriter,
        current_run_context,
    )

    captured: dict[str, object] = {}

    def fn(state: InputModel, ctx: AgentRunContext) -> OutputModel:
        captured["ctx"] = ctx
        captured["state"] = state
        return OutputModel()

    action = FunctionAction[InputModel, OutputModel](function=fn)

    graph = StateGraph(dict)
    node_id, _ = _compile_function_action(graph, action, prefix="fa", gate_ids=[])

    run_ctx = AgentRunContext(
        run_id="run-b1-compile",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )

    # Compiled node reads the ContextVar at invocation time.
    token = current_run_context.set(run_ctx)
    try:
        node_fn = graph.nodes[node_id].runnable  # type: ignore[attr-defined]
        node_fn.invoke({})
    finally:
        current_run_context.reset(token)

    assert captured["ctx"] is run_ctx
