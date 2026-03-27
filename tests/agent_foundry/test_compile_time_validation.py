"""Tests for compile-time validation of node I/O contracts against state_schema.

PR 2: Node inputs_schema/outputs_schema validated against state_schema at compile time.
"""

import pytest

from agent_foundry.planner.errors import SchemaContractError
from agent_foundry.planner.validators import validate_plan
from agent_foundry.planner.wiring_plan import GraphWiringPlan


def _state_schema(*keys: str) -> dict:
    return {
        "type": "object",
        "properties": {k: {"type": "string"} for k in keys},
    }


def _plan_with_node_io(
    state_schema: dict | None = None,
    inputs_schema: dict | None = None,
    outputs_schema: dict | None = None,
) -> GraphWiringPlan:
    return GraphWiringPlan(
        goal="test",
        nodes=[
            {
                "id": "n1",
                "role": "rag_retriever",
                "config": {},
                "inputs_schema": inputs_schema,
                "outputs_schema": outputs_schema,
            }
        ],
        edges=[],
        entry_point="n1",
        state_schema=state_schema,
        role_versions={"rag_retriever": "1.0.0"},
    )


class TestNodeOutputAgainstStateSchema:
    """Node output keys must be a subset of state_schema properties."""

    def test_given_output_key_in_state_schema_when_validated_then_passes(self, registry):
        plan = _plan_with_node_io(
            state_schema=_state_schema("result"),
            outputs_schema=_state_schema("result"),
        )
        validate_plan(plan, registry)

    def test_given_output_key_not_in_state_schema_when_validated_then_raises(self, registry):
        plan = _plan_with_node_io(
            state_schema=_state_schema("result"),
            outputs_schema=_state_schema("bogus"),
        )
        with pytest.raises(SchemaContractError, match="bogus"):
            validate_plan(plan, registry)

    def test_given_no_outputs_schema_when_validated_then_passes(self, registry):
        plan = _plan_with_node_io(
            state_schema=_state_schema("result"),
            outputs_schema=None,
        )
        validate_plan(plan, registry)


class TestNodeInputAgainstStateSchema:
    """Node input keys must exist in state_schema properties."""

    def test_given_input_key_in_state_schema_when_validated_then_passes(self, registry):
        plan = _plan_with_node_io(
            state_schema=_state_schema("input_data"),
            inputs_schema=_state_schema("input_data"),
        )
        validate_plan(plan, registry)

    def test_given_input_key_not_in_state_schema_when_validated_then_raises(self, registry):
        plan = _plan_with_node_io(
            state_schema=_state_schema("input_data"),
            inputs_schema=_state_schema("missing_key"),
        )
        with pytest.raises(SchemaContractError, match="missing_key"):
            validate_plan(plan, registry)


class TestNoStateSchemaSkipsValidation:
    """Without state_schema, node I/O validation is skipped."""

    def test_given_no_state_schema_when_validated_then_passes(self, registry):
        plan = _plan_with_node_io(
            state_schema=None,
            outputs_schema=_state_schema("anything"),
        )
        validate_plan(plan, registry)


class TestStateMappingAlignment:
    """state_mapping keys must align with parent and subgraph schemas."""

    def test_given_valid_mapping_when_validated_then_passes(self, registry):
        plan = GraphWiringPlan(
            goal="test",
            nodes=[
                {
                    "id": "kernel",
                    "subgraph": {
                        "goal": "sub",
                        "nodes": [{"id": "w", "role": "rag_retriever", "config": {}}],
                        "edges": [],
                        "entry_point": "w",
                        "state_schema": _state_schema("sub_key", "sub_out"),
                        "role_versions": {"rag_retriever": "1.0.0"},
                    },
                    "state_mapping": {
                        "input": {"parent_key": "sub_key"},
                        "output": {"sub_out": "parent_out"},
                    },
                }
            ],
            edges=[],
            entry_point="kernel",
            state_schema=_state_schema("parent_key", "parent_out"),
        )
        validate_plan(plan, registry)

    def test_given_parent_input_key_not_in_parent_schema_when_validated_then_raises(self, registry):
        plan = GraphWiringPlan(
            goal="test",
            nodes=[
                {
                    "id": "kernel",
                    "subgraph": {
                        "goal": "sub",
                        "nodes": [{"id": "w", "role": "rag_retriever", "config": {}}],
                        "edges": [],
                        "entry_point": "w",
                        "state_schema": _state_schema("sub_key"),
                        "role_versions": {"rag_retriever": "1.0.0"},
                    },
                    "state_mapping": {
                        "input": {"missing_parent_key": "sub_key"},
                        "output": {},
                    },
                }
            ],
            edges=[],
            entry_point="kernel",
            state_schema=_state_schema("parent_key"),
        )
        with pytest.raises(SchemaContractError, match="missing_parent_key"):
            validate_plan(plan, registry)

    def test_given_subgraph_input_key_not_in_subgraph_schema_when_validated_then_raises(
        self, registry
    ):
        plan = GraphWiringPlan(
            goal="test",
            nodes=[
                {
                    "id": "kernel",
                    "subgraph": {
                        "goal": "sub",
                        "nodes": [{"id": "w", "role": "rag_retriever", "config": {}}],
                        "edges": [],
                        "entry_point": "w",
                        "state_schema": _state_schema("actual_sub_key"),
                        "role_versions": {"rag_retriever": "1.0.0"},
                    },
                    "state_mapping": {
                        "input": {"parent_key": "wrong_sub_key"},
                        "output": {},
                    },
                }
            ],
            edges=[],
            entry_point="kernel",
            state_schema=_state_schema("parent_key"),
        )
        with pytest.raises(SchemaContractError, match="wrong_sub_key"):
            validate_plan(plan, registry)
