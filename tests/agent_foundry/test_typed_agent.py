"""Tests for the TypedAgent protocol and is_typed_agent detection."""

from pydantic import BaseModel, Field

from agent_foundry.agents.protocol import is_typed_agent


class SimpleInput(BaseModel):
    value: str = Field(description="A test value")


class SimpleOutput(BaseModel):
    result: str = Field(description="A test result")


class ValidTypedAgent:
    def __call__(self, value: SimpleInput) -> SimpleOutput:
        return SimpleOutput(result=f"processed: {value.value}")


class PrimitiveInputAgent:
    def __call__(self, name: str, count: int) -> SimpleOutput:
        return SimpleOutput(result=f"{name}:{count}")


class NoReturnAnnotationAgent:
    def __call__(self, value: SimpleInput):
        return {"result": "no annotation"}


class DictReturnAgent:
    def __call__(self, value: SimpleInput) -> dict:
        return {"result": "dict return"}


class NoParamsAgent:
    def __call__(self) -> SimpleOutput:
        return SimpleOutput(result="no params")


class TestIsTypedAgent:
    def test_given_valid_typed_agent_when_checked_then_returns_true(self):
        assert is_typed_agent(ValidTypedAgent()) is True

    def test_given_primitive_input_agent_when_checked_then_returns_true(self):
        assert is_typed_agent(PrimitiveInputAgent()) is True

    def test_given_no_return_annotation_when_checked_then_returns_false(self):
        assert is_typed_agent(NoReturnAnnotationAgent()) is False

    def test_given_dict_return_when_checked_then_returns_false(self):
        assert is_typed_agent(DictReturnAgent()) is False

    def test_given_no_params_when_checked_then_returns_false(self):
        assert is_typed_agent(NoParamsAgent()) is False

    def test_given_plain_function_when_checked_then_returns_false(self):
        assert is_typed_agent(lambda x: x) is False

    def test_given_non_callable_when_checked_then_returns_false(self):
        assert is_typed_agent("not callable") is False
