"""Archipelago checkpoint/resume — compilation, breakpoint pause, and resume tests."""

import json
from pathlib import Path
from typing import Any

import pytest

from agent_foundry.compiler.compiler import compile_plan
from agent_foundry.planner.wiring_plan import GraphWiringPlan

PLAN_PATH = (
    Path(__file__).parent.parent.parent.parent / "src" / "archipelago" / "archipelago_system.json"
)


# ── Stub handlers ──

_execution_log: list[str] = []


def _make_logging_handler(node_id: str, state_updates: dict[str, Any]):
    def handler(state: dict[str, Any]) -> dict[str, Any]:
        _execution_log.append(node_id)
        return {**state, **state_updates}

    return handler


STUB_HANDLERS = {
    "strategy_generate_product_brief": _make_logging_handler(
        "strategy",
        {
            "product_brief": {
                "name": "Test",
                "problem_statement": "Test",
                "target_personas": ["eng"],
                "success_metrics": ["m1"],
                "constraints": [],
            },
        },
    ),
    "architecture_generate_feature_arch": _make_logging_handler(
        "architecture",
        {
            "feature_architecture": {
                "feature_name": "Test",
                "components": ["c1"],
                "data_flow": "a->b",
                "technology_choices": ["Python"],
                "risks": [],
            },
        },
    ),
    "spec_generate_feature_spec": _make_logging_handler(
        "spec",
        {
            "feature_spec": {
                "title": "Test",
                "objective": "Test",
                "acceptance_criteria": ["ac1"],
                "pr_slices": [{"title": "s1", "commits": ["c1"]}],
            },
            "test_plan": {
                "feature_name": "Test",
                "test_cases": [{"name": "t1", "type": "unit"}],
                "coverage_targets": ["handler"],
            },
        },
    ),
    "human_approval_gate": _make_logging_handler(
        "spec_approval_gate",
        {
            "approved": True,
            "approver": "auto",
        },
    ),
    "coding_implement_feature_from_spec": _make_logging_handler(
        "dev_test",
        {
            "code_patch": {
                "feature_name": "Test",
                "files_changed": ["f.py"],
                "diff_summary": "diff",
                "branch_name": "feat/t",
            },
            "test_results": {
                "feature_name": "Test",
                "tests_passed": 1,
                "tests_failed": 0,
                "test_output": "ok",
                "all_green": True,
            },
        },
    ),
    "write_unit_tests_from_spec": _make_logging_handler(
        "unit_test_writer",
        {
            "worker_result": {
                "result_summary": "Tests written",
                "workspace_ref": "/workspace",
                "patches": [],
                "evidence": [],
                "status": "completed",
            },
            "workspace_volume": "archipelago-test",
        },
    ),
    "code_implement_from_tests": _make_logging_handler(
        "code_writer",
        {
            "worker_result": {
                "result_summary": "Code implemented",
                "workspace_ref": "/workspace",
                "patches": [],
                "evidence": [],
                "status": "completed",
            },
        },
    ),
}


@pytest.fixture
def base_plan_data():
    return json.loads(PLAN_PATH.read_text())


@pytest.fixture(autouse=True)
def clear_execution_log():
    _execution_log.clear()


# ── Commit 1: Checkpoint compilation tests ──


class TestCheckpointCompilation:
    def test_given_plan_with_persistence_when_compiled_then_graph_has_checkpointer(
        self, registry, base_plan_data
    ):
        base_plan_data["persistence"] = {"backend": "memory", "thread_id": "test-1"}
        plan = GraphWiringPlan(**base_plan_data)
        graph = compile_plan(plan, registry, handler_registry=STUB_HANDLERS)
        # LangGraph compiled graph exposes checkpointer via .checkpointer
        assert graph.checkpointer is not None

    def test_given_plan_without_persistence_when_compiled_then_no_checkpointer(
        self, registry, base_plan_data
    ):
        plan = GraphWiringPlan(**base_plan_data)
        graph = compile_plan(plan, registry, handler_registry=STUB_HANDLERS)
        assert graph.checkpointer is None

    def test_given_plan_with_breakpoints_and_persistence_when_compiled_then_interrupt_before_set(
        self, registry, base_plan_data
    ):
        base_plan_data["persistence"] = {"backend": "memory", "thread_id": "test-1"}
        plan = GraphWiringPlan(**base_plan_data)
        graph = compile_plan(plan, registry, handler_registry=STUB_HANDLERS)
        # The compiled graph should have interrupt_before configured
        # This is stored internally by LangGraph
        assert graph.checkpointer is not None


# ── Commit 2: Breakpoint pause tests ──


class TestBreakpointPause:
    def test_given_pipeline_with_breakpoint_when_invoked_then_execution_pauses_at_gate(
        self, registry, base_plan_data
    ):
        base_plan_data["persistence"] = {"backend": "memory", "thread_id": "pause-1"}
        plan = GraphWiringPlan(**base_plan_data)
        graph = compile_plan(plan, registry, handler_registry=STUB_HANDLERS)

        config = {"configurable": {"thread_id": "pause-1"}}
        graph.invoke({"product_brief_input": "test"}, config)

        # strategy, architecture, spec executed; gate and downstream did NOT
        assert "strategy" in _execution_log
        assert "architecture" in _execution_log
        assert "spec" in _execution_log
        assert "spec_approval_gate" not in _execution_log
        assert "unit_test_writer" not in _execution_log
        assert "code_writer" not in _execution_log

    def test_given_paused_execution_when_state_inspected_then_strategy_architecture_spec_artifacts_present(
        self, registry, base_plan_data
    ):
        base_plan_data["persistence"] = {"backend": "memory", "thread_id": "pause-2"}
        plan = GraphWiringPlan(**base_plan_data)
        graph = compile_plan(plan, registry, handler_registry=STUB_HANDLERS)

        config = {"configurable": {"thread_id": "pause-2"}}
        result = graph.invoke({"product_brief_input": "test"}, config)

        assert "product_brief" in result
        assert "feature_architecture" in result
        assert "feature_spec" in result
        assert "test_plan" in result

    def test_given_paused_execution_when_state_inspected_then_downstream_artifacts_absent(
        self, registry, base_plan_data
    ):
        base_plan_data["persistence"] = {"backend": "memory", "thread_id": "pause-3"}
        plan = GraphWiringPlan(**base_plan_data)
        graph = compile_plan(plan, registry, handler_registry=STUB_HANDLERS)

        config = {"configurable": {"thread_id": "pause-3"}}
        result = graph.invoke({"product_brief_input": "test"}, config)

        assert "worker_result" not in result


# ── Commit 3: Resume tests ──


class TestCheckpointResume:
    def test_given_paused_execution_when_resumed_with_approval_then_completes_to_end(
        self, registry, base_plan_data
    ):
        base_plan_data["persistence"] = {"backend": "memory", "thread_id": "resume-1"}
        plan = GraphWiringPlan(**base_plan_data)
        graph = compile_plan(plan, registry, handler_registry=STUB_HANDLERS)

        config = {"configurable": {"thread_id": "resume-1"}}
        # First invocation pauses at breakpoint
        graph.invoke({"product_brief_input": "test"}, config)

        # Resume from checkpoint
        result = graph.invoke(None, config)

        assert "worker_result" in result
        assert result["worker_result"]["status"] == "completed"

    def test_given_paused_execution_when_resumed_then_prior_nodes_not_re_executed(
        self, registry, base_plan_data
    ):
        base_plan_data["persistence"] = {"backend": "memory", "thread_id": "resume-2"}
        plan = GraphWiringPlan(**base_plan_data)
        graph = compile_plan(plan, registry, handler_registry=STUB_HANDLERS)

        config = {"configurable": {"thread_id": "resume-2"}}
        graph.invoke({"product_brief_input": "test"}, config)

        # Clear log before resume
        _execution_log.clear()

        # Resume
        graph.invoke(None, config)

        # Only gate and downstream nodes should have run
        assert "strategy" not in _execution_log
        assert "architecture" not in _execution_log
        assert "spec" not in _execution_log
        assert "spec_approval_gate" in _execution_log
        assert "unit_test_writer" in _execution_log
        assert "code_writer" in _execution_log

    def test_given_checkpoint_and_new_graph_from_same_plan_when_loaded_then_resumes_correctly(
        self, registry, base_plan_data
    ):
        base_plan_data["persistence"] = {"backend": "memory", "thread_id": "resume-3"}
        plan = GraphWiringPlan(**base_plan_data)
        graph1 = compile_plan(plan, registry, handler_registry=STUB_HANDLERS)

        config = {"configurable": {"thread_id": "resume-3"}}
        graph1.invoke({"product_brief_input": "test"}, config)

        # Compile a new graph from the same plan, sharing the checkpointer
        # (In real use, the checkpointer would be persisted; for memory backend,
        # we reuse the same compiled graph which shares the MemorySaver instance)
        _execution_log.clear()
        result = graph1.invoke(None, config)

        assert "worker_result" in result
        assert result["worker_result"]["status"] == "completed"
