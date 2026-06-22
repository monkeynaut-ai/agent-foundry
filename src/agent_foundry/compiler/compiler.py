"""Construct compiler: translates typed construct graphs into executable LangGraph."""

from __future__ import annotations

import copy
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, NamedTuple, TypedDict, cast

from langgraph._internal._runnable import RunnableCallable
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, ValidationError

# invoke_ai_call is safe at module level: invoke.py imports AICall only under
# TYPE_CHECKING, so no runtime cycle exists.
from agent_foundry.ai_models.execute.invoke import invoke_ai_call
from agent_foundry.constructs.ai_call import AICall
from agent_foundry.constructs.errors import ConstructCompilationError
from agent_foundry.constructs.models import (
    AgentAction,
    AsyncFunctionAction,
    Conditional,
    Construct,
    FunctionAction,
    GateAction,
    Loop,
    Retry,
    RetryExceptionPolicy,
    Sequence,
    get_type_args,
)
from agent_foundry.constructs.process import Process
from agent_foundry.constructs.retry_types import (
    WELL_KNOWN_METADATA_FIELDS,
    AttemptFailure,
    AttemptOutcome,
    DispositionKind,
    ResolverDidNotConvergeError,
    ResolverDisposition,
    RetryAborted,
    RetryExhaustionReason,
    RetryRoute,
)
from agent_foundry.models.usage import TokenUsage
from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
from agent_foundry.orchestration.run_context import current_run_context, require_current_run_context
from agent_foundry.telemetry.spans import emit_span

# Flat (non-prefixed) state key the resolver node writes its ResolverDisposition
# into and the disposition router reads. Fixed name so a resolver author can
# declare it without knowing the Retry's compile prefix.
DISPOSITION_KEY = "disposition"

# -- Compile context and result --


@dataclass
class CompileContext:
    """Mutable state threaded through the compile pass.

    ``prefix`` names the current node scope. ``gate_ids`` is a shared
    accumulator — child contexts must carry the same list instance so
    that gate node ids collected deep in the tree are visible to
    ``compile_process`` at the top.
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

_compiler_registry: dict[type[Construct], _CompilerStorage] = {}


def register_compiler[P: Construct](
    prim_type: type[P],
    compiler_fn: Callable[[StateGraph, P, CompileContext], CompileResult],
) -> None:
    """Register a compiler function for a construct type.

    The function's construct parameter type is checked against ``prim_type``
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


def _is_async_callable(obj: Any) -> bool:
    """Return True if obj is an async callable.

    Handles both ``async def`` functions and callable objects whose
    ``__call__`` method is a coroutine function.

    There is the possibility of a false negative. This will occur when a
    function returns a coroutine without declaring ``async def``. This causes
    it to be reported as not-async, which triggers the compile-time guard and
    blocks the coroutine from being executed.
    """
    if inspect.iscoroutinefunction(obj):
        return True
    call = getattr(type(obj), "__call__", None)  # noqa: B004 — not a callability test; need the method to inspect
    return call is not None and inspect.iscoroutinefunction(call)


def _derive_state_type(input_type: type[BaseModel], output_type: type[BaseModel]) -> type:
    """Derive a TypedDict(total=False) from the union of I and O model fields."""
    fields: dict[str, Any] = {}
    for model in (input_type, output_type):
        for name in model.model_fields:
            fields[name] = Any
    return TypedDict("ConstructState", fields, total=False)  # type: ignore[call-overload]


def _retry_channels(prefix: str) -> dict[str, Any]:
    """Compiler-internal outer-state channel names a single Retry at ``prefix`` needs.

    These cannot be discovered during compilation: LangGraph fixes the state
    schema at ``StateGraph(state_type)`` construction and drops keys a node
    returns that the schema did not declare. So they are injected into the
    schema of whatever (sub)graph owns the Retry's nodes (see
    ``_state_type_with_retry_channels``).

    Only internal channels (backstop counter, routing signals) are
    prefix-namespaced. The resolver-read exhaustion metadata uses fixed
    well-known names (see ``WELL_KNOWN_METADATA_CHANNELS``) so a resolver
    author can declare matching input fields without knowing the compile
    prefix.
    """
    return {
        f"{prefix}__resolver_reentries": Any,  # backstop counter (loop-carried)
        _retry_route_key(prefix): Any,  # automated-phase routing signal
        _reentry_route_key(prefix): Any,  # re-entry routing signal
    }


# Constant (not prefix-namespaced) channel names carrying the exhaustion
# metadata the resolver reads. The compiler writes these into the Retry's scope
# right before the resolver node; a resolver input model declares matching
# fields to read them. The names must be constant rather than scoped to the
# Retry's compile prefix because a resolver author cannot know that prefix.
#
# Each name is written once and read immediately by the resolver that runs as
# the next node. Correctness depends on no second Retry writing these names
# between that write and read. Today nothing can: all execution is sequential
# (Sequence is linear, Loop awaits each iteration in turn, Conditional takes one
# branch, and there is no parallel construct), so no two Retries' write->read
# windows ever overlap — not siblings, not nested. The shared names would only
# collide if two Retries became live in the same scope at once, e.g. a Retry
# inside another Retry's resolver, or concurrent execution were ever introduced.
WELL_KNOWN_EXHAUSTION_REASON = "exhaustion_reason"
WELL_KNOWN_ATTEMPT_FAILURES = "attempt_failures"
WELL_KNOWN_METADATA_CHANNELS: dict[str, Any] = dict.fromkeys(WELL_KNOWN_METADATA_FIELDS, Any)


def _collect_retry_channels(prim: Construct, prefix: str) -> dict[str, Any]:
    """Walk the process tree and collect outer-state channels every Retry needs.

    A Retry contributes its prefix-namespaced internal channels and the fixed
    well-known metadata channels; child enumeration recurses through
    ``child_specs`` so the per-child prefixes match the compilers' scheme by
    construction (a divergence would make a nested Retry write to undeclared
    keys that LangGraph silently drops). Leaves return no children, so they add
    nothing.
    """
    channels: dict[str, Any] = {}
    if isinstance(prim, Retry):
        channels.update(_retry_channels(prefix))
        channels.update(WELL_KNOWN_METADATA_CHANNELS)
    for child, suffix in prim.child_specs():
        channels.update(_collect_retry_channels(child, f"{prefix}_{suffix}"))
    return channels


def _state_type_with_retry_channels(
    name: str, fields: dict[str, Any], children: list[tuple[Construct, str]]
) -> type:
    """Build a TypedDict(total=False) from ``fields`` plus the retry channels of
    each ``(child_construct, child_prefix)`` compiled into this subgraph.

    A subgraph's schema is fixed at ``StateGraph(...)`` construction; any Retry
    compiled into it (at arbitrary nesting depth below its direct children)
    writes channels that must be declared here or LangGraph drops them.
    """
    merged = dict(fields)
    for child, child_prefix in children:
        merged.update(_collect_retry_channels(child, child_prefix))
    return TypedDict(name, merged, total=False)  # type: ignore[call-overload]


def _compile_body_subgraph(
    state_type_name: str,
    io_types: list[type[BaseModel]],
    body: Construct,
    body_prefix: str,
    ctx: CompileContext,
) -> Any:
    """Compile a single-body subgraph (entry -> body -> END) and return the
    compiled graph. ``io_types`` are the models whose fields seed the subgraph
    state schema (outer + body I/O); the body's retry channels are injected too.
    Shared by Loop and Retry, whose bodies compile identically."""
    fields: dict[str, Any] = {}
    for model in io_types:
        for name in model.model_fields:
            fields[name] = Any
    body_state_type = _state_type_with_retry_channels(
        state_type_name, fields, [(body, body_prefix)]
    )
    body_graph = StateGraph(body_state_type)
    body_entry, body_exit = _compile_node(body_graph, body, ctx.child(body_prefix))
    body_graph.set_entry_point(body_entry)
    body_graph.add_edge(body_exit, END)
    return body_graph.compile()


def _scope_in(parent_state: dict[str, Any], child_input_type: type[BaseModel]) -> dict[str, Any]:
    """Scope parent state down to child's input fields. Validates required fields."""
    fields = set(child_input_type.model_fields.keys())
    scoped = {k: v for k, v in parent_state.items() if k in fields}
    try:
        child_input_type.model_validate(scoped)
    except ValidationError as e:
        raise ConstructCompilationError(f"Scope-in failed: {e}", construct_type="scope_in") from e
    return scoped


def _scope_out(child_result: dict[str, Any], child_output_type: type[BaseModel]) -> dict[str, Any]:
    """Scope child result down to output fields. Validates output completeness."""
    fields = set(child_output_type.model_fields.keys())
    scoped = {k: v for k, v in child_result.items() if k in fields}
    try:
        child_output_type.model_validate(scoped)
    except ValidationError as e:
        raise ConstructCompilationError(f"Scope-out failed: {e}", construct_type="scope_out") from e
    return scoped


def _validate_scoped_input(
    state: dict[str, Any], input_type: type[BaseModel], node_id: str
) -> BaseModel:
    """Project state to ``input_type``'s declared fields, then validate.

    Returns the validated model instance. The projection step makes the
    compiler's behavior independent of the input model's ``extra``
    config — extras are dropped before validation regardless.
    Required-field errors include ``node_id`` so a developer reading
    the failure can locate the offending step in a multi-construct process.

    This is the inbound counterpart to ``_scope_out``.
    """
    fields = set(input_type.model_fields.keys())
    scoped = {k: v for k, v in state.items() if k in fields}
    try:
        return input_type.model_validate(scoped)
    except ValidationError as e:
        raise ConstructCompilationError(
            f"Boundary validation failed at {node_id}: {e}",
            construct_type=node_id,
        ) from e


def _retry_route_key(prefix: str) -> str:
    """Scoped state channel the automated retry node writes its RetryRoute into."""
    return f"{prefix}__retry_route"


def _reentry_route_key(prefix: str) -> str:
    """Scoped state channel the re-entry node writes its RetryRoute into."""
    return f"{prefix}__reentry_route"


def _read_retry_route(state: dict[str, Any], route_key: str, node_id: str) -> RetryRoute:
    """Read a required RetryRoute marker, raising if a node failed to write it.

    A missing marker means a node forgot to set its route channel — a compiler
    wiring bug — so this fails loud rather than silently defaulting a branch.
    """
    raw = state.get(route_key)
    if raw is None:
        raise ConstructCompilationError(
            f"Retry {node_id}: missing route marker '{route_key}'",
            construct_type=node_id,
        )
    return RetryRoute(raw)


def _derive_exhaustion_reason(raised: int, clean_not_passed: int) -> RetryExhaustionReason:
    if raised and not clean_not_passed:
        return RetryExhaustionReason.BODY_EXCEPTIONS
    if clean_not_passed and not raised:
        return RetryExhaustionReason.CONDITION_NOT_MET
    return RetryExhaustionReason.MIXED


def _coerce_disposition(raw: Any) -> ResolverDisposition:
    if isinstance(raw, ResolverDisposition):
        return raw
    return ResolverDisposition.model_validate(raw)


def _outcome_from_body(
    state: dict[str, Any],
    body_result: dict[str, Any],
    *,
    body_out: type[BaseModel],
    retry_in: type[BaseModel],
    retry_id: str,
    until_fn: Callable[[Any], bool],
) -> tuple[dict[str, Any], AttemptOutcome]:
    """Merge a body attempt's output into state and evaluate the until() condition."""
    merged = dict(state)
    merged.update(_scope_out(body_result, body_out))
    model = _validate_scoped_input(merged, retry_in, retry_id)
    return merged, (AttemptOutcome.PASSED if until_fn(model) else AttemptOutcome.NOT_PASSED)


def _compile_node(graph: StateGraph, prim: Construct, ctx: CompileContext) -> CompileResult:
    """Compile a construct into graph nodes/edges."""
    # Parameterized generics (e.g., FunctionAction[A, B]) create new classes.
    # Walk MRO to find the registered base type.
    prim_type = type(prim)
    for cls in prim_type.__mro__:
        compiler = _compiler_registry.get(cls)
        if compiler is not None:
            return compiler(graph, prim, ctx)
    raise ConstructCompilationError(
        f"No compiler registered for {prim_type.__name__}",
        construct_type=prim_type.__name__,
    )


# -- Entry point --


def compile_process(process: Process) -> Any:
    """Build the executable graph for a process.

    Not part of the public API — products use :func:`run_process`.
    The returned object is opaque; calling methods on it directly is
    unsupported.
    """
    process.validate()
    root = process.root
    root_in, root_out = get_type_args(root)
    state_type = _derive_state_type(root_in, root_out)
    extra = _collect_retry_channels(root, "root")
    if extra:
        merged = {**dict.fromkeys(state_type.__annotations__, Any), **extra}
        state_type = TypedDict("ConstructState", merged, total=False)  # type: ignore[call-overload]
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
    node_id = ctx.prefix
    label = action.name or node_id
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
        ctx_opt = current_run_context.get()
        if ctx_opt is not None:
            ctx_opt.lifecycle_writer.append(
                LifecycleEvent.FUNCTION_ACTION_STARTED,
                node_id=node_id,
                name=label,
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
                    name=label,
                    reason=str(exc),
                )
            raise
        if ctx_opt is not None:
            ctx_opt.lifecycle_writer.append(
                LifecycleEvent.FUNCTION_ACTION_COMPLETED,
                node_id=node_id,
                name=label,
            )
        return result.model_dump()

    graph.add_node(node_id, node_fn)  # type: ignore[arg-type]
    return CompileResult(node_id, node_id)


register_compiler(FunctionAction, _compile_function_action)


def _compile_async_function_action(
    graph: StateGraph, action: AsyncFunctionAction, ctx: CompileContext
) -> CompileResult:
    node_id = ctx.prefix
    label = action.name or node_id
    input_type, _ = get_type_args(action)
    fn = cast(Callable[..., Awaitable[BaseModel]], action.function)
    arity = len(inspect.signature(fn).parameters)

    async def node_fn(state: dict[str, Any]) -> dict[str, Any]:
        ctx_opt = current_run_context.get()
        if ctx_opt is not None:
            ctx_opt.lifecycle_writer.append(
                LifecycleEvent.FUNCTION_ACTION_STARTED,
                node_id=node_id,
                name=label,
            )
        try:
            if arity == 0:
                result = await fn()
            else:
                model_input = _validate_scoped_input(state, input_type, node_id)
                result = await fn(model_input)
        except Exception as exc:
            if ctx_opt is not None:
                ctx_opt.lifecycle_writer.append(
                    LifecycleEvent.FUNCTION_ACTION_FAILED,
                    node_id=node_id,
                    name=label,
                    reason=str(exc),
                )
            raise
        if ctx_opt is not None:
            ctx_opt.lifecycle_writer.append(
                LifecycleEvent.FUNCTION_ACTION_COMPLETED,
                node_id=node_id,
                name=label,
            )
        return result.model_dump()

    graph.add_node(node_id, node_fn)  # type: ignore[arg-type]
    return CompileResult(node_id, node_id)


register_compiler(AsyncFunctionAction, _compile_async_function_action)


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
    specs = seq.child_specs()
    step_children = [(step, f"{ctx.prefix}_{suffix}") for step, suffix in specs]
    sub_state_type = _state_type_with_retry_channels("SeqState", fields, step_children)
    sub_graph = StateGraph(sub_state_type)

    first_entry = None
    prev_exit = None
    for step, suffix in specs:
        entry, exit_ = _compile_node(sub_graph, step, ctx.child(f"{ctx.prefix}_{suffix}"))
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
    # then/else are role-specific for edge wiring, so child_specs drives only the
    # prefix derivation; the suffix per branch is looked up by object identity.
    suffix_for = {id(child): suffix for child, suffix in cond.child_specs()}
    then_prefix = f"{ctx.prefix}_{suffix_for[id(cond.then_branch)]}"
    branch_children: list[tuple[Construct, str]] = [(cond.then_branch, then_prefix)]
    if cond.else_branch is not None:
        else_prefix = f"{ctx.prefix}_{suffix_for[id(cond.else_branch)]}"
        branch_children.append((cond.else_branch, else_prefix))
    sub_state_type = _state_type_with_retry_channels("CondState", fields, branch_children)
    sub_graph = StateGraph(sub_state_type)

    router_id = f"{ctx.prefix}_router"
    merge_id = f"{ctx.prefix}_merge"

    then_entry, then_exit = _compile_node(sub_graph, cond.then_branch, ctx.child(then_prefix))

    if cond.else_branch is not None:
        else_entry, else_exit = _compile_node(
            sub_graph,
            cond.else_branch,
            ctx.child(else_prefix),  # type: ignore[possibly-undefined]
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

    ((body, body_suffix),) = loop.child_specs()
    body_prefix = f"{ctx.prefix}_{body_suffix}"
    # State includes loop I/O + body I/O for accumulated context.
    compiled_body = _compile_body_subgraph(
        "LoopBodyState", [loop_in, loop_out, body_in, body_out], body, body_prefix, ctx
    )

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


def _emit_lifecycle(event: LifecycleEvent, **fields: Any) -> None:
    """Append a lifecycle event when a run context is active; no-op otherwise
    (e.g. unit tests that compile/invoke nodes without an installed run)."""
    ctx_opt = current_run_context.get()
    if ctx_opt is not None:
        ctx_opt.lifecycle_writer.append(event, **fields)


def _compile_retry(
    graph: StateGraph,
    retry: Retry,
    ctx: CompileContext,
) -> CompileResult:
    """Compile Retry as the resolver-cycle topology.

    The automated phase runs in one node (no checkpointer needed — its body
    subgraph has no gate). Exhaustion has exactly one path: a cycle of real
    outer-graph nodes (resolver / re-entry / abort), so a GateAction resolver can
    pause and resume as an outer-graph node and the backstop counter lives in a
    declared state channel rather than Python locals.
    """
    by_role = {suffix: child for child, suffix in retry.child_specs()}
    body = by_role[Retry.BODY_SUFFIX]
    resolver = by_role.get(Retry.RESOLVER_SUFFIX)
    prefix = ctx.prefix

    retry_in, retry_out = get_type_args(retry)
    body_in, body_out = get_type_args(body)
    body_prefix = f"{prefix}_{Retry.BODY_SUFFIX}"
    # State includes retry I/O + body I/O for accumulated context.
    compiled_body = _compile_body_subgraph(
        "RetryBodyState", [retry_in, retry_out, body_in, body_out], body, body_prefix, ctx
    )

    until_fn = retry.until
    max_attempts = retry.max_attempts
    max_reentries = retry.resolver_max_reentries
    # Precompute as a bool so the closure captures a plain value, not the enum class.
    treat_body_exception_as_failure = (
        retry.exception_policy == RetryExceptionPolicy.CATCH_AND_CONTINUE
    )

    retry_id = f"{prefix}_retry"
    resolver_id = f"{prefix}_{Retry.RESOLVER_SUFFIX}"
    reentry_id = f"{prefix}_reentry"
    abort_id = f"{prefix}_abort"
    merge_id = f"{prefix}_merge"
    reentries_key = f"{prefix}__resolver_reentries"
    retry_route_key = _retry_route_key(prefix)
    reentry_route_key = _reentry_route_key(prefix)
    # Resolver-read metadata uses fixed names a resolver can declare without
    # knowing this compile prefix. Write-once-read-immediately by the resolver
    # that runs right after the automated loop. v1 limitation: a nested Retry in
    # this Retry's resolver or body could collide on these names (and on the flat
    # ``disposition`` key).
    exhaustion_reason_key = WELL_KNOWN_EXHAUSTION_REASON
    attempt_failures_key = WELL_KNOWN_ATTEMPT_FAILURES

    def _handle_body_exception(
        snapshot: dict[str, Any], exc: Exception, attempt_num: int
    ) -> tuple[dict[str, Any], AttemptOutcome, AttemptFailure]:
        """Map a body raise per exception_policy. PROPAGATE re-raises; otherwise
        record the failure, restore the pre-attempt state, return NOT_PASSED and
        the failure record so the automated loop can tally exhaustion reason."""
        if not treat_body_exception_as_failure:
            raise exc
        failure = AttemptFailure(
            attempt_num=attempt_num,
            exception_type=type(exc).__name__,
            exception_message=str(exc),
            timestamp=datetime.now(UTC),
        )
        _emit_lifecycle(
            LifecycleEvent.RETRY_ATTEMPT_ERRORED,
            node_id=retry_id,
            attempt_num=failure.attempt_num,
            exception_type=failure.exception_type,
            exception_message=failure.exception_message,
        )
        return snapshot, AttemptOutcome.NOT_PASSED, failure

    # Shared body-execution + outcome logic, used by BOTH the automated loop and
    # the re-entry node so there is no separate guided-exception path. The third
    # element is the AttemptFailure when the body raised (CATCH_AND_CONTINUE),
    # else None — the automated loop uses it to derive the exhaustion reason.
    def _run_body_once_sync(
        state: dict[str, Any], attempt_num: int
    ) -> tuple[dict[str, Any], AttemptOutcome, AttemptFailure | None]:
        snapshot = copy.deepcopy(state)
        try:
            result = compiled_body.invoke(dict(state))  # type: ignore[arg-type]
            merged, outcome = _outcome_from_body(
                state,
                result,
                body_out=body_out,
                retry_in=retry_in,
                retry_id=retry_id,
                until_fn=until_fn,
            )
            _emit_lifecycle(
                LifecycleEvent.RETRY_ATTEMPT_PASSED
                if outcome is AttemptOutcome.PASSED
                else LifecycleEvent.RETRY_ATTEMPT_NOT_PASSED,
                node_id=retry_id,
                attempt_num=attempt_num,
            )
            return merged, outcome, None
        except Exception as exc:
            return _handle_body_exception(snapshot, exc, attempt_num)

    async def _run_body_once_async(
        state: dict[str, Any], attempt_num: int
    ) -> tuple[dict[str, Any], AttemptOutcome, AttemptFailure | None]:
        snapshot = copy.deepcopy(state)
        try:
            result = await compiled_body.ainvoke(dict(state))  # type: ignore[arg-type]
            merged, outcome = _outcome_from_body(
                state,
                result,
                body_out=body_out,
                retry_in=retry_in,
                retry_id=retry_id,
                until_fn=until_fn,
            )
            _emit_lifecycle(
                LifecycleEvent.RETRY_ATTEMPT_PASSED
                if outcome is AttemptOutcome.PASSED
                else LifecycleEvent.RETRY_ATTEMPT_NOT_PASSED,
                node_id=retry_id,
                attempt_num=attempt_num,
            )
            return merged, outcome, None
        except Exception as exc:
            return _handle_body_exception(snapshot, exc, attempt_num)

    def _retry_exhausted(
        state: dict[str, Any], reason: RetryExhaustionReason, failures: list[AttemptFailure]
    ) -> dict[str, Any]:
        state[retry_route_key] = RetryRoute.EXHAUSTED
        state[reentries_key] = 0
        state[exhaustion_reason_key] = reason.value
        state[attempt_failures_key] = [f.model_dump() for f in failures]
        return state

    def _retry_passed(state: dict[str, Any]) -> dict[str, Any]:
        out = _scope_out(state, retry_out)
        out[retry_route_key] = RetryRoute.PASS
        return out

    def retry_node_sync(state: dict[str, Any]) -> dict[str, Any]:
        current_state = dict(state)
        failures: list[AttemptFailure] = []
        clean_not_passed = 0
        for attempt_num in range(max_attempts):
            current_state, outcome, failure = _run_body_once_sync(current_state, attempt_num + 1)
            if outcome is AttemptOutcome.PASSED:
                return _retry_passed(current_state)
            if failure is not None:
                failures.append(failure)
            else:
                clean_not_passed += 1
        reason = _derive_exhaustion_reason(len(failures), clean_not_passed)
        return _retry_exhausted(current_state, reason, failures)

    async def retry_node_async(state: dict[str, Any]) -> dict[str, Any]:
        current_state = dict(state)
        failures: list[AttemptFailure] = []
        clean_not_passed = 0
        for attempt_num in range(max_attempts):
            current_state, outcome, failure = await _run_body_once_async(
                current_state, attempt_num + 1
            )
            if outcome is AttemptOutcome.PASSED:
                return _retry_passed(current_state)
            if failure is not None:
                failures.append(failure)
            else:
                clean_not_passed += 1
        reason = _derive_exhaustion_reason(len(failures), clean_not_passed)
        return _retry_exhausted(current_state, reason, failures)

    # -- Resolver node: emits a ResolverDisposition into state --
    if resolver is None:

        def unset_resolver_node(state: dict[str, Any]) -> dict[str, Any]:
            return {
                DISPOSITION_KEY: ResolverDisposition(
                    kind=DispositionKind.ABORT, reason="no resolver configured"
                ).model_dump()
            }

        graph.add_node(resolver_id, unset_resolver_node)  # type: ignore[arg-type]
        resolver_entry = resolver_id
        resolver_exit = resolver_id
    else:
        resolver_entry, resolver_exit = _compile_node(graph, resolver, ctx.child(resolver_id))

    def retry_router(state: dict[str, Any]) -> str:
        route = _read_retry_route(state, retry_route_key, retry_id)
        return merge_id if route is RetryRoute.PASS else resolver_entry

    graph.add_node(
        retry_id,
        RunnableCallable(retry_node_sync, retry_node_async, name=retry_id, trace=False),
    )
    graph.add_conditional_edges(retry_id, retry_router, [merge_id, resolver_entry])

    def disposition_router(state: dict[str, Any]) -> str:
        raw = state.get(DISPOSITION_KEY)
        if raw is None:
            raise ConstructCompilationError(
                f"Retry {retry_id}: resolver produced no '{DISPOSITION_KEY}' field",
                construct_type=retry_id,
            )
        try:
            disposition = _coerce_disposition(raw)
        except ValidationError as exc:
            raise ConstructCompilationError(
                f"Retry {retry_id}: '{DISPOSITION_KEY}' is not a ResolverDisposition: {exc}",
                construct_type=retry_id,
            ) from exc
        _emit_lifecycle(
            LifecycleEvent.RESOLVER_DISPOSITION,
            node_id=retry_id,
            kind=disposition.kind.value,
            reason=disposition.reason,
        )
        if disposition.kind is DispositionKind.ACCEPT:
            return merge_id
        if disposition.kind is DispositionKind.ABORT:
            return abort_id
        return reentry_id  # RETRY

    graph.add_conditional_edges(resolver_exit, disposition_router, [merge_id, abort_id, reentry_id])

    # -- Re-entry node: increment backstop, run body once, re-evaluate until() --
    def _reentry_check_backstop(state: dict[str, Any]) -> int:
        reentries = int(state.get(reentries_key, 0)) + 1
        if reentries > max_reentries:
            raise ResolverDidNotConvergeError(max_reentries)
        return reentries

    def _reentry_finish(
        current_state: dict[str, Any], reentries: int, outcome: AttemptOutcome
    ) -> dict[str, Any]:
        current_state[reentries_key] = reentries
        if outcome is AttemptOutcome.PASSED:
            out = _scope_out(current_state, retry_out)
            out[reentry_route_key] = RetryRoute.PASS
            return out
        current_state[reentry_route_key] = RetryRoute.NOT_PASSED
        return current_state

    def reentry_node_sync(state: dict[str, Any]) -> dict[str, Any]:
        reentries = _reentry_check_backstop(state)
        current_state = dict(state)
        current_state[reentries_key] = reentries
        current_state, outcome, _failure = _run_body_once_sync(current_state, reentries)
        return _reentry_finish(current_state, reentries, outcome)

    async def reentry_node_async(state: dict[str, Any]) -> dict[str, Any]:
        reentries = _reentry_check_backstop(state)
        current_state = dict(state)
        current_state[reentries_key] = reentries
        current_state, outcome, _failure = await _run_body_once_async(current_state, reentries)
        return _reentry_finish(current_state, reentries, outcome)

    def reentry_router(state: dict[str, Any]) -> str:
        route = _read_retry_route(state, reentry_route_key, retry_id)
        return merge_id if route is RetryRoute.PASS else resolver_entry

    graph.add_node(
        reentry_id,
        RunnableCallable(reentry_node_sync, reentry_node_async, name=reentry_id, trace=False),
    )
    graph.add_conditional_edges(reentry_id, reentry_router, [merge_id, resolver_entry])

    # -- Abort node: raise RetryAborted carrying the reason --
    def abort_node(state: dict[str, Any]) -> dict[str, Any]:
        raw = state.get(DISPOSITION_KEY)
        reason = _coerce_disposition(raw).reason if raw is not None else ""
        raise RetryAborted(reason)

    graph.add_node(abort_id, abort_node)  # type: ignore[arg-type]

    # -- Merge / exit node: fed by the automated pass path and the ACCEPT path --
    graph.add_node(merge_id, lambda state: state)  # type: ignore[arg-type]

    return CompileResult(entry_id=retry_id, exit_id=merge_id)


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

    # Detect async executors at compile time so we can expose the node
    # to LangGraph as a coroutine function. ``graph.ainvoke`` awaits
    # async node callables and runs sync ones via ``asyncio.to_thread``
    # — giving both sync and async executors correct semantics without
    # a blanket coroutine-wrap on the sync path.
    executor_is_async = _is_async_callable(executor)

    def _validate_typed(result: Any) -> BaseModel:
        if not isinstance(result, output_type):
            raise ConstructCompilationError(
                f"AgentAction {node_id}: executor returned "
                f"{type(result).__name__}, expected {output_type.__name__}",
                construct_type=node_id,
            )
        return result

    def _prepare(state: dict[str, Any]) -> tuple[Any, str, str, Any, BaseModel]:
        model_input = _validate_scoped_input(state, input_type, node_id)
        prompt = prompt_builder(model_input)
        instructions = instructions_provider(model_input)
        run_ctx = require_current_run_context()
        return action, prompt, instructions, run_ctx, model_input

    if executor_is_async:

        async def node_fn_async(state: dict[str, Any]) -> dict[str, Any]:
            construct, prompt, instructions, run_ctx, model_input = _prepare(state)
            redaction = run_ctx.telemetry.redaction if run_ctx.telemetry is not None else None

            with emit_span(
                name=f"agent_foundry.AgentAction.{action.name}",
                construct_type="AgentAction",
                construct_name=action.name,
                input_model=model_input,
                run_id=run_ctx.run_id,
                redaction=redaction,
            ) as handle:
                handle.set_operation_name("chat")
                result = await executor(
                    construct=construct,
                    prompt=prompt,
                    instructions=instructions,
                    run_ctx=run_ctx,
                )
                typed = _validate_typed(result)
                handle.set_output(typed)
                return typed.model_dump()

        # No sync function — attempting ``graph.invoke`` on a process with
        # an async AgentAction raises a clear TypeError from LangGraph
        # pointing callers at ``ainvoke`` / ``run_process``.
        graph.add_node(node_id, node_fn_async)  # type: ignore[arg-type]
    else:

        def node_fn_sync(state: dict[str, Any]) -> dict[str, Any]:
            construct, prompt, instructions, run_ctx, model_input = _prepare(state)
            redaction = run_ctx.telemetry.redaction if run_ctx.telemetry is not None else None

            with emit_span(
                name=f"agent_foundry.AgentAction.{action.name}",
                construct_type="AgentAction",
                construct_name=action.name,
                input_model=model_input,
                run_id=run_ctx.run_id,
                redaction=redaction,
            ) as handle:
                handle.set_operation_name("chat")
                result = executor(
                    construct=construct,
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


def _compile_ai_call(
    graph: StateGraph,
    action: AICall,
    ctx: CompileContext,
) -> CompileResult:
    node_id = ctx.prefix
    label = action.name or node_id
    input_type, output_type = get_type_args(action)

    executor = action.executor

    if executor is not None and not _is_async_callable(executor):
        raise ConstructCompilationError(
            f"AICall {node_id}: executor must be async (async def or class with async __call__)",
            construct_type=node_id,
        )

    def _validate_typed(result: Any) -> BaseModel:
        if not isinstance(result, output_type):
            raise ConstructCompilationError(
                f"AICall {node_id}: executor returned "
                f"{type(result).__name__}, expected {output_type.__name__}",
                construct_type=node_id,
            )
        return result

    async def node_fn(state: dict[str, Any]) -> dict[str, Any]:
        model_input = _validate_scoped_input(state, input_type, node_id)

        ctx_opt = current_run_context.get()
        redaction = (
            ctx_opt.telemetry.redaction
            if ctx_opt is not None and ctx_opt.telemetry is not None
            else None
        )
        run_id = ctx_opt.run_id if ctx_opt is not None else node_id

        if ctx_opt is not None:
            ctx_opt.lifecycle_writer.append(
                LifecycleEvent.AI_CALL_STARTED,
                node_id=node_id,
                name=label,
            )

        with emit_span(
            name=f"agent_foundry.AICall.{label}",
            construct_type="AICall",
            construct_name=label,
            input_model=model_input,
            run_id=run_id,
            redaction=redaction,
        ) as handle:
            handle.set_operation_name("chat")
            usage: TokenUsage | None = None
            try:
                if executor is None:
                    call_result = await invoke_ai_call(construct=action, model_input=model_input)
                    result = call_result.output
                    usage = call_result.usage
                else:
                    result = await executor(construct=action, model_input=model_input)
                typed = _validate_typed(result)
            except TypeError as exc:
                # TypeError here typically means the executor's return value was not
                # awaitable — e.g. a sync callable that passed the _is_async_callable
                # check via __call__ but whose invocation returned a plain object.
                # This can happen if __call__ is not actually async despite the class
                # structure suggesting it is.
                if ctx_opt is not None:
                    ctx_opt.lifecycle_writer.append(
                        LifecycleEvent.AI_CALL_FAILED,
                        node_id=node_id,
                        name=label,
                        reason=str(exc),
                    )
                raise ConstructCompilationError(
                    f"AICall {node_id}: {exc}",
                    construct_type=node_id,
                ) from exc
            except Exception as exc:
                if ctx_opt is not None:
                    ctx_opt.lifecycle_writer.append(
                        LifecycleEvent.AI_CALL_FAILED,
                        node_id=node_id,
                        name=label,
                        reason=str(exc),
                    )
                raise
            handle.set_output(typed)
            if ctx_opt is not None:
                usage_fields: dict[str, Any] = {}
                if usage is not None:
                    usage_fields["usage"] = usage.model_dump()
                    usage_fields["num_turns"] = 1
                ctx_opt.lifecycle_writer.append(
                    LifecycleEvent.AI_CALL_COMPLETED,
                    node_id=node_id,
                    name=label,
                    **usage_fields,
                )
            return typed.model_dump()

    graph.add_node(node_id, node_fn)  # type: ignore[arg-type]
    return CompileResult(node_id, node_id)


register_compiler(AICall, _compile_ai_call)
