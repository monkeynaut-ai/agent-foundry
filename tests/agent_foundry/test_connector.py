"""Tests for the LangGraph connector."""

import pytest
from pydantic import BaseModel, Field, ValidationError

from agent_foundry.agents.connector import make_typed_connector


class TaskModel(BaseModel):
    objective: str = Field(description="What to do")
    title: str = Field(description="Short name")


class OutputModel(BaseModel):
    result_summary: str
    status: str


class MockAgent:
    """Agent with BaseModel input and output."""

    def __call__(self, current_task: TaskModel) -> OutputModel:
        return OutputModel(
            result_summary=f"Processed: {current_task.objective}",
            status="completed",
        )


class MultiParamAgent:
    """Agent with multiple parameters including primitives."""

    def __call__(self, current_task: TaskModel, workspace_volume: str) -> OutputModel:
        return OutputModel(
            result_summary=f"{current_task.objective} in {workspace_volume}",
            status="completed",
        )


class OptionalParamAgent:
    """Agent with an optional parameter that has a default."""

    def __call__(self, current_task: TaskModel, workspace_volume: str | None = None) -> OutputModel:
        vol = workspace_volume or "default-vol"
        return OutputModel(
            result_summary=f"{current_task.objective} in {vol}",
            status="completed",
        )


class PrimitiveOnlyAgent:
    """Agent with only primitive parameters."""

    def __call__(self, name: str, count: int) -> OutputModel:
        return OutputModel(result_summary=f"{name}:{count}", status="completed")


class TestMakeTypedConnector:
    def test_given_base_model_param_when_called_then_validates_and_passes(self):
        connector = make_typed_connector(MockAgent())
        state = {"current_task": {"objective": "Build X", "title": "Test"}}
        result = connector(state)
        assert result["result_summary"] == "Processed: Build X"
        assert result["status"] == "completed"

    def test_given_dict_for_model_param_when_called_then_coerces_to_model(self):
        connector = make_typed_connector(MockAgent())
        # State has a raw dict, not a TaskModel instance
        state = {"current_task": {"objective": "Build X", "title": "Test"}}
        result = connector(state)
        assert result["status"] == "completed"

    def test_given_model_instance_for_model_param_when_called_then_accepts(self):
        connector = make_typed_connector(MockAgent())
        state = {"current_task": TaskModel(objective="Build X", title="Test")}
        result = connector(state)
        assert result["result_summary"] == "Processed: Build X"

    def test_given_multiple_params_when_called_then_extracts_all(self):
        connector = make_typed_connector(MultiParamAgent())
        state = {
            "current_task": {"objective": "Build X", "title": "Test"},
            "workspace_volume": "vol-123",
        }
        result = connector(state)
        assert result["result_summary"] == "Build X in vol-123"

    def test_given_primitive_params_when_called_then_passes_directly(self):
        connector = make_typed_connector(PrimitiveOnlyAgent())
        state = {"name": "test", "count": 42}
        result = connector(state)
        assert result["result_summary"] == "test:42"

    def test_given_extra_state_keys_when_called_then_ignores_them(self):
        connector = make_typed_connector(MockAgent())
        state = {
            "current_task": {"objective": "Build X", "title": "Test"},
            "unrelated_key": "should be ignored",
        }
        result = connector(state)
        assert "unrelated_key" not in result
        assert result["status"] == "completed"

    def test_given_optional_param_missing_from_state_when_called_then_uses_default(self):
        connector = make_typed_connector(OptionalParamAgent())
        state = {"current_task": {"objective": "Build X", "title": "Test"}}
        result = connector(state)
        assert result["result_summary"] == "Build X in default-vol"

    def test_given_optional_param_present_in_state_when_called_then_uses_state_value(self):
        connector = make_typed_connector(OptionalParamAgent())
        state = {
            "current_task": {"objective": "Build X", "title": "Test"},
            "workspace_volume": "vol-123",
        }
        result = connector(state)
        assert result["result_summary"] == "Build X in vol-123"

    def test_given_missing_required_key_when_called_then_raises_key_error(self):
        connector = make_typed_connector(MockAgent())
        state = {"wrong_key": "value"}
        with pytest.raises(KeyError, match="current_task"):
            connector(state)

    def test_given_invalid_model_data_when_called_then_raises_validation_error(self):
        connector = make_typed_connector(MockAgent())
        # Missing required 'title' field
        state = {"current_task": {"objective": "Build X"}}
        with pytest.raises(ValidationError):
            connector(state)

    def test_given_output_model_when_dumped_then_returns_flat_dict(self):
        connector = make_typed_connector(MockAgent())
        state = {"current_task": {"objective": "Build X", "title": "Test"}}
        result = connector(state)
        # Result should be a plain dict, not a BaseModel
        assert isinstance(result, dict)
        assert set(result.keys()) == {"result_summary", "status"}


class TestMakeTypedConnectorErrors:
    def test_given_no_typed_params_when_wrapping_then_raises_type_error(self):
        class BadAgent:
            def __call__(self) -> OutputModel:
                return OutputModel(result_summary="", status="completed")

        with pytest.raises(TypeError, match="no typed parameters"):
            make_typed_connector(BadAgent())

    def test_given_no_return_annotation_when_wrapping_then_raises_type_error(self):
        class BadAgent:
            def __call__(self, x: str):
                return {"result": x}

        with pytest.raises(TypeError, match="must return a BaseModel"):
            make_typed_connector(BadAgent())

    def test_given_dict_return_when_wrapping_then_raises_type_error(self):
        class BadAgent:
            def __call__(self, x: str) -> dict:
                return {"result": x}

        with pytest.raises(TypeError, match="must return a BaseModel"):
            make_typed_connector(BadAgent())
