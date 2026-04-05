"""Primitive compiler: translates typed primitive graphs into executable LangGraph."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, ValidationError

from agent_foundry.primitives.errors import PrimitiveCompilationError
from agent_foundry.primitives.models import (
    FunctionAction,
    Primitive,
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
    node_id = prefix
    input_type, _ = get_type_args(action)
    fn = action.function

    def node_fn(state: dict[str, Any]) -> dict[str, Any]:
        _validate_boundary(state, input_type, node_id)
        model_input = input_type.model_validate(state)
        result = fn(model_input)
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
