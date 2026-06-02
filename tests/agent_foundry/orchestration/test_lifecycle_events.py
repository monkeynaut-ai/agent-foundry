"""Tests for the LifecycleEvent StrEnum.

Stable wire constants for event names emitted by the executor, registry,
and compiler nodes into ``lifecycle.jsonl``.
"""

from __future__ import annotations

from enum import StrEnum

from agent_foundry.orchestration.lifecycle_events import LifecycleEvent

EXPECTED_MEMBERS = {
    "RUN_STARTED",
    "RUN_ENDED",
    "RUN_FAILED",
    "RUN_ABORTED",
    "AGENT_CONTAINER_STARTED",
    "AGENT_INVOCATION_STARTED",
    "AGENT_INVOCATION_COMPLETED",
    "AGENT_INVOCATION_FAILED",
    "TURN_STARTED",
    "TURN_COMPLETED",
    "TURN_API_RETRIED",
    "RESPONDER_REQUESTED",
    "RESPONDER_ANSWERED",
    "FUNCTION_ACTION_STARTED",
    "FUNCTION_ACTION_COMPLETED",
    "FUNCTION_ACTION_FAILED",
    "AI_CALL_STARTED",
    "AI_CALL_COMPLETED",
    "AI_CALL_FAILED",
    "RETRY_ATTEMPT_PASSED",
    "RETRY_ATTEMPT_NOT_PASSED",
    "RETRY_ATTEMPT_ERRORED",
    "RESOLVER_DISPOSITION",
    "GATE_ENTERED",
    "GATE_RESUMED",
    "DOMAIN",
}


def test_lifecycle_event_is_strenum() -> None:
    assert issubclass(LifecycleEvent, StrEnum)


def test_lifecycle_event_values_are_lowercased_member_names() -> None:
    for name in EXPECTED_MEMBERS:
        member = LifecycleEvent[name]
        assert member.value == name.lower(), (
            f"LifecycleEvent.{name}.value must equal {name.lower()!r}, got {member.value!r}"
        )


def test_lifecycle_event_member_set_is_exact() -> None:
    actual = {member.name for member in LifecycleEvent}
    assert actual == EXPECTED_MEMBERS


def test_run_aborted_event_value() -> None:
    assert LifecycleEvent.RUN_ABORTED.value == "run_aborted"
