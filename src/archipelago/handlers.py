"""LLM-backed handlers for each Archipelago pipeline stage."""

from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

from archipelago.models import (
    CodePatch,
    FeatureArchitecture,
    FeatureSpec,
    ProductBrief,
    TestPlan,
    TestResults,
)
from archipelago.prompts import (
    ARCHITECTURE_PROMPT,
    DEV_TEST_PROMPT,
    SPEC_PROMPT,
    STRATEGY_PROMPT,
)


def _get_llm() -> ChatAnthropic:
    return ChatAnthropic(model="claude-sonnet-4-20250514")


def strategy_handler(state: dict[str, Any]) -> dict[str, Any]:
    """Generate a ProductBrief from a high-level product idea."""
    product_brief_input = state.get("product_brief_input", "")
    if not product_brief_input:
        raise ValueError("product_brief_input is required")

    llm = _get_llm().with_structured_output(ProductBrief)
    prompt = STRATEGY_PROMPT.format(product_brief_input=product_brief_input)
    result = llm.invoke([HumanMessage(content=prompt)])
    return {**state, "product_brief": result.model_dump()}


def architecture_handler(state: dict[str, Any]) -> dict[str, Any]:
    """Generate a FeatureArchitecture from a ProductBrief."""
    brief = state["product_brief"]

    llm = _get_llm().with_structured_output(FeatureArchitecture)
    prompt = ARCHITECTURE_PROMPT.format(**brief)
    result = llm.invoke([HumanMessage(content=prompt)])
    return {**state, "feature_architecture": result.model_dump()}


def spec_handler(state: dict[str, Any]) -> dict[str, Any]:
    """Generate a FeatureSpec and TestPlan from a FeatureArchitecture."""
    arch = state["feature_architecture"]

    llm = _get_llm()
    prompt = SPEC_PROMPT.format(**arch)
    response = llm.invoke([HumanMessage(content=prompt)])

    # Parse the combined response into separate models
    import json

    content = response.content
    parsed = json.loads(content) if isinstance(content, str) else content
    feature_spec = FeatureSpec(**parsed["feature_spec"])
    test_plan = TestPlan(**parsed["test_plan"])

    return {
        **state,
        "feature_spec": feature_spec.model_dump(),
        "test_plan": test_plan.model_dump(),
    }


def dev_test_handler(state: dict[str, Any]) -> dict[str, Any]:
    """Generate CodePatch and TestResults from a FeatureSpec and TestPlan."""
    feature_spec = state["feature_spec"]
    test_plan = state["test_plan"]

    llm = _get_llm()
    prompt = DEV_TEST_PROMPT.format(
        feature_spec_title=feature_spec["title"],
        feature_spec_objective=feature_spec["objective"],
        feature_spec_acceptance_criteria=feature_spec["acceptance_criteria"],
        test_plan_feature_name=test_plan["feature_name"],
        test_plan_test_cases=test_plan["test_cases"],
        test_plan_coverage_targets=test_plan["coverage_targets"],
    )
    response = llm.invoke([HumanMessage(content=prompt)])

    import json

    content = response.content
    parsed = json.loads(content) if isinstance(content, str) else content
    code_patch = CodePatch(**parsed["code_patch"])
    test_results = TestResults(**parsed["test_results"])

    return {
        **state,
        "code_patch": code_patch.model_dump(),
        "test_results": test_results.model_dump(),
    }


def spec_approval_gate_handler(state: dict[str, Any]) -> dict[str, Any]:
    """Auto-approve gate for automated runs."""
    return {**state, "approved": True, "approver": "auto"}


ARCHIPELAGO_HANDLERS: dict[str, Any] = {
    "strategy_generate_product_brief": strategy_handler,
    "architecture_generate_feature_arch": architecture_handler,
    "spec_generate_feature_spec": spec_handler,
    "human_approval_gate": spec_approval_gate_handler,
    "dev_implement_feature_tdd": dev_test_handler,
}
