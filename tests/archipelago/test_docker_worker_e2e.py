"""Docker worker end-to-end pipeline tests with stub handlers."""

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from agent_foundry.compiler.compiler import compile_plan
from agent_foundry.observability.tracer import ExecutionTracer
from agent_foundry.planner.wiring_plan import GraphWiringPlan
from agent_foundry.registry.spec import load_capability_spec

from .conftest import PRODUCT_CAPS_DIR

PLAN_PATH = Path(__file__).parent.parent.parent / "src" / "archipelago" / "pipeline_plan.json"


def _stub_strategy(state: dict[str, Any]) -> dict[str, Any]:
    return {
        **state,
        "product_brief": {
            "name": "Test",
            "problem_statement": "Test",
            "target_personas": ["eng"],
            "success_metrics": ["m1"],
            "constraints": [],
        },
    }


def _stub_architecture(state: dict[str, Any]) -> dict[str, Any]:
    return {
        **state,
        "feature_architecture": {
            "feature_name": "Test",
            "components": ["c1"],
            "data_flow": "a->b",
            "technology_choices": ["Python"],
            "risks": [],
        },
    }


def _stub_spec(state: dict[str, Any]) -> dict[str, Any]:
    return {
        **state,
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
    }


def _stub_gate(state: dict[str, Any]) -> dict[str, Any]:
    return {**state, "approved": True, "approver": "auto"}


def _stub_docker_worker(state: dict[str, Any]) -> dict[str, Any]:
    return {
        **state,
        "worker_result": {
            "result_summary": "Feature completed",
            "workspace_ref": "ws-test",
            "patches": [
                {
                    "pr_id": "pr-1",
                    "branch_name": "feat/t",
                    "files_changed": ["f.py"],
                    "diff_summary": "diff",
                },
            ],
            "evidence": [
                {
                    "commit_id": "abc",
                    "pr_id": "pr-1",
                    "test_commands_run": ["pytest"],
                    "test_output": "ok",
                    "tests_passed": 5,
                    "tests_failed": 0,
                    "all_green": True,
                },
            ],
            "status": "completed",
        },
    }


STUB_HANDLERS = {
    "strategy_generate_product_brief": _stub_strategy,
    "architecture_generate_feature_arch": _stub_architecture,
    "spec_generate_feature_spec": _stub_spec,
    "human_approval_gate": _stub_gate,
    "coding_implement_feature_from_spec": _stub_docker_worker,
}


@pytest.fixture
def plan():
    plan_data = json.loads(PLAN_PATH.read_text())
    return GraphWiringPlan(**plan_data)


@pytest.fixture
def final_state(registry, plan):
    graph = compile_plan(plan, registry, handler_registry=STUB_HANDLERS)
    return graph.invoke({"product_brief_input": "Build a test product"})


class TestEndToEnd:
    def test_given_valid_input_when_pipeline_runs_then_final_state_has_worker_result(
        self, final_state
    ):
        assert "worker_result" in final_state
        assert final_state["worker_result"]["status"] == "completed"

    def test_given_valid_input_when_pipeline_runs_then_worker_result_validates(self, final_state):
        spec = load_capability_spec(PRODUCT_CAPS_DIR / "coding_implement_feature_from_spec.yaml")
        jsonschema.validate(final_state["worker_result"], spec.outputs_schema)

    def test_given_pipeline_with_tracer_when_run_then_docker_worker_span_emitted(
        self, registry, plan
    ):
        tracer = ExecutionTracer()
        node_caps = {n.id: n.capability for n in plan.nodes}

        def _make_traced(node_id, original):
            def handler(state):
                span = tracer.start_span(node_id, node_caps[node_id])
                result = original(state)
                tracer.end_span(span, "ok")
                return result

            return handler

        traced = {cap: _make_traced(nid, STUB_HANDLERS[cap]) for nid, cap in node_caps.items()}
        graph = compile_plan(plan, registry, handler_registry=traced)
        graph.invoke({"product_brief_input": "test"})

        spans = tracer.export()
        worker_spans = [s for s in spans if s["capability"] == "coding_implement_feature_from_spec"]
        assert len(worker_spans) == 1
        assert worker_spans[0]["status"] == "ok"

    def test_given_pipeline_with_tracer_when_run_then_all_5_spans_emitted(self, registry, plan):
        tracer = ExecutionTracer()
        node_caps = {n.id: n.capability for n in plan.nodes}

        def _make_traced(node_id, original):
            def handler(state):
                span = tracer.start_span(node_id, node_caps[node_id])
                result = original(state)
                tracer.end_span(span, "ok")
                return result

            return handler

        traced = {cap: _make_traced(nid, STUB_HANDLERS[cap]) for nid, cap in node_caps.items()}
        graph = compile_plan(plan, registry, handler_registry=traced)
        graph.invoke({"product_brief_input": "test"})

        assert len(tracer.export()) == 5

    def test_given_interrupt_during_pipeline_when_breakpoint_hit_then_state_contains_payload(
        self, registry, plan
    ):
        """Use a stub handler that returns breakpoint_payload; verify state."""

        def _stub_docker_worker_interrupt(state: dict[str, Any]) -> dict[str, Any]:
            return {
                **state,
                "breakpoint_payload": {
                    "type": "clarification",
                    "question": "Which DB?",
                    "options": ["pg"],
                    "default": "pg",
                },
                "worker_result": None,
            }

        handlers = {**STUB_HANDLERS, "coding_implement_feature_from_spec": _stub_docker_worker_interrupt}
        graph = compile_plan(plan, registry, handler_registry=handlers)
        final = graph.invoke({"product_brief_input": "test"})
        assert final.get("breakpoint_payload") is not None
        assert final["breakpoint_payload"]["type"] == "clarification"
        assert final["worker_result"] is None

    def test_given_resumed_after_interrupt_when_pipeline_continues_then_completes(
        self, registry, plan
    ):
        """Simulate resuming after a breakpoint by running with a completing handler."""
        call_count = {"n": 0}

        def _stub_docker_worker_resume(state: dict[str, Any]) -> dict[str, Any]:
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First call: simulate interrupt
                return {
                    **state,
                    "breakpoint_payload": {
                        "type": "clarification",
                        "question": "Which DB?",
                        "options": ["pg"],
                        "default": "pg",
                    },
                    "worker_result": None,
                }
            # Second call: complete successfully
            return _stub_docker_worker(state)

        # Run pipeline — first invocation hits breakpoint
        handlers = {**STUB_HANDLERS, "coding_implement_feature_from_spec": _stub_docker_worker_resume}
        graph = compile_plan(plan, registry, handler_registry=handlers)
        first_result = graph.invoke({"product_brief_input": "test"})
        assert first_result.get("breakpoint_payload") is not None

        # Simulate resume by re-invoking with breakpoint cleared
        resumed_state = {**first_result, "breakpoint_payload": None}
        handlers2 = {**STUB_HANDLERS, "coding_implement_feature_from_spec": _stub_docker_worker}
        graph2 = compile_plan(plan, registry, handler_registry=handlers2)
        final = graph2.invoke(resumed_state)
        assert final["worker_result"] is not None
        assert final["worker_result"]["status"] == "completed"
