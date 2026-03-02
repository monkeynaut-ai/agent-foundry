"""Deterministic spec handler for the Archipelago pipeline."""

from archipelago.models import FeatureSpec, TestPlan


class SpecHandler:
    def __init__(self, spec):
        self.spec = spec

    def __call__(self, state: dict) -> dict:
        arch = state.get("feature_architecture")
        if not arch:
            raise ValueError("feature_architecture is required")

        print(f"[spec] Input: feature_architecture.feature_name={arch['feature_name']}")

        feature_spec = FeatureSpec(
            title=f"{arch['feature_name']} MVP",
            objective=f"Implement core functionality for {arch['feature_name']}",
            acceptance_criteria=[
                "All CRUD operations functional",
                "API response time under 200ms",
                "Input validation on all endpoints",
                "Error handling with meaningful messages",
            ],
            pr_slices=[
                {"title": "Data models and migrations", "commits": ["Add schema", "Add migrations"]},
                {"title": "Core API endpoints", "commits": ["Add CRUD handlers", "Add routing"]},
                {"title": "Integration tests", "commits": ["Add API tests", "Add edge case tests"]},
            ],
        )

        test_plan = TestPlan(
            feature_name=arch["feature_name"],
            test_cases=[
                {"name": "test_create_resource", "type": "unit"},
                {"name": "test_read_resource", "type": "unit"},
                {"name": "test_update_resource", "type": "unit"},
                {"name": "test_delete_resource", "type": "unit"},
                {"name": "test_api_integration", "type": "integration"},
            ],
            coverage_targets=["core_service", "api_handlers", "data_layer"],
        )

        print(f"[spec] Generated feature spec: {feature_spec.title}")
        print(f"[spec] Generated test plan: {len(test_plan.test_cases)} test cases")
        return {
            **state,
            "feature_spec": feature_spec.model_dump(),
            "test_plan": test_plan.model_dump(),
        }
