"""Tests for host-side AgentFilePath verification in the container executor.

Two layers:

* Schema extraction: pin the behavior of extracting ``FilePathFieldSpec``
  entries from the agent's output-model JSON schema — the schema the
  container executor walks via ``walk_file_path_fields`` to drive
  host-side verification after every successful turn. Only
  ``SuccessOutcome[O]``'s payload can carry agent-written file paths, so
  the executor walks the output model's schema to collect specs.

* Full executor loop: host-side verification + bounded retry exercised
  end-to-end against a scripted adapter.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel

from agent_foundry.agents.agent_turn_envelope import AgentTurnEnvelope
from agent_foundry.agents.schema_tools import to_claude_code_schema
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
    """Extract FilePathFieldSpec list from the output-model schema.

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
        # --json-schema. The verification logic doesn't need this
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


# ---------------------------------------------------------------------------
# Host-side verification + bounded retry
# ---------------------------------------------------------------------------
#
# Post-success envelope, the executor:
#   1. Resolves declared paths via ``extract_paths``.
#   2. For each path, reads through ``ContainerManager.read_file_from_container``
#      (returns None on missing) and checks existence + size.
#   3. Empty violations → return payload.
#   4. Non-empty → issue ONE bounded ``--resume`` correction turn + re-verify.
#   5. Second failure → raise ``AgentFailedError(reason="file_path_verification_failed: ...")``.


import pytest  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from agent_foundry.orchestration import container_executor  # noqa: E402
from agent_foundry.orchestration.container_executor import (  # noqa: E402
    TurnResult,
    run_agent_in_container,
)
from agent_foundry.orchestration.errors import AgentFailedError  # noqa: E402
from agent_foundry.orchestration.registry import AgentContainerRegistry  # noqa: E402
from agent_foundry.orchestration.run_context import (  # noqa: E402
    AgentRunContext,
    NoOpLifecycleWriter,
)
from agent_foundry.primitives.models import (  # noqa: E402
    AgentAction,
    ContainerReusePolicy,
)

from .fakes import FakeClaudeCodeAdapter, FakeContainerManager  # noqa: E402


class _VerifyInput(BaseModel):
    task: str


class _VerifyOutput(BaseModel):
    """Success payload with a single AgentFilePath-marked field."""

    review_path: Annotated[str, AgentFilePath()]


def _make_verify_primitive() -> AgentAction[_VerifyInput, _VerifyOutput]:
    return AgentAction[_VerifyInput, _VerifyOutput](
        name="reviewer",
        prompt_builder=lambda s: f"do: {s.task}",
        instructions_provider=lambda: "Be precise.",
        executor=run_agent_in_container,
        reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
    )


def _make_ctx(fake_mgr: FakeContainerManager) -> AgentRunContext:
    registry = AgentContainerRegistry(
        manager=fake_mgr,
        base_image_tag="agent-foundry-base:test",
        workspace_volume="vol-verify",
    )
    return AgentRunContext(
        run_id="run-verify",
        container_registry=registry,
        lifecycle_writer=NoOpLifecycleWriter(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )


def _install_adapter(monkeypatch: pytest.MonkeyPatch, adapter: FakeClaudeCodeAdapter) -> None:
    """Wrap the scripted adapter as a ``run_turn`` callable and install it.

    These verification tests use the older ``FakeClaudeCodeAdapter``
    shape (``run_turn(*, prompt, json_schema, resume_session_id) ->
    envelope``). The current executor calls
    ``_run_claude_turn(live, *, prompt, resume_session_id, schema) ->
    TurnResult``. This helper adapts the former to the latter so the
    tests keep their scripting ergonomics.
    """

    async def _fake_run_turn(
        live: object,
        *,
        prompt: str,
        resume_session_id: str | None,
        schema: dict,
    ) -> TurnResult:
        envelope = await adapter.run_turn(
            prompt=prompt,
            json_schema=schema,
            resume_session_id=resume_session_id,
        )
        return TurnResult(envelope=envelope, session_id="sess-verify", raw_output=b"")

    monkeypatch.setattr(container_executor, "_run_claude_turn", _fake_run_turn)


class TestExecutorFilePathVerification:
    """Host-side verification + bounded retry around SuccessOutcome."""

    @pytest.mark.asyncio
    async def test_happy_path_no_retry_when_all_paths_valid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adapter = FakeClaudeCodeAdapter(
            turn_script=[
                {
                    "outcome": {
                        "kind": "success",
                        "payload": {"review_path": "/workspace/review.md"},
                    }
                }
            ]
        )
        _install_adapter(monkeypatch, adapter)

        fake_mgr = FakeContainerManager()
        fake_mgr.read_file_script = {"/workspace/review.md": ["# review body"]}

        result = await run_agent_in_container(
            primitive=_make_verify_primitive(),
            prompt="go",
            run_ctx=_make_ctx(fake_mgr),
        )

        assert isinstance(result, _VerifyOutput)
        assert result.review_path == "/workspace/review.md"
        # Exactly one adapter turn — no retry.
        assert len(adapter.calls) == 1
        # One verification read for the declared path (the executor also
        # snapshots /home/claude/.claude/CLAUDE.md at invocation end;
        # filter that out).
        verification_reads = [r for r in fake_mgr.read_file_log if r[0] == "/workspace/review.md"]
        assert verification_reads == [("/workspace/review.md", False, len(b"# review body"))]

    @pytest.mark.asyncio
    async def test_missing_file_retry_recovers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        adapter = FakeClaudeCodeAdapter(
            turn_script=[
                {
                    "outcome": {
                        "kind": "success",
                        "payload": {"review_path": "/workspace/review.md"},
                    }
                },
                {
                    "outcome": {
                        "kind": "success",
                        "payload": {"review_path": "/workspace/review.md"},
                    }
                },
            ]
        )
        _install_adapter(monkeypatch, adapter)

        fake_mgr = FakeContainerManager()
        # First read: missing. Second read (after correction turn): content.
        fake_mgr.read_file_script = {"/workspace/review.md": [None, "# recovered"]}

        result = await run_agent_in_container(
            primitive=_make_verify_primitive(),
            prompt="go",
            run_ctx=_make_ctx(fake_mgr),
        )

        assert isinstance(result, _VerifyOutput)
        # Two adapter turns — original plus one bounded retry.
        assert len(adapter.calls) == 2
        # The retry must be a ``--resume`` turn: the second call carries a
        # non-None resume_session_id. (The executor supplies whatever id the
        # adapter surfaces; the exact value is driver-dependent, so we only
        # assert the retry is resumed, not fresh.)
        assert adapter.calls[1]["resume"] is not None
        # The correction prompt must name the violating path so the agent
        # knows what to fix.
        assert "/workspace/review.md" in adapter.calls[1]["prompt"]
        # Verification ran twice on that path.
        read_paths = [entry[0] for entry in fake_mgr.read_file_log]
        assert read_paths.count("/workspace/review.md") == 2

    @pytest.mark.asyncio
    async def test_oversized_file_retry_recovers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        adapter = FakeClaudeCodeAdapter(
            turn_script=[
                {
                    "outcome": {
                        "kind": "success",
                        "payload": {"review_path": "/workspace/review.md"},
                    }
                },
                {
                    "outcome": {
                        "kind": "success",
                        "payload": {"review_path": "/workspace/review.md"},
                    }
                },
            ]
        )
        _install_adapter(monkeypatch, adapter)

        # Default limit is PLATFORM_DEFAULT_MAX_FILE_BYTES (10MB). First read
        # blows past it; retry fits.
        oversized = "x" * (PLATFORM_DEFAULT_MAX_FILE_BYTES + 1)
        fake_mgr = FakeContainerManager()
        fake_mgr.read_file_script = {"/workspace/review.md": [oversized, "compact body"]}

        result = await run_agent_in_container(
            primitive=_make_verify_primitive(),
            prompt="go",
            run_ctx=_make_ctx(fake_mgr),
        )

        assert isinstance(result, _VerifyOutput)
        assert len(adapter.calls) == 2
        assert adapter.calls[1]["resume"] is not None
        # Correction prompt should reference the oversized path.
        assert "/workspace/review.md" in adapter.calls[1]["prompt"]

    @pytest.mark.asyncio
    async def test_missing_file_retry_still_fails_raises_agent_failed_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adapter = FakeClaudeCodeAdapter(
            turn_script=[
                {
                    "outcome": {
                        "kind": "success",
                        "payload": {"review_path": "/workspace/review.md"},
                    }
                },
                {
                    "outcome": {
                        "kind": "success",
                        "payload": {"review_path": "/workspace/review.md"},
                    }
                },
            ]
        )
        _install_adapter(monkeypatch, adapter)

        fake_mgr = FakeContainerManager()
        # Both reads missing — bounded retry exhausted.
        fake_mgr.read_file_script = {"/workspace/review.md": [None, None]}

        with pytest.raises(AgentFailedError) as excinfo:
            await run_agent_in_container(
                primitive=_make_verify_primitive(),
                prompt="go",
                run_ctx=_make_ctx(fake_mgr),
            )

        assert "file_path_verification_failed" in excinfo.value.reason
        # Exactly two adapter turns — original + one retry. No unbounded loop.
        assert len(adapter.calls) == 2
        # Under the current contract the container is kept alive for reuse
        # across invocations and only destroyed by ``registry.shutdown_all``,
        # so at this point it is still ``running``.
        assert fake_mgr.handles[0].status == "running"

    @pytest.mark.asyncio
    async def test_failure_outcome_skips_verification_and_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adapter = FakeClaudeCodeAdapter(
            turn_script=[
                {
                    "outcome": {
                        "kind": "failed",
                        "reason": "unresolvable ambiguity",
                    }
                }
            ]
        )
        _install_adapter(monkeypatch, adapter)

        fake_mgr = FakeContainerManager()
        # If the executor were to verify on failure envelopes, it would hit
        # this script. The test asserts it does NOT.
        fake_mgr.read_file_script = {"/workspace/review.md": ["should-not-read"]}

        with pytest.raises(AgentFailedError) as excinfo:
            await run_agent_in_container(
                primitive=_make_verify_primitive(),
                prompt="go",
                run_ctx=_make_ctx(fake_mgr),
            )

        assert "unresolvable ambiguity" in excinfo.value.reason
        # No verification reads on non-success envelopes (the executor
        # still snapshots /home/claude/.claude/CLAUDE.md at invocation
        # end; filter that out of the assertion).
        verification_reads = [r for r in fake_mgr.read_file_log if not r[0].endswith("CLAUDE.md")]
        assert verification_reads == []
        # Only the initial turn — no retry for FailureOutcome.
        assert len(adapter.calls) == 1
