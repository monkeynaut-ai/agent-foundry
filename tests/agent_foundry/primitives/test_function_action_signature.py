"""Tests for FunctionAction.function signature.

``FunctionAction.function`` carries the contract
``function(state: I) -> O``. Product code that needs run-scoped state
(emit domain events, read artifacts_dir, check cancellation) imports
accessors from ``agent_foundry.runtime`` — no ``run_ctx`` parameter
leaks into product signatures.

The annotation is ``Callable[[Any], BaseModel]`` (``Any`` on the
state slot is a pragmatic compromise: Pydantic cannot resolve
``TypeVar I`` at ``model_rebuild`` time).
"""

from __future__ import annotations

from pydantic import BaseModel

from agent_foundry.primitives.models import FunctionAction


class InputModel(BaseModel):
    pass


class OutputModel(BaseModel):
    pass


def test_function_action_accepts_one_arg_callable():
    def fn(state: InputModel) -> OutputModel:
        return OutputModel()

    action = FunctionAction[InputModel, OutputModel](function=fn)
    assert action.function is fn


def test_function_action_accepts_lambda():
    action = FunctionAction[InputModel, OutputModel](function=lambda s: OutputModel())
    assert callable(action.function)


# -- annotation-resolvability --


def test_function_action_function_annotation_resolves():
    """FunctionAction's annotation must resolve cleanly.

    Pins that ``model_fields["function"]`` can be introspected without
    raising.
    """
    field = FunctionAction[InputModel, OutputModel].model_fields["function"]
    assert field is not None


# -- runtime.emit threading through compiled node --
#
# Pins the end-to-end contract that a FunctionAction whose function
# calls ``runtime.emit`` inside a running plan reaches the active
# ``AgentRunContext``'s lifecycle writer.


def test_function_action_callable_can_emit_via_runtime(tmp_path):
    import asyncio

    from langgraph.graph import StateGraph

    from agent_foundry import runtime
    from agent_foundry.compiler.primitive_compiler import _compile_function_action
    from agent_foundry.orchestration.lifecycle_writer import LifecycleWriter
    from agent_foundry.orchestration.run_context import (
        AgentRunContext,
        current_run_context,
    )

    captured_events: list[tuple[str, dict]] = []

    class _RecordingWriter(LifecycleWriter):
        def append(self, event_type, **fields):
            captured_events.append(("platform", {"type": event_type.value, **fields}))

        def append_run_event(self, kind, **fields):
            captured_events.append(("domain", {"kind": kind, **fields}))

        def close(self) -> None:
            return None

    def fn(state: InputModel) -> OutputModel:
        runtime.emit("probe_fired", detail="ok")
        return OutputModel()

    action = FunctionAction[InputModel, OutputModel](function=fn)

    graph = StateGraph(dict)
    node_id, _ = _compile_function_action(graph, action, prefix="fa", gate_ids=[])

    run_ctx = AgentRunContext(
        run_id="run-fn-compile",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=_RecordingWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )

    token = current_run_context.set(run_ctx)
    try:
        node_fn = graph.nodes[node_id].runnable  # type: ignore[attr-defined]
        node_fn.invoke({})
    finally:
        current_run_context.reset(token)

    domain_events = [e for kind, e in captured_events if kind == "domain"]
    assert any(e["kind"] == "probe_fired" and e.get("detail") == "ok" for e in domain_events)
