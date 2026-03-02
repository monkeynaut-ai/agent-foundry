"""Docker worker capability spec — loading, schema validation, and registry tests."""

from pathlib import Path

import jsonschema
import pytest

from agent_foundry.registry.registry import CapabilityRegistry
from agent_foundry.registry.spec import CapabilitySpec, load_capability_spec
from archipelago.docker_worker.models import WorkerInput, WorkerConstraints, WorkerResult

PRODUCT_CAPS_DIR = Path(__file__).parent.parent.parent / "src" / "archipelago" / "capabilities"


@pytest.fixture
def registry():
    return CapabilityRegistry.with_product_specs(PRODUCT_CAPS_DIR)


class TestCodingSpec:
    def test_given_yaml_file_when_loaded_then_returns_valid_capability_spec(self):
        spec = load_capability_spec(
            PRODUCT_CAPS_DIR / "coding_implement_feature_from_spec.yaml"
        )
        assert isinstance(spec, CapabilitySpec)
        assert spec.name == "coding_implement_feature_from_spec"
        assert spec.version == "1.0.0"
        assert "docker-worker" in spec.tags

    def test_given_coding_spec_when_inputs_schema_validates_worker_input_then_passes(
        self,
    ):
        spec = load_capability_spec(
            PRODUCT_CAPS_DIR / "coding_implement_feature_from_spec.yaml"
        )
        worker_input = WorkerInput(
            repo_ref="abc123",
            feature_spec={"title": "test"},
            constraints=WorkerConstraints(),
            test_commands=["pytest"],
        )
        jsonschema.validate(worker_input.model_dump(), spec.inputs_schema)

    def test_given_coding_spec_when_outputs_schema_validates_worker_result_then_passes(
        self,
    ):
        spec = load_capability_spec(
            PRODUCT_CAPS_DIR / "coding_implement_feature_from_spec.yaml"
        )
        worker_result = WorkerResult(
            result_summary="done",
            workspace_ref="ws-1",
            patches=[],
            evidence=[],
            status="completed",
        )
        jsonschema.validate(worker_result.model_dump(), spec.outputs_schema)


class TestRegistryIntegration:
    def test_given_registry_when_searched_by_docker_worker_tag_then_returns_coding_spec(
        self, registry
    ):
        results = registry.search(tags=["docker-worker"])
        names = [s.name for s in results]
        assert "coding_implement_feature_from_spec" in names
