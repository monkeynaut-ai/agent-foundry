"""Primitive Pydantic models — composable, typed building blocks."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContainerReusePolicy(StrEnum):
    """Policy for whether and how an AgentAction reuses containers across invocations.

    - NEW_EACH_TIME: Each invocation creates a fresh container, destroyed after.
    - REUSE_RESUME: Subsequent invocations reuse the same container with the
      agent session resumed (same conversation context).
    - REUSE_NEW_SESSION: Subsequent invocations reuse the container but start
      a fresh agent session (no conversation history, filesystem state persists).
    """

    NEW_EACH_TIME = "new_each_time"
    REUSE_RESUME = "reuse_resume"
    REUSE_NEW_SESSION = "reuse_new_session"


class Primitive[I: BaseModel, O: BaseModel](BaseModel):
    """Base class for all plan primitives.

    Every primitive is parameterized with input (I) and output (O) state
    types.  These are Pydantic BaseModel subclasses that define the state
    keys the primitive reads from and writes back to its parent scope.
    Type information is accessible at runtime via ``get_type_args()``.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @model_validator(mode="after")
    def _require_parameterization(self) -> Primitive:
        metadata = type(self).__pydantic_generic_metadata__
        if not metadata["args"]:
            cls_name = type(self).__name__
            raise ValueError(
                f"{cls_name} must be parameterized: use {cls_name}[InputType, OutputType](...)"
            )
        return self


class Sequence[I: BaseModel, O: BaseModel](Primitive[I, O]):
    """Execute steps in order, passing state between them."""

    steps: list[Primitive] = Field(min_length=1)


class Loop[I: BaseModel, O: BaseModel](Primitive[I, O]):
    """Iterate over a collection in state, executing body per item.

    The ``over`` callable extracts the collection from the input state.
    The ``item_key`` names the state key that each item is bound to
    during iteration.
    """

    over: Callable[[I], list]
    item_key: str = Field(min_length=1)
    body: Primitive
    max_iterations: int = Field(default=100, ge=1)


class Retry[I: BaseModel, O: BaseModel](Primitive[I, O]):
    """Execute body, evaluate condition, repeat up to max_attempts times.

    The ``until`` callable checks a condition on the state — when it returns
    True, the retry stops.  If max_attempts is exhausted, Retry exits normally
    with domain state intact.  The parent reads the output and routes accordingly
    (e.g. via a Conditional to a GateAction for human escalation).
    """

    max_attempts: int = Field(ge=1)
    until: Callable[[I], bool]
    body: Primitive


class Conditional[I: BaseModel, O: BaseModel](Primitive[I, O]):
    """Branch based on a state condition.

    The ``condition`` callable evaluates the state and returns a boolean.
    If True, ``then_branch`` executes.  If False and ``else_branch`` is
    provided, it executes.  Otherwise, the primitive is a no-op.
    """

    condition: Callable[[I], bool]
    then_branch: Primitive
    else_branch: Primitive | None = None


class FunctionAction[I: BaseModel, O: BaseModel](Primitive[I, O]):
    """A synchronous, in-process function call.

    Wraps a plain function that transforms input state to output state.
    Used for deterministic operations like git commit, PR submission,
    file generation, or any non-AI transformation.
    """

    function: Callable[[I], O]


class GateAction[I: BaseModel, O: BaseModel](Primitive[I, O]):
    """Block execution until external input is received.

    Always blocks when reached — routing to the gate is the parent's
    responsibility (e.g. a Conditional checking whether escalation is needed).
    The ``prompt_key`` identifies which state field to display to the human.
    The ``interaction`` field specifies the interaction method (e.g. "human_stdin").
    """

    interaction: str = Field(min_length=1)
    prompt_key: str = Field(min_length=1)


def get_type_args(prim: Primitive) -> tuple[type[BaseModel], type[BaseModel]]:
    """Extract (input_type, output_type) from a parameterized primitive.

    Raises TypeError if the primitive was not parameterized.
    """
    metadata = type(prim).__pydantic_generic_metadata__
    args = metadata["args"]
    if not args:
        raise TypeError("Primitive must be parameterized: use Primitive[InputType, OutputType]")
    return args[0], args[1]


# Resolve forward references for recursive primitive nesting.
Sequence.model_rebuild()
Loop.model_rebuild()
Retry.model_rebuild()
Conditional.model_rebuild()
FunctionAction.model_rebuild()
GateAction.model_rebuild()
