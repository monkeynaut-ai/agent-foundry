"""Primitive compiler: translates typed primitive graphs into executable LangGraph."""

from __future__ import annotations

import asyncio
import contextlib
import signal
import threading
import uuid
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict, cast

from langgraph._internal._runnable import RunnableCallable
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, ValidationError

from agent_foundry.primitives.errors import PrimitiveCompilationError
from agent_foundry.primitives.models import (
    AgentAction,
    Conditional,
    FunctionAction,
    GateAction,
    Loop,
    Primitive,
    Retry,
    Sequence,
    get_type_args,
)
from agent_foundry.primitives.plan import PrimitivePlan
from agent_foundry.responders.protocol import ResponderProvider

# -- Compiler registry --

type _CompilerStorage = Callable[[StateGraph, Any, str, list[str]], tuple[str, str]]

_compiler_registry: dict[type[Primitive], _CompilerStorage] = {}


def register_compiler[P: Primitive](
    prim_type: type[P],
    compiler_fn: Callable[[StateGraph, P, str, list[str]], tuple[str, str]],
) -> None:
    """Register a compiler function for a primitive type.

    The function's primitive parameter type is checked against ``prim_type``
    at the call site, so ``register_compiler(Sequence, _compile_sequence)``
    statically verifies ``_compile_sequence`` accepts ``Sequence``.

    Raises ``ValueError`` if a compiler is already registered for
    ``prim_type``. This guards against accidental override of core
    compilers by extension code or import-order bugs.
    """
    if prim_type in _compiler_registry:
        raise ValueError(f"Compiler already registered for {prim_type.__name__}")
    _compiler_registry[prim_type] = cast(_CompilerStorage, compiler_fn)


# -- Helpers --


def _derive_state_type(input_type: type[BaseModel], output_type: type[BaseModel]) -> type:
    """Derive a TypedDict(total=False) from the union of I and O model fields."""
    fields: dict[str, Any] = {}
    for model in (input_type, output_type):
        for name in model.model_fields:
            fields[name] = Any
    return TypedDict("PrimitiveState", fields, total=False)  # type: ignore[call-overload]


def _validate_boundary(
    state: dict[str, Any], model_type: type[BaseModel], node_id: str
) -> dict[str, Any]:
    """Validate state at a primitive boundary via Pydantic model construction."""
    try:
        model_type.model_validate(state)
    except ValidationError as e:
        raise PrimitiveCompilationError(
            f"Boundary validation failed at {node_id}: {e}",
            primitive_type=node_id,
        ) from e
    return state


def _scope_in(parent_state: dict[str, Any], child_input_type: type[BaseModel]) -> dict[str, Any]:
    """Scope parent state down to child's input fields. Validates required fields."""
    fields = set(child_input_type.model_fields.keys())
    scoped = {k: v for k, v in parent_state.items() if k in fields}
    try:
        child_input_type.model_validate(scoped)
    except ValidationError as e:
        raise PrimitiveCompilationError(f"Scope-in failed: {e}", primitive_type="scope_in") from e
    return scoped


def _scope_out(child_result: dict[str, Any], child_output_type: type[BaseModel]) -> dict[str, Any]:
    """Scope child result down to output fields. Validates output completeness."""
    fields = set(child_output_type.model_fields.keys())
    scoped = {k: v for k, v in child_result.items() if k in fields}
    try:
        child_output_type.model_validate(scoped)
    except ValidationError as e:
        raise PrimitiveCompilationError(f"Scope-out failed: {e}", primitive_type="scope_out") from e
    return scoped


def _compile_node(
    graph: StateGraph, prim: Primitive, prefix: str, gate_ids: list[str]
) -> tuple[str, str]:
    """Compile a primitive into graph nodes/edges. Returns (entry_id, exit_id)."""
    # Parameterized generics (e.g., FunctionAction[A, B]) create new classes.
    # Walk MRO to find the registered base type.
    prim_type = type(prim)
    for cls in prim_type.__mro__:
        compiler = _compiler_registry.get(cls)
        if compiler is not None:
            return compiler(graph, prim, prefix, gate_ids)
    raise PrimitiveCompilationError(
        f"No compiler registered for {prim_type.__name__}",
        primitive_type=prim_type.__name__,
    )


# -- Entry points --


def compile_primitive(plan: PrimitivePlan) -> Any:
    """Compile a PrimitivePlan into an executable LangGraph."""
    plan.validate()
    root = plan.root
    root_in, root_out = get_type_args(root)
    state_type = _derive_state_type(root_in, root_out)
    graph = StateGraph(state_type)

    gate_ids: list[str] = []
    entry_id, exit_id = _compile_node(graph, root, "root", gate_ids)
    graph.set_entry_point(entry_id)
    graph.add_edge(exit_id, END)

    compile_kwargs: dict[str, Any] = {}
    if gate_ids:
        from langgraph.checkpoint.memory import MemorySaver

        compile_kwargs["checkpointer"] = MemorySaver()
        compile_kwargs["interrupt_before"] = gate_ids

    return graph.compile(**compile_kwargs)


def run_primitive_plan_sync(
    plan: PrimitivePlan,
    initial_state: BaseModel | None = None,
    config: dict[str, Any] | None = None,
) -> BaseModel:
    """Legacy synchronous entry point (pre-Plan 2).

    Preserved so F0 / F.3 call sites continue to work during the CS7
    Plan 2 migration. Emits a ``DeprecationWarning``; prefer the new
    async :func:`run_primitive_plan` which builds an
    :class:`AgentRunContext` and wires lifecycle + registry teardown.
    """
    warnings.warn(
        "run_primitive_plan_sync is deprecated; migrate to the async "
        "run_primitive_plan entry point (CS7 Plan 2).",
        DeprecationWarning,
        stacklevel=2,
    )
    _, root_out = get_type_args(plan.root)
    graph = compile_primitive(plan)

    input_dict = initial_state.model_dump() if initial_state is not None else {}
    result_dict = graph.invoke(input_dict, config=config or {})
    return root_out.model_validate(result_dict)


async def run_primitive_plan(
    plan: PrimitivePlan,
    *,
    initial_state: BaseModel,
    artifacts_dir: Path,
    workspace_volume: str,
    base_image_tag: str,
    responder_provider: ResponderProvider,
    run_id: str | None = None,
) -> BaseModel:
    """Execute a :class:`PrimitivePlan` with full CS7 Plan 2 wiring.

    Bootstraps the run artifacts directory, builds a
    :class:`LifecycleWriter` and :class:`AgentContainerRegistry`,
    constructs the :class:`AgentRunContext`, installs cooperative
    SIGINT/SIGTERM handlers (main thread only), sets the
    ``current_run_context`` ContextVar, and invokes the compiled graph
    via :meth:`ainvoke`.

    Teardown (``finally``) always runs: the registry is shut down,
    ``summary.txt`` is rendered, and the ContextVar + signal handlers
    are reset — even on cancel or agent failure.
    """
    # Deferred imports — orchestration depends on compiler via the
    # run-context ContextVar, so we resolve these at call time rather
    # than at module import to keep the dependency graph acyclic.
    from agent_foundry.orchestration.artifacts import bootstrap_run_artifacts
    from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
    from agent_foundry.orchestration.lifecycle_writer import LifecycleWriter
    from agent_foundry.orchestration.registry import AgentContainerRegistry
    from agent_foundry.orchestration.run_context import (
        AgentRunContext,
        current_run_context,
    )
    from agent_foundry.orchestration.summary import render_summary

    resolved_run_id = run_id if run_id is not None else uuid.uuid4().hex

    run_dir = bootstrap_run_artifacts(
        artifacts_dir=artifacts_dir,
        run_id=resolved_run_id,
        workspace_volume=workspace_volume,
        base_image_tag=base_image_tag,
    )

    _, root_out = get_type_args(plan.root)

    lifecycle = LifecycleWriter(run_id=resolved_run_id, path=run_dir / "lifecycle.jsonl")
    import os as _os

    oauth_token = _os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    # Inject role instructions + wait for container health only when we
    # have a real OAuth token — unit tests that wire a fake driver skip
    # this path and keep their pre-Plan-2 registry shape. The base image
    # declares a HEALTHCHECK that polls for ``/tmp/.container-ready``;
    # the entrypoint touches that marker after all setup completes.
    registry = AgentContainerRegistry(
        workspace_volume=workspace_volume,
        base_image_tag=base_image_tag,
        oauth_token=oauth_token,
        inject_instructions=oauth_token is not None,
        wait_for_health=oauth_token is not None,
    )
    cancel = asyncio.Event()

    run_ctx = AgentRunContext(
        run_id=resolved_run_id,
        artifacts_dir=run_dir,
        container_registry=registry,
        responder_provider=responder_provider,
        lifecycle_writer=lifecycle,
        cancel_event=cancel,
        env={"CLAUDE_CODE_OAUTH_TOKEN": oauth_token} if oauth_token else {},
    )

    # Install SIGINT/SIGTERM handlers — main thread only. Signal-handler
    # installation from a non-main thread raises ``ValueError`` on
    # POSIX; guard explicitly so we degrade cleanly in worker threads
    # (tests, notebook kernels) rather than crashing the run.
    loop = asyncio.get_running_loop()
    installed_signals: list[int] = []
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, cancel.set)
                installed_signals.append(sig)
            except (NotImplementedError, RuntimeError, ValueError):
                # NotImplementedError on Windows; RuntimeError/ValueError
                # on loops that refuse signal handlers (uvloop edge
                # cases, nested loops). Cancellation still works via
                # direct ``cancel_event.set()`` from callers.
                pass

    token = current_run_context.set(run_ctx)
    lifecycle.append({"type": LifecycleEvent.RUN_STARTED.value, "run_id": resolved_run_id})

    try:
        graph = compile_primitive(plan)
        result_dict = await graph.ainvoke(initial_state.model_dump())
        lifecycle.append({"type": LifecycleEvent.RUN_ENDED.value, "run_id": resolved_run_id})
        return root_out.model_validate(result_dict)
    finally:
        try:
            await registry.shutdown_all()
        except Exception:
            logger_msg = "registry.shutdown_all raised during teardown"
            import logging

            logging.getLogger(__name__).warning(logger_msg, exc_info=True)
        try:
            render_summary(run_dir)
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "render_summary raised during teardown", exc_info=True
            )
        for sig in installed_signals:
            with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
                loop.remove_signal_handler(sig)
        current_run_context.reset(token)
        lifecycle.close()


# -- Per-type compilers --


def _compile_function_action(
    graph: StateGraph, action: FunctionAction, prefix: str, gate_ids: list[str]
) -> tuple[str, str]:
    import inspect

    node_id = prefix
    input_type, _ = get_type_args(action)
    # ``FunctionAction.function`` is annotated ``(state, run_ctx) -> O`` post
    # Task B.1. Task G.1 widens the arity probe so 2-arg callables receive
    # the current ``AgentRunContext`` pulled from the ``current_run_context``
    # ContextVar at invocation time; 1-arg and 0-arg callables remain
    # supported for migration.
    fn = cast(Callable[..., BaseModel], action.function)
    arity = len(inspect.signature(fn).parameters)

    def node_fn(state: dict[str, Any]) -> dict[str, Any]:
        # Resolve the current ``AgentRunContext`` once — we need it to
        # emit ``FUNCTION_ACTION_STARTED`` / ``_COMPLETED`` / ``_FAILED``
        # lifecycle events regardless of callable arity. When no run is
        # in progress (legacy ``run_primitive_plan_sync`` + unit tests
        # that compile nodes without a run context), skip event emission
        # so the compiler remains usable outside Plan 2's run path.
        from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
        from agent_foundry.orchestration.run_context import (
            current_run_context,
        )

        ctx_opt = current_run_context.get()
        if ctx_opt is not None:
            ctx_opt.lifecycle_writer.append(
                {
                    "type": LifecycleEvent.FUNCTION_ACTION_STARTED,
                    "node_id": node_id,
                }
            )
        try:
            if arity == 0:
                result = fn()
            else:
                _validate_boundary(state, input_type, node_id)
                model_input = input_type.model_validate(state)
                if arity >= 2:
                    if ctx_opt is None:
                        from agent_foundry.orchestration.run_context import (
                            require_current_run_context,
                        )

                        run_ctx = require_current_run_context()
                    else:
                        run_ctx = ctx_opt
                    result = fn(model_input, run_ctx)
                else:
                    result = fn(model_input)
        except Exception as exc:
            if ctx_opt is not None:
                ctx_opt.lifecycle_writer.append(
                    {
                        "type": LifecycleEvent.FUNCTION_ACTION_FAILED,
                        "node_id": node_id,
                        "reason": str(exc),
                    }
                )
            raise
        if ctx_opt is not None:
            ctx_opt.lifecycle_writer.append(
                {
                    "type": LifecycleEvent.FUNCTION_ACTION_COMPLETED,
                    "node_id": node_id,
                }
            )
        return result.model_dump()

    graph.add_node(node_id, node_fn)
    return (node_id, node_id)


register_compiler(FunctionAction, _compile_function_action)


def _compile_sequence(
    graph: StateGraph,
    seq: Sequence,
    prefix: str,
    gate_ids: list[str],
) -> tuple[str, str]:
    seq_in, seq_out = get_type_args(seq)

    # Build subgraph state type from ALL step I/O types (not just Sequence I/O).
    # Intermediate types may have fields not in the Sequence's I or O that
    # LangGraph needs to carry between steps within the subgraph.
    all_types = [seq_in, seq_out]
    for step in seq.steps:
        step_in, step_out = get_type_args(step)
        all_types.extend([step_in, step_out])

    fields: dict[str, Any] = {}
    for model in all_types:
        for name in model.model_fields:
            fields[name] = Any
    sub_state_type = TypedDict("SeqState", fields, total=False)  # type: ignore[call-overload]
    sub_graph = StateGraph(sub_state_type)

    first_entry = None
    prev_exit = None
    for i, step in enumerate(seq.steps):
        child_prefix = f"{prefix}_step_{i}"
        entry, exit_ = _compile_node(sub_graph, step, child_prefix, gate_ids)
        if first_entry is None:
            first_entry = entry
        if prev_exit is not None:
            sub_graph.add_edge(prev_exit, entry)
        prev_exit = exit_
    assert first_entry is not None
    assert prev_exit is not None

    sub_graph.set_entry_point(first_entry)
    sub_graph.add_edge(prev_exit, END)
    compiled_sub = sub_graph.compile()

    # Wrapper node: scope-in → execute subgraph → scope-out
    node_id = f"{prefix}_seq"

    def seq_node(state: dict[str, Any]) -> dict[str, Any]:
        scoped_input = _scope_in(state, seq_in)
        result = compiled_sub.invoke(scoped_input)
        return _scope_out(result, seq_out)

    async def seq_node_async(state: dict[str, Any]) -> dict[str, Any]:
        scoped_input = _scope_in(state, seq_in)
        result = await compiled_sub.ainvoke(scoped_input)
        return _scope_out(result, seq_out)

    graph.add_node(node_id, RunnableCallable(seq_node, seq_node_async, name=node_id, trace=False))
    return (node_id, node_id)


register_compiler(Sequence, _compile_sequence)


def _compile_conditional(
    graph: StateGraph,
    cond: Conditional,
    prefix: str,
    gate_ids: list[str],
) -> tuple[str, str]:
    cond_in, cond_out = get_type_args(cond)

    # Build subgraph state from all branch I/O types
    all_types = [cond_in, cond_out]
    then_in, then_out = get_type_args(cond.then_branch)
    all_types.extend([then_in, then_out])
    if cond.else_branch is not None:
        else_in_t, else_out_t = get_type_args(cond.else_branch)
        all_types.extend([else_in_t, else_out_t])

    fields: dict[str, Any] = {}
    for model in all_types:
        for name in model.model_fields:
            fields[name] = Any
    sub_state_type = TypedDict("CondState", fields, total=False)  # type: ignore[call-overload]
    sub_graph = StateGraph(sub_state_type)

    router_id = f"{prefix}_router"
    merge_id = f"{prefix}_merge"

    then_entry, then_exit = _compile_node(sub_graph, cond.then_branch, f"{prefix}_then", gate_ids)

    if cond.else_branch is not None:
        else_entry, else_exit = _compile_node(
            sub_graph, cond.else_branch, f"{prefix}_else", gate_ids
        )
        targets = [then_entry, else_entry]
    else:
        targets = [then_entry, merge_id]

    condition_fn = cond.condition

    def router_fn(state: dict[str, Any]) -> str:
        model = cond_in.model_validate(state)
        if condition_fn(model):
            return then_entry
        if cond.else_branch is not None:
            return else_entry  # type: ignore[possibly-undefined]
        return merge_id

    sub_graph.add_node(router_id, lambda state: state)
    sub_graph.add_conditional_edges(router_id, router_fn, targets)

    sub_graph.add_node(merge_id, lambda state: state)
    sub_graph.add_edge(then_exit, merge_id)
    if cond.else_branch is not None:
        sub_graph.add_edge(else_exit, merge_id)  # type: ignore[possibly-undefined]

    sub_graph.set_entry_point(router_id)
    sub_graph.add_edge(merge_id, END)
    compiled_sub = sub_graph.compile()

    # Wrapper node: scope-in → execute subgraph → scope-out
    node_id = f"{prefix}_cond"

    def cond_node(state: dict[str, Any]) -> dict[str, Any]:
        # Pass full parent state — branches read what they need from accumulated state
        result = compiled_sub.invoke(dict(state))
        return _scope_out(result, cond_out)

    async def cond_node_async(state: dict[str, Any]) -> dict[str, Any]:
        result = await compiled_sub.ainvoke(dict(state))
        return _scope_out(result, cond_out)

    graph.add_node(node_id, RunnableCallable(cond_node, cond_node_async, name=node_id, trace=False))
    return (node_id, node_id)


register_compiler(Conditional, _compile_conditional)


def _compile_loop(
    graph: StateGraph,
    loop: Loop,
    prefix: str,
    gate_ids: list[str],
) -> tuple[str, str]:
    loop_in, loop_out = get_type_args(loop)
    body_in, body_out = get_type_args(loop.body)

    # Compile body subgraph — state includes loop I/O + body I/O for accumulated context
    all_types = [loop_in, loop_out, body_in, body_out]
    fields: dict[str, Any] = {}
    for model in all_types:
        for name in model.model_fields:
            fields[name] = Any
    body_state_type = TypedDict("LoopBodyState", fields, total=False)  # type: ignore[call-overload]
    body_graph = StateGraph(body_state_type)
    body_entry, body_exit = _compile_node(body_graph, loop.body, f"{prefix}_body", gate_ids)
    body_graph.set_entry_point(body_entry)
    body_graph.add_edge(body_exit, END)
    compiled_body = body_graph.compile()

    over_fn = loop.over
    item_key = loop.item_key
    max_iter = loop.max_iterations

    # Wrapper node: iterates, scoping in/out per iteration
    node_id = f"{prefix}_loop"

    def loop_node(state: dict[str, Any]) -> dict[str, Any]:
        model = loop_in.model_validate(state)
        items = over_fn(model)
        # Accumulated state — starts with full parent state, grows across iterations
        current_state = dict(state)

        for i, item in enumerate(items):
            if i >= max_iter:
                break
            # Inject item, then pass full accumulated state to body
            current_state[item_key] = item
            result = compiled_body.invoke(dict(current_state))
            # Merge body output back into accumulated state
            updates = _scope_out(result, body_out)
            current_state.update(updates)

        return _scope_out(current_state, loop_out)

    async def loop_node_async(state: dict[str, Any]) -> dict[str, Any]:
        model = loop_in.model_validate(state)
        items = over_fn(model)
        current_state = dict(state)

        for i, item in enumerate(items):
            if i >= max_iter:
                break
            current_state[item_key] = item
            result = await compiled_body.ainvoke(dict(current_state))
            updates = _scope_out(result, body_out)
            current_state.update(updates)

        return _scope_out(current_state, loop_out)

    graph.add_node(node_id, RunnableCallable(loop_node, loop_node_async, name=node_id, trace=False))
    return (node_id, node_id)


register_compiler(Loop, _compile_loop)


def _compile_retry(
    graph: StateGraph,
    retry: Retry,
    prefix: str,
    gate_ids: list[str],
) -> tuple[str, str]:
    retry_in, retry_out = get_type_args(retry)
    body_in, body_out = get_type_args(retry.body)

    # Compile body subgraph — state includes retry I/O + body I/O for accumulated context
    all_types = [retry_in, retry_out, body_in, body_out]
    fields: dict[str, Any] = {}
    for model in all_types:
        for name in model.model_fields:
            fields[name] = Any
    body_state_type = TypedDict("RetryBodyState", fields, total=False)  # type: ignore[call-overload]
    body_graph = StateGraph(body_state_type)
    body_entry, body_exit = _compile_node(body_graph, retry.body, f"{prefix}_body", gate_ids)
    body_graph.set_entry_point(body_entry)
    body_graph.add_edge(body_exit, END)
    compiled_body = body_graph.compile()

    until_fn = retry.until
    max_attempts = retry.max_attempts

    # Wrapper node: retry loop with scoped body execution
    node_id = f"{prefix}_retry"

    def retry_node(state: dict[str, Any]) -> dict[str, Any]:
        # Accumulated state — starts with full parent state
        current_state = dict(state)
        for _ in range(max_attempts):
            # Pass full accumulated state to body
            result = compiled_body.invoke(dict(current_state))
            current_state.update(_scope_out(result, body_out))
            # Check until condition
            model = retry_in.model_validate(current_state)
            if until_fn(model):
                break
        return _scope_out(current_state, retry_out)

    async def retry_node_async(state: dict[str, Any]) -> dict[str, Any]:
        current_state = dict(state)
        for _ in range(max_attempts):
            result = await compiled_body.ainvoke(dict(current_state))
            current_state.update(_scope_out(result, body_out))
            model = retry_in.model_validate(current_state)
            if until_fn(model):
                break
        return _scope_out(current_state, retry_out)

    graph.add_node(
        node_id, RunnableCallable(retry_node, retry_node_async, name=node_id, trace=False)
    )
    return (node_id, node_id)


register_compiler(Retry, _compile_retry)


def _compile_gate_action(
    graph: StateGraph,
    gate: GateAction,
    prefix: str,
    gate_ids: list[str],
) -> tuple[str, str]:
    gate_id = prefix

    def gate_node(state: dict[str, Any]) -> dict[str, Any]:
        return state  # interrupt_before pauses BEFORE this node

    graph.add_node(gate_id, gate_node)
    gate_ids.append(gate_id)
    return (gate_id, gate_id)


register_compiler(GateAction, _compile_gate_action)


def _compile_agent_action(
    graph: StateGraph,
    action: AgentAction,
    prefix: str,
    gate_ids: list[str],
) -> tuple[str, str]:
    node_id = prefix
    input_type, output_type = get_type_args(action)
    prompt_builder = action.prompt_builder
    executor = action.executor

    import inspect as _inspect

    # Detect async executors at compile time so we can expose the node
    # to LangGraph as a coroutine function. ``graph.ainvoke`` awaits
    # async node callables and runs sync ones via ``asyncio.to_thread``
    # — giving both kinds of executors (F0 sync + Plan 2 async
    # ``run_agent_in_container``) correct semantics without a blanket
    # coroutine-wrap on the sync path.
    executor_is_async = _inspect.iscoroutinefunction(executor)

    def _validate_and_return(result: Any) -> dict[str, Any]:
        if not isinstance(result, output_type):
            raise PrimitiveCompilationError(
                f"AgentAction {node_id}: executor returned "
                f"{type(result).__name__}, expected {output_type.__name__}",
                primitive_type=node_id,
            )
        return result.model_dump()

    def _prepare(state: dict[str, Any]) -> tuple[Any, str, Any]:
        _validate_boundary(state, input_type, node_id)
        model_input = input_type.model_validate(state)
        prompt = prompt_builder(model_input)

        # Resolve ContextVar at invocation time. Deferred import avoids
        # any risk of an orchestration -> compiler cycle.
        from agent_foundry.orchestration.run_context import (
            require_current_run_context,
        )

        run_ctx = require_current_run_context()
        return action, prompt, run_ctx

    if executor_is_async:
        async_executor = cast(
            Callable[..., Any], executor
        )  # typed Callable[..., BaseModel] — pyright can't see the coroutine

        async def node_fn_async(state: dict[str, Any]) -> dict[str, Any]:
            primitive, prompt, run_ctx = _prepare(state)
            result = await async_executor(primitive=primitive, prompt=prompt, run_ctx=run_ctx)
            return _validate_and_return(result)

        # No sync function — attempting ``graph.invoke`` on a plan with
        # an async AgentAction raises a clear TypeError from LangGraph
        # pointing callers at ``ainvoke`` / ``run_primitive_plan``.
        graph.add_node(node_id, RunnableCallable(None, node_fn_async, name=node_id, trace=False))
    else:

        def node_fn_sync(state: dict[str, Any]) -> dict[str, Any]:
            primitive, prompt, run_ctx = _prepare(state)
            result = executor(primitive=primitive, prompt=prompt, run_ctx=run_ctx)
            return _validate_and_return(result)

        graph.add_node(node_id, node_fn_sync)

    return (node_id, node_id)


register_compiler(AgentAction, _compile_agent_action)
