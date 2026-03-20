"""S3.1 — Pydantic model + JSON round-trip (happy path).

Tests: valid JSON parses; .model_dump_json() round-trips with no field loss.
"""

import pytest
from pydantic import ValidationError

from agent_foundry.planner.wiring_plan import (
    GraphWiringPlan,
    NodeDef,
    StateMappingDef,
)


def _minimal_plan() -> dict:
    return {
        "goal": "decision-support",
        "nodes": [
            {
                "id": "retriever",
                "role": "rag_retriever",
                "config": {"k": 3},
            },
            {
                "id": "output",
                "role": "structured_output_pydantic",
                "config": {},
            },
        ],
        "edges": [
            {"source": "retriever", "target": "output"},
        ],
        "entry_point": "retriever",
        "role_versions": {
            "rag_retriever": "1.0.0",
            "structured_output_pydantic": "1.0.0",
        },
    }


class TestParseValidPlan:
    """Valid JSON parses into GraphWiringPlan."""

    def test_parse_minimal_plan(self):
        plan = GraphWiringPlan(**_minimal_plan())
        assert plan.goal == "decision-support"

    def test_parse_nodes(self):
        plan = GraphWiringPlan(**_minimal_plan())
        assert len(plan.nodes) == 2
        assert plan.nodes[0].id == "retriever"
        assert plan.nodes[0].role == "rag_retriever"

    def test_parse_edges(self):
        plan = GraphWiringPlan(**_minimal_plan())
        assert len(plan.edges) == 1
        assert plan.edges[0].source == "retriever"
        assert plan.edges[0].target == "output"

    def test_parse_entry_point(self):
        plan = GraphWiringPlan(**_minimal_plan())
        assert plan.entry_point == "retriever"

    def test_parse_role_versions(self):
        plan = GraphWiringPlan(**_minimal_plan())
        assert plan.role_versions["rag_retriever"] == "1.0.0"


class TestJsonRoundTrip:
    """model_dump_json() round-trips with no field loss."""

    def test_round_trip_no_field_loss(self):
        plan = GraphWiringPlan(**_minimal_plan())
        json_str = plan.model_dump_json()
        reconstructed = GraphWiringPlan.model_validate_json(json_str)
        assert reconstructed == plan

    def test_dict_round_trip(self):
        plan = GraphWiringPlan(**_minimal_plan())
        dumped = plan.model_dump()
        reconstructed = GraphWiringPlan(**dumped)
        assert reconstructed == plan


class TestOptionalFields:
    """Optional fields have correct defaults."""

    def test_optional_fields_have_expected_defaults(self):
        plan = GraphWiringPlan(**_minimal_plan())
        assert plan.tools == []
        assert plan.breakpoints == []
        assert plan.persistence is None

    def test_plan_with_tools(self):
        data = _minimal_plan()
        data["tools"] = [{"name": "calculator", "args_schema": {"type": "object"}}]
        plan = GraphWiringPlan(**data)
        assert len(plan.tools) == 1
        assert plan.tools[0].name == "calculator"

    def test_plan_with_persistence(self):
        data = _minimal_plan()
        data["persistence"] = {"backend": "sqlite", "thread_id": "t1"}
        plan = GraphWiringPlan(**data)
        assert plan.persistence.backend == "sqlite"


def _minimal_subgraph_plan() -> dict:
    """A subgraph plan for use in subgraph node tests."""
    return {
        "goal": "kernel",
        "nodes": [
            {"id": "worker", "role": "test_role", "config": {}},
        ],
        "edges": [],
        "entry_point": "worker",
        "role_versions": {"test_role": "1.0.0"},
    }


class TestSubgraphNodeDef:
    """NodeDef supports subgraph nodes with state mapping."""

    def test_given_subgraph_and_state_mapping_when_parsed_then_node_created(self):
        node = NodeDef(
            id="kernel",
            subgraph=GraphWiringPlan(**_minimal_subgraph_plan()),
            state_mapping=StateMappingDef(
                input={"parent_key": "sub_key"},
                output={"sub_out": "parent_out"},
            ),
        )
        assert node.subgraph is not None
        assert node.role is None
        assert node.state_mapping.input == {"parent_key": "sub_key"}
        assert node.state_mapping.output == {"sub_out": "parent_out"}

    def test_given_both_role_and_subgraph_when_parsed_then_validation_error(self):
        with pytest.raises(ValidationError, match="mutually exclusive"):
            NodeDef(
                id="bad",
                role="some_role",
                subgraph=GraphWiringPlan(**_minimal_subgraph_plan()),
                state_mapping=StateMappingDef(),
            )

    def test_given_neither_role_nor_subgraph_when_parsed_then_validation_error(self):
        with pytest.raises(ValidationError, match="must have either"):
            NodeDef(id="empty")

    def test_given_subgraph_without_state_mapping_when_parsed_then_validation_error(self):
        with pytest.raises(ValidationError, match="state_mapping.*required"):
            NodeDef(
                id="no_mapping",
                subgraph=GraphWiringPlan(**_minimal_subgraph_plan()),
            )

    def test_given_role_node_when_parsed_then_subgraph_and_mapping_are_none(self):
        node = NodeDef(id="simple", role="test_role")
        assert node.subgraph is None
        assert node.state_mapping is None


class TestSubgraphPlanRoundTrip:
    """Plans with subgraph nodes serialize and deserialize correctly."""

    def test_given_plan_with_subgraph_node_when_json_round_tripped_then_equal(self):
        data = _minimal_plan()
        data["nodes"].append(
            {
                "id": "kernel",
                "subgraph": _minimal_subgraph_plan(),
                "state_mapping": {
                    "input": {"parent_in": "sub_in"},
                    "output": {"sub_out": "parent_out"},
                },
            }
        )
        data["edges"].append({"source": "output", "target": "kernel"})
        plan = GraphWiringPlan(**data)
        json_str = plan.model_dump_json()
        reconstructed = GraphWiringPlan.model_validate_json(json_str)
        assert reconstructed == plan

    def test_given_plan_with_subgraph_node_when_dict_round_tripped_then_equal(self):
        data = _minimal_plan()
        data["nodes"].append(
            {
                "id": "kernel",
                "subgraph": _minimal_subgraph_plan(),
                "state_mapping": {"input": {}, "output": {}},
            }
        )
        plan = GraphWiringPlan(**data)
        dumped = plan.model_dump()
        reconstructed = GraphWiringPlan(**dumped)
        assert reconstructed == plan


class TestStateMappingDef:
    """StateMappingDef defaults and serialization."""

    def test_given_empty_mapping_when_created_then_defaults_to_empty_dicts(self):
        mapping = StateMappingDef()
        assert mapping.input == {}
        assert mapping.output == {}

    def test_given_populated_mapping_when_round_tripped_then_equal(self):
        mapping = StateMappingDef(
            input={"a": "b", "c": "d"},
            output={"x": "y"},
        )
        dumped = mapping.model_dump()
        reconstructed = StateMappingDef(**dumped)
        assert reconstructed == mapping
