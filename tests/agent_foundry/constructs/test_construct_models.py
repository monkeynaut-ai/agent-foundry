"""Tests for construct models and common contract."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from agent_foundry.ai_models.inference import InferenceParameters
from agent_foundry.ai_models.model import ModelCapabilities, ModelEntry
from agent_foundry.constructs import (
    AgentAction,
    StdioMcpServer,
    StreamableHttpMcpServer,
)
from agent_foundry.constructs.ai_call import AICall, ModelInput
from agent_foundry.constructs.models import (
    Conditional,
    Construct,
    ContainerReusePolicy,
    FunctionAction,
    GateAction,
    Loop,
    Retry,
    Sequence,
    get_type_args,
)


class StubInput(BaseModel):
    value: str


class StubOutput(BaseModel):
    result: str


class _LeafStubGeneric[I: BaseModel, O: BaseModel](Construct[I, O]):
    """Concrete placeholder leaf for composition tests. Implements the
    structural contract so it can stand in as a child construct.

    Generic because ``Construct`` rejects construction unless its type args
    flow through ``__pydantic_generic_metadata__``; binding the args on the
    class line (``Construct[StubInput, StubOutput]``) leaves that empty."""

    def child_specs(self) -> list[tuple[Construct, str]]:
        return []


_LeafStub = _LeafStubGeneric[StubInput, StubOutput]


# ======================================================================
# Construct Base
# ======================================================================


class TestConstructBase:
    """Construct base model is parameterized with input/output types."""

    def test_given_type_params_when_created_then_succeeds(self):
        p = _LeafStub()
        input_type, output_type = get_type_args(p)
        assert input_type is StubInput
        assert output_type is StubOutput

    def test_unparameterized_construct_raises_at_construction(self):
        # The base is abstract, so instantiation is blocked before the
        # parameterization model_validator can run.
        with pytest.raises(TypeError):
            Construct()


# ======================================================================
# child_specs — structural child enumeration
# ======================================================================


def _ai_call_leaf() -> AICall:
    return AICall[StubInput, StubOutput](
        model_input=ModelInput[StubInput](instructions="s", prompt="p"),
        parameters=InferenceParameters(max_tokens=16),
        model=ModelEntry(
            model_id="fake",
            provider=object(),
            capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
        ),
    )


def _agent_action_leaf() -> AgentAction:
    return AgentAction[StubInput, StubOutput](
        name="agent",
        model="claude-sonnet-4-6",
        prompt_builder=lambda s: "p",
        instructions_provider=lambda s: "i",
        executor=lambda *, construct, prompt: StubOutput(result="r"),
        reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
    )


class TestChildSpecs:
    """Constructs expose their child constructs + local suffixes via child_specs."""

    def test_bare_construct_cannot_instantiate(self):
        with pytest.raises(TypeError):
            Construct[StubInput, StubOutput]()

    def test_subclass_forgetting_child_specs_cannot_instantiate(self):
        class Forgot(Construct[StubInput, StubOutput]):
            pass

        with pytest.raises(TypeError):
            Forgot()

    def test_sequence_child_specs_enumerates_steps(self):
        a, b = _LeafStub(), _LeafStub()
        seq = Sequence[StubInput, StubOutput](steps=[a, b])
        assert seq.child_specs() == [(a, "step_0"), (b, "step_1")]

    def test_conditional_child_specs_then_only(self):
        then = _LeafStub()
        cond = Conditional[StubInput, StubOutput](condition=lambda s: True, then_branch=then)
        assert cond.child_specs() == [(then, "then")]

    def test_conditional_child_specs_then_and_else(self):
        then, els = _LeafStub(), _LeafStub()
        cond = Conditional[StubInput, StubOutput](
            condition=lambda s: True, then_branch=then, else_branch=els
        )
        assert cond.child_specs() == [(then, "then"), (els, "else")]

    def test_loop_child_specs(self):
        body = _LeafStub()
        loop = Loop[StubInput, StubOutput](over=lambda s: [], item_key="i", body=body)
        assert loop.child_specs() == [(body, "body")]

    def test_retry_child_specs_body_only(self):
        body = _LeafStub()
        retry = Retry[StubInput, StubInput](max_attempts=1, until=lambda s: True, body=body)
        assert retry.child_specs() == [(body, "body")]

    def test_retry_child_specs_body_and_resolver(self):
        body, resolver = _LeafStub(), _LeafStub()
        retry = Retry[StubInput, StubInput](
            max_attempts=1,
            until=lambda s: True,
            body=body,
            on_max_attempts_resolver=resolver,
        )
        # Ordering is load-bearing: body first, resolver second.
        assert retry.child_specs() == [(body, "body"), (resolver, "resolver")]

    def test_function_action_child_specs_empty(self):
        fn = FunctionAction[StubInput, StubOutput](function=lambda s: StubOutput(result=""))
        assert fn.child_specs() == []

    def test_gate_action_child_specs_empty(self):
        gate = GateAction[GateInput, GateOutput](
            interaction="human_stdin", prompt_key="escalation_context"
        )
        assert gate.child_specs() == []

    def test_agent_action_child_specs_empty(self):
        assert _agent_action_leaf().child_specs() == []

    def test_ai_call_child_specs_empty(self):
        assert _ai_call_leaf().child_specs() == []


# -- Fixture models for Loop tests --


class ChangeSet(BaseModel):
    name: str
    steps: list[str]


class LoopInput(BaseModel):
    change_sets: list[ChangeSet]


class LoopOutput(BaseModel):
    change_sets: list[ChangeSet]


# -- Fixture models for Retry tests --


class RetryInput(BaseModel):
    findings: list[str]
    no_must_fix: bool


class RetryOutput(BaseModel):
    findings: list[str]
    no_must_fix: bool


# -- Fixture models for Conditional tests --


class CondInput(BaseModel):
    has_findings: bool


class CondOutput(BaseModel):
    handled: bool


# -- Fixture models for Gate tests --


class GateInput(BaseModel):
    must_fix_remain: bool
    escalation_context: str


class GateOutput(BaseModel):
    human_response: str


# -- Fixture models for Action tests --


class CommitInput(BaseModel):
    workspace_volume: str


class CommitOutput(BaseModel):
    commit_hash: str


def fake_commit(state: CommitInput) -> CommitOutput:
    return CommitOutput(commit_hash="abc123")


# ======================================================================
# Sequence
# ======================================================================


class TestSequence:
    """Sequence construct executes steps in order."""

    def test_given_valid_steps_when_created_then_succeeds(self):
        inner = _LeafStub()
        seq = Sequence[StubInput, StubOutput](steps=[inner])
        assert len(seq.steps) == 1
        assert isinstance(seq.steps[0], Construct)

    def test_given_multiple_steps_when_created_then_succeeds(self):
        a = _LeafStub()
        b = _LeafStub()
        c = _LeafStub()
        seq = Sequence[StubInput, StubOutput](steps=[a, b, c])
        assert len(seq.steps) == 3

    def test_given_empty_steps_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            Sequence[StubInput, StubOutput](steps=[])

    def test_given_no_steps_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            Sequence[StubInput, StubOutput]()

    def test_type_args_preserved(self):
        inner = _LeafStub()
        seq = Sequence[StubInput, StubOutput](steps=[inner])
        input_type, output_type = get_type_args(seq)
        assert input_type is StubInput
        assert output_type is StubOutput


# ======================================================================
# Loop
# ======================================================================


class TestLoop:
    """Loop construct iterates over a collection in state."""

    def test_given_valid_config_when_created_then_succeeds(self):
        body = _LeafStub()
        loop = Loop[LoopInput, LoopOutput](
            over=lambda state: state.change_sets,
            item_key="current_change_set",
            body=body,
        )
        assert loop.item_key == "current_change_set"
        assert loop.max_iterations == 100

    def test_given_custom_max_iterations_when_created_then_stored(self):
        body = _LeafStub()
        loop = Loop[LoopInput, LoopOutput](
            over=lambda state: state.change_sets,
            item_key="current_change_set",
            body=body,
            max_iterations=50,
        )
        assert loop.max_iterations == 50

    def test_given_zero_max_iterations_when_created_then_raises(self):
        body = _LeafStub()
        with pytest.raises(ValidationError):
            Loop[LoopInput, LoopOutput](
                over=lambda state: state.change_sets,
                item_key="current_change_set",
                body=body,
                max_iterations=0,
            )

    def test_given_empty_item_key_when_created_then_raises(self):
        body = _LeafStub()
        with pytest.raises(ValidationError):
            Loop[LoopInput, LoopOutput](
                over=lambda state: state.change_sets,
                item_key="",
                body=body,
            )

    def test_given_missing_over_when_created_then_raises(self):
        body = _LeafStub()
        with pytest.raises(ValidationError):
            Loop[LoopInput, LoopOutput](
                item_key="item",
                body=body,
            )

    def test_over_callable_is_invocable(self):
        body = _LeafStub()
        loop = Loop[LoopInput, LoopOutput](
            over=lambda state: state.change_sets,
            item_key="current_change_set",
            body=body,
        )
        state = LoopInput(change_sets=[ChangeSet(name="cs1", steps=["s1"])])
        result = loop.over(state)
        assert len(result) == 1
        assert result[0].name == "cs1"


# ======================================================================
# Retry
# ======================================================================


class _ResolverState(BaseModel):
    n: int = 0
    verdict: str = ""


def _resolver_seat_body():
    return FunctionAction[_ResolverState, _ResolverState](
        function=lambda s: _ResolverState(n=s.n + 1)
    )


class TestRetryResolverSeat:
    """Retry exposes a resolver seat consulted on max-attempts exhaustion."""

    def test_retry_resolver_seat_defaults_none(self):
        r = Retry[_ResolverState, _ResolverState](
            max_attempts=3, until=lambda s: s.n >= 3, body=_resolver_seat_body()
        )
        assert r.on_max_attempts_resolver is None
        assert r.resolver_max_reentries == 50

    def test_retry_accepts_resolver_construct(self):
        resolver = FunctionAction[_ResolverState, _ResolverState](function=lambda s: s)
        r = Retry[_ResolverState, _ResolverState](
            max_attempts=1,
            until=lambda s: False,
            body=_resolver_seat_body(),
            on_max_attempts_resolver=resolver,
        )
        assert r.on_max_attempts_resolver is resolver

    def test_resolver_max_reentries_ge_1(self):
        with pytest.raises(ValidationError):
            Retry[_ResolverState, _ResolverState](
                max_attempts=1,
                until=lambda s: False,
                body=_resolver_seat_body(),
                resolver_max_reentries=0,
            )

    def test_retry_backwards_compatible_without_resolver(self):
        r = Retry[_ResolverState, _ResolverState](
            max_attempts=2, until=lambda s: s.n >= 2, body=_resolver_seat_body()
        )
        assert r.on_max_attempts_resolver is None

    def test_on_exhaustion_field_removed(self):
        assert "on_exhaustion" not in Retry.model_fields
        with pytest.raises(ValidationError):
            Retry[_ResolverState, _ResolverState](
                max_attempts=1,
                until=lambda s: False,
                body=_resolver_seat_body(),
                on_exhaustion=lambda ex: _ResolverState(),
            )

    def test_disposition_types_exported_from_package(self):
        from agent_foundry.constructs import (
            AttemptOutcome,
            DispositionKind,
            ResolverDidNotConvergeError,
            ResolverDisposition,
            RetryAborted,
        )

        assert ResolverDisposition is not None
        assert DispositionKind is not None
        assert RetryAborted is not None
        assert ResolverDidNotConvergeError is not None
        assert AttemptOutcome is not None


class TestRetry:
    """Retry construct repeats body until condition met or exhausted."""

    def test_given_valid_config_when_created_then_succeeds(self):
        body = _LeafStub()
        retry = Retry[RetryInput, RetryOutput](
            max_attempts=2,
            until=lambda state: state.no_must_fix,
            body=body,
        )
        assert retry.max_attempts == 2

    def test_until_callable_is_invocable(self):
        body = _LeafStub()
        retry = Retry[RetryInput, RetryOutput](
            max_attempts=2,
            until=lambda state: state.no_must_fix,
            body=body,
        )
        state = RetryInput(findings=[], no_must_fix=True)
        assert retry.until(state) is True

    def test_given_zero_max_attempts_when_created_then_raises(self):
        body = _LeafStub()
        with pytest.raises(ValidationError):
            Retry[RetryInput, RetryOutput](
                max_attempts=0,
                until=lambda state: state.no_must_fix,
                body=body,
            )


# ======================================================================
# Conditional
# ======================================================================


class TestConditional:
    """Conditional construct branches based on state."""

    def test_given_both_branches_when_created_then_succeeds(self):
        then = _LeafStub()
        else_ = _LeafStub()
        cond = Conditional[CondInput, CondOutput](
            condition=lambda state: state.has_findings,
            then_branch=then,
            else_branch=else_,
        )
        assert isinstance(cond.then_branch, Construct)
        assert isinstance(cond.else_branch, Construct)

    def test_given_no_else_branch_when_created_then_none(self):
        then = _LeafStub()
        cond = Conditional[CondInput, CondOutput](
            condition=lambda state: state.has_findings,
            then_branch=then,
        )
        assert cond.else_branch is None

    def test_condition_callable_is_invocable(self):
        then = _LeafStub()
        cond = Conditional[CondInput, CondOutput](
            condition=lambda state: state.has_findings,
            then_branch=then,
        )
        state = CondInput(has_findings=True)
        assert cond.condition(state) is True

    def test_given_missing_then_branch_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            Conditional[CondInput, CondOutput](
                condition=lambda state: state.has_findings,
            )

    def test_given_missing_condition_when_created_then_raises(self):
        then = _LeafStub()
        with pytest.raises(ValidationError):
            Conditional[CondInput, CondOutput](
                then_branch=then,
            )


# ======================================================================
# Gate
# ======================================================================


class TestGateAction:
    """GateAction always blocks when reached — no condition field."""

    def test_given_valid_config_when_created_then_succeeds(self):
        gate = GateAction[GateInput, GateOutput](
            interaction="human_stdin",
            prompt_key="escalation_context",
        )
        assert gate.interaction == "human_stdin"
        assert gate.prompt_key == "escalation_context"

    def test_given_missing_interaction_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            GateAction[GateInput, GateOutput](
                prompt_key="escalation_context",
            )

    def test_given_missing_prompt_key_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            GateAction[GateInput, GateOutput](
                interaction="human_stdin",
            )

    def test_given_empty_interaction_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            GateAction[GateInput, GateOutput](
                interaction="",
                prompt_key="escalation_context",
            )


# ======================================================================
# Action
# ======================================================================


class TestFunctionAction:
    """FunctionAction wraps a synchronous, in-process function."""

    def test_given_valid_function_when_created_then_succeeds(self):
        action = FunctionAction[CommitInput, CommitOutput](function=fake_commit)
        assert callable(action.function)

    def test_function_is_invocable(self):
        action = FunctionAction[CommitInput, CommitOutput](function=fake_commit)
        result = action.function(CommitInput(workspace_volume="vol-1"))
        assert result.commit_hash == "abc123"

    def test_given_lambda_function_when_created_then_succeeds(self):
        action = FunctionAction[StubInput, StubOutput](
            function=lambda state: StubOutput(result="done"),
        )
        result = action.function(StubInput(value="test"))
        assert result.result == "done"

    def test_given_missing_function_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            FunctionAction[CommitInput, CommitOutput]()


# ======================================================================
# Recursive Nesting
# ======================================================================


class TestRecursiveNesting:
    """Constructs can be nested recursively via direct object references."""

    def test_sequence_containing_loop(self):
        body = _LeafStub()
        loop = Loop[LoopInput, LoopOutput](
            over=lambda state: state.change_sets,
            item_key="current",
            body=body,
        )
        seq = Sequence[StubInput, StubOutput](steps=[loop])
        assert isinstance(seq.steps[0], Loop)

    def test_retry_containing_sequence(self):
        a = _LeafStub()
        b = _LeafStub()
        inner_seq = Sequence[StubInput, StubOutput](steps=[a, b])
        retry = Retry[RetryInput, RetryOutput](
            max_attempts=2,
            until=lambda state: state.no_must_fix,
            body=inner_seq,
        )
        assert isinstance(retry.body, Sequence)

    def test_sequence_containing_conditional_containing_loop(self):
        body = _LeafStub()
        loop = Loop[LoopInput, LoopOutput](
            over=lambda state: state.change_sets,
            item_key="current",
            body=body,
        )
        cond = Conditional[CondInput, CondOutput](
            condition=lambda state: state.has_findings,
            then_branch=loop,
        )
        seq = Sequence[StubInput, StubOutput](steps=[cond])
        assert isinstance(seq.steps[0], Conditional)
        assert isinstance(seq.steps[0].then_branch, Loop)


# ======================================================================
# Public API
# ======================================================================


class TestPublicAPI:
    """All constructs are importable from the package."""

    def test_import_from_package(self):
        from agent_foundry.constructs import (
            Conditional,
            Construct,
            FunctionAction,
            GateAction,
            Loop,
            Process,
            Retry,
            Sequence,
        )

        assert Construct is not None
        assert Sequence is not None
        assert Loop is not None
        assert Retry is not None
        assert Conditional is not None
        assert FunctionAction is not None
        assert GateAction is not None
        assert Process is not None

    def test_agent_action_importable_from_package(self):
        assert AgentAction is not None

    def test_container_reuse_policy_importable_from_package(self):
        from agent_foundry.constructs import ContainerReusePolicy

        assert ContainerReusePolicy is not None

    def test_response_channels_not_exported_from_package(self):
        """Response channel types are not part of the constructs surface."""
        import agent_foundry.constructs as constructs

        assert not hasattr(constructs, "StructuredOutputChannel")
        assert not hasattr(constructs, "FileCollectionChannel")
        assert not hasattr(constructs, "ResponseChannel")
        assert not hasattr(constructs, "ResponseChannelKind")


# -- stub helpers for AgentAction mcp_servers tests --


class AgentMcpInput(BaseModel):
    task: str


class AgentMcpOutput(BaseModel):
    result: str


def _mcp_prompt_builder(state: AgentMcpInput) -> str:
    return f"task: {state.task}"


def _mcp_instructions_provider(_state: object) -> str:
    return "# Agent instructions\n\nDo the task."


def _mcp_executor(*, construct, prompt) -> AgentMcpOutput:
    return AgentMcpOutput(result="done")


# ======================================================================
# AgentAction — mcp_servers field
# ======================================================================


class TestAgentActionMcpServers:
    """AgentAction.mcp_servers declares which MCP servers the agent can access."""

    def test_agent_action_mcp_servers_defaults_to_empty_dict(self):
        action = AgentAction[AgentMcpInput, AgentMcpOutput](
            name="test-agent",
            model="claude-sonnet-4-6",
            prompt_builder=_mcp_prompt_builder,
            instructions_provider=_mcp_instructions_provider,
            executor=_mcp_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        assert action.mcp_servers == {}

    def test_agent_action_accepts_stdio_mcp_servers(self):
        action = AgentAction[AgentMcpInput, AgentMcpOutput](
            name="test-agent",
            model="claude-sonnet-4-6",
            prompt_builder=_mcp_prompt_builder,
            instructions_provider=_mcp_instructions_provider,
            executor=_mcp_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
            mcp_servers={"fs": StdioMcpServer(command="npx", args=["-y", "mcp-fs"])},
        )
        assert action.mcp_servers == {"fs": StdioMcpServer(command="npx", args=["-y", "mcp-fs"])}

    def test_agent_action_accepts_http_mcp_servers(self):
        action = AgentAction[AgentMcpInput, AgentMcpOutput](
            name="test-agent",
            model="claude-sonnet-4-6",
            prompt_builder=_mcp_prompt_builder,
            instructions_provider=_mcp_instructions_provider,
            executor=_mcp_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
            mcp_servers={
                "svc": StreamableHttpMcpServer(
                    url="http://localhost:9000/mcp",
                    headers={"Authorization": "Bearer tok"},
                )
            },
        )
        assert action.mcp_servers == {
            "svc": StreamableHttpMcpServer(
                url="http://localhost:9000/mcp",
                headers={"Authorization": "Bearer tok"},
            )
        }

    def test_agent_action_accepts_mixed_mcp_servers(self):
        stdio_server = StdioMcpServer(command="npx", args=["-y", "mcp-fs"])
        http_server = StreamableHttpMcpServer(url="http://localhost:9000/mcp")
        action = AgentAction[AgentMcpInput, AgentMcpOutput](
            name="test-agent",
            model="claude-sonnet-4-6",
            prompt_builder=_mcp_prompt_builder,
            instructions_provider=_mcp_instructions_provider,
            executor=_mcp_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
            mcp_servers={"fs": stdio_server, "svc": http_server},
        )
        assert isinstance(action.mcp_servers["fs"], StdioMcpServer)
        assert isinstance(action.mcp_servers["svc"], StreamableHttpMcpServer)
