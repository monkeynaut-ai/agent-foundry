"""Response models for the eval API.

``TargetSpec`` is the public, JSON-serializable view of an evaluation
target. It exposes only what an external client (UI, web app, future
SDK) needs to know — the target's name, its kind, and its input /
output JSON schemas — never the live Python object behind it.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_foundry.evals.models import EvalTargetKind
from agent_foundry.primitives.ai_call import AICall
from agent_foundry.primitives.models import get_type_args


class TargetSpec(BaseModel):
    """Public, JSON-serializable description of an evaluation target."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    kind: EvalTargetKind
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


def target_spec_from_ai_call(name: str, call: AICall) -> TargetSpec:
    """Build a :class:`TargetSpec` from a registered ``AICall`` instance."""
    input_type, output_type = get_type_args(call)
    return TargetSpec(
        name=name,
        kind=EvalTargetKind.AI_CALL,
        input_schema=input_type.model_json_schema(),
        output_schema=output_type.model_json_schema(),
    )
