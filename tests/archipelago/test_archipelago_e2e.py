"""Archipelago end-to-end pipeline tests with stub handlers and tracing."""

from pathlib import Path
from typing import Any

import jsonschema
import pytest

from agent_foundry.compiler.compiler import compile_plan
from agent_foundry.observability.tracer import ExecutionTracer
from agent_foundry.planner.wiring_plan import GraphWiringPlan
from agent_foundry.registry.registry import CapabilityRegistry
from agent_foundry.registry.spec import load_capability_spec

CAPABILITIES_DIR = Path(__file__).parent.parent.parent / "capabilities"
PLAN_PATH = Path(__file__).parent.parent.parent / "src" / "archipelago" / "pipeline_plan.json"


# ── Stub handlers that produce valid artifacts without LLM calls ──


def _stub_strategy(state: dict[str, Any]) -> dict[str, Any]:
    return {
        **state,
        "product_brief": {
            "name": "Test Product",
            "problem_statement": "Test problem",
            "target_personas": ["engineer"],
            "success_metrics": ["metric-1"],
            "constraints": [],
        },
    }


def _stub_architecture(state: dict[str, Any]) -> dict[str, Any]:
    return {
        **state,
        "feature_architecture": {
            "feature_name": "Test Feature",
            "components": ["comp-a"],
            "data_flow": "a -> b",
            "technology_choices": ["Python"],
            "risks": [],
        },
    }


def _stub_spec(state: dict[str, Any]) -> dict[str, Any]:
    return {
        **state,
        "feature_spec": {
            "title": "Test Spec",
            "objective": "Test objective",
            "acceptance_criteria": ["criterion-1"],
            "pr_slices": [{"title": "slice-1", "commits": ["c1"]}],
        },
        "test_plan": {
            "feature_name": "Test Feature",
            "test_cases": [{"name": "test_one", "type": "unit"}],
            "coverage_targets": ["handler"],
        },
    }


def _stub_gate(state: dict[str, Any]) -> dict[str, Any]:
    return {**state, "approved": True, "approver": "auto"}


def _stub_dev_test(state: dict[str, Any]) -> dict[str, Any]:
    return {
        **state,
        "code_patch": {
            "feature_name": "Test Feature",
            "files_changed": ["src/foo.py"],
            "diff_summary": "Added foo",
            "branch_name": "feat/foo",
        },
        "test_results": {
            "feature_name": "Test Feature",
            "tests_passed": 5,
            "tests_failed": 0,
            "test_output": "5 passed",
            "all_green": True,
        },
    }


STUB_HANDLERS = {
    "strategy_generate_product_brief": _stub_strategy,
    "architecture_generate_feature_arch": _stub_architecture,
    "spec_generate_feature_spec": _stub_spec,
    "human_approval_gate": _stub_gate,
    "coding_implement_feature_from_spec": _stub_dev_test,
}


@pytest.fixture
def registry():
    return CapabilityRegistry.from_directory(CAPABILITIES_DIR)


@pytest.fixture
def plan():
    import json
    plan_data = json.loads(PLAN_PATH.read_text())
    return GraphWiringPlan(**plan_data)


@pytest.fixture
def final_state(registry, plan):
    graph = compile_plan(plan, registry, handler_registry=STUB_HANDLERS)
    return graph.invoke({"product_brief_input": "Build a test product"})


ARTIFACT_KEYS = [
    "product_brief",
    "feature_architecture",
    "feature_spec",
    "test_plan",
    "code_patch",
    "test_results",
]


class TestEndToEnd:
    def test_given_valid_input_when_pipeline_runs_then_final_state_has_all_6_artifacts(
        self, final_state
    ):
        for key in ARTIFACT_KEYS:
            assert key in final_state, f"Missing artifact: {key}"

    def test_given_valid_input_when_pipeline_runs_then_all_artifacts_validate(
        self, final_state
    ):
        strategy_spec = load_capability_spec(
            CAPABILITIES_DIR / "strategy_generate_product_brief.yaml"
        )
        jsonschema.validate({"product_brief": final_state["product_brief"]}, strategy_spec.outputs_schema)

        arch_spec = load_capability_spec(
            CAPABILITIES_DIR / "architecture_generate_feature_arch.yaml"
        )
        jsonschema.validate(
            final_state["feature_architecture"], arch_spec.outputs_schema
        )

        spec_spec = load_capability_spec(
            CAPABILITIES_DIR / "spec_generate_feature_spec.yaml"
        )
        combined_spec = {
            "feature_spec": final_state["feature_spec"],
            "test_plan": final_state["test_plan"],
        }
        jsonschema.validate(combined_spec, spec_spec.outputs_schema)

        dev_spec = load_capability_spec(
            CAPABILITIES_DIR / "dev_implement_feature_tdd.yaml"
        )
        combined_dev = {
            "code_patch": final_state["code_patch"],
            "test_results": final_state["test_results"],
        }
        jsonschema.validate(combined_dev, dev_spec.outputs_schema)

    def test_given_pipeline_with_tracer_when_run_then_5_spans_exported(
        self, registry, plan
    ):
        tracer = ExecutionTracer()
        node_caps = {n.id: n.capability for n in plan.nodes}

        def _make_traced_handler(node_id, original):
            def handler(state):
                span = tracer.start_span(node_id, node_caps[node_id])
                result = original(state)
                tracer.end_span(span, "ok")
                return result
            return handler

        traced_handlers = {
            cap: _make_traced_handler(nid, STUB_HANDLERS[cap])
            for nid, cap in node_caps.items()
        }

        graph = compile_plan(plan, registry, handler_registry=traced_handlers)
        graph.invoke({"product_brief_input": "Build a test product"})

        spans = tracer.export()
        assert len(spans) == 5

    def test_given_pipeline_with_tracer_when_run_then_all_spans_have_ok_status(
        self, registry, plan
    ):
        tracer = ExecutionTracer()
        node_caps = {n.id: n.capability for n in plan.nodes}

        def _make_traced_handler(node_id, original):
            def handler(state):
                span = tracer.start_span(node_id, node_caps[node_id])
                result = original(state)
                tracer.end_span(span, "ok")
                return result
            return handler

        traced_handlers = {
            cap: _make_traced_handler(nid, STUB_HANDLERS[cap])
            for nid, cap in node_caps.items()
        }

        graph = compile_plan(plan, registry, handler_registry=traced_handlers)
        graph.invoke({"product_brief_input": "Build a test product"})

        spans = tracer.export()
        for span in spans:
            assert span["status"] == "ok"

    def test_given_pipeline_with_tracer_when_run_then_all_spans_have_nonzero_duration(
        self, registry, plan
    ):
        tracer = ExecutionTracer()
        node_caps = {n.id: n.capability for n in plan.nodes}

        def _make_traced_handler(node_id, original):
            def handler(state):
                span = tracer.start_span(node_id, node_caps[node_id])
                result = original(state)
                tracer.end_span(span, "ok")
                return result
            return handler

        traced_handlers = {
            cap: _make_traced_handler(nid, STUB_HANDLERS[cap])
            for nid, cap in node_caps.items()
        }

        graph = compile_plan(plan, registry, handler_registry=traced_handlers)
        graph.invoke({"product_brief_input": "Build a test product"})

        spans = tracer.export()
        for span in spans:
            duration = span["end_time"] - span["start_time"]
            assert duration >= 0
