"""Construct Pydantic models — composable, typed building blocks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_foundry.agents.lifecycle import ContainerConfig
from agent_foundry.constructs.mcp import McpServer


class ContainerReusePolicy(StrEnum):
    """Policy for whether and how an AgentAction reuses containers across invocations.

    - REUSE_RESUME: Subsequent invocations reuse the same container with the
      agent session resumed (same conversation context).
    - REUSE_NEW_SESSION: Subsequent invocations reuse the container but start
      a fresh agent session (no conversation history, filesystem state persists).
    """

    REUSE_RESUME = "reuse_resume"
    REUSE_NEW_SESSION = "reuse_new_session"


class Construct[I: BaseModel, O: BaseModel](BaseModel, ABC):
    """Base class for all process constructs.

    Every construct is parameterized with input (I) and output (O) state
    types.  These are Pydantic BaseModel subclasses that define the state
    keys the construct reads from and writes back to its parent scope.
    Type information is accessible at runtime via ``get_type_args()``.
    """

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _require_parameterization(self) -> Construct:
        metadata = type(self).__pydantic_generic_metadata__
        if not metadata["args"]:
            cls_name = type(self).__name__
            raise ValueError(
                f"{cls_name} must be parameterized: use {cls_name}[InputType, OutputType](...)"
            )
        return self

    @abstractmethod
    def child_specs(self) -> list[tuple[Construct, str]]:
        """Return child constructs paired with their local compile-prefix suffix.

        Leaves return ``[]``. The suffix is a local label (``"step_0"``,
        ``"then"``, ``"body"``, ``"resolver"``); callers compose the full
        prefix.
        """


class Sequence[I: BaseModel, O: BaseModel](Construct[I, O]):
    """Execute steps in order, passing state between them."""

    steps: list[Construct] = Field(min_length=1)

    def child_specs(self) -> list[tuple[Construct, str]]:
        return [(step, f"step_{i}") for i, step in enumerate(self.steps)]


class Loop[I: BaseModel, O: BaseModel](Construct[I, O]):
    """Iterate over a collection in state, executing body per item.

    The ``over`` callable extracts the collection from the input state.
    The ``item_key`` names the state key that each item is bound to
    during iteration.
    """

    over: Callable[[I], list]
    item_key: str = Field(min_length=1)
    body: Construct
    max_iterations: int = Field(default=100, ge=1)

    def child_specs(self) -> list[tuple[Construct, str]]:
        return [(self.body, "body")]


class RetryExceptionPolicy(StrEnum):
    """Controls what Retry does when its body raises an exception.

    - PROPAGATE: re-raise immediately (default, preserves existing behaviour).
    - CATCH_AND_CONTINUE: catch the exception, consume the attempt, restore
      pre-attempt state, and continue to the next attempt.
    """

    PROPAGATE = "propagate"
    CATCH_AND_CONTINUE = "catch_and_continue"


class Retry[I: BaseModel, O: BaseModel](Construct[I, O]):
    """Execute body, evaluate condition, repeat up to max_attempts times.

    The ``until`` callable checks a condition on the state — when it returns
    True, the retry stops.  Exhausting max_attempts is fail-closed: the
    ``on_max_attempts_resolver`` seat is consulted to decide ACCEPT/ABORT/RETRY,
    and when no resolver is set Retry ABORTs (raises RetryAborted).
    """

    max_attempts: int = Field(ge=1)
    until: Callable[[I], bool]
    body: Construct
    exception_policy: RetryExceptionPolicy = RetryExceptionPolicy.PROPAGATE
    """Exception handling policy for body failures. Defaults to PROPAGATE (existing behaviour)."""
    on_max_attempts_resolver: Construct | None = None
    """Construct consulted when the automated loop exhausts max_attempts without until() passing.

    The resolver runs as a normal outer-graph node and merges its output into graph state
    like any other node. Its output model must declare a ``disposition: ResolverDisposition``
    field; the compiler reads that field's ``kind`` (ACCEPT/ABORT/RETRY) to route and uses the
    resolver node's own output state as the continue/accept state. The disposition is a pure
    routing signal — it carries no state. A GateAction resolver satisfies this by having its
    parser set ``kind`` and write findings into existing state fields. When None, exhaustion is
    fail-closed (ABORT)."""

    resolver_max_reentries: int = Field(default=50, ge=1)
    """Safety backstop: max consecutive RETRY re-entries before raising
    ResolverDidNotConvergeError. A safety invariant, not a budget the resolver reasons about."""

    BODY_SUFFIX: ClassVar[str] = "body"
    RESOLVER_SUFFIX: ClassVar[str] = "resolver"

    def child_specs(self) -> list[tuple[Construct, str]]:
        specs: list[tuple[Construct, str]] = [(self.body, self.BODY_SUFFIX)]
        if self.on_max_attempts_resolver is not None:
            specs.append((self.on_max_attempts_resolver, self.RESOLVER_SUFFIX))
        return specs


class Conditional[I: BaseModel, O: BaseModel](Construct[I, O]):
    """Branch based on a state condition.

    The ``condition`` callable evaluates the state and returns a boolean.
    If True, ``then_branch`` executes.  If False and ``else_branch`` is
    provided, it executes.  Otherwise, the construct is a no-op.
    """

    condition: Callable[[I], bool]
    then_branch: Construct
    else_branch: Construct | None = None

    def child_specs(self) -> list[tuple[Construct, str]]:
        specs: list[tuple[Construct, str]] = [(self.then_branch, "then")]
        if self.else_branch is not None:
            specs.append((self.else_branch, "else"))
        return specs


class FunctionAction[I: BaseModel, O: BaseModel](Construct[I, O]):
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
    name: str | None = Field(default=None, min_length=1)
    """Diagnostic label for lifecycle events and logs. Not used for composition
    or lookup. Optional — when None the compiler falls back to the positional
    node_id."""

    def child_specs(self) -> list[tuple[Construct, str]]:
        return []


class AsyncFunctionAction[I: BaseModel, O: BaseModel](Construct[I, O]):
    """An asynchronous in-process function call that runs ON the event loop.

    Wraps a coroutine function transforming input state to output state.
    The callable is awaited directly on the executing loop, so it may
    ``await`` run-scoped async resources — most notably the operator
    responder via ``agent_foundry.runtime.responder()``.

    Because the callable runs on the loop rather than a worker thread, a
    blocking or CPU-bound call inside it stalls the entire loop. Keep the
    body non-blocking (only ``await`` real coroutines); push synchronous,
    blocking, or CPU-bound work into a ``FunctionAction`` instead.
    """

    function: Callable[[I], Awaitable[O]]
    """The coroutine invoked by the compiled node.

    Signature is ``async (state) -> O``. For run-scoped state (emit domain
    events, read artifacts_dir, check cancellation, reach the responder),
    import accessors from ``agent_foundry.runtime``:

        from agent_foundry import runtime

        async def my_function(state: StateA) -> StateB:
            resp = runtime.responder()
            answer = await resp.respond(request, context)
            return StateB(...)

    No need to accept ``run_ctx`` as a parameter.
    """
    name: str | None = Field(default=None, min_length=1)
    """Diagnostic label for lifecycle events and logs. Not used for composition
    or lookup. Optional — when None the compiler falls back to the positional
    node_id."""

    def child_specs(self) -> list[tuple[Construct, str]]:
        return []


class GateAction[I: BaseModel, O: BaseModel](Construct[I, O]):
    """Block execution until external input is received.

    Always blocks when reached — routing to the gate is the parent's
    responsibility (e.g. a Conditional checking whether escalation is needed).
    The ``prompt_key`` identifies which state field to display to the human.
    The ``interaction`` field specifies the interaction method (e.g. "human_stdin").
    """

    interaction: str = Field(min_length=1)
    prompt_key: str = Field(min_length=1)

    def child_specs(self) -> list[tuple[Construct, str]]:
        return []


class AgentAction[I: BaseModel, O: BaseModel](Construct[I, O]):
    """Run an LLM agent in a container to transform input state to output state.

    Two-sided interface:
      - Product side declares agent configuration via collaborator callables
        (``prompt_builder``, ``instructions_provider``).
      - Platform side handles container lifecycle, instruction injection,
        structured output, and response validation.

    This construct is a leaf (no children). The compiler registers a node
    that calls the prompt builder, then delegates to the agent runner.
    The runner always returns an instance of ``O`` via structured output.

    The ``name`` field is a diagnostic label used for artifact directory
    names, lifecycle event payloads, and log prefixes. It is NOT used
    for composition or lookup — constructs reference each other by
    Python object reference, and the AgentContainerRegistry is keyed
    by ``id(construct)``. Two AgentActions with the same name are
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
    # Contract: ``executor(*, construct: AgentAction, prompt: str) -> O``.
    # The compiler calls the executor with keyword arguments; the construct
    # passed in is the same ``AgentAction`` instance (the executor can read
    # ``instructions_provider``, container config, etc. from it).
    executor: Callable[..., O | Awaitable[O]]

    # Container configuration (platform defaults, product may override)
    timeout_seconds: int = Field(default=3600, ge=1)
    skip_permissions: bool = False
    container_config: ContainerConfig | None = None

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

    # Model — required, no default. Product must declare which Claude model
    # this agent runs on. Use ClaudeModel constants or a raw model ID string.
    model: str = Field(min_length=1)

    # Effort — optional. When set, passed as ``--effort`` to the claude CLI.
    # When None, the flag is omitted and the CLI uses its own default.
    # Use ClaudeEffort constants or a raw effort string. Empty string is
    # rejected — use None to omit the flag.
    effort: str | None = Field(default=None, min_length=1)

    # Working directory — optional. When set, passed as ``workdir`` to the
    # container exec_run call so claude starts in that directory. Claude Code
    # auto-loads CLAUDE.md files upward from cwd, so setting this to the
    # codebase root (e.g. /workspace/codebase) makes the project's CLAUDE.md
    # available to every agent without an explicit Read. When None, the
    # container image's WORKDIR is used (/workspace by default).
    cwd: str | None = None

    # MCP servers — optional. Maps server name to MCP server configuration.
    # Empty dict (the default) means no MCP tool access (safe by default).
    # The dict key is the server name Claude Code uses in tool calls:
    # ``mcp__<server_name>__<tool_name>``.
    mcp_servers: dict[str, McpServer] = Field(default_factory=dict)

    def child_specs(self) -> list[tuple[Construct, str]]:
        return []


def get_type_args(prim: Construct) -> tuple[type[BaseModel], type[BaseModel]]:
    """Extract (input_type, output_type) from a parameterized construct.

    Raises TypeError if the construct was not parameterized.
    """
    metadata = type(prim).__pydantic_generic_metadata__
    args = metadata["args"]
    if not args:
        raise TypeError("Construct must be parameterized: use Construct[InputType, OutputType]")
    return args[0], args[1]


# Resolve forward references for recursive construct nesting.
Sequence.model_rebuild()
Loop.model_rebuild()
Retry.model_rebuild()
Conditional.model_rebuild()
FunctionAction.model_rebuild()
AsyncFunctionAction.model_rebuild()
GateAction.model_rebuild()
AgentAction.model_rebuild()
