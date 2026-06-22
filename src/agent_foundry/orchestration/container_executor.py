"""Inner turn loop for running an AgentAction in its container.

Provides:
  * responder round-trip for ``ClarificationOutcome`` / ``PermissionOutcome``
  * reuse-policy dispatch across invocations (``REUSE_RESUME`` vs
    ``REUSE_NEW_SESSION``); within an invocation, continuations always
    reuse the current-turn session id
  * session-id recording on :class:`LiveContainer` via
    :meth:`AgentContainerRegistry.record_session_id`
  * lifecycle event emission: ``AGENT_INVOCATION_STARTED``,
    ``TURN_STARTED`` / ``TURN_COMPLETED``, ``RESPONDER_REQUESTED`` /
    ``RESPONDER_ANSWERED``, ``AGENT_INVOCATION_COMPLETED`` /
    ``AGENT_INVOCATION_FAILED``
  * file snapshotting on success via
    :meth:`ContainerManager.copy_from_container` into
    ``<run_dir>/<agent_name>/turns/<n>/collected_files/``
  * cancel-event check between turns
  * max 20 responder iterations per invocation

The per-turn mechanics — shelling out to ``claude`` inside the live
container via :meth:`ContainerManagerBase.exec_run` and parsing
stream-json — live in the module-level helper :func:`_run_claude_turn`.
Tests inject a scripted fake by passing ``run_turn=<fake>`` as a
keyword argument to :func:`run_agent_in_container`; no global test
seam is required.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from agent_foundry.agents.agent_turn_envelope import (
    AgentTurnEnvelope,
    ClarificationOutcome,
    PermissionOutcome,
    TurnOutcomeKind,
)
from agent_foundry.agents.lifecycle import ContainerHandleBase, ContainerManagerBase
from agent_foundry.agents.schema_tools import to_claude_code_schema
from agent_foundry.constructs.models import (
    AgentAction,
    ContainerReusePolicy,
    get_type_args,
)
from agent_foundry.models.markers import (
    FilePathFieldSpec,
    extract_paths,
    walk_file_path_fields,
)
from agent_foundry.models.usage import TokenUsage
from agent_foundry.orchestration.artifacts import agent_turn_dir
from agent_foundry.orchestration.errors import AgentFailedError
from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
from agent_foundry.orchestration.registry import LiveContainer
from agent_foundry.orchestration.run_context import RunContext
from agent_foundry.responders.models import (
    ResponderContext,
    build_request_from_outcome,
)

logger = logging.getLogger(__name__)


MAX_RESPONDER_ITERATIONS = 20

# Bounded retry for transient upstream API errors (5xx, 429). claude's CLI
# already retries 5xx internally; this is a one-shot safety net for the
# rare case its budget is exhausted before the run completes.
_RETRYABLE_API_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
_MAX_TURN_API_RETRIES: int = 1
_TURN_API_RETRY_SLEEP_SECONDS: float = 2.0

# Per-turn cap on stream.jsonl writes for failed turns. The full claude
# stream-json for a turn typically lands well under 1 MB; failures that
# blow past this are pathological and indicate a separate bug to chase.
# We still want a postmortem trail, so cap-and-mark rather than drop.
_FAILED_TURN_STREAM_MAX_BYTES: int = 100 * 1024 * 1024
_FAILED_TURN_TRUNCATION_MARKER: bytes = (
    b"\n--- output truncated by container_executor (exceeded 100MiB failed-turn cap) ---\n"
)


class AgentExecFailedError(RuntimeError):
    """Raised when an in-container agent invocation exits non-zero or
    fails to produce a parseable envelope.

    Attributes:
      exit_code: the agent process's exit code (137 = SIGKILL/OOM).
      output: full stdout/stderr bytes from the exec.
      container_logs: container log tail captured at the time of failure.
      api_error_status: HTTP status from the trailing result event when
        the agent process gave up after its own retries (None when not
        reported, e.g. SIGKILL).
      num_turns: model turns the process completed before exiting.
      api_error_message: short error text from the trailing result event.
    """

    def __init__(
        self,
        message: str,
        *,
        exit_code: int,
        output: bytes,
        container_logs: str,
        api_error_status: int | None = None,
        num_turns: int | None = None,
        api_error_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.output = output
        self.container_logs = container_logs
        self.api_error_status = api_error_status
        self.num_turns = num_turns
        self.api_error_message = api_error_message


class ParsedResultEvent(BaseModel):
    """Fields pulled from a claude stream's trailing ``result`` event.

    All fields are optional: a stream with no ``result`` event (e.g. a
    SIGKILL'd container) yields an instance with every field ``None``,
    so usage/cost capture degrades to "unknown" rather than crashing.
    ``total_cost_usd`` is the Claude-Code-reported dollar figure for the
    whole invocation; ``usage`` carries the four token buckets.
    """

    api_error_status: int | None = None
    num_turns: int | None = None
    result_text: str | None = None
    total_cost_usd: float | None = None
    usage: TokenUsage | None = None


def _parse_result_event(output: bytes) -> ParsedResultEvent:
    """Scan a claude stream for the trailing ``result`` event.

    Returns an all-``None`` :class:`ParsedResultEvent` when no parseable
    ``result`` event is present.
    """
    for raw_line in output.decode(errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        if evt.get("type") == "result":
            cost = evt.get("total_cost_usd")
            return ParsedResultEvent(
                api_error_status=evt.get("api_error_status"),
                num_turns=evt.get("num_turns"),
                result_text=evt.get("result"),
                total_cost_usd=cost if isinstance(cost, (int, float)) else None,
                usage=TokenUsage.from_mapping(evt.get("usage")),
            )
    return ParsedResultEvent()


class TurnResult(BaseModel):
    """Result of one ``RunTurn`` invocation.

    ``envelope`` is the raw dict payload matching ``AgentTurnEnvelope[O]``;
    the caller validates it against the product's declared output type.
    ``raw_output`` is the full executor stream (claude JSONL for the
    default implementation, or equivalent for alternative ``RunTurn``
    implementations) — ``run_agent_in_container`` tees this to stderr
    and to the per-turn ``stream.jsonl`` artifact on every turn,
    regardless of outcome, so stream persistence is free for every
    ``RunTurn`` implementation.
    """

    envelope: dict[str, Any]
    session_id: str | None
    raw_output: bytes
    usage: TokenUsage | None = None
    total_cost_usd: float | None = None
    num_turns: int | None = None


# Contract for the ``run_turn`` callable threaded through
# :func:`run_agent_in_container`. Tests inject fakes matching this
# signature via the ``run_turn=`` keyword argument.
RunTurn = Callable[..., Awaitable[TurnResult]]


async def _run_claude_turn(
    live: LiveContainer,
    *,
    prompt: str,
    resume_session_id: str | None,
    schema: dict[str, Any],
    model: str,
    effort: str | None = None,
    skip_permissions: bool = False,
    cwd: str | None = None,
) -> TurnResult:
    """Invoke ``claude`` once inside the live container and return a
    :class:`TurnResult` carrying the parsed envelope dict, captured
    session id, and the full raw JSONL stream.

    This is the production helper that :func:`run_agent_in_container`
    calls by default. It shells out via
    ``live.manager.exec_run(live.handle, ['claude', '-p', prompt, …])``,
    runs the blocking call in a worker thread, and parses the
    stream-json output for:

      * the ``system/init`` event (session id)
      * the assistant ``StructuredOutput`` tool_use (envelope payload)
      * a fallback: a ```json …``` code block in an assistant text
        message, which Claude Code sometimes emits instead of the
        synthetic ``StructuredOutput`` tool call despite the
        ``--json-schema`` flag.

    Raises ``RuntimeError`` if claude exits non-zero or no envelope
    can be extracted. Stream persistence (stderr tee + per-turn
    ``stream.jsonl``) is performed by the caller on the returned
    ``TurnResult.raw_output``, not here — so every ``RunTurn``
    implementation gets it for free.
    """

    def _do_exec() -> TurnResult:
        # Run via gosu so initgroups(3) is called, which picks up supplementary
        # GIDs from /etc/group. docker exec with --user=<name> does not reliably
        # call initgroups, so processes exec'd as "claude" don't see GIDs added
        # by usermod in the entrypoint. gosu explicitly calls initgroups before
        # dropping privileges, making supplementary groups visible to the kernel.
        cmd = [
            "gosu",
            "claude",
            "/home/claude/.local/bin/claude",
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--json-schema",
            json.dumps(schema),
            "--model",
            model,
        ]
        if effort is not None:
            cmd += ["--effort", effort]
        if skip_permissions:
            cmd.append("--dangerously-skip-permissions")
        if resume_session_id:
            cmd.extend(["--resume", resume_session_id])
        result = live.manager.exec_run(live.handle, cmd, user="root", workdir=cwd)
        exit_code = result.exit_code
        output = result.output
        if exit_code != 0:
            logs = live.manager.read_logs(live.handle, tail=80).decode(errors="replace")
            parsed = _parse_result_event(output)
            raise AgentExecFailedError(
                f"claude exec failed (exit={exit_code}):\n"
                f"stdout/stderr: {output.decode(errors='replace')}\n\n"
                f"container logs: {logs}",
                exit_code=exit_code,
                output=output,
                container_logs=logs,
                api_error_status=parsed.api_error_status,
                num_turns=parsed.num_turns,
                api_error_message=parsed.result_text,
            )
        envelope: dict[str, Any] | None = None
        session_id: str | None = None
        fallback_texts: list[str] = []
        for raw_line in output.decode().splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if evt.get("type") == "system" and evt.get("subtype") == "init":
                session_id = evt.get("session_id") or session_id
            elif evt.get("type") == "assistant":
                for block in evt.get("message", {}).get("content", []):
                    if block.get("type") == "tool_use" and block.get("name") == "StructuredOutput":
                        envelope = block.get("input")
                    elif block.get("type") == "text":
                        fallback_texts.append(block.get("text", ""))
        # Fallback: if claude returned the envelope as a ```json …``` text
        # block rather than a ``StructuredOutput`` tool_use (which it
        # sometimes does despite the forced-tool ``--json-schema`` flag),
        # parse it out of the assistant text.
        if envelope is None and fallback_texts:
            combined = "\n".join(fallback_texts)
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", combined, flags=re.DOTALL)
            if match is not None:
                try:
                    parsed = json.loads(match.group(1))
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    if "outcome" in parsed:
                        envelope = parsed
                    else:
                        envelope = {"outcome": {"kind": "success", "payload": parsed}}
        if envelope is None:
            logs = live.manager.read_logs(live.handle, tail=40).decode(errors="replace")
            raise AgentExecFailedError(
                "no StructuredOutput tool use captured\n"
                f"--- claude stdout ({len(output)} bytes) ---\n"
                f"{output.decode(errors='replace')}\n"
                f"--- container logs ---\n{logs}",
                exit_code=exit_code,
                output=output,
                container_logs=logs,
            )
        parsed = _parse_result_event(output)
        return TurnResult(
            envelope=envelope,
            session_id=session_id,
            raw_output=output,
            usage=parsed.usage,
            total_cost_usd=parsed.total_cost_usd,
            num_turns=parsed.num_turns,
        )

    return await asyncio.to_thread(_do_exec)


def _agent_name(construct: AgentAction) -> str:
    """Return the product-declared diagnostic label for the agent.

    Used for artifact directory naming, lifecycle event payloads,
    and log prefixes. Does not participate in composition or lookup.
    """
    return construct.name


_CGROUP_MEMORY_FILES: tuple[str, ...] = (
    "/sys/fs/cgroup/memory.events",
    "/sys/fs/cgroup/memory.peak",
    "/sys/fs/cgroup/memory.current",
    "/sys/fs/cgroup/memory.max",
)


def _read_cgroup_text(live: LiveContainer, path: str) -> str | None:
    """Read a cgroup pseudo-file from inside the container via ``cat``.

    ``ContainerManager.read_file_from_container`` routes through docker's
    ``get_archive`` (a tar stream). That fails for cgroup-v2 entries
    because sysfs pseudo-files do not tar-serialize — every read returns
    ``None`` even though the file is readable via ``cat``. So this helper
    shells out instead, returning the decoded stdout on exit_code == 0
    and ``None`` otherwise (file missing, cgroup-v1 host, exec error).
    """
    try:
        result = live.manager.exec_run(live.handle, ["cat", path])
        if result.exit_code == 0 and result.output:
            return result.output.decode(errors="replace")
    except Exception as exc:
        logger.warning("cgroup read of %s failed for %s: %s", path, live.agent_name, exc)
    return None


def _capture_forensic_fields(
    live: LiveContainer,
    *,
    exit_code_hint: int | None = None,
    api_error_status: int | None = None,
    num_turns: int | None = None,
    api_error_message: str | None = None,
) -> dict[str, Any]:
    """Return structured failure-cause fields for a lifecycle event.

    Best-effort: each lookup is independently try/except'd, and a key is
    only included if the underlying read succeeded.

    Fields:
      * ``exit_code``: ``exit_code_hint`` if supplied, else inspect's
        ``State.ExitCode``.
      * ``oom_killed``: inspect's ``State.OOMKilled``.
      * ``memory_peak_bytes``: cgroup-v2 ``/sys/fs/cgroup/memory.peak``.
      * ``api_error_status`` / ``num_turns`` / ``api_error_message``:
        from the failed-turn result event, when the caller supplies them.
    """
    fields: dict[str, Any] = {}
    if api_error_status is not None:
        fields["api_error_status"] = api_error_status
    if num_turns is not None:
        fields["num_turns"] = num_turns
    if api_error_message is not None:
        fields["api_error_message"] = api_error_message

    # exit_code (from the typed exception when available, else inspect).
    inspect_attrs: dict[str, Any] | None = None
    try:
        inspect_attrs = live.manager.inspect(live.handle)
    except Exception as exc:
        logger.warning("forensic: inspect failed for %s: %s", live.agent_name, exc)

    if exit_code_hint is not None:
        fields["exit_code"] = exit_code_hint
    elif isinstance(inspect_attrs, dict):
        state = inspect_attrs.get("State", {}) or {}
        if "ExitCode" in state:
            fields["exit_code"] = state["ExitCode"]

    if isinstance(inspect_attrs, dict):
        state = inspect_attrs.get("State", {}) or {}
        if "OOMKilled" in state:
            fields["oom_killed"] = state["OOMKilled"]

    # memory.peak (cgroup-v2). Read via exec_run + cat — sysfs pseudo-files
    # do not tar-serialize, so ``read_file_from_container`` returns None.
    peak_raw = _read_cgroup_text(live, "/sys/fs/cgroup/memory.peak")
    if peak_raw is not None and peak_raw.strip():
        try:
            fields["memory_peak_bytes"] = int(peak_raw.strip())
        except ValueError as exc:
            logger.warning(
                "forensic: memory.peak unparseable for %s: %r (%s)",
                live.agent_name,
                peak_raw,
                exc,
            )

    return fields


def _snapshot_container_artifacts(
    live: LiveContainer,
    run_dir: Any,
    agent_name: str,
    *,
    pause_on_failure: bool = False,
    run_id: str = "",
) -> None:
    """Persist container postmortem artifacts to the host.

    Each write is independently best-effort and must not propagate —
    writes are independent and none should mask the primary exception.

    Writes (under ``<run_dir>/<agent>/``):

    - ``container.log`` — full container stdout + stderr to date.
    - ``CLAUDE.md`` — merged role-instructions seen by the agent.
    - ``docker-inspect.json`` — container attrs at teardown.
    - ``cgroup-memory.txt`` — cgroup-v2 memory accounting snapshot.
    - ``inspect-container.sh`` — only when ``pause_on_failure`` and
      ``live.failed``; wraps ``docker exec`` for postmortem.
    """
    from agent_foundry.orchestration.artifacts import (
        agent_log_path,
        write_inspect_container_script,
    )

    agent_dir = run_dir / agent_name
    agent_dir.mkdir(parents=True, exist_ok=True)

    # --- inspect-container.sh (only when the container will be retained) ---
    # Written only when both conditions hold: pause_on_failure was enabled
    # AND this container's invocation failed. Otherwise the container will
    # be destroyed at teardown and the script would point at nothing.
    if pause_on_failure and live.failed:
        try:
            write_inspect_container_script(
                run_dir=run_dir,
                agent_name=agent_name,
                container_id=live.handle.container_id,
                run_id=run_id,
            )
        except Exception as exc:
            logger.warning(
                "failed to write inspect-container.sh for agent %s: %s",
                agent_name,
                exc,
            )

    # --- container.log ---
    # Routes through manager.read_logs so the docker-SDK shape stays
    # encapsulated inside ContainerManager. Fake managers return
    # b"" by default for handles they don't have logs scripted for.
    try:
        raw = live.manager.read_logs(live.handle, stdout=True, stderr=True, timestamps=False)
        if isinstance(raw, bytes):
            log_path = agent_log_path(run_dir, agent_name)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_bytes(raw)
    except Exception as exc:
        logger.warning(
            "failed to snapshot container.log for agent %s: %s",
            agent_name,
            exc,
        )

    # --- CLAUDE.md ---
    try:
        content = live.manager.read_file_from_container(
            live.handle, "/home/claude/.claude/CLAUDE.md"
        )
        if isinstance(content, str):
            (agent_dir / "CLAUDE.md").write_text(content, encoding="utf-8")
    except Exception as exc:
        logger.warning(
            "failed to snapshot CLAUDE.md for agent %s: %s",
            agent_name,
            exc,
        )

    # --- docker-inspect.json ---
    try:
        attrs = live.manager.inspect(live.handle)
        (agent_dir / "docker-inspect.json").write_text(
            json.dumps(attrs, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning(
            "failed to snapshot docker-inspect.json for agent %s: %s",
            agent_name,
            exc,
        )

    # --- cgroup-memory.txt ---
    # Each section is a path header followed by the file's content (or
    # "(unavailable)" if the read failed — happens on cgroup-v1 hosts,
    # in test fakes that don't script these reads, or when the container
    # is no longer reachable).
    try:
        sections: list[str] = []
        for cgroup_path in _CGROUP_MEMORY_FILES:
            content = _read_cgroup_text(live, cgroup_path)
            body = content if content else "(unavailable)"
            sections.append(f"=== {cgroup_path} ===\n{body}\n")
        (agent_dir / "cgroup-memory.txt").write_text("\n".join(sections), encoding="utf-8")
    except Exception as exc:
        logger.warning(
            "failed to snapshot cgroup-memory.txt for agent %s: %s",
            agent_name,
            exc,
        )


def _verify_paths(
    manager: ContainerManagerBase,
    handle: ContainerHandleBase,
    payload_dict: dict[str, Any],
    specs: list[FilePathFieldSpec],
) -> list[str]:
    violations: list[str] = []
    for path, max_size in extract_paths(payload_dict, specs):
        content = manager.read_file_from_container(handle, path)
        if content is None:
            violations.append(f"{path}: missing")
            continue
        size = len(content.encode()) if isinstance(content, str) else len(content)
        if size > max_size:
            violations.append(f"{path}: oversized ({size} > {max_size})")
    return violations


def _build_correction_prompt(violations: list[str]) -> str:
    bullets = "\n".join(f"- {v}" for v in violations)
    return (
        "You declared these files in your structured output but they are "
        "missing or oversized:\n"
        f"{bullets}\n\n"
        "Please write them correctly (or reduce their size), then emit the "
        "structured output again."
    )


async def _snapshot_files(
    *,
    live: LiveContainer,
    run_ctx: RunContext,
    agent_name: str,
    turn_number: int,
    payload_dict: dict[str, Any],
    specs: list[FilePathFieldSpec],
) -> None:
    """Copy every AgentFilePath-marked field into the turn's collected_files.

    Failures are non-fatal — as planned, verification has already
    confirmed the file exists on the container, so a copy failure is
    logged and execution continues.
    """
    if not specs:
        return
    turn_dir = agent_turn_dir(run_ctx.artifacts_dir, agent_name, turn_number)
    target_root = turn_dir / "collected_files"
    target_root.mkdir(parents=True, exist_ok=True)
    from pathlib import Path as _Path

    for declared_path, _max in extract_paths(payload_dict, specs):
        target = target_root / _Path(declared_path).name
        try:
            ok = await asyncio.to_thread(
                live.manager.copy_from_container,
                live.handle,
                declared_path,
                target,
            )
            if not ok:
                logger.warning(
                    "failed to snapshot %s from container %s",
                    declared_path,
                    live.handle.container_id,
                )
        except Exception as exc:
            logger.warning(
                "error snapshotting %s from container %s: %s",
                declared_path,
                live.handle.container_id,
                exc,
            )


def _initial_resume_session_id(construct: AgentAction, live: LiveContainer) -> str | None:
    """Pick the resume session id for the first turn of this invocation.

    ``REUSE_RESUME`` threads a previously captured session id (if any)
    into ``claude --resume``. ``REUSE_NEW_SESSION`` always starts fresh.
    """
    if construct.reuse_policy == ContainerReusePolicy.REUSE_RESUME:
        return live.session_id
    return None


async def run_agent_in_container(
    *,
    construct: AgentAction,
    prompt: str,
    run_ctx: RunContext,
    run_turn: RunTurn | None = None,
    instructions: str | None = None,
) -> BaseModel:
    """Execute one invocation of an AgentAction in its container.

    Full inner-loop semantics — see module docstring for the event
    set and retry/responder/cancel bounds.

    The ``run_turn`` kwarg is the per-turn transport: a callable matching
    the signature of :func:`_run_claude_turn`. Passing ``None`` (the
    default) resolves to the current module-level ``_run_claude_turn``
    at call time — so tests that go through the compiler (where the
    kwarg cannot be threaded) can ``monkeypatch.setattr(container_executor,
    "_run_claude_turn", fake)`` and have it take effect.
    """
    if run_turn is None:
        run_turn = _run_claude_turn
    _input_type, output_type = get_type_args(construct)
    envelope_type = AgentTurnEnvelope[output_type]  # type: ignore[valid-type]
    schema = to_claude_code_schema(envelope_type)
    file_path_specs = walk_file_path_fields(output_type.model_json_schema())
    agent_name = _agent_name(construct)
    registry = run_ctx.container_registry
    lifecycle = run_ctx.lifecycle_writer

    # Acquire (or create) the per-construct live container.
    live = await registry.get_or_create(
        construct,
        lifecycle_writer=lifecycle,
        agent_name=agent_name,
        instructions=instructions,
        extra_env=run_ctx.extra_env,
        extra_volumes=run_ctx.extra_volumes,
    )

    # Invocation number: per-container counter stamped on the live
    # container for lifecycle tagging.
    invocation = live.next_invocation()

    lifecycle.append(
        LifecycleEvent.AGENT_INVOCATION_STARTED,
        agent_name=agent_name,
        invocation=invocation,
    )

    current_prompt = prompt
    current_resume: str | None = _initial_resume_session_id(construct, live)
    current_session_id: str | None = live.session_id
    turn_number = live.next_turn()
    responder_iterations = 0
    verification_attempts = 0

    try:
        while True:
            # Cooperative cancel between turns.
            if run_ctx.cancel_event.is_set():
                raise AgentFailedError(
                    reason="cancelled",
                    agent_name=agent_name,
                    invocation=invocation,
                )

            # Responder-loop safety cap.
            if responder_iterations > MAX_RESPONDER_ITERATIONS:
                raise AgentFailedError(
                    reason="responder loop exceeded max iterations",
                    agent_name=agent_name,
                    invocation=invocation,
                )

            lifecycle.append(
                LifecycleEvent.TURN_STARTED,
                agent_name=agent_name,
                invocation=invocation,
                turn=turn_number,
            )

            # Create the per-turn artifacts dir and persist the prompt
            # before the turn runs so a crash mid-turn still leaves a
            # readable trail.
            turn_dir = agent_turn_dir(run_ctx.artifacts_dir, agent_name, turn_number)
            try:
                (turn_dir / "prompt.txt").write_text(current_prompt, encoding="utf-8")
            except Exception:
                logger.warning("failed to persist prompt.txt for turn %s", turn_number)

            api_retry_attempt = 0
            while True:
                try:
                    result = await run_turn(
                        live,
                        prompt=current_prompt,
                        resume_session_id=current_resume,
                        schema=schema,
                        model=construct.model,
                        effort=construct.effort,
                        skip_permissions=construct.skip_permissions,
                        cwd=construct.cwd,
                    )
                    break
                except AgentExecFailedError as exec_err:
                    # Retry on (a) explicit transient HTTP statuses from
                    # the upstream API, or (b) transport-class failures
                    # where claude reported an error but never got an
                    # HTTP response (api_error_status is None but the
                    # process produced an error message — TLS handshake,
                    # DNS, connection-refused, etc).
                    transport_error = exec_err.api_error_status is None and bool(
                        exec_err.api_error_message
                    )
                    retryable = (
                        exec_err.api_error_status is not None
                        and exec_err.api_error_status in _RETRYABLE_API_STATUSES
                    ) or transport_error
                    if retryable and api_retry_attempt < _MAX_TURN_API_RETRIES:
                        api_retry_attempt += 1
                        # Persist the pre-retry stream so the postmortem
                        # trail isn't lost when the next attempt succeeds.
                        try:
                            body = exec_err.output
                            if len(body) > _FAILED_TURN_STREAM_MAX_BYTES:
                                body = (
                                    body[:_FAILED_TURN_STREAM_MAX_BYTES]
                                    + _FAILED_TURN_TRUNCATION_MARKER
                                )
                            pre_retry_path = (
                                turn_dir / f"stream.before-api-retry.{api_retry_attempt}.jsonl"
                            )
                            pre_retry_path.write_bytes(body)
                        except Exception:
                            logger.warning(
                                "failed to persist stream.before-api-retry.%d.jsonl for turn %s",
                                api_retry_attempt,
                                turn_number,
                            )
                        lifecycle.append(
                            LifecycleEvent.TURN_API_RETRIED,
                            agent_name=agent_name,
                            invocation=invocation,
                            turn=turn_number,
                            attempt=api_retry_attempt,
                            api_error_status=exec_err.api_error_status,
                            num_turns=exec_err.num_turns,
                            api_error_message=exec_err.api_error_message,
                        )
                        logger.warning(
                            "retrying turn after api_error_status=%s (attempt %d/%d)",
                            exec_err.api_error_status,
                            api_retry_attempt,
                            _MAX_TURN_API_RETRIES,
                        )
                        await asyncio.sleep(_TURN_API_RETRY_SLEEP_SECONDS)
                        continue
                    # Final failure: persist the raw output to stream.jsonl
                    # before the exception propagates so the failed turn has
                    # the same on-disk artifact a successful turn would
                    # (capped at _FAILED_TURN_STREAM_MAX_BYTES; pathological
                    # outputs get marked, not dropped).
                    try:
                        body = exec_err.output
                        if len(body) > _FAILED_TURN_STREAM_MAX_BYTES:
                            body = (
                                body[:_FAILED_TURN_STREAM_MAX_BYTES]
                                + _FAILED_TURN_TRUNCATION_MARKER
                            )
                        (turn_dir / "stream.jsonl").write_bytes(body)
                    except Exception:
                        logger.warning(
                            "failed to persist stream.jsonl for failed turn %s",
                            turn_number,
                        )
                    raise

            # Tee the raw stream regardless of outcome so every RunTurn
            # implementation gets stderr + stream.jsonl persistence for
            # free by populating result.raw_output. Stdout is already
            # used by StdinResponder for interactive prompts.
            sys.stderr.write(result.raw_output.decode(errors="replace"))
            sys.stderr.flush()
            try:
                (turn_dir / "stream.jsonl").write_bytes(result.raw_output)
            except Exception:
                logger.warning("failed to persist stream.jsonl for turn %s", turn_number)

            # Persist the raw envelope payload as soon as we have it,
            # regardless of outcome.
            try:
                import json as _json

                (turn_dir / "envelope.json").write_text(
                    _json.dumps(result.envelope, default=str, indent=2), encoding="utf-8"
                )
            except Exception:
                logger.warning("failed to persist envelope.json for turn %s", turn_number)

            # Capture and record the session id as soon as we have one —
            # regardless of envelope outcome — so REUSE_RESUME continuations
            # (within and across invocations) have something to thread.
            if result.session_id:
                current_session_id = result.session_id
                if live.session_id != result.session_id:
                    registry.record_session_id(construct, result.session_id)

            try:
                envelope = envelope_type.model_validate(result.envelope)
            except ValidationError as exc:
                raise AgentFailedError(
                    reason=f"payload validation failed: {exc}",
                    agent_name=agent_name,
                    invocation=invocation,
                ) from exc

            outcome = envelope.outcome

            lifecycle.append(
                LifecycleEvent.TURN_COMPLETED,
                agent_name=agent_name,
                invocation=invocation,
                turn=turn_number,
                outcome_kind=str(outcome.kind),
            )

            if outcome.kind == TurnOutcomeKind.FAILED:
                lifecycle.append(
                    LifecycleEvent.AGENT_INVOCATION_FAILED,
                    agent_name=agent_name,
                    invocation=invocation,
                    reason=outcome.reason,
                )
                raise AgentFailedError(
                    reason=outcome.reason,
                    agent_name=agent_name,
                    invocation=invocation,
                )

            if outcome.kind == TurnOutcomeKind.SUCCESS:
                payload = outcome.payload
                payload_dict = (
                    payload.model_dump() if isinstance(payload, BaseModel) else dict(payload)
                )

                # Host-side file-path verification with one bounded retry.
                violations: list[str] = []
                if file_path_specs:
                    violations = _verify_paths(
                        live.manager, live.handle, payload_dict, file_path_specs
                    )

                if violations:
                    if verification_attempts >= 1:
                        lifecycle.append(
                            LifecycleEvent.AGENT_INVOCATION_FAILED,
                            agent_name=agent_name,
                            invocation=invocation,
                            reason=f"file_path_verification_failed: {violations}",
                        )
                        raise AgentFailedError(
                            reason=f"file_path_verification_failed: {violations}",
                            agent_name=agent_name,
                            invocation=invocation,
                        )
                    verification_attempts += 1
                    current_prompt = _build_correction_prompt(violations)
                    current_resume = current_session_id
                    turn_number = live.next_turn()
                    continue

                # Persist the success payload as output.json.
                try:
                    import json as _json

                    (turn_dir / "output.json").write_text(
                        _json.dumps(payload_dict, default=str, indent=2),
                        encoding="utf-8",
                    )
                except Exception:
                    logger.warning("failed to persist output.json for turn %s", turn_number)

                # Success path: snapshot declared files then return.
                await _snapshot_files(
                    live=live,
                    run_ctx=run_ctx,
                    agent_name=agent_name,
                    turn_number=turn_number,
                    payload_dict=payload_dict,
                    specs=file_path_specs,
                )
                usage_fields: dict[str, Any] = {}
                if result.usage is not None:
                    usage_fields["usage"] = result.usage.model_dump()
                if result.total_cost_usd is not None:
                    usage_fields["total_cost_usd"] = result.total_cost_usd
                if result.num_turns is not None:
                    usage_fields["num_turns"] = result.num_turns
                lifecycle.append(
                    LifecycleEvent.AGENT_INVOCATION_COMPLETED,
                    agent_name=agent_name,
                    invocation=invocation,
                    **usage_fields,
                )
                if isinstance(payload, output_type):
                    return payload
                return output_type.model_validate(payload_dict)

            # Clarification / permission → responder round-trip.
            if outcome.kind in (
                TurnOutcomeKind.CLARIFICATION_NEEDED,
                TurnOutcomeKind.PERMISSION_NEEDED,
            ):
                provider = run_ctx.responder_provider
                if provider is None:
                    raise AgentFailedError(
                        reason=(
                            "responder required for "
                            f"{outcome.kind} outcome but run_ctx.responder_provider is None"
                        ),
                        agent_name=agent_name,
                        invocation=invocation,
                    )
                # ``outcome`` is already a ClarificationOutcome or
                # PermissionOutcome instance (discriminated union).
                assert isinstance(outcome, (ClarificationOutcome, PermissionOutcome))
                request = build_request_from_outcome(
                    outcome,
                    agent_name=agent_name,
                    invocation=invocation,
                    turn=turn_number,
                )
                responder_context = ResponderContext(
                    run_id=run_ctx.run_id,
                    request_id=uuid.uuid4().hex,
                    agent_name=agent_name,
                    invocation=invocation,
                    turn=turn_number,
                )
                lifecycle.append(
                    LifecycleEvent.RESPONDER_REQUESTED,
                    agent_name=agent_name,
                    invocation=invocation,
                    turn=turn_number,
                    request_id=responder_context.request_id,
                    kind=str(outcome.kind),
                )
                try:
                    responder = provider()
                    response = await responder.respond(request, responder_context)
                except AgentFailedError:
                    raise
                except Exception as exc:
                    lifecycle.append(
                        LifecycleEvent.AGENT_INVOCATION_FAILED,
                        agent_name=agent_name,
                        invocation=invocation,
                        reason=f"responder failed: {exc}",
                    )
                    raise AgentFailedError(
                        reason=f"responder failed: {exc}",
                        agent_name=agent_name,
                        invocation=invocation,
                    ) from exc

                lifecycle.append(
                    LifecycleEvent.RESPONDER_ANSWERED,
                    agent_name=agent_name,
                    invocation=invocation,
                    turn=turn_number,
                    request_id=responder_context.request_id,
                )

                current_prompt = response.answer
                current_resume = current_session_id
                turn_number = live.next_turn()
                responder_iterations += 1
                continue

            # Defensive: unreachable given the StrEnum covers all cases.
            raise AgentFailedError(
                reason=f"unhandled outcome kind: {outcome.kind}",
                agent_name=agent_name,
                invocation=invocation,
            )
    except AgentFailedError:
        # Already logged above at the point of raise. Mark the live
        # container failed so an outer ``shutdown_all(pause_on_failure=True)``
        # can retain it for postmortem inspection.
        live.failed = True
        raise
    except Exception as exc:
        # Mark the container failed (see above) before doing the
        # best-effort forensic capture.
        live.failed = True
        # Best-effort: capture structured forensic fields (exit_code,
        # oom_killed, memory_peak_bytes, plus api_error_* when claude
        # itself reported the failure) for the lifecycle event so common
        # dispatch on the cause is a one-line check rather than parsing
        # the reason string. ``reason`` stays for the long tail.
        if isinstance(exc, AgentExecFailedError):
            forensic_fields = _capture_forensic_fields(
                live,
                exit_code_hint=exc.exit_code,
                api_error_status=exc.api_error_status,
                num_turns=exc.num_turns,
                api_error_message=exc.api_error_message,
            )
        else:
            forensic_fields = _capture_forensic_fields(live)
        lifecycle.append(
            LifecycleEvent.AGENT_INVOCATION_FAILED,
            agent_name=agent_name,
            invocation=invocation,
            reason=str(exc),
            **forensic_fields,
        )
        raise AgentFailedError(
            reason=str(exc),
            agent_name=agent_name,
            invocation=invocation,
        ) from exc
    finally:
        # Best-effort snapshot of the container's logs + rendered
        # CLAUDE.md into the run's artifacts dir. Runs after every
        # invocation — success, failure, or cancellation — so a
        # postmortem always has both artifacts available even if the
        # agent crashed. The container filesystem is ephemeral; this
        # is the only durable record.
        _snapshot_container_artifacts(
            live,
            run_ctx.artifacts_dir,
            agent_name,
            pause_on_failure=run_ctx.pause_on_failure,
            run_id=run_ctx.run_id,
        )
