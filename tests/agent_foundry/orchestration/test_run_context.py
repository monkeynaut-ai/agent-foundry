from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
from agent_foundry.orchestration.run_context import (
    AgentRunContext,
    NoOpLifecycleWriter,
)


def test_agent_run_context_has_required_core_fields() -> None:
    ctx = AgentRunContext(
        run_id="run-1",
        container_registry=object(),
        lifecycle_writer=NoOpLifecycleWriter(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )
    assert ctx.run_id == "run-1"
    assert ctx.env["CLAUDE_CODE_OAUTH_TOKEN"] == "tok"


def test_no_op_lifecycle_writer_accepts_append_and_discards() -> None:
    writer = NoOpLifecycleWriter()
    # Must not raise; must not persist anywhere visible.
    writer.append(LifecycleEvent.RUN_STARTED, payload={"x": 1})
    writer.append(LifecycleEvent.RUN_ENDED)
    # No public read surface — the whole point is that it's a sink.


def test_agent_run_context_env_is_required() -> None:
    with pytest.raises(ValidationError):
        AgentRunContext(  # type: ignore[call-arg]
            run_id="r",
            container_registry=object(),
            lifecycle_writer=NoOpLifecycleWriter(),
        )


# -- Full AgentRunContext shape --
# These tests pin the full AgentRunContext shape: artifacts_dir,
# responder_provider, cancel_event, frozen=True, and the module-level
# ContextVar + require_current_run_context() helper.


def _responder_provider_stub() -> object:
    """Stand-in ResponderProvider for context-shape tests."""
    return object()


def test_agent_run_context_accepts_full_fields(tmp_path: Path) -> None:
    ctx = AgentRunContext(
        run_id="run-full",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=_responder_provider_stub(),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )
    assert ctx.run_id == "run-full"
    assert ctx.artifacts_dir == tmp_path
    assert isinstance(ctx.cancel_event, asyncio.Event)


def test_agent_run_context_cancel_event_starts_unset(tmp_path: Path) -> None:
    ctx = AgentRunContext(
        run_id="run-full",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=_responder_provider_stub(),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )
    assert ctx.cancel_event.is_set() is False


def test_agent_run_context_is_frozen(tmp_path: Path) -> None:
    ctx = AgentRunContext(
        run_id="run-full",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=_responder_provider_stub(),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )
    with pytest.raises(ValidationError):
        ctx.run_id = "other"  # type: ignore[misc]


def test_agent_run_context_frozen_permits_cancel_event_mutation(
    tmp_path: Path,
) -> None:
    # frozen=True blocks attribute reassignment but NOT mutation of mutable
    # field values. This is load-bearing — the cancel_event must be settable.
    ctx = AgentRunContext(
        run_id="run-full",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=_responder_provider_stub(),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )
    ctx.cancel_event.set()
    assert ctx.cancel_event.is_set() is True


def test_agent_run_context_run_id_nonempty(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        AgentRunContext(
            run_id="",
            artifacts_dir=tmp_path,
            container_registry=object(),
            responder_provider=_responder_provider_stub(),
            lifecycle_writer=NoOpLifecycleWriter(),
            cancel_event=asyncio.Event(),
            env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
        )


# -- ContextVar helpers --


def _make_ctx(tmp_path: Path) -> AgentRunContext:
    return AgentRunContext(
        run_id="run-cv",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=_responder_provider_stub(),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )


def test_require_current_run_context_raises_when_unset() -> None:
    from agent_foundry.orchestration.run_context import (
        current_run_context,
        require_current_run_context,
    )

    assert current_run_context.get() is None
    with pytest.raises(RuntimeError, match="AgentRunContext"):
        require_current_run_context()


def test_require_current_run_context_returns_set_value(tmp_path: Path) -> None:
    from agent_foundry.orchestration.run_context import (
        current_run_context,
        require_current_run_context,
    )

    ctx = _make_ctx(tmp_path)
    token = current_run_context.set(ctx)
    try:
        assert require_current_run_context() is ctx
    finally:
        current_run_context.reset(token)


def test_require_current_run_context_raises_after_reset(tmp_path: Path) -> None:
    from agent_foundry.orchestration.run_context import (
        current_run_context,
        require_current_run_context,
    )

    ctx = _make_ctx(tmp_path)
    token = current_run_context.set(ctx)
    current_run_context.reset(token)
    with pytest.raises(RuntimeError):
        require_current_run_context()


class TestDefaultArtifactsDir:
    """The fallback used when ``AgentRunContext`` is constructed without
    an explicit ``artifacts_dir``. Must land under ``<cwd>/.tmp/`` so
    leaked dirs stay scoped to the project and don't accumulate in
    system /tmp."""

    def test_given_no_artifacts_dir_when_constructed_then_lands_under_cwd_dot_tmp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        ctx = AgentRunContext(
            run_id="run-default",
            container_registry=object(),
            lifecycle_writer=NoOpLifecycleWriter(),
            env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
        )
        assert ctx.artifacts_dir.parent == tmp_path / ".tmp"
        assert ctx.artifacts_dir.name.startswith("agent_foundry_run_")
        assert ctx.artifacts_dir.is_dir()

    def test_given_no_dot_tmp_when_constructed_then_creates_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert not (tmp_path / ".tmp").exists()
        AgentRunContext(
            run_id="run-creates-dot-tmp",
            container_registry=object(),
            lifecycle_writer=NoOpLifecycleWriter(),
            env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
        )
        assert (tmp_path / ".tmp").is_dir()

    def test_given_two_constructions_when_compared_then_paths_differ(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        a = AgentRunContext(
            run_id="run-a",
            container_registry=object(),
            lifecycle_writer=NoOpLifecycleWriter(),
            env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
        )
        b = AgentRunContext(
            run_id="run-b",
            container_registry=object(),
            lifecycle_writer=NoOpLifecycleWriter(),
            env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
        )
        assert a.artifacts_dir != b.artifacts_dir
