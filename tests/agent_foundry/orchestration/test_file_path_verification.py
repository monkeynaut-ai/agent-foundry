"""Tests for host-side AgentFilePath verification in the container executor.

Task E.1 (this file, initial version):
    Pin the behavior of extracting ``FilePathFieldSpec`` entries from the
    agent's output-model JSON schema — the schema the container executor
    walks via ``walk_file_path_fields`` to drive host-side verification
    after every successful turn. Only ``SuccessOutcome[O]``'s payload can
    carry agent-written file paths, so the executor walks the output
    model's schema to collect specs.

Task E.2 (future) will extend this file with verification + retry tests that
exercise the full executor loop once host-side wiring exists.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel

from agent_foundry.acp.agent_turn_envelope import AgentTurnEnvelope
from agent_foundry.acp.schema_tools import to_claude_code_schema
from agent_foundry.models.markers import (
    PLATFORM_DEFAULT_MAX_FILE_BYTES,
    AgentFilePath,
    FilePathFieldSpec,
    walk_file_path_fields,
)


class OutputWithPath(BaseModel):
    """Agent success payload carrying a single AgentFilePath-marked field."""

    review_path: Annotated[str, AgentFilePath()]
    summary: str


class OutputWithCustomPath(BaseModel):
    """Agent success payload with a custom per-field size limit."""

    transcript_path: Annotated[str, AgentFilePath(max_size_bytes=50_000_000)]


class OutputWithListOfPaths(BaseModel):
    """Agent success payload with a list of AgentFilePath-marked strings."""

    paths: list[Annotated[str, AgentFilePath()]]


class OutputWithoutPaths(BaseModel):
    """Agent success payload with no AgentFilePath markers at all."""

    title: str
    count: int


class TestExecutorSpecExtraction:
    """E.1: extracting FilePathFieldSpec list from the output-model schema.

    The executor will walk the output model ``O`` (i.e., the type parameter
    of ``AgentTurnEnvelope[O]``) to obtain the ``list[FilePathFieldSpec]``
    used host-side to verify agent-written files after every successful
    turn. These tests pin that extraction behavior by invoking the same
    helper call the executor uses, without exercising the executor loop.

    Sanity: the envelope schema itself is also buildable (that's what the
    executor hands to ``claude --json-schema``), so we build it here too
    to keep the wiring honest.
    """

    def test_envelope_schema_builds_for_output_model(self) -> None:
        # Pin that we can construct the schema the executor passes to
        # --json-schema. The E.2 verification logic doesn't need this
        # schema (it walks the output model directly) but building it
        # is part of the executor's per-invocation setup.
        envelope_schema = to_claude_code_schema(AgentTurnEnvelope[OutputWithPath])
        assert "properties" in envelope_schema
        assert "outcome" in envelope_schema["properties"]

    def test_extracts_single_spec_from_output_schema(self) -> None:
        specs = walk_file_path_fields(OutputWithPath.model_json_schema())

        assert len(specs) == 1
        (spec,) = specs
        assert isinstance(spec, FilePathFieldSpec)
        assert spec.json_pointer == "/review_path"
        assert spec.max_size_bytes == PLATFORM_DEFAULT_MAX_FILE_BYTES

    def test_extracts_custom_max_size_from_output_schema(self) -> None:
        specs = walk_file_path_fields(OutputWithCustomPath.model_json_schema())

        assert len(specs) == 1
        assert specs[0].json_pointer == "/transcript_path"
        assert specs[0].max_size_bytes == 50_000_000

    def test_extracts_list_wildcard_from_output_schema(self) -> None:
        specs = walk_file_path_fields(OutputWithListOfPaths.model_json_schema())

        assert len(specs) == 1
        assert specs[0].json_pointer == "/paths/*"
        assert specs[0].max_size_bytes == PLATFORM_DEFAULT_MAX_FILE_BYTES

    def test_empty_specs_when_output_model_has_no_markers(self) -> None:
        # A model without any AgentFilePath markers must yield [] — the
        # executor uses this to short-circuit verification entirely.
        specs = walk_file_path_fields(OutputWithoutPaths.model_json_schema())
        assert specs == []
