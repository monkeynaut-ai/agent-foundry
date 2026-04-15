"""Regression test: ``x-agent-file-path`` markers survive ``to_claude_code_schema``.

Task D.3 of CS7 Plan 2. The Plan 2 executor walks the flattened schema
returned by ``to_claude_code_schema`` looking for ``x-agent-file-path``
extension keys. If the schema flattener ever strips unknown keys, the
executor silently loses all file-path validation. This test pins the
survival of those markers through the flattening transform.
"""

from typing import Annotated, Any

from pydantic import BaseModel

from agent_foundry.acp.schema_tools import to_claude_code_schema
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


def test_agent_file_path_markers_survive_flattening() -> None:
    raw = _Outer.model_json_schema()
    # Sanity: the raw schema carries markers on review_path (inline) and on
    # the $defs entry for _Nested.transcript_path.
    assert _count_markers(raw) == 2

    flat = to_claude_code_schema(_Outer)

    # $defs must be gone post-flatten; markers must remain on the exact same
    # properties, now inlined.
    assert "$defs" not in flat
    assert _count_markers(flat) == 2


def test_outer_marker_preserved_on_exact_property() -> None:
    flat = to_claude_code_schema(_Outer)
    review_path = flat["properties"]["review_path"]
    marker = review_path["x-agent-file-path"]
    assert marker == {"max_size_bytes": 10_000_000}


def test_nested_marker_preserved_after_inlining() -> None:
    flat = to_claude_code_schema(_Outer)
    nested = flat["properties"]["nested"]
    # _Nested must be inlined (no $ref), and transcript_path must still
    # carry its marker with the custom max_size_bytes.
    assert "$ref" not in nested
    transcript_path = nested["properties"]["transcript_path"]
    marker = transcript_path["x-agent-file-path"]
    assert marker == {"max_size_bytes": 50_000_000}
