"""Claude Code model constants and discovery for use in AgentAction declarations."""

from enum import StrEnum

import anthropic


class ClaudeModel(StrEnum):
    """Hardcoded Claude model identifiers for the Claude Code executor.

    Values are passed directly to the ``claude --model`` flag.
    Use ``list_claude_models()`` to fetch the live list from the Anthropic API.
    """

    OPUS_4_7 = "claude-opus-4-7"
    SONNET_4_6 = "claude-sonnet-4-6"
    OPUS_4_6 = "claude-opus-4-6"
    OPUS_4_5 = "claude-opus-4-5-20251101"
    HAIKU_4_5 = "claude-haiku-4-5-20251001"
    SONNET_4_5 = "claude-sonnet-4-5-20250929"
    OPUS_4_1 = "claude-opus-4-1-20250805"
    OPUS_4 = "claude-opus-4-20250514"
    SONNET_4 = "claude-sonnet-4-20250514"


def list_claude_models() -> list[str]:
    """Return all Claude model IDs currently available via the Anthropic API.

    Requires ``ANTHROPIC_API_KEY`` in the environment.
    """
    client = anthropic.Anthropic()
    return [m.id for m in client.models.list()]
