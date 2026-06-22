"""Tests for Process container and graph introspection."""

from __future__ import annotations

from pydantic import BaseModel

from agent_foundry.constructs.models import (
    Conditional,
    Construct,
    Loop,
    Retry,
    Sequence,
)
from agent_foundry.constructs.process import Process


class In(BaseModel):
    value: str


class Out(BaseModel):
    result: str


class _LeafStub[I: BaseModel, O: BaseModel](Construct[I, O]):
    """Concrete leaf placeholder — implements the structural contract so the
    abstract ``Construct`` base permits instantiation."""

    def child_specs(self) -> list[tuple[Construct, str]]:
        return []


class TestProcess:
    """Process holds a root construct and provides graph introspection."""

    def test_given_root_construct_when_created_then_accessible(self):
        root = _LeafStub[In, Out]()
        process = Process(root=root)
        assert process.root is root

    def test_all_constructs_returns_single_root(self):
        root = _LeafStub[In, Out]()
        process = Process(root=root)
        assert len(process.all_constructs()) == 1
        assert process.all_constructs()[0] is root

    def test_all_constructs_finds_sequence_children(self):
        a = _LeafStub[In, Out]()
        b = _LeafStub[In, Out]()
        seq = Sequence[In, Out](steps=[a, b])
        process = Process(root=seq)
        assert len(process.all_constructs()) == 3

    def test_all_constructs_finds_deeply_nested(self):
        deep = _LeafStub[In, Out]()
        inner_seq = Sequence[In, Out](steps=[deep])
        loop = Loop[In, Out](
            over=lambda s: [],
            item_key="item",
            body=inner_seq,
        )
        root = Sequence[In, Out](steps=[loop])
        process = Process(root=root)
        all_prims = process.all_constructs()
        assert len(all_prims) == 4
        assert deep in all_prims

    def test_all_constructs_walks_retry_body(self):
        inner = _LeafStub[In, Out]()
        retry = Retry[In, Out](
            max_attempts=2,
            until=lambda s: True,
            body=inner,
        )
        process = Process(root=retry)
        assert len(process.all_constructs()) == 2
        assert inner in process.all_constructs()

    def test_all_constructs_walks_retry_resolver(self):
        inner = _LeafStub[In, Out]()
        resolver = _LeafStub[In, Out]()
        retry = Retry[In, Out](
            max_attempts=2,
            until=lambda s: True,
            body=inner,
            on_max_attempts_resolver=resolver,
        )
        process = Process(root=retry)
        all_prims = process.all_constructs()
        assert len(all_prims) == 3
        assert resolver in all_prims

    def test_all_constructs_walks_conditional_branches(self):
        then = _LeafStub[In, Out]()
        else_ = _LeafStub[In, Out]()
        cond = Conditional[In, Out](
            condition=lambda s: True,
            then_branch=then,
            else_branch=else_,
        )
        process = Process(root=cond)
        all_prims = process.all_constructs()
        assert len(all_prims) == 3
        assert then in all_prims
        assert else_ in all_prims

    def test_all_constructs_skips_none_else_branch(self):
        then = _LeafStub[In, Out]()
        cond = Conditional[In, Out](
            condition=lambda s: True,
            then_branch=then,
        )
        process = Process(root=cond)
        assert len(process.all_constructs()) == 2
