"""S3.1 — Pydantic model + JSON round-trip (happy path).

Tests: valid JSON parses; .model_dump_json() round-trips with no field loss.
"""

from agent_foundry.planner.wiring_plan import (
    GraphWiringPlan,
)


def _minimal_plan() -> dict:
    return {
        "goal": "decision-support",
        "nodes": [
            {
                "id": "retriever",
                "capability": "rag_retriever",
                "config": {"k": 3},
            },
            {
                "id": "output",
                "capability": "structured_output_pydantic",
                "config": {},
            },
        ],
        "edges": [
            {"source": "retriever", "target": "output"},
        ],
        "entry_point": "retriever",
        "capability_versions": {
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
        assert plan.nodes[0].capability == "rag_retriever"

    def test_parse_edges(self):
        plan = GraphWiringPlan(**_minimal_plan())
        assert len(plan.edges) == 1
        assert plan.edges[0].source == "retriever"
        assert plan.edges[0].target == "output"

    def test_parse_entry_point(self):
        plan = GraphWiringPlan(**_minimal_plan())
        assert plan.entry_point == "retriever"

    def test_parse_capability_versions(self):
        plan = GraphWiringPlan(**_minimal_plan())
        assert plan.capability_versions["rag_retriever"] == "1.0.0"


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
