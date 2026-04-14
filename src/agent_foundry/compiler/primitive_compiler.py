"""Primitive compiler: translates typed primitive graphs into executable LangGraph."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypedDict

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

# -- Compiler registry --

type CompilerFn = Callable[[StateGraph, Primitive, str, list[str]], tuple[str, str]]

_compiler_registry: dict[type[Primitive], CompilerFn] = {}


def register_compiler(prim_type: type[Primitive], compiler_fn: CompilerFn) -> None:
    """Register a compiler function for a primitive type."""
    _compiler_registry[prim_type] = compiler_fn


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


def run_primitive_plan(
    plan: PrimitivePlan,
    initial_state: BaseModel | None = None,
    config: dict[str, Any] | None = None,
) -> BaseModel:
    """Compile and execute a PrimitivePlan with typed input/output."""
    _, root_out = get_type_args(plan.root)
    graph = compile_primitive(plan)

    input_dict = initial_state.model_dump() if initial_state is not None else {}
    result_dict = graph.invoke(input_dict, config=config or {})
    return root_out.model_validate(result_dict)


# -- Per-type compilers --


def _compile_function_action(
    graph: StateGraph, action: FunctionAction, prefix: str, gate_ids: list[str]
) -> tuple[str, str]:
    import inspect

    node_id = prefix
    input_type, _ = get_type_args(action)
    fn = action.function
    takes_input = len(inspect.signature(fn).parameters) > 0

    def node_fn(state: dict[str, Any]) -> dict[str, Any]:
        if takes_input:
            _validate_boundary(state, input_type, node_id)
            model_input = input_type.model_validate(state)
            result = fn(model_input)
        else:
            result = fn()
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

    graph.add_node(node_id, seq_node)
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

    graph.add_node(node_id, cond_node)
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

    graph.add_node(node_id, loop_node)
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

    graph.add_node(node_id, retry_node)
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

    def node_fn(state: dict[str, Any]) -> dict[str, Any]:
        _validate_boundary(state, input_type, node_id)
        model_input = input_type.model_validate(state)
        prompt = prompt_builder(model_input)

        result = executor(primitive=action, prompt=prompt)

        if not isinstance(result, output_type):
            raise PrimitiveCompilationError(
                f"AgentAction {node_id}: executor returned "
                f"{type(result).__name__}, expected {output_type.__name__}",
                primitive_type=node_id,
            )

        return result.model_dump()

    graph.add_node(node_id, node_fn)
    return (node_id, node_id)


register_compiler(AgentAction, _compile_agent_action)
