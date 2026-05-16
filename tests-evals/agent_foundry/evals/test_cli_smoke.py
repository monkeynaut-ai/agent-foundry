"""End-to-end smoke test of the eval CLI.

Exercises the full ``main()`` flow — argument parsing, suite loading,
runner invocation, report rendering, persistence — with the agent
invocation stubbed so the test runs without Docker or Claude Code.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from agent_foundry.evals import cli as cli_module
from agent_foundry.primitives.models import AgentAction

_SUITE_MODULE = '''
"""Minimal suite for CLI smoke test."""

from pydantic import BaseModel
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import EqualsExpected

from agent_foundry.evals.models import EvalSuite
from agent_foundry.primitives.models import AgentAction, ContainerReusePolicy


class SmokeInput(BaseModel):
    text: str


class SmokeOutput(BaseModel):
    result: str


def _stub_executor(*, primitive, prompt, instructions, run_ctx):
    return SmokeOutput(result="")


_agent = AgentAction[SmokeInput, SmokeOutput](
    name="smoke_agent",
    prompt_builder=lambda inp: inp.text,
    instructions_provider=lambda inp: "do the thing",
    executor=_stub_executor,
    reuse_policy=ContainerReusePolicy.REUSE_RESUME,
    model="claude-sonnet-4-6",
)

suite = EvalSuite(
    name="smoke_suite",
    agent=_agent,
    dataset=Dataset[SmokeInput, SmokeOutput, None](
        name="smoke_ds",
        cases=[
            Case(name="upper_a", inputs=SmokeInput(text="a"), expected_output=SmokeOutput(result="A")),
            Case(name="upper_b", inputs=SmokeInput(text="b"), expected_output=SmokeOutput(result="B")),
        ],
        evaluators=[EqualsExpected()],
    ),
    invocations_per_case=2,
)
'''


def test_cli_smoke_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """main() loads the suite, runs it, writes report.json, exits 0."""
    suite_file = tmp_path / "smoke_suite.py"
    suite_file.write_text(_SUITE_MODULE)

    # Stub agent invocation. The fake task returns the expected output
    # uppercased, matching the dataset's expected outputs.
    def fake_build_task(
        agent: AgentAction, **_kwargs: Any
    ) -> Callable[[Any], Awaitable[BaseModel]]:
        # Pull the agent's declared output type off its generic args so
        # this fake works for any AgentAction shape with a {"result": str}
        # output schema.
        from agent_foundry.primitives.models import get_type_args

        _input_type, output_type = get_type_args(agent)

        async def task(input_state: BaseModel) -> BaseModel:
            text = input_state.text  # type: ignore[attr-defined]
            return output_type.model_validate({"result": text.upper()})

        return task

    monkeypatch.setattr(cli_module, "build_run_primitive_plan_task", fake_build_task)

    out_dir = tmp_path / "runs"
    exit_code = cli_module.main(
        [
            str(suite_file),
            "--artifacts-dir",
            str(tmp_path / "artifacts"),
            "--workspace-volume",
            "test-vol",
            "--base-image-tag",
            "test-image:latest",
            "--out-dir",
            str(out_dir),
            "--invocations",
            "2",
        ]
    )

    assert exit_code == 0

    # report.json was written under out_dir/<run_id>/
    run_dirs = list(out_dir.iterdir())
    assert len(run_dirs) == 1
    report_path = run_dirs[0] / "report.json"
    assert report_path.is_file()

    data = json.loads(report_path.read_text())
    assert data["suite_name"] == "smoke_suite"
    assert data["invocations_per_case"] == 2
    # 2 cases x 2 invocations = 4 entries.
    assert len(data["report"]["cases"]) == 4

    # Console output shows the report's evaluation summary.
    captured = capsys.readouterr()
    assert "Report written to" in captured.out
