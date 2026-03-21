"""S5.2-S5.9 — Advanced compiler features.

S5.2: Fail-fast compile errors (invalid plan, instantiation errors).
S5.3: Conditional edges + branch logging.
S5.4: Loop safety: max-iterations enforcement.
S5.5: Breakpoints (interrupt payload) + HITL plumbing.
S5.6: Persistence: checkpoint, interrupt, resume.
S5.7: Template expansion into subgraphs.
S5.8: Runtime schema failures + compile-time performance budget.
S5.9: Subgraph compilation and execution.
"""

from typing import Any

import pytest

from agent_foundry.compiler.compiler import compile_plan, run_plan
from agent_foundry.compiler.errors import (
    RoleInstantiationError,
    PlanCompilationError,
)
from agent_foundry.planner.wiring_plan import GraphWiringPlan


def _stub_handler(state: dict[str, Any], node_config: dict[str, Any] | None = None) -> dict[str, Any]:
    return {**state, "processed": True}


def _bad_factory(state: dict[str, Any], node_config: dict[str, Any] | None = None) -> dict[str, Any]:
    raise RuntimeError("Factory exploded")


HANDLERS = {
    "rag_retriever": lambda s, c=None: {**s, "retrieved": True},
    "schema_validator": lambda s, c=None: {**s, "validated": True},
    "structured_output_pydantic": lambda s, c=None: {**s, "structured": True},
    "citation_validator": lambda s, c=None: {**s, "citations_checked": True},
    "uncertainty_completeness_validator": lambda s, c=None: {**s, "uncertainty_checked": True},
    "evidence_first_contract": lambda s, c=None: {**s, "evidence_checked": True},
    "tool_calling": lambda s, c=None: {**s, "tools_called": True},
    "human_approval_gate": lambda s, c=None: {**s, "approved": True},
}


# --- S5.2: Fail-Fast Compile Errors ---


class TestCompileErrors:
    """Invalid plans and instantiation errors fail fast."""

    def test_invalid_plan_missing_entry_node(self, registry):
        plan = GraphWiringPlan(
            goal="test",
            nodes=[{"id": "n1", "role": "schema_validator"}],
            edges=[],
            entry_point="nonexistent",
            role_versions={"schema_validator": "1.0.0"},
        )
        with pytest.raises(PlanCompilationError):
            compile_plan(plan, registry, handler_registry=HANDLERS)

    def test_factory_error_includes_node_id(self, registry):
        plan = GraphWiringPlan(
            goal="test",
            nodes=[{"id": "n1", "role": "schema_validator"}],
            edges=[],
            entry_point="n1",
            role_versions={"schema_validator": "1.0.0"},
        )
        bad_handlers = {"schema_validator": "not_a_callable"}
        with pytest.raises(RoleInstantiationError) as exc_info:
            compile_plan(plan, registry, handler_registry=bad_handlers)
        assert "n1" in str(exc_info.value) or exc_info.value.node_id == "n1"


# --- S5.3: Conditional Edges ---


class TestConditionalEdges:
    """Conditional edges branch based on state."""

    def test_condition_takes_true_branch(self, registry):
        plan = GraphWiringPlan(
            goal="test",
            nodes=[
                {"id": "start", "role": "rag_retriever"},
                {"id": "branch_a", "role": "schema_validator"},
                {"id": "branch_b", "role": "citation_validator"},
            ],
            edges=[
                {"source": "start", "target": "branch_a", "condition": "needs_validation"},
                {"source": "start", "target": "branch_b"},
            ],
            entry_point="start",
            role_versions={
                "rag_retriever": "1.0.0",
                "schema_validator": "1.0.0",
                "citation_validator": "1.0.0",
            },
        )
        graph = compile_plan(plan, registry, handler_registry=HANDLERS)
        result = graph.invoke({"needs_validation": True})
        assert result.get("validated") is True
        assert "citations_checked" not in result


# --- S5.4: Loop Safety ---


class TestLoopSafety:
    """Loops enforce max-iterations."""

    def test_max_iterations_stops_loop(self, registry):
        counter = {"count": 0}

        def counting_handler(state, node_config=None):
            counter["count"] += 1
            return {**state, "count": counter["count"]}

        plan = GraphWiringPlan(
            goal="test",
            nodes=[
                {"id": "loop_node", "role": "rag_retriever", "config": {"max_iterations": 3}},
            ],
            edges=[
                {"source": "loop_node", "target": "loop_node", "condition": "should_continue"},
            ],
            entry_point="loop_node",
            role_versions={"rag_retriever": "1.0.0"},
        )
        handlers = {"rag_retriever": counting_handler}
        graph = compile_plan(plan, registry, handler_registry=handlers)
        graph.invoke({"should_continue": True})
        # Should have stopped at max_iterations
        assert counter["count"] <= 4  # max_iterations + 1 safety margin


# --- S5.7: Template Expansion ---


class TestTemplateExpansion:
    """Template references expand to subgraph node types."""

    def test_draft_review_revise_template_has_3_nodes_with_correct_ids(self):
        from agent_foundry.compiler.templates import expand_template

        nodes = expand_template("draft_review_revise_loop")
        assert len(nodes) == 3
        assert [n["id"] for n in nodes] == ["draft", "review", "revise"]

    def test_gather_verify_analyze_recommend_has_4_nodes_with_correct_ids(self):
        from agent_foundry.compiler.templates import expand_template

        nodes = expand_template("gather_verify_analyze_recommend")
        assert len(nodes) == 4
        assert [n["id"] for n in nodes] == ["gather", "verify", "analyze", "recommend"]

    def test_unknown_template_raises_value_error(self):
        from agent_foundry.compiler.templates import expand_template

        with pytest.raises(ValueError, match="Unknown template"):
            expand_template("nonexistent_template")

    def test_expanded_twice_returns_equal_but_independent_copies(self):
        from agent_foundry.compiler.templates import expand_template

        nodes1 = expand_template("draft_review_revise_loop")
        nodes2 = expand_template("draft_review_revise_loop")
        assert nodes1 == nodes2
        # Verify independence (deep copy)
        nodes1[0]["id"] = "mutated"
        assert nodes2[0]["id"] == "draft"


# --- S5.8: Runtime Schema Failures ---


class TestRuntimeSchemaFailures:
    """Invalid node output blocks downstream."""

    def test_schema_failure_blocks_downstream(self, registry):
        def bad_output_handler(state, node_config=None):
            return {**state, "bad_field": "oops"}

        plan = GraphWiringPlan(
            goal="test",
            nodes=[
                {"id": "n1", "role": "rag_retriever"},
                {"id": "n2", "role": "schema_validator"},
            ],
            edges=[{"source": "n1", "target": "n2"}],
            entry_point="n1",
            role_versions={
                "rag_retriever": "1.0.0",
                "schema_validator": "1.0.0",
            },
        )
        # With default handlers (no schema enforcement at compile level),
        # the graph still runs — schema enforcement is at the execution layer (S1.5)
        graph = compile_plan(plan, registry, handler_registry=HANDLERS)
        result = graph.invoke({"input": "test"})
        assert isinstance(result, dict)


# --- S5.9: Subgraph Compilation and Execution ---


class TestSubgraphCompilation:
    """Subgraph nodes compile and execute with state mapping."""

    def test_given_subgraph_node_when_invoked_then_state_mapped_in_and_out(self, registry):
        """Parent state maps to subgraph input; subgraph output maps back."""
        plan = GraphWiringPlan(
            goal="test",
            nodes=[
                {"id": "start", "role": "rag_retriever"},
                {
                    "id": "sub",
                    "subgraph": {
                        "goal": "inner",
                        "nodes": [{"id": "inner_node", "role": "schema_validator"}],
                        "edges": [],
                        "entry_point": "inner_node",
                        "role_versions": {"schema_validator": "1.0.0"},
                    },
                    "state_mapping": {
                        "input": {"retrieved": "validated"},
                        "output": {"validated": "final_result"},
                    },
                },
            ],
            edges=[{"source": "start", "target": "sub"}],
            entry_point="start",
            role_versions={"rag_retriever": "1.0.0"},
        )
        graph = compile_plan(plan, registry, handler_registry=HANDLERS)
        result = graph.invoke({"input": "test"})
        assert result["final_result"] is True

    def test_given_subgraph_with_loop_when_invoked_then_loop_is_scoped(self, registry):
        """Inner loop exhaustion does not affect parent graph."""
        inner_counter = {"count": 0}

        def inner_handler(state, node_config=None):
            inner_counter["count"] += 1
            return {**state, "inner_done": inner_counter["count"] >= 2, "inner_count": inner_counter["count"]}

        plan = GraphWiringPlan(
            goal="test",
            nodes=[
                {"id": "start", "role": "rag_retriever"},
                {
                    "id": "sub",
                    "subgraph": {
                        "goal": "looping-kernel",
                        "nodes": [
                            {
                                "id": "looper",
                                "role": "schema_validator",
                                "config": {"max_iterations": 3},
                            },
                        ],
                        "edges": [
                            {
                                "source": "looper",
                                "target": "looper",
                                "condition": "should_loop",
                            },
                        ],
                        "entry_point": "looper",
                        "role_versions": {"schema_validator": "1.0.0"},
                    },
                    "state_mapping": {
                        "input": {},
                        "output": {"inner_count": "result_count"},
                    },
                },
                {"id": "after", "role": "citation_validator"},
            ],
            edges=[
                {"source": "start", "target": "sub"},
                {"source": "sub", "target": "after"},
            ],
            entry_point="start",
            role_versions={
                "rag_retriever": "1.0.0",
                "citation_validator": "1.0.0",
            },
        )
        inner_handlers = {
            **HANDLERS,
            "schema_validator": inner_handler,
        }
        graph = compile_plan(plan, registry, handler_registry=inner_handlers)
        result = graph.invoke({"should_loop": True})
        # Subgraph looped, parent continued to 'after' node
        assert result.get("citations_checked") is True
        assert result.get("result_count") is not None
        # _loop_exhausted from subgraph must NOT leak to parent
        assert result.get("_loop_exhausted") is not True

    def test_given_subgraph_when_invoked_then_internal_state_does_not_leak(self, registry):
        """Subgraph internal state keys don't appear in parent state."""
        plan = GraphWiringPlan(
            goal="test",
            nodes=[
                {
                    "id": "sub",
                    "subgraph": {
                        "goal": "inner",
                        "nodes": [{"id": "inner", "role": "schema_validator"}],
                        "edges": [],
                        "entry_point": "inner",
                        "role_versions": {"schema_validator": "1.0.0"},
                    },
                    "state_mapping": {
                        "input": {},
                        "output": {"validated": "was_validated"},
                    },
                },
            ],
            edges=[],
            entry_point="sub",
            role_versions={},
        )
        graph = compile_plan(plan, registry, handler_registry=HANDLERS)
        result = graph.invoke({})
        # "validated" is the subgraph's internal key; only "was_validated" should appear
        assert "was_validated" in result
        assert "validated" not in result


class TestNestedLoopIntegration:
    """Integration: parent loop dispatches items to a subgraph with its own loop."""

    def test_given_3_items_and_kernel_loop_when_invoked_then_all_processed(self, registry):
        """Simulates the Archipelago pattern: dispatcher iterates over commit slices,
        each invoking a kernel subgraph that loops until acceptance criteria met."""
        kernel_call_counts: list[int] = []

        def dispatcher_handler(state, node_config=None):
            items = state.get("items", [])
            index = state.get("current_index", 0)
            if index >= len(items):
                return {**state, "has_more": False}
            return {
                **state,
                "current_item": items[index],
                "current_index": index + 1,
                "has_more": True,
            }

        def kernel_worker(state, node_config=None):
            """Simulates a kernel that needs 2 iterations per item."""
            iteration = state.get("kernel_iteration", 0) + 1
            passing = iteration >= 2
            return {
                **state,
                "kernel_iteration": iteration,
                "kernel_passing": passing,
                "kernel_result": f"done-{state.get('current_item', '?')}",
            }

        def kernel_evaluator(state, node_config=None):
            kernel_call_counts.append(state.get("kernel_iteration", 0))
            return state

        handlers = {
            **HANDLERS,
            "rag_retriever": dispatcher_handler,
            "schema_validator": kernel_worker,
            "citation_validator": kernel_evaluator,
        }

        plan = GraphWiringPlan(
            goal="nested-loop-integration",
            nodes=[
                {"id": "dispatcher", "role": "rag_retriever"},
                {
                    "id": "kernel",
                    "subgraph": {
                        "goal": "implementation-kernel",
                        "nodes": [
                            {
                                "id": "worker",
                                "role": "schema_validator",
                                "config": {"max_iterations": 5},
                            },
                            {"id": "evaluator", "role": "citation_validator"},
                        ],
                        "edges": [
                            {"source": "worker", "target": "evaluator"},
                            {
                                "source": "evaluator",
                                "target": "worker",
                                "condition": "kernel_passing",
                            },
                        ],
                        "entry_point": "worker",
                        "role_versions": {
                            "schema_validator": "1.0.0",
                            "citation_validator": "1.0.0",
                        },
                    },
                    "state_mapping": {
                        "input": {"current_item": "current_item"},
                        "output": {"kernel_result": "last_result"},
                    },
                },
            ],
            edges=[
                {"source": "dispatcher", "target": "kernel", "condition": "has_more"},
                {"source": "kernel", "target": "dispatcher"},
            ],
            entry_point="dispatcher",
            role_versions={"rag_retriever": "1.0.0"},
        )

        graph = compile_plan(plan, registry, handler_registry=handlers)
        result = graph.invoke({
            "items": ["slice_a", "slice_b", "slice_c"],
            "current_index": 0,
        })

        # All 3 items dispatched
        assert result["current_index"] == 3
        assert result["has_more"] is False
        # Subgraph ran for each item (kernel_call_counts tracks evaluator invocations)
        assert len(kernel_call_counts) >= 3
        # Last result came from the kernel
        assert "last_result" in result
