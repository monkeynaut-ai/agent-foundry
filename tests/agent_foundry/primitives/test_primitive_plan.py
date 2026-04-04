"""Tests for PrimitivePlan container and graph introspection."""

from __future__ import annotations

from pydantic import BaseModel

from agent_foundry.primitives.models import (
    Conditional,
    Loop,
    Primitive,
    Retry,
    Sequence,
)
from agent_foundry.primitives.plan import PrimitivePlan


class In(BaseModel):
    value: str


class Out(BaseModel):
    result: str


class TestPrimitivePlan:
    """PrimitivePlan holds a root primitive and provides graph introspection."""

    def test_given_root_primitive_when_created_then_accessible(self):
        root = Primitive(input=In, output=Out)
        plan = PrimitivePlan(root=root)
        assert plan.root is root

    def test_all_primitives_returns_single_root(self):
        root = Primitive(input=In, output=Out)
        plan = PrimitivePlan(root=root)
        assert len(plan.all_primitives()) == 1
        assert plan.all_primitives()[0] is root

    def test_all_primitives_finds_sequence_children(self):
        a = Primitive(input=In, output=Out)
        b = Primitive(input=In, output=Out)
        seq = Sequence(input=In, output=Out, steps=[a, b])
        plan = PrimitivePlan(root=seq)
        assert len(plan.all_primitives()) == 3

    def test_all_primitives_finds_deeply_nested(self):
        deep = Primitive(input=In, output=Out)
        inner_seq = Sequence(input=In, output=Out, steps=[deep])
        loop = Loop(
            input=In,
            output=Out,
            over=lambda s: [],
            item_key="item",
            body=inner_seq,
        )
        root = Sequence(input=In, output=Out, steps=[loop])
        plan = PrimitivePlan(root=root)
        all_prims = plan.all_primitives()
        assert len(all_prims) == 4
        assert deep in all_prims

    def test_all_primitives_walks_retry_body(self):
        inner = Primitive(input=In, output=Out)
        retry = Retry(
            input=In,
            output=Out,
            max_attempts=2,
            until=lambda s: True,
            body=inner,
            on_exhausted="fail",
        )
        plan = PrimitivePlan(root=retry)
        assert len(plan.all_primitives()) == 2
        assert inner in plan.all_primitives()

    def test_all_primitives_walks_conditional_branches(self):
        then = Primitive(input=In, output=Out)
        else_ = Primitive(input=In, output=Out)
        cond = Conditional(
            input=In,
            output=Out,
            condition=lambda s: True,
            then_branch=then,
            else_branch=else_,
        )
        plan = PrimitivePlan(root=cond)
        all_prims = plan.all_primitives()
        assert len(all_prims) == 3
        assert then in all_prims
        assert else_ in all_prims

    def test_all_primitives_skips_none_else_branch(self):
        then = Primitive(input=In, output=Out)
        cond = Conditional(
            input=In,
            output=Out,
            condition=lambda s: True,
            then_branch=then,
        )
        plan = PrimitivePlan(root=cond)
        assert len(plan.all_primitives()) == 2
