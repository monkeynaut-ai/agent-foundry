"""Tests for the AgentAction compiler node."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from agent_foundry.compiler.primitive_compiler import _compile_primitive
from agent_foundry.primitives.errors import PrimitiveCompilationError
from agent_foundry.primitives.models import (
    AgentAction,
    ContainerReusePolicy,
)
from agent_foundry.primitives.plan import PrimitivePlan


class AgentInput(BaseModel):
    query: str


class AgentOutput(BaseModel):
    answer: str


_prompts_built: list[str] = []


def _record_prompt_builder(state: AgentInput) -> str:
    prompt = f"Q: {state.query}"
    _prompts_built.append(prompt)
    return prompt


def _stub_instructions() -> str:
    return "instructions"


@pytest.fixture(autouse=True)
def reset_recorded_prompts():
    _prompts_built.clear()
    yield
    _prompts_built.clear()


@pytest.fixture(autouse=True)
def _default_run_context(tmp_path):
    """Provide a default ``AgentRunContext`` for compiler tests.

    The compiled node resolves ``current_run_context`` at invocation
    time, so every ``graph.invoke`` in this file needs an active
    context. Tests that care about the run_ctx value set their own via
    ``current_run_context.set(...)`` — that inner ``set``
    shadows this fixture's default until ``reset``.
    """
    import asyncio

    from agent_foundry.orchestration.run_context import (
        AgentRunContext,
        NoOpLifecycleWriter,
        current_run_context,
    )

    ctx = AgentRunContext(
        run_id="compiler-test-default",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )
    token = current_run_context.set(ctx)
    try:
        yield
    finally:
        current_run_context.reset(token)


class TestAgentActionCompiler:
    """The AgentAction compiler node mirrors FunctionAction behavior.

    The compiler calls ``action.executor(primitive=action, prompt=...)``.
    Tests supply their executor directly on the AgentAction — no monkey-
    patching, because the executor is an explicit field on the primitive.
    """

    def test_executor_called_with_primitive_and_prompt(self):
        captured: dict[str, Any] = {}

        def _executor(*, primitive, prompt, run_ctx):
            captured["primitive"] = primitive
            captured["prompt"] = prompt
            return AgentOutput(answer="42")

        action = AgentAction[AgentInput, AgentOutput](
            name="test-agent",
            prompt_builder=_record_prompt_builder,
            instructions_provider=_stub_instructions,
            executor=_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        plan = PrimitivePlan(root=action)
        graph = _compile_primitive(plan)

        graph.invoke({"query": "hello"})

        assert _prompts_built == ["Q: hello"]
        assert captured["prompt"] == "Q: hello"
        assert captured["primitive"] is action

    def test_missing_required_input_field_raises(self):
        def _executor(*, primitive, prompt, run_ctx):
            return AgentOutput(answer="42")

        action = AgentAction[AgentInput, AgentOutput](
            name="test-agent",
            prompt_builder=_record_prompt_builder,
            instructions_provider=_stub_instructions,
            executor=_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        plan = PrimitivePlan(root=action)
        graph = _compile_primitive(plan)

        with pytest.raises(PrimitiveCompilationError, match="Boundary validation failed"):
            graph.invoke({})  # missing `query`

    def test_executor_output_merged_into_state(self):
        def _executor(*, primitive, prompt, run_ctx):
            return AgentOutput(answer="42")

        action = AgentAction[AgentInput, AgentOutput](
            name="test-agent",
            prompt_builder=_record_prompt_builder,
            instructions_provider=_stub_instructions,
            executor=_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        plan = PrimitivePlan(root=action)
        graph = _compile_primitive(plan)

        result = graph.invoke({"query": "hello"})

        assert result["answer"] == "42"

    def test_executor_must_return_instance_of_output_type(self):
        class WrongType(BaseModel):
            other: str

        def _executor(*, primitive, prompt, run_ctx):
            return WrongType(other="oops")

        action = AgentAction[AgentInput, AgentOutput](
            name="test-agent",
            prompt_builder=_record_prompt_builder,
            instructions_provider=_stub_instructions,
            executor=_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        plan = PrimitivePlan(root=action)
        graph = _compile_primitive(plan)

        with pytest.raises(PrimitiveCompilationError, match="AgentOutput"):
            graph.invoke({"query": "hello"})

    def test_compiles_with_empty_lockdown_dirs(self):
        """Empty visible_dirs/writable_dirs are a valid configuration.

        Safe-by-default invariant: empty dirs means no access, not
        no-compilation. Implementers must not add a guard that rejects
        empty dirs.
        """

        def _executor(*, primitive, prompt, run_ctx):
            return AgentOutput(answer="42")

        action = AgentAction[AgentInput, AgentOutput](
            name="test-agent",
            prompt_builder=_record_prompt_builder,
            instructions_provider=_stub_instructions,
            executor=_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
            # visible_dirs and writable_dirs default to empty.
        )
        plan = PrimitivePlan(root=action)
        graph = _compile_primitive(plan)

        result = graph.invoke({"query": "hello"})

        assert result["answer"] == "42"


# ======================================================================
# AgentAction compiler — exception propagation
# ======================================================================


class _ExecutorFailure(RuntimeError):
    """Simulates any executor-level failure (non-success envelope, crash, etc)."""


class TestAgentActionCompiler_ExceptionPropagation:
    """Executor exceptions propagate through the compiled node."""

    def test_executor_exception_propagates(self):
        def _executor(*, primitive, prompt, run_ctx):
            raise _ExecutorFailure("agent failed")

        action = AgentAction[AgentInput, AgentOutput](
            name="test-agent",
            prompt_builder=_record_prompt_builder,
            instructions_provider=_stub_instructions,
            executor=_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        plan = PrimitivePlan(root=action)
        graph = _compile_primitive(plan)

        with pytest.raises(_ExecutorFailure, match="agent failed"):
            graph.invoke({"query": "hello"})


# ======================================================================
# AgentAction integration — nested composition
# ======================================================================


class SeqInput(BaseModel):
    query: str


class SeqMid(BaseModel):
    query: str
    answer: str


class SeqOutput(BaseModel):
    query: str
    answer: str
    annotated: str


class TestAgentActionCompiler_Composition:
    def test_agent_action_inside_sequence(self):
        from agent_foundry.primitives.models import FunctionAction, Sequence

        class AgentStepInput(BaseModel):
            query: str

        class AgentStepOutput(BaseModel):
            answer: str

        def _executor(*, primitive, prompt, run_ctx):
            return AgentStepOutput(answer="42")

        agent_step = AgentAction[AgentStepInput, AgentStepOutput](
            name="test-agent",
            prompt_builder=lambda s: f"Q: {s.query}",
            instructions_provider=_stub_instructions,
            executor=_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        annotate_step = FunctionAction[SeqMid, SeqOutput](
            function=lambda s: SeqOutput(
                query=s.query,
                answer=s.answer,
                annotated=f"[{s.answer}]",
            ),
        )
        seq = Sequence[SeqInput, SeqOutput](steps=[agent_step, annotate_step])
        plan = PrimitivePlan(root=seq)
        graph = _compile_primitive(plan)

        result = graph.invoke({"query": "hello"})

        assert result["query"] == "hello"
        assert result["answer"] == "42"
        assert result["annotated"] == "[42]"


# ======================================================================
# run_ctx threading through _compile_agent_action
# ======================================================================


class TestAgentActionCompiler_RunCtxThreading:
    """The AgentAction compiled node must call
    ``action.executor(primitive=action, prompt=<built>, run_ctx=<ctx>)``,
    where ``run_ctx`` is pulled from the ``current_run_context``
    ContextVar at invocation time (not capture/compile time).
    """

    def test_executor_receives_run_ctx_kwarg_from_context_var(self, tmp_path):
        import asyncio

        from agent_foundry.orchestration.run_context import (
            AgentRunContext,
            NoOpLifecycleWriter,
            current_run_context,
        )

        captured: dict[str, Any] = {}

        def _executor(*, primitive, prompt, run_ctx):
            captured["primitive"] = primitive
            captured["prompt"] = prompt
            captured["run_ctx"] = run_ctx
            return AgentOutput(answer="ok")

        action = AgentAction[AgentInput, AgentOutput](
            name="test-agent",
            prompt_builder=_record_prompt_builder,
            instructions_provider=_stub_instructions,
            executor=_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        plan = PrimitivePlan(root=action)
        graph = _compile_primitive(plan)

        run_ctx = AgentRunContext(
            run_id="run-g1-agent",
            artifacts_dir=tmp_path,
            container_registry=object(),
            responder_provider=object(),
            lifecycle_writer=NoOpLifecycleWriter(),
            cancel_event=asyncio.Event(),
            env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
        )

        token = current_run_context.set(run_ctx)
        try:
            result = graph.invoke({"query": "hello"})
        finally:
            current_run_context.reset(token)

        assert captured["primitive"] is action
        assert captured["prompt"] == "Q: hello"
        assert captured["run_ctx"] is run_ctx
        assert result["answer"] == "ok"

    def test_executor_receives_latest_context_var_value_at_invocation(self, tmp_path):
        """Invoking the same compiled graph twice with different
        ``current_run_context`` values must cause each invocation's
        executor to see the value current at that invocation — proving
        the compiled node re-resolves the ContextVar per invocation
        rather than snapshotting it at compile time or on first use.
        """
        import asyncio

        from agent_foundry.orchestration.run_context import (
            AgentRunContext,
            NoOpLifecycleWriter,
            current_run_context,
        )

        observed: list[AgentRunContext] = []

        def _executor(*, primitive, prompt, run_ctx):
            observed.append(run_ctx)
            return AgentOutput(answer="ok")

        action = AgentAction[AgentInput, AgentOutput](
            name="test-agent",
            prompt_builder=_record_prompt_builder,
            instructions_provider=_stub_instructions,
            executor=_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        plan = PrimitivePlan(root=action)
        graph = _compile_primitive(plan)

        run_ctx_a = AgentRunContext(
            run_id="run-g1-late-bind-a",
            artifacts_dir=tmp_path,
            container_registry=object(),
            responder_provider=object(),
            lifecycle_writer=NoOpLifecycleWriter(),
            cancel_event=asyncio.Event(),
            env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
        )
        run_ctx_b = AgentRunContext(
            run_id="run-g1-late-bind-b",
            artifacts_dir=tmp_path,
            container_registry=object(),
            responder_provider=object(),
            lifecycle_writer=NoOpLifecycleWriter(),
            cancel_event=asyncio.Event(),
            env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
        )

        token_a = current_run_context.set(run_ctx_a)
        try:
            graph.invoke({"query": "hello"})
        finally:
            current_run_context.reset(token_a)

        token_b = current_run_context.set(run_ctx_b)
        try:
            graph.invoke({"query": "hello"})
        finally:
            current_run_context.reset(token_b)

        assert len(observed) == 2
        assert observed[0] is run_ctx_a
        assert observed[1] is run_ctx_b
