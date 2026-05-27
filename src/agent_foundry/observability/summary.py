import argparse
import sys
from pathlib import Path

from pydantic import BaseModel

from agent_foundry.observability.models import AgentTurnRecord, TokenUsage
from agent_foundry.observability.store import JsonlObservabilityStore, ObservabilityStore


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


def _fmt_int(v: int | None) -> str:
    return f"{v:,}" if v is not None else "N/A"


def _fmt_tool_calls(tool_calls: dict[str, int]) -> str:
    if not tool_calls:
        return "(none)"
    return ", ".join(f"{tool}={count:,}" for tool, count in sorted(tool_calls.items()))


def _print_summary(summary: RunSummary) -> None:
    t = summary.tokens
    print("Run Summary")
    print("===========")
    print(f"Total turns    : {summary.turn_count:,}")
    print(f"Total duration : {summary.total_duration_s:.1f}s")
    print()
    print("Tool calls")
    print("----------")
    if summary.tool_calls_by_tool:
        for tool, count in sorted(summary.tool_calls_by_tool.items()):
            print(f"{tool} : {count:,}")
    else:
        print("(none)")
    print()
    print("Token usage")
    print("-----------")
    print(f"Input        : {_fmt_int(t.input_tokens)}")
    print(f"Output       : {_fmt_int(t.output_tokens)}")
    print(f"Cache read   : {_fmt_int(t.cache_read_tokens)}")
    print(f"Cache write  : {_fmt_int(t.cache_write_tokens)}")
    print()
    print("Per-agent breakdown")
    print("-------------------")
    for agent in summary.agents:
        at = agent.tokens
        print(f"Agent: {agent.agent_name}")
        print(f"  Turns           : {agent.turn_count:,}")
        print(f"  Duration        : {agent.total_duration_s:.1f}s")
        print(f"  Terminal outcome: {agent.terminal_outcome}")
        print(f"  Tool calls      : {_fmt_tool_calls(agent.tool_calls_by_tool)}")
        print(
            f"  Tokens          : input={_fmt_int(at.input_tokens)}, "
            f"output={_fmt_int(at.output_tokens)}, "
            f"cache_read={_fmt_int(at.cache_read_tokens)}, "
            f"cache_write={_fmt_int(at.cache_write_tokens)}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize an Agent Foundry run")
    parser.add_argument("run_id", help="Run ID to summarize")
    parser.add_argument(
        "--artifacts-dir",
        default=".agent_foundry/artifacts",
        help="Path to artifacts directory (default: .agent_foundry/artifacts)",
    )
    args = parser.parse_args()

    observability_path = Path(args.artifacts_dir) / args.run_id / "observability.jsonl"
    if not observability_path.exists():
        print(
            f"Error: observability file not found: {observability_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    with JsonlObservabilityStore(path=observability_path) as store:
        summary = summarize_run(store)

    _print_summary(summary)


if __name__ == "__main__":
    main()
