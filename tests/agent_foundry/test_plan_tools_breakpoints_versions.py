"""S3.4 — Tool calling contract; S3.5 — Breakpoints/persistence; S3.6 — Versioning + loops.

S3.4: tool_calling node requires non-empty tools list with unique names.
S3.5: breakpoints reference existing nodes; persistence has required fields.
S3.6: role_versions must cover all node types; loops require termination.
"""

import pytest
from pydantic import ValidationError

from agent_foundry.planner.errors import PlanValidationError
from agent_foundry.planner.validators import validate_plan

from .conftest import make_plan as _make_plan

# --- S3.4: Tool Calling Contract ---


class TestToolCallingContract:
    """tool_calling nodes require tools list with unique names."""

    def test_tool_calling_without_tools_fails(self, registry):
        plan = _make_plan(
            nodes=[
                {"id": "n1", "role": "tool_calling"},
            ],
            edges=[],
            entry_point="n1",
            tools=[],
            role_versions={"tool_calling": "1.0.0"},
        )
        with pytest.raises(PlanValidationError, match="tool"):
            validate_plan(plan, registry)

    def test_duplicate_tool_names_fails(self, registry):
        plan = _make_plan(
            nodes=[
                {"id": "n1", "role": "tool_calling"},
            ],
            edges=[],
            entry_point="n1",
            tools=[
                {"name": "calc", "args_schema": {}},
                {"name": "calc", "args_schema": {}},
            ],
            role_versions={"tool_calling": "1.0.0"},
        )
        with pytest.raises(PlanValidationError, match=r"duplicate.*tool"):
            validate_plan(plan, registry)

    def test_tool_calling_with_valid_tools_passes(self, registry):
        plan = _make_plan(
            nodes=[
                {"id": "n1", "role": "tool_calling"},
            ],
            edges=[],
            entry_point="n1",
            tools=[
                {"name": "calc", "args_schema": {"type": "object"}},
            ],
            role_versions={"tool_calling": "1.0.0"},
        )
        validate_plan(plan, registry)  # Should not raise


# --- S3.5: Breakpoints and Persistence ---


class TestBreakpoints:
    """Breakpoints must reference existing nodes."""

    def test_breakpoint_to_missing_node_fails(self, registry):
        plan = _make_plan(breakpoints=["nonexistent_node"])
        with pytest.raises(PlanValidationError, match="breakpoint"):
            validate_plan(plan, registry)

    def test_breakpoint_to_existing_node_passes(self, registry):
        plan = _make_plan(breakpoints=["n1"])
        validate_plan(plan, registry)


class TestPersistenceValidation:
    """Persistence config must have required non-empty fields."""

    def test_persistence_missing_backend_fails(self):
        with pytest.raises(ValidationError, match="backend"):
            _make_plan(persistence={"thread_id": "t1"})

    def test_persistence_missing_thread_id_fails(self):
        with pytest.raises(ValidationError, match="thread_id"):
            _make_plan(persistence={"backend": "sqlite"})

    def test_valid_persistence_passes(self, registry):
        plan = _make_plan(persistence={"backend": "sqlite", "thread_id": "t1"})
        validate_plan(plan, registry)


# --- S3.6: Versioning + Loop Termination ---


class TestRoleVersionsCoverage:
    """role_versions must cover all node types."""

    def test_missing_version_entry_fails(self, registry):
        plan = _make_plan(role_versions={"rag_retriever": "1.0.0"})
        # schema_validator is missing from versions
        with pytest.raises(PlanValidationError, match="version"):
            validate_plan(plan, registry)

    def test_all_versions_covered_passes(self, registry):
        plan = _make_plan()
        validate_plan(plan, registry)


class TestLoopTermination:
    """Loops require termination condition or max iterations."""

    def test_loop_without_termination_fails(self, registry):
        plan = _make_plan(
            edges=[
                {"source": "n1", "target": "n2"},
                {"source": "n2", "target": "n1"},  # Loop!
            ]
        )
        with pytest.raises(PlanValidationError, match=r"loop.*termination|cycle"):
            validate_plan(plan, registry)

    def test_loop_with_condition_passes(self, registry):
        plan = _make_plan(
            edges=[
                {"source": "n1", "target": "n2"},
                {"source": "n2", "target": "n1", "condition": "needs_retry"},
            ],
            nodes=[
                {"id": "n1", "role": "rag_retriever", "config": {"max_iterations": 5}},
                {"id": "n2", "role": "schema_validator"},
            ],
        )
        validate_plan(plan, registry)


# --- S3.7: Subgraph Node Validation ---


def _subgraph_plan_data(**overrides) -> dict:
    """Build a valid subgraph plan dict."""
    defaults = {
        "goal": "kernel",
        "nodes": [
            {"id": "inner1", "role": "rag_retriever"},
        ],
        "edges": [],
        "entry_point": "inner1",
        "role_versions": {"rag_retriever": "1.0.0"},
    }
    defaults.update(overrides)
    return defaults


class TestSubgraphValidation:
    """Plans with subgraph nodes are validated recursively."""

    def test_given_valid_subgraph_node_when_validated_then_passes(self, registry):
        plan = _make_plan(
            nodes=[
                {"id": "n1", "role": "rag_retriever"},
                {
                    "id": "n2",
                    "subgraph": _subgraph_plan_data(),
                    "state_mapping": {"input": {}, "output": {}},
                },
            ],
            edges=[{"source": "n1", "target": "n2"}],
            role_versions={"rag_retriever": "1.0.0"},
        )
        validate_plan(plan, registry)

    def test_given_subgraph_with_unknown_role_when_validated_then_fails(self, registry):
        plan = _make_plan(
            nodes=[
                {"id": "n1", "role": "rag_retriever"},
                {
                    "id": "n2",
                    "subgraph": _subgraph_plan_data(
                        nodes=[{"id": "bad", "role": "nonexistent_role"}],
                        entry_point="bad",
                        role_versions={"nonexistent_role": "1.0.0"},
                    ),
                    "state_mapping": {"input": {}, "output": {}},
                },
            ],
            edges=[{"source": "n1", "target": "n2"}],
            role_versions={"rag_retriever": "1.0.0"},
        )
        from agent_foundry.planner.errors import UnknownRoleError

        with pytest.raises(UnknownRoleError, match="nonexistent_role"):
            validate_plan(plan, registry)

    def test_given_subgraph_with_dangling_edge_when_validated_then_fails(self, registry):
        plan = _make_plan(
            nodes=[
                {"id": "n1", "role": "rag_retriever"},
                {
                    "id": "n2",
                    "subgraph": _subgraph_plan_data(
                        edges=[{"source": "inner1", "target": "ghost"}],
                    ),
                    "state_mapping": {"input": {}, "output": {}},
                },
            ],
            edges=[{"source": "n1", "target": "n2"}],
            role_versions={"rag_retriever": "1.0.0"},
        )
        from agent_foundry.planner.errors import DanglingEdgeError

        with pytest.raises(DanglingEdgeError, match="ghost"):
            validate_plan(plan, registry)

    def test_given_subgraph_node_when_role_versions_checked_then_subgraph_skipped(
        self, registry
    ):
        """Subgraph nodes don't need entries in the parent's role_versions."""
        plan = _make_plan(
            nodes=[
                {"id": "n1", "role": "rag_retriever"},
                {
                    "id": "n2",
                    "subgraph": _subgraph_plan_data(),
                    "state_mapping": {"input": {}, "output": {}},
                },
            ],
            edges=[{"source": "n1", "target": "n2"}],
            role_versions={"rag_retriever": "1.0.0"},
        )
        validate_plan(plan, registry)
