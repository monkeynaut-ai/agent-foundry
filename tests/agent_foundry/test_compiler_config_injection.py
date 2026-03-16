"""Tests for compiler node.config injection into handler state.

Verifies that config fields from GraphWiringPlan nodes (acp_hidden_dirs,
worker_mode, etc.) are injected into the state that handlers receive.
"""

from typing import Any

from agent_foundry.compiler.compiler import compile_plan
from agent_foundry.planner.wiring_plan import GraphWiringPlan


def _make_plan_with_config(config: dict[str, Any]) -> GraphWiringPlan:
    return GraphWiringPlan(
        goal="test-config-injection",
        nodes=[{"id": "n1", "role": "test_role", "config": config}],
        edges=[],
        entry_point="n1",
        role_versions={"test_role": "1.0.0"},
    )


class TestConfigInjection:
    def test_given_node_with_acp_hidden_dirs_when_invoked_then_handler_sees_config_in_state(
        self, registry
    ):
        captured: dict[str, Any] = {}

        def spy(state):
            captured.update(state)
            return state

        plan = _make_plan_with_config({"acp_hidden_dirs": ["/workspace/src"]})
        graph = compile_plan(plan, registry, handler_registry={"test_role": spy})
        graph.invoke({"input": "test"})

        assert captured.get("acp_hidden_dirs") == ["/workspace/src"]

    def test_given_node_with_worker_mode_when_invoked_then_handler_sees_config_in_state(
        self, registry
    ):
        captured: dict[str, Any] = {}

        def spy(state):
            captured.update(state)
            return state

        plan = _make_plan_with_config({"worker_mode": "unit_test_writer"})
        graph = compile_plan(plan, registry, handler_registry={"test_role": spy})
        graph.invoke({"input": "test"})

        assert captured.get("worker_mode") == "unit_test_writer"

    def test_given_node_with_empty_config_when_invoked_then_state_unchanged(self, registry):
        captured: dict[str, Any] = {}

        def spy(state):
            captured.update(state)
            return state

        plan = _make_plan_with_config({})
        graph = compile_plan(plan, registry, handler_registry={"test_role": spy})
        graph.invoke({"input": "test"})

        assert captured.get("input") == "test"
        assert "acp_hidden_dirs" not in captured
        assert "worker_mode" not in captured

    def test_given_node_with_max_iterations_and_config_when_invoked_then_both_work(self, registry):
        call_count = {"n": 0}
        captured: dict[str, Any] = {}

        def spy(state):
            call_count["n"] += 1
            captured.update(state)
            return state

        plan = _make_plan_with_config(
            {
                "acp_hidden_dirs": ["/workspace/src"],
                "max_iterations": 2,
            }
        )
        graph = compile_plan(plan, registry, handler_registry={"test_role": spy})
        graph.invoke({"input": "test"})

        assert captured.get("acp_hidden_dirs") == ["/workspace/src"]
