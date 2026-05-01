"""Primitive Pydantic models — composable, typed building blocks."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContainerReusePolicy(StrEnum):
    """Policy for whether and how an AgentAction reuses containers across invocations.

    - REUSE_RESUME: Subsequent invocations reuse the same container with the
      agent session resumed (same conversation context).
    - REUSE_NEW_SESSION: Subsequent invocations reuse the container but start
      a fresh agent session (no conversation history, filesystem state persists).
    """

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
    """The callable invoked by the compiled node.

    Signature is ``(state) -> O``. For access to run-scoped state
    (emit domain events, read artifacts_dir, check cancellation),
    import accessors from ``agent_foundry.runtime``:

        from agent_foundry import runtime

        def my_function(state: StateA) -> StateB:
            runtime.emit("step_completed", step="hello")
            return StateB(...)

    No need to accept ``run_ctx`` as a parameter.
    """


class GateAction[I: BaseModel, O: BaseModel](Primitive[I, O]):
    """Block execution until external input is received.

    Always blocks when reached — routing to the gate is the parent's
    responsibility (e.g. a Conditional checking whether escalation is needed).
    The ``prompt_key`` identifies which state field to display to the human.
    The ``interaction`` field specifies the interaction method (e.g. "human_stdin").
    """

    interaction: str = Field(min_length=1)
    prompt_key: str = Field(min_length=1)


class AgentAction[I: BaseModel, O: BaseModel](Primitive[I, O]):
    """Run an LLM agent in a container to transform input state to output state.

    Two-sided interface:
      - Product side declares agent configuration via collaborator callables
        (``prompt_builder``, ``instructions_provider``).
      - Platform side handles container lifecycle, instruction injection,
        structured output, and response validation.

    This primitive is a leaf (no children). The compiler registers a node
    that calls the prompt builder, then delegates to the agent runner.
    The runner always returns an instance of ``O`` via structured output.

    The ``name`` field is a diagnostic label used for artifact directory
    names, lifecycle event payloads, and log prefixes. It is NOT used
    for composition or lookup — primitives reference each other by
    Python object reference, and the AgentContainerRegistry is keyed
    by ``id(primitive)``. Two AgentActions with the same name are
    technically legal but will collide in artifact paths and confuse
    logs; products are expected to pick unique, meaningful names
    (e.g. "reviewer", "planner", "implementer").
    """

    # Diagnostic label — required, no default. Used for artifact dir
    # naming and log/event labelling; never for composition or lookup.
    name: str = Field(min_length=1)

    # Product-side collaborators. Both receive the input-state slice so
    # prompts and instructions can be resolved against per-run data (e.g.
    # Jinja-templated instructions via archetype.templating).
    prompt_builder: Callable[[I], str]
    instructions_provider: Callable[[I], str]

    # Executor — required, no default. The callable that actually runs the
    # agent and returns an instance of ``O``. The default is
    # ``run_agent_in_container`` (container + Claude Code CLI); future
    # SDK/API executors will be additional callables products can choose.
    # Different agents in the same system can use different executors.
    #
    # Contract: ``executor(*, primitive: AgentAction, prompt: str) -> O``.
    # The compiler calls the executor with keyword arguments; the primitive
    # passed in is the same ``AgentAction`` instance (the executor can read
    # ``instructions_provider``, container config, etc. from it).
    executor: Callable[..., O | Awaitable[O]]

    # Container configuration (platform defaults, product may override)
    timeout_seconds: int = Field(default=3600, ge=1)
    skip_permissions: bool = False

    # Filesystem access — GID-based group permissions.
    # Lists the supplementary GIDs the agent process should hold when
    # Claude Code is invoked via docker exec --group-add. An empty list
    # means no supplementary groups (read-only against group-owned dirs).
    # workspace_bootstrap is responsible for chown/chmod of workspace
    # directories to their respective GIDs before agents run.
    gids: list[int] = Field(default_factory=list)

    # Container reuse — required, no default. Product must explicitly choose
    # how containers are reused across invocations.
    reuse_policy: ContainerReusePolicy


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
AgentAction.model_rebuild()
