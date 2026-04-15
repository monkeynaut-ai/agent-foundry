"""Tests for the AgentAction compiler node."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from agent_foundry.compiler.primitive_compiler import compile_primitive
from agent_foundry.primitives.errors import PrimitiveCompilationError
from agent_foundry.primitives.models import (
    AgentAction,
    ContainerReusePolicy,
    StructuredOutputChannel,
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


class TestAgentActionCompiler:
    """The AgentAction compiler node mirrors FunctionAction behavior.

    The compiler calls ``action.executor(primitive=action, prompt=...)``.
    Tests supply their executor directly on the AgentAction — no monkey-
    patching, because the executor is an explicit field on the primitive.
    """

    def test_executor_called_with_primitive_and_prompt(self):
        captured: dict[str, Any] = {}

        def _executor(*, primitive, prompt):
            captured["primitive"] = primitive
            captured["prompt"] = prompt
            return AgentOutput(answer="42")

        action = AgentAction[AgentInput, AgentOutput](
            prompt_builder=_record_prompt_builder,
            instructions_provider=_stub_instructions,
            response_channel=StructuredOutputChannel(),
            executor=_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        plan = PrimitivePlan(root=action)
        graph = compile_primitive(plan)

        graph.invoke({"query": "hello"})

        assert _prompts_built == ["Q: hello"]
        assert captured["prompt"] == "Q: hello"
        assert captured["primitive"] is action

    def test_missing_required_input_field_raises(self):
        def _executor(*, primitive, prompt):
            return AgentOutput(answer="42")

        action = AgentAction[AgentInput, AgentOutput](
            prompt_builder=_record_prompt_builder,
            instructions_provider=_stub_instructions,
            response_channel=StructuredOutputChannel(),
            executor=_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        plan = PrimitivePlan(root=action)
        graph = compile_primitive(plan)

        with pytest.raises(PrimitiveCompilationError, match="Boundary validation failed"):
            graph.invoke({})  # missing `query`

    def test_executor_output_merged_into_state(self):
        def _executor(*, primitive, prompt):
            return AgentOutput(answer="42")

        action = AgentAction[AgentInput, AgentOutput](
            prompt_builder=_record_prompt_builder,
            instructions_provider=_stub_instructions,
            response_channel=StructuredOutputChannel(),
            executor=_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        plan = PrimitivePlan(root=action)
        graph = compile_primitive(plan)

        result = graph.invoke({"query": "hello"})

        assert result["answer"] == "42"

    def test_executor_must_return_instance_of_output_type(self):
        class WrongType(BaseModel):
            other: str

        def _executor(*, primitive, prompt):
            return WrongType(other="oops")

        action = AgentAction[AgentInput, AgentOutput](
            prompt_builder=_record_prompt_builder,
            instructions_provider=_stub_instructions,
            response_channel=StructuredOutputChannel(),
            executor=_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        plan = PrimitivePlan(root=action)
        graph = compile_primitive(plan)

        with pytest.raises(PrimitiveCompilationError, match="AgentOutput"):
            graph.invoke({"query": "hello"})

    def test_compiler_is_agnostic_to_response_channel(self):
        """The compiler must not branch on response_channel — that's executor-internal.

        Confirm by compiling an AgentAction that uses FileCollectionChannel
        and verifying it behaves identically to the StructuredOutputChannel
        cases above: executor is called, result is merged into state.
        """
        from agent_foundry.primitives.models import FileCollectionChannel

        def _executor(*, primitive, prompt):
            return AgentOutput(answer="42")

        def _builder(files: dict[str, str]) -> AgentOutput:
            return AgentOutput(answer=files.get("/workspace/out.md", ""))

        action = AgentAction[AgentInput, AgentOutput](
            prompt_builder=_record_prompt_builder,
            instructions_provider=_stub_instructions,
            response_channel=FileCollectionChannel(
                files=["/workspace/out.md"],
                builder=_builder,
            ),
            executor=_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        plan = PrimitivePlan(root=action)
        graph = compile_primitive(plan)

        result = graph.invoke({"query": "hello"})

        assert result["answer"] == "42"

    def test_compiles_with_empty_lockdown_dirs(self):
        """Empty visible_dirs/writable_dirs are a valid configuration.

        Safe-by-default invariant: empty dirs means no access, not
        no-compilation. Plan 2 implementers must not add a guard that
        rejects empty dirs.
        """

        def _executor(*, primitive, prompt):
            return AgentOutput(answer="42")

        action = AgentAction[AgentInput, AgentOutput](
            prompt_builder=_record_prompt_builder,
            instructions_provider=_stub_instructions,
            response_channel=StructuredOutputChannel(),
            executor=_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
            # visible_dirs and writable_dirs default to empty.
        )
        plan = PrimitivePlan(root=action)
        graph = compile_primitive(plan)

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
        def _executor(*, primitive, prompt):
            raise _ExecutorFailure("agent failed")

        action = AgentAction[AgentInput, AgentOutput](
            prompt_builder=_record_prompt_builder,
            instructions_provider=_stub_instructions,
            response_channel=StructuredOutputChannel(),
            executor=_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        plan = PrimitivePlan(root=action)
        graph = compile_primitive(plan)

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

        def _executor(*, primitive, prompt):
            return AgentStepOutput(answer="42")

        agent_step = AgentAction[AgentStepInput, AgentStepOutput](
            prompt_builder=lambda s: f"Q: {s.query}",
            instructions_provider=_stub_instructions,
            response_channel=StructuredOutputChannel(),
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
        graph = compile_primitive(plan)

        result = graph.invoke({"query": "hello"})

        assert result["query"] == "hello"
        assert result["answer"] == "42"
        assert result["annotated"] == "[42]"
