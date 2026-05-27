from pydantic import BaseModel

from agent_foundry.observability.models import AgentTurnRecord, TokenUsage
from agent_foundry.observability.store import ObservabilityStore


def _aggregate_tokens(records: list[AgentTurnRecord]) -> TokenUsage:
    def _agg(values: list[int | None]) -> int | None:
        non_none = [v for v in values if v is not None]
        return sum(non_none) if non_none else None

    return TokenUsage(
        input_tokens=_agg([r.tokens.input_tokens for r in records]),
        output_tokens=_agg([r.tokens.output_tokens for r in records]),
        cache_read_tokens=_agg([r.tokens.cache_read_tokens for r in records]),
        cache_write_tokens=_agg([r.tokens.cache_write_tokens for r in records]),
    )


def _merge_tool_calls(records: list[AgentTurnRecord]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for r in records:
        for tool, count in r.tool_calls_by_tool.items():
            merged[tool] = merged.get(tool, 0) + count
    return merged


class AgentSummary(BaseModel):
    agent_name: str
    turn_count: int
    total_duration_s: float
    tool_calls_by_tool: dict[str, int]
    tokens: TokenUsage
    terminal_outcome: str


class RunSummary(BaseModel):
    total_duration_s: float
    turn_count: int
    tool_calls_by_tool: dict[str, int]
    tokens: TokenUsage
    agents: list[AgentSummary]


def summarize_run(store: ObservabilityStore) -> RunSummary:
    records = list(store.iter_records())

    by_agent: dict[str, list[AgentTurnRecord]] = {}
    for r in records:
        by_agent.setdefault(r.agent_name, []).append(r)

    agents: list[AgentSummary] = []
    for agent_name in sorted(by_agent):
        agent_records = by_agent[agent_name]
        last_turn = max(agent_records, key=lambda r: r.turn_index)
        agents.append(
            AgentSummary(
                agent_name=agent_name,
                turn_count=len(agent_records),
                total_duration_s=sum(r.duration_s for r in agent_records),
                tool_calls_by_tool=_merge_tool_calls(agent_records),
                tokens=_aggregate_tokens(agent_records),
                terminal_outcome=last_turn.outcome_kind,
            )
        )

    return RunSummary(
        total_duration_s=sum((r.duration_s for r in records), 0.0),
        turn_count=len(records),
        tool_calls_by_tool=_merge_tool_calls(records),
        tokens=_aggregate_tokens(records),
        agents=agents,
    )
