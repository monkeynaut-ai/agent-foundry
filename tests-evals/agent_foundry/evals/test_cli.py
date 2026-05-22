"""Tests for ``agent_foundry.evals.cli``."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_foundry.evals.cli import (
    MissingTargetArgsError,
    SuiteLoadError,
    build_task_for_suite,
    load_suite,
    parse_args,
)
from agent_foundry.evals.models import EvalSuite

_AGENT_SUITE_MODULE = '''
"""Minimal agent eval suite for CLI tests."""

from pydantic import BaseModel
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import EqualsExpected

from agent_foundry.evals.models import AgentTarget, EvalSuite
from agent_foundry.primitives.models import AgentAction, ContainerReusePolicy


class _Input(BaseModel):
    text: str


class _Output(BaseModel):
    result: str


def _stub_executor(*, primitive, prompt, instructions, run_ctx):
    return _Output(result="")


_agent = AgentAction[_Input, _Output](
    name="test_agent",
    prompt_builder=lambda inp: inp.text,
    instructions_provider=lambda inp: "do the thing",
    executor=_stub_executor,
    reuse_policy=ContainerReusePolicy.REUSE_RESUME,
    model="claude-sonnet-4-6",
)

suite = EvalSuite(
    name="loaded_suite",
    target=AgentTarget(agent=_agent),
    dataset=Dataset[_Input, _Output, None](
        name="ds",
        cases=[Case(name="c1", inputs=_Input(text="a"), expected_output=_Output(result="A"))],
        evaluators=[EqualsExpected()],
    ),
    invocations_per_case=1,
)
'''


_AI_CALL_SUITE_MODULE = '''
"""Minimal AICall eval suite for CLI tests."""

from pydantic import BaseModel
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import EqualsExpected

from agent_foundry.ai_models.inference import InferenceParameters
from agent_foundry.ai_models.model import ModelCapabilities, ModelEntry
from agent_foundry.evals.models import AICallTarget, EvalSuite
from agent_foundry.primitives.ai_call import AICall, ModelInput


class _Input(BaseModel):
    text: str


class _Output(BaseModel):
    result: str


_entry = ModelEntry(
    model_id="fake",
    provider=object(),
    capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
)

_call = AICall[_Input, _Output](
    model_input=ModelInput[_Input](instructions="i", prompt="p"),
    parameters=InferenceParameters(max_tokens=128),
    model=_entry,
)

suite = EvalSuite(
    name="ai_call_loaded_suite",
    target=AICallTarget(ai_call=_call),
    dataset=Dataset[_Input, _Output, None](
        name="ds",
        cases=[Case(name="c1", inputs=_Input(text="a"), expected_output=_Output(result="A"))],
        evaluators=[EqualsExpected()],
    ),
    invocations_per_case=1,
)
'''


def test_load_suite_returns_eval_suite(tmp_path: Path) -> None:
    """load_suite imports the module and returns its 'suite' symbol."""
    suite_file = tmp_path / "my_suite.py"
    suite_file.write_text(_AGENT_SUITE_MODULE)
    suite = load_suite(suite_file)
    assert isinstance(suite, EvalSuite)
    assert suite.name == "loaded_suite"


def test_load_suite_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(SuiteLoadError) as exc_info:
        load_suite(tmp_path / "nope.py")
    assert "not found" in str(exc_info.value).lower()


def test_load_suite_missing_suite_symbol_raises(tmp_path: Path) -> None:
    """Module must export a 'suite' symbol."""
    no_symbol = tmp_path / "no_symbol.py"
    no_symbol.write_text("x = 1\n")
    with pytest.raises(SuiteLoadError) as exc_info:
        load_suite(no_symbol)
    assert "suite" in str(exc_info.value).lower()


def test_load_suite_wrong_type_raises(tmp_path: Path) -> None:
    """'suite' must be an EvalSuite instance."""
    wrong = tmp_path / "wrong.py"
    wrong.write_text("suite = 'not an EvalSuite'\n")
    with pytest.raises(SuiteLoadError) as exc_info:
        load_suite(wrong)
    assert "evalsuite" in str(exc_info.value).lower()


# --- argument parsing ---


def test_parse_args_minimal_for_agent_target() -> None:
    args = parse_args(
        [
            "evals/agent_a/suite.py",
            "--artifacts-dir",
            "/tmp/artifacts",
            "--workspace-volume",
            "vol",
            "--base-image-tag",
            "agent-worker:latest",
        ]
    )
    assert args.suite_path == Path("evals/agent_a/suite.py")
    assert args.artifacts_dir == Path("/tmp/artifacts")
    assert args.workspace_volume == "vol"
    assert args.base_image_tag == "agent-worker:latest"
    # Defaults.
    assert args.out_dir == Path("evals/runs")
    assert args.max_concurrency == 1
    assert args.invocations is None


def test_parse_args_container_args_optional_for_ai_call_target() -> None:
    """Container args are optional at the parser level; the dispatch
    layer enforces them per target kind."""
    args = parse_args(["evals/foo/suite.py"])
    assert args.suite_path == Path("evals/foo/suite.py")
    assert args.artifacts_dir is None
    assert args.workspace_volume is None
    assert args.base_image_tag is None


def test_parse_args_invocations_override() -> None:
    args = parse_args(
        [
            "evals/agent_a/suite.py",
            "--invocations",
            "5",
        ]
    )
    assert args.invocations == 5


def test_parse_args_max_concurrency_override() -> None:
    args = parse_args(
        [
            "evals/agent_a/suite.py",
            "--max-concurrency",
            "10",
        ]
    )
    assert args.max_concurrency == 10


def test_parse_args_out_dir_override() -> None:
    args = parse_args(
        [
            "evals/agent_a/suite.py",
            "--out-dir",
            "custom/path",
        ]
    )
    assert args.out_dir == Path("custom/path")


# --- build_task_for_suite dispatch ---


def test_build_task_for_suite_agent_target_requires_container_args(tmp_path: Path) -> None:
    suite_file = tmp_path / "agent_suite.py"
    suite_file.write_text(_AGENT_SUITE_MODULE)
    suite = load_suite(suite_file)
    args = parse_args([str(suite_file)])

    with pytest.raises(MissingTargetArgsError) as exc_info:
        build_task_for_suite(suite, args)
    assert "--artifacts-dir" in str(exc_info.value)
    assert "--workspace-volume" in str(exc_info.value)
    assert "--base-image-tag" in str(exc_info.value)


def test_build_task_for_suite_agent_target_with_container_args(tmp_path: Path) -> None:
    suite_file = tmp_path / "agent_suite.py"
    suite_file.write_text(_AGENT_SUITE_MODULE)
    suite = load_suite(suite_file)
    args = parse_args(
        [
            str(suite_file),
            "--artifacts-dir",
            "/tmp/a",
            "--workspace-volume",
            "v",
            "--base-image-tag",
            "t",
        ]
    )

    task = build_task_for_suite(suite, args)
    assert callable(task)


def test_build_task_for_suite_ai_call_target_ignores_container_args(tmp_path: Path) -> None:
    suite_file = tmp_path / "ai_call_suite.py"
    suite_file.write_text(_AI_CALL_SUITE_MODULE)
    suite = load_suite(suite_file)
    args = parse_args([str(suite_file)])  # No container args needed.

    task = build_task_for_suite(suite, args)
    assert callable(task)
