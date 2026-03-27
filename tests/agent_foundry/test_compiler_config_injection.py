"""Tests for compiler node.config injection into handler node_config parameter.

Verifies that config fields from GraphWiringPlan nodes (acp_hidden_dirs,
worker_mode, etc.) are passed via the node_config parameter to handlers,
and do NOT appear in the state dict.
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
        state_schema={"type": "object", "properties": {}, "additionalProperties": True},
        role_versions={"test_role": "1.0.0"},
    )


class TestConfigInjection:
    def test_given_node_with_acp_hidden_dirs_when_invoked_then_handler_sees_config_in_node_config(
        self, registry
    ):
        captured_state: dict[str, Any] = {}
        captured_config: dict[str, Any] | None = None

        def spy(state, node_config=None):
            captured_state.update(state)
            nonlocal captured_config
            captured_config = node_config
            return state

        plan = _make_plan_with_config({"acp_hidden_dirs": ["/workspace/src"]})
        graph = compile_plan(plan, registry, handler_registry={"test_role": spy})
        graph.invoke({"input": "test"})

        assert captured_config is not None
        assert captured_config.get("acp_hidden_dirs") == ["/workspace/src"]
        assert "acp_hidden_dirs" not in captured_state

    def test_given_node_with_worker_mode_when_invoked_then_handler_sees_config_in_node_config(
        self, registry
    ):
        captured_state: dict[str, Any] = {}
        captured_config: dict[str, Any] | None = None

        def spy(state, node_config=None):
            captured_state.update(state)
            nonlocal captured_config
            captured_config = node_config
            return state

        plan = _make_plan_with_config({"worker_mode": "unit_test_writer"})
        graph = compile_plan(plan, registry, handler_registry={"test_role": spy})
        graph.invoke({"input": "test"})

        assert captured_config is not None
        assert captured_config.get("worker_mode") == "unit_test_writer"
        assert "worker_mode" not in captured_state

    def test_given_node_with_empty_config_when_invoked_then_state_unchanged(self, registry):
        captured_state: dict[str, Any] = {}
        captured_config: dict[str, Any] | None = None

        def spy(state, node_config=None):
            captured_state.update(state)
            nonlocal captured_config
            captured_config = node_config
            return state

        plan = _make_plan_with_config({})
        graph = compile_plan(plan, registry, handler_registry={"test_role": spy})
        graph.invoke({"input": "test"})

        assert captured_state.get("input") == "test"
        assert "acp_hidden_dirs" not in captured_state
        assert "worker_mode" not in captured_state

    def test_given_node_with_max_iterations_and_config_when_invoked_then_both_work(self, registry):
        call_count = {"n": 0}
        captured_state: dict[str, Any] = {}
        captured_config: dict[str, Any] | None = None

        def spy(state, node_config=None):
            call_count["n"] += 1
            captured_state.update(state)
            nonlocal captured_config
            captured_config = node_config
            return state

        plan = _make_plan_with_config(
            {
                "acp_hidden_dirs": ["/workspace/src"],
                "max_iterations": 2,
            }
        )
        graph = compile_plan(plan, registry, handler_registry={"test_role": spy})
        graph.invoke({"input": "test"})

        assert captured_config is not None
        assert captured_config.get("acp_hidden_dirs") == ["/workspace/src"]
        assert "acp_hidden_dirs" not in captured_state
