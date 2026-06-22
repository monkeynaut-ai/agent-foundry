"""Tests for AsyncFunctionAction.function signature and shape.

``AsyncFunctionAction.function`` carries the contract
``async function(state: I) -> O``. It runs ON the event loop, so product
code may ``await`` run-scoped async resources (e.g. the responder).
"""

from __future__ import annotations

from pydantic import BaseModel

from agent_foundry.constructs.models import AsyncFunctionAction


class InputModel(BaseModel):
    pass


class OutputModel(BaseModel):
    pass


def test_async_function_action_accepts_one_arg_coroutine():
    async def fn(state: InputModel) -> OutputModel:
        return OutputModel()

    action = AsyncFunctionAction[InputModel, OutputModel](function=fn)
    assert action.function is fn


def test_async_function_action_child_specs_is_empty():
    async def fn(state: InputModel) -> OutputModel:
        return OutputModel()

    action = AsyncFunctionAction[InputModel, OutputModel](function=fn)
    assert action.child_specs() == []


def test_async_function_action_function_annotation_resolves():
    field = AsyncFunctionAction[InputModel, OutputModel].model_fields["function"]
    assert field is not None


def test_async_function_action_accepts_optional_name():
    async def fn(state: InputModel) -> OutputModel:
        return OutputModel()

    action = AsyncFunctionAction[InputModel, OutputModel](function=fn, name="resolve_choice")
    assert action.name == "resolve_choice"
