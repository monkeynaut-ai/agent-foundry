"""Wire-stable lifecycle event type constants.

The ``LifecycleEvent`` ``StrEnum`` defines the canonical ``type`` values
emitted into ``artifacts/<run_id>/lifecycle.jsonl``. These constants are
part of the artifact contract: downstream tools (bundles, replayers,
dashboards) parse these strings verbatim, so the values must remain
stable across releases. When adding a new event type, pick a name and
leave it alone — treat the string as a wire format, not an internal
identifier.
"""

from enum import StrEnum


class LifecycleEvent(StrEnum):
    """Stable wire constants for the lifecycle.jsonl event stream."""

    RUN_STARTED = "run_started"
    RUN_ENDED = "run_ended"
    RUN_FAILED = "run_failed"
    AGENT_CONTAINER_STARTED = "agent_container_started"
    AGENT_INVOCATION_STARTED = "agent_invocation_started"
    AGENT_INVOCATION_COMPLETED = "agent_invocation_completed"
    AGENT_INVOCATION_FAILED = "agent_invocation_failed"
    TURN_STARTED = "turn_started"
    TURN_COMPLETED = "turn_completed"
    TURN_API_RETRIED = "turn_api_retried"
    RESPONDER_REQUESTED = "responder_requested"
    RESPONDER_ANSWERED = "responder_answered"
    FUNCTION_ACTION_STARTED = "function_action_started"
    FUNCTION_ACTION_COMPLETED = "function_action_completed"
    FUNCTION_ACTION_FAILED = "function_action_failed"
    AI_CALL_STARTED = "ai_call_started"
    AI_CALL_COMPLETED = "ai_call_completed"
    AI_CALL_FAILED = "ai_call_failed"
    RETRY_ATTEMPT_FAILED = "retry_attempt_failed"
    RETRY_ATTEMPT_COMPLETED = "retry_attempt_completed"
    RESOLVER_DISPOSITION = "resolver_disposition"
    GATE_ENTERED = "gate_entered"
    GATE_RESUMED = "gate_resumed"
    DOMAIN = "domain"
