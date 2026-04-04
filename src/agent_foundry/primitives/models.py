"""Primitive Pydantic models — composable, typed building blocks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _is_basemodel_subclass(v: Any) -> bool:
    return isinstance(v, type) and issubclass(v, BaseModel)


class Primitive(BaseModel):
    """Base class for all plan primitives.

    Every primitive has a typed input boundary and a typed output boundary.
    Input/output are Pydantic BaseModel subclasses that define the state
    keys the primitive reads from and writes back to its parent scope.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    input: type[BaseModel]
    output: type[BaseModel]

    @model_validator(mode="after")
    def _validate_type_fields(self) -> Primitive:
        if not _is_basemodel_subclass(self.input):
            raise ValueError(f"Primitive: 'input' must be a BaseModel subclass, got {self.input}")
        if not _is_basemodel_subclass(self.output):
            raise ValueError(f"Primitive: 'output' must be a BaseModel subclass, got {self.output}")
        return self


class Sequence(Primitive):
    """Execute steps in order, passing state between them."""

    steps: list[Primitive] = Field(min_length=1)


class Loop(Primitive):
    """Iterate over a collection in state, executing body per item.

    The ``over`` callable extracts the collection from the input state.
    The ``item_key`` names the state key that each item is bound to
    during iteration.
    """

    over: Callable
    item_key: str = Field(min_length=1)
    body: Primitive
    max_iterations: int = Field(default=100, ge=1)


class Retry(Primitive):
    """Execute body, evaluate condition, repeat up to max_attempts times.

    The ``until`` callable checks a condition on the state — when it returns
    True, the retry stops.  If max_attempts is exhausted without the condition
    being met, the ``on_exhausted`` action is taken (e.g. "escalate").
    """

    max_attempts: int = Field(ge=1)
    until: Callable
    body: Primitive
    on_exhausted: str


class Conditional(Primitive):
    """Branch based on a state condition.

    The ``condition`` callable evaluates the state and returns a boolean.
    If True, ``then_branch`` executes.  If False and ``else_branch`` is
    provided, it executes.  Otherwise, the primitive is a no-op.
    """

    condition: Callable
    then_branch: Primitive
    else_branch: Primitive | None = None


class Gate(Primitive):
    """Block execution until external input is received.

    The ``condition`` callable determines whether the gate activates.
    If True, execution blocks and ``prompt_key`` identifies which state
    field to display to the human.  The ``interaction`` field specifies
    the interaction method (e.g. "human_stdin").
    """

    condition: Callable
    interaction: str = Field(min_length=1)
    prompt_key: str = Field(min_length=1)


class Action(Primitive):
    """A deterministic, non-AI step.

    Wraps a plain function that transforms input state to output state
    without invoking an LLM.  Used for operations like git commit,
    PR submission, file generation.
    """

    function: Callable


# Resolve forward references for recursive primitive nesting.
Sequence.model_rebuild()
Loop.model_rebuild()
Retry.model_rebuild()
Conditional.model_rebuild()
