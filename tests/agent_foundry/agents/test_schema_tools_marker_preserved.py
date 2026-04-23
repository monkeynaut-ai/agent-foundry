"""Regression test: ``x-agent-file-path`` markers are stripped from the
Claude-bound schema but preserved on the raw ``model_json_schema()``
that production file-path verification reads.

This file previously asserted markers must SURVIVE
``to_claude_code_schema``, on the premise that unknown extension keys
should pass through for future consumers. That premise conflicted with
Claude Code 2.1.x's observed behavior: any ``x-*`` extension keyword
makes the CLI silently refuse to inject the ``StructuredOutput`` tool,
producing ``result.subtype == "success"`` runs with no envelope — the
exact silent-disable failure class the ``discriminator`` strip already
guards against.

The container executor reads file-path markers via
``walk_file_path_fields(output_type.model_json_schema())``
(``container_executor.py:376``) — i.e. the raw Pydantic schema, never
the sanitized one. So stripping ``x-*`` from the sanitized copy is safe.
"""

from typing import Annotated, Any

from pydantic import BaseModel

from agent_foundry.agents.schema_tools import to_claude_code_schema
from agent_foundry.models.markers import AgentFilePath


class _Nested(BaseModel):
    transcript_path: Annotated[str, AgentFilePath(max_size_bytes=50_000_000)]


class _Outer(BaseModel):
    review_path: Annotated[str, AgentFilePath()]
    nested: _Nested


def _count_markers(node: Any) -> int:
    """Count every ``x-agent-file-path`` occurrence anywhere in the schema tree."""
    count = 0
    if isinstance(node, dict):
        if "x-agent-file-path" in node:
            count += 1
        for value in node.values():
            count += _count_markers(value)
    elif isinstance(node, list):
        for item in node:
            count += _count_markers(item)
    return count


def test_raw_schema_still_carries_markers_for_verification() -> None:
    """Production file-path verification uses ``model_json_schema()`` directly.
    Those markers must still be present there (nothing here strips them)."""
    raw = _Outer.model_json_schema()
    # inline on review_path + on _Nested.transcript_path inside $defs.
    assert _count_markers(raw) == 2


def test_sanitized_schema_has_markers_stripped() -> None:
    """The schema passed to Claude Code via ``--json-schema`` must be
    free of ``x-*`` extensions, else 2.1.x silently disables structured
    output enforcement."""
    flat = to_claude_code_schema(_Outer)
    assert "$defs" not in flat
    assert _count_markers(flat) == 0


def test_sanitized_schema_strips_any_x_prefix_key() -> None:
    """The strip rule is generic: any ``x-*`` key. Not just our own markers."""
    flat = to_claude_code_schema(_Outer)

    def has_x_key(node: Any) -> bool:
        if isinstance(node, dict):
            if any(isinstance(k, str) and k.startswith("x-") for k in node):
                return True
            return any(has_x_key(v) for v in node.values())
        if isinstance(node, list):
            return any(has_x_key(item) for item in node)
        return False

    assert not has_x_key(flat)
