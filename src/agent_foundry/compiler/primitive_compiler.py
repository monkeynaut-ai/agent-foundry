"""Primitive compiler: translates typed primitive graphs into executable LangGraph."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, NamedTuple, TypedDict, cast

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, ValidationError

from agent_foundry.primitives.ai_request import AIRequest
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
from agent_foundry.telemetry.spans import emit_span

# -- Compile context and result --


@dataclass
class CompileContext:
    """Mutable state threaded through the compile pass.

    ``prefix`` names the current node scope. ``gate_ids`` is a shared
    accumulator — child contexts must carry the same list instance so
    that gate node ids collected deep in the tree are visible to
    ``compile_runtime_plan`` at the top.
    """

    prefix: str
    gate_ids: list[str] = field(default_factory=list)

    def child(self, prefix: str) -> CompileContext:
        """Return a child context with a new prefix and the same gate_ids list."""
        return CompileContext(prefix=prefix, gate_ids=self.gate_ids)


class CompileResult(NamedTuple):
    entry_id: str
    exit_id: str


# -- Compiler registry --

type _CompilerStorage = Callable[[StateGraph, Any, CompileContext], CompileResult]

_compiler_registry: dict[type[Primitive], _CompilerStorage] = {}


def register_compiler[P: Primitive](
    prim_type: type[P],
    compiler_fn: Callable[[StateGraph, P, CompileContext], CompileResult],
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


def _validate_scoped_input(
    state: dict[str, Any], input_type: type[BaseModel], node_id: str
) -> BaseModel:
    """Project state to ``input_type``'s declared fields, then validate.

    Returns the validated model instance. The projection step makes the
    compiler's behavior independent of the input model's ``extra``
    config — extras are dropped before validation regardless.
    Required-field errors include ``node_id`` so a developer reading
    the failure can locate the offending step in a multi-primitive plan.

    This is the inbound counterpart to ``_scope_out``.
    """
    fields = set(input_type.model_fields.keys())
    scoped = {k: v for k, v in state.items() if k in fields}
    try:
        return input_type.model_validate(scoped)
    except ValidationError as e:
        raise PrimitiveCompilationError(
            f"Boundary validation failed at {node_id}: {e}",
            primitive_type=node_id,
        ) from e


def _compile_node(graph: StateGraph, prim: Primitive, ctx: CompileContext) -> CompileResult:
    """Compile a primitive into graph nodes/edges."""
    # Parameterized generics (e.g., FunctionAction[A, B]) create new classes.
    # Walk MRO to find the registered base type.
    prim_type = type(prim)
    for cls in prim_type.__mro__:
        compiler = _compiler_registry.get(cls)
        if compiler is not None:
            return compiler(graph, prim, ctx)
    raise PrimitiveCompilationError(
        f"No compiler registered for {prim_type.__name__}",
        primitive_type=prim_type.__name__,
    )


# -- Entry point --


def compile_runtime_plan(plan: PrimitivePlan) -> Any:
    """Build the executable graph for a plan.

    Not part of the public API — products use :func:`run_primitive_plan`.
    The returned object is opaque; calling methods on it directly is
    unsupported.
    """
    plan.validate()
    root = plan.root
    root_in, root_out = get_type_args(root)
    state_type = _derive_state_type(root_in, root_out)
    graph = StateGraph(state_type)

    ctx = CompileContext(prefix="root")
    entry_id, exit_id = _compile_node(graph, root, ctx)
    graph.set_entry_point(entry_id)
    graph.add_edge(exit_id, END)

    compile_kwargs: dict[str, Any] = {}
    if ctx.gate_ids:
        from langgraph.checkpoint.memory import MemorySaver

        compile_kwargs["checkpointer"] = MemorySaver()
        compile_kwargs["interrupt_before"] = ctx.gate_ids

    return graph.compile(**compile_kwargs)


# -- Per-type compilers --


def _compile_function_action(
    graph: StateGraph, action: FunctionAction, ctx: CompileContext
) -> CompileResult:
    import inspect

    node_id = ctx.prefix
    input_type, _ = get_type_args(action)
    # ``FunctionAction.function`` is annotated ``(state) -> O``. Product
    # code that needs run-scoped state (emit domain events, read
    # artifacts_dir, check cancellation) imports accessors from
    # ``agent_foundry.runtime``. 0-arg callables remain supported
    # for trivial / side-effect-only steps.
    fn = cast(Callable[..., BaseModel], action.function)
    arity = len(inspect.signature(fn).parameters)

    def node_fn(state: dict[str, Any]) -> dict[str, Any]:
        # Resolve the current ``RunContext`` once — we need it to
        # emit ``FUNCTION_ACTION_STARTED`` / ``_COMPLETED`` / ``_FAILED``
        # lifecycle events regardless of callable arity. When no run is
        # in progress (e.g. unit tests that compile nodes without a run
        # context), skip event emission.
        from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
        from agent_foundry.orchestration.run_context import current_run_context

        ctx_opt = current_run_context.get()
        if ctx_opt is not None:
            ctx_opt.lifecycle_writer.append(
                LifecycleEvent.FUNCTION_ACTION_STARTED,
                node_id=node_id,
            )
        try:
            if arity == 0:
                result = fn()
            else:
                model_input = _validate_scoped_input(state, input_type, node_id)
                result = fn(model_input)
        except Exception as exc:
            if ctx_opt is not None:
                ctx_opt.lifecycle_writer.append(
                    LifecycleEvent.FUNCTION_ACTION_FAILED,
                    node_id=node_id,
                    reason=str(exc),
                )
            raise
        if ctx_opt is not None:
            ctx_opt.lifecycle_writer.append(
                LifecycleEvent.FUNCTION_ACTION_COMPLETED,
                node_id=node_id,
            )
        return result.model_dump()

    graph.add_node(node_id, node_fn)  # type: ignore[arg-type]
    return CompileResult(node_id, node_id)


register_compiler(FunctionAction, _compile_function_action)


def _compile_sequence(
    graph: StateGraph,
    seq: Sequence,
    ctx: CompileContext,
) -> CompileResult:
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
        entry, exit_ = _compile_node(sub_graph, step, ctx.child(f"{ctx.prefix}_step_{i}"))
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
    node_id = f"{ctx.prefix}_seq"

    async def seq_node(state: dict[str, Any]) -> dict[str, Any]:
        scoped_input = _scope_in(state, seq_in)
        result = await compiled_sub.ainvoke(scoped_input)  # type: ignore[arg-type]
        return _scope_out(result, seq_out)

    graph.add_node(node_id, seq_node)  # type: ignore[arg-type]
    return CompileResult(node_id, node_id)


register_compiler(Sequence, _compile_sequence)


def _compile_conditional(
    graph: StateGraph,
    cond: Conditional,
    ctx: CompileContext,
) -> CompileResult:
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

    router_id = f"{ctx.prefix}_router"
    merge_id = f"{ctx.prefix}_merge"

    then_entry, then_exit = _compile_node(
        sub_graph, cond.then_branch, ctx.child(f"{ctx.prefix}_then")
    )

    if cond.else_branch is not None:
        else_entry, else_exit = _compile_node(
            sub_graph, cond.else_branch, ctx.child(f"{ctx.prefix}_else")
        )
        targets = [then_entry, else_entry]
    else:
        targets = [then_entry, merge_id]

    condition_fn = cond.condition

    def router_fn(state: dict[str, Any]) -> str:
        # LangGraph's sub-graph TypedDict filtering already drops extras
        # before this routing call, but project explicitly for symmetry
        # with the other compile functions and as defense against future
        # framework changes.
        model = _validate_scoped_input(state, cond_in, router_id)
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
    node_id = f"{ctx.prefix}_cond"

    async def cond_node(state: dict[str, Any]) -> dict[str, Any]:
        result = await compiled_sub.ainvoke(dict(state))  # type: ignore[arg-type]
        return _scope_out(result, cond_out)

    graph.add_node(node_id, cond_node)  # type: ignore[arg-type]
    return CompileResult(node_id, node_id)


register_compiler(Conditional, _compile_conditional)


def _compile_loop(
    graph: StateGraph,
    loop: Loop,
    ctx: CompileContext,
) -> CompileResult:
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
    body_entry, body_exit = _compile_node(body_graph, loop.body, ctx.child(f"{ctx.prefix}_body"))
    body_graph.set_entry_point(body_entry)
    body_graph.add_edge(body_exit, END)
    compiled_body = body_graph.compile()

    over_fn = loop.over
    item_key = loop.item_key
    max_iter = loop.max_iterations

    # Wrapper node: iterates, scoping in/out per iteration
    node_id = f"{ctx.prefix}_loop"

    async def loop_node(state: dict[str, Any]) -> dict[str, Any]:
        model = _validate_scoped_input(state, loop_in, node_id)
        items = over_fn(model)
        # Accumulated state — starts with full parent state, grows across iterations
        current_state = dict(state)

        for i, item in enumerate(items):
            if i >= max_iter:
                break
            # Inject item, then pass full accumulated state to body
            current_state[item_key] = item
            result = await compiled_body.ainvoke(dict(current_state))  # type: ignore[arg-type]
            # Merge body output back into accumulated state
            updates = _scope_out(result, body_out)
            current_state.update(updates)

        return _scope_out(current_state, loop_out)

    graph.add_node(node_id, loop_node)  # type: ignore[arg-type]
    return CompileResult(node_id, node_id)


register_compiler(Loop, _compile_loop)


def _compile_retry(
    graph: StateGraph,
    retry: Retry,
    ctx: CompileContext,
) -> CompileResult:
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
    body_entry, body_exit = _compile_node(body_graph, retry.body, ctx.child(f"{ctx.prefix}_body"))
    body_graph.set_entry_point(body_entry)
    body_graph.add_edge(body_exit, END)
    compiled_body = body_graph.compile()

    until_fn = retry.until
    max_attempts = retry.max_attempts

    # Wrapper node: retry loop with scoped body execution
    node_id = f"{ctx.prefix}_retry"

    async def retry_node(state: dict[str, Any]) -> dict[str, Any]:
        current_state = dict(state)
        for _ in range(max_attempts):
            result = await compiled_body.ainvoke(dict(current_state))  # type: ignore[arg-type]
            current_state.update(_scope_out(result, body_out))
            model = _validate_scoped_input(current_state, retry_in, node_id)
            if until_fn(model):
                break
        return _scope_out(current_state, retry_out)

    graph.add_node(node_id, retry_node)  # type: ignore[arg-type]
    return CompileResult(node_id, node_id)


register_compiler(Retry, _compile_retry)


def _compile_gate_action(
    graph: StateGraph,
    gate: GateAction,
    ctx: CompileContext,
) -> CompileResult:
    gate_id = ctx.prefix

    def gate_node(state: dict[str, Any]) -> dict[str, Any]:
        return state  # interrupt_before pauses BEFORE this node

    graph.add_node(gate_id, gate_node)  # type: ignore[arg-type]
    ctx.gate_ids.append(gate_id)
    return CompileResult(gate_id, gate_id)


register_compiler(GateAction, _compile_gate_action)


def _compile_agent_action(
    graph: StateGraph,
    action: AgentAction,
    ctx: CompileContext,
) -> CompileResult:
    node_id = ctx.prefix
    input_type, output_type = get_type_args(action)
    prompt_builder = action.prompt_builder
    instructions_provider = action.instructions_provider
    executor = action.executor

    import inspect as _inspect

    # Detect async executors at compile time so we can expose the node
    # to LangGraph as a coroutine function. ``graph.ainvoke`` awaits
    # async node callables and runs sync ones via ``asyncio.to_thread``
    # — giving both sync and async executors correct semantics without
    # a blanket coroutine-wrap on the sync path.
    executor_is_async = _inspect.iscoroutinefunction(executor)

    def _validate_typed(result: Any) -> BaseModel:
        if not isinstance(result, output_type):
            raise PrimitiveCompilationError(
                f"AgentAction {node_id}: executor returned "
                f"{type(result).__name__}, expected {output_type.__name__}",
                primitive_type=node_id,
            )
        return result

    def _prepare(state: dict[str, Any]) -> tuple[Any, str, str, Any, BaseModel]:
        model_input = _validate_scoped_input(state, input_type, node_id)
        prompt = prompt_builder(model_input)
        instructions = instructions_provider(model_input)

        # Resolve ContextVar at invocation time. Deferred import avoids
        # any risk of an orchestration -> compiler cycle.
        from agent_foundry.orchestration.run_context import require_current_run_context

        run_ctx = require_current_run_context()
        return action, prompt, instructions, run_ctx, model_input

    if executor_is_async:

        async def node_fn_async(state: dict[str, Any]) -> dict[str, Any]:
            primitive, prompt, instructions, run_ctx, model_input = _prepare(state)
            redaction = run_ctx.telemetry.redaction if run_ctx.telemetry is not None else None

            with emit_span(
                name=f"agent_foundry.AgentAction.{action.name}",
                primitive_type="AgentAction",
                primitive_name=action.name,
                input_model=model_input,
                run_id=run_ctx.run_id,
                redaction=redaction,
            ) as handle:
                handle.set_operation_name("chat")
                result = await executor(
                    primitive=primitive,
                    prompt=prompt,
                    instructions=instructions,
                    run_ctx=run_ctx,
                )
                typed = _validate_typed(result)
                handle.set_output(typed)
                return typed.model_dump()

        # No sync function — attempting ``graph.invoke`` on a plan with
        # an async AgentAction raises a clear TypeError from LangGraph
        # pointing callers at ``ainvoke`` / ``run_primitive_plan``.
        graph.add_node(node_id, node_fn_async)  # type: ignore[arg-type]
    else:

        def node_fn_sync(state: dict[str, Any]) -> dict[str, Any]:
            primitive, prompt, instructions, run_ctx, model_input = _prepare(state)
            redaction = run_ctx.telemetry.redaction if run_ctx.telemetry is not None else None

            with emit_span(
                name=f"agent_foundry.AgentAction.{action.name}",
                primitive_type="AgentAction",
                primitive_name=action.name,
                input_model=model_input,
                run_id=run_ctx.run_id,
                redaction=redaction,
            ) as handle:
                handle.set_operation_name("chat")
                result = executor(
                    primitive=primitive,
                    prompt=prompt,
                    instructions=instructions,
                    run_ctx=run_ctx,
                )
                typed = _validate_typed(result)
                handle.set_output(typed)
                return typed.model_dump()

        graph.add_node(node_id, node_fn_sync)  # type: ignore[arg-type]

    return CompileResult(node_id, node_id)


register_compiler(AgentAction, _compile_agent_action)


def _compile_ai_request(
    graph: StateGraph,
    action: AIRequest,
    ctx: CompileContext,
) -> CompileResult:
    node_id = ctx.prefix
    input_type, _ = get_type_args(action)

    async def node_fn(state: dict[str, Any]) -> dict[str, Any]:
        from agent_foundry.orchestration.run_context import current_run_context
        from agent_foundry.primitives.ai_request import invoke_ai_request

        model_input = _validate_scoped_input(state, input_type, node_id)

        ctx_opt = current_run_context.get()
        redaction = (
            ctx_opt.telemetry.redaction
            if ctx_opt is not None and ctx_opt.telemetry is not None
            else None
        )
        run_id = ctx_opt.run_id if ctx_opt is not None else node_id

        with emit_span(
            name=f"agent_foundry.AIRequest.{node_id}",
            primitive_type="AIRequest",
            primitive_name=node_id,
            input_model=model_input,
            run_id=run_id,
            redaction=redaction,
        ) as handle:
            handle.set_operation_name("chat")
            try:
                result = await invoke_ai_request(action, model_input)
            except TypeError as exc:
                raise PrimitiveCompilationError(
                    f"AIRequest {node_id}: {exc}",
                    primitive_type=node_id,
                ) from exc
            handle.set_output(result)
            return result.model_dump()

    graph.add_node(node_id, node_fn)  # type: ignore[arg-type]
    return CompileResult(node_id, node_id)


register_compiler(AIRequest, _compile_ai_request)
